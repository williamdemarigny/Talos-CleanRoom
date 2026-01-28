#!/bin/bash
set -euo pipefail

# Greenbone Community Edition Deployment Script
#
# Converted from official docker-compose.yml:
# https://greenbone.github.io/docs/latest/_static/docker-compose.yml
#
# Components:
# - Redis (caching)
# - PostgreSQL with GVM extensions
# - GVMD (Greenbone Vulnerability Manager Daemon)
# - GSA (Greenbone Security Assistant - Web UI)
# - OSPD-OpenVAS (Scanner Protocol Daemon)
# - OpenVAS Scanner Daemon (Notus mode)
# - Vulnerability feed data containers
#
# Prerequisites:
# - Kubernetes cluster is running and stable
# - Longhorn storage class is available
# - kubectl is configured to access the cluster
#
# Note: Initial setup takes 15-30 minutes due to feed synchronization

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=============================================="
echo "  Greenbone Community Edition Deployment"
echo "=============================================="
echo ""

# Check prerequisites
echo "[1/5] Checking prerequisites..."

if ! command -v kubectl &> /dev/null; then
    echo "Error: kubectl is not installed or not in PATH"
    exit 1
fi

if ! kubectl cluster-info &> /dev/null; then
    echo "Error: Cannot connect to Kubernetes cluster"
    exit 1
fi

# Check if Longhorn is available
if ! kubectl get storageclass longhorn &> /dev/null; then
    echo "Error: Longhorn storage class not found."
    echo "Please run deploy-ingress-stack.sh first and wait for Longhorn to be ready."
    exit 1
fi

echo "✓ Prerequisites met"
echo ""

# Create namespace
echo "[2/5] Creating namespace..."
kubectl apply -f "${SCRIPT_DIR}/namespace.yaml"
echo "✓ Namespace created"
echo ""

# Deploy PVCs
echo "[3/5] Creating Persistent Volume Claims..."
kubectl apply -f "${SCRIPT_DIR}/pvc.yaml"
echo "✓ PVCs created"
echo ""

# Deploy Greenbone
echo "[4/5] Deploying Greenbone Community Edition..."
kubectl apply -f "${SCRIPT_DIR}/service.yaml"
kubectl apply -f "${SCRIPT_DIR}/greenbone-deployment.yaml"

echo ""
echo "  Waiting for Greenbone to initialize..."
echo "  This includes:"
echo "    - Pulling multiple container images (~3GB total)"
echo "    - Synchronizing vulnerability feed data"
echo "    - Running PostgreSQL migrations"
echo "    - Starting all services"
echo ""
echo "  This process takes 15-30 minutes on first deployment."
echo ""

# Wait for the pod to be running (init containers + main containers)
echo "  Phase 1: Waiting for init containers to complete..."
for i in {1..120}; do
    POD_STATUS=$(kubectl get pods -n openvas -l app=greenbone -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Pending")
    INIT_STATUS=$(kubectl get pods -n openvas -l app=greenbone -o jsonpath='{.items[0].status.initContainerStatuses[*].ready}' 2>/dev/null || echo "")

    if [ "$POD_STATUS" = "Running" ]; then
        echo "  ✓ Init containers completed, main containers starting..."
        break
    fi

    if [ $i -eq 120 ]; then
        echo ""
        echo "  Note: Init containers still running after 60 minutes."
        echo "  This may be normal for slow networks or first-time pulls."
        echo "  You can monitor progress with:"
        echo "    kubectl logs -n openvas -l app=greenbone -c vulnerability-tests"
        echo "    kubectl describe pod -n openvas -l app=greenbone"
        break
    fi

    # Get current init container status
    CURRENT_INIT=$(kubectl get pods -n openvas -l app=greenbone -o jsonpath='{.items[0].status.initContainerStatuses[-1].name}' 2>/dev/null || echo "starting")

    echo "    [$i/120] Phase: $POD_STATUS | Current init: $CURRENT_INIT"
    sleep 30
done

# Wait for readiness probe to pass
echo ""
echo "  Phase 2: Waiting for GSA web interface to be ready..."
for i in {1..60}; do
    # Check if GSA container is ready
    READY=$(kubectl get pods -n openvas -l app=greenbone -o jsonpath='{.items[0].status.containerStatuses[?(@.name=="gsa")].ready}' 2>/dev/null || echo "false")

    if [ "$READY" = "true" ]; then
        echo "  ✓ Greenbone is ready!"
        break
    fi

    if [ $i -eq 60 ]; then
        echo ""
        echo "  Note: GSA is still initializing."
        echo "  The web UI may take additional time to become available."
        echo "  You can monitor progress with:"
        echo "    kubectl logs -n openvas -l app=greenbone -c gsa"
        echo "    kubectl logs -n openvas -l app=greenbone -c gvmd"
        break
    fi

    echo "    [$i/60] Waiting for GSA web interface..."
    sleep 30
done

echo ""
echo "[5/5] Applying IngressRoute..."
kubectl apply -f "${SCRIPT_DIR}/../traefik/ingressroutes/openvas-ingressroute.yaml"
echo "✓ IngressRoute applied"
echo ""

# Create admin user if not exists
echo "Creating admin user (if not already exists)..."
kubectl exec -n openvas deployment/greenbone -c gvmd -- \
    gvmd --create-user=admin --password=admin 2>/dev/null || \
    echo "  (Admin user may already exist)"
echo ""

echo "=============================================="
echo "  Greenbone Community Edition Deployed!"
echo "=============================================="
echo ""
kubectl get pods -n openvas
echo ""
echo "Access Greenbone Security Assistant:"
echo "  URL: https://openvas.knowledgeondemand.net"
echo "  Default credentials: admin / admin"
echo ""
echo "IMPORTANT: Change the default password immediately!"
echo ""
echo "Note: First login may take time while vulnerability"
echo "      feed synchronization completes in the background."
echo ""
echo "Monitor logs with:"
echo "  kubectl logs -n openvas -l app=greenbone -c gsa -f"
echo "  kubectl logs -n openvas -l app=greenbone -c gvmd -f"
echo "  kubectl logs -n openvas -l app=greenbone -c ospd-openvas -f"
echo ""
echo "View all container status:"
echo "  kubectl describe pod -n openvas -l app=greenbone"
echo ""
echo "Add DNS record if not already configured:"
echo "  openvas.knowledgeondemand.net -> <Traefik LoadBalancer IP>"
echo ""
