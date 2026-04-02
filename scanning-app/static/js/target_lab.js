/**
 * Target Lab — Alpine.js component for Vulhub K8s-based vulnerable environments.
 */
function targetLab() {
    return {
        enabled: false,
        loading: true,
        catalog: [],
        targets: [],
        capacity: { used: 0, max: 8, available: 8 },
        selectedCategory: 'all',
        searchQuery: '',
        deployingId: '',
        error: '',
        _pollTimer: null,

        categories: [
            { value: 'all', label: 'All' },
            { value: 'rce', label: 'RCE' },
            { value: 'web', label: 'Web' },
            { value: 'network', label: 'Network' },
            { value: 'auth', label: 'Auth' },
            { value: 'misc', label: 'Misc' },
        ],

        async init() {
            await Promise.all([this.loadCatalog(), this.loadTargets()]);
            this.loading = false;

            // Poll targets every 10 seconds
            this._pollTimer = setInterval(() => this.loadTargets(), 10000);

            // Clean up polling on navigation
            window.addEventListener('beforeunload', () => this.cleanup());
        },

        cleanup() {
            if (this._pollTimer) {
                clearInterval(this._pollTimer);
                this._pollTimer = null;
            }
        },

        async loadCatalog() {
            try {
                const resp = await authFetch('/api/target-lab/catalog');
                if (resp.ok) {
                    const data = await resp.json();
                    this.catalog = data.catalog || [];
                    this.enabled = data.enabled;
                } else {
                    this.enabled = false;
                }
            } catch (e) {
                console.error('Failed to load catalog:', e);
                this.enabled = false;
            }
        },

        async loadTargets() {
            try {
                const resp = await authFetch('/api/target-lab/targets');
                if (resp.ok) {
                    const data = await resp.json();
                    this.targets = data.targets || [];
                    this.capacity = data.capacity || this.capacity;
                    this.enabled = data.enabled;
                }
            } catch (e) {
                console.error('Failed to load targets:', e);
            }
        },

        get filteredCatalog() {
            let items = this.catalog;
            if (this.selectedCategory !== 'all') {
                items = items.filter(e => e.category === this.selectedCategory);
            }
            if (this.searchQuery.trim()) {
                const q = this.searchQuery.trim().toLowerCase();
                items = items.filter(e =>
                    (e.name && e.name.toLowerCase().includes(q)) ||
                    (e.cve && e.cve.toLowerCase().includes(q)) ||
                    (e.description && e.description.toLowerCase().includes(q))
                );
            }
            return items;
        },

        async deploy(envId) {
            this.error = '';
            this.deployingId = envId;
            try {
                const resp = await authFetch('/api/target-lab/deploy', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ env_id: envId }),
                });
                if (!resp.ok) {
                    try {
                        const data = await resp.json();
                        this.error = data.detail || 'Deployment failed';
                    } catch {
                        this.error = 'Deployment failed (HTTP ' + resp.status + ')';
                    }
                    return;
                }
                await this.loadTargets();
            } catch (e) {
                this.error = 'Deployment request failed: ' + e.message;
            } finally {
                this.deployingId = '';
            }
        },

        async confirmDestroy(targetId, name) {
            if (!confirm('Destroy target "' + name + '"? This will delete the namespace and all resources.')) {
                return;
            }
            this.error = '';
            try {
                const resp = await authFetch('/api/target-lab/destroy/' + targetId, {
                    method: 'POST',
                });
                if (!resp.ok) {
                    try {
                        const data = await resp.json();
                        this.error = data.detail || 'Destroy failed';
                    } catch {
                        this.error = 'Destroy failed (HTTP ' + resp.status + ')';
                    }
                    return;
                }
                await this.loadTargets();
            } catch (e) {
                this.error = 'Destroy request failed: ' + e.message;
            }
        },

        async extendTtl(targetId) {
            this.error = '';
            try {
                const resp = await authFetch('/api/target-lab/extend/' + targetId, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ hours: 2 }),
                });
                if (!resp.ok) {
                    try {
                        const data = await resp.json();
                        this.error = data.detail || 'TTL extension failed';
                    } catch {
                        this.error = 'TTL extension failed (HTTP ' + resp.status + ')';
                    }
                    return;
                }
                await this.loadTargets();
            } catch (e) {
                this.error = 'TTL extension failed: ' + e.message;
            }
        },

        scanTarget(endpoint) {
            window.location.href = '/scan?target=' + encodeURIComponent(endpoint);
        },

        ttlSeconds(target) {
            if (!target.ttl_expires_at) return 0;
            const expires = new Date(target.ttl_expires_at).getTime();
            const remaining = Math.max(0, Math.floor((expires - Date.now()) / 1000));
            return remaining;
        },

        ttlRemaining(target) {
            const seconds = this.ttlSeconds(target);
            if (seconds <= 0) return 'Expired';
            const h = Math.floor(seconds / 3600);
            const m = Math.floor((seconds % 3600) / 60);
            if (h > 0) return h + 'h ' + m + 'm';
            return m + 'm';
        },

        statusClass(status) {
            switch (status) {
                case 'running':    return 'bg-green-900/50 text-green-400';
                case 'deploying':  return 'bg-yellow-900/50 text-yellow-400';
                case 'destroying': return 'bg-orange-900/50 text-orange-400';
                case 'error':      return 'bg-red-900/50 text-red-400';
                case 'destroyed':  return 'bg-gray-700 text-gray-400';
                default:           return 'bg-gray-700 text-gray-400';
            }
        },

        categoryBadgeClass(category) {
            switch (category) {
                case 'rce':     return 'bg-red-900/50 text-red-400';
                case 'web':     return 'bg-blue-900/50 text-blue-400';
                case 'network': return 'bg-green-900/50 text-green-400';
                case 'auth':    return 'bg-yellow-900/50 text-yellow-400';
                default:        return 'bg-gray-700 text-gray-300';
            }
        },
    };
}
