# Talos CleanRoom -- Capstone Presentation Speaker Notes

**Presenter:** William de Marigny | St. Mary's University | Spring 2026
**Total duration:** ~25 minutes (11:30 slides + 13:00 live demo)
**Structure:** Interspersed -- slides alternate with live demo sections

---

## Pre-Presentation Checklist

- [ ] Open browser tabs (pre-logged in):
  - Tab 1: `https://cleanroom.knowledgeondemand.net` (Portal -- logged OUT for demo)
  - Tab 2: `https://cleanroom.knowledgeondemand.net` (Portal -- logged IN as backup)
  - Tab 3: Deployment Console dashboard (pre-loaded)
  - Tab 4: Scanning Console (pre-loaded)
- [ ] Pre-stage a completed vulnerability scan so the Reports dashboard has real data
- [ ] Deploy a Vulhub target in the Target Lab (if showing that feature)
- [ ] Set browser zoom to 125-150% so the audience can read the UI
- [ ] Have the fallback screenshot folder open: `docs/user-guide/docs/img/`
- [ ] Have the fallback videos ready: `docs/user-guide/docs/videos/`
- [ ] Test the projector/screen connection
- [ ] Close unnecessary apps to avoid notification pop-ups

---

## Slide-by-Slide Guide

### Slide 1: Title Slide (0:30)

**On screen:** "Talos CleanRoom: An Infrastructure-as-Code Security Platform on Kubernetes"

**Say:**
> "Good [morning/afternoon]. I'm William de Marigny and today I'll present Talos CleanRoom -- a platform I built from scratch that deploys a full Kubernetes cluster and an integrated security toolchain with a single click, then lets you scan your network for vulnerabilities and malware -- all managed through GitOps."

> "I'll alternate between slides and live demos so you can see the real system in action."

**Timing target:** 0:30

---

### Slide 2: The Problem (1:00)

**On screen:** 6 bullet points about security toolchain complexity

**Say:**
> "If you wanted to stand up a professional vulnerability management environment from scratch, you'd need to install and configure at least 4 separate security tools -- OpenVAS for vulnerability detection, Metasploit for exploit verification, Faraday for aggregating results, and something like LOKI for malware scanning."

> "Then you need a Kubernetes cluster to run all of this, which means Terraform, networking, storage, TLS certificates, ingress routing, GitOps..."

> "There's no turnkey solution that does all of this as Infrastructure-as-Code with a web interface. Security teams spend more time fighting infrastructure than finding vulnerabilities. That's the gap this project fills."

**Timing target:** 1:00

---

### Slide 3: The Solution (1:30)

**On screen:** Two columns -- "What It Does" (left) and "Key Numbers" (right)

**Say:**
> "The platform does two major things. First, it deploys your entire infrastructure with one click -- Terraform creates VMs on Proxmox, Talos Linux bootstraps Kubernetes, and ArgoCD deploys all the security tools automatically."

> "Second, it gives you a unified interface to scan, analyze, and track vulnerabilities across Nmap, OpenVAS, Metasploit, and LOKI-RS."

> [Point to right column] "Some key numbers: 434 commits in about 3 and a half months. The deployment pipeline has 23 automated steps. There are 3 web applications connected by single sign-on. And the entire platform state is managed in Git."

**Timing target:** 1:30

---

### Slide 4: Architecture Diagram (1:30)

**On screen:** Programmatic architecture diagram showing Proxmox -> K8s -> Apps -> LXC

**Say:**
> [Point top-down] "The foundation is a 4-node Proxmox cluster. On top of that, Terraform creates 4 VMs that become a Talos Linux Kubernetes cluster -- one control plane node and three workers."

> "Inside the cluster, ArgoCD manages everything via GitOps. The infrastructure layer handles load balancing with MetalLB, TLS certificates with cert-manager, and ingress routing with Traefik."

> "The security layer runs OpenVAS, Metasploit, Faraday, and a private Harbor container registry."

> "The application layer has the Scanning Console, the Portal for SSO, and a PostgreSQL database."

> [Point to bottom] "Outside the cluster, the Deployment Console runs in a separate LXC container -- it needs to manage the cluster from the outside. There's also a Build VM for creating Docker images."

> "Every namespace has default-deny network policies. Zero-trust networking."

**Timing target:** 1:30

---

### Slide 5: Technology Stack (1:00)

**On screen:** Two columns -- "Backend & Infrastructure" vs "Frontend & Security Tools"

**Say:**
> "On the backend, all three web apps use FastAPI -- a modern async Python framework. The frontend uses server-rendered Jinja2 templates with Alpine.js for interactivity and Tailwind CSS."

