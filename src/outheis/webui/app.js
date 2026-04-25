/**
 * outheis Web UI
 */

// Mobile sidebar toggle
function _initSidebar() {
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('sidebar-overlay');
  const hamburger = document.getElementById('hamburger');
  if (!sidebar || !overlay || !hamburger) return;

  function openSidebar() { sidebar.classList.add('open'); overlay.classList.add('open'); }
  function closeSidebar() { sidebar.classList.remove('open'); overlay.classList.remove('open'); }

  hamburger.addEventListener('click', openSidebar);
  overlay.addEventListener('click', closeSidebar);
  sidebar.querySelectorAll('.nav-item').forEach(el => el.addEventListener('click', closeSidebar));
}

document.addEventListener('DOMContentLoaded', _initSidebar);

let currentView = 'overview';
let currentTab = 'general';
let currentFile = null;
let fileMode = 'rendered';
let currentEditor = null;
let ws = null;
let config = null;
const taskDurations = {}; // {type: {seconds, ok}} — persists across re-renders
const activePolls = {};  // {type: {intervalId, btn}} — cleared on reconnect

// File auto-refresh: poll mtime every 4s; reload if changed externally
let _fileRefreshInterval = null;
let _fileRefreshMtime = null;
let _fileRefreshDirty = false; // true when user has unsaved edits

// File list auto-refresh: poll list every 5s; update sidebar if files added/removed/renamed
let _fileListInterval = null;

// Snapshot of file list for change detection: name → modified mtime
let _fileListSnapshot = {};

function _applyFileList(container, type, newList) {
  const countEl = document.getElementById(`${type}-count`);
  if (countEl) countEl.textContent = String(newList.length);
  container.querySelectorAll('.file-item').forEach((el) => el.remove());
  const fragment = document.createDocumentFragment();
  for (const f of newList) {
    const div = document.createElement('div');
    div.className = 'file-item' + (f.name === currentFile ? ' active' : '');
    div.dataset.filename = f.name;
    div.onclick = () => openFileEl(div, type);
    div.innerHTML = `<span>${escapeHtml(f.name)}</span><span class="file-size">${formatSize(f.size)}</span>`;
    fragment.appendChild(div);
  }
  container.appendChild(fragment);
  _fileListSnapshot = Object.fromEntries(newList.map((f) => [f.name, f.modified ?? f.size]));
}

function startFileListRefresh(type) {
  stopFileListRefresh();
  _fileListInterval = setInterval(async () => {
    if (currentView !== type) { stopFileListRefresh(); return; }
    try {
      const files = await fetchAPI(`/api/${type}`);
      const newList = Array.isArray(files) ? files : files.files || [];
      const container = document.querySelector('.file-list');
      if (!container) return;
      // Detect any change: name set, order, or mtime/size of any entry
      const newSnap = Object.fromEntries(newList.map((f) => [f.name, f.modified ?? f.size]));
      const changed = JSON.stringify(newSnap) !== JSON.stringify(_fileListSnapshot);
      if (!changed) return;
      const currentFileMtimeBefore = _fileListSnapshot[currentFile];
      _applyFileList(container, type, newList);
      // If current file was removed, open first available
      if (newList.length && !newList.some((f) => f.name === currentFile)) {
        currentFile = newList[0].name;
        openFile(type, currentFile);
      } else if (currentFile && newSnap[currentFile] !== currentFileMtimeBefore && !_fileRefreshDirty) {
        // Current file changed on disk — reload it
        await loadFile(type, currentFile);
      }
    } catch (_) {}
  }, 5000);
}

async function refreshFileList(type, btn) {
  if (btn) { btn.classList.add('spinning'); btn.disabled = true; }
  try {
    const files = await fetchAPI(`/api/${type}`);
    const newList = Array.isArray(files) ? files : files.files || [];
    const container = document.querySelector('.file-list');
    if (container) {
      _applyFileList(container, type, newList);
      if (newList.length && !newList.some((f) => f.name === currentFile)) {
        currentFile = newList[0].name;
        await openFile(type, currentFile);
      } else if (currentFile && !_fileRefreshDirty) {
        await loadFile(type, currentFile);
      }
    }
  } catch (_) {}
  if (btn) { setTimeout(() => { btn.classList.remove('spinning'); btn.disabled = false; }, 400); }
}

function stopFileListRefresh() {
  if (_fileListInterval) { clearInterval(_fileListInterval); _fileListInterval = null; }
}

function startFileRefresh(type, filename) {
  stopFileRefresh();
  _fileRefreshMtime = null;
  _fileRefreshDirty = false;
  _fileRefreshInterval = setInterval(async () => {
    if (_fileRefreshDirty) return; // user editing — skip
    if (!currentFile || currentFile !== filename || currentView !== type) {
      stopFileRefresh();
      return;
    }
    try {
      const data = await fetchAPI(`/api/mtime?type=${type}&filename=${encodeURIComponent(filename)}`);
      if (data.error) return;
      if (_fileRefreshMtime === null) { _fileRefreshMtime = data.mtime; return; }
      if (data.mtime !== _fileRefreshMtime) {
        _fileRefreshMtime = data.mtime;
        await loadFile(type, filename);
      }
    } catch (_) {}
  }, 4000);
}

function stopFileRefresh() {
  if (_fileRefreshInterval) { clearInterval(_fileRefreshInterval); _fileRefreshInterval = null; }
}

const viewTitle = document.getElementById('view-title');
const viewPath = document.getElementById('view-path');
const viewTabs = document.getElementById('view-tabs');
const viewContent = document.getElementById('view-content');
const viewActions = document.getElementById('view-actions');
const statusEl = document.getElementById('status');
const connectionStatus = document.getElementById('connection-status');

// Agent definitions
const AGENTS = [
  { key: 'relay', name: 'ou', role: 'Coordination, routing, user interface' },
  { key: 'data', name: 'zeno', role: 'Vault access, search, indexing' },
  { key: 'agenda', name: 'cato', role: 'Agenda.md, Exchange.md' },
  { key: 'action', name: 'hiro', role: 'Task execution, background jobs' },
  { key: 'pattern', name: 'rumi', role: 'Memory extraction, skill distillation' },
  { key: 'code', name: 'alan', role: 'Code introspection, proposals' },
];

// Navigation
document.getElementById('nav').addEventListener('click', (e) => {
  const item = e.target.closest('.nav-item');
  if (!item) return;
  document.querySelectorAll('.nav-item').forEach((el) => el.classList.remove('active'));
  item.classList.add('active');
  currentView = item.dataset.view;
  currentTab = 'general';
  location.hash = currentView;
  renderView();
});

// Views
async function renderView() {
  viewTabs.innerHTML = '';
  viewActions.innerHTML = '';
  stopFileRefresh();
  stopFileListRefresh();
  if (currentEditor) { try { currentEditor.destroy(); } catch (_) {} currentEditor = null; }

  switch (currentView) {
    case 'overview':
      await renderOverview();
      break;
    case 'config':
      await renderConfig();
      break;
    case 'messages':
      await renderMessages();
      break;
    case 'scheduler':
      await renderScheduler();
      break;
    case 'memory':
      await renderFileView('memory', '~/.outheis/human/memory/');
      break;
    case 'skills':
      await renderFileView('skills', '~/.outheis/human/skills/');
      break;
    case 'rules':
      await renderFileView('rules', '~/.outheis/human/rules/');
      break;
case 'agenda':
      await renderAgendaView();
      break;
    case 'codebase':
      await renderFileView('codebase', 'vault/Codebase/');
      break;
    case 'files':
      await renderFileView('files', 'vault/');
      break;
    case 'tags':
      await renderTags();
      break;
    case 'migration':
      await renderMigration();
      break;
  }
}

// Overview
async function renderOverview() {
  viewTitle.textContent = 'Overview';
  viewPath.textContent = '';

  const [status, cfg] = await Promise.all([
    fetchAPI('/api/status'),
    config ? Promise.resolve(config) : fetchAPI('/api/config'),
  ]);
  if (!config) config = cfg;

  // Resolve fallback alias → provider + model name
  const fbAlias = (status.system_mode === 'fallback' && status.fallback_model && status.fallback_model !== 'none')
    ? status.fallback_model : null;
  let fbProvider = '', fbModelName = '', fbStage = '';
  if (fbAlias) {
    const provAliases = cfg.llm?.provider_aliases || {};
    const models = cfg.llm?.models || {};
    const fallbackOrder = cfg.llm?.fallback_order || [];
    const searchOrder = fallbackOrder.length
      ? [...fallbackOrder, ...Object.keys(provAliases).filter(p => !fallbackOrder.includes(p))]
      : Object.keys(provAliases);
    for (const p of searchOrder) {
      if (provAliases[p]?.[fbAlias]) { fbProvider = p; fbModelName = provAliases[p][fbAlias]; break; }
    }
    if (!fbProvider && models[fbAlias]) {
      const m = models[fbAlias];
      fbProvider = typeof m === 'object' ? (m.provider || '') : '';
      fbModelName = typeof m === 'object' ? (m.name || '') : String(m);
    }
    if (fallbackOrder.length && fbProvider) {
      const idx = fallbackOrder.indexOf(fbProvider);
      if (idx >= 0) fbStage = `stage ${idx + 1} of ${fallbackOrder.length}`;
    }
  }

  // Determine which provider failed — only reliable when fallback_order is configured
  const fbFailedProvider = (() => {
    const fallbackOrder = cfg.llm?.fallback_order || [];
    if (!fallbackOrder.length) return null;
    if (fbProvider) {
      const idx = fallbackOrder.indexOf(fbProvider);
      return idx > 0 ? fallbackOrder[idx - 1] : fallbackOrder[0];
    }
    return fallbackOrder[0];
  })();

  // Extract human-readable error message without guessing categories
  const fbExtractReason = (raw) => {
    if (!raw) return 'unavailable';
    // Try to extract 'message': '...' from Python exception string
    const m = raw.match(/'message':\s*'([^']+)'/);
    if (m) return m[1];
    const m2 = raw.match(/"message":\s*"([^"]+)"/);
    if (m2) return m2[1];
    // Strip "Error code: 400 - " prefix
    const stripped = raw.replace(/^Error code:\s*\d+\s*-\s*/i, '').trim();
    return stripped.length > 120 ? stripped.slice(0, 120) + '…' : stripped;
  };

  // Build per-stage cause lines: failed stages with reason, current stage as active
  const fbStageLines = (() => {
    const fallbackOrder = cfg.llm?.fallback_order || [];
    const lines = [];
    if (fallbackOrder.length && fbProvider) {
      const currentIdx = fallbackOrder.indexOf(fbProvider);
      for (let i = 0; i < fallbackOrder.length; i++) {
        const p = fallbackOrder[i];
        if (i < currentIdx) {
          const reason = i === currentIdx - 1 ? fbExtractReason(status.fallback_reason) : 'unavailable';
          lines.push(`${p} (stage ${i + 1}): ${reason}`);
        } else if (i === currentIdx) {
          lines.push(`${p} (stage ${i + 1}): active`);
        }
      }
    } else {
      // No fallback_order — can't reliably identify which provider failed, just show reason
      const reason = fbExtractReason(status.fallback_reason);
      if (reason) lines.push(reason);
      if (fbProvider) lines.push(`${fbProvider}: active`);
    }
    return lines;
  })();

  // Per-agent lines: always show when in fallback, resolve to provider:model if possible
  const fbAgentLines = (() => {
    if (status.system_mode !== 'fallback') return [];
    const agents = cfg.agents || {};
    const cloudAgents = ['relay', 'data', 'agenda', 'pattern', 'code'];
    const modelLabel = fbProvider && fbModelName ? `${fbProvider}: ${fbModelName}` : fbAlias || '?';
    return Object.entries(agents)
      .filter(([role, a]) => a.enabled && cloudAgents.includes(role))
      .map(([role]) => `${role}: ${modelLabel}`);
  })();

  const msgCountEl = document.getElementById('msg-count');
  if (msgCountEl) msgCountEl.textContent = status.messages_today || 0;
  const allMessages = await fetchAPI('/api/messages?limit=100');
  const conversations = allMessages.filter((msg) => msg.from?.user || msg.to === 'transport').slice(0, 10);

  viewContent.innerHTML = `
    <div class="scroll">
      <div class="metrics">
        <div class="metric">
          <div class="metric-label">Dispatcher</div>
          <div class="metric-value ${status.running ? (status.system_mode === 'fallback' ? 'warning' : 'success') : ''}">${status.running ? (status.system_mode === 'fallback' ? `Fallback${fbStage ? ` (${fbStage})` : ''}` : 'Running') : 'Stopped'}</div>
          ${status.system_mode === 'fallback' && fbStageLines.length ? `<div style="font-size:12px;color:var(--text-tertiary);margin-top:4px;line-height:1.6;">${fbStageLines.join('<br>')}</div>` : ''}
        </div>
        ${status.system_mode === 'fallback' ? `
        <div class="metric" style="grid-column: 1 / -1;">
          <div class="metric-label">Fallback model</div>
          <div class="metric-value warning" style="font-size:14px;line-height:1.8;">${fbAgentLines.length ? fbAgentLines.join('<br>') : (fbProvider ? `${fbProvider}: ${fbModelName}` : status.fallback_model || '?')}</div>
        </div>` : ''}
        <div class="metric">
          <div class="metric-label">Active agents</div>
          <div class="metric-value">${status.enabled_agents} / ${status.total_agents}</div>
        </div>
        <div class="metric">
          <div class="metric-label">Messages today</div>
          <div class="metric-value">${status.messages_today}</div>
        </div>
        <div class="metric">
          <div class="metric-label">PID</div>
          <div class="metric-value">${status.pid || '—'}</div>
        </div>
        <div class="metric" style="grid-column: 1 / -1; display: flex; gap: 10px; flex-wrap: wrap; align-items: center;">
          ${status.running ? `<button class="btn-restart" onclick="restartDaemon()">Restart outheis</button>` : ''}
          ${status.auth_required ? `<button class="btn" onclick="logout()" style="border-color: var(--text-primary)">Logout</button>` : ''}
          <div id="overview-update-slot" style="display:flex;align-items:center;gap:8px;"></div>
        </div>
      </div>
      <div class="card">
        <div class="card-header"><span class="card-title">Recent conversations</span></div>
        ${conversations.length ? conversations.map((msg) => renderMessage(msg)).join('') : '<div class="msg-item"><div class="msg-text" style="color: var(--text-tertiary);">No conversations yet</div></div>'}
      </div>
    </div>
  `;

  if (status.running) {
    statusEl.classList.add('running');
    statusEl.classList.toggle('fallback', status.system_mode === 'fallback');
  } else {
    statusEl.classList.remove('running');
    statusEl.classList.remove('fallback');
  }

  checkForUpdate();
}

