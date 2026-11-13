/**
 * Frontend Application Logic for Configurable Workflow Decision Platform
 */

const defaultBackend = window.location.port === '3000' ? 'http://127.0.0.1:8000' : (window.location.origin || 'http://127.0.0.1:8000');

const STATE = {
  backendUrl: localStorage.getItem('decision_backend_url') || defaultBackend,
  connected: false,
  workflows: [],
  selectedWorkflow: null,
  workflowDetails: {},
  examples: {},
  activeRequest: null,
  activeDecision: null,
  activeAudit: null,
  requestsHistory: [],
  editorMode: 'form', // 'form' | 'json'
};

// DOM References
const el = {
  connectionDot: document.getElementById('connection-dot'),
  connectionText: document.getElementById('connection-text'),
  backendUrlInput: document.getElementById('backend-url-input'),
  btnReloadWorkflows: document.getElementById('btn-reload-workflows'),
  statTotal: document.getElementById('stat-total'),
  statApproved: document.getElementById('stat-approved'),
  statRejected: document.getElementById('stat-rejected'),
  statManual: document.getElementById('stat-manual'),
  statPending: document.getElementById('stat-pending'),
  workflowSelect: document.getElementById('workflow-select'),
  workflowDesc: document.getElementById('workflow-desc'),
  presetsContainer: document.getElementById('presets-container'),
  formContainer: document.getElementById('dynamic-form-fields'),
  jsonEditor: document.getElementById('json-editor'),
  btnToggleMode: document.getElementById('btn-toggle-mode'),
  idempotencyInput: document.getElementById('idempotency-key'),
  btnGenKey: document.getElementById('btn-gen-key'),
  btnSubmit: document.getElementById('btn-submit'),
  decisionInspector: document.getElementById('decision-inspector'),
  inspectorEmpty: document.getElementById('inspector-empty'),
  inspectorContent: document.getElementById('inspector-content'),
  historyTableBody: document.getElementById('history-table-body'),
  btnRefreshHistory: document.getElementById('btn-refresh-history'),
  pipelineFlow: document.getElementById('pipeline-flow'),
  rulesCatalog: document.getElementById('rules-catalog'),
  toastContainer: document.getElementById('toast-container'),
};

// API Helpers
async function api(path, options = {}) {
  const url = `${STATE.backendUrl}${path}`;
  try {
    const res = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(options.headers || {}),
      },
    });

    const isJson = (res.headers.get('content-type') || '').includes('application/json');
    const data = isJson ? await res.json() : await res.text();

    if (!res.ok) {
      const err = new Error(data.detail || data.error || (data.errors ? data.errors.join(', ') : `HTTP ${res.status}`));
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  } catch (err) {
    throw err;
  }
}

