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
let activeSystemId = null;
let activeSystemTab = 'overview';

// ── System Data Model ──

const PREBUILT_SYSTEMS = [
    { id:'sys_procurement', name:'Procurement Risk Analysis', objective:'Validate vendor compliance and assess procurement risks',
      status:'live', icon:'verified_user', color:'#00bcd4',
      agents:[{id:'procurement',name:'Procurement Agent',model:'gpt-4o',type:'Procurement',
        prompt:'You are a procurement compliance agent. Validate vendor documents, check regulatory compliance, and flag risks.'}],
      knowledge:{docs:12,chunks:1240,lastSync:'2 min ago'}, skills:['sap_api','email','doc_parser'],
      flow:null, runs:{total:1240,lastRun:'2 min ago',successRate:97},
      impact:{roi:'+320%',costPerRun:'$0.18',timeSaved:'42%'},
      lastAction:'Retrieved 3 docs → Generated risk score', lastActionTime:Date.now()-120000 },
    { id:'sys_legal', name:'Contract Intelligence', objective:'Analyze contracts for risks, obligations, and compliance issues',
      status:'live', icon:'gavel', color:'#8b5cf6',
      agents:[{id:'legal',name:'Legal Review',model:'gpt-4o',type:'Legal',
        prompt:'You are a contract analysis agent. Extract clauses, identify risks, and assess regulatory compliance.'}],
      knowledge:{docs:8,chunks:890,lastSync:'15 min ago'}, skills:['doc_parser','compliance_check'],
      flow:null, runs:{total:856,lastRun:'15 min ago',successRate:94},
      impact:{roi:'+280%',costPerRun:'$0.22',timeSaved:'38%'},
      lastAction:'Analyzed contract → Flagged 2 risk clauses', lastActionTime:Date.now()-900000 },
    { id:'sys_hr', name:'HR Knowledge Assistant', objective:'Answer HR policy questions, support onboarding, manage leave requests',
      status:'idle', icon:'people', color:'#f59e0b',
      agents:[{id:'hr',name:'HR Assistant',model:'gpt-4o-mini',type:'HR',
        prompt:'You are an HR assistant. Answer policy questions, help with onboarding, and manage leave queries.'}],
      knowledge:{docs:5,chunks:420,lastSync:'1 hour ago'}, skills:['email','calendar'],
      flow:null, runs:{total:340,lastRun:'1 hour ago',successRate:99},
      impact:{roi:'+150%',costPerRun:'$0.04',timeSaved:'25%'},
      lastAction:'Answered policy query → Leave balance retrieved', lastActionTime:Date.now()-3600000 },
    { id:'sys_finance', name:'Financial Analysis Engine', objective:'Analyze statements, track budgets, forecast expenses, validate invoices',
      status:'live', icon:'account_balance', color:'#10b981',
      agents:[{id:'finance',name:'Financial Analyst',model:'gpt-4o',type:'Finance',
        prompt:'You are a financial analyst agent. Analyze statements, track budgets, create forecasts, and validate expenses.'}],
      knowledge:{docs:15,chunks:1800,lastSync:'5 min ago'}, skills:['sap_api','excel_parser','bi_connector'],
      flow:null, runs:{total:2100,lastRun:'5 min ago',successRate:96},
      impact:{roi:'+410%',costPerRun:'$0.15',timeSaved:'55%'},
      lastAction:'Parsed Q1 report → Budget variance flagged', lastActionTime:Date.now()-300000 },
];

function _initSystems() {
    if (localStorage.getItem('aip_systems')) return;
    const legacy = JSON.parse(localStorage.getItem('aip_agents') || '[]');
    const migrated = legacy.map(a => ({
        id: 'sys_' + (a.id || Date.now()), name: a.name || 'Untitled System',
        objective: '', status: 'draft', icon: 'smart_toy', color: 'var(--accent)',
        agents: [{ id: a.id, name: a.name, model: a.model || 'gpt-4o', type: a.type || 'Custom', prompt: a.systemPrompt || '' }],
        knowledge: { docs: 0, chunks: 0, lastSync: '—' }, skills: [],
        flow: null, runs: { total: 0, lastRun: '—', successRate: 0 },
        impact: { roi: '—', costPerRun: '—', timeSaved: '—' },
        lastAction: '', lastActionTime: 0,
    }));
    const all = [...PREBUILT_SYSTEMS, ...migrated];
    localStorage.setItem('aip_systems', JSON.stringify(all));
}

function listSystems() {
    _initSystems();
    return JSON.parse(localStorage.getItem('aip_systems') || '[]');
}
function getSystem(id) { return listSystems().find(s => s.id === id) || null; }
function updateSystem(id, patch) {
    const sys = listSystems();
    const idx = sys.findIndex(s => s.id === id);
    if (idx < 0) return;
    sys[idx] = { ...sys[idx], ...patch };
    localStorage.setItem('aip_systems', JSON.stringify(sys));
}
function createSystem(obj) {
    const sys = listSystems();
    sys.push(obj);
    localStorage.setItem('aip_systems', JSON.stringify(sys));
    return obj;
}

const stepTitles = {
    1: 'Reasoning',
    2: 'Model Config',
    3: 'Knowledge',
    4: 'Skills',
    5: 'Controls',
    6: 'Execution',
    7: 'Save System',
};
const headerSubtitles = {
    1: 'Define Reasoning Engine',
    2: 'Connect to a Model',
    3: 'Upload Knowledge Documents',
    4: 'Configure Skills',
    5: 'Review Controls & Guardrails',
    6: 'Run the System',
    7: 'Review & Save Configuration',
};

function toggleTheme() {
    const html = document.documentElement;
    const isDark = html.getAttribute('data-theme') === 'dark';
    html.setAttribute('data-theme', isDark ? 'light' : 'dark');
    localStorage.setItem('aip_theme', isDark ? 'light' : 'dark');
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
    const saved = localStorage.getItem('aip_theme');
    if (saved) document.documentElement.setAttribute('data-theme', saved);
    const icon = document.getElementById('theme-icon');
    if (icon) icon.textContent = (saved || 'dark') === 'dark' ? 'light_mode' : 'dark_mode';
})();

async function loadStepModules() {
    const mod = await import('./steps.js?v=30');
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
    if (title) title.textContent = `Step ${step}`;
    if (sub) sub.textContent = step === 6 ? getAgentName() : headerSubtitles[step];
    if (btn) {
        if (step === 7) {
            btn.innerHTML = '<span class="material-icons-outlined text-base">save</span> Save System';
            btn.onclick = saveCurrentAgent;
            btn.style.display = '';
        } else {
            btn.innerHTML = 'Next Step <span class="material-icons-outlined text-lg">arrow_forward</span>';
            btn.onclick = nextStep;
            btn.style.display = '';
        }
    }
}

function updateValueLoopPhase(phase) {
    document.querySelectorAll('.vl-phase').forEach(el => {
        if (el.dataset.phase === phase) {
            el.style.color = 'var(--accent)';
            el.style.fontWeight = '600';
            el.style.borderBottom = '2px solid var(--accent)';
        } else {
            el.style.color = 'var(--text-muted)';
            el.style.fontWeight = '400';
            el.style.borderBottom = '2px solid transparent';
        }
    });
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
    updateValueLoopPhase(step === 6 ? 'execute' : 'build');

    const content = document.getElementById('step-content');
    if (content) content.scrollTop = 0;
    window.scrollTo(0, 0);
}

function nextStep() {
    if (currentStep >= TOTAL_STEPS) goToStep(1);
    else goToStep(currentStep + 1);
}

// -- Sidebar Page Navigation --

let currentPage = 'systems';

