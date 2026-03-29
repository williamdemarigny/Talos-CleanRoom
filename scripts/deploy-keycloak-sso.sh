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

# Source logging helpers
source "$REPO_ROOT/lib/functions.sh"

# =============================================================================
# Generate passwords
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
print_step "1" "Creating namespaces"

for ns in keycloak oauth2-proxy deployment-console; do
    kubectl create namespace "$ns" --dry-run=client -o yaml | kubectl apply -f - 2>/dev/null
    log_info "Namespace $ns ready"
done

# =============================================================================
# Step 2: Create K8s secrets
# =============================================================================
print_step "2" "Creating K8s secrets"

# Keycloak DB credentials in cleanroom-db namespace
kubectl -n cleanroom-db create secret generic keycloak-db-credentials \
    --from-literal=postgres-password="$KC_DB_PASSWORD" \
    --dry-run=client -o yaml | kubectl apply -f -
log_info "Created keycloak-db-credentials in cleanroom-db"

# Keycloak credentials in keycloak namespace
kubectl -n keycloak create secret generic keycloak-credentials \
    --from-literal=admin-password="$KC_ADMIN_PASSWORD" \
    --dry-run=client -o yaml | kubectl apply -f -
log_info "Created keycloak-credentials in keycloak"

# Keycloak DB credentials in keycloak namespace (same password)
kubectl -n keycloak create secret generic keycloak-db-credentials \
    --from-literal=postgres-password="$KC_DB_PASSWORD" \
    --dry-run=client -o yaml | kubectl apply -f -
log_info "Created keycloak-db-credentials in keycloak"

# OAuth2-Proxy credentials
kubectl -n oauth2-proxy create secret generic oauth2-proxy-credentials \
    --from-literal=client-secret="configure-after-keycloak-realm-import" \
    --from-literal=cookie-secret="$OAUTH2_COOKIE_SECRET" \
    --dry-run=client -o yaml | kubectl apply -f -
log_info "Created oauth2-proxy-credentials in oauth2-proxy"

# =============================================================================
# Step 3: Initialize Keycloak database in cleanroom-db
# =============================================================================
print_step "3" "Initializing Keycloak database"

# Check if keycloak database already exists
DB_EXISTS=$(kubectl -n cleanroom-db exec statefulset/cleanroom-db -- \
    psql -U cleanroom -tAc "SELECT 1 FROM pg_database WHERE datname='keycloak'" 2>/dev/null || echo "")

if [ "$DB_EXISTS" = "1" ]; then
    log_info "Keycloak database already exists — skipping creation"
else
    log_info "Creating keycloak database and user..."
    kubectl -n cleanroom-db exec statefulset/cleanroom-db -- psql -U cleanroom -c "
        CREATE ROLE keycloak WITH LOGIN PASSWORD '$KC_DB_PASSWORD';
        CREATE DATABASE keycloak OWNER keycloak;
        REVOKE ALL ON DATABASE cleanroom FROM keycloak;
        REVOKE CONNECT ON DATABASE cleanroom FROM keycloak;
    " 2>/dev/null || log_warn "Database creation had warnings (may already exist)"

    # Restrict keycloak user from cleanroom schema
    kubectl -n cleanroom-db exec statefulset/cleanroom-db -- psql -U cleanroom -d cleanroom -c "
        REVOKE ALL ON SCHEMA public FROM keycloak;
    " 2>/dev/null || true

    # Grant keycloak full access to its own database
    kubectl -n cleanroom-db exec statefulset/cleanroom-db -- psql -U cleanroom -d keycloak -c "
        GRANT ALL ON SCHEMA public TO keycloak;
    " 2>/dev/null || true

    log_info "Keycloak database created with restricted user"
fi

# =============================================================================
# Step 4: Deploy ArgoCD applications
# =============================================================================
print_step "4" "Deploying ArgoCD applications"

kubectl apply -f "$REPO_ROOT/apps/deployment-console/application.yaml"
log_info "Applied deployment-console ArgoCD app"

kubectl apply -f "$REPO_ROOT/apps/keycloak/application.yaml"
log_info "Applied keycloak Helm ArgoCD app"

kubectl apply -f "$REPO_ROOT/apps/keycloak/application-manifests.yaml"
log_info "Applied keycloak IngressRoute ArgoCD app"

kubectl apply -f "$REPO_ROOT/apps/oauth2-proxy/application.yaml"
log_info "Applied oauth2-proxy ArgoCD app"

# =============================================================================
# Step 5: Wait for Keycloak to start
# =============================================================================
print_step "5" "Waiting for Keycloak to start"

log_info "Waiting for Keycloak pod to be ready (this may take 2-5 minutes)..."
for ((i=1; i<=60; i++)); do
    POD_STATUS=$(kubectl -n keycloak get pods -l app.kubernetes.io/name=keycloak -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "NotFound")
    READY=$(kubectl -n keycloak get pods -l app.kubernetes.io/name=keycloak -o jsonpath='{.items[0].status.containerStatuses[0].ready}' 2>/dev/null || echo "false")
    if [ "$READY" = "true" ]; then
        log_info "Keycloak pod is ready!"
        break
    fi
    echo -ne "\r  Waiting for Keycloak ($i/60) — Status: $POD_STATUS..."
    sleep 10
