// Deployment monitor Alpine.js component

function deploymentMonitor() {
    return {
        status: 'idle',
        currentStep: 0,
        isRunning: false,
        wsConnected: false,
        steps: [],
        logs: [],
        expandedSteps: [],
        autoScroll: true,
        startTime: null,
        elapsedTime: '',
        ws: null,
        elapsedTimer: null,
        pollInterval: null,

        // Shared helpers instance (polling, scroll, log dedup)
        _wsBase: null,

        // Client-side statuses that should not be overwritten by server polls
        _clientSideStatuses: ['cleaning'],

        // Step definitions — must match DEPLOYMENT_STEPS in app/models/deployment.py
        stepDefinitions: [
            { id: 0, name: 'validate_git', description: 'Validate Git Repository' },
            { id: 1, name: 'check_dependencies', description: 'Check Dependencies' },
            { id: 2, name: 'terraform_deploy', description: 'Terraform Deploy' },
            { id: 3, name: 'wait_for_vms', description: 'Wait for VMs to Boot' },
            { id: 4, name: 'generate_talos_config', description: 'Generate Talos Config' },
            { id: 5, name: 'apply_talos_configs', description: 'Apply Talos Configurations' },
            { id: 6, name: 'verify_cluster_health', description: 'Verify Cluster Health' },
            { id: 7, name: 'get_kubeconfig', description: 'Get Kubeconfig' },
            { id: 8, name: 'install_argocd', description: 'Install ArgoCD' },
            { id: 9, name: 'deploy_infrastructure', description: 'Deploy Infrastructure Stack' },
            { id: 10, name: 'argocd_self_management', description: 'Enable ArgoCD Self-Management' },
            { id: 11, name: 'deploy_harbor', description: 'Deploy Harbor Registry' },
            { id: 12, name: 'deploy_build_vm', description: 'Deploy Build VM' },
            { id: 13, name: 'mirror_greenbone_images', description: 'Mirror Greenbone Images to Harbor' },
            { id: 14, name: 'deploy_openvas', description: 'Deploy OpenVAS' },
            { id: 15, name: 'deploy_faraday', description: 'Deploy Faraday' },
            { id: 16, name: 'deploy_metasploit', description: 'Deploy Metasploit' },
            { id: 17, name: 'deploy_threat_dragon', description: 'Deploy Threat Dragon' },
            { id: 18, name: 'configure_integrations', description: 'Configure Integrations' },
            { id: 19, name: 'generate_secrets', description: 'Generate & Apply Secrets' },
            { id: 20, name: 'commit_push_secrets', description: 'Commit & Push Secrets' },
            { id: 21, name: 'prepare_vulhub_targets', description: 'Prepare Vulhub Target Environments' },
            { id: 22, name: 'build_push_images', description: 'Build & Push Container Images' },
            { id: 23, name: 'deploy_cleanroom_apps', description: 'Deploy CleanRoom Applications' },
            { id: 24, name: 'deploy_console_routing', description: 'Deploy Deployment Console Routing' },
            { id: 25, name: 'apply_network_policies', description: 'Apply Network Policies' },
        ],

        get statusText() {
            switch (this.status) {
                case 'running': return 'Deployment in Progress';
                case 'cleaning': return 'Cleanup in Progress';
                case 'completed': return 'Deployment Completed';
                case 'failed': return 'Deployment Failed';
                case 'aborted': return 'Deployment Aborted';
                default: return 'Ready to Deploy';
            }
        },

        get statusBannerClass() {
            switch (this.status) {
                case 'running': return 'bg-yellow-900/30 border border-yellow-700 text-yellow-300';
                case 'cleaning': return 'bg-orange-900/30 border border-orange-700 text-orange-300';
                case 'completed': return 'bg-green-900/30 border border-green-700 text-green-300';
                case 'failed': return 'bg-red-900/30 border border-red-700 text-red-300';
                case 'aborted': return 'bg-orange-900/30 border border-orange-700 text-orange-300';
                default: return 'bg-gray-700 border border-gray-600 text-gray-300';
            }
        },

        init() {
            // Initialize shared helpers (used for polling, scroll, log dedup)
            this._wsBase = new WebSocketBase(
                '/ws/deployment',
                '/api/deployment/status',
                '/api/deployment/logs',
                { logBufferMax: 5000, logBufferKeep: 4000 }
            );
            this._wsBase.bind(this);

            // Initialize steps with default status
            this.steps = this.stepDefinitions.map(step => ({
                ...step,
                status: 'pending',
                started_at: null,
                completed_at: null,
                error_message: null
            }));

            // Connect to WebSocket (supplementary real-time updates)
            this.connectWebSocket();

            // Load initial status
            this.loadStatus();
        },

        // =================================================================
        // REST Polling (primary log delivery — reliable)
        // =================================================================

        startPolling() {
            this._wsBase.startPolling();
        },

        stopPolling() {
            this._wsBase.stopPolling();
        },

        // Page-specific poll status handler (called by WebSocketBase.pollUpdates)
        onPollStatus(statusData) {
            if (statusData.deployment && statusData.deployment.steps) {
                statusData.deployment.steps.forEach(s => {
                    const step = this.steps.find(st => st.id === s.id);
                    if (step) {
                        step.status = s.status;
                        step.started_at = s.started_at;
                        step.completed_at = s.completed_at;
                        step.error_message = s.error_message;
                    }
                });
                this.currentStep = statusData.current_step;
            }
            this.isRunning = statusData.is_running;
        },

        // Called by WebSocketBase when polling detects the run finished
        onPollComplete() {
            const wasCleaning = this.status === 'cleaning';
            this.stopPolling();
            this.stopElapsedTimer();
            if (wasCleaning) {
                this.status = 'idle';
                this.isRunning = false;
                this.steps.forEach(s => {
                    s.status = 'pending';
                    s.started_at = null;
                    s.completed_at = null;
                    s.error_message = null;
                });
            }
        },

        // =================================================================
        // WebSocket (supplementary — lower latency when connected)
        // =================================================================

        connectWebSocket() {
            this.ws = new DeploymentWebSocket({
                onConnect: () => {
                    this.wsConnected = true;
                },
                onDisconnect: () => {
                    this.wsConnected = false;
                },
                onInitialState: (data) => {
                    this.status = data.status;
                    this.currentStep = data.current_step;
                    this.isRunning = data.status === 'running';

                    if (data.steps && data.steps.length > 0) {
                        data.steps.forEach(s => {
                            const step = this.steps.find(st => st.id === s.id);
                            if (step) {
                                Object.assign(step, s);
                            }
                        });
                    }

                    // Load existing logs when reconnecting
                    if (data.logs && data.logs.length > 0) {
                        this.logs = data.logs;
                        this.scrollToBottom();
                    }

                    if (this.isRunning) {
                        this.startElapsedTimer();
                        this.startPolling();
                    }
                },
                onLog: (data) => {
                    this._wsBase.addLog(data);
                },
                onStepUpdate: (data) => {
                    const step = this.steps.find(s => s.id === data.step_id);
                    if (step) {
                        step.status = data.status;
                        step.started_at = data.started_at;
                        step.completed_at = data.completed_at;
                        step.error_message = data.error_message;
                    }

                    // Update running status
                    if (data.status === 'running') {
                        this.currentStep = data.step_id;
                        this.isRunning = true;
                        this.status = 'running';
                        this.expandedSteps = [...this.expandedSteps, data.step_id];
                    } else if (data.status === 'failed') {
                        this.status = 'failed';
                        this.isRunning = false;
                        this.stopElapsedTimer();
                        this.stopPolling();
                    } else if (data.status === 'success' && data.step_id === this.steps.length - 1) {
                        // Last step completed
                        this.status = 'completed';
                        this.isRunning = false;
                        this.stopElapsedTimer();
                        this.stopPolling();
                    }
                }
            });

            this.ws.connect();
        },

        scrollToBottom() {
            this._wsBase.scrollToBottom();
        },

        // =================================================================
        // Status + Actions
        // =================================================================

        async loadStatus() {
            try {
                const response = await fetch('/api/deployment/status');
                const data = await response.json();

                // Detect cleanup: is_running but no deployment (status=idle)
                if (data.is_running && data.status === 'idle' && !data.deployment) {
                    this.status = 'cleaning';
                } else {
                    this.status = data.status;
                }

                this.currentStep = data.current_step;
                this.isRunning = data.is_running;

                if (data.deployment && data.deployment.steps) {
                    data.deployment.steps.forEach(s => {
                        const step = this.steps.find(st => st.id === s.id);
                        if (step) {
                            Object.assign(step, s);
                        }
                    });
                }

                if (this.isRunning) {
                    this.startElapsedTimer();
                    this.startPolling();
                }
            } catch (e) {
                console.error('Failed to load status:', e);
            }
        },

        async startDeployment() {
            if (this.isRunning) return;

            if (!confirm('Are you sure you want to start the deployment?')) return;

            try {
                const response = await fetch('/api/deployment/start', { method: 'POST' });
                if (response.ok) {
                    this.status = 'running';
                    this.isRunning = true;
                    this.logs = [];
                    this._wsBase.resetLogOffset();
                    this.startTime = new Date();
                    this.startElapsedTimer();
                    this.startPolling();

                    // Reset steps
                    this.steps.forEach(s => {
                        s.status = 'pending';
                        s.started_at = null;
                        s.completed_at = null;
                        s.error_message = null;
                    });
                } else {
                    const error = await response.json();
                    alert('Failed to start deployment: ' + error.detail);
                }
            } catch (e) {
                alert('Failed to start deployment: ' + e.message);
            }
        },

        async abortDeployment() {
            if (!this.isRunning) return;

            if (!confirm('Are you sure you want to abort the deployment?')) return;

            try {
                const response = await fetch('/api/deployment/abort', { method: 'POST' });
                if (response.ok) {
                    this.status = 'aborted';
                    this.isRunning = false;
                    this.stopElapsedTimer();
                    this.stopPolling();
                }
            } catch (e) {
                alert('Failed to abort deployment: ' + e.message);
            }
        },

        async resumeDeployment(fromStep) {
            if (this.isRunning) return;

            if (!confirm('Resume deployment from where it left off?')) return;

            try {
                let url = '/api/deployment/resume';
                if (fromStep !== undefined) url += `?from_step=${fromStep}`;
                const response = await fetch(url, { method: 'POST' });
                if (response.ok) {
                    this.status = 'running';
                    this.isRunning = true;
                    this.startTime = new Date();
                    this.startElapsedTimer();
                    this.startPolling();
                    // Note: logs are NOT cleared — append mode
                } else {
                    const error = await response.json();
                    alert('Failed to resume deployment: ' + error.detail);
                }
            } catch (e) {
                alert('Failed to resume deployment: ' + e.message);
            }
        },

        async skipStep(stepId) {
            if (this.isRunning) return;

            const step = this.steps.find(s => s.id === stepId);
            const stepName = step ? step.description : `Step ${stepId}`;
            if (!confirm(`Skip "${stepName}" and continue deployment?`)) return;

            try {
                const response = await fetch(`/api/deployment/skip-step?step_id=${stepId}`, { method: 'POST' });
                if (response.ok) {
                    // Step will be marked skipped and deployment will resume
                    if (step) step.status = 'skipped';
                    this.status = 'running';
                    this.isRunning = true;
                    this.startTime = new Date();
                    this.startElapsedTimer();
                    this.startPolling();
                } else {
                    const error = await response.json();
                    alert('Failed to skip step: ' + error.detail);
                }
            } catch (e) {
                alert('Failed to skip step: ' + e.message);
            }
        },

        async runCleanup() {
            if (this.isRunning) return;

            if (!confirm('Are you sure you want to run cleanup? This will destroy all Terraform-managed resources.')) return;

            try {
                const response = await fetch('/api/deployment/cleanup', { method: 'POST' });

                let data;
                try {
                    data = await response.json();
                } catch {
                    alert('Cleanup request failed — check server logs.');
                    return;
                }

                if (response.ok) {
                    // Cleanup launched in background — switch to cleaning state
                    this.status = 'cleaning';
                    this.isRunning = true;
                    this.logs = [];
                    this._wsBase.resetLogOffset();
                    this.startTime = new Date();
                    this.startElapsedTimer();
                    this.startPolling();
                } else {
                    alert('Cleanup failed: ' + (data.detail || 'Unknown error'));
                }
            } catch (e) {
                alert('Failed to run cleanup: ' + e.message);
            }
        },

        // =================================================================
        // Timers
        // =================================================================

        startElapsedTimer() {
            if (!this.startTime) {
                this.startTime = new Date();
            }

            this.elapsedTimer = setInterval(() => {
                const elapsed = Math.floor((new Date() - this.startTime) / 1000);
                this.elapsedTime = formatElapsedTime(elapsed);
            }, 1000);
        },

        stopElapsedTimer() {
            if (this.elapsedTimer) {
                clearInterval(this.elapsedTimer);
                this.elapsedTimer = null;
            }
        },

        formatDuration(step) {
            if (!step.started_at) return '';

            const start = new Date(step.started_at);
            const end = step.completed_at ? new Date(step.completed_at) : new Date();
            const elapsed = Math.floor((end - start) / 1000);

            return formatElapsedTime(elapsed);
        },

        formatTime(timestamp) {
            return new Date(timestamp).toLocaleTimeString();
        },

        stepClass(step) {
            switch (step.status) {
                case 'running': return 'bg-yellow-900/20 border-l-4 border-yellow-500';
                case 'success': return 'bg-green-900/20 border-l-4 border-green-500';
                case 'failed': return 'bg-red-900/20 border-l-4 border-red-500';
                case 'skipped': return 'bg-yellow-900/10 border-l-4 border-yellow-600';
                default: return 'bg-gray-700/50';
            }
        },

        stepIconClass(step) {
            switch (step.status) {
                case 'running': return 'bg-yellow-900';
                case 'success': return 'bg-green-900';
                case 'failed': return 'bg-red-900';
                case 'skipped': return 'bg-yellow-900';
                default: return 'bg-gray-700';
            }
        },

        toggleStep(stepId) {
            const index = this.expandedSteps.indexOf(stepId);
            if (index === -1) {
                this.expandedSteps = [...this.expandedSteps, stepId];
            } else {
                this.expandedSteps = this.expandedSteps.filter((_, i) => i !== index);
            }
        },

        getStepLogs(stepId) {
            return this.logs.filter(l => l.step_id === stepId);
        },

        logClass(log) {
            return getLogLevelClass(log.level);
        },

        clearLogs() {
            this.logs = [];
            this._wsBase.resetLogOffset();
        }
    };
}