const pageConfig = {
    systems:       { title: 'Systems',              breadcrumb: 'Systems' },
    systemView:    { title: 'System',               breadcrumb: 'System' },
    runs:          { title: 'Runs',                 breadcrumb: 'Runs' },
    intelligence:  { title: 'Intelligence',         breadcrumb: 'Intelligence' },
    governance:    { title: 'Governance',            breadcrumb: 'Governance' },
    resources:     { title: 'Resources',            breadcrumb: 'Resources' },
    // Legacy aliases for backwards compat
    hub:           { title: 'Systems',              breadcrumb: 'Systems' },
    agents:        { title: 'Systems',              breadcrumb: 'Systems' },
    integrations:  { title: 'Resources',            breadcrumb: 'Resources' },
    orchestration: { title: 'System Design',        breadcrumb: 'Flow Editor' },
    workspace:     { title: 'Runs',                 breadcrumb: 'Runs' },
    knowledge:     { title: 'Resources',            breadcrumb: 'Knowledge' },
    access:        { title: 'Governance',           breadcrumb: 'Access' },
    audit:         { title: 'Governance',           breadcrumb: 'Audit' },
    quality:       { title: 'Intelligence',         breadcrumb: 'Quality' },
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

async function goToPage(page, opts) {
    // Legacy redirects
    const redirects = { hub:'systems', agents:'systems', knowledge:'resources', workspace:'runs', quality:'intelligence', access:'governance', audit:'governance', integrations:'resources' };
    if (redirects[page]) page = redirects[page];

    currentPage = page;
    updateSidebarActive(page);

    const mod = await loadStepModules();
    const content = document.getElementById('step-content');
    const cfg = pageConfig[page] || { title: page, breadcrumb: page };
    const title = document.getElementById('header-title');
    const sub = document.getElementById('step-title');
    const btn = document.getElementById('next-btn');

    if (title) title.textContent = cfg.breadcrumb;
    if (sub) sub.textContent = cfg.title;
    if (btn) btn.style.display = 'none';

    content.className = 'min-h-0 flex-1 overflow-y-auto p-5 page-enter relative z-[1]';

    if (page === 'systems') {
        content.innerHTML = mod.page_systems();
        loadSystems();
    } else if (page === 'systemView') {
        const sysId = (opts && opts.systemId) || activeSystemId;
        if (!sysId) { goToPage('systems'); return; }
        activeSystemId = sysId;
        const sys = getSystem(sysId);
        if (!sys) { goToPage('systems'); return; }
        if (title) title.textContent = 'System';
        if (sub) sub.textContent = sys.name;
        content.innerHTML = mod.page_systemView(sys, activeSystemTab);
        _initSystemViewTab(activeSystemTab, sys);
    } else if (page === 'runs') {
        content.innerHTML = mod.page_globalRuns();
        loadGlobalRuns();
    } else if (page === 'intelligence') {
        content.innerHTML = mod.page_unifiedIntelligence();
        loadUnifiedIntelligence('quality');
    } else if (page === 'governance') {
        content.innerHTML = mod.page_governance();
        loadGovernanceSub('access');
    } else if (page === 'resources') {
        content.innerHTML = mod.page_resources();
        loadResourcesSub('integrations');
    } else if (page === 'orchestration') {
        content.innerHTML = mod.page_orchestration();
        initWorkflowEditor();
    }

    document.querySelectorAll('.step-btn').forEach(btn => {
        const ind = btn.querySelector('.step-indicator');
        ind.classList.remove('step-active');
        if (!ind.classList.contains('step-completed')) ind.classList.add('step-pending');
    });

    if (content) content.scrollTop = 0;
    window.scrollTo(0, 0);
}

function openSystem(sysId) {
    activeSystemId = sysId;
    activeSystemTab = 'overview';
    goToPage('systemView', { systemId: sysId });
}

function switchSystemTab(tab) {
    activeSystemTab = tab;
    const sys = getSystem(activeSystemId);
    if (!sys) return;
    document.querySelectorAll('.sys-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
    const tabContent = document.getElementById('system-tab-content');
    if (!tabContent) return;
    _renderSystemTabContent(tabContent, tab, sys);
    _initSystemViewTab(tab, sys);
}

async function _renderSystemTabContent(container, tab, sys) {
    const mod = await loadStepModules();
    if (tab === 'overview') container.innerHTML = mod.systemTab_overview(sys);
    else if (tab === 'design') container.innerHTML = mod.systemTab_design(sys);
    else if (tab === 'runs') container.innerHTML = mod.systemTab_runs(sys);
    else if (tab === 'intelligence') container.innerHTML = mod.systemTab_intelligence(sys);
    else if (tab === 'settings') container.innerHTML = mod.systemTab_settings(sys);
}

async function _initSystemViewTab(tab, sys) {
    if (tab === 'overview') _loadSystemOverview(sys);
    else if (tab === 'design') setTimeout(() => initDesignCanvas(sys), 100);
    else if (tab === 'runs') loadSystemRuns(sys);
    else if (tab === 'intelligence') loadSystemIntelligence(sys);
}

// ══════════════════════════════════════════════════════════════════════════════
// SYSTEMS LIST
// ══════════════════════════════════════════════════════════════════════════════

function loadSystems() {
    const systems = listSystems();
    const grid = document.getElementById('systems-grid');
    const countEl = document.getElementById('systems-count');
    if (countEl) countEl.textContent = systems.length;
    if (!grid) return;
    if (!systems.length) {
        grid.innerHTML = '<div class="col-span-2 text-center py-12"><span class="material-icons-outlined text-4xl mb-2" style="color:var(--text-muted);">hub</span><p class="text-[12px] font-medium" style="color:var(--text-secondary);">No systems yet</p><p class="text-[11px]" style="color:var(--text-muted);">Use the Quick Start above or click New System.</p></div>';
        return;
    }
    grid.innerHTML = systems.map(s => _systemCard(s)).join('');
}

function _systemCard(s) {
    const statusColors = { live:'var(--success)', idle:'var(--warning)', error:'var(--error)', draft:'var(--text-muted)' };
    const statusDot = statusColors[s.status] || statusColors.draft;
    return `
    <div class="t-card p-4 cursor-pointer transition-all" style="border-radius:var(--radius);" onclick="openSystem('${s.id}')" onmouseenter="this.style.borderColor='var(--border-active)'" onmouseleave="this.style.borderColor=''">
        <div class="flex items-start justify-between mb-2">
            <div class="flex items-center gap-2.5">
                <div class="w-8 h-8 rounded-lg flex items-center justify-center" style="background:${s.color || 'var(--accent)'};opacity:0.9;">
                    <span class="material-icons-outlined text-white text-base">${s.icon || 'hub'}</span>
                </div>
                <div>
                    <h3 class="text-[13px] font-semibold" style="color:var(--text-primary);">${s.name}</h3>
                    <p class="text-[10px] line-clamp-1" style="color:var(--text-muted);">${s.objective || 'No objective'}</p>
                </div>
            </div>
            <div class="exec-pulse shrink-0">
                <span class="pulse-dot ${s.status || 'draft'}" style="background:${statusDot};"></span>
                <span class="text-[9px] capitalize">${s.status || 'draft'}</span>
            </div>
        </div>
        <div class="grid grid-cols-3 gap-2 mt-3 pt-3" style="border-top:1px solid var(--border-default);">
            <div class="text-center">
                <p class="text-[13px] font-bold" style="color:var(--text-primary);">${s.runs?.total || 0}</p>
                <p class="text-[8px] uppercase tracking-wider" style="color:var(--text-muted);">Runs</p>
            </div>
            <div class="text-center">
                <p class="text-[13px] font-bold" style="color:var(--success);">${s.impact?.roi || '—'}</p>
                <p class="text-[8px] uppercase tracking-wider" style="color:var(--text-muted);">ROI</p>
            </div>
            <div class="text-center">
                <p class="text-[13px] font-bold" style="color:var(--accent);">${s.impact?.timeSaved || '—'}</p>
                <p class="text-[8px] uppercase tracking-wider" style="color:var(--text-muted);">Time Saved</p>
            </div>
        </div>
        ${s.lastAction ? `<div class="exec-pulse mt-2 pt-2" style="border-top:1px solid var(--border-default);"><span class="pulse-dot ${s.status}" style="background:${statusDot};width:4px;height:4px;"></span><span class="text-[9px] truncate" style="max-width:250px;">${s.lastAction}</span></div>` : ''}
    </div>`;
}

function filterSystems(query) {
    const systems = listSystems();
    const grid = document.getElementById('systems-grid');
    if (!grid) return;
    const q = (query || '').toLowerCase();
    const filtered = q ? systems.filter(s => s.name.toLowerCase().includes(q) || (s.objective||'').toLowerCase().includes(q)) : systems;
    grid.innerHTML = filtered.map(s => _systemCard(s)).join('');
}

function createNewSystem() {
    const id = 'sys_' + Date.now();
    const sys = { id, name:'New System', objective:'', status:'draft', icon:'smart_toy', color:'var(--accent)',
        agents:[], knowledge:{docs:0,chunks:0,lastSync:'—'}, skills:[], flow:null,
        runs:{total:0,lastRun:'—',successRate:0}, impact:{roi:'—',costPerRun:'—',timeSaved:'—'},
        lastAction:'', lastActionTime:0 };
    createSystem(sys);
    openSystem(id);
}

function deleteSystemAndReturn(sysId) {
    const sys = listSystems().filter(s => s.id !== sysId);
    localStorage.setItem('aip_systems', JSON.stringify(sys));
    goToPage('systems');
    showToast('System deleted');
}

// ══════════════════════════════════════════════════════════════════════════════
// SYSTEM VIEW HELPERS
// ══════════════════════════════════════════════════════════════════════════════

function _loadSystemOverview(sys) {
    // Overview is static HTML from systemTab_overview, nothing async needed
}

function loadSystemRuns(sys) {
    const container = document.getElementById('system-runs-list');
    if (!container) return;
    const runs = _getSimulatedRuns(sys);
    if (!runs.length) {
        container.innerHTML = '<div class="text-center py-8"><span class="material-icons-outlined text-3xl mb-2" style="color:var(--text-muted);">play_circle</span><p class="text-[12px] font-medium" style="color:var(--text-secondary);">No runs yet</p><p class="text-[11px]" style="color:var(--text-muted);">Click "New Run" to execute this system.</p></div>';
        return;
    }
    container.innerHTML = runs.map((r, i) => `
    <div class="t-card p-3 flex items-center gap-3" style="border-radius:var(--radius);">
        <div class="w-7 h-7 rounded-md flex items-center justify-center" style="background:${r.success ? 'rgba(16,185,129,0.15)' : 'rgba(239,68,68,0.15)'};">
            <span class="material-icons-outlined text-sm" style="color:${r.success ? 'var(--success)' : 'var(--error)'};">${r.success ? 'check_circle' : 'error'}</span>
        </div>
        <div class="flex-1 min-w-0">
            <p class="text-[11px] font-medium truncate" style="color:var(--text-primary);">${r.label}</p>
            <p class="text-[9px]" style="color:var(--text-muted);">${r.time}</p>
        </div>
        <div class="text-right shrink-0">
            <p class="text-[10px] font-medium" style="color:var(--text-secondary);">${r.cost}</p>
            <p class="text-[9px]" style="color:var(--text-muted);">${r.duration}</p>
        </div>
    </div>`).join('');
}

function _getSimulatedRuns(sys) {
    if (!sys.runs?.total) return [];
    const samples = [
        { label:'Query: compliance check', success:true, cost:'$0.12', duration:'2.4s', time:'2 min ago' },
        { label:'Query: vendor validation', success:true, cost:'$0.18', duration:'3.1s', time:'15 min ago' },
        { label:'Batch: document analysis', success:true, cost:'$0.45', duration:'8.2s', time:'1 hour ago' },
        { label:'Query: risk assessment', success:false, cost:'$0.08', duration:'1.2s', time:'2 hours ago' },
        { label:'Query: contract review', success:true, cost:'$0.22', duration:'4.5s', time:'3 hours ago' },
    ];
    return samples.slice(0, Math.min(5, sys.runs.total));
}

function loadSystemIntelligence(sys) {
    // Placeholder: in-system intelligence view
}

function openSystemRun(sysId) {
    activeSystemId = sysId;
    activeSystemTab = 'runs';
    const sys = getSystem(sysId);
    if (!sys) return;
    // Switch to the Execution step (Step 6 = chat) with system context
    const agent = sys.agents?.[0];
    if (agent) {
        savedAgentName = agent.name || sys.name;
        savedModel = agent.model || 'gpt-4o';
        savedSystemPrompt = agent.prompt || '';
    }
    goToStep(6);
}

// ══════════════════════════════════════════════════════════════════════════════
// DESIGN CANVAS (3-layer system)
// ══════════════════════════════════════════════════════════════════════════════

var canvasScale = 1;
var canvasPanX = 0;
var canvasPanY = 0;
var canvasDragging = false;
var canvasDragStart = { x:0, y:0 };
var canvasShowTech = false;

const CANVAS_BLOCKS = [
    { id:'decision', label:'Decision Engine', alias:'LLM + Agents + Prompts', icon:'psychology', color:'#6366f1', x:300, y:30, steps:[1,2], initHooks:['loadRAGSettings'] },
    { id:'knowledge', label:'Knowledge', alias:'RAG + Vector Store + Docs', icon:'library_books', color:'#00bcd4', x:80, y:160, steps:[3], initHooks:['initFileUpload','loadKBStats'] },
    { id:'skills', label:'Skills', alias:'Tools + APIs + Connectors', icon:'build_circle', color:'#f59e0b', x:520, y:160, steps:[4], initHooks:[] },
    { id:'guardrails', label:'Controls', alias:'Governance + Filters + RBAC', icon:'shield', color:'#ef4444', x:80, y:300, steps:[5], initHooks:[] },
    { id:'output', label:'Execution', alias:'Chat + Streaming + TTS', icon:'terminal', color:'#10b981', x:520, y:300, steps:[6], initHooks:['initChat'] },
    { id:'flow', label:'Flow', alias:'Drawflow Pipeline Editor', icon:'account_tree', color:'#8b5cf6', x:300, y:300, steps:['flow'], initHooks:['initWorkflowEditor'] },
];

const CANVAS_CONNECTIONS = [
    ['knowledge','decision'], ['decision','skills'], ['decision','flow'],
    ['guardrails','decision'], ['guardrails','output'], ['flow','output'], ['skills','output']
];

function initDesignCanvas(sys) {
    const world = document.getElementById('canvas-world');
    const svg = document.getElementById('canvas-svg');
    const container = document.getElementById('design-canvas');
    if (!world || !svg || !container) return;

    canvasScale = 1; canvasPanX = 40; canvasPanY = 20;
    world.innerHTML = '';

    CANVAS_BLOCKS.forEach(b => {
        const div = document.createElement('div');
        div.className = 'canvas-block';
        div.id = 'cb-' + b.id;
        div.style.left = b.x + 'px';
        div.style.top = b.y + 'px';
        div.innerHTML = `
            <div class="cb-icon" style="background:${b.color}20;"><span class="material-icons-outlined" style="color:${b.color};">${b.icon}</span></div>
            <div class="cb-label">${b.label}</div>
            <div class="cb-alias">${b.alias}</div>
            <div class="cb-status"><span style="width:5px;height:5px;border-radius:50%;background:var(--success);"></span> Active</div>`;
        div.ondblclick = (e) => { e.stopPropagation(); openDesignBlock(b, sys); };
        div.onclick = (e) => { e.stopPropagation(); _selectCanvasBlock(b.id); };
        world.appendChild(div);
    });

    _drawCanvasConnections(svg);
    _applyCanvasTransform();

    container.onwheel = (e) => { e.preventDefault(); canvasZoom(e.deltaY > 0 ? -0.08 : 0.08); };
    container.onmousedown = (e) => { if (e.target === container || e.target === world || e.target === svg) { canvasDragging = true; canvasDragStart = { x:e.clientX - canvasPanX, y:e.clientY - canvasPanY }; } };
    container.onmousemove = (e) => { if (canvasDragging) { canvasPanX = e.clientX - canvasDragStart.x; canvasPanY = e.clientY - canvasDragStart.y; _applyCanvasTransform(); } };
    container.onmouseup = () => canvasDragging = false;
    container.onmouseleave = () => canvasDragging = false;
}

function _drawCanvasConnections(svg) {
    svg.innerHTML = '';
    CANVAS_CONNECTIONS.forEach(([fromId, toId]) => {
        const from = document.getElementById('cb-' + fromId);
        const to = document.getElementById('cb-' + toId);
        if (!from || !to) return;
        const fx = parseFloat(from.style.left) + 90;
        const fy = parseFloat(from.style.top) + 60;
        const tx = parseFloat(to.style.left) + 90;
        const ty = parseFloat(to.style.top) + 10;
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        const my = (fy + ty) / 2;
        path.setAttribute('d', `M${fx},${fy} C${fx},${my} ${tx},${my} ${tx},${ty}`);
        path.setAttribute('class', 'canvas-connection');
        svg.appendChild(path);
    });
}

function _applyCanvasTransform() {
    const world = document.getElementById('canvas-world');
    const svg = document.getElementById('canvas-svg');
    const t = `translate(${canvasPanX}px, ${canvasPanY}px) scale(${canvasScale})`;
    if (world) world.style.transform = t;
    if (svg) svg.style.transform = t;
    const zl = document.getElementById('canvas-zoom-level');
    if (zl) zl.textContent = Math.round(canvasScale * 100);
}

function canvasZoom(delta) {
    canvasScale = Math.max(0.4, Math.min(2.5, canvasScale + delta));
    _applyCanvasTransform();
}

function canvasResetView() {
    canvasScale = 1; canvasPanX = 40; canvasPanY = 20;
    _applyCanvasTransform();
}

function canvasToggleTech(show) {
    canvasShowTech = show;
    document.querySelectorAll('.cb-alias').forEach(el => el.style.display = show ? 'block' : '');
}

function _selectCanvasBlock(blockId) {
    const wasActive = document.getElementById('cb-' + blockId)?.classList.contains('active');
    document.querySelectorAll('.canvas-block').forEach(b => b.classList.remove('active'));
    const container = document.getElementById('design-canvas');
    if (wasActive) {
        if (container) container.classList.remove('focus-mode');
    } else {
        const el = document.getElementById('cb-' + blockId);
        if (el) el.classList.add('active');
        if (container) container.classList.add('focus-mode');
    }
}

async function openDesignBlock(block, sys) {
    const panel = document.getElementById('design-panel');
    const backdrop = document.getElementById('design-backdrop');
    const titleEl = document.getElementById('design-panel-title');
    const body = document.getElementById('design-panel-body');
    const nav = document.getElementById('design-panel-nav');
    if (!panel || !body) return;

    if (titleEl) titleEl.textContent = block.label;

    if (block.steps[0] === 'flow') {
        // Flow => inject Drawflow orchestration page
        const mod = await loadStepModules();
        body.innerHTML = mod.page_orchestration();
        setTimeout(() => initWorkflowEditor(), 200);
        if (nav) nav.innerHTML = '';
    } else {
        // Builder steps => inject the existing step forms
        const mod = await loadStepModules();
        const stepFns = {
            1: () => mod.step1_agentCreation(),
            2: () => mod.step2_modelSelection(),
            3: () => mod.step3_knowledgeUpload(),
            4: () => mod.step4_rulesTools(),
            5: () => mod.step5_governance(),
            6: () => mod.step6_execution(),
            7: () => mod.step7_save(),
        };
        const steps = block.steps;
        let html = '';
        steps.forEach(s => { if (stepFns[s]) html += stepFns[s](); });
        body.innerHTML = html;

        // Nav arrows for multi-step blocks
        if (nav) {
            const allSteps = CANVAS_BLOCKS.reduce((a,b) => a.concat(b.steps.filter(s => s !== 'flow')), []);
            nav.innerHTML = allSteps.map(s => `<button onclick="designPanelGoStep(${s})" class="px-1.5 py-0.5 text-[9px] font-medium" style="background:${steps.includes(s)?'var(--accent)':'var(--bg-elevated)'};color:${steps.includes(s)?'white':'var(--text-muted)'};border-radius:var(--radius-xs);">Step ${s}</button>`).join('');
        }

        // Run init hooks after DOM paint
        requestAnimationFrame(() => {
            block.initHooks.forEach(hook => {
                if (typeof window[hook] === 'function') window[hook]();
                else if (hook === 'loadRAGSettings' && typeof loadRAGSettings === 'function') loadRAGSettings();
                else if (hook === 'initFileUpload' && typeof initFileUpload === 'function') initFileUpload();
                else if (hook === 'loadKBStats' && typeof loadKBStats === 'function') loadKBStats();
                else if (hook === 'initChat' && typeof initChat === 'function') initChat();
            });
            _restoreDesignPanelValues(sys);
        });
    }

    backdrop.classList.add('open');
    panel.classList.add('open');
}

async function designPanelGoStep(stepNum) {
    const body = document.getElementById('design-panel-body');
    if (!body) return;
    const mod = await loadStepModules();
    const stepFns = {
        1: () => mod.step1_agentCreation(),
        2: () => mod.step2_modelSelection(),
        3: () => mod.step3_knowledgeUpload(),
        4: () => mod.step4_rulesTools(),
        5: () => mod.step5_governance(),
        6: () => mod.step6_execution(),
        7: () => mod.step7_save(),
    };
    if (stepFns[stepNum]) {
        body.innerHTML = stepFns[stepNum]();
        const block = CANVAS_BLOCKS.find(b => b.steps.includes(stepNum));
        if (block) {
            requestAnimationFrame(() => {
                block.initHooks.forEach(hook => {
                    if (typeof window[hook] === 'function') window[hook]();
                });
            });
        }
    }
}

function _restoreDesignPanelValues(sys) {
    const agent = sys.agents?.[0];
    if (!agent) return;
    const nameEl = document.getElementById('agent-name');
    if (nameEl) nameEl.value = agent.name || '';
    const promptEl = document.querySelector('.code-editor');
    if (promptEl) promptEl.value = agent.prompt || '';
}

function closeDesignPanel() {
    const panel = document.getElementById('design-panel');
    const backdrop = document.getElementById('design-backdrop');
    if (panel) panel.classList.remove('open');
    if (backdrop) backdrop.classList.remove('open');
}

// ══════════════════════════════════════════════════════════════════════════════
// GLOBAL RUNS
// ══════════════════════════════════════════════════════════════════════════════

function loadGlobalRuns() {
    const systems = listSystems();
    let totalRuns = 0, totalSuccess = 0;
    systems.forEach(s => {
        totalRuns += s.runs?.total || 0;
        totalSuccess += (s.runs?.total || 0) * ((s.runs?.successRate || 0) / 100);
    });
    const el = (id, v) => { const e = document.getElementById(id); if(e) e.textContent = v; };
    el('runs-total', totalRuns);
    el('runs-today', Math.floor(totalRuns * 0.05));
    el('runs-success', totalRuns ? Math.round(totalSuccess/totalRuns) + '%' : '0%');
    el('runs-cost', '$' + (totalRuns * 0.15).toFixed(0));

    const list = document.getElementById('global-runs-list');
    if (!list) return;
    const allRuns = [];
    systems.forEach(s => {
        _getSimulatedRuns(s).forEach(r => allRuns.push({ ...r, systemName: s.name, systemColor: s.color, systemIcon: s.icon }));
    });
    if (!allRuns.length) return;
    list.innerHTML = allRuns.map(r => `
    <div class="t-card p-3 flex items-center gap-3" style="border-radius:var(--radius);">
        <div class="w-7 h-7 rounded-md flex items-center justify-center" style="background:${r.success ? 'rgba(16,185,129,0.15)' : 'rgba(239,68,68,0.15)'};">
            <span class="material-icons-outlined text-sm" style="color:${r.success ? 'var(--success)' : 'var(--error)'};">${r.success ? 'check_circle' : 'error'}</span>
        </div>
        <div class="flex-1 min-w-0">
            <p class="text-[11px] font-medium truncate" style="color:var(--text-primary);">${r.label}</p>
            <p class="text-[9px]" style="color:var(--text-muted);">${r.systemName} · ${r.time}</p>
        </div>
        <div class="text-right shrink-0">
            <p class="text-[10px] font-medium" style="color:var(--text-secondary);">${r.cost}</p>
            <p class="text-[9px]" style="color:var(--text-muted);">${r.duration}</p>
        </div>
    </div>`).join('');
}

// ══════════════════════════════════════════════════════════════════════════════
// UNIFIED INTELLIGENCE (sub-tabs)
// ══════════════════════════════════════════════════════════════════════════════

async function loadUnifiedIntelligence(sub) {
    document.querySelectorAll('[data-subtab]').forEach(t => t.classList.toggle('active', t.dataset.subtab === sub));
    const container = document.getElementById('intel-sub-content');
    if (!container) return;

    if (sub === 'quality') {
        const mod = await loadStepModules();
        container.innerHTML = mod.page_agentQuality();
        loadQualityPage();
    } else if (sub === 'feeds') {
        const mod = await loadStepModules();
        container.innerHTML = mod.page_intelligence();
        loadIntelligenceDashboard();
    } else if (sub === 'performance') {
        container.innerHTML = `
        <div class="t-card p-6 text-center" style="border-radius:var(--radius);">
            <span class="material-icons-outlined text-3xl mb-2" style="color:var(--text-muted);">analytics</span>
            <p class="text-[12px] font-medium" style="color:var(--text-secondary);">Performance Metrics</p>
            <p class="text-[11px]" style="color:var(--text-muted);">Latency, throughput, drift detection, and cost optimization analytics coming soon.</p>
        </div>`;
    }
}

// ══════════════════════════════════════════════════════════════════════════════
// GOVERNANCE (sub-tabs)
// ══════════════════════════════════════════════════════════════════════════════

async function loadGovernanceSub(sub) {
    document.querySelectorAll('[data-subtab]').forEach(t => t.classList.toggle('active', t.dataset.subtab === sub));
    const container = document.getElementById('gov-sub-content');
    if (!container) return;
    const mod = await loadStepModules();

    if (sub === 'access') {
        container.innerHTML = mod.page_accessRoles();
    } else if (sub === 'audit') {
        container.innerHTML = mod.page_auditLogs();
        loadAuditPage();
    }
}

// ══════════════════════════════════════════════════════════════════════════════
// RESOURCES (sub-tabs)
// ══════════════════════════════════════════════════════════════════════════════

async function loadResourcesSub(sub) {
    document.querySelectorAll('[data-subtab]').forEach(t => t.classList.toggle('active', t.dataset.subtab === sub));
    const container = document.getElementById('res-sub-content');
    if (!container) return;
    const mod = await loadStepModules();

    if (sub === 'integrations') {
        container.innerHTML = mod.page_integrations();
    } else if (sub === 'knowledge') {
        container.innerHTML = mod.step3_knowledgeUpload();
        requestAnimationFrame(() => {
            if (typeof initFileUpload === 'function') initFileUpload();
            loadKBStats();
        });
    } else if (sub === 'models') {
        container.innerHTML = `
        <div class="max-w-3xl mx-auto space-y-3">
            <div class="t-card p-4" style="border-radius:var(--radius);">
                <div class="flex items-center gap-2 mb-3">
                    <span class="material-icons-outlined text-sm" style="color:var(--accent);">model_training</span>
                    <h3 class="text-[12px] font-semibold" style="color:var(--text-primary);">Model Configuration</h3>
                </div>
                <div class="grid grid-cols-1 gap-2">
                    ${[{name:'GPT-4o',provider:'OpenAI',status:'Active',cost:'$0.005/1K tokens'},{name:'GPT-4o-mini',provider:'OpenAI',status:'Active',cost:'$0.0002/1K tokens'},{name:'GPT-5',provider:'OpenAI',status:'Active',cost:'$0.01/1K tokens'},{name:'Claude 3.5 Sonnet',provider:'Anthropic',status:'Available',cost:'$0.003/1K tokens'}].map(m => `
                    <div class="flex items-center justify-between p-2.5" style="background:var(--bg-elevated);border-radius:var(--radius-sm);">
                        <div class="flex items-center gap-2">
                            <span class="material-icons-outlined text-sm" style="color:var(--accent);">smart_toy</span>
                            <div>
                                <p class="text-[11px] font-medium" style="color:var(--text-primary);">${m.name}</p>
                                <p class="text-[9px]" style="color:var(--text-muted);">${m.provider} · ${m.cost}</p>
                            </div>
                        </div>
                        <span class="text-[9px] px-1.5 py-0.5 font-medium" style="background:${m.status==='Active'?'rgba(16,185,129,0.15)':'var(--bg-elevated)'};color:${m.status==='Active'?'var(--success)':'var(--text-muted)'};border-radius:var(--radius-xs);">${m.status}</span>
                    </div>`).join('')}
                </div>
            </div>
        </div>`;
    }
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
        return `<div onclick="openDocPreview('${doc.document_id}', '${escapeHtml(fname)}')" class="flex items-center justify-between p-2.5 rounded-lg cursor-pointer transition-all group" style="background:var(--bg-elevated);border:1px solid var(--border-default);">
            <div class="flex items-center gap-2.5 min-w-0">
                <span class="material-icons-outlined ${iconColor} text-lg">${icon}</span>
                <div class="min-w-0">
                    <p class="text-sm font-medium truncate" style="color:var(--text-primary);">${escapeHtml(displayName)}</p>
                    <p class="text-[11px]" style="color:var(--text-muted);">${isPdf ? 'PDF' : escapeHtml(doc.document_type || 'document')}</p>
                </div>
            </div>
            <div class="flex items-center gap-2 shrink-0">
                <span class="px-2 py-0.5 text-[10px] font-medium rounded-full" style="background:rgba(16,185,129,0.15);color:#34d399;">Indexed</span>
                <span class="material-icons-outlined text-sm" style="color:var(--text-muted);">visibility</span>
                <button onclick="event.stopPropagation(); deleteIndexedDoc('${doc.document_id}', this)" class="w-6 h-6 flex items-center justify-center rounded transition-colors opacity-0 group-hover:opacity-100">
                    <span class="material-icons-outlined text-red-500 text-sm">delete</span>
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
    _clearSession();
    location.reload();
}

function showToast(msg) {
    const existing = document.getElementById('toast-msg');
    if (existing) existing.remove();
    const toast = document.createElement('div');
    toast.id = 'toast-msg';
    toast.className = 'fixed bottom-4 right-4 z-[9999] px-3 py-2 text-[11px] flex items-center gap-2 animate-slideUp';
    toast.style.cssText = 'background:var(--bg-card);color:var(--text-primary);border:1px solid var(--border-default);box-shadow:0 4px 16px rgba(0,0,0,0.2);border-radius:var(--radius-sm);';
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
        const rpm = document.getElementById('rag-pipeline-mode');
        if (rpm) {
            const v = localStorage.getItem('aip_rag_pipeline_mode') || 'auto';
            if ([...rpm.options].some((o) => o.value === v)) rpm.value = v;
        }
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
    const agents = JSON.parse(localStorage.getItem('aip_agents') || '[]');
    agents.unshift(agent);
    localStorage.setItem('aip_agents', JSON.stringify(agents));

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
    const agents = JSON.parse(localStorage.getItem('aip_agents') || '[]');
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
        <div class="flex items-center justify-between p-2.5 transition-colors group" style="background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:var(--radius);">
            <div class="flex items-center gap-2.5 min-w-0">
                <div class="w-7 h-7 flex items-center justify-center shrink-0" style="background:var(--accent-subtle);border-radius:var(--radius-sm);">
                    <span class="material-icons-outlined text-base" style="color:var(--accent);">smart_toy</span>
                </div>
                <div class="min-w-0">
                    <p class="text-[12px] font-semibold truncate" style="color:var(--text-primary);">${escapeHtml(agent.name)}</p>
                    <div class="flex items-center gap-1.5 mt-0.5 flex-wrap">
                        <span class="px-1.5 py-0.5 text-[8px] font-medium" style="background:var(--bg-card);border:1px solid var(--border-default);color:var(--text-secondary);border-radius:var(--radius-xs);">${escapeHtml(agent.type)}</span>
                        <span class="px-1.5 py-0.5 text-[8px] font-medium" style="background:var(--accent-subtle);color:var(--accent);border-radius:var(--radius-xs);">${escapeHtml(agent.model)}</span>
                        <span class="text-[9px] font-mono" style="color:var(--text-muted);">${date}</span>
                    </div>
                </div>
            </div>
            <div class="flex items-center gap-1.5 shrink-0">
                <button onclick="chatWithAgent('${agent.id}')" class="px-2 py-1 text-[10px] font-medium text-white transition-colors flex items-center gap-1" style="background:var(--accent);border-radius:var(--radius-sm);">
                    <span class="material-icons-outlined text-xs">chat</span>Chat
                </button>
                <button onclick="deleteAgent('${agent.id}')" class="w-6 h-6 flex items-center justify-center transition-colors opacity-0 group-hover:opacity-100" style="border-radius:var(--radius-xs);">
                    <span class="material-icons-outlined text-sm" style="color:var(--text-muted);">delete</span>
                </button>
            </div>
        </div>`;
    }).join('');
}

