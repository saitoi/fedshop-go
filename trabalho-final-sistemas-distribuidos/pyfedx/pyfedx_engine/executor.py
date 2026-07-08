"""Federated query execution."""

from __future__ import annotations

import re
import time
from typing import Dict, List, Optional, Sequence, Tuple

from .client import HttpSparqlClient
from .filtering import _get_str, eval_filter
from .federation import _collect_all_triples, select_group_query, select_query
from .model import Endpoint, GroupPattern, Query, SparqlError, Triple
from .parser import VAR_RE, unique
from .planner import order_triples

# ---------------------------------------------------------------------------
# Join helpers
# ---------------------------------------------------------------------------


def compatible(left: Dict[str, str], right: Dict[str, str]) -> bool:
    return all(_get_str(left[k]) == _get_str(right[k]) for k in left.keys() & right.keys())


def join_bindings(
    left: List[Dict[str, str]], right: List[Dict[str, str]]
) -> List[Dict[str, str]]:
    if not left:
        return [dict(row) for row in right]
    if not right:
        return []
    out: List[Dict[str, str]] = []
    for lrow in left:
        for rrow in right:
            if compatible(lrow, rrow):
                merged = dict(lrow)
                merged.update(rrow)
                out.append(merged)
    return out


def _bound_vars(rows: List[Dict[str, str]]) -> set:
    out: set = set()
    for row in rows:
        out.update(row)
    return out


def hash_join_bindings(
    left: List[Dict[str, str]], right: List[Dict[str, str]]
) -> List[Dict[str, str]]:
    """Join bindings with a hash table on shared variables.

    Falls back to the original nested-loop path for Cartesian joins or rows that
    do not bind all shared variables, preserving OPTIONAL-compatible semantics.
    """
    if not left:
        return [dict(row) for row in right]
    if not right:
        return []
    shared = sorted(_bound_vars(left) & _bound_vars(right))
    if not shared:
        return join_bindings(left, right)

    def key(row: Dict[str, str]) -> Tuple[str, ...]:
        return tuple(_get_str(row[var]) for var in shared)

    indexed_right: Dict[Tuple[str, ...], List[Dict[str, str]]] = {}
    slow_right: List[Dict[str, str]] = []
    for rrow in right:
        if all(var in rrow for var in shared):
            indexed_right.setdefault(key(rrow), []).append(rrow)
        else:
            slow_right.append(rrow)

    out: List[Dict[str, str]] = []
    for lrow in left:
        candidates: List[Dict[str, str]] = []
        if all(var in lrow for var in shared):
            candidates.extend(indexed_right.get(key(lrow), []))
        else:
            for rows in indexed_right.values():
                candidates.extend(rows)
        candidates.extend(slow_right)
        for rrow in candidates:
            if compatible(lrow, rrow):
                merged = dict(lrow)
                merged.update(rrow)
                out.append(merged)
    return out


def _join(
    left: List[Dict[str, str]],
    right: List[Dict[str, str]],
    method: str,
) -> List[Dict[str, str]]:
    if method == "hash":
        return hash_join_bindings(left, right)
    return join_bindings(left, right)


def left_outer_join(
    left: List[Dict[str, str]], right: List[Dict[str, str]]
) -> List[Dict[str, str]]:
    """SPARQL OPTIONAL semantics: keep all left rows; extend with right where compatible."""
    if not left:
        return []
    if not right:
        return [dict(row) for row in left]
    out: List[Dict[str, str]] = []
    for lrow in left:
        matches = [rrow for rrow in right if compatible(lrow, rrow)]
        if matches:
            for rrow in matches:
                merged = dict(lrow)
                merged.update(rrow)
                out.append(merged)
        else:
            out.append(dict(lrow))
    return out


