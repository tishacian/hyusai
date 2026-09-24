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
const html = readFileSync(join(process.cwd(), 'src/index.html'), 'utf8');
const tailwind = readFileSync(join(process.cwd(), 'tailwind.config.ts'), 'utf8');

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

/** The opaque colour an `rgba()` wash paints over a surface, as a pill does. */
function over(wash: string, surface: string): string {
  const match = wash.match(/^rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)$/);
  assert.ok(match, `not an rgba() wash: ${wash}`);
  const alpha = Number(match[4]);
  return `#${[1, 3, 5]
    .map((offset, index) => alpha * Number(match[index + 1]) + (1 - alpha) * Number.parseInt(surface.slice(offset, offset + 2), 16))
    .map((channel) => Math.round(channel).toString(16).padStart(2, '0'))
    .join('')}`;
}

/**
 * Violet, purple and indigo: a saturated hue between blue and magenta.
 *
 * Near white, HSL saturation misleads: one step of blue (#fcfcfd) already
 * reads as 20 % saturated. The chroma floor keeps such greys out and still
 * catches the palest lavender (#f5f3ff).
 */
function violet([red, green, blue]: number[]): boolean {
  const [r, g, b] = [red, green, blue].map((channel) => channel / 255);
  const max = Math.max(r, g, b);
  const delta = max - Math.min(r, g, b);
  if (delta < 0.04) return false;
  const lightness = (max + max - delta) / 2;
  const saturation = delta / (1 - Math.abs(2 * lightness - 1));
  const sector = max === r ? ((g - b) / delta + 6) % 6 : max === g ? (b - r) / delta + 2 : (r - g) / delta + 4;
  const hue = sector * 60;
  return saturation >= 0.2 && hue >= 230 && hue <= 330;
}

test('primary CTA text meets WCAG AA in dark and light themes', () => {
  assert.equal(token(dark, '--ck-cta-bg'), '#1fb8cc');
  for (const block of [dark, light]) {
    assert.ok(contrast(token(block, '--ck-cta-fg'), token(block, '--ck-cta-bg')) >= 4.5);
  }
});

test('secondary text meets WCAG AA on the canvas and on cockpit panels', () => {
  for (const name of ['--ck-fg-3', '--ck-fg-4', '--ck-fg-5']) {
    assert.equal(token(dark, name), '#a0a9b5', name);
  }
  assert.deepEqual([token(dark, '--ck-bg-base'), token(dark, '--ck-bg-panel')], ['#0d1116', '#121820']);
  for (const block of [dark, light]) {
    for (const surface of ['--ck-bg-base', '--ck-bg-panel']) {
      assert.ok(contrast(token(block, '--ck-fg-4'), token(block, surface)) >= 4.5, surface);
    }
  }
});

test('secondary text meets WCAG AA on raised surfaces too', () => {
  // Popovers and dropdowns sit on `--ck-bg-panel-hi`, not `--ck-bg-panel`, and
  // in the light theme that is the lightest surface — a lighter background than
  // the one the caption colour was chosen against. The column profile panel
  // labels its figures in `--ck-fg-4`, so the pairing has to hold on both.
  assert.equal(token(dark, '--ck-bg-panel-hi'), '#182029');
  for (const block of [dark, light]) {
    assert.ok(contrast(token(block, '--ck-fg-4'), token(block, '--ck-bg-panel-hi')) >= 4.5);
  }
});

test('the light theme has three greys: text, strong text and secondary', () => {
  assert.deepEqual(
    ['--ck-fg-1', '--ck-fg-2', '--ck-fg-3', '--ck-fg-4', '--ck-fg-5'].map((name) => token(light, name)),
    ['#151a21', '#2f3742', '#525c69', '#525c69', '#525c69'],
  );
  assert.equal(token(dark, '--ck-fg-2'), '#c8cdd4');
});

