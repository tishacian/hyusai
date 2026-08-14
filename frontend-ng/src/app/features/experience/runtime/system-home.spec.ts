import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  compileSystemHome,
  firstManualIngress,
  hasHitlHint,
  uniqueBindingKey,
  uniqueSlug,
} from './system-home';

const LABELS = {
  subtitle: 'Fill in the details, then send.',
  submit: 'Submit',
  missingEntry: 'No manual entry is offered right now.',
  approvalTitle: 'Approval',
  approvalBody: 'A person must approve before this continues.',
};

const CONTRACT = {
  ingresses: [
    {
      ingress_id: 'chat.in',
      source_node_id: 'chat.in',
      kind: 'chat',
      input_schema: { type: 'object', properties: { message: { type: 'string' } } },
    },
    {
      ingress_id: 'start',
      source_node_id: 'start',
      kind: 'manual',
      input_schema: {
        type: 'object',
        required: ['query'],
        properties: { query: { type: 'string', title: 'Request' } },
      },
    },
  ],
};

test('firstManualIngress skips non-manual entries', () => {
  const ingress = firstManualIngress(CONTRACT);
  assert.equal(ingress?.ingress_id, 'start');
  assert.equal(firstManualIngress({ ingresses: [] }), null);
  assert.equal(firstManualIngress(null), null);
});

test('hasHitlHint reads graph kinds and ingress ids', () => {
  assert.equal(hasHitlHint(CONTRACT), false);
  assert.equal(hasHitlHint(CONTRACT, ['task', 'hitl']), true);
  assert.equal(
    hasHitlHint({
      ingresses: [{ ingress_id: 'gate.hitl', source_node_id: 'gate.hitl', kind: 'manual' }],
    }),
    true,
  );
});

test('compileSystemHome builds form_result from the manual contract', () => {
  const doc = compileSystemHome({
    systemName: 'Password reset',
    bindingKey: 'home.password-reset.start.x',
    ingress: firstManualIngress(CONTRACT),
    hasHitl: false,
    labels: LABELS,
  });
  assert.equal(doc.pages.length, 1);
  assert.equal(doc.pages[0]?.id, 'form_result');
  assert.equal(doc.pages[0]?.title, 'Password reset');
  assert.deepEqual(
    doc.pages[0]?.components.map((node) => node.type),
    ['header', 'form', 'runtime_status', 'result', 'evidence', 'history'],
  );
  const form = doc.pages[0]?.components.find((node) => node.type === 'form');
  assert.equal(form?.props?.['bindingKey'], 'home.password-reset.start.x');
  assert.equal(form?.props?.['submitLabel'], 'Submit');
  assert.deepEqual(form?.props?.['schema'], CONTRACT.ingresses[1]?.input_schema);
  assert.equal(/flow|run|skill/i.test(doc.pages[0]?.title ?? ''), false);
});

test('compileSystemHome adds approval_card when a hitl hint is present', () => {
  const withHitl = compileSystemHome({
    systemName: 'Expenses',
    bindingKey: 'home.expenses.start.x',
    ingress: firstManualIngress(CONTRACT),
    hasHitl: true,
    labels: LABELS,
  });
  assert.ok(withHitl.pages[0]?.components.some((node) => node.type === 'approval_card'));

  const noIngress = compileSystemHome({
    systemName: 'Watch',
    bindingKey: 'home.watch.submit.x',
    ingress: null,
    hasHitl: false,
    labels: LABELS,
  });
  assert.deepEqual(
    noIngress.pages[0]?.components.map((node) => node.type),
    ['header', 'callout', 'runtime_status', 'result', 'evidence', 'history'],
  );
});

test('unique identifiers stay within the backend regexes', () => {
  assert.match(uniqueSlug('Password Reset', 'm9k2'), /^[a-z][a-z0-9-]{0,119}$/);
  assert.match(uniqueSlug('2024 Q1', 'aa'), /^[a-z][a-z0-9-]{0,119}$/);
  assert.match(
    uniqueBindingKey('Password Reset', 'start', 'm9k2'),
    /^[a-z][a-z0-9._-]{0,119}$/,
  );
});
