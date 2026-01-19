#!/bin/bash
set -euo pipefail

# ArgoCD Installation Script
# This script installs ArgoCD using Helm

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE="argocd"
RELEASE_NAME="argocd"
CHART_VERSION="7.7.16"  # Update to latest stable version as needed

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

# Get initial admin password
echo ""
echo "=== ArgoCD Installation Complete ==="
echo ""
echo "To get the initial admin password, run:"
echo "  kubectl -n ${NAMESPACE} get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo"
echo ""
echo "To access ArgoCD UI via port-forward:"
echo "  kubectl port-forward svc/argocd-server -n ${NAMESPACE} 8080:443"
echo "  Then open: https://localhost:8080"
echo ""
echo "Default login: admin / <password from above>"
