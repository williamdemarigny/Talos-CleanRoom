#!/bin/bash
# Automated OpenVAS GSA v25 fix tester
#
# Iterates through fix strategies, applies each, waits for the pod to come
# up, tests the login API end-to-end, and reports which strategy works.
#
# Usage:
#   ./test-openvas-fixes.sh                           # run all strategies
#   ./test-openvas-fixes.sh --strategies S2,S3        # specific strategies
#   ./test-openvas-fixes.sh --kubeconfig /path/to/kc  # custom kubeconfig
#
# Output:
#   openvas-test.log     — top-level log
#   diag/<strategy>-*    — per-strategy diagnostic captures
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
KUBECONFIG_PATH="${REPO_ROOT}/kubeconfig.yaml"
STRATEGIES="S7,S8"
MAX_WAIT_MIN=15
LOG_FILE="${SCRIPT_DIR}/openvas-test.log"
DIAG_DIR="${SCRIPT_DIR}/diag"
NAMESPACE="openvas"

# ---------------------------------------------------------------------------
# Parse args
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --kubeconfig) KUBECONFIG_PATH="$2"; shift 2 ;;
    --strategies) STRATEGIES="$2"; shift 2 ;;
    --max-wait-min) MAX_WAIT_MIN="$2"; shift 2 ;;
    --log) LOG_FILE="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

export KUBECONFIG="$KUBECONFIG_PATH"
mkdir -p "$DIAG_DIR"
: > "$LOG_FILE"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log() {
  local ts msg
  ts="$(date '+%H:%M:%S')"
  msg="[$ts] $*"
  echo "$msg"
  echo "$msg" >> "$LOG_FILE"
}

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------
preflight() {
  log "=== Pre-flight checks ==="
  if ! command -v kubectl &>/dev/null; then
    log "ERROR: kubectl not found"
    exit 1
  fi
  if ! kubectl cluster-info --request-timeout=5s >/dev/null 2>&1; then
    log "ERROR: Cannot reach Kubernetes cluster (KUBECONFIG=$KUBECONFIG_PATH)"
    exit 1
  fi
  if ! kubectl get ns "$NAMESPACE" >/dev/null 2>&1; then
    log "ERROR: namespace $NAMESPACE does not exist"
    exit 1
  fi
  if ! kubectl get secret -n "$NAMESPACE" openvas-credentials >/dev/null 2>&1; then
    log "ERROR: secret openvas-credentials missing in $NAMESPACE"
    exit 1
  fi

  # CRITICAL: Disable ArgoCD auto-sync so our patches don't get reverted by selfHeal
  if kubectl get application -n argocd openvas >/dev/null 2>&1; then
    log "Disabling ArgoCD auto-sync for openvas (so patches stick)..."
    kubectl patch application openvas -n argocd --type=merge \
      -p '{"spec":{"syncPolicy":{"automated":null}}}' 2>&1 | tee -a "$LOG_FILE"
  fi

  log "All pre-flight checks passed."
}

# Re-enable ArgoCD auto-sync (called on exit)
restore_argocd_sync() {
  if kubectl get application -n argocd openvas >/dev/null 2>&1; then
    log "Re-enabling ArgoCD auto-sync for openvas..."
    kubectl patch application openvas -n argocd --type=merge \
      -p '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true}}}}' 2>&1 | tee -a "$LOG_FILE" || true
  fi
}
trap restore_argocd_sync EXIT

# ---------------------------------------------------------------------------
# Helper: get the openvas admin password from the secret
# ---------------------------------------------------------------------------
get_admin_password() {
  kubectl get secret -n "$NAMESPACE" openvas-credentials \
    -o jsonpath='{.data.admin-password}' | base64 -d
}

# ---------------------------------------------------------------------------
# Helper: wait for the greenbone pod to be 6/6 Running
# ---------------------------------------------------------------------------
wait_for_pod_ready() {
  local strategy="$1"
  local max_seconds=$((MAX_WAIT_MIN * 60))
  local elapsed=0
  local interval=15

  log "  Waiting for pod 6/6 Running (max ${MAX_WAIT_MIN}m)..."
  while [ $elapsed -lt $max_seconds ]; do
    sleep $interval
    elapsed=$((elapsed + interval))

    local pod_info ready_count phase
    pod_info=$(kubectl get pods -n "$NAMESPACE" \
      -l app.kubernetes.io/name=greenbone \
      -o jsonpath='{.items[0].status.phase}/{.items[0].status.containerStatuses[*].ready}' \
      2>/dev/null || echo "Unknown/")
    phase="${pod_info%%/*}"
    ready_count=$(echo "${pod_info#*/}" | tr ' ' '\n' | grep -c "true" || true)

    log "    [${elapsed}s] phase=$phase ready=$ready_count/6"

    if [ "$phase" = "Running" ] && [ "$ready_count" = "6" ]; then
      log "  Pod is 6/6 Running"
      return 0
    fi
  done
  log "  TIMEOUT: pod never became 6/6 Running"
  return 1
}