def anti_join(
    left: List[Dict[str, str]], right: List[Dict[str, str]]
) -> List[Dict[str, str]]:
    """Keep left rows that have no compatible right row."""
    if not left or not right:
        return [dict(row) for row in left]
    shared = sorted(_bound_vars(left) & _bound_vars(right))
    if not shared:
        return []

    def key(row: Dict[str, str]) -> Tuple[str, ...]:
        return tuple(_get_str(row[var]) for var in shared)

    index: Dict[Tuple[str, ...], List[Dict[str, str]]] = {}
    slow_right: List[Dict[str, str]] = []
    for rrow in right:
        if all(var in rrow for var in shared):
            index.setdefault(key(rrow), []).append(rrow)
        else:
            slow_right.append(rrow)

    out: List[Dict[str, str]] = []
    for lrow in left:
        candidates: List[Dict[str, str]] = []
        if all(var in lrow for var in shared):
            candidates.extend(index.get(key(lrow), []))
        else:
            for rows in index.values():
                candidates.extend(rows)
        candidates.extend(slow_right)
        if not any(compatible(lrow, rrow) for rrow in candidates):
            out.append(dict(lrow))
    return out


def distinct_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen: set = set()
    out: List[Dict[str, str]] = []
    for row in rows:
        key = tuple(sorted((_get_str(k), _get_str(v)) for k, v in row.items()))
        if key not in seen:
            out.append(row)
            seen.add(key)
    return out


def _sort_key(val: str):
    v = _get_str(val)
    try:
        return (0, float(v), "")
    except (ValueError, TypeError):
        return (1, 0.0, v)


def apply_order_by(
    rows: List[Dict[str, str]], order_by: Tuple[Tuple[str, bool], ...]
) -> List[Dict[str, str]]:
    if not order_by:
        return rows
    for var, ascending in reversed(order_by):
        rows = sorted(rows, key=lambda row, v=var: _sort_key(row.get(v, "")), reverse=not ascending)
    return rows



def _check_intermediate_size(
    rows: List[Dict[str, str]],
    max_intermediate: int,
    context: str,
) -> None:
    if max_intermediate > 0 and len(rows) > max_intermediate:
        raise SparqlError(
            f"intermediate result exceeded {max_intermediate} rows after {context}: {len(rows)}"
        )


def _filter_variables(expr: str) -> set:
    return set(VAR_RE.findall(expr))


def _not_bound_variables(expr: str) -> set:
    return set(re.findall(r"!\s*BOUND\s*\(\s*\?([A-Za-z_][\w-]*)\s*\)", expr, re.I))


def _apply_ready_filters(
    rows: List[Dict[str, str]],
    filters: Sequence[str],
) -> List[Dict[str, str]]:
    if not rows or not filters:
        return rows
    bound = _bound_vars(rows)
    for expr in filters:
        if _filter_variables(expr).issubset(bound):
            rows = [row for row in rows if eval_filter(expr, row)]
            if not rows:
                return []
            bound = _bound_vars(rows)
    return rows


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _execute_bgp(
    triples: List[Triple],
    source_map: Dict[Triple, List[Endpoint]],
    client: HttpSparqlClient,
    prefixes: Dict[str, str],
    *,
    planner: str = "connected-source-count",
    join_method: str = "hash",
    max_intermediate: int = 500_000,
    filters: Sequence[str] = (),
) -> List[Dict[str, str]]:
    """Execute a flat list of triple patterns with source-based join."""
    result: List[Dict[str, str]] = []
    plan_started = time.monotonic()
    ordered = order_triples(triples, source_map, planner)
    client.planning_seconds += time.monotonic() - plan_started
    for triple in ordered:
        sources = source_map.get(triple, [])
        if not sources:
            return []
        vars_ = triple.variables()
        union_rows: List[Dict[str, str]] = []
        for endpoint in sources:
            union_rows.extend(client.select(endpoint, select_query(prefixes, [triple], vars_)))
        result = _join(result, union_rows, join_method)
        result = _apply_ready_filters(result, filters)
        _check_intermediate_size(result, max_intermediate, triple.key())
        if not result:
            return []
    return result


def _execute_endpoint_bgp(
    triples: List[Triple],
    filters: Sequence[str],
    source_map: Dict[Triple, List[Endpoint]],
    client: HttpSparqlClient,
    prefixes: Dict[str, str],
) -> Optional[List[Dict[str, str]]]:
    """Execute a whole BGP at endpoints that can answer every triple.

    This pushes joins and filters to Virtuoso for source-local parts of a query,
    avoiding local materialization explosions like q05.  If no common endpoint
    exists, return None so the federated local join path can handle it.
    """
    if not triples:
        return []
    if any("owl#sameAs>" in triple.predicate for triple in triples):
        return None
    common: Optional[set] = None
    by_eid: Dict[str, Endpoint] = {}
    for triple in triples:
        sources = source_map.get(triple, [])
        if not sources:
            return []
        eids = {endpoint.eid for endpoint in sources}
        by_eid.update({endpoint.eid: endpoint for endpoint in sources})
        common = eids if common is None else common & eids
        if not common:
            return None
    variables = unique(var for triple in triples for var in triple.variables())
    sparql = select_group_query(prefixes, triples, filters, variables)
    rows: List[Dict[str, str]] = []
    for eid in sorted(common or []):
        rows.extend(client.select(by_eid[eid], sparql))
    return distinct_rows(rows)


