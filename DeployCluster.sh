#!/bin/bash

set -eo pipefail  # Exit immediately if any command exits with a non-zero status and handle errors in pipes.

# Configuration variables
MASTER_NODE="talos-CleanRoom-master-01.knowledgeondemand.net"
HEALTH_CHECK_RETRIES=30
HEALTH_CHECK_INTERVAL=10

# Function to perform cleanup on failure (defined early so it's available for all error handlers)
cleanup() {
    echo "Performing cleanup..."
    local repo_root
    repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || true
    if [[ -n "$repo_root" ]]; then
        cd "$repo_root/Resources/IAC-DNS/terraform/talos-cluster-create" 2>/dev/null || echo "Warning: Could not change directory to Terraform directory for cleanup."
        terraform destroy -auto-approve || echo "Warning: Failed to perform terraform destroy during cleanup."
    else
        echo "Warning: Could not determine repository root for cleanup."
    fi
}

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Step 0: Validate git repository
if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
    echo "Error: This script must be run from within the git repository."
    exit 1
fi

# Step 0.1: Dependency Validation
dependencies=("terraform" "talhelper" "talosctl" "sops" "jq" "curl" "kubectl" "helm")

for cmd in "${dependencies[@]}"; do
    if ! command_exists "$cmd"; then
        echo "Error: '$cmd' is not installed. Please install it before proceeding."
        exit 1
    fi
done

echo "All dependencies are present. Proceeding with deployment..."

# Step 1: Terraform Deployment
echo "Deploying infrastructure with Terraform..."
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/terraform/talos-cluster-create" || { echo "Error: Could not change directory to Terraform directory."; cleanup; exit 1; }
terraform init || { echo "Error: Terraform initialization failed."; cleanup; exit 1; }
terraform plan -out=".tfplan" || { echo "Error: Terraform planning failed."; cleanup; exit 1; }
terraform apply ".tfplan" || { echo "Error: Terraform apply failed."; cleanup; exit 1; }

# Step 2: Talos Configuration Generation
echo "Generating Talos configuration..."
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS" || { echo "Error: Could not change directory to Talos configuration directory."; cleanup; exit 1; }
./tfvars-to-talos-env.sh || { echo "Error: Failed to run tfvars-to-talos-env.sh."; cleanup; exit 1; }

cd talos || { echo "Error: Could not change directory to Talos config directory."; cleanup; exit 1; }
export SOPS_AGE_KEY_FILE="${SOPS_AGE_KEY_FILE:-$HOME/.config/sops/age/keys.txt}"
talhelper gensecret > talsecret.sops.yaml || { echo "Error: Failed to generate Talos secret."; cleanup; exit 1; }
sops -e -i talsecret.sops.yaml || { echo "Error: Failed to encrypt Talos secret."; cleanup; exit 1; }
talhelper genconfig --env-file talenv.yaml || { echo "Error: Failed to generate Talos config."; cleanup; exit 1; }

# Step 3: Apply Talos Configurations
echo "Applying Talos configurations..."
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/talos" || { echo "Error: Could not change directory to Talos apply directory."; cleanup; exit 1; }
export TALOSCONFIG=$(pwd)/clusterconfig/talosconfig

./apply-configs.sh --bootstrap || { echo "Error: Failed to apply Talos configurations."; cleanup; exit 1; }

# Step 4: Verify Cluster Health
echo "Waiting for cluster health (max wait: $((HEALTH_CHECK_RETRIES * HEALTH_CHECK_INTERVAL)) seconds)..."
for ((i=1; i<=HEALTH_CHECK_RETRIES; i++)); do
    if talosctl health --nodes="$MASTER_NODE" &>/dev/null; then
        echo "Cluster is healthy."
        break
    else
        echo "Cluster not yet healthy. Retrying ($i/$HEALTH_CHECK_RETRIES)..."
        sleep "$HEALTH_CHECK_INTERVAL"
    fi
done

if ! talosctl health --nodes="$MASTER_NODE" &>/dev/null; then
    echo "Error: Cluster failed to become healthy within the allowed time."
    cleanup
    exit 1
fi

# Step 5: Get kubeconfig
echo "Getting kubeconfig..."
talosctl kubeconfig --nodes="$MASTER_NODE" ~/.kube/config || { echo "Error: Failed to retrieve kubeconfig."; cleanup; exit 1; }

