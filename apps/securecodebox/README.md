# SecureCodeBox Nmap Scanner

This directory contains the ArgoCD applications for deploying SecureCodeBox with the Nmap network scanner for Kubernetes-native security scanning.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                 SecureCodeBox System                     │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌─────────────────┐    Creates    ┌─────────────────┐  │
│  │    Operator     │──────────────▶│   Scanner Job   │  │
│  │  (controller)   │               │     (nmap)      │  │
│  └────────┬────────┘               └────────┬────────┘  │
│           │                                  │           │
│           │ Watches                          │ Results   │
│           ▼                                  ▼           │
│  ┌─────────────────┐               ┌─────────────────┐  │
│  │   Scan CRD      │               │   Parser Job    │  │
│  │  (user creates) │               │ (processes XML) │  │
│  └─────────────────┘               └────────┬────────┘  │
│                                              │           │
│                                              ▼           │
│                                    ┌─────────────────┐  │
│                                    │   Findings      │  │
│                                    │   (results)     │  │
│                                    └─────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## Components

| Component | Version | Purpose |
|-----------|---------|---------|
| SecureCodeBox Operator | 5.5.0 | Manages scan lifecycle, CRDs |
| Nmap Scanner | 5.5.0 | Network discovery and security auditing |
| Nmap Parser | 5.5.0 | Processes nmap XML output into findings |

## Resource Requirements

| Component | CPU Request | CPU Limit | Memory Request | Memory Limit |
|-----------|-------------|-----------|----------------|--------------|
| Operator | 100m | 200m | 128Mi | 256Mi |
| Scanner (per scan) | 100m | 500m | 128Mi | 512Mi |
| Parser (per scan) | 50m | 200m | 64Mi | 256Mi |

**Note:** Scanner and Parser are Jobs that run temporarily during scans, not persistent deployments.

## Installation

### Prerequisites

- Kubernetes cluster running
- ArgoCD installed and accessible
- kubectl configured

### Deploy via ArgoCD

```bash
# 1. Deploy the operator (required first)
kubectl apply -f operator-application.yaml

# Wait for operator to be ready
kubectl wait --for=condition=available deployment/securecodebox-controller-manager \
  -n securecodebox-system --timeout=300s

# 2. Deploy nmap scanner
kubectl apply -f nmap-application.yaml

# Verify scantype is registered
kubectl get scantypes -n securecodebox-system
```

### Verify Installation

```bash
# Check ArgoCD applications
kubectl get applications -n argocd | grep securecodebox

# Check pods
kubectl get pods -n securecodebox-system

# Check available scan types
kubectl get scantypes -n securecodebox-system
```

## Usage

> **Note:** Examples use `scanme.nmap.org` (a legitimate test target). Replace with your authorized target IP/hostname. Only scan systems you have permission to test.

### Running Scans

Create a Scan custom resource to trigger an nmap scan:

```yaml
apiVersion: execution.securecodebox.io/v1
kind: Scan
metadata:
  name: nmap-my-target
  namespace: securecodebox-system
spec:
  scanType: nmap
  parameters:
    - "-sV"           # Service version detection
    - "scanme.nmap.org"     # Target IP/hostname
```

Apply with:
```bash
kubectl apply -f - <<EOF
apiVersion: execution.securecodebox.io/v1
kind: Scan
metadata:
  name: nmap-test
  namespace: securecodebox-system
spec:
  scanType: nmap
  parameters:
    - "-sV"
    - "scanme.nmap.org"
EOF
```

### Common Nmap Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `-sn` | Ping scan (host discovery only) | `-sn 10.83.3.0/24` |
| `-sV` | Service version detection | `-sV scanme.nmap.org` |
| `-sS` | TCP SYN scan (stealth) | `-sS scanme.nmap.org` |
| `-p` | Specific ports | `-p 22,80,443` |
| `-F` | Fast scan (top 100 ports) | `-F scanme.nmap.org` |
| `-T4` | Aggressive timing | `-T4 scanme.nmap.org` |
| `-A` | Aggressive (OS, version, scripts) | `-A scanme.nmap.org` |
| `-O` | OS detection (requires privileges) | `-O scanme.nmap.org` |

### Example Scans

#### Quick Host Discovery
```yaml
apiVersion: execution.securecodebox.io/v1
kind: Scan
metadata:
  name: network-discovery
  namespace: securecodebox-system
spec:
  scanType: nmap
  parameters:
    - "-sn"
    - "10.83.3.0/24"
```

#### Service Version Scan
```yaml
apiVersion: execution.securecodebox.io/v1
kind: Scan
metadata:
  name: service-scan
  namespace: securecodebox-system
spec:
  scanType: nmap
  parameters:
    - "-sV"
    - "-T4"
    - "-p"
    - "22,80,443,8080,8443"
    - "scanme.nmap.org"
```

#### Scheduled Daily Scan
```yaml
apiVersion: execution.securecodebox.io/v1
kind: ScheduledScan
metadata:
  name: daily-network-scan
  namespace: securecodebox-system
spec:
  interval: 24h
  scanSpec:
    scanType: nmap
    parameters:
      - "-sV"
      - "-F"
      - "10.83.3.0/24"
```

### Checking Results

```bash
# List all scans
kubectl get scans -n securecodebox-system

# Watch scan progress
kubectl get scans -n securecodebox-system -w

# Get scan details
kubectl describe scan <scan-name> -n securecodebox-system

# List findings (results)
kubectl get findings -n securecodebox-system

# Get finding details
kubectl get findings -n securecodebox-system -o yaml
```

### Scan Lifecycle

1. **Pending** - Scan created, waiting for scheduler
2. **Scanning** - Nmap scanner job running
3. **ParseResult** - Parser processing nmap XML output
4. **Done** - Scan complete, findings available

## Troubleshooting

### Check Operator Logs
```bash
kubectl logs -n securecodebox-system -l app.kubernetes.io/name=securecodebox-operator -f
```

### Check Scan Pod Logs
```bash
# Find the scan pod
kubectl get pods -n securecodebox-system

# View logs
kubectl logs -n securecodebox-system <scan-pod-name>
```

### Scan Stuck in Pending
```bash
# Check if scantype exists
kubectl get scantypes -n securecodebox-system

# Check operator status
kubectl get pods -n securecodebox-system -l app.kubernetes.io/name=securecodebox-operator
```

### Delete Stuck Scan
```bash
kubectl delete scan <scan-name> -n securecodebox-system
```

## File Structure

```
securecodebox/
├── operator-application.yaml  # ArgoCD app for SecureCodeBox operator
├── nmap-application.yaml      # ArgoCD app for nmap scanner
├── example-scans.yaml         # Sample scan configurations
├── deploy-securecodebox.sh    # Deployment script
└── README.md                  # This file
```

## Security Considerations

- Nmap scans should only be run against systems you own or have permission to scan
- Some scan types (OS detection with `-O`) require elevated privileges
- Network scans can trigger IDS/IPS alerts
- Consider rate limiting with `-T2` or `-T3` for production networks

## Additional Scanners

SecureCodeBox supports many other scanners. To add more, create additional ArgoCD applications:

- `trivy` - Container vulnerability scanning
- `nikto` - Web server scanning
- `zap` - Web application security testing
- `nuclei` - Vulnerability detection

See: https://www.securecodebox.io/docs/scanners/

## References

- [SecureCodeBox Documentation](https://www.securecodebox.io/docs/)
- [Nmap Scanner Docs](https://www.securecodebox.io/docs/scanners/nmap)
- [Nmap Official](https://nmap.org/book/man.html)
