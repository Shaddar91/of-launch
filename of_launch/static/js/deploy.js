/**
 * OF Launch deploy dashboard: environment selection, service listing, artifact browsing,
 * dependency resolution and sequential batch deploy.
 */

let environmentsData = {};
let selectedServices = {};
let manuallyUnchecked = new Set();
let deployResolve = null;

document.addEventListener('DOMContentLoaded', initializePage);

function initializePage() {
    fetchEnvironments();
    document.getElementById('env-select').addEventListener('change', onEnvironmentChange);
    document.getElementById('confirm-deploy-btn').addEventListener('click', onConfirmDeploy);
}

async function fetchEnvironments() {
    try {
        const resp = await fetch('/api/environments');
        environmentsData = await resp.json();
        const select = document.getElementById('env-select');
        for (const env of Object.keys(environmentsData)) {
            const opt = document.createElement('option');
            opt.value = env;
            opt.textContent = env.charAt(0).toUpperCase() + env.slice(1);
            select.appendChild(opt);
        }
    } catch (e) {
        console.error('Failed to fetch environments:', e);
    }
}

function currentEnv() {
    return document.getElementById('env-select').value;
}

function clusterOf(env) {
    return (environmentsData[env] && environmentsData[env].cluster) || '';
}

async function onEnvironmentChange() {
    const env = currentEnv();
    selectedServices = {};
    manuallyUnchecked.clear();
    hideSection('artifacts-card');
    hideSection('deploy-card');
    hideSection('result-card');
    document.getElementById('artifacts-container').innerHTML = '';
    document.getElementById('result-container').innerHTML = '';
    document.getElementById('cluster-name').textContent = env ? clusterOf(env) : '-';
    hideDependencyInfo();

    if (!env) {
        hideSection('services-card');
        document.getElementById('services-list').innerHTML = '';
        return;
    }

    showSection('services-card');
    document.getElementById('services-loading').style.display = 'block';
    document.getElementById('services-list').innerHTML = '';

    try {
        const resp = await fetch(`/api/services?env=${encodeURIComponent(env)}`);
        const data = await resp.json();
        if (data.error) {
            document.getElementById('services-list').innerHTML =
                `<div class="alert alert-danger">${escapeHtml(data.error)}</div>`;
            return;
        }
        renderServices(data.services);
    } catch (e) {
        document.getElementById('services-list').innerHTML =
            `<div class="alert alert-danger">Failed to load services: ${escapeHtml(e.message)}</div>`;
    } finally {
        document.getElementById('services-loading').style.display = 'none';
    }
}

function renderServices(servicesByType) {
    const container = document.getElementById('services-list');
    container.innerHTML = '';

    const typeLabels = {
        frontend: {label: 'Frontend (S3 + CloudFront)', color: 'primary'},
        eks: {label: 'EKS (ArgoCD + Helm)', color: 'success'},
        worker: {label: 'Worker (CodeDeploy)', color: 'warning'},
        cron: {label: 'Cron Jobs (CodeDeploy)', color: 'info'}
    };

    if (Object.keys(servicesByType).length === 0) {
        container.innerHTML = '<div class="text-muted">No services registered for this environment.</div>';
        return;
    }

    for (const [deployType, services] of Object.entries(servicesByType)) {
        const typeInfo = typeLabels[deployType] || {label: deployType, color: 'secondary'};
        const section = document.createElement('div');
        section.className = 'mb-3';
        section.innerHTML = `
            <h6><span class="badge bg-${typeInfo.color} me-2">${typeInfo.label}</span></h6>
        `;

        for (const svc of services) {
            const row = document.createElement('div');
            row.className = 'form-check mb-2 ms-3';
            row.id = `svc-row-${svc.name}`;
            row.innerHTML = `
                <input class="form-check-input service-checkbox" type="checkbox"
                       id="svc-${svc.name}" data-service="${svc.name}" data-type="${deployType}"
                       onchange="onServiceToggle('${svc.name}', '${deployType}', this.checked)">
                <label class="form-check-label" for="svc-${svc.name}">
                    ${escapeHtml(svc.display_name)} <small class="text-muted">(${svc.name})</small>
                </label>
                <span class="badge bg-secondary ms-1 dep-badge" id="dep-badge-${svc.name}" style="display:none;font-size:0.7rem;">auto-selected</span>
            `;
            section.appendChild(row);
        }
        container.appendChild(section);
    }
}

