/* Chart.js wrapper functions */

const COLORS = {
    S0: '#34d399', S1: '#fbbf24', S2: '#fb923c', S3: '#f87171', S4: '#ff4444',
    accent: '#6c7bf7',
    palette: ['#6c7bf7', '#34d399', '#fbbf24', '#fb923c', '#f87171', '#a78bfa', '#38bdf8', '#f472b6'],
};

const Charts = {
    _instances: {},

    destroy(id) {
        if (this._instances[id]) {
            this._instances[id].destroy();
            delete this._instances[id];
        }
    },

    severityPie(canvasId, distribution) {
        this.destroy(canvasId);
        const ctx = document.getElementById(canvasId);
        if (!ctx) return;
        const labels = ['S0', 'S1', 'S2', 'S3', 'S4'];
        const data = labels.map(s => distribution[s] || 0);
        const colors = labels.map(s => COLORS[s]);

        this._instances[canvasId] = new Chart(ctx, {
            type: 'doughnut',
            data: { labels, datasets: [{ data, backgroundColor: colors, borderWidth: 0 }] },
            options: {
                responsive: true,
                plugins: {
                    legend: { position: 'bottom', labels: { color: '#8b8fa3', font: { size: 11 } } },
                },
            },
        });
    },

    classBar(canvasId, byClass) {
        this.destroy(canvasId);
        const ctx = document.getElementById(canvasId);
        if (!ctx) return;
        const labels = Object.keys(byClass);
        const data = Object.values(byClass);

        this._instances[canvasId] = new Chart(ctx, {
            type: 'bar',
            data: {
                labels,
                datasets: [{ data, backgroundColor: COLORS.palette.slice(0, labels.length), borderWidth: 0 }],
            },
            options: {
                responsive: true,
                indexAxis: 'y',
                plugins: { legend: { display: false } },
                scales: {
                    x: { ticks: { color: '#8b8fa3' }, grid: { color: '#2a2e3f' } },
                    y: { ticks: { color: '#8b8fa3' }, grid: { display: false } },
                },
            },
        });
    },

    metricsBar(canvasId, metrics) {
        this.destroy(canvasId);
        const ctx = document.getElementById(canvasId);
        if (!ctx) return;
        const labels = Object.keys(metrics);
        const data = Object.values(metrics);

        this._instances[canvasId] = new Chart(ctx, {
            type: 'bar',
            data: {
                labels,
                datasets: [{ data, backgroundColor: COLORS.accent, borderWidth: 0 }],
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: {
                    x: { ticks: { color: '#8b8fa3', font: { size: 10 } }, grid: { color: '#2a2e3f' } },
                    y: { ticks: { color: '#8b8fa3' }, grid: { color: '#2a2e3f' } },
                },
            },
        });
    },
};
