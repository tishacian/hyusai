import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  Injector,
  ɵChangeDetectionScheduler as ChangeDetectionScheduler,
  ɵEffectScheduler as EffectScheduler,
} from '@angular/core';
import { Subject, of } from 'rxjs';
import {
  CanonicalApiService,
  type Capability,
  type Run,
  type Skill,
  type System,
} from '@app/core/canonical-api.service';
import { ChatOverlayService } from '@app/features/chat/chat-overlay.service';
import { I18nService } from '@app/core/i18n.service';
import {
  WorkspaceService,
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { Router } from '@angular/router';
import { CommandPaletteComponent } from './command-palette.component';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { navigationObjectUrl } from '@app/core/navigation.catalog';

class WorkspaceStub {
  private slug = 'andritz';
  private epoch = 1;
  private readonly resetters = new Set<(transition: WorkspaceContextTransition) => void>();

  currentSlug = () => this.slug;
  contextEpoch = () => this.epoch;
  current = () => ({ settings: {} });
  experienceV1Enabled = () => false;
  experienceStudioV1Enabled = () => false;

  captureRequestScope(): WorkspaceRequestScope {
    return Object.freeze({ workspaceSlug: this.slug, workspaceId: `workspace-${this.slug}`, epoch: this.epoch });
  }

  isRequestScopeCurrent(scope: WorkspaceRequestScope): boolean {
    return scope.workspaceSlug === this.slug && scope.epoch === this.epoch;
  }

  registerContextReset(resetter: (transition: WorkspaceContextTransition) => void): () => void {
    this.resetters.add(resetter);
    return () => this.resetters.delete(resetter);
  }

  refreshCurrentWorkspace() {
    return of(null);
  }

  switchWorkspace(): void {
    const transition: WorkspaceContextTransition = {
      previousSlug: this.slug,
      nextSlug: 'sentinel-ci',
      previousEpoch: this.epoch,
      nextEpoch: this.epoch + 1,
    };
    for (const resetter of [...this.resetters]) resetter(transition);
    this.slug = transition.nextSlug;
    this.epoch = transition.nextEpoch;
  }
}

class CanonicalStub {
  readonly capabilities: Array<Subject<Capability[]>> = [];
  readonly runs: Array<Subject<Run[]>> = [];
  readonly skills: Array<Subject<Skill[]>> = [];
  readonly systems: Array<Subject<System[]>> = [];

  listCapabilities() {
    const subject = new Subject<Capability[]>();
    this.capabilities.push(subject);
    return subject.asObservable();
  }

  listSkills() {
    const subject = new Subject<Skill[]>();
    this.skills.push(subject);
    return subject.asObservable();
  }

  listRuns() {
    const subject = new Subject<Run[]>();
    this.runs.push(subject);
    return subject.asObservable();
  }

  listSystems() {
    const subject = new Subject<System[]>();
    this.systems.push(subject);
    return subject.asObservable();
  }
}

test('command palette drops A index and rejects an old dynamic command after A→B', async () => {
  const workspace = new WorkspaceStub();
  const canonical = new CanonicalStub();
  const navigations: string[] = [];
  const injector = Injector.create({
    providers: [
      CommandPaletteComponent,
      { provide: WorkspaceService, useValue: workspace },
      { provide: CanonicalApiService, useValue: canonical },
      { provide: ChatOverlayService, useValue: { open: () => undefined } },
      { provide: Router, useValue: { navigateByUrl: (url: string) => navigations.push(url) } },
      {
        provide: ZoomContextService,
        useValue: { objectUrl: navigationObjectUrl },
      },
      { provide: I18nService, useValue: { t: (key: string) => key } },
      {
        provide: ChangeDetectionScheduler,
        useValue: { notify() {}, runningTick: false },
      },
      {
        provide: EffectScheduler,
        useValue: { add() {}, schedule() {}, flush() {}, remove() {} },
      },
    ],
  });
  const palette = injector.get(CommandPaletteComponent);
  palette.ngOnInit();
  canonical.capabilities[0].next([]);
  canonical.runs[0].next([{
    id: 'run-a',
    system_id: 'system-a',
    status: 'completed',
  }]);
  canonical.skills[0].next([]);
  canonical.systems[0].next([{
    id: 'system-a',
    name: 'Andritz private system',
    status: 'active',
  } as System]);
  const staleCommand = palette.results().find((item) => item.id === 'sys.system-a');
  assert.ok(staleCommand);

  workspace.switchWorkspace();
  assert.equal(palette.results().some((item) => item.id === 'sys.system-a'), false);
  assert.equal(palette.results().some((item) => item.id === 'run.run-a'), false);
  palette.go(staleCommand);
  assert.deepEqual(navigations, [], 'an A command cannot navigate after epoch B is active');

  await Promise.resolve();
  assert.equal(canonical.systems.length, 2, 'the palette reloads for workspace B');
  canonical.capabilities[1].next([{
    id: 'cap-b',
    slug: 'capability-b',
    name: 'Capability B',
  }]);
  canonical.runs[1].next([{
    id: 'run-b',
    system_id: 'system-b',
    capability_id: 'cap-b',
    status: 'running',
  }]);
  canonical.skills[1].next([{
    id: 'skill-b-id',
    slug: 'skill-b',
    name: 'Skill B',
  }]);
  canonical.systems[1].next([{
    id: 'system-b',
    name: 'Sentinel system',
    status: 'active',
  } as System]);
  assert.equal(palette.results().some((item) => item.id === 'sys.system-a'), false);
  assert.equal(palette.results().some((item) => item.id === 'sys.system-b'), true);
  assert.equal(
    palette.results().find((item) => item.id === 'cap.cap-b')?.route,
    '/capabilities/cap-b',
  );
  assert.equal(
    palette.results().find((item) => item.id === 'sk.skill-b-id')?.route,
    '/skills/skill-b',
  );
  assert.equal(
    palette.results().find((item) => item.id === 'run.run-b')?.route,
    '/runs/run-b',
  );

  palette.ngOnDestroy();
});

test('Thème Présentation opens /hypervisor?theme=presentation', () => {
  const workspace = new WorkspaceStub();
  const canonical = new CanonicalStub();
  const navigations: string[] = [];
  const injector = Injector.create({
    providers: [
      CommandPaletteComponent,
      { provide: WorkspaceService, useValue: workspace },
      { provide: CanonicalApiService, useValue: canonical },
      { provide: ChatOverlayService, useValue: { open: () => undefined } },
      { provide: Router, useValue: { navigateByUrl: (url: string) => navigations.push(url) } },
      {
        provide: ZoomContextService,
        useValue: { objectUrl: navigationObjectUrl },
      },
      { provide: I18nService, useValue: { t: (key: string) => key } },
      {
        provide: ChangeDetectionScheduler,
        useValue: { notify() {}, runningTick: false },
      },
      {
        provide: EffectScheduler,
        useValue: { add() {}, schedule() {}, flush() {}, remove() {} },
      },
    ],
  });
  const palette = injector.get(CommandPaletteComponent);
  palette.ngOnInit();
  canonical.capabilities[0].next([]);
  canonical.runs[0].next([]);
  canonical.skills[0].next([]);
  canonical.systems[0].next([]);

  palette.query.set('presentation');
  const command = palette.results().find((item) => item.id === 'theme.presentation');
  assert.ok(command);
  assert.equal(command.route, '/hypervisor?theme=presentation');
  palette.go(command);
  assert.deepEqual(navigations, ['/hypervisor?theme=presentation']);
  palette.ngOnDestroy();
});

function paletteWithChat(opens: unknown[]) {
  const workspace = new WorkspaceStub();
  const canonical = new CanonicalStub();
  const navigations: string[] = [];
  const injector = Injector.create({
    providers: [
      CommandPaletteComponent,
      { provide: WorkspaceService, useValue: workspace },
      { provide: CanonicalApiService, useValue: canonical },
      { provide: ChatOverlayService, useValue: { open: (options: unknown) => opens.push(options) } },
      { provide: Router, useValue: { navigateByUrl: (url: string) => navigations.push(url) } },
      { provide: ZoomContextService, useValue: { objectUrl: navigationObjectUrl } },
      {
        provide: I18nService,
        useValue: {
          locale: () => 'fr',
          t: (key: string, params?: Record<string, unknown>) =>
            params ? `${key}|${JSON.stringify(params)}` : key,
        },
      },
      { provide: ChangeDetectionScheduler, useValue: { notify() {}, runningTick: false } },
      { provide: EffectScheduler, useValue: { add() {}, schedule() {}, flush() {}, remove() {} } },
    ],
  });
  const palette = injector.get(CommandPaletteComponent);
  palette.ngOnInit();
  canonical.capabilities[0].next([]);
  canonical.runs[0].next([]);
  canonical.skills[0].next([]);
  canonical.systems[0].next([]);
  return { palette, navigations };
}

const enter = { key: 'Enter', preventDefault() {} } as KeyboardEvent;

test('L27 — a query with no match offers « Ask the agent » first; Enter prefills the chat', () => {
  const opens: unknown[] = [];
  const { palette, navigations } = paletteWithChat(opens);
  palette.query.set('  quels runs ont échoué hier  ');

  const [ask, ...rest] = palette.results();
  assert.equal(ask.id, 'agent.ask');
  assert.equal(ask.kind, 'agent');
  assert.equal(ask.label, 'palette.ask_agent|{"query":"quels runs ont échoué hier"}');
  assert.equal(rest.some((row) => row.id === 'agent.ask'), false, 'one agent row only');
  assert.equal(palette.selectedIndex(), 0, 'selected by default');
  assert.equal(palette.noMatch(), true);
  assert.equal(palette.activeDescendant(), 'ck-palette-option-0');
  assert.equal(palette.announcement(), 'palette.announce.fallback');

  palette.onKey(enter);
  assert.deepEqual(opens, [{ mode: 'quick', initialPrompt: 'quels runs ont échoué hier' }]);
  assert.deepEqual(navigations, []);
  assert.equal(palette.open(), false, 'the palette closes');
  palette.ngOnDestroy();
});

test('L27 — a lexicon term shows « Qu’est-ce que … ? » with its definition in place', () => {
  const opens: unknown[] = [];
  const { palette } = paletteWithChat(opens);
  palette.query.set('draft');
  const define = palette.results().find((row) => row.id === 'define.draft');
  assert.ok(define, 'the definition row is listed');
  assert.equal(define.kind, 'definition');
  assert.equal(define.label, 'palette.what_is|{"term":"Brouillon"}');
  assert.match(define.hint, /brouillon|version/i, 'the secondary line is the lexicon definition');

  palette.go(define);
  assert.deepEqual(opens, [{
    mode: 'quick',
    initialPrompt: 'palette.what_is.prompt|{"term":"Brouillon"}',
  }]);

  palette.query.set('exécution');
  const run = palette.results().find((row) => row.id === 'define.run');
  assert.equal(run?.label, 'palette.what_is.elided|{"term":"Exécution"}', 'French elision');
  palette.ngOnDestroy();
});

test('L27 — matching commands keep Enter; definitions follow them', () => {
  const { palette, navigations } = paletteWithChat([]);
  palette.query.set('skill');
  const rows = palette.results();
  assert.equal(rows[0].id, 'view.skills');
  assert.equal(rows.at(-1)?.id, 'define.skill');
  assert.equal(rows.some((row) => row.id === 'agent.ask'), false);
  assert.equal(palette.noMatch(), false);
  assert.equal(palette.announcement(), `palette.footer.results|{"count":${rows.length}}`);
  palette.onKey(enter);
  assert.deepEqual(navigations, ['/skills']);
  palette.ngOnDestroy();
});
