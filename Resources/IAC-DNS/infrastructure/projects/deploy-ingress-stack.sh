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

# Helper: wait for a deployment to exist and become available via polling.
# Unlike 'kubectl wait', this handles the resource not existing yet gracefully.
wait_for_deployment() {
    local name="$1"
    local namespace="$2"
    local timeout="${3:-300}"
    local elapsed=0
    local interval=10

    local avail
    while [[ $elapsed -lt $timeout ]]; do
        # Check if deployment exists and has available replicas
        avail=$(kubectl get deployment "$name" -n "$namespace" \
            -o jsonpath='{.status.availableReplicas}' 2>/dev/null || echo "")
        if [[ "$avail" =~ ^[1-9] ]]; then
            echo "  ✓ $name is available ($avail replicas)"
            return 0
        fi

        echo "  Waiting for deployment $name in $namespace... (${elapsed}/${timeout}s)"
        sleep "$interval"
        elapsed=$((elapsed + interval))
    done

    echo "  Error: deployment $name in $namespace not available after ${timeout}s"
    # Dump ArgoCD Application status for diagnostics
    echo "  --- ArgoCD Application status ---"
    kubectl get application "$name" -n argocd \
        -o jsonpath='  sync={.status.sync.status} health={.status.health.status} conditions={.status.conditions[*].message}' 2>/dev/null || true
    echo ""
    return 1
}

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
for ns in metallb-system cert-manager traefik longhorn-system; do
    kubectl create namespace "$ns" --dry-run=client -o yaml | kubectl apply -f - 2>/dev/null
done
echo "✓ Namespaces ready"
echo ""

# Deploy MetalLB
echo "[2/10] Deploying MetalLB..."
kubectl apply -f "${SCRIPT_DIR}/metallb/application.yaml"

echo "Waiting for MetalLB to be ready..."
wait_for_deployment metallb-controller metallb-system 300

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
wait_for_deployment cert-manager cert-manager 300

# Wait for webhook to be ready (required before creating issuers)
wait_for_deployment cert-manager-webhook cert-manager 300

echo "✓ cert-manager deployed"
echo ""

# Apply Cloudflare API token secret (required for DNS-01 challenge)
echo "[5/12] Applying Cloudflare API token secret..."
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
echo "[6/12] Configuring ClusterIssuers..."
sleep 5  # Give webhook time to fully initialize
kubectl apply -f "${SCRIPT_DIR}/cert-manager/cluster-issuers.yaml"
echo "✓ ClusterIssuers configured"
echo ""

# Deploy Traefik
echo "[7/12] Deploying Traefik..."
kubectl apply -f "${SCRIPT_DIR}/traefik/application.yaml"

echo "Waiting for Traefik to be ready..."
wait_for_deployment traefik traefik 300

echo "✓ Traefik deployed"
echo ""

# Apply Middlewares
echo "[8/12] Configuring Traefik Middlewares..."
kubectl apply -f "${SCRIPT_DIR}/traefik/middlewares.yaml"
echo "✓ Middlewares configured"
echo ""

# Apply Wildcard Certificate
echo "[9/12] Applying Wildcard Certificate..."
kubectl apply -f "${SCRIPT_DIR}/cert-manager/wildcard-certificate.yaml"
echo "✓ Wildcard certificate applied (uses letsencrypt-staging by default)"
echo "  Note: Switch to letsencrypt-prod after testing"
echo ""

# Deploy Longhorn
echo "[10/12] Deploying Longhorn..."
# Create PriorityClass before Longhorn — the Helm chart references it but doesn't create it
kubectl apply -f "${SCRIPT_DIR}/longhorn/priority-class.yaml"
kubectl apply -f "${SCRIPT_DIR}/longhorn/application.yaml"

