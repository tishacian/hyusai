import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');

const sideRail = readFileSync(
  resolve(root, 'src/app/features/layout/side-rail.component.ts'),
  'utf8',
);
const catalog = readFileSync(resolve(root, 'src/app/core/navigation.catalog.ts'), 'utf8');
const dict = readFileSync(resolve(root, 'src/app/core/i18n.dict.ts'), 'utf8');

const dictKeys = new Set([...dict.matchAll(/'([^']+)':/g)].map((match) => match[1]));

function extractUnionMembers(typeName) {
  const match = catalog.match(new RegExp(`export type ${typeName} =([\\s\\S]*?);`));
  if (!match) return [];
  return [...match[1].matchAll(/'([^']+)'/g)].map((entry) => entry[1]);
}

const primaryVerbKeys = extractUnionMembers('CockpitLens');
const sectionKeys = extractUnionMembers('CockpitSectionKey');
const sideRailKeys = [
  ...new Set(
    [...sideRail.matchAll(/i18n\.t\('([^']+)'\)/g)].map((match) => match[1]),
  ),
].filter((key) => !key.includes(' + '));
const missing = new Set();

if (primaryVerbKeys.length === 0 || sectionKeys.length === 0) {
  console.error('Navigation catalog keys could not be parsed.');
  console.error(`CockpitLens=${primaryVerbKeys.length}; CockpitSectionKey=${sectionKeys.length}`);
  process.exit(1);
}

for (const verb of primaryVerbKeys) {
  if (!dictKeys.has(`nav.${verb}`)) missing.add(`nav.${verb}`);
  if (!dictKeys.has(`nav.hint.${verb}`)) missing.add(`nav.hint.${verb}`);
}

for (const key of sectionKeys) {
  if (!dictKeys.has(`nav.${key}`)) missing.add(`nav.${key}`);
}

for (const key of sideRailKeys) {
  if (!dictKeys.has(key)) missing.add(key);
}

if (missing.size > 0) {
  console.error('Missing navigation i18n keys:');
  for (const key of [...missing].sort()) {
    console.error(`- ${key}`);
  }
  process.exit(1);
}

console.log(
  `Navigation i18n coverage OK (${primaryVerbKeys.length + sectionKeys.length + sideRailKeys.length} catalog keys checked).`,
);
