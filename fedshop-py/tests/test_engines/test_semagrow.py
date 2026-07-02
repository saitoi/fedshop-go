"""Tests for engines/semagrow.py — Semagrow adapter."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd


def make_adapter(tmp_path, config_small):
    from fedshop.engines.semagrow import SemagrowAdapter
    return SemagrowAdapter(config_small, engine_dir=tmp_path)


# ---------------------------------------------------------------------------
# transform_results
# ---------------------------------------------------------------------------

def test_transform_results_empty_infile_creates_empty_outfile(config_small, tmp_path):
    adapter = make_adapter(tmp_path, config_small)
    infile = tmp_path / "results.txt"
    outfile = tmp_path / "results.csv"
    infile.write_text("")
    adapter.transform_results(infile, outfile)
    assert outfile.exists()
    assert outfile.read_text() == ""


def test_transform_results_nonempty_copies_file(config_small, tmp_path):
    adapter = make_adapter(tmp_path, config_small)
    infile = tmp_path / "results.txt"
    outfile = tmp_path / "results.csv"
    infile.write_text("col1,col2\nval1,val2\n")
    adapter.transform_results(infile, outfile)
    assert outfile.read_text() == "col1,col2\nval1,val2\n"


# ---------------------------------------------------------------------------
# transform_provenance
# ---------------------------------------------------------------------------

def _write_composition_and_cache(directory: Path, comp: dict, prefix_cache: dict) -> Path:
    comp_file = directory / "composition.json"
    pc_file = directory / "prefix_cache.json"
    comp_file.write_text(json.dumps(comp))
    pc_file.write_text(json.dumps(prefix_cache))
    return comp_file


def test_transform_provenance_empty_infile_creates_empty_outfile(config_small, tmp_path):
    adapter = make_adapter(tmp_path, config_small)
    infile = tmp_path / "source_selection.txt"
    outfile = tmp_path / "provenance.csv"
    comp_file = _write_composition_and_cache(tmp_path, {"tp0": ["?s", "?p", "?o"]}, {})
    infile.write_text("")
    adapter.transform_provenance(infile, outfile, comp_file)
    assert outfile.exists()
    assert outfile.read_text() == ""


def test_transform_provenance_no_prefix_cache_creates_empty_outfile(config_small, tmp_path):
    adapter = make_adapter(tmp_path, config_small)
    infile = tmp_path / "source_selection.txt"
    outfile = tmp_path / "provenance.csv"
    comp_file = tmp_path / "composition.json"
    comp_file.write_text(json.dumps({"tp0": ["?s", "?p", "?o"]}))
    # No prefix_cache.json
    infile.write_text("some content")
    adapter.transform_provenance(infile, outfile, comp_file)
    assert outfile.exists()
    assert outfile.read_text() == ""


def test_transform_provenance_produces_pivot_csv(config_small, tmp_path):
    adapter = make_adapter(tmp_path, config_small)

    # Semagrow StatementPattern uses comma-separated Var fields
    # Triple: ?s ?p ?o  →  lookup via composition
    comp = {"tp0": ["?s", "?p", "?o"]}
    prefix_cache = {"http://example.com/": "ex"}
    comp_file = _write_composition_and_cache(tmp_path, comp, prefix_cache)

    # Semagrow tps;sources format — tps contains StatementPattern string
    tp_str = "StatementPattern Var (name=s) Var (name=p) Var (name=o)"
    source = "http://localhost:5555/vendor0/sparql"
    infile = tmp_path / "source_selection.txt"
    outfile = tmp_path / "provenance.csv"
    infile.write_text(f"{tp_str};{source}\n")

    adapter.transform_provenance(infile, outfile, comp_file)
    assert outfile.exists()
    df = pd.read_csv(outfile)
    assert "tp0" in df.columns


# ---------------------------------------------------------------------------
# generate_config_file
# ---------------------------------------------------------------------------

def test_generate_config_file_writes_repo_ttl_with_metadata_path(config_small, tmp_path):
    from fedshop.engines.semagrow import SemagrowAdapter

    adapter = SemagrowAdapter(config_small, engine_dir=tmp_path)

    proxy_mapping = {
        "http://www.vendor0.fr/": "http://localhost:5555/vendor0/sparql",
    }

    with (
        patch("fedshop.engines.semagrow.os.system", return_value=0),
        patch("builtins.open", side_effect=Exception("should not write summary")),
    ):
        # Summary file exists with endpoint so no regen needed; only repo_file written
        summary_file = tmp_path / "summaries" / "metadata-fedshop-batch0.ttl"
        summary_file.parent.mkdir(parents=True)
        summary_file.write_text(f"http://localhost:5555/vendor0/sparql")

        repo_file = adapter.generate_config_file(batch_id=0, proxy_mapping=proxy_mapping)

    assert repo_file.exists()
    content = repo_file.read_text()
    assert "semagrow:metadataInit" in content
    assert str(summary_file) in content


def test_run_benchmark_writes_engine_log_outside_engine_repo(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from fedshop.engines.semagrow import SemagrowAdapter

    cwd = tmp_path / "workspace"
    bench_root = Path("benchmark") / "run-2026-06-30-new" / "evaluation" / "semagrow" / "q01" / "instance_0" / "batch_0" / "attempt_0"
    bench_root_abs = cwd / bench_root
    bench_root_abs.mkdir(parents=True)
    query_path = cwd / "generation" / "q01" / "instance_0" / "injected.sparql"
    query_path.parent.mkdir(parents=True)
    query_path.write_text("SELECT * WHERE { ?s ?p ?o }")

    config = SimpleNamespace(
        evaluation=SimpleNamespace(
            timeout=1,
            proxy=SimpleNamespace(endpoint="http://localhost:8080"),
            engines={"semagrow": SimpleNamespace(extra={})},
        ),
        generation=SimpleNamespace(virtuoso=SimpleNamespace(port=8890)),
    )

    class FakeProxyClient:
        def reset(self):
            pass

        def get_stats(self):
            return {"NB_HTTP_REQ": 1, "NB_ASK": 2, "DATA_TRANSFER": 3}

    class FakeProc:
        returncode = 0

        def wait(self, timeout):
            return None

    engine_dir = tmp_path / "semagrow-repo"
    (engine_dir / "summaries").mkdir(parents=True)
    (engine_dir / "summaries" / "repo-fedshop-batch0.ttl").write_text("repo")
    monkeypatch.chdir(cwd)
    monkeypatch.setattr("fedshop.engines.semagrow._wait_virtuoso", lambda endpoint, max_wait=120: None)
    monkeypatch.setattr("fedshop.engines.semagrow.subprocess.Popen", lambda *a, **k: FakeProc())
    monkeypatch.setattr("fedshop.engines.semagrow.os.system", lambda cmd: 0)

    adapter = SemagrowAdapter(config, engine_dir=engine_dir)
    adapter.run_benchmark(
        query_path=query_path,
        batch_id=0,
        out_result=bench_root_abs / "results.txt",
        out_source_selection=bench_root_abs / "source_selection.txt",
        query_plan=bench_root_abs / "query_plan.txt",
        stats=bench_root / "stats.csv",
        proxy_client=FakeProxyClient(),
    )

    assert (bench_root_abs / "engine.log").exists()
    assert (bench_root_abs / "stats.csv").exists()
    assert not (engine_dir / "benchmark").exists()
