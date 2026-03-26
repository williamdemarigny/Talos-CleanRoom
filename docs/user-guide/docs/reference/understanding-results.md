# Understanding Results

This page explains how to interpret the severity scores, enrichment data, and finding levels shown in scan results.

## CVSS — Vulnerability Severity

CVSS (Common Vulnerability Scoring System) rates vulnerabilities on a scale of 0.0 to 10.0:

| Score | Severity | Color | What It Means |
|---|---|---|---|
| 9.0 - 10.0 | **Critical** | Red | Extremely dangerous. Can be easily exploited with severe consequences. Fix immediately. |
| 7.0 - 8.9 | **High** | Orange | Serious vulnerability. Should be fixed as a high priority. |
| 4.0 - 6.9 | **Medium** | Yellow | Moderate risk. Plan to fix in a reasonable timeframe. |
| 0.1 - 3.9 | **Low** | Blue | Minor issue. Fix when convenient or accept the risk. |
| 0.0 | **Info** | Gray | Informational finding. No direct security impact. |

!!! tip "Focus on Critical and High first"
    When triaging a large number of findings, start with Critical and High severity vulnerabilities. These represent the most immediate risk to your systems.

## EPSS — Exploit Probability

EPSS (Exploit Prediction Scoring System) predicts the probability that a vulnerability will be exploited in the wild within the next 30 days.

| Value | Meaning |
|---|---|
| **Score** (0.0 to 1.0) | Probability of exploitation. For example, 0.15 means a 15% chance. |
| **Percentile** (0-100) | How this vulnerability compares to all other known vulnerabilities. A 95th percentile means it is more likely to be exploited than 95% of all CVEs. |

!!! tip "EPSS helps prioritize"
    Two vulnerabilities might both be rated "High" by CVSS, but if one has an EPSS of 0.90 (90% likely to be exploited) and the other has 0.01 (1%), you should fix the first one first.

## NVD Severity vs. Tool Severity

The Scanning Console shows two severity assessments:

- **Tool Severity** — the severity as reported by the scanning tool (Nmap, OpenVAS, or Metasploit). This is the original finding.
- **NVD Severity** — the severity from the National Vulnerability Database, based on the official CVSS score. This is added during [enrichment](../scanning/enrichment.md).

When both are available, the NVD severity is generally considered more authoritative, but the tool severity is never overwritten — both are preserved.

## Enrichment Statuses

Each vulnerability has an enrichment status:

| Status | Meaning |
|---|---|
| **Enriched** | CVSS and EPSS data was successfully retrieved |
| **Pending** | Waiting to be enriched (enrichment may still be running) |
| **Skipped** | The vulnerability has no CVE identifier, so it cannot be looked up in NVD |
| **Failed** | The lookup failed (network error or API issue). Will be retried automatically. |

## IOC Severity Levels

IOC (Indicator of Compromise) findings use a different scoring system:

| Severity | Score Range | Meaning |
|---|---|---|
| **Alert** | 80-100 | High confidence match. The file is very likely malicious (malware, hacking tool, known threat). Investigate immediately. |
| **Warning** | 60-79 | Suspicious file. May be a legitimate tool that is commonly abused, or a partial signature match. Review manually. |
| **Notice** | Below 60 | Low confidence. The file triggered a low-priority rule. Usually benign, but noted for completeness. |

## CVE Identifiers

Many vulnerabilities are identified by a **CVE number** (Common Vulnerabilities and Exposures), such as `CVE-2024-1234`. This is a globally unique identifier maintained by MITRE. You can look up any CVE at [cve.org](https://www.cve.org/) for official details.

## CWE Categories

The **CWE** (Common Weakness Enumeration) field categorizes the type of vulnerability. Common examples:

| CWE | Category | Example |
|---|---|---|
| CWE-79 | Cross-Site Scripting (XSS) | Injecting scripts into web pages |
| CWE-89 | SQL Injection | Injecting database commands |
| CWE-120 | Buffer Overflow | Sending too much data to crash a program |
| CWE-200 | Information Exposure | Leaking sensitive data |
| CWE-287 | Authentication Bypass | Accessing systems without proper login |
