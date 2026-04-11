/**
 * Main app controller -- vanilla JS, no framework.
 * Chat UX inspired by Tressol-Chabrier retail ops frontend.
 */

let currentStep = 1;
const TOTAL_STEPS = 7;
let chatStreaming = false;
let selectedProvider = 'openai';
let savedAgentName = '';
let savedAgentType = 'Default';
let savedModel = 'gpt-5';
let savedTemperature = 0.3;
let savedSystemPrompt = '';
let currentAgentId = null;
let builderExpanded = false;

const stepTitles = {
    1: 'Agent Creation',
    2: 'Model Selection',
    3: 'Knowledge Upload',
    4: 'Tools',
    5: 'Governance',
    6: 'Execution',
    7: 'Save Agent',
};
const headerSubtitles = {
    1: 'Create Your Agent',
    2: 'Connect to a Model',
    3: 'Upload Knowledge Documents',
    4: 'Configure Tools',
    5: 'Review Governance Controls',
    6: 'Run the Agent',
    7: 'Review & Save Configuration',
};

function toggleTheme() {
    const html = document.documentElement;
    const isDark = html.getAttribute('data-theme') === 'dark';
    html.setAttribute('data-theme', isDark ? 'light' : 'dark');
    localStorage.setItem('omnirag_theme', isDark ? 'light' : 'dark');
    const icon = document.getElementById('theme-icon');
    if (icon) icon.textContent = isDark ? 'dark_mode' : 'light_mode';
}

function toggleBuilderNav() {
    builderExpanded = !builderExpanded;
    const nav = document.getElementById('step-nav');
    const chev = document.getElementById('builder-chevron');
    if (nav) {
        nav.style.maxHeight = builderExpanded ? '400px' : '0';
        nav.style.opacity = builderExpanded ? '1' : '0';
    }
    if (chev) chev.style.transform = builderExpanded ? 'rotate(180deg)' : 'rotate(0deg)';
}

(function initTheme() {
    const saved = localStorage.getItem('omnirag_theme');
    if (saved) document.documentElement.setAttribute('data-theme', saved);
    const icon = document.getElementById('theme-icon');
    if (icon) icon.textContent = (saved || 'dark') === 'dark' ? 'light_mode' : 'dark_mode';
})();

async function loadStepModules() {
    const mod = await import('./steps.js');
    return mod;
}

async function renderStep(step) {
    const mod = await loadStepModules();
    const fns = {
        1: mod.step1_agentCreation,
        2: mod.step2_modelSelection,
        3: mod.step3_knowledgeUpload,
        4: mod.step4_rulesTools,
        5: mod.step5_governance,
        6: mod.step6_execution,
        7: mod.step7_save,
    };
    const content = document.getElementById('step-content');
    content.innerHTML = fns[step]();

    if (step === 2) loadRAGSettings();
    if (step === 3) { initFileUpload(); loadKBStats(); }
    if (step === 5) loadAuditData();
    if (step === 6) initChat();
}

function updateStepIndicators(step) {
    document.querySelectorAll('.step-btn').forEach(btn => {
        const s = parseInt(btn.dataset.step);
        const ind = btn.querySelector('.step-indicator');
        ind.classList.remove('step-active', 'step-completed', 'step-pending');
        if (s < step) ind.classList.add('step-completed');
        else if (s === step) ind.classList.add('step-active');
        else ind.classList.add('step-pending');
    });
}

function persistAgentConfig() {
    const nameEl = document.getElementById('agent-name');
    const typeEl = document.getElementById('agent-type');
    const modelEl = document.getElementById('model-select');
    const tempEl = document.getElementById('temp-slider');
    const promptEl = document.querySelector('.code-editor');
    if (nameEl) savedAgentName = nameEl.value;
    if (typeEl) savedAgentType = typeEl.value;
    if (modelEl) savedModel = modelEl.value;
    if (tempEl) savedTemperature = parseInt(tempEl.value) / 100;
    if (promptEl) savedSystemPrompt = promptEl.value;
}

function getAgentName() {
    const el = document.getElementById('agent-name');
    return el ? el.value : savedAgentName;
}

function updateHeader(step) {
    const title = document.getElementById('header-title');
    const sub = document.getElementById('step-title');
    const btn = document.getElementById('next-btn');
    if (title) title.textContent = stepTitles[step];
    if (sub) sub.textContent = step === 6 ? `Run ${getAgentName()}` : headerSubtitles[step];
    if (btn) {
        if (step === 7) {
            btn.innerHTML = '<span class="material-icons-outlined text-base">save</span> Save Agent';
            btn.onclick = saveCurrentAgent;
            btn.style.display = '';
        } else {
            btn.innerHTML = 'Next Step <span class="material-icons-outlined text-lg">arrow_forward</span>';
            btn.onclick = nextStep;
            btn.style.display = '';
        }
    }
}

function goToStep(step) {
    if (step < 1 || step > TOTAL_STEPS) return;
    persistAgentConfig();
    currentStep = step;
    currentPage = 'builder';
    updateStepIndicators(step);
    updateHeader(step);
    renderStep(step);

    const btn = document.getElementById('next-btn');
    if (btn) btn.style.display = '';

    if (!builderExpanded) toggleBuilderNav();
    updateSidebarActive(null);
}

function nextStep() {
    if (currentStep >= TOTAL_STEPS) goToStep(1);
    else goToStep(currentStep + 1);
}

// -- Sidebar Page Navigation --

let currentPage = 'hub';

const pageConfig = {
    hub:           { title: 'Agent Hub',       breadcrumb: 'Agent Hub' },
    agents:        { title: 'My Agents',       breadcrumb: 'Agents' },
    integrations:  { title: 'Integrations',    breadcrumb: 'Integrations' },
    orchestration: { title: 'Orchestration',   breadcrumb: 'Orchestration' },
    knowledge:     { title: 'Knowledge Base',  breadcrumb: 'Knowledge Base' },
    access:        { title: 'Access & Roles',  breadcrumb: 'Access & Roles' },
    audit:         { title: 'Audit Logs',      breadcrumb: 'Audit Logs' },
};

function updateSidebarActive(page) {
    document.querySelectorAll('.sidebar-link').forEach(link => {
        const p = link.dataset.page;
        if (p === page) {
            link.style.background = 'linear-gradient(90deg,rgba(0,188,212,0.12),transparent)';
            link.style.borderLeft = '3px solid var(--accent)';
            link.style.color = '#fff';
            const icon = link.querySelector('.material-icons-outlined');
            if (icon) icon.classList.add('text-brand-400');
        } else {
            link.style.background = 'transparent';
            link.style.borderLeft = '3px solid transparent';
            link.style.color = 'var(--text-muted)';
            const icon = link.querySelector('.material-icons-outlined');
            if (icon) icon.classList.remove('text-brand-400');
        }
    });
}

async function goToPage(page) {
    currentPage = page;
    updateSidebarActive(page);

    const mod = await loadStepModules();
    const content = document.getElementById('step-content');
    const cfg = pageConfig[page];
    const title = document.getElementById('header-title');
    const sub = document.getElementById('step-title');
    const btn = document.getElementById('next-btn');

    if (title) title.textContent = cfg.breadcrumb;
    if (sub) sub.textContent = cfg.title;
    if (btn) btn.style.display = 'none';

    content.className = 'flex-1 overflow-y-auto p-5 page-enter';

    if (page === 'hub') {
        content.innerHTML = mod.page_agentHub();
        loadHubAgents();
    } else if (page === 'agents') {
        content.innerHTML = mod.page_agents();
        loadAgentsPage();
    } else if (page === 'integrations') {
        content.innerHTML = mod.page_integrations();
    } else if (page === 'orchestration') {
        content.innerHTML = mod.page_orchestration();
    } else if (page === 'knowledge') {
        content.innerHTML = mod.page_knowledgeBase();
        initFileUpload();
        loadKBStats();
    } else if (page === 'access') {
        content.innerHTML = mod.page_accessRoles();
    } else if (page === 'audit') {
        content.innerHTML = mod.page_auditLogs();
        loadAuditPage();
    }

    document.querySelectorAll('.step-btn').forEach(btn => {
        const ind = btn.querySelector('.step-indicator');
        ind.classList.remove('step-active');
        if (!ind.classList.contains('step-completed')) ind.classList.add('step-pending');
    });
}

