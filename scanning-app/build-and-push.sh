#!/bin/bash
# Build and push Scanning Console image to Harbor private registry.
#
# Build context is the REPO ROOT (not scanning-app/):
#   docker build -f scanning-app/Dockerfile -t scanning-console .
#
# This script handles:
#   1. Waits for Harbor to be reachable
#   2. Creates the "cleanroom" Harbor project (idempotent)
#   3. Creates harbor-pull-secret in the scanning namespace (idempotent)
#   4. Logs into Harbor with Docker
#   5. Builds the scanning console container image
#   6. Pushes the image to Harbor
#
# Prerequisites on the build VM:
#   - Docker installed
#   - kubectl configured with cluster access
#   - curl and jq
#
# Usage:
#   ./build-and-push.sh                    # uses default version v1.0.0
#   ./build-and-push.sh v1.1.0             # specify version tag
#
# Environment variables (optional, avoids prompts):
#   HARBOR_USER       Harbor username       (default: admin)
#   HARBOR_PASSWORD    Harbor admin password
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
VERSION="${1:-v1.0.0}"
HARBOR_HOST="harbor.knowledgeondemand.net"
HARBOR_PROJECT="cleanroom"
IMAGE_NAME="${HARBOR_HOST}/${HARBOR_PROJECT}/scanning-console"
IMAGE_TAG="${VERSION}"

# Find repo root (parent of scanning-app/)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Namespaces that need pull secrets
PULL_SECRET_NAMESPACES=("scanning-console")

echo "=== Scanning Console — Build & Push ==="
echo "Version  : ${VERSION}"
echo "Harbor   : ${HARBOR_HOST}"
echo "Image    : ${IMAGE_NAME}:${IMAGE_TAG}"
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
    exit 1
fi

if ! docker info > /dev/null 2>&1; then
    echo "ERROR: Docker daemon is not running."
    exit 1
fi

if ! kubectl cluster-info --request-timeout=5s > /dev/null 2>&1; then
    echo "ERROR: Cannot reach Kubernetes cluster."
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
echo "--- Step 2: Waiting for Harbor ---"
MAX_WAIT=120
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    HTTP_CODE=$(curl -sk -o /dev/null -w "%{http_code}" \
        "https://${HARBOR_HOST}/api/v2.0/health" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        echo "Harbor is healthy."
        break
    fi
    echo "  Waiting... (${WAITED}s, HTTP ${HTTP_CODE})"
    sleep 5
    WAITED=$((WAITED + 5))
done

if [ $WAITED -ge $MAX_WAIT ]; then
    echo "ERROR: Harbor not reachable after ${MAX_WAIT}s"
    exit 1
fi

# ---------------------------------------------------------------------------
# Step 3: Create Harbor project (idempotent)
# ---------------------------------------------------------------------------
echo ""
echo "--- Step 3: Creating Harbor project '${HARBOR_PROJECT}' ---"
PROJECT_EXISTS=$(curl -sk \
    -u "${HARBOR_USER}:${HARBOR_PASSWORD}" \
    "https://${HARBOR_HOST}/api/v2.0/projects?name=${HARBOR_PROJECT}" \
    | jq 'length')

if [ "${PROJECT_EXISTS}" -gt 0 ] 2>/dev/null; then
    echo "Project '${HARBOR_PROJECT}' already exists."
else
    CREATE_CODE=$(curl -sk -o /dev/null -w "%{http_code}" \
        -u "${HARBOR_USER}:${HARBOR_PASSWORD}" \
        -X POST "https://${HARBOR_HOST}/api/v2.0/projects" \
        -H "Content-Type: application/json" \
        -d "{\"project_name\": \"${HARBOR_PROJECT}\", \"public\": false}")
    if [ "$CREATE_CODE" = "201" ] || [ "$CREATE_CODE" = "409" ]; then
        echo "Project '${HARBOR_PROJECT}' ready."
    else
        echo "ERROR: Failed to create project (HTTP ${CREATE_CODE})."
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# Step 4: Create harbor-pull-secret (idempotent)
# ---------------------------------------------------------------------------
echo ""
echo "--- Step 4: Creating harbor-pull-secret ---"

for NS in "${PULL_SECRET_NAMESPACES[@]}"; do
    kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f - 2>/dev/null

    if kubectl get secret harbor-pull-secret -n "$NS" > /dev/null 2>&1; then
        echo "  [${NS}] harbor-pull-secret exists — updating."
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
# Step 5: Docker login
# ---------------------------------------------------------------------------
echo ""
echo "--- Step 5: Docker login ---"
echo "${HARBOR_PASSWORD}" | docker login "${HARBOR_HOST}" -u "${HARBOR_USER}" --password-stdin

# ---------------------------------------------------------------------------
# Step 6: Build the image (from repo root)
# ---------------------------------------------------------------------------
echo ""
echo "--- Step 6: Building image ---"
docker build \
    -f "${SCRIPT_DIR}/Dockerfile" \
    -t "${IMAGE_NAME}:${IMAGE_TAG}" \
    -t "${IMAGE_NAME}:latest" \
    "${REPO_ROOT}"

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
echo "  Scanning Console — Build Complete"
echo "============================================"
echo ""
echo "  Image: ${IMAGE_NAME}:${IMAGE_TAG}"
echo "  Image: ${IMAGE_NAME}:latest"
echo ""