function chatWithAgent(agentId) {
    const agents = JSON.parse(localStorage.getItem('aip_agents') || '[]');
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
    const agents = JSON.parse(localStorage.getItem('aip_agents') || '[]');
    localStorage.setItem('aip_agents', JSON.stringify(agents.filter(a => a.id !== agentId)));
    loadAgentsPage();
    showToast('Agent deleted');
}

async function loadHubAgents() {
    const grid = document.getElementById('hub-agents-grid');
    if (!grid) return;

    try {
        const api = await import('./api.js');
        const stats = await api.getDocumentStats();
        const kbEl = document.getElementById('hub-kb-count');
        if (kbEl) kbEl.textContent = stats.total_chunks ? `${stats.total_chunks}` : '0';
    } catch (_) { /* non-blocking */ }

    const prebuilt = [
        { id: 'procurement', name: 'Procurement Agent', type: 'Procurement', icon: 'verified_user', color: '#00bcd4', desc: 'Vendor qualification, compliance validation, and document verification against procurement policies.', model: 'gpt-4o' },
        { id: 'legal', name: 'Legal Review', type: 'Legal', icon: 'gavel', color: '#8b5cf6', desc: 'Contract analysis, clause extraction, risk assessment, and regulatory compliance review.', model: 'gpt-4o' },
        { id: 'hr', name: 'HR Assistant', type: 'HR', icon: 'people', color: '#f59e0b', desc: 'Policy Q&A, onboarding support, leave management, and employee handbook queries.', model: 'gpt-4o-mini' },
        { id: 'finance', name: 'Financial Analyst', type: 'Finance', icon: 'account_balance', color: '#10b981', desc: 'Financial statement analysis, budget tracking, forecasting, and expense validation.', model: 'gpt-4o' },
    ];

    const savedAgents = JSON.parse(localStorage.getItem('aip_agents') || '[]');

    let html = '';
    prebuilt.forEach(a => {
        html += `
        <div class="agent-hub-card group" onclick="launchPrebuiltAgent('${a.id}')">
            <div class="flex items-start justify-between mb-2.5">
                <div class="w-8 h-8 flex items-center justify-center" style="background:${a.color}15;border-radius:var(--radius-sm);">
                    <span class="material-icons-outlined text-lg" style="color:${a.color};">${a.icon}</span>
                </div>
                <div class="flex items-center gap-1">
                    <span class="w-1.5 h-1.5 rounded-full" style="background:var(--success);"></span>
                    <span class="text-[9px] font-medium" style="color:var(--success);">Ready</span>
                </div>
            </div>
            <h3 class="text-[13px] font-semibold mb-0.5" style="color:var(--text-primary);">${a.name}</h3>
            <p class="text-[10px] leading-relaxed mb-2.5" style="color:var(--text-muted);">${a.desc}</p>
            <div class="flex items-center gap-1.5">
                <span class="px-1.5 py-0.5 text-[8px] font-medium" style="background:var(--accent-subtle);color:var(--accent);border-radius:var(--radius-xs);">${a.model}</span>
                <span class="px-1.5 py-0.5 text-[8px] font-medium" style="background:var(--bg-elevated);color:var(--text-muted);border-radius:var(--radius-xs);">${a.type}</span>
            </div>
        </div>`;
    });

    savedAgents.forEach(a => {
        html += `
        <div class="agent-hub-card group" onclick="chatWithAgent('${a.id}')">
            <div class="flex items-start justify-between mb-2.5">
                <div class="w-8 h-8 flex items-center justify-center" style="background:var(--accent-subtle);border-radius:var(--radius-sm);">
                    <span class="material-icons-outlined text-lg" style="color:var(--accent);">smart_toy</span>
                </div>
                <span class="text-[9px] font-mono" style="color:var(--text-muted);">Custom</span>
            </div>
            <h3 class="text-[13px] font-semibold mb-0.5" style="color:var(--text-primary);">${escapeHtml(a.name)}</h3>
            <p class="text-[10px] mb-2.5" style="color:var(--text-muted);">Custom agent &middot; ${escapeHtml(a.type)}</p>
            <div class="flex items-center gap-1.5">
                <span class="px-1.5 py-0.5 text-[8px] font-medium" style="background:var(--accent-subtle);color:var(--accent);border-radius:var(--radius-xs);">${escapeHtml(a.model)}</span>
            </div>
        </div>`;
    });

    html += `
    <div class="agent-hub-card agent-hub-create flex flex-col items-center justify-center text-center" onclick="goToStep(1)" style="min-height:160px;">
        <span class="material-icons-outlined text-2xl mb-1.5" style="color:var(--text-muted);">add</span>
        <p class="text-[12px] font-semibold" style="color:var(--text-secondary);">Create Agent</p>
        <p class="text-[10px] mt-0.5" style="color:var(--text-muted);">Build from scratch</p>
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
    const content = document.getElementById('step-content');
    if (content) content.scrollTop = 0;
    window.scrollTo(0, 0);
}

// -- Agent palette items for workflow editor --

function _getAgentPaletteItems() {
    const prebuilt = [
        { type: 'agent_procurement', icon: 'verified_user', name: 'Procurement Agent', meta: 'gpt-4o' },
        { type: 'agent_legal', icon: 'gavel', name: 'Legal Review', meta: 'gpt-4o' },
        { type: 'agent_hr', icon: 'people', name: 'HR Assistant', meta: 'gpt-4o-mini' },
        { type: 'agent_finance', icon: 'account_balance', name: 'Financial Analyst', meta: 'gpt-4o' },
    ];
    try {
        const saved = JSON.parse(localStorage.getItem('aip_agents') || '[]');
        saved.forEach(a => {
            prebuilt.push({ type: 'agent_' + a.id, icon: 'smart_toy', name: a.name || 'Custom Agent', meta: a.model || 'gpt-4o' });
        });
    } catch (_) {}
    return prebuilt;
}

// -- Hub Quick Start: templates + objective-driven launch --

var HUB_TEMPLATES = {
    contracts: { name: 'Contract Analyzer', type: 'Legal', icon: 'gavel', model: 'gpt-4o',
        prompt: 'You are an AI contract analyst. Analyze documents for risks, obligations, key clauses, and compliance issues. Always cite specific sections and provide structured risk assessments.',
        suggestions: ['Analyze this contract for risks', 'Extract key obligations', 'Compare against compliance checklist'] },
    delays: { name: 'Delay Predictor', type: 'Operations', icon: 'trending_up', model: 'gpt-4o',
        prompt: 'You are a project risk analyst. Based on historical data and current indicators, predict potential delays and budget overruns. Quantify confidence levels and recommend mitigations.',
        suggestions: ['Predict budget overrun risk', 'Which projects are most at risk?', 'Compare current vs baseline'] },
    docreview: { name: 'Document Reviewer', type: 'Finance', icon: 'description', model: 'gpt-4o',
        prompt: 'You are a document review specialist. Extract, classify, and summarize key information from uploaded documents. Flag anomalies and missing data.',
        suggestions: ['Summarize this document', 'Extract financial figures', 'Flag compliance issues'] },
    riskscore: { name: 'Risk Scorer', type: 'Operations', icon: 'shield', model: 'gpt-4o',
        prompt: 'You are an enterprise risk scoring agent. Score risks across multiple dimensions (financial, operational, regulatory). Provide structured assessments with confidence levels.',
        suggestions: ['Score overall risk', 'Identify top 3 risk factors', 'Recommend mitigations'] },
};

function launchFromObjective(text) {
    if (!text || !text.trim()) { showToast('Please describe your objective'); return; }
    const obj = text.trim();
    const words = obj.split(/\s+/).slice(0, 4).map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
    savedAgentName = words + ' Agent';
    savedAgentType = 'Custom';
    savedModel = 'gpt-4o';
    savedSystemPrompt = 'You are an intelligent AI agent. Your objective: ' + obj + '. Analyze available data, provide structured insights, cite sources, and recommend actions. Be precise and business-oriented.';
    currentAgentId = 'objective_' + Date.now();
    _showGenerationOverlay(() => goToStep(6));
}

function launchFromTemplate(tplId) {
    const tpl = HUB_TEMPLATES[tplId];
    if (!tpl) return;
    savedAgentName = tpl.name;
    savedAgentType = tpl.type;
    savedModel = tpl.model;
    savedSystemPrompt = tpl.prompt;
    currentAgentId = 'tpl_' + tplId;
    _showGenerationOverlay(() => goToStep(6));
}

function _showGenerationOverlay(onComplete) {
    const overlay = document.createElement('div');
    overlay.id = 'gen-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;background:var(--bg-deepest);opacity:1;transition:opacity 0.4s ease;';
    const steps = [
        { icon: 'smart_toy', text: 'Creating agent...' },
        { icon: 'library_books', text: 'Connecting knowledge base...' },
        { icon: 'account_tree', text: 'Building reasoning pipeline...' },
        { icon: 'check_circle', text: 'System ready' },
    ];
    overlay.innerHTML = `<div class="text-center"><div id="gen-steps" class="space-y-2"></div></div>`;
    document.body.appendChild(overlay);
    const container = overlay.querySelector('#gen-steps');
    let i = 0;
    function showNext() {
        if (i >= steps.length) {
            setTimeout(() => {
                overlay.style.opacity = '0';
                setTimeout(() => { overlay.remove(); onComplete(); }, 400);
            }, 300);
            return;
        }
        const s = steps[i];
        const el = document.createElement('div');
        el.className = 'flex items-center gap-2 animate-slideUp';
        el.innerHTML = `<span class="material-icons-outlined text-sm" style="color:var(--accent);">${s.icon}</span><span class="text-[12px] font-medium" style="color:var(--text-primary);">${s.text}</span>`;
        container.appendChild(el);
        i++;
        setTimeout(showNext, 400);
    }
    showNext();
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
        row.className = 'flex items-center justify-between p-2.5';
        row.style.cssText = 'background:var(--accent-subtle);border:1px solid var(--border-active);border-radius:var(--radius-sm);';
        const isPdf = file.name.toLowerCase().endsWith('.pdf');
        const icon = isPdf ? 'picture_as_pdf' : 'upload_file';
        row.innerHTML = `
            <div class="flex items-center gap-2.5">
                <span class="material-icons-outlined text-base" style="color:${isPdf ? 'var(--error)' : 'var(--accent)'};">${icon}</span>
                <div>
                    <p class="text-[12px] font-medium" style="color:var(--text-primary);">${escapeHtml(file.name)}</p>
                    <p class="text-[10px]" style="color:var(--text-muted);">${(file.size / 1024).toFixed(1)} KB</p>
                </div>
            </div>
            <div class="flex items-center gap-2">
                <span class="upload-status px-1.5 py-0.5 text-[9px] font-medium" style="background:rgba(245,158,11,0.12);color:var(--warning);border-radius:var(--radius-xs);">Uploading...</span>
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
            badge.className = 'upload-status px-1.5 py-0.5 text-[9px] font-medium';
            badge.style.cssText = 'background:rgba(239,68,68,0.12);color:var(--error);border-radius:var(--radius-xs);';
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
    const ragMode =
        document.getElementById('rag-pipeline-mode')?.value ||
        localStorage.getItem('aip_rag_pipeline_mode') ||
        'auto';
    const enabledTools = Object.entries(JSON.parse(localStorage.getItem('aip_tools') || '{}')).filter(([_, v]) => v).map(([k]) => k);
    api.streamChat(
        query,
        {
            model: document.getElementById('model-select')?.value || savedModel || 'gpt-5',
            provider: selectedProvider || 'openai',
            temperature: parseInt(document.getElementById('temp-slider')?.value ?? String(Math.round(savedTemperature * 100))) / 100,
            system_prompt: document.querySelector('.code-editor')?.value || savedSystemPrompt || null,
            rag_pipeline_mode: ragMode,
            enabled_tools: enabledTools,
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
            try {
                const aid = currentAgentId || 'rag';
                localStorage.setItem('aip_last_eval_context', JSON.stringify({
                    agent_id: aid,
                    query,
                    response: accumulatedText,
                }));
            } catch (_) { /* non-blocking */ }

            _appendROISummaryCard(messagesDiv, accumulatedText);
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

    const descLines = (step.description || '').split('\n').filter(l => l.trim());
    const narrativeLine = descLines.length > 0 ? descLines[0] : step.title;
    const detailLines = descLines.slice(1);

    const metricsHtml = (step.metrics && isDone) ? renderMetricsGauges(step.metrics) : '';

    const hasL2 = isDone && (detailLines.length > 0 || metricsHtml);
    const hasL3 = isDone && step.model;
    const uid = step.id;

    let l2Content = '';
    if (hasL2) {
        const detailText = detailLines.map(l => `<p class="text-[10px] leading-snug" style="color:var(--text-muted);">${escapeHtml(l)}</p>`).join('');
        l2Content = `<div id="tool-l2-${uid}" class="reasoning-l2 pl-6 mt-1" style="max-height:0;overflow:hidden;transition:max-height .25s ease;">${metricsHtml}${detailText}</div>`;
    }

    let l3Content = '';
    if (hasL3) {
        const costEst = _estimateStepCost(step);
        const promptPreview = step.prompt ? escapeHtml(step.prompt.substring(0, 200)) + (step.prompt.length > 200 ? '...' : '') : '(not exposed by backend)';
        l3Content = `<div id="tool-l3-${uid}" class="reasoning-l3 pl-6 mt-1" style="max-height:0;overflow:hidden;transition:max-height .25s ease;">
            <div class="p-2 mt-0.5 space-y-1" style="background:var(--bg-deepest);border-radius:var(--radius-sm);border:1px solid var(--border-default);">
                <p class="text-[9px] font-mono" style="color:var(--text-muted);">Model: <strong style="color:var(--text-secondary);">${escapeHtml(step.model || '—')}</strong>${costEst ? ' &middot; Cost: ~$' + costEst : ''}</p>
                <p class="text-[9px] font-mono" style="color:var(--text-muted);">Prompt: <span style="color:var(--text-secondary);">${promptPreview}</span></p>
                <button onclick="navigator.clipboard.writeText(this.dataset.raw);showToast('Copied')" data-raw="${escapeHtml(JSON.stringify(step, null, 2))}" class="text-[9px] font-medium flex items-center gap-1" style="color:var(--accent);"><span class="material-icons-outlined text-[10px]">content_copy</span>Copy raw JSON</button>
            </div>
        </div>`;
    }

    const togglesHtml = (hasL2 || hasL3) && isDone ? `<div class="flex items-center gap-2 pl-6 mt-1">
        ${hasL2 ? `<button onclick="_toggleReasoningLevel('tool-l2-${uid}')" class="text-[9px] font-medium flex items-center gap-0.5" style="color:var(--accent);"><span class="material-icons-outlined text-[10px]">unfold_more</span>Details</button>` : ''}
        ${hasL3 ? `<button onclick="_toggleReasoningLevel('tool-l3-${uid}')" class="text-[9px] font-medium flex items-center gap-0.5" style="color:var(--text-muted);"><span class="material-icons-outlined text-[10px]">code</span>Inspect</button>` : ''}
    </div>` : '';

    const html = `
        <div id="tool-${step.id}" class="rounded-lg border px-3 py-2 transition-all ${isRunning ? 'tool-card-running' : ''}" style="background:${bgColor};border-color:${borderColor}">
            <div class="flex items-center gap-2 mb-0.5">
                <span class="material-icons-outlined shrink-0" style="font-size:15px;color:${iconColor}">${iconName}</span>
                <span class="text-[12px] font-mono font-semibold" style="color:${titleColor}">${escapeHtml(step.component)}</span>
                ${statusHtml}
                ${durationHtml}
            </div>
            <div class="pl-6"><p class="text-[10px] leading-snug" style="color:var(--text-secondary);">${escapeHtml(narrativeLine)}</p></div>
            ${l2Content}${l3Content}${togglesHtml}
        </div>
    `;

    if (existing) {
        existing.outerHTML = html;
    } else {
        container.insertAdjacentHTML('beforeend', html);
    }
}

function _toggleReasoningLevel(elId) {
    const el = document.getElementById(elId);
    if (!el) return;
    if (el.style.maxHeight && el.style.maxHeight !== '0px') {
        el.style.maxHeight = '0px';
    } else {
        el.style.maxHeight = el.scrollHeight + 'px';
    }
}

function _estimateStepCost(step) {
    if (!step.model || !step.duration) return '';
    const rates = { 'gpt-4o': 0.005, 'gpt-4o-mini': 0.0004, 'gpt-5': 0.008 };
    const perCall = rates[step.model] || 0.003;
    return perCall.toFixed(4);
}

function _appendROISummaryCard(container, responseText) {
    const tokensEst = Math.round((responseText || '').length / 4);
    const modelUsed = savedModel || 'gpt-4o';
    const rates = { 'gpt-4o': 2.5, 'gpt-4o-mini': 0.15, 'gpt-5': 5.0 };
    const ratePer1M = rates[modelUsed] || 2.5;
    const costEst = ((tokensEst / 1000000) * ratePer1M * 3).toFixed(4);
    const typeMap = { 'Legal': 'contract analysis', 'Finance': 'financial review', 'HR': 'HR policy lookup', 'Operations': 'operational assessment', 'Procurement': 'procurement verification' };
    const taskType = typeMap[savedAgentType] || 'analysis task';

    const card = document.createElement('div');
    card.className = 'mt-3 ml-2.5 rounded-lg border px-4 py-3';
    card.style.cssText = 'background:var(--bg-elevated);border-color:var(--border-default);';
    card.innerHTML = `
        <div class="flex items-center gap-2 mb-2">
            <span class="material-icons-outlined text-sm" style="color:var(--accent);">insights</span>
            <span class="text-[11px] font-semibold" style="color:var(--text-primary);">Task Summary</span>
        </div>
        <div class="flex items-center gap-4 mb-2 text-[10px]" style="color:var(--text-secondary);">
            <span>Cost: ~$${costEst} (${tokensEst.toLocaleString()} tokens)</span>
            <span>Model: ${escapeHtml(modelUsed)}</span>
        </div>
        <p class="text-[10px] mb-3" style="color:var(--text-muted);">Estimated value: ~30 min manual ${taskType} saved</p>
        <div class="flex items-center gap-2 flex-wrap">
            <button onclick="goToPage('quality')" class="px-2 py-1 text-[9px] font-medium flex items-center gap-1" style="background:var(--accent-subtle);color:var(--accent);border:1px solid var(--border-active);border-radius:var(--radius-sm);"><span class="material-icons-outlined text-[10px]">verified</span>Run Quality Eval</button>
            <button onclick="goToStep(2)" class="px-2 py-1 text-[9px] font-medium flex items-center gap-1" style="background:var(--bg-elevated);color:var(--text-secondary);border:1px solid var(--border-default);border-radius:var(--radius-sm);"><span class="material-icons-outlined text-[10px]">tune</span>Optimize in Builder</button>
            <button onclick="goToPage('hub')" class="px-2 py-1 text-[9px] font-medium flex items-center gap-1" style="background:var(--bg-elevated);color:var(--text-secondary);border:1px solid var(--border-default);border-radius:var(--radius-sm);"><span class="material-icons-outlined text-[10px]">bolt</span>New Objective</button>
        </div>
    `;
    container.appendChild(card);
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

let currentUser = _loadSession() || { email: 'thibaud.ishacian@presight.ai', name: 'Thibaud Ishacian', role: 'Admin' };

function _loadSession() {
    try {
        const raw = sessionStorage.getItem('aip_session');
        if (!raw) return null;
        const s = JSON.parse(raw);
        if (s && s.email && s.name && s.authenticated) return s;
    } catch (_) {}
    return null;
}

function _saveSession(user) {
    try {
        sessionStorage.setItem('aip_session', JSON.stringify({ ...user, authenticated: true }));
    } catch (_) {}
}

function _clearSession() {
    try { sessionStorage.removeItem('aip_session'); } catch (_) {}
}

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

    _saveSession(currentUser);

    setTimeout(() => {
        _activateApp();
    }, 800);
}

function _activateApp() {
    const screen = document.getElementById('login-screen');
    if (screen) {
        screen.style.opacity = '0';
        screen.style.transition = 'opacity 0.4s ease';
        setTimeout(() => screen.remove(), 500);
    }

    document.getElementById('app-sidebar').style.opacity = '1';
    document.getElementById('app-main').style.opacity = '1';

    const userEl = document.getElementById('user-badge');
    if (userEl) {
        const initials = currentUser.name.split(' ').map(n => n[0]).join('');
        userEl.innerHTML = `<div class="w-7 h-7 rounded-full flex items-center justify-center text-white text-[10px] font-bold" style="background:var(--accent);">${initials}</div>
            <span class="text-xs font-medium truncate" style="color:var(--text-secondary);">${escapeHtml(currentUser.name)}</span>
            <span class="material-icons-outlined text-sm" style="color:var(--text-muted);">expand_more</span>`;
    }

    goToPage('systems');
}

// Allow Enter key on login form
document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && document.getElementById('login-screen')) {
        e.preventDefault();
        handleLogin();
    }
});

