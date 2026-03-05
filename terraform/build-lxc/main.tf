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

# ── Build VM LXC Container ──────────────────────────────────────────────────
# Used for building and pushing Docker images (e.g., LOKI-RS scanner) to Harbor

module "lxc_container" {
  source = "../modules/proxmox-lxc"

  node_name   = var.proxmox_node != "" ? var.proxmox_node : data.proxmox_virtual_environment_nodes.cluster_nodes.names[0]
  vmid        = var.lxc_vmid
  description = "Talos CleanRoom Build VM \u2014 Docker image builds"
  tags        = var.lxc_tags
  pool_id     = var.proxmox_pool

  # OS template
  template_storage  = var.template_storage
  template_filename = var.lxc_template_filename

  # Compute
  cores  = var.lxc_cores
  memory = var.lxc_memory
  swap   = var.lxc_swap

  # Storage
  disk_datastore_id = var.lxc_storage
  disk_size         = var.lxc_disk_size

  # Network
  network_bridge = var.network_bridge
  vlan_id        = var.vlan_id
  mac_address    = var.lxc_mac_address

  # Initialization
  hostname        = var.lxc_hostname
  ip_address      = var.lxc_ip_address
  gateway         = var.lxc_gateway
  dns_domain      = var.dns_domain
  dns_servers     = var.dns_servers
  root_password   = var.lxc_root_password
  ssh_public_keys = var.ssh_public_keys

  # Privileged container for Docker builds (avoids keyctl root@pam requirement)
  unprivileged    = false
  feature_nesting = true
  feature_keyctl  = false
}

# State migration: the resource was previously defined inline as
# proxmox_virtual_environment_container.build_vm — tell Terraform
# it now lives inside the module so that existing state is preserved.
moved {
  from = proxmox_virtual_environment_container.build_vm
  to   = module.lxc_container.proxmox_virtual_environment_container.this
}

# ── Outputs ──────────────────────────────────────────────────────────────────

output "container_id" {
  description = "The VM ID of the build VM LXC container"
  value       = module.lxc_container.container_id
}

output "container_ip" {
  description = "The IP address of the build VM"
  value       = module.lxc_container.ip_address
}

output "container_hostname" {
  description = "The hostname of the build VM"
  value       = module.lxc_container.hostname
}

output "proxmox_node" {
  description = "The Proxmox node where the build VM is deployed"
  value       = module.lxc_container.node_name
}
