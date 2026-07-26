"""Tests unitaires : extraction SQL et garde-fous de sécurité."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "llm_service"))

from app.sql_gen import extract_sql, is_safe_sql  # noqa: E402


def test_extract_from_markdown_fence():
    raw = "Voici la requête :\n```sql\nSELECT * FROM t\n```\nEt voilà."
    assert extract_sql(raw) == "SELECT * FROM t;"

def test_extract_plain_select():
    assert extract_sql("select 1") == "select 1;"

def test_extract_with_chatter():
    raw = "Bien sûr ! select count(*) from orders; J'espère que ça aide."
    assert extract_sql(raw).startswith("select count(*)")

def test_safe_sql_accepts_select():
    assert is_safe_sql("SELECT * FROM fct_daily_revenue;")

def test_safe_sql_rejects_ddl_dml():
    for bad in ["DROP TABLE t;", "select 1; delete from t", "UPDATE t SET x=1"]:
        assert not is_safe_sql(bad)

def test_safe_sql_rejects_non_select():
    assert not is_safe_sql("WITH x AS (SELECT 1) INSERT INTO t SELECT * FROM x")


def test_query_retourne_502_si_llm_injoignable(monkeypatch, tmp_path):
    """Regression : un LLM injoignable doit donner 502, pas 500 (bug du 25/07/2026)."""
    import duckdb
    from fastapi.testclient import TestClient

    db = tmp_path / "t.duckdb"
    duckdb.connect(str(db)).execute(
        "create table fct_daily_revenue(order_date date, nb_orders bigint, revenue_eur double)"
    )
    monkeypatch.setenv("DUCKDB_PATH", str(db))
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:1")

    import importlib

    from app import main, sql_gen

    importlib.reload(sql_gen)
    importlib.reload(main)
    client = TestClient(main.app)
    assert client.post("/query", json={"question": "total ?"}).status_code == 502


def test_readyz_ne_depend_pas_du_llm(monkeypatch, tmp_path):
    """La readiness ne doit pas tomber quand seul le LLM est injoignable."""
    import duckdb
    from fastapi.testclient import TestClient

    db = tmp_path / "t2.duckdb"
    duckdb.connect(str(db)).execute(
        "create table fct_daily_revenue(order_date date, nb_orders bigint, revenue_eur double)"
    )
    monkeypatch.setenv("DUCKDB_PATH", str(db))
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:1")

    import importlib

    from app import main, sql_gen

    importlib.reload(sql_gen)
    importlib.reload(main)
    body = TestClient(main.app).get("/readyz").json()
    assert body["ready"] is True
    assert "injoignable" in body["checks"]["ollama"]


def test_console_web_servie_a_la_racine():
    """La console HTML doit etre servie sur / (interface du service)."""
    from app.main import app
    from fastapi.testclient import TestClient

    r = TestClient(app).get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "fct_daily_revenue" in r.text
