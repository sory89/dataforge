#!/usr/bin/env bash
# Correctif DataForge : prompt v4 few-shot + déterminisme Ollama + golden set désambiguïsé.
# À lancer depuis ~/dataforge. Idempotent.
set -euo pipefail
[ -f llm_service/app/sql_gen.py ] || { echo "Lance ce script depuis ~/dataforge"; exit 1; }

python3 - << 'PY'
from pathlib import Path

# ---------- 1. sql_gen.py : déterminisme + prompt v4 ----------
p = Path("llm_service/app/sql_gen.py")
s = p.read_text()

if "OLLAMA_TEMPERATURE" not in s:
    s = s.replace(
        'TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "60"))',
        'TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "60"))\n'
        "# Deterministe : sans temperature nulle, le meme prompt donne des SQL\n"
        "# differents d'un run a l'autre. Un gate CI non reproductible est inutilisable.\n"
        'TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0"))\n'
        'SEED = int(os.getenv("OLLAMA_SEED", "42"))',
    )
    s = s.replace(
        'json={"model": MODEL, "prompt": prompt, "stream": False},',
        'json={\n'
        '                "model": MODEL,\n'
        '                "prompt": prompt,\n'
        '                "stream": False,\n'
        '                "options": {\n'
        '                    "temperature": TEMPERATURE,\n'
        '                    "seed": SEED,\n'
        '                    "top_p": 1.0,\n'
        '                    "num_predict": 256,\n'
        '                },\n'
        '            },',
    )
    print("  + determinisme (temperature 0, seed 42)")

if '"v4"' not in s:
    v4 = '''    "v4": (
        "Traduis la question en SQL DuckDB.\\n\\n"
        "Tables :\\n"
        "fct_daily_revenue(order_date DATE, nb_orders BIGINT, revenue_eur DOUBLE)"
        "  -- une ligne par jour, deja agregee\\n"
        "stg_orders(order_id INT, customer_id INT, order_date DATE, "
        "amount_eur DOUBLE, status VARCHAR)  -- une ligne par commande\\n\\n"
        "Exemples :\\n\\n"
        "Q : Chiffre d'affaires par jour, avec la date\\n"
        "A : SELECT order_date, revenue_eur FROM fct_daily_revenue ORDER BY order_date;\\n\\n"
        "Q : Quel jour compte le plus de commandes, avec la date\\n"
        "A : SELECT order_date, nb_orders FROM fct_daily_revenue "
        "ORDER BY nb_orders DESC LIMIT 1;\\n\\n"
        "Q : Toutes les colonnes des commandes du client 42\\n"
        "A : SELECT * FROM stg_orders WHERE customer_id = 42;\\n\\n"
        "Q : Nombre total de commandes annulees\\n"
        "A : SELECT COUNT(*) FROM stg_orders WHERE status = 'cancelled';\\n\\n"
        "Reponds uniquement par la requete SQL.\\n\\n"
        "Q : {question}\\n"
        "A : "
    ),
'''
    anchor = '    "v3": (' if '"v3": (' in s else "}\n\nFORBIDDEN"
    if anchor == '    "v3": (':
        s = s.replace(anchor, v4 + anchor, 1)
    else:
        s = s.replace("}\n\nFORBIDDEN", v4 + "}\n\nFORBIDDEN", 1)
    print("  + prompt v4 (few-shot)")

s = s.replace('prompt_version: str = "v2"', 'prompt_version: str = "v4"')
s = s.replace('prompt_version: str = "v3"', 'prompt_version: str = "v4"')
p.write_text(s)

# ---------- 2. main.py ----------
p = Path("llm_service/app/main.py")
s = p.read_text()
for old in ('"PROMPT_VERSION", "v2"', '"PROMPT_VERSION", "v3"'):
    s = s.replace(old, '"PROMPT_VERSION", "v4"')
p.write_text(s)

