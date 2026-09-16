import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import {
  CERTIFIED_RENDERER_VERSION,
  CHART_MAX_POINTS,
  chartKind,
  chartPalette,
  chartRamp,
  chartSeries,
  extractCitations,
  fieldsFromSchema,
  formSchemaSupported,
  isReadyFileReference,
  localizeDocument,
  mapRunStatus,
  parseDocument,
  renderableComponents,
  resolveCatalogType,
  runtimeAfterSuccess,
  runtimeDataBinding,
  runtimeItems,
  runtimeResultRows,
  runtimeSummary,
  selectRuntimeData,
  validateValues,
  valuesToPayload,
} from './model';
import {
  NODE_SPANS,
  PAGE_COLUMNS,
  a11yOf,
  a11yPayload,
  appearanceOf,
  needsEmptyText,
  onAccentColor,
  pageAppearance,
  spanColumns,
  spanOf,
  supportsSpan,
} from './style';

const RUNTIME_CSS = readFileSync('src/app/features/experience/runtime/runtime.scss', 'utf8');
const FROZEN_CSS = readFileSync('src/app/features/experience/runtime/v0_1/runtime.scss', 'utf8');

const SCHEMA = {
  type: 'object',
  required: ['amount', 'category'],
  properties: {
    amount: { type: 'number', title: 'Amount' },
    category: { type: 'string', enum: ['travel', 'meals'] },
    when: { type: 'string', format: 'date' },
    urgent: { type: 'boolean' },
    receipt: { type: 'string', format: 'binary', title: 'Receipt' },
    note: { type: 'string' },
  },
};

test('fieldsFromSchema maps string/number/enum/date/boolean/file', () => {
  const fields = fieldsFromSchema(SCHEMA);
  assert.deepEqual(
    fields.map((field) => [field.name, field.kind, field.required, field.label]),
    [
      ['amount', 'number', true, 'Amount'],
      ['category', 'enum', true, 'Category'],
      ['when', 'date', false, 'When'],
      ['urgent', 'boolean', false, 'Urgent'],
      ['receipt', 'file', false, 'Receipt'],
      ['note', 'string', false, 'Note'],
    ],
  );
  assert.deepEqual(fields.find((field) => field.name === 'category')?.options, ['travel', 'meals']);
  assert.deepEqual(fields.find((field) => field.name === 'category')?.optionLabels, ['travel', 'meals']);
});

test('form presentation localizes copy without changing schema values', () => {
  const raw = {
    i18n: {
      fr: {
        'expense.amount.label': 'Montant',
        'expense.amount.description': 'TTC',
        'expense.category.travel': 'Déplacement',
      },
    },
    pages: [{
      id: 'home',
      title: 'Expense',
      components: [{
        type: 'form',
        id: 'expense',
        props: {
          schema: SCHEMA,
          fieldPresentation: {
            amount: {
              label: { $i18n: 'expense.amount.label', fallback: 'Amount' },
              description: { $i18n: 'expense.amount.description', fallback: 'Including tax' },
            },
            category: {
              options: {
                travel: { $i18n: 'expense.category.travel', fallback: 'Travel' },
              },
            },
          },
        },
      }],
    }],
  };
  const localized = localizeDocument(raw, 'fr-FR');
  const node = localized.pages[0]?.components[0];
  const fields = fieldsFromSchema(node?.props?.['schema'], node?.props?.['fieldPresentation']);

  assert.equal(fields.find((field) => field.name === 'amount')?.label, 'Montant');
  assert.equal(fields.find((field) => field.name === 'amount')?.description, 'TTC');
  assert.deepEqual(fields.find((field) => field.name === 'category')?.options, ['travel', 'meals']);
  assert.deepEqual(fields.find((field) => field.name === 'category')?.optionLabels, ['Déplacement', 'meals']);
  assert.deepEqual(node?.props?.['schema'], SCHEMA);
});

