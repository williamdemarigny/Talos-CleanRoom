// Shared application JavaScript for all Talos CleanRoom apps.
// Provides auth helpers, fetch wrappers, and formatting utilities.

// --- One-time code auto-redeem ---
// If the URL contains a ?code= parameter (from portal cross-domain auth),
// redeem it for a local JWT, store it, and strip the code from the URL.
(async function autoRedeemCode() {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    if (!code) return;

    try {
        const response = await fetch('/api/auth/redeem-code', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code: code })
        });

        if (response.ok) {
            const data = await response.json();
            localStorage.setItem('access_token', data.access_token);
            // Strip the code from URL (no page reload)
            params.delete('code');
            const cleanUrl = params.toString()
                ? `${window.location.pathname}?${params}`
                : window.location.pathname;
            history.replaceState(null, '', cleanUrl);
        } else {
            console.error('Code redemption failed:', response.status);
            // Code expired or invalid — redirect to login
            window.location.href = '/login';
        }
    } catch (e) {
        console.error('Code redemption error:', e);
    }
})();

// Logout function
async function logout() {
    try {
        await fetch('/api/auth/logout', { method: 'POST' });
        localStorage.removeItem('access_token');
        window.location.href = '/login';
    } catch (e) {
        console.error('Logout failed:', e);
        window.location.href = '/login';
    }
}

// Get auth token from storage
function getToken() {
    return localStorage.getItem('access_token');
}

// Add auth header to fetch requests
async function authFetch(url, options = {}) {
    const token = getToken();
    if (token) {
        options.headers = options.headers || {};
        options.headers['Authorization'] = `Bearer ${token}`;
    }
    const response = await fetch(url, options);
    if (response.status === 401) {
        window.location.href = '/login';
        throw new Error('Unauthorized');
    }
    return response;
}

// Format duration from seconds
function formatDuration(seconds) {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);

    const parts = [];
    if (hours > 0) parts.push(`${hours}h`);
    if (minutes > 0) parts.push(`${minutes}m`);
    parts.push(`${secs}s`);

    return parts.join(' ');
}

// Format timestamp
function formatTimestamp(isoString) {
    const date = new Date(isoString);
    return date.toLocaleString();
}

// Format time only
function formatTimeOnly(isoString) {
    const date = new Date(isoString);
    return date.toLocaleTimeString();
}
