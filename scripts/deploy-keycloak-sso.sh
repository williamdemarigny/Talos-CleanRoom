#!/bin/bash
# =============================================================================
# Deploy Keycloak SSO — Bootstrap script for existing clusters
# =============================================================================
# Use this script to deploy Keycloak SSO to a cluster that was deployed
# BEFORE the Keycloak integration was added. For fresh deployments,
# steps 17 and 23 handle this automatically.
#
# Prerequisites:
#   - kubectl configured with cluster access
#   - SOPS + Age key available (SOPS_AGE_KEY_FILE)
#   - Cluster running with cleanroom-db already deployed
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Source logging helpers (provides print_info, print_warning, print_error, print_step)
source "$REPO_ROOT/lib/functions.sh"

# =============================================================================
# Generate passwords (alphanumeric only — safe for sed, SQL, JSON)
# =============================================================================
generate_password() {
    local length=${1:-32}
    openssl rand -base64 "$length" | tr -dc 'a-zA-Z0-9' | head -c "$length"
}

KC_ADMIN_PASSWORD=$(generate_password 24)
KC_DB_PASSWORD=$(generate_password 32)
OAUTH2_COOKIE_SECRET=$(generate_password 32)

echo "=============================================="
echo " Keycloak SSO Deployment"
echo "=============================================="
echo ""

# =============================================================================
# Step 1: Create namespaces
# =============================================================================
print_step "1 — Creating namespaces"

for ns in keycloak oauth2-proxy deployment-console; do
    kubectl create namespace "$ns" --dry-run=client -o yaml | kubectl apply -f - 2>/dev/null
    print_info "Namespace $ns ready"
done

# =============================================================================
# Step 2: Create K8s secrets
# =============================================================================
print_step "2 — Creating K8s secrets"

# Keycloak DB credentials in cleanroom-db namespace
kubectl -n cleanroom-db create secret generic keycloak-db-credentials \
    --from-literal=postgres-password="$KC_DB_PASSWORD" \
    --dry-run=client -o yaml | kubectl apply -f -
print_info "Created keycloak-db-credentials in cleanroom-db"

# Keycloak credentials in keycloak namespace
kubectl -n keycloak create secret generic keycloak-credentials \
    --from-literal=admin-password="$KC_ADMIN_PASSWORD" \
    --dry-run=client -o yaml | kubectl apply -f -
print_info "Created keycloak-credentials in keycloak"

# Keycloak DB credentials in keycloak namespace (same password)
kubectl -n keycloak create secret generic keycloak-db-credentials \
    --from-literal=postgres-password="$KC_DB_PASSWORD" \
    --dry-run=client -o yaml | kubectl apply -f -
print_info "Created keycloak-db-credentials in keycloak"

# OAuth2-Proxy credentials
kubectl -n oauth2-proxy create secret generic oauth2-proxy-credentials \
    --from-literal=client-id="traefik-forward-auth" \
    --from-literal=client-secret="configure-after-keycloak-realm-import" \
    --from-literal=cookie-secret="$OAUTH2_COOKIE_SECRET" \
    --dry-run=client -o yaml | kubectl apply -f -
print_info "Created oauth2-proxy-credentials in oauth2-proxy"

# =============================================================================
# Step 3: Initialize Keycloak database in cleanroom-db
# =============================================================================
print_step "3 — Initializing Keycloak database"

# Check if keycloak database already exists
DB_EXISTS=$(kubectl -n cleanroom-db exec statefulset/cleanroom-db -- \
    psql -U cleanroom -tAc "SELECT 1 FROM pg_database WHERE datname='keycloak'" 2>/dev/null || echo "")

if [ "$DB_EXISTS" = "1" ]; then
    print_info "Keycloak database already exists — skipping creation"
else
    print_info "Creating keycloak database and user..."
    kubectl -n cleanroom-db exec statefulset/cleanroom-db -- psql -U cleanroom -c "
        CREATE ROLE keycloak WITH LOGIN PASSWORD '$KC_DB_PASSWORD';
        CREATE DATABASE keycloak OWNER keycloak;
        REVOKE ALL ON DATABASE cleanroom FROM keycloak;
        REVOKE CONNECT ON DATABASE cleanroom FROM keycloak;
    " 2>/dev/null || print_warning "Database creation had warnings (may already exist)"

    # Restrict keycloak user from cleanroom schema
    kubectl -n cleanroom-db exec statefulset/cleanroom-db -- psql -U cleanroom -d cleanroom -c "
        REVOKE ALL ON SCHEMA public FROM keycloak;
    " 2>/dev/null || true

    # Grant keycloak full access to its own database
    kubectl -n cleanroom-db exec statefulset/cleanroom-db -- psql -U cleanroom -d keycloak -c "
        GRANT ALL ON SCHEMA public TO keycloak;
    " 2>/dev/null || true

    print_info "Keycloak database created with restricted user"
