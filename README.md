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

Uptime Kuma is deployed automatically by ArgoCD. Open http://localhost:30001 to access it.

### Kuma Versionizer API Credentials

The `kuma-versionizer` application needs credentials to authenticate with Uptime Kuma's API. Create the secret in the kuma-versionizer namespace:

```bash
kubectl create secret generic uptime-kuma-credentials \
  --from-literal=username=admin \
  --from-literal=password=okradmin123 \
  --namespace kuma-versionizer
```

**Credentials:**
- Username: `admin`
- Password: `okradmin123`

**Note:** These are the same credentials you'll use to login to Uptime Kuma at http://localhost:30001 on first setup.

### Backup & Restore (Simple Manual Commands)

#### Create a Backup

```bash
# Get the pod name
kubectl get pods -n uptime-kuma

# Copy the database file from the pod to your local machine
kubectl cp uptime-kuma/<POD_NAME>:/app/data/kuma.db ./kuma-backup.db -n uptime-kuma

# Example:
# kubectl cp uptime-kuma/uptime-kuma-6f8b9d7c4d-abc12:/app/data/kuma.db ./kuma-backup.db -n uptime-kuma
```

Your backup is now saved locally as `kuma-backup.db` ✅

#### Restore from Backup

```bash
# Get the pod name
kubectl get pods -n uptime-kuma

# Copy your backup file to the pod (overwrites current database)
kubectl cp ./kuma-backup.db uptime-kuma/<POD_NAME>:/app/data/kuma.db -n uptime-kuma

# Restart the pod to load the restored database
kubectl delete pod -l app.kubernetes.io/name=uptime-kuma -n uptime-kuma

# Example:
# kubectl cp ./kuma-backup.db uptime-kuma/uptime-kuma-6f8b9d7c4d-abc12:/app/data/kuma.db -n uptime-kuma
# kubectl delete pod -l app.kubernetes.io/name=uptime-kuma -n uptime-kuma
```

Your monitors are restored! ✅

---

## How It Works

1. **ArgoCD** watches Git for changes
2. **Helm** manages Kubernetes deployments
3. **GitOps**: All config in Git, automatic sync
4. **Backup/Restore**: Uptime Kuma config stored as ConfigMap in Git

## Clean Up

Docker Desktop → Settings → Kubernetes → Reset Cluster