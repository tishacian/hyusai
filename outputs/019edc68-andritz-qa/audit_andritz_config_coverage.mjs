import fs from "node:fs";
import path from "node:path";

const repoRoot = path.resolve(import.meta.dirname, "../..");
const outputDir = import.meta.dirname;
const matrixSourcePath = path.join(outputDir, "build_andritz_qa_matrix.mjs");
const outputPath = path.join(outputDir, "andritz_config_coverage_audit.json");

const matrixSource = fs.readFileSync(matrixSourcePath, "utf8");
const featureIds = new Set(
  [...matrixSource.matchAll(/id: "((?:CHT|KCAP|COL|SFTP)-\d+)"/g)].map((match) => match[1]),
);

const files = {
  workspaceSettings: "frontend-ng/src/app/features/workspace/chat-knowledge-settings.component.ts",
  voiceGateway: "backend/app/services/voice_session_gateway.py",
  backendConfig: "backend/app/core/config.py",
  secureDeposit: "backend/app/services/secure_deposit.py",
  secureDepositOps: "backend/app/services/secure_deposit_operations.py",
  voiceCaptureConfig: "frontend-ng/src/app/core/voice-capture-config.ts",
  voiceLoopController: "frontend-ng/src/app/core/voice-loop-controller.service.ts",
};

const configGroups = [
  group("workspace.source_scopes", files.workspaceSettings, ["source scopes", "collection_slugs", "top_k", "table_profile_key", "document_profile_key"], ["CHT-015", "COL-005", "COL-021"]),
  group("workspace.knowledge_guides", files.workspaceSettings, ["Knowledge guide", "guide_key", "markdown", "publishGuide"], ["COL-011", "CHT-015"]),
  group("workspace.chat_defaults", files.workspaceSettings, ["ChatSettingsDraft", "prompt_pack", "placeholder", "context_mode"], ["CHT-001", "CHT-003", "CHT-015"]),
  group("workspace.assistant_profiles", files.workspaceSettings, ["assistant_profiles", "assistant_profile_default", "default_knowledge_scope", "voice_loop"], ["CHT-015", "CHT-021", "KCAP-010"]),
  group("workspace.action_packs", files.workspaceSettings, ["WorkspaceActionSettingsDraft", "enabled_packs_text", "hidden_actions_text"], ["CHT-003", "CHT-021"]),

  group("workspace.voice_loop_modes", files.workspaceSettings, ["VoiceLoopSettingsDraft", "default_mode", "session_loop", "realtime"], ["CHT-011", "CHT-018", "KCAP-010"]),
  group("workspace.voice_capture_robustness", files.workspaceSettings, ["capture_mode", "auto_capture_mode_enabled", "rms_threshold", "endpoint_grace_ms"], ["CHT-011", "KCAP-010", "KCAP-011"]),
  group("workspace.voice_vad_timing", files.workspaceSettings, ["silence_ms", "dictation_silence_ms", "min_speech_ms", "vad_hangover_ms", "vad_min_silence_frames_ms"], ["CHT-011", "KCAP-011"]),
  group("workspace.voice_loop_behaviour", files.workspaceSettings, ["auto_send_final_transcript", "auto_endpoint", "auto_rearm_after_tts", "barge_in"], ["CHT-011", "CHT-018", "KCAP-010"]),
  group("workspace.voice_commands", files.workspaceSettings, ["commands_enabled", "trigger_word", "command_packs_text", "stop_phrases_text"], ["CHT-018", "KCAP-036"]),
  group("workspace.voice_output", files.workspaceSettings, ["VoiceOutputSettingsDraft", "latency_profile", "flush_first_chars", "flush_timeout_ms", "interrupt_on_user_speech"], ["CHT-012"]),

  group("workspace.table_intelligence", files.workspaceSettings, ["TableProfileDraft", "metric_aliases_text", "require_compatible_units", "require_cell_citations"], ["COL-009", "COL-013"]),
  group("workspace.document_intelligence", files.workspaceSettings, ["DocumentProfileDraft", "max_candidate_facts", "max_evidence_rows"], ["COL-010", "COL-013"]),
  group("workspace.ocr_settings", files.workspaceSettings, ["OcrSettingsDraft", "provider_priority_text", "scan_detection", "openai_vision_enabled"], ["COL-007", "COL-010"]),

  group("client.capture_mode_persistence", files.voiceCaptureConfig, ["capture_mode", "auto_capture_mode_enabled", "voiceCaptureStorageKey", "resolveVoiceCaptureConfig"], ["CHT-011", "KCAP-010", "KCAP-011"]),
  group("client.vad_controller_metrics", files.voiceLoopController, ["capture_mode", "endpoint_candidate", "endpoint_confirmed", "requestData"], ["CHT-011", "KCAP-011", "KCAP-037"]),

  group("voice.session_runtime_selection", files.voiceGateway, ["provider", "runtime", "model", "language", "fallback_policy"], ["CHT-011", "CHT-012", "KCAP-009"]),
  group("voice.session_oracle_options", files.voiceGateway, ["tandem_oracle", "live_partial_stt_enabled", "live_questions_enabled", "partial_stt_min_interval_ms"], ["KCAP-012", "KCAP-014", "KCAP-037"]),
  group("voice.oracle_throttling_options", files.voiceGateway, ["min_interval_ms", "min_delta_chars", "VoiceTandemOracle"], ["KCAP-014"]),

  group("backend.rag_retrieval_deadlines", files.backendConfig, ["rag_fast_retrieval_deadline_seconds", "rag_deep_retrieval_deadline_seconds", "rag_auto_deep_retrieval_enabled"], ["CHT-009", "CHT-010", "KCAP-013", "COL-008"]),
  group("backend.chat_stream_limits", files.backendConfig, ["chat_history_token_budget", "chat_stream_timeout_seconds"], ["CHT-007", "CHT-014"]),
  group("backend.voice_runtime_catalog", files.backendConfig, ["voice_runtime_default_provider", "voice_runtime_allowed_providers", "voice_realtime_default_transport"], ["CHT-011", "CHT-012", "CHT-019", "KCAP-009"]),
  group("backend.voice_realtime_stt_flags", files.backendConfig, ["voice_realtime_stt_enabled", "voice_realtime_stt_workspace_slugs", "voice_realtime_stt_max_turn_ms"], ["CHT-019", "KCAP-009"]),
  group("backend.voice_oracle_worker", files.backendConfig, ["voice_oracle_live_questions_retrieval_enabled", "voice_oracle_retrieval_via_worker", "voice_oracle_retrieval_timeout_seconds"], ["KCAP-014", "KCAP-037"]),
  group("backend.voice_transcript_rewrite", files.backendConfig, ["voice_transcript_rewrite_enabled", "voice_transcript_rewrite_timeout_ms", "voice_transcript_glossary_max_terms"], ["CHT-011", "KCAP-012"]),
  group("backend.voice_partial_stt_interval", files.backendConfig, ["voice_partial_stt_min_interval_ms"], ["CHT-011", "KCAP-012"]),

  group("backend.secure_deposit_enablement", files.backendConfig, ["secure_deposit_enabled_workspace_slugs", "secure_deposit_public_base_url", "secure_deposit_session_ttl_seconds"], ["SFTP-001", "SFTP-002", "SFTP-015"]),
  group("backend.secure_deposit_file_policy", files.backendConfig, ["secure_deposit_default_max_file_size_mb", "secure_deposit_allowed_extensions", "secure_deposit_archive_promotion_max_files"], ["SFTP-003", "SFTP-008", "SFTP-009", "SFTP-011"]),
  group("backend.secure_deposit_storage", files.backendConfig, ["secure_deposit_storage_dir", "secure_deposit_sftp_temp_dir"], ["SFTP-003", "SFTP-005", "SFTP-010"]),
  group("backend.secure_deposit_sftp_server", files.backendConfig, ["secure_deposit_sftp_host", "secure_deposit_sftp_port", "secure_deposit_sftp_host_key_path"], ["SFTP-004", "SFTP-014"]),
  group("service.secure_deposit_workspace_gate", files.secureDeposit, ["secure_deposit", "enabled_workspace_slugs", "settings"], ["SFTP-015"]),
  group("service.secure_deposit_reconciliation", files.secureDepositOps, ["SFTP_RECONCILIATION_JOB_KIND", "sftp_upload_sidecar_path", "run_sftp_reconciliation_job"], ["SFTP-010", "SFTP-016"]),
];