async function loadKBStats() {
    try {
        const api = await import('./api.js');
        const [stats, docList] = await Promise.all([
            api.getDocumentStats(),
            api.listDocuments(),
        ]);
        const docEl = document.getElementById('kb-doc-count');
        const chunkEl = document.getElementById('kb-chunk-count');
        const statsEl = document.getElementById('kb-stats');
        const dimEl = document.getElementById('kb-vector-dim');
        if (docEl) docEl.textContent = docList.total || 0;
        if (chunkEl) chunkEl.textContent = stats.total_chunks || 0;
        if (statsEl) statsEl.querySelector('p').textContent = stats.total_chunks || 0;
        if (dimEl) dimEl.textContent = stats.vector_dim || '—';

        renderDocList(document.getElementById('kb-documents'), docList.documents || []);
        renderDocList(document.getElementById('preloaded-docs'), docList.documents || []);
    } catch (e) { /* non-blocking */ }
}

function renderDocList(container, docs) {
    if (!container || !docs.length) {
        if (container) container.innerHTML = '<p class="text-xs text-slate-400">No documents indexed yet.</p>';
        return;
    }
    container.innerHTML = docs.map(doc => {
        const fname = doc.filename || '';
        const isPdf = fname.toLowerCase().endsWith('.pdf');
        const name = fname.replace(/\.(md|txt|pdf|docx)$/i, '').replace(/_/g, ' ');
        const displayName = name.charAt(0).toUpperCase() + name.slice(1);
        const icon = isPdf ? 'picture_as_pdf' : 'description';
        const iconColor = isPdf ? 'text-red-500' : 'text-brand-500';
        return `<div onclick="openDocPreview('${doc.document_id}', '${escapeHtml(fname)}')" class="flex items-center justify-between p-2.5 bg-slate-50 rounded-lg hover:bg-brand-50 hover:border-brand-200 border border-transparent cursor-pointer transition-colors group">
            <div class="flex items-center gap-2.5 min-w-0">
                <span class="material-icons-outlined ${iconColor} text-lg">${icon}</span>
                <div class="min-w-0">
                    <p class="text-sm font-medium text-slate-800 truncate group-hover:text-brand-700">${escapeHtml(displayName)}</p>
                    <p class="text-[11px] text-slate-400">${isPdf ? 'PDF' : escapeHtml(doc.document_type || 'document')}</p>
                </div>
            </div>
            <div class="flex items-center gap-2 shrink-0">
                <span class="px-2 py-0.5 text-[10px] font-medium bg-emerald-100 text-emerald-700 rounded-full">Indexed</span>
                <span class="material-icons-outlined text-slate-300 text-sm group-hover:text-brand-400">visibility</span>
                <button onclick="event.stopPropagation(); deleteIndexedDoc('${doc.document_id}', this)" class="w-6 h-6 flex items-center justify-center rounded hover:bg-red-50 transition-colors opacity-0 group-hover:opacity-100">
                    <span class="material-icons-outlined text-slate-400 hover:text-red-500 text-sm">delete</span>
                </button>
            </div>
        </div>`;
    }).join('');
}

async function loadAuditPage() {
    try {
        const api = await import('./api.js');
        const [summary, logs] = await Promise.all([
            api.getAuditSummary(),
            api.listAuditLogs(20),
        ]);

        const statsEl = document.getElementById('audit-page-stats');
        if (statsEl) statsEl.querySelector('p').textContent = summary.total_events || 0;

        const tbody = document.getElementById('audit-table-body');
        if (!tbody) return;

        if (!logs.logs || logs.logs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="px-3 py-8 text-center text-slate-400 text-sm">No audit events yet. Execute the agent to generate entries.</td></tr>';
            return;
        }

        tbody.innerHTML = logs.logs.map(log => {
            const ts = new Date(log.timestamp);
            const time = ts.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
            const date = ts.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
            const sevClass = log.severity === 'error' ? 'bg-red-100 text-red-700' :
                             log.severity === 'warning' ? 'bg-amber-100 text-amber-700' :
                             'bg-slate-100 text-slate-600';
            return `<tr class="border-b border-slate-100 hover:bg-slate-50">
                <td class="px-3 py-2 text-slate-500 whitespace-nowrap">${date} ${time}</td>
                <td class="px-3 py-2 font-medium text-slate-700">${escapeHtml(log.event_type)}</td>
                <td class="px-3 py-2 text-slate-600">${escapeHtml(log.actor || '—')}</td>
                <td class="px-3 py-2 font-mono text-slate-500">${escapeHtml(log.agent_id || '—')}</td>
                <td class="px-3 py-2"><span class="px-1.5 py-0.5 text-[10px] font-medium ${sevClass} rounded">${escapeHtml(log.severity || 'info')}</span></td>
            </tr>`;
        }).join('');
    } catch (e) {
        const tbody = document.getElementById('audit-table-body');
        if (tbody) tbody.innerHTML = '<tr><td colspan="5" class="px-3 py-8 text-center text-slate-400 text-sm">Could not load audit events.</td></tr>';
    }
}

// -- Step 1: capability toggle --

function toggleCap(label) {
    setTimeout(() => {
        const cb = label.querySelector('input[type="checkbox"]');
        if (cb && cb.checked) {
            label.classList.remove('bg-slate-50', 'border-slate-200');
            label.classList.add('bg-emerald-50', 'border-emerald-200');
        } else {
            label.classList.remove('bg-emerald-50', 'border-emerald-200');
            label.classList.add('bg-slate-50', 'border-slate-200');
        }
    }, 0);
}

// -- Step 2: provider selection --

function selectProvider(card) {
    document.querySelectorAll('.provider-card').forEach(c => {
        c.classList.remove('border-brand-500', 'bg-brand-50', 'border-2');
        c.classList.add('border', 'border-slate-200');
        const check = c.querySelector('.provider-check');
        if (check) check.classList.add('hidden');
    });
    card.classList.remove('border', 'border-slate-200');
    card.classList.add('border-2', 'border-brand-500', 'bg-brand-50');
    const check = card.querySelector('.provider-check');
    if (check) check.classList.remove('hidden');
    selectedProvider = card.dataset.provider;

    const modelSel = document.getElementById('model-select');
    if (modelSel) {
        const models = {
            openai: [['gpt-5', 'GPT-5'], ['gpt-4.5', 'GPT-4.5'], ['gpt-4o-mini', 'GPT-4o-mini']],
            anthropic: [['claude-opus-4-6', 'Claude Opus 4.6'], ['claude-sonnet-4-6', 'Claude Sonnet 4.6'], ['claude-haiku-4-5-20251001', 'Claude Haiku 4.5']],
            selfhosted: [
                ['mistral-3-14b', 'Mistral 3 (14B)'],
                ['gemma-4', 'Gemma 4 (31B)'],
                ['llama-3.1-8b', 'Llama 3.1 (8B)'],
                ['gpt-oss-20b', 'GPT-OSS (20B)'],
                ['phi-4-14b', 'Phi-4 (14B)'],
                ['qwen-3.5-9b', 'Qwen 3.5 (9B)'],
            ],
        };
        const opts = models[selectedProvider] || models.openai;
        modelSel.innerHTML = opts.map(([v, l], i) => `<option value="${v}"${i === 0 ? ' selected' : ''}>${l}</option>`).join('');
    }
}

