#!/usr/bin/env bash
# Corrige les deux causes de "No data" : RBAC nodes/proxy pour cAdvisor,
# et rappel que les annotations du Rollout viennent de Git via ArgoCD.
set -uo pipefail
[ -f k8s/monitoring/prometheus-rbac.yaml ] || { echo "Lance depuis ~/dataforge"; exit 1; }

python3 - << 'PY'
from pathlib import Path
p = Path("k8s/monitoring/prometheus-rbac.yaml"); s = p.read_text()
if "nodes/proxy" in s:
    print("  = nodes/proxy deja present")
else:
    s = s.replace("resources: [nodes, nodes/metrics,",
                  "resources: [nodes, nodes/proxy, nodes/metrics,")
    p.write_text(s)
    print("  + nodes/proxy dans le ClusterRole Prometheus")
PY

echo ""
echo ">> Diagnostic"
POD=$(kubectl -n dataforge get pod -l app=llm-service -o name 2>/dev/null | head -1)
if [ -n "$POD" ]; then
  ann=$(kubectl -n dataforge get "$POD" -o jsonpath='{.metadata.annotations.prometheus\.io/scrape}' 2>/dev/null)
  [ "$ann" = "true" ] && echo "  OK   annotation prometheus.io/scrape presente" \
                      || echo "  KO   annotation absente -> le Rollout n'est pas a jour (git push requis)"
  if kubectl -n dataforge exec "$POD" -- python -c "
import urllib.request,sys
b=urllib.request.urlopen('http://localhost:8000/metrics',timeout=5).read().decode()
sys.exit(0 if 'dataforge_queries_total' in b else 1)" 2>/dev/null; then
    echo "  OK   /metrics expose dataforge_queries_total"
  else
    echo "  KO   /metrics absent -> image sans prometheus-client (make mk-build requis)"
  fi
fi

echo ""
echo ">> Application du correctif RBAC"
kubectl apply -f k8s/monitoring/prometheus-rbac.yaml
kubectl -n monitoring delete pod -l app=prometheus
echo "     Prometheus redemarre (recharge le token et la config)"
