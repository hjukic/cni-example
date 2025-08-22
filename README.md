# 🐳 GitOps Kubernetes Project with ArgoCD and Helm

This project is a very simple, presentation-friendly GitOps demo that uses ArgoCD and Helm to deploy a color-changing webapp to a local Kubernetes cluster (Docker Desktop Kubernetes). Perfect for demonstrating GitOps workflows, rollbacks, and visual configuration changes!

## 📁 Project Structure

```
cni-example/
├── charts/
│   ├── applications/              # ArgoCD Application definitions
│   │   ├── templates/            # Application CRD templates
│   │   │   ├── webapp-color.yaml # Webapp-color application definition
│   │   │   └── monitoring.yaml   # Monitoring stack definition
│   │   ├── Chart.yaml            # Applications chart
│   │   └── values.yaml           # Global application settings
│   ├── webapp-color/             # Webapp-color custom chart
│   │   ├── Chart.yaml            # Custom chart definition
│   │   ├── templates/            # Kubernetes manifests
│   │   │   ├── deployment.yaml   # Deployment template
│   │   │   ├── service.yaml      # Service template
│   │   │   └── servicemonitor.yaml # Prometheus monitoring
│   │   └── values.yaml           # Custom values for webapp-color
│   ├── monitoring/               # Monitoring stack using official chart
│   │   ├── Chart.yaml            # Points to kube-prometheus-stack
│   │   └── values.yaml           # Monitoring configuration
│   └── bootstrap.yaml            # Start everything with ONE file
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

### Access Applications

**Webapp-Color Application:**
```bash
# Direct NodePort access
http://localhost:30080

# Or port-forward (alternative)
kubectl port-forward -n webapp-color svc/webapp-color 8081:80
# Then open: http://localhost:8081
```

**Monitoring Stack:**
```bash
# Grafana Dashboard (username: admin, password: admin123)
http://localhost:30000

# Prometheus UI
http://localhost:30001

# AlertManager UI
kubectl port-forward -n monitoring svc/monitoring-kube-prometheus-st-alertmanager 9093:9093
# Then open: http://localhost:9093
```

## 🔎 Verify Deployment
```bash
# See the ArgoCD Applications
kubectl get applications -n argocd

# See the webapp-color pods
kubectl get pods -n webapp-color

# See the monitoring stack
kubectl get pods -n monitoring

# Check services
kubectl get svc -n webapp-color
kubectl get svc -n monitoring
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
- **Consistent Structure**: Both apps follow the same chart organization pattern
- **Mixed Chart Types**: Custom charts (webapp-color) + Official charts (monitoring)  
- **Visual Configuration Changes**: Change webapp colors by modifying values.yaml
- **Rollback Capabilities**: Demonstrate ArgoCD rollback vs Git revert workflows
- **Complete Monitoring**: Prometheus, Grafana, and AlertManager via GitOps
- **Clean Separation**: Application definitions separate from chart customizations

## 🎨 GitOps Demo: Color Changes

This project is perfect for demonstrating GitOps workflows with visual feedback:

### 1. **Change Application Color**
Edit `charts/webapp-color/values.yaml`:
```yaml
# Change this line to any supported color
appColor: "red"  # Options: red, green, blue, darkblue, pink
```

### 2. **Commit and Push**
```bash
git add charts/webapp-color/values.yaml
git commit -m "Change webapp color to red"
git push
```

### 3. **Watch ArgoCD Sync**
- Open ArgoCD UI: http://localhost:8080
- Watch the webapp-color application sync automatically
- Visit the webapp: http://localhost:30080
- See the color change immediately!

### 4. **Monitor the Changes**
- Open Grafana: http://localhost:30000 (admin/admin123)
- Watch metrics during deployment
- See HTTP request patterns change
- Monitor resource usage during sync

## 🔄 Rollback Demo

### Setup for Rollback Demo
To demonstrate rollbacks without auto-sync interference, the project is configured with `selfHeal` disabled.

### Demo Workflow
1. **Deploy initial color** (e.g., green)
2. **Change to different color** via Git (e.g., blue)
3. **Use ArgoCD UI to rollback** to previous version
4. **Show the difference**: Manual rollback vs Git-driven changes

### Enable/Disable Auto-Sync
Edit `charts/applications/templates/webapp-color.yaml`:
```yaml
# Comment out for rollback demos
# automated:
#   selfHeal: true

# Uncomment for full GitOps
automated:
  selfHeal: true
```

## 📊 Monitoring Demo

### Explore Grafana Dashboards
1. **Open Grafana**: http://localhost:30000 (admin/admin123)
2. **Browse dashboards**: 
   - Kubernetes / Compute Resources / Cluster
   - Kubernetes / Compute Resources / Namespace (Pods)
   - Node Exporter / Nodes

### Monitor Your Webapp
1. **Generate traffic**: Visit http://localhost:30080 and refresh multiple times
2. **Watch metrics**: See HTTP requests appear in Prometheus/Grafana
3. **Scale the app**: `kubectl scale deployment webapp-color -n webapp-color --replicas=3`
4. **Observe changes**: Watch pod metrics update in real-time

### Prometheus Queries
Open Prometheus (http://localhost:30001) and try these queries:
```promql
# CPU usage of webapp-color pods
rate(container_cpu_usage_seconds_total{namespace="webapp-color"}[5m])

# Memory usage
container_memory_usage_bytes{namespace="webapp-color"}

# HTTP requests (if your app exposes metrics)
http_requests_total{job="webapp-color"}
```

## ➕ Adding New Applications

To add a new application (e.g., another webapp):

1. **Create Application Definition** in `charts/applications/templates/my-app.yaml`:
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  namespace: argocd
  name: my-app
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: {{ .Values.global.repoURL }}
    path: charts/my-app
    targetRevision: {{ .Values.global.targetRevision }}
  destination:
    server: https://kubernetes.default.svc
    namespace: my-app
  syncPolicy:
    automated:
     selfHeal: true  # Comment out for demo flexibility
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
```

2. **Create Chart Folder** `charts/my-app/` with:
   - `Chart.yaml` - Chart metadata
   - `values.yaml` - Configuration values
   - `templates/` - Kubernetes manifests (deployment.yaml, service.yaml)

3. **Commit and push** - ArgoCD will automatically deploy the new application!

## 🎯 How It Works

1. **Bootstrap** deploys the `applications` chart once
2. **Applications chart** creates ArgoCD Applications for each app
3. **Consistent structure** with two chart types:
   - **Custom charts** (webapp-color): Local Kubernetes templates
   - **Official charts** (monitoring): Dependencies on external Helm charts with custom values
4. **ArgoCD automatically** deploys everything from Git commits
5. **Visual feedback** through webapp color changes makes GitOps concepts tangible
6. **No manual deployment** needed after bootstrap - pure GitOps!