function updateTempLabel(slider) {
    const val = (parseInt(slider.value) / 100).toFixed(1);
    const label = document.getElementById('temp-label');
    const descs = { '0.0': 'Deterministic', '0.1': 'Very precise', '0.2': 'Precise', '0.3': 'Precise and deterministic', '0.5': 'Balanced', '0.7': 'Creative', '0.8': 'Very creative', '1.0': 'Maximum creativity' };
    const desc = descs[val] || (val < 0.4 ? 'Precise' : val < 0.7 ? 'Balanced' : 'Creative');
    if (label) label.textContent = `${val} — ${desc}`;
}

// -- User dropdown --

function toggleUserDropdown() {
    const dd = document.getElementById('user-dropdown');
    if (!dd) return;
    const isHidden = dd.classList.contains('hidden');
    dd.classList.toggle('hidden');
    if (isHidden) {
        document.getElementById('dd-name').textContent = currentUser.name;
        document.getElementById('dd-email').textContent = currentUser.email;
        document.getElementById('dd-role').textContent = currentUser.role || 'Admin';
    }
}

function signOut() {
    location.reload();
}

function showToast(msg) {
    const existing = document.getElementById('toast-msg');
    if (existing) existing.remove();
    const toast = document.createElement('div');
    toast.id = 'toast-msg';
    toast.className = 'fixed bottom-4 right-4 z-[9999] px-3.5 py-2.5 text-[12px] rounded-xl flex items-center gap-2 animate-slideUp';
    toast.style.cssText = 'background:var(--bg-card);color:var(--text-primary);border:1px solid var(--border-default);box-shadow:0 8px 32px rgba(0,0,0,0.3);';
    toast.innerHTML = `<span class="material-icons-outlined text-sm" style="color:var(--accent);">info</span>${msg}`;
    document.body.appendChild(toast);
    setTimeout(() => { toast.style.opacity = '0'; toast.style.transition = 'opacity 0.3s'; setTimeout(() => toast.remove(), 300); }, 2500);
}

// Close dropdown on outside click
document.addEventListener('click', (e) => {
    const badge = document.getElementById('user-badge');
    const dd = document.getElementById('user-dropdown');
    if (dd && !dd.classList.contains('hidden') && badge && !badge.contains(e.target) && !dd.contains(e.target)) {
        dd.classList.add('hidden');
    }
});

// -- Access & Roles: invite form --

function toggleInviteForm() {
    const form = document.getElementById('invite-form');
    if (!form) return;
    form.classList.toggle('hidden');
    if (!form.classList.contains('hidden')) {
        const input = document.getElementById('invite-email');
        if (input) input.focus();
    }
}

function sendInvite() {
    const emailInput = document.getElementById('invite-email');
    const email = emailInput?.value?.trim();
    if (!email || !email.includes('@')) {
        if (emailInput) { emailInput.classList.add('border-red-300'); emailInput.focus(); }
        return;
    }
    emailInput.classList.remove('border-red-300');

    const form = document.getElementById('invite-form');
    if (form) {
        form.innerHTML = `<div class="flex items-center gap-2 py-2">
            <span class="material-icons-outlined text-emerald-600 text-sm">check_circle</span>
            <span class="text-sm text-emerald-700">Invitation sent to <strong>${email}</strong></span>
        </div>`;
        setTimeout(() => form.classList.add('hidden'), 3000);
    }
}

// -- Step 2: RAG settings --

async function loadRAGSettings() {
    try {
        const res = await fetch('/api/v1/settings');
        const data = await res.json();
        const s = data.settings || {};
        const topk = document.getElementById('rag-topk');
        const vw = document.getElementById('rag-vweight');
        const th = document.getElementById('rag-threshold');
        if (topk) { topk.value = s.ragTopK || 5; document.getElementById('rag-topk-val').textContent = topk.value; }
        if (vw) { vw.value = Math.round((s.ragVectorWeight || 0.7) * 100); document.getElementById('rag-vweight-val').textContent = (vw.value / 100).toFixed(1); }
        if (th) { th.value = Math.round((s.ragSimilarityThreshold || 0.2) * 100); document.getElementById('rag-threshold-val').textContent = (th.value / 100).toFixed(2); }
    } catch (e) { /* non-blocking */ }
}

async function saveRAGSettings() {
    const btn = document.getElementById('save-rag-settings');
    try {
        const topk = parseInt(document.getElementById('rag-topk')?.value || '5');
        const vw = parseInt(document.getElementById('rag-vweight')?.value || '70') / 100;
        const th = parseInt(document.getElementById('rag-threshold')?.value || '20') / 100;

        const res = await fetch('/api/v1/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                ragTopK: topk,
                ragVectorWeight: vw,
                ragBM25Weight: parseFloat((1 - vw).toFixed(2)),
                ragSimilarityThreshold: th,
            }),
        });
        if (res.ok && btn) {
            btn.innerHTML = '<span class="material-icons-outlined text-xs">check</span> Saved';
            btn.classList.remove('text-brand-600', 'bg-brand-50');
            btn.classList.add('text-emerald-600', 'bg-emerald-50');
            setTimeout(() => {
                btn.innerHTML = '<span class="material-icons-outlined text-xs">save</span> Save';
                btn.classList.remove('text-emerald-600', 'bg-emerald-50');
                btn.classList.add('text-brand-600', 'bg-brand-50');
            }, 2000);
        }
    } catch (e) {
        if (btn) btn.textContent = 'Error';
    }
}

// -- Step 4: rules editing --

let rulesEditing = false;

function toggleEditRules() {
    rulesEditing = !rulesEditing;
    const btn = document.getElementById('edit-rules-btn');
    const rows = document.querySelectorAll('.rule-row');

    if (rulesEditing) {
        if (btn) {
            btn.innerHTML = '<span class="material-icons-outlined text-sm">check</span> Done';
            btn.classList.remove('text-amber-700', 'bg-amber-50', 'hover:bg-amber-100');
            btn.classList.add('text-emerald-700', 'bg-emerald-50', 'hover:bg-emerald-100');
        }
        rows.forEach(row => {
            row.classList.add('border-amber-200', 'bg-amber-50/30');
            row.classList.remove('border-slate-200');
            const actions = row.querySelector('.rule-actions');
            if (actions) {
                actions.classList.remove('hidden');
                actions.innerHTML = `
                    <button onclick="event.stopPropagation(); changeRuleSeverity(this.closest('.rule-row'))" class="p-1 rounded hover:bg-amber-100 transition" title="Change severity">
                        <span class="material-icons-outlined text-amber-600 text-sm">swap_vert</span>
                    </button>
                    <button onclick="event.stopPropagation(); removeRule(this.closest('.rule-row'))" class="p-1 rounded hover:bg-red-100 transition" title="Remove rule">
                        <span class="material-icons-outlined text-red-500 text-sm">delete_outline</span>
                    </button>`;
            }
        });
    } else {
        if (btn) {
            btn.innerHTML = '<span class="material-icons-outlined text-sm">edit</span> Edit rules';
            btn.classList.add('text-amber-700', 'bg-amber-50', 'hover:bg-amber-100');
            btn.classList.remove('text-emerald-700', 'bg-emerald-50', 'hover:bg-emerald-100');
        }
        rows.forEach(row => {
            row.classList.remove('border-amber-200', 'bg-amber-50/30');
            row.classList.add('border-slate-200');
            const actions = row.querySelector('.rule-actions');
            if (actions) { actions.classList.add('hidden'); actions.innerHTML = ''; }
        });
    }
}

