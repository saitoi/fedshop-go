"""ANAPSID engine adapter.

Ported from reference-repos/FedShop/fedshop/engines/anapsid.py.
Key characteristics:
  - Python 2.7-based engine; requires python2 binary on PATH
  - Batches > 4 are skipped (ANAPSID saturates regex at larger federation sizes)
  - ANAPSID writes exec_time.txt, planning_time.txt, source_selection_time.txt, ask.txt itself
  - Source selection format: custom URL→triple mapping, parsed with ANAPSID-specific regex
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pandas as pd

from ..config import BenchmarkConfig
from ..engines.base import EngineAdapter
from ..engines.fedx import _pad
from ..proxy import ProxyClient

ANAPSID_MAX_BATCH = 4


def _python2_bin() -> str:
    """Locate the Python 2.7 binary, accounting for pyenv shims."""
    path = shutil.which("python2")
    if path is None:
        raise RuntimeError("Python 2.7 is required to run ANAPSID.")
    if "shims" in path:
        path = path.replace("shims", "versions/2.7.18/bin")
    return path


class AnapsidAdapter(EngineAdapter):

    def __init__(self, config: BenchmarkConfig, engine_dir: Path | None = None) -> None:
        if engine_dir is None:
            engine_dir = Path(config.evaluation.engines["anapsid"].dir)
        super().__init__(config, engine_dir)

    def prerequisites(self) -> None:
        python2 = _python2_bin()
        pip2 = f"{python2} -m pip"
        cmd = (
            f"rm -rf build && "
            f"{pip2} install -r requirements.txt --no-cache --force-reinstall && "
            f"{pip2} install . --no-cache --force-reinstall"
        )
        old_cwd = os.getcwd()
        os.chdir(self.engine_dir)
        if os.system(cmd) != 0:
            raise RuntimeError("Could not install ANAPSID")
        os.chdir(old_cwd)

    def generate_config_file(self, batch_id: int, proxy_mapping: dict[str, str]) -> Path:
        old_cwd = os.getcwd()
        os.chdir(self.engine_dir)

        Path("summaries").mkdir(parents=True, exist_ok=True)
        endpoints_file = f"summaries/endpoints_batch{batch_id}.txt"
        summary_file = f"summaries/sum_fedshop_batch{batch_id}.txt"

        federation_members = self.config.generation.virtuoso.federation_members
        endpoints: list[str] = []
        for iri in federation_members[f"batch{batch_id}"].values():
            if iri in proxy_mapping:
                endpoints.append(proxy_mapping[iri])

        with open(endpoints_file, "w") as f:
            for ep in endpoints:
                f.write(f"{ep}\n")

        update_required = False
        if not Path(summary_file).exists():
            update_required = True
        else:
            content = Path(summary_file).read_text()
            for ep in endpoints:
                if ep not in content:
                    update_required = True
                    break

        if update_required:
            tmp_file = f"{summary_file}.tmp"
            with open(tmp_file, "w") as f:
                for ep in sorted(endpoints):
                    f.write(f"{ep}\n")
            # get_predicates is a Python 2.7 script bundled with ANAPSID
            python2 = _python2_bin()
            cmd = f"{python2} scripts/get_predicates {tmp_file} {summary_file}"
            os.system(cmd)
            Path(tmp_file).unlink(missing_ok=True)

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

        if batch_id > ANAPSID_MAX_BATCH:
            # ANAPSID saturates regex engine at batch 5+; skip with timeout stats.
            # Leave metric .txt files absent so _write_stats fills them with failed_reason.
            if str(stats) != "/dev/null":
                self._write_stats(stats, "timeout")
            return

        summary_file = f"summaries/sum_fedshop_batch{batch_id}.txt"
        proxy_endpoint = self.config.evaluation.proxy.endpoint
        timeout = self.config.evaluation.timeout

        if proxy_client is None:
            proxy_client = ProxyClient(proxy_endpoint)
        proxy_client.reset()

        base = stats.parent
        python2 = _python2_bin()
        env_prefix = f'HTTP_PROXY={proxy_endpoint} HTTPS_PROXY={proxy_endpoint} NO_PROXY=""'
        timeout_cmd = f"timeout --signal=SIGKILL {timeout}" if timeout != 0 else ""

        cmd = (
            f"{env_prefix} {timeout_cmd} {python2} scripts/run_anapsid "
            f"-e {summary_file} "
            f"-q {query_path.resolve()} "
            f"-p naive -s False -o False -d SSGM -a True "
            f"-r {out_result.resolve()} "
            f"-z {(base / 'ask.txt').resolve()} "
            f"-y {(base / 'planning_time.txt').resolve()} "
            f"-x {query_plan.resolve()} "
            f"-v {out_source_selection.resolve()} "
            f"-u {(base / 'source_selection_time.txt').resolve()} "
            f"-n {(base / 'exec_time.txt').resolve()} "
            f"-c {str(noexec)}"
        ).strip()

        old_cwd = os.getcwd()
        os.chdir(self.engine_dir)
        proc = subprocess.Popen(
            cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        failed_reason: str | None = None

        try:
            proc.wait(timeout=timeout)
            if proc.returncode != 0:
                error_file = base / "error.txt"
                if error_file.exists():
                    failed_reason = error_file.read_text().strip()
                    if failed_reason == "type_error":
                        (base / "ask.txt").unlink(missing_ok=True)
                else:
                    failed_reason = "error_runtime"
        except subprocess.TimeoutExpired:
            failed_reason = "timeout"
        finally:
            os.system('pkill -9 -f "scripts/run_anapsid"')

        os.chdir(old_cwd)

        if str(stats) != "/dev/null":
            proxy_stats = proxy_client.get_stats()
            # Overwrite ask/http_req/data_transfer with proxy canonical values.
            # exec_time.txt, planning_time.txt, source_selection_time.txt are
            # written by ANAPSID itself and left intact.
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
        content = infile.read_text().strip()
        if not content:
            outfile.touch()
            return
        # ANAPSID produces a custom dict-like format; eval() reconstructs the binding dicts.
        lines = re.findall(r"(?:[a-zA-Z0-9\-_\.:\^\/'\"<># ]+){?", content)
        dict_list = [eval("{" + line + "}") for line in lines if line.strip()]  # noqa: S307
        pd.DataFrame(dict_list).to_csv(outfile, index=False)

    def transform_provenance(
        self,
        infile: Path,
        outfile: Path,
        composition_file: Path,
    ) -> None:
        prefix_cache_file = composition_file.parent / "prefix_cache.json"

        raw = infile.read_text()
        if not raw.strip():
            outfile.touch()
            return

        if not prefix_cache_file.exists():
            outfile.touch()
            return

        # Parse ANAPSID source selection: each entry is (source_url, triple_block)
        pattern = (
            r"((?:http://www\.(?:vendor|ratingsite)[0-9]+\.fr/))>', \[\n\s+"
            r"((?:[a-zA-Z0-9\-_\.:\?\^/'\"<>=#\n ]+))(?:\n\+)?"
        )
        matches = re.findall(pattern, raw)

        mydict: dict[str, list[str]] = {}
        for url, triple_block in matches:
            if re.search(r"\n\s+", triple_block):
                triples = re.split(r",\s+\n\s+", triple_block)
            else:
                triples = [triple_block]
            for triple in triples:
                triple = triple.strip()
                if triple not in mydict:
                    mydict[triple] = []
                if url not in mydict[triple]:
                    mydict[triple].append(url)

        raw_ss = pd.DataFrame(
            [(k, v) for k, v in mydict.items()],
            columns=["triples", "sources"],
        )

        with open(prefix_cache_file) as pf, open(composition_file) as cf:
            prefix_cache_dict = json.load(pf)
            composition = json.load(cf)

        comp = {k: " ".join(v) for k, v in composition.items()}
        inv_comp: dict[str, list[str]] = {}
        for k, v in comp.items():
            inv_comp.setdefault(v, []).append(k)

        def get_triple_id(x: str) -> list[str]:
            result = re.sub(r"[\[\]]", "", x).strip()
            for prefix, alias in prefix_cache_dict.items():
                result = re.sub(rf"<{re.escape(prefix)}(\w+)>", rf"{alias}:\1", result)
            return inv_comp[result]

        raw_ss["triples"] = raw_ss["triples"].apply(lambda x: re.split(r"\s*,\s*", x))
        raw_ss = raw_ss.explode("triples")
        raw_ss["triples"] = raw_ss["triples"].apply(get_triple_id)
        raw_ss = raw_ss.explode("triples")
        raw_ss["tp_number"] = (
            raw_ss["triples"].str.replace("tp", "", regex=False).astype(int)
        )
        raw_ss.sort_values("tp_number", inplace=True)
        raw_ss["sources"] = raw_ss["sources"].apply(
            lambda x: re.split(r"\s*,\s*", re.sub(r"[\[\]]", "", str(x)))
        )

        max_length = int(raw_ss["sources"].apply(len).max())
        raw_ss["sources"] = raw_ss["sources"].apply(lambda x: _pad(x, max_length))

        out_df = (
            raw_ss.set_index("triples")["sources"]
            .to_frame()
            .T
            .apply(pd.Series.explode)
            .reset_index(drop=True)
        )
        out_df.to_csv(outfile, index=False)
