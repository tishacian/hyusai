import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { shownSpecFields, specColumns, specValues, tabularFields, tabularSpec } from './tabular-options.vm';
import type { ModelCatalog, PlanColumn, SpecFieldDescriptor } from './models.vm';

const fixture = JSON.parse(readFileSync(resolve(process.cwd(), 'e2e/fixtures/ml-tabular-extensions.json'), 'utf8'));
const fields: SpecFieldDescriptor[] = fixture.fields;
const columns: PlanColumn[] = fixture.columns;

test('tabular options use catalog descriptors and remain empty for legacy catalogs', () => {
  assert.deepEqual(tabularFields({} as ModelCatalog, 'regression'), []);
  const catalog = { families: [{ key: 'tabular', tasks: ['classification', 'regression'], spec_fields: fields }] } as ModelCatalog;
  assert.deepEqual(tabularFields(catalog, 'regression'), fields);
  assert.deepEqual(tabularFields(catalog, 'forecasting'), []);
  assert.deepEqual(tabularSpec([], { probe_mode: 'on' }, 'regression'), {});
});

test('visibility reads resolved task and default values, never an authored task', () => {
  assert.deepEqual(shownSpecFields(fields, {}, 'regression').map((field) => field.key), ['probe_mode']);
  assert.deepEqual(shownSpecFields(fields, { task: 'regression', probe_mode: 'on' }, 'classification').map((field) => field.key), ['probe_enabled']);
  assert.deepEqual(shownSpecFields(fields, { probe_mode: 'on' }, 'regression').map((field) => field.key), ['probe_mode', 'probe_count', 'probe_columns']);
  const dependent = [...fields, { key: 'default_probe', kind: 'bool', required: false, default: false, when: { probe_mode: ['off'] } } satisfies SpecFieldDescriptor];
  assert.ok(shownSpecFields(dependent, {}, 'regression').some((field) => field.key === 'default_probe'));
});

test('request spec contains only applicable catalog fields and never the task context', () => {
  const authored = { probe_mode: 'on', probe_count: 5, probe_enabled: true, task: 'classification' };
  assert.deepEqual(tabularSpec(fields, authored, 'regression'), { probe_mode: 'on', probe_count: 5, probe_columns: [] });
  assert.deepEqual(tabularSpec(fields, authored, 'classification'), { probe_enabled: true });
  assert.deepEqual(tabularSpec(fields, { ...authored, probe_mode: 'off' }, 'regression'), { probe_mode: 'off' });
  assert.equal(authored.probe_count, 5, 'reading the form never mutates its draft');
  assert.equal(specValues(fields, { probe_count: null }, 'regression')['probe_count'], 3);
});

test('column choices exclude the target and honor catalog column kinds', () => {
  const field = fields.find((entry) => entry.key === 'probe_columns')!;
  assert.deepEqual(specColumns(field, columns, 'region').map((column) => column.name), ['segment']);
});

test('distillation inference cost is optional and an explicit zero survives serialization', () => {
  const cost: SpecFieldDescriptor[] = [{ key: 'distillation_inference_cost_per_1000', kind: 'float', required: false, min: 0, max: 1000, when: { task: ['classification'] } }];
  assert.deepEqual(tabularSpec(cost, {}, 'classification'), {});
  assert.deepEqual(tabularSpec(cost, { distillation_inference_cost_per_1000: null }, 'classification'), {});
  assert.deepEqual(tabularSpec(cost, { distillation_inference_cost_per_1000: 0 }, 'classification'), { distillation_inference_cost_per_1000: 0 });
  assert.deepEqual(tabularSpec(cost, { distillation_inference_cost_per_1000: 0 }, 'regression'), {});
});

test('text encoder is available for both tabular tasks and keeps legacy auto behavior', () => {
  const textFields = fixture.text_fields as SpecFieldDescriptor[];
  for (const task of ['classification', 'regression'] as const) {
    assert.deepEqual(tabularSpec(textFields, {}, task), { text_encoder: 'auto' });
    assert.deepEqual(tabularSpec(textFields, { text_encoder: 'minhash' }, task), { text_encoder: 'minhash' });
  }
});
