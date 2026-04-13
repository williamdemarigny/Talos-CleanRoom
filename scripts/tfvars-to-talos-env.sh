#!/bin/bash

# tfvars-to-talos-env.sh
# Extract values from cluster.auto.tfvars and generate talenv.yaml for talhelper

set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[USAGE]${NC} $1"
}

# Default values
TFVARS_FILE="terraform/cluster-create/cluster.auto.tfvars"
OUTPUT_FILE="cluster/talenv.yaml"
OUTPUT_FORMAT="yaml"
VERBOSE=true
BACKUP=false
FORCE=false

# Show usage
usage() {
    cat << EOF
tfvars-to-talos-env - Extract Terraform values for Talos talenv.yaml

USAGE:
    $0 [OPTIONS] [TFVARS_FILE]

OPTIONS:
    -h, --help              Show this help message
    -o, --output FILE       Output to file (default: talos/talenv.yaml)
    -f, --format FORMAT     Output format: yaml|shell (default: yaml)
    -v, --verbose           Enable verbose output
    -b, --backup            Create backup of existing file before overwriting
    --force                 Overwrite existing file without confirmation

EXAMPLES:
    # Generate talenv.yaml for talhelper
    $0

    # Generate with backup of existing file
    $0 --backup

    # Overwrite without confirmation (for scripts/CI)
    $0 --force

    # Generate shell exports (legacy)
    $0 -f shell

    # Use with talhelper
    $0 && cd talos && talhelper genconfig --env-file talenv.yaml

EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            usage
            exit 0
            ;;
        -o|--output)
            OUTPUT_FILE="$2"
            shift 2
            ;;
        -f|--format)
            OUTPUT_FORMAT="$2"
            shift 2
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        -b|--backup)
            BACKUP=true
            shift
            ;;
        --force)
            FORCE=true
            shift
            ;;
        -*)
            echo "Unknown option: $1" >&2
            usage
            exit 1
            ;;
        *)
            TFVARS_FILE="$1"
            shift
            ;;
    esac
done

# Check if tfvars file exists
if [[ ! -f "$TFVARS_FILE" ]]; then
    echo "Error: Terraform vars file '$TFVARS_FILE' not found" >&2
    exit 1
fi

# Function to create backup of existing file
create_backup() {
    local file="$1"
    if [[ -f "$file" ]]; then
        local backup_file="${file}.backup.$(date +%Y%m%d_%H%M%S)"
        cp "$file" "$backup_file"
        print_info "Backup created: $backup_file"
    fi
}

# Function to prompt for confirmation
confirm_overwrite() {
    local file="$1"
    if [[ -f "$file" ]]; then
        echo -e "${YELLOW}[WARNING]${NC} File '$file' already exists."
        read -p "Overwrite? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Aborted. Use --force to skip confirmation or --backup to create a backup."
            exit 1
        fi
    fi
}

# Function to perform atomic write (write to temp file, then move)
atomic_write() {
    local target_file="$1"
    local temp_file
    temp_file=$(mktemp "${target_file}.tmp.XXXXXX")

    # Generate content to temp file
    if generate_env_vars > "$temp_file"; then
        # Move temp file to target (atomic operation)
        mv "$temp_file" "$target_file"
        return 0
    else
        # Clean up temp file on failure
        rm -f "$temp_file"
        echo "Error: Failed to generate configuration" >&2
        return 1
    fi
}

if [[ "$VERBOSE" == true ]]; then
    print_info "Processing: $TFVARS_FILE"
fi

