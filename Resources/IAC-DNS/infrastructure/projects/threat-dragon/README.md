# OWASP Threat Dragon

OWASP Threat Dragon is a threat modeling tool used to create threat model diagrams as part of a secure development lifecycle.

## Features

- Visual threat model diagram creation
- Support for STRIDE, LINDDUN, CIA, DIE, and PLOT4ai frameworks
- Automated threat generation with rule engine
- Export to PDF reports
- Repository integration (GitHub, GitLab, Bitbucket)

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Traefik                          │
│              (Ingress Controller)                   │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│              Threat Dragon                          │
│          threatdragon.knowledgeondemand.net         │
│                                                     │
│  ┌─────────────────────────────────────────────┐   │
│  │           Node.js Application               │   │
│  │              (Port 3000)                    │   │
│  │                                             │   │
│  │  - Threat Model Editor                      │   │
│  │  - Diagram Canvas                           │   │
│  │  - Report Generator                         │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

## Resource Requirements

| Component | CPU Request | CPU Limit | Memory Request | Memory Limit |
|-----------|-------------|-----------|----------------|--------------|
| Threat Dragon | 100m | 500m | 128Mi | 512Mi |

## Installation

### Quick Deploy

```bash
./deploy-threat-dragon.sh
```

### Manual Deploy

```bash
# 1. Create namespace
kubectl apply -f namespace.yaml

# 2. Apply secrets (update values first!)
kubectl apply -f secrets.yaml

# 3. Deploy via ArgoCD
kubectl apply -f application.yaml

# 4. Wait for deployment
kubectl wait --for=condition=available deployment/threat-dragon \
  -n threat-dragon --timeout=300s
```

### Verify Deployment

```bash
kubectl get pods -n threat-dragon
kubectl get svc -n threat-dragon
kubectl get ingressroute -n threat-dragon
```

## Configuration

### Secrets (IMPORTANT!)

Before production use, generate new encryption keys:

```bash
# Generate random keys
openssl rand -hex 16  # Run 3 times for each key

# Or use Python
python -c "import secrets; print(secrets.token_hex(16))"
```

Update `secrets.yaml`:
```yaml
stringData:
  encryption-keys: "YOUR_NEW_KEY_HERE"
  jwt-signing-key: "YOUR_NEW_KEY_HERE"
  jwt-refresh-signing-key: "YOUR_NEW_KEY_HERE"
```

Apply updated secrets:
```bash
kubectl apply -f secrets.yaml
kubectl rollout restart deployment/threat-dragon -n threat-dragon
```

### Repository Integration (Optional)

To enable GitHub/GitLab/Bitbucket integration, add these environment variables to the deployment:

**GitHub:**
```yaml
env:
- name: GITHUB_CLIENT_ID
  value: "your-github-oauth-app-client-id"
- name: GITHUB_CLIENT_SECRET
  valueFrom:
    secretKeyRef:
      name: threat-dragon-secrets
      key: github-client-secret
```

**GitLab:**
```yaml
env:
- name: GITLAB_CLIENT_ID
  value: "your-gitlab-app-id"
- name: GITLAB_CLIENT_SECRET
  valueFrom:
    secretKeyRef:
      name: threat-dragon-secrets
      key: gitlab-client-secret
```

## Access

| URL | Credentials |
|-----|-------------|
| https://threatdragon.knowledgeondemand.net | admin / admin (Traefik basic auth) |

### DNS Configuration

Add a DNS record pointing to your Traefik LoadBalancer IP:

```
threatdragon.knowledgeondemand.net -> <TRAEFIK_LB_IP>
```

Get the LoadBalancer IP:
```bash
kubectl get svc traefik -n traefik -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
```

## Usage

### Creating a Threat Model

1. Access the UI at https://threatdragon.knowledgeondemand.net
2. Click "Create New Threat Model"
3. Enter model details (title, description, owner)
4. Add diagrams using the visual editor
5. Add components (processes, data stores, actors, data flows)
6. Generate threats using the built-in rules engine
7. Document mitigations for identified threats

### Supported Threat Frameworks

- **STRIDE** - Spoofing, Tampering, Repudiation, Information Disclosure, Denial of Service, Elevation of Privilege
- **LINDDUN** - Linkability, Identifiability, Non-repudiation, Detectability, Disclosure, Unawareness, Non-compliance
- **CIA** - Confidentiality, Integrity, Availability
- **DIE** - Distributed, Immutable, Ephemeral
- **PLOT4ai** - AI/ML specific threats

### Exporting Reports

1. Open a threat model
2. Click "Report" in the toolbar
3. Select export format (PDF)
4. Download the generated report

## Troubleshooting

### Check Logs
```bash
kubectl logs -n threat-dragon -l app=threat-dragon -f
```

### Check Pod Status
```bash
kubectl describe pod -n threat-dragon -l app=threat-dragon
```

### Restart Deployment
```bash
kubectl rollout restart deployment/threat-dragon -n threat-dragon
```

### Check IngressRoute
```bash
kubectl describe ingressroute threat-dragon -n threat-dragon
```

## File Structure

```
threat-dragon/
├── application.yaml       # ArgoCD Application
├── namespace.yaml         # Kubernetes Namespace
├── deployment.yaml        # Deployment spec
├── service.yaml          # ClusterIP Service
├── secrets.yaml          # Encryption keys (UPDATE BEFORE PROD!)
├── ingressroute.yaml     # Traefik IngressRoute + TLS cert
├── deploy-threat-dragon.sh # Deployment script
└── README.md             # This file
```

## References

- [OWASP Threat Dragon](https://owasp.org/www-project-threat-dragon/)
- [GitHub Repository](https://github.com/OWASP/threat-dragon)
- [Documentation](https://owasp.org/www-project-threat-dragon/docs-2/)
- [Docker Hub](https://hub.docker.com/r/owasp/threat-dragon)
