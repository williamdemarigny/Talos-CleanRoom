#!/bin/bash
# Vulhub Target Lab Validation Suite
#
# Validates all 16 (or a subset) Vulhub targets end-to-end:
#   1. Deploy via API
#   2. Verify pod is healthy and stays healthy (no crashloops)
#   3. Verify TCP connectivity from openvas namespace
#   4. Run a vulnerability scan with the recommended tools
#   5. Verify the env's CVE was detected by at least one scanner
#   6. Destroy the target and continue to the next
#
# Each failed target gets diagnostic captures saved to diag/<env_id>-*.txt
# A summary markdown table is written at the end.
#
# Usage:
#   ./validate-targets.sh                              # all 16 targets
#   ./validate-targets.sh --targets log4shell,heartbleed
#   SCANNING_PW=xxx ./validate-targets.sh
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
KUBECONFIG_PATH="${REPO_ROOT}/kubeconfig.yaml"
SCANNING_URL="https://scan.knowledgeondemand.net"
SCANNING_USER="admin"
SCANNING_PW="${SCANNING_PW:-}"
TARGETS=""              # empty = all
SCAN_TIMEOUT_MIN=10
# Tools to use in the validator. OpenVAS is excluded by default because:
#   1. Standard scans take 15-60 min even on a single port (NVT count)
#   2. We've already validated OpenVAS works in earlier integration tests
#   3. Nmap NSE scripts + Metasploit modules detect most CVEs faster
# Override with --tools to include openvas if you have time.
VALIDATOR_TOOLS='["nmap","metasploit"]'
VALIDATOR_PROFILE="standard"
LOG_FILE="${SCRIPT_DIR}/validate-targets.log"
SUMMARY_FILE="${SCRIPT_DIR}/validate-targets-summary.md"
DIAG_DIR="${SCRIPT_DIR}/diag"

# ---------------------------------------------------------------------------
# Parse args
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --kubeconfig) KUBECONFIG_PATH="$2"; shift 2 ;;
    --targets) TARGETS="$2"; shift 2 ;;
    --scan-timeout) SCAN_TIMEOUT_MIN="$2"; shift 2 ;;
    --log) LOG_FILE="$2"; shift 2 ;;
    --scanning-url) SCANNING_URL="$2"; shift 2 ;;
    --scanning-pw) SCANNING_PW="$2"; shift 2 ;;
    --tools) VALIDATOR_TOOLS="$2"; shift 2 ;;
    --profile) VALIDATOR_PROFILE="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

if [ -z "$SCANNING_PW" ]; then
  echo "ERROR: scanning password required (--scanning-pw or SCANNING_PW env)"
  exit 1
fi

export KUBECONFIG="$KUBECONFIG_PATH"
# Disable Python's newline translation on Windows so captured output is clean
export PYTHONIOENCODING="utf-8"
# Force LF line endings from Python on Windows
export PYTHONUTF8=1
mkdir -p "$DIAG_DIR"
: > "$LOG_FILE"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log() {
  local ts="$(date '+%Y-%m-%d %H:%M:%S')"
  # Write to stderr so command-substitution callers don't capture log lines.
  # Also append to log file.
  echo "[$ts] $*" >&2
  echo "[$ts] $*" >> "$LOG_FILE"
}

log_section() {
  log ""
  log "============================================================"
  log "  $*"
  log "============================================================"
}

# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------
TOKEN=""

api_login() {
  log "Logging in to scanning console as $SCANNING_USER..."
  TOKEN=$(curl -sk "$SCANNING_URL/api/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"$SCANNING_USER\",\"password\":\"$SCANNING_PW\"}" \
    2>/dev/null | pyrun -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)
  if [ -z "$TOKEN" ]; then
    log "ERROR: login failed"
    return 1
  fi
  log "Login OK (token=${TOKEN:0:20}...)"
  return 0
}

api_get() {
  local path="$1"
  curl -sk -H "Authorization: Bearer $TOKEN" "$SCANNING_URL$path" 2>/dev/null
}

