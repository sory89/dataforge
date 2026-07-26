# DataForge — CI/CD pour pipelines data et services LLM

Plateforme de démonstration, entièrement locale : un pipeline data (dbt + Airflow)
et un service Text-to-SQL, industrialisés de la pull request au déploiement
Kubernetes. Aucun compte cloud requis.

**Ce que le projet démontre** : un gate d'évaluation LLM qui bloque réellement les
régressions, un Slim CI dbt, un scan de vulnérabilités avec arbitrage documenté, et
une boucle GitOps complète — le tout mesuré, pas seulement câblé.

---

## Résultat de bout en bout

Question en français → SQL généré par un LLM local → exécution → réponse, depuis
un pod Kubernetes :

```bash
$ curl -X POST localhost:8000/query \
    -d '{"question":"Quel est le chiffre d'\''affaires total ?"}'

{"sql":"SELECT SUM(revenue_eur) AS total_revenue FROM fct_daily_revenue;",
 "rows":[{"total_revenue":1209.7}],
 "prompt_version":"v4"}

real  0m1.341s
```

Le chiffre correspond exactement à celui calculé par dbt dans le mart
`fct_daily_revenue`.

Le service expose aussi une **console web** sur `/` : on y pose la question, on
voit le SQL généré, le résultat, et — élément central — les colonnes du schéma
utilisées par la requête s'y allument. Les échecs du modèle observés dans ce
projet étant tous des violations de schéma (colonne inventée, `GROUP BY` superflu
sur une table déjà agrégée), rendre le schéma visible est ce qui permet de voir
immédiatement si le modèle est resté dans le cadre.

---

## Architecture

```
Pull request
  ├─ lint            ruff · sqlfluff · hadolint
  ├─ unit-tests      13 tests (service + intégrité des DAGs Airflow)
  ├─ dbt slim ci     state:modified+ contre le manifest de production
  ├─ security        Trivy (SARIF) · SBOM Syft
  └─ llm-eval-gate   golden set 12 cas, seuil 80 %
       │ merge sur main
       ▼
  build image (base DuckDB construite par dbt dans l'image)
       │ bump du tag dans k8s/base/
       ▼
  ArgoCD sync ──► Rollout blue/green (Argo Rollouts) ──► promotion manuelle
       │                                                        │
       │  smoke test avant bascule                  analyse Prometheus apres :
       ▼                                            rollback auto si le taux
  Prometheus · Grafana (tableau de bord versionne)   d'echec SQL depasse 25 %
```

**Stack** : dbt · DuckDB · Airflow · FastAPI · Ollama (`qwen2.5-coder:1.5b`) ·
Docker multi-stage · Kubernetes (Minikube / k3d) · ArgoCD · Argo Rollouts ·
Prometheus · Grafana · GitHub Actions · Trivy · Syft

---

## Le gate d'évaluation LLM

C'est la pièce centrale, et celle qui a le plus appris.

### Évaluation par exécution, pas par mots-clés

Le SQL généré est **réellement exécuté** sur la base construite par dbt, et le
*résultat* comparé à la valeur attendue (*execution accuracy*). Une comparaison
textuelle laissait passer des requêtes syntaxiquement plausibles mais fausses :

```sql
-- PASS avec une comparaison par mots-clés, résultat pourtant erroné :
-- le JOIN duplique les lignes et gonfle le SUM
SELECT o.order_date FROM stg_orders o
JOIN fct_daily_revenue r ON o.order_date = r.order_date
GROUP BY o.order_date ORDER BY SUM(r.revenue_eur) DESC LIMIT 1;
```

L'évaluation par exécution attrape aussi les colonnes inventées — le modèle a
produit `fct_daily_revenue.order_id`, qui n'existe pas, détecté par le binder.

### Trois bugs de méthode identifiés et corrigés