async function onServiceToggle(serviceName, deployType, checked) {
    if (checked) {
        manuallyUnchecked.delete(serviceName);
        selectedServices[serviceName] = {deploy_type: deployType, version: null, auto_selected: false};
        loadArtifactsForService(serviceName, deployType);
    } else {
        manuallyUnchecked.add(serviceName);
        delete selectedServices[serviceName];
        removeArtifactSelector(serviceName);
        const badge = document.getElementById(`dep-badge-${serviceName}`);
        if (badge) badge.style.display = 'none';

        await cleanupOrphanedDependencies();
    }
    updateDeployButton();
    await checkDependencies();
}

function dropAutoSelected(name) {
    delete selectedServices[name];
    removeArtifactSelector(name);
    const checkbox = document.getElementById(`svc-${name}`);
    if (checkbox) { checkbox.checked = false; checkbox.disabled = false; }
    const badge = document.getElementById(`dep-badge-${name}`);
    if (badge) badge.style.display = 'none';
}

async function cleanupOrphanedDependencies() {
    const env = currentEnv();
    if (!env) return;

    const manuallySelected = Object.entries(selectedServices)
        .filter(([_, s]) => !s.auto_selected)
        .map(([name, _]) => name);

    if (manuallySelected.length === 0) {
        for (const [name, svc] of Object.entries({...selectedServices})) {
            if (svc.auto_selected) dropAutoSelected(name);
        }
        return;
    }

    try {
        const resp = await fetch(
            `/api/dependencies?env=${encodeURIComponent(env)}&services=${manuallySelected.join(',')}`
        );
        const data = await resp.json();
        const neededNames = new Set((data.auto_selected || []).map(d => d.name));
        for (const [name, svc] of Object.entries({...selectedServices})) {
            if (svc.auto_selected && !neededNames.has(name)) dropAutoSelected(name);
        }
    } catch (e) {
        console.error('Failed to cleanup orphaned dependencies:', e);
    }
}

async function checkDependencies() {
    const env = currentEnv();
    if (!env) return;

    const selected = Object.keys(selectedServices);
    if (selected.length === 0) {
        hideDependencyInfo();
        return;
    }

    try {
        const resp = await fetch(
            `/api/dependencies?env=${encodeURIComponent(env)}&services=${selected.join(',')}`
        );
        const data = await resp.json();

        if (data.auto_selected && data.auto_selected.length > 0) {
            showDependencyInfo(data);
            for (const dep of data.auto_selected) {
                manuallyUnchecked.delete(dep.name);
                if (!selectedServices[dep.name]) {
                    const checkbox = document.getElementById(`svc-${dep.name}`);
                    if (checkbox && !checkbox.checked) {
                        checkbox.checked = true;
                        checkbox.disabled = true;
                        checkbox.title = `${dep.reason}; the bundle is all-or-nothing, uncheck the originally selected service to clear`;
                        selectedServices[dep.name] = {
                            deploy_type: dep.deploy_type,
                            version: null,
                            auto_selected: true
                        };
                        loadArtifactsForService(dep.name, dep.deploy_type);
                        const badge = document.getElementById(`dep-badge-${dep.name}`);
                        if (badge) {
                            badge.style.display = 'inline';
                            badge.title = dep.reason;
                        }
                    }
                }
            }
            updateDeployButton();
        } else {
            hideDependencyInfo();
        }
    } catch (e) {
        console.error('Failed to check dependencies:', e);
    }
}

function showDependencyInfo(data) {
    const info = document.getElementById('dependency-info');
    if (!info) return;
    let html = '<strong>Dependencies resolved:</strong> ';
    html += data.auto_selected.map(
        d => `<span class="badge bg-secondary me-1">${escapeHtml(d.name)}</span>`
    ).join(' ');
    if (data.deploy_order && data.deploy_order.length > 1) {
        html += `<br><small class="text-muted">Deploy order: ${data.deploy_order.join(' → ')}</small>`;
    }
    info.innerHTML = html;
    info.style.display = 'block';
}

function hideDependencyInfo() {
    const info = document.getElementById('dependency-info');
    if (info) info.style.display = 'none';
}