test('--ck-accent and --ck-signal-cool are the primary in both themes', () => {
  // The code reads both as the accent: links, focus rings, buttons. Info keeps
  // its own trio instead.
  assert.deepEqual([token(dark, '--ck-primary'), token(light, '--ck-primary')], ['#1fb8cc', '#0a7483']);
  for (const block of [dark, light]) {
    for (const name of ['--ck-accent', '--ck-signal-cool']) {
      assert.equal(token(block, name), token(block, '--ck-primary'), name);
    }
  }
  assert.equal(token(light, '--ck-status-info-fg'), '#215e8c');
});

test('light text, links, the filled button and the signals meet WCAG AA on every light surface', () => {
  const surfaces = ['--ck-bg-void', '--ck-bg-base', '--ck-bg-panel', '--ck-bg-panel-hi', '--ck-bg-inset'].map(
    (name) => token(light, name),
  );
  assert.deepEqual(surfaces, ['#e9ecef', '#f2f4f6', '#f8f9fa', '#fcfcfd', '#edf0f2']);
  const readable = (foreground: string, background: string, what: string) => {
    const ratio = contrast(foreground, background);
    assert.ok(ratio >= 4.5, `${what}: ${foreground} on ${background} is ${ratio.toFixed(2)}:1`);
  };

  const bare = [
    '--ck-fg-1', '--ck-fg-2', '--ck-fg-3', '--ck-primary',
    '--ck-signal-pos', '--ck-signal-warn', '--ck-signal-neg', '--ck-status-info-fg', '--ck-signal-ice',
  ];
  for (const name of bare) {
    for (const surface of surfaces) readable(token(light, name), surface, name);
  }
  for (const tone of ['ok', 'warn', 'neg', 'info']) {
    for (const surface of surfaces) {
      const pill = over(token(light, `--ck-status-${tone}-bg`), surface);
      readable(token(light, `--ck-status-${tone}-fg`), pill, `${tone} pill`);
    }
  }
  for (const name of ['--ck-cta-bg', '--ck-cta-bg-hover']) {
    readable(token(light, '--ck-cta-fg'), token(light, name), name);
  }
});

test('no token holds #a78bfa, #7c3aed or any other violet', () => {
  const found: string[] = [];
  for (const [file, text] of [['cockpit-tokens.scss', source], ['tailwind.config.ts', tailwind]]) {
    for (const match of text.matchAll(/#([0-9a-f]{6})(?:[0-9a-f]{2})?\b|rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/gi)) {
      const channels = match[1]
        ? [0, 2, 4].map((offset) => Number.parseInt(match[1].slice(offset, offset + 2), 16))
        : [match[2], match[3], match[4]].map(Number);
      if (violet(channels)) found.push(`${file}: ${match[0]}`);
    }
  }
  assert.ok(violet([0xa7, 0x8b, 0xfa]) && violet([0x7c, 0x3a, 0xed]) && violet([0x63, 0x66, 0xf1]));
  assert.ok(violet([0xf5, 0xf3, 0xff]) && !violet([0xfc, 0xfc, 0xfd]));
  assert.deepEqual(found, []);
});

test('the declared families are Space Grotesk, IBM Plex Sans and IBM Plex Mono', () => {
  const lead = (name: string) => token(source, name).split(',')[0].trim().replace(/"/g, '');
  assert.deepEqual(
    ['--ck-font-display', '--ck-font-sans', '--ck-font-mono'].map(lead),
    ['Space Grotesk', 'IBM Plex Sans', 'IBM Plex Mono'],
  );
  const loaded = [...html.matchAll(/[?&]family=([^:&"]+)/g)].map((match) => match[1].replace(/\+/g, ' '));
  assert.deepEqual([...new Set(loaded)].sort(), ['IBM Plex Mono', 'IBM Plex Sans', 'Space Grotesk']);
  for (const [file, text] of [['cockpit-tokens.scss', source], ['index.html', html], ['tailwind.config.ts', tailwind]]) {
    assert.doesNotMatch(text, /\b(?:Inter|JetBrains Mono|Fira Code|Roboto|Arial)\b/, file);
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
