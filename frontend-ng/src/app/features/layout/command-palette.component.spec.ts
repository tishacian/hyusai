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

  captureRequestScope(): WorkspaceRequestScope {
    return Object.freeze({ workspaceSlug: this.slug, epoch: this.epoch });
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
