import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector, runInInjectionContext } from '@angular/core';
import { Router } from '@angular/router';
import { of } from 'rxjs';
import { navigationProfileGuard } from './navigation-profile.guard';
import { NavigationResolverService } from './navigation-resolver.service';
import { NavigationTelemetryService } from './navigation-telemetry.service';
import { WorkspaceExperienceShadowService } from './workspace-experience-shadow.service';
import { WorkspaceService } from './workspace.service';

const LEGACY_DECISION = {
  requestedRoute: '/systems',
  resolvedRoute: '/chat',
  owner: 'navigation_resolver' as const,
  reason: 'business_profile_disallowed' as const,
};

function runGuard(options: { shadowThrows?: boolean; legacyDecision?: typeof LEGACY_DECISION | null } = {}) {
  const events: string[] = [];
  const redirects: unknown[] = [];
  const parsedRoutes: string[] = [];
  const shadowCalls: unknown[][] = [];
  const shadowFailureCalls: string[] = [];
  const legacyDecision = options.legacyDecision === undefined
    ? LEGACY_DECISION
    : options.legacyDecision;
  const injector = Injector.create({
    providers: [
      {
        provide: WorkspaceService,
        useValue: {
          workspaces: () => [{ slug: 'andritz' }],
          loadWorkspaces: () => of([{ slug: 'andritz' }]),
        },
      },
      {
        provide: NavigationResolverService,
        useValue: {
          activateWorkspaceFromRoute: () => {
            events.push('activate');
            return null;
          },
          resolve: () => {
            events.push('legacy');
            return legacyDecision;
          },
          resolveWorkspaceLoadFailure: () => null,
        },
      },
      {
        provide: WorkspaceExperienceShadowService,
        useValue: {
          observeNavigation: (...args: unknown[]) => {
            events.push('shadow');
            shadowCalls.push(args);
            if (options.shadowThrows) throw new Error('shadow failed');
            // A maliciously divergent return value proves the guard does not
            // consume shadow output.
            return { resolvedRoute: '/client360', status: 'unexplained_divergence' };
          },
          recordUnexpectedFailure: (route: string) => {
            events.push('shadow-failure');
            shadowFailureCalls.push(route);
          },
        },
      },
      {
        provide: NavigationTelemetryService,
        useValue: {
          registerRedirect: (decision: unknown) => {
            events.push('telemetry');
            redirects.push(decision);
          },
        },
      },
      {
        provide: Router,
        useValue: {
          parseUrl: (route: string) => {
            events.push('parse');
            parsedRoutes.push(route);
            return { legacyUrlTree: route };
          },
        },
      },
    ],
  });

  const result = runInInjectionContext(injector, () =>
    navigationProfileGuard({} as never, { url: '/systems' } as never),
  );
  return { events, redirects, parsedRoutes, result, shadowCalls, shadowFailureCalls };
}

test('navigation guard observes V2 after the legacy decision and executes only legacy output', () => {
  const harness = runGuard();

  assert.deepEqual(harness.events, ['activate', 'legacy', 'shadow', 'telemetry', 'parse']);
  assert.deepEqual(harness.shadowFailureCalls, []);
  assert.deepEqual(harness.shadowCalls, [['/systems', LEGACY_DECISION]]);
  assert.deepEqual(harness.redirects, [LEGACY_DECISION]);
  assert.deepEqual(harness.parsedRoutes, ['/chat']);
  assert.deepEqual(harness.result, { legacyUrlTree: '/chat' });
});

test('an unexpected shadow exception never interrupts legacy navigation', () => {
  const harness = runGuard({ shadowThrows: true });

  assert.deepEqual(harness.events, ['activate', 'legacy', 'shadow', 'shadow-failure', 'telemetry', 'parse']);
  assert.deepEqual(harness.shadowFailureCalls, ['/systems']);
  assert.deepEqual(harness.redirects, [LEGACY_DECISION]);
  assert.deepEqual(harness.parsedRoutes, ['/chat']);
  assert.deepEqual(harness.result, { legacyUrlTree: '/chat' });
});

test('a direct legacy decision remains direct even when shadow reports a divergence', () => {
  const harness = runGuard({ legacyDecision: null });

  assert.deepEqual(harness.events, ['activate', 'legacy', 'shadow']);
  assert.deepEqual(harness.shadowCalls, [['/systems', null]]);
  assert.deepEqual(harness.redirects, []);
  assert.deepEqual(harness.parsedRoutes, []);
  assert.equal(harness.result, true);
});
