/**
 * outheis Web UI
 */

let currentView = 'overview';
let currentTab = 'general';
let currentFile = null;
let fileMode = 'rendered';
let ws = null;
let config = null;

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
  { key: 'agenda', name: 'cato', role: 'Daily.md, Inbox.md, Exchange.md' },
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
  renderView();
});

// Views
async function renderView() {
  viewTabs.innerHTML = '';
  viewActions.innerHTML = '';

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
    case 'patterns':
      await renderFileView('patterns', '~/.outheis/human/cache/patterns/');
      break;
    case 'agenda':
      await renderFileView('agenda', 'vault/Agenda/');
      break;
    case 'codebase':
      await renderFileView('codebase', 'vault/Codebase/');
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

  const status = await fetchAPI('/api/status');
  const messages = await fetchAPI('/api/messages?limit=10');

  viewContent.innerHTML = `
    <div class="scroll">
      <div class="metrics">
        <div class="metric">
          <div class="metric-label">Dispatcher</div>
          <div class="metric-value ${status.running ? 'success' : ''}">${status.running ? 'Running' : 'Stopped'}</div>
        </div>
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
      </div>
      <div class="card">
        <div class="card-header"><span class="card-title">Recent messages</span></div>
        ${messages.length ? messages.map((msg) => renderMessage(msg)).join('') : '<div class="msg-item"><div class="msg-text" style="color: var(--text-tertiary);">No messages yet</div></div>'}
      </div>
    </div>
  `;

  if (status.running) {
    statusEl.classList.add('running');
    statusEl.querySelector('.status-text').textContent = 'Running';
  } else {
    statusEl.classList.remove('running');
    statusEl.querySelector('.status-text').textContent = 'Stopped';
  }
}

function renderMessage(msg) {
  const time = msg.timestamp ? new Date(msg.timestamp).toLocaleTimeString() : '';
  const from = msg.from_agent || msg.from || 'system';
  const to = msg.to || '';
  const text = msg.payload?.text || msg.payload?.error || JSON.stringify(msg.payload || {});

  let agentClass = 'info';
  if (from === 'cato' || from === 'agenda') agentClass = 'success';
  else if (from === 'scheduler') agentClass = 'warning';

  const routing = to ? `${from} → ${to}` : from;

  return `
    <div class="msg-item">
      <div class="msg-header">
        <span class="msg-time">${time}</span>
        <span class="msg-agent ${agentClass}">${routing}</span>
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
  renderConfigTab();
}

function switchConfigTab(tab) {
  currentTab = tab;
  document.querySelectorAll('.tab').forEach((t, i) => {
    t.classList.toggle('active', ['general', 'providers', 'models', 'agents', 'signal'].indexOf(tab) === i);
  });
  renderConfigTab();
}

function renderConfigTab() {
  switch (currentTab) {
    case 'general':
      renderConfigGeneral();
      break;
    case 'providers':
      renderConfigProviders();
      break;
    case 'models':
      renderConfigModels();
      break;
    case 'agents':
      renderConfigAgents();
      break;
    case 'signal':
      renderConfigSignal();
      break;
  }
}

function renderConfigGeneral() {
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
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <span class="card-title">Vaults</span>
          <button class="btn" onclick="addVault()">+ Add vault</button>
        </div>
        <div class="card-body" id="vaults-container">
          ${(config.human?.vaults || [])
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
            ${renderProviderCard('anthropic', config.llm?.anthropic)}
            ${renderProviderCard('openai', config.llm?.openai)}
            ${renderProviderCard('ollama', config.llm?.ollama)}
          </div>
        </div>
      </div>
    </div>
  `;
}

function renderProviderCard(name, providerConfig) {
  const isActive = providerConfig?.api_key || (name === 'ollama' && providerConfig?.base_url);
  const displayName = name.charAt(0).toUpperCase() + name.slice(1);

  return `
    <div class="provider">
      <div class="provider-header">
        <span class="provider-name">${displayName}</span>
        <span class="provider-dot ${isActive ? 'active' : ''}"></span>
      </div>
      ${name !== 'ollama' ? `
        <div class="provider-field">
          <label>API key</label>
          <input type="password" id="cfg-${name}-key" value="${providerConfig?.api_key || ''}" placeholder="sk-...">
        </div>
      ` : ''}
      <div class="provider-field">
        <label>Base URL</label>
        <input type="text" id="cfg-${name}-url" value="${providerConfig?.base_url || getDefaultUrl(name)}">
      </div>
    </div>
  `;
}

