"""Semagrow engine adapter.

Ported from reference-repos/FedShop/fedshop/engines/semagrow.py.
Key characteristics:
  - Two Maven components: rdf4j/ (engine) + sevod-scraper (summary generator)
  - Generates per-endpoint VoID summaries via sevod-scraper, merges with rdflib
  - Results are already CSV format (direct copy)
  - Source selection format: tps;sources semicolon-delimited CSV with FedX-like StatementPattern triples
  - summary_generator_dir is read from engine config extra fields
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from io import StringIO
from pathlib import Path

import urllib.parse
import urllib.request

import pandas as pd

from ..config import BenchmarkConfig
from ..engines.base import EngineAdapter
from ..engines.fedx import _pad, _wait_virtuoso
from ..proxy import ProxyClient


class SemagrowAdapter(EngineAdapter):

    def __init__(self, config: BenchmarkConfig, engine_dir: Path | None = None) -> None:
        engine_entry = config.evaluation.engines.get("semagrow")
        if engine_dir is None:
            if engine_entry is None:
                raise KeyError("No 'semagrow' engine entry in config")
            engine_dir = Path(engine_entry.dir)
        self.summary_generator_dir = Path(
            engine_entry.extra.get("summary_generator_dir", "") if engine_entry else ""
        )
        super().__init__(config, engine_dir)

    @staticmethod
    def _maven_settings_path() -> str:
        """Write a temp settings.xml that redirects the dead maven.tinyjee.org plugin repo.

        Maven 3.8+ blocks HTTP plugin repositories by default. The semagrow root pom.xml
        declares maven.tinyjee.org (dead, HTTP-only) for aspectj-maven-plugin used by the
        monitor module. Redirecting it to Maven Central lets the build succeed without
        touching the submodule sources.
        """
        settings_xml = (
            '<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0"'
            ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
            ' xsi:schemaLocation="http://maven.apache.org/SETTINGS/1.0.0'
            ' http://maven.apache.org/xsd/settings-1.0.0.xsd">\n'
            "  <mirrors>\n"
            "    <mirror>\n"
            "      <id>tinyjee-to-central</id>\n"
            "      <url>https://repo1.maven.org/maven2</url>\n"
            "      <mirrorOf>maven.tinyjee.org</mirrorOf>\n"
            "    </mirror>\n"
            "  </mirrors>\n"
            "</settings>\n"
        )
        fd, path = tempfile.mkstemp(suffix=".xml", prefix="semagrow-mvn-settings-")
        with os.fdopen(fd, "w") as f:
            f.write(settings_xml)
        return path

    def prerequisites(self) -> None:
        old_cwd = os.getcwd()
        settings = self._maven_settings_path()
        try:
            # Semagrow: build only the modules needed to run the CLI.
            # http-endpoint and webgui require old war plugin incompatible with Java 21.
            # monitor uses aspectj-maven-plugin from the dead maven.tinyjee.org repo;
            # the temp settings.xml above redirects it to Maven Central.
            os.chdir(self.engine_dir.resolve())
            cmd = (
                f"mvn install dependency:copy-dependencies package"
                f" -Dmaven.test.skip=true -Daspectj.skip=true"
                f" --projects commons,core-api,monitor,core,sparql,rdf4j -am"
                f" -s {settings}"
            )
            if os.system(cmd) != 0:
                raise RuntimeError(f"Could not compile semagrow at {self.engine_dir}")
            # sevod-scraper: build only commons, sparql, cli (rdfdump-spark requires Scala).
            os.chdir(self.summary_generator_dir.resolve())
            cmd = (
                f"mvn install dependency:copy-dependencies package"
                f" -Dmaven.test.skip=true"
                f" --projects commons,sparql,cli -am"
                f" -s {settings}"
            )
            if os.system(cmd) != 0:
                raise RuntimeError(f"Could not compile sevod-scraper at {self.summary_generator_dir}")
        finally:
            os.unlink(settings)
            os.chdir(old_cwd)

    def generate_config_file(self, batch_id: int, proxy_mapping: dict[str, str]) -> Path:
        summary_file = (self.engine_dir / f"summaries/metadata-fedshop-batch{batch_id}.ttl").resolve()
        repo_file = (self.engine_dir / f"summaries/repo-fedshop-batch{batch_id}.ttl").resolve()

        summary_file.parent.mkdir(parents=True, exist_ok=True)

        # SemagrowSailFactory.initializeMetadata() loads the metadata file via new File(filename).
        # That resolves relative paths against the JVM's CWD, not via FileUtils. Write the absolute
        # path so the JVM can find the file regardless of CWD.
        metadata_name = str(summary_file)

        # Always regenerate repo_file so it uses metadata_name (not an old absolute path)
        repo_file.write_text(
            "################################################################################\n"
            "# Sesame configuration for SemaGrow\n"
            "#\n"
            "# ATTENTION: the Sail implementing the sail:sailType must be published\n"
            "#            in META-INF/services/org.openrdf.sail.SailFactory\n"
            "################################################################################\n"
            "@prefix void: <http://rdfs.org/ns/void#>.\n"
            "@prefix rep:  <http://www.openrdf.org/config/repository#>.\n"
            "@prefix sr:   <http://www.openrdf.org/config/repository/sail#>.\n"
            "@prefix sail: <http://www.openrdf.org/config/sail#>.\n"
            "@prefix semagrow: <http://schema.semagrow.eu/>.\n"
            "@prefix quetsal: <http://quetsal.aksw.org/>.\n"
            "\n"
            "[] a rep:Repository ;\n"
            "\trep:repositoryTitle \"SemaGrow Repository\" ;\n"
            "\trep:repositoryID \"semagrow\" ;\n"
            "\trep:repositoryImpl [\n"
            "\t\trep:repositoryType \"semagrow:SemagrowRepository\" ;\n"
            "\t\tsr:sailImpl [\n"
            "\t\t\tsail:sailType \"semagrow:SemagrowSail\" ;\n"
            f"\t\t\tsemagrow:metadataInit \"{metadata_name}\" ;\n"
            "\t\t\tsemagrow:executorBatchSize \"8\" ;\n"
            "\t\t\tsemagrow:sourceSelectors \"PREFIX\"\n"
            "\t\t]\n"
            "\t] ."
        )

        # Generate summary if absent or any endpoint is missing from it
        update_summary = False
        endpoints = list(proxy_mapping.values())
        if summary_file.exists():
            summary_txt = summary_file.read_text()
            if not all(ep in summary_txt for ep in endpoints):
                update_summary = True
        else:
            update_summary = True

        if update_summary:
            self._generate_flat_void_metadata(proxy_mapping, summary_file)

        return repo_file

    def _generate_flat_void_metadata(self, proxy_mapping: dict[str, str], output_file: Path) -> None:
        """Generate flat VoID metadata by querying each endpoint for its distinct predicates.

        Produces direct void:property and void:triples on dataset nodes (no partition blank nodes),
        which lets Semagrow's VOIDSourceSelector work without SEVOD/RDFS inference.
        """
        lines = [
            "@prefix void: <http://rdfs.org/ns/void#> .",
            "@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
            "@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .",
            "@prefix sevod: <http://semagrow.eu/sevod#> .",
            "",
        ]
        for i, (graph_uri, endpoint) in enumerate(proxy_mapping.items()):
            dataset_uri = f"<http://example.org/dataset{i}>"
            # Parse endpoint base URL (remove query params for host detection)
            base_url = endpoint.split("?")[0]

            # Query for distinct predicates in this endpoint's named graph
            sparql_query = (
                f"SELECT DISTINCT ?p WHERE {{ GRAPH <{graph_uri}> {{ ?s ?p ?o }} }}"
            )
            params = urllib.parse.urlencode({"query": sparql_query})
            req_url = f"{base_url}?{params}"
            try:
                with urllib.request.urlopen(req_url, timeout=30) as resp:
                    content = resp.read().decode()
            except Exception:
                content = ""

            # Extract predicate URIs from SPARQL XML results: <uri>http://...</uri>
            predicates: list[str] = re.findall(r"<uri>([^<]+)</uri>", content)

            # Query for triple count
            count_query = f"SELECT (COUNT(*) AS ?c) WHERE {{ GRAPH <{graph_uri}> {{ ?s ?p ?o }} }}"
            count_params = urllib.parse.urlencode({"query": count_query})
            count_url = f"{base_url}?{count_params}"
            triple_count = 0
            try:
                with urllib.request.urlopen(count_url, timeout=30) as resp:
                    count_txt = resp.read().decode()
                nums = re.findall(r"<literal[^>]*>(\d+)</literal>", count_txt)
                if nums:
                    triple_count = int(nums[0])
            except Exception:
                triple_count = 0

            # Write flat dataset description
            lines.append(f"{dataset_uri} a void:Dataset ;")
            lines.append(f"    void:sparqlEndpoint <{endpoint}> ;")
            lines.append(f'    void:triples "{triple_count}"^^xsd:integer ;')
            # Subject/object regex patterns for URI-prefix-based source selection
            domain = graph_uri.rstrip("/")
            lines.append(f'    <http://semagrow.eu/sevod#subjectRegexPattern> "{domain}/" ;')
            lines.append(f'    <http://semagrow.eu/sevod#objectRegexPattern> "{domain}/" ;')
            for pred in predicates:
                lines.append(f"    void:property <{pred}> ;")
            lines[-1] = lines[-1].rstrip(" ;") + " ."
            lines.append("")

        output_file.write_text("\n".join(lines))

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

        summary_file = (self.engine_dir / f"summaries/metadata-fedshop-batch{batch_id}.ttl").resolve()
        repo_file = (self.engine_dir / f"summaries/repo-fedshop-batch{batch_id}.ttl").resolve()
        tmp_results = Path(tempfile.mktemp(suffix=".csv", prefix="semagrow_"))

        proxy_cfg = self.config.evaluation.proxy
        timeout = self.config.evaluation.timeout

        if proxy_client is None:
            proxy_client = ProxyClient(proxy_cfg.endpoint)

        virt_port = self.config.generation.virtuoso.port
        _wait_virtuoso(f"http://localhost:{virt_port}/sparql")
        proxy_client.reset()

        # FileUtils.getFile("repository.ttl") checks /tmp/repository.ttl before the classloader.
        # The metadata path is written as an absolute path in repository.ttl, so it's loaded
        # via new File(absolutePath) directly — no /tmp copy needed for metadata.
        tmp_repo = Path("/tmp/repository.ttl")
        shutil.copy(repo_file, tmp_repo)

        # Resolve to absolute paths before any os.chdir
        tmp_results_abs = tmp_results.resolve()
        out_result_abs = out_result.resolve()
        query_path_abs = query_path.resolve()
        stats_abs = stats if str(stats) == "/dev/null" else stats.resolve()
        base = stats_abs.parent
        base.mkdir(parents=True, exist_ok=True)

        # CliMain takes positional args: args[0]=config_path args[1]=SPARQL_text args[2]=output_path
        # We use java -cp directly to avoid Maven overhead and control the classpath precisely.
        cp = (
            "rdf4j/target/classes:"
            "core/target/classes:"
            "core-api/target/classes:"
            "commons/target/classes:"
            "sparql/target/classes:"
            "rdf4j/target/dependency/*"
        )
        query_text = query_path_abs.read_text()

        # Do not set http.proxyHost/proxyPort: Semagrow's Apache HttpClient hangs when a
        # system proxy is configured (even with nonProxyHosts), while endpoints bypass the
        # proxy anyway (host.docker.internal in nonProxyHosts → NB_HTTP_REQ=0 like FedX).
        java_args = [
            "java",
            "-Xmx2g",
            "-Dhttp.keepAlive=false",
            "-cp", cp,
            "org.semagrow.cli.CliMain",
            "repository.ttl",   # args[0]: logged; resolver reads /tmp/repository.ttl via FileUtils
            query_text,          # args[1]: SPARQL query text (not file path)
            str(tmp_results_abs),  # args[2]: output file path
        ]

        old_cwd = os.getcwd()
        os.chdir(self.engine_dir)

        t_start = time.time()
        log_handle = None
        stdout_target = subprocess.DEVNULL
        if str(stats_abs) != "/dev/null":
            log_handle = (base / "engine.log").open("wb")
            stdout_target = log_handle
        proc = subprocess.Popen(
            java_args, stdout=stdout_target, stderr=subprocess.STDOUT
        )
        failed_reason: str | None = None

        try:
            proc.wait(timeout)
            if proc.returncode == 0 and tmp_results_abs.exists() and tmp_results_abs.stat().st_size > 0:
                shutil.copy(tmp_results_abs, out_result_abs)
            elif proc.returncode != 0:
                failed_reason = "error_runtime"
        except subprocess.TimeoutExpired:
            failed_reason = "timeout"
        finally:
            os.system("pkill -9 -f 'org.semagrow.cli.CliMain'")
            if log_handle is not None:
                log_handle.close()

        exec_time = time.time() - t_start
        os.chdir(old_cwd)

        if str(stats_abs) != "/dev/null":
            proxy_stats = proxy_client.get_stats()
            (base / "exec_time.txt").write_text(str(exec_time))
            (base / "http_req.txt").write_text(str(proxy_stats.get("NB_HTTP_REQ", 0)))
            (base / "ask.txt").write_text(str(proxy_stats.get("NB_ASK", 0)))
            (base / "data_transfer.txt").write_text(str(proxy_stats.get("DATA_TRANSFER", 0)))
            self._write_stats(stats_abs, failed_reason)

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
        try:
            df = pd.read_csv(infile)
            df.drop_duplicates(inplace=True)
            df.to_csv(outfile, index=False)
        except (pd.errors.EmptyDataError, ValueError):
            outfile.touch()

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

        # Semagrow source selection: tps;sources CSV, one entry per StatementPattern
        clean = "tps;sources\n" + raw.replace(")\n", ")").replace("n\n", "n")
        in_df = pd.read_csv(StringIO(clean), sep=";")
        in_df = in_df.groupby("tps")["sources"].apply(list).reset_index(name="sources")

        with open(prefix_cache_file) as pf, open(composition_file) as cf:
            prefix2alias: dict[str, str] = json.load(pf)
            composition = json.load(cf)

        comp = {k: " ".join(v) for k, v in composition.items()}
        inv_comp: dict[str, list[str]] = {}
        for k, v in comp.items():
            inv_comp.setdefault(v, []).append(k)

        def extract_triple(x: str) -> str:
            pattern = (
                r"StatementPattern\s+?Var\s+\((name=\w+,\s+value=(.*),\s+anonymous|name=(\w+))\)"
                r"\s+Var\s+\((name=\w+,\s+value=(.*),\s+anonymous|name=(\w+))\)"
                r"\s+Var\s+\((name=\w+,\s+value=(.*),\s+anonymous|name=(\w+))\)"
            )
            match = re.match(pattern, x)
            if match is None:
                return x

            s = match.group(2) if match.group(2) is not None else f"?{match.group(3)}"
            p = match.group(5) if match.group(5) is not None else f"?{match.group(6)}"
            o = match.group(8) if match.group(8) is not None else f"?{match.group(9)}"
            result = " ".join([s, p, o])

            for prefix, alias in prefix2alias.items():
                result = result.replace(prefix, f"{alias}:")

            if s.startswith("http"):
                result = result.replace(s, f"<{s}>")
            if o.startswith("http"):
                result = result.replace(o, f"<{o}>")
            return result

        def lookup_composition(x: str) -> list[str]:
            result = re.sub(r"[\[\]]", "", x).strip()
            for prefix, alias in prefix2alias.items():
                result = re.sub(rf"<{re.escape(prefix)}(\w+)>", rf"{alias}:\1", result)
            return inv_comp[result]

        in_df["tps"] = in_df["tps"].apply(extract_triple)
        in_df["tp_name"] = in_df["tps"].apply(lookup_composition)
        in_df = in_df.explode("tp_name")
        in_df["tp_number"] = in_df["tp_name"].str.replace("tp", "", regex=False).astype(int)
        in_df.sort_values("tp_number", inplace=True)

        max_length = int(in_df["sources"].apply(len).max())
        in_df["sources"] = in_df["sources"].apply(lambda x: _pad(x, max_length))

        out_df = (
            in_df.set_index("tp_name")["sources"]
            .to_frame()
            .T
            .apply(pd.Series.explode)
            .reset_index(drop=True)
        )
        out_df.to_csv(outfile, index=False)