# Python wrapper that strips CR from output (Windows compat)
pyrun() {
  python "$@" | tr -d '\r'
}

api_post() {
  local path="$1"
  local body="$2"
  if [ -z "$body" ]; then
    body='{}'
  fi
  curl -sk -X POST -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "$body" "$SCANNING_URL$path" 2>/dev/null
}

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------
preflight() {
  log_section "Pre-flight checks"
  for cmd in kubectl curl python; do
    if ! command -v "$cmd" &>/dev/null; then
      log "ERROR: $cmd not found"
      exit 1
    fi
  done
  if ! kubectl cluster-info --request-timeout=5s >/dev/null 2>&1; then
    log "ERROR: cannot reach Kubernetes cluster"
    exit 1
  fi
  api_login || exit 1

  # Verify capacity
  local capacity
  capacity=$(api_get /api/target-lab/capacity | pyrun -c "import sys,json; d=json.load(sys.stdin); print(f\"{d.get('used','?')}/{d.get('max','?')}\")")
  log "Target Lab capacity: $capacity"

  # Verify openvas pod is up
  local ov_state
  ov_state=$(kubectl get pods -n openvas -l app.kubernetes.io/name=greenbone -o jsonpath='{.items[0].status.phase}' 2>/dev/null)
  log "OpenVAS pod state: $ov_state"

  log "Pre-flight passed."
}

# ---------------------------------------------------------------------------
# Get the catalog (env_id, cve, ports, recommended_scan)
# ---------------------------------------------------------------------------
get_catalog_field() {
  local env_id="$1"
  local field="$2"
  api_get /api/target-lab/catalog | pyrun -c "
import sys, json
d = json.load(sys.stdin)
for e in d.get('catalog', []):
    if e['env_id'] == '$env_id':
        v = e.get('$field')
        if isinstance(v, (list, dict)):
            out = json.dumps(v)
        else:
            out = str(v) if v is not None else ''
        sys.stdout.buffer.write(out.encode())
        break
"
}

list_all_env_ids() {
  api_get /api/target-lab/catalog | pyrun -c "
import sys, json
d = json.load(sys.stdin)
out = '\n'.join(e['env_id'] for e in d.get('catalog', []))
sys.stdout.buffer.write(out.encode())
sys.stdout.buffer.write(b'\n')
"
}

# ---------------------------------------------------------------------------
# Target lifecycle
# ---------------------------------------------------------------------------
deploy_target() {
  local env_id="$1"
  local resp
  # Retry up to 4 times if the deploy lock is held (15s, 30s, 60s backoff)
  for delay in 0 15 30 60; do
    [ "$delay" -gt 0 ] && sleep "$delay"
    resp=$(api_post /api/target-lab/deploy "{\"env_id\":\"$env_id\"}")
    if ! echo "$resp" | grep -q "deployment lock"; then
      break
    fi
  done
  echo "$resp"
}

destroy_target() {
  local target_id="$1"
  api_post "/api/target-lab/destroy/$target_id" "{}" >/dev/null
}

get_target_id_for() {
  local env_id="$1"
  api_get /api/target-lab/targets | pyrun -c "
import sys, json
d = json.load(sys.stdin)
for t in d.get('targets', []):
    if t['env_id'] == '$env_id':
        print(t['id'])
        break
"
}

get_target_status() {
  local env_id="$1"
  api_get /api/target-lab/targets | pyrun -c "
import sys, json
d = json.load(sys.stdin)
for t in d.get('targets', []):
    if t['env_id'] == '$env_id':
        print(t['status'])
        break
else:
    print('NONE')
"
}

get_target_namespace() {
  local env_id="$1"
  api_get /api/target-lab/targets | pyrun -c "
import sys, json
d = json.load(sys.stdin)
for t in d.get('targets', []):
    if t['env_id'] == '$env_id':
        print(t['namespace'])
        break
"
}

get_target_endpoint() {
  local env_id="$1"
  api_get /api/target-lab/targets | pyrun -c "
import sys, json
d = json.load(sys.stdin)
for t in d.get('targets', []):
    if t['env_id'] == '$env_id':
        print(t['service_endpoint'])
        break
"
}