| Problème | Symptôme | Correction |
|---|---|---|
| Génération non déterministe | Le même prompt scorait 80 %, puis 40 %, puis 60 % | `temperature: 0`, `seed` fixe |
| Golden set ambigu | Questions ne précisant pas les colonnes attendues : on mesurait le test, pas le modèle | Reformulation explicite |
| Golden set non discriminant | 3 prompts très différents à 100 % sur 5 cas triviaux | 7 cas ajoutés (fenêtres, sous-requêtes scalaires, `HAVING`, `LAG`) |

**Sans reproductibilité de la mesure, toute optimisation de prompt est du bruit.**
Les trois premières itérations de prompt de ce projet comparaient des scores
instables et n'ont donc aucune valeur.

### Mesures (déterministes, 12 cas)

| Prompt | Basiques | Difficiles | Total |
|---|---|---|---|
| v4 — few-shot, 4 exemples | 5/5 | 6/7 | **92 %** |
| v5 — v4 + exemple de calcul dérivé | 4/5 | 6/7 | 83 % |

`qwen2.5-coder:1.5b` réussit `ROWS BETWEEN 2 PRECEDING`, `SUM() OVER ()`, `LAG()`,
`HAVING` et une sous-requête scalaire corrélée. Son unique échec est un `GROUP BY`
superflu sur une table déjà agrégée.

**v5 est la mesure la plus intéressante** : conçu pour corriger cet échec, il y
parvient — et casse deux autres cas au passage. Sur un modèle de cette taille, une
modification de prompt a des effets **non locaux et non prédictibles**. Le gate a
détecté une régression introduite par un changement qui paraissait raisonnable et
qui corrigeait effectivement sa cible. Sans lui, v5 partait en production comme une
amélioration. Décision : retour à v4, v5 conservé et documenté.

Détails complets dans [`docs/ADR-003`](docs/ADR-003-eval-par-execution.md).

---

## DevSecOps : arbitrer, pas masquer

Le premier scan Trivy a remonté **27 vulnérabilités CRITICAL/HIGH**, de deux
natures opposées :

| Origine | Nombre | Correctif disponible |
|---|---|---|
| Paquets Debian de l'image de base | 23 | **aucun** (`affected` / `fix_deferred`) |
| Dépendances Python du service | 4 | oui, toutes |

Les 23 CVE Debian (`perl-base`, `util-linux`, `ncurses`, `gzip`…) n'ont aucun
patch amont — changer d'image de base ne les élimine pas. Bloquer sur elles
produit un gate rouge en permanence, que l'équipe finit par désactiver, perdant
aussi la détection utile.

**Décision** : `ignore-unfixed: true`, et correction immédiate des 4 CVE Python
(`duckdb` 1.0.0 → 1.5.5 pour un accès filesystem via `sniff_csv` ; `starlette`
0.38.6 → 1.3.1 pour un SSRF et deux DoS ; `fastapi` 0.115.0 → 0.140.0, requis car
les versions antérieures épinglent `starlette < 0.39`).

Ce n'est pas l'inverse d'un `.trivyignore` par hasard : une CVE écartée faute de
patch **redevient bloquante dès qu'un correctif sort**, alors qu'une entrée dans
`.trivyignore` la masque définitivement. Le SBOM et l'upload SARIF conservent la
visibilité complète.

Détails dans [`docs/ADR-004`](docs/ADR-004-trivy-cve-non-corrigeables.md).

---

## GitOps observé, pas seulement configuré

Le `selfHeal` d'ArgoCD a écrasé une modification appliquée à la main par
`kubectl patch` et rétabli l'état déclaré dans Git. Toute correction durable doit
passer par un commit — principe souvent récité, rarement vu à l'œuvre.

Autres points de friction résolus, du genre qui coûte une demi-heure en mission :

- La CRD `applicationsets.argoproj.io` dépasse la limite de 256 Ko des annotations
  `kubectl apply` → `--server-side` obligatoire