function changeRuleSeverity(row) {
    const badge = row.querySelector('.rule-severity');
    if (!badge) return;
    const cycle = ['CRITICAL', 'MAJOR', 'MINOR'];
    const colors = { CRITICAL: ['bg-red-100', 'text-red-700'], MAJOR: ['bg-amber-100', 'text-amber-700'], MINOR: ['bg-blue-100', 'text-blue-700'] };
    const barColors = { CRITICAL: 'bg-red-500', MAJOR: 'bg-amber-500', MINOR: 'bg-blue-500' };
    const cur = badge.textContent.trim();
    const next = cycle[(cycle.indexOf(cur) + 1) % cycle.length];
    badge.textContent = next;
    badge.className = `px-2 py-0.5 text-[10px] font-bold ${colors[next][0]} ${colors[next][1]} rounded-full rule-severity`;
    const bar = row.querySelector('.w-1\\.5');
    if (bar) { bar.className = `w-1.5 h-7 rounded ${barColors[next]}`; }
}

function removeRule(row) {
    row.style.transition = 'all 0.3s ease';
    row.style.opacity = '0';
    row.style.transform = 'translateX(20px)';
    setTimeout(() => row.remove(), 300);
}

function openRuleSource(row) {
    if (rulesEditing) return;
    const docId = row.dataset.docId;
    const docTitle = row.dataset.docTitle;
    if (docId && docTitle) openDocPreview(docId, docTitle);
}

// -- Document Preview --

async function openDocPreview(docId, title) {
    const modal = document.getElementById('doc-preview-modal');
    const titleEl = document.getElementById('doc-preview-title');
    const body = document.getElementById('doc-preview-body');
    if (!modal) return;

    titleEl.textContent = title || 'Document';
    body.innerHTML = '<div class="flex items-center justify-center h-32 text-slate-400 text-sm">Loading…</div>';
    modal.classList.remove('hidden');

    try {
        const api = await import('./api.js');
        const doc = await api.previewDocument(docId);

        if (doc.content_type === 'application/pdf' && doc.download_url) {
            body.innerHTML = `<iframe src="${doc.download_url}" class="w-full rounded-lg border border-slate-200" style="height:calc(100vh - 180px);min-height:500px" frameborder="0"></iframe>`;
        } else if (doc.content) {
            body.innerHTML = renderMarkdown(doc.content);
        } else {
            body.innerHTML = '<p class="text-sm text-slate-500">No preview available for this file type.</p>';
        }
    } catch (e) {
        body.innerHTML = `<p class="text-sm text-red-500">Could not load document preview.</p>`;
    }
}

function confirmResetKB() {
    const modal = document.getElementById('reset-kb-modal');
    if (modal) { modal.style.display = 'flex'; modal.classList.remove('hidden'); }
}

function closeResetKBModal() {
    const modal = document.getElementById('reset-kb-modal');
    if (modal) { modal.style.display = 'none'; modal.classList.add('hidden'); }
}

async function doResetKB() {
    const btn = document.getElementById('reset-kb-confirm-btn');
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="material-icons-outlined text-sm animate-spin">sync</span> Resetting…'; }
    try {
        const api = await import('./api.js');
        await api.clearAllDocuments();
        closeResetKBModal();
        showToast('Knowledge base reset');
        loadKBStats();
    } catch (e) {
        showToast(`Reset failed: ${e.message}`);
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '<span class="material-icons-outlined text-sm">delete_forever</span> Reset Knowledge Base'; }
    }
}

// -- Agent Library (localStorage) --

function saveCurrentAgent() {
    persistAgentConfig();
    const agent = {
        id: 'agent_' + Date.now(),
        name: savedAgentName || 'My Agent',
        type: savedAgentType || 'Default',
        model: savedModel || 'gpt-5',
        provider: selectedProvider || 'openai',
        temperature: savedTemperature ?? 0.3,
        systemPrompt: savedSystemPrompt || '',
        createdAt: new Date().toISOString(),
    };
    const agents = JSON.parse(localStorage.getItem('omnirag_agents') || '[]');
    agents.unshift(agent);
    localStorage.setItem('omnirag_agents', JSON.stringify(agents));

    const actionsEl = document.getElementById('step7-actions');
    if (actionsEl) {
        actionsEl.innerHTML = `
            <div class="flex flex-col items-center py-5 text-center">
                <div class="w-10 h-10 rounded-full bg-emerald-100 flex items-center justify-center mb-2">
                    <span class="material-icons-outlined text-emerald-600 text-xl">check_circle</span>
                </div>
                <p class="text-[13px] font-semibold text-slate-800 mb-0.5">Agent saved!</p>
                <p class="text-[11px] text-slate-500 mb-3">${escapeHtml(agent.name)} has been added to your library.</p>
                <div class="flex items-center gap-2">
                    <button onclick="goToPage('agents')" class="px-3 py-1.5 text-[12px] font-medium text-white bg-brand-600 hover:bg-brand-700 rounded-md transition-colors">
                        View Agents
                    </button>
                    <button onclick="goToStep(1)" class="px-3 py-1.5 text-[12px] font-medium text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-md transition-colors">
                        New Agent
                    </button>
                </div>
            </div>`;
    }
}

function loadAgentsPage() {
    const container = document.getElementById('agents-list');
    if (!container) return;
    const agents = JSON.parse(localStorage.getItem('omnirag_agents') || '[]');
    if (!agents.length) {
        container.innerHTML = `
            <div class="flex flex-col items-center py-10 text-center">
                <span class="material-icons-outlined text-slate-300 text-4xl mb-2">smart_toy</span>
                <p class="text-[13px] font-medium text-slate-500">No agents saved yet</p>
                <p class="text-[11px] text-slate-400 mt-0.5 mb-3">Use the Agent Builder to create and save your first agent</p>
                <button onclick="goToStep(1)" class="px-3 py-1.5 text-[12px] font-medium text-brand-600 bg-brand-50 hover:bg-brand-100 rounded-md transition-colors">
                    Create Agent
                </button>
            </div>`;
        return;
    }
    const providerColors = { openai: 'emerald', anthropic: 'amber', 'self-hosted': 'violet' };
    container.innerHTML = agents.map(agent => {
        const date = new Date(agent.createdAt).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
        const pc = providerColors[agent.provider] || 'slate';
        return `
        <div class="flex items-center justify-between p-3 bg-slate-50 rounded-lg border border-slate-100 hover:border-brand-200 hover:bg-brand-50 transition-colors group">
            <div class="flex items-center gap-3 min-w-0">
                <div class="w-8 h-8 rounded-md bg-brand-100 flex items-center justify-center shrink-0">
                    <span class="material-icons-outlined text-brand-600 text-base">smart_toy</span>
                </div>
                <div class="min-w-0">
                    <p class="text-[13px] font-semibold text-slate-800 truncate">${escapeHtml(agent.name)}</p>
                    <div class="flex items-center gap-1.5 mt-0.5 flex-wrap">
                        <span class="px-1.5 py-0.5 text-[9px] font-medium bg-slate-200 text-slate-600 rounded">${escapeHtml(agent.type)}</span>
                        <span class="px-1.5 py-0.5 text-[9px] font-medium bg-${pc}-100 text-${pc}-700 rounded">${escapeHtml(agent.model)}</span>
                        <span class="text-[10px] text-slate-400">${date}</span>
                    </div>
                </div>
            </div>
            <div class="flex items-center gap-2 shrink-0">
                <button onclick="chatWithAgent('${agent.id}')" class="px-2.5 py-1.5 text-[11px] font-medium text-white bg-brand-600 hover:bg-brand-700 rounded-md transition-colors flex items-center gap-1">
                    <span class="material-icons-outlined text-sm">chat</span>Chat
                </button>
                <button onclick="deleteAgent('${agent.id}')" class="w-7 h-7 flex items-center justify-center rounded-md hover:bg-red-50 transition-colors opacity-0 group-hover:opacity-100">
                    <span class="material-icons-outlined text-slate-400 hover:text-red-500 text-sm">delete</span>
                </button>
            </div>
        </div>`;
    }).join('');
}

