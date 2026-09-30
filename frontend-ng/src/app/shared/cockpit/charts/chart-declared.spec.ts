import '@angular/compiler';
import { ChangeDetectorRef, ElementRef, Injector, runInInjectionContext } from '@angular/core';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';

import {
  CK_DECLARED_DASH_BOLD,
  CK_DECLARED_DASH_THIN,
  ckChartIsDeclared,
  ckChartToneVar,
} from './chart.types';
import { CkChartMiniAreaComponent } from './mini-area.component';
import { CkChartRadialDaysComponent } from './radial-days.component';
import { CkChartSankeyFlowComponent } from './sankey-flow.component';
import { CkChartStreamComponent } from './stream.component';
import { CkChartUnitDotsComponent } from './unit-dots.component';

/**
 * "Declared" is painted in the primary colour, the same teal as a button.
 * Every declared mark therefore carries a second, colour-free cue: a hatch on
 * areas, dashes on thin marks, ◐ in text. These tests pin that cue on each
 * chart's view model and check the template actually paints it.
 */

const injector = Injector.create({
  providers: [
    { provide: ElementRef, useValue: new ElementRef({}) },
    { provide: ChangeDetectorRef, useValue: { markForCheck: () => undefined } },
  ],
});

function make<T>(type: new () => T): T {
  return runInInjectionContext(injector, () => new type());
}

function source(file: string): string {
  return readFileSync(join(process.cwd(), 'src/app/shared/cockpit/charts', file), 'utf8');
}

test('chart tones map to the data inks, and only the declared tones count as declared', () => {
  assert.equal(ckChartToneVar('ink'), 'var(--ck-data-measured)');
  assert.equal(ckChartToneVar('ink-soft'), 'var(--ck-data-measured)');
  assert.equal(ckChartToneVar('declared'), 'var(--ck-data-declared)');
  assert.equal(ckChartToneVar('declared-soft'), 'var(--ck-data-declared)');
  assert.equal(ckChartToneVar('muted'), 'var(--ck-data-muted)');
  assert.equal(ckChartToneVar('negative'), 'var(--ck-data-zero)');
  assert.deepEqual(
    (['ink', 'ink-soft', 'declared', 'declared-soft', 'muted', 'negative', null] as const).map(ckChartIsDeclared),
    [false, false, true, true, false, false, false],
  );
});

