import '@angular/compiler';
import assert from 'node:assert/strict';
import test from 'node:test';
import {
  Injector,
  signal,
  ɵChangeDetectionScheduler as ChangeDetectionScheduler,
  ɵEffectScheduler as EffectScheduler,
} from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { NEVER, of } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import {
  WorkspaceService,
  type WorkspaceInfo,
  type WorkspaceMemberDetail,
} from '@app/core/workspace.service';
import { AccessRolesComponent } from '@app/features/governance/access-roles.component';
import { WorkspaceMembersComponent } from './members.component';

const WORKSPACE: WorkspaceInfo = {
  id: 'workspace-future',
  slug: 'future-workspace',
  name: 'Future workspace',
  role: 'admin',
  settings: { features: { workspace_app_platform_v1: true } },
  workspace_app_runtime: {
    mode: 'authoritative',
    enabled: true,
    valid: true,
    installations: [
      {
        app_id: 'andritz.chat', version: '1.0.0', manifest_digest: 'chat', category: 'business_app',
        routes: ['/chat'], primary_surface_id: 'chat', default_route: '/chat', branding_namespace: 'andritz',
        api_prefixes: ['/api/v1/chat'], action_packs: [], entitlement_keys: ['chat'],
      },
      {
        app_id: 'future.workspace-surface', version: '2.0.0', manifest_digest: 'future', category: 'business_app',
        routes: ['/future'], primary_surface_id: 'future-surface', default_route: '/future', branding_namespace: 'future',
        api_prefixes: ['/api/v1/future'], action_packs: [], entitlement_keys: ['future-surface'],
        display_name: 'Future Workspace Surface',
      },
    ],
    experience: null,
  },
};

const MEMBER: WorkspaceMemberDetail = {
  user_id: 'member-future',
  email: 'future@example.com',
  username: 'future',
  role: 'member',
  role_template: 'workspace_contributor',
  custom_labels: [],
  joined_at: '2026-07-22T00:00:00Z',
  is_current_user: false,
  app_entitlements: ['chat', 'future-surface'],
};

function checkbox(checked: boolean): Event {
  return { target: { checked } } as unknown as Event;
}

test('Members displays and sends a manifest-defined non-Andritz entitlement on invite', () => {
  const current = signal<WorkspaceInfo | null>(WORKSPACE);
  const invitations: unknown[][] = [];
  const workspace = {
    current,
    currentSlug: () => WORKSPACE.slug,
    appEntitlementsEnabled: () => true,
    isAdmin: () => true,
    listMembers: () => of([]),
    inviteMember: (...args: unknown[]) => {
      invitations.push(args);
      return of({
        status: 'ok', user_id: 'invitee', role: 'member',
        app_entitlements: ['future-surface'], invitation_email_sent: false,
      });
    },
  };
  const injector = Injector.create({ providers: [
    WorkspaceMembersComponent,
    { provide: WorkspaceService, useValue: workspace },
    {
      provide: ActivatedRoute,
      useValue: { parent: { paramMap: of({ get: (key: string) => key === 'slug' ? WORKSPACE.slug : null }) } },
    },
    { provide: ToastrService, useValue: { success() {}, info() {}, error() {} } },
    { provide: ChangeDetectionScheduler, useValue: { notify() {}, runningTick: false } },
    { provide: EffectScheduler, useValue: { add() {}, schedule() {}, flush() {}, remove() {} } },
  ] });
  const component = injector.get(WorkspaceMembersComponent);

  assert.deepEqual(component.inviteAppOptions().map((item) => [item.key, item.label]), [
    ['chat', 'Recherche'],
    ['future-surface', 'Future Workspace Surface'],
  ]);
  assert.equal(
    component.memberAppOptions(MEMBER).find((item) => item.key === 'future-surface')?.label,
    'Future Workspace Surface',
  );

  component.inviteEmail = 'invitee@example.com';
  component.inviteAppEntitlements = ['future-surface'];
  component.invite();
  assert.deepEqual(invitations[0], [
    WORKSPACE.slug,
    'invitee@example.com',
    'member',
    ['future-surface'],
  ]);
});

test('Governance toggle preserves a future active key and saves it unchanged', () => {
  const current = signal<WorkspaceInfo | null>(WORKSPACE);
  const updates: unknown[][] = [];
  const workspace = {
    current,
    appEntitlementsEnabled: () => true,
    updateIamMember: (...args: unknown[]) => {
      updates.push(args);
      return NEVER;
    },
    getIamSummary: () => of(null),
    getIamMatrix: () => of(null),
  };
  const injector = Injector.create({ providers: [
    AccessRolesComponent,
    { provide: WorkspaceService, useValue: workspace },
  ] });
  const component = injector.get(AccessRolesComponent);
  const member = structuredClone(MEMBER);
  component.members.set([member]);

  assert.deepEqual(component.appOptions().map((item) => item.key), ['chat', 'future-surface']);
  component.setMemberApp(member, 'chat', checkbox(false));
  assert.deepEqual(member.app_entitlements, ['future-surface']);
  component.saveMember(member);

  assert.deepEqual(updates[0], [
    MEMBER.user_id,
    {
      role_template: 'workspace_contributor',
      custom_labels: [],
      app_entitlements: ['future-surface'],
    },
  ]);
});
