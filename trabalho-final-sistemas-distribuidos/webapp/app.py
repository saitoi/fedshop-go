"""Servidor FastAPI do visualizador do motor de consultas federado (pyfedx).

Executa a consulta de verdade contra os endpoints (Virtuoso) via tracer.run_traced
e devolve o trace completo; a animação é reproduzida no frontend (arquitetura
executar → gravar → reproduzir).
"""

from __future__ import annotations

import re
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import go_engine
import config_support
import infra
import tracer


@asynccontextmanager
async def lifespan(app: FastAPI):
    infra.ensure_infra()
    yield


app = FastAPI(title="FedQuery Visualizer", lifespan=lifespan)

_HERE = Path(__file__).parent
_FEDSHOP_PY = _HERE.parent / "fedshop-py"
_GENERATION = _FEDSHOP_PY / "benchmark" / "generation"
_DATA = _FEDSHOP_PY / "data"
_DIST = _HERE / "frontend" / "dist"

if (_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    index = _DIST / "index.html"
    if not index.exists():
        raise HTTPException(
            status_code=503,
            detail="Frontend não compilado — rode `npm run build` em webapp/frontend",
        )
    return FileResponse(str(index))


@app.get("/api/queries")
def list_queries() -> JSONResponse:
    """Consultas disponíveis: instanciadas (benchmark/generation) e templates."""
    queries: list[dict] = []

    if _GENERATION.exists():
        for q_dir in sorted(_GENERATION.iterdir()):
            inst = q_dir / "instance_0" / "injected.sparql"
            if q_dir.is_dir() and inst.exists():
                queries.append({
                    "id": f"{q_dir.name}-instance0",
                    "label": q_dir.name,
                    "query": q_dir.name,
                })

    raw_dir = _FEDSHOP_PY / "inputs" / "queries"
    if raw_dir.exists():
        for sparql_file in sorted(raw_dir.glob("*.sparql")):
            name = sparql_file.stem
            if not any(q["query"] == name for q in queries):
                queries.append({
                    "id": name,
                    "label": name,
                    "query": name,
                })

    return JSONResponse(queries)


@app.get("/api/query/{query_id}")
def get_query(query_id: str) -> JSONResponse:
    plain = query_id.replace("-instance0", "")
    candidates = [
        _GENERATION / plain / "instance_0" / "injected.sparql",
        _FEDSHOP_PY / "inputs" / "queries" / f"{plain}.sparql",
    ]
    for p in candidates:
        if p.exists():
            return JSONResponse({"content": p.read_text()})
    raise HTTPException(status_code=404, detail=f"Query '{query_id}' not found")


@app.get("/api/configs")
def list_configs() -> JSONResponse:
    """Batches disponíveis para visualização."""
    configs = [
        {"id": f"batch{batch_id}", "label": f"Batch {batch_id}"}
        for batch_id in config_support.available_batch_ids(_DATA)
    ]
    return JSONResponse(configs)


class ExecuteRequest(BaseModel):
    query: str
    config_id: str = "batch0"
    engine: str = "pyfedx"
    timeout: float = 60.0


@app.get("/api/engines")
def list_engines() -> JSONResponse:
    engines = [{"id": "pyfedx", "label": "pyfedx (Python)"}]
    if go_engine.BINARY.exists():
        engines.append({"id": "fedshop-go", "label": "fedshop-go (Go, bound join)"})
    return JSONResponse(engines)


@app.post("/api/execute")
def execute(req: ExecuteRequest) -> JSONResponse:
    """Executa a consulta de verdade e devolve o trace completo para o player."""
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Consulta vazia")
    if not re.fullmatch(r"batch\d+", req.config_id):
        raise HTTPException(status_code=400, detail="config_id inválido")
    config_path = _DATA / f"virtuoso-proxy-mapping-{req.config_id}.json"

    timeout = min(req.timeout, 300.0)
    batch_id = int(req.config_id.removeprefix("batch"))
    if config_path.exists():
        mapping = config_support.normalize_mapping(json.loads(config_path.read_text()))
    elif batch_id in config_support.available_batch_ids(_DATA):
        mapping = config_support.build_batch_mapping(batch_id)
    else:
        raise HTTPException(status_code=404, detail=f"Config '{req.config_id}' não encontrado")
    config_text = json.dumps(mapping)
    if req.engine == "fedshop-go":
        result = go_engine.run_traced(req.query, config_text, timeout=timeout)
    elif req.engine == "pyfedx":
        result = tracer.run_traced(req.query, config_text, timeout=timeout)
    else:
        raise HTTPException(status_code=400, detail=f"engine '{req.engine}' desconhecido")
    result["engine"] = req.engine
    return JSONResponse(result)


# Fallback para os demais arquivos do build (favicon etc.) — registrado por
# último para não sombrear as rotas /api.
if _DIST.exists():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="dist")
