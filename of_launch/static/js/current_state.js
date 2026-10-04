/* Current State Page JavaScript. */

let servicesData = {};
let availableEnvironments = [];

function initializePage() {
  const urlParams = new URLSearchParams(window.location.search);
  const selectedEnv = urlParams.get('environment');

  if (selectedEnv) {
    document.getElementById('environment-filter').value = selectedEnv;
    renderServices();
  } else {
    showInitialState();
  }

  updateLastRefreshTime();

  setInterval(() => {
    updateLastRefreshTime();
  }, 60000);
}

function showInitialState() {
  const container = document.getElementById('services-container');
  container.innerHTML = `
    <div class="empty-state">
      <div class="empty-icon">🔍</div>
      <h3>Select an Environment</h3>
      <p>Please select an environment from the dropdown above to view ECS services.</p>
    </div>
  `;
}

function onEnvironmentChange() {
  const selectedEnv = document.getElementById('environment-filter').value;

  if (!selectedEnv) {
    showInitialState();
    return;
  }

  showLoadingState();

  fetchEnvironmentData(selectedEnv);
}

function showLoadingState() {
  const container = document.getElementById('services-container');
  const loading = document.getElementById('loading');

  container.style.display = 'none';
  loading.style.display = 'flex';
}

function hideLoadingState() {
  const container = document.getElementById('services-container');
  const loading = document.getElementById('loading');

  loading.style.display = 'none';
  container.style.display = 'block';
}

async function fetchEnvironmentData(environment) {
  try {
    const response = await fetch(`/current-state?environment=${encodeURIComponent(environment)}&ajax=1`);
    const data = await response.json();

    if (response.ok) {
      servicesData = { [environment]: data };
      renderServices();
    } else {
      showErrorState(data.error || 'Failed to fetch environment data');
    }
  } catch (error) {
    console.error('Error fetching environment data:', error);
    showErrorState('Network error occurred while fetching data');
  } finally {
    hideLoadingState();
  }
}

function showErrorState(errorMessage) {
  const container = document.getElementById('services-container');
  container.innerHTML = `
    <div class="empty-state">
      <div class="empty-icon">❌</div>
      <h3>Error Loading Data</h3>
      <p>${errorMessage}</p>
      <button onclick="onEnvironmentChange()" style="margin-top: 10px; padding: 8px 16px; background: #3b82f6; color: white; border: none; border-radius: 4px; cursor: pointer;">
        Retry
      </button>
    </div>
  `;
}

function renderServices() {
  const container = document.getElementById('services-container');
  const selectedEnv = document.getElementById('environment-filter').value;

  if (!selectedEnv) {
    showInitialState();
    return;
  }

  container.innerHTML = '';

  let servicesToShow = [];

  if (servicesData && servicesData[selectedEnv]) {
    if (Array.isArray(servicesData[selectedEnv])) {
      servicesToShow = servicesData[selectedEnv];
    }
  }

  if (servicesToShow.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">🔍❌</div>
        <h3>No services found</h3>
        <p>No services are currently running in the selected environment.</p>
      </div>
    `;
    return;
  }

  const table = document.createElement('div');
  table.className = 'table-container';
  table.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Service Name</th>
          <th>Environment</th>
          <th>Current Image</th>
          <th>Tasks</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody id="services-tbody">
      </tbody>
    </table>
  `;

  container.appendChild(table);

  const tbody = document.getElementById('services-tbody');
  servicesToShow.forEach(service => {
    const row = createServiceRow(service);
    tbody.appendChild(row);
  });
}

function createServiceRow(service) {
  const row = document.createElement('tr');

  let status = service.status || 'unknown';
  let statusText = status;

  switch (status) {
    case 'active':
      statusText = 'Active';
      break;
    case 'partial':
      statusText = 'Partial';
      break;
    case 'pending':
      statusText = 'Pending';
      break;
    case 'stopped':
      statusText = 'Stopped';
      break;
    default:
      statusText = 'Unknown';
  }

  const escapedServiceName = service.name.replace(/'/g, "\\'").replace(/"/g, '&quot;');
  const escapedEnvironment = service.environment.replace(/'/g, "\\'").replace(/"/g, '&quot;');

  row.innerHTML = `
    <td class="service-name-cell">${escapeHtml(service.name)}</td>
    <td>
      <span class="environment-badge">
        ${escapeHtml(service.environment)}
      </span>
    </td>
    <td class="image-tag-cell">
      ${service.current_image && service.current_image !== 'unknown' ?
      `<span class="current-image">${escapeHtml(service.current_image)}</span>` :
      '<span style="color: #6b7280;">No image</span>'
    }
    </td>
    <td>
      <div class="task-info">
        <span class="task-count status-${status}" title="${statusText}">
          ${service.task_count || 0}/${service.desired_count || 0}
          ${service.pending_count > 0 ? ` (${service.pending_count} pending)` : ''}
        </span>
      </div>
    </td>
    <td>
      <div class="actions-cell">
        <button class="btn-icon btn-history" onclick="viewHistory('${escapedServiceName}', '${escapedEnvironment}')" title="View History">
          📜
        </button>
      </div>
    </td>
  `;

  return row;
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function refreshData() {
  const selectedEnv = document.getElementById('environment-filter').value;

  if (!selectedEnv) {
    showInitialState();
    return;
  }

  showLoadingState();
  fetchEnvironmentData(selectedEnv);
}

function updateLastRefreshTime() {
  const now = new Date();
  const timeStr = now.toLocaleTimeString();
  document.getElementById('last-updated-time').textContent = `Last updated: ${timeStr}`;
}

function viewHistory(serviceName, environment) {
  const url = `/deployment-history?service=${encodeURIComponent(serviceName)}&environment=${encodeURIComponent(environment)}`;
  window.location.href = url;
}

function initializeFlaskData(currentDeployments, environments) {
  servicesData = currentDeployments;
  availableEnvironments = environments;

  console.log('Services data from Flask:', servicesData);
  console.log('Available environments:', availableEnvironments);
}

document.addEventListener('DOMContentLoaded', initializePage);
