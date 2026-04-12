// Alpine.js components for Reports pages

function reportsDashboard() {
    return {
        summary: { scan_count: 0, host_count: 0, vuln_total: 0, vulns_by_severity: {} },
        scans: [],

        async init() {
            await Promise.all([this.fetchSummary(), this.fetchScans()]);
        },

        async fetchSummary() {
            try {
                const resp = await authFetch('/api/reports/summary');
                this.summary = await resp.json();
            } catch (e) {
                console.error('Failed to fetch summary:', e);
            }
        },

        async fetchScans() {
            try {
                const resp = await authFetch('/api/reports/scans?limit=20');
                const data = await resp.json();
                this.scans = data.scans || [];
            } catch (e) {
                console.error('Failed to fetch scans:', e);
            }
        }
    };
}


function reportsHosts() {
    return {
        hosts: [],
        filterScanId: '',
        offset: 0,
        pageSize: 50,

        async init() {
            await this.fetchHosts();
        },

        async fetchHosts() {
            try {
                let url = `/api/reports/hosts?limit=${this.pageSize}&offset=${this.offset}`;
                if (this.filterScanId) url += `&scan_id=${encodeURIComponent(this.filterScanId)}`;
                const resp = await authFetch(url);
                const data = await resp.json();
                this.hosts = data.hosts || [];
            } catch (e) {
                console.error('Failed to fetch hosts:', e);
            }
        },

        nextPage() {
            this.offset += this.pageSize;
            this.fetchHosts();
        },

        prevPage() {
            this.offset = Math.max(0, this.offset - this.pageSize);
            this.fetchHosts();
        }
    };
}


function reportsVulns() {
    return {
        vulns: [],
        selectedVulns: [],
        bulkStatus: '',
        filterSeverity: '',
        filterRemediation: '',
        filterScanId: '',
        filterEnrichment: '',
        sortBy: '',
        sortOrder: 'desc',
        offset: 0,
        pageSize: 50,

        async init() {
            await this.fetchVulns();
        },

        async fetchVulns() {
            try {
                let url = `/api/reports/vulns?limit=${this.pageSize}&offset=${this.offset}`;
                if (this.filterSeverity) url += `&severity=${encodeURIComponent(this.filterSeverity)}`;
                if (this.filterRemediation) url += `&remediation_status=${encodeURIComponent(this.filterRemediation)}`;
                if (this.filterScanId) url += `&scan_id=${encodeURIComponent(this.filterScanId)}`;
                if (this.filterEnrichment) url += `&enrichment_status=${encodeURIComponent(this.filterEnrichment)}`;
                if (this.sortBy) url += `&sort_by=${this.sortBy}&sort_order=${this.sortOrder}`;
                const resp = await authFetch(url);
                const data = await resp.json();
                this.vulns = data.vulns || [];
                this.selectedVulns = [];
            } catch (e) {
                console.error('Failed to fetch vulns:', e);
            }
        },

        toggleSort(field) {
            if (this.sortBy === field) {
                this.sortOrder = this.sortOrder === 'desc' ? 'asc' : 'desc';
            } else {
                this.sortBy = field;
                this.sortOrder = 'desc';
            }
            this.offset = 0;
            this.fetchVulns();
        },

        toggleAll(event) {
            if (event.target.checked) {
                this.selectedVulns = this.vulns.map(v => v.id);
            } else {
                this.selectedVulns = [];
            }
        },

        async bulkUpdate() {
            if (!this.bulkStatus || this.selectedVulns.length === 0) return;
            try {
                const resp = await authFetch('/api/reports/vulns/bulk-remediation', {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ vuln_ids: this.selectedVulns, status: this.bulkStatus })
                });
                if (resp.ok) {
                    this.bulkStatus = '';
                    await this.fetchVulns();
                }
            } catch (e) {
                console.error('Failed to bulk update:', e);
            }
        },

        nextPage() {
            this.offset += this.pageSize;
            this.fetchVulns();
        },

        prevPage() {
            this.offset = Math.max(0, this.offset - this.pageSize);
            this.fetchVulns();
        }
    };
}


function reportsAudit() {
    return {
        entries: [],
        filterAction: '',
        filterUser: '',
        offset: 0,
        pageSize: 50,

        async init() {
            await this.fetchEntries();
        },

        async fetchEntries() {
            try {
                let url = `/api/reports/audit?limit=${this.pageSize}&offset=${this.offset}`;
                if (this.filterAction) url += `&action=${encodeURIComponent(this.filterAction)}`;
                if (this.filterUser) url += `&audit_user=${encodeURIComponent(this.filterUser)}`;
                const resp = await authFetch(url);
                const data = await resp.json();
                this.entries = data.entries || [];
            } catch (e) {
                console.error('Failed to fetch audit log:', e);
            }
        },

        nextPage() {
            this.offset += this.pageSize;
            this.fetchEntries();
        },

        prevPage() {
            this.offset = Math.max(0, this.offset - this.pageSize);
            this.fetchEntries();
        }
    };
}
