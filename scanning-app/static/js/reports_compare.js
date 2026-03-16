// Alpine.js component for Scan Comparison page

function reportsCompare() {
    return {
        scans: [],
        scanA: '',
        scanB: '',
        result: null,

        async init() {
            await this.fetchScans();
        },

        async fetchScans() {
            try {
                const resp = await fetch('/api/reports/scans?limit=100');
                const data = await resp.json();
                this.scans = data.scans || [];
            } catch (e) {
                console.error('Failed to fetch scans:', e);
            }
        },

        async compare() {
            if (!this.scanA || !this.scanB) return;
            try {
                const resp = await fetch(`/api/reports/compare/${this.scanA}/${this.scanB}`);
                if (resp.ok) {
                    this.result = await resp.json();
                }
            } catch (e) {
                console.error('Failed to compare scans:', e);
            }
        }
    };
}
