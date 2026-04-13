#!/bin/bash

# apply-configs.sh
# Automatically discover DHCP IPs of Talos VMs from Proxmox and apply Talos machine configs

set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to wait for Talos API to be ready on a node
# For unconfigured nodes (maintenance mode), uses --insecure
# For configured nodes (after config applied), uses TALOSCONFIG
wait_for_talos_api() {
    local ip="$1"
    local max_attempts="${2:-30}"
    local interval="${3:-10}"
    local use_insecure="${4:-true}"

    print_info "  Waiting for Talos API on $ip:50000..."

    for ((i=1; i<=max_attempts; i++)); do
        # Use talosctl directly as the readiness check — more reliable than
        # /dev/tcp/ port probes which can fail in LXC containers
        local output
        local exit_code

        if [[ "$use_insecure" == "true" ]]; then
            # In maintenance mode, use 'version --insecure' to check API readiness
            if output=$(timeout 10 talosctl version --insecure -n "$ip" -e "$ip" 2>&1); then
                exit_code=0
            else
                exit_code=$?
            fi
        else
            # For configured nodes, use TALOSCONFIG
            if output=$(timeout 10 talosctl version --nodes "$ip" --endpoints "$ip" 2>&1); then
                exit_code=0
            else
                exit_code=$?
            fi
        fi

        # API is ready if command succeeds (exit code 0)
        if [[ $exit_code -eq 0 ]]; then
            print_success "  Talos API is ready on $ip"
            return 0
        fi

        # Check for specific error messages that indicate API is responding but in maintenance mode
        if echo "$output" | grep -qi "maintenance mode"; then
            print_success "  Talos API is ready on $ip (maintenance mode)"
            return 0
        fi

        # Log progress with diagnostics every 5th attempt
        if (( i % 5 == 0 )); then
            if ping -c 1 -W 2 "$ip" &>/dev/null 2>&1; then
                print_warning "    Attempt $i/$max_attempts - Host $ip reachable but Talos API not responding"
            else
                print_warning "    Attempt $i/$max_attempts - Host $ip NOT reachable (no ping response)"
            fi
            print_info "    Last response (exit=$exit_code): ${output:0:150}"
        else
            print_info "    Attempt $i/$max_attempts - Talos API not ready, waiting ${interval}s..."
        fi

        if [[ $i -lt $max_attempts ]]; then
            sleep "$interval"
        fi
    done

    print_error "  Talos API not ready on $ip after $((max_attempts * interval)) seconds"
    _diagnose_talos_api_failure "$ip"
    return 1
}

