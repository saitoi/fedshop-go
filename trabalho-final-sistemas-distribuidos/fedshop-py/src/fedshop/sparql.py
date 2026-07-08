from __future__ import annotations

import http.client
from io import BytesIO
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import pandas as pd
from SPARQLWrapper import SPARQLWrapper, CSV, JSON

# Virtuoso emits one `X-SPARQL-default-graph:` response header per graph in
# the query's default-graph-uri set. At large federation scale (100+
# members) this exceeds http.client's hardcoded 100-header parse limit,
# raising "got more than 100 headers" — independent of GET vs POST, since
# it's the response, not the request, that overflows.
http.client._MAXHEADERS = 10000


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
        # POST, not GET: at large batch scale (100+ federation members) each
        # added via a `default-graph-uri` query param, a GET request's URL
        # becomes long enough that Virtuoso's response breaks the client's
        # HTTP header parser ("got more than 100 headers"). POST sends the
        # same params as a form-encoded body, sidestepping the URL limit.
        sw.setMethod("POST")
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
        sw.setMethod("POST")
        sw.setReturnFormat(JSON)
        sw.setQuery(query)
        if timeout is not None:
            sw.setTimeout(timeout)
        result = sw.query().convert()
        return bool(result.get("boolean", False))
