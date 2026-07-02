from __future__ import annotations

import json

import pandas as pd


def test_artifact_store_initializes_small_duckdb_schema(config_small, tmp_path):
    from fedshop.artifacts import ArtifactStore

    db_path = tmp_path / "fedshop.duckdb"
    store = ArtifactStore(db_path)
    store.initialize()

    tables = set(store.connection.execute(
        """
        select table_schema || '.' || table_name
        from information_schema.tables
        where table_schema in ('input', 'output', 'meta')
        """
    ).fetchall())
    names = {row[0] for row in tables}

    assert names == {
        "input.config",
        "input.rdf",
        "input.queries",
        "output.executions",
        "output.results",
        "output.source_selection",
        "output.metrics",
        "meta.artifacts",
    }

    query_cols = {
        row[1]
        for row in store.connection.execute("describe input.queries").fetchall()
    }
    assert "instance_id" not in query_cols


def test_default_artifact_db_lives_at_fedshop_root_even_with_bench_dir(config_small, tmp_path):
    from fedshop.artifacts import default_artifact_db

    config_small.generation.workdir = str(tmp_path / "data")

    assert default_artifact_db(config_small) == tmp_path / "fedshop.duckdb"
    assert default_artifact_db(config_small, tmp_path / "benchmark" / "run") == tmp_path / "fedshop.duckdb"


def test_artifact_store_persists_simplified_config_json(config_small, tmp_path):
    from fedshop.config import EngineEntry
    from fedshop.artifacts import ArtifactStore

    config_small.generation.workdir = str(tmp_path / "data")
    config_small.generation.queries_dir = str(tmp_path / "inputs" / "queries")
    config_small.generation.virtuoso.data_dir = str(tmp_path / "inputs" / "product-dataset")
    config_small.generation.virtuoso.compose_file = str(tmp_path / "docker" / "virtuoso.yml")
    config_small.generation.schema["product"].template = str(tmp_path / "inputs" / "templates" / "bsbm-product.template")
    config_small.evaluation.n_attempts = 3
    config_small.generation.n_batch = 2
    config_small.evaluation.engines["pyfedx"] = EngineEntry(dir="/project/scripts")

    store = ArtifactStore(tmp_path / "fedshop.duckdb")
    config_id = store.persist_config(
        config_small,
        bench_dir=tmp_path / "benchmark",
        artifact_db=tmp_path / "fedshop.duckdb",
    )

    row = store.connection.execute(
        """
        select profile, batch_count, attempts, product_count, config_json
        from input.config
        where config_id = ?
        """,
        [config_id],
    ).fetchone()

    assert row[0] == "smoke"
    assert row[1] == 2
    assert row[2] == 3
    assert row[3] == 20000

    config_json = json.loads(row[4])
    assert set(config_json) == {"paths", "virtuoso", "proxy", "engines", "watdiv"}
    assert config_json["paths"] == {
        "inputs_dir": "inputs",
        "queries_dir": "inputs/queries",
        "templates_dir": "inputs/templates",
        "dataset_dir": "inputs/product-dataset",
        "docker_dir": "docker",
    }
    assert config_json["virtuoso"]["endpoint"].endswith("/sparql")
    assert set(config_json["engines"]) == {"pyfedx", "fedshop-go"}
    assert "workspace_root" not in json.dumps(config_json)
    assert "query_instances" not in json.dumps(config_json)


def test_artifact_store_persists_query_without_instance_id(config_small, tmp_path):
    from fedshop.artifacts import ArtifactStore

    store = ArtifactStore(tmp_path / "fedshop.duckdb")
    store.persist_query(
        config_id="cfg",
        query_id="q01",
        selection_batch_id=0,
        template_path=tmp_path / "q01.sparql",
        const_path=tmp_path / "q01.const.json",
        template_sparql="SELECT * WHERE { ?s ?p ?o }",
        const_json={"ProductType": {}},
        selected_values=pd.DataFrame([{"ProductType": "T"}]),
        injected_sparql="SELECT * WHERE { <s> ?p ?o }",
        composition_json={"tp0": ["s", "p", "o"]},
        injected_path=tmp_path / "instance_0" / "injected.sparql",
        composition_path=tmp_path / "instance_0" / "composition.json",
    )

    row = store.connection.execute(
        "select query_id, selected_values_json, injected_sparql from input.queries"
    ).fetchone()

    assert row[0] == "q01"
    assert json.loads(row[1]) == [{"ProductType": "T"}]
    assert row[2].startswith("SELECT")


