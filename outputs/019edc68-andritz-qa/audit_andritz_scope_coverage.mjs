import fs from "node:fs";
import path from "node:path";

const repoRoot = path.resolve(import.meta.dirname, "../..");
const outputDir = import.meta.dirname;
const matrixSourcePath = path.join(outputDir, "build_andritz_qa_matrix.mjs");
const outputPath = path.join(outputDir, "andritz_scope_coverage_audit.json");

const matrixSource = fs.readFileSync(matrixSourcePath, "utf8");
const featureIds = new Set(
  [...matrixSource.matchAll(/id: "((?:CHT|KCAP|COL|SFTP)-\d+)"/g)].map((match) => match[1]),
);

const backendFiles = [
  {
    rel: "backend/app/api/v1/endpoints/chat.py",
    prefixes: { router: "/chat" },
  },
  {
    rel: "backend/app/api/v1/endpoints/sessions.py",
    prefixes: { router: "/sessions" },
  },
  {
    rel: "backend/app/api/v1/endpoints/contexts.py",
    prefixes: { router: "/contexts" },
  },
  {
    rel: "backend/app/api/v1/endpoints/livekit.py",
    prefixes: { router: "/livekit" },
  },
  {
    rel: "backend/app/api/v1/endpoints/voice.py",
    prefixes: { router: "/voice" },
  },
  {
    rel: "backend/app/api/v1/endpoints/knowledge_capture.py",
    prefixes: { router: "/knowledge-capture" },
  },
  {
    rel: "backend/app/api/v1/endpoints/documents.py",
    prefixes: { router: "/documents" },
  },
  {
    rel: "backend/app/api/v1/endpoints/secure_deposit.py",
    prefixes: { internal_router: "/sftp", public_router: "/deposit-links" },
  },
  {
    rel: "backend/app/api/v1/endpoints/workspace_jobs.py",
    prefixes: { router: "/workspace-jobs" },
  },
];

