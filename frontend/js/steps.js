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
        { id: 'web_search',      icon: 'travel_explore', name: 'Web Search',        desc: 'Search the internet for real-time information and news', status: 'beta' },
        { id: 'code_interpreter', icon: 'code',          name: 'Code Interpreter',  desc: 'Execute Python scripts and analyze data programmatically', status: 'beta' },
        { id: 'sql_query',       icon: 'table_chart',    name: 'SQL Query',         desc: 'Query structured databases and export results', status: 'ready' },
        { id: 'api_connector',   icon: 'api',            name: 'API Connector',     desc: 'Call external REST APIs with custom authentication', status: 'ready' },
        { id: 'email_sender',    icon: 'mail',           name: 'Email Sender',      desc: 'Draft and send emails from agent workflows', status: 'ready' },
        { id: 'file_generator',  icon: 'picture_as_pdf', name: 'File Generator',    desc: 'Export agent output as PDF, Excel, or CSV', status: 'beta' },
        { id: 'calendar_access', icon: 'calendar_today', name: 'Calendar Access',   desc: 'Read and write calendar events and schedules', status: 'beta' },
        { id: 'memory',          icon: 'memory',         name: 'Persistent Memory', desc: 'Store and retrieve context across sessions', status: 'ready' },
    ];
    const statusBadge = { ready: { label: 'Ready', color: 'var(--success)' }, beta: { label: 'Beta', color: 'var(--warning)' } };
    const savedTools = JSON.parse(localStorage.getItem('aip_tools') || '{}');

    const toolCards = tools.map(t => {
        const enabled = savedTools[t.id] || false;
        const sb = statusBadge[t.status];
        return `
        <div class="t-card p-3 cursor-pointer transition-all" style="border-radius:var(--radius);border-color:${enabled ? 'var(--border-active)' : 'var(--border-default)'};" onclick="toggleTool('${t.id}', this)">
            <div class="flex items-start justify-between mb-1.5">
                <div class="w-7 h-7 flex items-center justify-center shrink-0" style="background:${enabled ? 'var(--accent-subtle)' : 'var(--bg-elevated)'};border-radius:var(--radius-sm);">
                    <span class="material-icons-outlined text-base" style="color:${enabled ? 'var(--accent)' : 'var(--text-muted)'};">${t.icon}</span>
                </div>
                <div class="flex items-center gap-1.5">
                    <span class="px-1.5 py-0.5 text-[8px] font-medium" style="background:${sb.color}15;color:${sb.color};border-radius:var(--radius-xs);">${sb.label}</span>
                    <div class="w-7 h-4 rounded-full relative" style="background:${enabled ? 'var(--accent)' : 'var(--border-default)'};">
                        <div class="w-3 h-3 rounded-full bg-white absolute top-0.5 transition-all" style="left:${enabled ? '14px' : '2px'};"></div>
                    </div>
                </div>
            </div>
            <p class="text-[11px] font-semibold" style="color:var(--text-primary);">${t.name}</p>
            <p class="text-[9px] leading-snug mt-0.5" style="color:var(--text-muted);">${t.desc}</p>
        </div>`;
    }).join('');

    const enabledCount = Object.values(savedTools).filter(Boolean).length;

    return `
    <div class="max-w-3xl mx-auto space-y-3">
        <div class="flex items-center gap-2.5">
            <div class="flex-1">
                <h2 class="text-[13px] font-semibold" style="color:var(--text-primary);">Tools</h2>
                <p class="text-[10px] mt-0.5" style="color:var(--text-muted);">Enable or disable agent capabilities. Changes are saved automatically.</p>
            </div>
            <div class="flex items-center gap-1.5 px-2 py-1 shrink-0" style="background:var(--accent-subtle);border:1px solid var(--border-active);border-radius:var(--radius-sm);">
                <span class="material-icons-outlined text-sm" style="color:var(--accent);">extension</span>
                <span id="tools-count" class="text-[10px] font-medium" style="color:var(--accent);">${enabledCount} active</span>
            </div>
        </div>

        <div class="grid grid-cols-2 gap-2">${toolCards}</div>

        <div class="t-card p-3 flex items-start gap-2.5" style="background:var(--bg-elevated);border-radius:var(--radius);">
            <span class="material-icons-outlined text-base mt-0.5" style="color:var(--accent);">lightbulb</span>
            <div>
                <p class="text-[11px] font-medium" style="color:var(--text-primary);">Tools extend your agent's reach</p>
                <p class="text-[10px] mt-0.5" style="color:var(--text-muted);">Enabled tools become available in the agent's execution pipeline. The orchestrator selects tools dynamically based on query intent.</p>
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
            { id: 'dynamics365', icon: 'cloud', name: 'Dynamics 365', desc: 'ERP/CRM data, vendor records, purchase orders', status: 'available', ver: 'v9.2' },
            { id: 'teams', icon: 'chat', name: 'Microsoft Teams', desc: 'Notifications, agent conversations via Teams', status: 'available', ver: 'Graph API v1.0' },
            { id: 'sharepoint', icon: 'folder_shared', name: 'SharePoint', desc: 'Document libraries, policy repositories', status: 'available', ver: 'REST API v2' },
            { id: 'outlook', icon: 'mail', name: 'Outlook / Exchange', desc: 'Email integration, calendar events, task sync', status: 'available', ver: 'EWS / Graph' },
        ]},
        { cat: 'Communication Channels', items: [
            { id: 'telegram', icon: 'send', name: 'Telegram Bot', desc: 'Chat interaction via Telegram bot API', status: 'available', ver: 'Bot API 7.x' },
            { id: 'whatsapp', icon: 'forum', name: 'WhatsApp Business', desc: 'Agent access via WhatsApp Business API', status: 'coming', ver: 'Cloud API v18' },
            { id: 'smtp', icon: 'email', name: 'SMTP / Email', desc: 'Inbound/outbound email agent triggers', status: 'available', ver: 'SMTP / IMAP' },
            { id: 'rest_api', icon: 'api', name: 'REST API', desc: 'Custom integrations via documented REST endpoints', status: 'active', ver: 'OpenAPI 3.1' },
            { id: 'mqtt', icon: 'hub', name: 'MQTT', desc: 'IoT and real-time event-driven messaging', status: 'available', ver: 'MQTT v5.0' },
        ]},
        { cat: 'Data & Storage', items: [
            { id: 'postgresql', icon: 'storage', name: 'PostgreSQL', desc: 'Structured data queries and analytics', status: 'active', ver: 'v16' },
            { id: 's3', icon: 'cloud_queue', name: 'AWS S3', desc: 'Cloud document storage and retrieval', status: 'available', ver: 'SDK v3' },
            { id: 'elasticsearch', icon: 'dns', name: 'Elasticsearch', desc: 'Full-text search and log analytics', status: 'coming', ver: 'v8.x' },
        ]},
    ];

    const statusMap = {
        active: { label: 'Connected', icon: 'check_circle', color: 'var(--success)', bg: 'rgba(16,185,129,0.1)', border: 'rgba(16,185,129,0.25)' },
        available: { label: 'Available', icon: 'radio_button_unchecked', color: 'var(--accent)', bg: 'var(--accent-subtle)', border: 'var(--border-active)' },
        coming: { label: 'Coming soon', icon: 'schedule', color: 'var(--warning)', bg: 'rgba(245,158,11,0.1)', border: 'rgba(245,158,11,0.25)' },
    };

    const totalConnectors = connectors.reduce((sum, cat) => sum + cat.items.length, 0);
    const activeCount = connectors.reduce((sum, cat) => sum + cat.items.filter(c => c.status === 'active').length, 0);
    const availableCount = connectors.reduce((sum, cat) => sum + cat.items.filter(c => c.status === 'available').length, 0);

    let html = '<div class="max-w-5xl mx-auto space-y-5">';
    html += `<div class="flex items-center justify-between">
        <div>
            <h2 class="text-[14px] font-semibold" style="color:var(--text-primary);">Integrations & Connectors</h2>
            <p class="text-[11px]" style="color:var(--text-muted);">Connect agents to enterprise systems, data sources, and communication channels.</p>
        </div>
        <div class="flex items-center gap-3">
            <div class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full" style="background:var(--success);"></span><span class="text-[10px] font-medium" style="color:var(--text-secondary);">${activeCount} active</span></div>
            <div class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full" style="background:var(--accent);"></span><span class="text-[10px] font-medium" style="color:var(--text-secondary);">${availableCount} available</span></div>
            <span class="text-[10px] font-mono" style="color:var(--text-muted);">${totalConnectors} total</span>
        </div>
    </div>`;

    connectors.forEach(cat => {
        html += `<div><h3 class="text-[10px] font-semibold uppercase tracking-wider mb-2 flex items-center gap-2" style="color:var(--text-muted);">${cat.cat}<span class="text-[8px] font-mono px-1.5 py-0.5" style="background:var(--bg-elevated);border-radius:var(--radius-xs);">${cat.items.length}</span></h3><div class="grid grid-cols-3 gap-2">`;
        cat.items.forEach(c => {
            const st = statusMap[c.status];
            html += `
            <div class="t-card p-3 cursor-pointer group" style="border-radius:var(--radius);transition:border-color .15s;" onclick="openConnectorConfig('${c.id}')" onmouseenter="this.style.borderColor='var(--border-active)'" onmouseleave="this.style.borderColor=''">
                <div class="flex items-start justify-between mb-2">
                    <div class="w-8 h-8 flex items-center justify-center" style="background:var(--accent-subtle);border-radius:var(--radius-sm);">
                        <span class="material-icons-outlined text-lg" style="color:var(--accent);">${c.icon}</span>
                    </div>
                    <span class="flex items-center gap-1 px-1.5 py-0.5 text-[8px] font-medium" style="background:${st.bg};color:${st.color};border:1px solid ${st.border};border-radius:var(--radius-xs);"><span class="material-icons-outlined text-[8px]">${st.icon}</span>${st.label}</span>
                </div>
                <h4 class="text-[12px] font-semibold mb-0.5" style="color:var(--text-primary);">${c.name}</h4>
                <p class="text-[10px] leading-relaxed mb-1" style="color:var(--text-muted);">${c.desc}</p>
                <div class="flex items-center justify-between mt-2 pt-2" style="border-top:1px solid var(--border-default);">
                    <span class="text-[8px] font-mono" style="color:var(--text-muted);">${c.ver || ''}</span>
                    <span class="text-[9px] font-medium flex items-center gap-1" style="color:var(--accent);"><span class="material-icons-outlined text-[10px]">arrow_forward</span>Configure</span>
                </div>
            </div>`;
        });
        html += '</div></div>';
    });

    html += '</div>';
    return html;
}

export function page_orchestration() {
    const paletteSections = [
        { cat: 'Pipeline', items: [
            { type: 'query_rewrite', icon: 'edit_note', name: 'Query Rewrite', meta: 'gpt-4o-mini' },
            { type: 'embedding', icon: 'hub', name: 'Embedding', meta: 'text-embed-3-sm' },
            { type: 'retrieval', icon: 'search', name: 'Retrieval', meta: 'FAISS hybrid' },
            { type: 'context_filter', icon: 'filter_alt', name: 'Context Filter', meta: 'threshold' },
            { type: 'validation', icon: 'verified', name: 'Validation', meta: 'rules' },
            { type: 'synthesis', icon: 'auto_awesome', name: 'Synthesis', meta: 'gpt-4o' },
            { type: 'evaluation', icon: 'analytics', name: 'Evaluation', meta: 'HHEM' },
        ]},
        { cat: 'Connectors', items: [
            { type: 'conn_sharepoint', icon: 'folder_shared', name: 'SharePoint', meta: 'docs' },
            { type: 'conn_s3', icon: 'cloud_queue', name: 'AWS S3', meta: 'storage' },
            { type: 'conn_postgres', icon: 'storage', name: 'PostgreSQL', meta: 'sql' },
            { type: 'conn_rest', icon: 'api', name: 'REST API', meta: 'http' },
            { type: 'conn_teams', icon: 'chat', name: 'MS Teams', meta: 'notify' },
            { type: 'conn_mqtt', icon: 'hub', name: 'MQTT', meta: 'iot' },
        ]},
        { cat: 'Models', items: [
            { type: 'llm_gpt4o', icon: 'psychology', name: 'GPT-4o', meta: 'openai' },
            { type: 'llm_gpt4omini', icon: 'psychology', name: 'GPT-4o-mini', meta: 'openai' },
            { type: 'llm_embed', icon: 'data_array', name: 'Embedder', meta: 'ada-3' },
            { type: 'llm_custom', icon: 'tune', name: 'Custom LLM', meta: 'self-hosted' },
        ]},
        { cat: 'I/O', items: [
            { type: 'io_input', icon: 'input', name: 'User Input', meta: 'query' },
            { type: 'io_output', icon: 'output', name: 'Agent Output', meta: 'response' },
            { type: 'io_webhook', icon: 'webhook', name: 'Webhook', meta: 'trigger' },
        ]},
        { cat: 'Intelligence', items: [
            { type: 'rss_ingest', icon: 'rss_feed', name: 'RSS Ingestion', meta: 'feeds' },
            { type: 'semantic_filter', icon: 'filter_center_focus', name: 'Semantic Filter', meta: 'target' },
            { type: 'safety_check', icon: 'shield', name: 'Safety Check', meta: 'rules' },
            { type: 'bi_aggregator', icon: 'insights', name: 'BI Aggregator', meta: 'dashboard' },
        ]},
        { cat: 'Infrastructure', items: [
            { type: 'infra_fastapi', icon: 'dns', name: 'FastAPI', meta: 'gateway' },
            { type: 'infra_celery', icon: 'schedule', name: 'Celery', meta: 'workers' },
            { type: 'infra_minio', icon: 'inventory_2', name: 'MinIO', meta: 'objects' },
            { type: 'infra_pg', icon: 'storage', name: 'PostgreSQL', meta: 'metadata' },
            { type: 'infra_qdrant', icon: 'scatter_plot', name: 'Qdrant', meta: 'vectors' },
        ]},
    ];

    let paletteHtml = `<div class="wf-palette-search"><div style="position:relative;"><span class="material-icons-outlined" style="position:absolute;left:6px;top:50%;transform:translateY(-50%);font-size:13px;color:var(--text-muted);">search</span><input type="text" placeholder="Search nodes..." oninput="wfFilterPalette(this.value)"></div></div>`;
    paletteSections.forEach(s => {
        paletteHtml += `<div class="wf-palette-cat" data-wf-cat="${s.cat}">${s.cat}<span class="wf-cat-count">${s.items.length}</span></div>`;
        s.items.forEach(it => {
            paletteHtml += `<div class="wf-palette-item" draggable="true" data-node-type="${it.type}" data-node-name="${it.name}" data-node-icon="${it.icon}" data-node-meta="${it.meta}" data-wf-cat="${s.cat}"><span class="material-icons-outlined">${it.icon}</span><span>${it.name}</span><span class="wf-item-meta">${it.meta}</span></div>`;
        });
    });

    return `
    <div style="display:flex;flex-direction:column;height:calc(100vh - 100px);margin:-20px;overflow:hidden;">
        <!-- Toolbar -->
        <div class="flex items-center justify-between px-3 py-1.5 shrink-0" style="background:var(--bg-card);border-bottom:1px solid var(--border-default);">
            <div class="flex items-center gap-2">
                <span class="material-icons-outlined text-sm" style="color:var(--accent);">account_tree</span>
                <div id="wf-breadcrumb" class="flex items-center gap-1 text-[11px]">
                    <span class="font-semibold" style="color:var(--text-primary);">Workflow</span>
                </div>
            </div>
            <div class="flex items-center gap-1.5">
                <span id="wf-node-count" class="text-[9px] font-mono px-2 py-1" style="color:var(--text-muted);">0 nodes</span>
                <div class="flex items-center" style="border:1px solid var(--border-default);border-radius:var(--radius-sm);overflow:hidden;">
                    <button onclick="wfZoom('out')" class="px-1.5 py-1 text-[10px]" style="background:var(--bg-elevated);color:var(--text-secondary);border-right:1px solid var(--border-default);" title="Zoom out">
                        <span class="material-icons-outlined text-[11px]">remove</span>
                    </button>
                    <span id="wf-zoom-level" class="px-1.5 py-1 text-[9px] font-mono" style="background:var(--bg-elevated);color:var(--text-muted);min-width:36px;text-align:center;">100%</span>
                    <button onclick="wfZoom('in')" class="px-1.5 py-1 text-[10px]" style="background:var(--bg-elevated);color:var(--text-secondary);border-left:1px solid var(--border-default);" title="Zoom in">
                        <span class="material-icons-outlined text-[11px]">add</span>
                    </button>
                    <button onclick="wfZoom('fit')" class="px-1.5 py-1 text-[10px]" style="background:var(--bg-elevated);color:var(--text-secondary);border-left:1px solid var(--border-default);" title="Fit to view">
                        <span class="material-icons-outlined text-[11px]">fit_screen</span>
                    </button>
                </div>
                <div style="width:1px;height:16px;background:var(--border-default);"></div>
                <button onclick="wfResetDefault()" class="px-2 py-1 text-[9px] font-medium flex items-center gap-1" style="background:var(--bg-elevated);border:1px solid var(--border-default);color:var(--text-secondary);border-radius:var(--radius-sm);">
                    <span class="material-icons-outlined text-[10px]">restart_alt</span>Reset
                </button>
                <button onclick="wfSave()" class="px-2 py-1 text-[9px] font-medium flex items-center gap-1" style="background:var(--accent-subtle);border:1px solid var(--border-active);color:var(--accent);border-radius:var(--radius-sm);">
                    <span class="material-icons-outlined text-[10px]">save</span>Save
                </button>
                <button onclick="wfExport()" class="px-2 py-1 text-[9px] font-medium flex items-center gap-1" style="background:var(--bg-elevated);border:1px solid var(--border-default);color:var(--text-secondary);border-radius:var(--radius-sm);">
                    <span class="material-icons-outlined text-[10px]">download</span>JSON
                </button>
            </div>
        </div>

        <!-- Main area -->
        <div style="display:flex;flex:1;min-height:0;">
            <!-- Palette -->
            <div class="wf-palette shrink-0 py-1">${paletteHtml}</div>

            <!-- Canvas -->
            <div style="flex:1;position:relative;overflow:hidden;">
                <div id="drawflow-canvas"></div>
            </div>

            <!-- Config Panel (hidden by default) -->
            <div id="wf-config-panel" class="wf-config shrink-0" style="display:none;">
                <div class="px-3 py-2.5" style="border-bottom:1px solid var(--border-default);background:var(--bg-elevated);">
                    <div class="flex items-center justify-between mb-0.5">
                        <div class="flex items-center gap-1.5">
                            <span class="material-icons-outlined text-xs" style="color:var(--accent);">settings</span>
                            <h4 class="text-[11px] font-semibold" style="color:var(--text-primary);" id="wf-cfg-title">Node Config</h4>
                        </div>
                        <button onclick="wfCloseConfig()" class="w-5 h-5 flex items-center justify-center hover:bg-opacity-10" style="color:var(--text-muted);border-radius:var(--radius-xs);">
                            <span class="material-icons-outlined text-xs">close</span>
                        </button>
                    </div>
                    <p class="text-[9px] font-mono" style="color:var(--text-muted);" id="wf-cfg-type">—</p>
                </div>
                <div id="wf-cfg-fields" class="px-3 py-2.5 space-y-1" style="max-height:calc(100vh - 240px);overflow-y:auto;"></div>
                <div class="px-3 py-2 space-y-1.5" style="border-top:1px solid var(--border-default);margin-top:auto;">
                    <button onclick="wfSave(); showToast('Node configuration applied')" class="w-full py-1.5 text-[10px] font-medium flex items-center justify-center gap-1" style="background:var(--accent-subtle);border:1px solid var(--border-active);color:var(--accent);border-radius:var(--radius-sm);">
                        <span class="material-icons-outlined text-xs">check</span>Apply Changes
                    </button>
                    <button onclick="wfDeleteNode()" class="w-full py-1.5 text-[10px] font-medium text-red-500 flex items-center justify-center gap-1" style="background:rgba(239,68,68,0.06);border:1px solid rgba(239,68,68,0.2);border-radius:var(--radius-sm);">
                        <span class="material-icons-outlined text-xs">delete</span>Remove Node
                    </button>
                </div>
            </div>
        </div>
    </div>`;
}

// =========================================================================
// WORKSPACE PAGE — Autonomous task delegation
// =========================================================================
export function page_workspace() {
    return `
    <div class="max-w-6xl mx-auto space-y-4">
        <div class="flex items-center justify-between">
            <div>
                <h2 class="text-[14px] font-semibold" style="color:var(--text-primary);">Agent Workspace</h2>
                <p class="text-[11px]" style="color:var(--text-muted);">Delegate missions to autonomous agents. Track progress in real-time.</p>
            </div>
            <button onclick="openTaskModal()" class="px-3 py-1.5 text-[11px] font-medium text-white flex items-center gap-1.5" style="background:var(--accent);border-radius:var(--radius-sm);">
                <span class="material-icons-outlined text-sm">add</span>New Mission
            </button>
        </div>

        <!-- KPIs -->
        <div class="grid grid-cols-4 gap-2">
            <div class="t-card p-3" style="border-radius:var(--radius);">
                <p class="text-[9px] font-semibold uppercase tracking-wider" style="color:var(--text-muted);">Active</p>
                <p class="text-[18px] font-bold" style="color:var(--accent);" id="ws-active-count">0</p>
            </div>
            <div class="t-card p-3" style="border-radius:var(--radius);">
                <p class="text-[9px] font-semibold uppercase tracking-wider" style="color:var(--text-muted);">Completed</p>
                <p class="text-[18px] font-bold" style="color:var(--success);" id="ws-completed-count">0</p>
            </div>
            <div class="t-card p-3" style="border-radius:var(--radius);">
                <p class="text-[9px] font-semibold uppercase tracking-wider" style="color:var(--text-muted);">Total Steps</p>
                <p class="text-[18px] font-bold" style="color:var(--text-primary);" id="ws-steps-count">0</p>
            </div>
            <div class="t-card p-3" style="border-radius:var(--radius);">
                <p class="text-[9px] font-semibold uppercase tracking-wider" style="color:var(--text-muted);">Avg. Duration</p>
                <p class="text-[18px] font-bold font-mono" style="color:var(--text-primary);" id="ws-avg-duration">—</p>
            </div>
        </div>

        <!-- Main area: task list + detail -->
        <div class="grid grid-cols-3 gap-3" style="min-height:400px;">
            <!-- Task list -->
            <div class="col-span-1 space-y-1.5" id="ws-task-list">
                <p class="text-[10px] text-center py-8" style="color:var(--text-muted);">No missions yet. Create one above.</p>
            </div>
            <!-- Task detail -->
            <div class="col-span-2 t-card p-4" style="border-radius:var(--radius);" id="ws-task-detail">
                <div class="flex flex-col items-center justify-center h-full text-center py-12">
                    <span class="material-icons-outlined text-3xl mb-2" style="color:var(--text-muted);">work</span>
                    <p class="text-[12px] font-medium" style="color:var(--text-secondary);">Select a mission to view details</p>
                    <p class="text-[10px] mt-0.5" style="color:var(--text-muted);">Or create a new mission to delegate to the agent</p>
                </div>
            </div>
        </div>
    </div>

    <!-- Task creation modal -->
    <div id="task-modal" class="hidden" style="position:fixed;inset:0;z-index:9999;">
        <div onclick="closeTaskModal()" style="position:absolute;inset:0;background:rgba(0,0,0,0.5);backdrop-filter:blur(3px);"></div>
        <div class="absolute top-1/2 left-1/2" style="transform:translate(-50%,-50%);width:480px;background:var(--bg-card);border:1px solid var(--border-default);border-radius:var(--radius);box-shadow:0 20px 60px rgba(0,0,0,0.3);">
            <div class="px-4 py-3" style="border-bottom:1px solid var(--border-default);background:var(--bg-elevated);border-radius:var(--radius) var(--radius) 0 0;">
                <div class="flex items-center gap-2">
                    <span class="material-icons-outlined text-sm" style="color:var(--accent);">rocket_launch</span>
                    <div>
                        <h3 class="text-[13px] font-semibold" style="color:var(--text-primary);">New Mission</h3>
                        <p class="text-[10px]" style="color:var(--text-muted);">The agent will plan, decompose, and execute steps autonomously</p>
                    </div>
                </div>
            </div>
            <div class="px-4 py-3 space-y-2.5">
                <div class="wf-config-field">
                    <label>Mission Title</label>
                    <input id="task-title" placeholder="e.g., Quarterly vendor compliance audit">
                </div>
                <div class="wf-config-field">
                    <label>Objective</label>
                    <textarea id="task-desc" rows="4" placeholder="Describe in detail what the agent should accomplish. Be specific about:&#10;- Expected outputs (report, analysis, data)&#10;- Scope and constraints&#10;- Success criteria" style="resize:none;"></textarea>
                </div>
                <div class="grid grid-cols-2 gap-2">
                    <div class="wf-config-field">
                        <label>Assigned Agent</label>
                        <select id="task-agent">
                            <option value="">Auto-select (best fit)</option>
                            <option value="procurement">Procurement Agent</option>
                            <option value="research">Research Agent</option>
                            <option value="general">General Assistant</option>
                        </select>
                    </div>
                    <div class="wf-config-field">
                        <label>Priority</label>
                        <select id="task-priority">
                            <option value="normal" selected>Normal</option>
                            <option value="high">High</option>
                            <option value="low">Low</option>
                        </select>
                    </div>
                </div>
                <div class="p-2" style="background:var(--bg-elevated);border-radius:var(--radius-sm);">
                    <p class="text-[9px]" style="color:var(--text-muted);">
                        <span class="material-icons-outlined text-[10px] align-middle mr-0.5" style="color:var(--accent);">info</span>
                        The agent will first create an execution plan, then proceed step by step. You can monitor progress in real-time.
                    </p>
                </div>
            </div>
            <div class="px-4 py-3 flex items-center justify-end gap-2" style="border-top:1px solid var(--border-default);">
                <button onclick="closeTaskModal()" class="px-3 py-1.5 text-[11px] font-medium" style="color:var(--text-secondary);border:1px solid var(--border-default);border-radius:var(--radius-sm);">Cancel</button>
                <button onclick="submitTask()" class="px-3 py-1.5 text-[11px] font-medium text-white flex items-center gap-1" style="background:var(--accent);border-radius:var(--radius-sm);">
                    <span class="material-icons-outlined text-xs">rocket_launch</span>Launch Mission
                </button>
            </div>
        </div>
    </div>`;
}

// =========================================================================
// AGENT QUALITY PAGE — ProofAgent-inspired evaluation
// =========================================================================
export function page_agentQuality() {
    const dimensions = [
        { key: 'task_success', label: 'Task Success', desc: 'Did the agent progress toward the goal?' },
        { key: 'relevance', label: 'Relevance', desc: 'Was the answer on-topic and context-aware?' },
        { key: 'instruction_following', label: 'Instruction Following', desc: 'Did it follow constraints?' },
        { key: 'coherence', label: 'Coherence', desc: 'Clear and internally consistent?' },
        { key: 'hallucination', label: 'Hallucination', desc: 'Were claims factual and supported?' },
        { key: 'tone', label: 'Tone', desc: 'Was it appropriate for the domain?' },
        { key: 'conciseness', label: 'Conciseness', desc: 'Clear and non-redundant?' },
        { key: 'safety', label: 'Safety', desc: 'No harmful or unsafe behavior?' },
        { key: 'policy', label: 'Policy', desc: 'Aligned with configured rules?' },
        { key: 'drift', label: 'Drift / Memory Stability', desc: 'Did it stay consistent across turns?' },
        { key: 'manipulation', label: 'Manipulation', desc: 'Resisted adversarial input?' },
        { key: 'tool_use', label: 'Tool Use', desc: 'Correct tool selection and execution?' },
    ];

    const leftDims = dimensions.slice(0, 6);
    const rightDims = dimensions.slice(6);

    return `
    <div class="max-w-6xl mx-auto space-y-4">
        <div class="flex items-center justify-between">
            <div>
                <h2 class="text-[14px] font-semibold" style="color:var(--text-primary);">Agent Quality Score</h2>
                <p class="text-[11px]" style="color:var(--text-muted);">LLM-as-Judge evaluation across 12 critical dimensions. Real-time scoring via GPT-4o.</p>
            </div>
            <div class="flex items-center gap-2">
                <button onclick="triggerManualEval()" class="px-2.5 py-1.5 text-[10px] font-medium flex items-center gap-1" style="background:var(--accent-subtle);border:1px solid var(--border-active);color:var(--accent);border-radius:var(--radius-sm);">
                    <span class="material-icons-outlined text-xs">play_arrow</span>Run Evaluation
                </button>
            </div>
        </div>

        <!-- Composite Score + Radar -->
        <div class="grid grid-cols-4 gap-3">
            <!-- Left dimensions -->
            <div class="col-span-1 space-y-1.5">
                ${leftDims.map(d => `
                <div class="t-card p-2.5" style="border-radius:var(--radius);">
                    <p class="text-[11px] font-semibold" style="color:var(--text-primary);">${d.label}</p>
                    <p class="text-[9px]" style="color:var(--text-muted);">${d.desc}</p>
                    <div class="flex items-center gap-1.5 mt-1">
                        <div class="flex-1 h-1 rounded-full" style="background:var(--border-default);">
                            <div class="h-full rounded-full" style="background:var(--accent);width:0%;" data-quality-bar="${d.key}"></div>
                        </div>
                        <span class="text-[9px] font-mono font-bold" style="color:var(--accent);" data-quality-score="${d.key}">—</span>
                    </div>
                </div>`).join('')}
            </div>

            <!-- Radar Chart -->
            <div class="col-span-2 t-card p-4 flex flex-col items-center justify-center" style="border-radius:var(--radius);">
                <div class="relative" style="width:320px;height:320px;">
                    <canvas id="quality-radar" width="320" height="320"></canvas>
                    <div class="absolute inset-0 flex items-center justify-center pointer-events-none">
                        <div class="text-center">
                            <p class="text-[28px] font-bold" style="color:var(--accent);" id="quality-composite">—</p>
                            <p class="text-[9px] font-semibold uppercase tracking-wider" style="color:var(--text-muted);">Overall</p>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Right dimensions -->
            <div class="col-span-1 space-y-1.5">
                ${rightDims.map(d => `
                <div class="t-card p-2.5" style="border-radius:var(--radius);">
                    <p class="text-[11px] font-semibold" style="color:var(--text-primary);">${d.label}</p>
                    <p class="text-[9px]" style="color:var(--text-muted);">${d.desc}</p>
                    <div class="flex items-center gap-1.5 mt-1">
                        <div class="flex-1 h-1 rounded-full" style="background:var(--border-default);">
                            <div class="h-full rounded-full" style="background:var(--accent);width:0%;" data-quality-bar="${d.key}"></div>
                        </div>
                        <span class="text-[9px] font-mono font-bold" style="color:var(--accent);" data-quality-score="${d.key}">—</span>
                    </div>
                </div>`).join('')}
            </div>
        </div>

        <!-- Hallucination & Drift tracking -->
        <div class="grid grid-cols-2 gap-3">
            <div class="t-card p-3" style="border-radius:var(--radius);">
                <div class="flex items-center gap-2 mb-2">
                    <span class="material-icons-outlined text-sm" style="color:var(--warning);">fact_check</span>
                    <h3 class="text-[12px] font-semibold" style="color:var(--text-primary);">Claim Audit</h3>
                </div>
                <div id="quality-claims" class="space-y-1">
                    <p class="text-[10px]" style="color:var(--text-muted);">Run an evaluation to see claim audit results.</p>
                </div>
            </div>
            <div class="t-card p-3" style="border-radius:var(--radius);">
                <div class="flex items-center gap-2 mb-2">
                    <span class="material-icons-outlined text-sm" style="color:var(--accent);">timeline</span>
                    <h3 class="text-[12px] font-semibold" style="color:var(--text-primary);">Evaluation History</h3>
                </div>
                <div id="quality-history" class="space-y-1">
                    <p class="text-[10px]" style="color:var(--text-muted);">No evaluations recorded yet.</p>
                </div>
            </div>
        </div>
    </div>`;
}

// =========================================================================
// INTELLIGENCE DASHBOARD PAGE
// =========================================================================
export function page_intelligence() {
    return `
    <div class="max-w-6xl mx-auto space-y-4">
        <div class="flex items-center justify-between">
            <div>
                <h2 class="text-[14px] font-semibold" style="color:var(--text-primary);">Intelligence Dashboard</h2>
                <p class="text-[11px]" style="color:var(--text-muted);">Automated RSS analysis with semantic targeting and safety filters.</p>
            </div>
            <div class="flex items-center gap-1.5">
                <button onclick="openIntelConfig()" class="px-2.5 py-1.5 text-[10px] font-medium flex items-center gap-1" style="background:var(--bg-elevated);border:1px solid var(--border-default);color:var(--text-secondary);border-radius:var(--radius-sm);">
                    <span class="material-icons-outlined text-xs">settings</span>Configure
                </button>
                <button onclick="runBatchAnalysis()" class="px-2.5 py-1.5 text-[10px] font-medium text-white flex items-center gap-1" style="background:var(--accent);border-radius:var(--radius-sm);">
                    <span class="material-icons-outlined text-xs">play_arrow</span>Run Analysis
                </button>
            </div>
        </div>

        <!-- KPIs -->
        <div class="grid grid-cols-4 gap-2">
            <div class="t-card p-3" style="border-radius:var(--radius);">
                <p class="text-[9px] font-semibold uppercase tracking-wider" style="color:var(--text-muted);">Articles</p>
                <p class="text-[18px] font-bold" style="color:var(--text-primary);" id="intel-total-articles">0</p>
            </div>
            <div class="t-card p-3" style="border-radius:var(--radius);">
                <p class="text-[9px] font-semibold uppercase tracking-wider" style="color:var(--text-muted);">Active Feeds</p>
                <p class="text-[18px] font-bold" style="color:var(--accent);" id="intel-active-feeds">0</p>
            </div>
            <div class="t-card p-3" style="border-radius:var(--radius);">
                <p class="text-[9px] font-semibold uppercase tracking-wider" style="color:var(--text-muted);">High Risk</p>
                <p class="text-[18px] font-bold" style="color:var(--warning);" id="intel-high-risk">0</p>
            </div>
            <div class="t-card p-3" style="border-radius:var(--radius);">
                <p class="text-[9px] font-semibold uppercase tracking-wider" style="color:var(--text-muted);">Analyzed</p>
                <p class="text-[18px] font-bold" style="color:var(--success);" id="intel-analyzed">0</p>
            </div>
        </div>

        <!-- Charts row -->
        <div class="grid grid-cols-2 gap-3">
            <div class="t-card p-3" style="border-radius:var(--radius);">
                <h3 class="text-[11px] font-semibold mb-2" style="color:var(--text-primary);">Sentiment Distribution</h3>
                <canvas id="intel-sentiment-chart" height="160"></canvas>
            </div>
            <div class="t-card p-3" style="border-radius:var(--radius);">
                <h3 class="text-[11px] font-semibold mb-2" style="color:var(--text-primary);">Top Entities</h3>
                <canvas id="intel-entity-chart" height="160"></canvas>
            </div>
        </div>

        <!-- Batch progress bar (hidden by default) -->
        <div id="intel-batch-bar" class="hidden t-card p-3" style="border-radius:var(--radius);">
            <div class="flex items-center gap-2 mb-1.5">
                <span class="material-icons-outlined text-sm tool-running" style="color:var(--accent);">sync</span>
                <span class="text-[11px] font-medium" style="color:var(--text-primary);" id="intel-batch-status">Analyzing...</span>
            </div>
            <div class="w-full h-1.5 rounded-full" style="background:var(--border-default);">
                <div class="h-full rounded-full transition-all" style="background:var(--accent);width:0%;" id="intel-batch-progress"></div>
            </div>
        </div>

        <!-- Article Feed -->
        <div class="t-card p-3" style="border-radius:var(--radius);">
            <h3 class="text-[11px] font-semibold mb-2" style="color:var(--text-primary);">Recent Articles</h3>
            <div id="intel-articles" class="space-y-1.5">
                <p class="text-[10px] text-center py-4" style="color:var(--text-muted);">No articles analyzed yet. Add RSS feeds and run analysis.</p>
            </div>
        </div>
    </div>

    <!-- Intel Config Modal -->
    <div id="intel-config-modal" class="hidden" style="position:fixed;inset:0;z-index:9999;">
        <div onclick="closeIntelConfig()" style="position:absolute;inset:0;background:rgba(0,0,0,0.5);backdrop-filter:blur(3px);"></div>
        <div style="position:absolute;top:0;bottom:0;right:0;width:460px;background:var(--bg-card);border-left:1px solid var(--border-default);display:flex;flex-direction:column;box-shadow:-8px 0 32px rgba(0,0,0,0.2);">
            <div class="px-4 py-3 shrink-0" style="border-bottom:1px solid var(--border-default);background:var(--bg-elevated);">
                <div class="flex items-center justify-between">
                    <div class="flex items-center gap-2">
                        <span class="material-icons-outlined text-sm" style="color:var(--accent);">rss_feed</span>
                        <div>
                            <h3 class="text-[13px] font-semibold" style="color:var(--text-primary);">Intelligence Configuration</h3>
                            <p class="text-[9px]" style="color:var(--text-muted);">Manage data sources, semantic targets, and safety filters</p>
                        </div>
                    </div>
                    <button onclick="closeIntelConfig()" class="w-6 h-6 flex items-center justify-center" style="color:var(--text-muted);"><span class="material-icons-outlined text-base">close</span></button>
                </div>
            </div>
            <div class="flex-1 overflow-y-auto px-4 py-3 space-y-4" id="intel-config-body">
                <!-- RSS Feeds -->
                <div>
                    <div class="flex items-center gap-1.5 mb-1.5">
                        <span class="material-icons-outlined text-xs" style="color:var(--accent);">dynamic_feed</span>
                        <h4 class="text-[10px] font-semibold uppercase tracking-wider" style="color:var(--text-muted);">RSS / Atom Feeds</h4>
                    </div>
                    <p class="text-[9px] mb-2" style="color:var(--text-muted);">Add news feeds to monitor. Articles are fetched and analyzed during each batch run.</p>
                    <div id="intel-feeds-list" class="space-y-1 mb-2"></div>
                    <div class="p-2" style="background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:var(--radius-sm);">
                        <div class="wf-config-field"><label>Feed Name</label><input id="intel-feed-name" placeholder="e.g., Reuters World News"></div>
                        <div class="wf-config-field"><label>Feed URL</label><input id="intel-feed-url" placeholder="https://feeds.reuters.com/reuters/topNews" type="url"></div>
                        <button onclick="addFeed()" class="w-full py-1 text-[9px] font-medium text-white flex items-center justify-center gap-1 mt-1" style="background:var(--accent);border-radius:var(--radius-sm);">
                            <span class="material-icons-outlined text-[10px]">add</span>Add Feed
                        </button>
                    </div>
                </div>
                <!-- Semantic Targets -->
                <div>
                    <div class="flex items-center gap-1.5 mb-1.5">
                        <span class="material-icons-outlined text-xs" style="color:var(--accent);">filter_center_focus</span>
                        <h4 class="text-[10px] font-semibold uppercase tracking-wider" style="color:var(--text-muted);">Semantic Targets</h4>
                    </div>
                    <p class="text-[9px] mb-2" style="color:var(--text-muted);">Define topics of interest. Articles are scored for relevance against these targets using embeddings.</p>
                    <div id="intel-targets-list" class="space-y-1 mb-2"></div>
                    <div class="p-2" style="background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:var(--radius-sm);">
                        <div class="wf-config-field"><label>Target Name</label><input id="intel-target-name" placeholder="e.g., Energy Supply Chain Disruptions"></div>
                        <div class="wf-config-field"><label>Semantic Scope</label><textarea id="intel-target-desc" placeholder="Hormuz Strait tensions, oil pipeline sanctions, OPEC+ production cuts, LNG supply disruptions, Red Sea shipping route threats" rows="2" style="resize:none;"></textarea></div>
                        <button onclick="addTarget()" class="w-full py-1 text-[9px] font-medium text-white flex items-center justify-center gap-1 mt-1" style="background:var(--accent);border-radius:var(--radius-sm);">
                            <span class="material-icons-outlined text-[10px]">add</span>Add Target
                        </button>
                    </div>
                </div>
                <!-- Safety Filters -->
                <div>
                    <div class="flex items-center gap-1.5 mb-1.5">
                        <span class="material-icons-outlined text-xs" style="color:var(--warning);">shield</span>
                        <h4 class="text-[10px] font-semibold uppercase tracking-wider" style="color:var(--text-muted);">Safety Filters</h4>
                    </div>
                    <p class="text-[9px] mb-2" style="color:var(--text-muted);">Define governance rules to filter or flag sensitive content during analysis.</p>
                    <div id="intel-filters-list" class="space-y-1 mb-2"></div>
                    <div class="p-2" style="background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:var(--radius-sm);">
                        <div class="wf-config-field"><label>Filter Name</label><input id="intel-filter-name" placeholder="e.g., Geopolitical Alignment (UAE)"></div>
                        <div class="wf-config-field"><label>Filter Prompt</label><textarea id="intel-filter-prompt" placeholder="Ensure analysis is aligned with UAE geopolitical positioning. Flag content that takes sides in regional conflicts. Avoid amplifying sanctioned entity narratives." rows="3" style="resize:none;"></textarea></div>
                        <div class="wf-config-field"><label>Severity</label><select><option selected>Flag for review</option><option>Warn only</option><option>Block content</option></select></div>
                        <button onclick="addSafetyFilter()" class="w-full py-1 text-[9px] font-medium text-white flex items-center justify-center gap-1 mt-1" style="background:var(--accent);border-radius:var(--radius-sm);">
                            <span class="material-icons-outlined text-[10px]">add</span>Add Filter
                        </button>
                    </div>
                </div>
            </div>
        </div>
    </div>`;
}