// =========================================================================
// WORKFLOW EDITOR (Drawflow)
// =========================================================================

var wfEditor = null;
var wfCurrentModule = 'Home';
var wfSelectedNode = null;

function wfNodeHtml(icon, title, meta, extra) {
    return `<div class="df-node"><div class="df-node-header"><span class="material-icons-outlined">${icon}</span><span class="df-title">${title}</span></div><div class="df-node-meta">${meta}</div>${extra || ''}</div>`;
}

function wfMacroHtml(icon, title, meta, steps) {
    return `<div class="df-node"><div class="df-node-header"><span class="material-icons-outlined">${icon}</span><span class="df-title">${title}</span></div><div class="df-node-meta">${meta}</div><div class="df-drilldown" ondblclick="wfDrillDown('${title}')"><span class="material-icons-outlined" style="font-size:10px;">unfold_more</span>${steps} steps &middot; double-click to expand</div></div>`;
}

function initWorkflowEditor() {
    const container = document.getElementById('drawflow-canvas');
    if (!container || typeof Drawflow === 'undefined') return;

    wfEditor = new Drawflow(container);
    wfEditor.reroute = true;
    wfEditor.reroute_fix_curvature = true;

    wfEditor.addModule('Home');
    wfEditor.addModule('Data Ingestion');
    wfEditor.addModule('Knowledge Processing');
    wfEditor.addModule('Agent Reasoning');
    wfEditor.addModule('Response Generation');
    wfEditor.addModule('Quality Assurance');

    wfEditor.start();

    const saved = localStorage.getItem('aip_workflow');
    if (saved) {
        try {
            wfEditor.import(JSON.parse(saved));
            wfCurrentModule = 'Home';
            wfEditor.changeModule('Home');
        } catch (_) { wfSeedDefault(); }
    } else {
        wfSeedDefault();
    }

    wfEditor.on('nodeSelected', function(id) {
        wfSelectedNode = id;
        wfShowConfig(id);
    });
    wfEditor.on('nodeUnselected', function() {
        wfSelectedNode = null;
        wfCloseConfig();
    });
    wfEditor.on('nodeMoved', function() { /* auto-handled */ });

    const macroModuleMap = {
        'input': null, 'output': null,
        'ingestion': 'Data Ingestion',
        'processing': 'Knowledge Processing',
        'reasoning': 'Agent Reasoning',
        'generation': 'Response Generation',
        'quality': 'Quality Assurance'
    };
    wfEditor.on('nodeSelected', function(id) {
        const node = wfEditor.getNodeFromId(id);
        if (!node) return;
        const el = document.querySelector('#node-' + id);
        if (!el) return;
        el.ondblclick = function() {
            const mod = macroModuleMap[node.name];
            if (mod) wfDrillDown(mod);
        };
    });

    wfSetupDragDrop();

    wfEditor.on('nodeCreated', () => wfUpdateNodeCount());
    wfEditor.on('nodeRemoved', () => wfUpdateNodeCount());
    setTimeout(wfUpdateNodeCount, 200);
}

function wfSeedDefault() {
    if (!wfEditor) return;
    wfEditor.changeModule('Home');

    const n1 = wfEditor.addNode('input', 0, 1, 50, 200, 'df-macro', {type:'io_input'}, wfMacroHtml('input', 'User Query', 'Entry point', '1'));
    const n2 = wfEditor.addNode('ingestion', 1, 1, 280, 120, 'df-macro', {type:'ingestion'}, wfMacroHtml('cloud_upload', 'Data Ingestion', 'Connectors &middot; Upload &middot; Storage', '3'));
    const n3 = wfEditor.addNode('processing', 1, 1, 530, 120, 'df-macro', {type:'processing'}, wfMacroHtml('memory', 'Knowledge Processing', 'Parse &middot; Chunk &middot; Embed &middot; Store', '4'));
    const n4 = wfEditor.addNode('reasoning', 1, 1, 780, 120, 'df-macro', {type:'reasoning'}, wfMacroHtml('psychology', 'Agent Reasoning', 'Rewrite &middot; Retrieve &middot; Filter &middot; Validate', '4'));
    const n5 = wfEditor.addNode('generation', 1, 1, 1030, 120, 'df-macro', {type:'generation'}, wfMacroHtml('auto_awesome', 'Response Generation', 'Prompt &middot; LLM &middot; Structured Output', '3'));
    const n6 = wfEditor.addNode('quality', 1, 1, 1280, 120, 'df-macro', {type:'quality'}, wfMacroHtml('verified', 'Quality Assurance', 'Factuality &middot; HHEM &middot; Audit', '3'));
    const n7 = wfEditor.addNode('output', 1, 0, 1530, 200, 'df-macro', {type:'io_output'}, wfMacroHtml('output', 'Agent Response', 'Final output', '1'));

    wfEditor.addConnection(n1, n2, 'output_1', 'input_1');
    wfEditor.addConnection(n2, n3, 'output_1', 'input_1');
    wfEditor.addConnection(n3, n4, 'output_1', 'input_1');
    wfEditor.addConnection(n4, n5, 'output_1', 'input_1');
    wfEditor.addConnection(n5, n6, 'output_1', 'input_1');
    wfEditor.addConnection(n6, n7, 'output_1', 'input_1');

    const infraY = 380;
    wfEditor.addNode('fastapi', 0, 0, 280, infraY, 'df-infra', {type:'infra_fastapi'}, wfNodeHtml('dns', 'FastAPI', 'API Gateway'));
    wfEditor.addNode('celery', 0, 0, 530, infraY, 'df-infra', {type:'infra_celery'}, wfNodeHtml('schedule', 'Celery', 'Task Queue'));
    wfEditor.addNode('minio', 0, 0, 780, infraY, 'df-infra', {type:'infra_minio'}, wfNodeHtml('inventory_2', 'MinIO', 'Object Storage'));
    wfEditor.addNode('pg', 0, 0, 1030, infraY, 'df-infra', {type:'infra_pg'}, wfNodeHtml('storage', 'PostgreSQL', 'Metadata DB'));
    wfEditor.addNode('qdrant', 0, 0, 1280, infraY, 'df-infra', {type:'infra_qdrant'}, wfNodeHtml('scatter_plot', 'Qdrant', 'Vector Store'));

    wfSeedSubmodules();
}

function wfSeedSubmodules() {
    if (!wfEditor) return;

    wfEditor.changeModule('Data Ingestion');
    const di1 = wfEditor.addNode('upload', 0, 1, 80, 150, '', {type:'io_input'}, wfNodeHtml('cloud_upload', 'File Upload', 'PDF, DOCX, MD'));
    const di2 = wfEditor.addNode('sharepoint', 0, 1, 80, 280, '', {type:'conn_sharepoint'}, wfNodeHtml('folder_shared', 'SharePoint', 'Policy docs'));
    const di3 = wfEditor.addNode('s3', 0, 1, 80, 400, '', {type:'conn_s3'}, wfNodeHtml('cloud_queue', 'AWS S3', 'Bucket sync'));
    const di4 = wfEditor.addNode('minio_store', 1, 1, 380, 250, '', {type:'infra_minio'}, wfNodeHtml('inventory_2', 'MinIO Storage', 'Object store'));
    const di5 = wfEditor.addNode('out', 1, 0, 620, 250, '', {type:'io_output'}, wfNodeHtml('output', 'To Processing', 'Next stage'));
    wfEditor.addConnection(di1, di4, 'output_1', 'input_1');
    wfEditor.addConnection(di2, di4, 'output_1', 'input_1');
    wfEditor.addConnection(di3, di4, 'output_1', 'input_1');
    wfEditor.addConnection(di4, di5, 'output_1', 'input_1');

    wfEditor.changeModule('Knowledge Processing');
    const kp1 = wfEditor.addNode('in', 0, 1, 50, 200, '', {type:'io_input'}, wfNodeHtml('input', 'From Ingestion', 'Raw docs'));
    const kp2 = wfEditor.addNode('parser', 1, 1, 250, 200, '', {type:'query_rewrite'}, wfNodeHtml('description', 'Parser', 'pdfplumber'));
    const kp3 = wfEditor.addNode('chunker', 1, 1, 450, 200, '', {type:'context_filter'}, wfNodeHtml('content_cut', 'Chunker', '512 tokens'));
    const kp4 = wfEditor.addNode('embedder', 1, 1, 650, 200, '', {type:'embedding'}, wfNodeHtml('hub', 'Embedder', 'text-embed-3-sm'));
    const kp5 = wfEditor.addNode('qdrant', 1, 0, 850, 200, '', {type:'infra_qdrant'}, wfNodeHtml('scatter_plot', 'Qdrant Store', 'FAISS index'));
    wfEditor.addConnection(kp1, kp2, 'output_1', 'input_1');
    wfEditor.addConnection(kp2, kp3, 'output_1', 'input_1');
    wfEditor.addConnection(kp3, kp4, 'output_1', 'input_1');
    wfEditor.addConnection(kp4, kp5, 'output_1', 'input_1');

    wfEditor.changeModule('Agent Reasoning');
    const ar1 = wfEditor.addNode('in', 0, 1, 50, 200, '', {type:'io_input'}, wfNodeHtml('input', 'User Query', 'Raw input'));
    const ar2 = wfEditor.addNode('rewrite', 1, 1, 250, 200, '', {type:'query_rewrite'}, wfNodeHtml('edit_note', 'Query Rewrite', 'gpt-4o-mini'));
    const ar3 = wfEditor.addNode('retrieve', 1, 1, 470, 200, '', {type:'retrieval'}, wfNodeHtml('search', 'Hybrid Retrieval', 'topK=5'));
    const ar4 = wfEditor.addNode('filter', 1, 1, 690, 200, '', {type:'context_filter'}, wfNodeHtml('filter_alt', 'Context Filter', 'threshold=0.2'));
    const ar5 = wfEditor.addNode('validate', 1, 0, 910, 200, '', {type:'validation'}, wfNodeHtml('verified', 'Validation', 'Rules engine'));
    wfEditor.addConnection(ar1, ar2, 'output_1', 'input_1');
    wfEditor.addConnection(ar2, ar3, 'output_1', 'input_1');
    wfEditor.addConnection(ar3, ar4, 'output_1', 'input_1');
    wfEditor.addConnection(ar4, ar5, 'output_1', 'input_1');

    wfEditor.changeModule('Response Generation');
    const rg1 = wfEditor.addNode('in', 0, 1, 50, 200, '', {type:'io_input'}, wfNodeHtml('input', 'Validated Context', 'From reasoning'));
    const rg2 = wfEditor.addNode('prompt', 1, 1, 280, 200, '', {type:'synthesis'}, wfNodeHtml('description', 'System Prompt', 'Template'));
    const rg3 = wfEditor.addNode('llm', 1, 1, 520, 200, '', {type:'llm_gpt4o'}, wfNodeHtml('psychology', 'GPT-4o', 'Synthesis LLM'));
    const rg4 = wfEditor.addNode('out', 1, 0, 760, 200, '', {type:'io_output'}, wfNodeHtml('output', 'Raw Response', 'Markdown'));
    wfEditor.addConnection(rg1, rg2, 'output_1', 'input_1');
    wfEditor.addConnection(rg2, rg3, 'output_1', 'input_1');
    wfEditor.addConnection(rg3, rg4, 'output_1', 'input_1');

    wfEditor.changeModule('Quality Assurance');
    const qa1 = wfEditor.addNode('in', 0, 1, 50, 200, '', {type:'io_input'}, wfNodeHtml('input', 'LLM Response', 'Raw output'));
    const qa2 = wfEditor.addNode('eval', 1, 1, 300, 150, '', {type:'evaluation'}, wfNodeHtml('analytics', 'Evaluator', 'Cosine similarity'));
    const qa3 = wfEditor.addNode('hhem', 1, 1, 300, 300, '', {type:'evaluation'}, wfNodeHtml('fact_check', 'HHEM', 'Hallucination check'));
    const qa4 = wfEditor.addNode('audit', 1, 1, 560, 200, '', {type:'validation'}, wfNodeHtml('receipt_long', 'Audit Logger', 'SQLite'));
    const qa5 = wfEditor.addNode('out', 1, 0, 780, 200, '', {type:'io_output'}, wfNodeHtml('output', 'Final Response', 'Scored + logged'));
    wfEditor.addConnection(qa1, qa2, 'output_1', 'input_1');
    wfEditor.addConnection(qa1, qa3, 'output_1', 'input_1');
    wfEditor.addConnection(qa2, qa4, 'output_1', 'input_1');
    wfEditor.addConnection(qa3, qa4, 'output_1', 'input_1');
    wfEditor.addConnection(qa4, qa5, 'output_1', 'input_1');

    wfEditor.changeModule('Home');
}

function wfDrillDown(moduleName) {
    if (!wfEditor) return;
    wfCurrentModule = moduleName;
    wfEditor.changeModule(moduleName);
    const bc = document.getElementById('wf-breadcrumb');
    if (bc) bc.innerHTML = `<span style="color:var(--text-muted);cursor:pointer;" onclick="wfGoHome()">Workflow</span><span class="material-icons-outlined text-[10px]" style="color:var(--text-muted);">chevron_right</span><span class="font-semibold" style="color:var(--text-primary);">${moduleName}</span>`;
}

function wfGoHome() {
    if (!wfEditor) return;
    wfCurrentModule = 'Home';
    wfEditor.changeModule('Home');
    const bc = document.getElementById('wf-breadcrumb');
    if (bc) bc.innerHTML = `<span class="font-semibold" style="color:var(--text-primary);">Workflow</span>`;
}

function wfSetupDragDrop() {
    const canvas = document.getElementById('drawflow-canvas');
    if (!canvas) return;

    document.querySelectorAll('.wf-palette-item').forEach(item => {
        item.addEventListener('dragstart', (e) => {
            e.dataTransfer.setData('node-type', item.dataset.nodeType);
            e.dataTransfer.setData('node-name', item.dataset.nodeName);
            e.dataTransfer.setData('node-icon', item.dataset.nodeIcon);
            e.dataTransfer.setData('node-meta', item.dataset.nodeMeta);
        });
    });

    canvas.addEventListener('drop', (e) => {
        e.preventDefault();
        const type = e.dataTransfer.getData('node-type');
        const name = e.dataTransfer.getData('node-name');
        const icon = e.dataTransfer.getData('node-icon');
        const meta = e.dataTransfer.getData('node-meta');
        if (!type || !wfEditor) return;
        const isInfra = type.startsWith('infra_');
        const cls = isInfra ? 'df-infra' : '';
        const inputs = type.startsWith('io_input') ? 0 : 1;
        const outputs = type.startsWith('io_output') ? 0 : 1;
        const rect = canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left) / wfEditor.zoom - wfEditor.precanvas.getBoundingClientRect().x / wfEditor.zoom;
        const y = (e.clientY - rect.top) / wfEditor.zoom - wfEditor.precanvas.getBoundingClientRect().y / wfEditor.zoom;
        wfEditor.addNode(type, inputs, outputs, x, y, cls, {type: type}, wfNodeHtml(icon, name, meta));
    });

    canvas.addEventListener('dragover', (e) => e.preventDefault());
}

