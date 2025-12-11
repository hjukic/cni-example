# GitOps Demo with ArgoCD + Uptime Kuma

Simple GitOps demo using ArgoCD and Helm to deploy a color-changing webapp with Uptime Kuma monitoring.

## Prerequisites

- Docker Desktop with Kubernetes enabled
- kubectl and Helm installed

**Install Tools (Windows):**
```powershell
winget install Kubernetes.kubectl
winget install Helm.Helm
```

**Enable Kubernetes:** Docker Desktop → Settings → Kubernetes → Enable Kubernetes

## Quick Start

### 1. Setup ArgoCD

```bash
git clone <repository-url>
cd cni-example
```

### 2. Install ArgoCD with Helm (Offline Mode)
```bash
# Create namespace and install ArgoCD
kubectl create namespace argocd
helm repo add argo https://argoproj.github.io/argo-helm
helm install argocd ./sources/argo-cd.tgz --namespace argocd --set server.extraArgs[0]=--insecure
```


### 2.1 Install ArgoCD with Helm (Online Alternative)
```bash
# Create namespace and install ArgoCD
kubectl create namespace argocd
helm repo add argo https://argoproj.github.io/argo-helm
helm install argocd argo/argo-cd --namespace argocd --set server.extraArgs[0]=--insecure

# Bootstrap GitOps
kubectl apply -f charts/bootstrap.yaml
```

### 2. Access ArgoCD

```bash
kubectl port-forward -n argocd svc/argocd-server 8080:80
```

Open: http://localhost:8080
- Username: `admin`
- Password: `kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d`

### 3. Access Applications

- **Webapp**: http://localhost:30080
- **Uptime Kuma**: http://localhost:30001

## GitOps Demo: Change Color

Edit `charts/webapp-color/values.yaml`:

```yaml
appColor: "red"  # Options: red, green, blue, darkblue, pink
```

Commit and push:

```bash
git add charts/webapp-color/values.yaml
git commit -m "Change color to red"
git push
```

Watch ArgoCD sync and see the color change at http://localhost:30080

## GitOps Demo: Rollback

```bash
git revert HEAD
git push
```

ArgoCD automatically rolls back the change!

---

## Uptime Kuma Monitoring

### Setup

```bash
helm upgrade --install uptime-kuma charts/uptime-kuma --namespace uptime-kuma --create-namespace
```

Open http://localhost:30001 and configure monitors.

### Backup Configuration

```bash
# Trigger backup
kubectl create job -n uptime-kuma backup-now --from=cronjob/uptime-kuma-backup

# Save to Git
kubectl get configmap uptime-kuma-db-backup -n uptime-kuma -o yaml > charts/uptime-kuma/templates/restore-db-backup.yaml
git add charts/uptime-kuma/templates/restore-db-backup.yaml
git commit -m "Backup Uptime Kuma config"
git push
```

### Test Restore

```bash
# Delete everything
helm uninstall uptime-kuma -n uptime-kuma
kubectl delete pvc uptime-kuma uptime-kuma-backup -n uptime-kuma

# Redeploy - config auto-restores from Git!
helm upgrade --install uptime-kuma charts/uptime-kuma --namespace uptime-kuma --create-namespace
```

Your monitors are back! ✅

---

## How It Works

1. **ArgoCD** watches Git for changes
2. **Helm** manages Kubernetes deployments
3. **GitOps**: All config in Git, automatic sync
4. **Backup/Restore**: Uptime Kuma config stored as ConfigMap in Git

## Clean Up

Docker Desktop → Settings → Kubernetes → Reset Cluster