test('certified no-code forms reject schema shapes the renderer cannot enforce', () => {
  assert.equal(formSchemaSupported(SCHEMA), true);
  assert.equal(formSchemaSupported({
    type: 'object',
    properties: { filters: { type: 'object' } },
  }), false);
  assert.equal(formSchemaSupported({
    type: 'object',
    properties: { query: { type: 'string', pattern: '^REQ-' } },
  }), false);
  assert.equal(formSchemaSupported({
    type: 'object',
    properties: { when: { type: 'string', format: 'date-time' } },
  }), false);
  assert.equal(formSchemaSupported({
    type: 'object',
    properties: { attachment: { type: 'boolean', 'x-file': true } },
  }), false);
  assert.equal(formSchemaSupported({
    type: 'object',
    properties: { priority: { type: 'integer', enum: [1.5] } },
  }), false);
  assert.equal(formSchemaSupported({
    type: 'object',
    properties: {
      attachment: { type: 'string', format: 'date', 'x-file': true, contentMediaType: 'application/pdf' },
    },
  }), false);
  assert.equal(formSchemaSupported({
    type: 'object',
    properties: { code: { type: 'string' } },
    const: { code: 'A' },
  }), false);
  assert.equal(formSchemaSupported({
    type: 'object',
    properties: { code: { type: 'string' } },
    dependentSchemas: { code: { required: ['other'] } },
  }), false);
  assert.equal(formSchemaSupported({
    $ref: '#/$defs/Input',
    $defs: { Input: { type: 'object', properties: { query: { type: 'string' } } } },
  }), false);
});

test('schema identifiers keep payload keys but expose deterministic business labels', () => {
  const fields = fieldsFromSchema({
    type: 'object',
    properties: {
      scenario: { type: 'string' },
      case: { type: 'string' },
      'source.request': { type: 'string' },
      employeeID: { type: 'string', title: 'Employee ID' },
    },
  });
  assert.deepEqual(fields.map(({ name, label }) => [name, label]), [
    ['scenario', 'Scenario'],
    ['case', 'Case'],
    ['source.request', 'Source request'],
    ['employeeID', 'Employee ID'],
  ]);
});

test('selector-free template bindings project common output shapes', () => {
  assert.deepEqual(runtimeItems({ requests: [{ id: 1 }] }), [{ id: 1 }]);
  assert.deepEqual(runtimeItems({ id: 1, status: 'open' }), [{ id: 1, status: 'open' }]);
  assert.equal(runtimeSummary({ items: [{}, {}] }), 2);
  assert.equal(runtimeSummary({ total: 7 }), 7);
});

test('a chart series scales its bars against the largest value it plots', () => {
  assert.deepEqual(
    chartSeries([
      { label: 'critical', value: 9 },
      { label: 'high', value: 24 },
      { label: 'medium', value: 61 },
    ]),
    {
      // Width ranks a bar against the biggest one; share answers the other
      // question a band chart is asked, which is how much of the base it is.
      points: [
        { label: 'critical', value: 9, width: 15, share: 9.574468085106384 },
        { label: 'high', value: 24, width: 39, share: 25.53191489361702 },
        { label: 'medium', value: 61, width: 100, share: 64.8936170212766 },
      ],
      hidden: 0,
    },
  );

  // A run output names its own columns; the defaults only apply when it doesn't.
  assert.deepEqual(
    chartSeries([{ band: 'churn risk', subscribers: '1240' }], 'band', 'subscribers').points,
    [{ label: 'churn risk', value: 1240, width: 100, share: 100 }],
  );
});

test('a share is only offered for a series that is a whole to take a share of', () => {
  // A permutation score that hurt the fit is a negative contribution, not a
  // negative slice of a pie: "-12% of the total" is not a sentence.
  assert.deepEqual(
    chartSeries([
      { label: 'tenure', value: 8 },
      { label: 'region', value: -3 },
    ]).points.map((point) => point.share),
    [null, null],
  );

  // Nor is anything a share of zero.
  assert.deepEqual(
    chartSeries([{ label: 'none', value: 0 }]).points.map((point) => point.share),
    [null],
  );

  // Once the cap has hidden rows the shares are of what is drawn, so they add
  // up to what the reader can actually see and count.
  const capped = chartSeries(
    Array.from({ length: CHART_MAX_POINTS + 1 }, (_, index) => ({
      label: `band-${index}`,
      value: index + 1,
    })),
  );
  assert.equal(capped.hidden, 1);
  const total = capped.points.reduce((sum, point) => sum + (point.share ?? 0), 0);
  assert.ok(Math.abs(total - 100) < 1e-9, `shares sum to ${total}`);
});

