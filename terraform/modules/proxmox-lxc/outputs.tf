# ──────────────────────────────────────────────────────────────────────────────
# Proxmox LXC Module — Outputs
# ──────────────────────────────────────────────────────────────────────────────

output "container_id" {
  description = "The VM ID of the created LXC container."
  value       = proxmox_virtual_environment_container.this.vm_id
}

output "node_name" {
  description = "The Proxmox node where the container was deployed."
  value       = proxmox_virtual_environment_container.this.node_name
}

output "ip_address" {
  description = "The configured IP address (as passed in — CIDR notation)."
  value       = var.ip_address
}

output "hostname" {
  description = "The container hostname."
  value       = var.hostname
}
