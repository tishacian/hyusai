import assert from 'node:assert/strict';
import test from 'node:test';
import {
  FSE_INTERVENTION_V1,
  applicableTemplateFields,
  asCheckboxGroup,
  captureTemplateSystemReady,
  coerceCaptureTemplate,
  composePublicationName,
  isHeaderFieldFilled,
  resolveInterventionType,
  seedHeaderDefaults,
  templateWithInterventionType,
  weekLabelFromIsoDate,
} from './capture-templates';

test('FSE template plan remains blocked until its System is resolved', () => {
  assert.equal(captureTemplateSystemReady(FSE_INTERVENTION_V1, null), false);
  assert.equal(captureTemplateSystemReady(FSE_INTERVENTION_V1, ''), false);
  assert.equal(captureTemplateSystemReady(FSE_INTERVENTION_V1, 'system-fse'), true);
  assert.equal(captureTemplateSystemReady(null, null), true);
});

test('FSE template exposes three EX70 intervention types with plan seeds', () => {
  const types = FSE_INTERVENTION_V1.intervention_types ?? [];
  assert.equal(types.length, 3);
  assert.deepEqual(
    types.map((t) => t.id),
    ['weekly_site', 'field_service', 'process'],
  );
  assert.ok(types.every((t) => t.doc_ref.includes('EX70') && t.plan_seed.topics.length > 0));
  const weekly = templateWithInterventionType(FSE_INTERVENTION_V1, 'weekly_site');
  assert.ok(weekly.plan_seed.topics.some((t) => t.title.startsWith('HSE')));
  const field = templateWithInterventionType(FSE_INTERVENTION_V1, 'field_service');
  assert.ok(field.plan_seed.topics.some((t) => /Travaux exécutés|Situation sur site/i.test(t.title)));
});

test('equipment_progress applies only to weekly_site and process', () => {
  const weekly = applicableTemplateFields(FSE_INTERVENTION_V1, 'weekly_site');
  const fieldService = applicableTemplateFields(FSE_INTERVENTION_V1, 'field_service');
  assert.ok(weekly.some((f) => f.key === 'progress'));
  assert.ok(!fieldService.some((f) => f.key === 'progress'));
});

test('seed defaults prefill HSE, distribution and site_modifications', () => {
  const defaults = seedHeaderDefaults(FSE_INTERVENTION_V1, 'weekly_site');
  assert.match(String(defaults['hse_safety']), /None/i);
  assert.ok(Array.isArray(defaults['distribution']));
  assert.ok((defaults['distribution'] as string[]).length > 0);
  const mods = asCheckboxGroup(defaults['site_modifications']);
  assert.deepEqual(mods.values, ['none']);
});

test('checkbox_group and equipment_progress fill rules', () => {
  const mods = FSE_INTERVENTION_V1.required_fields.find((f) => f.key === 'site_modifications')!;
  const progress = FSE_INTERVENTION_V1.required_fields.find((f) => f.key === 'progress')!;
  assert.equal(isHeaderFieldFilled(mods, { selected: ['none'], description: '' }), true);
  assert.equal(isHeaderFieldFilled(mods, { values: ['none'], description: '' }), true);
  assert.equal(isHeaderFieldFilled(mods, { selected: ['plc_hmi'], description: '' }), false);
  assert.equal(isHeaderFieldFilled(mods, { selected: ['plc_hmi'], description: 'logic update' }), true);
  assert.equal(isHeaderFieldFilled(progress, []), false);
  assert.equal(isHeaderFieldFilled(progress, [{ equipment: 'Mill', percent: 40 }]), true);
});

test('weekLabelFromIsoDate returns ISO week', () => {
  assert.equal(weekLabelFromIsoDate('2026-07-20'), 'W30');
});

test('FSE cartouche exposes week and issued_by', () => {
  const keys = FSE_INTERVENTION_V1.required_fields.map((f) => f.key);
  assert.ok(keys.includes('week'));
  assert.ok(keys.includes('issued_by'));
});

test('coerceCaptureTemplate merges intervention_types and field options', () => {
  const coerced = coerceCaptureTemplate({
    id: 'fse_intervention_v1',
    intervention_types: [
      {
        id: 'weekly_site',
        label: 'Weekly',
        doc_ref: 'P APG EX70 004 01',
        plan_seed: { topics: [{ title: 'HSE' }] },
      },
    ],
    required_fields: [
      {
        key: 'distribution',
        label: 'Diffusion',
        kind: 'select_multi',
        required: true,
        options: [{ value: 'quality', label: 'Quality' }],
        default: ['quality'],
      },
    ],
  });
  assert.ok(coerced);
  assert.equal(resolveInterventionType(coerced, 'weekly_site')?.doc_ref, 'P APG EX70 004 01');
  assert.equal(coerced!.required_fields[0].options?.[0].value, 'quality');
});

test('composePublicationName follows PROJECT-Supervisor-Week', () => {
  const name = composePublicationName({
    reference: 'APG-42',
    participants: 'J Dupont',
    intervention_date: '2026-07-20',
  });
  assert.equal(name, 'APG-42-J Dupont-2026-07-20');
});
