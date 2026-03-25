/* API client — fetch wrapper for dashboard endpoints */

const API = {
    async get(path) {
        const res = await fetch(`/api${path}`);
        if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
        return res.json();
    },

    async post(path, body) {
        const res = await fetch(`/api${path}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
        return res.json();
    },

    // Research
    getCycles: (limit = 20) => API.get(`/cycles?limit=${limit}`),
    getCycle: (id) => API.get(`/cycles/${id}`),

    // Failures
    getFailures: (params = {}) => {
        const qs = new URLSearchParams(params).toString();
        return API.get(`/failures${qs ? '?' + qs : ''}`);
    },
    getFailureStats: () => API.get('/failures/stats'),
    getFailure: (id) => API.get(`/failures/${id}`),

    // Benchmarks
    getBenchmarks: () => API.get('/benchmarks'),
    getBenchmark: (id) => API.get(`/benchmarks/${id}`),
    getComparisons: () => API.get('/benchmarks/comparisons'),

    // Attacks
    getAttackScans: () => API.get('/attacks/scans'),
    getAttackScan: (id) => API.get(`/attacks/scans/${id}`),
    getProbes: (category) => API.get(`/attacks/probes${category ? '?category=' + category : ''}`),

    // Settings
    getSettings: () => API.get('/settings'),
    getGlobalStats: () => API.get('/settings/stats'),
};
