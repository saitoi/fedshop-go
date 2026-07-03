"""Source selection and SPARQL query builders."""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from .client import HttpSparqlClient
from .model import Endpoint, GroupPattern, Query, Triple

# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def prefixes_sparql(prefixes: Dict[str, str]) -> str:
    return "".join(f"PREFIX {name}: <{iri}>\n" for name, iri in sorted(prefixes.items()))


def ask_query(prefixes: Dict[str, str], triple: Triple) -> str:
    return f"{prefixes_sparql(prefixes)}ASK WHERE {{\n  {triple.sparql()}\n}}"


def select_query(
    prefixes: Dict[str, str], triples: Sequence[Triple], variables: Sequence[str]
) -> str:
    selected = " ".join(f"?{var}" for var in variables) if variables else "*"
    body = "\n".join(f"  {triple.sparql()}" for triple in triples)
    return f"{prefixes_sparql(prefixes)}SELECT DISTINCT {selected} WHERE {{\n{body}\n}}"


def select_group_query(
    prefixes: Dict[str, str],
    triples: Sequence[Triple],
    filters: Sequence[str],
    variables: Sequence[str],
) -> str:
    selected = " ".join(f"?{var}" for var in variables) if variables else "*"
    parts = [f"  {triple.sparql()}" for triple in triples]
    parts.extend(f"  FILTER({expr})" for expr in filters)
    body = "\n".join(parts)
    return f"{prefixes_sparql(prefixes)}SELECT DISTINCT {selected} WHERE {{\n{body}\n}}"


# ---------------------------------------------------------------------------
# Source selection
# ---------------------------------------------------------------------------


def _collect_all_triples(group: GroupPattern) -> List[Triple]:
    """Collect all distinct Triple objects in a GroupPattern (incl. unions/optionals)."""
    seen: set = set()
    result: List[Triple] = []

    def _collect(g: GroupPattern) -> None:
        for t in g.triples:
            if t not in seen:
                seen.add(t)
                result.append(t)
        for opt in g.optionals:
            _collect(opt)
        for arm1, arm2 in g.unions:
            _collect(arm1)
            _collect(arm2)

    _collect(group)
    return result


def select_sources(
    query: Query,
    endpoints: Sequence[Endpoint],
    client: HttpSparqlClient,
) -> Tuple[Dict[Triple, List[Endpoint]], int]:
    all_triples = _collect_all_triples(query.group)
    selected: Dict[Triple, List[Endpoint]] = {}
    ask_count = 0
    cache: Dict[Tuple[Triple, str], bool] = {}
    for triple in all_triples:
        sources: List[Endpoint] = []
        for endpoint in endpoints:
            key = (triple, endpoint.url)
            if key not in cache:
                cache[key] = bool(client.ask(endpoint, ask_query(query.prefixes, triple)))
                ask_count += 1
            if cache[key]:
                sources.append(endpoint)
        selected[triple] = sources
    return selected, ask_count



__all__ = ["ask_query", "prefixes_sparql", "select_group_query", "select_query", "select_sources", "_collect_all_triples"]
