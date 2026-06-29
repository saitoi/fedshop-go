"""Tests for ingest.py — Virtuoso isql interface."""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import MagicMock, patch


def test_run_isql_without_docker_uses_bare_binary():
    """run_isql without container_name should not prefix with docker exec."""
    from fedshop.ingest import run_isql

    captured = []

    def fake_run(cmd, **kwargs):
        captured.append(cmd)
        return MagicMock(returncode=0, stdout=b"")

    with patch("fedshop.ingest.subprocess.run", side_effect=fake_run):
        run_isql("SELECT 1;", isql_path="/opt/virtuoso/isql")

    assert captured
    assert "docker" not in captured[0]
    assert "SELECT 1" in captured[0]


def test_run_isql_with_docker_prepends_exec():
    """run_isql with container_name should prefix command with docker exec."""
    from fedshop.ingest import run_isql

    captured = []

    def fake_run(cmd, **kwargs):
        captured.append(cmd)
        return MagicMock(returncode=0, stdout=b"")

    with patch("fedshop.ingest.subprocess.run", side_effect=fake_run):
        run_isql("SELECT 1;", isql_path="/opt/virtuoso/isql", container_name="my-container")

    assert captured
    assert "docker exec my-container" in captured[0]


def test_run_isql_capture_output_returns_string():
    """With capture_output=True, run_isql should return decoded stdout."""
    from fedshop.ingest import run_isql

    with patch("fedshop.ingest.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=b"hello\n")
        result = run_isql("SELECT 1;", isql_path="/usr/bin/isql", capture_output=True)

    assert result == "hello\n"


def test_load_nq_file_calls_ld_dir_and_rdf_loader_run():
    """load_nq_file should call ld_dir, rdf_loader_run, and checkpoint via run_isql."""
    from fedshop.ingest import load_nq_file

    calls_made = []

    def fake_isql(statement, isql_path, container_name=None, **kwargs):
        calls_made.append(statement)

    with patch("fedshop.ingest.run_isql", side_effect=fake_isql):
        load_nq_file(
            nq_file=Path("/data/vendor0.nq"),
            graph_uri="http://www.vendor0.fr/",
            isql_path="/opt/isql",
            container_name="container-1",
            container_data_path="/usr/share/proj",
        )

    statements = " ".join(calls_made)
    assert "SPARQL CLEAR GRAPH <http://www.vendor0.fr/>" in statements
    assert "DELETE FROM DB.DBA.LOAD_LIST" in statements
    assert "ld_dir" in statements
    assert "rdf_loader_run" in statements
    assert "checkpoint" in statements
    assert statements.index("CLEAR GRAPH") < statements.index("ld_dir")


def test_ingest_batch_writes_proxy_mapping_json(config_small, tmp_path):
    """ingest_batch should write virtuoso-proxy-mapping-batchN.json."""
    from fedshop.ingest import ingest_batch

    # Override workdir and data_dir to tmp
    config_small.generation.virtuoso.data_dir = str(tmp_path)
    config_small.generation.workdir = str(tmp_path)

    def fake_isql(statement, isql_path, container_name=None, **kwargs):
        pass  # swallow all isql calls

    with patch("fedshop.ingest.run_isql", side_effect=fake_isql):
        mapping_file = ingest_batch(config_small, batch_id=0)

    assert mapping_file.exists()
    mapping = json.loads(mapping_file.read_text())
    assert len(mapping) == 20  # batch0 has 20 federation members
    assert len(set(mapping.values())) == 20
    for member_iri, endpoint in mapping.items():
        parsed = urlparse(endpoint)
        assert parsed.hostname == "host.docker.internal"
        assert parsed.path == "/sparql"
        assert parse_qs(parsed.query) == {"default-graph-uri": [member_iri]}


def test_register_sparql_endpoint_scopes_url_to_member_graph():
    """Each endpoint URL must select exactly one named graph."""
    from fedshop.ingest import register_sparql_endpoint

    calls_made = []

    def fake_isql(statement, isql_path, container_name=None, **kwargs):
        calls_made.append(statement)

    with patch("fedshop.ingest.run_isql", side_effect=fake_isql):
        url = register_sparql_endpoint(
            member_iri="http://www.vendor0.fr/",
            lpath="/vendor0/sparql",
            isql_path="/opt/isql",
            container_name=None,
            vport=8890,
        )

    parsed = urlparse(url)
    assert parsed.path == "/sparql"
    assert parse_qs(parsed.query) == {
        "default-graph-uri": ["http://www.vendor0.fr/"]
    }
    assert calls_made == []
