# Deployment Steps

The deployment process runs 23 automated steps (numbered 0-22). Here is what each step does in plain language.

## Step-by-Step Guide

| Step | Name | What It Does |
|---|---|---|
| **0** | Validate Git Repository | Checks that the Git repository is properly configured and accessible |
| **1** | Check Dependencies | Verifies all required tools are installed (Terraform, kubectl, Helm, etc.) |
| **2** | Terraform Deploy | Creates the virtual machines on Proxmox (the server infrastructure) |
| **3** | Wait for VMs to Boot | Waits for all virtual machines to finish starting up (~3 minutes) |
| **4** | Generate Talos Config | Creates the configuration files for the Talos Linux operating system |
| **5** | Apply Talos Configurations | Pushes the Talos config to each virtual machine |
| **6** | Verify Cluster Health | Checks that the Kubernetes cluster is healthy and all nodes are ready |
| **7** | Get Kubeconfig | Downloads the cluster access credentials (kubeconfig file) |
| **8** | Install ArgoCD | Installs the GitOps deployment manager |
| **9** | Deploy Infrastructure Stack | Deploys core infrastructure: MetalLB (load balancer), cert-manager (TLS certificates), Traefik (web gateway), Ceph storage |
| **10** | Enable ArgoCD Self-Management | Configures ArgoCD to manage its own updates |
| **11** | Deploy OpenVAS | Installs the vulnerability scanner engine |
| **12** | Deploy Faraday | Installs the vulnerability management platform |
| **13** | Deploy Metasploit | Installs the penetration testing framework |
| **14** | Deploy Threat Dragon | Installs the threat modeling tool |
| **15** | Deploy Harbor Registry | Installs the container image registry |
| **16** | Configure Integrations | Sets up connections between the deployed tools |
| **17** | Generate & Apply Secrets | Creates passwords and encryption keys for all services |
| **18** | Commit & Push Secrets | Saves encrypted secrets to the Git repository |
| **19** | Deploy Build VM | Creates the container image build environment |
| **20** | Build & Push Container Images | Builds the Scanning Console, Portal, and other custom images |
| **21** | Deploy CleanRoom Applications | Deploys the Scanning Console and Portal to Kubernetes |
| **22** | Apply Network Policies | Applies zero-trust network security rules between all services |

## Which Steps Take the Longest?

| Step | Typical Duration | Why |
|---|---|---|
| **2** (Terraform Deploy) | 3-5 minutes | Creating VMs on Proxmox |
| **3** (Wait for VMs) | ~3 minutes | Fixed boot delay |
| **5** (Apply Talos Configs) | 2-5 minutes | Network connectivity to each node |
| **6** (Verify Cluster Health) | 3-10 minutes | Waiting for Kubernetes to fully start |
| **9** (Infrastructure Stack) | 5-10 minutes | Deploying multiple Helm charts |
| **11** (OpenVAS) | 5-15 minutes | Large container images to pull and start |
| **20** (Build Images) | 5-10 minutes | Building Docker images |

## Which Steps Are Most Likely to Fail?

| Step | Common Cause | Resolution |
|---|---|---|
| **2** | Proxmox API unreachable | Check network, then Resume |
| **3** | VMs take longer than expected to boot | Resume (step will retry) |
| **5** | Nodes not reachable via Talos API | Check DHCP/network, then Resume |
| **6** | Cluster health check timeout | Wait, then Resume |
| **11-15** | Image pull failures or Pod scheduling issues | Check cluster resources, then Resume |
| **20** | Docker build fails on Build VM | Check Build VM connectivity, then Resume |

See [Recovery & Troubleshooting](../deployment/recovery.md) for how to resume or skip failed steps.