# Step 6: Install ArgoCD
echo "Installing ArgoCD..."
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/infrastructure/argocd" || { echo "Error: Could not change directory to ArgoCD installation directory."; cleanup; exit 1; }
chmod +x install.sh && ./install.sh || { echo "Error: Failed to install ArgoCD."; cleanup; exit 1; }

# ArgoCD password is preconfigured in values.yaml (admin/admin)
echo "ArgoCD installed with default credentials: admin / admin"

# Step 7: Deploy Infrastructure Stack
echo "Deploying infrastructure stack..."
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/infrastructure/projects" || { echo "Error: Could not change directory to infrastructure projects directory."; cleanup; exit 1; }
chmod +x deploy-ingress-stack.sh && ./deploy-ingress-stack.sh || { echo "Error: Failed to deploy infrastructure stack."; cleanup; exit 1; }

# Step 8: Enable ArgoCD Self-Management
echo "Enabling ArgoCD self-management..."
cd "$(git rev-parse --show-toplevel)" || { echo "Error: Could not change directory to repository root."; cleanup; exit 1; }
kubectl apply -f Resources/IAC-DNS/infrastructure/projects/argocd/application.yaml || { echo "Error: Failed to enable ArgoCD self-management."; cleanup; exit 1; }

# Verify ArgoCD self-management
echo "Verifying ArgoCD self-management..."
sleep 10
if kubectl get applications -n argocd argocd &>/dev/null; then
    echo "ArgoCD is now self-managing."
else
    echo "Warning: ArgoCD self-management application not found. You may need to apply it manually."
fi

# Step 9: Deploy OpenVAS (vulnerability scanner)
echo "Deploying OpenVAS..."
cd "$(git rev-parse --show-toplevel)" || { echo "Error: Could not change directory to repository root."; exit 1; }
kubectl apply -f Resources/IAC-DNS/infrastructure/projects/openvas/application.yaml || echo "Warning: Failed to deploy OpenVAS application. You may need to apply it manually."

# Step 10: Deploy Faraday (security platform with web UI)
echo "Deploying Faraday..."
kubectl apply -f Resources/IAC-DNS/infrastructure/projects/faraday/application.yaml || echo "Warning: Failed to deploy Faraday application. You may need to apply it manually."

# Step 11: Deploy Metasploit Framework (penetration testing)
echo "Deploying Metasploit Framework..."
kubectl apply -f Resources/IAC-DNS/infrastructure/projects/metasploit/application.yaml || echo "Warning: Failed to deploy Metasploit application. You may need to apply it manually."

# Step 12: Deploy Threat Dragon (threat modeling)
echo "Deploying Threat Dragon..."
kubectl apply -f Resources/IAC-DNS/infrastructure/projects/threat-dragon/application.yaml || echo "Warning: Failed to deploy Threat Dragon application. You may need to apply it manually."

# Wait for applications to sync
echo "Waiting for applications to sync..."
sleep 30

# Final status check
echo ""
echo "Checking deployment status..."
kubectl get applications -n argocd

echo ""
echo "=========================================="
echo "Deployment complete!"
echo "=========================================="
echo ""
echo "Default Credentials (CHANGE IN PRODUCTION!):"
echo "  - ArgoCD:     admin / admin"
echo "  - OpenVAS:    admin / admin"
echo "  - Faraday:    faraday / admin"
echo "  - Traefik/Longhorn: Uses basic-auth-secret (create with htpasswd)"
echo ""
echo "Access services at:"
echo "  - ArgoCD:        https://argocd.knowledgeondemand.net"
echo "  - Traefik:       https://traefik.knowledgeondemand.net"
echo "  - Longhorn:      https://longhorn.knowledgeondemand.net"
echo "  - OpenVAS:       https://openvas.knowledgeondemand.net"
echo "  - Faraday:       https://faraday.knowledgeondemand.net"
echo "  - Threat Dragon: https://threatdragon.knowledgeondemand.net"
echo ""
echo "Metasploit access (CLI only - no web UI):"
echo "  kubectl exec -it -n metasploit deployment/metasploit -c metasploit -- ./msfconsole"
echo ""
echo "ArgoCD is now self-managing. Push changes to git and they will auto-sync."
echo ""
echo "Note: OpenVAS feed synchronization takes 30-60 minutes on first deployment."
echo "=========================================="
