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

/**
 * The value a theme block really resolves to, the way the cascade resolves it:
 * the light block only overrides what it restates, so a token it leaves alone
 * (`--ck-status-neutral-fg`) still applies — and its `var(--ck-fg-3)` alias
 * then picks up the *light* `--ck-fg-3`, not the dark one it was declared next
 * to.
 */
function token(block: string, name: string): string {
  const match = block.match(new RegExp(`${name}:\\s*([^;]+);`))
    ?? dark.match(new RegExp(`${name}:\\s*([^;]+);`));
  assert.ok(match, `missing ${name}`);
  const value = match[1].trim();
  const alias = value.match(/^var\((--[^)]+)\)$/)?.[1];
  return alias ? token(block, alias) : value;
}

function channels(hex: string): [number, number, number] {
  assert.match(hex, /^#[0-9a-f]{6}$/i);
  return [1, 3, 5].map((offset) => Number.parseInt(hex.slice(offset, offset + 2), 16)) as
    [number, number, number];
}

function luminance(hex: string): number {
  return channels(hex)
    .map((value) => value / 255)
    .map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4)
    .reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
}

function contrast(foreground: string, background: string): number {
  const [high, low] = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (high + 0.05) / (low + 0.05);
}

/**
 * What a translucent token actually paints once the browser has composited it.
 *
 * A wash token (`--ck-tint-faint`, every `--ck-status-*-bg`) is never the
 * colour behind the text: the opaque surface underneath it is. Reading the
 * token at face value is exactly how a caption can clear AA against
 * `--ck-bg-panel` and still fail on the panel *plus* its own 5 % wash, which
 * is the pairing the Ask shell and every status chip really render.
 */
function flatten(wash: string, base: string): string {
  const parsed = wash.match(/^rgba\(([^)]+)\)$/);
  assert.ok(parsed, `not an rgba() wash: ${wash}`);
  const [r, g, b, alpha] = parsed[1].split(',').map((part) => Number.parseFloat(part.trim()));
  const under = channels(base);
  return `#${[r, g, b]
    .map((value, index) => Math.round(value * alpha + under[index] * (1 - alpha)))
    .map((value) => value.toString(16).padStart(2, '0'))
    .join('')}`;
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

test('secondary text meets WCAG AA on the faint wash panels wear', () => {
  // `--ck-tint-faint` is the standard "slightly recessed" surface: the Ask
  // header rail, the drop sidebar, quiet buttons, neutral chips. It sits on
  // whatever panel hosts it, so the caption tier has to clear AA there too.
  // Only the two surfaces that actually host the wash are checked:
  // `--ck-bg-inset` is itself the recessed surface, and `--ck-bg-panel-hi` is
  // the popover surface, which raises rather than recesses what sits on it.
  for (const block of [dark, light]) {
    for (const base of ['--ck-bg-base', '--ck-bg-panel']) {
      assert.ok(
        contrast(
          token(block, '--ck-fg-4'),
          flatten(token(block, '--ck-tint-faint'), token(block, base)),
        ) >= 4.5,
        `--ck-fg-4 on --ck-tint-faint over ${base}`,
      );
    }
  }
});

test('signal tones are readable as text on every cockpit surface', () => {
  // Title-bar readouts, builder gate counters and inline warnings paint
  // `--ck-signal-*` straight onto a surface with no wash of their own.
  const signals = ['pos', 'neg', 'warn', 'cool', 'violet'];
  for (const block of [dark, light]) {
    for (const signal of signals) {
      for (const surface of ['--ck-bg-base', '--ck-bg-panel', '--ck-bg-panel-hi', '--ck-bg-inset']) {
        assert.ok(
          contrast(token(block, `--ck-signal-${signal}`), token(block, surface)) >= 4.5,
          `--ck-signal-${signal} on ${surface}`,
        );
      }
    }
  }
});

test('status chips keep their label readable on their own tint', () => {
  // `.ck-tone-*` paints `-fg` on `-bg`, and `-bg` is translucent, so the chip
  // resolves differently on a panel than it does on an inset row. Both are
  // real placements (provider cards vs. builder section headers).
  const tones = ['ok', 'warn', 'neg', 'info', 'preview', 'neutral'];
  for (const block of [dark, light]) {
    for (const tone of tones) {
      for (const surface of ['--ck-bg-base', '--ck-bg-panel', '--ck-bg-inset']) {
        assert.ok(
          contrast(
            token(block, `--ck-status-${tone}-fg`),
            flatten(token(block, `--ck-status-${tone}-bg`), token(block, surface)),
          ) >= 4.5,
          `--ck-status-${tone}-fg on its tint over ${surface}`,
        );
      }
    }
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
