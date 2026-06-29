from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


@pytest.mark.parametrize(
    ("query_name", "expected"),
    [
        ("q06", True),
        ("q07", False),
        ("q08", True),
        ("q09", True),
        ("q10", True),
        ("q11", True),
        ("q12", True),
    ],
)
def test_q06_to_q12_reference_scope(query_name, expected):
    from fedshop.query import _uses_source_local_reference

    assert _uses_source_local_reference(query_name) is expected


def test_q08_value_selection_keeps_relation_that_identifies_products():
    """ProductXYZ candidates must be products that are actually reviewed."""
    from fedshop.query import build_value_selection_query

    root = __import__("pathlib").Path(__file__).parents[1]
    query = (root / "queries" / "q08.sparql").read_text()
    constants = json.loads((root / "queries" / "q08.const.json").read_text())

    selection = build_value_selection_query(query, constants)
    generated = "\n".join(item["query"] for item in selection.values())

    assert "http://www4.wiwiss.fu-berlin.de/bizer/bsbm/v01/vocabulary/reviewFor" in generated


def test_q10_value_selection_keeps_relation_that_identifies_products():
    """ProductXYZ candidates must be products referenced by an offer."""
    from fedshop.query import build_value_selection_query

    root = __import__("pathlib").Path(__file__).parents[1]
    query = (root / "queries" / "q10.sparql").read_text()
    constants = json.loads((root / "queries" / "q10.const.json").read_text())

    selection = build_value_selection_query(query, constants)
    generated = "\n".join(item["query"] for item in selection.values())

    assert "http://www4.wiwiss.fu-berlin.de/bizer/bsbm/v01/vocabulary/product" in generated


def test_value_selection_falls_back_to_graph_scoped_endpoints():
    from fedshop.query import sample_workload_values

    client = MagicMock()
    client.select_csv.side_effect = [
        b"ReviewXYZ\nhttp://www.ratingsite0.fr/Review1\n",
        b"ReviewXYZ\nhttp://www.ratingsite1.fr/Review2\n",
    ]
    subqueries = {
        "sq0": {
            "kind": "join",
            "query": (
                "SELECT ?ReviewXYZ WHERE { "
                "?ReviewXYZ <http://purl.org/stuff/rev#reviewer> ?x }"
            ),
        }
    }

    result = sample_workload_values(
        subqueries,
        "http://localhost:8890/sparql",
        2,
        sparql_client=client,
        fallback_endpoints=[
            "http://localhost:8890/sparql?default-graph-uri=ratingsite0",
            "http://localhost:8890/sparql?default-graph-uri=ratingsite1",
        ],
    )

    assert result["ReviewXYZ"].tolist() == [
        "http://www.ratingsite0.fr/Review1",
        "http://www.ratingsite1.fr/Review2",
    ]
    called_endpoints = [call.args[0] for call in client.select_csv.call_args_list]
    assert "http://localhost:8890/sparql" not in called_endpoints


def test_single_pattern_reference_query_unions_graph_scoped_results():
    from fedshop.query import execute_reference_query

    client = MagicMock()
    client.select_csv.side_effect = [
        b"x\nreviewer0\n",
        b"x\nreviewer0\nreviewer1\n",
    ]

    result = execute_reference_query(
        "SELECT ?x WHERE { <http://review/1> <http://reviewer> ?x }",
        "http://localhost:8890/sparql",
        sparql_client=client,
        scoped_endpoints=["graph0", "graph1"],
    )

    assert result["x"].tolist() == ["reviewer0", "reviewer1"]


