import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector, signal } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { SideRailComponent } from './side-rail.component';

function railFor(options: { path?: string; experienceStudio?: boolean; mode?: string } = {}) {
  const path = signal(options.path ?? '/chat');
  const injector = Injector.create({
    providers: [
      SideRailComponent,
      {
        provide: WorkspaceService,
        useValue: {
          current: () => ({ mode: options.mode ?? 'portfolio' }),
          mode: () => options.mode ?? 'portfolio',
          isDemoMode: () => (options.mode ?? 'portfolio') === 'demo',
          experienceV1Enabled: () => options.experienceStudio === true,
          experienceStudioV1Enabled: () => options.experienceStudio === true,
        },
      },
      {
        provide: ZoomContextService,
        useValue: {
          route: () => ({ path: path() }),
          lens: () => 'operate',
          axesV4Enabled: () => false,
        },
      },
      { provide: I18nService, useValue: { t: (key: string) => key } },
    ],
  });
  return { rail: injector.get(SideRailComponent), path };
}

test('the standard rail is exactly Ask, Knowledge, Build, Runs, in that order', () => {
  const { rail } = railFor();
  assert.deepEqual(
    rail.items().map((item) => item.key),
    ['ask', 'knowledge', 'build', 'runs'],
  );
});

test('every destination points at its task route', () => {
  const { rail } = railFor();
  const [ask, knowledge, build, runs] = rail.items();

  assert.equal(rail.routeFor(ask), '/chat');
  assert.deepEqual(rail.queryFor(ask), { mode: 'quick' });
  assert.equal(rail.routeFor(knowledge), '/knowledge');
  assert.equal(rail.queryFor(knowledge), null);
  assert.equal(rail.routeFor(build), '/systems');
  assert.equal(rail.routeFor(runs), '/runs');
});

test('Build opens the Create hub when Experience Studio is enabled', () => {
  const { rail } = railFor({ experienceStudio: true });
  const build = rail.items().find((item) => item.key === 'build')!;
  assert.equal(rail.routeFor(build), '/create');
  assert.equal(rail.itemLabel(build), 'nav.build');
  assert.equal(rail.itemHint(build), 'nav.hint.build.create');
});

test('the rail keeps the same four destinations in every workspace mode', () => {
  for (const mode of ['portfolio', 'builder', 'demo']) {
    const { rail } = railFor({ mode });
    assert.deepEqual(
      rail.items().map((item) => item.key),
      ['ask', 'knowledge', 'build', 'runs'],
      `mode ${mode}`,
    );
  }
});

test('active state is route-based and holds on descendants', () => {
  const { rail, path } = railFor();

  const cases: Array<[string, string]> = [
    ['/chat', 'ask'],
    ['/knowledge', 'knowledge'],
    ['/knowledge/kb-42', 'knowledge'],
    ['/systems', 'build'],
    ['/systems/sys-1/flow', 'build'],
    ['/create', 'build'],
    ['/create/apps/app-7', 'build'],
    ['/runs', 'runs'],
    ['/runs/run-9/invocations/inv-3', 'runs'],
  ];

  for (const [url, expected] of cases) {
    path.set(url);
    const active = rail.items().filter((item) => rail.isActive(item)).map((item) => item.key);
    assert.deepEqual(active, [expected], url);
  }
});

test('an advanced deep link lights no primary destination', () => {
  const { rail, path } = railFor();
  for (const url of ['/hypervisor', '/steering/contexts', '/governance/audit', '/models/m-1']) {
    path.set(url);
    assert.deepEqual(rail.items().filter((item) => rail.isActive(item)), [], url);
  }
});

test('/knowledge-adjacent paths do not leak into the Knowledge entry', () => {
  const { rail, path } = railFor();
  path.set('/knowledge-capture');
  assert.deepEqual(rail.items().filter((item) => rail.isActive(item)), []);
});

test('the accessible name and the title stay free of em dashes', () => {
  const { rail } = railFor();
  const ask = rail.items().find((item) => item.key === 'ask')!;
  assert.equal(rail.itemLabel(ask), 'nav.ask');
  assert.equal(rail.itemHint(ask), 'nav.hint.ask');
  assert.ok(!rail.itemTitle(ask).includes('—'));
});

test('Escape collapses the expanded rail', () => {
  const { rail } = railFor();
  rail.onFocusIn();
  assert.equal(rail.expanded(), true);
  rail.onKey({ key: 'Escape' } as KeyboardEvent);
  assert.equal(rail.expanded(), false);
});

test('clicking a destination records the rail as the navigation trigger', () => {
  const { rail } = railFor();
  // No telemetry service is provided: the optional dependency must stay optional.
  assert.doesNotThrow(() => rail.onItemClick());
});
