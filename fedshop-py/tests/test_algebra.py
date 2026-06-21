"""Tests for algebra/rdflib_algebra.py — patches and round-trips."""

from rdflib.namespace import XSD
from rdflib.plugins.sparql.algebra import translateQuery, traverse
from rdflib.plugins.sparql.parser import parseQuery
from rdflib.term import Literal, URIRef

from fedshop.algebra.rdflib_algebra import (
    disable_orderby_limit,
    inject_constant_into_placeholders,
    translateAlgebra,
)

SIMPLE_SELECT = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?s ?p ?o
WHERE { ?s ?p ?o . }
LIMIT 5
"""

SELECT_WITH_FILTER = """
PREFIX bsbm: <http://www4.wiwiss.fu-berlin.de/bizer/bsbm/v01/vocabulary/>
SELECT DISTINCT ?product
WHERE {
    ?product bsbm:productFeature ?Feature .
    FILTER(?price < ?maxPrice)
}
"""


# ─── Patch 1: date literal handling ─────────────────────────────────────────

def test_inject_date_literal_yyyy_mm_dd():
    """YYYY-MM-DD strings should become XSD.date literals, not datetimes."""
    injection = {"dateVar": "2024-01-15"}
    algebra = parseQuery("SELECT ?s WHERE { ?s ?p ?dateVar . }")
    result = traverse(algebra, visitPost=lambda n: inject_constant_into_placeholders(n, injection))

    # Collect all literals from the traversal result
    def collect_literals(node, children):
        if isinstance(node, Literal):
            children.append([node])
        from itertools import chain
        return list(chain(*children))

    from rdflib.plugins.sparql.algebra import _traverseAgg
    literals = _traverseAgg(result, collect_literals)
    date_literals = [l for l in literals if l.datatype == XSD.date]
    assert len(date_literals) > 0, "Expected at least one XSD.date literal"
    assert str(date_literals[0]) == "2024-01-15"


def test_inject_uri_value():
    """URI strings should become URIRef nodes."""
    injection = {"ProductType": "http://www.example.com/types/Type1"}
    algebra = parseQuery("SELECT ?s WHERE { ?s a ?ProductType . }")
    result = traverse(algebra, visitPost=lambda n: inject_constant_into_placeholders(n, injection))

    def collect_urirefs(node, children):
        if isinstance(node, URIRef):
            children.append([node])
        from itertools import chain
        return list(chain(*children))

    from rdflib.plugins.sparql.algebra import _traverseAgg
    urirefs = _traverseAgg(result, collect_urirefs)
    matching = [u for u in urirefs if "Type1" in str(u)]
    assert len(matching) > 0


def test_inject_integer_value():
    """Integer strings should become integer Literals."""
    injection = {"price": "42"}
    algebra = parseQuery("SELECT ?s WHERE { ?s ?p ?price . }")
    result = traverse(algebra, visitPost=lambda n: inject_constant_into_placeholders(n, injection))

    def collect_literals(node, children):
        if isinstance(node, Literal):
            children.append([node])
        from itertools import chain
        return list(chain(*children))

    from rdflib.plugins.sparql.algebra import _traverseAgg
    literals = _traverseAgg(result, collect_literals)
    int_literals = [l for l in literals if l.toPython() == 42]
    assert len(int_literals) > 0


# ─── Patch 2: no WHERE keyword ──────────────────────────────────────────────

def test_translate_algebra_no_where_keyword():
    """translateAlgebra should not emit the WHERE keyword."""
    algebra = parseQuery(SIMPLE_SELECT)
    translated = translateQuery(algebra)
    result = translateAlgebra(translated)
    assert "WHERE" not in result


def test_translate_algebra_has_select():
    """translateAlgebra output should contain SELECT."""
    algebra = parseQuery(SIMPLE_SELECT)
    translated = translateQuery(algebra)
    result = translateAlgebra(translated)
    assert "SELECT" in result


# ─── Patch 3: StringIO (no file side-channel) ───────────────────────────────

def test_translate_algebra_roundtrip_simple_select():
    """A simple SELECT round-trips through algebra without creating query.txt."""
    import os
    before_files = set(os.listdir("."))

    algebra = parseQuery(SIMPLE_SELECT)
    translated = translateQuery(algebra)
    result = translateAlgebra(translated)

    after_files = set(os.listdir("."))
    assert "query.txt" not in after_files - before_files, "query.txt should not be created (patch 3)"
    assert result.strip()


def test_translate_algebra_parallel_safe(tmp_path):
    """Two concurrent translateAlgebra calls don't interfere (no shared file)."""
    import concurrent.futures

    def run(q):
        algebra = parseQuery(q)
        return translateAlgebra(translateQuery(algebra))

    queries = [
        "SELECT ?a WHERE { ?a ?b ?c . }",
        "SELECT ?x WHERE { ?x ?y ?z . }",
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        results = list(ex.map(run, queries))

    assert all(r.strip() for r in results)
    assert "?a" in results[0]
    assert "?x" in results[1]


# ─── disable_orderby_limit ──────────────────────────────────────────────────

def test_disable_orderby_removes_orderby_key():
    """disable_orderby_limit should remove orderby from CompValue nodes."""
    from rdflib.plugins.sparql.parserutils import CompValue
    node = CompValue("SelectQuery", orderby=["?x"], limitoffset=10)
    result = disable_orderby_limit(node)
    assert "orderby" not in result
    assert "limitoffset" not in result
