import fs from "node:fs";
import path from "node:path";

const repoRoot = path.resolve(import.meta.dirname, "../..");
const outputDir = import.meta.dirname;
const matrixSourcePath = path.join(outputDir, "build_andritz_qa_matrix.mjs");
const outputPath = path.join(outputDir, "andritz_permission_coverage_audit.json");

const matrixSource = fs.readFileSync(matrixSourcePath, "utf8");
const featureIds = new Set(
  [...matrixSource.matchAll(/id: "((?:CHT|KCAP|COL|SFTP)-\d+)"/g)].map((match) => match[1]),
);

const manifestPath = "backend/app/services/iam/manifest.py";
const enginePath = "backend/app/services/iam/engine.py";
const iamEndpointPath = "backend/app/api/v1/endpoints/iam.py";
const permissionsServicePath = "frontend-ng/src/app/core/permissions.service.ts";
const frontendGateFiles = [
  "frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts",
  "frontend-ng/src/app/features/chat/chat-panel.component.ts",
];

const capabilitySections = [
  section("expert_knowledge_capture", "CAPTURE_MANIFEST", "SECURE_DEPOSIT_MANIFEST"),
  section("secure_deposit", "SECURE_DEPOSIT_MANIFEST", "VOICE2VOICE_MANIFEST"),
  section("voice2voice_interaction", "VOICE2VOICE_MANIFEST", "AGENTIUM_ACTIONS_MANIFEST"),
  section("agentium_actions", "AGENTIUM_ACTIONS_MANIFEST", "TRANSLATION_SUITE_MANIFEST"),
];

const permissionRules = [
  mapRule("expert_knowledge_capture", "voice_runtime", "read", ["KCAP-009", "CHT-011"]),
  mapRule("expert_knowledge_capture", "capture_session", "create", ["KCAP-001", "KCAP-002", "KCAP-004"]),
  mapRule("expert_knowledge_capture", "capture_session", "read", ["KCAP-001", "KCAP-035"]),
  mapRule("expert_knowledge_capture", "capture_session", "update", ["KCAP-006", "KCAP-027", "KCAP-031"]),
  mapRule("expert_knowledge_capture", "capture_session", "execute", ["KCAP-007", "KCAP-008", "KCAP-010", "KCAP-011", "KCAP-012", "KCAP-019"]),
  mapRule("expert_knowledge_capture", "knowledge_proposal", "read", ["KCAP-020", "KCAP-024", "KCAP-038"]),
  mapRule("expert_knowledge_capture", "knowledge_proposal", "submit_review", ["KCAP-020", "KCAP-024"]),
  mapRule("expert_knowledge_capture", "knowledge_proposal", "review_decide", ["KCAP-024"]),
  mapRule("expert_knowledge_capture", "knowledge_proposal", "chat_correct", ["CHT-013"]),
  mapRule("expert_knowledge_capture", "knowledge_proposal", "trigger_ingestion", ["KCAP-025"]),
  mapRule("expert_knowledge_capture", "workspace", "manage_members", ["KCAP-001"]),
  mapRule("expert_knowledge_capture", "policy", "manage_policies", ["KCAP-001"]),
  mapRule("expert_knowledge_capture", "audit_log", "read", ["KCAP-030"]),

  mapRule("secure_deposit", "deposit_link", "create", ["SFTP-001", "SFTP-002"]),
  mapRule("secure_deposit", "deposit_link", "read", ["SFTP-001", "SFTP-005"]),
  mapRule("secure_deposit", "deposit_link", "read_all", ["SFTP-001", "SFTP-005"]),
  mapRule("secure_deposit", "deposit_link", "update", ["SFTP-001", "SFTP-017"]),
  mapRule("secure_deposit", "deposit_link", "revoke", ["SFTP-001", "SFTP-017"]),
  mapRule("secure_deposit", "deposit_file", "read", ["SFTP-005", "SFTP-006", "SFTP-011"]),
  mapRule("secure_deposit", "deposit_file", "read_all", ["SFTP-005", "SFTP-006", "SFTP-010", "SFTP-016"]),
  mapRule("secure_deposit", "deposit_file", "promote", ["SFTP-008", "SFTP-009", "SFTP-013"]),
  mapRule("secure_deposit", "deposit_file", "download_archive", ["SFTP-011"]),
  mapRule("secure_deposit", "deposit_file", "operate", ["SFTP-010", "SFTP-016"]),
  mapRule("secure_deposit", "deposit_config", "manage", ["SFTP-015", "SFTP-017"]),

  mapRule("voice2voice_interaction", "voice_runtime", "read", ["CHT-011", "CHT-012", "KCAP-009"]),

  mapRule("agentium_actions", "action", "read", ["CHT-003", "CHT-021"]),
  mapRule("agentium_actions", "action", "resolve", ["CHT-003", "CHT-021"]),
  mapRule("agentium_actions", "action", "execute", ["CHT-003", "CHT-021", "SFTP-008"]),
  mapRule("agentium_actions", "action", "manage", ["CHT-003", "CHT-021"]),
];

const manifestPermissions = capabilitySections.flatMap(extractManifestPermissions);
const classifiedManifest = manifestPermissions.map((permission) => classifyPermission(permission));
const uncoveredManifest = classifiedManifest.filter((permission) => permission.feature_ids.length === 0);
const frontendGates = frontendGateFiles.flatMap(extractFrontendGates).map((gate) => ({
  ...gate,
  feature_ids: featureIdsForPermission("expert_knowledge_capture", gate.resource_kind, gate.action),
}));
const uncoveredFrontendGates = frontendGates.filter((gate) => gate.feature_ids.length === 0);
const engineChecks = checkEngineAndFrontendConditionCoverage();
const missingFeatureRefs = [...classifiedManifest, ...frontendGates]
  .flatMap((item) => item.feature_ids.map((featureId) => ({ featureId, item })))
  .filter((entry) => !featureIds.has(entry.featureId));

