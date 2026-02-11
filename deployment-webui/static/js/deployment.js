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

        // Step definitions
        stepDefinitions: [
            { id: 0, name: 'validate_git', description: 'Validate Git Repository' },
            { id: 1, name: 'check_dependencies', description: 'Check Dependencies' },
            { id: 2, name: 'terraform_deploy', description: 'Terraform Deploy' },
            { id: 3, name: 'generate_talos_config', description: 'Generate Talos Config' },
            { id: 4, name: 'apply_talos_configs', description: 'Apply Talos Configurations' },
            { id: 5, name: 'verify_cluster_health', description: 'Verify Cluster Health' },
            { id: 6, name: 'get_kubeconfig', description: 'Get Kubeconfig' },
            { id: 7, name: 'install_argocd', description: 'Install ArgoCD' },
            { id: 8, name: 'deploy_infrastructure', description: 'Deploy Infrastructure Stack' },
            { id: 9, name: 'argocd_self_management', description: 'Enable ArgoCD Self-Management' },
            { id: 10, name: 'deploy_openvas', description: 'Deploy OpenVAS' },
            { id: 11, name: 'deploy_faraday', description: 'Deploy Faraday' },
            { id: 12, name: 'deploy_metasploit', description: 'Deploy Metasploit' },
            { id: 13, name: 'deploy_threat_dragon', description: 'Deploy Threat Dragon' },
        ],

        get statusText() {
            switch (this.status) {
                case 'running': return 'Deployment in Progress';
                case 'completed': return 'Deployment Completed';
                case 'failed': return 'Deployment Failed';
                case 'aborted': return 'Deployment Aborted';
                default: return 'Ready to Deploy';
            }
        },

        get statusBannerClass() {
            switch (this.status) {
                case 'running': return 'bg-yellow-900/30 border border-yellow-700 text-yellow-300';
                case 'completed': return 'bg-green-900/30 border border-green-700 text-green-300';
                case 'failed': return 'bg-red-900/30 border border-red-700 text-red-300';
                case 'aborted': return 'bg-orange-900/30 border border-orange-700 text-orange-300';
                default: return 'bg-gray-700 border border-gray-600 text-gray-300';
            }
        },

        init() {
            // Initialize steps with default status
            this.steps = this.stepDefinitions.map(step => ({
                ...step,
                status: 'pending',
                started_at: null,
                completed_at: null,
                error_message: null
            }));

            // Connect to WebSocket
            this.connectWebSocket();

            // Load initial status
            this.loadStatus();
        },

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
                        // Auto-scroll to bottom after loading logs
                        if (this.autoScroll) {
                            this.$nextTick(() => {
                                const container = this.$refs.logContainer;
                                if (container) {
                                    container.scrollTop = container.scrollHeight;
                                }
                            });
                        }
                    }

                    if (this.isRunning) {
                        this.startElapsedTimer();
                    }
                },
                onLog: (data) => {
                    this.logs.push(data);
                    if (this.autoScroll) {
                        this.$nextTick(() => {
                            const container = this.$refs.logContainer;
                            if (container) {
                                container.scrollTop = container.scrollHeight;
                            }
                        });
                    }
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
                        this.expandedSteps.push(data.step_id);
                    } else if (data.status === 'failed') {
                        this.status = 'failed';
                        this.isRunning = false;
                        this.stopElapsedTimer();
                    } else if (data.status === 'success' && data.step_id === 13) {
                        // Last step completed
                        this.status = 'completed';
                        this.isRunning = false;
                        this.stopElapsedTimer();
                    }
                }
            });

            this.ws.connect();
        },

        async loadStatus() {
            try {
                const response = await fetch('/api/deployment/status');
                const data = await response.json();
                this.status = data.status;
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
                    this.startTime = new Date();
                    this.startElapsedTimer();

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
                }
            } catch (e) {
                alert('Failed to abort deployment: ' + e.message);
            }
        },

        async runCleanup() {
            if (this.isRunning) return;

            if (!confirm('Are you sure you want to run cleanup? This will destroy all Terraform-managed resources.')) return;

            try {
                const response = await fetch('/api/deployment/cleanup', { method: 'POST' });
                const data = await response.json();
                if (response.ok) {
                    alert(data.message);
                    // Reset status after cleanup
                    this.status = 'idle';
                    this.steps.forEach(s => {
                        s.status = 'pending';
                        s.started_at = null;
                        s.completed_at = null;
                        s.error_message = null;
                    });
                } else {
                    alert('Cleanup failed: ' + data.detail);
                }
            } catch (e) {
                alert('Failed to run cleanup: ' + e.message);
            }
        },

        startElapsedTimer() {
            if (!this.startTime) {
                this.startTime = new Date();
            }

            this.elapsedTimer = setInterval(() => {
                const elapsed = Math.floor((new Date() - this.startTime) / 1000);
                this.elapsedTime = this.formatSeconds(elapsed);
            }, 1000);
        },

        stopElapsedTimer() {
            if (this.elapsedTimer) {
                clearInterval(this.elapsedTimer);
                this.elapsedTimer = null;
            }
        },

        formatSeconds(seconds) {
            const hours = Math.floor(seconds / 3600);
            const minutes = Math.floor((seconds % 3600) / 60);
            const secs = seconds % 60;

            const parts = [];
            if (hours > 0) parts.push(`${hours}h`);
            if (minutes > 0 || hours > 0) parts.push(`${minutes}m`);
            parts.push(`${secs}s`);

            return parts.join(' ');
        },

        formatDuration(step) {
            if (!step.started_at) return '';

            const start = new Date(step.started_at);
            const end = step.completed_at ? new Date(step.completed_at) : new Date();
            const elapsed = Math.floor((end - start) / 1000);

            return this.formatSeconds(elapsed);
        },

        formatTime(timestamp) {
            return new Date(timestamp).toLocaleTimeString();
        },

        stepClass(step) {
            switch (step.status) {
                case 'running': return 'bg-yellow-900/20 border-l-4 border-yellow-500';
                case 'success': return 'bg-green-900/20 border-l-4 border-green-500';
                case 'failed': return 'bg-red-900/20 border-l-4 border-red-500';
                default: return 'bg-gray-700/50';
            }
        },

        stepIconClass(step) {
            switch (step.status) {
                case 'running': return 'bg-yellow-900';
                case 'success': return 'bg-green-900';
                case 'failed': return 'bg-red-900';
                default: return 'bg-gray-700';
            }
        },

        toggleStep(stepId) {
            const index = this.expandedSteps.indexOf(stepId);
            if (index === -1) {
                this.expandedSteps.push(stepId);
            } else {
                this.expandedSteps.splice(index, 1);
            }
        },

        getStepLogs(stepId) {
            return this.logs.filter(l => l.step_id === stepId);
        },

        logClass(log) {
            switch (log.level) {
                case 'error': return 'text-red-400';
                case 'warn': return 'text-yellow-400';
                default: return 'text-gray-300';
            }
        },

        clearLogs() {
            this.logs = [];
        }
    };
}