// Toast Notifications
function showToast(message, type = 'info') {
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `<span>${message}</span>`;
  el.toastContainer.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

// Status Helpers
function getStatusClass(status) {
  if (!status) return 'invalid';
  const s = status.toLowerCase();
  if (s.includes('approve')) return 'approved';
  if (s.includes('reject')) return 'rejected';
  if (s.includes('manual')) return 'manual_review';
  if (s.includes('retry')) return 'retry_pending';
  if (s.includes('process')) return 'processing';
  return 'invalid';
}

// Health & Stats Check
async function checkHealth() {
  try {
    const health = await api('/health');
    if (health.status === 'ok') {
      STATE.connected = true;
      el.connectionDot.className = 'dot connected';
      el.connectionText.textContent = 'Connected (8000)';
    }
    await refreshStats();
  } catch (e) {
    STATE.connected = false;
    el.connectionDot.className = 'dot disconnected';
    el.connectionText.textContent = 'Disconnected';
  }
}

async function refreshStats() {
  try {
    const stats = await api('/stats');
    el.statTotal.textContent = stats.total_requests || 0;
    el.statApproved.textContent = stats.by_status.APPROVED || 0;
    el.statRejected.textContent = stats.by_status.REJECTED || 0;
    el.statManual.textContent = stats.by_status.MANUAL_REVIEW || 0;
    el.statPending.textContent = (stats.by_status.RETRY_PENDING || 0) + (stats.by_status.PROCESSING || 0);
  } catch (e) {
    // ignore
  }
}

// Workflow & Details Loading
async function initWorkflows() {
  try {
    const list = await api('/workflows');
    STATE.workflows = list;
    el.workflowSelect.innerHTML = '';

    list.forEach((w) => {
      const opt = document.createElement('option');
      opt.value = w.name;
      opt.textContent = `${w.name} (v${w.version})`;
      el.workflowSelect.appendChild(opt);
    });

    if (list.length > 0) {
      STATE.selectedWorkflow = list[0].name;
      await onWorkflowChanged(STATE.selectedWorkflow);
    }

    // Load examples
    try {
      STATE.examples = await api('/examples');
      renderPresets();
    } catch (e) {
      console.warn('Could not load examples', e);
    }
  } catch (e) {
    console.error('Failed to load workflows', e);
    showToast('Failed to load workflows from backend', 'error');
  }
}

async function onWorkflowChanged(wfName) {
  STATE.selectedWorkflow = wfName;
  try {
    const details = await api(`/workflows/${wfName}`);
    STATE.workflowDetails[wfName] = details;
    el.workflowDesc.textContent = details.description || '';
    renderPresets();
    renderDynamicForm(details.input_schema || {});
    renderWorkflowArchitecture(details);
  } catch (e) {
    showToast(`Error fetching workflow '${wfName}'`, 'error');
  }
}

// Preset Buttons
function renderPresets() {
  el.presetsContainer.innerHTML = '';
  const currentWf = STATE.selectedWorkflow;
  const presets = STATE.examples[currentWf] || [];

  if (presets.length === 0) {
    el.presetsContainer.innerHTML = '<span style="color:var(--text-dim);font-size:11px;">No presets available</span>';
    return;
  }

  presets.forEach((p) => {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'preset-chip';
    chip.textContent = p.label;
    chip.onclick = () => loadPresetData(p.data);
    el.presetsContainer.appendChild(chip);
  });
}

function loadPresetData(data) {
  el.jsonEditor.value = JSON.stringify(data, null, 2);
  populateFormFromObject(data);
  showToast('Loaded preset data');
}

// Dynamic Form Generation
function renderDynamicForm(schema) {
  el.formContainer.innerHTML = '';
  const fields = Object.entries(schema);

  if (fields.length === 0) {
    el.formContainer.innerHTML = '<span style="color:var(--text-dim);">No schema defined. Use JSON mode.</span>';
    return;
  }

  fields.forEach(([fieldName, spec]) => {
    const group = document.createElement('div');
    group.className = 'form-group';

    const label = document.createElement('label');
    label.className = 'form-label';
    label.innerHTML = `
      <span>${fieldName} ${spec.required ? '<b style="color:var(--status-rejected);">*</b>' : ''}</span>
      <span style="color:var(--text-dim);font-size:10px;">${spec.type}</span>
    `;

    let input;
    if (spec.type === 'boolean') {
      input = document.createElement('select');
      input.className = 'form-control';
      input.id = `field-${fieldName}`;
      input.innerHTML = `
        <option value="true">true</option>
        <option value="false">false</option>
      `;
    } else if (spec.type === 'integer' || spec.type === 'number') {
      input = document.createElement('input');
      input.type = 'number';
      input.step = spec.type === 'integer' ? '1' : 'any';
      input.className = 'form-control';
      input.id = `field-${fieldName}`;
    } else {
      input = document.createElement('input');
      input.type = 'text';
      input.className = 'form-control';
      input.id = `field-${fieldName}`;
    }

    input.dataset.type = spec.type;
    input.dataset.field = fieldName;
    input.addEventListener('input', syncFormToJson);

    group.appendChild(label);
    group.appendChild(input);
    el.formContainer.appendChild(group);
  });

  // Default initial JSON sync
  syncFormToJson();
}

function syncFormToJson() {
  const data = getFormData();
  el.jsonEditor.value = JSON.stringify(data, null, 2);
}

function getFormData() {
  const data = {};
  const inputs = el.formContainer.querySelectorAll('[data-field]');
  inputs.forEach((input) => {
    const field = input.dataset.field;
    const type = input.dataset.type;
    const val = input.value.trim();

    if (val === '') return;

    if (type === 'integer') {
      data[field] = parseInt(val, 10);
    } else if (type === 'number') {
      data[field] = parseFloat(val);
    } else if (type === 'boolean') {
      data[field] = val === 'true';
    } else {
      data[field] = val;
    }
  });
  return data;
}

function populateFormFromObject(obj) {
  const inputs = el.formContainer.querySelectorAll('[data-field]');
  inputs.forEach((input) => {
    const field = input.dataset.field;
    if (obj[field] !== undefined) {
      input.value = obj[field];
    } else {
      input.value = '';
    }
  });
}

// Submit Request
async function submitDecision() {
  let payloadData;
  try {
    payloadData = JSON.parse(el.jsonEditor.value);
  } catch (err) {
    showToast('Invalid JSON in payload: ' + err.message, 'error');
    return;
  }

  const workflow = el.workflowSelect.value;
  const idempotencyKey = el.idempotencyInput.value.trim() || undefined;

  el.btnSubmit.disabled = true;
  el.btnSubmit.innerHTML = '<span>Evaluating...</span>';

  try {
    const headers = {};
    if (idempotencyKey) {
      headers['Idempotency-Key'] = idempotencyKey;
    }

    const res = await api('/requests', {
      method: 'POST',
      headers,
      body: JSON.stringify({ workflow, data: payloadData }),
    });

    const request = res.request;
    const isDuplicate = res.duplicate;
    showToast(isDuplicate ? 'Duplicate request acknowledged (cached)' : 'Request processed successfully!', 'success');

    await inspectRequest(request.id);
    await refreshStats();
    await loadHistory();
  } catch (err) {
    if (err.status === 422 && err.data && err.data.request) {
      showToast('Validation failed according to workflow schema', 'error');
      renderValidationFailure(err.data.request, err.data.errors);
      await refreshStats();
      await loadHistory();
    } else {
      showToast(err.message, 'error');
    }
  } finally {
    el.btnSubmit.disabled = false;
    el.btnSubmit.innerHTML = '<span>⚡ Run Decision Engine</span>';
  }
}

// Inspect Request Details
async function inspectRequest(requestId) {
  el.inspectorEmpty.style.display = 'none';
  el.inspectorContent.style.display = 'flex';

  try {
    const req = await api(`/requests/${requestId}`);
    STATE.activeRequest = req;

    let decision = null;
    let audit = null;

    try {
      decision = await api(`/requests/${requestId}/decision`);
      STATE.activeDecision = decision;
    } catch (e) {
      STATE.activeDecision = null;
    }

    try {
      audit = await api(`/requests/${requestId}/audit`);
      STATE.activeAudit = audit;
    } catch (e) {
      STATE.activeAudit = null;
    }

    renderDecisionInspector(req, decision, audit);
  } catch (err) {
    showToast(`Failed to load request: ${err.message}`, 'error');
  }
}

function renderValidationFailure(req, errors) {
  el.inspectorEmpty.style.display = 'none';
  el.inspectorContent.style.display = 'flex';

  el.inspectorContent.innerHTML = `
    <div class="decision-hero">
      <div>
        <span class="status-pill large invalid">INVALID INPUT</span>
        <div style="margin-top:6px;font-size:12px;color:var(--text-muted);">
          Request was halted at validation stage; dependencies and rules were bypassed.
        </div>
      </div>
      <div style="text-align:right;">
        <span style="font-family:var(--font-mono);font-size:13px;color:#fff;">${req.id}</span>
      </div>
    </div>

    <div class="reasons-box">
      <div class="reasons-title">Validation Errors:</div>
      <ul class="reasons-list">
        ${errors.map((e) => `<li>${e}</li>`).join('')}
      </ul>
    </div>

    <div class="meta-grid">
      <div class="meta-box">
        <div class="meta-label">Workflow</div>
        <div class="meta-val">${req.workflow} (v${req.workflow_version})</div>
      </div>
      <div class="meta-box">
        <div class="meta-label">Idempotency Key</div>
        <div class="meta-val" title="${req.idempotency_key}">${req.idempotency_key.substring(0, 16)}...</div>
      </div>
    </div>
  `;
}

function renderDecisionInspector(req, decision, audit) {
  const statusClass = getStatusClass(req.status);
  const reasons = (decision && decision.reasons) || [];
  const trace = (decision && decision.trace) || (req.context && req.context.trace) || [];
  const facts = (decision && decision.facts) || (req.context && req.context.dependency_facts) || {};

  let html = `
    <div class="decision-hero">
      <div>
        <span class="status-pill large ${statusClass}">${req.status}</span>
        <div style="margin-top:6px;font-size:12px;color:var(--text-muted);">
          Stage: <b>${req.current_stage || 'complete'}</b> • Workflow: <b>${req.workflow}</b>
        </div>
      </div>
      <div style="text-align:right;">
        <div style="font-size:11px;color:var(--text-dim);">REQUEST ID</div>
        <div style="font-family:var(--font-mono);font-size:14px;font-weight:700;color:#fff;">${req.id}</div>
      </div>
    </div>
  `;

  // Action Panel for Manual Review
  if (req.status === 'MANUAL_REVIEW') {
    html += `
      <div class="action-box">
        <div style="font-weight:700;color:var(--status-manual);display:flex;align-items:center;gap:6px;">
          <span>⚠️ Human Review Required</span>
        </div>
        <div style="font-size:12px;color:var(--text-muted);">
          This request triggered a soft failure rule. A qualified reviewer can approve or reject with comments.
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
          <input type="text" id="review-reviewer" class="form-control" placeholder="Reviewer Name (e.g. Alex M.)" value="Risk Officer" />
          <input type="text" id="review-note" class="form-control" placeholder="Reviewer Notes / Verification reason" value="Documents manually verified" />
        </div>
        <div style="display:flex;gap:10px;justify-content:flex-end;">
          <button class="btn-secondary" style="color:var(--status-rejected);border-color:var(--status-rejected-border);" onclick="onReviewSubmit('${req.id}', 'reject')">
            Reject Request
          </button>
          <button class="btn-primary" style="background:var(--status-approved);border-color:var(--status-approved-border);" onclick="onReviewSubmit('${req.id}', 'approve')">
            Approve Request
          </button>
        </div>
      </div>
    `;
  }

  // Action Panel for Retry
  if (req.status === 'RETRY_PENDING') {
    html += `
      <div class="action-box">
        <div style="font-weight:700;color:var(--status-retry);display:flex;align-items:center;gap:6px;">
          <span>🔄 External Dependency Retry Pending</span>
        </div>
        <div style="font-size:12px;color:var(--text-muted);">
          An external dependency timed out or failed. Retry attempts: <b>${req.retry_count}</b>.
        </div>
        <div style="display:flex;justify-content:flex-end;">
          <button class="btn-primary" onclick="onRetrySubmit('${req.id}')">
            Retry Evaluation Now
          </button>
        </div>
      </div>
    `;
  }

  // Reasons list if any
  if (reasons.length > 0) {
    const isWarning = req.status === 'MANUAL_REVIEW';
    html += `
      <div class="reasons-box ${isWarning ? 'warning' : ''}">
        <div class="reasons-title">${isWarning ? 'Flagged Conditions' : 'Rejection Reasons'}:</div>
        <ul class="reasons-list">
          ${reasons.map((r) => `<li>${r}</li>`).join('')}
        </ul>
      </div>
    `;
  }

  // Summary Meta
  html += `
    <div class="meta-grid">
      <div class="meta-box">
        <div class="meta-label">Idempotency Key</div>
        <div class="meta-val" title="${req.idempotency_key}">${req.idempotency_key}</div>
      </div>
      <div class="meta-box">
        <div class="meta-label">Computed Facts</div>
        <div class="meta-val">${Object.keys(facts).length > 0 ? Object.entries(facts).map(([k, v]) => `${k}: ${v}`).join(', ') : 'None'}</div>
      </div>
      <div class="meta-box">
        <div class="meta-label">Submitted At</div>
        <div class="meta-val">${new Date(req.created_at).toLocaleString()}</div>
      </div>
      <div class="meta-box">
        <div class="meta-label">Last Updated</div>
        <div class="meta-val">${new Date(req.updated_at).toLocaleString()}</div>
      </div>
    </div>
  `;

  // Rule Execution Trace Table
  if (trace && trace.length > 0) {
    html += `
      <div style="margin-top:8px;">
        <div style="font-size:13px;font-weight:700;color:#fff;margin-bottom:10px;">Rule Execution Trace</div>
        <div class="data-table-container">
          <table class="rules-table">
            <thead>
              <tr>
                <th>Rule Name</th>
                <th>Stage</th>
                <th>Status</th>
                <th>Field Evaluated</th>
                <th>Condition</th>
                <th>Message</th>
              </tr>
            </thead>
            <tbody>
              ${trace.map((t) => {
                const badgeClass = t.status === 'passed' ? 'approved' : t.status === 'skipped' ? 'processing' : 'rejected';
                return `
                  <tr>
                    <td>
                      <span class="rule-name">${t.rule}</span>
                      <span class="rule-desc">on fail: ${t.on_fail}</span>
                    </td>
                    <td><span class="badge-stage">${t.stage || '-'}</span></td>
                    <td><span class="status-pill ${badgeClass}">${t.status}</span></td>
                    <td><code style="font-family:var(--font-mono);">${t.field || '-'}</code></td>
                    <td>
                      <span style="font-family:var(--font-mono);font-size:11px;">
                        actual: <b>${t.actual !== null ? JSON.stringify(t.actual) : 'null'}</b>
                        <br>${t.op} ${t.expected !== null ? JSON.stringify(t.expected) : ''}
                      </span>
                    </td>
                    <td style="color:var(--text-muted);">${t.message || ''}</td>
                  </tr>
                `;
              }).join('')}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  // Audit Events Timeline
  if (audit && audit.events && audit.events.length > 0) {
    html += `
      <div style="margin-top:14px;">
        <div style="font-size:13px;font-weight:700;color:#fff;margin-bottom:12px;">Full Audit Trail Timeline</div>
        <div class="timeline">
          ${audit.events.map((e) => `
            <div class="timeline-item">
              <div class="timeline-dot"></div>
              <div class="timeline-header">
                <span class="timeline-event">${e.stage ? `[${e.stage}] ` : ''}${e.event}</span>
                <span class="timeline-time">${new Date(e.at).toLocaleTimeString()}</span>
              </div>
              ${Object.keys(e.detail || {}).length > 0 ? `
                <div class="timeline-detail">${JSON.stringify(e.detail)}</div>
              ` : ''}
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  el.inspectorContent.innerHTML = html;
}

// Review / Retry Actions
window.onReviewSubmit = async function (requestId, decision) {
  const reviewer = document.getElementById('review-reviewer').value.trim() || 'Reviewer';
  const note = document.getElementById('review-note').value.trim();

  try {
    await api(`/requests/${requestId}/review`, {
      method: 'POST',
      body: JSON.stringify({ decision, reviewer, note }),
    });
    showToast(`Decision recorded: ${decision.toUpperCase()}`, 'success');
    await inspectRequest(requestId);
    await refreshStats();
    await loadHistory();
  } catch (err) {
    showToast(`Review failed: ${err.message}`, 'error');
  }
};

window.onRetrySubmit = async function (requestId) {
  try {
    await api(`/requests/${requestId}/retry`, { method: 'POST' });
    showToast('Retry dispatched successfully', 'success');
    await inspectRequest(requestId);
    await refreshStats();
    await loadHistory();
  } catch (err) {
    showToast(`Retry failed: ${err.message}`, 'error');
  }
};

// Request History Table
async function loadHistory() {
  try {
    const list = await api('/requests');
    STATE.requestsHistory = list;
    el.historyTableBody.innerHTML = '';

    if (list.length === 0) {
      el.historyTableBody.innerHTML = `
        <tr><td colspan="6" style="text-align:center;color:var(--text-dim);padding:24px;">No requests found in database.</td></tr>
      `;
      return;
    }

    list.forEach((r) => {
      const tr = document.createElement('tr');
      const statusClass = getStatusClass(r.status);
      tr.innerHTML = `
        <td style="font-family:var(--font-mono);font-weight:600;color:#fff;">${r.id}</td>
        <td>${r.workflow}</td>
        <td><span class="status-pill ${statusClass}">${r.status}</span></td>
        <td><span class="badge-stage">${r.current_stage || 'complete'}</span></td>
        <td>${r.retry_count}</td>
        <td style="color:var(--text-dim);font-size:12px;">${new Date(r.created_at).toLocaleString()}</td>
      `;
      tr.onclick = () => {
        // Switch to console tab and inspect
        switchTab('console');
        inspectRequest(r.id);
      };
      el.historyTableBody.appendChild(tr);
    });
  } catch (err) {
    console.error('Failed to load history', err);
  }
}

// Workflow Architecture Tab
function renderWorkflowArchitecture(wf) {
  if (!wf) return;

  // Pipeline Flow Nodes
  let flowHtml = '';
  const stages = wf.stages || [];
  stages.forEach((s, idx) => {
    flowHtml += `
      <div class="pipeline-node">
        <div style="font-size:11px;color:var(--text-dim);text-transform:uppercase;">Stage ${idx + 1}</div>
        <div style="font-weight:700;color:#fff;">${s.name}</div>
        <div style="font-size:11px;color:var(--text-muted);">
          Type: <b>${s.type}</b>${s.dependency ? ` (${s.dependency})` : ''}
        </div>
        <div style="font-size:11px;color:var(--text-dim);">
          Rules: ${s.rules ? s.rules.join(', ') : 'None'}
        </div>
      </div>
    `;

    if (s.next) {
      flowHtml += `
        <div class="pipeline-arrow">➔</div>
      `;
    }
  });

  flowHtml += `
    <div class="pipeline-node" style="border-color:var(--status-approved-border);background:var(--status-approved-bg);">
      <div style="font-size:11px;color:var(--status-approved);text-transform:uppercase;">Terminal</div>
      <div style="font-weight:700;color:#fff;">APPROVE</div>
      <div style="font-size:11px;color:var(--text-muted);">All stages cleared</div>
    </div>
  `;
  el.pipelineFlow.innerHTML = flowHtml;

  // Rules Catalog
  const rules = Object.values(wf.rules || {});
  let rulesHtml = `
    <table class="rules-table">
      <thead>
        <tr>
          <th>Rule ID</th>
          <th>Type</th>
          <th>Field</th>
          <th>Condition / Operator</th>
          <th>Threshold</th>
          <th>On Fail Action</th>
          <th>Description</th>
        </tr>
      </thead>
      <tbody>
        ${rules.map((r) => `
          <tr>
            <td style="font-weight:600;color:#fff;">${r.id}</td>
            <td><span class="badge-stage">${r.type}</span></td>
            <td><code>${r.field}</code></td>
            <td><code style="color:var(--primary);">${r.op}</code></td>
            <td>${r.value !== null && r.value !== undefined ? JSON.stringify(r.value) : '-'}</td>
            <td><span class="status-pill ${r.on_fail === 'reject' ? 'rejected' : 'manual_review'}">${r.on_fail}</span></td>
            <td style="color:var(--text-muted);">${r.description || '-'}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
  el.rulesCatalog.innerHTML = rulesHtml;
}

// Tab Switching
function switchTab(tabId) {
  document.querySelectorAll('.tab-btn').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.tab === tabId);
  });
  document.querySelectorAll('.tab-content').forEach((content) => {
    content.classList.toggle('active', content.id === `tab-${tabId}`);
  });

  if (tabId === 'history') {
    loadHistory();
  }
}

// Event Bindings
document.querySelectorAll('.tab-btn').forEach((btn) => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

el.workflowSelect.addEventListener('change', (e) => onWorkflowChanged(e.target.value));

el.btnToggleMode.addEventListener('click', () => {
  STATE.editorMode = STATE.editorMode === 'form' ? 'json' : 'form';
  if (STATE.editorMode === 'json') {
    syncFormToJson();
    el.formContainer.style.display = 'none';
    el.jsonEditor.style.display = 'block';
    el.btnToggleMode.textContent = 'Switch to Form View';
  } else {
    try {
      const parsed = JSON.parse(el.jsonEditor.value);
      populateFormFromObject(parsed);
    } catch (e) {
      // ignore
    }
    el.formContainer.style.display = 'flex';
    el.jsonEditor.style.display = 'none';
    el.btnToggleMode.textContent = 'Switch to JSON View';
  }
});

el.btnGenKey.addEventListener('click', () => {
  const key = 'key_' + Math.random().toString(36).substring(2, 10);
  el.idempotencyInput.value = key;
  showToast(`Generated Idempotency Key: ${key}`);
});

el.btnReloadWorkflows.addEventListener('click', async () => {
  try {
    const res = await api('/workflows/reload', { method: 'POST' });
    showToast(`Workflows hot-reloaded: ${res.loaded.join(', ')}`, 'success');
    await initWorkflows();
  } catch (err) {
    showToast(`Reload failed: ${err.message}`, 'error');
  }
});

el.btnSubmit.addEventListener('click', submitDecision);
el.btnRefreshHistory.addEventListener('click', loadHistory);

// Backend URL update
el.backendUrlInput.value = STATE.backendUrl;
el.backendUrlInput.addEventListener('change', (e) => {
  STATE.backendUrl = e.target.value.trim().replace(/\/$/, '');
  localStorage.setItem('decision_backend_url', STATE.backendUrl);
  showToast(`Backend set to ${STATE.backendUrl}`);
  checkHealth();
  initWorkflows();
});

// Initial boot
window.addEventListener('DOMContentLoaded', async () => {
  await checkHealth();
  await initWorkflows();
  await loadHistory();
  // Poll health and stats every 10 seconds
  setInterval(checkHealth, 10000);
});

