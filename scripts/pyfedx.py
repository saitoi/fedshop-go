#!/usr/bin/env python3
"""Dependency-free, single-file FedX-style runner for small FedShop experiments.

Supports: SELECT DISTINCT, FILTER (comparisons, REGEX, BOUND, LANGMATCHES),
OPTIONAL, UNION, ORDER BY, LIMIT.  Unsupported features (GRAPH, BIND, VALUES,
subqueries) raise SparqlError.

Source-selection output format:
  triple,source_selection
  ?s <http://...> ?o,["endpoint_id_1","endpoint_id_2"]

  Note: no trailing '.' in triple — matches the format expected by fedshop-py's
  composition.json lookup (where keys are " ".join([s, p, o])).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Constants / regex
# ---------------------------------------------------------------------------

RDF_TYPE = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
PREFIX_RE = re.compile(r"(?im)^\s*PREFIX\s+([A-Za-z][\w-]*):\s*<([^>]+)>")
SELECT_RE = re.compile(r"(?is)\bSELECT\s+(DISTINCT\s+)?(.+?)\s+(?:\bWHERE\b|\{)")
LIMIT_RE = re.compile(r"(?is)\bLIMIT\s+(\d+)")
VAR_RE = re.compile(r"\?([A-Za-z_][\w-]*)")
ENDPOINT_RE = re.compile(r'(?is)<([^>]+)>\s+a\s+sd:Service\s*;.*?sd:endpoint\s+"([^"]+)"')
ORDERBY_RE = re.compile(r"(?is)\bORDER\s+BY\b(.+?)(?:\bLIMIT\b|\bOFFSET\b|$)")

# Sentinel used to encode language tags inside string values (NUL byte).
_LANG_SEP = "\x00"

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# String / character utilities
# ---------------------------------------------------------------------------


def strip_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        in_iri = in_string = escaped = False
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
    depth = in_iri = in_string = escaped = False
    depth = 0
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
    raise SparqlError("missing closing brace")


def where_body(text: str) -> str:
    match = re.search(r"(?is)\bWHERE\b\s*{", text)
    if not match:
        # No WHERE keyword — try bare { ... }
        open_pos = text.find("{")
        if open_pos == -1:
            raise SparqlError("unsupported query: no WHERE or { block found")
        close_pos = matching_brace(text, open_pos)
        return text[open_pos + 1 : close_pos]
    open_pos = text.find("{", match.start())
    close_pos = matching_brace(text, open_pos)
    return text[open_pos + 1 : close_pos]


# ---------------------------------------------------------------------------
# Tokenizer (for BGP and filter expressions)
# ---------------------------------------------------------------------------


def tokenize(body: str) -> List[str]:
    """Tokenize a SPARQL WHERE body (not filter expressions)."""
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


def tokenize_filter(expr: str) -> List[str]:
    """Tokenize a SPARQL filter expression, correctly disambiguating < IRI > from < operator."""
    tokens: List[str] = []
    i, n = 0, len(expr)
    while i < n:
        if expr[i].isspace():
            i += 1
            continue
        # Two-char operators
        if i + 1 < n and expr[i : i + 2] in ("&&", "||", "!=", "<=", ">="):
            tokens.append(expr[i : i + 2])
            i += 2
            continue
        # IRI or < comparison operator
        if expr[i] == "<":
            j = i + 1
            # IRI if next char is not whitespace and not '='
            if j < n and not expr[j].isspace() and expr[j] != "=":
                k = expr.find(">", j)
                if k != -1 and "\n" not in expr[j:k]:
                    tokens.append(expr[i : k + 1])
                    i = k + 1
                    continue
            tokens.append("<")
            i += 1
            continue
        if expr[i] in ">!=":
            tokens.append(expr[i])
            i += 1
            continue
        # Typed/language literal
        if expr[i] == '"':
            j = i + 1
            while j < n:
                if expr[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if expr[j] == '"':
                    j += 1
                    break
                j += 1
            if j < n and expr[j : j + 2] == "^^":
                j += 2
                if j < n and expr[j] == "<":
                    k = expr.find(">", j)
                    j = k + 1 if k != -1 else j
                else:
                    while j < n and expr[j] not in " \t\n\r(),":
                        j += 1
            elif j < n and expr[j] == "@":
                j += 1
                while j < n and (expr[j].isalpha() or expr[j] == "-"):
                    j += 1
            tokens.append(expr[i:j])
            i = j
            continue
        # Variable
        if expr[i] == "?":
            j = i + 1
            while j < n and (expr[j].isalnum() or expr[j] == "_"):
                j += 1
            tokens.append(expr[i:j])
            i = j
            continue
        # Parens, comma, arithmetic operators
        if expr[i] in "(),+-*":
            tokens.append(expr[i])
            i += 1
            continue
        # Identifier / keyword / number
        j = i
        while j < n and expr[j] not in " \t\n\r<>!=&|(),+-*":
            j += 1
        if j > i:
            tokens.append(expr[i:j])
            i = j
        else:
            i += 1
    return tokens


# ---------------------------------------------------------------------------
# BGP parser (triples only, no FILTER/OPTIONAL/UNION)
# ---------------------------------------------------------------------------


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


def _parse_bgp_tokens(tokens: List[str], prefixes: Dict[str, str]) -> List[Triple]:
    """Parse a flat list of tokens into Triple objects (no FILTER/OPTIONAL/UNION)."""
    triples: List[Triple] = []
    i = 0
    last_subject = last_predicate = None
    while i < len(tokens):
        tok = tokens[i]
        low = tok.lower()
        if tok == ".":
            i += 1
            continue
        if low in ("filter", "optional", "union", "bind", "values", "graph"):
            raise SparqlError(f"unexpected keyword in BGP: {tok!r}")
        if tok in {"{", "}"}:
            raise SparqlError(f"unexpected brace in BGP: {tok!r}")
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
                raise SparqlError(f"incomplete triple pattern near {tok!r}")
            subject = expand_term(tokens[i], prefixes)
            predicate = expand_term(tokens[i + 1], prefixes)
            i += 2
        if i >= len(tokens):
            raise SparqlError("triple pattern missing object")
        obj = expand_term(tokens[i], prefixes)
        i += 1
        triples.append(Triple(subject, predicate, obj))
        last_subject, last_predicate = subject, predicate
    return triples


def parse_bgp_simple(body: str, prefixes: Dict[str, str]) -> List[Triple]:
    """Parse a WHERE sub-body that contains only triple patterns."""
    filtered = []
    for t in tokenize(body):
        if t.upper() in ("ORDER", "LIMIT", "OFFSET"):
            break
        filtered.append(t)
    return _parse_bgp_tokens(filtered, prefixes)


# ---------------------------------------------------------------------------
# Group parser
# ---------------------------------------------------------------------------


def _split_at_top_level_blocks(body: str) -> List[Tuple[str, Optional[str]]]:
    """Split body into (text_before_block, block_content) pairs.

    The last element always has block_content=None (trailing text).
    """
    result: List[Tuple[str, Optional[str]]] = []
    pos = 0
    n = len(body)
    in_iri = in_string = escaped = False
    text_start = 0

    while pos < n:
        ch = body[pos]
        if escaped:
            escaped = False
            pos += 1
            continue
        if ch == "\\" and in_string:
            escaped = True
            pos += 1
            continue
        if ch == "<" and not in_string:
            in_iri = True
        elif ch == ">" and in_iri and not in_string:
            in_iri = False
        elif ch == '"' and not in_iri:
            in_string = not in_string
        elif ch == "{" and not in_iri and not in_string:
            text_before = body[text_start:pos]
            close = matching_brace(body, pos)
            block_content = body[pos + 1 : close]
            result.append((text_before, block_content))
            text_start = close + 1
            pos = close + 1
            continue
        pos += 1

    result.append((body[text_start:], None))
    return result


def _parse_text_segment(
    text: str,
    prefixes: Dict[str, str],
    triples: List[Triple],
    filters: List[str],
) -> None:
    """Parse a text segment (between blocks) for FILTER expressions and triple patterns."""
    # Extract all FILTER(...) blocks using balanced-paren scanning
    remaining = text
    while True:
        m = re.search(r"\bFILTER\s*\(", remaining, re.I)
        if not m:
            break
        paren_start = remaining.index("(", m.start())
        depth = 0
        pos = paren_start
        while pos < len(remaining):
            if remaining[pos] == "(":
                depth += 1
            elif remaining[pos] == ")":
                depth -= 1
                if depth == 0:
                    break
            pos += 1
        filters.append(remaining[paren_start + 1 : pos])
        remaining = remaining[: m.start()] + remaining[pos + 1 :]

    # Strip trailing OPTIONAL keyword (its { } was already extracted as a block)
    remaining = re.sub(r"\bOPTIONAL\s*$", "", remaining.strip(), flags=re.I).strip()

    if remaining:
        triples.extend(parse_bgp_simple(remaining, prefixes))


def parse_group(body: str, prefixes: Dict[str, str]) -> GroupPattern:
    """Parse a WHERE body into a GroupPattern (handles FILTER, OPTIONAL, UNION)."""
    body = strip_comments(body)
    triples: List[Triple] = []
    filters: List[str] = []
    optionals: List[GroupPattern] = []
    unions: List[Tuple[GroupPattern, GroupPattern]] = []

    segments = _split_at_top_level_blocks(body)
    i = 0

    while i < len(segments):
        text, block_content = segments[i]
        text_stripped = text.strip()

        if block_content is not None:
            # Determine block type by what precedes { in the text
            upper_text = text_stripped.upper()

            if upper_text.endswith("OPTIONAL") or re.search(r"\bOPTIONAL\s*$", text_stripped, re.I):
                # OPTIONAL { ... }
                prefix_text = re.sub(r"\bOPTIONAL\s*$", "", text_stripped, flags=re.I).strip()
                if prefix_text:
                    _parse_text_segment(prefix_text, prefixes, triples, filters)
                optionals.append(parse_group(block_content, prefixes))
                i += 1
                continue

            # Check if this is the first arm of a UNION
            if i + 1 < len(segments):
                next_text, next_block = segments[i + 1]
                if next_block is not None and re.match(r"^\s*UNION\s*$", next_text, re.I):
                    arm1 = parse_group(block_content, prefixes)
                    arm2 = parse_group(next_block, prefixes)
                    unions.append((arm1, arm2))
                    # Parse any text before the first arm
                    if text_stripped:
                        _parse_text_segment(text_stripped, prefixes, triples, filters)
                    i += 2
                    continue

            # Standalone sub-group — flatten into current group
            if text_stripped:
                _parse_text_segment(text_stripped, prefixes, triples, filters)
            sub = parse_group(block_content, prefixes)
            triples.extend(sub.triples)
            filters.extend(sub.filters)
            optionals.extend(sub.optionals)
            unions.extend(sub.unions)
            i += 1
            continue

        # Final text-only segment (block_content is None)
        if text_stripped:
            _parse_text_segment(text_stripped, prefixes, triples, filters)
        i += 1

    return GroupPattern(triples=triples, filters=filters, optionals=optionals, unions=unions)


# ---------------------------------------------------------------------------
# ORDER BY parser
# ---------------------------------------------------------------------------


def _parse_order_by(text: str) -> Tuple[Tuple[str, bool], ...]:
    m = ORDERBY_RE.search(text)
    if not m:
        return ()
    order_text = m.group(1).strip()
    result: List[Tuple[str, bool]] = []
    # DESC(?var)
    for var in re.findall(r"DESC\s*\(\s*\?(\w+)\s*\)", order_text, re.I):
        result.append((var, False))
    # ASC(?var) or bare ?var (treated as ascending)
    remainder = re.sub(r"(?:ASC|DESC)\s*\([^)]+\)", "", order_text, flags=re.I)
    for var in re.findall(r"\?(\w+)", remainder):
        result.append((var, True))
    return tuple(result)


# ---------------------------------------------------------------------------
# Query parser
# ---------------------------------------------------------------------------


def unique(values: Iterable[str]) -> List[str]:
    seen: set = set()
    out: List[str] = []
    for value in values:
        if value not in seen:
            out.append(value)
            seen.add(value)
    return out


def parse_query(text: str) -> Query:
    prefixes = {m.group(1): m.group(2) for m in PREFIX_RE.finditer(text)}
    select_match = SELECT_RE.search(text)
    if not select_match:
        raise SparqlError("unsupported query: missing SELECT ... WHERE")
    select_clause = select_match.group(2).strip()
    select = [] if select_clause == "*" else unique(VAR_RE.findall(select_clause))
    limit_match = LIMIT_RE.search(text)
    limit = int(limit_match.group(1)) if limit_match else None
    group = parse_group(where_body(text), prefixes)
    order_by = _parse_order_by(text)
    return Query(
        prefixes=prefixes,
        select=select,
        group=group,
        distinct=bool(select_match.group(1)),
        limit=limit,
        order_by=order_by,
    )


def parse_endpoints(text: str) -> List[Endpoint]:
    endpoints = []
    for idx, match in enumerate(ENDPOINT_RE.finditer(text)):
        raw_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", match.group(1)).strip("_")
        endpoints.append(Endpoint(raw_id or f"endpoint_{idx}", match.group(2)))
    if not endpoints:
        raise SparqlError("no sd:endpoint entries found in config")
    return endpoints


# ---------------------------------------------------------------------------
# Filter expression evaluator
# ---------------------------------------------------------------------------


def _coerce_typed_literal(tok: str):
    """Convert a typed/plain SPARQL literal token to a Python scalar."""
    # Typed: "value"^^<xsd:type> or "value"^^xsd:type
    m = re.match(r'^"(.*?)"\^\^<?(.+?)>?$', tok, re.S)
    if m:
        val, dtype = m.group(1), m.group(2).lower()
        if "integer" in dtype or "int" in dtype:
            try:
                return int(val)
            except ValueError:
                return val
        if any(t in dtype for t in ("decimal", "double", "float")):
            try:
                return float(val)
            except ValueError:
                return val
        return val  # dates and other types: return as string
    # Language-tagged: "value"@lang
    m = re.match(r'^"(.*)"@[A-Za-z-]+$', tok, re.S)
    if m:
        return m.group(1)
    # Plain string
    m = re.match(r'^"(.*)"$', tok, re.S)
    if m:
        return m.group(1)
    return tok


def _coerce_value(val: str):
    """Coerce a binding string to int/float if possible, else return string."""
    # Strip language-tag encoding
    if _LANG_SEP in val:
        val = val.split(_LANG_SEP, 1)[0]
    if not val:
        return val
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


def _get_lang(val: str) -> str:
    """Extract language tag encoded by _LANG_SEP."""
    if _LANG_SEP in val:
        return val.split(_LANG_SEP, 1)[1]
    return ""


def _get_str(val: str) -> str:
    """Return the string value without language tag encoding."""
    if _LANG_SEP in val:
        return val.split(_LANG_SEP, 1)[0]
    return val


def _compare(left, op: str, right) -> bool:
    try:
        lf = float(left) if not isinstance(left, (int, float)) else left
        rf = float(right) if not isinstance(right, (int, float)) else right
        return {"<": lf < rf, "<=": lf <= rf, ">": lf > rf, ">=": lf >= rf,
                "=": lf == rf, "!=": lf != rf}[op]
    except (TypeError, ValueError):
        ls, rs = _get_str(str(left)), _get_str(str(right))
        return {"<": ls < rs, "<=": ls <= rs, ">": ls > rs, ">=": ls >= rs,
                "=": ls == rs, "!=": ls != rs}[op]


class _FilterParser:
    """Recursive-descent parser/evaluator for SPARQL filter expressions."""

    def __init__(self, tokens: List[str], row: Dict[str, str]):
        self.tokens = tokens
        self.pos = 0
        self.row = row

    def peek(self) -> Optional[str]:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def consume(self) -> str:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, tok: str) -> None:
        actual = self.consume()
        if actual != tok:
            raise SparqlError(f"filter: expected {tok!r}, got {actual!r}")

    def parse(self):
        val = self.or_expr()
        return val

    def or_expr(self):
        left = self.and_expr()
        while self.peek() == "||":
            self.consume()
            right = self.and_expr()
            left = bool(left) or bool(right)
        return left

    def and_expr(self):
        left = self.not_expr()
        while self.peek() == "&&":
            self.consume()
            right = self.not_expr()
            left = bool(left) and bool(right)
        return left

    def not_expr(self):
        if self.peek() == "!":
            self.consume()
            val = self.rel_expr()
            return not bool(val)
        return self.rel_expr()

    def rel_expr(self):
        left = self.add_expr()
        op = self.peek()
        if op in ("<", "<=", ">", ">=", "=", "!="):
            self.consume()
            right = self.add_expr()
            return _compare(left, op, right)
        return left

    def add_expr(self):
        left = self.primary()
        while self.peek() in ("+", "-"):
            op = self.consume()
            right = self.primary()
            try:
                lf = float(left) if not isinstance(left, (int, float)) else left
                rf = float(right) if not isinstance(right, (int, float)) else right
                left = lf + rf if op == "+" else lf - rf
            except (TypeError, ValueError):
                pass
        return left

    def primary(self):
        tok = self.peek()
        if tok is None:
            raise SparqlError("unexpected end of filter expression")

        upper = tok.upper() if isinstance(tok, str) else ""

        # Grouped expression
        if tok == "(":
            self.consume()
            val = self.or_expr()
            self.expect(")")
            return val

        # BOUND(?var)
        if upper == "BOUND":
            self.consume()
            self.expect("(")
            var_tok = self.consume()
            self.expect(")")
            var = var_tok.lstrip("?")
            val = self.row.get(var, "")
            return bool(val)

        # REGEX(?var, "pattern" [, "flags"])
        if upper == "REGEX":
            self.consume()
            self.expect("(")
            var_tok = self.consume()
            self.expect(",")
            pattern_tok = self.consume()
            flags = 0
            if self.peek() == ",":
                self.consume()
                flag_tok = self.consume()
                flag_str = _coerce_typed_literal(flag_tok)
                if "i" in str(flag_str):
                    flags |= re.I
            self.expect(")")
            var = var_tok.lstrip("?")
            value = _get_str(self.row.get(var, ""))
            pattern = _coerce_typed_literal(pattern_tok)
            try:
                return bool(re.search(str(pattern), value, flags))
            except re.error:
                return False

        # LANGMATCHES(LANG(?var), "pattern")
        if upper == "LANGMATCHES":
            self.consume()
            self.expect("(")
            lang_val = self.primary()  # inner LANG(?var) call
            self.expect(",")
            pattern_tok = self.consume()
            self.expect(")")
            pattern = str(_coerce_typed_literal(pattern_tok)).lower()
            actual = str(lang_val).lower()
            if pattern == "*":
                return bool(actual)
            return actual == pattern

        # LANG(?var)
        if upper == "LANG":
            self.consume()
            self.expect("(")
            var_tok = self.consume()
            self.expect(")")
            var = var_tok.lstrip("?")
            return _get_lang(self.row.get(var, ""))

        # STR(?var)
        if upper == "STR":
            self.consume()
            self.expect("(")
            inner = self.primary()
            self.expect(")")
            return _get_str(str(inner))

        # Variable
        if tok.startswith("?"):
            self.consume()
            return _coerce_value(self.row.get(tok[1:], ""))

        # IRI
        if tok.startswith("<") and tok.endswith(">"):
            self.consume()
            return tok

        # Literal
        if tok.startswith('"'):
            self.consume()
            return _coerce_typed_literal(tok)

        # Numeric
        try:
            self.consume()
            return int(tok)
        except ValueError:
            pass
        try:
            return float(tok)
        except ValueError:
            pass

        self.consume()
        return tok


def eval_filter(expr: str, row: Dict[str, str]) -> bool:
    """Evaluate a SPARQL filter expression string against a binding row."""
    try:
        tokens = tokenize_filter(expr)
        parser = _FilterParser(tokens, row)
        return bool(parser.parse())
    except (SparqlError, IndexError, KeyError, TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# HTTP SPARQL client
# ---------------------------------------------------------------------------


class HttpSparqlClient:
    def __init__(self, timeout: float = 60.0):
        self.timeout = timeout
        self.http_requests = 0

    def ask(self, endpoint: Endpoint, query: str) -> bool:
        self.http_requests += 1
        data, content_type = self._request(
            endpoint.url, query, "application/sparql-results+json,text/boolean,*/*"
        )
        text = data.decode("utf-8", errors="replace").strip()
        if "json" in content_type or text.startswith("{"):
            payload = json.loads(text)
            return bool(payload.get("boolean"))
        return text.lower() in {"true", "1", "yes"}

    def select(self, endpoint: Endpoint, query: str) -> List[Dict[str, str]]:
        self.http_requests += 1
        data, content_type = self._request(
            endpoint.url, query, "application/sparql-results+json,text/csv,*/*"
        )
        text = data.decode("utf-8", errors="replace")
        if "json" in content_type or text.lstrip().startswith("{"):
            return _parse_sparql_json(text)
        return _parse_csv_bindings(text)

    def _request(self, url: str, query: str, accept: str) -> Tuple[bytes, str]:
        encoded = urllib.parse.urlencode({"query": query}).encode("utf-8")
        req = urllib.request.Request(url, data=encoded, method="POST")
        req.add_header("Accept", accept)
        req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=utf-8")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read(), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            body = exc.read(4096).decode("utf-8", errors="replace")
            raise SparqlError(f"{url} returned HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise SparqlError(f"{url} request failed: {exc}") from exc


def _parse_sparql_json(text: str) -> List[Dict[str, str]]:
    payload = json.loads(text)
    vars_ = payload.get("head", {}).get("vars", [])
    rows = []
    for binding in payload.get("results", {}).get("bindings", []):
        row: Dict[str, str] = {}
        for var in vars_:
            if var in binding:
                val = binding[var].get("value", "")
                lang = binding[var].get("xml:lang", "")
                row[var] = f"{val}{_LANG_SEP}{lang}" if lang else val
        rows.append(row)
    return rows


def _parse_csv_bindings(text: str) -> List[Dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for record in reader:
        rows.append({k.lstrip("?"): v for k, v in record.items() if k is not None})
    return rows


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
    return f"{prefixes_sparql(prefixes)}SELECT {selected} WHERE {{\n{body}\n}}"


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


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _execute_bgp(
    triples: List[Triple],
    source_map: Dict[Triple, List[Endpoint]],
    client: HttpSparqlClient,
    prefixes: Dict[str, str],
) -> List[Dict[str, str]]:
    """Execute a flat list of triple patterns with source-based join."""
    result: List[Dict[str, str]] = []
    ordered = sorted(triples, key=lambda t: len(source_map.get(t, [])))
    for triple in ordered:
        sources = source_map.get(triple, [])
        if not sources:
            return []
        vars_ = triple.variables()
        union_rows: List[Dict[str, str]] = []
        for endpoint in sources:
            union_rows.extend(client.select(endpoint, select_query(prefixes, [triple], vars_)))
        result = join_bindings(result, union_rows)
        if not result:
            return []
    return result


def execute_group(
    group: GroupPattern,
    source_map: Dict[Triple, List[Endpoint]],
    client: HttpSparqlClient,
    prefixes: Dict[str, str],
) -> List[Dict[str, str]]:
    """Recursively execute a GroupPattern and return binding rows."""
    # 1. Execute mandatory BGP triples
    result = _execute_bgp(group.triples, source_map, client, prefixes)

    # 2. Execute UNION arms (dedup, then join with current result)
    for arm1, arm2 in group.unions:
        rows1 = execute_group(arm1, source_map, client, prefixes)
        rows2 = execute_group(arm2, source_map, client, prefixes)
        union_rows = distinct_rows(rows1 + rows2)
        result = join_bindings(result, union_rows) if result else union_rows

    # 3. Left-outer-join OPTIONAL patterns
    for opt in group.optionals:
        opt_result = execute_group(opt, source_map, client, prefixes)
        result = left_outer_join(result, opt_result)

    # 4. Apply FILTER predicates
    for f in group.filters:
        result = [row for row in result if eval_filter(f, row)]

    return result


def execute(
    query: Query,
    source_map: Dict[Triple, List[Endpoint]],
    client: HttpSparqlClient,
) -> List[Dict[str, str]]:
    rows = execute_group(query.group, source_map, client, query.prefixes)

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
    path: str, query: Query, source_map: Dict[Triple, List[Endpoint]]
) -> None:
    if path == "/dev/null":
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    all_triples = _collect_all_triples(query.group)
    lines = ["PyFedX plan", f"distinct={query.distinct}", f"limit={query.limit}", ""]
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


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


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
    if not args.noexec:
        rows = execute(query, source_map, client)
        exec_s = time.monotonic() - ss_started - ss_seconds
        print(f"[pyfedx] execution: {len(rows)} rows in {exec_s:.2f}s", flush=True)
    else:
        print("[pyfedx] noexec — skipping execution", flush=True)

    write_csv(args.out_result, rows, query.select)
    write_source_selection(args.out_source_selection, source_map, query.group)
    write_plan(args.query_plan, query, source_map)
    total_s = time.monotonic() - started
    print(f"[pyfedx] results  → {args.out_result}", flush=True)
    print(f"[pyfedx] sources  → {args.out_source_selection}", flush=True)
    print(f"[pyfedx] plan     → {args.query_plan}", flush=True)
    print(f"[pyfedx] stats    → {args.stats}", flush=True)
    print(f"[pyfedx] done in {total_s:.2f}s", flush=True)

    write_stats(
        args.stats,
        {
            "engine": "pyfedx",
            "ask": ask_count,
            "http_requests": client.http_requests,
            "source_selection_seconds": ss_seconds,
            "total_seconds": total_s,
            "rows": len(rows),
            "noexec": args.noexec,
        },
    )
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Single-file FedX-style SPARQL federation runner"
    )
    parser.add_argument("--config", help="Turtle config with sd:endpoint entries")
    parser.add_argument("--query", help="SPARQL SELECT query file")
    parser.add_argument("--out-result", default="/dev/null")
    parser.add_argument("--out-source-selection", default="/dev/null")
    parser.add_argument("--query-plan", default="/dev/null")
    parser.add_argument("--stats", default="/dev/null")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--noexec", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser


# ---------------------------------------------------------------------------
# Self-tests
# ---------------------------------------------------------------------------


class FakeClient:
    def __init__(self):
        self.http_requests = 0
        self.ask_responses: Dict[Tuple[str, str], bool] = {}
        self.select_responses: Dict[Tuple[str, str], List[Dict[str, str]]] = {}

    def ask(self, endpoint: Endpoint, query: str) -> bool:
        self.http_requests += 1
        for (eid, pat), val in self.ask_responses.items():
            if eid == endpoint.eid and pat in query:
                return val
        # Default: endpoint e1 has everything, e2 has "label"
        if "label" in query:
            return endpoint.eid in {"e1", "e2"}
        return endpoint.eid == "e1"

    def select(self, endpoint: Endpoint, query: str) -> List[Dict[str, str]]:
        self.http_requests += 1
        for (eid, pat), rows in self.select_responses.items():
            if eid == endpoint.eid and pat in query:
                return rows
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
        self.assertEqual(len(query.group.triples), 2)
        self.assertEqual(
            query.group.triples[0],
            Triple("?s", "<http://www.w3.org/2000/01/rdf-schema#label>", "?label"),
        )
        self.assertEqual(query.group.triples[1].predicate, RDF_TYPE)

    def test_parse_semicolon_expansion(self):
        query = parse_query("SELECT ?s WHERE { ?s a <T> ; <p> ?o . }")
        self.assertEqual(
            query.group.triples,
            [Triple("?s", RDF_TYPE, "<T>"), Triple("?s", "<p>", "?o")],
        )

    def test_parse_filter(self):
        query = parse_query(
            "SELECT ?x WHERE { ?x <p> ?v . FILTER(?v > \"5\"^^<xsd:integer>) }"
        )
        self.assertEqual(len(query.group.filters), 1)
        self.assertEqual(len(query.group.triples), 1)

    def test_parse_optional(self):
        query = parse_query(
            "SELECT ?x ?y WHERE { ?x <p> ?v . OPTIONAL { ?x <q> ?y . } }"
        )
        self.assertEqual(len(query.group.triples), 1)
        self.assertEqual(len(query.group.optionals), 1)
        self.assertEqual(len(query.group.optionals[0].triples), 1)

    def test_parse_union(self):
        query = parse_query(
            "SELECT ?x WHERE { { ?x <p> ?v . } UNION { ?x <q> ?v . } }"
        )
        self.assertEqual(len(query.group.unions), 1)
        arm1, arm2 = query.group.unions[0]
        self.assertEqual(len(arm1.triples), 1)
        self.assertEqual(len(arm2.triples), 1)

    def test_parse_order_by(self):
        query = parse_query(
            "SELECT ?x WHERE { ?x <p> ?v . } ORDER BY ?x LIMIT 10"
        )
        self.assertEqual(query.order_by, (("x", True),))
        self.assertEqual(query.limit, 10)

    def test_parse_order_by_desc(self):
        query = parse_query(
            "SELECT ?x WHERE { ?x <p> ?v . } ORDER BY DESC(?x)"
        )
        self.assertEqual(query.order_by, (("x", False),))

    def test_join_bindings_keeps_compatible_rows(self):
        self.assertEqual(
            join_bindings(
                [{"s": "a", "x": "1"}, {"s": "b", "x": "2"}],
                [{"s": "a", "y": "3"}, {"s": "c", "y": "4"}],
            ),
            [{"s": "a", "x": "1", "y": "3"}],
        )

    def test_left_outer_join_keeps_unmatched_left(self):
        result = left_outer_join(
            [{"x": "1"}, {"x": "2"}],
            [{"x": "1", "y": "A"}],
        )
        self.assertEqual(len(result), 2)
        matched = next(r for r in result if r["x"] == "1")
        self.assertEqual(matched["y"], "A")
        unmatched = next(r for r in result if r["x"] == "2")
        self.assertNotIn("y", unmatched)

    def test_left_outer_join_empty_right(self):
        left = [{"x": "1"}, {"x": "2"}]
        result = left_outer_join(left, [])
        self.assertEqual(result, [{"x": "1"}, {"x": "2"}])

    def test_filter_numeric_gt(self):
        self.assertTrue(eval_filter('?v > "5"^^<http://www.w3.org/2001/XMLSchema#integer>', {"v": "10"}))
        self.assertFalse(eval_filter('?v > "5"^^<http://www.w3.org/2001/XMLSchema#integer>', {"v": "3"}))

    def test_filter_and(self):
        expr = '?a > "1"^^<xsd:integer> && ?b < "10"^^<xsd:integer>'
        self.assertTrue(eval_filter(expr, {"a": "5", "b": "7"}))
        self.assertFalse(eval_filter(expr, {"a": "5", "b": "15"}))

    def test_filter_bound(self):
        self.assertTrue(eval_filter("BOUND(?x)", {"x": "something"}))
        self.assertFalse(eval_filter("BOUND(?x)", {"x": ""}))
        self.assertFalse(eval_filter("BOUND(?x)", {}))

    def test_filter_not_bound(self):
        self.assertTrue(eval_filter("!BOUND(?x)", {}))
        self.assertFalse(eval_filter("!BOUND(?x)", {"x": "val"}))

    def test_filter_regex(self):
        # SPARQL REGEX is case-sensitive by default
        self.assertTrue(eval_filter('REGEX(?label, "Phone")', {"label": "Smart Phone"}))
        self.assertFalse(eval_filter('REGEX(?label, "phone")', {"label": "Smart Phone"}))
        self.assertFalse(eval_filter('REGEX(?label, "tablet")', {"label": "Smart Phone"}))

    def test_filter_uri_neq_var(self):
        self.assertTrue(
            eval_filter(
                "<http://example.org/P1> != ?product",
                {"product": "<http://example.org/P2>"},
            )
        )
        self.assertFalse(
            eval_filter(
                "<http://example.org/P1> != ?product",
                {"product": "<http://example.org/P1>"},
            )
        )

    def test_filter_arithmetic(self):
        # ?sim < ?orig + 20
        expr = '?sim < ?orig + "20"^^<http://www.w3.org/2001/XMLSchema#integer>'
        self.assertTrue(eval_filter(expr, {"sim": "25", "orig": "10"}))
        self.assertFalse(eval_filter(expr, {"sim": "35", "orig": "10"}))

    def test_apply_order_by_ascending(self):
        rows = [{"x": "3"}, {"x": "1"}, {"x": "2"}]
        result = apply_order_by(rows, (("x", True),))
        self.assertEqual([r["x"] for r in result], ["1", "2", "3"])

    def test_apply_order_by_descending(self):
        rows = [{"x": "3"}, {"x": "1"}, {"x": "2"}]
        result = apply_order_by(rows, (("x", False),))
        self.assertEqual([r["x"] for r in result], ["3", "2", "1"])

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

    def test_source_selection_with_optional(self):
        """OPTIONAL with no sources for ?y should preserve left rows."""
        query = parse_query(
            "SELECT ?x ?y WHERE { ?x <p> ?z . OPTIONAL { ?x <q> ?y . } }"
        )
        endpoints = [Endpoint("e1", "http://e1/sparql")]
        client = FakeClient()
        # Override: p is on e1, q is on no endpoint
        client.ask_responses = {("e1", "<p>"): True, ("e1", "<q>"): False}
        client.select_responses = {("e1", "<p>"): [{"x": "A", "z": "1"}]}
        source_map, _ = select_sources(query, endpoints, client)
        rows = execute(query, source_map, client)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["x"], "A")
        # Unbound OPTIONAL variable must be absent (not projected as empty string)
        self.assertNotIn("y", rows[0])

    def test_execute_union(self):
        """UNION should merge and deduplicate arms."""
        query = parse_query(
            "SELECT ?x WHERE { { ?x <p1> <V> . } UNION { ?x <p2> <V> . } }"
        )
        endpoints = [Endpoint("e1", "http://e1/sparql")]
        client = FakeClient()
        client.ask_responses = {("e1", "<p1>"): True, ("e1", "<p2>"): True}
        client.select_responses = {
            ("e1", "<p1>"): [{"x": "A"}, {"x": "B"}],
            ("e1", "<p2>"): [{"x": "B"}, {"x": "C"}],
        }
        source_map, _ = select_sources(query, endpoints, client)
        rows = execute(query, source_map, client)
        xs = {r["x"] for r in rows}
        self.assertEqual(xs, {"A", "B", "C"})

    def test_parse_endpoints(self):
        endpoints = parse_endpoints(
            "@prefix sd: <http://www.w3.org/ns/sparql-service-description#> .\n"
            '<http://vendor.example/> a sd:Service ; sd:endpoint "http://proxy/vendor" .'
        )
        self.assertEqual(endpoints, [Endpoint("http_vendor.example", "http://proxy/vendor")])

    def test_source_selection_output_no_trailing_dot(self):
        """write_source_selection must not include trailing '.' in triple column."""
        query = parse_query("SELECT ?x WHERE { ?x <p> ?y . }")
        triple = query.group.triples[0]
        ep = Endpoint("e1", "http://e1/sparql")
        source_map = {triple: [ep]}
        import os, tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            tmp = f.name
        try:
            write_source_selection(tmp, source_map, query.group)
            with open(tmp) as f:
                content = f.read()
            self.assertIn("?x <p> ?y", content)
            self.assertNotIn("?x <p> ?y .", content)
        finally:
            os.unlink(tmp)


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
