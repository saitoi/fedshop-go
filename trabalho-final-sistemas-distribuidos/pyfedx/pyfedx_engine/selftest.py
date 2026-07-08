"""Self-tests for the standalone PyFedX CLI."""

from __future__ import annotations

import os
import tempfile
import unittest
from typing import Dict, List, Tuple

from .artifacts import write_source_selection
from .executor import apply_order_by, anti_join, execute, hash_join_bindings, join_bindings, left_outer_join
from .filtering import eval_filter
from .federation import select_sources
from .model import Endpoint, RDF_TYPE, Triple
from .parser import parse_endpoints, parse_query
from .planner import order_triples

class FakeClient:
    def __init__(self):
        self.http_requests = 0
        self.planning_seconds = 0.0
        self.ask_responses: Dict[Tuple[str, str], bool] = {}
        self.select_responses: Dict[Tuple[str, str], List[Dict[str, str]]] = {}

    def ask(self, endpoint: Endpoint, query: str) -> bool:
        self.http_requests += 1
        for (eid, pat), val in self.ask_responses.items():
            if eid == endpoint.eid and pat in query:
                return val
        # Default: endpoint e1 has everything, e2 has "label"
        if "label" in query:
            return endpoint.eid in {"e1", "e2"}
        return endpoint.eid == "e1"

    def select(self, endpoint: Endpoint, query: str) -> List[Dict[str, str]]:
        self.http_requests += 1
        for (eid, pat), rows in self.select_responses.items():
            if eid == endpoint.eid and pat in query:
                return rows
        if "rdf-syntax-ns#type" in query and "label" in query:
            return [{"s": "p1", "label": "Phone"}]
        if "rdf-syntax-ns#type" in query:
            return [{"s": "p1"}, {"s": "p2"}]
        if endpoint.eid == "e1":
            return [{"s": "p1", "label": "Phone"}]
        return [{"s": "p2", "label": "Camera"}]


