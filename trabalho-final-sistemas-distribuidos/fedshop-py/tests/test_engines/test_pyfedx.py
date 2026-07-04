"""Tests for engines/pyfedx.py — PyFedX adapter."""

import csv
import io
import json
from pathlib import Path

import pandas as pd
import pytest


def _write_source_sel(path: Path, rows: list[dict]) -> None:
    """Write a source_selection CSV with proper quoting (JSON arrays need quoting)."""
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["triple", "source_selection"])
        writer.writeheader()
        writer.writerows(rows)


def test_generate_config_file_writes_ttl(config_small, tmp_path):
    """generate_config_file should write sd:endpoint entries for each proxy mapping entry."""
    from fedshop.engines.pyfedx import PyFedXAdapter

    adapter = PyFedXAdapter(config_small, engine_dir=tmp_path)
    (tmp_path / "target" / "config").mkdir(parents=True)

    proxy_mapping = {
        "http://www.vendor0.fr/": "http://localhost:5555/vendor0/sparql",
        "http://www.ratingsite0.fr/": "http://localhost:5555/ratingsite0/sparql",
    }
    ttl_path = adapter.generate_config_file(batch_id=0, proxy_mapping=proxy_mapping)
    content = ttl_path.read_text()

    assert "sd:endpoint" in content
    assert "vendor0" in content
    assert "ratingsite0" in content


def test_generate_config_file_idempotent(config_small, tmp_path):
    """Calling generate_config_file twice with same endpoints should not rewrite the file."""
    import time
    from fedshop.engines.pyfedx import PyFedXAdapter

    adapter = PyFedXAdapter(config_small, engine_dir=tmp_path)
    (tmp_path / "target" / "config").mkdir(parents=True)
    proxy_mapping = {"http://www.vendor0.fr/": "http://localhost:5555/v0/sparql"}

    adapter.generate_config_file(0, proxy_mapping)
    ttl_path = tmp_path / "target" / "config" / "config_batch0.ttl"
    mtime1 = ttl_path.stat().st_mtime

    time.sleep(0.01)
    adapter.generate_config_file(0, proxy_mapping)
    mtime2 = ttl_path.stat().st_mtime

    assert mtime1 == mtime2, "TTL should not be rewritten when endpoints are unchanged"


def test_prerequisites_raises_when_script_missing(config_small, tmp_path):
    """prerequisites() should raise if pyfedx.py is not in engine_dir."""
    from fedshop.engines.pyfedx import PyFedXAdapter

    adapter = PyFedXAdapter(config_small, engine_dir=tmp_path)
    with pytest.raises(RuntimeError, match="pyfedx.py not found"):
        adapter.prerequisites()


def test_prerequisites_passes_when_script_exists(config_small, tmp_path):
    """prerequisites() should succeed when pyfedx.py is present."""
    from fedshop.engines.pyfedx import PyFedXAdapter

    (tmp_path / "pyfedx.py").write_text("# stub")
    adapter = PyFedXAdapter(config_small, engine_dir=tmp_path)
    adapter.prerequisites()  # should not raise


def test_transform_results_copies_csv(config_small, tmp_path):
    """transform_results should copy infile CSV to outfile unchanged."""
    from fedshop.engines.pyfedx import PyFedXAdapter

    adapter = PyFedXAdapter(config_small, engine_dir=tmp_path)
    infile = tmp_path / "results.txt"
    outfile = tmp_path / "results.csv"
    infile.write_text("product,label\nhttp://p1,Phone\nhttp://p2,Camera\n")

    adapter.transform_results(infile, outfile)

    assert outfile.exists()
    df = pd.read_csv(outfile)
    assert list(df.columns) == ["product", "label"]
    assert len(df) == 2


def test_transform_results_empty_input_touches_outfile(config_small, tmp_path):
    """transform_results with empty infile should create empty outfile."""
    from fedshop.engines.pyfedx import PyFedXAdapter

    adapter = PyFedXAdapter(config_small, engine_dir=tmp_path)
    infile = tmp_path / "results.txt"
    outfile = tmp_path / "results.csv"
    infile.write_text("")

    adapter.transform_results(infile, outfile)

    assert outfile.exists()
    assert outfile.stat().st_size == 0


def test_transform_provenance_basic(config_small, tmp_path):
    """transform_provenance should produce pivot table matching composition.json layout."""
    from fedshop.engines.pyfedx import PyFedXAdapter

    adapter = PyFedXAdapter(config_small, engine_dir=tmp_path)

    # source_selection with "?var <uri> ?var" keys (pyfedx SPARQL format)
    source_sel = tmp_path / "source_selection.txt"
    _write_source_sel(source_sel, [
        {"triple": "?s <http://www.w3.org/2002/07/owl#sameAs> ?x",
         "source_selection": json.dumps(["http_www.vendor0.fr", "http_www.vendor1.fr"])},
        {"triple": "?x <http://example.org/label> ?label",
         "source_selection": json.dumps(["http_www.vendor0.fr"])},
    ])

    # composition.json uses bare names (no ? or <>) — real FedShop format
    composition = tmp_path / "composition.json"
    composition.write_text(json.dumps({
        "tp0": ["s", "http://www.w3.org/2002/07/owl#sameAs", "x"],
        "tp1": ["x", "http://example.org/label", "label"],
    }))

    outfile = tmp_path / "provenance.csv"
    adapter.transform_provenance(source_sel, outfile, composition)

    df = pd.read_csv(outfile)
    assert "tp0" in df.columns
    assert "tp1" in df.columns
    assert len(df) == 2  # max_length = 2 (tp0 has 2 sources)


def test_transform_provenance_empty_source_selection(config_small, tmp_path):
    """transform_provenance with all-empty source selections touches outfile."""
    from fedshop.engines.pyfedx import PyFedXAdapter

    adapter = PyFedXAdapter(config_small, engine_dir=tmp_path)

    source_sel = tmp_path / "source_selection.txt"
    _write_source_sel(source_sel, [
        {"triple": "?s <http://example.org/p> ?o",
         "source_selection": json.dumps([])},
    ])

    composition = tmp_path / "composition.json"
    composition.write_text(json.dumps({
        "tp0": ["s", "http://example.org/p", "o"],
    }))

    outfile = tmp_path / "provenance.csv"
    adapter.transform_provenance(source_sel, outfile, composition)

    assert outfile.exists()
    assert outfile.stat().st_size == 0


def test_transform_provenance_empty_infile(config_small, tmp_path):
    """transform_provenance with empty infile creates empty outfile."""
    from fedshop.engines.pyfedx import PyFedXAdapter

    adapter = PyFedXAdapter(config_small, engine_dir=tmp_path)
    source_sel = tmp_path / "source_selection.txt"
    source_sel.write_text("")
    composition = tmp_path / "composition.json"
    composition.write_text("{}")
    outfile = tmp_path / "provenance.csv"

    adapter.transform_provenance(source_sel, outfile, composition)

    assert outfile.exists()
    assert outfile.stat().st_size == 0