test('a ramp spans its anchors however many bars the run came back with', () => {
  // The signals the severity palette is actually built from, dark theme.
  const signals = ['#34d399', '#f5b84a', '#ef5a6f'];

  // As many bands as anchors returns the anchors: the interpolation adds
  // nothing and must therefore change nothing.
  assert.deepEqual(chartRamp(signals, 3), signals);

  // The ends mean the same thing at every length, which is what lets a reader
  // compare this morning's four bands with last week's six.
  for (const count of [2, 4, 5, 9]) {
    const ramp = chartRamp(signals, count);
    assert.equal(ramp.length, count);
    assert.equal(ramp[0], signals[0]);
    assert.equal(ramp.at(-1), signals.at(-1));
  }

  assert.deepEqual(chartRamp(signals, 1), [signals[0]]);
  assert.deepEqual(chartRamp(signals, 0), []);

  // Short hex is a colour too, and a token can resolve to one.
  assert.deepEqual(chartRamp(['#000', '#fff'], 2), ['#000000', '#ffffff']);

  // A token that resolved to something this cannot parse is handed back rather
  // than turned into `#NaNNaNNaN`: the wrong colour still draws a chart.
  assert.deepEqual(chartRamp(['rgb(1 2 3)', '#ffffff'], 2), ['rgb(1 2 3)', '#ffffff']);
  assert.deepEqual(chartRamp([], 2), ['', '']);
});

test('a ramp between two hues stays a colour instead of passing through grey', () => {
  // The whole reason the interpolation is not done on the channels. Averaging
  // this green and this amber gives #b5c164, a dead olive that reads as a
  // rendering fault sitting between two saturated bars.
  const [, midpoint] = chartRamp(['#34d399', '#f5b84a'], 3);
  const [red, green, blue] = [1, 3, 5].map((at) => Number.parseInt(midpoint!.slice(at, at + 2), 16));

  // Chroma survives the trip: the least channel is far below the greatest,
  // which is exactly what a washed-out midpoint loses.
  assert.ok(
    Math.max(red!, green!, blue!) - Math.min(red!, green!, blue!) > 110,
    `${midpoint} is washed out`,
  );
  // And it lands on the yellow anyone would expect between green and amber,
  // rather than on the olive the shorter path through the cube produces.
  assert.ok(blue! < red! && blue! < green!, `${midpoint} is not a yellow`);

  // Grey has no hue to walk, so a ramp through it is a lightness ramp and must
  // not pick up a colour cast from an arbitrary angle.
  for (const shade of chartRamp(['#000000', '#ffffff'], 5)) {
    const [r, g, b] = [1, 3, 5].map((at) => Number.parseInt(shade.slice(at, at + 2), 16));
    assert.ok(Math.max(r!, g!, b!) - Math.min(r!, g!, b!) <= 1, `${shade} is not grey`);
  }
});

test('a palette is opt-in, because a ramp claims an order the data may not have', () => {
  assert.equal(chartPalette('severity'), 'severity');
  assert.equal(chartPalette('accent'), 'accent');
  // Anything unrecognised falls to the palette that ranks nothing.
  assert.equal(chartPalette(undefined), 'accent');
  assert.equal(chartPalette('rainbow'), 'accent');
  assert.equal(chartPalette({ palette: 'severity' }), 'accent');
});

