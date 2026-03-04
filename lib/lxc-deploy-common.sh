#!/bin/bash
#######################################
# Talos CleanRoom - Shared LXC Deploy Functions Library
#######################################
# This library provides common functions shared between LXC deployment scripts
# (webui/deploy-lxc.sh, build-vm/deploy-lxc.sh).
#
# Usage:
#   source "$(dirname "${BASH_SOURCE[0]}")/../lib/lxc-deploy-common.sh"
#
# Functions provided:
#   - prompt_credential: Prompt user for a credential value
#   - resolve_ssh_key: Validate and resolve an SSH key file path
#   - validate_ssh_connection: Test SSH connectivity to a host
#
# Expects the following color variables to be defined by the caller:
#   RED, GREEN, YELLOW, NC
#######################################

# Prevent multiple sourcing
[[ -n "${_TALOS_LXC_DEPLOY_COMMON_LOADED:-}" ]] && return 0
readonly _TALOS_LXC_DEPLOY_COMMON_LOADED=1

#######################################
# Prompt user for a credential, storing the result in the named variable.
# If the variable is already set (non-empty), the prompt is skipped.
#
# Arguments:
#   $1 - var_name    : Name of the variable to store the credential in
#   $2 - prompt_text : Text to display when prompting
#   $3 - is_secret   : "true" to use silent input (read -rs), "false" for normal input
#
# Example:
#   prompt_credential PROXMOX_API_TOKEN "Proxmox API Token (format: user@pam!tokenid=secret)" false
#   prompt_credential PROXMOX_SSH_PASSWORD "Proxmox SSH password for root" true
#######################################
prompt_credential() {
    local var_name="$1"
    local prompt_text="$2"
    local is_secret="${3:-false}"

    # Skip if already set
    local current_value="${!var_name:-}"
    if [ -n "$current_value" ]; then
        return 0
    fi

    echo -e "${YELLOW}${prompt_text}:${NC}"
    if [ "$is_secret" = "true" ]; then
        read -rs "${var_name?}"
        echo ""
    else
        read -r "${var_name?}"
    fi

    # Export the variable so it's available in the caller's scope
    export "${var_name?}"
}

#######################################
# Validate and resolve an SSH key file path.
# Checks common SSH key locations for a default, prompts the user,
# and validates the file exists.
#
# Arguments:
#   $1 - default_path : Optional default path to suggest (empty string to auto-detect)
#
# Output:
#   Prints the resolved SSH key path to stdout.
#   Sets GITHUB_SSH_KEY in the environment.
#
# Returns:
#   0 if key found, 1 if not found (exits script on failure)
#
# Example:
#   resolve_ssh_key ""
#   resolve_ssh_key "/home/user/.ssh/id_ed25519"
#######################################
resolve_ssh_key() {
    local default_path="${1:-}"

    # If GITHUB_SSH_KEY is already set and non-empty, just validate it
    if [ -n "${GITHUB_SSH_KEY:-}" ]; then
        if [ ! -f "$GITHUB_SSH_KEY" ]; then
            echo -e "${RED}Error: SSH key not found at ${GITHUB_SSH_KEY}${NC}"
            return 1
        fi
        echo -e "${GREEN}Using SSH key: ${GITHUB_SSH_KEY}${NC}"
        return 0
    fi

    # Auto-detect default key if not provided
    if [ -z "$default_path" ]; then
        for key_path in ~/.ssh/id_ed25519 ~/.ssh/id_rsa ~/.ssh/github ~/.ssh/id_ecdsa; do
            if [ -f "$key_path" ]; then
                default_path="$key_path"
                break
            fi
        done
    fi

    # Prompt user
    if [ -n "$default_path" ]; then
        echo -e "${YELLOW}Path to GitHub SSH private key [${default_path}]:${NC}"
        read -r GITHUB_SSH_KEY
        GITHUB_SSH_KEY="${GITHUB_SSH_KEY:-$default_path}"
    else
        echo -e "${YELLOW}Path to GitHub SSH private key:${NC}"
        read -r GITHUB_SSH_KEY
    fi

    # Validate
    if [ ! -f "$GITHUB_SSH_KEY" ]; then
        echo -e "${RED}Error: SSH key not found at ${GITHUB_SSH_KEY}${NC}"
        return 1
    fi

    echo -e "${GREEN}Using SSH key: ${GITHUB_SSH_KEY}${NC}"
    export GITHUB_SSH_KEY
    return 0
}

#######################################
# Test SSH connectivity to a host.
#
# Arguments:
#   $1 - host : Hostname or IP to connect to
#   $2 - user : SSH username
#   $3 - key  : Path to SSH private key (optional, empty string to skip)
#
# Returns:
#   0 if connection succeeds, 1 if it fails
#
# Example:
#   validate_ssh_connection "10.83.3.190" "deploy" ""
#   validate_ssh_connection "10.83.3.190" "deploy" "/home/user/.ssh/id_ed25519"
#######################################
validate_ssh_connection() {
    local host="$1"
    local user="$2"
    local key="${3:-}"

    local ssh_opts="-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null -o ConnectTimeout=30 -o BatchMode=yes"

    local ssh_cmd="ssh ${ssh_opts}"
    if [ -n "$key" ]; then
        ssh_cmd="${ssh_cmd} -i ${key}"
    fi

    if ${ssh_cmd} "${user}@${host}" "echo ok" 2>/dev/null | grep -q ok; then
        echo -e "${GREEN}SSH connection to ${user}@${host} successful${NC}"
        return 0
    else
        echo -e "${RED}SSH connection to ${user}@${host} failed${NC}"
        return 1
    fi
}
