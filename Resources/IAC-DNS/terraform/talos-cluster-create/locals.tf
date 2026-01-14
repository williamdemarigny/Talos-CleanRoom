locals {
  # Base configuration values - use reasonable defaults and derive from node data
  cluster_name  = "proxmox-talos-cluster"
  talos_version = "v1.12.1" # Match the ISO version
  cni_name      = "cilium"

  # Network configuration - using FQDN-based addressing
  network_cidr     = "10.83.3.0/24"
  gateway          = "10.83.3.1"
  cluster_endpoint = "https://${var.nodes[0].fqdn}:6443"

  # Storage and network settings from variables
  network_bridge          = var.network_bridge
  disk_storage            = var.disk_storage
  additional_disk_storage = var.additional_disk_storage
  vlan_id                 = var.vlan_id

  # Get available cluster nodes - safeguard against empty clusters
  available_nodes = length(data.proxmox_virtual_environment_nodes.cluster_nodes.names) > 0 ? data.proxmox_virtual_environment_nodes.cluster_nodes.names : []

  # Validate that we have available nodes
  validation = length(local.available_nodes) > 0 ? true : null

  # Distribute VMs evenly across available nodes using round-robin
  node_distribution = length(local.available_nodes) > 0 ? {
    for idx, node in var.nodes : node.name =>
    local.available_nodes[idx % length(local.available_nodes)]
  } : {}

  # Transform nodes from variables for use in resources
  all_nodes_transformed = {
    for node in var.nodes : node.name => {
      vmid                    = node.vmid
      name                    = node.name
      node_name               = lookup(var.node_affinity, node.name, lookup(local.node_distribution, node.name, null))
      cores                   = node.cores
      memory                  = node.memory
      fqdn                    = node.fqdn
      gateway                 = local.gateway
      disk_size               = node.disk_size
      disk_storage            = local.disk_storage
      disk_type               = "scsi"
      onboot                  = true
      sockets                 = 1
      network_bridge          = local.network_bridge
      network_model           = "virtio"
      mac_address             = node.mac_address
      vlan_id                 = coalesce(node.vlan_id, var.vlan_id)
      tags                    = lookup(node, "tags", [node.role])
      additional_disk_size    = lookup(node, "additional_disk_size", null)
      additional_disk_storage = lookup(node, "additional_disk_size", null) != null ? local.additional_disk_storage : null
      role                    = node.role
      iso_file                = node.role == "worker-gpu" ? coalesce(var.talos_gpu_iso_file, var.talos_iso_file) : var.talos_iso_file
    }
  }

  # Node type configurations for different roles
  node_configs = {
    controlplane = {
      cpu_type       = "host"
      memory_balloon = false
      bios           = "seabios"
      boot_order     = ["scsi0", "ide2"] # Boot from disk first, then ISO
      description    = "Talos Control Plane Node - Managed by Terraform"
    }
    worker = {
      cpu_type       = "host"
      memory_balloon = false
      bios           = "seabios"
      boot_order     = ["scsi0", "ide2"] # Boot from disk first, then ISO
      description    = "Talos Worker Node - Managed by Terraform"
    }
  }

  # OPNSense VM configuration
  opnsense_vms_transformed = var.opnsense_enabled ? {
    for idx, vm in var.opnsense_vms : vm.name => {
      vmid           = vm.vmid
      name           = vm.name
      node_name      = lookup(var.node_affinity, vm.name, local.available_nodes[idx % length(local.available_nodes)])
      cores          = vm.cores
      memory         = vm.memory
      fqdn           = vm.fqdn
      disk_size      = vm.disk_size
      disk_storage   = local.disk_storage
      network_bridge = local.network_bridge
      network_model  = "virtio"
      mac_address    = vm.mac_address
      vlan_id        = local.vlan_id
      tags           = lookup(vm, "tags", ["opnsense", "firewall"])
    }
  } : {}

  opnsense_config = {
    cpu_type       = "host"
    memory_balloon = false
    bios           = "seabios"
    description    = "OPNSense Firewall Appliance (cloned from template) - Managed by Terraform"
  }

  # OPNSense API configuration for each VM
  opnsense_api_config = var.opnsense_enabled && var.opnsense_api_key != "" ? {
    for vm_name, vm_data in local.opnsense_vms_transformed : vm_name => {
      url        = "${var.opnsense_api_protocol}://${vm_data.fqdn}:${var.opnsense_api_port}"
      api_key    = var.opnsense_api_key
      api_secret = var.opnsense_api_secret
      insecure   = var.opnsense_api_insecure
      fqdn       = vm_data.fqdn
      name       = vm_data.name
    }
  } : {}
}