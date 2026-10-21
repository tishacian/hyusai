import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { signal } from '@angular/core';
import { ForecastPlaygroundComponent } from './forecast-playground.component';
import type { ForecastAnswer, ForecastRequestBody } from './forecast.vm';
import type { ModelDto, ServingBlock } from './models.vm';

const answer = (horizon: number): ForecastAnswer => ({
  served: { model_id: 'forecast-v1', version: 1 }, horizon, interval_level: .8,
  series: [], forecast: [], rows: horizon, duration_ms: 10,
});

function harness() {
  let workspaceCurrent = true;
  const calls: Array<{ body: ForecastRequestBody; resolve: (value: ForecastAnswer) => void; reject: (error: unknown) => void }> = [];
  const horizon = signal(14), level = signal(.8), series = signal('web');
  const planned = signal<Record<string, number>>({ campaign: 1 });
  const canAsk = signal(true);
  const model = signal<ModelDto>({ id: 'forecast-v1', version: 1, spec: { horizon: 14, interval_level: .8 } } as ModelDto);
  const serving = signal<ServingBlock>({ enabled: true, callable: true, serving_model_id: 'forecast-v1', serving_version: 1, is_serving: true, mode: 'forecast' } as ServingBlock);
  const component = Object.assign(Object.create(ForecastPlaygroundComponent.prototype), {
    horizon, level, series, planned, canAsk, model, serving, requestGeneration: 0, modelContext: '',
    running: signal(false), answer: signal<ForecastAnswer | null>(answer(14)), error: signal<string | null>(null),
    maxSteps: () => 90,
    request: () => ({ params: { horizon: horizon(), interval_level: level() }, inputs: [{ series: series(), ...planned() }] }),
    i18n: { t: (key: string) => key },
    workspace: { captureRequestScope: () => 'showcase', isRequestScopeCurrent: () => workspaceCurrent },
    models: { forecast: (_id: string, body: ForecastRequestBody) => new Promise<ForecastAnswer>((resolve, reject) => calls.push({ body, resolve, reject })) },
  });
  component.syncModelContext();
  series.set('web'); planned.set({ campaign: 1 }); component.answer.set(answer(14));
  return { component, calls, switchWorkspace: () => { workspaceCurrent = false; } };
}

test('a failed forecast retry never leaves the previous successful answer visible', async () => {
  const { component, calls } = harness();
  const pending = component.run();
  assert.equal(component.answer(), null);
  assert.equal(component.running(), true);
  calls[0].reject({ error: { detail: { message: 'Forecast unavailable' } } });
  await pending;
  assert.equal(component.answer(), null);
  assert.equal(component.error(), 'Forecast unavailable');
  assert.equal(component.running(), false);
});

for (const [label, change] of [
  ['horizon', (component: ReturnType<typeof harness>['component']) => component.onHorizon(21)],
  ['interval', (component: ReturnType<typeof harness>['component']) => component.onLevel({ target: { value: '.9' } })],
  ['series', (component: ReturnType<typeof harness>['component']) => component.onSeries('store')],
  ['covariate', (component: ReturnType<typeof harness>['component']) => component.onPlanned('campaign', 2)],
] as const) {
  test(`changing the ${label} clears the answer and ignores an earlier in-flight result`, async () => {
    const { component, calls } = harness();
    const previous = component.run();
    change(component);
    assert.equal(component.answer(), null);
    assert.equal(component.running(), false);
    const current = component.run();
    assert.equal(calls.length, 2);
    calls[0].resolve(answer(14));
    await previous;
    assert.equal(component.answer(), null);
    assert.equal(component.running(), true, 'the old response cannot stop the new request');
    calls[1].resolve(answer(component.horizon()));
    await current;
    assert.equal(component.answer()?.horizon, component.horizon());
    assert.equal(component.running(), false);
  });
}

test('an unchanged parameter preserves its matching answer', () => {
  const { component } = harness();
  component.onHorizon(14);
  component.onLevel({ target: { value: '.8' } });
  component.onSeries('web');
  component.onPlanned('campaign', 1);
  assert.equal(component.answer()?.horizon, 14);
});

test('an incomplete question and a duplicate click do not send a forecast', async () => {
  const { component, calls } = harness();
  component.canAsk.set(false);
  await component.run();
  assert.equal(calls.length, 0);
  component.canAsk.set(true);
  const pending = component.run();
  await component.run();
  assert.equal(calls.length, 1);
  calls[0].resolve(answer(14));
  await pending;
});

test('a response from the previous workspace remains ignored', async () => {
  const { component, calls, switchWorkspace } = harness();
  const pending = component.run();
  switchWorkspace();
  calls[0].resolve(answer(14));
  await pending;
  assert.equal(component.answer(), null);
});

test('refreshing the same model preserves user parameters, a completed answer and an in-flight request', async () => {
  const { component, calls } = harness();
  component.onHorizon(21);
  component.onLevel({ target: { value: '.9' } });
  const pending = component.run();
  // Monitoring returns a new DTO, with reordered spec keys and new counters.
  const refresh = () => {
    component.model.update((row: ModelDto) => ({ ...row, spec: { interval_level: .8, horizon: 14 } }));
    component.serving.update((row: ServingBlock) => ({ ...row, predict_count: (row.predict_count ?? 0) + 1 }));
    component.syncModelContext();
  };
  refresh();
  assert.equal(component.horizon(), 21);
  assert.equal(component.level(), .9);
  assert.equal(component.series(), 'web');
  assert.deepEqual(component.planned(), { campaign: 1 });
  assert.equal(component.running(), true);
  calls[0].resolve(answer(21));
  await pending;
  refresh();
  assert.equal(component.answer()?.horizon, 21);
  assert.equal(component.horizon(), 21);
  assert.equal(component.level(), .9);
});

for (const [label, change] of [
  ['model version', (component: ReturnType<typeof harness>['component']) => component.model.update((row: ModelDto) => ({ ...row, version: 2 }))],
  ['saved spec', (component: ReturnType<typeof harness>['component']) => component.model.update((row: ModelDto) => ({ ...row, spec: { horizon: 7, interval_level: .95 } }))],
  ['serving alias', (component: ReturnType<typeof harness>['component']) => component.serving.update((row: ServingBlock) => ({ ...row, serving_model_id: 'forecast-v2', serving_version: 2, is_serving: false }))],
] as const) {
  test(`a changed ${label} invalidates the answer and rejects the earlier response before the effect runs`, async () => {
    const { component, calls } = harness();
    component.onHorizon(21);
    const pending = component.run();
    change(component);
    calls[0].resolve(answer(21));
    await pending;
    assert.equal(component.answer(), null, 'the old identity is rejected even before Angular runs the effect');
    component.syncModelContext();
    assert.equal(component.horizon(), label === 'saved spec' ? 7 : 14);
    assert.equal(component.level(), label === 'saved spec' ? .95 : .8);
    assert.equal(component.running(), false);
    assert.equal(component.answer(), null);
  });
}

test('new model inputs clear an already completed forecast', () => {
  const { component } = harness();
  assert.equal(component.answer()?.horizon, 14);
  component.model.update((row: ModelDto) => ({ ...row, id: 'other-model' }));
  component.syncModelContext();
  assert.equal(component.answer(), null);
});
