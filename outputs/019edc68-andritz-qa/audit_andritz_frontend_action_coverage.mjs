import fs from "node:fs";
import path from "node:path";

const repoRoot = path.resolve(import.meta.dirname, "../..");
const outputDir = import.meta.dirname;
const matrixSourcePath = path.join(outputDir, "build_andritz_qa_matrix.mjs");
const outputPath = path.join(outputDir, "andritz_frontend_action_coverage_audit.json");

const matrixSource = fs.readFileSync(matrixSourcePath, "utf8");
const featureIds = new Set(
  [...matrixSource.matchAll(/id: "((?:CHT|KCAP|COL|SFTP)-\d+)"/g)].map((match) => match[1]),
);

const scopedFiles = [
  "frontend-ng/src/app/features/chat/assistant-draft-drawer.component.ts",
  "frontend-ng/src/app/features/chat/chat-overlay.component.ts",
  "frontend-ng/src/app/features/chat/chat-panel.component.ts",
  "frontend-ng/src/app/features/chat/chat-workspace.component.ts",
  "frontend-ng/src/app/features/connectors/connectors-page.component.ts",
  "frontend-ng/src/app/features/connectors/sftp/sftp-connector.component.ts",
  "frontend-ng/src/app/features/deposit/deposit-portal.component.ts",
  "frontend-ng/src/app/features/knowledge/embedding-map.component.ts",
  "frontend-ng/src/app/features/knowledge/knowledge-base.component.ts",
  "frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts",
  "frontend-ng/src/app/features/knowledge/knowledge-view.component.ts",
  "frontend-ng/src/app/features/workspace/chat-knowledge-settings.component.ts",
];