# ---------- 3. run_eval.py : choix v4 + option --runs ----------
p = Path("llm_service/eval/run_eval.py")
s = p.read_text()
s = s.replace('choices=["v1", "v2", "v3"]', 'choices=["v1", "v2", "v3", "v4"]')
s = s.replace('default="v3"', 'default="v4"')
s = s.replace('default="v2"', 'default="v4"')

if "--runs" not in s:
    old_tail = """    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.threshold, args.mock, args.prompt)))"""
    new_tail = """    parser.add_argument(
        "--runs", type=int, default=1, help="repete l'eval pour mesurer la stabilite"
    )
    args = parser.parse_args()

    if args.runs == 1:
        sys.exit(asyncio.run(run(args.threshold, args.mock, args.prompt)))

    codes = []
    for i in range(args.runs):
        print(f"\\n########## run {i + 1}/{args.runs} ##########")
        codes.append(asyncio.run(run(args.threshold, args.mock, args.prompt)))
    stable = len(set(codes)) == 1
    print(f"\\nStabilite sur {args.runs} runs : ", end="")
    print("deterministe" if stable else f"NON DETERMINISTE (verdicts {codes})")
    sys.exit(max(codes))"""
    s = s.replace(old_tail, new_tail, 1)
    print("  + option --runs")
p.write_text(s)

# ---------- 4. k8s manifest ----------
k = Path("k8s/base/llm-service-rollout.yaml")
if k.exists():
    t = k.read_text().replace("value: v2", "value: v4").replace("value: v3", "value: v4")
    k.write_text(t)
print("Fichiers Python corriges.")
PY

# ---------- 5. golden set desambiguise ----------
cat > llm_service/eval/golden_set.json << 'JSONEOF'
[
  {
    "id": "ca_total",
    "question": "Quel est le chiffre d'affaires total ?",
    "expected_rows": [[1209.7]],
    "tolerance": 0.01
  },
  {
    "id": "commandes_par_jour",
    "question": "Pour chaque jour, donne la date et le nombre de commandes",
    "expected_rows": [
      ["2026-06-01", 1],
      ["2026-06-02", 3],
      ["2026-06-05", 2],
      ["2026-06-08", 1],
      ["2026-06-09", 3]
    ],
    "order_matters": false
  },
  {
    "id": "commandes_client_101",
    "question": "Affiche toutes les colonnes des commandes du client 101",
    "expected_contains_value": 120.5,
    "expected_row_count": 3
  },
  {
    "id": "meilleur_jour",
    "question": "Quelle date a le chiffre d'affaires le plus eleve ?",
    "expected_rows": [["2026-06-08"]],
    "first_column_only": true
  },
  {
    "id": "montant_moyen",
    "question": "Montant moyen des commandes completees",
    "expected_rows": [[120.97]],
    "tolerance": 0.01
  }
]
JSONEOF
echo "  + golden set desambiguise"

# ---------- 6. cible Makefile ----------
if ! grep -q "llm-eval-compare" Makefile; then
cat >> Makefile << 'MKEOF'

llm-eval-compare:
	@for v in v2 v3 v4; do \
		echo "=== prompt $$v ==="; \
		$(PY) llm_service/eval/run_eval.py --prompt $$v --threshold 0 | tail -1; \
	done

llm-eval-stability:
	$(PY) llm_service/eval/run_eval.py --prompt v4 --threshold 0.80 --runs 3
MKEOF
echo "  + cibles llm-eval-compare et llm-eval-stability"
fi

echo ""
echo "Correctif applique. Verification :"
grep -c '"v4"' llm_service/app/sql_gen.py | sed 's/^/  prompt v4 present : /'
grep -c 'OLLAMA_TEMPERATURE' llm_service/app/sql_gen.py | sed 's/^/  determinisme      : /'
echo ""
echo "Lance maintenant :"
echo "  make dbt-build && make llm-eval-compare"
