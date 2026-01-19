#!/bin/bash
set -euo pipefail

# ArgoCD Uninstallation Script

NAMESPACE="argocd"
RELEASE_NAME="argocd"

echo "=== ArgoCD Uninstallation ==="

# Check if helm is available
if ! command -v helm &> /dev/null; then
    echo "Error: helm is not installed or not in PATH"
    exit 1
fi

# Uninstall ArgoCD
echo "Uninstalling ArgoCD Helm release..."
helm uninstall "${RELEASE_NAME}" --namespace "${NAMESPACE}" || true

# Delete namespace
echo "Deleting namespace: ${NAMESPACE}..."
kubectl delete namespace "${NAMESPACE}" --ignore-not-found

echo ""
echo "=== ArgoCD Uninstallation Complete ==="
