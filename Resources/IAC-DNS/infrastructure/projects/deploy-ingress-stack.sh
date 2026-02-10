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
sleep 15  # Give ArgoCD time to create namespace and initial resources

# Wait for the longhorn-system namespace to exist (ArgoCD creates it)
for i in $(seq 1 12); do
    kubectl get namespace longhorn-system &>/dev/null && break
    echo "  Waiting for longhorn-system namespace... ($i/12)"
    sleep 10
done
kubectl get namespace longhorn-system || { echo "Error: longhorn-system namespace never created"; exit 1; }

# 1. Wait for longhorn-manager DaemonSet — one pod per node, core of Longhorn
echo "  Waiting for longhorn-manager DaemonSet..."
for i in $(seq 1 36); do
    DESIRED=$(kubectl get daemonset longhorn-manager -n longhorn-system -o jsonpath='{.status.desiredNumberScheduled}' 2>/dev/null || echo "0")
    READY=$(kubectl get daemonset longhorn-manager -n longhorn-system -o jsonpath='{.status.numberReady}' 2>/dev/null || echo "0")
    if [[ "$DESIRED" -gt 0 && "$READY" -eq "$DESIRED" ]]; then
        echo "  ✓ longhorn-manager: $READY/$DESIRED pods ready"
        break
    fi
    echo "  longhorn-manager: $READY/$DESIRED ready... ($i/36)"
    sleep 10
done
[[ "$READY" -eq "$DESIRED" && "$DESIRED" -gt 0 ]] || { echo "Error: longhorn-manager DaemonSet never became ready"; exit 1; }

# 2. Poll for CSI controllers (created by longhorn-driver-deployer after manager is ready)
echo "  Waiting for Longhorn CSI controllers..."
for component in csi-attacher csi-provisioner csi-resizer csi-snapshotter; do
    # Poll until the deployment exists and is available (up to 6 min)
    FOUND=false
    for i in $(seq 1 36); do
        REPLICAS=$(kubectl get deployment ${component} -n longhorn-system -o jsonpath='{.status.availableReplicas}' 2>/dev/null || echo "")
        if [[ "$REPLICAS" =~ ^[1-9] ]]; then
            echo "  ✓ ${component} ready ($REPLICAS replicas available)"
            FOUND=true
            break
        fi
        echo "  Waiting for ${component}... ($i/36)"
        sleep 10
    done
    [[ "$FOUND" == true ]] || { echo "Error: ${component} deployment never became available"; exit 1; }
done

# 3. Wait for longhorn-csi-plugin DaemonSet — per-node volume mount driver
echo "  Waiting for longhorn-csi-plugin DaemonSet..."
for i in $(seq 1 36); do
    DESIRED=$(kubectl get daemonset longhorn-csi-plugin -n longhorn-system -o jsonpath='{.status.desiredNumberScheduled}' 2>/dev/null || echo "0")
    READY=$(kubectl get daemonset longhorn-csi-plugin -n longhorn-system -o jsonpath='{.status.numberReady}' 2>/dev/null || echo "0")
    if [[ "$DESIRED" -gt 0 && "$READY" -eq "$DESIRED" ]]; then
        echo "  ✓ longhorn-csi-plugin: $READY/$DESIRED pods ready"
        break
    fi
    echo "  longhorn-csi-plugin: $READY/$DESIRED ready... ($i/36)"
    sleep 10
done
[[ "$READY" -eq "$DESIRED" && "$DESIRED" -gt 0 ]] || { echo "Error: longhorn-csi-plugin DaemonSet never became ready"; exit 1; }

# 4. Wait for Longhorn UI
echo "  Waiting for Longhorn UI..."
kubectl wait --for=condition=available deployment/longhorn-ui \
    -n longhorn-system \
    --timeout=300s 2>/dev/null || {
    echo "  Waiting for longhorn-ui deployment to be created..."
    sleep 30
    kubectl wait --for=condition=available deployment/longhorn-ui \
        -n longhorn-system \
        --timeout=300s
}
echo "  ✓ longhorn-ui ready"

