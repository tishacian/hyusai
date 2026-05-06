import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');

const sideRail = readFileSync(
  resolve(root, 'src/app/features/layout/side-rail.component.ts'),
  'utf8',
);
const dict = readFileSync(resolve(root, 'src/app/core/i18n.dict.ts'), 'utf8');

const dictKeys = new Set([...dict.matchAll(/'([^']+)':/g)].map((match) => match[1]));
const verbKeys = [...sideRail.matchAll(/key:\s*'([^']+)'/g)].map((match) => match[1]);
const primaryVerbKeys = ['hypervisor', 'build', 'operate', 'steer', 'govern'];
const missing = new Set();

for (const verb of primaryVerbKeys) {
  if (!dictKeys.has(`nav.${verb}`)) missing.add(`nav.${verb}`);
  if (!dictKeys.has(`nav.hint.${verb}`)) missing.add(`nav.hint.${verb}`);
}

for (const key of verbKeys) {
  if (!dictKeys.has(`nav.${key}`)) missing.add(`nav.${key}`);
}

if (missing.size > 0) {
  console.error('Missing navigation i18n keys:');
  for (const key of [...missing].sort()) {
    console.error(`- ${key}`);
  }
  process.exit(1);
}

console.log(`Navigation i18n coverage OK (${verbKeys.length} catalog keys checked).`);
