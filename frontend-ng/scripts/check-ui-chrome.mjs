import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, relative, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');

const strictTargets = [
  'src/app',
];

const ignored = [
  'src/app/features/mission-room',
  'src/app/features/knowledge/knowledge-capture.component.ts',
];

const ignoredLinePatterns = [
  /\bvigie-/,
  /\bAYA\b/,
  /\bSentinel-CI\b/,
];

const legacyForbidden = [
  { name: 'gradient-title', pattern: /\bgradient-title\b/ },
  { name: 'brand-to-violet gradient', pattern: /from-brand-500(?:\/[0-9]+)?\s+to-violet-500/ },
  { name: 'violet gradient endpoint', pattern: /to-violet-500/ },
];

const strictForbidden = [
  ...legacyForbidden,
  { name: 'legacy brand utility', pattern: /\b(?:bg|text|ring|border|from|to|accent)-brand-/ },
  { name: 'legacy violet utility', pattern: /\b(?:bg|text|ring|border|from|to)-violet-/ },
  { name: 'legacy card surface', pattern: /\bt-card\b/ },
  { name: 'legacy glass surface', pattern: /\bglass(?:-blur)?\b/ },
  { name: 'tailwind gradient surface', pattern: /\bbg-gradient-to-/ },
];

function listFiles(entry) {
  const full = resolve(root, entry);
  if (!existsSync(full)) return [];
  const rel = relative(root, full);
  if (ignored.some((prefix) => rel.startsWith(prefix))) return [];
  const stat = statSync(full);
  if (stat.isFile()) return [full];
  const out = [];
  for (const child of readdirSync(full)) {
    out.push(...listFiles(`${entry}/${child}`));
  }
  return out;
}

function scanTargets(targets, rules, label) {
  const findings = [];
  const seen = new Set();
  for (const target of targets) {
    for (const file of listFiles(target)) {
      if (!/\.(ts|scss|html)$/.test(file)) continue;
      const text = readFileSync(file, 'utf8');
      const rel = relative(root, file);
      for (const rule of rules) {
        const lines = text.split(/\r?\n/);
        for (let idx = 0; idx < lines.length; idx += 1) {
          const line = lines[idx];
          if (ignoredLinePatterns.some((pattern) => pattern.test(line))) continue;
          if (rule.pattern.test(line)) {
            const finding = `${rel}:${idx + 1}: ${rule.name}`;
            if (!seen.has(finding)) {
              seen.add(finding);
              findings.push(`${finding} (${label})`);
            }
          }
        }
      }
    }
  }
  return findings;
}

const findings = [
  ...scanTargets(strictTargets, strictForbidden, 'official platform cockpit'),
];

if (findings.length > 0) {
  console.error('Agentium platform chrome must stay Cockpit Workbench.');
  console.error('The following legacy style patterns were found:');
  for (const finding of findings) console.error(`- ${finding}`);
  console.error('Mission Room / Sentinel-CI / AYA-specific cockpit styles are intentionally not scanned.');
  process.exit(1);
}

console.log('Agentium UI chrome guard OK.');
