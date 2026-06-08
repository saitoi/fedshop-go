#!/usr/bin/env python3
"""Dependency-free, single-file FedX-style runner for small FedShop experiments.

This is not RDF4J/FedX in Python. It implements the same core pipeline used by
FedShop's FedX wrapper: parse basic graph patterns, source-select each triple
pattern with endpoint ASK probes, query selected SPARQL endpoints, and locally
join bindings. Unsupported SPARQL features fail fast instead of being silently
misread.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


RDF_TYPE = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
PREFIX_RE = re.compile(r"(?im)^\s*PREFIX\s+([A-Za-z][\w-]*):\s*<([^>]+)>")
SELECT_RE = re.compile(r"(?is)\bSELECT\s+(DISTINCT\s+)?(.+?)\s+\bWHERE\b")
LIMIT_RE = re.compile(r"(?is)\bLIMIT\s+(\d+)")
VAR_RE = re.compile(r"\?([A-Za-z_][\w-]*)")
ENDPOINT_RE = re.compile(r'(?is)<([^>]+)>\s+a\s+sd:Service\s*;.*?sd:endpoint\s+"([^"]+)"')


@dataclass(frozen=True)
class Triple:
    subject: str
    predicate: str
    object: str

    def sparql(self) -> str:
        return f"{self.subject} {self.predicate} {self.object} ."

    def variables(self) -> List[str]:
        out: List[str] = []
        for term in (self.subject, self.predicate, self.object):
            if term.startswith("?") and term[1:] not in out:
                out.append(term[1:])
        return out


@dataclass(frozen=True)
class Query:
    prefixes: Dict[str, str]
    select: List[str]
    triples: List[Triple]
    distinct: bool = False
    limit: Optional[int] = None


@dataclass(frozen=True)
class Endpoint:
    eid: str
    url: str


class SparqlError(RuntimeError):
    pass


def strip_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        in_iri = False
        in_string = False
        escaped = False
        keep = []
        for ch in line:
            if escaped:
                keep.append(ch)
                escaped = False
                continue
            if ch == "\\" and in_string:
                keep.append(ch)
                escaped = True
                continue
            if ch == "<" and not in_string:
                in_iri = True
            elif ch == ">" and in_iri and not in_string:
                in_iri = False
            elif ch == '"' and not in_iri:
                in_string = not in_string
            if ch == "#" and not in_iri and not in_string:
                break
            keep.append(ch)
        lines.append("".join(keep))
    return "\n".join(lines)


def matching_brace(text: str, open_pos: int) -> int:
    depth = 0
    in_iri = False
    in_string = False
    escaped = False
    for pos in range(open_pos, len(text)):
        ch = text[pos]
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_string:
            escaped = True
            continue
        if ch == "<" and not in_string:
            in_iri = True
        elif ch == ">" and in_iri and not in_string:
            in_iri = False
        elif ch == '"' and not in_iri:
            in_string = not in_string
        elif not in_iri and not in_string:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return pos
    raise SparqlError("missing closing WHERE brace")


def where_body(text: str) -> str:
    match = re.search(r"(?is)\bWHERE\b\s*{", text)
    if not match:
        raise SparqlError("unsupported query: missing WHERE block")
    open_pos = text.find("{", match.start())
    close_pos = matching_brace(text, open_pos)
    return text[open_pos + 1 : close_pos]


def tokenize(body: str) -> List[str]:
    token_re = re.compile(
        r"""
        <[^>]*>
        |"(?:\\.|[^"\\])*"(?:@[A-Za-z-]+|\^\^<[^>]+>|\^\^[A-Za-z][\w-]*:[\w.-]+)?
        |\?[A-Za-z_][\w-]*
        |[A-Za-z][\w-]*:[\w.-]+
        |[{}();,.]
        |[^\s{}();,.]+
        """,
        re.X,
    )
    return token_re.findall(strip_comments(body))


def expand_term(term: str, prefixes: Dict[str, str]) -> str:
    if term == "a":
        return RDF_TYPE
    if term.startswith("?") or term.startswith("<") or term.startswith('"'):
        return term
    if ":" in term:
        prefix, local = term.split(":", 1)
        if prefix in prefixes:
            return f"<{prefixes[prefix]}{local}>"
    return term


def parse_bgp(body: str, prefixes: Dict[str, str]) -> List[Triple]:
    tokens = tokenize(body)
    triples: List[Triple] = []
    i = 0
    last_subject: Optional[str] = None
    last_predicate: Optional[str] = None
    unsupported = {"optional", "union", "minus", "bind", "values", "graph"}
    while i < len(tokens):
        tok = tokens[i]
        low = tok.lower()
        if tok == ".":
            i += 1
            continue
        if low == "filter":
            raise SparqlError("FILTER is not supported by this single-file runner")
        if low in unsupported or tok in {"{", "}"}:
            raise SparqlError(f"unsupported SPARQL feature near {tok!r}")
        if tok == ";":
            if last_subject is None:
                raise SparqlError("semicolon without subject")
            i += 1
            if i >= len(tokens) or tokens[i] == ".":
                continue
            subject = last_subject
            predicate = expand_term(tokens[i], prefixes)
            i += 1
        elif tok == ",":
            if last_subject is None or last_predicate is None:
                raise SparqlError("comma without subject/predicate")
            subject = last_subject
            predicate = last_predicate
            i += 1
        else:
            if i + 2 >= len(tokens):
                raise SparqlError("incomplete triple pattern")
            subject = expand_term(tokens[i], prefixes)
            predicate = expand_term(tokens[i + 1], prefixes)
            i += 2
        if i >= len(tokens):
            raise SparqlError("triple pattern missing object")
        obj = expand_term(tokens[i], prefixes)
        i += 1
        triples.append(Triple(subject, predicate, obj))
        last_subject, last_predicate = subject, predicate
    if not triples:
        raise SparqlError("query has no basic graph patterns")
    return triples


def parse_query(text: str) -> Query:
    prefixes = {m.group(1): m.group(2) for m in PREFIX_RE.finditer(text)}
    select_match = SELECT_RE.search(text)
    if not select_match:
        raise SparqlError("unsupported query: missing SELECT ... WHERE")
    select_clause = select_match.group(2).strip()
    select = [] if select_clause == "*" else unique(VAR_RE.findall(select_clause))
    limit_match = LIMIT_RE.search(text)
    limit = int(limit_match.group(1)) if limit_match else None
    return Query(
        prefixes=prefixes,
        select=select,
        triples=parse_bgp(where_body(text), prefixes),
        distinct=bool(select_match.group(1)),
        limit=limit,
    )


def unique(values: Iterable[str]) -> List[str]:
    seen = set()
    out = []
    for value in values:
        if value not in seen:
            out.append(value)
            seen.add(value)
    return out


def parse_endpoints(text: str) -> List[Endpoint]:
    endpoints = []
    for idx, match in enumerate(ENDPOINT_RE.finditer(text)):
        raw_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", match.group(1)).strip("_")
        endpoints.append(Endpoint(raw_id or f"endpoint_{idx}", match.group(2)))
    if not endpoints:
        raise SparqlError("no sd:endpoint entries found in config")
    return endpoints


class HttpSparqlClient:
    def __init__(self, timeout: float = 60.0):
        self.timeout = timeout
        self.http_requests = 0

    def ask(self, endpoint: Endpoint, query: str) -> bool:
        self.http_requests += 1
        data, content_type = self._request(endpoint.url, query, "application/sparql-results+json,text/boolean,*/*")
        text = data.decode("utf-8", errors="replace").strip()
        if "json" in content_type or text.startswith("{"):
            payload = json.loads(text)
            return bool(payload.get("boolean"))
        return text.lower() in {"true", "1", "yes"}

    def select(self, endpoint: Endpoint, query: str) -> List[Dict[str, str]]:
        self.http_requests += 1
        data, content_type = self._request(endpoint.url, query, "application/sparql-results+json,text/csv,*/*")
        text = data.decode("utf-8", errors="replace")
        if "json" in content_type or text.lstrip().startswith("{"):
            return parse_sparql_json(text)
        return parse_csv_bindings(text)

    def _request(self, endpoint_url: str, query: str, accept: str) -> Tuple[bytes, str]:
        encoded = urllib.parse.urlencode({"query": query}).encode("utf-8")
        req = urllib.request.Request(endpoint_url, data=encoded, method="POST")
        req.add_header("Accept", accept)
        req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=utf-8")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read(), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            body = exc.read(4096).decode("utf-8", errors="replace")
            raise SparqlError(f"{endpoint_url} returned HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise SparqlError(f"{endpoint_url} request failed: {exc}") from exc


def parse_sparql_json(text: str) -> List[Dict[str, str]]:
    payload = json.loads(text)
    vars_ = payload.get("head", {}).get("vars", [])
    rows = []
    for binding in payload.get("results", {}).get("bindings", []):
        row = {}
        for var in vars_:
            if var in binding:
                row[var] = binding[var].get("value", "")
        rows.append(row)
    return rows


def parse_csv_bindings(text: str) -> List[Dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for record in reader:
        rows.append({k.lstrip("?"): v for k, v in record.items() if k is not None})
    return rows


def prefixes_sparql(prefixes: Dict[str, str]) -> str:
    return "".join(f"PREFIX {name}: <{iri}>\n" for name, iri in sorted(prefixes.items()))


def ask_query(prefixes: Dict[str, str], triple: Triple) -> str:
    return f"{prefixes_sparql(prefixes)}ASK WHERE {{\n  {triple.sparql()}\n}}"


def select_query(prefixes: Dict[str, str], triples: Sequence[Triple], variables: Sequence[str]) -> str:
    selected = " ".join(f"?{var}" for var in variables) if variables else "*"
    body = "\n".join(f"  {triple.sparql()}" for triple in triples)
    return f"{prefixes_sparql(prefixes)}SELECT {selected} WHERE {{\n{body}\n}}"


def select_sources(query: Query, endpoints: Sequence[Endpoint], client) -> Tuple[Dict[Triple, List[Endpoint]], int]:
    selected: Dict[Triple, List[Endpoint]] = {}
    ask_count = 0
    cache: Dict[Tuple[Triple, str], bool] = {}
    for triple in query.triples:
        sources = []
        for endpoint in endpoints:
            key = (triple, endpoint.url)
            if key not in cache:
                cache[key] = bool(client.ask(endpoint, ask_query(query.prefixes, triple)))
                ask_count += 1
            if cache[key]:
                sources.append(endpoint)
        selected[triple] = sources
    return selected, ask_count


def compatible(left: Dict[str, str], right: Dict[str, str]) -> bool:
    return all(left[k] == right[k] for k in left.keys() & right.keys())


def join_bindings(left: List[Dict[str, str]], right: List[Dict[str, str]]) -> List[Dict[str, str]]:
    if not left:
        return [dict(row) for row in right]
    if not right:
        return []
    out = []
    for lrow in left:
        for rrow in right:
            if compatible(lrow, rrow):
                merged = dict(lrow)
                merged.update(rrow)
                out.append(merged)
    return out


def distinct_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    out = []
    for row in rows:
        key = tuple(sorted(row.items()))
        if key not in seen:
            out.append(row)
            seen.add(key)
    return out


def execute(query: Query, source_map: Dict[Triple, List[Endpoint]], client) -> List[Dict[str, str]]:
    joined: List[Dict[str, str]] = []
    ordered = sorted(query.triples, key=lambda triple: len(source_map[triple]))
    for triple in ordered:
        sources = source_map[triple]
        if not sources:
            return []
        vars_ = triple.variables()
        union_rows: List[Dict[str, str]] = []
        for endpoint in sources:
            union_rows.extend(client.select(endpoint, select_query(query.prefixes, [triple], vars_)))
        joined = join_bindings(joined, union_rows)
        if not joined:
            return []
    if query.select:
        joined = [{var: row.get(var, "") for var in query.select} for row in joined]
    if query.distinct:
        joined = distinct_rows(joined)
    if query.limit is not None:
        joined = joined[: query.limit]
    return joined


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


def write_source_selection(path: str, source_map: Dict[Triple, List[Endpoint]]) -> None:
    if path == "/dev/null":
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["triple", "source_selection"])
        writer.writeheader()
        for triple, endpoints in source_map.items():
            writer.writerow(
                {
                    "triple": triple.sparql(),
                    "source_selection": json.dumps([endpoint.eid for endpoint in endpoints]),
                }
            )


def write_plan(path: str, query: Query, source_map: Dict[Triple, List[Endpoint]]) -> None:
    if path == "/dev/null":
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    lines = ["PyFedX plan", f"distinct={query.distinct}", f"limit={query.limit}", ""]
    for idx, triple in enumerate(query.triples, 1):
        sources = source_map[triple]
        node = "EmptyStatementPattern" if not sources else "ExclusiveStatement" if len(sources) == 1 else "StatementSourcePattern"
        lines.append(f"tp{idx}: {node}: {triple.sparql()}")
        lines.append(f"  sources: {', '.join(endpoint.eid for endpoint in sources) or '-'}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_stats(path: str, stats: Dict[str, object]) -> None:
    if path == "/dev/null":
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_app(args: argparse.Namespace, client: Optional[HttpSparqlClient] = None) -> int:
    started = time.monotonic()
    client = client or HttpSparqlClient(timeout=args.timeout)
    query = parse_query(Path(args.query).read_text(encoding="utf-8"))
    endpoints = parse_endpoints(Path(args.config).read_text(encoding="utf-8"))
    ss_started = time.monotonic()
    source_map, ask_count = select_sources(query, endpoints, client)
    ss_seconds = time.monotonic() - ss_started
    rows: List[Dict[str, str]] = []
    if not args.noexec:
        rows = execute(query, source_map, client)
    write_csv(args.out_result, rows, query.select)
    write_source_selection(args.out_source_selection, source_map)
    write_plan(args.query_plan, query, source_map)
    write_stats(
        args.stats,
        {
            "engine": "pyfedx",
            "ask": ask_count,
            "http_requests": client.http_requests,
            "source_selection_seconds": ss_seconds,
            "total_seconds": time.monotonic() - started,
            "rows": len(rows),
            "noexec": args.noexec,
        },
    )
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Single-file FedX-style SPARQL federation runner")
    parser.add_argument("--config", help="FedX/FedShop Turtle config containing sd:endpoint entries")
    parser.add_argument("--query", help="SPARQL SELECT query file")
    parser.add_argument("--out-result", default="/dev/null")
    parser.add_argument("--out-source-selection", default="/dev/null")
    parser.add_argument("--query-plan", default="/dev/null")
    parser.add_argument("--stats", default="/dev/null")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--noexec", action="store_true", help="perform source selection only")
    parser.add_argument("--self-test", action="store_true", help="run built-in tests")
    return parser


class FakeClient:
    def __init__(self):
        self.http_requests = 0

    def ask(self, endpoint: Endpoint, query: str) -> bool:
        self.http_requests += 1
        if "label" in query:
            return endpoint.eid in {"e1", "e2"}
        return endpoint.eid == "e1"

    def select(self, endpoint: Endpoint, query: str) -> List[Dict[str, str]]:
        self.http_requests += 1
        if "rdf-syntax-ns#type" in query:
            return [{"s": "p1"}, {"s": "p2"}]
        if endpoint.eid == "e1":
            return [{"s": "p1", "label": "Phone"}]
        return [{"s": "p2", "label": "Camera"}]


class SelfTests(unittest.TestCase):
    def test_parse_basic_query(self):
        query = parse_query(
            """PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT DISTINCT ?s ?label WHERE {
              ?s rdfs:label ?label .
              ?s a <http://example/Thing> .
            } LIMIT 3"""
        )
        self.assertTrue(query.distinct)
        self.assertEqual(query.select, ["s", "label"])
        self.assertEqual(query.limit, 3)
        self.assertEqual(query.triples[0], Triple("?s", "<http://www.w3.org/2000/01/rdf-schema#label>", "?label"))
        self.assertEqual(query.triples[1].predicate, RDF_TYPE)

    def test_parse_semicolon_expansion(self):
        query = parse_query("SELECT ?s WHERE { ?s a <T> ; <p> ?o . }")
        self.assertEqual(query.triples, [Triple("?s", RDF_TYPE, "<T>"), Triple("?s", "<p>", "?o")])

    def test_join_bindings_keeps_compatible_rows(self):
        self.assertEqual(
            join_bindings(
                [{"s": "a", "x": "1"}, {"s": "b", "x": "2"}],
                [{"s": "a", "y": "3"}, {"s": "c", "y": "4"}],
            ),
            [{"s": "a", "x": "1", "y": "3"}],
        )

    def test_source_selection_and_execution(self):
        query = parse_query(
            """PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT ?s ?label WHERE { ?s a <T> . ?s rdfs:label ?label . }"""
        )
        endpoints = [Endpoint("e1", "http://e1/sparql"), Endpoint("e2", "http://e2/sparql")]
        client = FakeClient()
        source_map, ask_count = select_sources(query, endpoints, client)
        rows = execute(query, source_map, client)
        self.assertEqual(ask_count, 4)
        self.assertEqual(rows, [{"s": "p1", "label": "Phone"}, {"s": "p2", "label": "Camera"}])

    def test_parse_endpoints(self):
        endpoints = parse_endpoints(
            '@prefix sd: <http://www.w3.org/ns/sparql-service-description#> .\n'
            '<http://vendor.example/> a sd:Service ; sd:endpoint "http://proxy/vendor" .'
        )
        self.assertEqual(endpoints, [Endpoint("http_vendor.example", "http://proxy/vendor")])


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.self_test:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(SelfTests)
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    if not args.config or not args.query:
        parser.error("--config and --query are required unless --self-test is used")
    return run_app(args)


if __name__ == "__main__":
    raise SystemExit(main())
