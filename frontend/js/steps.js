/**
 * Step content templates for the agent builder wizard.
 * Each function returns an HTML string for the step.
 */

export function step1_agentCreation() {
    return `
    <div class="max-w-3xl mx-auto space-y-3">
        <div class="t-card rounded-xl p-4">
            <div class="flex items-center gap-2.5 mb-3">
                <div class="w-7 h-7 rounded-md flex items-center justify-center" style="background:var(--accent-subtle);">
                    <span class="material-icons-outlined text-brand-500 text-lg">smart_toy</span>
                </div>
                <div>
                    <h3 class="text-sm font-semibold" style="color:var(--text-primary);">Define Your Agent</h3>
                    <p class="text-[11px]" style="color:var(--text-muted);">Configure the agent's identity and capabilities</p>
                </div>
            </div>
            <div class="space-y-2.5">
                <div class="grid grid-cols-5 gap-2.5">
                    <div class="col-span-3">
                        <label class="text-[11px] font-medium mb-1 block" style="color:var(--text-muted);">Agent Name</label>
                        <input id="agent-name" type="text" value="" placeholder="My Agent" class="t-input w-full px-3 py-1.5 border rounded-lg text-sm focus:ring-1 focus:ring-brand-500">
                    </div>
                    <div class="col-span-2">
                        <label class="text-[11px] font-medium mb-1 block" style="color:var(--text-muted);">Type</label>
                        <select id="agent-type" class="t-input w-full px-3 py-1.5 border rounded-lg text-sm focus:ring-1 focus:ring-brand-500">
                            <option selected>Default</option>
                            <option>Finance</option>
                            <option>Legal</option>
                            <option>HR</option>
                            <option>Operations</option>
                            <option>Customer Support</option>
                            <option>Custom</option>
                        </select>
                    </div>
                </div>
                <div>
                    <label class="text-[11px] font-medium mb-1 block" style="color:var(--text-muted);">System Prompt</label>
                    <textarea class="code-editor w-full px-3 py-2 border rounded-lg text-[12px] h-20 focus:ring-1 focus:ring-brand-500" placeholder="Describe your agent's role, behavior, and any specific instructions…"></textarea>
                </div>
            </div>
        </div>

        <div class="t-card rounded-xl p-4">
            <h3 class="text-[13px] font-semibold mb-2.5 flex items-center gap-1.5" style="color:var(--text-primary);">
                <span class="material-icons-outlined text-base" style="color:var(--text-muted);">tune</span>
                Capabilities
            </h3>
            <div class="flex flex-wrap gap-1.5">
                <label class="cap-label flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg cursor-pointer transition-colors" style="background:var(--accent-subtle);border:1px solid var(--border-active);" onclick="toggleCap(this)">
                    <input type="checkbox" checked class="w-3.5 h-3.5 text-brand-600 rounded">
                    <span class="text-[12px] font-medium" style="color:var(--text-primary);">RAG Retrieval</span>
                </label>
                <label class="cap-label flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg cursor-pointer transition-colors" style="background:var(--accent-subtle);border:1px solid var(--border-active);" onclick="toggleCap(this)">
                    <input type="checkbox" checked class="w-3.5 h-3.5 text-brand-600 rounded">
                    <span class="text-[12px] font-medium" style="color:var(--text-primary);">Document Parsing</span>
                </label>
                <label class="cap-label flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg cursor-pointer transition-colors" style="background:var(--bg-elevated);border:1px solid var(--border-default);" onclick="toggleCap(this)">
                    <input type="checkbox" class="w-3.5 h-3.5 text-brand-600 rounded">
                    <span class="text-[12px] font-medium" style="color:var(--text-secondary);">External API</span>
                </label>
                <label class="cap-label flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg cursor-pointer transition-colors" style="background:var(--bg-elevated);border:1px solid var(--border-default);" onclick="toggleCap(this)">
                    <input type="checkbox" class="w-3.5 h-3.5 text-brand-600 rounded">
                    <span class="text-[12px] font-medium" style="color:var(--text-secondary);">Structured Output</span>
                </label>
            </div>
        </div>

        <div class="t-card rounded-xl p-3" style="background:var(--bg-elevated);">
            <div class="flex items-start gap-2.5">
                <span class="material-icons-outlined text-brand-500 text-base mt-0.5">info</span>
                <div class="text-[12px]" style="color:var(--text-secondary);">
                    <p class="font-medium mb-0.5" style="color:var(--text-primary);">What you see as a single agent is actually an orchestrated execution of multiple steps under the hood.</p>
                    <p class="text-[11px]" style="color:var(--text-muted);">The platform is both the <strong>Agent interface</strong> (facade) and the <strong>Orchestrator</strong> (engine). At Step 6, you'll see the full pipeline unfold.</p>
                </div>
            </div>
        </div>
    </div>`;
}

