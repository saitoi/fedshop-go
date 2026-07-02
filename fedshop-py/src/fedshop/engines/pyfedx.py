"""PyFedX engine adapter.

Wraps scripts/pyfedx.py — a pure-Python, dependency-free SPARQL federation
runner that supports FILTER, OPTIONAL, UNION, and ORDER BY.

Output format notes (differs from FedX adapter):
- results file: already CSV (just copied to results.csv)
- source_selection: CSV with columns "triple" (s p o, no trailing '.') and
  "source_selection" (JSON array of endpoint IDs)
- stats: JSON written by pyfedx.py; re-read here to build standard stats.csv
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pandas as pd

from ..config import BenchmarkConfig
from ..engines.base import EngineAdapter
from ..engines.fedx import _pad
from ..proxy import ProxyClient


class PyFedXAdapter(EngineAdapter):

    def __init__(self, config: BenchmarkConfig, engine_dir: Path | None = None) -> None:
        if engine_dir is None:
            engine_dir = Path(config.evaluation.engines["pyfedx"].dir)
        super().__init__(config, engine_dir)

    @property
    def _script(self) -> Path:
        return self.engine_dir / "pyfedx.py"

    def prerequisites(self) -> None:
        if not self._script.exists():
            raise RuntimeError(f"pyfedx.py not found at {self._script}")

    def generate_config_file(self, batch_id: int, proxy_mapping: dict[str, str]) -> Path:
        """Write Turtle federation config — same format as FedX."""
        config_dir = self.engine_dir / "target" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        endpoints_file = config_dir / f"config_batch{batch_id}.ttl"

        federation_members = self.config.generation.virtuoso.federation_members
        endpoints: dict[str, str] = {}
        for federation_member_iri in federation_members[f"batch{batch_id}"].values():
            if federation_member_iri in proxy_mapping:
                endpoints[federation_member_iri] = proxy_mapping[federation_member_iri]

        update_required = not endpoints_file.exists()
        if not update_required:
            content = endpoints_file.read_text()
            for ep_url in endpoints.values():
                if f'sd:endpoint "{ep_url}' not in content:
                    update_required = True
                    break

        if update_required:
            with open(endpoints_file, "w") as f:
                f.write(textwrap.dedent(
                    """
                    @prefix sd: <http://www.w3.org/ns/sparql-service-description#> .
                    @prefix fedx: <http://rdf4j.org/config/federation#> .

                    """
                ))
                for graph_uri, ep_url in endpoints.items():
                    f.write(textwrap.dedent(
                        f"""
                        <{graph_uri}> a sd:Service ;
                            fedx:store "SPARQLEndpoint";
                            sd:endpoint "{ep_url}";
                            fedx:supportsASKQueries true .

                        """
                    ))

        return endpoints_file

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
        out_result.touch()
        out_source_selection.touch()
        query_plan.touch()

        config_path = self.engine_dir / "target" / "config" / f"config_batch{batch_id}.ttl"
        timeout = self.config.evaluation.timeout
        proxy_cfg = self.config.evaluation.proxy

        if proxy_client is None:
            proxy_client = ProxyClient(proxy_cfg.endpoint)

        proxy_client.reset()

        pyfedx_json = out_result.parent / "pyfedx_stats.json"
        cmd = [
            sys.executable,
            str(self._script),
            "--config", str(config_path),
            "--query", str(query_path),
            "--out-result", str(out_result),
            "--out-source-selection", str(out_source_selection),
            "--query-plan", str(query_plan),
            "--stats", str(pyfedx_json),
            "--timeout", str(float(timeout)),
        ]
        if noexec:
            cmd.append("--noexec")

        t_start = time.time()
        failed_reason: str | None = None
        proc = subprocess.Popen(cmd)  # inherit stdout/stderr so caller sees progress
        try:
            proc.wait(timeout)
            if proc.returncode != 0:
                failed_reason = "error_runtime"
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            failed_reason = "timeout"

        exec_time = time.time() - t_start
        proxy_stats = proxy_client.get_stats()
        self._write_stats(stats, pyfedx_json, failed_reason, exec_time, proxy_stats)

    def _write_stats(
        self,
        stats_path: Path,
        pyfedx_json: Path,
        failed_reason: str | None,
        exec_time: float,
        proxy_stats: dict,
    ) -> None:
        m = re.match(
            r".*/([\w-]+)/(q\w+)/instance_(\d+)/batch_(\d+)/attempt_(\d+)/stats.csv",
            str(stats_path),
        )
        if not m:
            return

        pyfedx_stats: dict = {}
        if pyfedx_json.exists():
            try:
                pyfedx_stats = json.loads(pyfedx_json.read_text())
            except Exception:
                pass

        def _v(key: str, default=None):
            return pyfedx_stats.get(key, default)

        total_s = _v("total_seconds", exec_time)
        ss_s = _v("source_selection_seconds", 0.0)
        plan_s = _v("planning_seconds", 0.0)
        exec_s = _v("execution_seconds")  # present in fedshop-go JSON; absent in pyfedx JSON
        join_s = exec_s if exec_s is not None else max(0.0, total_s - ss_s - plan_s)

        row: dict = {
            "engine": m.group(1),
            "query": m.group(2),
            "instance": m.group(3),
            "batch": m.group(4),
            "attempt": m.group(5),
            "exec_time": failed_reason if failed_reason else total_s,
            "source_selection_time": failed_reason if failed_reason else ss_s,
            "planning_time": failed_reason if failed_reason else plan_s,
            "join_time": failed_reason if failed_reason else join_s,
            "ask": failed_reason if failed_reason else _v("ask", 0),
            "http_req": failed_reason if failed_reason else _v("http_requests", proxy_stats.get("NB_HTTP_REQ", 0)),
            "data_transfer": failed_reason if failed_reason else _v("data_transfer", proxy_stats.get("DATA_TRANSFER", 0)),
        }
        stats_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([row]).to_csv(stats_path, index=False)

    def transform_results(self, infile: Path, outfile: Path) -> None:
        """pyfedx already writes CSV — just copy."""
        if infile.stat().st_size == 0:
            outfile.touch()
        else:
            shutil.copy(infile, outfile)

    def transform_provenance(
        self,
        infile: Path,
        outfile: Path,
        composition_file: Path,
    ) -> None:
        with open(infile) as f:
            if not f.read().strip():
                outfile.touch()
                return

        with open(composition_file) as f:
            composition = json.load(f)

        def _to_sparql_term(t: str) -> str:
            if t.startswith("http://") or t.startswith("https://"):
                return f"<{t}>"
            return f"?{t}"

        inv_composition = {
            " ".join(_to_sparql_term(t) for t in v): k
            for k, v in composition.items()
        }

        in_df = pd.read_csv(infile)
        # triple column is already "s p o" (no trailing '.') — direct lookup
        in_df["tp_name"] = in_df["triple"].apply(lambda x: inv_composition[x])
        in_df["tp_number"] = in_df["tp_name"].str.replace("tp", "", regex=False).astype(int)
        in_df.sort_values("tp_number", inplace=True)
        in_df["source_selection"] = in_df["source_selection"].apply(json.loads)

        max_length = in_df["source_selection"].apply(len).max()
        if max_length == 0:
            outfile.touch()
            return

        in_df["source_selection"] = in_df["source_selection"].apply(
            lambda x: _pad(x, max_length)
        )

        out_df = (
            in_df.set_index("tp_name")["source_selection"]
            .to_frame()
            .T
            .apply(pd.Series.explode)
            .reset_index(drop=True)
        )
        out_df.to_csv(outfile, index=False)
