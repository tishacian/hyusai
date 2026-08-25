/**
 * Every `<app-icon name="…">` in the app must resolve to a registered icon.
 *
 * `LucideIconDirective` converts the name to PascalCase and then looks it up; if
 * the lookup misses, it *throws* during change detection. The screen keeps the
 * gap where the icon should be and the console fills with the same error on every
 * render, which is how three names went unnoticed on the run trace page
 * (`list-tree`, `arrow-right-to-line`, `bookmark`) and four more elsewhere.
 *
 * Two consequences of that PascalCase step are worth stating, because both have
 * already misled us: a kebab-case *key* in the registry can never be reached, and
 * a name has to exist in the installed `lucide-angular`, not merely look
 * plausible — there is no `Cube`, only `Box`.
 */
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';

const APP_ROOT = join(process.cwd(), 'src', 'app');
const REGISTRY = join(APP_ROOT, 'shared', 'ui', 'icon-registry.ts');

/** The conversion `LucideIconDirective.toPascalCase` applies before lookup. */
function toPascalCase(name: string): string {
  return name.replace(/(\w)([a-z0-9]*)(_|-|\s*)/g, (_all, head: string, tail: string) =>
    head.toUpperCase() + tail.toLowerCase(),
  );
}

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return walk(path);
    return path.endsWith('.ts') && !path.endsWith('.spec.ts') ? [path] : [];
  });
}

function registeredKeys(): Set<string> {
  const source = readFileSync(REGISTRY, 'utf8');
  const table = source.slice(source.indexOf('export const REGISTERED_LUCIDE_ICONS'));
  const shorthand = [...table.matchAll(/^ {2}([A-Za-z0-9]+),$/gm)].map((m) => m[1]);
  const explicit = [...table.matchAll(/^ {2}'?([A-Za-z0-9-]+)'?:/gm)].map((m) => m[1]);
  return new Set([...shorthand, ...explicit]);
}

/** Literal lucide names used in templates, excluding the phosphor set. */
function usedNames(): Map<string, string[]> {
  const used = new Map<string, string[]>();
  for (const file of walk(APP_ROOT)) {
    const source = readFileSync(file, 'utf8');
    for (const match of source.matchAll(/<app-icon[^>]*?name="([a-z0-9-]+)"([^>]*?)>/gs)) {
      const [, name, rest] = match;
      if (rest.includes('set="phosphor"')) continue;
      used.set(name, [...(used.get(name) ?? []), file.slice(APP_ROOT.length + 1)]);
    }
  }
  return used;
}

/**
 * Icon names declared as DATA rather than written in a template: palette
 * entries, catalog rows, engine descriptors. They reach the same directive by
 * the same lookup, so they fail the same way — a template scan alone misses
 * them, which is how a palette entry can throw on the first drop.
 */
function declaredNames(): Map<string, string[]> {
  const declared = new Map<string, string[]>();
  for (const file of walk(APP_ROOT)) {
    const source = readFileSync(file, 'utf8');
    for (const match of source.matchAll(/\bicon: '([a-z0-9-]+)'/g)) {
      const name = match[1];
      declared.set(name, [...(declared.get(name) ?? []), file.slice(APP_ROOT.length + 1)]);
    }
  }
  return declared;
}

test('every icon name used in a template resolves in the registry', () => {
  const keys = registeredKeys();
  const used = usedNames();
  assert.ok(used.size > 50, 'the template scanner stopped finding icon usages');

  const unresolved = [...used.entries()]
    .filter(([name]) => !keys.has(toPascalCase(name)))
    .map(([name, files]) => `${name} (→ ${toPascalCase(name)}) used in ${files[0]}`);

  assert.deepEqual(
    unresolved,
    [],
    `these names throw at render time and leave a hole on the page:\n  ${unresolved.join('\n  ')}`,
  );
});

test('every icon name declared as data resolves in the registry too', () => {
  const keys = registeredKeys();
  const declared = declaredNames();
  assert.ok(declared.size > 20, 'the data scanner stopped finding icon declarations');

  const unresolved = [...declared.entries()]
    .filter(([name]) => !keys.has(toPascalCase(name)))
    .map(([name, files]) => `${name} (→ ${toPascalCase(name)}) declared in ${files[0]}`);

  assert.deepEqual(
    unresolved,
    [],
    `these names throw the moment the row they name is rendered:\n  ${unresolved.join('\n  ')}`,
  );
});

test('no registry key is written in a form the lookup can never reach', () => {
  const keys = registeredKeys();
  const unreachable = [...keys].filter((key) => key.includes('-') && !keys.has(toPascalCase(key)));
  assert.deepEqual(
    unreachable,
    [],
    `kebab-case keys are looked up after PascalCase conversion, so these are dead entries: ${unreachable.join(', ')}`,
  );
});