function wfShowConfig(nodeId) {
    const panel = document.getElementById('wf-config-panel');
    const titleEl = document.getElementById('wf-cfg-title');
    const typeEl = document.getElementById('wf-cfg-type');
    const fieldsEl = document.getElementById('wf-cfg-fields');
    if (!panel || !wfEditor) return;

    const nodeData = wfEditor.getNodeFromId(nodeId);
    if (!nodeData) return;
    const type = nodeData.data?.type || nodeData.class || 'unknown';

    titleEl.textContent = nodeData.name || type;
    typeEl.textContent = type;
    panel.style.display = '';

    const statusBadge = `<div class="flex items-center gap-1.5 p-1.5 mb-2" style="background:var(--bg-elevated);border-radius:var(--radius-sm);"><span class="w-1.5 h-1.5 rounded-full" style="background:var(--success);"></span><span class="text-[9px] font-medium" style="color:var(--success);">Active</span><span class="text-[9px] ml-auto font-mono" style="color:var(--text-muted);">node-${nodeId}</span></div>`;

    let fields = statusBadge;
    fields += `<div class="wf-config-field"><label>Display Name</label><input id="wf-cfg-name" value="${nodeData.name || ''}" onchange="wfUpdateNodeName(${nodeId}, this.value)"></div>`;
    fields += `<div class="wf-config-field"><label>Description</label><input placeholder="Brief description of this node's role..." value=""></div>`;

    if (type.startsWith('agent_')) {
        const agentId = type.replace('agent_', '');
        const saved = JSON.parse(localStorage.getItem('aip_agents') || '[]');
        const prebuiltMap = { procurement: { name:'Procurement Agent', type:'Procurement', model:'gpt-4o', prompt:'Enterprise procurement compliance agent.' }, legal: { name:'Legal Review', type:'Legal', model:'gpt-4o', prompt:'Contract analysis and risk assessment agent.' }, hr: { name:'HR Assistant', type:'HR', model:'gpt-4o-mini', prompt:'HR policy and onboarding assistant.' }, finance: { name:'Financial Analyst', type:'Finance', model:'gpt-4o', prompt:'Financial analysis and forecasting agent.' } };
        const info = prebuiltMap[agentId] || saved.find(a => a.id === agentId) || { name: agentId, type: '—', model: '—', prompt: '' };
        const promptSnip = (info.prompt || info.systemPrompt || '').substring(0, 120);
        fields += `<div class="p-2 mb-2" style="background:var(--accent-subtle);border:1px solid var(--border-active);border-radius:var(--radius-sm);"><p class="text-[10px] font-semibold" style="color:var(--accent);">${escapeHtml(info.name || agentId)}</p><p class="text-[9px]" style="color:var(--text-muted);">${escapeHtml(info.type)} &middot; ${escapeHtml(info.model)}</p></div>`;
        if (promptSnip) fields += `<div class="wf-config-field"><label>System Prompt</label><textarea rows="3" readonly style="font-size:9px;resize:none;opacity:0.8;">${escapeHtml(promptSnip)}${promptSnip.length >= 120 ? '...' : ''}</textarea></div>`;
        fields += `<div class="flex gap-2 mt-2"><button onclick="launchPrebuiltAgent('${agentId}')" class="flex-1 py-1.5 text-[10px] font-medium flex items-center justify-center gap-1" style="background:var(--accent);color:white;border-radius:var(--radius-sm);"><span class="material-icons-outlined text-xs">chat</span>Open in Chat</button><button onclick="goToStep(1)" class="flex-1 py-1.5 text-[10px] font-medium flex items-center justify-center gap-1" style="background:var(--bg-elevated);border:1px solid var(--border-default);color:var(--text-secondary);border-radius:var(--radius-sm);"><span class="material-icons-outlined text-xs">edit</span>Edit in Builder</button></div>`;
    } else if (type.startsWith('llm_') || type === 'synthesis' || type === 'query_rewrite') {
        const isRewrite = type === 'query_rewrite';
        const isGpt4o = type === 'llm_gpt4o' || type === 'synthesis';
        fields += `<div class="wf-config-field"><label>Provider</label><select><option selected>OpenAI</option><option>Azure OpenAI</option><option>Anthropic</option><option>Self-hosted (vLLM)</option><option>Ollama</option></select></div>`;
        fields += `<div class="wf-config-field"><label>Model</label><select>${isGpt4o ? '<option selected>gpt-4o</option><option>gpt-4o-mini</option>' : '<option>gpt-4o</option><option selected>gpt-4o-mini</option>'}<option>gpt-4.1-nano</option><option>claude-3.5-sonnet</option><option>llama-3.1-70b</option></select></div>`;
        fields += `<div class="wf-config-field"><label>Temperature</label><div class="flex items-center gap-2"><input type="range" min="0" max="100" value="${isRewrite ? 20 : 30}" class="flex-1" oninput="this.nextElementSibling.textContent=(this.value/100).toFixed(2)"><span class="text-[9px] font-mono w-8 text-right" style="color:var(--accent);">${isRewrite ? '0.20' : '0.30'}</span></div></div>`;
        fields += `<div class="wf-config-field"><label>Max Output Tokens</label><input type="number" value="${isRewrite ? 256 : 4096}" min="64" max="16384"></div>`;
        fields += `<div class="wf-config-field"><label>Top-P</label><div class="flex items-center gap-2"><input type="range" min="0" max="100" value="95" class="flex-1" oninput="this.nextElementSibling.textContent=(this.value/100).toFixed(2)"><span class="text-[9px] font-mono w-8 text-right" style="color:var(--accent);">0.95</span></div></div>`;
        fields += `<div class="wf-config-field"><label>Frequency Penalty</label><div class="flex items-center gap-2"><input type="range" min="0" max="200" value="0" class="flex-1" oninput="this.nextElementSibling.textContent=(this.value/100).toFixed(2)"><span class="text-[9px] font-mono w-8 text-right" style="color:var(--accent);">0.00</span></div></div>`;
        fields += `<div class="wf-config-field"><label>Response Format</label><select><option selected>text</option><option>json_object</option><option>structured (schema)</option></select></div>`;
        fields += `<div class="wf-config-field"><label>Streaming</label><div class="flex items-center gap-2 mt-1"><div onclick="this.dataset.on=this.dataset.on==='1'?'0':'1';this.style.background=this.dataset.on==='1'?'var(--accent)':'var(--border-default)';this.firstElementChild.style.left=this.dataset.on==='1'?'14px':'2px'" class="w-7 h-4 rounded-full relative cursor-pointer" data-on="1" style="background:var(--accent);"><div class="w-3 h-3 rounded-full bg-white absolute top-0.5 transition-all" style="left:14px;"></div></div><span class="text-[9px]" style="color:var(--text-muted);">Enable SSE streaming</span></div></div>`;
    } else if (type === 'retrieval') {
        fields += `<div class="wf-config-field"><label>Strategy</label><select><option selected>Hybrid (Dense + BM25)</option><option>Dense only (FAISS)</option><option>Sparse only (BM25)</option><option>Re-rank (Cohere)</option></select></div>`;
        fields += `<div class="wf-config-field"><label>Top-K Results</label><div class="flex items-center gap-2"><input type="number" value="5" min="1" max="50" class="w-16"><span class="text-[9px]" style="color:var(--text-muted);">documents to retrieve</span></div></div>`;
        fields += `<div class="wf-config-field"><label>Vector Weight (Dense vs. Sparse)</label><div class="flex items-center gap-2"><input type="range" min="0" max="100" value="70" class="flex-1" oninput="this.nextElementSibling.textContent=this.value+'% dense / '+(100-this.value)+'% sparse'"><span class="text-[9px] font-mono" style="color:var(--accent);">70% dense / 30% sparse</span></div></div>`;
        fields += `<div class="wf-config-field"><label>Similarity Threshold</label><div class="flex items-center gap-2"><input type="range" min="0" max="100" value="20" class="flex-1" oninput="this.nextElementSibling.textContent=(this.value/100).toFixed(2)"><span class="text-[9px] font-mono w-8 text-right" style="color:var(--accent);">0.20</span></div></div>`;
        fields += `<div class="wf-config-field"><label>Vector Store</label><select><option selected>FAISS (local)</option><option>Qdrant</option><option>Chroma</option><option>Pinecone</option><option>Weaviate</option></select></div>`;
        fields += `<div class="wf-config-field"><label>Embedding Model</label><select><option selected>text-embedding-3-small</option><option>text-embedding-3-large</option><option>e5-mistral-7b</option></select></div>`;
    } else if (type === 'embedding') {
        fields += `<div class="wf-config-field"><label>Embedding Model</label><select><option selected>text-embedding-3-small</option><option>text-embedding-3-large</option><option>e5-mistral-7b</option><option>bge-large-en</option></select></div>`;
        fields += `<div class="wf-config-field"><label>Dimensions</label><input type="number" value="1536" min="256" max="3072"></div>`;
        fields += `<div class="wf-config-field"><label>Batch Size</label><input type="number" value="32" min="1" max="256"></div>`;
        fields += `<div class="wf-config-field"><label>Normalize</label><div class="flex items-center gap-2 mt-1"><div class="w-7 h-4 rounded-full relative cursor-pointer" style="background:var(--accent);"><div class="w-3 h-3 rounded-full bg-white absolute top-0.5" style="left:14px;"></div></div><span class="text-[9px]" style="color:var(--text-muted);">L2 normalization</span></div></div>`;
    } else if (type === 'context_filter') {
        fields += `<div class="wf-config-field"><label>Filter Strategy</label><select><option selected>Score threshold</option><option>Max token budget</option><option>Contextual compression</option><option>LLM-based rerank</option></select></div>`;
        fields += `<div class="wf-config-field"><label>Min. Relevance Score</label><div class="flex items-center gap-2"><input type="range" min="0" max="100" value="20" class="flex-1" oninput="this.nextElementSibling.textContent=(this.value/100).toFixed(2)"><span class="text-[9px] font-mono w-8 text-right" style="color:var(--accent);">0.20</span></div></div>`;
        fields += `<div class="wf-config-field"><label>Max Context Tokens</label><input type="number" value="4000" min="500" max="32000"></div>`;
        fields += `<div class="wf-config-field"><label>Deduplication</label><div class="flex items-center gap-2 mt-1"><div class="w-7 h-4 rounded-full relative cursor-pointer" style="background:var(--accent);"><div class="w-3 h-3 rounded-full bg-white absolute top-0.5" style="left:14px;"></div></div><span class="text-[9px]" style="color:var(--text-muted);">Remove near-duplicate chunks</span></div></div>`;
    } else if (type === 'validation') {
        fields += `<div class="wf-config-field"><label>Validation Mode</label><select><option selected>Rule-based</option><option>LLM-based</option><option>Schema validation</option><option>Hybrid</option></select></div>`;
        fields += `<div class="wf-config-field"><label>Rules Source</label><select><option selected>Auto-extracted from KB</option><option>Manual rules</option><option>External policy API</option></select></div>`;
        fields += `<div class="wf-config-field"><label>Strict Mode</label><div class="flex items-center gap-2 mt-1"><div class="w-7 h-4 rounded-full relative cursor-pointer" style="background:var(--border-default);"><div class="w-3 h-3 rounded-full bg-white absolute top-0.5" style="left:2px;"></div></div><span class="text-[9px]" style="color:var(--text-muted);">Reject non-compliant responses</span></div></div>`;
        fields += `<div class="wf-config-field"><label>Fallback Action</label><select><option selected>Return warning</option><option>Retry with constraints</option><option>Escalate to human</option></select></div>`;
    } else if (type.startsWith('conn_')) {
        const connDefaults = {
            conn_sharepoint: { url: 'https://tenant.sharepoint.com/sites/policies', auth: 'OAuth 2.0', scope: 'Sites.Read.All' },
            conn_s3: { url: 's3://company-data/documents/', auth: 'IAM Role', scope: 'eu-west-1' },
            conn_postgres: { url: 'postgresql://db.internal:5432/analytics', auth: 'Credentials', scope: 'public schema' },
            conn_rest: { url: 'https://api.internal.company.com/v2', auth: 'Bearer Token', scope: 'read:data' },
            conn_teams: { url: 'https://graph.microsoft.com/v1.0/teams', auth: 'OAuth 2.0', scope: 'ChannelMessage.Send' },
            conn_mqtt: { url: 'mqtt://broker.iot.internal:1883', auth: 'Client Certificate', scope: 'sensors/+/data' },
        };
        const def = connDefaults[type] || { url: 'https://...', auth: 'Bearer Token', scope: '' };
        fields += `<div class="wf-config-field"><label>Endpoint / Connection URI</label><input type="url" value="${def.url}"></div>`;
        fields += `<div class="wf-config-field"><label>Authentication</label><select>${['Bearer Token','API Key','OAuth 2.0','IAM Role','Client Certificate','Basic Auth','None'].map(a => `<option${a===def.auth?' selected':''}>${a}</option>`).join('')}</select></div>`;
        fields += `<div class="wf-config-field"><label>Scope / Permissions</label><input value="${def.scope}"></div>`;
        fields += `<div class="wf-config-field"><label>Credentials</label><input type="password" placeholder="••••••••••" value="configured"></div>`;
        fields += `<div class="wf-config-field"><label>Timeout (ms)</label><input type="number" value="15000" min="1000" max="120000"></div>`;
        fields += `<div class="wf-config-field"><label>Retry Policy</label><select><option selected>3x exponential backoff</option><option>No retry</option><option>5x linear</option></select></div>`;
        fields += `<div class="flex items-center gap-1.5 p-1.5 mt-2" style="background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.2);border-radius:var(--radius-sm);"><span class="material-icons-outlined text-xs" style="color:var(--success);">link</span><span class="text-[9px] font-medium" style="color:var(--success);">Connection verified &middot; 42ms latency</span></div>`;
    } else if (type === 'evaluation') {
        fields += `<div class="wf-config-field"><label>Evaluation Method</label><select><option selected>Embedding cosine similarity</option><option>LLM-as-Judge (GPT-4o)</option><option>Both</option></select></div>`;
        fields += `<div class="wf-config-field"><label>Metrics</label>`;
        [['Factuality','Grounding against retrieved docs',true],['Relevance','Query-response alignment',true],['Coherence','Internal consistency',true],['HHEM','Hallucination estimation',true],['Conciseness','Redundancy detection',false],['Safety','Toxicity and harm check',false]].forEach(([m,d,c]) => {
            fields += `<label class="flex items-center gap-1.5 text-[10px] p-1 mt-0.5 cursor-pointer" style="color:var(--text-secondary);background:var(--bg-elevated);border-radius:var(--radius-xs);"><input type="checkbox" ${c?'checked ':''} class="w-3 h-3"><div><span style="color:var(--text-primary);">${m}</span><span class="text-[8px] block" style="color:var(--text-muted);">${d}</span></div></label>`;
        });
        fields += `</div>`;
        fields += `<div class="wf-config-field"><label>Score Threshold (pass/fail)</label><div class="flex items-center gap-2"><input type="range" min="0" max="100" value="60" class="flex-1" oninput="this.nextElementSibling.textContent=this.value+'%'"><span class="text-[9px] font-mono w-8 text-right" style="color:var(--accent);">60%</span></div></div>`;
        fields += `<div class="wf-config-field"><label>On Failure</label><select><option selected>Log warning</option><option>Block response</option><option>Retry generation</option></select></div>`;
    } else if (type.startsWith('infra_')) {
        const infraDefaults = {
            infra_fastapi: { host: '0.0.0.0', port: 8000, status: 'Running', extra: 'Workers: 4 (uvicorn)' },
            infra_celery: { host: 'redis://cache:6379/0', port: 6379, status: 'Running', extra: 'Queues: default, batch, priority' },
            infra_minio: { host: 'minio.internal', port: 9000, status: 'Running', extra: 'Buckets: documents, embeddings' },
            infra_pg: { host: 'pg.internal', port: 5432, status: 'Running', extra: 'DB: omnirag | Pool: 20 connections' },
            infra_qdrant: { host: 'qdrant.internal', port: 6333, status: 'Running', extra: 'Collections: kb_vectors | Dim: 1536' },
        };
        const def = infraDefaults[type] || { host: 'localhost', port: 8000, status: 'Running', extra: '' };
        fields += `<div class="wf-config-field"><label>Host</label><input value="${def.host}"></div>`;
        fields += `<div class="wf-config-field"><label>Port</label><input type="number" value="${def.port}"></div>`;
        fields += `<div class="wf-config-field"><label>Status</label><div class="flex items-center gap-1.5 mt-1"><span class="w-1.5 h-1.5 rounded-full" style="background:var(--success);"></span><span class="text-[10px] font-medium" style="color:var(--success);">${def.status}</span></div></div>`;
        fields += `<div class="wf-config-field"><label>Details</label><p class="text-[9px] font-mono mt-0.5" style="color:var(--text-muted);">${def.extra}</p></div>`;
        fields += `<div class="wf-config-field"><label>Health Check</label><select><option selected>TCP ping</option><option>HTTP /health</option><option>Custom script</option></select></div>`;
    } else if (type === 'rss_ingest') {
        fields += `<div class="wf-config-field"><label>Feed URLs</label><textarea rows="3" placeholder="https://feeds.reuters.com/reuters/topNews&#10;https://rss.nytimes.com/services/xml/rss/nyt/World.xml" style="resize:none;font-family:'JetBrains Mono',monospace;font-size:9px;"></textarea></div>`;
        fields += `<div class="wf-config-field"><label>Refresh Interval</label><select><option>15 minutes</option><option selected>1 hour</option><option>6 hours</option><option>Daily</option></select></div>`;
        fields += `<div class="wf-config-field"><label>Max Articles per Fetch</label><input type="number" value="50" min="5" max="500"></div>`;
        fields += `<div class="wf-config-field"><label>Content Extraction</label><select><option selected>RSS summary</option><option>Full article (readability)</option><option>Both</option></select></div>`;
    } else if (type === 'semantic_filter') {
        fields += `<div class="wf-config-field"><label>Target Description</label><textarea rows="2" placeholder="e.g., Hormuz Strait tensions, energy supply chain disruption..." style="resize:none;"></textarea></div>`;
        fields += `<div class="wf-config-field"><label>Relevance Threshold</label><div class="flex items-center gap-2"><input type="range" min="0" max="100" value="30" class="flex-1" oninput="this.nextElementSibling.textContent=(this.value/100).toFixed(2)"><span class="text-[9px] font-mono w-8 text-right" style="color:var(--accent);">0.30</span></div></div>`;
        fields += `<div class="wf-config-field"><label>Boost Keywords</label><input placeholder="oil, sanctions, strait, pipeline (comma-separated)"></div>`;
    } else if (type === 'safety_check') {
        fields += `<div class="wf-config-field"><label>Safety Prompt</label><textarea rows="3" placeholder="Ensure analysis aligns with UAE geopolitical positioning. Flag content that could be perceived as taking sides in regional conflicts..." style="resize:none;"></textarea></div>`;
        fields += `<div class="wf-config-field"><label>Severity</label><select><option>Warn only</option><option selected>Flag for review</option><option>Block content</option></select></div>`;
        fields += `<div class="wf-config-field"><label>Check Dimensions</label>`;
        ['Geopolitical alignment','Toxicity','PII detection','Bias'].forEach(d => {
            fields += `<label class="flex items-center gap-1.5 text-[10px] mt-1" style="color:var(--text-secondary);"><input type="checkbox" checked class="w-3 h-3">${d}</label>`;
        });
        fields += `</div>`;
    } else if (type === 'bi_aggregator') {
        fields += `<div class="wf-config-field"><label>Aggregation</label><select><option selected>Sentiment + Entity + Risk</option><option>Sentiment only</option><option>Entity graph</option><option>Custom</option></select></div>`;
        fields += `<div class="wf-config-field"><label>Time Window</label><select><option>Last 24 hours</option><option selected>Last 7 days</option><option>Last 30 days</option><option>Custom range</option></select></div>`;
        fields += `<div class="wf-config-field"><label>Output</label><select><option selected>Dashboard JSON</option><option>CSV export</option><option>PDF report</option><option>Webhook push</option></select></div>`;
    } else if (type === 'io_input') {
        fields += `<div class="wf-config-field"><label>Input Type</label><select><option selected>User query (text)</option><option>Webhook payload</option><option>Scheduled trigger</option><option>File upload</option></select></div>`;
        fields += `<div class="wf-config-field"><label>Max Input Length</label><input type="number" value="2000" min="100" max="32000"></div>`;
        fields += `<div class="wf-config-field"><label>Pre-processing</label><select><option selected>None</option><option>Language detection</option><option>Intent classification</option><option>PII redaction</option></select></div>`;
    } else if (type === 'io_output') {
        fields += `<div class="wf-config-field"><label>Output Format</label><select><option selected>Streaming SSE</option><option>JSON response</option><option>Markdown</option><option>Structured (Pydantic)</option></select></div>`;
        fields += `<div class="wf-config-field"><label>Post-processing</label><select><option selected>Markdown rendering</option><option>Citation injection</option><option>Both</option><option>None</option></select></div>`;
        fields += `<div class="wf-config-field"><label>TTS Output</label><div class="flex items-center gap-2 mt-1"><div class="w-7 h-4 rounded-full relative cursor-pointer" style="background:var(--border-default);"><div class="w-3 h-3 rounded-full bg-white absolute top-0.5" style="left:2px;"></div></div><span class="text-[9px]" style="color:var(--text-muted);">Enable voice output (OpenAI TTS)</span></div></div>`;
    } else if (type === 'io_webhook') {
        fields += `<div class="wf-config-field"><label>Webhook URL</label><input type="url" placeholder="https://hooks.company.com/agent/trigger"></div>`;
        fields += `<div class="wf-config-field"><label>Method</label><select><option selected>POST</option><option>PUT</option><option>PATCH</option></select></div>`;
        fields += `<div class="wf-config-field"><label>Headers</label><textarea rows="2" placeholder='{"Authorization": "Bearer ...", "Content-Type": "application/json"}' style="resize:none;font-family:'JetBrains Mono',monospace;font-size:9px;"></textarea></div>`;
        fields += `<div class="wf-config-field"><label>Secret</label><input type="password" placeholder="whsec_..."></div>`;
    }

    fieldsEl.innerHTML = fields;
}

