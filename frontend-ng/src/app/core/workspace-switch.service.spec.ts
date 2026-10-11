import '@angular/compiler';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { Location } from '@angular/common';
import { type SpyLocation, provideLocationMocks } from '@angular/common/testing';
import {
  Component,
  type EnvironmentInjector,
  createEnvironmentInjector,
  inject,
  ɵConsole,
  ɵINJECTOR_SCOPE,
} from '@angular/core';
import {
  type CanDeactivateFn,
  NavigationEnd,
  RouteReuseStrategy,
  Router,
  type Routes,
  TitleStrategy,
  provideRouter,
} from '@angular/router';
import { navigationProfileGuard } from './navigation-profile.guard';
import { NavigationResolverService } from './navigation-resolver.service';
import { NavigationTelemetryService } from './navigation-telemetry.service';
import { WorkspaceExperienceShadowService } from './workspace-experience-shadow.service';
import {
  WORKSPACE_EPOCH,
  WorkspaceRouteReuseStrategy,
  workspaceEpochResolver,
} from './workspace-route-reuse.strategy';
import { workspaceSwitchGuard } from './workspace-switch.guard';
import {
  type PendingChangesSummary,
  WorkspaceSwitchService,
  workspaceSwitchTarget,
} from './workspace-switch.service';
import { WorkspaceService } from './workspace.service';

@Component({ standalone: true, template: '' })
class Page {}

interface Tenant {
  readonly slug: string;
  readonly name: string;
  readonly mode: 'executive' | 'builder' | 'business';
}

class Tenants {
  private slug: string;
  private epoch = 1;

  constructor(private readonly list: readonly Tenant[], initial: string) {
    this.slug = initial;
  }

  readonly workspaces = () => this.list;
  readonly currentSlug = () => this.slug;
  readonly contextEpoch = () => this.epoch;
  readonly current = () => this.list.find((tenant) => tenant.slug === this.slug) ?? null;

  switchWorkspace(slug: string): boolean {
    if (slug === this.slug || !this.list.some((tenant) => tenant.slug === slug)) return false;
    this.slug = slug;
    this.epoch += 1;
    return true;
  }
}

/** The two redirects of the bug report: the builder home and the business shell. */
function policy(tenants: Tenants) {
  return {
    activateWorkspaceFromRoute: () => null,
    resolveWorkspaceLoadFailure: () => null,
    resolve: (requestedRoute: string) => {
      const path = requestedRoute.split('?')[0];
      const mode = tenants.current()?.mode;
      const resolvedRoute = mode === 'builder' && path === '/hypervisor'
        ? '/create'
        : mode === 'business' && path !== '/chat'
          ? '/chat'
          : null;
      return resolvedRoute
        ? { requestedRoute, resolvedRoute, owner: 'navigation_resolver', reason: 'workspace_mode_home' }
        : null;
    },
  };
}

/** The Cockpit shell as `app.routes.ts` wires it, on the real Angular router. */
function harness(tenants: Tenants) {
  let exit: () => boolean | Promise<boolean> = () => true;
  let unsaved: PendingChangesSummary | null = null;
  const leaveEditor: CanDeactivateFn<unknown> = () => {
    if (unsaved && inject(WorkspaceSwitchService).suspend(unsaved)) return false;
    return exit();
  };
  const routes: Routes = [{
    path: '',
    component: Page,
    canActivate: [workspaceSwitchGuard],
    canActivateChild: [navigationProfileGuard],
    runGuardsAndResolvers: 'always',
    resolve: { [WORKSPACE_EPOCH]: workspaceEpochResolver },
    children: [
      { path: 'hypervisor', component: Page },
      { path: 'chat', component: Page },
      { path: 'create', component: Page },
      { path: 'create/apps', component: Page },
      { path: 'create/apps/:id', component: Page, canDeactivate: [leaveEditor] },
    ],
  }];
  const injector = createEnvironmentInjector([
    { provide: ɵINJECTOR_SCOPE, useValue: 'root' },
    { provide: ɵConsole, useClass: ɵConsole },
    provideRouter(routes),
    provideLocationMocks(),
    { provide: RouteReuseStrategy, useClass: WorkspaceRouteReuseStrategy },
    { provide: TitleStrategy, useValue: { updateTitle: () => undefined } },
    { provide: WorkspaceService, useValue: tenants },
    { provide: NavigationResolverService, useValue: policy(tenants) },
    { provide: NavigationTelemetryService, useValue: { registerRedirect: () => undefined } },
    {
      provide: WorkspaceExperienceShadowService,
      useValue: { observeNavigation: () => undefined, recordUnexpectedFailure: () => undefined },
    },
  ], null as unknown as EnvironmentInjector);
  const router = injector.get(Router);
  const location = injector.get(Location) as SpyLocation;
  const ends: string[] = [];
  router.events.subscribe((event) => {
    if (event instanceof NavigationEnd) ends.push(event.urlAfterRedirects);
  });
  return {
    injector,
    router,
    ends,
    switcher: injector.get(WorkspaceSwitchService),
    /** `history.length` of the spy location. */
    history: () => (location as unknown as { _history: unknown[] })._history.length,
    page: () => router.routerState.root.firstChild?.firstChild ?? null,
    holdExit: () => {
      let release!: (allowed: boolean) => void;
      exit = () => new Promise<boolean>((resolve) => (release = resolve));
      return (allowed: boolean) => release(allowed);
    },
    refuseExit: (summary: PendingChangesSummary) => (unsaved = summary),
    clearUnsaved: () => (unsaved = null),
  };
}

