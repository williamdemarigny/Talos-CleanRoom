# Security Basics

!!! danger "Change default passwords immediately"
    All Talos CleanRoom applications ship with the default username **admin** and password **admin**. Change these as soon as possible after your first login.

## Default Credentials

| Service | Default Username | Default Password |
|---|---|---|
| Portal | admin | admin |
| Deployment Console | admin | admin |
| Scanning Console | admin | admin |
| ArgoCD | admin | admin |
| Harbor | admin | Harbor12345 |
| OpenVAS | admin | admin |

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