done
echo ""

# =============================================================================
# Step 6: Generate OIDC client secrets and import realm
# =============================================================================
print_step "6" "Importing Keycloak realm with OIDC client secrets"

SECRET_PORTAL=$(generate_password 32)
SECRET_SCANNING=$(generate_password 32)
SECRET_DEPLOY=$(generate_password 32)
SECRET_ARGOCD=$(generate_password 32)
SECRET_HARBOR=$(generate_password 32)
SECRET_FORWARD_AUTH=$(generate_password 32)

# Template the realm config with generated secrets
REALM_JSON=$(cat "$REPO_ROOT/apps/keycloak/realm-config.json" \
    | sed "s/__SECRET_PORTAL__/$SECRET_PORTAL/g" \
    | sed "s/__SECRET_SCANNING_CONSOLE__/$SECRET_SCANNING/g" \
    | sed "s/__SECRET_DEPLOYMENT_CONSOLE__/$SECRET_DEPLOY/g" \
    | sed "s/__SECRET_ARGOCD__/$SECRET_ARGOCD/g" \
    | sed "s/__SECRET_HARBOR__/$SECRET_HARBOR/g" \
    | sed "s/__SECRET_FORWARD_AUTH__/$SECRET_FORWARD_AUTH/g")

# Write realm JSON into the Keycloak pod
echo "$REALM_JSON" | base64 | kubectl -n keycloak exec -i deploy/keycloak -- \
    bash -c 'base64 -d > /tmp/realm.json'
log_info "Realm config written to Keycloak pod"

# Authenticate with Keycloak admin CLI
kubectl -n keycloak exec deploy/keycloak -- \
    /opt/bitnami/keycloak/bin/kcadm.sh config credentials \
    --server http://localhost:8080 \
    --realm master \
    --user admin \
    --password "$KC_ADMIN_PASSWORD" 2>/dev/null
log_info "Authenticated to Keycloak admin API"

# Import the realm
if kubectl -n keycloak exec deploy/keycloak -- \
    /opt/bitnami/keycloak/bin/kcadm.sh create realms \
    -f /tmp/realm.json 2>/dev/null; then
    log_info "Realm 'cleanroom' created successfully"
else
    log_warn "Realm may already exist, attempting partial import..."
    kubectl -n keycloak exec deploy/keycloak -- \
        /opt/bitnami/keycloak/bin/kcadm.sh create partialImport \
        -r cleanroom -f /tmp/realm.json \
        -s ifResourceExists=OVERWRITE 2>/dev/null || log_warn "Partial import had warnings"
fi

# =============================================================================
# Step 7: Distribute OIDC client secrets to app secrets
# =============================================================================
print_step "7" "Configuring OIDC credentials in application secrets"

ISSUER_URL="https://keycloak.knowledgeondemand.net/realms/cleanroom"

# Portal
kubectl -n portal patch secret portal-credentials --type merge -p \
    "{\"stringData\":{\"oidc-issuer-url\":\"$ISSUER_URL\",\"oidc-client-id\":\"portal\",\"oidc-client-secret\":\"$SECRET_PORTAL\"}}" 2>/dev/null
log_info "Portal OIDC configured"

# Scanning Console
kubectl -n scanning-console patch secret scanning-console-credentials --type merge -p \
    "{\"stringData\":{\"oidc-issuer-url\":\"$ISSUER_URL\",\"oidc-client-id\":\"scanning-console\",\"oidc-client-secret\":\"$SECRET_SCANNING\"}}" 2>/dev/null
log_info "Scanning Console OIDC configured"

# ArgoCD
kubectl -n argocd patch secret argocd-secret --type merge -p \
    "{\"stringData\":{\"oidc.keycloak.clientSecret\":\"$SECRET_ARGOCD\"}}" 2>/dev/null
log_info "ArgoCD OIDC configured"

# OAuth2-Proxy
kubectl -n oauth2-proxy patch secret oauth2-proxy-credentials --type merge -p \
    "{\"stringData\":{\"client-secret\":\"$SECRET_FORWARD_AUTH\"}}" 2>/dev/null
log_info "OAuth2-Proxy credentials configured"

# =============================================================================
# Step 8: Restart apps to pick up OIDC config
# =============================================================================
print_step "8" "Restarting applications to enable OIDC"

for ns_deploy in "portal/portal" "scanning-console/scanning-console" "oauth2-proxy/oauth2-proxy"; do
    ns="${ns_deploy%%/*}"
    deploy="${ns_deploy##*/}"
    kubectl -n "$ns" rollout restart "deployment/$deploy" 2>/dev/null || true
    log_info "Restarted $deploy in $ns"
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
echo "Realm admin user: admin (temporary password — will be prompted to change)"
echo ""
echo "Verify: Open https://cleanroom.knowledgeondemand.net/login"
echo "        You should see 'Sign in with Keycloak SSO' button"
echo ""
