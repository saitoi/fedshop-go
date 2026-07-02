from __future__ import annotations

import requests


class ProxyClient:
    """HTTP client for the FedShop proxy (/reset and /get-stats)."""

    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout

    def reset(self) -> None:
        resp = requests.get(self.base_url + "reset", timeout=self.timeout)
        if resp.status_code != 200:
            raise RuntimeError(f"Proxy /reset returned {resp.status_code}")

    def get_stats(self) -> dict:
        """Return proxy stats dict: NB_HTTP_REQ, NB_ASK, DATA_TRANSFER."""
        resp = requests.get(self.base_url + "get-stats", timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()