# ---------------------------------------------------------------------------
# Helper: test the login API from inside the cluster
# ---------------------------------------------------------------------------
test_login_api() {
  local strategy="$1"
  local pwd
  pwd=$(get_admin_password)

  log "  Testing login API via internal curl pod..."

  # Run a one-off curl pod that POSTs to /gmp with form data
  # Use -w to print ONLY the HTTP code on the last line, easy to grep
  local pod_name="login-test-${strategy,,}-$$"
  local result_file="${DIAG_DIR}/${strategy}-curl.log"
  local code_file="${DIAG_DIR}/${strategy}-code.txt"

  # Capture full response body + HTTP status code
  kubectl run "$pod_name" --rm -i --restart=Never \
    --image=curlimages/curl -n "$NAMESPACE" --quiet \
    --command -- sh -c "curl -sv -m 30 -o /tmp/body.txt -w 'HTTP_CODE:%{http_code}' \
      'http://greenbone:80/gmp' \
      -X POST \
      -F 'cmd=login' \
      -F 'login=admin' \
      -F 'password=${pwd}' 2>/tmp/verbose.txt; \
      echo ''; \
      echo '--VERBOSE--'; cat /tmp/verbose.txt; \
      echo '--BODY--'; cat /tmp/body.txt" \
    > "$result_file" 2>&1 || true

  # Extract HTTP code from the result
  local code
  code=$(grep -oE "HTTP_CODE:[0-9]+" "$result_file" 2>/dev/null | head -1 | cut -d: -f2 || echo "000")
  echo "$code" > "$code_file"

  log "  HTTP code: $code"

  # Success = 200 OK, 303 See Other (redirect after login)
  if [ "$code" = "200" ] || [ "$code" = "303" ]; then
    log "  PASS: Login successful (HTTP $code)"
    return 0
  fi
  log "  FAIL: HTTP $code (expected 200 or 303)"
  return 1
}

