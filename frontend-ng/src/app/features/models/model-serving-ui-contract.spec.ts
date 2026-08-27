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
const LIST = source('models-list.component.ts');
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

test('a card off the serving alias predicts from itself, form and snippet alike', () => {
  // The form is built from `block.fields`, which is *this* version's signature.
  // Left unpinned the call is answered by the champion, and two versions of a
  // lineage need not share a column list — so on any card but the serving one
  // the money shot was a contract refusal. One read, used by both, so the
  // command the audience copies reproduces the answer they just watched.
  assert.match(PLAYGROUND, /pinnedVersion\(this\.serving\(\), this\.model\(\)\.version\)/);
  assert.match(PLAYGROUND, /version: this\.pinned\(\)/, 'the snippet carries the pin');
  assert.match(
    PLAYGROUND,
    /const pinned = this\.pinned\(\);[\s\S]{0,220}\.\.\.\(pinned \? \{ version: pinned \} : \{\}\)/,
    'the call carries the pin',
  );
  // And the line beside the button promises whichever version will answer,
  // rather than a champion the pin deliberately bypasses.
  assert.match(PLAYGROUND, /served\?\.version \?\? this\.pinned\(\) \?\? block\.serving_version/);
  assert.match(CLIENT, /options\.version \? \{ version: options\.version \} : \{\}/);
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
  // The handle is moved by the property the fill is moved by. It was a rotated
  // group once, on the same duration and the same curve, and it still trailed
  // the stroke's tip by a third of the dial: a browser interpolates a transform
  // and a dash offset by different rules, and only one of them was the easing
  // this dial asked for.
  assert.match(PLAYGROUND, /class="ck-gauge__hand"/);
  assert.match(PLAYGROUND, /\[attr\.stroke-dashoffset\]="dial\.handle"/);
  assert.match(PLAYGROUND, /\.ck-gauge__hand \{[\s\S]*?transition: stroke-dashoffset 620ms/);
  assert.doesNotMatch(PLAYGROUND, /transition: transform \d+ms/);
  assert.match(PLAYGROUND, /prefers-reduced-motion: reduce/);
});

test('the dial is an instrument: a ramp, a glow, and a point to read it off', () => {
  // A flat 11px stroke is a progress bar bent into a semicircle. The ramp gives
  // the arc a direction, the glow lifts it off the track, and the handle gives
  // the number somewhere to be.
  assert.match(PLAYGROUND, /<linearGradient \[attr\.id\]="rampId"/);
  assert.match(PLAYGROUND, /class="ck-gauge__stop ck-gauge__stop--from"/);
  assert.match(PLAYGROUND, /stop-color: var\(--gauge-ink\)/);
  // Two passes of one dot, wide then narrow, so the handle reads as a ring on
  // the track rather than as a blob of the same colour as the stroke.
  assert.match(PLAYGROUND, /class="ck-gauge__hand ck-gauge__hand--core"/);
  assert.match(PLAYGROUND, /\.ck-gauge__hand--core \{[\s\S]*?stroke: var\(--ck-bg-panel/);
  assert.match(PLAYGROUND, /filter: drop-shadow\(/);
});

test('one property carries the dial’s verdict to everything drawn from it', () => {
  // Flagged is a fact about the answer, and the arc, its glow and the handle's
  // ring all have to agree about it. One custom property on the root, rather
  // than a `--flag` variant of each of them.
  assert.match(PLAYGROUND, /\[class\.ck-gauge--flag\]="dial\.flagged"/);
  assert.match(PLAYGROUND, /\.ck-gauge--flag \{\s*--gauge-ink: var\(--ck-signal-neg/);
  assert.ok(
    !/\.ck-gauge__fill--flag/.test(PLAYGROUND),
    'the per-element flag variants are gone, not merely unused',
  );
});

test('each dial owns the gradient it paints itself with', () => {
  // `url(#id)` resolves document-wide: a shared id would let one Playground
  // paint another one's arc, flagged colour included.
  assert.match(PLAYGROUND, /let gauges = 0/);
  assert.match(PLAYGROUND, /rampId = `ck-gauge-ramp-\$\{\+\+gauges\}`/);
  assert.match(PLAYGROUND, /\[attr\.stroke\]="'url\(#' \+ rampId \+ '\)'"/);
  // And the paint stays an attribute: a `stroke` in the stylesheet would
  // outrank it and silently restore the flat fill.
  const fill = /\.ck-gauge__fill \{([^}]*)\}/.exec(PLAYGROUND);
  assert.ok(fill, 'the fill has a rule');
  assert.ok(!/\bstroke:/.test(fill![1]), 'and that rule sets no stroke');
});

test('the explanation is asked for explicitly, and only for the one row on screen', () => {
  assert.match(PLAYGROUND, /explain: true/);
  assert.match(CLIENT, /options\.explain \? \{ explain: true \} : \{\}/);
});

test('publishing links into the catalog and carries the model’s provenance', () => {
  assert.match(PLAYGROUND, /routerLink="\/skills"/);
  assert.match(PLAYGROUND, /models\.publish\.provenance/);
  assert.match(PLAYGROUND, /\(changed\)|changed\.emit\(\)/);

  // The toast is itself the deep link. The whole point of publishing is that
  // the model is now a Skill in the catalogue, and the shortest path to seeing
  // that is a tap on the thing that just said so — so the toast survives the
  // tap and navigates, rather than dismissing and leaving the reader to hunt.
  assert.match(PLAYGROUND, /\.onTap\.subscribe\(\(\) => \{/);
  assert.match(PLAYGROUND, /this\.router\.navigate\(\['\/skills'\], \{ queryParams: \{ q: slug \} \}\)/);
  assert.match(PLAYGROUND, /tapToDismiss: false/);
  for (const dict of [MODELS_FR, MODELS_EN]) {
    const copy = (dict as Record<string, string>)['models.publish.done'];
    assert.ok(copy?.trim(), 'the publish toast has copy');
    assert.match(copy, /clique|click/i, 'and it says the toast can be clicked');
  }
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

test('the hero says what kind of model this is, not only how it was fitted', () => {
  // The algorithm does not settle the question — a gradient boosting does both
  // tasks — and every metric below the hero is read differently depending on
  // the answer. The list page labels the task; the card used not to.
  assert.match(CARD, /\[eyebrow\]="eyebrow\(row\)"/);
  assert.match(CARD, /'models\.task\.' \+ model\.task/);
  assert.match(CARD, /'models\.algo\.' \+ model\.algo/);
  for (const key of ['models.task.classification', 'models.task.regression']) {
    assert.ok(MODELS_FR[key], `${key} has FR copy`);
    assert.ok(MODELS_EN[key], `${key} has EN copy`);
  }
});

test('a dead link to a model says so, and offers the way back', () => {
  // The fallback used to render the *list* empty state, which reads "no model
  // yet — train one". A reader who followed a stale link is not trying to
  // train anything, and there are models; this one is just not among them.
  assert.match(CARD, /models\.detail\.gone\.title/);
  assert.match(CARD, /models\.detail\.gone\.description/);
  assert.ok(
    !/models\.list\.empty\.title/.test(CARD),
    'the card does not borrow the list page empty copy',
  );
  // An empty state with nothing to click is a dead end.
  assert.match(CARD, /routerLink="\/models"[\s\S]{0,220}models\.detail\.back/);
  for (const key of ['models.detail.gone.title', 'models.detail.gone.description']) {
    assert.ok(MODELS_FR[key], `${key} has FR copy`);
    assert.ok(MODELS_EN[key], `${key} has EN copy`);
  }
});

test('the card banner is the pipeline, not the version chain', () => {
  // Versions already draw v1 → v2. The banner is the data path the card is
  // about: training table → transform → this version → scored children.
  assert.match(CARD, /data-testid="provenance-chain"/);
  assert.match(CARD, /pipelineHops\(this\.detail\(\)\?\.provenance/);
  assert.match(CLIENT, /provenance: PipelineProvenance/);
  for (const key of [
    'models.detail.provenance',
    'models.detail.provenance.dataset',
    'models.detail.provenance.transform',
    'models.detail.provenance.model',
    'models.detail.provenance.scored',
  ]) {
    assert.ok(MODELS_FR[key], `${key} has FR copy`);
    assert.ok(MODELS_EN[key], `${key} has EN copy`);
  }
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

test('the curves are chart.js, and they are hoverable, because the elbow is the argument', () => {
  // The plan names chart.js for ROC/PR, and the reason is the pointer: these are
  // the two plots an audience interrogates rather than glances at. A hand-rolled
  // path cannot answer "what does that elbow cost me in false positives", so the
  // canvas and its tooltip are the contract, not an implementation detail.
  const curve = readFileSync(
    join(process.cwd(), 'src/app/features/data/viz/curve-chart.component.ts'),
    'utf8',
  );
  assert.match(curve, /from 'ng2-charts'/);
  assert.match(curve, /baseChart/);
  assert.doesNotMatch(curve, /<svg/, 'the curve was hand-rolled again');
  assert.match(curve, /tooltip: \{/);
  // The area under a ROC *is* the metric, so the fill has to survive the move.
  assert.match(curve, /fill: this\.fill\(\) \? 'origin' : false/);
  // A canvas cannot resolve `var()`, so the tokens are read off the host and
  // re-read when the theme flips — otherwise a dark chart survives into light.
  assert.match(curve, /getComputedStyle/);
  assert.match(curve, /this\.theme\.resolved\(\)/);
  // Every curve says what its axes are, which is the other thing the SVG never
  // had room for.
  for (const key of [
    'models.evidence.roc.x',
    'models.evidence.roc.y',
    'models.evidence.roc.point',
    'models.evidence.pr.x',
    'models.evidence.pr.y',
    'models.evidence.pr.point',
    'models.evidence.fit.x',
    'models.evidence.fit.y',
    'models.evidence.fit.point',
  ]) {
    assert.ok(MODELS_FR[key], `${key} has FR copy`);
    assert.ok(MODELS_EN[key], `${key} has EN copy`);
    assert.match(CARD, new RegExp(key.replace(/\./g, '\\.')));
  }
});

test('the comparison tab weighs a pair, and never one version against itself', () => {
  // The tab, the verdict sentence, and the re-score button must all speak about
  // the same two versions, or the table says one thing and the sentence above
  // it another.
  assert.match(CARD, /comparisonPair\(this\.model\(\), this\.versions\(\)\)/);
  assert.match(CARD, /comparisonRows\(pair\.before, pair\.after/);
  assert.match(CARD, /this\.models\.comparison\(pair\.after\.id, pair\.before\.id\)/);
  // The delta beside a score is a claim about a retrain, so it keeps reading
  // strictly backwards even where the table looks forwards.
  assert.match(CARD, /previousVersion\(this\.model\(\), this\.versions\(\)\)/);
});

test('a fit reads as a check-list wherever it is watched, and says when it lands', () => {
  // "Zéro spinner muet" is a plan-level bet, and a fit is the longest wait in
  // the story — longer still with folds, which refit the pipeline once each. So
  // every surface that can be open while a fit runs draws the same list from the
  // same function, rather than one of them showing a single word.
  for (const [name, text] of [
    ['card', CARD],
    ['list', LIST],
  ] as const) {
    assert.match(text, /data-testid="train-checklist"/, name);
    assert.match(text, /trainChecklist\(/, name);
    assert.match(text, /i18n\.t\(step\.key, step\.params\)/, name);
    assert.match(text, /\[attr\.data-state\]="step\.state"/, name);
    // Done, running, not yet: three states, or the list is a paragraph.
    assert.match(text, /step\.state === 'done'/, name);
    assert.match(text, /step\.state === 'active'/, name);
  }

  // A fit settles while the reader is looking somewhere else — the studio said
  // "queued" and closed. Without a toast the row merely stops pulsing, which is
  // the silence the check-list exists to remove.
  assert.match(LIST, /private announceSettled\(\)/);
  assert.match(LIST, /this\.toast\.success\(/);
  assert.match(LIST, /this\.toast\.error\(this\.i18n\.t\('models\.progress\.failed'/);
  // And the number is the point: "v4 ready — AUC 0.87", not "training finished".
  assert.match(LIST, /'models\.progress\.settled'/);
  assert.match(LIST, /'models\.progress\.settled\.plain'/);
  for (const key of [
    'models.progress.settled',
    'models.progress.settled.plain',
    'models.progress.failed',
    'models.progress.step.fitting.counted',
    'models.progress.step.validating.counted',
  ]) {
    assert.ok(MODELS_FR[key], `${key} has FR copy`);
    assert.ok(MODELS_EN[key], `${key} has EN copy`);
  }
});