export function step2_modelSelection() {
    return `
    <div class="max-w-3xl mx-auto space-y-3">
        <div class="bg-white rounded-lg border border-slate-200 p-4">
            <div class="flex items-center gap-2.5 mb-3">
                <div class="w-7 h-7 rounded-md bg-purple-100 flex items-center justify-center">
                    <span class="material-icons-outlined text-purple-600 text-lg">model_training</span>
                </div>
                <div>
                    <h3 class="text-sm font-semibold text-slate-900">Connect to a Model</h3>
                    <p class="text-[11px] text-slate-500">Select the LLM provider and model</p>
                </div>
            </div>

            <div class="grid grid-cols-3 gap-2 mb-4">
                <div class="provider-card p-2.5 border-2 border-brand-500 bg-brand-50 rounded-md cursor-pointer relative transition-all" data-provider="openai" onclick="selectProvider(this)">
                    <span class="provider-check absolute top-1.5 right-1.5 w-3.5 h-3.5 rounded-full bg-brand-500 flex items-center justify-center">
                        <span class="material-icons-outlined text-white text-[9px]">check</span>
                    </span>
                    <p class="text-[13px] font-semibold text-slate-900">OpenAI</p>
                    <p class="text-[10px] text-slate-500 mt-0.5">GPT-5, GPT-4.5, GPT-4o-mini</p>
                </div>
                <div class="provider-card p-2.5 border border-slate-200 rounded-md cursor-pointer hover:border-slate-300 transition-all relative" data-provider="anthropic" onclick="selectProvider(this)">
                    <span class="provider-check hidden absolute top-1.5 right-1.5 w-3.5 h-3.5 rounded-full bg-brand-500 flex items-center justify-center">
                        <span class="material-icons-outlined text-white text-[9px]">check</span>
                    </span>
                    <p class="text-[13px] font-semibold text-slate-900">Anthropic</p>
                    <p class="text-[10px] text-slate-500 mt-0.5">Opus 4.6, Sonnet 4.6, Haiku 4.5</p>
                </div>
                <div class="provider-card p-2.5 border border-slate-200 rounded-md cursor-pointer hover:border-slate-300 transition-all relative" data-provider="selfhosted" onclick="selectProvider(this)">
                    <span class="provider-check hidden absolute top-1.5 right-1.5 w-3.5 h-3.5 rounded-full bg-brand-500 flex items-center justify-center">
                        <span class="material-icons-outlined text-white text-[9px]">check</span>
                    </span>
                    <p class="text-[13px] font-semibold text-slate-900">Self-hosted</p>
                    <p class="text-[10px] text-slate-500 mt-0.5">Mistral 3, Gemma 4, Llama 3.1, Phi-4…</p>
                </div>
            </div>

            <div class="grid grid-cols-2 gap-3">
                <div>
                    <label class="text-[11px] font-medium text-slate-500 mb-1 block">Model</label>
                    <select id="model-select" class="w-full px-3 py-1.5 border border-slate-200 rounded-md text-sm bg-white focus:ring-1 focus:ring-brand-500">
                        <option value="gpt-5" selected>GPT-5</option>
                        <option value="gpt-4.5">GPT-4.5</option>
                        <option value="gpt-4o-mini">GPT-4o-mini</option>
                    </select>
                </div>
                <div>
                    <label class="text-[11px] font-medium text-slate-500 mb-1 block">Temperature</label>
                    <input id="temp-slider" type="range" min="0" max="100" value="30" class="w-full" oninput="updateTempLabel(this)">
                    <p id="temp-label" class="text-[10px] text-slate-500 mt-0.5">0.3 — Precise and deterministic</p>
                </div>
            </div>
        </div>

        <div class="bg-white rounded-lg border border-slate-200 p-4">
            <div class="flex items-center justify-between mb-2.5">
                <h4 class="text-[13px] font-semibold text-slate-900 flex items-center gap-1.5">
                    <span class="material-icons-outlined text-brand-500 text-base">tune</span>
                    Retrieval Settings
                </h4>
                <button id="save-rag-settings" onclick="saveRAGSettings()" class="px-2 py-1 text-[10px] font-medium text-brand-600 bg-brand-50 hover:bg-brand-100 rounded-md transition-colors flex items-center gap-1">
                    <span class="material-icons-outlined text-[11px]">save</span>
                    Save
                </button>
            </div>
            <div class="grid grid-cols-3 gap-3">
                <div>
                    <label class="text-[11px] font-medium text-slate-500 mb-1 block">Top-K results</label>
                    <input id="rag-topk" type="range" min="1" max="20" value="5" class="w-full" oninput="document.getElementById('rag-topk-val').textContent=this.value">
                    <p class="text-[10px] text-slate-500 mt-0.5">Chunks: <span id="rag-topk-val">5</span></p>
                </div>
                <div>
                    <label class="text-[11px] font-medium text-slate-500 mb-1 block">Vector weight</label>
                    <input id="rag-vweight" type="range" min="0" max="100" value="70" class="w-full" oninput="document.getElementById('rag-vweight-val').textContent=(this.value/100).toFixed(1)">
                    <p class="text-[10px] text-slate-500 mt-0.5">Weight: <span id="rag-vweight-val">0.7</span></p>
                </div>
                <div>
                    <label class="text-[11px] font-medium text-slate-500 mb-1 block">Similarity threshold</label>
                    <input id="rag-threshold" type="range" min="0" max="100" value="20" class="w-full" oninput="document.getElementById('rag-threshold-val').textContent=(this.value/100).toFixed(2)">
                    <p class="text-[10px] text-slate-500 mt-0.5">Min: <span id="rag-threshold-val">0.20</span></p>
                </div>
            </div>
        </div>

        <div class="bg-white rounded-lg border border-slate-200 p-3">
            <h4 class="text-[11px] font-semibold text-slate-500 mb-2">Platform Capabilities</h4>
            <div class="flex flex-wrap gap-1">
                <span class="px-2 py-0.5 text-[10px] font-medium bg-brand-50 text-brand-700 rounded">Multi-provider routing</span>
                <span class="px-2 py-0.5 text-[10px] font-medium bg-purple-50 text-purple-700 rounded">Streaming (SSE)</span>
                <span class="px-2 py-0.5 text-[10px] font-medium bg-emerald-50 text-emerald-700 rounded">Structured output</span>
                <span class="px-2 py-0.5 text-[10px] font-medium bg-amber-50 text-amber-700 rounded">Query rewriting</span>
                <span class="px-2 py-0.5 text-[10px] font-medium bg-slate-100 text-slate-600 rounded">Hybrid retrieval</span>
            </div>
        </div>
    </div>`;
}

export function step3_knowledgeUpload() {
    return `
    <div class="max-w-3xl mx-auto space-y-3">
        <div class="bg-white rounded-lg border border-slate-200 p-4">
            <div class="flex items-center gap-2.5 mb-3">
                <div class="w-7 h-7 rounded-md bg-emerald-100 flex items-center justify-center">
                    <span class="material-icons-outlined text-emerald-600 text-lg">library_books</span>
                </div>
                <div>
                    <h3 class="text-sm font-semibold text-slate-900">Knowledge Base</h3>
                    <p class="text-[11px] text-slate-500">Upload documents for RAG retrieval</p>
                </div>
            </div>

            <div id="upload-zone" class="border border-dashed border-slate-300 rounded-md p-6 text-center hover:border-brand-400 transition-colors cursor-pointer">
                <span class="material-icons-outlined text-3xl text-slate-400 mb-1">cloud_upload</span>
                <p class="text-[13px] font-medium text-slate-700">Drag & drop documents or click to browse</p>
                <p class="text-[11px] text-slate-400 mt-0.5">PDF, DOCX, TXT, Markdown &middot; Max 10 MB</p>
                <input id="file-input" type="file" class="hidden" accept=".pdf,.docx,.txt,.md" multiple>
            </div>

            <div id="uploaded-files" class="mt-3 space-y-1.5"></div>

            <button onclick="confirmResetKB()" class="w-full mt-2 flex items-center justify-center gap-1.5 px-3 py-1.5 text-[11px] font-medium text-red-600 border border-red-200 bg-red-50 hover:bg-red-100 rounded-md transition-colors">
                <span class="material-icons-outlined text-sm">delete_forever</span>
                Reset Knowledge Base
            </button>

            <div class="mt-3 pt-3 border-t border-slate-100">
                <h4 class="text-[12px] font-semibold text-slate-600 mb-2">Knowledge Base</h4>
                <div class="space-y-1.5" id="preloaded-docs">
                    <p class="text-[11px] text-slate-400">Loading…</p>
                </div>
            </div>
        </div>

        <div class="bg-white rounded-lg border border-slate-200 p-3">
            <h4 class="text-[11px] font-semibold text-slate-500 mb-2">RAG Pipeline</h4>
            <div class="flex items-center gap-1.5 text-[10px] flex-wrap">
                <span class="px-2 py-0.5 bg-slate-100 text-slate-600 rounded font-mono">Parse</span>
                <span class="material-icons-outlined text-slate-300 text-[10px]">arrow_forward</span>
                <span class="px-2 py-0.5 bg-slate-100 text-slate-600 rounded font-mono">Chunk</span>
                <span class="material-icons-outlined text-slate-300 text-[10px]">arrow_forward</span>
                <span class="px-2 py-0.5 bg-slate-100 text-slate-600 rounded font-mono">Embed</span>
                <span class="material-icons-outlined text-slate-300 text-[10px]">arrow_forward</span>
                <span class="px-2 py-0.5 bg-brand-50 text-brand-700 rounded font-mono">FAISS</span>
                <span class="material-icons-outlined text-slate-300 text-[10px]">arrow_forward</span>
                <span class="px-2 py-0.5 bg-emerald-50 text-emerald-700 rounded font-mono">Hybrid Retrieval</span>
            </div>
        </div>
    </div>`;
}

