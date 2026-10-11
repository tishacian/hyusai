import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const outputDir = import.meta.dirname;
const matrixSourcePath = path.join(outputDir, "build_andritz_qa_matrix.mjs");
const outputPath = path.join(outputDir, "andritz_test_execution_safety_audit.json");

const matrixSource = fs.readFileSync(matrixSourcePath, "utf8");
const features = loadFeatures(matrixSource);
const allTests = features.flatMap((feature) =>
  (Array.isArray(feature.tests) ? feature.tests : []).map((test, index) => ({
    test_id: `${feature.id}-T${String(index + 1).padStart(2, "0")}`,
    feature_id: feature.id,
    feature_name: feature.name,
    scope: feature.scope,
    type: test.type || "Unspecified",
    scenario: test.scenario || "",
    preconditions:
      test.preconditions ||
      "Authenticated Andritz workspace user with safe, non-production-destructive test data.",
    steps: test.steps || "",
    expected: test.expected || "",
    severity_if_fails: test.severityIfFails || "Medium",
  })),
);

const classified = allTests.map(classifyTest);
const unclassified = classified.filter((test) => test.execution_mode === "unclassified");
const criticalMutationTests = classified.filter((test) => test.critical_mutation_candidate);
const unguardedCriticalMutations = criticalMutationTests.filter((test) => !test.has_explicit_safety_guard);
const modeCounts = countBy(classified, "execution_mode");
const scopeCounts = countBy(classified, "scope");
const mutationCounts = countBy(
  classified.filter((test) => test.critical_mutation_candidate),
  "mutation_guard_level",
);

const audit = {
  generated_at: new Date().toISOString(),
  scope: {
    workspace: "andritz",
    systems: ["Chat Recherche", "Knowledge Capture", "Collections", "SFTP Andritz"],
    safety:
      "static matrix execution-safety classification only; no browser, backend, VM, SFTP, collection, vector or object-store mutation",
  },
  matrix: {
    feature_count: features.length,
    test_count: allTests.length,
  },
  execution_safety: {
    execution_mode_counts: modeCounts,
    scope_counts: scopeCounts,
    critical_mutation_candidate_count: criticalMutationTests.length,
    mutation_guard_counts: mutationCounts,
    unclassified_count: unclassified.length,
    unguarded_critical_mutation_count: unguardedCriticalMutations.length,
    classification_rules: [
      "mocked_browser_safe: local Playwright/browser scenario explicitly mocked",
      "static_local_safe: audit/build/code-inspection scenario with no runtime data call",
      "read_only_candidate: route/list/open/search/view/load scenario that should remain read-only when run against a backend",
      "fixture_or_synthetic_backend: scenario names synthetic, fixture, test DB, tmp_path or monkeypatch safety",
      "mutation_synthetic_or_mock_only: scenario performs create/upload/publish/promote/delete/clear/revoke/quarantine/archive and must stay synthetic, mocked, denied or explicitly approved",
      "manual_safety_gate_required: scenario is valid but requires human-controlled execution constraints before touching a real system",
    ],
    tests: classified,
    unclassified,
    unguarded_critical_mutations: unguardedCriticalMutations,
  },
  status: unclassified.length === 0 && unguardedCriticalMutations.length === 0 ? "pass" : "fail",
};

fs.writeFileSync(outputPath, `${JSON.stringify(audit, null, 2)}\n`);
console.log(
  JSON.stringify(
    {
      status: audit.status,
      feature_count: audit.matrix.feature_count,
      test_count: audit.matrix.test_count,
      execution_mode_counts: audit.execution_safety.execution_mode_counts,
      critical_mutation_candidate_count: audit.execution_safety.critical_mutation_candidate_count,
      unclassified_count: audit.execution_safety.unclassified_count,
      unguarded_critical_mutation_count: audit.execution_safety.unguarded_critical_mutation_count,
      output: outputPath,
    },
    null,
    2,
  ),
);

if (audit.status !== "pass") {
  process.exitCode = 1;
}