function chatWithAgent(agentId) {
    const agents = JSON.parse(localStorage.getItem('omnirag_agents') || '[]');
    const agent = agents.find(a => a.id === agentId);
    if (!agent) return;
    savedAgentName = agent.name;
    savedAgentType = agent.type;
    savedModel = agent.model;
    selectedProvider = agent.provider;
    savedTemperature = agent.temperature;
    savedSystemPrompt = agent.systemPrompt;
    currentAgentId = agentId;
    goToStep(6);
}

function deleteAgent(agentId) {
    const agents = JSON.parse(localStorage.getItem('omnirag_agents') || '[]');
    localStorage.setItem('omnirag_agents', JSON.stringify(agents.filter(a => a.id !== agentId)));
    loadAgentsPage();
    showToast('Agent deleted');
}

async function loadHubAgents() {
    const grid = document.getElementById('hub-agents-grid');
    if (!grid) return;

    const prebuilt = [
        { id: 'procurement', name: 'Procurement Agent', type: 'Procurement', icon: 'verified_user', color: '#00bcd4', desc: 'Vendor qualification, compliance validation, and document verification against procurement policies.', model: 'gpt-4o' },
        { id: 'legal', name: 'Legal Review', type: 'Legal', icon: 'gavel', color: '#8b5cf6', desc: 'Contract analysis, clause extraction, risk assessment, and regulatory compliance review.', model: 'gpt-4o' },
        { id: 'hr', name: 'HR Assistant', type: 'HR', icon: 'people', color: '#f59e0b', desc: 'Policy Q&A, onboarding support, leave management, and employee handbook queries.', model: 'gpt-4o-mini' },
        { id: 'finance', name: 'Financial Analyst', type: 'Finance', icon: 'account_balance', color: '#10b981', desc: 'Financial statement analysis, budget tracking, forecasting, and expense validation.', model: 'gpt-4o' },
    ];

    const savedAgents = JSON.parse(localStorage.getItem('omnirag_agents') || '[]');

    let html = '';
    prebuilt.forEach(a => {
        html += `
        <div class="agent-hub-card group" onclick="launchPrebuiltAgent('${a.id}')">
            <div class="flex items-start justify-between mb-3">
                <div class="w-10 h-10 rounded-xl flex items-center justify-center" style="background:${a.color}20;">
                    <span class="material-icons-outlined text-xl" style="color:${a.color};">${a.icon}</span>
                </div>
                <div class="flex items-center gap-1.5">
                    <span class="w-2 h-2 rounded-full" style="background:var(--success);"></span>
                    <span class="text-[10px] font-medium" style="color:var(--success);">Ready</span>
                </div>
            </div>
            <h3 class="text-[14px] font-semibold mb-1" style="color:var(--text-primary);">${a.name}</h3>
            <p class="text-[11px] leading-relaxed mb-3" style="color:var(--text-muted);">${a.desc}</p>
            <div class="flex items-center gap-2">
                <span class="px-2 py-0.5 text-[9px] font-medium rounded-md" style="background:var(--accent-subtle);color:var(--accent);">${a.model}</span>
                <span class="px-2 py-0.5 text-[9px] font-medium rounded-md" style="background:var(--bg-elevated);color:var(--text-muted);">${a.type}</span>
            </div>
        </div>`;
    });

    savedAgents.forEach(a => {
        html += `
        <div class="agent-hub-card group" onclick="chatWithAgent('${a.id}')">
            <div class="flex items-start justify-between mb-3">
                <div class="w-10 h-10 rounded-xl flex items-center justify-center" style="background:var(--accent-subtle);">
                    <span class="material-icons-outlined text-xl" style="color:var(--accent);">smart_toy</span>
                </div>
                <span class="text-[10px] font-mono" style="color:var(--text-muted);">Custom</span>
            </div>
            <h3 class="text-[14px] font-semibold mb-1" style="color:var(--text-primary);">${escapeHtml(a.name)}</h3>
            <p class="text-[11px] mb-3" style="color:var(--text-muted);">Custom agent &middot; ${escapeHtml(a.type)}</p>
            <div class="flex items-center gap-2">
                <span class="px-2 py-0.5 text-[9px] font-medium rounded-md" style="background:var(--accent-subtle);color:var(--accent);">${escapeHtml(a.model)}</span>
            </div>
        </div>`;
    });

    html += `
    <div class="agent-hub-card agent-hub-create flex flex-col items-center justify-center text-center" onclick="goToStep(1)" style="min-height:180px;">
        <span class="material-icons-outlined text-3xl mb-2" style="color:var(--text-muted);">add_circle_outline</span>
        <p class="text-[13px] font-semibold" style="color:var(--text-secondary);">Create Agent</p>
        <p class="text-[11px] mt-0.5" style="color:var(--text-muted);">Build from scratch</p>
    </div>`;

    grid.innerHTML = html;
}

function launchPrebuiltAgent(agentId) {
    const configs = {
        procurement: { name: 'Procurement Agent', type: 'Procurement' },
        legal: { name: 'Legal Review', type: 'Legal' },
        hr: { name: 'HR Assistant', type: 'HR' },
        finance: { name: 'Financial Analyst', type: 'Finance' },
    };
    const cfg = configs[agentId];
    if (!cfg) return;
    savedAgentName = cfg.name;
    savedAgentType = cfg.type;
    currentAgentId = agentId;
    goToStep(6);
}

function closeDocPreview() {
    const modal = document.getElementById('doc-preview-modal');
    if (modal) modal.classList.add('hidden');
}

async function loadPreloadedDocs() {
    try {
        const api = await import('./api.js');
        const docList = await api.listDocuments();
        renderDocList(document.getElementById('preloaded-docs'), docList.documents || []);
    } catch (e) { /* non-blocking */ }
}

async function deleteIndexedDoc(documentId, btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="material-icons-outlined text-slate-300 text-sm animate-spin">sync</span>';
    const row = btn.closest('.group');
    try {
        const api = await import('./api.js');
        await api.deleteDocument(documentId);
        showToast('Document deleted');
        if (row) {
            row.style.transition = 'opacity 0.2s ease, transform 0.2s ease';
            row.style.opacity = '0';
            row.style.transform = 'translateX(8px)';
            setTimeout(() => {
                row.remove();
                loadKBStats();
            }, 210);
        } else {
            loadKBStats();
        }
    } catch (e) {
        showToast(`Delete failed: ${e.message}`);
        btn.disabled = false;
        btn.innerHTML = '<span class="material-icons-outlined text-slate-400 hover:text-red-500 text-sm">delete</span>';
    }
}

// -- File Upload (Step 3) --