const actionRules = [
  match("chat-panel", /createNewChat|openChatSession|archiveChatSession|deleteChatSession|clearConversation/, ["CHT-014"]),
  match("chat-panel", /send\(|stageActionPrompt|useSuggestion/, ["CHT-002", "CHT-003"]),
  match("chat-panel", /startExecutiveVoiceLoop|stopVoiceExperience|toggleMic/, ["CHT-011", "CHT-018"]),
  match("chat-panel", /toggleTTS|pauseResumeTts/, ["CHT-012"]),
  match("chat-panel", /setSessionDocsMode/, ["CHT-006"]),
  match("chat-panel", /traceOpen|toggleTrail|toggleEval/, ["CHT-007"]),
  match("chat-panel", /gotoSourceTarget|toggleSources|previewSource/, ["CHT-008"]),
  match("chat-panel", /toggleDeepRetrievalDetails|launchDeepSearch/, ["CHT-009"]),
  match("chat-panel", /rate\(|factCheck|openReviewQueue|openQaReview/, ["CHT-017"]),
  match("chat-panel", /toggleCorrection|closeCorrection|submitCorrection|toggleCorrectionMic/, ["CHT-013"]),
  match("chat-panel", /copy\(|demoVoiceChipsDismissed/, ["CHT-007"]),

  match("chat-workspace", /openFlowBuilder/, ["CHT-003", "CHT-021"]),
  match("chat-workspace", /dropOpen|fileInput|onFileSelect|onDragOver|onDragLeave|onDrop|persistContext|detachSessionDoc/, ["CHT-004", "CHT-005", "CHT-006"]),
  match("chat-overlay", /expandToWorkspaceChat/, ["CHT-021"]),
  match("assistant-draft-drawer", /validate|modify|cancel/, ["CHT-017"]),

  match("knowledge-capture", /goSurface|setDashboardTab|openDashboardSession|openDashboardProposal|startNewSessionDraft|refreshPublishedFiches|openPublishedFiche/, ["KCAP-001", "KCAP-028", "KCAP-035"]),
  match("knowledge-capture", /selectedDomain|showAdvancedSetup|createContextFromCollection|toggleDurationUnlimited|selectPlanMode|continueFromPreparation/, ["KCAP-002", "KCAP-004"]),
  match("knowledge-capture", /applyPlanOutlineFormat|selectPlan|generatePlan|approvePlan|validateTopic|addTopic|removeTopic|renameTopic|selectedQuestionId|moveQuestion|removeQuestion|addQuestion|savePlan|plan\/|outline/i, ["KCAP-005", "KCAP-006"]),
  match("knowledge-capture", /onProvidedPlanFile|confirmProvidedPlanReplacement|cancelProvidedPlanReplacement|clearProvidedPlanSource|backToPlanModeSelection|createPlan|dictatePlanDialogue|submitPlanDialogueTurn|finalizePlanBuild/, ["KCAP-003", "KCAP-005", "KCAP-006"]),
  match("knowledge-capture", /pauseSession|resumeSession|startGuidedSession|onPrimaryCaptureAction|finishCapture|interruptSpeech|readCurrentQuestion/, ["KCAP-007", "KCAP-009"]),
  match("knowledge-capture", /sendAnswer|sendWrittenCaptureNote|beginAmend|applyAmend|editingEventId/, ["KCAP-008", "KCAP-030"]),
  match("knowledge-capture", /captureDocument|previewCaptureDocument|DocumentFile|documentInput/, ["KCAP-015", "KCAP-016", "KCAP-017", "KCAP-021"]),
  match("knowledge-capture", /retrieval|previewRetrievalChunk|Suggestion|suggestion/i, ["KCAP-013", "KCAP-032"]),
  match("knowledge-capture", /Oracle|oracle|muteOracle|unmuteOracle|answerOracleQuestion|dismissOracleQuestion|deferOracleQuestion/, ["KCAP-014"]),
  match("knowledge-capture", /createProposal|proposal|review|publish|instruction|openQuestion|toggleReportEditMode/i, ["KCAP-020", "KCAP-022", "KCAP-023", "KCAP-024", "KCAP-025", "KCAP-034"]),
  match("knowledge-capture", /applySessionClosure|closure|finishCurrentSection/, ["KCAP-019"]),
  match("knowledge-capture", /archiveSession|unarchiveSession|requestDeleteSession|confirmDeleteSession|cancelDeleteSession|toggleArchivedSessions/, ["KCAP-027"]),
  match("knowledge-capture", /quality|deferQualityItem|respondToQualityItem/i, ["KCAP-029"]),
  match("knowledge-capture", /setConversationMode/, ["KCAP-039"]),
  match("knowledge-capture", /startClarificationSession/, ["KCAP-023", "KCAP-039"]),
  match("knowledge-capture", /selectCaptureTopic|selectCaptureSubtopic|selectCaptureQuestion|jumpToLatestTranscript/, ["KCAP-006", "KCAP-008"]),

  match("knowledge-view", /onTabChange|loadSources|source|previewDocument|loadChunks|Chunk/i, ["COL-005", "COL-007", "COL-014", "COL-023"]),
  match("knowledge-view", /loadDocumentFacts|documentFact|loadOcrFacts|ocrFact/i, ["COL-010", "COL-013"]),
  match("knowledge-view", /loadTableFacts|tableFact/i, ["COL-009", "COL-013"]),
  match("knowledge-view", /saveCollectionGuide|loadGuideIntoEditor|guide/i, ["COL-011"]),
  match("knowledge-view", /launchRetrievalArtifactJob/, ["COL-012"]),
  match("knowledge-view", /binding/i, ["COL-022"]),

  match("knowledge-base", /createCollection|createOpen|openCreateCollection/, ["COL-002"]),
  match("knowledge-base", /upload|FileSelect|fileInput|onDragOver|onDragLeave|onDrop/i, ["COL-003", "COL-019"]),
  match("knowledge-base", /delete|requestDelete|clear/i, ["COL-004"]),
  match("knowledge-base", /loadCollections|loadBrowsePage|browse|search|filter|previewDoc/i, ["COL-001", "COL-005", "COL-007", "COL-008", "COL-017", "COL-023"]),

  match("embedding-map", /loadGraph|selectNode|zoom|pan|resetView|sample|documentId/i, ["COL-014"]),

  match("sftp-connector", /load\(|loadOperations|loadIndexingMonitor|refreshTargetCollection/, ["SFTP-005", "SFTP-010", "SFTP-015", "SFTP-016"]),
  match("sftp-connector", /createLink|rotate|revoke|focusLinkQueue|secretLink|copy\(absoluteUrl|copy\(link/, ["SFTP-001", "SFTP-017"]),
  match("sftp-connector", /analyzeCurrentView/, ["SFTP-007", "SFTP-016"]),
  match("sftp-connector", /promoteBatch/, ["SFTP-009", "SFTP-013"]),
  match("sftp-connector", /promote\(/, ["SFTP-008", "SFTP-013"]),
  match("sftp-connector", /runReconciliationCheck|quarantineFromDryRun/, ["SFTP-010"]),
  match("sftp-connector", /downloadArchive|downloadFile|downloadArchiveMember|downloadArchiveMemberPath/, ["SFTP-011"]),
  match("sftp-connector", /previewFile|previewArchiveMember|archivePreview|openZipArchive|openArchiveFolder/, ["SFTP-006"]),
  match("sftp-connector", /setStatusFilter|goToFolder|clearQueueSearch|goToParentFolder|previousQueuePage|nextQueuePage|openFolder/, ["SFTP-005"]),

  match("deposit-portal", /unlock|loadFiles/, ["SFTP-002"]),
  match("deposit-portal", /onFileInput|fileInput|uploadSelected|onDragOver|onDragLeave|onDrop/, ["SFTP-003"]),

  match("connectors-page", /openSetup|saveSetup|onFieldInput|testSetup|clearSetup/, ["SFTP-018"]),

  match("chat-knowledge-settings", /load\(|saveAll|addScope|setDefaultScope|removeScope|copyEffectiveChatToWorkspace|copyWorkspaceChatToProfile|addCollectionToDefaultScope|copyCollection/, ["CHT-015", "COL-021"]),
  match("chat-knowledge-settings", /Guide|guide|saveGuide|publishGuide|archiveGuide|openGuideEditor|closeGuideEditor|toggleGuideHistory/i, ["COL-011"]),
  match("chat-knowledge-settings", /TableProfile|tableProfile|DocumentProfile|documentProfile/i, ["COL-009", "COL-010", "COL-013"]),
  match("chat-knowledge-settings", /Prompt|prompt|AssistantProfile|assistantProfile/i, ["CHT-015", "COL-021"]),
  match("chat-knowledge-settings", /voiceLoop|default_mode|capture|dictation/i, ["CHT-011", "CHT-012", "CHT-018", "KCAP-010", "KCAP-037"]),
];

const fileDefaults = [
  fileDefault("chat-panel", ["CHT-001", "CHT-007"]),
  fileDefault("chat-workspace", ["CHT-001", "CHT-021"]),
  fileDefault("chat-overlay", ["CHT-021"]),
  fileDefault("assistant-draft-drawer", ["CHT-017"]),
  fileDefault("knowledge-capture", ["KCAP-001", "KCAP-007"]),
  fileDefault("knowledge-view", ["COL-005", "COL-023"]),
  fileDefault("knowledge-base", ["COL-001", "COL-023"]),
  fileDefault("embedding-map", ["COL-014"]),
  fileDefault("sftp-connector", ["SFTP-018", "SFTP-005"]),
  fileDefault("deposit-portal", ["SFTP-002", "SFTP-003"]),
  fileDefault("connectors-page", ["SFTP-018"]),
  fileDefault("chat-knowledge-settings", ["CHT-015", "COL-021"]),
];

const bindings = scopedFiles.flatMap(extractBindings);
const classifiedBindings = bindings.map((binding) => classifyBinding(binding));
const uncovered = classifiedBindings.filter((binding) => binding.feature_ids.length === 0);
const defaultMapped = classifiedBindings.filter((binding) => binding.coverage_rule.startsWith("file-default:"));
const missingFeatureRefs = classifiedBindings
  .flatMap((binding) => binding.feature_ids.map((featureId) => ({ featureId, binding })))
  .filter((entry) => !featureIds.has(entry.featureId));

const audit = {
  generated_at: new Date().toISOString(),
  scope: {
    workspace: "andritz",
    systems: ["Chat Recherche", "Knowledge Capture", "Collections", "SFTP Andritz"],
    safety: "static frontend template and matrix audit only; no browser, backend, VM, SFTP, collection, vector or object-store mutation",
  },
  matrix: {
    feature_count: featureIds.size,
  },
  frontend_actions: {
    scoped_file_count: scopedFiles.length,
    binding_count: classifiedBindings.length,
    uncovered_count: uncovered.length,
    default_mapped_count: defaultMapped.length,
    missing_feature_ref_count: missingFeatureRefs.length,
    bindings: classifiedBindings,
    uncovered,
    missing_feature_refs: missingFeatureRefs.map((entry) => ({
      feature_id: entry.featureId,
      file: entry.binding.file,
      line: entry.binding.line,
      event: entry.binding.event,
      expression: entry.binding.expression,
    })),
  },
  status: uncovered.length === 0 && missingFeatureRefs.length === 0 ? "pass" : "fail",
};

fs.writeFileSync(outputPath, `${JSON.stringify(audit, null, 2)}\n`);
console.log(JSON.stringify({
  status: audit.status,
  scoped_file_count: audit.frontend_actions.scoped_file_count,
  binding_count: audit.frontend_actions.binding_count,
  uncovered_count: audit.frontend_actions.uncovered_count,
  default_mapped_count: audit.frontend_actions.default_mapped_count,
  missing_feature_ref_count: audit.frontend_actions.missing_feature_ref_count,
  output: outputPath,
}, null, 2));

if (audit.status !== "pass") {
  process.exitCode = 1;
}

function extractBindings(rel) {
  const abs = path.join(repoRoot, rel);
  const source = fs.readFileSync(abs, "utf8");
  const bindingRe = /\((click|ngSubmit|submit|change|input|keyup\.enter|keydown\.enter|drop|dragover|dragleave)\)\s*=\s*"([^"]+)"/gms;
  return [...source.matchAll(bindingRe)].map((match) => ({
    file: rel,
    line: lineNumber(source, match.index || 0),
    event: match[1],
    expression: normalizeExpression(match[2]),
  }));
}

function classifyBinding(binding) {
  const matchedRule = actionRules.find((entry) => {
    return binding.file.includes(entry.fileToken) && entry.pattern.test(binding.expression);
  });
  if (matchedRule) {
    return {
      ...binding,
      feature_ids: matchedRule.featureIds,
      coverage_rule: `${matchedRule.fileToken}:${matchedRule.pattern.source}`,
    };
  }
  const fallback = fileDefaults.find((entry) => binding.file.includes(entry.fileToken));
  return {
    ...binding,
    feature_ids: fallback?.featureIds || [],
    coverage_rule: fallback ? `file-default:${fallback.fileToken}` : "uncovered",
  };
}

function lineNumber(source, index) {
  return source.slice(0, index).split("\n").length;
}

function normalizeExpression(value) {
  return value.replace(/\s+/g, " ").trim();
}

function match(fileToken, pattern, featureIds) {
  return { fileToken, pattern, featureIds };
}

function fileDefault(fileToken, featureIds) {
  return { fileToken, featureIds };
}
