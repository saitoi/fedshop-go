"""Distributed-topology benchmark support (T1/T2/T3).

T1: engine/client + endpoints on one machine.
T2: all Virtuoso endpoints on one remote machine, engine/client on another.
T3: vendor endpoints on machine B, ratingsite endpoints on machine C,
    engine/client on machine A.

Everything here operates on per-topology bench dirs (e.g. benchmark-dist/topo1)
and never touches the legacy benchmark/ outputs.
"""

from __future__ import annotations

import json
import platform
import re
import socket
import subprocess
import time
from pathlib import Path

import numpy as np
import pandas as pd

TOPOLOGIES = ("topo1", "topo2", "topo3")

_MAPPING_GLOB = "virtuoso-proxy-mapping-batch*.json"

_PING_RE = re.compile(r"=\s*([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)\s*ms")


# ─── Endpoint mapping rewrite ────────────────────────────────────────────────

def _replace_host(endpoint_url: str, new_host: str, port: int) -> str:
    """Swap scheme://host[:port] of a Virtuoso endpoint URL, keeping path+query."""
    m = re.match(r"^(https?)://([^/]+)(/.*)?$", endpoint_url)
    if not m:
        return endpoint_url
    scheme, rest = m.group(1), m.group(3) or ""
    return f"{scheme}://{new_host}:{port}{rest}"


def rewrite_mapping(
    workdir: Path,
    vendor_host: str,
    ratingsite_host: str,
    port: int = 8890,
) -> list[Path]:
    """Point vendor*/ratingsite* graphs in the proxy-mapping JSONs at remote hosts.

    Rewrites the files in place (they live in the dist workdir, e.g. data-dist/,
    so the legacy data/ mappings are untouched). Pass the same host twice for T2.
    """
    workdir = Path(workdir)
    mapping_files = sorted(workdir.glob(_MAPPING_GLOB))
    if not mapping_files:
        raise FileNotFoundError(f"No {_MAPPING_GLOB} found in {workdir}")
    for mapping_file in mapping_files:
        mapping: dict[str, str] = json.loads(mapping_file.read_text())
        rewritten: dict[str, str] = {}
        for graph_iri, endpoint_url in mapping.items():
            if "ratingsite" in graph_iri:
                rewritten[graph_iri] = _replace_host(endpoint_url, ratingsite_host, port)
            elif "vendor" in graph_iri:
                rewritten[graph_iri] = _replace_host(endpoint_url, vendor_host, port)
            else:
                rewritten[graph_iri] = endpoint_url
        mapping_file.write_text(json.dumps(rewritten, indent=2) + "\n")
    return mapping_files


# ─── Run manifest (network covariates) ───────────────────────────────────────

def _ping_stats(host: str, count: int = 20) -> dict | None:
    """RTT min/avg/max/stddev in ms from `ping`, or None when unreachable."""
    try:
        proc = subprocess.run(
            ["ping", "-c", str(count), "-q", host],
            capture_output=True, text=True, timeout=count * 2 + 10,
        )
    except Exception:
        return None
    m = _PING_RE.search(proc.stdout)
    if not m:
        return None
    return {
        "min_ms": float(m.group(1)),
        "avg_ms": float(m.group(2)),
        "max_ms": float(m.group(3)),
        "stddev_ms": float(m.group(4)),
    }


def _iperf_mbps(host: str, seconds: int = 3) -> float | None:
    """Measured bandwidth in Mbit/s via iperf3 (requires iperf3 -s on the host)."""
    try:
        proc = subprocess.run(
            ["iperf3", "-c", host, "-J", "-t", str(seconds)],
            capture_output=True, text=True, timeout=seconds * 4 + 20,
        )
        payload = json.loads(proc.stdout)
        return payload["end"]["sum_received"]["bits_per_second"] / 1e6
    except Exception:
        return None


def _local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "unknown"


def collect_manifest(
    bench_dir: Path,
    topology: str,
    vendor_host: str,
    ratingsite_host: str,
    *,
    run_iperf: bool = False,
    ping_count: int = 20,
) -> dict:
    """Record topology, machine identity, and RTT/bandwidth covariates.

    Written to bench_dir/run_manifest.json; the merge step joins these values
    onto every metrics row of that topology.
    """
    bench_dir = Path(bench_dir)
    hosts = {"vendor": vendor_host, "ratingsite": ratingsite_host}
    manifest: dict = {
        "topology": topology,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "machine": {
            "hostname": platform.node(),
            "local_ip": _local_ip(),
            "platform": platform.platform(),
        },
        "hosts": {},
    }
    measured: dict[str, dict] = {}
    for role, host in hosts.items():
        if host not in measured:
            entry: dict = {"host": host}
            entry["rtt"] = _ping_stats(host, ping_count)
            entry["bandwidth_mbps"] = _iperf_mbps(host) if run_iperf else None
            measured[host] = entry
        manifest["hosts"][role] = measured[host]
    bench_dir.mkdir(parents=True, exist_ok=True)
    out = bench_dir / "run_manifest.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def _load_manifest(topo_dir: Path) -> dict:
    manifest_file = Path(topo_dir) / "run_manifest.json"
    if manifest_file.exists():
        try:
            return json.loads(manifest_file.read_text())
        except Exception:
            pass
    return {}


