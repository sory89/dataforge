.PHONY: setup lint test dbt-build k3d-up k3d-down llm-eval docker-build

VENV=.venv
PY=$(VENV)/bin/python
PIP=$(VENV)/bin/pip

setup:
	python3 -m venv $(VENV)
	$(PIP) install -U pip
	$(PIP) install -r requirements-dev.txt

lint:
	$(VENV)/bin/ruff check airflow llm_service tests
	$(VENV)/bin/sqlfluff lint dbt/models --dialect duckdb
	docker run --rm -i hadolint/hadolint < llm_service/Dockerfile || true

test:
	$(PY) -m pytest tests airflow/tests -v

dbt-build:
	cd dbt && ../$(VENV)/bin/dbt build --target dev

k3d-up:
	bash scripts/k3d_bootstrap.sh

k3d-down:
	k3d cluster delete dataforge

llm-eval:
	$(PY) llm_service/eval/run_eval.py --threshold 0.80

docker-build:
	docker build -f llm_service/Dockerfile -t dataforge/llm-service:local .

# --- Minikube ---
.PHONY: mk-up mk-down mk-build mk-deploy mk-status

mk-up:
	bash scripts/minikube_bootstrap.sh

mk-down:
	minikube delete --profile dataforge

mk-build:
	bash scripts/minikube_build_image.sh local

mk-deploy:
	kubectl apply -k k8s/overlays/local

mk-status:
	kubectl -n dataforge get rollout,pods,svc
	kubectl argo rollouts get rollout llm-service -n dataforge || true

llm-eval-compare:
	@for v in v2 v4 v5; do \
		echo "=== prompt $$v ==="; \
		$(PY) llm_service/eval/run_eval.py --prompt $$v --threshold 0 | tail -1; \
	done

# --- Monitoring ---
.PHONY: mk-monitoring mk-monitoring-ui

mk-monitoring:
	kubectl apply -k k8s/monitoring
	kubectl -n monitoring rollout status deploy/prometheus --timeout=180s
	kubectl -n monitoring rollout status deploy/grafana --timeout=180s

mk-monitoring-ui:
	@pkill -f "port-forward.*3000" 2>/dev/null || true
	@pkill -f "port-forward.*9090" 2>/dev/null || true
	@kubectl -n monitoring port-forward svc/grafana 3000:3000 > /dev/null 2>&1 &
	@kubectl -n monitoring port-forward svc/prometheus 9090:9090 > /dev/null 2>&1 &
	@sleep 3
	@echo "Grafana    http://localhost:3000  (anonyme, ou admin/dataforge)"
	@echo "Prometheus http://localhost:9090"
