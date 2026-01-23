#!/bin/bash
set -euo pipefail

# Kubernetes Infrastructure Stack Deployment Script
# Deploys: MetalLB -> cert-manager -> Traefik -> Longhorn -> ClamAV
#
# Prerequisites:
# - Kubernetes cluster is running (Talos)
# - ArgoCD is installed and running
# - kubectl is configured to access the cluster

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=============================================="
echo "  Kubernetes Infrastructure Stack Deployment"
echo "=============================================="
echo ""

# Check prerequisites
echo "[1/12] Checking prerequisites..."

if ! command -v kubectl &> /dev/null; then
    echo "Error: kubectl is not installed or not in PATH"
    exit 1
fi

if ! kubectl cluster-info &> /dev/null; then
    echo "Error: Cannot connect to Kubernetes cluster"
    exit 1
fi

# Check if ArgoCD is running
if ! kubectl get namespace argocd &> /dev/null; then
    echo "Error: ArgoCD namespace not found. Please install ArgoCD first."
    echo "Run: ./infrastructure/argocd/install.sh"
    exit 1
fi

echo "✓ Prerequisites met"
echo ""

# Deploy MetalLB
echo "[2/12] Deploying MetalLB..."
kubectl apply -f "${SCRIPT_DIR}/metallb/application.yaml"

echo "Waiting for MetalLB to be ready..."
sleep 10  # Give ArgoCD time to create resources

# Wait for MetalLB controller
kubectl wait --for=condition=available deployment/metallb-controller \
    -n metallb-system \
    --timeout=300s 2>/dev/null || {
    echo "Waiting for MetalLB deployment to be created..."
    sleep 30
    kubectl wait --for=condition=available deployment/metallb-controller \
        -n metallb-system \
        --timeout=300s
}

echo "✓ MetalLB deployed"
echo ""

# Configure MetalLB IP Pool
echo "[3/12] Configuring MetalLB IP Pool..."
kubectl apply -f "${SCRIPT_DIR}/metallb/ip-pool.yaml"
echo "✓ MetalLB IP Pool configured (10.83.3.200-10.83.3.250)"
echo ""

# Deploy cert-manager
echo "[4/12] Deploying cert-manager..."
kubectl apply -f "${SCRIPT_DIR}/cert-manager/application.yaml"

echo "Waiting for cert-manager to be ready..."
sleep 10

kubectl wait --for=condition=available deployment/cert-manager \
    -n cert-manager \
    --timeout=300s 2>/dev/null || {
    echo "Waiting for cert-manager deployment to be created..."
    sleep 30
    kubectl wait --for=condition=available deployment/cert-manager \
        -n cert-manager \
        --timeout=300s
}

# Wait for webhook to be ready (required before creating issuers)
kubectl wait --for=condition=available deployment/cert-manager-webhook \
    -n cert-manager \
    --timeout=300s

echo "✓ cert-manager deployed"
echo ""

# Configure ClusterIssuers
echo "[5/12] Configuring ClusterIssuers..."
sleep 5  # Give webhook time to fully initialize
kubectl apply -f "${SCRIPT_DIR}/cert-manager/cluster-issuers.yaml"
echo "✓ ClusterIssuers configured"
echo ""

# Deploy Traefik
echo "[6/12] Deploying Traefik..."
kubectl apply -f "${SCRIPT_DIR}/traefik/application.yaml"

echo "Waiting for Traefik to be ready..."
sleep 10

kubectl wait --for=condition=available deployment/traefik \
    -n traefik \
    --timeout=300s 2>/dev/null || {
    echo "Waiting for Traefik deployment to be created..."
    sleep 30
    kubectl wait --for=condition=available deployment/traefik \
        -n traefik \
        --timeout=300s
}

echo "✓ Traefik deployed"
echo ""

# Apply Middlewares
echo "[7/12] Configuring Traefik Middlewares..."
kubectl apply -f "${SCRIPT_DIR}/traefik/middlewares.yaml"
echo "✓ Middlewares configured"
echo ""

# Deploy Longhorn
echo "[8/12] Deploying Longhorn..."
kubectl apply -f "${SCRIPT_DIR}/longhorn/application.yaml"

echo "Waiting for Longhorn to be ready..."
sleep 15  # Give ArgoCD time to create namespace and resources

kubectl wait --for=condition=available deployment/longhorn-driver-deployer \
    -n longhorn-system \
    --timeout=300s 2>/dev/null || {
    echo "Waiting for Longhorn deployment to be created..."
    sleep 45
    kubectl wait --for=condition=available deployment/longhorn-driver-deployer \
        -n longhorn-system \
        --timeout=300s
}

echo "✓ Longhorn deployed"
echo ""

# Deploy ClamAV
echo "[9/12] Deploying ClamAV..."
kubectl apply -f "${SCRIPT_DIR}/clamav/application.yaml"

echo "Waiting for ClamAV to be ready..."
sleep 15  # Give ArgoCD time to create namespace and resources

kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=clamav \
    -n clamav \
    --timeout=300s 2>/dev/null || {
    echo "Waiting for ClamAV pod to be created..."
    sleep 45
    kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=clamav \
        -n clamav \
        --timeout=300s
}

echo "✓ ClamAV deployed"
echo ""

# Get LoadBalancer IP
echo "[10/12] Retrieving Traefik LoadBalancer IP..."
sleep 5
TRAEFIK_IP=$(kubectl get svc traefik -n traefik -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "pending")

# Apply IngressRoutes
echo "[11/12] Applying IngressRoutes..."
kubectl apply -f "${SCRIPT_DIR}/traefik/dashboard-ingressroute.yaml"
kubectl apply -f "${SCRIPT_DIR}/traefik/ingressroutes/"
echo "✓ IngressRoutes applied"

# Apply ClamAV TCP IngressRoute
echo "[12/12] Applying ClamAV TCP IngressRoute..."
kubectl apply -f "${SCRIPT_DIR}/clamav/tcp-ingressroute.yaml"
echo "✓ ClamAV TCP IngressRoute applied"
echo ""

echo ""
echo "=============================================="
echo "  Deployment Complete!"
echo "=============================================="
echo ""
echo "Traefik LoadBalancer IP: ${TRAEFIK_IP}"
echo ""
echo "Next Steps:"
echo ""
echo "1. Configure DNS records in OPNsense pointing to ${TRAEFIK_IP}:"
echo "   - traefik.knowledgeondemand.net"
echo "   - argocd.knowledgeondemand.net"
echo "   - longhorn.knowledgeondemand.net"
echo ""
echo "2. Create basic-auth secret for protected services:"
echo "   # Install htpasswd if needed: apt-get install apache2-utils"
echo "   htpasswd -nb admin YOUR_PASSWORD"
echo "   kubectl create secret generic basic-auth-secret \\"
echo "       --from-literal=users='admin:\$apr1\$...' \\"
echo "       -n traefik"
echo ""
echo "3. Verify deployment:"
echo "   kubectl get pods -n metallb-system"
echo "   kubectl get pods -n cert-manager"
echo "   kubectl get pods -n traefik"
echo "   kubectl get pods -n longhorn-system"
echo "   kubectl get pods -n clamav"
echo "   kubectl get svc -n traefik"
echo ""
echo "4. ClamAV is accessible at:"
echo "   - Internal: clamav.clamav.svc.cluster.local:3310"
echo "   - External: ${TRAEFIK_IP}:3310 (via Traefik TCP routing)"
echo ""
