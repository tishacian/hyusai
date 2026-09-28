import '@angular/compiler';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { Injector, runInInjectionContext, signal } from '@angular/core';
import { type Navigation, type NavigationBehaviorOptions, Router } from '@angular/router';
import { Subject, of } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
import { AuthApiService } from '@app/core/auth-api.service';
import { AuthBootstrapService } from '@app/core/auth-bootstrap.service';
import { ChatOverlayService } from '@app/features/chat/chat-overlay.service';
import { HelpOverlayService } from '@app/features/help/help-overlay.service';
import { experienceUnsavedChangesGuard } from '@app/features/experience/experience.guard';
import { I18nService } from '@app/core/i18n.service';
import { ThemeService } from '@app/core/theme.service';
import { TokenStorageService } from '@app/core/token-storage.service';
import {
  WorkspaceService,
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { type PendingChangesSummary, WorkspaceSwitchService } from '@app/core/workspace-switch.service';
import { AuthStore } from '@app/store/auth.store';
import { TitleBarComponent } from './title-bar.component';

interface TelemetrySnapshot {
  throughput_rpm: number | null;
  latency_ms: number | null;
  yield_pct: number | null;
  runs_count?: number;
}

class WorkspaceStub {
  private slug = 'andritz';
  private epoch = 3;
  private readonly resetters = new Set<(transition: WorkspaceContextTransition) => void>();
  settings: Record<string, unknown> | undefined;
  modeValue: 'builder' | 'executive' | 'operator' = 'executive';

  readonly workspaces = () => [
    { id: 'workspace-andritz', slug: 'andritz', name: 'Andritz', role: 'member' },
    { id: 'workspace-sentinel-ci', slug: 'sentinel-ci', name: 'Sentinel CI', role: 'member' },
  ];
  readonly currentSlug = () => this.slug;
  readonly contextEpoch = () => this.epoch;
  readonly current = () => ({ settings: this.settings, mode: this.modeValue, name: this.workspaces().find((w) => w.slug === this.slug)?.name ?? this.slug });
  readonly mode = () => this.modeValue;
  readonly isBuilderMode = () => this.modeValue === 'builder';
  readonly experienceV1Enabled = () => true;

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

  switchWorkspace(nextSlug = 'sentinel-ci'): boolean {
    if (nextSlug === this.slug) return false;
    const transition: WorkspaceContextTransition = {
      previousSlug: this.slug,
      nextSlug,
      previousEpoch: this.epoch,
      nextEpoch: this.epoch + 1,
    };
    for (const resetter of [...this.resetters]) resetter(transition);
    this.slug = nextSlug;
    this.epoch = transition.nextEpoch;
    return true;
  }

  resetterCount(): number {
    return this.resetters.size;
  }
}

interface RecordedNavigation {
  readonly url: string;
  readonly extras: NavigationBehaviorOptions;
  settled: boolean;
  settle(accepted: boolean): void;
}

/** Records each navigation and lets a test play the guards the real router would run. */
class RouterStub {
  url = '/systems/system-1?facet=runs';
  readonly events = new Subject<unknown>();
  readonly navigations: RecordedNavigation[] = [];
  aborted = 0;

  readonly navigate = () => Promise.resolve(true);

  readonly navigateByUrl = (url: string, extras: NavigationBehaviorOptions = {}) =>
    new Promise<boolean>((resolve) => {
      const navigation: RecordedNavigation = {
        url,
        extras,
        settled: false,
        settle: (accepted) => {
          navigation.settled = true;
          if (accepted) this.url = url;
          resolve(accepted);
        },
      };
      this.navigations.push(navigation);
    });

  readonly currentNavigation = (): Navigation | null => {
    const navigation = this.navigations.at(-1);
    if (!navigation || navigation.settled) return null;
    return {
      extras: navigation.extras,
      abort: () => {
        this.aborted += 1;
        navigation.settle(false);
      },
    } as unknown as Navigation;
  };

  /** The shell guard, once every CanDeactivate guard of A has passed. */
  exitAccepted(switcher: WorkspaceSwitchService): void {
    assert.equal(switcher.commit(this.currentNavigation()), true);
    this.navigations.at(-1)!.settle(true);
  }

  /** The Studio editor guard, with unsaved changes. */
  exitRefused(injector: Injector, summary: PendingChangesSummary): void {
    const editor = {
      pendingChanges: () => summary,
      confirmDiscardChanges: () => assert.fail('a workspace switch never opens confirm()'),
    };
    const allowed = runInInjectionContext(injector, () =>
      experienceUnsavedChangesGuard(editor, null as never, null as never, null as never),
    );
    assert.equal(allowed, false);
    this.navigations.at(-1)!.settle(false);
  }
}

function harness(options: { api?: unknown } = {}) {
  const workspace = new WorkspaceStub();
  const router = new RouterStub();
  const resolved = signal<'light' | 'dark'>('dark');
  const injector = Injector.create({
    providers: [
      TitleBarComponent,
      WorkspaceSwitchService,
      { provide: WorkspaceService, useValue: workspace },
      {
        provide: ApiService,
        useValue: options.api ?? { get: () => new Subject<TelemetrySnapshot>().asObservable() },
      },
      { provide: ThemeService, useValue: { mode: signal('dark'), resolved, setMode: () => undefined, cycle: () => undefined } },
      { provide: AuthStore, useValue: { email: () => null, role: () => null, clear: () => undefined } },
      {
        provide: ChatOverlayService,
        useValue: { isOpen: () => false, open: () => undefined, close: () => undefined },
      },
      {
        provide: HelpOverlayService,
        useValue: {
          isOpen: () => false,
          open: () => undefined,
          close: () => undefined,
          openFullPage: () => undefined,
        },
      },
      {
        provide: I18nService,
        useValue: {
          locale: signal('en'),
          supported: ['en', 'fr'],
          t: (key: string, params?: Record<string, unknown>) => (params ? `${key} ${JSON.stringify(params)}` : key),
          setLocale: () => undefined,
        },
      },
      { provide: AuthBootstrapService, useValue: { markInvalid: () => undefined } },
      { provide: TokenStorageService, useValue: { getRefreshToken: () => null, clear: () => undefined } },
      { provide: AuthApiService, useValue: { logout: () => of(null) } },
      { provide: Router, useValue: router },
      { provide: ToastrService, useValue: { success: () => undefined, error: () => undefined } },
    ],
  });
  const titleBar = injector.get(TitleBarComponent);
  const view = titleBar as unknown as {
    pendingFor(slug: string): boolean;
    suspendedFor(slug: string): { label: string; count: number } | null;
    unsavedReason(state: { label: string; count: number }): string;
    switchNotice(): { name: string; location: string; previous: { slug: string; name: string } | null } | null;
    builderChip(): { label: string; tooltip: string } | null;
    thrpt(): string;
    accountMenuItems: readonly string[];
  };
  return { injector, workspace, router, resolved, titleBar, view, switcher: injector.get(WorkspaceSwitchService) };
}

test('TitleBar drops A telemetry atomically and reloads only B after a workspace switch', async () => {
  const responses: Subject<TelemetrySnapshot>[] = [];
  const requestedSlugs: Array<string | null | undefined> = [];
  const api = {
    get: (
      path: string,
      _params?: unknown,
      options?: { workspaceSlug?: string | null },
    ) => {
      assert.equal(path, '/telemetry/live');
      requestedSlugs.push(options?.workspaceSlug);
      const response = new Subject<TelemetrySnapshot>();
      responses.push(response);
      return response.asObservable();
    },
  };
  const { injector, workspace, titleBar } = harness({ api });

  try {
    const telemetryHarness = titleBar as unknown as { refreshTelemetry(): void };

    // The constructor's timer(0) has not had a macrotask opportunity yet.
    telemetryHarness.refreshTelemetry();
    assert.deepEqual(requestedSlugs, ['andritz']);
    responses[0].next({
      throughput_rpm: 12,
      latency_ms: 90,
      yield_pct: 98,
      runs_count: 4,
    });
    assert.equal(titleBar.telemetry()?.throughput_rpm, 12);

    workspace.switchWorkspace();
    assert.equal(titleBar.telemetry(), null, 'A metrics are cleared before B is published');
    assert.equal(responses[0].observed, false, 'the A request is unsubscribed by the reset');

    responses[0].next({
      throughput_rpm: 999,
      latency_ms: 1,
      yield_pct: 100,
      runs_count: 999,
    });
    assert.equal(titleBar.telemetry(), null, 'late A data cannot repopulate the TitleBar');

    await Promise.resolve();
    assert.deepEqual(requestedSlugs, ['andritz', 'sentinel-ci']);
    responses[1].next({
      throughput_rpm: 2,
      latency_ms: 140,
      yield_pct: 91,
      runs_count: 1,
    });
    assert.equal(titleBar.telemetry()?.throughput_rpm, 2);
  } finally {
    injector.destroy();
  }

  assert.equal(workspace.resetterCount(), 0, 'destroy unregisters the workspace reset callback');
  assert.equal(responses.at(-1)?.observed, false, 'destroy unsubscribes the B request');
});

test('TitleBar commits B only after the guarded exit from A succeeds', async () => {
  const { injector, workspace, router, titleBar, switcher } = harness();
  try {
    const refused = titleBar.selectWorkspace('sentinel-ci');
    assert.equal(workspace.currentSlug(), 'andritz', 'A remains active while CanDeactivate is pending');
    router.exitRefused(injector, { label: 'PR to PO', count: 3, discard: () => undefined });
    await refused;
    assert.equal(workspace.currentSlug(), 'andritz', 'a refused exit keeps A intact');

    const accepted = titleBar.selectWorkspace('sentinel-ci');
    assert.equal(workspace.currentSlug(), 'andritz');
    router.exitAccepted(switcher);
    await accepted;
    assert.equal(workspace.currentSlug(), 'sentinel-ci', 'B is published only after the guarded exit');
    assert.deepEqual(
      router.navigations.map((navigation) => navigation.url),
      ['/systems', '/systems'],
      'one navigation per attempt, never through /hypervisor',
    );
  } finally {
    injector.destroy();
  }
});

test('TitleBar switches with a single replaceUrl navigation to the same surface', async () => {
  const { injector, workspace, router, titleBar, view, switcher } = harness();
  try {
    titleBar.workspaceMenuOpen.set(true);
    const switching = titleBar.selectWorkspace('sentinel-ci');
    assert.equal(router.navigations.length, 1);
    const [navigation] = router.navigations;
    assert.equal(navigation.url, '/systems', 'the object id and its facet are dropped');
    assert.equal(navigation.extras.replaceUrl, true);
    assert.equal(navigation.extras.onSameUrlNavigation, 'reload');

    router.exitAccepted(switcher);
    await switching;

    assert.equal(workspace.currentSlug(), 'sentinel-ci');
    assert.equal(titleBar.workspaceMenuOpen(), false, 'the menu closes on success');
    assert.deepEqual(view.switchNotice(), {
      name: 'Sentinel CI',
      location: 'experience.adoption.nav.build › Systems',
      previous: { slug: 'andritz', name: 'Andritz' },
    });
  } finally {
    injector.destroy();
  }
});

test('TitleBar treats the current URL as a destination, not a failure', async () => {
  const { injector, workspace, router, titleBar, switcher } = harness();
  try {
    router.url = '/hypervisor';
    const switching = titleBar.selectWorkspace('sentinel-ci');
    assert.deepEqual(router.navigations.map((navigation) => navigation.url), ['/hypervisor']);
    assert.equal(router.navigations[0].extras.onSameUrlNavigation, 'reload');

    router.exitAccepted(switcher);
    await switching;

    assert.equal(workspace.currentSlug(), 'sentinel-ci');
    assert.equal(switcher.state().phase, 'switched');
  } finally {
    injector.destroy();
  }
});

test('TitleBar keeps the menu open while the switch is pending, and Escape cancels it', async () => {
  const focused: string[] = [];
  const previousDocument = globalThis.document;
  globalThis.document = {
    getElementById: (id: string) => ({ focus: () => focused.push(id) }),
  } as unknown as Document;
  const { injector, workspace, router, titleBar, view } = harness();
  try {
    titleBar.workspaceMenuOpen.set(true);
    const switching = titleBar.selectWorkspace('sentinel-ci');
    assert.equal(view.pendingFor('sentinel-ci'), true, 'the chosen row reads « Ouverture… »');

    titleBar.closeMenus();
    titleBar.toggleWorkspaceMenu(new Event('click'));
    assert.equal(titleBar.workspaceMenuOpen(), true, 'neither an outside click nor the toggle closes it');

    titleBar.onEscape();
    await switching;
    await Promise.resolve();

    assert.equal(router.aborted, 1, 'Escape aborts the navigation');
    assert.equal(workspace.currentSlug(), 'andritz');
    assert.equal(titleBar.workspaceMenuOpen(), false);
    assert.deepEqual(focused, ['tb-workspace-toggle'], 'focus returns to the selector');
  } finally {
    injector.destroy();
    globalThis.document = previousDocument;
  }
});

test('TitleBar shows the refusal and its reason inside the menu', async () => {
  const { injector, workspace, router, titleBar, view, switcher } = harness();
  try {
    let discarded = 0;
    titleBar.workspaceMenuOpen.set(true);
    const refused = titleBar.selectWorkspace('sentinel-ci');
    router.exitRefused(injector, { label: 'PR to PO', count: 3, discard: () => (discarded += 1) });
    await refused;

    assert.equal(titleBar.workspaceMenuOpen(), true, 'the menu stays open on the refusal');
    const suspended = view.suspendedFor('sentinel-ci');
    assert.ok(suspended);
    assert.equal(
      view.unsavedReason(suspended),
      'workspace.switch.unsaved_other {"label":"PR to PO","count":3}',
    );

    const retried = titleBar.discardAndSwitch();
    assert.equal(discarded, 1, '« Abandonner et changer » discards first');
    router.exitAccepted(switcher);
    await retried;
    assert.equal(workspace.currentSlug(), 'sentinel-ci');
    assert.equal(titleBar.workspaceMenuOpen(), false);
  } finally {
    injector.destroy();
  }
});

test('« Rester ici » keeps A and closes the menu', async () => {
  const { injector, workspace, router, titleBar, switcher } = harness();
  try {
    titleBar.workspaceMenuOpen.set(true);
    const refused = titleBar.selectWorkspace('sentinel-ci');
    router.exitRefused(injector, { label: 'PR to PO', count: 1, discard: () => assert.fail('the draft is kept') });
    await refused;

    titleBar.stayHere();

    assert.equal(workspace.currentSlug(), 'andritz');
    assert.equal(switcher.state().phase, 'cancelled');
    assert.equal(titleBar.workspaceMenuOpen(), false);
    assert.equal(router.navigations.length, 1);
  } finally {
    injector.destroy();
  }
});

test('the title bar never shows a tenant emblem image (ADR lot 2)', () => {
  const { workspace, resolved, titleBar, injector } = harness();
  workspace.settings = {
    platform_brand: {
      label: 'NAWA',
      emblem: '/assets/nawa/nawa-logo.png',
      emblem_light: '/assets/nawa/nawa-logo-transparent.png',
      home: '/nawa/itsd',
    },
  };
  try {
    const source = readFileSync(
      join(process.cwd(), 'src/app/features/layout/title-bar.component.ts'),
      'utf8',
    );
    assert.match(source, /tb-mark/, 'the Agentium « A » mark stays in the 56px column');
    assert.doesNotMatch(source, /platformBrand|tb-emblem-brand|emblemIsKeyed/, 'tenant artwork left the bandeau');
    assert.equal(titleBar.builderChip(), null);
    resolved.set('light');
    assert.equal(titleBar.builderChip(), null);
  } finally {
    injector.destroy();
  }
});

test('a workspace with no brand keeps the Agentium mark only', () => {
  const source = readFileSync(
    join(process.cwd(), 'src/app/features/layout/title-bar.component.ts'),
    'utf8',
  );
  assert.match(source, />A</);
  assert.doesNotMatch(source, /Agentium<\/span>/);
});

test('the account menu no longer offers Settings', () => {
  const { titleBar, injector } = harness();
  try {
    assert.deepEqual([...titleBar.accountMenuItems], ['profile', 'security', 'locale', 'theme', 'signout']);
    const source = readFileSync(
      join(process.cwd(), 'src/app/features/layout/title-bar.component.ts'),
      'utf8',
    );
    assert.doesNotMatch(source, /navigate\('\/settings'\)/);
    assert.doesNotMatch(source, /nav\.settings/);
  } finally {
    injector.destroy();
  }
});

test('Télémétrie replaces Diagnostics and throughput uses /min from throughput_rpm', () => {
  const { titleBar, view, injector } = harness();
  try {
    titleBar.telemetry.set({
      throughput_rpm: 412,
      latency_ms: 96,
      yield_pct: 98,
      runs_count: 4,
    });
    assert.equal(view.thrpt(), '412/min');
    const source = readFileSync(
      join(process.cwd(), 'src/app/features/layout/title-bar.component.ts'),
      'utf8',
    );
    assert.match(source, /titlebar\.telemetry\.details/);
    assert.match(source, /titlebar\.telemetry\.panel_title/);
    assert.match(source, /observability.*facet.*traces|facet: 'traces'/);
    assert.doesNotMatch(source, /Diagnostics/);
    assert.doesNotMatch(source, / r\/m/);
  } finally {
    injector.destroy();
  }
});

test('L16: help origin uses the page title, not the workspace name', () => {
  const source = readFileSync(
    join(process.cwd(), 'src/app/features/layout/title-bar.component.ts'),
    'utf8',
  );
  assert.match(source, /helpOriginLabel/);
  assert.match(source, /main h1/);
  assert.doesNotMatch(
    source.slice(source.indexOf('openHelp()'), source.indexOf('openChat()')),
    /workspaceService\.current\(\)\?\.name/,
  );
});

test('in builder mode the chip announces two hidden zones', () => {
  const { workspace, view, injector } = harness();
  workspace.modeValue = 'builder';
  try {
    const chip = view.builderChip();
    assert.ok(chip);
    assert.match(chip.label, /titlebar\.builder\.chip/);
    assert.match(chip.label, /"count":2/);
    assert.match(chip.tooltip, /titlebar\.builder\.chip_tooltip/);
    assert.match(chip.tooltip, /hypervisor/);
    assert.match(chip.tooltip, /steer/);
  } finally {
    injector.destroy();
  }
});