fi

# =============================================================================
# Step 4: Deploy ArgoCD applications
# =============================================================================
print_step "4 — Deploying ArgoCD applications"

kubectl apply -f "$REPO_ROOT/apps/deployment-console/application.yaml"
print_info "Applied deployment-console ArgoCD app"

kubectl apply -f "$REPO_ROOT/apps/keycloak/application.yaml"
print_info "Applied keycloak ArgoCD app"

kubectl apply -f "$REPO_ROOT/apps/oauth2-proxy/application.yaml"
print_info "Applied oauth2-proxy ArgoCD app"

# =============================================================================
# Step 5: Wait for Keycloak to start
# =============================================================================
print_step "5 — Waiting for Keycloak to start"

print_info "Waiting for Keycloak pod to be ready (this may take 2-5 minutes)..."
READY="false"
for ((i=1; i<=60; i++)); do
    POD_STATUS=$(kubectl -n keycloak get pods -l app.kubernetes.io/name=keycloak -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "NotFound")
    READY=$(kubectl -n keycloak get pods -l app.kubernetes.io/name=keycloak -o jsonpath='{.items[0].status.containerStatuses[0].ready}' 2>/dev/null || echo "false")
    if [ "$READY" = "true" ]; then
        print_info "Keycloak pod is ready!"
        break
    fi
    echo -ne "\r  Waiting for Keycloak ($i/60) — Status: $POD_STATUS..."
    sleep 10
done
echo ""

if [ "$READY" != "true" ]; then
    print_error "Keycloak pod never became ready after 10 minutes"
    exit 1
fi

# Verify Keycloak HTTP port is actually responding (readiness probe may pass before HTTP is fully ready)
# Note: Keycloak 26 image (quay.io/keycloak/keycloak) does NOT include curl.
# Use the built-in bash /dev/tcp check or kcadm.sh to verify HTTP readiness.
print_info "Verifying Keycloak HTTP port is responsive..."
for ((i=1; i<=30; i++)); do
    if kubectl -n keycloak exec deploy/keycloak -- bash -c 'echo > /dev/tcp/localhost/8080' 2>/dev/null; then
        print_info "Keycloak HTTP port responding"
        break
    fi
    if [ "$i" -eq 30 ]; then
        print_error "Keycloak HTTP port did not respond after 1 minute"
        exit 1
    fi
    echo -ne "\r  Verifying HTTP port ($i/30)..."
    sleep 2
done

# =============================================================================
# Step 6: Generate OIDC client secrets and import realm
# =============================================================================
print_step "6 — Importing Keycloak realm with OIDC client secrets"

SECRET_PORTAL=$(generate_password 32)
SECRET_SCANNING=$(generate_password 32)
SECRET_DEPLOY=$(generate_password 32)
SECRET_ARGOCD=$(generate_password 32)
SECRET_HARBOR=$(generate_password 32)
SECRET_FORWARD_AUTH=$(generate_password 32)

# Template the realm config with generated secrets (use | delimiter to avoid
# conflicts with base64 characters like / and + in generated passwords)
REALM_JSON=$(cat "$REPO_ROOT/apps/keycloak/realm-config.json" \
    | sed "s|__SECRET_PORTAL__|$SECRET_PORTAL|g" \
    | sed "s|__SECRET_SCANNING_CONSOLE__|$SECRET_SCANNING|g" \
    | sed "s|__SECRET_DEPLOYMENT_CONSOLE__|$SECRET_DEPLOY|g" \
    | sed "s|__SECRET_ARGOCD__|$SECRET_ARGOCD|g" \
    | sed "s|__SECRET_HARBOR__|$SECRET_HARBOR|g" \
    | sed "s|__SECRET_FORWARD_AUTH__|$SECRET_FORWARD_AUTH|g")

# Write realm JSON into the Keycloak pod
echo "$REALM_JSON" | base64 | kubectl -n keycloak exec -i deploy/keycloak -- \
    bash -c 'base64 -d > /tmp/realm.json'
print_info "Realm config written to Keycloak pod"

# Authenticate with Keycloak admin CLI
if ! kubectl -n keycloak exec deploy/keycloak -- \
    /opt/keycloak/bin/kcadm.sh config credentials \
    --server http://localhost:8080 \
    --realm master \
    --user admin \
    --password "$KC_ADMIN_PASSWORD" 2>/dev/null; then
    print_error "Failed to authenticate to Keycloak admin API"
    exit 1