export function step4_rulesTools() {
    const tools = [
        { icon: 'travel_explore', color: 'blue',    name: 'Web Search',        desc: 'Search the internet for real-time information and news' },
        { icon: 'code',           color: 'violet',  name: 'Code Interpreter',  desc: 'Execute Python scripts and analyze data programmatically' },
        { icon: 'table_chart',    color: 'emerald', name: 'SQL Query',         desc: 'Query structured databases and export results' },
        { icon: 'api',            color: 'orange',  name: 'API Connector',     desc: 'Call external REST APIs with custom authentication' },
        { icon: 'mail',           color: 'rose',    name: 'Email Sender',      desc: 'Draft and send emails from agent workflows' },
        { icon: 'picture_as_pdf', color: 'red',     name: 'File Generator',    desc: 'Export agent output as PDF, Excel, or CSV' },
        { icon: 'calendar_today', color: 'amber',   name: 'Calendar Access',   desc: 'Read and write calendar events and schedules' },
        { icon: 'memory',         color: 'indigo',  name: 'Persistent Memory', desc: 'Store and retrieve context across sessions' },
    ];
    const colorMap = {
        blue:   { bg: 'bg-blue-100',   icon: 'text-blue-600'   },
        violet: { bg: 'bg-violet-100', icon: 'text-violet-600' },
        emerald:{ bg: 'bg-emerald-100',icon: 'text-emerald-600'},
        orange: { bg: 'bg-orange-100', icon: 'text-orange-600' },
        rose:   { bg: 'bg-rose-100',   icon: 'text-rose-600'   },
        red:    { bg: 'bg-red-100',    icon: 'text-red-600'    },
        amber:  { bg: 'bg-amber-100',  icon: 'text-amber-600'  },
        indigo: { bg: 'bg-indigo-100', icon: 'text-indigo-600' },
    };
    const toolCards = tools.map(t => {
        const c = colorMap[t.color];
        return `
        <div class="relative bg-white rounded-lg border border-slate-200 p-3.5 flex items-start gap-3 opacity-60 cursor-not-allowed select-none">
            <div class="w-8 h-8 rounded-md ${c.bg} flex items-center justify-center shrink-0">
                <span class="material-icons-outlined ${c.icon} text-lg">${t.icon}</span>
            </div>
            <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 mb-0.5">
                    <p class="text-[13px] font-semibold text-slate-700">${t.name}</p>
                    <span class="px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider bg-amber-100 text-amber-700 rounded">Coming soon</span>
                </div>
                <p class="text-[11px] text-slate-400 leading-snug">${t.desc}</p>
            </div>
            <div class="shrink-0 w-8 h-5 rounded-full bg-slate-200 relative" title="Not yet available">
                <div class="w-4 h-4 rounded-full bg-white shadow-sm absolute top-0.5 left-0.5"></div>
            </div>
        </div>`;
    }).join('');

    return `
    <div class="max-w-3xl mx-auto space-y-4">
        <div class="flex items-center gap-2.5">
            <div class="flex-1">
                <h2 class="text-sm font-semibold text-slate-900">Tools</h2>
                <p class="text-[11px] text-slate-500 mt-0.5">Extend your agent with external capabilities. Select the tools it can use during execution.</p>
            </div>
            <div class="flex items-center gap-1.5 px-2.5 py-1.5 bg-amber-50 border border-amber-200 rounded-lg shrink-0">
                <span class="material-icons-outlined text-amber-500 text-sm">construction</span>
                <span class="text-[11px] font-medium text-amber-700">In development</span>
            </div>
        </div>

        <div class="grid grid-cols-2 gap-2.5">
            ${toolCards}
        </div>

        <div class="bg-slate-50 border border-slate-200 rounded-lg px-4 py-3 flex items-start gap-3">
            <span class="material-icons-outlined text-slate-400 text-lg mt-0.5">info</span>
            <div>
                <p class="text-[12px] font-medium text-slate-700">Tool integrations are coming in the next release</p>
                <p class="text-[11px] text-slate-500 mt-0.5">Opt-in tools let your agent reach beyond the knowledge base — searching the web, running code, calling APIs, and more. Each tool will be individually toggled per agent.</p>
            </div>
        </div>
    </div>`;
}

export function step5_governance() {
    return `
    <div class="max-w-3xl mx-auto space-y-3">
        <div class="bg-white rounded-lg border border-slate-200 p-4">
            <div class="flex items-center gap-2.5 mb-3">
                <div class="w-7 h-7 rounded-md bg-indigo-100 flex items-center justify-center">
                    <span class="material-icons-outlined text-indigo-600 text-lg">security</span>
                </div>
                <div>
                    <h3 class="text-sm font-semibold text-slate-900">Governance & Audit</h3>
                    <p class="text-[11px] text-slate-500">Every action is logged, traceable, and auditable</p>
                </div>
            </div>

            <div class="grid grid-cols-3 gap-2 mb-4">
                <div class="p-2.5 bg-slate-50 border border-slate-200 rounded-md">
                    <span class="material-icons-outlined text-indigo-500 text-lg mb-1">group</span>
                    <h4 class="text-[11px] font-semibold text-slate-900">Access Control</h4>
                    <p class="text-[10px] text-slate-500 mt-0.5">OIDC / SSO (Keycloak)</p>
                    <div class="mt-1.5 flex gap-2">
                        <span class="flex items-center gap-1 text-[9px] text-slate-500"><span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>Admin</span>
                        <span class="flex items-center gap-1 text-[9px] text-slate-500"><span class="w-1.5 h-1.5 rounded-full bg-slate-400"></span>User</span>
                    </div>
                </div>
                <div class="p-2.5 bg-slate-50 border border-slate-200 rounded-md">
                    <span class="material-icons-outlined text-amber-500 text-lg mb-1">receipt_long</span>
                    <h4 class="text-[11px] font-semibold text-slate-900">Audit Trail</h4>
                    <p class="text-[10px] text-slate-500 mt-0.5">Full execution logging</p>
                    <p class="text-[10px] text-amber-700 font-mono mt-1.5" id="audit-count">Loading...</p>
                </div>
                <div class="p-2.5 bg-slate-50 border border-slate-200 rounded-md">
                    <span class="material-icons-outlined text-emerald-500 text-lg mb-1">visibility</span>
                    <h4 class="text-[11px] font-semibold text-slate-900">Execution Tracing</h4>
                    <p class="text-[10px] text-slate-500 mt-0.5">Pipeline steps with timing</p>
                    <p class="text-[10px] text-emerald-700 font-mono mt-1.5">Real-time SSE</p>
                </div>
            </div>

            <div class="bg-slate-50 rounded-md border border-slate-100 p-3">
                <h4 class="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-2">Recent Audit Events</h4>
                <div id="audit-logs" class="space-y-1.5 text-[11px] font-mono text-slate-600">
                    <p class="text-slate-400">No events yet. Execute the agent to generate audit entries.</p>
                </div>
            </div>
        </div>
    </div>`;
}