class SelfTests(unittest.TestCase):

    def test_parse_basic_query(self):
        query = parse_query(
            """PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT DISTINCT ?s ?label WHERE {
              ?s rdfs:label ?label .
              ?s a <http://example/Thing> .
            } LIMIT 3"""
        )
        self.assertTrue(query.distinct)
        self.assertEqual(query.select, ["s", "label"])
        self.assertEqual(query.limit, 3)
        self.assertEqual(len(query.group.triples), 2)
        self.assertEqual(
            query.group.triples[0],
            Triple("?s", "<http://www.w3.org/2000/01/rdf-schema#label>", "?label"),
        )
        self.assertEqual(query.group.triples[1].predicate, RDF_TYPE)

    def test_parse_semicolon_expansion(self):
        query = parse_query("SELECT ?s WHERE { ?s a <T> ; <p> ?o . }")
        self.assertEqual(
            query.group.triples,
            [Triple("?s", RDF_TYPE, "<T>"), Triple("?s", "<p>", "?o")],
        )

    def test_parse_filter(self):
        query = parse_query(
            "SELECT ?x WHERE { ?x <p> ?v . FILTER(?v > \"5\"^^<xsd:integer>) }"
        )
        self.assertEqual(len(query.group.filters), 1)
        self.assertEqual(len(query.group.triples), 1)

    def test_parse_optional(self):
        query = parse_query(
            "SELECT ?x ?y WHERE { ?x <p> ?v . OPTIONAL { ?x <q> ?y . } }"
        )
        self.assertEqual(len(query.group.triples), 1)
        self.assertEqual(len(query.group.optionals), 1)
        self.assertEqual(len(query.group.optionals[0].triples), 1)

    def test_parse_union(self):
        query = parse_query(
            "SELECT ?x WHERE { { ?x <p> ?v . } UNION { ?x <q> ?v . } }"
        )
        self.assertEqual(len(query.group.unions), 1)
        arm1, arm2 = query.group.unions[0]
        self.assertEqual(len(arm1.triples), 1)
        self.assertEqual(len(arm2.triples), 1)

    def test_parse_order_by(self):
        query = parse_query(
            "SELECT ?x WHERE { ?x <p> ?v . } ORDER BY ?x LIMIT 10"
        )
        self.assertEqual(query.order_by, (("x", True),))
        self.assertEqual(query.limit, 10)

    def test_parse_order_by_desc(self):
        query = parse_query(
            "SELECT ?x WHERE { ?x <p> ?v . } ORDER BY DESC(?x)"
        )
        self.assertEqual(query.order_by, (("x", False),))

    def test_join_bindings_keeps_compatible_rows(self):
        self.assertEqual(
            join_bindings(
                [{"s": "a", "x": "1"}, {"s": "b", "x": "2"}],
                [{"s": "a", "y": "3"}, {"s": "c", "y": "4"}],
            ),
            [{"s": "a", "x": "1", "y": "3"}],
        )

    def test_hash_join_matches_nested_loop(self):
        left = [{"s": "a", "x": "1"}, {"s": "b", "x": "2"}]
        right = [{"s": "a", "y": "3"}, {"s": "c", "y": "4"}]
        self.assertEqual(hash_join_bindings(left, right), join_bindings(left, right))

    def test_connected_planner_avoids_early_cartesian_when_possible(self):
        t_type_label = Triple("?ProductType", "<label>", "?ptLabel")
        t_feature_label = Triple("?ProductFeature1", "<label>", "?pfLabel")
        t_product_type = Triple("?product", "<type>", "?ProductType")
        t_product_feature = Triple("?product", "<feature>", "?ProductFeature1")
        source_map = {
            t_type_label: [Endpoint("e1", "u")],
            t_feature_label: [Endpoint("e1", "u")],
            t_product_type: [Endpoint("e1", "u"), Endpoint("e2", "u")],
            t_product_feature: [Endpoint("e1", "u"), Endpoint("e2", "u")],
        }
        ordered = order_triples(
            [t_type_label, t_feature_label, t_product_type, t_product_feature],
            source_map,
            "connected-source-count",
        )
        self.assertEqual(ordered[:2], [t_type_label, t_product_type])

    def test_left_outer_join_keeps_unmatched_left(self):
        result = left_outer_join(
            [{"x": "1"}, {"x": "2"}],
            [{"x": "1", "y": "A"}],
        )
        self.assertEqual(len(result), 2)
        matched = next(r for r in result if r["x"] == "1")
        self.assertEqual(matched["y"], "A")
        unmatched = next(r for r in result if r["x"] == "2")
        self.assertNotIn("y", unmatched)

    def test_left_outer_join_empty_right(self):
        left = [{"x": "1"}, {"x": "2"}]
        result = left_outer_join(left, [])
        self.assertEqual(result, [{"x": "1"}, {"x": "2"}])

    def test_anti_join_keeps_only_unmatched_left(self):
        result = anti_join(
            [{"x": "1"}, {"x": "2"}],
            [{"x": "1", "y": "A"}],
        )
        self.assertEqual(result, [{"x": "2"}])

    def test_filter_numeric_gt(self):
        self.assertTrue(eval_filter('?v > "5"^^<http://www.w3.org/2001/XMLSchema#integer>', {"v": "10"}))
        self.assertFalse(eval_filter('?v > "5"^^<http://www.w3.org/2001/XMLSchema#integer>', {"v": "3"}))

    def test_filter_and(self):
        expr = '?a > "1"^^<xsd:integer> && ?b < "10"^^<xsd:integer>'
        self.assertTrue(eval_filter(expr, {"a": "5", "b": "7"}))
        self.assertFalse(eval_filter(expr, {"a": "5", "b": "15"}))

    def test_filter_bound(self):
        self.assertTrue(eval_filter("BOUND(?x)", {"x": "something"}))
        self.assertFalse(eval_filter("BOUND(?x)", {"x": ""}))
        self.assertFalse(eval_filter("BOUND(?x)", {}))

    def test_filter_not_bound(self):
        self.assertTrue(eval_filter("!BOUND(?x)", {}))
        self.assertFalse(eval_filter("!BOUND(?x)", {"x": "val"}))

    def test_filter_regex(self):
        # SPARQL REGEX is case-sensitive by default
        self.assertTrue(eval_filter('REGEX(?label, "Phone")', {"label": "Smart Phone"}))
        self.assertFalse(eval_filter('REGEX(?label, "phone")', {"label": "Smart Phone"}))
        self.assertFalse(eval_filter('REGEX(?label, "tablet")', {"label": "Smart Phone"}))

    def test_filter_uri_neq_var(self):
        self.assertTrue(
            eval_filter(
                "<http://example.org/P1> != ?product",
                {"product": "<http://example.org/P2>"},
            )
        )
        self.assertFalse(
            eval_filter(
                "<http://example.org/P1> != ?product",
                {"product": "<http://example.org/P1>"},
            )
        )

    def test_filter_arithmetic(self):
        # ?sim < ?orig + 20
        expr = '?sim < ?orig + "20"^^<http://www.w3.org/2001/XMLSchema#integer>'
        self.assertTrue(eval_filter(expr, {"sim": "25", "orig": "10"}))
        self.assertFalse(eval_filter(expr, {"sim": "35", "orig": "10"}))

    def test_apply_order_by_ascending(self):
        rows = [{"x": "3"}, {"x": "1"}, {"x": "2"}]
        result = apply_order_by(rows, (("x", True),))
        self.assertEqual([r["x"] for r in result], ["1", "2", "3"])

    def test_apply_order_by_descending(self):
        rows = [{"x": "3"}, {"x": "1"}, {"x": "2"}]
        result = apply_order_by(rows, (("x", False),))
        self.assertEqual([r["x"] for r in result], ["3", "2", "1"])

    def test_source_selection_and_execution(self):
        query = parse_query(
            """PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT ?s ?label WHERE { ?s a <T> . ?s rdfs:label ?label . }"""
        )
        endpoints = [Endpoint("e1", "http://e1/sparql"), Endpoint("e2", "http://e2/sparql")]
        client = FakeClient()
        source_map, ask_count = select_sources(query, endpoints, client)
        rows = execute(query, source_map, client)
        self.assertEqual(ask_count, 4)
        self.assertEqual(rows, [{"s": "p1", "label": "Phone"}, {"s": "p2", "label": "Camera"}])

    def test_source_selection_with_optional(self):
        """OPTIONAL with no sources for ?y should preserve left rows."""
        query = parse_query(
            "SELECT ?x ?y WHERE { ?x <p> ?z . OPTIONAL { ?x <q> ?y . } }"
        )
        endpoints = [Endpoint("e1", "http://e1/sparql")]
        client = FakeClient()
        # Override: p is on e1, q is on no endpoint
        client.ask_responses = {("e1", "<p>"): True, ("e1", "<q>"): False}
        client.select_responses = {("e1", "<p>"): [{"x": "A", "z": "1"}]}
        source_map, _ = select_sources(query, endpoints, client)
        rows = execute(query, source_map, client)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["x"], "A")
        # Unbound OPTIONAL variable must be absent (not projected as empty string)
        self.assertNotIn("y", rows[0])

    def test_execute_union(self):
        """UNION should merge and deduplicate arms."""
        query = parse_query(
            "SELECT ?x WHERE { { ?x <p1> <V> . } UNION { ?x <p2> <V> . } }"
        )
        endpoints = [Endpoint("e1", "http://e1/sparql")]
        client = FakeClient()
        client.ask_responses = {("e1", "<p1>"): True, ("e1", "<p2>"): True}
        client.select_responses = {
            ("e1", "<p1>"): [{"x": "A"}, {"x": "B"}],
            ("e1", "<p2>"): [{"x": "B"}, {"x": "C"}],
        }
        source_map, _ = select_sources(query, endpoints, client)
        rows = execute(query, source_map, client)
        xs = {r["x"] for r in rows}
        self.assertEqual(xs, {"A", "B", "C"})

    def test_parse_endpoints(self):
        endpoints = parse_endpoints(
            "@prefix sd: <http://www.w3.org/ns/sparql-service-description#> .\n"
            '<http://vendor.example/> a sd:Service ; sd:endpoint "http://proxy/vendor" .'
        )
        self.assertEqual(endpoints, [Endpoint("http_vendor.example", "http://proxy/vendor")])

    def test_source_selection_output_no_trailing_dot(self):
        """write_source_selection must not include trailing '.' in triple column."""
        query = parse_query("SELECT ?x WHERE { ?x <p> ?y . }")
        triple = query.group.triples[0]
        ep = Endpoint("e1", "http://e1/sparql")
        source_map = {triple: [ep]}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            tmp = f.name
        try:
            write_source_selection(tmp, source_map, query.group)
            with open(tmp) as f:
                content = f.read()
            self.assertIn("?x <p> ?y", content)
            self.assertNotIn("?x <p> ?y .", content)
        finally:
            os.unlink(tmp)



def run_self_tests() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SelfTests)
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1

__all__ = ["FakeClient", "SelfTests", "run_self_tests"]
