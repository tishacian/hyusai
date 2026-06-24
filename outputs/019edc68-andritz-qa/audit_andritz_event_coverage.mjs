import fs from "node:fs";
import path from "node:path";

const repoRoot = path.resolve(import.meta.dirname, "../..");
const outputDir = import.meta.dirname;
const matrixSourcePath = path.join(outputDir, "build_andritz_qa_matrix.mjs");
const outputPath = path.join(outputDir, "andritz_event_coverage_audit.json");

const matrixSource = fs.readFileSync(matrixSourcePath, "utf8");
const featureIds = new Set(
  [...matrixSource.matchAll(/id: "((?:CHT|KCAP|COL|SFTP)-\d+)"/g)].map((match) => match[1]),
);

const files = {
  chatEndpoint: "backend/app/api/v1/endpoints/chat.py",
  chatPanel: "frontend-ng/src/app/features/chat/chat-panel.component.ts",
  sseService: "frontend-ng/src/app/core/sse.service.ts",
  voiceGateway: "backend/app/services/voice_session_gateway.py",
  voiceService: "frontend-ng/src/app/core/voice-session.service.ts",
  captureService: "backend/app/services/knowledge_capture.py",
  captureEndpoint: "backend/app/api/v1/endpoints/knowledge_capture.py",
  captureComponent: "frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts",
};

