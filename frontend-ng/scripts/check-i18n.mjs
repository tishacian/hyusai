/**
 * i18n guard — `npm run check:i18n`.
 *
 * Five checks, in the order a sweep hits them:
 *
 *   1. dictionary hygiene — FR/EN parity, no key defined twice across
 *      domains, every key filed in the domain that owns its prefix;
 *   2. navigation coverage — every navigation catalog entry has its keys;
 *   3. hard-coded UI text — French literals left in a template (3) or in the
 *      TypeScript around it (3b): computed labels, suggestion cards, menu
 *      options, config constants — the half a template-only scan never saw;
 *   4. lexicon — banned synonyms and internal jargon in UI strings;
 *   4b. French terms — an English lexicon term left in a French string
 *      (« Nouveau System »), ratcheted per dictionary;
 *   5. keys no dictionary answers.
 *
 * Every failure prints the fix, not just the fault. Legitimate exceptions
 * live in `scripts/i18n-allowlist.json` with a written reason; the
 * hard-coded-text and French-term budgets are ratchets — they may shrink,
 * never grow.
 *
 * Runs in ~1s: one esbuild pass over the dictionary and the lexicon (so the
 * guard reads real values, not a regex approximation of them), then a single
 * read of every template.
 */
import { build } from 'esbuild';
import { mkdtempSync, readFileSync, readdirSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');
const ALLOWLIST_PATH = 'scripts/i18n-allowlist.json';
/** `I18N_ALL=1 npm run check:i18n` lists every hit — the sweep view. */
const SAMPLE_CAP = process.env['I18N_ALL'] ? Infinity : 3;

const failures = [];
/** @param {string} title @param {string[]} lines */
const fail = (title, lines) => failures.push({ title, lines });
const notes = [];

// ---------------------------------------------------------------------------
// Load the dictionary and the lexicon as real modules.
// ---------------------------------------------------------------------------

const outDir = mkdtempSync(join(tmpdir(), 'i18n-guard-'));
let dict;
let lexicon;
try {
  await build({
    entryPoints: [
      join(root, 'src/app/core/i18n.dict.ts'),
      join(root, 'src/app/core/i18n.lexicon.ts'),
    ],
    bundle: true,
    platform: 'node',
    format: 'esm',
    target: 'es2022',
    outExtension: { '.js': '.mjs' },
    outdir: outDir,
    absWorkingDir: root,
    tsconfig: join(root, 'tsconfig.json'),
    logLevel: 'warning',
  });
  dict = await import(pathToFileURL(join(outDir, 'i18n.dict.mjs')).href);
  lexicon = await import(pathToFileURL(join(outDir, 'i18n.lexicon.mjs')).href);
} finally {
  rmSync(outDir, { recursive: true, force: true });
}

const { I18N_DOMAINS, FR_DICT, EN_DICT } = dict;

// ---------------------------------------------------------------------------
// Allowlist
// ---------------------------------------------------------------------------

/**
 * @typedef {{
 *   hardcodedText: Record<string, { max: number, reason: string }>,
 *   hardcodedCode: Record<string, { max: number, reason: string }>,
 *   lexicon: Record<string, { words: string[], reason: string }>,
 *   frenchTerms: Record<string, { max: number, reason: string }>,
 * }} Allowlist
 */
/** @type {Allowlist} */
const allowlist = JSON.parse(readFileSync(join(root, ALLOWLIST_PATH), 'utf8'));
const textBudget = allowlist.hardcodedText ?? {};
const codeBudget = allowlist.hardcodedCode ?? {};
const lexiconAllowed = allowlist.lexicon ?? {};
const frenchTermBudget = allowlist.frenchTerms ?? {};

// ---------------------------------------------------------------------------
// 1. Dictionary hygiene
// ---------------------------------------------------------------------------

const owningDomain = new Map(); // key -> domain
const prefixOwner = new Map(); // prefix -> domain
for (const [domain, spec] of Object.entries(I18N_DOMAINS)) {
  for (const prefix of spec.prefixes) {
    const previous = prefixOwner.get(prefix);
    if (previous) {
      fail('Two domains claim the same key prefix', [
        `'${prefix}.' is claimed by both '${previous}' and '${domain}' in I18N_DOMAINS.`,
        `Fix: give the prefix to one domain in src/app/core/i18n.dict.ts.`,
      ]);
    }
    prefixOwner.set(prefix, domain);
  }
}

const parityProblems = [];
const misfiled = [];
const duplicated = [];

for (const [domain, spec] of Object.entries(I18N_DOMAINS)) {
  const frKeys = Object.keys(spec.fr);
  const enKeys = new Set(Object.keys(spec.en));
  for (const key of frKeys) {
    if (!enKeys.has(key)) parityProblems.push(`${domain}: '${key}' has FR but no EN`);
    const previous = owningDomain.get(key);
    if (previous) duplicated.push(`'${key}' is defined in both '${previous}' and '${domain}'`);
    owningDomain.set(key, domain);
    const prefix = key.split('.')[0];
    if (!spec.prefixes.includes(prefix)) {
      const owner = prefixOwner.get(prefix);
      misfiled.push(
        owner
          ? `'${key}' sits in ${domain}.dict.ts but '${prefix}.' belongs to ${owner}.dict.ts`
          : `'${key}' sits in ${domain}.dict.ts but no domain claims the prefix '${prefix}.'`,
      );
    }
  }
  for (const key of enKeys) {
    if (!(key in spec.fr)) parityProblems.push(`${domain}: '${key}' has EN but no FR`);
  }
}

if (parityProblems.length > 0) {
  fail('FR/EN parity broken', [
    ...parityProblems,
    'Fix: add the missing side in the same domain module. Both halves of a',
    'domain module must hold exactly the same keys.',
  ]);
}
if (duplicated.length > 0) {
  fail('Key defined in two domains', [
    ...duplicated,
    'Fix: keep it in the domain that owns the prefix and delete the other copy.',
    'A duplicate silently wins by merge order in i18n.dict.ts.',
  ]);
}
if (misfiled.length > 0) {
  fail('Key filed in the wrong domain module', [
    ...misfiled,
    'Fix: move the key to the module that owns its prefix, or claim the prefix',
    "in that module's I18N_DOMAINS entry (src/app/core/i18n.dict.ts).",
  ]);
}

const frCount = Object.keys(FR_DICT).length;
const enCount = Object.keys(EN_DICT).length;
if (frCount !== enCount) {
  fail('Merged dictionaries differ in size', [
    `FR_DICT has ${frCount} keys, EN_DICT has ${enCount}.`,
    'Fix: usually the parity failure above. Otherwise a domain module is missing',
    'from one of the two spreads in src/app/core/i18n.dict.ts.',
  ]);
}

// ---------------------------------------------------------------------------
// 2. Navigation coverage (ported from check-i18n-nav.mjs)
// ---------------------------------------------------------------------------

const sideRail = readFileSync(
  join(root, 'src/app/features/layout/side-rail.component.ts'),
  'utf8',
);
const catalog = readFileSync(join(root, 'src/app/core/navigation.catalog.ts'), 'utf8');

/**
 * Members of a string-literal union declared in the catalog, following
 * aliases: `CockpitLens = CockpitDestination = 'hypervisor' | ObjectLens`
 * resolves down to the five literals.
 */
function extractUnionMembers(typeName, seen = new Set()) {
  if (seen.has(typeName)) return [];
  seen.add(typeName);
  const match = catalog.match(new RegExp(`export type ${typeName} =([\\s\\S]*?);`));
  if (!match) return [];
  const body = match[1];
  const members = [...body.matchAll(/'([^']+)'/g)].map((entry) => entry[1]);
  for (const alias of body.replace(/'[^']*'/g, '').matchAll(/[A-Za-z_$][\w$]*/g)) {
    members.push(...extractUnionMembers(alias[0], seen));
  }
  return [...new Set(members)];
}

const primaryVerbKeys = extractUnionMembers('CockpitLens');
const sectionKeys = extractUnionMembers('CockpitSectionKey');
const sideRailKeys = [
  ...new Set([...sideRail.matchAll(/i18n\.t\('([^']+)'\)/g)].map((match) => match[1])),
].filter((key) => !key.includes(' + '));

if (primaryVerbKeys.length === 0 || sectionKeys.length === 0) {
  fail('Navigation catalog keys could not be parsed', [
    `CockpitLens=${primaryVerbKeys.length}; CockpitSectionKey=${sectionKeys.length}`,
    'Fix: check the union declarations in src/app/core/navigation.catalog.ts.',
  ]);
}

const missingNav = new Set();
for (const verb of primaryVerbKeys) {
  if (!(`nav.${verb}` in FR_DICT)) missingNav.add(`nav.${verb}`);
  if (!(`nav.hint.${verb}` in FR_DICT)) missingNav.add(`nav.hint.${verb}`);
}
for (const key of sectionKeys) {
  if (!(`nav.${key}` in FR_DICT)) missingNav.add(`nav.${key}`);
}
for (const key of sideRailKeys) {
  if (!(key in FR_DICT)) missingNav.add(key);
}
if (missingNav.size > 0) {
  fail('Navigation i18n keys missing', [
    ...[...missingNav].sort().map((key) => `- ${key}`),
    'Fix: add them to src/app/core/i18n/chrome.dict.ts (FR and EN).',
  ]);
}

// ---------------------------------------------------------------------------
// Template collection
// ---------------------------------------------------------------------------

/** Walk src/app for component sources and standalone templates. */
function collectFiles(dir, acc = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      collectFiles(full, acc);
      continue;
    }
    if (entry.name.endsWith('.spec.ts')) continue;
    if (entry.name.endsWith('.ts') || entry.name.endsWith('.html')) acc.push(full);
  }
  return acc;
}

/**
 * Pull every inline `<prop>:` backtick literal out of a component source.
 * Tracks `${}` nesting so a backtick inside an interpolation doesn't end the
 * template early, and keeps absolute offsets so we can report line numbers.
 *
 * @returns {{ text: string, offset: number, end: number }[]}
 */
function backtickBlocks(source, prop) {
  const blocks = [];
  const opener = new RegExp(`(^|[\\s,{])${prop}:\\s*\``, 'g');
  let match;
  while ((match = opener.exec(source)) !== null) {
    const start = match.index + match[0].length;
    let i = start;
    let depth = 0;
    while (i < source.length) {
      const ch = source[i];
      if (ch === '\\') {
        i += 2;
        continue;
      }
      if (ch === '$' && source[i + 1] === '{') {
        depth += 1;
        i += 2;
        continue;
      }
      if (ch === '}' && depth > 0) {
        depth -= 1;
        i += 1;
        continue;
      }
      if (ch === '`' && depth === 0) break;
      i += 1;
    }
    blocks.push({ text: source.slice(start, i), offset: start, end: i });
    opener.lastIndex = i;
  }
  return blocks;
}

const inlineTemplates = (source) => backtickBlocks(source, 'template');

/**
 * `styles: [ ... ]` — the array form. CSS is not screen copy, and blanking it
 * keeps a `content:` rule or a selector out of the French probes.
 *
 * @returns {[number, number][]}
 */
function styleArrayRanges(source) {
  const ranges = [];
  const opener = /(^|[\s,{])styles:\s*\[/g;
  let match;
  while ((match = opener.exec(source)) !== null) {
    const start = match.index + match[0].length - 1;
    let i = start + 1;
    let depth = 1;
    while (i < source.length && depth > 0) {
      const ch = source[i];
      if (ch === '`' || ch === "'" || ch === '"') {
        i += 1;
        while (i < source.length && source[i] !== ch) i += source[i] === '\\' ? 2 : 1;
      } else if (ch === '[') depth += 1;
      else if (ch === ']') depth -= 1;
      i += 1;
    }
    ranges.push([start, i]);
    opener.lastIndex = i;
  }
  return ranges;
}

/**
 * Every string literal in the *code* of a TypeScript source — the half of the
 * repo the template probes are blind to. Computed labels, suggestion cards,
 * menu options and config constants all live here, and a whole screen shipped
 * in French behind a green guard because of it.
 *
 * Skips comments (a French comment is not a shipped string), regex literals
 * (`` /^\s*```/ `` would otherwise open a template literal and swallow the
 * next few hundred lines of code, hiding whatever French sits in them) and
 * the ranges of the `template:`/`styles:` blocks, which the template pass
 * already owns.
 * Inside a backtick literal, `${...}` collapses to `{}`: the surrounding words
 * are copy, the expression is code. `{}` and not a space, so that
 * `` `/runs/${id}/hitl` `` stays the URL it is instead of becoming a sentence.
 *
 * @param {string} source
 * @param {[number, number][]} skip
 * @returns {{ text: string, offset: number }[]}
 */
function tsLiterals(source, skip) {
  const inSkip = (i) => skip.some(([from, to]) => i >= from && i < to);
  const literals = [];
  /**
   * A `/` opens a regex only where a value may start — after an operator, an
   * opening bracket or a `return`. After an identifier or a `)` it is a
   * division. Cheap, and the two cases never overlap in this repo.
   */
  const regexCanStart = (at) => {
    let j = at - 1;
    while (j >= 0 && /\s/.test(source[j])) j -= 1;
    if (j < 0) return true;
    if ('([{,;:=!&|?+-*%<>~^'.includes(source[j])) return true;
    return /\breturn$|\bcase$|\btypeof$/.test(source.slice(Math.max(0, j - 8), j + 1));
  };
  let i = 0;
  while (i < source.length) {
    const ch = source[i];
    if (ch === '/' && source[i + 1] === '/') {
      while (i < source.length && source[i] !== '\n') i += 1;
      continue;
    }
    if (ch === '/' && source[i + 1] === '*') {
      const close = source.indexOf('*/', i + 2);
      if (close < 0) break;
      i = close + 2;
      continue;
    }
    if (ch === '/' && regexCanStart(i)) {
      // Skip the regex body: a `/` or a backtick inside it is not a literal.
      let j = i + 1;
      let inClass = false;
      while (j < source.length && source[j] !== '\n') {
        const c = source[j];
        if (c === '\\') {
          j += 2;
          continue;
        }
        if (c === '[') inClass = true;
        else if (c === ']') inClass = false;
        else if (c === '/' && !inClass) break;
        j += 1;
      }
      // Unterminated on this line: it was a division after all, step over it.
      i = source[j] === '/' ? j + 1 : i + 1;
      continue;
    }
    if (ch !== "'" && ch !== '"' && ch !== '`') {
      i += 1;
      continue;
    }
    if (inSkip(i)) {
      i += 1;
      continue;
    }
    const offset = i;
    i += 1;
    let depth = 0;
    let text = '';
    while (i < source.length) {
      const c = source[i];
      if (c === '\\') {
        text += source.slice(i, i + 2);
        i += 2;
        continue;
      }
      if (ch === '`' && c === '$' && source[i + 1] === '{') {
        depth += 1;
        i += 2;
        text += '{}';
        continue;
      }
      if (ch === '`' && c === '}' && depth > 0) {
        depth -= 1;
        i += 1;
        continue;
      }
      if (c === ch && depth === 0) break;
      if (ch !== '`' && c === '\n') break; // unterminated: a regex or a division
      if (depth === 0) text += c;
      i += 1;
    }
    i += 1;
    literals.push({ text, offset });
  }
  return literals;
}

/**
 * True when a literal can only be an identifier, an API value, a slug, a
 * dotted i18n key, a URL or a CSS/test selector — never something a user
 * reads. This is the whole difficulty of scanning code instead of markup:
 * `'runs.status.hitl_pending'` and `'Aucune conversation'` are both strings.
 *
 * The shape of a label is what a shape of an identifier is not: a space, or a
 * capital followed by lowercase. `'Aucun'` and `'Sous-sujet'` are labels;
 * `'catalog_only'`, `'UNAVAILABLE'`, `'ck-tone-warn'` and `'/api/v1/flows'`
 * are not.
 */
function isTechnicalLiteral(text) {
  if (/\s/.test(text)) return false;
  if (/^[^A-Za-z]*$/.test(text)) return true; // punctuation, numbers, glyphs
  if (/^[a-z][\w$-]*$/.test(text)) return true; // slug, kebab, snake, camelCase
  if (/^[A-Z0-9_]+$/.test(text)) return true; // SCREAMING_SNAKE constant
  if (/[/:@#?&=]/.test(text)) return true; // path, URL, query, selector
  if (/^[\w.$-]+$/.test(text) && text.includes('.')) return true; // dotted key
  return false;
}

/** Replace matches with same-length blanks, keeping newlines so lines still line up. */
function blank(text, pattern) {
  return text.replace(pattern, (m) => m.replace(/[^\n]/g, ' '));
}

/**
 * Blank everything in a template that can't be user-visible text: HTML
 * comments, control-flow block heads (`@for (job of jobs(); track job.id) {`
 * names variables, not copy), event handlers, and class/style/router
 * bindings. Whatever survives is text, an attribute a screen reader or a
 * tooltip will read, or an interpolation — all of which must be translated.
 */
function stripNonText(text) {
  let out = blank(text, /<!--[\s\S]*?-->/g);
  out = blank(out, /@(?:if|else if|else|for|empty|switch|case|default|let|defer|placeholder|loading|error)\b[^{]*\{/g);
  out = blank(out, /\([A-Za-z][\w.:$-]*\)\s*=\s*"[^"]*"/g);
  out = blank(
    out,
    /(?:class|style|routerLink|routerLinkActive|id|name|formControlName|ariaLabel)\s*=\s*"[^"]*"/g,
  );
  // Inside an expression, only quoted literals are copy; `job` in
  // `{{ label(job) }}` is a variable, not a word we ship.
  out = out.replace(/\{\{[\s\S]*?\}\}/g, (m) => keepLiterals(m));
  out = out.replace(
    /(\[[^\]"=\s]+\]|\*[\w-]+)(\s*=\s*")([^"]*)(")/g,
    (_m, attr, mid, expr, close) =>
      attr.replace(/[^\n]/g, ' ') + mid.replace(/[^\n]/g, ' ') + keepLiterals(expr) + close,
  );
  return out;
}

/** Blank everything outside quoted string literals. */
function keepLiterals(expr) {
  let out = '';
  let quote = null;
  for (const ch of expr) {
    if (quote) {
      out += ch;
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === "'" || ch === '"' || ch === '`') {
      quote = ch;
      out += ch;
      continue;
    }
    out += ch === '\n' ? '\n' : ' ';
  }
  return out;
}

const files = collectFiles(join(root, 'src/app'));
/** @type {{ path: string, source: string, blocks: {text:string, offset:number}[] }[]} */
const templates = [];
/** @type {{ path: string, source: string, literals: {text:string, offset:number}[] }[]} */
const codeFiles = [];
for (const full of files) {
  const source = readFileSync(full, 'utf8');
  const path = relative(root, full).split(sep).join('/');
  if (full.endsWith('.html')) {
    templates.push({ path, source, blocks: [{ text: stripNonText(source), offset: 0 }] });
    continue;
  }
  const raw = inlineTemplates(source);
  const blocks = raw.map((b) => ({ text: stripNonText(b.text), offset: b.offset }));
  if (blocks.length > 0) templates.push({ path, source, blocks });
  // The dictionary and the lexicon are where French literals belong.
  if (path.startsWith('src/app/core/i18n')) continue;
  const skip = [
    ...raw.map((b) => [b.offset - 1, b.end + 1]),
    ...backtickBlocks(source, 'styles').map((b) => [b.offset - 1, b.end + 1]),
    ...styleArrayRanges(source),
  ];
  const literals = tsLiterals(source, skip).filter(
    (lit) => lit.text.trim() !== '' && !isTechnicalLiteral(lit.text),
  );
  if (literals.length > 0) codeFiles.push({ path, source, literals });
}

const lineAt = (source, offset) => source.slice(0, offset).split('\n').length;

// ---------------------------------------------------------------------------
// 3. Hard-coded UI text in templates
// ---------------------------------------------------------------------------

const ACCENTED = /[àâäçéèêëîïôöùûüÿœæÀÂÄÇÉÈÊËÎÏÔÖÙÛÜŸŒÆ]/;
/**
 * French elision — `d'`, `l'`, `qu'`, `jusqu'` as standalone tokens.
 *
 * The accent probe alone is blind to French typed without accents, which is
 * how `client360-page.component.ts` shipped a whole screen of hard-coded
 * French the guard never saw. Elision is the part of French that survives
 * accent-stripping: you can write "Vue d'ensemble" without the accent, you
 * cannot write it without the apostrophe.
 *
 * The leading `[^A-Za-z]` is what keeps English out: "world's", "model's"
 * and "field's" have a letter before the `d`, so they don't match, while
 * "d'ensemble" does. `n'` and `s'` are deliberately absent — "doesn't" and
 * "it's" would light up on every English screen.
 */
const ELISION = /(?:^|[^A-Za-z])(?:[dlDL]|[Qq]u|[Jj]usqu)['\u2019](?=[A-Za-zÀ-ÿ])/;
/**
 * French function words — the last probe, for French typed with neither an
 * accent nor an elision ("Detail opportunite selectionnee").
 *
 * Only words with no English homograph are listed, and only function words:
 * a noun list would drift, determiners and prepositions do not. `sans` is
 * deliberately absent — it collides with `font-sans` in every inline style,
 * which is the shape of false positive that makes a guard get ignored.
 * `plus` and `encore` are absent for the same reason.
 */
const FUNCTION_WORDS =
  /(?:^|[^A-Za-z])(?:avec|dans|sous|vers|chez|cette|cet|ces|aucun|aucune|chaque|leurs|notre|nos|votre|vos|depuis|lorsque|ainsi|ensuite|entre|selon|pour|les|des|une|du|aux|elles|nous|vous|toutes|tous|toute|veuillez|cliquez)(?![A-Za-z])/i;
const isFrench = (line) =>
  ACCENTED.test(line) || ELISION.test(line) || FUNCTION_WORDS.test(line);
/** @type {Map<string, {count:number, samples:string[]}>} */
const hardcoded = new Map();

for (const { path, source, blocks } of templates) {
  for (const block of blocks) {
    const lines = block.text.split('\n');
    let cursor = block.offset;
    for (const line of lines) {
      if (isFrench(line)) {
        const entry = hardcoded.get(path) ?? { count: 0, samples: [] };
        entry.count += 1;
        if (entry.samples.length < SAMPLE_CAP) {
          entry.samples.push(`${lineAt(source, cursor)}: ${line.trim().slice(0, 90)}`);
        }
        hardcoded.set(path, entry);
      }
      cursor += line.length + 1;
    }
  }
}

/**
 * Compare a measured per-file count against its ratchet. Over budget is a
 * failure with samples; under budget is a note asking for the new number, so
 * the debt can only ever go down.
 *
 * @param {Map<string, {count:number, samples:string[]}>} measured
 * @param {Record<string, {max:number, reason:string}>} budget
 * @param {string} unit
 */
function ratchet(measured, budget, unit) {
  const over = [];
  const shrunk = [];
  for (const [path, { count, samples }] of [...measured].sort()) {
    const entry = budget[path];
    if (!entry) {
      over.push(`${path} — ${count} ${unit}`);
      for (const sample of samples) over.push(`    ${sample}`);
      continue;
    }
    if (count > entry.max) {
      over.push(`${path} — ${count} ${unit}, budget is ${entry.max} (${entry.reason})`);
      for (const sample of samples) over.push(`    ${sample}`);
    } else if (count < entry.max) {
      shrunk.push(`${path}: "max": ${entry.max} → ${count}`);
    }
  }
  for (const path of Object.keys(budget)) {
    if (!measured.has(path)) shrunk.push(`${path}: fully swept, delete the entry`);
  }
  return { over, shrunk };
}

const SWEEP_FIX = [
  'Fix: move the string to the domain module of src/app/core/i18n/ and render',
  "it with i18n.t('domain.surface.thing'). See src/app/core/i18n/CONVENTION.md.",
];

const template = ratchet(hardcoded, textBudget, 'French line(s)');
if (template.over.length > 0) {
  fail('Hard-coded French text in a template', [
    ...template.over,
    '',
    ...SWEEP_FIX,
    `If the text is seeded business content and must stay literal, add it to`,
    `${ALLOWLIST_PATH} under "hardcodedText" with a "max" and a "reason".`,
  ]);
}
if (template.shrunk.length > 0) {
  notes.push(
    'Hard-coded text budget can be tightened (a sweep landed — please ratchet it down):',
    ...template.shrunk.map((line) => `  ${line}`),
  );
}

// ---------------------------------------------------------------------------
// 3b. Hard-coded UI text in TypeScript code
// ---------------------------------------------------------------------------

/**
 * The same three probes, on the other half of the repo. Until this pass
 * existed the guard only read `template:` blocks, so every computed label,
 * suggestion card, menu option and config constant was invisible to it — and
 * `client360-page.component.ts` sat green with 44 lines of French in its
 * class body while the allowlist ratchet measured only its markup.
 *
 * Own budget, own ratchet: the template numbers were measured on markup and
 * folding the two together would silently reset them.
 */
/** @type {Map<string, {count:number, samples:string[]}>} */
const hardcodedCode = new Map();
for (const { path, source, literals } of codeFiles) {
  for (const lit of literals) {
    if (!isFrench(lit.text)) continue;
    const entry = hardcodedCode.get(path) ?? { count: 0, samples: [] };
    entry.count += 1;
    if (entry.samples.length < SAMPLE_CAP) {
      entry.samples.push(`${lineAt(source, lit.offset)}: ${lit.text.trim().slice(0, 90)}`);
    }
    hardcodedCode.set(path, entry);
  }
}

const code = ratchet(hardcodedCode, codeBudget, 'French literal(s)');
if (code.over.length > 0) {
  fail('Hard-coded French text in TypeScript code', [
    ...code.over,
    '',
    ...SWEEP_FIX,
    'Identifiers, API values, slugs, dotted keys, URLs and selectors are not',
    'reported — only literals shaped like something a user reads.',
    `If the literal is seeded scenario data or a French sample value, add it to`,
    `${ALLOWLIST_PATH} under "hardcodedCode" with a "max" and a "reason".`,
  ]);
}
if (code.shrunk.length > 0) {
  notes.push(
    'Hard-coded code budget can be tightened (a sweep landed — please ratchet it down):',
    ...code.shrunk.map((line) => `  ${line}`),
  );
}

// ---------------------------------------------------------------------------
// 4. Lexicon enforcement
// ---------------------------------------------------------------------------

const forbidden = lexicon.forbiddenWords().map((entry) => ({
  ...entry,
  re: new RegExp(
    `(?<![A-Za-z0-9_-])${entry.word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?![A-Za-z0-9_-])`,
    'i',
  ),
}));

const wordAllowed = (path, word) =>
  (lexiconAllowed[path]?.words ?? []).some((w) => w.toLowerCase() === word.toLowerCase());

const lexiconHits = [];

function checkString(path, location, text) {
  for (const entry of forbidden) {
    if (!entry.re.test(text)) continue;
    if (wordAllowed(path, entry.word)) continue;
    const fix =
      entry.kind === 'banned-synonym'
        ? `say "${entry.en}" / "${entry.fr}" instead`
        : `internal term: primary label is "${entry.en}" / "${entry.fr}", keep the raw term on a secondary line or in a title`;
    lexiconHits.push(`${path}:${location} — "${entry.word}" (${entry.conceptId}): ${fix}`);
  }
}

for (const [key, value] of Object.entries(FR_DICT)) {
  const domain = owningDomain.get(key) ?? 'unknown';
  checkString(`src/app/core/i18n/${domain}.dict.ts`, key, String(value));
}
for (const [key, value] of Object.entries(EN_DICT)) {
  const domain = owningDomain.get(key) ?? 'unknown';
  checkString(`src/app/core/i18n/${domain}.dict.ts`, key, String(value));
}
for (const { path, source, blocks } of templates) {
  for (const block of blocks) {
    let cursor = block.offset;
    for (const line of block.text.split('\n')) {
      if (line.trim()) checkString(path, String(lineAt(source, cursor)), line);
      cursor += line.length + 1;
    }
  }
}
// Code literals too: a label computed in the class body is as visible as one
// typed in the markup, and `'Pipeline mode'` drifts there just as easily.
for (const { path, source, literals } of codeFiles) {
  for (const lit of literals) {
    checkString(path, String(lineAt(source, lit.offset)), lit.text);
  }
}

if (lexiconHits.length > 0) {
  fail('Lexicon violation in a UI string', [
    ...lexiconHits,
    '',
    'The lexicon is src/app/core/i18n.lexicon.ts — one concept, one word.',
    'Fix: use the canonical term. If this occurrence is legitimate (a third-party',
    `name, a code sample, an API field shown as raw detail), add it to ${ALLOWLIST_PATH}`,
    'under "lexicon" with the file path, the words, and a "reason".',
  ]);
}

// ---------------------------------------------------------------------------
// 4b. French strings that keep the English term
// ---------------------------------------------------------------------------

/**
 * The lexicon says System is « Système » and Run is « Exécution » in French,
 * yet « Nouveau System » and « Voir dans Runs → » shipped behind a green
 * guard: the banned-word pass only knows synonyms, not a term left in
 * English. This pass reads every French value — dictionary and lexicon
 * definitions — for the `untranslated` forms the lexicon declares.
 *
 * One hit per key, whatever the number of words in it. A ratchet, not a hard
 * fail: `frenchTerms[path].max` in the allowlist may only go down, so a
 * dictionary another stream is still sweeping stays green without letting a
 * new occurrence in.
 */
/** @type {Map<string, {count:number, samples:string[]}>} */
const untranslated = new Map();
/** @param {string} path @param {string} key @param {string} text */
function checkFrench(path, key, text) {
  const words = lexicon.untranslatedInFrench(text);
  if (words.length === 0) return;
  const entry = untranslated.get(path) ?? { count: 0, samples: [] };
  entry.count += 1;
  if (entry.samples.length < SAMPLE_CAP) {
    const say = words.map((w) => `"${w.word}" → « ${w.fr} »`).join(', ');
    entry.samples.push(`${key}: ${say} — ${text.trim().slice(0, 70)}`);
  }
  untranslated.set(path, entry);
}
for (const [key, value] of Object.entries(FR_DICT)) {
  const domain = owningDomain.get(key) ?? 'unknown';
  checkFrench(`src/app/core/i18n/${domain}.dict.ts`, key, String(value));
}
for (const entry of lexicon.UI_LEXICON) {
  checkFrench('src/app/core/i18n.lexicon.ts', `${entry.id}.definition.fr`, entry.definition.fr);
}

const frenchTerms = ratchet(untranslated, frenchTermBudget, 'French string(s) with an English term');
if (frenchTerms.over.length > 0) {
  fail('English term left in a French string', [
    ...frenchTerms.over,
    '',
    'Fix: say the French term of src/app/core/i18n.lexicon.ts, with its',
    'agreement — « Nouveau système », « Exécutions terminées », « Ouvrir',
    "l'exécution ». Skill, Capability and Flow are product nouns and stay as is.",
    `A genuine exception (a product name) goes to ${ALLOWLIST_PATH} under`,
    '"frenchTerms" with a "max" and a "reason".',
  ]);
}
if (frenchTerms.shrunk.length > 0) {
  notes.push(
    'French-term budget can be tightened (a sweep landed — please ratchet it down):',
    ...frenchTerms.shrunk.map((line) => `  ${line}`),
  );
}

// ---------------------------------------------------------------------------
// 5. Keys that no dictionary answers
// ---------------------------------------------------------------------------

/**
 * `I18nService.t` is typed `I18nKey | string`, because the API-mirroring call
 * sites build their key at runtime. The cost of that escape hatch is that a
 * mistyped or never-declared literal is not a `tsc` error — it renders the key
 * itself on screen, as `flow.toolbar.state.hold` did in the toolbar's autosave
 * pill until a Playwright assertion happened to read the pill.
 *
 * So: every literal key handed to `t()` must exist. Template-literal and
 * concatenated keys are skipped — those are the legitimate runtime lookups,
 * and CONVENTION.md §3 requires them to fall back to the raw value.
 */
const unknownKeys = [];
const T_CALL = /\bt\(\s*'([^'`$]+)'/g;
for (const full of files) {
  const source = readFileSync(full, 'utf8');
  const path = relative(root, full).split(sep).join('/');
  if (path.startsWith('src/app/core/i18n')) continue;
  let hit;
  while ((hit = T_CALL.exec(source)) !== null) {
    const key = hit[1];
    // `t('…')` only ever takes a dotted key; anything else is another `t(`.
    if (!/^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$/i.test(key)) continue;
    if (key in FR_DICT) continue;
    unknownKeys.push(`${path}:${lineAt(source, hit.index)} — t('${key}') has no entry`);
  }
}

if (unknownKeys.length > 0) {
  fail('Key handed to t() that no dictionary defines', [
    ...unknownKeys,
    '',
    'Fix: declare the key in the domain module that owns its prefix. A missing',
    'key is not a blank — t() returns the key, so the raw dotted string ships to',
    'the screen.',
  ]);
}

// ---------------------------------------------------------------------------
// Report
// ---------------------------------------------------------------------------

if (failures.length > 0) {
  for (const { title, lines } of failures) {
    console.error(`\n✗ ${title}`);
    for (const line of lines) console.error(`  ${line}`);
  }
  console.error(`\n${failures.length} i18n check(s) failed.`);
  process.exit(1);
}

for (const line of notes) console.log(line);
console.log(
  `i18n OK — ${frCount} keys across ${Object.keys(I18N_DOMAINS).length} domains, ` +
    `${primaryVerbKeys.length + sectionKeys.length + sideRailKeys.length} navigation keys, ` +
    `${templates.length} templates and ${codeFiles.length} code files scanned, ` +
    `${forbidden.length} lexicon rules and ${lexicon.untranslatedTerms().length} French-term rules enforced.`,
);
