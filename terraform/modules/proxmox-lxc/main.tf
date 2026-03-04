# ──────────────────────────────────────────────────────────────────────────────
# Proxmox LXC Module — Container Resource
#
# Shared module that captures the common Proxmox LXC container pattern used
# across multiple root modules (webui-lxc, build-lxc, etc.).
# ──────────────────────────────────────────────────────────────────────────────

terraform {
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = ">= 0.82.1"
    }
  }
}

resource "proxmox_virtual_environment_container" "this" {
  description = var.description

  node_name = var.node_name
  vm_id     = var.vmid
  tags      = var.tags

  # Container configuration
  unprivileged  = var.unprivileged
  started       = var.started
  start_on_boot = var.start_on_boot

  # Operating system template
  operating_system {
    template_file_id = "${var.template_storage}:vztmpl/${var.template_filename}"
    type             = var.os_type
  }

  # CPU configuration
  cpu {
    cores = var.cores
  }

  # Memory configuration
  memory {
    dedicated = var.memory
    swap      = var.swap
  }

  # Root filesystem
  disk {
    datastore_id = var.disk_datastore_id
    size         = var.disk_size
  }

  # Network configuration
  network_interface {
    name        = "eth0"
    bridge      = var.network_bridge
    vlan_id     = var.vlan_id > 0 ? var.vlan_id : null
    mac_address = var.mac_address != "" ? var.mac_address : null
  }

  # Initial configuration
  initialization {
    hostname = var.hostname

    ip_config {
      ipv4 {
        address = var.ip_address
        gateway = var.gateway
      }
    }

    dns {
      domain  = var.dns_domain
      servers = var.dns_servers
    }

    user_account {
      password = var.root_password
      keys     = var.ssh_public_keys
    }
  }

  # Assign to resource pool
  pool_id = var.pool_id != "" ? var.pool_id : null

  # Features
  features {
    nesting = var.feature_nesting
    keyctl  = var.feature_keyctl
  }
}
