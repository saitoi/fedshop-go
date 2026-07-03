"""Executa o fedshop-go com --trace e normaliza o trace para o formato do player.

O binário é a cópia local do trabalho (../go-engine/fedshop-go, compilar com
`go build -o fedshop-go ./cmd/fedshop-go`); a flag --trace grava os eventos no
mesmo schema do tracer.py. Aqui só é preciso:
  - gerar o config TTL (sd:Service) a partir do proxy mapping JSON,
  - normalizar os ids de endpoint ("http_www.vendor0.fr" → "vendor0").
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

_DEFAULT_BINARY = Path(__file__).parent.parent / "go-engine" / "fedshop-go"
BINARY = Path(os.environ.get("FEDSHOP_GO_BINARY", str(_DEFAULT_BINARY)))


def _endpoint_ttl(mapping: dict[str, str]) -> str:
    lines = [
        "@prefix sd: <http://www.w3.org/ns/sparql-service-description#> .",
        "@prefix fedx: <http://rdf4j.org/config/federation#> .",
        "",
    ]
    for iri, url in mapping.items():
        url = url.replace("host.docker.internal", "localhost")
        lines += [
            f"<{iri}> a sd:Service ;",
            '    fedx:store "SPARQLEndpoint" ;',
            f'    sd:endpoint "{url}" ;',
            "    fedx:supportsASKQueries true .",
            "",
        ]
    return "\n".join(lines)


def _short_endpoint_id(raw: str) -> str:
    """"http_www.vendor0.fr" ou "http://www.vendor0.fr/" → "vendor0"."""
    m = re.search(r"(vendor|ratingsite)(\d+)", raw)
    if m:
        return f"{m.group(1)}{m.group(2)}"
    return re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("_")


def _normalize(trace: dict) -> dict:
    """Encurta os ids de endpoint em todos os eventos (in place)."""
    id_map: dict[str, str] = {}
    for ev in trace.get("events", []):
        if ev.get("type") == "run_start":
            for ep in ev.get("endpoints", []):
                short = _short_endpoint_id(ep.get("graph_iri") or ep["id"])
                id_map[ep["id"]] = short
                ep["id"] = short
    for ev in trace.get("events", []):
        if "endpoint_id" in ev:
            ev["endpoint_id"] = id_map.get(ev["endpoint_id"], _short_endpoint_id(ev["endpoint_id"]))
        if ev.get("type") in ("source_selection_done",) and "sources" in ev:
            ev["sources"] = {
                tp: [id_map.get(e, _short_endpoint_id(e)) for e in eps]
                for tp, eps in ev["sources"].items()
            }
        if ev.get("type") == "tp_exec" and "sources" in ev:
            ev["sources"] = [id_map.get(e, _short_endpoint_id(e)) for e in ev["sources"]]
    events = trace.get("events", [])
    if trace.get("error") and not any(e.get("type") == "error" for e in events):
        last_t = events[-1]["t1"] if events else 0.0
        events.append({
            "seq": len(events), "type": "error",
            "t0": last_t, "t1": last_t, "message": trace["error"],
        })
    return trace


def run_traced(
    query_str: str,
    config_text: str,
    timeout: float = 60.0,
    join: str = "bind",
    binary: Optional[Path] = None,
) -> dict:
    """Executa a consulta com o fedshop-go e devolve {"events": [...], "error": ...}."""
    binary = binary or BINARY
    if not binary.exists():
        return {"events": [], "error": f"binário fedshop-go não encontrado em {binary}"}

    mapping = json.loads(config_text)
    with tempfile.TemporaryDirectory(prefix="fedshop-go-viz-") as tmp:
        tmpdir = Path(tmp)
        (tmpdir / "config.ttl").write_text(_endpoint_ttl(mapping), encoding="utf-8")
        (tmpdir / "query.sparql").write_text(query_str, encoding="utf-8")
        trace_path = tmpdir / "trace.json"
        cmd = [
            str(binary), "query",
            "--config", str(tmpdir / "config.ttl"),
            "--query", str(tmpdir / "query.sparql"),
            "--out-result", str(tmpdir / "results.csv"),
            "--out-source-selection", str(tmpdir / "ss.csv"),
            "--query-plan", str(tmpdir / "plan.txt"),
            "--stats", str(tmpdir / "stats.json"),
            "--selector", "ask",
            "--join", join,
            "--timeout", f"{timeout:.0f}s",
            "--trace", str(trace_path),
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout + 15
            )
        except subprocess.TimeoutExpired:
            return {"events": [], "error": f"fedshop-go excedeu o tempo máximo ({timeout:.0f}s)"}

        if trace_path.exists():
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            if trace.get("events") is None:
                trace["events"] = []
            if proc.returncode != 0 and not trace.get("error"):
                trace["error"] = proc.stderr.strip() or f"fedshop-go saiu com código {proc.returncode}"
            return _normalize(trace)
        return {
            "events": [],
            "error": proc.stderr.strip() or f"fedshop-go saiu com código {proc.returncode} sem gravar o trace",
        }
