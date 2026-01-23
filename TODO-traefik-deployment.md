# Traefik Ingress Stack Deployment Checklist

## Prerequisites

- [ ] Talos cluster is running
- [ ] kubectl is configured to access the cluster
- [ ] ArgoCD is installed and running

## Deployment Steps

### Step 1: Verify Cluster Access
```bash
kubectl cluster-info
kubectl get nodes
```
- [ ] Cluster is accessible
- [ ] All nodes are Ready

### Step 2: Ensure ArgoCD is Running
```bash
# If not already installed, bootstrap with Helm
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update
helm install argocd argo/argo-cd -n argocd --create-namespace \
    -f Resources/IAC-DNS/infrastructure/argocd/values.yaml

# Verify ArgoCD is running (should have 2 replicas for HA components)
kubectl get pods -n argocd
kubectl get deployment -n argocd
```
- [ ] ArgoCD pods are running
- [ ] HA components show 2/2 replicas (controller, server, repo-server, applicationset)

### Step 3: Deploy the Ingress Stack

**Option A: Use the deployment script (recommended)**
```bash
cd Resources/IAC-DNS/infrastructure/projects
chmod +x deploy-ingress-stack.sh
./deploy-ingress-stack.sh
```

**Option B: Manual step-by-step**
```bash
cd Resources/IAC-DNS/infrastructure/projects

# 1. Deploy MetalLB
kubectl apply -f metallb/application.yaml
kubectl wait --for=condition=available deployment/metallb-controller -n metallb-system --timeout=300s
kubectl apply -f metallb/ip-pool.yaml

# 2. Deploy cert-manager
kubectl apply -f cert-manager/application.yaml
kubectl wait --for=condition=available deployment/cert-manager -n cert-manager --timeout=300s
kubectl wait --for=condition=available deployment/cert-manager-webhook -n cert-manager --timeout=300s
kubectl apply -f cert-manager/cluster-issuers.yaml

# 3. Deploy Traefik
kubectl apply -f traefik/application.yaml
kubectl wait --for=condition=available deployment/traefik -n traefik --timeout=300s
kubectl apply -f traefik/middlewares.yaml
```

- [ ] MetalLB deployed and IP pool configured
- [ ] cert-manager deployed and ClusterIssuers created
- [ ] Traefik deployed and middlewares configured

### Step 4: Get Traefik LoadBalancer IP
```bash
kubectl get svc traefik -n traefik
```
- [ ] Note the EXTERNAL-IP: __________________

### Step 5: Configure DNS in OPNsense

Navigate to: **Services > Unbound DNS > Overrides**

Add Host Overrides:

| Host | Domain | IP Address |
|------|--------|------------|
| traefik | knowledgeondemand.net | (Traefik IP) |
| argocd | knowledgeondemand.net | (Traefik IP) |
| longhorn | knowledgeondemand.net | (Traefik IP) |

- [ ] DNS overrides configured in OPNsense
- [ ] DNS resolution verified: `nslookup argocd.knowledgeondemand.net`

### Step 6: Create Basic Auth Secret
```bash
# Generate password hash (install apache2-utils if needed)
htpasswd -nb admin YOUR_SECURE_PASSWORD

# Create the secret (replace the hash with output from above)
kubectl create secret generic basic-auth-secret \
    --from-literal=users='admin:$apr1$...' \
    -n traefik
```
- [ ] Basic auth secret created

### Step 7: Apply IngressRoutes
```bash
cd Resources/IAC-DNS/infrastructure/projects

# Traefik dashboard
kubectl apply -f traefik/dashboard-ingressroute.yaml

# ArgoCD and Longhorn
kubectl apply -f traefik/ingressroutes/
```
- [ ] Traefik dashboard IngressRoute applied
- [ ] ArgoCD IngressRoute applied
- [ ] Longhorn IngressRoute applied

### Step 8: Verify Deployment
```bash
# Check all pods are running
kubectl get pods -n metallb-system
kubectl get pods -n cert-manager
kubectl get pods -n traefik
kubectl get pods -n argocd

# Verify HA - pods should be distributed across nodes
kubectl get pods -n traefik -o wide
kubectl get pods -n argocd -o wide

# Check certificates
kubectl get certificates -A

# Check IngressRoutes
kubectl get ingressroute -A
```
- [ ] All MetalLB pods running (controller + speaker daemonset)
- [ ] All cert-manager pods running
- [ ] All Traefik pods running (2 replicas on different nodes)
- [ ] All ArgoCD pods running (2 replicas for HA components)
- [ ] Certificates created