function initFileUpload() {
    const zone = document.getElementById('upload-zone');
    const input = document.getElementById('file-input');
    if (!zone || !input) return;

    zone.addEventListener('click', () => input.click());
    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('border-brand-400', 'bg-brand-50'); });
    zone.addEventListener('dragleave', () => { zone.classList.remove('border-brand-400', 'bg-brand-50'); });
    zone.addEventListener('drop', e => {
        e.preventDefault();
        zone.classList.remove('border-brand-400', 'bg-brand-50');
        handleFiles(e.dataTransfer.files);
    });
    input.addEventListener('change', () => handleFiles(input.files));
}

async function handleFiles(files) {
    const container = document.getElementById('uploaded-files');
    for (const file of files) {
        const row = document.createElement('div');
        row.className = 'flex items-center justify-between p-3 bg-brand-50 border border-brand-200 rounded-lg';
        const isPdf = file.name.toLowerCase().endsWith('.pdf');
        const icon = isPdf ? 'picture_as_pdf' : 'upload_file';
        row.innerHTML = `
            <div class="flex items-center gap-3">
                <span class="material-icons-outlined ${isPdf ? 'text-red-500' : 'text-brand-500'}">${icon}</span>
                <div>
                    <p class="text-sm font-medium text-slate-800">${escapeHtml(file.name)}</p>
                    <p class="text-xs text-slate-500">${(file.size / 1024).toFixed(1)} KB</p>
                </div>
            </div>
            <div class="flex items-center gap-2">
                <span class="upload-status px-2 py-0.5 text-xs font-medium bg-amber-100 text-amber-700 rounded-full">Uploading...</span>
            </div>
        `;
        container.appendChild(row);

        try {
            const api = await import('./api.js');
            const result = await api.uploadDocument(file);
            loadKBStats();
            row.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
            row.style.opacity = '0';
            row.style.transform = 'translateY(-4px)';
            setTimeout(() => row.remove(), 310);
        } catch (e) {
            const badge = row.querySelector('.upload-status');
            badge.className = 'upload-status px-2 py-0.5 text-xs font-medium bg-red-100 text-red-700 rounded-full';
            badge.textContent = 'Error';
        }
    }
}

// -- Audit (Step 5) --

async function loadAuditData() {
    try {
        const api = await import('./api.js');
        const summary = await api.getAuditSummary();
        const el = document.getElementById('audit-count');
        if (el) el.textContent = `${summary.total_events} events logged`;

        const logsData = await api.listAuditLogs(8);
        const logsList = logsData.logs || [];
        const container = document.getElementById('audit-logs');
        if (container && logsList.length > 0) {
            container.innerHTML = logsList.map(ev => {
                const time = ev.timestamp ? new Date(ev.timestamp).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }) : '';
                const icon = ev.event_type === 'agent_execution' ? 'smart_toy' : ev.event_type === 'document_upload' ? 'upload_file' : 'event';
                const color = ev.event_type === 'agent_execution' ? 'text-brand-600' : ev.event_type === 'document_upload' ? 'text-emerald-600' : 'text-slate-500';
                const detail = typeof ev.details === 'object' ? (ev.details.query || JSON.stringify(ev.details)).substring(0, 80) : (ev.details || '—');
                return `<div class="flex items-center gap-3 p-2 rounded-lg hover:bg-white transition-colors">
                    <span class="material-icons-outlined ${color} text-sm">${icon}</span>
                    <span class="flex-1 truncate">${ev.event_type || 'event'}: ${escapeHtml(detail)}</span>
                    <span class="text-slate-400 text-[10px] shrink-0">${time}</span>
                    <span class="text-slate-400 text-[10px] shrink-0">${ev.actor || '—'}</span>
                </div>`;
            }).join('');
        }
    } catch (e) {
        const el = document.getElementById('audit-count');
        if (el) el.textContent = 'Connected';
    }
}

// -- Voice --

let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
let ttsEnabled = false;

async function toggleMic() {
    if (isRecording) {
        stopRecording();
    } else {
        startRecording();
    }
}

async function startRecording() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
        audioChunks = [];
        mediaRecorder.ondataavailable = e => { if (e.data.size > 0) audioChunks.push(e.data); };
        mediaRecorder.onstop = async () => {
            stream.getTracks().forEach(t => t.stop());
            const blob = new Blob(audioChunks, { type: 'audio/webm' });
            const micBtn = document.getElementById('mic-btn');
            if (micBtn) { micBtn.innerHTML = '<span class="material-icons-outlined text-sm animate-spin">sync</span>'; }
            try {
                const api = await import('./api.js');
                const result = await api.transcribeAudio(blob);
                const input = document.getElementById('chat-input');
                if (input && result.text) { input.value = result.text; input.focus(); }
            } catch (e) {
                showToast('Transcription failed: ' + e.message);
            } finally {
                if (micBtn) { micBtn.innerHTML = '<span class="material-icons-outlined text-sm">mic</span>'; }
            }
        };
        mediaRecorder.start();
        isRecording = true;
        const micBtn = document.getElementById('mic-btn');
        if (micBtn) { micBtn.innerHTML = '<span class="material-icons-outlined text-sm text-red-500 pulse-ring">stop</span>'; }
    } catch (e) {
        showToast('Microphone access denied');
    }
}

function stopRecording() {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') mediaRecorder.stop();
    isRecording = false;
}

function toggleTTS() {
    ttsEnabled = !ttsEnabled;
    const btn = document.getElementById('tts-btn');
    if (btn) {
        btn.style.color = ttsEnabled ? 'var(--accent)' : 'var(--text-muted)';
        btn.title = ttsEnabled ? 'Speaker on' : 'Speaker off';
    }
    showToast(ttsEnabled ? 'Voice output enabled' : 'Voice output disabled');
}

async function playTTS(text) {
    if (!ttsEnabled || !text) return;
    try {
        const api = await import('./api.js');
        const clean = text.replace(/[#*_`\[\]|]/g, '').substring(0, 2000);
        const blob = await api.synthesizeSpeech(clean);
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        audio.play();
        audio.onended = () => URL.revokeObjectURL(url);
    } catch (e) { /* non-blocking */ }
}

// -- Chat / Execution (Step 6) --

function initChat() {
    const input = document.getElementById('chat-input');
    if (!input) return;

    input.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendChat();
        }
    });

    input.addEventListener('input', () => {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 120) + 'px';
    });
}

function sendSuggestion(btn) {
    const text = btn.textContent.trim();
    const input = document.getElementById('chat-input');
    if (input) input.value = text;
    sendChat();
}

