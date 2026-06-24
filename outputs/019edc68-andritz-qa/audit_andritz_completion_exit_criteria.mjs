import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const outputDir = import.meta.dirname;
const matrixSourcePath = path.join(outputDir, "build_andritz_qa_matrix.mjs");
const outputPath = path.join(outputDir, "andritz_completion_exit_criteria_audit.json");

const matrixSource = fs.readFileSync(matrixSourcePath, "utf8");
const features = loadConstArray(matrixSource, "features", "\n];\n\nconst executionEvidence");
const executionEvidence = loadConstArray(matrixSource, "executionEvidence", "\n];\n\nfunction pass");
const defectRecords = loadConstArray(matrixSource, "defectRecords", "\n];\n\nconst allTests");

const allTests = features.flatMap((feature) =>
  (Array.isArray(feature.tests) ? feature.tests : []).map((test, index) => ({
    test_id: `${feature.id}-T${String(index + 1).padStart(2, "0")}`,
    feature_id: feature.id,
    type: test.type,
    scenario: test.scenario,
  })),
);

const requiredFeatureFields = [
  "id",
  "name",
  "story",
  "expected",
  "edges",
  "validation",
  "dependencies",
  "assumptions",
  "notes",
  "source",
  "scope",
  "tests",
];
const missingFeatureFields = features.flatMap((feature) =>
  requiredFeatureFields
    .filter((field) => {
      const value = feature[field];
      return Array.isArray(value) ? value.length === 0 : value === undefined || value === null || value === "";
    })
    .map((field) => ({ feature_id: feature.id, field })),
);

const audits = {
  scope: readJson("andritz_scope_coverage_audit.json"),
  frontend_actions: readJson("andritz_frontend_action_coverage_audit.json"),
  frontend_api: readJson("andritz_frontend_api_coverage_audit.json"),
  config: readJson("andritz_config_coverage_audit.json"),
  permission: readJson("andritz_permission_coverage_audit.json"),
  events: readJson("andritz_event_coverage_audit.json"),
  taxonomy: readJson("andritz_test_taxonomy_coverage_audit.json"),
  safety: readJson("andritz_test_execution_safety_audit.json"),
  progress: readJson("andritz_execution_progress_audit.json"),
};

const evidenceById = new Map(executionEvidence.map((entry) => [entry.id, entry]));
const requiredRegressionEvidence = [
  "EXEC-2026-06-24-REG-001",
  "EXEC-2026-06-24-REG-002",
  "EXEC-2026-06-24-REG-003",
];
const missingRegressionEvidence = requiredRegressionEvidence.filter((id) => !evidenceById.has(id));
const failingRegressionEvidence = requiredRegressionEvidence.filter((id) => {
  const evidence = evidenceById.get(id);
  return evidence && !/(passed|validation passed|200|0 failed)/i.test(`${evidence.result} ${evidence.notes || ""}`);
});

const openDefects = defectRecords.filter((defect) => !["Fixed", "Closed", "Waived"].includes(defect.status));
const openCriticalHighDefects = openDefects.filter((defect) => ["Critical", "High"].includes(defect.severity));

const checks = [
  check("phase1_feature_inventory_present", features.length === 101, {
    feature_count: features.length,
    expected_feature_count: 101,
  }),
  check("phase1_required_feature_fields_complete", missingFeatureFields.length === 0, {
    missing_feature_fields_count: missingFeatureFields.length,
    missing_feature_fields: missingFeatureFields,
  }),
  check("phase1_backend_scope_audit_passed", audits.scope.status === "pass", summarizeAudit(audits.scope)),
  check("phase1_frontend_action_audit_passed", audits.frontend_actions.status === "pass", summarizeAudit(audits.frontend_actions)),
  check("phase1_frontend_api_audit_passed", audits.frontend_api.status === "pass", summarizeAudit(audits.frontend_api)),
  check("phase1_configuration_audit_passed", audits.config.status === "pass", summarizeAudit(audits.config)),
  check("phase1_permission_audit_passed", audits.permission.status === "pass", summarizeAudit(audits.permission)),
  check("phase1_runtime_event_audit_passed", audits.events.status === "pass", summarizeAudit(audits.events)),
  check("phase2_test_taxonomy_passed", audits.taxonomy.status === "pass", audits.taxonomy.taxonomy),
  check("phase2_all_features_have_tests", audits.taxonomy.taxonomy.missing_test_count === 0, audits.taxonomy.taxonomy),
  check("phase2_all_features_have_happy_and_risk_paths", audits.taxonomy.taxonomy.missing_happy_path_count === 0 && audits.taxonomy.taxonomy.missing_risk_path_count === 0, audits.taxonomy.taxonomy),
  check("phase3_all_tests_mapped_to_evidence", audits.progress.status === "pass" && audits.progress.matrix.executed_test_count === audits.progress.matrix.test_count, audits.progress.matrix),
  check("phase3_no_orphan_or_missing_safety_rows", audits.progress.execution_progress.orphan_executed_ids.length === 0 && audits.progress.execution_progress.missing_safety_rows.length === 0, {
    orphan_executed_ids: audits.progress.execution_progress.orphan_executed_ids,
    missing_safety_rows: audits.progress.execution_progress.missing_safety_rows,
  }),
  check("phase4_no_open_defects", openDefects.length === 0, {
    open_defect_count: openDefects.length,
    open_defects: openDefects,
  }),
  check("phase4_no_open_critical_or_high_defects", openCriticalHighDefects.length === 0, {
    open_critical_high_defect_count: openCriticalHighDefects.length,
    open_critical_high_defects: openCriticalHighDefects,
  }),
  check("phase5_backend_regression_evidence_passed", !missingRegressionEvidence.includes("EXEC-2026-06-24-REG-001") && !failingRegressionEvidence.includes("EXEC-2026-06-24-REG-001"), evidenceById.get("EXEC-2026-06-24-REG-001") || null),
  check("phase5_mocked_browser_regression_evidence_passed", !missingRegressionEvidence.includes("EXEC-2026-06-24-REG-002") && !failingRegressionEvidence.includes("EXEC-2026-06-24-REG-002"), evidenceById.get("EXEC-2026-06-24-REG-002") || null),
  check("phase5_vm_read_only_regression_evidence_passed", !missingRegressionEvidence.includes("EXEC-2026-06-24-REG-003") && !failingRegressionEvidence.includes("EXEC-2026-06-24-REG-003"), evidenceById.get("EXEC-2026-06-24-REG-003") || null),
  check("phase6_no_missing_discovery_or_execution_gaps", audits.scope.backend.uncovered_count === 0 && audits.frontend_actions.frontend_actions.uncovered_count === 0 && audits.frontend_api.frontend_api.uncovered_count === 0 && audits.progress.matrix.unexecuted_test_count === 0, {
    backend_uncovered: audits.scope.backend.uncovered_count,
    frontend_action_uncovered: audits.frontend_actions.frontend_actions.uncovered_count,
    frontend_api_uncovered: audits.frontend_api.frontend_api.uncovered_count,
    unexecuted_tests: audits.progress.matrix.unexecuted_test_count,
  }),
  check("data_safety_no_unguarded_critical_mutations", audits.safety.execution_safety.unguarded_critical_mutation_count === 0, audits.safety.execution_safety),
  check("data_safety_real_andritz_sftp_not_mutated_by_validation", evidenceSafetyScopesAvoidRealMutation(executionEvidence), {
    checked_evidence_count: executionEvidence.length,
    note: "Safety scopes for regression/audit rows explicitly state local mocked/synthetic/read-only execution and no real Andritz/SFTP collection mutation.",
  }),
];