def test_artifact_store_persists_execution_results_source_selection_and_metrics(tmp_path):
    from fedshop.artifacts import ArtifactStore

    store = ArtifactStore(tmp_path / "fedshop.duckdb")
    stats = tmp_path / "stats.csv"
    pd.DataFrame([{
        "engine": "pyfedx",
        "query": "q01",
        "batch": 0,
        "attempt": 1,
        "exec_time": 1.5,
        "source_selection_time": 0.2,
        "planning_time": 0.1,
        "join_time": 1.2,
        "ask": 3,
        "http_req": 4,
        "data_transfer": 512,
    }]).to_csv(stats, index=False)
    results = tmp_path / "results.csv"
    pd.DataFrame({"product": ["p1"], "label": ["L"]}).to_csv(results, index=False)
    selection = tmp_path / "source_selection.txt"
    pd.DataFrame({
        "triple": ["?s ?p ?o"],
        "source_selection": [json.dumps(["http://source/1", "http://source/2"])],
    }).to_csv(selection, index=False)
    metrics = pd.DataFrame([{
        "engine": "pyfedx",
        "query": "q01",
        "batch": 0,
        "attempt": 1,
        "status": "ok",
        "nb_results": 1,
        "nb_ref_results": 1,
        "mismatch": False,
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
        "exec_time": 1.5,
        "is_timeout": False,
        "is_error": False,
    }])

    run_id = store.persist_execution_from_files(
        config_id="cfg",
        engine="pyfedx",
        query_id="q01",
        batch_id=0,
        attempt=1,
        stats_path=stats,
        results_path=results,
        provenance_path=tmp_path / "provenance.csv",
        source_selection_path=selection,
        query_plan_path=tmp_path / "query_plan.txt",
    )
    store.persist_results_csv(
        config_id="cfg",
        result_kind="engine",
        engine="pyfedx",
        query_id="q01",
        batch_id=0,
        attempt=1,
        csv_path=results,
    )
    store.persist_source_selection_csv(
        run_id=run_id,
        config_id="cfg",
        engine="pyfedx",
        query_id="q01",
        batch_id=0,
        attempt=1,
        csv_path=selection,
    )
    store.persist_metrics("cfg", metrics)

    execution = store.connection.execute(
        "select status, exec_time, http_req from output.executions where run_id = ?",
        [run_id],
    ).fetchone()
    assert execution == ("ok", 1.5, 4)

    binding = store.connection.execute("select bindings_json from output.results").fetchone()[0]
    assert json.loads(binding) == {"product": "p1", "label": "L"}

    selected = store.connection.execute(
        "select selected_source_count from output.source_selection"
    ).fetchone()[0]
    assert selected == 2

    metric = store.connection.execute(
        "select status, precision from output.metrics"
    ).fetchone()
    assert metric == ("ok", 1.0)


def test_artifact_store_persists_nquads_as_input_rdf(tmp_path):
    from fedshop.artifacts import ArtifactStore

    nq = tmp_path / "vendor0.nq"
    nq.write_text(
        '<http://s> <http://p> "literal" <http://www.vendor0.fr/> .\n'
        '<http://s2> <http://p2> <http://o2> <http://www.vendor0.fr/> .\n'
    )

    store = ArtifactStore(tmp_path / "fedshop.duckdb")
    store.persist_rdf_file(
        config_id="cfg",
        batch_id=0,
        source_name="vendor0",
        source_type="vendor",
        graph="http://www.vendor0.fr/",
        file_path=nq,
    )

    rows = store.connection.execute(
        """
        select subject, predicate, object, object_type, graph, source_name
        from input.rdf
        order by row_number
        """
    ).fetchall()

    assert rows == [
        ("http://s", "http://p", "literal", "literal", "http://www.vendor0.fr/", "vendor0"),
        ("http://s2", "http://p2", "http://o2", "iri", "http://www.vendor0.fr/", "vendor0"),
    ]