function wfCloseConfig() {
    const panel = document.getElementById('wf-config-panel');
    if (panel) panel.style.display = 'none';
    wfSelectedNode = null;
}

function wfDeleteNode() {
    if (wfSelectedNode && wfEditor) {
        wfEditor.removeNodeId('node-' + wfSelectedNode);
        wfCloseConfig();
    }
}

function wfUpdateNodeName(nodeId, name) {
    if (!wfEditor) return;
    try {
        const nodeEl = document.getElementById('node-' + nodeId);
        if (nodeEl) {
            const titleEl = nodeEl.querySelector('.df-title');
            if (titleEl) titleEl.textContent = name;
        }
        const node = wfEditor.getNodeFromId(nodeId);
        if (node) {
            node.name = name;
            wfEditor.updateNodeDataFromId(nodeId, { ...node.data, displayName: name });
        }
    } catch (_) {}
}

function wfRunWorkflow() {
    if (!wfEditor) { showToast('No workflow loaded'); return; }
    const data = wfEditor.export();
    const nodes = Object.values(data.drawflow?.Home?.data || {});
    if (nodes.length < 2) { showToast('Add at least 2 nodes to run a workflow'); return; }
    const agentNodes = nodes.filter(n => (n.data?.type || n.class || '').startsWith('agent_'));
    let extra = '';
    if (agentNodes.length > 0) {
        const first = agentNodes[0];
        const agentId = (first.data?.type || '').replace('agent_', '');
        extra = `<div class="mt-3 pt-3" style="border-top:1px solid var(--border-default);"><p class="text-[10px] mb-2" style="color:var(--text-secondary);">Test individual agents via Chat:</p><button onclick="launchPrebuiltAgent('${agentId}');document.getElementById('wf-run-modal')?.remove()" class="px-3 py-1.5 text-[10px] font-medium flex items-center gap-1" style="background:var(--accent);color:white;border-radius:var(--radius-sm);"><span class="material-icons-outlined text-xs">chat</span>Chat with ${escapeHtml(first.name || agentId)}</button></div>`;
    }
    const modal = document.createElement('div');
    modal.id = 'wf-run-modal';
    modal.style.cssText = 'position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;';
    modal.innerHTML = `<div onclick="this.parentElement.remove()" style="position:absolute;inset:0;background:rgba(0,0,0,0.5);backdrop-filter:blur(3px);"></div><div class="glass" style="position:relative;width:380px;padding:24px;"><div class="flex items-center gap-2 mb-2"><span class="material-icons-outlined text-lg" style="color:var(--accent);">play_circle</span><h3 class="text-[14px] font-semibold" style="color:var(--text-primary);">Run Workflow</h3></div><p class="text-[12px] mb-1" style="color:var(--text-secondary);">Workflow execution engine is coming in V2.</p><p class="text-[10px]" style="color:var(--text-muted);">Your graph has ${nodes.length} nodes. Backend execution, CRON scheduling, and checkpoint resume will be available in the next release.</p>${extra}<button onclick="this.closest('#wf-run-modal').remove()" class="mt-3 px-3 py-1.5 text-[10px] font-medium" style="background:var(--bg-elevated);border:1px solid var(--border-default);color:var(--text-secondary);border-radius:var(--radius-sm);">Close</button></div>`;
    document.body.appendChild(modal);
}

function wfSave() {
    if (!wfEditor) return;
    localStorage.setItem('aip_workflow', JSON.stringify(wfEditor.export()));
    showToast('Workflow saved');
}

function wfResetDefault() {
    if (!wfEditor) return;
    wfEditor.clear();
    wfEditor.addModule('Home');
    wfEditor.addModule('Data Ingestion');
    wfEditor.addModule('Knowledge Processing');
    wfEditor.addModule('Agent Reasoning');
    wfEditor.addModule('Response Generation');
    wfEditor.addModule('Quality Assurance');
    wfSeedDefault();
    wfGoHome();
    localStorage.removeItem('aip_workflow');
    showToast('Workflow reset to default');
}

