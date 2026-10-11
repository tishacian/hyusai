/**
 * The bargain the schema builder makes: JSON stops being mandatory without
 * ceasing to be available. These tests hold both halves of it — the round trip
 * through the field rows loses nothing, and a schema the rows cannot express
 * is reported rather than flattened.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  applyFields,
  blankField,
  emptyObjectSchema,
  objectToValues,
  projectSchema,
  valueFieldsFromSchema,
  valuesToObject,
} from './schema-builder.vm';

const CONTRACT = {
  $schema: 'https://json-schema.org/draft/2020-12/schema',
  title: 'Reset a ticket',
  type: 'object',
  additionalProperties: false,
  required: ['ticket_id'],
  properties: {
    ticket_id: { type: 'string', description: 'The ticket to reset.' },
    reason: { type: 'string', enum: ['duplicate', 'spam'], default: 'duplicate' },
    retries: { type: 'integer', default: 3 },
    tags: { type: 'array', items: { type: 'string' } },
    author: {
      type: 'object',
      required: ['email'],
      properties: { email: { type: 'string' }, internal: { type: 'boolean' } },
    },
  },
};

test('a contract the rows can hold projects with nothing left over', () => {
  const { fields, unsupported } = projectSchema(CONTRACT);

  assert.deepEqual(unsupported, []);
  assert.deepEqual(
    fields.map((field) => [field.name, field.type, field.required]),
    [
      ['ticket_id', 'string', true],
      ['reason', 'string', false],
      ['retries', 'integer', false],
      ['tags', 'array', false],
      ['author', 'object', false],
    ],
  );
  assert.deepEqual(fields[1].enumValues, ['duplicate', 'spam']);
  assert.equal(fields[2].defaultValue, '3');
  assert.equal(fields[3].itemType, 'string');
  assert.deepEqual(
    fields[4].children.map((child) => [child.name, child.type, child.required]),
    [['email', 'string', true], ['internal', 'boolean', false]],
  );
});

test('writing the rows back preserves the keys the rows never knew about', () => {
  const { fields } = projectSchema(CONTRACT);

  const rewritten = applyFields(CONTRACT, fields);

  assert.equal(rewritten['$schema'], CONTRACT.$schema);
  assert.equal(rewritten['title'], 'Reset a ticket');
  assert.equal(rewritten['additionalProperties'], false);
  // And the round trip is stable: a visual edit committed twice says the same.
  assert.deepEqual(rewritten, applyFields(rewritten, projectSchema(rewritten).fields));
  assert.deepEqual(projectSchema(rewritten).fields, fields);
});

test('an exact array count writes and reads both JSON Schema bounds', () => {
  const { fields } = projectSchema({
    type: 'object',
    properties: {
      items: { type: 'array', items: { type: 'string' }, minItems: 3, maxItems: 3 },
    },
  });

  assert.equal(fields[0].exactCount, 3);
  assert.deepEqual(applyFields({}, fields).properties, {
    items: { type: 'array', items: { type: 'string' }, minItems: 3, maxItems: 3 },
  });
});

test('an edit through the rows changes only what it touched', () => {
  const { fields } = projectSchema(CONTRACT);
  const renamed = fields.map((field) =>
    field.name === 'reason' ? { ...field, required: true, description: 'Why.' } : field,
  );

  const rewritten = applyFields(CONTRACT, renamed);

  assert.deepEqual(rewritten['required'], ['ticket_id', 'reason']);
  const properties = rewritten['properties'] as Record<string, Record<string, unknown>>;
  assert.equal(properties['reason']['description'], 'Why.');
  assert.deepEqual(properties['ticket_id'], CONTRACT.properties.ticket_id);
});

test('a construct no row can hold is named, not flattened', () => {
  const withRef = {
    type: 'object',
    $defs: { money: { type: 'number' } },
    properties: {
      total: { $ref: '#/$defs/money' },
      either: { oneOf: [{ type: 'string' }] },
      deep: { type: 'object', properties: { a: { type: 'object', properties: { b: {} } } } },
      rows: { type: 'array', items: { type: 'object' } },
    },
  };

  const { unsupported } = projectSchema(withRef);

  assert.equal(unsupported.length, 5);
  assert.ok(unsupported.some((reason) => reason.includes('$defs')));
  assert.ok(unsupported.some((reason) => reason.includes('$ref')));
  assert.ok(unsupported.some((reason) => reason.includes('oneOf')));
  assert.ok(unsupported.some((reason) => reason.includes('third level')));
  assert.ok(unsupported.some((reason) => reason.includes('rows')));
});

test('an empty contract is a clean slate, not a complaint', () => {
  assert.deepEqual(projectSchema({}), { fields: [], unsupported: [] });
  assert.deepEqual(projectSchema(emptyObjectSchema()).unsupported, []);
  assert.deepEqual(applyFields({}, []), { type: 'object', properties: {} });
  assert.deepEqual(projectSchema([]).unsupported.length, 1);
});

test('a row with no name is dropped rather than writing an empty key', () => {
  const rewritten = applyFields({}, [blankField(''), blankField('ok')]);

  assert.deepEqual(Object.keys(rewritten['properties'] as object), ['ok']);
});

test('preset inputs are derived from the target contract and typed on the way in', () => {
  const fields = valueFieldsFromSchema(CONTRACT);

  assert.deepEqual(
    fields.map((field) => [field.name, field.type, field.required]),
    [
      ['ticket_id', 'string', true],
      ['reason', 'string', false],
      ['retries', 'integer', false],
      ['tags', 'array', false],
      ['author', 'object', false],
    ],
  );
  assert.deepEqual(fields[1].options, ['duplicate', 'spam']);

  assert.deepEqual(
    valuesToObject(fields, { ticket_id: 'T-1', retries: '5', reason: '  ' }),
    { ticket_id: 'T-1', retries: 5 },
    'a blank entry is an absent key, not an empty string',
  );
  assert.deepEqual(objectToValues({ retries: 5, ticket_id: 'T-1' }), {
    retries: '5',
    ticket_id: 'T-1',
  });
});
