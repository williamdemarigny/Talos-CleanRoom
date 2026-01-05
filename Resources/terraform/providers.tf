
# Resources/terraform/providers.tf
terraform {
  required_providers {
    talos = {
      source  = "siderolabs/talos"
      version = "0.10.0"
    }
    proxmox = {
      source  = "bpg/proxmox"
      version = "0.90.0"
    }
  }
}