async function sendChat() {
    const input = document.getElementById('chat-input');
    const messagesDiv = document.getElementById('chat-messages');
    const sendBtn = document.getElementById('chat-send');
    const statusEl = document.getElementById('chat-status');
    if (!input || !input.value.trim() || chatStreaming) return;

    const query = input.value.trim();
    chatStreaming = true;
    input.disabled = true;
    sendBtn.disabled = true;
    input.value = '';
    input.style.height = 'auto';

    // Hide welcome/suggestions
    const welcome = document.getElementById('chat-welcome');
    if (welcome) welcome.remove();

    // User message bubble
    appendUserMessage(messagesDiv, query);

    // Assistant container
    const assistantEl = appendAssistantShell(messagesDiv);
    const toolsContainer = assistantEl.querySelector('.tools-container');
    const textContainer = assistantEl.querySelector('.text-container');

    if (statusEl) statusEl.textContent = 'Processing…';
    let accumulatedText = '';
    let hasText = false;

    const api = await import('./api.js');
    api.streamChat(
        query,
        {
            model: document.getElementById('model-select')?.value || savedModel || 'gpt-5',
            provider: selectedProvider || 'openai',
            temperature: parseInt(document.getElementById('temp-slider')?.value ?? String(Math.round(savedTemperature * 100))) / 100,
            system_prompt: document.querySelector('.code-editor')?.value || savedSystemPrompt || null,
        },
        // onChunk
        (chunk) => {
            if (chunk.chunk_type === 'decision_step' && chunk.decision_step) {
                renderToolCallCard(toolsContainer, chunk.decision_step);
                scrollChat(messagesDiv);
            }
            if (chunk.chunk_type === 'text' && chunk.content) {
                if (!hasText) {
                    hasText = true;
                    textContainer.classList.remove('hidden');
                }
                accumulatedText += chunk.content;
                textContainer.innerHTML = `<div class="prose-chat cursor-blink">${renderMarkdown(accumulatedText)}</div>`;
                scrollChat(messagesDiv);
            }
            if (chunk.chunk_type === 'error') {
                textContainer.classList.remove('hidden');
                textContainer.innerHTML = `<p class="text-sm text-red-600">${escapeHtml(chunk.content)}</p>`;
            }
        },
        // onDone
        () => {
            chatStreaming = false;
            input.disabled = false;
            sendBtn.disabled = false;
            if (statusEl) statusEl.textContent = '';

            // Update agent label: remove "processing" indicator
            const processingLabel = assistantEl.querySelector('.agent-processing');
            if (processingLabel) processingLabel.remove();

            // Remove cursor blink
            const blink = textContainer.querySelector('.cursor-blink');
            if (blink) blink.classList.remove('cursor-blink');

            toolsContainer.querySelectorAll('.tool-card-running').forEach(el => {
                el.classList.remove('tool-card-running');
                el.style.borderColor = 'rgba(16,185,129,0.2)';
                el.style.background = 'var(--bg-elevated)';
            });
            toolsContainer.querySelectorAll('.tool-status-label').forEach(el => el.remove());

            // Remove loading dots
            const dots = assistantEl.querySelector('.loading-dots');
            if (dots) dots.remove();

            logAuditEvent(api, query, accumulatedText);
            playTTS(accumulatedText);
            input.focus();
        },
        // onError
        (err) => {
            chatStreaming = false;
            input.disabled = false;
            sendBtn.disabled = false;
            if (statusEl) statusEl.textContent = '';
            textContainer.classList.remove('hidden');
            textContainer.innerHTML = `<p class="text-sm text-red-600">Connection error: ${escapeHtml(err.message)}</p>`;
        }
    );
}

function appendUserMessage(container, text) {
    const div = document.createElement('div');
    div.className = 'flex justify-end';
    div.innerHTML = `
        <div class="max-w-[75%] rounded-xl px-3.5 py-2.5 text-[13px] leading-relaxed whitespace-pre-wrap text-white" style="background:var(--accent);">
            ${escapeHtml(text)}
        </div>
    `;
    container.appendChild(div);
}

function appendAssistantShell(container) {
    const div = document.createElement('div');
    div.className = 'flex flex-col gap-1.5 assistant-msg';
    div.innerHTML = `
        <div class="flex items-center gap-1.5">
            <span class="block w-0.5 h-3 rounded-sm" style="background:var(--accent);"></span>
            <span class="text-[9px] font-semibold uppercase tracking-widest" style="color:var(--text-muted);">Agent</span>
            <span class="agent-processing text-[10px] ml-1" style="color:var(--text-muted);">— processing…</span>
        </div>
        <div class="ml-2.5 space-y-1 tools-container"></div>
        <div class="text-container ml-2.5 rounded-xl px-4 py-3 hidden" style="background:var(--bg-elevated);border:1px solid var(--border-default);"></div>
        <div class="loading-dots ml-2.5 flex gap-1 items-center h-4">
            <span class="w-1.5 h-1.5 rounded-full dot-bounce" style="background:var(--text-muted);animation-delay:0ms"></span>
            <span class="w-1.5 h-1.5 rounded-full dot-bounce" style="background:var(--text-muted);animation-delay:150ms"></span>
            <span class="w-1.5 h-1.5 rounded-full dot-bounce" style="background:var(--text-muted);animation-delay:300ms"></span>
        </div>
    `;
    container.appendChild(div);
    return div;
}

const STEP_ICONS = {
    query_received: 'input', query_rewrite: 'auto_fix_high', embedding: 'hub',
    retrieve: 'search', context_filtering: 'filter_alt', validation: 'verified',
    synthesis: 'edit_note', evaluation: 'analytics',
    document_ingestion: 'description', routing: 'alt_route', default: 'settings',
};

function renderToolCallCard(container, step) {
    const existing = document.getElementById('tool-' + step.id);
    const isRunning = step.status === 'active';
    const isDone = step.status === 'completed';
    const isError = step.status === 'error';
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';

    const iconColor = isRunning ? 'var(--accent)' : isError ? 'var(--error)' : isDone ? 'var(--success)' : 'var(--text-muted)';
    const titleColor = isRunning ? 'var(--text-primary)' : isDone ? 'var(--text-secondary)' : 'var(--text-muted)';
    const borderColor = isRunning ? 'var(--border-active)' : isError ? 'rgba(239,68,68,0.3)' : isDone ? 'rgba(16,185,129,0.2)' : 'var(--border-default)';
    const bgColor = isRunning ? (isDark ? 'rgba(0,188,212,0.06)' : '#f0fdfa') : isError ? (isDark ? 'rgba(239,68,68,0.06)' : '#fef2f2') : 'var(--bg-elevated)';
    const iconName = STEP_ICONS[step.type] || STEP_ICONS.default;

    const statusHtml = isRunning
        ? `<span class="tool-status-label text-[10px] ml-auto font-medium" style="color:var(--accent)">running…</span>`
        : '';
    const durationHtml = isDone && step.duration
        ? `<span class="text-[10px] font-mono ml-auto" style="color:var(--text-muted);">${step.duration}ms</span>`
        : '';

    const metricsHtml = (step.metrics && isDone) ? renderMetricsGauges(step.metrics) : '';

    const descLines = (step.description || '').split('\n').filter(l => l.trim());
    const descHtml = !metricsHtml && descLines.length > 0
        ? `<div class="mt-0.5 space-y-0">${descLines.map(l => `<p class="text-[10px] leading-tight" style="color:var(--text-muted);">${escapeHtml(l)}</p>`).join('')}</div>`
        : '';

    const html = `
        <div id="tool-${step.id}" class="rounded-lg border px-3 py-2 transition-all ${isRunning ? 'tool-card-running' : ''}" style="background:${bgColor};border-color:${borderColor}">
            <div class="flex items-center gap-2 mb-0.5">
                <span class="material-icons-outlined shrink-0" style="font-size:15px;color:${iconColor}">${iconName}</span>
                <span class="text-[12px] font-mono font-semibold" style="color:${titleColor}">${escapeHtml(step.component)}</span>
                ${statusHtml}
                ${durationHtml}
            </div>
            <div class="flex items-center gap-1.5 text-[10px] mb-0.5 pl-6" style="color:var(--text-muted);">
                <span>${escapeHtml(step.title)}</span>
                <span>&middot;</span>
                <span class="font-mono">${escapeHtml(step.model || '')}</span>
            </div>
            <div class="pl-6">${metricsHtml || descHtml}</div>
        </div>
    `;

    if (existing) {
        existing.outerHTML = html;
    } else {
        container.insertAdjacentHTML('beforeend', html);
    }
}

