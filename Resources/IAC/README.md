# Talos Kubernetes Cluster on Proxmox - Infrastructure as Code

This repository contains Infrastructure as Code (IaC) for deploying a Talos Linux Kubernetes cluster on Proxmox, with OPNsense firewall VMs.

## Architecture Overview

### Network Configuration
- **Network**: 10.83.3.0/24
- **Gateway**: 10.83.3.1
- **VLAN**: 3

### Virtual Machines

#### OPNsense Firewall VMs
| Name | VMID | IP | MAC | Cores | Memory | Disk |
|------|------|-----|-----|-------|--------|------|
| opnsense-fw-01 | 1010 | 10.83.3.5 | BC:24:21:F1:00:01 | 2 | 8GB | 30G |
| opnsense-fw-02 | 1011 | 10.83.3.6 | BC:24:21:F1:00:02 | 2 | 8GB | 30G |

#### Talos Kubernetes Cluster
| Name | VMID | Role | IP | MAC | Cores | Memory | Primary Disk | Additional Disk |
|------|------|------|-----|-----|-------|--------|--------------|-----------------|
| talos-CleanRoom-master-01 | 2000 | Control Plane | 10.83.3.10 | BC:24:21:A4:B2:97 | 2 | 8GB | 30G | - |
| talos-CleanRoom-worker-01 | 3001 | Worker | 10.83.3.15 | BC:24:21:4C:99:A1 | 2 | 8GB | 30G | 30G |
| talos-CleanRoom-worker-02 | 3002 | Worker | 10.83.3.16 | BC:24:21:4C:99:A3 | 2 | 8GB | 30G | 30G |
| talos-CleanRoom-worker-03 | 3003 | Worker | 10.83.3.17 | BC:24:21:4C:99:A4 | 2 | 8GB | 30G | 30G |

### VM Distribution Across Proxmox Nodes
- **pve01**: talos-CleanRoom-master-01
- **pve02**: talos-CleanRoom-worker-01
- **pve03**: talos-CleanRoom-worker-02
- **pve04**: talos-CleanRoom-worker-03

## Directory Structure

```
Resources/IAC/
├── terraform/
│   └── talos-cluster-create/
│       ├── main.tf                      # Main Terraform configuration
│       ├── variables.tf                 # Variable definitions
│       ├── locals.tf                    # Local values and computations
│       ├── cluster.auto.tfvars          # Cluster configuration (non-secret)
│       └── credentials.auto.tfvars      # Proxmox credentials (secret, gitignored)
├── talos/
│   ├── talconfig.yaml                   # Talos cluster configuration
│   ├── talsecret.sops.yaml             # SOPS-encrypted secrets
│   ├── talenv.yaml                      # Generated environment variables
│   ├── apply-configs.sh                 # Automation script for applying configs
│   └── clusterconfig/                   # Generated Talos machine configs
├── tfvars-to-talos-env.sh              # Extract Terraform vars for Talos
└── README.md                            # This file
```

## Prerequisites

### Required Tools
All tools are installed and configured in your Git Bash environment:

- **Terraform** (v1.x+) - Infrastructure provisioning
- **talhelper** (v3.0.45) - Talos configuration generator
- **talosctl** (v1.11.6) - Talos Linux CLI
- **sops** (v3.11.0) - Secrets encryption
- **jq** (v1.8.1) - JSON processing
- **curl** - API requests

### Environment Setup
Your `~/.bashrc` is configured with:
```bash
# Tool paths
export PATH="$PATH:/c/Users/willi/AppData/Local/Microsoft/WinGet/Packages/talhelper.talhelper_Microsoft.Winget.Source_8wekyb3d8bbwe"
export PATH="$PATH:/c/Program Files (x86)/Sops"
export PATH="$PATH:/c/Users/willi/AppData/Local/Microsoft/WinGet/Packages/jqlang.jq_Microsoft.Winget.Source_8wekyb3d8bbwe"
export PATH="$PATH:/c/Users/willi/AppData/Local/Microsoft/WinGet/Packages/Sidero.talosctl_Microsoft.Winget.Source_8wekyb3d8bbwe"

# SOPS configuration
export EDITOR="code --wait"
export SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt
```

### SOPS Age Key
- Location: `~/.config/sops/age/keys.txt`
- Public key configured in `.sops.yaml`

## Deployment Workflow

### 1. Deploy Infrastructure with Terraform

```bash
cd Resources/IAC/terraform/talos-cluster-create

# Review planned changes
terraform plan

# Deploy OPNsense firewalls and Talos VMs
terraform apply
```

**What happens:**
- OPNsense VMs are cloned from template VMID 1000
- Talos VMs are created with nocloud ISO
- VMs boot with DHCP initially (will be converted to static IPs)

### 2. Generate Talos Configuration

```bash
cd Resources/IAC

# Extract Terraform variables for Talos
./tfvars-to-talos-env.sh

cd talos

# Generate Talos machine configs
talhelper genconfig --env-file talenv.yaml
```

**What happens:**
- `talenv.yaml` is created with network settings from Terraform
- Machine-specific YAML configs are generated in `clusterconfig/`
- Configs include static IP assignments matching `talconfig.yaml`
- SOPS-encrypted secrets are decrypted and embedded

### 3. Apply Talos Configs (Automated)

```bash
cd Resources/IAC/talos

# Dry run to preview
./apply-configs.sh --dry-run

# Apply configurations
./apply-configs.sh

# Apply configs and bootstrap cluster
./apply-configs.sh --bootstrap
```

