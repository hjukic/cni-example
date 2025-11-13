# Version Monitoring with Uptime Kuma

This guide explains how to automatically monitor and display application versions in Uptime Kuma.

## Overview

The `webapp-color` deployment automatically exposes a version endpoint that reads the version from `charts/webapp-color/values.yaml`. When you update the `image.tag` in values.yaml, the version endpoint automatically reflects the new version.

## Quick Start

### Access the Version Endpoint

The version is automatically available at:
- **Cluster-internal**: `http://webapp-color.default.svc.cluster.local:8081/version.txt`
- **Via NodePort**: Check the service for the assigned port, then access `http://<node-ip>:<port>/version.txt`

### Configure Uptime Kuma Monitor

1. Open Uptime Kuma UI at `http://<node-ip>:30001`
2. Add a new monitor:
   - **Type**: HTTP(s) - Keyword
   - **URL**: `http://webapp-color.default.svc.cluster.local:8081/version.txt`
   - **Expected Keyword**: Your current version (e.g., "latest", "v1.0.0")
   - **Heartbeat Interval**: 60 seconds
   - **Retries**: 3
   - **Accepted Status Codes**: 200-299

The monitor will automatically detect when the version changes!

## How It Works

1. **Version Source**: The version comes from `image.tag` in `charts/webapp-color/values.yaml`
2. **ConfigMap**: A ConfigMap stores the version value
3. **Sidecar Container**: A lightweight busybox HTTP server serves the version file
4. **Automatic Updates**: When you change `image.tag` and deploy, the version endpoint updates automatically

## Updating the Version

Simply edit `charts/webapp-color/values.yaml`:

```yaml
image:
  repository: kodekloud/webapp-color
  tag: "v1.0.1"  # Change this to update version
  pullPolicy: IfNotPresent
```

After deploying (via ArgoCD or manual helm upgrade), the version endpoint will automatically reflect the new value.

## Monitor Configuration Reference

### WebApp Version Monitor
- **Name**: webapp-color-version
- **Type**: HTTP(s) - Keyword
- **URL**: `http://webapp-color.default.svc.cluster.local:8081/version.txt`
- **Heartbeat Interval**: 60 seconds
- **Retries**: 3
- **Accepted Status Codes**: 200-299

### WebApp Monitor
- **Name**: webapp-color
- **Type**: HTTP(s)
- **URL**: `http://webapp-color.default.svc.cluster.local`
- **Heartbeat Interval**: 60 seconds
- **Retries**: 3
- **Accepted Status Codes**: 200-299