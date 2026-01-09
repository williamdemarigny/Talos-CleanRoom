# OPNSense Automated Installation Guide

This directory contains configuration files and scripts for automating OPNSense installation on Proxmox VMs.

## Problem

OPNSense ISOs boot to a live installer that requires manual interaction to complete installation. This guide provides several solutions for automated deployment.

## Solutions

### Solution 1: Manual Installation (Simplest)

**Best for**: Initial setup, learning, single deployments

1. **Deploy VMs** via Terraform:
   ```bash
   terraform apply
   ```

2. **Access VM Console** in Proxmox for each OPNSense VM (VMID 1000, 1001)

3. **Complete Installation**:
   - Login: `installer` / `opnsense`
   - Select: **Install (UFS)** or **Install (ZFS)**
   - Choose disk: `da0` (default)
   - Set root password
   - Configure network:
     - **opnsense-fw-01**: WAN = `vtnet0` with IP `10.83.3.5/24`
     - **opnsense-fw-02**: WAN = `vtnet0` with IP `10.83.3.6/24`
     - Gateway: `10.83.3.1`
   - Complete installation and reboot

4. **Post-Installation**:
   - Remove ISO or change boot order in Proxmox
   - Access web UI: `https://10.83.3.5` or `https://10.83.3.6`
   - Default credentials: `root` / `opnsense`

---

### Solution 2: Pre-Built Template (Most Automated)

**Best for**: Production, repeated deployments, CI/CD

#### Step 1: Create OPNSense Template

1. **Manually install OPNSense once** (follow Solution 1)

2. **Configure the installed VM**:
   ```bash
   # SSH into the OPNSense VM
   ssh root@10.83.3.5

   # Install qemu-guest-agent
   pkg install qemu-guest-agent
   sysrc qemu_guest_agent_enable="YES"
   service qemu-guest-agent start

   # Remove machine-specific data
   rm -f /conf/config.xml
   rm -f /etc/ssh/ssh_host_*
   rm -rf /var/log/*
   history -c
   ```

3. **In Proxmox**:
   - Shutdown the VM
   - Right-click VM → "Convert to Template"
   - Name it: `opnsense-template`

#### Step 2: Update Terraform to Clone from Template

Modify `main.tf` to use `clone` instead of ISO:

```hcl
resource "proxmox_virtual_environment_vm" "opnsense" {
  # ... existing configuration ...

  # Remove cdrom block
  # cdrom { ... }

  # Add clone block instead
  clone {
    vm_id = 9000  # Your template VMID
    full  = true
  }

  # Add cloud-init for customization
  initialization {
    ip_config {
      ipv4 {
        address = "${each.value.ip}/24"
        gateway = "10.83.3.1"
      }
    }

    user_account {
      username = "root"
      password = var.opnsense_root_password
    }

    dns {
      servers = ["8.8.8.8", "8.8.4.4"]
    }
  }
}
```

---

### Solution 3: Custom ISO with Installer Config (Advanced)

**Best for**: Fully automated deployments, no template needed

#### Create Custom ISO

1. **Download OPNSense ISO**:
   ```bash
   wget https://mirror.ams1.nl.leaseweb.net/opnsense/releases/25.7/OPNsense-25.7-dvd-amd64.iso
   ```

2. **Extract ISO**:
   ```bash
   mkdir /tmp/opnsense-iso
   mount -o loop OPNsense-25.7-dvd-amd64.iso /tmp/opnsense-iso
   mkdir /tmp/opnsense-custom
   cp -r /tmp/opnsense-iso/* /tmp/opnsense-custom/
   umount /tmp/opnsense-iso
   ```

3. **Add installer config**:
   ```bash
   # Copy the installerconfig file to the ISO root
   cp installerconfig-fw-01 /tmp/opnsense-custom/installerconfig

   # Make it executable
   chmod +x /tmp/opnsense-custom/installerconfig
   ```

4. **Rebuild ISO**:
   ```bash
   mkisofs -o OPNsense-25.7-custom-amd64.iso \
     -b boot/cdboot -no-emul-boot \
     -r -J -V "OPNsense" \
     /tmp/opnsense-custom
   ```

5. **Upload to Proxmox**:
   ```bash
   scp OPNsense-25.7-custom-amd64.iso root@proxmox:/var/lib/vz/template/iso/
   ```

6. **Update cluster.auto.tfvars**:
   ```hcl
   opnsense_iso_file = "local:iso/OPNsense-25.7-custom-amd64.iso"
   ```

---

### Solution 4: Ansible Post-Deployment Configuration

**Best for**: Configuration management, ongoing updates

Use Ansible to configure OPNSense after manual installation.

---

## Configuration Files Included

- **`installerconfig-fw-01`**: Automated install config for first firewall
- **`installerconfig-fw-02`**: Automated install config for second firewall
- **`auto-install.sh`**: Generic installation script
- **`install-config.conf`**: Installation parameters

## Network Configuration

### opnsense-fw-01
- **VMID**: 1000
- **WAN IP**: 10.83.3.5/24
- **Gateway**: 10.83.3.1
- **MAC**: BC:24:21:F1:00:01
- **Interface**: vtnet0

### opnsense-fw-02
- **VMID**: 1001
- **WAN IP**: 10.83.3.6/24
- **Gateway**: 10.83.3.1
- **MAC**: BC:24:21:F1:00:02
- **Interface**: vtnet0

## Post-Installation Access

### Web UI
- **opnsense-fw-01**: https://10.83.3.5
- **opnsense-fw-02**: https://10.83.3.6
- **Default User**: root
- **Default Pass**: opnsense (change immediately!)

### SSH Access
```bash
ssh root@10.83.3.5
ssh root@10.83.3.6
```

## Recommended Approach

**For your use case**, I recommend:

1. **Immediate**: Use **Solution 1 (Manual Installation)**
   - Takes 5-10 minutes per VM
   - Most reliable
   - Complete control

2. **Long-term**: Use **Solution 2 (Template-based)**
   - Create template from first manual install
   - All future deployments are automated
   - Consistent configuration

## Troubleshooting

### VM boots to installer every time
- Installation didn't complete successfully
- Boot order still set to ISO first
- Change boot order in Proxmox: VM → Options → Boot Order → Move disk above cdrom

### Cannot access web UI
- OPNSense interface may be on different network
- Check console for actual IP assignment
- Ensure VLAN 3 is configured on network bridge

### Network interface not detected
- VirtIO driver may not be loaded
- Use E1000 instead of VirtIO in Terraform
- Or use FreeBSD virtio drivers

### Installation fails with disk errors
- Disk may be too small (minimum 8GB recommended)
- Try UFS instead of ZFS
- Check Proxmox storage availability

## Security Notes

⚠️ **Important**: The default password in these configs is `opnsense`. Change immediately after installation!

```bash
# After first login
passwd root
```

## Additional Resources

- [OPNSense Installation Guide](https://docs.opnsense.org/manual/install.html)
- [OPNSense Hardware Setup](https://docs.opnsense.org/manual/hardware.html)
- [Proxmox Cloud-Init](https://pve.proxmox.com/wiki/Cloud-Init_Support)
