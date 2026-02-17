#!/bin/bash
#######################################
# Talos CleanRoom - Shared Shell Functions Library
#######################################
# This library provides common functions used across deployment scripts.
#
# Usage:
#   source "$(dirname "${BASH_SOURCE[0]}")/../lib/functions.sh"
#   # or with REPO_ROOT:
#   source "${REPO_ROOT}/Resources/IAC-DNS/lib/functions.sh"
#
# Functions provided:
#   - Color output: print_info, print_success, print_warning, print_error
#   - Prerequisites: command_exists, check_prerequisites
#   - Kubernetes: wait_for_deployment, wait_for_daemonset, wait_for_namespace
#   - Utilities: retry_command
#######################################

# Prevent multiple sourcing
[[ -n "${_TALOS_FUNCTIONS_LOADED:-}" ]] && return 0
readonly _TALOS_FUNCTIONS_LOADED=1

#######################################
# Color definitions
#######################################
readonly GREEN='\033[0;32m'
readonly BLUE='\033[0;34m'
readonly YELLOW='\033[1;33m'
readonly RED='\033[0;31m'
readonly CYAN='\033[0;36m'
readonly NC='\033[0m'  # No Color

#######################################
# Logging functions
# Arguments:
#   $1 - Message to print
#######################################
print_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error()   { echo -e "${RED}[ERROR]${NC} $1" >&2; }
print_step()    { echo -e "${CYAN}[STEP]${NC} $1"; }

#######################################
# Check if a command exists
# Arguments:
#   $1 - Command name to check
# Returns:
#   0 if command exists, 1 otherwise
#######################################
command_exists() {
    command -v "$1" &> /dev/null
}

