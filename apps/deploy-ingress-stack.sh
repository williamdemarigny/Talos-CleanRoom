#!/bin/bash
set -euo pipefail

# Kubernetes Infrastructure Stack Deployment Script
# Deploys: Metrics Server -> MetalLB -> cert-manager -> Traefik -> Ceph CSI RBD
#
# Prerequisites:
# - Kubernetes cluster is running (Talos)
# - ArgoCD is installed and running
# - kubectl is configured to access the cluster
#
# Note: OpenVAS is deployed separately via deploy-openvas.sh
# after the cluster is stable

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Source shared functions library (provides wait_for_deployment, etc.)
source "${REPO_ROOT}/lib/functions.sh"

echo "=============================================="
echo "  Kubernetes Infrastructure Stack Deployment"
echo "=============================================="
echo ""

# Check prerequisites
echo "[1/13] Checking prerequisites..."

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
    echo "Run: ./apps/argocd/install.sh"
    exit 1
fi

# Wait for ArgoCD repo-server — must be operational to fetch/render Helm charts.
# The ArgoCD install script uses --wait, but there can be a brief gap before
# the reconciliation loop starts processing new Applications.
echo "Waiting for ArgoCD repo-server to be ready..."
kubectl wait --for=condition=available deployment/argocd-repo-server \
    -n argocd --timeout=300s

echo "✓ Prerequisites met"
echo ""

# Pre-create namespaces so deployments don't depend on ArgoCD's async sync to create them.
# ArgoCD's CreateNamespace=true only creates the namespace AFTER fetching and rendering the
# Helm chart, which can be slow. Pre-creating avoids that race condition entirely.
echo "Pre-creating namespaces..."
for ns in metallb-system cert-manager traefik ceph-csi; do
    kubectl create namespace "$ns" --dry-run=client -o yaml | kubectl apply -f - 2>/dev/null
done
echo "✓ Namespaces ready"
echo ""

# Deploy Metrics Server
echo "[2/13] Deploying Metrics Server..."
kubectl apply -f "${SCRIPT_DIR}/metrics-server/application.yaml"

echo "Waiting for Metrics Server to be ready..."
wait_for_deployment metrics-server kube-system 300s

echo "✓ Metrics Server deployed"
echo ""

# Deploy MetalLB
echo "[3/13] Deploying MetalLB..."
kubectl apply -f "${SCRIPT_DIR}/metallb/application.yaml"

echo "Waiting for MetalLB to be ready..."
wait_for_deployment metallb-controller metallb-system 300s

echo "✓ MetalLB deployed"
echo ""

# Configure MetalLB IP Pool
echo "[4/13] Configuring MetalLB IP Pool..."
kubectl apply -f "${SCRIPT_DIR}/metallb/ip-pool.yaml"
echo "✓ MetalLB IP Pool configured (10.83.3.200-10.83.3.250)"
echo ""

# Deploy cert-manager
echo "[5/13] Deploying cert-manager..."
kubectl apply -f "${SCRIPT_DIR}/cert-manager/application.yaml"

echo "Waiting for cert-manager to be ready..."
wait_for_deployment cert-manager cert-manager 300s

# Wait for webhook to be ready (required before creating issuers)
wait_for_deployment cert-manager-webhook cert-manager 300s

echo "✓ cert-manager deployed"
echo ""

# Apply Cloudflare API token secret (required for DNS-01 challenge)
echo "[6/13] Applying Cloudflare API token secret..."
if [[ -f "${SCRIPT_DIR}/cert-manager/cloudflare-secret.sops.yaml" ]]; then
    sops -d "${SCRIPT_DIR}/cert-manager/cloudflare-secret.sops.yaml" | kubectl apply -f -
    echo "✓ Cloudflare secret applied"
else
    echo "Warning: cloudflare-secret.sops.yaml not found"
    echo "  Create from template: cert-manager/cloudflare-secret.yaml"
    echo "  Then encrypt with: sops -e cloudflare-secret.yaml > cloudflare-secret.sops.yaml"
fi
echo ""

# Configure ClusterIssuers
echo "[7/13] Configuring ClusterIssuers..."
sleep 5  # Give webhook time to fully initialize
kubectl apply -f "${SCRIPT_DIR}/cert-manager/cluster-issuers.yaml"
echo "✓ ClusterIssuers configured"
echo ""

# Deploy Traefik
echo "[8/13] Deploying Traefik..."
kubectl apply -f "${SCRIPT_DIR}/traefik/application.yaml"

echo "Waiting for Traefik to be ready..."
wait_for_deployment traefik traefik 300s

echo "✓ Traefik deployed"
echo ""

# Apply Middlewares
echo "[9/13] Configuring Traefik Middlewares..."
kubectl apply -f "${SCRIPT_DIR}/traefik/middlewares.yaml"
echo "✓ Middlewares configured"
echo ""

