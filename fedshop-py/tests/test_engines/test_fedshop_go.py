"""Tests for the production fedshop-go adapter."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd


def test_generate_config_reuses_fedshop_endpoint_contract(config_small, tmp_path):
    from fedshop.engines.fedshop_go import FedShopGoAdapter

    adapter = FedShopGoAdapter(config_small, engine_dir=tmp_path)
    path = adapter.generate_config_file(0, {
        "http://www.vendor0.fr/": "http://localhost:5555/vendor0",
        "http://www.ratingsite0.fr/": "http://localhost:5555/rating0",
    })
    content = path.read_text()
    assert 'sd:endpoint "http://localhost:5555/vendor0"' in content
    assert 'sd:endpoint "http://localhost:5555/rating0"' in content


def test_generate_config_localizes_docker_host_without_proxy(config_small, tmp_path):
    from fedshop.engines.fedshop_go import FedShopGoAdapter

    adapter = FedShopGoAdapter(config_small, engine_dir=tmp_path)
    path = adapter.generate_config_file(0, {
        "http://www.vendor0.fr/": (
            "http://host.docker.internal:8890/sparql?"
            "default-graph-uri=http%3A%2F%2Fwww.vendor0.fr%2F"
        ),
    })

    content = path.read_text()
    assert "host.docker.internal" not in content
    assert "http://localhost:8890/sparql?" in content


def test_prerequisites_builds_with_workspace_cache(config_small, tmp_path):
    from fedshop.engines.fedshop_go import FedShopGoAdapter
    adapter = FedShopGoAdapter(config_small, engine_dir=tmp_path)
    with patch("fedshop.engines.fedshop_go.subprocess.run") as run:
        adapter.prerequisites()
    assert run.call_args.kwargs["env"]["GOCACHE"] == str(tmp_path / ".gocache")


def test_run_benchmark_invokes_binary_and_writes_standard_stats(config_small, tmp_path):
    from fedshop.engines.fedshop_go import FedShopGoAdapter

    engine_dir = tmp_path / "go-engine"
    engine_dir.mkdir()
    binary = engine_dir / "fedshop-go"
    binary.write_text("binary")
    binary.chmod(0o755)
    config_dir = engine_dir / "target" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "config_batch0.ttl").write_text("config")
    query = tmp_path / "query.sparql"
    query.write_text("SELECT ?s WHERE { ?s ?p ?o }")
    out_dir = tmp_path / "evaluation" / "fedshop_go" / "q01" / "instance_0" / "batch_0" / "attempt_0"
    out_dir.mkdir(parents=True)
    stats = out_dir / "stats.csv"
    proxy = MagicMock()
    proxy.get_stats.return_value = {"NB_HTTP_REQ": 4, "DATA_TRANSFER": 100}

    def finish_process(command, **kwargs):
        stats_json = Path(command[command.index("--stats") + 1])
        stats_json.write_text(json.dumps({
            "total_seconds": 1.2,
            "source_selection_seconds": 0.2,
            "planning_seconds": 0.1,
            "ask": 3,
            "http_requests": 7,
            "data_transfer": 123,
        }))
        proc = MagicMock()
        proc.wait.return_value = 0
        proc.returncode = 0
        return proc

    adapter = FedShopGoAdapter(config_small, engine_dir=engine_dir)
    with patch("fedshop.engines.fedshop_go.subprocess.Popen", side_effect=finish_process) as popen:
        adapter.run_benchmark(
            query, 0, out_dir / "results.txt", out_dir / "source_selection.txt",
            out_dir / "query_plan.txt", stats, proxy_client=proxy,
        )

    command = popen.call_args.args[0]
    assert command[:2] == [str(binary), "query"]
    assert "--selector" in command and "ask" in command
    assert "--http-proxy" not in command
    assert command[command.index("--max-concurrency") + 1] == "4"
    assert command[command.index("--bind-batch-size") + 1] == "20"
    assert command[command.index("--retry-count") + 1] == "2"
    assert stats.exists()
    stats_row = pd.read_csv(stats).iloc[0]
    assert stats_row["planning_time"] == 0.1
    assert stats_row["http_req"] == 7
    assert stats_row["data_transfer"] == 123
    proxy.reset.assert_not_called()
    proxy.get_stats.assert_not_called()


def test_failed_run_removes_stale_engine_artifacts(config_small, tmp_path):
    from fedshop.engines.fedshop_go import FedShopGoAdapter

    engine_dir = tmp_path / "go-engine"
    (engine_dir / "target" / "config").mkdir(parents=True)
    (engine_dir / "fedshop-go").write_text("binary")
    (engine_dir / "target" / "config" / "config_batch0.ttl").write_text("config")
    query = tmp_path / "query.sparql"
    query.write_text("SELECT ?s WHERE { ?s ?p ?o }")
    out_dir = tmp_path / "evaluation" / "fedshop-go" / "q01" / "instance_0" / "batch_0" / "attempt_0"
    out_dir.mkdir(parents=True)
    outputs = [
        out_dir / "results.txt",
        out_dir / "source_selection.txt",
        out_dir / "query_plan.txt",
    ]
    for output in outputs:
        output.write_text("stale")
    engine_stats = out_dir / "fedshop_go_stats.json"
    engine_stats.write_text('{"rows": 999, "total_seconds": 1}')

    process = MagicMock(returncode=1)
    process.wait.return_value = 1
    proxy = MagicMock()
    proxy.get_stats.return_value = {}
    adapter = FedShopGoAdapter(config_small, engine_dir=engine_dir)

    with patch("fedshop.engines.fedshop_go.subprocess.Popen", return_value=process):
        adapter.run_benchmark(
            query,
            0,
            outputs[0],
            outputs[1],
            outputs[2],
            out_dir / "stats.csv",
            proxy_client=proxy,
        )

    assert [output.read_text() for output in outputs] == ["", "", ""]
    assert not engine_stats.exists()
    assert pd.read_csv(out_dir / "stats.csv").iloc[0]["exec_time"] == "error_runtime"
