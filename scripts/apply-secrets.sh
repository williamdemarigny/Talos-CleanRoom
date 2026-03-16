#!/bin/bash
#######################################
# apply-secrets.sh - Decrypt and apply all SOPS-encrypted secrets to Kubernetes
#
# This script decrypts each *.sops.yaml secret and applies it to the cluster.
# Run AFTER generate-secrets.sh and BEFORE deploying applications.
#
# Prerequisites:
#   - sops: For decrypting secrets
#   - kubectl: Connected to the target cluster
#   - SOPS Age key available (SOPS_AGE_KEY_FILE or default location)
#
# Usage:
#   ./apply-secrets.sh [--dry-run] [--app <name>]
#
# Options:
#   --dry-run    Show what would be applied without executing
#   --app <name> Apply secrets for a single app only (e.g., --app metasploit)
#######################################

set -euo pipefail

# Colors
readonly GREEN='\033[0;32m'
readonly BLUE='\033[0;34m'
readonly YELLOW='\033[1;33m'
readonly RED='\033[0;31m'
readonly NC='\033[0m'

print_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error()   { echo -e "${RED}[ERROR]${NC} $1" >&2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPS_DIR="${SCRIPT_DIR}/../apps"

DRY_RUN=false
TARGET_APP=""

# All apps with SOPS-encrypted secrets and their file patterns
# Format: "app_dir:secret_file"
SECRET_FILES=(
    "argocd:secrets.sops.yaml"
    "traefik:basic-auth-secret.sops.yaml"
    "metasploit:secrets.sops.yaml"
    "faraday:secrets.sops.yaml"
    "openvas:secrets.sops.yaml"
    "cleanroom-db:secrets.sops.yaml"
    "scanning-console:secrets.sops.yaml"
    "portal:secrets.sops.yaml"
    "threat-dragon:secrets.sops.yaml"
)

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            --app)
                TARGET_APP="$2"
                shift 2
                ;;
            --help|-h)
                echo "Usage: $0 [--dry-run] [--app <name>]"
                echo ""
                echo "Options:"
                echo "  --dry-run    Show what would be applied without executing"
                echo "  --app <name> Apply secrets for a single app only"
                echo ""
                echo "Available apps:"
                for entry in "${SECRET_FILES[@]}"; do
                    echo "  ${entry%%:*}"
                done
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
}

check_prerequisites() {
    local missing=()

    for cmd in sops kubectl; do
        if ! command -v "$cmd" &> /dev/null; then
            missing+=("$cmd")
        fi
    done

    if [[ ${#missing[@]} -gt 0 ]]; then
        print_error "Missing required commands: ${missing[*]}"
        exit 1
    fi

    # Verify cluster connectivity
    if ! kubectl cluster-info &> /dev/null 2>&1; then
        print_error "Cannot connect to Kubernetes cluster. Check KUBECONFIG."
        exit 1
    fi

    # Check SOPS age key
    if [[ ! -f "${SOPS_AGE_KEY_FILE:-$HOME/.config/sops/age/keys.txt}" ]]; then
        print_error "SOPS age key not found. Set SOPS_AGE_KEY_FILE or create ~/.config/sops/age/keys.txt"
        exit 1
    fi

    print_success "Prerequisites check passed"
}

apply_secret() {
    local app_dir="$1"
    local secret_file="$2"
    local filepath="${APPS_DIR}/${app_dir}/${secret_file}"

    if [[ ! -f "$filepath" ]]; then
        print_warning "  Skipping ${app_dir}/${secret_file} (file not found — run generate-secrets.sh first)"
        return 0
    fi

    if [[ "$DRY_RUN" == "true" ]]; then
        print_info "  [DRY-RUN] Would apply: ${app_dir}/${secret_file}"
        sops -d "$filepath" | head -5
        echo "  ..."
        return 0
    fi

    if sops -d "$filepath" | kubectl apply -f - 2>/dev/null; then
        print_success "  Applied: ${app_dir}/${secret_file}"
    else
        print_error "  Failed to apply: ${app_dir}/${secret_file}"
        return 1
    fi
}

main() {
    echo "=============================================="
    echo "  Talos CleanRoom - Apply Secrets"
    echo "=============================================="
    echo ""

    parse_args "$@"
    check_prerequisites

    if [[ "$DRY_RUN" == "true" ]]; then
        print_warning "Running in dry-run mode — no changes will be applied"
    fi

    echo ""

    local applied=0
    local failed=0
    local skipped=0

    for entry in "${SECRET_FILES[@]}"; do
        local app_dir="${entry%%:*}"
        local secret_file="${entry#*:}"

        # Filter by target app if specified
        if [[ -n "$TARGET_APP" && "$app_dir" != "$TARGET_APP" ]]; then
            continue
        fi

        print_info "Processing ${app_dir}..."
        if apply_secret "$app_dir" "$secret_file"; then
            if [[ -f "${APPS_DIR}/${app_dir}/${secret_file}" ]]; then
                ((applied++))
            else
                ((skipped++))
            fi
        else
            ((failed++))
        fi
    done

    echo ""
    echo "=============================================="
    print_info "Applied: ${applied}, Skipped: ${skipped}, Failed: ${failed}"

    if [[ $failed -gt 0 ]]; then
        print_error "Some secrets failed to apply. Check errors above."
        exit 1
    fi

    if [[ "$DRY_RUN" == "false" ]]; then
        print_success "All secrets applied successfully!"
    fi
    echo "=============================================="
}

main "$@"
