#!/bin/bash
#######################################
# generate-secrets.sh - Generate Kubernetes secrets for Talos CleanRoom
#
# This script generates secure passwords for all applications and creates
# SOPS-encrypted Kubernetes Secret manifests.
#
# Prerequisites:
#   - sops: For encrypting secrets
#   - openssl: For generating random passwords
#   - python3: For generating bcrypt hashes (ArgoCD)
#   - htpasswd or python: For generating SHA hashes (Traefik)
#
# Usage:
#   ./generate-secrets.sh [--dry-run]
#
# Options:
#   --dry-run    Show what would be generated without writing files
#
# Output:
#   Creates SOPS-encrypted secret files in each project directory
#
# Environment Variables:
#   SOPS_AGE_KEY_FILE - Path to SOPS age key (default: ~/.config/sops/age/keys.txt)
#######################################

set -euo pipefail

# Colors for output
readonly GREEN='\033[0;32m'
readonly BLUE='\033[0;34m'
readonly YELLOW='\033[1;33m'
readonly RED='\033[0;31m'
readonly NC='\033[0m'

# Logging functions
print_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error()   { echo -e "${RED}[ERROR]${NC} $1" >&2; }

# Script directory and paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECTS_DIR="${SCRIPT_DIR}/../apps"

# Configuration
DRY_RUN=false
PASSWORD_LENGTH=24

#######################################
# Parse command line arguments
#######################################
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            --help|-h)
                echo "Usage: $0 [--dry-run]"
                echo ""
                echo "Options:"
                echo "  --dry-run    Show what would be generated without writing files"
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
}

#######################################
# Find a working Python interpreter
# On Windows, 'python3' may be a broken Store alias;
# fall back to 'python' if it reports version 3.x
#######################################
PYTHON=""
find_python() {
    if python3 --version &>/dev/null; then
        PYTHON="python3"
    elif python --version 2>&1 | grep -q "Python 3"; then
        PYTHON="python"
    fi
}

