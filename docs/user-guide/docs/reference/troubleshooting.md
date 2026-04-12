# Troubleshooting

Common errors and how to resolve them.

## Deployment Console

### "Deployment already in progress"
**Cause:** You tried to start a deployment while one is already running.
**Fix:** Wait for the current deployment to finish, or click **Abort** to stop it first.

### Deployment step fails repeatedly
**Cause:** Usually a transient network issue, but could indicate a configuration problem.
**Fix:**

1. Check the error message shown on the failed step (click to expand)
2. Try **Resume** first — many failures resolve on retry
3. If the same step fails 2-3 times, check the [Deployment Steps](deployment-steps.md) reference for that specific step's common causes
4. As a last resort, **Skip** the step (but understand what it does before skipping)

### Cannot download kubeconfig
**Cause:** Kubeconfig is only available after a successful deployment.
**Fix:** Complete a deployment first, then the Download Kubeconfig button will become active.

## Scanning Console

### "A scan is already in progress"
**Cause:** Only one vulnerability scan (or one IOC scan) can run at a time.
**Fix:** Wait for the current scan to complete or abort it.

### "Invalid target" error
**Cause:** The target you entered is not a valid IP address, CIDR range, or hostname.
**Fix:** Check the format:

- Valid: `10.83.3.10`, `10.83.3.0/24`, `server.example.com`
- Invalid: `10.83.3`, `http://10.83.3.10`, `10.83.3.0/33`

### Scan seems stuck
**Cause:** Some scans (especially OpenVAS Thorough) can take many hours.
**Fix:**

- Check the elapsed time — Thorough scans can run for 14+ hours
- Check the log stream for activity — if logs are still appearing, the scan is working
- Each tool has a maximum timeout; it will stop automatically if it exceeds the limit

### IOC scan mount failure
**Cause:** Cannot connect to the target via SSH or SMB.
**Fix:**

- Verify the target IP is correct and reachable from the cluster
- Double-check username/password
- For SSH: ensure the SSH service is running on the target
- For SMB: verify the share name is correct (e.g., `C$` for the C drive)

## General

### Page shows "Connecting..." or "Connection lost"

**Cause:** The WebSocket connection to the server dropped.
**Fix:**

- The page will automatically attempt to reconnect
- If it persists, refresh the page
- Check that you have network access to the server

### Redirected to login page unexpectedly

**Cause:** Your session has expired (sessions last 8 hours).
**Fix:** Log in again. Any running scans or deployments are not affected.

### "Rate limit exceeded" error

The Scanning Console has rate limits to prevent abuse:

| Action | Limit |
|---|---|
| Login attempts | 5 per minute per IP |
| Scan starts | 10 per minute per user |
| Enrichment triggers | 2 per hour per user |
| Export requests | 20 per minute per user |

**Fix:** Wait a moment and try again. If you are hitting the scan start limit, you may be starting and aborting scans too frequently.

### Browser shows security certificate warning

**Cause:** Your browser does not trust the TLS certificate.
**Fix:**

- For `*.knowledgeondemand.net` URLs: certificates are issued by Let's Encrypt and should be trusted automatically
- For `10.83.3.190:8000` (Deployment Console): this uses a self-signed certificate; you can safely proceed past the warning
