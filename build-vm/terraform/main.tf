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

# Build VM LXC Container
# Used for building and pushing Docker images (e.g., LOKI-RS scanner) to Harbor
resource "proxmox_virtual_environment_container" "build_vm" {
  description = "Talos CleanRoom Build VM — Docker image builds"

  node_name = var.proxmox_node != "" ? var.proxmox_node : data.proxmox_virtual_environment_nodes.cluster_nodes.names[0]
  vm_id     = var.lxc_vmid
  tags      = var.lxc_tags

  # Container configuration
  unprivileged  = true
  started       = true
  start_on_boot = true

  # Operating system template
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

  # Assign to resource pool
  pool_id = var.proxmox_pool != "" ? var.proxmox_pool : null

  # Features — nesting + keyctl required for Docker in unprivileged LXC
  features {
    nesting = true
    keyctl  = true
  }

  depends_on = [data.proxmox_virtual_environment_nodes.cluster_nodes]
}

# Outputs
output "container_id" {
  description = "The VM ID of the build VM LXC container"
  value       = proxmox_virtual_environment_container.build_vm.vm_id
}

output "container_ip" {
  description = "The IP address of the build VM"
  value       = var.lxc_ip_address
}

output "container_hostname" {
  description = "The hostname of the build VM"
  value       = var.lxc_hostname
}

output "proxmox_node" {
  description = "The Proxmox node where the build VM is deployed"
  value       = proxmox_virtual_environment_container.build_vm.node_name
}