function artifactUrl(env, deployType, serviceName) {
    const e = encodeURIComponent(env);
    const s = encodeURIComponent(serviceName);
    if (deployType === 'frontend') return `/api/artifacts/frontend?env=${e}&app=${s}`;
    if (deployType === 'eks') return `/api/artifacts/ecr?env=${e}&service=${s}`;
    if (deployType === 'cron') return `/api/artifacts/cron?env=${e}&service=${s}`;
    return `/api/artifacts/worker?env=${e}&service=${s}`;
}

async function loadArtifactsForService(serviceName, deployType) {
    const env = currentEnv();
    showSection('artifacts-card');

    const container = document.getElementById('artifacts-container');
    let svcDiv = document.getElementById(`artifact-${serviceName}`);
    if (!svcDiv) {
        svcDiv = document.createElement('div');
        svcDiv.id = `artifact-${serviceName}`;
        svcDiv.className = 'mb-3 p-3 border rounded';
        container.appendChild(svcDiv);
    }
    svcDiv.innerHTML = `
        <div class="d-flex align-items-center">
            <strong>${escapeHtml(serviceName)}</strong>
            <span class="spinner-border spinner-border-sm ms-2"></span>
            <small class="ms-2 text-muted">Loading artifacts...</small>
        </div>
    `;

    try {
        const resp = await fetch(artifactUrl(env, deployType, serviceName));
        const data = await resp.json();
        renderArtifactSelector(serviceName, deployType, data);
    } catch (e) {
        svcDiv.innerHTML = `
            <strong>${escapeHtml(serviceName)}</strong>
            <div class="alert alert-danger mt-2 mb-0">Failed to load artifacts</div>
        `;
    }
}

function renderArtifactSelector(serviceName, deployType, data) {
    const svcDiv = document.getElementById(`artifact-${serviceName}`);
    if (!svcDiv) return;

    let items = [];
    let labelField = '';
    let valueField = '';

    if (deployType === 'eks') {
        items = data.images || [];
        labelField = 'image_tag';
        valueField = 'image_tag';
    } else {
        items = data.artifacts || [];
        labelField = 'version_hash';
        valueField = 'key';
    }

    let html = `<div class="d-flex justify-content-between align-items-center mb-2">
        <strong>${escapeHtml(serviceName)}</strong>
        <div>
            <span class="badge bg-secondary me-2">${items.length} available</span>
            <button class="btn btn-sm btn-outline-secondary" onclick="refreshArtifacts('${serviceName}', '${deployType}')" title="Refresh artifacts">
                &#x21bb;
            </button>
        </div>
    </div>`;

    if (data.error) {
        html += `<div class="alert alert-warning mb-0">${escapeHtml(data.error)}</div>`;
    } else if (items.length === 0) {
        html += '<div class="text-muted">No artifacts found</div>';
    } else {
        html += `<select class="form-select" id="version-${serviceName}"
                  onchange="onVersionSelect('${serviceName}', this.value)">
            <option value="">-- Select version --</option>`;

        for (const item of items) {
            const label = item[labelField] || 'unknown';
            const value = item[valueField] || '';
            const date = item.last_modified || item.pushed_at || '';
            const dateStr = date ? new Date(date).toLocaleString() : '';
            const size = item.size_display || '';
            html += `<option value="${escapeHtml(value)}">
                ${escapeHtml(label)} - ${dateStr} ${size ? '(' + size + ')' : ''}
            </option>`;
        }
        html += '</select>';

        if (data.mock) {
            html += '<small class="text-info mt-1 d-block">[MOCK DATA]</small>';
        }
    }

    svcDiv.innerHTML = html;
}

function refreshArtifacts(serviceName, deployType) {
    if (selectedServices[serviceName]) {
        selectedServices[serviceName].version = null;
    }
    updateDeployButton();
    loadArtifactsForService(serviceName, deployType);
}

function removeArtifactSelector(serviceName) {
    const el = document.getElementById(`artifact-${serviceName}`);
    if (el) el.remove();
    const container = document.getElementById('artifacts-container');
    if (container && container.children.length === 0) {
        hideSection('artifacts-card');
    }
}

function onVersionSelect(serviceName, version) {
    if (selectedServices[serviceName]) {
        selectedServices[serviceName].version = version || null;
    }
    updateDeployButton();
}