test('a chart drops rows no bar can honestly stand for', () => {
  // A document and a run output are both untrusted here. A row with no label,
  // or whose value is not a number, is absent data — plotting it at zero would
  // claim a measurement that was never taken.
  assert.deepEqual(
    chartSeries([
      { label: 'kept', value: 3 },
      { label: '', value: 8 },
      { label: 'no number', value: 'many' },
      { label: 'boolean', value: true },
      { label: 'missing' },
      'not a row',
      null,
    ]).points,
    [{ label: 'kept', value: 3, width: 100, share: 100 }],
  );

  for (const value of [undefined, null, 'rows', 42, {}, [], [{}]]) {
    assert.deepEqual(chartSeries(value).points, [], `${JSON.stringify(value ?? null)} plots nothing`);
  }

  // A label long enough to break a canvas legend is cut, not refused.
  const long = chartSeries([{ label: 'x'.repeat(400), value: 1 }]).points[0];
  assert.equal(long?.label.length, 32);
  assert.ok(long?.label.endsWith('…'));
});

test('over the cap a chart keeps the largest values in the order they arrived', () => {
  const many = Array.from({ length: CHART_MAX_POINTS + 4 }, (_, index) => ({
    label: `band-${index}`,
    value: index,
  }));
  const series = chartSeries(many);

  assert.equal(series.points.length, CHART_MAX_POINTS);
  assert.equal(series.hidden, 4);
  // Ranking decides what is worth the space; the authored order decides where
  // it goes, because "critical, high, medium, low" is not sorted by count.
  assert.deepEqual(
    series.points.map((point) => point.label),
    many.slice(4).map((point) => point.label),
  );
});

test('an unrecognised chart kind draws bars rather than nothing', () => {
  assert.equal(chartKind('bar'), 'bar');
  assert.equal(chartKind('donut'), 'donut');
  assert.equal(chartKind('sunburst'), 'bar');
  assert.equal(chartKind(undefined), 'bar');
  assert.equal(chartKind({ kind: 'donut' }), 'bar');
});

test('business results are bounded, nested and humanised without JSON fallback', () => {
  assert.deepEqual(runtimeResultRows({
    case_id: 'INC-42',
    approved: true,
    owner: { employeeName: 'Léa' },
    steps: [{ status_code: 'ready' }, 'done'],
  }), [
    { path: ['Case id'], value: 'INC-42' },
    { path: ['Approved'], value: true },
    { path: ['Owner', 'Employee Name'], value: 'Léa' },
    { path: ['Steps', 1, 'Status code'], value: 'ready' },
    { path: ['Steps', 2], value: 'done' },
  ]);
  assert.deepEqual(runtimeResultRows({ deep: { value: 1 } }, 1), [
    { path: ['Deep'], value: '…' },
  ]);
  assert.deepEqual(runtimeResultRows([1, 2, 3], 6, 2), [
    { path: [1], value: 1 },
    { path: [2], value: 2 },
    { path: ['…'], value: '…' },
  ]);
});

test('BRD text length constraints are enforced without truncation or UTF-16 counting', () => {
  const schema = { type: 'object', properties: { query: { type: 'string', minLength: 2, maxLength: 3 } } };
  assert.equal(formSchemaSupported(schema), true);
  const fields = fieldsFromSchema(schema);
  assert.equal(fields[0]?.minLength, 2);
  assert.equal(fields[0]?.maxLength, 3);
  for (const query of ['', 'a', 'abcd', '😀', 42]) {
    assert.deepEqual(validateValues(fields, { query }), { query: 'invalid' });
  }
  for (const query of ['ab', 'abc', '😀😀', '😀😀😀']) {
    assert.deepEqual(validateValues(fields, { query }), {});
    assert.deepEqual(valuesToPayload(fields, { query }), { query });
  }
  assert.deepEqual(validateValues(fields, {}), {});
  assert.deepEqual(validateValues(fieldsFromSchema({ ...schema, required: ['query'] }), {}), { query: 'required' });
  const noMinimum = fieldsFromSchema({ type: 'object', properties: { query: { type: 'string', maxLength: 0 } } });
  assert.deepEqual(validateValues(noMinimum, { query: '' }), {});
  assert.deepEqual(validateValues(noMinimum, { query: 'a' }), { query: 'invalid' });
  const requiredEmpty = fieldsFromSchema({
    type: 'object', required: ['query'], properties: { query: { type: 'string', maxLength: 0 } },
  });
  assert.deepEqual(validateValues(requiredEmpty, { query: '' }), {});
  assert.deepEqual(valuesToPayload(requiredEmpty, { query: '' }), { query: '' });
  assert.deepEqual(validateValues(requiredEmpty, {}), { query: 'required' });
  for (const spec of [
    { type: 'string', enum: ['AA', 'BB'], minLength: 2 },
    { type: 'string', format: 'date', minLength: 10 },
  ]) {
    const optional = fieldsFromSchema({ type: 'object', properties: { query: spec } });
    assert.deepEqual(validateValues(optional, { query: '' }), {});
    assert.deepEqual(valuesToPayload(optional, { query: '' }), {});
  }
  for (const field of [
    { type: 'string', minLength: -1 }, { type: 'string', maxLength: 1.5 },
    { type: 'string', minLength: true }, { type: 'string', maxLength: null },
    { type: 'string', minLength: 4, maxLength: 2 }, { type: 'number', minLength: 1 },
    { type: 'string', format: 'binary', minLength: 1 },
    { type: 'string', 'x-file': true, maxLength: 12 },
    { type: 'string', maxLength: Number.MAX_SAFE_INTEGER + 1 },
  ]) assert.equal(formSchemaSupported({ type: 'object', properties: { query: field } }), false);
});