const guardsRun = () => new Promise((resolve) => setImmediate(resolve));

const executive: Tenant[] = [
  { slug: 'acme', name: 'Acme', mode: 'executive' },
  { slug: 'nawa', name: 'Nawa', mode: 'executive' },
];

test('a switch from /hypervisor lands on the same URL in one replaceUrl navigation', async () => {
  const tenants = new Tenants(executive, 'acme');
  const h = harness(tenants);
  try {
    await h.router.navigateByUrl('/hypervisor');
    const shell = h.router.routerState.root.firstChild;
    const page = h.page();
    const length = h.history();
    h.ends.length = 0;

    const outcome = await h.switcher.switch('nawa');

    assert.equal(outcome.phase, 'switched');
    assert.equal(tenants.currentSlug(), 'nawa');
    assert.equal(h.router.url, '/hypervisor');
    assert.deepEqual(h.ends, ['/hypervisor'], 'one navigation, no hop');
    assert.equal(h.history(), length, 'no history step');
    assert.notEqual(h.page(), page, 'the page is recreated for the new tenant');
    assert.equal(h.router.routerState.root.firstChild, shell, 'the chrome around it stays');
  } finally {
    h.injector.destroy();
  }
});

test('a switch from /create in builder mode is not swallowed by the builder home', async () => {
  const tenants = new Tenants([
    { slug: 'acme', name: 'Acme', mode: 'builder' },
    { slug: 'nawa', name: 'Nawa', mode: 'builder' },
  ], 'acme');
  const h = harness(tenants);
  try {
    await h.router.navigateByUrl('/create');
    const page = h.page();
    const length = h.history();

    const outcome = await h.switcher.switch('nawa');

    assert.equal(outcome.phase, 'switched');
    assert.equal(tenants.currentSlug(), 'nawa');
    assert.equal(h.router.url, '/create');
    assert.equal(h.history(), length);
    assert.notEqual(h.page(), page);
  } finally {
    h.injector.destroy();
  }
});

test('a switch from /chat in the business shell reloads the business home in place', async () => {
  const tenants = new Tenants([
    { slug: 'acme', name: 'Acme', mode: 'business' },
    { slug: 'nawa', name: 'Nawa', mode: 'business' },
  ], 'acme');
  const h = harness(tenants);
  try {
    await h.router.navigateByUrl('/chat');
    const page = h.page();
    const length = h.history();

    const outcome = await h.switcher.switch('nawa');

    assert.equal(outcome.phase, 'switched');
    assert.equal(tenants.currentSlug(), 'nawa');
    assert.equal(h.router.url, '/chat');
    assert.equal(h.history(), length);
    assert.notEqual(h.page(), page);
  } finally {
    h.injector.destroy();
  }
});

test("the next workspace's policy applies at the same URL, still without a history step", async () => {
  const tenants = new Tenants([
    { slug: 'acme', name: 'Acme', mode: 'executive' },
    { slug: 'nawa', name: 'Nawa', mode: 'builder' },
  ], 'acme');
  const h = harness(tenants);
  try {
    await h.router.navigateByUrl('/hypervisor');
    const length = h.history();
    h.ends.length = 0;

    const outcome = await h.switcher.switch('nawa');

    assert.equal(outcome.phase, 'switched');
    assert.equal(h.router.url, '/create', 'a builder workspace opens on Create');
    assert.deepEqual(h.ends, ['/create'], 'no NavigationEnd on /hypervisor on the way');
    assert.equal(h.history(), length);
  } finally {
    h.injector.destroy();
  }
});

