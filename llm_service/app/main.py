"""Service Text-to-SQL : question en langage naturel -> SQL -> résultat DuckDB."""
from __future__ import annotations

import os
import time
from pathlib import Path

import duckdb
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from app import metrics
from app.sql_gen import OLLAMA_URL, generate_sql, is_safe_sql

app = FastAPI(title="DataForge Text-to-SQL", version="1.0.0")

DB_PATH = os.getenv("DUCKDB_PATH", ":memory:")
INDEX = Path(__file__).parent / "index.html"
PROMPT_VERSION = os.getenv("PROMPT_VERSION", "v4")

metrics.preinitialize(PROMPT_VERSION)


class Question(BaseModel):
    question: str


class SQLResponse(BaseModel):
    sql: str
    rows: list[dict]
    prompt_version: str


@app.get("/", include_in_schema=False)
def console() -> FileResponse:
    """Console web : poser une question et voir le SQL genere puis le resultat."""
    return FileResponse(INDEX, media_type="text/html")


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics() -> Response:
    """Expose les metriques applicatives ainsi que le CPU et la memoire du process."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/healthz")
def healthz() -> dict:
    """Liveness : le process repond. Ne teste pas les dependances externes."""
    return {"status": "ok", "prompt_version": PROMPT_VERSION}


@app.get("/readyz")
async def readyz() -> dict:
    """Readiness : verifie que la base et le LLM sont joignables."""
    checks = {}
    try:
        con = duckdb.connect(DB_PATH, read_only=DB_PATH != ":memory:")
        con.execute("select 1 from fct_daily_revenue limit 1")
        checks["duckdb"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["duckdb"] = f"erreur: {str(exc).splitlines()[0][:80]}"
    metrics.DEPS_UP.labels(dependency="duckdb").set(checks["duckdb"] == "ok")
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            checks["ollama"] = "ok" if r.status_code == 200 else f"http {r.status_code}"
    except httpx.HTTPError as exc:
        checks["ollama"] = f"injoignable: {type(exc).__name__}"
    metrics.DEPS_UP.labels(dependency="ollama").set(checks["ollama"] == "ok")
    # La readiness ne depend QUE de la base embarquee : faire dependre un pod
    # d'une dependance externe (le LLM) provoque une indisponibilite en cascade.
    # L'etat d'Ollama est expose pour l'observabilite, sans conditionner le trafic.
    return {"ready": checks["duckdb"] == "ok", "checks": checks}


@app.post("/query", response_model=SQLResponse)
async def query(q: Question) -> SQLResponse:
    labels = {"prompt_version": PROMPT_VERSION}
    t0 = time.perf_counter()
    try:
        sql = await generate_sql(q.question, prompt_version=PROMPT_VERSION)
    except httpx.HTTPError as exc:
        # LLM injoignable : 502 explicite plutot qu'une 500 opaque
        metrics.QUERIES.labels(**labels, outcome="llm_error").inc()
        raise HTTPException(
            status_code=502, detail=f"LLM injoignable ({type(exc).__name__})"
        ) from exc
    metrics.LLM_LATENCY.labels(**labels).observe(time.perf_counter() - t0)
    if not is_safe_sql(sql):
        metrics.QUERIES.labels(**labels, outcome="unsafe_sql").inc()
        raise HTTPException(status_code=400, detail="SQL rejeté (lecture seule uniquement)")
    t1 = time.perf_counter()
    try:
        con = duckdb.connect(DB_PATH, read_only=DB_PATH != ":memory:")
        result = con.execute(sql)
        columns = [d[0] for d in result.description]
        rows = [dict(zip(columns, r, strict=False)) for r in result.fetchall()]
    except Exception as exc:  # noqa: BLE001
        metrics.QUERIES.labels(**labels, outcome="invalid_sql").inc()
        raise HTTPException(status_code=422, detail=f"Erreur d'exécution SQL : {exc}") from exc

    metrics.SQL_LATENCY.observe(time.perf_counter() - t1)
    metrics.ROWS_RETURNED.observe(len(rows))
    metrics.QUERIES.labels(**labels, outcome="ok" if rows else "empty").inc()
    return SQLResponse(sql=sql, rows=rows, prompt_version=PROMPT_VERSION)