test('validateValues flags required and invalid numbers, accepts a filled form', () => {
  const fields = fieldsFromSchema(SCHEMA);
  assert.deepEqual(validateValues(fields, {}), { amount: 'required', category: 'required' });
  assert.equal(validateValues(fields, { amount: 'x', category: 'travel' }).amount, 'invalid');
  assert.deepEqual(validateValues(fields, { amount: 12, category: 'travel', when: '2026-08-13' }), {});
  assert.deepEqual(valuesToPayload(fields, { amount: '12.5', category: 'travel', urgent: true }), {
    amount: 12.5,
    category: 'travel',
    urgent: true,
  });
  assert.deepEqual(
    valuesToPayload(fields, {
      receipt: { kind: 'document', document_id: 'doc-42', filename: 'receipt.pdf' },
    }),
    { receipt: 'doc-42' },
  );

  const numericEnum = fieldsFromSchema({
    type: 'object',
    properties: { priority: { type: 'integer', enum: [1, 2, 3] } },
  });
  assert.deepEqual(valuesToPayload(numericEnum, { priority: '2' }), { priority: 2 });
});

test('the authoring catalog creates releases against renderer 0.2', () => {
  assert.equal(CERTIFIED_RENDERER_VERSION, 'certified-components-0.2.0');
});

test('document copy resolves explicit i18n refs with a controlled fallback', () => {
  const raw = {
    i18n: {
      fr: { 'orders.title': 'Commandes', 'orders.hero': 'À traiter', 'orders.empty': 'Aucune commande' },
      en: { 'orders.title': 'Orders' },
    },
    pages: [{
      id: 'home',
      title: { $i18n: 'orders.title', fallback: 'Orders' },
      components: [{
        type: 'header',
        id: 'hero',
        props: {
          title: { $i18n: 'orders.hero', fallback: 'Pending' },
          a11y: { emptyText: { $i18n: 'orders.empty', fallback: 'No orders' } },
        },
      }],
    }],
  };
  assert.equal(localizeDocument(raw, 'fr-FR').pages[0]?.title, 'Commandes');
  assert.equal(localizeDocument(raw, 'fr-FR').pages[0]?.components[0]?.props?.['title'], 'À traiter');
  assert.equal(
    a11yOf(localizeDocument(raw, 'fr-FR').pages[0]!.components[0]!).emptyText,
    'Aucune commande',
  );
  assert.equal(localizeDocument(raw, 'en').pages[0]?.components[0]?.props?.['title'], 'Pending');
  assert.deepEqual(parseDocument(raw).pages[0]?.title, { $i18n: 'orders.title', fallback: 'Orders' });
});

