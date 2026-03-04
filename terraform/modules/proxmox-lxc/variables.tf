# ──────────────────────────────────────────────────────────────────────────────
# Proxmox LXC Module — Input Variables
# ──────────────────────────────────────────────────────────────────────────────

# ── Placement ────────────────────────────────────────────────────────────────

variable "node_name" {
  description = "Proxmox node to deploy on. Required."
  type        = string
}

variable "vmid" {
  description = "VM ID for the LXC container."
  type        = number
}

variable "description" {
  description = "Human-readable description shown in the Proxmox UI."
  type        = string
  default     = ""
}

variable "tags" {
  description = "Tags to apply to the container."
  type        = list(string)
  default     = []
}

variable "pool_id" {
  description = "Proxmox resource pool ID. Empty string means no pool."
  type        = string
  default     = ""
}

# ── Container Lifecycle ──────────────────────────────────────────────────────

variable "unprivileged" {
  description = "Run container unprivileged."
  type        = bool
  default     = true
}

variable "started" {
  description = "Start the container after creation."
  type        = bool
  default     = true
}

variable "start_on_boot" {
  description = "Start the container when the Proxmox host boots."
  type        = bool
  default     = true
}

# ── OS Template ──────────────────────────────────────────────────────────────

variable "template_storage" {
  description = "Proxmox storage that holds the container template."
  type        = string
  default     = "cephfs"
}

variable "template_filename" {
  description = "Template filename (under vztmpl/)."
  type        = string
  default     = "debian-12-standard_12.12-1_amd64.tar.zst"
}

variable "os_type" {
  description = "Operating system type for the container."
  type        = string
  default     = "debian"
}

# ── Compute ──────────────────────────────────────────────────────────────────

variable "cores" {
  description = "Number of CPU cores."
  type        = number
  default     = 2
}

variable "memory" {
  description = "Dedicated memory in MB."
  type        = number
  default     = 2048
}

variable "swap" {
  description = "Swap memory in MB."
  type        = number
  default     = 512
}

# ── Storage ──────────────────────────────────────────────────────────────────

variable "disk_datastore_id" {
  description = "Datastore for the root filesystem."
  type        = string
  default     = "local-lvm"
}

variable "disk_size" {
  description = "Root disk size in GB."
  type        = number
  default     = 20
}

# ── Network ──────────────────────────────────────────────────────────────────

variable "network_bridge" {
  description = "Proxmox bridge for the container NIC."
  type        = string
  default     = "vmbr0"
}

variable "vlan_id" {
  description = "VLAN ID (0 = no VLAN tagging)."
  type        = number
  default     = 0
}

variable "mac_address" {
  description = "Optional fixed MAC address. Empty string lets Proxmox auto-assign."
  type        = string
  default     = ""
}

# ── Initialization ───────────────────────────────────────────────────────────

variable "hostname" {
  description = "Container hostname."
  type        = string
}

variable "ip_address" {
  description = "IPv4 address in CIDR notation (e.g. 10.83.3.190/24)."
  type        = string
}

variable "gateway" {
  description = "IPv4 default gateway."
  type        = string
}

variable "dns_domain" {
  description = "DNS search domain."
  type        = string
  default     = "knowledgeondemand.net"
}

variable "dns_servers" {
  description = "List of DNS resolver addresses."
  type        = list(string)
  default     = ["8.8.8.8", "8.8.4.4"]
}

variable "root_password" {
  description = "Root password for the container."
  type        = string
  sensitive   = true
}

variable "ssh_public_keys" {
  description = "SSH public keys injected into the container."
  type        = list(string)
  default     = []
}

# ── Features ─────────────────────────────────────────────────────────────────

variable "feature_nesting" {
  description = "Enable nesting (required for Docker-in-LXC, nested containers)."
  type        = bool
  default     = true
}

variable "feature_keyctl" {
  description = "Enable keyctl (required for Docker overlay2 in unprivileged LXC)."
  type        = bool
  default     = false
}
