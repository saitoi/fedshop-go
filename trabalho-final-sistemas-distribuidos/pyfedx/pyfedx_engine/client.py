"""SPARQL HTTP client."""

from __future__ import annotations

import csv
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Tuple

from .filtering import _LANG_SEP
from .model import Endpoint, SparqlError

# ---------------------------------------------------------------------------
# HTTP SPARQL client
# ---------------------------------------------------------------------------


class HttpSparqlClient:
    def __init__(self, timeout: float = 60.0):
        self.timeout = timeout
        self.http_requests = 0
        self.bytes_received = 0
        self.bytes_sent = 0
        self.request_latencies: List[float] = []
        self.requests_by_host: Dict[str, int] = {}
        self.planning_seconds = 0.0

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
            endpoint.url, query, "application/sparql-results+json,*/*;q=0.1"
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
        # Key by full endpoint URL (one per federation member): in T1/T2 all
        # members share the same host, so host granularity would collapse.
        self.requests_by_host[url] = self.requests_by_host.get(url, 0) + 1
        self.bytes_sent += len(encoded)
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = resp.read()
                self.request_latencies.append(time.monotonic() - started)
                self.bytes_received += len(data)
                return data, resp.headers.get("Content-Type", "")
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



__all__ = ["HttpSparqlClient"]