> "I chose Talos Linux because it's an immutable, API-driven OS designed specifically for Kubernetes. There's no SSH, no shell, no package manager -- that makes it inherently more secure."

> "Cross-app authentication uses HMAC-signed one-time codes, so you log in once at the Portal and you're seamlessly authenticated across all three apps."

> **[TRANSITION]** "Let me switch to the live system and show you how all of this works in practice."

**Timing target:** 1:00

---

### Slide 6: Live Demo Transition 1 (0:15)

**On screen:** "Live Demo: Portal Login -> SSO Navigation -> Deployment Console -> Dashboard -> Configuration"

**Say:**
> "I'll start at the Portal, log in, and walk through the Deployment Console."

**Action:** Switch to browser.

---

## LIVE DEMO 1: Portal + Deployment Console (5:00)

### Step 1: Portal Login (0:30)

**Action:** Open `https://cleanroom.knowledgeondemand.net` (logged-out tab)

**Say:**
> "This is the Portal -- the entry point for the platform."

**Action:** Enter admin/admin, click Sign In.

> "The landing page shows two cards -- one for each console application. Each card shows the deployment type and URL."

**Show:** Landing page with Deployment Console and Scanning Console cards.

### Step 2: SSO Navigation (0:30)

**Action:** Click the Deployment Console card.

**Say:**
> "Notice I didn't have to log in again. Behind the scenes, the Portal generated an HMAC-signed one-time code, passed it in the URL, and the Deployment Console exchanged it for a local JWT. Single sign-on across different domains."

### Step 3: Dashboard (1:00)

**Action:** Show the dashboard.

**Say:**
> "This is the dashboard. You can see the deployment status -- all 23 steps completed. Dependencies are verified, configuration is valid."

**Action:** Scroll through the deployed services section.

> "After a successful deployment, you get links to every service -- ArgoCD, Harbor, OpenVAS, Faraday, the Portal, the Scanning Console. Each shows the URL, username, and a masked password you can reveal with the eye icon."

### Step 4: Configuration (1:00)

**Action:** Navigate to Configuration page.

> "This is the configuration editor. The Terraform tab shows the VM specifications -- VMID, hostname, CPU cores, memory, disk size, MAC address."

**Action:** Switch to Talos Config tab.

> "The Talos tab shows the cluster configuration -- cluster name, Talos version, Kubernetes version, API endpoint, node IPs."

**Action:** (Optional) Trigger a validation error.

> "The system validates your configuration before deployment. If something is wrong, you get specific error messages."

### Step 5: Logs (1:00)

**Action:** Navigate to Deployment page or Logs page.

> "The deployment page shows real-time progress. Each of the 23 steps has a status indicator, duration, and expandable log viewer."

**Action:** Expand a step's logs, show filtering.

> "You can filter logs by step and by severity level. Everything streams via WebSocket in real-time."

**Action:** Show the resume/skip capability.

> "If a step fails, you can fix the issue and resume from that exact step -- or skip it if it's not critical. The state is checkpointed after every step."

### Step 6: Cleanup (0:30)

**Action:** Show the cleanup confirmation dialog (DO NOT click Confirm).

> "There's also a cleanup function that tears down the entire infrastructure -- Terraform destroy, Talos node reset, Ceph storage cleanup. This shows the confirmation dialog."

**Action:** Click Cancel, switch back to slides.

### Fallback if Demo Fails

1. Play `docs/user-guide/docs/videos/01-getting-started.mp4` (37 seconds)
2. Show screenshots in order:
   - `portal/portal-login-empty.jpg`
   - `portal/portal-landing-cards.jpg`
   - `deployment/deployment-dashboard-completed.jpg`
   - `deployment/deployment-config-terraform.jpg`
   - `deployment/deployment-logs-filters.jpg`
3. Narrate the same talking points over the screenshots

---

### Slide 7: 23-Step Deployment Pipeline (1:00)

**On screen:** Step groups + screenshot inset of mid-deployment

**Say:**
> "What you just saw was the end state. Let me walk through what happens during a deployment."

> "Steps 0 through 2 use Terraform to create VMs on Proxmox. Steps 3 through 5 generate Talos configs and bootstrap the cluster. Steps 6 through 11 set up the infrastructure -- ArgoCD, MetalLB, cert-manager, Traefik, and Ceph storage."

> "Steps 12 through 16 deploy all the security tools. And the final steps handle secrets, the Build VM, container image builds, app deployment, and network policies."

