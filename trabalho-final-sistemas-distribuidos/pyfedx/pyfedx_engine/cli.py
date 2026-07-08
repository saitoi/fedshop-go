"""Command-line entry point."""

from __future__ import annotations

import argparse
import math
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .artifacts import write_csv, write_plan, write_source_selection, write_stats
from .client import HttpSparqlClient
from .executor import execute
from .federation import _collect_all_triples, select_sources
from .parser import parse_endpoints, parse_query

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def _latency_summary(latencies: List[float]) -> Dict[str, float]:
    """Summarize per-request network latencies into count/total/mean/p50/p95."""
    if not latencies:
        return {
            "net_req_count": 0,
            "net_total_seconds": 0.0,
            "net_mean_seconds": 0.0,
            "net_p50_seconds": 0.0,
            "net_p95_seconds": 0.0,
        }
    ordered = sorted(latencies)

    def pct(p: float) -> float:
        idx = min(len(ordered) - 1, max(0, math.ceil(p * len(ordered)) - 1))
        return ordered[idx]

    total = sum(ordered)
    return {
        "net_req_count": len(ordered),
        "net_total_seconds": total,
        "net_mean_seconds": total / len(ordered),
        "net_p50_seconds": pct(0.5),
        "net_p95_seconds": pct(0.95),
    }


def _load_imbalance(requests_by_host: Dict[str, int]) -> float:
    """Ratio max/mean of requests per endpoint host (1.0 = perfectly balanced)."""
    if not requests_by_host:
        return 0.0
    counts = list(requests_by_host.values())
    mean = sum(counts) / len(counts)
    return max(counts) / mean if mean > 0 else 0.0


def run_app(args: argparse.Namespace, client: Optional[HttpSparqlClient] = None) -> int:
    started = time.monotonic()
    client = client or HttpSparqlClient(timeout=args.timeout)

    query = parse_query(Path(args.query).read_text(encoding="utf-8"))
    endpoints = parse_endpoints(Path(args.config).read_text(encoding="utf-8"))
    all_triples = _collect_all_triples(query.group)

    print(f"[pyfedx] query: {args.query}", flush=True)
    print(f"[pyfedx] endpoints: {len(endpoints)}  triples: {len(all_triples)}", flush=True)

    ss_started = time.monotonic()
    source_map, ask_count = select_sources(query, endpoints, client)
    ss_seconds = time.monotonic() - ss_started

    print(f"[pyfedx] source selection: {ask_count} ASK probes in {ss_seconds:.2f}s", flush=True)
    for triple in all_triples:
        srcs = source_map.get(triple, [])
        src_ids = [e.eid for e in srcs]
        print(f"[pyfedx]   {triple.key()} → {src_ids or '(none)'}", flush=True)

    rows: List[Dict[str, str]] = []
    exec_s = 0.0
    if not args.noexec:
        rows = execute(
            query,
            source_map,
            client,
            planner=args.planner,
            join_method=args.join,
            max_intermediate=args.max_intermediate,
        )
        exec_s = time.monotonic() - ss_started - ss_seconds
        print(f"[pyfedx] execution: {len(rows)} rows in {exec_s:.2f}s", flush=True)
    else:
        print("[pyfedx] noexec — skipping execution", flush=True)

    write_csv(args.out_result, rows, query.select)
    write_source_selection(args.out_source_selection, source_map, query.group)
    write_plan(args.query_plan, query, source_map, planner=args.planner)
    total_s = time.monotonic() - started
    print(f"[pyfedx] results  → {args.out_result}", flush=True)
    print(f"[pyfedx] sources  → {args.out_source_selection}", flush=True)
    print(f"[pyfedx] plan     → {args.query_plan}", flush=True)
    print(f"[pyfedx] stats    → {args.stats}", flush=True)
    print(f"[pyfedx] done in {total_s:.2f}s", flush=True)

    planning_s = client.planning_seconds
    write_stats(
        args.stats,
        {
            "engine": "pyfedx",
            "ask": ask_count,
            "http_requests": client.http_requests,
            "source_selection_seconds": ss_seconds,
            "planning_seconds": planning_s,
            "execution_seconds": max(0.0, exec_s - planning_s),
            "data_transfer": client.bytes_received,
            "request_bytes": client.bytes_sent,
            "endpoints_contacted": len(client.requests_by_host),
            "endpoint_load_imbalance": _load_imbalance(client.requests_by_host),
            "planner": args.planner,
            "join": args.join,
            "max_intermediate": args.max_intermediate,
            "total_seconds": total_s,
            "rows": len(rows),
            "noexec": args.noexec,
            **_latency_summary(client.request_latencies),
        },
    )
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="FedX-style SPARQL federation runner"
    )
    parser.add_argument("--config", help="Turtle config with sd:endpoint entries")
    parser.add_argument("--query", help="SPARQL SELECT query file")
    parser.add_argument("--out-result", default="/dev/null")
    parser.add_argument("--out-source-selection", default="/dev/null")
    parser.add_argument("--query-plan", default="/dev/null")
    parser.add_argument("--stats", default="/dev/null")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--planner",
        choices=["connected-source-count", "source-count"],
        default="connected-source-count",
        help="BGP ordering strategy",
    )
    parser.add_argument(
        "--join",
        choices=["hash", "nested-loop"],
        default="hash",
        help="Join algorithm for compatible bindings",
    )
    parser.add_argument(
        "--max-intermediate",
        type=int,
        default=500_000,
        help="Abort when an intermediate result exceeds this many rows; 0 disables",
    )
    parser.add_argument("--noexec", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.self_test:
        from .selftest import run_self_tests

        return run_self_tests()
    if not args.config or not args.query:
        parser.error("--config and --query are required unless --self-test is used")
    return run_app(args)


__all__ = ["build_arg_parser", "main", "run_app"]
