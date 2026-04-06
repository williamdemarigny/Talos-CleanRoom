// Alpine.js component for Scan Detail report page

function reportsScanDetail(scanId) {
    return {
        scanId: scanId,
        scan: null,

        get labCoverage() {
            if (!this.scan || !this.scan.lab_env_id) return { detected: false };
            const allVulns = (this.scan.hosts || []).flatMap(h => h.vulnerabilities || []);
            const hasLabExpected = allVulns.some(v => v.tool_source === 'lab_expected');
            // If no lab_expected vuln exists, scanners detected the CVE natively
            return { detected: !hasLabExpected };
        },

        async init() {
            await this.fetchScan();
        },

        async fetchScan() {
            try {
                const resp = await fetch(`/api/reports/scans/${this.scanId}`);
                if (resp.ok) {
                    this.scan = await resp.json();
                } else {
                    console.error('Scan not found');
                }
            } catch (e) {
                console.error('Failed to fetch scan:', e);
            }
        }
    };
}