> "The key design decision: every step is checkpointed to an encrypted state file. If step 14 fails because OpenVAS runs out of memory, you fix the issue and resume from step 14. All previous work is preserved."

**Timing target:** 1:00

---

### Slide 8: Scanning Architecture (1:30)

**On screen:** Two columns -- "Vulnerability Scanning" vs "IOC Scanning"

**Say:**
> "The Scanning Console is the second major application. It provides a unified interface for four vulnerability scanning tools and one IOC scanner."

> [Point left] "For vulnerability scanning: Nmap does port discovery, OpenVAS runs 70,000+ vulnerability tests, and Metasploit does exploit-based verification. Results are auto-enriched with CVSS severity scores and EPSS exploit probability data. Everything gets uploaded to Faraday."

> [Point right] "The IOC scanner is different -- it checks individual servers for signs of malware. It mounts a remote filesystem via SSH or SMB, then runs LOKI-RS against known threat signatures -- YARA rules, malicious file hashes, and C2 indicators."

> "Let me demonstrate this live."

**Timing target:** 1:30

---

### Slide 9: Live Demo Transition 2 (0:15)

**On screen:** "Live Demo: Vulnerability Scan -> IOC Scan -> Reports Dashboard -> Scan Comparison"

**Say:**
> "I'll walk through vulnerability scanning, IOC scanning, and the reporting features."

**Action:** Switch to browser.

---

## LIVE DEMO 2: Scanning Console + Reports (8:00)

### Step 1: SSO into Scanning Console (0:15)

**Action:** From Portal, click the Scanning Console card (or use pre-loaded tab).

**Say:**
> "Again, seamless single sign-on -- no second login required."

### Step 2: Target Lab (1:30)

**Action:** Navigate to the Target Lab tab.

> "This is the Target Lab -- a catalog of intentionally vulnerable environments from the Vulhub project. Each entry shows the CVE, a description, difficulty level, and which scanning tools are recommended."

**Action:** Show the catalog grid.

> "You can deploy these targets directly from the interface. They run as containers in the cluster, giving you safe, isolated environments to scan."

**Action:** Show any active targets (if pre-deployed).

### Step 3: Vulnerability Scan Configuration (1:00)

**Action:** Navigate to the Scan tab.

> "Here's the scan configuration. I enter a target IP or CIDR range, select which tools to run..."

**Action:** Enter a target IP, toggle Nmap and OpenVAS.

> "...and choose a scan profile. Quick runs the top 100 ports in about 5 minutes. Standard does a full service version scan. Thorough does everything including all UDP ports."

**Action:** Show the Custom profile module picker.

> "The Custom profile lets you pick individual Metasploit modules -- there are 39 available, covering everything from EternalBlue and BlueKeep to Heartbleed and Log4Shell."

**Action:** Click Start Scan (if a target is available).

### Step 4: Scan Progress (1:30)

**Action:** Show the real-time progress view.

> "Each tool gets its own progress card. You can see Nmap running, OpenVAS initializing, and the log stream updating in real-time."

**Action:** Show log filtering by tool name.

> "The logs are filterable by tool. Each entry is timestamped and tagged with the source tool."

**Action:** If Nmap completes quickly, show completion. Otherwise move on.

> "When a tool completes, you see the findings count and a badge indicating the results were uploaded to Faraday."

> [If enrichment runs] "After scanning, the system enriches findings with CVSS scores and EPSS exploit probability data from the NVD."

### Step 5: IOC Scanning (1:30)

**Action:** Navigate to the IOC Scan tab.

> "The IOC scanner takes a different approach. Instead of scanning the network, it mounts a remote filesystem and scans the files directly."

**Action:** Show the SSH configuration form.

> "For Linux targets, you configure SSH credentials. For Windows, you use SMB with a share name."

**Action:** (If target available) Start a quick IOC scan.

> "The scan goes through four phases: mounting the filesystem, running LOKI-RS, parsing results, and uploading to Faraday."

**Action:** Show findings if available.

> "Findings are categorized by severity -- Alerts for high-confidence malware indicators, Warnings for suspicious patterns, and Notices for informational matches. You can expand each finding to see the file path, hash values, and matched YARA rules."

### Step 6: Reports (2:00)

**Action:** Navigate to the Reports tab.

> "The Reports dashboard aggregates all scan data. You can see total scans, unique hosts, total vulnerabilities, and a severity breakdown."

**Action:** Show the summary cards.

**Action:** Click into a scan detail.

> "Drilling into a scan shows the timeline, which tools ran, and all findings organized by host."