// -- Sidebar pages --

export function page_knowledgeBase() {
    return `
    <div class="max-w-3xl mx-auto space-y-3">
        <div class="bg-white rounded-lg border border-slate-200 p-4">
            <div class="flex items-center justify-between mb-3">
                <div class="flex items-center gap-2.5">
                    <div class="w-7 h-7 rounded-md bg-emerald-100 flex items-center justify-center">
                        <span class="material-icons-outlined text-emerald-600 text-lg">library_books</span>
                    </div>
                    <div>
                        <h3 class="text-sm font-semibold text-slate-900">Knowledge Base</h3>
                        <p class="text-[11px] text-slate-500">Documents indexed for retrieval</p>
                    </div>
                </div>
                <div id="kb-stats" class="text-right">
                    <p class="text-base font-semibold text-slate-900">—</p>
                    <p class="text-[10px] text-slate-400">chunks indexed</p>
                </div>
            </div>

            <div class="grid grid-cols-3 gap-2 mb-4">
                <div class="p-2.5 bg-emerald-50 border border-emerald-200 rounded-md text-center">
                    <p class="text-lg font-bold text-emerald-700" id="kb-doc-count">—</p>
                    <p class="text-[10px] text-slate-500">Documents</p>
                </div>
                <div class="p-2.5 bg-brand-50 border border-brand-200 rounded-md text-center">
                    <p class="text-lg font-bold text-brand-700" id="kb-chunk-count">—</p>
                    <p class="text-[10px] text-slate-500">Chunks</p>
                </div>
                <div class="p-2.5 bg-purple-50 border border-purple-200 rounded-md text-center">
                    <p class="text-lg font-bold text-purple-700" id="kb-vector-dim">—</p>
                    <p class="text-[10px] text-slate-500">Vector dims</p>
                </div>
            </div>

            <div id="upload-zone" class="border border-dashed border-slate-300 rounded-md p-5 text-center hover:border-brand-400 transition-colors cursor-pointer mb-3">
                <span class="material-icons-outlined text-2xl text-slate-400 mb-1">cloud_upload</span>
                <p class="text-[13px] font-medium text-slate-700">Upload documents</p>
                <p class="text-[10px] text-slate-400 mt-0.5">PDF, DOCX, TXT, Markdown</p>
                <input id="file-input" type="file" class="hidden" accept=".pdf,.docx,.txt,.md" multiple>
            </div>
            <div id="uploaded-files" class="space-y-1.5"></div>

            <button onclick="confirmResetKB()" class="w-full mt-2 flex items-center justify-center gap-1.5 px-3 py-1.5 text-[11px] font-medium text-red-600 border border-red-200 bg-red-50 hover:bg-red-100 rounded-md transition-colors">
                <span class="material-icons-outlined text-sm">delete_forever</span>
                Reset Knowledge Base
            </button>

            <div class="pt-3 border-t border-slate-100">
                <h4 class="text-[11px] font-semibold text-slate-500 mb-2">Indexed Documents</h4>
                <div class="space-y-1.5" id="kb-documents">
                    <p class="text-[11px] text-slate-400">Loading documents…</p>
                </div>
            </div>
        </div>

        <div class="bg-white rounded-lg border border-slate-200 p-3">
            <h4 class="text-[11px] font-semibold text-slate-500 mb-2">Retrieval Pipeline</h4>
            <div class="flex items-center gap-1.5 text-[10px] flex-wrap">
                <span class="px-2 py-0.5 bg-slate-100 text-slate-600 rounded font-mono">Parse</span>
                <span class="material-icons-outlined text-slate-300 text-[10px]">arrow_forward</span>
                <span class="px-2 py-0.5 bg-slate-100 text-slate-600 rounded font-mono">Chunk</span>
                <span class="material-icons-outlined text-slate-300 text-[10px]">arrow_forward</span>
                <span class="px-2 py-0.5 bg-slate-100 text-slate-600 rounded font-mono">Embed</span>
                <span class="material-icons-outlined text-slate-300 text-[10px]">arrow_forward</span>
                <span class="px-2 py-0.5 bg-brand-50 text-brand-700 rounded font-mono">FAISS</span>
                <span class="material-icons-outlined text-slate-300 text-[10px]">arrow_forward</span>
                <span class="px-2 py-0.5 bg-emerald-50 text-emerald-700 rounded font-mono">Hybrid Retrieval</span>
            </div>
        </div>
    </div>`;
}

