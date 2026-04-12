// Portal app JavaScript — auth helpers

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
