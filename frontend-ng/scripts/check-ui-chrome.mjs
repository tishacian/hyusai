/**
 * UI chrome guard — `npm run check:ui-chrome`.
 *
 * Two layers:
 *
 *   1. Hard-fail legacy Cockpit patterns (gradients, brand/violet utilities,
 *      glass/card surfaces) on `src/app`, same exemptions as before.
 *   2. Ratchet on banned fonts, violet/indigo/purple names and hexes, pill
 *      radii, and glow halos. Scans `src/app`, `src/styles`, `src/styles.scss`,
 *      `src/index.html`, and `tailwind.config.ts`. Per-file counts may shrink,
 *      never grow — budget in `docs/compliance/ui-chrome-baseline.v1.json`.
 *
 * Chrome zero (`features/layout/`, `shared/cockpit/`, `src/styles/`) becomes
 * mandatory once L6–L8 land; until then the ratchet alone holds the line.
 *
 * `--write [path]` regenerates the baseline. `--report` prints without failing
 * on ratchet overages (rollback / sweep view).
 */
import {
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { dirname, relative, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');
const repoRoot = resolve(root, '..');
const DEFAULT_BASELINE = resolve(repoRoot, 'docs/compliance/ui-chrome-baseline.v1.json');

const writeIdx = process.argv.indexOf('--write');
const writeAt =
  writeIdx === -1
    ? null
    : resolve(process.cwd(), process.argv[writeIdx + 1] || DEFAULT_BASELINE);
const reportOnly = process.argv.includes('--report');

/** @typedef {{ id: string, name: string, pattern: RegExp }} Rule */

/** Hard-fail legacy patterns (zero tolerance). */
export const legacyForbidden = [
  { name: 'gradient-title', pattern: /\bgradient-title\b/ },
  { name: 'brand-to-violet gradient', pattern: /from-brand-500(?:\/[0-9]+)?\s+to-violet-500/ },
  { name: 'violet gradient endpoint', pattern: /to-violet-500/ },
  { name: 'legacy brand utility', pattern: /\b(?:bg|text|ring|border|from|to|accent)-brand-/ },
  { name: 'legacy violet utility', pattern: /\b(?:bg|text|ring|border|from|to)-violet-/ },
  { name: 'legacy card surface', pattern: /\bt-card\b/ },
  { name: 'legacy glass surface', pattern: /\bglass(?:-blur)?\b/ },
  { name: 'tailwind gradient surface', pattern: /\bbg-gradient-to-/ },
];

/**
 * Ratchet rules. Patterns are line-scoped; each match counts as one hit.
 * Font names stay case-sensitive so prose like "inter-budget" does not trip.
 */
export const ratchetRules = /** @type {Rule[]} */ ([
  {
    id: 'font',
    name: 'banned font',
    pattern:
      /Inter Tight|(?<![A-Za-z])Inter(?![A-Za-z])|(?<![A-Za-z])Roboto(?![A-Za-z])|(?<![A-Za-z])Arial(?![A-Za-z])|JetBrains Mono|JetBrainsMono|(?<![A-Za-z])JetBrains(?![A-Za-z])|font-family\s*:\s*['"]?(?:system-ui|-apple-system|BlinkMacSystemFont)/g,
  },
  {
    id: 'violet',
    name: 'banned violet',
    pattern: /\b(?:violet|indigo|purple)\b|#(?:a78bfa|8b5cf6|6366f1|7c3aed)\b/gi,
  },
  {
    id: 'pill',
    name: 'banned pill radius',
    pattern: /\brounded-(?:full|2xl|3xl)\b|border-radius\s*:\s*(?:999px|50%)/g,
  },
  {
    id: 'halo',
    name: 'banned glow halo',
    pattern: /--ck-glow-|box-shadow\s*:\s*0\s+0\b/g,
  },
]);

const RULE_IDS = ratchetRules.map((rule) => rule.id);

const legacyTargets = ['src/app'];
const ratchetTargets = [
  'src/app',
  'src/styles',
  'src/styles.scss',
  'src/index.html',
  'tailwind.config.ts',
];

const ignored = [
  'src/app/features/mission-room',
  'src/app/features/knowledge/knowledge-capture.component.ts',
];

const ignoredLinePatterns = [/\bvigie-/, /\bAYA\b/, /\bSentinel-CI\b/];

/**
 * @param {string} entry
 * @param {(rel: string) => boolean} [include]
 * @returns {string[]}
 */
export function listFiles(entry, include = () => true) {
  const full = resolve(root, entry);
  if (!existsSync(full)) return [];
  const rel = relative(root, full).split('\\').join('/');
  if (ignored.some((prefix) => rel === prefix || rel.startsWith(`${prefix}/`) || rel.startsWith(prefix))) {
    return [];
  }
  const stat = statSync(full);
  if (stat.isFile()) return include(rel) ? [full] : [];
  const out = [];
  for (const child of readdirSync(full)) {
    out.push(...listFiles(`${entry}/${child}`, include));
  }
  return out;
}

/**
 * @param {string} rel
 */
function isScannable(rel) {
  if (rel.endsWith('.spec.ts')) return false;
  if (rel.endsWith('tailwind.config.ts')) return true;
  return /\.(ts|scss|html|css)$/.test(rel);
}

/**
 * @param {string} line
 * @param {RegExp} pattern
 */
export function countMatches(line, pattern) {
  const flags = pattern.flags.includes('g') ? pattern.flags : `${pattern.flags}g`;
  const re = new RegExp(pattern.source, flags);
  const hits = line.match(re);
  return hits ? hits.length : 0;
}

/**
 * @param {string} text
 * @param {string} rel
 * @param {Rule[]} rules
 * @returns {{ findings: string[], counts: Record<string, number>, samples: Record<string, string[]> }}
 */
export function scanText(text, rel, rules) {
  /** @type {Record<string, number>} */
  const counts = Object.fromEntries(rules.map((rule) => [rule.id, 0]));
  /** @type {Record<string, string[]>} */
  const samples = Object.fromEntries(rules.map((rule) => [rule.id, []]));
  const findings = [];
  const lines = text.split(/\r?\n/);

  for (let idx = 0; idx < lines.length; idx += 1) {
    const line = lines[idx];
    if (ignoredLinePatterns.some((pattern) => pattern.test(line))) continue;
    for (const rule of rules) {
      const n = countMatches(line, rule.pattern);
      if (!n) continue;
      counts[rule.id] += n;
      const sample = `${rel}:${idx + 1}: ${rule.name}`;
      findings.push(sample);
      if (samples[rule.id].length < 3) samples[rule.id].push(sample);
    }
  }
  return { findings, counts, samples };
}

/**
 * @param {string[]} targets
 * @param {Rule[]} rules
 */
export function scanTargets(targets, rules) {
  /** @type {Map<string, { counts: Record<string, number>, samples: Record<string, string[]> }>} */
  const byFile = new Map();
  const findings = [];

  for (const target of targets) {
    for (const file of listFiles(target, isScannable)) {
      const rel = relative(root, file).split('\\').join('/');
      const text = readFileSync(file, 'utf8');
      const scanned = scanText(text, rel, rules);
      findings.push(...scanned.findings);
      const total = RULE_IDS.reduce((sum, id) => sum + (scanned.counts[id] || 0), 0);
      if (total > 0) {
        byFile.set(rel, { counts: scanned.counts, samples: scanned.samples });
      }
    }
  }
  return { findings, byFile };
}

/**
 * @param {Map<string, { counts: Record<string, number>, samples: Record<string, string[]> }>} measured
 * @param {{ files?: Record<string, Record<string, number>> }} baseline
 */
export function compareRatchet(measured, baseline) {
  const files = baseline.files ?? {};
  const over = [];
  const shrunk = [];

  for (const [path, { counts, samples }] of [...measured].sort((a, b) => a[0].localeCompare(b[0]))) {
    const budget = files[path];
    for (const id of RULE_IDS) {
      const count = counts[id] || 0;
      if (!count) continue;
      const max = budget?.[id] ?? 0;
      if (count > max) {
        over.push(`${path}:${id} — ${count} hit(s), budget is ${max}`);
        for (const sample of samples[id] || []) over.push(`    ${sample}`);
      } else if (budget && count < max) {
        shrunk.push(`${path}.${id}: ${max} → ${count}`);
      }
    }
  }

  for (const [path, budget] of Object.entries(files).sort()) {
    const measuredCounts = measured.get(path)?.counts;
    if (!measuredCounts) {
      shrunk.push(`${path}: fully swept, delete the entry`);
      continue;
    }
    for (const id of RULE_IDS) {
      const max = budget[id] || 0;
      if (!max) continue;
      const count = measuredCounts[id] || 0;
      if (count === 0 && max > 0) shrunk.push(`${path}.${id}: ${max} → 0`);
    }
  }

  return { over, shrunk };
}

/**
 * @param {Map<string, { counts: Record<string, number> }>} byFile
 */
export function buildBaseline(byFile) {
  /** @type {Record<string, Record<string, number>>} */
  const files = {};
  for (const [path, { counts }] of [...byFile].sort((a, b) => a[0].localeCompare(b[0]))) {
    /** @type {Record<string, number>} */
    const entry = {};
    let any = false;
    for (const id of RULE_IDS) {
      const n = counts[id] || 0;
      if (n > 0) {
        entry[id] = n;
        any = true;
      }
    }
    if (any) files[path] = entry;
  }
  return {
    schema_version: 1,
    generated_at: new Date().toISOString(),
    rules: Object.fromEntries(ratchetRules.map((rule) => [rule.id, rule.name])),
    files,
  };
}

function scanLegacy() {
  const findings = [];
  const seen = new Set();
  for (const target of legacyTargets) {
    for (const file of listFiles(target, (rel) => /\.(ts|scss|html)$/.test(rel))) {
      const text = readFileSync(file, 'utf8');
      const rel = relative(root, file).split('\\').join('/');
      const lines = text.split(/\r?\n/);
      for (let idx = 0; idx < lines.length; idx += 1) {
        const line = lines[idx];
        if (ignoredLinePatterns.some((pattern) => pattern.test(line))) continue;
        for (const rule of legacyForbidden) {
          if (!rule.pattern.test(line)) continue;
          rule.pattern.lastIndex = 0;
          const finding = `${rel}:${idx + 1}: ${rule.name}`;
          if (!seen.has(finding)) {
            seen.add(finding);
            findings.push(`${finding} (official platform cockpit)`);
          }
        }
      }
    }
  }
  return findings;
}

function main() {
  const legacyFindings = scanLegacy();
  const { byFile } = scanTargets(ratchetTargets, ratchetRules);

  if (writeAt) {
    const report = buildBaseline(byFile);
    mkdirSync(dirname(writeAt), { recursive: true });
    writeFileSync(writeAt, `${JSON.stringify(report, null, 2)}\n`);
    process.stdout.write(
      `check-ui-chrome: wrote baseline (${Object.keys(report.files).length} files) → ${relative(repoRoot, writeAt)}\n`,
    );
    if (legacyFindings.length > 0) {
      console.error('Legacy hard-fail patterns still present; baseline was written anyway.');
      for (const finding of legacyFindings) console.error(`- ${finding}`);
      process.exit(1);
    }
    return;
  }

  if (legacyFindings.length > 0) {
    console.error('Agentium platform chrome must stay Cockpit Workbench.');
    console.error('The following legacy style patterns were found:');
    for (const finding of legacyFindings) console.error(`- ${finding}`);
    console.error('Mission Room / Sentinel-CI / AYA-specific cockpit styles are intentionally not scanned.');
    process.exit(1);
  }

  const baselinePath = existsSync(DEFAULT_BASELINE) ? DEFAULT_BASELINE : null;
  if (!baselinePath) {
    console.error(
      `check-ui-chrome: missing baseline at ${relative(repoRoot, DEFAULT_BASELINE)}. ` +
        `Generate it with: node scripts/check-ui-chrome.mjs --write`,
    );
    process.exit(1);
  }

  const baseline = JSON.parse(readFileSync(baselinePath, 'utf8'));
  const { over, shrunk } = compareRatchet(byFile, baseline);

  if (shrunk.length > 0) {
    console.log('UI chrome budget can be tightened (a sweep landed — please ratchet it down):');
    for (const line of shrunk.slice(0, 40)) console.log(`- ${line}`);
    if (shrunk.length > 40) console.log(`- … and ${shrunk.length - 40} more`);
  }

  const fileCount = byFile.size;
  const hitCount = [...byFile.values()].reduce(
    (sum, row) => sum + RULE_IDS.reduce((s, id) => s + (row.counts[id] || 0), 0),
    0,
  );
  process.stdout.write(
    `check-ui-chrome: ${hitCount} ratchet hit(s) across ${fileCount} file(s)` +
      ` · baseline ${relative(repoRoot, baselinePath)}\n`,
  );

  if (over.length > 0) {
    console.error('UI chrome ratchet failed — counts may only go down:');
    for (const line of over) console.error(`- ${line}`);
    if (!reportOnly) process.exit(1);
  } else {
    console.log('Agentium UI chrome guard OK.');
  }
}

const isMain =
  process.argv[1] &&
  pathToFileURL(resolve(process.argv[1])).href === import.meta.url;

if (isMain) main();