export function page_accessRoles() {
    const users = [
        { initials: 'TI', name: 'Thibaud Ishacian', email: 'thibaud.ishacian@presight.ai', color: 'brand', role: 'Admin' },
        { initials: 'EC', name: 'Eric Chau', email: 'eric.chau@presight.ai', color: 'emerald', role: 'Admin' },
        { initials: 'MC', name: 'Mehdi Chouiten', email: 'mehdi.chouiten@presight.ai', color: 'violet', role: 'Admin' },
        { initials: 'HK', name: 'Hermann Kuetat', email: 'hermann.kuetat@presight.ai', color: 'amber', role: 'User' },
        { initials: 'ED', name: 'Enzo Damion', email: 'enzo.damion@datategy.net', color: 'indigo', role: 'Admin' },
    ];

    const currentEmail = (typeof currentUser !== 'undefined') ? currentUser.email : '';

    const sessionRows = users.map(u => {
        const isMe = u.email === currentEmail;
        const status = isMe
            ? '<span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span><span class="text-[10px] text-emerald-600 font-medium">Active now</span>'
            : '<span class="w-1.5 h-1.5 rounded-full bg-slate-300"></span><span class="text-[10px] text-slate-500">Offline</span>';
        const highlight = isMe ? 'bg-brand-50 border border-brand-100' : 'bg-slate-50 border border-slate-100';
        return `<div class="flex items-center justify-between p-2 ${highlight} rounded-md text-[12px]">
            <div class="flex items-center gap-2">
                <div class="w-6 h-6 rounded-md bg-${u.color}-600 flex items-center justify-center text-[9px] font-bold text-white">${u.initials}</div>
                <div>
                    <p class="font-medium text-slate-800 text-[12px]">${u.name}${isMe ? ' <span class="text-[9px] text-brand-500 font-normal">(you)</span>' : ''}</p>
                    <p class="text-[10px] text-slate-400">${u.email}</p>
                </div>
            </div>
            <div class="flex items-center gap-2.5">
                <span class="px-1.5 py-0.5 text-[9px] font-medium bg-slate-100 text-slate-600 rounded">${u.role}</span>
                <div class="flex items-center gap-1">${status}</div>
            </div>
        </div>`;
    }).join('');

    return `
    <div class="max-w-3xl mx-auto space-y-3">
        <div class="bg-white rounded-lg border border-slate-200 p-4">
            <div class="flex items-center justify-between mb-4">
                <div class="flex items-center gap-2.5">
                    <div class="w-7 h-7 rounded-md bg-indigo-100 flex items-center justify-center">
                        <span class="material-icons-outlined text-indigo-600 text-lg">group</span>
                    </div>
                    <div>
                        <h3 class="text-sm font-semibold text-slate-900">Access & Roles</h3>
                        <p class="text-[11px] text-slate-500">Role-based access control via OIDC / Keycloak</p>
                    </div>
                </div>
                <button id="invite-btn" onclick="toggleInviteForm()" class="px-2.5 py-1 text-[11px] font-medium text-brand-600 bg-brand-50 hover:bg-brand-100 rounded-md transition-colors flex items-center gap-1">
                    <span class="material-icons-outlined text-sm">person_add</span>
                    Invite
                </button>
            </div>

            <div id="invite-form" class="hidden mb-3 p-3 bg-brand-50 border border-brand-200 rounded-md space-y-2.5 transition-all">
                <div class="flex items-center gap-1.5 mb-0.5">
                    <span class="material-icons-outlined text-brand-600 text-sm">mail_outline</span>
                    <span class="text-[11px] font-semibold text-brand-800">Invite a new member</span>
                </div>
                <div class="grid grid-cols-5 gap-2">
                    <input id="invite-email" type="email" placeholder="name@company.com" class="col-span-3 px-2.5 py-1.5 border border-brand-300 rounded-md text-sm focus:ring-1 focus:ring-brand-500 focus:border-brand-500 bg-white">
                    <select id="invite-role" class="col-span-1 px-2 py-1.5 border border-brand-300 rounded-md text-sm bg-white focus:ring-1 focus:ring-brand-500">
                        <option>User</option>
                        <option>Admin</option>
                    </select>
                    <button onclick="sendInvite()" class="col-span-1 px-2.5 py-1.5 text-sm font-medium text-white bg-brand-600 hover:bg-brand-700 rounded-md transition-colors">Send</button>
                </div>
            </div>

            <div class="bg-slate-50 border border-slate-200 rounded-md p-3 mb-4">
                <div class="flex items-center gap-1.5 mb-2">
                    <span class="material-icons-outlined text-indigo-500 text-base">shield</span>
                    <span class="text-[11px] font-semibold text-slate-700">Identity Provider</span>
                </div>
                <div class="grid grid-cols-2 gap-2 text-[11px]">
                    <div><span class="text-slate-500">Provider:</span> <span class="font-medium text-slate-800">Keycloak 24.x</span></div>
                    <div><span class="text-slate-500">Protocol:</span> <span class="font-medium text-slate-800">OIDC / OAuth 2.0</span></div>
                    <div><span class="text-slate-500">Realm:</span> <span class="font-medium text-slate-800">datategy</span></div>
                    <div><span class="text-slate-500">SSO:</span> <span class="font-medium text-emerald-700">Enabled</span></div>
                </div>
            </div>

            <h4 class="text-[11px] font-semibold text-slate-500 mb-2">Roles</h4>
            <div class="space-y-1.5 mb-4">
                <div class="flex items-center justify-between p-2 border border-slate-200 rounded-md">
                    <div class="flex items-center gap-2">
                        <span class="w-2 h-2 rounded-full bg-emerald-500"></span>
                        <div>
                            <p class="text-[12px] font-medium text-slate-800">Admin</p>
                            <p class="text-[10px] text-slate-500">Full platform access, agent management, user management</p>
                        </div>
                    </div>
                    <span class="px-1.5 py-0.5 text-[9px] font-medium bg-emerald-100 text-emerald-700 rounded">4 users</span>
                </div>
                <div class="flex items-center justify-between p-2 border border-slate-200 rounded-md">
                    <div class="flex items-center gap-2">
                        <span class="w-2 h-2 rounded-full bg-slate-400"></span>
                        <div>
                            <p class="text-[12px] font-medium text-slate-800">User</p>
                            <p class="text-[10px] text-slate-500">Execute agents, upload documents, view own results</p>
                        </div>
                    </div>
                    <span class="px-1.5 py-0.5 text-[9px] font-medium bg-slate-100 text-slate-600 rounded">1 user</span>
                </div>
            </div>

            <div class="pt-3 border-t border-slate-100">
                <div class="flex items-center justify-between mb-2">
                    <h4 class="text-[11px] font-semibold text-slate-500">Workspace Members</h4>
                    <span class="text-[10px] text-slate-400">5 members</span>
                </div>
                <div class="space-y-1.5">
                    ${sessionRows}
                </div>
            </div>
        </div>
    </div>`;
}

export function page_auditLogs() {
    return `
    <div class="max-w-3xl mx-auto space-y-3">
        <div class="bg-white rounded-lg border border-slate-200 p-4">
            <div class="flex items-center justify-between mb-4">
                <div class="flex items-center gap-2.5">
                    <div class="w-7 h-7 rounded-md bg-amber-100 flex items-center justify-center">
                        <span class="material-icons-outlined text-amber-600 text-lg">receipt_long</span>
                    </div>
                    <div>
                        <h3 class="text-sm font-semibold text-slate-900">Audit Logs</h3>
                        <p class="text-[11px] text-slate-500">Execution history and compliance events</p>
                    </div>
                </div>
                <div id="audit-page-stats" class="text-right">
                    <p class="text-base font-semibold text-slate-900">—</p>
                    <p class="text-[10px] text-slate-400">total events</p>
                </div>
            </div>

            <div class="overflow-hidden rounded-md border border-slate-200">
                <table class="w-full text-[11px]">
                    <thead>
                        <tr class="bg-[#181e2a]">
                            <th class="text-left px-3 py-2 text-[9px] font-semibold text-slate-300 uppercase tracking-wider">Time</th>
                            <th class="text-left px-3 py-2 text-[9px] font-semibold text-slate-300 uppercase tracking-wider">Event</th>
                            <th class="text-left px-3 py-2 text-[9px] font-semibold text-slate-300 uppercase tracking-wider">Actor</th>
                            <th class="text-left px-3 py-2 text-[9px] font-semibold text-slate-300 uppercase tracking-wider">Agent</th>
                            <th class="text-left px-3 py-2 text-[9px] font-semibold text-slate-300 uppercase tracking-wider">Severity</th>
                        </tr>
                    </thead>
                    <tbody id="audit-table-body">
                        <tr><td colspan="5" class="px-3 py-6 text-center text-slate-400 text-[12px]">Loading audit events...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>`;
}

