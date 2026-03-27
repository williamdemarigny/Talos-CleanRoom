// Shared WebSocket + polling base class for Alpine.js page components.
//
// Usage inside an Alpine component:
//
//   init() {
//       this._wsBase = new WebSocketBase(
//           '/api/scan/ws',        // wsPath (relative, token appended automatically)
//           '/api/scan/status',    // pollStatusUrl
//           '/api/scan/logs',      // pollLogsUrl
//           { pollInterval: 3000, pingInterval: 15000 }
//       );
//       this._wsBase.bind(this);   // binds to the Alpine component
//       this._wsBase.connectWebSocket();
//   }
//
// The Alpine component must provide:
//   - this.ws           (will be set by the base)
//   - this.wsConnected  (will be set by the base)
//   - this.logs         (array - base appends to it)
//   - this.autoScroll   (boolean - controls auto-scroll)
//   - this.$refs.logContainer  (DOM ref for scroll target)
//   - this.$nextTick    (Alpine built-in)
//   - this.onWsMessage(message)  — page-specific message handler
//   - this.onPollStatus(data)    — page-specific status poll handler
//   - this.onPollComplete()      — called when polling detects run finished (optional)

class WebSocketBase {
    /**
     * @param {string} wsPath         - WebSocket endpoint path (e.g. '/api/scan/ws')
     * @param {string} pollStatusUrl  - REST status endpoint
     * @param {string} pollLogsUrl    - REST logs endpoint
     * @param {object} options        - Optional overrides
     * @param {number} options.pollInterval  - Polling interval in ms (default 3000)
     * @param {number} options.pingInterval  - Ping/heartbeat interval in ms (default 30000)
     * @param {number} options.logBufferMax  - Max log entries before trimming (default 2000)
     * @param {number} options.logBufferKeep - Entries to keep after trim (default 1500)
     * @param {number} options.reconnectDelay - Base reconnect delay in ms (default 3000)
     */
    constructor(wsPath, pollStatusUrl, pollLogsUrl, options = {}) {
        this.wsPath = wsPath;
        this.pollStatusUrl = pollStatusUrl;
        this.pollLogsUrl = pollLogsUrl;

        this.pollIntervalMs = options.pollInterval || 3000;
        this.pingIntervalMs = options.pingInterval || 30000;
        this.logBufferMax = options.logBufferMax || 2000;
        this.logBufferKeep = options.logBufferKeep || 1500;
        this.reconnectDelay = options.reconnectDelay || 3000;

        // Internal interval IDs
        this._pollInterval = null;
        this._pingInterval = null;

        // Track how many logs have been fetched from the server (independent of
        // the in-memory buffer which may be trimmed).
        this._logOffset = 0;

        // The Alpine component reference (set via bind())
        this.component = null;
    }

    /**
     * Bind this helper to an Alpine component instance.
     * Must be called before any other method.
     *
     * @param {object} component - The Alpine component (typically `this` inside init())
     */
    bind(component) {
        this.component = component;
    }

    // =================================================================
    // REST Polling
    // =================================================================

    /**
     * Start periodic polling. Clears any existing interval first.
     */
    startPolling() {
        this.stopPolling();
        this._pollInterval = setInterval(() => this.pollUpdates(), this.pollIntervalMs);
    }

    /**
     * Stop periodic polling.
     */
    stopPolling() {
        if (this._pollInterval) {
            clearInterval(this._pollInterval);
            this._pollInterval = null;
        }
    }

    /**
     * Single poll cycle: fetches status + new logs, delegates to component handlers.
     */
    async pollUpdates() {
        const comp = this.component;
        if (!comp) return;

        try {
            // Fetch status (use authFetch for Bearer token auth)
            const statusResp = await authFetch(this.pollStatusUrl);
            const statusData = await statusResp.json();

            // Delegate status handling to the page component
            if (comp.onPollStatus) {
                comp.onPollStatus(statusData);
            }

            // Fetch logs (only new ones beyond what we have)
            const logResp = await authFetch(`${this.pollLogsUrl}?offset=${this._logOffset}`);
            const logData = await logResp.json();

            if (logData.logs && logData.logs.length > 0) {
                for (const log of logData.logs) {
                    comp.logs.push(log);
                }
                this._logOffset += logData.logs.length;
                this.scrollToBottom();
            }

            // Check if run finished
            const prevStatus = comp.status;
            comp.status = statusData.status;

            if (comp.onPollComplete && !statusData.is_running &&
                (prevStatus === 'running' || (comp.isRunningStatus && comp.isRunningStatus(prevStatus)))) {
                comp.onPollComplete();
            }
        } catch (e) {
            // Polling failure is non-fatal, will retry next interval
        }
    }

