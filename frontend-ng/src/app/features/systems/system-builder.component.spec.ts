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