def test_reference_query_prunes_scoped_endpoints_from_bound_source_iri():
    from fedshop.query import execute_reference_query

    client = MagicMock()
    client.select_csv.return_value = b"x\nreviewer1\n"
    graph0 = (
        "http://localhost:8890/sparql?"
        "default-graph-uri=http://www.ratingsite0.fr/"
    )
    graph1 = (
        "http://localhost:8890/sparql?"
        "default-graph-uri=http://www.ratingsite1.fr/"
    )

    execute_reference_query(
        (
            "SELECT ?x WHERE { <http://www.ratingsite1.fr/Review1> "
            "<http://purl.org/stuff/rev#reviewer> ?x }"
        ),
        "http://localhost:8890/sparql",
        sparql_client=client,
        scoped_endpoints=[graph0, graph1],
    )

    assert [call.args[0] for call in client.select_csv.call_args_list] == [graph1]


def test_batch_zero_regenerates_empty_cached_workload(config_small, tmp_path):
    from fedshop.query import generate_queries_for_template

    template = tmp_path / "q09.sparql"
    template.write_text("SELECT ?x WHERE { ?ReviewXYZ <http://example/reviewer> ?x }")
    constants = tmp_path / "q09.const.json"
    constants.write_text(json.dumps({"ReviewXYZ": {"exclusive": True}}))
    output = tmp_path / "q09"
    output.mkdir()
    config_small.generation.workdir = str(tmp_path)
    (tmp_path / "virtuoso-proxy-mapping-batch0.json").write_text(json.dumps({
        "http://www.ratingsite0.fr/": (
            "http://host.docker.internal:8890/sparql?"
            "default-graph-uri=http%3A%2F%2Fwww.ratingsite0.fr%2F"
        )
    }))
    (output / "value_selection.json").write_text(
        json.dumps({"sq0": {"kind": "exclusive", "query": "SELECT ?ReviewXYZ WHERE { ?ReviewXYZ ?p ?o }"}})
    )
    (output / "workload_value_selection.csv").write_text("ReviewXYZ\n")
    sampled = pd.DataFrame({"ReviewXYZ": ["http://example/review/1", "http://example/review/2"]})

    with patch("fedshop.query.sample_workload_values", return_value=sampled) as sample, patch(
        "fedshop.query.execute_reference_query", return_value=pd.DataFrame({"x": ["reviewer"]})
    ) as reference:
        generate_queries_for_template(
            template,
            constants,
            output,
            config_small,
            batch_id=0,
            sparql_client=MagicMock(),
        )

    sample.assert_called_once()
    assert sample.call_args.kwargs["fallback_endpoints"] == [
        "http://localhost:8890/sparql?"
        "default-graph-uri=http://www.ratingsite0.fr/"
    ]
    reference_endpoint = reference.call_args_list[0].args[1]
    assert reference_endpoint == (
        "http://localhost:8890/sparql?"
        "default-graph-uri=http%3A%2F%2Fwww.ratingsite0.fr%2F"
    )
    assert reference.call_args_list[0].kwargs["scoped_endpoints"] == [
        "http://localhost:8890/sparql?"
        "default-graph-uri=http://www.ratingsite0.fr/"
    ]
    assert (output / "instance_0" / "injected.sparql").exists()
    assert (output / "instance_1" / "injected.sparql").exists()
    assert len(pd.read_csv(output / "workload_value_selection.csv")) == 2


def test_batch_zero_resamples_even_valid_cached_workload(config_small, tmp_path):
    from fedshop.query import generate_queries_for_template

    template = tmp_path / "q09.sparql"
    template.write_text("SELECT ?x WHERE { ?ReviewXYZ <http://example/reviewer> ?x }")
    constants = tmp_path / "q09.const.json"
    constants.write_text(json.dumps({"ReviewXYZ": {"exclusive": True}}))
    output = tmp_path / "q09"
    output.mkdir()
    stale_instance = output / "instance_0"
    stale_instance.mkdir()
    (stale_instance / "injected.sparql").write_text("stale query")
    (stale_instance / "composition.json").write_text('{"stale": true}')
    (output / "value_selection.json").write_text(
        json.dumps({"sq0": {"kind": "exclusive", "query": "SELECT ?ReviewXYZ WHERE { ?ReviewXYZ ?p ?o }"}})
    )
    pd.DataFrame({"ReviewXYZ": ["stale-1", "stale-2"]}).to_csv(
        output / "workload_value_selection.csv", index=False
    )
    sampled = pd.DataFrame({"ReviewXYZ": ["fresh-1", "fresh-2"]})

    with patch("fedshop.query.sample_workload_values", return_value=sampled) as sample, patch(
        "fedshop.query.execute_reference_query", return_value=pd.DataFrame({"x": []})
    ):
        generate_queries_for_template(
            template, constants, output, config_small, batch_id=0, sparql_client=MagicMock()
        )

    sample.assert_called_once()
    assert pd.read_csv(output / "workload_value_selection.csv")["ReviewXYZ"].tolist() == [
        "fresh-1",
        "fresh-2",
    ]
    assert (stale_instance / "injected.sparql").read_text() != "stale query"
    assert "stale" not in (stale_instance / "composition.json").read_text()