#######################################
# Check multiple prerequisites
# Arguments:
#   $@ - List of commands to check
# Returns:
#   0 if all exist, 1 if any missing
#######################################
check_prerequisites() {
    local missing=()
    for cmd in "$@"; do
        if ! command_exists "$cmd"; then
            missing+=("$cmd")
        fi
    done

    if [[ ${#missing[@]} -gt 0 ]]; then
        print_error "Missing required commands: ${missing[*]}"
        return 1
    fi

    print_success "All prerequisites met"
    return 0
}

#######################################
# Wait for a Kubernetes namespace to exist
# Arguments:
#   $1 - Namespace name
#   $2 - Maximum attempts (default: 12)
#   $3 - Interval in seconds (default: 10)
# Returns:
#   0 if namespace exists, 1 if timeout
#######################################
wait_for_namespace() {
    local namespace="$1"
    local max_attempts="${2:-12}"
    local interval="${3:-10}"

    for ((i=1; i<=max_attempts; i++)); do
        if kubectl get namespace "$namespace" &> /dev/null; then
            print_success "Namespace '$namespace' exists"
            return 0
        fi
        print_info "Waiting for namespace '$namespace'... ($i/$max_attempts)"
        sleep "$interval"
    done

    print_error "Namespace '$namespace' not found after $max_attempts attempts"
    return 1
}

#######################################
# Wait for a Kubernetes deployment to be available
# Arguments:
#   $1 - Deployment name
#   $2 - Namespace
#   $3 - Timeout (default: 300s)
# Returns:
#   0 if available, 1 if timeout
#######################################
wait_for_deployment() {
    local deployment="$1"
    local namespace="$2"
    local timeout="${3:-300s}"

    # First attempt
    if kubectl wait --for=condition=available "deployment/${deployment}" \
        -n "${namespace}" \
        --timeout="${timeout}" 2>/dev/null; then
        print_success "${deployment} is available"
        return 0
    fi

    # Retry with delay if deployment doesn't exist yet
    print_warning "Waiting for ${deployment} deployment to be created..."
    sleep 30

    if kubectl wait --for=condition=available "deployment/${deployment}" \
        -n "${namespace}" \
        --timeout="${timeout}"; then
        print_success "${deployment} is available"
        return 0
    fi

    print_error "${deployment} did not become available within timeout"
    return 1
}

#######################################
# Wait for a DaemonSet to be fully ready
# Arguments:
#   $1 - DaemonSet name
#   $2 - Namespace
#   $3 - Maximum attempts (default: 36)
#   $4 - Interval in seconds (default: 10)
# Returns:
#   0 if ready, 1 if timeout
#######################################
wait_for_daemonset() {
    local daemonset="$1"
    local namespace="$2"
    local max_attempts="${3:-36}"
    local interval="${4:-10}"

    for ((i=1; i<=max_attempts; i++)); do
        local desired ready
        desired=$(kubectl get daemonset "${daemonset}" -n "${namespace}" \
            -o jsonpath='{.status.desiredNumberScheduled}' 2>/dev/null || echo "0")
        ready=$(kubectl get daemonset "${daemonset}" -n "${namespace}" \
            -o jsonpath='{.status.numberReady}' 2>/dev/null || echo "0")

        if [[ "$desired" -gt 0 && "$ready" -eq "$desired" ]]; then
            print_success "${daemonset}: ${ready}/${desired} pods ready"
            return 0
        fi

        print_info "${daemonset}: ${ready}/${desired} ready... ($i/$max_attempts)"
        sleep "$interval"
    done

    print_error "${daemonset} did not become ready after $max_attempts attempts"
    return 1
}

#######################################
# Retry a command with exponential backoff
# Arguments:
#   $1 - Maximum attempts
#   $2 - Initial delay in seconds
#   $@ - Command to run
# Returns:
#   Exit code of the last command attempt
#######################################
retry_command() {
    local max_attempts="$1"
    local delay="$2"
    shift 2
    local cmd=("$@")

    local attempt=1
    while [[ $attempt -le $max_attempts ]]; do
        if "${cmd[@]}"; then
            return 0
        fi

        if [[ $attempt -lt $max_attempts ]]; then
            print_warning "Attempt $attempt failed, retrying in ${delay}s..."
            sleep "$delay"
            delay=$((delay * 2))  # Exponential backoff
        fi

        ((attempt++))
    done

    print_error "Command failed after $max_attempts attempts: ${cmd[*]}"
    return 1
}

#######################################
# Print a section header
# Arguments:
#   $1 - Section title
#######################################
print_section() {
    local title="$1"
    local width=60
    local padding=$(( (width - ${#title} - 2) / 2 ))

    echo ""
    printf '=%.0s' $(seq 1 $width)
    echo ""
    printf '%*s %s %*s\n' $padding '' "$title" $padding ''
    printf '=%.0s' $(seq 1 $width)
    echo ""
}

#######################################
# Confirm an action with the user
# Arguments:
#   $1 - Prompt message
# Returns:
#   0 if confirmed, 1 if declined
#######################################
confirm_action() {
    local prompt="${1:-Continue?}"
    local response

    read -r -p "${prompt} [y/N] " response
    case "$response" in
        [yY][eE][sS]|[yY])
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

#######################################
# Check if running as root
# Returns:
#   0 if root, 1 otherwise
#######################################
check_root() {
    if [[ $EUID -ne 0 ]]; then
        print_error "This script must be run as root"
        return 1
    fi
    return 0
}

#######################################
# Validate that a file exists
# Arguments:
#   $1 - File path
# Returns:
#   0 if exists, 1 otherwise
#######################################
require_file() {
    local filepath="$1"
    if [[ ! -f "$filepath" ]]; then
        print_error "Required file not found: $filepath"
        return 1
    fi
    return 0
}

#######################################
# Validate that a directory exists
# Arguments:
#   $1 - Directory path
# Returns:
#   0 if exists, 1 otherwise
#######################################
require_directory() {
    local dirpath="$1"
    if [[ ! -d "$dirpath" ]]; then
        print_error "Required directory not found: $dirpath"
        return 1
    fi
    return 0
}
