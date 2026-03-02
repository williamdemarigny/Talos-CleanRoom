# Talos CleanRoom Build VM

A Debian 12 LXC container on Proxmox for building and pushing Docker images to the self-hosted Harbor registry. Follows the same Terraform + pct exec deployment pattern as the [Deployment WebUI](../deployment-webui/README.md).

## Purpose

The build VM provides a Docker-capable environment for:
- Building the LOKI-RS IOC scanner container image
- Pushing images to Harbor (`harbor.knowledgeondemand.net`)
- Creating Harbor projects and Kubernetes pull secrets via the `build-and-push.sh` script

## Quick Start

```bash
cd build-vm
./deploy-lxc.sh
```

Follow the prompts to enter Proxmox credentials, SSH key path, and kubeconfig path. The script handles everything: LXC creation, Docker CE installation, kubectl setup, repo clone, and secret copying.

Once deployed, build and push the LOKI-RS image:

```bash
ssh deploy@10.83.3.191
cd /opt/talos-cleanroom/Resources/IAC-DNS/infrastructure/projects/loki
./build-and-push.sh
```

## Container Specifications

| Setting | Value |
|---------|-------|
| VMID | 201 |
| Hostname | build-vm |
| IP | 10.83.3.191/24 |
| Cores | 2 |
| Memory | 4096 MB |
| Disk | 50 GB |
| OS | Debian 12 |
| LXC Features | nesting + keyctl (required for Docker) |

## Prerequisites

- Proxmox VE 7.x or 8.x
- Terraform installed on your workstation
- Proxmox API token with appropriate permissions
- SSH key with access to the GitHub repository
- Kubeconfig with access to the Talos cluster (for creating pull secrets)

## What Gets Installed

The `scripts/setup-lxc.sh` installs:

| Tool | Purpose |
|------|---------|
| Docker CE | Build and push container images |
| kubectl | Create Kubernetes secrets, manage namespaces |
| curl, jq | Harbor API calls in `build-and-push.sh` |
| git | Pull repository updates |

**Not installed** (these are on the WebUI LXC instead): Python, Helm, Terraform, talosctl, talhelper, SOPS.

## Directory Structure

```
build-vm/
├── README.md              # This file
├── deploy-lxc.sh          # Main deployment script
├── scripts/
│   └── setup-lxc.sh       # Container setup (Docker CE, kubectl)
└── terraform/
    ├── main.tf             # LXC resource definition
    └── variables.tf        # Variable definitions
```

## How deploy-lxc.sh Works

Same 6-step pattern as the WebUI's `deploy-lxc.sh`:

1. **Collect credentials**: Proxmox API token, SSH passwords, GitHub SSH key, kubeconfig path
2. **Check LXC template**: Verify Debian 12 template exists on Proxmox (downloads if missing)
3. **Terraform deploy**: Create the LXC container
4. **Container setup via pct exec**: Install packages, create `deploy` user (with `docker` group), clone repo, run `setup-lxc.sh`
5. **Copy secrets**: Kubeconfig to `/root/.kube/config` and `~deploy/.kube/config`
6. **Done**: SSH access info and next steps

### Key Differences from WebUI deploy-lxc.sh

| Aspect | WebUI (VMID 200) | Build VM (VMID 201) |
|--------|-------------------|---------------------|
| Docker | Not installed | Docker CE |
| Python/FastAPI | Installed | Not installed |
| Helm/TF/talosctl/SOPS | Installed | Not installed |
| keyctl LXC feature | No | Yes (Docker requires it) |
| SSH user groups | sudo | sudo,docker |
| Secrets copied | SOPS keys + TF creds | Kubeconfig |
| Systemd service | deployment-webui | None |

## Docker in Unprivileged LXC

Running Docker inside an unprivileged Proxmox LXC requires two features in the container config:

- **nesting = true**: Allows nested namespaces
- **keyctl = true**: Allows keyring operations (required for Docker's overlay2 storage driver)

Both are set automatically in `terraform/main.tf`. No privileged container needed.

## build-and-push.sh

The `build-and-push.sh` script (located at `Resources/IAC-DNS/infrastructure/projects/loki/build-and-push.sh`) handles the full bootstrap:

1. Check prerequisites (docker, kubectl, curl, jq)
2. Collect Harbor credentials (or use `HARBOR_USER` / `HARBOR_PASSWORD` env vars)
3. Wait for Harbor to be healthy
4. Create `cleanroom` project via Harbor API (idempotent)
5. Create `harbor-pull-secret` in `loki-scanner` namespace (idempotent)
6. Docker login to Harbor
7. Build the LOKI-RS image
8. Push to Harbor

```bash
# Interactive (prompts for password)
./build-and-push.sh

# Non-interactive
HARBOR_PASSWORD=xxx ./build-and-push.sh

# Specify LOKI-RS version
./build-and-push.sh v2.10.0
```

## Maintenance

### Updating the Repository

```bash
ssh deploy@10.83.3.191
cd /opt/talos-cleanroom
git pull
```

### Rebuilding an Image

```bash
cd /opt/talos-cleanroom/Resources/IAC-DNS/infrastructure/projects/loki
./build-and-push.sh v2.10.0
```

### Docker Cleanup

```bash
# Remove unused images and build cache
docker system prune -a
```

### Recovery

If locked out of SSH:
```bash
ssh root@pve01.knowledgeondemand.net 'pct exec 201 -- bash'
```