export function step6_execution() {
    const agentName = (typeof savedAgentName !== 'undefined' && savedAgentName) ? savedAgentName : 'My Agent';
    const agentType = (typeof savedAgentType !== 'undefined' && savedAgentType) ? savedAgentType : 'Custom';

    const descMap = {
        'Finance': 'Ask a financial question or submit a document to analyze…',
        'Legal': 'Ask a legal question or submit a contract to review…',
        'HR': 'Ask an HR question or submit a document to process…',
        'Operations': 'Describe an operational request or document to analyze…',
        'Customer Support': 'Describe a customer request to process…',
    };
    const welcomeMap = {
        'Finance': 'Ask financial questions or submit documents. The agent will retrieve relevant context from your knowledge base and generate a precise answer.',
        'Legal': 'Ask legal questions or submit contracts for review. The agent will cross-reference your knowledge base and provide structured analysis.',
        'HR': 'Ask HR-related questions or submit documents. The agent will retrieve relevant policies and generate a clear response.',
        'Operations': 'Submit operational requests or documents. The agent will process them against your configured knowledge base.',
        'Customer Support': 'Describe a customer issue and the agent will process it using the knowledge base and tools configured above.',
    };
    const placeholder = descMap[agentType] || 'Send a message to test your agent…';
    const welcome = welcomeMap[agentType] || 'Test your agent with a real query. Each orchestration step will be shown in real time.';

    return `
    <div class="max-w-3xl mx-auto flex flex-col" style="height:calc(100vh - 180px);">
        <div class="t-card rounded-xl flex flex-col flex-1 min-h-0 overflow-hidden">
            <!-- Header -->
            <div class="px-4 py-2.5 flex items-center gap-2 shrink-0" style="border-bottom:1px solid var(--border-default);background:var(--bg-elevated);">
                <div class="w-1 h-4 rounded-sm" style="background:var(--accent);"></div>
                <h3 class="text-[13px] font-semibold" style="color:var(--text-primary);">${agentName}</h3>
                <span id="chat-status" class="text-[11px] ml-auto" style="color:var(--text-muted);"></span>
            </div>

            <!-- Messages -->
            <div id="chat-messages" class="flex-1 overflow-y-auto px-4 py-5 space-y-4">
                <div id="chat-welcome" class="flex flex-col items-center justify-center h-full">
                    <div class="w-full max-w-lg">
                        <div class="mb-5">
                            <div class="flex items-center gap-2 mb-1.5">
                                <span class="block w-1 h-5 rounded-sm" style="background:var(--accent);"></span>
                                <h2 class="font-semibold text-[15px]" style="color:var(--text-primary);">${agentName}</h2>
                            </div>
                            <p class="text-[13px] ml-3" style="color:var(--text-muted);">${welcome}</p>
                        </div>
                        <div class="space-y-1.5" id="suggestion-cards">
                            <button onclick="sendSuggestion(this)" class="suggestion-card w-full text-left text-[12px] rounded-lg px-3 py-2.5 transition-all" style="color:var(--text-secondary);background:var(--bg-elevated);border:1px solid var(--border-default);">
                                <span class="font-medium" style="color:var(--text-primary);">Summarize</span> — What are the key points in the uploaded documents?
                            </button>
                            <button onclick="sendSuggestion(this)" class="suggestion-card w-full text-left text-[12px] rounded-lg px-3 py-2.5 transition-all" style="color:var(--text-secondary);background:var(--bg-elevated);border:1px solid var(--border-default);">
                                What criteria does the agent use to evaluate a request?
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Input bar -->
            <div class="px-4 py-3 shrink-0" style="border-top:1px solid var(--border-default);">
                <div class="flex items-end gap-2 px-3 py-2 rounded-lg transition-colors" style="background:var(--bg-elevated);border:1px solid var(--border-default);">
                    <button id="mic-btn" onclick="toggleMic()" class="shrink-0 w-7 h-7 rounded-lg flex items-center justify-center transition-colors" style="color:var(--text-muted);" title="Voice input">
                        <span class="material-icons-outlined text-sm">mic</span>
                    </button>
                    <textarea id="chat-input" rows="1" placeholder="${placeholder}"
                        class="flex-1 resize-none bg-transparent text-[13px] focus:outline-none disabled:opacity-50 leading-relaxed"
                        style="max-height:100px;color:var(--text-primary);"></textarea>
                    <button id="tts-btn" onclick="toggleTTS()" class="shrink-0 w-7 h-7 rounded-lg flex items-center justify-center transition-colors" style="color:var(--text-muted);" title="Toggle voice output">
                        <span class="material-icons-outlined text-sm">volume_up</span>
                    </button>
                    <button id="chat-send" onclick="sendChat()"
                        class="shrink-0 w-7 h-7 rounded-lg text-white transition-colors disabled:opacity-30 disabled:cursor-not-allowed flex items-center justify-center" style="background:var(--accent);">
                        <span class="material-icons-outlined text-base">arrow_forward</span>
                    </button>
                </div>
                <p class="text-[10px] mt-1 text-center" style="color:var(--text-muted);">Enter to send &middot; Mic for voice &middot; Speaker for TTS</p>
            </div>
        </div>
    </div>`;
}

export function step7_save() {
    const name = (typeof savedAgentName !== 'undefined' && savedAgentName) ? savedAgentName : 'My Agent';
    const type = (typeof savedAgentType !== 'undefined' && savedAgentType) ? savedAgentType : 'Default';
    const model = (typeof savedModel !== 'undefined' && savedModel) ? savedModel : 'gpt-5';
    const provider = (typeof selectedProvider !== 'undefined' && selectedProvider) ? selectedProvider : 'openai';
    const temp = (typeof savedTemperature !== 'undefined') ? savedTemperature : 0.3;
    const prompt = (typeof savedSystemPrompt !== 'undefined') ? savedSystemPrompt : '';
    const providerLabel = { openai: 'OpenAI', anthropic: 'Anthropic', 'self-hosted': 'Self-hosted' }[provider] || provider;

    return `
    <div class="max-w-3xl mx-auto space-y-4">
        <div class="bg-white rounded-lg border border-slate-200 p-5">
            <div class="flex items-center gap-2.5 mb-5">
                <div class="w-8 h-8 rounded-md bg-brand-100 flex items-center justify-center">
                    <span class="material-icons-outlined text-brand-600 text-lg">smart_toy</span>
                </div>
                <div>
                    <h3 class="text-sm font-semibold text-slate-900">Review & Save</h3>
                    <p class="text-[11px] text-slate-500">Confirm your agent configuration before saving</p>
                </div>
            </div>

            <div class="grid grid-cols-2 gap-3 mb-5">
                <div class="p-3 bg-slate-50 rounded-md border border-slate-100">
                    <p class="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-1">Agent Name</p>
                    <p class="text-[13px] font-medium text-slate-800">${name}</p>
                </div>
                <div class="p-3 bg-slate-50 rounded-md border border-slate-100">
                    <p class="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-1">Type</p>
                    <p class="text-[13px] font-medium text-slate-800">${type}</p>
                </div>
                <div class="p-3 bg-slate-50 rounded-md border border-slate-100">
                    <p class="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-1">Model</p>
                    <p class="text-[13px] font-medium text-slate-800">${model}</p>
                </div>
                <div class="p-3 bg-slate-50 rounded-md border border-slate-100">
                    <p class="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-1">Provider</p>
                    <p class="text-[13px] font-medium text-slate-800">${providerLabel}</p>
                </div>
                <div class="p-3 bg-slate-50 rounded-md border border-slate-100 col-span-2">
                    <p class="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-1.5">Temperature</p>
                    <div class="flex items-center gap-3">
                        <div class="flex-1 bg-slate-200 rounded-full h-1.5">
                            <div class="bg-brand-500 rounded-full h-1.5" style="width:${Math.round(temp * 100)}%"></div>
                        </div>
                        <span class="text-[12px] font-mono text-slate-700 shrink-0">${temp.toFixed(2)}</span>
                    </div>
                </div>
                ${prompt ? `
                <div class="p-3 bg-slate-50 rounded-md border border-slate-100 col-span-2">
                    <p class="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-1">System Prompt</p>
                    <p class="text-[12px] text-slate-600 font-mono leading-relaxed line-clamp-3">${prompt.slice(0, 220)}${prompt.length > 220 ? '…' : ''}</p>
                </div>` : ''}
            </div>

            <div id="step7-actions">
                <button onclick="saveCurrentAgent()" class="w-full py-2.5 px-4 bg-brand-600 hover:bg-brand-700 text-white text-[13px] font-semibold rounded-md transition-colors flex items-center justify-center gap-2">
                    <span class="material-icons-outlined text-base">save</span>
                    Save Agent
                </button>
            </div>
        </div>

        <div class="bg-slate-50 border border-slate-200 rounded-lg px-4 py-3 flex items-start gap-2.5">
            <span class="material-icons-outlined text-slate-400 text-base mt-0.5">info</span>
            <p class="text-[11px] text-slate-500">Saved agents appear in the <strong class="text-slate-700">Agents</strong> section. Click <strong class="text-slate-700">Chat</strong> on any agent to start a new session with its configuration.</p>
        </div>
    </div>`;
}