#######################################
# Check prerequisites
#######################################
check_prerequisites() {
    local missing=()

    for cmd in sops openssl; do
        if ! command -v "$cmd" &> /dev/null; then
            missing+=("$cmd")
        fi
    done

    find_python
    if [[ -z "$PYTHON" ]]; then
        missing+=("python3")
    fi

    if [[ ${#missing[@]} -gt 0 ]]; then
        print_error "Missing required commands: ${missing[*]}"
        exit 1
    fi

    # Check SOPS age key
    if [[ ! -f "${SOPS_AGE_KEY_FILE:-$HOME/.config/sops/age/keys.txt}" ]]; then
        print_error "SOPS age key not found. Set SOPS_AGE_KEY_FILE or create ~/.config/sops/age/keys.txt"
        exit 1
    fi

    print_success "Prerequisites check passed (python: $PYTHON)"
}

#######################################
# Generate a random password
# Arguments:
#   $1 - Password length (default: 24)
#######################################
generate_password() {
    local length="${1:-$PASSWORD_LENGTH}"
    openssl rand -base64 48 | tr -dc 'a-zA-Z0-9' | head -c "$length"
}

#######################################
# Generate bcrypt hash for ArgoCD
# Arguments:
#   $1 - Password to hash
#######################################
generate_bcrypt_hash() {
    local password="$1"
    $PYTHON -c "import bcrypt; print(bcrypt.hashpw(b'${password}', bcrypt.gensalt(10)).decode())"
}

#######################################
# Generate SHA hash for Traefik basic auth
# Arguments:
#   $1 - Username
#   $2 - Password
#######################################
generate_sha_hash() {
    local username="$1"
    local password="$2"
    local sha_hash
    sha_hash=$($PYTHON -c "import hashlib; import base64; print('{SHA}' + base64.b64encode(hashlib.sha1(b'${password}').digest()).decode())")
    echo "${username}:${sha_hash}"
}

#######################################
# Write and encrypt a secret file
# Arguments:
#   $1 - File path
#   $2 - Content
#######################################
write_encrypted_secret() {
    local filepath="$1"
    local content="$2"
    local dir
    dir=$(dirname "$filepath")

    if [[ "$DRY_RUN" == "true" ]]; then
        print_info "[DRY-RUN] Would write: $filepath"
        echo "---"
        echo "$content"
        echo "---"
        return
    fi

    # Write unencrypted first
    echo "$content" > "$filepath"

    # Encrypt in place with SOPS
    if sops -e -i "$filepath" 2>/dev/null; then
        print_success "Created: $filepath"
    else
        print_error "Failed to encrypt: $filepath"
        rm -f "$filepath"
        return 1
    fi
}

#######################################
# Generate Metasploit secrets
#######################################
generate_metasploit_secrets() {
    print_info "Generating Metasploit secrets..."

    local db_password rpc_password
    db_password=$(generate_password)
    rpc_password=$(generate_password)

    local content="# Metasploit Database and RPC Credentials
# Generated by generate-secrets.sh - DO NOT COMMIT UNENCRYPTED
---
apiVersion: v1
kind: Secret
metadata:
  name: metasploit-db-credentials
  namespace: metasploit
  labels:
    app.kubernetes.io/name: metasploit
    app.kubernetes.io/component: credentials
    app.kubernetes.io/managed-by: generate-secrets
type: Opaque
stringData:
  password: \"${db_password}\"
---
apiVersion: v1
kind: Secret
metadata:
  name: metasploit-rpc-credentials
  namespace: metasploit
  labels:
    app.kubernetes.io/name: metasploit
    app.kubernetes.io/component: credentials
    app.kubernetes.io/managed-by: generate-secrets
type: Opaque
stringData:
  password: \"${rpc_password}\""

    write_encrypted_secret "${PROJECTS_DIR}/metasploit/secrets.sops.yaml" "$content"

    print_info "  DB Password: ${db_password:0:4}****"
    print_info "  RPC Password: ${rpc_password:0:4}****"
}

#######################################
# Generate Faraday secrets
#######################################
generate_faraday_secrets() {
    print_info "Generating Faraday secrets..."

    local db_password admin_password
    db_password=$(generate_password)
    admin_password="admin"  # Default admin password — change after first login

    local content="# Faraday Database and Admin Credentials
# Generated by generate-secrets.sh - DO NOT COMMIT UNENCRYPTED
---
apiVersion: v1
kind: Secret
metadata:
  name: faraday-credentials
  namespace: faraday
  labels:
    app.kubernetes.io/name: faraday
    app.kubernetes.io/component: credentials
    app.kubernetes.io/managed-by: generate-secrets
type: Opaque
stringData:
  postgres-password: \"${db_password}\"
  admin-password: \"${admin_password}\""

    write_encrypted_secret "${PROJECTS_DIR}/faraday/secrets.sops.yaml" "$content"

    print_info "  DB Password: ${db_password:0:4}****"
    print_info "  Admin Password: ${admin_password:0:4}****"
}

#######################################
# Generate OpenVAS secrets
#######################################
generate_openvas_secrets() {
    print_info "Generating OpenVAS secrets..."

    local admin_password db_password
    admin_password="admin"  # Default admin password — change after first login
    db_password=$(generate_password)

    local content="# OpenVAS/Greenbone Credentials
# Generated by generate-secrets.sh - DO NOT COMMIT UNENCRYPTED
---
apiVersion: v1
kind: Secret
metadata:
  name: openvas-credentials
  namespace: openvas
  labels:
    app.kubernetes.io/name: openvas
    app.kubernetes.io/component: credentials
    app.kubernetes.io/managed-by: generate-secrets
type: Opaque
stringData:
  admin-password: \"${admin_password}\"
  postgres-password: \"${db_password}\""

    write_encrypted_secret "${PROJECTS_DIR}/openvas/secrets.sops.yaml" "$content"

    print_info "  Admin Password: ${admin_password:0:4}****"
    print_info "  DB Password: ${db_password:0:4}****"
}

#######################################
# Generate Traefik basic auth secrets
#######################################
generate_traefik_secrets() {
    print_info "Generating Traefik basic auth secrets..."

    local admin_password users_entry
    admin_password=$(generate_password)
    users_entry=$(generate_sha_hash "admin" "$admin_password")

    local content="# Traefik Basic Auth Credentials
# Generated by generate-secrets.sh - DO NOT COMMIT UNENCRYPTED
---
apiVersion: v1
kind: Secret
metadata:
  name: basic-auth-secret
  namespace: traefik
  labels:
    app.kubernetes.io/name: traefik
    app.kubernetes.io/component: basic-auth
    app.kubernetes.io/managed-by: generate-secrets
type: Opaque
stringData:
  users: \"${users_entry}\""

    write_encrypted_secret "${PROJECTS_DIR}/traefik/basic-auth-secret.sops.yaml" "$content"

    print_info "  Username: admin"
    print_info "  Password: ${admin_password:0:4}****"
    print_warning "  Save this password - it provides access to Traefik and ArgoCD dashboards"
}

#######################################
# Generate ArgoCD secrets
#######################################
generate_argocd_secrets() {
    print_info "Generating ArgoCD secrets..."

    local admin_password bcrypt_hash
    admin_password="admin"  # Default admin password — change after first login
    bcrypt_hash=$(generate_bcrypt_hash "$admin_password")

    local content="# ArgoCD Admin Credentials
# Generated by generate-secrets.sh - DO NOT COMMIT UNENCRYPTED
# Apply AFTER ArgoCD is installed
---
apiVersion: v1
kind: Secret
metadata:
  name: argocd-secret-override
  namespace: argocd
  labels:
    app.kubernetes.io/name: argocd
    app.kubernetes.io/component: server
    app.kubernetes.io/managed-by: generate-secrets
type: Opaque
stringData:
  admin.password: \"${bcrypt_hash}\"
  admin.passwordMtime: \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\""

    write_encrypted_secret "${SCRIPT_DIR}/../apps/argocd/secrets.sops.yaml" "$content"

    print_info "  Username: admin"
    print_info "  Password: ${admin_password:0:4}****"
    print_warning "  Save this password - it provides access to ArgoCD"
}

#######################################
# Generate CleanRoom DB secrets
#######################################
generate_cleanroom_db_secrets() {
    print_info "Generating CleanRoom DB secrets..."

    local db_password
    db_password=$(generate_password)

    local content="# CleanRoom Database Credentials
# Generated by generate-secrets.sh - DO NOT COMMIT UNENCRYPTED
# Required by: cleanroom-db StatefulSet, scanning-console Deployment
---
apiVersion: v1
kind: Secret
metadata:
  name: cleanroom-db-credentials
  namespace: cleanroom-db
  labels:
    app.kubernetes.io/name: cleanroom-db
    app.kubernetes.io/component: database
    app.kubernetes.io/managed-by: generate-secrets
type: Opaque
stringData:
  postgres-password: \"${db_password}\""

    write_encrypted_secret "${PROJECTS_DIR}/cleanroom-db/secrets.sops.yaml" "$content"

    # Return password for use by scanning-console secret
    CLEANROOM_DB_PASSWORD="$db_password"
    print_info "  DB Password: ${db_password:0:4}****"
}

#######################################
# Generate Scanning Console secrets
#######################################
generate_scanning_console_secrets() {
    print_info "Generating Scanning Console secrets..."

    local secret_key admin_password admin_hash db_url
    secret_key=$(generate_password 48)
    admin_password="admin"  # Default admin password — change after first login
    admin_hash=$(generate_bcrypt_hash "$admin_password")

    # Use the DB password from cleanroom-db generation
    local db_password="${CLEANROOM_DB_PASSWORD:-$(generate_password)}"
    db_url="postgresql+asyncpg://cleanroom:${db_password}@cleanroom-db.cleanroom-db.svc.cluster.local:5432/cleanroom"

    local content="# Scanning Console Credentials
# Generated by generate-secrets.sh - DO NOT COMMIT UNENCRYPTED
---
apiVersion: v1
kind: Secret
metadata:
  name: scanning-console-credentials
  namespace: scanning-console
  labels:
    app.kubernetes.io/name: scanning-console
    app.kubernetes.io/component: security-console
    app.kubernetes.io/managed-by: generate-secrets
type: Opaque
stringData:
  secret-key: \"${secret_key}\"
  database-url: \"${db_url}\"
  admin-password-hash: \"${admin_hash}\""

    write_encrypted_secret "${PROJECTS_DIR}/scanning-console/secrets.sops.yaml" "$content"

    print_info "  Admin Password: ${admin_password:0:4}****"
    print_info "  SECRET_KEY: ${secret_key:0:4}****"
    print_warning "  Save the admin password and SECRET_KEY!"
    print_warning "  SECRET_KEY must match across Portal and Deployment Console for SSO"

    # Export for portal to reuse
    SHARED_SECRET_KEY="$secret_key"
    SHARED_ADMIN_HASH="$admin_hash"
}

#######################################
# Generate Portal secrets
#######################################
generate_portal_secrets() {
    print_info "Generating Portal secrets..."

    # Reuse the same SECRET_KEY and admin hash for cross-app SSO
    local secret_key="${SHARED_SECRET_KEY:-$(generate_password 48)}"
    local admin_hash="${SHARED_ADMIN_HASH:-}"

    if [[ -z "$admin_hash" ]]; then
        local admin_password="admin"  # Default admin password — change after first login
        admin_hash=$(generate_bcrypt_hash "$admin_password")
        print_info "  Admin Password: admin (default)"
    else
        print_info "  Admin hash: reused from Scanning Console (same credentials)"
    fi

    local content="# Unified Portal Credentials
# Generated by generate-secrets.sh - DO NOT COMMIT UNENCRYPTED
---
apiVersion: v1
kind: Secret
metadata:
  name: portal-credentials
  namespace: portal
  labels:
    app.kubernetes.io/name: portal
    app.kubernetes.io/component: web-portal
    app.kubernetes.io/managed-by: generate-secrets
type: Opaque
stringData:
  secret-key: \"${secret_key}\"
  admin-password-hash: \"${admin_hash}\""

    write_encrypted_secret "${PROJECTS_DIR}/portal/secrets.sops.yaml" "$content"

    print_info "  SECRET_KEY: ${secret_key:0:4}**** (shared with Scanning Console)"
}

#######################################
# Generate Threat Dragon secrets
#######################################
generate_threat_dragon_secrets() {
    print_info "Generating Threat Dragon secrets..."

    local encryption_key jwt_signing_key jwt_refresh_key
    encryption_key=$(openssl rand -hex 16)
    jwt_signing_key=$(openssl rand -hex 16)
    jwt_refresh_key=$(openssl rand -hex 16)

    local content="# Threat Dragon Session and JWT Credentials
# Generated by generate-secrets.sh - DO NOT COMMIT UNENCRYPTED
---
apiVersion: v1
kind: Secret
metadata:
  name: threat-dragon-secrets
  namespace: threat-dragon
  labels:
    app.kubernetes.io/name: threat-dragon
    app.kubernetes.io/component: credentials
    app.kubernetes.io/managed-by: generate-secrets
type: Opaque
stringData:
  encryption-keys: \"${encryption_key}\"
  jwt-signing-key: \"${jwt_signing_key}\"
  jwt-refresh-signing-key: \"${jwt_refresh_key}\""

    write_encrypted_secret "${PROJECTS_DIR}/threat-dragon/secrets.sops.yaml" "$content"

    print_info "  Encryption Key: ${encryption_key:0:4}****"
    print_info "  JWT Signing Key: ${jwt_signing_key:0:4}****"
    print_info "  JWT Refresh Key: ${jwt_refresh_key:0:4}****"
}

#######################################
# Main function
#######################################

# Shared state between generators (for cross-app SSO key sharing)
CLEANROOM_DB_PASSWORD=""
SHARED_SECRET_KEY=""
SHARED_ADMIN_HASH=""

main() {
    echo "=============================================="
    echo "  Talos CleanRoom - Secret Generation"
    echo "=============================================="
    echo ""

    parse_args "$@"
    check_prerequisites

    if [[ "$DRY_RUN" == "true" ]]; then
        print_warning "Running in dry-run mode - no files will be written"
    fi

    echo ""
    generate_metasploit_secrets
    echo ""
    generate_faraday_secrets
    echo ""
    generate_openvas_secrets
    echo ""
    generate_traefik_secrets
    echo ""
    generate_argocd_secrets
    echo ""
    generate_cleanroom_db_secrets
    echo ""
    generate_scanning_console_secrets
    echo ""
    generate_portal_secrets
    echo ""
    generate_threat_dragon_secrets
    echo ""

    echo "=============================================="
    if [[ "$DRY_RUN" == "true" ]]; then
        print_info "Dry run complete. Run without --dry-run to create files."
    else
        print_success "Secret generation complete!"
        echo ""
        echo "Next Steps:"
        echo "1. Commit the encrypted secret files to git"
        echo "2. Update deployments to reference the new secrets"
        echo "3. Apply secrets before deploying applications"
        echo ""
        print_warning "IMPORTANT: Save the passwords shown above!"
        print_warning "They are only displayed once and cannot be recovered."
    fi
    echo "=============================================="
}

main "$@"
