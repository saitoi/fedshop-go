"""Garante que o Docker (Desktop) e os serviços de infraestrutura (Virtuoso,
proxy do FedShop) estejam de pé antes do servidor começar a atender requisições.

Chamado pelo lifespan do FastAPI em app.py. Se algo não puder ser levantado
automaticamente (Docker Desktop ausente, timeout etc.) apenas loga um aviso —
o servidor sobe do mesmo jeito, só que `/api/execute` vai falhar até a infra
estar disponível.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

_HERE = Path(__file__).parent
_DOCKER_DIR = _HERE.parent / "fedshop-py" / "docker"
_VIRTUOSO_COMPOSE = _DOCKER_DIR / "virtuoso.yml"
_PROXY_COMPOSE = _DOCKER_DIR / "proxy.yml"

_VIRTUOSO_URL = "http://localhost:8890/sparql?query=ASK%20%7B%3Fs%20%3Fp%20%3Fo%7D"
_PROXY_URL = "http://localhost:5555/get-stats"

_DOCKER_DAEMON_TIMEOUT = 90
_SERVICE_TIMEOUT = 60


def _log(msg: str) -> None:
    print(f"[infra] {msg}", file=sys.stderr, flush=True)


def _manage_infra_enabled() -> bool:
    raw = os.environ.get("FEDSHOP_WEBAPP_MANAGE_INFRA", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _docker_daemon_up() -> bool:
    return subprocess.run(
        ["docker", "info"], capture_output=True, timeout=10
    ).returncode == 0


def _url_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def _ensure_docker_daemon() -> bool:
    if _docker_daemon_up():
        return True

    if sys.platform == "darwin":
        _log("Docker não está rodando — abrindo Docker Desktop...")
        subprocess.run(["open", "-a", "Docker"], check=False)
    else:
        _log("Docker não está rodando e não sei iniciá-lo automaticamente neste SO.")
        return False

    deadline = time.monotonic() + _DOCKER_DAEMON_TIMEOUT
    while time.monotonic() < deadline:
        if _docker_daemon_up():
            _log("Docker Desktop no ar.")
            return True
        time.sleep(2)
    _log(f"Docker não respondeu em {_DOCKER_DAEMON_TIMEOUT}s — desistindo.")
    return False


def _compose_up(compose_file: Path) -> bool:
    result = subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "up", "-d"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        _log(f"falha ao subir {compose_file.name}: {result.stderr.strip()}")
        return False
    return True


def _wait_for(url: str, label: str, timeout: int = _SERVICE_TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _url_ok(url):
            _log(f"{label} disponível.")
            return True
        time.sleep(2)
    _log(f"{label} não respondeu em {timeout}s.")
    return False


def ensure_infra() -> None:
    """Sobe Docker Desktop + Virtuoso + proxy do FedShop se ainda não estiverem no ar."""
    if not _manage_infra_enabled():
        _log("gerenciamento local de infra desativado por FEDSHOP_WEBAPP_MANAGE_INFRA.")
        return

    if _url_ok(_VIRTUOSO_URL) and _url_ok(_PROXY_URL):
        _log("Virtuoso e proxy já estão de pé.")
        return

    if not _ensure_docker_daemon():
        _log("seguindo sem infra — /api/execute vai falhar até Virtuoso/proxy subirem.")
        return

    if not _url_ok(_VIRTUOSO_URL):
        _log("subindo Virtuoso...")
        if _compose_up(_VIRTUOSO_COMPOSE):
            _wait_for(_VIRTUOSO_URL, "Virtuoso")

    if not _url_ok(_PROXY_URL):
        _log("subindo proxy do FedShop...")
        if _compose_up(_PROXY_COMPOSE):
            _wait_for(_PROXY_URL, "proxy")
