#!/usr/bin/env bash
# =============================================================================
# Prepare Metasploitable3 VM Templates on Proxmox
# =============================================================================
#
# This script downloads pre-built Metasploitable3 Vagrant boxes from Rapid7,
# converts them from VMDK to QCOW2, and creates Proxmox VM templates that
# the Scanning Console's Target Lab feature can clone on demand.
#
# Prerequisites:
#   - Run on a Proxmox node (has qm, qemu-img, curl)
#   - ~10 GB free in /tmp for downloads + conversion
#   - Storage "local-lvm" available (adjust STORAGE if different)
#
# Usage:
#   ssh root@<proxmox-node>
#   bash prepare-metasploitable3-templates.sh [--ubuntu-only | --windows-only]
#
# Template VMIDs:
#   4000 — Metasploitable3 Ubuntu 14.04
#   4001 — Metasploitable3 Windows Server 2008 R2
#
# After running this script, the Target Lab feature in the Scanning Console
# can clone these templates to deploy target VMs for vulnerability scanning.
# =============================================================================

set -euo pipefail

# --- Configuration ---
STORAGE="local-lvm"
BRIDGE="vmbr0"
VLAN_TAG=3
WORK_DIR="/tmp/metasploitable3-prep"

UBUNTU_VMID=4000
UBUNTU_NAME="metasploitable3-ubuntu"
UBUNTU_BOX_URL="https://app.vagrantup.com/rapid7/boxes/metasploitable3-ub1404/versions/0.1.12-weekly/providers/virtualbox/amd64/vagrant.box"

WINDOWS_VMID=4001
WINDOWS_NAME="metasploitable3-windows"
WINDOWS_BOX_URL="https://app.vagrantup.com/rapid7/boxes/metasploitable3-win2k8/versions/0.1.0-weekly/providers/virtualbox/amd64/vagrant.box"

# --- Logging ---
log()  { echo "[$(date '+%H:%M:%S')] $*"; }
die()  { echo "[ERROR] $*" >&2; exit 1; }

# --- Prerequisite checks ---
for cmd in qm qemu-img curl tar; do
    command -v "$cmd" >/dev/null || die "Required command not found: $cmd"
done

# --- Parse arguments ---
DO_UBUNTU=true
DO_WINDOWS=true
case "${1:-}" in
    --ubuntu-only)  DO_WINDOWS=false ;;
    --windows-only) DO_UBUNTU=false ;;
    --help|-h)
        echo "Usage: $0 [--ubuntu-only | --windows-only]"
        exit 0
        ;;
esac

mkdir -p "$WORK_DIR"

