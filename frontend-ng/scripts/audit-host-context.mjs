/**
 * One-shot audit: `:host-context(...)` rules whose target class does not exist
 * in the host component's own template.
 *
 * Angular's emulated view encapsulation rewrites every rule with the host's
 * `_ngcontent-xxx` attribute, so such a rule can never match anything — it is
 * dead weight that reads as working styling. The voice-controls bar shipped
 * near-white-on-white in light mode for exactly this reason.
 *
 * Not part of `npm test`; run it by hand:
 *   node scripts/audit-host-context.mjs
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');

function walk(dir, acc = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) walk(full, acc);
    else if (/\.(ts|scss|html)$/.test(entry.name) && !entry.name.endsWith('.spec.ts')) {
      acc.push(full);
    }
  }
  return acc;
}

const read = (p) => {
  try {
    return statSync(p).isFile() ? readFileSync(p, 'utf8') : '';
  } catch {
    return '';
  }
};

/**
 * Everything the host component can render: its inline template, any
 * `templateUrl`, and — because a parent may hand markup in through a slot —
 * nothing else. Slotted content is the one legitimate reason a class can be
 * absent here, so we report rather than assert.
 */
function templateOf(tsPath) {
  const src = read(tsPath);
  let text = '';
  const inline = src.match(/template:\s*`([\s\S]*?)`\s*,?\s*(?:styles?|standalone|selector|host|imports|changeDetection|encapsulation|providers|animations|\})/);
  if (inline) text += inline[1];
  const url = src.match(/templateUrl:\s*'([^']+)'/);
  if (url) text += read(join(dirname(tsPath), url[1]));
  // A class can also be attached from the class body — `[class.x]`, a string in
  // a tone map — so the body counts too. The `styles` block must NOT: it is the
  // very CSS under audit, and counting it would make every class look present.
  text += stripStyles(src);
  return text;
}

/** Blank `styles: [...]` and `styles: ` + backtick blocks, keeping offsets. */
function stripStyles(src) {
  let out = src;
  for (const opener of [/styles:\s*\[/g, /styles:\s*`/g]) {
    let match;
    while ((match = opener.exec(out)) !== null) {
      const start = match.index + match[0].length - 1;
      const close = out[start] === '[' ? ']' : '`';
      let i = start + 1;
      let depth = 1;
      while (i < out.length && depth > 0) {
        if (out[i] === '\\') i += 1;
        else if (out[i] === close && close === '`') depth = 0;
        else if (out[i] === '[') depth += 1;
        else if (out[i] === ']') depth -= 1;
        i += 1;
      }
      out = out.slice(0, start) + ' '.repeat(i - start) + out.slice(i);
      opener.lastIndex = i;
    }
  }
  return out;
}

/** The .ts that owns a .scss: same basename, or the file importing it. */
function ownerOf(file) {
  if (file.endsWith('.ts')) return file;
  const sibling = file.replace(/\.scss$/, '.ts');
  if (read(sibling)) return sibling;
  const base = file.split('/').pop();
  for (const candidate of files.filter((f) => f.endsWith('.ts'))) {
    if (read(candidate).includes(base)) return candidate;
  }
  return null;
}

const files = walk(join(root, 'src/app'));
const findings = [];

for (const file of files) {
  const src = read(file);
  if (!src.includes(':host-context')) continue;
  const owner = ownerOf(file);
  const template = owner ? templateOf(owner) : '';
  const rel = relative(root, file);

  const rule = /:host-context\(([^)]*)\)([^{;]*)\{/g;
  let match;
  while ((match = rule.exec(src)) !== null) {
    const [, condition, tail] = match;
    const classes = [...tail.matchAll(/\.([A-Za-z_][\w-]*)/g)].map((m) => m[1]);
    if (classes.length === 0) continue; // `:host-context(x) :host`, `... button`
    const missing = classes.filter(
      (cls) => !new RegExp(`[\\s"'.\\[]${cls}(?![\\w-])`).test(template),
    );
    if (missing.length === 0) continue;
    const line = src.slice(0, match.index).split('\n').length;
    findings.push({
      file: rel,
      line,
      condition: condition.trim(),
      selector: tail.trim(),
      missing,
      owner: owner ? relative(root, owner) : '(no owner found)',
    });
  }
}

if (findings.length === 0) {
  console.log('No dead :host-context rule found.');
} else {
  console.log(`${findings.length} suspect :host-context rule(s):\n`);
  for (const f of findings) {
    console.log(`${f.file}:${f.line}`);
    console.log(`  :host-context(${f.condition}) ${f.selector}`);
    console.log(`  absent from ${f.owner}: ${f.missing.join(', ')}\n`);
  }
}
