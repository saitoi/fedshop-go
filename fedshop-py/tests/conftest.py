from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def config_small():
    from fedshop.config import load_config
    return load_config(FIXTURES / "config_small.yaml")


@pytest.fixture
def q01_query_text():
    path = FIXTURES / "q01.sparql"
    if path.exists():
        return path.read_text()
    # Minimal fallback query for algebra tests
    return """
PREFIX bsbm: <http://www4.wiwiss.fu-berlin.de/bizer/bsbm/v01/vocabulary/>
SELECT DISTINCT ?product ?label
WHERE {
    ?product a ?ProductType .
    ?product bsbm:productFeature ?ProductFeature1 .
    ?product rdfs:label ?label
}
LIMIT 10
"""


@pytest.fixture
def q01_const_info():
    path = FIXTURES / "q01.const.json"
    if path.exists():
        return json.loads(path.read_text())
    return {
        "ProductType": {},
        "ProductFeature1": {},
    }


class MockSparqlClient:
    """Pre-baked SparqlClient for tests."""

    def __init__(self, csv_response: bytes = b"col1,col2\nval1,val2\n"):
        self._csv = csv_response
        self._ask = True

    def select_csv(self, endpoint: str, query: str, timeout=None) -> bytes:
        return self._csv

    def select_df(self, endpoint: str, query: str, timeout=None) -> pd.DataFrame:
        return pd.read_csv(BytesIO(self._csv))

    def ask(self, endpoint: str, query: str, timeout=None) -> bool:
        return self._ask


class MockProxyClient:
    """Pre-baked ProxyClient for tests."""

    def __init__(self, stats: dict | None = None):
        self._stats = stats or {"NB_HTTP_REQ": 10, "NB_ASK": 5, "DATA_TRANSFER": 1024}
        self.reset_called = False

    def reset(self) -> None:
        self.reset_called = True

    def get_stats(self) -> dict:
        return self._stats


@pytest.fixture
def mock_sparql_client():
    return MockSparqlClient()


@pytest.fixture
def mock_proxy_client():
    return MockProxyClient()
