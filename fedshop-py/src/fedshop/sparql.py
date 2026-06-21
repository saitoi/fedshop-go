from __future__ import annotations

from io import BytesIO

import pandas as pd
from SPARQLWrapper import SPARQLWrapper, CSV, JSON


class SparqlClient:
    """Thin injectable wrapper around SPARQLWrapper."""

    def select_csv(self, endpoint: str, query: str, timeout: int | None = None) -> bytes:
        """Execute a SELECT query and return raw CSV bytes."""
        sw = SPARQLWrapper(endpoint)
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
        sw = SPARQLWrapper(endpoint)
        sw.setMethod("GET")
        sw.setReturnFormat(JSON)
        sw.setQuery(query)
        if timeout is not None:
            sw.setTimeout(timeout)
        result = sw.query().convert()
        return bool(result.get("boolean", False))
