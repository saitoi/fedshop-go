"""Core query and federation data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

RDF_TYPE = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"

@dataclass(frozen=True)
class Triple:
    subject: str
    predicate: str
    object: str

    def sparql(self) -> str:
        return f"{self.subject} {self.predicate} {self.object} ."

    def key(self) -> str:
        """Space-separated s p o — matches composition.json key format."""
        return f"{self.subject} {self.predicate} {self.object}"

    def variables(self) -> List[str]:
        out: List[str] = []
        for term in (self.subject, self.predicate, self.object):
            if term.startswith("?") and term[1:] not in out:
                out.append(term[1:])
        return out


@dataclass
class GroupPattern:
    triples: List[Triple] = field(default_factory=list)
    filters: List[str] = field(default_factory=list)
    optionals: List["GroupPattern"] = field(default_factory=list)
    unions: List[Tuple["GroupPattern", "GroupPattern"]] = field(default_factory=list)


@dataclass(frozen=True)
class Query:
    prefixes: Dict[str, str]
    select: List[str]
    group: GroupPattern
    distinct: bool = False
    limit: Optional[int] = None
    order_by: Tuple[Tuple[str, bool], ...] = ()   # ((var, ascending), ...)


@dataclass(frozen=True)
class Endpoint:
    eid: str
    url: str


class SparqlError(RuntimeError):
    pass


__all__ = ["Endpoint", "GroupPattern", "Query", "RDF_TYPE", "SparqlError", "Triple"]
