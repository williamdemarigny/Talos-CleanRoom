# Scan Profiles

Scan profiles control how thorough (and how long) each scanning tool operates. Choose a profile based on your time budget and the level of detail you need.

## Profile Comparison

| | Quick | Standard | Thorough |
|---|---|---|---|
| **Duration** | ~5-15 min (Nmap) / ~2 hrs (with OpenVAS) | ~2-8 hours | ~4-14 hours |
| **Best for** | Fast check, smoke test | Regular assessments | Full compliance audit |
| **Nmap** | Top 100 ports, fast timing | All TCP ports, version detection | All TCP+UDP, full scripts |
| **OpenVAS** | Host discovery only | Full and Fast scan | Full and Deep scan |
| **Metasploit** | Not available | 11 core modules | 39 modules (comprehensive) |
| **WPScan** | Version detection only | Vulnerable plugins + themes, user detection | Aggressive enumeration of all plugins, themes, users, and config backups |

## Nmap Details

| Profile | Flags | What It Does |
|---|---|---|
| Quick | `-T4 --top-ports 100` | Scans only the 100 most common ports with aggressive timing |
| Standard | `-sV -sC` | Scans all 65,535 TCP ports with version and script detection |
| Thorough | `-sV -sC -p- -A` | All TCP and UDP ports, OS detection, traceroute, all scripts |

## OpenVAS Details

| Profile | Config | What It Does |
|---|---|---|
| Quick | Host Discovery | Only checks if hosts are alive and identifies their OS |
| Standard | Full and Fast | Runs all vulnerability tests that can be done without being disruptive |
| Thorough | Full and Deep | Runs all tests including potentially disruptive ones and deep checks |

!!! warning "Thorough scans are intensive"
    A Thorough OpenVAS scan can generate significant network traffic and may cause performance impacts on target systems. Use with caution on production networks.

## Metasploit Details

### Standard Profile (11 modules)

Checks for the most commonly exploited vulnerabilities:

- EternalBlue (MS17-010), Conficker, BlueKeep (CVE-2019-0708)
- Heartbleed (OpenSSL), Log4Shell, Shellshock
- HTTP.sys (MS15-034)
- SSH, HTTP, SMB, and FTP version detection

### Thorough Profile (39 modules)

Adds to Standard with:

- SMB share and user enumeration
- RDP vulnerability checks
- HTTP brute-force and directory scanning
- Database scanners (MySQL, PostgreSQL, MSSQL)
- Additional service fingerprinting

## WPScan Details

WPScan is a WordPress-specific vulnerability scanner. It runs as a temporary Kubernetes pod using the `wpscanteam/wpscan` image. If the target is not running WordPress, WPScan automatically skips and reports no findings.

| Profile | What It Does |
|---|---|
| Quick | Detects WordPress version only |
| Standard | Enumerates vulnerable plugins and themes, detects users |
| Thorough | Aggressive enumeration of all plugins, themes, users, and config backups |

## Custom Profile

The Custom profile lets you pick exactly which tools and modules to run:

- **Metasploit modules** — browse by category and select individual modules
- **OpenVAS configuration** — choose a preset config or select specific NVT (Network Vulnerability Test) families

## Timeouts

Each tool has a maximum runtime to prevent scans from running indefinitely:

| Profile | Nmap | OpenVAS | Metasploit | WPScan |
|---|---|---|---|---|
| Quick | 5 min | 2 hr 5 min | 15 min | 2 min |
| Standard | 15 min | 8 hr | 1 hr 30 min | 10 min |
| Thorough | 1 hr | 14 hr | 3 hr | 30 min |

If a tool reaches its timeout, it will stop and report whatever results it has found so far.

## Which Profile Should I Use?

- **Quick** — when you need a fast sanity check or are scanning a large number of hosts and want initial results quickly
- **Standard** — for most regular vulnerability assessments; good balance of thoroughness and time
- **Thorough** — for compliance audits, penetration test preparation, or when you need maximum coverage and have the time
- **Custom** — when you know exactly which checks you want to run (e.g., only checking for a specific CVE)