test('data/query bindings are closed and selectors cannot traverse prototypes', () => {
  assert.deepEqual(
    runtimeDataBinding({
      type: 'table',
      props: { dataBinding: { source: 'run-output', componentId: 'load', selector: 'rows.0' } },
    }),
    { source: 'run-output', componentId: 'load', bindingKey: undefined, selector: 'rows.0', input: {} },
  );
  assert.equal(
    runtimeDataBinding({
      type: 'table',
      props: { dataBinding: { source: 'url', componentId: 'load', selector: 'rows' } },
    }),
    null,
  );
  assert.equal(
    runtimeDataBinding({
      type: 'table',
      props: { queryBinding: { source: 'system-binding', bindingKey: 'orders.list', selector: 'rows' } },
    })?.bindingKey,
    'orders.list',
  );
  assert.deepEqual(selectRuntimeData({ rows: [{ id: 7 }] }, 'rows.0'), { id: 7 });
  assert.equal(selectRuntimeData({}, '__proto__.polluted'), undefined);
});

test('only an uploaded document id is a ready file reference', () => {
  assert.equal(isReadyFileReference({ kind: 'document', document_id: null, filename: 'a.pdf', job_id: 'j1' }), false);
  assert.equal(isReadyFileReference({ kind: 'document', document_id: 'doc-1', filename: 'a.pdf' }), true);
});

test('after-success behavior is a closed catalog with safe page ids', () => {
  assert.deepEqual(runtimeAfterSuccess('result'), { kind: 'result' });
  assert.deepEqual(runtimeAfterSuccess('reset'), { kind: 'reset' });
  assert.deepEqual(runtimeAfterSuccess('page:review_2'), { kind: 'page', pageId: 'review_2' });
  assert.deepEqual(runtimeAfterSuccess('page:'), { kind: 'stay' });
  assert.deepEqual(runtimeAfterSuccess('page:../admin'), { kind: 'stay' });
  assert.deepEqual(runtimeAfterSuccess('https://evil.example'), { kind: 'stay' });
});

test('unknown types fall back; nested page is ignored', () => {
  assert.deepEqual(resolveCatalogType('section'), { kind: 'ok', type: 'section' });
  assert.deepEqual(resolveCatalogType('chart'), { kind: 'ok', type: 'chart' });
  assert.deepEqual(resolveCatalogType('map_panel'), { kind: 'ok', type: 'map_panel' });
  assert.deepEqual(resolveCatalogType('agenda_panel'), { kind: 'ok', type: 'agenda_panel' });
  assert.deepEqual(resolveCatalogType('intelligence_feed'), { kind: 'ok', type: 'intelligence_feed' });
  assert.deepEqual(resolveCatalogType('decision_queue'), { kind: 'ok', type: 'decision_queue' });
  assert.deepEqual(resolveCatalogType('page'), { kind: 'skip' });
  assert.deepEqual(resolveCatalogType('magic_widget'), { kind: 'fallback', type: 'magic_widget' });

  const doc = parseDocument({
    pages: [
      {
        id: 'home',
        title: 'Home',
        components: [
          { type: 'page', id: 'nested' },
          { type: 'magic_widget', props: { x: 1 } },
          { type: 'header', id: 'h1', props: { title: 'Hello' } },
        ],
      },
    ],
  });
  assert.equal(doc.pages[0]?.components.length, 3);
  assert.equal(resolveCatalogType(doc.pages[0]!.components[0]!.type).kind, 'skip');
  assert.equal(resolveCatalogType(doc.pages[0]!.components[1]!.type).kind, 'fallback');
  assert.equal(resolveCatalogType(doc.pages[0]!.components[2]!.type).kind, 'ok');
});