function renderMessage(msg) {
  const time = msg.timestamp ? new Date(msg.timestamp * 1000).toLocaleString() : '';
  const from = msg.from?.agent || msg.from?.user?.name || msg.from?.user?.identity || 'system';
  const to = msg.to || '';
  const text = msg.payload?.text || msg.payload?.error || JSON.stringify(msg.payload || {});

  const knownAgents = ['relay', 'data', 'agenda', 'action', 'pattern', 'code', 'scheduler', 'webui', 'dispatcher', 'transport'];
  const grayAgents  = ['webui', 'dispatcher', 'transport'];
  const agentTag = (id, isUser) => {
    if (isUser) return 'agent-human';
    if (grayAgents.includes(id)) return 'agent-gray';
    return knownAgents.includes(id) ? `agent-${id}` : 'info';
  };
  const fromIsUser = !!msg.from?.user;
  const fromClass = agentTag(from, fromIsUser);
  const toClass   = agentTag(to, false);

  const routing = to
    ? `<span class="msg-agent ${fromClass}">${from}</span><span class="msg-arrow">→</span><span class="msg-agent ${toClass}">${to}</span>`
    : `<span class="msg-agent ${fromClass}">${from}</span>`;

  return `
    <div class="msg-item">
      <div class="msg-header">
        <span class="msg-time">${time}</span>
        <span class="msg-routing">${routing}</span>
      </div>
      <div class="msg-text">${escapeHtml(String(text))}</div>
    </div>
  `;
}

// Config
async function renderConfig() {
  viewTitle.textContent = 'Configuration';
  viewPath.textContent = '~/.outheis/human/config.json';
  viewActions.innerHTML = '<button class="btn btn-primary" onclick="saveConfig()">Save changes</button>';

  const tabs = ['general', 'providers', 'models', 'agents', 'signal'];
  viewTabs.innerHTML = tabs
    .map((t) => `<div class="tab ${t === currentTab ? 'active' : ''}" onclick="switchConfigTab('${t}')">${t.charAt(0).toUpperCase() + t.slice(1)}</div>`)
    .join('');

  config = await fetchAPI('/api/config');
  await renderConfigTab();
}

function switchConfigTab(tab) {
  currentTab = tab;
  document.querySelectorAll('.tab').forEach((t, i) => {
    t.classList.toggle('active', ['general', 'providers', 'models', 'agents', 'signal'].indexOf(tab) === i);
  });
  renderConfigTab();
}

async function renderConfigTab() {
  switch (currentTab) {
    case 'general':
      await renderConfigGeneral();
      break;
    case 'providers':
      renderConfigProviders();
      break;
    case 'models':
      await renderConfigModels();
      break;
    case 'agents':
      renderConfigAgents();
      break;
    case 'signal':
      renderConfigSignal();
      break;
  }
}

function _buildStateOptions(regionsData, country, selectedState) {
  const region = (regionsData || []).find(r => r.country === country);
  const states = region ? region.states : [];
  const noneSelected = !selectedState ? 'selected' : '';
  return `<option value="" ${noneSelected}>— country-wide —</option>` +
    states.map(s => `<option value="${s}" ${selectedState === s ? 'selected' : ''}>${s}</option>`).join('');
}

function updateHolidaysStateDropdown() {
  const country = document.getElementById('cfg-holidays-country')?.value || '';
  const stateEl = document.getElementById('cfg-holidays-state');
  if (stateEl) stateEl.innerHTML = _buildStateOptions(window._regionsData || [], country, '');
}

async function renderConfigGeneral() {
  const regionsResp = await fetchAPI('/api/regions').catch(() => ({ regions: [] }));
  const regionsData = regionsResp.regions || [];
  window._regionsData = regionsData;
  viewContent.innerHTML = `
    <div class="scroll">
      <div class="card">
        <div class="card-header"><span class="card-title">User profile</span></div>
        <div class="card-body">
          <div class="form-row">
            <label class="form-label">Name</label>
            <div class="form-value"><input type="text" id="cfg-name" value="${config.human?.name || ''}"></div>
          </div>
          <div class="form-row">
            <label class="form-label">Email</label>
            <div class="form-value"><input type="email" id="cfg-email" value="${config.human?.email || ''}"></div>
          </div>
          <div class="form-row">
            <label class="form-label">Phone</label>
            <div class="form-value"><input type="text" id="cfg-phone" value="${config.human?.phone || ''}"></div>
          </div>
          <div class="form-row">
            <label class="form-label">Language</label>
            <div class="form-value">
              <select id="cfg-language">
                <option value="de" ${config.human?.language === 'de' ? 'selected' : ''}>de</option>
                <option value="en" ${config.human?.language === 'en' ? 'selected' : ''}>en</option>
              </select>
            </div>
          </div>
          <div class="form-row">
            <label class="form-label">Timezone</label>
            <div class="form-value">
              <select id="cfg-timezone">
                <option value="Europe/Berlin" ${config.human?.timezone === 'Europe/Berlin' ? 'selected' : ''}>Europe/Berlin</option>
                <option value="Europe/London" ${config.human?.timezone === 'Europe/London' ? 'selected' : ''}>Europe/London</option>
                <option value="America/New_York" ${config.human?.timezone === 'America/New_York' ? 'selected' : ''}>America/New_York</option>
                <option value="UTC" ${config.human?.timezone === 'UTC' ? 'selected' : ''}>UTC</option>
              </select>
            </div>
          </div>
          <div class="form-row">
            <label class="form-label">Country</label>
            <div class="form-value">
              <select id="cfg-holidays-country" onchange="updateHolidaysStateDropdown()">
                <option value="">— none —</option>
                ${(regionsData || []).map(r =>
                  `<option value="${r.country}" ${(config.human?.holidays?.country || '') === r.country ? 'selected' : ''}>${r.country}</option>`
                ).join('')}
              </select>
            </div>
          </div>
          <div class="form-row">
            <label class="form-label">State / Region</label>
            <div class="form-value">
              <select id="cfg-holidays-state">
                ${_buildStateOptions(regionsData, config.human?.holidays?.country || '', config.human?.holidays?.state || '')}
              </select>
            </div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <span class="card-title">Vaults</span>
          <button class="btn" onclick="addVault()">+ Add vault</button>
        </div>
        <div class="card-body" id="vaults-container">
          ${(config.human?.vault || [])
            .map(
              (v, i) => `
            <div class="form-row">
              <label class="form-label">${i === 0 ? 'Primary' : 'Secondary'}</label>
              <div class="form-value">
                <input type="text" class="vault-input" value="${v}">
                <button class="btn btn-icon danger" onclick="removeRow(this)">×</button>
              </div>
            </div>
          `
            )
            .join('')}
        </div>
      </div>

      <div class="card">
        <div class="card-header"><span class="card-title">Web UI</span></div>
        <div class="card-body">
          <div class="form-row">
            <label class="form-label">Host</label>
            <div class="form-value">
              <input type="text" id="cfg-webui-host" value="${config.webui?.host || '127.0.0.1'}" placeholder="127.0.0.1" oninput="updateWebuiHostWarning()">
              <span class="form-hint" id="cfg-webui-host-hint" style="${(config.webui?.host && config.webui.host !== '127.0.0.1') ? '' : 'display:none'}; color: var(--accent-danger); opacity: 1;">Warning: binding to a non-loopback address exposes the Web UI on the network. Use at your own risk. Requires daemon restart.</span>
            </div>
          </div>
          <div class="form-row">
            <label class="form-label">Port</label>
            <div class="form-value">
              <input type="number" id="cfg-webui-port" value="${config.webui?.port || 8080}" min="1024" max="65535">
              <span class="form-hint">Requires daemon restart to take effect.</span>
            </div>
          </div>
          <div class="form-row">
            <label class="form-label">Password</label>
            <div class="form-value">
              <input type="password" id="cfg-webui-password" value="${config.webui?.password || ''}" placeholder="Leave empty to disable auth">
              <button type="button" class="btn-show" onclick="togglePasswordVisibility('cfg-webui-password', this)">SHOW</button>
              <span class="form-hint">If set, the Web UI requires login. Leave empty for open access.</span>
            </div>
          </div>
          <div class="form-row">
            <label class="form-label">Session hours</label>
            <div class="form-value">
              <input type="number" id="cfg-webui-session-hours" value="${config.webui?.session_hours ?? 4}" min="1" max="720">
              <span class="form-hint">How long a login session stays valid before re-authentication is required.</span>
            </div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-header"><span class="card-title">Agenda</span></div>
        <div class="card-body">
          <div class="form-row">
            <label class="form-label">Done retention (days)</label>
            <div class="form-value">
              <input type="number" id="cfg-agenda-retention" value="${config.agents?.agenda?.retention ?? ''}" min="1" placeholder="Leave empty to keep forever">
              <span class="form-hint">How many days completed (#done-*) items remain in Shadow.md before being pruned. Empty = keep forever.</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  `;
}

function renderConfigProviders() {
  viewContent.innerHTML = `
    <div class="scroll">
      <div class="card">
        <div class="card-header"><span class="card-title">LLM Providers</span></div>
        <div class="card-body">
          <div class="providers">
            ${renderProviderCard('anthropic', config.llm?.providers?.anthropic)}
            ${renderProviderCard('openai', config.llm?.providers?.openai)}
            ${renderOllamaGroup(config.llm?.providers?.ollama)}
          </div>
        </div>
      </div>
    </div>
  `;
}

function renderProviderCard(name, providerConfig) {
  const isActive = !!providerConfig?.api_key;
  const displayName = name.charAt(0).toUpperCase() + name.slice(1);
  return `
    <div class="provider">
      <div class="provider-header">
        <span class="provider-name">${displayName}</span>
        <span class="provider-dot ${isActive ? 'active' : ''}"></span>
      </div>
      <div class="provider-field">
        <div class="provider-field-label-row">
          <label>API key</label>
          <button class="btn-show-key" onclick="toggleKeyVisibility('cfg-${name}-key', this)">show</button>
        </div>
        <input type="password" id="cfg-${name}-key" value="${providerConfig?.api_key || ''}" placeholder="sk-...">
      </div>
      <div class="provider-field">
        <label>Base URL</label>
        <input type="text" id="cfg-${name}-url" value="${providerConfig?.base_url || getDefaultUrl(name)}">
      </div>
    </div>
  `;
}

function renderOllamaGroup(ollamaConfig) {
  const local = ollamaConfig?.local || {};
  const cloud = ollamaConfig?.cloud || {};
  const localActive = !!local.base_url;
  const cloudActive = !!cloud.api_key;
  return `
    <div class="provider">
      <div class="provider-header">
        <span class="provider-name">Ollama</span>
      </div>
      <div style="display:flex;flex-direction:column;gap:12px;">
        <div style="border:1px solid var(--border);border-radius:6px;padding:12px;">
          <div class="provider-header" style="margin-bottom:8px;">
            <span class="provider-name" style="font-size:12px;opacity:.7">local</span>
            <span class="provider-dot ${localActive ? 'active' : ''}"></span>
          </div>
          <div class="provider-field">
            <label>Base URL</label>
            <input type="text" id="cfg-ollama-local-url" value="${local.base_url || 'http://localhost:11434'}">
          </div>
          <div class="provider-field">
            <label>Environment variables <span style="font-weight:400;opacity:.6">(passed to ollama serve)</span></label>
            <div id="cfg-ollama-local-envvars">
              ${Object.entries(local.env_vars || {}).map(([k, v]) =>
                `<div class="form-row">
                  <input type="text" class="ollama-env-key" value="${k}" placeholder="VARIABLE">
                  <input type="text" class="ollama-env-val" value="${v}" placeholder="value">
                  <button class="btn btn-sm" onclick="this.closest('.form-row').remove()">×</button>
                </div>`
              ).join('')}
            </div>
            <button class="btn btn-sm" style="margin-top:4px" onclick="addOllamaEnvVar()">+ Add variable</button>
          </div>
        </div>
        <div style="border:1px solid var(--border);border-radius:6px;padding:12px;">
          <div class="provider-header" style="margin-bottom:8px;">
            <span class="provider-name" style="font-size:12px;opacity:.7">cloud</span>
            <span class="provider-dot ${cloudActive ? 'active' : ''}"></span>
          </div>
          <div class="provider-field">
            <div class="provider-field-label-row">
              <label>API key</label>
              <button class="btn-show-key" onclick="toggleKeyVisibility('cfg-ollama-cloud-key', this)">show</button>
            </div>
            <input type="password" id="cfg-ollama-cloud-key" value="${cloud.api_key || ''}" placeholder="835a...">
          </div>
          <div class="provider-field">
            <label>Base URL</label>
            <input type="text" id="cfg-ollama-cloud-url" value="${cloud.base_url || 'https://ollama.com/v1'}">
          </div>
        </div>
      </div>
    </div>
  `;
}

const KNOWN_PROVIDERS = ['anthropic', 'openai', 'ollama.local', 'ollama.cloud'];

function _providerOptions(selected) {
  return KNOWN_PROVIDERS.map(p => `<option value="${p}" ${selected === p ? 'selected' : ''}>${p}</option>`).join('');
}

function _modelRow(alias, provider, name, ollamaModels) {
  const isOllamaLocal = provider === 'ollama.local';
  const modelField = isOllamaLocal
    ? `<select class="model-name-input" data-ollama-select="true" onfocus="refreshOllamaSelect(this)">
         <option value="">— pick a model —</option>
         ${ollamaModels.map(m => `<option value="${m}" ${name === m ? 'selected' : ''}>${m}</option>`).join('')}
       </select>`
    : `<input type="text" class="model-name-input" value="${name}">`;
  return `
    <div class="model-row" data-alias="${alias}">
      <input type="text" class="model-alias-input" value="${alias}" style="width:180px;font-weight:500;">
      <div class="model-provider"><select class="model-provider-select" onchange="onProviderChange(this)">${_providerOptions(provider)}</select></div>
      <div class="model-name">${modelField}</div>
      <button class="btn btn-icon danger" onclick="removeRow(this)">×</button>
    </div>`;
}

async function renderConfigModels() {
  const providerAliases = config.llm?.provider_aliases || {};
  const fallbackOrder = config.llm?.fallback_order || [];
  const ollamaData = await fetchAPI('/api/ollama/models');
  const ollamaModels = ollamaData?.models || [];

  // Merge provider_aliases and flat models, dedup by (provider, alias), sort by provider → alias
  const entries = [];
  const seen = new Set();
  Object.entries(providerAliases).forEach(([provider, aliases]) => {
    Object.entries(aliases).forEach(([alias, name]) => {
      entries.push([alias, provider, name]);
      seen.add(`${provider}:${alias}`);
    });
  });
  const models = config.llm?.models || {};
  Object.entries(models).forEach(([alias, m]) => {
    const provider = m?.provider || 'anthropic';
    const name = m?.name || m || '';
    if (!seen.has(`${provider}:${alias}`)) entries.push([alias, provider, name]);
  });
  entries.sort(([aA, aP], [bA, bP]) => aP !== bP ? aP.localeCompare(bP) : aA.localeCompare(bA));

  const rows = entries.map(([alias, provider, name]) => _modelRow(alias, provider, name, ollamaModels)).join('');

  viewContent.innerHTML = `
    <div class="scroll">
      <div class="card">
        <div class="card-header">
          <span class="card-title">Model aliases</span>
          <button class="btn" onclick="addModel()">+ Add alias</button>
        </div>
        <div class="card-body" style="padding:12px 20px;">
          <div class="form-row" style="margin-bottom:10px;">
            <div class="form-label" style="display:flex;align-items:center;gap:6px;">
              Fallback order
              <div class="update-info-wrap">
                <span class="update-info-icon" tabindex="0">ℹ</span>
                <div class="update-tooltip">The fallback mechanism requires the same alias names across providers to take effect.</div>
              </div>
            </div>
            <div class="form-value">
              <div id="fallback-order-list" class="fo-list">${_foRenderItems(fallbackOrder)}</div>
            </div>
          </div>
          <div id="models-container">${rows}</div>
        </div>
      </div>
    </div>
  `;
  document.querySelectorAll('#fallback-order-list .fo-item').forEach(_foBindDrag);
}