### Step 9: Access Services

| Service | URL | Credentials |
|---------|-----|-------------|
| Traefik Dashboard | https://traefik.knowledgeondemand.net | admin / (basic auth password) |
| ArgoCD | https://argocd.knowledgeondemand.net | admin / (see below) |
| Longhorn | https://longhorn.knowledgeondemand.net | admin / (basic auth password) |

**Get ArgoCD admin password:**
```bash
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo
```

- [ ] Traefik dashboard accessible
- [ ] ArgoCD accessible
- [ ] Longhorn accessible

---

## Post-Deployment (Optional)

### Enable ArgoCD Self-Management

After initial Helm bootstrap, enable ArgoCD to manage itself via GitOps:

```bash
# Commit and push argocd values.yaml changes first
git add Resources/IAC-DNS/infrastructure/argocd/
git commit -m "ArgoCD HA configuration and self-management"
git push

# Apply the self-managing Application
kubectl apply -f Resources/IAC-DNS/infrastructure/argocd/application.yaml

# Verify ArgoCD is now managing itself
kubectl get applications -n argocd | grep argocd
```

- [ ] ArgoCD self-management Application applied
- [ ] Future changes to values.yaml auto-sync via GitOps

### Switch to Let's Encrypt Certificates

Once DNS is publicly resolvable (if applicable), update certificate issuers:

1. Edit IngressRoute certificate references to use `letsencrypt-staging` first
2. Verify certificates are issued correctly
3. Switch to `letsencrypt-prod` for trusted certificates

- [ ] Let's Encrypt staging tested
- [ ] Let's Encrypt production enabled

### Assign Static IP to Traefik

Edit `Resources/IAC-DNS/infrastructure/projects/traefik/application.yaml`:
```yaml
service:
  annotations:
    metallb.universe.tf/loadBalancerIPs: "10.83.3.200"
```

Then sync in ArgoCD or run:
```bash
kubectl apply -f traefik/application.yaml
```

- [ ] Static IP assigned (if desired)

---

## Troubleshooting Commands

```bash
# Check Traefik logs
kubectl logs -n traefik -l app.kubernetes.io/name=traefik -f

# Check MetalLB speaker logs
kubectl logs -n metallb-system -l app.kubernetes.io/component=speaker

# Check MetalLB speaker pods (should be running on each node)
kubectl get pods -n metallb-system
kubectl get daemonset -n metallb-system

# Check cert-manager logs
kubectl logs -n cert-manager -l app=cert-manager

# Check certificate status
kubectl describe certificate -A

# Check ArgoCD application sync status
kubectl get applications -n argocd

# Check node status
kubectl get nodes -o wide
```

### MetalLB Speaker Pods Not Starting

If MetalLB speaker pods fail with PodSecurity errors, verify namespace labels:
```bash
kubectl get namespace metallb-system -o yaml | grep pod-security

# If labels are missing (should be set automatically by ArgoCD):
kubectl label namespace metallb-system pod-security.kubernetes.io/enforce=privileged --overwrite
kubectl label namespace metallb-system pod-security.kubernetes.io/audit=privileged --overwrite
kubectl label namespace metallb-system pod-security.kubernetes.io/warn=privileged --overwrite
kubectl rollout restart daemonset metallb-speaker -n metallb-system
```

**Note:** The MetalLB application.yaml now includes `managedNamespaceMetadata` to automatically apply these labels.

---

## Files Reference

```
Resources/IAC-DNS/infrastructure/
├── argocd/
│   ├── namespace.yaml               # ArgoCD namespace
│   ├── values.yaml                  # ArgoCD Helm values (HA config)
│   └── application.yaml             # ArgoCD self-management Application
└── projects/
    ├── deploy-ingress-stack.sh      # Automated deployment script
    ├── metallb/
    │   ├── application.yaml         # MetalLB ArgoCD app (includes pod security labels)
    │   └── ip-pool.yaml             # IP pool: 10.83.3.200-250
    ├── cert-manager/
    │   ├── application.yaml         # cert-manager ArgoCD app
    │   └── cluster-issuers.yaml     # Self-signed + Let's Encrypt
    └── traefik/
        ├── application.yaml         # Traefik ArgoCD app (2 replicas, HA)
        ├── middlewares.yaml         # Security middlewares
        ├── dashboard-ingressroute.yaml  # Dashboard access
        ├── README.md                # Documentation
        └── ingressroutes/
            ├── argocd-ingressroute.yaml
            └── longhorn-ingressroute.yaml
```
