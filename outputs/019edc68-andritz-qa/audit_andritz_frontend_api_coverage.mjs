import fs from "node:fs";
import path from "node:path";

const repoRoot = path.resolve(import.meta.dirname, "../..");
const outputDir = import.meta.dirname;
const matrixSourcePath = path.join(outputDir, "build_andritz_qa_matrix.mjs");
const outputPath = path.join(outputDir, "andritz_frontend_api_coverage_audit.json");

const matrixSource = fs.readFileSync(matrixSourcePath, "utf8");
const featureIds = new Set(
  [...matrixSource.matchAll(/id: "((?:CHT|KCAP|COL|SFTP)-\d+)"/g)].map((match) => match[1]),
);

const scopedFiles = [
  "frontend-ng/src/app/core/api.service.ts",
  "frontend-ng/src/app/core/livekit-conversation.service.ts",
  "frontend-ng/src/app/core/sse.service.ts",
  "frontend-ng/src/app/core/voice-session.service.ts",
  "frontend-ng/src/app/features/chat/chat-panel.component.ts",
  "frontend-ng/src/app/features/chat/chat-workspace.component.ts",
  "frontend-ng/src/app/features/connectors/sftp/sftp-connector.component.ts",
  "frontend-ng/src/app/features/deposit/deposit-portal.component.ts",
  "frontend-ng/src/app/features/knowledge/embedding-map.component.ts",
  "frontend-ng/src/app/features/knowledge/knowledge-base.component.ts",
  "frontend-ng/src/app/features/knowledge/knowledge-capture.component.ts",
  "frontend-ng/src/app/features/knowledge/knowledge-view.component.ts",
  "frontend-ng/src/app/features/workspace/chat-knowledge-settings.component.ts",
  "frontend-ng/src/app/shared/document-preview/document-preview.component.ts",
];

const scopedPrefixes = [
  "/actions",
  "/chat",
  "/contexts",
  "/deposit-links",
  "/documents",
  "/evaluation",
  "/knowledge",
  "/knowledge-capture",
  "/livekit",
  "/presets",
  "/reasoning",
  "/sessions",
  "/settings",
  "/sftp",
  "/systems",
  "/voice",
];