# ---------------------------------------------------------------------------
# Pod health check (returns 0 if healthy, 1 otherwise)
# Captures diagnostics on failure.
# ---------------------------------------------------------------------------
check_pod_health() {
  local env_id="$1"
  local ns="$2"

  local pod_json
  pod_json=$(kubectl get pods -n "$ns" -o json 2>&1)
  local ready restarts phase
  ready=$(echo "$pod_json" | pyrun -c "
import sys, json
try:
    d = json.load(sys.stdin)
    if not d['items']:
        print('NOPOD')
        sys.exit()
    p = d['items'][0]
    cs = p['status'].get('containerStatuses', [])
    if not cs:
        print('NOSTATUS')
        sys.exit()
    print('1' if cs[0]['ready'] else '0')
except: print('ERR')
")
  restarts=$(echo "$pod_json" | pyrun -c "
import sys, json
try:
    d = json.load(sys.stdin)
    p = d['items'][0]
    cs = p['status'].get('containerStatuses', [{}])
    print(cs[0].get('restartCount', '?'))
except: print('?')
")
  phase=$(echo "$pod_json" | pyrun -c "
import sys, json
try:
    d = json.load(sys.stdin)
    p = d['items'][0]
    print(p['status'].get('phase', '?'))
except: print('?')
")

  log "  Pod check: phase=$phase ready=$ready restarts=$restarts"

  if [ "$ready" != "1" ] || [ "$restarts" != "0" ]; then
    log "  POD UNHEALTHY — capturing diagnostics"
    capture_pod_diag "$env_id" "$ns"
    return 1
  fi
  return 0
}

capture_pod_diag() {
  local env_id="$1"
  local ns="$2"
  kubectl get pods -n "$ns" -o yaml > "$DIAG_DIR/${env_id}-pod-yaml.txt" 2>&1 || true
  kubectl describe pods -n "$ns" > "$DIAG_DIR/${env_id}-pod-describe.txt" 2>&1 || true
  # kubectl logs needs a pod selector when using --all-containers
  kubectl logs -n "$ns" -l app.kubernetes.io/part-of=vulhub-targets --all-containers --tail=100 > "$DIAG_DIR/${env_id}-pod-logs.txt" 2>&1 || true
  kubectl logs -n "$ns" -l app.kubernetes.io/part-of=vulhub-targets --all-containers --previous --tail=100 > "$DIAG_DIR/${env_id}-pod-logs-previous.txt" 2>&1 || true
  kubectl get events -n "$ns" --sort-by='.lastTimestamp' > "$DIAG_DIR/${env_id}-pod-events.txt" 2>&1 || true
}

# ---------------------------------------------------------------------------
# TCP connectivity check from openvas namespace
# ---------------------------------------------------------------------------
check_connectivity() {
  local env_id="$1"
  local endpoint="$2"  # host:port

  local host="${endpoint%:*}"
  local port="${endpoint##*:}"

  log "  Connectivity test: $host:$port from openvas namespace..."

  local pod_name="conn-test-${env_id//_/-}-$$"
  kubectl run "$pod_name" --restart=Never --image=curlimages/curl -n openvas \
    --command -- sh -c "curl -sk -m 5 -o /dev/null -w 'TCP_OK\n' \"https://$host:$port/\" 2>/dev/null || \
                       curl -sk -m 5 -o /dev/null -w 'TCP_OK\n' \"http://$host:$port/\" 2>/dev/null || \
                       echo 'TCP_FAIL'" \
    >/dev/null 2>&1

  # Wait for pod to complete
  sleep 8

  local result
  result=$(kubectl logs -n openvas "$pod_name" 2>&1)
  kubectl delete pod -n openvas "$pod_name" --force --grace-period=0 >/dev/null 2>&1 || true

  if echo "$result" | grep -q "TCP_OK"; then
    log "  Connectivity OK"
    return 0
  fi
  log "  Connectivity FAIL: $result"
  return 1
}

# ---------------------------------------------------------------------------
# Run scan and wait for completion
# ---------------------------------------------------------------------------
run_scan() {
  local env_id="$1"
  local target="$2"      # host:port
  local tools="$3"       # JSON array string e.g. ["nmap","metasploit"]
  local profile="$4"     # quick / standard / thorough
  local nmap_scripts="${5:-}"  # optional NSE scripts (comma-separated)

  log "  Starting scan: target=$target tools=$tools profile=$profile nmap_scripts=${nmap_scripts:-none}"

  # Abort any in-flight scan from a previous iteration
  local prev_status
  prev_status=$(api_get /api/scan/status | pyrun -c "import sys,json; print(json.load(sys.stdin).get('status','idle'))" 2>/dev/null)
  if [ "$prev_status" = "running" ] || [ "$prev_status" = "?" ]; then
    log "  Aborting previous in-flight scan (status=$prev_status)..."
    api_post /api/scan/abort '{}' >/dev/null
    sleep 10
  fi

  # Build request body — include nmap_scripts only if non-empty
  local body
  if [ -n "$nmap_scripts" ]; then
    body=$(printf '{"target":"%s","tools":%s,"profile":"%s","nmap_scripts":"%s"}' "$target" "$tools" "$profile" "$nmap_scripts")
  else
    body=$(printf '{"target":"%s","tools":%s,"profile":"%s"}' "$target" "$tools" "$profile")
  fi

  local resp
  resp=$(api_post /api/scan/start "$body")

  local scan_id
  scan_id=$(echo "$resp" | pyrun -c "import sys,json; print(json.load(sys.stdin).get('scan_id',''))" 2>/dev/null)

  if [ -z "$scan_id" ]; then
    log "  ERROR: scan failed to start: $resp"
    return 1
  fi

  log "  Scan started (id=$scan_id), polling status..."

  local max_polls=$((SCAN_TIMEOUT_MIN * 2))  # 30s intervals
  for i in $(seq 1 $max_polls); do
    sleep 30
    local status_json status
    status_json=$(api_get /api/scan/status)
    status=$(echo "$status_json" | pyrun -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null)
    log "    [${i}*30s] scan status: $status"
    if [ "$status" = "completed" ] || [ "$status" = "failed" ]; then
      echo "$scan_id"
      return 0
    fi
  done

  log "  ERROR: scan timeout after ${SCAN_TIMEOUT_MIN}m"
  return 1
}

# ---------------------------------------------------------------------------
# Check if CVE was detected in scan results
# ---------------------------------------------------------------------------
verify_cve_detected() {
  local env_id="$1"
  local scan_id="$2"
  local cve="$3"

  log "  Checking scan $scan_id for $cve..."

  local report
  report=$(api_get "/api/reports/scans/$scan_id")
  echo "$report" > "$DIAG_DIR/${env_id}-scan-report.json"

  local matches
  matches=$(echo "$report" | pyrun -c "
import sys, json
d = json.load(sys.stdin)
cve = '$cve'.upper()
matches = []
for h in d.get('hosts', []):
    for v in h.get('vulnerabilities', []):
        haystack = ' '.join(filter(None, [
            str(v.get('name','')),
            str(v.get('external_id','')),
            str(v.get('description','')),
            str(v.get('refs',''))
        ])).upper()
        if cve in haystack:
            matches.append(f\"{v.get('tool_source','?')}: {v.get('name','?')[:80]}\")
print(len(matches))
for m in matches[:5]:
    print('  ' + m)
" 2>/dev/null)

  local count
  count=$(echo "$matches" | head -1)

  if [ -z "$count" ] || [ "$count" = "0" ]; then
    log "  CVE $cve NOT detected in any finding"
    # Show top findings for diagnosis
    echo "$report" | pyrun -c "
import sys, json
d = json.load(sys.stdin)
total = sum(len(h.get('vulnerabilities',[])) for h in d.get('hosts',[]))
print(f'Total vulns found: {total}')
for h in d.get('hosts',[]):
    print(f'Host {h[\"ip\"]}: {len(h.get(\"services\",[]))} svcs, {len(h.get(\"vulnerabilities\",[]))} vulns')
    for v in h.get('vulnerabilities',[])[:5]:
        print(f'  [{v.get(\"tool_source\",\"?\")}] {v.get(\"name\",\"?\")[:80]}')
" >> "$LOG_FILE" 2>&1
    return 1
  fi

  log "  CVE $cve DETECTED in $count finding(s):"
  echo "$matches" | tail -n +2 | while read line; do
    log "    $line"
  done
  return 0
}

# ---------------------------------------------------------------------------
# Test one target end-to-end
# ---------------------------------------------------------------------------
declare -A RESULTS_DEPLOY RESULTS_POD RESULTS_REACH RESULTS_SCAN RESULTS_CVE

test_target() {
  local env_id="$1"
  log_section "Testing target: $env_id"

  # Defaults to FAIL — only set to PASS on explicit success
  RESULTS_DEPLOY[$env_id]="FAIL"
  RESULTS_POD[$env_id]="-"
  RESULTS_REACH[$env_id]="-"
  RESULTS_SCAN[$env_id]="-"
  RESULTS_CVE[$env_id]="-"

  # Get catalog metadata
  local cve tools profile nmap_scripts
  cve=$(get_catalog_field "$env_id" cve)
  local recommended
  recommended=$(get_catalog_field "$env_id" recommended_scan)
  nmap_scripts=$(echo "$recommended" | pyrun -c "import sys,json; print(json.load(sys.stdin).get('nmap_scripts',''))" 2>/dev/null)
  # Use catalog's recommended tools/profile but EXCLUDE openvas (too slow for the validator)
  tools=$(echo "$recommended" | pyrun -c "
import sys, json
d = json.load(sys.stdin)
tools = [t for t in d.get('tools', ['nmap']) if t != 'openvas']
if not tools:
    tools = ['nmap']
print(json.dumps(tools))
" 2>/dev/null)
  profile=$(echo "$recommended" | pyrun -c "import sys,json; p=json.load(sys.stdin).get('profile','standard'); print(p if p != 'custom' else 'standard')" 2>/dev/null)
  # Override with validator-wide settings if explicitly set
  [ -n "${VALIDATOR_TOOLS_OVERRIDE:-}" ] && tools="$VALIDATOR_TOOLS_OVERRIDE"
  [ -n "${VALIDATOR_PROFILE_OVERRIDE:-}" ] && profile="$VALIDATOR_PROFILE_OVERRIDE"

  log "  CVE: $cve"
  log "  Validator scan: tools=$tools profile=$profile nmap_scripts=${nmap_scripts:-none}"

  # 1. Deploy
  local deploy_resp
  deploy_resp=$(deploy_target "$env_id")
  if echo "$deploy_resp" | grep -q '"detail"'; then
    log "  DEPLOY FAILED: $deploy_resp"
    echo "$deploy_resp" > "$DIAG_DIR/${env_id}-deploy-error.txt"
    return
  fi
  RESULTS_DEPLOY[$env_id]="PASS"
  log "  Deploy initiated"

  # 2. Poll for running status (max 3 min)
  local target_status=""
  for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
    sleep 15
    target_status=$(get_target_status "$env_id")
    log "    [${i}*15s] target status: $target_status"
    if [ "$target_status" = "running" ]; then break; fi
    if [ "$target_status" = "error" ] || [ "$target_status" = "destroyed" ]; then
      log "  Target entered error state"
      break
    fi
  done

  local target_id ns
  target_id=$(get_target_id_for "$env_id")
  ns=$(get_target_namespace "$env_id")

  if [ "$target_status" != "running" ]; then
    log "  Target never reached running (status=$target_status)"
    capture_pod_diag "$env_id" "$ns"
    [ -n "$target_id" ] && destroy_target "$target_id"
    sleep 30
    return
  fi

  # 3. Validate pod health (twice — initial + after 60s wait)
  if ! check_pod_health "$env_id" "$ns"; then
    [ -n "$target_id" ] && destroy_target "$target_id"
    sleep 30
    return
  fi
  log "  Initial pod health OK, waiting 60s to check stability..."
  sleep 60
  if ! check_pod_health "$env_id" "$ns"; then
    log "  Pod became unhealthy after 60s — likely crash loop"
    [ -n "$target_id" ] && destroy_target "$target_id"
    sleep 30
    return
  fi
  RESULTS_POD[$env_id]="PASS"

  # 4. Connectivity check
  local endpoint
  endpoint=$(get_target_endpoint "$env_id")
  if [ -n "$endpoint" ]; then
    if check_connectivity "$env_id" "$endpoint"; then
      RESULTS_REACH[$env_id]="PASS"
    fi
  fi

  # 5. Run scan
  local scan_id
  if scan_id=$(run_scan "$env_id" "$endpoint" "$tools" "$profile" "$nmap_scripts"); then
    RESULTS_SCAN[$env_id]="PASS"

    # 6. CVE detection
    if [ -n "$cve" ]; then
      if verify_cve_detected "$env_id" "$scan_id" "$cve"; then
        RESULTS_CVE[$env_id]="PASS"
      fi
    else
      RESULTS_CVE[$env_id]="N/A"
    fi
  fi

  # 7. Abort any running scan (in case scan timed out but is still active)
  local final_status
  final_status=$(api_get /api/scan/status | pyrun -c "import sys,json; print(json.load(sys.stdin).get('status','idle'))" 2>/dev/null)
  if [ "$final_status" = "running" ]; then
    log "  Aborting in-flight scan before destroying target..."
    api_post /api/scan/abort '{}' >/dev/null
    sleep 10
  fi

  # 8. Destroy target
  log "  Destroying target $target_id..."
  [ -n "$target_id" ] && destroy_target "$target_id"
  sleep 30
}

# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------
write_summary() {
  log_section "Final Summary"

  local total=0 passed=0
  {
    echo "# Vulhub Target Validation Results"
    echo ""
    echo "Generated: $(date)"
    echo ""
    echo "| env_id | deploy | pod_ready | reachable | scan | cve_detected | overall |"
    echo "|--------|--------|-----------|-----------|------|--------------|---------|"
    for env_id in "${TEST_LIST[@]}"; do
      local deploy="${RESULTS_DEPLOY[$env_id]:-?}"
      local pod="${RESULTS_POD[$env_id]:-?}"
      local reach="${RESULTS_REACH[$env_id]:-?}"
      local scan="${RESULTS_SCAN[$env_id]:-?}"
      local cve="${RESULTS_CVE[$env_id]:-?}"

      local overall="FAIL"
      if [ "$deploy" = "PASS" ] && [ "$pod" = "PASS" ] && [ "$reach" = "PASS" ] && [ "$scan" = "PASS" ] && { [ "$cve" = "PASS" ] || [ "$cve" = "N/A" ]; }; then
        overall="PASS"
        passed=$((passed + 1))
      fi
      total=$((total + 1))
      echo "| $env_id | $deploy | $pod | $reach | $scan | $cve | $overall |"
    done
    echo ""
    echo "**$passed / $total targets passed all stages.**"
  } | tee "$SUMMARY_FILE" | tee -a "$LOG_FILE"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
  log_section "Vulhub Target Lab Validation Suite"
  log "Kubeconfig:    $KUBECONFIG_PATH"
  log "Scanning URL:  $SCANNING_URL"
  log "Log:           $LOG_FILE"
  log "Summary:       $SUMMARY_FILE"
  log "Diag:          $DIAG_DIR"

  preflight

  # Build target list
  declare -ga TEST_LIST=()
  if [ -n "$TARGETS" ]; then
    IFS=',' read -ra TEST_LIST <<< "$TARGETS"
  else
    while IFS= read -r line; do
      [ -n "$line" ] && TEST_LIST+=("$line")
    done < <(list_all_env_ids)
  fi
  log "Targets to test (${#TEST_LIST[@]}): ${TEST_LIST[*]}"

  for env_id in "${TEST_LIST[@]}"; do
    test_target "$env_id"
  done

  write_summary
}

main "$@"
