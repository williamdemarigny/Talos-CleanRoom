#!/bin/bash
set -e

MOUNT_POINT="/scan"
mkdir -p "$MOUNT_POINT"

echo "LOKI-RS IOC Scanner starting..."
echo "Target: ${TARGET}"
echo "Mount type: ${MOUNT_TYPE}"
echo "Scan path: ${SCAN_PATH:-/}"

# Mount the remote filesystem
if [ "$MOUNT_TYPE" = "ssh" ]; then
    echo "Mounting via SSHFS..."

    if [ -n "$SSH_KEY" ]; then
        # Use SSH key authentication
        mkdir -p /root/.ssh
        echo "$SSH_KEY" > /root/.ssh/id_rsa
        chmod 600 /root/.ssh/id_rsa
        sshfs "${SSH_USER}@${TARGET}:${SCAN_PATH:-/}" "$MOUNT_POINT" \
            -o IdentityFile=/root/.ssh/id_rsa,StrictHostKeyChecking=no,reconnect,allow_other
    else
        # Use password authentication
        echo "$SSH_PASSWORD" | sshfs "${SSH_USER}@${TARGET}:${SCAN_PATH:-/}" "$MOUNT_POINT" \
            -o password_stdin,StrictHostKeyChecking=no,reconnect,allow_other
    fi

elif [ "$MOUNT_TYPE" = "smb" ]; then
    echo "Mounting via SMB/CIFS..."
    mount -t cifs "//${TARGET}/${SMB_SHARE}" "$MOUNT_POINT" \
        -o "username=${SMB_USER},password=${SMB_PASSWORD},domain=${SMB_DOMAIN:-WORKGROUP},vers=3.0"
else
    echo "ERROR: Unknown mount type: $MOUNT_TYPE"
    exit 1
fi

# Verify mount succeeded
if ! mountpoint -q "$MOUNT_POINT"; then
    echo "ERROR: Failed to mount remote filesystem"
    exit 1
fi

echo "Remote filesystem mounted successfully at $MOUNT_POINT"

# Build LOKI-RS arguments
LOKI_ARGS="-f $MOUNT_POINT --no-procs --jsonl /dev/stdout --no-html"

if [ -n "$MAX_FILE_SIZE" ]; then
    LOKI_ARGS="$LOKI_ARGS -m $MAX_FILE_SIZE"
fi

if [ "$NO_ARCHIVE" = "1" ]; then
    LOKI_ARGS="$LOKI_ARGS --no-archive"
fi

echo "Running: ./loki $LOKI_ARGS"
echo "---"

# Run LOKI-RS (JSONL output goes to stdout for kubectl logs capture)
exec ./loki $LOKI_ARGS
