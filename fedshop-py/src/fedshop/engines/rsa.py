"""RSA engine adapter (FedUP source selection + Jena Fuseki execution).

Ported from reference-repos/FedShop/fedshop/engines/rsa.py.
RSA = Reference Source Assignment: uses FedUP to build a federated SERVICE
query from a pre-computed summary index, then executes it on Jena Fuseki.

Key differences from the reference Click CLI:
- Uses current FedUP jar (FedUPCLI + SummarizerCLI) instead of the old
  fr.gdd.fedup.utils.QuerySourceSelectionExplain class.
- Summary (fedup-id) is built with tdb2.xloader from NQ files per batch (cached).
- FedUPCLI --explain -e None writes the SERVICE query to stderr; we parse it out.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse
import pandas as pd
import requests

from ..config import BenchmarkConfig
from ..engines.base import EngineAdapter
from ..proxy import ProxyClient


def _jena_alive(url: str) -> bool:
    try:
        r = requests.get(url, params={"query": "ASK {?s ?p ?o}"}, timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _wait_jena(url: str, max_wait: int = 60) -> None:
    deadline = time.time() + max_wait
    while time.time() < deadline:
        if _jena_alive(url):
            return
        time.sleep(2)
    raise RuntimeError(f"Jena Fuseki did not become ready at {url} within {max_wait}s")


def _modulo_on_suffix(uri: str) -> str:
    """Reduce a URI to scheme://host (ModuloOnSuffix(1))."""
    p = urlparse(uri)
    if not p.scheme or not p.netloc:
        return uri
    return f"{p.scheme}://{p.netloc}"


def _transform_nq_line(line: str) -> str:
    """Apply FedUP's LeavePredicateUntouched + ModuloOnSuffix(1) to one NQ line.

    The FedUP Summary uses ModuloOnSuffix via LeavePredicateUntouched, which:
      - transforms subject URI → scheme://host
      - leaves predicate URI UNCHANGED
      - transforms object URI → scheme://host; replaces any literal → "any"
      - leaves graph URI UNCHANGED (not touched by LeavePredicateUntouched)

    But for the VALUES/GRAPH clause matching to work, the graph in TDB2 must
    also be scheme://host (no trailing slash), so we DO transform the graph too.

    NQ files use tab-separated fields:
      <subject>\\t<predicate>\\t<object>\\t<graph> .
    """
    if not line or line.startswith('#') or not line.strip():
        return line

    parts = line.rstrip('\n').split('\t')
    if len(parts) < 4:
        return line

    subj, pred = parts[0], parts[1]
    obj_raw = parts[2]
    graph_dot = parts[3]  # e.g. "<http://www.vendor0.fr/> ."

    # Transform subject (always <URI> or _:blank)
    if subj.startswith('<') and subj.endswith('>'):
        subj = f"<{_modulo_on_suffix(subj[1:-1])}>"

    # Predicate: leave unchanged (LeavePredicateUntouched)

    # Transform object
    if obj_raw.startswith('<') and obj_raw.endswith('>'):
        # URI object → scheme://host
        obj_out = f"<{_modulo_on_suffix(obj_raw[1:-1])}>"
    elif obj_raw.startswith('"') or obj_raw.startswith("'"):
        # Any literal → "any" (ModuloOnSuffix maps Node_Literal → "any")
        obj_out = '"any"'
    else:
        # blank node or other
        obj_out = obj_raw

    # Transform graph (extract <URI> from "<URI> .")
    g_match = re.match(r'^(<[^>]+>)\s*\.\s*$', graph_dot)
    if g_match:
        g_uri = g_match.group(1)[1:-1]
        g_out = f"<{_modulo_on_suffix(g_uri)}>"
        graph_dot_out = f"{g_out} ."
    else:
        graph_dot_out = graph_dot

    return f"{subj}\t{pred}\t{obj_out}\t{graph_dot_out}\n"


def _transform_nq_to_tmpdir(nq_files: list[str], tmp_dir: Path) -> list[str]:
    """Write ModuloOnSuffix-transformed copies of nq_files into tmp_dir."""
    out_paths = []
    for src in nq_files:
        dst = tmp_dir / Path(src).name
        with open(src) as fin, open(dst, "w") as fout:
            for raw in fin:
                fout.write(_transform_nq_line(raw))
        out_paths.append(str(dst))
    return out_paths


_SPARQL_START_RE = re.compile(r"^\s*(SELECT|ASK|CONSTRUCT|DESCRIBE)\b", re.IGNORECASE)