# ---------------------------------------------------------------------------
# Helper: capture diagnostics for a failed strategy
# ---------------------------------------------------------------------------
capture_diagnostics() {
  local strategy="$1"
  local pod_name
  pod_name=$(kubectl get pods -n "$NAMESPACE" \
    -l app.kubernetes.io/name=greenbone \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")

  if [ -z "$pod_name" ]; then
    log "  No pod found for diagnostics"
    return
  fi

  log "  Capturing diagnostics to ${DIAG_DIR}/${strategy}-*.log"
  kubectl logs -n "$NAMESPACE" "$pod_name" -c gsa --tail=80 \
    > "${DIAG_DIR}/${strategy}-gsa.log" 2>&1 || true
  kubectl logs -n "$NAMESPACE" "$pod_name" -c gvmd --tail=80 \
    > "${DIAG_DIR}/${strategy}-gvmd.log" 2>&1 || true
  kubectl get events -n "$NAMESPACE" --sort-by='.lastTimestamp' \
    > "${DIAG_DIR}/${strategy}-events.log" 2>&1 || true
  kubectl describe pod -n "$NAMESPACE" "$pod_name" \
    > "${DIAG_DIR}/${strategy}-describe.log" 2>&1 || true

  # Summary file
  {
    echo "Strategy: $strategy"
    echo "Pod: $pod_name"
    kubectl get pod -n "$NAMESPACE" "$pod_name" \
      -o jsonpath='Restarts: {.status.containerStatuses[*].restartCount}{"\n"}Ready: {.status.containerStatuses[*].ready}{"\n"}'
  } > "${DIAG_DIR}/${strategy}-summary.txt" 2>&1
}

# ---------------------------------------------------------------------------
# Strategy definitions
#
# Each strategy is a function that returns a JSON patch (strategic merge)
# to apply to the greenbone deployment. The patch ONLY modifies the gvmd
# and gsa containers. All other parts of the deployment stay intact.
# ---------------------------------------------------------------------------

# S1: Baseline — current state, no changes (just verify failure is reproducible)
strategy_S1() {
  cat <<'EOF'
{}
EOF
}

# S2: gvmd with TLS gnutls priorities + GSA with --munix-socket
strategy_S2() {
  cat <<'EOF'
{
  "spec": {
    "template": {
      "spec": {
        "containers": [
          {
            "name": "gvmd",
            "command": ["/bin/sh", "-c"],
            "args": ["echo 'Waiting for PostgreSQL socket...' && while [ ! -S /var/run/postgresql/.s.PGSQL.5432 ]; do sleep 2; done && echo 'Waiting for OSPD...' && while [ ! -S /run/ospd/ospd-openvas.sock ]; do sleep 2; done && if ! gosu gvmd gvmd --get-users 2>/dev/null | grep -q '^admin$'; then gosu gvmd gvmd --create-user=admin --password=\"${GVMD_ADMIN_PASSWORD}\" || true; fi && if ! gvm-manage-certs -V >/dev/null 2>&1; then gvm-manage-certs -a; fi && chown -R gvmd:gvmd /var/lib/gvm/CA /var/lib/gvm/private/CA 2>/dev/null || true && echo 'Starting GVMD with TLS...' && exec /usr/local/bin/entrypoint gvmd -f --gnutls-priorities='NORMAL:+VERS-TLS1.3:+VERS-TLS1.2'"]
          },
          {
            "name": "gsa",
            "command": ["/bin/sh", "-c"],
            "args": ["echo 'Waiting for GVMD...' && while [ ! -S /run/gvmd/gvmd.sock ]; do sleep 2; done && echo 'Starting GSA...' && exec gsad --foreground --http-only --port=80 --munix-socket=/run/gvmd/gvmd.sock"]
          }
        ]
      }
    }
  }
}
EOF
}

# S3: Drop --http-only, let gsad use HTTPS internally
strategy_S3() {
  cat <<'EOF'
{
  "spec": {
    "template": {
      "spec": {
        "containers": [
          {
            "name": "gvmd",
            "command": ["/bin/sh", "-c"],
            "args": ["echo 'Waiting for PostgreSQL...' && while [ ! -S /var/run/postgresql/.s.PGSQL.5432 ]; do sleep 2; done && while [ ! -S /run/ospd/ospd-openvas.sock ]; do sleep 2; done && if ! gosu gvmd gvmd --get-users 2>/dev/null | grep -q '^admin$'; then gosu gvmd gvmd --create-user=admin --password=\"${GVMD_ADMIN_PASSWORD}\" || true; fi && if ! gvm-manage-certs -V >/dev/null 2>&1; then gvm-manage-certs -a; fi && chown -R gvmd:gvmd /var/lib/gvm/CA /var/lib/gvm/private/CA 2>/dev/null || true && exec /usr/local/bin/entrypoint gvmd -f --gnutls-priorities='NORMAL'"]
          },
          {
            "name": "gsa",
            "command": ["/bin/sh", "-c"],
            "args": ["while [ ! -S /run/gvmd/gvmd.sock ]; do sleep 2; done && exec gsad --foreground --port=443 --no-redirect --munix-socket=/run/gvmd/gvmd.sock --ssl-certificate=/var/lib/gvm/CA/servercert.pem --ssl-private-key=/var/lib/gvm/private/CA/serverkey.pem"],
            "ports": [{"containerPort": 443, "name": "https"}]
          }
        ]
      }
    }
  }
}
EOF
}

# S4: Disable TLS on gvmd by NOT setting --gnutls-priorities
strategy_S4() {
  cat <<'EOF'
{
  "spec": {
    "template": {
      "spec": {
        "containers": [
          {
            "name": "gvmd",
            "command": ["/bin/sh", "-c"],
            "args": ["while [ ! -S /var/run/postgresql/.s.PGSQL.5432 ]; do sleep 2; done && while [ ! -S /run/ospd/ospd-openvas.sock ]; do sleep 2; done && if ! gosu gvmd gvmd --get-users 2>/dev/null | grep -q '^admin$'; then gosu gvmd gvmd --create-user=admin --password=\"${GVMD_ADMIN_PASSWORD}\" || true; fi && exec /usr/local/bin/entrypoint gvmd -f"]
          },
          {
            "name": "gsa",
            "command": ["/bin/sh", "-c"],
            "args": ["while [ ! -S /run/gvmd/gvmd.sock ]; do sleep 2; done && exec gsad --foreground --http-only --port=80 --munix-socket=/run/gvmd/gvmd.sock"]
          }
        ]
      }
    }
  }
}
EOF
}

# S5: Use :latest tag instead of :stable
strategy_S5() {
  cat <<'EOF'
{
  "spec": {
    "template": {
      "spec": {
        "containers": [
          {
            "name": "gvmd",
            "image": "harbor.knowledgeondemand.net/cleanroom/gvmd:latest"
          },
          {
            "name": "gsa",
            "image": "harbor.knowledgeondemand.net/cleanroom/gsa:latest"
          }
        ]
      }
    }
  }
}
EOF
}

# S6: Use :edge tag (newest builds)
strategy_S6() {
  cat <<'EOF'
{
  "spec": {
    "template": {
      "spec": {
        "containers": [
          {
            "name": "gvmd",
            "image": "harbor.knowledgeondemand.net/cleanroom/gvmd:edge"
          },
          {
            "name": "gsa",
            "image": "harbor.knowledgeondemand.net/cleanroom/gsa:edge"
          }
        ]
      }
    }
  }
}
EOF
}

# S7: Use ghcr.io gsad v24.8.0 (last known-good before v25 segfault bug)
# Pull gsad daemon directly from GHCR which still has version-tagged images
strategy_S7() {
  cat <<'EOF'
{
  "spec": {
    "template": {
      "spec": {
        "containers": [
          {
            "name": "gsa",
            "image": "ghcr.io/greenbone/gsad:24.8.0"
          }
        ]
      }
    }
  }
}
EOF
}

# S8: Use ghcr.io gsad 24.6.0 (even older v24)
strategy_S8() {
  cat <<'EOF'
{
  "spec": {
    "template": {
      "spec": {
        "containers": [
          {
            "name": "gsa",
            "image": "ghcr.io/greenbone/gsad:24.6.0"
          }
        ]
      }
    }
  }
}
EOF
}

# ---------------------------------------------------------------------------
# Helper: apply a strategy by calling its function and patching the deployment
# ---------------------------------------------------------------------------
apply_strategy() {
  local strategy="$1"
  local fn="strategy_${strategy}"

  if ! declare -f "$fn" >/dev/null; then
    log "  ERROR: strategy function $fn not defined"
    return 1
  fi

  local patch
  patch=$($fn)

  if [ "$patch" = "{}" ] && [ "$strategy" = "S1" ]; then
    log "  S1 baseline — applying current greenbone-deployment.yaml as-is"
    if ! kubectl apply -f "${SCRIPT_DIR}/greenbone-deployment.yaml" 2>&1 | tail -3 | tee -a "$LOG_FILE"; then
      log "  ERROR: kubectl apply failed"
      return 1
    fi
  else
    log "  Applying patch for $strategy..."
    # First, restore baseline so patches build on a clean state
    kubectl apply -f "${SCRIPT_DIR}/greenbone-deployment.yaml" 2>&1 | tail -2 | tee -a "$LOG_FILE" || true
    # Write patch to a temp file (Windows Git Bash kubectl can't read /dev/stdin)
    local patch_file="${DIAG_DIR}/${strategy}-patch.json"
    echo "$patch" > "$patch_file"
    if ! kubectl patch deployment greenbone -n "$NAMESPACE" \
        --type=strategic --patch-file="$patch_file" 2>&1 | tee -a "$LOG_FILE"; then
      log "  ERROR: kubectl patch failed"
      return 1
    fi
  fi

  # Force a rollout to pick up the new spec
  kubectl rollout restart deployment/greenbone -n "$NAMESPACE" 2>&1 | tail -2 | tee -a "$LOG_FILE" || true
  log "  Strategy applied. Waiting for new pod to roll out..."
  sleep 20  # give the new pod time to be created
  return 0
}

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
main() {
  log "============================================================"
  log "  OpenVAS Fix Strategy Tester"
  log "============================================================"
  log "  Strategies:  $STRATEGIES"
  log "  Max wait:    ${MAX_WAIT_MIN} min per strategy"
  log "  Kubeconfig:  $KUBECONFIG_PATH"
  log "  Log file:    $LOG_FILE"
  log "  Diag dir:    $DIAG_DIR"
  log ""

  preflight

  IFS=',' read -ra strategy_list <<< "$STRATEGIES"

  for strategy in "${strategy_list[@]}"; do
    log ""
    log "============================================================"
    log "  Testing strategy: $strategy"
    log "============================================================"

    if ! apply_strategy "$strategy"; then
      log "  SKIP: could not apply strategy"
      continue
    fi

    if ! wait_for_pod_ready "$strategy"; then
      log "  FAIL: pod never became ready"
      capture_diagnostics "$strategy"
      continue
    fi

    # Extra wait for gsad to fully bind
    sleep 30

    if test_login_api "$strategy"; then
      log ""
      log "============================================================"
      log "  SUCCESS: Strategy $strategy fixes the OpenVAS login!"
      log "============================================================"
      log "  Working strategy file: ${SCRIPT_DIR}/test-strategies/${strategy}.yaml"
      log "  To make permanent: copy that strategy's gvmd/gsa container"
      log "  configuration into apps/openvas/greenbone-deployment.yaml"
      capture_diagnostics "$strategy"
      exit 0
    fi

    log "  FAIL: $strategy did not fix login"
    capture_diagnostics "$strategy"
  done

  log ""
  log "============================================================"
  log "  ALL STRATEGIES FAILED"
  log "============================================================"
  log "  See ${DIAG_DIR}/ for per-strategy diagnostic captures."
  exit 1
}

main "$@"