# Diagnostic function called when Talos API check fails
_diagnose_talos_api_failure() {
    local ip="$1"

    print_warning "  --- Diagnostic information for $ip ---"

    # Check basic network reachability
    if ping -c 2 -W 2 "$ip" &>/dev/null 2>&1; then
        print_info "  PING: Host is reachable"
    else
        print_error "  PING: Host is NOT reachable — VM may be down or IP has changed"
    fi

    # Check if common ports are open (indicates VM is running but Talos may not be)
    # Use nc (netcat) if available, fall back to /dev/tcp/
    for port in 22 80 443 6443 50000; do
        if command -v nc &>/dev/null; then
            if timeout 3 nc -z "$ip" "$port" 2>/dev/null; then
                print_info "  PORT $port: OPEN"
            else
                print_info "  PORT $port: closed"
            fi
        else
            if timeout 3 bash -c "echo > /dev/tcp/$ip/$port" 2>/dev/null; then
                print_info "  PORT $port: OPEN"
            else
                print_info "  PORT $port: closed"
            fi
        fi
    done

    # Try to get VM status from Proxmox if credentials are available
    if [[ -n "${PROXMOX_ENDPOINT:-}" && -n "${PROXMOX_TOKEN:-}" ]]; then
        print_info "  Checking VM status on Proxmox..."

        # Find the VMID that matches this IP by checking all known VMs
        local nodes_response=$(proxmox_api "/cluster/resources?type=vm" 2>/dev/null || true)
        if [[ -n "$nodes_response" ]]; then
            local vm_info=$(echo "$nodes_response" | jq -r '.data[]? | select(.type=="qemu") | "\(.vmid) \(.node) \(.status) \(.name // "unknown")"' 2>/dev/null || true)
            if [[ -n "$vm_info" ]]; then
                print_info "  Proxmox VMs:"
                while IFS= read -r vm_line; do
                    local vm_vmid vm_node vm_status vm_name
                    read -r vm_vmid vm_node vm_status vm_name <<< "$vm_line"
                    print_info "    VMID=$vm_vmid node=$vm_node status=$vm_status name=$vm_name"

                    # If VM is running, try to get its current IP from guest agent
                    if [[ "$vm_status" == "running" ]]; then
                        local agent_resp=$(proxmox_api "/nodes/${vm_node}/qemu/${vm_vmid}/agent/network-get-interfaces" 2>/dev/null || true)
                        local vm_ip=$(echo "$agent_resp" | jq -r '.data.result[]? | select(.name != "lo") | .["ip-addresses"][]? | select(.["ip-address-type"] == "ipv4") | .["ip-address"]' 2>/dev/null | head -1 || true)
                        if [[ -n "$vm_ip" ]]; then
                            print_info "      Current IP: $vm_ip"
                            if [[ "$vm_ip" != "$ip" ]]; then
                                print_warning "      IP MISMATCH: Expected $ip but VM has $vm_ip"
                            fi
                        fi
                    fi
                done <<< "$vm_info"
            fi
        fi
    fi

    # Show talosctl client version for reference
    local client_ver=$(talosctl version --client 2>&1 | head -3 || true)
    print_info "  talosctl client: ${client_ver:0:100}"

    print_warning "  --- End diagnostics ---"
}

# Function to wait for controller to EXIT maintenance mode and be ready for bootstrap
# IMPORTANT: Before bootstrap, the controller will be in "booting" stage with etcd NOT running.
# This is CORRECT - etcd only starts AFTER bootstrap is executed on the first control plane.
# We just need to verify the node has exited maintenance mode and is waiting for bootstrap.
wait_for_controller_ready() {
    local endpoint="$1"
    local max_attempts="${2:-60}"
    local interval="${3:-10}"

    print_info "Waiting for controller to exit maintenance mode..."
    print_info "(Controller will be in 'booting' stage until bootstrap is executed)"

    for ((i=1; i<=max_attempts; i++)); do
        # Check machine status to verify we're out of maintenance mode
        if output=$(talosctl --nodes "$endpoint" --endpoints "$endpoint" get machinestatus -o yaml 2>&1); then
            # Success if stage is "booting" or "running" (anything except maintenance)
            # "booting" = waiting for bootstrap (etcd not running yet) - this is the expected pre-bootstrap state
            # "running" = fully operational (only after bootstrap completes)
            if echo "$output" | grep -q "stage: booting"; then
                print_success "Controller is ready for bootstrap (stage: booting, attempt $i/$max_attempts)"
                # Check if it's waiting for etcd (expected state)
                if echo "$output" | grep -q "etcd not running"; then
                    print_info "  etcd waiting for bootstrap (expected)"
                fi
                return 0
            elif echo "$output" | grep -q "stage: running"; then
                # Already running - might be a re-bootstrap or cluster already exists
                print_success "Controller is already running (attempt $i/$max_attempts)"
                return 0
            fi
        fi

        # Log current state for debugging
        local state="unknown"
        if echo "$output" | grep -q "stage: maintenance"; then
            state="maintenance mode (still applying config)"
        elif echo "$output" | grep -q "rpc error"; then
            state="API not reachable"
        fi

        print_info "  Attempt $i/$max_attempts - Controller state: $state, waiting ${interval}s..."
        sleep "$interval"
    done

    print_error "Controller failed to exit maintenance mode after $((max_attempts * interval)) seconds"
    return 1
}

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TFVARS_FILE="../terraform/cluster-create/cluster.auto.tfvars"
CREDENTIALS_FILE="../terraform/cluster-create/credentials.auto.tfvars"
CONFIG_DIR="$SCRIPT_DIR/clusterconfig"