function renderMetricsGauges(metrics) {
    const scoreLabels = {
        relevance: 'Relevance',
        factuality: 'Factuality',
        coherence: 'Coherence',
        hhem: 'HHEM',
        adv_hhem: 'Adv. HHEM',
    };
    const latencyKeys = { llm_latency: 'LLM latency', total_latency: 'Total pipeline' };

    function scoreColor(key, v) {
        if (key === 'hhem' || key === 'adv_hhem') {
            return v > 0.5 ? '#ef4444' : v > 0.3 ? '#f59e0b' : '#10b981';
        }
        return v >= 0.7 ? '#10b981' : v >= 0.4 ? '#f59e0b' : '#ef4444';
    }
    function latencyColor(ms) {
        return ms < 3000 ? '#10b981' : ms < 8000 ? '#f59e0b' : '#ef4444';
    }

    let bars = '';
    for (const [key, val] of Object.entries(metrics)) {
        if (latencyKeys[key]) continue;
        const pct = Math.round(val * 100);
        const color = scoreColor(key, val);
        const label = scoreLabels[key] || key;
        bars += `
            <div class="flex items-center gap-1.5" style="margin-bottom:2px">
                <span style="font-size:10px;color:var(--text-muted);width:64px;flex-shrink:0;font-family:'Inter',sans-serif">${label}</span>
                <div style="flex:1;height:4px;background:var(--border-default);border-radius:2px;overflow:hidden">
                    <div style="width:${pct}%;height:100%;background:${color};border-radius:2px;transition:width 0.5s ease"></div>
                </div>
                <span style="font-size:10px;font-family:'JetBrains Mono',monospace;color:${color};width:32px;text-align:right;font-weight:600">${val.toFixed(2)}</span>
            </div>
        `;
    }

    const hasLatency = metrics.llm_latency != null || metrics.total_latency != null;
    if (hasLatency) {
        bars += `<div style="border-top:1px solid var(--border-default);margin:4px 0 2px"></div>`;
        for (const [key, label] of Object.entries(latencyKeys)) {
            const ms = metrics[key];
            if (ms == null) continue;
            const color = latencyColor(ms);
            const display = ms >= 1000 ? (ms / 1000).toFixed(1) + 's' : ms + 'ms';
            bars += `
                <div class="flex items-center gap-1.5" style="margin-bottom:2px">
                    <span style="font-size:10px;color:var(--text-muted);width:64px;flex-shrink:0;font-family:'Inter',sans-serif">${label}</span>
                    <div style="flex:1"></div>
                    <span style="font-size:10px;font-family:'JetBrains Mono',monospace;color:${color};font-weight:600">${display}</span>
                </div>
            `;
        }
    }

    return `<div style="margin-top:3px">${bars}</div>`;
}

function scrollChat(container) {
    container.scrollTop = container.scrollHeight;
}

async function logAuditEvent(api, query, response) {
    try {
        await api.createAuditEvent({
            event_type: 'agent_execution',
            actor: currentUser.email,
            agent_id: 'procurement',
            details: { query: query.substring(0, 200), response_length: response.length },
        });
    } catch (e) {
        // non-blocking
    }
}

// -- Markdown Renderer --

function renderMarkdown(text) {
    let html = escapeHtml(text);

    // Code blocks (``` ... ```)
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) =>
        `<pre><code>${code.trim()}</code></pre>`
    );

    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Headers
    html = html.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

    // Bold and italic
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

    // Horizontal rules
    html = html.replace(/^---$/gm, '<hr>');

    // Tables
    html = html.replace(/^(\|.+\|)\n(\|[\s\-:|]+\|)\n((?:\|.+\|\n?)+)/gm, (_, headerRow, sepRow, bodyRows) => {
        const headers = headerRow.split('|').filter(c => c.trim()).map(c => `<th>${c.trim()}</th>`).join('');
        const rows = bodyRows.trim().split('\n').map(row => {
            const cells = row.split('|').filter(c => c.trim()).map(c => `<td>${c.trim()}</td>`).join('');
            return `<tr>${cells}</tr>`;
        }).join('');
        return `<table><thead><tr>${headers}</tr></thead><tbody>${rows}</tbody></table>`;
    });

    // Unordered lists
    html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>\n?)+/g, match => `<ul>${match}</ul>`);

    // Ordered lists
    html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');

    // Blockquotes
    html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');

    // Paragraphs: convert double newlines
    html = html.replace(/\n\n/g, '</p><p>');
    html = html.replace(/\n/g, '<br>');
    html = '<p>' + html + '</p>';

    // Clean empty paragraphs
    html = html.replace(/<p>\s*<\/p>/g, '');
    html = html.replace(/<p>(<h[1-4]>)/g, '$1');
    html = html.replace(/(<\/h[1-4]>)<\/p>/g, '$1');
    html = html.replace(/<p>(<table>)/g, '$1');
    html = html.replace(/(<\/table>)<\/p>/g, '$1');
    html = html.replace(/<p>(<ul>)/g, '$1');
    html = html.replace(/(<\/ul>)<\/p>/g, '$1');
    html = html.replace(/<p>(<pre>)/g, '$1');
    html = html.replace(/(<\/pre>)<\/p>/g, '$1');
    html = html.replace(/<p>(<blockquote>)/g, '$1');
    html = html.replace(/(<\/blockquote>)<\/p>/g, '$1');
    html = html.replace(/<p>(<hr>)<\/p>/g, '$1');

    return html;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// -- Login --

let currentUser = { email: 'thibaud.ishacian@presight.ai', name: 'Thibaud Ishacian', role: 'Admin' };

function selectAccount(btn) {
    document.querySelectorAll('.account-btn').forEach(b => {
        b.classList.remove('border-brand-500', 'bg-brand-50');
        b.classList.add('border-transparent');
    });
    btn.classList.remove('border-transparent');
    btn.classList.add('border-brand-500', 'bg-brand-50');
    currentUser = { email: btn.dataset.email, name: btn.dataset.name, role: btn.dataset.role };
}

function handleLogin() {
    const pwd = document.getElementById('login-password');
    const err = document.getElementById('login-error');
    if (!pwd || pwd.value !== 'Presight2026!') {
        if (err) { err.classList.remove('hidden'); }
        if (pwd) { pwd.classList.add('border-red-300'); pwd.focus(); }
        return;
    }
    if (err) err.classList.add('hidden');

    const btn = document.getElementById('login-btn');
    btn.innerHTML = '<span class="inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></span> Signing in…';
    btn.disabled = true;

    setTimeout(() => {
        const screen = document.getElementById('login-screen');
        screen.style.opacity = '0';
        screen.style.transition = 'opacity 0.4s ease';

        document.getElementById('app-sidebar').style.opacity = '1';
        document.getElementById('app-main').style.opacity = '1';

        const userEl = document.getElementById('user-badge');
        if (userEl) {
            const initials = currentUser.name.split(' ').map(n => n[0]).join('');
            userEl.innerHTML = `<div class="w-7 h-7 rounded-full flex items-center justify-center text-white text-[10px] font-bold" style="background:var(--accent);">${initials}</div>
                <span class="text-xs font-medium truncate" style="color:var(--text-secondary);">${escapeHtml(currentUser.name)}</span>
                <span class="material-icons-outlined text-sm" style="color:var(--text-muted);">expand_more</span>`;
        }

        goToPage('hub');
        setTimeout(() => screen.remove(), 500);
    }, 800);
}

// Allow Enter key on login form
document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && document.getElementById('login-screen')) {
        e.preventDefault();
        handleLogin();
    }
});

// Initialize - wait for login, don't render content yet
