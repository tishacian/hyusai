import '@angular/compiler';
import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';
import { Injector, signal } from '@angular/core';
import {
  Event as RouterEvent,
  NavigationCancel,
  NavigationCancellationCode,
  NavigationEnd,
  NavigationError,
  NavigationStart,
  Router,
} from '@angular/router';
import { Observable, Subject, of } from 'rxjs';
import { ApiService } from './api.service';
import {
  NAVIGATION_RESOLVED_EVENT,
  NavigationResolvedDetails,
  NavigationTelemetryService,
  navigationSurfaceForRoute,
  privacySafeNavigationRoute,
} from './navigation-telemetry.service';
import { WorkspaceService } from './workspace.service';

interface AuditCall {
  path: string;
  body: {
    event_type: string;
    details: NavigationResolvedDetails;
    severity: string;
  };
}

class RouterStub {
  readonly events = new Subject<RouterEvent>();
  url = '/';
}

class ApiStub {
  readonly calls: AuditCall[] = [];

  post(path: string, body: AuditCall['body']): Observable<unknown> {
    this.calls.push({ path, body });
    return of({ id: 'audit-navigation' });
  }
}

class WorkspaceStub {
  readonly currentSlug = signal<string | null>('andritz');
  private resetter: (() => void) | null = null;

  registerContextReset(resetter: () => void): () => void {
    this.resetter = resetter;
    return () => {
      this.resetter = null;
    };
  }

  resetContext(): void {
    this.resetter?.();
  }
}

const services: NavigationTelemetryService[] = [];

afterEach(() => {
  for (const service of services.splice(0)) service.ngOnDestroy();
});

function makeHarness() {
  const router = new RouterStub();
  const api = new ApiStub();
  const workspace = new WorkspaceStub();
  const injector = Injector.create({
    providers: [
      NavigationTelemetryService,
      { provide: Router, useValue: router },
      { provide: ApiService, useValue: api },
      { provide: WorkspaceService, useValue: workspace },
    ],
  });
  const telemetry = injector.get(NavigationTelemetryService);
  services.push(telemetry);
  telemetry.start();
  return { router, api, workspace, telemetry };
}

test('direct navigation emits one workspace-scoped event without query or fragment', () => {
  const { router, api } = makeHarness();
  router.events.next(new NavigationStart(1, '/client360/opportunities?customer=private#mail'));
  router.events.next(new NavigationEnd(
    1,
    '/client360/opportunities?customer=private#mail',
    '/client360/opportunities?customer=private#mail',
  ));

  assert.equal(api.calls.length, 1);
  assert.equal(api.calls[0].path, '/audit');
  assert.equal(api.calls[0].body.event_type, NAVIGATION_RESOLVED_EVENT);
  assert.deepEqual(api.calls[0].body.details, {
    schema_version: 1,
    requested_route: '/client360/:segment',
    resolved_route: '/client360/:segment',
    effective_workspace: 'andritz',
    effective_surface: 'client360-pdr',
    redirect_owner: 'angular_router',
    redirect_reason: 'direct',
    redirected: false,
  });
});

test('explicit redirect keeps the original request, owner and typed reason', () => {
  const { router, api, telemetry } = makeHarness();
  router.events.next(new NavigationStart(1, '/systems?view=private'));
  telemetry.registerRedirect({
    requestedRoute: '/systems?view=private',
    resolvedRoute: '/chat?ignored=private',
    owner: 'navigation_resolver',
    reason: 'business_profile_disallowed',
  });
  // Angular starts a replacement navigation after a guard returns a UrlTree.
  router.events.next(new NavigationCancel(
    1,
    '/systems?view=private',
    'Redirecting to /chat',
    NavigationCancellationCode.Redirect,
  ));
  router.events.next(new NavigationStart(2, '/chat?ignored=private'));
  router.events.next(new NavigationEnd(2, '/chat?ignored=private', '/chat?ignored=private'));

  assert.equal(api.calls.length, 1);
  assert.deepEqual(api.calls[0].body.details, {
    schema_version: 1,
    requested_route: '/systems',
    resolved_route: '/chat',
    effective_workspace: 'andritz',
    effective_surface: 'chat',
    redirect_owner: 'navigation_resolver',
    redirect_reason: 'business_profile_disallowed',
    redirected: true,
  });
});

