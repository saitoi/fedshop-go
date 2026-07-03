"""Executa uma consulta federada com o pyfedx instrumentado e grava um trace completo.

O trace é uma lista ordenada de eventos com timestamps reais (segundos relativos ao
início da execução) e payloads integrais — incluindo o texto SPARQL de cada ASK/SELECT.
O frontend reproduz esse trace como uma animação com relógio virtual.

A orquestração (seleção de fontes + execução) é reimplementada aqui chamando as
primitivas do pyfedx (join_bindings, left_outer_join, eval_filter, ...), porque as
funções originais não têm hooks para eventos de join/filtro.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Localiza scripts/pyfedx.py — configurável via PYFEDX_PATH
_DEFAULT_SCRIPTS = str(Path(__file__).parent.parent.parent / "scripts")
_SCRIPTS_DIR = os.environ.get("PYFEDX_PATH", _DEFAULT_SCRIPTS)
sys.path.insert(0, _SCRIPTS_DIR)

import pyfedx  # noqa: E402

SAMPLE_ROWS = 5
JOIN_SAMPLE_ROWS = 25  # amostras maiores para a aba de detalhe de joins


# ---------------------------------------------------------------------------
# Trace
# ---------------------------------------------------------------------------


class Trace:
    def __init__(self) -> None:
        self.events: List[dict] = []
        self._start = time.monotonic()

    def now(self) -> float:
        return round(time.monotonic() - self._start, 6)

    def emit(self, type_: str, t0: Optional[float] = None, **payload) -> dict:
        t1 = self.now()
        event = {"seq": len(self.events), "type": type_, "t0": t0 if t0 is not None else t1, "t1": t1}
        event.update(payload)
        self.events.append(event)
        return event


def _clean_rows(rows: List[Dict[str, str]], limit: int = SAMPLE_ROWS) -> List[Dict[str, str]]:
    """Amostra de linhas com a codificação de language-tag removida."""
    return [
        {k: pyfedx._get_str(v) for k, v in row.items()}
        for row in rows[:limit]
    ]


# ---------------------------------------------------------------------------
# Endpoints (config JSON {graph_iri: url} do fedshop-py)
# ---------------------------------------------------------------------------


def parse_endpoints_json(config_text: str) -> List[pyfedx.Endpoint]:
    mapping: Dict[str, str] = json.loads(config_text)
    endpoints: List[pyfedx.Endpoint] = []
    for iri, url in mapping.items():
        # A webapp roda no host: host.docker.internal não resolve fora de containers.
        url = url.replace("host.docker.internal", "localhost")
        # "http://www.vendor0.fr/" → "vendor0"
        domain = iri.rstrip("/").split("/")[-1]
        parts = [p for p in domain.split(".") if p.lower() != "www"]
        eid = parts[0] if parts else f"ep{len(endpoints)}"
        eid = re.sub(r"[^A-Za-z0-9_-]+", "_", eid).strip("_") or f"ep{len(endpoints)}"
        endpoints.append(pyfedx.Endpoint(eid=eid, url=url))
    if not endpoints:
        raise pyfedx.SparqlError("config sem endpoints")
    return endpoints


# ---------------------------------------------------------------------------
# Cliente HTTP instrumentado
# ---------------------------------------------------------------------------


class BudgetExceeded(RuntimeError):
    pass


class TracedClient(pyfedx.HttpSparqlClient):
    def __init__(self, trace: Trace, timeout: float = 60.0, budget: float = 60.0) -> None:
        super().__init__(timeout)
        self.trace = trace
        self.budget = budget

    def _check_budget(self) -> None:
        if self.trace.now() > self.budget:
            raise BudgetExceeded(
                f"tempo máximo de execução excedido ({self.budget:.0f}s)"
            )

    def traced_ask(self, endpoint: pyfedx.Endpoint, query: str, tp_id: str) -> bool:
        self._check_budget()
        t0 = self.trace.now()
        result = super().ask(endpoint, query)
        self.trace.emit(
            "ask", t0=t0,
            tp_id=tp_id, endpoint_id=endpoint.eid, sparql=query, result=result,
        )
        return result

    def traced_select(
        self, endpoint: pyfedx.Endpoint, query: str, tp_id: str
    ) -> List[Dict[str, str]]:
        self._check_budget()
        t0 = self.trace.now()
        rows = super().select(endpoint, query)
        self.trace.emit(
            "select", t0=t0,
            tp_id=tp_id, endpoint_id=endpoint.eid, sparql=query,
            rows=len(rows), sample=_clean_rows(rows),
        )
        return rows


# ---------------------------------------------------------------------------
# Identificação dos padrões de tripla (tp1..tpN) e contexto no grupo
# ---------------------------------------------------------------------------


def assign_tp_ids(group: pyfedx.GroupPattern) -> Tuple[Dict[pyfedx.Triple, str], List[dict]]:
    """Atribui tp1..tpN na mesma ordem de _collect_all_triples; anota o contexto."""
    contexts: Dict[pyfedx.Triple, str] = {}

    def walk(g: pyfedx.GroupPattern, ctx: str) -> None:
        for t in g.triples:
            contexts.setdefault(t, ctx)
        for opt in g.optionals:
            walk(opt, "optional")
        for arm1, arm2 in g.unions:
            walk(arm1, "union")
            walk(arm2, "union")

    walk(group, "bgp")
    all_triples = pyfedx._collect_all_triples(group)
    tp_ids = {t: f"tp{i}" for i, t in enumerate(all_triples, 1)}
    info = [
        {
            "id": tp_ids[t],
            "sparql": t.key(),
            "vars": t.variables(),
            "context": contexts.get(t, "bgp"),
        }
        for t in all_triples
    ]
    return tp_ids, info


# ---------------------------------------------------------------------------
# Seleção de fontes (espelha pyfedx.select_sources, com eventos)
# ---------------------------------------------------------------------------


def traced_select_sources(
    query: pyfedx.Query,
    endpoints: List[pyfedx.Endpoint],
    client: TracedClient,
    tp_ids: Dict[pyfedx.Triple, str],
    trace: Trace,
) -> Tuple[Dict[pyfedx.Triple, List[pyfedx.Endpoint]], int]:
    all_triples = pyfedx._collect_all_triples(query.group)
    selected: Dict[pyfedx.Triple, List[pyfedx.Endpoint]] = {}
    ask_count = 0
    for triple in all_triples:
        sources: List[pyfedx.Endpoint] = []
        ask = pyfedx.ask_query(query.prefixes, triple)
        for endpoint in endpoints:
            if client.traced_ask(endpoint, ask, tp_ids[triple]):
                sources.append(endpoint)
            ask_count += 1
        selected[triple] = sources
    return selected, ask_count


# ---------------------------------------------------------------------------
# Execução (espelha pyfedx._execute_bgp / execute_group / execute, com eventos)
# ---------------------------------------------------------------------------

# Teto para resultados intermediários: acima disso a consulta é abortada em vez
# de travar o servidor (o pyfedx materializa a extensão completa de cada tripla).
MAX_INTERMEDIATE = 500_000


def hash_join(
    left: List[Dict[str, str]], right: List[Dict[str, str]]
) -> List[Dict[str, str]]:
    """Equivalente a pyfedx.join_bindings, mas com hash join nas variáveis
    compartilhadas em vez de nested-loop (mesma semântica, muito mais rápido)."""
    if not left:
        return [dict(row) for row in right]
    if not right:
        return []
    shared = sorted(_bound_vars(left) & _bound_vars(right))
    if not shared:
        return pyfedx.join_bindings(left, right)  # produto cartesiano (raro)

    def key(row: Dict[str, str]) -> tuple:
        # None para variável ausente na linha (compatível com qualquer valor)
        return tuple(pyfedx._get_str(row[v]) if v in row else None for v in shared)

    # Linhas com todas as shared vars presentes vão para o índice; as demais
    # (possível com OPTIONAL) caem no caminho lento nested-loop.
    index: Dict[tuple, List[Dict[str, str]]] = {}
    slow_right: List[Dict[str, str]] = []
    for rrow in right:
        if all(v in rrow for v in shared):
            index.setdefault(key(rrow), []).append(rrow)
        else:
            slow_right.append(rrow)

    out: List[Dict[str, str]] = []
    for lrow in left:
        if all(v in lrow for v in shared):
            for rrow in index.get(key(lrow), []):
                merged = dict(lrow)
                merged.update(rrow)
                out.append(merged)
        else:
            for rrow in index.values():
                for r in rrow:
                    if pyfedx.compatible(lrow, r):
                        merged = dict(lrow)
                        merged.update(r)
                        out.append(merged)
        for rrow in slow_right:
            if pyfedx.compatible(lrow, rrow):
                merged = dict(lrow)
                merged.update(rrow)
                out.append(merged)
    return out


class IntermediateTooLarge(RuntimeError):
    pass


def _check_size(rows: List[Dict[str, str]], where: str) -> None:
    if len(rows) > MAX_INTERMEDIATE:
        raise IntermediateTooLarge(
            f"resultado intermediário com {len(rows)} linhas em {where} "
            f"(limite {MAX_INTERMEDIATE}) — consulta inviável para o pyfedx"
        )


def _bound_vars(rows: List[Dict[str, str]]) -> set:
    out: set = set()
    for row in rows:
        out.update(row.keys())
    return out


def traced_execute_bgp(
    triples: List[pyfedx.Triple],
    source_map: Dict[pyfedx.Triple, List[pyfedx.Endpoint]],
    client: TracedClient,
    prefixes: Dict[str, str],
    tp_ids: Dict[pyfedx.Triple, str],
    trace: Trace,
) -> List[Dict[str, str]]:
    result: List[Dict[str, str]] = []
    # Ordenação por conectividade: começa pelo padrão com menos fontes e sempre
    # escolhe em seguida um padrão que compartilha variável com as já ligadas
    # (evita produto cartesiano; desempate por menos fontes). O pyfedx original
    # ordena só por nº de fontes, o que explode em consultas como a q05.
    remaining = sorted(triples, key=lambda t: len(source_map.get(t, [])))
    ordered: List[pyfedx.Triple] = []
    bound: set = set()
    while remaining:
        connected = [t for t in remaining if bound & set(t.variables())]
        pick = connected[0] if connected else remaining[0]
        remaining.remove(pick)
        ordered.append(pick)
        bound.update(pick.variables())
    for order, triple in enumerate(ordered, 1):
        sources = source_map.get(triple, [])
        tp_id = tp_ids[triple]
        trace.emit(
            "tp_exec", tp_id=tp_id, order=order,
            sources=[e.eid for e in sources],
        )
        if not sources:
            trace.emit(
                "join", tp_id=tp_id, left=len(result), right=0, out=0, shared_vars=[],
                left_sample=_clean_rows(result, JOIN_SAMPLE_ROWS), right_sample=[], sample=[],
                left_vars=sorted(_bound_vars(result)), right_vars=triple.variables(), out_vars=[],
            )
            return []
        vars_ = triple.variables()
        union_rows: List[Dict[str, str]] = []
        for endpoint in sources:
            sub = pyfedx.select_query(prefixes, [triple], vars_)
            union_rows.extend(client.traced_select(endpoint, sub, tp_id))
        _check_size(union_rows, f"SELECTs de {tp_id}")
        shared = sorted(_bound_vars(result) & set(vars_)) if result else []
        left_size = len(result)
        left_sample = _clean_rows(result, JOIN_SAMPLE_ROWS)
        left_vars = sorted(_bound_vars(result))
        result = hash_join(result, union_rows)
        _check_size(result, f"join de {tp_id}")
        trace.emit(
            "join", tp_id=tp_id,
            left=left_size, right=len(union_rows), out=len(result),
            shared_vars=shared,
            left_sample=left_sample, right_sample=_clean_rows(union_rows, JOIN_SAMPLE_ROWS),
            sample=_clean_rows(result, JOIN_SAMPLE_ROWS),
            left_vars=left_vars, right_vars=vars_, out_vars=sorted(_bound_vars(result)),
        )
        if not result:
            return []
    return result


def traced_execute_group(
    group: pyfedx.GroupPattern,
    source_map: Dict[pyfedx.Triple, List[pyfedx.Endpoint]],
    client: TracedClient,
    prefixes: Dict[str, str],
    tp_ids: Dict[pyfedx.Triple, str],
    trace: Trace,
) -> List[Dict[str, str]]:
    result = traced_execute_bgp(group.triples, source_map, client, prefixes, tp_ids, trace)

    for arm1, arm2 in group.unions:
        rows1 = traced_execute_group(arm1, source_map, client, prefixes, tp_ids, trace)
        rows2 = traced_execute_group(arm2, source_map, client, prefixes, tp_ids, trace)
        union_rows = pyfedx.distinct_rows(rows1 + rows2)
        before = len(result)
        result = hash_join(result, union_rows) if result else union_rows
        _check_size(result, "union")
        trace.emit(
            "union_merge",
            arm1=len(rows1), arm2=len(rows2), merged=len(union_rows),
            left=before, out=len(result),
            sample=_clean_rows(result, JOIN_SAMPLE_ROWS),
            out_vars=sorted(_bound_vars(result)),
        )

    for opt in group.optionals:
        opt_result = traced_execute_group(opt, source_map, client, prefixes, tp_ids, trace)
        before = len(result)
        result = pyfedx.left_outer_join(result, opt_result)
        trace.emit(
            "optional_join", left=before, right=len(opt_result), out=len(result),
            sample=_clean_rows(result, JOIN_SAMPLE_ROWS),
            out_vars=sorted(_bound_vars(result)),
        )

    for f in group.filters:
        before = len(result)
        result = [row for row in result if pyfedx.eval_filter(f, row)]
        trace.emit(
            "filter", expr=f, before=before, after=len(result),
            sample=_clean_rows(result, JOIN_SAMPLE_ROWS),
            out_vars=sorted(_bound_vars(result)),
        )

    return result


def traced_execute(
    query: pyfedx.Query,
    source_map: Dict[pyfedx.Triple, List[pyfedx.Endpoint]],
    client: TracedClient,
    tp_ids: Dict[pyfedx.Triple, str],
    trace: Trace,
) -> List[Dict[str, str]]:
    rows = traced_execute_group(query.group, source_map, client, query.prefixes, tp_ids, trace)

    if query.select:
        rows = [
            {var: pyfedx._get_str(row[var]) for var in query.select if var in row}
            for row in rows
        ]
    else:
        rows = [{k: pyfedx._get_str(v) for k, v in row.items()} for row in rows]

    before_distinct = len(rows)
    if query.distinct:
        rows = pyfedx.distinct_rows(rows)
    rows = pyfedx.apply_order_by(rows, query.order_by)
    before_limit = len(rows)
    if query.limit is not None:
        rows = rows[: query.limit]
    trace.emit(
        "postprocess",
        distinct=query.distinct, before_distinct=before_distinct,
        order_by=[[v, asc] for v, asc in query.order_by],
        limit=query.limit, before_limit=before_limit, final=len(rows),
    )
    return rows


# ---------------------------------------------------------------------------
# Entrada pública
# ---------------------------------------------------------------------------


def run_traced(query_str: str, config_text: str, timeout: float = 60.0) -> dict:
    """Executa a consulta de verdade e devolve {"events": [...], "error": str|None}."""
    trace = Trace()
    error: Optional[str] = None
    try:
        query = pyfedx.parse_query(query_str)
        endpoints = parse_endpoints_json(config_text)
        tp_ids, tp_info = assign_tp_ids(query.group)
        client = TracedClient(trace, timeout=min(timeout, 30.0), budget=timeout)

        trace.emit(
            "run_start",
            query=query_str,
            triples=tp_info,
            endpoints=[{"id": e.eid, "url": e.url} for e in endpoints],
            select=query.select, distinct=query.distinct, limit=query.limit,
        )

        trace.emit("phase", name="source_selection")
        ss_t0 = trace.now()
        source_map, ask_count = traced_select_sources(query, endpoints, client, tp_ids, trace)
        trace.emit(
            "source_selection_done", t0=ss_t0,
            sources={tp_ids[t]: [e.eid for e in eps] for t, eps in source_map.items()},
            ask_count=ask_count,
        )

        trace.emit("phase", name="execution")
        exec_t0 = trace.now()
        rows = traced_execute(query, source_map, client, tp_ids, trace)

        trace.emit(
            "run_complete", t0=exec_t0,
            rows=len(rows), sample=_clean_rows(rows, limit=20),
            columns=query.select or sorted(_bound_vars(rows)),
            http_requests=client.http_requests,
            total_seconds=trace.now(),
        )
    except Exception as exc:  # noqa: BLE001 — erro vai para o trace/cliente
        error = str(exc)
        trace.emit("error", message=error)
    return {"events": trace.events, "error": error}