const eventGroups = [
  group("chat.sse.text", ["CHT-007"], [
    token(files.sseService, "chunk_type?: 'text'"),
    token(files.chatPanel, "chunk.chunk_type === 'text'"),
  ]),
  group("chat.sse.session", ["CHT-014"], [
    token(files.chatPanel, "chunk.chunk_type === 'session'"),
    token(files.chatPanel, "this.chatSessionId = sessionId"),
  ]),
  group("chat.sse.decision_step", ["CHT-007"], [
    token(files.sseService, "decision_step?: unknown"),
    token(files.chatPanel, "chunk.chunk_type === 'decision_step'"),
  ]),
  group("chat.sse.retrieval", ["CHT-009", "CHT-010"], [
    token(files.chatPanel, "chunk.chunk_type === 'retrieval'"),
    token(files.chatPanel, "deep_queued"),
  ]),
  group("chat.sse.sources", ["CHT-008"], [
    token(files.sseService, "sources?: unknown"),
    token(files.chatPanel, "chunk.sources && Array.isArray(chunk.sources)"),
  ]),
  group("chat.sse.eval_pending_run", ["CHT-017"], [
    token(files.sseService, "run_id?: string"),
    token(files.chatPanel, "if (chunk.run_id) turnRunId = chunk.run_id"),
  ]),
  group("chat.sse.error_done", ["CHT-007"], [
    token(files.sseService, "chunk_type?: 'text' | 'decision_step' | 'error'"),
    token(files.sseService, "subject.next({ type: 'done' })"),
  ]),

  group("voice.ws.contract", ["CHT-011", "KCAP-009"], [
    token(files.voiceService, "export type VoiceSessionEventType"),
    token(files.voiceGateway, "async def _send("),
  ]),
  group("voice.session.ready", ["CHT-011", "KCAP-009"], [
    token(files.voiceGateway, '"session.ready"'),
    token(files.captureComponent, "event.type === 'session.ready'"),
    token(files.chatPanel, "event.type === 'session.ready'"),
  ]),
  group("voice.loop.controls", ["CHT-018", "KCAP-010"], [
    token(files.voiceService, "'loop.start'"),
    token(files.voiceGateway, '"loop.start"'),
    token(files.chatPanel, "event.type === 'loop.start' || event.type === 'loop.resume'"),
  ]),
  group("voice.client.audio", ["CHT-011", "KCAP-011"], [
    token(files.voiceService, "'audio.frame'"),
    token(files.voiceService, "'audio.endpoint.auto'"),
    token(files.voiceGateway, 'event_type == "audio.frame"'),
    token(files.voiceGateway, 'event_type in {"audio.endpoint", "audio.endpoint.auto"}'),
  ]),
  group("voice.pause_without_commit", ["KCAP-010", "KCAP-011"], [
    token(files.voiceService, "'audio.pause'"),
    token(files.voiceGateway, 'event_type == "audio.pause"'),
    token(files.captureComponent, "send audio.pause"),
  ]),
  group("voice.transcript.partial", ["CHT-011", "KCAP-012"], [
    token(files.voiceGateway, '"transcript.partial"'),
    token(files.captureComponent, "event.type === 'text.partial' || event.type === 'transcript.partial'"),
    token(files.chatPanel, "event.type === 'text.partial' || event.type === 'transcript.partial'"),
  ]),
  group("voice.text.final", ["CHT-011", "KCAP-012"], [
    token(files.voiceGateway, '"text.final"'),
    token(files.captureComponent, "event.type === 'text.final'"),
    token(files.chatPanel, "event.type === 'text.final'"),
  ]),
  group("voice.runtime.metric", ["KCAP-037", "CHT-011"], [
    token(files.voiceGateway, '"runtime.metric"'),
    token(files.captureComponent, "event.type === 'runtime.metric'"),
    token(files.chatPanel, "event.type === 'runtime.metric'"),
  ]),
  group("voice.client.metric", ["KCAP-037", "CHT-011"], [
    token(files.voiceService, "'client.metric'"),
    token(files.voiceGateway, '"voice.client_metric"'),
    token(files.captureComponent, "emitCaptureClientMetric"),
    token(files.chatPanel, "emitVoiceClientMetric"),
  ]),
  group("voice.oracle.delta", ["KCAP-014", "KCAP-037"], [
    token(files.voiceGateway, '"oracle.delta"'),
    token(files.captureComponent, "event.type === 'oracle.delta' || event.type === 'oracle.superseded'"),
    token(files.chatPanel, "event.type === 'oracle.delta'"),
  ]),
  group("voice.oracle.action_commit", ["KCAP-014"], [
    token(files.voiceGateway, '"oracle.action"'),
    token(files.voiceGateway, '"oracle.commit"'),
    token(files.captureComponent, "event.type === 'oracle.action'"),
    token(files.captureComponent, "event.type === 'oracle.commit'"),
  ]),
  group("voice.oracle.questions", ["KCAP-014", "KCAP-023"], [
    token(files.voiceGateway, '"oracle.questions"'),
    token(files.captureComponent, "event.type === 'oracle.questions'"),
  ]),
  group("voice.section.active", ["KCAP-006", "KCAP-013"], [
    token(files.voiceService, "'section.active'"),
    token(files.voiceGateway, '"section.active"'),
    token(files.captureComponent, "event.type === 'section.active'"),
  ]),
  group("voice.conversation.step", ["KCAP-019", "KCAP-020", "KCAP-039"], [
    token(files.voiceGateway, '"conversation.step"'),
    token(files.captureComponent, "event.type === 'conversation.step'"),
  ]),
  group("voice.capture.finalize.progress", ["KCAP-019", "KCAP-020"], [
    token(files.voiceGateway, '"capture.finalize.progress"'),
    token(files.captureComponent, "event.type === 'capture.finalize.progress'"),
  ]),
  group("voice.audio.out", ["CHT-012", "KCAP-010"], [
    token(files.voiceGateway, '"audio.out"'),
    token(files.captureComponent, "event.type === 'audio.out'"),
  ]),
  group("voice.session.error", ["CHT-011", "KCAP-009"], [
    token(files.voiceService, "'session.error'"),
    token(files.voiceGateway, '"session.error"'),
  ]),

  group("kc.event.plan_dialogue", ["KCAP-005", "KCAP-006"], [
    token(files.captureService, 'event_type="plan_dialogue_turn"'),
    token(files.captureService, 'event_type="oracle_topic_refresh"'),
  ]),
  group("kc.event.plan_created_amended_approved", ["KCAP-002", "KCAP-005", "KCAP-006"], [
    token(files.captureService, 'event_type="capture_plan_created"'),
    token(files.captureService, 'event_type="capture_plan_amended"'),
    token(files.captureService, 'event_type="capture_plan_approved"'),
  ]),
  group("kc.event.question_bank", ["KCAP-006", "KCAP-032"], [
    token(files.captureService, 'event_type="question_bank_generating"'),
    token(files.captureService, 'event_type="question_bank_ready"'),
  ]),
  group("kc.event.hints", ["KCAP-013", "KCAP-032"], [
    token(files.captureService, 'event_type="hint_pushed"'),
    token(files.captureService, 'event_type="hint_resolved"'),
    token(files.captureService, 'event_type="hint_deferred"'),
    token(files.captureComponent, "event.type === 'capture.hint_pushed'"),
  ]),
  group("kc.event.pause_resume_close", ["KCAP-007", "KCAP-019"], [
    token(files.captureService, 'event_type="capture_session_paused"'),
    token(files.captureService, 'event_type="capture_session_resumed"'),
    token(files.captureService, 'event_type="capture_session_completed"'),
  ]),
  group("kc.event.documents", ["KCAP-015", "KCAP-016", "KCAP-017", "KCAP-021"], [
    token(files.captureService, 'event_type="capture_document_uploaded"'),
    token(files.captureService, 'event_type="capture_document_viewed"'),
  ]),
  group("kc.event.turns", ["KCAP-008", "KCAP-012", "KCAP-030"], [
    token(files.captureService, 'event_type="stt_final"'),
    token(files.captureService, 'event_type="expert_turn_finalized" if speaker == "expert" else "transcript_turn_recorded"'),
    token(files.captureService, 'event_type="transcript_amended"'),
  ]),
  group("kc.event.proposal", ["KCAP-020", "KCAP-024", "KCAP-025", "KCAP-034"], [
    token(files.captureService, 'event_type="proposal_generated"'),
    token(files.captureService, 'event_type="proposal_reviewed"'),
    token(files.captureService, 'event_type="proposal_report_edited"'),
    token(files.captureService, 'event_type="kc.proposal.published"'),
  ]),
  group("kc.event.open_questions", ["KCAP-023"], [
    token(files.captureService, 'event_type="proposal_open_question_status_updated"'),
    token(files.captureService, 'event_type="proposal_open_question_answered"'),
  ]),
  group("kc.event.retrieval_prefetch", ["KCAP-013"], [
    token(files.captureService, 'event_type="retrieval_prefetch_started"'),
    token(files.captureService, 'event_type=event_type'),
  ]),
  group("kc.event.quality", ["KCAP-029"], [
    token(files.captureService, 'event_type="quality_item_deferred"'),
  ]),
  group("kc.event.chat_correction", ["CHT-013"], [
    token(files.captureEndpoint, 'event_type="kc.chat_correction.created"'),
    token(files.captureService, 'event_type="chat_correction_voice"'),
  ]),
];

