# After Deployment

Once the deployment completes successfully, all security tools and infrastructure are running. Here is what you can do next.

## Downloading the Kubeconfig

The kubeconfig file gives command-line access to the Kubernetes cluster. To download it:

1. Go to the **Dashboard**
2. Click **Download Kubeconfig**
3. Save the file to your computer

!!! note "Who needs this?"
    Most users will not need the kubeconfig file. It is primarily for administrators who want to use `kubectl` commands directly. If you are only using the web interface, you can skip this.

## Accessing Deployed Services

The Dashboard shows all deployed services with clickable URLs:

| Service | URL | What It Does |
|---|---|---|
| **ArgoCD** | `https://argocd.knowledgeondemand.net` | GitOps manager — shows the health of all Kubernetes applications |
| **Harbor** | `https://harbor.knowledgeondemand.net` | Container registry — stores Docker images used by the platform |
| **OpenVAS** | `https://openvas.knowledgeondemand.net` | Vulnerability scanner engine (also accessible through the Scanning Console) |
| **Faraday** | `https://faraday.knowledgeondemand.net` | Vulnerability management — aggregates all scan findings in one place |
| **Threat Dragon** | `https://threatdragon.knowledgeondemand.net` | Threat modeling tool for documenting security architecture |

Use the credentials shown on the Dashboard (or the [Portal Credentials page](../getting-started/credentials.md)) to log in to each service.

## What is Faraday?

Faraday is a vulnerability management platform. When you run scans through the Scanning Console, the results are automatically uploaded to Faraday. You can use Faraday to:

- View all vulnerabilities from all scan tools in one place
- Track remediation progress
- Generate compliance reports

You will see "Open Faraday" links throughout the Scanning Console after scans complete.

## Re-deploying

If you need to start fresh (e.g., after a configuration change), you can:

1. Run **Cleanup** from the Dashboard (see [Recovery](recovery.md))
2. Wait for cleanup to complete
3. Start a new deployment

## What's Next?

- [Vulnerability Scanning](../scanning/vulnerability-scan.md) — run your first security scan
- [Viewing Credentials](../getting-started/credentials.md) — find passwords for all services
- [Reports Dashboard](../reports/dashboard.md) — view scan results