const backendCoverageRules = [
  rule(/^POST \/chat\/stream$/, ["CHT-007"]),
  rule(/^POST \/chat\/completion$/, ["CHT-016"]),
  rule(/^POST \/chat\/deep-retrieval-jobs$/, ["CHT-009"]),
  rule(/^POST \/chat\/retrieval-plan-preview$/, ["CHT-010"]),
  rule(/^.* \/sessions(?:\/\{session_id\}(?:\/messages)?)?$/, ["CHT-014"]),
  rule(/^.* \/contexts(?:\/\{ctx_id\}(?:\/persist)?)?$/, ["CHT-004", "CHT-005", "CHT-006"]),
  rule(/^.* \/livekit(?:\/.*)?$/, ["CHT-019", "KCAP-009"]),
  rule(/^.* \/voice\/sessions\/\{session_id\}$/, ["KCAP-009", "CHT-011", "CHT-012"]),
  rule(/^GET \/voice\/runtimes$/, ["KCAP-009"]),
  rule(/^POST \/voice\/transcribe$/, ["CHT-011", "KCAP-012"]),
  rule(/^POST \/voice\/synthesize$/, ["CHT-012"]),
  rule(/^POST \/voice\/realtime\/.*$/, ["CHT-019", "KCAP-009"]),
  rule(/^POST \/voice\/sessions\/\{session_id\}\/events$/, ["KCAP-037"]),

  rule(/^GET \/knowledge-capture\/voice-runtimes$/, ["KCAP-009"]),
  rule(/^POST \/knowledge-capture\/plan-source\/extract$/, ["KCAP-003"]),
  rule(/^POST \/knowledge-capture\/plans$/, ["KCAP-002", "KCAP-004"]),
  rule(/^GET \/knowledge-capture\/sessions$/, ["KCAP-001"]),
  rule(/^GET \/knowledge-capture\/sessions\/\{session_id\}$/, ["KCAP-035"]),
  rule(/^DELETE \/knowledge-capture\/sessions\/\{session_id\}$/, ["KCAP-027"]),
  rule(/^POST \/knowledge-capture\/sessions\/\{session_id\}\/(?:archive|unarchive)$/, ["KCAP-027"]),
  rule(/^PATCH \/knowledge-capture\/sessions\/\{session_id\}\/plan$/, ["KCAP-006"]),
  rule(/^POST \/knowledge-capture\/sessions\/\{session_id\}\/plan\/approve$/, ["KCAP-006"]),
  rule(/^POST \/knowledge-capture\/sessions\/\{session_id\}\/start$/, ["KCAP-007"]),
  rule(/^POST \/knowledge-capture\/sessions\/\{session_id\}\/turns$/, ["KCAP-008"]),
  rule(/^.* \/knowledge-capture\/sessions\/\{session_id\}\/documents(?:\/view)?$/, ["KCAP-015", "KCAP-016", "KCAP-017"]),
  rule(/^POST \/knowledge-capture\/sessions\/\{session_id\}\/retrieval-prefetch$/, ["KCAP-013"]),
  rule(/^POST \/knowledge-capture\/sessions\/\{session_id\}\/conversation-step$/, ["KCAP-039"]),
  rule(/^GET \/knowledge-capture\/sessions\/\{session_id\}\/events$/, ["KCAP-030"]),
  rule(/^PATCH \/knowledge-capture\/sessions\/\{session_id\}\/events\/\{event_id\}\/amend$/, ["KCAP-030"]),
  rule(/^PATCH \/knowledge-capture\/sessions\/\{session_id\}\/oracle-questions$/, ["KCAP-014"]),
  rule(/^PATCH \/knowledge-capture\/sessions\/\{session_id\}\/flags$/, ["KCAP-031"]),
  rule(/^POST \/knowledge-capture\/sessions\/\{session_id\}\/plan\/dialogue-turn$/, ["KCAP-005"]),
  rule(/^POST \/knowledge-capture\/sessions\/\{session_id\}\/plan\/finalize$/, ["KCAP-005"]),
  rule(/^.* \/knowledge-capture\/sessions\/\{session_id\}\/plan\/topics$/, ["KCAP-006"]),
  rule(/^POST \/knowledge-capture\/sessions\/\{session_id\}\/plan\/validate-topics$/, ["KCAP-006"]),
  rule(/^GET \/knowledge-capture\/sessions\/\{session_id\}\/hint-queue$/, ["KCAP-032"]),
  rule(/^POST \/knowledge-capture\/sessions\/\{session_id\}\/(?:pause|resume)$/, ["KCAP-007"]),
  rule(/^POST \/knowledge-capture\/sessions\/\{session_id\}\/proposal\/export$/, ["KCAP-033"]),
  rule(/^POST \/knowledge-capture\/sessions\/\{session_id\}\/proposal$/, ["KCAP-020", "KCAP-026"]),
  rule(/^GET \/knowledge-capture\/sessions\/\{session_id\}\/closure-sheet$/, ["KCAP-019"]),
  rule(/^POST \/knowledge-capture\/sessions\/\{session_id\}\/(?:closure|extend)$/, ["KCAP-019"]),
  rule(/^GET \/knowledge-capture\/sessions\/\{session_id\}\/quality-backlog$/, ["KCAP-029"]),
  rule(/^POST \/knowledge-capture\/sessions\/\{session_id\}\/quality\/defer$/, ["KCAP-029"]),
  rule(/^GET \/knowledge-capture\/fiches$/, ["KCAP-028"]),
  rule(/^GET \/knowledge-capture\/proposals$/, ["KCAP-038"]),
  rule(/^PATCH \/knowledge-capture\/proposals\/\{proposal_id\}\/review$/, ["KCAP-024"]),
  rule(/^PATCH \/knowledge-capture\/proposals\/\{proposal_id\}\/content$/, ["KCAP-034"]),
  rule(/^PATCH \/knowledge-capture\/proposals\/\{proposal_id\}\/open-questions$/, ["KCAP-023"]),
  rule(/^POST \/knowledge-capture\/proposals\/\{proposal_id\}\/open-questions\/\{question_id\}\/answer$/, ["KCAP-023"]),
  rule(/^POST \/knowledge-capture\/proposals\/\{proposal_id\}\/instruction$/, ["KCAP-022"]),
  rule(/^POST \/knowledge-capture\/proposals\/\{proposal_id\}\/publish$/, ["KCAP-025"]),
  rule(/^POST \/knowledge-capture\/chat-correction$/, ["CHT-013"]),

  rule(/^GET \/documents\/collections$/, ["COL-001"]),
  rule(/^POST \/documents\/collections$/, ["COL-002"]),
  rule(/^GET \/documents\/collections\/\{collection_id\}$/, ["COL-005"]),
  rule(/^PATCH \/documents\/collections\/\{collection_id\}$/, ["COL-016"]),
  rule(/^DELETE \/documents\/collections\/\{collection_name\}$/, ["COL-004"]),
  rule(/^GET \/documents\/collections\/\{collection_id\}\/inventory$/, ["COL-005"]),
  rule(/^GET \/documents\/collections\/\{collection_id\}\/diagnostics$/, ["COL-006"]),
  rule(/^POST \/documents\/collections\/\{collection_id\}\/documents$/, ["COL-020"]),
  rule(/^POST \/documents\/collections\/\{collection_id\}\/retrieval-artifact-jobs$/, ["COL-012"]),
  rule(/^POST \/documents\/upload$/, ["COL-003"]),
  rule(/^POST \/documents\/upload-batch$/, ["CHT-004", "COL-019"]),
  rule(/^GET \/documents\/list$/, ["COL-017", "COL-023"]),
  rule(/^DELETE \/documents\/clear$/, ["COL-018"]),
  rule(/^GET \/documents\/(?:\{document_id\}\/(?:metadata|raw|rich-preview|converted-preview)|preview\/\{document_id\}|file\/\{document_id\})$/, ["COL-007", "CHT-008", "KCAP-016"]),
  rule(/^DELETE \/documents\/\{document_id\}$/, ["COL-004"]),
  rule(/^GET \/documents\/chunks$/, ["COL-014"]),
  rule(/^GET \/documents\/stats$/, ["COL-014"]),
  rule(/^GET \/documents\/graph$/, ["COL-014"]),
  rule(/^POST \/documents\/search$/, ["COL-008", "CHT-002"]),
  rule(/^GET \/documents\/table-facts$/, ["COL-009", "COL-013"]),
  rule(/^GET \/documents\/document-facts$/, ["COL-010", "CHT-020"]),
  rule(/^GET \/documents\/jobs(?:\/\{job_id\})?$/, ["COL-015", "SFTP-016", "CHT-009"]),

  rule(/^.* \/deposit-links\/\{access_id\}\/session$/, ["SFTP-002"]),
  rule(/^.* \/deposit-links\/\{access_id\}\/files$/, ["SFTP-002", "SFTP-003"]),
  rule(/^GET \/sftp\/health$/, ["SFTP-014", "SFTP-015"]),
  rule(/^.* \/sftp\/links(?:\/\{link_id\})?(?:\/(?:rotate|revoke))?$/, ["SFTP-001", "SFTP-017"]),
  rule(/^GET \/sftp\/deposits$/, ["SFTP-005"]),
  rule(/^GET \/sftp\/deposits\/\{file_id\}\/(?:preview|archive|archive\/member\/preview)$/, ["SFTP-006"]),
  rule(/^GET \/sftp\/deposits\/\{file_id\}\/(?:download|archive\/member\/download)$/, ["SFTP-011"]),
  rule(/^GET \/sftp\/deposits\/archive$/, ["SFTP-011"]),
  rule(/^POST \/sftp\/deposits\/\{file_id\}\/promote$/, ["SFTP-008", "SFTP-013"]),
  rule(/^POST \/sftp\/deposits\/promote-bulk$/, ["SFTP-009", "SFTP-013"]),
  rule(/^POST \/sftp\/deposits\/indexing-assist$/, ["SFTP-007", "SFTP-016"]),
  rule(/^GET \/sftp\/operations$/, ["SFTP-010"]),
  rule(/^POST \/sftp\/operations\/reconcile$/, ["SFTP-010"]),

  rule(/^.* \/workspace-jobs\/?(?:\{job_id\}(?:\/(?:events|transition))?)?$/, ["COL-015", "CHT-009"]),
];

