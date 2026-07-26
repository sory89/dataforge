"""Metriques Prometheus du service Text-to-SQL.

Deux familles :
  - Qualite du LLM en production : SQL invalide, resultats vides, rejets du
    garde-fou. En production on ne connait pas la reponse attendue, donc ces
    signaux indirects sont le seul moyen de detecter une regression.
  - Ressources : CPU et memoire du process, exposes automatiquement par
    prometheus_client (process_cpu_seconds_total, process_resident_memory_bytes).

Toutes les metriques de qualite portent le label prompt_version, ce qui permet
de comparer deux prompts en production et pas seulement sur le golden set.
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

QUERIES = Counter(
    "dataforge_queries_total",
    "Requetes /query traitees, par version de prompt et issue",
    ["prompt_version", "outcome"],
)

LLM_LATENCY = Histogram(
    "dataforge_llm_generation_seconds",
    "Duree de generation du SQL par le LLM",
    ["prompt_version"],
    buckets=(0.5, 1, 2, 5, 10, 20, 40, 60, 120, 180),
)

SQL_LATENCY = Histogram(
    "dataforge_sql_execution_seconds",
    "Duree d'execution du SQL sur DuckDB",
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1, 5),
)

ROWS_RETURNED = Histogram(
    "dataforge_rows_returned",
    "Nombre de lignes retournees par requete",
    buckets=(0, 1, 5, 10, 50, 100, 1000),
)

DEPS_UP = Gauge(
    "dataforge_dependency_up",
    "Etat des dependances vu par /readyz (1 = joignable)",
    ["dependency"],
)

# Issues possibles, documentees pour le tableau de bord :
#   ok            -> SQL valide, execute, resultat non vide
#   empty         -> SQL valide mais zero ligne (souvent un contresens semantique)
#   invalid_sql   -> erreur du binder DuckDB (colonne inventee, GROUP BY errone)
#   unsafe_sql    -> rejete par is_safe_sql avant d'atteindre la base
#   llm_error     -> LLM injoignable ou timeout
OUTCOMES = ("ok", "empty", "invalid_sql", "unsafe_sql", "llm_error")


def preinitialize(prompt_version: str) -> None:
    """Cree les series a zero pour que les taux soient calculables des le demarrage."""
    for outcome in OUTCOMES:
        QUERIES.labels(prompt_version=prompt_version, outcome=outcome)
    for dep in ("duckdb", "ollama"):
        DEPS_UP.labels(dependency=dep).set(0)
