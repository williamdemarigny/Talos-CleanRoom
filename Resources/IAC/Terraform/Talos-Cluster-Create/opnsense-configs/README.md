# OPNSense Installation Guide

This directory contains documentation for installing OPNSense firewall appliances deployed by Terraform.

## Overview

The Terraform configuration in this project deploys OPNSense VMs with ISO boot. **Manual installation via console is required** after VMs are created.

## Deployment Process

### What Terraform Does

When you run `terraform apply`, Terraform will:

1. ✅ Create two OPNSense VMs (VMID 1000 and 1001)
2. ✅ Attach OPNSense ISO from `cephfs:iso/OPNsense-25.7-dvd-amd64.iso`
3. ✅ Configure hardware: 2 CPU cores, 8GB RAM, 30GB disk each
4. ✅ Connect to vmbr0 network bridge with VLAN 3
5. ✅ Set MAC addresses and VM IDs as specified
6. ✅ Start the VMs
7. ⏸️ **VMs boot to OPNSense installer** - MANUAL WORK REQUIRED

### What You Must Do Manually

After Terraform deployment, you must:

1. **Access each VM console** in Proxmox UI
2. **Complete OPNSense installation** (5-10 minutes per VM)
3. **Configure network settings** during installation
4. **Reboot** after installation completes

See **[QUICK-START.md](QUICK-START.md)** for detailed step-by-step instructions.

---

## Manual Installation Steps

### For opnsense-fw-01 (VMID 1000)

#### 1. Access Console
- In Proxmox: Select VM 1000 → Click "Console"

#### 2. Login to Installer
```
Username: installer
Password: opnsense
```

#### 3. Start Installation
- Select: **"Install (UFS)"** (recommended) or **"Install (ZFS)"**
- Confirm disk: **da0**

#### 4. Configure Network
- **WAN Interface**: vtnet0
- **IP Address**: `10.83.3.5`
- **Subnet**: `24` (or 255.255.255.0)
- **Gateway**: `10.83.3.1`
- **DNS**: `8.8.8.8`, `8.8.4.4`

#### 5. Set Root Password
- Choose a secure password
- Confirm password

#### 6. Complete Installation
- Wait for files to copy (2-3 minutes)
- Select **Reboot**

#### 7. Post-Installation
- After reboot, verify VM boots from disk
- If it boots to installer again:
  - In Proxmox: VM → Hardware → CD/DVD → "Do not use any media"
  - Or: VM → Options → Boot Order → Move disk above CD-ROM
- Access web UI: `https://10.83.3.5`
- Login: `root` / (password you set)

### For opnsense-fw-02 (VMID 1001)

**Repeat the same steps** with these values:
- **IP Address**: `10.83.3.6`
- **Web UI**: `https://10.83.3.6`

---

## Network Configuration

### opnsense-fw-01
- **VMID**: 1000
- **IP Address**: 10.83.3.5/24
- **Gateway**: 10.83.3.1
- **Interface**: vtnet0 (WAN)
- **VLAN**: 3
- **MAC**: BC:24:21:F1:00:01

### opnsense-fw-02
- **VMID**: 1001
- **IP Address**: 10.83.3.6/24
- **Gateway**: 10.83.3.1
- **Interface**: vtnet0 (WAN)
- **VLAN**: 3
- **MAC**: BC:24:21:F1:00:02

---

## Post-Installation Access

### Web Interface
- **opnsense-fw-01**: https://10.83.3.5
- **opnsense-fw-02**: https://10.83.3.6
- **Default Credentials**: `root` / password you set during installation
- **Initial Setup**: Complete the setup wizard on first login

### SSH Access (if enabled)
```bash
ssh root@10.83.3.5
ssh root@10.83.3.6
```

---

## Troubleshooting

### VM Boots to Installer Every Time

**Problem**: Installation didn't complete or boot order is wrong

