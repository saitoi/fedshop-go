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


def load_config(path: str | Path) -> BenchmarkConfig:
    """Load config_small.yaml into typed dataclasses without OmegaConf."""
    with open(path) as f:
        raw: dict = yaml.safe_load(f)

    seed = {"config_dir": str(Path(path).resolve().parent)}
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