function wfExport() {
    if (!wfEditor) return;
    const data = JSON.stringify(wfEditor.export(), null, 2);
    const blob = new Blob([data], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'workflow.json'; a.click();
    URL.revokeObjectURL(url);
    showToast('Workflow exported');
}

let wfZoomLevel = 1;
function wfZoom(action) {
    if (!wfEditor) return;
    if (action === 'in') wfZoomLevel = Math.min(wfZoomLevel + 0.1, 2);
    else if (action === 'out') wfZoomLevel = Math.max(wfZoomLevel - 0.1, 0.3);
    else if (action === 'fit') wfZoomLevel = 1;
    wfEditor.zoom = wfZoomLevel;
    if (typeof wfEditor.zoom_refresh === 'function') {
        wfEditor.zoom_refresh();
    } else {
        const precanvas = wfEditor.precanvas;
        if (precanvas) precanvas.style.transform = `translate(${wfEditor.canvas_x}px, ${wfEditor.canvas_y}px) scale(${wfZoomLevel})`;
    }
    const el = document.getElementById('wf-zoom-level');
    if (el) el.textContent = Math.round(wfZoomLevel * 100) + '%';
}

function wfUpdateNodeCount() {
    const el = document.getElementById('wf-node-count');
    if (!el || !wfEditor) return;
    const exp = wfEditor.export();
    const mod = exp.drawflow?.[wfEditor.module];
    const count = mod?.data ? Object.keys(mod.data).length : 0;
    el.textContent = count + ' node' + (count !== 1 ? 's' : '');
}

function wfFilterPalette(query) {
    const q = query.toLowerCase().trim();
    document.querySelectorAll('.wf-palette-item').forEach(item => {
        const name = (item.dataset.nodeName || '').toLowerCase();
        const type = (item.dataset.nodeType || '').toLowerCase();
        const meta = (item.dataset.nodeMeta || '').toLowerCase();
        item.style.display = (!q || name.includes(q) || type.includes(q) || meta.includes(q)) ? '' : 'none';
    });
    document.querySelectorAll('.wf-palette-cat').forEach(cat => {
        const catName = cat.dataset.wfCat;
        if (!catName) return;
        const items = document.querySelectorAll(`.wf-palette-item[data-wf-cat="${catName}"]`);
        const anyVisible = Array.from(items).some(i => i.style.display !== 'none');
        cat.style.display = anyVisible ? '' : 'none';
    });
}

// =========================================================================
// TOOL TOGGLES (Step 4)
// =========================================================================

function toggleTool(toolId, cardEl) {
    const saved = JSON.parse(localStorage.getItem('aip_tools') || '{}');
    saved[toolId] = !saved[toolId];
    localStorage.setItem('aip_tools', JSON.stringify(saved));

    const enabled = saved[toolId];
    const toggle = cardEl.querySelector('.w-7.h-4');
    const dot = toggle.querySelector('div');
    const iconWrap = cardEl.querySelector('.w-7.h-7');
    const icon = iconWrap.querySelector('.material-icons-outlined');
    toggle.style.background = enabled ? 'var(--accent)' : 'var(--border-default)';
    dot.style.left = enabled ? '14px' : '2px';
    cardEl.style.borderColor = enabled ? 'var(--border-active)' : 'var(--border-default)';
    iconWrap.style.background = enabled ? 'var(--accent-subtle)' : 'var(--bg-elevated)';
    icon.style.color = enabled ? 'var(--accent)' : 'var(--text-muted)';

    const count = Object.values(saved).filter(Boolean).length;
    const countEl = document.getElementById('tools-count');
    if (countEl) countEl.textContent = count + ' active';
}

// =========================================================================
// CONNECTOR CONFIG PANEL
// =========================================================================

var currentConnectorId = null;

const connectorConfigs = {
    dynamics365: { icon: 'cloud', name: 'Dynamics 365', desc: 'Microsoft ERP/CRM platform for vendor records, purchase orders, and financial data.', fields: [
        { label: 'Tenant ID', key: 'tenant_id', type: 'text', placeholder: 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx' },
        { label: 'Client ID', key: 'client_id', type: 'text', placeholder: 'app-registration-client-id' },
        { label: 'Client Secret', key: 'client_secret', type: 'password', placeholder: '••••••••••••' },
        { label: 'Environment URL', key: 'env_url', type: 'url', placeholder: 'https://org.crm.dynamics.com' },
        { label: 'API Version', key: 'api_version', type: 'select', options: ['v9.2', 'v9.1', 'v9.0'] },
        { label: 'Entities to Sync', key: 'entities', type: 'text', placeholder: 'accounts, contacts, opportunities' },
    ]},
    teams: { icon: 'chat', name: 'Microsoft Teams', desc: 'Send notifications, receive messages, and create agent-assisted channels.', fields: [
        { label: 'Incoming Webhook URL', key: 'webhook_url', type: 'url', placeholder: 'https://outlook.office.com/webhook/...' },
        { label: 'Bot Framework App ID', key: 'bot_id', type: 'text', placeholder: 'bot-app-id' },
        { label: 'Bot Secret', key: 'bot_secret', type: 'password', placeholder: '••••••••••••' },
        { label: 'Default Channel', key: 'channel_id', type: 'text', placeholder: '19:abc123...@thread.tacv2' },
        { label: 'Message Format', key: 'msg_format', type: 'select', options: ['Adaptive Card', 'Plain text', 'Markdown'] },
    ]},
    sharepoint: { icon: 'folder_shared', name: 'SharePoint', desc: 'Access document libraries, policy repositories, and knowledge stores.', fields: [
        { label: 'Site URL', key: 'site_url', type: 'url', placeholder: 'https://tenant.sharepoint.com/sites/policies' },
        { label: 'Client ID', key: 'client_id', type: 'text', placeholder: 'sharepoint-app-client-id' },
        { label: 'Client Secret', key: 'client_secret', type: 'password', placeholder: '••••••••••••' },
        { label: 'Document Library', key: 'library', type: 'text', placeholder: 'Shared Documents' },
        { label: 'Sync Direction', key: 'sync_dir', type: 'select', options: ['Read only', 'Read/Write', 'Bidirectional'] },
        { label: 'File Filters', key: 'file_filters', type: 'text', placeholder: '*.pdf, *.docx, *.xlsx' },
    ]},
    outlook: { icon: 'mail', name: 'Outlook / Exchange', desc: 'Trigger agents from inbound emails, send notifications, and manage tasks.', fields: [
        { label: 'Tenant ID', key: 'tenant_id', type: 'text', placeholder: 'azure-ad-tenant-id' },
        { label: 'Client ID', key: 'client_id', type: 'text', placeholder: 'mail-app-client-id' },
        { label: 'Client Secret', key: 'client_secret', type: 'password', placeholder: '••••••••••••' },
        { label: 'Monitored Mailbox', key: 'mailbox', type: 'email', placeholder: 'agent@company.com' },
        { label: 'Auth Method', key: 'auth_type', type: 'select', options: ['OAuth 2.0 (recommended)', 'Basic Auth', 'Service Account'] },
        { label: 'Trigger Rules', key: 'triggers', type: 'text', placeholder: 'subject:contains("procurement"), from:@vendor.com' },
    ]},
    telegram: { icon: 'send', name: 'Telegram Bot', desc: 'Interact with agents via Telegram for mobile-first access.', fields: [
        { label: 'Bot Token', key: 'bot_token', type: 'password', placeholder: '1234567890:ABCdefGHIjkl...' },
        { label: 'Default Chat ID', key: 'chat_id', type: 'text', placeholder: '-1001234567890' },
        { label: 'Webhook Endpoint', key: 'webhook_url', type: 'url', placeholder: 'https://api.company.com/telegram/hook' },
        { label: 'Parse Mode', key: 'parse_mode', type: 'select', options: ['MarkdownV2', 'HTML', 'Plain'] },
    ]},
    whatsapp: { icon: 'forum', name: 'WhatsApp Business', desc: 'Enterprise messaging via WhatsApp Business API.', fields: [
        { label: 'API Key', key: 'api_key', type: 'password', placeholder: 'whatsapp-api-key' },
        { label: 'Phone Number ID', key: 'phone_id', type: 'text', placeholder: '1234567890' },
        { label: 'Business Account ID', key: 'business_id', type: 'text', placeholder: 'business-account-id' },
        { label: 'Verify Token', key: 'verify_token', type: 'password', placeholder: 'webhook-verify-token' },
        { label: 'Template Namespace', key: 'template_ns', type: 'text', placeholder: 'company_notifications' },
    ]},
    smtp: { icon: 'email', name: 'SMTP / Email', desc: 'Send email notifications and reports from agent pipelines.', fields: [
        { label: 'SMTP Host', key: 'smtp_host', type: 'text', placeholder: 'smtp.office365.com' },
        { label: 'Port', key: 'port', type: 'number', placeholder: '587' },
        { label: 'Username', key: 'username', type: 'text', placeholder: 'noreply@company.com' },
        { label: 'Password', key: 'password', type: 'password', placeholder: '••••••••••••' },
        { label: 'Encryption', key: 'tls', type: 'select', options: ['STARTTLS (recommended)', 'SSL/TLS', 'None'] },
        { label: 'From Name', key: 'from_name', type: 'text', placeholder: 'AI Platform Notifications' },
    ]},
    rest_api: { icon: 'api', name: 'REST API', desc: 'Generic HTTP connector for any REST-based service or webhook.', fields: [
        { label: 'Base URL', key: 'base_url', type: 'url', placeholder: 'https://api.internal.company.com/v2' },
        { label: 'Auth Type', key: 'auth_type', type: 'select', options: ['Bearer Token', 'API Key (header)', 'OAuth 2.0', 'Basic Auth', 'None'] },
        { label: 'Auth Credential', key: 'api_key', type: 'password', placeholder: 'sk-... or Bearer token' },
        { label: 'Default Headers', key: 'headers', type: 'textarea', placeholder: '{"Content-Type": "application/json"}' },
        { label: 'Rate Limit', key: 'rate_limit', type: 'text', placeholder: '100 req/min' },
        { label: 'Timeout (ms)', key: 'timeout', type: 'number', placeholder: '15000' },
    ]},
    mqtt: { icon: 'hub', name: 'MQTT', desc: 'IoT and real-time event-driven messaging for sensor and device data.', fields: [
        { label: 'Broker URL', key: 'broker_url', type: 'url', placeholder: 'mqtt://broker.iot.internal:1883' },
        { label: 'Topic Pattern', key: 'topic', type: 'text', placeholder: 'sensors/+/data' },
        { label: 'QoS Level', key: 'qos', type: 'select', options: ['0 - At most once', '1 - At least once', '2 - Exactly once'] },
        { label: 'Client ID', key: 'client_id', type: 'text', placeholder: 'agent-mqtt-client-01' },
        { label: 'Authentication', key: 'auth', type: 'select', options: ['Username/Password', 'Client Certificate', 'None'] },
    ]},
    postgresql: { icon: 'storage', name: 'PostgreSQL', desc: 'Structured data queries, analytics, and metadata storage.', fields: [
        { label: 'Host', key: 'host', type: 'text', placeholder: 'pg.internal.company.com' },
        { label: 'Port', key: 'port', type: 'number', placeholder: '5432' },
        { label: 'Database', key: 'database', type: 'text', placeholder: 'analytics' },
        { label: 'Schema', key: 'schema', type: 'text', placeholder: 'public' },
        { label: 'Username', key: 'username', type: 'text', placeholder: 'agent_readonly' },
        { label: 'Password', key: 'password', type: 'password', placeholder: '••••••••••••' },
        { label: 'SSL Mode', key: 'ssl_mode', type: 'select', options: ['require', 'verify-full', 'prefer', 'disable'] },
        { label: 'Pool Size', key: 'pool_size', type: 'number', placeholder: '20' },
    ]},
    s3: { icon: 'cloud_queue', name: 'AWS S3', desc: 'Cloud object storage for documents, embeddings, and artifacts.', fields: [
        { label: 'Bucket Name', key: 'bucket', type: 'text', placeholder: 'company-data-documents' },
        { label: 'Region', key: 'region', type: 'select', options: ['eu-west-1', 'us-east-1', 'me-south-1', 'ap-southeast-1', 'eu-central-1'] },
        { label: 'Access Key ID', key: 'access_key', type: 'password', placeholder: 'AKIA...' },
        { label: 'Secret Access Key', key: 'secret_key', type: 'password', placeholder: '••••••••••••' },
        { label: 'Prefix / Folder', key: 'prefix', type: 'text', placeholder: 'documents/incoming/' },
        { label: 'Storage Class', key: 'storage_class', type: 'select', options: ['STANDARD', 'INTELLIGENT_TIERING', 'GLACIER'] },
    ]},
    elasticsearch: { icon: 'dns', name: 'Elasticsearch', desc: 'Full-text search and log analytics for enterprise data.', fields: [
        { label: 'Cluster URL', key: 'cluster_url', type: 'url', placeholder: 'https://es.internal:9200' },
        { label: 'Index Pattern', key: 'index', type: 'text', placeholder: 'agent-logs-*' },
        { label: 'API Key', key: 'api_key', type: 'password', placeholder: 'base64-encoded-key' },
        { label: 'Cloud ID', key: 'cloud_id', type: 'text', placeholder: 'deployment:region:id (Elastic Cloud)' },
    ]},
};

function openConnectorConfig(connId) {
    currentConnectorId = connId;
    const cfg = connectorConfigs[connId];
    if (!cfg) return;

    const modal = document.getElementById('connector-config-modal');
    const icon = document.getElementById('cc-icon');
    const title = document.getElementById('cc-title');
    const body = document.getElementById('cc-body');

    icon.textContent = cfg.icon;
    title.textContent = cfg.name;

    const saved = JSON.parse(localStorage.getItem('aip_connectors') || '{}');
    const savedCfg = saved[connId] || {};

    let html = `<p class="text-[10px] mb-2" style="color:var(--text-muted);">${cfg.desc || ''}</p>`;
    html += `<div class="flex items-center justify-between p-2" style="background:var(--bg-elevated);border-radius:var(--radius);">
        <div class="flex items-center gap-2"><span class="material-icons-outlined text-xs" style="color:var(--text-muted);">power</span><span class="text-[10px] font-medium" style="color:var(--text-secondary);">Connection Status</span></div>
        <label class="flex items-center gap-1.5 cursor-pointer"><span class="text-[10px] font-medium" style="color:${savedCfg.enabled ? 'var(--success)' : 'var(--text-muted);'};">${savedCfg.enabled ? 'Connected' : 'Disabled'}</span>
        <div onclick="toggleConnectorStatus(this)" class="w-7 h-4 rounded-full relative cursor-pointer" style="background:${savedCfg.enabled ? 'var(--accent)' : 'var(--border-default)'};">
            <div class="w-3 h-3 rounded-full bg-white absolute top-0.5 transition-all" style="left:${savedCfg.enabled ? '14px' : '2px'};"></div>
        </div></label>
    </div>`;

    cfg.fields.forEach(f => {
        const val = savedCfg[f.key] || '';
        if (f.type === 'select') {
            html += `<div class="wf-config-field"><label>${f.label}</label><select data-field="${f.key}">${(f.options||[]).map(o => `<option${val===o?' selected':''}>${o}</option>`).join('')}</select></div>`;
        } else if (f.type === 'textarea') {
            html += `<div class="wf-config-field"><label>${f.label}</label><textarea data-field="${f.key}" rows="2" placeholder="${f.placeholder || ''}" style="resize:none;font-family:'JetBrains Mono',monospace;font-size:9px;">${val}</textarea></div>`;
        } else {
            html += `<div class="wf-config-field"><label>${f.label}</label><input type="${f.type || 'text'}" data-field="${f.key}" value="${val}" placeholder="${f.placeholder || ''}"></div>`;
        }
    });

    body.innerHTML = html;
    modal.classList.remove('hidden');
    modal.style.display = 'flex';
}

function closeConnectorConfig() {
    const modal = document.getElementById('connector-config-modal');
    modal.classList.add('hidden');
    modal.style.display = '';
    currentConnectorId = null;
}

function toggleConnectorStatus(el) {
    const isOn = el.style.background.includes('accent');
    el.style.background = isOn ? 'var(--border-default)' : 'var(--accent)';
    el.querySelector('div').style.left = isOn ? '2px' : '14px';
    const label = el.parentElement.querySelector('span');
    label.textContent = isOn ? 'Disabled' : 'Connected';
    label.style.color = isOn ? 'var(--text-muted)' : 'var(--success)';
}

function saveConnector() {
    if (!currentConnectorId) return;
    const saved = JSON.parse(localStorage.getItem('aip_connectors') || '{}');
    const cfg = {};
    document.querySelectorAll('#cc-body [data-field]').forEach(el => {
        cfg[el.dataset.field] = el.value;
    });
    const toggle = document.querySelector('#cc-body [onclick*="toggleConnectorStatus"]');
    cfg.enabled = toggle ? toggle.style.background.includes('accent') : false;
    saved[currentConnectorId] = cfg;
    localStorage.setItem('aip_connectors', JSON.stringify(saved));
    showToast('Connector configuration saved');
}

function testConnector() {
    const btn = event.target.closest('button');
    const orig = btn.innerHTML;
    btn.innerHTML = '<span class="material-icons-outlined text-xs tool-running">sync</span>Testing...';
    btn.disabled = true;
    const latency = 200 + Math.floor(Math.random() * 300);
    setTimeout(() => {
        btn.innerHTML = orig;
        btn.disabled = false;
        showToast(`Connection successful · ${latency}ms latency`);
    }, 800 + Math.floor(Math.random() * 1200));
}

function addConnectorToWorkflow() {
    if (!currentConnectorId || !wfEditor) {
        showToast('Open the workflow page first');
        return;
    }
    const cfg = connectorConfigs[currentConnectorId];
    if (!cfg) return;
    wfEditor.changeModule(wfCurrentModule);
    wfEditor.addNode('conn_' + currentConnectorId, 1, 1, 200, 200, '', {type: 'conn_' + currentConnectorId}, wfNodeHtml(cfg.icon, cfg.name, 'connector'));
    showToast(cfg.name + ' added to workflow');
    closeConnectorConfig();
}

// =========================================================================
// WORKSPACE (Task delegation)
// =========================================================================

var currentTaskId = null;

var _missionTemplates = [
    { title: 'Market Analysis', objective: 'Conduct a comprehensive market analysis for [sector]. Identify top 5 competitors, current trends, SWOT analysis, and provide a strategic recommendation report.' },
    { title: 'Compliance Audit', objective: 'Review all recent procurement documents and contracts for compliance with ISO 27001 and GDPR requirements. Flag any non-conformities and produce a remediation report.' },
    { title: 'Data Quality Report', objective: 'Scan the indexed knowledge base. Evaluate document quality, identify duplicates, check embedding coverage, and produce a data quality scorecard with improvement recommendations.' },
    { title: 'Executive Briefing', objective: 'Compile the latest intelligence feed analysis into a concise executive briefing. Cover key geopolitical risks, market signals, and recommended actions for leadership review.' },
];

function prefillMission(idx) {
    const t = _missionTemplates[idx];
    if (!t) return;
    openTaskModal();
    const titleEl = document.getElementById('task-title');
    const descEl = document.getElementById('task-desc');
    if (titleEl) titleEl.value = t.title;
    if (descEl) descEl.value = t.objective;
}

function _populateTaskAgentSelect() {
    const sel = document.getElementById('task-agent');
    if (!sel) return;
    const prebuilt = [
        { id: '', name: 'Auto-select (best fit)' },
        { id: 'procurement', name: 'Procurement Agent' },
        { id: 'rag', name: 'RAG Agent (default)' },
    ];
    const custom = JSON.parse(localStorage.getItem('aip_agents') || '[]');
    let html = '';
    prebuilt.forEach(a => { html += `<option value="${a.id}">${escapeHtml(a.name)}</option>`; });
    custom.forEach(a => { html += `<option value="${escapeHtml(a.id)}">${escapeHtml(a.name)} · custom</option>`; });
    sel.innerHTML = html;
}

async function loadWorkspace() {
    try {
        const api = await import('./api.js');
        const data = await api.listTasks(30);
        const tasks = data.tasks || [];
        const list = document.getElementById('ws-task-list');
        const activeEl = document.getElementById('ws-active-count');
        const compEl = document.getElementById('ws-completed-count');
        const stepsEl = document.getElementById('ws-steps-count');
        const avgEl = document.getElementById('ws-avg-duration');

        const active = tasks.filter(t => t.status === 'running' || t.status === 'planning');
        const completed = tasks.filter(t => t.status === 'completed');
        if (activeEl) activeEl.textContent = active.length;
        if (compEl) compEl.textContent = completed.length;

        const totalSteps = tasks.reduce((sum, t) => {
            if (Array.isArray(t.steps)) return sum + t.steps.length;
            return sum;
        }, 0);
        if (stepsEl) stepsEl.textContent = totalSteps;

        const durations = completed.filter(t => t.total_duration_ms > 0).map(t => t.total_duration_ms);
        if (avgEl) {
            if (durations.length > 0) {
                const avg = durations.reduce((a, b) => a + b, 0) / durations.length;
                avgEl.textContent = avg < 1000 ? Math.round(avg) + 'ms' : (avg / 1000).toFixed(1) + 's';
            } else {
                avgEl.textContent = '—';
            }
        }

        if (!list || tasks.length === 0) return;

        const statusColors = { pending: 'var(--text-muted)', planning: 'var(--warning)', running: 'var(--accent)', completed: 'var(--success)', failed: '#ef4444' };
        const statusLabels = { pending: 'Pending', planning: 'Planning…', running: 'Running…', completed: 'Done', failed: 'Failed' };
        list.innerHTML = tasks.map(t => `
            <div class="t-card p-2.5 cursor-pointer" style="border-radius:var(--radius);" onclick="selectTask('${t.id}')">
                <div class="flex items-center justify-between mb-0.5">
                    <p class="text-[11px] font-semibold truncate" style="color:var(--text-primary);max-width:180px;">${escapeHtml(t.title)}</p>
                    <span class="text-[8px] font-medium px-1 py-0.5" style="color:${statusColors[t.status] || 'var(--text-muted)'};background:${statusColors[t.status] || 'var(--text-muted)'}15;border-radius:3px;">${statusLabels[t.status] || t.status}</span>
                </div>
                <p class="text-[9px] truncate" style="color:var(--text-muted);">${escapeHtml(t.description)}</p>
                ${t.progress > 0 && t.progress < 100 ? `<div class="w-full h-1 rounded-full mt-1" style="background:var(--border-default);"><div class="h-full rounded-full" style="background:var(--accent);width:${t.progress}%;"></div></div>` : ''}
                ${t.created_at ? `<p class="text-[8px] mt-1 font-mono" style="color:var(--text-muted);">${new Date(t.created_at).toLocaleString()}</p>` : ''}
            </div>`).join('');
    } catch (e) {
        console.error('loadWorkspace failed', e);
    }
}

async function selectTask(taskId) {
    currentTaskId = taskId;
    try {
        const api = await import('./api.js');
        const task = await api.getTask(taskId);
        const detail = document.getElementById('ws-task-detail');
        if (!detail) return;

        const steps = task.steps || [];
        const statusColors = { pending: 'var(--text-muted)', running: 'var(--accent)', completed: 'var(--success)', failed: '#ef4444' };
        const statusIcons = { pending: 'schedule', running: 'sync', completed: 'check_circle', failed: 'error' };

        detail.innerHTML = `
            <div class="flex items-center justify-between mb-3">
                <div>
                    <h3 class="text-[13px] font-semibold" style="color:var(--text-primary);">${escapeHtml(task.title)}</h3>
                    <p class="text-[10px]" style="color:var(--text-muted);">${escapeHtml(task.description)}</p>
                </div>
                ${task.status === 'pending' ? `<button onclick="runTask('${taskId}')" class="px-2.5 py-1.5 text-[10px] font-medium text-white flex items-center gap-1" style="background:var(--accent);border-radius:var(--radius-sm);"><span class="material-icons-outlined text-xs">play_arrow</span>Execute</button>` : ''}
            </div>
            <div class="space-y-1.5" id="ws-steps-timeline">
                ${steps.length ? steps.map(s => `
                    <div class="flex items-start gap-2 p-2" style="background:var(--bg-elevated);border-radius:var(--radius-sm);">
                        <span class="material-icons-outlined text-sm mt-0.5 ${s.status === 'running' ? 'tool-running' : ''}" style="color:${statusColors[s.status] || 'var(--text-muted)'};">${statusIcons[s.status] || 'schedule'}</span>
                        <div class="flex-1 min-w-0">
                            <p class="text-[11px] font-medium" style="color:var(--text-primary);">${escapeHtml(s.title)}</p>
                            ${s.result ? `<p class="text-[9px] mt-0.5 line-clamp-3" style="color:var(--text-muted);">${escapeHtml(s.result.substring(0, 200))}...</p>` : ''}
                            ${s.duration_ms ? `<span class="text-[8px] font-mono" style="color:var(--text-muted);">${s.duration_ms}ms</span>` : ''}
                        </div>
                    </div>
                `).join('') : '<p class="text-[10px] text-center py-4" style="color:var(--text-muted);">Task not yet executed</p>'}
            </div>
            ${task.artifacts && task.artifacts.report ? `
                <div class="mt-3 p-3" style="background:var(--bg-elevated);border-radius:var(--radius);border:1px solid var(--border-default);">
                    <h4 class="text-[10px] font-semibold uppercase tracking-wider mb-1.5" style="color:var(--text-muted);">Final Report</h4>
                    <div class="prose-chat text-[11px]" style="color:var(--text-secondary);">${renderMarkdown(task.artifacts.report)}</div>
                </div>` : ''}`;
    } catch (_) {}
}

async function runTask(taskId) {
    const api = await import('./api.js');
    const timeline = document.getElementById('ws-steps-timeline');

    api.streamTaskRun(taskId,
        (event) => {
            if (!timeline) return;
            if (event.type === 'task_plan') {
                const steps = event.steps || [];
                timeline.innerHTML = steps.map(s => `
                    <div class="flex items-start gap-2 p-2" style="background:var(--bg-elevated);border-radius:var(--radius-sm);" id="ws-step-${s.id}">
                        <span class="material-icons-outlined text-sm mt-0.5" style="color:var(--text-muted);">schedule</span>
                        <div class="flex-1"><p class="text-[11px] font-medium" style="color:var(--text-primary);">${escapeHtml(s.title)}</p></div>
                    </div>`).join('');
            } else if (event.type === 'task_step') {
                const el = document.getElementById('ws-step-' + event.step.id);
                if (el) {
                    const icon = el.querySelector('.material-icons-outlined');
                    icon.textContent = 'sync';
                    icon.classList.add('tool-running');
                    icon.style.color = 'var(--accent)';
                }
            } else if (event.type === 'task_step_complete') {
                const el = document.getElementById('ws-step-' + event.step.id);
                if (el) {
                    const icon = el.querySelector('.material-icons-outlined');
                    icon.textContent = event.step.status === 'completed' ? 'check_circle' : 'error';
                    icon.classList.remove('tool-running');
                    icon.style.color = event.step.status === 'completed' ? 'var(--success)' : '#ef4444';
                    const div = el.querySelector('.flex-1');
                    div.innerHTML += `<p class="text-[9px] mt-0.5" style="color:var(--text-muted);">${escapeHtml((event.step.result || '').substring(0, 200))}</p><span class="text-[8px] font-mono" style="color:var(--text-muted);">${event.step.duration_ms}ms</span>`;
                }
            } else if (event.type === 'task_complete') {
                showToast('Mission completed');
                selectTask(taskId);
                loadWorkspace();
            }
        },
        () => {},
        (err) => showToast('Task error: ' + err.message)
    );
}

function openTaskModal() {
    const modal = document.getElementById('task-modal');
    if (!modal) return;
    if (modal.parentElement !== document.body) document.body.appendChild(modal);
    modal.classList.remove('hidden');
    _populateTaskAgentSelect();
}
function closeTaskModal() {
    const modal = document.getElementById('task-modal');
    if (modal) modal.classList.add('hidden');
}

async function submitTask() {
    const title = document.getElementById('task-title').value.trim();
    const desc = document.getElementById('task-desc').value.trim();
    const agentId = document.getElementById('task-agent')?.value || null;
    if (!desc) { showToast('Please describe the mission objective'); return; }
    try {
        const api = await import('./api.js');
        const task = await api.createTask({ title: title || desc.substring(0, 80), description: desc, agent_id: agentId || undefined });
        closeTaskModal();
        document.getElementById('task-title').value = '';
        document.getElementById('task-desc').value = '';
        showToast('Mission launched — planning in progress…');
        loadWorkspace();
        runTask(task.id);
    } catch (e) { showToast('Error: ' + e.message); }
}

// =========================================================================
// AGENT QUALITY (ProofAgent-style evaluation)
// =========================================================================

var qualityChart = null;

function populateQualityAgentSelect() {
    const sel = document.getElementById('quality-agent-select');
    if (!sel) return;
    const saved = localStorage.getItem('aip_quality_agent_id') || 'rag';
    const prebuilt = [
        { id: 'rag', name: 'Platform RAG (default)' },
        { id: 'procurement', name: 'Procurement Agent' },
        { id: 'legal', name: 'Legal Review' },
        { id: 'hr', name: 'HR Assistant' },
        { id: 'finance', name: 'Financial Analyst' },
    ];
    const custom = JSON.parse(localStorage.getItem('aip_agents') || '[]');
    let html = '';
    prebuilt.forEach(a => {
        html += `<option value="${a.id}">${escapeHtml(a.name)}</option>`;
    });
    custom.forEach(a => {
        html += `<option value="${escapeHtml(a.id)}">${escapeHtml(a.name)} · custom</option>`;
    });
    sel.innerHTML = html;
    const ok = [...sel.options].some(o => o.value === saved);
    sel.value = ok ? saved : 'rag';
}

function getQualityAgentId() {
    const sel = document.getElementById('quality-agent-select');
    if (sel && sel.value) return sel.value;
    return localStorage.getItem('aip_quality_agent_id') || 'rag';
}

function onQualityAgentChange() {
    const sel = document.getElementById('quality-agent-select');
    if (sel) localStorage.setItem('aip_quality_agent_id', sel.value);
    loadQualityPage();
}

function _updateQualityContextStatus() {
    const el = document.getElementById('quality-context-status');
    if (!el) return;
    let ctx = null;
    try { ctx = JSON.parse(localStorage.getItem('aip_last_eval_context') || 'null'); } catch (_) {}
    if (ctx && ctx.query && ctx.response) {
        const preview = ctx.query.length > 60 ? ctx.query.substring(0, 60) + '…' : ctx.query;
        el.innerHTML = `<p class="text-[9px]" style="color:var(--success);"><span class="material-icons-outlined text-[10px] align-middle mr-0.5">check_circle</span> Ready — last chat: "<em>${escapeHtml(preview)}</em>" (agent: ${escapeHtml(ctx.agent_id || 'rag')})</p>`;
    } else {
        el.innerHTML = '<p class="text-[9px]" style="color:var(--warning);"><span class="material-icons-outlined text-[10px] align-middle mr-0.5">warning</span> No chat context available. Go to <strong>Execution</strong> and chat with an agent first.</p>';
    }
}

function _showEmptyRadar() {
    const container = document.getElementById('quality-radar-container');
    if (!container) return;
    const canvas = document.getElementById('quality-radar');
    if (canvas && typeof Chart !== 'undefined') {
        const dims = ['task_success','relevance','instruction_following','coherence','hallucination','tone','conciseness','safety','policy','drift','manipulation','tool_use'];
        const labels = ['Task','Relev.','Instr.','Coher.','Halluc.','Tone','Conc.','Safety','Policy','Drift','Manip.','Tool'];
        if (qualityChart) qualityChart.destroy();
        qualityChart = new Chart(canvas, {
            type: 'radar',
            data: { labels, datasets: [{ data: dims.map(() => 0), backgroundColor: 'rgba(0,188,212,0.05)', borderColor: 'rgba(0,188,212,0.15)', pointRadius: 0, borderWidth: 1 }] },
            options: {
                responsive: false,
                plugins: { legend: { display: false } },
                scales: { r: { beginAtZero: true, max: 100, ticks: { display: false, stepSize: 25 }, grid: { color: 'rgba(255,255,255,0.06)' }, angleLines: { color: 'rgba(255,255,255,0.06)' }, pointLabels: { color: 'rgba(255,255,255,0.25)', font: { size: 8, family: 'Inter' } } } }
            }
        });
    }
}

async function loadQualityPage() {
    populateQualityAgentSelect();
    _updateQualityContextStatus();
    try {
        const api = await import('./api.js?v=25');
        const aid = getQualityAgentId();
        const data = await api.getLatestEval(aid);
        if (data.evaluation) {
            renderQualityScores(data.evaluation);
        } else {
            const compositeEl = document.getElementById('quality-composite');
            if (compositeEl) compositeEl.textContent = '—';
            ['task_success','relevance','instruction_following','coherence','hallucination','tone','conciseness','safety','policy','drift','manipulation','tool_use'].forEach(d => {
                const bar = document.querySelector(`[data-quality-bar="${d}"]`);
                const label = document.querySelector(`[data-quality-score="${d}"]`);
                if (bar) bar.style.width = '0%';
                if (label) label.textContent = '—';
            });
            _showEmptyRadar();
            const claimsEl = document.getElementById('quality-claims');
            if (claimsEl) claimsEl.innerHTML = '<p class="text-[10px]" style="color:var(--text-muted);">Run an evaluation to see claim audit results.</p>';
        }

        const hist = await api.getEvalHistory(aid, 10);
        renderEvalHistory(hist.evaluations || []);
    } catch (e) {
        console.error('loadQualityPage failed', e);
        _showEmptyRadar();
    }
}

function renderQualityScores(evaluation) {
    const scores = evaluation.scores || {};
    const dims = ['task_success','relevance','instruction_following','coherence','hallucination','tone','conciseness','safety','policy','drift','manipulation','tool_use'];

    dims.forEach(d => {
        const bar = document.querySelector(`[data-quality-bar="${d}"]`);
        const label = document.querySelector(`[data-quality-score="${d}"]`);
        if (bar) bar.style.width = (scores[d] || 0) + '%';
        if (label) label.textContent = (scores[d] || 0);
    });

    const compositeEl = document.getElementById('quality-composite');
    if (compositeEl) compositeEl.textContent = evaluation.composite_score?.toFixed(1) || '—';

    renderRadarChart(scores);

    if (evaluation.claim_audit) {
        const claimsEl = document.getElementById('quality-claims');
        if (claimsEl) {
            const claims = evaluation.claim_audit.claims || [];
            claimsEl.innerHTML = claims.map(c => `
                <div class="flex items-start gap-1.5 p-1.5" style="background:var(--bg-elevated);border-radius:var(--radius-xs);">
                    <span class="material-icons-outlined text-xs mt-0.5" style="color:${c.supported ? 'var(--success)' : 'var(--warning)'};">${c.supported ? 'check_circle' : 'warning'}</span>
                    <p class="text-[9px]" style="color:var(--text-secondary);">${escapeHtml(c.claim)}</p>
                </div>
            `).join('') || '<p class="text-[10px]" style="color:var(--text-muted);">No claims extracted</p>';
        }
    }
}

function renderRadarChart(scores) {
    const canvas = document.getElementById('quality-radar');
    if (!canvas || typeof Chart === 'undefined') return;

    const labels = ['Task Success','Relevance','Instruct.','Coherence','Halluc.','Tone','Concise.','Safety','Policy','Drift','Manip.','Tool Use'];
    const dims = ['task_success','relevance','instruction_following','coherence','hallucination','tone','conciseness','safety','policy','drift','manipulation','tool_use'];
    const values = dims.map(d => scores[d] || 0);

    if (qualityChart) qualityChart.destroy();

    const accentRgb = '0, 188, 212';
    qualityChart = new Chart(canvas, {
        type: 'radar',
        data: {
            labels,
            datasets: [{
                data: values,
                backgroundColor: `rgba(${accentRgb}, 0.15)`,
                borderColor: `rgba(${accentRgb}, 0.8)`,
                pointBackgroundColor: `rgba(${accentRgb}, 1)`,
                pointRadius: 3,
                pointHoverRadius: 5,
                borderWidth: 1.5,
            }]
        },
        options: {
            responsive: false,
            plugins: { legend: { display: false } },
            scales: {
                r: {
                    beginAtZero: true,
                    max: 100,
                    ticks: { display: false, stepSize: 25 },
                    grid: { color: 'rgba(255,255,255,0.06)' },
                    angleLines: { color: 'rgba(255,255,255,0.06)' },
                    pointLabels: { color: 'rgba(255,255,255,0.5)', font: { size: 9, family: 'Inter' } },
                }
            }
        }
    });
}

function renderEvalHistory(evaluations) {
    const el = document.getElementById('quality-history');
    if (!el) return;
    if (!evaluations.length) {
        el.innerHTML = '<p class="text-[10px]" style="color:var(--text-muted);">No evaluations recorded yet for this agent.</p>';
        return;
    }
    el.innerHTML = evaluations.map(e => `
        <div class="flex items-center justify-between p-1.5" style="background:var(--bg-elevated);border-radius:var(--radius-xs);">
            <span class="text-[9px] font-mono" style="color:var(--text-muted);">${e.created_at ? new Date(e.created_at).toLocaleString() : '—'}</span>
            <span class="text-[10px] font-bold" style="color:var(--accent);">${e.composite_score != null ? Number(e.composite_score).toFixed(1) : '—'}</span>
        </div>
    `).join('');
}

async function triggerManualEval() {
    const api = await import('./api.js?v=25');
    const agentId = getQualityAgentId();
    let ctx = null;
    try {
        ctx = JSON.parse(localStorage.getItem('aip_last_eval_context') || 'null');
    } catch (_) {}
    if (!ctx || !ctx.query || !ctx.response) {
        showToast('No chat to evaluate. Go to Execution (step 6), chat with an agent, then come back here.');
        return;
    }
    const btn = document.getElementById('quality-run-btn');
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="material-icons-outlined text-xs tool-running">sync</span> Evaluating…'; }
    try {
        await api.evaluateResponse({
            query: ctx.query,
            response: ctx.response,
            agent_id: agentId,
            system_prompt: savedSystemPrompt || '',
        });
        showToast('Evaluation complete — scores updated');
        await loadQualityPage();
    } catch (e) {
        showToast('Evaluation failed: ' + (e.message || e));
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '<span class="material-icons-outlined text-xs">play_arrow</span>Run Evaluation'; }
    }
}

// =========================================================================
// INTELLIGENCE DASHBOARD
// =========================================================================

var sentimentChart = null;
var entityChart = null;

async function loadIntelligenceDashboard() {
    try {
        const api = await import('./api.js');
        const data = await api.getIntelDashboard();
        const kpis = data.kpis || {};
        const el = (id) => document.getElementById(id);
        if (el('intel-total-articles')) el('intel-total-articles').textContent = kpis.total_articles || 0;
        if (el('intel-active-feeds')) el('intel-active-feeds').textContent = kpis.active_feeds || 0;
        if (el('intel-high-risk')) el('intel-high-risk').textContent = kpis.high_risk || 0;
        if (el('intel-analyzed')) el('intel-analyzed').textContent = kpis.analyzed || 0;

        requestAnimationFrame(() => {
            renderSentimentChart(data.sentiment || {});
            renderEntityChart(data.top_entities || []);
        });
        renderArticles(data.articles || []);
    } catch (e) {
        console.error('Intelligence dashboard failed', e);
        if (typeof showToast === 'function') {
            showToast('Intelligence: impossible de charger le tableau de bord — ' + (e.message || 'erreur réseau'));
        }
    }
}

function _intelChartWidth(canvas) {
    const box = canvas ? canvas.parentElement : null;
    const raw = box ? box.clientWidth : 0;
    return raw > 0 ? Math.max(160, raw) : 400;
}

function renderSentimentChart(sentiment) {
    const canvas = document.getElementById('intel-sentiment-chart');
    if (!canvas || typeof Chart === 'undefined') return;
    if (sentimentChart) sentimentChart.destroy();
    sentimentChart = null;
    canvas.removeAttribute('style');

    const vals = [sentiment.positive || 0, sentiment.negative || 0, sentiment.neutral || 0, sentiment.mixed || 0];
    const total = vals.reduce((a, b) => a + b, 0);
    if (total === 0) {
        const box = canvas.parentElement;
        if (box) box.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;"><p style="color:var(--text-muted);font-size:10px;text-align:center;">No sentiment data yet.<br>Run analysis to populate.</p></div>';
        return;
    }

    const w = _intelChartWidth(canvas);
    canvas.width = w;
    canvas.height = 200;
    sentimentChart = new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels: ['Positive', 'Negative', 'Neutral', 'Mixed'],
            datasets: [{
                data: vals,
                backgroundColor: ['rgba(16,185,129,0.7)', 'rgba(239,68,68,0.7)', 'rgba(148,163,184,0.5)', 'rgba(245,158,11,0.7)'],
                borderWidth: 0,
            }]
        },
        options: {
            responsive: false,
            maintainAspectRatio: false,
            layout: { padding: 6 },
            plugins: { legend: { position: 'right', labels: { color: 'rgba(255,255,255,0.5)', font: { size: 10 }, boxWidth: 12 } } },
            cutout: '55%',
        }
    });
}