function _foRenderItems(order) {
  const items = order.map(p => `
    <div class="fo-item" draggable="true" data-provider="${p}">
      <span class="fo-handle">⠿</span>
      <span>${p}</span>
      <span class="fo-remove" onclick="this.closest('.fo-item').remove();_foUpdateArrows()">×</span>
    </div>`).join('<span class="fo-arrow">→</span>');
  return items + `
    <select onchange="foAddItem(this)" style="width:20ch;min-width:0;margin-left:16px;">
      <option value="">+ provider</option>
      ${KNOWN_PROVIDERS.map(p => `<option value="${p}">${p}</option>`).join('')}
    </select>`;
}

function _foUpdateArrows() {
  const list = document.getElementById('fallback-order-list');
  if (!list) return;
  list.querySelectorAll('.fo-arrow').forEach(a => a.remove());
  const items = [...list.querySelectorAll('.fo-item')];
  items.forEach((item, i) => {
    if (i < items.length - 1) {
      const arrow = document.createElement('span');
      arrow.className = 'fo-arrow';
      arrow.textContent = '→';
      item.after(arrow);
    }
  });
}

function foAddItem(sel) {
  const p = sel.value;
  sel.value = '';
  if (!p) return;
  const list = document.getElementById('fallback-order-list');
  if (list.querySelector(`[data-provider="${p}"]`)) return;
  const div = document.createElement('div');
  div.className = 'fo-item';
  div.draggable = true;
  div.dataset.provider = p;
  div.innerHTML = `<span class="fo-handle">⠿</span><span>${p}</span><span class="fo-remove" onclick="this.closest('.fo-item').remove();_foUpdateArrows()">×</span>`;
  _foBindDrag(div);
  const addSel = list.querySelector('select');
  if (list.querySelector('.fo-item')) {
    const arrow = document.createElement('span');
    arrow.className = 'fo-arrow';
    arrow.textContent = '→';
    addSel.before(arrow);
  }
  addSel.before(div);
}

let _foDragging = null;

function _foBindDrag(el) {
  el.addEventListener('dragstart', e => {
    _foDragging = el;
    e.dataTransfer.effectAllowed = 'move';
    setTimeout(() => el.classList.add('fo-dragging'), 0);
  });
  el.addEventListener('dragend', () => {
    el.classList.remove('fo-dragging');
    _foDragging = null;
    _foUpdateArrows();
  });
  el.addEventListener('dragover', e => {
    e.preventDefault();
    if (!_foDragging || _foDragging === el) return;
    const r = el.getBoundingClientRect();
    if (e.clientX < r.left + r.width / 2) el.before(_foDragging);
    else el.after(_foDragging);
  });
  el.addEventListener('drop', e => e.preventDefault());
}

document.addEventListener('DOMContentLoaded', () => {
  document.body.addEventListener('dragover', e => {
    if (e.target.closest('#fallback-order-list')) e.preventDefault();
  });
});

async function refreshOllamaSelect(selectEl) {
  const current = selectEl.value;
  const data = await fetchAPI('/api/ollama/models');
  const models = data?.models || [];
  selectEl.innerHTML = `<option value="">— pick a model —</option>` +
    models.map(m => `<option value="${m}" ${current === m ? 'selected' : ''}>${m}</option>`).join('');
}

function onProviderChange(providerSelect) {
  const row = providerSelect.closest('.model-row');
  const nameDiv = row.querySelector('.model-name');
  const current = nameDiv.querySelector('input, select')?.value || '';
  if (providerSelect.value === 'ollama.local') {
    nameDiv.innerHTML = `<select class="model-name-input" data-ollama-select="true" onfocus="refreshOllamaSelect(this)">
      <option value="${current}">${current || '— pick a model —'}</option>
    </select>`;
    refreshOllamaSelect(nameDiv.querySelector('select'));
  } else {
    nameDiv.innerHTML = `<input type="text" class="model-name-input" value="${current}">`;
  }
}

function renderConfigAgents() {
  viewContent.innerHTML = `
    <div class="scroll">
      <div class="card">
        <div class="card-header"><span class="card-title">Agents</span></div>
        <div class="card-body" style="padding: 12px 20px;" id="agents-container">
          ${AGENTS.map((agent) => {
            const agentConfig = config.agents?.[agent.key] || {};
            const enabled = agentConfig.enabled ?? true;
            const model = agentConfig.model || 'capable';
            return `
              <div class="agent-row" data-key="${agent.key}">
                <span class="agent-color-bar agent-color-${agent.key}"></span>
                <div class="agent-info">
                  <span class="agent-name">${agent.name}</span>
                  <span class="agent-key">${agent.key}</span>
                </div>
                <div class="agent-role">${agent.role}</div>
                <div class="agent-model">
                  <select class="agent-model-select">
                    ${[...new Set([
                      ...Object.values(config.llm?.provider_aliases || {}).flatMap(a => Object.keys(a)),
                      ...Object.keys(config.llm?.models || {}),
                    ]) ].sort().map(alias =>
                      `<option value="${alias}" ${model === alias ? 'selected' : ''}>${alias}</option>`
                    ).join('')}
                  </select>
                </div>
                <div class="agent-toggle">
                  <label style="display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text-muted);">
                    <input type="checkbox" class="agent-enabled" ${enabled ? 'checked' : ''}>
                    Enabled
                  </label>
                </div>
              </div>
            `;
          }).join('')}
        </div>
      </div>
    </div>
  `;
}

function renderConfigSignal() {
  viewContent.innerHTML = `
    <div class="scroll">
      <div class="card">
        <div class="card-header"><span class="card-title">Signal transport</span></div>
        <div class="card-body">
          <div class="form-row">
            <label class="form-label">Enabled</label>
            <div class="form-value">
              <input type="checkbox" id="cfg-signal-enabled" ${config.signal?.enabled ? 'checked' : ''}>
            </div>
          </div>
          <div class="form-row">
            <label class="form-label">Bot name</label>
            <div class="form-value">
              <input type="text" id="cfg-signal-bot-name" value="${config.signal?.bot_name || 'Ou'}">
            </div>
          </div>
          <div class="form-row">
            <label class="form-label">Bot phone</label>
            <div class="form-value">
              <input type="text" id="cfg-signal-bot-phone" value="${config.signal?.bot_phone || ''}">
            </div>
          </div>
          <div class="form-row" style="align-items: flex-start;">
            <label class="form-label">Allowed contacts</label>
            <div class="form-value" style="flex-direction: column; gap: 8px;" id="whitelist-container">
              ${(config.signal?.allowed || [])
                .map(
                  (contact) => `
                <div class="whitelist-row" style="display:flex;gap:8px;">
                  <input type="text" class="whitelist-name-input" placeholder="Name" value="${contact.name || ''}">
                  <input type="text" class="whitelist-phone-input" placeholder="+49..." value="${contact.phone || ''}">
                  <button class="btn btn-icon danger" onclick="removeRow(this)">×</button>
                </div>
              `
                )
                .join('')}
              <button class="btn" style="width: 100%;" onclick="addWhitelist()">+</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  `;
}

function getDefaultUrl(provider) {
  return {
    anthropic: 'https://api.anthropic.com',
    openai: 'https://api.openai.com/v1',
    'ollama.local': 'http://localhost:11434',
    'ollama.cloud': 'https://ollama.com/v1',
  }[provider] || '';
}

function toggleKeyVisibility(inputId, btn) {
  const input = document.getElementById(inputId);
  if (!input) return;
  const hidden = input.type === 'password';
  input.type = hidden ? 'text' : 'password';
  btn.textContent = hidden ? 'hide' : 'show';
}

function addOllamaEnvVar() {
  const container = document.getElementById('cfg-ollama-local-envvars');
  if (!container) return;
  const row = document.createElement('div');
  row.className = 'form-row';
  row.innerHTML = '<input type="text" class="ollama-env-key" placeholder="VARIABLE"> <input type="text" class="ollama-env-val" placeholder="value"> <button class="btn btn-sm" onclick="this.closest(\'.form-row\').remove()">×</button>';
  container.appendChild(row);
}

function addVault() {
  const container = document.getElementById('vaults-container');
  const count = container.querySelectorAll('.form-row').length;
  const row = document.createElement('div');
  row.className = 'form-row';
  row.innerHTML = `
    <label class="form-label">${count === 0 ? 'Primary' : 'Secondary'}</label>
    <div class="form-value">
      <input type="text" class="vault-input" placeholder="~/path/to/vault">
      <button class="btn btn-icon danger" onclick="removeRow(this)">×</button>
    </div>
  `;
  container.appendChild(row);
}

function addModel() {
  const container = document.getElementById('models-container');
  const div = document.createElement('div');
  div.innerHTML = _modelRow('', 'anthropic', '', []);
  const row = div.firstElementChild;
  container.appendChild(row);
  row.querySelector('.model-alias-input')?.focus();
}

function addWhitelist() {
  const container = document.getElementById('whitelist-container');
  const row = document.createElement('div');
  row.className = 'whitelist-row';
  row.style.cssText = 'display:flex;gap:8px;';
  row.innerHTML = `
    <input type="text" class="whitelist-name-input" placeholder="Name">
    <input type="text" class="whitelist-phone-input" placeholder="+49...">
    <button class="btn btn-icon danger" onclick="removeRow(this)">×</button>
  `;
  container.insertBefore(row, addBtn);
}

function removeRow(btn) {
  btn.closest('.form-row, .model-row, .whitelist-row, .sched-row').remove();
}

function togglePasswordVisibility(inputId, btn) {
  const input = document.getElementById(inputId);
  if (!input) return;
  const show = input.type === 'password';
  input.type = show ? 'text' : 'password';
  btn.textContent = show ? 'HIDE' : 'SHOW';
}

function updateWebuiHostWarning() {
  const host = document.getElementById('cfg-webui-host')?.value || '';
  const hint = document.getElementById('cfg-webui-host-hint');
  if (hint) hint.style.display = (host && host !== '127.0.0.1' && host !== 'localhost') ? '' : 'none';
}

async function saveConfig() {
  const updatedConfig = { ...config };

  // General tab
  const nameEl = document.getElementById('cfg-name');
  if (nameEl) {
    const holidaysCountry = document.getElementById('cfg-holidays-country')?.value?.trim() || '';
    const holidaysState = document.getElementById('cfg-holidays-state')?.value?.trim() || '';
    const retentionEl = document.getElementById('cfg-agenda-retention');
    const retentionVal = retentionEl?.value ? parseInt(retentionEl.value, 10) : null;
    updatedConfig.human = {
      ...updatedConfig.human,
      name: nameEl.value,
      email: document.getElementById('cfg-email')?.value,
      phone: document.getElementById('cfg-phone')?.value,
      language: document.getElementById('cfg-language')?.value,
      timezone: document.getElementById('cfg-timezone')?.value,
      vault: Array.from(document.querySelectorAll('.vault-input')).map((el) => el.value).filter((v) => v),
      holidays: { country: holidaysCountry, state: holidaysState },
    };
    if (retentionEl) {
      updatedConfig.agents = updatedConfig.agents || {};
      updatedConfig.agents.agenda = { ...updatedConfig.agents.agenda, retention: retentionVal };
    }
    const webuiPort = document.getElementById('cfg-webui-port');
    if (webuiPort) {
      updatedConfig.webui = {
        ...updatedConfig.webui,
        host: document.getElementById('cfg-webui-host')?.value || '127.0.0.1',
        port: parseInt(webuiPort.value, 10) || 8080,
        password: document.getElementById('cfg-webui-password')?.value ?? '',
        session_hours: parseInt(document.getElementById('cfg-webui-session-hours')?.value, 10) || 4,
      };
    }
  }

  // Providers tab
  const anthropicKey = document.getElementById('cfg-anthropic-key');
  if (anthropicKey) {
    updatedConfig.llm = updatedConfig.llm || {};
    const ollamaLocalEnvVars = (() => {
      const rows = document.querySelectorAll('#cfg-ollama-local-envvars .form-row');
      const vars = {};
      rows.forEach(row => {
        const k = row.querySelector('.ollama-env-key')?.value?.trim();
        const v = row.querySelector('.ollama-env-val')?.value?.trim();
        if (k) vars[k] = v || '';
      });
      return vars;
    })();
    updatedConfig.llm.providers = {
      anthropic: { api_key: anthropicKey.value, base_url: document.getElementById('cfg-anthropic-url')?.value },
      openai: { api_key: document.getElementById('cfg-openai-key')?.value, base_url: document.getElementById('cfg-openai-url')?.value },
      ollama: {
        local: {
          api_key: 'ollama-local',
          base_url: document.getElementById('cfg-ollama-local-url')?.value || 'http://localhost:11434',
          ...(Object.keys(ollamaLocalEnvVars).length ? { env_vars: ollamaLocalEnvVars } : {}),
        },
        cloud: {
          api_key: document.getElementById('cfg-ollama-cloud-key')?.value || '',
          base_url: document.getElementById('cfg-ollama-cloud-url')?.value || 'https://ollama.com/v1',
        },
      },
    };
  }

  // Models tab
  const container = document.getElementById('models-container');
  if (container) {
    updatedConfig.llm = updatedConfig.llm || {};
    // Build provider_aliases from flat rows: group by provider → {alias: name}
    const providerAliases = {};
    const incompleteAliases = [];
    Array.from(container.querySelectorAll('.model-row')).forEach(row => {
      const alias = row.querySelector('.model-alias-input')?.value?.trim();
      const provider = row.querySelector('.model-provider-select')?.value || '';
      const name = row.querySelector('.model-name-input')?.value?.trim() || '';
      if (!alias) return;
      if (!provider || !name) { incompleteAliases.push(`${provider||'?'}/${alias}`); row.style.outline = '1px solid var(--accent-warning)'; return; }
      row.style.outline = '';
      providerAliases[provider] = providerAliases[provider] || {};
      providerAliases[provider][alias] = name;
    });
    updatedConfig.llm.provider_aliases = Object.keys(providerAliases).length ? providerAliases : null;
    if (Object.keys(providerAliases).length) updatedConfig.llm.models = {}; // superseded by provider_aliases
    // Fallback order
    const foList = document.getElementById('fallback-order-list');
    if (foList) {
      const order = [...foList.querySelectorAll('.fo-item')].map(el => el.dataset.provider).filter(Boolean);
      updatedConfig.llm.fallback_order = order.length ? order : null;
    }
    if (incompleteAliases.length > 0) {
      showToast(`Warning: incomplete: ${incompleteAliases.join(', ')}`, 5000);
    }
  }

  // Agents tab
  const agentRows = document.querySelectorAll('.agent-row');
  if (agentRows.length > 0) {
    updatedConfig.agents = updatedConfig.agents || {};
    agentRows.forEach((row) => {
      const key = row.dataset.key;
      updatedConfig.agents[key] = {
        ...updatedConfig.agents[key],
        model: row.querySelector('.agent-model-select')?.value,
        enabled: row.querySelector('.agent-enabled')?.checked,
      };
    });
  }

  // Signal tab
  const signalEnabled = document.getElementById('cfg-signal-enabled');
  if (signalEnabled) {
    const whitelistRows = document.querySelectorAll('#whitelist-container .whitelist-row');
    updatedConfig.signal = {
      enabled: signalEnabled.checked,
      bot_name: document.getElementById('cfg-signal-bot-name')?.value,
      bot_phone: document.getElementById('cfg-signal-bot-phone')?.value,
      allowed: Array.from(whitelistRows).map((row) => ({
        name: row.querySelector('.whitelist-name-input')?.value || '',
        phone: row.querySelector('.whitelist-phone-input')?.value || '',
      })).filter((c) => c.phone),
    };
  }

  await fetchAPI('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(updatedConfig) });
  config = updatedConfig;
  showToast('Configuration saved');

}

// Messages
async function sendPrompt() {
  const textarea = document.getElementById('prompt-input');
  const text = textarea.value.trim();
  if (!text) return;
  textarea.value = '';
  textarea.disabled = true;
  try {
    await fetchAPI('/api/send', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) });
    await renderMessages();
  } finally {
    textarea.disabled = false;
    textarea.focus();
  }
}

