#!/bin/bash
set -euo pipefail

# Apply Repository Credentials Script
# This script decrypts and applies ArgoCD repository credentials
# Must be run BEFORE ArgoCD tries to sync from private repositories

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE="argocd"
SOPS_FILE="${SCRIPT_DIR}/repo-credentials.sops.yaml"

echo "=== Applying ArgoCD Repository Credentials ==="

# Check if sops is available
if ! command -v sops &> /dev/null; then
    echo "Error: sops is not installed or not in PATH"
    echo "Install with: brew install sops (macOS) or download from https://github.com/getsops/sops/releases"
    exit 1
fi

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo "Error: kubectl is not installed or not in PATH"
    exit 1
fi

# Check if encrypted file exists
if [[ ! -f "${SOPS_FILE}" ]]; then
    echo "Error: Encrypted credentials file not found: ${SOPS_FILE}"
    echo ""
    echo "To create it:"
    echo "  1. Edit repo-credentials.yaml with your credentials"
    echo "  2. Run: sops --encrypt repo-credentials.yaml > repo-credentials.sops.yaml"
    echo "  3. Delete the unencrypted file: rm repo-credentials.yaml"
    exit 1
fi

# Check cluster connectivity
echo "Checking cluster connectivity..."
if ! kubectl cluster-info &> /dev/null; then
    echo "Error: Cannot connect to Kubernetes cluster"
    exit 1
fi

# Ensure namespace exists
echo "Ensuring namespace ${NAMESPACE} exists..."
kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

# Decrypt and apply credentials
echo "Decrypting and applying repository credentials..."
sops --decrypt "${SOPS_FILE}" | kubectl apply -f -

echo ""
echo "=== Repository Credentials Applied Successfully ==="
echo ""
echo "ArgoCD can now access your private repositories."
echo "Verify with: kubectl get secrets -n ${NAMESPACE} -l argocd.argoproj.io/secret-type=repository"