const apiRules = [
  rule(/^\/chat\/stream/, ["CHT-007"]),
  rule(/^\/chat\/completion/, ["CHT-016"]),
  rule(/^\/chat\/deep-retrieval-jobs/, ["CHT-009"]),
  rule(/^\/chat\/retrieval-plan-preview/, ["CHT-010"]),
  rule(/^\/sessions(?:\/|\?|$)/, ["CHT-014"]),
  rule(/^\/contexts(?:\/|\?|$)/, ["CHT-004", "CHT-005", "CHT-006"]),
  rule(/^\/livekit(?:\/|$)/, ["CHT-019", "KCAP-009"]),
  rule(/^\/voice\/runtimes/, ["CHT-011", "KCAP-009"]),
  rule(/^\/voice\/transcribe/, ["CHT-011", "KCAP-012"]),
  rule(/^\/voice\/synthesize/, ["CHT-012"]),
  rule(/^\/voice\/sessions/, ["CHT-011", "CHT-012", "KCAP-009", "KCAP-037"]),

  rule(/^\/knowledge-capture\/voice-runtimes/, ["KCAP-009"]),
  rule(/^\/knowledge-capture\/plan-source\/extract/, ["KCAP-003"]),
  rule(/^\/knowledge-capture\/plans/, ["KCAP-002", "KCAP-004"]),
  rule(/^\/knowledge-capture\/sessions(?:\/|\?|$)/, ["KCAP-001", "KCAP-035"]),
  rule(/^\/knowledge-capture\/sessions\/[^/]+\/plan\/dialogue-turn/, ["KCAP-005"]),
  rule(/^\/knowledge-capture\/sessions\/[^/]+\/plan\/finalize/, ["KCAP-005"]),
  rule(/^\/knowledge-capture\/sessions\/[^/]+\/plan\/approve/, ["KCAP-006"]),
  rule(/^\/knowledge-capture\/sessions\/[^/]+\/plan\/validate-topics/, ["KCAP-006"]),
  rule(/^\/knowledge-capture\/sessions\/[^/]+\/plan\/topics/, ["KCAP-006"]),
  rule(/^\/knowledge-capture\/sessions\/[^/]+\/plan/, ["KCAP-005", "KCAP-006"]),
  rule(/^\/knowledge-capture\/sessions\/[^/]+\/start/, ["KCAP-007"]),
  rule(/^\/knowledge-capture\/sessions\/[^/]+\/turns/, ["KCAP-008", "KCAP-012"]),
  rule(/^\/knowledge-capture\/sessions\/[^/]+\/documents/, ["KCAP-015", "KCAP-016", "KCAP-017", "KCAP-021"]),
  rule(/^\/knowledge-capture\/sessions\/[^/]+\/retrieval-prefetch/, ["KCAP-013"]),
  rule(/^\/knowledge-capture\/sessions\/[^/]+\/conversation-step/, ["KCAP-039"]),
  rule(/^\/knowledge-capture\/sessions\/[^/]+\/events/, ["KCAP-030"]),
  rule(/^\/knowledge-capture\/sessions\/[^/]+\/oracle-questions/, ["KCAP-014"]),
  rule(/^\/knowledge-capture\/sessions\/[^/]+\/flags/, ["KCAP-031"]),
  rule(/^\/knowledge-capture\/sessions\/[^/]+\/hint-queue/, ["KCAP-032"]),
  rule(/^\/knowledge-capture\/sessions\/[^/]+\/(?:pause|resume)/, ["KCAP-007"]),
  rule(/^\/knowledge-capture\/sessions\/[^/]+\/proposal\/export/, ["KCAP-033"]),
  rule(/^\/knowledge-capture\/sessions\/[^/]+\/proposal/, ["KCAP-020", "KCAP-026"]),
  rule(/^\/knowledge-capture\/sessions\/[^/]+\/closure-sheet/, ["KCAP-019"]),
  rule(/^\/knowledge-capture\/sessions\/[^/]+\/(?:closure|extend)/, ["KCAP-019"]),
  rule(/^\/knowledge-capture\/sessions\/[^/]+\/quality/, ["KCAP-029"]),
  rule(/^\/knowledge-capture\/fiches/, ["KCAP-028"]),
  rule(/^\/knowledge-capture\/proposals(?:\/|\?|$)/, ["KCAP-038"]),
  rule(/^\/knowledge-capture\/proposals\/[^/]+\/review/, ["KCAP-024"]),
  rule(/^\/knowledge-capture\/proposals\/[^/]+\/content/, ["KCAP-034"]),
  rule(/^\/knowledge-capture\/proposals\/[^/]+\/open-questions/, ["KCAP-023"]),
  rule(/^\/knowledge-capture\/proposals\/[^/]+\/instruction/, ["KCAP-022"]),
  rule(/^\/knowledge-capture\/proposals\/[^/]+\/publish/, ["KCAP-025"]),
  rule(/^\/knowledge-capture\/chat-correction/, ["CHT-013"]),

  rule(/^\/documents$/, ["COL-001", "COL-005"]),
  rule(/^\/documents\/collections$/, ["COL-001"]),
  rule(/^\/documents\/collections\/[^/]+\/diagnostics/, ["COL-006"]),
  rule(/^\/documents\/collections\/[^/]+\/retrieval-artifact-jobs/, ["COL-012"]),
  rule(/^\/documents\/collections\/[^/]+\/documents/, ["COL-020"]),
  rule(/^\/documents\/collections(?:\/|\?|$)/, ["COL-005"]),
  rule(/^\/documents\/upload-batch/, ["CHT-004", "COL-019"]),
  rule(/^\/documents\/upload/, ["COL-003"]),
  rule(/^\/documents\/list/, ["COL-017", "COL-023"]),
  rule(/^\/documents\/clear/, ["COL-018"]),
  rule(/^\/documents\/search/, ["COL-008", "CHT-002"]),
  rule(/^\/documents\/(?:graph|chunks|stats)/, ["COL-014"]),
  rule(/^\/documents\/table-facts/, ["COL-009", "COL-013"]),
  rule(/^\/documents\/document-facts/, ["COL-010", "CHT-020"]),
  rule(/^\/documents\/jobs/, ["COL-015", "SFTP-016", "CHT-009"]),
  rule(/^\/documents\/[^/]+\/metadata/, ["COL-007", "CHT-008"]),
  rule(/^\/documents\/(?:preview|file|raw|rich-preview|converted-preview)/, ["COL-007", "CHT-008", "KCAP-016"]),
  rule(/^\/documents\/[^/]+/, ["COL-007", "COL-004"]),

  rule(/^\/knowledge\/scopes/, ["CHT-015", "COL-021"]),
  rule(/^\/knowledge\/guides/, ["COL-011"]),
  rule(/^\/knowledge\/table-query/, ["COL-009", "COL-013"]),
  rule(/^\/knowledge\/document-query/, ["COL-010", "CHT-020"]),

  rule(/^\/sftp\/health/, ["SFTP-015"]),
  rule(/^\/sftp\/links(?:\/|$)/, ["SFTP-001", "SFTP-017"]),
  rule(/^\/sftp\/deposits\/indexing-assist/, ["SFTP-007", "SFTP-016"]),
  rule(/^\/sftp\/deposits\/promote-bulk/, ["SFTP-009", "SFTP-013"]),
  rule(/^\/sftp\/deposits\/[^/]+\/promote/, ["SFTP-008", "SFTP-013"]),
  rule(/^\/sftp\/deposits\/[^/]+\/archive\/member\/preview/, ["SFTP-006"]),
  rule(/^\/sftp\/deposits\/[^/]+\/archive\/member\/download/, ["SFTP-011"]),
  rule(/^\/sftp\/deposits\/[^/]+\/archive/, ["SFTP-006", "SFTP-011"]),
  rule(/^\/sftp\/deposits\/[^/]+\/preview/, ["SFTP-006"]),
  rule(/^\/sftp\/deposits\/[^/]+\/download/, ["SFTP-011"]),
  rule(/^\/sftp\/deposits(?:\/|\?|$)/, ["SFTP-005"]),
  rule(/^\/sftp\/operations\/reconcile/, ["SFTP-010"]),
  rule(/^\/sftp\/operations/, ["SFTP-010", "SFTP-016"]),
  rule(/^\/deposit-links\/[^/]+\/session/, ["SFTP-002"]),
  rule(/^\/deposit-links\/[^/]+\/files/, ["SFTP-002", "SFTP-003"]),

  rule(/^\/actions\/effective/, ["CHT-003", "CHT-021"]),
  rule(/^\/reasoning\/templates/, ["CHT-003", "CHT-021"]),
  rule(/^\/evaluation\/score/, ["CHT-017"]),
  rule(/^\/evaluation\/review-queue/, ["CHT-017"]),
  rule(/^\/presets/, ["CHT-015", "COL-021"]),
  rule(/^\/settings/, ["CHT-015"]),
  rule(/^\/systems(?:\/|\?|$)/, ["KCAP-002", "KCAP-004"]),
];