# Show usage
usage() {
    cat << EOF
apply-configs - Apply Talos machine configs to VMs using DHCP IPs

USAGE:
    $0 [OPTIONS]

OPTIONS:
    -h, --help              Show this help message
    -d, --dry-run          Show what would be done without applying configs
    -b, --bootstrap        Bootstrap the cluster after applying configs
    -e, --endpoint URL     Proxmox API endpoint (default: from credentials)
    -t, --token TOKEN      Proxmox API token (default: from credentials)

DESCRIPTION:
    This script queries Proxmox to find the DHCP-assigned IPs of your Talos VMs,
    then applies the corresponding machine configs with static IP settings.

EXAMPLES:
    # Dry run to see what would happen
    $0 --dry-run

    # Apply configs to all VMs
    $0

    # Apply configs and bootstrap the cluster
    $0 --bootstrap

REQUIREMENTS:
    - Proxmox credentials in credentials.auto.tfvars
    - Talos machine configs in $CONFIG_DIR
    - curl and jq installed
    - talosctl installed

EOF
}

# Parse command line arguments
DRY_RUN=false
BOOTSTRAP=false
PROXMOX_ENDPOINT=""
PROXMOX_TOKEN=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            usage
            exit 0
            ;;
        -d|--dry-run)
            DRY_RUN=true
            shift
            ;;
        -b|--bootstrap)
            BOOTSTRAP=true
            shift
            ;;
        -e|--endpoint)
            PROXMOX_ENDPOINT="$2"
            shift 2
            ;;
        -t|--token)
            PROXMOX_TOKEN="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage
            exit 1
            ;;
    esac
done

# Check required tools
for cmd in curl jq talosctl; do
    if ! command -v $cmd &> /dev/null; then
        print_error "$cmd is required but not installed"
        exit 1
    fi
done

