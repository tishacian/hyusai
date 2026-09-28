import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  mapAgendaMetadataToOrdre,
  mapDecisionsToOrdre,
  mapMacroToIndicateurs,
  mapMapToZones,
  mapMonitorToAlertes,
  mapNewsToFlux,
  mapRegisterToIndicateurs,
  mapTimelineToEcheancier,
} from './impact-block-data';

test('timeline agenda maps to echeancier items', () => {
  const items = mapTimelineToEcheancier({
    agenda: [
      { id: 'e1', title: 'Conseil', location: 'Salle A', status: 'confirmed', time: '09:00', date: '2026-09-28' },
      { title: '', time: '10:00' },
    ],
  });
  assert.equal(items.length, 1);
  assert.equal(items[0]!.id, 'e1');
  assert.equal(items[0]!.place, 'Salle A');
});

test('news signals map to flux; empty stays empty', () => {
  assert.deepEqual(mapNewsToFlux({ signals: [] }), []);
  const items = mapNewsToFlux({
    signals: [{ id: 'n1', title: 'Alert press', source_category: 'verified', sentiment: 'neg', confidence: 0.8 }],
  });
  assert.equal(items[0]!.klass, 'verified');
});

test('map zones and monitor alertes keep zone for filtering', () => {
  assert.deepEqual(mapMapToZones({ zones: [{ id: 'z1', name: 'Nord', level: 2 }] }), [
    { id: 'z1', name: 'Nord', level: 2 },
  ]);
  const alerts = mapMonitorToAlertes({
    zones: [{ id: 'z1', name: 'Nord', level: 'high', signals: ['Incursion'] }],
  });
  assert.equal(alerts[0]!.zone, 'Nord');
});

test('ordre prefers agenda metadata; decisions are a fallback', () => {
  const fromAgenda = mapAgendaMetadataToOrdre({
    agenda: [{
      id: 'evt',
      title: 'Réunion',
      metadata: {
        agenda_items: [{
          id: 'p1',
          title: 'Budget',
          origin: 'agent',
          options: [{ id: 'a', label: 'Approuver', recommended: true }],
        }],
      },
    }],
  }, 'evt');
  assert.equal(fromAgenda[0]!.origin, 'agent');
  assert.equal(fromAgenda[0]!.options?.[0]?.recommended, true);

  const fromDecisions = mapDecisionsToOrdre([
    {
      id: 'd1',
      scope: 'portfolio',
      kind: 'meeting',
      status: 'proposed',
      title: 'Arbitrage',
      agent_suggested: true,
    },
  ]);
  assert.equal(fromDecisions[0]!.origin, 'agent');
  assert.deepEqual(fromDecisions[0]!.options, []);
});

test('macro and register indicateurs stay honest when empty', () => {
  assert.deepEqual(mapMacroToIndicateurs({ indicators: [] }), []);
  const fromRegister = mapRegisterToIndicateurs([
    {
      systemId: 's1',
      capabilityId: null,
      name: 'Helpdesk',
      initials: 'H',
      health: 'pos',
      daysSinceLastRun: { state: 'available', value: 1 },
      outputUnit: 'tickets',
      weekSpark: [],
      cost: { state: 'available', value: 10 },
      hours: { state: 'available', value: 4 },
      valueDeclared: { state: 'available', value: 100 },
      outcomes: { state: 'available', value: 2 },
      runs: { state: 'available', value: 3 },
      basisStatus: 'measured',
      currency: 'EUR',
      outsideDenominator: false,
    },
  ]);
  assert.equal(fromRegister[0]!.state, 'measured');
  assert.equal(fromRegister[0]!.value, '100');
});
