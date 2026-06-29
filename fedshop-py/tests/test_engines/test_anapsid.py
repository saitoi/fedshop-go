"""Tests for engines/anapsid.py — ANAPSID adapter."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


def make_adapter(tmp_path, config_small):
    from fedshop.engines.anapsid import AnapsidAdapter
    return AnapsidAdapter(config_small, engine_dir=tmp_path)


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


def test_transform_results_parses_anapsid_dict_format(config_small, tmp_path):
    adapter = make_adapter(tmp_path, config_small)
    infile = tmp_path / "results.txt"
    outfile = tmp_path / "results.csv"
    # ANAPSID dict-like output: each line is key: 'value', key2: 'value2'
    infile.write_text("'product': 'http://example.com/p1', 'label': 'Widget'")
    adapter.transform_results(infile, outfile)
    df = pd.read_csv(outfile)
    assert "product" in df.columns
    assert "label" in df.columns
    assert df.iloc[0]["product"] == "http://example.com/p1"


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
    comp_file = _write_composition_and_cache(
        tmp_path,
        {"tp0": ["?s", "?p", "?o"]},
        {},
    )
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

    # composition.json values use the abbreviated prefixed form (post-expansion).
    # get_triple_id expands <http://example.com/s> → ex:s and looks up in inv_comp.
    comp = {"tp0": ["ex:s", "ex:p", "?o"]}
    prefix_cache = {"http://example.com/": "ex"}
    comp_file = _write_composition_and_cache(tmp_path, comp, prefix_cache)

    # ANAPSID source selection format: (url)>', [\n  triple\n
    raw = (
        "http://www.vendor0.fr/>', [\n"
        "  <http://example.com/s> <http://example.com/p> ?o\n"
    )
    infile = tmp_path / "source_selection.txt"
    outfile = tmp_path / "provenance.csv"
    infile.write_text(raw)

    adapter.transform_provenance(infile, outfile, comp_file)
    assert outfile.exists()
    df = pd.read_csv(outfile)
    assert "tp0" in df.columns


# ---------------------------------------------------------------------------
# run_benchmark — batch > 4 skip
# ---------------------------------------------------------------------------

def test_run_benchmark_skips_batch_gt4_writes_timeout_stats(config_small, tmp_path):
    from fedshop.engines.anapsid import AnapsidAdapter, ANAPSID_MAX_BATCH

    adapter = AnapsidAdapter(config_small, engine_dir=tmp_path)

    out_dir = tmp_path / "evaluation" / "anapsid" / "q01" / "instance_0" / "batch_5" / "attempt_0"
    out_dir.mkdir(parents=True)

    results_txt = out_dir / "results.txt"
    source_sel = out_dir / "source_selection.txt"
    query_plan = out_dir / "query_plan.txt"
    stats = out_dir / "stats.csv"
    query = tmp_path / "q01.sparql"
    query.write_text("SELECT * WHERE { ?s ?p ?o }")

    adapter.run_benchmark(
        query_path=query,
        batch_id=ANAPSID_MAX_BATCH + 1,
        out_result=results_txt,
        out_source_selection=source_sel,
        query_plan=query_plan,
        stats=stats,
    )

    assert stats.exists()
    df = pd.read_csv(stats)
    assert df.iloc[0]["exec_time"] == "timeout"


# ---------------------------------------------------------------------------
# generate_config_file
# ---------------------------------------------------------------------------

def test_generate_config_file_writes_endpoints_file(config_small, tmp_path):
    from fedshop.engines.anapsid import AnapsidAdapter

    adapter = AnapsidAdapter(config_small, engine_dir=tmp_path)

    proxy_mapping = {
        "http://www.vendor0.fr/": "http://localhost:5555/vendor0/sparql",
        "http://www.vendor1.fr/": "http://localhost:5555/vendor1/sparql",
    }

    # Mock os.system and _python2_bin to avoid needing Python 2.7 installed
    with (
        patch("fedshop.engines.anapsid.os.system", return_value=0),
        patch("fedshop.engines.anapsid._python2_bin", return_value="/usr/bin/python2"),
    ):
        adapter.generate_config_file(batch_id=0, proxy_mapping=proxy_mapping)

    endpoints_file = tmp_path / "summaries" / "endpoints_batch0.txt"
    assert endpoints_file.exists()
    content = endpoints_file.read_text()
    assert "http://localhost:5555/vendor0/sparql" in content
