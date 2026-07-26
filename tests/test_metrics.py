"""Tests des metriques Prometheus exposees par le service."""
import sys
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "llm_service"))


@pytest.fixture
def client(monkeypatch, tmp_path):
    db = tmp_path / "m.duckdb"
    duckdb.connect(str(db)).execute(
        "create table fct_daily_revenue(order_date date, nb_orders bigint, revenue_eur double)"
    )
    monkeypatch.setenv("DUCKDB_PATH", str(db))
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:1")
    import importlib

    from app import main, sql_gen

    importlib.reload(sql_gen)
    importlib.reload(main)
    return TestClient(main.app)


def test_endpoint_metrics_expose_les_familles_attendues(client):
    body = client.get("/metrics").text
    for famille in (
        "dataforge_queries_total",
        "dataforge_llm_generation_seconds",
        "dataforge_sql_execution_seconds",
        "dataforge_rows_returned",
        "dataforge_dependency_up",
    ):
        assert famille in body, f"metrique absente : {famille}"


def test_metriques_cpu_et_memoire_presentes(client):
    body = client.get("/metrics").text
    assert "process_cpu_seconds_total" in body
    assert "process_resident_memory_bytes" in body


def test_series_preinitialisees_a_zero(client):
    """Les taux doivent etre calculables des le demarrage, avant tout trafic."""
    body = client.get("/metrics").text
    assert 'outcome="invalid_sql"' in body
    assert 'outcome="ok"' in body


def test_llm_injoignable_compte_en_llm_error(client):
    assert client.post("/query", json={"question": "total ?"}).status_code == 502
    body = client.get("/metrics").text
    lignes = [
        ligne
        for ligne in body.splitlines()
        if 'outcome="llm_error"' in ligne and ligne.startswith("dataforge_")
    ]
    assert lignes and float(lignes[0].split()[-1]) >= 1


def test_readyz_alimente_la_gauge_de_dependance(client):
    client.get("/readyz")
    body = client.get("/metrics").text
    assert 'dataforge_dependency_up{dependency="ollama"} 0.0' in body
    assert 'dataforge_dependency_up{dependency="duckdb"} 1.0' in body
