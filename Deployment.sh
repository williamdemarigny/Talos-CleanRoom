#!/bin/bash

set -eo pipefail  # Exit immediately if any command exits with a non-zero status

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to perform cleanup on exit
cleanup() {
    echo "Performing cleanup..."
    cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/terraform/talos-cluster-create" 2>/dev/null || true
    terraform destroy -auto-approve 2>/dev/null || echo "Warning: Failed to perform terraform destroy during cleanup."
}

# Trap exit signals for cleanup
trap cleanup EXIT

# Step 0: Dependency Validation
dependencies=("terraform" "talhelper" "talosctl" "sops" "jq" "curl")

echo "Checking dependencies..."
for cmd in "${dependencies[@]}"; do
    if ! command_exists "$cmd"; then
        echo "Error: '$cmd' is not installed. Please install it before proceeding."
        exit 1
    fi
done

echo "All dependencies are present. Proceeding with deployment..."

# Step 0.5: Environment Variable Validation
required_env_vars=("SOPS_AGE_KEY_FILE")

echo "Validating environment variables..."
for env_var in "${required_env_vars[@]}"; do
    if [[ -z "${!env_var}" ]]; then
        echo "Error: Required environment variable '$env_var' is not set."
        exit 1
    fi
done

echo "Required environment variables are set. Proceeding with deployment..."

# Step 1: Environment Setup
echo "Installing required tools..."
sudo apt-get update && sudo apt-get install -y curl jq || { echo "Error: Failed to install required tools."; cleanup; exit 1; }

# Step 2: Configuration Management
echo "Copying configuration files..."
cp "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/talos/cluster.auto.tfvars" "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/terraform/talos-cluster-create/" || { echo "Error: Failed to copy configuration files."; cleanup; exit 1; }

# Step 3: Terraform Deployment
echo "Deploying infrastructure with Terraform..."
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/terraform/talos-cluster-create" || { echo "Error: Could not change directory to Terraform directory."; cleanup; exit 1; }
terraform init || { echo "Error: Terraform initialization failed."; cleanup; exit 1; }
terraform plan -out=".tfplan" || { echo "Error: Terraform planning failed."; cleanup; exit 1; }
terraform apply ".tfplan" || { echo "Error: Terraform apply failed."; cleanup; exit 1; }

# Step 4: Talos Configuration Generation
echo "Generating Talos configuration..."
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS" || { echo "Error: Could not change directory to Talos configuration directory."; cleanup; exit 1; }
./tfvars-to-talos-env.sh || { echo "Error: Failed to run tfvars-to-talos-env.sh."; cleanup; exit 1; }

cd talos || { echo "Error: Could not change directory to Talos config directory."; cleanup; exit 1; }
export SOPS_AGE_KEY_FILE="$SOPS_AGE_KEY_FILE"
talhelper gensecret > talsecret.sops.yaml || { echo "Error: Failed to generate Talos secret."; cleanup; exit 1; }
sops -e -i talsecret.sops.yaml || { echo "Error: Failed to encrypt Talos secret."; cleanup; exit 1; }
talhelper genconfig --env-file talenv.yaml || { echo "Error: Failed to generate Talos config."; cleanup; exit 1; }

# Step 5: Apply Talos Configurations
echo "Applying Talos configurations..."
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/talos" || { echo "Error: Could not change directory to Talos apply directory."; cleanup; exit 1; }
export TALOSCONFIG="$(pwd)/clusterconfig/talosconfig"
./apply-configs.sh --bootstrap || { echo "Error: Failed to apply Talos configurations."; cleanup; exit 1; }

# Step 6: Verify Cluster Health
echo "Waiting for cluster health..."
timeout=300  # 5 minutes max wait
start_time=$(date +%s)
while true; do
    if talosctl health --nodes=talos-CleanRoom-master-01.knowledgeondemand.net &>/dev/null; then
        echo "Cluster is healthy."
        break
    fi
    
    current_time=$(date +%s)
    if (( current_time - start_time > timeout )); then
        echo "Timeout waiting for cluster health (exceeded $timeout seconds)"
        cleanup
        exit 1
    fi
    
    sleep 10
done

# Step 7: Get kubeconfig
echo "Getting kubeconfig..."
talosctl kubeconfig --nodes=talos-CleanRoom-master-01.knowledgeondemand.net ~/.kube/config || { echo "Error: Failed to retrieve kubeconfig."; cleanup; exit 1; }

# Step 8: Install ArgoCD
echo "Installing ArgoCD..."
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/infrastructure/argocd" || { echo "Error: Could not change directory to ArgoCD installation directory."; cleanup; exit 1; }
chmod +x install.sh && ./install.sh || { echo "Error: Failed to install ArgoCD."; cleanup; exit 1; }

export ARGO_PASSWORD=$(kubectl -n argocd get secret argocd-initial-password -o jsonpath='{.data.password}' | base64 --decode)
echo "ArgoCD admin password: $ARGO_PASSWORD"

# Step 9: Deploy Infrastructure Stack
echo "Deploying infrastructure stack..."
cd "$(git rev-parse --show-toplevel)/Resources/IAC-DNS/infrastructure/projects" || { echo "Error: Could not change directory to infrastructure projects directory."; cleanup; exit 1; }
chmod +x deploy-infra.sh && ./deploy-infra.sh || { echo "Error: Failed to deploy infrastructure stack."; cleanup; exit 1; }

echo "Deployment complete!"
