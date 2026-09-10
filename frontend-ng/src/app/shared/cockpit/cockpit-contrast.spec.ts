import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';

/**
 * Every file that can style something, recursively.
 *
 * Specs are excluded: they name tokens in prose and in assertions about tokens,
 * neither of which paints a pixel.
 */
function sources(root: string): string[] {
  return readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const path = join(root, entry.name);
    if (entry.isDirectory()) return sources(path);
    if (/\.spec\.ts$/.test(entry.name)) return [];
    return /\.(ts|scss|css|html)$/.test(entry.name) ? [path] : [];
  });
}

const source = readFileSync(join(process.cwd(), 'src/styles/cockpit-tokens.scss'), 'utf8');
const dark = source.slice(source.indexOf(':root,'), source.indexOf('html:not(.dark)'));
const light = source.slice(source.indexOf('html:not(.dark)'));

function token(block: string, name: string): string {
  const match = block.match(new RegExp(`${name}:\\s*([^;]+);`));
  assert.ok(match, `missing ${name}`);
  const value = match[1].trim();
  const alias = value.match(/^var\((--[^)]+)\)$/)?.[1];
  return alias ? token(block, alias) : value;
}

function luminance(hex: string): number {
  assert.match(hex, /^#[0-9a-f]{6}$/i);
  const channels = [1, 3, 5].map((offset) => Number.parseInt(hex.slice(offset, offset + 2), 16) / 255);
  return channels
    .map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4)
    .reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
}

function contrast(foreground: string, background: string): number {
  const [high, low] = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (high + 0.05) / (low + 0.05);
}

test('primary CTA text meets WCAG AA in dark and light themes', () => {
  for (const block of [dark, light]) {
    assert.ok(contrast(token(block, '--ck-cta-fg'), token(block, '--ck-cta-bg')) >= 4.5);
  }
});

test('secondary text meets WCAG AA on cockpit panels', () => {
  for (const block of [dark, light]) {
    assert.ok(contrast(token(block, '--ck-fg-4'), token(block, '--ck-bg-panel')) >= 4.5);
  }
});

test('secondary text meets WCAG AA on raised surfaces too', () => {
  // Popovers and dropdowns sit on `--ck-bg-panel-hi`, not `--ck-bg-panel`, and
  // in the light theme that is pure white — a lighter background than the one
  // the caption colour was chosen against. The column profile panel labels its
  // figures in `--ck-fg-4`, so the pairing has to hold on both surfaces.
  for (const block of [dark, light]) {
    assert.ok(contrast(token(block, '--ck-fg-4'), token(block, '--ck-bg-panel-hi')) >= 4.5);
  }
});

test('every cockpit token a component names is a token the theme defines', () => {
  // A misspelled or invented token is silent: `var(--ck-bg-elevated, #14161c)`
  // compiles, renders, and looks right in whichever theme the fallback happens
  // to suit — then shows dark text on a dark panel in the other one. The
  // fallback is what hides it, so the reference itself has to be checked.
  const defined = new Set(
    [...source.matchAll(/^\s*(--ck-[a-z0-9-]+)\s*:/gm)].map((match) => match[1]),
  );
  const referenced = new Map<string, string>();
  for (const file of sources(join(process.cwd(), 'src/app'))) {
    for (const match of readFileSync(file, 'utf8').matchAll(
      /var\(\s*(--ck-[a-z0-9-]+)/g,
    )) {
      // A trailing hyphen is a prefix the code completes at runtime
      // (`var(--ck-signal-${tone})`); no token is named that, and which one is
      // meant is not knowable from the source.
      if (match[1].endsWith('-')) continue;
      if (!referenced.has(match[1])) referenced.set(match[1], file);
    }
  }

  assert.ok(referenced.size > 50, 'the scan found the references, not none of them');
  const unknown = [...referenced].filter(([name]) => !defined.has(name));
  assert.deepEqual(
    unknown.map(([name, file]) => `${name} (${file.replace(process.cwd(), '')})`),
    [],
  );
});
