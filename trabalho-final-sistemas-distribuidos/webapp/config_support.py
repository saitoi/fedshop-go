"""Helpers for FedShop federation batch configs used by the webapp."""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlencode, urlparse

DEFAULT_BATCHES = 10
DEFAULT_MEMBERS_PER_BATCH = 10
DEFAULT_VIRTUOSO_ENDPOINT = "http://localhost:8890/sparql"
ENV_VIRTUOSO_ENDPOINT = "FEDSHOP_VIRTUOSO_ENDPOINT"
ENV_VENDOR_ENDPOINT = "FEDSHOP_VENDOR_ENDPOINT"
ENV_RATINGSITE_ENDPOINT = "FEDSHOP_RATINGSITE_ENDPOINT"


def _default_graph_url(graph_iri: str, endpoint: str = DEFAULT_VIRTUOSO_ENDPOINT) -> str:
    return f"{endpoint}?{urlencode({'default-graph-uri': graph_iri})}"


def _env_value(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def _graph_specific_endpoint(graph_iri: str) -> str | None:
    if re.search(r"vendor\d+", graph_iri):
        return _env_value(ENV_VENDOR_ENDPOINT)
    if re.search(r"ratingsite\d+", graph_iri):
        return _env_value(ENV_RATINGSITE_ENDPOINT)
    return None


def _configured_endpoint_for(graph_iri: str, fallback: str = DEFAULT_VIRTUOSO_ENDPOINT) -> str:
    return (
        _graph_specific_endpoint(graph_iri)
        or _env_value(ENV_VIRTUOSO_ENDPOINT)
        or fallback
    )


def _sparql_endpoint_for(url: str, fallback: str = DEFAULT_VIRTUOSO_ENDPOINT) -> str:
    url = url.replace("host.docker.internal", "localhost")
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}/sparql"
    return fallback


def build_batch_mapping(
    batch_id: int,
    *,
    members_per_batch: int = DEFAULT_MEMBERS_PER_BATCH,
    endpoint: str | None = None,
) -> dict[str, str]:
    """Build the cumulative FedShop member mapping for a zero-based batch id."""
    if batch_id < 0:
        raise ValueError("batch_id must be non-negative")
    upper = (batch_id + 1) * members_per_batch
    mapping: dict[str, str] = {}
    for vendor_id in range(upper):
        iri = f"http://www.vendor{vendor_id}.fr/"
        mapping[iri] = _default_graph_url(
            iri, endpoint or _configured_endpoint_for(iri)
        )
    for ratingsite_id in range(upper):
        iri = f"http://www.ratingsite{ratingsite_id}.fr/"
        mapping[iri] = _default_graph_url(
            iri, endpoint or _configured_endpoint_for(iri)
        )
    return mapping


def normalize_mapping(mapping: dict[str, str]) -> dict[str, str]:
    """Rewrite legacy per-member endpoint paths to stable default-graph URLs."""
    return {
        iri: _default_graph_url(
            iri, _configured_endpoint_for(iri, _sparql_endpoint_for(url))
        )
        for iri, url in mapping.items()
    }


def configured_batch_count() -> int:
    raw = os.environ.get("FEDSHOP_WEBAPP_BATCHES")
    if not raw:
        return DEFAULT_BATCHES
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_BATCHES


def available_batch_ids(data_dir: Path) -> list[int]:
    ids = set(range(configured_batch_count()))
    for f in data_dir.glob("virtuoso-proxy-mapping-batch*.json"):
        match = re.search(r"batch(\d+)", f.name)
        if match:
            ids.add(int(match.group(1)))
    return sorted(ids)
