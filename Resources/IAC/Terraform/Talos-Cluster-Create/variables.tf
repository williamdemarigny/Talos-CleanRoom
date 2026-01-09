variable "proxmox_api_url" {
  description = "The URL for the Proxmox API."
  type        = string
  
  validation {
    condition     = can(regex("^https://", var.proxmox_api_url))
    error_message = "proxmox_api_url must start with https://"
  }
}

variable "proxmox_node" {
  description = "Default fallback Proxmox node. If empty, nodes are auto-discovered from cluster."
  type        = string
  default     = ""
}

variable "proxmox_api_token" {
  description = "The Proxmox API token."
  type        = string
  sensitive   = true
}

variable "proxmox_pool" {
  description = "The Proxmox resource pool for cluster-level VM organization."
  type        = string
  default     = ""
}

variable "proxmox_ssh_user" {
  description = "The SSH user for the Proxmox node."
  type        = string
  default     = "root"
}

variable "proxmox_ssh_password" {
  description = "The SSH password for the Proxmox node."
  type        = string
  sensitive   = true
}

variable "nodes" {
  description = "A list of virtual machines to create."
  type = list(object({
    name                 = string
    vmid                 = number
    role                 = string
    ip                   = string
    cores                = number
    memory               = number
    disk_size            = string
    mac_address          = string
    tags                 = optional(list(string))
    additional_disk_size = optional(string)
    additional_disk_storage = optional(string, "datapool")
    vlan_id              = optional(number)
  }))
}

variable "talos_iso_file" {
  description = "Default Proxmox storage reference to the uploaded Talos ISO for regular nodes, e.g. local:iso/talos-1.10.6.iso"
  type        = string
}

variable "talos_gpu_iso_file" {
  description = "Proxmox storage reference to the uploaded Talos GPU-enabled ISO, e.g. local:iso/talos-1.10.6-gpu.iso"
  type        = string
  default     = null
}

variable "disk_storage" {
  description = "Primary datastore ID for the main VM disk (e.g. local, local-zfs, zfs1)"
  type        = string
}

variable "additional_disk_storage" {
  description = "Datastore ID for any additional data disks (if nodes specify additional_disk_size)."
  type        = string
  default     = "local"
}

variable "network_bridge" {
  description = "Proxmox bridge to attach VM NICs to (e.g. vmbr0)."
  type        = string
  default     = "vmbr0"
}

variable "vlan_id" {
  description = "VLAN ID to assign to all VMs (1-4094)."
  type        = number
  default     = 3
  
  validation {
    condition     = var.vlan_id >= 1 && var.vlan_id <= 4094
    error_message = "vlan_id must be between 1 and 4094."
  }
}

variable "node_affinity" {
  description = "Optional map of VM names to preferred Proxmox cluster nodes for pinning specific VMs."
  type        = map(string)
  default     = {}
}

# OPNSense Configuration Variables
variable "opnsense_enabled" {
  description = "Enable deployment of OPNSense firewall VMs."
  type        = bool
  default     = false
}

variable "opnsense_iso_file" {
  description = "Proxmox storage reference to the uploaded OPNSense ISO, e.g. cephfs:iso/OPNSense-25.7-dvd-amd64.iso"
  type        = string
  default     = ""
}

variable "opnsense_vms" {
  description = "List of OPNSense firewall VMs to create."
  type = list(object({
    name        = string
    vmid        = number
    ip          = string
    cores       = number
    memory      = number
    disk_size   = string
    mac_address = string
    tags        = optional(list(string))
  }))
  default = []
}