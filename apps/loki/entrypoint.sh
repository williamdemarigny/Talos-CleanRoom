#!/bin/bash
set -e

MOUNT_POINT="/scan"
mkdir -p "$MOUNT_POINT"

echo "LOKI-RS IOC Scanner starting..."
echo "Target: ${TARGET}"
echo "Mount type: ${MOUNT_TYPE}"
echo "Scan path: ${SCAN_PATH:-/}"

# Read credentials from mounted K8s Secret (preferred) or env vars (fallback).
# Secret-based credentials avoid exposing passwords in pod spec / kubectl describe.
if [ -f /var/secrets/ioc/ssh-key ]; then
    SSH_KEY=$(cat /var/secrets/ioc/ssh-key)
fi
if [ -f /var/secrets/ioc/ssh-password ]; then
    SSH_PASSWORD=$(cat /var/secrets/ioc/ssh-password)
fi
if [ -f /var/secrets/ioc/smb-password ]; then
    SMB_PASSWORD=$(cat /var/secrets/ioc/smb-password)
fi

# Mount the remote filesystem
# NOTE: Use "if ! cmd; then" pattern (not "cmd; if [ $? -ne 0 ]") because
# set -e causes immediate exit on failed commands before $? can be checked.
if [ "$MOUNT_TYPE" = "ssh" ]; then
    echo "Mounting via SSHFS to ${SSH_USER}@${TARGET}:${SCAN_PATH:-/}..."

    if [ -n "$SSH_KEY" ]; then
        # Use SSH key authentication
        mkdir -p /root/.ssh
        echo "$SSH_KEY" > /root/.ssh/id_rsa
        chmod 600 /root/.ssh/id_rsa
        if ! sshfs "${SSH_USER}@${TARGET}:${SCAN_PATH:-/}" "$MOUNT_POINT" \
            -o IdentityFile=/root/.ssh/id_rsa,StrictHostKeyChecking=no,reconnect,allow_other; then
            echo "ERROR: SSHFS key-based mount failed. Check SSH key permissions and target accessibility."
            exit 1
        fi
    elif [ -n "$SSH_PASSWORD" ]; then
        # Use password authentication
        if ! echo "$SSH_PASSWORD" | sshfs "${SSH_USER}@${TARGET}:${SCAN_PATH:-/}" "$MOUNT_POINT" \
            -o password_stdin,StrictHostKeyChecking=no,reconnect,allow_other; then
            echo "ERROR: SSHFS password-based mount failed. Check credentials and target accessibility."
            exit 1
        fi
    else
        echo "ERROR: No SSH credentials provided. Provide SSH_KEY or SSH_PASSWORD."
        exit 1
    fi

elif [ "$MOUNT_TYPE" = "smb" ]; then
    echo "Mounting via SMB/CIFS to //${TARGET}/${SMB_SHARE}..."
    if [ -z "$SMB_USER" ] || [ -z "$SMB_PASSWORD" ]; then
        echo "ERROR: SMB username and password are required."
        exit 1
    fi
    if ! mount -t cifs "//${TARGET}/${SMB_SHARE}" "$MOUNT_POINT" \
        -o "username=${SMB_USER},password=${SMB_PASSWORD},domain=${SMB_DOMAIN:-WORKGROUP},vers=3.0"; then
        echo "ERROR: SMB/CIFS mount failed. Check credentials, share name, and target accessibility."
        exit 1
    fi
else
    echo "ERROR: Unknown mount type: $MOUNT_TYPE"
    exit 1
fi

# Verify mount succeeded
if ! mountpoint -q "$MOUNT_POINT"; then
    echo "ERROR: Failed to mount remote filesystem — mountpoint check failed"
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