def _extract_service_query(stderr_content: str) -> str | None:
    """Parse the SERVICE query out of FedUPCLI --explain stderr output.

    FedUPCLI prints (to stderr):
      1. The original query
      2. Timing / INFO log lines from the optimizer
      3. Jena algebra dump (via log.info "Built the following query")
      4. The SPARQL SERVICE query (via OpAsQuery.asQuery().toString())
      5. "Took X ms to perform the source assignment."

    We scan backward from the timing line to find the last SELECT/ASK/CONSTRUCT
    line that starts the actual SPARQL query.
    """
    lines = stderr_content.splitlines()
    # Step 1: find "Took X ms to perform the source assignment."
    assignment_idx = None
    for i, line in enumerate(lines):
        if re.match(r"Took \d+ ms to perform the source assignment", line):
            assignment_idx = i
            break
    if assignment_idx is None:
        return None
    # Step 2: scan backward for a line starting with SELECT/ASK/CONSTRUCT/DESCRIBE.
    # The SPARQL query ends just before the assignment timing line (possibly with
    # an empty line gap), so find the block that ends at assignment_idx.
    sparql_start = None
    for i in range(assignment_idx - 1, -1, -1):
        if _SPARQL_START_RE.match(lines[i]):
            sparql_start = i
            break
    if sparql_start is None:
        return None
    query = "\n".join(lines[sparql_start:assignment_idx]).strip()
    if not query:
        return None
    # If log lines are present in the extracted text, FedUP failed to produce a
    # SERVICE query (optimizer returned null) and we accidentally grabbed the
    # original query + log output. Treat this as no query.
    if "[main] INFO" in query or "[main] DEBUG" in query or "[main] WARN" in query:
        return None
    return query