# Load Proxmox credentials if not provided
if [[ -z "$PROXMOX_ENDPOINT" || -z "$PROXMOX_TOKEN" ]]; then
    if [[ ! -f "$CREDENTIALS_FILE" ]]; then
        print_error "Credentials file not found: $CREDENTIALS_FILE"
        exit 1
    fi

    print_info "Loading Proxmox credentials from $CREDENTIALS_FILE"

    # Extract endpoint
    if [[ -z "$PROXMOX_ENDPOINT" ]]; then
        PROXMOX_ENDPOINT=$(sed -n 's/.*proxmox_api_url[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "$CREDENTIALS_FILE" || true)
    fi

    # Extract token
    if [[ -z "$PROXMOX_TOKEN" ]]; then
        PROXMOX_TOKEN=$(sed -n 's/.*proxmox_api_token[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "$CREDENTIALS_FILE" || true)
    fi
fi

if [[ -z "$PROXMOX_ENDPOINT" || -z "$PROXMOX_TOKEN" ]]; then
    print_error "Could not load Proxmox credentials"
    exit 1
fi

# Remove /api2/json suffix if present
PROXMOX_ENDPOINT="${PROXMOX_ENDPOINT%/api2/json}"

print_info "Proxmox endpoint: $PROXMOX_ENDPOINT"

# Function to query Proxmox API
proxmox_api() {
    local path="$1"
    local response=$(curl -s -k -H "Authorization: PVEAPIToken=${PROXMOX_TOKEN}" \
        "${PROXMOX_ENDPOINT}/api2/json${path}")
    echo "$response"
}

# Function to get VM IP by VMID
get_vm_ip() {
    local vmid="$1"
    local node="$2"

    print_info "    Querying guest agent for IP address..." >&2

    # Query VM network interfaces via agent
    local response=$(proxmox_api "/nodes/${node}/qemu/${vmid}/agent/network-get-interfaces")

    # Check if agent is available
    if echo "$response" | jq -e '.data' > /dev/null 2>&1; then
        # Extract IPv4 address (exclude loopback)
        local ip=$(echo "$response" | jq -r '.data.result[]? | select(.name != "lo") | .["ip-addresses"][]? | select(.["ip-address-type"] == "ipv4") | .["ip-address"]' | head -1)
        echo "$ip"
    else
        echo ""
    fi
}

# Function to find VM node in Proxmox cluster
find_vm_node() {
    local vmid="$1"

    print_info "    Searching for VM in Proxmox cluster..." >&2

    # Try to get nodes from Terraform state first (more reliable)
    local tf_dir="../terraform/cluster-create"
    if [[ -f "$tf_dir/terraform.tfstate" ]]; then
        local vm_node=$(cd "$tf_dir" && terraform output -json 2>/dev/null | jq -r --arg vmid "$vmid" '.vm_details.value | to_entries[] | select(.value.vmid == ($vmid|tonumber)) | .key' | head -1)

        if [[ -n "$vm_node" ]]; then
            # Get the actual node name from distribution
            local node=$(cd "$tf_dir" && terraform output -json 2>/dev/null | jq -r --arg vm "$vm_node" '.vm_distribution.value | to_entries[] | select(.value[] == $vm) | .key' | head -1)
            if [[ -n "$node" ]]; then
                echo "$node"
                return 0
            fi
        fi
    fi

    # Fallback to API query
    local nodes=$(proxmox_api "/nodes" | jq -r '.data[]? | .node' 2>/dev/null)

    if [[ -z "$nodes" ]]; then
        print_warning "    Could not query Proxmox nodes via API" >&2
        return 1
    fi

    for node in $nodes; do
        local vm_status=$(proxmox_api "/nodes/${node}/qemu/${vmid}/status/current" 2>/dev/null)
        local status=$(echo "$vm_status" | jq -r '.data.status // empty' 2>/dev/null)

        if [[ -n "$status" ]]; then
            echo "$node"
            return 0
        fi
    done

    return 1
}

# Auto-set TALOSCONFIG if not already set
if [[ -z "${TALOSCONFIG:-}" ]]; then
    export TALOSCONFIG="$CONFIG_DIR/talosconfig"
fi

# Main execution
print_info "Starting Talos config application process"
print_info "Using TALOSCONFIG: $TALOSCONFIG"
echo ""

# Check if config directory exists
if [[ ! -d "$CONFIG_DIR" ]]; then
    print_error "Config directory not found: $CONFIG_DIR"
    print_warning "Run 'talhelper genconfig' first to generate configs"
    exit 1
fi

# Parse VMs from tfvars and process each one
print_info "Loading VM information from $TFVARS_FILE"
echo ""

# Brief pause before querying Proxmox guest agents.
# The deployment service's wait_for_vms step has already verified all VMs are
# booted and Talos API is reachable, so we only need a short stabilization delay.
print_info "Waiting for VMs to stabilize..."
sleep 10
echo ""

CONTROL_PLANE_ENDPOINT=""
declare -a APPLIED_VMS

# Extract and process nodes from tfvars
in_nodes_array=false
current_node=""

while IFS= read -r line; do
    line="${line%$'\r'}"

    if [[ "$line" =~ nodes[[:space:]]*=[[:space:]]*\[ ]]; then
        in_nodes_array=true
        continue
    fi

    if [[ "$in_nodes_array" == true && "$line" =~ ^[[:space:]]*\][[:space:]]*$ ]]; then
        break
    fi

    if [[ "$in_nodes_array" == true ]]; then
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
        current_node+="$line "

        if [[ "$line" =~ \}[[:space:]]*,?[[:space:]]*$ ]]; then
            # Extract values
            name=$(echo "$current_node" | sed -n 's/.*name[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p')
            vmid=$(echo "$current_node" | sed -n 's/.*vmid[[:space:]]*=[[:space:]]*\([0-9]*\).*/\1/p')
            role=$(echo "$current_node" | sed -n 's/.*role[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p')
            # Support both IP-based and FQDN-based configurations
            # Extract ip field only (not fqdn) using sed with word-boundary-like pattern
            static_ip=$(echo "$current_node" | sed -n 's/.*[^a-z]ip[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' || true)
            fqdn=$(echo "$current_node" | sed -n 's/.*fqdn[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p')
            # Use FQDN if IP is not available (DNS-based configuration)
            target_endpoint="${static_ip:-$fqdn}"

            if [[ -n "$name" && -n "$vmid" ]]; then
                print_info "Processing VM: $name (VMID: $vmid, Role: $role)"
                if [[ -n "$fqdn" ]]; then
                    print_info "  Target FQDN: $fqdn"
                else
                    print_info "  Target static IP: $static_ip"
                fi

                # Find which Proxmox node hosts this VM
                node=$(find_vm_node "$vmid" || true)
                if [[ -z "$node" ]]; then
                    print_warning "  VM not found in Proxmox cluster - skipping"
                    echo ""
                    current_node=""
                    continue
                fi

                print_success "  Found on Proxmox node: $node"

                # Get DHCP IP (retry — guest agent may not be ready yet)
                dhcp_ip=""
                for ip_attempt in $(seq 1 30); do
                    dhcp_ip=$(get_vm_ip "$vmid" "$node" || true)
                    if [[ -n "$dhcp_ip" ]]; then
                        break
                    fi
                    print_info "  Waiting for guest agent to report IP... ($ip_attempt/30)"
                    sleep 10
                done

                if [[ -z "$dhcp_ip" ]]; then
                    if [[ "$role" == "controlplane" ]]; then
                        print_error "  Could not get DHCP IP for control plane node — aborting"
                        exit 1
                    fi
                    print_warning "  Could not get DHCP IP"
                    print_warning "  VM may not be running or QEMU guest agent not responding"
                    echo ""
                    current_node=""
                    continue
                fi

                print_success "  Current DHCP IP: $dhcp_ip"

                # Wait for Talos API to be ready before applying config
                # Use insecure mode since the node is still unconfigured (maintenance mode)
                if [[ "$DRY_RUN" == false ]]; then
                    # Control plane gets more time — it must succeed for bootstrap
                    api_attempts=45
                    if [[ "$role" == "controlplane" ]]; then
                        api_attempts=90
                    fi
                    if ! wait_for_talos_api "$dhcp_ip" "$api_attempts" 10 true; then
                        if [[ "$role" == "controlplane" ]]; then
                            print_error "  Talos API not ready on control plane node — aborting"
                            exit 1
                        fi
                        print_error "  Talos API not ready - skipping this VM"
                        echo ""
                        current_node=""
                        continue
                    fi
                fi

                # Save control plane info for bootstrap (use FQDN or IP)
                if [[ "$role" == "controlplane" ]]; then
                    CONTROL_PLANE_ENDPOINT="$target_endpoint"
                fi

                # Find corresponding config file
                config_file=$(find "$CONFIG_DIR" -name "*${name}.yaml" -type f | head -1)

                if [[ -z "$config_file" ]]; then
                    print_warning "  Config file not found for $name in $CONFIG_DIR"
                    echo ""
                    current_node=""
                    continue
                fi

                print_info "  Config file: $(basename "$config_file")"

                if [[ "$DRY_RUN" == true ]]; then
                    print_info "  [DRY RUN] Would apply config to $dhcp_ip"
                else
                    print_info "  Applying configuration..."

                    # Retry apply-config up to 5 times with 10 second delays
                    # The API check may pass but the node might not be fully ready for config
                    apply_success=false
                    apply_attempts=5
                    apply_interval=10

                    for ((a=1; a<=apply_attempts; a++)); do
                        # In talosctl 1.12+, --insecure is a global flag (before command)
                        # Capture output and exit code without triggering set -e
                        if apply_output=$(talosctl apply-config --insecure -n "$dhcp_ip" --file "$config_file" 2>&1); then
                            apply_exit=0
                        else
                            apply_exit=$?
                        fi

                        if [[ $apply_exit -eq 0 ]]; then
                            print_success "  Config applied successfully!"
                            print_info "  VM will reboot and come up at: $target_endpoint"
                            APPLIED_VMS+=("$name:$dhcp_ip:$target_endpoint")
                            apply_success=true
                            break
                        else
                            print_warning "  Apply attempt $a/$apply_attempts failed: ${apply_output:0:100}"
                            if [[ $a -lt $apply_attempts ]]; then
                                print_info "  Retrying in ${apply_interval}s..."
                                sleep "$apply_interval"
                            fi
                        fi
                    done

                    if [[ "$apply_success" == false ]]; then
                        print_error "  Failed to apply config after $apply_attempts attempts"
                        if [[ "$role" == "controlplane" ]]; then
                            print_error "  Control plane config must be applied — aborting"
                            exit 1
                        fi
                    fi
                fi

                echo ""
            fi

            current_node=""
        fi
    fi
done < "$TFVARS_FILE"

# Bootstrap cluster if requested
if [[ "$BOOTSTRAP" == true && -n "$CONTROL_PLANE_ENDPOINT" ]]; then
    echo ""
    print_info "Waiting for controller to reboot and become ready for bootstrap..."
    print_info "Target endpoint: $CONTROL_PLANE_ENDPOINT"

    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Would bootstrap cluster on $CONTROL_PLANE_ENDPOINT"
    else
        # Phase 1: Wait for the Talos API to be reachable at the new static IP/FQDN
        # This confirms the VM has rebooted and the network is configured
        print_info ""
        print_info "Phase 1: Waiting for Talos API to be reachable..."
        if ! wait_for_talos_api "$CONTROL_PLANE_ENDPOINT" 90 10 false; then
            print_error "Talos API not reachable at $CONTROL_PLANE_ENDPOINT"
            print_error "The VM may not have rebooted or network configuration failed"
            exit 1
        fi

        # Phase 2: Wait for controller to fully exit maintenance mode and initialize etcd
        # This is the critical step - bootstrap WILL FAIL if etcd is not ready
        print_info ""
        print_info "Phase 2: Waiting for controller to exit maintenance mode..."
        if ! wait_for_controller_ready "$CONTROL_PLANE_ENDPOINT" 90 10; then
            print_error "Controller failed to exit maintenance mode"
            print_error "Check logs with: talosctl -n $CONTROL_PLANE_ENDPOINT -e $CONTROL_PLANE_ENDPOINT logs"
            exit 1
        fi

        print_info ""
        print_info "Controller is ready. Bootstrapping cluster on: $CONTROL_PLANE_ENDPOINT"
        if talosctl bootstrap --nodes "$CONTROL_PLANE_ENDPOINT" --endpoints "$CONTROL_PLANE_ENDPOINT"; then
            print_success "Cluster bootstrapped successfully!"
            echo ""
            print_info "Configure talosctl context:"
            print_info "  talosctl config endpoint $CONTROL_PLANE_ENDPOINT"
            print_info "  talosctl config node $CONTROL_PLANE_ENDPOINT"
        else
            print_error "Failed to bootstrap cluster"
        fi
    fi
fi

echo ""
print_success "Done!"

if [[ "$DRY_RUN" == false && ${#APPLIED_VMS[@]} -gt 0 ]]; then
    echo ""
    print_info "Summary of applied configs:"
    for vm_info in "${APPLIED_VMS[@]}"; do
        IFS=':' read -r name dhcp_ip target <<< "$vm_info"
        echo "  - $name: $dhcp_ip → $target"
    done

    echo ""
    print_info "Next steps:"
    print_info "  1. Wait for VMs to reboot (1-2 minutes)"
    print_info "  2. Verify connectivity: talosctl --nodes $CONTROL_PLANE_ENDPOINT health"
    if [[ "$BOOTSTRAP" == false ]]; then
        print_info "  3. Bootstrap cluster: talosctl bootstrap --nodes $CONTROL_PLANE_ENDPOINT --endpoints $CONTROL_PLANE_ENDPOINT"
    fi
fi