const references = scopedFiles.flatMap(extractApiReferences);
const classifiedReferences = dedupeReferences(references).map((reference) => classifyReference(reference));
const uncovered = classifiedReferences.filter((reference) => reference.feature_ids.length === 0);
const missingFeatureRefs = classifiedReferences
  .flatMap((reference) => reference.feature_ids.map((featureId) => ({ featureId, reference })))
  .filter((entry) => !featureIds.has(entry.featureId));

const audit = {
  generated_at: new Date().toISOString(),
  scope: {
    workspace: "andritz",
    systems: ["Chat Recherche", "Knowledge Capture", "Collections", "SFTP Andritz"],
    safety: "static frontend API-reference and matrix audit only; no browser, backend, VM, SFTP, collection, vector or object-store mutation",
  },
  matrix: {
    feature_count: featureIds.size,
  },
  frontend_api: {
    scoped_file_count: scopedFiles.length,
    reference_count: classifiedReferences.length,
    uncovered_count: uncovered.length,
    missing_feature_ref_count: missingFeatureRefs.length,
    references: classifiedReferences,
    uncovered,
    missing_feature_refs: missingFeatureRefs.map((entry) => ({
      feature_id: entry.featureId,
      file: entry.reference.file,
      line: entry.reference.line,
      method: entry.reference.method,
      path: entry.reference.path,
      raw: entry.reference.raw,
    })),
  },
  status: uncovered.length === 0 && missingFeatureRefs.length === 0 ? "pass" : "fail",
};

