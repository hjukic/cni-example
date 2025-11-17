# Monitoring webapp-color with Uptime Kuma

Automatic version tagging for Uptime Kuma monitors.

## Setup Monitor

1. Open Uptime Kuma at `http://<node-ip>:30001`
2. Add HTTP(s) monitor:
   - **Name**: `webapp-color`
   - **URL**: `http://webapp-color.webapp-color.svc.cluster.local`

## Automatic Version Tagging

A CronJob automatically syncs versions from `/static/version.txt` to Uptime Kuma tags (e.g., `version-1.0.0`).

### Quick Setup

**1. Create secret with credentials:**

```bash
kubectl create secret generic uptime-kuma-credentials \
  --from-literal=username='YOUR_UPTIME_KUMA_USERNAME' \
  --from-literal=password='YOUR_UPTIME_KUMA_PASSWORD' \
  -n version-sync
```

**2. Configure `charts/version-sync/values.yaml`:**

```yaml
namespace: version-sync
schedule: "*/5 * * * *"

uptimeKuma:
  url: "http://uptime-kuma.uptime-kuma.svc.cluster.local:3001"
  usernameSecret:
    name: "uptime-kuma-credentials"
    key: "username"
  passwordSecret:
    name: "uptime-kuma-credentials"
    key: "password"

services:
  - monitorName: "webapp-color"
    versionEndpoint: "http://webapp-color.webapp-color.svc.cluster.local/static/version.txt"
```

**3. Deploy:**

```bash
kubectl create namespace version-sync
helm install version-sync charts/version-sync -n version-sync
```

**4. Verify:**

```bash
kubectl logs -n version-sync -l app=version-sync --tail=20
```

Expected: `✓ Successfully updated monitor 'webapp-color' with tag 'version-1.0.0'`

## Configuration

Add more services to monitor:

```yaml
services:
  - monitorName: "webapp-color"
    versionEndpoint: "http://webapp-color.webapp-color.svc.cluster.local/static/version.txt"
  - monitorName: "another-service"
    versionEndpoint: "http://another-service.default.svc.cluster.local/version.txt"
    tagPrefix: "ver"  # Optional, creates tags like "ver-2.0.0"
```

## Troubleshooting

- **Auth fails**: Check credentials in secret
- **Monitor not found**: Monitor name must match exactly
- **View logs**: `kubectl logs -n version-sync -l app=version-sync`

## How It Works

1. Fetches version from service endpoint every 5 minutes
2. Creates/updates version tag in Uptime Kuma
3. Removes old version tags automatically
4. Uses official [uptime-kuma-api](https://github.com/lucasheld/uptime-kuma-api) library

## Update Version

Edit `charts/webapp-color/Chart.yaml`:

```yaml
version: 1.0.1  # Update this
```

Deploy via ArgoCD or `helm upgrade`. Tags update automatically on next CronJob run.