test('renderableComponents drops an action_button that duplicates the form submit', () => {
  const ids = (nodes: ReturnType<typeof renderableComponents>) => nodes.map((node) => node.id);

  assert.deepEqual(
    ids(renderableComponents([
      { type: 'form', id: 'f', props: { bindingKey: 'nawa.reset' } },
      { type: 'action_button', id: 'a', props: { bindingKey: 'nawa.reset' } },
    ])),
    ['f'],
  );

  // Unbound seed pair: the button cannot run anything the form does not.
  assert.deepEqual(
    ids(renderableComponents([
      { type: 'form', id: 'f' },
      { type: 'action_button', id: 'a', props: { label: 'Send' } },
    ])),
    ['f'],
  );

  // A second action on its own binding stays.
  assert.deepEqual(
    ids(renderableComponents([
      { type: 'form', id: 'f', props: { bindingKey: 'nawa.reset' } },
      { type: 'action_button', id: 'a', props: { bindingKey: 'nawa.escalate' } },
    ])),
    ['f', 'a'],
  );

  assert.deepEqual(
    ids(renderableComponents([{ type: 'action_button', id: 'a', props: { bindingKey: 'x' } }])),
    ['a'],
  );
});

test('appearance props persist on a page and a node', () => {
  const doc = parseDocument({
    pages: [
      {
        id: 'home',
        title: 'Home',
        props: { theme: 'dark', density: 'compact', description: 'Ops' },
        components: [
          {
            type: 'header',
            id: 'h1',
            props: { title: 'Inbox', description: 'Today', density: 'compact', accent: '#0ea5e9' },
          },
        ],
      },
    ],
  });
  const page = doc.pages[0]!;
  const node = page.components[0]!;
  assert.deepEqual(pageAppearance(page), { description: 'Ops', density: 'compact', theme: 'dark' });
  assert.equal(appearanceOf(node).title, 'Inbox');
  assert.equal(appearanceOf(node).description, 'Today');
  assert.equal(appearanceOf(node).density, 'compact');
  assert.equal(appearanceOf(node).accent, '#0ea5e9');
});

test('a width nobody wrote, or wrote wrong, is the whole row', () => {
  // Every document published so far declares no width, and a released one is
  // only ever checked for shape: `span: 7` and `span: 'two-thirds'` both reach
  // the renderer exactly as an author typed them. Reading either as the full
  // row leaves such a page readable, where honouring it would tile a row that
  // does not add up.
  assert.equal(spanOf(undefined), 'full');
  assert.equal(spanOf({}), 'full');
  assert.equal(spanOf({ span: 'half' }), 'half');
  assert.equal(spanOf({ span: 7 }), 'full');
  assert.equal(spanOf({ span: 'two-thirds' }), 'full');
  assert.equal(spanOf({ span: null }), 'full');
  // A membership test written with `in` answers for the prototype chain too,
  // and would let this one through as a width.
  assert.equal(spanOf({ span: 'toString' }), 'full');
  assert.equal(appearanceOf({ type: 'kpi', props: { span: 'quarter' } }).span, 'quarter');
  assert.equal(appearanceOf({ type: 'kpi' }).span, 'full');
});

test('each width divides a page row with nothing left over', () => {
  // This is the whole reason the vocabulary is named fractions instead of a
  // column count: an author cannot ask for a width that leaves a strip of the
  // row unused. Four tiles, three panels or two panels have to fill the row
  // they share.
  for (const span of NODE_SPANS) {
    assert.equal(PAGE_COLUMNS % spanColumns(span), 0);
  }
  assert.equal(spanColumns('full'), PAGE_COLUMNS);
  assert.equal(spanColumns('half') * 2, PAGE_COLUMNS);
  assert.equal(spanColumns('third') * 3, PAGE_COLUMNS);
  assert.equal(spanColumns('quarter') * 4, PAGE_COLUMNS);
});

test('a header keeps its row while the panels of a board may share one', () => {
  // The inspector decides which widths an author is ever offered, and a header
  // or a section carries the page's own name — narrowed, a board would announce
  // itself from a corner.
  assert.equal(supportsSpan('kpi'), true);
  assert.equal(supportsSpan('chart'), true);
  assert.equal(supportsSpan('table'), true);
  assert.equal(supportsSpan('header'), false);
  assert.equal(supportsSpan('section'), false);
});

