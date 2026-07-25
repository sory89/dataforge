# ADR-001 : Slim CI dbt avec state:modified+

## Contexte
Un `dbt build` complet sur chaque PR devient coûteux et lent quand le projet grossit
(des centaines de modèles = 20-40 min de CI, coût warehouse en prod Snowflake).

## Décision
Utiliser le manifest de production (sauvegardé via GitHub Actions cache à chaque merge
sur main) comme état de référence, et ne builder que `state:modified+` (modèles modifiés
et leur aval) avec `--defer` pour référencer les objets prod non modifiés.

## Conséquences
- CI passe de O(projet) à O(changement) : quelques secondes à quelques minutes.
- Nécessite de maintenir le manifest à jour (job save-manifest sur main).
- Premier run (cache vide) : fallback build complet.