- Ollama n'écoute que sur `127.0.0.1` → inaccessible depuis un pod, override
  systemd `OLLAMA_HOST=0.0.0.0` nécessaire
- Une action GitHub épinglée sur un tag inexistant (`trivy-action@0.24.0`) fait
  échouer un job en 4 secondes → argument pour épingler par SHA

---

## Choix d'ingénierie notables

**Readiness découplée des dépendances externes.** `/healthz` est une liveness pure ;
`/readyz` vérifie la base embarquée et *rapporte* l'état d'Ollama sans en dépendre.
Faire dépendre la disponibilité d'un pod d'un service externe provoque une
indisponibilité en cascade : si le LLM tombe, tous les pods quittent le service
alors qu'ils répondent correctement en 502.

```json
{"ready":true,"checks":{"duckdb":"ok","ollama":"injoignable: ConnectError"}}
```

**Base construite au build de l'image.** Une étape dédiée du Dockerfile multi-stage
exécute `dbt build` et copie le fichier DuckDB dans l'image — déterministe, sans
accès réseau au runtime, sans ConfigMap ni initContainer.

**Un timeout LLM fait échouer le cas, pas le run.** Un gate d'évaluation doit
rester exploitable quand le modèle est lent.

**Slim CI dbt.** Le manifest de production est mis en cache à chaque merge sur
`main`, puis les pull requests ne construisent que `state:modified+` avec `--defer`.
Le mécanisme est en place ; le projet de démonstration (2 modèles) est trop petit
pour en illustrer le gain, qui devient décisif à l'échelle de centaines de modèles.

---

## Démarrage

```bash
make setup          # venv + dépendances
make lint           # ruff · sqlfluff · hadolint
make test           # 13 tests
make dbt-build      # pipeline dbt sur DuckDB (10 tests de données)
make llm-eval       # gate d'évaluation, 12 cas

make mk-up          # Minikube + ArgoCD + Argo Rollouts
make mk-build       # image dans le daemon Docker du cluster
make mk-deploy      # overlay local
```

Prérequis : Docker, Python 3.12, Minikube, et Ollama avec `qwen2.5-coder:1.5b`.
Guide détaillé : [`docs/minikube-guide.md`](docs/minikube-guide.md).

---

## Limites assumées et suites

- **Pas de jeu de validation tenu à l'écart.** Les prompts ont été itérés en
  regardant le golden set, donc le 92 % est potentiellement surajusté. Valider la
  généralisation exige des cas jamais consultés pendant l'itération — prochaine
  étape prioritaire.
- **Modèle 1,5 Md sur CPU** : dépasse régulièrement 60 s sur les cas complexes
  (timeout relevé à 180 s). Un gate réel demanderait un modèle accéléré, ou un
  sous-ensemble en pre-merge et le jeu complet en nightly.
- **DuckDB est un moteur embarqué**, mal adapté à un service multi-répliques. En
  production, une base réseau remplacerait l'image auto-suffisante.
- **Ollama tourne sur l'hôte**, pas dans le cluster. Le déployer dans Kubernetes
  rendrait la démonstration autonome.
- **Promotion blue/green** : le mécanisme est configuré (`autoPromotionEnabled:
  false` + `AnalysisTemplate`), la promotion manuelle reste à démontrer.

---

## Décisions d'architecture

| ADR | Sujet |
|---|---|
| [001](docs/ADR-001-slim-ci.md) | Slim CI dbt avec `state:modified+` |
| [002](docs/ADR-002-blue-green-llm.md) | Blue/green pour un service LLM |
| [003](docs/ADR-003-eval-par-execution.md) | Évaluation par exécution, déterminisme, itérations de prompt |
| [004](docs/ADR-004-trivy-cve-non-corrigeables.md) | Trivy : bloquer sur le corrigeable uniquement |
| [005](docs/ADR-005-monitoring.md) | Monitoring : mesurer la qualite LLM sans verite terrain |
