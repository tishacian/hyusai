import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { BehaviorSubject, Subject } from 'rxjs';
import {
  CanonicalApiService,
  type Capability,
  type Run,
  type Skill,
} from '@app/core/canonical-api.service';
import {
  WorkspaceService,
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { CapabilitiesComponent } from './capabilities.component';

class WorkspaceStub {
  private slug = 'workspace-a';
  private epoch = 1;
  private readonly resetters = new Set<(transition: WorkspaceContextTransition) => void>();

  readonly currentSlug = () => this.slug;
  readonly contextEpoch = () => this.epoch;
  readonly isBuilderMode = () => false;

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

  switchWorkspace(): void {
    const transition: WorkspaceContextTransition = {
      previousSlug: this.slug,
      nextSlug: 'workspace-b',
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
  readonly skills: Array<Subject<Skill[]>> = [];
  readonly runs: Array<Subject<Run[]>> = [];

  listCapabilities() {
    const response = new Subject<Capability[]>();
    this.capabilities.push(response);
    return response;
  }

  listSkills() {
    const response = new Subject<Skill[]>();
    this.skills.push(response);
    return response;
  }

  listRuns() {
    const response = new Subject<Run[]>();
    this.runs.push(response);
    return response;
  }
}

function completeCatalog(
  canonical: CanonicalStub,
  index: number,
  capabilities: Capability[],
  skills: Skill[] = [],
): void {
  canonical.capabilities[index].next(capabilities);
  canonical.capabilities[index].complete();
  canonical.skills[index].next(skills);
  canonical.skills[index].complete();
}

test('Capabilities purges A, reloads B and follows focus across browser history', async () => {
  const query = new BehaviorSubject(convertToParamMap({ focus: 'cap-shared' }));
  const workspace = new WorkspaceStub();
  const canonical = new CanonicalStub();
  const routedQueries: Array<Record<string, string | null>> = [];
  const injector = Injector.create({
    providers: [
      CapabilitiesComponent,
      {
        provide: ActivatedRoute,
        useValue: {
          queryParamMap: query.asObservable(),
          snapshot: { queryParamMap: query.value },
        },
      },
      { provide: CanonicalApiService, useValue: canonical },
      { provide: WorkspaceService, useValue: workspace },
      { provide: ZoomContextService, useValue: { objectUrlTree: () => ({}) } },
      {
        provide: Router,
        useValue: {
          navigate: (
            _commands: unknown[],
            options: { queryParams: Record<string, string | null> },
          ) => {
            routedQueries.push(options.queryParams);
            query.next(convertToParamMap(
              options.queryParams.focus ? { focus: options.queryParams.focus } : {},
            ));
            return Promise.resolve(true);
          },
        },
      },
    ],
  });
  const view = injector.get(CapabilitiesComponent);
  view.ngOnInit();
  completeCatalog(canonical, 0, [{
    id: 'cap-shared',
    slug: 'shared',
    name: 'Capability A',
  }]);
  assert.equal(view.selected()?.name, 'Capability A');
  canonical.runs[0].next([{
    id: 'run-a',
    system_id: 'system-a',
    status: 'completed',
  }]);
  assert.equal(view.latestRun()?.id, 'run-a');

  workspace.switchWorkspace();
  assert.deepEqual(view.capabilities(), []);
  assert.deepEqual(view.skills(), []);
  assert.equal(view.selected(), null);
  assert.equal(view.latestRun(), null);
  assert.equal(view.loading(), true);

  await Promise.resolve();
  assert.equal(canonical.capabilities.length, 2);
  completeCatalog(canonical, 1, [
    { id: 'cap-shared', slug: 'shared', name: 'Capability B' },
    { id: 'cap-other', slug: 'other', name: 'Other B Capability' },
  ]);
  assert.equal(view.selected()?.name, 'Capability B');
  canonical.runs[0].next([{
    id: 'late-run-a',
    system_id: 'system-a',
    status: 'completed',
  }]);
  canonical.runs[1].next([{
    id: 'run-b',
    system_id: 'system-b',
    status: 'completed',
  }]);
  assert.equal(view.latestRun()?.id, 'run-b');

  query.next(convertToParamMap({ focus: 'cap-other' }));
  assert.equal(view.selected()?.id, 'cap-other');
  canonical.runs[2].next([{
    id: 'run-other-b',
    system_id: 'system-other-b',
    status: 'completed',
  }]);
  assert.equal(view.latestRun()?.id, 'run-other-b');

  query.next(convertToParamMap({ focus: 'cap-shared' }));
  assert.equal(view.selected()?.name, 'Capability B');

  view.selectCapability(null);
  assert.equal(view.selected(), null, 'closing the drill-down removes routed focus');
  view.selectCapability(view.capabilities().find((item) => item.id === 'cap-other')!);
  assert.equal(view.selected()?.id, 'cap-other', 'card clicks are projected back from Router focus');
  assert.deepEqual(routedQueries.at(-1), {
    focus: 'cap-other',
    scope: null,
    capabilityId: null,
    systemId: null,
    runId: null,
    skillRef: null,
  });

  view.ngOnDestroy();
});
