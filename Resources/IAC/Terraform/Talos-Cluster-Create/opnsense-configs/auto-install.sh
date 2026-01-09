#!/bin/sh
#
# OPNSense Automated Installation Script
# This script performs an unattended installation of OPNSense
#
# Usage: Place this on a config drive or inject via cloud-init
#

set -e

# Source configuration
. /root/install-config.conf

echo "=== OPNSense Automated Installation ==="
echo "Installation Type: $INSTALL_TYPE"
echo "Target Disk: $INSTALL_DISK"
echo "Hostname: $HOSTNAME"

# Wait for disk to be available
sleep 5

# Partition and format disk
if [ "$INSTALL_TYPE" = "ufs" ]; then
    echo "Installing with UFS..."

    # Destroy any existing partition scheme
    gpart destroy -F $INSTALL_DISK || true

    # Create GPT partition scheme
    gpart create -s gpt $INSTALL_DISK

    # Create boot partition (512K)
    gpart add -t freebsd-boot -s 512K $INSTALL_DISK

    # Create swap partition (2GB)
    gpart add -t freebsd-swap -s 2G -l swap0 $INSTALL_DISK

    # Create root partition (rest of disk)
    gpart add -t freebsd-ufs -l root0 $INSTALL_DISK

    # Install bootcode
    gpart bootcode -b /boot/pmbr -p /boot/gptboot -i 1 $INSTALL_DISK

    # Format root partition
    newfs -U /dev/gpt/root0

    # Mount root partition
    mount /dev/gpt/root0 /mnt

elif [ "$INSTALL_TYPE" = "zfs" ]; then
    echo "Installing with ZFS..."

    # Destroy any existing partition scheme
    gpart destroy -F $INSTALL_DISK || true

    # Create GPT partition scheme
    gpart create -s gpt $INSTALL_DISK

    # Create boot partition
    gpart add -t freebsd-boot -s 512K $INSTALL_DISK
    gpart bootcode -b /boot/pmbr -p /boot/gptzfsboot -i 1 $INSTALL_DISK

    # Create swap partition
    gpart add -t freebsd-swap -s 2G -l swap0 $INSTALL_DISK

    # Create ZFS partition
    gpart add -t freebsd-zfs -l disk0 $INSTALL_DISK

    # Create ZFS pool
    zpool create -f -o altroot=/mnt -o cachefile=/tmp/zpool.cache zroot /dev/gpt/disk0

    # Create ZFS datasets
    zfs create -o compression=lz4 -o atime=off zroot/ROOT
    zfs create -o mountpoint=/ zroot/ROOT/default
    zfs create -o mountpoint=/tmp -o exec=on -o setuid=off zroot/tmp
    zfs create -o mountpoint=/usr -o canmount=off zroot/usr
    zfs create zroot/usr/home
    zfs create -o setuid=off zroot/usr/ports
    zfs create zroot/usr/src
    zfs create -o mountpoint=/var -o canmount=off zroot/var
    zfs create -o exec=off -o setuid=off zroot/var/audit
    zfs create -o exec=off -o setuid=off zroot/var/crash
    zfs create -o exec=off -o setuid=off zroot/var/log
    zfs create -o atime=on zroot/var/mail
    zfs create -o setuid=off zroot/var/tmp

    # Set bootfs
    zpool set bootfs=zroot/ROOT/default zroot

    # Export and import pool
    zpool export zroot
    zpool import -o altroot=/mnt -o cachefile=/tmp/zpool.cache zroot
fi

# Copy OPNSense system files
echo "Copying OPNSense system files..."
cd /mnt
tar -xpf /usr/local/opnsense/base.txz
tar -xpf /usr/local/opnsense/kernel.txz

# Configure system
echo "Configuring system..."

# Set hostname
echo "hostname=\"$HOSTNAME.$DOMAIN\"" > /mnt/etc/rc.conf.local

# Enable necessary services
cat >> /mnt/etc/rc.conf.local << EOF
sshd_enable="YES"
sendmail_enable="NONE"
ifconfig_${WAN_INTERFACE}="inet $WAN_IP netmask 255.255.255.0"
defaultrouter="$WAN_GATEWAY"
EOF

# Configure DNS
cat > /mnt/etc/resolv.conf << EOF
nameserver $DNS_PRIMARY
nameserver $DNS_SECONDARY
EOF

# Set root password
echo "Setting root password..."
echo "$ROOT_PASSWORD" | pw -V /mnt/etc usermod root -h 0

# Enable SSH
echo "PermitRootLogin yes" >> /mnt/etc/ssh/sshd_config

# Set timezone
cp /usr/share/zoneinfo/$TIMEZONE /mnt/etc/localtime

# Create fstab for UFS
if [ "$INSTALL_TYPE" = "ufs" ]; then
    cat > /mnt/etc/fstab << EOF
# Device        Mountpoint      FStype  Options Dump    Pass#
/dev/gpt/root0  /               ufs     rw      1       1
/dev/gpt/swap0  none            swap    sw      0       0
EOF
fi

# Copy ZFS cache for ZFS installs
if [ "$INSTALL_TYPE" = "zfs" ]; then
    cp /tmp/zpool.cache /mnt/boot/zfs/zpool.cache
fi

# Unmount
cd /
umount /mnt

echo "=== Installation Complete ==="

if [ "$AUTO_REBOOT" = "YES" ]; then
    echo "Rebooting in 5 seconds..."
    sleep 5
    reboot
else
    echo "Installation complete. Please reboot manually."
fi
