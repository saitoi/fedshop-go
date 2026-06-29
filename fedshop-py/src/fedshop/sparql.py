from __future__ import annotations

from io import BytesIO
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import pandas as pd
from SPARQLWrapper import SPARQLWrapper, CSV, JSON


class SparqlClient:
    """Thin injectable wrapper around SPARQLWrapper."""

    @staticmethod
    def _wrapper(endpoint: str) -> SPARQLWrapper:
        parts = urlsplit(endpoint)
        params = parse_qs(parts.query)
        default_graphs = params.pop("default-graph-uri", [])
        base_endpoint = urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(params, doseq=True), "")
        )
        wrapper = SPARQLWrapper(base_endpoint)
        for graph in default_graphs:
            wrapper.addDefaultGraph(graph)
        return wrapper

    def select_csv(self, endpoint: str, query: str, timeout: int | None = None) -> bytes:
        """Execute a SELECT query and return raw CSV bytes."""
        sw = self._wrapper(endpoint)
        sw.setMethod("GET")
        sw.setReturnFormat(CSV)
        sw.setQuery(query)
        if timeout is not None:
            sw.setTimeout(timeout)
        return sw.query().convert()

    def select_df(self, endpoint: str, query: str, timeout: int | None = None) -> pd.DataFrame:
        """Execute a SELECT query and return a DataFrame."""
        raw = self.select_csv(endpoint, query, timeout)
        return pd.read_csv(BytesIO(raw))

    def ask(self, endpoint: str, query: str, timeout: int | None = None) -> bool:
        """Execute an ASK query and return a boolean."""
        sw = self._wrapper(endpoint)
        sw.setMethod("GET")
        sw.setReturnFormat(JSON)
        sw.setQuery(query)
        if timeout is not None:
            sw.setTimeout(timeout)
        result = sw.query().convert()
        return bool(result.get("boolean", False))
