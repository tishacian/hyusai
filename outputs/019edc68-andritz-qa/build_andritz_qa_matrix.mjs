import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "/Users/thib/Developer/PAPAI/omnirag/outputs/019edc68-andritz-qa";
const outputXlsx = path.join(outputDir, "andritz_qa_matrix.xlsx");
const previewPng = path.join(outputDir, "andritz_qa_matrix_summary.png");
const inspectTxt = path.join(outputDir, "andritz_qa_matrix_inspect.txt");
const sheetPreviewRanges = [
  ["Coverage Summary", "A1:D21", "andritz_qa_matrix_summary.png"],
  ["QA Matrix", "A1:P14", "andritz_qa_matrix_qa_matrix_preview.png"],
  ["Test Backlog", "A1:L18", "andritz_qa_matrix_test_backlog_preview.png"],
  ["Defect Register", "A1:J26", "andritz_qa_matrix_defect_register_preview.png"],
  ["Execution Log", "A90:I128", "andritz_qa_matrix_execution_log_preview.png"],
  ["Phase Log", "A85:F122", "andritz_qa_matrix_phase_log_preview.png"],
];
const discoveryDate = "2026-06-23";

const status = "Discovered - tests drafted, not executed";
const noDefects = 0;
const severityNone = "None";

function src(...refs) {
  return refs.join("\n");
}

function tests(featureId, scenarios) {
  return scenarios.map((scenario, index) => ({
    testId: `${featureId}-T${String(index + 1).padStart(2, "0")}`,
    featureId,
    type: scenario.type,
    scenario: scenario.scenario,
    preconditions: scenario.preconditions || "Authenticated Andritz workspace user with safe, non-production-destructive test data.",
    steps: scenario.steps,
    expected: scenario.expected,
    status: "Not executed",
    severityIfFails: scenario.severityIfFails || "Medium",
    notes: scenario.notes || "",
  }));
}

const features = [
  {
    id: "CHT-001",
    name: "Recherche chat route and business shell",
    story: "As an Andritz business user, I can open the Recherche chat surface from the authenticated shell and understand that it searches workspace knowledge.",
    expected: "Route /chat mounts ChatWorkspaceComponent behind auth/navigation guards. In business surface it shows the Recherche tag, workspace-source hint, and ChatPanel.",
    edges: "Unauthenticated access redirects through auth guard; business/executive profile changes header copy; route can also be mounted as overlay/focus surface.",
    validation: "Route exists; auth guard active; header and panel render; workspace profile does not hide the surface unintentionally.",
    dependencies: "Angular routes, NavigationProfileService, WorkspaceService, ChatPanelComponent.",
    assumptions: "The Andritz navigation profile exposes chat/recherche to intended members.",
    notes: "Initial code discovery only; no browser execution yet.",
    source: src("frontend-ng/src/app/app.routes.ts", "frontend-ng/src/app/features/chat/chat-workspace.component.ts"),
    scope: "Chat Recherche",
    tests: [
      { type: "Happy path", scenario: "Open Recherche route", steps: "Login, navigate to /chat, observe shell.", expected: "Recherche shell and chat panel are visible without console errors." },
      { type: "Permission/security", scenario: "Open route unauthenticated", preconditions: "No auth token.", steps: "Navigate to /chat.", expected: "User is redirected or blocked by auth guard.", severityIfFails: "High" },
      { type: "Responsive", scenario: "Open chat on mobile width", steps: "Set viewport < 480px and open /chat.", expected: "Header and composer remain usable without clipped controls." },
      { type: "Regression", scenario: "Mocked Andritz browser route smoke", steps: "Run local Playwright with mocked auth/workspace APIs and open /chat.", expected: "The authenticated shell and chat surface render without contacting real backend data." },
    ],
  },
  {
    id: "CHT-002",
    name: "Quick ask workspace RAG",
    story: "As a user, I can ask a question without selecting a system, using workspace default knowledge and source policy.",
    expected: "Quick ask mode uses workspace RAG defaults and sends chat requests through /chat/stream or /chat/completion depending on panel settings.",
    edges: "Empty prompt, long prompt, no matching sources, backend timeout, disabled document upload.",
    validation: "Question cannot be blank; response must show answer state, sources when available, and non-blocking error messaging on timeout.",
    dependencies: "ChatPanelComponent, /api/v1/chat/stream, /api/v1/chat/completion, RAG service.",
    assumptions: "Workspace default source scope is configured for Andritz.",
    notes: "Focus on correctness and source grounding before performance claims.",
    source: src("frontend-ng/src/app/features/chat/chat-panel.component.ts", "backend/app/api/v1/endpoints/chat.py"),
    scope: "Chat Recherche",
    tests: [
      { type: "Happy path", scenario: "Ask a normal Andritz knowledge question", steps: "Enter a business question and send.", expected: "Assistant streams or returns an answer with stable final state." },
      { type: "Error path", scenario: "Backend stream timeout", steps: "Simulate or observe slow response beyond configured timeout.", expected: "UI stops streaming and displays recoverable error without losing the user prompt.", severityIfFails: "High" },
      { type: "Boundary", scenario: "Very long prompt", steps: "Paste a long question near client/server limits and send.", expected: "Request is accepted or rejected with clear validation; UI remains responsive." },
      { type: "Regression", scenario: "Mocked Recherche quick ask stream", steps: "Open /chat, send a workspace question with mocked SSE retrieval/text chunks.", expected: "The browser shows the user question, streamed answer, source count and source detail; payload includes session_id, stream=true and include_sources=true.", severityIfFails: "High" },
    ],
  },
  {
    id: "CHT-003",
    name: "System-scoped chat selection",
    story: "As a user, I can select a System so the chat uses scoped instructions, retrieval settings, and flow overrides.",
    expected: "System picker lists systems; selecting one changes mode and passes system/context settings into chat requests.",
    edges: "System deleted while selected; system has no context; flow builder link only appears where available.",
    validation: "Selected system id persists for current interaction; invalid system degrades safely to quick ask or error.",
    dependencies: "CanonicalApiService systems, ChatWorkspaceComponent, ChatPanelComponent.",
    assumptions: "Andritz has at least one chat-capable system in the workspace.",
    notes: "Need VM validation against current Andritz system catalog.",
    source: src("frontend-ng/src/app/features/chat/chat-workspace.component.ts", "frontend-ng/src/app/core/canonical-api.service.ts"),
    scope: "Chat Recherche",
    tests: [
      { type: "Happy path", scenario: "Select a system and ask", steps: "Choose a system, ask a question.", expected: "Request includes system scope and answer uses the selected context." },
      { type: "Invalid input", scenario: "Stale/deleted system id", steps: "Reload with an invalid preselected system id.", expected: "UI does not crash and user can continue in quick mode." },
      { type: "Permission/security", scenario: "System not readable by user", steps: "Use a user lacking read permission.", expected: "System is hidden or backend rejects access; no data leak.", severityIfFails: "High" },
    ],
  },
  {
    id: "CHT-004",
    name: "Drop-and-ask document upload",
    story: "As a user, I can drop files into chat to create an ephemeral document context for a question.",
    expected: "Dropzone accepts PDF, TXT, MD, DOCX, CSV, JSON, XLSX variants and images listed in the accept attribute; uploaded docs are indexed and tracked as session docs.",
    edges: "Unsupported file, upload failure, partial metadata, large document, feature flag disabled.",
    validation: "Only allowed extensions are selectable; upload progress is visible; metadata failure does not break chat.",
    dependencies: "ChatWorkspaceComponent, /documents/upload or batch upload, /documents/{id}/metadata, /contexts.",
    assumptions: "Feature flag chat_document_upload is enabled for Andritz unless explicitly disabled.",
    notes: "High value regression area because uploaded docs change retrieval scope.",
    source: src("frontend-ng/src/app/features/chat/chat-workspace.component.ts", "backend/app/api/v1/endpoints/documents.py", "backend/app/api/v1/endpoints/contexts.py"),
    scope: "Chat Recherche",
    tests: [
      { type: "Happy path", scenario: "Drop PDF then ask", steps: "Drop a small PDF, wait for indexing, ask about it.", expected: "Doc appears in session docs and answer cites it." },
      { type: "Error path", scenario: "Unsupported file type", steps: "Try uploading an unsupported extension.", expected: "Upload is blocked or rejected with clear message; no broken context." },
      { type: "Boundary/performance", scenario: "Large XLSX/PDF upload", steps: "Upload a near-limit supported file.", expected: "Progress and failure/success states remain clear; UI does not freeze.", severityIfFails: "High" },
      { type: "Permission/security", scenario: "Workspace disables chat document upload", steps: "Set features.chat_document_upload=false, open /chat, and ask a normal question.", expected: "Drop-and-ask file controls are hidden, no upload request can be sent, and Quick ask still streams normally.", severityIfFails: "High" },
      { type: "Error path", scenario: "Upload batch fails", steps: "Mock /documents/upload-batch failure after selecting a synthetic file.", expected: "A recoverable error is visible, no ephemeral context is created, no fake session doc is shown, and Quick ask remains usable with null context.", severityIfFails: "High" },
      { type: "Data integrity", scenario: "Partial upload excludes failed files", steps: "Mock /documents/upload-batch with one success and one failed row.", expected: "Only successful filenames are shown and sent to the ephemeral context; failed filenames are excluded while the partial-failure warning remains visible.", severityIfFails: "High" },
    ],
  },
  {
    id: "CHT-005",
    name: "Persist ephemeral chat context",
    story: "As a user, I can keep a temporary drop-and-ask context as a permanent workspace context.",
    expected: "Persist button calls POST /contexts/{id}/persist for ephemeral contexts and refreshes UI state.",
    edges: "Already permanent context, expired context, permission denied, network retry.",
    validation: "Persist is idempotent; no duplicate context is created; failure is visible.",
    dependencies: "ChatWorkspaceComponent, CanonicalApiService, /contexts/{id}/persist.",
    assumptions: "User has context persist permission in Andritz if the button is visible.",
    notes: "Data integrity risk is duplication or dangling docs.",
    source: src("frontend-ng/src/app/features/chat/chat-workspace.component.ts", "backend/app/api/v1/endpoints/contexts.py"),
    scope: "Chat Recherche",
    tests: [
      { type: "Happy path", scenario: "Persist ephemeral context", steps: "Upload docs, click Persist.", expected: "Context becomes permanent and remains attached." },
      { type: "Error path", scenario: "Persist expired context", steps: "Use an expired context id.", expected: "Backend rejects; UI keeps current chat usable." },
      { type: "Permission/security", scenario: "Persist without permission", steps: "Use limited role.", expected: "No permanent context is created.", severityIfFails: "High" },
      { type: "Regression", scenario: "Persist is explicit after drop-and-ask upload", steps: "Attach a synthetic session doc, wait for the Persist control, then click it.", expected: "No persist request occurs before the click; exactly one POST /contexts/{id}/persist occurs after the click and success is visible.", severityIfFails: "High" },
      { type: "Error path", scenario: "Persist failure is visible", steps: "Mock /contexts/{id}/persist failure after attaching a synthetic session doc and clicking Persist.", expected: "Exactly one persist request is sent, a recoverable error is visible, and the Persist action is re-enabled without duplicate context promotion.", severityIfFails: "Medium" },
    ],
  },
  {
    id: "CHT-006",
    name: "Chat source scope and session-doc mode",
    story: "As a user, I can choose whether temporary docs replace or complement workspace sources.",
    expected: "ChatPanel includes context_id and context_mode when session docs exist; workspace source policy still applies.",
    edges: "No context id, selected source stale, empty session docs, mixed workspace and uploaded sources.",
    validation: "Request payload matches selected mode; answer sources make scope clear.",
    dependencies: "ChatPanelComponent, ChatWorkspaceComponent, RAG source policy.",
    assumptions: "Andritz source policy allows expected workspace documents.",
    notes: "Needs manual UI verification because mode controls are inside large chat panel.",
    source: src("frontend-ng/src/app/features/chat/chat-panel.component.ts", "backend/app/api/v1/endpoints/chat.py"),
    scope: "Chat Recherche",
    tests: [
      { type: "Happy path", scenario: "Ask with session docs complementing workspace", steps: "Upload doc, set complement mode, ask.", expected: "Answer may cite both workspace and session docs." },
      { type: "Boundary", scenario: "Ask with no session docs but context mode set", steps: "Clear docs then send request.", expected: "Backend handles null/empty context safely." },
      { type: "Validation", scenario: "Source selection visible in request", steps: "Inspect network payload.", expected: "context_id/context_mode/source_selection reflect UI." },
      { type: "Regression", scenario: "Mocked drop-and-ask combine payload", steps: "Attach a synthetic session doc, switch to + Sources, ask a question and inspect mocked stream request.", expected: "No real upload occurs; the stream payload includes context_id, context_mode=combine, selected workspace scope and include_sources=true.", severityIfFails: "High" },
      { type: "Regression", scenario: "Mocked drop-and-ask only payload", steps: "Attach a synthetic session doc, keep the default Only mode, ask a question and inspect mocked stream request.", expected: "No real upload occurs; the stream payload includes context_id, context_mode=replace and knowledge_scope=null so workspace sources are not mixed into session-doc-only answers.", severityIfFails: "High" },
      { type: "Regression", scenario: "Latest source mode wins after toggle", steps: "Attach a synthetic session doc, switch to + Sources, switch back to Only, ask and inspect mocked request payload.", expected: "Final /sessions and /chat/stream payloads use context_mode=replace and knowledge_scope=null; no stale combine/workspace scope remains.", severityIfFails: "High" },
      { type: "Regression", scenario: "Detach last session doc clears stale scope", steps: "Attach a synthetic session doc, remove it from the session, ask and inspect mocked request payload.", expected: "Context PATCH writes data_refs=[]; final /sessions and /chat/stream payloads use context_id=null and context_mode=null so no removed document remains in scope.", severityIfFails: "High" },
      { type: "Error path", scenario: "Detach context update failure preserves session doc", steps: "Attach a synthetic session doc, mock /contexts/{id} PATCH failure, click remove, then ask.", expected: "A recoverable error is visible, the doc remains attached, Persist remains available and the next request still carries context_id/context_mode for the existing session doc.", severityIfFails: "Medium" },
      { type: "Regression", scenario: "Detach one of multiple session docs keeps remaining scope", steps: "Attach two synthetic session docs, remove one, then ask and inspect mocked request payload.", expected: "Context PATCH keeps only the remaining filename in data_refs; the remaining doc stays visible and the next request keeps context_id/context_mode for the still-attached session doc.", severityIfFails: "High" },
      { type: "Regression", scenario: "Re-upload after last detach recreates context", steps: "Attach a synthetic session doc, detach it, attach a different synthetic doc, then ask and inspect mocked request payload.", expected: "The second upload creates a fresh ephemeral context payload with only the new filename, and the next request uses the recreated session-doc context without stale data_refs.", severityIfFails: "High" },
      { type: "Error path", scenario: "Context creation failure does not fake attachment", steps: "Attach a synthetic session doc while POST /contexts fails, then ask and inspect mocked request payload.", expected: "A recoverable error is visible, the doc is removed from the session-doc UI, Persist is unavailable, and final /sessions and /chat/stream payloads use context_id=null/context_mode=null with workspace scope.", severityIfFails: "High" },
      { type: "Error path", scenario: "Append context update failure rolls back only new doc", steps: "Attach a first synthetic session doc, then attach a second doc while PATCH /contexts/{id} fails; ask and inspect mocked request payload.", expected: "The failed second doc is removed from the session-doc UI, the first doc remains attached, Persist stays available, and final /sessions and /chat/stream payloads keep the existing context_id/context_mode for the first doc only.", severityIfFails: "High" },
    ],
  },
  {
    id: "CHT-007",
    name: "Streaming chat answer lifecycle",
    story: "As a user, I see answers stream progressively and settle into a final response with trace/audit information.",
    expected: "POST /chat/stream emits SSE chunks; ChatPanel buffers stream, finalizes message, logs audit, and handles stream closure.",
    edges: "Connection drop, malformed SSE, slow retrieval, source-less answer, timeout fallback.",
    validation: "Streaming flag resets; draft buffer clears; final answer is not duplicated; errors do not leave spinner stuck.",
    dependencies: "ChatPanelComponent, SSE service, /chat/stream, chat run ledger.",
    assumptions: "Network supports event streams for Andritz users.",
    notes: "Regression target after oracle/transcript decoupling work.",
    source: src("frontend-ng/src/app/features/chat/chat-panel.component.ts", "backend/app/api/v1/endpoints/chat.py", "backend/app/services/chat_run_ledger.py"),
    scope: "Chat Recherche",
    tests: [
      { type: "Happy path", scenario: "Stream normal answer", steps: "Ask a grounded question.", expected: "Tokens appear progressively and final message persists." },
      { type: "Error path", scenario: "Interrupted network", steps: "Abort network mid-stream.", expected: "UI leaves streaming state and keeps user prompt/partial response recoverably.", severityIfFails: "High" },
      { type: "Performance", scenario: "Slow retrieval before stream", steps: "Ask a hard question.", expected: "User receives clear waiting state and no frozen composer." },
    ],
  },
  {
    id: "CHT-008",
    name: "Chat source citations and preview drawer",
    story: "As a user, I can inspect answer sources and preview the cited document without leaving chat.",
    expected: "Sources are rendered as chips/drawer entries; preview uses document rich-preview endpoints and cited excerpts where available.",
    edges: "Missing document id, unsupported preview type, metadata without page, deleted source.",
    validation: "Preview link only appears when document_id/preview_url is valid; missing preview falls back to download or message.",
    dependencies: "AssistantDraftDrawerComponent, DocumentPreviewComponent, /documents/{id}/rich-preview.",
    assumptions: "Object store has original or converted document previews for Andritz collections.",
    notes: "Important for trust and auditability.",
    source: src("frontend-ng/src/app/features/chat/assistant-draft-drawer.component.ts", "frontend-ng/src/app/shared/document-preview/document-preview.component.ts", "backend/app/api/v1/endpoints/documents.py"),
    scope: "Chat Recherche",
    tests: [
      { type: "Happy path", scenario: "Open cited PDF source", steps: "Ask a sourceable question, click source.", expected: "Preview opens at available page/excerpt." },
      { type: "Error path", scenario: "Missing preview asset", steps: "Click source whose preview is unavailable.", expected: "Fallback message/download route appears; UI does not crash." },
      { type: "Permission/security", scenario: "Preview unauthorized source", steps: "Attempt preview as limited user.", expected: "Backend denies and no document data leaks.", severityIfFails: "High" },
    ],
  },
  {
    id: "CHT-009",
    name: "Deep retrieval job from chat",
    story: "As a user, I can request deeper retrieval when the first answer needs more evidence.",
    expected: "ChatPanel posts /chat/deep-retrieval-jobs, polls workspace/document job URL, and promotes deep answer/sources into the message.",
    edges: "Job queued/running long, job fails, source question missing, duplicate jobs.",
    validation: "Progress, stage, summary, deep sources and final answer update correctly; failed jobs remain inspectable.",
    dependencies: "ChatPanelComponent, /chat/deep-retrieval-jobs, /workspace-jobs or /documents/jobs.",
    assumptions: "Worker queue is running in Andritz deployment.",
    notes: "Long-running path; use non-destructive questions only.",
    source: src("frontend-ng/src/app/features/chat/chat-panel.component.ts", "backend/app/api/v1/endpoints/chat.py", "backend/app/api/v1/endpoints/workspace_jobs.py"),
    scope: "Chat Recherche",
    tests: [
      { type: "Happy path", scenario: "Launch deep search", steps: "Run deep retrieval from an answer.", expected: "Job progresses and answer/sources are enriched." },
      { type: "Error path", scenario: "Worker job fails", steps: "Simulate failed job status.", expected: "Failure is shown without replacing the original answer." },
      { type: "Performance", scenario: "Long-running deep search", steps: "Observe polling for a slow job.", expected: "Polling does not overload backend or freeze UI." },
      { type: "Regression", scenario: "Mocked auto deep queue to completed answer", steps: "Stream a deep_queued event, poll a mocked workspace job, and wait for completion.", expected: "The browser shows a persistent Deep Search tracker, polls the job once, promotes the deep answer and source summary, and keeps all data synthetic.", severityIfFails: "High" },
    ],
  },
  {
    id: "CHT-010",
    name: "Retrieval plan preview",
    story: "As a power user or reviewer, I can preview how retrieval will plan a chat query before or during execution.",
    expected: "POST /chat/retrieval-plan-preview returns retrieval planning information used by chat controls/debug surfaces.",
    edges: "No sources, invalid retrieval mode, permissions, very broad query.",
    validation: "Preview request respects workspace scope and does not expose inaccessible collections.",
    dependencies: "Chat endpoint, RAG retrieval plan service.",
    assumptions: "UI control is available in current profile or debug mode.",
    notes: "API interaction discovered; UI access needs browser validation.",
    source: src("backend/app/api/v1/endpoints/chat.py", "backend/app/services/rag/retrieval_plan.py"),
    scope: "Chat Recherche",
    tests: [
      { type: "Happy path", scenario: "Preview retrieval plan", steps: "Submit plan preview for a normal query.", expected: "Plan contains selected strategy and scoped sources." },
      { type: "Invalid input", scenario: "Unsupported retrieval mode", steps: "Send invalid mode.", expected: "Backend rejects or normalizes safely." },
      { type: "Permission/security", scenario: "Preview hidden collection", steps: "Use user without collection access.", expected: "Preview omits inaccessible sources.", severityIfFails: "High" },
    ],
  },
  {
    id: "CHT-011",
    name: "Chat voice dictation and live partials",
    story: "As a user, I can dictate a chat prompt and see server-authoritative live partials/final transcript.",
    expected: "Chat voice opens a VoiceSessionGateway session, sends MediaRecorder chunks, receives text.partial/text.final, and updates draft/final prompt.",
    edges: "Unsupported browser speech preview, late partial, empty final, microphone denied, network gap.",
    validation: "Final transcript supersedes preview; late partials for same turn do not corrupt final; empty final preserves usable fallback preview.",
    dependencies: "ChatPanelComponent, VoiceSessionService, VoiceSessionGateway, STT provider.",
    assumptions: "OpenAI/voice provider credentials are configured on VM.",
    notes: "Known high-sensitivity UX area; requires latency metrics during execution.",
    source: src("frontend-ng/src/app/features/chat/chat-panel.component.ts", "frontend-ng/src/app/core/voice-session.service.ts", "backend/app/services/voice_session_gateway.py"),
    scope: "Chat Recherche",
    tests: [
      { type: "Happy path", scenario: "Dictate prompt", steps: "Click voice, speak one sentence, stop.", expected: "Partial appears during speech and final fills composer." },
      { type: "Error path", scenario: "Microphone permission denied", steps: "Deny mic access.", expected: "Clear error; no stuck recording state." },
      { type: "Performance", scenario: "Network jitter during chunks", steps: "Throttle network and dictate.", expected: "No lost final; client metrics show chunk gaps.", severityIfFails: "High" },
    ],
  },
  {
    id: "CHT-012",
    name: "Chat voice conversation loop and TTS controls",
    story: "As a user, I can run voice2voice chat with auto-send, TTS playback, pause/resume, and interruption.",
    expected: "Voice loop controls start/pause/resume/stop, can auto-send final transcript, interrupt TTS on speech or user stop, and emit loop lifecycle events.",
    edges: "Barge-in during TTS, stop while transcribing, resume after mic track republish, unsupported LiveKit.",
    validation: "Loop state transitions are consistent; no silent mic after resume; TTS queue clears on interruption.",
    dependencies: "ChatPanelComponent, VoiceTtsPlaybackService, LiveKitConversationService, VoiceSessionGateway.",
    assumptions: "Andritz users have browser permissions and network for LiveKit or cascade fallback.",
    notes: "Must not block text chat when voice fails.",
    source: src("frontend-ng/src/app/features/chat/chat-panel.component.ts", "frontend-ng/src/app/core/livekit-conversation.service.ts", "frontend-ng/src/app/core/voice-tts-playback.service.ts"),
    scope: "Chat Recherche",
    tests: [
      { type: "Happy path", scenario: "Run voice loop ask/answer", steps: "Start loop, speak, wait for answer/TTS.", expected: "Transcript sends automatically and TTS plays answer." },
      { type: "Boundary", scenario: "Stop while transcribing", steps: "Speak, stop before final transcript.", expected: "State resets without duplicate send." },
      { type: "Error path", scenario: "Interrupt TTS with speech", steps: "Start speaking while TTS plays.", expected: "TTS stops and mic capture resumes cleanly.", severityIfFails: "High" },
    ],
  },
  {
    id: "CHT-013",
    name: "Chat correction to knowledge proposal",
    story: "As an expert reviewer, I can correct an assistant answer and turn the correction into a reviewable knowledge proposal.",
    expected: "Chat correction payload posts to /knowledge-capture/chat-correction; backend creates proposal, applies review policy, and returns acknowledgement.",
    edges: "No sources, correction too short, reviewer lacks permission, review disabled, source attachment already uploaded.",
    validation: "Requires chat_correct permission; proposal status honors review policy; publication is not automatic unless explicitly intended by correction policy.",
    dependencies: "ChatPanelComponent, ApiService, knowledge_capture chat-correction endpoint.",
    assumptions: "Reviewer roles have intended correction rights in Andritz.",
    notes: "Out of main capture flow but affects knowledge base quality.",
    source: src("frontend-ng/src/app/features/chat/chat-panel.component.ts", "frontend-ng/src/app/core/api.service.ts", "backend/app/api/v1/endpoints/knowledge_capture.py", "backend/app/services/knowledge_capture.py"),
    scope: "Chat Recherche, Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Submit correction with sources", steps: "Correct an answer and submit.", expected: "Proposal is created and acknowledgement appears." },
      { type: "Permission/security", scenario: "Non-reviewer submits correction", steps: "Use member without correction permission.", expected: "Backend rejects; no proposal created.", severityIfFails: "High" },
      { type: "Validation", scenario: "Empty correction", steps: "Submit blank correction.", expected: "Client or backend blocks with clear message." },
    ],
  },
  {
    id: "CHT-014",
    name: "Durable chat sessions and history",
    story: "As a user, I can continue previous chat sessions and retrieve their messages.",
    expected: "Sessions endpoints create/list/get/patch/delete durable chat sessions and messages scoped to current workspace.",
    edges: "Admin list vs own sessions, deleted session, missing messages, workspace switch.",
    validation: "Users only see permitted sessions; session touch/update occurs after turns; deletes are scoped.",
    dependencies: "/api/v1/sessions endpoints, ChatPanel session id, audit logger.",
    assumptions: "Andritz retention policy allows session history.",
    notes: "Needs non-destructive read-only validation before testing deletes.",
    source: src("backend/app/api/v1/endpoints/sessions.py", "frontend-ng/src/app/features/chat/chat-panel.component.ts"),
    scope: "Chat Recherche",
    tests: [
      { type: "Happy path", scenario: "Continue chat session", steps: "Ask, reload, reopen session.", expected: "Messages are listed and can continue." },
      { type: "Permission/security", scenario: "Read another user's private session", steps: "Attempt direct session id access.", expected: "Access denied unless admin/read_all.", severityIfFails: "High" },
      { type: "Error path", scenario: "Deleted session route", steps: "Open deleted session id.", expected: "404/recoverable UI state." },
    ],
  },
  {
    id: "CHT-015",
    name: "Workspace chat knowledge settings",
    story: "As an admin, I can configure chat source policy and defaults that Recherche and capture review gates honor.",
    expected: "Workspace chat knowledge settings are read by frontend and resolved by backend source policy helpers.",
    edges: "Settings absent, legacy settings route, conflicting system/workspace policy, review disabled.",
    validation: "Effective policy is consistent across chat, capture, and proposal auto-accept logic.",
    dependencies: "chat-knowledge-settings component, settings/presets APIs, knowledge_capture source policy resolver.",
    assumptions: "Andritz policy intentionally disables or enables review based on governance decision.",
    notes: "Policy mismatch can cause publication/review UX defects.",
    source: src("frontend-ng/src/app/features/workspace/chat-knowledge-settings.component.ts", "backend/app/api/v1/endpoints/knowledge_capture.py", "backend/app/services/systems/bootstrap.py"),
    scope: "Chat Recherche, Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Read effective policy", steps: "Open settings and compare backend behavior.", expected: "UI policy matches capture proposal handling." },
      { type: "Boundary", scenario: "Missing settings", steps: "Use workspace with no explicit source policy.", expected: "Defaults are conservative and consistent." },
      { type: "Permission/security", scenario: "Member edits admin setting", steps: "Attempt settings write as member.", expected: "Write denied.", severityIfFails: "High" },
    ],
  },

  {
    id: "KCAP-001",
    name: "Capture dashboard sessions and fiches tabs",
    story: "As a capture user, I can see my capture sessions and published fiches from the Knowledge Capture dashboard.",
    expected: "Dashboard tabs list sessions, quality backlog, and published fiches with filters and open actions.",
    edges: "No sessions, archived sessions toggle, failed fiches load, open questions counts, author labels.",
    validation: "Counts match backend; archived visibility works; opening session routes to correct capture stage.",
    dependencies: "KnowledgeCaptureComponent, /knowledge-capture/sessions, /knowledge-capture/fiches.",
    assumptions: "Andritz reviewers/members have intended read permissions.",
    notes: "Baseline entry point for all capture workflows.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts", "backend/app/api/v1/endpoints/knowledge_capture.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Open dashboard", steps: "Navigate to /knowledge/capture.", expected: "Sessions tab loads and actions reflect permissions." },
      { type: "Boundary", scenario: "No sessions/fiches", steps: "Use empty workspace/user.", expected: "Empty states render without errors." },
      { type: "Permission/security", scenario: "Reviewer/member visibility", steps: "Compare reviewer and member roles.", expected: "Capture access matches IAM policy, no hidden data leak.", severityIfFails: "High" },
      { type: "Regression", scenario: "Mocked Andritz browser dashboard smoke", steps: "Run local Playwright with mocked capture sessions/fiches APIs and open /knowledge/capture.", expected: "The capture dashboard, empty states and primary session action render without contacting real backend data." },
      { type: "Responsive", scenario: "Open capture dashboard on mobile width", steps: "Set viewport to mobile width and open /knowledge/capture with mocked Andritz APIs.", expected: "The capture dashboard remains reachable and primary actions/empty state text are visible without real backend data." },
      { type: "Permission/security", scenario: "Reviewer IAM matrix exposes capture controls", steps: "Call /iam/matrix as workspace_reviewer in an IAM-enforced workspace.", expected: "The matrix exposes capture_session create plus owner-scoped update/execute as allowed for the subject.", severityIfFails: "High" },
      { type: "Regression", scenario: "Reviewer new capture button enabled from IAM matrix", steps: "Run local Playwright with mocked reviewer auth/workspace/IAM APIs and open /knowledge/capture.", expected: "The New/Nouvelle capture action is visible and enabled without contacting real backend data.", severityIfFails: "High" },
      { type: "Permission/security", scenario: "Open capture dashboard unauthenticated", preconditions: "No auth token.", steps: "Navigate directly to /knowledge/capture.", expected: "Route redirects to sign-in with redirectURL preserved before capture data APIs are exposed.", severityIfFails: "High" },
    ],
  },
  {
    id: "KCAP-002",
    name: "Prepare capture session",
    story: "As a user, I can prepare a capture by entering title, domain, document context, duration, and mode.",
    expected: "Prep form creates a plan/session through /knowledge-capture/plans with selected context and capture options.",
    edges: "Blank title, no collection context, unlimited duration, unsupported mode, loading failure.",
    validation: "Create button disabled without title/permission; selected context maps to context_id/system_id/capability where applicable.",
    dependencies: "KnowledgeCaptureComponent, create_capture_plan service, contexts/collections.",
    assumptions: "Andritz has available contexts/collections or workspace default sources.",
    notes: "Preconditions define later plan/free conversation branch.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts", "backend/app/api/v1/endpoints/knowledge_capture.py", "backend/app/services/knowledge_capture.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Create capture session", steps: "Fill title/domain/context, continue.", expected: "Session is created and next stage opens." },
      { type: "Validation", scenario: "Blank title", steps: "Clear title.", expected: "Continue button disabled." },
      { type: "Error path", scenario: "Plan creation fails", steps: "Simulate 500/timeout.", expected: "Error is visible and form state is preserved." },
      { type: "Permission/security", scenario: "Reviewer creates and starts capture under IAM", steps: "Use an IAM-enforced workspace and a workspace_reviewer membership to create a free-conversation capture then start it.", expected: "Reviewer can create and start their own capture session without inheriting broad admin rights.", severityIfFails: "High" },
    ],
  },
  {
    id: "KCAP-003",
    name: "Plan source extraction",
    story: "As a user, I can paste or upload an existing plan and have it extracted into capture structure.",
    expected: "POST /knowledge-capture/plan-source/extract parses text/file plan source and returns structured outline for review.",
    edges: "Unsupported file, empty extract, replaces existing plan flag, huge pasted outline.",
    validation: "File type and content errors are shown; extracted topics can be edited before approval.",
    dependencies: "ApiService plan-source/extract, capture plan builder.",
    assumptions: "Supported parser stack is installed on VM for uploaded plan files.",
    notes: "Need validate against PDF/DOCX/PPTX examples later.",
    source: src("frontend-ng/src/app/core/api.service.ts", "backend/app/api/v1/endpoints/knowledge_capture.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Upload plan file", steps: "Upload a valid plan document.", expected: "Topics/subtopics are extracted." },
      { type: "Invalid input", scenario: "Unsupported/empty file", steps: "Upload invalid file.", expected: "Clear rejection and no corrupted session plan." },
      { type: "Boundary", scenario: "Large pasted plan", steps: "Paste long outline.", expected: "Extraction completes or fails gracefully with retry path." },
    ],
  },
  {
    id: "KCAP-004",
    name: "Capture modes with plan, provided plan, free conversation, plan build",
    story: "As a user, I can choose the capture mode that matches the meeting: AI plan, provided plan, free conversation, or plan co-build.",
    expected: "CapturePlanMode controls prep/plan/session UI and backend plan shape, including free_conversation_v1 handling.",
    edges: "Switch mode mid-prep, free conversation without material, plan_build not ready, provided plan missing topics.",
    validation: "Mode-specific primary path is unique; free conversation does not expose irrelevant plan composer except fallback.",
    dependencies: "KnowledgeCaptureComponent mode state, create_capture_plan, finalize_capture.",
    assumptions: "UX baseline is planned mode; free mode should differ only by absent plan rail.",
    notes: "Historically high-risk desync area.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts", "backend/app/services/knowledge_capture.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Create free conversation session", steps: "Select free conversation and continue.", expected: "Capture opens in conversation_only without manual composer unless fallback." },
      { type: "Happy path", scenario: "Create provided plan session", steps: "Provide plan and approve.", expected: "Plan rail and breadcrumb guide capture." },
      { type: "Regression", scenario: "Free conversation report", steps: "Capture material and finalize.", expected: "Report is structured with Synthese de la capture topic.", severityIfFails: "High" },
      { type: "Regression", scenario: "Browser creates no-plan capture", steps: "Open Knowledge Capture, click New capture, fill a title and continue with Sans plan selected.", expected: "The browser posts plan_mode=free_conversation, opens the capture surface and hides the Plan rail.", severityIfFails: "High" },
    ],
  },
  {
    id: "KCAP-005",
    name: "Plan dialogue co-construction",
    story: "As a user, I can discuss with the assistant to co-build a capture plan before starting.",
    expected: "Dialogue turn endpoint appends conversation to plan dialogue, oracle proposes topics, and finalize generates structured topics.",
    edges: "LLM timeout, incoherent proposal, user edits after dialogue, ready_to_finalize false.",
    validation: "Dialogue turns persist; final plan requires enough structure before start.",
    dependencies: "/sessions/{id}/plan/dialogue-turn, /plan/finalize, capture_knowledge_oracle.",
    assumptions: "LLM provider available and model latency acceptable.",
    notes: "Do not execute with destructive content; this is plan-only.",
    source: src("backend/app/api/v1/endpoints/knowledge_capture.py", "backend/app/services/capture_knowledge_oracle.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Co-build plan", steps: "Send two dialogue turns then finalize.", expected: "Plan topics are produced and visible." },
      { type: "Error path", scenario: "LLM timeout", steps: "Simulate plan finalize timeout.", expected: "User remains on plan stage with retry option." },
      { type: "Validation", scenario: "Insufficient plan", steps: "Try starting before ready.", expected: "Start is blocked or requires explicit fallback." },
    ],
  },
  {
    id: "KCAP-006",
    name: "Plan topic editing, validation, approval",
    story: "As a user, I can edit topics/subtopics, validate the plan, and approve it before capture.",
    expected: "Plan topic GET/PATCH and validate-topics endpoints update normalized topic structure; approve endpoint marks plan approved/startable.",
    edges: "Duplicate topic ids, empty title, reorder/indent/outdent, validation warnings.",
    validation: "Plan structure remains normalized; approval status persists; capture cannot start from invalid plan.",
    dependencies: "KnowledgeCaptureComponent topic editor, amend_capture_plan, approve_capture_plan.",
    assumptions: "Existing planned-mode UX remains baseline.",
    notes: "Useful for comparing plan vs no-plan behavior.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts", "backend/app/api/v1/endpoints/knowledge_capture.py", "backend/app/services/knowledge_capture.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Edit and approve plan", steps: "Rename topic, add subtopic, validate, approve.", expected: "Approved plan persists and capture can start." },
      { type: "Invalid input", scenario: "Empty topic title", steps: "Clear topic title and validate.", expected: "Validation blocks or repairs safely." },
      { type: "Boundary", scenario: "Reorder nested topics", steps: "Move subtopics up/down/indent/outdent.", expected: "No topic loss or duplicate ids." },
    ],
  },
  {
    id: "KCAP-007",
    name: "Start, pause, resume capture session",
    story: "As a user, I can start the approved capture, pause it, and resume without losing transcript or plan position.",
    expected: "Start/pause/resume endpoints update session status; frontend updates state and voice loop accordingly.",
    edges: "Pause while transcribing, resume after connection loss, already active/paused, stale session id.",
    validation: "Status transitions are valid; audio resources released/restarted correctly; transcript remains intact.",
    dependencies: "/sessions/{id}/start, /pause, /resume; voice services.",
    assumptions: "User has capture_update permission.",
    notes: "Critical for long sessions.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts", "backend/app/api/v1/endpoints/knowledge_capture.py", "backend/app/services/knowledge_capture.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Start pause resume", steps: "Start session, pause, resume.", expected: "Session status and controls update correctly." },
      { type: "Boundary", scenario: "Pause while STT finalizing", steps: "Speak then pause immediately.", expected: "Final transcript is not lost." },
      { type: "Error path", scenario: "Resume stale session", steps: "Resume a completed/deleted session.", expected: "Clear error; UI does not enter active state.", severityIfFails: "High" },
    ],
  },
  {
    id: "KCAP-008",
    name: "Written capture turns",
    story: "As an expert, I can add written notes during capture and have them consumed by the same capture/oracle/report structure as voice turns.",
    expected: "Text input posts to /sessions/{id}/conversation-step or /turns with input_modality text and optional document refs.",
    edges: "Blank text, simultaneous voice turn, correction/complement kinds, active section missing.",
    validation: "Written turn appears in transcript/event ledger; it updates facts, retrieval/oracle context, and final report.",
    dependencies: "KnowledgeCaptureComponent composer, process_conversation_step, append_turn.",
    assumptions: "Voice and text share downstream consumption contracts.",
    notes: "Feature was added to support mixed input streams.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts", "backend/app/api/v1/endpoints/knowledge_capture.py", "backend/app/services/knowledge_capture.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Add typed note", steps: "Type note during active capture and submit.", expected: "Note appears as transcript turn and report fact." },
      { type: "Boundary", scenario: "Submit while voice is transcribing", steps: "Speak then submit typed note before final.", expected: "Both turns are persisted in correct order." },
      { type: "Validation", scenario: "Blank note", steps: "Submit whitespace.", expected: "Submit is blocked or ignored without event pollution." },
      { type: "Regression", scenario: "Add typed note in guided plan section", steps: "Create a synthetic guided-plan capture, validate the plan, start the session, then submit a typed note.", expected: "The browser keeps the active plan question/section context and posts the note as a text complement without document refs.", severityIfFails: "High" },
      { type: "Regression", scenario: "Switch guided plan section before typed note", steps: "Create a guided-plan capture, validate and start it, select another subtopic from the plan rail, then submit a typed note.", expected: "The browser sends the note as a text complement tied to the selected section question, not the previous/default section.", severityIfFails: "High" },
    ],
  },
  {
    id: "KCAP-009",
    name: "Voice runtime selection and session gateway",
    story: "As a capture user, I can capture orally through the configured voice runtime without blocking the capture workflow.",
    expected: "Voice runtime list is exposed; session starts cascade/OpenAI or LiveKit as configured; audio events flow through VoiceSessionGateway.",
    edges: "Runtime unavailable, provider fallback, wrong MIME, language unsupported, missing OpenAI key.",
    validation: "Voice failure shows recoverable notice; text/manual capture remains possible; runtime metrics emitted.",
    dependencies: "/voice-runtimes, /livekit, VoiceSessionGateway, VoiceRuntimeProvider.",
    assumptions: "Current deployment uses available OpenAI STT/voice provider settings.",
    notes: "Do not confuse subtitle UX with app purpose; transcript is capture input.",
    source: src("backend/app/api/v1/endpoints/knowledge_capture.py", "backend/app/api/v1/endpoints/livekit.py", "backend/app/services/voice_session_gateway.py", "frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Start capture voice", steps: "Click Parler/Demarrer and speak.", expected: "Audio chunks send, partial/final transcript appears." },
      { type: "Error path", scenario: "Provider unavailable", steps: "Simulate STT failure.", expected: "User sees error and can continue by text/manual." },
      { type: "Regression", scenario: "WebM/LiveKit MIME path", steps: "Capture with normal browser MediaRecorder.", expected: "No unnecessary Whisper/fallback path from MIME mismatch.", severityIfFails: "High" },
    ],
  },
  {
    id: "KCAP-010",
    name: "Voice capture modes normal, robust, manual_safe",
    story: "As a user with different device quality, I can choose normal, robust, or manual-safe capture behavior.",
    expected: "Local storage persists capture mode per workspace/profile; robust extends VAD thresholds; manual_safe disables auto_endpoint.",
    edges: "Stored invalid mode, workspace default conflict, changing mode mid-session, manual_safe with max_turn.",
    validation: "Robust never makes existing config less conservative; manual_safe never auto-endpoints.",
    dependencies: "voice-capture-config.ts, KnowledgeCaptureComponent, ChatPanelComponent.",
    assumptions: "Manual toggle remains first activation path; auto robust disabled unless explicitly enabled.",
    notes: "Previously impacted fluidity; needs careful UX testing.",
    source: src("frontend-ng/src/app/core/voice-capture-config.ts", "frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts", "frontend-ng/src/app/features/chat/chat-panel.component.ts"),
    scope: "Knowledge Capture, Chat Recherche",
    tests: [
      { type: "Happy path", scenario: "Switch robust mode", steps: "Select robust and reload.", expected: "Mode persists and resolved thresholds match robust preset." },
      { type: "Validation", scenario: "Manual safe endpoint", steps: "Select manual_safe and speak with silence.", expected: "No auto endpoint is sent; manual stop required." },
      { type: "Boundary", scenario: "Existing longer silence config", steps: "Set workspace silence above robust threshold.", expected: "Robust does not reduce it." },
    ],
  },
  {
    id: "KCAP-011",
    name: "Adaptive VAD endpoint and client metrics",
    story: "As a user, I get automatic turn endpoints on real pauses without false pauses from degraded devices.",
    expected: "Client monitors RMS/noise floor, speech/silence thresholds, hangover, grace, and emits client.metric runtime events.",
    edges: "Low microphone level, background noise, micro-cuts, resumed speech during grace, max turn cap.",
    validation: "Silence candidate cancels on resumed voice; requestData flushes before endpoint; metrics record endpoint_candidate/confirmed/cancelled.",
    dependencies: "VoiceLoopController, voice-capture-config, KnowledgeCaptureComponent audio monitor, VoiceSessionGateway client.metric.",
    assumptions: "AudioContext and MediaRecorder are available in user browser.",
    notes: "Field validation required; code discovery only now.",
    source: src("frontend-ng/src/app/core/voice-loop-controller.service.ts", "frontend-ng/src/app/core/voice-capture-config.ts", "frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts", "backend/app/services/voice_session_gateway.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Pause creates endpoint", steps: "Speak, pause naturally.", expected: "Endpoint confirmed after grace and final transcript produced." },
      { type: "Boundary", scenario: "Voice resumes during grace", steps: "Pause briefly then resume before grace ends.", expected: "Endpoint candidate is cancelled and same turn continues.", severityIfFails: "High" },
      { type: "Performance", scenario: "Long continuous speech", steps: "Speak until max_turn_ms.", expected: "Max turn endpoint flushes audio without browser memory growth." },
    ],
  },
  {
    id: "KCAP-012",
    name: "Partial STT and final transcript orchestration",
    story: "As a speaker, I see a live transcript-like preview while final STT remains authoritative.",
    expected: "Audio frames may trigger partial STT; endpoint finalizes, records endpoint_stt_ms/turn_audio_capture_ms/text_final_total_ms and text.final event.",
    edges: "Partial empty/same/stale/skipped, late partial same turn, reused partial, provider retry, oversized audio.",
    validation: "Final transcript is not blocked by oracle; partial metrics explain missing live text; reused_partial avoids duplicate provider call.",
    dependencies: "VoiceSessionGateway, KnowledgeCaptureComponent, ChatPanelComponent.",
    assumptions: "Batch STT cannot equal true realtime but should feel fluid enough.",
    notes: "User-facing latency concern; must be measured on VM.",
    source: src("backend/app/services/voice_session_gateway.py", "frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts", "frontend-ng/src/app/features/chat/chat-panel.component.ts"),
    scope: "Knowledge Capture, Chat Recherche",
    tests: [
      { type: "Happy path", scenario: "Partial then final", steps: "Speak 5-8 seconds.", expected: "Partial appears before final; final replaces/commits text." },
      { type: "Regression", scenario: "Late same-turn partial", steps: "Delay partial response while final transcribing.", expected: "Late same-turn partial is accepted or safely ignored with metric reason.", severityIfFails: "High" },
      { type: "Metrics", scenario: "No useful partial", steps: "Use empty/noisy audio.", expected: "runtime.metric records skipped/empty/same/stale reason." },
    ],
  },
  {
    id: "KCAP-013",
    name: "Retrieval prefetch during capture",
    story: "As an expert speaks, relevant context can be prefetched in the background without blocking transcript flow.",
    expected: "Client calls /retrieval-prefetch with transcript text and active section; backend returns chunks/hints/passive state using retrieval profiles.",
    edges: "Retrieval timeout, weak evidence, free conversation passive mode, stale turn/section.",
    validation: "Retrieval is visually separate from transcript; weak evidence does not produce grounded questions.",
    dependencies: "KnowledgeCaptureComponent maybePrefetchRetrieval, prefetch_capture_retrieval, RAG profiles.",
    assumptions: "Andritz collections are indexed enough for useful context.",
    notes: "Do not reintroduce visual blocking of transcript.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts", "backend/app/api/v1/endpoints/knowledge_capture.py", "backend/app/services/knowledge_capture.py", "backend/app/services/rag/retrieval_profiles.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Prefetch retrieves chunks", steps: "Speak about known source.", expected: "Chunks appear in context panel; transcript continues independently." },
      { type: "Error path", scenario: "Retrieval timeout", steps: "Force slow retrieval.", expected: "No grounded question is emitted; capture remains usable.", severityIfFails: "High" },
      { type: "Regression", scenario: "Oracle arrives while transcript pending", steps: "Observe simultaneous retrieval/questions and STT.", expected: "Transcript rendering is not delayed by questions." },
    ],
  },
  {
    id: "KCAP-014",
    name: "Oracle live questions and statuses",
    story: "As a capture facilitator, I can see AI-generated open questions only when sufficiently grounded, and manage their status.",
    expected: "Oracle questions are generated asynchronously, shown as active/open, and can be answered/dismissed/deferred through status endpoints.",
    edges: "No retrieval evidence, duplicate questions, muted oracle, stale session, slow LLM.",
    validation: "Questions carry grounding intent and never block text.final; muted sessions hide questions.",
    dependencies: "capture_knowledge_oracle, update_oracle_question_statuses, frontend activeOracleQuestions.",
    assumptions: "Quality is preferred over speed for question generation.",
    notes: "Core separation from voice path must be preserved.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts", "backend/app/services/capture_knowledge_oracle.py", "backend/app/services/knowledge_capture.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Grounded oracle question appears", steps: "Speak sourceable fact with retrieval evidence.", expected: "Question appears after transcript without blocking it." },
      { type: "Error path", scenario: "No evidence", steps: "Speak unsourceable statement.", expected: "No question is presented as grounded.", severityIfFails: "High" },
      { type: "Validation", scenario: "Dismiss/defer question", steps: "Change question status.", expected: "Status persists and UI updates." },
    ],
  },
  {
    id: "KCAP-015",
    name: "Capture document upload and list",
    story: "As an expert, I can upload PDFs, PPTX, DOC/DOCX, PNG, and JPEG documents during capture.",
    expected: "Documents are uploaded to a capture-specific collection, indexed, listed, and stored in session document state.",
    edges: "Multiple docs, indexing delayed, unsupported/large file, upload during voice capture.",
    validation: "Document support never interrupts voice capture; failed upload shows warning; list refresh updates active collection.",
    dependencies: "/sessions/{id}/documents, register_capture_documents, documents upload/indexing.",
    assumptions: "Allowed formats match browser accept and backend parser support.",
    notes: "Recently implemented; requires end-to-end test with sample files.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts", "backend/app/api/v1/endpoints/knowledge_capture.py", "backend/app/services/knowledge_capture.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Upload PDF and image", steps: "Upload one PDF and one PNG during capture.", expected: "Both appear in document panel and index without interrupting voice." },
      { type: "Boundary", scenario: "Upload while recording", steps: "Start voice capture and upload doc.", expected: "Voice stream continues and upload state is non-blocking.", severityIfFails: "High" },
      { type: "Invalid input", scenario: "Unsupported file", steps: "Upload unsupported type.", expected: "Rejected with clear message." },
      { type: "Error path", scenario: "Upload service failure", steps: "Upload a capture document while /sessions/{id}/documents returns an error, then add a written note.", expected: "A recoverable warning appears, no document is shown or previewed, and the written note still posts without document_refs/visual_context.", severityIfFails: "High" },
    ],
  },
  {
    id: "KCAP-016",
    name: "Capture document preview and active page/slide logging",
    story: "As an expert, I can navigate an uploaded document and have the viewed page/slide logged in the transcript timecode.",
    expected: "Preview opens rich-preview URL; view changes call /documents/view with document_id, page/slide, collection, title, and active_view metadata.",
    edges: "Preview not ready, document deleted, page unknown, slide vs page fields, rapid navigation.",
    validation: "Active view updates session state; view logging failure is non-blocking; timecode_ms is derived server-side.",
    dependencies: "DocumentPreviewComponent, record_capture_document_view, capture document state.",
    assumptions: "Preview component emits page/slide changes for supported formats.",
    notes: "Critical for later report source links.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts", "frontend-ng/src/app/shared/document-preview/document-preview.component.ts", "backend/app/services/knowledge_capture.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Navigate PDF page", steps: "Preview document, move to page 3.", expected: "Active view label updates and backend state includes page 3/timecode." },
      { type: "Boundary", scenario: "Rapid slide changes", steps: "Move across several slides quickly.", expected: "Final active view is correct; no UI lock." },
      { type: "Error path", scenario: "Preview unavailable", steps: "Open document still indexing.", expected: "Warning appears and capture continues." },
      { type: "Regression", scenario: "Written note uses active document view", steps: "Create a no-plan capture, attach a synthetic document, preview it, then add a written note.", expected: "The preview request stays collection-scoped; /documents/view records page 1; /turns carries document_refs and visual_context for the active document without a real upload.", severityIfFails: "High" },
      { type: "Error path", scenario: "View logging failure", steps: "Open a capture document while /documents/view returns an error, then add a written note.", expected: "The UI keeps the active view optimistically and the written turn carries document_refs/visual_context instead of blocking capture.", severityIfFails: "High" },
    ],
  },
  {
    id: "KCAP-017",
    name: "Active document references on voice and text turns",
    story: "As an expert, when I say or write 'on this page', the active document view is attached to the capture turn.",
    expected: "activeCaptureDocumentRef is included in voice frame metadata or typed turn payload as document_refs; report sources derive from facts and document refs.",
    edges: "No active view, document changes mid-turn, text and voice simultaneous, duplicate refs.",
    validation: "Turn metadata includes document_id/page/slide/timecode; report source links point back to the referenced location.",
    dependencies: "KnowledgeCaptureComponent activeCaptureDocumentFields, _normalize_capture_document_refs, report source merge.",
    assumptions: "The active view at submission/endpoint time is the intended reference.",
    notes: "High-value Andritz workflow for equipment/photo/page references.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts", "backend/app/services/knowledge_capture.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Voice references active page", steps: "Open page 2, speak 'sur cette page...'.", expected: "Committed turn contains document_refs with page 2." },
      { type: "Happy path", scenario: "Typed reference active slide", steps: "Open slide, type note.", expected: "Typed turn carries same doc ref." },
      { type: "Boundary", scenario: "Switch page during long turn", steps: "Speak while changing page.", expected: "Document ref behavior is deterministic and documented.", severityIfFails: "Medium" },
      { type: "Regression", scenario: "Typed note after switching active document", steps: "Upload two synthetic capture documents, preview the first then the second, and submit a written note.", expected: "The written turn references only the latest active document and carries the correct collection/page metadata.", severityIfFails: "High" },
      { type: "Regression", scenario: "Guided typed note keeps plan and active document reference", steps: "Create a guided-plan capture, switch to another plan subtopic, preview an uploaded document, then submit a typed note.", expected: "The turn payload keeps the selected plan question and carries document_refs plus visual_context for the active document view.", severityIfFails: "High" },
      { type: "Regression", scenario: "Voice turn keeps active document reference", steps: "Preview an uploaded capture document, then send audio.frame/audio.endpoint metadata for a voice turn.", expected: "The voice transport forwards document_refs plus visual_context through both WebSocket and LiveKit paths so the backend can attach the active page to the finalized transcript turn.", severityIfFails: "High" },
      { type: "Regression", scenario: "Written note after preview page change", steps: "Preview a capture PDF, move from page 1 to page 2, close the preview, then submit a written note.", expected: "The active-view label, /documents/view call and /turns payload all reference page 2 with document_refs plus visual_context.", severityIfFails: "High" },
    ],
  },
  {
    id: "KCAP-018",
    name: "Finish current section",
    story: "As a planned-session user, I can finish a section and move to the next plan section while retaining transcript continuity.",
    expected: "Finish section triggers section finalization or active section advance; breadcrumb updates; section synthesis can be computed.",
    edges: "Free conversation mode, no active section, section with no facts, finalization timeout.",
    validation: "No transcript loss; next section is selected; free mode does not expose misleading section controls.",
    dependencies: "finishCurrentSection, finalize_capture_section, set_active_capture_section.",
    assumptions: "Section finalization is optional background synthesis, not a voice blocker.",
    notes: "User wants paragraphs/structure without harming subtitle feeling.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts", "backend/app/services/knowledge_capture.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Finish planned section", steps: "Capture a fact, click finish section.", expected: "Section advances and previous facts remain." },
      { type: "Boundary", scenario: "Finish empty section", steps: "Finish section before any turn.", expected: "Graceful advance or warning." },
      { type: "Regression", scenario: "Free mode section controls", steps: "Open free conversation.", expected: "No plan-only controls confuse primary path." },
    ],
  },
  {
    id: "KCAP-019",
    name: "Closure sheet and finish/extend/schedule actions",
    story: "As a user near session end, I can finish capture, extend it, or schedule/record closure information.",
    expected: "Closure sheet endpoint summarizes captured material; closure action finish routes to finalization, extend increases duration, schedule follows existing closure flow.",
    edges: "No material, free conversation with material, finalization timeout, already completed session.",
    validation: "Finish with material creates structured proposal; timeout keeps user on capture/report with retry, not dashboard.",
    dependencies: "/closure-sheet, /closure, apply_session_closure_action, finalize_capture.",
    assumptions: "No-plan sessions with material must use finalize_capture path.",
    notes: "Prior UX defect area.",
    source: src("backend/app/api/v1/endpoints/knowledge_capture.py", "backend/app/services/knowledge_capture.py", "frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Finish capture with material", steps: "Capture two turns then finish.", expected: "Finalization loader completes and report opens." },
      { type: "Error path", scenario: "Finalization timeout", steps: "Simulate slow finalize.", expected: "User remains in session/report path with retry.", severityIfFails: "High" },
      { type: "Boundary", scenario: "Finish empty free session", steps: "Create free session, no material, finish.", expected: "No bogus proposal is published or displayed." },
      { type: "Regression", scenario: "No-plan finalization failure stays in capture", steps: "Create a no-plan capture, add a written note, then make the closure/finalization request fail.", expected: "The UI shows a recoverable failure, remains on the active capture session, keeps the turn payload, and sends no publish request.", severityIfFails: "High" },
    ],
  },
  {
    id: "KCAP-020",
    name: "Final report generation and loader",
    story: "As a user, I wait through an explicit finalization loader while the capture is transformed into a structured report.",
    expected: "beginCaptureFinalizing displays stages; finalize_capture computes sections, dedupe, vocabulary, reformulation, questions, and proposal payload.",
    edges: "Progress event missing, done event without proposal, connection lost, old proposal exists.",
    validation: "Loader has safety fallback to fetch latest proposal; does not navigate to dashboard on timeout.",
    dependencies: "KnowledgeCaptureComponent finalization state, finalize_capture progress callback.",
    assumptions: "Long-running finalization is acceptable if transparent.",
    notes: "Must be tested with planned and free sessions.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts", "backend/app/services/knowledge_capture.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Finalize to proposal", steps: "Finish a populated session.", expected: "Loader reaches done and report screen opens." },
      { type: "Error path", scenario: "Done event lost", steps: "Simulate missing event but persisted proposal.", expected: "Fallback fetch opens report." },
      { type: "Performance", scenario: "Large transcript finalization", steps: "Finalize long capture.", expected: "Progress remains visible and backend does not time out unexpectedly." },
    ],
  },
  {
    id: "KCAP-021",
    name: "Structured report fiche rendering",
    story: "As a reviewer, I see a styled structured fiche with sections, facts, sources, and open questions, not a raw markdown textarea.",
    expected: "buildReportFiche reads proposal.plan_structure.topics; fallback topic Synthese de la capture is generated for free sessions with facts.",
    edges: "No topics, unassigned facts, malformed markdown, sources without preview, open questions linking.",
    validation: "Renderer never falls back to raw textarea for valid material; source previews open from report.",
    dependencies: "KnowledgeCaptureComponent report builder, _ensure_free_conversation_report_topic.",
    assumptions: "Report markdown remains editable but structured view is primary.",
    notes: "Known previous no-plan desync area.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts", "backend/app/services/knowledge_capture.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Regression", scenario: "Free conversation structured report", steps: "Finalize no-plan capture.", expected: "Structured fiche shows Synthese de la capture topic.", severityIfFails: "High" },
      { type: "Happy path", scenario: "Preview report source", steps: "Click a report source with doc id.", expected: "Rich preview opens at referenced page/slide." },
      { type: "Boundary", scenario: "Malformed plan_structure", steps: "Load proposal with missing topics but facts.", expected: "Pseudo-topic is materialized." },
    ],
  },
  {
    id: "KCAP-022",
    name: "Report instruction rewrite",
    story: "As a reviewer, I can instruct the assistant to correct, complete, or rephrase the displayed report.",
    expected: "Instruction endpoint rewrites report content and returns updated proposal; fallback appends instruction if rewrite fails.",
    edges: "Blank instruction, LLM timeout, concurrent edits, accepted proposal.",
    validation: "Instruction does not publish; updated content remains reviewable and auditable.",
    dependencies: "/proposals/{id}/instruction, apply_proposal_report_instruction.",
    assumptions: "Reviewer understands this edits report draft, not source facts directly.",
    notes: "The manual composer in no-plan capture should not be confused with this report editor.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts", "backend/app/api/v1/endpoints/knowledge_capture.py", "backend/app/services/knowledge_capture.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Apply report instruction", steps: "Add instruction to improve section wording.", expected: "Report updates and proposal remains in review state." },
      { type: "Invalid input", scenario: "Blank instruction", steps: "Submit empty instruction.", expected: "Blocked by client/backend." },
      { type: "Error path", scenario: "LLM rewrite fails", steps: "Simulate failure.", expected: "Fallback preserves original report plus audit trail." },
    ],
  },
  {
    id: "KCAP-023",
    name: "Proposal open question handling",
    story: "As a reviewer, I can answer, defer, leave open, or invalidate proposal open questions.",
    expected: "Open-question endpoints update statuses; answering a question can trigger targeted section re-synthesis.",
    edges: "Duplicate question text, invalid question id, answered question reanswered, source retrieval refs.",
    validation: "Open question count updates; answered content is incorporated into report without losing sources.",
    dependencies: "answer_proposal_open_question, update_proposal_open_question_statuses.",
    assumptions: "Questions may arrive late but are managed in report sidebar.",
    notes: "Important for publication readiness.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts", "backend/app/services/knowledge_capture.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Answer open question", steps: "Open report with question, answer it.", expected: "Question becomes answered and report section updates." },
      { type: "Validation", scenario: "Invalidate question", steps: "Mark question invalid/delete.", expected: "It is removed from open count but audited." },
      { type: "Error path", scenario: "Unknown question id", steps: "Submit answer to stale id.", expected: "Backend rejects without corrupting proposal." },
    ],
  },
  {
    id: "KCAP-024",
    name: "Proposal review status",
    story: "As a reviewer or authorized owner, I can mark a proposal accepted, rejected, or needing revision according to review policy.",
    expected: "Review endpoint changes proposal.status and review metadata; review-disabled policy can auto-accept without auto-publishing.",
    edges: "Unauthorized reviewer, already published, review disabled, concurrent review.",
    validation: "Review policy is enforced; status changes are audited; acceptance does not publish automatically.",
    dependencies: "review_proposal, _auto_accept_capture_proposal_if_review_disabled, IAM.",
    assumptions: "Andritz policy may have review disabled but still requires explicit publish.",
    notes: "P0 safety guard from prior incident.",
    source: src("backend/app/api/v1/endpoints/knowledge_capture.py", "backend/app/services/knowledge_capture.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Accept proposal", steps: "Review report and accept.", expected: "Status becomes accepted; publish still requires explicit click." },
      { type: "Permission/security", scenario: "Unauthorized review", steps: "Attempt review as plain member if not allowed.", expected: "Denied.", severityIfFails: "High" },
      { type: "Regression", scenario: "Review disabled auto-accept", steps: "Finalize with review disabled.", expected: "Proposal accepted but not published.", severityIfFails: "Critical" },
    ],
  },
  {
    id: "KCAP-025",
    name: "Explicit publish proposal to knowledge",
    story: "As a user, I must explicitly confirm publication before a capture proposal is ingested into knowledge.",
    expected: "POST /proposals/{id}/publish promotes report and capture documents to knowledge only after explicit frontend action.",
    edges: "Pending review, already published, missing document promotions, source rewrite, open questions remaining.",
    validation: "No backend path auto-publishes during finalization/review; published fiche appears after publish; document links are rewritten to publication target.",
    dependencies: "publish_proposal_to_knowledge, _promote_capture_documents_for_publication, document service.",
    assumptions: "Open questions may block or warn depending policy; must verify actual code behavior.",
    notes: "Critical data governance feature.",
    source: src("backend/app/api/v1/endpoints/knowledge_capture.py", "backend/app/services/knowledge_capture.py", "frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts"),
    scope: "Knowledge Capture, Collections",
    tests: [
      { type: "Happy path", scenario: "Publish accepted proposal", steps: "Accept then click publish.", expected: "Fiche is published and visible in fiches/knowledge." },
      { type: "Regression", scenario: "No accidental publish", steps: "Finalize/review without clicking publish.", expected: "No publication row/document is created.", severityIfFails: "Critical" },
      { type: "Error path", scenario: "Publish with missing doc promotion", steps: "Use proposal with capture document source missing.", expected: "Publish fails clearly or publishes with safe source fallback." },
    ],
  },
  {
    id: "KCAP-026",
    name: "Free conversation structured finalization",
    story: "As a user capturing without a plan, I get the same structured report quality as planned mode, only without the plan rail.",
    expected: "Free sessions with proposal material call finalize_capture from proposal and closure finish paths; pseudo-topic is added if facts lack topics.",
    edges: "No material, old REST fallback, no topics but facts, closure action extend/schedule.",
    validation: "create_update_proposal fallback cannot produce raw unstructured report with facts; frontend reportFiche can render.",
    dependencies: "is_free_conversation_session, session_has_proposal_material, finalize_capture, _ensure_free_conversation_report_topic.",
    assumptions: "The session mode marker is free_conversation_v1 or mode=free_conversation.",
    notes: "Directly addresses prior no-plan UX break.",
    source: src("backend/app/api/v1/endpoints/knowledge_capture.py", "backend/app/services/knowledge_capture.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Regression", scenario: "POST proposal on free session", steps: "Call proposal endpoint on free session with material.", expected: "Structured proposal contains Synthese de la capture topic.", severityIfFails: "High" },
      { type: "Regression", scenario: "Closure finish free session", steps: "Finish free session with material.", expected: "Same structured proposal shape as finalize_capture." },
      { type: "Boundary", scenario: "Free session no material", steps: "Finish without substantive text.", expected: "No bogus report; existing path handles empty state." },
    ],
  },
  {
    id: "KCAP-027",
    name: "Archive, unarchive, delete capture sessions",
    story: "As a capture owner/admin, I can archive sessions, restore them, or delete them when appropriate.",
    expected: "Archive/unarchive/delete endpoints update visibility or permanently remove session artifacts according to permissions.",
    edges: "Archived session with published proposal, delete confirmation, not owner, open question counts.",
    validation: "Delete is confirmed in UI; backend enforces permissions; archived sessions can be toggled visible.",
    dependencies: "KnowledgeCaptureComponent dashboard actions, archive/delete services.",
    assumptions: "For Andritz data safety, destructive delete should be tested only with synthetic sessions.",
    notes: "Do not execute delete against real Andritz/SFTP-derived data without explicit approval.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts", "backend/app/api/v1/endpoints/knowledge_capture.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Archive and restore synthetic session", steps: "Archive then show archived and unarchive.", expected: "Visibility changes without data loss." },
      { type: "Permission/security", scenario: "Delete another user's session", steps: "Attempt direct delete as unauthorized user.", expected: "Denied.", severityIfFails: "High" },
      { type: "Destructive safety", scenario: "Delete requires confirmation", steps: "Click delete flow on synthetic session.", expected: "Explicit confirmation is required before delete." },
    ],
  },
  {
    id: "KCAP-028",
    name: "Published fiches library",
    story: "As a user, I can browse, filter, preview, and open knowledge fiches published from capture.",
    expected: "Fiches tab loads /knowledge-capture/fiches and filters by category, destination/collection, and author; preview/open actions use document ids/urls.",
    edges: "No fiches, missing preview_url, many fiches, author missing, category blank.",
    validation: "Filters update rows; preview honors permissions; session owner can open originating session.",
    dependencies: "KnowledgeCaptureComponent fiches tab, list_published_fiches.",
    assumptions: "Published fiches are stored as proposals/documents in current workspace.",
    notes: "Useful for post-publication verification.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts", "backend/app/services/knowledge_capture.py"),
    scope: "Knowledge Capture, Collections",
    tests: [
      { type: "Happy path", scenario: "Filter published fiches", steps: "Open fiches tab and filter.", expected: "Rows update and counts remain consistent." },
      { type: "Error path", scenario: "Preview missing", steps: "Open fiche without preview_url/document_id.", expected: "No broken preview action." },
      { type: "Permission/security", scenario: "Non-owner open session", steps: "Click session action as non-owner.", expected: "Only permitted sessions open.", severityIfFails: "High" },
    ],
  },
  {
    id: "KCAP-029",
    name: "Quality backlog and defer actions",
    story: "As a reviewer, I can see capture quality items and defer them from dashboard/session views.",
    expected: "Quality backlog endpoint lists imprecisions/contradictions/open questions; defer endpoint updates status.",
    edges: "Empty backlog, stale item id, repeated defer, session archived.",
    validation: "Backlog item count updates; deferred items do not disappear incorrectly from report audit.",
    dependencies: "/quality-backlog, /quality/defer, proposal/open question services.",
    assumptions: "Quality tabs are shown for intended reviewer roles.",
    notes: "Potential bridge between capture and review queue.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts", "backend/app/api/v1/endpoints/knowledge_capture.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Defer quality item", steps: "Open backlog item and defer.", expected: "Item status updates and count changes." },
      { type: "Boundary", scenario: "Empty backlog", steps: "Open dashboard with no issues.", expected: "Empty state visible." },
      { type: "Error path", scenario: "Stale item id", steps: "Defer already removed item.", expected: "Clear error and list reload possible." },
    ],
  },
  {
    id: "KCAP-030",
    name: "Capture event ledger and amendments",
    story: "As a user or reviewer, I can inspect and amend capture events so transcript corrections remain auditable.",
    expected: "Events endpoint lists ordered ExpertCaptureEvent rows; amend endpoint updates text_amended/status/source and syncs transcript.",
    edges: "Amending finalized/published event, duplicate client turn id, dirty transcript materialization.",
    validation: "Amendment changes effective text and proposal facts after rebuild; raw text remains available for audit.",
    dependencies: "list_capture_events, amend_capture_event, transcript materialization helpers.",
    assumptions: "UI exposes amendment where intended; backend path exists regardless.",
    notes: "Important when voice transcription is good but needs expert correction.",
    source: src("backend/app/api/v1/endpoints/knowledge_capture.py", "backend/app/services/knowledge_capture.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Amend transcript event", steps: "Modify a synthetic event text.", expected: "Event effective text and transcript update." },
      { type: "Permission/security", scenario: "Unauthorized amend", steps: "Attempt amend as non-owner.", expected: "Denied.", severityIfFails: "High" },
      { type: "Regression", scenario: "Amend then finalize", steps: "Amend before final report.", expected: "Report uses amended text, not raw erroneous text." },
    ],
  },

  {
    id: "COL-001",
    name: "Knowledge collections list",
    story: "As a user, I can see workspace knowledge collections and their status/counts.",
    expected: "Knowledge base page loads /documents/collections and renders collection cards/list with counts/status.",
    edges: "No collections, stale status, failed load, large number of collections.",
    validation: "Counts match backend serialization; errors show retry path.",
    dependencies: "KnowledgeBaseComponent, /documents/collections, knowledge_collections service.",
    assumptions: "Andritz collection set may be large due SFTP ingestion.",
    notes: "Use read-only validation first.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-base.component.ts", "backend/app/api/v1/endpoints/documents.py", "backend/app/services/knowledge_collections.py"),
    scope: "Collections",
    tests: [
      { type: "Happy path", scenario: "Load collections", steps: "Open /knowledge.", expected: "Collections load with status/counts." },
      { type: "Performance", scenario: "Large collection list", steps: "Open workspace with many collections.", expected: "Page remains responsive." },
      { type: "Error path", scenario: "Collections API fails", steps: "Simulate 500.", expected: "Error state visible; no stale destructive action." },
      { type: "Regression", scenario: "Mocked Andritz browser collection smoke", steps: "Run local Playwright with mocked /documents/collections and open /knowledge.", expected: "The Knowledge collections page renders the mocked Andritz collection without contacting real backend data." },
      { type: "Responsive", scenario: "Open collections on mobile width", steps: "Set viewport to mobile width and open /knowledge with mocked Andritz APIs.", expected: "The Knowledge collections page remains reachable and shows the workspace collection without real backend data." },
      { type: "Permission/security", scenario: "Open collections unauthenticated", preconditions: "No auth token.", steps: "Navigate directly to /knowledge.", expected: "Route redirects to sign-in with redirectURL preserved before collection metadata is exposed.", severityIfFails: "High" },
    ],
  },
  {
    id: "COL-002",
    name: "Create collection",
    story: "As an authorized user, I can create a named collection for documents.",
    expected: "KnowledgeBaseComponent posts /documents/collections; backend slugifies/uniquifies name.",
    edges: "Duplicate name, invalid/blank name, permission denied.",
    validation: "Slug uniqueness; created collection appears in list; no duplicate unintended collection.",
    dependencies: "create_collection, create_or_get_collection.",
    assumptions: "Andritz collection creation is restricted to admins/operators.",
    notes: "Test with synthetic collection only.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-base.component.ts", "backend/app/services/knowledge_collections.py"),
    scope: "Collections",
    tests: [
      { type: "Happy path", scenario: "Create synthetic collection", steps: "Create QA collection.", expected: "Collection appears with unique slug." },
      { type: "Invalid input", scenario: "Blank name", steps: "Submit blank collection name.", expected: "Blocked/rejected." },
      { type: "Permission/security", scenario: "Unauthorized create", steps: "Try as read-only user.", expected: "Denied.", severityIfFails: "High" },
    ],
  },
  {
    id: "COL-003",
    name: "Upload documents to collection",
    story: "As an authorized user, I can upload files into a collection and trigger ingestion jobs.",
    expected: "Upload posts /documents/upload or collection documents endpoint, stores originals, creates worker job, updates collection status.",
    edges: "Unsupported extension, duplicate filename, large file, worker down, batch upload partial failure.",
    validation: "Status changes queued/running/completed/failed; source inventory records normalized source rows.",
    dependencies: "KnowledgeBaseComponent uploadFiles, documents upload endpoints, worker ingest.",
    assumptions: "Use synthetic files, not real SFTP data, for destructive/upload tests.",
    notes: "High data-integrity area.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-base.component.ts", "backend/app/api/v1/endpoints/documents.py", "backend/app/services/worker_ingest.py", "backend/app/services/knowledge_collections.py"),
    scope: "Collections",
    tests: [
      { type: "Happy path", scenario: "Upload small PDF", steps: "Upload synthetic PDF to QA collection.", expected: "Job completes and document appears in inventory." },
      { type: "Error path", scenario: "Worker unavailable", steps: "Simulate worker failure.", expected: "Job failure is visible; original is not lost." },
      { type: "Boundary", scenario: "Duplicate filename", steps: "Upload same file twice.", expected: "Collision behavior is deterministic and inventory remains coherent." },
    ],
  },
  {
    id: "COL-004",
    name: "Delete collection or document",
    story: "As an admin, I can delete synthetic collections/documents with explicit confirmation and without affecting unrelated data.",
    expected: "UI asks confirmation; backend delete endpoints remove scoped collection/document.",
    edges: "Deleting real Andritz/SFTP collection, in-flight job, missing collection, permission denied.",
    validation: "Never execute on real Andritz data without explicit approval; confirmation required; deletion is workspace-scoped.",
    dependencies: "KnowledgeBaseComponent confirmDelete, /documents/{id}, /documents/collections/{name}.",
    assumptions: "Destructive tests use QA synthetic data only.",
    notes: "Safety-critical; not executed in discovery.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-base.component.ts", "backend/app/api/v1/endpoints/documents.py"),
    scope: "Collections",
    tests: [
      { type: "Destructive safety", scenario: "Delete synthetic document", steps: "Use QA document, confirm delete.", expected: "Only target synthetic doc removed." },
      { type: "Permission/security", scenario: "Unauthorized delete", steps: "Attempt delete as non-admin.", expected: "Denied.", severityIfFails: "Critical" },
      { type: "Boundary", scenario: "Delete collection with running job", steps: "Attempt delete while ingestion running.", expected: "Blocked or handled without orphaned data.", severityIfFails: "High" },
      { type: "Destructive safety", scenario: "Delete synthetic collection requires typed confirmation", steps: "Open QA collection delete flow, type the exact collection name, confirm delete.", expected: "No delete is sent before exact typed confirmation; only the target synthetic collection is removed." },
      { type: "Permission/security", scenario: "Collection delete forbidden", steps: "Attempt confirmed collection delete when backend returns 403.", expected: "Error is visible and the collection remains listed.", severityIfFails: "High" },
      { type: "Permission/security", scenario: "Document delete forbidden", steps: "Attempt confirmed document delete when backend returns 403.", expected: "Error is visible and the document remains listed.", severityIfFails: "High" },
    ],
  },
  {
    id: "COL-005",
    name: "Collection inventory browse/filter/sort",
    story: "As a user, I can browse a collection's source inventory with pagination, filters, and sort.",
    expected: "Collection view calls /documents/collections/{id}/inventory with q, source_kind, extension, status, sort and offset.",
    edges: "Large Andritz inventory, empty page, invalid filters, sort direction toggles.",
    validation: "Pagination counts and filters align with backend; no client memory blow-up.",
    dependencies: "KnowledgeViewComponent, collection_inventory service.",
    assumptions: "Andritz SPL collections may contain many archived source rows.",
    notes: "Read-only validation safe.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-view.component.ts", "backend/app/api/v1/endpoints/documents.py", "backend/app/services/knowledge_collections.py"),
    scope: "Collections",
    tests: [
      { type: "Happy path", scenario: "Browse inventory", steps: "Open large collection and paginate.", expected: "Rows and totals update correctly." },
      { type: "Boundary/performance", scenario: "Search/filter large inventory", steps: "Apply query and extension/status filters.", expected: "Response time acceptable and UI responsive." },
      { type: "Invalid input", scenario: "Invalid offset/filter", steps: "Call endpoint with invalid params.", expected: "Backend normalizes or rejects safely." },
    ],
  },
  {
    id: "COL-006",
    name: "Collection diagnostics",
    story: "As an operator, I can inspect collection diagnostics including kinds, extensions, document facts, and top sources.",
    expected: "Diagnostics endpoint feeds cards/tabs for status, fact counts, source distribution, and provider metadata.",
    edges: "No diagnostics, stale manifest, failed document facts, mixed source kinds.",
    validation: "Diagnostic counts are read-only and do not trigger ingestion by accident.",
    dependencies: "KnowledgeViewComponent loadDiagnostics, /collections/{id}/diagnostics.",
    assumptions: "Diagnostics can be run safely on Andritz read-only.",
    notes: "Useful for SFTP collection health.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-view.component.ts", "backend/app/api/v1/endpoints/documents.py"),
    scope: "Collections",
    tests: [
      { type: "Happy path", scenario: "Open diagnostics tab", steps: "Open collection detail diagnostics.", expected: "Metrics cards populate." },
      { type: "Error path", scenario: "Diagnostics API fails", steps: "Simulate failure.", expected: "UI reports error without hiding existing inventory." },
      { type: "Boundary", scenario: "Collection with no sources", steps: "Open empty synthetic collection.", expected: "Zeros/empty state render correctly." },
    ],
  },
  {
    id: "COL-007",
    name: "Document rich/raw/converted preview",
    story: "As a user, I can preview indexed documents and inspect raw or converted forms where available.",
    expected: "Endpoints serve metadata, preview, file, rich-preview, raw, converted-preview and chunks by document id/collection.",
    edges: "Unsupported file, missing object, image/PDF differences, page parameter, HTML sanitization, permission denied.",
    validation: "Preview respects permissions and content type; no unsafe HTML execution; download names are safe.",
    dependencies: "DocumentPreviewComponent, documents endpoints, object store.",
    assumptions: "Object store paths are valid for Andritz indexed docs.",
    notes: "Cross-used by chat, capture report, collection browser.",
    source: src("backend/app/api/v1/endpoints/documents.py", "frontend-ng/src/app/shared/document-preview/document-preview.component.ts"),
    scope: "Collections, Chat Recherche, Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Preview PDF", steps: "Open a PDF source from collection.", expected: "Preview renders with correct content type." },
      { type: "Error path", scenario: "Missing converted preview", steps: "Open doc lacking conversion.", expected: "Fallback raw/download path works." },
      { type: "Security", scenario: "HTML preview sanitization", steps: "Preview document with script-like content.", expected: "No script execution.", severityIfFails: "Critical" },
      { type: "Permission/security", scenario: "Forbidden collection preview", steps: "Open a collection document preview with preview permission denied.", expected: "Permission error renders without stale content or download link.", severityIfFails: "High" },
    ],
  },
  {
    id: "COL-008",
    name: "Search inside collection",
    story: "As a user, I can search within a specific collection from the knowledge UI.",
    expected: "Search modal calls /documents/search or RAG endpoints scoped to collection and displays matching chunks/sources.",
    edges: "Empty query, no results, large query, collection missing, search API failure.",
    validation: "Search is scoped to selected collection; no cross-collection leak; failed search is not confused with no results or stale results.",
    dependencies: "KnowledgeBaseComponent runSearch, documents search endpoint/vector store.",
    assumptions: "Collection has vector/sparse indexes built.",
    notes: "Read-only, safe for Andritz.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-base.component.ts", "backend/app/api/v1/endpoints/documents.py"),
    scope: "Collections",
    tests: [
      { type: "Happy path", scenario: "Search known term", steps: "Search term expected in collection.", expected: "Relevant chunks returned with source info." },
      { type: "Boundary", scenario: "No results", steps: "Search nonsense term.", expected: "Empty state, not error." },
      { type: "Permission/security", scenario: "Cross-collection isolation", steps: "Search collection as limited user.", expected: "Only permitted collection results appear.", severityIfFails: "High" },
      { type: "Error path", scenario: "Search API fails", steps: "Force /documents/search to return 500 from the Knowledge search drawer.", expected: "Inline error state is visible and no stale results are displayed.", severityIfFails: "High" },
      { type: "Regression", scenario: "Open a new search context after previous results", steps: "Run a successful search, close the drawer, then open Search in this collection.", expected: "The new drawer context starts with an empty query and no stale result/error state.", severityIfFails: "High" },
    ],
  },
  {
    id: "COL-009",
    name: "Table facts explorer",
    story: "As a user, I can inspect structured spreadsheet/table facts extracted from collection documents.",
    expected: "Knowledge view calls /documents/table-facts with collection, sheet/query filters, pagination and warnings.",
    edges: "No table facts, malformed cell references, many sheets, warnings.",
    validation: "Pagination/filter values are stable; warnings visible; fact source links are traceable.",
    dependencies: "KnowledgeViewComponent loadTableFacts, documents table-facts endpoint.",
    assumptions: "Andritz spreadsheets are parsed into table facts where supported.",
    notes: "Important for industrial documents and SPL lists.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-view.component.ts", "backend/app/api/v1/endpoints/documents.py"),
    scope: "Collections",
    tests: [
      { type: "Happy path", scenario: "Load table facts", steps: "Open facts tab for collection with spreadsheets.", expected: "Rows show sheet/cell/value/source metadata." },
      { type: "Boundary", scenario: "Filter by sheet/query", steps: "Apply query and sheet filter.", expected: "Facts list updates without stale rows." },
      { type: "Error path", scenario: "No facts", steps: "Open collection without table facts.", expected: "Empty state, no exception." },
    ],
  },
  {
    id: "COL-010",
    name: "Document and OCR facts explorer",
    story: "As a user, I can inspect document facts and OCR/visual facts extracted from documents and images.",
    expected: "Knowledge view calls /documents/document-facts and typed OCR filters, dedupes OCR facts, and shows confidence/box metadata.",
    edges: "No OCR provider, duplicate OCR lines, low confidence, image page references.",
    validation: "Facts are traceable to document/page/image; low confidence warnings are visible.",
    dependencies: "KnowledgeViewComponent, document_intelligence/ocr services, documents fact endpoints.",
    assumptions: "OCR may be optional depending deployment configuration.",
    notes: "Supports image/photo capture use cases.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-view.component.ts", "backend/app/api/v1/endpoints/documents.py", "backend/app/services/document_intelligence.py", "backend/app/services/ocr.py"),
    scope: "Collections",
    tests: [
      { type: "Happy path", scenario: "Load document facts", steps: "Open facts tab and document fact filter.", expected: "Facts show semantic type and document references." },
      { type: "Boundary", scenario: "OCR duplicate facts", steps: "Open OCR-rich image document.", expected: "Duplicates are deduped in UI." },
      { type: "Error path", scenario: "OCR unavailable", steps: "Open collection without OCR artifacts.", expected: "Graceful empty state." },
    ],
  },
  {
    id: "COL-011",
    name: "Knowledge guides",
    story: "As an operator, I can create and publish interpretation guides for a collection or scope.",
    expected: "Knowledge guides endpoints list/effective/create/patch guides; collection editor loads and saves draft/published markdown.",
    edges: "No current guide, invalid markdown, draft vs published, scope conflict.",
    validation: "Effective guide resolution is deterministic; publishing updates current guide without losing draft history.",
    dependencies: "KnowledgeViewComponent guide editor, /knowledge/guides endpoints, knowledge_guides service.",
    assumptions: "Guide editing is restricted to authorized roles.",
    notes: "Guides influence answer/capture interpretation, so regression matters.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-view.component.ts", "backend/app/api/v1/endpoints/knowledge.py", "backend/app/services/knowledge_guides.py"),
    scope: "Collections, Chat Recherche",
    tests: [
      { type: "Happy path", scenario: "Save draft guide", steps: "Edit guide and save draft.", expected: "Draft appears and current published guide unchanged." },
      { type: "Happy path", scenario: "Publish guide", steps: "Publish guide.", expected: "Effective guide updates." },
      { type: "Permission/security", scenario: "Unauthorized guide edit", steps: "Try edit as read-only.", expected: "Denied.", severityIfFails: "High" },
    ],
  },
  {
    id: "COL-012",
    name: "Retrieval artifact jobs",
    story: "As an operator, I can launch retrieval artifact rebuilds for a collection.",
    expected: "Collection detail posts retrieval-artifact-jobs with kind summary_index_rebuild, sparse_index_rebuild, or qdrant_sparse_reindex and polls job status.",
    edges: "Job already running, worker unavailable, invalid kind, long-running reindex.",
    validation: "Job status/progress is visible; repeated launches do not corrupt collection indexes.",
    dependencies: "KnowledgeViewComponent, /collections/{id}/retrieval-artifact-jobs, WorkerJob.",
    assumptions: "Only operators/admins can launch heavy jobs.",
    notes: "High performance impact; schedule carefully.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-view.component.ts", "backend/app/api/v1/endpoints/documents.py", "backend/app/services/worker_offline_retrieval_artifacts.py"),
    scope: "Collections, Chat Recherche",
    tests: [
      { type: "Happy path", scenario: "Launch summary rebuild on synthetic collection", steps: "Start job and poll.", expected: "Job completes and status updates." },
      { type: "Invalid input", scenario: "Invalid job kind", steps: "POST unsupported kind.", expected: "Backend rejects." },
      { type: "Performance", scenario: "Large Andritz reindex read-only dry assessment", steps: "Do not launch; inspect queue/load first.", expected: "Risk noted before execution.", severityIfFails: "High" },
    ],
  },
  {
    id: "COL-013",
    name: "Document and table query APIs",
    story: "As chat/capture systems, I can query document/table facts directly for grounded answers.",
    expected: "/knowledge/document-query and /knowledge/table-query route requests to document/table intelligence services with collection scope.",
    edges: "Missing collection_or_scope, ambiguous query, no facts, malformed filters.",
    validation: "Query is scoped; response contains traceable fact ids/sources.",
    dependencies: "ApiService documentQuery/tableQuery, knowledge endpoint, table/document intelligence.",
    assumptions: "Used by advanced UX or backend chains even if not directly exposed.",
    notes: "Include because it affects Recherche and capture grounding.",
    source: src("frontend-ng/src/app/core/api.service.ts", "backend/app/api/v1/endpoints/knowledge.py", "backend/app/services/table_intelligence.py", "backend/app/services/document_intelligence.py"),
    scope: "Collections, Chat Recherche, Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Document query in scope", steps: "Call document-query for known collection.", expected: "Relevant fact payload with sources." },
      { type: "Boundary", scenario: "No fact match", steps: "Query absent term.", expected: "Empty/low confidence response, not hallucinated fact." },
      { type: "Permission/security", scenario: "Query hidden scope", steps: "Attempt inaccessible collection.", expected: "Denied or omitted.", severityIfFails: "High" },
    ],
  },
  {
    id: "COL-014",
    name: "Collection stats, chunks, and embedding graph",
    story: "As an operator, I can inspect chunks, stats, and embedding graph for a collection.",
    expected: "Knowledge view calls /documents/chunks, /stats, /graph and renders chunk lists/embedding map where available.",
    edges: "No graph, huge chunk list, document filter, vector store unavailable.",
    validation: "Chunk pagination filters by collection/document; stats do not leak other collections.",
    dependencies: "KnowledgeViewComponent, EmbeddingMapComponent, documents endpoints.",
    assumptions: "Embedding graph may be optional/expensive.",
    notes: "Read-only diagnostics useful for QA.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-view.component.ts", "frontend-ng/src/app/features/knowledge/embedding-map.component.ts", "backend/app/api/v1/endpoints/documents.py"),
    scope: "Collections",
    tests: [
      { type: "Happy path", scenario: "Load chunks and stats", steps: "Open collection detail.", expected: "Stats and first chunk page load." },
      { type: "Boundary", scenario: "Filter chunks by document", steps: "Select document filter.", expected: "Only selected document chunks show." },
      { type: "Error path", scenario: "Graph unavailable", steps: "Open graph when vector data missing.", expected: "Graceful empty/error state." },
    ],
  },
  {
    id: "COL-015",
    name: "Worker job monitoring",
    story: "As an operator, I can monitor ingestion/retrieval jobs and job events.",
    expected: "Workspace jobs endpoints list/create/get/transition/events; collection and SFTP UIs poll job status.",
    edges: "Queued forever, failed job, transition unauthorized, events missing.",
    validation: "Jobs are workspace-scoped; polling intervals do not overload backend.",
    dependencies: "/workspace-jobs, /documents/jobs, worker_dispatch, Celery worker.",
    assumptions: "Workers are running on VM.",
    notes: "Needed before executing ingestion-heavy tests.",
    source: src("backend/app/api/v1/endpoints/workspace_jobs.py", "backend/app/services/workspace_jobs.py", "frontend-ng/src/app/features/connectors/sftp/sftp-connector.component.ts", "frontend-ng/src/app/features/knowledge/knowledge-view.component.ts"),
    scope: "Collections, SFTP Andritz",
    tests: [
      { type: "Happy path", scenario: "Poll job", steps: "Start synthetic ingestion job and poll.", expected: "Status/events progress to terminal state." },
      { type: "Error path", scenario: "Failed job details", steps: "Inspect failed job.", expected: "Error payload explains failure." },
      { type: "Permission/security", scenario: "Transition job unauthorized", steps: "Attempt transition as member.", expected: "Denied.", severityIfFails: "High" },
    ],
  },

  {
    id: "SFTP-001",
    name: "Secure deposit link management",
    story: "As an operator, I can create, list, update, rotate, and revoke secure deposit links for external/SFTP uploads.",
    expected: "SFTP connector calls /sftp/links endpoints; backend serializes link and can reveal generated password only when appropriate.",
    edges: "Duplicate label, expired link, revoked link, rotate password, permission denied.",
    validation: "Passwords are not leaked after creation/rotation; revoked links cannot authenticate.",
    dependencies: "SftpConnectorComponent, secure_deposit endpoints/service.",
    assumptions: "Andritz secure deposit is enabled for workspace.",
    notes: "Credential handling is security-critical.",
    source: src("frontend-ng/src/app/features/connectors/sftp/sftp-connector.component.ts", "backend/app/api/v1/endpoints/secure_deposit.py", "backend/app/services/secure_deposit.py"),
    scope: "SFTP Andritz",
    tests: [
      { type: "Happy path", scenario: "Create synthetic deposit link", steps: "Create link with QA label.", expected: "Link appears; password reveal limited to creation response." },
      { type: "Security", scenario: "Rotate/revoke link", steps: "Rotate then revoke.", expected: "Old credentials fail; revoked link unusable.", severityIfFails: "Critical" },
      { type: "Permission/security", scenario: "Member manages links", steps: "Attempt create/revoke as non-operator.", expected: "Denied.", severityIfFails: "High" },
      { type: "Regression", scenario: "Browser link lifecycle stays explicit", steps: "Create a synthetic link, hide the one-time secret, rotate the stored link, then revoke it.", expected: "Only explicit link mutations are sent, stored-list passwords remain hidden, and no staged file promotion/reconciliation occurs." },
    ],
  },
  {
    id: "SFTP-002",
    name: "Public deposit session authentication",
    story: "As an external depositor, I can unlock a deposit portal with access id/password and receive a scoped session token.",
    expected: "Public portal posts /deposit-links/{access_id}/session; backend verifies password/hash/link usability and issues token.",
    edges: "Wrong password, revoked/expired link, workspace disabled, missing session header.",
    validation: "Bad auth returns clear failure; session token is scoped to access id; no workspace data exposed.",
    dependencies: "DepositPortalComponent, public deposit endpoints, session token secret.",
    assumptions: "External portal is intentionally public but scoped.",
    notes: "Security and usability both critical.",
    source: src("frontend-ng/src/app/features/deposit/deposit-portal.component.ts", "backend/app/api/v1/endpoints/secure_deposit.py", "backend/app/services/secure_deposit.py"),
    scope: "SFTP Andritz",
    tests: [
      { type: "Happy path", scenario: "Unlock public portal", steps: "Use valid QA link/password.", expected: "Portal unlocks and lists files for that link." },
      { type: "Invalid input", scenario: "Wrong password", steps: "Submit wrong password.", expected: "Denied without revealing link details." },
      { type: "Security", scenario: "Use token for another access id", steps: "Replay token against different link.", expected: "Rejected.", severityIfFails: "Critical" },
    ],
  },
  {
    id: "SFTP-003",
    name: "Public deposit file upload",
    story: "As an external depositor, I can upload allowed files through the public portal.",
    expected: "Portal POSTs files with deposit session header; backend enforces allowed extensions/max size and records DepositFile.",
    edges: "Large file, unsupported extension, duplicate filename, interrupted upload.",
    validation: "Rejected files do not create promoted records; accepted files show in file list with status.",
    dependencies: "DepositPortalComponent, receive_file, object/local staged storage.",
    assumptions: "Use synthetic QA link/files only.",
    notes: "Never use real Andritz files for destructive failure tests unless approved.",
    source: src("frontend-ng/src/app/features/deposit/deposit-portal.component.ts", "backend/app/services/secure_deposit.py"),
    scope: "SFTP Andritz",
    tests: [
      { type: "Happy path", scenario: "Upload small supported file", steps: "Upload synthetic PDF/XLSX.", expected: "File appears as received/staged." },
      { type: "Boundary", scenario: "Max size exceeded", steps: "Upload over max size.", expected: "Rejected and audited without partial usable file." },
      { type: "Invalid input", scenario: "Unsupported extension", steps: "Upload unsupported file.", expected: "Rejected with clear message." },
    ],
  },
  {
    id: "SFTP-004",
    name: "SFTP upload server write-only flow",
    story: "As an external sender, I can upload files by SFTP while being prevented from reading/deleting server data.",
    expected: "AsyncSSH SFTP server authenticates access id/password, exposes upload-only behavior, writes temp sidecar, records staged file on close.",
    edges: "Auth failure, workspace disabled, invalid filename, oversize upload, read/list/delete attempts.",
    validation: "Read/delete operations are denied; sidecar cleaned; failed uploads audited; completed upload becomes DepositFile.",
    dependencies: "secure_deposit_sftp.py, secure_deposit_operations sidecars, object/local staged storage.",
    assumptions: "SFTP process is deployed and reachable for Andritz.",
    notes: "Very high data safety area; test with disposable QA link only.",
    source: src("backend/app/services/secure_deposit_sftp.py", "backend/app/services/secure_deposit.py", "backend/app/services/secure_deposit_operations.py"),
    scope: "SFTP Andritz",
    tests: [
      { type: "Happy path", scenario: "SFTP upload synthetic file", steps: "Connect with QA link, put file.", expected: "Upload completes and appears in deposit queue." },
      { type: "Security", scenario: "Attempt SFTP read/delete", steps: "ls/read/remove paths.", expected: "Denied consistently.", severityIfFails: "Critical" },
      { type: "Boundary", scenario: "Interrupted upload", steps: "Disconnect mid-upload.", expected: "Temp sidecar cleaned or marked; no corrupt promoted data." },
    ],
  },
  {
    id: "SFTP-005",
    name: "Deposit queue folders, search, pagination, status filters",
    story: "As an operator, I can inspect staged deposit files through folder navigation, search, status filters, and pagination.",
    expected: "SFTP connector loads /sftp/deposits and builds queue items/folder tree client-side.",
    edges: "Thousands of files, folder names, archive paths, stale filters, selected link filter.",
    validation: "Filtering is read-only; current folder/search scope is clear; counts remain coherent.",
    dependencies: "SftpConnectorComponent, /sftp/deposits, DepositFile serialization.",
    assumptions: "Andritz queue may be large and contains real data; avoid mutations.",
    notes: "Safe read-only validation candidate.",
    source: src("frontend-ng/src/app/features/connectors/sftp/sftp-connector.component.ts", "backend/app/api/v1/endpoints/secure_deposit.py"),
    scope: "SFTP Andritz",
    tests: [
      { type: "Happy path", scenario: "Browse deposit queue", steps: "Open SFTP connector and navigate folders.", expected: "Files/folders display and filters work." },
      { type: "Performance", scenario: "Large queue pagination", steps: "Change page size/search in large queue.", expected: "UI remains responsive." },
      { type: "Boundary", scenario: "No files for filter", steps: "Select empty status/search.", expected: "Empty state without losing previous data." },
      { type: "Regression", scenario: "Deposit link filter scopes queue", steps: "Open SFTP connector with multiple synthetic deposit links, select a secondary link, then search for a no-match string.", expected: "Queue state remains scoped to the selected link, empty search displays safely, and no promote/archive mutation is sent." },
    ],
  },
  {
    id: "SFTP-006",
    name: "Deposit file preview and archive browsing",
    story: "As an operator, I can preview staged files and inspect ZIP archive members before promoting.",
    expected: "Preview endpoints support text/spreadsheet/docx/image/pdf where possible; ZIP browser lists folders/members and previews/downloads members.",
    edges: "Huge archive, unsupported member, path traversal attempt, preview requiring bytes, corrupted ZIP.",
    validation: "Archive member paths are sanitized; preview failures do not alter file status; download uses safe filename.",
    dependencies: "SftpConnectorComponent preview methods, secure_deposit archive preview helpers.",
    assumptions: "Andritz ZIP archives may be large; preview should be bounded.",
    notes: "Critical before promote decisions.",
    source: src("frontend-ng/src/app/features/connectors/sftp/sftp-connector.component.ts", "backend/app/services/secure_deposit.py"),
    scope: "SFTP Andritz",
    tests: [
      { type: "Happy path", scenario: "Preview staged file", steps: "Open preview for small PDF/image.", expected: "Preview renders and can close." },
      { type: "Happy path", scenario: "Browse ZIP archive", steps: "Open archive, navigate folder, preview member.", expected: "Member list and preview are correct." },
      { type: "Security", scenario: "Path traversal member request", steps: "Call member preview with ../ path.", expected: "Rejected.", severityIfFails: "Critical" },
      { type: "Regression", scenario: "Browser preview stays read-only", steps: "Open SFTP connector with synthetic file and ZIP, preview the file and a ZIP member.", expected: "Drawer renders both previews and sends no download/promote/archive-bulk request." },
    ],
  },
  {
    id: "SFTP-007",
    name: "Deposit indexing assist",
    story: "As an operator, I get recommendations for how received files should be indexed or promoted.",
    expected: "SFTP connector posts /sftp/deposits/indexing-assist; backend recommends target collection/status using filename/archive analysis.",
    edges: "Unknown file family, archive with no supported docs, duplicate promoted file, stale collection snapshot.",
    validation: "Recommendations are advisory; they never promote automatically.",
    dependencies: "build_indexing_assist_snapshot, _recommend_received_file, collection snapshot.",
    assumptions: "Andritz naming conventions are encoded in assist rules.",
    notes: "Read-only except if operator follows promote action.",
    source: src("frontend-ng/src/app/features/connectors/sftp/sftp-connector.component.ts", "backend/app/services/secure_deposit.py"),
    scope: "SFTP Andritz",
    tests: [
      { type: "Happy path", scenario: "Run indexing assist", steps: "Open SFTP connector and analyze current view.", expected: "Recommendations appear with target collection." },
      { type: "Boundary", scenario: "Unknown file", steps: "Use synthetic unknown filename.", expected: "Recommendation is safe/needs review, not auto-promote." },
      { type: "Regression", scenario: "No automatic promote", steps: "Run assist on received files.", expected: "No DepositFile status changes to promoted.", severityIfFails: "Critical" },
    ],
  },
  {
    id: "SFTP-008",
    name: "Promote single deposit file to collection",
    story: "As an operator, I can promote a staged deposit file into a chosen knowledge collection.",
    expected: "POST /sftp/deposits/{file_id}/promote creates/uses target collection, copies/expands file, creates worker job, updates status.",
    edges: "Already promoted, target collection missing, archive expansion, worker dispatch failure, duplicate document.",
    validation: "Promotion is explicit; source file status and collection manifest remain consistent; failures are recoverable.",
    dependencies: "promote_file_to_collection, _promote_archive_file_to_collection, worker_dispatch.",
    assumptions: "Use synthetic file for mutation tests; do not promote real queue items unless instructed.",
    notes: "High data-integrity risk.",
    source: src("frontend-ng/src/app/features/connectors/sftp/sftp-connector.component.ts", "backend/app/api/v1/endpoints/secure_deposit.py", "backend/app/services/secure_deposit.py"),
    scope: "SFTP Andritz, Collections",
    tests: [
      { type: "Happy path", scenario: "Promote synthetic file", steps: "Promote QA file to QA collection.", expected: "Status becomes promoted and job starts/completes." },
      { type: "Boundary", scenario: "Promote already promoted file", steps: "Promote same file again.", expected: "Idempotent or rejected without duplicate data." },
      { type: "Error path", scenario: "Worker dispatch fails", steps: "Simulate dispatch failure.", expected: "Status/error clearly recorded; staged file not lost.", severityIfFails: "High" },
    ],
  },
  {
    id: "SFTP-009",
    name: "Bulk promote deposit files",
    story: "As an operator, I can promote multiple selected deposit files into a target collection.",
    expected: "POST /sftp/deposits/promote-bulk validates file ids, promotes batch, creates jobs/manifest entries.",
    edges: "Mixed missing ids, mixed statuses, large selection, partial failures, archive batches.",
    validation: "Missing ids return 404 detail; no silent partial corruption; bulk action requires explicit selection.",
    dependencies: "SftpConnectorComponent promoteBatch, promote_files_to_collection_batch.",
    assumptions: "Bulk mutation should be tested only with synthetic deposits.",
    notes: "Especially dangerous for real Andritz queue; do not run blindly.",
    source: src("frontend-ng/src/app/features/connectors/sftp/sftp-connector.component.ts", "backend/app/api/v1/endpoints/secure_deposit.py", "backend/app/services/secure_deposit.py"),
    scope: "SFTP Andritz, Collections",
    tests: [
      { type: "Happy path", scenario: "Bulk promote synthetic files", steps: "Select QA files and promote to QA collection.", expected: "All selected files promoted; job/result summary correct." },
      { type: "Error path", scenario: "One missing id", steps: "Include stale id in request.", expected: "404 details missing ids; no unintended promotion.", severityIfFails: "High" },
      { type: "Boundary/performance", scenario: "Large selection", steps: "Select many synthetic files.", expected: "UI/backend handle batch without timeout or duplicate jobs." },
    ],
  },
  {
    id: "SFTP-010",
    name: "SFTP operations monitor and reconciliation",
    story: "As an operator, I can view live SFTP operations and run reconciliation checks for sidecars/uploads.",
    expected: "Operations endpoint returns health/snapshot; reconcile endpoint inspects temp/sidecar state and can identify stale uploads.",
    edges: "Stale sidecars, active upload, worker process down, quarantine dry run.",
    validation: "Reconcile is explicit and permission-guarded; dry-run/quarantine behavior does not delete good data.",
    dependencies: "SftpConnectorComponent loadOperations/runReconciliationCheck, secure_deposit_operations.",
    assumptions: "VM has SFTP sidecar directory access.",
    notes: "Read-only operations snapshot safe; reconcile/quarantine needs caution.",
    source: src("frontend-ng/src/app/features/connectors/sftp/sftp-connector.component.ts", "backend/app/api/v1/endpoints/secure_deposit.py", "backend/app/services/secure_deposit_operations.py"),
    scope: "SFTP Andritz",
    tests: [
      { type: "Happy path", scenario: "Load operations snapshot", steps: "Open connector operations panel.", expected: "Health/live upload snapshot visible." },
      { type: "Permission/security", scenario: "Run reconcile unauthorized", steps: "Attempt as non-operator.", expected: "Denied.", severityIfFails: "High" },
      { type: "Destructive safety", scenario: "Quarantine from dry run", steps: "Review dry run before quarantine.", expected: "No mutation without explicit operator action.", severityIfFails: "Critical" },
      { type: "Regression", scenario: "Cancel quarantine confirmation", steps: "Click Move to quarantine, then dismiss the browser confirmation.", expected: "No quarantine request is sent and the SFTP operations controls remain usable.", severityIfFails: "Critical" },
      { type: "Error path", scenario: "Operations monitor unavailable", steps: "Force /sftp/operations to fail and refresh the monitor.", expected: "A visible non-blocking error appears, loading stops, and no reconcile/quarantine/promote/download mutation is sent.", severityIfFails: "High" },
      { type: "Regression", scenario: "Run reconciliation dry-run", steps: "Click Run check against a synthetic operations snapshot.", expected: "Only mode=dry_run is sent, operations refreshes, and no quarantine/promote/download mutation occurs.", severityIfFails: "High" },
    ],
  },
  {
    id: "SFTP-011",
    name: "Deposit downloads and archives",
    story: "As an authorized operator, I can download staged files, ZIP members, or an archive of selected deposit files.",
    expected: "Download endpoints stream files/archive with audit events and safe names.",
    edges: "Missing file, huge archive, unauthorized download, zip member not found.",
    validation: "Download requires permission; audit event recorded; no path traversal.",
    dependencies: "SftpConnectorComponent download methods, build_deposit_archive, extract_deposit_zip_member_to_temp.",
    assumptions: "Downloads are allowed for reviewer/operator roles only.",
    notes: "Read-only but can leak data if permissions wrong.",
    source: src("frontend-ng/src/app/features/connectors/sftp/sftp-connector.component.ts", "backend/app/api/v1/endpoints/secure_deposit.py", "backend/app/services/secure_deposit.py"),
    scope: "SFTP Andritz",
    tests: [
      { type: "Happy path", scenario: "Download synthetic file", steps: "Download QA staged file.", expected: "Correct file contents/name and audit event." },
      { type: "Permission/security", scenario: "Unauthorized download", steps: "Attempt as unauthorized user.", expected: "Denied.", severityIfFails: "Critical" },
      { type: "Boundary", scenario: "Huge archive download", steps: "Request large archive in safe environment.", expected: "Streaming works or bounded error appears." },
      { type: "Error path", scenario: "Recoverable file download failure", steps: "Click Download file for a synthetic received file while the download endpoint fails.", expected: "A visible error appears, the download button recovers, and no promote/reconcile/archive mutation is sent.", severityIfFails: "High" },
      { type: "Error path", scenario: "Recoverable staging ZIP failure", steps: "Click Download ZIP for the synthetic received queue while the archive endpoint fails.", expected: "A visible error appears, the ZIP button recovers, and no promote/reconcile/file-download mutation is sent.", severityIfFails: "High" },
    ],
  },
  {
    id: "SFTP-012",
    name: "Andritz SPL wave import planning and execution",
    story: "As an operator, I can plan controlled SPL archive ingestion waves with ledger resume and size/file-count safeguards.",
    expected: "spl_wave_importer builds wave plans by project/folder/size, records ledger in workspace settings, and executes promotion jobs.",
    edges: "Archive too large, too many supported documents, already promoted, missing deposit, ledger resume, allow_repromote.",
    validation: "Plan phase is read-only; execution respects limits and ledger; no duplicate or skipped archive without reason.",
    dependencies: "spl_wave_importer.py, secure_deposit archive readers, worker_dispatch, workspace settings ledger.",
    assumptions: "This is Andritz-specific business process; execute only with explicit instruction.",
    notes: "Very high impact on Andritz collection state; discovery only.",
    source: src("backend/app/services/spl_wave_importer.py", "backend/app/services/secure_deposit.py", "backend/app/services/knowledge_collections.py"),
    scope: "SFTP Andritz, Collections",
    tests: [
      { type: "Happy path", scenario: "Build wave plan read-only", steps: "Run planning against known synthetic deposits.", expected: "Plan lists promotable/skipped archives with reasons." },
      { type: "Boundary", scenario: "Wave exceeds document limit", steps: "Plan archives above max docs.", expected: "Plan marks not promotable with limit reason." },
      { type: "Destructive safety", scenario: "Execute only with approval", steps: "Do not execute on real Andritz data without explicit command.", expected: "No collection state mutation during QA discovery.", severityIfFails: "Critical" },
    ],
  },
  {
    id: "SFTP-013",
    name: "Target collection selection for SFTP promote",
    story: "As an operator, I can choose or refresh the collection slug targeted by SFTP promotions.",
    expected: "SFTP connector loads knowledge collections, defaults target collection slug, and sends collection_slug to promote calls.",
    edges: "Collection deleted after selection, slug typo, empty collection list, default mismatch.",
    validation: "Selected target is explicit before promote; backend creates/uses intended collection only.",
    dependencies: "SftpConnectorComponent loadKnowledgeCollections/setCollectionSlug, secure_deposit target collection resolver.",
    assumptions: "Andritz has canonical target collections for SPL/import waves.",
    notes: "Wrong target collection is a severe business defect.",
    source: src("frontend-ng/src/app/features/connectors/sftp/sftp-connector.component.ts", "backend/app/services/secure_deposit.py"),
    scope: "SFTP Andritz, Collections",
    tests: [
      { type: "Happy path", scenario: "Select target collection", steps: "Choose QA target collection then promote QA file.", expected: "Documents land in selected collection." },
      { type: "Invalid input", scenario: "Invalid slug", steps: "Send invalid collection_slug.", expected: "Backend rejects or creates only per safe rules." },
      { type: "Regression", scenario: "Default target visible", steps: "Open connector.", expected: "Default target is explicit, not hidden.", severityIfFails: "High" },
      { type: "Regression", scenario: "Selected target drives assist without promote", steps: "Select an alternate synthetic collection and run indexing assist.", expected: "Assist payload carries selected collection_slug and no promote/download endpoint is called." },
    ],
  },
  {
    id: "SFTP-014",
    name: "Secure deposit workspace enablement and extension policy",
    story: "As an operator, I can rely on secure deposit being enabled only for intended workspaces and accepting only configured extensions.",
    expected: "secure_deposit checks enabled workspace slugs and default allowed extensions before link/session/upload behavior.",
    edges: "Workspace disabled, settings absent, custom extension list, case-insensitive extension.",
    validation: "Disabled workspace blocks public/SFTP auth; extension checks are consistent across portal and SFTP.",
    dependencies: "secure_deposit settings, workspace settings, SFTP auth.",
    assumptions: "Andritz slug is included in enabled secure deposit configuration.",
    notes: "Prevents accidental exposure in other workspaces.",
    source: src("backend/app/services/secure_deposit.py", "backend/app/services/secure_deposit_sftp.py"),
    scope: "SFTP Andritz",
    tests: [
      { type: "Happy path", scenario: "Enabled Andritz workspace", steps: "Check health/session for Andritz QA link.", expected: "Allowed when configured." },
      { type: "Security", scenario: "Disabled workspace auth", steps: "Use disabled workspace link.", expected: "Auth/session denied.", severityIfFails: "Critical" },
      { type: "Validation", scenario: "Extension case handling", steps: "Upload .PDF/.pdf synthetic files.", expected: "Policy applies consistently." },
    ],
  },
  {
    id: "CHT-016",
    name: "Non-streaming chat completion fallback",
    story: "As a user or client integration, I can receive a complete chat answer from the non-streaming completion endpoint when SSE streaming is unsuitable.",
    expected: "POST /chat/completion validates the request, resolves workspace/system context, runs RAG/generation, and returns a complete answer payload with sources/metadata where available.",
    edges: "Streaming disabled, empty prompt, model timeout, no retrieval results, malformed context id.",
    validation: "Completion response is scoped to the current workspace and has the same grounding/source policy expectations as streaming chat.",
    dependencies: "/api/v1/chat/completion, RAG service, model router, source policy.",
    assumptions: "Frontend primarily streams, but completion remains an API interaction to validate for integrations/fallbacks.",
    notes: "Discovered as a separate endpoint not explicitly represented in the first matrix.",
    source: src("backend/app/api/v1/endpoints/chat.py", "frontend-ng/src/app/features/chat/chat-panel.component.ts"),
    scope: "Chat Recherche",
    tests: [
      { type: "Happy path", scenario: "Request non-streaming answer", steps: "POST a normal grounded query to /chat/completion.", expected: "Complete answer and source metadata are returned." },
      { type: "Error path", scenario: "Completion model timeout", steps: "Simulate slow/failed model provider.", expected: "Endpoint returns a bounded error/fallback and does not create a stuck chat state.", severityIfFails: "High" },
      { type: "Permission/security", scenario: "Completion with inaccessible context", steps: "Use a context id outside user permissions.", expected: "Request is denied or context ignored without leaking data.", severityIfFails: "High" },
    ],
  },
  {
    id: "CHT-017",
    name: "Chat answer feedback and quality hooks",
    story: "As a user, I can provide feedback on answers so quality signals and correction workflows remain attached to the right chat run.",
    expected: "Chat panel logs feedback/audit metadata, links feedback to source run/decision ids where present, and keeps the original answer inspectable.",
    edges: "Feedback before run id is available, duplicate feedback, connection failure, feedback on deep-search-promoted answer.",
    validation: "Feedback never mutates the answer text; it remains workspace/user scoped and does not expose hidden sources.",
    dependencies: "ChatPanelComponent feedback logging, canonical/evaluation APIs, chat run ledger.",
    assumptions: "Feedback controls are enabled in the current Andritz UI profile.",
    notes: "Quality hook was present in code but not a dedicated first-pass feature.",
    source: src("frontend-ng/src/app/features/chat/chat-panel.component.ts", "frontend-ng/src/app/core/canonical-api.service.ts", "backend/app/services/evaluation/feedback_service.py"),
    scope: "Chat Recherche",
    tests: [
      { type: "Happy path", scenario: "Submit positive/negative feedback", steps: "Ask a question, submit feedback.", expected: "Feedback is recorded and UI remains on the same answer." },
      { type: "Boundary", scenario: "Feedback on deep retrieval answer", steps: "Promote deep answer then submit feedback.", expected: "Feedback links to the promoted answer/run metadata." },
      { type: "Error path", scenario: "Feedback API failure", steps: "Simulate failure while submitting.", expected: "User receives a recoverable notice; answer is not changed." },
    ],
  },
  {
    id: "CHT-018",
    name: "Chat voice commands",
    story: "As a voice chat user, I can use supported voice commands such as stop, repeat, rephrase, or send without corrupting the conversation loop.",
    expected: "Voice command detection emits command events to the voice session and performs command-specific UI actions only when valid for the current state.",
    edges: "Command phrase appears in normal speech, no assistant answer to repeat, command during streaming, disabled command pack.",
    validation: "False positives are minimized; unsupported commands do not send unintended chat prompts.",
    dependencies: "ChatPanelComponent voice command handling, VoiceSessionGateway command events.",
    assumptions: "Command packs are enabled by workspace voice_loop configuration when intended.",
    notes: "Complements chat voice dictation; separate because commands alter orchestration.",
    source: src("frontend-ng/src/app/features/chat/chat-panel.component.ts", "frontend-ng/src/app/core/voice-session.service.ts"),
    scope: "Chat Recherche",
    tests: [
      { type: "Happy path", scenario: "Repeat last answer by voice", steps: "After an answer, speak configured repeat command.", expected: "Assistant answer is repeated via TTS without creating a new user query." },
      { type: "Boundary", scenario: "Command-like phrase in normal prompt", steps: "Dictate a sentence containing a command phrase as content.", expected: "It is not incorrectly handled as a command." },
      { type: "Error path", scenario: "Rephrase command without answer", steps: "Speak rephrase before any assistant answer.", expected: "Clear no-answer state and no backend query.", severityIfFails: "Medium" },
    ],
  },
  {
    id: "CHT-019",
    name: "LiveKit voice control plane",
    story: "As a voice-capable user, I can obtain LiveKit configuration, room/token credentials, and agent dispatch for realtime or bridged voice sessions.",
    expected: "LiveKit endpoints expose config, create rooms, mint tokens, dispatch agents, and accept webhooks without coupling voice setup to chat/capture business logic.",
    edges: "LiveKit disabled, invalid surface, token for wrong room, webhook replay, agent dispatch failure.",
    validation: "Tokens are scoped; webhook/auth handling is safe; disabled LiveKit falls back gracefully.",
    dependencies: "/api/v1/livekit endpoints, LiveKit service, VoiceSessionGateway/bridge.",
    assumptions: "Andritz deployment may use cascade or LiveKit depending runtime configuration.",
    notes: "Shared by Chat Recherche and Knowledge Capture voice flows.",
    source: src("backend/app/api/v1/endpoints/livekit.py", "frontend-ng/src/app/core/livekit-conversation.service.ts"),
    scope: "Chat Recherche, Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Create room and token", steps: "Call config, rooms, then token for a synthetic voice session.", expected: "Room/token payloads are valid and scoped to requested surface." },
      { type: "Error path", scenario: "Agent dispatch failure", steps: "Simulate dispatch error.", expected: "Failure is visible and does not block non-voice capture/chat." },
      { type: "Security", scenario: "Webhook replay/invalid signature", steps: "Send invalid webhook.", expected: "Rejected without mutating session state.", severityIfFails: "Critical" },
    ],
  },
  {
    id: "CHT-020",
    name: "Chat document metadata facts panel",
    story: "As a chat user working with uploaded documents, I can see lightweight document facts such as title, filename, pages, sheets, language, keywords, and chunk count.",
    expected: "After upload, chat fetches /documents/{id}/metadata; partial metadata degrades gracefully and does not break the drop-and-ask session.",
    edges: "Metadata 404, NLTK/docmeta partial failure, very long keyword list, document still indexing.",
    validation: "Metadata loading state clears; fallback title/filename remains visible; no upload context is lost.",
    dependencies: "ChatWorkspaceComponent fetchDocMetadata, /documents/{id}/metadata.",
    assumptions: "Metadata endpoint may return sparse payloads for some formats.",
    notes: "Previously folded into drop-and-ask, now explicit for UX coverage.",
    source: src("frontend-ng/src/app/features/chat/chat-workspace.component.ts", "backend/app/api/v1/endpoints/documents.py"),
    scope: "Chat Recherche, Collections",
    tests: [
      { type: "Happy path", scenario: "Display uploaded document facts", steps: "Upload a PDF/DOCX and wait for metadata.", expected: "Facts render without hiding the uploaded doc row." },
      { type: "Error path", scenario: "Metadata 404", steps: "Simulate metadata endpoint returning 404.", expected: "Doc remains usable with meta null/fallback display." },
      { type: "Boundary", scenario: "Long keyword metadata", steps: "Use metadata with many keywords.", expected: "UI remains readable and does not overflow." },
    ],
  },
  {
    id: "CHT-021",
    name: "Chat overlay, command palette, and workspace focus route",
    story: "As a user, I can open Recherche from the command palette, shell overlay, or direct workspace focus URL without losing the same chat capabilities.",
    expected: "ChatOverlayComponent embeds ChatWorkspaceComponent inline; command palette chat actions open ask/system/drop modes; /workspace/:slug/chat mounts ChatFocusComponent with query params and hides the global overlay on that route.",
    edges: "Workspace slug missing, chat upload flag off, drop mode requested while disabled, overlay expanded while already on focus route, mobile inline sizing.",
    validation: "Entry point selection only changes presentation/start mode; it must not bypass auth/navigation profile guards, workspace source policy, or chat upload feature flags.",
    dependencies: "ChatOverlayComponent, ChatOverlayService, ChatFocusComponent, CommandPaletteComponent, ShellComponent, WorkspaceRoutes.",
    assumptions: "Command palette entries are visible according to the current navigation profile and workspace feature flags.",
    notes: "Discovery gap found during route scan; this is a user-facing entry-point feature distinct from answer generation.",
    source: src("frontend-ng/src/app/features/chat/chat-overlay.component.ts", "frontend-ng/src/app/features/chat/chat-focus.component.ts", "frontend-ng/src/app/features/chat/chat-overlay.service.ts", "frontend-ng/src/app/features/layout/command-palette.component.ts", "frontend-ng/src/app/features/workspace/workspace.routes.ts"),
    scope: "Chat Recherche",
    tests: [
      { type: "Happy path", scenario: "Open chat from command palette", steps: "Use command palette chat.ask and chat.system entries.", expected: "Overlay opens with requested start mode and normal ChatWorkspace capabilities." },
      { type: "Regression", scenario: "Open /workspace/:slug/chat directly", steps: "Navigate to a valid workspace focus chat URL.", expected: "ChatFocusComponent renders, global overlay is suppressed, and workspace settings link is correct." },
      { type: "Permission/security", scenario: "Drop command while upload disabled", steps: "Disable chat_document_upload and invoke chat.drop.", expected: "Drop entry is hidden or ignored; no upload bypass occurs.", severityIfFails: "High" },
    ],
  },
  {
    id: "KCAP-031",
    name: "Capture session flags",
    story: "As a capture user or facilitator, I can update session flags such as oracle question visibility without changing the transcript or report content.",
    expected: "PATCH /sessions/{id}/flags updates allowed session metadata flags and returns the serialized session.",
    edges: "Unknown flag, stale session, completed session, unauthorized update.",
    validation: "Only supported flags are persisted; transcript/events/proposals are not mutated by flag changes.",
    dependencies: "update_capture_session_flags, KnowledgeCaptureComponent flags state.",
    assumptions: "Flags are lightweight UI/runtime controls, not governance approvals.",
    notes: "Dedicated endpoint was not isolated in the first pass.",
    source: src("backend/app/api/v1/endpoints/knowledge_capture.py", "backend/app/services/knowledge_capture.py", "frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Mute oracle questions", steps: "Patch supported flag to hide questions.", expected: "Session returns with flag applied and transcript unchanged." },
      { type: "Invalid input", scenario: "Unknown flag", steps: "PATCH unsupported key.", expected: "Ignored or rejected without corrupting metadata." },
      { type: "Permission/security", scenario: "Unauthorized flag update", steps: "Attempt as user without capture update rights.", expected: "Denied.", severityIfFails: "High" },
    ],
  },
  {
    id: "KCAP-032",
    name: "Hint queue for guided capture",
    story: "As a planned capture user, I can receive passive hints tied to plan gaps without forcing the expert into a rigid questionnaire.",
    expected: "GET /sessions/{id}/hint-queue returns queued hints generated from retrieval/oracle processing and scoped to active topic/subtopic.",
    edges: "No hints, duplicate hints, hints answered by transcript, topic-only plan, muted oracle.",
    validation: "Hints are passive/dismissible and do not block voice/text capture; resolved hints hide safely.",
    dependencies: "get_hint_queue, process_capture_partial_hints, resolve_hints_from_expert_text.",
    assumptions: "Hints are guidance aids, not mandatory questions.",
    notes: "Separate from proposal open questions and oracle live questions.",
    source: src("backend/app/api/v1/endpoints/knowledge_capture.py", "backend/app/services/knowledge_capture.py", "frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Load hint queue", steps: "Start planned capture with generated hints and call hint queue.", expected: "Relevant hints appear for active section." },
      { type: "Boundary", scenario: "Expert answers hint organically", steps: "Speak text overlapping a hint.", expected: "Hint visibility updates without manual action." },
      { type: "Error path", scenario: "Hint queue load fails", steps: "Simulate endpoint failure.", expected: "Capture continues and UI degrades silently or with non-blocking notice." },
    ],
  },
  {
    id: "KCAP-033",
    name: "Proposal markdown export",
    story: "As a reviewer, I can export a capture proposal/report to Markdown for external review or archival.",
    expected: "POST /sessions/{id}/proposal/export returns generated Markdown for the latest/target proposal without publishing it.",
    edges: "No proposal, stale proposal id, large report, open questions included.",
    validation: "Export is read-only; content reflects current edited proposal and includes sources/open questions where implemented.",
    dependencies: "export_session_proposal_markdown, proposal serialization.",
    assumptions: "Markdown export is a convenience action, not a publication action.",
    notes: "Important to separate export from publish.",
    source: src("backend/app/api/v1/endpoints/knowledge_capture.py", "backend/app/services/knowledge_capture.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Export current proposal", steps: "Finalize synthetic capture and export.", expected: "Markdown contains title, report sections, sources/open questions." },
      { type: "Boundary", scenario: "No proposal exists", steps: "Call export before finalization.", expected: "Clear not-found/validation response." },
      { type: "Regression", scenario: "Export does not publish", steps: "Export accepted proposal.", expected: "Published state remains unchanged.", severityIfFails: "Critical" },
    ],
  },
  {
    id: "KCAP-034",
    name: "Direct proposal content edit",
    story: "As a reviewer, I can directly edit report markdown/content while preserving proposal state and auditability.",
    expected: "PATCH /proposals/{id}/content updates report content and related payload fields, then returns the serialized proposal.",
    edges: "Blank report, accepted/published proposal, concurrent edit, malformed markdown.",
    validation: "Direct edits are explicit, do not auto-publish, and do not erase captured facts or sources.",
    dependencies: "update_proposal_report_content, KnowledgeCaptureComponent report edit mode.",
    assumptions: "Direct edit is a reviewer action distinct from LLM instruction rewrite.",
    notes: "Complements KCAP-022 instruction rewrite.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts", "backend/app/api/v1/endpoints/knowledge_capture.py", "backend/app/services/knowledge_capture.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Save edited report markdown", steps: "Toggle edit mode, change a sentence, save.", expected: "Proposal content updates and structured view can re-render." },
      { type: "Boundary", scenario: "Blank content", steps: "Attempt saving blank report.", expected: "Blocked or safely rejected." },
      { type: "Regression", scenario: "Edit accepted proposal", steps: "Edit after auto-accept/review accept.", expected: "Status/audit behavior is explicit and no publish occurs.", severityIfFails: "High" },
    ],
  },
  {
    id: "KCAP-035",
    name: "Capture session detail reload and deep resume",
    story: "As a user, I can reopen an existing capture session from dashboard or URL and resume at the correct stage.",
    expected: "GET /sessions/{id} returns serialized session; frontend derives active surface from session/proposal/status and reloads events/documents/proposals as needed.",
    edges: "Archived session, completed with proposal, active without voice connection, missing session, owned by another user.",
    validation: "Reopen does not create duplicate sessions; stage is deterministic; permissions are enforced.",
    dependencies: "KnowledgeCaptureComponent open dashboard action, get_session, list proposals/events/documents.",
    assumptions: "Users often return after timeout or finalization fallback.",
    notes: "Previously observed navigation regressions make this a separate validation target.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts", "backend/app/api/v1/endpoints/knowledge_capture.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Reopen active capture", steps: "Create active session, leave dashboard, reopen.", expected: "Session opens in capture surface with transcript and controls." },
      { type: "Happy path", scenario: "Reopen completed report", steps: "Open session with proposal.", expected: "Report/review surface opens with structured proposal." },
      { type: "Permission/security", scenario: "Open inaccessible session id", steps: "Use direct URL/id for another user's session.", expected: "Denied or hidden.", severityIfFails: "High" },
    ],
  },
  {
    id: "KCAP-036",
    name: "Capture voice commands for turn, section, and session control",
    story: "As a speaker, I can end a turn, finish a section, or stop a session by configured voice command without clicking controls.",
    expected: "Capture voice command detection normalizes transcript text, emits command metadata, and invokes endpoint/section/session actions where valid.",
    edges: "Natural phrase mistaken for command, command during final STT, disabled command pack, free conversation without section.",
    validation: "Commands do not erase speech content accidentally; invalid commands are ignored or surfaced safely.",
    dependencies: "KnowledgeCaptureComponent detectCaptureVoiceCommand/handleCaptureVoiceCommand, VoiceSessionGateway command events.",
    assumptions: "Command packs are optional per workspace voice_loop settings.",
    notes: "Affects orchestration mechanics directly.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts", "backend/app/services/voice_session_gateway.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Voice command finishes turn", steps: "Speak configured end-turn command during capture.", expected: "Current turn endpoints and transcript is committed once." },
      { type: "Boundary", scenario: "Command-like normal speech", steps: "Say a sentence containing 'fin de session' as content.", expected: "No accidental session finish unless command confidence/path applies.", severityIfFails: "High" },
      { type: "Regression", scenario: "Finish section command in free mode", steps: "Use section command in free conversation.", expected: "No plan-section mutation occurs." },
    ],
  },
  {
    id: "KCAP-037",
    name: "Capture runtime metrics and latency audit",
    story: "As an operator, I can observe capture latency and client audio metrics without slowing voice/STT.",
    expected: "Voice gateway accepts client.metric, emits runtime.metric, and records endpoint_stt_ms, turn_audio_capture_ms, text_final_total_ms and partial skip reasons.",
    edges: "Metric spam, unknown payload keys, missing latency fields, client hidden tab, clock skew.",
    validation: "Metrics are throttled/audited and never block audio.frame/audio.endpoint or final transcript.",
    dependencies: "VoiceSessionGateway client metric handling, KnowledgeCaptureComponent emitCaptureClientMetric.",
    assumptions: "Metrics are diagnostic JSON; no migration required.",
    notes: "Needed for future Phase 3 performance validation.",
    source: src("backend/app/services/voice_session_gateway.py", "frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts", "frontend-ng/src/app/features/chat/chat-panel.component.ts"),
    scope: "Knowledge Capture, Chat Recherche",
    tests: [
      { type: "Happy path", scenario: "Emit client capture metric", steps: "During voice capture, emit sampled VAD/chunk metric.", expected: "runtime.metric is emitted with source client_capture." },
      { type: "Boundary/performance", scenario: "Metric burst", steps: "Send many metrics quickly.", expected: "Gateway throttles/ignores excess without affecting audio.", severityIfFails: "High" },
      { type: "Validation", scenario: "Latency fields on final turn", steps: "Complete a voice turn.", expected: "endpoint_stt_ms is distinct from turn_audio_capture_ms." },
    ],
  },
  {
    id: "KCAP-038",
    name: "Capture proposal listing and filtering",
    story: "As a reviewer, I can list proposals by status/session and find the current report to review or publish.",
    expected: "GET /knowledge-capture/proposals supports listing workspace proposals and optional session filtering used by finalization fallback.",
    edges: "Multiple proposals for one session, stale accepted proposal, empty list, permissions.",
    validation: "Newest relevant proposal is selected deterministically; inaccessible proposals are hidden.",
    dependencies: "listCaptureProposals frontend fallback, proposals endpoint, proposal serialization.",
    assumptions: "Finalization may need to recover by fetching latest proposal after event loss.",
    notes: "Separate from dashboard fiches and published fiches.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts", "backend/app/api/v1/endpoints/knowledge_capture.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "List proposals for session", steps: "Finalize then query proposals by session id.", expected: "Latest proposal is returned first/usable by UI fallback." },
      { type: "Boundary", scenario: "Multiple proposals", steps: "Create multiple proposal revisions in synthetic session.", expected: "UI chooses the intended latest active proposal." },
      { type: "Permission/security", scenario: "List proposals as limited user", steps: "Attempt listing across workspace.", expected: "Only permitted proposals appear.", severityIfFails: "High" },
    ],
  },
  {
    id: "KCAP-039",
    name: "Conversation-only autonomous capture loop",
    story: "As an expert in a no-plan capture, I can run an autonomous voice/text conversation where Agentium prompts, records, infers intent, manages confirmations, and prepares the report without exposing the manual composer unless fallback is needed.",
    expected: "Free-conversation sessions default to conversation_only. The UI hides manual answer input unless text fallback is active, starts LiveKit or backend WebSocket voice with mode conversation_only, posts final turns to /sessions/{id}/conversation-step, and the backend records conversation_intent_detected events while returning next_prompt, proposal, closure, and confirmation state as appropriate.",
    edges: "Microphone denied, LiveKit unavailable, WebSocket unavailable, interruption of prior prompt, stale last proposal, proposal acceptance requiring confirmation, free conversation user attempting manual mode without fallback.",
    validation: "Conversation-only must not auto-publish; confirmations remain explicit; client_turn_id/parent event links are preserved; voice fallback and text fallback share the same backend contract; user remains in capture/report workflow rather than dashboard on slow finalization.",
    dependencies: "KnowledgeCaptureComponent conversationMode/ensureVoiceConnection/submitConversationStep, ApiService conversationStep, process_conversation_step, VoiceSessionGateway, LiveKitConversationService.",
    assumptions: "The UX baseline is planned capture minus the plan rail; the absence of a plan must not change publication safety or transcript/oracle orchestration.",
    notes: "Discovered during route/API audit: /sessions/{id}/conversation-step was broader than written-turn capture and deserved a dedicated feature.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts", "frontend-ng/src/app/core/api.service.ts", "backend/app/api/v1/endpoints/knowledge_capture.py", "backend/app/services/knowledge_capture.py"),
    scope: "Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Run no-plan conversation-only answer loop", steps: "Create free conversation session, start conversation_only voice, answer one prompt.", expected: "Final transcript is sent through conversation-step, a conversation_intent_detected event is recorded, and next prompt/status updates without manual composer." },
      { type: "Error path", scenario: "Voice transport unavailable falls back to text", steps: "Deny microphone or simulate LiveKit/WebSocket failure.", expected: "Text fallback appears, typed answer posts to conversation-step, and session remains usable.", severityIfFails: "High" },
      { type: "Permission/security", scenario: "Proposal acceptance from conversation-only requires explicit authority", steps: "Trigger proposal/accept intent as a user lacking publish/review authority.", expected: "Backend denies acceptance/publish path and no fiche is published without explicit authorized confirmation.", severityIfFails: "Critical" },
    ],
  },
  {
    id: "COL-016",
    name: "Update collection metadata",
    story: "As an authorized operator, I can update collection metadata such as name/description/status without reingesting documents.",
    expected: "PATCH /documents/collections/{collection_id} updates allowed collection fields and returns serialized collection state.",
    edges: "Slug/name conflict, status transition, collection missing, unauthorized user.",
    validation: "Patch does not remove document_names, manifest entries, sources, or indexed data.",
    dependencies: "documents collection patch endpoint, knowledge_collections update status/serialize.",
    assumptions: "UI exposure may be limited, but API exists and affects collection integrity.",
    notes: "Data-preservation validation is key for Andritz.",
    source: src("backend/app/api/v1/endpoints/documents.py", "backend/app/services/knowledge_collections.py"),
    scope: "Collections",
    tests: [
      { type: "Happy path", scenario: "Patch synthetic collection description", steps: "PATCH QA collection description.", expected: "Metadata updates and documents remain unchanged." },
      { type: "Invalid input", scenario: "Patch invalid collection id", steps: "Use missing id.", expected: "404/clear error." },
      { type: "Permission/security", scenario: "Unauthorized patch", steps: "Attempt as read-only user.", expected: "Denied.", severityIfFails: "High" },
    ],
  },
  {
    id: "COL-017",
    name: "Legacy/global document list endpoint",
    story: "As legacy UI or integration code, I can list documents through /documents/list while preserving workspace/collection scoping.",
    expected: "GET /documents/list returns document rows compatible with older surfaces and current collection filters.",
    edges: "Large list, collection omitted, stale metadata, duplicate document ids.",
    validation: "Endpoint does not leak documents from other workspaces/collections; pagination/limits are safe where implemented.",
    dependencies: "/documents/list endpoint, vector/document store metadata.",
    assumptions: "Newer collection inventory is primary, but legacy endpoint remains active.",
    notes: "Discovered endpoint not explicit in first matrix.",
    source: src("backend/app/api/v1/endpoints/documents.py"),
    scope: "Collections",
    tests: [
      { type: "Happy path", scenario: "List documents in workspace", steps: "Call /documents/list with safe filters.", expected: "Document rows are returned for permitted scope." },
      { type: "Boundary/performance", scenario: "Large Andritz document list", steps: "Read-only call with bounded limit.", expected: "Response is bounded and performant." },
      { type: "Permission/security", scenario: "Cross-workspace list", steps: "Attempt to list another workspace collection.", expected: "No cross-workspace data returned.", severityIfFails: "High" },
    ],
  },
  {
    id: "COL-018",
    name: "Global document clear safety",
    story: "As an admin, I can clear documents only in explicitly approved synthetic contexts and never accidentally wipe Andritz collections.",
    expected: "DELETE /documents/clear is a destructive endpoint requiring strict permission/intent and should not be used during ordinary QA discovery.",
    edges: "Wrong workspace, production Andritz data, in-flight worker jobs, object store/vector store divergence.",
    validation: "Endpoint is permission-protected; QA plan marks it destructive and excludes it from read-only validation.",
    dependencies: "documents clear endpoint, vector/document stores, IAM.",
    assumptions: "Real Andritz/SFTP data must not be cleared without explicit user approval and backup strategy.",
    notes: "Explicitly tracked because the goal says do not lose data.",
    source: src("backend/app/api/v1/endpoints/documents.py"),
    scope: "Collections",
    tests: [
      { type: "Destructive safety", scenario: "Do not execute on Andritz", steps: "During QA discovery, only inspect endpoint permissions/code.", expected: "No clear request is sent.", severityIfFails: "Critical" },
      { type: "Permission/security", scenario: "Unauthorized clear", steps: "Attempt as non-admin in isolated environment.", expected: "Denied.", severityIfFails: "Critical" },
      { type: "Regression", scenario: "Synthetic clear with confirmation", steps: "If explicitly approved, clear only disposable synthetic workspace.", expected: "Only intended synthetic data is removed and stores remain consistent." },
    ],
  },
  {
    id: "COL-019",
    name: "Batch document upload",
    story: "As an operator, I can upload multiple documents in one batch and see per-file/job outcomes.",
    expected: "POST /documents/upload-batch accepts multiple files, creates collection/source/job records, and reports batch success/failure.",
    edges: "Partial batch failure, mixed extensions, large aggregate size, duplicate filenames.",
    validation: "One bad file does not silently corrupt the rest; failures are explicit and original accepted files are traceable.",
    dependencies: "/documents/upload-batch, worker ingest, knowledge_collections source records.",
    assumptions: "Use synthetic batch files for mutation tests.",
    notes: "Separate from single upload and SFTP promote flows.",
    source: src("backend/app/api/v1/endpoints/documents.py", "frontend-ng/src/app/features/knowledge/knowledge-base.component.ts"),
    scope: "Collections",
    tests: [
      { type: "Happy path", scenario: "Upload synthetic batch", steps: "Upload several small supported docs.", expected: "Batch response includes jobs/sources for all files." },
      { type: "Error path", scenario: "Mixed unsupported file", steps: "Include one unsupported file.", expected: "Failure is reported clearly without losing accepted files." },
      { type: "Boundary/performance", scenario: "Large batch", steps: "Upload near allowed aggregate limits in QA workspace.", expected: "UI/backend remain responsive or reject with bounded error." },
    ],
  },
  {
    id: "COL-020",
    name: "Add documents to existing collection",
    story: "As an operator, I can add uploaded documents directly to an existing collection endpoint.",
    expected: "POST /documents/collections/{collection_id}/documents adds files to a target collection and preserves its existing manifest and inventory.",
    edges: "Collection id by slug/name, collection missing, duplicate source names, worker failure.",
    validation: "Existing document_names and source rows are extended, not overwritten.",
    dependencies: "collection documents endpoint, create_worker_job, object store manifest.",
    assumptions: "UI may route uploads through this endpoint for collection-specific add actions.",
    notes: "Important for incremental Andritz collection updates.",
    source: src("backend/app/api/v1/endpoints/documents.py", "backend/app/services/knowledge_collections.py"),
    scope: "Collections",
    tests: [
      { type: "Happy path", scenario: "Add doc to QA collection", steps: "POST one synthetic file to existing collection.", expected: "Collection inventory gains one source; prior sources remain." },
      { type: "Boundary", scenario: "Duplicate document name", steps: "Add file with existing name.", expected: "Duplicate handling is deterministic and no manifest loss occurs." },
      { type: "Error path", scenario: "Worker enqueue failure", steps: "Simulate failure after upload.", expected: "Collection status/job reflects failure and original file is not orphaned." },
    ],
  },
  {
    id: "COL-021",
    name: "Knowledge scopes configuration",
    story: "As an admin/operator, I can view and update knowledge scopes used to group collections for chat and capture retrieval.",
    expected: "GET/PATCH /knowledge/scopes returns and updates workspace knowledge scope configuration.",
    edges: "Invalid scope shape, missing collection, overlapping scopes, permission denied.",
    validation: "Scopes reference only permitted collections and changes do not alter underlying collection data.",
    dependencies: "knowledge scopes endpoints, rag knowledge_scopes service, workspace settings.",
    assumptions: "Andritz uses scopes to constrain Recherche/capture source policy.",
    notes: "This is a configuration option explicitly requested by the goal.",
    source: src("backend/app/api/v1/endpoints/knowledge.py", "backend/app/services/rag/knowledge_scopes.py"),
    scope: "Collections, Chat Recherche, Knowledge Capture",
    tests: [
      { type: "Happy path", scenario: "Read scopes", steps: "GET /knowledge/scopes.", expected: "Configured scopes and collection refs are returned." },
      { type: "Invalid input", scenario: "Patch invalid scope", steps: "Send malformed scope config in synthetic workspace.", expected: "Rejected without altering existing scopes." },
      { type: "Permission/security", scenario: "Member patches scopes", steps: "Attempt PATCH as non-admin.", expected: "Denied.", severityIfFails: "High" },
    ],
  },
  {
    id: "COL-022",
    name: "Collection source bindings to systems/flows",
    story: "As an operator, I can understand which systems or flows use a collection before changing or deleting it.",
    expected: "Collection detail computes bindings/feature rows from systems/flow definitions and collection metadata.",
    edges: "Flow references stale collection slug, collection renamed, many systems, hidden system.",
    validation: "Bindings are read-only and permission-scoped; delete/update workflows can use them to warn operators.",
    dependencies: "KnowledgeViewComponent bindings/featureRows, CanonicalApiService systems, collection metadata.",
    assumptions: "Andritz has systems/flows bound to knowledge collections used by Recherche.",
    notes: "Not a separate backend endpoint, but a user-facing business process in collection detail.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-view.component.ts", "frontend-ng/src/app/core/canonical-api.service.ts"),
    scope: "Collections, Chat Recherche",
    tests: [
      { type: "Happy path", scenario: "View collection bindings", steps: "Open collection detail with known system usage.", expected: "Bound systems/flows are visible." },
      { type: "Boundary", scenario: "Stale flow reference", steps: "Inspect collection referenced by old slug.", expected: "UI handles stale reference without crashing." },
      { type: "Permission/security", scenario: "Hidden system binding", steps: "Open as user without system read access.", expected: "Hidden system details are not leaked.", severityIfFails: "High" },
    ],
  },
  {
    id: "COL-023",
    name: "Knowledge page document browse drawer",
    story: "As a user, I can inspect the document inventory for a collection directly from the Knowledge page before previewing or deleting any file.",
    expected: "The Knowledge page Browse documents action opens a drawer backed by /documents/list with paginated documents, preview actions, and delete actions only after inventory loads successfully.",
    edges: "Document inventory API failure, empty collection, large collection, stale document id, permission denied, retry after transient failure.",
    validation: "A failed inventory load must not be shown as a legitimate empty collection and must not expose stale preview/delete actions.",
    dependencies: "KnowledgeBaseComponent openBrowse/loadBrowsePage, /documents/list, document preview/delete endpoints.",
    assumptions: "Andritz document inventories can include SFTP-ingested content, so browse failures must be explicit and non-destructive.",
    notes: "Discovered while hardening Collections error handling; distinct from the collection detail inventory route.",
    source: src("frontend-ng/src/app/features/knowledge/knowledge-base.component.ts", "backend/app/api/v1/endpoints/documents.py"),
    scope: "Collections",
    tests: [
      { type: "Happy path", scenario: "Open document browse drawer", steps: "Open /knowledge, click Browse documents for a collection.", expected: "The drawer shows document rows, totals and preview/delete actions for loaded documents." },
      { type: "Error path", scenario: "Document list API fails", steps: "Force /documents/list to return 500 and click Browse documents.", expected: "The drawer shows a retryable error state and no document delete action.", severityIfFails: "High" },
      { type: "Boundary", scenario: "Empty loaded collection", steps: "Return a successful empty document list.", expected: "The drawer shows Empty collection only after a successful response." },
    ],
  },
  {
    id: "SFTP-015",
    name: "Secure deposit health",
    story: "As an operator, I can confirm whether secure deposit/SFTP is enabled and healthy for the current workspace.",
    expected: "GET /sftp/health returns enabled/configured state used by the SFTP connector to show or disable operations.",
    edges: "Workspace disabled, settings absent, SFTP process down, partial configuration.",
    validation: "Disabled health state hides/prevents mutation controls; no credentials or secrets are exposed.",
    dependencies: "SftpConnectorComponent load, secure_deposit_health endpoint.",
    assumptions: "Andritz should report enabled if secure deposit is configured.",
    notes: "Read-only and safe to validate.",
    source: src("frontend-ng/src/app/features/connectors/sftp/sftp-connector.component.ts", "backend/app/api/v1/endpoints/secure_deposit.py"),
    scope: "SFTP Andritz",
    tests: [
      { type: "Happy path", scenario: "Load SFTP health", steps: "Open connector or call /sftp/health.", expected: "Health payload reflects workspace enabled state." },
      { type: "Boundary", scenario: "Disabled workspace", steps: "Use disabled workspace in safe environment.", expected: "Controls are disabled and no uploads/promotes allowed." },
      { type: "Security", scenario: "Health leaks secrets", steps: "Inspect payload.", expected: "No passwords/host keys/session secrets returned.", severityIfFails: "Critical" },
    ],
  },
  {
    id: "SFTP-016",
    name: "SFTP indexing monitor",
    story: "As an operator, I can monitor indexing jobs related to the selected SFTP target collection.",
    expected: "SFTP connector polls knowledge jobs/collection state for the target collection and shows active/latest job status.",
    edges: "No target collection, job polling failure, many jobs, collection refresh while promoting.",
    validation: "Polling is read-only, bounded, and stops on component destroy; job status does not trigger unintended promote.",
    dependencies: "SftpConnectorComponent loadIndexingMonitor/pollIndexingMonitor, documents jobs/collections endpoints.",
    assumptions: "Worker jobs reflect SFTP promotion ingestion status.",
    notes: "First matrix had generic worker monitoring; this is the SFTP-specific UI.",
    source: src("frontend-ng/src/app/features/connectors/sftp/sftp-connector.component.ts", "backend/app/api/v1/endpoints/documents.py"),
    scope: "SFTP Andritz, Collections",
    tests: [
      { type: "Happy path", scenario: "View target collection indexing status", steps: "Select target collection and wait for monitor.", expected: "Latest/active jobs display correctly." },
      { type: "Error path", scenario: "Jobs endpoint failure", steps: "Simulate jobs load failure.", expected: "Connector remains usable and shows non-blocking error." },
      { type: "Performance", scenario: "Long connector session", steps: "Leave connector open.", expected: "Polling interval remains bounded and cleaned up on navigation." },
    ],
  },
  {
    id: "SFTP-017",
    name: "Secure deposit link copy and external handoff UX",
    story: "As an operator, I can copy deposit URLs/credentials safely when handing a link to an external depositor.",
    expected: "SFTP connector copy action copies visible values and displays confirmation; sensitive values are only available when backend reveals them.",
    edges: "Clipboard denied, password not available after creation, revoked link, wrong link selected.",
    validation: "UI never fabricates or re-displays hidden passwords; copied URL corresponds to selected link.",
    dependencies: "SftpConnectorComponent copy/link label helpers, DepositAccessLink serialization.",
    assumptions: "Operators need a safe handoff flow for Andritz external uploads.",
    notes: "User-facing workflow not represented by backend route alone.",
    source: src("frontend-ng/src/app/features/connectors/sftp/sftp-connector.component.ts", "backend/app/services/secure_deposit.py"),
    scope: "SFTP Andritz",
    tests: [
      { type: "Happy path", scenario: "Copy deposit URL", steps: "Create/select QA link and click copy URL.", expected: "Clipboard receives selected link URL and confirmation appears." },
      { type: "Security", scenario: "Password hidden after creation", steps: "Reload links list after creation.", expected: "Password is not re-exposed unless rotate/create response reveals it.", severityIfFails: "Critical" },
      { type: "Error path", scenario: "Clipboard permission denied", steps: "Block clipboard API and click copy.", expected: "User sees clear failure and no state corruption." },
    ],
  },
  {
    id: "SFTP-018",
    name: "Connectors catalogue SFTP entry and enablement gate",
    story: "As an operator, I can find the secure deposit connector from the Connectors page and understand whether the workspace has it configured.",
    expected: "ConnectorsPageComponent renders the SFTP connector catalogue card and routes to /connectors/sftp; configured state is computed from workspace connector settings secure_deposit.enabled or sftp.enabled. When both are disabled, the catalogue card remains visible as a supported connector but is not marked configured/Config saved.",
    edges: "Workspace settings absent, connector disabled, stale navigation card, user lacks connector permission, direct URL when card appears unconfigured.",
    validation: "The card status reflects workspace settings; an unconfigured card does not by itself authorize backend actions; direct SFTP actions remain backend permission guarded.",
    dependencies: "ConnectorsPageComponent, connectors.routes.ts, SftpConnectorComponent, workspace settings.",
    assumptions: "Andritz secure deposit should be enabled intentionally through workspace connector settings.",
    notes: "Discovery gap found during route scan; complements SFTP operational features by documenting the entry route/gate.",
    source: src("frontend-ng/src/app/features/connectors/connectors-page.component.ts", "frontend-ng/src/app/features/connectors/connectors.routes.ts", "frontend-ng/src/app/features/connectors/sftp/sftp-connector.component.ts"),
    scope: "SFTP Andritz",
    tests: [
      { type: "Happy path", scenario: "Open SFTP from connectors catalogue", steps: "Open /connectors and click secure deposit.", expected: "User lands on /connectors/sftp and connector loads health state." },
      { type: "Boundary", scenario: "Connector disabled in workspace settings", steps: "Use workspace settings with secure_deposit and sftp disabled.", expected: "SFTP card remains visible as a supported catalogue entry, but it is not marked configured and does not show Config saved." },
      { type: "Permission/security", scenario: "Direct route while card hidden", steps: "Navigate directly to /connectors/sftp as a user without intended access.", expected: "Backend actions remain denied and no data is exposed.", severityIfFails: "High" },
      { type: "Regression", scenario: "Connector navigation i18n key coverage", steps: "Run npm run check:i18n after parsing navigation.catalog.ts.", expected: "Every cockpit verb/section key, including connectors, has a dictionary entry and the guard fails if zero keys are parsed.", severityIfFails: "Medium" },
      { type: "Regression", scenario: "Mocked Andritz browser connector smoke", steps: "Run local Playwright with mocked secure deposit APIs and open /connectors then /connectors/sftp.", expected: "The connector catalogue exposes Secure Deposit and the SFTP page renders health, links and empty live-upload state without contacting real backend data." },
      { type: "Responsive", scenario: "Open connector catalogue and SFTP page on mobile width", steps: "Set viewport to mobile width and open /connectors then /connectors/sftp with mocked Andritz APIs.", expected: "The connector catalogue and SFTP surface remain reachable and show secure deposit/live-upload status without real backend data." },
      { type: "Permission/security", scenario: "Open SFTP route unauthenticated", preconditions: "No auth token.", steps: "Navigate directly to /connectors/sftp.", expected: "Route redirects to sign-in with redirectURL preserved before secure-deposit data APIs are exposed.", severityIfFails: "High" },
    ],
  },
];

const executionEvidence = [
  {
    id: "EXEC-2026-06-23-BE-001",
    date: "2026-06-23",
    command:
      "poetry run pytest app/tests/api/test_knowledge_capture_api.py app/tests/api/test_documents_collections.py app/tests/api/test_documents_upload_chat_flag.py app/tests/api/test_secure_deposit_api.py app/tests/api/test_livekit_api.py app/tests/services/test_chat_correction_proposal.py app/tests/services/test_knowledge_collections_worker.py app/tests/services/test_livekit_service.py app/tests/services/test_secure_deposit.py -q",
    result: "118 passed, 1 skipped, 0 failed",
    duration: "24.21s",
    warnings: "3454 warnings, mostly datetime.utcnow deprecations and dependency warnings; no product test failures.",
    safetyScope:
      "Local backend pytest using test DB/tmp_path/monkeypatch fixtures. No VM mutation, no real Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Partial backend automated execution only. Browser UX, responsive behaviour, VM read-only checks and destructive synthetic tests remain pending.",
  },
  {
    id: "EXEC-2026-06-23-FE-001",
    date: "2026-06-23",
    command:
      "/Users/thib/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node ./node_modules/@angular/cli/bin/ng.js build",
    result: "Frontend production build passed",
    duration: "11.392s",
    warnings:
      "Angular build warnings: initial bundle budget exceeded by 198.68 kB; mission-room component CSS and drawflow CSS budgets exceeded; maplibre-gl and earcut CommonJS optimization bailouts; one optional-chain warning in mission-room/vp-map-preview.",
    safetyScope:
      "Local frontend compile/build only. No backend calls, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    mappedTestCases: "",
    notes:
      "Compilation evidence for Angular routes/components including knowledge-capture-component, knowledge-view-component, sftp-connector-component, chat-knowledge-settings-component and LiveKit lazy chunks. Does not prove user journeys or browser UX.",
  },
  {
    id: "EXEC-2026-06-23-BE-002",
    date: "2026-06-23",
    command:
      "poetry run pytest app/tests/api/test_chat_sessions_api.py app/tests/api/test_chat_stream_hardening.py app/tests/services/test_workspace_chat_system.py app/tests/services/test_chat_grounding.py app/tests/services/test_omnirag_sources.py app/tests/services/test_omnirag_conversation_memory.py app/tests/services/test_voice_runtime_providers.py app/tests/services/test_voice_transcript_glossary.py app/tests/services/test_pipeline_retrieval.py -q",
    result: "137 passed, 0 failed",
    duration: "3.58s",
    warnings: "2317 warnings, mostly datetime.utcnow deprecations and dependency warnings; no product test failures after remediation.",
    safetyScope:
      "Local backend pytest using test DB/monkeypatch fixtures. No VM mutation, no real Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Chat/RAG/voice backend execution. Initial run found two degraded-retrieval observability failures; backend patch fixed them and full lot passed.",
  },
  {
    id: "EXEC-2026-06-23-VM-001",
    date: "2026-06-23",
    command:
      "ssh omnirag-demo 'cd /home/ubuntu/omnirag && bash scripts/deploy-vm.sh --check-only'; docker ps status; curl GET health/routes/auth probes",
    result:
      "VM drift audit passed; backend/frontend health 200; SPA routes /chat, /knowledge/capture, /knowledge, /connectors, /connectors/sftp returned 200; protected KC/SFTP APIs returned 401 unauthenticated",
    duration: "< 10s combined",
    warnings:
      "Initial route-probe shell quoting attempt was invalid and returned curl malformed URL errors; rerun with remote-side expansion succeeded. /api/v1/chat/sessions returned 404 and was not used as auth evidence because it is not the canonical route.",
    safetyScope:
      "VM read-only audit and GET probes only. No rebuild, no reset, no authenticated mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    mappedTestCases: "",
    notes:
      "Operational deployment evidence only. Confirms no container drift, core service health, static SPA route availability, and unauthenticated rejection for Knowledge Capture and SFTP endpoints; does not prove authenticated UX journeys.",
  },
  {
    id: "EXEC-2026-06-23-BE-003",
    date: "2026-06-23",
    command:
      "poetry run pytest app/tests/services/test_retrieval_policy.py app/tests/services/test_rag_context_worker.py app/tests/services/test_rag_service.py -q",
    result: "108 passed, 0 failed",
    duration: "5.02s",
    warnings:
      "209 warnings, mostly datetime.utcnow deprecations and dependency warnings; no product test failures.",
    safetyScope:
      "Local backend pytest using fake services, test DB, tmp_path and monkeypatch fixtures. No VM mutation, no real Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Service-level RAG policy/context execution for Andritz-style retrieval: guide policies, source/scope inclusion, retrieval profiles, oracle live/grounded budgets, dense collection planning, table/document fact retrieval and cache/deadline behavior. Does not prove authenticated browser UX.",
  },
  {
    id: "EXEC-2026-06-23-BE-004",
    date: "2026-06-23",
    command:
      "poetry run pytest app/tests/api/test_knowledge_capture_api.py app/tests/services/test_knowledge_capture.py -k \"free_conversation or conversation_only or conversation_step or session_complete_intent_generates_closure_sheet or closure_finish\" -q; poetry run pytest app/tests/api/test_knowledge_capture_api.py -q",
    result: "16 passed, 101 deselected, 0 failed; then 18 passed, 0 failed",
    duration: "8.97s + 15.93s",
    warnings:
      "Targeted lot emitted 3521 warnings plus one existing pending async task warning from a gateway test; API lot emitted 3279 warnings. Warnings are mostly datetime.utcnow deprecations and local Qdrant compatibility warnings; no product test failures.",
    safetyScope:
      "Local backend pytest using test DB/monkeypatch fixtures only. No VM mutation, no real Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Added API coverage for no-plan conversation-step turn recording, closure confirmation state, permission enforcement hooks, and denial of unauthorized conversation-only proposal acceptance. Initial targeted test exposed fixed serializer defect for unlimited free-conversation sessions losing session_end_pending.",
  },
  {
    id: "EXEC-2026-06-23-BE-005",
    date: "2026-06-23",
    command:
      "poetry run pytest app/tests/api/test_knowledge_capture_api.py::test_capture_document_view_api_records_active_view app/tests/api/test_knowledge_capture_api.py::test_capture_text_turn_api_preserves_document_refs -q; poetry run pytest app/tests/api/test_knowledge_capture_api.py -q",
    result: "2 passed, 0 failed; then 20 passed, 0 failed",
    duration: "5.63s + 18.35s",
    warnings:
      "Targeted lot emitted 438 warnings; full API lot emitted 3712 warnings. Warnings are mostly datetime.utcnow deprecations and local Qdrant compatibility warnings; no product test failures.",
    safetyScope:
      "Local backend pytest using test DB/monkeypatch fixtures only. No object-store upload, no worker dispatch, no VM mutation, no real Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Added API coverage for capture document active-view logging and typed capture turns carrying document_refs/visual_context. Upload/indexing and authenticated browser preview remain pending.",
  },
  {
    id: "EXEC-2026-06-23-BE-006",
    date: "2026-06-23",
    command:
      "poetry run pytest app/tests/api/test_knowledge_capture_api.py::test_capture_document_upload_api_queues_document_without_worker_side_effects app/tests/api/test_knowledge_capture_api.py -q",
    result: "22 passed, 0 failed",
    duration: "19.66s",
    warnings:
      "4161 warnings, mostly datetime.utcnow deprecations and local Qdrant compatibility warnings; no product test failures.",
    safetyScope:
      "Local backend pytest using test DB, tmp_path local object store, and monkeypatched worker dispatch only. No worker side effect, no VM mutation, no real Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Added API coverage for capture-session document upload of one PDF and one PNG, capture-specific collection creation, queued source ledger entries, local object-store persistence, worker-job payload, and capture_document_uploaded events.",
  },
  {
    id: "EXEC-2026-06-23-BE-007",
    date: "2026-06-23",
    command:
      "poetry run pytest app/tests/services/test_knowledge_capture.py::test_retrieval_prefetch_and_interruption_are_audited -q; poetry run pytest app/tests/services/test_knowledge_capture.py -q",
    result: "1 passed, 0 failed; then 99 passed, 0 failed",
    duration: "1.78s + 6.03s",
    warnings:
      "Targeted run emitted 240 warnings; full service lot emitted 14232 warnings. Warnings are mostly datetime.utcnow deprecations and local Qdrant compatibility warnings; no product test failures.",
    safetyScope:
      "Local backend service pytest using test DB, fake providers, tmp fixtures and monkeypatches only. No VM mutation, no real Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Full Knowledge Capture service execution. Initial run exposed a stale test harness call that simulated a voice/STT scenario without input_modality=voice; test fixed to match VoiceSessionGateway and now verifies stt_final audit on the real voice append_turn contract.",
  },
  {
    id: "EXEC-2026-06-23-BE-008",
    date: "2026-06-23",
    command:
      "poetry run pytest app/tests/api/test_documents_collections.py app/tests/services/test_knowledge_collections_worker.py -q",
    result: "30 passed, 0 failed",
    duration: "2.30s",
    warnings:
      "268 warnings, mostly datetime.utcnow deprecations and dependency warnings; no product test failures.",
    safetyScope:
      "Local backend pytest using test DB, tmp_path/local object store and monkeypatched services only. Includes synthetic delete/worker/ledger flows; no VM mutation, no real Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Collections API + worker execution covering ledger listing, inventory, previews, search, diagnostics, uploads, worker jobs, delete on synthetic collection, BM25 artifact/rebuild behavior, deduplication, materialization error handling and SPL wave ledger finalization.",
  },
  {
    id: "EXEC-2026-06-23-BE-009",
    date: "2026-06-23",
    command:
      "poetry run pytest app/tests/api/test_secure_deposit_api.py app/tests/services/test_secure_deposit.py app/tests/services/test_spl_wave_importer.py -q",
    result: "60 passed, 1 skipped, 0 failed",
    duration: "9.15s",
    warnings:
      "392 warnings, mostly datetime.utcnow deprecations and dependency warnings; no product test failures.",
    safetyScope:
      "Local backend pytest using test DB, tmp_path/local secure-deposit storage, fake dispatch and monkeypatched services only. Includes synthetic upload/promote/reconcile/quarantine/wave-plan flows; no VM mutation, no real Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Secure Deposit/SFTP synthetic execution covering link/session auth, allowed-extension policy, staged upload path safety, previews/downloads/archive browsing, promotion queue payloads, indexing assist, operations/reconciliation quarantine, SPL wave planning, namespace collision guards and archive reindexing.",
  },
  {
    id: "EXEC-2026-06-23-FE-002",
    date: "2026-06-23",
    command:
      "npm run check:i18n; npm run check:ui-chrome; /Users/thib/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node ./node_modules/@angular/cli/bin/ng.js build -c production",
    result: "Navigation i18n coverage OK (26 catalog keys checked); Agentium UI chrome guard OK; Frontend production build passed",
    duration: "0.17s + 0.17s + 12.150s",
    warnings:
      "Production build warnings unchanged from prior frontend evidence: initial bundle budget exceeded by 198.68 kB; mission-room component CSS and drawflow CSS budgets exceeded; maplibre-gl and earcut CommonJS optimization bailouts; one optional-chain warning in mission-room/vp-map-preview.",
    safetyScope:
      "Local frontend static guards and compile/build only. No backend calls, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Initial i18n guard reported OK while checking 0 catalog keys. Guard was fixed to parse navigation.catalog.ts; it then exposed missing nav.connectors. Added FR/EN nav.connectors and reran i18n guard, UI chrome guard and production build successfully.",
  },
  {
    id: "EXEC-2026-06-23-FE-003",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "1 passed, 0 failed",
    duration: "13.1s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version warning from local environment. First run before assertion adjustment rendered the page but failed on FR-only label expectation; test was corrected to accept FR/EN.",
    safetyScope:
      "Local Playwright browser smoke with all /api/v1/** calls mocked in-page. No backend calls, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Mocked authenticated Andritz workspace route smoke covering /connectors, /connectors/sftp, /knowledge, /knowledge/capture and /chat first-screen rendering. Playwright config now supports E2E_CHROMIUM_EXECUTABLE so local cache/system browsers can run without downloading a new browser.",
  },
  {
    id: "EXEC-2026-06-23-FE-004",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "2 passed, 0 failed",
    duration: "16.1s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version warning and FORCE_COLOR/NO_COLOR warnings from local environment.",
    safetyScope:
      "Local Playwright browser smoke with all /api/v1/** calls mocked in-page. No backend calls, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Added mobile viewport smoke for /connectors, /connectors/sftp, /knowledge, /knowledge/capture and /chat while retaining the desktop mocked Andritz route smoke.",
  },
  {
    id: "EXEC-2026-06-23-BE-010",
    date: "2026-06-23",
    command:
      "poetry run pytest app/tests/services/test_iam_engine.py app/tests/api/test_knowledge_capture_api.py -q",
    result: "28 passed, 0 failed",
    duration: "19.23s",
    warnings:
      "4174 warnings, mostly datetime.utcnow deprecations and local Qdrant compatibility warnings; no product test failures.",
    safetyScope:
      "Local backend pytest using test DB, FastAPI TestClient fixtures, workspace-local IAM enforcement and monkeypatched cache warmup only. No VM mutation, no real Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Reviewer capture IAM remediation: service test proves reviewers can create/update/execute only their own capture sessions, and API test proves an IAM-enforced reviewer can create and start a free-conversation capture through /knowledge-capture/plans and /sessions/{id}/start.",
  },
  {
    id: "EXEC-2026-06-23-BE-011",
    date: "2026-06-23",
    command:
      "poetry run pytest app/tests/api/test_iam_api.py::test_iam_matrix_exposes_reviewer_capture_create_and_owned_execution -q",
    result: "1 passed, 0 failed",
    duration: "0.60s",
    warnings:
      "3 datetime.utcnow deprecation warnings from SQLAlchemy schema defaults; no product test failures.",
    safetyScope:
      "Local backend API pytest using test DB and FastAPI TestClient only. No VM mutation, no real Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Validates /iam/matrix, the exact frontend permission source, returns workspace_reviewer capture_session create/update/execute allowed_for_subject=true for create and owner-scoped operations.",
  },
  {
    id: "EXEC-2026-06-23-FE-005",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "3 passed, 0 failed",
    duration: "16.6s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version warning and FORCE_COLOR/NO_COLOR warnings from local environment.",
    safetyScope:
      "Local Playwright browser smoke with all /api/v1/** calls mocked in-page. No backend calls, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds a mocked reviewer IAM matrix case proving /knowledge/capture renders the New/Nouvelle capture action enabled for workspace_reviewer while retaining desktop and mobile route smokes.",
  },
  {
    id: "EXEC-2026-06-23-FE-006",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "8 passed, 0 failed",
    duration: "18.8s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; unauthenticated guard cases use no token and only verify redirect to sign-in for /chat, /knowledge, /knowledge/capture and /connectors/sftp. No VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds no-token browser guard tests proving the protected Recherche, Collections, Knowledge Capture and Secure Deposit routes redirect to /auth/signin with redirectURL preserved instead of exposing protected shells to unauthenticated users. Adds a disabled SFTP workspace-settings case proving the catalogue card stays visible as ready but is not marked configured/Config saved.",
  },
  {
    id: "EXEC-2026-06-23-FE-007",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "9 passed, 0 failed",
    duration: "19.1s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the Collections error case forces /documents/collections to return 500 and asserts an error/retry state, disabled create/upload mutation controls, and no collection-card destructive action. No VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds a mocked Collections API failure smoke covering the non-destructive load-error state, retry control, disabled mutation buttons and hidden collection delete actions. Verifies DEF-2026-06-23-COL-001 after the frontend error-state fix.",
  },
  {
    id: "EXEC-2026-06-23-FE-008",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "10 passed, 0 failed",
    duration: "17.9s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the document browse error case forces /documents/list to return 500 and asserts an error/retry state with no document delete action. No VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds a mocked Knowledge page document-inventory failure smoke and verifies DEF-2026-06-23-COL-023 after the browse drawer error-state fix.",
  },
  {
    id: "EXEC-2026-06-23-FE-009",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "11 passed, 0 failed",
    duration: "20.0s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the search error case forces /documents/search to return 500 and asserts an inline error with no stale result row. No VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds a mocked Knowledge search failure smoke and verifies DEF-2026-06-23-COL-008 after the search drawer error-state fix.",
  },
  {
    id: "EXEC-2026-06-23-FE-010",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "12 passed, 0 failed",
    duration: "19.6s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the search-context case runs a synthetic successful search, closes the drawer, opens collection search and asserts no stale query/result/error state. No VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds a mocked Knowledge search context-reset smoke and verifies DEF-2026-06-23-COL-008B after the search drawer stale-state fix.",
  },
  {
    id: "EXEC-2026-06-23-FE-011",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "13 passed, 0 failed",
    duration: "21.0s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the accepted capture proposal case counts /publish requests and proves none are sent when opening review or moving to the publish step, then exactly one is sent after the explicit Publish click. No VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds a mocked explicit-publication guard for Knowledge Capture: an accepted proposal can be reviewed and opened in Publish without auto-publication; publication occurs only after the final user click.",
  },
  {
    id: "EXEC-2026-06-23-FE-012",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "14 passed, 0 failed",
    duration: "23.0s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the no-plan capture creation case posts only to mocked /knowledge-capture/plans, records the request payload, returns a synthetic free_conversation_v1 session and verifies the Plan rail is hidden. No backend calls, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage for Knowledge Capture free-conversation creation: New capture -> title -> Sans plan sends plan_mode=free_conversation and opens the capture surface without exposing a Plan rail.",
  },
  {
    id: "EXEC-2026-06-23-FE-013",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "15 passed, 0 failed",
    duration: "23.3s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the Recherche quick-ask case mocks /sessions and /chat/stream SSE chunks, records only the request payload and verifies source rendering. No backend calls, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage for Chat Recherche quick ask: a mocked SSE response displays the streamed answer, source count and source detail while proving the payload requests streaming and sources.",
  },
  {
    id: "EXEC-2026-06-23-FE-014",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "16 passed, 0 failed",
    duration: "23.1s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the drop-and-ask case uses a synthetic in-memory text file, intercepts /documents/upload-batch, creates a mocked ephemeral context and verifies the chat stream payload. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage for Chat Recherche session-doc + workspace-source orchestration: attach synthetic doc, switch to + Sources, and prove context_id/context_mode=combine/knowledge_scope/include_sources are preserved in /chat/stream.",
  },
  {
    id: "EXEC-2026-06-23-FE-015",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "17 passed, 0 failed",
    duration: "24.1s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the drop-and-ask Only case uses a synthetic in-memory text file, intercepts /documents/upload-batch, creates a mocked ephemeral context and verifies the chat session/stream payload. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage for Chat Recherche session-doc-only isolation: keep default Only mode and prove context_id/context_mode=replace/knowledge_scope=null/include_sources are preserved in /chat/stream.",
  },
  {
    id: "EXEC-2026-06-23-FE-016",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "18 passed, 0 failed",
    duration: "24.3s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the disabled chat upload case sets features.chat_document_upload=false, verifies no file input/dropzone is rendered, asks a normal question and verifies no upload request is emitted. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage for Chat Recherche drop-and-ask feature gating: when upload is disabled at workspace settings level, upload controls disappear while Quick ask remains usable.",
  },
  {
    id: "EXEC-2026-06-23-FE-017",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "19 passed, 0 failed",
    duration: "24.9s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the persist-context case uses a synthetic in-memory text file, intercepts /documents/upload-batch and /contexts/{id}/persist, verifies no persist happens before the explicit click and exactly one persist request after. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage for Chat Recherche drop-and-ask context persistence: the ephemeral context can be promoted only after an explicit Persist click.",
  },
  {
    id: "EXEC-2026-06-23-FE-018",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "20 passed, 0 failed",
    duration: "27.3s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the persist-failure case uses a synthetic in-memory text file, intercepts /documents/upload-batch and /contexts/{id}/persist, returns a mocked 403, verifies a recoverable error is visible and the Persist action is re-enabled. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage for the Chat Recherche drop-and-ask persistence failure path and verifies the UI no longer silently swallows a null persistContext result.",
  },
  {
    id: "EXEC-2026-06-23-FE-019",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "21 passed, 0 failed",
    duration: "27.1s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the upload-failure case uses a synthetic in-memory text file, intercepts /documents/upload-batch, returns a mocked 500, verifies no context creation, no visible fake session doc and a subsequent Quick ask with null context. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage for the Chat Recherche drop-and-ask upload failure path: failed upload is visible and recoverable, and the chat stream remains usable without a stale ephemeral context.",
  },
  {
    id: "EXEC-2026-06-23-FE-020",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "22 passed, 0 failed",
    duration: "28.9s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the partial-upload case uses synthetic in-memory text files, intercepts /documents/upload-batch with one success and one failed row, and verifies the failed filename is excluded from session docs and /contexts data_refs. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage and remediation for Chat Recherche drop-and-ask partial upload integrity: only successfully indexed files can enter the ephemeral context.",
  },
  {
    id: "EXEC-2026-06-23-FE-021",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "23 passed, 0 failed",
    duration: "28.4s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the metadata-failure case uses a synthetic in-memory text file, intercepts /documents/{id}/metadata with a mocked 404, verifies fallback filename display, cleared spinner and a subsequent chat stream using the ephemeral context. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage for Chat document metadata failure: missing metadata does not break the drop-and-ask document row or the downstream context-scoped chat request.",
  },
  {
    id: "EXEC-2026-06-23-FE-022",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "24 passed, 0 failed",
    duration: "27.8s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the long-keywords metadata case uses a synthetic in-memory text file, intercepts /documents/{id}/metadata with eight keywords, verifies only four chips render and the context-scoped chat request still works. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage for Chat document metadata keyword overflow: long metadata remains compact and does not break the drop-and-ask flow.",
  },
  {
    id: "EXEC-2026-06-23-FE-023",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "25 passed, 0 failed",
    duration: "29.8s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the source-mode toggle case uses a synthetic in-memory text file, toggles + Sources then Only, and verifies the final /sessions and /chat/stream payloads use context_mode=replace and knowledge_scope=null. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage for Chat source-mode transition state: returning from + Sources to Only keeps the final request scoped to session docs only.",
  },
  {
    id: "EXEC-2026-06-23-FE-024",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "26 passed, 0 failed",
    duration: "30.2s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the session-doc detach case uses a synthetic in-memory text file, updates only the ephemeral context data_refs via mocked PATCH, and verifies the final /sessions and /chat/stream payloads carry context_id=null and context_mode=null. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage and remediation for Chat session-doc detach: removing the last temporary doc clears stale drop-and-ask scope without deleting indexed data.",
  },
  {
    id: "EXEC-2026-06-23-FE-025",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "27 passed, 0 failed",
    duration: "30.3s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the detach-update-failure case uses a synthetic in-memory text file, mocks /contexts/{id} PATCH as 500, verifies the doc remains attached, and verifies the next /sessions and /chat/stream payloads keep the existing context_id/context_mode. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage and remediation for Chat session-doc detach failure handling: a failed context PATCH no longer removes the doc locally or clears live chat scope.",
  },
  {
    id: "EXEC-2026-06-23-FE-026",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "28 passed, 0 failed",
    duration: "31.9s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the multi-doc detach case uses two synthetic in-memory text files, verifies context creation with both filenames, mocked PATCH with only the remaining filename, and final /sessions and /chat/stream payloads keeping the existing context_id/context_mode. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage for Chat multi-document session scope: detaching one temporary doc keeps the remaining session doc scoped without clearing the context.",
  },
  {
    id: "EXEC-2026-06-23-FE-027",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "29 passed, 0 failed",
    duration: "30.9s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the context-recreate case uses two synthetic in-memory text files across two uploads, verifies first context creation, mocked detach PATCH with data_refs=[], second context creation with only the new filename, and final /sessions and /chat/stream payloads using the recreated context_id/context_mode. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage for Chat session context recreation: after detaching the final temporary doc, a later upload creates a fresh ephemeral context without stale data_refs.",
  },
  {
    id: "EXEC-2026-06-23-FE-028",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "30 passed, 0 failed",
    duration: "33.9s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the context-create-failure case uses a synthetic in-memory text file, upload succeeds in mock, /contexts POST returns a mocked 500, and the test verifies the doc is not shown as attached and final /sessions and /chat/stream payloads have context_id=null and context_mode=null. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage and remediation for Chat context creation failure: failed ephemeral context creation no longer leaves a false attached session doc in the UI.",
  },
  {
    id: "EXEC-2026-06-23-FE-029",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "31 passed, 0 failed",
    duration: "33.9s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the append-update-failure case uses synthetic in-memory text files, creates one mocked ephemeral context, makes the second upload succeed, returns a mocked 500 for /contexts/{id} PATCH, and verifies only the newly added doc is rolled back while the first doc remains scoped for /sessions and /chat/stream. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage for Chat append-to-existing-context failure handling: a failed PATCH rolls back only the newly added temporary doc and preserves the existing session-doc scope.",
  },
  {
    id: "EXEC-2026-06-23-FE-030",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "32 passed, 0 failed",
    duration: "34.8s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the source-preview case streams a synthetic answer with one cited source, opens the source preview button, serves a mocked /documents/{id}/rich-preview text payload, verifies collection_name and filename query params, and confirms the preview text/highlight render. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage for Chat source citations and preview drawer: a cited source can open a document preview with the expected scoped request and highlighted snippet.",
  },
  {
    id: "EXEC-2026-06-23-FE-031",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "33 passed, 0 failed",
    duration: "36.1s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the unavailable-source-preview case streams a synthetic answer with one cited source, opens the preview button, returns a mocked 404 from /documents/{id}/rich-preview, verifies collection_name and filename query params, and confirms the drawer shows a recoverable error while the chat composer remains available. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage for Chat source preview fallback: a missing preview asset is visible and recoverable without breaking the chat surface.",
  },
  {
    id: "EXEC-2026-06-23-FE-032",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "34 passed, 0 failed",
    duration: "36.2s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the forbidden-source-preview case streams a synthetic answer with one cited source, opens the preview button, returns a mocked 403 from /documents/{id}/rich-preview, verifies collection_name and filename query params, confirms the drawer shows a permission-denied error, and checks no preview text/highlight is rendered while chat remains usable. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage for Chat source preview authorization failure: denied previews do not leak source content and leave the chat surface usable.",
  },
  {
    id: "EXEC-2026-06-23-FE-033",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "35 passed, 0 failed",
    duration: "37.3s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the written-note-active-document case creates a synthetic no-plan capture, returns it as active, uploads an in-memory PDF through mocked capture-document endpoints, opens a mocked rich-preview, records a mocked /knowledge-capture/sessions/{id}/documents/view call, then posts a written capture note and verifies /turns carries document_refs and visual_context for the active page. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage for mixing written capture input with an active document view while preserving the same document-ref contract used by voice turns.",
  },
  {
    id: "EXEC-2026-06-23-FE-034",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "36 passed, 0 failed",
    duration: "39.2s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the capture-document-upload-failure case creates a synthetic no-plan capture, returns it as active, makes /knowledge-capture/sessions/{id}/documents return a mocked 500 for an in-memory PDF, verifies the user-visible warning, confirms no document/preview/view request is created, then posts a written capture note and verifies /turns carries no document_refs or visual_context. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage for non-destructive capture-document upload failure handling while keeping written capture usable.",
  },
  {
    id: "EXEC-2026-06-23-FE-035",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "37 passed, 0 failed",
    duration: "37.8s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the capture-multi-document-active-view case creates a synthetic no-plan capture, returns two in-memory uploaded capture documents, previews both through mocked rich-preview endpoints, records mocked /documents/view calls, then posts a written note and verifies /turns references only the latest active document. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage for switching active capture documents before typed input so mixed written/document capture cannot carry stale document_refs.",
  },
  {
    id: "EXEC-2026-06-23-FE-036",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "38 passed, 0 failed",
    duration: "39.6s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the capture-document-view-logging-failure case creates a synthetic no-plan capture, returns an in-memory uploaded capture document, opens mocked rich-preview, forces /knowledge-capture/sessions/{id}/documents/view to return 500, then posts a written note and verifies /turns still carries the optimistic active document_refs/visual_context. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage for non-blocking capture document view logging failure while preserving written capture context.",
  },
  {
    id: "EXEC-2026-06-23-FE-037",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "39 passed, 0 failed",
    duration: "41.8s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the unsupported-capture-document case creates a synthetic no-plan capture, forces /knowledge-capture/sessions/{id}/documents to return a mocked 400 with a backend detail, verifies that detail is shown in the voice notice, confirms no fake document/preview/view state is created, then posts a written note without document_refs. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage and remediation for unsupported capture-document upload messages so actionable backend rejection details are not hidden by a generic fallback.",
  },
  {
    id: "EXEC-2026-06-23-FE-038",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "40 passed, 0 failed",
    duration: "43.5s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the capture-document-preview-unavailable case creates a synthetic no-plan capture, uploads an in-memory capture document through mocked endpoints, forces /documents/{id}/rich-preview to return 404, verifies the preview error detail is visible, confirms /documents/view records the active page, then posts a written note carrying document_refs/visual_context. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage for unavailable capture document previews while preserving capture continuity and active document context.",
  },
  {
    id: "EXEC-2026-06-23-FE-039",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "41 passed, 0 failed",
    duration: "30.8s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the collection-document-inventory case opens /knowledge with a synthetic collection, clicks Browse documents, verifies the mocked /documents/list query uses collection_name=andritz-qa, limit=100 and offset=0, and confirms the loaded drawer shows the synthetic PDF inventory before any preview/delete action. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level happy-path coverage for the Knowledge page document inventory drawer, complementing the existing non-destructive failure-state coverage.",
  },
  {
    id: "EXEC-2026-06-23-FE-040",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "42 passed, 0 failed",
    duration: "31.4s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the empty-collection-inventory case opens /knowledge with a synthetic collection, makes /documents/list return HTTP 200 with documents=[], verifies the scoped query parameters, and confirms the drawer shows Empty collection without preview/delete actions or load-error messaging. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level boundary coverage for a successful empty Knowledge document inventory so operators do not confuse true empty collections with failed loads or stale destructive actions.",
  },
  {
    id: "EXEC-2026-06-23-FE-041",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "43 passed, 0 failed",
    duration: "33.1s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the collection-preview-fallback case opens a synthetic collection inventory, clicks Preview for a synthetic PDF, verifies /documents/list and /documents/preview/{id} are both scoped to collection_name=andritz-qa, and confirms the preview drawer shows the Open file download fallback. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage for the Knowledge collection preview fallback path when converted inline preview content is unavailable but a scoped download URL is returned.",
  },
  {
    id: "EXEC-2026-06-23-FE-042",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "44 passed, 0 failed",
    duration: "34.4s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the unsafe-collection-preview case opens a synthetic collection inventory, makes /documents/preview/{id} return script-like HTML content, verifies the request is scoped to collection_name=andritz-qa, and confirms the preview drawer renders the payload as inert text without setting window.__andritzPreviewXss or exposing an Open file action. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level security coverage for Knowledge collection preview sanitization: HTML/script-like preview content is displayed as text rather than executed.",
  },
  {
    id: "EXEC-2026-06-23-FE-043",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "45 passed, 0 failed",
    duration: "36.3s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 odd-version and FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page attempted /api/v1/help-content through the local dev proxy and received ECONNREFUSED because no backend was running; the guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the forbidden-collection-preview case opens a synthetic collection inventory, first renders a scoped download fallback from /documents/preview/{id}, then makes the next preview call return HTTP 403 with a permission detail, verifies both requests are scoped to collection_name=andritz-qa, and confirms the second preview drawer shows only the permission error without stale text content, binary fallback copy or an Open file action. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level permission coverage for Knowledge collection preview: forbidden previews after a prior successful preview surface a clear error and do not leak stale document content or download links.",
  },
  {
    id: "EXEC-2026-06-23-FE-044",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "46 passed, 0 failed",
    duration: "37.6s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page may attempt /api/v1/help-content through the local dev proxy when no backend is running; guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the synthetic document-delete case opens the Knowledge collection inventory for andritz-qa, verifies no DELETE request is sent when the Delete document control only opens the confirmation dialog, then clicks the explicit confirm button and verifies the only DELETE request is scoped to collection_name=andritz-qa. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level destructive-safety coverage for Knowledge collection document deletion: deletion requires explicit confirmation and remains scoped to the synthetic collection.",
  },
  {
    id: "EXEC-2026-06-23-FE-045",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "47 passed, 0 failed",
    duration: "38.9s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page may attempt /api/v1/help-content through the local dev proxy when no backend is running; guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the synthetic collection-delete case opens the Knowledge collection card for andritz-qa, verifies the Delete collection confirm button is disabled until the exact collection name is typed, verifies no DELETE request is sent before confirmation, then sends one mocked DELETE to /documents/collections/andritz-qa and verifies the synthetic collection disappears from the mocked list. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level destructive-safety coverage for Knowledge collection deletion: typed confirmation is required and the operation remains limited to the synthetic collection.",
  },
  {
    id: "EXEC-2026-06-23-FE-046",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "49 passed, 0 failed",
    duration: "41.6s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page may attempt /api/v1/help-content through the local dev proxy when no backend is running; guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the synthetic forbidden-delete cases make confirmed collection and document delete requests return HTTP 403, verify the backend detail is visible to the user, and confirm the collection/document remains visible after the failed delete. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level permission-denial coverage for Knowledge destructive actions: backend 403 responses do not remove collection or document state from the UI.",
  },
  {
    id: "EXEC-2026-06-23-FE-047",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "51 passed, 0 failed",
    duration: "42.7s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. The unauthenticated sign-in page may attempt /api/v1/help-content through the local dev proxy when no backend is running; guard assertions still passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the synthetic collection-create cases verify no POST is sent while the create form is blank, then create a synthetic andritz-qa-scratch collection through mocked /documents/collections?collection_name=..., and separately make creation return HTTP 403 to confirm the error is visible and no fake collection appears. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level coverage for Knowledge collection creation: explicit user input is required, successful synthetic creation appears after reload, and forbidden creation does not create stale UI state.",
  },
  {
    id: "EXEC-2026-06-23-FE-048",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "52 passed, 0 failed",
    duration: "42.0s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the synthetic SFTP staging queue case loads three mocked deposit files, verifies received-status queue counters and hidden-status state, filters/searches the component queue state, and asserts no promote, bulk-promote or archive-download endpoint is called. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level read-only coverage for SFTP staging queue load/filter behavior without triggering promotion or download actions.",
  },
  {
    id: "EXEC-2026-06-23-FE-049",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "53 passed, 0 failed",
    duration: "42.9s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the synthetic SFTP operations/indexing assist case renders a live upload snapshot, dry-run reconciliation summary, target collection indexing job state, and an advisory promote-now recommendation for one mocked received file, then asserts no promote, bulk-promote, archive-download or reconcile mutation endpoint is called. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level read-only coverage for SFTP operations monitor, indexing assist recommendations, and indexing job monitor without triggering promotion, quarantine or download actions.",
  },
  {
    id: "EXEC-2026-06-23-FE-050",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "54 passed, 0 failed",
    duration: "43.4s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the synthetic SFTP preview/archive case renders a staged file preview and a ZIP member preview from mocked deposit endpoints, then asserts no promote, bulk-promote, staging ZIP download, file download or archive-member download endpoint is called. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level read-only coverage for SFTP staged-file preview and ZIP archive member preview without triggering promotion or download actions.",
  },
  {
    id: "EXEC-2026-06-23-FE-051",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "55 passed, 0 failed",
    duration: "46.5s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the synthetic SFTP target-collection case adds a second mocked Knowledge collection, selects it in the SFTP connector, runs indexing assist for one mocked received file, and verifies the assist payload carries collection_slug=maintenance-qa while no promote, bulk-promote or archive-download endpoint is called. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level read-only coverage for SFTP target collection selection feeding indexing assist without triggering promotion or download actions.",
  },
  {
    id: "EXEC-2026-06-23-FE-052",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "56 passed, 0 failed",
    duration: "45.3s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1. Initial sandboxed launch failed with a macOS Chromium MachPort permission error; rerun with approved local process permissions passed.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the synthetic SFTP deposit-link handoff case copies an existing mocked public deposit URL through a controlled clipboard stub, verifies stored links do not expose a password field, and asserts no link mutation, promote, bulk-promote or reconciliation endpoint is called. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level read-only coverage for SFTP external handoff: copying an existing deposit URL remains non-mutating and the stored link list does not re-display a generated password.",
  },
  {
    id: "EXEC-2026-06-23-FE-053",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "57 passed, 0 failed",
    duration: "47.6s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the synthetic SFTP clipboard-denied case forces navigator.clipboard.writeText to reject, verifies a visible Copy failed error, verifies no URL-copied success state or local clipboard value, and asserts no link mutation, promote, bulk-promote or reconciliation endpoint is called. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level error-path coverage for SFTP external handoff: a clipboard permission failure is recoverable and remains non-mutating.",
  },
  {
    id: "EXEC-2026-06-23-FE-054",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "58 passed, 0 failed",
    duration: "45.6s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the synthetic SFTP link-filter/empty-search case uses two mocked deposit links and four synthetic deposit files, selects a secondary link, verifies queue scoping and a no-match empty search, and asserts no promote, bulk-promote or archive-download mutation. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level read-only coverage for SFTP staging queue link filtering and empty search/no files behavior.",
  },
  {
    id: "EXEC-2026-06-23-FE-055",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "59 passed, 0 failed",
    duration: "47.8s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the synthetic SFTP link-lifecycle case creates a mocked deposit link, verifies the generated password appears only in the one-time share panel and not in the stored link list, hides the secret, rotates the stored link, revokes it, and asserts no promote, bulk-promote or reconciliation mutation. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level explicit-lifecycle coverage for SFTP secure-deposit link creation, one-time secret handling, rotation and revocation.",
  },
  {
    id: "EXEC-2026-06-23-FE-056",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "60 passed, 0 failed",
    duration: "48.1s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the synthetic SFTP forbidden-link-management case uses a reviewer-shaped session with mocked 403 responses for create, rotate and revoke, verifies no fake link or one-time password is rendered, verifies the stored link remains active with hidden password state, and asserts no promote, bulk-promote or reconciliation mutation. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level permission-denial coverage for SFTP secure-deposit link management without creating fake credential or staged-file side effects.",
  },
  {
    id: "EXEC-2026-06-23-FE-057",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "61 passed, 0 failed",
    duration: "48.8s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the synthetic SFTP disabled-health direct-route case returns secure-deposit health enabled=false, verifies the disabled warning and disabled create-link form controls, keeps existing link visibility read-only, and asserts no link, promote, bulk-promote or reconciliation mutation. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level disabled-workspace coverage for direct /connectors/sftp access: the page remains read-only and does not mutate link or staging state.",
  },
  {
    id: "EXEC-2026-06-23-FE-058",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "62 passed, 0 failed",
    duration: "49.6s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the synthetic SFTP enabled-health direct-route case returns secure-deposit health enabled=true, verifies the disabled warning is absent, verifies create-link controls are enabled, inspects the component health payload for no password/secret/token/private/credential/session fields, and asserts no link, promote, bulk-promote or reconciliation mutation occurs on page load. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level enabled-workspace health coverage for direct /connectors/sftp access: the page becomes operational without exposing secrets or mutating link/staging state on load.",
  },
  {
    id: "EXEC-2026-06-23-FE-059",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "63 passed, 0 failed",
    duration: "49.5s",
    warnings:
      "Angular dev-server warning unchanged: NG8107 optional-chain warning in mission-room/vp-map-preview. Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1. Follow-up Angular build also passed in 11.772s with existing budget/CommonJS warnings.",
    safetyScope:
      "Local Playwright browser smoke plus local Angular build. Authenticated Andritz cases mock all /api/v1/** calls in-page; the synthetic SFTP indexing-monitor failure case makes /documents/jobs return HTTP 500, verifies a visible non-blocking pipeline error, verifies Analyze current view and Create link remain enabled, and asserts no link, promote, bulk-promote, archive-download or reconciliation mutation occurs. Indexing-assist calls in this case are read-only and carry file_ids=[]. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Verifies the SFTP indexing pipeline failure remediation: jobs polling failures no longer disappear silently and do not block or mutate secure-deposit workflows.",
  },
  {
    id: "EXEC-2026-06-23-FE-060",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "64 passed, 0 failed",
    duration: "50.4s",
    warnings:
      "Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. First sandboxed targeted run failed before app execution because Chromium could not bootstrap the macOS MachPort rendezvous; rerun with approved unsandboxed Playwright launch passed. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the new SFTP reconciliation permission-denial case uses workspace_reviewer, makes /sftp/operations/reconcile return HTTP 403 for a dry-run request, verifies the denial is visible, verifies Run check and Move to quarantine controls recover, and asserts no quarantine, link, promote, bulk-promote or archive-download mutation occurs. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level permission coverage for the SFTP operations monitor: a denied reconciliation check is explicit and recoverable, and the quarantine path is not triggered.",
  },
  {
    id: "EXEC-2026-06-23-FE-061",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "65 passed, 0 failed",
    duration: "50.6s",
    warnings:
      "Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the new SFTP quarantine-confirmation case uses synthetic SFTP operations with a completed dry-run candidate set, clicks Move to quarantine, dismisses the browser confirmation dialog, verifies the safety copy, and asserts no reconciliation/quarantine, promote, bulk-promote or archive-download mutation occurs. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level destructive-safety coverage for the SFTP operations monitor: canceling the quarantine confirmation leaves production-sensitive paths untouched.",
  },
  {
    id: "EXEC-2026-06-23-FE-062",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "66 passed, 0 failed",
    duration: "50.8s",
    warnings:
      "Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the new SFTP operations-monitor failure case makes /sftp/operations return HTTP 500, verifies a visible non-blocking monitor error after initial load and manual Refresh ops, inspects component state for operations=null and loading=false, and asserts no reconcile/quarantine, promote, bulk-promote or archive-download mutation occurs. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level failure visibility coverage for the SFTP operations monitor: an unavailable monitor is explicit and does not trigger production-sensitive workflows.",
  },
  {
    id: "EXEC-2026-06-23-FE-063",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "67 passed, 0 failed",
    duration: "52.9s",
    warnings:
      "Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the new SFTP dry-run reconciliation case makes /sftp/operations/reconcile return a completed dry-run job, verifies the success is visible and /sftp/operations refreshes, and asserts no quarantine, link, promote, bulk-promote or archive-download mutation occurs. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level happy-path coverage for the SFTP Run check action while proving it stays a dry-run and does not touch production-sensitive workflows.",
  },
  {
    id: "EXEC-2026-06-23-FE-064",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "68 passed, 0 failed",
    duration: "51.9s",
    warnings:
      "Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the new SFTP file-download error case clicks Download file for a synthetic received file, makes /sftp/deposits/{id}/download return HTTP 500, verifies the visible recoverable fallback and button recovery, and asserts no reconcile/quarantine, promote, bulk-promote, staging ZIP or archive-member download mutation occurs. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level error-path coverage for SFTP staged-file downloads while proving the failure remains recoverable and isolated from production-sensitive workflows.",
  },
  {
    id: "EXEC-2026-06-23-FE-065",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "69 passed, 0 failed",
    duration: "54.7s",
    warnings:
      "Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the new SFTP staging-ZIP download error case clicks Download ZIP for the synthetic received queue, makes /sftp/deposits/archive return HTTP 500, verifies the visible recoverable fallback and button recovery, and asserts no reconcile/quarantine, promote, bulk-promote, file-download or archive-member download mutation occurs. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level error-path coverage for SFTP staging ZIP downloads while proving the failure remains recoverable and isolated from production-sensitive workflows.",
  },
  {
    id: "EXEC-2026-06-23-FE-066",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "70 passed, 0 failed",
    duration: "53.1s",
    warnings:
      "Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the new Chat document metadata facts case uses a synthetic in-memory text file, intercepts /documents/upload-batch, /documents/{id}/metadata, /contexts and /chat/stream, verifies title/pages/tokens/chunks/keyword chips render, and proves the downstream chat request keeps the ephemeral context. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level happy-path coverage for Chat document metadata facts after drop-and-ask upload, completing the nominal/error/boundary metadata trio.",
  },
  {
    id: "EXEC-2026-06-23-FE-067",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "71 passed, 0 failed",
    duration: "54.7s",
    warnings:
      "Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the new Chat system-scope case supplies a synthetic workspace_chat system, selects it through the visible context picker, verifies the UI switches to System chat, and proves /sessions receives context.system_id while /chat/stream receives agent_id for the selected system. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level happy-path coverage for system-scoped Recherche chat selection and payload propagation.",
  },
  {
    id: "EXEC-2026-06-23-FE-068",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "72 passed, 0 failed",
    duration: "55.6s",
    warnings:
      "Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz case mocks all /api/v1/** calls in-page; the stale Chat system-scope case opens /workspace/andritz/chat with a deleted systemId query param, returns an empty synthetic systems catalogue, verifies the UI falls back to Quick ask, and proves /sessions receives context.system_id=null while /chat/stream receives agent_id=null. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level invalid-input coverage for stale/deleted Recherche system ids and verifies no stale system scope leaks into chat payloads.",
  },
  {
    id: "EXEC-2026-06-23-FE-069",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "73 passed, 0 failed",
    duration: "58.8s",
    warnings:
      "Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the new forbidden Chat system-catalogue case opens /workspace/andritz/chat with a preselected systemId while /systems returns HTTP 403, verifies the UI falls back to Quick ask, and proves /sessions receives context.system_id=null while /chat/stream receives agent_id=null. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level permission/security coverage for unreadable Recherche system catalogues and verifies no forbidden system scope leaks into chat payloads.",
  },
  {
    id: "EXEC-2026-06-23-FE-070",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "74 passed, 0 failed",
    duration: "56.1s",
    warnings:
      "Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the new Chat PDF drop-and-ask case selects a synthetic in-memory PDF, intercepts /documents/upload-batch, /documents/{id}/metadata, /contexts, /sessions and /chat/stream, verifies PDF filename/page/token/chunk facts render, and proves the downstream question uses the ephemeral PDF context. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level happy-path coverage for Chat Recherche PDF drop-and-ask upload before asking while keeping all document ingestion synthetic and isolated.",
  },
  {
    id: "EXEC-2026-06-23-FE-071",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "75 passed, 0 failed",
    duration: "57.2s",
    warnings:
      "Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the new unsupported Chat drop-and-ask file case selects a synthetic in-memory .bin file, intercepts /documents/upload-batch with HTTP 400 and a backend detail, verifies the rejection detail is visible, creates no ephemeral context or attached doc, and proves the next Quick ask uses null context. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level invalid-input coverage for Chat Recherche unsupported drop-and-ask file selection while keeping ingestion synthetic and isolated.",
  },
  {
    id: "EXEC-2026-06-23-FE-072",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "76 passed, 0 failed",
    duration: "59.9s",
    warnings:
      "Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the new large Chat drop-and-ask boundary case selects a synthetic in-memory XLSX-like file, delays the mocked /documents/upload-batch response, verifies the indexing progress remains visible, renders large-document metadata facts, creates an ephemeral context, and proves the downstream question uses that session document. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level boundary/performance coverage for Chat Recherche large drop-and-ask upload responsiveness while keeping ingestion synthetic and isolated.",
  },
  {
    id: "EXEC-2026-06-23-FE-073",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "77 passed, 0 failed",
    duration: "1.1m",
    warnings:
      "Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the new expired drop-and-ask context case uploads a synthetic in-memory text file, creates a mocked ephemeral context, returns HTTP 410 from /contexts/{id}/persist, verifies the persist failure is visible/recoverable, and proves the chat surface can still send a context-scoped question. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level error-path coverage for Chat Recherche expired drop-and-ask context persistence while keeping ingestion synthetic and isolated.",
  },
  {
    id: "EXEC-2026-06-23-FE-074",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "78 passed, 0 failed",
    duration: "1.0m",
    warnings:
      "Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the new no-session-doc Quick ask case sends a question without uploading any file, verifies no upload/context creation request occurs, no session-doc mode control is shown, and proves /sessions plus /chat/stream carry context_id=null and context_mode=null with the selected workspace knowledge scope. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level boundary coverage for Chat Recherche source-scope behavior when no drop-and-ask session documents are attached.",
  },
  {
    id: "EXEC-2026-06-23-FE-075",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "79 passed, 0 failed",
    duration: "1.0m",
    warnings:
      "Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the new long-prompt Quick ask case sends a synthetic near-limit text question without uploading any file, verifies the composer remains usable, and proves /sessions plus /chat/stream carry the full query with context_id=null/context_mode=null and the selected workspace knowledge scope. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level boundary coverage for Chat Recherche long prompt handling while keeping all retrieval and session persistence mocked.",
  },
  {
    id: "EXEC-2026-06-23-FE-076",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "80 passed, 0 failed",
    duration: "1.1m",
    warnings:
      "Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the new slow-stream Quick ask case delays the mocked /chat/stream response, verifies visible in-flight progress and the streaming send state before the final answer renders, and proves the request keeps context_id=null/context_mode=null with the selected workspace knowledge scope. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level performance/UX coverage for Chat Recherche slow retrieval before answer text while keeping retrieval and session persistence mocked.",
  },
  {
    id: "EXEC-2026-06-23-FE-077",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "81 passed, 0 failed",
    duration: "1.1m",
    warnings:
      "Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the new interrupted-stream Quick ask case aborts the mocked /chat/stream request after visible in-flight progress, verifies a recoverable transport error is shown, proves the synthetic success answer is not rendered, and confirms the composer becomes editable again with context_id=null/context_mode=null and the selected workspace knowledge scope. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level error-path coverage for Chat Recherche stream interruption and composer recovery while keeping retrieval and session persistence mocked.",
  },
  {
    id: "EXEC-2026-06-23-FE-078",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "82 passed, 0 failed",
    duration: "1.2m",
    warnings:
      "Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the new auto Deep Search case emits a synthetic deep_queued SSE chunk, polls a mocked /workspace-jobs/job-andritz-deep-1 response, verifies the persistent Deep Search tracker, and proves the completed deep answer/source summary renders without backend calls, real upload, VM mutation, Andritz collection mutation or SFTP production-data mutation.",
    notes:
      "Adds browser-level regression coverage for Chat Recherche auto-deep retrieval orchestration from stream queue to completed synthetic answer.",
  },
  {
    id: "EXEC-2026-06-23-FE-079",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "83 passed, 0 failed",
    duration: "1.2m",
    warnings:
      "Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the new no-plan finalization failure case creates a synthetic capture, posts a written text turn, forces /knowledge-capture/sessions/{id}/closure to return 504, verifies the UI stays on the active session with a recoverable error, and proves no proposal publish request is sent. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level regression coverage for Knowledge Capture no-plan finalization failure recovery without dashboard return or implicit publication.",
  },
  {
    id: "EXEC-2026-06-23-FE-080",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "84 passed, 0 failed",
    duration: "1.3m",
    warnings:
      "Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the new empty no-plan capture case creates a synthetic active free-conversation session without turns, forces /knowledge-capture/sessions/{id}/closure to return proposal=null, verifies the UI stays on the session with a recoverable no-report message, and proves no report or publish request is created. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level boundary coverage for Knowledge Capture empty no-plan finish behavior so an empty capture cannot create a bogus proposal or implicit publication.",
  },
  {
    id: "EXEC-2026-06-23-FE-081",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "85 passed, 0 failed",
    duration: "1.2m",
    warnings:
      "Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the new guided-plan written capture case creates a synthetic plan-build session, validates mocked topics, starts the session in guided/manual mode, submits a typed complement tied to question q-alignment, and proves no real backend call, upload, VM mutation, Andritz collection mutation, SFTP production-data mutation or publish request occurs.",
    notes:
      "Adds browser-level regression coverage for mixed written capture in a planned session so typed notes keep the active plan breadcrumb/question context.",
  },
  {
    id: "EXEC-2026-06-23-FE-082",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium --reporter=line",
    result: "86 passed, 0 failed",
    duration: "1.2m",
    warnings:
      "Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the new guided-plan section-switch written capture case creates a synthetic plan-build session, validates mocked topics, starts the session, switches the active plan rail subtopic, submits a typed complement tied to question q-safety-stop, and proves no real backend call, upload, VM mutation, Andritz collection mutation, SFTP production-data mutation or publish request occurs.",
    notes:
      "Adds browser-level regression coverage for mixed written capture after plan-section switching so typed notes follow the selected plan breadcrumb/question instead of a stale/default section.",
  },
  {
    id: "EXEC-2026-06-23-FE-083",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium --reporter=line",
    result: "87 passed, 0 failed",
    duration: "1.2m",
    warnings:
      "Node v23 FORCE_COLOR/NO_COLOR warnings from local environment. Local run used 127.0.0.1 to reuse the existing dev server and avoid Playwright starting a second localhost server on ::1.",
    safetyScope:
      "Local Playwright browser smoke. Authenticated Andritz cases mock all /api/v1/** calls in-page; the new guided-plan active-document written capture case creates a synthetic plan-build session, validates mocked topics, starts the session, switches the active plan rail subtopic, uploads and previews a synthetic capture document, records page 1 as active view, submits a typed complement tied to question q-safety-stop with document_refs plus visual_context, and proves no real backend call, upload, VM mutation, Andritz collection mutation, SFTP production-data mutation or publish request occurs.",
    notes:
      "Adds browser-level regression coverage for the combined mixed-input contract: guided plan breadcrumb plus active document/page reference on one written capture turn.",
  },
  {
    id: "EXEC-2026-06-23-FE-084",
    date: "2026-06-23",
    command:
      "/Users/thib/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node ./node_modules/@angular/cli/bin/ng.js build",
    result: "Frontend build passed",
    duration: "11.666s",
    warnings:
      "Known Angular build warnings remained unchanged: optional chain NG8107 in mission-room/vp-map-preview.component.ts, initial bundle budget, mission-room CSS budget, drawflow CSS budget, and CommonJS warnings for maplibre-gl/earcut.",
    safetyScope:
      "Local frontend build plus source guard for the Knowledge Capture voice document-reference transport fix. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Verifies voice-session and LiveKit transport serializers now forward document_refs and visual_context from active capture document metadata on audio.frame and audio.endpoint.",
  },
  {
    id: "EXEC-2026-06-23-FE-085",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts e2e/tests/07-voice-transport-contract.spec.ts --project=chromium --reporter=line",
    result: "89 passed, 0 failed",
    duration: "1.3m",
    warnings:
      "Node v23 FORCE_COLOR/NO_COLOR warnings from local environment plus expected CommonJS-to-ESM experimental warning from loading @angular/compiler in the Node-side voice transport contract spec.",
    safetyScope:
      "Local Playwright browser/contract smoke. The Andritz browser cases mock all /api/v1/** calls in-page; the new voice transport contract instantiates WebSocket and LiveKit connection classes with in-memory socket/room stubs and verifies audio.frame/audio.endpoint payloads carry document_refs plus visual_context. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Upgrades the Knowledge Capture voice active-document proof from source guard/build to direct transport assertions for both backend WebSocket and LiveKit fallback, while preserving the full mocked Andritz browser regression suite.",
  },
  {
    id: "EXEC-2026-06-23-FE-086",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts e2e/tests/07-voice-transport-contract.spec.ts --project=chromium --reporter=line",
    result: "90 passed, 0 failed",
    duration: "1.2m",
    warnings:
      "Node v23 FORCE_COLOR/NO_COLOR warnings from local environment plus expected CommonJS-to-ESM experimental warning from loading @angular/compiler in the Node-side voice transport contract spec.",
    safetyScope:
      "Local Playwright browser/contract smoke. The Andritz browser cases mock all /api/v1/** calls in-page; the new active-document page-change case uses a synthetic capture document, simulates the PDF preview pageChange event to page 2, verifies /documents/view records page 2, and confirms the following written turn carries page 2 document_refs plus visual_context. The voice transport contract still uses in-memory WebSocket/LiveKit stubs. No backend calls, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds regression coverage for active capture document page synchronization before a written turn, while preserving the full mocked Andritz browser suite and direct voice transport assertions.",
  },
  {
    id: "EXEC-2026-06-23-FE-087",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts e2e/tests/07-voice-transport-contract.spec.ts e2e/tests/08-voice-capture-contract.spec.ts --project=chromium --reporter=line",
    result: "94 passed, 0 failed",
    duration: "1.2m",
    warnings:
      "Node v23 FORCE_COLOR/NO_COLOR warnings from local environment plus expected CommonJS-to-ESM experimental warning from loading @angular/compiler in the Node-side voice transport/capture contract specs.",
    safetyScope:
      "Local Playwright browser/contract smoke. The Andritz browser cases mock all /api/v1/** calls in-page; voice transport tests use in-memory WebSocket/LiveKit stubs; the new voice capture contract exercises resolveVoiceCaptureConfig plus VoiceLoopController endpoint-candidate scheduling/cancellation/confirmation with a fake recording MediaRecorder. No backend calls, no real microphone, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds regression coverage for robust/manual capture preset resolution, silence endpoint flush, and cancelling a silence endpoint candidate when voice resumes during the grace window.",
  },
  {
    id: "EXEC-2026-06-23-FE-088",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts e2e/tests/07-voice-transport-contract.spec.ts e2e/tests/08-voice-capture-contract.spec.ts --project=chromium --reporter=line",
    result: "95 passed, 0 failed",
    duration: "1.3m",
    warnings:
      "Node v23 FORCE_COLOR/NO_COLOR warnings from local environment plus expected CommonJS-to-ESM experimental warning from loading @angular/compiler in the Node-side voice transport/capture contract specs.",
    safetyScope:
      "Local Playwright browser/contract smoke. The Andritz browser cases mock all /api/v1/** calls in-page; the new late same-turn partial case uses the Angular dev component instance to simulate transcript.partial while recording=false and transcribing=true; voice transport/capture tests are in-memory/fake recorder. No backend calls, no real microphone, no real upload, no VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    notes:
      "Adds browser-level regression coverage that a same-turn transcript.partial remains visible as italic live text during endpoint STT finalization instead of being dropped as stale.",
  },
  {
    id: "EXEC-2026-06-23-BE-011",
    date: "2026-06-23",
    command:
      "cd backend && poetry run pytest app/tests/api/test_documents_collections.py",
    result: "23 passed, 0 failed",
    duration: "1.97s",
    warnings:
      "140 warnings, mostly datetime.utcnow deprecations plus local SWIG deprecation warnings from optional native dependencies.",
    safetyScope:
      "Local backend API tests only. The new clear-documents cases use a fake DocumentService, synthetic workspace/user rows, and tmp_path legacy upload files; no real backend, no VM, no Andritz collection, no SFTP production-data mutation, and no real vector/object store clear.",
    notes:
      "Fixes and verifies global document clear safety: non-admin users are denied, admins must pass confirm=true and matching confirm_collection_name, and the legacy uploads directory is not deleted unless clear_uploads=true is explicitly supplied.",
  },
  {
    id: "EXEC-2026-06-23-BE-012",
    date: "2026-06-23",
    command:
      "cd backend && poetry run pytest app/tests/services/test_secure_deposit.py",
    result: "35 passed, 1 skipped, 0 failed",
    duration: "12.84s",
    warnings:
      "149 warnings, mostly datetime.utcnow deprecations plus local SWIG deprecation warnings from optional native dependencies.",
    safetyScope:
      "Local Secure Deposit service tests only. The new cases use synthetic workspace/link rows, tmp_path secure_deposit storage, and local UploadFile/staged-file fixtures; no real SFTP server, no VM, no Andritz/SFTP production-data mutation, and no real collection mutation.",
    notes:
      "Verifies disabled workspaces block link creation and existing-link authentication, and proves extension allow-lists apply case-insensitively across public upload plus SFTP staging while rejected disallowed files remain unmoved.",
  },
  {
    id: "EXEC-2026-06-23-BE-013",
    date: "2026-06-23",
    command:
      "cd backend && poetry run pytest app/tests/api/test_secure_deposit_api.py app/tests/services/test_secure_deposit.py",
    result: "50 passed, 1 skipped, 0 failed",
    duration: "14.15s",
    warnings:
      "380 warnings, mostly datetime.utcnow/utcfromtimestamp deprecations plus local SWIG deprecation warnings from optional native dependencies.",
    safetyScope:
      "Local Secure Deposit API/service tests only. The new cases use synthetic workspaces, users, memberships, access links, JWT sessions, tmp_path secure_deposit storage, and a fake asyncssh SFTP facade; no real SFTP server, no VM, no Andritz/SFTP production-data mutation, and no real collection mutation.",
    notes:
      "Adds critical access-control coverage: a public deposit session token cannot be reused against another access_id, owner-scoped rotate/revoke makes old credentials fail and revoked links unusable, a non-owner contributor is denied staged-file download by real IAM enforcement, and the SFTP facade rejects read/delete operations as upload-only.",
  },
  {
    id: "EXEC-2026-06-23-BE-014",
    date: "2026-06-23",
    command:
      "cd backend && poetry run pytest app/tests/services/test_expert_review_disable.py app/tests/api/test_knowledge_capture_api.py",
    result: "33 passed, 0 failed",
    duration: "25.14s",
    warnings:
      "4641 warnings, mostly datetime.utcnow deprecations plus local Qdrant/SWIG warnings from optional native dependencies.",
    safetyScope:
      "Local Knowledge Capture backend/API tests only. The new critical cases use synthetic workspace/session/proposal rows and fake publish/DocumentService guards; the broader lot uses test DB, tmp_path and monkeypatch fixtures. No backend network call, no VM, no Andritz collection, no SFTP production-data mutation, and no unintended ingestion/publication side effect.",
    notes:
      "Adds critical publication-safety coverage: review-disabled capture proposal finalization persists accepted status without publication metadata or ingestion, and exporting an accepted proposal returns Markdown while keeping proposal.status=accepted and publication.published_at absent.",
  },
  {
    id: "EXEC-2026-06-23-BE-015",
    date: "2026-06-23",
    command:
      "cd backend && poetry run pytest app/tests/api/test_secure_deposit_api.py app/tests/services/test_secure_deposit.py app/tests/services/test_spl_wave_importer.py app/tests/scripts/test_promote_spl_wave_cli.py",
    result: "71 passed, 1 skipped, 0 failed",
    duration: "14.67s",
    warnings:
      "461 warnings, mostly datetime.utcnow/utcfromtimestamp deprecations plus local SWIG deprecation warnings from optional native dependencies.",
    safetyScope:
      "Local SFTP/Secure Deposit/SPL backend tests only. The new CLI cases use fake SessionLocal/workspace/user/plan objects and monkeypatched build/execute functions; the broader lot uses synthetic database rows and tmp_path fixtures. No Docker, no network, no VM, no real SFTP server, no Andritz/SFTP production-data mutation, and no real collection promotion.",
    notes:
      "Adds explicit SPL promotion safety coverage: promote_spl_wave_v1/v2/v3 default to dry-run when --execute is absent, close their DB session, print the dry-run plan, and do not call copy_collection_documents or execute_* promotion functions.",
  },
  {
    id: "EXEC-2026-06-23-BE-016",
    date: "2026-06-23",
    command:
      "cd backend && poetry run pytest app/tests/api/test_knowledge_capture_api.py app/tests/services/test_expert_review_disable.py app/tests/services/test_knowledge_capture.py",
    result: "139 passed, 0 failed",
    duration: "22.26s",
    warnings:
      "18910 warnings, mostly datetime.utcnow deprecations plus local Qdrant/SWIG warnings from optional native dependencies.",
    safetyScope:
      "Local Knowledge Capture API/service tests only. The new cases use synthetic workspace/user/session/proposal/event rows, IAM-enforced test workspace settings, and monkeypatched permission denials/publish guards. No backend network call, no VM, no real upload, no Andritz collection, no SFTP production-data mutation, and no implicit ingestion/publication side effect.",
    notes:
      "Adds Knowledge Capture permission and accepted-proposal content coverage: contributor proposal listing hides foreign authorless legacy proposals, non-owner contributors cannot open foreign sessions, denied review/delete/amend/flags leave persisted state unchanged, and editing an accepted proposal updates content without publishing.",
  },
  {
    id: "EXEC-2026-06-23-BE-017",
    date: "2026-06-23",
    command:
      "cd backend && poetry run pytest app/tests/api/test_knowledge_guides.py app/tests/api/test_documents_collections.py",
    result: "31 passed, 0 failed",
    duration: "2.45s",
    warnings:
      "201 warnings, mostly datetime.utcnow deprecations plus local SWIG deprecation warnings from optional native dependencies.",
    safetyScope:
      "Local Collections/Knowledge API tests only. The new cases use synthetic workspaces, users, memberships, guide/scope settings, table facts, collection metadata and a fake DocumentService; no backend network call, no VM, no real Andritz collection, no SFTP production-data mutation, and no vector/object-store mutation.",
    notes:
      "Adds Collections permission/scope coverage: non-admin guide create/patch and scope patch requests are denied without mutation, non-admin collection metadata patch is denied without mutation, table-query cannot leak facts from another workspace, and /documents/list remains scoped to the current workspace.",
  },
  {
    id: "EXEC-2026-06-23-FE-089",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://127.0.0.1:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium --reporter=line -g \"renders only current permitted system bindings\"",
    result: "1 passed, 0 failed",
    duration: "1.4s",
    warnings:
      "Node FORCE_COLOR/NO_COLOR warning from the local Playwright environment.",
    safetyScope:
      "Local mocked Playwright browser smoke only. The test intercepts all /api/v1/** calls in-page, returns a synthetic /systems response containing one visible Andritz binding plus one stale old-slug binding, clicks the Knowledge detail Bindings action, and asserts stale plus hidden binding text is absent. No backend call, no VM, no real Andritz collection, no SFTP production-data mutation, and no vector/object-store mutation.",
    notes:
      "Adds Collections UI permission-scope and action coverage proving the Knowledge detail Bindings action switches to the existing Bindings tab, renders only the current collection binding returned by /systems, ignores stale old-slug bindings, and does not expose a hidden system binding.",
  },
  {
    id: "EXEC-2026-06-23-BE-018",
    date: "2026-06-23",
    command:
      "cd backend && poetry run pytest app/tests/api/test_documents_collections.py",
    result: "26 passed, 0 failed",
    duration: "2.32s",
    warnings:
      "155 warnings, mostly datetime.utcnow deprecations plus local SWIG deprecation warnings from optional native dependencies.",
    safetyScope:
      "Local Collections API tests only. The new invalid-pagination case uses a synthetic workspace and collection, verifies FastAPI rejects source_offset/source_limit bounds before returning inventory rows, and performs no backend network call, no VM access, no real Andritz collection mutation, no SFTP production-data mutation, and no vector/object-store mutation.",
    notes:
      "Adds Collections inventory input-validation coverage: negative source_offset and excessive source_limit return 422 and do not load or expose source rows.",
  },
  {
    id: "EXEC-2026-06-23-BE-019",
    date: "2026-06-23",
    command:
      "cd backend && poetry run pytest app/tests/api/test_documents_collections.py",
    result: "27 passed, 0 failed",
    duration: "1.88s",
    warnings:
      "158 warnings, mostly datetime.utcnow deprecations plus local SWIG deprecation warnings from optional native dependencies.",
    safetyScope:
      "Local Collections API tests only. The new empty-collection case uses a synthetic workspace and collection, forces vector diagnostics to be unavailable, and verifies inventory/diagnostics stay zero/empty without backend network call, VM access, real Andritz collection mutation, SFTP production-data mutation, or vector/object-store mutation.",
    notes:
      "Adds Collections empty-state diagnostics coverage: an empty collection returns zero source/document/chunk counts, empty fact states, disabled graph status, and unknown vector drift when the vector service is unavailable.",
  },
  {
    id: "EXEC-2026-06-23-BE-020",
    date: "2026-06-23",
    command:
      "cd backend && poetry run pytest app/tests/api/test_documents_collections.py",
    result: "28 passed, 0 failed",
    duration: "1.96s",
    warnings:
      "159 warnings, mostly datetime.utcnow deprecations plus local SWIG deprecation warnings from optional native dependencies.",
    safetyScope:
      "Local Collections API tests only. The new workspace document-list case uses a synthetic workspace and fake DocumentService, verifies vector fallback listing, pagination and hidden/temp/missing-id filtering, and performs no backend network call, VM access, real Andritz collection mutation, SFTP production-data mutation, or vector/object-store mutation.",
    notes:
      "Adds Collections workspace document-list coverage: /documents/list without a ledger collection passes the current workspace slug to DocumentService, returns valid documents only, and preserves total/offset/limit/has_more pagination metadata.",
  },
  {
    id: "EXEC-2026-06-23-BE-021",
    date: "2026-06-23",
    command:
      "cd backend && poetry run pytest app/tests/api/test_documents_collections.py",
    result: "29 passed, 0 failed",
    duration: "2.01s",
    warnings:
      "167 warnings, mostly datetime.utcnow deprecations plus local SWIG deprecation warnings from optional native dependencies.",
    safetyScope:
      "Local Collections API tests only. The new duplicate-filename upload case uses a synthetic workspace/collection, tmp_path local object store and mocked worker dispatch, verifies same-request duplicate names do not create duplicate ledger rows after the fix, and performs no backend network call, VM access, real Andritz collection mutation, SFTP production-data mutation, or vector/object-store mutation.",
    notes:
      "Adds and verifies duplicate collection-upload filename handling: the same normalized filename in one request is upserted once, object storage has the deterministic last payload, collection document_names remains unique, and inventory stays coherent.",
  },
  {
    id: "EXEC-2026-06-23-BE-022",
    date: "2026-06-23",
    command:
      "cd backend && poetry run pytest app/tests/api/test_documents_collections.py",
    result: "31 passed, 0 failed",
    duration: "2.36s",
    warnings:
      "183 warnings, mostly datetime.utcnow deprecations plus local SWIG deprecation warnings from optional native dependencies.",
    safetyScope:
      "Local Collections API tests only. The new table-facts cases use synthetic workspace, collection and KnowledgeTableFact rows, verify ledger-backed spreadsheet fact metadata plus sheet/query filtering, and perform no backend network call, VM access, real Andritz collection mutation, SFTP production-data mutation, upload, or vector/object-store mutation.",
    notes:
      "Adds Collections structured table-fact coverage: /documents/table-facts returns sheet/cell/value/source metadata from the ledger and filters by sheet_name plus q without leaking stale rows from other sheets or measures.",
  },
  {
    id: "EXEC-2026-06-23-BE-023",
    date: "2026-06-23",
    command:
      "cd backend && poetry run pytest app/tests/api/test_knowledge_guides.py",
    result: "7 passed, 0 failed",
    duration: "0.59s",
    warnings:
      "54 warnings, mostly datetime.utcnow deprecations from SQLAlchemy defaults, knowledge guide audit timestamps and guide versioning helpers.",
    safetyScope:
      "Local Knowledge Guides/Scopes API tests only. The new invalid-scope case uses a synthetic workspace/admin user, preserves the original workspace.settings knowledge_scopes, and monkeypatches chat-system refresh to fail if reached. No backend network call, VM access, real Andritz collection mutation, SFTP production-data mutation, upload, or vector/object-store mutation.",
    notes:
      "Adds Knowledge Scope invalid-input coverage: PATCH /knowledge/scopes rejects an invalid scope key with 422, leaves existing scopes unchanged, and does not refresh chat system defaults.",
  },
  {
    id: "EXEC-2026-06-23-BE-024",
    date: "2026-06-23",
    command:
      "cd backend && poetry run pytest app/tests/api/test_knowledge_guides.py",
    result: "8 passed, 0 failed",
    duration: "0.73s",
    warnings:
      "63 warnings, mostly datetime.utcnow deprecations from SQLAlchemy defaults, knowledge guide audit timestamps and guide versioning helpers.",
    safetyScope:
      "Local Knowledge Guides API tests only. The new draft-to-published guide case uses a synthetic workspace/admin user/collection, proves effective guides ignore drafts then include the published version, and performs no backend network call, VM access, real Andritz collection mutation, SFTP production-data mutation, upload, or vector/object-store mutation.",
    notes:
      "Adds Knowledge Guide publication coverage: creating a draft guide does not affect effective guides, patching it to published creates version 2 with published_at, and effective guide resolution returns the published markdown.",
  },
  {
    id: "EXEC-2026-06-23-BE-025",
    date: "2026-06-23",
    command:
      "cd backend && poetry run pytest app/tests/api/test_documents_collections.py",
    result: "32 passed, 0 failed",
    duration: "2.01s",
    warnings:
      "188 warnings, mostly datetime.utcnow deprecations plus local SWIG deprecation warnings from optional native dependencies.",
    safetyScope:
      "Local Collections API tests only. The new OCR-unavailable case uses a synthetic workspace/collection with a non-OCR document fact, verifies document_ocr_text filtering returns a clean empty result, and performs no backend network call, VM access, real Andritz collection mutation, SFTP production-data mutation, OCR provider call, upload, or vector/object-store mutation.",
    notes:
      "Adds Document/OCR facts empty-state coverage: /documents/document-facts with semantic_type=document_ocr_text returns no items, zero totals, stable pagination metadata and existing by_type context when no OCR layer is present.",
  },
  {
    id: "EXEC-2026-06-23-BE-026",
    date: "2026-06-23",
    command:
      "cd backend && poetry run pytest app/tests/api/test_documents_collections.py",
    result: "33 passed, 0 failed",
    duration: "2.31s",
    warnings:
      "198 warnings, mostly datetime.utcnow deprecations plus local SWIG deprecation warnings from optional native dependencies.",
    safetyScope:
      "Local Collections API tests only. The new batch upload case uses a synthetic workspace/collection, tmp_path local object store and mocked worker dispatch, verifies one job plus source rows for text/CSV/image files, and performs no backend network call, VM access, real Andritz collection mutation, SFTP production-data mutation, OCR provider call, or vector/object-store mutation outside tmp_path.",
    notes:
      "Adds synthetic collection batch-upload coverage: /documents/collections/{id}/documents returns the queued job, stores all originals, updates document_names/document_count, creates one source per uploaded file, and keeps inventory by_kind coherent.",
  },
  {
    id: "EXEC-2026-06-23-BE-027",
    date: "2026-06-23",
    command:
      "cd backend && poetry run pytest app/tests/api/test_documents_collections.py::test_list_documents_caps_large_vector_page_and_rejects_oversized_limit -q",
    result: "1 passed, 0 failed",
    duration: "1.61s",
    warnings:
      "5 warnings, mostly datetime.utcnow deprecations plus local SWIG deprecation warnings from optional native dependencies.",
    safetyScope:
      "Local Collections API test only. The new large document-list case uses a synthetic workspace and fake in-memory DocumentService returning 1505 documents, verifies limit/offset pagination and FastAPI rejection of limit=1001, and performs no backend network call, VM access, real Andritz collection mutation, SFTP production-data mutation, upload, or vector/object-store mutation.",
    notes:
      "Adds large vector document-list coverage: /documents/list can page 1000 items from a larger vector-only result set, preserves total/has_more metadata, and rejects oversized limits before instantiating the document service.",
  },
  {
    id: "EXEC-2026-06-23-BE-028",
    date: "2026-06-23",
    command:
      "cd backend && poetry run pytest app/tests/api/test_documents_collections.py -q",
    result: "36 passed, 0 failed",
    duration: "2.33s",
    warnings:
      "221 warnings, mostly datetime.utcnow deprecations plus local SWIG deprecation warnings from optional native dependencies.",
    safetyScope:
      "Local Collections API tests only. The new existing-collection upload cases use synthetic workspaces/collections, tmp_path local object stores and mocked worker dispatch, verify manifest extension plus same-name requeue cleanup, and perform no backend network call, VM access, real Andritz collection mutation, SFTP production-data mutation, or vector/object-store mutation outside tmp_path.",
    notes:
      "Adds existing-collection upload coverage and verifies the fix for stale source ledger metadata: adding a new file preserves prior sources, while reuploading an existing filename leaves one manifest entry, rewrites the original object, resets chunk_count to 0, clears stale document_id metadata, and queues the source for reindexing.",
  },
  {
    id: "EXEC-2026-06-23-BE-029",
    date: "2026-06-23",
    command:
      "cd backend && poetry run pytest app/tests/api/test_documents_collections.py -q",
    result: "37 passed, 0 failed",
    duration: "2.27s",
    warnings:
      "230 warnings, mostly datetime.utcnow deprecations plus local SWIG deprecation warnings from optional native dependencies.",
    safetyScope:
      "Local Collections API tests only. The new worker-enqueue failure case uses a synthetic workspace/collection, tmp_path local object store and mocked dispatch_worker_job raising RuntimeError, verifies visible API failure plus persisted failed job/errored collection/source ledger, and performs no backend network call, VM access, real Andritz collection mutation, SFTP production-data mutation, or vector/object-store mutation outside tmp_path.",
    notes:
      "Adds existing-collection worker-dispatch failure coverage and verifies the fix for false queued states: dispatch errors now return 503 while persisting job.status=failed, collection.status=error, collection.last_error and traceable original/source rows.",
  },
  {
    id: "EXEC-2026-06-23-BE-030",
    date: "2026-06-23",
    command:
      "cd backend && poetry run pytest app/tests/api/test_documents_collections.py -q",
    result: "38 passed, 0 failed",
    duration: "2.32s",
    warnings:
      "277 warnings, mostly datetime.utcnow deprecations plus local SWIG deprecation warnings from optional native dependencies.",
    safetyScope:
      "Local Collections API tests only. The new large batch case uses a synthetic workspace, /documents/upload-batch, 40 tiny in-memory text files, tmp_path local object store and mocked worker dispatch, and performs no backend network call, VM access, real Andritz collection mutation, SFTP production-data mutation, or vector/object-store mutation outside tmp_path.",
    notes:
      "Adds large synthetic upload-batch coverage: one request creates the target collection, one queued job, 40 traceable source rows/original objects, stable document_names/document_count, and queued per-file response rows without invoking real ingestion.",
  },
  {
    id: "EXEC-2026-06-23-BE-031",
    date: "2026-06-23",
    command:
      "cd backend && poetry run pytest app/tests/api/test_documents_collections.py -q",
    result: "39 passed, 0 failed",
    duration: "2.30s",
    warnings:
      "287 warnings, mostly datetime.utcnow deprecations plus local SWIG deprecation warnings from optional native dependencies.",
    safetyScope:
      "Local Collections API tests only. The new diagnostics failure case uses a synthetic workspace/collection and a fake DocumentService that raises on get_document_count, verifying SQL ledger diagnostics remain visible without backend network call, VM access, real Andritz collection mutation, SFTP production-data mutation, or vector/object-store mutation.",
    notes:
      "Adds diagnostics degradation coverage: /documents/collections/{id}/diagnostics returns 200 when vector diagnostics fail, keeps ledger source/document/chunk counts plus fact coverage visible, and marks vector drift as unknown.",
  },
  {
    id: "EXEC-2026-06-23-BE-032",
    date: "2026-06-23",
    command:
      "cd backend && poetry run pytest app/tests/api/test_documents_collections.py -q",
    result: "41 passed, 0 failed",
    duration: "2.30s",
    warnings:
      "289 warnings, mostly datetime.utcnow deprecations plus local SWIG deprecation warnings from optional native dependencies.",
    safetyScope:
      "Local Collections API tests only. The new unsupported-upload cases use synthetic workspaces, /documents/upload-batch and /documents/upload, one tiny supported text file, tiny unsupported .exe files, tmp_path local object-store settings and dispatch guards, and verify rejection before collection/source/job/original persistence. They perform no backend network call, VM access, real Andritz collection mutation, SFTP production-data mutation, or vector/object-store mutation outside tmp_path.",
    notes:
      "Adds mixed unsupported upload-batch coverage and verifies the new atomic extension guard: unsupported files return 422 with the rejected filename while accepted files are not half-manifested, no worker is dispatched, and no source/original ledger is created. Also verifies single-file /documents/upload preserves the 422 instead of wrapping it as a 500.",
  },
  {
    id: "EXEC-2026-06-23-BE-033",
    date: "2026-06-23",
    command:
      "cd backend && poetry run pytest app/tests/api/test_documents_collections.py -q",
    result: "42 passed, 0 failed",
    duration: "2.55s",
    warnings:
      "652 warnings, mostly datetime.utcnow deprecations plus local SWIG deprecation warnings from optional native dependencies.",
    safetyScope:
      "Local Collections API tests only. The new large collection-list case creates 120 synthetic collection ledger rows in one synthetic workspace plus one separate-workspace row, uses a mocked VectorDBFactory legacy list, and verifies workspace isolation plus legacy de-dup/filter behavior without backend network call, VM access, real Andritz collection mutation, SFTP production-data mutation, upload, or vector/object-store mutation.",
    notes:
      "Adds large workspace collection-list coverage: /documents/collections returns all 120 current-workspace ledger rows in newest-first order, excludes another workspace's collection, filters internal legacy names, de-duplicates legacy names already present in the ledger, preserves default selection, and omits document_names from list items.",
  },
  {
    id: "EXEC-2026-06-23-BE-034",
    date: "2026-06-23",
    command:
      "cd backend && poetry run pytest app/tests/api/test_documents_collections.py -q",
    result: "43 passed, 0 failed",
    duration: "2.45s",
    warnings:
      "662 warnings, mostly datetime.utcnow deprecations plus local SWIG deprecation warnings from optional native dependencies.",
    safetyScope:
      "Local Collections API tests only. The new large retrieval-artifact dry-run case uses one synthetic workspace, a synthetic collection with large document/chunk counters, three synthetic source rows, tmp_path local object-store settings and a dispatch guard that fails if any worker is enqueued. It performs no backend network call, VM access, real Andritz collection mutation, SFTP production-data mutation, worker dispatch, or vector/object-store mutation outside tmp_path.",
    notes:
      "Adds read-only large reindex assessment coverage: POST /documents/collections/{collection}/retrieval-artifact-jobs with qdrant_sparse_reindex dry_run returns a dry_run response, creates no WorkerJob, does not call dispatch_worker_job, preserves collection/source ledger state, and leaves the sentinel original object untouched.",
  },
  {
    id: "EXEC-2026-06-23-FE-090",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "91 passed, 0 failed",
    duration: "1.3m",
    warnings:
      "Node FORCE_COLOR/NO_COLOR warnings from the local Playwright environment.",
    safetyScope:
      "Local mocked Playwright browser smoke only. Authenticated Andritz cases mock all /api/v1/** calls in-page; the new OCR duplicate case injects synthetic /documents/document-facts responses for document_ocr_text and visual_warning, activates the Knowledge detail OCR facet through the mounted Angular component, and verifies duplicate OCR rows render once while the unique warning remains visible. No backend call, no VM, no real Andritz collection, no SFTP production-data mutation, no OCR provider call, and no vector/object-store mutation.",
    notes:
      "Adds Collections OCR duplicate-fact UI coverage: duplicate OCR facts with the same document/page/bounding-box/content are deduped in the Knowledge detail OCR evidence view while total source evidence remains auditable.",
  },
  {
    id: "EXEC-2026-06-23-FE-091",
    date: "2026-06-23",
    command:
      "E2E_BASE_URL=http://localhost:4200 E2E_CHROMIUM_EXECUTABLE=/Users/thib/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell npm run test:e2e -- e2e/tests/06-andritz-mocked-shell.spec.ts --project=chromium",
    result: "92 passed, 0 failed",
    duration: "1.3m",
    warnings:
      "Node FORCE_COLOR/NO_COLOR warnings from the local Playwright environment.",
    safetyScope:
      "Local mocked Playwright browser smoke only. Authenticated Andritz cases mock all /api/v1/** calls in-page; the new connector-catalogue SFTP case clicks the SFTP / Secure Deposit card from /connectors, verifies navigation to /connectors/sftp and asserts no link, promote, bulk-promote or reconciliation mutation request fires. No backend call, no VM, no real SFTP server, no Andritz/SFTP production-data mutation, and no collection/vector/object-store mutation.",
    notes:
      "Adds SFTP catalogue navigation coverage: workspace users can open SFTP from the connectors catalogue, and the navigation path remains read-only until an explicit operator action.",
  },
];

function pass(testId, note, evidenceIndex = 0) {
  const evidence = executionEvidence[evidenceIndex];
  return [
    testId,
    {
      status: "Pass",
      date: evidence.date,
      evidence: evidence.id,
      notes: note,
    },
  ];
}

const executedTestResults = new Map([
  pass("CHT-013-T01", "Mapped to chat correction proposal creation tests with provenance and audio handling."),
  pass("CHT-013-T02", "Mapped to reviewer permission tests for chat correction."),
  pass("CHT-019-T01", "Mapped to LiveKit config/room/token service and API tests."),
  pass("CHT-019-T02", "Mapped to LiveKit agent dispatch fallback/bridge tests."),
  pass("CHT-019-T03", "Mapped to LiveKit webhook authorization rejection tests."),
  pass("KCAP-002-T01", "Mapped to topic-plan/session creation API tests."),
  pass("KCAP-004-T01", "Mapped to free-conversation plan creation API tests."),
  pass("KCAP-004-T02", "Mapped to provided-plan creation API tests."),
  pass("KCAP-004-T03", "Mapped to free-conversation structured proposal API tests."),
  pass("KCAP-004-T04", "Mapped to local Playwright mocked no-plan capture creation smoke proving the browser sends plan_mode=free_conversation and hides the Plan rail.", 23),
  pass("KCAP-019-T01", "Mapped to closure/free-conversation finish structured proposal tests."),
  pass("KCAP-026-T01", "Mapped to POST proposal on free session with material returning structured topic."),
  pass("KCAP-026-T02", "Mapped to closure finish free session returning structured proposal shape."),
  pass("KCAP-027-T01", "Mapped to archive/unarchive capture session API tests."),
  pass("KCAP-028-T01", "Mapped to published-fiches listing API tests; browser filtering remains pending."),
  pass("KCAP-038-T01", "Mapped to proposal listing by session id API tests."),
  pass("COL-001-T01", "Mapped to list collections API tests."),
  pass("COL-001-T02", "Mapped to local Collections API test proving /documents/collections handles 120 synthetic current-workspace ledger rows without leaking other workspaces and de-duplicates/filters legacy vector names.", 123),
  pass("COL-003-T01", "Mapped to collection document upload creating worker job and storing original."),
  pass("COL-003-T03", "Mapped to local Collections API test proving duplicate filenames in one collection upload request are handled deterministically without duplicate ledger rows or inventory corruption.", 111),
  pass("COL-005-T01", "Mapped to collection inventory pagination tests."),
  pass("COL-005-T02", "Mapped to collection inventory filtering/sorting/global aggregate tests."),
  pass("COL-005-T03", "Mapped to local Collections API test proving invalid inventory source_offset/source_limit are rejected with 422 before source rows are returned.", 108),
  pass("COL-006-T01", "Mapped to collection diagnostics coverage tests."),
  pass("COL-006-T02", "Mapped to local Collections API test proving diagnostics returns ledger counts/fact coverage with drift_status=unknown when the vector service raises.", 121),
  pass("COL-006-T03", "Mapped to local Collections API test proving empty collection inventory and diagnostics stay coherent with zero counts, empty fact states and disabled graph status even when vector diagnostics are unavailable.", 109),
  pass("COL-007-T01", "Mapped to document preview/rich-preview resolution tests."),
  pass("COL-008-T01", "Mapped to dense scoped collection search tests."),
  pass("COL-008-T02", "Mapped to search timeout/fallback tests."),
  pass("COL-009-T01", "Mapped to local Collections API test proving /documents/table-facts returns ledger-backed spreadsheet rows with document, sheet, cell, row, unit and value metadata.", 112),
  pass("COL-009-T02", "Mapped to local Collections API test proving /documents/table-facts sheet_name plus q filtering returns only matching ledger facts and excludes stale rows.", 112),
  pass("COL-010-T01", "Mapped to document facts endpoint tests."),
  pass("COL-010-T02", "Mapped to local Playwright mocked Knowledge detail OCR smoke proving duplicate OCR rows render once while distinct visual warnings remain visible.", 125),
  pass("COL-010-T03", "Mapped to local Collections API test proving OCR document-fact filters return a clean empty state when no OCR/visual layer is indexed for a collection.", 115),
  pass("COL-012-T01", "Mapped to retrieval artifact job dry-run/manual queue tests."),
  pass("COL-012-T03", "Mapped to local Collections API test proving a large synthetic qdrant_sparse_reindex dry_run remains read-only: no worker job, no dispatch, no collection/source mutation and no object-store mutation.", 124),
  pass("COL-014-T01", "Mapped to chunks/stats/graph endpoint tests."),
  pass("COL-014-T02", "Mapped to document-scoped chunk listing tests."),
  pass("COL-014-T03", "Mapped to embedding graph bounded sample/no raw vector exposure tests."),
  pass("COL-015-T01", "Mapped to worker job lifecycle/poll-url tests."),
  pass("COL-015-T02", "Mapped to worker ingest error and failed job detail tests."),
  pass("COL-018-T01", "Mapped to local API guardrail tests and code inspection proving the Andritz clear path is not executed during QA; destructive clear requires explicit admin confirmation.", 100),
  pass("COL-018-T02", "Mapped to local API test proving a non-admin workspace member receives 403 and DocumentService.clear_all_documents is never instantiated.", 100),
  pass("COL-018-T03", "Mapped to local API synthetic clear test proving an admin-confirmed request targets only the named synthetic collection and does not delete legacy upload files by default.", 100),
  pass("COL-004-T01", "Mapped to local Playwright mocked document-delete smoke proving no DELETE before explicit confirmation and a scoped /documents/{id}?collection_name=andritz-qa request after confirmation.", 55),
  pass("COL-004-T04", "Mapped to local Playwright mocked collection-delete smoke proving the Delete collection action requires exact typed confirmation and sends only a synthetic /documents/collections/andritz-qa DELETE after confirmation.", 56),
  pass("COL-004-T05", "Mapped to local Playwright mocked forbidden collection-delete smoke proving HTTP 403 surfaces the backend detail and keeps the synthetic collection visible.", 57),
  pass("COL-004-T06", "Mapped to local Playwright mocked forbidden document-delete smoke proving HTTP 403 surfaces the backend detail and keeps the synthetic document visible.", 57),
  pass("COL-007-T02", "Mapped to local Playwright mocked collection-preview-fallback smoke proving /documents/preview/{id} is scoped to andritz-qa and renders the Open file download fallback without real data.", 52),
  pass("COL-007-T03", "Mapped to local Playwright mocked unsafe-collection-preview smoke proving script-like preview content is rendered inertly and does not execute in the Collections preview drawer.", 53),
  pass("COL-007-T04", "Mapped to local Playwright mocked forbidden-collection-preview smoke proving /documents/preview/{id} 403 after a prior successful preview renders a permission error without stale content or download links.", 54),
  pass("COL-023-T01", "Mapped to local Playwright mocked collection-document-inventory smoke proving the Knowledge page opens a successful /documents/list drawer scoped to andritz-qa before any preview/delete action.", 50),
  pass("COL-023-T03", "Mapped to local Playwright mocked empty-collection-inventory smoke proving a successful empty /documents/list response shows Empty collection without load-error or preview/delete actions.", 51),
  pass("COL-002-T01", "Mapped to local Playwright mocked collection-create smoke proving explicit user input posts collection_name=andritz-qa-scratch and the synthetic collection appears after the mocked reload.", 58),
  pass("COL-002-T02", "Mapped to local Playwright mocked collection-create smoke proving the Create action stays disabled while the collection name is blank.", 58),
  pass("COL-002-T03", "Mapped to local Playwright mocked forbidden collection-create smoke proving HTTP 403 surfaces the backend detail and does not create a fake collection card.", 58),
  pass("COL-003-T02", "Mapped to worker ingest materialization error tests preserving document error state without corrupting collection ledger.", 9),
  pass("COL-004-T02", "Mapped to worker ingest deduplication test proving identical content is not duplicated in generated chunks.", 9),
  pass("COL-004-T03", "Mapped to worker ingest materialization-error test proving partial failures are recorded per document.", 9),
  pass("COL-009-T03", "Mapped to delete_collection synthetic API test removing ledger and object-store entries only for the test collection.", 9),
  pass("COL-012-T02", "Mapped to BM25 rebuild worker tests for sidecar rebuild, hard chunk limit skip and artifact staleness envelope behavior.", 9),
  pass("COL-015-T03", "Mapped to worker job listing/filter tests for recent deep retrieval jobs and polling payload boundaries.", 9),
  pass("COL-016-T01", "Mapped to worker ingest finalization test recording SPL wave/deposit ledger completion on synthetic data.", 9),
  pass("COL-016-T02", "Mapped to worker ingest skip-terminal-job and materialization-error tests preserving terminal/error state.", 9),
  pass("COL-011-T03", "Mapped to local Knowledge API test proving a workspace_contributor receives 403 on guide create and guide patch while the existing guide version remains unchanged.", 106),
  pass("COL-011-T02", "Mapped to local Knowledge Guides API test proving draft guides are ignored by effective guide resolution until patched to published, after which the published version becomes effective.", 114),
  pass("COL-016-T03", "Mapped to local Documents API test proving a non-admin workspace member receives 403 on collection metadata patch and name/description remain unchanged.", 106),
  pass("COL-017-T01", "Mapped to local Documents API test proving /documents/list returns current-workspace vector documents with pagination and filters hidden/temp/missing-id rows.", 110),
  pass("COL-017-T02", "Mapped to local Collections API test proving /documents/list pages a large synthetic vector-only document set at limit=1000 and rejects oversized limit=1001 without invoking the service.", 117),
  pass("COL-017-T03", "Mapped to local Documents API test proving /documents/list for a collection slug that exists only in another workspace returns no documents and instantiates the vector fallback with the current workspace slug.", 106),
  pass("COL-019-T01", "Mapped to local Collections API test proving synthetic multi-file collection upload returns a queued job, stores all originals and creates coherent source rows/inventory for every file.", 116),
  pass("COL-019-T02", "Mapped to local Collections API test proving a mixed supported/unsupported /documents/upload-batch request returns a clear 422 before collection/source/job/original persistence or worker dispatch.", 122),
  pass("COL-019-T03", "Mapped to local Collections API test proving /documents/upload-batch handles a 40-file synthetic batch with one job, traceable source rows, original objects and stable manifest counts.", 120),
  pass("COL-020-T01", "Mapped to local Collections API test proving adding a synthetic file to an existing collection extends document_names/source rows without overwriting the prior ready source.", 118),
  pass("COL-020-T02", "Mapped to local Collections API test proving reuploading an existing filename keeps one manifest entry and requeues a clean source row without stale chunk/document metadata.", 118),
  pass("COL-020-T03", "Mapped to local Collections API test proving a worker dispatch failure returns a visible 503 while persisting a failed job, errored collection status, and traceable source/original file.", 119),
  pass("COL-021-T02", "Mapped to local Knowledge Scopes API test proving invalid scope patches are rejected with 422 without mutating existing workspace knowledge_scopes or refreshing chat defaults.", 113),
  pass("COL-021-T03", "Mapped to local Knowledge API test proving a workspace_contributor receives 403 on PATCH /knowledge/scopes and workspace settings remain unchanged.", 106),
  pass("COL-022-T01", "Mapped to local Playwright mocked collection-detail smoke proving the Knowledge detail Bindings action renders the visible system whose flow_definition.collections includes andritz-qa.", 107),
  pass("COL-022-T02", "Mapped to local Playwright mocked collection-detail smoke proving a system that still references an old collection slug is ignored without crashing the collection detail.", 107),
  pass("COL-022-T03", "Mapped to local Playwright mocked collection-detail smoke proving a hidden system binding absent from the permission-scoped /systems response is not rendered in the collection detail.", 107),
  pass("SFTP-002-T01", "Mapped to deposit link password/session authentication tests."),
  pass("SFTP-002-T02", "Mapped to bad password rejection tests."),
  pass("SFTP-006-T01", "Mapped to staged-file preview tests for text/PDF/DOCX/spreadsheet variants."),
  pass("SFTP-006-T02", "Mapped to ZIP archive browsing/member preview/download tests."),
  pass("SFTP-006-T03", "Mapped to ZIP member path traversal rejection tests."),
  pass("SFTP-008-T01", "Mapped to single ZIP/spreadsheet promote queueing worker payload tests."),
  pass("SFTP-008-T03", "Mapped to invalid ZIP/promotion failure preserving received status tests."),
  pass("SFTP-009-T01", "Mapped to bulk promote supported documents using one worker job."),
  pass("SFTP-010-T01", "Mapped to SFTP operations active sidecar upload snapshot tests."),
  pass("SFTP-010-T03", "Mapped to reconciliation dry-run/quarantine safety tests."),
  pass("SFTP-001-T01", "Mapped to secure-deposit link/session service test creating a synthetic link and limiting password reveal/session scope.", 10),
  pass("SFTP-001-T02", "Mapped to local internal/public Secure Deposit API test proving owner-scoped rotate invalidates the old password, the rotated password works, revoke marks the link revoked, and the rotated password then receives 403.", 102),
  pass("SFTP-002-T01", "Mapped to refreshed deposit link password/session authentication tests.", 10),
  pass("SFTP-002-T02", "Mapped to refreshed bad password rejection tests.", 10),
  pass("SFTP-002-T03", "Mapped to local public Secure Deposit API/service tests proving a valid session token for one access_id is rejected with 401 when reused against another access_id.", 102),
  pass("SFTP-004-T01", "Mapped to synthetic SFTP staged upload path recording and safe root alias/longname behavior; no real SFTP server was mutated.", 10),
  pass("SFTP-004-T02", "Mapped to local fake-asyncssh SFTP facade test proving read-open and remove operations are denied because Secure Deposit SFTP is upload-only.", 102),
  pass("SFTP-004-T03", "Mapped to sidecar reconciliation/quarantine tests for interrupted or stale partial uploads in local tmp storage.", 10),
  pass("SFTP-006-T01", "Mapped to refreshed staged-file preview tests for text/PDF/HTML/DOCX/spreadsheet variants.", 10),
  pass("SFTP-006-T02", "Mapped to refreshed ZIP archive folder/member browsing plus member preview/download tests.", 10),
  pass("SFTP-006-T03", "Mapped to refreshed ZIP member path traversal rejection tests.", 10),
  pass("SFTP-007-T01", "Mapped to deposit indexing-assist recommendation and collection summary API test.", 10),
  pass("SFTP-008-T01", "Mapped to refreshed single ZIP/spreadsheet promote queueing worker payload tests on synthetic deposits.", 10),
  pass("SFTP-008-T03", "Mapped to refreshed invalid ZIP/path traversal/too-many-supported-files promotion safety tests preserving source state.", 10),
  pass("SFTP-009-T01", "Mapped to refreshed bulk promote supported documents using one worker job on synthetic deposits.", 10),
  pass("SFTP-010-T01", "Mapped to refreshed SFTP operations active sidecar upload snapshot tests.", 10),
  pass("SFTP-010-T03", "Mapped to refreshed reconciliation dry-run/quarantine safety tests with explicit local fixture mutation only.", 10),
  pass("SFTP-011-T01", "Mapped to deposit archive creation and ZIP member preview/download tests with safe synthetic files.", 10),
  pass("SFTP-011-T02", "Mapped to local internal Secure Deposit API test proving a contributor who does not own the link receives 403 on staged-file download under real IAM enforcement.", 102),
  pass("SFTP-012-T01", "Mapped to SPL wave dry-run planning tests for synthetic deposits and archive groups.", 10),
  pass("SFTP-012-T02", "Mapped to SPL wave archive/document limit tests isolating large archives and bounded member reads.", 10),
  pass("SFTP-012-T03", "Mapped to local CLI guard tests proving SPL promotion scripts require explicit --execute before any copy/execute mutation path can run.", 104),
  pass("SFTP-013-T01", "Mapped to promote payload tests proving selected collection slug is carried into worker queueing.", 10),
  pass("SFTP-014-T01", "Mapped to full local Secure Deposit service execution proving enabled Andritz-style workspaces keep link/session behavior working while disabled workspaces are denied.", 101),
  pass("SFTP-014-T02", "Mapped to local service tests proving a disabled workspace blocks both new link creation and authentication of an existing synthetic link.", 101),
  pass("SFTP-014-T03", "Mapped to local service tests proving PDF allow-lists are case-insensitive for both public UploadFile and SFTP staged paths, while .EXE is rejected and left unmoved.", 101),
  pass("SFTP-018-T01", "Mapped to local mocked Playwright connector-catalogue smoke proving the SFTP card opens /connectors/sftp without link/promote/bulk-promote/reconcile mutations.", 126),
  pass("SFTP-018-T04", "Mapped to fixed navigation i18n guard parsing navigation.catalog.ts, checking 26 catalog keys and proving nav.connectors exists in FR/EN dictionaries.", 11),
  pass("CHT-001-T04", "Mapped to local Playwright mocked Andritz route smoke opening /chat without real backend data.", 12),
  pass("KCAP-001-T04", "Mapped to local Playwright mocked Andritz route smoke opening /knowledge/capture with empty dashboard/fiches data.", 12),
  pass("COL-001-T04", "Mapped to local Playwright mocked Andritz route smoke opening /knowledge with a synthetic collection payload.", 12),
  pass("SFTP-018-T05", "Mapped to local Playwright mocked Andritz route smoke opening /connectors and /connectors/sftp with synthetic secure-deposit health/queue data.", 12),
  pass("CHT-001-T03", "Mapped to local Playwright mocked Andritz mobile viewport smoke opening /chat.", 13),
  pass("CHT-001-T02", "Mapped to local Playwright no-token guard smoke proving /chat redirects to /auth/signin with redirectURL preserved.", 17),
  pass("KCAP-001-T05", "Mapped to local Playwright mocked Andritz mobile viewport smoke opening /knowledge/capture.", 13),
  pass("COL-001-T05", "Mapped to local Playwright mocked Andritz mobile viewport smoke opening /knowledge.", 13),
  pass("SFTP-018-T06", "Mapped to local Playwright mocked Andritz mobile viewport smoke opening /connectors and /connectors/sftp.", 13),
  pass("KCAP-001-T08", "Mapped to local Playwright no-token guard smoke proving /knowledge/capture redirects to /auth/signin with redirectURL preserved.", 17),
  pass("COL-001-T06", "Mapped to local Playwright no-token guard smoke proving /knowledge redirects to /auth/signin with redirectURL preserved.", 17),
  pass("COL-001-T03", "Mapped to local Playwright mocked 500 response for /documents/collections proving the Knowledge page shows an error/retry state, disables create/upload mutation buttons and exposes no collection-card destructive action.", 18),
  pass("COL-023-T02", "Mapped to local Playwright mocked 500 response for /documents/list proving the Knowledge page browse drawer shows an error/retry state and exposes no document delete action.", 19),
  pass("COL-008-T04", "Mapped to local Playwright mocked 500 response for /documents/search proving the Knowledge search drawer shows an inline error and no stale result row.", 20),
  pass("COL-008-T05", "Mapped to local Playwright search context-reset smoke proving a new Knowledge search context opens with an empty query and no stale result/error state.", 21),
  pass("SFTP-018-T07", "Mapped to local Playwright no-token guard smoke proving /connectors/sftp redirects to /auth/signin with redirectURL preserved.", 17),
  pass("SFTP-018-T02", "Mapped to local Playwright disabled connector-settings smoke proving the SFTP card remains ready but not configured/Config saved.", 17),
  pass("SFTP-005-T01", "Mapped to local Playwright mocked SFTP staging queue smoke proving synthetic deposit files load into received-status queue counters, component search/filter state resolves a promoted file, and no promote/bulk-promote/archive-download endpoint is called.", 59),
  pass("SFTP-006-T04", "Mapped to local Playwright mocked SFTP preview/archive smoke proving a synthetic staged file and ZIP member render in the drawer without promote/bulk-promote/download calls.", 61),
  pass("SFTP-007-T03", "Mapped to local Playwright mocked SFTP indexing-assist smoke proving advisory recommendations appear for a synthetic received file and no promote/bulk-promote/archive-download endpoint is called.", 60),
  pass("SFTP-010-T01", "Mapped to local Playwright mocked SFTP operations smoke proving a live upload snapshot, last received file, and dry-run reconciliation summary render without calling reconcile/quarantine.", 60),
  pass("SFTP-016-T01", "Mapped to local Playwright mocked SFTP indexing monitor smoke proving the target collection running job state is visible alongside indexing-assist output.", 60),
  pass("SFTP-013-T02", "Mapped to local Playwright mocked SFTP target-collection smoke proving an alternate selected collection_slug is sent to indexing assist without promote/bulk-promote/archive-download calls.", 62),
  pass("SFTP-017-T01", "Mapped to local Playwright mocked SFTP deposit-link handoff smoke proving Copy URL writes the existing public deposit URL to clipboard without backend mutation.", 63),
  pass("SFTP-017-T02", "Mapped to local Playwright mocked SFTP deposit-link handoff smoke proving the stored link list does not expose a generated password after load.", 63),
  pass("SFTP-017-T03", "Mapped to local Playwright mocked SFTP clipboard-denied smoke proving a failed Copy URL action shows Copy failed without mutating links or staging data.", 64),
  pass("SFTP-005-T03", "Mapped to local Playwright mocked SFTP link-filter/empty-search smoke proving a no-match search renders an empty state without losing selected-link scope or mutating files.", 65),
  pass("SFTP-005-T04", "Mapped to local Playwright mocked SFTP link-filter smoke proving queue state is scoped to the selected deposit link without promote/bulk-promote/archive-download calls.", 65),
  pass("SFTP-001-T04", "Mapped to local Playwright mocked SFTP link-lifecycle smoke proving create, hide one-time secret, rotate and revoke are explicit link mutations while stored passwords remain hidden and no staged-file mutation occurs.", 66),
  pass("SFTP-001-T03", "Mapped to local Playwright mocked SFTP forbidden-link-management smoke proving create, rotate and revoke 403 responses show recoverable errors, do not create fake credential/link state, keep the stored link active, and avoid staged-file mutations.", 67),
  pass("SFTP-015-T02", "Mapped to local Playwright mocked SFTP disabled-health direct-route smoke proving /connectors/sftp shows disabled state, disables create-link controls, keeps link visibility read-only and sends no mutation.", 68),
  pass("SFTP-018-T03", "Mapped to local Playwright mocked SFTP direct-route disabled-health smoke proving direct page access remains non-mutating when secure deposit is disabled in workspace settings.", 68),
  pass("SFTP-015-T01", "Mapped to local Playwright mocked SFTP enabled-health direct-route smoke proving /connectors/sftp receives enabled health, removes the disabled warning, enables create-link controls and sends no mutation on load.", 69),
  pass("SFTP-015-T03", "Mapped to local Playwright mocked SFTP enabled-health direct-route smoke inspecting the health payload and proving no password/secret/token/private/credential/session keys are exposed.", 69),
  pass("SFTP-016-T02", "Mapped to local Playwright mocked SFTP indexing-monitor failure smoke proving /documents/jobs 500 surfaces a visible non-blocking pipeline error while keeping controls usable and avoiding link/promote/bulk/reconcile mutations.", 70),
  pass("SFTP-010-T02", "Mapped to local Playwright mocked SFTP reconciliation permission-denial smoke proving a reviewer receives a visible 403 error, controls recover, and no quarantine/promote/bulk/archive mutation occurs.", 71),
  pass("SFTP-010-T04", "Mapped to local Playwright mocked SFTP quarantine-confirmation smoke proving dismissing the confirmation dialog sends no reconcile/quarantine, promote, bulk or archive mutation.", 72),
  pass("SFTP-010-T05", "Mapped to local Playwright mocked SFTP operations-monitor failure smoke proving /sftp/operations 500 remains visible, loading clears, and no reconcile/quarantine/promote/bulk/archive mutation occurs.", 73),
  pass("SFTP-010-T06", "Mapped to local Playwright mocked SFTP reconciliation dry-run smoke proving Run check sends only mode=dry_run, refreshes operations, and sends no quarantine/link/promote/bulk/archive mutation.", 74),
  pass("SFTP-011-T04", "Mapped to local Playwright mocked SFTP file-download failure smoke proving a failed Download file action shows a recoverable fallback, re-enables controls, and sends no reconcile/promote/bulk/archive mutation.", 75),
  pass("SFTP-011-T05", "Mapped to local Playwright mocked SFTP staging-ZIP failure smoke proving a failed Download ZIP action shows a recoverable fallback, re-enables controls, and sends no reconcile/promote/bulk/file/archive-member mutation.", 76),
  pass("KCAP-001-T03", "Mapped to IAM engine tests proving reviewer capture permissions are explicit while non-owner operations remain denied.", 14),
  pass("KCAP-002-T04", "Mapped to IAM-enforced Knowledge Capture API test where a workspace_reviewer creates and starts a free-conversation capture session.", 14),
  pass("KCAP-001-T06", "Mapped to /iam/matrix API test proving workspace_reviewer receives capture_session create plus owner-scoped update/execute as allowed_for_subject.", 15),
  pass("KCAP-001-T07", "Mapped to local Playwright mocked reviewer IAM matrix smoke proving the New/Nouvelle capture action is enabled on /knowledge/capture.", 16),
  pass("CHT-001-T01", "Mapped to local Playwright mocked route smoke opening /chat and proving the Recherche shell/chat panel render without contacting real backend data.", 12),
  pass("CHT-002-T01", "Mapped to chat stream hardening happy-path answer tests.", 2),
  pass("CHT-002-T02", "Mapped to controlled chat stream timeout/error tests.", 2),
  pass("CHT-002-T03", "Mapped to local Playwright mocked long-prompt smoke proving Quick ask sends the complete synthetic prompt with null session-doc context while the UI remains usable.", 86),
  pass("CHT-002-T04", "Mapped to local Playwright mocked Recherche quick-ask SSE smoke proving the stream payload, answer rendering and source panel are visible without real backend data.", 24),
  pass("CHT-003-T01", "Mapped to local Playwright mocked Recherche system-scope smoke proving a selected workspace_chat system switches the UI to System chat and sends system_id/agent_id in session and stream payloads.", 78),
  pass("CHT-003-T02", "Mapped to local Playwright mocked stale-system smoke proving a deleted preselected systemId falls back to Quick ask and sends null system_id/agent_id instead of leaking the stale scope.", 79),
  pass("CHT-003-T03", "Mapped to local Playwright mocked forbidden-system-catalogue smoke proving /systems 403 falls back to Quick ask and sends null system_id/agent_id instead of leaking an unreadable system scope.", 80),
  pass("CHT-004-T01", "Mapped to local Playwright mocked PDF drop-and-ask smoke proving a synthetic PDF upload creates an ephemeral context, renders PDF metadata facts, and sends the next chat turn with context_id/context_mode=replace.", 81),
  pass("CHT-004-T02", "Mapped to local Playwright mocked unsupported-file smoke proving a backend 400 rejection detail is shown, no ephemeral context/session doc is created and the next Quick ask uses null context.", 82),
  pass("CHT-004-T03", "Mapped to local Playwright mocked large-file boundary smoke proving delayed upload progress stays visible, large-document metadata renders and the next chat turn uses the ephemeral session-doc context.", 83),
  pass("CHT-004-T04", "Mapped to local Playwright mocked disabled-upload smoke proving features.chat_document_upload=false hides file controls, emits no upload request and keeps Quick ask usable.", 27),
  pass("CHT-004-T05", "Mapped to local Playwright mocked upload-failure smoke proving a failed /documents/upload-batch shows a recoverable error, creates no context/session doc and leaves Quick ask usable with null context.", 30),
  pass("CHT-004-T06", "Mapped to local Playwright mocked partial-upload smoke proving failed upload rows are excluded from session docs and ephemeral context data_refs while the partial-failure warning remains visible.", 31),
  pass("CHT-005-T01", "Mapped to local Playwright mocked persist-context smoke proving an uploaded synthetic session doc creates an ephemeral context, then an explicit Persist click promotes it and shows success.", 28),
  pass("CHT-005-T02", "Mapped to local Playwright mocked expired-persist smoke proving an HTTP 410 persist rejection is visible/recoverable and the current chat remains usable with its session-doc context.", 84),
  pass("CHT-005-T03", "Mapped to local Playwright mocked persist-failure smoke using a 403 permission-denied response, proving no success is shown and the Persist action remains recoverable.", 29),
  pass("CHT-005-T04", "Mapped to local Playwright mocked persist-context smoke proving drop-and-ask persistence calls /contexts/{id}/persist only after the explicit Persist click.", 28),
  pass("CHT-005-T05", "Mapped to local Playwright mocked persist-failure smoke proving a /contexts/{id}/persist failure shows a recoverable error, re-enables Persist and sends no duplicate request.", 29),
  pass("CHT-006-T01", "Mapped to selected context collection stream tests.", 2),
  pass("CHT-006-T02", "Mapped to local Playwright mocked no-session-doc Quick ask smoke proving no upload/context request occurs and /sessions plus /chat/stream keep context_id/context_mode null while preserving workspace knowledge scope.", 85),
  pass("CHT-006-T04", "Mapped to local Playwright mocked drop-and-ask combine-mode smoke proving a synthetic session doc creates an ephemeral context and /chat/stream carries context_id, context_mode=combine, knowledge_scope and include_sources without real upload.", 25),
  pass("CHT-006-T05", "Mapped to local Playwright mocked drop-and-ask Only-mode smoke proving a synthetic session doc keeps /chat/stream scoped to context_mode=replace with knowledge_scope=null and no real upload.", 26),
  pass("CHT-006-T06", "Mapped to local Playwright mocked source-mode toggle smoke proving returning from + Sources to Only sends context_mode=replace and knowledge_scope=null.", 34),
  pass("CHT-006-T07", "Mapped to local Playwright mocked session-doc detach smoke proving removing the last doc patches data_refs=[] and sends the next chat with context_id/context_mode null.", 35),
  pass("CHT-006-T08", "Mapped to local Playwright mocked detach PATCH failure smoke proving the doc remains attached and the next chat keeps context_id/context_mode.", 36),
  pass("CHT-006-T09", "Mapped to local Playwright mocked multi-doc detach smoke proving removing one session doc keeps the remaining filename in data_refs and preserves context_id/context_mode.", 37),
  pass("CHT-006-T10", "Mapped to local Playwright mocked recreate-after-final-detach smoke proving a later upload creates a fresh context payload with only the new filename.", 38),
  pass("CHT-006-T11", "Mapped to local Playwright mocked context-create failure smoke proving failed ephemeral context creation removes the doc from session UI and the next chat has null context_id/context_mode.", 39),
  pass("CHT-006-T12", "Mapped to local Playwright mocked append PATCH failure smoke proving a failed second upload is rolled back while the first session doc and context scope remain active.", 40),
  pass("CHT-007-T01", "Mapped to stable SSE retrieval/text/final lifecycle tests.", 2),
  pass("CHT-007-T02", "Mapped to local Playwright mocked interrupted-stream smoke proving a recoverable transport error is visible, the synthetic success answer is not rendered, and the composer becomes editable again.", 88),
  pass("CHT-007-T03", "Mapped to local Playwright mocked slow-stream smoke proving visible in-flight progress and streaming send state remain present before a delayed /chat/stream response finalizes.", 87),
  pass("CHT-008-T01", "Mapped to local Playwright mocked source-preview smoke proving a cited source opens /documents/{id}/rich-preview with collection_name/filename scope and renders highlighted preview content.", 41),
  pass("CHT-008-T02", "Mapped to local Playwright mocked unavailable-source-preview smoke proving a failed /documents/{id}/rich-preview request renders a recoverable error and leaves chat usable.", 42),
  pass("CHT-008-T03", "Mapped to local Playwright mocked forbidden-source-preview smoke proving a denied /documents/{id}/rich-preview request renders a permission error without leaking preview content.", 43),
  pass("CHT-009-T01", "Mapped to deep retrieval job queueing and auto fast refinement tests.", 2),
  pass("CHT-009-T02", "Mapped to worker dispatch queue-only/deep retrieval failure-path tests.", 2),
  pass("CHT-009-T03", "Mapped to auto-deep degraded retrieval and explicit filter merge tests.", 2),
  pass("CHT-009-T04", "Mapped to local Playwright mocked auto-deep smoke proving deep_queued SSE creates a persistent tracker, polls /workspace-jobs, and promotes the completed deep answer/source summary without real backend data.", 89),
  pass("CHT-014-T01", "Mapped to chat sessions list/detail/history tests.", 2),
  pass("CHT-014-T02", "Mapped to cross-user/private session access and admin audit tests.", 2),
  pass("CHT-014-T03", "Mapped to archive/delete session API visibility tests.", 2),
  pass("CHT-015-T01", "Mapped to workspace chat system/source policy seed and resolver tests.", 2),
  pass("CHT-015-T02", "Mapped to missing/settings inheritance and sync-only-present policy tests.", 2),
  pass("CHT-016-T01", "Mapped to non-streaming completion degraded metadata and normal completion hardening tests.", 2),
  pass("CHT-016-T02", "Mapped to completion degraded retrieval fallback and timeout/deep queue behavior tests.", 2),
  pass("CHT-016-T03", "Mapped to unknown/inaccessible context controlled-error tests.", 2),
  pass("CHT-020-T01", "Mapped to local Playwright mocked document-metadata facts smoke proving an uploaded session document renders title, page/token/chunk counts and keyword chips while preserving context-scoped chat.", 77),
  pass("CHT-020-T02", "Mapped to local Playwright mocked document-metadata 404 smoke proving the upload row falls back to filename display, clears loading state and keeps the ephemeral context usable for chat.", 32),
  pass("CHT-020-T03", "Mapped to local Playwright mocked long-keyword metadata smoke proving only four keyword chips render, later keywords stay hidden and context-scoped chat still works.", 33),
  pass("KCAP-009-T01", "Mapped to voice runtime provider resolution/catalog tests; live audio remains pending.", 2),
  pass("KCAP-009-T02", "Mapped to unsupported provider/fallback capability tests.", 2),
  pass("COL-008-T03", "Mapped to retrieval scope isolation and dense/scoped guardrail tests.", 2),
  pass("COL-011-T01", "Mapped to knowledge guide policy parsing/query variant tests.", 2),
  pass("COL-021-T01", "Mapped to knowledge scope inclusion/default resolution service tests.", 2),
  pass("CHT-006-T03", "Mapped to retrieval profile scope/session-context combination tests; browser drop-and-ask payload inspection is covered separately by CHT-006-T04.", 4),
  pass("CHT-010-T01", "Mapped to corpus planner/retrieval profile tests for selected strategy and scoped sources.", 4),
  pass("CHT-010-T02", "Mapped to retrieval profile normalization/clamping tests for auto/invalid-like UI settings.", 4),
  pass("KCAP-013-T01", "Mapped to retrieve_rag_context service tests returning chunks/context with profile metadata; capture UI remains pending.", 4),
  pass("KCAP-013-T02", "Mapped to shared latency deadline and fast retrieval budget tests; oracle UI timeout behavior remains pending.", 4),
  pass("COL-013-T01", "Mapped to table/document fact retrieval path tests with scoped exact facts and sources.", 4),
  pass("COL-013-T02", "Mapped to no/weak-match retrieval-policy tests that avoid hallucinated fact promotion.", 4),
  pass("COL-013-T03", "Mapped to local table-query API test proving a requested collection slug with facts only in another workspace returns no evidence and no hidden source content.", 106),
  pass("KCAP-039-T01", "Mapped to free-conversation API conversation-step test recording an answer turn, conversation_intent_detected event, and closure sheet state.", 5),
  pass("KCAP-039-T03", "Mapped to conversation-step permission tests confirming review/ingestion permission checks and 403 denial leaves proposal pending.", 5),
  pass("KCAP-015-T01", "Mapped to capture document upload API test queuing one PDF and one PNG in a capture-specific collection without interrupting capture state.", 7),
  pass("KCAP-015-T03", "Mapped to local Playwright mocked unsupported-capture-document smoke proving backend rejection detail is shown and no fake document state is created.", 48),
  pass("KCAP-015-T04", "Mapped to local Playwright mocked capture-document-upload-failure smoke proving failed upload shows a recoverable warning, creates no fake document/preview/view, and keeps written capture usable without document_refs.", 45),
  pass("KCAP-016-T01", "Mapped to capture document view API test recording active page/view metadata and returning it through the documents list endpoint.", 6),
  pass("KCAP-016-T03", "Mapped to local Playwright mocked capture-document-preview-unavailable smoke proving preview 404 shows a recoverable drawer error and capture text remains usable.", 49),
  pass("KCAP-016-T04", "Mapped to local Playwright mocked written-note-active-document smoke proving the capture document preview is scoped, /documents/view records page 1, and /turns carries document_refs plus visual_context without real upload.", 44),
  pass("KCAP-016-T05", "Mapped to local Playwright mocked capture-document-view-logging-failure smoke proving failed /documents/view does not block a written turn with optimistic document_refs.", 47),
  pass("KCAP-017-T02", "Mapped to typed capture turn API test preserving document_refs and visual_context for an active slide.", 6),
  pass("KCAP-017-T04", "Mapped to local Playwright mocked multi-document active-view smoke proving a written note after switching documents references only the latest active document.", 46),
  pass("KCAP-017-T05", "Mapped to local Playwright mocked guided-plan active-document written capture smoke proving a typed complement keeps question_id=q-safety-stop while carrying document_refs and visual_context for the active document page.", 94),
  pass("KCAP-017-T06", "Mapped to local Playwright voice transport contract proving audio.frame/audio.endpoint carry active document_refs plus visual_context over both backend WebSocket and LiveKit fallback paths, with the full mocked Andritz browser suite rerun in the same lot.", 96),
  pass("KCAP-017-T07", "Mapped to local Playwright mocked active-document page-change smoke proving a written note after moving the capture PDF preview from page 1 to page 2 sends page 2 in /documents/view, document_refs and visual_context.", 97),
  pass("KCAP-005-T01", "Mapped to plan-build dialogue service tests that create grounded topics, preserve dialogue-built plan topics, finalize, generate question bank, and start the session.", 8),
  pass("KCAP-005-T03", "Mapped to plan-build validation/readiness tests proving topics are required/validated before the capture start path.", 8),
  pass("KCAP-006-T01", "Mapped to topic plan edit/approval and topic validation service tests.", 8),
  pass("KCAP-006-T02", "Mapped to topic validation/normalization tests for missing or invalid topic structures.", 8),
  pass("KCAP-008-T01", "Mapped to written capture turn service test preserving document context while staying off the STT path.", 8),
  pass("KCAP-008-T04", "Mapped to local Playwright mocked guided-plan written note smoke proving a typed complement keeps question_id=q-alignment and the active plan context while staying off real backend/data paths.", 92),
  pass("KCAP-008-T05", "Mapped to local Playwright mocked guided-plan section-switch written note smoke proving a typed complement follows the selected plan section question_id=q-safety-stop instead of the default q-alignment.", 93),
  pass("KCAP-011-T01", "Mapped to local Playwright voice capture contract proving a silence endpoint candidate flushes recorder data and confirms an endpoint without a real microphone.", 98),
  pass("KCAP-011-T02", "Mapped to local Playwright voice capture contract proving resumed voice during endpoint grace cancels the silence candidate and does not stop the current turn.", 98),
  pass("KCAP-012-T01", "Mapped to VoiceSessionGateway partial-then-final tests with live transcript.partial and reused partial finalization.", 8),
  pass("KCAP-012-T02", "Mapped to local Playwright mocked Knowledge Capture late-partial smoke proving a transcript.partial with the current turn_id still renders as italic live text while recording=false and transcribing=true.", 99),
  pass("KCAP-012-T03", "Mapped to partial_stt and endpoint_stt runtime metric tests for empty partials, provider/reused_partial source, and separated endpoint_stt_ms.", 8),
  pass("KCAP-013-T03", "Mapped to free-conversation weak-evidence prefetch test proving retrieval remains passive and does not push grounded questions/hints.", 8),
  pass("KCAP-014-T01", "Mapped to live grounded question generation tests proving oracle.questions is emitted after text.final with kb grounding.", 8),
  pass("KCAP-014-T02", "Mapped to live questions retrieval-timeout test proving no grounded question is emitted without completed evidence.", 8),
  pass("KCAP-014-T03", "Mapped to oracle question status persistence tests and quality backlog suppression when questions are dismissed/deferred.", 8),
  pass("KCAP-018-T01", "Mapped to section.finish/finalize_capture_section and gateway section-finish tests that synthesize a planned section without losing transcript state.", 8),
  pass("KCAP-019-T03", "Mapped to local Playwright mocked empty no-plan finish smoke proving proposal=null stays in the active capture surface, shows a recoverable no-report message, and sends no publish request.", 91),
  pass("KCAP-019-T04", "Mapped to local Playwright mocked no-plan finalization-failure smoke proving a failed closure/finalization request stays on the active capture session, shows a recoverable error, preserves the written turn payload, and sends no publish request.", 90),
  pass("KCAP-020-T01", "Mapped to finalize_capture service tests building proposal plan_structure and section synthesis.", 8),
  pass("KCAP-020-T03", "Mapped to concurrent/failure-tolerant finalization tests proving multi-section synthesis continues when one section reformulation fails.", 8),
  pass("KCAP-021-T01", "Mapped to free-conversation finalization and pseudo-section synthesis tests producing a structured report topic.", 8),
  pass("KCAP-021-T03", "Mapped to malformed/no-topic structure fallback tests that materialize a session pseudo-topic from facts/synthesis.", 8),
  pass("KCAP-022-T01", "Mapped to report instruction service test updating current report markdown and recommended ingestion without publishing.", 8),
  pass("KCAP-023-T01", "Mapped to answer_proposal_open_question service test resynthesizing only the targeted section and marking the question answered.", 8),
  pass("KCAP-023-T02", "Mapped to open-question status tests for defer/restore/invalidate with proposal metrics and audit events.", 8),
  pass("KCAP-024-T01", "Mapped to capture plan turn/review proposal service tests that accept a proposal through review state.", 8),
  pass("KCAP-024-T02", "Mapped to local Knowledge Capture API denial test proving review_decide=403 leaves proposal.status=pending_review with no reviewer/reviewed_at mutation.", 105),
  pass("KCAP-024-T03", "Mapped to local Knowledge Capture review-disabled regression test proving the proposal response and persisted row become accepted while ingestion is not called and publication.published_at remains absent.", 103),
  pass("KCAP-025-T01", "Mapped to publish_proposal_to_knowledge service tests that publish an accepted proposal and persist export URLs.", 8),
  pass("KCAP-025-T01", "Mapped to local Playwright mocked accepted-proposal flow proving the Publish step requires an explicit final click before /publish is called.", 22),
  pass("KCAP-025-T02", "Mapped to local Playwright mocked accepted-proposal flow proving opening Review and Continue to publication do not send /publish.", 22),
  pass("KCAP-025-T03", "Mapped to capture-document publication promotion tests rewriting report sources to the publication collection.", 8),
  pass("KCAP-029-T01", "Mapped to defer voice/quality-item and oracle backlog status tests.", 8),
  pass("KCAP-030-T01", "Mapped to amend_capture_event service test proving effective transcript text changes are auditable.", 8),
  pass("KCAP-030-T02", "Mapped to local Knowledge Capture API denial test proving a forbidden event amendment leaves event text/status and session transcript unchanged.", 105),
  pass("KCAP-030-T03", "Mapped to amendment-before-proposal test proving generated proposal facts use amended text instead of raw transcript.", 8),
  pass("KCAP-031-T01", "Mapped to capture session flags service test toggling suppress_oracle_questions without transcript mutation.", 8),
  pass("KCAP-031-T03", "Mapped to local Knowledge Capture API denial test proving forbidden session flag updates leave metrics unchanged.", 105),
  pass("KCAP-032-T01", "Mapped to plan-build hint queue tests returning relevant hints for active subtopic after grounded partial processing.", 8),
  pass("KCAP-032-T02", "Mapped to resolve_hints_from_expert_text service test hiding hints organically answered by expert text.", 8),
  pass("KCAP-034-T03", "Mapped to local Knowledge Capture API regression test proving editing an accepted proposal updates report content while keeping status=accepted and publication.published_at absent.", 105),
  pass("KCAP-035-T03", "Mapped to real-IAM local API test proving a workspace_contributor receives 403 when directly opening another user's capture session id.", 105),
  pass("KCAP-033-T03", "Mapped to local Knowledge Capture export regression test proving POST /sessions/{id}/proposal/export returns Markdown for an accepted proposal while keeping proposal.status=accepted and published_at absent.", 103),
  pass("KCAP-027-T02", "Mapped to local Knowledge Capture API denial test proving forbidden delete returns 403 and leaves the capture session persisted.", 105),
  pass("KCAP-028-T03", "Mapped to local Knowledge Capture API direct-open permission test proving non-owner contributors cannot open foreign capture session ids.", 105),
  pass("KCAP-038-T03", "Mapped to real-IAM local API test proving contributor proposal listing hides foreign authorless legacy proposals while keeping own legacy proposal visible.", 105),
  pass("KCAP-037-T01", "Mapped to VoiceSessionGateway client.metric test sanitizing and re-emitting endpoint_candidate as runtime.metric source=client_capture.", 8),
  pass("KCAP-037-T03", "Mapped to endpoint STT latency audit test persisting endpoint_stt_ms separately from turn_audio_capture_ms in turn/session metrics.", 8),
]);

const defectRecords = [
  {
    id: "DEF-2026-06-23-CHT-001",
    featureIds: ["CHT-009", "CHT-016"],
    reproduction:
      "Run chat/RAG/voice pytest lot. Before the fix, degraded retrieval strict fallback stripped `retrieval_deadline_exceeded` from user-visible fallback text and over-sanitized the queued deep retrieval partial preview.",
    expected:
      "Strict grounding fallback exposes the degraded retrieval reason in the response/metadata, while the queued deep retrieval job keeps a clean fallback preview for async refinement.",
    actual:
      "Initial run: test_chat_stream_auto_queues_deep_job_for_degraded_retrieval and test_chat_completion_returns_degraded_retrieval_metadata failed.",
    severity: "Medium",
    rootCause:
      "Answer policy cleanup ran before deep-job preview capture and treated the diagnostic token `retrieval:` like ordinary internal vocabulary.",
    status: "Fixed",
    ownerNotes:
      "Fixed in chat endpoint by separating raw deep-refinement preview from sanitized persisted content and preserving `retrieval:` diagnostics. Verified by EXEC-2026-06-23-BE-002.",
    updated: "2026-06-23",
  },
  {
    id: "DEF-2026-06-23-KCAP-002",
    featureIds: ["KCAP-019", "KCAP-039"],
    reproduction:
      "Run the new free-conversation conversation-step API test with duration_minutes=0. Before the fix, the session_complete path returned a closure_sheet and confirmation target but serialized session.metrics.session_end_pending as false.",
    expected:
      "Unlimited no-plan sessions that generate a closure sheet through conversation-step keep session_end_pending=true in the returned session metrics so the UI can remain in the closure/confirmation workflow.",
    actual:
      "Initial test run failed with closure_body.session.metrics.session_end_pending == false, even though generate_session_closure_sheet had set the underlying metric to true.",
    severity: "High",
    rootCause:
      "_compute_timer_metrics returned session_end_pending=false for all unlimited active sessions, overwriting the persisted closure-pending flag during serialize_session.",
    status: "Fixed",
    ownerNotes:
      "Fixed by preserving the persisted session_end_pending flag for unlimited sessions. Verified by EXEC-2026-06-23-BE-004.",
    updated: "2026-06-23",
  },
  {
    id: "DEF-2026-06-23-SFTP-003",
    featureIds: ["SFTP-018"],
    reproduction:
      "Run npm run check:i18n before the fix. The script printed Navigation i18n coverage OK (0 catalog keys checked), so the guard no longer inspected the moved navigation catalog. After fixing the parser, it failed on missing nav.connectors.",
    expected:
      "The navigation i18n guard parses the cockpit navigation catalog, fails if it checks zero keys, and verifies every verb/section key used by the side rail and mini rail has dictionary coverage.",
    actual:
      "The stale guard only searched side-rail component literals and passed while checking zero keys; nav.connectors was absent from both FR and EN dictionaries.",
    severity: "Medium",
    rootCause:
      "Navigation keys moved to navigation.catalog.ts, but scripts/check-i18n-nav.mjs still parsed side-rail.component.ts for literal key definitions.",
    status: "Fixed",
    ownerNotes:
      "Fixed by parsing CockpitLens and CockpitSectionKey from navigation.catalog.ts, failing on empty parse, checking side-rail direct i18n keys, and adding nav.connectors to FR/EN dictionaries. Verified by EXEC-2026-06-23-FE-002.",
    updated: "2026-06-23",
  },
  {
    id: "DEF-2026-06-23-KCAP-040",
    featureIds: ["KCAP-001", "KCAP-002"],
    reproduction:
      "In an IAM-enforced workspace, a workspace_reviewer membership evaluated capture_session.create/execute/update before the fix. The manifest only granted capture creation to contributors/admins and owner-scoped execution/update to contributors.",
    expected:
      "Reviewers can open the Capture dashboard, create a new capture session, and operate their own capture without requiring broad admin rights or mutating another user's session.",
    actual:
      "Reviewer capture creation was denied by default unless the separate reviewers_inherit_contributor flag was enabled, leaving users like Eric blocked on 'Nouvelle capture'.",
    severity: "High",
    rootCause:
      "CAPTURE_MANIFEST used CONTRIBUTOR_OR_ADMIN for capture_session.create and contributor-only owner-scoped rules for update/execute, despite reviewer being an intended capture-capable business role.",
    status: "Fixed",
    ownerNotes:
      "Fixed by adding reviewer to capture operator roles for create and owner-scoped update/execute. Verified by EXEC-2026-06-23-BE-010.",
    updated: "2026-06-23",
  },
  {
    id: "DEF-2026-06-23-KCAP-041",
    featureIds: ["KCAP-015"],
    reproduction:
      "Mock /knowledge-capture/sessions/{id}/documents to return HTTP 400 with a detail such as 'Type de fichier non supporte pour la capture.' and upload an unsupported capture document.",
    expected:
      "The capture UI surfaces the backend rejection detail so the expert understands why the document was rejected, while no fake document, preview or active view is created.",
    actual:
      "Before the fix, onCaptureDocumentFileSelect always displayed the generic 'Chargement document impossible pour cette capture.' message, hiding actionable backend validation details.",
    severity: "Medium",
    rootCause:
      "The capture-document upload error callback did not reuse the component's apiErrorMessage helper and discarded err.error.detail.",
    status: "Fixed",
    ownerNotes:
      "Fixed by routing capture-document upload errors through apiErrorMessage with the generic text as fallback. Verified by EXEC-2026-06-23-FE-037.",
    updated: "2026-06-23",
  },
  {
    id: "DEF-2026-06-23-KCAP-042",
    featureIds: ["KCAP-017"],
    reproduction:
      "Open a capture document preview so voiceFrameMeta contains document_refs/visual_context, then inspect audio.frame or audio.endpoint payloads sent by VoiceSessionConnection or LiveKitConversationConnection before the fix.",
    expected:
      "Voice capture payloads forward active document_refs and visual_context just like written capture turns, allowing the backend to attach the referenced page/slide/photo to the finalized transcript turn.",
    actual:
      "The component produced the active document metadata, but both frontend voice transports dropped document_refs and visual_context while serializing audio.frame/audio.endpoint.",
    severity: "High",
    rootCause:
      "The new active-document metadata contract was added at the Knowledge Capture component/backend boundary, but the intermediate WebSocket and LiveKit voice serializers were not extended.",
    status: "Fixed",
    ownerNotes:
      "Fixed by adding document_refs and visual_context to VoiceFrameMeta and forwarding them in both voice-session and LiveKit audio.frame/audio.endpoint payloads. Verified by EXEC-2026-06-23-FE-084 and direct transport assertions in EXEC-2026-06-23-FE-085.",
    updated: "2026-06-23",
  },
  {
    id: "DEF-2026-06-23-KCAP-043",
    featureIds: ["KCAP-016", "KCAP-017"],
    reproduction:
      "Open a capture document preview on page 1, navigate the PDF viewer to page 2, close the preview, then submit a written note referring to 'cette page'.",
    expected:
      "The active-view label and the next capture turn reference the same page as the preview, and the /documents/view audit plus /turns payload both carry page 2.",
    actual:
      "Before the fix, onSourcePreviewViewChanged persisted the page-change audit but did not update the parent sourcePreviewPage signal, leaving the visible active-view/page context able to stay on page 1 after the preview moved to page 2.",
    severity: "Medium",
    rootCause:
      "The parent Knowledge Capture component treated the preview pageChange event as a backend/audit update only and skipped local signal synchronization.",
    status: "Fixed",
    ownerNotes:
      "Fixed by synchronizing sourcePreviewPage in onSourcePreviewViewChanged before persisting the capture document view. Verified by EXEC-2026-06-23-FE-086.",
    updated: "2026-06-23",
  },
  {
    id: "DEF-2026-06-23-KCAP-044",
    featureIds: ["KCAP-038", "KCAP-035"],
    reproduction:
      "In an IAM-enforced workspace, create a workspace_contributor user and a foreign capture proposal whose created_by_user_id is null but whose session belongs to another user, then call GET /knowledge-capture/proposals as the contributor.",
    expected:
      "Contributor proposal listing returns only proposals owned by the contributor or attached to contributor-owned sessions; legacy authorless proposals must not bypass the session owner boundary.",
    actual:
      "Before the fix, list_capture_proposals included all authorless proposals through KnowledgeUpdateProposal.created_by_user_id.is_(None), even when the joined ExpertCaptureSession belonged to another user.",
    severity: "High",
    rootCause:
      "The contributor-only proposal filter treated null proposal authors as globally visible instead of resolving legacy ownership through the proposal's capture session.",
    status: "Fixed",
    ownerNotes:
      "Fixed by removing the authorless-proposal visibility shortcut so the existing session-owner branch remains the legacy fallback. Verified by EXEC-2026-06-23-BE-016.",
    updated: "2026-06-23",
  },
  {
    id: "DEF-2026-06-23-COL-001",
    featureIds: ["COL-001"],
    reproduction:
      "Force /documents/collections to return HTTP 500 in the mocked Andritz browser smoke. Before the fix, KnowledgeBaseComponent cleared collections and rendered the same 'No collections yet' empty state used for a legitimate empty workspace.",
    expected:
      "A failed Collections load shows an explicit non-destructive error state with a Retry action, disables create/upload mutation controls, and does not render stale collection cards or delete actions.",
    actual:
      "Initial implementation silently treated the API failure as an empty collection list, which could mislead an operator into thinking Andritz had no collections.",
    severity: "Medium",
    rootCause:
      "KnowledgeBaseComponent had loading and data signals but no collections-load error signal or template branch.",
    status: "Fixed",
    ownerNotes:
      "Fixed by adding collectionsError state, a retryable error empty-state branch, disabled create/upload controls while the list is failed, clearing vector DB summary on failure, and a mocked Playwright 500 case. Verified by EXEC-2026-06-23-FE-007.",
    updated: "2026-06-23",
  },
  {
    id: "DEF-2026-06-23-COL-023",
    featureIds: ["COL-023"],
    reproduction:
      "Force /documents/list to return HTTP 500 and open the Knowledge page Browse documents drawer for a mocked Andritz collection. Before the fix, KnowledgeBaseComponent cleared browseDocs and rendered the same 'Empty collection' state used for a legitimate successful empty response.",
    expected:
      "A failed document inventory load shows an explicit retryable error state and does not expose stale preview/delete actions.",
    actual:
      "Initial implementation silently treated the failed inventory call as an empty collection, making an operational failure look like a true absence of documents.",
    severity: "High",
    rootCause:
      "The browse drawer tracked loading and documents but had no browseError signal or error template branch.",
    status: "Fixed",
    ownerNotes:
      "Fixed by adding browseError state, clearing it on new/successful loads, rendering a retryable document-load error state, and adding a mocked Playwright 500 case. Verified by EXEC-2026-06-23-FE-008.",
    updated: "2026-06-23",
  },
  {
    id: "DEF-2026-06-23-COL-008",
    featureIds: ["COL-008"],
    reproduction:
      "Force /documents/search to return HTTP 500 from the Knowledge search drawer. Before the fix, the UI only emitted a toast and kept the drawer body in a no-results or previous-results state.",
    expected:
      "A failed search shows an inline error state and clears stale result rows so operators do not confuse a backend failure with valid evidence.",
    actual:
      "Initial implementation only used a transient toast and did not track searchError, which could leave stale result rows visible after a failed query.",
    severity: "High",
    rootCause:
      "KnowledgeBaseComponent tracked searchAttempted/searching/results but had no searchError signal or error branch in the search drawer.",
    status: "Fixed",
    ownerNotes:
      "Fixed by adding searchError state, clearing it on new/successful searches, clearing searchResults on failure, rendering an inline error state, and adding a mocked Playwright 500 case. Verified by EXEC-2026-06-23-FE-009.",
    updated: "2026-06-23",
  },
  {
    id: "DEF-2026-06-23-COL-008B",
    featureIds: ["COL-008"],
    reproduction:
      "Run a successful Knowledge search, close the drawer, then open Search in this collection. Before the fix, the drawer reused the previous query/result state when entering a new search context.",
    expected:
      "Opening a new global or collection-scoped search context starts clean: empty query, no old results, no previous error and no stale no-results state.",
    actual:
      "Initial implementation opened the drawer directly with searchOpen.set(true) or openSearchIn without resetting searchQuery/searchResults/searchAttempted/searchError.",
    severity: "High",
    rootCause:
      "Search drawer lifecycle did not centralize state reset between global search and collection-scoped search.",
    status: "Fixed",
    ownerNotes:
      "Fixed by routing global search through openGlobalSearch, resetting search state on new context, clearing collection draft on close, and clearing stale results when a new search starts. Verified by EXEC-2026-06-23-FE-010.",
    updated: "2026-06-23",
  },
  {
    id: "DEF-2026-06-23-COL-018",
    featureIds: ["COL-018"],
    reproduction:
      "Inspect and exercise DELETE /documents/clear in a local synthetic API test. Before the fix, any authenticated workspace user could call the endpoint with the default collection_name, no confirmation token, and the success path also wiped every file in the legacy UPLOADS_DIR.",
    expected:
      "Global document clear is unavailable to non-admin users, requires explicit destructive confirmation naming the target collection, and does not delete unrelated legacy upload files unless separately requested.",
    actual:
      "The endpoint depended only on get_current_workspace, accepted collection_name=documents by default, instantiated DocumentService.clear_all_documents immediately, and deleted all entries from UPLOADS_DIR after success.",
    severity: "Critical",
    rootCause:
      "A legacy maintenance endpoint predated workspace-admin/confirmation guardrails and treated vector collection cleanup plus legacy upload cleanup as one implicit operation.",
    status: "Fixed",
    ownerNotes:
      "Fixed by adding workspace admin enforcement, confirm=true, confirm_collection_name equality, and opt-in clear_uploads. Verified locally with fake DocumentService and synthetic tmp uploads in EXEC-2026-06-23-BE-011.",
    updated: "2026-06-23",
  },
  {
    id: "DEF-2026-06-23-COL-019",
    featureIds: ["COL-011", "COL-021"],
    reproduction:
      "Call POST/PATCH /knowledge/guides or PATCH /knowledge/scopes as a synthetic workspace_contributor before the fix.",
    expected:
      "Only workspace admins can mutate interpretation guides or workspace knowledge-scope configuration; denied requests leave guide versions and workspace settings unchanged.",
    actual:
      "The endpoints depended only on an authenticated current workspace/current user and passed directly into create_guide/update_guide or workspace.settings mutation.",
    severity: "High",
    rootCause:
      "The Knowledge admin configuration endpoints were added without reusing the workspace-admin role guard already present on destructive document maintenance routes.",
    status: "Fixed",
    ownerNotes:
      "Fixed by adding workspace-admin enforcement to guide create/patch and scope patch. Verified by EXEC-2026-06-23-BE-017.",
    updated: "2026-06-23",
  },
  {
    id: "DEF-2026-06-23-COL-020",
    featureIds: ["COL-016"],
    reproduction:
      "Call PATCH /documents/collections/{collection_id} as a synthetic non-admin workspace member before the fix.",
    expected:
      "Only workspace admins can patch collection metadata, and denied attempts leave collection name/description plus indexed data untouched.",
    actual:
      "The endpoint depended only on the current workspace and DB session, so any authenticated workspace user could change collection presentation metadata.",
    severity: "High",
    rootCause:
      "Collection metadata patch missed the existing _require_workspace_admin guard used by other sensitive document collection operations.",
    status: "Fixed",
    ownerNotes:
      "Fixed by requiring workspace-admin membership before resolving and mutating the collection row. Verified by EXEC-2026-06-23-BE-017.",
    updated: "2026-06-23",
  },
  {
    id: "DEF-2026-06-23-COL-024",
    featureIds: ["COL-022"],
    reproduction:
      "Open /knowledge/andritz-qa in the local mocked browser smoke with one visible bound system, then click the header Bindings action before the fix.",
    expected:
      "The Bindings action exposes the visible bound system from the permission-scoped /systems catalogue and never exposes hidden systems absent from that catalogue.",
    actual:
      "The action opened a secondary 'Bindings overview' panel whose rendered panel body did not expose the visible binding in the tested viewport, while the existing Bindings tab already contained the correct data.",
    severity: "Medium",
    rootCause:
      "KnowledgeViewComponent used a side panel for the header Bindings action while Guide and Table facts used tab switching; the duplicated panel path diverged from the working tab content.",
    status: "Fixed",
    ownerNotes:
      "Fixed by aligning the header Bindings action with the other Knowledge facets: it now switches to the existing Bindings tab and the empty side-panel path was removed. Verified by EXEC-2026-06-23-FE-089.",
    updated: "2026-06-23",
  },
  {
    id: "DEF-2026-06-23-COL-025",
    featureIds: ["COL-003"],
    reproduction:
      "POST two files with the same filename in a single synthetic /documents/collections/{id}/documents request. Before the fix, the second source upsert could not see the first pending ORM row and the request crashed on the unique constraint for collection_id + normalized_name.",
    expected:
      "A same-request duplicate filename is handled deterministically: the object-store original is overwritten by the last payload, the collection document_names list remains unique, one ledger source row exists, and inventory remains coherent.",
    actual:
      "Initial targeted test failed with sqlalchemy.exc.IntegrityError / sqlite3 UNIQUE constraint failed: knowledge_collection_sources.collection_id, knowledge_collection_sources.normalized_name.",
    severity: "High",
    rootCause:
      "_queue_collection_ingest called upsert_collection_source once per multipart item before flushing; duplicate normalized names in the same request created two pending rows because the second lookup did not find the first unflushed instance.",
    status: "Fixed",
    ownerNotes:
      "Fixed by grouping collection source updates by normalize_source_name within the request and applying one upsert per normalized filename after object writes. Verified by EXEC-2026-06-23-BE-021.",
    updated: "2026-06-23",
  },
  {
    id: "DEF-2026-06-23-COL-026",
    featureIds: ["COL-020"],
    reproduction:
      "POST a file whose normalized filename already exists in a synthetic /documents/collections/{id}/documents collection. Before the fix, the source row status moved back to queued but retained the old chunk_count and source_metadata.document_id from the prior indexed version.",
    expected:
      "Reuploading an existing filename keeps a single manifest/source entry, overwrites the stored original, queues the source for reindexing, and clears stale chunk/document metadata until the worker writes fresh results.",
    actual:
      "The targeted test initially failed because chunk_count stayed at 2 after requeue; source metadata would also continue pointing at the previous document id until worker completion.",
    severity: "High",
    rootCause:
      "The collection upload path called upsert_collection_source with status=queued and size bytes only, while upsert_collection_source preserved existing chunk_count and merged metadata unless fresh metadata was supplied.",
    status: "Fixed",
    ownerNotes:
      "Fixed by adding an explicit replace_source_metadata option to upsert_collection_source and using it only when upload requeues a source, together with chunk_count=0. Verified by EXEC-2026-06-23-BE-028.",
    updated: "2026-06-23",
  },
  {
    id: "DEF-2026-06-23-COL-027",
    featureIds: ["COL-020"],
    reproduction:
      "Mock dispatch_worker_job to raise during POST /documents/collections/{id}/documents on a synthetic collection. Before the fix, the source, collection and job were already committed as queued, then the API surfaced an unstructured 500 without marking the failed dispatch in the ledger.",
    expected:
      "A worker dispatch failure is visible to the caller and leaves an auditable state: job failed, collection error with last_error, source/original file still traceable for retry or investigation.",
    actual:
      "The upload path committed queued state before dispatch and had no dispatch exception handling, leaving operators with a false queued/in-progress state even though no worker task was launched.",
    severity: "High",
    rootCause:
      "_queue_collection_ingest committed the collection/source/job ledger before dispatch_worker_job but did not catch dispatch exceptions to update job or collection status.",
    status: "Fixed",
    ownerNotes:
      "Fixed by catching dispatch exceptions, persisting update_job(status=failed, stage=dispatch_failed), setting collection.status=error/last_error, committing that state, then returning HTTP 503. Verified by EXEC-2026-06-23-BE-029.",
    updated: "2026-06-23",
  },
  {
    id: "DEF-2026-06-23-CHT-005",
    featureIds: ["CHT-005"],
    reproduction:
      "Mock /contexts/{id}/persist to return an error/null result after uploading a drop-and-ask document and clicking Persist.",
    expected:
      "User sees a recoverable failure and the Persist action becomes available again; no silent failure and no duplicate context promotion.",
    actual:
      "CanonicalApiService.persistContext() swallowed the HTTP error as null and ChatWorkspaceComponent handled only non-null success, so no error toast appeared.",
    severity: "Medium",
    rootCause:
      "Component expected an error callback, but the canonical service catchError converted persistence failure into a null next value.",
    status: "Fixed",
    ownerNotes:
      "ChatWorkspaceComponent now treats a null persistContext result as failure and shows the existing Drop-and-ask error toast. Verified by EXEC-2026-06-23-FE-018.",
    updated: "2026-06-23",
  },
  {
    id: "DEF-2026-06-23-CHT-004",
    featureIds: ["CHT-004", "CHT-006"],
    reproduction:
      "Mock /documents/upload-batch to return one successful document and one failed document row, then inspect the subsequent POST /contexts payload.",
    expected:
      "Only successfully indexed filenames are displayed as session docs and sent to the ephemeral context data_refs; failed filenames remain excluded from retrieval scope.",
    actual:
      "ChatWorkspaceComponent filtered visible session docs on status=success but built context data_refs from every returned filename, including failed rows.",
    severity: "High",
    rootCause:
      "uploadFiles used the raw upload response filename list for ensureEphemeralContext instead of the success-filtered document list.",
    status: "Fixed",
    ownerNotes:
      "uploadFiles now filters context data_refs to status=success before ensureEphemeralContext. Verified by EXEC-2026-06-23-FE-020.",
    updated: "2026-06-23",
  },
  {
    id: "DEF-2026-06-23-CHT-006",
    featureIds: ["CHT-006"],
    reproduction:
      "Attach a drop-and-ask document, decide it should not ground the next answer, and try to remove it from the active chat session before asking.",
    expected:
      "User can detach the document from the temporary session context without deleting indexed data; context data_refs is patched and the next chat turn has no stale context_id/context_mode when no session docs remain.",
    actual:
      "The session-doc list was display-only, so an accidentally attached document stayed in the active drop-and-ask scope until the page/session was reset.",
    severity: "High",
    rootCause:
      "ChatWorkspaceComponent had an append/update path for ephemeral context data_refs but no per-document detach flow or final-doc context clearing.",
    status: "Fixed",
    ownerNotes:
      "Added a per-row remove control that PATCHes the ephemeral context with remaining data_refs and clears ephemeralContextId when the last doc is detached. Verified by EXEC-2026-06-23-FE-024.",
    updated: "2026-06-23",
  },
  {
    id: "DEF-2026-06-23-CHT-007",
    featureIds: ["CHT-006"],
    reproduction:
      "Mock /contexts/{id} PATCH to fail while removing an attached drop-and-ask session document.",
    expected:
      "The UI shows a recoverable error, keeps the doc attached, keeps Persist available and preserves the active session-doc scope for the next chat request.",
    actual:
      "CanonicalApiService.updateContext() returns null on HTTP failure, but detachSessionDoc treated every next() value as success and removed the doc locally.",
    severity: "Medium",
    rootCause:
      "The detach flow handled error callbacks but did not check the null failure sentinel returned by the canonical context service.",
    status: "Fixed",
    ownerNotes:
      "detachSessionDoc now treats a null updateContext result as failure, resets the pending state, displays the existing recoverable error and leaves local session docs unchanged. Verified by EXEC-2026-06-23-FE-025.",
    updated: "2026-06-23",
  },
  {
    id: "DEF-2026-06-23-CHT-008",
    featureIds: ["CHT-006"],
    reproduction:
      "Mock /contexts POST to fail after a successful drop-and-ask upload and before asking the next chat question.",
    expected:
      "The UI shows a recoverable error, does not present the uploaded file as attached to the chat session, hides Persist, and sends the next /sessions and /chat/stream payloads with context_id=null and context_mode=null.",
    actual:
      "Before the fix, createContext() failure returned null and ChatWorkspaceComponent left the uploaded doc visible as attached even though no ephemeral context id existed.",
    severity: "High",
    rootCause:
      "ensureEphemeralContext only set the context id when createContext returned a truthy context, but it did not treat the null failure sentinel as a rollback condition for newly-added session docs.",
    status: "Fixed",
    ownerNotes:
      "ensureEphemeralContext now treats null create/update results as failure, removes newly-added session docs from the UI, and shows a recoverable Drop-and-ask error. Verified by EXEC-2026-06-23-FE-028.",
    updated: "2026-06-23",
  },
  {
    id: "DEF-2026-06-23-SFTP-016",
    featureIds: ["SFTP-016"],
    reproduction:
      "Force /documents/jobs to return HTTP 500 from the SFTP connector, then manually refresh the Indexing pipeline monitor.",
    expected:
      "The SFTP connector shows a visible non-blocking pipeline error, keeps analysis/link controls usable, and does not trigger link, promote, bulk-promote, archive-download or reconcile mutations.",
    actual:
      "Before the fix, loadIndexingMonitor silently cleared knowledgeJobs and reset loading, so the UI looked like a legitimate empty pipeline instead of an operational failure.",
    severity: "Medium",
    rootCause:
      "SftpConnectorComponent had knowledgeJobsLoading and knowledgeJobs state but no indexing-monitor error signal or template branch for /documents/jobs failures.",
    status: "Fixed",
    ownerNotes:
      "Fixed by adding indexingMonitorError, rendering it inside the Indexing pipeline panel, clearing it on successful reload, and adding a mocked Playwright failure case. Verified by EXEC-2026-06-23-FE-059.",
    updated: "2026-06-23",
  },
];

const allTests = features.flatMap((feature) => tests(feature.id, feature.tests));
const mappedPassedCount = executedTestResults.size;
const executedFeatureIds = new Set([...executedTestResults.keys()].map((testId) => testId.slice(0, testId.lastIndexOf("-T"))));
const openDefectRecords = defectRecords.filter((defect) => !["Fixed", "Closed", "Waived"].includes(defect.status));
const openCriticalHighDefects = openDefectRecords.filter((defect) => ["Critical", "High"].includes(defect.severity));

function mappedTestCasesForEvidence(evidenceId) {
  return [...executedTestResults.entries()]
    .filter(([, result]) => result.evidence === evidenceId)
    .map(([testId]) => testId)
    .join("\n");
}

function mappedPassedCountForEvidence(evidenceId) {
  return [...executedTestResults.values()].filter((result) => result.evidence === evidenceId).length;
}

function executedCountForFeature(featureId) {
  return allTests.filter((test) => test.featureId === featureId && executedTestResults.has(test.testId)).length;
}

function defectCountForFeature(featureId) {
  return defectRecords.filter((defect) => defect.featureIds.includes(featureId)).length;
}

function severityForFeature(featureId) {
  const severities = defectRecords
    .filter((defect) => defect.featureIds.includes(featureId))
    .map((defect) => defect.severity);
  if (severities.includes("Critical")) return "Critical";
  if (severities.includes("High")) return "High";
  if (severities.includes("Medium")) return "Medium";
  if (severities.includes("Low")) return "Low";
  return severityNone;
}

function notExecutedCountForPrefix(prefix) {
  return allTests.filter((test) => test.featureId.startsWith(prefix) && !executedTestResults.has(test.testId)).length;
}

function featureExecutionStatus(feature) {
  return executedCountForFeature(feature.id) > 0
    ? "Partial local backend pass - manual/e2e pending"
    : status;
}

function featureExecutionNotes(feature) {
  const count = executedCountForFeature(feature.id);
  if (count === 0) {
    return feature.notes;
  }
  const evidenceCounts = new Map();
  for (const test of allTests.filter((candidate) => candidate.featureId === feature.id)) {
    const result = executedTestResults.get(test.testId);
    if (!result) continue;
    evidenceCounts.set(result.evidence, (evidenceCounts.get(result.evidence) || 0) + 1);
  }
  const evidenceSummary = [...evidenceCounts.entries()]
    .map(([evidenceId, evidenceCount]) => `${evidenceId}: ${evidenceCount} mapped test case(s) passed locally.`)
    .join("\n");
  return `${feature.notes}\n${evidenceSummary}\nBrowser UX, VM read-only checks and/or destructive synthetic tests remain pending as applicable.`;
}

for (const feature of features) {
  feature.testCaseRefs = allTests
    .filter((test) => test.featureId === feature.id)
    .map((test) => `${test.testId} ${test.type}: ${test.scenario}`)
    .join("\n");
}

function featureCountForSurface(surface) {
  return features.filter((feature) => feature.scope.includes(surface)).length;
}

function testCountForPrefix(prefix) {
  return allTests.filter((test) => test.featureId.startsWith(prefix)).length;
}

function writeMatrix(sheet, startCell, rows) {
  sheet.getRange(startCell).write(rows);
}

function styleHeader(range) {
  range.format.fill = { color: "#E7F0FA" };
  range.format.font = { color: "#0B1220", bold: true };
  range.format.wrapText = true;
  range.format.verticalAlignment = "Top";
  range.format.borders = { preset: "all", style: "thin", color: "#6B7A90" };
}

function styleBody(range) {
  range.format.wrapText = true;
  range.format.verticalAlignment = "Top";
  range.format.borders = { preset: "all", style: "thin", color: "#D9E2EC" };
}

function setWidths(sheet, widths) {
  widths.forEach((width, col) => {
    sheet.getRangeByIndexes(0, col, 1, 1).format.columnWidth = width;
  });
}

await fs.mkdir(outputDir, { recursive: true });

const workbook = Workbook.create();

const summary = workbook.worksheets.add("Coverage Summary");
summary.showGridLines = false;
summary.getRange("A1:D1").values = [["Andritz QA Matrix - Chat Recherche, Knowledge Capture, Collections", "", "", ""]];
summary.getRange("A1").format.font = { color: "#0B1220", bold: true, size: 16 };
summary.getRange("A1").format.rowHeight = 30;

const summaryRows = [
  ["Generated", discoveryDate, "", "", "", "", "", ""],
  ["Scope", "Only Chat Recherche, Knowledge Capture, Collections/SFTP for Andritz", "", "", "", "", "", ""],
  ["Safety posture", "Local automated tests/builds only. No destructive Andritz/SFTP data operation executed.", "", "", "", "", "", ""],
  ["Features documented", features.length, "", "", "", "", "", ""],
  ["Test cases drafted", allTests.length, "", "", "", "", "", ""],
  ["Mapped tests passed", mappedPassedCount, "", "", "", "", "", ""],
  ["Features with partial backend pass", executedFeatureIds.size, "", "", "", "", "", ""],
  ["Frontend production build", `${executionEvidence[1].result} (${executionEvidence[1].duration}); FE-002 static guards and rebuild also passed.`, "", "", "", "", "", ""],
  ["VM read-only smoke", "Drift audit passed; backend/frontend health 200; critical SPA routes served; KC/SFTP protected APIs rejected unauthenticated access.", "", "", "", "", "", ""],
  ["Defects found/fixed", `${defectRecords.length} found, ${defectRecords.filter((defect) => defect.status === "Fixed").length} fixed`, "", "", "", "", "", ""],
  ["Open defects recorded", openDefectRecords.length, "", "", "", "", "", ""],
  ["Critical/high defects", openCriticalHighDefects.length, "", "", "", "", "", ""],
  ["Execution status", `${executionEvidence[0].result}; ${executionEvidence[2].result}; ${executionEvidence[3].result}; ${executionEvidence[4].result}; ${executionEvidence[5].result}; ${executionEvidence[6].result}; ${executionEvidence[7].result}; ${executionEvidence[8].result}; ${executionEvidence[9].result}; ${executionEvidence[10].result}; ${executionEvidence[11].result}; ${executionEvidence[12].result}; ${executionEvidence[13].result}; ${executionEvidence[14].result}; ${executionEvidence[15].result}; ${executionEvidence[16].result}; ${executionEvidence[17].result}; ${executionEvidence[18].result}; ${executionEvidence[19].result}; ${executionEvidence[20].result}; ${executionEvidence[21].result}; latest Andritz mocked browser + voice transport/capture contract smoke: ${executionEvidence[99].result}; latest Collections clear-safety API lot: ${executionEvidence[100].result}; latest Secure Deposit workspace/extension policy lot: ${executionEvidence[101].result}; latest Secure Deposit critical access-control lot: ${executionEvidence[102].result}; latest Knowledge Capture publication-safety lot: ${executionEvidence[103].result}; latest SFTP/SPL explicit-execute guard lot: ${executionEvidence[104].result}; latest Knowledge Capture permission/content lot: ${executionEvidence[105].result}; latest Collections permission/scope lot: ${executionEvidence[106].result}; latest Collections hidden-binding UI smoke: ${executionEvidence[107].result}; latest Collections inventory input-validation lot: ${executionEvidence[108].result}; latest Collections unsupported upload guard lot: ${executionEvidence[122].result}; latest Collections large-list lot: ${executionEvidence[123].result}; latest Collections large dry-run reindex lot: ${executionEvidence[124].result}; latest Collections OCR duplicate UI smoke: ${executionEvidence[125].result}; latest SFTP catalogue navigation smoke: ${executionEvidence[126].result}; authenticated real-backend browser/e2e validation remains pending.`, "", "", "", "", "", ""],
  ["Confidence score", "91/100 - backend/API and service coverage now includes no-plan safety, capture document upload/references, unsupported upload rejection detail, multi-document active-view scoping, capture preview page-change synchronization, guided-plan written note anchoring, guided-plan section-switch anchoring, guided-plan document-reference anchoring, voice active-document transport, late same-turn partial rendering, adaptive VAD endpoint candidate cancellation/flush, non-blocking capture document view logging failure, no-plan finalization failure recovery, empty no-plan finish guard, oracle grounding, STT metrics, report finalization, publication promotion, reviewer capture IAM and IAM matrix exposure, Knowledge Capture proposal/session permission denials and contributor proposal-scope filtering, accepted-proposal content editing without implicit publication, collections worker/indexing ledger behavior, collection inventory input bounds, large collection-list isolation, large retrieval-artifact dry-run read-only assessment, OCR duplicate-fact UI dedupe, global document clear admin/confirmation safety, knowledge guide/scope admin gates, collection metadata patch admin gates, cross-workspace table-query and legacy list isolation, collection hidden-system binding non-leak and Bindings action UX, secure deposit workspace enablement/extension policy, secure deposit token/rotate-revoke/download/SFTP upload-only access gates, synthetic collection creation safety, synthetic document and collection delete safety with permission-denial rollback, synthetic SFTP/Secure Deposit promotion/reconciliation/wave planning, SPL CLI dry-run-by-default execution guard, frontend navigation guard coverage and SFTP connector catalogue navigation for the SFTP connector entry, and local mocked desktop/mobile/reviewer/multi-route unauthenticated-guard, disabled-SFTP-settings/direct-page, enabled-SFTP health/no-secret direct-page, SFTP staging queue load/filter/link-scope/empty-search safety, SFTP operations/indexing-assist monitor safety, SFTP operations monitor failure visibility, SFTP reconciliation dry-run success UX, SFTP reconciliation permission-denial UX, SFTP quarantine cancel confirmation safety, SFTP file-download failure recovery, SFTP staging ZIP download failure recovery, SFTP indexing-monitor failure visibility, SFTP preview/archive drawer safety, SFTP target collection selection safety, SFTP deposit link create/rotate/revoke/copy/password/copy-failure/permission-denial handoff safety, Chat selected system scope propagation, stale-system fallback, forbidden-system fallback, Quick ask long-prompt boundary handling, slow-stream waiting feedback, stream interruption recovery, auto-deep retrieval tracking, PDF drop-and-ask happy path, unsupported-file rejection, large-file boundary responsiveness, no-session-doc null-scope handling and context persistence happy/expired/permission-denial handling, Chat document metadata facts/failure/keyword compaction, Collections API-failure, successful document-browse drawer, empty document-browse drawer, explicit scoped document delete confirmation, typed collection delete confirmation, forbidden delete handling, document preview download fallback, document preview sanitization, forbidden collection preview, document-browse failure, Knowledge search failure and Knowledge search context-reset browser smokes for Chat, Knowledge Capture, Collections and SFTP entry rendering. Authenticated browser journeys against real backend data, real audio/VAD field behavior, real SFTP server behavior, and real Andritz data-preserving end-to-end validation remain pending.", "", "", "", "", "", ""],
];
summary.getRange("A3:H16").values = summaryRows;
styleBody(summary.getRange("A3:H16"));
summary.getRange("A3:A16").format.font = { bold: true, color: "#16324F" };
summary.getRange("A17:H17").values = [["Surface", "Feature Count", "Remaining Not Executed Tests", "Critical Risk Notes", "", "", "", ""]];
styleHeader(summary.getRange("A17:H17"));
const surfaces = [
  ["Chat Recherche", featureCountForSurface("Chat Recherche"), notExecutedCountForPrefix("CHT-"), "Streaming, source grounding, voice partial/final consistency", "", "", "", ""],
  ["Knowledge Capture", featureCountForSurface("Knowledge Capture"), notExecutedCountForPrefix("KCAP-"), "No auto-publish, no-plan structure, voice/oracle decoupling, document references", "", "", "", ""],
  ["Collections", featureCountForSurface("Collections"), notExecutedCountForPrefix("COL-"), "Collection integrity, previews, facts, workers", "", "", "", ""],
  ["SFTP Andritz", featureCountForSurface("SFTP Andritz"), notExecutedCountForPrefix("SFTP-"), "Never mutate real data without explicit approval; link/auth/promote are high impact", "", "", "", ""],
];
summary.getRange("A18:H21").values = surfaces;
styleBody(summary.getRange("A18:H21"));
setWidths(summary, [24, 44, 24, 74, 8, 8, 8, 8]);

const matrix = workbook.worksheets.add("QA Matrix");
matrix.showGridLines = false;
const matrixHeaders = [
  "Feature ID",
  "Feature Name",
  "User Story",
  "Expected Behaviour",
  "Edge Cases",
  "Test Cases",
  "Current Status",
  "Defect Count",
  "Severity",
  "Notes",
  "Last Tested Date",
  "Validation Rules",
  "Dependencies",
  "Assumptions",
  "Source References",
  "Scope",
];
const matrixRows = features.map((feature) => [
  feature.id,
  feature.name,
  feature.story,
  feature.expected,
  feature.edges,
  feature.testCaseRefs,
  featureExecutionStatus(feature),
  defectCountForFeature(feature.id),
  severityForFeature(feature.id),
  featureExecutionNotes(feature),
  executedCountForFeature(feature.id) > 0 ? executionEvidence[0].date : "",
  feature.validation,
  feature.dependencies,
  feature.assumptions,
  feature.source,
  feature.scope,
]);
writeMatrix(matrix, "A1", [matrixHeaders, ...matrixRows]);
styleHeader(matrix.getRange("A1:P1"));
styleBody(matrix.getRangeByIndexes(1, 0, matrixRows.length, matrixHeaders.length));
matrix.freezePanes.freezeRows(1);
setWidths(matrix, [14, 34, 52, 58, 44, 60, 28, 12, 12, 42, 16, 46, 42, 42, 46, 28]);
matrix.getRangeByIndexes(1, 7, matrixRows.length, 1).setNumberFormat("0");
matrix.dataValidations.add({
  range: `G2:G${matrixRows.length + 1}`,
  rule: { type: "list", values: ["Discovered - tests drafted, not executed", "Partial local backend pass - manual/e2e pending", "In execution", "Executed pass", "Executed fail", "Fixed", "Waived"] },
});
matrix.dataValidations.add({
  range: `I2:I${matrixRows.length + 1}`,
  rule: { type: "list", values: ["None", "Low", "Medium", "High", "Critical"] },
});

const testSheet = workbook.worksheets.add("Test Backlog");
testSheet.showGridLines = false;
const testHeaders = ["Test ID", "Feature ID", "Type", "Scenario", "Preconditions", "Steps", "Expected Result", "Status", "Severity If Fails", "Notes", "Last Executed", "Evidence"];
const testRows = allTests.map((test) => {
  const executed = executedTestResults.get(test.testId);
  return [
    test.testId,
    test.featureId,
    test.type,
    test.scenario,
    test.preconditions,
    test.steps,
    test.expected,
    executed?.status || test.status,
    test.severityIfFails,
    [test.notes, executed?.notes].filter(Boolean).join("\n"),
    executed?.date || "",
    executed?.evidence || "",
  ];
});
writeMatrix(testSheet, "A1", [testHeaders, ...testRows]);
styleHeader(testSheet.getRange("A1:L1"));
styleBody(testSheet.getRangeByIndexes(1, 0, testRows.length, testHeaders.length));
testSheet.freezePanes.freezeRows(1);
setWidths(testSheet, [18, 14, 18, 46, 46, 58, 58, 18, 18, 42, 16, 24]);
testSheet.dataValidations.add({
  range: `H2:H${testRows.length + 1}`,
  rule: { type: "list", values: ["Not executed", "Pass", "Fail", "Blocked", "Waived"] },
});
testSheet.dataValidations.add({
  range: `I2:I${testRows.length + 1}`,
  rule: { type: "list", values: ["Low", "Medium", "High", "Critical"] },
});

const defects = workbook.worksheets.add("Defect Register");
defects.showGridLines = false;
const defectHeaders = [
  "Defect ID",
  "Feature ID",
  "Reproduction Steps",
  "Expected Result",
  "Actual Result",
  "Severity",
  "Root Cause Hypothesis",
  "Status",
  "Owner/Notes",
  "Last Updated",
];
const defectRows = defectRecords.map((defect) => [
  defect.id,
  defect.featureIds.join(", "),
  defect.reproduction,
  defect.expected,
  defect.actual,
  defect.severity,
  defect.rootCause,
  defect.status,
  defect.ownerNotes,
  defect.updated,
]);
writeMatrix(defects, "A1", [defectHeaders, ...defectRows]);
styleHeader(defects.getRange("A1:J1"));
styleBody(defects.getRangeByIndexes(1, 0, Math.max(defectRows.length, 1), defectHeaders.length));
defects.getRange(`A${defectRows.length + 2}:J20`).format.borders = { preset: "all", style: "thin", color: "#E4E7EB" };
defects.freezePanes.freezeRows(1);
setWidths(defects, [18, 14, 60, 50, 50, 14, 48, 18, 42, 16]);
defects.dataValidations.add({ range: "F2:F200", rule: { type: "list", values: ["Low", "Medium", "High", "Critical"] } });
defects.dataValidations.add({ range: "H2:H200", rule: { type: "list", values: ["Open", "Investigating", "Fixed", "Retest", "Waived", "Closed"] } });

const execution = workbook.worksheets.add("Execution Log");
execution.showGridLines = false;
const executionHeaders = ["Evidence ID", "Date", "Command", "Result", "Duration", "Warnings", "Safety Scope", "Mapped Test Cases", "Notes"];
const executionRows = executionEvidence.map((evidence) => [
  evidence.id,
  evidence.date,
  evidence.command,
  evidence.result,
  evidence.duration,
  evidence.warnings,
  evidence.safetyScope,
  evidence.mappedTestCases ?? mappedTestCasesForEvidence(evidence.id),
  evidence.notes,
]);
writeMatrix(execution, "A1", [executionHeaders, ...executionRows]);
styleHeader(execution.getRange("A1:I1"));
styleBody(execution.getRangeByIndexes(1, 0, executionRows.length, executionHeaders.length));
execution.freezePanes.freezeRows(1);
setWidths(execution, [28, 16, 86, 28, 14, 52, 64, 44, 70]);

const phase = workbook.worksheets.add("Phase Log");
phase.showGridLines = false;
const phaseHeaders = ["Date", "Phase", "Action", "Result", "Safety Notes", "Next Step"];
const phaseRows = [
  [
    discoveryDate,
    "Phase 1 / Phase 2 seed",
    "Code-based discovery for Chat Recherche, Knowledge Capture, Collections and SFTP Andritz surfaces.",
    `${features.length} features documented and ${allTests.length} test cases drafted.`,
    "No VM mutation, no SFTP/collection destructive operation, no deploy.",
    "Record backend automated execution evidence, then continue read-only/browser/VM validations before any synthetic mutation test.",
  ],
  [
    executionEvidence[0].date,
    "Phase 3 partial backend execution",
    "Executed focused backend API/service pytest lot for capture, collections, LiveKit, chat correction, and secure deposit.",
    `${executionEvidence[0].result}; ${mappedPassedCountForEvidence(executionEvidence[0].id)} workbook test cases mapped as Pass.`,
    executionEvidence[0].safetyScope,
    "Run browser UX/e2e validations and VM read-only checks; keep destructive SFTP/collection tests synthetic and explicitly approved.",
  ],
  [
    executionEvidence[1].date,
    "Phase 3 frontend compile validation",
    "Executed Angular production build locally with the bundled Node runtime.",
    `${executionEvidence[1].result} in ${executionEvidence[1].duration}; warnings logged as non-blocking compile risks.`,
    executionEvidence[1].safetyScope,
    "Follow with browser route smoke tests for Chat Recherche, Knowledge Capture, Knowledge View and SFTP connector.",
  ],
  [
    executionEvidence[2].date,
    "Phase 3 chat/RAG/voice backend execution + remediation",
    "Executed focused Chat/RAG/voice pytest lot, fixed degraded-retrieval observability regression, and reran the full lot.",
    `${executionEvidence[2].result}; ${mappedPassedCountForEvidence(executionEvidence[2].id)} workbook test cases mapped as Pass.`,
    executionEvidence[2].safetyScope,
    "Continue browser UX/e2e and VM read-only validation; keep production SFTP/collection mutations out of QA without explicit approval.",
  ],
  [
    executionEvidence[3].date,
    "Phase 3 VM read-only deployment smoke",
    "Ran deploy-vm.sh --check-only, container status, backend/frontend healthchecks, static SPA route probes, and unauthenticated protected API probes.",
    executionEvidence[3].result,
    executionEvidence[3].safetyScope,
    "Run authenticated browser UX/e2e smoke with a safe Andritz test account before marking route/user journeys as executed.",
  ],
  [
    executionEvidence[4].date,
    "Phase 3 RAG/scopes service execution",
    "Executed focused retrieval policy, RAG context worker and RAG service pytest lot.",
    `${executionEvidence[4].result}; ${mappedPassedCountForEvidence(executionEvidence[4].id)} workbook test cases mapped as Pass.`,
    executionEvidence[4].safetyScope,
    "Continue authenticated browser/e2e checks for Chat Recherche, capture prefetch/oracle UI and collection knowledge-guide editing.",
  ],
  [
    discoveryDate,
    "Phase 1 route/API gap audit",
    "Compared relevant Chat, Knowledge Capture, Knowledge, Documents and Secure Deposit endpoints/routes against the matrix.",
    "Added KCAP-039 for the conversation-only autonomous capture loop; public deposit portal remained covered by SFTP public deposit features.",
    "Read-only source inspection only. No VM mutation, no Andritz collection mutation, no SFTP production-data mutation.",
    "Generate and run targeted backend/component tests for conversation-step, fallback text, and explicit confirmation behavior.",
  ],
  [
    executionEvidence[5].date,
    "Phase 3 conversation-only API execution + remediation",
    "Added and executed free-conversation conversation-step API tests covering turn recording, closure state, permission checks and denied acceptance.",
    `${executionEvidence[5].result}; ${mappedPassedCountForEvidence(executionEvidence[5].id)} workbook test cases mapped as Pass; DEF-2026-06-23-KCAP-002 fixed.`,
    executionEvidence[5].safetyScope,
    "Continue with authenticated browser validation for the no-plan capture UX, text fallback, and LiveKit/WebSocket failure paths.",
  ],
  [
    executionEvidence[6].date,
    "Phase 3 capture document reference API execution",
    "Added and executed API tests for capture document active-view logging and typed turns carrying document_refs/visual_context.",
    `${executionEvidence[6].result}; ${mappedPassedCountForEvidence(executionEvidence[6].id)} workbook test cases mapped as Pass.`,
    executionEvidence[6].safetyScope,
    "Continue with safe upload/indexing tests using local object store fixtures, then authenticated browser preview/navigation validation.",
  ],
  [
    executionEvidence[7].date,
    "Phase 3 capture document upload API execution",
    "Added and executed API test for capture-session upload of a PDF plus PNG with async indexing queued and worker dispatch neutralized.",
    `${executionEvidence[7].result}; ${mappedPassedCountForEvidence(executionEvidence[7].id)} workbook test case mapped as Pass.`,
    executionEvidence[7].safetyScope,
    "Continue with authenticated browser upload/preview validation and indexing-completion checks on safe synthetic documents.",
  ],
  [
    executionEvidence[8].date,
    "Phase 3 Knowledge Capture service execution + harness correction",
    "Executed the full Knowledge Capture service pytest lot after fixing a stale voice/STT test harness call to pass input_modality=voice like VoiceSessionGateway.",
    `${executionEvidence[8].result}; ${mappedPassedCountForEvidence(executionEvidence[8].id)} workbook test cases mapped as Pass; no product defect found in this lot.`,
    executionEvidence[8].safetyScope,
    "Continue with authenticated browser/e2e checks for capture voice fluidity, VAD field behavior, report renderer, document preview navigation, and publication confirmation.",
  ],
  [
    executionEvidence[9].date,
    "Phase 3 Collections API + worker execution",
    "Executed local Collections API and worker pytest files covering ledger, inventory, previews, search, diagnostics, upload queueing, worker jobs, synthetic delete, BM25 artifacts and SPL wave ledger finalization.",
    `${executionEvidence[9].result}; ${mappedPassedCountForEvidence(executionEvidence[9].id)} workbook test cases mapped as Pass.`,
    executionEvidence[9].safetyScope,
    "Continue with authenticated browser/e2e checks on safe synthetic collections and avoid any real Andritz/SFTP mutation unless explicitly approved.",
  ],
  [
    executionEvidence[10].date,
    "Phase 3 SFTP/Secure Deposit synthetic execution",
    "Executed local Secure Deposit API/service and SPL wave importer pytest files covering synthetic link/session auth, previews, downloads, promotion payloads, sidecar reconciliation/quarantine, wave planning and namespace/collision guards.",
    `${executionEvidence[10].result}; ${mappedPassedCountForEvidence(executionEvidence[10].id)} workbook test cases mapped as Pass.`,
    executionEvidence[10].safetyScope,
    "Continue with authenticated browser/e2e checks and read-only VM validation; do not mutate real Andritz SFTP deposits or collections without explicit approval.",
  ],
  [
    executionEvidence[11].date,
    "Phase 4 frontend navigation guard remediation",
    "Fixed stale navigation i18n guard that passed while checking zero keys, added missing FR/EN nav.connectors dictionary entries, and reran i18n guard, UI chrome guard, and production build.",
    `${executionEvidence[11].result}; ${mappedPassedCountForEvidence(executionEvidence[11].id)} workbook test case mapped as Pass; DEF-2026-06-23-SFTP-003 fixed.`,
    executionEvidence[11].safetyScope,
    "Continue with authenticated browser/e2e checks for actual connector-card visibility, direct-route permission behavior, and SFTP connector UX.",
  ],
  [
    executionEvidence[12].date,
    "Phase 3 mocked browser route smoke",
    "Added and executed a local Playwright smoke with mocked auth/workspace/API responses for the Andritz workspace, covering first-screen render of Chat, Knowledge Capture, Collections and SFTP connector entry.",
    `${executionEvidence[12].result}; ${mappedPassedCountForEvidence(executionEvidence[12].id)} workbook test cases mapped as Pass.`,
    executionEvidence[12].safetyScope,
    "Continue with authenticated browser/e2e against a safe real test account and mobile/voice validation; keep real SFTP deposits and collections read-only unless explicitly approved.",
  ],
  [
    executionEvidence[13].date,
    "Phase 3 mocked mobile route smoke",
    "Extended the local Playwright Andritz route smoke with a mobile viewport pass for Chat, Knowledge Capture, Collections and SFTP connector entry while keeping all API traffic mocked.",
    `${executionEvidence[13].result}; ${mappedPassedCountForEvidence(executionEvidence[13].id)} workbook test cases mapped as Pass.`,
    executionEvidence[13].safetyScope,
    "Continue with authenticated mobile UX checks against a safe real test account and real audio/VAD field validation; do not mutate real Andritz SFTP deposits or collections without explicit approval.",
  ],
  [
    executionEvidence[14].date,
    "Phase 4 reviewer capture IAM remediation",
    "Fixed the Knowledge Capture IAM manifest so workspace reviewers can create capture sessions and operate only their own sessions, then verified the true enforced API path without bypassing permissions.",
    `${executionEvidence[14].result}; ${mappedPassedCountForEvidence(executionEvidence[14].id)} workbook test cases mapped as Pass; DEF-2026-06-23-KCAP-040 fixed.`,
    executionEvidence[14].safetyScope,
    "Continue with authenticated browser validation that the reviewer UI button is enabled and the full capture flow works against a safe test account.",
  ],
  [
    executionEvidence[15].date,
    "Phase 4 reviewer IAM matrix API validation",
    "Added and executed an IAM API test proving the matrix consumed by the frontend exposes reviewer capture create/update/execute permissions under workspace-local IAM enforcement.",
    `${executionEvidence[15].result}; ${mappedPassedCountForEvidence(executionEvidence[15].id)} workbook test case mapped as Pass.`,
    executionEvidence[15].safetyScope,
    "Continue with real authenticated reviewer browser validation when a safe test account is available.",
  ],
  [
    executionEvidence[16].date,
    "Phase 3 mocked reviewer capture UI smoke",
    "Extended the local Playwright Andritz smoke with a reviewer IAM matrix scenario and verified the Knowledge Capture new-session button is visible and enabled.",
    `${executionEvidence[16].result}; ${mappedPassedCountForEvidence(executionEvidence[16].id)} workbook test case mapped as Pass.`,
    executionEvidence[16].safetyScope,
    "Continue with the same reviewer journey against a safe real backend account before marking the end-to-end workflow complete.",
  ],
  [
    executionEvidence[17].date,
    "Phase 3 unauthenticated route guard smoke",
    "Extended the local Playwright Andritz smoke with no-token route guard checks for Recherche chat, Knowledge, Knowledge Capture and Secure Deposit, and a disabled SFTP workspace-settings catalogue-state check.",
    `${executionEvidence[17].result}; ${mappedPassedCountForEvidence(executionEvidence[17].id)} workbook test cases mapped as Pass.`,
    executionEvidence[17].safetyScope,
    "Continue with authenticated real-backend browser journeys when a safe test account is available.",
  ],
  [
    executionEvidence[18].date,
    "Phase 3 Collections error-state smoke",
    "Extended the local Playwright Andritz smoke with a mocked /documents/collections 500 response and fixed the Knowledge page to show an explicit retryable error state with mutation controls disabled instead of the legitimate empty-collections state.",
    `${executionEvidence[18].result}; ${mappedPassedCountForEvidence(executionEvidence[18].id)} workbook test case mapped as Pass; DEF-2026-06-23-COL-001 fixed.`,
    executionEvidence[18].safetyScope,
    "Continue with a safe authenticated real-backend browser check for transient collection-load failures; do not mutate real Andritz collections.",
  ],
  [
    executionEvidence[19].date,
    "Phase 3 document browse error-state smoke",
    "Extended the local Playwright Andritz smoke with a mocked /documents/list 500 response and fixed the Knowledge page browse drawer to show an explicit retryable document-load error instead of the legitimate empty-collection state.",
    `${executionEvidence[19].result}; ${mappedPassedCountForEvidence(executionEvidence[19].id)} workbook test case mapped as Pass; DEF-2026-06-23-COL-023 fixed.`,
    executionEvidence[19].safetyScope,
    "Continue with safe authenticated real-backend browser checks for read-only inventory browsing; do not mutate real Andritz documents or collections.",
  ],
  [
    executionEvidence[20].date,
    "Phase 3 Knowledge search error-state smoke",
    "Extended the local Playwright Andritz smoke with a mocked /documents/search 500 response and fixed the Knowledge search drawer to show an inline error while clearing stale result rows.",
    `${executionEvidence[20].result}; ${mappedPassedCountForEvidence(executionEvidence[20].id)} workbook test case mapped as Pass; DEF-2026-06-23-COL-008 fixed.`,
    executionEvidence[20].safetyScope,
    "Continue with safe authenticated real-backend browser checks for read-only search behaviour and source scoping.",
  ],
  [
    executionEvidence[21].date,
    "Phase 3 Knowledge search context-reset smoke",
    "Extended the local Playwright Andritz smoke with a successful search followed by a new collection-scoped search context, and fixed the drawer lifecycle to clear stale query/result/error state.",
    `${executionEvidence[21].result}; ${mappedPassedCountForEvidence(executionEvidence[21].id)} workbook test case mapped as Pass; DEF-2026-06-23-COL-008B fixed.`,
    executionEvidence[21].safetyScope,
    "Continue with safe authenticated real-backend browser checks for read-only search behaviour and source scoping.",
  ],
  [
    executionEvidence[30].date,
    "Phase 3 Chat drop-and-ask upload-failure smoke",
    "Extended the local Playwright Andritz smoke with a mocked /documents/upload-batch 500 response, proving a failed Chat drop-and-ask upload is visible and does not create a stale context or fake session doc.",
    `${executionEvidence[30].result}; ${mappedPassedCountForEvidence(executionEvidence[30].id)} workbook test case mapped as Pass.`,
    executionEvidence[30].safetyScope,
    "Continue with safe local mocks for remaining Chat upload edge cases before any real-backend journey.",
  ],
  [
    executionEvidence[31].date,
    "Phase 4 Chat partial-upload remediation",
    "Extended the local Playwright Andritz smoke with a partial /documents/upload-batch response and fixed ChatWorkspaceComponent so failed upload rows cannot enter the ephemeral context data_refs.",
    `${executionEvidence[31].result}; ${mappedPassedCountForEvidence(executionEvidence[31].id)} workbook test case mapped as Pass; DEF-2026-06-23-CHT-004 fixed.`,
    executionEvidence[31].safetyScope,
    "Continue with safe local mocks for remaining Chat session-doc metadata and deletion edge cases.",
  ],
  [
    executionEvidence[32].date,
    "Phase 3 Chat document metadata-failure smoke",
    "Extended the local Playwright Andritz smoke with a mocked /documents/{id}/metadata 404 response, proving the uploaded session doc falls back to filename display and remains usable in context-scoped chat.",
    `${executionEvidence[32].result}; ${mappedPassedCountForEvidence(executionEvidence[32].id)} workbook test case mapped as Pass.`,
    executionEvidence[32].safetyScope,
    "Continue with safe local mocks for long metadata keywords and session-doc removal edge cases.",
  ],
  [
    executionEvidence[33].date,
    "Phase 3 Chat document metadata keyword smoke",
    "Extended the local Playwright Andritz smoke with a long keyword list from /documents/{id}/metadata, proving the facts panel renders only the first four chips and keeps context-scoped chat usable.",
    `${executionEvidence[33].result}; ${mappedPassedCountForEvidence(executionEvidence[33].id)} workbook test case mapped as Pass.`,
    executionEvidence[33].safetyScope,
    "Continue with safe local mocks for session-doc removal and source-mode transition edge cases.",
  ],
  [
    executionEvidence[34].date,
    "Phase 3 Chat source-mode toggle smoke",
    "Extended the local Playwright Andritz smoke with a + Sources then Only transition after attaching a synthetic session doc, proving the final session and stream payloads use session-doc-only scope.",
    `${executionEvidence[34].result}; ${mappedPassedCountForEvidence(executionEvidence[34].id)} workbook test case mapped as Pass.`,
    executionEvidence[34].safetyScope,
    "Continue with safe local mocks for session-doc removal, then carefully graduate read-only real-backend checks.",
  ],
  [
    executionEvidence[35].date,
    "Phase 4 Chat session-doc detach remediation",
    "Extended the local Playwright Andritz smoke with a synthetic session-doc detach case and added a non-destructive remove control that patches only the ephemeral context data_refs, then clears stale chat scope when no session docs remain.",
    `${executionEvidence[35].result}; ${mappedPassedCountForEvidence(executionEvidence[35].id)} workbook test case mapped as Pass; DEF-2026-06-23-CHT-006 fixed.`,
    executionEvidence[35].safetyScope,
    "Continue with safe local mocks for multi-document detach and context PATCH failure handling.",
  ],
  [
    executionEvidence[36].date,
    "Phase 4 Chat detach PATCH-failure remediation",
    "Extended the local Playwright Andritz smoke with a mocked /contexts/{id} PATCH 500 during session-doc detach, and fixed the component to treat updateContext(null) as failure rather than success.",
    `${executionEvidence[36].result}; ${mappedPassedCountForEvidence(executionEvidence[36].id)} workbook test case mapped as Pass; DEF-2026-06-23-CHT-007 fixed.`,
    executionEvidence[36].safetyScope,
    "Continue with safe local mocks for multi-document detach and later read-only real-backend source-scope checks.",
  ],
  [
    executionEvidence[37].date,
    "Phase 3 Chat multi-doc detach smoke",
    "Extended the local Playwright Andritz smoke with a two-document drop-and-ask upload and removal of only one session doc, proving the ephemeral context data_refs and chat payload preserve the remaining doc scope.",
    `${executionEvidence[37].result}; ${mappedPassedCountForEvidence(executionEvidence[37].id)} workbook test case mapped as Pass.`,
    executionEvidence[37].safetyScope,
    "Continue with safe local mocks for repeated detach/add-back cycles and later read-only real-backend source-scope checks.",
  ],
  [
    executionEvidence[38].date,
    "Phase 3 Chat context recreate smoke",
    "Extended the local Playwright Andritz smoke with a final-doc detach followed by a second upload, proving the new upload creates a fresh ephemeral context payload with only the new filename and the chat payload uses the recreated session-doc scope.",
    `${executionEvidence[38].result}; ${mappedPassedCountForEvidence(executionEvidence[38].id)} workbook test case mapped as Pass.`,
    executionEvidence[38].safetyScope,
    "Continue with safe local mocks for repeated detach/add-back cycles and context create failure handling.",
  ],
  [
    executionEvidence[39].date,
    "Phase 4 Chat context-create failure remediation",
    "Extended the local Playwright Andritz smoke with a mocked /contexts POST 500 after a successful drop-and-ask upload, and fixed ChatWorkspaceComponent so failed context creation rolls back newly-added session docs instead of showing a false attachment.",
    `${executionEvidence[39].result}; ${mappedPassedCountForEvidence(executionEvidence[39].id)} workbook test case mapped as Pass; DEF-2026-06-23-CHT-008 fixed.`,
    executionEvidence[39].safetyScope,
    "Continue with safe local mocks for context update failure on append and later read-only real-backend source-scope checks.",
  ],
  [
    executionEvidence[40].date,
    "Phase 3 Chat append PATCH-failure smoke",
    "Extended the local Playwright Andritz smoke with an existing drop-and-ask context followed by a second upload whose context PATCH fails, proving the UI rolls back only the newly-added document and preserves the first document scope.",
    `${executionEvidence[40].result}; ${mappedPassedCountForEvidence(executionEvidence[40].id)} workbook test case mapped as Pass.`,
    executionEvidence[40].safetyScope,
    "Continue with safe local mocks for remaining Chat source preview and read-only real-backend source-scope checks.",
  ],
  [
    executionEvidence[41].date,
    "Phase 3 Chat source preview smoke",
    "Extended the local Playwright Andritz smoke to open a cited Recherche source preview, verifying the rich-preview request is scoped by collection_name and filename and the preview drawer renders highlighted source text.",
    `${executionEvidence[41].result}; ${mappedPassedCountForEvidence(executionEvidence[41].id)} workbook test case mapped as Pass.`,
    executionEvidence[41].safetyScope,
    "Continue with safe local mocks for missing preview/unauthorized preview fallbacks and later read-only real-backend source-scope checks.",
  ],
  [
    executionEvidence[42].date,
    "Phase 3 Chat source preview error smoke",
    "Extended the local Playwright Andritz smoke to open a cited Recherche source whose rich-preview request returns a mocked 404, proving the preview drawer renders a recoverable error and leaves the chat surface usable.",
    `${executionEvidence[42].result}; ${mappedPassedCountForEvidence(executionEvidence[42].id)} workbook test case mapped as Pass.`,
    executionEvidence[42].safetyScope,
    "Continue with safe local mocks for unauthorized preview and then read-only real-backend source-scope checks.",
  ],
  [
    executionEvidence[43].date,
    "Phase 3 Chat source preview forbidden smoke",
    "Extended the local Playwright Andritz smoke to open a cited Recherche source whose rich-preview request returns a mocked 403, proving the preview drawer renders a permission error without rendering source content.",
    `${executionEvidence[43].result}; ${mappedPassedCountForEvidence(executionEvidence[43].id)} workbook test case mapped as Pass.`,
    executionEvidence[43].safetyScope,
    "Continue with read-only real-backend source-scope checks and broader regression execution.",
  ],
  [
    executionEvidence[44].date,
    "Phase 3 Knowledge Capture written note document-context smoke",
    "Extended the local Playwright Andritz smoke to attach a synthetic capture document, open its preview, persist the active page view, and add a written note whose turn payload carries document_refs and visual_context.",
    `${executionEvidence[44].result}; ${mappedPassedCountForEvidence(executionEvidence[44].id)} workbook test case mapped as Pass.`,
    executionEvidence[44].safetyScope,
    "Continue with safe local mocks for unsupported capture-document upload and then read-only real-backend browser checks.",
  ],
  [
    executionEvidence[45].date,
    "Phase 3 Knowledge Capture document upload failure smoke",
    "Extended the local Playwright Andritz smoke so a failed capture-document upload shows a recoverable warning, creates no fake document/preview/view state, and still allows a written capture note.",
    `${executionEvidence[45].result}; ${mappedPassedCountForEvidence(executionEvidence[45].id)} workbook test case mapped as Pass.`,
    executionEvidence[45].safetyScope,
    "Continue with safe local mocks for unsupported-file selection and then read-only real-backend browser checks.",
  ],
  [
    executionEvidence[46].date,
    "Phase 3 Knowledge Capture multi-document active-view smoke",
    "Extended the local Playwright Andritz smoke so a typed note after opening two synthetic capture documents references only the latest active document, preserving collection/page metadata and avoiding stale document_refs.",
    `${executionEvidence[46].result}; ${mappedPassedCountForEvidence(executionEvidence[46].id)} workbook test case mapped as Pass.`,
    executionEvidence[46].safetyScope,
    "Continue with safe local mocks for PDF page-change emission and then read-only real-backend browser checks.",
  ],
  [
    executionEvidence[47].date,
    "Phase 3 Knowledge Capture document view logging-failure smoke",
    "Extended the local Playwright Andritz smoke so a failed /documents/view audit call does not block capture: the active view remains visible and the following written turn still carries document_refs and visual_context.",
    `${executionEvidence[47].result}; ${mappedPassedCountForEvidence(executionEvidence[47].id)} workbook test case mapped as Pass.`,
    executionEvidence[47].safetyScope,
    "Continue with safe local mocks for PDF page-change emission and then read-only real-backend browser checks.",
  ],
  [
    executionEvidence[48].date,
    "Phase 4 Knowledge Capture upload rejection detail remediation",
    "Fixed capture-document upload errors to surface backend validation details, then extended the local Playwright Andritz smoke with a mocked unsupported-file rejection that creates no fake document state and keeps written capture usable.",
    `${executionEvidence[48].result}; ${mappedPassedCountForEvidence(executionEvidence[48].id)} workbook test case mapped as Pass; DEF-2026-06-23-KCAP-041 fixed.`,
    executionEvidence[48].safetyScope,
    "Continue with safe local mocks for PDF page-change emission and then read-only real-backend browser checks.",
  ],
  [
    executionEvidence[49].date,
    "Phase 3 Knowledge Capture document preview unavailable smoke",
    "Extended the local Playwright Andritz smoke so an unavailable capture-document preview shows a recoverable drawer error while preserving the selected active document context for the following written turn.",
    `${executionEvidence[49].result}; ${mappedPassedCountForEvidence(executionEvidence[49].id)} workbook test case mapped as Pass.`,
    executionEvidence[49].safetyScope,
    "Continue with safe local mocks for PDF page-change emission and then read-only real-backend browser checks.",
  ],
  [
    executionEvidence[50].date,
    "Phase 3 Collections document inventory drawer smoke",
    "Extended the local Playwright Andritz smoke so the Knowledge page opens a successful document inventory drawer, proves /documents/list is scoped to the selected synthetic collection, and verifies the loaded PDF row before any preview/delete action.",
    `${executionEvidence[50].result}; ${mappedPassedCountForEvidence(executionEvidence[50].id)} workbook test case mapped as Pass.`,
    executionEvidence[50].safetyScope,
    "Continue with safe local mocks for empty inventory and read-only real-backend browser checks.",
  ],
  [
    executionEvidence[51].date,
    "Phase 3 Collections empty inventory drawer smoke",
    "Extended the local Playwright Andritz smoke so a successful empty /documents/list response is rendered as Empty collection, while preview/delete actions and load-error messaging remain absent.",
    `${executionEvidence[51].result}; ${mappedPassedCountForEvidence(executionEvidence[51].id)} workbook test case mapped as Pass.`,
    executionEvidence[51].safetyScope,
    "Continue with read-only real-backend browser checks for collection inventory browsing and source scoping.",
  ],
  [
    executionEvidence[52].date,
    "Phase 3 Collections document preview fallback smoke",
    "Extended the local Playwright Andritz smoke so the Knowledge page opens a document preview from the collection inventory, proves both list and preview requests are scoped to the selected synthetic collection, and verifies the download fallback renders.",
    `${executionEvidence[52].result}; ${mappedPassedCountForEvidence(executionEvidence[52].id)} workbook test case mapped as Pass.`,
    executionEvidence[52].safetyScope,
    "Continue with safe local mocks for unauthorized collection previews and then read-only real-backend browser checks.",
  ],
  [
    executionEvidence[53].date,
    "Phase 3 Collections document preview sanitization smoke",
    "Extended the local Playwright Andritz smoke so script-like document preview content returned from the collection preview endpoint is rendered inertly as text and does not execute in the browser.",
    `${executionEvidence[53].result}; ${mappedPassedCountForEvidence(executionEvidence[53].id)} workbook test case mapped as Pass.`,
    executionEvidence[53].safetyScope,
    "Continue with unauthorized collection preview fallback and read-only real-backend browser checks.",
  ],
  [
    executionEvidence[54].date,
    "Phase 3 Collections forbidden preview smoke",
    "Extended the local Playwright Andritz smoke so a denied collection preview after a prior successful preview returns a permission error without rendering stale document content, binary fallback copy or a download action.",
    `${executionEvidence[54].result}; ${mappedPassedCountForEvidence(executionEvidence[54].id)} workbook test case mapped as Pass.`,
    executionEvidence[54].safetyScope,
    "Continue with read-only real-backend browser checks for collection preview permissions and inventory scoping.",
  ],
  [
    executionEvidence[55].date,
    "Phase 3 Collections document delete confirmation smoke",
    "Extended the local Playwright Andritz smoke so a synthetic document delete first opens a confirmation dialog without issuing DELETE, then sends one scoped DELETE only after the explicit user confirmation.",
    `${executionEvidence[55].result}; ${mappedPassedCountForEvidence(executionEvidence[55].id)} workbook test case mapped as Pass.`,
    executionEvidence[55].safetyScope,
    "Continue with read-only real-backend browser checks and keep any destructive collection/SFTP tests synthetic unless explicitly approved.",
  ],
  [
    executionEvidence[56].date,
    "Phase 3 Collections collection delete typed-confirmation smoke",
    "Extended the local Playwright Andritz smoke so a synthetic collection delete keeps the confirm action disabled until the exact collection name is typed, then sends one mocked DELETE only after explicit confirmation.",
    `${executionEvidence[56].result}; ${mappedPassedCountForEvidence(executionEvidence[56].id)} workbook test case mapped as Pass.`,
    executionEvidence[56].safetyScope,
    "Continue with read-only real-backend browser checks and keep real collection/SFTP delete validation out of scope unless explicitly approved.",
  ],
  [
    executionEvidence[57].date,
    "Phase 3 Collections forbidden delete rollback smoke",
    "Extended the local Playwright Andritz smoke so confirmed collection/document delete requests that return 403 show the backend detail and leave the synthetic collection/document visible.",
    `${executionEvidence[57].result}; ${mappedPassedCountForEvidence(executionEvidence[57].id)} workbook test cases mapped as Pass.`,
    executionEvidence[57].safetyScope,
    "Continue with read-only real-backend browser checks; keep destructive delete validation synthetic unless explicitly approved.",
  ],
  [
    executionEvidence[58].date,
    "Phase 3 Collections collection create smoke",
    "Extended the local Playwright Andritz smoke so synthetic collection creation requires explicit user input, sends the scoped collection_name query, appears after mocked reload, and forbidden creation does not create stale UI state.",
    `${executionEvidence[58].result}; ${mappedPassedCountForEvidence(executionEvidence[58].id)} workbook test cases mapped as Pass.`,
    executionEvidence[58].safetyScope,
    "Continue with safe local upload/create edge cases before any read-only real-backend browser checks.",
  ],
  [
    executionEvidence[59].date,
    "Phase 3 SFTP staging queue smoke",
    "Extended the local Playwright Andritz smoke with a synthetic SFTP staging queue: three mocked deposit files load into received/all status controls, queue search resolves a promoted file in component state, and no promote, bulk-promote or archive-download request is sent.",
    `${executionEvidence[59].result}; ${mappedPassedCountForEvidence(executionEvidence[59].id)} workbook test case mapped as Pass.`,
    executionEvidence[59].safetyScope,
    "Continue with SFTP read-only queue/preview/operations browser coverage; keep promote/reconcile mutations synthetic unless explicitly approved.",
  ],
  [
    executionEvidence[60].date,
    "Phase 3 SFTP operations and indexing assist smoke",
    "Extended the local Playwright Andritz smoke with a synthetic SFTP operations snapshot and indexing assist run: live upload, dry-run reconciliation, target collection indexing job and advisory promote-now recommendation render in the browser.",
    `${executionEvidence[60].result}; ${mappedPassedCountForEvidence(executionEvidence[60].id)} workbook test cases mapped as Pass.`,
    executionEvidence[60].safetyScope,
    "Continue with safe SFTP preview/archive browser coverage and read-only real-backend checks; keep promote/reconcile/quarantine mutations synthetic unless explicitly approved.",
  ],
  [
    executionEvidence[61].date,
    "Phase 3 SFTP preview/archive smoke",
    "Extended the local Playwright Andritz smoke with a synthetic staged-file preview and ZIP member preview: both render in the SFTP drawer while download and promotion endpoints remain untouched.",
    `${executionEvidence[61].result}; ${mappedPassedCountForEvidence(executionEvidence[61].id)} workbook test case mapped as Pass.`,
    executionEvidence[61].safetyScope,
    "Continue with read-only real-backend SFTP inventory/preview checks when a safe account is available; keep downloads/promotions/reconcile/quarantine synthetic unless explicitly approved.",
  ],
  [
    executionEvidence[62].date,
    "Phase 3 SFTP target collection smoke",
    "Extended the local Playwright Andritz smoke so selecting an alternate synthetic Knowledge collection updates the SFTP target collection and feeds that collection_slug into indexing assist.",
    `${executionEvidence[62].result}; ${mappedPassedCountForEvidence(executionEvidence[62].id)} workbook test case mapped as Pass.`,
    executionEvidence[62].safetyScope,
    "Continue with read-only real-backend connector validation when safe; keep target promotion execution synthetic unless explicitly approved.",
  ],
  [
    executionEvidence[63].date,
    "Phase 3 SFTP deposit link copy smoke",
    "Extended the local Playwright Andritz smoke so copying an existing synthetic deposit URL writes only the public URL to a controlled clipboard stub, while stored-link password text and link/promotion/reconcile mutations remain absent.",
    `${executionEvidence[63].result}; ${mappedPassedCountForEvidence(executionEvidence[63].id)} workbook test cases mapped as Pass.`,
    executionEvidence[63].safetyScope,
    "Continue with read-only real-backend connector validation when safe; keep link creation/rotation/revocation and deposit promotion synthetic unless explicitly approved.",
  ],
  [
    executionEvidence[64].date,
    "Phase 3 SFTP clipboard failure smoke",
    "Extended the local Playwright Andritz smoke so a denied clipboard write shows a recoverable Copy failed message while avoiding URL-copied success state and all link/promotion/reconcile mutations.",
    `${executionEvidence[64].result}; ${mappedPassedCountForEvidence(executionEvidence[64].id)} workbook test case mapped as Pass.`,
    executionEvidence[64].safetyScope,
    "Continue with read-only real-backend connector validation when safe; keep link creation/rotation/revocation and deposit promotion synthetic unless explicitly approved.",
  ],
  [
    executionEvidence[65].date,
    "Phase 3 SFTP link-filter empty-search smoke",
    "Extended the local Playwright Andritz smoke so selecting a secondary synthetic deposit link scopes the staging queue correctly, then a no-match search shows a safe empty state while file data remains scoped and no promotion/archive mutation is sent.",
    `${executionEvidence[65].result}; ${mappedPassedCountForEvidence(executionEvidence[65].id)} workbook test cases mapped as Pass.`,
    executionEvidence[65].safetyScope,
    "Continue with read-only real-backend connector validation when safe; keep link creation/rotation/revocation and deposit promotion synthetic unless explicitly approved.",
  ],
  [
    executionEvidence[66].date,
    "Phase 3 SFTP link lifecycle smoke",
    "Extended the local Playwright Andritz smoke so synthetic link creation, one-time secret hiding, password rotation and revocation remain explicit, with stored-list passwords hidden and no staged-file promotion or reconciliation side effect.",
    `${executionEvidence[66].result}; ${mappedPassedCountForEvidence(executionEvidence[66].id)} workbook test case mapped as Pass.`,
    executionEvidence[66].safetyScope,
    "Continue with read-only real-backend connector validation when safe; keep real link creation/rotation/revocation and deposit promotion out of automated tests unless explicitly approved.",
  ],
  [
    executionEvidence[67].date,
    "Phase 3 SFTP forbidden link management smoke",
    "Extended the local Playwright Andritz smoke so mocked 403 responses for synthetic link creation, rotation and revocation show recoverable errors without creating fake credential/link state or touching staged-file workflows.",
    `${executionEvidence[67].result}; ${mappedPassedCountForEvidence(executionEvidence[67].id)} workbook test case mapped as Pass.`,
    executionEvidence[67].safetyScope,
    "Continue with read-only real-backend connector validation when safe; keep real link creation/rotation/revocation and deposit promotion out of automated tests unless explicitly approved.",
  ],
  [
    executionEvidence[68].date,
    "Phase 3 SFTP disabled direct-route smoke",
    "Extended the local Playwright Andritz smoke so a mocked secure-deposit disabled health state on direct /connectors/sftp access shows the disabled warning, disables create-link controls, keeps existing link visibility read-only and avoids link/staging mutations.",
    `${executionEvidence[68].result}; ${mappedPassedCountForEvidence(executionEvidence[68].id)} workbook test cases mapped as Pass.`,
    executionEvidence[68].safetyScope,
    "Continue with read-only real-backend connector validation when safe; keep real link creation/rotation/revocation and deposit promotion out of automated tests unless explicitly approved.",
  ],
  [
    executionEvidence[69].date,
    "Phase 3 SFTP enabled health/no-secret smoke",
    "Extended the local Playwright Andritz smoke so a mocked secure-deposit enabled health state on direct /connectors/sftp access enables create-link controls, removes the disabled warning, verifies the health payload shape, and proves no secret-like fields or page-load mutations are exposed.",
    `${executionEvidence[69].result}; ${mappedPassedCountForEvidence(executionEvidence[69].id)} workbook test cases mapped as Pass.`,
    executionEvidence[69].safetyScope,
    "Continue with read-only real-backend connector validation when safe; keep real link creation/rotation/revocation and deposit promotion out of automated tests unless explicitly approved.",
  ],
  [
    executionEvidence[70].date,
    "Phase 4 SFTP indexing monitor failure remediation",
    "Fixed SFTP /documents/jobs failures so manual pipeline refresh shows a visible non-blocking error instead of silently looking like an empty pipeline, then extended the local Playwright Andritz smoke to verify controls remain usable and no staged-file/link mutations occur.",
    `${executionEvidence[70].result}; ${mappedPassedCountForEvidence(executionEvidence[70].id)} workbook test case mapped as Pass; DEF-2026-06-23-SFTP-016 fixed.`,
    executionEvidence[70].safetyScope,
    "Continue with read-only real-backend connector validation when safe; next safe local target is SFTP polling cleanup or operations failure display without reconcile/quarantine mutation.",
  ],
  [
    executionEvidence[71].date,
    "Phase 4 SFTP reconciliation permission-denial UX",
    "Extended the local Playwright Andritz smoke so a mocked reviewer receives a visible 403 denial when starting an SFTP reconciliation dry run, while the UI recovers and the quarantine/promote/archive paths remain untouched.",
    `${executionEvidence[71].result}; ${mappedPassedCountForEvidence(executionEvidence[71].id)} workbook test case mapped as Pass.`,
    executionEvidence[71].safetyScope,
    "Continue with read-only real-backend connector validation when safe; keep real reconcile/quarantine execution excluded unless explicitly approved.",
  ],
  [
    executionEvidence[72].date,
    "Phase 4 SFTP quarantine confirmation safety",
    "Extended the local Playwright Andritz smoke so a synthetic SFTP quarantine action opens the browser confirmation and, when dismissed, sends no reconciliation/quarantine request while leaving controls usable.",
    `${executionEvidence[72].result}; ${mappedPassedCountForEvidence(executionEvidence[72].id)} workbook test case mapped as Pass.`,
    executionEvidence[72].safetyScope,
    "Continue with read-only real-backend connector validation when safe; keep real quarantine execution excluded unless explicitly approved.",
  ],
  [
    executionEvidence[73].date,
    "Phase 4 SFTP operations monitor failure visibility",
    "Extended the local Playwright Andritz smoke so a mocked /sftp/operations failure is displayed after initial load and manual refresh, loading clears, and production-sensitive SFTP actions remain untouched.",
    `${executionEvidence[73].result}; ${mappedPassedCountForEvidence(executionEvidence[73].id)} workbook test case mapped as Pass.`,
    executionEvidence[73].safetyScope,
    "Continue with read-only real-backend connector validation when safe; keep real reconcile/quarantine execution excluded unless explicitly approved.",
  ],
  [
    executionEvidence[74].date,
    "Phase 4 SFTP reconciliation dry-run UX",
    "Extended the local Playwright Andritz smoke so the SFTP Run check action completes a mocked dry-run job, refreshes the operations snapshot, and keeps quarantine/promote/archive paths untouched.",
    `${executionEvidence[74].result}; ${mappedPassedCountForEvidence(executionEvidence[74].id)} workbook test case mapped as Pass.`,
    executionEvidence[74].safetyScope,
    "Continue with read-only real-backend connector validation when safe; keep real reconcile/quarantine execution excluded unless explicitly approved.",
  ],
  [
    executionEvidence[75].date,
    "Phase 4 SFTP file-download failure recovery",
    "Extended the local Playwright Andritz smoke so a synthetic SFTP file download failure shows a visible fallback, re-enables the Download file control, and keeps promote/reconcile/archive paths untouched.",
    `${executionEvidence[75].result}; ${mappedPassedCountForEvidence(executionEvidence[75].id)} workbook test case mapped as Pass.`,
    executionEvidence[75].safetyScope,
    "Continue with read-only real-backend connector validation when safe; keep real download/promote/reconcile/quarantine execution excluded unless explicitly approved.",
  ],
  [
    executionEvidence[76].date,
    "Phase 4 SFTP staging ZIP failure recovery",
    "Extended the local Playwright Andritz smoke so a synthetic SFTP staging ZIP download failure shows a visible fallback, re-enables the Download ZIP control, and keeps promote/reconcile/file-download paths untouched.",
    `${executionEvidence[76].result}; ${mappedPassedCountForEvidence(executionEvidence[76].id)} workbook test case mapped as Pass.`,
    executionEvidence[76].safetyScope,
    "Continue with read-only real-backend connector validation when safe; keep real download/promote/reconcile/quarantine execution excluded unless explicitly approved.",
  ],
  [
    executionEvidence[77].date,
    "Phase 3 Chat document metadata facts smoke",
    "Extended the local Playwright Andritz smoke so a synthetic Chat drop-and-ask upload hydrates document metadata, renders title/page/token/chunk/keyword facts, and still sends the next chat turn with the ephemeral context.",
    `${executionEvidence[77].result}; ${mappedPassedCountForEvidence(executionEvidence[77].id)} workbook test case mapped as Pass.`,
    executionEvidence[77].safetyScope,
    "Continue with authenticated real-backend read-only validation when safe; keep real file upload tests synthetic and isolated unless explicitly approved.",
  ],
  [
    executionEvidence[78].date,
    "Phase 3 Chat selected system scope smoke",
    "Extended the local Playwright Andritz smoke so a synthetic Recherche workspace_chat system can be selected from the Context picker and is propagated to both chat session creation and streaming answer payloads.",
    `${executionEvidence[78].result}; ${mappedPassedCountForEvidence(executionEvidence[78].id)} workbook test case mapped as Pass.`,
    executionEvidence[78].safetyScope,
    "Continue with real-backend read-only validation of actual Andritz system catalogue when safe; do not mutate Systems or workspace source policy in automated QA.",
  ],
  [
    executionEvidence[79].date,
    "Phase 3 Chat stale system fallback smoke",
    "Extended ChatWorkspace so a stale/deleted preselected Recherche system id is resolved against the loaded systems catalogue, falls back to Quick ask, and cannot leak a deleted system scope into session or stream payloads.",
    `${executionEvidence[79].result}; ${mappedPassedCountForEvidence(executionEvidence[79].id)} workbook test case mapped as Pass.`,
    executionEvidence[79].safetyScope,
    "Continue with permission-denial and real-backend read-only validation of the actual Andritz system catalogue when safe; do not mutate Systems or workspace source policy in automated QA.",
  ],
  [
    executionEvidence[80].date,
    "Phase 3 Chat forbidden system catalogue smoke",
    "Extended the local Playwright Andritz smoke so a forbidden /systems catalogue response after a preselected Recherche system id falls back to Quick ask and cannot leak an unreadable system scope into session or stream payloads.",
    `${executionEvidence[80].result}; ${mappedPassedCountForEvidence(executionEvidence[80].id)} workbook test case mapped as Pass.`,
    executionEvidence[80].safetyScope,
    "Continue with real-backend read-only validation of the actual Andritz system catalogue when safe; do not mutate Systems or workspace source policy in automated QA.",
  ],
  [
    executionEvidence[81].date,
    "Phase 3 Chat PDF drop-and-ask smoke",
    "Extended the local Playwright Andritz smoke so a synthetic PDF upload creates an ephemeral Chat context, renders PDF metadata facts, and grounds the next question on that session document without a real upload.",
    `${executionEvidence[81].result}; ${mappedPassedCountForEvidence(executionEvidence[81].id)} workbook test case mapped as Pass.`,
    executionEvidence[81].safetyScope,
    "Continue with unsupported-file and large-file validation using synthetic inputs only; do not upload real Andritz documents unless explicitly approved.",
  ],
  [
    executionEvidence[82].date,
    "Phase 3 Chat unsupported drop-and-ask smoke",
    "Extended the local Playwright Andritz smoke so a synthetic unsupported .bin file returns a mocked backend 400 detail, creates no ephemeral Chat context or attached document, and leaves the next Quick ask unscoped.",
    `${executionEvidence[82].result}; ${mappedPassedCountForEvidence(executionEvidence[82].id)} workbook test case mapped as Pass.`,
    executionEvidence[82].safetyScope,
    "Continue with large-file/boundary validation using synthetic inputs only; do not upload real Andritz documents unless explicitly approved.",
  ],
  [
    executionEvidence[83].date,
    "Phase 3 Chat large drop-and-ask boundary smoke",
    "Extended the local Playwright Andritz smoke so a synthetic XLSX-like upload delays indexing long enough to show progress, renders large-document metadata facts, and grounds the next question on the ephemeral Chat context.",
    `${executionEvidence[83].result}; ${mappedPassedCountForEvidence(executionEvidence[83].id)} workbook test case mapped as Pass.`,
    executionEvidence[83].safetyScope,
    "Continue with read-only real-backend checks when safe; do not upload real Andritz documents unless explicitly approved.",
  ],
  [
    executionEvidence[84].date,
    "Phase 3 Chat expired persist smoke",
    "Extended the local Playwright Andritz smoke so a synthetic drop-and-ask context returns HTTP 410 on Persist, surfaces a recoverable failure, and keeps the current chat usable with session-doc context.",
    `${executionEvidence[84].result}; ${mappedPassedCountForEvidence(executionEvidence[84].id)} workbook test case mapped as Pass.`,
    executionEvidence[84].safetyScope,
    "Continue with read-only real-backend checks when safe; do not upload real Andritz documents unless explicitly approved.",
  ],
  [
    executionEvidence[85].date,
    "Phase 3 Chat no-session-doc scope smoke",
    "Extended the local Playwright Andritz smoke so Quick ask without uploaded session documents keeps context_id/context_mode null while preserving the selected workspace knowledge scope.",
    `${executionEvidence[85].result}; ${mappedPassedCountForEvidence(executionEvidence[85].id)} workbook test case mapped as Pass.`,
    executionEvidence[85].safetyScope,
    "Continue with read-only real-backend checks when safe; do not upload real Andritz documents unless explicitly approved.",
  ],
  [
    executionEvidence[86].date,
    "Phase 3 Chat long-prompt boundary smoke",
    "Extended the local Playwright Andritz smoke so Quick ask accepts a long synthetic prompt, keeps the composer usable, and sends the full prompt with null session-doc context.",
    `${executionEvidence[86].result}; ${mappedPassedCountForEvidence(executionEvidence[86].id)} workbook test case mapped as Pass.`,
    executionEvidence[86].safetyScope,
    "Continue with read-only real-backend checks when safe; do not upload real Andritz documents unless explicitly approved.",
  ],
  [
    executionEvidence[87].date,
    "Phase 3 Chat slow-stream waiting smoke",
    "Extended the local Playwright Andritz smoke so a delayed mocked /chat/stream request keeps visible in-flight progress and streaming send state until the final answer renders.",
    `${executionEvidence[87].result}; ${mappedPassedCountForEvidence(executionEvidence[87].id)} workbook test case mapped as Pass.`,
    executionEvidence[87].safetyScope,
    "Continue with read-only real-backend checks when safe; keep slow/live retrieval validation synthetic unless explicitly approved.",
  ],
  [
    executionEvidence[88].date,
    "Phase 3 Chat interrupted-stream recovery smoke",
    "Extended the local Playwright Andritz smoke so an aborted mocked /chat/stream request surfaces a recoverable transport error, avoids rendering the synthetic success answer, and re-enables the composer.",
    `${executionEvidence[88].result}; ${mappedPassedCountForEvidence(executionEvidence[88].id)} workbook test case mapped as Pass.`,
    executionEvidence[88].safetyScope,
    "Continue with read-only real-backend checks when safe; keep real network fault injection non-mutating and avoid production data uploads.",
  ],
  [
    executionEvidence[89].date,
    "Phase 3 Chat auto-deep retrieval smoke",
    "Extended the local Playwright Andritz smoke so a synthetic deep_queued SSE event creates a persistent Deep Search tracker, polls a mocked workspace job, and promotes the completed deep answer/source summary.",
    `${executionEvidence[89].result}; ${mappedPassedCountForEvidence(executionEvidence[89].id)} workbook test case mapped as Pass.`,
    executionEvidence[89].safetyScope,
    "Continue with real-backend read-only validation when safe; keep auto-deep job execution synthetic unless explicitly approved.",
  ],
  [
    executionEvidence[90].date,
    "Phase 3 Knowledge Capture no-plan finalization failure smoke",
    "Extended the local Playwright Andritz smoke so a synthetic no-plan capture with a written turn handles a mocked closure/finalization 504 by staying on the active capture session.",
    `${executionEvidence[90].result}; ${mappedPassedCountForEvidence(executionEvidence[90].id)} workbook test case mapped as Pass.`,
    executionEvidence[90].safetyScope,
    "Continue with real-backend read-only validation when safe; keep finalization-failure injection mocked unless explicitly approved.",
  ],
  [
    executionEvidence[91].date,
    "Phase 3 Knowledge Capture empty no-plan finish smoke",
    "Extended the local Playwright Andritz smoke so finishing a synthetic empty free-conversation capture returns proposal=null, keeps the user in the session, and creates no bogus report or publication.",
    `${executionEvidence[91].result}; ${mappedPassedCountForEvidence(executionEvidence[91].id)} workbook test case mapped as Pass.`,
    executionEvidence[91].safetyScope,
    "Continue with real-backend read-only validation when safe; keep empty-session finish checks synthetic unless explicitly approved.",
  ],
  [
    executionEvidence[92].date,
    "Phase 3 Knowledge Capture guided-plan written note smoke",
    "Extended the local Playwright Andritz smoke so a synthetic plan-build session validates topics, starts in guided/manual mode, and submits a typed complement tied to the active plan question.",
    `${executionEvidence[92].result}; ${mappedPassedCountForEvidence(executionEvidence[92].id)} workbook test case mapped as Pass.`,
    executionEvidence[92].safetyScope,
    "Continue with real-backend read-only validation when safe; keep guided-plan browser capture checks mocked unless explicitly approved.",
  ],
  [
    executionEvidence[93].date,
    "Phase 3 Knowledge Capture guided-plan section switch smoke",
    "Extended the local Playwright Andritz smoke so a synthetic guided-plan session switches to another plan rail subtopic before submitting a typed complement tied to the newly selected question.",
    `${executionEvidence[93].result}; ${mappedPassedCountForEvidence(executionEvidence[93].id)} workbook test case mapped as Pass.`,
    executionEvidence[93].safetyScope,
    "Continue with real-backend read-only validation when safe; keep guided-plan browser capture checks mocked unless explicitly approved.",
  ],
  [
    executionEvidence[94].date,
    "Phase 3 Knowledge Capture guided-plan active-document smoke",
    "Extended the local Playwright Andritz smoke so a synthetic guided-plan session switches section, previews an uploaded capture document, records the active page view, and submits a typed complement carrying both plan and document context.",
    `${executionEvidence[94].result}; ${mappedPassedCountForEvidence(executionEvidence[94].id)} workbook test case mapped as Pass.`,
    executionEvidence[94].safetyScope,
    "Continue with real-backend read-only validation when safe; keep guided-plan document-reference checks mocked unless explicitly approved.",
  ],
  [
    executionEvidence[95].date,
    "Phase 4 Knowledge Capture voice active-document transport fix",
    "Fixed the voice WebSocket and LiveKit serializers so active document_refs and visual_context produced by Knowledge Capture are carried on audio.frame and audio.endpoint for voice turns.",
    `${executionEvidence[95].result}; ${mappedPassedCountForEvidence(executionEvidence[95].id)} workbook test case mapped as Pass; DEF-2026-06-23-KCAP-042 fixed.`,
    executionEvidence[95].safetyScope,
    "Continue with real-backend voice validation when safe; keep document-reference transport assertions non-destructive.",
  ],
  [
    executionEvidence[96].date,
    "Phase 5 Knowledge Capture voice active-document regression",
    "Added and executed a direct Playwright transport contract for voice document_refs/visual_context on backend WebSocket and LiveKit fallback, then reran the mocked Andritz browser suite in the same lot.",
    `${executionEvidence[96].result}; ${mappedPassedCountForEvidence(executionEvidence[96].id)} workbook test case mapped as Pass; DEF-2026-06-23-KCAP-042 regression-covered.`,
    executionEvidence[96].safetyScope,
    "Continue with real-backend voice validation when safe; keep production capture-document tests non-destructive.",
  ],
  [
    executionEvidence[97].date,
    "Phase 5 Knowledge Capture active-document page-change regression",
    "Fixed parent-state synchronization when the capture document preview emits a page change, then reran the full mocked Andritz browser suite plus voice transport contract.",
    `${executionEvidence[97].result}; ${mappedPassedCountForEvidence(executionEvidence[97].id)} workbook test case mapped as Pass; DEF-2026-06-23-KCAP-043 fixed.`,
    executionEvidence[97].safetyScope,
    "Continue with real-backend capture-document validation when safe; keep preview/page-reference checks non-destructive unless explicitly approved.",
  ],
  [
    executionEvidence[98].date,
    "Phase 5 Knowledge Capture adaptive VAD endpoint regression",
    "Added a direct voice capture contract for robust/manual capture presets, endpoint candidate cancellation during grace, and recorder flush before confirmed silence endpoints, then reran the full mocked Andritz browser suite plus voice transport contracts.",
    `${executionEvidence[98].result}; ${mappedPassedCountForEvidence(executionEvidence[98].id)} workbook test cases mapped as Pass.`,
    executionEvidence[98].safetyScope,
    "Continue with real-device audio validation when safe; keep automated VAD tests synthetic until microphone/browser field runs are explicitly scheduled.",
  ],
  [
    executionEvidence[99].date,
    "Phase 5 Knowledge Capture late partial rendering regression",
    "Added a browser-level Knowledge Capture smoke for same-turn transcript.partial during endpoint STT finalization, then reran the full mocked Andritz browser suite plus voice transport/capture contracts.",
    `${executionEvidence[99].result}; ${mappedPassedCountForEvidence(executionEvidence[99].id)} workbook test case mapped as Pass.`,
    executionEvidence[99].safetyScope,
    "Continue with real-device audio validation when safe; keep late-partial rendering checks mocked unless explicitly approved.",
  ],
  [
    executionEvidence[100].date,
    "Phase 5 Collections global clear safety hardening",
    "Hardened DELETE /documents/clear so it requires workspace admin access, confirm=true, matching confirm_collection_name, and explicit clear_uploads before touching the legacy uploads directory.",
    `${executionEvidence[100].result}; ${mappedPassedCountForEvidence(executionEvidence[100].id)} workbook test cases mapped as Pass; DEF-2026-06-23-COL-018 fixed.`,
    executionEvidence[100].safetyScope,
    "Continue with read-only/mocked validation for remaining collection mutation endpoints; never execute global clear on real Andritz/SFTP data without explicit approval and backup strategy.",
  ],
  [
    executionEvidence[101].date,
    "Phase 5 SFTP secure deposit workspace policy regression",
    "Added local Secure Deposit service coverage for workspace disabled gates on link creation/authentication and case-insensitive extension enforcement across public upload plus SFTP staging.",
    `${executionEvidence[101].result}; ${mappedPassedCountForEvidence(executionEvidence[101].id)} workbook test cases mapped as Pass.`,
    executionEvidence[101].safetyScope,
    "Continue with read-only/mocked validation for remaining SFTP link/download/connector gates; keep real SFTP server and production deposits untouched unless explicitly approved.",
  ],
  [
    executionEvidence[102].date,
    "Phase 5 SFTP critical access-control regression",
    "Added local Secure Deposit API/service coverage for access_id-bound public sessions, owner-scoped rotate/revoke credential invalidation, IAM-denied non-owner staged-file downloads, and upload-only SFTP read/delete rejection.",
    `${executionEvidence[102].result}; ${mappedPassedCountForEvidence(executionEvidence[102].id)} workbook test cases mapped as Pass.`,
    executionEvidence[102].safetyScope,
    "Continue with SPL execution confirmation tests using mocked/local data only; keep real SFTP server and production deposits untouched unless explicitly approved.",
  ],
  [
    executionEvidence[103].date,
    "Phase 5 Knowledge Capture publication-safety regression",
    "Added local Knowledge Capture API/service coverage for review-disabled auto-accept without publication and Markdown export of an accepted proposal without changing published state.",
    `${executionEvidence[103].result}; ${mappedPassedCountForEvidence(executionEvidence[103].id)} workbook test cases mapped as Pass.`,
    executionEvidence[103].safetyScope,
    "Continue with real-backend read-only capture validation when safe; keep publish/ingestion actions explicit and synthetic unless the user approves production mutation.",
  ],
  [
    executionEvidence[104].date,
    "Phase 5 SFTP SPL explicit-execute guard regression",
    "Added local CLI regression coverage proving promote_spl_wave_v1/v2/v3 default to dry-run and never call copy/execute mutation functions unless --execute is explicitly supplied.",
    `${executionEvidence[104].result}; ${mappedPassedCountForEvidence(executionEvidence[104].id)} workbook test cases mapped as Pass.`,
    executionEvidence[104].safetyScope,
    "Continue with authenticated read-only SFTP validation when safe; keep all SPL promotion/nightly-runner execution against real Andritz data behind explicit operator approval.",
  ],
  [
    executionEvidence[105].date,
    "Phase 5 Knowledge Capture permission/content regression",
    "Added local Knowledge Capture API coverage for proposal/session permission denial, contributor proposal-scope filtering, and accepted-proposal content editing without implicit publication.",
    `${executionEvidence[105].result}; ${mappedPassedCountForEvidence(executionEvidence[105].id)} workbook test cases mapped as Pass; DEF-2026-06-23-KCAP-044 fixed.`,
    executionEvidence[105].safetyScope,
    "Continue with authenticated browser and real-backend read-only capture validation when safe; keep destructive session/proposal actions synthetic unless explicitly approved.",
  ],
  [
    executionEvidence[106].date,
    "Phase 5 Collections permission/scope regression",
    "Added local Collections/Knowledge API coverage for admin-only guide/scope/collection metadata mutations and workspace isolation in table-query plus legacy document listing.",
    `${executionEvidence[106].result}; ${mappedPassedCountForEvidence(executionEvidence[106].id)} workbook test cases mapped as Pass; DEF-2026-06-23-COL-019 and DEF-2026-06-23-COL-020 fixed.`,
    executionEvidence[106].safetyScope,
    "Continue with read-only/mocked validation for remaining collection bindings and frontend permission scoping; keep all real Andritz collection/SFTP mutations behind explicit approval.",
  ],
  [
    executionEvidence[107].date,
    "Phase 5 Collections hidden-binding UI smoke",
    "Added a local mocked Playwright collection-detail smoke proving visible bindings render, stale old-slug bindings are ignored, and hidden bindings absent from the permission-scoped /systems catalogue are not rendered.",
    `${executionEvidence[107].result}; ${mappedPassedCountForEvidence(executionEvidence[107].id)} workbook test cases mapped as Pass; DEF-2026-06-23-COL-024 fixed.`,
    executionEvidence[107].safetyScope,
    "Continue with authenticated read-only browser validation when safe; keep collection/SFTP mutation tests synthetic unless explicitly approved.",
  ],
  [
    executionEvidence[108].date,
    "Phase 5 Collections inventory input validation",
    "Added local Collections API coverage proving invalid collection inventory pagination bounds are rejected before any source rows are returned.",
    `${executionEvidence[108].result}; ${mappedPassedCountForEvidence(executionEvidence[108].id)} workbook test case mapped as Pass.`,
    executionEvidence[108].safetyScope,
    "Continue with mocked/read-only validation for large inventories and diagnostics; avoid querying real Andritz large collections for stress unless explicitly approved.",
  ],
  [
    executionEvidence[109].date,
    "Phase 5 Collections empty diagnostics regression",
    "Added local Collections API coverage proving an empty collection keeps inventory and diagnostics coherent at zero/empty even when vector diagnostics are unavailable.",
    `${executionEvidence[109].result}; ${mappedPassedCountForEvidence(executionEvidence[109].id)} workbook test case mapped as Pass.`,
    executionEvidence[109].safetyScope,
    "Continue with mocked/read-only validation for diagnostics failure states and large inventories; keep all real Andritz/SFTP mutation checks behind explicit approval.",
  ],
  [
    executionEvidence[110].date,
    "Phase 5 Collections workspace document-list regression",
    "Added local Collections API coverage proving /documents/list returns current-workspace vector documents with stable filtering and pagination when no ledger collection is present.",
    `${executionEvidence[110].result}; ${mappedPassedCountForEvidence(executionEvidence[110].id)} workbook test case mapped as Pass.`,
    executionEvidence[110].safetyScope,
    "Continue with mocked/read-only validation for large document-list performance and upload/promote flows; keep real Andritz/SFTP data untouched unless explicitly approved.",
  ],
  [
    executionEvidence[111].date,
    "Phase 5 Collections duplicate upload regression",
    "Added local Collections API coverage for same-request duplicate filenames, fixed the unique-constraint crash, and verified inventory remains coherent.",
    `${executionEvidence[111].result}; ${mappedPassedCountForEvidence(executionEvidence[111].id)} workbook test case mapped as Pass; DEF-2026-06-23-COL-025 fixed.`,
    executionEvidence[111].safetyScope,
    "Continue with mocked/synthetic validation for mixed unsupported uploads, batch limits and worker enqueue failures; do not upload into real Andritz collections unless explicitly approved.",
  ],
  [
    executionEvidence[112].date,
    "Phase 5 Collections table-facts regression",
    "Added local Collections API coverage for ledger-backed spreadsheet facts, including sheet/cell/value/source metadata and sheet/query filtering without stale rows.",
    `${executionEvidence[112].result}; ${mappedPassedCountForEvidence(executionEvidence[112].id)} workbook test cases mapped as Pass.`,
    executionEvidence[112].safetyScope,
    "Continue with mocked/synthetic OCR and guide publication checks; keep real Andritz spreadsheet/OCR validation read-only unless explicitly approved.",
  ],
  [
    executionEvidence[113].date,
    "Phase 5 Collections knowledge-scope invalid-input regression",
    "Added local Knowledge Scopes API coverage proving invalid scope patches are rejected before workspace settings or chat default systems are touched.",
    `${executionEvidence[113].result}; ${mappedPassedCountForEvidence(executionEvidence[113].id)} workbook test case mapped as Pass.`,
    executionEvidence[113].safetyScope,
    "Continue with synthetic/read-only validation for guide publication and remaining collection diagnostics; keep real workspace scope edits behind explicit approval.",
  ],
  [
    executionEvidence[114].date,
    "Phase 5 Collections guide publication regression",
    "Added local Knowledge Guides API coverage proving draft guides are not effective until explicitly published, and that publication updates effective guide resolution.",
    `${executionEvidence[114].result}; ${mappedPassedCountForEvidence(executionEvidence[114].id)} workbook test case mapped as Pass.`,
    executionEvidence[114].safetyScope,
    "Continue with mocked/synthetic validation for collection diagnostics and OCR states; keep real guide edits in Andritz behind explicit approval.",
  ],
  [
    executionEvidence[115].date,
    "Phase 5 Collections OCR empty-state regression",
    "Added local Collections API coverage proving OCR document-fact filters return a stable empty state when no OCR or visual layer is indexed.",
    `${executionEvidence[115].result}; ${mappedPassedCountForEvidence(executionEvidence[115].id)} workbook test case mapped as Pass.`,
    executionEvidence[115].safetyScope,
    "Continue with mocked/synthetic validation for OCR duplicate handling and diagnostics failure UI; do not invoke real OCR providers or mutate real Andritz collections without approval.",
  ],
  [
    executionEvidence[116].date,
    "Phase 5 Collections synthetic batch-upload regression",
    "Added local Collections API coverage proving a multi-file synthetic upload creates one queued job, persists originals, creates source rows and keeps inventory coherent.",
    `${executionEvidence[116].result}; ${mappedPassedCountForEvidence(executionEvidence[116].id)} workbook test case mapped as Pass.`,
    executionEvidence[116].safetyScope,
    "Continue with mocked/synthetic validation for mixed unsupported uploads, large batch limits and worker enqueue failures; do not upload into real Andritz collections without explicit approval.",
  ],
  [
    executionEvidence[117].date,
    "Phase 5 Collections large document-list regression",
    "Added local Collections API coverage proving vector-only document listing remains paginated and bounded for a large synthetic result set.",
    `${executionEvidence[117].result}; ${mappedPassedCountForEvidence(executionEvidence[117].id)} workbook test case mapped as Pass.`,
    executionEvidence[117].safetyScope,
    "Continue with mocked/synthetic validation for mixed unsupported uploads, large batch limits and worker enqueue failures; do not query or mutate real Andritz large collections without explicit approval.",
  ],
  [
    executionEvidence[118].date,
    "Phase 4/5 Collections existing-upload remediation",
    "Added local Collections API coverage for adding to an existing collection and reuploading an existing filename, then fixed stale source-ledger metadata on requeue.",
    `${executionEvidence[118].result}; ${mappedPassedCountForEvidence(executionEvidence[118].id)} workbook test cases mapped as Pass; DEF-2026-06-23-COL-026 fixed.`,
    executionEvidence[118].safetyScope,
    "Continue with mocked/synthetic validation for mixed unsupported uploads, large batch limits and worker enqueue failures; keep real Andritz collection uploads behind explicit approval.",
  ],
  [
    executionEvidence[119].date,
    "Phase 4/5 Collections dispatch-failure remediation",
    "Added local Collections API coverage for worker enqueue failure on collection upload, then fixed false queued states by persisting failed job and errored collection status.",
    `${executionEvidence[119].result}; ${mappedPassedCountForEvidence(executionEvidence[119].id)} workbook test case mapped as Pass; DEF-2026-06-23-COL-027 fixed.`,
    executionEvidence[119].safetyScope,
    "Continue with mocked/synthetic validation for mixed unsupported uploads and large batch limits; keep real Andritz collection uploads behind explicit approval.",
  ],
  [
    executionEvidence[120].date,
    "Phase 5 Collections large upload-batch regression",
    "Added local Collections API coverage proving /documents/upload-batch can queue a 40-file synthetic batch with one job and coherent source/original ledgers.",
    `${executionEvidence[120].result}; ${mappedPassedCountForEvidence(executionEvidence[120].id)} workbook test case mapped as Pass.`,
    executionEvidence[120].safetyScope,
    "Continue with mocked/synthetic validation for mixed unsupported uploads; keep real Andritz collection uploads behind explicit approval.",
  ],
  [
    executionEvidence[121].date,
    "Phase 5 Collections diagnostics failure regression",
    "Added local Collections API coverage proving diagnostics remains useful when vector diagnostics fail, by returning SQL ledger counts and fact coverage with unknown drift.",
    `${executionEvidence[121].result}; ${mappedPassedCountForEvidence(executionEvidence[121].id)} workbook test case mapped as Pass.`,
    executionEvidence[121].safetyScope,
    "Continue with mocked/synthetic validation for OCR duplicate facts, mixed unsupported uploads and read-only reindex assessment.",
  ],
  [
    executionEvidence[122].date,
    "Phase 5 Collections mixed upload guard",
    "Added local Collections API coverage for mixed supported/unsupported batch upload and unsupported single upload, then added an atomic extension guard before collection/source/job/original persistence.",
    `${executionEvidence[122].result}; ${mappedPassedCountForEvidence(executionEvidence[122].id)} workbook test case mapped as Pass.`,
    executionEvidence[122].safetyScope,
    "Continue with mocked/synthetic validation for OCR duplicate facts and read-only reindex assessment; keep real Andritz uploads behind explicit approval.",
  ],
  [
    executionEvidence[123].date,
    "Phase 5 Collections large list regression",
    "Added local Collections API coverage proving the collection index handles a large synthetic workspace list while preserving workspace isolation and legacy vector-name filtering.",
    `${executionEvidence[123].result}; ${mappedPassedCountForEvidence(executionEvidence[123].id)} workbook test case mapped as Pass.`,
    executionEvidence[123].safetyScope,
    "Continue with mocked/synthetic validation for OCR duplicate facts and read-only reindex assessment; keep real Andritz collection/SFTP checks non-mutating unless explicitly approved.",
  ],
  [
    executionEvidence[124].date,
    "Phase 5 Collections large reindex dry-run guard",
    "Added local Collections API coverage proving large retrieval-artifact reindex assessment stays read-only when dry_run=true.",
    `${executionEvidence[124].result}; ${mappedPassedCountForEvidence(executionEvidence[124].id)} workbook test case mapped as Pass.`,
    executionEvidence[124].safetyScope,
    "Continue with mocked/synthetic validation for OCR duplicate facts; keep real Andritz reindex/SFTP operations behind explicit approval.",
  ],
  [
    executionEvidence[125].date,
    "Phase 5 Collections OCR duplicate UI smoke",
    "Added local mocked Playwright coverage proving Knowledge detail OCR evidence dedupes duplicate OCR facts while keeping distinct visual warnings visible.",
    `${executionEvidence[125].result}; ${mappedPassedCountForEvidence(executionEvidence[125].id)} workbook test case mapped as Pass.`,
    executionEvidence[125].safetyScope,
    "Collections drafted tests are now all mapped to local synthetic/mocked pass evidence; continue with Chat/KCapture/SFTP remaining validation and real-backend read-only checks when safe.",
  ],
  [
    executionEvidence[126].date,
    "Phase 5 SFTP catalogue navigation smoke",
    "Added local mocked Playwright coverage proving the Connectors catalogue opens SFTP / Secure Deposit and does not trigger any secure-deposit mutation endpoint.",
    `${executionEvidence[126].result}; ${mappedPassedCountForEvidence(executionEvidence[126].id)} workbook test case mapped as Pass.`,
    executionEvidence[126].safetyScope,
    "Continue with remaining SFTP read-only browser validation and real-backend checks only when a safe non-mutating account/path is available.",
  ],
];
writeMatrix(phase, "A1", [phaseHeaders, ...phaseRows]);
styleHeader(phase.getRange("A1:F1"));
styleBody(phase.getRangeByIndexes(1, 0, phaseRows.length, phaseHeaders.length));
setWidths(phase, [16, 26, 70, 52, 58, 62]);

for (const sheet of [summary, matrix, testSheet, defects, execution, phase]) {
  const used = sheet.getUsedRange();
  if (used) {
    used.format.font = { name: "Aptos", size: 10 };
    used.format.verticalAlignment = "Top";
  }
}
summary.getRange("A1").format.font = { name: "Aptos Display", color: "#0B1220", bold: true, size: 16 };
summary.getRange("A17:H17").format.fill = { color: "#E7F0FA" };
summary.getRange("A17:H17").format.font = { name: "Aptos", color: "#0B1220", bold: true, size: 10 };
summary.getRange("A17:H17").format.borders = { preset: "all", style: "thin", color: "#6B7A90" };
styleHeader(matrix.getRange("A1:P1"));
styleHeader(testSheet.getRange("A1:L1"));
styleHeader(defects.getRange("A1:J1"));
styleHeader(execution.getRange("A1:I1"));
styleHeader(phase.getRange("A1:F1"));

const inspect = await workbook.inspect({
  kind: "workbook,sheet,region,formula",
  maxChars: 12000,
  tableMaxRows: 8,
  tableMaxCols: 8,
  tableMaxCellChars: 120,
});
await fs.writeFile(inspectTxt, inspect.ndjson ?? String(inspect), "utf8");

const previewFiles = [];
for (const [sheetName, range, filename] of sheetPreviewRanges) {
  const rendered = await workbook.render({ sheetName, range, autoCrop: "all", scale: 1, format: "png" });
  const previewPath = path.join(outputDir, filename);
  await fs.writeFile(previewPath, new Uint8Array(await rendered.arrayBuffer()));
  previewFiles.push(previewPath);
}

const exported = await SpreadsheetFile.exportXlsx(workbook);
await exported.save(outputXlsx);

console.log(JSON.stringify({
  outputXlsx,
  previewPng,
  previewFiles,
  inspectTxt,
  featureCount: features.length,
  testCount: allTests.length,
}, null, 2));
