#!/bin/bash
#######################################
# DeployCluster.sh - Talos CleanRoom Cluster Deployment Orchestrator
#######################################
# Orchestrates the complete deployment of a Talos Kubernetes cluster
# including infrastructure, security tools, and the 3-app platform.
#
# Prerequisites:
#   - terraform, talhelper, talosctl, sops, jq, curl, kubectl, helm
#   - Proxmox credentials in credentials.auto.tfvars
#   - SOPS age keys configured (~/.config/sops/age/keys.txt)
#   - Network connectivity to Proxmox and target VLAN
#   - generate-secrets.sh already run (encrypted secrets in apps/)
#
# Usage:
#   ./DeployCluster.sh [--skip-terraform] [--skip-talos] [--from-step N]
#
# Options:
#   --skip-terraform   Skip Terraform provisioning (VMs already exist)
#   --skip-talos       Skip Talos config + bootstrap (cluster already running)
#   --from-step N      Resume from step N (1-12)
#
# Steps:
#   1.  Terraform VMs on Proxmox
#   2.  Talos config generation + encryption
#   3.  Apply configs + bootstrap cluster
#   4.  Cluster health verification
#   5.  kubeconfig retrieval
#   6.  ArgoCD installation
#   7.  Infrastructure stack (MetalLB, cert-manager, Traefik, Ceph CSI)
#   8.  ArgoCD self-management
#   9.  Apply application secrets
#   10. Security tools (Harbor, OpenVAS, Faraday, Metasploit, Threat Dragon)
#   11. Network policies
#   12. CleanRoom DB + Scanning Console + Portal
#
# Manual steps after this script:
#   - Configure DNS (*.knowledgeondemand.net -> Traefik LB IP)
#   - Deploy Build VM (build-vm/deploy-lxc.sh)
#   - Build and push images (LOKI-RS, scanning-console, portal)
#   - Deploy Deployment Console (webui/deploy-lxc.sh)
#
# Exit Codes:
#   0 - Success
#   1 - Prerequisites check or general error
#
# Cleanup:
#   On failure during Terraform/Talos steps, the script offers to run
#   terraform destroy to clean up partial infrastructure.
#######################################

set -euo pipefail

#######################################
# Configuration
#######################################
readonly MASTER_NODE="talos-CleanRoom-master-01.knowledgeondemand.net"
readonly MASTER_NODE_IP="10.83.3.10"

readonly HEALTH_CHECK_RETRIES=45
readonly HEALTH_CHECK_INTERVAL=10
readonly VM_BOOT_WAIT=60
readonly TALOS_API_TIMEOUT=15

# Colors
readonly GREEN='\033[0;32m'
readonly BLUE='\033[0;34m'
readonly YELLOW='\033[1;33m'
readonly RED='\033[0;31m'
readonly NC='\033[0m'
readonly BOLD='\033[1m'

#######################################
# Logging
#######################################
print_step()    { echo -e "\n${BOLD}${BLUE}[Step $1/$TOTAL_STEPS]${NC} ${BOLD}$2${NC}"; }
print_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[OK]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error()   { echo -e "${RED}[ERROR]${NC} $1" >&2; }

TOTAL_STEPS=12
SKIP_TERRAFORM=false
SKIP_TALOS=false
FROM_STEP=0

#######################################
# Parse arguments
#######################################
while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-terraform) SKIP_TERRAFORM=true; shift ;;
        --skip-talos)     SKIP_TALOS=true; shift ;;
        --from-step)      FROM_STEP="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 [--skip-terraform] [--skip-talos] [--from-step N]"
            exit 0
            ;;
        *) print_error "Unknown option: $1"; exit 1 ;;
    esac
done

should_run_step() {
    [[ "$1" -ge "$FROM_STEP" ]]
}