class RsaAdapter(EngineAdapter):

    def __init__(self, config: BenchmarkConfig, engine_dir: Path | None = None) -> None:
        entry = config.evaluation.engines["rsa"]
        if engine_dir is None:
            engine_dir = Path(entry.dir)
        super().__init__(config, engine_dir)
        self.fedup_dir = Path(entry.extra.get("fedup_dir", ""))
        self.endpoint = entry.extra.get("endpoint", "http://localhost:3030/FedShop/query")
        self.compose_file = entry.extra.get("compose_file", "")
        self.service_name = entry.extra.get("service_name", "jena-fuseki")
        self.container_name = entry.extra.get("container_name", "docker-jena-fuseki-1")

        self._fedup_jar = str(self.fedup_dir / "target" / "fedup.jar")
        self._jena_bin = str(self.engine_dir / "jena" / "bin")

    def prerequisites(self) -> None:
        if self.fedup_dir and self.fedup_dir.exists():
            old_cwd = os.getcwd()
            os.chdir(self.fedup_dir)
            if os.system("mvn clean install dependency:copy-dependencies package -Dmaven.test.skip=true") != 0:
                raise RuntimeError("Could not build FedUP")
            os.chdir(old_cwd)

    def generate_config_file(self, batch_id: int, proxy_mapping: dict[str, str]) -> Path:
        fedup_dir = self.fedup_dir
        federation_file = fedup_dir / f"config/fedshop/endpoints_batch{batch_id}.txt"
        summary_dir = fedup_dir / f"summaries/fedshop/batch{batch_id}"

        # Write endpoints file (one federation member IRI per line).
        federation_file.parent.mkdir(parents=True, exist_ok=True)
        federation_members = self.config.generation.virtuoso.federation_members
        members = list(federation_members.get(f"batch{batch_id}", {}).values())
        federation_file.write_text("\n".join(members) + "\n")

        # Build FedUP TDB2 summary from batch NQ files if not already cached.
        # The summary must use ModuloOnSuffix-transformed graph URIs (scheme://host,
        # no trailing slash) so that FedUP's source-selection query, which also applies
        # ModuloOnSuffix to the query's GRAPH variables, finds matches in the TDB2.
        # We pre-transform the NQ files in a temp dir before loading with tdbloader.
        # Do NOT pre-create summary_dir: an empty dir looks "ready" but is an empty TDB2.
        summary_ready = summary_dir.exists() and any(summary_dir.iterdir())
        if not summary_ready:
            dataset_dir = Path(self.config.generation.virtuoso.data_dir)
            member_names = list(self.config.generation.virtuoso.federation_members
                                .get(f"batch{batch_id}", {}).keys())
            nq_files = [str(dataset_dir / f"{name}.nq") for name in member_names
                        if (dataset_dir / f"{name}.nq").exists()]
            if not nq_files:
                raise RuntimeError(f"No NQ files found for batch {batch_id} members")
            tdbloader = str(Path(self._jena_bin) / "tdb2.tdbloader")
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                transformed = _transform_nq_to_tmpdir(nq_files, tmp_path)
                cmd = [tdbloader, "--loc", str(summary_dir)] + transformed
                result = subprocess.run(cmd, capture_output=False, timeout=1200)
            if result.returncode != 0:
                raise RuntimeError(f"tdb2.tdbloader failed for batch {batch_id}")

        # Start Jena Fuseki if not responding.
        if not _jena_alive(self.endpoint):
            os.system(f"docker compose -f {self.compose_file} up -d {self.service_name}")
            _wait_jena(self.endpoint)

        return federation_file

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

        proxy_cfg = self.config.evaluation.proxy
        timeout = self.config.evaluation.timeout

        if proxy_client is None:
            proxy_client = ProxyClient(proxy_cfg.endpoint)

        proxy_client.reset()

        fedup_dir = self.fedup_dir
        summary_dir = fedup_dir / f"summaries/fedshop/batch{batch_id}"

        # Build --modify lambda: transforms TDB2 graph URIs to Virtuoso named-graph SPARQL URLs.
        # host.docker.internal resolves to 127.0.0.1 on macOS host AND to the host IP inside
        # Docker containers, so this URL works for both FedUP ASK queries (host side) and
        # for Jena Fuseki SERVICE query execution (inside Docker).
        virt = self.config.generation.virtuoso
        virtuoso_base = f"http://host.docker.internal:{virt.port}/sparql?default-graph-uri="
        # TDB2 summary graphs use ModuloOnSuffix URIs (e.g. http://www.vendor0.fr, no slash).
        # Virtuoso named graphs have a trailing slash (http://www.vendor0.fr/), so add it back.
        modify_lambda = f'(e) -> "{virtuoso_base}" + e + "/"'

        failed_reason: str | None = None
        t_start = time.time()

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
            stderr_file = tf.name

        try:
            timeout_prefix = ["timeout", "--signal=SIGKILL", str(timeout)] if timeout != 0 else []
            cmd = timeout_prefix + [
                "java",
                "-Dorg.slf4j.simpleLogger.defaultLogLevel=info",
                "-jar", self._fedup_jar,
                "-f", str(query_path.resolve()),
                "-s", str(summary_dir),
                "--modify", modify_lambda,
                "-e", "None",
                "--explain",
            ]

            with open(stderr_file, "w") as sf:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=sf,
                )
            try:
                proc.wait(timeout if timeout != 0 else None)
                if proc.returncode not in (0, None):
                    failed_reason = "error_runtime"
            except subprocess.TimeoutExpired:
                proc.kill()
                failed_reason = "timeout"

            # Parse SERVICE query from stderr.
            stderr_content = Path(stderr_file).read_text()
            service_query = _extract_service_query(stderr_content)

            if service_query:
                query_plan.write_text(service_query)
            else:
                if failed_reason is None:
                    failed_reason = "error_runtime"

        finally:
            Path(stderr_file).unlink(missing_ok=True)

        # Execute SERVICE query via arq CLI (avoids Jena Fuseki OOM on large queries).
        if failed_reason is None and query_plan.stat().st_size > 0:
            arq_bin = str(Path(self._jena_bin) / "arq")
            arq_timeout = timeout if timeout != 0 else 600
            try:
                arq_cmd = (
                    ["timeout", "--signal=SIGKILL", str(arq_timeout)]
                    + [arq_bin, "--query", str(query_plan), "--results", "CSV"]
                )
                arq_result = subprocess.run(
                    arq_cmd,
                    capture_output=True,
                    text=True,
                    timeout=arq_timeout + 5,
                )
                if arq_result.returncode == 0 and arq_result.stdout.strip():
                    out_result.write_text(arq_result.stdout)
                else:
                    failed_reason = "error_runtime"
            except Exception:
                failed_reason = "error_runtime"

        exec_time = time.time() - t_start

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
            if metric == "exec_time" and failed_reason is not None:
                row[metric] = failed_reason
                continue
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
        shutil.copy(infile, outfile)

    def transform_provenance(
        self,
        infile: Path,
        outfile: Path,
        composition_file: Path,
    ) -> None:
        if not infile.read_text().strip():
            outfile.touch()
            return
        shutil.copy(infile, outfile)
