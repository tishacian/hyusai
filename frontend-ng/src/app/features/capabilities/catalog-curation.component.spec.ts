import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { Subject } from 'rxjs';
import {
  WorkspaceService,
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { CatalogCurationComponent } from './catalog-curation.component';
import {
  CatalogCurationApi,
  type CatalogCurationReport,
  type CatalogPolicy,
  type CatalogPolicyPatch,
} from './catalog-curation.api';

class WorkspaceStub {
  private slug = 'andritz';
  private epoch = 1;
  private readonly resetters = new Set<(transition: WorkspaceContextTransition) => void>();

  readonly currentSlug = () => this.slug;
  readonly contextEpoch = () => this.epoch;
  readonly isBuilderMode = () => false;

  captureRequestScope(): WorkspaceRequestScope {
    return Object.freeze({ workspaceSlug: this.slug, workspaceId: `ws-${this.slug}`, epoch: this.epoch });
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
      nextSlug: 'sentinel-ci',
      previousEpoch: this.epoch,
      nextEpoch: this.epoch + 1,
    };
    for (const resetter of [...this.resetters]) resetter(transition);
    this.slug = transition.nextSlug;
    this.epoch = transition.nextEpoch;
  }
}

class ApiStub {
  readonly reports: Array<Subject<CatalogCurationReport>> = [];
  readonly patches: CatalogPolicyPatch[] = [];
  readonly writes: Array<Subject<CatalogCurationReport>> = [];

  report() {
    const response = new Subject<CatalogCurationReport>();
    this.reports.push(response);
    return response;
  }

  update(patch: CatalogPolicyPatch) {
    this.patches.push(patch);
    const response = new Subject<CatalogCurationReport>();
    this.writes.push(response);
    return response;
  }
}

const POLICY: CatalogPolicy = {
  show_universal: true,
  show_unconfigured_industries: false,
  allowed_industries: ['manufacturing'],
  enabled_capabilities: [],
  hidden_capabilities: ['expert_capture'],
  enabled_skills: ['rpa_dispatch_v1'],
  hidden_skills: [],
  allowed_industries_source: 'inferred',
};

function report(overrides: Partial<CatalogCurationReport> = {}): CatalogCurationReport {
  return {
    summary: {
      total: 85,
      visible: 28,
      filtered: 57,
      filtered_reasons: { industry_not_allowed: 45, unclaimed: 12 },
    },
    policy: POLICY,
    categories: [{ category: 'Analysis', total: 10, visible: 4 }],
    gaps: [
      {
        lever: 'industry',
        key: 'government',
        skills: 36,
        skill_slugs: ['mission_command_v1'],
        capabilities: ['aya_voice'],
      },
      { lever: 'unclaimed', key: '', skills: 12, skill_slugs: ['causal_drill_v1'], capabilities: [] },
    ],
    overrides: [
      {
        kind: 'enabled',
        entry: 'rpa_dispatch_v1',
        slug: 'rpa_dispatch_v1',
        name: 'RPA dispatch',
        status: 'effective',
        source: 'app:rpa_bridge',
      },
    ],
    skills: [
      {
        slug: 'expert_answer_v1',
        name: 'Expert answer',
        category: 'Analysis',
        visible: true,
        reason: 'capability',
        capabilities: ['expert_capture'],
        carriers: ['expert_capture'],
      },
      {
        slug: 'causal_drill_v1',
        name: 'Causal drill',
        category: 'Analysis',
        visible: false,
        reason: 'unclaimed',
        capabilities: [],
        carriers: [],
      },
    ],
    capabilities: [],
    editable: true,
    ...overrides,
  };
}

function build() {
  const workspace = new WorkspaceStub();
  const api = new ApiStub();
  const injector = Injector.create({
    providers: [
      CatalogCurationComponent,
      { provide: CatalogCurationApi, useValue: api },
      { provide: WorkspaceService, useValue: workspace },
    ],
  });
  return { view: injector.get(CatalogCurationComponent), api, workspace };
}

test('a coverage gap is applied as the tier decision it is, not as 36 toggles', () => {
  const { view, api } = build();
  view.ngOnInit();
  api.reports[0].next(report());

  view.applyGap(view.report()!.gaps[0]);

  assert.deepEqual(api.patches[0], { allowed_industries: ['manufacturing', 'government'] });
  assert.equal(view.saving(), true);

  // The server's recomputed coverage replaces the local view wholesale.
  api.writes[0].next(report({ summary: { total: 85, visible: 64, filtered: 21, filtered_reasons: {} }, gaps: [] }));
  assert.equal(view.report()!.summary.visible, 64);
  assert.equal(view.saving(), false);
  view.ngOnDestroy();
});

