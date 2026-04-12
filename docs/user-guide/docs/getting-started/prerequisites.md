# Prerequisites

Before using Talos CleanRoom, make sure you have the following:

## What You Need

| Requirement | Details |
|---|---|
| **Web browser** | Any modern browser: Chrome, Firefox, Edge, or Safari. WebSocket support is required for real-time updates (all modern browsers support this). |
| **Network access** | Your computer must be able to reach `*.knowledgeondemand.net` and the Deployment Console at `10.83.3.190:8000`. If you are on a VPN or restricted network, check with your network administrator. |
| **Platform deployed** | The Talos CleanRoom platform must already be deployed and running. If you see connection errors, the platform may not be set up yet — contact your infrastructure team. |

## For Vulnerability Scanning

- You need the IP address or address range (called a [CIDR range](../reference/glossary.md#cidr)) of the systems you want to scan
- The target systems must be network-reachable from the Kubernetes cluster (not from your browser)

## For IOC Scanning

- You need SSH or SMB/Windows file sharing credentials for the target system
- The target system must be reachable from the Kubernetes cluster

## What's Next?

Ready to get started? Head to [Logging In](login.md) to access the platform.
