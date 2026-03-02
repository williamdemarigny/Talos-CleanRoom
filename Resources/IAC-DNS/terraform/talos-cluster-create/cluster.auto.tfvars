# Fully populated cluster configuration (non-secret). Adjust as needed.
# Secrets (API token, SSH password) go ONLY in credentials.auto.tfvars.

# ============================================================================
# OPNSense Firewall Configuration
# ============================================================================
# Enable OPNSense firewall deployment (deployed before Talos cluster)
opnsense_enabled = false

# OPNSense template configuration (cloned from existing template VM)
# IMPORTANT: Specify the node where template VM 1000 is located
opnsense_template_vmid    = 1000
opnsense_template_node    = "pve01" # Change to the node where template exists (pve01, pve02, etc)
opnsense_template_storage = "CleanRoom_Storage"

# OPNSense VMs (cloned from template VMID 1000)
# Note: Cloned VMs must use different VMIDs than the template
opnsense_vms = [
  {
    name        = "opnsense-fw-01"
    vmid        = 1010
    fqdn        = "opnsense-fw-01.knowledgeondemand.net"
     ip_address  = "10.83.3.5"
    cores       = 2
    memory      = 8192
    disk_size   = "32G"
    mac_address = "BC:24:21:F1:00:01"
    tags        = ["opnsense", "firewall", "fw-01"]
  },
  {
    name        = "opnsense-fw-02"
    vmid        = 1011
    fqdn        = "opnsense-fw-02.knowledgeondemand.net"
     ip_address  = "10.83.3.6"
    cores       = 2
    memory      = 8192
    disk_size   = "32G"
    mac_address = "BC:24:21:F1:00:02"
    tags        = ["opnsense", "firewall", "fw-02"]
  }
]

# ============================================================================
# Talos Kubernetes Cluster Configuration
# ============================================================================
# Talos ISOs uploaded to Proxmox ISO storage
# Confirm filenames match Proxmox storage list.
talos_iso_file = "cephfs:iso/metal-amd64.iso" # Talos v1.12.2 with qemu-guest-agent

# Datastore for all VM disks. Uses shared Ceph storage for HA compatibility.
disk_storage = "CleanRoom_Storage"

# Proxmox network bridge
network_bridge = "vmbr0"

# Cluster node definitions (MACs preserved for router/DHCP reservations)
# Fields:
# - vmid: unique VM ID per Proxmox node
# - role: controlplane | worker
# Storage is provided by Ceph CSI (RBD) — no secondary disks needed

nodes = [
  # Control Plane Node - Uses standard Talos ISO
  {
    name        = "talos-CleanRoom-master-01",
    vmid        = 2000,
    role        = "controlplane",
    fqdn        = "talos-CleanRoom-master-01.knowledgeondemand.net",
    cores       = 4,
    memory      = 24576,
    disk_size   = "30G",
    mac_address = "BC:24:21:A4:B2:97",
    tags        = ["talos", "controlplane"]
  },

  # Regular Worker Node - Uses standard Talos ISO
  # Storage via Ceph CSI (RBD) — no secondary disk needed
  {
    name        = "talos-CleanRoom-worker-01",
    vmid        = 3001,
    role        = "worker",
    fqdn        = "talos-CleanRoom-worker-01.knowledgeondemand.net",
    cores       = 4,
    memory      = 24576,
    disk_size   = "30G",
    mac_address = "BC:24:21:4C:99:A1",
    tags        = ["talos", "worker"]
  },

  # Regular Worker Node - Uses standard Talos ISO
  # Storage via Ceph CSI (RBD) — no secondary disk needed
  {
    name        = "talos-CleanRoom-worker-02",
    vmid        = 3002,
    role        = "worker",
    fqdn        = "talos-CleanRoom-worker-02.knowledgeondemand.net",
    cores       = 4,
    memory      = 24576,
    disk_size   = "30G",
    mac_address = "BC:24:21:4C:99:A2",
    tags        = ["talos", "worker"]
  },

  # Regular Worker Node - Uses standard Talos ISO
  # Storage via Ceph CSI (RBD) — no secondary disk needed
  {
    name        = "talos-CleanRoom-worker-03",
    vmid        = 3003,
    role        = "worker",
    fqdn        = "talos-CleanRoom-worker-03.knowledgeondemand.net",
    cores       = 4,
    memory      = 24576,
    disk_size   = "30G",
    mac_address = "BC:24:21:4C:99:A3",
    tags        = ["talos", "worker"]
  }

]
