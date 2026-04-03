#!/bin/bash
# Mirror all Greenbone Community Edition images to Harbor private registry.
#
# Eliminates the external dependency on registry.community.greenbone.net
# so that pod restarts and deployments don't fail due to upstream CDN issues.
#
# This script handles:
#   1. Waits for Harbor to be reachable
#   2. Creates the "cleanroom" Harbor project (idempotent)
#   3. Creates harbor-pull-secret in the openvas namespace (idempotent)
#   4. Logs into Harbor with Docker
#   5. Pulls all Greenbone images from upstream
#   6. Tags and pushes them to Harbor
#
# Prerequisites (run on the build VM — VMID 201):
#   - Docker installed
#   - kubectl configured with cluster access
#   - curl and jq
#
# Usage:
#   ./mirror-greenbone.sh                    # pull, tag, push all images
#   ./mirror-greenbone.sh --dry-run          # show what would be done
#
# Environment variables (optional, avoids prompts):
#   HARBOR_USER       Harbor username       (default: admin)
#   HARBOR_PASSWORD    Harbor admin password
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
HARBOR_HOST="harbor.knowledgeondemand.net"
HARBOR_PROJECT="cleanroom"
SOURCE_REGISTRY="registry.community.greenbone.net/community"
DEST_REGISTRY="${HARBOR_HOST}/${HARBOR_PROJECT}"
DRY_RUN=false

if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "=== DRY RUN — no images will be pulled or pushed ==="
    echo ""
fi

# All unique Greenbone images used in greenbone-deployment.yaml.
# Format: "source_name:source_tag:dest_name:dest_tag"
#
# Feed images (data containers — updated frequently):
#   These use no tag upstream (defaults to :latest). We mirror as :latest.
#
# Service images (long-running processes):
#   These use :stable upstream. We mirror as :stable.
#
IMAGES=(
    # Feed / data init containers (no upstream tag = latest)
    "vulnerability-tests::vulnerability-tests:latest"
    "notus-data::notus-data:latest"
    "scap-data::scap-data:latest"
    "cert-bund-data::cert-bund-data:latest"
    "dfn-cert-data::dfn-cert-data:latest"
    "data-objects::data-objects:latest"
    "report-formats::report-formats:latest"
    "gpg-data::gpg-data:latest"
    "redis-server::redis-server:latest"
    # Service containers (:stable upstream)
    "pg-gvm:stable:pg-gvm:stable"
    "gvmd:stable:gvmd:stable"
    "openvas-scanner:stable:openvas-scanner:stable"
    "ospd-openvas:stable:ospd-openvas:stable"
    "gsa:stable:gsa:stable"
)

PULL_SECRET_NAMESPACES=("openvas")

echo "=== Greenbone → Harbor Mirror ==="
echo "Source registry : ${SOURCE_REGISTRY}"
echo "Dest registry   : ${DEST_REGISTRY}"
echo "Images to mirror: ${#IMAGES[@]}"
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
echo "--- Step 3: Ensuring Harbor project '${HARBOR_PROJECT}' exists ---"
PROJECT_CHECK=$(curl -sk -o /dev/null -w "%{http_code}" \
    -u "${HARBOR_USER}:${HARBOR_PASSWORD}" \
    "https://${HARBOR_HOST}/api/v2.0/projects?name=${HARBOR_PROJECT}")

if [ "$PROJECT_CHECK" = "401" ]; then
    echo "ERROR: Harbor authentication failed. Check username/password."
    exit 1
fi

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
        echo "Project '${HARBOR_PROJECT}' created."
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
    kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f - 2>/dev/null

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
# Step 6: Pull, tag, and push each image
# ---------------------------------------------------------------------------
echo ""
echo "--- Step 6: Mirroring images ---"

FAILED=()
SUCCEEDED=0

for entry in "${IMAGES[@]}"; do
    IFS=':' read -r src_name src_tag dest_name dest_tag <<< "$entry"

    if [ -n "$src_tag" ]; then
        SRC="${SOURCE_REGISTRY}/${src_name}:${src_tag}"
    else
        SRC="${SOURCE_REGISTRY}/${src_name}"
    fi
    DST="${DEST_REGISTRY}/${dest_name}:${dest_tag}"

    echo ""
    echo "  [${dest_name}:${dest_tag}]"
    echo "    src: ${SRC}"
    echo "    dst: ${DST}"

    if $DRY_RUN; then
        echo "    (dry-run — skipping)"
        continue
    fi

    if docker pull "$SRC"; then
        docker tag "$SRC" "$DST"
        if docker push "$DST"; then
            echo "    OK"
            SUCCEEDED=$((SUCCEEDED + 1))
        else
            echo "    FAILED (push)"
            FAILED+=("$dest_name:$dest_tag")
        fi
    else
        echo "    FAILED (pull)"
        FAILED+=("$dest_name:$dest_tag")
    fi
done

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "============================================"
echo "  Greenbone → Harbor Mirror Complete"
echo "============================================"
echo ""
echo "  Succeeded: ${SUCCEEDED}/${#IMAGES[@]}"

if [ ${#FAILED[@]} -gt 0 ]; then
    echo "  Failed:    ${#FAILED[@]}"
    for f in "${FAILED[@]}"; do
        echo "    - ${f}"
    done
    echo ""
    echo "  Re-run this script to retry failed images."
    exit 1
else
    echo "  Failed:    0"
fi

echo ""
echo "  Next step: Ensure greenbone-deployment.yaml uses Harbor image refs."
echo "  All images: ${DEST_REGISTRY}/<name>:<tag>"
echo ""