function renderConfigModels() {
  const models = config.llm?.models || { fast: 'claude-haiku-4-5', capable: 'claude-sonnet-4-20250514', reasoning: 'claude-opus-4-5' };

  viewContent.innerHTML = `
    <div class="scroll">
      <div class="card">
        <div class="card-header">
          <span class="card-title">Model aliases</span>
          <button class="btn" onclick="addModel()">+ Add alias</button>
        </div>
        <div class="card-body" style="padding: 12px 20px;" id="models-container">
          ${Object.entries(models)
            .map(
              ([alias, model]) => `
            <div class="model-row" data-alias="${alias}">
              <input type="text" class="model-alias-input" value="${alias}" style="width: 90px; font-weight: 500;">
              <div class="model-provider">
                <select class="model-provider-select">
                  <option value="anthropic" ${model.startsWith('claude') ? 'selected' : ''}>anthropic</option>
                  <option value="openai" ${model.startsWith('gpt') || model.startsWith('o1') ? 'selected' : ''}>openai</option>
                  <option value="ollama" ${!model.startsWith('claude') && !model.startsWith('gpt') && !model.startsWith('o1') ? 'selected' : ''}>ollama</option>
                </select>
              </div>
              <div class="model-name">
                <input type="text" class="model-name-input" value="${model}">
              </div>
              <button class="btn btn-icon danger" onclick="removeRow(this)">×</button>
            </div>
          `
            )
            .join('')}
        </div>
      </div>
    </div>
  `;
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
                <div class="agent-info">
                  <span class="agent-name">${agent.name}</span>
                  <span class="agent-key">${agent.key}</span>
                </div>
                <div class="agent-role">${agent.role}</div>
                <div class="agent-model">
                  <select class="agent-model-select">
                    <option value="fast" ${model === 'fast' ? 'selected' : ''}>fast</option>
                    <option value="capable" ${model === 'capable' ? 'selected' : ''}>capable</option>
                    <option value="reasoning" ${model === 'reasoning' ? 'selected' : ''}>reasoning</option>
                  </select>
                </div>
                <div class="agent-toggle">
                  <input type="checkbox" class="agent-enabled" ${enabled ? 'checked' : ''}>
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
            <label class="form-label">Phone number</label>
            <div class="form-value">
              <input type="text" id="cfg-signal-phone" value="${config.signal?.phone || ''}">
            </div>
          </div>
          <div class="form-row">
            <label class="form-label">Signal CLI path</label>
            <div class="form-value">
              <input type="text" id="cfg-signal-cli" value="${config.signal?.cli_path || '/usr/local/bin/signal-cli'}">
            </div>
          </div>
          <div class="form-row" style="align-items: flex-start;">
            <label class="form-label">Whitelist</label>
            <div class="form-value" style="flex-direction: column; gap: 8px;" id="whitelist-container">
              ${(config.signal?.whitelist || [])
                .map(
                  (phone) => `
                <div class="whitelist-row">
                  <input type="text" class="whitelist-input" value="${phone}">
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
  return { anthropic: 'https://api.anthropic.com', openai: 'https://api.openai.com/v1', ollama: 'http://localhost:11434' }[provider] || '';
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
  const row = document.createElement('div');
  row.className = 'model-row';
  row.innerHTML = `
    <input type="text" class="model-alias-input" placeholder="alias" style="width: 90px; font-weight: 500;">
    <div class="model-provider">
      <select class="model-provider-select">
        <option value="anthropic">anthropic</option>
        <option value="openai">openai</option>
        <option value="ollama">ollama</option>
      </select>
    </div>
    <div class="model-name">
      <input type="text" class="model-name-input" placeholder="model-name">
    </div>
    <button class="btn btn-icon danger" onclick="removeRow(this)">×</button>
  `;
  container.appendChild(row);
}

function addWhitelist() {
  const container = document.getElementById('whitelist-container');
  const addBtn = container.querySelector('button:last-child');
  const row = document.createElement('div');
  row.className = 'whitelist-row';
  row.innerHTML = `
    <input type="text" class="whitelist-input" placeholder="+49...">
    <button class="btn btn-icon danger" onclick="removeRow(this)">×</button>
  `;
  container.insertBefore(row, addBtn);
}

function removeRow(btn) {
  btn.closest('.form-row, .model-row, .whitelist-row, .sched-row').remove();
}

async function saveConfig() {
  const updatedConfig = { ...config };

  // General tab
  const nameEl = document.getElementById('cfg-name');
  if (nameEl) {
    updatedConfig.human = {
      ...updatedConfig.human,
      name: nameEl.value,
      email: document.getElementById('cfg-email')?.value,
      phone: document.getElementById('cfg-phone')?.value,
      language: document.getElementById('cfg-language')?.value,
      timezone: document.getElementById('cfg-timezone')?.value,
      vaults: Array.from(document.querySelectorAll('.vault-input')).map((el) => el.value).filter((v) => v),
    };
  }

  // Providers tab
  const anthropicKey = document.getElementById('cfg-anthropic-key');
  if (anthropicKey) {
    updatedConfig.llm = updatedConfig.llm || {};
    updatedConfig.llm.anthropic = { api_key: anthropicKey.value, base_url: document.getElementById('cfg-anthropic-url')?.value };
    updatedConfig.llm.openai = { api_key: document.getElementById('cfg-openai-key')?.value, base_url: document.getElementById('cfg-openai-url')?.value };
    updatedConfig.llm.ollama = { base_url: document.getElementById('cfg-ollama-url')?.value };
  }

  // Models tab
  const modelRows = document.querySelectorAll('.model-row');
  if (modelRows.length > 0) {
    updatedConfig.llm = updatedConfig.llm || {};
    updatedConfig.llm.models = {};
    modelRows.forEach((row) => {
      const alias = row.querySelector('.model-alias-input')?.value;
      const model = row.querySelector('.model-name-input')?.value;
      if (alias && model) updatedConfig.llm.models[alias] = model;
    });
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
    updatedConfig.signal = {
      enabled: signalEnabled.checked,
      phone: document.getElementById('cfg-signal-phone')?.value,
      cli_path: document.getElementById('cfg-signal-cli')?.value,
      whitelist: Array.from(document.querySelectorAll('.whitelist-input')).map((el) => el.value).filter((v) => v),
    };
  }

  await fetchAPI('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(updatedConfig) });
  config = updatedConfig;
  showToast('Configuration saved');
}

// Messages
async function renderMessages() {
  viewTitle.textContent = 'Messages';
  viewPath.textContent = '~/.outheis/human/messages.jsonl';
  viewTabs.innerHTML = '<div class="tab active">Live</div><div class="tab">Archive</div>';

  const messages = await fetchAPI('/api/messages?limit=50');
  viewContent.innerHTML = `
    <div style="overflow-y: auto; flex: 1; background: var(--bg-primary);">
      ${messages.length ? messages.map((msg) => renderMessage(msg)).join('') : '<div class="msg-item"><div class="msg-text" style="color: var(--text-tertiary);">No messages yet</div></div>'}
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

function renderSchedulerTasks() {
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
          ${renderScheduleRow('pattern_nightly', schedule.pattern_nightly)}
          ${schedule.index_rebuild ? renderScheduleRow('index_rebuild', schedule.index_rebuild) : ''}
        </div>
      </div>
    </div>
  `;
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

function renderScheduleRow(type, schedConfig) {
  const enabled = schedConfig?.enabled ?? true;
  const times = schedConfig?.times || (schedConfig?.hour !== undefined ? [`${String(schedConfig.hour).padStart(2, '0')}:${String(schedConfig.minute || 0).padStart(2, '0')}`] : ['04:00']);

  return `
    <div class="sched-row" data-type="${type}">
      <div class="sched-type">
        <select class="sched-type-select">
          <option value="agenda_review" ${type === 'agenda_review' ? 'selected' : ''}>agenda_review</option>
          <option value="shadow_scan" ${type === 'shadow_scan' ? 'selected' : ''}>shadow_scan</option>
          <option value="pattern_nightly" ${type === 'pattern_nightly' ? 'selected' : ''}>pattern_nightly</option>
          <option value="index_rebuild" ${type === 'index_rebuild' ? 'selected' : ''}>index_rebuild</option>
        </select>
      </div>
      <div class="sched-times">
        ${times.map((t) => `<div class="sched-time"><input type="text" class="sched-time-input" value="${t}"><span class="remove" onclick="removeTime(this)">×</span></div>`).join('')}
        <div class="sched-add" onclick="addTime(this, '${times[times.length - 1]}')">+</div>
      </div>
      <div><input type="checkbox" class="sched-enabled" ${enabled ? 'checked' : ''}></div>
      <button class="btn btn-icon danger" onclick="removeRow(this)" style="margin-left: 8px;">×</button>
    </div>
  `;
}

function addScheduleTask() {
  const container = document.getElementById('schedule-container');
  const row = document.createElement('div');
  row.className = 'sched-row';
  row.innerHTML = `
    <div class="sched-type">
      <select class="sched-type-select">
        <option value="agenda_review">agenda_review</option>
        <option value="shadow_scan">shadow_scan</option>
        <option value="pattern_nightly">pattern_nightly</option>
        <option value="index_rebuild">index_rebuild</option>
      </select>
    </div>
    <div class="sched-times">
      <div class="sched-time"><input type="text" class="sched-time-input" value="04:00"><span class="remove" onclick="removeTime(this)">×</span></div>
      <div class="sched-add" onclick="addTime(this, '04:00')">+</div>
    </div>
    <div><input type="checkbox" class="sched-enabled" checked></div>
    <button class="btn btn-icon danger" onclick="removeRow(this)" style="margin-left: 8px;">×</button>
  `;
  container.appendChild(row);
}

function addTime(btn, lastTime) {
  const [h, m] = lastTime.split(':').map(Number);
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
    const times = Array.from(row.querySelectorAll('.sched-time-input')).map((el) => el.value).filter((v) => v && v.match(/^\d{2}:\d{2}$/));
    if (type && times.length > 0) updatedConfig.schedule[type] = { enabled, times };
  });

  await fetchAPI('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(updatedConfig) });
  config = updatedConfig;
  showToast('Schedule saved');
}

// File view
async function renderFileView(type, pathPrefix) {
  viewTitle.textContent = type.charAt(0).toUpperCase() + type.slice(1);
  viewPath.textContent = pathPrefix;
  viewActions.innerHTML = '<button class="btn btn-primary" onclick="saveCurrentFile()">Save</button>';

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

  currentFile = fileList[0].name;
  fileMode = 'rendered';

  viewContent.innerHTML = `
    <div class="file-split">
      <div class="file-list">
        ${fileList.map((f) => `<div class="file-item ${f.name === currentFile ? 'active' : ''}" onclick="openFile('${type}', '${f.name}', this)"><span>${f.name}</span><span class="file-size">${formatSize(f.size)}</span></div>`).join('')}
      </div>
      <div class="file-view">
        <div class="file-header">
          <span class="file-name">${currentFile}</span>
          <div class="file-toggle">
            <button class="btn active" onclick="setFileMode('rendered', this)">Rendered</button>
            <button class="btn" onclick="setFileMode('source', this)">Source</button>
          </div>
        </div>
        <div class="file-body" id="file-body"></div>
      </div>
    </div>
  `;

  await loadFile(type, currentFile);
}

async function openFile(type, filename, el) {
  document.querySelectorAll('.file-item').forEach((e) => e.classList.remove('active'));
  el.classList.add('active');
  currentFile = filename;
  document.querySelector('.file-name').textContent = filename;
  await loadFile(type, filename);
}

let currentFileContent = '';

async function loadFile(type, filename) {
  const data = await fetchAPI(`/api/${type}/${filename}`);
  currentFileContent = data.content || '';
  renderFileContent(currentFileContent);
}

function renderFileContent(content) {
  const body = document.getElementById('file-body');
  if (fileMode === 'rendered') {
    body.innerHTML = `<div class="file-md">${marked.parse(content)}</div>`;
  } else {
    body.innerHTML = `<div class="file-raw" contenteditable spellcheck="false">${escapeHtml(content)}</div>`;
  }
}

function setFileMode(mode, btn) {
  // Save current content if in source mode
  const raw = document.querySelector('.file-raw');
  if (raw) currentFileContent = raw.textContent;

  fileMode = mode;
  document.querySelectorAll('.file-toggle button').forEach((b) => b.classList.remove('active'));
  btn.classList.add('active');
  renderFileContent(currentFileContent);
}

async function saveCurrentFile() {
  const raw = document.querySelector('.file-raw');
  if (raw) currentFileContent = raw.textContent;

  if (!currentFileContent && fileMode === 'rendered') {
    showToast('Switch to Source mode to edit');
    return;
  }

  await fetchAPI(`/api/${currentView}/${currentFile}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: currentFileContent }),
  });

  showToast('File saved');
}