**What the script does:**
1. Queries Terraform state to find VM locations
2. Queries Proxmox guest agent for DHCP IPs
3. Applies machine configs to VMs via their DHCP IPs
4. VMs reboot and come up with static IPs
5. (Optional) Bootstraps the Kubernetes cluster

### 4. Bootstrap Cluster (Manual)

If not using `--bootstrap` flag:

```bash
# Wait for VMs to reboot (~2 minutes)
sleep 120

# Bootstrap the control plane
talosctl bootstrap --nodes 10.83.3.10 --endpoints 10.83.3.10

# Configure talosctl context
talosctl config endpoint 10.83.3.10
talosctl config node 10.83.3.10

# Get kubeconfig
talosctl kubeconfig .
```

### 5. Verify Deployment

```bash
# Check Talos cluster health
talosctl health

# Check Kubernetes nodes
kubectl get nodes

# Check all pods
kubectl get pods -A
```

## Key Features

### Terraform Configuration

**VM Creation:**
- Automated VM distribution across Proxmox cluster nodes (round-robin)
- Unique MAC addresses for each VM to prevent DHCP conflicts
- Support for additional storage disks on worker nodes
- VLAN tagging (VLAN 3)

**OPNsense Integration:**
- Clone from existing template VM
- Automated deployment before Talos cluster
- Load balancing across multiple Proxmox nodes

**Outputs:**
- VM details (IP, MAC, role)
- VM distribution across nodes
- OPNsense API endpoints

### Talos Configuration

**Network Settings:**
- Static IP configuration (no Cloud-Init needed)
- Custom DNS servers (1.1.1.1, 1.0.0.1)
- Custom NTP server (time.cloudflare.com)

**Security:**
- SOPS-encrypted secrets using Age encryption
- Unique machine tokens per node

**Storage:**
- Longhorn storage support on worker nodes
- Additional raw disks mounted at `/var/mnt/longhorn_sdb`

**System Tuning:**
- Hugepages configured (1024 pages)
- BPF JIT hardening enabled
- Custom kernel modules (nvme_tcp, vfio_pci, uio_pci_generic)

### Automation Scripts

**tfvars-to-talos-env.sh:**
- Extracts VM configuration from Terraform tfvars
- Generates `talenv.yaml` for talhelper
- Supports both YAML and shell export formats

**apply-configs.sh:**
- Discovers DHCP IPs from Proxmox API
- Applies Talos configs to VMs automatically
- Supports dry-run mode
- Optional cluster bootstrap
- Continues processing all VMs even if some fail

## Networking Considerations

### Initial Boot (DHCP)
- VMs boot with nocloud ISO
- QEMU guest agent provides DHCP IP to Proxmox
- Each VM gets unique DHCP IP due to unique MAC addresses

### Static IP Assignment
- Talos machine configs contain static network configuration
- Applied via `talosctl apply-config --insecure`
- VMs reboot and come up with static IPs
- MAC address matching ensures correct interface selection

### Important Note
**Talos does not support Cloud-Init for network configuration.** The nocloud ISO is used for initial boot only. Static IPs are configured through Talos machine configuration, not Cloud-Init.

## Troubleshooting

### VMs not getting unique IPs
**Problem:** Multiple VMs have the same MAC address
**Solution:** Ensure each VM has a unique MAC address in `cluster.auto.tfvars`

### apply-configs.sh can't find VMs
**Problem:** Proxmox API not responding or VMs not started
**Solution:**
- Check VMs are running in Proxmox UI
- Verify credentials in `credentials.auto.tfvars`
- Check Terraform state: `terraform output vm_distribution`

### SOPS decryption failed
**Problem:** `talhelper` can't decrypt secrets
**Solution:**
- Verify `SOPS_AGE_KEY_FILE` is set: `echo $SOPS_AGE_KEY_FILE`
- Check age key exists: `ls -la ~/.config/sops/age/keys.txt`
- Reload bashrc: `source ~/.bashrc`

### Guest agent not responding
**Problem:** Can't get DHCP IP from VM
**Solution:**
- Wait for VM to fully boot (~1-2 minutes)
- Check guest agent is running (should be automatic with nocloud ISO)
- Verify VM has network connectivity

### Talos configs not applying
**Problem:** `talosctl apply-config` fails
**Solution:**
- Verify VM is reachable: `ping <DHCP-IP>`
- Check correct config file is being used
- Try manual apply: `talosctl apply-config --insecure --nodes <IP> --file <config.yaml>`

## Security Notes

### Secrets Management
- Proxmox API credentials stored in `credentials.auto.tfvars` (gitignored)
- Talos secrets encrypted with SOPS using Age encryption
- Age private key stored locally at `~/.config/sops/age/keys.txt`
- Public key configured in `.sops.yaml`

### Network Security
- VMs isolated on VLAN 3
- OPNsense firewalls provide perimeter security
- Talos uses machine tokens for node authentication

## Next Steps

1. **DHCP Configuration:** Configure external firewall to provide DHCP for the 10.83.3.0/24 network
2. **OPNsense Configuration:** Configure OPNsense firewalls for cluster access
3. **CNI Installation:** Install Cilium CNI after cluster bootstrap
4. **Storage Configuration:** Configure Longhorn for persistent storage
5. **Application Deployment:** Deploy workloads to the cluster

## References

- [Talos Linux Documentation](https://www.talos.dev/)
- [Proxmox Terraform Provider](https://registry.terraform.io/providers/bpg/proxmox/latest/docs)
- [talhelper Documentation](https://github.com/budimanjojo/talhelper)
- [SOPS Documentation](https://github.com/getsops/sops)

## Support

For issues or questions:
1. Check the Troubleshooting section above
2. Review Talos/Terraform logs
3. Consult the official documentation links
