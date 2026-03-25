/* Main dashboard application — page routing and rendering */

const App = {
    currentPage: 'dashboard',

    init() {
        document.querySelectorAll('[data-page]').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                this.navigate(link.dataset.page);
            });
        });
        this.navigate('dashboard');
    },

    navigate(page, params = {}) {
        this.currentPage = page;

        // Update nav
        document.querySelectorAll('[data-page]').forEach(a => a.classList.remove('active'));
        const activeLink = document.querySelector(`[data-page="${page}"]`);
        if (activeLink) activeLink.classList.add('active');

        // Update pages
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        const pageEl = document.getElementById(`page-${page}`);
        if (pageEl) pageEl.classList.add('active');

        // Load page data
        this.loadPage(page, params);
    },

    async loadPage(page, params) {
        try {
            switch (page) {
                case 'dashboard': return await this.loadDashboard();
                case 'cycles': return await this.loadCycles();
                case 'cycle-detail': return await this.loadCycleDetail(params.id);
                case 'failures': return await this.loadFailures();
                case 'failure-detail': return await this.loadFailureDetail(params.id);
                case 'benchmarks': return await this.loadBenchmarks();
                case 'attacks': return await this.loadAttacks();
                case 'settings': return await this.loadSettings();
            }
        } catch (err) {
            console.error(`Error loading ${page}:`, err);
        }
    },

    // ── Dashboard ──
    async loadDashboard() {
        const [stats, failStats, cycles] = await Promise.all([
            API.getGlobalStats(),
            API.getFailureStats(),
            API.getCycles(10),
        ]);

        document.getElementById('stat-cycles').textContent = stats.total_cycles;
        document.getElementById('stat-failures').textContent = stats.total_failures;
        document.getElementById('stat-benchmarks').textContent = stats.total_benchmarks;
        document.getElementById('stat-attacks').textContent = stats.total_attack_scans;

        Charts.severityPie('chart-severity', failStats.by_severity || {});
        Charts.classBar('chart-class', failStats.by_class || {});

        const tbody = document.getElementById('recent-cycles');
        tbody.innerHTML = cycles.length ? cycles.map(c => `
            <tr onclick="App.navigate('cycle-detail', {id:'${c.id}'})">
                <td>${c.started_at ? new Date(c.started_at).toLocaleDateString() : '-'}</td>
                <td>${esc(c.target || '-')}</td>
                <td>${esc(c.focus || '-')}</td>
                <td>${c.hypotheses_generated || 0}</td>
                <td>${c.failures_found || 0}</td>
                <td>${c.mode || '-'}</td>
            </tr>
        `).join('') : '<tr><td colspan="6" class="empty">No cycles yet</td></tr>';
    },

    // ── Cycles ──
    async loadCycles() {
        const cycles = await API.getCycles(50);
        const tbody = document.getElementById('cycles-table');
        tbody.innerHTML = cycles.length ? cycles.map(c => `
            <tr onclick="App.navigate('cycle-detail', {id:'${c.id}'})">
                <td>${c.id}</td>
                <td>${c.started_at ? new Date(c.started_at).toLocaleDateString() : '-'}</td>
                <td>${esc(c.target || '-')}</td>
                <td>${esc(c.focus || '-')}</td>
                <td>${c.hypotheses_generated || 0}</td>
                <td>${c.failures_found || 0}</td>
                <td>$${(c.total_cost_usd || 0).toFixed(2)}</td>
            </tr>
        `).join('') : '<tr><td colspan="7" class="empty">No cycles yet</td></tr>';
    },

    // ── Cycle detail ──
    async loadCycleDetail(cycleId) {
        if (!cycleId) return;
        const pageEl = document.getElementById('page-cycle-detail');
        pageEl.classList.add('active');
        document.getElementById('page-cycles').classList.remove('active');

        const data = await API.getCycle(cycleId);
        const c = data.cycle;

        document.getElementById('cycle-detail-content').innerHTML = `
            <span class="back-link" onclick="App.navigate('cycles')">&larr; Back to cycles</span>
            <h1>Cycle: ${c.id}</h1>
            <div class="stats-grid">
                <div class="stat-card"><div class="stat-value">${data.hypotheses.length}</div><div class="stat-label">Hypotheses</div></div>
                <div class="stat-card"><div class="stat-value">${data.failures.length}</div><div class="stat-label">Failures</div></div>
                <div class="stat-card"><div class="stat-value">${data.interventions.length}</div><div class="stat-label">Interventions</div></div>
                <div class="stat-card"><div class="stat-value">$${(c.total_cost_usd || 0).toFixed(2)}</div><div class="stat-label">Cost</div></div>
            </div>

            <h2>Hypotheses</h2>
            <table class="data-table"><thead><tr><th>ID</th><th>Description</th><th>Class</th><th>Severity</th><th>Status</th></tr></thead><tbody>
            ${data.hypotheses.map(h => `<tr><td>${h.id}</td><td>${esc(h.description)}</td><td>${h.failure_class}</td><td><span class="badge badge-${h.expected_severity.toLowerCase()}">${h.expected_severity}</span></td><td>${h.status}</td></tr>`).join('')}
            </tbody></table>

            <h2>Failures</h2>
            <table class="data-table"><thead><tr><th>ID</th><th>Class</th><th>Severity</th><th>Rate</th><th>Evidence</th></tr></thead><tbody>
            ${data.failures.map(f => `<tr onclick="App.navigate('failure-detail', {id:'${f.id}'})"><td>${f.id}</td><td>${f.failure_class}</td><td><span class="badge badge-${f.severity.toLowerCase()}">${f.severity}</span></td><td>${(f.failure_rate * 100).toFixed(0)}%</td><td>${esc(f.evidence)}</td></tr>`).join('')}
            </tbody></table>

            <h2>Interventions</h2>
            <table class="data-table"><thead><tr><th>ID</th><th>Type</th><th>Description</th><th>Status</th></tr></thead><tbody>
            ${data.interventions.map(i => `<tr><td>${i.id}</td><td>${i.type}</td><td>${esc(i.description)}</td><td>${i.validation_status}</td></tr>`).join('')}
            </tbody></table>
        `;
    },

    // ── Failures ──
    async loadFailures(filters = {}) {
        const [failures, stats] = await Promise.all([
            API.getFailures(filters),
            API.getFailureStats(),
        ]);

        const tbody = document.getElementById('failures-table');
        tbody.innerHTML = failures.length ? failures.map(f => `
            <tr onclick="App.navigate('failure-detail', {id:'${f.id}'})">
                <td>${f.id}</td>
                <td>${f.failure_class}</td>
                <td><span class="badge badge-${f.severity.toLowerCase()}">${f.severity}</span></td>
                <td>${(f.failure_rate * 100).toFixed(0)}%</td>
                <td>${esc(f.evidence)}</td>
                <td>${f.created_at ? new Date(f.created_at).toLocaleDateString() : '-'}</td>
            </tr>
        `).join('') : '<tr><td colspan="6" class="empty">No failures found</td></tr>';
    },

    // ── Failure detail ──
    async loadFailureDetail(failureId) {
        if (!failureId) return;
        const pageEl = document.getElementById('page-failure-detail');
        pageEl.classList.add('active');
        document.getElementById('page-failures').classList.remove('active');

        const data = await API.getFailure(failureId);
        const f = data.failure;

        document.getElementById('failure-detail-content').innerHTML = `
            <span class="back-link" onclick="App.navigate('failures')">&larr; Back to failures</span>
            <h1>Failure: ${f.id}</h1>
            <div class="stats-grid">
                <div class="stat-card"><div class="stat-value">${f.failure_class}</div><div class="stat-label">Class</div></div>
                <div class="stat-card"><div class="stat-value"><span class="badge badge-${f.severity.toLowerCase()}">${f.severity}</span></div><div class="stat-label">Severity</div></div>
                <div class="stat-card"><div class="stat-value">${(f.failure_rate * 100).toFixed(0)}%</div><div class="stat-label">Failure Rate</div></div>
            </div>

            <h2>Evidence</h2>
            <div class="detail-panel"><pre>${esc(f.evidence || 'No evidence recorded')}</pre></div>

            ${f.sample_failure_output ? `<h2>Sample Failure Output</h2><div class="detail-panel"><pre>${esc(f.sample_failure_output)}</pre></div>` : ''}
            ${f.sample_correct_output ? `<h2>Sample Correct Output</h2><div class="detail-panel"><pre>${esc(f.sample_correct_output)}</pre></div>` : ''}

            <h2>Interventions (${data.interventions.length})</h2>
            <table class="data-table"><thead><tr><th>Type</th><th>Description</th><th>Status</th><th>Before</th><th>After</th></tr></thead><tbody>
            ${data.interventions.map(i => `<tr><td>${i.type}</td><td>${esc(i.description)}</td><td>${i.validation_status}</td><td>${i.failure_rate_before != null ? (i.failure_rate_before * 100).toFixed(0) + '%' : '-'}</td><td>${i.failure_rate_after != null ? (i.failure_rate_after * 100).toFixed(0) + '%' : '-'}</td></tr>`).join('') || '<tr><td colspan="5" class="empty">No interventions</td></tr>'}
            </tbody></table>
        `;
    },

    // ── Benchmarks ──
    async loadBenchmarks() {
        const benchmarks = await API.getBenchmarks();
        const tbody = document.getElementById('benchmarks-table');
        tbody.innerHTML = benchmarks.length ? benchmarks.map(b => `
            <tr onclick="App.loadBenchmarkDetail('${b.id}')">
                <td>${b.id}</td>
                <td>${b.started_at ? new Date(b.started_at).toLocaleDateString() : '-'}</td>
                <td>${esc(b.model_name || '-')}</td>
                <td>${esc(b.profile || '-')}</td>
                <td>${b.duration_seconds ? b.duration_seconds.toFixed(1) + 's' : '-'}</td>
            </tr>
        `).join('') : '<tr><td colspan="5" class="empty">No benchmarks yet</td></tr>';
    },

    async loadBenchmarkDetail(id) {
        const data = await API.getBenchmark(id);
        const m = data.metrics || {};
        const detail = document.getElementById('benchmark-detail');
        detail.innerHTML = `
            <h2>Benchmark: ${data.id}</h2>
            <div class="stats-grid">
                <div class="stat-card"><div class="stat-value">${m.success_rate != null ? (m.success_rate * 100).toFixed(0) + '%' : '-'}</div><div class="stat-label">Success Rate</div></div>
                <div class="stat-card"><div class="stat-value">${m.unique_failures_found || 0}</div><div class="stat-label">Failures Found</div></div>
                <div class="stat-card"><div class="stat-value">${m.max_severity || '-'}</div><div class="stat-label">Max Severity</div></div>
                <div class="stat-card"><div class="stat-value">${m.consistency_score != null ? (m.consistency_score * 100).toFixed(0) + '%' : '-'}</div><div class="stat-label">Consistency</div></div>
            </div>
            <div class="detail-panel"><pre>${JSON.stringify(m, null, 2)}</pre></div>
        `;
    },

    // ── Attacks ──
    async loadAttacks() {
        const [scans, probes] = await Promise.all([
            API.getAttackScans(),
            API.getProbes(),
        ]);

        const scansTbody = document.getElementById('attacks-scans-table');
        scansTbody.innerHTML = scans.length ? scans.map(s => `
            <tr>
                <td>${s.id}</td>
                <td>${s.started_at ? new Date(s.started_at).toLocaleDateString() : '-'}</td>
                <td>${s.total_probes}</td>
                <td>${s.vulnerable_probes}</td>
                <td>${(s.vulnerability_rate * 100).toFixed(0)}%</td>
            </tr>
        `).join('') : '<tr><td colspan="5" class="empty">No scans yet</td></tr>';

        document.getElementById('probes-count').textContent = probes.length;
    },

    // ── Settings ──
    async loadSettings() {
        const settings = await API.getSettings();
        document.getElementById('settings-content').innerHTML = `
            <div class="detail-panel"><pre>${JSON.stringify(settings, null, 2)}</pre></div>
        `;
    },
};

// Escape HTML
function esc(str) {
    if (!str) return '';
    const d = document.createElement('div');
    d.textContent = String(str).slice(0, 300);
    return d.innerHTML;
}

// Filter handler for failures page
function applyFailureFilters() {
    const severity = document.getElementById('filter-severity').value;
    const cls = document.getElementById('filter-class').value;
    const params = {};
    if (severity) params.severity = severity;
    if (cls) params.failure_class = cls;
    App.loadFailures(params);
}

// Boot
document.addEventListener('DOMContentLoaded', () => App.init());
