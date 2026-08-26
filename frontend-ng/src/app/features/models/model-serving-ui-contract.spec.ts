/**
 * UI contract of the serving surfaces — the Playground, the key panel, the
 * publish control and the version comparison — asserted against the component
 * sources and the dictionary (same technique as
 * `flow-transform-ui-contract.spec.ts`).
 *
 * These are the claims a demo dies on if they quietly stop being true: the form
 * is generated from the model's own contract, the cURL next to it is the request
 * the form just made, the secret is shown exactly once, and the gauge moves.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { MODELS_EN, MODELS_FR } from '@app/core/i18n/models.dict';

function source(name: string): string {
  return readFileSync(join(process.cwd(), 'src/app/features/models', name), 'utf8');
}

const PLAYGROUND = source('model-playground.component.ts');
const CARD = source('model-view.component.ts');
const CLIENT = source('models.service.ts');

/**
 * Every whole `models.` key a source names, which is what a viewer reads.
 *
 * A literal ending in a dot is a prefix the component completes at runtime
 * (`'models.metric.' + score.key`); those families are covered key-by-key in
 * `models.vm.spec.ts`, where the set of suffixes is known.
 */
function keysIn(text: string): string[] {
  return [...text.matchAll(/'(models\.[^']+)'/g)]
    .map((match) => match[1])
    .filter((key) => !key.endsWith('.'));
}

test('every key the serving surfaces name has FR and EN copy', () => {
  const keys = [...new Set([...keysIn(PLAYGROUND), ...keysIn(CARD)])];
  assert.ok(keys.length > 40, 'the scan found the keys, not zero of them');
  const missing = keys.filter(
    (key) =>
      !(MODELS_FR as Record<string, string>)[key]?.trim() ||
      !(MODELS_EN as Record<string, string>)[key]?.trim(),
  );
  assert.deepEqual(missing, []);
});

