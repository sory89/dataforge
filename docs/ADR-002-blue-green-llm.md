# ADR-002 : Blue/Green pour le service LLM via Argo Rollouts

## Contexte
Un changement de prompt ou de modèle peut dégrader silencieusement la qualité du
Text-to-SQL sans faire échouer les probes classiques (le service répond 200 mais
génère du mauvais SQL).

## Décision
1. Gate d'évaluation en CI : golden set de questions -> score minimal 80 % requis.
2. Déploiement Blue/Green (Argo Rollouts) : la nouvelle version reçoit le trafic
   preview, une AnalysisTemplate exécute un smoke test avant promotion.
3. `autoPromotionEnabled: false` : promotion manuelle en prod, rollback en une commande.

## Conséquences
- Aucune régression de qualité LLM ne peut atteindre prod sans être mesurée.
- Le versionning des prompts (PROMPT_VERSION) rend chaque déploiement traçable.