// Migration
async function renderMigration() {
  viewTitle.textContent = 'Migration';
  viewPath.textContent = 'vault/Migration/';

  const data = await fetchAPI('/api/migration');

  if (!data.exists) {
    viewContent.innerHTML = `
      <div class="scroll">
        <div class="empty">
          <div class="empty-title">Migration directory not found</div>
          <div class="empty-text">Create the directory to enable migrations.</div>
          <button class="btn btn-primary" onclick="createMigrationDir()">Create vault/Migration</button>
        </div>
      </div>
    `;
  } else {
    viewContent.innerHTML = `
      <div class="scroll">
        <div class="drop-zone">Drop migration files here<br><span style="font-size: 11px;">(.py or .md files)</span></div>
        <div class="card">
          <div class="card-header"><span class="card-title">Migration files</span></div>
          ${data.files.length ? data.files.map((f) => `<div class="msg-item"><div class="msg-header"><span class="msg-time" style="width: 180px;">${f.name}</span><span class="file-size">${formatSize(f.size)}</span></div></div>`).join('') : '<div class="msg-item"><div class="msg-text" style="color: var(--text-tertiary);">No migration files yet</div></div>'}
        </div>
      </div>
    `;
  }
}

async function createMigrationDir() {
  await fetchAPI('/api/migration/create', { method: 'POST' });
  await renderMigration();
}

