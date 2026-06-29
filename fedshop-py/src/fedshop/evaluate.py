"""Phase 4: Evaluation loop.

Iterates over (engine, query, instance, batch, attempt) combinations,
runs each engine, transforms outputs, and writes stats.csv.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .config import BenchmarkConfig
from .proxy import ProxyClient


def check_timeout_propagation(results_txt: Path) -> bool:
    """Return True if the previous batch timed out.

    FedX writes an empty results.txt both when the query returns 0 rows AND when
    it times out. We distinguish by checking the adjacent stats.csv: only treat
    it as a timeout when stats.csv says exec_time == "timeout".
    """
    if not results_txt.exists():
        return False
    stats_csv = results_txt.parent / "stats.csv"
    if stats_csv.exists():
        try:
            df = pd.read_csv(stats_csv)
            if not df.empty and str(df.iloc[0]["exec_time"]) == "timeout":
                return True
            return False
        except Exception:
            pass
    return results_txt.stat().st_size == 0


def _write_stats_failure(
    stats_path: Path,
    engine: str,
    query: str,
    instance: int,
    batch: int,
    attempt: int,
    reason: str,
) -> None:
    row = {
        "engine": engine,
        "query": query,
        "instance": str(instance),
        "batch": str(batch),
        "attempt": str(attempt),
        "exec_time": reason,
        "source_selection_time": reason,
        "planning_time": reason,
        "ask": reason,
        "http_req": reason,
        "data_transfer": reason,
    }
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([row]).to_csv(stats_path, index=False)


def run_evaluation(
    config: BenchmarkConfig,
    engine_name: str,
    query_name: str,
    instance_id: int,
    batch_id: int,
    attempt: int,
    bench_dir: Path,
    *,
    noexec: bool = False,
    proxy_client: ProxyClient | None = None,
) -> Path:
    """Run a single (engine, query, instance, batch, attempt) combination.

    Returns path to the stats.csv file written.
    """
    from .engines.anapsid import AnapsidAdapter
    from .engines.costfed import CostFedAdapter
    from .engines.fedshop_go import FedShopGoAdapter
    from .engines.fedx import FedXAdapter
    from .engines.pyfedx import PyFedXAdapter
    from .engines.rsa import RsaAdapter
    from .engines.semagrow import SemagrowAdapter
    from .engines.splendid import SplendidAdapter

    engine_adapters = {
        "fedx": FedXAdapter,
        "pyfedx": PyFedXAdapter,
        "costfed": CostFedAdapter,
        "fedshop-go": FedShopGoAdapter,
        "anapsid": AnapsidAdapter,
        "semagrow": SemagrowAdapter,
        "splendid": SplendidAdapter,
        "rsa": RsaAdapter,
    }

    if engine_name not in engine_adapters:
        import warnings
        warnings.warn(f"No adapter for engine '{engine_name}', skipping. Known: {list(engine_adapters)}")
        return Path("/dev/null")

    adapter_cls = engine_adapters[engine_name]
    adapter = adapter_cls(config)

    out_dir = bench_dir / "evaluation" / engine_name / query_name / f"instance_{instance_id}" / f"batch_{batch_id}" / f"attempt_{attempt}"
    out_dir.mkdir(parents=True, exist_ok=True)

    stats_path = out_dir / "stats.csv"
    results_txt = out_dir / "results.txt"
    source_sel_txt = out_dir / "source_selection.txt"
    query_plan_txt = out_dir / "query_plan.txt"
    results_csv = out_dir / "results.csv"
    provenance_csv = out_dir / "provenance.csv"

    # Every attempt owns a complete artifact set.  Truncate it up front so a
    # timeout, runtime failure, or skipped query cannot expose files from an
    # older run under the current attempt path.
    for artifact in (
        results_txt,
        source_sel_txt,
        query_plan_txt,
        results_csv,
        provenance_csv,
    ):
        artifact.write_text("")

    if batch_id > 0:
        prev_results = (
            bench_dir / "evaluation" / engine_name / query_name /
            f"instance_{instance_id}" / f"batch_{batch_id - 1}" / f"attempt_{attempt}" / "results.txt"
        )
        if check_timeout_propagation(prev_results):
            _write_stats_failure(stats_path, engine_name, query_name, instance_id, batch_id, attempt, "timeout")
            results_txt.touch()
            source_sel_txt.touch()
            query_plan_txt.touch()
            results_csv.touch()
            provenance_csv.touch()
            return stats_path

    query_path = bench_dir / "generation" / query_name / f"instance_{instance_id}" / "injected.sparql"
    composition_file = bench_dir / "generation" / query_name / f"instance_{instance_id}" / "composition.json"

    if not query_path.exists():
        import warnings
        warnings.warn(f"No injected query for {query_name}/instance_{instance_id} (value selection produced no rows), skipping.")
        _write_stats_failure(stats_path, engine_name, query_name, instance_id, batch_id, attempt, "no_query")
        return stats_path

    workdir = Path(config.generation.workdir)
    proxy_mapping_file = workdir / f"virtuoso-proxy-mapping-batch{batch_id}.json"
    proxy_mapping: dict[str, str] = {}
    if proxy_mapping_file.exists():
        proxy_mapping = json.loads(proxy_mapping_file.read_text())

    if noexec:
        _write_stats_failure(stats_path, engine_name, query_name, instance_id, batch_id, attempt, "timeout")
        results_txt.touch()
        source_sel_txt.touch()
        query_plan_txt.touch()
        results_csv.touch()
        provenance_csv.touch()
        return stats_path

    if proxy_client is None:
        proxy_client = ProxyClient(config.evaluation.proxy.endpoint)

    adapter.generate_config_file(batch_id, proxy_mapping)
    adapter.run_benchmark(
        query_path=query_path,
        batch_id=batch_id,
        out_result=results_txt,
        out_source_selection=source_sel_txt,
        query_plan=query_plan_txt,
        stats=stats_path,
        noexec=noexec,
        proxy_client=proxy_client,
    )

    adapter.transform_results(results_txt, results_csv)
    if composition_file.exists():
        adapter.transform_provenance(source_sel_txt, provenance_csv, composition_file)
    else:
        provenance_csv.touch()

    return stats_path


def run_all_evaluations(
    config: BenchmarkConfig,
    bench_dir: Path,
    *,
    engine_filter: str | None = None,
    query_filter: str | None = None,
    proxy_client: ProxyClient | None = None,
) -> None:
    """Run evaluations for all (engine, query, instance, batch, attempt) combinations."""
    gen = config.generation
    evl = config.evaluation

    gen_dir = bench_dir / "generation"
    if not gen_dir.exists():
        raise FileNotFoundError(f"Generation directory not found: {gen_dir}")

    query_names = sorted(p.name for p in gen_dir.iterdir() if p.is_dir())
    if query_filter:
        query_names = [q for q in query_names if q == query_filter]

    engines = list(evl.engines.keys())
    if engine_filter:
        engines = [e for e in engines if e == engine_filter]

    for engine_name in engines:
        for query_name in query_names:
            for instance_id in range(gen.n_query_instances):
                for batch_id in range(gen.n_batch):
                    for attempt in range(evl.n_attempts):
                        run_evaluation(
                            config=config,
                            engine_name=engine_name,
                            query_name=query_name,
                            instance_id=instance_id,
                            batch_id=batch_id,
                            attempt=attempt,
                            bench_dir=bench_dir,
                            proxy_client=proxy_client,
                        )
