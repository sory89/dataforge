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
