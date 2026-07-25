"""Gate d'évaluation Text-to-SQL par EXÉCUTION (execution accuracy).

Le SQL généré est réellement exécuté sur DuckDB et le résultat comparé à la
valeur attendue. Contrairement à une comparaison de mots-clés, cela détecte :
  - les colonnes inventées (erreur d'exécution)
  - les JOIN qui dupliquent les lignes et faussent les agrégats
  - les requêtes syntaxiquement valides mais sémantiquement fausses

Usage :
    python run_eval.py --threshold 0.80                  # Ollama réel
    python run_eval.py --threshold 0.80 --mock           # sans LLM (CI)
    python run_eval.py --threshold 0.80 --prompt v2      # comparer les prompts
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

import duckdb
import httpx

sys.path.insert(0, str(Path(__file__).parents[1]))

GOLDEN = Path(__file__).parent / "golden_set.json"
DB_PATH = Path(__file__).parents[2] / "dbt" / "dataforge.duckdb"

MOCK_ANSWERS = {
    "ca_total": "select sum(revenue_eur) from fct_daily_revenue;",
    "commandes_par_jour": "select order_date, nb_orders from fct_daily_revenue;",
    "commandes_client_101": "select * from stg_orders where customer_id = 101;",
    "meilleur_jour": (
        "select order_date from fct_daily_revenue order by revenue_eur desc limit 1;"
    ),
    "montant_moyen": (
        "select avg(amount_eur) from stg_orders where status = 'completed';"
    ),
    "clients_meilleur_jour": (
        "select distinct customer_id from stg_orders where order_date = "
        "(select order_date from fct_daily_revenue order by revenue_eur desc limit 1);"
    ),
    "part_relative": (
        "select order_date, round(100.0 * revenue_eur / "
        "(select sum(revenue_eur) from fct_daily_revenue), 2) from fct_daily_revenue;"
    ),
    "moyenne_mobile_3j": (
        "select order_date, round(avg(revenue_eur) over (order by order_date "
        "rows between 2 preceding and current row), 2) from fct_daily_revenue;"
    ),
    "clients_fideles": (
        "select customer_id, count(*) from stg_orders group by customer_id "
        "having count(*) >= 2;"
    ),
    "jours_sup_moyenne": (
        "select order_date from fct_daily_revenue where revenue_eur > "
        "(select avg(revenue_eur) from fct_daily_revenue);"
    ),
    "panier_moyen_par_jour": (
        "select order_date, round(revenue_eur / nb_orders, 2) from fct_daily_revenue;"
    ),
    "ecart_jour_precedent": (
        "select order_date, round(revenue_eur - lag(revenue_eur) over "
        "(order by order_date), 2) from fct_daily_revenue;"
    ),
}


def normalize(value: object) -> object:
    """Rend les valeurs comparables : dates -> ISO, floats -> arrondis, None conserve."""
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, int):
        return value
    return str(value) if value is not None else None


def compare(rows: list[tuple], case: dict) -> tuple[bool, str]:
    """Compare le résultat obtenu au résultat attendu du golden set."""
    actual = [[normalize(v) for v in row] for row in rows]

    if "expected_row_count" in case and len(actual) != case["expected_row_count"]:
        return False, f"{len(actual)} ligne(s) au lieu de {case['expected_row_count']}"

    if "expected_contains_value" in case:
        target = normalize(case["expected_contains_value"])
        flat = [v for row in actual for v in row]
        if target not in flat:
            return False, f"valeur {target} absente du résultat"
        return True, "valeur attendue présente"

    expected = [[normalize(v) for v in row] for row in case["expected_rows"]]

    if case.get("first_column_only"):
        actual = [[row[0]] for row in actual if row]

    if not case.get("order_matters", True):
        actual = sorted(actual, key=str)
        expected = sorted(expected, key=str)

    if len(actual) != len(expected):
        return False, f"{len(actual)} ligne(s) au lieu de {len(expected)}"

    for got, want in zip(actual, expected, strict=False):
        if len(got) < len(want):
            return False, f"colonnes manquantes : {got} vs {want}"
        for g, w in zip(got, want, strict=False):
            if g is None or w is None:
                if g is not w:
                    return False, f"valeur {g!r} au lieu de {w!r}"
                continue
            if isinstance(g, int | float) and isinstance(w, int | float):
                if abs(g - w) > case.get("tolerance", 0.01):
                    return False, f"valeur {g} au lieu de {w}"
            elif str(g) != str(w):
                return False, f"valeur {g!r} au lieu de {w!r}"
    return True, "résultat exact"


def execute(sql: str, con: duckdb.DuckDBPyConnection) -> tuple[list | None, str]:
    try:
        return con.execute(sql).fetchall(), ""
    except Exception as exc:  # noqa: BLE001
        return None, f"SQL invalide : {str(exc).splitlines()[0]}"


async def run(threshold: float, mock: bool, prompt: str) -> int:
    if not DB_PATH.exists():
        print(f"Base absente : {DB_PATH}\nLance d'abord : make dbt-build")
        return 2

    cases = json.loads(GOLDEN.read_text())
    con = duckdb.connect(str(DB_PATH), read_only=True)
    passed = 0
    results: dict[str, bool] = {}

    for case in cases:
        if mock:
            sql = MOCK_ANSWERS.get(case["id"], "")
        else:
            from app.sql_gen import generate_sql, is_safe_sql  # noqa: PLC0415

            try:
                sql = await generate_sql(case["question"], prompt_version=prompt)
            except httpx.HTTPError as exc:
                # Un LLM lent ou injoignable fait echouer LE CAS, pas tout le run.
                print(f"[FAIL] {case['question']}")
                print(f"       -> LLM indisponible : {type(exc).__name__}")
                results[case["id"]] = False
                continue
            if not is_safe_sql(sql):
                print(f"[FAIL] {case['question']}\n       SQL rejeté (non lecture seule)")
                results[case["id"]] = False
                continue

        rows, err = execute(sql, con)
        if rows is None:
            ok, detail = False, err
        else:
            ok, detail = compare(rows, case)

        passed += ok
        results[case["id"]] = ok
        print(f"[{'PASS' if ok else 'FAIL'}] {case['question']}")
        print(f"       {' '.join(sql.split())}")
        print(f"       -> {detail}")

    score = passed / len(cases)
    basiques = [c for c in cases if c.get("difficulty", "basique") == "basique"]
    n_bas = sum(results[c["id"]] for c in basiques)
    n_hard = passed - n_bas
    print(f"\n  basiques : {n_bas}/{len(basiques)}", end="")
    print(f"   difficiles : {n_hard}/{len(cases) - len(basiques)}")
    print(f"Score d'exécution : {score:.0%} ({passed}/{len(cases)})", end="")
    print(f" — seuil : {threshold:.0%} — prompt : {'mock' if mock else prompt}")
    return 0 if score >= threshold else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=0.80)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--prompt", default="v4", choices=["v1", "v2", "v3", "v4", "v5"])
    parser.add_argument(
        "--runs", type=int, default=1, help="répète l'éval pour mesurer la stabilité"
    )
    args = parser.parse_args()

    if args.runs == 1:
        sys.exit(asyncio.run(run(args.threshold, args.mock, args.prompt)))

    codes = []
    for i in range(args.runs):
        print(f"\n########## run {i + 1}/{args.runs} ##########")
        codes.append(asyncio.run(run(args.threshold, args.mock, args.prompt)))
    stable = len(set(codes)) == 1
    print(f"\nStabilité sur {args.runs} runs : ", end="")
    print("déterministe" if stable else f"NON DÉTERMINISTE (verdicts {codes})")
    sys.exit(max(codes))
