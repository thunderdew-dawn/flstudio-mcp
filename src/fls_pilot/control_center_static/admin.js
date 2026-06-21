/**
 * FLS Pilot — Minimal Admin UI (PR 5)
 * Only active when the Control Center is started with --admin.
 * Sends JSON data to /api/admin/* routes. No code execution.
 */

'use strict';

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------

function showPage(name) {
  document.querySelectorAll('.page').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('nav button[data-page]').forEach(el => el.classList.remove('active'));
  const page = document.getElementById('page-' + name);
  if (page) page.classList.add('active');
  const btn = document.querySelector('nav button[data-page="' + name + '"]');
  if (btn) btn.classList.add('active');
  // Load data for the page on first visit
  switch (name) {
    case 'workflows':     loadWorkflows();    break;
    case 'workflow-runs': loadWorkflowRuns(); break;
    case 'job-kinds':     loadJobKinds();     break;
    case 'jobs':          loadJobs();         break;
  }
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

async function apiFetch(path, opts) {
  const res = await fetch(path, opts);
  const data = await res.json();
  return { ok: res.ok, status: res.status, data };
}

function pill(label, variant) {
  return `<span class="pill ${variant || ''}">${esc(label)}</span>`;
}

function esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function setAlert(id, msg, type) {
  const el = document.getElementById(id);
  if (!el) return;
  if (!msg) { el.innerHTML = ''; return; }
  el.innerHTML = `<div class="alert alert-${type || 'info'}">${esc(msg)}</div>`;
}

function ts(isoStr) {
  if (!isoStr) return '—';
  try { return new Date(isoStr).toLocaleString(); } catch { return isoStr; }
}

// ---------------------------------------------------------------------------
// Workflows page
// ---------------------------------------------------------------------------

let _editingWorkflowId = null;
let _workflowRows = [];
let _registeredJobKinds = null;

async function getRegisteredJobKinds() {
  if (Array.isArray(_registeredJobKinds)) return _registeredJobKinds;
  try {
    const { ok, data } = await apiFetch('/api/admin/job-kinds');
    if (!ok || !data.ok) throw new Error(data.error || 'Failed to load job kinds');
    _registeredJobKinds = data.kinds || [];
  } catch {
    _registeredJobKinds = [];
  }
  return _registeredJobKinds;
}

function workflowJobKinds(kinds) {
  return (kinds || []).filter(k => String(k).startsWith('workflow.'));
}

function renderJobKindHint(kinds) {
  const wfKinds = workflowJobKinds(kinds);
  if (wfKinds.length) {
    return 'Registered workflow job kinds: ' + wfKinds.join(', ');
  }
  if ((kinds || []).length) {
    return 'Registered job kinds: ' + kinds.join(', ') +
      '. None are workflow.* handlers; create/register a workflow job handler before using Run.';
  }
  return 'No job kinds are registered. Start the Runtime daemon or register a workflow job handler first.';
}

async function loadWorkflows() {
  const el = document.getElementById('workflows-content');
  el.innerHTML = '<div class="empty"><span class="spinner"></span> Loading…</div>';
  setAlert('workflows-alert', '', '');
  try {
    const { ok, data } = await apiFetch('/api/admin/workflows');
    if (!ok || !data.ok) throw new Error(data.error || 'Failed to load workflows');
    renderWorkflows(data.workflows || []);
  } catch (e) {
    el.innerHTML = '';
    setAlert('workflows-alert', e.message, 'error');
  }
}

function renderWorkflows(rows) {
  const el = document.getElementById('workflows-content');
  _workflowRows = Array.isArray(rows) ? rows : [];
  if (!_workflowRows.length) {
    el.innerHTML = '<div class="empty">No workflows found.</div>';
    return;
  }
  const tbody = _workflowRows.map((w, index) => {
    const statusV = String(w.status || 'unknown');
    const originV = String(w.origin || 'unknown');
    const isProtected = Boolean(w.protected);
    return `
      <tr>
        <td class="code">${esc(w.workflow_id)}</td>
        <td>${esc(w.title || '—')}</td>
        <td>${pill(statusV, statusV)}</td>
        <td>${pill(originV, originV === 'builtin' ? 'builtin' : '')}</td>
        <td>${esc(w.runner_type || '—')}${w.runner_ref ? `<div class="muted code">${esc(w.runner_ref)}</div>` : ''}</td>
        <td>
          <button class="btn btn-ghost" style="font-size:12px;padding:3px 8px"
            onclick="viewWorkflowByIndex(${index})">View</button>
          ${!isProtected ? `
            <button class="btn btn-ghost" style="font-size:12px;padding:3px 8px"
              onclick="openEditModalByIndex(${index})">Edit</button>
            <button class="btn btn-danger" style="font-size:12px;padding:3px 8px"
              onclick="archiveWorkflow(${JSON.stringify(w.workflow_id)})">Archive</button>
          ` : `<span class="pill" style="font-size:11px">protected</span>`}
          ${w.runner_type === 'job' ? `
            <button class="btn btn-primary" style="font-size:12px;padding:3px 8px"
              onclick="openRunModal(${JSON.stringify(w.workflow_id)})">Run</button>
          ` : ''}
        </td>
      </tr>`;
  }).join('');
  el.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>ID</th><th>Title</th><th>Status</th><th>Origin</th><th>Runner</th><th>Actions</th>
        </tr>
      </thead>
      <tbody>${tbody}</tbody>
    </table>`;
}

function workflowByIndex(index) {
  const n = Number(index);
  if (!Number.isInteger(n) || n < 0 || n >= _workflowRows.length) return null;
  return _workflowRows[n];
}

function viewWorkflowByIndex(index) {
  const w = workflowByIndex(index);
  if (!w) { alert('Could not find workflow data.'); return; }
  document.getElementById('workflow-view-title').textContent =
    (w.origin === 'builtin' || w.protected) ? 'Built-in Workflow (read-only)' : 'Workflow Definition';
  document.getElementById('workflow-view-json').value = JSON.stringify(w, null, 2);
  document.getElementById('workflow-view-modal').classList.remove('hidden');
}

async function openCreateModal() {
  _editingWorkflowId = null;
  document.getElementById('workflow-modal-title').textContent = 'New Custom Workflow';
  document.getElementById('workflow-modal-save').textContent = 'Create';
  const kinds = await getRegisteredJobKinds();
  const wfKinds = workflowJobKinds(kinds);
  const runnerRef = wfKinds[0] || '';
  document.getElementById('workflow-json').value = JSON.stringify({
    workflow_id: 'user.my_workflow',
    title: 'My Workflow',
    kind: 'analysis_workflow',
    status: runnerRef ? 'active' : 'draft',
    origin: 'custom',
    runner_type: 'job',
    runner_ref: runnerRef || null,
    analysis_report_required: false,
    health_inclusion_policy: 'optional_context_report',
    inputs_schema: {},
    metadata: {
      notes: runnerRef
        ? 'runner_ref must stay one of the registered workflow job kinds.'
        : 'Register a workflow.* job handler first, then set runner_ref and status=active.'
    }
  }, null, 2);
  setAlert('workflow-modal-alert', renderJobKindHint(kinds), runnerRef ? 'info' : 'error');
  document.getElementById('workflow-modal').classList.remove('hidden');
}

function openEditModalByIndex(index) {
  const w = workflowByIndex(index);
  if (!w) { alert('Could not find workflow data.'); return; }
  _editingWorkflowId = w.workflow_id;
  document.getElementById('workflow-modal-title').textContent = 'Edit Workflow';
  document.getElementById('workflow-modal-save').textContent = 'Save';
  document.getElementById('workflow-json').value = JSON.stringify(w, null, 2);
  getRegisteredJobKinds().then(kinds =>
    setAlert('workflow-modal-alert', renderJobKindHint(kinds), 'info')
  );
  document.getElementById('workflow-modal').classList.remove('hidden');
}

function closeModal(id) {
  document.getElementById(id).classList.add('hidden');
}

async function saveWorkflow() {
  setAlert('workflow-modal-alert', '', '');
  let definition;
  try {
    definition = JSON.parse(document.getElementById('workflow-json').value);
  } catch (e) {
    setAlert('workflow-modal-alert', 'Invalid JSON: ' + e.message, 'error');
    return;
  }
  if (typeof definition !== 'object' || Array.isArray(definition)) {
    setAlert('workflow-modal-alert', 'Definition must be a JSON object.', 'error');
    return;
  }
  // Safety: reject forbidden fields (enforced server-side too, but warn here)
  const forbidden = ['code', 'script', 'cmd', 'command', 'raw'];
  const found = forbidden.filter(k => k in definition);
  if (found.length) {
    setAlert('workflow-modal-alert',
      'Workflow definitions must not contain: ' + found.join(', '), 'error');
    return;
  }
  try {
    let resp;
    if (_editingWorkflowId) {
      resp = await apiFetch('/api/admin/workflows/' + encodeURIComponent(_editingWorkflowId), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ patch: definition }),
      });
    } else {
      resp = await apiFetch('/api/admin/workflows', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ definition }),
      });
    }
    if (!resp.ok || !resp.data.ok) throw new Error(resp.data.error || 'Save failed');
    closeModal('workflow-modal');
    loadWorkflows();
  } catch (e) {
    setAlert('workflow-modal-alert', e.message, 'error');
  }
}

async function archiveWorkflow(workflowId) {
  if (!confirm('Archive workflow "' + workflowId + '"? This cannot be undone here.')) return;
  setAlert('workflows-alert', '', '');
  try {
    const resp = await apiFetch('/api/admin/workflows/' + encodeURIComponent(workflowId), {
      method: 'DELETE',
    });
    if (!resp.ok || !resp.data.ok) throw new Error(resp.data.error || 'Archive failed');
    setAlert('workflows-alert', 'Workflow archived.', 'success');
    loadWorkflows();
  } catch (e) {
    setAlert('workflows-alert', e.message, 'error');
  }
}

// ---------------------------------------------------------------------------
// Run Workflow modal
// ---------------------------------------------------------------------------

let _runWorkflowId = null;

function openRunModal(workflowId) {
  _runWorkflowId = workflowId;
  document.getElementById('run-modal-wfid').textContent = workflowId;
  document.getElementById('run-inputs').value = '{}';
  setAlert('run-modal-alert', '', '');
  document.getElementById('run-modal').classList.remove('hidden');
}

async function submitWorkflowRun() {
  setAlert('run-modal-alert', '', '');
  let inputs;
  try {
    inputs = JSON.parse(document.getElementById('run-inputs').value);
  } catch (e) {
    setAlert('run-modal-alert', 'Invalid JSON: ' + e.message, 'error');
    return;
  }
  try {
    const resp = await apiFetch(
      '/api/admin/workflows/' + encodeURIComponent(_runWorkflowId) + '/run',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ inputs }),
      }
    );
    if (!resp.ok || !resp.data.ok) throw new Error(resp.data.error || 'Submit failed');
    closeModal('run-modal');
    setAlert('workflows-alert', 'Workflow run submitted.', 'success');
    showPage('workflow-runs');
  } catch (e) {
    setAlert('run-modal-alert', e.message, 'error');
  }
}

// ---------------------------------------------------------------------------
// Workflow Runs page
// ---------------------------------------------------------------------------

async function loadWorkflowRuns() {
  const el = document.getElementById('runs-content');
  el.innerHTML = '<div class="empty"><span class="spinner"></span> Loading…</div>';
  setAlert('runs-alert', '', '');
  try {
    const { ok, data } = await apiFetch('/api/admin/workflow-runs');
    if (!ok || !data.ok) throw new Error(data.error || 'Failed to load runs');
    renderWorkflowRuns(data.workflow_runs || []);
  } catch (e) {
    el.innerHTML = '';
    setAlert('runs-alert', e.message, 'error');
  }
}

function renderWorkflowRuns(rows) {
  const el = document.getElementById('runs-content');
  if (!rows.length) {
    el.innerHTML = '<div class="empty">No workflow runs found.</div>';
    return;
  }
  const tbody = rows.map(r => {
    const st = String(r.status || 'unknown');
    const canCancel = ['queued', 'running'].includes(st);
    return `
      <tr>
        <td class="code" style="font-size:11px">${esc(r.run_id)}</td>
        <td class="code">${esc(r.workflow_id)}</td>
        <td>${pill(st, st)}</td>
        <td>${ts(r.started_at)}</td>
        <td>${ts(r.finished_at)}</td>
        <td>
          ${canCancel ? `
            <button class="btn btn-danger" style="font-size:12px;padding:3px 8px"
              onclick="cancelWorkflowRun(${JSON.stringify(r.run_id)})">Cancel</button>
          ` : ''}
        </td>
      </tr>`;
  }).join('');
  el.innerHTML = `
    <table>
      <thead>
        <tr><th>Run ID</th><th>Workflow</th><th>Status</th><th>Started</th><th>Finished</th><th>Actions</th></tr>
      </thead>
      <tbody>${tbody}</tbody>
    </table>`;
}

async function cancelWorkflowRun(runId) {
  if (!confirm('Cancel run "' + runId + '"?')) return;
  setAlert('runs-alert', '', '');
  try {
    const resp = await apiFetch('/api/admin/workflow-runs/' + encodeURIComponent(runId) + '/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    if (!resp.ok || !resp.data.ok) throw new Error(resp.data.error || 'Cancel failed');
    setAlert('runs-alert', 'Run cancelled.', 'success');
    loadWorkflowRuns();
  } catch (e) {
    setAlert('runs-alert', e.message, 'error');
  }
}

// ---------------------------------------------------------------------------
// Job Kinds page
// ---------------------------------------------------------------------------

async function loadJobKinds() {
  const el = document.getElementById('kinds-content');
  el.innerHTML = '<div class="empty"><span class="spinner"></span> Loading…</div>';
  try {
    const { ok, data } = await apiFetch('/api/admin/job-kinds');
    if (!ok || !data.ok) throw new Error(data.error || 'Failed to load job kinds');
    const kinds = data.kinds || [];
    _registeredJobKinds = kinds;
    if (!kinds.length) {
      el.innerHTML = '<div class="empty">No registered job kinds.</div>';
      return;
    }
    el.innerHTML = kinds.map(k => `<span class="kind-chip">${esc(k)}</span>`).join(' ');
  } catch (e) {
    el.innerHTML = `<div class="alert alert-error">${esc(e.message)}</div>`;
  }
}

// ---------------------------------------------------------------------------
// Jobs page
// ---------------------------------------------------------------------------

async function loadJobs() {
  const el = document.getElementById('jobs-content');
  el.innerHTML = '<div class="empty"><span class="spinner"></span> Loading…</div>';
  setAlert('jobs-alert', '', '');
  try {
    const { ok, data } = await apiFetch('/api/admin/jobs');
    if (!ok || !data.ok) throw new Error(data.error || 'Failed to load jobs');
    renderJobs(data.jobs || []);
  } catch (e) {
    el.innerHTML = '';
    setAlert('jobs-alert', e.message, 'error');
  }
}

function renderJobs(rows) {
  const el = document.getElementById('jobs-content');
  if (!rows.length) {
    el.innerHTML = '<div class="empty">No jobs found.</div>';
    return;
  }
  const tbody = rows.map(j => {
    const st = String(j.status || 'unknown');
    const canCancel = ['queued', 'running'].includes(st);
    return `
      <tr>
        <td class="code" style="font-size:11px">${esc(j.job_id)}</td>
        <td class="code">${esc(j.kind)}</td>
        <td>${pill(st, st)}</td>
        <td>${ts(j.created_at)}</td>
        <td>
          ${canCancel ? `
            <button class="btn btn-danger" style="font-size:12px;padding:3px 8px"
              onclick="cancelJob(${JSON.stringify(j.job_id)})">Cancel</button>
          ` : ''}
        </td>
      </tr>`;
  }).join('');
  el.innerHTML = `
    <table>
      <thead>
        <tr><th>Job ID</th><th>Kind</th><th>Status</th><th>Created</th><th>Actions</th></tr>
      </thead>
      <tbody>${tbody}</tbody>
    </table>`;
}

async function cancelJob(jobId) {
  if (!confirm('Cancel job "' + jobId + '"?')) return;
  setAlert('jobs-alert', '', '');
  try {
    const resp = await apiFetch('/api/admin/jobs/' + encodeURIComponent(jobId) + '/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    if (!resp.ok || !resp.data.ok) throw new Error(resp.data.error || 'Cancel failed');
    setAlert('jobs-alert', 'Job cancelled.', 'success');
    loadJobs();
  } catch (e) {
    setAlert('jobs-alert', e.message, 'error');
  }
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  loadWorkflows();
});
