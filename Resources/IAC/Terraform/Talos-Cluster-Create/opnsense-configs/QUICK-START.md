# OPNSense Quick Installation Guide

## Current Situation
Your OPNSense VMs (VMID 1000 and 1001) are booting to the live installer. This is **expected behavior**.

## Quick Installation Steps (5-10 minutes per VM)

### For opnsense-fw-01 (VMID 1000)

1. **Access Console** in Proxmox:
   - Select VM 1000 in Proxmox
   - Click "Console"

2. **Login to Installer**:
   ```
   Username: installer
   Password: opnsense
   ```

3. **Start Installation**:
   - You'll see the installer menu
   - Select: **"Install (UFS)"** (recommended) or **"Install (ZFS)"**
   - Press Enter

4. **Disk Selection**:
   - Select disk: **da0** (should be automatically selected)
   - Confirm: **Yes**

5. **Installation Progress**:
   - Wait 2-3 minutes for installation to complete
   - Files will be copied to disk

6. **Root Password**:
   - Set root password when prompted
   - Suggestion: Use `opnsense` initially (change later)
   - Confirm password

7. **Network Configuration**:
   - **WAN Interface**: `vtnet0` (should be auto-detected)
   - **Configuration Type**: Static
   - **IP Address**: `10.83.3.5`
   - **Subnet Mask**: `24` (or 255.255.255.0)
   - **Gateway**: `10.83.3.1`
   - **IPv6**: Configure none (or DHCP if preferred)
   - **DNS Servers**: `8.8.8.8` and `8.8.4.4`

8. **Complete Installation**:
   - Review settings
   - Confirm installation
   - Select **Reboot**

9. **Post-Reboot**:
   - VM should boot from disk
   - If it boots to installer again:
     - In Proxmox: VM 1000 → Hardware → CD/DVD Drive → Do not use any media
     - Or: VM 1000 → Options → Boot Order → Move Hard Disk above CD-ROM
   - Reboot again

10. **Verify Installation**:
    - Wait for boot to complete (1-2 minutes)
    - Access web UI: https://10.83.3.5
    - Login: `root` / password you set

---

### For opnsense-fw-02 (VMID 1001)

**Repeat the same steps** with these differences:

- **IP Address**: `10.83.3.6` (instead of 10.83.3.5)
- **Web UI**: https://10.83.3.6

---

## Post-Installation Configuration

Once both VMs are installed and running:

### 1. Access Web Interface

**opnsense-fw-01**:
```
URL: https://10.83.3.5
Username: root
Password: <password you set>
```

**opnsense-fw-02**:
```
URL: https://10.83.3.6
Username: root
Password: <password you set>
```

### 2. Initial Configuration Wizard

1. **General Information**:
   - Hostname: `opnsense-fw-01` or `opnsense-fw-02`
   - Domain: `local` (or your domain)
   - DNS Servers: `8.8.8.8`, `8.8.4.4`

2. **Time Server**:
   - Leave default or use your preferred NTP server

3. **WAN Configuration**:
   - Should already be configured from installation
   - Verify IP: 10.83.3.5 or 10.83.3.6

4. **LAN Configuration** (Optional):
   - If you add a second network interface later
   - Skip for now if only using WAN

5. **Change Password**:
   - Change from default if you used `opnsense`

6. **Reload Settings**:
   - Complete wizard
   - Settings will be applied

### 3. Enable SSH (Optional but Recommended)

1. Go to: **System → Settings → Administration**
2. Enable: **Secure Shell**
3. Check: **Login Group**: wheel
4. Check: **Permit root user login**: Yes
5. Save

Test SSH access:
```bash
ssh root@10.83.3.5
ssh root@10.83.3.6
```

---

## Troubleshooting

### VM Keeps Booting to Installer

**Solution 1 - Remove ISO**:
1. In Proxmox: Select VM → Hardware
2. Click on CD/DVD Drive
3. Click "Edit"
4. Select "Do not use any media"
5. Click "OK"
6. Reboot VM

**Solution 2 - Change Boot Order**:
1. In Proxmox: Select VM → Options
2. Click on "Boot Order"
3. Click "Edit"
4. Drag "Hard Disk (scsi0)" above "CD-ROM (ide2)"
5. Click "OK"
6. Reboot VM

### Cannot Access Web UI

1. **Check VM is running**: In Proxmox console, should see OPNSense login prompt
2. **Verify network**: From Proxmox node, try: `ping 10.83.3.5`
3. **Check VLAN**: Ensure VLAN 3 is configured on vmbr0 bridge
4. **Browser certificate**: Accept the self-signed certificate warning

### Installation Fails

- **Disk too small**: Minimum 8GB required (you have 30GB, so this shouldn't be an issue)
- **Memory error**: 8GB RAM should be sufficient
- **Try UFS instead of ZFS**: UFS is simpler and more reliable for firewalls

---

## Next Steps After Installation

1. **Configure firewall rules** for your Kubernetes cluster
2. **Set up VPN** if needed
3. **Configure additional interfaces** if you have LAN/DMZ networks
4. **Enable IDS/IPS** (Suricata) for security
5. **Set up backups** of configuration

---

## Default Credentials

⚠️ **Change these immediately after installation!**

- **Console/SSH**: root / (password you set)
- **Web UI**: root / (password you set)
- **Installer**: installer / opnsense

---

## Quick Reference

| Setting | opnsense-fw-01 | opnsense-fw-02 |
|---------|----------------|----------------|
| VMID | 1000 | 1001 |
| IP Address | 10.83.3.5/24 | 10.83.3.6/24 |
| Gateway | 10.83.3.1 | 10.83.3.1 |
| Interface | vtnet0 | vtnet0 |
| VLAN | 3 | 3 |
| MAC | BC:24:21:F1:00:01 | BC:24:21:F1:00:02 |
| Web UI | https://10.83.3.5 | https://10.83.3.6 |

---

## Time Estimate

- **Per VM**: 5-10 minutes
- **Both VMs**: 15-20 minutes total
- **Post-config**: 10-15 minutes

**Total**: ~30 minutes for complete setup

---

## Need Help?

See the full [Installation Guide](README.md) for:
- Detailed troubleshooting steps
- Security recommendations
- Integration with Talos cluster
- Additional resources and support
