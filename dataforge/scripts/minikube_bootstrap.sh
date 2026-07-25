#!/usr/bin/env bash
# Cluster local Minikube complet : ArgoCD + Argo Rollouts + apps DataForge.
# Prérequis : minikube, kubectl. Optionnel : plugin kubectl-argo-rollouts.
set -euo pipefail

PROFILE=dataforge
K8S_VERSION=v1.30.0

# --- 1. Cluster ---
if ! minikube profile list 2>/dev/null | grep -q "$PROFILE"; then
  minikube start \
    --profile "$PROFILE" \
    --kubernetes-version "$K8S_VERSION" \
    --cpus 4 --memory 6g --disk-size 30g \
    --driver docker \
    --addons metrics-server
else
  minikube start --profile "$PROFILE"
fi

kubectl config use-context "$PROFILE"

# --- 2. ArgoCD ---
echo ">> Installation ArgoCD"
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# --- 3. Argo Rollouts (blue/green) ---
echo ">> Installation Argo Rollouts"
kubectl create namespace argo-rollouts --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n argo-rollouts -f https://github.com/argoproj/argo-rollouts/releases/latest/download/install.yaml

echo ">> Attente ArgoCD..."
kubectl -n argocd rollout status deploy/argocd-server --timeout=300s

# --- 4. Applications DataForge ---
echo ">> Déploiement des applications ArgoCD"
kubectl apply -f k8s/argocd/

# --- 5. Accès ---
echo ""
echo ">> Mot de passe admin ArgoCD :"
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d && echo
echo ""
echo ">> UI ArgoCD   : kubectl -n argocd port-forward svc/argocd-server 8443:443"
echo "               puis https://localhost:8443 (user: admin)"
echo ">> Service LLM : kubectl -n dataforge port-forward svc/llm-service 8000:80"
echo ">> Dashboard   : minikube dashboard --profile $PROFILE"
