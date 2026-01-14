# DNS Address Mapping for IAC-DNS

This directory contains a DNS-based version of the Infrastructure as Code, allowing deployment from a jumpbox within the network.

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
| talos-CleanRoom-worker-02.knowledgeondemand.net | 10.83.3.15 | Worker | BC:24:21:4C:99:A1 |
| talos-CleanRoom-worker-03.knowledgeondemand.net | 10.83.3.16 | Worker | BC:24:21:4C:99:A2 |
| talos-CleanRoom-worker-04.knowledgeondemand.net | 10.83.3.17 | Worker | BC:24:21:4C:99:A3 |

## Key Changes from IP-based Configuration

### Terraform Files
- **credentials.auto.tfvars**: Proxmox API URL changed from IP to FQDN (`pve01.knowledgeondemand.net`)
- **cluster.auto.tfvars**: All node and VM definitions now use `fqdn` field instead of `ip`
- **variables.tf**: Variable definitions updated to use `fqdn` instead of `ip`
- **locals.tf**: Network configuration uses static values, FQDNs referenced for cluster endpoint
- **main.tf**: Outputs updated to display FQDNs instead of IPs

### Talos Configuration Files
- **talconfig.yaml**:
  - Cluster endpoint uses FQDN variable `${CONTROL_PLANE_ENDPOINT_FQDN}`
  - Node `ipAddress` fields use FQDN variables (e.g., `${TALOS_CONTROL_PLANE_FQDN_0}`)
  - Network interfaces set to `dhcp: true` (DNS resolution handles addressing)
- **talenv.yaml**: All IP variables converted to FQDN variables

### Scripts
- **tfvars-to-talos-env.sh**: Updated to extract and process FQDNs instead of IPs

## Prerequisites for DNS-based Deployment

1. **DNS Configuration**: All FQDNs must be resolvable in your network
2. **DNS Records**: Create A records for all hosts listed above
3. **Network Access**: The jumpbox must have network access to all FQDNs
4. **DHCP Configuration**: Ensure DHCP is properly configured for the 10.83.3.0/24 network

## Deployment Workflow

The deployment workflow remains the same as the IP-based configuration:

1. Deploy infrastructure with Terraform from the jumpbox
2. Generate Talos configuration using the updated scripts
3. Apply Talos configs (VMs will use DHCP + DNS)
4. Bootstrap the cluster

## Benefits of DNS-based Addressing

- **Portability**: Can run from any machine with DNS access (workstation or jumpbox)
- **Flexibility**: IP addresses can change without modifying code
- **Maintainability**: Centralized DNS management
- **Scalability**: Easier to add/move nodes without code changes
