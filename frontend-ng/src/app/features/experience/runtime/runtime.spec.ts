import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  CERTIFIED_RENDERER_VERSION,
  extractCitations,
  fieldsFromSchema,
  isReadyFileReference,
  localizeDocument,
  mapRunStatus,
  parseDocument,
  renderableComponents,
  rendererPinMatches,
  resolveCatalogType,
  runtimeAfterSuccess,
  runtimeDataBinding,
  selectRuntimeData,
  validateValues,
  valuesToPayload,
} from './model';
import { a11yOf, appearanceOf, pageAppearance } from './style';

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
      ['category', 'enum', true, 'category'],
      ['when', 'date', false, 'when'],
      ['urgent', 'boolean', false, 'urgent'],
      ['receipt', 'file', false, 'Receipt'],
      ['note', 'string', false, 'note'],
    ],
  );
  assert.deepEqual(fields.find((field) => field.name === 'category')?.options, ['travel', 'meals']);
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
});

test('renderer pin matches the catalog constant and refuses a foreign pin', () => {
  assert.equal(rendererPinMatches(undefined), false);
  assert.equal(rendererPinMatches(null), false);
  assert.equal(rendererPinMatches(''), false);
  assert.equal(rendererPinMatches(CERTIFIED_RENDERER_VERSION), true);
  assert.equal(rendererPinMatches('certified-components-9.9.9'), false);
});

test('document copy resolves explicit i18n refs with a controlled fallback', () => {
  const raw = {
    i18n: {
      fr: { 'orders.title': 'Commandes', 'orders.hero': 'À traiter' },
      en: { 'orders.title': 'Orders' },
    },
    pages: [{
      id: 'home',
      title: { $i18n: 'orders.title', fallback: 'Orders' },
      components: [{
        type: 'header',
        id: 'hero',
        props: { title: { $i18n: 'orders.hero', fallback: 'Pending' } },
      }],
    }],
  };
  assert.equal(localizeDocument(raw, 'fr-FR').pages[0]?.title, 'Commandes');
  assert.equal(localizeDocument(raw, 'fr-FR').pages[0]?.components[0]?.props?.['title'], 'À traiter');
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