# 5. Verify Longhorn webhook configurations exist (webhooks are built into longhorn-manager)
echo "  Verifying Longhorn webhooks..."
for webhook in longhorn-webhook-mutator longhorn-webhook-validator; do
    if kubectl get mutatingwebhookconfiguration ${webhook} &>/dev/null || \
       kubectl get validatingwebhookconfiguration ${webhook} &>/dev/null; then
        echo "  ✓ ${webhook} configured"
    else
        echo "  Note: ${webhook} not found (webhooks built into longhorn-manager in v1.7+)"
    fi
done

# 6. Verify Engine Image is deployed on all nodes
echo "  Verifying Longhorn engine image..."
for i in $(seq 1 24); do
    STATE=$(kubectl get engineimages.longhorn.io -n longhorn-system -o jsonpath='{.items[0].status.state}' 2>/dev/null || echo "")
    if [[ "$STATE" == "deployed" ]]; then
        echo "  ✓ Engine image deployed"
        break
    fi
    echo "  Engine image state: ${STATE:-pending}... ($i/24)"
    sleep 5
done
[[ "$STATE" == "deployed" ]] || { echo "Error: Longhorn engine image never became deployed"; exit 1; }

# 7. Verify Longhorn nodes are registered and schedulable
echo "  Verifying Longhorn nodes..."
WORKER_NODES=$(kubectl get nodes --no-headers -l '!node-role.kubernetes.io/control-plane' 2>/dev/null | wc -l || echo "0")
if [[ "$WORKER_NODES" -eq 0 ]]; then
    WORKER_NODES=$(kubectl get nodes --no-headers 2>/dev/null | wc -l || echo "1")
fi
for i in $(seq 1 24); do
    READY_NODES=$(kubectl get nodes.longhorn.io -n longhorn-system --no-headers 2>/dev/null | grep -c "True" || echo "0")
    if [[ "$READY_NODES" -ge "$WORKER_NODES" ]]; then
        echo "  ✓ All $READY_NODES Longhorn nodes ready"
        break
    fi
    echo "  Longhorn nodes: $READY_NODES/$WORKER_NODES ready... ($i/24)"
    sleep 5
done
[[ "$READY_NODES" -ge "$WORKER_NODES" ]] || { echo "Warning: Not all Longhorn nodes are ready ($READY_NODES/$WORKER_NODES)"; }

# 8. Verify the Longhorn StorageClass exists — confirms CSI is registered
echo "  Verifying Longhorn StorageClass..."
for i in $(seq 1 12); do
    if kubectl get storageclass longhorn &>/dev/null; then
        echo "  ✓ StorageClass 'longhorn' registered"
        break
    fi
    echo "  Waiting for StorageClass... ($i/12)"
    sleep 10
done
kubectl get storageclass longhorn || { echo "Error: Longhorn StorageClass never appeared"; exit 1; }

# 9. Create and verify a test PVC — the definitive operational test
echo "  Testing Longhorn with a test PVC..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: longhorn-test-pvc
  namespace: longhorn-system
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: longhorn
  resources:
    requests:
      storage: 1Gi
EOF

# Wait for PVC to bind (up to 2 minutes)
PVC_BOUND=false
for i in $(seq 1 24); do
    PHASE=$(kubectl get pvc longhorn-test-pvc -n longhorn-system -o jsonpath='{.status.phase}' 2>/dev/null || echo "")
    if [[ "$PHASE" == "Bound" ]]; then
        echo "  ✓ Test PVC bound successfully"
        PVC_BOUND=true
        break
    fi
    echo "  Test PVC phase: ${PHASE:-Pending}... ($i/24)"
    sleep 5
done

# Cleanup test PVC regardless of result
kubectl delete pvc longhorn-test-pvc -n longhorn-system --ignore-not-found=true &>/dev/null

if [[ "$PVC_BOUND" != true ]]; then
    echo "Error: Test PVC failed to bind - Longhorn may not be fully operational"
    exit 1
fi

echo "✓ Longhorn fully deployed and operational"
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
