// Alpine.js component for the IOC Scanner tab

function iocScanManager() {
    return {
        // Form state
        target: '',
        mountType: 'ssh',
        scanPath: '/',
        // SSH
        sshUsername: 'root',
        sshPassword: '',
        // SMB
        smbShare: 'C$',
        smbUsername: '',
        smbPassword: '',
        smbDomain: 'WORKGROUP',
        // Advanced
        maxFileSizeMb: 64,
        scanArchives: true,
        showAdvanced: false,

        // Scan state
        status: 'idle',
        scanTarget: '',
        findings: [],
        alertsCount: 0,
        warningsCount: 0,
        noticesCount: 0,
        uploadedToFaraday: false,
        logs: [],
        history: [],
        findingsFilter: null,
        expandedFinding: null,

        // UI state
        autoScroll: true,
        wsConnected: false,
        ws: null,
        pollInterval: null,
        startTime: null,
        elapsedTime: '',
        timerInterval: null,

        // Shared helpers instance
        _wsBase: null,

        phases: [
            { id: 'mounting', label: 'Mounting' },
            { id: 'scanning', label: 'Scanning' },
            { id: 'parsing', label: 'Parsing' },
            { id: 'uploading', label: 'Uploading' }
        ],

        get isRunning() {
            return ['mounting', 'scanning', 'parsing', 'uploading'].includes(this.status);
        },

        get hasResults() {
            return ['completed', 'failed', 'aborted'].includes(this.status);
        },

        get totalFindings() {
            return this.findings.length;
        },

        get canStart() {
            if (!this.target.trim()) return false;
            if (this.mountType === 'ssh' && !this.sshUsername) return false;
            if (this.mountType === 'smb' && !this.smbShare) return false;
            return true;
        },

        get filteredFindings() {
            if (!this.findingsFilter) return this.findings;
            return this.findings.filter(f => f.severity === this.findingsFilter);
        },

        get statusBannerClass() {
            switch (this.status) {
                case 'mounting':
                case 'scanning':
                case 'parsing':
                case 'uploading':
                    return 'bg-yellow-900/50 text-yellow-200';
                case 'completed':
                    return this.alertsCount > 0
                        ? 'bg-red-900/50 text-red-200'
                        : 'bg-green-900/50 text-green-200';
                case 'failed':
                    return 'bg-red-900/50 text-red-200';
                case 'aborted':
                    return 'bg-orange-900/50 text-orange-200';
                default:
                    return 'bg-gray-700 text-gray-300';
            }
        },

        get statusText() {
            switch (this.status) {
                case 'idle': return 'Ready to scan';
                case 'mounting': return 'Mounting remote filesystem...';
                case 'scanning': return 'LOKI-RS scanning for IOCs...';
                case 'parsing': return 'Parsing results...';
                case 'uploading': return 'Uploading to Faraday...';
                case 'completed':
                    return this.alertsCount > 0
                        ? `INDICATORS DETECTED (${this.alertsCount} alert(s))`
                        : this.warningsCount > 0
                            ? `Suspicious objects found (${this.warningsCount} warning(s))`
                            : 'System appears clean';
                case 'failed': return 'Scan failed';
                case 'aborted': return 'Scan aborted';
                default: return this.status;
            }
        },

        async init() {
            // Initialize shared helpers
            this._wsBase = new WebSocketBase(
                '/api/ioc-scan/ws',
                '/api/ioc-scan/status',
                '/api/ioc-scan/logs',
                { pingInterval: 30000 }
            );
            this._wsBase.bind(this);

            this._wsBase.connectWebSocket();
            await this.fetchStatus();
            await this.fetchHistory();
            if (this.isRunning) {
                this.startPolling();
            }
        },

        // =================================================================
        // Phase Progress
        // =================================================================

        phaseClass(phaseId) {
            const phaseOrder = ['mounting', 'scanning', 'parsing', 'uploading'];
            const currentIdx = phaseOrder.indexOf(this.status);
            const phaseIdx = phaseOrder.indexOf(phaseId);

            if (this.status === phaseId) {
                return 'border border-yellow-500 text-yellow-300';
            } else if (currentIdx > phaseIdx || this.status === 'completed') {
                return 'border border-green-600 text-green-400';
            } else {
                return 'border border-gray-700 text-gray-500';
            }
        },

        phaseStatus(phaseId) {
            const phaseOrder = ['mounting', 'scanning', 'parsing', 'uploading'];
            const currentIdx = phaseOrder.indexOf(this.status);
            const phaseIdx = phaseOrder.indexOf(phaseId);

            if (this.status === phaseId) return 'In progress...';
            if (currentIdx > phaseIdx || this.status === 'completed') return 'Done';
            if (this.status === 'failed' || this.status === 'aborted') {
                if (currentIdx === phaseIdx) return 'Failed';
                if (currentIdx > phaseIdx) return 'Done';
                return 'Skipped';
            }
            return 'Pending';
        },

        // =================================================================
        // REST Polling
        // =================================================================

        startPolling() {
            this._wsBase.startPolling();
        },

        stopPolling() {
            this._wsBase.stopPolling();
        },

        // Page-specific poll status handler (called by WebSocketBase.pollUpdates)
        onPollStatus(statusData) {
            this.status = statusData.status || this.status;
            if (statusData.scan) {
                this.scanTarget = statusData.scan.target || '';
                this.alertsCount = statusData.scan.alerts_count || 0;
                this.warningsCount = statusData.scan.warnings_count || 0;
                this.noticesCount = statusData.scan.notices_count || 0;
                this.uploadedToFaraday = statusData.scan.uploaded_to_faraday || false;
                if (statusData.scan.findings) {
                    this.findings = statusData.scan.findings;
                }
            }
        },

        // Called by WebSocketBase when polling detects the run finished
        onPollComplete() {
            this.stopPolling();
            this.stopTimer();
            this.fetchHistory();
        },

        isRunningStatus(s) {
            return ['mounting', 'scanning', 'parsing', 'uploading'].includes(s);
        },

        // =================================================================
        // WebSocket
        // =================================================================

        // Page-specific message handler (called by WebSocketBase)
        onWsMessage(message) {
            switch (message.type) {
                case 'ioc_initial_state':
                    this.handleInitialState(message.data);
                    break;
                case 'ioc_log':
                    this._wsBase.addLog(message.data);
                    break;
                case 'ioc_status_update':
                    this.handleStatusUpdate(message.data);
                    break;
                case 'pong':
                    break;
            }
        },

        handleInitialState(data) {
            this.status = data.status || 'idle';
            this.scanTarget = data.target || '';
            this.alertsCount = data.alerts_count || 0;
            this.warningsCount = data.warnings_count || 0;
            this.noticesCount = data.notices_count || 0;
            this.uploadedToFaraday = data.uploaded_to_faraday || false;
            if (data.findings) {
                this.findings = data.findings;
            }
            if (data.logs && data.logs.length > 0) {
                this.logs = data.logs;
                this.scrollToBottom();
            }
            if (data.started_at && this.isRunningStatus(this.status)) {
                this.startTime = new Date(data.started_at);
                this.startTimer();
                this.startPolling();
            }
        },

        handleStatusUpdate(data) {
            this.status = data.status;
            this.alertsCount = data.alerts_count || 0;
            this.warningsCount = data.warnings_count || 0;
            this.noticesCount = data.notices_count || 0;
            this.uploadedToFaraday = data.uploaded_to_faraday || false;

            if (['completed', 'failed', 'aborted'].includes(data.status)) {
                this.fetchStatus();  // Get full findings
                this.fetchHistory();
                this.stopPolling();
                this.stopTimer();
            }
        },

        scrollToBottom() {
            this._wsBase.scrollToBottom();
        },

        // =================================================================
        // Scan Actions
        // =================================================================

        async startScan() {
            if (!this.canStart) return;

            // Client-side credential validation
            if (this.mountType === 'ssh') {
                if (!this.sshUsername) {
                    this.error = 'SSH username is required';
                    return;
                }
                if (!this.sshPassword) {
                    this.error = 'SSH password is required';
                    return;
                }
            } else if (this.mountType === 'smb') {
                if (!this.smbShare) {
                    this.error = 'SMB share name is required';
                    return;
                }
                if (!this.smbUsername || !this.smbPassword) {
                    this.error = 'SMB username and password are required';
                    return;
                }
            }

            const payload = {
                target: this.target,
                mount_type: this.mountType,
                scan_path: this.scanPath,
                max_file_size_mb: this.maxFileSizeMb,
                scan_archives: this.scanArchives
            };

            if (this.mountType === 'ssh') {
                payload.ssh_username = this.sshUsername;
                payload.ssh_password = this.sshPassword;
            } else {
                payload.smb_share = this.smbShare;
                payload.smb_username = this.smbUsername;
                payload.smb_password = this.smbPassword;
                payload.smb_domain = this.smbDomain;
            }

            try {
                const response = await authFetch('/api/ioc-scan/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                if (response.ok) {
                    this.status = 'mounting';
                    this.scanTarget = this.target;
                    this.logs = [];
                    this._wsBase.resetLogOffset();
                    this.findings = [];
                    this.alertsCount = 0;
                    this.warningsCount = 0;
                    this.noticesCount = 0;
                    this.uploadedToFaraday = false;
                    this.expandedFinding = null;
                    this.startTime = new Date();
                    this.startTimer();
                    this.startPolling();
                } else {
                    const error = await response.json();
                    alert('Failed to start IOC scan: ' + error.detail);
                }
            } catch (e) {
                alert('Failed to start IOC scan: ' + e.message);
            }
        },

        async abortScan() {
            if (!confirm('Are you sure you want to abort the IOC scan?')) return;

            try {
                const response = await authFetch('/api/ioc-scan/abort', { method: 'POST' });
                if (response.ok) {
                    this.status = 'aborted';
                    this.stopTimer();
                    this.stopPolling();
                    await this.fetchHistory();
                }
            } catch (e) {
                console.error('Failed to abort IOC scan:', e);
            }
        },

        resetScan() {
            this.status = 'idle';
            this.scanTarget = '';
            this.findings = [];
            this.alertsCount = 0;
            this.warningsCount = 0;
            this.noticesCount = 0;
            this.uploadedToFaraday = false;
            this.logs = [];
            this._wsBase.resetLogOffset();
            this.expandedFinding = null;
            this.stopTimer();
            this.stopPolling();
            this.elapsedTime = '';
        },

        async fetchStatus() {
            try {
                const response = await authFetch('/api/ioc-scan/status');
                const data = await response.json();
                this.status = data.status;
                if (data.scan) {
                    this.scanTarget = data.scan.target || '';
                    this.alertsCount = data.scan.alerts_count || 0;
                    this.warningsCount = data.scan.warnings_count || 0;
                    this.noticesCount = data.scan.notices_count || 0;
                    this.uploadedToFaraday = data.scan.uploaded_to_faraday || false;
                    if (data.scan.findings) {
                        this.findings = data.scan.findings;
                    }
                    if (data.scan.started_at && data.is_running) {
                        this.startTime = new Date(data.scan.started_at);
                        this.startTimer();
                    }
                    if (!data.is_running) {
                        this.stopTimer();
                    }
                }
            } catch (e) {
                console.error('Failed to fetch IOC scan status:', e);
            }
        },

        async fetchHistory() {
            try {
                const response = await authFetch('/api/ioc-scan/history');
                const data = await response.json();
                this.history = data.history || [];
            } catch (e) {
                console.error('Failed to fetch IOC scan history:', e);
            }
        },

        // =================================================================
        // UI Helpers
        // =================================================================

        toggleFinding(idx) {
            this.expandedFinding = this.expandedFinding === idx ? null : idx;
        },

        severityBadgeClass(severity) {
            switch (severity) {
                case 'alert': return 'bg-red-600 text-white';
                case 'warning': return 'bg-yellow-600 text-white';
                case 'notice': return 'bg-cyan-600 text-white';
                default: return 'bg-gray-600 text-white';
            }
        },

        logClass(log) {
            return getLogLevelClass(log.level);
        },

        formatTime(ts) {
            if (!ts) return '';
            const d = new Date(ts);
            return d.toLocaleTimeString();
        },

        // =================================================================
        // Timer
        // =================================================================

        startTimer() {
            this.stopTimer();
            this.updateElapsed();
            this.timerInterval = setInterval(() => this.updateElapsed(), 1000);
        },

        stopTimer() {
            if (this.timerInterval) {
                clearInterval(this.timerInterval);
                this.timerInterval = null;
            }
        },

        updateElapsed() {
            if (!this.startTime) return;
            const now = new Date();
            const diff = Math.floor((now - this.startTime) / 1000);
            this.elapsedTime = formatElapsedTime(diff);
        }
    };
}