export function page_agents() {
    return `
    <div class="max-w-3xl mx-auto space-y-3">
        <div class="t-card rounded-xl p-4">
            <div class="flex items-center justify-between mb-4">
                <div class="flex items-center gap-2.5">
                    <div class="w-7 h-7 rounded-md flex items-center justify-center" style="background:var(--accent-subtle);">
                        <span class="material-icons-outlined text-brand-500 text-lg">smart_toy</span>
                    </div>
                    <div>
                        <h3 class="text-sm font-semibold" style="color:var(--text-primary);">My Agents</h3>
                        <p class="text-[11px]" style="color:var(--text-muted);">Your saved agent configurations</p>
                    </div>
                </div>
                <button onclick="goToStep(1)" class="px-2.5 py-1.5 text-[11px] font-medium rounded-lg transition-colors flex items-center gap-1" style="color:var(--accent);background:var(--accent-subtle);">
                    <span class="material-icons-outlined text-sm">add</span>
                    New Agent
                </button>
            </div>
            <div id="agents-list" class="space-y-2">
                <p class="text-[12px] text-center py-4" style="color:var(--text-muted);">Loading…</p>
            </div>
        </div>
    </div>`;
}

export function page_agentHub() {
    return `
    <div class="max-w-5xl mx-auto">
        <!-- KPI Row -->
        <div class="grid grid-cols-4 gap-3 mb-6">
            <div class="t-card rounded-xl p-4">
                <div class="flex items-center gap-2 mb-2">
                    <span class="material-icons-outlined text-lg" style="color:var(--accent);">hub</span>
                    <span class="text-[11px] font-medium" style="color:var(--text-muted);">Active Agents</span>
                </div>
                <p class="text-2xl font-bold" style="color:var(--text-primary);">4</p>
                <p class="text-[10px] mt-0.5" style="color:var(--success);">All operational</p>
            </div>
            <div class="t-card rounded-xl p-4">
                <div class="flex items-center gap-2 mb-2">
                    <span class="material-icons-outlined text-lg" style="color:var(--info);">library_books</span>
                    <span class="text-[11px] font-medium" style="color:var(--text-muted);">Knowledge Docs</span>
                </div>
                <p class="text-2xl font-bold" id="hub-kb-count" style="color:var(--text-primary);">—</p>
                <p class="text-[10px] mt-0.5" style="color:var(--text-muted);">Indexed</p>
            </div>
            <div class="t-card rounded-xl p-4">
                <div class="flex items-center gap-2 mb-2">
                    <span class="material-icons-outlined text-lg" style="color:var(--warning);">cable</span>
                    <span class="text-[11px] font-medium" style="color:var(--text-muted);">Integrations</span>
                </div>
                <p class="text-2xl font-bold" style="color:var(--text-primary);">12</p>
                <p class="text-[10px] mt-0.5" style="color:var(--text-muted);">Connectors available</p>
            </div>
            <div class="t-card rounded-xl p-4">
                <div class="flex items-center gap-2 mb-2">
                    <span class="material-icons-outlined text-lg" style="color:var(--success);">speed</span>
                    <span class="text-[11px] font-medium" style="color:var(--text-muted);">Avg. Latency</span>
                </div>
                <p class="text-2xl font-bold" style="color:var(--text-primary);">2.4s</p>
                <p class="text-[10px] mt-0.5" style="color:var(--success);">Within SLA</p>
            </div>
        </div>

        <!-- Agent Cards -->
        <div class="flex items-center justify-between mb-4">
            <div>
                <h2 class="text-base font-semibold" style="color:var(--text-primary);">Agents</h2>
                <p class="text-[12px]" style="color:var(--text-muted);">Select an agent to start a conversation, or create a new one.</p>
            </div>
            <button onclick="goToStep(1)" class="px-3 py-1.5 text-[12px] font-medium text-white rounded-lg transition-all flex items-center gap-1.5" style="background:var(--accent);">
                <span class="material-icons-outlined text-sm">add</span>
                New Agent
            </button>
        </div>

        <div class="grid grid-cols-3 gap-3" id="hub-agents-grid">
            <div class="t-card rounded-xl p-5 flex items-center justify-center" style="min-height:180px;">
                <span class="text-[12px]" style="color:var(--text-muted);">Loading agents…</span>
            </div>
        </div>
    </div>`;
}

