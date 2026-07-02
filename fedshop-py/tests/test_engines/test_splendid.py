"""Tests for engines/splendid.py — SPLENDID adapter."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest


def make_adapter(tmp_path, config_small):
    from fedshop.engines.splendid import SplendidAdapter
    return SplendidAdapter(config_small, engine_dir=tmp_path)


# ---------------------------------------------------------------------------
# transform_results
# ---------------------------------------------------------------------------

def test_transform_results_copies_file(config_small, tmp_path):
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

    # SPLENDID triples;sources CSV: triples column has space-joined full-URI triple patterns;
    # multiple patterns comma-separated. get_triple_id abbreviates and looks up in inv_comp.
    comp = {"tp0": ["ex:s", "ex:p", "?o"]}
    prefix_cache = {"http://example.com/": "ex"}
    comp_file = _write_composition_and_cache(tmp_path, comp, prefix_cache)

    # Full-URI space-joined triple as produced by SPLENDID
    triple_str = "<http://example.com/s> <http://example.com/p> ?o"
    source = "[http://localhost:5555/vendor0/sparql]"

    infile = tmp_path / "source_selection.txt"
    outfile = tmp_path / "provenance.csv"
    infile.write_text(f"triples;sources\n{triple_str};{source}\n")

    adapter.transform_provenance(infile, outfile, comp_file)
    assert outfile.exists()
    df = pd.read_csv(outfile)
    assert "tp0" in df.columns


def test_transform_provenance_multiple_sources(config_small, tmp_path):
    adapter = make_adapter(tmp_path, config_small)

    comp = {
        "tp0": ["ex:s", "ex:p", "?o"],
        "tp1": ["?x", "ex:q", "?y"],
    }
    prefix_cache = {"http://example.com/": "ex"}
    comp_file = _write_composition_and_cache(tmp_path, comp, prefix_cache)

    lines = (
        "triples;sources\n"
        "<http://example.com/s> <http://example.com/p> ?o;"
        "[http://localhost:5555/vendor0/sparql,http://localhost:5555/vendor1/sparql]\n"
        "?x <http://example.com/q> ?y;"
        "[http://localhost:5555/vendor0/sparql]\n"
    )
    infile = tmp_path / "source_selection.txt"
    outfile = tmp_path / "provenance.csv"
    infile.write_text(lines)

    adapter.transform_provenance(infile, outfile, comp_file)
    assert outfile.exists()
    df = pd.read_csv(outfile)
    assert set(["tp0", "tp1"]).issubset(df.columns)
    # Two sources on tp0 means two rows
    assert len(df) == 2


# ---------------------------------------------------------------------------
# _generate_void_description
# ---------------------------------------------------------------------------

def test_generate_void_description_writes_n3_file(config_small, tmp_path):
    adapter = make_adapter(tmp_path, config_small)

    void_file = tmp_path / "vendor0.n3"

    responses = iter([
        b"<literal>3</literal>",
        b"<literal>2</literal>",
        b"<literal>2</literal>",
        (
            b"<uri>http://purl.org/goodrelations/v1#price</uri>"
            b"<literal>1</literal><literal>1</literal><literal>1</literal>"
        ),
        (
            b"<uri>http://purl.org/goodrelations/v1#Offering</uri>"
            b"<literal>2</literal>"
        ),
    ])

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return next(responses)

    with patch("fedshop.engines.splendid.urllib.request.urlopen", return_value=FakeResponse()):
        adapter._generate_void_description(
            "http://www.vendor0.fr/",
            "http://localhost:8890/vendor0/sparql",
            void_file,
        )

    assert void_file.exists()
    content = void_file.read_text()
    assert "@prefix void:" in content
    assert "void:triples" in content
    assert "void:sparqlEndpoint" in content
    assert "vendor0" in content


# ---------------------------------------------------------------------------
# generate_config_file
# ---------------------------------------------------------------------------

def test_generate_config_file_writes_n3_config(config_small, tmp_path):
    from fedshop.engines.splendid import SplendidAdapter

    adapter = SplendidAdapter(config_small, engine_dir=tmp_path)

    proxy_mapping = {
        "http://www.vendor0.fr/": "http://localhost:5555/vendor0/sparql",
    }

    # Pre-create void file so _generate_void_description is skipped
    void_dir = tmp_path / "eval" / "void"
    void_dir.mkdir(parents=True)
    (void_dir / "vendor0.n3").write_text("# placeholder\n@prefix void: <http://rdfs.org/ns/void#>.\n")

    config_path = adapter.generate_config_file(batch_id=0, proxy_mapping=proxy_mapping)

    assert config_path.exists()
    content = config_path.read_text()
    assert "rep:Repository" in content
    assert "west:VoidRepository" in content
