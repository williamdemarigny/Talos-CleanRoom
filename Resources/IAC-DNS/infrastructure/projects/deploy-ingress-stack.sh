#!/bin/bash
set -euo pipefail

# Kubernetes Infrastructure Stack Deployment Script
# Deploys: MetalLB -> cert-manager -> Traefik -> Longhorn
#
# Prerequisites:
# - Kubernetes cluster is running (Talos)
# - ArgoCD is installed and running
# - kubectl is configured to access the cluster
#
# Note: OpenVAS is deployed separately via deploy-openvas.sh
# after the cluster is stable

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=============================================="
echo "  Kubernetes Infrastructure Stack Deployment"
echo "=============================================="
echo ""

# Check prerequisites
echo "[1/10] Checking prerequisites..."

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
echo "[2/10] Deploying MetalLB..."
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
echo "[3/10] Configuring MetalLB IP Pool..."
kubectl apply -f "${SCRIPT_DIR}/metallb/ip-pool.yaml"
echo "✓ MetalLB IP Pool configured (10.83.3.200-10.83.3.250)"
echo ""

# Deploy cert-manager
echo "[4/10] Deploying cert-manager..."
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
echo "[5/10] Configuring ClusterIssuers..."
sleep 5  # Give webhook time to fully initialize
kubectl apply -f "${SCRIPT_DIR}/cert-manager/cluster-issuers.yaml"
echo "✓ ClusterIssuers configured"
echo ""

# Deploy Traefik
echo "[6/10] Deploying Traefik..."
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
echo "[7/10] Configuring Traefik Middlewares..."
kubectl apply -f "${SCRIPT_DIR}/traefik/middlewares.yaml"
echo "✓ Middlewares configured"
echo ""

# Deploy Longhorn
echo "[8/10] Deploying Longhorn..."
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

# Get LoadBalancer IP
echo "[9/10] Retrieving Traefik LoadBalancer IP..."
sleep 5
TRAEFIK_IP=$(kubectl get svc traefik -n traefik -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "pending")

# Apply IngressRoutes (excluding OpenVAS which will be added later)
echo "[10/10] Applying IngressRoutes..."
kubectl apply -f "${SCRIPT_DIR}/traefik/dashboard-ingressroute.yaml"
kubectl apply -f "${SCRIPT_DIR}/traefik/ingressroutes/argocd-ingressroute.yaml"
kubectl apply -f "${SCRIPT_DIR}/traefik/ingressroutes/longhorn-ingressroute.yaml"
echo "✓ IngressRoutes applied"
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
echo "2. Default credentials (CHANGE IN PRODUCTION!):"
echo "   All UIs use: admin / admin"
echo "   - Traefik/Longhorn: update traefik/middlewares.yaml"
echo "   - ArgoCD: update infrastructure/argocd/values.yaml"
echo ""
echo "3. Verify deployment:"
echo "   kubectl get pods -n metallb-system"
echo "   kubectl get pods -n cert-manager"
echo "   kubectl get pods -n traefik"
echo "   kubectl get pods -n longhorn-system"
echo "   kubectl get svc -n traefik"
echo ""
echo "4. Access UIs (credentials: admin/admin):"
echo "   - https://traefik.knowledgeondemand.net (Traefik Dashboard)"
echo "   - https://longhorn.knowledgeondemand.net (Longhorn Storage)"
echo "   - https://argocd.knowledgeondemand.net (ArgoCD)"
echo ""
echo "5. Deploy OpenVAS (optional, resource-intensive):"
echo "   After the cluster is stable, run:"
echo "   ./deploy-openvas.sh"
echo ""