# Apply Wildcard Certificate
echo "[10/13] Applying Wildcard Certificate..."
kubectl apply -f "${SCRIPT_DIR}/cert-manager/wildcard-certificate.yaml"
echo "✓ Wildcard certificate applied (letsencrypt-prod)"
echo ""

# Deploy Ceph CSI RBD
echo "[11/13] Deploying Ceph CSI RBD..."
CEPH_STORAGE_DIR="${REPO_ROOT}/apps/ceph-storage"

# 1. Apply CephX secret (SOPS-encrypted)
echo "  Applying Ceph CSI secret..."
if [[ -f "${CEPH_STORAGE_DIR}/ceph-csi-secret.sops.yaml" ]]; then
    sops -d "${CEPH_STORAGE_DIR}/ceph-csi-secret.sops.yaml" | kubectl apply -f -
    echo "  ✓ Ceph CSI secret applied"
elif [[ -f "${CEPH_STORAGE_DIR}/ceph-csi-secret.yaml" ]]; then
    echo "  Warning: Using unencrypted secret (encrypt with SOPS for production)"
    kubectl apply -f "${CEPH_STORAGE_DIR}/ceph-csi-secret.yaml"
    echo "  ✓ Ceph CSI secret applied (unencrypted)"
else
    echo "  Error: No Ceph CSI secret found in ${CEPH_STORAGE_DIR}/"
    exit 1
fi

# 2. Apply ArgoCD Application for ceph-csi-rbd Helm chart
echo "  Applying Ceph CSI ArgoCD application..."
kubectl apply -f "${CEPH_STORAGE_DIR}/application.yaml"

# 3. Wait for csi-rbdplugin-provisioner Deployment (controller)
# On freshly bootstrapped clusters, kubelet configmap cache sync can take 8-12 minutes
echo "  Waiting for csi-rbdplugin-provisioner (up to 15 minutes on fresh clusters)..."
PROVISIONER_READY=false
for i in $(seq 1 90); do
    REPLICAS=$(kubectl get deployment ceph-csi-rbd-provisioner -n ceph-csi \
        -o jsonpath='{.status.availableReplicas}' 2>/dev/null || echo "")
    if [[ "$REPLICAS" =~ ^[1-9] ]]; then
        echo "  ✓ csi-rbdplugin-provisioner ready ($REPLICAS replicas)"
        PROVISIONER_READY=true
        break
    fi
    echo "  Waiting for provisioner... ($i/90)"
    sleep 10
done
if [[ "$PROVISIONER_READY" != "true" ]]; then
    echo ""
    echo "  ===== Ceph CSI provisioner not available — diagnostics ====="
    echo ""
    echo "  --- Deployments in ceph-csi namespace ---"
    kubectl get deployments -n ceph-csi -o wide 2>/dev/null || true
    echo ""
    echo "  --- Pods in ceph-csi namespace ---"
    kubectl get pods -n ceph-csi -o wide 2>/dev/null || true
    echo ""
    echo "  --- ArgoCD Application status ---"
    kubectl get application ceph-csi-rbd -n argocd \
        -o jsonpath='  sync={.status.sync.status} health={.status.health.status}' 2>/dev/null || true
    echo ""
    echo "  --- Recent ceph-csi events (warnings) ---"
    kubectl get events -n ceph-csi --field-selector type!=Normal \
        --sort-by='.lastTimestamp' 2>/dev/null | tail -15 || true
    echo ""
    echo "  Troubleshooting tips:"
    echo "    - Verify Ceph monitors are reachable: kubectl exec -n ceph-csi <pod> -- ceph -s"
    echo "    - Check secret: kubectl get secret csi-rbd-secret -n ceph-csi -o yaml"
    echo "    - Check ConfigMap: kubectl get configmap ceph-csi-config -n ceph-csi -o yaml"
    exit 1
fi

# 4. Wait for csi-rbdplugin DaemonSet (node plugin — mounts RBD on each node)
echo "  Waiting for csi-rbdplugin DaemonSet..."
for i in $(seq 1 36); do
    DESIRED=$(kubectl get daemonset ceph-csi-rbd-nodeplugin -n ceph-csi \
        -o jsonpath='{.status.desiredNumberScheduled}' 2>/dev/null || echo "0")
    READY=$(kubectl get daemonset ceph-csi-rbd-nodeplugin -n ceph-csi \
        -o jsonpath='{.status.numberReady}' 2>/dev/null || echo "0")
    if [[ "$DESIRED" -gt 0 && "$READY" -eq "$DESIRED" ]]; then
        echo "  ✓ csi-rbdplugin: $READY/$DESIRED pods ready"
        break
    fi
    echo "  csi-rbdplugin: $READY/$DESIRED ready... ($i/36)"
    sleep 10