const resolvedGroups = eventGroups.map(resolveGroup);
const missingSources = resolvedGroups.filter((entry) => !entry.source_found);
const missingFeatureRefs = resolvedGroups
  .flatMap((entry) => entry.feature_ids.map((featureId) => ({ featureId, entry })))
  .filter((item) => !featureIds.has(item.featureId));

const audit = {
  generated_at: new Date().toISOString(),
  scope: {
    workspace: "andritz",
    systems: ["Chat Recherche", "Knowledge Capture", "Collections", "SFTP Andritz"],
    safety: "static runtime event-to-feature audit only; no browser, backend, VM, SFTP, collection, vector or object-store mutation",
  },
  matrix: {
    feature_count: featureIds.size,
  },
  events: {
    group_count: resolvedGroups.length,
    missing_source_count: missingSources.length,
    missing_feature_ref_count: missingFeatureRefs.length,
    groups: resolvedGroups,
    missing_sources: missingSources,
    missing_feature_refs: missingFeatureRefs.map((item) => ({
      feature_id: item.featureId,
      event_key: item.entry.key,
    })),
  },
  status: missingSources.length === 0 && missingFeatureRefs.length === 0 ? "pass" : "fail",
};

fs.writeFileSync(outputPath, `${JSON.stringify(audit, null, 2)}\n`);
console.log(JSON.stringify({
  status: audit.status,
  group_count: audit.events.group_count,
  missing_source_count: audit.events.missing_source_count,
  missing_feature_ref_count: audit.events.missing_feature_ref_count,
  output: outputPath,
}, null, 2));

if (audit.status !== "pass") {
  process.exitCode = 1;
}

function group(key, featureIds, tokens) {
  return { key, feature_ids: featureIds, tokens };
}

function token(file, token) {
  return { file, token };
}

function resolveGroup(entry) {
  const tokenLocations = entry.tokens.map((item) => {
    const source = fs.readFileSync(path.join(repoRoot, item.file), "utf8");
    const index = source.indexOf(item.token);
    return {
      ...item,
      found: index >= 0,
      line: index >= 0 ? lineNumber(source, index) : null,
    };
  });
  return {
    ...entry,
    source_found: tokenLocations.every((item) => item.found),
    first_line: tokenLocations.find((item) => item.found)?.line || null,
    token_locations: tokenLocations,
  };
}

function lineNumber(source, index) {
  return source.slice(0, index).split("\n").length;
}
