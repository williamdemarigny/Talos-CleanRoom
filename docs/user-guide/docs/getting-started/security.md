# Security Basics

## Default Credentials

Only the **Portal** and **Deployment Console** use the default credentials:

| Service | Default Username | Default Password |
|---|---|---|
| Portal | admin | admin |
| Deployment Console | admin | admin |

All other services (Scanning Console, ArgoCD, Harbor, OpenVAS, Faraday, Threat Dragon) receive **auto-generated passwords** during deployment. You can find these passwords in two places:

- **Portal** — click **Credentials** in the top navigation bar to see all service passwords. See [Viewing Credentials](credentials.md) for details.
- **Deployment Console** — the **Dashboard** page shows service credentials in the "Deployed Services" section at the bottom.

!!! warning "Change default passwords"
    The Portal and Deployment Console both ship with **admin / admin**. Consider changing these after your first login.

## Session Duration

Your login session lasts **8 hours**. After that:

- You will be automatically redirected to the login page
- Any page you are viewing will prompt you to log in again
- Work in progress (running scans, active deployments) is **not affected** — they continue running on the server regardless of your session status

## Single Sign-On Behavior

When you click a card on the Portal to navigate to another app:

- A one-time authentication code is generated (valid for 60 seconds)
- You are redirected to the target app and logged in automatically
- If the code expires before the redirect completes, you will see the login page — simply go back to the Portal and click again

## What's Next?

- [Logging In](login.md) — how to access the platform
- [Dashboard](../deployment/dashboard.md) — get started with the Deployment Console
- [Vulnerability Scanning](../scanning/vulnerability-scan.md) — run your first security scan
