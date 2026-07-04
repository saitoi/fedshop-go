"""SPARQL and federation-config parsers."""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Tuple

from .model import Endpoint, GroupPattern, Query, RDF_TYPE, SparqlError, Triple

PREFIX_RE = re.compile(r"(?im)^\s*PREFIX\s+([A-Za-z][\w-]*):\s*<([^>]+)>")
SELECT_RE = re.compile(r"(?is)\bSELECT\s+(DISTINCT\s+)?(.+?)\s+(?:\bWHERE\b|\{)")
LIMIT_RE = re.compile(r"(?is)\bLIMIT\s+(\d+)")
VAR_RE = re.compile(r"\?([A-Za-z_][\w-]*)")
ENDPOINT_RE = re.compile(r"(?is)<([^>]+)>\s+a\s+sd:Service\s*;.*?sd:endpoint\s+\"([^\"]+)\"")
ORDERBY_RE = re.compile(r"(?is)\bORDER\s+BY\b(.+?)(?:\bLIMIT\b|\bOFFSET\b|$)")

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



__all__ = ["expand_term", "parse_bgp_simple", "parse_endpoints", "parse_group", "parse_query", "strip_comments", "tokenize", "tokenize_filter", "unique", "VAR_RE", "where_body"]