echo "Waiting for Longhorn to be ready..."

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
if [[ "$READY" -ne "$DESIRED" || "$DESIRED" -eq 0 ]]; then
    echo ""
    echo "  ===== longhorn-manager DaemonSet not fully ready ($READY/$DESIRED) ====="
    echo ""
    echo "  --- All longhorn-manager pods (node placement + status) ---"
    kubectl get pods -n longhorn-system -l app=longhorn-manager -o wide 2>/dev/null || true
    echo ""
    echo "  --- Non-running pods detail ---"
    for pod in $(kubectl get pods -n longhorn-system -l app=longhorn-manager \
        --field-selector=status.phase!=Running -o name 2>/dev/null); do
        echo "  >>> $pod <<<"
        kubectl describe "$pod" -n longhorn-system 2>/dev/null | tail -20
        echo ""
    done
    echo "  --- Container logs from crash-looping pods ---"
    for pod in $(kubectl get pods -n longhorn-system -l app=longhorn-manager \
        -o jsonpath='{.items[*].metadata.name}' 2>/dev/null); do
        echo "  >>> $pod (last 30 lines) <<<"
        kubectl logs "$pod" -n longhorn-system --tail=30 2>/dev/null || \
            kubectl logs "$pod" -n longhorn-system --previous --tail=30 2>/dev/null || \
            echo "  (no logs available)"
        echo ""
    done
    echo "  --- Kubernetes node conditions ---"
    kubectl get nodes -o wide 2>/dev/null || true
    echo ""
    echo "  --- Recent longhorn-system events (warnings/errors) ---"
    kubectl get events -n longhorn-system --field-selector type!=Normal \
        --sort-by='.lastTimestamp' 2>/dev/null | tail -10 || true
    echo ""
    echo "  Troubleshooting tips:"
    echo "    - Check if the failing node's /dev/vdb disk exists: talosctl -n <node-ip> disks"
    echo "    - Check mount status: talosctl -n <node-ip> get mounts | grep longhorn"
    echo "    - Check kubelet logs: talosctl -n <node-ip> logs kubelet | grep -i longhorn"
    echo "    - Check loaded kernel modules: talosctl -n <node-ip> read /proc/modules | grep iscsi"
    exit 1
fi

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
    if [[ "$FOUND" != true ]]; then
        echo ""
        echo "  ===== CSI component ${component} not available — diagnostics ====="
        echo ""
        echo "  --- All deployments in longhorn-system ---"
        kubectl get deployments -n longhorn-system -o wide 2>/dev/null || true
        echo ""
        echo "  --- longhorn-driver-deployer pod status ---"
        kubectl get pods -n longhorn-system -l app=longhorn-driver-deployer -o wide 2>/dev/null || true
        echo ""
        echo "  --- longhorn-driver-deployer logs ---"
        for pod in $(kubectl get pods -n longhorn-system -l app=longhorn-driver-deployer \
            -o jsonpath='{.items[*].metadata.name}' 2>/dev/null); do
            echo "  >>> $pod <<<"
            kubectl logs "$pod" -n longhorn-system --tail=40 2>/dev/null || echo "  (no logs)"
        done
        echo ""
        echo "  --- CSI-related pods ---"
        kubectl get pods -n longhorn-system 2>/dev/null | grep -E "csi|driver" || echo "  (none found)"
        echo ""
        echo "  --- Recent longhorn-system events (warnings) ---"
        kubectl get events -n longhorn-system --field-selector type!=Normal \
            --sort-by='.lastTimestamp' 2>/dev/null | tail -15 || true
        echo ""
        echo "  --- ArgoCD Application status for longhorn ---"
        kubectl get application longhorn -n argocd \
            -o jsonpath='  sync={.status.sync.status} health={.status.health.status}' 2>/dev/null || true
        echo ""
        kubectl get application longhorn -n argocd \
            -o jsonpath='{.status.conditions[*].message}' 2>/dev/null || true
        echo ""
        exit 1
    fi
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
if [[ "$READY" -ne "$DESIRED" || "$DESIRED" -eq 0 ]]; then
    echo "  Error: longhorn-csi-plugin not fully ready ($READY/$DESIRED)"
    kubectl get pods -n longhorn-system -l app=longhorn-csi-plugin -o wide 2>/dev/null || true
    exit 1
fi

# 4. Wait for Longhorn UI
echo "  Waiting for Longhorn UI..."
wait_for_deployment longhorn-ui longhorn-system 300

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