test('explicit redirect records the final destination after a chained Angular redirect', () => {
  const { router, api, telemetry } = makeHarness();
  router.events.next(new NavigationStart(1, '/hypervisor'));
  telemetry.registerRedirect({
    requestedRoute: '/hypervisor',
    resolvedRoute: '/settings',
    owner: 'navigation_resolver',
    reason: 'workspace_default_route',
  });
  router.events.next(new NavigationCancel(
    1,
    '/hypervisor',
    'Redirecting to /settings',
    NavigationCancellationCode.Redirect,
  ));
  router.events.next(new NavigationStart(2, '/settings'));
  router.events.next(new NavigationEnd(2, '/settings', '/presets'));

  assert.equal(api.calls.length, 1);
  assert.deepEqual(api.calls[0].body.details, {
    schema_version: 1,
    requested_route: '/hypervisor',
    resolved_route: '/presets',
    effective_workspace: 'andritz',
    effective_surface: 'presets',
    redirect_owner: 'navigation_resolver',
    redirect_reason: 'workspace_default_route',
    redirected: true,
  });
});

test('explicit redirect survives a superseded navigation when its replacement wins', () => {
  const { router, api, telemetry } = makeHarness();
  router.events.next(new NavigationStart(1, '/workspace'));
  telemetry.registerRedirect({
    requestedRoute: '/workspace',
    resolvedRoute: '/workspace/andritz/settings',
    owner: 'navigation_resolver',
    reason: 'workspace_settings_entrypoint',
  });
  router.events.next(new NavigationCancel(
    1,
    '/workspace',
    'Superseded by /workspace/andritz/settings',
    NavigationCancellationCode.SupersededByNewNavigation,
  ));
  router.events.next(new NavigationStart(2, '/workspace/andritz/settings'));
  router.events.next(new NavigationEnd(
    2,
    '/workspace/andritz/settings',
    '/workspace/andritz/settings',
  ));

  assert.equal(api.calls.length, 1);
  assert.deepEqual(api.calls[0].body.details, {
    schema_version: 1,
    requested_route: '/workspace',
    resolved_route: '/workspace/:slug/settings',
    effective_workspace: 'andritz',
    effective_surface: 'workspace-admin',
    redirect_owner: 'navigation_resolver',
    redirect_reason: 'workspace_settings_entrypoint',
    redirected: true,
  });
});

test('a superseded redirect cannot leak into a different replacement destination', () => {
  const { router, api, telemetry } = makeHarness();
  router.events.next(new NavigationStart(1, '/workspace'));
  telemetry.registerRedirect({
    requestedRoute: '/workspace',
    resolvedRoute: '/workspace/andritz/settings',
    owner: 'navigation_resolver',
    reason: 'workspace_settings_entrypoint',
  });
  router.events.next(new NavigationCancel(
    1,
    '/workspace',
    'Superseded by /chat',
    NavigationCancellationCode.SupersededByNewNavigation,
  ));
  router.events.next(new NavigationStart(2, '/chat'));
  router.events.next(new NavigationEnd(2, '/chat', '/chat'));

  assert.equal(api.calls.length, 1);
  assert.equal(api.calls[0].body.details.requested_route, '/chat');
  assert.equal(api.calls[0].body.details.resolved_route, '/chat');
  assert.equal(api.calls[0].body.details.redirect_owner, 'angular_router');
  assert.equal(api.calls[0].body.details.redirect_reason, 'direct');
  assert.equal(api.calls[0].body.details.redirected, false);
});

