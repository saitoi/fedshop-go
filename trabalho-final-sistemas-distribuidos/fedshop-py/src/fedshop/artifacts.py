from __future__ import annotations

import hashlib
import json
import math
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
from rdflib import BNode, Literal, URIRef
from rdflib import Dataset

from .config import BenchmarkConfig


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _stable_id(prefix: str, payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(_json_dumps(payload).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def default_artifact_db(config: BenchmarkConfig, bench_dir: Path | str | None = None) -> Path:
    return Path(config.generation.workdir).resolve().parent / "fedshop.duckdb"


class ArtifactStore:
    """Small DuckDB-backed artifact catalog for the simplified FedShop pipeline."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = duckdb.connect(str(self.db_path))
        self.initialize()

    def initialize(self) -> None:
        con = self.connection
        con.execute("create schema if not exists input")
        con.execute("create schema if not exists output")
        con.execute("create schema if not exists meta")

        con.execute(
            """
            create table if not exists input.config (
                config_id text primary key,
                profile text,
                seed integer,
                use_docker boolean,
                batch_count integer,
                members_per_batch integer,
                attempts integer,
                product_count integer,
                bench_dir text,
                workdir text,
                queries_dir text,
                artifact_db text,
                config_json json,
                created_at timestamp
            )
            """
        )
        con.execute(
            """
            create table if not exists input.rdf (
                config_id text,
                batch_id integer,
                source_name text,
                source_type text,
                graph text,
                subject text,
                predicate text,
                object text,
                object_type text,
                object_datatype text,
                object_lang text,
                file_path text,
                row_number integer
            )
            """
        )
        con.execute(
            """
            create table if not exists input.queries (
                config_id text,
                query_id text,
                selection_batch_id integer,
                template_path text,
                const_path text,
                template_sparql text,
                const_json json,
                selected_values_json json,
                injected_sparql text,
                composition_json json,
                injected_path text,
                composition_path text
            )
            """
        )
        con.execute(
            """
            create table if not exists output.executions (
                run_id text,
                config_id text,
                engine text,
                query_id text,
                batch_id integer,
                attempt integer,
                status text,
                exec_time double,
                source_selection_time double,
                planning_time double,
                join_time double,
                ask integer,
                http_req integer,
                data_transfer double,
                started_at timestamp,
                finished_at timestamp,
                stats_path text,
                results_path text,
                provenance_path text,
                source_selection_path text,
                query_plan_path text,
                raw_stats_path text,
                error_message text
            )
            """
        )
        con.execute(
            """
            create table if not exists output.results (
                config_id text,
                result_kind text,
                engine text,
                query_id text,
                batch_id integer,
                attempt integer,
                row_number integer,
                bindings_json json,
                result_hash text
            )
            """
        )
        con.execute(
            """
            create table if not exists output.source_selection (
                run_id text,
                config_id text,
                engine text,
                query_id text,
                batch_id integer,
                attempt integer,
                tp_name text,
                tp_number integer,
                triple_pattern text,
                selected_sources_json json,
                selected_source_count integer,
                source_selection_path text
            )
            """
        )
        con.execute(
            """
            create table if not exists output.metrics (
                run_id text,
                config_id text,
                engine text,
                query text,
                batch integer,
                attempt integer,
                status text,
                nb_results double,
                nb_ref_results double,
                mismatch boolean,
                precision double,
                recall double,
                f1 double,
                nb_spurious double,
                nb_missing double,
                nb_duplicates double,
                missing_vars double,
                exec_time double,
                source_selection_time double,
                planning_time double,
                join_time double,
                ask double,
                http_req double,
                data_transfer double,
                tpwss double,
                avg_rwss double,
                min_rwss double,
                max_rwss double,
                nb_distinct_sources double,
                relevant_sources_selectivity double,
                false_positive_sources double,
                redundant_requests double,
                is_timeout boolean,
                is_error boolean
            )
            """
        )
        con.execute(
            """
            create table if not exists meta.artifacts (
                artifact_id text,
                config_id text,
                run_id text,
                phase text,
                artifact_kind text,
                logical_name text,
                path text,
                content_hash text,
                size_bytes bigint,
                created_at timestamp
            )
            """
        )

    def persist_config(
        self,
        config: BenchmarkConfig,
        *,
        bench_dir: Path | str,
        artifact_db: Path | str | None = None,
        profile: str = "smoke",
        seed: int = 42,
    ) -> str:
        artifact_path = Path(artifact_db) if artifact_db is not None else self.db_path
        product_count = int(config.generation.schema["product"].params.get("product_n", 0))
        batch_count = int(config.generation.n_batch)
        vendor_n = int(config.generation.schema["vendor"].params.get("vendor_n", batch_count * 10))
        members_per_batch = vendor_n // batch_count if batch_count else 0
        config_json = self._simplified_config_json(config)
        payload = {
            "profile": profile,
            "seed": seed,
            "use_docker": config.use_docker,
            "batch_count": batch_count,
            "members_per_batch": members_per_batch,
            "attempts": int(config.evaluation.n_attempts),
            "product_count": product_count,
            "bench_dir": str(bench_dir),
            "workdir": str(config.generation.workdir),
            "queries_dir": str(config.generation.queries_dir),
            "artifact_db": str(artifact_path),
            "config_json": config_json,
        }
        config_id = _stable_id("cfg", payload)
        self.connection.execute("delete from input.config where config_id = ?", [config_id])
        self.connection.execute(
            """
            insert into input.config values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                config_id,
                profile,
                seed,
                bool(config.use_docker),
                batch_count,
                members_per_batch,
                int(config.evaluation.n_attempts),
                product_count,
                str(bench_dir),
                str(config.generation.workdir),
                str(config.generation.queries_dir),
                str(artifact_path),
                _json_dumps(config_json),
                _now_iso(),
            ],
        )
        return config_id

    def persist_query(
        self,
        *,
        config_id: str,
        query_id: str,
        selection_batch_id: int,
        template_path: Path,
        const_path: Path,
        template_sparql: str,
        const_json: dict[str, Any],
        selected_values: pd.DataFrame,
        injected_sparql: str,
        composition_json: dict[str, Any],
        injected_path: Path,
        composition_path: Path,
    ) -> None:
        self.connection.execute(
            "delete from input.queries where config_id = ? and query_id = ?",
            [config_id, query_id],
        )
        self.connection.execute(
            """
            insert into input.queries values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                config_id,
                query_id,
                int(selection_batch_id),
                str(template_path),
                str(const_path),
                template_sparql,
                _json_dumps(const_json),
                _json_dumps(selected_values.to_dict(orient="records")),
                injected_sparql,
                _json_dumps(composition_json),
                str(injected_path),
                str(composition_path),
            ],
        )

    def _simplified_config_json(self, config: BenchmarkConfig) -> dict[str, Any]:
        engines: dict[str, Any] = {}
        if "pyfedx" in config.evaluation.engines:
            engines["pyfedx"] = {"dir": self._rel_engine_dir(config.evaluation.engines["pyfedx"].dir)}
        if "fedshop-go" in config.evaluation.engines:
            entry = config.evaluation.engines["fedshop-go"]
            engines["fedshop-go"] = {
                "dir": self._rel_engine_dir(entry.dir),
                "selector": entry.extra.get("selector", "ask"),
                "join": entry.extra.get("join", "bind"),
                "planner": entry.extra.get("planner", "source-count"),
                "max_concurrency": int(entry.extra.get("max_concurrency", 4)),
            }

        return {
            "paths": {
                "inputs_dir": self._rel_config_path(Path(config.generation.queries_dir).parent),
                "queries_dir": self._rel_config_path(config.generation.queries_dir),
                "templates_dir": self._rel_config_path(Path(config.generation.schema["product"].template).parent),
                "dataset_dir": self._rel_config_path(config.generation.virtuoso.data_dir),
                "docker_dir": self._rel_config_path(Path(config.generation.virtuoso.compose_file).parent),
            },
            "virtuoso": {
                "port": int(config.generation.virtuoso.port),
                "endpoint": config.generation.virtuoso.default_endpoint,
            },
            "proxy": {
                "port": int(config.evaluation.proxy.port),
                "endpoint": config.evaluation.proxy.endpoint,
            },
            "engines": engines,
            "watdiv": {
                "product": {
                    "template": Path(config.generation.schema["product"].template).name,
                    "scale_factor": int(config.generation.schema["product"].scale_factor),
                    "params": {
                        "feature_c": config.generation.schema["product"].params.get("feature_c", 9),
                        "type_c": config.generation.schema["product"].params.get("type_c", 9),
                    },
                },
                "vendor": {
                    "template": Path(config.generation.schema["vendor"].template).name,
                    "scale_factor": int(config.generation.schema["vendor"].scale_factor),
                },
                "ratingsite": {
                    "template": Path(config.generation.schema["ratingsite"].template).name,
                    "scale_factor": int(config.generation.schema["ratingsite"].scale_factor),
                },
            },
        }

    @staticmethod
    def _rel_engine_dir(path: str) -> str:
        text = str(path)
        if text.endswith("/scripts"):
            return "scripts"
        if text.endswith("/go-engine"):
            return "../go-engine"
        return text

    @staticmethod
    def _rel_config_path(path: str | Path) -> str:
        path_obj = Path(path).resolve(strict=False)
        parts = path_obj.parts
        if "inputs" in parts:
            idx = parts.index("inputs")
            return str(Path(*parts[idx:]))
        if parts and parts[-1] == "docker":
            return "docker"
        return str(path)

    def persist_execution_from_files(
        self,
        *,
        config_id: str,
        engine: str,
        query_id: str,
        batch_id: int,
        attempt: int,
        stats_path: Path,
        results_path: Path,
        provenance_path: Path,
        source_selection_path: Path,
        query_plan_path: Path,
        raw_stats_path: Path | None = None,
        error_message: str | None = None,
    ) -> str:
        run_id = _stable_id(
            "run",
            {
                "config_id": config_id,
                "engine": engine,
                "query_id": query_id,
                "batch_id": batch_id,
                "attempt": attempt,
            },
        )
        row = self._read_stats(stats_path)
        status = "ok"
        exec_raw = row.get("exec_time")
        try:
            exec_time = float(exec_raw)
        except (TypeError, ValueError):
            exec_time = math.nan
            status = str(exec_raw) if exec_raw is not None else "missing"

        self.connection.execute("delete from output.executions where run_id = ?", [run_id])
        self.connection.execute(
            """
            insert into output.executions values (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                run_id,
                config_id,
                engine,
                query_id,
                int(batch_id),
                int(attempt),
                status,
                self._float_or_none(exec_time),
                self._float_field(row, "source_selection_time"),
                self._float_field(row, "planning_time"),
                self._float_field(row, "join_time"),
                self._int_field(row, "ask"),
                self._int_field(row, "http_req"),
                self._float_field(row, "data_transfer"),
                None,
                _now_iso(),
                str(stats_path),
                str(results_path),
                str(provenance_path),
                str(source_selection_path),
                str(query_plan_path),
                str(raw_stats_path) if raw_stats_path else None,
                error_message,
            ],
        )
        return run_id

    def persist_results_csv(
        self,
        *,
        config_id: str,
        result_kind: str,
        engine: str | None,
        query_id: str,
        batch_id: int,
        attempt: int | None,
        csv_path: Path,
    ) -> None:
        self.connection.execute(
            """
            delete from output.results
            where config_id = ? and result_kind = ? and coalesce(engine, '') = ?
              and query_id = ? and batch_id = ? and coalesce(attempt, -1) = ?
            """,
            [config_id, result_kind, engine or "", query_id, int(batch_id), int(attempt) if attempt is not None else -1],
        )
        if not csv_path.exists() or csv_path.stat().st_size == 0:
            return
        df = pd.read_csv(csv_path)
        for row_number, record in enumerate(df.to_dict(orient="records")):
            bindings = _json_dumps(record)
            self.connection.execute(
                "insert into output.results values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    config_id,
                    result_kind,
                    engine,
                    query_id,
                    int(batch_id),
                    int(attempt) if attempt is not None else None,
                    row_number,
                    bindings,
                    hashlib.sha256(bindings.encode("utf-8")).hexdigest(),
                ],
            )

    def persist_source_selection_csv(
        self,
        *,
        run_id: str,
        config_id: str,
        engine: str,
        query_id: str,
        batch_id: int,
        attempt: int,
        csv_path: Path,
    ) -> None:
        self.connection.execute("delete from output.source_selection where run_id = ?", [run_id])
        if not csv_path.exists() or csv_path.stat().st_size == 0:
            return
        df = pd.read_csv(csv_path)
        for idx, record in enumerate(df.to_dict(orient="records")):
            raw_sources = record.get("source_selection", "[]")
            try:
                sources = json.loads(raw_sources) if isinstance(raw_sources, str) else list(raw_sources)
            except (TypeError, ValueError):
                sources = []
            tp_name = record.get("tp_name") or f"tp{idx}"
            tp_number = int(str(tp_name).replace("tp", "")) if str(tp_name).startswith("tp") else idx
            self.connection.execute(
                "insert into output.source_selection values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    run_id,
                    config_id,
                    engine,
                    query_id,
                    int(batch_id),
                    int(attempt),
                    tp_name,
                    tp_number,
                    str(record.get("triple", "")),
                    _json_dumps(sources),
                    len(sources),
                    str(csv_path),
                ],
            )

    def persist_metrics(self, config_id: str, metrics: pd.DataFrame) -> None:
        for record in metrics.to_dict(orient="records"):
            run_id = _stable_id(
                "run",
                {
                    "config_id": config_id,
                    "engine": record.get("engine"),
                    "query_id": record.get("query"),
                    "batch_id": record.get("batch"),
                    "attempt": record.get("attempt"),
                },
            )
            self.connection.execute(
                """
                delete from output.metrics
                where config_id = ? and engine = ? and query = ? and batch = ?
                  and coalesce(attempt, -1) = ?
                """,
                [
                    config_id,
                    record.get("engine"),
                    record.get("query"),
                    self._int_value(record.get("batch")),
                    self._int_value(record.get("attempt"), default=-1),
                ],
            )
            self.connection.execute(
                """
                insert into output.metrics values (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                [
                    run_id,
                    config_id,
                    record.get("engine"),
                    record.get("query"),
                    self._int_value(record.get("batch")),
                    self._int_value(record.get("attempt")),
                    record.get("status"),
                    self._float_value(record.get("nb_results")),
                    self._float_value(record.get("nb_ref_results")),
                    self._bool_value(record.get("mismatch")),
                    self._float_value(record.get("precision")),
                    self._float_value(record.get("recall")),
                    self._float_value(record.get("f1")),
                    self._float_value(record.get("nb_spurious")),
                    self._float_value(record.get("nb_missing")),
                    self._float_value(record.get("nb_duplicates")),
                    self._float_value(record.get("missing_vars")),
                    self._float_value(record.get("exec_time")),
                    self._float_value(record.get("source_selection_time")),
                    self._float_value(record.get("planning_time")),
                    self._float_value(record.get("join_time")),
                    self._float_value(record.get("ask")),
                    self._float_value(record.get("http_req")),
                    self._float_value(record.get("data_transfer")),
                    self._float_value(record.get("tpwss")),
                    self._float_value(record.get("avg_rwss")),
                    self._float_value(record.get("min_rwss")),
                    self._float_value(record.get("max_rwss")),
                    self._float_value(record.get("nb_distinct_sources")),
                    self._float_value(record.get("relevant_sources_selectivity")),
                    self._float_value(record.get("false_positive_sources")),
                    self._float_value(record.get("redundant_requests")),
                    self._bool_value(record.get("is_timeout")),
                    self._bool_value(record.get("is_error")),
                ],
            )

    def persist_rdf_file(
        self,
        *,
        config_id: str,
        batch_id: int,
        source_name: str,
        source_type: str,
        graph: str,
        file_path: Path,
    ) -> None:
        self.connection.execute(
            """
            delete from input.rdf
            where config_id = ? and batch_id = ? and source_name = ? and file_path = ?
            """,
            [config_id, int(batch_id), source_name, str(file_path)],
        )
        if not file_path.exists() or file_path.stat().st_size == 0:
            return

        rdf_graph = Dataset()
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DeprecationWarning, module="rdflib")
            rdf_graph.parse(str(file_path), format="nquads")
        quads = sorted(
            rdf_graph.quads((None, None, None, None)),
            key=lambda q: (str(q[0]), str(q[1]), str(q[2]), self._rdf_graph_value(q[3])),
        )
        for row_number, quad in enumerate(quads):
            subject, predicate, obj, ctx = quad
            graph_value = self._rdf_graph_value(ctx) if ctx is not None else graph
            object_type = self._rdf_object_type(obj)
            self.connection.execute(
                "insert into input.rdf values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    config_id,
                    int(batch_id),
                    source_name,
                    source_type,
                    graph_value,
                    str(subject),
                    str(predicate),
                    str(obj),
                    object_type,
                    str(obj.datatype) if isinstance(obj, Literal) and obj.datatype else None,
                    str(obj.language) if isinstance(obj, Literal) and obj.language else None,
                    str(file_path),
                    row_number,
                ],
            )

    @staticmethod
    def _read_stats(path: Path) -> dict[str, Any]:
        if not path.exists() or path.stat().st_size == 0:
            return {}
        try:
            return pd.read_csv(path).iloc[0].to_dict()
        except Exception:
            return {}

    @staticmethod
    def _float_or_none(value: Any) -> float | None:
        try:
            f = float(value)
        except (TypeError, ValueError):
            return None
        return None if math.isnan(f) else f

    @classmethod
    def _float_field(cls, row: dict[str, Any], key: str) -> float | None:
        return cls._float_value(row.get(key))

    @classmethod
    def _int_field(cls, row: dict[str, Any], key: str) -> int | None:
        return cls._int_value(row.get(key))

    @staticmethod
    def _float_value(value: Any) -> float | None:
        try:
            f = float(value)
        except (TypeError, ValueError):
            return None
        return None if math.isnan(f) else f

    @staticmethod
    def _int_value(value: Any, default: int | None = None) -> int | None:
        try:
            f = float(value)
        except (TypeError, ValueError):
            return default
        if math.isnan(f):
            return default
        return int(f)

    @staticmethod
    def _bool_value(value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, float) and math.isnan(value):
            return None
        if isinstance(value, str):
            return value.lower() in {"true", "1", "yes"}
        return bool(value)

    @staticmethod
    def _rdf_object_type(value: Any) -> str:
        if isinstance(value, URIRef):
            return "iri"
        if isinstance(value, Literal):
            return "literal"
        if isinstance(value, BNode):
            return "blank"
        return "unknown"

    @staticmethod
    def _rdf_graph_value(value: Any) -> str:
        identifier = getattr(value, "identifier", None)
        return str(identifier if identifier is not None else value)
