"""Output artifact writers."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, List, Sequence

from .federation import _collect_all_triples
from .model import Endpoint, GroupPattern, Query, Triple
from .parser import unique
from .planner import order_triples

# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------


def write_csv(path: str, rows: List[Dict[str, str]], variables: Sequence[str]) -> None:
    if path == "/dev/null":
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    headers = list(variables) if variables else unique(k for row in rows for k in row)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in headers})


def write_source_selection(
    path: str,
    source_map: Dict[Triple, List[Endpoint]],
    group: GroupPattern,
) -> None:
    """Write source_selection CSV.

    triple column: "s p o" (no trailing '.') — directly matches composition.json key format.
    source_selection column: JSON array of endpoint IDs.
    """
    if path == "/dev/null":
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    all_triples = _collect_all_triples(group)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["triple", "source_selection"])
        writer.writeheader()
        for triple in all_triples:
            endpoints = source_map.get(triple, [])
            writer.writerow(
                {
                    "triple": triple.key(),  # "s p o" without trailing "."
                    "source_selection": json.dumps([e.eid for e in endpoints]),
                }
            )


def write_plan(
    path: str,
    query: Query,
    source_map: Dict[Triple, List[Endpoint]],
    *,
    planner: str = "connected-source-count",
) -> None:
    if path == "/dev/null":
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    all_triples = _collect_all_triples(query.group)
    ordered_bgp = order_triples(query.group.triples, source_map, planner)
    lines = [
        "PyFedX plan",
        f"distinct={query.distinct}",
        f"limit={query.limit}",
        f"planner={planner}",
        "bgp_order=" + " -> ".join(t.key() for t in ordered_bgp),
        "",
    ]
    for idx, triple in enumerate(all_triples, 1):
        sources = source_map.get(triple, [])
        node = (
            "EmptyStatementPattern"
            if not sources
            else "ExclusiveStatement"
            if len(sources) == 1
            else "StatementSourcePattern"
        )
        lines.append(f"tp{idx}: {node}: {triple.sparql()}")
        lines.append(f"  sources: {', '.join(e.eid for e in sources) or '-'}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_stats(path: str, stats: Dict[str, object]) -> None:
    if path == "/dev/null":
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")



__all__ = ["write_csv", "write_plan", "write_source_selection", "write_stats"]