function updateDeployButton() {
    const hasSelected = Object.keys(selectedServices).length > 0;
    const allVersioned = Object.values(selectedServices).every(s => s.version);
    if (hasSelected && allVersioned) {
        showSection('deploy-card');
    } else {
        hideSection('deploy-card');
    }
}

async function triggerDeploy() {
    const env = currentEnv();

    if (env === 'production') {
        const confirmed = await showProductionConfirmation(env);
        if (!confirmed) return;
    }

    const btn = document.getElementById('deploy-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Deploying sequentially...';

    const servicesList = Object.entries(selectedServices).map(([name, svc]) => ({
        name: name,
        deploy_type: svc.deploy_type,
        version: svc.version
    }));

    try {
        const resp = await fetch('/api/deploy/batch', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({env: env, services: servicesList})
        });
        if (!resp.ok && resp.status !== 202) {
            const text = await resp.text();
            throw new Error(`HTTP ${resp.status}: ${text.slice(0, 200)}`);
        }
        const data = await resp.json();
        showBatchDeployResults(data);
        if (data.batch_id && data.batch_status === 'in_progress') {
            await pollBatchUntilTerminal(data.batch_id);
        }
    } catch (e) {
        showSection('result-card');
        document.getElementById('result-container').innerHTML =
            `<div class="alert alert-danger">Deploy failed: ${escapeHtml(e.message)}</div>`;
    }

    btn.disabled = false;
    btn.innerHTML = 'Deploy Selected Services';
}

async function pollBatchUntilTerminal(batchId) {
    const POLL_INTERVAL_MS = 3000;
    const TERMINAL = new Set(['completed', 'partial_failure', 'failed']);
    while (true) {
        await new Promise(r => setTimeout(r, POLL_INTERVAL_MS));
        try {
            const resp = await fetch(`/api/deploy/status?batch_id=${encodeURIComponent(batchId)}`);
            if (!resp.ok) {
                console.warn(`status poll returned ${resp.status}`);
                continue;
            }
            const data = await resp.json();
            showBatchDeployResults(data);
            if (TERMINAL.has(data.batch_status)) return;
        } catch (e) {
            console.warn('status poll error', e);
        }
    }
}

function showBatchDeployResults(data) {
    showSection('result-card');
    const container = document.getElementById('result-container');

    const summaryClass = data.batch_status === 'completed' ? 'success'
        : data.batch_status === 'partial_failure' ? 'warning'
        : data.batch_status === 'in_progress' ? 'info' : 'danger';
    const spinner = data.batch_status === 'in_progress'
        ? '<span class="spinner-border spinner-border-sm me-2"></span>' : '';
    const where = data.cluster ? `${escapeHtml(data.environment)} on ${escapeHtml(data.cluster)}` : escapeHtml(data.environment);

    let html = `
    <div class="alert alert-${summaryClass} mb-3">
        <div class="d-flex justify-content-between align-items-center">
            <div>
                ${spinner}<strong>Batch Deploy: ${escapeHtml(data.batch_status.toUpperCase())}</strong>
                <span class="ms-2">${where}</span>
            </div>
            <div>
                <span class="badge bg-success">${data.succeeded} succeeded</span>
                ${data.failed > 0 ? `<span class="badge bg-danger ms-1">${data.failed} failed</span>` : ''}
                ${data.skipped > 0 ? `<span class="badge bg-secondary ms-1">${data.skipped} skipped</span>` : ''}
            </div>
        </div>
        ${data.deploy_order ? `<small class="text-muted">Deploy order: ${data.deploy_order.join(' → ')}</small>` : ''}
        ${data.error ? `<small class="d-block text-danger">${escapeHtml(data.error)}</small>` : ''}
    </div>`;

    for (const r of (data.results || [])) {
        const statusClass = r.status === 'completed' ? 'success'
            : r.status === 'error' || r.status === 'failed' ? 'danger'
            : r.status === 'skipped' ? 'secondary' : 'warning';
        const typeColors = {frontend: 'primary', eks: 'success', worker: 'warning', cron: 'info'};
        const typeColor = typeColors[r.deployment_type] || 'secondary';

        html += `
        <div class="alert alert-${statusClass} mb-2">
            <div class="d-flex justify-content-between align-items-center">
                <div>
                    <span class="badge bg-${typeColor} me-2">${escapeHtml(r.deployment_type || '')}</span>
                    <strong>${escapeHtml(r.service || r.service_name || 'unknown')}</strong>
                </div>
                <span class="badge bg-${statusClass}">${escapeHtml(r.status)}</span>
            </div>
            ${r.message ? `<small class="d-block mt-1">${escapeHtml(r.message)}</small>` : ''}
            ${r.error ? `<small class="d-block mt-1 text-danger">${escapeHtml(r.error)}</small>` : ''}
            ${r.mock ? '<span class="badge bg-info ms-2" style="font-size:0.65rem;">MOCK</span>' : ''}
        </div>`;

        if (r.steps) {
            html += '<ul class="list-group mb-2">';
            for (const step of r.steps) {
                html += `<li class="list-group-item list-group-item-light py-1">
                    <small>Step ${step.step}: ${escapeHtml(step.detail)} (${step.duration_ms}ms)</small>
                </li>`;
            }
            html += '</ul>';
        }
    }

    html += `<div class="text-center mt-3">
        <a href="/status/" class="btn btn-outline-info">View Status Dashboard</a>
        <a href="/deployment-history" class="btn btn-outline-secondary ms-2">View History</a>
    </div>`;

    container.innerHTML = html;
}