test('B is published only after the guarded exit from A succeeds', async () => {
  const tenants = new Tenants(executive, 'acme');
  const h = harness(tenants);
  try {
    await h.router.navigateByUrl('/create/apps/app-1');
    const release = h.holdExit();

    const switching = h.switcher.switch('nawa');
    await guardsRun();
    assert.equal(h.switcher.state().phase, 'pending');
    assert.equal(tenants.currentSlug(), 'acme', 'A stays the tenant while CanDeactivate is pending');

    release(true);
    const outcome = await switching;
    assert.equal(outcome.phase, 'switched');
    assert.equal(tenants.currentSlug(), 'nawa');
    assert.equal(h.router.url, '/create/apps', 'the same surface, without the object id');
  } finally {
    h.injector.destroy();
  }
});

test('a refused exit keeps A and the draft, then « Abandonner et changer » discards and switches', async () => {
  const tenants = new Tenants(executive, 'acme');
  const h = harness(tenants);
  try {
    await h.router.navigateByUrl('/create/apps/app-1');
    const page = h.page();
    const length = h.history();
    let discarded = 0;
    h.refuseExit({
      label: 'PR to PO',
      count: 3,
      discard: () => {
        discarded += 1;
        h.clearUnsaved();
      },
    });

    const refused = await h.switcher.switch('nawa');

    assert.deepEqual(refused, { phase: 'suspended', slug: 'nawa', label: 'PR to PO', count: 3 });
    assert.equal(tenants.currentSlug(), 'acme');
    assert.equal(h.router.url, '/create/apps/app-1');
    assert.equal(h.page(), page, 'the editor and its draft are still there');
    assert.equal(h.history(), length);

    const outcome = await h.switcher.discardAndSwitch();

    assert.equal(discarded, 1);
    assert.equal(outcome.phase, 'switched');
    assert.equal(tenants.currentSlug(), 'nawa');
    assert.equal(h.router.url, '/create/apps');
  } finally {
    h.injector.destroy();
  }
});

test('Escape during the wait cancels the switch before B is published', async () => {
  const tenants = new Tenants(executive, 'acme');
  const h = harness(tenants);
  try {
    await h.router.navigateByUrl('/create/apps/app-1');
    const length = h.history();
    const release = h.holdExit();

    const switching = h.switcher.switch('nawa');
    await guardsRun();
    assert.equal(h.switcher.cancel(), true);

    const outcome = await switching;
    assert.equal(outcome.phase, 'cancelled');
    release(true);
    await guardsRun();
    assert.equal(tenants.currentSlug(), 'acme');
    assert.equal(h.router.url, '/create/apps/app-1');
    assert.equal(h.history(), length);
  } finally {
    h.injector.destroy();
  }
});

test('the target is the same zone and surface, without an object id', () => {
  assert.equal(workspaceSwitchTarget('/systems/sys-1?facet=runs', 'acme', 'nawa'), '/systems');
  assert.equal(workspaceSwitchTarget('/hypervisor?facet=couts', 'acme', 'nawa'), '/hypervisor?facet=couts');
  assert.equal(workspaceSwitchTarget('/create/apps/app-1', 'acme', 'nawa'), '/create/apps');
  assert.equal(workspaceSwitchTarget('/runs/run-1/invocations/inv-1', 'acme', 'nawa'), '/runs');
  assert.equal(workspaceSwitchTarget('/runs?lens=build', 'acme', 'nawa'), '/runs?lens=build');
  assert.equal(workspaceSwitchTarget('/workspace/acme/members', 'acme', 'nawa'), '/workspace/nawa/members');
  assert.equal(workspaceSwitchTarget('/', 'acme', 'nawa'), '/');
});

test('the Cockpit shell route carries the switch guard and resolves the epoch on every navigation', () => {
  const routes = readFileSync(join(process.cwd(), 'src', 'app', 'app.routes.ts'), 'utf8');
  assert.match(routes, /canActivate: \[authGuard, workspaceSwitchGuard\]/);
  assert.match(routes, /runGuardsAndResolvers: 'always'/);
  assert.match(routes, /resolve: \{ \[WORKSPACE_EPOCH\]: workspaceEpochResolver \}/);
});