# Function to extract values and generate exports
generate_env_vars() {
    # Step 1: Using static network configuration for DNS-based addressing
    local network_base="10.83.3"
    local gateway_ip="10.83.3.1"

    if [[ "$VERBOSE" == true ]]; then
        print_info "Using static network configuration for DNS addressing" >&2
        print_info "Network: ${network_base}.0/24" >&2
        print_info "Gateway: $gateway_ip" >&2
    fi

    # Step 2: Find the first control plane FQDN by scanning the nodes array
    local first_control_plane_fqdn=""
    local in_nodes_array_pre=false
    local current_node_pre=""
    while IFS= read -r line_pre; do
        # Strip carriage return for Windows CRLF line endings
        line_pre="${line_pre%$'\r'}"

        if [[ "$line_pre" =~ nodes[[:space:]]*=[[:space:]]*\[ ]]; then
            in_nodes_array_pre=true
            continue
        fi
        if [[ "$in_nodes_array_pre" == true && "$line_pre" =~ ^[[:space:]]*\][[:space:]]*$ ]]; then
            break
        fi
        if [[ "$in_nodes_array_pre" == true ]]; then
            [[ -z "$line_pre" || "$line_pre" =~ ^[[:space:]]*# ]] && continue
            current_node_pre+="$line_pre "
            if [[ "$line_pre" =~ \}[[:space:]]*,?[[:space:]]*$ ]]; then
                local role_pre=$(echo "$current_node_pre" | sed -n 's/.*role[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p')
                if [[ "$role_pre" == "controlplane" ]]; then
                    first_control_plane_fqdn=$(echo "$current_node_pre" | sed -n 's/.*fqdn[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p')
                    if [[ -n "$first_control_plane_fqdn" ]]; then
                        if [[ "$VERBOSE" == true ]]; then
                            print_info "Found first control plane FQDN: $first_control_plane_fqdn" >&2
                        fi
                        break # Found the first control plane FQDN
                    fi
                fi
                current_node_pre=""
            fi
        fi
    done < "$TFVARS_FILE"

    # Step 3: Output file header comments
    if [[ "$OUTPUT_FORMAT" == "yaml" ]]; then
        echo "# talenv.yaml - Talos environment variables for talhelper"
        echo "# Extracted from $TFVARS_FILE"
        echo "# Generated on $(date)"
        echo ""
    else
        echo "# Talos environment variables extracted from $TFVARS_FILE"
        echo "# Generated on $(date)"
        echo ""
    fi

    # Step 4: Output network configuration (now we have both subnet and control plane FQDN)
    if [[ -n "$network_base" && -n "$gateway_ip" ]]; then
        if [[ "$OUTPUT_FORMAT" == "yaml" ]]; then
            echo "# Network Configuration"
            echo "GATEWAY_IP: \"$gateway_ip\""
            echo "NETWORK_BASE: \"$network_base\""
            # For bootstrapping, use the first control plane FQDN.
            # For HA, you would use a VIP here.
            if [[ -n "$first_control_plane_fqdn" ]]; then
                echo "CONTROL_PLANE_ENDPOINT_FQDN: \"$first_control_plane_fqdn\""
            else
                echo "# WARNING: Could not determine first control plane FQDN. Using fallback." >&2
                echo "CONTROL_PLANE_ENDPOINT_FQDN: \"talos-CleanRoom-master-01.knowledgeondemand.net\"" # Fallback
            fi
            echo ""
        else
            echo "# Network Configuration"
            echo "export GATEWAY_IP=\"$gateway_ip\""
            echo "export NETWORK_BASE=\"$network_base\""
            if [[ -n "$first_control_plane_fqdn" ]]; then
                echo "export CONTROL_PLANE_ENDPOINT_FQDN=\"$first_control_plane_fqdn\""
            else
                echo "# WARNING: Could not determine first control plane FQDN. Using fallback." >&2
                echo "export CONTROL_PLANE_ENDPOINT_FQDN=\"talos-CleanRoom-master-01.knowledgeondemand.net\""
            fi
            echo ""
        fi
    fi

    # Extract OPNsense VMs from opnsense_vms array
    local opnsense_idx=0
    local in_opnsense_array=false
    local current_opnsense=""
    local found_opnsense=false

    while IFS= read -r line; do
        # Strip carriage return for Windows CRLF line endings
        line="${line%$'\r'}"

        # Check if we're entering opnsense_vms array
        if [[ "$line" =~ opnsense_vms[[:space:]]*=[[:space:]]*\[ ]]; then
            in_opnsense_array=true
            found_opnsense=true
            continue
        fi

        # Check if we're exiting opnsense_vms array
        if [[ "$in_opnsense_array" == true && "$line" =~ ^[[:space:]]*\][[:space:]]*$ ]]; then
            break
        fi

        # Process lines within opnsense_vms array
        if [[ "$in_opnsense_array" == true ]]; then
            # Skip empty lines and comments
            [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue

            # Accumulate the current OPNsense VM definition
            current_opnsense+="$line "

            # Check if we have a complete VM definition (ends with })
            if [[ "$line" =~ \}[[:space:]]*,?[[:space:]]*$ ]]; then
                # Extract values from the complete OPNsense VM string
                local name=$(echo "$current_opnsense" | sed -n 's/.*name[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p')
                local fqdn=$(echo "$current_opnsense" | sed -n 's/.*fqdn[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p')
                local mac=$(echo "$current_opnsense" | sed -n 's/.*mac_address[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p')
                local vmid=$(echo "$current_opnsense" | sed -n 's/.*vmid[[:space:]]*=[[:space:]]*\([0-9]*\).*/\1/p')

                # Output if we have all required values
                if [[ -n "$name" && -n "$fqdn" && -n "$mac" ]]; then
                    # Only print header once when we find the first OPNsense VM
                    if [[ "$opnsense_idx" -eq 0 ]]; then
                        if [[ "$OUTPUT_FORMAT" == "yaml" ]]; then
                            echo "# OPNsense Firewall Configuration"
                        else
                            echo "# OPNsense Firewall Configuration"
                        fi
                    fi

                    if [[ "$OUTPUT_FORMAT" == "yaml" ]]; then
                        echo "OPNSENSE_FQDN_${opnsense_idx}: \"$fqdn\""
                        echo "OPNSENSE_MAC_${opnsense_idx}: \"$mac\""
                        echo "OPNSENSE_NAME_${opnsense_idx}: \"$name\""
                        [[ -n "$vmid" ]] && echo "OPNSENSE_VMID_${opnsense_idx}: \"$vmid\""
                    else
                        echo "export OPNSENSE_FQDN_${opnsense_idx}=\"$fqdn\""
                        echo "export OPNSENSE_MAC_${opnsense_idx}=\"$mac\""
                        echo "export OPNSENSE_NAME_${opnsense_idx}=\"$name\""
                        [[ -n "$vmid" ]] && echo "export OPNSENSE_VMID_${opnsense_idx}=\"$vmid\""
                    fi
                    if [[ "$VERBOSE" == true ]]; then
                        print_info "Processed OPNsense ${opnsense_idx}: $name -> $fqdn" >&2
                    fi
                    opnsense_idx=$((opnsense_idx + 1))
                fi

                # Reset for next OPNsense VM
                current_opnsense=""
            fi
        fi
    done < "$TFVARS_FILE"

    # Add separator if we found OPNsense VMs
    if [[ "$found_opnsense" == true && "$opnsense_idx" -gt 0 ]]; then
        echo ""
    fi

    # Process each node in the nodes array
    local control_plane_idx=0
    local worker_idx=1  # Start workers at index 1
    local gpu_worker_idx=0

    if [[ "$OUTPUT_FORMAT" == "yaml" ]]; then
        echo "# Talos Node Configuration"
    else
        echo "# Talos Node Configuration"
    fi
    
    # Extract nodes array using a simpler bash approach
    local node_count=0
    local in_nodes_array=false
    local current_node=""
    
    while IFS= read -r line; do
        # Strip carriage return for Windows CRLF line endings
        line="${line%$'\r'}"

        # Check if we're entering nodes array
        if [[ "$line" =~ nodes[[:space:]]*=[[:space:]]*\[ ]]; then
            in_nodes_array=true
            continue
        fi

        # Check if we're exiting nodes array
        if [[ "$in_nodes_array" == true && "$line" =~ ^[[:space:]]*\][[:space:]]*$ ]]; then
            break
        fi

        # Process lines within nodes array
        if [[ "$in_nodes_array" == true ]]; then
            # Skip empty lines and comments
            [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue

            # Accumulate the current node definition
            current_node+="$line "

            # Check if we have a complete node (ends with })
            if [[ "$line" =~ \}[[:space:]]*,?[[:space:]]*$ ]]; then
                # Extract values from the complete node string
                local name=$(echo "$current_node" | sed -n 's/.*name[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p')
                local role=$(echo "$current_node" | sed -n 's/.*role[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p')
                local fqdn=$(echo "$current_node" | sed -n 's/.*fqdn[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p')
                local mac=$(echo "$current_node" | sed -n 's/.*mac_address[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p')

                # Output if we have all required values
                if [[ -n "$name" && -n "$role" && -n "$fqdn" && -n "$mac" ]]; then
                    # Generate role-based environment variables
                    case "$role" in
                        "controlplane")
                            if [[ "$OUTPUT_FORMAT" == "yaml" ]]; then
                                echo "TALOS_CONTROL_PLANE_FQDN_${control_plane_idx}: \"$fqdn\""
                                echo "TALOS_CONTROL_PLANE_MAC_${control_plane_idx}: \"$mac\""
                                echo "TALOS_CONTROL_PLANE_NAME_${control_plane_idx}: \"$name\""
                            else
                                echo "export TALOS_CONTROL_PLANE_FQDN_${control_plane_idx}=\"$fqdn\""
                                echo "export TALOS_CONTROL_PLANE_MAC_${control_plane_idx}=\"$mac\""
                                echo "export TALOS_CONTROL_PLANE_NAME_${control_plane_idx}=\"$name\""
                            fi
                            if [[ "$VERBOSE" == true ]]; then
                                print_info "Processed control plane ${control_plane_idx}: $name -> $fqdn" >&2
                            fi
                            control_plane_idx=$((control_plane_idx + 1))
                            ;;
                        "worker")
                            if [[ "$OUTPUT_FORMAT" == "yaml" ]]; then
                                echo "TALOS_WORKER_FQDN_${worker_idx}: \"$fqdn\""
                                echo "TALOS_WORKER_MAC_${worker_idx}: \"$mac\""
                                echo "TALOS_WORKER_NAME_${worker_idx}: \"$name\""
                            else
                                echo "export TALOS_WORKER_FQDN_${worker_idx}=\"$fqdn\""
                                echo "export TALOS_WORKER_MAC_${worker_idx}=\"$mac\""
                                echo "export TALOS_WORKER_NAME_${worker_idx}=\"$name\""
                            fi
                            if [[ "$VERBOSE" == true ]]; then
                                print_info "Processed worker ${worker_idx}: $name -> $fqdn" >&2
                            fi
                            worker_idx=$((worker_idx + 1))
                            ;;
                        "worker-gpu")
                            if [[ "$OUTPUT_FORMAT" == "yaml" ]]; then
                                echo "TALOS_GPU_WORKER_FQDN_${gpu_worker_idx}: \"$fqdn\""
                                echo "TALOS_GPU_WORKER_MAC_${gpu_worker_idx}: \"$mac\""
                                echo "TALOS_GPU_WORKER_NAME_${gpu_worker_idx}: \"$name\""
                            else
                                echo "export TALOS_GPU_WORKER_FQDN_${gpu_worker_idx}=\"$fqdn\""
                                echo "export TALOS_GPU_WORKER_MAC_${gpu_worker_idx}=\"$mac\""
                                echo "export TALOS_GPU_WORKER_NAME_${gpu_worker_idx}=\"$name\""
                            fi
                            if [[ "$VERBOSE" == true ]]; then
                                print_info "Processed GPU worker ${gpu_worker_idx}: $name -> $fqdn" >&2
                            fi
                            gpu_worker_idx=$((gpu_worker_idx + 1))
                            ;;
                        *)
                            if [[ "$VERBOSE" == true ]]; then
                                print_warning "Unknown role '$role' for node $name" >&2
                            fi
                            ;;
                    esac
                fi

                # Reset for next node
                current_node=""
            fi
        fi
    done < "$TFVARS_FILE"
    
    echo ""
    if [[ "$OUTPUT_FORMAT" == "yaml" ]]; then
        echo "# Usage with talhelper:"
        echo "# talhelper genconfig --env-file talenv.yaml"
    else
        echo "# Usage:"
        echo "# source <(./$(basename "$0") -f shell)"
        echo "# talhelper genconfig"
    fi
}

