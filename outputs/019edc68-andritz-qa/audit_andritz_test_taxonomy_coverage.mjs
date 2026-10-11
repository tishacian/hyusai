import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const outputDir = import.meta.dirname;
const matrixSourcePath = path.join(outputDir, "build_andritz_qa_matrix.mjs");
const outputPath = path.join(outputDir, "andritz_test_taxonomy_coverage_audit.json");

const matrixSource = fs.readFileSync(matrixSourcePath, "utf8");
const features = loadFeatures(matrixSource);

const categories = [
  category("happy", ["happy"]),
  category("error", ["error"]),
  category("boundary", ["boundary"]),
  category("invalid", ["invalid"]),
  category("permission", ["permission", "security"]),
  category("performance", ["performance"]),
  category("responsive", ["responsive", "mobile"]),
  category("regression", ["regression"]),
  category("destructive_safety", ["destructive"]),
  category("data_integrity", ["data integrity"]),
];
const riskKeywords = [
  "error",
  "boundary",
  "invalid",
  "permission",
  "security",
  "performance",
  "responsive",
  "mobile",
  "regression",
  "destructive",
  "data integrity",
  "accessibility",
  "timeout",
];

const coverage = features.map((feature) => {
  const tests = Array.isArray(feature.tests) ? feature.tests : [];
  const normalizedTypes = tests.map((test) => normalizeType(test.type));
  const categoryHits = Object.fromEntries(
    categories.map((entry) => [
      entry.key,
      normalizedTypes.some((type) => entry.keywords.some((keyword) => type.includes(keyword))),
    ]),
  );
  const hasTests = tests.length > 0;
  const hasHappyPath = categoryHits.happy;
  const hasRiskPath = normalizedTypes.some((type) => riskKeywords.some((keyword) => type.includes(keyword)));
  return {
    feature_id: feature.id,
    feature_name: feature.name,
    scope: feature.scope,
    test_count: tests.length,
    has_tests: hasTests,
    has_happy_path: hasHappyPath,
    has_risk_path: hasRiskPath,
    category_hits: categoryHits,
    test_types: [...new Set(tests.map((test) => test.type || "Unspecified"))],
  };
});

const missingTests = coverage.filter((entry) => !entry.has_tests);
const missingHappyPath = coverage.filter((entry) => !entry.has_happy_path);
const missingRiskPath = coverage.filter((entry) => !entry.has_risk_path);
const categoryFeatureCounts = Object.fromEntries(
  categories.map((entry) => [
    entry.key,
    coverage.filter((feature) => feature.category_hits[entry.key]).length,
  ]),
);

const audit = {
  generated_at: new Date().toISOString(),
  scope: {
    workspace: "andritz",
    systems: ["Chat Recherche", "Knowledge Capture", "Collections", "SFTP Andritz"],
    safety: "static matrix test-taxonomy audit only; no browser, backend, VM, SFTP, collection, vector or object-store mutation",
  },
  matrix: {
    feature_count: features.length,
    test_count: features.reduce((total, feature) => total + (Array.isArray(feature.tests) ? feature.tests.length : 0), 0),
  },
  taxonomy: {
    missing_test_count: missingTests.length,
    missing_happy_path_count: missingHappyPath.length,
    missing_risk_path_count: missingRiskPath.length,
    category_feature_counts: categoryFeatureCounts,
    feature_coverage: coverage,
    missing_tests: missingTests,
    missing_happy_path: missingHappyPath,
    missing_risk_path: missingRiskPath,
  },
  status:
    missingTests.length === 0 && missingHappyPath.length === 0 && missingRiskPath.length === 0
      ? "pass"
      : "fail",
};

fs.writeFileSync(outputPath, `${JSON.stringify(audit, null, 2)}\n`);
console.log(
  JSON.stringify(
    {
      status: audit.status,
      feature_count: audit.matrix.feature_count,
      test_count: audit.matrix.test_count,
      missing_test_count: audit.taxonomy.missing_test_count,
      missing_happy_path_count: audit.taxonomy.missing_happy_path_count,
      missing_risk_path_count: audit.taxonomy.missing_risk_path_count,
      category_feature_counts: audit.taxonomy.category_feature_counts,
      output: outputPath,
    },
    null,
    2,
  ),
);

if (audit.status !== "pass") {
  process.exitCode = 1;
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

function normalizeType(value) {
  return String(value || "").trim().toLowerCase();
}

function category(key, keywords) {
  return { key, keywords };
}
