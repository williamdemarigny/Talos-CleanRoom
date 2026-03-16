# Traefik Ingress Controller Deployment

This directory contains the ArgoCD applications and configurations for deploying Traefik as the ingress controller for the Kubernetes cluster.

## Architecture Overview

```
Internet/Network
      │
      ▼
┌─────────────────┐
│    OPNsense     │  (Firewall/Router)
│   10.83.3.1     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│    MetalLB      │  (LoadBalancer for bare-metal)
│ 10.83.3.200-250 │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│    Traefik      │  (Ingress Controller)
│   LoadBalancer  │
└────────┬────────┘
         │
    ┌────┴────┬─────────┐
    ▼         ▼         ▼
┌───────┐ ┌───────┐ ┌───────┐
│ArgoCD │ │Harbor │ │OpenVAS│  (Services)
└───────┘ └───────┘ └───────┘
```

## Components

| Component | Version | Purpose |
|-----------|---------|---------|
| MetalLB | 0.14.9 | LoadBalancer implementation for bare-metal |
| cert-manager | 1.16.2 | Automatic TLS certificate management |
| Traefik | 33.2.1 | Ingress controller |

## Deployment Order

The applications use ArgoCD sync waves to ensure correct deployment order:

1. **Wave -2**: MetalLB (LoadBalancer support)
2. **Wave -1**: cert-manager (TLS certificates)
3. **Wave 0**: Traefik (Ingress controller)

## Installation Steps

### 1. Apply ArgoCD Applications

```bash
# Apply MetalLB
kubectl apply -f metallb/application.yaml

# Wait for MetalLB to be ready
kubectl wait --for=condition=available deployment/metallb-controller -n metallb-system --timeout=300s

# Apply MetalLB IP Pool configuration
kubectl apply -f metallb/ip-pool.yaml

# Apply cert-manager
kubectl apply -f cert-manager/application.yaml

# Wait for cert-manager to be ready
kubectl wait --for=condition=available deployment/cert-manager -n cert-manager --timeout=300s

# Apply cert-manager ClusterIssuers
kubectl apply -f cert-manager/cluster-issuers.yaml

# Apply Traefik
kubectl apply -f traefik/application.yaml

# Wait for Traefik to be ready
kubectl wait --for=condition=available deployment/traefik -n traefik --timeout=300s
```

### 2. Configure Basic Auth (Required for Dashboard)

```bash
# Generate password hash (replace 'admin' and 'your-password')
htpasswd -nb admin your-password

# Create the secret
kubectl create secret generic basic-auth-secret \
  --from-literal=users='admin:$apr1$...' \
  -n traefik
```

### 3. Apply Middlewares and IngressRoutes

```bash
# Apply Traefik middlewares
kubectl apply -f traefik/middlewares.yaml

# Apply Dashboard IngressRoute
kubectl apply -f traefik/dashboard-ingressroute.yaml

# Apply service IngressRoutes
kubectl apply -f traefik/ingressroutes/
```

### 4. Configure DNS

Add DNS records pointing to the Traefik LoadBalancer IP:

```
traefik.knowledgeondemand.net      -> <TRAEFIK_LB_IP>
argocd.knowledgeondemand.net       -> <TRAEFIK_LB_IP>
harbor.knowledgeondemand.net       -> <TRAEFIK_LB_IP>
openvas.knowledgeondemand.net      -> <TRAEFIK_LB_IP>
faraday.knowledgeondemand.net      -> <TRAEFIK_LB_IP>
threatdragon.knowledgeondemand.net -> <TRAEFIK_LB_IP>
scan.knowledgeondemand.net         -> <TRAEFIK_LB_IP>
cleanroom.knowledgeondemand.net    -> <TRAEFIK_LB_IP>
```

Get the LoadBalancer IP:
```bash
kubectl get svc traefik -n traefik -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
```

## Configuration

### MetalLB IP Pool

Edit `metallb/ip-pool.yaml` to configure the IP range for LoadBalancer services:

```yaml
spec:
  addresses:
    - 10.83.3.200-10.83.3.250  # Adjust to your network
```

### TLS Certificates

The setup uses cert-manager with three ClusterIssuers:

- `selfsigned-issuer` - For internal/development (default)
- `letsencrypt-staging` - For testing Let's Encrypt
- `letsencrypt-prod` - For production certificates

To switch to Let's Encrypt, update the `issuerRef` in Certificate resources:

```yaml
issuerRef:
  name: letsencrypt-prod  # or letsencrypt-staging
  kind: ClusterIssuer
```

### Static IP Assignment

To assign a specific IP to Traefik, uncomment and edit in `traefik/application.yaml`:

```yaml
service:
  annotations:
    metallb.universe.tf/loadBalancerIPs: "10.83.3.200"
```

## Adding New Services

### Using IngressRoute (Recommended)

```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: my-app
  namespace: my-namespace
spec:
  entryPoints:
    - websecure
  routes:
    - match: Host(`myapp.knowledgeondemand.net`)
      kind: Rule
      services:
        - name: my-service
          port: 80
      middlewares:
        - name: secured
          namespace: traefik
  tls:
    secretName: my-app-tls
```

### Using Standard Ingress

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app
  namespace: my-namespace
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  ingressClassName: traefik
  tls:
    - hosts:
        - myapp.knowledgeondemand.net
      secretName: my-app-tls
  rules:
    - host: myapp.knowledgeondemand.net
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: my-service
                port:
                  number: 80
```

## Troubleshooting

### Check Traefik Logs
```bash
kubectl logs -n traefik -l app.kubernetes.io/name=traefik -f
```

### Check LoadBalancer Status
```bash
kubectl get svc -n traefik traefik
kubectl describe svc -n traefik traefik
```

### Check Certificate Status
```bash
kubectl get certificates -A
kubectl describe certificate <name> -n <namespace>
```

### Check MetalLB
```bash
kubectl get ipaddresspool -n metallb-system
kubectl logs -n metallb-system -l app.kubernetes.io/component=speaker
```

## File Structure

```
traefik/
├── application.yaml           # ArgoCD Application for Traefik
├── middlewares.yaml          # Reusable Traefik middlewares
├── dashboard-ingressroute.yaml # Traefik dashboard access
├── ingressroutes/
│   ├── argocd-ingressroute.yaml
│   └── longhorn-ingressroute.yaml  # Legacy (Longhorn replaced by Ceph CSI)
└── README.md

metallb/
├── application.yaml          # ArgoCD Application for MetalLB
└── ip-pool.yaml             # IP address pool configuration

cert-manager/
├── application.yaml          # ArgoCD Application for cert-manager
└── cluster-issuers.yaml     # ClusterIssuer configurations
```
