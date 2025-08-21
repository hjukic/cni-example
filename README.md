# 🐳 GitOps Kubernetes Project with ArgoCD and Helm

This project is a very simple, presentation-friendly GitOps demo that uses ArgoCD and Helm to deploy an example app (nginx) to a local Kubernetes cluster (Docker Desktop Kubernetes).

## 📁 Project Structure

```
cni-example/
├── charts/
│   ├── applications/              # ArgoCD Application definitions
│   │   ├── templates/            # Application CRD templates
│   │   │   └── nginx.yaml        # Nginx application definition
│   │   ├── Chart.yaml            # Applications chart
│   │   └── values.yaml           # Global application settings
│   ├── nginx/                    # Nginx application chart
│   │   ├── Chart.yaml            # Points to official nginx chart
│   │   └── values.yaml           # Custom values for nginx
│   └── bootstrap.yaml            # Start everything with ONE file
├── scripts/                       # Utility scripts
└── README.md                      # This file
```

## ✅ Prerequisites

- Docker Desktop with Kubernetes enabled
- kubectl installed and in PATH
- Helm 

## 🛠️ Installing Required Tools

### kubectl (Kubernetes command line tool)

**Windows:**
```bash
winget install Kubernetes.kubectl
```

**Linux/WSL:**
```bash
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl
sudo mv kubectl /usr/local/bin/
```

### Helm (Kubernetes package manager)

**Windows:**
```bash
winget install Helm.Helm
```

**Linux/WSL:**
```bash
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

### Verify Installation
```bash
kubectl version --client
helm version
```

## ☸️ Configuring Kubernetes in Docker-Desktop

1. **Open Docker Desktop**
2. **Go to Settings** (gear icon)
3. **Click on "Kubernetes"** in the left sidebar
4. **Check "Enable Kubernetes"**
5. **Click "Apply & Restart"**
6. **Wait for Kubernetes to start** (you'll see a green status)

**Note:** Docker Desktop uses by default **kubeadm** to set up the Kubernetes cluster, which provides a fully functional single-node cluster perfect for development and demos. Alternatively **kind** can be used in case of wanting to try multi node cluster deployments.

### Verify Kubernetes is Running:
```bash
kubectl cluster-info
kubectl get nodes
```

## 🚀 Quick Start

### Install ArgoCD with Helm
```bash
# Create namespace and install ArgoCD
kubectl create namespace argocd
helm repo add argo https://argoproj.github.io/argo-helm
helm install argocd argo/argo-cd --namespace argocd --set server.extraArgs[0]=--insecure
```

### Wait for ArgoCD to be ready
```bash
kubectl wait --for=condition=Available deployment/argocd-server -n argocd --timeout=300s
```

### Bootstrap the GitOps platform
```bash
kubectl apply -f charts/bootstrap.yaml
```
This creates an ArgoCD Application that manages all other applications through the `charts/applications` chart.

### Access ArgoCD UI
```bash
kubectl port-forward -n argocd svc/argocd-server 8080:80
```
Open: http://localhost:8080

- Username: `admin`
- Password (initial, if not set by Helm):
```bash
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d; echo
```

### Access Nginx Deployment

```bash
kubectl port-forward -n nginx svc/nginx 8081:80
```

## 🔎 Verify Deployment
```bash
# See the ArgoCD Applications
kubectl get applications -n argocd

# See the nginx pods in the nginx namespace (created by ArgoCD)
kubectl get pods -n nginx
```

## 🧹 Clean Up (manual)
```bash
# Remove the applications Application first
kubectl delete application applications -n argocd

# Remove ArgoCD
kubectl delete namespace argocd
```

## 🧠 What This Demonstrates

- **GitOps**: Kubernetes state defined in Git and applied by ArgoCD
- **App of Apps**: A single ArgoCD Application manages all other applications
- **Official Charts**: Uses official Helm charts with custom values
- **Clean Separation**: Application definitions separate from chart customizations

## ➕ Adding New Applications

To add a new application (e.g., traefik):

1. **Create Application Definition** in `charts/applications/templates/traefik.yaml`:
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  namespace: argocd
  name: traefik
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: infrastructure
  source:
    repoURL: {{ .Values.global.repoURL }}
    path: charts/traefik
    targetRevision: {{ .Values.global.targetRevision }}
  destination:
    server: https://kubernetes.default.svc
    namespace: traefik
  syncPolicy:
    automated:
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
```

2. **Create Chart Folder** `charts/traefik/` with:
   - `Chart.yaml` pointing to official traefik chart
   - `values.yaml` with your customizations

3. **Add to Applications Values** in `charts/applications/values.yaml`:
```yaml
applications:
  traefik:
    enabled: true
    project: infrastructure
    namespace: traefik
```

4. **Commit and push** - ArgoCD will automatically deploy the new application!

## 🎯 How It Works

1. **Bootstrap** deploys the `applications` chart once
2. **Applications chart** creates ArgoCD Applications for each app
3. **Each app folder** points to official Helm charts with custom values
4. **ArgoCD automatically** deploys everything from Git commits
5. **No manual deployment** needed after bootstrap