async function renderMessages() {
  viewTitle.textContent = 'Messages';
  viewPath.textContent = '~/.outheis/human/messages.jsonl';
  viewTabs.innerHTML = '<div class="tab active">Live</div><div class="tab">Archive</div>';

  const messages = await fetchAPI('/api/messages?limit=50');
  viewContent.innerHTML = `
    <div style="display: flex; flex-direction: column; height: 100%; background: var(--bg-primary);">
      <div style="padding: 12px 16px; border-bottom: 1px solid var(--border-primary); display: flex; gap: 8px;">
        <textarea id="prompt-input" placeholder="Send a message to outheis…" rows="2" style="flex: 1; resize: none; background: var(--bg-secondary); border: 1px solid var(--border-primary); border-radius: 6px; color: var(--text-primary); font-family: inherit; font-size: 13px; padding: 8px 10px; outline: none;" onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendPrompt();}"></textarea>
        <button class="btn btn-primary" onclick="sendPrompt()" style="align-self: flex-end;">Send</button>
      </div>
      <div id="msg-list" style="overflow-y: auto; flex: 1;">
        ${messages.length ? messages.map((msg) => renderMessage(msg)).join('') : '<div class="msg-item"><div class="msg-text" style="color: var(--text-tertiary);">No messages yet</div></div>'}
      </div>
    </div>
  `;
}

// Scheduler
async function renderScheduler() {
  viewTitle.textContent = 'Scheduler';
  viewPath.textContent = '';
  viewActions.innerHTML = '<button class="btn btn-primary" onclick="saveSchedule()">Save changes</button>';
  viewTabs.innerHTML = '<div class="tab active" onclick="switchSchedulerTab(\'tasks\')">Tasks</div><div class="tab" onclick="switchSchedulerTab(\'history\')">History</div>';

  config = config || (await fetchAPI('/api/config'));
  renderSchedulerTasks();
}

function switchSchedulerTab(tab) {
  document.querySelectorAll('.tab').forEach((t, i) => t.classList.toggle('active', (tab === 'tasks' && i === 0) || (tab === 'history' && i === 1)));
  tab === 'tasks' ? renderSchedulerTasks() : renderSchedulerHistory();
}

async function renderSchedulerTasks() {
  const schedule = config.schedule || {};
  viewContent.innerHTML = `
    <div class="scroll">
      <div class="card">
        <div class="card-header">
          <span class="card-title">Scheduled tasks</span>
          <button class="btn" onclick="addScheduleTask()">+ Add task</button>
        </div>
        <div class="card-body" style="padding: 12px 20px;" id="schedule-container">
          ${renderScheduleRow('agenda_review', schedule.agenda_review)}
          ${renderScheduleRow('shadow_scan', schedule.shadow_scan)}
          ${renderScheduleRow('pattern_infer', schedule.pattern_infer)}
          ${renderScheduleRow('memory_migrate', schedule.memory_migrate)}
          ${renderScheduleRow('index_rebuild', schedule.index_rebuild)}
        </div>
      </div>
    </div>
  `;
  const { running = [] } = await fetchAPI('/api/scheduler/running');
  for (const [type, poll] of Object.entries(activePolls)) {
    const row = viewContent.querySelector(`.sched-row[data-type="${type}"]`);
    if (row) {
      const btn = row.querySelector('.sched-run-btn');
      if (!btn.dataset.originalLabel) btn.dataset.originalLabel = btn.textContent;
      poll.btn = btn;
      btn.textContent = 'Running…';
      btn.disabled = true;
    }
  }
  for (const type of running) {
    if (activePolls[type]) continue; // already tracked
    const row = viewContent.querySelector(`.sched-row[data-type="${type}"]`);
    if (row) {
      const btn = row.querySelector('.sched-run-btn');
      if (!btn.dataset.originalLabel) btn.dataset.originalLabel = btn.textContent;
      btn.textContent = 'Running…';
      btn.disabled = true;
      watchTask(type, btn);
    }
  }
}

async function renderSchedulerHistory() {
  const messages = await fetchAPI('/api/messages?limit=100');
  const schedulerMessages = messages.filter((m) => m.from === 'scheduler' || m.from_agent === 'scheduler');
  viewContent.innerHTML = `
    <div class="scroll">
      <div class="card">
        <div class="card-header"><span class="card-title">Scheduler history</span></div>
        ${schedulerMessages.length ? schedulerMessages.map((msg) => renderMessage(msg)).join('') : '<div class="msg-item"><div class="msg-text" style="color: var(--text-tertiary);">No scheduler events yet</div></div>'}
      </div>
    </div>
  `;
}

const SCHED_DEFAULTS = {
  agenda_review:    { time: Array.from({length: 20}, (_, i) => `${String(i + 4).padStart(2, '0')}:55`) },
  shadow_scan:      { time: ['03:30'] },
  pattern_infer:    { time: ['04:00'] },
  memory_migrate:   { time: ['04:00'] },
  index_rebuild:    { time: ['04:30'] },
  archive_rotation: { time: ['05:00'] },
};

const SCHED_DESCRIPTIONS = {
  agenda_review:    'cato — personal secretary service',
  shadow_scan:      'zeno scans vault for new and changed files, updates context',
  pattern_infer:    'rumi analyzes message history to extract patterns and promote them to skills and rules',
  memory_migrate:   'rumi reads Exchange.md decisions and adopts/rejects pending memory items',
  index_rebuild:    'zeno rebuilds the vault full-text search index from scratch',
  archive_rotation: 'moves old message log entries to the archive',
};

function renderScheduleRow(type, schedConfig) {
  const defaults = SCHED_DEFAULTS[type] || { time: ['04:00'] };
  const isInterval = 'interval_minutes' in (defaults);
  const cfg = Object.assign({ enabled: true }, defaults, schedConfig || {});
  const enabled = cfg.enabled ?? true;

  const dur = taskDurations[type];
  const durText = dur ? `${dur.ok ? '✓' : '✗'} ${dur.seconds}s` : '';

  const allOptions = ['agenda_review', 'shadow_scan', 'pattern_infer', 'memory_migrate', 'index_rebuild'];
  const selectOptions = allOptions.map((v) => `<option value="${v}" ${type === v ? 'selected' : ''}>${v}</option>`).join('');

  let timesHtml;
  if (isInterval) {
    const minutes = cfg.interval_minutes ?? 360;
    timesHtml = `<div class="sched-interval">every <input type="number" class="sched-interval-input" value="${minutes}" min="1" style="width:60px"> min</div>`;
  } else {
    const times = cfg.time ?? [];
    const displayTimes = times.length > 0 ? times : (SCHED_DEFAULTS[type]?.time?.length > 0 ? SCHED_DEFAULTS[type].time : null);
    const lastTime = displayTimes ? displayTimes[displayTimes.length - 1] : '04:00';
    timesHtml = `
      ${(displayTimes || []).map((t) => `<div class="sched-time"><input type="text" class="sched-time-input" value="${t}"><span class="remove" onclick="removeTime(this)">×</span></div>`).join('')}
      <div class="sched-add" onclick="addTime(this, '${lastTime}')">+</div>
    `;
  }

  return `
    <div class="sched-row" data-type="${type}">
      <div class="sched-type">
        <select class="sched-type-select" onchange="this.nextElementSibling.textContent = SCHED_DESCRIPTIONS[this.value] || ''">
          ${selectOptions}
        </select>
        <div class="sched-desc">${SCHED_DESCRIPTIONS[type] || ''}</div>
      </div>
      <div class="sched-times">${timesHtml}</div>
      <div class="sched-controls">
        <label class="sched-enabled-label">
          <input type="checkbox" class="sched-enabled" ${enabled ? 'checked' : ''}>
          Enabled
        </label>
        <button class="btn sched-run-btn" onclick="runTask('${type}', this)">Run now</button>
        <span class="sched-duration">${durText}</span>
        <button class="btn btn-icon danger" onclick="removeRow(this)">×</button>
      </div>
    </div>
  `;
}

// Watch a task that is already known to be running (no trigger time check).
// Resets the button when the task leaves the running state.
function watchTask(type, btn) {
  if (activePolls[type]) return; // already tracked
  const startedAt = Date.now();
  const originalLabel = btn.dataset.originalLabel ?? btn.textContent;
  btn.dataset.originalLabel = originalLabel;
  const intervalId = setInterval(async () => {
    const { running = [], tasks = {} } = await fetchAPI('/api/scheduler/running');
    const currentBtn = activePolls[type]?.btn ?? btn;
    if (!running.includes(type)) {
      clearInterval(intervalId);
      delete activePolls[type];
      const rec = tasks[type];
      const ok = rec?.status === 'completed';
      const seconds = Math.round((Date.now() - startedAt) / 1000);
      if (ok) taskDurations[type] = { seconds, ok: true };
      const label = currentBtn.dataset.originalLabel ?? originalLabel;
      currentBtn.textContent = ok ? '✓' : label;
      currentBtn.disabled = false;
      setTimeout(() => { currentBtn.textContent = label; }, 3000);
    }
  }, 1000);
  activePolls[type] = { intervalId, btn };
}

async function runTask(type, btn) {
  const originalLabel = btn.dataset.originalLabel ?? btn.textContent;
  btn.dataset.originalLabel = originalLabel;
  const startedAt = Date.now();
  btn.textContent = 'Running…';
  btn.disabled = true;

  const durSpan = btn.nextElementSibling; // .sched-duration span

  const res = await fetchAPI(`/api/scheduler/run/${type}`, { method: 'POST' });
  if (res.error) {
    btn.textContent = '✗';
    btn.disabled = false;
    setTimeout(() => { btn.textContent = originalLabel; }, 5000);
    return;
  }

  const triggerTime = Date.now();
  const deadline = triggerTime + 10 * 60 * 1000; // 10 min timeout

  const intervalId = setInterval(async () => {
    const label = (activePolls[type]?.btn ?? btn).dataset.originalLabel ?? originalLabel;
    if (Date.now() > deadline) {
      clearInterval(intervalId);
      delete activePolls[type];
      btn.textContent = label;
      btn.disabled = false;
      return;
    }
    const currentBtn = activePolls[type]?.btn ?? btn;
    const { running = [], tasks = {} } = await fetchAPI('/api/scheduler/running');
    const rec = tasks[type];
    const isRunning = running.includes(type);
    // Done when record has finished_at and is no longer running
    const isDone = rec && rec.finished_at && !isRunning;
    if (isDone) {
      clearInterval(intervalId);
      delete activePolls[type];
      const status = rec.status;
      const ok = status === 'completed';
      const skipped = status === 'skipped';
      const seconds = Math.round((Date.now() - startedAt) / 1000);
      if (!skipped) taskDurations[type] = { seconds, ok };
      currentBtn.textContent = ok ? '✓' : (skipped ? '⏸' : '✗');
      currentBtn.disabled = false;
      if (durSpan && !skipped) durSpan.textContent = `${ok ? '✓' : '✗'} ${seconds}s`;
      if (durSpan && skipped) durSpan.textContent = 'busy';
      setTimeout(() => { currentBtn.textContent = label; if (skipped && durSpan) durSpan.textContent = ''; }, 3000);
    }
  }, 1000);
  activePolls[type] = { intervalId, btn };
}

function addScheduleTask() {
  const container = document.getElementById('schedule-container');
  const row = document.createElement('div');
  row.className = 'sched-row';
  row.innerHTML = `
    <div class="sched-type">
      <select class="sched-type-select" onchange="this.nextElementSibling.textContent = SCHED_DESCRIPTIONS[this.value] || ''">
        <option value="agenda_review">agenda_review</option>
        <option value="shadow_scan">shadow_scan</option>
        <option value="pattern_infer">pattern_infer</option>
        <option value="memory_migrate">memory_migrate</option>
        <option value="index_rebuild">index_rebuild</option>
      </select>
      <div class="sched-desc">${SCHED_DESCRIPTIONS['agenda_review']}</div>
    </div>
    <div class="sched-times">
      <div class="sched-time"><input type="text" class="sched-time-input" value="04:00"><span class="remove" onclick="removeTime(this)">×</span></div>
      <div class="sched-add" onclick="addTime(this, '04:00')">+</div>
    </div>
    <div class="sched-controls">
      <label class="sched-enabled-label">
        <input type="checkbox" class="sched-enabled" checked>
        Enabled
      </label>
      <button class="btn sched-run-btn" onclick="runTask(this.closest('.sched-row').querySelector('.sched-type-select').value, this)">Run now</button>
      <span class="sched-duration"></span>
      <button class="btn btn-icon danger" onclick="removeRow(this)">×</button>
    </div>
  `;
  container.appendChild(row);
}