test('the page grid is cut into the tracks the width projection counts', () => {
  // The track count is stated twice, in two languages: `PAGE_COLUMNS` for the
  // projection and the inspector, a `repeat()` for the browser. Nothing makes
  // them agree, so a quarter authored against twelve tracks and drawn on ten
  // would tile wrong with each half of the pair looking right on its own.
  assert.match(RUNTIME_CSS, new RegExp(`repeat\\(${PAGE_COLUMNS}, minmax\\(0, 1fr\\)\\)`));
  assert.match(
    RUNTIME_CSS,
    new RegExp(`\\.xp-rt-page > \\* \\{\\s*grid-column: span ${spanColumns('full')};`),
  );
  for (const span of NODE_SPANS.filter((value) => value !== 'full')) {
    assert.match(
      RUNTIME_CSS,
      new RegExp(`\\[data-span='${span}'\\] \\{\\s*grid-column: span ${spanColumns(span)};`),
    );
  }
  // A third of a page is unreadable on a phone, so the narrow viewport takes
  // every width back to the row it would have had anyway.
  assert.match(RUNTIME_CSS, /@media \(max-width: 900px\)/);
});

test('the renderer a pinned release draws through never learned about columns', () => {
  // `runtime/v0_1/` is the catalog `certified-components-0.1.0` was signed off
  // against, and it carries its own stylesheet for exactly this reason: a
  // layout decision taken for the current catalog must not reach a release
  // whose pixels somebody already approved.
  assert.match(FROZEN_CSS, /\.xp-rt-page \{\s*display: flex;/);
  assert.doesNotMatch(FROZEN_CSS, /data-span/);
});

test('custom accents always choose the higher-contrast text colour', () => {
  assert.equal(onAccentColor('#7dd3fc'), '#05070a');
  assert.equal(onAccentColor('#0e7490'), '#ffffff');
  assert.equal(onAccentColor('invalid'), '#05070a');
});

test('a11y aria on a button and a form', () => {
  const button = {
    type: 'action_button',
    id: 'go',
    props: { label: 'Send', a11y: { ariaLabel: 'Submit expense' } },
  };
  const form = {
    type: 'form',
    id: 'f1',
    props: { ariaLabel: 'legacy', a11y: { ariaLabel: 'Expense form', emptyText: 'No fields', headingLevel: 2 } },
  };
  assert.equal(a11yOf(button).ariaLabel, 'Submit expense');
  assert.equal(a11yOf(form).ariaLabel, 'Expense form');
  assert.equal(a11yOf(form).emptyText, 'No fields');
  assert.equal(a11yOf(form).headingLevel, 2);
  assert.equal(a11yOf({ type: 'action_button', props: { ariaLabel: 'Go' } }).ariaLabel, 'Go');
  const localized = { $i18n: 'form.empty', fallback: 'No fields' };
  assert.deepEqual(
    a11yPayload({ type: 'form', props: { a11y: { emptyText: localized } } }, 'keyboardHint', 'Use Tab'),
    { emptyText: localized, keyboardHint: 'Use Tab' },
  );
});

test('a block that draws nothing on a bad morning is offered the words to say so', () => {
  // The inspector decides which fields an author ever sees, so a block whose
  // runtime reads `emptyText` while this set omits it can only be given one by
  // hand-editing the document. A chart is emptier more often than most: it has
  // a series the author wrote and a binding that may replace it with a shape no
  // bar can stand for.
  assert.equal(needsEmptyText('chart'), true);
  assert.equal(needsEmptyText('header'), false);
});

test('mapRunStatus uses business vocabulary; citations read output_ref', () => {
  assert.equal(mapRunStatus('running'), 'running');
  assert.equal(mapRunStatus('hitl_pending'), 'pending_validation');
  assert.equal(mapRunStatus('completed'), 'completed');
  assert.equal(mapRunStatus('cancelled'), 'retry');
  assert.equal(mapRunStatus('failed'), 'error');
  assert.deepEqual(
    extractCitations({
      output_ref: { citations: [{ title: 'Policy', source: 'kb://p' }, 'bare'] },
    }),
    [
      { title: 'Policy', source: 'kb://p', snippet: undefined },
      { title: 'bare' },
    ],
  );
});