**Action:** Navigate to the Hosts view.

> "The Hosts view shows every discovered host with its open ports and services."

**Action:** Navigate to the Vulnerabilities view. Show filters.

> "The Vulnerabilities view lets you filter by severity, tool, host, or search for specific CVEs."

**Action:** Show the Compare feature.

> "One of the most useful features is scan comparison. Select two scans and see what's new, what's been resolved, and what's common. This is how you measure remediation progress over time."

**Action:** Show the Audit Log.

> "Finally, there's a full audit trail of every action taken in the system."

**Action:** Switch back to slides.

### Fallback if Demo Fails

1. Play `docs/user-guide/docs/videos/05-reports-tour.mp4` (35 seconds) for reports
2. Show screenshots in order:
   - `scanning/scanning-scan-config-empty.jpg` -- scan configuration
   - `scanning/scanning-scan-running.jpg` -- real-time progress
   - `scanning/scanning-scan-completed.jpg` -- completion with enrichment
   - `scanning/scanning-ioc-ssh.jpg` -- IOC scanner SSH config
   - `scanning/scanning-ioc-findings.jpg` -- IOC findings
   - `reports/reports-dashboard.jpg` -- reports overview
   - `reports/reports-vulns-filters.jpg` -- vulnerability filtering
   - `reports/reports-compare-results.jpg` -- scan comparison
3. Narrate over screenshots (~4 minutes)

---

### Slide 10: Security Architecture (1:30)

**On screen:** 8 bullet points on security decisions

**Say:**
> "Security was a primary concern throughout the design."

> "Starting at the OS level -- Talos Linux is immutable. You literally cannot SSH into the nodes. The only management interface is the Talos API."

> "At the network level, every Kubernetes namespace starts with default-deny for both ingress and egress. I had to explicitly define what each service is allowed to communicate with."

> "Secrets are encrypted at rest in the Git repository using SOPS with Age keys. ArgoCD decrypts them on deploy."

> "The SSO mechanism avoids putting JWTs in URLs, which is a common security anti-pattern. Instead, the Portal generates a short-lived, HMAC-signed, one-time code that the target app exchanges for a local JWT. Single-use, rate-limited, and never replayable."

**Timing target:** 1:30

---

### Slide 11: Results & Achievements (1:00)

**On screen:** 8 bullet points + reports dashboard screenshot inset

**Say:**
> "The end result: bare Proxmox nodes to a fully running security platform in about 45 minutes. One click."

> "434 commits of code across Python, JavaScript, Bash, Terraform, Kubernetes YAML, Helm charts, and SQL."

> "Three production-quality web applications sharing a common authentication library. A documentation site with over 30 pages, screenshots, and video walkthroughs."

> "And most importantly -- it works. We successfully detected known CVEs with all four scanning tools and demonstrated IOC detection against simulated threat indicators."

**Timing target:** 1:00

---

### Slide 12: Lessons Learned & Future Work (1:00)

**On screen:** Two columns -- "Lessons Learned" vs "Future Work"

**Say:**
> "A few highlights from lessons learned."

> "OpenVAS kept getting killed by Kubernetes because it exceeded its 1 gigabyte memory limit. I had to bump it to 4 gig and enable shared process namespaces for zombie process reaping."

> "Faraday's Community Edition doesn't have a working bulk API -- the Celery worker that processes bulk imports doesn't run. I had to write code to create every host, service, and vulnerability individually via the REST API."

> "And the cross-app authentication went through three iterations before I settled on the one-time code exchange pattern."

> [Point right] "For future work, the highest-impact addition would be scheduled scans on a cron schedule, and LDAP integration for enterprise authentication."

**Timing target:** 1:00

---

### Slide 13: Questions (0:30)

**On screen:** "Questions?" with name and GitHub URL

**Say:**
> "Thank you for your attention. I'm happy to take questions. The full source code and documentation are on GitHub."

**Keep the live system open** in the browser for any feature-specific questions.

---

## Timing Summary

| Section | Target | Cumulative |
|---------|--------|------------|
| Slide 1: Title | 0:30 | 0:30 |
| Slide 2: Problem | 1:00 | 1:30 |
| Slide 3: Solution | 1:30 | 3:00 |
| Slide 4: Architecture | 1:30 | 4:30 |
| Slide 5: Tech Stack | 1:00 | 5:30 |
| Slide 6: Demo Transition | 0:15 | 5:45 |
| **LIVE DEMO 1** | **5:00** | **10:45** |
| Slide 7: Deployment | 1:00 | 11:45 |
| Slide 8: Scanning | 1:30 | 13:15 |
| Slide 9: Demo Transition | 0:15 | 13:30 |
| **LIVE DEMO 2** | **8:00** | **21:30** |
| Slide 10: Security | 1:30 | 23:00 |
| Slide 11: Results | 1:00 | 24:00 |
| Slide 12: Lessons | 1:00 | 25:00 |
| Slide 13: Questions | 0:30 | 25:30 |

