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

## Prerequisites for DNS-based Deployment

1. **DNS Configuration**: All FQDNs must be resolvable in your network
2. **DNS Records**: Create A records for all hosts listed above
3. **Network Access**: The jumpbox must have network access to all FQDNs
4. **DHCP Configuration**: Ensure DHCP is properly configured for the 10.83.3.0/24 network


