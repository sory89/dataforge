# ADR-003 : Évaluation Text-to-SQL par exécution, pas par mots-clés

## Contexte
La première version du gate comparait le SQL généré à une liste de mots-clés
attendus. Une session réelle avec `qwen2.5-coder:1.5b` a révélé deux limites :

1. **Faux négatif utile** — le modèle a inventé `fct_daily_revenue.order_id`
   (colonne inexistante). Le gate l'a bien rejeté, mais par chance : le mot-clé
   attendu était absent.
2. **Faux positif** — pour « quel jour a généré le plus de revenus », le modèle
   a joint la table de détail à la table agrégée. Tous les mots-clés attendus
   étaient présents, donc PASS, alors que le JOIN duplique les lignes et gonfle
   le `SUM` : le mauvais jour est retourné.

## Décision
Le gate exécute réellement le SQL sur la base DuckDB construite par dbt et
compare le **résultat** à la valeur attendue (execution accuracy), avec
tolérance numérique et comparaison non ordonnée quand c'est pertinent.

Le jeu de données de test a été enrichi pour que le bug de duplication soit
observable : plusieurs jours comptent désormais 2 ou 3 commandes. Avec une seule
commande par jour, un JOIN fautif produisait le bon résultat par accident.

Un prompt `v3` a été ajouté : il documente explicitement que
`fct_daily_revenue` est pré-agrégée et interdit les JOIN sur les métriques
quotidiennes.

## Conséquences
- Le gate détecte les colonnes inventées (erreur du binder) et les agrégats
  faussés — invisibles pour une comparaison textuelle.
- Le golden set doit être recalibré quand les données de seed changent.
- `tests/test_eval_detects_bad_sql.py` verrouille les deux cas réels observés.
- La base dbt devient un prérequis du gate : le CI lance `dbt build` avant.

## Addendum — itération sur les prompts (25/07/2026)

Mesures réelles avec `qwen2.5-coder:1.5b`, éval par exécution :

| Prompt | Score | Nature des échecs |
|---|---|---|
| v2 (schéma seul) | 80 % | JOIN détail×agrégat, colonne inventée |
| v3 (règles négatives) | 40 % | colonnes omises — le modèle sur-applique les interdictions |
| v4 (few-shot) | à mesurer | — |

Deux enseignements contre-intuitifs :

1. **Les règles négatives dégradent les petits modèles.** Passer de v2 à v3 en
   ajoutant « n'y fais JAMAIS de JOIN » a fait chuter le score de moitié : le
   modèle a produit des requêtes minimalistes en supprimant des colonnes
   nécessaires. Sur un modèle de 1,5 Md de paramètres, les exemples (few-shot)
   sont un levier bien plus fiable que les interdictions.
2. **Un golden set ambigu mesure le test, pas le modèle.** « Combien de commandes
   par jour ? » n'indique pas si la date doit figurer dans le résultat. Deux des
   trois échecs de v3 venaient de cette ambiguïté, pas du modèle. Les questions
   ont été reformulées pour expliciter la forme attendue.

D'où `make llm-eval-compare`, qui mesure tous les prompts sur le même golden set :
sans mesure comparative, l'intuition sur « le meilleur prompt » est fausse une
fois sur deux.
