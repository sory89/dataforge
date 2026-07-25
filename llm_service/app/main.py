"""Service Text-to-SQL : question en langage naturel -> SQL -> résultat DuckDB."""
from __future__ import annotations

import os

import duckdb
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.sql_gen import generate_sql, is_safe_sql

app = FastAPI(title="DataForge Text-to-SQL", version="1.0.0")

DB_PATH = os.getenv("DUCKDB_PATH", ":memory:")
PROMPT_VERSION = os.getenv("PROMPT_VERSION", "v4")


class Question(BaseModel):
    question: str


class SQLResponse(BaseModel):
    sql: str
    rows: list[dict]
    prompt_version: str


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "prompt_version": PROMPT_VERSION}


@app.post("/query", response_model=SQLResponse)
async def query(q: Question) -> SQLResponse:
    sql = await generate_sql(q.question, prompt_version=PROMPT_VERSION)
    if not is_safe_sql(sql):
        raise HTTPException(status_code=400, detail="SQL rejeté (lecture seule uniquement)")
    try:
        con = duckdb.connect(DB_PATH, read_only=DB_PATH != ":memory:")
        result = con.execute(sql)
        columns = [d[0] for d in result.description]
        rows = [dict(zip(columns, r)) for r in result.fetchall()]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Erreur d'exécution SQL : {exc}") from exc
    return SQLResponse(sql=sql, rows=rows, prompt_version=PROMPT_VERSION)
