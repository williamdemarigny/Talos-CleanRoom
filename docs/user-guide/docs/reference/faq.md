# Frequently Asked Questions

## General

### What are the default credentials?
Username: `admin`, Password: `admin` for all three apps (Portal, Deployment Console, Scanning Console). Change these immediately after first login — see [Security Basics](../getting-started/security.md).

### How do I access the different apps?
Start at the Portal (`cleanroom.knowledgeondemand.net`), log in, and click the card for the app you need. You will be automatically signed in via single sign-on. See [Logging In](../getting-started/login.md).

### How long does my session last?
8 hours. After that, you will be redirected to the login page. Running scans and deployments are not affected by session expiry — they continue on the server.

## Deployment

### How long does a deployment take?
Typically **30 to 60 minutes** for a full deployment. The longest steps are VM creation, cluster bootstrapping, and application installation. See [Deployment Steps](deployment-steps.md) for timing details.

### What if a deployment step fails?
You can **Resume** (retry the failed step) or **Skip** (move to the next step). Most failures are transient network issues that resolve on retry. See [Recovery](../deployment/recovery.md).

### Can I re-deploy?
Yes. Run **Cleanup** from the Dashboard to destroy all resources, then start a fresh deployment. See [Recovery](../deployment/recovery.md).

### Do I need the kubeconfig file?
Only if you plan to use command-line tools like `kubectl`. For most users, the web interface is sufficient.

## Scanning

### How long does a scan take?

| Profile | Approximate Duration |
|---|---|
| Quick | ~5 minutes |
| Standard | ~1-2 hours |
| Thorough | ~4-14 hours |

Actual time depends on the number of targets and network conditions.

### Can I run multiple scans at once?
No. Only one vulnerability scan and one IOC scan can run at a time. Wait for the current scan to complete, then start a new one.

### Where do scan results go?
Results are stored in the **PostgreSQL database** and can be viewed in the Reports section. They are also automatically uploaded to **Faraday** for centralized vulnerability management.

### What is enrichment?
After a scan, the system looks up each vulnerability in public databases (NVD, FIRST.org) to add CVSS severity scores and EPSS exploit probability data. See [Enrichment](../scanning/enrichment.md).

### What does "uploaded to Faraday" mean?
Faraday is a vulnerability management platform. Scan results are automatically sent to Faraday so you can view all findings from all tools in one place. You can access Faraday via the link shown after scans complete.

### What target format should I use?
- Single IP: `10.83.3.10`
- IP range (CIDR): `10.83.3.0/24` (scans all 256 addresses in that block)
- Hostname: `server.example.com`
- Multiple targets: separate with commas

## Reports

### How do I export scan results?
Go to **Reports** → **Vulnerabilities**, optionally apply filters, then click **Export CSV** or **Export JSON**. See [Exporting Results](../scanning/export.md).

### How do I compare two scans?
Go to **Reports** → **Compare Scans**, select two scans, and click Compare. You will see which vulnerabilities are new, resolved, or unchanged. See [Comparing Scans](../reports/compare.md).

### What is the Audit Log for?
The Audit Log records who started scans, exported data, and triggered enrichment. It provides accountability and is useful for compliance. See [Audit Log](../reports/audit.md).
