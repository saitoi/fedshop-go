"""FILTER expression evaluation and binding value helpers."""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from .model import SparqlError
from .parser import tokenize_filter

_LANG_SEP = "\x00"

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



__all__ = ["eval_filter", "_get_lang", "_get_str", "_LANG_SEP"]
