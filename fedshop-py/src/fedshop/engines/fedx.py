"""FedX engine adapter.

Ported from reference-repos/FedShop/fedshop/engines/fedx.py.
Preserves two critical patches from the handoff doc:
  1. http.nonProxyHosts includes host.docker.internal|localhost|127.0.0.1 in the Java exec.
  2. pad() is called before the set_index/explode pivot in transform_provenance (q05 fix).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import textwrap
import time
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import BenchmarkConfig
from ..engines.base import EngineAdapter
from ..proxy import ProxyClient


def _label_encode(x: list[str]) -> list[int]:
    unique = sorted(set(x))
    mapping = {v: i for i, v in enumerate(unique)}
    return [mapping[v] for v in x]


def _pad(x: list[str], max_length: int) -> list[str]:
    """Pad a source-selection list to max_length with empty strings.

    Patch 2: called before the pivot-explode to handle unequal tp list lengths (q05 bug fix).
    """
    encoded = _label_encode(x)
    unique = sorted(set(x))
    padded = encoded + [-1] * (max_length - len(x))
    return [unique[i] if i != -1 else "" for i in padded]


class FedXAdapter(EngineAdapter):

    def __init__(self, config: BenchmarkConfig, engine_dir: Path | None = None) -> None:
        if engine_dir is None:
            engine_dir = Path(config.evaluation.engines["fedx"].dir)
        super().__init__(config, engine_dir)

    def prerequisites(self) -> None:
        oldcwd = os.getcwd()
        os.chdir(self.engine_dir)
        if os.system("mvn clean && mvn install dependency:copy-dependencies package") != 0:
            raise RuntimeError("Could not compile FedX")
        os.chdir(oldcwd)

    def generate_config_file(self, batch_id: int, proxy_mapping: dict[str, str]) -> Path:
        """Write Turtle federation config for a batch.

        Reads federation members from config and maps their IRIs to proxy endpoint URLs.
        """
        old_cwd = os.getcwd()
        os.chdir(self.engine_dir)

        endpoints_file = Path(f"target/config/config_batch{batch_id}.ttl")
        endpoints_file.parent.mkdir(parents=True, exist_ok=True)

        federation_members = self.config.generation.virtuoso.federation_members
        endpoints: dict[str, str] = {}
        for federation_member_iri in federation_members[f"batch{batch_id}"].values():
            if federation_member_iri in proxy_mapping:
                endpoints[federation_member_iri] = proxy_mapping[federation_member_iri]

        update_required = False
        if endpoints_file.exists():
            content = endpoints_file.read_text()
            for endpoint in endpoints.values():
                if f'sd:endpoint "{endpoint}' not in content:
                    update_required = True
                    break
        else:
            update_required = True

        if update_required:
            with open(endpoints_file, "w") as f:
                f.write(textwrap.dedent(
                    """
                    @prefix sd: <http://www.w3.org/ns/sparql-service-description#> .
                    @prefix fedx: <http://rdf4j.org/config/federation#> .

                    """
                ))
                for graph_uri, endpoint in endpoints.items():
                    f.write(textwrap.dedent(
                        f"""
                        <{graph_uri}> a sd:Service ;
                            fedx:store "SPARQLEndpoint";
                            sd:endpoint "{endpoint}";
                            fedx:supportsASKQueries true .

                        """
                    ))

        os.chdir(old_cwd)
        return self.engine_dir / endpoints_file

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

        engine_config = f"target/config/config_batch{batch_id}.ttl"
        timeout = self.config.evaluation.timeout
        proxy_cfg = self.config.evaluation.proxy
        proxy_host = proxy_cfg.host
        proxy_port = proxy_cfg.port
        proxy_endpoint = proxy_cfg.endpoint

        if proxy_client is None:
            proxy_client = ProxyClient(proxy_endpoint)

        proxy_client.reset()

        args = " ".join([
            engine_config,
            str(query_path.resolve()),
            str(out_result.resolve()),
            str(out_source_selection.resolve()),
            str(query_plan.resolve()),
            str(timeout + 10),
            str(noexec).lower(),
        ])

        # Patch 1: http.nonProxyHosts excludes local addresses
        # Patch 2: http.keepAlive=false avoids stale-connection errors when running
        #          multiple batches (Apache HttpClient reuses connections that Virtuoso
        #          has closed between batches, triggering NoHttpResponseException)
        timeout_cmd = f"timeout --signal=SIGKILL {timeout}" if timeout != 0 else ""
        cmd = (
            f'{timeout_cmd} mvn exec:java '
            f'-Dhttp.proxyHost="{proxy_host}" '
            f'-Dhttp.proxyPort="{proxy_port}" '
            f'-Dhttp.nonProxyHosts="host.docker.internal|localhost|127.0.0.1" '
            f'-Dhttp.keepAlive=false '
            f'-Dexec.mainClass="org.example.FedX" '
            f'-Dexec.args="{args}"'
        ).strip()

        old_cwd = os.getcwd()
        os.chdir(self.engine_dir)

        t_start = time.time()
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        failed_reason: str | None = None

        try:
            proc.wait(timeout)
            if proc.returncode != 0 and not stats.exists():
                failed_reason = "error_runtime"
        except subprocess.TimeoutExpired:
            failed_reason = "timeout"
        finally:
            os.system('pkill -9 -f "FedX-1.0-SNAPSHOT.jar"')

        exec_time = time.time() - t_start
        os.chdir(old_cwd)

        if str(stats) != "/dev/null":
            proxy_stats = proxy_client.get_stats()
            base = stats.parent

            (base / "http_req.txt").write_text(str(proxy_stats.get("NB_HTTP_REQ", 0)))
            (base / "ask.txt").write_text(str(proxy_stats.get("NB_ASK", 0)))
            (base / "data_transfer.txt").write_text(str(proxy_stats.get("DATA_TRANSFER", 0)))
            (base / "exec_time.txt").write_text(str(exec_time))

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
        if infile.stat().st_size == 0:
            outfile.touch()
            return

        records = []
        with open(infile) as f:
            for line in f.readlines():
                bindings = re.sub(r"(\[|\])", "", line.strip()).split(";")
                record: dict[str, str] = {}
                for binding in bindings:
                    b = binding.split("=")
                    key = b[0]
                    value = "".join(b[1:])
                    value = re.sub(r'"(.*)"(\^\^|@).*', r"\1", value)
                    value = value.replace('"', "")
                    record[key] = value
                records.append(record)

        pd.DataFrame.from_records(records).to_csv(outfile, index=False)

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
                r"StatementPattern\s+(\(new scope\)\s+)?Var\s+\((name=\w+,\s+value=(.*),\s+anonymous|name=(\w+))\)"
                r"\s+Var\s+\((name=\w+,\s+value=(.*),\s+anonymous|name=(\w+))\)"
                r"\s+Var\s+\((name=\w+,\s+value=(.*),\s+anonymous|name=(\w+))\)"
            )
            m = re.match(pattern, x)
            s = m.group(3) or m.group(4)
            p = m.group(6) or m.group(7)
            o = m.group(9) or m.group(10)
            return " ".join([s, p, o])

        def extract_source_selection(x: str) -> list[str]:
            pattern = r"StatementSource\s+\(id=sparql_([a-z]+(\.\w+)+\.[a-z]+)_,\s+type=[A-Z]+\)"
            return [cg[0] for cg in re.findall(pattern, x)]

        with open(composition_file) as f:
            composition = json.load(f)
        inv_composition = {f"{' '.join(v)}": k for k, v in composition.items()}

        in_df = pd.read_csv(infile)
        in_df["triple"] = in_df["triple"].apply(extract_triple)
        in_df["tp_name"] = in_df["triple"].apply(lambda x: inv_composition[x])
        in_df["tp_number"] = in_df["tp_name"].str.replace("tp", "", regex=False).astype(int)
        in_df.sort_values("tp_number", inplace=True)
        in_df["source_selection"] = in_df["source_selection"].apply(extract_source_selection)

        # Patch 2: pad before pivot-explode to handle unequal source selection lengths (q05 fix)
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
