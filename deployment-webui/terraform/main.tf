terraform {
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "0.82.1"
    }
  }
}

provider "proxmox" {
  endpoint  = var.proxmox_api_url
  api_token = var.proxmox_api_token
  insecure  = true
  ssh {
    username = var.proxmox_ssh_user
    password = var.proxmox_ssh_password
  }
}

# Query available nodes in the Proxmox cluster
data "proxmox_virtual_environment_nodes" "cluster_nodes" {
}

# Note: Template download removed - Proxmox host may not have internet access
# Download the template manually using pveam or upload via the Proxmox UI:
#   pveam download cephfs debian-12-standard_12.12-1_amd64.tar.zst
# Or use an existing template on your Proxmox host

# Deployment Web UI LXC Container
resource "proxmox_virtual_environment_container" "deployment_webui" {
  description = "Talos CleanRoom Deployment Web UI"

  node_name = var.proxmox_node != "" ? var.proxmox_node : data.proxmox_virtual_environment_nodes.cluster_nodes.names[0]
  vm_id     = var.lxc_vmid
  tags      = var.lxc_tags

  # Container configuration
  unprivileged = true
  started      = true
  start_on_boot = true

  # Operating system template
  # Template must exist on Proxmox - download with: pveam download cephfs debian-12-standard_12.12-1_amd64.tar.zst
  operating_system {
    template_file_id = "${var.template_storage}:vztmpl/${var.lxc_template_filename}"
    type             = "debian"
  }

  # CPU configuration
  cpu {
    cores = var.lxc_cores
  }

  # Memory configuration
  memory {
    dedicated = var.lxc_memory
    swap      = var.lxc_swap
  }

  # Root filesystem
  disk {
    datastore_id = var.lxc_storage
    size         = var.lxc_disk_size
  }

  # Network configuration
  network_interface {
    name        = "eth0"
    bridge      = var.network_bridge
    vlan_id     = var.vlan_id > 0 ? var.vlan_id : null
    mac_address = var.lxc_mac_address != "" ? var.lxc_mac_address : null
  }

  # Initial configuration
  initialization {
    hostname = var.lxc_hostname

    ip_config {
      ipv4 {
        address = var.lxc_ip_address
        gateway = var.lxc_gateway
      }
    }

    dns {
      domain  = var.dns_domain
      servers = var.dns_servers
    }

    user_account {
      password = var.lxc_root_password
      keys     = var.ssh_public_keys
    }
  }

  # Mount point for the repository (bind mount from Proxmox host)
  # Note: Requires manual setup on Proxmox host
  # mount_point {
  #   volume = "/path/to/repo"
  #   path   = "/repo"
  #   shared = false
  # }

  # Assign to resource pool
  pool_id = var.proxmox_pool != "" ? var.proxmox_pool : null

  # Features
  features {
    nesting = true  # Allow nested containers/docker if needed
  }

  depends_on = [data.proxmox_virtual_environment_nodes.cluster_nodes]
}

# Outputs
output "container_id" {
  description = "The VM ID of the created LXC container"
  value       = proxmox_virtual_environment_container.deployment_webui.vm_id
}

output "container_ip" {
  description = "The IP address of the container"
  value       = var.lxc_ip_address
}

output "webui_url" {
  description = "URL to access the Deployment Web UI"
  value       = "http://${trimsuffix(var.lxc_ip_address, "/24")}:8000"
}

output "container_hostname" {
  description = "The hostname of the container"
  value       = var.lxc_hostname
}

output "proxmox_node" {
  description = "The Proxmox node where the container is deployed"
  value       = proxmox_virtual_environment_container.deployment_webui.node_name
}
