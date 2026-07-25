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
