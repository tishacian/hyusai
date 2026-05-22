import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, relative, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');

const targets = [
  'src/app/shared/ui/section-header.component.ts',
  'src/app/features/workspace',
  'src/app/features/governance',
  'src/app/features/resources',
  'src/app/features/connectors',
  'src/app/features/settings',
];

const ignored = [
  'src/app/features/mission-room',
];

const forbidden = [
  { name: 'gradient-title', pattern: /\bgradient-title\b/ },
  { name: 'brand-to-violet gradient', pattern: /from-brand-500(?:\/[0-9]+)?\s+to-violet-500/ },
  { name: 'violet gradient endpoint', pattern: /to-violet-500/ },
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

const findings = [];
for (const target of targets) {
  for (const file of listFiles(target)) {
    if (!/\.(ts|scss|html)$/.test(file)) continue;
    const text = readFileSync(file, 'utf8');
    for (const rule of forbidden) {
      const match = text.match(rule.pattern);
      if (match) {
        findings.push(`${relative(root, file)}: ${rule.name}`);
      }
    }
  }
}

if (findings.length > 0) {
  console.error('Generic Agentium chrome must stay Cockpit Lean.');
  console.error('The following legacy style patterns were found:');
  for (const finding of findings) console.error(`- ${finding}`);
  console.error('Sentinel-CI / AYA-specific cockpit styles are intentionally not scanned.');
  process.exit(1);
}

console.log('Agentium UI chrome guard OK.');