const failedChecks = checks.filter((entry) => entry.status !== "pass");
const audit = {
  generated_at: new Date().toISOString(),
  scope: {
    workspace: "andritz",
    systems: ["Chat Recherche", "Knowledge Capture", "Collections", "SFTP Andritz safety surface"],
    safety:
      "static completion audit only; reads local matrix/audit artifacts and does not call browser, backend, VM, SFTP, collection, vector or object-store endpoints",
  },
  matrix: {
    feature_count: features.length,
    test_count: allTests.length,
    execution_evidence_count: executionEvidence.length,
    defect_count: defectRecords.length,
    open_defect_count: openDefects.length,
    open_critical_high_defect_count: openCriticalHighDefects.length,
  },
  exit_criteria_checks: checks,
  failed_check_count: failedChecks.length,
  failed_checks: failedChecks,
  status: failedChecks.length === 0 ? "pass" : "fail",
  completion_proven: failedChecks.length === 0,
};

fs.writeFileSync(outputPath, `${JSON.stringify(audit, null, 2)}\n`);
console.log(
  JSON.stringify(
    {
      status: audit.status,
      completion_proven: audit.completion_proven,
      feature_count: audit.matrix.feature_count,
      test_count: audit.matrix.test_count,
      execution_evidence_count: audit.matrix.execution_evidence_count,
      defect_count: audit.matrix.defect_count,
      open_defect_count: audit.matrix.open_defect_count,
      open_critical_high_defect_count: audit.matrix.open_critical_high_defect_count,
      failed_check_count: audit.failed_check_count,
      output: outputPath,
    },
    null,
    2,
  ),
);

if (audit.status !== "pass") {
  process.exitCode = 1;
}

function readJson(filename) {
  return JSON.parse(fs.readFileSync(path.join(outputDir, filename), "utf8"));
}

function check(id, passed, evidence) {
  return {
    id,
    status: passed ? "pass" : "fail",
    evidence,
  };
}

function summarizeAudit(audit) {
  return {
    status: audit.status,
    matrix: audit.matrix,
    scope: audit.scope,
  };
}

function evidenceSafetyScopesAvoidRealMutation(evidenceEntries) {
  const relevantRows = evidenceEntries.filter((entry) => /AUDIT|REG/.test(entry.id));
  return relevantRows.every((entry) => {
    const text = `${entry.safetyScope || ""} ${entry.warnings || ""}`.toLowerCase();
    const realAndritzMutationMentionIsNegated =
      !text.includes("real andritz collection mutation") || text.includes("no real andritz collection mutation");
    const realSftpAccessMentionIsNegated =
      !text.includes("real sftp access") || text.includes("no real sftp access");
    return (
      text.includes("no ") &&
      (text.includes("mutation") || text.includes("read-only") || text.includes("mocked") || text.includes("synthetic")) &&
      realAndritzMutationMentionIsNegated &&
      realSftpAccessMentionIsNegated
    );
  });
}

function loadConstArray(source, constName, endMarker) {
  const declaration = `const ${constName} = `;
  const start = source.indexOf(declaration);
  if (start < 0) {
    throw new Error(`Unable to locate ${constName} declaration`);
  }
  const arrayStart = source.indexOf("[", start);
  const arrayEnd = source.indexOf(endMarker, arrayStart);
  if (arrayStart < 0 || arrayEnd < 0) {
    throw new Error(`Unable to extract ${constName} array`);
  }
  const arrayLiteral = source.slice(arrayStart, arrayEnd + 2);
  const script = new vm.Script(`
    const src = (...refs) => refs.join("\\n");
    const ${constName} = ${arrayLiteral};
    ${constName};
  `);
  return script.runInNewContext(Object.create(null), { timeout: 1000 });
}
