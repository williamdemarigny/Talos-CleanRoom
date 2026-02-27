// WebSocket client for real-time deployment updates

class DeploymentWebSocket {
    constructor(options = {}) {
        this.url = null;
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = options.maxReconnectAttempts || 10;
        this.reconnectDelay = options.reconnectDelay || 2000;
        this.pingInterval = null;
        this.connected = false;

        // Callbacks
        this.onConnect = options.onConnect || (() => {});
        this.onDisconnect = options.onDisconnect || (() => {});
        this.onMessage = options.onMessage || (() => {});
        this.onLog = options.onLog || (() => {});
        this.onStepUpdate = options.onStepUpdate || (() => {});
        this.onInitialState = options.onInitialState || (() => {});
        this.onError = options.onError || (() => {});
    }

    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const token = localStorage.getItem('access_token') || '';
        this.url = `${protocol}//${window.location.host}/ws/deployment?token=${token}`;

        try {
            this.ws = new WebSocket(this.url);

            this.ws.onopen = () => {
                console.log('WebSocket connected');
                this.connected = true;
                this.reconnectAttempts = 0;
                this.startPing();
                this.onConnect();
            };

            this.ws.onclose = (event) => {
                console.log('WebSocket disconnected:', event.code, event.reason);
                this.connected = false;
                this.stopPing();
                this.onDisconnect();

                // Attempt reconnect if not a normal closure
                if (event.code !== 1000 && event.code !== 4001) {
                    this.attemptReconnect();
                }
            };

            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                this.onError(error);
            };

            this.ws.onmessage = (event) => {
                try {
                    const message = JSON.parse(event.data);
                    this.handleMessage(message);
                } catch (e) {
                    console.error('Failed to parse WebSocket message:', e);
                }
            };
        } catch (e) {
            console.error('Failed to create WebSocket:', e);
            this.attemptReconnect();
        }
    }

    handleMessage(message) {
        this.onMessage(message);

        switch (message.type) {
            case 'initial_state':
                this.onInitialState(message.data);
                break;
            case 'log':
                this.onLog(message.data);
                break;
            case 'step_update':
                this.onStepUpdate(message.data);
                break;
            case 'started':
                console.log('Deployment started');
                break;
            case 'aborted':
                console.log('Deployment aborted');
                break;
            case 'pong':
                // Heartbeat response
                break;
            default:
                console.log('Unknown message type:', message.type);
        }
    }

    attemptReconnect() {
        this.reconnectAttempts++;
        // Cap delay at 10 seconds
        const delay = Math.min(this.reconnectDelay * this.reconnectAttempts, 10000);

        setTimeout(() => {
            this.connect();
        }, delay);
    }

    startPing() {
        this.stopPing();
        this.pingInterval = setInterval(() => {
            if (this.connected) {
                this.send({ type: 'ping' });
            }
        }, 15000);
    }

    stopPing() {
        if (this.pingInterval) {
            clearInterval(this.pingInterval);
            this.pingInterval = null;
        }
    }

    send(data) {
        if (this.connected && this.ws) {
            this.ws.send(JSON.stringify(data));
        }
    }

    startDeployment() {
        this.send({ type: 'start' });
    }

    abortDeployment() {
        this.send({ type: 'abort' });
    }

    disconnect() {
        this.stopPing();
        if (this.ws) {
            this.ws.close(1000, 'Client disconnect');
        }
    }
}