# Main execution
if [[ "$OUTPUT_FORMAT" == "yaml" ]]; then
    # Default to talenv.yaml if no output file specified
    if [[ "$OUTPUT_FILE" == "talos/talenv.yaml" ]]; then
        # Create talos directory if it doesn't exist
        mkdir -p "$(dirname "$OUTPUT_FILE")"
    fi

    # Check for existing file and handle accordingly
    if [[ -f "$OUTPUT_FILE" ]]; then
        # Create backup if requested
        if [[ "$BACKUP" == true ]]; then
            create_backup "$OUTPUT_FILE"
        fi

        # Prompt for confirmation unless --force is used
        if [[ "$FORCE" != true ]]; then
            confirm_overwrite "$OUTPUT_FILE"
        fi
    fi

    # Use atomic write to safely generate the file
    if atomic_write "$OUTPUT_FILE"; then
        print_success "talenv.yaml generated: $OUTPUT_FILE"
        if [[ "$VERBOSE" == true ]]; then
            print_warning "Next steps:"
            echo "  cd talos && talhelper genconfig --env-file talenv.yaml"
        fi
    else
        exit 1
    fi
else
    # Shell export format
    if [[ -n "$OUTPUT_FILE" ]]; then
        # Check for existing file and handle accordingly
        if [[ -f "$OUTPUT_FILE" ]]; then
            # Create backup if requested
            if [[ "$BACKUP" == true ]]; then
                create_backup "$OUTPUT_FILE"
            fi

            # Prompt for confirmation unless --force is used
            if [[ "$FORCE" != true ]]; then
                confirm_overwrite "$OUTPUT_FILE"
            fi
        fi

        # Use atomic write to safely generate the file
        if atomic_write "$OUTPUT_FILE"; then
            print_success "Environment variables written to: $OUTPUT_FILE"
            print_warning "Source the file with: source $OUTPUT_FILE"
        else
            exit 1
        fi
    else
        generate_env_vars
    fi

    if [[ "$VERBOSE" == true ]]; then
        print_success "Environment variables generated!"
        echo ""
        print_warning "Next steps:"
        echo "  1. Source the variables: source <($0 -f shell)"
        echo "  2. Run talhelper: talhelper genconfig"
        echo "  3. Or combine: source <($0 -f shell) && talhelper genconfig"
    fi
fi