function showProductionConfirmation(env) {
    return new Promise((resolve) => {
        deployResolve = resolve;
        const details = document.getElementById('confirm-details');
        const typeColors = {frontend: 'primary', eks: 'success', worker: 'warning', cron: 'info'};
        const typeLabels = {frontend: 'Frontend', eks: 'EKS', worker: 'Worker', cron: 'Cron'};
        const grouped = {};
        for (const [name, svc] of Object.entries(selectedServices)) {
            if (!grouped[svc.deploy_type]) grouped[svc.deploy_type] = [];
            grouped[svc.deploy_type].push({name, version: svc.version, auto: svc.auto_selected});
        }
        const totalCount = Object.keys(selectedServices).length;
        let html = `<table class="table table-sm mb-3">
            <tr><th>Environment</th><td><span class="badge bg-danger">${escapeHtml(env.toUpperCase())}</span></td></tr>
            <tr><th>Cluster</th><td>${escapeHtml(clusterOf(env))}</td></tr>
            <tr><th>Total Services</th><td>${totalCount}</td></tr>
        </table>`;
        html += '<h6>Deployment Scope:</h6>';

        const typeOrder = ['frontend', 'eks', 'worker', 'cron'];
        for (const dtype of typeOrder) {
            const svcs = grouped[dtype];
            if (!svcs) continue;
            const color = typeColors[dtype] || 'secondary';
            const label = typeLabels[dtype] || dtype;
            html += `<div class="mb-2"><span class="badge bg-${color} me-2">${label}</span>`;
            for (const s of svcs) {
                html += `<span class="badge bg-light text-dark border me-1">${escapeHtml(s.name)}`;
                if (s.auto) {
                    html += ' <small class="text-info">(auto)</small>';
                }
                if (s.version) {
                    const verDisplay = s.version.includes('/') ? s.version.split('/').pop() : s.version;
                    const cleanVer = verDisplay.replace(/\.(tar\.gz|tar\.bz2|tgz|zip)$/, '');
                    html += ` <small class="text-muted">(${escapeHtml(cleanVer)})</small>`;
                }
                html += '</span>';
            }
            html += '</div>';
        }

        html += `<div class="alert alert-warning mt-3 mb-0">
            <small>Deploy order: ${typeOrder.filter(t => grouped[t]).join(' → ')}</small>
        </div>`;

        details.innerHTML = html;

        const modal = new bootstrap.Modal(document.getElementById('confirmModal'));
        modal.show();

        document.getElementById('confirmModal').addEventListener('hidden.bs.modal', function handler() {
            document.getElementById('confirmModal').removeEventListener('hidden.bs.modal', handler);
            if (deployResolve) {
                deployResolve(false);
                deployResolve = null;
            }
        });
    });
}

function onConfirmDeploy() {
    if (deployResolve) {
        deployResolve(true);
        deployResolve = null;
    }
    bootstrap.Modal.getInstance(document.getElementById('confirmModal')).hide();
}

function showSection(id) { document.getElementById(id).style.display = 'block'; }
function hideSection(id) { document.getElementById(id).style.display = 'none'; }

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(text));
    return div.innerHTML;
}
