/**
 * Step content templates for the agent builder wizard.
 * Each function returns an HTML string for the step.
 */

export function step1_agentCreation() {
    return `
    <div class="max-w-3xl mx-auto space-y-3">
        <div class="bg-white rounded-lg border border-slate-200 p-4">
            <div class="flex items-center gap-2.5 mb-3">
                <div class="w-7 h-7 rounded-md bg-brand-100 flex items-center justify-center">
                    <span class="material-icons-outlined text-brand-600 text-lg">smart_toy</span>
                </div>
                <div>
                    <h3 class="text-sm font-semibold text-slate-900">Define Your Agent</h3>
                    <p class="text-[11px] text-slate-500">Configure the agent's identity and capabilities</p>
                </div>
            </div>
            <div class="space-y-2.5">
                <div class="grid grid-cols-5 gap-2.5">
                    <div class="col-span-3">
                        <label class="text-[11px] font-medium text-slate-500 mb-1 block">Agent Name</label>
                        <input id="agent-name" type="text" value="Vendor Compliance Agent" class="w-full px-3 py-1.5 border border-slate-200 rounded-md text-sm focus:ring-1 focus:ring-brand-500 focus:border-brand-500">
                    </div>
                    <div class="col-span-2">
                        <label class="text-[11px] font-medium text-slate-500 mb-1 block">Type</label>
                        <select id="agent-type" class="w-full px-3 py-1.5 border border-slate-200 rounded-md text-sm bg-white focus:ring-1 focus:ring-brand-500">
                            <option selected>Procurement</option>
                            <option>Customer Support</option>
                            <option>Data Analysis</option>
                            <option>Custom</option>
                        </select>
                    </div>
                </div>
                <div>
                    <label class="text-[11px] font-medium text-slate-500 mb-1 block">System Prompt</label>
                    <textarea class="code-editor w-full px-3 py-2 border border-slate-200 rounded-md text-[12px] h-20 focus:ring-1 focus:ring-brand-500">You are a Vendor Compliance Validation Agent operating within an enterprise procurement platform.

Your role is to validate vendor document submissions against compliance checklists.
You check for: trade licenses, insurance certificates, financial statements, regulatory certifications, and NDAs.

Be precise, professional, and always reference the compliance policy when available.</textarea>
                </div>
            </div>
        </div>

        <div class="bg-white rounded-lg border border-slate-200 p-4">
            <h3 class="text-[13px] font-semibold text-slate-900 mb-2.5 flex items-center gap-1.5">
                <span class="material-icons-outlined text-slate-400 text-base">tune</span>
                Capabilities
            </h3>
            <div class="flex flex-wrap gap-1.5">
                <label class="cap-label flex items-center gap-1.5 px-2.5 py-1.5 bg-brand-50 border border-brand-200 rounded-md cursor-pointer transition-colors" onclick="toggleCap(this)">
                    <input type="checkbox" checked class="w-3.5 h-3.5 text-brand-600 rounded">
                    <span class="text-[12px] font-medium text-slate-700">RAG Retrieval</span>
                </label>
                <label class="cap-label flex items-center gap-1.5 px-2.5 py-1.5 bg-brand-50 border border-brand-200 rounded-md cursor-pointer transition-colors" onclick="toggleCap(this)">
                    <input type="checkbox" checked class="w-3.5 h-3.5 text-brand-600 rounded">
                    <span class="text-[12px] font-medium text-slate-700">Document Parsing</span>
                </label>
                <label class="cap-label flex items-center gap-1.5 px-2.5 py-1.5 bg-slate-50 border border-slate-200 rounded-md cursor-pointer transition-colors" onclick="toggleCap(this)">
                    <input type="checkbox" class="w-3.5 h-3.5 text-brand-600 rounded">
                    <span class="text-[12px] font-medium text-slate-700">External API</span>
                </label>
                <label class="cap-label flex items-center gap-1.5 px-2.5 py-1.5 bg-slate-50 border border-slate-200 rounded-md cursor-pointer transition-colors" onclick="toggleCap(this)">
                    <input type="checkbox" class="w-3.5 h-3.5 text-brand-600 rounded">
                    <span class="text-[12px] font-medium text-slate-700">Structured Output</span>
                </label>
            </div>
        </div>

        <div class="bg-slate-50 rounded-lg border border-slate-200 p-3">
            <div class="flex items-start gap-2.5">
                <span class="material-icons-outlined text-brand-500 text-base mt-0.5">info</span>
                <div class="text-[12px] text-slate-600">
                    <p class="font-medium text-slate-800 mb-0.5">What you see as a single agent is actually an orchestrated execution of multiple steps under the hood.</p>
                    <p class="text-[11px] text-slate-500">The platform is both the <strong>Agent interface</strong> (facade) and the <strong>Orchestrator</strong> (engine). At Step 6, you'll see the full pipeline unfold.</p>
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
                    <p class="text-[10px] text-slate-500 mt-0.5">GPT-4o, GPT-4o-mini</p>
                </div>
                <div class="provider-card p-2.5 border border-slate-200 rounded-md cursor-pointer hover:border-slate-300 transition-all relative" data-provider="anthropic" onclick="selectProvider(this)">
                    <span class="provider-check hidden absolute top-1.5 right-1.5 w-3.5 h-3.5 rounded-full bg-brand-500 flex items-center justify-center">
                        <span class="material-icons-outlined text-white text-[9px]">check</span>
                    </span>
                    <p class="text-[13px] font-semibold text-slate-900">Anthropic</p>
                    <p class="text-[10px] text-slate-500 mt-0.5">Claude 3.5 Sonnet</p>
                </div>
                <div class="provider-card p-2.5 border border-slate-200 rounded-md cursor-pointer hover:border-slate-300 transition-all relative" data-provider="selfhosted" onclick="selectProvider(this)">
                    <span class="provider-check hidden absolute top-1.5 right-1.5 w-3.5 h-3.5 rounded-full bg-brand-500 flex items-center justify-center">
                        <span class="material-icons-outlined text-white text-[9px]">check</span>
                    </span>
                    <p class="text-[13px] font-semibold text-slate-900">Self-hosted</p>
                    <p class="text-[10px] text-slate-500 mt-0.5">Ollama, vLLM</p>
                </div>
            </div>

            <div class="grid grid-cols-2 gap-3">
                <div>
                    <label class="text-[11px] font-medium text-slate-500 mb-1 block">Model</label>
                    <select id="model-select" class="w-full px-3 py-1.5 border border-slate-200 rounded-md text-sm bg-white focus:ring-1 focus:ring-brand-500">
                        <option value="gpt-4o" selected>GPT-4o</option>
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

            <div class="mt-3 pt-3 border-t border-slate-100">
                <h4 class="text-[12px] font-semibold text-slate-600 mb-2">Pre-loaded Knowledge Base</h4>
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
    return `
    <div class="max-w-3xl mx-auto space-y-3">
        <div class="bg-white rounded-lg border border-slate-200 p-4">
            <div class="flex items-center justify-between mb-3">
                <div class="flex items-center gap-2.5">
                    <div class="w-7 h-7 rounded-md bg-amber-100 flex items-center justify-center">
                        <span class="material-icons-outlined text-amber-600 text-lg">rule</span>
                    </div>
                    <div>
                        <h3 class="text-sm font-semibold text-slate-900">Validation Rules</h3>
                        <p class="text-[11px] text-slate-500">Extracted from your knowledge base</p>
                    </div>
                </div>
                <button id="edit-rules-btn" onclick="toggleEditRules()" class="px-2.5 py-1 text-[11px] font-medium text-amber-700 bg-amber-50 hover:bg-amber-100 rounded-md transition-colors flex items-center gap-1">
                    <span class="material-icons-outlined text-sm">edit</span>
                    Edit rules
                </button>
            </div>

            <div class="bg-emerald-50 border border-emerald-200 rounded-md px-3 py-2 mb-3 flex items-center gap-2">
                <span class="material-icons-outlined text-emerald-600 text-base">auto_awesome</span>
                <p class="text-[11px] text-emerald-800"><span class="font-semibold">5 rules auto-extracted</span> from 3 knowledge base documents &middot; Severity levels assigned by document analysis</p>
            </div>

            <div class="space-y-1.5" id="rules-list">
                <div class="rule-row flex items-center justify-between p-2.5 border border-slate-200 rounded-md cursor-pointer hover:bg-slate-50 transition-colors" data-doc-id="77cb9af2-6006-51ed-bd01-adc548a7e2be" data-doc-title="vendor_qualification_policy.md" onclick="openRuleSource(this)">
                    <div class="flex items-center gap-2.5">
                        <span class="w-1 h-6 rounded-sm bg-red-500"></span>
                        <div>
                            <p class="text-[13px] font-medium text-slate-800 rule-name">Trade License</p>
                            <p class="text-[10px] text-slate-500 rule-desc">Must be valid, renewed within 12 months</p>
                        </div>
                    </div>
                    <div class="flex items-center gap-2">
                        <span class="rule-actions hidden"></span>
                        <span class="text-[9px] text-slate-400 italic rule-source">vendor_qualification_policy.md</span>
                        <span class="px-1.5 py-0.5 text-[9px] font-bold bg-red-100 text-red-700 rounded rule-severity">CRITICAL</span>
                    </div>
                </div>
                <div class="rule-row flex items-center justify-between p-2.5 border border-slate-200 rounded-md cursor-pointer hover:bg-slate-50 transition-colors" data-doc-id="77cb9af2-6006-51ed-bd01-adc548a7e2be" data-doc-title="vendor_qualification_policy.md" onclick="openRuleSource(this)">
                    <div class="flex items-center gap-2.5">
                        <span class="w-1 h-6 rounded-sm bg-red-500"></span>
                        <div>
                            <p class="text-[13px] font-medium text-slate-800 rule-name">Insurance Certificate</p>
                            <p class="text-[10px] text-slate-500 rule-desc">Liability &amp; professional indemnity, min $2M coverage</p>
                        </div>
                    </div>
                    <div class="flex items-center gap-2">
                        <span class="rule-actions hidden"></span>
                        <span class="text-[9px] text-slate-400 italic rule-source">vendor_qualification_policy.md</span>
                        <span class="px-1.5 py-0.5 text-[9px] font-bold bg-red-100 text-red-700 rounded rule-severity">CRITICAL</span>
                    </div>
                </div>
                <div class="rule-row flex items-center justify-between p-2.5 border border-slate-200 rounded-md cursor-pointer hover:bg-slate-50 transition-colors" data-doc-id="77cb9af2-6006-51ed-bd01-adc548a7e2be" data-doc-title="vendor_qualification_policy.md" onclick="openRuleSource(this)">
                    <div class="flex items-center gap-2.5">
                        <span class="w-1 h-6 rounded-sm bg-amber-500"></span>
                        <div>
                            <p class="text-[13px] font-medium text-slate-800 rule-name">Financial Statements</p>
                            <p class="text-[10px] text-slate-500 rule-desc">Audited, last 2 fiscal years</p>
                        </div>
                    </div>
                    <div class="flex items-center gap-2">
                        <span class="rule-actions hidden"></span>
                        <span class="text-[9px] text-slate-400 italic rule-source">vendor_qualification_policy.md</span>
                        <span class="px-1.5 py-0.5 text-[9px] font-bold bg-amber-100 text-amber-700 rounded rule-severity">MAJOR</span>
                    </div>
                </div>
                <div class="rule-row flex items-center justify-between p-2.5 border border-slate-200 rounded-md cursor-pointer hover:bg-slate-50 transition-colors" data-doc-id="0076badc-01f0-59a6-be24-efad5dc6f336" data-doc-title="iso9001_compliance_checklist.md" onclick="openRuleSource(this)">
                    <div class="flex items-center gap-2.5">
                        <span class="w-1 h-6 rounded-sm bg-amber-500"></span>
                        <div>
                            <p class="text-[13px] font-medium text-slate-800 rule-name">Regulatory Certifications</p>
                            <p class="text-[10px] text-slate-500 rule-desc">ISO 9001, ISO 27001, industry-specific</p>
                        </div>
                    </div>
                    <div class="flex items-center gap-2">
                        <span class="rule-actions hidden"></span>
                        <span class="text-[9px] text-slate-400 italic rule-source">iso9001_compliance_checklist.md</span>
                        <span class="px-1.5 py-0.5 text-[9px] font-bold bg-amber-100 text-amber-700 rounded rule-severity">MAJOR</span>
                    </div>
                </div>
                <div class="rule-row flex items-center justify-between p-2.5 border border-slate-200 rounded-md cursor-pointer hover:bg-slate-50 transition-colors" data-doc-id="c32d0cbe-9946-5cc1-a0d0-87553b0cca00" data-doc-title="nda_template.md" onclick="openRuleSource(this)">
                    <div class="flex items-center gap-2.5">
                        <span class="w-1 h-6 rounded-sm bg-blue-500"></span>
                        <div>
                            <p class="text-[13px] font-medium text-slate-800 rule-name">Non-Disclosure Agreement</p>
                            <p class="text-[10px] text-slate-500 rule-desc">Signed NDA using company template</p>
                        </div>
                    </div>
                    <div class="flex items-center gap-2">
                        <span class="rule-actions hidden"></span>
                        <span class="text-[9px] text-slate-400 italic rule-source">nda_template.md</span>
                        <span class="px-1.5 py-0.5 text-[9px] font-bold bg-blue-100 text-blue-700 rounded rule-severity">MINOR</span>
                    </div>
                </div>
            </div>
        </div>

        <div class="bg-white rounded-lg border border-slate-200 p-4">
            <h3 class="text-[13px] font-semibold text-slate-900 mb-2.5">Tools Available</h3>
            <div class="grid grid-cols-2 gap-2">
                <div class="p-2.5 bg-slate-50 rounded-md flex items-start gap-2.5 border border-slate-100">
                    <span class="material-icons-outlined text-brand-500 text-lg mt-0.5">search</span>
                    <div>
                        <p class="text-[13px] font-medium text-slate-800">Knowledge Search</p>
                        <p class="text-[11px] text-slate-500">Hybrid BM25 + vector retrieval</p>
                    </div>
                </div>
                <div class="p-2.5 bg-slate-50 rounded-md flex items-start gap-2.5 border border-slate-100">
                    <span class="material-icons-outlined text-brand-500 text-lg mt-0.5">checklist</span>
                    <div>
                        <p class="text-[13px] font-medium text-slate-800">Rule Engine</p>
                        <p class="text-[11px] text-slate-500">Auto-extracted rule validation</p>
                    </div>
                </div>
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
                    <p class="text-lg font-bold text-purple-700">1536</p>
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
                    <div><span class="text-slate-500">Realm:</span> <span class="font-medium text-slate-800">presight-ai</span></div>
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
                    <span class="px-1.5 py-0.5 text-[9px] font-medium bg-emerald-100 text-emerald-700 rounded">3 users</span>
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
                    <span class="text-[10px] text-slate-400">4 members</span>
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
    const agentName = (typeof savedAgentName !== 'undefined' && savedAgentName) ? savedAgentName : 'Vendor Compliance Agent';
    const agentType = (typeof savedAgentType !== 'undefined' && savedAgentType) ? savedAgentType : 'Procurement';

    const descMap = {
        'Procurement': 'Describe a submission to validate against your configured rules…',
        'Customer Support': 'Describe a customer request to process…',
        'Data Analysis': 'Describe a dataset or question to analyze…',
    };
    const welcomeMap = {
        'Procurement': 'Submit a dossier and the agent will validate it against the compliance rules and knowledge base you configured. Each orchestration step is shown in real time.',
        'Customer Support': 'Describe a customer issue and the agent will process it using the knowledge base and tools configured above.',
        'Data Analysis': 'Ask a question or describe a dataset. The agent will analyze it using the configured pipeline.',
    };
    const placeholder = descMap[agentType] || 'Send a message to test your agent…';
    const welcome = welcomeMap[agentType] || 'Test your agent with a real query. Each orchestration step will be shown in real time.';

    return `
    <div class="max-w-3xl mx-auto flex flex-col" style="height:calc(100vh - 230px);">
        <div class="bg-white rounded-lg border border-slate-200 flex flex-col flex-1 min-h-0">
            <!-- Header -->
            <div class="px-4 py-2.5 border-b border-slate-200 flex items-center gap-2 shrink-0 bg-slate-50">
                <div class="w-1 h-4 rounded-sm bg-brand-500"></div>
                <h3 class="text-[13px] font-semibold text-slate-900">${agentName}</h3>
                <span id="chat-status" class="text-[11px] text-slate-400 ml-auto"></span>
            </div>

            <!-- Messages -->
            <div id="chat-messages" class="flex-1 overflow-y-auto px-4 py-5 space-y-4">
                <div id="chat-welcome" class="flex flex-col items-center justify-center h-full">
                    <div class="w-full max-w-lg">
                        <div class="mb-5">
                            <div class="flex items-center gap-2 mb-1.5">
                                <span class="block w-1 h-5 rounded-sm bg-brand-500"></span>
                                <h2 class="font-semibold text-[15px] text-slate-900">${agentName}</h2>
                            </div>
                            <p class="text-[13px] text-slate-500 ml-3">${welcome}</p>
                        </div>
                        <div class="space-y-1.5" id="suggestion-cards">
                            <button onclick="sendSuggestion(this)" class="suggestion-card w-full text-left text-[12px] text-slate-500 bg-white border border-slate-200 hover:border-brand-400 hover:text-slate-700 rounded-md px-3 py-2 transition-colors">
                                <span class="font-medium text-slate-700">TechCorp Solutions</span> — Trade license OK, insurance OK, missing financial statements 2024-2025, ISO 27001 valid, NDA not submitted
                            </button>
                            <button onclick="sendSuggestion(this)" class="suggestion-card w-full text-left text-[12px] text-slate-500 bg-white border border-slate-200 hover:border-brand-400 hover:text-slate-700 rounded-md px-3 py-2 transition-colors">
                                <span class="font-medium text-slate-700">GreenBuild Materials</span> — All documents submitted: trade license, insurance, financials 2024-2025, ISO 14001, NDA signed
                            </button>
                            <button onclick="sendSuggestion(this)" class="suggestion-card w-full text-left text-[12px] text-slate-500 bg-white border border-slate-200 hover:border-brand-400 hover:text-slate-700 rounded-md px-3 py-2 transition-colors">
                                What documents are required for vendor qualification under our procurement policy?
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Input bar -->
            <div class="border-t border-slate-200 px-4 py-3 shrink-0">
                <div class="flex items-end gap-2.5 bg-slate-50 border border-slate-200 rounded-md px-3 py-2 focus-within:border-brand-400 transition-colors">
                    <textarea id="chat-input" rows="1" placeholder="${placeholder}"
                        class="flex-1 resize-none bg-transparent text-[13px] text-slate-800 placeholder-slate-400 focus:outline-none disabled:opacity-50 leading-relaxed"
                        style="max-height:100px;"></textarea>
                    <button id="chat-send" onclick="sendChat()"
                        class="shrink-0 w-7 h-7 rounded-md bg-brand-600 text-white hover:bg-brand-700 transition-colors disabled:opacity-30 disabled:cursor-not-allowed flex items-center justify-center">
                        <span class="material-icons-outlined text-base">arrow_forward</span>
                    </button>
                </div>
                <p class="text-[10px] text-slate-400 mt-1 text-center">Enter to send &middot; Shift+Enter for new line</p>
            </div>
        </div>
    </div>`;
}
