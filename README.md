# DataForge CI/CD — DevOps for Data Engineering

Plateforme de démonstration 100 % locale : CI/CD complet pour pipelines data
(Airflow + dbt) et service LLM Text-to-SQL, avec GitOps (ArgoCD), Slim CI dbt,
déploiement blue/green (Argo Rollouts), gates d'évaluation LLM et DevSecOps
(Trivy, SBOM). Aucun compte cloud requis.

## Quickstart (Minikube)

```bash
make setup          # venv + dépendances Python
make lint           # ruff, sqlfluff, hadolint
make test           # pytest (DAGs + service LLM)
make dbt-build      # dbt build sur DuckDB local
make llm-eval       # gate d'évaluation Text-to-SQL

make mk-up          # cluster Minikube + ArgoCD + Argo Rollouts + apps
make mk-build       # image llm-service dans le daemon Docker de Minikube
make mk-deploy      # overlay Kustomize local (blue/green, 1 replica)
make mk-status      # état du rollout
```

Alternative légère : `make k3d-up` (voir `scripts/k3d_bootstrap.sh`).

## Architecture

```
PR ──► CI (lint, tests, Slim CI dbt, Trivy, SBOM, gate éval LLM)
         │ merge main
         ▼
      Build & push image (GHCR) ──► ArgoCD sync (staging)
         │ tag v*
         ▼
      Approbation ──► Prod : blue/green + smoke test + rollback en 1 commande
```

- `docs/minikube-guide.md` — guide local pas à pas
- `docs/ADR-001-slim-ci.md` — pourquoi le Slim CI dbt
- `docs/ADR-002-blue-green-llm.md` — pourquoi le blue/green pour un service LLM
# dataforge
# dataforge

