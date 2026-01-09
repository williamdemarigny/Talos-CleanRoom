locals {
  # Base configuration values - use reasonable defaults and derive from node data
  cluster_name     = "proxmox-talos-cluster"
  talos_version    = "v1.12.1"  # Match the ISO version
  cni_name         = "cilium"
  
  # Network configuration - derive from first node IP
  network_cidr     = "${join(".", slice(split(".", var.nodes[0].ip), 0, 3))}.0/24"
  gateway          = "${join(".", slice(split(".", var.nodes[0].ip), 0, 3))}.1"
  cluster_endpoint = "https://${join(".", slice(split(".", var.nodes[0].ip), 0, 3))}.100:6443"
  
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
      node_name              = lookup(var.node_affinity, node.name, lookup(local.node_distribution, node.name, null))
      cores                   = node.cores
      memory                  = node.memory
      ip                      = node.ip
      gateway                 = local.gateway
      disk_size               = node.disk_size
      disk_storage            = local.disk_storage
      disk_type               = "scsi"
      onboot                  = true
      sockets                 = 1
      network_bridge          = local.network_bridge
      network_model           = "virtio"
      mac_address             = node.mac_address
      vlan_id                 = lookup(node, "vlan_id", var.vlan_id)
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
      cpu_type = "host"
      memory_balloon = false
      bios = "seabios"
      boot_order = ["scsi0", "ide2"]  # Boot from disk first, then ISO
      description = "Talos Control Plane Node - Managed by Terraform"
    }
    worker = {
      cpu_type = "host"
      memory_balloon = false
      bios = "seabios"
      boot_order = ["scsi0", "ide2"]  # Boot from disk first, then ISO
      description = "Talos Worker Node - Managed by Terraform"
    }
    "worker-gpu" = {
      cpu_type = "host"
      memory_balloon = false
      bios = "seabios"  # SeaBIOS works fine for GPU - configure passthrough in Proxmox UI
      boot_order = ["scsi0", "ide2"]  # Boot from disk first, then ISO
      description = "Talos GPU Worker Node (configure GPU passthrough in Proxmox UI) - Managed by Terraform"
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
      ip             = vm.ip
      disk_size      = vm.disk_size
      disk_storage   = local.disk_storage
      network_bridge = local.network_bridge
      network_model  = "virtio"
      mac_address    = vm.mac_address
      vlan_id        = local.vlan_id
      tags           = lookup(vm, "tags", ["opnsense", "firewall"])
      iso_file       = var.opnsense_iso_file
    }
  } : {}

  opnsense_config = {
    cpu_type       = "host"
    memory_balloon = false
    bios           = "seabios"
    boot_order     = ["ide2", "scsi0"]  # Boot from ISO first for initial setup, then disk
    description    = "OPNSense Firewall Appliance - Managed by Terraform"
  }
}