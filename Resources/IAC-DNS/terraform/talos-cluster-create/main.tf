terraform {
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "0.82.1"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
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

# OPNSense Firewall VMs - deployed first (cloned from template)
resource "proxmox_virtual_environment_vm" "opnsense" {
  for_each = local.opnsense_vms_transformed

  name        = each.value.name
  node_name   = each.value.node_name
  description = local.opnsense_config.description
  tags        = each.value.tags
  vm_id       = each.value.vmid

  # Clone from template
  clone {
    vm_id        = var.opnsense_template_vmid
    node_name    = var.opnsense_template_node != "" ? var.opnsense_template_node : null
    datastore_id = var.opnsense_template_storage
    full         = true
  }

  # Start VM after configuration is applied (MAC address updated)
  started = true
  on_boot = true
  bios    = local.opnsense_config.bios

  # Enable QEMU Guest Agent for better VM management
  agent {
    enabled = true
  }

  # Boot from disk
  boot_order = ["scsi0"]

  cpu {
    cores   = each.value.cores
    sockets = 1
    type    = local.opnsense_config.cpu_type
  }

  memory {
    dedicated = each.value.memory
  }

  # Network configuration - MAC address will be updated after clone to avoid conflicts
  network_device {
    bridge      = each.value.network_bridge
    model       = each.value.network_model
    mac_address = each.value.mac_address
    vlan_id     = each.value.vlan_id
  }

  # Assign to resource pool for organization
  pool_id = var.proxmox_pool != "" ? var.proxmox_pool : null

  depends_on = [data.proxmox_virtual_environment_nodes.cluster_nodes]
}

# Talos Kubernetes Cluster VMs - deployed after OPNSense
resource "proxmox_virtual_environment_vm" "vm" {
  for_each = local.all_nodes_transformed

  name        = each.value.name
  node_name   = each.value.node_name != "" ? each.value.node_name : data.proxmox_virtual_environment_nodes.cluster_nodes.names[0]
  description = local.node_configs[each.value.role].description
  tags        = each.value.tags
  vm_id       = each.value.vmid

  started = each.value.onboot
  bios    = local.node_configs[each.value.role].bios

  # Enable QEMU Guest Agent for better VM management
  agent {
    enabled = true
  }

  # Boot the disk first, then the ISO as fallback
  boot_order = local.node_configs[each.value.role].boot_order

  cpu {
    cores   = each.value.cores
    sockets = each.value.sockets
    type    = local.node_configs[each.value.role].cpu_type
  }

  memory {
    dedicated = each.value.memory
  }

  # Network configuration
  network_device {
    bridge      = each.value.network_bridge
    model       = each.value.network_model
    mac_address = each.value.mac_address
    vlan_id     = each.value.vlan_id
  }

  # Primary disk
  disk {
    interface    = "scsi0"
    datastore_id = each.value.disk_storage
    size         = tonumber(trimsuffix(each.value.disk_size, "G"))
    cache        = "none"
    discard      = "ignore"
    ssd          = false
  }

  # Additional disk for storage (worker nodes with additional_disk_size)
  dynamic "disk" {
    for_each = each.value.additional_disk_size != null ? [1] : []
    content {
      interface    = "scsi1"
      datastore_id = each.value.additional_disk_storage
      size         = tonumber(trimsuffix(each.value.additional_disk_size, "G"))
      cache        = "none"
      discard      = "ignore"
      ssd          = false
      file_format  = "raw"
    }
  }

  # Assign to resource pool for cluster-level organization
  pool_id = var.proxmox_pool != "" ? var.proxmox_pool : null

  # Attach appropriate Talos ISO based on node role
  cdrom {
    interface = "ide2"
    file_id   = each.value.iso_file
  }

  depends_on = [
    data.proxmox_virtual_environment_nodes.cluster_nodes,
    proxmox_virtual_environment_vm.opnsense
  ]
}

# High Availability configuration for Talos VMs
resource "proxmox_virtual_environment_haresource" "talos_ha" {
  for_each = var.ha_enabled ? local.all_nodes_transformed : {}

  resource_id  = "vm:${proxmox_virtual_environment_vm.vm[each.key].vm_id}"
  state        = "started"
  group        = var.ha_group != "" ? var.ha_group : null
  max_relocate = var.ha_max_relocate
  max_restart  = var.ha_max_restart

  depends_on = [proxmox_virtual_environment_vm.vm]
}

# High Availability configuration for OPNSense VMs
resource "proxmox_virtual_environment_haresource" "opnsense_ha" {
  for_each = var.ha_enabled && var.opnsense_enabled ? local.opnsense_vms_transformed : {}

  resource_id  = "vm:${proxmox_virtual_environment_vm.opnsense[each.key].vm_id}"
  state        = "started"
  group        = var.ha_group != "" ? var.ha_group : null
  max_relocate = var.ha_max_relocate
  max_restart  = var.ha_max_restart

  depends_on = [proxmox_virtual_environment_vm.opnsense]
}

output "vm_mac_addresses" {
  description = "MAC addresses of the created VMs."
  value = {
    for k, v in proxmox_virtual_environment_vm.vm : k => v.network_device[0].mac_address
  }
}

output "vm_details" {
  description = "Details of created VMs organized by role."
  value = {
    for k, v in proxmox_virtual_environment_vm.vm : k => {
      vmid        = v.vm_id
      fqdn        = local.all_nodes_transformed[k].fqdn
      mac_address = v.network_device[0].mac_address
      role        = local.all_nodes_transformed[k].role
      cores       = v.cpu[0].cores
      memory      = v.memory[0].dedicated
      iso_used    = local.all_nodes_transformed[k].iso_file
    }
  }
}

output "node_roles" {
  description = "Node roles and their configurations."
  value = {
    controlplane = [for k, v in local.all_nodes_transformed : k if v.role == "controlplane"]
    workers      = [for k, v in local.all_nodes_transformed : k if v.role == "worker"]
  }
}

output "cluster_status" {
  description = "Proxmox cluster nodes available for VM deployment."
  value = {
    available_nodes = data.proxmox_virtual_environment_nodes.cluster_nodes.names
    node_count      = length(data.proxmox_virtual_environment_nodes.cluster_nodes.names)
  }
}

output "vm_distribution" {
  description = "VM distribution across cluster nodes."
  value = {
    for node_name in data.proxmox_virtual_environment_nodes.cluster_nodes.names :
    node_name => [
      for vm_name, vm_data in local.all_nodes_transformed :
      vm_data.name if vm_data.node_name == node_name
    ]
  }
}

# OPNSense Outputs
output "opnsense_vms" {
  description = "Details of deployed OPNSense firewall VMs."
  value = var.opnsense_enabled ? {
    for k, v in proxmox_virtual_environment_vm.opnsense : k => {
      vmid        = v.vm_id
      name        = v.name
      fqdn        = local.opnsense_vms_transformed[k].fqdn
      mac_address = v.network_device[0].mac_address
      cores       = v.cpu[0].cores
      memory      = v.memory[0].dedicated
      node        = v.node_name
      status      = "deployed"
    }
  } : {}
}

output "deployment_order" {
  description = "Order of VM deployment."
  value = var.opnsense_enabled ? {
    first  = "OPNSense Firewalls"
    second = "Talos Kubernetes Cluster"
    } : {
    only = "Talos Kubernetes Cluster"
  }
}

# OPNSense API Connection Information
output "opnsense_api_endpoints" {
  description = "OPNSense API endpoints for each firewall VM."
  sensitive   = true
  value = var.opnsense_enabled && var.opnsense_api_key != "" ? {
    for k, v in proxmox_virtual_environment_vm.opnsense : k => {
      name     = v.name
      url      = "${var.opnsense_api_protocol}://${local.opnsense_vms_transformed[k].fqdn}:${var.opnsense_api_port}"
      fqdn     = local.opnsense_vms_transformed[k].fqdn
      port     = var.opnsense_api_port
      protocol = var.opnsense_api_protocol
      insecure = var.opnsense_api_insecure
    }
  } : {}
}

output "opnsense_api_configured" {
  description = "Indicates whether OPNSense API credentials are configured."
  sensitive   = true
  value       = var.opnsense_enabled && var.opnsense_api_key != "" && var.opnsense_api_secret != ""
}

# High Availability Outputs
output "ha_enabled" {
  description = "Whether High Availability is enabled for VMs."
  value       = var.ha_enabled
}

output "ha_talos_vms" {
  description = "High Availability status for Talos VMs."
  value = {
    for k, v in proxmox_virtual_environment_haresource.talos_ha : k => {
      resource_id  = v.resource_id
      state        = v.state
      max_relocate = v.max_relocate
      max_restart  = v.max_restart
    }
  }
}

output "ha_opnsense_vms" {
  description = "High Availability status for OPNSense VMs."
  value = {
    for k, v in proxmox_virtual_environment_haresource.opnsense_ha : k => {
      resource_id  = v.resource_id
      state        = v.state
      max_relocate = v.max_relocate
      max_restart  = v.max_restart
    }
  }
}