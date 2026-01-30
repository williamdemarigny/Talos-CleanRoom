// Main application JavaScript

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