    // =================================================================
    // WebSocket
    // =================================================================

    /**
     * Connect to the WebSocket endpoint with auto-reconnect and heartbeat.
     */
    connectWebSocket() {
        const comp = this.component;
        if (!comp) return;

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const token = localStorage.getItem('access_token') || '';
        const url = `${protocol}//${window.location.host}${this.wsPath}?token=${token}`;

        try {
            comp.ws = new WebSocket(url);

            comp.ws.onopen = () => {
                comp.wsConnected = true;
                this.startPing();
            };

            comp.ws.onclose = (event) => {
                comp.wsConnected = false;
                this.stopPing();
                // Reconnect unless normal closure or auth failure
                if (event.code !== 1000 && event.code !== 4001) {
                    setTimeout(() => this.connectWebSocket(), this.reconnectDelay);
                }
            };

            comp.ws.onerror = () => {
                comp.wsConnected = false;
            };

            comp.ws.onmessage = (event) => {
                try {
                    const message = JSON.parse(event.data);
                    if (comp.onWsMessage) {
                        comp.onWsMessage(message);
                    }
                } catch (e) {
                    console.error('Failed to parse WebSocket message:', e);
                }
            };
        } catch (e) {
            console.error('Failed to create WebSocket:', e);
            setTimeout(() => this.connectWebSocket(), this.reconnectDelay);
        }
    }

    /**
     * Cleanly disconnect the WebSocket.
     */
    disconnectWebSocket() {
        const comp = this.component;
        this.stopPing();
        if (comp && comp.ws) {
            comp.ws.close(1000, 'Client disconnect');
            comp.ws = null;
            comp.wsConnected = false;
        }
    }

    // =================================================================
    // Heartbeat Ping
    // =================================================================

    /**
     * Start sending periodic ping messages over the WebSocket.
     *
     * @param {number} [interval] - Override the default ping interval (ms)
     */
    startPing(interval) {
        this.stopPing();
        const ms = interval || this.pingIntervalMs;
        this._pingInterval = setInterval(() => {
            const comp = this.component;
            if (comp && comp.ws && comp.ws.readyState === WebSocket.OPEN) {
                comp.ws.send(JSON.stringify({ type: 'ping' }));
            }
        }, ms);
    }

    /**
     * Stop the heartbeat ping interval.
     */
    stopPing() {
        if (this._pingInterval) {
            clearInterval(this._pingInterval);
            this._pingInterval = null;
        }
    }

    // =================================================================
    // Log Helpers
    // =================================================================

    /**
     * Reset the log poll offset (call when logs are cleared, e.g. new scan).
     */
    resetLogOffset() {
        this._logOffset = 0;
    }

    /**
     * Add a log entry with deduplication and buffer management.
     * Skips logs whose timestamp+message match an existing entry.
     *
     * @param {object} data - Log entry with at least { timestamp, message }
     */
    addLog(data) {
        const comp = this.component;
        if (!comp) return;

        // Deduplicate
        const isDupe = comp.logs.some(l =>
            l.timestamp === data.timestamp && l.message === data.message
        );
        if (isDupe) return;

        comp.logs.push(data);

        // Keep log buffer manageable
        if (comp.logs.length > this.logBufferMax) {
            comp.logs = comp.logs.slice(-this.logBufferKeep);
        }

        this.scrollToBottom();
    }

    /**
     * Auto-scroll the log container to the bottom if autoScroll is enabled.
     * Uses Alpine's $nextTick to wait for DOM update, and reads from $refs.logContainer.
     */
    scrollToBottom() {
        const comp = this.component;
        if (!comp || !comp.autoScroll) return;

        comp.$nextTick(() => {
            const container = comp.$refs.logContainer;
            if (container) {
                container.scrollTop = container.scrollHeight;
            }
        });
    }
}
