/**
 * Admin User Management
 */

const validRoles = ['admin', 'production-executor', 'shared-executor'];
let pendingDeleteUsername = null;
let pendingResetUsername = null;

document.addEventListener('DOMContentLoaded', loadUsers);

async function loadUsers() {
    document.getElementById('users-loading').style.display = 'block';
    document.getElementById('users-table').style.display = 'none';
    try {
        const resp = await fetch('/admin/api/users');
        const data = await resp.json();
        if (data.error) {
            showAlert(data.error, 'danger');
            return;
        }
        renderUsers(data.users);
    } catch (e) {
        showAlert('Failed to load users: ' + e.message, 'danger');
    } finally {
        document.getElementById('users-loading').style.display = 'none';
    }
}

function renderUsers(users) {
    const tbody = document.getElementById('users-tbody');
    tbody.innerHTML = '';
    for (const u of users) {
        const roleBadge = u.role === 'admin' ? 'warning'
            : u.role === 'production-executor' ? 'danger' : 'info';
        const lastLogin = u.last_login ? new Date(u.last_login).toLocaleString() : 'never';
        const created = u.created_at ? new Date(u.created_at).toLocaleString() : '';

        const roleOptions = validRoles.map(r =>
            `<option value="${r}" ${r === u.role ? 'selected' : ''}>${r}</option>`
        ).join('');

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><strong>${esc(u.username)}</strong></td>
            <td>
                <select class="form-select form-select-sm d-inline-block" style="width:auto;"
                        onchange="changeRole('${esc(u.username)}', this.value)">
                    ${roleOptions}
                </select>
            </td>
            <td><small>${created}</small></td>
            <td><small>${lastLogin}</small></td>
            <td>
                <button class="btn btn-outline-warning btn-sm me-1" onclick="showResetPasswordModal('${esc(u.username)}')">Reset PW</button>
                <button class="btn btn-outline-danger btn-sm" onclick="showDeleteModal('${esc(u.username)}')">Delete</button>
            </td>
        `;
        tbody.appendChild(tr);
    }
    document.getElementById('users-table').style.display = 'table';
}

function showAddUserModal() {
    document.getElementById('new-username').value = '';
    document.getElementById('new-password').value = '';
    document.getElementById('new-role').value = 'shared-executor';
    new bootstrap.Modal(document.getElementById('addUserModal')).show();
}

async function addUser() {
    const username = document.getElementById('new-username').value.trim();
    const password = document.getElementById('new-password').value;
    const role = document.getElementById('new-role').value;
    if (!username || !password) {
        showAlert('Username and password required', 'danger');
        return;
    }
    try {
        const resp = await fetch('/admin/api/users', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({username, password, role})
        });
        const data = await resp.json();
        if (data.error) {
            showAlert(data.error, 'danger');
            return;
        }
        bootstrap.Modal.getInstance(document.getElementById('addUserModal')).hide();
        showAlert(data.message, 'success');
        loadUsers();
    } catch (e) {
        showAlert('Failed to create user: ' + e.message, 'danger');
    }
}

async function changeRole(username, newRole) {
    try {
        const resp = await fetch(`/admin/api/users/${encodeURIComponent(username)}/role`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({role: newRole})
        });
        const data = await resp.json();
        if (data.error) {
            showAlert(data.error, 'danger');
            loadUsers();
            return;
        }
        showAlert(data.message, 'success');
    } catch (e) {
        showAlert('Failed to change role: ' + e.message, 'danger');
    }
}

function showResetPasswordModal(username) {
    pendingResetUsername = username;
    document.getElementById('reset-pw-username').textContent = username;
    document.getElementById('reset-password').value = '';
    new bootstrap.Modal(document.getElementById('resetPasswordModal')).show();
}

async function resetPassword() {
    const password = document.getElementById('reset-password').value;
    if (!password) {
        showAlert('Password required', 'danger');
        return;
    }
    try {
        const resp = await fetch(`/admin/api/users/${encodeURIComponent(pendingResetUsername)}/password`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({password})
        });
        const data = await resp.json();
        if (data.error) {
            showAlert(data.error, 'danger');
            return;
        }
        bootstrap.Modal.getInstance(document.getElementById('resetPasswordModal')).hide();
        showAlert(data.message, 'success');
    } catch (e) {
        showAlert('Failed to reset password: ' + e.message, 'danger');
    }
}

function showDeleteModal(username) {
    pendingDeleteUsername = username;
    document.getElementById('delete-username-display').textContent = username;
    new bootstrap.Modal(document.getElementById('deleteModal')).show();
}

async function confirmDelete() {
    try {
        const resp = await fetch(`/admin/api/users/${encodeURIComponent(pendingDeleteUsername)}`, {
            method: 'DELETE'
        });
        const data = await resp.json();
        if (data.error) {
            showAlert(data.error, 'danger');
            return;
        }
        bootstrap.Modal.getInstance(document.getElementById('deleteModal')).hide();
        showAlert(data.message, 'success');
        loadUsers();
    } catch (e) {
        showAlert('Failed to delete user: ' + e.message, 'danger');
    }
}

function showAlert(message, type) {
    const container = document.getElementById('alert-container');
    const div = document.createElement('div');
    div.className = `alert alert-${type} alert-dismissible fade show`;
    div.innerHTML = `${esc(message)}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>`;
    container.prepend(div);
    setTimeout(() => div.remove(), 5000);
}

function esc(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(text));
    return div.innerHTML;
}