# ─── Merge per-topology metrics + derived distributed metrics ────────────────

_BLOCK_KEYS = ["engine", "query", "instance", "batch"]


def merge_topologies(
    topo_dirs: dict[str, Path],
    output_path: Path | str,
    *,
    baseline: str = "topo1",
) -> pd.DataFrame:
    """Concatenate per-topology metrics.csv files with a topology column.

    Adds manifest covariates (RTT/bandwidth) and derived distributed-systems
    metrics: slowdown vs the baseline topology, network-time ratio, throughput,
    bytes per result, predicted communication time, and exec-time jitter (CV
    across attempts).
    """
    frames: list[pd.DataFrame] = []
    for topology, topo_dir in topo_dirs.items():
        topo_dir = Path(topo_dir)
        metrics_csv = topo_dir / "metrics.csv"
        if not metrics_csv.exists():
            raise FileNotFoundError(
                f"{metrics_csv} not found — run `fedshop metrics compute "
                f"{metrics_csv} --bench-dir {topo_dir}` first"
            )
        df = pd.read_csv(metrics_csv)
        df["topology"] = topology
        manifest = _load_manifest(topo_dir)
        hosts = manifest.get("hosts", {})
        vendor_rtt = (hosts.get("vendor") or {}).get("rtt") or {}
        ratingsite_rtt = (hosts.get("ratingsite") or {}).get("rtt") or {}
        df["rtt_vendor_ms"] = vendor_rtt.get("avg_ms", np.nan)
        df["rtt_ratingsite_ms"] = ratingsite_rtt.get("avg_ms", np.nan)
        bandwidths = [
            (hosts.get(role) or {}).get("bandwidth_mbps")
            for role in ("vendor", "ratingsite")
        ]
        bandwidths = [b for b in bandwidths if b]
        df["bandwidth_mbps"] = min(bandwidths) if bandwidths else np.nan
        frames.append(df)

    merged = pd.concat(frames, ignore_index=True)
    ok = merged["status"] == "ok"

    # Slowdown vs baseline topology: per-block median exec_time at the baseline.
    base_median = (
        merged[ok & (merged["topology"] == baseline)]
        .groupby(_BLOCK_KEYS)["exec_time"]
        .median()
        .rename("_baseline_exec")
    )
    merged = merged.merge(base_median, on=_BLOCK_KEYS, how="left")
    merged["slowdown_vs_t1"] = np.where(
        ok & (merged["_baseline_exec"] > 0),
        merged["exec_time"] / merged["_baseline_exec"],
        np.nan,
    )
    merged.drop(columns=["_baseline_exec"], inplace=True)

    # Network-time ratio: <1 → fraction of run waiting on the network,
    # >1 → requests overlap in time (the engine hides latency via concurrency).
    if "net_total_time" in merged.columns:
        merged["network_time_ratio"] = np.where(
            ok & (merged["exec_time"] > 0),
            merged["net_total_time"] / merged["exec_time"],
            np.nan,
        )
        # Predicted pure-latency cost: requests × RTT (mean of the two hosts).
        mean_rtt_s = merged[["rtt_vendor_ms", "rtt_ratingsite_ms"]].mean(axis=1) / 1000.0
        merged["predicted_net_time"] = np.where(
            ok, merged["http_req"] * mean_rtt_s, np.nan
        )

    merged["throughput_rows_s"] = np.where(
        ok & (merged["exec_time"] > 0),
        merged["nb_results"] / merged["exec_time"],
        np.nan,
    )
    merged["bytes_per_result"] = np.where(
        ok & (merged["nb_results"] > 0),
        merged["data_transfer"] / merged["nb_results"],
        np.nan,
    )

    # Jitter: coefficient of variation of exec_time across attempts per block.
    cv = (
        merged[ok]
        .groupby(_BLOCK_KEYS + ["topology"])["exec_time"]
        .agg(lambda values: values.std(ddof=0) / values.mean() if values.mean() > 0 else np.nan)
        .rename("exec_time_cv")
    )
    merged = merged.merge(cv, on=_BLOCK_KEYS + ["topology"], how="left")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(output_path, index=False)
    return merged


# ─── Bench-dir bootstrap ─────────────────────────────────────────────────────

def bootstrap_bench_dir(topo_dir: Path, generation_dir: Path) -> Path:
    """Create benchmark-dist/topoN with a symlinked shared generation/."""
    topo_dir = Path(topo_dir)
    topo_dir.mkdir(parents=True, exist_ok=True)
    link = topo_dir / "generation"
    generation_dir = Path(generation_dir).resolve()
    if not generation_dir.exists():
        raise FileNotFoundError(f"Generation dir not found: {generation_dir}")
    if link.is_symlink() or link.exists():
        return topo_dir
    link.symlink_to(generation_dir, target_is_directory=True)
    return topo_dir
