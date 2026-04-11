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
        <div class="t-card rounded-xl p-4">
            <div class="flex items-center gap-2.5 mb-3">
                <div class="w-7 h-7 rounded-md flex items-center justify-center" style="background:rgba(139,92,246,0.15);">
                    <span class="material-icons-outlined text-purple-500 text-lg">model_training</span>
                </div>
                <div>
                    <h3 class="text-sm font-semibold" style="color:var(--text-primary);">Connect to a Model</h3>
                    <p class="text-[11px]" style="color:var(--text-muted);">Select the LLM provider and model</p>
                </div>
            </div>

            <div class="grid grid-cols-3 gap-2 mb-4">
                <div class="provider-card p-2.5 border-2 border-brand-500 rounded-lg cursor-pointer relative transition-all" style="background:var(--accent-subtle);" data-provider="openai" onclick="selectProvider(this)">
                    <span class="provider-check absolute top-1.5 right-1.5 w-3.5 h-3.5 rounded-full bg-brand-500 flex items-center justify-center">
                        <span class="material-icons-outlined text-white text-[9px]">check</span>
                    </span>
                    <p class="text-[13px] font-semibold" style="color:var(--text-primary);">OpenAI</p>
                    <p class="text-[10px] mt-0.5" style="color:var(--text-muted);">GPT-5, GPT-4.5, GPT-4o-mini</p>
                </div>
                <div class="provider-card p-2.5 rounded-lg cursor-pointer transition-all relative" style="border:1px solid var(--border-default);" data-provider="anthropic" onclick="selectProvider(this)">
                    <span class="provider-check hidden absolute top-1.5 right-1.5 w-3.5 h-3.5 rounded-full bg-brand-500 flex items-center justify-center">
                        <span class="material-icons-outlined text-white text-[9px]">check</span>
                    </span>
                    <p class="text-[13px] font-semibold" style="color:var(--text-primary);">Anthropic</p>
                    <p class="text-[10px] mt-0.5" style="color:var(--text-muted);">Opus 4.6, Sonnet 4.6, Haiku 4.5</p>
                </div>
                <div class="provider-card p-2.5 rounded-lg cursor-pointer transition-all relative" style="border:1px solid var(--border-default);" data-provider="selfhosted" onclick="selectProvider(this)">
                    <span class="provider-check hidden absolute top-1.5 right-1.5 w-3.5 h-3.5 rounded-full bg-brand-500 flex items-center justify-center">
                        <span class="material-icons-outlined text-white text-[9px]">check</span>
                    </span>
                    <p class="text-[13px] font-semibold" style="color:var(--text-primary);">Self-hosted</p>
                    <p class="text-[10px] mt-0.5" style="color:var(--text-muted);">Mistral 3, Gemma 4, Llama 3.1, Phi-4…</p>
                </div>
            </div>

            <div class="grid grid-cols-2 gap-3">
                <div>
                    <label class="text-[11px] font-medium mb-1 block" style="color:var(--text-muted);">Model</label>
                    <select id="model-select" class="t-input w-full px-3 py-1.5 border rounded-lg text-sm focus:ring-1 focus:ring-brand-500">
                        <option value="gpt-5" selected>GPT-5</option>
                        <option value="gpt-4.5">GPT-4.5</option>
                        <option value="gpt-4o-mini">GPT-4o-mini</option>
                    </select>
                </div>
                <div>
                    <label class="text-[11px] font-medium mb-1 block" style="color:var(--text-muted);">Temperature</label>
                    <input id="temp-slider" type="range" min="0" max="100" value="30" class="w-full" oninput="updateTempLabel(this)">
                    <p id="temp-label" class="text-[10px] mt-0.5" style="color:var(--text-muted);">0.3 — Precise and deterministic</p>
                </div>
            </div>
        </div>

        <div class="t-card rounded-xl p-4">
            <div class="flex items-center justify-between mb-2.5">
                <h4 class="text-[13px] font-semibold flex items-center gap-1.5" style="color:var(--text-primary);">
                    <span class="material-icons-outlined text-brand-500 text-base">tune</span>
                    Retrieval Settings
                </h4>
                <button id="save-rag-settings" onclick="saveRAGSettings()" class="px-2 py-1 text-[10px] font-medium rounded-lg transition-colors flex items-center gap-1" style="color:var(--accent);background:var(--accent-subtle);">
                    <span class="material-icons-outlined text-[11px]">save</span>
                    Save
                </button>
            </div>
            <div class="grid grid-cols-3 gap-3">
                <div>
                    <label class="text-[11px] font-medium mb-1 block" style="color:var(--text-muted);">Top-K results</label>
                    <input id="rag-topk" type="range" min="1" max="20" value="5" class="w-full" oninput="document.getElementById('rag-topk-val').textContent=this.value">
                    <p class="text-[10px] mt-0.5" style="color:var(--text-muted);">Chunks: <span id="rag-topk-val">5</span></p>
                </div>
                <div>
                    <label class="text-[11px] font-medium mb-1 block" style="color:var(--text-muted);">Vector weight</label>
                    <input id="rag-vweight" type="range" min="0" max="100" value="70" class="w-full" oninput="document.getElementById('rag-vweight-val').textContent=(this.value/100).toFixed(1)">
                    <p class="text-[10px] mt-0.5" style="color:var(--text-muted);">Weight: <span id="rag-vweight-val">0.7</span></p>
                </div>
                <div>
                    <label class="text-[11px] font-medium mb-1 block" style="color:var(--text-muted);">Similarity threshold</label>
                    <input id="rag-threshold" type="range" min="0" max="100" value="20" class="w-full" oninput="document.getElementById('rag-threshold-val').textContent=(this.value/100).toFixed(2)">
                    <p class="text-[10px] mt-0.5" style="color:var(--text-muted);">Min: <span id="rag-threshold-val">0.20</span></p>
                </div>
            </div>
        </div>

        <div class="t-card rounded-xl p-3" style="background:var(--bg-elevated);">
            <h4 class="text-[11px] font-semibold mb-2" style="color:var(--text-muted);">Platform Capabilities</h4>
            <div class="flex flex-wrap gap-1">
                <span class="px-2 py-0.5 text-[10px] font-medium rounded-md" style="background:var(--accent-subtle);color:var(--accent);">Multi-provider routing</span>
                <span class="px-2 py-0.5 text-[10px] font-medium rounded-md" style="background:rgba(139,92,246,0.12);color:#a78bfa;">Streaming (SSE)</span>
                <span class="px-2 py-0.5 text-[10px] font-medium rounded-md" style="background:rgba(16,185,129,0.12);color:#34d399;">Structured output</span>
                <span class="px-2 py-0.5 text-[10px] font-medium rounded-md" style="background:rgba(245,158,11,0.12);color:#fbbf24;">Query rewriting</span>
                <span class="px-2 py-0.5 text-[10px] font-medium rounded-md" style="background:var(--bg-elevated);color:var(--text-muted);border:1px solid var(--border-default);">Hybrid retrieval</span>
            </div>
        </div>
    </div>`;
}

export function step3_knowledgeUpload() {
    return `
    <div class="max-w-3xl mx-auto space-y-3">
        <div class="t-card rounded-xl p-4">
            <div class="flex items-center gap-2.5 mb-3">
                <div class="w-7 h-7 rounded-md flex items-center justify-center" style="background:rgba(16,185,129,0.15);">
                    <span class="material-icons-outlined text-emerald-500 text-lg">library_books</span>
                </div>
                <div>
                    <h3 class="text-sm font-semibold" style="color:var(--text-primary);">Knowledge Base</h3>
                    <p class="text-[11px]" style="color:var(--text-muted);">Upload documents for RAG retrieval</p>
                </div>
            </div>

            <div id="upload-zone" class="border border-dashed rounded-xl p-6 text-center cursor-pointer transition-colors" style="border-color:var(--border-default);">
                <span class="material-icons-outlined text-3xl mb-1" style="color:var(--text-muted);">cloud_upload</span>
                <p class="text-[13px] font-medium" style="color:var(--text-primary);">Drag & drop documents or click to browse</p>
                <p class="text-[11px] mt-0.5" style="color:var(--text-muted);">PDF, DOCX, TXT, Markdown &middot; Max 10 MB</p>
                <input id="file-input" type="file" class="hidden" accept=".pdf,.docx,.txt,.md" multiple>
            </div>

            <div id="uploaded-files" class="mt-3 space-y-1.5"></div>

            <button onclick="confirmResetKB()" class="w-full mt-2 flex items-center justify-center gap-1.5 px-3 py-1.5 text-[11px] font-medium text-red-500 rounded-lg transition-colors" style="border:1px solid rgba(239,68,68,0.3);background:rgba(239,68,68,0.08);">
                <span class="material-icons-outlined text-sm">delete_forever</span>
                Reset Knowledge Base
            </button>

            <div class="mt-3 pt-3" style="border-top:1px solid var(--border-default);">
                <h4 class="text-[12px] font-semibold mb-2" style="color:var(--text-secondary);">Knowledge Base</h4>
                <div class="space-y-1.5" id="preloaded-docs">
                    <p class="text-[11px]" style="color:var(--text-muted);">Loading…</p>
                </div>
            </div>
        </div>

        <div class="t-card rounded-xl p-3" style="background:var(--bg-elevated);">
            <h4 class="text-[11px] font-semibold mb-2" style="color:var(--text-muted);">RAG Pipeline</h4>
            <div class="flex items-center gap-1.5 text-[10px] flex-wrap">
                <span class="px-2 py-0.5 rounded-md font-mono" style="background:var(--bg-card);border:1px solid var(--border-default);color:var(--text-secondary);">Parse</span>
                <span class="material-icons-outlined text-[10px]" style="color:var(--text-muted);">arrow_forward</span>
                <span class="px-2 py-0.5 rounded-md font-mono" style="background:var(--bg-card);border:1px solid var(--border-default);color:var(--text-secondary);">Chunk</span>
                <span class="material-icons-outlined text-[10px]" style="color:var(--text-muted);">arrow_forward</span>
                <span class="px-2 py-0.5 rounded-md font-mono" style="background:var(--bg-card);border:1px solid var(--border-default);color:var(--text-secondary);">Embed</span>
                <span class="material-icons-outlined text-[10px]" style="color:var(--text-muted);">arrow_forward</span>
                <span class="px-2 py-0.5 rounded-md font-mono" style="background:var(--accent-subtle);color:var(--accent);">FAISS</span>
                <span class="material-icons-outlined text-[10px]" style="color:var(--text-muted);">arrow_forward</span>
                <span class="px-2 py-0.5 rounded-md font-mono" style="background:rgba(16,185,129,0.12);color:#34d399;">Hybrid Retrieval</span>
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
        <div class="relative t-card p-3 flex items-start gap-2.5 opacity-50 cursor-not-allowed select-none" style="border-radius:var(--radius);">
            <div class="w-7 h-7 flex items-center justify-center shrink-0" style="background:var(--bg-elevated);border-radius:var(--radius-sm);">
                <span class="material-icons-outlined ${c.icon} text-base">${t.icon}</span>
            </div>
            <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 mb-0.5">
                    <p class="text-[12px] font-semibold" style="color:var(--text-primary);">${t.name}</p>
                    <span class="px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-wider" style="background:rgba(245,158,11,0.12);color:var(--warning);border-radius:var(--radius-xs);">Soon</span>
                </div>
                <p class="text-[10px] leading-snug" style="color:var(--text-muted);">${t.desc}</p>
            </div>
        </div>`;
    }).join('');

    return `
    <div class="max-w-3xl mx-auto space-y-3">
        <div class="flex items-center gap-2.5">
            <div class="flex-1">
                <h2 class="text-[13px] font-semibold" style="color:var(--text-primary);">Tools</h2>
                <p class="text-[10px] mt-0.5" style="color:var(--text-muted);">Extend your agent with external capabilities.</p>
            </div>
            <div class="flex items-center gap-1.5 px-2 py-1 shrink-0" style="background:rgba(245,158,11,0.1);border:1px solid rgba(245,158,11,0.2);border-radius:var(--radius-sm);">
                <span class="material-icons-outlined text-sm" style="color:var(--warning);">construction</span>
                <span class="text-[10px] font-medium" style="color:var(--warning);">In development</span>
            </div>
        </div>

        <div class="grid grid-cols-2 gap-2">
            ${toolCards}
        </div>

        <div class="t-card p-3 flex items-start gap-2.5" style="background:var(--bg-elevated);border-radius:var(--radius);">
            <span class="material-icons-outlined text-base mt-0.5" style="color:var(--text-muted);">info</span>
            <div>
                <p class="text-[11px] font-medium" style="color:var(--text-primary);">Tool integrations are coming in the next release</p>
                <p class="text-[10px] mt-0.5" style="color:var(--text-muted);">Opt-in tools let your agent reach beyond the knowledge base — searching the web, running code, calling APIs, and more.</p>
            </div>
        </div>
    </div>`;
}

export function step5_governance() {
    return `
    <div class="max-w-3xl mx-auto space-y-3">
        <div class="t-card rounded-xl p-4">
            <div class="flex items-center gap-2.5 mb-3">
                <div class="w-7 h-7 rounded-md flex items-center justify-center" style="background:rgba(99,102,241,0.15);">
                    <span class="material-icons-outlined text-indigo-400 text-lg">security</span>
                </div>
                <div>
                    <h3 class="text-sm font-semibold" style="color:var(--text-primary);">Governance & Audit</h3>
                    <p class="text-[11px]" style="color:var(--text-muted);">Every action is logged, traceable, and auditable</p>
                </div>
            </div>

            <div class="grid grid-cols-3 gap-2 mb-4">
                <div class="p-2.5 rounded-lg" style="background:var(--bg-elevated);border:1px solid var(--border-default);">
                    <span class="material-icons-outlined text-indigo-400 text-lg mb-1">group</span>
                    <h4 class="text-[11px] font-semibold" style="color:var(--text-primary);">Access Control</h4>
                    <p class="text-[10px] mt-0.5" style="color:var(--text-muted);">OIDC / SSO (Keycloak)</p>
                    <div class="mt-1.5 flex gap-2">
                        <span class="flex items-center gap-1 text-[9px]" style="color:var(--text-muted);"><span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>Admin</span>
                        <span class="flex items-center gap-1 text-[9px]" style="color:var(--text-muted);"><span class="w-1.5 h-1.5 rounded-full" style="background:var(--text-muted);"></span>User</span>
                    </div>
                </div>
                <div class="p-2.5 rounded-lg" style="background:var(--bg-elevated);border:1px solid var(--border-default);">
                    <span class="material-icons-outlined text-amber-500 text-lg mb-1">receipt_long</span>
                    <h4 class="text-[11px] font-semibold" style="color:var(--text-primary);">Audit Trail</h4>
                    <p class="text-[10px] mt-0.5" style="color:var(--text-muted);">Full execution logging</p>
                    <p class="text-[10px] text-amber-500 font-mono mt-1.5" id="audit-count">Loading...</p>
                </div>
                <div class="p-2.5 rounded-lg" style="background:var(--bg-elevated);border:1px solid var(--border-default);">
                    <span class="material-icons-outlined text-emerald-500 text-lg mb-1">visibility</span>
                    <h4 class="text-[11px] font-semibold" style="color:var(--text-primary);">Execution Tracing</h4>
                    <p class="text-[10px] mt-0.5" style="color:var(--text-muted);">Pipeline steps with timing</p>
                    <p class="text-[10px] text-emerald-500 font-mono mt-1.5">Real-time SSE</p>
                </div>
            </div>

            <div class="p-3 rounded-lg" style="background:var(--bg-elevated);border:1px solid var(--border-default);">
                <h4 class="text-[10px] font-bold uppercase tracking-wider mb-2" style="color:var(--text-muted);">Recent Audit Events</h4>
                <div id="audit-logs" class="space-y-1.5 text-[11px] font-mono" style="color:var(--text-secondary);">
                    <p style="color:var(--text-muted);">No events yet. Execute the agent to generate audit entries.</p>
                </div>
            </div>
        </div>
    </div>`;
}

// -- Sidebar pages --

export function page_knowledgeBase() {
    return `
    <div class="max-w-3xl mx-auto space-y-3">
        <div class="t-card p-4" style="border-radius:var(--radius);">
            <div class="flex items-center justify-between mb-3">
                <div class="flex items-center gap-2.5">
                    <div class="w-7 h-7 flex items-center justify-center" style="background:rgba(16,185,129,0.12);border-radius:var(--radius-sm);">
                        <span class="material-icons-outlined text-base" style="color:var(--success);">library_books</span>
                    </div>
                    <div>
                        <h3 class="text-[13px] font-semibold" style="color:var(--text-primary);">Knowledge Base</h3>
                        <p class="text-[10px]" style="color:var(--text-muted);">Documents indexed for retrieval</p>
                    </div>
                </div>
                <div id="kb-stats" class="text-right">
                    <p class="text-[14px] font-semibold" style="color:var(--text-primary);">—</p>
                    <p class="text-[9px] uppercase tracking-wider" style="color:var(--text-muted);">chunks indexed</p>
                </div>
            </div>

            <div class="grid grid-cols-3 gap-2 mb-3">
                <div class="p-2 text-center" style="background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:var(--radius-sm);">
                    <p class="text-[15px] font-bold" style="color:var(--success);" id="kb-doc-count">—</p>
                    <p class="text-[9px] uppercase tracking-wider" style="color:var(--text-muted);">Documents</p>
                </div>
                <div class="p-2 text-center" style="background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:var(--radius-sm);">
                    <p class="text-[15px] font-bold" style="color:var(--accent);" id="kb-chunk-count">—</p>
                    <p class="text-[9px] uppercase tracking-wider" style="color:var(--text-muted);">Chunks</p>
                </div>
                <div class="p-2 text-center" style="background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:var(--radius-sm);">
                    <p class="text-[15px] font-bold" style="color:var(--info);" id="kb-vector-dim">—</p>
                    <p class="text-[9px] uppercase tracking-wider" style="color:var(--text-muted);">Vector dims</p>
                </div>
            </div>

            <div id="upload-zone" class="border border-dashed p-4 text-center cursor-pointer transition-colors" style="border-color:var(--border-default);border-radius:var(--radius);">
                <span class="material-icons-outlined text-2xl mb-1" style="color:var(--text-muted);">cloud_upload</span>
                <p class="text-[12px] font-medium" style="color:var(--text-primary);">Upload documents</p>
                <p class="text-[10px] mt-0.5" style="color:var(--text-muted);">PDF, DOCX, TXT, Markdown</p>
                <input id="file-input" type="file" class="hidden" accept=".pdf,.docx,.txt,.md" multiple>
            </div>
            <div id="uploaded-files" class="mt-2 space-y-1"></div>

            <button onclick="confirmResetKB()" class="w-full mt-2 flex items-center justify-center gap-1.5 px-3 py-1.5 text-[10px] font-medium text-red-500 transition-colors" style="border:1px solid rgba(239,68,68,0.2);background:rgba(239,68,68,0.06);border-radius:var(--radius-sm);">
                <span class="material-icons-outlined text-sm">delete_forever</span>
                Reset Knowledge Base
            </button>

            <div class="pt-3 mt-2" style="border-top:1px solid var(--border-default);">
                <h4 class="text-[10px] font-semibold uppercase tracking-wider mb-2" style="color:var(--text-muted);">Indexed Documents</h4>
                <div class="space-y-1" id="kb-documents">
                    <p class="text-[11px]" style="color:var(--text-muted);">Loading documents…</p>
                </div>
            </div>
        </div>

        <div class="t-card p-3" style="background:var(--bg-elevated);border-radius:var(--radius);">
            <h4 class="text-[10px] font-semibold uppercase tracking-wider mb-2" style="color:var(--text-muted);">Retrieval Pipeline</h4>
            <div class="flex items-center gap-1.5 text-[10px] flex-wrap">
                <span class="px-2 py-0.5 font-mono" style="background:var(--bg-card);border:1px solid var(--border-default);color:var(--text-secondary);border-radius:var(--radius-xs);">Parse</span>
                <span class="material-icons-outlined text-[10px]" style="color:var(--text-muted);">arrow_forward</span>
                <span class="px-2 py-0.5 font-mono" style="background:var(--bg-card);border:1px solid var(--border-default);color:var(--text-secondary);border-radius:var(--radius-xs);">Chunk</span>
                <span class="material-icons-outlined text-[10px]" style="color:var(--text-muted);">arrow_forward</span>
                <span class="px-2 py-0.5 font-mono" style="background:var(--bg-card);border:1px solid var(--border-default);color:var(--text-secondary);border-radius:var(--radius-xs);">Embed</span>
                <span class="material-icons-outlined text-[10px]" style="color:var(--text-muted);">arrow_forward</span>
                <span class="px-2 py-0.5 font-mono" style="background:var(--accent-subtle);color:var(--accent);border-radius:var(--radius-xs);">FAISS</span>
                <span class="material-icons-outlined text-[10px]" style="color:var(--text-muted);">arrow_forward</span>
                <span class="px-2 py-0.5 font-mono" style="background:rgba(16,185,129,0.1);color:var(--success);border-radius:var(--radius-xs);">Hybrid Retrieval</span>
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
        { initials: 'ED', name: 'Enzo Damion', email: 'enzo.damion@presight.ai', color: 'indigo', role: 'Admin' },
    ];

    const currentEmail = (typeof currentUser !== 'undefined') ? currentUser.email : '';

    const sessionRows = users.map(u => {
        const isMe = u.email === currentEmail;
        const status = isMe
            ? '<span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span><span class="text-[10px] font-medium" style="color:var(--success);">Active</span>'
            : '<span class="w-1.5 h-1.5 rounded-full" style="background:var(--text-muted);"></span><span class="text-[10px]" style="color:var(--text-muted);">Offline</span>';
        const bg = isMe ? 'background:var(--accent-subtle);border:1px solid var(--border-active);' : 'background:var(--bg-elevated);border:1px solid var(--border-default);';
        return `<div class="flex items-center justify-between p-2 text-[11px]" style="${bg}border-radius:var(--radius-sm);">
            <div class="flex items-center gap-2">
                <div class="w-5 h-5 flex items-center justify-center text-[8px] font-bold text-white" style="background:var(--accent);border-radius:var(--radius-xs);">${u.initials}</div>
                <div>
                    <p class="font-medium text-[11px]" style="color:var(--text-primary);">${u.name}${isMe ? ' <span class="text-[9px] font-normal" style="color:var(--accent);">(you)</span>' : ''}</p>
                    <p class="text-[9px] font-mono" style="color:var(--text-muted);">${u.email}</p>
                </div>
            </div>
            <div class="flex items-center gap-2">
                <span class="px-1.5 py-0.5 text-[8px] font-medium" style="background:var(--bg-card);border:1px solid var(--border-default);color:var(--text-secondary);border-radius:var(--radius-xs);">${u.role}</span>
                <div class="flex items-center gap-1">${status}</div>
            </div>
        </div>`;
    }).join('');

    return `
    <div class="max-w-3xl mx-auto space-y-3">
        <div class="t-card p-4" style="border-radius:var(--radius);">
            <div class="flex items-center justify-between mb-3">
                <div class="flex items-center gap-2.5">
                    <div class="w-7 h-7 flex items-center justify-center" style="background:rgba(99,102,241,0.12);border-radius:var(--radius-sm);">
                        <span class="material-icons-outlined text-base" style="color:var(--info);">group</span>
                    </div>
                    <div>
                        <h3 class="text-[13px] font-semibold" style="color:var(--text-primary);">Access & Roles</h3>
                        <p class="text-[10px]" style="color:var(--text-muted);">Role-based access control via OIDC / Keycloak</p>
                    </div>
                </div>
                <button id="invite-btn" onclick="toggleInviteForm()" class="px-2 py-1 text-[10px] font-medium transition-colors flex items-center gap-1" style="color:var(--accent);background:var(--accent-subtle);border-radius:var(--radius-sm);">
                    <span class="material-icons-outlined text-sm">person_add</span>
                    Invite
                </button>
            </div>

            <div id="invite-form" class="hidden mb-3 p-3 space-y-2 transition-all" style="background:var(--accent-subtle);border:1px solid var(--border-active);border-radius:var(--radius);">
                <div class="flex items-center gap-1.5 mb-0.5">
                    <span class="material-icons-outlined text-sm" style="color:var(--accent);">mail_outline</span>
                    <span class="text-[10px] font-semibold" style="color:var(--text-primary);">Invite a new member</span>
                </div>
                <div class="grid grid-cols-5 gap-2">
                    <input id="invite-email" type="email" placeholder="name@company.com" class="t-input col-span-3 px-2.5 py-1.5 border text-[12px] focus:ring-1 focus:ring-brand-500" style="border-radius:var(--radius-sm);">
                    <select id="invite-role" class="t-input col-span-1 px-2 py-1.5 border text-[12px] focus:ring-1 focus:ring-brand-500" style="border-radius:var(--radius-sm);">
                        <option>User</option>
                        <option>Admin</option>
                    </select>
                    <button onclick="sendInvite()" class="col-span-1 px-2 py-1.5 text-[12px] font-medium text-white transition-colors" style="background:var(--accent);border-radius:var(--radius-sm);">Send</button>
                </div>
            </div>

            <div class="p-2.5 mb-3" style="background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:var(--radius);">
                <div class="flex items-center gap-1.5 mb-1.5">
                    <span class="material-icons-outlined text-sm" style="color:var(--info);">shield</span>
                    <span class="text-[10px] font-semibold" style="color:var(--text-primary);">Identity Provider</span>
                </div>
                <div class="grid grid-cols-2 gap-1.5 text-[10px]">
                    <div><span style="color:var(--text-muted);">Provider:</span> <span class="font-medium" style="color:var(--text-primary);">Keycloak 24.x</span></div>
                    <div><span style="color:var(--text-muted);">Protocol:</span> <span class="font-medium" style="color:var(--text-primary);">OIDC / OAuth 2.0</span></div>
                    <div><span style="color:var(--text-muted);">Realm:</span> <span class="font-medium" style="color:var(--text-primary);">enterprise</span></div>
                    <div><span style="color:var(--text-muted);">SSO:</span> <span class="font-medium" style="color:var(--success);">Enabled</span></div>
                </div>
            </div>

            <h4 class="text-[10px] font-semibold uppercase tracking-wider mb-1.5" style="color:var(--text-muted);">Roles</h4>
            <div class="space-y-1 mb-3">
                <div class="flex items-center justify-between p-2" style="border:1px solid var(--border-default);border-radius:var(--radius-sm);">
                    <div class="flex items-center gap-2">
                        <span class="w-1.5 h-1.5 rounded-full" style="background:var(--success);"></span>
                        <div>
                            <p class="text-[11px] font-medium" style="color:var(--text-primary);">Admin</p>
                            <p class="text-[9px]" style="color:var(--text-muted);">Full platform access, agent management, user management</p>
                        </div>
                    </div>
                    <span class="px-1.5 py-0.5 text-[8px] font-medium" style="background:rgba(16,185,129,0.1);color:var(--success);border-radius:var(--radius-xs);">4 users</span>
                </div>
                <div class="flex items-center justify-between p-2" style="border:1px solid var(--border-default);border-radius:var(--radius-sm);">
                    <div class="flex items-center gap-2">
                        <span class="w-1.5 h-1.5 rounded-full" style="background:var(--text-muted);"></span>
                        <div>
                            <p class="text-[11px] font-medium" style="color:var(--text-primary);">User</p>
                            <p class="text-[9px]" style="color:var(--text-muted);">Execute agents, upload documents, view own results</p>
                        </div>
                    </div>
                    <span class="px-1.5 py-0.5 text-[8px] font-medium" style="background:var(--bg-elevated);border:1px solid var(--border-default);color:var(--text-secondary);border-radius:var(--radius-xs);">1 user</span>
                </div>
            </div>

            <div class="pt-2.5" style="border-top:1px solid var(--border-default);">
                <div class="flex items-center justify-between mb-1.5">
                    <h4 class="text-[10px] font-semibold uppercase tracking-wider" style="color:var(--text-muted);">Workspace Members</h4>
                    <span class="text-[9px] font-mono" style="color:var(--text-muted);">5 members</span>
                </div>
                <div class="space-y-1">
                    ${sessionRows}
                </div>
            </div>
        </div>
    </div>`;
}

