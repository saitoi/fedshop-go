from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class VirtuosoConfig:
    compose_file: str
    service_name: str
    isql: str
    data_dir: str
    port: int
    default_url: str
    default_endpoint: str
    batch_members: list[str]
    federation_members: dict[str, dict[str, str]]


@dataclass
class SchemaEntry:
    is_source: bool
    provenance: str
    template: str
    scale_factor: int
    export_output_dir: str
    export_dep_output_dir: str | None
    params: dict[str, Any]


@dataclass
class GeneratorConfig:
    dir: str
    exec: str


@dataclass
class GenerationConfig:
    workdir: str
    queries_dir: str
    n_batch: int
    n_query_instances: int
    verbose: bool
    generator: GeneratorConfig
    virtuoso: VirtuosoConfig
    schema: dict[str, SchemaEntry]


@dataclass
class ProxyConfig:
    compose_file: str
    service_name: str
    host: str
    port: int
    endpoint: str
    container_name: str


@dataclass
class EngineEntry:
    dir: str
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class EvaluationConfig:
    n_attempts: int
    timeout: int
    proxy: ProxyConfig
    engines: dict[str, EngineEntry]


@dataclass
class BenchmarkConfig:
    use_docker: bool
    generation: GenerationConfig
    evaluation: EvaluationConfig


def _resolve_string(value: str, flat: dict[str, Any]) -> str:
    """Resolve ${path.to.key} references in a string using a flat lookup dict.

    Uses [^${}]+ to match innermost refs first so nested ${outer: ${inner}}
    expressions resolve correctly across multiple passes.
    """
    def replacer(m: re.Match) -> str:
        key = m.group(1).strip()
        resolved = flat.get(key, m.group(0))
        return str(resolved)

    prev = None
    result = value
    while prev != result:
        prev = result
        result = re.sub(r"\$\{([^${}]+)\}", replacer, result)
    return result


def _flatten(d: dict, prefix: str = "", out: dict | None = None) -> dict[str, Any]:
    """Flatten a nested dict to dot-separated keys."""
    if out is None:
        out = {}
    for k, v in d.items():
        key = f"{prefix}{k}" if prefix else k
        if isinstance(v, dict):
            _flatten(v, key + ".", out)
        else:
            out[key] = v
    return out


