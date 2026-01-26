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
dependencies=("terraform" "talhelper" "talosctl" "sops" "jq" "curl" "kubectl")

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

export ARGO_PASSWORD=$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d)
echo "ArgoCD admin password: $ARGO_PASSWORD"

# Step 7: Deploy Infrastructure Stack
echo "Deploying infrastructure stack..."
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/infrastructure/projects" || { echo "Error: Could not change directory to infrastructure projects directory."; cleanup; exit 1; }
chmod +x deploy-ingress-stack.sh && ./deploy-ingress-stack.sh || { echo "Error: Failed to deploy infrastructure stack."; cleanup; exit 1; }

echo "Deployment complete!"