# =============================================================================
# Helper: Download box, extract VMDK, convert to QCOW2, create template
# =============================================================================
prepare_template() {
    local vmid="$1"
    local name="$2"
    local box_url="$3"
    local os_type="$4"    # l26 for Linux, win7 for Windows
    local memory="$5"

    log "=== Preparing $name (VMID $vmid) ==="

    # Check if template already exists
    if qm status "$vmid" &>/dev/null; then
        log "VMID $vmid already exists. Skipping (delete with 'qm destroy $vmid' to rebuild)."
        return 0
    fi

    local box_file="$WORK_DIR/${name}.box"

    # Step 1: Download Vagrant box
    if [[ -f "$box_file" ]]; then
        # Validate existing file is a valid archive before reusing
        if tar tf "$box_file" &>/dev/null; then
            log "Box file already downloaded and valid, reusing: $box_file"
        else
            log "Existing box file is corrupt, re-downloading..."
            rm -f "$box_file"
            curl -L --progress-bar --fail -o "$box_file" "$box_url" || die "Download failed for $box_url"
        fi
    else
        log "Downloading Vagrant box (~1-5 GB)..."
        curl -L --progress-bar --fail -o "$box_file" "$box_url" || die "Download failed for $box_url"
    fi

    # Step 2: Extract VMDK from box (it's a tar.gz)
    log "Extracting VMDK from box file..."
    local extract_dir="$WORK_DIR/${name}-extract"
    mkdir -p "$extract_dir"
    tar xf "$box_file" -C "$extract_dir"

    # Find the VMDK file (name varies between boxes)
    local vmdk_file
    vmdk_file=$(find "$extract_dir" -name '*.vmdk' -type f | head -1)
    [[ -n "$vmdk_file" ]] || die "No VMDK file found in box archive"
    log "Found VMDK: $(basename "$vmdk_file")"

    # Step 3: Convert VMDK to QCOW2
    local qcow2_file="$WORK_DIR/${name}.qcow2"
    log "Converting VMDK to QCOW2 (this takes a few minutes)..."
    qemu-img convert -f vmdk -O qcow2 "$vmdk_file" "$qcow2_file"
    log "QCOW2 size: $(du -h "$qcow2_file" | cut -f1)"

    # Step 4: Create VM shell
    log "Creating VM $vmid ($name)..."
    qm create "$vmid" \
        --name "$name" \
        --memory "$memory" \
        --cores 2 \
        --net0 "e1000,bridge=${BRIDGE},tag=${VLAN_TAG}" \
        --ostype "$os_type" \
        --agent 1 \
        --scsihw virtio-scsi-single \
        --boot "order=scsi0" \
        --description "Metasploitable3 target VM template. Credentials: vagrant/vagrant"

    # Step 5: Import disk
    log "Importing disk to $STORAGE..."
    qm importdisk "$vmid" "$qcow2_file" "$STORAGE"
    qm set "$vmid" --scsi0 "${STORAGE}:vm-${vmid}-disk-0"

    # Step 6: Add cloud-init drive (Linux only — for IP assignment on clone)
    if [[ "$os_type" == "l26" ]]; then
        log "Adding cloud-init drive..."
        qm set "$vmid" --ide2 "${STORAGE}:cloudinit"
        qm set "$vmid" --serial0 socket --vga serial0
    fi

    # Step 7: Convert to template
    log "Converting to template..."
    qm template "$vmid"

    # Step 8: Cleanup extracted files (keep .box for potential re-use)
    rm -rf "$extract_dir" "$qcow2_file"

    log "Template $vmid ($name) created successfully."
}

# =============================================================================
# Prepare templates
# =============================================================================

if $DO_UBUNTU; then
    prepare_template "$UBUNTU_VMID" "$UBUNTU_NAME" "$UBUNTU_BOX_URL" "l26" 4096
    echo ""
    log "NOTE: For best results, start the Ubuntu template temporarily to install"
    log "      qemu-guest-agent (required for automatic IP detection):"
    log ""
    log "        qm set $UBUNTU_VMID --template 0     # un-template"
    log "        qm start $UBUNTU_VMID"
    log "        # Wait ~60s, then SSH in (vagrant/vagrant at DHCP IP):"
    log "        #   sudo apt-get update && sudo apt-get install -y qemu-guest-agent"
    log "        #   sudo systemctl enable qemu-guest-agent"
    log "        #   sudo shutdown -h now"
    log "        qm template $UBUNTU_VMID              # re-template"
    echo ""
fi

if $DO_WINDOWS; then
    prepare_template "$WINDOWS_VMID" "$WINDOWS_NAME" "$WINDOWS_BOX_URL" "win7" 4096
    echo ""
    log "NOTE: Windows 2008 R2 does not support cloud-init."
    log "      The Target Lab assigns a fixed IP (10.83.3.169) and limits"
    log "      Windows to 1 concurrent instance."
    echo ""
fi

# =============================================================================
# Summary
# =============================================================================
log "=== Template Preparation Complete ==="
log ""
log "Verify with:  qm list | grep -E '${UBUNTU_VMID}|${WINDOWS_VMID}'"
log ""
log "The Scanning Console's Target Lab can now clone these templates"
log "to deploy target VMs for vulnerability scanning."

# Cleanup work directory if empty
rmdir "$WORK_DIR" 2>/dev/null || true