function addTime(btn, lastTime) {
  const inputs = btn.parentNode.querySelectorAll('.sched-time-input');
  const ref = inputs.length > 0 ? inputs[inputs.length - 1].value : (lastTime || '04:00');
  const [h, m] = ref.split(':').map(Number);
  const newTime = `${String((h + 1) % 24).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
  const timeEl = document.createElement('div');
  timeEl.className = 'sched-time';
  timeEl.innerHTML = `<input type="text" class="sched-time-input" value="${newTime}"><span class="remove" onclick="removeTime(this)">×</span>`;
  btn.parentNode.insertBefore(timeEl, btn);
}

function removeTime(btn) {
  const row = btn.closest('.sched-times');
  if (row.querySelectorAll('.sched-time').length > 1) btn.closest('.sched-time').remove();
}

async function saveSchedule() {
  const updatedConfig = { ...config };
  updatedConfig.schedule = {};

  document.querySelectorAll('.sched-row').forEach((row) => {
    const type = row.querySelector('.sched-type-select')?.value;
    const enabled = row.querySelector('.sched-enabled')?.checked;
    if (!type) return;
    const intervalEl = row.querySelector('.sched-interval-input');
    if (intervalEl) {
      updatedConfig.schedule[type] = { enabled, time: [], interval_minutes: parseInt(intervalEl.value, 10) || 360 };
    } else {
      const time = Array.from(row.querySelectorAll('.sched-time-input')).map((el) => el.value)
        .filter((v) => v && v.match(/^\d{2}:\d{2}$/));
      updatedConfig.schedule[type] = { enabled, time };
    }
  });

  await fetchAPI('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(updatedConfig) });
  config = updatedConfig;
  showToast('Schedule saved');
}

// File view
async function renderAgendaView() {
  viewTitle.textContent = 'Agenda';
  viewPath.textContent = 'vault/Agenda/';

  viewActions.innerHTML = `
    <button class="btn sched-run-btn" data-task="agenda_review" onclick="runTask('agenda_review', this)">Review</button>
    <button class="btn" id="migrate-shadow-btn" onclick="migrateFromShadow()" style="margin-left:6px" title="Import non-vault items from Shadow.md into agenda.json">Migrate Shadow</button>
  `;
  const { running = [] } = await fetchAPI('/api/scheduler/running');
  const reviewBtn = viewActions.querySelector('.sched-run-btn[data-task="agenda_review"]');
  if (reviewBtn) {
    if (activePolls['agenda_review']) { activePolls['agenda_review'].btn = reviewBtn; reviewBtn.textContent = 'Running…'; reviewBtn.disabled = true; }
    else if (running.includes('agenda_review')) { reviewBtn.textContent = 'Running…'; reviewBtn.disabled = true; watchTask('agenda_review', reviewBtn); }
  }

  const validTabs = ['calendar', 'agendamd', 'source', 'extern'];
  const tab = validTabs.includes(currentTab) ? currentTab : 'calendar';
  viewTabs.innerHTML = `
    <div class="tab ${tab === 'calendar' ? 'active' : ''}" onclick="switchAgendaTab('calendar')">Calendar</div>
    <div class="tab ${tab === 'agendamd' ? 'active' : ''}" onclick="switchAgendaTab('agendamd')">Notebook</div>
    <div class="tab ${tab === 'source'   ? 'active' : ''}" onclick="switchAgendaTab('source')">Source</div>
    <div class="tab ${tab === 'extern'   ? 'active' : ''}" onclick="switchAgendaTab('extern')">External</div>
  `;
  await renderAgendaTab(tab);
}

async function switchAgendaTab(tab) {
  if (currentTab === 'source' && tab !== 'source') {
    const raw = document.querySelector('.file-raw');
    if (raw) {
      try { JSON.parse(raw.textContent); }
      catch (e) {
        if (!confirm(`agenda.json hat einen Syntaxfehler:\n${e.message}\n\nTrotzdem verlassen?`)) return;
      }
    }
  }
  currentTab = tab;
  const tabOrder = ['calendar', 'agendamd', 'source', 'extern'];
  viewTabs.querySelectorAll('.tab').forEach((t, i) =>
    t.classList.toggle('active', tabOrder[i] === tab)
  );
  await renderAgendaTab(tab);
}

async function renderAgendaTab(tab) {
  stopFileListRefresh();
  if (tab === 'calendar') {
    viewContent.innerHTML = '<div style="flex:1;display:flex;padding:0 24px;overflow:hidden;"><iframe src="/agenda" style="width:100%;height:100%;border:none;display:block;flex:1;" allowfullscreen></iframe></div>';
  } else if (tab === 'source') {
    await renderSourceTab();
  } else if (tab === 'extern') {
    await renderExternTab();
  } else {
    currentFile = 'Agenda.md';
    fileMode = 'rendered';
    viewContent.innerHTML = `
      <div class="file-view" style="flex:1;display:flex;flex-direction:column;height:100%;">
        <div class="file-header">
          <span class="file-name">Agenda.md</span>
          <div class="file-toggle" style="display:flex;align-items:center;gap:6px;">
            <input type="text" id="search-input" class="search-input" placeholder="regex search…" onkeydown="if(event.key==='Enter')searchFiles('agenda');if(event.key==='Escape')closeSearch();">
            <button class="btn" onclick="searchFiles('agenda')">Search</button>
            <button class="btn" onclick="loadFile('agenda','Agenda.md')" title="Reload from disk">Refresh</button>
            <button class="btn btn-primary" onclick="saveCurrentFile()">Save</button>
          </div>
        </div>
        <div id="search-results" style="display:none;"></div>
        <div class="file-body" id="file-body" style="flex:1;overflow:auto;"></div>
      </div>
    `;
    await loadFile('agenda', 'Agenda.md');
    startFileRefresh('agenda', 'Agenda.md');
  }
}

async function renderSourceTab() {
  currentFile = null;
  fileMode = 'raw';
  viewContent.innerHTML = `
    <div class="file-view" style="flex:1;display:flex;flex-direction:column;height:100%;">
      <div class="file-header">
        <span class="file-name">agenda.json</span>
        <div class="file-toggle" style="display:flex;align-items:center;gap:6px;">
          <input type="text" id="search-input" class="search-input" placeholder="regex search…" onkeydown="if(event.key==='Enter')searchSourceJson();if(event.key==='Escape')closeSearch();">
          <button class="btn" onclick="searchSourceJson()">Search</button>
          <button class="btn" onclick="loadSourceJson()">Refresh</button>
          <button class="btn btn-primary" onclick="saveSourceJson()">Save</button>
        </div>
      </div>
      <div id="search-results" style="display:none;"></div>
      <div class="file-body" id="file-body" style="flex:1;overflow:auto;"></div>
    </div>
  `;
  await loadSourceJson();
}

async function loadSourceJson() {
  const body = document.getElementById('file-body');
  if (!body) return;
  try {
    const res = await fetch('/agenda.json?_=' + Date.now());
    const text = await res.text();
    const parsed = JSON.parse(text);
    currentFileContent = JSON.stringify(parsed, null, 2);
    body.innerHTML = `<div class="file-raw" contenteditable spellcheck="false">${escapeHtml(currentFileContent)}</div>`;
  } catch (e) {
    body.innerHTML = `<div style="padding:16px;color:var(--accent-danger);">${escapeHtml(e.message)}</div>`;
  }
}

async function saveSourceJson() {
  const raw = document.querySelector('.file-raw');
  if (!raw) return;
  const content = raw.textContent;
  try {
    JSON.parse(content);
  } catch (e) {
    showToast('Invalid JSON: ' + e.message);
    return;
  }
  const res = await fetch('/agenda.json', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
  if (res.ok) showToast('agenda.json saved');
  else showToast('Save failed');
}

function searchSourceJson() {
  const input = document.getElementById('search-input');
  const panel = document.getElementById('search-results');
  if (!input || !panel) return;
  const q = input.value.trim();
  if (!q) { panel.style.display = 'none'; return; }
  let pattern;
  try { pattern = new RegExp(q, 'i'); }
  catch (e) {
    panel.style.display = 'block';
    panel.innerHTML = `<div class="search-error">Invalid regex: ${escapeHtml(e.message)} <button class="search-close" onclick="closeSearch()">✕</button></div>`;
    return;
  }
  const raw = document.querySelector('.file-raw');
  const text = raw ? raw.textContent : (currentFileContent || '');
  const matches = [];
  text.split('\n').forEach((line, i) => {
    if (pattern.test(line)) matches.push({ line: i + 1, content: line.trim().slice(0, 200) });
  });
  panel.style.display = 'block';
  if (!matches.length) {
    panel.innerHTML = `<div class="search-empty">No matches <button class="search-close" onclick="closeSearch()">✕</button></div>`;
    return;
  }
  const rows = matches.map(({ line, content }) =>
    `<div class="search-match"><span class="search-line">:${line}</span><span class="search-content">${escapeHtml(content)}</span></div>`
  ).join('');
  panel.innerHTML = `
    <div class="search-header"><span>${matches.length} match${matches.length !== 1 ? 'es' : ''}</span><button class="search-close" onclick="closeSearch()">✕</button></div>
    <div class="search-list">${rows}</div>`;
}

const ICS_FACETS = ['misc','cato','hiro','senswork','rumi','self','zeno','ou','familie','schatzl'];

async function renderExternTab() {
  const sources = await fetchAPI('/api/agenda/ics-sources').catch(()=>[]);
  const facetSelect = (stem, current) =>
    `<select id="ics-facet-${stem}" style="font-size:12px;background:var(--bg-secondary);border:0.5px solid var(--border-secondary);color:var(--text-primary);padding:2px 6px;border-radius:2px;">
      ${ICS_FACETS.map(f=>`<option value="${f}"${f===current?' selected':''}>${f}</option>`).join('')}
    </select>`;

  const sourceRows = sources.map(s=>`
    <div style="display:flex;align-items:center;gap:12px;padding:8px 0;border-bottom:0.5px solid var(--border-secondary);">
      <span style="flex:1;font-size:13px;">${s.stem}.ics</span>
      <span style="font-size:12px;color:var(--text-tertiary);">${s.count} Termine</span>
      ${facetSelect(s.stem, s.facet)}
      <button class="btn" onclick="reimportIcs('${s.stem}',this)">Importieren</button>
    </div>`).join('');

  viewContent.innerHTML = `
    <div class="scroll" style="padding:20px;">
      <div style="margin-bottom:24px;">
        <div style="font-size:13px;font-weight:500;margin-bottom:10px;">ICS-Datei hochladen</div>
        <div id="ics-drop-zone" style="border:1px dashed var(--border-secondary);border-radius:4px;padding:24px;text-align:center;cursor:pointer;color:var(--text-tertiary);font-size:13px;"
          ondragover="event.preventDefault();this.style.borderColor='var(--accent)'"
          ondragleave="this.style.borderColor='var(--border-secondary)'"
          ondrop="handleIcsDrop(event)">
          ICS-Datei hierher ziehen oder <label style="color:var(--accent);cursor:pointer;text-decoration:underline;">
            auswählen<input type="file" accept=".ics" style="display:none" onchange="handleIcsUpload(this)">
          </label>
        </div>
      </div>
      ${sources.length ? `
      <div>
        <div style="font-size:13px;font-weight:500;margin-bottom:10px;">Importierte Quellen</div>
        ${sourceRows}
        <div style="margin-top:12px;display:flex;gap:8px;">
          <button class="btn btn-primary" onclick="reimportAllIcs(this)">Alle neu importieren</button>
        </div>
      </div>` : `<div style="font-size:13px;color:var(--text-tertiary);">Noch keine externen Quellen importiert.</div>`}
    </div>`;
}

async function handleIcsDrop(event) {
  event.preventDefault();
  document.getElementById('ics-drop-zone').style.borderColor = 'var(--border-secondary)';
  const file = event.dataTransfer.files[0];
  if (file) await uploadIcsFile(file);
}

async function handleIcsUpload(input) {
  const file = input.files[0];
  if (file) await uploadIcsFile(file);
}

async function uploadIcsFile(file) {
  const form = new FormData();
  form.append('file', file);
  const zone = document.getElementById('ics-drop-zone');
  if (zone) zone.textContent = 'Lade hoch…';
  const res = await fetch('/api/agenda/upload-ics', { method: 'POST', body: form }).then(r=>r.json()).catch(()=>null);
  if (res && res.status === 'ok') {
    await renderExternTab();
  } else {
    if (zone) zone.textContent = 'Fehler beim Hochladen.';
  }
}

async function reimportIcs(stem, btn) {
  const sel = document.getElementById('ics-facet-'+stem);
  if (sel) await fetchAPI('/api/agenda/ics-config', { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({[stem]: sel.value}) });
  btn.textContent = 'Importiere…'; btn.disabled = true;
  await fetchAPI('/api/agenda/scan-ics', { method: 'POST' });
  await renderExternTab();
}

async function reimportAllIcs(btn) {
  const cfg = {};
  document.querySelectorAll('[id^="ics-facet-"]').forEach(sel => {
    cfg[sel.id.replace('ics-facet-','')] = sel.value;
  });
  if (Object.keys(cfg).length) await fetchAPI('/api/agenda/ics-config', { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(cfg) });
  btn.textContent = 'Importiere…'; btn.disabled = true;
  await fetchAPI('/api/agenda/scan-ics', { method: 'POST' });
  await renderExternTab();
}

async function migrateFromShadow() {
  const btn = document.getElementById('migrate-shadow-btn');
  if (btn) { btn.textContent = 'Migrating…'; btn.disabled = true; }
  try {
    const res = await fetchAPI('/api/agenda/migrate-from-shadow', { method: 'POST' });
    const msg = res.error ? `Error: ${res.error}` : `Done — ${res.imported} item(s) imported`;
    if (btn) { btn.textContent = msg; }
    setTimeout(() => { if (btn) { btn.textContent = 'Migrate Shadow'; btn.disabled = false; } }, 3000);
  } catch (e) {
    if (btn) { btn.textContent = 'Failed'; btn.disabled = false; }
  }
}

async function renderFileView(type, pathPrefix) {
  viewTitle.textContent = type.charAt(0).toUpperCase() + type.slice(1);
  viewPath.textContent = pathPrefix;
  const taskForView = { agenda: 'agenda_review', codebase: 'code_review', migration: 'memory_migrate', files: 'shadow_scan' }[type];
  const taskLabel = { files: 'Scan' }[type] || 'Review';
  viewActions.innerHTML = taskForView
    ? `<button class="btn sched-run-btn" data-task="${taskForView}" onclick="runTask('${taskForView}', this)">${taskLabel}</button>`
    : '';
  if (taskForView) {
    const tasks = [taskForView];
    const { running = [] } = await fetchAPI('/api/scheduler/running');
    for (const t of tasks) {
      const btn = viewActions.querySelector(`.sched-run-btn[data-task="${t}"]`);
      if (!btn) continue;
      if (activePolls[t]) {
        activePolls[t].btn = btn;
        btn.textContent = 'Running…';
        btn.disabled = true;
      } else if (running.includes(t)) {
        btn.textContent = 'Running…';
        btn.disabled = true;
        watchTask(t, btn);
      }
    }
  }

  const files = await fetchAPI(`/api/${type}`);
  const fileList = Array.isArray(files) ? files : files.files || [];

  if (fileList.length === 0) {
    viewContent.innerHTML = `<div class="scroll"><div class="empty"><div class="empty-title">No files found</div><div class="empty-text">Create files in ${pathPrefix}</div></div></div>`;
    const countEl = document.getElementById(`${type}-count`);
    if (countEl) countEl.textContent = '0';
    return;
  }

  const countEl = document.getElementById(`${type}-count`);
  if (countEl) countEl.textContent = String(fileList.length);

  const savedFile = localStorage.getItem(`lastFile_${type}`);
  const keepFile = (currentFile && fileList.some((f) => f.name === currentFile)) ? currentFile
    : (savedFile && fileList.some((f) => f.name === savedFile)) ? savedFile
    : fileList[0].name;
  currentFile = keepFile;
  fileMode = 'rendered';

  viewContent.innerHTML = `
    <div class="file-split">
      <div class="file-list" id="file-list-panel">
        <div class="file-list-create" id="file-list-create-btn" onclick="activateCreateForm('${escapeHtml(type)}')"><span class="file-list-create-icon">+</span> Create new<button class="file-list-refresh-btn" title="Refresh" onclick="event.stopPropagation();refreshFileList('${escapeHtml(type)}', this)">↻</button></div>
        <div class="file-list-create-form" id="file-list-create-form" style="display:none">
          <div class="create-path-breadcrumb" id="create-path-breadcrumb"></div>
          <input class="create-input" id="create-input" type="text" placeholder="name or path/to/file.md"
            oninput="updateCreateBreadcrumb(this.value)"
            onkeydown="handleCreateKey(event, '${escapeHtml(type)}')">
          <div class="create-hint">↵ confirm · Esc cancel</div>
        </div>
        ${fileList.map((f) => `<div class="file-item ${f.name === currentFile ? 'active' : ''}" data-filename="${escapeHtml(f.name)}" onclick="openFileEl(this, '${escapeHtml(type)}')"><span>${escapeHtml(f.name)}</span><span class="file-size">${formatSize(f.size)}</span></div>`).join('')}
      </div>
      <div class="file-list-resize" id="file-list-resize"></div>
      <div class="file-view">
        <div class="file-header">
          <button class="file-list-toggle" id="file-list-toggle" onclick="toggleFileList()">&#8249;</button>
          <span class="file-name">${currentFile}</span>
          <div class="file-toggle">
            <input type="text" id="search-input" class="search-input" placeholder="regex search…" onkeydown="if(event.key==='Enter')searchFiles('${type}')">
            <button class="btn" onclick="searchFiles('${type}')">Search</button>
            <button class="btn btn-primary" onclick="saveCurrentFile()">Save</button>
            <button class="btn" onclick="renameCurrentFile('${type}')">Rename</button>
            <button class="btn" style="color:var(--danger,#e05252)" onclick="deleteCurrentFile('${type}')">Delete</button>
          </div>
        </div>
        <div id="search-results" class="search-results" style="display:none"></div>
        <div class="file-body" id="file-body"></div>
      </div>
    </div>
  `;

  // Seed snapshot so first poll doesn't trigger a spurious reload
  _fileListSnapshot = Object.fromEntries(fileList.map((f) => [f.name, f.modified ?? f.size]));

  await loadFile(type, currentFile);
  startFileRefresh(type, currentFile);
  startFileListRefresh(type);
  initFileListResize();
}

function toggleFileList() {
  const panel = document.getElementById('file-list-panel');
  const btn = document.getElementById('file-list-toggle');
  if (!panel || !btn) return;
  const collapsed = panel.classList.toggle('collapsed');
  btn.innerHTML = collapsed ? '&#8250;' : '&#8249;';
  localStorage.setItem('fileListCollapsed', collapsed ? '1' : '0');
}

function initFileListResize() {
  const handle = document.getElementById('file-list-resize');
  const panel  = document.getElementById('file-list-panel');
  if (!handle || !panel) return;

  const saved = localStorage.getItem('fileListWidth');
  if (saved) panel.style.width = saved + 'px';

  const btn = document.getElementById('file-list-toggle');
  if (localStorage.getItem('fileListCollapsed') === '1') {
    panel.style.transition = 'none';
    panel.classList.add('collapsed');
    if (btn) btn.innerHTML = '&#8250;';
    requestAnimationFrame(() => { panel.style.transition = ''; });
  }

  let startX, startW;

  handle.addEventListener('mousedown', (e) => {
    startX = e.clientX;
    startW = panel.offsetWidth;
    handle.classList.add('dragging');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    function onMove(e) {
      const w = Math.max(120, Math.min(480, startW + e.clientX - startX));
      panel.style.width = w + 'px';
    }

    function onUp() {
      handle.classList.remove('dragging');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      localStorage.setItem('fileListWidth', panel.offsetWidth);
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    }

    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  });
}

async function deleteMemoryEntry(index) {
  const parsed = JSON.parse(currentFileContent);
  parsed.entries.splice(index, 1);
  parsed.updated_at = new Date().toISOString();
  const newContent = JSON.stringify(parsed, null, 2);
  const [type, filename] = [currentView, currentFile];
  await fetchAPI(`/api/${type}/${encodeURIComponent(filename)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: newContent }),
  });
  currentFileContent = newContent;
  renderFileContent(newContent);
  showToast('Entry deleted');
}