**Buffer:** ~30 seconds for transitions and overruns.

---

## Screenshot Reference

All screenshots at: `docs/user-guide/docs/img/`

| Demo Section | Screenshots Used |
|-------------|-----------------|
| Demo 1: Portal | `portal/portal-login-empty.jpg`, `portal/portal-landing-cards.jpg`, `portal/portal-credentials-masked.jpg` |
| Demo 1: Deployment | `deployment/deployment-dashboard-completed.jpg`, `deployment/deployment-config-terraform.jpg`, `deployment/deployment-config-talos.jpg`, `deployment/deployment-config-validation-error.jpg`, `deployment/deployment-logs-filters.jpg`, `deployment/deployment-failed-resume-skip.jpg`, `deployment/deployment-cleanup-confirm.jpg`, `deployment/deployment-idle-start.jpg`, `deployment/deployment-running-midflight.jpg`, `deployment/deployment-completed-banner.jpg` |
| Demo 2: Scanning | `scanning/scanning-target-lab-catalog.jpg`, `scanning/scanning-target-lab-active.jpg`, `scanning/scanning-scan-config-empty.jpg`, `scanning/scanning-scan-custom-modules.jpg`, `scanning/scanning-scan-running.jpg`, `scanning/scanning-scan-completed.jpg`, `scanning/scanning-enrichment-progress.jpg` |
| Demo 2: IOC | `scanning/scanning-ioc-ssh.jpg`, `scanning/scanning-ioc-smb.jpg`, `scanning/scanning-ioc-running.jpg`, `scanning/scanning-ioc-findings.jpg` |
| Demo 2: Reports | `reports/reports-dashboard.jpg`, `reports/reports-scan-detail.jpg`, `reports/reports-hosts.jpg`, `reports/reports-vulns-filters.jpg`, `reports/reports-compare-results.jpg`, `reports/reports-audit.jpg`, `scanning/scanning-vuln-remediation.jpg` |

## Video Reference

All videos at: `docs/user-guide/docs/videos/`

| Video | Duration | Use |
|-------|----------|-----|
| `01-getting-started.mp4` | 37s | Fallback for Demo 1 |
| `01-getting-started_subtitled.mp4` | 37s | Fallback with subtitles |
| `03-vuln-scan.mp4` | 14m | Do NOT embed (too long); reference for deep-dive questions |
| `05-reports-tour.mp4` | 35s | Fallback for Demo 2 reports section |
| `05-reports-tour_subtitled.mp4` | 35s | Fallback with subtitles |

---

## Anticipated Questions

**Q: Why Talos Linux instead of Ubuntu or another distro?**
> Talos is immutable and API-only. There's no SSH, no shell, no package manager. The attack surface is minimal. It's designed specifically for Kubernetes and nothing else.

**Q: Why not use a managed Kubernetes service (EKS, GKE, AKS)?**
> This runs on-premises on Proxmox, giving full control over the infrastructure. That's the point of the project -- demonstrating IaC on bare metal, not delegating to a cloud provider.

**Q: How long does a full deployment take?**
> About 45 minutes from bare Proxmox nodes to a fully running platform with all security tools deployed.

**Q: Could this scale to production?**
> Yes. Talos and ArgoCD are production-grade. The web apps would need horizontal scaling (multiple replicas behind a load balancer) and the PostgreSQL database would need production tuning (connection pooling, proper backups, possibly a managed service).

**Q: What was the hardest part?**
> OpenVAS integration. It's a complex application with 11 init containers and 6 main containers, 10 persistent volume claims, and very specific resource requirements. Getting it stable in Kubernetes with proper networking and zombie process handling took significant iteration.

**Q: How do you handle secrets?**
> SOPS encrypts secrets with Age keys. The encrypted secrets are committed to Git. ArgoCD has a KSOPS plugin that decrypts them during deployment. Secrets are never stored in plaintext in the repository.

**Q: What testing did you do?**
> Each scanning tool was verified against known-vulnerable targets (Vulhub containers). The deployment pipeline was tested through multiple full deploy/destroy/redeploy cycles. The IOC scanner was tested against files with known YARA rule matches.