#######################################
# Cleanup on failure
#######################################
cleanup() {
    echo ""
    print_warning "Deployment failed. Performing cleanup..."
    local repo_root
    repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || true
    if [[ -n "$repo_root" && -d "$repo_root/terraform/cluster-create" ]]; then
        print_warning "Running terraform destroy..."
        cd "$repo_root/terraform/cluster-create"
        terraform destroy -auto-approve || print_error "terraform destroy failed"
    fi
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

#######################################
# Step 0: Validate git repository and prerequisites
#######################################
echo ""
echo "=============================================="
echo "  Talos CleanRoom - Cluster Deployment"
echo "=============================================="
echo ""

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
    print_error "This script must be run from within the git repository."
    exit 1
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"

# Check dependencies
dependencies=("terraform" "talhelper" "talosctl" "sops" "jq" "curl" "kubectl" "helm")
missing=()
for cmd in "${dependencies[@]}"; do
    if ! command_exists "$cmd"; then
        missing+=("$cmd")
    fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
    print_error "Missing required tools: ${missing[*]}"
    exit 1
fi
print_success "All dependencies present"

# Check for SOPS age key
if [[ ! -f "${SOPS_AGE_KEY_FILE:-$HOME/.config/sops/age/keys.txt}" ]]; then
    print_error "SOPS age key not found. Run: age-keygen -o ~/.config/sops/age/keys.txt"
    exit 1
fi
export SOPS_AGE_KEY_FILE="${SOPS_AGE_KEY_FILE:-$HOME/.config/sops/age/keys.txt}"

#######################################
# Step 1: Terraform Deployment
#######################################
if should_run_step 1 && [[ "$SKIP_TERRAFORM" != "true" ]]; then
    print_step 1 "Terraform Deployment"

    cd "$REPO_ROOT/terraform/cluster-create"
    terraform init || { print_error "Terraform init failed"; cleanup; exit 1; }
    terraform plan -out=".tfplan" || { print_error "Terraform plan failed"; cleanup; exit 1; }
    terraform apply ".tfplan" || { print_error "Terraform apply failed"; cleanup; exit 1; }
    print_success "VMs created on Proxmox"
else
    print_info "Skipping Step 1: Terraform"
fi

#######################################
# Step 2: Talos Configuration Generation
#######################################
if should_run_step 2 && [[ "$SKIP_TALOS" != "true" ]]; then
    print_step 2 "Talos Configuration Generation"

    cd "$REPO_ROOT"
    ./scripts/tfvars-to-talos-env.sh --force || { print_error "tfvars-to-talos-env.sh failed"; cleanup; exit 1; }

    cd "$REPO_ROOT/cluster"
    talhelper gensecret > talsecret.sops.yaml || { print_error "talhelper gensecret failed"; cleanup; exit 1; }
    sops -e -i talsecret.sops.yaml || { print_error "SOPS encryption failed"; cleanup; exit 1; }
    talhelper genconfig --env-file talenv.yaml || { print_error "talhelper genconfig failed"; cleanup; exit 1; }
    print_success "Talos configs generated and encrypted"
else
    print_info "Skipping Step 2: Talos config generation"
fi

#######################################
# Step 3: Apply Talos Configurations + Bootstrap
#######################################
if should_run_step 3 && [[ "$SKIP_TALOS" != "true" ]]; then
    print_step 3 "Apply Talos Configurations + Bootstrap"

    cd "$REPO_ROOT/cluster"
    export TALOSCONFIG=$(pwd)/clusterconfig/talosconfig

    ./apply-configs.sh --bootstrap || { print_error "apply-configs.sh failed"; cleanup; exit 1; }
    print_success "Talos configs applied and cluster bootstrapped"
else
    print_info "Skipping Step 3: Talos config application"
fi

#######################################
# Step 4: Verify Cluster Health
#######################################
if should_run_step 4; then
    print_step 4 "Verify Cluster Health"

    export TALOSCONFIG="${TALOSCONFIG:-$REPO_ROOT/cluster/clusterconfig/talosconfig}"

    # Wait for Talos API
    print_info "Waiting for Talos API on control plane..."
    API_READY=false
    for ((i=1; i<=60; i++)); do
        if timeout 5 bash -c "echo > /dev/tcp/$MASTER_NODE_IP/50000" 2>/dev/null; then
            API_READY=true
            break
        fi
        echo -ne "\r  Attempt $i/60..."
        sleep 5
    done
    echo ""

    if [[ "$API_READY" != "true" ]]; then
        print_error "Talos API not reachable after 5 minutes"
        cleanup
        exit 1
    fi

    # Post-bootstrap stabilization
    print_info "Waiting 30s for post-bootstrap stabilization..."
    sleep 30

    # Health check loop
    print_info "Checking cluster health (max wait: $((HEALTH_CHECK_RETRIES * HEALTH_CHECK_INTERVAL))s)..."
    HEALTHY=false
    for ((i=1; i<=HEALTH_CHECK_RETRIES; i++)); do
        if talosctl health --nodes="$MASTER_NODE" 2>&1; then
            HEALTHY=true
            break
        fi
        echo -ne "\r  Health check $i/$HEALTH_CHECK_RETRIES..."
        sleep "$HEALTH_CHECK_INTERVAL"
    done
    echo ""

    if [[ "$HEALTHY" != "true" ]]; then
        print_error "Cluster failed to become healthy"
        cleanup
        exit 1
    fi
    print_success "Cluster is healthy"
fi

#######################################
# Step 5: Get kubeconfig
#######################################
if should_run_step 5; then
    print_step 5 "Get kubeconfig"

    export TALOSCONFIG="${TALOSCONFIG:-$REPO_ROOT/cluster/clusterconfig/talosconfig}"
    mkdir -p ~/.kube
    talosctl kubeconfig --nodes="$MASTER_NODE" ~/.kube/config || { print_error "Failed to get kubeconfig"; exit 1; }

    # Verify kubectl works
    kubectl get nodes || { print_error "kubectl cannot connect to cluster"; exit 1; }
    print_success "kubeconfig retrieved"
fi

#######################################
# Step 6: Install ArgoCD
#######################################
if should_run_step 6; then
    print_step 6 "Install ArgoCD"

    cd "$REPO_ROOT/apps/argocd"
    chmod +x install.sh
    ./install.sh || { print_error "ArgoCD installation failed"; exit 1; }
    print_success "ArgoCD installed (default: admin / admin)"
fi

#######################################
# Step 7: Deploy Infrastructure Stack
#######################################
if should_run_step 7; then
    print_step 7 "Deploy Infrastructure Stack"

    cd "$REPO_ROOT/apps"
    chmod +x deploy-ingress-stack.sh
    ./deploy-ingress-stack.sh || { print_error "Infrastructure stack deployment failed"; exit 1; }
    print_success "Infrastructure stack deployed (MetalLB, cert-manager, Traefik, Ceph CSI)"
fi

#######################################
# Step 8: Enable ArgoCD Self-Management
#######################################
if should_run_step 8; then
    print_step 8 "Enable ArgoCD Self-Management"

    cd "$REPO_ROOT"
    kubectl apply -f apps/argocd/application.yaml || { print_error "ArgoCD self-management failed"; exit 1; }

    sleep 10
    if kubectl get applications -n argocd argocd &>/dev/null; then
        print_success "ArgoCD is now self-managing"
    else
        print_warning "ArgoCD self-management app not yet visible (may need a few more seconds)"
    fi
fi

#######################################
# Step 9: Apply Application Secrets
#######################################
if should_run_step 9; then
    print_step 9 "Apply Application Secrets"

    cd "$REPO_ROOT"

    if [[ -x scripts/apply-secrets.sh ]]; then
        ./scripts/apply-secrets.sh || { print_error "Failed to apply secrets"; exit 1; }
    else
        # Fallback: apply individually
        print_info "apply-secrets.sh not found, applying secrets individually..."
        for sops_file in apps/*/secrets.sops.yaml apps/traefik/basic-auth-secret.sops.yaml; do
            if [[ -f "$sops_file" ]]; then
                print_info "  Applying $sops_file..."
                sops -d "$sops_file" | kubectl apply -f - || print_warning "Failed to apply $sops_file"
            fi
        done
    fi
    print_success "Application secrets applied"
fi

#######################################
# Step 10: Deploy Security Tools
#######################################
if should_run_step 10; then
    print_step 10 "Deploy Security Tools"

    cd "$REPO_ROOT"

    # Harbor first (creates PVCs, takes longest)
    print_info "Deploying Harbor..."
    kubectl apply -f apps/harbor/application.yaml || print_warning "Failed to deploy Harbor"

    # Security tools
    for app in openvas faraday metasploit threat-dragon; do
        print_info "Deploying $app..."
        kubectl apply -f "apps/$app/application.yaml" || print_warning "Failed to deploy $app"
    done

    # Wait for apps to start syncing
    sleep 15
    print_success "Security tool ArgoCD applications created"
    print_info "Harbor and OpenVAS will take 15-30 minutes to fully initialize"
fi

#######################################
# Step 11: Apply Network Policies
#######################################
if should_run_step 11; then
    print_step 11 "Apply Network Policies"

    cd "$REPO_ROOT"
    kubectl apply -f apps/network-policies/ || print_warning "Some network policies failed to apply"
    print_success "Zero-trust network policies applied"
fi

#######################################
# Step 12: Deploy Platform Apps (DB + Scanning Console + Portal)
#######################################
if should_run_step 12; then
    print_step 12 "Deploy Platform Apps"

    cd "$REPO_ROOT"

    # CleanRoom DB first (Scanning Console depends on it)
    print_info "Deploying CleanRoom DB..."
    kubectl apply -f apps/cleanroom-db/application.yaml || { print_error "Failed to deploy CleanRoom DB"; exit 1; }

    # Wait for DB to be ready
    print_info "Waiting for PostgreSQL to be ready..."
    for ((i=1; i<=30; i++)); do
        if kubectl -n cleanroom-db exec statefulset/cleanroom-db -- pg_isready 2>/dev/null; then
            print_success "CleanRoom DB is ready"
            break
        fi
        echo -ne "\r  Waiting for DB ($i/30)..."
        sleep 10
    done
    echo ""

    # Create Harbor pull secrets for namespaces that pull from private registry
    print_info "Creating Harbor pull secrets..."
    for ns in scanning-console portal loki-scanner; do
        kubectl create secret docker-registry harbor-pull-secret \
            --namespace="$ns" \
            --docker-server=harbor.knowledgeondemand.net \
            --docker-username=admin \
            --docker-password=Harbor12345 \
            2>/dev/null || print_info "  harbor-pull-secret already exists in $ns"
    done

    # Scanning Console
    print_info "Deploying Scanning Console..."
    kubectl apply -f apps/scanning-console/application.yaml || print_warning "Failed to deploy Scanning Console"

    # Portal
    print_info "Deploying Portal..."
    kubectl apply -f apps/portal/application.yaml || print_warning "Failed to deploy Portal"

    # Deployment Console (ExternalName service → LXC, no pods)
    print_info "Deploying Deployment Console routing..."
    kubectl apply -f apps/deployment-console/application.yaml || print_warning "Failed to deploy Deployment Console"

    print_success "Platform apps deployed"
    print_warning "Scanning Console and Portal require images in Harbor to start."
    print_warning "See DEPLOYMENT.md steps 12-13 for Build VM and image builds."
fi

#######################################
# Deployment Summary
#######################################
echo ""
echo "=============================================="
echo "  Deployment Complete!"
echo "=============================================="
echo ""
echo "Automated steps complete. Remaining manual steps:"
echo ""
echo "  1. Configure DNS:"
echo "     Get Traefik LB IP: kubectl get svc traefik -n traefik"
echo "     Create wildcard: *.knowledgeondemand.net -> <LB IP>"
echo ""
echo "  2. Deploy Build VM (for image builds):"
echo "     cd build-vm && ./deploy-lxc.sh"
echo ""
echo "  3. Build and push images (SSH to Build VM):"
echo "     ssh deploy@10.83.3.191"
echo "     cd /opt/talos-cleanroom/apps/loki && ./build-and-push.sh"
echo "     cd /opt/talos-cleanroom/scanning-app && docker build/push"
echo "     cd /opt/talos-cleanroom/portal && docker build/push"
echo ""
echo "  4. Deploy Deployment Console:"
echo "     cd webui && ./deploy-lxc.sh"
echo ""
echo "Credentials:"
echo "  Portal:           https://cleanroom.knowledgeondemand.net (admin / admin)"
echo "  All service creds: https://cleanroom.knowledgeondemand.net/credentials"
echo "  CLI alternative:  sops -d apps/portal/credential-vault.sops.yaml"
echo ""
echo "Access services at:"
echo "  ArgoCD:           https://argocd.knowledgeondemand.net"
echo "  Traefik:          https://traefik.knowledgeondemand.net"
echo "  Harbor:           https://harbor.knowledgeondemand.net"
echo "  OpenVAS:          https://openvas.knowledgeondemand.net"
echo "  Faraday:          https://faraday.knowledgeondemand.net"
echo "  Threat Dragon:    https://threatdragon.knowledgeondemand.net"
echo "  Scanning Console: https://scan.knowledgeondemand.net"
echo "  Portal:           https://cleanroom.knowledgeondemand.net"
echo ""
echo "See DEPLOYMENT.md for the complete guide."
echo "=============================================="
