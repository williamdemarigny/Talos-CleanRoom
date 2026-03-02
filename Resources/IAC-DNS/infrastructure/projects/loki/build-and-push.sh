#!/bin/bash
# Build and push LOKI-RS scanner image to Harbor private registry.
#
# This script handles the full bootstrap:
#   1. Waits for Harbor to be reachable
#   2. Creates the "cleanroom" Harbor project (idempotent)
#   3. Creates the harbor-pull-secret in the loki-scanner namespace (idempotent)
#   4. Logs into Harbor with Docker
#   5. Builds the LOKI-RS container image
#   6. Pushes the image to Harbor
#
# Prerequisites on the build VM:
#   - Docker installed:  apt-get install docker.io
#   - kubectl configured with cluster access
#   - curl and jq:  apt-get install curl jq
#
# Usage:
#   ./build-and-push.sh                    # uses default version, prompts for password
#   ./build-and-push.sh v2.10.0            # specify LOKI-RS version
#
# Environment variables (optional, avoids prompts):
#   HARBOR_USER       Harbor username       (default: admin)
#   HARBOR_PASSWORD    Harbor admin password
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LOKI_VERSION="${1:-v2.10.0}"
HARBOR_HOST="harbor.knowledgeondemand.net"
HARBOR_PROJECT="cleanroom"
IMAGE_NAME="${HARBOR_HOST}/${HARBOR_PROJECT}/loki-rs-scanner"
IMAGE_TAG="${LOKI_VERSION}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Namespaces that need pull secrets for Harbor images
PULL_SECRET_NAMESPACES=("loki-scanner")

echo "=== LOKI-RS Scanner — Full Bootstrap ==="
echo "LOKI-RS version : ${LOKI_VERSION}"
echo "Harbor           : ${HARBOR_HOST}"
echo "Image            : ${IMAGE_NAME}:${IMAGE_TAG}"
echo ""

# ---------------------------------------------------------------------------
# Step 0: Check prerequisites
# ---------------------------------------------------------------------------
echo "--- Step 0: Checking prerequisites ---"
missing=()
for cmd in docker kubectl curl jq; do
    if ! command -v "$cmd" &> /dev/null; then
        missing+=("$cmd")
    fi
done