test('the card mounts the Playground on the read it already made', () => {
  // One request serves the whole card. A tab that re-fetched the serving block
  // would also re-render the key list under a secret the user is still copying.
  assert.match(CARD, /<ck-tab id="play"/);
  assert.match(CARD, /<app-model-playground/);
  assert.match(CARD, /\[serving\]="plane"/);
  assert.match(CARD, /\(servingChange\)="serving\.set\(\$event\)"/);
  assert.ok(
    !/models\.serving\(/.test(PLAYGROUND),
    'the Playground reads the block from the card, it does not fetch one',
  );
});

test('the request the Playground sends is MLflow serving shape', () => {
  // The whole point of the cURL next to the form: one shape, so the snippet on
  // the slide cannot drift from the call the UI makes.
  assert.match(CLIENT, /inputs: \[row\]/);
  assert.match(CLIENT, /\$\{this\.base\}\/\$\{modelId\}\/predict/);
});

test('the route and the header are the server’s facts, never retyped in the UI', () => {
  // A hardcoded path is how a demo ends up POSTing to a route that moved.
  assert.ok(!/\/api\/v1\//.test(PLAYGROUND), 'the endpoint comes from the block');
  assert.ok(!/X-API-Key/.test(PLAYGROUND), 'the header name comes from the block');
  assert.match(PLAYGROUND, /header: block\.key_header/);
  assert.match(PLAYGROUND, /endpoint: block\.endpoint/);
});

test('the key panel shows a prefix, and the secret only from the mint response', () => {
  assert.match(PLAYGROUND, /\{\{ key\.prefix \}\}…/);
  assert.ok(
    !/key\.secret/.test(PLAYGROUND),
    'a listed key has no secret to render — only the minted one does',
  );
  assert.match(PLAYGROUND, /@if \(minted\(\); as fresh\)/);
  assert.match(PLAYGROUND, /\{\{ fresh\.secret \}\}/);
});

test('a revoked key stays visible, because a demo has to show it stop answering', () => {
  assert.match(PLAYGROUND, /ck-badge--warn.*key\.revoked|\[class\.ck-badge--warn\]="key\.revoked"/s);
  assert.match(PLAYGROUND, /@if \(!key\.revoked\) \{/);
});

test('the gauge animates, because the jump is the argument', () => {
  assert.match(PLAYGROUND, /stroke-dashoffset \d+ms/);
  assert.match(PLAYGROUND, /\[attr\.stroke-dashoffset\]="arc - dial\.dash"/);
});

test('the explanation is asked for explicitly, and only for the one row on screen', () => {
  assert.match(PLAYGROUND, /\{ explain: true \}/);
  assert.match(CLIENT, /options\.explain \? \{ explain: true \} : \{\}/);
});

test('publishing links into the catalog and carries the model’s provenance', () => {
  assert.match(PLAYGROUND, /routerLink="\/skills"/);
  assert.match(PLAYGROUND, /models\.publish\.provenance/);
  assert.match(PLAYGROUND, /\(changed\)|changed\.emit\(\)/);
});

test('the catalog card says which model a published skill answers from', () => {
  const catalog = readFileSync(
    join(process.cwd(), 'src/app/features/skills/skills.component.ts'),
    'utf8',
  );
  // Both surfaces the chip appears on: the row a reader scans, and the panel
  // they open. Each links to the model card, because the chip is a claim and a
  // claim should be checkable in one click.
  assert.match(catalog, /data-testid="skill-provenance"/);
  assert.match(catalog, /data-testid="skill-provenance-detail"/);
  assert.match(catalog, /\[routerLink\]="\['\/models', sk\.provenance!\.model_id\]"/);
  // The same sentence the model card uses — written once, so the two cannot
  // drift into saying the model differently.
  assert.match(catalog, /this\.i18n\.t\('models\.publish\.provenance', params\)/);
  assert.match(catalog, /provenanceLineParams\(/);
  assert.ok(
    (MODELS_FR as Record<string, string>)['models.publish.provenance']?.trim(),
    'models.publish.provenance has FR copy',
  );
  assert.ok(
    (MODELS_EN as Record<string, string>)['models.publish.provenance']?.trim(),
    'models.publish.provenance has EN copy',
  );
  // Derived server side from the frozen binding, so the version it names is the
  // one that currently serves rather than the one that served at publication.
  assert.doesNotMatch(
    catalog,
    /provenance\s*=\s*\{/,
    'the client never assembles a provenance of its own',
  );
});

test('the score tiles carry a delta and the comparison tab is mounted', () => {
  assert.match(CARD, /<ck-tab id="compare"/);
  assert.match(CARD, /class="ck-delta ck-mono"/);
  assert.match(CARD, /\[attr\.data-move\]="delta\.flat \? 'flat' : delta\.better \? 'up' : 'down'"/);
  // Coloured by verdict, not by sign: a smaller MAE has to read as green.
  assert.match(CARD, /\.ck-delta\[data-move='up'\] \{\s*color: var\(--ck-signal-pos/);
});

test('the card names the challenger, and takes that fact from the server', () => {
  // Champion and challenger are one story; a card that showed only the crown
  // would leave the audience without the version promotion would put in.
  assert.match(CARD, /class="ck-badge ck-badge--challenger ck-mono"/);
  assert.match(CARD, /models\.detail\.challenger/);
  assert.match(CARD, /models\.versions\.challenger/);
  // Rendered from `challenger_id`, not worked out here: the same rule drives the
  // registry's `@challenger` alias, and a second implementation would drift.
  assert.match(CARD, /challenger_id \?\? null/);
  assert.match(CLIENT, /challenger_id: string \| null/);
  assert.doesNotMatch(
    CARD,
    /is_champion\s*\)\s*\.sort\(/,
    'the card does not rank versions to guess a challenger',
  );
  // A distinct tone: a contender, not a peer of the version that answers.
  assert.match(CARD, /\.ck-badge--challenger \{\s*color: var\(--ck-signal-warm/);
});

test('promotion hands back both halves of the lineage', () => {
  // Otherwise the crown moves and the challenger badge keeps naming the winner.
  assert.match(CLIENT, /\$\{this\.base\}\/\$\{modelId\}\/champion/);
  assert.match(CLIENT, /challenger_id: string \| null;\s*\}>\(/);
});

test('the card says which version it is without opening a tab', () => {
  // Every version of a lineage shares this page's title, so a card with no
  // version on it leaves the reader unsure whether they are looking at the one
  // that serves — the single most load-bearing fact on the page.
  assert.match(CARD, /data-testid="hero-version"/);
  assert.match(CARD, /models\.versions\.label', \{ version: row\.version \}/);
});

test('the lineage reads forwards, and marks the current and the serving one apart', () => {
  assert.match(CARD, /data-testid="lineage-chain"/);
  // Oldest first: a chain is read as a progression, and `v3 → v2 → v1` says
  // nothing. The list below it stays newest-first, which is a different job.
  assert.match(CARD, /sort\(\(left, right\) => left\.version - right\.version\)/);
  // Two facts, two cues. Sharing one would make "I am reading v2" and "v2
  // serves" indistinguishable.
  assert.match(CARD, /\[attr\.data-current\]="link\.current"/);
  assert.match(CARD, /\[attr\.data-champion\]="link\.champion"/);
  assert.match(CARD, /\.ck-lineage__link\[data-current='true'\]/);
  assert.match(CARD, /\.ck-lineage__link\[data-champion='true'\]/);
  // The arrows are decoration, so they are drawn rather than announced.
  assert.match(CARD, /\.ck-lineage__item:not\(:last-child\)::after/);
  // A single version is not a progression; drawing a one-link chain would be
  // ceremony around nothing.
  assert.match(CARD, /@if \(lineage\(\)\.length > 1\)/);
});

test('the model card draws its charts from the shared viz kit', () => {
  // The plan's kit exists so a curve here and a curve anywhere else are one
  // drawing. Inline `<svg>` creeping back into this file is the regression.
  assert.match(CARD, /<ck-curve-chart/);
  assert.match(CARD, /<ck-confusion-matrix/);
  assert.match(CARD, /<ck-bar-list/);
  assert.doesNotMatch(CARD, /<svg/, 'a chart was hand-rolled here again');
  assert.doesNotMatch(CARD, /class="ck-matrix"/);
  // A ROC without its diagonal cannot be read, so the reference travels with
  // every curve rather than being an option some caller forgets.
  assert.match(CARD, /\[reference\]="DIAGONAL"/);
  assert.match(CARD, /\[reference\]="prevalence\(\)"/);
  assert.match(CARD, /\[reference\]="identity\(\)"/);
});
