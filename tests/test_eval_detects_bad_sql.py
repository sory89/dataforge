"""Anti-régression : le gate d'éval doit rejeter le SQL réellement produit
par qwen2.5-coder:1.5b lors de la session du 25/07/2026.

Cas 1 : colonne order_id inventée sur le mart agrégé -> erreur d'exécution.
Cas 2 : JOIN détail x agrégat -> lignes dupliquées, SUM gonflé, mauvais jour.
"""
import json
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "llm_service" / "eval"))

from run_eval import compare, execute  # noqa: E402

DB = ROOT / "dbt" / "dataforge.duckdb"
CASES = {
    c["id"]: c
    for c in json.loads((ROOT / "llm_service" / "eval" / "golden_set.json").read_text())
}

pytestmark = pytest.mark.skipif(not DB.exists(), reason="lancer make dbt-build d'abord")


@pytest.fixture
def con():
    return duckdb.connect(str(DB), read_only=True)


def test_colonne_inventee_rejetee(con):
    sql = (
        "SELECT COUNT(DISTINCT T2.order_id) AS c FROM stg_orders AS T1 "
        "JOIN fct_daily_revenue AS T2 ON T1.order_date = T2.order_date"
    )
    rows, err = execute(sql, con)
    assert rows is None and "order_id" in err


def test_join_gonflant_rejete(con):
    sql = (
        "SELECT o.order_date FROM stg_orders o "
        "JOIN fct_daily_revenue r ON o.order_date = r.order_date "
        "GROUP BY o.order_date ORDER BY SUM(r.revenue_eur) DESC LIMIT 1"
    )
    rows, _ = execute(sql, con)
    ok, detail = compare(rows, CASES["meilleur_jour"])
    assert not ok, f"le join gonflant aurait dû échouer ({detail})"


def test_sql_correct_accepte(con):
    sql = "SELECT order_date FROM fct_daily_revenue ORDER BY revenue_eur DESC LIMIT 1"
    rows, _ = execute(sql, con)
    ok, _ = compare(rows, CASES["meilleur_jour"])
    assert ok