fs.writeFileSync(outputPath, `${JSON.stringify(audit, null, 2)}\n`);
console.log(JSON.stringify({
  status: audit.status,
  scoped_file_count: audit.frontend_api.scoped_file_count,
  reference_count: audit.frontend_api.reference_count,
  uncovered_count: audit.frontend_api.uncovered_count,
  missing_feature_ref_count: audit.frontend_api.missing_feature_ref_count,
  output: outputPath,
}, null, 2));

if (audit.status !== "pass") {
  process.exitCode = 1;
}

function extractApiReferences(rel) {
  const abs = path.join(repoRoot, rel);
  const source = stripComments(fs.readFileSync(abs, "utf8"));
  const references = [];
  const literalRe = /(?<quote>['"`])(?<value>(?:\\.|(?!\k<quote>)[\s\S])*?)\k<quote>/g;
  for (const match of source.matchAll(literalRe)) {
    const value = unescapeLite(match.groups.value);
    const normalized = normalizeApiPath(value, rel);
    if (!normalized || !isScopedApiPath(normalized)) continue;
    references.push({
      file: rel,
      line: lineNumber(source, match.index || 0),
      method: inferMethod(source, match.index || 0),
      path: normalized,
      raw: value.replace(/\s+/g, " ").trim(),
    });
  }
  return references;
}

function normalizeApiPath(value, file) {
  let candidate = value.trim();
  if (!candidate.includes("/") || candidate.includes(" ")) return null;
  candidate = candidate.replace(/\$\{this\.base\}/g, baseForFile(file));
  candidate = candidate.replace(/\$\{this\.accessId\(\)\}/g, "{access_id}");
  candidate = candidate.replace(/\$\{encodeURIComponent\([^}]+\)\}/g, "{id}");
  candidate = candidate.replace(/\$\{[^}]+\}/g, "{id}");
  candidate = candidate.replace(/^https?:\/\/[^/]+/, "");
  candidate = candidate.replace(/^\/api\/v1/, "");
  if (candidate.includes("?")) {
    candidate = `${candidate.split("?")[0]}?`;
  }
  return candidate || "/";
}

function baseForFile(file) {
  if (file.includes("knowledge-base") || file.includes("knowledge-view")) return "/api/v1/documents";
  return "";
}

function isScopedApiPath(value) {
  if (!value.startsWith("/")) return false;
  return scopedPrefixes.some((prefix) => value === prefix || value.startsWith(`${prefix}/`) || value.startsWith(`${prefix}?`));
}

function classifyReference(reference) {
  const matched = apiRules.find((entry) => entry.pattern.test(reference.path));
  return {
    ...reference,
    feature_ids: matched?.featureIds || [],
    coverage_rule: matched?.pattern.source || null,
  };
}

function dedupeReferences(references) {
  const seen = new Set();
  const unique = [];
  for (const reference of references) {
    const key = `${reference.file}:${reference.line}:${reference.method}:${reference.path}:${reference.raw}`;
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(reference);
  }
  return unique;
}

function inferMethod(source, index) {
  const context = source.slice(Math.max(0, index - 160), index + 40);
  const method = context.match(/\.(get|post|patch|delete|blob|stream)\s*(?:<|\()/)?.[1];
  if (method) return method.toUpperCase();
  if (/fetch\s*\($/.test(context)) return "FETCH";
  if (/new URL\s*\($/.test(context)) return "WS";
  return "REFERENCE";
}

function stripComments(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/.*$/gm, "$1");
}

function unescapeLite(value) {
  return value.replace(/\\`/g, "`").replace(/\\'/g, "'").replace(/\\"/g, '"');
}

function lineNumber(source, index) {
  return source.slice(0, index).split("\n").length;
}

function rule(pattern, featureIds) {
  return { pattern, featureIds };
}
