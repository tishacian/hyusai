import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { BehaviorSubject, Subject } from 'rxjs';
import { CanonicalApiService, type Skill } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { LensService } from '@app/core/lens';
import { ZoomContextService } from '@app/core/zoom-context.service';
import {
  WorkspaceService,
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { SkillViewComponent } from './skill-view.component';
import { formatSkillCost, observedSkillCost } from './skill-cost';

test('Skill costs distinguish missing, zero and positive amounts below display precision', () => {
  for (const value of [null, undefined, NaN, Infinity, -0.01]) {
    assert.equal(formatSkillCost(value), '—');
  }
  assert.equal(formatSkillCost(0), '$0.00');
  assert.equal(formatSkillCost(-0), '$0.00');
  assert.equal(formatSkillCost(Number.MIN_VALUE), '< $0.0001');
  assert.equal(formatSkillCost(0.000001), '< $0.0001');
  assert.equal(formatSkillCost(0.000099), '< $0.0001');
  assert.equal(formatSkillCost(0.0001), '$0.0001');
  assert.equal(formatSkillCost(0.0008), '$0.0008');
  assert.equal(formatSkillCost(0.012), '$0.012');
  assert.equal(formatSkillCost(125.25), '$125.25');
  assert.equal(formatSkillCost(0.000001, 'EUR'), '< €0.0001');
  assert.equal(formatSkillCost(2, 'EUR'), '€2.00');
  assert.equal(formatSkillCost(2, null), '—');
  assert.equal(formatSkillCost(2, 'invalid'), '—');
  assert.equal(formatSkillCost(2, 42 as unknown as string), '—');
});

test('Observed Skill costs never substitute a catalog price or unmeasured default', () => {
  assert.equal(observedSkillCost(undefined), null);
  assert.equal(observedSkillCost({}), null);
  assert.equal(observedSkillCost({ calls: 0, total_cost: 0 }), null);
  assert.equal(observedSkillCost({ calls: 1, total_cost: 0, cost_state: 'not_measured' }), null);
  assert.equal(observedSkillCost({ calls: 1, total_cost: null }), null);
  assert.equal(observedSkillCost({ calls: 1, total_cost: 0, cost_state: 'available' }), 0);
  assert.equal(observedSkillCost({ calls: 1, total_cost: 0.000001 }), 0.000001);
});

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
          snapshot: { paramMap: params.value, queryParamMap: convertToParamMap({}) },
        },
      },
      { provide: Router, useValue: { navigate: () => Promise.resolve(true) } },
      { provide: CanonicalApiService, useValue: canonical },
      { provide: WorkspaceService, useValue: workspace },
      { provide: LensService, useValue: { lens: () => 'build' } },
      { provide: I18nService, useValue: { locale: () => 'fr', t: (key: string) => key } },
      { provide: ZoomContextService, useValue: { navV5Enabled: () => false, zoneI18nKey: () => 'nav.build.create' } },
    ],
  });
  const view = injector.get(SkillViewComponent);
  view.ngOnInit();
  const skill = { id: 'skill-a', slug: 'shared-skill', name: 'Skill A', pricing: { unit: 'per_call', unit_price: 0, currency: 'USD' } };
  reads[0].next(skill);
  assert.equal(view.skill()?.name, 'Skill A');
  const observedCost = () => view.kpis().find(kpi => kpi.label === 'skills.cost.observed')?.value;
  assert.equal(observedCost(), 'skills.cost.not_measured', 'a default zero tariff is not an observed invocation cost');
  reads[0].next({ ...skill, metrics: { calls: 1, total_cost: 0 } });
  assert.equal(observedCost(), '$0.00');
  reads[0].next({ ...skill, metrics: { calls: 1, total_cost: 0.000001 } });
  assert.equal(observedCost(), '< $0.0001');
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
