# Proxmox Connection Variables
variable "proxmox_api_url" {
  description = "The URL for the Proxmox API."
  type        = string

  validation {
    condition     = can(regex("^https://", var.proxmox_api_url))
    error_message = "proxmox_api_url must start with https://"
  }
}

variable "proxmox_api_token" {
  description = "The Proxmox API token."
  type        = string
  sensitive   = true
}

variable "proxmox_node" {
  description = "Default Proxmox node for deployment. If empty, first available node is used."
  type        = string
  default     = ""
}

variable "proxmox_pool" {
  description = "The Proxmox resource pool for container organization."
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

# LXC Container Configuration
variable "lxc_vmid" {
  description = "VM ID for the LXC container."
  type        = number
  default     = 200
}

variable "lxc_hostname" {
  description = "Hostname for the LXC container."
  type        = string
  default     = "deployment-webui"
}

variable "lxc_cores" {
  description = "Number of CPU cores for the container."
  type        = number
  default     = 2
}

variable "lxc_memory" {
  description = "Memory in MB for the container."
  type        = number
  default     = 2048
}

variable "lxc_swap" {
  description = "Swap memory in MB for the container."
  type        = number
  default     = 512
}

variable "lxc_disk_size" {
  description = "Root disk size in GB for the container."
  type        = number
  default     = 20
}

variable "lxc_storage" {
  description = "Storage location for the container root filesystem."
  type        = string
  default     = "local-lvm"
}

variable "lxc_tags" {
  description = "Tags to apply to the container."
  type        = list(string)
  default     = ["deployment", "webui", "management"]
}

# Template Configuration
# Note: Template must be downloaded manually - Proxmox may not have internet access
# Download with: pveam download cephfs debian-12-standard_12.12-1_amd64.tar.zst

variable "template_storage" {
  description = "Storage location for LXC templates."
  type        = string
  default     = "cephfs"
}

variable "lxc_template_filename" {
  description = "Filename for the LXC template."
  type        = string
  default     = "debian-12-standard_12.12-1_amd64.tar.zst"
}

# Network Configuration
variable "network_bridge" {
  description = "Proxmox bridge to attach container NIC to."
  type        = string
  default     = "vmbr0"
}

variable "vlan_id" {
  description = "VLAN ID for the container (0 for no VLAN)."
  type        = number
  default     = 0
}

variable "lxc_ip_address" {
  description = "IP address for the container in CIDR notation (e.g., 192.168.1.100/24)."
  type        = string
}

variable "lxc_gateway" {
  description = "Default gateway for the container."
  type        = string
}

variable "lxc_mac_address" {
  description = "Optional MAC address for the container NIC."
  type        = string
  default     = ""
}

variable "dns_domain" {
  description = "DNS domain for the container."
  type        = string
  default     = "knowledgeondemand.net"
}

variable "dns_servers" {
  description = "DNS servers for the container."
  type        = list(string)
  default     = ["8.8.8.8", "8.8.4.4"]
}

# Authentication
variable "lxc_root_password" {
  description = "Root password for the container."
  type        = string
  sensitive   = true
}

variable "ssh_public_keys" {
  description = "SSH public keys to add to the container for root access."
  type        = list(string)
  default     = []
}

# Web UI Configuration
variable "webui_admin_username" {
  description = "Admin username for the web UI."
  type        = string
  default     = "admin"
}

variable "webui_admin_password" {
  description = "Admin password for the web UI (will be hashed)."
  type        = string
  sensitive   = true
  default     = "admin"
}
