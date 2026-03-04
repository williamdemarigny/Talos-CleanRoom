#!/bin/bash
set -euo pipefail

# OWASP Threat Dragon Deployment Script
#
# Prerequisites:
# - Kubernetes cluster is running
# - ArgoCD is installed
# - Traefik is deployed with basic-auth middleware
# - cert-manager is running

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=============================================="
echo "  OWASP Threat Dragon Deployment"
echo "=============================================="
echo ""

# Check prerequisites
echo "[1/4] Checking prerequisites..."

if ! command -v kubectl &> /dev/null; then
    echo "Error: kubectl is not installed or not in PATH"
    exit 1
fi

if ! kubectl cluster-info &> /dev/null; then
    echo "Error: Cannot connect to Kubernetes cluster"
    exit 1
fi

if ! kubectl get namespace argocd &> /dev/null; then
    echo "Error: ArgoCD namespace not found"
    exit 1
fi

echo "Prerequisites met"
echo ""

# Create namespace first (in case ArgoCD sync is slow)
echo "[2/4] Creating namespace..."
kubectl apply -f "${SCRIPT_DIR}/namespace.yaml"
echo "Namespace created"
echo ""

# Apply secrets (should be done before ArgoCD syncs)
echo "[3/4] Applying secrets..."
kubectl apply -f "${SCRIPT_DIR}/secrets.yaml"
echo "Secrets applied"
echo ""

# Deploy via ArgoCD
echo "[4/4] Deploying Threat Dragon via ArgoCD..."
kubectl apply -f "${SCRIPT_DIR}/application.yaml"

echo "Waiting for deployment to be ready..."
sleep 10

kubectl wait --for=condition=available deployment/threat-dragon \
    -n threat-dragon \
    --timeout=300s 2>/dev/null || {
    echo "Waiting for deployment to be created..."
    sleep 20
    kubectl wait --for=condition=available deployment/threat-dragon \
        -n threat-dragon \
        --timeout=300s
}

echo ""
echo "=============================================="
echo "  Threat Dragon Deployment Complete!"
echo "=============================================="
echo ""
echo "Verify deployment:"
echo "  kubectl get pods -n threat-dragon"
echo "  kubectl get svc -n threat-dragon"
echo ""
echo "Access UI:"
echo "  https://threatdragon.knowledgeondemand.net"
echo "  Credentials: admin / admin (Traefik basic auth)"
echo ""
echo "Configure DNS:"
echo "  Add DNS record for threatdragon.knowledgeondemand.net"
echo "  pointing to your Traefik LoadBalancer IP"
echo ""
echo "IMPORTANT: Update secrets before production use!"
echo "  Generate new keys: openssl rand -hex 16"
echo "  Edit: ${SCRIPT_DIR}/secrets.yaml"
echo "  Apply: kubectl apply -f ${SCRIPT_DIR}/secrets.yaml"
echo ""