export function page_auditLogs() {
    return `
    <div class="max-w-3xl mx-auto space-y-3">
        <div class="t-card p-4" style="border-radius:var(--radius);">
            <div class="flex items-center justify-between mb-3">
                <div class="flex items-center gap-2.5">
                    <div class="w-7 h-7 flex items-center justify-center" style="background:rgba(245,158,11,0.12);border-radius:var(--radius-sm);">
                        <span class="material-icons-outlined text-base" style="color:var(--warning);">receipt_long</span>
                    </div>
                    <div>
                        <h3 class="text-[13px] font-semibold" style="color:var(--text-primary);">Audit Logs</h3>
                        <p class="text-[10px]" style="color:var(--text-muted);">Execution history and compliance events</p>
                    </div>
                </div>
                <div id="audit-page-stats" class="text-right">
                    <p class="text-[14px] font-semibold" style="color:var(--text-primary);">—</p>
                    <p class="text-[9px] uppercase tracking-wider" style="color:var(--text-muted);">total events</p>
                </div>
            </div>

            <div class="overflow-hidden" style="border:1px solid var(--border-default);border-radius:var(--radius);">
                <table class="w-full text-[10px]">
                    <thead>
                        <tr style="background:var(--bg-elevated);">
                            <th class="text-left px-3 py-1.5 text-[8px] font-semibold uppercase tracking-wider" style="color:var(--text-muted);">Time</th>
                            <th class="text-left px-3 py-1.5 text-[8px] font-semibold uppercase tracking-wider" style="color:var(--text-muted);">Event</th>
                            <th class="text-left px-3 py-1.5 text-[8px] font-semibold uppercase tracking-wider" style="color:var(--text-muted);">Actor</th>
                            <th class="text-left px-3 py-1.5 text-[8px] font-semibold uppercase tracking-wider" style="color:var(--text-muted);">Agent</th>
                            <th class="text-left px-3 py-1.5 text-[8px] font-semibold uppercase tracking-wider" style="color:var(--text-muted);">Severity</th>
                        </tr>
                    </thead>
                    <tbody id="audit-table-body">
                        <tr><td colspan="5" class="px-3 py-4 text-center text-[11px]" style="color:var(--text-muted);">Loading audit events...</td></tr>
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
                            <p class="text-[13px]" style="color:var(--text-muted);">${welcome}</p>
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
    <div class="max-w-3xl mx-auto space-y-3">
        <div class="t-card p-4" style="border-radius:var(--radius);">
            <div class="flex items-center gap-2.5 mb-4">
                <div class="w-7 h-7 flex items-center justify-center" style="background:var(--accent-subtle);border-radius:var(--radius-sm);">
                    <span class="material-icons-outlined text-base" style="color:var(--accent);">smart_toy</span>
                </div>
                <div>
                    <h3 class="text-[13px] font-semibold" style="color:var(--text-primary);">Review & Save</h3>
                    <p class="text-[10px]" style="color:var(--text-muted);">Confirm your agent configuration before saving</p>
                </div>
            </div>

            <div class="grid grid-cols-2 gap-2 mb-4">
                <div class="p-2.5" style="background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:var(--radius-sm);">
                    <p class="text-[9px] font-semibold uppercase tracking-wider mb-0.5" style="color:var(--text-muted);">Agent Name</p>
                    <p class="text-[12px] font-medium" style="color:var(--text-primary);">${name}</p>
                </div>
                <div class="p-2.5" style="background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:var(--radius-sm);">
                    <p class="text-[9px] font-semibold uppercase tracking-wider mb-0.5" style="color:var(--text-muted);">Type</p>
                    <p class="text-[12px] font-medium" style="color:var(--text-primary);">${type}</p>
                </div>
                <div class="p-2.5" style="background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:var(--radius-sm);">
                    <p class="text-[9px] font-semibold uppercase tracking-wider mb-0.5" style="color:var(--text-muted);">Model</p>
                    <p class="text-[12px] font-medium font-mono" style="color:var(--text-primary);">${model}</p>
                </div>
                <div class="p-2.5" style="background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:var(--radius-sm);">
                    <p class="text-[9px] font-semibold uppercase tracking-wider mb-0.5" style="color:var(--text-muted);">Provider</p>
                    <p class="text-[12px] font-medium" style="color:var(--text-primary);">${providerLabel}</p>
                </div>
                <div class="p-2.5 col-span-2" style="background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:var(--radius-sm);">
                    <p class="text-[9px] font-semibold uppercase tracking-wider mb-1" style="color:var(--text-muted);">Temperature</p>
                    <div class="flex items-center gap-3">
                        <div class="flex-1 h-1" style="background:var(--border-default);border-radius:1px;">
                            <div class="h-1" style="width:${Math.round(temp * 100)}%;background:var(--accent);border-radius:1px;"></div>
                        </div>
                        <span class="text-[11px] font-mono shrink-0" style="color:var(--text-secondary);">${temp.toFixed(2)}</span>
                    </div>
                </div>
                ${prompt ? `
                <div class="p-2.5 col-span-2" style="background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:var(--radius-sm);">
                    <p class="text-[9px] font-semibold uppercase tracking-wider mb-0.5" style="color:var(--text-muted);">System Prompt</p>
                    <p class="text-[11px] font-mono leading-relaxed line-clamp-3" style="color:var(--text-secondary);">${prompt.slice(0, 220)}${prompt.length > 220 ? '…' : ''}</p>
                </div>` : ''}
            </div>

            <div id="step7-actions">
                <button onclick="saveCurrentAgent()" class="w-full py-2 px-4 text-white text-[12px] font-semibold transition-colors flex items-center justify-center gap-2" style="background:var(--accent);border-radius:var(--radius-sm);">
                    <span class="material-icons-outlined text-sm">save</span>
                    Save Agent
                </button>
            </div>
        </div>

        <div class="t-card p-3 flex items-start gap-2" style="background:var(--bg-elevated);border-radius:var(--radius);">
            <span class="material-icons-outlined text-sm mt-0.5" style="color:var(--text-muted);">info</span>
            <p class="text-[10px]" style="color:var(--text-muted);">Saved agents appear in the <strong style="color:var(--text-secondary);">Agent Hub</strong>. Click <strong style="color:var(--text-secondary);">Chat</strong> on any agent to start a session.</p>
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
        <div class="grid grid-cols-4 gap-2 mb-5">
            <div class="t-card p-3" style="border-radius:var(--radius);">
                <div class="flex items-center justify-between mb-1.5">
                    <span class="text-[9px] font-semibold uppercase tracking-wider" style="color:var(--text-muted);">Active Agents</span>
                    <span class="material-icons-outlined text-sm" style="color:var(--accent);">hub</span>
                </div>
                <p class="text-lg font-bold" style="color:var(--text-primary);">4</p>
                <p class="text-[9px] mt-0.5" style="color:var(--success);">All operational</p>
            </div>
            <div class="t-card p-3" style="border-radius:var(--radius);">
                <div class="flex items-center justify-between mb-1.5">
                    <span class="text-[9px] font-semibold uppercase tracking-wider" style="color:var(--text-muted);">Knowledge</span>
                    <span class="material-icons-outlined text-sm" style="color:var(--info);">library_books</span>
                </div>
                <p class="text-lg font-bold" id="hub-kb-count" style="color:var(--text-primary);">—</p>
                <p class="text-[9px] mt-0.5" style="color:var(--text-muted);">Chunks indexed</p>
            </div>
            <div class="t-card p-3" style="border-radius:var(--radius);">
                <div class="flex items-center justify-between mb-1.5">
                    <span class="text-[9px] font-semibold uppercase tracking-wider" style="color:var(--text-muted);">Integrations</span>
                    <span class="material-icons-outlined text-sm" style="color:var(--warning);">cable</span>
                </div>
                <p class="text-lg font-bold" style="color:var(--text-primary);">12</p>
                <p class="text-[9px] mt-0.5" style="color:var(--text-muted);">Connectors</p>
            </div>
            <div class="t-card p-3" style="border-radius:var(--radius);">
                <div class="flex items-center justify-between mb-1.5">
                    <span class="text-[9px] font-semibold uppercase tracking-wider" style="color:var(--text-muted);">Avg. Latency</span>
                    <span class="material-icons-outlined text-sm" style="color:var(--success);">speed</span>
                </div>
                <p class="text-lg font-bold" style="color:var(--text-primary);">2.4s</p>
                <p class="text-[9px] mt-0.5" style="color:var(--success);">Within SLA</p>
            </div>
        </div>

        <!-- Agent Cards -->
        <div class="flex items-center justify-between mb-3">
            <div>
                <h2 class="text-[14px] font-semibold" style="color:var(--text-primary);">Agents</h2>
                <p class="text-[11px]" style="color:var(--text-muted);">Select an agent to start a conversation, or create a new one.</p>
            </div>
            <button onclick="goToStep(1)" class="px-2.5 py-1.5 text-[11px] font-medium text-white transition-all flex items-center gap-1" style="background:var(--accent);border-radius:var(--radius-sm);">
                <span class="material-icons-outlined text-sm">add</span>
                New Agent
            </button>
        </div>

        <div class="grid grid-cols-3 gap-2" id="hub-agents-grid">
            <div class="t-card p-4 flex items-center justify-center" style="min-height:160px;border-radius:var(--radius);">
                <span class="text-[11px]" style="color:var(--text-muted);">Loading agents…</span>
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

    let html = '<div class="max-w-5xl mx-auto space-y-5">';
    html += '<div><h2 class="text-[14px] font-semibold" style="color:var(--text-primary);">Integrations & Connectors</h2><p class="text-[11px]" style="color:var(--text-muted);">Connect your agents to enterprise systems and communication channels.</p></div>';

    connectors.forEach(cat => {
        html += `<div><h3 class="text-[10px] font-semibold uppercase tracking-wider mb-2" style="color:var(--text-muted);">${cat.cat}</h3><div class="grid grid-cols-3 gap-2">`;
        cat.items.forEach(c => {
            const st = statusMap[c.status];
            html += `
            <div class="t-card p-3 cursor-pointer" style="border-radius:var(--radius);">
                <div class="flex items-start justify-between mb-2">
                    <div class="w-7 h-7 flex items-center justify-center" style="background:var(--accent-subtle);border-radius:var(--radius-sm);">
                        <span class="material-icons-outlined text-base" style="color:var(--accent);">${c.icon}</span>
                    </div>
                    <span class="px-1.5 py-0.5 text-[8px] font-medium" style="background:${st.bg};color:${st.color};border-radius:var(--radius-xs);">${st.label}</span>
                </div>
                <h4 class="text-[12px] font-semibold mb-0.5" style="color:var(--text-primary);">${c.name}</h4>
                <p class="text-[10px] leading-relaxed" style="color:var(--text-muted);">${c.desc}</p>
            </div>`;
        });
        html += '</div></div>';
    });

    html += '</div>';
    return html;
}

export function page_orchestration() {
    return `
    <div class="max-w-5xl mx-auto space-y-4">
        <div>
            <h2 class="text-[14px] font-semibold" style="color:var(--text-primary);">Orchestration Pipeline</h2>
            <p class="text-[11px]" style="color:var(--text-muted);">Visualize how agents execute queries through the processing pipeline.</p>
        </div>

        <!-- DAG Visualization -->
        <div class="t-card p-4" style="border-radius:var(--radius);">
            <div class="flex items-center gap-2 mb-3">
                <span class="material-icons-outlined text-base" style="color:var(--accent);">account_tree</span>
                <h3 class="text-[13px] font-semibold" style="color:var(--text-primary);">Execution DAG</h3>
            </div>
            <div class="flex items-center gap-1.5 flex-wrap" id="dag-pipeline">
                ${['Query Received','Query Rewrite','Embedding','Retrieval','Context Filter','Validation','Synthesis','Evaluation'].map((s, i) => `
                    <div class="flex items-center gap-1.5">
                        <div class="px-2 py-1.5 text-[10px] font-medium" style="background:var(--bg-elevated);border:1px solid var(--border-default);color:var(--text-secondary);border-radius:var(--radius-sm);">
                            <span class="text-[8px] font-bold mr-1 font-mono" style="color:var(--accent);">${i+1}</span>${s}
                        </div>
                        ${i < 7 ? '<span class="material-icons-outlined text-[10px]" style="color:var(--text-muted);">arrow_forward</span>' : ''}
                    </div>
                `).join('')}
            </div>
        </div>

        <!-- Pipeline Details -->
        <div class="grid grid-cols-2 gap-2">
            <div class="t-card p-3" style="border-radius:var(--radius);">
                <h4 class="text-[11px] font-semibold mb-2" style="color:var(--text-primary);">Pipeline Components</h4>
                <div class="space-y-1.5">
                    <div class="flex items-center justify-between text-[10px]">
                        <span style="color:var(--text-secondary);">Query Rewriter</span>
                        <span class="font-mono px-1.5 py-0.5" style="background:var(--accent-subtle);color:var(--accent);border-radius:var(--radius-xs);">gpt-4o-mini</span>
                    </div>
                    <div class="flex items-center justify-between text-[10px]">
                        <span style="color:var(--text-secondary);">Embedder</span>
                        <span class="font-mono px-1.5 py-0.5" style="background:var(--accent-subtle);color:var(--accent);border-radius:var(--radius-xs);">text-embedding-3-small</span>
                    </div>
                    <div class="flex items-center justify-between text-[10px]">
                        <span style="color:var(--text-secondary);">Vector Store</span>
                        <span class="font-mono px-1.5 py-0.5" style="background:var(--accent-subtle);color:var(--accent);border-radius:var(--radius-xs);">FAISS (Hybrid)</span>
                    </div>
                    <div class="flex items-center justify-between text-[10px]">
                        <span style="color:var(--text-secondary);">Synthesis LLM</span>
                        <span class="font-mono px-1.5 py-0.5" style="background:var(--accent-subtle);color:var(--accent);border-radius:var(--radius-xs);">gpt-4o</span>
                    </div>
                    <div class="flex items-center justify-between text-[10px]">
                        <span style="color:var(--text-secondary);">Evaluator</span>
                        <span class="font-mono px-1.5 py-0.5" style="background:var(--accent-subtle);color:var(--accent);border-radius:var(--radius-xs);">ResponseEvaluator</span>
                    </div>
                </div>
            </div>
            <div class="t-card p-3" style="border-radius:var(--radius);">
                <h4 class="text-[11px] font-semibold mb-2" style="color:var(--text-primary);">Orchestration Features</h4>
                <div class="space-y-2">
                    <div class="flex items-start gap-2">
                        <span class="material-icons-outlined text-xs mt-0.5" style="color:var(--success);">check_circle</span>
                        <div>
                            <p class="text-[11px] font-medium" style="color:var(--text-primary);">Multi-agent routing</p>
                            <p class="text-[9px]" style="color:var(--text-muted);">Automatic intent detection and agent selection</p>
                        </div>
                    </div>
                    <div class="flex items-start gap-2">
                        <span class="material-icons-outlined text-xs mt-0.5" style="color:var(--success);">check_circle</span>
                        <div>
                            <p class="text-[11px] font-medium" style="color:var(--text-primary);">Real-time streaming</p>
                            <p class="text-[9px]" style="color:var(--text-muted);">SSE-based execution trace with step-by-step visibility</p>
                        </div>
                    </div>
                    <div class="flex items-start gap-2">
                        <span class="material-icons-outlined text-xs mt-0.5" style="color:var(--success);">check_circle</span>
                        <div>
                            <p class="text-[11px] font-medium" style="color:var(--text-primary);">Quality evaluation</p>
                            <p class="text-[9px]" style="color:var(--text-muted);">Factuality, relevance, coherence, and HHEM scoring</p>
                        </div>
                    </div>
                    <div class="flex items-start gap-2">
                        <span class="material-icons-outlined text-xs mt-0.5" style="color:var(--accent);">schedule</span>
                        <div>
                            <p class="text-[11px] font-medium" style="color:var(--text-primary);">Workflow builder</p>
                            <p class="text-[9px]" style="color:var(--text-muted);">Visual DAG editor for custom pipelines (coming soon)</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>`;
}
