import '@angular/compiler';
import assert from 'node:assert/strict';
import test from 'node:test';
import {
  Injector,
  ɵChangeDetectionScheduler as ChangeDetectionScheduler,
  ɵEffectScheduler as EffectScheduler,
} from '@angular/core';
import { Subject } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import {
  findOctocityForbiddenPresentationTerms,
  findSentinelForbiddenPresentationTerms,
} from './mission-room.presentation';
import { VpMacroIndicatorsComponent } from './vp-macro-indicators.component';

/**
 * The macro strip is mounted by the shared cockpit in every workspace, so
 * anything it renders before its own aggregate answers is rendered under some
 * other tenant's branding. These tests assert both directions of the
 * `cross_terms_absent` canary against the pre-load and error states.
 */

function createHarness() {
  const calls: Array<{ path: string; response: Subject<unknown> }> = [];
  const api = {
    get: (path: string) => {
      const response = new Subject<unknown>();
      calls.push({ path, response });
      return response.asObservable();
    },
  };
  const injector = Injector.create({
    providers: [
      VpMacroIndicatorsComponent,
      { provide: ApiService, useValue: api },
      { provide: ChangeDetectionScheduler, useValue: { notify() {}, runningTick: false } },
      { provide: EffectScheduler, useValue: { add() {}, schedule() {}, flush() {}, remove() {} } },
    ],
  });
  return { component: injector.get(VpMacroIndicatorsComponent), calls };
}

function renderedCorpus(component: VpMacroIndicatorsComponent): string {
  return JSON.stringify([
    component.sovereignIndicators(),
    component.contextIndicators(),
    component.sourceLabel(),
  ]);
}

function assertTenantNeutral(component: VpMacroIndicatorsComponent, stage: string): void {
  const corpus = renderedCorpus(component);
  assert.deepEqual(
    findSentinelForbiddenPresentationTerms(corpus),
    [],
    `${stage} must not render Octocity vocabulary`,
  );
  assert.deepEqual(
    findOctocityForbiddenPresentationTerms(corpus),
    [],
    `${stage} must not render Sentinel vocabulary`,
  );
}

test('macro strip renders nothing tenant-branded before its aggregate answers', () => {
  const { component } = createHarness();

  assertTenantNeutral(component, 'pre-construction state');

  component.ngOnInit();
  assertTenantNeutral(component, 'in-flight state');
  assert.deepEqual(component.sovereignIndicators(), []);
  assert.deepEqual(component.contextIndicators(), []);
});

test('macro strip stays tenant-neutral when the aggregate fails', () => {
  const { component, calls } = createHarness();
  component.ngOnInit();

  assert.deepEqual(calls.map((call) => call.path), ['/mission-room/macro-indicators']);
  calls[0].response.error(new Error('macro-indicators unavailable'));

  assertTenantNeutral(component, 'error state');
  assert.deepEqual(component.sovereignIndicators(), []);
  assert.deepEqual(component.contextIndicators(), []);
});

test('macro strip renders the workspace payload it is actually served', () => {
  const { component, calls } = createHarness();
  component.ngOnInit();

  calls[0].response.next({
    sovereign_indicators: [{
      key: 'grid_load',
      label: 'Charge reseau',
      current: 812,
      unit: 'MW',
      source: 'Workspace telemetry',
      series: [{ date: '2026-05-24', value: 800 }, { date: '2026-05-25', value: 812 }],
    }],
    indicators: [{
      key: 'inflation',
      label: 'Inflation',
      current: 4.2,
      unit: '%',
      series: [{ year: 2024, value: 3.8 }, { year: 2025, value: 4.2 }],
    }],
    sovereign_source: 'Workspace telemetry',
  });
  calls[0].response.complete();

  assert.deepEqual(component.sovereignIndicators().map((item) => item.key), ['grid_load']);
  assert.deepEqual(component.contextIndicators().map((item) => item.key), ['inflation']);
  assert.equal(component.sourceLabel(), 'Workspace telemetry');
  assertTenantNeutral(component, 'loaded state');
});
