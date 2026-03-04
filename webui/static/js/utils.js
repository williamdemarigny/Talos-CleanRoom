// Shared utility functions for all page components
// Loaded globally before page-specific JS files

/**
 * Format elapsed seconds into a human-readable duration string.
 * Returns "Xh Xm Xs" for hours, "Xm Xs" for minutes, or "Xs" for seconds-only.
 *
 * @param {number} seconds - Total elapsed seconds
 * @returns {string} Formatted duration string
 */
function formatElapsedTime(seconds) {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;

    const parts = [];
    if (hours > 0) parts.push(`${hours}h`);
    if (minutes > 0 || hours > 0) parts.push(`${minutes}m`);
    parts.push(`${secs}s`);

    return parts.join(' ');
}

/**
 * Return a Tailwind CSS class string for a log entry based on its level.
 *
 * Supported levels: 'error', 'warn'. Everything else gets default styling.
 *
 * @param {string} level - The log level string
 * @returns {string} Tailwind CSS classes
 */
function getLogLevelClass(level) {
    switch (level) {
        case 'error': return 'text-red-400';
        case 'warn':  return 'text-yellow-400';
        default:      return 'text-gray-300';
    }
}

/**
 * Return Tailwind CSS classes for a status banner based on the current status.
 *
 * Handles: 'running', 'completed', 'failed', 'aborted', and idle/default.
 *
 * @param {string} status - The status string
 * @returns {string} Tailwind CSS classes for background, border, and text color
 */
function getStatusBannerClass(status) {
    switch (status) {
        case 'running':   return 'bg-yellow-900/50 text-yellow-200';
        case 'completed': return 'bg-green-900/50 text-green-200';
        case 'failed':    return 'bg-red-900/50 text-red-200';
        case 'aborted':   return 'bg-orange-900/50 text-orange-200';
        default:          return 'bg-gray-700 text-gray-300';
    }
}

/**
 * Wrapper around fetch() with standardized error handling.
 * Returns a normalized result object { ok, data, error }.
 *
 * @param {string} url - The URL to fetch
 * @param {object} options - Standard fetch options (method, headers, body, etc.)
 * @returns {Promise<{ok: boolean, data: any|null, error: string|null}>}
 */
async function apiCall(url, options = {}) {
    try {
        const response = await fetch(url, options);
        const data = await response.json();
        if (response.ok) {
            return { ok: true, data, error: null };
        }
        return { ok: false, data, error: data.detail || `HTTP ${response.status}` };
    } catch (e) {
        return { ok: false, data: null, error: e.message };
    }
}