function openFileEl(el, type) {
  openFile(type, el.dataset.filename, el);
}

async function openFile(type, filename, el) {
  document.querySelectorAll('.file-item').forEach((e) => e.classList.remove('active'));
  if (el) el.classList.add('active');
  currentFile = filename;
  localStorage.setItem(`lastFile_${type}`, filename);
  document.querySelector('.file-name').textContent = filename;
  await loadFile(type, filename);
  startFileRefresh(type, filename);
}

function activateCreateForm(type) {
  document.getElementById('file-list-create-btn').style.display = 'none';
  const form = document.getElementById('file-list-create-form');
  form.style.display = 'block';
  const input = document.getElementById('create-input');
  input.value = '';
  updateCreateBreadcrumb('');
  input.focus();
}

function deactivateCreateForm() {
  const btn = document.getElementById('file-list-create-btn');
  if (btn) btn.style.display = '';
  const form = document.getElementById('file-list-create-form');
  if (form) form.style.display = 'none';
}

function updateCreateBreadcrumb(value) {
  const el = document.getElementById('create-path-breadcrumb');
  if (!el) return;
  if (!value) { el.innerHTML = ''; return; }
  const parts = value.split('/');
  if (parts.length <= 1) { el.innerHTML = ''; return; }
  const dirs = parts.slice(0, -1);
  el.innerHTML = dirs.map(d => `<span class="create-breadcrumb-dir">${escapeHtml(d)}</span>`).join('<span class="create-breadcrumb-sep">/</span>') + '<span class="create-breadcrumb-sep">/</span>';
}

async function handleCreateKey(event, type) {
  if (event.key === 'Escape') {
    deactivateCreateForm();
    return;
  }
  if (event.key !== 'Enter') return;
  const name = event.target.value.trim();
  if (!name) return;
  const res = await fetchAPI(`/api/${type}/create`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  if (res.error) { showToast(res.error); return; }
  currentFile = res.name;
  await renderFileView(type, viewPath.textContent);
}

let currentFileContent = '';
let _syncRenderedTimer = null;

function syncRenderedContent() {
  clearTimeout(_syncRenderedTimer);
  _syncRenderedTimer = setTimeout(() => {
    const md = document.querySelector('.file-md[contenteditable]');
    if (md) currentFileContent = htmlToMarkdown(md);
  }, 300);
}

function htmlToMarkdown(el) {
  function serializeNode(node) {
    if (node.nodeType === 8) return ''; // strip HTML comments
    if (node.nodeType === 3) return node.textContent; // text
    if (node.nodeType !== 1) return '';               // not element

    const tag = node.tagName.toLowerCase();

    const inner = () => Array.from(node.childNodes).map(serializeNode).join('');

    switch (tag) {
      case 'h1': return `# ${inner().trim()}\n\n`;
      case 'h2': return `## ${inner().trim()}\n\n`;
      case 'h3': return `### ${inner().trim()}\n\n`;
      case 'h4': return `#### ${inner().trim()}\n\n`;
      case 'h5': return `##### ${inner().trim()}\n\n`;
      case 'h6': return `###### ${inner().trim()}\n\n`;
      case 'p':  { const c = inner().trim(); return c ? `${c}\n\n` : ''; }
      case 'br': return '\n';
      case 'hr': return '\n---\n\n';
      case 'strong': case 'b': return `**${inner()}**`;
      case 'em':     case 'i': return `*${inner()}*`;
      case 'del':    case 's': return `~~${inner()}~~`;
      case 'code':
        return node.parentElement?.tagName.toLowerCase() === 'pre'
          ? inner() : `\`${inner()}\``;
      case 'pre': {
        const c = node.querySelector('code');
        const lang = (c?.className || '').replace(/\blanguage-/, '').trim();
        return `\`\`\`${lang}\n${c ? c.textContent : inner()}\`\`\`\n\n`;
      }
      case 'blockquote':
        return inner().trim().split('\n').map(l => `> ${l}`).join('\n') + '\n\n';
      case 'a': return `[${inner()}](${node.getAttribute('href') || ''})`;
      case 'img': {
        const src = node.getAttribute('src') || '';
        const alt = node.getAttribute('alt') || '';
        return src.startsWith('/api/vault/raw') ? `![[${alt}]]` : `![${alt}](${src})`;
      }
      case 'ul': return serializeList(node, false);
      case 'ol': return serializeList(node, true);
      case 'li': return `- ${inner().trim()}\n`;
      case 'table': return serializeTable(node) + '\n\n';
      case 'thead': case 'tbody': case 'tr': case 'th': case 'td': return inner();
      case 'input': case 'label': return '';
      case 'span': return inner();
      case 'div': { const c = inner(); return c.endsWith('\n') ? c : c + '\n'; }
      default: return inner();
    }
  }

  function serializeList(listEl, ordered) {
    let idx = 1;
    return Array.from(listEl.children).map(li => {
      const cb = li.querySelector(':scope > input[type="checkbox"]');
      if (cb) {
        const text = Array.from(li.childNodes)
          .filter(n => !(n.nodeType === 1 && n.tagName === 'INPUT'))
          .map(serializeNode).join('').trim();
        return `- [${cb.checked ? 'x' : ' '}] ${text}`;
      }
      const nested = li.querySelector(':scope > ul, :scope > ol');
      const mainText = Array.from(li.childNodes)
        .filter(n => !(n.nodeType === 1 && (n.tagName === 'UL' || n.tagName === 'OL')))
        .map(serializeNode).join('').trim();
      let result = (ordered ? `${idx++}. ` : '- ') + mainText;
      if (nested) {
        const nestedMd = serializeList(nested, nested.tagName === 'OL');
        result += '\n' + nestedMd.trimEnd().split('\n').map(l => `  ${l}`).join('\n');
      }
      return result;
    }).join('\n') + '\n\n';
  }

  function serializeTable(tableEl) {
    const rows = Array.from(tableEl.querySelectorAll('tr'));
    if (!rows.length) return '';
    return rows.map((row, ri) => {
      const cells = Array.from(row.querySelectorAll('th, td')).map(c => c.textContent.trim());
      const line = `| ${cells.join(' | ')} |`;
      return ri === 0 ? line + '\n| ' + cells.map(() => '---').join(' | ') + ' |' : line;
    }).join('\n');
  }

  return Array.from(el.childNodes)
    .map(serializeNode)
    .join('')
    .replace(/\n{3,}/g, '\n\n')
    .trimStart()
    .replace(/\n+$/, '\n');
}

async function loadFile(type, filename) {
  const data = await fetchAPI(`/api/${type}/${encodeURIComponent(filename)}`);
  currentFileContent = data.content || '';
  renderFileContent(currentFileContent);
}

function preprocessWikilinks(content) {
  // Replace Obsidian ![[name.jpg]] and ![[name.jpg|WxH]] with <img> tags
  return content.replace(/!\[\[([^\]|]+?)(?:\|(\d+)x(\d+))?\]\]/g, (match, name, w, h) => {
    const resolved = currentVaultWikilinks[name.trim()];
    if (!resolved) return match;
    const src = '/api/vault/raw?path=' + encodeURIComponent(resolved);
    const style = w ? ` style="max-width:${w}px;"` : ' style="max-width:100%;"';
    return `<img src="${src}" alt="${escapeHtml(name)}"${style}>`;
  });
}

function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function renderFileContent(content) {
  const body = document.getElementById('file-body');
  if (fileMode === 'rendered') {
    let parsed = null;
    try { parsed = JSON.parse(content); } catch (_) {}
    if (parsed !== null && Array.isArray(parsed?.entries)) {
      if (parsed.entries.length === 0) {
        body.innerHTML = `<div class="file-md"><p style="color:var(--text-tertiary);font-size:13px;">No entries.</p></div>`;
      } else {
        body.innerHTML = `<div class="file-md">${parsed.entries.map((e, i) => `
          <div style="display:flex;align-items:flex-start;gap:12px;padding:12px 0;border-bottom:0.5px solid var(--border-primary);">
            <div style="flex:1;">
              <div style="font-size:11px;color:var(--text-tertiary);margin-bottom:6px;">
                ${e.type || ''} · ${e.confidence != null ? Math.round(e.confidence * 100) + '%' : ''} · ${e.created_at?.slice(0,10) || ''}
              </div>
              <div>${escapeHtml(e.content || JSON.stringify(e))}</div>
            </div>
            <button class="btn btn-icon danger" onclick="deleteMemoryEntry(${i})" title="Delete entry">×</button>
          </div>`).join('')}</div>`;
      }
    } else if (parsed !== null) {
      // JSON without entries array — render as formatted JSON
      body.innerHTML = `<div class="file-md"><pre style="font-size:12px;white-space:pre-wrap;">${escapeHtml(JSON.stringify(parsed, null, 2))}</pre></div>`;
    } else {
      // CM6 live-preview editor
      if (currentEditor) { try { currentEditor.destroy(); } catch (_) {} currentEditor = null; }
      body.innerHTML = '';
      if (window.MarkdownEditor) {
        currentEditor = window.MarkdownEditor.create(body, content, {
          onChange: () => { _fileRefreshDirty = true; },
          onSave: () => {
            _fileRefreshDirty = false;
            if (currentVaultPath) saveVaultFile(); else saveCurrentFile();
          },
        });
      } else {
        body.innerHTML = `<div class="file-raw" contenteditable spellcheck="false">${escapeHtml(content)}</div>`;
      }
    }
  } else {
    body.innerHTML = `<div class="file-raw" contenteditable spellcheck="false">${escapeHtml(content)}</div>`;
  }
}

function setFileMode(mode, btn) {
  const raw = document.querySelector('.file-raw');
  if (raw) currentFileContent = raw.textContent;
  const md = document.querySelector('.file-md[contenteditable]');
  if (md) currentFileContent = htmlToMarkdown(md);

  fileMode = mode;
  document.querySelectorAll('.file-toggle button').forEach((b) => b.classList.remove('active'));
  btn.classList.add('active');
  renderFileContent(currentFileContent);
}

