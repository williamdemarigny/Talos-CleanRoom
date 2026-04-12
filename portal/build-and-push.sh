#!/bin/bash
# Build and push Portal image to Harbor private registry.
#
# Build context is the REPO ROOT (not portal/):
#   docker build -f portal/Dockerfile -t portal .
#
# Usage:
#   ./build-and-push.sh                    # uses default version v1.0.0
#   ./build-and-push.sh v1.1.0             # specify version tag
#
# Environment variables (optional):
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
IMAGE_NAME="${HARBOR_HOST}/${HARBOR_PROJECT}/portal"
IMAGE_TAG="${VERSION}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PULL_SECRET_NAMESPACES=("portal")

echo "=== Portal — Build & Push ==="
echo "Version  : ${VERSION}"
echo "Image    : ${IMAGE_NAME}:${IMAGE_TAG}"
echo ""

# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------
echo "--- Checking prerequisites ---"
for cmd in docker kubectl curl jq; do
    if ! command -v "$cmd" &> /dev/null; then
        echo "ERROR: Missing: $cmd"
        exit 1
    fi
done

# ---------------------------------------------------------------------------
# Harbor credentials
# ---------------------------------------------------------------------------
HARBOR_USER="${HARBOR_USER:-admin}"
if [ -z "${HARBOR_PASSWORD:-}" ]; then
    echo "Harbor username: ${HARBOR_USER}"
    read -rsp "Harbor password: " HARBOR_PASSWORD
    echo ""
fi

[ -z "${HARBOR_PASSWORD}" ] && { echo "ERROR: Password required."; exit 1; }

# ---------------------------------------------------------------------------
# Wait for Harbor
# ---------------------------------------------------------------------------
echo "--- Waiting for Harbor ---"
MAX_WAIT=120
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    HTTP_CODE=$(curl -sk -o /dev/null -w "%{http_code}" \
        "https://${HARBOR_HOST}/api/v2.0/health" 2>/dev/null || echo "000")
    [ "$HTTP_CODE" = "200" ] && { echo "Harbor is healthy."; break; }
    echo "  Waiting... (${WAITED}s)"
    sleep 5
    WAITED=$((WAITED + 5))
done
[ $WAITED -ge $MAX_WAIT ] && { echo "ERROR: Harbor not reachable."; exit 1; }

# ---------------------------------------------------------------------------
# Ensure Harbor project
# ---------------------------------------------------------------------------
echo "--- Ensuring Harbor project '${HARBOR_PROJECT}' ---"
PROJECT_EXISTS=$(curl -sk \
    -u "${HARBOR_USER}:${HARBOR_PASSWORD}" \
    "https://${HARBOR_HOST}/api/v2.0/projects?name=${HARBOR_PROJECT}" \
    | jq 'length')

if [ "${PROJECT_EXISTS}" -gt 0 ] 2>/dev/null; then
    echo "Project exists."
else
    curl -sk -o /dev/null -w "" \
        -u "${HARBOR_USER}:${HARBOR_PASSWORD}" \
        -X POST "https://${HARBOR_HOST}/api/v2.0/projects" \
        -H "Content-Type: application/json" \
        -d "{\"project_name\": \"${HARBOR_PROJECT}\", \"public\": false}"
    echo "Project created."
fi

# ---------------------------------------------------------------------------
# Pull secrets
# ---------------------------------------------------------------------------
echo "--- Creating harbor-pull-secret ---"
for NS in "${PULL_SECRET_NAMESPACES[@]}"; do
    kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f - 2>/dev/null
    kubectl delete secret harbor-pull-secret -n "$NS" --ignore-not-found 2>/dev/null
    kubectl create secret docker-registry harbor-pull-secret \
        --namespace="$NS" \
        --docker-server="${HARBOR_HOST}" \
        --docker-username="${HARBOR_USER}" \
        --docker-password="${HARBOR_PASSWORD}"
    echo "  [${NS}] done."
done

# ---------------------------------------------------------------------------
# Docker login + Build + Push
# ---------------------------------------------------------------------------
echo "--- Docker login ---"
echo "${HARBOR_PASSWORD}" | docker login "${HARBOR_HOST}" -u "${HARBOR_USER}" --password-stdin

echo "--- Building image ---"
docker build \
    -f "${SCRIPT_DIR}/Dockerfile" \
    -t "${IMAGE_NAME}:${IMAGE_TAG}" \
    -t "${IMAGE_NAME}:latest" \
    "${REPO_ROOT}"

echo "--- Pushing to Harbor ---"
docker push "${IMAGE_NAME}:${IMAGE_TAG}"
docker push "${IMAGE_NAME}:latest"

echo ""
echo "=== Portal Build Complete ==="
echo "  Image: ${IMAGE_NAME}:${IMAGE_TAG}"
echo ""
