# Navigating the Platform

Talos CleanRoom is split into three web applications, each with its own navigation bar and purpose.

## The Three Apps

### Portal
Your starting point. The Portal has two cards that take you to the other apps:

- **Deployment Console** (cyan card) — for deploying and managing infrastructure
- **Scanning Console** (green card) — for running security scans and viewing reports

The Portal also has a **Credentials** page (accessible from the top navigation) where you can view passwords for all deployed services.

### Deployment Console
The Deployment Console has four main sections, accessible from the navigation bar:

| Tab | Purpose |
|---|---|
| **Dashboard** | Overview of deployment status, dependencies, and service credentials |
| **Configuration** | View and edit cluster configuration settings |
| **Deployment** | Start, monitor, and manage the 23-step deployment process |
| **Logs** | Search and filter deployment log entries |

### Scanning Console
The Scanning Console has four main sections:

| Tab | Purpose |
|---|---|
| **Scan** | Run vulnerability scans using Nmap, OpenVAS, and Metasploit |
| **IOC Scan** | Scan file systems for malware indicators (Indicators of Compromise) |
| **Target Lab** | Deploy Vulhub vulnerable environments for scan testing and validation |
| **Reports** | View scan results, compare scans, browse vulnerabilities, and export data |

## Switching Between Apps

- From any app, you can return to the Portal by navigating to `https://cleanroom.knowledgeondemand.net`
- From the Portal, click either card to jump to the Deployment Console or Scanning Console with automatic sign-on

## Logging Out

Click **Logout** in the top-right corner of any app's navigation bar. This ends your session for that app only. If you used single sign-on from the Portal, you may still be logged in to the Portal itself.

!!! note "Session duration"
    Your login session lasts **8 hours**. After that, you will be redirected to the login page and need to sign in again. See [Security Basics](security.md) for more details.

## What's Next?

- [Viewing Credentials](credentials.md) — find passwords for deployed services
- [Dashboard](../deployment/dashboard.md) — check deployment status
- [Vulnerability Scanning](../scanning/vulnerability-scan.md) — run your first scan