export function page_integrations() {
    const connectors = [
        { cat: 'Microsoft', items: [
            { icon: 'cloud', name: 'Dynamics 365', desc: 'ERP/CRM data, vendor records, purchase orders', status: 'available' },
            { icon: 'chat', name: 'Microsoft Teams', desc: 'Notifications, agent conversations via Teams', status: 'available' },
            { icon: 'folder_shared', name: 'SharePoint', desc: 'Document libraries, policy repositories', status: 'available' },
            { icon: 'mail', name: 'Outlook / Exchange', desc: 'Email integration, calendar events, task sync', status: 'available' },
        ]},
        { cat: 'Communication Channels', items: [
            { icon: 'send', name: 'Telegram Bot', desc: 'Chat interaction via Telegram bot API', status: 'available' },
            { icon: 'forum', name: 'WhatsApp Business', desc: 'Agent access via WhatsApp Business API', status: 'coming' },
            { icon: 'email', name: 'SMTP / Email', desc: 'Inbound/outbound email agent triggers', status: 'available' },
            { icon: 'api', name: 'REST API', desc: 'Custom integrations via documented REST endpoints', status: 'active' },
            { icon: 'hub', name: 'MQTT', desc: 'IoT and real-time event-driven messaging', status: 'available' },
        ]},
        { cat: 'Data & Storage', items: [
            { icon: 'storage', name: 'PostgreSQL', desc: 'Structured data queries and analytics', status: 'active' },
            { icon: 'cloud_queue', name: 'AWS S3', desc: 'Cloud document storage and retrieval', status: 'available' },
            { icon: 'dns', name: 'Elasticsearch', desc: 'Full-text search and log analytics', status: 'coming' },
        ]},
    ];

    const statusMap = {
        active: { label: 'Connected', color: 'var(--success)', bg: 'rgba(16,185,129,0.15)' },
        available: { label: 'Available', color: 'var(--accent)', bg: 'var(--accent-subtle)' },
        coming: { label: 'Coming soon', color: 'var(--warning)', bg: 'rgba(245,158,11,0.15)' },
    };

    let html = '<div class="max-w-5xl mx-auto space-y-6">';
    html += '<div class="flex items-center justify-between"><div><h2 class="text-base font-semibold" style="color:var(--text-primary);">Integrations & Connectors</h2><p class="text-[12px]" style="color:var(--text-muted);">Connect your agents to enterprise systems and communication channels.</p></div></div>';

    connectors.forEach(cat => {
        html += `<div><h3 class="text-[12px] font-semibold uppercase tracking-wider mb-3" style="color:var(--text-muted);">${cat.cat}</h3><div class="grid grid-cols-3 gap-3">`;
        cat.items.forEach(c => {
            const st = statusMap[c.status];
            html += `
            <div class="t-card rounded-xl p-4 transition-all cursor-pointer group">
                <div class="flex items-start justify-between mb-3">
                    <div class="w-9 h-9 rounded-lg flex items-center justify-center" style="background:var(--accent-subtle);">
                        <span class="material-icons-outlined text-lg" style="color:var(--accent);">${c.icon}</span>
                    </div>
                    <span class="px-2 py-0.5 text-[9px] font-medium rounded-md" style="background:${st.bg};color:${st.color};">${st.label}</span>
                </div>
                <h4 class="text-[13px] font-semibold mb-1" style="color:var(--text-primary);">${c.name}</h4>
                <p class="text-[11px] leading-relaxed" style="color:var(--text-muted);">${c.desc}</p>
            </div>`;
        });
        html += '</div></div>';
    });

    html += '</div>';
    return html;
}

export function page_orchestration() {
    return `
    <div class="max-w-5xl mx-auto space-y-6">
        <div class="flex items-center justify-between">
            <div>
                <h2 class="text-base font-semibold" style="color:var(--text-primary);">Orchestration Pipeline</h2>
                <p class="text-[12px]" style="color:var(--text-muted);">Visualize how agents execute queries through the processing pipeline.</p>
            </div>
        </div>

        <!-- DAG Visualization -->
        <div class="t-card rounded-xl p-6">
            <div class="flex items-center gap-2 mb-4">
                <span class="material-icons-outlined text-lg" style="color:var(--accent);">account_tree</span>
                <h3 class="text-[14px] font-semibold" style="color:var(--text-primary);">Execution DAG</h3>
            </div>
            <div class="flex items-center gap-2 flex-wrap" id="dag-pipeline">
                ${['Query Received','Query Rewrite','Embedding','Retrieval','Context Filter','Validation','Synthesis','Evaluation'].map((s, i) => `
                    <div class="flex items-center gap-2">
                        <div class="px-3 py-2 rounded-lg text-[11px] font-medium transition-all" style="background:var(--bg-elevated);border:1px solid var(--border-default);color:var(--text-secondary);">
                            <span class="text-[9px] font-bold mr-1.5" style="color:var(--accent);">${i+1}</span>${s}
                        </div>
                        ${i < 7 ? '<span class="material-icons-outlined text-xs" style="color:var(--text-muted);">arrow_forward</span>' : ''}
                    </div>
                `).join('')}
            </div>
        </div>

        <!-- Pipeline Details -->
        <div class="grid grid-cols-2 gap-3">
            <div class="t-card rounded-xl p-4">
                <h4 class="text-[12px] font-semibold mb-3" style="color:var(--text-primary);">Pipeline Components</h4>
                <div class="space-y-2">
                    <div class="flex items-center justify-between text-[11px]">
                        <span style="color:var(--text-secondary);">Query Rewriter</span>
                        <span class="font-mono px-2 py-0.5 rounded" style="background:var(--accent-subtle);color:var(--accent);">gpt-4o-mini</span>
                    </div>
                    <div class="flex items-center justify-between text-[11px]">
                        <span style="color:var(--text-secondary);">Embedder</span>
                        <span class="font-mono px-2 py-0.5 rounded" style="background:var(--accent-subtle);color:var(--accent);">text-embedding-3-small</span>
                    </div>
                    <div class="flex items-center justify-between text-[11px]">
                        <span style="color:var(--text-secondary);">Vector Store</span>
                        <span class="font-mono px-2 py-0.5 rounded" style="background:var(--accent-subtle);color:var(--accent);">FAISS (Hybrid)</span>
                    </div>
                    <div class="flex items-center justify-between text-[11px]">
                        <span style="color:var(--text-secondary);">Synthesis LLM</span>
                        <span class="font-mono px-2 py-0.5 rounded" style="background:var(--accent-subtle);color:var(--accent);">gpt-4o</span>
                    </div>
                    <div class="flex items-center justify-between text-[11px]">
                        <span style="color:var(--text-secondary);">Evaluator</span>
                        <span class="font-mono px-2 py-0.5 rounded" style="background:var(--accent-subtle);color:var(--accent);">ResponseEvaluator</span>
                    </div>
                </div>
            </div>
            <div class="t-card rounded-xl p-4">
                <h4 class="text-[12px] font-semibold mb-3" style="color:var(--text-primary);">Orchestration Features</h4>
                <div class="space-y-2.5">
                    <div class="flex items-start gap-2.5">
                        <span class="material-icons-outlined text-sm mt-0.5" style="color:var(--success);">check_circle</span>
                        <div>
                            <p class="text-[12px] font-medium" style="color:var(--text-primary);">Multi-agent routing</p>
                            <p class="text-[10px]" style="color:var(--text-muted);">Automatic intent detection and agent selection</p>
                        </div>
                    </div>
                    <div class="flex items-start gap-2.5">
                        <span class="material-icons-outlined text-sm mt-0.5" style="color:var(--success);">check_circle</span>
                        <div>
                            <p class="text-[12px] font-medium" style="color:var(--text-primary);">Real-time streaming</p>
                            <p class="text-[10px]" style="color:var(--text-muted);">SSE-based execution trace with step-by-step visibility</p>
                        </div>
                    </div>
                    <div class="flex items-start gap-2.5">
                        <span class="material-icons-outlined text-sm mt-0.5" style="color:var(--success);">check_circle</span>
                        <div>
                            <p class="text-[12px] font-medium" style="color:var(--text-primary);">Quality evaluation</p>
                            <p class="text-[10px]" style="color:var(--text-muted);">Factuality, relevance, coherence, and HHEM scoring</p>
                        </div>
                    </div>
                    <div class="flex items-start gap-2.5">
                        <span class="material-icons-outlined text-sm mt-0.5" style="color:var(--accent);">schedule</span>
                        <div>
                            <p class="text-[12px] font-medium" style="color:var(--text-primary);">Workflow builder</p>
                            <p class="text-[10px]" style="color:var(--text-muted);">Visual DAG editor for custom pipelines (coming soon)</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>`;
}
