# Glossary

Technical terms used throughout the Talos CleanRoom platform, explained in plain language.

## A-C

**ArgoCD**
: A tool that automatically deploys and updates applications in Kubernetes based on configuration files stored in Git. "GitOps" means Git is the single source of truth for what should be deployed.

**CIDR**{ #cidr }
: A way to specify a block of IP addresses. For example, `10.0.0.0/24` means all addresses from 10.0.0.0 to 10.0.0.255 (256 addresses). The number after the slash indicates how many addresses are in the block.

**CVE** (Common Vulnerabilities and Exposures)
: A unique identifier for a known security vulnerability, like `CVE-2024-1234`. Maintained by MITRE and used worldwide.

**CVSS** (Common Vulnerability Scoring System)
: A scoring system that rates vulnerability severity from 0.0 to 10.0. See [Understanding Results](understanding-results.md).

**CWE** (Common Weakness Enumeration)
: A categorization system for types of software vulnerabilities (e.g., SQL Injection, Buffer Overflow).

## D-F

**EPSS** (Exploit Prediction Scoring System)
: A score (0 to 1) predicting the probability that a vulnerability will be exploited in the next 30 days. See [Understanding Results](understanding-results.md).

**Enrichment**
: The process of looking up additional data (CVSS, EPSS, threat intel) for vulnerabilities from public databases. See [Enrichment](../scanning/enrichment.md).

**Faraday**
: A vulnerability management platform that aggregates findings from multiple scanning tools into a single view. Scan results are automatically uploaded to Faraday.

## G-K

**Harbor**
: A container image registry — a storage system for Docker container images (the building blocks of applications running in Kubernetes).

**IOC** (Indicator of Compromise)
: Evidence that a system has been breached or infected. Examples: malware files, suspicious registry entries, known malicious file hashes.

**Kubernetes**
: A platform for running and managing containerized applications across multiple servers. Talos CleanRoom runs on Kubernetes.

**Kubeconfig**
: A configuration file that provides access credentials for a Kubernetes cluster. Used by command-line tools like `kubectl`.

## L-N

**LOKI-RS**
: A file system scanner that checks for IOCs (Indicators of Compromise) using YARA rules, hash matching, and filename patterns. Used for the IOC Scan feature.

**Metasploit**
: A penetration testing framework that can verify vulnerabilities by attempting to exploit them. One of the three scanning tools available in the Scanning Console.

**Nmap**
: A network scanner that discovers hosts, open ports, and running services. The fastest of the three scanning tools.

**NVD** (National Vulnerability Database)
: A US government database of known vulnerabilities, maintained by NIST. The source for official CVSS scores.

**NVT** (Network Vulnerability Test)
: An individual test script used by OpenVAS to check for a specific vulnerability or configuration issue.

## O-S

**OpenVAS**
: An open-source vulnerability scanner that runs thousands of NVTs against target systems. The most thorough of the three scanning tools.

**Proxmox**
: The server virtualization platform that hosts the virtual machines running the Talos CleanRoom cluster.

**SMB/CIFS**
: Windows file sharing protocol. Used by IOC scanning to mount and scan Windows file systems remotely.

**SSHFS**
: A way to mount a remote Linux/Unix file system over SSH. Used by IOC scanning to scan Linux servers.

## T-Z

**Talos Linux**
: A minimal, security-focused Linux distribution designed specifically for running Kubernetes. The operating system used by all cluster nodes.

**Terraform**
: An infrastructure-as-code tool that creates and manages virtual machines and other infrastructure. Used by the Deployment Console to provision the cluster.

**Threat Dragon**
: An OWASP threat modeling tool for documenting and analyzing security architecture.

**Traefik**
: A web gateway (reverse proxy) that routes incoming web traffic to the correct application. Handles TLS encryption and DNS routing for all `*.knowledgeondemand.net` services.

**YARA**
: A pattern-matching language used to describe malware signatures. YARA rules are what LOKI-RS uses to identify suspicious files during IOC scans.