test('cancelled or failed redirects cannot leak into a later navigation', () => {
  const { router, api, telemetry } = makeHarness();
  router.events.next(new NavigationStart(1, '/systems'));
  telemetry.registerRedirect({
    requestedRoute: '/systems',
    resolvedRoute: '/chat',
    owner: 'navigation_resolver',
    reason: 'business_profile_disallowed',
  });
  router.events.next(new NavigationCancel(
    1,
    '/systems',
    'Guard rejected',
    NavigationCancellationCode.GuardRejected,
  ));
  router.events.next(new NavigationStart(2, '/client360'));
  router.events.next(new NavigationEnd(2, '/client360', '/client360'));

  assert.equal(api.calls.length, 1);
  assert.equal(api.calls[0].body.details.redirected, false);
  assert.equal(api.calls[0].body.details.redirect_owner, 'angular_router');
  assert.equal(api.calls[0].body.details.requested_route, '/client360');

  router.events.next(new NavigationStart(3, '/systems'));
  telemetry.registerRedirect({
    requestedRoute: '/systems',
    resolvedRoute: '/chat',
    owner: 'navigation_resolver',
    reason: 'business_profile_disallowed',
  });
  router.events.next(new NavigationError(3, '/systems', new Error('lazy chunk failed')));
  router.events.next(new NavigationStart(4, '/knowledge'));
  router.events.next(new NavigationEnd(4, '/knowledge', '/knowledge'));

  assert.equal(api.calls.length, 2);
  assert.equal(api.calls[1].body.details.redirected, false);
  assert.equal(api.calls[1].body.details.requested_route, '/knowledge');
});

test('static Angular redirect is inferred from urlAfterRedirects', () => {
  const { router, api } = makeHarness();
  router.events.next(new NavigationStart(1, '/settings'));
  router.events.next(new NavigationEnd(1, '/settings', '/presets'));

  assert.equal(api.calls.length, 1);
  assert.equal(api.calls[0].body.details.redirect_owner, 'angular_router');
  assert.equal(api.calls[0].body.details.redirect_reason, 'angular_route_redirect');
  assert.equal(api.calls[0].body.details.redirected, true);
  assert.equal(api.calls[0].body.details.requested_route, '/settings');
  assert.equal(api.calls[0].body.details.resolved_route, '/presets');
  assert.equal(api.calls[0].body.details.effective_surface, 'presets');
});

test('public/auth routes and navigations without a workspace are not emitted', () => {
  const { router, api, workspace } = makeHarness();
  router.events.next(new NavigationStart(1, '/auth/signin'));
  router.events.next(new NavigationEnd(1, '/auth/signin', '/auth/signin'));

  workspace.currentSlug.set(null);
  router.events.next(new NavigationStart(2, '/chat'));
  router.events.next(new NavigationEnd(2, '/chat', '/chat'));

  assert.equal(api.calls.length, 0);
});

test('the first NavigationEnd is safely backfilled after workspace loading', () => {
  const { router, api, workspace, telemetry } = makeHarness();
  workspace.currentSlug.set(null);
  router.events.next(new NavigationStart(1, '/chat?draft=private'));
  router.events.next(new NavigationEnd(1, '/chat?draft=private', '/chat?draft=private'));
  assert.equal(api.calls.length, 0);

  workspace.currentSlug.set('andritz');
  telemetry.flushDeferred();
  telemetry.flushDeferred();

  assert.equal(api.calls.length, 1);
  assert.equal(api.calls[0].body.details.effective_workspace, 'andritz');
  assert.equal(api.calls[0].body.details.requested_route, '/chat');
  assert.equal(api.calls[0].body.details.resolved_route, '/chat');
});

test('privacy and surface helpers redact identifiers and reuse the catalog ids', () => {
  assert.equal(
    privacySafeNavigationRoute('/runs/550e8400-e29b-41d4-a716-446655440000?prompt=secret'),
    '/runs/:runId',
  );
  assert.equal(
    privacySafeNavigationRoute('/account/person%40example.test#sessions'),
    '/account/:segment',
  );
  assert.equal(
    privacySafeNavigationRoute('/workspace/andritz/settings?member=private'),
    '/workspace/:slug/settings',
  );
  assert.equal(
    privacySafeNavigationRoute('/client360/customers/Jean-Dupont'),
    '/client360/:segment/:segment',
  );
  assert.equal(navigationSurfaceForRoute('/knowledge/capture/session/private'), 'knowledge-capture');
  assert.equal(navigationSurfaceForRoute('/systems/system-1/capture'), 'system-capture');
  assert.equal(navigationSurfaceForRoute('/hypervisor/mission-room/strategie'), 'mission-room');
  assert.equal(navigationSurfaceForRoute('/does-not-exist'), 'unknown');
});
