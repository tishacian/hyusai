import assert from 'node:assert/strict';
import { test } from 'node:test';
import { HYPERVISOR_FR, HYPERVISOR_EN } from '@app/core/i18n/hypervisor.dict';
import { FLOW_FR, FLOW_EN } from '@app/core/i18n/flow.dict';
import { SYSTEMS_FR, SYSTEMS_EN } from '@app/core/i18n/systems.dict';
import { availableHypervisorViews, DEFAULT_HYPERVISOR_VIEWS, IMPACT_GENERIC_VIEWS } from './hypervisor-v2-views';

test('Mission Room views are available only on Synthèse with a Mission Room, even in saved catalogs', () => {
  const saved = [...DEFAULT_HYPERVISOR_VIEWS, ...IMPACT_GENERIC_VIEWS];
  for (const hasRoom of [false, true]) for (const synthese of [false, true]) {
    const views = availableHypervisorViews(saved, hasRoom, synthese);
    assert.deepEqual(views.map(view => view.id), [
      'direction', 'operations', 'conformite',
      ...(hasRoom && synthese ? ['agenda', 'veille', 'securite', 'reunion', 'carte'] : []),
    ]);
  }
  assert.deepEqual(availableHypervisorViews(DEFAULT_HYPERVISOR_VIEWS, true, true).slice(3).map(view => view.id),
    ['agenda', 'veille', 'securite', 'reunion', 'carte']);
});

test('every built-in view has FR/EN labels, including accents and Compliance', () => {
  for (const view of [...DEFAULT_HYPERVISOR_VIEWS, ...IMPACT_GENERIC_VIEWS]) {
    const key = view.label as keyof typeof HYPERVISOR_FR;
    assert.ok(HYPERVISOR_FR[key]); assert.ok(HYPERVISOR_EN[key]);
  }
  assert.equal(HYPERVISOR_FR['hypervisor.v2.view.conformite'], 'Conformité');
  assert.equal(HYPERVISOR_EN['hypervisor.v2.view.conformite'], 'Compliance');
  assert.equal(HYPERVISOR_FR['hypervisor.v2.view.securite'], 'Sécurité');
});

test('demo copy exists in both locales with business French', () => {
  assert.equal(SYSTEMS_FR['systems.view.runs'], 'Exécutions');
  assert.equal(SYSTEMS_FR['systems.view.guardrails'], 'Garde-fous');
  assert.equal(SYSTEMS_FR['systems.view.runtime'], 'Moteur d’exécution');
  assert.equal(SYSTEMS_EN['systems.view.model'], 'Model');
  for (const [fr, en] of [[SYSTEMS_FR, SYSTEMS_EN], [FLOW_FR, FLOW_EN]]) {
    for (const key of Object.keys(fr)) assert.ok((en as Record<string, string>)[key], key);
  }
  assert.match(FLOW_FR['flow.versions.blocked.local_changes'], /Enregistrez ou abandonnez/);
});