const frontendSurfaceCoverage = [
  route("/chat", ["CHT-001", "CHT-021"]),
  route("/workspace/:slug/chat", ["CHT-001", "CHT-021"]),
  route("/workspace/:slug/chat-knowledge", ["CHT-015"]),
  route("/knowledge", ["COL-001", "COL-023"]),
  route("/knowledge/:kbId", ["COL-005", "COL-023"]),
  route("/knowledge/capture", ["KCAP-001"]),
  route("/connectors", ["SFTP-018"]),
  route("/connectors/sftp", ["SFTP-018", "SFTP-005"]),
  route("/deposit/:accessId", ["SFTP-002", "SFTP-003"]),
];

const backendEndpoints = extractBackendEndpoints();
const classifiedBackend = backendEndpoints.map((endpoint) => {
  const key = `${endpoint.method} ${endpoint.path}`;
  const matched = backendCoverageRules.find((entry) => entry.pattern.test(key));
  return {
    ...endpoint,
    feature_ids: matched?.featureIds || [],
    coverage_rule: matched?.pattern.source || null,
  };
});

const unknownBackend = classifiedBackend.filter((endpoint) => endpoint.feature_ids.length === 0);
const missingFeatureRefs = classifiedBackend
  .flatMap((endpoint) => endpoint.feature_ids.map((featureId) => ({ featureId, endpoint })))
  .filter((entry) => !featureIds.has(entry.featureId));
