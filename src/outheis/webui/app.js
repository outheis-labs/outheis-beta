/**
 * outheis Web UI
 */

let currentView = 'overview';
let currentTab = 'general';
let currentFile = null;
let fileMode = 'rendered';
let ws = null;
let config = null;
const taskDurations = {}; // {type: {seconds, ok}} — persists across re-renders
const activePolls = {};  // {type: {intervalId, btn}} — cleared on reconnect

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
    case 'files':
      await renderVaultFiles();
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

  const status = await fetchAPI('/api/status');
  const allMessages = await fetchAPI('/api/messages?limit=100');
  const conversations = allMessages.filter((msg) => msg.from?.user || msg.to === 'transport').slice(0, 10);

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
        <div class="card-header"><span class="card-title">Recent conversations</span></div>
        ${conversations.length ? conversations.map((msg) => renderMessage(msg)).join('') : '<div class="msg-item"><div class="msg-text" style="color: var(--text-tertiary);">No conversations yet</div></div>'}
      </div>
    </div>
  `;

  if (status.running) {
    statusEl.classList.add('running');
  } else {
    statusEl.classList.remove('running');
  }
}

function renderMessage(msg) {
  const time = msg.timestamp ? new Date(msg.timestamp * 1000).toLocaleString() : '';
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
            ${renderProviderCard('ollama', config.llm?.providers?.ollama)}
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
              ([alias, model]) => {
                const provider = model?.provider || 'anthropic';
                const name = model?.name || model || '';
                const runMode = model?.run_mode || 'on-demand';
                return `
            <div class="model-row" data-alias="${alias}">
              <input type="text" class="model-alias-input" value="${alias}" style="width: 90px; font-weight: 500;">
              <div class="model-provider">
                <select class="model-provider-select">
                  <option value="anthropic" ${provider === 'anthropic' ? 'selected' : ''}>anthropic</option>
                  <option value="openai" ${provider === 'openai' ? 'selected' : ''}>openai</option>
                  <option value="ollama" ${provider === 'ollama' ? 'selected' : ''}>ollama</option>
                </select>
              </div>
              <div class="model-name">
                <input type="text" class="model-name-input" value="${name}">
              </div>
              <div class="model-run-mode" title="on-demand: load per call · persistent: keep in memory (local models only)">
                <select class="model-run-mode-select">
                  <option value="on-demand" ${runMode === 'on-demand' ? 'selected' : ''}>on-demand</option>
                  <option value="persistent" ${runMode === 'persistent' ? 'selected' : ''}>persistent</option>
                </select>
              </div>
              <button class="btn btn-icon danger" onclick="removeRow(this)">×</button>
            </div>
          `;
              }
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
                    ${Object.keys(config.llm?.models || {fast:{},capable:{},reasoning:{}}).map(alias =>
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
    <div class="model-run-mode" title="on-demand: load per call · persistent: keep in memory (local models only)">
      <select class="model-run-mode-select">
        <option value="on-demand">on-demand</option>
        <option value="persistent">persistent</option>
      </select>
    </div>
    <button class="btn btn-icon danger" onclick="removeRow(this)">×</button>
  `;
  container.appendChild(row);
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
      vault: Array.from(document.querySelectorAll('.vault-input')).map((el) => el.value).filter((v) => v),
    };
  }

  // Providers tab
  const anthropicKey = document.getElementById('cfg-anthropic-key');
  if (anthropicKey) {
    updatedConfig.llm = updatedConfig.llm || {};
    updatedConfig.llm.providers = {
      anthropic: { api_key: anthropicKey.value, base_url: document.getElementById('cfg-anthropic-url')?.value },
      openai: { api_key: document.getElementById('cfg-openai-key')?.value, base_url: document.getElementById('cfg-openai-url')?.value },
      ollama: { base_url: document.getElementById('cfg-ollama-url')?.value },
    };
  }

  // Models tab
  const modelRows = document.querySelectorAll('.model-row');
  if (modelRows.length > 0) {
    updatedConfig.llm = updatedConfig.llm || {};
    updatedConfig.llm.models = {};
    modelRows.forEach((row) => {
      const alias = row.querySelector('.model-alias-input')?.value;
      const name = row.querySelector('.model-name-input')?.value;
      const provider = row.querySelector('.model-provider-select')?.value;
      const runMode = row.querySelector('.model-run-mode-select')?.value || 'on-demand';
      if (alias && name) updatedConfig.llm.models[alias] = { provider, name, run_mode: runMode };
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
        <textarea id="prompt-input" placeholder="Send a message to ou…" rows="2" style="flex: 1; resize: none; background: var(--bg-secondary); border: 1px solid var(--border-primary); border-radius: 6px; color: var(--text-primary); font-family: inherit; font-size: 13px; padding: 8px 10px; outline: none;" onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendPrompt();}"></textarea>
        <button class="btn btn-primary" onclick="sendPrompt()" style="align-self: flex-end;">Send</button>
      </div>
      <div style="overflow-y: auto; flex: 1;">
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
          ${renderScheduleRow('pattern_infer', schedule.pattern_infer)}
          ${renderScheduleRow('data_migrate', schedule.data_migrate)}
          ${renderScheduleRow('index_rebuild', schedule.index_rebuild)}
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

const SCHED_DEFAULTS = {
  agenda_review:    { time: Array.from({length: 20}, (_, i) => `${String(i + 4).padStart(2, '0')}:55`) },
  shadow_scan:      { time: ['03:30'] },
  pattern_infer:    { time: ['04:00'] },
  data_migrate:     { time: ['04:00'] },
  index_rebuild:    { time: ['04:30'] },
  archive_rotation: { time: ['05:00'] },
};

const SCHED_DESCRIPTIONS = {
  agenda_review:    'cato — personal secretary service',
  shadow_scan:      'zeno scans vault for new and changed files, updates context',
  pattern_infer:    'rumi analyzes message history to extract patterns and promote them to skills and rules',
  data_migrate:     'scans messages and insights for outdated schema versions — migrates records on next read',
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

  const allOptions = ['agenda_review', 'shadow_scan', 'pattern_infer', 'data_migrate', 'index_rebuild'];
  const selectOptions = allOptions.map((v) => `<option value="${v}" ${type === v ? 'selected' : ''}>${v}</option>`).join('');

  let timesHtml;
  if (isInterval) {
    const minutes = cfg.interval_minutes ?? 360;
    timesHtml = `<div class="sched-interval">every <input type="number" class="sched-interval-input" value="${minutes}" min="1" style="width:60px"> min</div>`;
  } else {
    const times = cfg.time?.length > 0 ? cfg.time : ['04:00'];
    timesHtml = `
      ${times.map((t) => `<div class="sched-time"><input type="text" class="sched-time-input" value="${t}"><span class="remove" onclick="removeTime(this)">×</span></div>`).join('')}
      <div class="sched-add" onclick="addTime(this, '${times[times.length - 1]}')">+</div>
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

async function runTask(type, btn) {
  const startedAt = Date.now();
  btn.textContent = 'Running…';
  btn.disabled = true;

  const durSpan = btn.nextElementSibling; // .sched-duration span

  const res = await fetchAPI(`/api/scheduler/run/${type}`, { method: 'POST' });
  if (res.error) {
    btn.textContent = '✗';
    btn.disabled = false;
    setTimeout(() => { btn.textContent = 'Run now'; }, 5000);
    return;
  }

  const convId = res.conversation_id;
  const deadline = Date.now() + 10 * 60 * 1000; // 10 min timeout

  const intervalId = setInterval(async () => {
    if (Date.now() > deadline) {
      clearInterval(intervalId);
      delete activePolls[type];
      btn.textContent = 'Run now';
      btn.disabled = false;
      return;
    }
    const messages = await fetchAPI('/api/messages?limit=100');
    const event = messages.find((m) =>
      m.conversation_id === convId &&
      m.from_agent === 'scheduler' &&
      m.payload?.status && m.payload.status !== 'started'
    );
    if (event) {
      clearInterval(intervalId);
      delete activePolls[type];
      const status = event.payload.status;
      const ok = status === 'completed';
      const skipped = status?.startsWith('skipped');
      const seconds = Math.round((Date.now() - startedAt) / 1000);
      if (!skipped) taskDurations[type] = { seconds, ok };
      btn.textContent = ok ? '✓' : (skipped ? '⏸' : '✗');
      btn.disabled = false;
      if (durSpan && !skipped) durSpan.textContent = `${ok ? '✓' : '✗'} ${seconds}s`;
      if (durSpan && skipped) durSpan.textContent = 'busy';
      if (!ok) setTimeout(() => { btn.textContent = 'Run now'; if (skipped && durSpan) durSpan.textContent = ''; }, 5000);
    }
  }, 2000);
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
        <option value="data_migrate">data_migrate</option>
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

async function deleteMemoryEntry(index) {
  const parsed = JSON.parse(currentFileContent);
  parsed.entries.splice(index, 1);
  parsed.updated_at = new Date().toISOString();
  const newContent = JSON.stringify(parsed, null, 2);
  const [type, filename] = [currentView, currentFile];
  await fetchAPI(`/api/${type}/${filename}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: newContent }),
  });
  currentFileContent = newContent;
  renderFileContent(newContent);
  showToast('Entry deleted');
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
      body.innerHTML = `<div class="file-md">${marked.parse(preprocessWikilinks(content))}</div>`;
    }
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

  const convId = res.conversation_id;
  const deadline = Date.now() + 10 * 60 * 1000;

  const intervalId = setInterval(async () => {
    if (Date.now() > deadline) {
      clearInterval(intervalId);
      btn.textContent = 'Scan';
      btn.disabled = false;
      return;
    }
    const messages = await fetchAPI('/api/messages?limit=100');
    const event = messages.find((m) =>
      m.conversation_id === convId &&
      m.from_agent === 'scheduler' &&
      m.payload?.status && m.payload.status !== 'started'
    );
    if (event) {
      clearInterval(intervalId);
      const ok = event.payload.status === 'completed';
      const skipped = event.payload.status?.startsWith('skipped');
      btn.textContent = ok ? '✓' : (skipped ? '⏸' : '✗');
      btn.disabled = false;
      setTimeout(async () => {
        await renderTags();
      }, 300);
      if (!ok) setTimeout(() => { btn.textContent = 'Scan'; }, 4000);
    }
  }, 2000);
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
    viewActions.innerHTML = '';
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

