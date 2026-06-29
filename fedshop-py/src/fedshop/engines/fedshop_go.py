"""Adapter for the production ``fedshop-go`` federated query engine."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from ..config import BenchmarkConfig
from ..proxy import ProxyClient
from .pyfedx import PyFedXAdapter


class FedShopGoAdapter(PyFedXAdapter):
    """Build and run the standalone Go engine using FedShop artifacts."""

    def __init__(self, config: BenchmarkConfig, engine_dir: Path | None = None) -> None:
        entry = config.evaluation.engines.get("fedshop-go")
        if engine_dir is None:
            if entry is None:
                raise RuntimeError("evaluation.engines.fedshop-go is not configured")
            engine_dir = Path(entry.dir)
        super().__init__(config, engine_dir)
        self.options = entry.extra if entry is not None else {}

    @property
    def binary(self) -> Path:
        return self.engine_dir / "fedshop-go"

    def prerequisites(self) -> None:
        self.engine_dir.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["GOCACHE"] = str(self.engine_dir / ".gocache")
        subprocess.run(
            ["go", "build", "-o", str(self.binary), "./cmd/fedshop-go"],
            cwd=self.engine_dir,
            check=True,
            env=env,
        )

    def generate_config_file(self, batch_id: int, proxy_mapping: dict[str, str]) -> Path:
        """Write graph-scoped endpoints reachable by the host Go process."""
        if self.options.get("http_proxy"):
            return super().generate_config_file(batch_id, proxy_mapping)
        host_mapping = {
            graph: endpoint.replace("host.docker.internal", "127.0.0.1").replace("localhost", "127.0.0.1")
            for graph, endpoint in proxy_mapping.items()
        }
        return super().generate_config_file(batch_id, host_mapping)

    def build_summary(self, batch_id: int) -> Path:
        """Build the measured predicate catalog for one federation batch."""
        config_path = self.engine_dir / "target" / "config" / f"config_batch{batch_id}.ttl"
        output = self.engine_dir / "target" / "summary" / f"summary_batch{batch_id}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            str(self.binary), "summarize",
            "--config", str(config_path),
            "--output", str(output),
            "--timeout", f"{float(self.config.evaluation.timeout)}s",
        ], check=True)
        return output

    def run_benchmark(
        self,
        query_path: Path,
        batch_id: int,
        out_result: Path,
        out_source_selection: Path,
        query_plan: Path,
        stats: Path,
        *,
        noexec: bool = False,
        proxy_client: ProxyClient | None = None,
    ) -> None:
        for path in (out_result, out_source_selection, query_plan):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("")

        use_proxy = bool(self.options.get("http_proxy"))
        if use_proxy:
            if proxy_client is None:
                proxy_client = ProxyClient(self.config.evaluation.proxy.endpoint)
            proxy_client.reset()

        config_path = self.engine_dir / "target" / "config" / f"config_batch{batch_id}.ttl"
        engine_stats = out_result.parent / "fedshop_go_stats.json"
        engine_stats.unlink(missing_ok=True)
        timeout = float(self.config.evaluation.timeout)
        command = [
            str(self.binary), "query",
            "--config", str(config_path),
            "--query", str(query_path),
            "--out-result", str(out_result),
            "--out-source-selection", str(out_source_selection),
            "--query-plan", str(query_plan),
            "--stats", str(engine_stats),
            "--timeout", f"{timeout}s",
            "--selector", self.options.get("selector", "ask"),
            "--cache", self.options.get("cache", "memory"),
            "--join", self.options.get("join", "bind"),
            "--planner", self.options.get("planner", "source-count"),
            "--failure-policy", self.options.get("failure_policy", "strict"),
            "--max-concurrency", str(self.options.get("max_concurrency", 4)),
            "--bind-batch-size", str(self.options.get("bind_batch_size", 20)),
            "--retry-count", str(self.options.get("retry_count", 2)),
        ]
        if self.options.get("http_proxy"):
            command.extend(["--http-proxy", str(self.options["http_proxy"])])
        if self.options.get("exclusive_groups", "true").lower() == "true":
            command.append("--exclusive-groups")
        if self.options.get("post_bind_max_input_rows") is not None:
            command.extend(["--post-bind-max-input-rows", str(self.options["post_bind_max_input_rows"])])
        if self.options.get("selector") == "summary":
            summary = self.engine_dir / "target" / "summary" / f"summary_batch{batch_id}.json"
            command.extend(["--summary", str(summary)])
        if noexec:
            command.append("--noexec")

        started = time.monotonic()
        failed_reason: str | None = None
        process = subprocess.Popen(command)
        try:
            process.wait(timeout)
            if process.returncode != 0:
                failed_reason = "error_runtime"
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            failed_reason = "timeout"

        elapsed = time.monotonic() - started
        self._write_stats(
            stats,
            engine_stats,
            failed_reason,
            elapsed,
            proxy_client.get_stats() if use_proxy and proxy_client is not None else {},
        )