const resolvedGroups = configGroups.map(resolveGroup);
const missingSources = resolvedGroups.filter((entry) => !entry.source_found);
const missingFeatureRefs = resolvedGroups
  .flatMap((entry) => entry.feature_ids.map((featureId) => ({ featureId, entry })))
  .filter((item) => !featureIds.has(item.featureId));

const audit = {
  generated_at: new Date().toISOString(),
  scope: {
    workspace: "andritz",
    systems: ["Chat Recherche", "Knowledge Capture", "Collections", "SFTP Andritz"],
    safety: "static configuration-to-feature audit only; no browser, backend, VM, SFTP, collection, vector or object-store mutation",
  },
  matrix: {
    feature_count: featureIds.size,
  },
  configuration: {
    group_count: resolvedGroups.length,
    missing_source_count: missingSources.length,
    missing_feature_ref_count: missingFeatureRefs.length,
    groups: resolvedGroups,
    missing_sources: missingSources,
    missing_feature_refs: missingFeatureRefs.map((item) => ({
      feature_id: item.featureId,
      config_key: item.entry.key,
      file: item.entry.file,
    })),
  },
  status: missingSources.length === 0 && missingFeatureRefs.length === 0 ? "pass" : "fail",
};

fs.writeFileSync(outputPath, `${JSON.stringify(audit, null, 2)}\n`);
console.log(JSON.stringify({
  status: audit.status,
  group_count: audit.configuration.group_count,
  missing_source_count: audit.configuration.missing_source_count,
  missing_feature_ref_count: audit.configuration.missing_feature_ref_count,
  output: outputPath,
}, null, 2));

if (audit.status !== "pass") {
  process.exitCode = 1;
}

function group(key, relFile, tokens, featureIds) {
  return { key, file: relFile, tokens, feature_ids: featureIds };
}

function resolveGroup(entry) {
  const abs = path.join(repoRoot, entry.file);
  const source = fs.readFileSync(abs, "utf8");
  const tokenLocations = entry.tokens.map((token) => {
    const index = source.indexOf(token);
    return {
      token,
      found: index >= 0,
      line: index >= 0 ? lineNumber(source, index) : null,
    };
  });
  const firstLine = tokenLocations.find((item) => item.found)?.line || null;
  return {
    ...entry,
    source_found: tokenLocations.every((item) => item.found),
    first_line: firstLine,
    token_locations: tokenLocations,
  };
}

function lineNumber(source, index) {
  return source.slice(0, index).split("\n").length;
}