test('stream: every declared area is hatched on top of its tint, measured areas are not', () => {
  const stream = make(CkChartStreamComponent);
  stream.series = [
    { id: 'capture', label: 'Capture', values: [4, 5, 6], tone: 'ink' },
    { id: 'helpdesk', label: 'Helpdesk', values: [3, 2, 4], tone: 'declared' },
    { id: 'pr', label: 'PR', values: [1, 2, 1], tone: 'declared-soft' },
  ];
  stream.ngOnChanges({ series: {} as never });
  const [ink, declared, soft] = stream.areas;
  assert.equal(ink!.hatch, null);
  assert.equal(declared!.hatch, `url(#${stream.hatchId})`);
  assert.equal(soft!.hatch, `url(#${stream.hatchSoftId})`, 'the soft neighbour carries a lighter hatch');
  assert.equal(declared!.fill, `url(#${stream.declaredId})`, 'the teal tint stays under the hatch');
  // Each declared layer is told apart by a 1 px top edge and a 1 px gap on its lower boundary.
  assert.ok(declared!.top.startsWith('M') && declared!.base?.startsWith('M'));
  assert.equal(ink!.base, null, 'the bottom layer sits on the baseline: no gap to cut');

  const other = make(CkChartStreamComponent);
  assert.notEqual(other.hatchId, stream.hatchId, 'pattern ids are unique per chart instance');
  assert.notEqual(other.layerMaskId, stream.layerMaskId, 'mask ids are unique per chart instance');

  const template = source('stream.component.ts');
  assert.match(template, /<pattern\s+\[attr\.id\]="hatchId"/);
  assert.match(template, /<pattern\s+\[attr\.id\]="hatchSoftId"/);
  assert.doesNotMatch(template, /rotate\(-45\)/, 'every declared layer hatches in the same direction');
  assert.match(template, /@if \(area\.hatch\) \{\s*<path\s+class="ck-area ck-area-hatch"[\s\S]*?\[attr\.fill\]="area\.hatch"/);
  assert.match(template, /class="ck-area-edge"\s+\[attr\.d\]="area\.top"/);
  assert.match(template, /\[attr\.mask\]="area\.hatch \? 'url\(#' \+ layerMaskId/);
});

test('stream: the chart keeps one viewBox unit per CSS pixel, so the hatch is never stretched', () => {
  const template = source('stream.component.ts');
  assert.doesNotMatch(template, /preserveAspectRatio/);
  assert.match(template, /\[style\.height\]="fluid \? 'auto' : null"/);
  assert.match(template, /this\.width = next;/);
});

test('radial days: a declared segment is dashed, a measured one stays a solid stroke', () => {
  const dial = new CkChartRadialDaysComponent();
  dial.days = [
    { measured: 4, declared: 3 },
    { measured: 5, declared: 0 },
    { measured: 0, declared: 2, weekend: true },
  ];
  dial.ngOnChanges({ days: {} as never });
  const [mixed, measuredOnly, declaredOnly] = dial.spokes;
  assert.ok(mixed!.ink && mixed!.teal);
  assert.equal(mixed!.tealDash, CK_DECLARED_DASH_BOLD);
  assert.equal(measuredOnly!.teal, '');
  assert.equal(measuredOnly!.tealDash, null);
  assert.equal(declaredOnly!.ink, '');
  assert.equal(declaredOnly!.tealDash, CK_DECLARED_DASH_BOLD);

  const template = source('radial-days.component.ts');
  assert.match(template, /class="ck-spoke-declared"[\s\S]*?\[attr\.stroke-dasharray\]="spoke\.tealDash"/);
  // The draw-in owns `stroke-dasharray` on the measured stroke; if it reached
  // the declared one it would erase the dashes for the whole entrance.
  assert.match(template, /:host-context\(\.hv2-enter\) \.ck-spoke-stroke \{\s*stroke-dasharray: var\(--len\)/);
  assert.doesNotMatch(template, /\.ck-spoke-declared[^{]*\{[^}]*stroke-dasharray/);
});

test('sankey: the value ribbon is hatched and the value node is dashed', () => {
  const flow = make(CkChartSankeyFlowComponent);
  flow.sources = [
    { id: 'capture', label: 'Capture', value: 612 },
    { id: 'risk', label: 'Risk', value: 212, stubLabel: '212 contrats ○' },
  ];
  flow.ngOnChanges({ sources: {} as never });
  const value = flow.ribbons.find((ribbon) => ribbon.kind === 'value');
  assert.equal(value?.declared, true);
  assert.ok(flow.ribbons.filter((ribbon) => ribbon.kind === 'runs').every((ribbon) => !ribbon.declared));
  const declaredNodes = flow.nodes.filter((node) => node.declared);
  assert.deepEqual(declaredNodes.map((node) => node.role), ['value']);
  assert.equal(flow.hatchFill, `url(#${flow.hatchId})`);
  assert.equal(flow.nodeDash, CK_DECLARED_DASH_THIN);

  const template = source('sankey-flow.component.ts');
  assert.match(template, /<pattern\s+\[attr\.id\]="hatchId"/);
  assert.match(template, /@if \(ribbon\.declared\) \{\s*<path\s+class="ck-ribbon ck-ribbon-hatch"[\s\S]*?\[attr\.fill\]="hatchFill"/);
  assert.match(template, /@if \(node\.declared\) \{[\s\S]*?class="ck-node ck-node-dash"[\s\S]*?\[attr\.stroke-dasharray\]="nodeDash"/);
});

test('mini-area and unit dots: declared sparks are dashed and declared dots draw ◐', () => {
  const spark = make(CkChartMiniAreaComponent);
  spark.tone = 'declared';
  assert.equal(spark.lineDash, CK_DECLARED_DASH_THIN);
  spark.tone = 'ink';
  assert.equal(spark.lineDash, null);
  assert.match(source('mini-area.component.ts'), /\[attr\.stroke-dasharray\]="lineDash"/);

  const dots = make(CkChartUnitDotsComponent);
  dots.tone = 'declared';
  dots.dotSize = 6;
  assert.equal(dots.declared, true);
  assert.equal(dots.halfDisc({ x: 3, y: 3 }), 'M3,0A3,3 0 0 0 3,6Z', 'the left half of the dot is filled');
  dots.tone = 'ink';
  assert.equal(dots.declared, false);
});