done
if [[ "$READY" -ne "$DESIRED" || "$DESIRED" -eq 0 ]]; then
    echo "  Error: csi-rbdplugin DaemonSet not fully ready ($READY/$DESIRED)"
    kubectl get pods -n ceph-csi -l app=ceph-csi-rbd -o wide 2>/dev/null || true
    exit 1
fi

# 5. Apply StorageClass
echo "  Applying Ceph RBD StorageClass..."
kubectl apply -f "${CEPH_STORAGE_DIR}/storageclass.yaml"
echo "  ✓ StorageClass 'ceph-rbd' created (default)"

# 6. Verify StorageClass is registered
echo "  Verifying StorageClass..."
for i in $(seq 1 12); do
    if kubectl get storageclass ceph-rbd &>/dev/null; then
        echo "  ✓ StorageClass 'ceph-rbd' registered"
        break
    fi
    echo "  Waiting for StorageClass... ($i/12)"
    sleep 5
done
kubectl get storageclass ceph-rbd &>/dev/null || { echo "Error: ceph-rbd StorageClass not found"; exit 1; }

# 7. Test with a PVC — the definitive operational test
echo "  Testing Ceph CSI with a test PVC..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ceph-rbd-test-pvc
  namespace: ceph-csi
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: ceph-rbd
  resources:
    requests:
      storage: 1Gi
EOF

PVC_BOUND=false
for i in $(seq 1 36); do
    PHASE=$(kubectl get pvc ceph-rbd-test-pvc -n ceph-csi -o jsonpath='{.status.phase}' 2>/dev/null || echo "")
    if [[ "$PHASE" == "Bound" ]]; then
        echo "  ✓ Test PVC bound successfully"
        PVC_BOUND=true
        break
    fi
    echo "  Test PVC phase: ${PHASE:-Pending}... ($i/36)"
    sleep 5
done

if [[ "$PVC_BOUND" != true ]]; then
    echo ""
    echo "  ===== Test PVC failed to bind — diagnostics ====="
    echo ""
    echo "  --- PVC details ---"
    kubectl describe pvc ceph-rbd-test-pvc -n ceph-csi 2>/dev/null || true
    echo ""
    echo "  --- Provisioner logs ---"
    for pod in $(kubectl get pods -n ceph-csi -l app=ceph-csi-rbd-provisioner \
        -o jsonpath='{.items[*].metadata.name}' 2>/dev/null); do
        echo "  >>> $pod <<<"
        kubectl logs "$pod" -n ceph-csi -c csi-rbdplugin --tail=30 2>/dev/null || echo "  (no logs)"
        echo ""
    done
    echo "  --- Recent ceph-csi events ---"
    kubectl get events -n ceph-csi --sort-by='.lastTimestamp' 2>/dev/null | tail -15 || true
fi

# Cleanup test PVC
kubectl delete pvc ceph-rbd-test-pvc -n ceph-csi --ignore-not-found=true &>/dev/null

if [[ "$PVC_BOUND" != true ]]; then
    echo "Error: Test PVC failed to bind — Ceph CSI may not be fully operational"
    exit 1
fi

echo "✓ Ceph CSI RBD fully deployed and operational"
echo ""

# Get LoadBalancer IP
echo "[12/13] Retrieving Traefik LoadBalancer IP..."
sleep 5
TRAEFIK_IP=$(kubectl get svc traefik -n traefik -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "pending")

# Apply IngressRoutes (excluding OpenVAS which will be added later)
echo "[13/13] Applying IngressRoutes..."
kubectl apply -f "${SCRIPT_DIR}/traefik/dashboard-ingressroute.yaml"
kubectl apply -f "${SCRIPT_DIR}/traefik/ingressroutes/argocd-ingressroute.yaml"
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
echo ""
echo "2. Default credentials (CHANGE IN PRODUCTION!):"
echo "   All UIs use: admin / admin"
echo "   - Traefik: update traefik/middlewares.yaml"
echo "   - ArgoCD: update apps/argocd/values.yaml"
echo ""
echo "3. Verify deployment:"
echo "   kubectl top nodes                    # Metrics Server"
echo "   kubectl get pods -n metallb-system"
echo "   kubectl get pods -n cert-manager"
echo "   kubectl get pods -n traefik"
echo "   kubectl get pods -n ceph-csi"
echo "   kubectl get svc -n traefik"
echo ""
echo "4. Access UIs (credentials: admin/admin):"
echo "   - https://traefik.knowledgeondemand.net (Traefik Dashboard)"
echo "   - https://argocd.knowledgeondemand.net (ArgoCD)"
echo ""
echo "5. Verify Ceph CSI storage:"
echo "   kubectl get storageclass"
echo "   kubectl get pods -n ceph-csi"
echo ""
echo "6. Deploy OpenVAS (optional, resource-intensive):"
echo "   After the cluster is stable, run:"
echo "   ./deploy-openvas.sh"
echo ""