async function saveCurrentFile() {
  if (currentEditor) { currentFileContent = currentEditor.getContent(); }
  else {
    const raw = document.querySelector('.file-raw');
    if (raw) currentFileContent = raw.textContent;
    const md = document.querySelector('.file-md[contenteditable]');
    if (md) currentFileContent = htmlToMarkdown(md);
  }

  await fetchAPI(`/api/${currentView}/${encodeURIComponent(currentFile)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: currentFileContent }),
  });

  _fileRefreshDirty = false;
  showToast('File saved');
}

async function deleteCurrentFile(type) {
  if (!currentFile || !confirm(`Delete "${currentFile}"?`)) return;
  const res = await fetchAPI(`/api/${type}/${encodeURIComponent(currentFile)}`, { method: 'DELETE' });
  if (res.error) { showToast(res.error); return; }
  currentFile = null;
  currentFileContent = '';
  await renderFileView(type, viewPath.textContent);
}

async function renameCurrentFile(type) {
  if (!currentFile) return;
  const newName = prompt('New filename:', currentFile);
  if (!newName || newName === currentFile) return;
  const res = await fetchAPI(`/api/${type}/rename`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ from: currentFile, to: newName }),
  });
  if (res.error) { showToast(res.error); return; }
  currentFile = res.name;
  await renderFileView(type, viewPath.textContent);
}

async function searchFiles(type) {
  const input = document.getElementById('search-input');
  const panel = document.getElementById('search-results');
  if (!input || !panel) return;
  const q = input.value.trim();
  if (!q) { panel.style.display = 'none'; return; }

  panel.style.display = 'block';
  panel.innerHTML = '<div class="search-loading">Searching…</div>';

  const data = await fetchAPI(`/api/search?type=${encodeURIComponent(type)}&q=${encodeURIComponent(q)}`);
  if (data.error) {
    panel.innerHTML = `<div class="search-error">${escapeHtml(data.error)} <button class="search-close" onclick="closeSearch()">✕</button></div>`;
    return;
  }

  const { results, total } = data;
  if (!results.length) {
    panel.innerHTML = `<div class="search-empty">No matches <button class="search-close" onclick="closeSearch()">✕</button></div>`;
    return;
  }

  const rows = results.map(({ file, matches }) => {
    const matchRows = matches.map(({ line, content }) =>
      `<div class="search-match" data-file="${escapeHtml(file)}" title=":${line}">
        <span class="search-line">:${line}</span><span class="search-content">${escapeHtml(content)}</span>
      </div>`
    ).join('');
    return `<div class="search-group">
      <div class="search-file" data-file="${escapeHtml(file)}">${escapeHtml(file)} <span class="badge">${matches.length}</span></div>
      ${matchRows}
    </div>`;
  }).join('');

  panel.innerHTML = `
    <div class="search-header">
      <span>${total} match${total !== 1 ? 'es' : ''} in ${results.length} file${results.length !== 1 ? 's' : ''}</span>
      <button class="search-close" onclick="closeSearch()">✕</button>
    </div>
    <div class="search-list">${rows}</div>`;

  panel.querySelector('.search-list').addEventListener('click', (e) => {
    const el = e.target.closest('[data-file]');
    if (!el) return;
    const file = el.dataset.file;
    const fileEl = Array.from(document.querySelectorAll('.file-item')).find((fi) => fi.querySelector('span')?.textContent === file);
    openFile(type, file, fileEl || null);
  });
}

function closeSearch() {
  const panel = document.getElementById('search-results');
  if (panel) panel.style.display = 'none';
  const input = document.getElementById('search-input');
  if (input) input.value = '';
}

// Tags
async function renderTags() {
  viewTitle.textContent = 'Tags';
  viewPath.textContent = '';

  const data = await fetchAPI('/api/tags');
  const tags = data.tags || [];
  const scannedAt = data.scanned_at ? data.scanned_at.replace('T', ' ') : 'never';

  document.getElementById('tags-count').textContent = String(tags.length);

  // Group by namespace prefix (part before first '-')
  const groups = {};
  for (const t of tags) {
    const m = t.name.match(/^#([a-zA-Z\u00c0-\u017e]+)-/);
    const prefix = m ? m[1] : '_misc';
    if (!groups[prefix]) groups[prefix] = [];
    groups[prefix].push(t);
  }
  const sortedPrefixes = Object.keys(groups).sort((a, b) =>
    a === '_misc' ? 1 : b === '_misc' ? -1 : a.localeCompare(b)
  );

  const renderTagRow = (t) => `
    <div class="msg-item tag-row" data-tag="${t.name}">
      <div class="msg-header">
        <span class="msg-from" style="font-family: monospace; min-width: 200px;">${t.name}</span>
        <span class="badge">${t.count}</span>
        <span style="color: var(--text-tertiary); font-size: 11px; flex: 1; padding: 0 8px;">${t.files.length} file${t.files.length !== 1 ? 's' : ''}</span>
        <input class="tag-rename-input" type="text" placeholder="rename to..." style="width: 160px; padding: 2px 6px; font-size: 12px; border: 1px solid var(--border); background: var(--bg-secondary); color: var(--text-primary); border-radius: 3px;" />
        <button class="btn btn-sm" onclick="renameTag('${t.name}', this)">Rename</button>
        <button class="btn btn-sm danger" onclick="deleteTag('${t.name}', this)">Delete</button>
      </div>
    </div>`;

  const renderGroup = (prefix, groupTags) => {
    const label = prefix === '_misc' ? 'other' : `#${prefix}-*`;
    const collapsed = true;
    const total = groupTags.reduce((s, t) => s + t.count, 0);
    return `
      <div class="tag-group">
        <div class="tag-group-header" onclick="toggleTagGroup(this)" style="cursor:pointer; display:flex; align-items:center; gap:8px; padding:6px 12px; background:var(--bg-secondary); border-bottom:1px solid var(--border);">
          <span style="font-size:11px; color:var(--text-tertiary);">${collapsed ? '▶' : '▼'}</span>
          <span style="font-family:monospace; font-size:12px;">${label}</span>
          <span class="badge">${groupTags.length}</span>
          <span style="color:var(--text-tertiary); font-size:11px;">${total} occurrences</span>
        </div>
        <div class="tag-group-body" ${collapsed ? 'style="display:none"' : ''}>
          ${groupTags.map(renderTagRow).join('')}
        </div>
      </div>`;
  };

  viewContent.innerHTML = `
    <div class="scroll">
      <div class="card">
        <div class="card-header">
          <span class="card-title">Vault Tags</span>
          <span style="color: var(--text-tertiary); font-size: 11px;">last scan: ${scannedAt}</span>
          <button class="btn btn-sm" id="tags-scan-btn" onclick="scanTags()">Scan</button>
        </div>
        ${tags.length === 0
          ? '<div class="msg-item"><div class="msg-text" style="color: var(--text-tertiary);">No tags found. Run a scan first.</div></div>'
          : sortedPrefixes.map((p) => renderGroup(p, groups[p])).join('')
        }
      </div>
    </div>
  `;
}

async function scanTags() {
  const btn = document.getElementById('tags-scan-btn');
  if (!btn) return;
  btn.textContent = 'Running…';
  btn.disabled = true;

  const res = await fetchAPI('/api/tags/scan', { method: 'POST' });
  if (res.error) {
    btn.textContent = '✗';
    setTimeout(() => { btn.textContent = 'Scan'; btn.disabled = false; }, 3000);
    return;
  }

  const triggerTime = Date.now();
  const deadline = triggerTime + 10 * 60 * 1000;

  const intervalId = setInterval(async () => {
    const freshBtn = document.getElementById('tags-scan-btn');
    if (!freshBtn || Date.now() > deadline) {
      clearInterval(intervalId);
      if (freshBtn) { freshBtn.textContent = 'Scan'; freshBtn.disabled = false; }
      return;
    }
    const { running = [], tasks = {} } = await fetchAPI('/api/scheduler/running');
    const rec = tasks['tag_scan'];
    const isRunning = running.includes('tag_scan');
    const isDone = rec && rec.finished_at && !isRunning;
    if (isDone) {
      clearInterval(intervalId);
      const ok = rec.status === 'completed';
      const skipped = rec.status === 'skipped';
      freshBtn.textContent = ok ? '✓' : (skipped ? '⏸' : '✗');
      freshBtn.disabled = false;
      setTimeout(async () => { await renderTags(); }, 300);
      if (!ok) setTimeout(() => { freshBtn.textContent = 'Scan'; }, 4000);
    }
  }, 1000);
}

function toggleTagGroup(header) {
  const body = header.nextElementSibling;
  const arrow = header.querySelector('span');
  const collapsed = body.style.display === 'none';
  body.style.display = collapsed ? '' : 'none';
  arrow.textContent = collapsed ? '▼' : '▶';
}

async function deleteTag(name, btn) {
  if (!confirm(`Remove ${name} from all files?`)) return;
  btn.textContent = '…';
  btn.disabled = true;
  const result = await fetchAPI('/api/tags/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  if (result.error) {
    showToast('Error: ' + result.error);
    btn.textContent = 'Delete';
    btn.disabled = false;
  } else {
    showToast(`${name} removed from ${result.files_changed} file(s)`);
    await renderTags();
  }
}

async function renameTag(oldName, btn) {
  const row = btn.closest('.tag-row');
  const input = row.querySelector('.tag-rename-input');
  let newName = input.value.trim();
  if (!newName) return;
  if (!newName.startsWith('#')) newName = '#' + newName;
  if (newName === oldName) return;

  btn.textContent = '…';
  btn.disabled = true;
  const result = await fetchAPI('/api/tags/rename', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ old_name: oldName, new_name: newName }),
  });
  if (result.error) {
    showToast('Error: ' + result.error);
    btn.textContent = 'Rename';
    btn.disabled = false;
  } else {
    showToast(`${oldName} → ${newName} in ${result.files_changed} file(s)`);
    await renderTags();
  }
}

// Migration
async function renderMigration() {
  const data = await fetchAPI('/api/migration');

  const migrationActions = `<button class="btn sched-run-btn" onclick="runTask('memory_migrate', this)">Run now</button>`;

  if (!data.exists) {
    viewTitle.textContent = 'Migration';
    viewPath.textContent = 'vault/Migration/';
    viewActions.innerHTML = '';
    viewContent.innerHTML = `
      <div class="scroll">
        <div class="empty">
          <div class="empty-title">Migration directory not found</div>
          <div class="empty-text">Create the directory to enable migrations.</div>
          <button class="btn btn-primary" onclick="createMigrationDir()">Create vault/Migration</button>
        </div>
      </div>
    `;
    return;
  }

  if (!data.files.length) {
    viewTitle.textContent = 'Migration';
    viewPath.textContent = 'vault/Migration/';
    viewActions.innerHTML = migrationActions;
    viewContent.innerHTML = `
      <div class="scroll">
        <div class="drop-zone" id="migration-drop-empty">
          Drop migration files here<br><span style="font-size: 11px;">(.md or .json files)</span>
        </div>
      </div>
    `;
    attachMigrationDropZone(document.getElementById('migration-drop-empty'));
    return;
  }

  await renderFileView('migration', 'vault/Migration/');
  // Ensure Run now button is visible even after renderFileView sets viewActions
  if (!viewActions.querySelector('.sched-run-btn')) {
    viewActions.insertAdjacentHTML('beforeend', migrationActions);
  }

  // Re-inject drop zone at top of file list
  const fileList = viewContent.querySelector('.file-list');
  if (fileList) {
    const dz = document.createElement('div');
    dz.className = 'drop-zone';
    dz.innerHTML = 'Drop files here<br><span style="font-size: 11px;">(.md or .json)</span>';
    attachMigrationDropZone(dz);
    fileList.insertBefore(dz, fileList.firstChild);
  }
}

function attachMigrationDropZone(el) {
  el.addEventListener('dragover', (e) => { e.preventDefault(); el.classList.add('drag-over'); });
  el.addEventListener('dragleave', () => el.classList.remove('drag-over'));
  el.addEventListener('drop', (e) => { e.preventDefault(); el.classList.remove('drag-over'); handleMigrationDrop(e.dataTransfer.files); });
}

async function handleMigrationDrop(files) {
  let uploaded = 0;
  for (const file of files) {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch('/api/migration/upload', { method: 'POST', body: form });
    const data = await res.json();
    if (data.status === 'uploaded') uploaded++;
    else showToast(`${file.name}: ${data.error || 'failed'}`);
  }
  if (uploaded) {
    showToast(`${uploaded} file(s) uploaded`);
    await renderMigration();
  }
}

async function createMigrationDir() {
  await fetchAPI('/api/migration/create', { method: 'POST' });
  await renderMigration();
}

function cancelActivePolls() {
  for (const [type, poll] of Object.entries(activePolls)) {
    clearInterval(poll.intervalId);
    poll.btn.textContent = 'Run now';
    poll.btn.disabled = false;
    delete activePolls[type];
  }
}

// WebSocket — exponential backoff: 3s → 6s → 12s → … → 60s cap
let _wsDelay = 3000;
function connectWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  // Force IPv4 loopback — localhost resolves to ::1 first on macOS, but uvicorn binds 127.0.0.1 only
  const hostname = window.location.hostname === 'localhost' ? '127.0.0.1' : window.location.hostname;
  const port = window.location.port ? `:${window.location.port}` : '';
  ws = new WebSocket(`${protocol}//${hostname}${port}/ws`);

  ws.onopen = () => {
    _wsDelay = 3000;
    connectionStatus.classList.add('running');
    connectionStatus.title = 'Connected';
  };
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === 'message' && currentView === 'messages') {
      const list = document.getElementById('msg-list');
      if (list) { list.insertAdjacentHTML('afterbegin', renderMessage(data.data)); list.firstElementChild?.scrollIntoView({behavior:'smooth'}); }
    }
  };
  ws.onclose = () => {
    connectionStatus.classList.remove('running');
    connectionStatus.title = 'Disconnected';
    setTimeout(connectWebSocket, _wsDelay);
    _wsDelay = Math.min(_wsDelay * 2, 60000);
  };
  ws.onerror = () => { connectionStatus.classList.remove('running'); connectionStatus.title = 'Disconnected'; };
}

// Logout
async function logout() {
  await fetch('/api/logout', { method: 'POST' });
  location.reload();
}

// Restart
async function restartDaemon() {
  if (!confirm('Restart outheis?\n\nThe daemon and Web UI will go offline for a few seconds.')) return;
  const btn = document.querySelector('.btn-restart');
  if (btn) { btn.disabled = true; btn.textContent = 'Restarting…'; }
  await fetchAPI('/api/restart', { method: 'POST' });
}

// Utilities
async function fetchAPI(url, options = {}) {
  try {
    const response = await fetch(url, options);
    if (response.status === 401) {
      location.reload(); // session expired — server will show login page
      return {};
    }
    return await response.json();
  } catch (error) {
    console.error('API error:', error);
    return {};
  }
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + 'B';
  if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + 'KB';
  return Math.round(bytes / (1024 * 1024)) + 'MB';
}

function showToast(message, duration = 2000) {
  const existing = document.querySelector('.toast');
  if (existing) existing.remove();

  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = message;
  document.body.appendChild(toast);

  setTimeout(() => toast.classList.add('show'), 10);
  setTimeout(() => { toast.classList.remove('show'); setTimeout(() => toast.remove(), 300); }, duration);
}

// Token chart tooltip
let _tokenTooltip = null;
function getTokenTooltip() {
  if (!_tokenTooltip) {
    _tokenTooltip = document.createElement('div');
    _tokenTooltip.className = 'token-tooltip';
    document.body.appendChild(_tokenTooltip);
  }
  return _tokenTooltip;
}

