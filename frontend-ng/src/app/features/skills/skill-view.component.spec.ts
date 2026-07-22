import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { ActivatedRoute, convertToParamMap } from '@angular/router';
import { BehaviorSubject, Subject } from 'rxjs';
import { CanonicalApiService, type Skill } from '@app/core/canonical-api.service';
import { LensService } from '@app/core/lens';
import {
  WorkspaceService,
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { SkillViewComponent } from './skill-view.component';

class WorkspaceStub {
  private slug = 'workspace-a';
  private epoch = 1;
  private readonly resetters = new Set<(transition: WorkspaceContextTransition) => void>();

  readonly currentSlug = () => this.slug;
  readonly contextEpoch = () => this.epoch;

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

test('Skill view purges A synchronously and only accepts the B reload', async () => {
  const params = new BehaviorSubject(convertToParamMap({ skillId: 'shared-skill' }));
  const workspace = new WorkspaceStub();
  const reads: Array<Subject<Skill | null>> = [];
  const canonical = {
    getSkill: () => {
      const response = new Subject<Skill | null>();
      reads.push(response);
      return response;
    },
  };
  const injector = Injector.create({
    providers: [
      SkillViewComponent,
      {
        provide: ActivatedRoute,
        useValue: {
          paramMap: params.asObservable(),
          snapshot: { paramMap: params.value },
        },
      },
      { provide: CanonicalApiService, useValue: canonical },
      { provide: WorkspaceService, useValue: workspace },
      { provide: LensService, useValue: { lens: () => 'build' } },
    ],
  });
  const view = injector.get(SkillViewComponent);
  view.ngOnInit();
  reads[0].next({ id: 'skill-a', slug: 'shared-skill', name: 'Skill A' });
  assert.equal(view.skill()?.name, 'Skill A');
  view.activeTab.set('spec');
  view.specPanelOpen.set(true);

  workspace.switchWorkspace();
  assert.equal(view.skill(), null, 'A is removed before B becomes current');
  assert.equal(view.activeTab(), 'overview');
  assert.equal(view.specPanelOpen(), false);

  await Promise.resolve();
  assert.equal(reads.length, 2);
  reads[0].next({ id: 'late-a', slug: 'shared-skill', name: 'Late Skill A' });
  reads[1].next({ id: 'skill-b', slug: 'shared-skill', name: 'Skill B' });
  assert.equal(view.skill()?.name, 'Skill B');

  view.ngOnDestroy();
});
