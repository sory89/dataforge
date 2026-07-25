"""Génération SQL via Ollama, avec extraction robuste et garde-fous."""
from __future__ import annotations

import os
import re

import httpx

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:1.5b")
TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "60"))
# Deterministe : sans temperature nulle, le meme prompt donne des SQL
# differents d'un run a l'autre. Un gate CI non reproductible est inutilisable.
TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0"))
SEED = int(os.getenv("OLLAMA_SEED", "42"))

PROMPTS = {
    "v1": (
        "Convertis cette question en SQL DuckDB. Réponds uniquement avec le SQL.\n"
        "Question : {question}"
    ),
    "v2": (
        "Tu es un expert SQL DuckDB. Schéma disponible :\n"
        "fct_daily_revenue(order_date DATE, nb_orders INT, revenue_eur DOUBLE)\n"
        "stg_orders(order_id INT, customer_id INT, order_date DATE, "
        "amount_eur DOUBLE, status VARCHAR)\n"
        "Réponds UNIQUEMENT avec la requête SQL, sans explication ni markdown.\n"
        "Question : {question}"
    ),
    "v4": (
        "Traduis la question en SQL DuckDB.\n\n"
        "Tables :\n"
        "fct_daily_revenue(order_date DATE, nb_orders BIGINT, revenue_eur DOUBLE)"
        "  -- une ligne par jour, deja agregee\n"
        "stg_orders(order_id INT, customer_id INT, order_date DATE, "
        "amount_eur DOUBLE, status VARCHAR)  -- une ligne par commande\n\n"
        "Exemples :\n\n"
        "Q : Chiffre d'affaires par jour, avec la date\n"
        "A : SELECT order_date, revenue_eur FROM fct_daily_revenue ORDER BY order_date;\n\n"
        "Q : Quel jour compte le plus de commandes, avec la date\n"
        "A : SELECT order_date, nb_orders FROM fct_daily_revenue "
        "ORDER BY nb_orders DESC LIMIT 1;\n\n"
        "Q : Toutes les colonnes des commandes du client 42\n"
        "A : SELECT * FROM stg_orders WHERE customer_id = 42;\n\n"
        "Q : Nombre total de commandes annulees\n"
        "A : SELECT COUNT(*) FROM stg_orders WHERE status = 'cancelled';\n\n"
        "Reponds uniquement par la requete SQL.\n\n"
        "Q : {question}\n"
        "A : "
    ),
    "v3": (
        "Tu es un expert SQL DuckDB. Voici le schéma EXACT. N'utilise aucune autre "
        "colonne que celles listées.\n\n"
        "-- Table déjà AGRÉGÉE : une seule ligne par jour.\n"
        "-- nb_orders est déjà le nombre de commandes du jour.\n"
        "-- revenue_eur est déjà le chiffre d'affaires du jour.\n"
        "fct_daily_revenue(order_date DATE, nb_orders BIGINT, revenue_eur DOUBLE)\n\n"
        "-- Table de DÉTAIL : une ligne par commande.\n"
        "stg_orders(order_id INT, customer_id INT, order_date DATE, "
        "amount_eur DOUBLE, status VARCHAR)\n\n"
        "Règles impératives :\n"
        "1. Pour toute métrique quotidienne (nombre de commandes par jour, CA par jour, "
        "meilleur jour), interroge fct_daily_revenue SEULE. N'y fais JAMAIS de JOIN : "
        "joindre la table de détail dupliquerait les lignes et faussrait les totaux.\n"
        "2. Pour toute question sur des commandes individuelles ou sur le statut, "
        "interroge stg_orders SEULE.\n"
        "3. N'invente jamais de colonne. order_id n'existe QUE dans stg_orders.\n"
        "4. Réponds UNIQUEMENT avec la requête SQL, sans explication ni markdown.\n\n"
        "Question : {question}"
    ),
}

FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|attach|copy|grant)\b", re.I)


def extract_sql(raw: str) -> str:
    """Extrait le SQL d'une réponse LLM (gère les fences markdown et le bavardage)."""
    fence = re.search(r"```(?:sql)?\s*(.+?)```", raw, re.S | re.I)
    if fence:
        raw = fence.group(1)
    match = re.search(r"(select\b.+?)(?:;|$)", raw, re.S | re.I)
    return (match.group(1).strip() + ";") if match else raw.strip()


def is_safe_sql(sql: str) -> bool:
    """Lecture seule : SELECT uniquement, pas de DDL/DML."""
    return sql.strip().lower().startswith("select") and not FORBIDDEN.search(sql)


async def generate_sql(question: str, prompt_version: str = "v4") -> str:
    prompt = PROMPTS[prompt_version].format(question=question)
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": TEMPERATURE,
                    "seed": SEED,
                    "top_p": 1.0,
                    "num_predict": 256,
                },
            },
        )
        resp.raise_for_status()
        return extract_sql(resp.json()["response"])
