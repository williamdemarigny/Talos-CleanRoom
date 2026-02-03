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

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TFVARS_FILE="../terraform/talos-cluster-create/cluster.auto.tfvars"
CREDENTIALS_FILE="../terraform/talos-cluster-create/credentials.auto.tfvars"
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
        PROXMOX_ENDPOINT=$(grep -oP 'proxmox_api_url\s*=\s*"\K[^"]+' "$CREDENTIALS_FILE" || true)
    fi

    # Extract token
    if [[ -z "$PROXMOX_TOKEN" ]]; then
        PROXMOX_TOKEN=$(grep -oP 'proxmox_api_token\s*=\s*"\K[^"]+' "$CREDENTIALS_FILE" || true)
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

    # Debug: Show raw response
    # echo "DEBUG Response: $response" >&2

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
    local tf_dir="../terraform/talos-cluster-create"
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
            # Use negative lookbehind pattern to avoid matching 'fqdn' when looking for 'ip'
            static_ip=$(echo "$current_node" | grep -oP '(?<!fq)ip\s*=\s*"\K[^"]+' || true)
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

                # Get DHCP IP
                dhcp_ip=$(get_vm_ip "$vmid" "$node" || true)

                if [[ -z "$dhcp_ip" ]]; then
                    print_warning "  Could not get DHCP IP"
                    print_warning "  VM may not be running or QEMU guest agent not responding"
                    echo ""
                    current_node=""
                    continue
                fi

                print_success "  Current DHCP IP: $dhcp_ip"

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
                    if talosctl apply-config --insecure --nodes "$dhcp_ip" --file "$config_file" 2>&1; then
                        print_success "  Config applied successfully!"
                        print_info "  VM will reboot and come up at: $target_endpoint"
                        APPLIED_VMS+=("$name:$dhcp_ip:$target_endpoint")
                    else
                        print_error "  Failed to apply config"
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
    print_info "Waiting for control plane node to be reachable before bootstrapping..."

    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Would bootstrap cluster on $CONTROL_PLANE_ENDPOINT"
    else
        # Wait for node to be reachable with timeout (max 10 minutes)
        MAX_WAIT=600
        WAIT_INTERVAL=15
        ELAPSED=0

        print_info "Waiting for $CONTROL_PLANE_ENDPOINT to be reachable (timeout: ${MAX_WAIT}s)..."

        while [[ $ELAPSED -lt $MAX_WAIT ]]; do
            # Try to get node version - this works even in maintenance mode
            if talosctl --nodes "$CONTROL_PLANE_ENDPOINT" --endpoints "$CONTROL_PLANE_ENDPOINT" version --short 2>/dev/null; then
                print_success "Node is reachable after ${ELAPSED}s"
                break
            fi

            ELAPSED=$((ELAPSED + WAIT_INTERVAL))
            print_info "  Waiting... (${ELAPSED}/${MAX_WAIT}s)"
            sleep $WAIT_INTERVAL
        done

        if [[ $ELAPSED -ge $MAX_WAIT ]]; then
            print_error "Timeout waiting for node to be reachable"
            exit 1
        fi

        # Give the node a moment to fully initialize after becoming reachable
        print_info "Node reachable, waiting additional 30 seconds for full initialization..."
        sleep 30

        print_info "Bootstrapping cluster on control plane: $CONTROL_PLANE_ENDPOINT"

        # Retry bootstrap a few times in case of transient failures
        BOOTSTRAP_RETRIES=3
        for i in $(seq 1 $BOOTSTRAP_RETRIES); do
            if talosctl bootstrap --nodes "$CONTROL_PLANE_ENDPOINT" --endpoints "$CONTROL_PLANE_ENDPOINT" 2>&1; then
                print_success "Cluster bootstrapped successfully!"
                echo ""
                print_info "Configure talosctl context:"
                print_info "  talosctl config endpoint $CONTROL_PLANE_ENDPOINT"
                print_info "  talosctl config node $CONTROL_PLANE_ENDPOINT"
                break
            else
                if [[ $i -lt $BOOTSTRAP_RETRIES ]]; then
                    print_warning "Bootstrap attempt $i failed, retrying in 30 seconds..."
                    sleep 30
                else
                    print_error "Failed to bootstrap cluster after $BOOTSTRAP_RETRIES attempts"
                fi
            fi
        done
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
