# Monitoring webapp-color with Uptime Kuma

This guide explains how to monitor the `webapp-color` application and its version endpoint using Uptime Kuma.

## Overview

The `webapp-color` deployment is configured with:
- **Namespace**: `webapp-color`
- **Service Type**: NodePort (port 80, nodePort 30080)
- **Version ConfigMap**: Mounted at `/opt/static` (served at `/static/version.txt` by the application)

Both `webapp-color` and `uptime-kuma` are deployed in the same Kubernetes cluster, allowing cluster-internal DNS communication.

## Quick Start

### Monitoring the Main WebApp Service

To monitor the main webapp-color service availability:

1. Open Uptime Kuma UI at `http://<node-ip>:30001`
2. Add a new monitor:
   - **Name**: webapp-color
   - **Type**: HTTP(s)
   - **URL**: `http://webapp-color.webapp-color.svc.cluster.local`
   - **Heartbeat Interval**: 60 seconds
   - **Retries**: 3
   - **Accepted Status Codes**: 200-299

**Alternative addresses:**
- **Cluster-internal (with port)**: `http://webapp-color.webapp-color.svc.cluster.local:80`
- **Via NodePort (external)**: `http://<node-ip>:30080`

### Monitoring the Version Endpoint

The version endpoint reads from a ConfigMap that stores the chart version. To monitor version changes:

1. Add a new monitor in Uptime Kuma:
   - **Name**: webapp-color-version
   - **Type**: HTTP(s) - Keyword
   - **URL**: `http://webapp-color.webapp-color.svc.cluster.local/static/version.txt`
   - **Expected Keyword**: Your current version (e.g., "1.0.0")
   - **Heartbeat Interval**: 60 seconds
   - **Retries**: 3
   - **Accepted Status Codes**: 200-299

## How It Works

1. **Version Source**: The version comes from `Chart.Version` in `charts/webapp-color/Chart.yaml` (stored in ConfigMap `webapp-color-version`)
2. **ConfigMap**: A ConfigMap stores the version value as `version.txt`
3. **Volume Mount**: The ConfigMap is mounted at `/opt/static` in the container, and the application serves it at `/static/version.txt`
4. **Service**: The service exposes the application on port 80 (targeting container port 8080)
5. **Automatic Updates**: When you update the chart version and deploy, the ConfigMap and version endpoint update automatically

## Updating the Version

To update the version, edit `charts/webapp-color/Chart.yaml`:

```yaml
apiVersion: v2
name: webapp-color
description: A Helm chart for webapp-color
version: 1.0.1  # Change this to update version
```

After deploying (via ArgoCD or manual helm upgrade), the ConfigMap and version endpoint will automatically reflect the new value.

## Dynamic Version Tagging

You can automatically sync the version from `version.txt` to Uptime Kuma as a tag, so the monitor is always labeled with the current version.

### How It Works

A Kubernetes CronJob periodically:
1. Fetches the version from `http://webapp-color.webapp-color.svc.cluster.local/static/version.txt`
2. Uses the Uptime Kuma API to update the monitor with a tag like `version-1.0.0`
3. Removes old version tags and adds the new one

### Setup Instructions

#### 1. Get Uptime Kuma API Token

1. Log into Uptime Kuma UI at `http://<node-ip>:30001`
2. Go to **Settings** → **API Tokens**
3. Click **Add API Token**
4. Give it a name (e.g., "version-sync")
5. Copy the generated token (you'll need it in the next step)

#### 2. Create the API Token Secret

Create a Kubernetes Secret with your Uptime Kuma API token:

```bash
kubectl create secret generic uptime-kuma-api-token \
  --from-literal=api-token='YOUR_API_TOKEN_HERE' \
  -n <namespace>
```

#### 3. Configure and Deploy

Update `charts/version-sync/values.yaml` with your configuration:

```yaml
namespace: default  # or your preferred namespace

# CronJob schedule (runs every 5 minutes)
schedule: "*/5 * * * *"

# Uses standard Python image - no custom image needed!
image:
  repository: python
  tag: "3.11-slim"
  pullPolicy: IfNotPresent

uptimeKuma:
  url: "http://uptime-kuma.uptime-kuma.svc.cluster.local:3001"
  secretName: "uptime-kuma-api-token"

# Services to monitor
services:
  - monitorName: "webapp-color"
    versionEndpoint: "http://webapp-color.webapp-color.svc.cluster.local/static/version.txt"
    tagPrefix: "version"  # Optional, defaults to "version"
  # Add more services:
  # - monitorName: "api-service"
  #   versionEndpoint: "http://api-service.api.svc.cluster.local/version.txt"
  #   tagPrefix: "version"
```

Deploy using Helm:

```bash
helm install version-sync charts/version-sync -n <namespace>
```

Or add it to your ArgoCD applications chart for GitOps deployment.

#### 4. Verify It's Working

Check the CronJob logs:

```bash
# List recent jobs
kubectl get jobs -n <namespace> | grep uptime-kuma-version-sync

# View logs from the latest job
kubectl logs -n <namespace> -l job-name --tail=50
```

You should see output like:

```
🚀 Starting version sync for 3 service(s)
   Uptime Kuma URL: http://uptime-kuma.uptime-kuma.svc.cluster.local:3001

📦 Processing service: webapp-color
   Endpoint: http://webapp-color.webapp-color.svc.cluster.local/static/version.txt
   ✓ Fetched version: 1.0.0
   ✓ Found monitor ID: 1
   ✓ Successfully updated monitor 'webapp-color' with tag 'version-1.0.0'

📦 Processing service: api-service
   Endpoint: http://api-service.api.svc.cluster.local/version.txt
   ✓ Fetched version: 2.1.3
   ✓ Found monitor ID: 2
   ✓ Successfully updated monitor 'api-service' with tag 'version-2.1.3'

📦 Processing service: frontend-app
   Endpoint: http://frontend-app.frontend.svc.cluster.local/api/version
   ✓ Fetched version: 3.0.0
   ✓ Found monitor ID: 3
   ✓ Successfully updated monitor 'frontend-app' with tag 'version-3.0.0'

📊 Summary:
   ✓ Successful: 3
   ✗ Failed: 0

✓ All version tags updated successfully
```

In Uptime Kuma UI, you should now see the monitor tagged with `version-1.0.0` (or your current version).


### Configuration Options

The CronJob can be configured via `charts/version-sync/values.yaml`:

**Global settings:**
- **namespace**: Kubernetes namespace for the CronJob
- **schedule**: Cron schedule (e.g., `"*/5 * * * *"` for every 5 minutes)
- **image.repository/tag**: Python image to use (default: `python:3.11-slim`)
- **uptimeKuma.url**: Uptime Kuma API URL
- **uptimeKuma.secretName**: Name of the Secret containing the API token
- **verifySSL**: Set to `"true"` if using HTTPS (default: `"false"`)
- **resources**: CPU/memory limits for the job

**Per-service settings (in `services` list):**
- **monitorName**: Name of the monitor in Uptime Kuma (required)
- **versionEndpoint**: URL to fetch version from (required)
- **tagPrefix**: Prefix for version tags (optional, defaults to "version")