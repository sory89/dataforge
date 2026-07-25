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

## Verification (25/07/2026)

Deploiement observe de bout en bout sur Minikube : la revision 2 demarre en
preview, l'AnalysisRun execute le smoke test, le Rollout se met en pause
(autoPromotionEnabled: false), la preview repond 200 pendant que l'active sert
encore l'ancienne version, puis `kubectl argo rollouts promote` bascule le trafic.
La revision 1 est conservee le temps du scaleDownDelay pour permettre un rollback.

Piege rencontre : `kubectl port-forward` se lie a un pod precis et ne suit pas les
changements d'endpoints du Service. Apres une promotion, le tunnel pointe encore
sur l'ancien pod et renvoie l'ancienne reponse. Un test de bascule via
port-forward peut donc faire croire a un echec de promotion.
