/**
 * Target Lab — Alpine.js component for Metasploitable3 VM management.
 *
 * Auto-deploy: On first visit per browser session, if no VMs are active and
 * the service is enabled, automatically deploys an Ubuntu 14.04 target VM.
 * Uses sessionStorage to prevent re-triggering on page refresh.
 */
function targetLabManager() {
    const AUTO_DEPLOY_KEY = 'tl_auto_deploy_triggered';

    return {
        enabled: false,
        templates: [],
        targets: [],
        capacity: { used: 0, max: 4, available: 4 },
        deploying: false,
        deployingType: '',
        autoDeploying: false,
        error: '',
        _pollTimer: null,
        _autoDeployLock: false,

        async init() {
            await this.loadTemplates();
            await this.loadTargets();

            // Auto-deploy Ubuntu if this is first visit and no VMs exist
            await this.attemptAutoDeploy();

            // Poll every 10 seconds for status updates
            this._pollTimer = setInterval(() => this.loadTargets(), 10000);
        },

        destroy() {
            if (this._pollTimer) clearInterval(this._pollTimer);
        },

        async loadTemplates() {
            try {
                const resp = await authFetch('/api/target-lab/templates');
                if (resp.ok) {
                    const data = await resp.json();
                    this.templates = data.templates || [];
                    this.enabled = data.enabled;
                } else {
                    this.enabled = false;
                }
            } catch (e) {
                console.error('Failed to load templates:', e);
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

        async attemptAutoDeploy() {
            // Only run once per browser session
            if (this._autoDeployLock) return;
            if (sessionStorage.getItem(AUTO_DEPLOY_KEY) === 'true') return;

            // Guard: service must be enabled with templates available
            if (!this.enabled || this.templates.length === 0) return;

            // Guard: no existing VMs (including deploying ones)
            if (this.targets.length > 0) {
                sessionStorage.setItem(AUTO_DEPLOY_KEY, 'true');
                return;
            }

            // Guard: capacity available
            if (this.capacity.available <= 0) return;

            // Guard: Ubuntu template must exist
            if (!this.templates.find(t => t.type === 'ubuntu')) return;

            this._autoDeployLock = true;
            this.autoDeploying = true;
            try {
                await this.deploy('ubuntu');
                sessionStorage.setItem(AUTO_DEPLOY_KEY, 'true');
            } catch (e) {
                console.error('[AutoDeploy] Failed:', e);
            } finally {
                this._autoDeployLock = false;
                this.autoDeploying = false;
            }
        },

        async deploy(templateType) {
            this.error = '';
            this.deploying = true;
            this.deployingType = templateType;
            try {
                const resp = await authFetch('/api/target-lab/deploy', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ template: templateType }),
                });
                const data = await resp.json();
                if (!resp.ok) {
                    this.error = data.detail || 'Deployment failed';
                    return;
                }
                await this.loadTargets();
            } catch (e) {
                this.error = 'Deployment request failed: ' + e.message;
            } finally {
                this.deploying = false;
                this.deployingType = '';
            }
        },

        isDeploying(type) {
            return this.deploying && this.deployingType === type;
        },

        async confirmDestroy(vmid, name) {
            if (!confirm(`Destroy target VM "${name}" (VMID ${vmid})? This cannot be undone.`)) {
                return;
            }
            this.error = '';
            try {
                const resp = await authFetch(`/api/target-lab/destroy/${vmid}`, {
                    method: 'POST',
                });
                if (!resp.ok) {
                    const data = await resp.json();
                    this.error = data.detail || 'Destroy failed';
                    return;
                }
                await this.loadTargets();
            } catch (e) {
                this.error = 'Destroy request failed: ' + e.message;
            }
        },

        async extendTTL(vmid) {
            this.error = '';
            try {
                const resp = await authFetch(`/api/target-lab/extend/${vmid}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ hours: 4 }),
                });
                if (!resp.ok) {
                    const data = await resp.json();
                    this.error = data.detail || 'TTL extension failed';
                    return;
                }
                await this.loadTargets();
            } catch (e) {
                this.error = 'TTL extension failed: ' + e.message;
            }
        },

        scanTarget(ip) {
            window.location.href = '/scan?target=' + encodeURIComponent(ip);
        },

        statusClass(status) {
            switch (status) {
                case 'running':   return 'bg-green-900/50 text-green-400';
                case 'deploying': return 'bg-yellow-900/50 text-yellow-400';
                case 'stopping':  return 'bg-orange-900/50 text-orange-400';
                case 'error':     return 'bg-red-900/50 text-red-400';
                case 'destroyed': return 'bg-gray-700 text-gray-400';
                default:          return 'bg-gray-700 text-gray-400';
            }
        },

        formatTTL(seconds) {
            if (!seconds || seconds <= 0) return 'Expired';
            const h = Math.floor(seconds / 3600);
            const m = Math.floor((seconds % 3600) / 60);
            if (h > 0) return h + 'h ' + m + 'm';
            return m + 'm';
        },
    };
}