// Vault file browser
let currentVaultPath = null;
let currentVaultWikilinks = {};

async function renderVaultFiles() {
  viewTitle.textContent = 'Files';
  viewPath.textContent = '';
  viewActions.innerHTML = '';

  const data = await fetchAPI('/api/vault/tree');
  const vaults = data.vaults || [];

  if (vaults.length === 0) {
    viewContent.innerHTML = '<div class="scroll"><div class="empty"><div class="empty-title">No vaults configured</div><div class="empty-text">Add vault paths in Configuration.</div></div></div>';
    return;
  }

  viewContent.innerHTML = `
    <div class="file-split">
      <div class="file-list" id="file-list-panel" style="overflow-y:auto;">
        <div class="file-list-create" id="file-list-create-btn" onclick="activateVaultCreateForm()"><span class="file-list-create-icon">+</span> Create new<button class="file-list-refresh-btn" title="Refresh" onclick="event.stopPropagation();renderVaultFiles()">↻</button></div>
        <div class="file-list-create-form" id="file-list-create-form" style="display:none">
          <div class="create-path-breadcrumb" id="create-path-breadcrumb"></div>
          <input class="create-input" id="create-input" type="text" placeholder="vault/path/to/file.md"
            oninput="updateCreateBreadcrumb(this.value)"
            onkeydown="handleVaultCreateKey(event)">
          <div class="create-hint">↵ confirm · Esc cancel</div>
        </div>
        <div id="vault-tree">
          ${vaults.map((v) => renderVaultTreeNode(v, 0)).join('')}
        </div>
      </div>
      <div class="file-list-resize" id="file-list-resize"></div>
      <div class="file-view">
        <div class="file-header">
          <button class="file-list-toggle" id="file-list-toggle" onclick="toggleFileList()">&#8249;</button>
          <span class="file-name" id="vault-filename">—</span>
          <div class="file-toggle" style="display:none">
            <input type="text" id="search-input" class="search-input" placeholder="regex search…" onkeydown="if(event.key==='Enter')searchVaultFiles()">
            <button class="btn" onclick="searchVaultFiles()">Search</button>
            <button class="btn btn-primary" onclick="saveVaultFile()">Save</button>
            <button class="btn" onclick="renameVaultFile()">Rename</button>
            <button class="btn" style="color:var(--danger,#e05252)" onclick="deleteVaultFile()">Delete</button>
          </div>
        </div>
        <div id="search-results" class="search-results" style="display:none"></div>
        <div class="file-body" id="file-body">
          <div class="file-md" style="color:var(--text-tertiary);font-size:13px;padding:24px;">Select a file from the tree.</div>
        </div>
      </div>
    </div>
  `;

  initFileListResize();

  document.getElementById('vault-tree').addEventListener('click', (e) => {
    const fileEl = e.target.closest('.vault-file');
    const dirLabel = e.target.closest('.vault-dir-label');
    if (fileEl) {
      openVaultFile(fileEl.dataset.path, fileEl);
    } else if (dirLabel) {
      toggleVaultDir(dirLabel);
    }
  });
}

function renderVaultTreeNode(node, depth) {
  if (node.type === 'file') {
    return `<div class="file-item vault-file" data-path="${escapeHtml(node.path)}" style="padding-left:${14 + depth * 12}px"><span>${escapeHtml(node.name)}</span><span class="file-size">${formatSize(node.size)}</span></div>`;
  }
  const isRoot = depth === 0;
  const children = (node.children || []).map((c) => renderVaultTreeNode(c, depth + 1)).join('');
  return `<div>
    <div class="file-item vault-dir-label" data-open="${isRoot}" style="padding-left:${14 + depth * 12}px;color:var(--text-secondary);cursor:pointer;">
      <span class="vault-dir-icon" style="font-size:9px;margin-right:5px;">${isRoot ? '▼' : '▶'}</span><span>${escapeHtml(node.name)}</span>
    </div>
    <div class="vault-dir-children" style="display:${isRoot ? 'block' : 'none'};">${children}</div>
  </div>`;
}

function toggleVaultDir(label) {
  const children = label.nextElementSibling;
  const icon = label.querySelector('.vault-dir-icon');
  const isOpen = label.dataset.open === 'true';
  children.style.display = isOpen ? 'none' : 'block';
  icon.textContent = isOpen ? '▶' : '▼';
  label.dataset.open = isOpen ? 'false' : 'true';
}

async function openVaultFile(path, el) {
  document.querySelectorAll('.vault-file').forEach((e) => e.classList.remove('active'));
  if (el) el.classList.add('active');
  currentVaultPath = path;
  const name = path.split('/').pop();
  document.getElementById('vault-filename').textContent = name;

  const data = await fetchAPI('/api/vault/file?path=' + encodeURIComponent(path));
  if (data.error) { showToast(data.error); return; }

  const body = document.getElementById('file-body');
  const toggle = document.querySelector('.file-view .file-toggle');

  const rawUrl = '/api/vault/raw?path=' + encodeURIComponent(path);
  if (data.kind === 'image') {
    toggle.style.display = 'none';
    viewActions.innerHTML = `<a class="btn" href="${rawUrl}" download="${escapeHtml(name)}">Download</a><button class="btn" style="color:var(--danger,#e05252);" onclick="deleteVaultFile()">Delete</button>`;
    body.innerHTML = `<div class="file-md" style="display:flex;justify-content:center;padding:24px;"><img src="${rawUrl}" style="max-width:100%;max-height:70vh;border-radius:4px;" alt="${escapeHtml(name)}"></div>`;
  } else if (data.kind === 'binary') {
    toggle.style.display = 'none';
    viewActions.innerHTML = `<a class="btn" href="${rawUrl}" download="${escapeHtml(name)}">Download</a><button class="btn" style="color:var(--danger,#e05252);" onclick="deleteVaultFile()">Delete</button>`;
    body.innerHTML = `<div class="file-md" style="color:var(--text-tertiary);font-size:13px;padding:24px;">Binary file · ${formatSize(data.size)}</div>`;
  } else {
    toggle.style.display = '';
    viewActions.innerHTML = '';
    currentVaultWikilinks = data.wikilinks || {};
    currentFileContent = data.content || '';
    fileMode = 'rendered';
    renderFileContent(currentFileContent);
  }
}

function activateVaultCreateForm() {
  document.getElementById('file-list-create-btn').style.display = 'none';
  const form = document.getElementById('file-list-create-form');
  form.style.display = 'block';
  const input = document.getElementById('create-input');
  input.value = '';
  updateCreateBreadcrumb('');
  input.focus();
}

async function handleVaultCreateKey(event) {
  if (event.key === 'Escape') { deactivateCreateForm(); return; }
  if (event.key !== 'Enter') return;
  const path = event.target.value.trim();
  if (!path) return;
  const res = await fetchAPI('/api/vault/file', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, content: '' }),
  });
  if (res.error) { showToast(res.error); return; }
  currentVaultPath = path;
  await renderVaultFiles();
}

async function renameVaultFile() {
  if (!currentVaultPath) return;
  const name = currentVaultPath.split('/').pop();
  const newName = prompt('New filename:', name);
  if (!newName || newName === name) return;
  const dir = currentVaultPath.slice(0, currentVaultPath.lastIndexOf('/') + 1);
  const newPath = dir + newName;
  const res = await fetchAPI('/api/vault/rename', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ from: currentVaultPath, to: newPath }),
  });
  if (res.error) { showToast(res.error); return; }
  currentVaultPath = newPath;
  document.getElementById('vault-filename').textContent = newName;
  showToast('Renamed');
  await renderVaultFiles();
}

async function searchVaultFiles() {
  const input = document.getElementById('search-input');
  const panel = document.getElementById('search-results');
  if (!input || !panel) return;
  const q = input.value.trim();
  if (!q) { panel.style.display = 'none'; return; }
  panel.style.display = 'block';
  panel.innerHTML = '<div class="search-loading">Searching…</div>';
  const data = await fetchAPI(`/api/search?type=vault&q=${encodeURIComponent(q)}`);
  if (data.error) {
    panel.innerHTML = `<div class="search-error">${escapeHtml(data.error)} <button class="search-close" onclick="closeSearch()">✕</button></div>`;
    return;
  }
  const { results, total } = data;
  if (!results?.length) {
    panel.innerHTML = `<div class="search-empty">No matches <button class="search-close" onclick="closeSearch()">✕</button></div>`;
    return;
  }
  const rows = results.map(({ file, matches }) => {
    const matchRows = matches.map(({ line, content }) =>
      `<div class="search-match" data-path="${escapeHtml(file)}" title=":${line}">
        <span class="search-line">:${line}</span><span class="search-content">${escapeHtml(content)}</span>
      </div>`
    ).join('');
    return `<div class="search-group">
      <div class="search-file" data-path="${escapeHtml(file)}">${escapeHtml(file.split('/').pop())} <span class="badge">${matches.length}</span></div>
      ${matchRows}
    </div>`;
  }).join('');
  panel.innerHTML = `
    <div class="search-header">
      <span>${total} match${total !== 1 ? 'es' : ''} in ${results.length} file${results.length !== 1 ? 's' : ''}</span>
      <button class="search-close" onclick="closeSearch()">✕</button>
    </div>
    <div class="search-list">${rows}</div>`;
  panel.querySelector('.search-list').addEventListener('click', (e) => {
    const el = e.target.closest('[data-path]');
    if (!el) return;
    const path = el.dataset.path;
    const fileEl = document.querySelector(`.vault-file[data-path="${CSS.escape(path)}"]`);
    if (fileEl) openVaultFile(path, fileEl);
  });
}

async function saveVaultFile() {
  if (!currentVaultPath) return;
  if (currentEditor) { currentFileContent = currentEditor.getContent(); }
  else {
    const raw = document.querySelector('.file-raw');
    if (raw) currentFileContent = raw.textContent;
    const md = document.querySelector('.file-md[contenteditable]');
    if (md) currentFileContent = htmlToMarkdown(md);
  }
  const res = await fetchAPI('/api/vault/file', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: currentVaultPath, content: currentFileContent }),
  });
  if (res.error) { showToast(res.error); return; }
  showToast('Saved');
}

async function deleteVaultFile() {
  if (!currentVaultPath) return;
  const name = currentVaultPath.split('/').pop();
  if (!confirm(`Delete "${name}"?`)) return;
  const res = await fetchAPI('/api/vault/file?path=' + encodeURIComponent(currentVaultPath), { method: 'DELETE' });
  if (res.error) { showToast(res.error); return; }
  showToast('Deleted');
  currentVaultPath = null;
  viewActions.innerHTML = '';
  await renderVaultFiles();
}

// Token chart
async function renderTokenChart() {
  const stats = await fetchAPI('/api/tokens/stats');
  if (!stats?.days) return;

  const maxTokens = Math.max(1, ...stats.days.flatMap((d) => d.periods));

  const chartEl = document.getElementById('dispatcher-info');
  if (!chartEl) return;

  chartEl.innerHTML = `
    <div style="display:flex;align-items:flex-end;gap:6px;">
      <div class="token-chart">
        ${stats.days.map((day) => `
          <div class="token-day">
            <div class="token-day-bars">
              ${day.periods.map((t, i) => `
                <div class="token-bar" data-tokens="${t}" data-period="${i}" style="height:${Math.max(1, Math.round((t / maxTokens) * 32))}px"></div>
              `).join('')}
            </div>
            <div class="token-day-label">${day.label}</div>
          </div>
        `).join('')}
      </div>
      <span class="token-total">${(stats.total_7d / 1000).toFixed(1)}k tokens / 7d</span>
    </div>
  `;

  const PERIOD_LABELS = ['0–6h', '6–12h', '12–18h', '18–24h'];
  chartEl.querySelectorAll('.token-bar').forEach((bar) => {
    bar.addEventListener('mousemove', (e) => {
      const tip = getTokenTooltip();
      const tokens = parseInt(bar.dataset.tokens, 10);
      const period = parseInt(bar.dataset.period, 10);
      tip.textContent = `${tokens.toLocaleString()} tokens (${PERIOD_LABELS[period]})`;
      tip.style.display = 'block';
      tip.style.left = `${e.clientX + 10}px`;
      tip.style.top = `${e.clientY - 28}px`;
    });
    bar.addEventListener('mouseleave', () => {
      getTokenTooltip().style.display = 'none';
    });
  });
}

// Init
async function init() {
  const hash = location.hash.slice(1);
  if (hash) {
    const item = document.querySelector(`.nav-item[data-view="${hash}"]`);
    if (item) {
      document.querySelectorAll('.nav-item').forEach((el) => el.classList.remove('active'));
      item.classList.add('active');
      currentView = hash;
    }
  }
  await renderView();
  connectWebSocket();

  const memory = await fetchAPI('/api/memory');
  const skills = await fetchAPI('/api/skills');
  const rules = await fetchAPI('/api/rules');
const agenda = await fetchAPI('/api/agenda');
  const tagsData = await fetchAPI('/api/tags');

  document.getElementById('memory-count').textContent = String(memory.length || 0);
  document.getElementById('skills-count').textContent = String(skills.length || 0);
  document.getElementById('rules-count').textContent = String(rules.length || 0);
document.getElementById('agenda-count').textContent = String(agenda.length || 0);
  document.getElementById('tags-count').textContent = String((tagsData.tags || []).length);

  await renderTokenChart();
  setInterval(renderTokenChart, 60000);

  async function pollDaemonStatus() {
    const s = await fetchAPI('/api/status');
    if (s.running) {
      statusEl.classList.add('running');
      statusEl.classList.toggle('fallback', s.system_mode === 'fallback');
      document.getElementById('offline-banner')?.remove();
    } else {
      statusEl.classList.remove('running');
      statusEl.classList.remove('fallback');
      if (!document.getElementById('offline-banner')) {
        const banner = document.createElement('div');
        banner.id = 'offline-banner';
        banner.innerHTML = `<strong>Dispatcher offline.</strong> Run <code>outheis start</code> in the terminal to restart.`;
        document.body.appendChild(banner);
      }
    }
  }
  await pollDaemonStatus();
  setInterval(pollDaemonStatus, 15000);

  checkForUpdate();
}

async function checkForUpdate() {
  const data = await fetchAPI('/api/version');

  // Populate version in sidebar regardless of update availability
  const verEl = document.getElementById('sidebar-version');
  if (verEl && data?.current) verEl.textContent = `v${data.current}`;

  if (!data?.update_available) return;

  const notice = document.getElementById('overview-update-slot');
  if (!notice) return;

  const date = data.release_date ? `<br>${escapeHtml(data.release_date)}` : '';
  notice.innerHTML = `
    <button class="btn btn-update" onclick="triggerUpdate()">Update</button>
    <div class="update-info-wrap">
      <span class="update-info-icon" tabindex="0">&#9432;</span>
      <div class="update-tooltip">v${escapeHtml(data.latest)}${date}</div>
    </div>
  `;
}

// Update is always user-initiated via the button — never called automatically
async function triggerUpdate() {
  await fetchAPI('/api/update', { method: 'POST' });
}

function escapeHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

init();
