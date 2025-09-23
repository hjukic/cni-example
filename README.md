# 🐳 GitOps Kubernetes Project with ArgoCD and Helm

This project is a very simple, presentation-friendly GitOps demo that uses ArgoCD and Helm to deploy a color-changing webapp to a local Kubernetes cluster (Docker Desktop Kubernetes). Perfect for demonstrating GitOps workflows, rollbacks, and visual configuration changes!

## 📁 Project Structure

```
cni-example/
├── charts/
│   ├── applications/              # ArgoCD Application definitions
│   │   ├── templates/            # Application CRD templates
│   │   │   └── webapp-color.yaml # Webapp-color application definition
│   │   ├── Chart.yaml            # Applications chart
│   │   └── values.yaml           # Global application settings
│   ├── webapp-color/             # Webapp-color custom chart
│   │   ├── Chart.yaml            # Custom chart definition
│   │   ├── templates/            # Kubernetes manifests
│   │   │   ├── deployment.yaml   # Deployment template
│   │   │   └── service.yaml      # Service template
│   │   └── values.yaml           # Custom values for webapp-color
│   └── bootstrap.yaml            # Start everything with ONE file
└── README.md                      # Readme file
```

## ✅ Prerequisites

Before getting started, ensure you have the following tools installed:

- 🐳 **Docker Desktop** with Kubernetes enabled
- 📦 **WinGet Package Manager** (Windows package manager)
- ☸️ **kubectl** installed and available in your PATH
- 🎯 **Helm** (Kubernetes package manager) 

## 🛠️ Installing Required Tools

### WinGet Package manager

Open the Powershell as Admin and run following command to download the WinGet Package to the ``C:\dev`` Folder

```powershell
Invoke-WebRequest -Uri “https://github.com/microsoft/winget-cli/releases/download/v1.11.430/Microsoft.DesktopAppInstaller_8wekyb3d8bbwe.msixbundle” -OutFile “C:\dev\WinGet.msixbundle”
```

Install the WinGet Package

```powershell
Add-AppxPackage “C:\dev\WinGet.msixbundle”
```

### kubectl (Kubernetes command line tool)

**Windows:**
```powerhsell
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
```powerhsell
winget install Helm.Helm
```

**Linux/WSL:**
```bash
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

### Verify Installation
```powerhsell
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
kubectl get nodes
```

## 🚀 Quick Start

### 1. Clone the Repository
First, make sure you have the repository checked out locally:

```bash
git clone <repository-url>
cd cni-example
```

### 2. Install ArgoCD with Helm
```bash
# Create namespace and install ArgoCD
kubectl create namespace argocd
helm repo add argo https://argoproj.github.io/argo-helm
helm install argocd argo/argo-cd --namespace argocd --set server.extraArgs[0]=--insecure
```

### 3. Bootstrap the GitOps platform
```bash
kubectl apply -f charts/bootstrap.yaml
```
This creates an ArgoCD Application that manages all other applications through the `charts/applications` chart.

### 4. Access ArgoCD UI
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
```

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

## 🔄 GitOps Demo: Rollback with Git Revert

Demonstrating GitOps rollback capabilities:

### 1. **Revert the Last Color Change**
```bash
# Revert the most recent commit (color change)
git revert HEAD
```

### 2. **Push the Revert**
```bash
git push
```

### 3. **Watch Automatic Rollback**
- ArgoCD detects the revert commit
- Automatically syncs the rollback
- Visit the webapp: http://localhost:30080
- See the color revert to the previous state!

### 4. **Alternative: Revert to Specific Commit**
```bash
# First, check recent commits
git log --oneline -5

# Then revert to a specific commit
git revert <commit-hash>
git push
```

## 🎯 How It Works

1. **Bootstrap** deploys the `applications` chart once
2. **Applications chart** creates ArgoCD Applications for each app
3. **Custom charts**: Local Kubernetes templates with configurable values
4. **ArgoCD automatically** deploys everything from Git commits
5. **Visual feedback** through webapp color changes makes GitOps concepts tangible
6. **No manual deployment** needed after bootstrap - pure GitOps!

## 🧹 Clean Up (manual)
```bash
"Reset Cluster" in Docker-Desktop Settings
```
