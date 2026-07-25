#!/usr/bin/env bash
# Builde l'image llm-service DIRECTEMENT dans le daemon Docker de Minikube,
# sans passer par un registry (idéal pour itérer en local).
set -euo pipefail

PROFILE=dataforge
TAG="${1:-local}"

# Pointe le client Docker vers le daemon interne de Minikube
eval "$(minikube -p "$PROFILE" docker-env)"

docker build -t "llm-service:${TAG}" llm_service/

echo ">> Image llm-service:${TAG} disponible dans le cluster."
echo ">> Pour l'utiliser, dans k8s/base/kustomization.yaml :"
echo "   images:"
echo "     - name: llm-service"
echo "       newName: llm-service"
echo "       newTag: ${TAG}"
echo ">> (avec imagePullPolicy: IfNotPresent — déjà le défaut pour un tag non-latest)"

# Alternative sans docker-env :
#   minikube image build -p dataforge -t llm-service:local llm_service/
#   minikube image load  -p dataforge llm-service:local   # si buildée hors cluster
