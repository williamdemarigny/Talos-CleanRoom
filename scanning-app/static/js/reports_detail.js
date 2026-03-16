// Alpine.js component for Scan Detail report page

function reportsScanDetail(scanId) {
    return {
        scanId: scanId,
        scan: null,

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