**Solution 1 - Remove ISO**:
```
1. Proxmox UI: Select VM → Hardware
2. Click CD/DVD Drive → Edit
3. Select "Do not use any media"
4. Reboot VM
```

**Solution 2 - Change Boot Order**:
```
1. Proxmox UI: Select VM → Options
2. Click "Boot Order" → Edit
3. Drag Hard Disk (scsi0) above CD-ROM (ide2)
4. Reboot VM
```

### Cannot Access Web UI

**Causes**:
- Installation not complete
- VM not booted from disk
- Network configuration incorrect
- VLAN 3 not configured on vmbr0

**Solutions**:
1. Check console - should see OPNSense login prompt (not installer)
2. From Proxmox node: `ping 10.83.3.5`
3. Verify VLAN 3 exists on bridge
4. Accept browser certificate warning (self-signed)

### Installation Fails

**Common Issues**:
- Insufficient disk space: Ensure 30GB available
- ISO not found: Verify `cephfs:iso/OPNsense-25.7-dvd-amd64.iso` exists
- Memory errors: 8GB should be sufficient
- Network errors: Use UFS instead of ZFS if issues occur

### Network Interface Not Detected

**Problem**: vtnet0 not showing during installation

**Solution**:
- VirtIO drivers should be included in OPNSense ISO
- If issues persist, change network model in Terraform from `virtio` to `e1000`
- Redeploy VMs after Terraform change

---

## Time Estimates

| Task | Time |
|------|------|
| Terraform deployment | 2-3 minutes |
| opnsense-fw-01 installation | 5-10 minutes |
| opnsense-fw-02 installation | 5-10 minutes |
| Post-configuration (both) | 10-15 minutes |
| **Total** | **25-40 minutes** |

---

## Security Recommendations

### Immediately After Installation

1. **Change default password** if you used `opnsense` during install
2. **Update OPNSense**:
   - System → Firmware → Check for Updates
3. **Enable SSH** (if needed):
   - System → Settings → Administration → Secure Shell
4. **Configure firewall rules** for Kubernetes cluster access
5. **Set up backups**:
   - System → Configuration → Backups

### Best Practices

- ✅ Use strong root passwords
- ✅ Keep OPNSense updated
- ✅ Configure proper firewall rules
- ✅ Enable logging and monitoring
- ✅ Regular configuration backups
- ✅ Review security advisories

---

## Integration with Talos Cluster

After both OPNSense VMs are installed and configured:

1. **Terraform continues** deploying Talos cluster VMs
2. **Configure OPNSense firewall rules** to allow:
   - Kubernetes API traffic (port 6443)
   - Internal cluster communication
   - Container registry access
3. **Set up NAT/routing** if needed for cluster egress
4. **Configure monitoring** for cluster traffic

---

## Additional Resources

- [OPNSense Documentation](https://docs.opnsense.org/)
- [OPNSense Installation Guide](https://docs.opnsense.org/manual/install.html)
- [OPNSense Initial Configuration](https://docs.opnsense.org/manual/how-tos/initial.html)
- [Proxmox VE Documentation](https://pve.proxmox.com/pve-docs/)

---

## Quick Reference

### Default Credentials
- **Installer**: `installer` / `opnsense`
- **Root**: `root` / (password set during install)
- **Web UI**: Same as root login

### Important Ports
- **HTTPS Web UI**: 443
- **SSH**: 22 (if enabled)
- **DNS**: 53 (if configured)

### Configuration Files
- **Main Config**: `/conf/config.xml`
- **Backup Location**: System → Configuration → Backups

---

## Support

For installation issues:
1. Check [Troubleshooting](#troubleshooting) section above
2. Review OPNSense logs in web UI
3. Check Proxmox console for error messages
4. Verify Terraform deployment completed successfully

For OPNSense-specific questions:
- [OPNSense Forums](https://forum.opnsense.org/)
- [OPNSense Documentation](https://docs.opnsense.org/)
