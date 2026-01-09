# Fully populated cluster configuration (non-secret). Adjust as needed.
# Secrets (API token, SSH password) go ONLY in credentials.auto.tfvars.

# ============================================================================
# OPNSense Firewall Configuration
# ============================================================================
# Enable OPNSense firewall deployment (deployed before Talos cluster)
opnsense_enabled = true

# OPNSense template configuration (cloned from existing template VM)
# IMPORTANT: Specify the node where template VM 1000 is located
opnsense_template_vmid    = 1000
opnsense_template_node    = "pve01" # Change to the node where template exists (pve01, pve02, etc)
opnsense_template_storage = "CleanRoom_Storage"

# OPNSense VMs (cloned from template VMID 1000)
# Note: Cloned VMs must use different VMIDs than the template
opnsense_vms = [
  {
    name        = "opnsense-fw-01-clone"
    vmid        = 1010
    ip          = "10.83.3.5"
    cores       = 2
    memory      = 8192
    disk_size   = "30G"
    mac_address = "BC:24:21:F1:00:01"
    tags        = ["opnsense", "firewall", "fw-01"]
  },
  {
    name        = "opnsense-fw-02-clone"
    vmid        = 1011
    ip          = "10.83.3.6"
    cores       = 2
    memory      = 8192
    disk_size   = "30G"
    mac_address = "BC:24:21:F1:00:02"
    tags        = ["opnsense", "firewall", "fw-02"]
  }
]

# ============================================================================
# Talos Kubernetes Cluster Configuration
# ============================================================================
# Talos ISOs uploaded to Proxmox ISO storage
# Confirm filenames match Proxmox storage list.
talos_iso_file = "cephfs:iso/talos-1.12.1.iso" # Standard Talos ISO
#talos_gpu_iso_file = "cephfs:iso/talos-1.12.1-gpu.iso"     # GPU-enabled Talos ISO (optional)

# Primary system disk datastore id (Proxmox storage ID)
# Choices visible on node: e.g. local, local-zfs, zfs1, zfs2, zfs3
disk_storage = "CleanRoom_Storage"

# Datastore for additional data disks (if nodes define additional_disk_size)
additional_disk_storage = "CleanRoom_Storage"

# Proxmox network bridge
network_bridge = "vmbr0"

# Cluster node definitions (MACs preserved for router/DHCP reservations)
# Fields:
# - vmid: unique VM ID per Proxmox node
# - role: controlplane | worker | worker-gpu (determines Talos extensions if you template later)
# - additional_disk_size: optional extra raw disk (size in G) for data/storage layers
# NOTE: Ensure IPs match your network plan and do not conflict.

nodes = [
  # Control Plane Node - Uses standard Talos ISO
  {
    name        = "talos-CleanRoom-master-01",
    vmid        = 2000,
    role        = "controlplane",
    ip          = "10.83.3.10",
    cores       = 2,
    memory      = 8192,
    disk_size   = "30G",
    mac_address = "BC:24:21:A4:B2:97",
    tags        = ["talos", "controlplane"]
  },

  # Regular Worker Node - Uses standard Talos ISO
  {
    name                 = "talos-CleanRoom-worker-01",
    vmid                 = 3001,
    role                 = "worker",
    ip                   = "10.83.3.15",
    cores                = 2,
    memory               = 8192,
    disk_size            = "30G",
    additional_disk_size = "30G",
    mac_address          = "BC:24:21:4C:99:A2",
    tags                 = ["talos", "worker"]
  },

  # Regular Worker Node - Uses standard Talos ISO
  {
    name                 = "talos-CleanRoom-worker-02",
    vmid                 = 3002,
    role                 = "worker",
    ip                   = "10.83.3.16",
    cores                = 2,
    memory               = 8192,
    disk_size            = "30G",
    additional_disk_size = "30G",
    mac_address          = "BC:24:21:4C:99:A2",
    tags                 = ["talos", "worker"]
  },

  # Regular Worker Node - Uses standard Talos ISO
  {
    name                 = "talos-CleanRoom-worker-03",
    vmid                 = 3003,
    role                 = "worker",
    ip                   = "10.83.3.17",
    cores                = 2,
    memory               = 8192,
    disk_size            = "30G",
    additional_disk_size = "30G",
    mac_address          = "BC:24:21:4C:99:A2",
    tags                 = ["talos", "worker"]
  }

  # GPU Worker Node - Uses GPU-enabled Talos ISO (configure GPU passthrough in Proxmox UI)
  #{ 
  #  vmid = 3002, 
  #  role = "worker-gpu", 
  #  ip = "192.168.10.213", 
  #  cores = 8, 
  #  memory = 18000, 
  #  disk_size = "64G", 
  #  additional_disk_size = "112G", 
  #  mac_address = "BC:24:21:AD:82:0D", 
  #  tags = ["talos", "worker-gpu"] 
  #}
]
