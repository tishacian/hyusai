import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector, signal } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { RUNS_EN, RUNS_FR } from '@app/core/i18n/runs.dict';
import type { Outcome } from '@app/core/canonical-api.service';
import { RunOutcomeCardComponent } from './run-outcome-card.component';
import { invocationCost } from './run-cost';

class CardProbe extends RunOutcomeCardComponent {
  snapshot() {
    return {
      id: this.shortId(), duration: this.durationLabel(), status: this.statusTone(),
      statusLabel: this.statusLabel(), decision: this.decisionLabel(),
      value: this.currency(this.value()), efficiency: this.efficiencyLabel(this.efficiency()),
      efficiencyTone: this.efficiencyTone(), confidence: this.percentage(this.outcome.confidence),
      confidenceTone: this.confidenceTone(), cost: this.formatCost(this.outcome.cost_internal),
    };
  }
}

function card(outcome: Outcome = {}) {
  const locale = signal<'en' | 'fr'>('en');
  const injector = Injector.create({ providers: [CardProbe, {
    provide: I18nService, useValue: {
      locale,
      t: (key: string) => (locale() === 'fr' ? RUNS_FR : RUNS_EN)[key as keyof typeof RUNS_FR] ?? key,
    },
  }] });
  const component = injector.get(CardProbe);
  component.run = { id: 'reference-run', status: 'completed', outcome };
  return { component, locale };
}

test('NorthForge unset value is absent, not zero business value or zero efficiency', () => {
  const { component } = card({ value_source: 'unset', value_estimated: 0, efficiency: 0, cost_internal: .012 });
  const view = component.snapshot();
  assert.equal(view.value, '—');
  assert.equal(view.efficiency, '—');
  assert.equal(view.efficiencyTone, 'neutral');
  assert.equal(view.cost, '$0.012');
  for (const source of [undefined, 'unset'] as const) {
    component.run = { id: 'legacy', outcome: { value_source: source, value_estimated: 999, efficiency: 999 } };
    assert.equal(component.snapshot().value, '—');
  }
});

test('declared and estimated zeros remain values; unavailable cost cannot yield efficiency', () => {
  const { component } = card();
  for (const source of ['auto', 'operator'] as const) {
    component.run = { id: source, outcome: { value_source: source, value_estimated: 0, efficiency: 0, cost_internal: 1 } };
    assert.equal(component.snapshot().value, '$0.00');
    assert.equal(component.snapshot().efficiency, '0%');
  }
  for (const cost of [undefined, null, 0, -1, NaN, Infinity]) {
    component.run = { id: 'unknown-cost', outcome: { value_source: 'auto', value_estimated: 10, efficiency: 10, cost_internal: cost } };
    assert.equal(component.snapshot().efficiency, '—');
  }
});

test('input updates and language changes refresh all cached Run summaries', () => {
  const { component, locale } = card();
  component.snapshot();
  component.run = { id: 'second-run', status: 'failed', duration_ms: 123.7,
    outcome: { value_source: 'operator', value_estimated: -2, confidence: .8, cost_internal: .001, efficiency: -1 } };
  assert.deepEqual(component.snapshot(), {
    id: 'second-r', duration: '124 ms', status: 'neg', statusLabel: 'Failed', decision: 'BLOCKED',
    value: '−$2.00', efficiency: '-100%', efficiencyTone: 'neg', confidence: '80%', confidenceTone: 'pos', cost: '$0.0010',
  });
  locale.set('fr');
  assert.equal(component.snapshot().decision, 'BLOQUÉ');
  assert.equal(component.snapshot().cost, new Intl.NumberFormat('fr', { style: 'currency', currency: 'USD', minimumFractionDigits: 4 }).format(.001));
  component.run = { id: 'third-run', status: 'running', outcome: {} };
  assert.equal(component.snapshot().status, 'cool');
  assert.equal(component.snapshot().value, '—');
});

test('nonfinite values and invalid confidence never become economic or quality indicators', () => {
  const { component } = card();
  for (const value of [NaN, Infinity, -Infinity]) {
    component.run = { id: 'invalid', outcome: { value_source: 'auto', value_estimated: value, confidence: value, cost_internal: value, efficiency: value } };
    const view = component.snapshot();
    for (const field of ['value', 'confidence', 'cost', 'efficiency'] as const) assert.equal(view[field], '—');
    assert.equal(view.confidenceTone, 'neutral');
  }
  for (const confidence of [-.1, 1.1]) {
    component.run = { id: 'invalid-confidence', outcome: { confidence } };
    assert.equal(component.snapshot().confidence, '—');
  }
});

test('invocation costs distinguish configured calculations, old zeros, missing evidence and tiny amounts', () => {
  const priced = (cost: number) => ({ cost, metrics: { cost_evidence: { state: 'calculated', method: 'catalog_unit_price', currency: 'EUR' } } });
  assert.deepEqual(invocationCost(priced(.012)), { value: '€0.012', labelKey: 'runs.outcome.cost_calculated' });
  assert.deepEqual(invocationCost(priced(0)), { value: '€0.00', labelKey: 'runs.outcome.cost_calculated' });
  assert.deepEqual(invocationCost(priced(.000001)), { value: '< €0.0001', labelKey: 'runs.outcome.cost_calculated' });
  assert.equal(invocationCost({ cost: 0 }).value, '—');
  assert.equal(invocationCost({ ...priced(9), cost_measured: false }).value, '—');
  assert.equal(invocationCost({ cost: 9, metrics: { cost_evidence: { state: 'not_measured' } } }).value, '—');
  assert.deepEqual(invocationCost({ cost: 1 }), { value: '$1.00', labelKey: 'runs.outcome.cost_recorded' });
  for (const cost of [NaN, Infinity, -1]) assert.equal(invocationCost(priced(cost)).value, '—');
  assert.equal(invocationCost({ ...priced(1), metrics: { cost_evidence: { state: 'calculated', currency: 'invalid' } } }).value, '—');
});
