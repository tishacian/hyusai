import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const outputDir = import.meta.dirname;
const matrixSourcePath = path.join(outputDir, "build_andritz_qa_matrix.mjs");
const safetyAuditPath = path.join(outputDir, "andritz_test_execution_safety_audit.json");
const outputPath = path.join(outputDir, "andritz_execution_progress_audit.json");

const matrixSource = fs.readFileSync(matrixSourcePath, "utf8");
const safetyAudit = JSON.parse(fs.readFileSync(safetyAuditPath, "utf8"));
const features = loadConstArray(matrixSource, "features", "\n];\n\nconst executionEvidence");
const defectRecords = loadConstArray(matrixSource, "defectRecords", "\n];\n\nconst allTests");
const allTests = features.flatMap((feature) =>
  (Array.isArray(feature.tests) ? feature.tests : []).map((test, index) => ({
    test_id: `${feature.id}-T${String(index + 1).padStart(2, "0")}`,
    feature_id: feature.id,
    feature_name: feature.name,
    scope: feature.scope,
    type: test.type || "Unspecified",
    scenario: test.scenario || "",
    severity_if_fails: test.severityIfFails || "Medium",
  })),
);

const backlogIds = new Set(allTests.map((test) => test.test_id));
const executedIds = new Set([...matrixSource.matchAll(/pass\("((?:CHT|KCAP|COL|SFTP)-\d+-T\d+)"/g)].map((match) => match[1]));
const orphanExecutedIds = [...executedIds].filter((testId) => !backlogIds.has(testId));
const duplicateExecutedIds = duplicateValues(
  [...matrixSource.matchAll(/pass\("((?:CHT|KCAP|COL|SFTP)-\d+-T\d+)"/g)].map((match) => match[1]),
);

const safetyByTestId = new Map(safetyAudit.execution_safety.tests.map((test) => [test.test_id, test]));
const missingSafetyRows = allTests.filter((test) => !safetyByTestId.has(test.test_id));
const enriched = allTests.map((test) => {
  const safety = safetyByTestId.get(test.test_id) || {};
  const executed = executedIds.has(test.test_id);
  return {
    ...test,
    executed,
    execution_mode: safety.execution_mode || "missing_safety_classification",
    critical_mutation_candidate: Boolean(safety.critical_mutation_candidate),
    mutation_guard_level: safety.mutation_guard_level || "missing_safety_classification",
  };
});

const progressByMode = summarizeBy(enriched, "execution_mode");
const progressByScope = summarizeBy(enriched, "scope");
const progressBySeverity = summarizeBy(enriched, "severity_if_fails");
const unexecuted = enriched.filter((test) => !test.executed);
const executed = enriched.filter((test) => test.executed);
const openDefects = defectRecords.filter((defect) => !["Fixed", "Closed", "Waived"].includes(defect.status));
const openCriticalHighDefects = openDefects.filter((defect) => ["Critical", "High"].includes(defect.severity));

const recommendedNextBatches = [
  nextBatch("static_local_safe", 20),
  nextBatch("mocked_browser_safe", 20),
  nextBatch("fixture_or_synthetic_backend", 20),
  nextBatch("read_only_candidate", 20),
  nextBatch("manual_safety_gate_required", 20),
  nextBatch("mutation_synthetic_or_mock_only", 20),
].filter((batch) => batch.remaining_count > 0);

const audit = {
  generated_at: new Date().toISOString(),
  scope: {
    workspace: "andritz",
    systems: ["Chat Recherche", "Knowledge Capture", "Collections", "SFTP Andritz"],
    safety:
      "static execution-progress audit only; reads local matrix and safety audit, no browser, backend, VM, SFTP, collection, vector or object-store mutation",
  },
  matrix: {
    feature_count: features.length,
    test_count: allTests.length,
    executed_test_count: executed.length,
    unexecuted_test_count: unexecuted.length,
    execution_percent: roundPercent(executed.length, allTests.length),
  },
  execution_progress: {
    by_mode: progressByMode,
    by_scope: progressByScope,
    by_severity: progressBySeverity,
    critical_mutation_candidate_count: enriched.filter((test) => test.critical_mutation_candidate).length,
    executed_critical_mutation_candidate_count: enriched.filter(
      (test) => test.critical_mutation_candidate && test.executed,
    ).length,
    unexecuted_critical_mutation_candidate_count: enriched.filter(
      (test) => test.critical_mutation_candidate && !test.executed,
    ).length,
    open_defect_count: openDefects.length,
    open_critical_high_defect_count: openCriticalHighDefects.length,
    orphan_executed_ids: orphanExecutedIds,
    duplicate_executed_ids: duplicateExecutedIds,
    missing_safety_rows: missingSafetyRows.map((test) => test.test_id),
    recommended_next_batches: recommendedNextBatches,
  },
  status:
    orphanExecutedIds.length === 0 && missingSafetyRows.length === 0
      ? unexecuted.length === 0
        ? "pass"
        : "pass_incomplete_execution_expected"
      : "fail",
};

fs.writeFileSync(outputPath, `${JSON.stringify(audit, null, 2)}\n`);
console.log(
  JSON.stringify(
    {
      status: audit.status,
      feature_count: audit.matrix.feature_count,
      test_count: audit.matrix.test_count,
      executed_test_count: audit.matrix.executed_test_count,
      unexecuted_test_count: audit.matrix.unexecuted_test_count,
      execution_percent: audit.matrix.execution_percent,
      open_defect_count: audit.execution_progress.open_defect_count,
      open_critical_high_defect_count: audit.execution_progress.open_critical_high_defect_count,
      orphan_executed_id_count: audit.execution_progress.orphan_executed_ids.length,
      missing_safety_row_count: audit.execution_progress.missing_safety_rows.length,
      output: outputPath,
    },
    null,
    2,
  ),
);

if (audit.status === "fail") {
  process.exitCode = 1;
}

function nextBatch(mode, limit) {
  const tests = unexecuted
    .filter((test) => test.execution_mode === mode)
    .slice(0, limit)
    .map((test) => ({
      test_id: test.test_id,
      feature_id: test.feature_id,
      feature_name: test.feature_name,
      scope: test.scope,
      type: test.type,
      scenario: test.scenario,
      severity_if_fails: test.severity_if_fails,
      mutation_guard_level: test.mutation_guard_level,
    }));
  return {
    execution_mode: mode,
    remaining_count: unexecuted.filter((test) => test.execution_mode === mode).length,
    suggested_count: tests.length,
    tests,
  };
}

function summarizeBy(items, key) {
  const buckets = new Map();
  for (const item of items) {
    const value = item[key] || "Unspecified";
    const bucket = buckets.get(value) || {
      total: 0,
      executed: 0,
      unexecuted: 0,
      execution_percent: 0,
    };
    bucket.total += 1;
    if (item.executed) {
      bucket.executed += 1;
    } else {
      bucket.unexecuted += 1;
    }
    buckets.set(value, bucket);
  }
  return Object.fromEntries(
    [...buckets.entries()].map(([key, bucket]) => [
      key,
      {
        ...bucket,
        execution_percent: roundPercent(bucket.executed, bucket.total),
      },
    ]),
  );
}

function duplicateValues(values) {
  const counts = new Map();
  for (const value of values) {
    counts.set(value, (counts.get(value) || 0) + 1);
  }
  return [...counts.entries()]
    .filter(([, count]) => count > 1)
    .map(([value, count]) => ({ value, count }));
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

function roundPercent(part, total) {
  if (!total) {
    return 0;
  }
  return Math.round((part / total) * 10000) / 100;
}