# 8. Wait for Longhorn nodes to have schedulable disk storage
# Nodes can report "ready" before their disks are fully discovered and initialized.
# With defaultReplicaCount=2, we need at least 2 nodes with schedulable storage.
echo "  Waiting for Longhorn node disks to become schedulable..."
MIN_SCHEDULABLE=2
for i in $(seq 1 36); do
    SCHEDULABLE=$(kubectl get nodes.longhorn.io -n longhorn-system -o json 2>/dev/null | \
        python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    count = 0
    for node in data.get('items', []):
        disks = node.get('status', {}).get('diskStatus', {})
        for disk_id, disk in disks.items():
            conditions = disk.get('conditions', {})
            schedulable = conditions.get('Schedulable', {})
            if schedulable.get('status') == 'True':
                storage = disk.get('storageAvailable', 0)
                if storage > 0:
                    count += 1
                    break
    print(count)
except:
    print(0)
" 2>/dev/null || echo "0")
    if [[ "$SCHEDULABLE" -ge "$MIN_SCHEDULABLE" ]]; then
        echo "  ✓ $SCHEDULABLE Longhorn nodes have schedulable disk storage"
        break
    fi
    echo "  Schedulable nodes: $SCHEDULABLE/$MIN_SCHEDULABLE... ($i/36)"
    sleep 10
done
if [[ "$SCHEDULABLE" -lt "$MIN_SCHEDULABLE" ]]; then
    echo "  Warning: Only $SCHEDULABLE/$MIN_SCHEDULABLE nodes have schedulable storage"
    echo "  --- Longhorn node disk status ---"
    kubectl get nodes.longhorn.io -n longhorn-system -o json 2>/dev/null | \
        python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    for node in data.get('items', []):
        name = node['metadata']['name']
        disks = node.get('status', {}).get('diskStatus', {})
        print(f'  Node: {name}')
        if not disks:
            print(f'    No disks registered')
        for disk_id, disk in disks.items():
            conditions = disk.get('conditions', {})
            schedulable = conditions.get('Schedulable', {}).get('status', 'Unknown')
            ready = conditions.get('Ready', {}).get('status', 'Unknown')
            avail = disk.get('storageAvailable', 0)
            total = disk.get('storageMaximum', 0)
            print(f'    Disk {disk_id}: schedulable={schedulable} ready={ready} avail={avail/(1024**3):.1f}Gi total={total/(1024**3):.1f}Gi')
except Exception as e:
    print(f'  (parse error: {e})')
" 2>/dev/null || echo "  (could not parse node status)"
fi

# 9. Verify the Longhorn StorageClass exists — confirms CSI is registered (was step 8)
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

# 10. Create and verify a test PVC — the definitive operational test
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

# Wait for PVC to bind (up to 3 minutes)
PVC_BOUND=false
for i in $(seq 1 36); do
    PHASE=$(kubectl get pvc longhorn-test-pvc -n longhorn-system -o jsonpath='{.status.phase}' 2>/dev/null || echo "")
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
    kubectl describe pvc longhorn-test-pvc -n longhorn-system 2>/dev/null || true
    echo ""
    echo "  --- Longhorn volumes ---"
    kubectl get volumes.longhorn.io -n longhorn-system 2>/dev/null || true
    echo ""
    echo "  --- Longhorn node disk status ---"
    kubectl get nodes.longhorn.io -n longhorn-system -o json 2>/dev/null | \
        python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    for node in data.get('items', []):
        name = node['metadata']['name']
        allow = node.get('spec', {}).get('allowScheduling', False)
        disks_spec = node.get('spec', {}).get('disks', {})
        disks_status = node.get('status', {}).get('diskStatus', {})
        print(f'  Node: {name}  allowScheduling={allow}')
        if not disks_spec and not disks_status:
            print(f'    No disks configured or detected')
        for disk_id in set(list(disks_spec.keys()) + list(disks_status.keys())):
            spec = disks_spec.get(disk_id, {})
            status = disks_status.get(disk_id, {})
            path = spec.get('path', 'unknown')
            sched = spec.get('allowScheduling', False)
            conditions = status.get('conditions', {})
            s_sched = conditions.get('Schedulable', {}).get('status', 'Unknown')
            s_ready = conditions.get('Ready', {}).get('status', 'Unknown')
            s_reason = conditions.get('Schedulable', {}).get('reason', '')
            avail = status.get('storageAvailable', 0)
            total = status.get('storageMaximum', 0)
            print(f'    Disk {disk_id}: path={path} allowScheduling={sched}')
            print(f'      schedulable={s_sched} ready={s_ready} reason={s_reason}')
            print(f'      available={avail/(1024**3):.1f}Gi total={total/(1024**3):.1f}Gi')
except Exception as e:
    print(f'  (parse error: {e})')
" 2>/dev/null || echo "  (could not parse node status)"
    echo ""
    echo "  --- Recent longhorn-system events ---"
    kubectl get events -n longhorn-system --sort-by='.lastTimestamp' 2>/dev/null | tail -15 || true
    echo ""
    echo "  --- Longhorn manager logs (last 20 lines per pod) ---"
    for pod in $(kubectl get pods -n longhorn-system -l app=longhorn-manager \
        -o jsonpath='{.items[*].metadata.name}' 2>/dev/null); do
        echo "  >>> $pod <<<"
        kubectl logs "$pod" -n longhorn-system --tail=20 2>/dev/null || echo "  (no logs)"
        echo ""
    done
fi

# Cleanup test PVC regardless of result
kubectl delete pvc longhorn-test-pvc -n longhorn-system --ignore-not-found=true &>/dev/null

if [[ "$PVC_BOUND" != true ]]; then
    echo "Error: Test PVC failed to bind - Longhorn may not be fully operational"
    exit 1
fi

echo "✓ Longhorn fully deployed and operational"
echo ""

# Get LoadBalancer IP
echo "[11/12] Retrieving Traefik LoadBalancer IP..."
sleep 5
TRAEFIK_IP=$(kubectl get svc traefik -n traefik -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "pending")

# Apply IngressRoutes (excluding OpenVAS which will be added later)
echo "[12/12] Applying IngressRoutes..."
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