def _resolve_all(raw: dict, seed: dict[str, Any] | None = None) -> dict:
    """
    Multi-pass resolver: flatten, then iteratively apply custom resolvers and
    ${} string interpolation until the dict stabilises.

    OmegaConf custom resolvers in config_small.yaml are evaluated as:
      normal_dist / normal_truncated → mean (first arg)
      multiply → product of two numbers
      divide → integer division
      get_product_* → small fixed defaults
      get_docker_endpoints / get_virtuoso_containers / get_proxy_target → []

    ``seed`` pre-populates the flat dict with auto-variables (e.g. config_dir)
    before the YAML keys are merged in, so they are available for ${} refs.
    """
    flat = {**(seed or {}), **_flatten(raw)}

    def apply_custom_resolvers(s: str) -> str:
        """Replace all ${custom_resolver: ...} patterns with their computed values."""
        # normal_dist(mu, sigma, avg) → avg (getValue returns ≈ avg when randVal ≈ mu)
        s = re.sub(
            r"\$\{normal_dist:\s*[^,}]+,\s*[^,}]+,\s*([^}]+)\}",
            lambda m: m.group(1).strip(),
            s,
        )
        # normal_truncated(mu, sigma, lower, upper) → mu (representative mean)
        s = re.sub(
            r"\$\{normal_truncated:\s*([^,}]+),\s*[^}]+\}",
            lambda m: m.group(1).strip(),
            s,
        )
        s = re.sub(r"\$\{get_product_producer_n:[^}]+\}", "250", s)
        s = re.sub(r"\$\{get_product_feature_n:[^}]+\}", "150", s)
        s = re.sub(r"\$\{get_product_type_n:[^}]+\}", "150", s)
        s = re.sub(r"\$\{get_docker_endpoints:[^}]+\}", "[]", s)
        s = re.sub(r"\$\{get_virtuoso_containers:[^}]+\}", "[]", s)
        s = re.sub(r"\$\{get_proxy_target:[^}]*\}", "[]", s)
        return s

    def apply_math_resolvers(s: str, current_flat: dict) -> str:
        """Resolve ${multiply:} and ${divide:} using the current flat dict."""
        # multiply: literal numbers
        s = re.sub(
            r"\$\{multiply:\s*(\d+),\s*(\d+)\}",
            lambda m: str(int(m.group(1)) * int(m.group(2))),
            s,
        )
        # multiply: with ref
        def _multiply_ref(m: re.Match) -> str:
            ref_val = current_flat.get(m.group(2))
            if ref_val is None or not str(ref_val).lstrip("-").isdigit():
                return m.group(0)
            return str(int(m.group(1)) * int(ref_val))
        s = re.sub(r"\$\{multiply:\s*(\d+),\s*\$\{([^}]+)\}\}", _multiply_ref, s)

        # divide: ${divide: ${ref}, n}
        def _divide_ref(m: re.Match) -> str:
            ref_val = current_flat.get(m.group(1))
            if ref_val is None or not str(ref_val).lstrip("-").isdigit():
                return m.group(0)
            return str(int(ref_val) // int(m.group(2)))
        s = re.sub(r"\$\{divide:\s*\$\{([^}]+)\},\s*(\d+)\}", _divide_ref, s)

        # divide: ${divide: literal, n} (ref already resolved to a number)
        s = re.sub(
            r"\$\{divide:\s*(\d+),\s*(\d+)\}",
            lambda m: str(int(m.group(1)) // int(m.group(2))),
            s,
        )
        return s

    def coerce(v: Any) -> Any:
        if not isinstance(v, str):
            return v
        try:
            return int(v)
        except (ValueError, TypeError):
            pass
        try:
            return float(v)
        except (ValueError, TypeError):
            pass
        return v

    # Iteratively resolve until stable.
    # Order matters: resolve ${key.path} refs first so nested refs inside custom
    # resolver args (e.g. ${get_product_producer_n: ${...product_n}}) are already
    # plain values when the [^}]+ pattern runs.
    for _ in range(10):
        prev = dict(flat)
        new_flat: dict[str, Any] = {}
        for k, v in flat.items():
            if isinstance(v, str):
                v = _resolve_string(v, flat)
                v = apply_custom_resolvers(v)
                v = apply_math_resolvers(v, flat)
                v = _resolve_string(v, flat)
                v = coerce(v)
            new_flat[k] = v
        flat = new_flat
        if flat == prev:
            break

    return flat


def _rebuild(raw: dict, flat: dict[str, Any], prefix: str = "") -> dict:
    """Rebuild a nested dict from a flat resolved dict."""
    result: dict[str, Any] = {}
    for k, v in raw.items():
        key = f"{prefix}{k}" if prefix else k
        if isinstance(v, dict):
            result[k] = _rebuild(v, flat, key + ".")
        else:
            result[k] = flat.get(key, v)
    return result


def _project_path(project_root: Path, value: str | Path) -> str:
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str(project_root / path)


def _derive_federation_members(n_batch: int, members_per_batch: int) -> dict[str, dict[str, str]]:
    federation_members: dict[str, dict[str, str]] = {}
    for batch_id in range(n_batch):
        upper = (batch_id + 1) * members_per_batch
        members: dict[str, str] = {}
        for vendor_id in range(upper):
            members[f"vendor{vendor_id}"] = f"http://www.vendor{vendor_id}.fr/"
        for ratingsite_id in range(upper):
            members[f"ratingsite{ratingsite_id}"] = f"http://www.ratingsite{ratingsite_id}.fr/"
        federation_members[f"batch{batch_id}"] = members
    return federation_members


def _expand_compact_config(raw: dict[str, Any], config_path: Path) -> dict[str, Any]:
    """Expand the simplified project config into the internal legacy shape."""
    if "generation" in raw:
        return raw

    project_root = config_path.resolve().parents[2]
    scale = raw.get("scale", {})
    queries = raw.get("queries", {})
    inputs = raw.get("inputs", {})
    services = raw.get("services", {})
    evaluation = raw.get("evaluation", {})
    engines = evaluation.get("engines", {})

    n_batch = int(scale.get("batches", 2))
    members_per_batch = int(scale.get("members_per_batch", 10))
    product_count = int(scale.get("product_count", 20000))
    product_scale_factor = int(scale.get("product_scale_factor", 1))
    source_scale_factor = int(scale.get("source_scale_factor", 1))
    feature_c = int(scale.get("feature_c", 9))
    type_c = int(scale.get("type_c", 9))
    offer_n = int(scale.get("offer_n", 20))
    review_n = int(scale.get("review_n", 100))

    workdir = _project_path(project_root, inputs.get("workdir", "data"))
    dataset_dir = _project_path(project_root, inputs.get("dataset", "inputs/product-dataset"))
    templates_dir = Path(_project_path(project_root, inputs.get("templates", "inputs/templates")))
    queries_dir = _project_path(project_root, queries.get("dir", "inputs/queries"))
    watdiv_dir = _project_path(project_root, inputs.get("watdiv", "../../reference-repos/watdiv"))

    virtuoso_port = int(services.get("virtuoso_port", 8890))
    virtuoso_service_name = str(services.get("virtuoso_service_name", "bsbm-virtuoso"))
    virtuoso_compose_file = str(services.get("virtuoso_compose_file", "docker/virtuoso.yml"))
    proxy_host = str(services.get("proxy_host", "localhost"))
    proxy_port = int(services.get("proxy_port", 5555))

    engine_defaults: dict[str, dict[str, Any]] = {
        "fedshop-go": {
            "dir": "../../go-engine",
            "selector": "ask",
            "join": "bind",
            "planner": "source-count",
            "max_concurrency": 4,
        },
        "pyfedx": {"dir": "../../scripts"},
    }
    expanded_engines: dict[str, dict[str, Any]] = {}
    for name in dict.fromkeys([*engine_defaults, *engines]):
        edata = {**engine_defaults.get(name, {}), **(engines.get(name) or {})}
        edata["dir"] = _project_path(project_root, edata.get("dir", ""))
        if "max_concurrency" in edata:
            edata["max_concurrency"] = int(edata["max_concurrency"])
        expanded_engines[name] = edata

    return {
        "use_docker": bool(raw.get("use_docker", True)),
        "generation": {
            "workdir": workdir,
            "queries_dir": queries_dir,
            "n_batch": n_batch,
            "n_query_instances": int(queries.get("instances", 1)),
            "verbose": bool(raw.get("verbose", False)),
            "generator": {
                "dir": watdiv_dir,
                "exec": str(Path(watdiv_dir) / "bin" / "Release" / "watdiv"),
            },
            "virtuoso": {
                "compose_file": _project_path(project_root, virtuoso_compose_file),
                "service_name": virtuoso_service_name,
                "isql": "/opt/virtuoso-opensource/bin/isql",
                "data_dir": dataset_dir,
                "port": virtuoso_port,
                "default_url": f"http://localhost:{virtuoso_port}",
                "default_endpoint": f"http://localhost:{virtuoso_port}/sparql",
                "batch_members": [
                    f"http://www.batch{batch_id}.fr/"
                    for batch_id in range(n_batch)
                ],
                "federation_members": _derive_federation_members(n_batch, members_per_batch),
                "endpoints": [],
                "container_names": [],
            },
            "schema": {
                "product": {
                    "is_source": False,
                    "provenance": "http://www4.wiwiss.fu-berlin.de/bizer/bsbm/v01/vocabulary/",
                    "template": str(templates_dir / "bsbm-product.template"),
                    "scale_factor": product_scale_factor,
                    "export_output_dir": str(Path(workdir) / "product"),
                    "params": {
                        "product_n": product_count,
                        "producer_n": 250,
                        "feature_n": 150,
                        "feature_c": feature_c,
                        "type_n": 150,
                        "type_c": type_c,
                        "productPropertyTextual4_p": 0.7,
                        "productPropertyTextual5_p": 0.8,
                        "productPropertyNumeric4_p": 0.7,
                        "productPropertyNumeric5_p": 0.8,
                        "textual_wc": 9,
                        "label_wc": 2,
                        "comment_wc": 100,
                        "type_comment_wc": 35,
                        "feature_comment_wc": 35,
                        "producer_comment_wc": 35,
                    },
                },
                "vendor": {
                    "is_source": True,
                    "provenance": "http://www.{%vendor_id}.fr/",
                    "template": str(templates_dir / "bsbm-vendor.template"),
                    "export_output_dir": dataset_dir,
                    "export_dep_output_dir": str(Path(workdir) / "product"),
                    "scale_factor": source_scale_factor,
                    "params": {
                        "vendor_n": n_batch * members_per_batch,
                        "offer_n": offer_n,
                        "product_n": product_count,
                        "label_wc": 2,
                        "comment_wc": 35,
                    },
                },
                "ratingsite": {
                    "is_source": True,
                    "provenance": "http://www.{%ratingsite_id}.fr/",
                    "template": str(templates_dir / "bsbm-ratingsite.template"),
                    "export_output_dir": dataset_dir,
                    "export_dep_output_dir": str(Path(workdir) / "product"),
                    "scale_factor": source_scale_factor,
                    "params": {
                        "ratingsite_n": n_batch * members_per_batch,
                        "product_n": product_count,
                        "review_n": review_n,
                        "person_n": review_n // 20,
                        "person_name_wc": 3,
                        "label_wc": 2,
                        "text_wc": 125,
                        "title_wc": 9,
                        "rating1_p": 0.7,
                        "rating2_p": 0.7,
                        "rating3_p": 0.7,
                        "rating4_p": 0.7,
                    },
                },
            },
        },
        "evaluation": {
            "n_attempts": int(evaluation.get("attempts", evaluation.get("n_attempts", 1))),
            "timeout": int(evaluation.get("timeout", 120)),
            "proxy": {
                "compose_file": _project_path(project_root, "docker/proxy.yml"),
                "service_name": "fedshop-proxy",
                "host": proxy_host,
                "port": proxy_port,
                "endpoint": f"http://{proxy_host}:{proxy_port}/",
                "container_name": "docker-fedshop-proxy-1",
                "targets": [],
            },
            "engines": expanded_engines,
        },
    }


def load_config(path: str | Path) -> BenchmarkConfig:
    """Load config_small.yaml into typed dataclasses without OmegaConf."""
    config_path = Path(path)
    with open(config_path) as f:
        raw: dict = yaml.safe_load(f)

    raw = _expand_compact_config(raw, config_path)
    seed = {"config_dir": str(config_path.resolve().parent)}
    flat = _resolve_all(raw, seed)
    resolved = _rebuild(raw, flat)
    gen = resolved["generation"]
    evl = resolved["evaluation"]

    virt = gen["virtuoso"]
    virtuoso_cfg = VirtuosoConfig(
        compose_file=str(virt.get("compose_file", "")),
        service_name=str(virt.get("service_name", "bsbm-virtuoso")),
        isql=str(virt.get("isql", "/opt/virtuoso-opensource/bin/isql")),
        data_dir=str(virt.get("data_dir", "")),
        port=int(virt.get("port", 8890)),
        default_url=str(virt.get("default_url", f"http://localhost:{virt.get('port', 8890)}")),
        default_endpoint=str(virt.get("default_endpoint", "")),
        batch_members=list(virt.get("batch_members", [])),
        federation_members={
            k: dict(v) for k, v in virt.get("federation_members", {}).items()
        },
    )

    schema: dict[str, SchemaEntry] = {}
    for section, sdata in gen.get("schema", {}).items():
        schema[section] = SchemaEntry(
            is_source=bool(sdata.get("is_source", False)),
            provenance=str(sdata.get("provenance", "")),
            template=str(sdata.get("template", "")),
            scale_factor=int(sdata.get("scale_factor", 1)),
            export_output_dir=str(sdata.get("export_output_dir", "")),
            export_dep_output_dir=(
                str(sdata["export_dep_output_dir"])
                if sdata.get("export_dep_output_dir")
                else None
            ),
            params=dict(sdata.get("params", {})),
        )

    _workdir_default = str(gen.get("workdir", "experiments/bsbm"))
    gen_cfg = GenerationConfig(
        workdir=_workdir_default,
        queries_dir=str(gen.get("queries_dir", _workdir_default + "/queries")),
        n_batch=int(gen.get("n_batch", 2)),
        n_query_instances=int(gen.get("n_query_instances", 2)),
        verbose=bool(gen.get("verbose", False)),
        generator=GeneratorConfig(
            dir=str(gen["generator"].get("dir", "generators/watdiv")),
            exec=str(gen["generator"].get("exec", "")),
        ),
        virtuoso=virtuoso_cfg,
        schema=schema,
    )

    proxy = evl["proxy"]
    proxy_host = str(proxy.get("host", "localhost"))
    proxy_port = int(proxy.get("port", 5555))
    proxy_cfg = ProxyConfig(
        compose_file=str(proxy.get("compose_file", "")),
        service_name=str(proxy.get("service_name", "fedshop-proxy")),
        host=proxy_host,
        port=proxy_port,
        endpoint=str(proxy.get("endpoint", f"http://{proxy_host}:{proxy_port}/")),
        container_name=str(proxy.get("container_name", "docker-fedshop-proxy-1")),
    )

    engines: dict[str, EngineEntry] = {}
    for name, edata in evl.get("engines", {}).items():
        if isinstance(edata, dict):
            main = {"dir": str(edata.get("dir", ""))}
            extra = {k: str(v) for k, v in edata.items() if k != "dir"}
            engines[name] = EngineEntry(dir=main["dir"], extra=extra)

    eval_cfg = EvaluationConfig(
        n_attempts=int(evl.get("n_attempts", 1)),
        timeout=int(evl.get("timeout", 120)),
        proxy=proxy_cfg,
        engines=engines,
    )

    return BenchmarkConfig(
        use_docker=bool(resolved.get("use_docker", True)),
        generation=gen_cfg,
        evaluation=eval_cfg,
    )
