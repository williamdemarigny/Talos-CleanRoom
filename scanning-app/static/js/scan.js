// Alpine.js component for the Security Scanner tab

function scanManager() {
    return {
        // Form state
        target: '',
        selectedTools: ['nmap'],
        profile: 'standard',

        // Custom module state (Metasploit)
        customModules: [],
        moduleCatalog: [],
        modulesLoaded: false,

        // Custom OpenVAS state
        openvasConfigs: [],
        openvasFamilies: [],
        selectedOpenvasConfig: null,
        selectedOpenvasFamilies: [],
        openvasCustomMode: 'preset',
        openvasDataLoaded: false,

        // Scan state
        status: 'idle',
        scanTarget: '',
        toolStates: [],
        logs: [],
        history: [],
        logFilter: null,

        // Enrichment state
        enrichmentStatus: 'idle',
        enrichmentProgress: 0,
        enrichmentTotal: 0,

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

        profileDescriptions: {
            'quick': 'Fast discovery scan. Best for initial reconnaissance.',
            'standard': 'Service detection + vulnerability scanning. Recommended for most assessments.',
            'thorough': 'Full port scan + comprehensive vulnerability checks. Slowest but most complete.',
            'custom': 'Choose individual Metasploit modules and OpenVAS scan configuration. Configure each tool below.'
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
                    'Metasploit': 'db_nmap top 1000 ports + 11 vulnerability modules: EternalBlue (MS17-010), Conficker (MS08-067), BlueKeep (CVE-2019-0708), Heartbleed (CVE-2014-0160), Log4Shell (CVE-2021-44228), Shellshock (CVE-2014-6271), HTTP.sys (MS15-034), SMB/SSH/HTTP version detection, FTP anonymous access',
                }
            },
            'thorough': {
                time: '1-3 hours',
                tools: {
                    'Nmap': 'All 65535 ports + aggressive OS/service detection (-sV -sC -p- -A)',
                    'OpenVAS': 'Full and Deep scan config (exhaustive NVT checks)',
                    'Metasploit': 'db_nmap top 1000 ports + 39 vulnerability modules: all Standard modules plus SMB share/user/pipe enumeration, RDP scanning, SSH user enumeration, HTTP directory brute-force/robots.txt/PUT/Tomcat/WordPress/Jenkins/WebDAV, SSL/TLS analysis, SMTP/POP3, MySQL/PostgreSQL/MSSQL/MongoDB/Redis, Telnet, SNMP, NetBIOS, UDP sweep, VNC no-auth',
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

        get customSelectionIncomplete() {
            if (this.profile !== 'custom') return false;
            // Check Metasploit: need at least one module
            if (this.selectedTools.includes('metasploit') && this.customModules.length === 0) {
                return true;
            }
            // Check OpenVAS: need a config selected or at least one family
            if (this.selectedTools.includes('openvas')) {
                if (this.openvasCustomMode === 'preset' && !this.selectedOpenvasConfig) {
                    return true;
                }
                if (this.openvasCustomMode === 'families' && this.selectedOpenvasFamilies.length === 0) {
                    return true;
                }
            }
            return false;
        },

        get statusBannerClass() {
            return getStatusBannerClass(this.status);
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
            // Initialize shared helpers
            this._wsBase = new WebSocketBase(
                '/api/scan/ws',
                '/api/scan/status',
                '/api/scan/logs',
                { pingInterval: 15000 }
            );
            this._wsBase.bind(this);

            this._wsBase.connectWebSocket();
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
            this._wsBase.startPolling();
        },

        stopPolling() {
            this._wsBase.stopPolling();
        },

        // Page-specific poll status handler (called by WebSocketBase.pollUpdates)
        onPollStatus(statusData) {
            if (statusData.scan) {
                this.scanTarget = statusData.scan.target || '';
                this.toolStates = statusData.scan.tools || [];
            }
        },

        // Called by WebSocketBase when polling detects the run finished
        onPollComplete() {
            this.stopPolling();
            this.stopTimer();
            this.fetchHistory();
        },

        // =================================================================
        // WebSocket (supplementary — lower latency when connected)
        // =================================================================

        // Page-specific message handler (called by WebSocketBase)
        onWsMessage(message) {
            switch (message.type) {
                case 'scan_initial_state':
                    this.handleInitialState(message.data);
                    break;
                case 'scan_log':
                    this._wsBase.addLog(message.data);
                    break;
                case 'scan_tool_update':
                    this.handleToolUpdate(message.data);
                    break;
                case 'enrichment_update':
                    this.handleEnrichmentUpdate(message.data);
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

        handleEnrichmentUpdate(data) {
            this.enrichmentStatus = data.status || 'idle';
            this.enrichmentProgress = data.progress || 0;
            this.enrichmentTotal = data.total || 0;
            if (data.status === 'completed') {
                this.enrichmentStatus = 'completed';
            }
        },

        scrollToBottom() {
            this._wsBase.scrollToBottom();
        },

        // =================================================================
        // Scan Actions
        // =================================================================

        async startScan() {
            if (!this.target.trim() || this.selectedTools.length === 0) return;

            const payload = {
                target: this.target,
                tools: this.selectedTools,
                profile: this.profile
            };
            if (this.profile === 'custom' && this.customModules.length > 0) {
                payload.custom_modules = this.customModules;
            }
            if (this.profile === 'custom' && this.selectedTools.includes('openvas')) {
                if (this.openvasCustomMode === 'preset' && this.selectedOpenvasConfig) {
                    payload.openvas_config = this.selectedOpenvasConfig;
                } else if (this.openvasCustomMode === 'families' && this.selectedOpenvasFamilies.length > 0) {
                    payload.openvas_families = this.selectedOpenvasFamilies;
                }
            }

            try {
                const response = await authFetch('/api/scan/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
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
                const response = await authFetch('/api/scan/abort', { method: 'POST' });
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
                const response = await authFetch('/api/scan/status');
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
                const response = await authFetch('/api/scan/history');
                const data = await response.json();
                this.history = data.history || [];
            } catch (e) {
                console.error('Failed to fetch scan history:', e);
            }
        },

        // =================================================================
        // Custom Module Selection
        // =================================================================

        async fetchModules() {
            if (this.modulesLoaded) return;
            try {
                const response = await fetch('/api/scan/modules');
                const data = await response.json();
                this.moduleCatalog = data.modules || [];
                this.modulesLoaded = true;
            } catch (e) {
                console.error('Failed to fetch module catalog:', e);
            }
        },

        get moduleCategories() {
            const cats = [];
            for (const mod of this.moduleCatalog) {
                if (!cats.includes(mod.category)) {
                    cats.push(mod.category);
                }
            }
            return cats;
        },

        categoryModules(category) {
            return this.moduleCatalog.filter(m => m.category === category);
        },

        toggleModule(moduleId) {
            const idx = this.customModules.indexOf(moduleId);
            if (idx >= 0) {
                this.customModules.splice(idx, 1);
            } else {
                this.customModules.push(moduleId);
            }
        },

        selectCategory(category) {
            const mods = this.categoryModules(category);
            for (const mod of mods) {
                if (!this.customModules.includes(mod.id)) {
                    this.customModules.push(mod.id);
                }
            }
        },

        deselectCategory(category) {
            const ids = this.categoryModules(category).map(m => m.id);
            this.customModules = this.customModules.filter(id => !ids.includes(id));
        },

        loadPreset(preset) {
            this.customModules = this.moduleCatalog
                .filter(m => m.profiles.includes(preset))
                .map(m => m.id);
        },

        // =================================================================
        // OpenVAS Custom Configuration
        // =================================================================

        async fetchOpenvasData() {
            if (this.openvasDataLoaded) return;
            try {
                const [configResp, familyResp] = await Promise.all([
                    fetch('/api/scan/openvas-configs'),
                    fetch('/api/scan/openvas-families')
                ]);
                const configData = await configResp.json();
                const familyData = await familyResp.json();
                this.openvasConfigs = configData.configs || [];
                this.openvasFamilies = familyData.families || [];
                this.openvasDataLoaded = true;
            } catch (e) {
                console.error('Failed to fetch OpenVAS data:', e);
            }
        },

        toggleOpenvasFamily(name) {
            const idx = this.selectedOpenvasFamilies.indexOf(name);
            if (idx >= 0) {
                this.selectedOpenvasFamilies.splice(idx, 1);
            } else {
                this.selectedOpenvasFamilies.push(name);
            }
        },

        // =================================================================
        // Timers
        // =================================================================

        startTimer() {
            this.stopTimer();
            this.timerInterval = setInterval(() => {
                if (this.startTime) {
                    const elapsed = Math.floor((new Date() - this.startTime) / 1000);
                    this.elapsedTime = formatElapsedTime(elapsed);
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
            return getLogLevelClass(log.level);
        },

        formatTime(timestamp) {
            if (!timestamp) return '';
            const d = new Date(timestamp);
            return d.toLocaleTimeString('en-US', { hour12: false });
        }
    }
}
