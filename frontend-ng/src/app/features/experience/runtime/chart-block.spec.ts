/**
 * `ChartBlock` through a real Angular `Injector` (no TestBed in this runner, so
 * signal inputs are bound by {@link bindInput}). The arithmetic behind the
 * series lives in `runtime.spec.ts`; what is exercised here is the resolution a
 * released document depends on — which of the two sources wins, and what a
 * reader is shown when the winning one carries nothing drawable.
 */
import '@angular/compiler';
import { ElementRef, Injector, runInInjectionContext, signal } from '@angular/core';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { I18nService } from '@app/core/i18n.service';
import { EXPERIENCE_EN } from '@app/core/i18n/experience.dict';
import { ThemeService } from '@app/core/theme.service';
import { ExperienceRuntimeService } from './experience-runtime.service';
import type { ExperienceNode, RuntimeNodeContext } from './model';
import { ChartBlock } from './runtime-blocks';

const CONTEXT: RuntimeNodeContext = {
  experienceSlug: 'churn-board',
  pageId: 'board',
  componentId: 'risk-bands',
  stateKey: 'churn-board:board:risk-bands',
  sourceStateKey: 'churn-board:board:load-board',
  mode: 'live',
};

const BANDS = [
  { label: 'critical', value: 9 },
  { label: 'high', value: 24 },
  { label: 'medium', value: 61 },
];

const BINDING = { source: 'run-output', componentId: 'load-board', selector: 'bands' };

/** The unit runner has no TestBed: a signal input reads like a function. */
function bindInput(component: object, name: string, value: unknown): void {
  Object.defineProperty(component, name, { value: () => value, configurable: true });
}

function i18nStub() {
  return {
    locale: signal('en' as const),
    t: (key: string, params?: Record<string, string | number>) => {
      const value = (EXPERIENCE_EN as Record<string, string>)[key] ?? key;
      return params
        ? value.replace(/\{(\w+)\}/g, (match, name: string) =>
            name in params ? String(params[name]) : match)
        : value;
    },
  };
}

interface ChartControls {
  readout(): string;
}

function setup(
  node: ExperienceNode,
  run: { output_ref?: Record<string, unknown> | null } | null = null,
  phase: 'idle' | 'loading' | 'running' | 'error' = 'idle',
): ChartBlock & ChartControls {
  const runtime = {
    run: () => run,
    phase: () => phase,
    lastError: () => null,
  };
  const injector = Injector.create({
    providers: [
      { provide: ExperienceRuntimeService, useValue: runtime },
      { provide: I18nService, useValue: i18nStub() },
      { provide: ThemeService, useValue: { resolved: signal('dark' as const) } },
      { provide: ElementRef, useValue: new ElementRef({}) },
    ],
  });
  const block = runInInjectionContext(injector, () => new ChartBlock());
  bindInput(block, 'node', node);
  bindInput(block, 'context', CONTEXT);
  return block as ChartBlock & ChartControls;
}

test('a chart with no binding draws the series the document shipped with', () => {
  const block = setup({
    type: 'chart',
    id: 'risk-bands',
    props: {
      title: { $i18n: 'board.bands.title', fallback: 'Risk bands' },
      caption: { $i18n: 'board.bands.caption', fallback: 'Subscribers by band' },
      kind: 'bar',
      series: BANDS,
    },
  });

  assert.equal(block.kind(), 'bar');
  assert.equal(block.slot(), 'ready');
  // A document that reached the renderer unlocalized still has copy to show:
  // the author's fallback is the string the page was written against.
  assert.equal(block.title(), 'Risk bands');
  assert.equal(block.caption(), 'Subscribers by band');
  assert.deepEqual(
    block.bars().map((bar) => [bar.label, bar.display, bar.width]),
    [['critical', '9', 15], ['high', '24', 39], ['medium', '61', 100]],
  );
});

test('a run-output binding replaces the series the document shipped with', () => {
  const node: ExperienceNode = {
    type: 'chart',
    id: 'risk-bands',
    props: { series: BANDS, dataBinding: BINDING },
  };
  const block = setup(node, {
    output_ref: { bands: [{ label: 'churned', value: 4 }, { label: 'retained', value: 96 }] },
  });

  assert.deepEqual(
    block.series().points.map((point) => point.label),
    ['churned', 'retained'],
  );
  // The static series is the fallback for a binding that has not resolved, not
  // a second dataset drawn beside the live one.
  assert.equal(block.series().points.length, 2);
  assert.equal(block.slot(), 'ready');
});

test('a bound chart follows the run it waits on, not the series it was authored with', () => {
  const node: ExperienceNode = {
    type: 'chart',
    id: 'risk-bands',
    props: { series: BANDS, dataBinding: BINDING },
  };

  assert.equal(setup(node, null, 'running').slot(), 'loading');
  assert.equal(setup(node, null, 'error').slot(), 'error');
  // A binding that has not answered yet is not an occasion to draw authored
  // numbers: `table` and `kpi` hand the slot to the run the moment a binding
  // exists, and a page whose blocks disagree about that is worse than one that
  // waits.
  assert.equal(setup(node).slot(), 'empty');
  assert.deepEqual(setup(node).bars(), []);
});

test('a binding that resolved to something undrawable shows the empty state', () => {
  const node: ExperienceNode = {
    type: 'chart',
    id: 'risk-bands',
    props: { series: BANDS, dataBinding: BINDING, a11y: { emptyText: 'No band was measured' } },
  };

  // Each of these is a shape a System can return on a bad morning. None of them
  // may take the page down, and none may be drawn as a chart of zeroes.
  for (const bands of [null, 'critical', 42, {}, [], [{ band: 'critical' }]]) {
    const block = setup(node, { output_ref: { bands } });
    assert.equal(block.slot(), 'empty', `${JSON.stringify(bands)} is not a series`);
    assert.deepEqual(block.bars(), []);
    assert.equal(block.emptyText(), 'No band was measured');
  }
});

test('a chart reads the fields it was told to read, and label/value when it was told nothing', () => {
  const rows = [{ band: 'critical', subscribers: 9 }, { band: 'high', subscribers: 27 }];

  assert.deepEqual(
    setup({
      type: 'chart',
      id: 'risk-bands',
      props: { series: rows, labelKey: 'band', valueKey: 'subscribers' },
    }).bars().map((bar) => bar.label),
    ['critical', 'high'],
  );

  // The same rows under the defaults name no label and no number at all.
  assert.deepEqual(setup({ type: 'chart', id: 'risk-bands', props: { series: rows } }).bars(), []);
});

test('an unrecognised kind draws bars rather than refusing the document', () => {
  const props = { series: BANDS };

  assert.equal(setup({ type: 'chart', id: 'c', props: { ...props, kind: 'donut' } }).kind(), 'donut');
  assert.equal(setup({ type: 'chart', id: 'c', props: { ...props, kind: 'sunburst' } }).kind(), 'bar');
  assert.equal(setup({ type: 'chart', id: 'c', props }).kind(), 'bar');
});

test('a donut announces the numbers its canvas hides', () => {
  const block = setup({
    type: 'chart',
    id: 'risk-bands',
    props: { kind: 'donut', title: 'Risk bands', series: BANDS },
  });

  assert.equal(block.readout(), 'Risk bands: critical 9, high 24, medium 61');
  // With nothing to read out, the name still has to be said: a bare role="img"
  // announces nothing at all.
  assert.equal(setup({ type: 'chart', id: 'c', props: { kind: 'donut' } }).readout(), 'Results chart');
});