const audit = {
  generated_at: new Date().toISOString(),
  scope: {
    workspace: "andritz",
    systems: ["Chat Recherche", "Knowledge Capture", "Collections", "SFTP Andritz"],
    safety: "static IAM permission-to-feature audit only; no browser, backend, VM, SFTP, collection, vector or object-store mutation",
  },
  matrix: {
    feature_count: featureIds.size,
  },
  permissions: {
    manifest_permission_count: classifiedManifest.length,
    manifest_uncovered_count: uncoveredManifest.length,
    frontend_gate_count: frontendGates.length,
    frontend_gate_uncovered_count: uncoveredFrontendGates.length,
    missing_feature_ref_count: missingFeatureRefs.length,
    manifest_permissions: classifiedManifest,
    frontend_gates: frontendGates,
    condition_coverage: engineChecks,
    uncovered_manifest_permissions: uncoveredManifest,
    uncovered_frontend_gates: uncoveredFrontendGates,
    missing_feature_refs: missingFeatureRefs.map((entry) => ({
      feature_id: entry.featureId,
      capability: entry.item.capability_id || "frontend_gate",
      resource_kind: entry.item.resource_kind,
      action: entry.item.action,
      file: entry.item.file,
      line: entry.item.line,
    })),
  },
  status:
    uncoveredManifest.length === 0 &&
    uncoveredFrontendGates.length === 0 &&
    missingFeatureRefs.length === 0 &&
    engineChecks.missing_tokens.length === 0
      ? "pass"
      : "fail",
};

fs.writeFileSync(outputPath, `${JSON.stringify(audit, null, 2)}\n`);
console.log(JSON.stringify({
  status: audit.status,
  manifest_permission_count: audit.permissions.manifest_permission_count,
  manifest_uncovered_count: audit.permissions.manifest_uncovered_count,
  frontend_gate_count: audit.permissions.frontend_gate_count,
  frontend_gate_uncovered_count: audit.permissions.frontend_gate_uncovered_count,
  missing_feature_ref_count: audit.permissions.missing_feature_ref_count,
  missing_condition_tokens: engineChecks.missing_tokens.length,
  output: outputPath,
}, null, 2));

if (audit.status !== "pass") {
  process.exitCode = 1;
}

function extractManifestPermissions(sectionDef) {
  const rel = manifestPath;
  const source = fs.readFileSync(path.join(repoRoot, rel), "utf8");
  const start = source.indexOf(`${sectionDef.startToken} =`);
  const end = source.indexOf(`${sectionDef.endToken} =`, start + 1);
  const body = source.slice(start, end);
  const ruleRe = /PermissionRule\(\s*"([^"]+)"\s*,\s*"([^"]+)"/g;
  return [...body.matchAll(ruleRe)].map((match) => ({
    capability_id: sectionDef.capabilityId,
    resource_kind: match[1],
    action: match[2],
    file: rel,
    line: lineNumber(source, start + (match.index || 0)),
  }));
}

function extractFrontendGates(rel) {
  const source = fs.readFileSync(path.join(repoRoot, rel), "utf8");
  const gateRe = /permissions\.can\(\s*'([^']+)'\s*,\s*'([^']+)'/g;
  return [...source.matchAll(gateRe)].map((match) => ({
    resource_kind: match[1],
    action: match[2],
    file: rel,
    line: lineNumber(source, match.index || 0),
  }));
}

function classifyPermission(permission) {
  return {
    ...permission,
    feature_ids: featureIdsForPermission(permission.capability_id, permission.resource_kind, permission.action),
  };
}

function featureIdsForPermission(capabilityId, resourceKind, action) {
  const rule = permissionRules.find(
    (entry) =>
      entry.capabilityId === capabilityId &&
      entry.resourceKind === resourceKind &&
      entry.action === action,
  );
  return rule?.featureIds || [];
}

function checkEngineAndFrontendConditionCoverage() {
  const required = [
    token(enginePath, "owner_match"),
    token(enginePath, "second_eye_ingestion"),
    token(enginePath, "WORKSPACE_PERMISSION_DENIED"),
    token(enginePath, "emit_audit_event"),
    token(iamEndpointPath, "iter_permissions()"),
    token(iamEndpointPath, "CAPTURE_MANIFEST.capability_id"),
    token(permissionsServicePath, "allowed_for_subject"),
    token(permissionsServicePath, "conditionsPass"),
    token(permissionsServicePath, "second_eye_ingestion"),
  ];
  const checked = required.map((item) => {
    const source = fs.readFileSync(path.join(repoRoot, item.file), "utf8");
    const index = source.indexOf(item.token);
    return {
      ...item,
      found: index >= 0,
      line: index >= 0 ? lineNumber(source, index) : null,
    };
  });
  return {
    checked_tokens: checked,
    missing_tokens: checked.filter((item) => !item.found),
    note:
      "Secure Deposit permissions are enforced server-side through the secure_deposit manifest; /iam/matrix currently enumerates the capture manifest used by Knowledge Capture and Chat correction UI gates.",
  };
}

function section(capabilityId, startToken, endToken) {
  return { capabilityId, startToken, endToken };
}

function mapRule(capabilityId, resourceKind, action, featureIds) {
  return { capabilityId, resourceKind, action, featureIds };
}

function token(file, token) {
  return { file, token };
}

function lineNumber(source, index) {
  return source.slice(0, index).split("\n").length;
}
