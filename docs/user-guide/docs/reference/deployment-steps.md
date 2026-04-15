# Deployment Steps

The deployment process runs 26 automated steps (numbered 0-25). Here is what each step does in plain language.

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
| **11** | Deploy Harbor Registry | Installs the container image registry |
| **12** | Deploy Build VM | Creates the container image build environment (LXC) |
| **13** | Mirror Greenbone Images to Harbor | Pulls Greenbone (OpenVAS) images from upstream and pushes them to Harbor |
| **14** | Deploy OpenVAS | Installs the vulnerability scanner engine |
| **15** | Deploy Faraday | Installs the vulnerability management platform |
| **16** | Deploy Metasploit | Installs the penetration testing framework |
| **17** | Deploy Threat Dragon | Installs the threat modeling tool |
| **18** | Configure Integrations | Sets up connections between the deployed tools |
| **19** | Generate & Apply Secrets | Creates passwords and encryption keys for all services |
| **20** | Commit & Push Secrets | Saves encrypted secrets to the Git repository |
| **21** | Prepare Vulhub Target Environments | Downloads and prepares vulnerable test environments for the Target Lab |
| **22** | Build & Push Container Images | Builds the Scanning Console, Portal, and other custom images |
| **23** | Deploy CleanRoom Applications | Deploys the Scanning Console and Portal to Kubernetes |
| **24** | Deploy Deployment Console Routing | Configures Traefik routing for the Deployment Console |
| **25** | Apply Network Policies | Applies zero-trust network security rules between all services |

## Which Steps Take the Longest?

| Step | Typical Duration | Why |
|---|---|---|
| **2** (Terraform Deploy) | 3-5 minutes | Creating VMs on Proxmox |
| **3** (Wait for VMs) | ~3 minutes | Fixed boot delay |
| **5** (Apply Talos Configs) | 2-5 minutes | Network connectivity to each node |
| **6** (Verify Cluster Health) | 3-10 minutes | Waiting for Kubernetes to fully start |
| **9** (Infrastructure Stack) | 5-10 minutes | Deploying multiple Helm charts |
| **12** (Deploy Build VM) | 3-5 minutes | Provisioning LXC container |
| **13** (Mirror Greenbone Images) | 5-15 minutes | Pulling large images from upstream registry |
| **14** (Deploy OpenVAS) | 5-15 minutes | Large container images to pull and start |
| **22** (Build & Push Images) | 5-10 minutes | Building Docker images on Build VM |

## Which Steps Are Most Likely to Fail?

| Step | Common Cause | Resolution |
|---|---|---|
| **2** | Proxmox API unreachable | Check network, then Resume |
| **3** | VMs take longer than expected to boot | Resume (step will retry) |
| **5** | Nodes not reachable via Talos API | Check DHCP/network, then Resume |
| **6** | Cluster health check timeout | Wait, then Resume |
| **13** | Upstream registry unreachable or TLS issues | Check Build VM connectivity to Greenbone registry, then Resume |
| **14-17** | Image pull failures or Pod scheduling issues | Check cluster resources, then Resume |
| **22** | Docker build fails on Build VM | Check Build VM connectivity, then Resume |

See [Recovery & Troubleshooting](../deployment/recovery.md) for how to resume or skip failed steps.
