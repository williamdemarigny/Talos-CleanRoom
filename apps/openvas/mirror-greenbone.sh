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
#   5. Skips images already present in Harbor (idempotent re-runs)
#   6. Pulls from multiple upstream registries with retry + fallback
#   7. Tags and pushes to Harbor
#
# Prerequisites (run on the build VM - VMID 201):
#   - Docker installed
#   - kubectl configured with cluster access
#   - curl and jq
#
# Usage:
#   ./mirror-greenbone.sh                    # pull, tag, push all images
#   ./mirror-greenbone.sh --dry-run          # show what would be done
#   ./mirror-greenbone.sh --force            # re-pull even if already in Harbor
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
DEST_REGISTRY="${HARBOR_HOST}/${HARBOR_PROJECT}"
DRY_RUN=false
FORCE=false

# Upstream registries in priority order.
# Each is tried with retries before moving to the next.
SOURCE_REGISTRIES=(
    "registry.community.greenbone.net/community"
    "ghcr.io/greenbone"
    "docker.io/greenbone"
)

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true; echo "=== DRY RUN ===" ;;
        --force)   FORCE=true;   echo "=== FORCE MODE — re-pulling all ===" ;;
    esac
done

# Greenbone images mirrored to Harbor.
# Format: "source_name:source_tag:dest_name:dest_tag"
#
# ALL Greenbone images are mirrored — the upstream CDN is unreliable.
# The deployment manifest references Harbor exclusively.
#
# NOTE: The :stable tag on the Greenbone registry has known corrupted blobs.
# For ospd-openvas and openvas-scanner, we pull specific version tags and
# tag them as :stable in Harbor. Update the version tags below when upgrading.
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
    "redis-server::redis-server:latest"
    "gpg-data::gpg-data:latest"
    # Service containers (:stable upstream, or pinned version if :stable is broken)
    "pg-gvm:stable:pg-gvm:stable"
    "gvmd:stable:gvmd:stable"
    "gsa:stable:gsa:stable"
    "openvas-scanner:stable:openvas-scanner:stable"
    "ospd-openvas:stable:ospd-openvas:stable"
)

# Fallback version tags — used when the :stable tag has corrupted layers.
# skopeo in-cluster mirror uses these directly (see mirror-greenbone-incluster.sh).
OSPD_OPENVAS_VERSION="v22.9.1-amd64"
OPENVAS_SCANNER_VERSION="v23.41.3-amd64"

PULL_SECRET_NAMESPACES=("openvas")

echo "=== Greenbone -> Harbor Mirror ==="
echo "Source registries: ${SOURCE_REGISTRIES[*]}"
echo "Dest registry   : ${DEST_REGISTRY}"
echo "Images to mirror: ${#IMAGES[@]}"
echo ""

# ---------------------------------------------------------------------------
# Helper: check if image:tag exists in Harbor
# ---------------------------------------------------------------------------
harbor_image_exists() {
    local repo="$1" tag="$2"
    local http_code
    http_code=$(curl -sk -o /dev/null -w "%{http_code}" \
        -u "${HARBOR_USER}:${HARBOR_PASSWORD}" \
        "https://${HARBOR_HOST}/api/v2.0/projects/${HARBOR_PROJECT}/repositories/${repo}/artifacts?q=tags%3D${tag}&page_size=1" \
        2>/dev/null || echo "000")
    if [ "$http_code" = "200" ]; then
        local count
        count=$(curl -sk \
            -u "${HARBOR_USER}:${HARBOR_PASSWORD}" \
            "https://${HARBOR_HOST}/api/v2.0/projects/${HARBOR_PROJECT}/repositories/${repo}/artifacts?q=tags%3D${tag}&page_size=1" \
            2>/dev/null | jq 'length' 2>/dev/null || echo "0")
        [ "$count" -gt 0 ] 2>/dev/null
    else
        return 1
    fi
}

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
SKIPPED=0