def test_batch_zero_rebuilds_cached_value_selection(config_small, tmp_path):
    from fedshop.query import generate_queries_for_template

    template = tmp_path / "q09.sparql"
    template.write_text("SELECT ?x WHERE { ?ReviewXYZ <http://example/reviewer> ?x }")
    constants = tmp_path / "q09.const.json"
    constants.write_text(json.dumps({"ReviewXYZ": {"exclusive": True}}))
    output = tmp_path / "q09"
    output.mkdir()
    (output / "value_selection.json").write_text('{"stale": true}')
    rebuilt = {"sq0": {"kind": "exclusive", "query": "SELECT ?ReviewXYZ WHERE { ?ReviewXYZ ?p ?o }"}}

    with patch("fedshop.query.build_value_selection_query", return_value=rebuilt) as build, patch(
        "fedshop.query.sample_workload_values",
        return_value=pd.DataFrame({"ReviewXYZ": ["fresh-1", "fresh-2"]}),
    ), patch("fedshop.query.execute_reference_query", return_value=pd.DataFrame({"x": []})):
        generate_queries_for_template(
            template, constants, output, config_small, batch_id=0, sparql_client=MagicMock()
        )

    build.assert_called_once()
    assert json.loads((output / "value_selection.json").read_text()) == rebuilt


def test_later_batch_overwrites_stale_reference_results(config_small, tmp_path):
    from fedshop.query import generate_queries_for_template

    config_small.generation.n_query_instances = 1
    template = tmp_path / "q09.sparql"
    template.write_text("SELECT ?x WHERE { ?ReviewXYZ <http://example/reviewer> ?x }")
    constants = tmp_path / "q09.const.json"
    constants.write_text(json.dumps({"ReviewXYZ": {}}))
    output = tmp_path / "q09"
    instance = output / "instance_0"
    instance.mkdir(parents=True)
    (output / "value_selection.json").write_text(json.dumps({
        "sq0": {
            "kind": "join",
            "query": "SELECT ?ReviewXYZ WHERE { ?ReviewXYZ ?p ?o }",
        }
    }))
    pd.DataFrame({"ReviewXYZ": ["http://example/review/1"]}).to_csv(
        output / "workload_value_selection.csv", index=False
    )
    (instance / "injected.sparql").write_text(
        "SELECT ?x WHERE { <http://example/review/1> <http://example/reviewer> ?x }"
    )
    (instance / "composition.json").write_text(
        json.dumps({"tp0": ["http://example/review/1", "http://example/reviewer", "x"]})
    )
    stale = instance / "results-batch1.csv"
    stale.write_text("x\nstale\n")

    with patch(
        "fedshop.query.execute_reference_query",
        return_value=pd.DataFrame({"x": ["fresh"]}),
    ) as reference:
        generate_queries_for_template(
            template,
            constants,
            output,
            config_small,
            batch_id=1,
            sparql_client=MagicMock(),
        )

    reference.assert_called_once()
    assert pd.read_csv(stale)["x"].tolist() == ["fresh"]