test('the unclaimed group is the only gap that enables skills one by one', () => {
  const { view, api } = build();
  view.ngOnInit();
  api.reports[0].next(report());

  view.applyGap(view.report()!.gaps[1]);

  assert.deepEqual(api.patches[0], { enabled_skills: ['rpa_dispatch_v1', 'causal_drill_v1'] });
  view.ngOnDestroy();
});

test('enabling a hidden capability also lifts the hide that outranks it', () => {
  const { view, api } = build();
  view.ngOnInit();
  api.reports[0].next(report({
    gaps: [{
      lever: 'capability',
      key: 'expert_capture',
      skills: 4,
      skill_slugs: ['expert_answer_v1'],
      capabilities: ['expert_capture'],
    }],
  }));

  view.applyGap(view.report()!.gaps[0]);

  // ``hidden_capabilities`` wins over ``enabled_capabilities`` server-side, so
  // enabling alone would look like a button that does nothing.
  assert.deepEqual(api.patches[0], {
    enabled_capabilities: ['expert_capture'],
    hidden_capabilities: [],
  });
  view.ngOnDestroy();
});

test('an app-written override is attributed to its app and cannot be removed here', () => {
  const { view, api } = build();
  view.ngOnInit();
  api.reports[0].next(report());
  const override = view.report()!.overrides[0];

  assert.equal(view.appOverrides().length, 1);
  assert.equal(view.sourceLabel(override), 'app · rpa_bridge');
  view.removeOverride(override);
  assert.deepEqual(api.patches, [], 'removal must go through the Apps screen');
  view.ngOnDestroy();
});

test('hiding a visible skill and enabling a filtered one write opposite levers', () => {
  const { view, api } = build();
  view.ngOnInit();
  api.reports[0].next(report());
  const [visible, filtered] = view.report()!.skills;

  view.toggleSkill(visible);
  assert.deepEqual(api.patches[0], { hidden_skills: ['expert_answer_v1'] });

  view.toggleSkill(filtered);
  assert.deepEqual(api.patches[1], {
    enabled_skills: ['rpa_dispatch_v1', 'causal_drill_v1'],
    hidden_skills: [],
  });
  view.ngOnDestroy();
});

test('the escape-hatch list stays closed until searched', () => {
  const { view, api } = build();
  view.ngOnInit();
  api.reports[0].next(report());

  assert.deepEqual(view.matches(), [], 'an unfiltered registry would read as an inventory');
  view.query.set('causal');
  assert.deepEqual(view.matches().map((skill) => skill.slug), ['causal_drill_v1']);
  view.ngOnDestroy();
});

test('a failed write leaves the displayed policy untouched and says so', () => {
  const { view, api } = build();
  view.ngOnInit();
  api.reports[0].next(report());

  view.applyGap(view.report()!.gaps[0]);
  api.writes[0].error(new Error('403'));

  assert.equal(view.saving(), false);
  assert.match(view.error()!, /nothing was changed/);
  assert.deepEqual(view.report()!.policy.allowed_industries, ['manufacturing']);
  view.ngOnDestroy();
});

test('switching workspace purges the coverage and reloads for the new one', async () => {
  const { view, api, workspace } = build();
  view.ngOnInit();
  api.reports[0].next(report());

  workspace.switchWorkspace();
  assert.equal(view.report(), null);
  assert.equal(view.loading(), true);

  await Promise.resolve();
  assert.equal(api.reports.length, 2);
  api.reports[1].next(report({ summary: { total: 85, visible: 64, filtered: 21, filtered_reasons: {} } }));
  assert.equal(view.report()!.summary.visible, 64);

  // A late response from the abandoned workspace must not repaint the screen.
  api.reports[0].next(report());
  assert.equal(view.report()!.summary.visible, 64);
  view.ngOnDestroy();
});

test('a read-only member sees the report without write affordances', () => {
  const { view, api } = build();
  view.ngOnInit();
  api.reports[0].next(report({ editable: false }));

  assert.equal(view.report()!.editable, false);
  assert.equal(view.coveragePercent(), '33');
  view.ngOnDestroy();
});
