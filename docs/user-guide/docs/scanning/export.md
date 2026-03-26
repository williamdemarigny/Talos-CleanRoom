# Exporting Results

You can download scan results as CSV or JSON files for reporting, compliance documentation, or sharing with team members.

## CSV Export

CSV files can be opened in Excel, Google Sheets, or any spreadsheet application.

1. Go to **Reports** → **Vulnerabilities**
2. Optionally apply filters (by scan, severity, or remediation status) to narrow the data
3. Click the **Export CSV** button

The downloaded CSV includes these columns:

- ID, Scan ID, Host ID
- Vulnerability name, severity, external ID (CVE number)
- Tool source (which scanner found it)
- Remediation status and notes
- CVSS score, CVSS vector, CVSS version, NVD severity
- EPSS score, EPSS percentile
- Enrichment status
- Description

!!! tip "Safe for spreadsheets"
    The CSV export includes protection against formula injection — values that start with special characters (`=`, `+`, `-`, `@`) are safely escaped so they cannot execute formulas when opened in Excel.

## JSON Export

JSON files are useful for importing into other security tools or for programmatic analysis.

### Vulnerability JSON

1. Go to **Reports** → **Vulnerabilities**
2. Click **Export JSON**

### Full Scan Report

To export everything from a single scan (hosts, services, vulnerabilities, and IOC findings):

1. Go to **Reports** → click on a specific scan
2. Click **Export JSON** on the scan detail page

## Filtering Before Export

Both CSV and JSON exports respect your current filters. To export only specific data:

- **By scan** — select a specific scan from the dropdown
- **By severity** — export only Critical/High vulnerabilities
- **By remediation status** — export only Open (unfixed) vulnerabilities

## Audit Trail

All exports are automatically logged in the [Audit Log](../reports/audit.md), recording who exported what and when.

## What's Next?

- [Vulnerabilities Report](../reports/vulnerabilities.md) — filter data before exporting
- [Remediation Tracking](remediation.md) — update status on findings
- [Audit Log](../reports/audit.md) — review export history