// WebSocket
function connectWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

  ws.onopen = () => { connectionStatus.textContent = 'Connected'; };
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === 'message' && currentView === 'messages') {
      const container = viewContent.querySelector('div');
      if (container) container.insertAdjacentHTML('afterbegin', renderMessage(data.data));
    }
  };
  ws.onclose = () => { connectionStatus.textContent = 'Disconnected'; setTimeout(connectWebSocket, 3000); };
  ws.onerror = () => { connectionStatus.textContent = 'Error'; };
}

// Utilities
async function fetchAPI(url, options = {}) {
  try {
    const response = await fetch(url, options);
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

function showToast(message) {
  const existing = document.querySelector('.toast');
  if (existing) existing.remove();

  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = message;
  document.body.appendChild(toast);

  setTimeout(() => toast.classList.add('show'), 10);
  setTimeout(() => { toast.classList.remove('show'); setTimeout(() => toast.remove(), 300); }, 2000);
}

// Init
async function init() {
  await renderView();
  connectWebSocket();

  const memory = await fetchAPI('/api/memory');
  const skills = await fetchAPI('/api/skills');
  const rules = await fetchAPI('/api/rules');
  const patterns = await fetchAPI('/api/patterns');
  const agenda = await fetchAPI('/api/agenda');

  document.getElementById('memory-count').textContent = String(memory.length || 0);
  document.getElementById('skills-count').textContent = String(skills.length || 0);
  document.getElementById('rules-count').textContent = String(rules.length || 0);
  document.getElementById('patterns-count').textContent = String(patterns.length || 0);
  document.getElementById('agenda-count').textContent = String(agenda.length || 0);
}

init();
