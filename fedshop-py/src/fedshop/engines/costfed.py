"""CostFed engine adapter.

Ported from reference-repos/FedShop/fedshop/engines/costfed.py.
Key differences from FedX:
  - Config: plain endpoints_batch{N}.txt + N3 summary (TBSSSummariesGenerator)
  - costfed.props is patched to point at the current batch summary
  - Main class: org.aksw.simba.start.QueryEvaluation
  - Results format: transposed CSV with varname=[val;val] cells
  - Source Var regex uses semicolons; source IDs are URL-encoded differently
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

import pandas as pd

from ..config import BenchmarkConfig
from ..engines.base import EngineAdapter
from ..engines.fedx import _pad
from ..proxy import ProxyClient


class CostFedAdapter(EngineAdapter):

    def __init__(self, config: BenchmarkConfig, engine_dir: Path | None = None) -> None:
        if engine_dir is None:
            engine_dir = Path(config.evaluation.engines["costfed"].dir)
        super().__init__(config, engine_dir)

    def prerequisites(self) -> None:
        # Skip costfed-web — it uses maven-war-plugin:2.3 which is incompatible with
        # modern Java's module system. Only costfed-core and its fedx dependency are needed.
        old_cwd = os.getcwd()
        os.chdir(self.engine_dir)
        if os.system("mvn clean install dependency:copy-dependencies -pl costfed,fedx") != 0:
            raise RuntimeError("Could not compile CostFed")
        os.chdir(old_cwd)

    def generate_config_file(self, batch_id: int, proxy_mapping: dict[str, str]) -> Path:
        old_cwd = os.getcwd()
        os.chdir(self.engine_dir)

        Path("summaries").mkdir(parents=True, exist_ok=True)
        endpoints_file = f"summaries/endpoints_batch{batch_id}.txt"
        summary_file = f"summaries/sum_fedshop_batch{batch_id}.n3"

        federation_members = self.config.generation.virtuoso.federation_members
        endpoints: list[str] = []
        for iri in federation_members[f"batch{batch_id}"].values():
            if iri in proxy_mapping:
                endpoints.append(proxy_mapping[iri])

        with open(endpoints_file, "w") as f:
            for ep in endpoints:
                f.write(f"{ep}\n")

        # Regenerate summary if missing or stale
        require_update = False
        if not Path(summary_file).exists() or Path(summary_file).stat().st_size == 0:
            require_update = True
        else:
            content = Path(summary_file).read_text()
            for ep in endpoints:
                if ep not in content:
                    require_update = True
                    break

        if require_update:
            cmd = (
                f'mvn exec:java '
                f'-Dexec.mainClass="org.aksw.simba.quetsal.util.TBSSSummariesGenerator" '
                f'-Dexec.args="{summary_file} {endpoints_file}" '
                f'-pl costfed'
            )
            proc = subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
            if proc.returncode != 0:
                raise RuntimeError(f"Could not generate {summary_file}")

        # Patch costfed.props to point at the current batch summary.
        # Use the absolute path so it resolves correctly regardless of JVM working dir.
        props_path = Path("costfed/costfed.props")
        abs_summary = str(Path(summary_file).resolve())
        content = props_path.read_text()
        patched = re.sub(
            r"quetzal\.fedSummaries=.*",
            f"quetzal.fedSummaries={abs_summary}",
            content,
        )
        props_path.write_text(patched)

        os.chdir(old_cwd)
        return self.engine_dir / summary_file

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

        timeout = self.config.evaluation.timeout
        proxy_cfg = self.config.evaluation.proxy
        proxy_host = proxy_cfg.host
        proxy_port = proxy_cfg.port
        proxy_endpoint = proxy_cfg.endpoint

        if proxy_client is None:
            proxy_client = ProxyClient(proxy_endpoint)

        proxy_client.reset()

        # Use absolute paths — mvn exec:java sets CWD to the module dir (engine_dir/costfed/),
        # not engine_dir, so relative paths resolve incorrectly inside FedShopRunner.
        props_file = str((self.engine_dir / "costfed" / "costfed.props").resolve())
        summary_file = str((self.engine_dir / f"summaries/sum_fedshop_batch{batch_id}.n3").resolve())
        endpoints_file = str((self.engine_dir / f"summaries/endpoints_batch{batch_id}.txt").resolve())
        noexec_str = str(noexec).lower()

        args = " ".join([
            props_file,
            str(out_result.resolve()),
            str(out_source_selection.resolve()),
            str(query_plan.resolve()),
            str(timeout + 10),
            summary_file,
            str(query_path.resolve()),
            noexec_str,
            endpoints_file,
        ])

        timeout_cmd = f"timeout --signal=SIGKILL {timeout}" if timeout != 0 else ""
        cmd = (
            f'{timeout_cmd} mvn exec:java '
            f'-Dhttp.proxyHost="{proxy_host}" '
            f'-Dhttp.proxyPort="{proxy_port}" '
            f'-Dhttp.nonProxyHosts="host.docker.internal|localhost|127.0.0.1" '
            f'-Dhttp.keepAlive=false '
            f'-Dexec.mainClass="org.aksw.simba.start.FedShopRunner" '
            f'-Dexec.args="{args}" '
            f'-pl costfed'
        ).strip()

        old_cwd = os.getcwd()
        os.chdir(self.engine_dir)

        t_start = time.time()
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        failed_reason: str | None = None

        try:
            proc.wait(timeout)
            if proc.returncode != 0:
                failed_reason = "error_runtime"
        except subprocess.TimeoutExpired:
            failed_reason = "timeout"
        finally:
            os.system('pkill -9 -f "costfed/target"')
            (self.engine_dir / "cache.db").unlink(missing_ok=True)

        exec_time = time.time() - t_start
        os.chdir(old_cwd)

        if str(stats) != "/dev/null":
            proxy_stats = proxy_client.get_stats()
            base = stats.parent
            (base / "exec_time.txt").write_text(str(exec_time))
            (base / "http_req.txt").write_text(str(proxy_stats.get("NB_HTTP_REQ", 0)))
            (base / "ask.txt").write_text(str(proxy_stats.get("NB_ASK", 0)))
            (base / "data_transfer.txt").write_text(str(proxy_stats.get("DATA_TRANSFER", 0)))
            self._write_stats(stats, failed_reason)

    def _write_stats(self, stats_path: Path, failed_reason: str | None) -> None:
        m = re.match(
            r".*/(\w+)/(q\w+)/instance_(\d+)/batch_(\d+)/attempt_(\d+)/stats.csv",
            str(stats_path),
        )
        if not m:
            return

        base = stats_path.parent
        row: dict[str, object] = {
            "engine": m.group(1),
            "query": m.group(2),
            "instance": m.group(3),
            "batch": m.group(4),
            "attempt": m.group(5),
        }
        for metric in ["exec_time", "source_selection_time", "planning_time", "ask", "http_req", "data_transfer"]:
            metric_file = base / f"{metric}.txt"
            if metric_file.exists():
                try:
                    row[metric] = float(metric_file.read_text())
                except ValueError:
                    row[metric] = failed_reason
            else:
                row[metric] = failed_reason

        pd.DataFrame([row]).to_csv(stats_path, index=False)

    def transform_results(self, infile: Path, outfile: Path) -> None:
        # FedShopRunner writes standard CSV directly — just copy.
        if infile.stat().st_size == 0:
            outfile.touch()
        else:
            import shutil
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

        def extract_triple(x: str) -> str:
            pattern = (
                r"StatementPattern\s+?Var\s+\((name=\w+;\s+value=(.*);\s+anonymous|name=(\w+))\)"
                r"\s+Var\s+\((name=\w+;\s+value=(.*);\s+anonymous|name=(\w+))\)"
                r"\s+Var\s+\((name=\w+;\s+value=(.*);\s+anonymous|name=(\w+))\)"
            )
            m = re.match(pattern, x)
            s = m.group(2) or m.group(3)
            p = m.group(5) or m.group(6)
            o = m.group(8) or m.group(9)
            return " ".join([s, p, o])

        def extract_source_selection(x: str) -> list[str]:
            pattern = r"StatementSource\s+\(id=((\w|:)+);\s+type=[A-Z]+\)"
            return [
                m[0].replace("sparql_", "http://").replace("_", "/")
                for m in re.findall(pattern, x)
            ]

        with open(composition_file) as f:
            composition = json.load(f)
        inv_composition = {" ".join(v): k for k, v in composition.items()}

        in_df = pd.read_csv(infile)
        in_df["triple"] = in_df["triple"].apply(extract_triple)
        in_df["tp_name"] = in_df["triple"].apply(lambda x: inv_composition[x])
        in_df["tp_number"] = in_df["tp_name"].str.replace("tp", "", regex=False).astype(int)
        in_df.sort_values("tp_number", inplace=True)
        in_df["source_selection"] = in_df["source_selection"].apply(extract_source_selection)

        max_length = in_df["source_selection"].apply(len).max()
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
