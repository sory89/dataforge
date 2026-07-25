# Guide Minikube — DataForge en local

## Prérequis
- Docker
- minikube >= 1.33
- kubectl
- (optionnel) plugin `kubectl-argo-rollouts` pour visualiser les rollouts

## Démarrage complet

```bash
make mk-up        # cluster + ArgoCD + Argo Rollouts + apps (4 CPU / 6 Go)
make mk-build     # builde llm-service:local dans le daemon Docker de Minikube
make mk-deploy    # applique l'overlay local (1 replica, image sans registry)
make mk-status    # état du rollout blue/green
```

## Accès aux services

```bash
# UI ArgoCD (admin / mot de passe affiché par mk-up)
kubectl -n argocd port-forward svc/argocd-server 8443:443
# Service Text-to-SQL
kubectl -n dataforge port-forward svc/llm-service 8000:80
curl -X POST localhost:8000/query -H 'Content-Type: application/json' \
  -d '{"question": "Quel est le chiffre d'\''affaires total ?"}'
```

## Cycle blue/green en local

```bash
# 1. Modifier le code, rebuilder avec un nouveau tag
bash scripts/minikube_build_image.sh v2
# 2. Mettre à jour newTag: v2 dans k8s/overlays/local/kustomization.yaml
make mk-deploy
# 3. La nouvelle version est en "preview" — smoke test automatique, puis :
kubectl argo rollouts promote llm-service -n dataforge     # bascule du trafic
kubectl argo rollouts undo llm-service -n dataforge        # rollback si besoin
```

## Différences avec k3d

| | Minikube | k3d |
|---|---|---|
| Image locale | `minikube docker-env` ou `minikube image load` | `k3d image import` |
| LoadBalancer | `minikube tunnel` | port mapping au create |
| Ressources | VM/conteneur dédié (plus lourd) | conteneurs légers |
| Addons | intégrés (`--addons`) | manuels |

Les deux scripts (`minikube_bootstrap.sh` / `k3d_bootstrap.sh`) déploient la même stack — choisis selon ta machine.

## Nettoyage

```bash
make mk-down
```

## Ollama accessible depuis le cluster

Ollama n'ecoute que sur 127.0.0.1 par defaut, donc injoignable depuis un pod.
Override systemd necessaire :

```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf << 'CONF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
CONF
sudo systemctl daemon-reload && sudo systemctl restart ollama
```

Verification : `ss -tlnp | grep 11434` doit montrer `*:11434`.
Depuis un pod : `http://host.minikube.internal:11434`.
