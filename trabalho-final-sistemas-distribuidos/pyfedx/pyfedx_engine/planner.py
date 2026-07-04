"""BGP ordering strategies."""

from __future__ import annotations

from typing import Dict, List

from .model import Endpoint, SparqlError, Triple

def order_triples(
    triples: List[Triple],
    source_map: Dict[Triple, List[Endpoint]],
    planner: str = "connected-source-count",
) -> List[Triple]:
    """Order BGP triples by source selectivity and graph connectivity.

    ``source-count`` is the historical PyFedX behavior. ``connected-source-count``
    starts with the most selective pattern, then keeps the join graph connected
    whenever possible, which avoids early Cartesian products in q01-style queries.
    """
    if planner == "source-count":
        return sorted(triples, key=lambda t: len(source_map.get(t, [])))
    if planner != "connected-source-count":
        raise SparqlError(f"unknown planner: {planner}")

    remaining = list(triples)
    ordered: List[Triple] = []
    bound: set = set()
    while remaining:
        if not ordered:
            choice = min(remaining, key=lambda t: (len(source_map.get(t, [])), len(t.variables())))
        else:
            connected = [t for t in remaining if bound & set(t.variables())]
            pool = connected or remaining
            choice = min(
                pool,
                key=lambda t: (
                    len(source_map.get(t, [])),
                    -len(bound & set(t.variables())),
                    len(t.variables()),
                ),
            )
        remaining.remove(choice)
        ordered.append(choice)
        bound.update(choice.variables())
    return ordered


__all__ = ["order_triples"]
