#!/usr/bin/env bash
# Lance DataForge de bout en bout : cluster, image, monitoring, trafic, interfaces.
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")"
[ -f Makefile ] || { echo "Lance depuis ~/dataforge"; exit 1; }

ok()   { printf "  \033[32mOK\033[0m   %s\n" "$1"; }
bad()  { printf "  \033[31mKO\033[0m   %s\n" "$1"; }
step() { printf "\n\033[1m>> %s\033[0m\n" "$1"; }

# --- 1. Prerequis ---
step "1/6  Verification des prerequis"
docker info > /dev/null 2>&1 && ok "docker" || { bad "docker injoignable"; exit 1; }

if curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
  ok "ollama"
else
  bad "ollama injoignable — sudo systemctl start ollama"
fi

if minikube -p dataforge status 2>/dev/null | grep -q "apiserver: Running"; then
  ok "cluster minikube"
else
  echo "     demarrage du cluster..."
  minikube start --profile dataforge || exit 1
fi

# --- 2. Image ---
step "2/6  Construction de l'image dans le daemon du cluster"
make mk-build > /tmp/build.log 2>&1 && ok "image llm-service:local" \
  || { bad "build echoue — voir /tmp/build.log"; exit 1; }

# --- 3. Service ---
step "3/6  Redemarrage du service sur la nouvelle image"
kubectl -n dataforge delete pod -l app=llm-service > /dev/null 2>&1
for i in $(seq 1 30); do
  phase=$(kubectl -n dataforge get pod -l app=llm-service \
    -o jsonpath='{.items[0].status.phase}' 2>/dev/null)
  [ "$phase" = "Running" ] && break
  sleep 3
done
[ "${phase:-}" = "Running" ] && ok "pod Running" || bad "pod non pret (${phase:-absent})"

# --- 4. Monitoring ---
step "4/6  Deploiement de Prometheus, Grafana et kube-state-metrics"
kubectl apply -k k8s/monitoring > /tmp/mon.log 2>&1 || bad "apply partiel — voir /tmp/mon.log"
kubectl -n monitoring rollout status deploy/prometheus --timeout=240s > /dev/null 2>&1 \
  && ok "prometheus" || bad "prometheus non pret"
kubectl -n monitoring rollout status deploy/grafana --timeout=240s > /dev/null 2>&1 \
  && ok "grafana" || bad "grafana non pret"
kubectl -n monitoring rollout status deploy/kube-state-metrics --timeout=120s > /dev/null 2>&1 \
  && ok "kube-state-metrics" || bad "kube-state-metrics non pret"

# --- 5. Redirections ---
step "5/6  Ouverture des acces"
pkill -f "port-forward" > /dev/null 2>&1
sleep 1
kubectl -n dataforge  port-forward svc/llm-service 8000:80   > /dev/null 2>&1 &
kubectl -n monitoring port-forward svc/grafana     3000:3000 > /dev/null 2>&1 &
kubectl -n monitoring port-forward svc/prometheus  9090:9090 > /dev/null 2>&1 &
kubectl -n argocd     port-forward svc/argocd-server 8443:443 > /dev/null 2>&1 &
sleep 4
for p in 8000 3000 9090; do
  curl -sf -o /dev/null "http://localhost:$p" && ok "port $p" || bad "port $p muet"
done

# --- 6. Trafic de demonstration ---
step "6/6  Generation de trafic (remplit le tableau de bord)"
QUESTIONS=(
  "Quel est le chiffre d'affaires total ?"
  "Quelle date a le chiffre d'affaires le plus eleve ?"
  "Quels clients ont passe au moins 2 commandes ?"
  "Moyenne mobile du chiffre d'affaires sur 3 jours"
  "Panier moyen par jour"
)
for q in "${QUESTIONS[@]}"; do
  code=$(curl -s -o /dev/null -w "%{http_code}" -m 200 -X POST localhost:8000/query \
    -H 'Content-Type: application/json' -d "{\"question\":\"$q\"}")
  case "$code" in
    200) ok  "$q" ;;
    422) bad "$q  (SQL invalide — attendu pour le panier moyen)" ;;
    *)   bad "$q  (HTTP $code)" ;;
  esac
done

cat << TXT

============================== INTERFACES ==============================
 Console Text-to-SQL   http://localhost:8000
 Grafana               http://localhost:3000   -> dossier DataForge
                       anonyme en lecture, ou admin / dataforge
 Prometheus            http://localhost:9090   -> Status / Targets
 ArgoCD                https://localhost:8443  -> admin / $(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' 2>/dev/null | base64 -d)
========================================================================

Arret des redirections : pkill -f port-forward
TXT
