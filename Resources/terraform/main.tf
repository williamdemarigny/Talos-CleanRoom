provider "proxmox" {
  endpoint = "https://pve01.knowledgeondemand.net:8006"
  insecure = true # Only needed if your Proxmox server is using a self-signed certificate
}
