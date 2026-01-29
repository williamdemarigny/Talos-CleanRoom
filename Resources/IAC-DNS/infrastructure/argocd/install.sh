#!/bin/bash
set -euo pipefail

# ArgoCD Installation Script
# This script installs ArgoCD using Helm

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE="argocd"
RELEASE_NAME="argocd"
CHART_VERSION="9.3.4"  # ArgoCD v3.2.5 - matches application.yaml

echo "=== ArgoCD Installation ==="

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo "Error: kubectl is not installed or not in PATH"
    exit 1
fi

# Check if helm is available
if ! command -v helm &> /dev/null; then
    echo "Error: helm is not installed or not in PATH"
    exit 1
fi

# Check cluster connectivity
echo "Checking cluster connectivity..."
if ! kubectl cluster-info &> /dev/null; then
    echo "Error: Cannot connect to Kubernetes cluster"
    exit 1
fi

# Create namespace
echo "Creating namespace: ${NAMESPACE}..."
kubectl apply -f "${SCRIPT_DIR}/namespace.yaml"

# Apply repository credentials if encrypted file exists
SOPS_CREDS="${SCRIPT_DIR}/repo-credentials.sops.yaml"
if [[ -f "${SOPS_CREDS}" ]]; then
    if command -v sops &> /dev/null; then
        echo "Applying repository credentials..."
        sops --decrypt "${SOPS_CREDS}" | kubectl apply -f -
    else
        echo "Warning: sops not found, skipping repository credentials"
        echo "Install sops to apply private repo credentials"
    fi
fi

# Add ArgoCD Helm repository
echo "Adding ArgoCD Helm repository..."
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update

# Install ArgoCD
echo "Installing ArgoCD..."
helm upgrade --install "${RELEASE_NAME}" argo/argo-cd \
    --namespace "${NAMESPACE}" \
    --version "${CHART_VERSION}" \
    --values "${SCRIPT_DIR}/values.yaml" \
    --wait \
    --timeout 10m

# Wait for ArgoCD to be ready
echo "Waiting for ArgoCD pods to be ready..."
kubectl wait --for=condition=ready pod \
    -l app.kubernetes.io/name=argocd-server \
    -n "${NAMESPACE}" \
    --timeout=300s

# Set admin password to 'admin' using ArgoCD's bcrypt tool
# This ensures the password works regardless of Helm chart version
echo "Setting admin password..."
ADMIN_HASH=$(kubectl -n "${NAMESPACE}" exec deployment/argocd-server -- argocd account bcrypt --password admin 2>/dev/null)
if [[ -n "${ADMIN_HASH}" ]]; then
    kubectl -n "${NAMESPACE}" patch secret argocd-secret \
        -p "{\"stringData\": {\"admin.password\": \"${ADMIN_HASH}\", \"admin.passwordMtime\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}}"
    echo "Admin password set to: admin"
else
    echo "Warning: Could not set admin password automatically"
    echo "The password from values.yaml may still work, or set it manually"
fi

echo ""
echo "=== ArgoCD Installation Complete ==="
echo ""
echo "Default credentials: admin / admin"
echo ""
echo "To access ArgoCD UI via port-forward:"
echo "  kubectl port-forward svc/argocd-server -n ${NAMESPACE} 8080:443"
echo "  Then open: https://localhost:8080"
echo ""