// WebSocket
function connectWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

  ws.onopen = () => { connectionStatus.textContent = 'Connected'; cancelActivePolls(); };
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === 'message' && currentView === 'messages') {
      const container = viewContent.querySelector('div');
      if (container) container.insertAdjacentHTML('afterbegin', renderMessage(data.data));
    }
  };
  ws.onclose = () => { connectionStatus.textContent = 'Disconnected'; setTimeout(connectWebSocket, 3000); };
  ws.onerror = () => { connectionStatus.textContent = 'Disconnected'; };
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
      <div class="file-list" id="vault-tree" style="overflow-y:auto;">
        ${vaults.map((v) => renderVaultTreeNode(v, 0)).join('')}
      </div>
      <div class="file-view">
        <div class="file-header">
          <span class="file-name" id="vault-filename">—</span>
          <div class="file-toggle">
            <button class="btn active" onclick="setFileMode('rendered', this)">Rendered</button>
            <button class="btn" onclick="setFileMode('source', this)">Source</button>
          </div>
        </div>
        <div class="file-body" id="file-body">
          <div class="file-md" style="color:var(--text-tertiary);font-size:13px;padding:24px;">Select a file from the tree.</div>
        </div>
      </div>
    </div>
  `;

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
    viewActions.innerHTML = `
      <button class="btn" style="color:var(--danger,#e05252);" onclick="deleteVaultFile()">Delete</button>
      <button class="btn btn-primary" onclick="saveVaultFile()">Save</button>
    `;
    currentVaultWikilinks = data.wikilinks || {};
    currentFileContent = data.content || '';
    fileMode = 'rendered';
    document.querySelectorAll('.file-toggle button').forEach((b) => b.classList.remove('active'));
    toggle.querySelector('button')?.classList.add('active');
    renderFileContent(currentFileContent);
  }
}

async function saveVaultFile() {
  if (!currentVaultPath) return;
  const raw = document.querySelector('.file-raw');
  if (raw) currentFileContent = raw.textContent;
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
  await renderView();
  connectWebSocket();

  const memory = await fetchAPI('/api/memory');
  const skills = await fetchAPI('/api/skills');
  const rules = await fetchAPI('/api/rules');
  const patterns = await fetchAPI('/api/patterns');
  const agenda = await fetchAPI('/api/agenda');
  const tagsData = await fetchAPI('/api/tags');

  document.getElementById('memory-count').textContent = String(memory.length || 0);
  document.getElementById('skills-count').textContent = String(skills.length || 0);
  document.getElementById('rules-count').textContent = String(rules.length || 0);
  document.getElementById('patterns-count').textContent = String(patterns.length || 0);
  document.getElementById('agenda-count').textContent = String(agenda.length || 0);
  document.getElementById('tags-count').textContent = String((tagsData.tags || []).length);

  await renderTokenChart();
  setInterval(renderTokenChart, 60000);
}

init();