def execute_group(
    group: GroupPattern,
    source_map: Dict[Triple, List[Endpoint]],
    client: HttpSparqlClient,
    prefixes: Dict[str, str],
    *,
    planner: str = "connected-source-count",
    join_method: str = "hash",
    max_intermediate: int = 500_000,
) -> List[Dict[str, str]]:
    """Recursively execute a GroupPattern and return binding rows."""
    # 1. Execute mandatory BGP triples
    endpoint_result: Optional[List[Dict[str, str]]] = None
    if group.triples and group.filters and not group.optionals and not group.unions:
        endpoint_result = _execute_endpoint_bgp(
            group.triples,
            group.filters,
            source_map,
            client,
            prefixes,
        )
    if endpoint_result is not None:
        result = endpoint_result
    else:
        result = _execute_bgp(
            group.triples,
            source_map,
            client,
            prefixes,
            planner=planner,
            join_method=join_method,
            max_intermediate=max_intermediate,
            filters=group.filters,
        )

    # 2. Execute UNION arms (dedup, then join with current result)
    for arm1, arm2 in group.unions:
        rows1 = execute_group(
            arm1,
            source_map,
            client,
            prefixes,
            planner=planner,
            join_method=join_method,
            max_intermediate=max_intermediate,
        )
        rows2 = execute_group(
            arm2,
            source_map,
            client,
            prefixes,
            planner=planner,
            join_method=join_method,
            max_intermediate=max_intermediate,
        )
        union_rows = distinct_rows(rows1 + rows2)
        result = _join(result, union_rows, join_method) if result else union_rows
        _check_intermediate_size(result, max_intermediate, "UNION")

    # 3. Left-outer-join OPTIONAL patterns
    for opt in group.optionals:
        opt_result = execute_group(
            opt,
            source_map,
            client,
            prefixes,
            planner=planner,
            join_method=join_method,
            max_intermediate=max_intermediate,
        )
        anti_vars = set().union(*(_not_bound_variables(expr) for expr in group.filters))
        opt_vars = set().union(*(set(triple.variables()) for triple in _collect_all_triples(opt)))
        if anti_vars & opt_vars:
            result = anti_join(result, opt_result)
        else:
            result = left_outer_join(result, opt_result)
            _check_intermediate_size(result, max_intermediate, "OPTIONAL")

    # 4. Apply FILTER predicates
    for f in group.filters:
        result = [row for row in result if eval_filter(f, row)]

    return result


def execute(
    query: Query,
    source_map: Dict[Triple, List[Endpoint]],
    client: HttpSparqlClient,
    *,
    planner: str = "connected-source-count",
    join_method: str = "hash",
    max_intermediate: int = 500_000,
) -> List[Dict[str, str]]:
    rows = execute_group(
        query.group,
        source_map,
        client,
        query.prefixes,
        planner=planner,
        join_method=join_method,
        max_intermediate=max_intermediate,
    )

    # Project to SELECT variables; omit unbound optional variables (absent from row)
    if query.select:
        rows = [
            {var: _get_str(row[var]) for var in query.select if var in row}
            for row in rows
        ]
    else:
        rows = [{k: _get_str(v) for k, v in row.items()} for row in rows]

    if query.distinct:
        rows = distinct_rows(rows)

    rows = apply_order_by(rows, query.order_by)

    if query.limit is not None:
        rows = rows[: query.limit]

    return rows



__all__ = ["anti_join", "apply_order_by", "compatible", "distinct_rows", "execute", "execute_group", "hash_join_bindings", "join_bindings", "left_outer_join", "_bound_vars", "_not_bound_variables"]