const missingFrontendFeatureRefs = frontendSurfaceCoverage
  .flatMap((entry) => entry.featureIds.map((featureId) => ({ featureId, route: entry.path })))
  .filter((entry) => !featureIds.has(entry.featureId));

const audit = {
  generated_at: new Date().toISOString(),
  scope: {
    workspace: "andritz",
    systems: ["Chat Recherche", "Knowledge Capture", "Collections", "SFTP Andritz"],
    safety: "static code and matrix audit only; no backend, VM, SFTP, collection, vector or object-store mutation",
  },
  matrix: {
    feature_count: featureIds.size,
  },
  backend: {
    endpoint_count: classifiedBackend.length,
    uncovered_count: unknownBackend.length,
    missing_feature_ref_count: missingFeatureRefs.length,
    endpoints: classifiedBackend,
    uncovered: unknownBackend,
    missing_feature_refs: missingFeatureRefs.map((entry) => ({
      feature_id: entry.featureId,
      endpoint: `${entry.endpoint.method} ${entry.endpoint.path}`,
      file: entry.endpoint.file,
    })),
  },
  frontend: {
    route_count: frontendSurfaceCoverage.length,
    missing_feature_ref_count: missingFrontendFeatureRefs.length,
    routes: frontendSurfaceCoverage.map((entry) => ({
      path: entry.path,
      feature_ids: entry.featureIds,
    })),
    missing_feature_refs: missingFrontendFeatureRefs,
  },
  status:
    unknownBackend.length === 0 &&
    missingFeatureRefs.length === 0 &&
    missingFrontendFeatureRefs.length === 0
      ? "pass"
      : "fail",
};

fs.writeFileSync(outputPath, `${JSON.stringify(audit, null, 2)}\n`);
console.log(JSON.stringify({
  status: audit.status,
  backend_endpoint_count: audit.backend.endpoint_count,
  backend_uncovered_count: audit.backend.uncovered_count,
  missing_feature_ref_count:
    audit.backend.missing_feature_ref_count + audit.frontend.missing_feature_ref_count,
  output: outputPath,
}, null, 2));

if (audit.status !== "pass") {
  process.exitCode = 1;
}

function rule(pattern, featureIds) {
  return { pattern, featureIds };
}

function route(path, featureIds) {
  return { path, featureIds };
}

function extractBackendEndpoints() {
  const endpoints = [];
  for (const file of backendFiles) {
    const source = fs.readFileSync(path.join(repoRoot, file.rel), "utf8");
    const decorator = /@(router|internal_router|public_router)\.(get|post|patch|delete|put|websocket)\(\s*["']([^"']*)["']/g;
    for (const match of source.matchAll(decorator)) {
      const routerName = match[1];
      const prefix = file.prefixes[routerName];
      if (!prefix) continue;
      endpoints.push({
        method: match[2].toUpperCase(),
        path: `${prefix}${match[3]}`,
        file: file.rel,
      });
    }
  }
  return endpoints.sort((a, b) => `${a.path} ${a.method}`.localeCompare(`${b.path} ${b.method}`));
}