if [ ${#missing[@]} -gt 0 ]; then
    echo "ERROR: Missing required tools: ${missing[*]}"
    echo "Install them and try again."
    exit 1
fi

if ! docker info > /dev/null 2>&1; then
    echo "ERROR: Docker daemon is not running. Please start Docker first."
    exit 1
fi

if ! kubectl cluster-info --request-timeout=5s > /dev/null 2>&1; then
    echo "ERROR: Cannot reach Kubernetes cluster. Check your KUBECONFIG."
    exit 1
fi

echo "All prerequisites OK."

# ---------------------------------------------------------------------------
# Step 1: Get Harbor credentials
# ---------------------------------------------------------------------------
echo ""
echo "--- Step 1: Harbor credentials ---"
HARBOR_USER="${HARBOR_USER:-admin}"

if [ -z "${HARBOR_PASSWORD:-}" ]; then
    echo "Harbor username: ${HARBOR_USER}"
    read -rsp "Harbor password: " HARBOR_PASSWORD
    echo ""
fi

if [ -z "${HARBOR_PASSWORD}" ]; then
    echo "ERROR: Harbor password is required."
    exit 1
fi

# ---------------------------------------------------------------------------
# Step 2: Wait for Harbor to be reachable
# ---------------------------------------------------------------------------
echo ""
echo "--- Step 2: Waiting for Harbor to be reachable ---"
MAX_WAIT=120
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    HTTP_CODE=$(curl -sk -o /dev/null -w "%{http_code}" \
        "https://${HARBOR_HOST}/api/v2.0/health" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        echo "Harbor is healthy."
        break
    fi
    echo "  Waiting for Harbor... (${WAITED}s, HTTP ${HTTP_CODE})"
    sleep 5
    WAITED=$((WAITED + 5))
done

if [ $WAITED -ge $MAX_WAIT ]; then
    echo "ERROR: Harbor not reachable at https://${HARBOR_HOST} after ${MAX_WAIT}s"
    exit 1
fi

# ---------------------------------------------------------------------------
# Step 3: Create Harbor project (idempotent)
# ---------------------------------------------------------------------------
echo ""
echo "--- Step 3: Creating Harbor project '${HARBOR_PROJECT}' ---"
PROJECT_CHECK=$(curl -sk -o /dev/null -w "%{http_code}" \
    -u "${HARBOR_USER}:${HARBOR_PASSWORD}" \
    "https://${HARBOR_HOST}/api/v2.0/projects?name=${HARBOR_PROJECT}")

if [ "$PROJECT_CHECK" = "401" ]; then
    echo "ERROR: Harbor authentication failed. Check username/password."
    exit 1
fi

# Try to get the project; if it doesn't exist, create it
PROJECT_EXISTS=$(curl -sk \
    -u "${HARBOR_USER}:${HARBOR_PASSWORD}" \
    "https://${HARBOR_HOST}/api/v2.0/projects?name=${HARBOR_PROJECT}" \
    | jq 'length')

if [ "${PROJECT_EXISTS}" -gt 0 ] 2>/dev/null; then
    echo "Project '${HARBOR_PROJECT}' already exists."
else
    echo "Creating project '${HARBOR_PROJECT}'..."
    CREATE_CODE=$(curl -sk -o /dev/null -w "%{http_code}" \
        -u "${HARBOR_USER}:${HARBOR_PASSWORD}" \
        -X POST "https://${HARBOR_HOST}/api/v2.0/projects" \
        -H "Content-Type: application/json" \
        -d "{
            \"project_name\": \"${HARBOR_PROJECT}\",
            \"public\": false,
            \"metadata\": {
                \"auto_scan\": \"true\"
            }
        }")
    if [ "$CREATE_CODE" = "201" ]; then
        echo "Project '${HARBOR_PROJECT}' created with auto-scan enabled."
    elif [ "$CREATE_CODE" = "409" ]; then
        echo "Project '${HARBOR_PROJECT}' already exists (race condition, OK)."
    else
        echo "ERROR: Failed to create project (HTTP ${CREATE_CODE})."
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# Step 4: Create harbor-pull-secret in target namespaces (idempotent)
# ---------------------------------------------------------------------------
echo ""
echo "--- Step 4: Creating harbor-pull-secret ---"

for NS in "${PULL_SECRET_NAMESPACES[@]}"; do
    # Ensure namespace exists
    kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f - 2>/dev/null

    # Check if secret already exists
    if kubectl get secret harbor-pull-secret -n "$NS" > /dev/null 2>&1; then
        echo "  [${NS}] harbor-pull-secret already exists — updating."
        kubectl delete secret harbor-pull-secret -n "$NS" --ignore-not-found
    fi

    kubectl create secret docker-registry harbor-pull-secret \
        --namespace="$NS" \
        --docker-server="${HARBOR_HOST}" \
        --docker-username="${HARBOR_USER}" \
        --docker-password="${HARBOR_PASSWORD}"
    echo "  [${NS}] harbor-pull-secret created."
done

# ---------------------------------------------------------------------------
# Step 5: Docker login to Harbor
# ---------------------------------------------------------------------------
echo ""
echo "--- Step 5: Docker login ---"
echo "${HARBOR_PASSWORD}" | docker login "${HARBOR_HOST}" -u "${HARBOR_USER}" --password-stdin
echo "Docker authenticated with ${HARBOR_HOST}."

# ---------------------------------------------------------------------------
# Step 6: Build the image
# ---------------------------------------------------------------------------
echo ""
echo "--- Step 6: Building image ---"
docker build \
    --build-arg "LOKI_VERSION=${LOKI_VERSION}" \
    -t "${IMAGE_NAME}:${IMAGE_TAG}" \
    -t "${IMAGE_NAME}:latest" \
    "${SCRIPT_DIR}"

echo ""
echo "Build complete. Image size:"
docker images "${IMAGE_NAME}:${IMAGE_TAG}" --format "{{.Size}}"

# ---------------------------------------------------------------------------
# Step 7: Push to Harbor
# ---------------------------------------------------------------------------
echo ""
echo "--- Step 7: Pushing to Harbor ---"
docker push "${IMAGE_NAME}:${IMAGE_TAG}"
docker push "${IMAGE_NAME}:latest"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo "============================================"
echo "  LOKI-RS Scanner — Bootstrap Complete"
echo "============================================"
echo ""
echo "  Harbor project : ${HARBOR_HOST}/${HARBOR_PROJECT}"
echo "  Image pushed   : ${IMAGE_NAME}:${IMAGE_TAG}"
echo "  Image pushed   : ${IMAGE_NAME}:latest"
echo "  Pull secrets   : ${PULL_SECRET_NAMESPACES[*]}"
echo ""
echo "  Trivy will auto-scan the pushed image in Harbor."
echo "  IOC scans from the WebUI will pull this image automatically."
echo ""