function renderEntityChart(entities) {
    const canvas = document.getElementById('intel-entity-chart');
    if (!canvas || typeof Chart === 'undefined') return;
    if (entityChart) entityChart.destroy();
    entityChart = null;
    canvas.removeAttribute('style');

    if (!entities || !entities.length) {
        const box = canvas.parentElement;
        if (box) box.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;"><p style="color:var(--text-muted);font-size:10px;text-align:center;">No entities extracted yet.<br>Run analysis to populate.</p></div>';
        return;
    }

    const w = _intelChartWidth(canvas);
    canvas.width = w;
    canvas.height = 200;
    entityChart = new Chart(canvas, {
        type: 'bar',
        data: {
            labels: entities.slice(0, 10).map(e => e.name),
            datasets: [{
                data: entities.slice(0, 10).map(e => e.count),
                backgroundColor: 'rgba(0,188,212,0.6)',
                borderRadius: 3,
            }]
        },
        options: {
            responsive: false,
            maintainAspectRatio: false,
            indexAxis: 'y',
            layout: { padding: 4 },
            plugins: { legend: { display: false } },
            scales: {
                x: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: 'rgba(255,255,255,0.4)', font: { size: 9 } } },
                y: { grid: { display: false }, ticks: { color: 'rgba(255,255,255,0.5)', font: { size: 9 } } },
            }
        }
    });
}

function renderArticles(articles) {
    const el = document.getElementById('intel-articles');
    if (!el) return;
    if (!articles || !articles.length) {
        el.innerHTML = '<p class="text-[10px] text-center py-4" style="color:var(--text-muted);">No articles analyzed yet. Add RSS feeds and run analysis.</p>';
        return;
    }
    const riskColors = { low: 'var(--success)', medium: 'var(--warning)', high: '#ef4444', critical: '#dc2626' };
    const sentColors = { positive: 'var(--success)', negative: '#ef4444', neutral: 'var(--text-muted)', mixed: 'var(--warning)' };
    el.innerHTML = articles.map(a => `
        <div class="flex items-start gap-2.5 p-2" style="background:var(--bg-elevated);border-radius:var(--radius-sm);">
            <div class="flex-1 min-w-0">
                <div class="flex items-center gap-1.5 mb-0.5">
                    <a href="${a.url}" target="_blank" class="text-[11px] font-medium truncate" style="color:var(--text-primary);">${escapeHtml(a.title)}</a>
                </div>
                ${a.summary ? `<p class="text-[9px] line-clamp-2" style="color:var(--text-muted);">${escapeHtml(a.summary)}</p>` : ''}
            </div>
            <div class="flex items-center gap-1.5 shrink-0">
                <span class="px-1.5 py-0.5 text-[8px] font-medium" style="background:${sentColors[a.sentiment] || 'var(--text-muted)'}15;color:${sentColors[a.sentiment] || 'var(--text-muted)'};border-radius:var(--radius-xs);">${a.sentiment || 'n/a'}</span>
                <span class="px-1.5 py-0.5 text-[8px] font-medium" style="background:${riskColors[a.risk_level] || 'var(--text-muted)'}15;color:${riskColors[a.risk_level] || 'var(--text-muted)'};border-radius:var(--radius-xs);">${a.risk_level || 'n/a'}</span>
                ${a.safety_flag !== 'clear' ? `<span class="material-icons-outlined text-xs" style="color:var(--warning);">shield</span>` : ''}
            </div>
        </div>
    `).join('');
}

async function runBatchAnalysis() {
    const bar = document.getElementById('intel-batch-bar');
    const progress = document.getElementById('intel-batch-progress');
    const status = document.getElementById('intel-batch-status');
    if (bar) bar.classList.remove('hidden');

    const api = await import('./api.js');
    api.streamBatchAnalysis(
        (event) => {
            if (event.type === 'batch_error') {
                showToast('Batch error: ' + (event.message || 'unknown'));
                if (bar) bar.classList.add('hidden');
                return;
            }
            if (progress) progress.style.width = (event.progress || 0) + '%';
            if (status) status.textContent = event.type === 'batch_complete' ? 'Complete' : `${event.type.replace('batch_', '')}...`;
            if (event.type === 'batch_complete') {
                setTimeout(() => { if (bar) bar.classList.add('hidden'); loadIntelligenceDashboard(); }, 1500);
            }
        },
        () => {},
        (err) => { showToast('Batch error: ' + (err.message || err)); if (bar) bar.classList.add('hidden'); }
    );
}

function openIntelConfig() {
    const modal = document.getElementById('intel-config-modal');
    if (!modal) return;
    if (modal.parentElement !== document.body) document.body.appendChild(modal);
    modal.classList.remove('hidden');
    loadIntelConfigData();
}
function closeIntelConfig() {
    const modal = document.getElementById('intel-config-modal');
    if (modal) modal.classList.add('hidden');
}

async function loadIntelConfigData() {
    try {
        const api = await import('./api.js');
        const [feeds, targets, filters] = await Promise.all([api.listFeeds(), api.listTargets(), api.listSafetyFilters()]);

        const feedsList = document.getElementById('intel-feeds-list');
        if (feedsList) feedsList.innerHTML = (feeds.feeds || []).map(f => `
            <div class="flex items-center justify-between p-1.5" style="background:var(--bg-elevated);border-radius:var(--radius-xs);">
                <div class="flex-1 min-w-0 mr-2"><p class="text-[10px] font-medium" style="color:var(--text-primary);">${escapeHtml(f.name)}</p><p class="text-[8px] font-mono truncate" style="color:var(--text-muted);max-width:280px;">${escapeHtml(f.url)}</p></div>
                <div class="flex items-center gap-1.5 shrink-0">
                    <span class="text-[8px] font-mono" style="color:var(--text-muted);">${f.article_count || 0} art.</span>
                    <span class="w-1.5 h-1.5 rounded-full" style="background:${f.active ? 'var(--success)' : 'var(--text-muted)'};"></span>
                    <button onclick="removeIntelFeed('${f.id}')" class="w-4 h-4 flex items-center justify-center" style="color:var(--text-muted);border-radius:var(--radius-xs);" title="Remove feed"><span class="material-icons-outlined text-[10px]">close</span></button>
                </div>
            </div>`).join('') || '<p class="text-[9px]" style="color:var(--text-muted);">No feeds configured</p>';

        const targetsList = document.getElementById('intel-targets-list');
        if (targetsList) targetsList.innerHTML = (targets.targets || []).map(t => `
            <div class="p-1.5" style="background:var(--bg-elevated);border-radius:var(--radius-xs);">
                <p class="text-[10px] font-medium" style="color:var(--text-primary);">${escapeHtml(t.name)}</p>
                <p class="text-[8px]" style="color:var(--text-muted);">${escapeHtml(t.description).substring(0, 100)}</p>
            </div>`).join('') || '<p class="text-[9px]" style="color:var(--text-muted);">No targets configured</p>';

        const filtersList = document.getElementById('intel-filters-list');
        if (filtersList) filtersList.innerHTML = (filters.filters || []).map(f => `
            <div class="p-1.5" style="background:var(--bg-elevated);border-radius:var(--radius-xs);">
                <p class="text-[10px] font-medium" style="color:var(--text-primary);">${escapeHtml(f.name)}</p>
                <p class="text-[8px]" style="color:var(--text-muted);">${escapeHtml(f.prompt_template).substring(0, 80)}</p>
            </div>`).join('') || '<p class="text-[9px]" style="color:var(--text-muted);">No filters configured</p>';
    } catch (e) {
        console.error('Intelligence config load failed', e);
        if (typeof showToast === 'function') {
            showToast('Configuration: ' + (e.message || 'erreur de chargement'));
        }
    }
}

async function addFeed() {
    const name = document.getElementById('intel-feed-name').value.trim();
    const url = document.getElementById('intel-feed-url').value.trim();
    if (!name || !url) { showToast('Name and URL required'); return; }
    try {
        const api = await import('./api.js');
        await api.createFeed({ name, url });
        showToast('Feed added');
        document.getElementById('intel-feed-name').value = '';
        document.getElementById('intel-feed-url').value = '';
        loadIntelConfigData();
    } catch (e) { showToast('Error: ' + e.message); }
}

async function addTarget() {
    const name = document.getElementById('intel-target-name').value.trim();
    const desc = document.getElementById('intel-target-desc').value.trim();
    if (!name || !desc) { showToast('Name and description required'); return; }
    try {
        const api = await import('./api.js');
        await api.createTarget({ name, description: desc });
        showToast('Target added');
        document.getElementById('intel-target-name').value = '';
        document.getElementById('intel-target-desc').value = '';
        loadIntelConfigData();
    } catch (e) { showToast('Error: ' + e.message); }
}

async function addSafetyFilter() {
    const name = document.getElementById('intel-filter-name').value.trim();
    const prompt = document.getElementById('intel-filter-prompt').value.trim();
    const severityEl = document.getElementById('intel-filter-severity');
    const severity = severityEl ? severityEl.value : 'flag';
    if (!name || !prompt) { showToast('Name and prompt required'); return; }
    try {
        const api = await import('./api.js');
        await api.createSafetyFilter({ name, prompt_template: prompt, severity });
        showToast('Safety filter added');
        document.getElementById('intel-filter-name').value = '';
        document.getElementById('intel-filter-prompt').value = '';
        if (severityEl) severityEl.selectedIndex = 0;
        loadIntelConfigData();
    } catch (e) { showToast('Error: ' + e.message); }
}

async function removeIntelFeed(feedId) {
    try {
        const api = await import('./api.js');
        await api.deleteFeed(feedId);
        showToast('Feed removed');
        loadIntelConfigData();
    } catch (e) { showToast('Error: ' + e.message); }
}

// Initialize — auto-restore session if still valid
(function _initSession() {
    const session = _loadSession();
    if (session) {
        currentUser = session;
        requestAnimationFrame(() => _activateApp());
    }
})();
