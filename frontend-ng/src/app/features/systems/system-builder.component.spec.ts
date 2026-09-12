import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector, signal } from '@angular/core';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { of } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
import {
  CanonicalApiService,
  type Capability,
  type Skill,
} from '@app/core/canonical-api.service';
import { FlowSerializerService } from '@app/core/flow-serializer.service';
import { RuntimeHealthService } from '@app/core/runtime-health.service';
import { SettingsService } from '@app/core/settings.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { SystemBuilderComponent } from './system-builder.component';
import { SystemsStore } from './systems.store';

function makeBuilder(): SystemBuilderComponent {
  const injector = Injector.create({
    providers: [
      SystemBuilderComponent,
      { provide: Router, useValue: { navigateByUrl: () => Promise.resolve(true) } },
      {
        provide: ActivatedRoute,
        useValue: { snapshot: { queryParamMap: convertToParamMap({}) } },
      },
      { provide: ZoomContextService, useValue: {} },
      { provide: ApiService, useValue: { get: () => of({}) } },
      { provide: CanonicalApiService, useValue: {} },
      { provide: RuntimeHealthService, useValue: {} },
      { provide: ToastrService, useValue: {} },
      { provide: SystemsStore, useValue: {} },
      { provide: FlowSerializerService, useValue: {} },
      {
        provide: WorkspaceService,
        useValue: { isDemoSafeMode: () => false, currentSlug: () => 'demo' },
      },
      { provide: SettingsService, useValue: { settings: signal({}) } },
    ],
  });
  return injector.get(SystemBuilderComponent);
}

test('selecting a capability refreshes its summary and bundled skills', () => {
  const builder = makeBuilder();
  const capability: Capability = {
    id: 'cap-qna',
    slug: 'intelligent-qna',
    name: 'Intelligent Q&A',
    tier: 'universal',
    skill_ids: ['skill-retrieve', 'skill-answer'],
  };
  const skills: Skill[] = [
    { id: 'skill-retrieve', slug: 'retrieve', name: 'Retrieve' },
    { id: 'skill-answer', slug: 'answer', name: 'Answer' },
  ];

  builder.capabilities.set([capability]);
  builder.skills.set(skills);
  assert.equal(builder.selectedCapability(), null);

  builder.selectCapability(capability);

  assert.equal(builder.selectedCapability()?.id, capability.id);
  assert.deepEqual(builder.bundledSkills().map((skill) => skill.id), [
    'skill-retrieve',
    'skill-answer',
  ]);
  assert.equal(builder.headerKpis()[1]?.value, 'UNIVERSAL');
  assert.equal(builder.headerKpis()[2]?.value, '2');
});

test('stub and unbound Skills block System creation until every runtime is bound', () => {
  const builder = makeBuilder();
  const capability: Capability = {
    id: 'cap-runtime',
    slug: 'runtime-ready',
    name: 'Runtime ready',
    tier: 'universal',
    skill_ids: ['skill-bound', 'skill-stub'],
  };
  builder.capabilities.set([capability]);
  builder.skills.set([
    { id: 'skill-bound', slug: 'bound', name: 'Bound', runtime_status: 'bound' },
    { id: 'skill-stub', slug: 'stub', name: 'Stub', runtime_status: 'stub' },
  ]);

  builder.selectCapability(capability);

  assert.equal(builder.blockedSkillsCount(), 1);
  assert.equal(builder.isSectionValid('skills'), false);
  assert.equal(builder.isSectionValid('launch'), false);
  assert.equal(
    builder.firstInvalidGateMessage(),
    'Bind every required Skill before creating this System.',
  );
  assert.equal(builder.headerKpis()[2]?.tone, 'warn');

  builder.skills.update((skills) =>
    skills.map((skill) => ({ ...skill, runtime_status: 'bound' as const })),
  );

  assert.equal(builder.blockedSkillsCount(), 0);
  assert.equal(builder.isSectionValid('skills'), true);
  assert.equal(builder.isSectionValid('launch'), true);
});

test('historical catalog-only app ids are not exposed in the System Builder', () => {
  const builder = makeBuilder();

  builder.enabledAppIds.set(['memory', 'rpa_bridge', 'unknown']);

  assert.deepEqual(builder.enabledApps().map((app) => app.id), ['rpa_bridge']);
});