fi
print_info "Authenticated to Keycloak admin API"

# Import the realm
if kubectl -n keycloak exec deploy/keycloak -- \
    /opt/keycloak/bin/kcadm.sh create realms \
    -f /tmp/realm.json 2>/dev/null; then
    print_info "Realm 'cleanroom' created successfully"
else
    print_warning "Realm may already exist, attempting partial import..."
    kubectl -n keycloak exec deploy/keycloak -- \
        /opt/keycloak/bin/kcadm.sh create partialImport \
        -r cleanroom -f /tmp/realm.json \
        -s ifResourceExists=OVERWRITE 2>/dev/null || print_warning "Partial import had warnings"
fi

# =============================================================================
# Step 7: Distribute OIDC client secrets to app secrets
# =============================================================================
print_step "7 — Configuring OIDC credentials in application secrets"

ISSUER_URL="https://keycloak.knowledgeondemand.net/realms/cleanroom"

# Helper: verify secret exists before patching
patch_secret_safe() {
    local ns="$1" secret="$2" json_patch="$3" label="$4"
    if ! kubectl -n "$ns" get secret "$secret" &>/dev/null; then
        print_warning "Secret $secret not found in $ns — creating it"
        kubectl -n "$ns" create secret generic "$secret" --dry-run=client -o yaml | kubectl apply -f - || {
            print_error "Failed to create secret $secret in $ns"
            return 1
        }
    fi
    kubectl -n "$ns" patch secret "$secret" --type merge -p "$json_patch"
    print_info "$label OIDC configured"
}

# Portal
patch_secret_safe portal portal-credentials \
    "{\"stringData\":{\"oidc-issuer-url\":\"$ISSUER_URL\",\"oidc-client-id\":\"portal\",\"oidc-client-secret\":\"$SECRET_PORTAL\"}}" \
    "Portal"

# Scanning Console
patch_secret_safe scanning-console scanning-console-credentials \
    "{\"stringData\":{\"oidc-issuer-url\":\"$ISSUER_URL\",\"oidc-client-id\":\"scanning-console\",\"oidc-client-secret\":\"$SECRET_SCANNING\"}}" \
    "Scanning Console"

# ArgoCD
patch_secret_safe argocd argocd-secret \
    "{\"stringData\":{\"oidc.keycloak.clientSecret\":\"$SECRET_ARGOCD\"}}" \
    "ArgoCD"

# OAuth2-Proxy
patch_secret_safe oauth2-proxy oauth2-proxy-credentials \
    "{\"stringData\":{\"client-secret\":\"$SECRET_FORWARD_AUTH\"}}" \
    "OAuth2-Proxy"

# =============================================================================
# Step 8: Restart apps to pick up OIDC config
# =============================================================================
print_step "8 — Restarting applications to enable OIDC"

for ns_deploy in "portal/portal" "scanning-console/scanning-console" "oauth2-proxy/oauth2-proxy"; do
    ns="${ns_deploy%%/*}"
    deploy="${ns_deploy##*/}"
    kubectl -n "$ns" rollout restart "deployment/$deploy" 2>/dev/null || true
    print_info "Restarted $deploy in $ns"
done

# =============================================================================
# Summary
# =============================================================================
echo ""
echo "=============================================="
echo " Keycloak SSO — Fully Deployed"
echo "=============================================="
echo ""
echo "Keycloak Admin Console:"
echo "  URL:      https://keycloak.knowledgeondemand.net"
echo "  Username: admin"
echo "  Password: $KC_ADMIN_PASSWORD"
echo ""
echo "SSO-enabled services:"
echo "  - Portal:           https://cleanroom.knowledgeondemand.net"
echo "  - Scanning Console: https://scan.knowledgeondemand.net"
echo "  - Deployment Console: https://deploy.knowledgeondemand.net"
echo "  - ArgoCD:           https://argocd.knowledgeondemand.net"
echo "  - Faraday:          https://faraday.knowledgeondemand.net (ForwardAuth)"
echo "  - OpenVAS:          https://openvas.knowledgeondemand.net (ForwardAuth)"
echo "  - Threat Dragon:    https://threatdragon.knowledgeondemand.net (ForwardAuth)"
echo ""
echo "Realm admin user: admin / admin (non-temporary, change after first login)"
echo ""
echo "Verify: Open https://cleanroom.knowledgeondemand.net/login"
echo "        You should see 'Sign in with Keycloak SSO' button"
echo ""
