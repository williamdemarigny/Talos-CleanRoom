#!/bin/bash
set -euo pipefail

# SecureCodeBox Deployment Script
# Deploys: Operator -> Nmap Scanner
#
# Prerequisites:
# - Kubernetes cluster is running
# - ArgoCD is installed and running
# - kubectl is configured to access the cluster

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=============================================="
echo "  SecureCodeBox Deployment"
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
    echo "Error: ArgoCD namespace not found. Please install ArgoCD first."
    exit 1
fi

echo "✓ Prerequisites met"
echo ""

# Deploy SecureCodeBox Operator
echo "[2/4] Deploying SecureCodeBox Operator..."
kubectl apply -f "${SCRIPT_DIR}/operator-application.yaml"

echo "Waiting for SecureCodeBox Operator to be ready..."
sleep 15

kubectl wait --for=condition=available deployment/securecodebox-controller-manager \
    -n securecodebox-system \
    --timeout=300s 2>/dev/null || {
    echo "Waiting for operator deployment to be created..."
    sleep 30
    kubectl wait --for=condition=available deployment/securecodebox-controller-manager \
        -n securecodebox-system \
        --timeout=300s
}

echo "✓ SecureCodeBox Operator deployed"
echo ""

# Deploy Nmap Scanner
echo "[3/4] Deploying Nmap Scanner..."
kubectl apply -f "${SCRIPT_DIR}/nmap-application.yaml"

echo "Waiting for Nmap ScanType to be registered..."
sleep 10

# Wait for ScanType CRD to be available
kubectl wait --for=condition=Ready scantype/nmap \
    -n securecodebox-system \
    --timeout=120s 2>/dev/null || {
    echo "Waiting for nmap ScanType..."
    sleep 20
    kubectl get scantype -n securecodebox-system
}

echo "✓ Nmap Scanner deployed"
echo ""

# Show status
echo "[4/4] Deployment Status"
echo ""
kubectl get pods -n securecodebox-system
echo ""
kubectl get scantype -n securecodebox-system 2>/dev/null || echo "ScanTypes not yet available"
echo ""

echo "=============================================="
echo "  SecureCodeBox Deployment Complete!"
echo "=============================================="
echo ""
echo "Usage Examples:"
echo ""
echo "1. Run example nmap scans:"
echo "   kubectl apply -f ${SCRIPT_DIR}/example-scans.yaml"
echo ""
echo "2. Check scan status:"
echo "   kubectl get scans -n securecodebox-system"
echo ""
echo "3. View scan results:"
echo "   kubectl get findings -n securecodebox-system"
echo ""
echo "4. Delete completed scans:"
echo "   kubectl delete scans --all -n securecodebox-system"
echo ""
echo "5. Available scan types in example-scans.yaml:"
echo "   - nmap-quick-scan: Fast scan of top 100 ports"
echo "   - nmap-service-scan: Service version detection"
echo "   - nmap-network-scan: Network host discovery"
echo "   - nmap-daily-scan: Scheduled daily scan"
echo ""
