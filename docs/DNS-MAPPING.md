## DNS to IP Address Mapping

### Proxmox Nodes
| FQDN | IP Address |
|------|------------|
| pve01.knowledgeondemand.net | 10.83.2.20 |
| pve02.knowledgeondemand.net | 10.83.2.21 |
| pve03.knowledgeondemand.net | 10.83.2.22 |
| pve04.knowledgeondemand.net | 10.83.2.23 |

### OPNsense Firewall VMs
| FQDN | IP Address | MAC Address |
|------|------------|-------------|
| opnsense-fw-01.knowledgeondemand.net | 10.83.3.5 | BC:24:21:F1:00:01 |
| opnsense-fw-02.knowledgeondemand.net | 10.83.3.6 | BC:24:21:F1:00:02 |

### Talos Kubernetes Cluster
| FQDN | IP Address | Role | MAC Address |
|------|------------|------|-------------|
| talos-CleanRoom-master-01.knowledgeondemand.net | 10.83.3.10 | Control Plane | BC:24:21:A4:B2:97 |
| talos-CleanRoom-worker-01.knowledgeondemand.net | 10.83.3.15 | Worker | BC:24:21:4C:99:A1 |
| talos-CleanRoom-worker-02.knowledgeondemand.net | 10.83.3.16 | Worker | BC:24:21:4C:99:A2 |
| talos-CleanRoom-worker-03.knowledgeondemand.net | 10.83.3.17 | Worker | BC:24:21:4C:99:A3 |

### LXC Containers
| Name | VMID | IP Address | Purpose |
|------|------|------------|---------|
| deployment-webui | 200 | 10.83.3.190 | Deployment Console (cluster lifecycle) |
| build-vm | 201 | 10.83.3.191 | Docker image builds for Harbor |

### Kubernetes Services (via Traefik LoadBalancer)

All services route through Traefik's MetalLB IP (10.83.3.200-250 range).
Create DNS A records for each FQDN below pointing to the Traefik external IP.

| FQDN | Service |
|------|---------|
| traefik.knowledgeondemand.net | Traefik Dashboard |
| argocd.knowledgeondemand.net | ArgoCD UI |
| harbor.knowledgeondemand.net | Harbor Container Registry |
| openvas.knowledgeondemand.net | OpenVAS Vulnerability Scanner |
| faraday.knowledgeondemand.net | Faraday Vulnerability Management |
| threatdragon.knowledgeondemand.net | OWASP Threat Dragon |
| scan.knowledgeondemand.net | Scanning Console (vulnerability scanning & reporting) |
| cleanroom.knowledgeondemand.net | Unified Portal (landing page & cross-app auth) |

### CLI-Only Services (no DNS record needed)

| Service | Access |
|---------|--------|
| Metasploit | `kubectl exec -it -n metasploit deploy/metasploit -c metasploit -- ./msfconsole` |
| SecureCodeBox | Create `Scan` CRDs; results parsed by operator |
| LOKI-RS IOC Scanner | Triggered from Scanning Console IOC Scan tab |

## Prerequisites for DNS-based Deployment

1. **DNS Configuration**: All FQDNs must be resolvable in your network
2. **DNS Records**: Create A records for all hosts listed above
3. **Wildcard TLS**: A wildcard certificate for `*.knowledgeondemand.net` is managed by cert-manager
4. **Network Access**: The deployment machine must have network access to all FQDNs
5. **DHCP Configuration**: Ensure DHCP reservations are configured for the 10.83.3.0/24 network
