/**
 * Required-parameter validity in the node inspector.
 *
 * The regression this pins: on a published, running System the node
 * `line_items_reconcile_v1` showed `po_lines` and `invoice_lines` in the
 * invalid state although both were fed by upstream bindings. The inspector
 * read `config.params.<key>` only, while the run engine merges those params as
 * defaults underneath whatever `config.inputs_map` binds.
 */
import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { FlowManifestField } from '@app/core/canonical-api.service';
import { isBoundInput, requiredParamUnsatisfied } from './manifest-fields.component';
import { labelDatasetField, labelDatasetValueMissing } from './llm-label-form';
import { FLOW_EN, FLOW_FR } from '@app/core/i18n/flow.dict';

function skillParam(key: string, required = true): FlowManifestField {
  return {
    key,
    source: 'skill.input_schema',
    type: 'array',
    required,
  } as FlowManifestField;
}

test('a required Skill param fed by an upstream binding is valid while empty', () => {
  const inputsMap = {
    po_lines: { node_id: 'extract.po', path: ['lines'] },
    invoice_lines: 'legacy.invoice.lines',
  };

  assert.equal(requiredParamUnsatisfied(skillParam('po_lines'), undefined, inputsMap), false);
  assert.equal(requiredParamUnsatisfied(skillParam('po_lines'), null, inputsMap), false);
  assert.equal(requiredParamUnsatisfied(skillParam('po_lines'), '', inputsMap), false);
  assert.equal(
    requiredParamUnsatisfied(skillParam('invoice_lines'), undefined, inputsMap),
    false,
    'a legacy dot-path binding still supplies the value at runtime',
  );
});

test('a required Skill param with neither value nor binding stays invalid', () => {
  assert.equal(requiredParamUnsatisfied(skillParam('po_lines'), undefined, {}), true);
  assert.equal(requiredParamUnsatisfied(skillParam('po_lines'), '', {}), true);
  assert.equal(
    requiredParamUnsatisfied(skillParam('po_lines'), undefined, { po_lines: '   ' }),
    true,
    'a blank binding binds nothing',
  );
  assert.equal(
    requiredParamUnsatisfied(skillParam('po_lines'), undefined, { po_lines: { node_id: '' } }),
    true,
    'a malformed VariableRef binds nothing',
  );
  assert.equal(
    requiredParamUnsatisfied(skillParam('po_lines'), undefined, { other_port: 'x.y' }),
    true,
    'the binding has to be on the matching port',
  );
});

test('a supplied value or an optional param is never flagged, whatever the bindings', () => {
  assert.equal(requiredParamUnsatisfied(skillParam('threshold'), 0, {}), false);
  assert.equal(requiredParamUnsatisfied(skillParam('rows'), [], {}), false);
  assert.equal(requiredParamUnsatisfied(skillParam('rows', false), undefined, {}), false);
});

test('only Skill params read a binding; node config and data keep the plain test', () => {
  const configField = { key: 'top_k', source: 'node.config', required: true } as FlowManifestField;
  const dataField = { key: 'top_k', source: 'node.data', required: true } as FlowManifestField;
  const inputsMap = { top_k: { node_id: 'upstream', path: ['top_k'] } };

  assert.equal(requiredParamUnsatisfied(configField, undefined, inputsMap), true);
  assert.equal(requiredParamUnsatisfied(dataField, undefined, inputsMap), true);
  assert.equal(requiredParamUnsatisfied(configField, 5, inputsMap), false);
});

test('binding recognition accepts a typed ref or a legacy path, nothing else', () => {
  assert.equal(isBoundInput({ node_id: 'n1', path: ['out'] }), true);
  assert.equal(isBoundInput({ node_id: 'n1', path: [] }), true);
  assert.equal(isBoundInput('n1.out'), true);
  assert.equal(isBoundInput(''), false);
  assert.equal(isBoundInput(null), false);
  assert.equal(isBoundInput(undefined), false);
  assert.equal(isBoundInput({}), false);
  assert.equal(isBoundInput(42), false);
});

test('dataset labeling presents every graph-owned setting in both languages', () => {
  const keys = ['sources', 'text_columns', 'labels', 'label_column', 'instruction', 'output_name',
    'batch_size', 'max_rows', 'max_tokens', 'max_output_tokens', 'max_cost_usd',
    'input_cost_per_million', 'output_cost_per_million', 'timeout_s', 'resume_job_id'];
  for (const key of keys) {
    const field = labelDatasetField('llm_label_dataset_v1', key);
    assert.ok(field, key);
    for (const dictionary of [FLOW_FR, FLOW_EN] as Record<string, string>[]) {
      assert.ok(dictionary[field.labelKey], `${key} has a label`);
      assert.ok(dictionary[field.helpKey], `${key} has instructions`);
    }
  }
  assert.equal(labelDatasetField('ml_predict_v1', 'sources'), null);
  assert.equal(labelDatasetField('llm_label_dataset_v1', 'unknown'), null);
  assert.equal(labelDatasetField('llm_label_dataset_v1', 'instruction')?.multiline, true);
});

test('labeling requires explicit prices but accepts an explicit zero price', () => {
  assert.equal(labelDatasetField('llm_label_dataset_v1', 'input_cost_per_million')?.required, true);
  assert.equal(labelDatasetField('llm_label_dataset_v1', 'output_cost_per_million')?.required, true);
  assert.equal(labelDatasetValueMissing(undefined), true);
  assert.equal(labelDatasetValueMissing(null), true);
  assert.equal(labelDatasetValueMissing(0), false);
  assert.equal(labelDatasetValueMissing([]), true);
  assert.equal(labelDatasetValueMissing('   '), true);
  assert.equal(labelDatasetValueMissing(['positive', 'negative']), false);
});
