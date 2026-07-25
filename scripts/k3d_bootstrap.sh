#!/usr/bin/env bash
# Cluster local complet : k3d + ArgoCD + Argo Rollouts + apps DataForge.
set -euo pipefail

CLUSTER=dataforge

if ! k3d cluster list | grep -q "$CLUSTER"; then
  k3d cluster create "$CLUSTER" --agents 2 -p "8080:80@loadbalancer"
fi

echo ">> Installation ArgoCD"
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

echo ">> Installation Argo Rollouts"
kubectl create namespace argo-rollouts --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n argo-rollouts -f https://github.com/argoproj/argo-rollouts/releases/latest/download/install.yaml

echo ">> Attente ArgoCD..."
kubectl -n argocd rollout status deploy/argocd-server --timeout=300s

echo ">> Déploiement des applications"
kubectl apply -f k8s/argocd/

echo ">> Mot de passe admin ArgoCD :"
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d && echo
echo ">> UI : kubectl -n argocd port-forward svc/argocd-server 8443:443"
