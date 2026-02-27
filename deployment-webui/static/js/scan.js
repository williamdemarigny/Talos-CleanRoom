// Alpine.js component for the Security Scanner tab

function scanManager() {
    return {
        // Form state
        target: '',
        selectedTools: ['nmap'],
        profile: 'standard',

        // Scan state
        status: 'idle',
        scanTarget: '',
        toolStates: [],
        logs: [],
        history: [],
        logFilter: null,

        // UI state
        autoScroll: true,
        wsConnected: false,
        ws: null,
        pingInterval: null,
        pollInterval: null,
        startTime: null,
        elapsedTime: '',
        timerInterval: null,

        profileDescriptions: {
            'quick': 'Fast discovery scan. Best for initial reconnaissance.',
            'standard': 'Service detection + vulnerability scanning. Recommended for most assessments.',
            'thorough': 'Full port scan + comprehensive vulnerability checks. Slowest but most complete.'
        },

        showProfileInfo: false,

        profileDetails: {
            'quick': {
                time: '5-15 minutes',
                tools: {
                    'Nmap': 'Top 100 ports, fast timing (-T4 --top-ports 100)',
                    'OpenVAS': 'Host discovery scan only',
                    'Metasploit': 'db_nmap discovery — no vulnerability modules',
                }
            },
            'standard': {
                time: '15-45 minutes',
                tools: {
                    'Nmap': 'Service version detection + default NSE scripts (-sV -sC)',
                    'OpenVAS': 'Full and Fast scan config (most common NVT checks)',
                    'Metasploit': 'db_nmap + 11 vulnerability modules: EternalBlue (MS17-010), Conficker (MS08-067), BlueKeep (CVE-2019-0708), Heartbleed (CVE-2014-0160), Log4Shell (CVE-2021-44228), Shellshock (CVE-2014-6271), HTTP.sys (MS15-034), SMB/SSH/HTTP version detection, FTP anonymous access',
                }
            },
            'thorough': {
                time: '1-3 hours',
                tools: {
                    'Nmap': 'All 65535 ports + aggressive OS/service detection (-sV -sC -p- -A)',
                    'OpenVAS': 'Full and Deep scan config (exhaustive NVT checks)',
                    'Metasploit': 'db_nmap full scan + 39 vulnerability modules: all Standard modules plus SMB share/user/pipe enumeration, RDP scanning, SSH user enumeration, HTTP directory brute-force/robots.txt/PUT/Tomcat/WordPress/Jenkins/WebDAV, SSL/TLS analysis, SMTP/POP3, MySQL/PostgreSQL/MSSQL/MongoDB/Redis, Telnet, SNMP, NetBIOS, UDP sweep, VNC no-auth',
                }
            }
        },

        get isRunning() {
            return this.status === 'running';
        },

        get completedTools() {
            return this.toolStates.filter(t => t.status === 'completed').length;
        },

        get uploadedTools() {
            return this.toolStates.filter(t => t.uploaded_to_faraday).length;
        },

        get filteredLogs() {
            if (!this.logFilter) return this.logs;
            return this.logs.filter(l => l.tool === this.logFilter || !l.tool);
        },

        get statusBannerClass() {
            switch (this.status) {
                case 'running': return 'bg-yellow-900/50 text-yellow-200';
                case 'completed': return 'bg-green-900/50 text-green-200';
                case 'failed': return 'bg-red-900/50 text-red-200';
                case 'aborted': return 'bg-orange-900/50 text-orange-200';
                default: return 'bg-gray-700 text-gray-300';
            }
        },

        get statusText() {
            switch (this.status) {
                case 'idle': return 'Ready to scan';
                case 'running': return 'Scan in progress...';
                case 'completed': return 'Scan completed';
                case 'failed': return 'Scan failed';
                case 'aborted': return 'Scan aborted';
                default: return this.status;
            }
        },

        async init() {
            this.connectWebSocket();
            await this.fetchStatus();
            await this.fetchHistory();
            // Start polling if a scan is already running
            if (this.isRunning) {
                this.startPolling();
            }
        },

        // =================================================================
        // REST Polling (primary log delivery — reliable)
        // =================================================================

        startPolling() {
            this.stopPolling();
            this.pollInterval = setInterval(() => this.pollUpdates(), 3000);
        },

        stopPolling() {
            if (this.pollInterval) {
                clearInterval(this.pollInterval);
                this.pollInterval = null;
            }
        },

        async pollUpdates() {
            try {
                // Fetch status + tool states
                const statusResp = await fetch('/api/scan/status');
                const statusData = await statusResp.json();

                if (statusData.scan) {
                    this.scanTarget = statusData.scan.target || '';
                    this.toolStates = statusData.scan.tools || [];
                }

                // Fetch logs (only new ones beyond what we have)
                const logResp = await fetch(`/api/scan/logs?offset=${this.logs.length}`);
                const logData = await logResp.json();

                if (logData.logs && logData.logs.length > 0) {
                    for (const log of logData.logs) {
                        this.logs.push(log);
                    }
                    this.scrollToBottom();
                }

                // Check if scan finished
                const prevStatus = this.status;
                this.status = statusData.status;

                if (prevStatus === 'running' && !statusData.is_running) {
                    this.stopPolling();
                    this.stopTimer();
                    await this.fetchHistory();
                }
            } catch (e) {
                // Polling failure is non-fatal, will retry next interval
            }
        },

        // =================================================================
        // WebSocket (supplementary — lower latency when connected)
        // =================================================================

        connectWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const token = localStorage.getItem('access_token') || '';
            const url = `${protocol}//${window.location.host}/api/scan/ws?token=${token}`;

            try {
                this.ws = new WebSocket(url);

                this.ws.onopen = () => {
                    this.wsConnected = true;
                    this.startPing();
                };

                this.ws.onclose = (event) => {
                    this.wsConnected = false;
                    this.stopPing();
                    // Reconnect unless normal closure or auth failure
                    if (event.code !== 1000 && event.code !== 4001) {
                        setTimeout(() => this.connectWebSocket(), 3000);
                    }
                };

                this.ws.onerror = () => {
                    this.wsConnected = false;
                };

                this.ws.onmessage = (event) => {
                    try {
                        const message = JSON.parse(event.data);
                        this.handleMessage(message);
                    } catch (e) {
                        console.error('Failed to parse scan WebSocket message:', e);
                    }
                };
            } catch (e) {
                console.error('Failed to create scan WebSocket:', e);
                setTimeout(() => this.connectWebSocket(), 3000);
            }
        },

        handleMessage(message) {
            switch (message.type) {
                case 'scan_initial_state':
                    this.handleInitialState(message.data);
                    break;
                case 'scan_log':
                    this.handleLog(message.data);
                    break;
                case 'scan_tool_update':
                    this.handleToolUpdate(message.data);
                    break;
                case 'pong':
                    break;
            }
        },

        handleInitialState(data) {
            this.status = data.status || 'idle';
            this.scanTarget = data.target || '';
            this.toolStates = data.tools || [];
            if (data.logs && data.logs.length > 0) {
                this.logs = data.logs;
                this.scrollToBottom();
            }
            if (data.started_at && this.status === 'running') {
                this.startTime = new Date(data.started_at);
                this.startTimer();
                this.startPolling();
            }
        },

        handleLog(data) {
            // Deduplicate: skip if we already have a log with same timestamp+message
            const isDupe = this.logs.some(l =>
                l.timestamp === data.timestamp && l.message === data.message
            );
            if (isDupe) return;

            this.logs.push(data);
            // Keep log buffer manageable
            if (this.logs.length > 2000) {
                this.logs = this.logs.slice(-1500);
            }
            this.scrollToBottom();
        },

        handleToolUpdate(data) {
            const idx = this.toolStates.findIndex(t => t.tool === data.tool);
            if (idx >= 0) {
                this.toolStates[idx] = { ...this.toolStates[idx], ...data };
            }
            // Check if scan completed (all tools done)
            const allDone = this.toolStates.every(t =>
                ['completed', 'failed', 'aborted'].includes(t.status)
            );
            if (allDone && this.status === 'running') {
                this.fetchStatus();
                this.fetchHistory();
                this.stopPolling();
                this.stopTimer();
            }
        },

        scrollToBottom() {
            if (this.autoScroll) {
                this.$nextTick(() => {
                    const container = this.$refs.logContainer;
                    if (container) {
                        container.scrollTop = container.scrollHeight;
                    }
                });
            }
        },

        // =================================================================
        // Scan Actions
        // =================================================================

        async startScan() {
            if (!this.target.trim() || this.selectedTools.length === 0) return;

            try {
                const response = await fetch('/api/scan/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        target: this.target,
                        tools: this.selectedTools,
                        profile: this.profile
                    })
                });

                if (response.ok) {
                    this.status = 'running';
                    this.scanTarget = this.target;
                    this.logs = [];
                    this.toolStates = this.selectedTools.map(t => ({
                        tool: t,
                        status: 'idle',
                        findings_count: 0,
                        uploaded_to_faraday: false,
                        error_message: null
                    }));
                    this.startTime = new Date();
                    this.startTimer();
                    this.startPolling();
                } else {
                    const error = await response.json();
                    alert('Failed to start scan: ' + error.detail);
                }
            } catch (e) {
                alert('Failed to start scan: ' + e.message);
            }
        },

        async abortScan() {
            if (!confirm('Are you sure you want to abort the scan?')) return;

            try {
                const response = await fetch('/api/scan/abort', { method: 'POST' });
                if (response.ok) {
                    this.status = 'aborted';
                    this.stopTimer();
                    this.stopPolling();
                    await this.fetchHistory();
                }
            } catch (e) {
                console.error('Failed to abort scan:', e);
            }
        },

        resetScan() {
            this.status = 'idle';
            this.scanTarget = '';
            this.toolStates = [];
            this.logs = [];
            this.stopTimer();
            this.stopPolling();
            this.elapsedTime = '';
        },

        async fetchStatus() {
            try {
                const response = await fetch('/api/scan/status');
                const data = await response.json();
                this.status = data.status;
                if (data.scan) {
                    this.scanTarget = data.scan.target || '';
                    this.toolStates = data.scan.tools || [];
                    if (data.scan.started_at && data.is_running) {
                        this.startTime = new Date(data.scan.started_at);
                        this.startTimer();
                    }
                    if (!data.is_running) {
                        this.stopTimer();
                    }
                }
            } catch (e) {
                console.error('Failed to fetch scan status:', e);
            }
        },

        async fetchHistory() {
            try {
                const response = await fetch('/api/scan/history');
                const data = await response.json();
                this.history = data.history || [];
            } catch (e) {
                console.error('Failed to fetch scan history:', e);
            }
        },

        // =================================================================
        // Timers
        // =================================================================

        startPing() {
            this.stopPing();
            this.pingInterval = setInterval(() => {
                if (this.wsConnected && this.ws) {
                    this.ws.send(JSON.stringify({ type: 'ping' }));
                }
            }, 15000);
        },

        stopPing() {
            if (this.pingInterval) {
                clearInterval(this.pingInterval);
                this.pingInterval = null;
            }
        },

        startTimer() {
            this.stopTimer();
            this.timerInterval = setInterval(() => {
                if (this.startTime) {
                    const elapsed = Math.floor((new Date() - this.startTime) / 1000);
                    const hours = Math.floor(elapsed / 3600);
                    const minutes = Math.floor((elapsed % 3600) / 60);
                    const seconds = elapsed % 60;
                    if (hours > 0) {
                        this.elapsedTime = `${hours}h ${minutes}m ${seconds}s`;
                    } else if (minutes > 0) {
                        this.elapsedTime = `${minutes}m ${seconds}s`;
                    } else {
                        this.elapsedTime = `${seconds}s`;
                    }
                }
            }, 1000);
        },

        stopTimer() {
            if (this.timerInterval) {
                clearInterval(this.timerInterval);
                this.timerInterval = null;
            }
        },

        logClass(log) {
            switch (log.level) {
                case 'error': return 'text-red-400';
                case 'warn': return 'text-yellow-400';
                default: return 'text-gray-300';
            }
        },

        formatTime(timestamp) {
            if (!timestamp) return '';
            const d = new Date(timestamp);
            return d.toLocaleTimeString('en-US', { hour12: false });
        }
    }
}