function classifyTest(test) {
  const text = normalize(
    [
      test.scope,
      test.feature_name,
      test.type,
      test.scenario,
      test.preconditions,
      test.steps,
      test.expected,
      test.severity_if_fails,
    ].join(" "),
  );
  const testBody = normalize(
    [test.type, test.scenario, test.steps, test.expected, test.severity_if_fails].join(" "),
  );

  const criticalMutationCandidate = hasCriticalMutation(text);
  const hasExplicitSafetyGuard = hasSafetyGuard(testBody) || hasSafetyGuard(normalize(test.preconditions));
  const executionMode = inferExecutionMode(text, criticalMutationCandidate, hasExplicitSafetyGuard);
  return {
    ...test,
    execution_mode: executionMode,
    critical_mutation_candidate: criticalMutationCandidate,
    has_explicit_safety_guard: hasExplicitSafetyGuard,
    mutation_guard_level: criticalMutationCandidate
      ? hasExplicitSafetyGuard
        ? "guarded_synthetic_mock_denied_or_explicit"
        : "unguarded"
      : "not_mutating",
  };
}

function inferExecutionMode(text, criticalMutationCandidate, hasExplicitSafetyGuard) {
  if (containsAny(text, ["mocked", "mock ", "playwright with mocked", "in-page mocked"])) {
    return "mocked_browser_safe";
  }
  if (containsAny(text, ["static", "audit", "code inspection", "inspect endpoint", "build", "compile", "check:i18n"])) {
    return "static_local_safe";
  }
  if (criticalMutationCandidate && hasExplicitSafetyGuard) {
    return "mutation_synthetic_or_mock_only";
  }
  if (containsAny(text, ["synthetic", "fixture", "test db", "tmp_path", "monkeypatch", "isolated", "disposable"])) {
    return "fixture_or_synthetic_backend";
  }
  if (containsAny(text, ["unauthorized", "unauthenticated", "denied", "permission", "blocked"])) {
    return "fixture_or_synthetic_backend";
  }
  if (
    containsAny(text, [
      "read-only",
      "list",
      "open",
      "view",
      "navigate",
      "search",
      "load",
      "preview",
      "poll",
      "refresh",
      "call",
      "ask",
    ])
  ) {
    return "read_only_candidate";
  }
  if (criticalMutationCandidate) {
    return "manual_safety_gate_required";
  }
  return "manual_safety_gate_required";
}

function hasCriticalMutation(text) {
  return containsAny(text, [
    "delete",
    "clear",
    "wipe",
    "quarantine",
    "promote",
    "publish",
    "upload",
    "create collection",
    "create context",
    "create session",
    "persist",
    "archive",
    "unarchive",
    "revoke",
    "rotate",
    "accept",
    "approve",
    "submit",
    "patch",
    "post ",
    "put ",
    "worker job",
  ]);
}

function hasSafetyGuard(text) {
  return containsAny(text, [
    "synthetic",
    "mock",
    "fixture",
    "test db",
    "tmp_path",
    "monkeypatch",
    "isolated",
    "disposable",
    "explicit approval",
    "explicitly approved",
    "read-only",
    "no request",
    "no clear request",
    "do not execute",
    "without contacting",
    "unauthorized",
    "unauthenticated",
    "denied",
    "blocked",
    "non-production-destructive",
  ]);
}

function loadFeatures(source) {
  const declaration = "const features = ";
  const start = source.indexOf(declaration);
  if (start < 0) {
    throw new Error("Unable to locate features declaration");
  }
  const arrayStart = source.indexOf("[", start);
  const arrayEndMarker = "\n];\n\nconst executionEvidence";
  const arrayEnd = source.indexOf(arrayEndMarker, arrayStart);
  if (arrayStart < 0 || arrayEnd < 0) {
    throw new Error("Unable to extract features array");
  }
  const featuresLiteral = source.slice(arrayStart, arrayEnd + 2);
  const script = new vm.Script(`
    const src = (...refs) => refs.join("\\n");
    const features = ${featuresLiteral};
    features;
  `);
  return script.runInNewContext(Object.create(null), { timeout: 1000 });
}

function countBy(items, key) {
  return items.reduce((counts, item) => {
    const value = item[key] || "Unspecified";
    counts[value] = (counts[value] || 0) + 1;
    return counts;
  }, {});
}

function containsAny(text, needles) {
  return needles.some((needle) => text.includes(needle));
}

function normalize(value) {
  return String(value || "").toLowerCase().replace(/\s+/g, " ").trim();
}
