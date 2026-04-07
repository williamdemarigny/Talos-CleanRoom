# Welcome to Talos CleanRoom

Talos CleanRoom is a security platform that helps you deploy infrastructure and scan networks for vulnerabilities. It consists of three web applications that work together:

- **Portal** — Your starting point. Log in here and navigate to the other apps.
- **Deployment Console** — Deploy and manage the underlying Kubernetes cluster and all security tools.
- **Scanning Console** — Run vulnerability scans, check for malware indicators, view reports, and track remediation.

## Which App Do I Need?

| I want to... | Go to... | Guide |
|---|---|---|
| Log in for the first time | **Portal** | [Logging In](getting-started/login.md) |
| Find passwords for deployed services | **Portal** → Credentials | [Viewing Credentials](getting-started/credentials.md) |
| Deploy the platform from scratch | **Deployment Console** | [Running a Deployment](deployment/running-deployment.md) |
| Check deployment status | **Deployment Console** → Dashboard | [Dashboard](deployment/dashboard.md) |
| Scan a network for vulnerabilities | **Scanning Console** → Scan | [Vulnerability Scanning](scanning/vulnerability-scan.md) |
| Check a server for malware/IOCs | **Scanning Console** → IOC Scan | [IOC Scanning](scanning/ioc-scan.md) |
| Deploy a vulnerable test target | **Scanning Console** → Target Lab | [Target Lab](scanning/target-lab.md) |
| View or export scan results | **Scanning Console** → Reports | [Reports Dashboard](reports/dashboard.md) |
| Compare two scans | **Scanning Console** → Reports → Compare | [Comparing Scans](reports/compare.md) |
| Track vulnerability remediation | **Scanning Console** → Reports → Vulnerabilities | [Remediation Tracking](scanning/remediation.md) |

## Quick Start

1. **Open the Portal** at `https://cleanroom.knowledgeondemand.net`
2. **Log in** with username `admin` and password `admin` (see [Security Basics](getting-started/security.md) to change these)
3. **Click a card** to navigate to the Deployment Console or Scanning Console — you will be logged in automatically via single sign-on

!!! tip "First time here?"
    Start with the [Prerequisites](getting-started/prerequisites.md) page to make sure you have everything you need, then follow the [Logging In](getting-started/login.md) guide.

## How This Guide Is Organized

- **[Getting Started](getting-started/prerequisites.md)** — Login, navigation, credentials, and security basics
- **[Deployment Console](deployment/dashboard.md)** — Deploying and managing the platform infrastructure
- **[Scanning](scanning/vulnerability-scan.md)** — Running vulnerability and IOC scans, Target Lab, enrichment, remediation, export
- **[Reports](reports/dashboard.md)** — Viewing scan results, comparing scans, audit trail
- **[Reference](reference/scan-profiles.md)** — Scan profiles, deployment steps, glossary, FAQ, troubleshooting
