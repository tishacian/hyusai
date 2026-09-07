/**
 * Count raw links to catalog surfaces (`npm run check:nav-links`).
 *
 * Three motifs from Lot 6 §1, scanned over `src/app/{features,shared,core}`
 * (`*.ts` + `*.html`, not `*.spec.ts`):
 *
 *   A  routerLink="/…"
 *   B  [routerLink]="['/…', …]"
 *   C  router.navigate(['/…']) / navigateByUrl('/…')
 *
 * L6.0: report mode (always exit 0). L6.1: `--fail-closed` fails on any
 * cockpit hit outside the allowlist.
 *
 * `--write <path>` versions the JSON (docs/compliance/nav-links-baseline.v1.json).
 */
import { mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');
const scanRoot = join(root, 'src/app');
const failClosed = process.argv.includes('--fail-closed');
const writeAt = (() => {
  const idx = process.argv.indexOf('--write');
  return idx === -1 ? null : resolve(process.cwd(), process.argv[idx + 1] || '');
})();

/** Allowlist = shells without Cockpit chrome (plan annex A.2). */
const ALLOWLIST_PREFIXES = [
  'features/mission-room/',
  'features/nawa/',
  'features/layout/business-shell-header.component.ts',
  'features/auth/',
  'core/auth.guard.ts',
  'core/auth-refresh-coordinator.service.ts',
  'features/workspace-app-runtime/workspace-app-unavailable.component.ts',
  'features/account/',
  'features/experience/work/',
];

const PATTERN_A = /routerLink\s*=\s*(?:["']\/[^"']*["']|["']\/[^"']*)/g;
const PATTERN_B = /\[routerLink\]\s*=\s*["']\s*\[\s*['"]\//g;
const PATTERN_C = /(?:this\.)?router\.navigate(?:ByUrl)?\(\s*(?:\[\s*['"]\/|['"`]\/)/g;

function walk(dir, acc = []) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) {
      if (name === 'node_modules' || name === 'dist') continue;
      walk(full, acc);
      continue;
    }
    if (!/\.(ts|html)$/.test(name) || name.endsWith('.spec.ts')) continue;
    acc.push(full);
  }
  return acc;
}

function countMatches(source, pattern) {
  const hits = source.match(pattern);
  return hits ? hits.length : 0;
}

function examples(source, pattern, cap = 3) {
  const out = [];
  pattern.lastIndex = 0;
  let match;
  while ((match = pattern.exec(source)) && out.length < cap) {
    const line = source.slice(0, match.index).split('\n').length;
    out.push({ line, snippet: match[0].slice(0, 80) });
  }
  return out;
}

function allowlisted(rel) {
  const posix = rel.split('\\').join('/');
  return ALLOWLIST_PREFIXES.some((prefix) => posix === prefix || posix.startsWith(prefix));
}

const files = walk(scanRoot);
const rows = [];
let cockpitA = 0;
let cockpitB = 0;
let cockpitC = 0;
let allowA = 0;
let allowB = 0;
let allowC = 0;

for (const file of files) {
  const rel = relative(join(root, 'src/app'), file);
  const source = readFileSync(file, 'utf8');
  const a = countMatches(source, PATTERN_A);
  const b = countMatches(source, PATTERN_B);
  const c = countMatches(source, PATTERN_C);
  if (!a && !b && !c) continue;
  const listed = allowlisted(rel);
  if (listed) {
    allowA += a;
    allowB += b;
    allowC += c;
  } else {
    cockpitA += a;
    cockpitB += b;
    cockpitC += c;
  }
  rows.push({
    file: rel,
    A: a,
    B: b,
    C: c,
    total: a + b + c,
    allowlisted: listed,
    examples: [
      ...examples(source, new RegExp(PATTERN_A.source, 'g')),
      ...examples(source, new RegExp(PATTERN_B.source, 'g')),
      ...examples(source, new RegExp(PATTERN_C.source, 'g')),
    ].slice(0, 4),
  });
}

rows.sort((left, right) => right.total - left.total || left.file.localeCompare(right.file));

const report = {
  schema_version: 1,
  mode: failClosed ? 'fail-closed' : 'report',
  generated_at: new Date().toISOString(),
  motifs: {
    A: 'routerLink="/…"',
    B: '[routerLink]="[\'/…\']"',
    C: 'router.navigate([\'/…\']) / navigateByUrl(\'/…\')',
  },
  totals: {
    cockpit: { A: cockpitA, B: cockpitB, C: cockpitC, total: cockpitA + cockpitB + cockpitC },
    allowlist: { A: allowA, B: allowB, C: allowC, total: allowA + allowB + allowC },
  },
  allowlist: ALLOWLIST_PREFIXES,
  files: rows,
};

const json = `${JSON.stringify(report, null, 2)}\n`;
if (writeAt) {
  mkdirSync(dirname(writeAt), { recursive: true });
  writeFileSync(writeAt, json);
}

const cockpit = report.totals.cockpit.total;
const allowed = report.totals.allowlist.total;
process.stdout.write(
  `check-nav-links (${report.mode}): cockpit ${cockpit} raw links` +
    ` (A ${cockpitA} · B ${cockpitB} · C ${cockpitC})` +
    ` · allowlist ${allowed}` +
    (writeAt ? ` · wrote ${relative(root, writeAt)}` : '') +
    '\n',
);

if (failClosed && cockpit > 0) {
  process.stderr.write(
    `fail-closed: ${cockpit} cockpit raw links remain. Migrate them through the catalog.\n`,
  );
  process.exit(1);
}
