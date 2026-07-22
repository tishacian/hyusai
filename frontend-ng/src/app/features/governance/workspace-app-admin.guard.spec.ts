import '@angular/compiler';
import assert from 'node:assert/strict';
import test from 'node:test';
import { Injector, runInInjectionContext } from '@angular/core';
import { Router } from '@angular/router';
import { NavigationProfileService } from '@app/core/navigation-profile.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { workspaceAppAdminGuard } from './workspace-app-admin.guard';

function evaluate(options: { admin: boolean; unavailable: boolean }) {
  const parsed: string[] = [];
  const injector = Injector.create({
    providers: [
      {
        provide: WorkspaceService,
        useValue: {
          workspaces: () => [{ slug: 'workspace' }],
          isAdmin: () => options.admin,
        },
      },
      {
        provide: NavigationProfileService,
        useValue: { workspaceAppUnavailable: () => options.unavailable },
      },
      {
        provide: Router,
        useValue: {
          parseUrl: (route: string) => {
            parsed.push(route);
            return { route };
          },
        },
      },
    ],
  });
  const result = runInInjectionContext(injector, () => (
    workspaceAppAdminGuard({} as never, {} as never)
  ));
  return { parsed, result };
}

test('workspace app repair remains directly available to workspace admins', () => {
  const result = evaluate({ admin: true, unavailable: true });
  assert.equal(result.result, true);
  assert.deepEqual(result.parsed, []);
});

test('invalid runtime sends non-admins to the isolated unavailable page', () => {
  const result = evaluate({ admin: false, unavailable: true });
  assert.deepEqual(result.result, { route: '/workspace-app-unavailable' });
  assert.deepEqual(result.parsed, ['/workspace-app-unavailable']);
});

test('legacy non-admin lifecycle access keeps its governance fallback', () => {
  const result = evaluate({ admin: false, unavailable: false });
  assert.deepEqual(result.result, { route: '/governance/audit' });
  assert.deepEqual(result.parsed, ['/governance/audit']);
});