for entry in "${IMAGES[@]}"; do
    IFS=':' read -r src_name src_tag dest_name dest_tag <<< "$entry"

    DST="${DEST_REGISTRY}/${dest_name}:${dest_tag}"

    echo ""
    echo "  [${dest_name}:${dest_tag}]"

    if $DRY_RUN; then
        echo "    (dry-run — skipping)"
        continue
    fi

    # Check if image already exists in Harbor (skip re-pull unless --force)
    if ! $FORCE && harbor_image_exists "$dest_name" "$dest_tag"; then
        echo "    already in Harbor — skipping (use --force to re-pull)"
        SKIPPED=$((SKIPPED + 1))
        SUCCEEDED=$((SUCCEEDED + 1))
        continue
    fi

    # Try each source registry with retries per registry
    IMAGE_OK=false
    for registry in "${SOURCE_REGISTRIES[@]}"; do
        if [ -n "$src_tag" ]; then
            SRC="${registry}/${src_name}:${src_tag}"
        else
            SRC="${registry}/${src_name}"
        fi
        echo "    trying: ${SRC}"

        for attempt in 1 2 3; do
            if [ $attempt -gt 1 ]; then
                WAIT=$((attempt * 15))
                echo "    retry ${attempt}/3 after ${WAIT}s..."
                sleep $WAIT
            fi

            PULL_OUTPUT=$(docker pull "$SRC" 2>&1) && PULL_OK=true || PULL_OK=false

            if $PULL_OK; then
                docker tag "$SRC" "$DST"
                if docker push "$DST" 2>&1; then
                    echo "    OK (from ${registry})"
                    SUCCEEDED=$((SUCCEEDED + 1))
                    IMAGE_OK=true
                    break 2  # break both loops
                else
                    echo "    FAILED push (attempt ${attempt}/3) — trying buildx manifest copy"
                    if docker buildx imagetools create --tag "$DST" "$SRC" 2>&1; then
                        echo "    OK via buildx (from ${registry})"
                        SUCCEEDED=$((SUCCEEDED + 1))
                        IMAGE_OK=true
                        break 2
                    else
                        echo "    FAILED buildx push (attempt ${attempt}/3)"
                    fi
                fi
            else
                # Show the actual error from Docker for diagnostics
                LAST_LINE=$(echo "$PULL_OUTPUT" | tail -1)
                echo "    FAILED pull (attempt ${attempt}/3): ${LAST_LINE}"
            fi
        done

        echo "    exhausted retries for ${registry}"
    done

    # Fallback: if :stable tag failed, try pinned version tag (avoids corrupted layers)
    if ! $IMAGE_OK; then
        FALLBACK_TAG=""
        case "$src_name" in
            ospd-openvas)    FALLBACK_TAG="$OSPD_OPENVAS_VERSION" ;;
            openvas-scanner) FALLBACK_TAG="$OPENVAS_SCANNER_VERSION" ;;
        esac

        if [ -n "$FALLBACK_TAG" ]; then
            echo "    trying fallback version tag: ${FALLBACK_TAG}"
            FALLBACK_SRC="${SOURCE_REGISTRIES[0]}/${src_name}:${FALLBACK_TAG}"
            echo "    trying: ${FALLBACK_SRC}"

            for attempt in 1 2 3; do
                if [ $attempt -gt 1 ]; then
                    WAIT=$((attempt * 15))
                    echo "    fallback retry ${attempt}/3 after ${WAIT}s..."
                    sleep $WAIT
                fi

                PULL_OUTPUT=$(docker pull "$FALLBACK_SRC" 2>&1) && PULL_OK=true || PULL_OK=false
                if $PULL_OK; then
                    docker tag "$FALLBACK_SRC" "$DST"
                    if docker push "$DST" 2>&1; then
                        echo "    OK (from fallback ${FALLBACK_TAG})"
                        SUCCEEDED=$((SUCCEEDED + 1))
                        IMAGE_OK=true
                        break
                    else
                        echo "    FAILED fallback push — trying buildx manifest copy"
                        if docker buildx imagetools create --tag "$DST" "$FALLBACK_SRC" 2>&1; then
                            echo "    OK via buildx fallback (${FALLBACK_TAG})"
                            SUCCEEDED=$((SUCCEEDED + 1))
                            IMAGE_OK=true
                            break
                        fi
                    fi
                else
                    LAST_LINE=$(echo "$PULL_OUTPUT" | tail -1)
                    echo "    FAILED fallback pull (attempt ${attempt}/3): ${LAST_LINE}"
                fi
            done
        fi
    fi

    if ! $IMAGE_OK; then
        echo "    FAILED from all sources (including fallback)"
        FAILED+=("$dest_name:$dest_tag")
    fi
done

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "============================================"
echo "  Greenbone -> Harbor Mirror Complete"
echo "============================================"
echo ""
echo "  Succeeded: ${SUCCEEDED}/${#IMAGES[@]} (${SKIPPED} already in Harbor)"

if [ ${#FAILED[@]} -gt 0 ]; then
    echo "  Failed:    ${#FAILED[@]}"
    for f in "${FAILED[@]}"; do
        echo "    - ${f}"
    done
    echo ""
    echo "  ERROR: Failed images will prevent OpenVAS from starting."
    echo "  The deployment manifest references Harbor exclusively — there is no"
    echo "  upstream fallback. Re-run this script (or with --force) to retry."
    echo "  If :stable tags are broken upstream, update the pinned version variables"
    echo "  (OSPD_OPENVAS_VERSION, OPENVAS_SCANNER_VERSION) at the top of this script."
else
    echo "  Failed:    0"
fi

echo ""
echo "  Mirrored images: ${DEST_REGISTRY}/<name>:<tag>"
echo ""

if [ ${#FAILED[@]} -gt 0 ]; then
    exit 1
fi
