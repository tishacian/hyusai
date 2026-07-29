import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Subject, of } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
import { AuthApiService } from '@app/core/auth-api.service';
import { AuthBootstrapService } from '@app/core/auth-bootstrap.service';
import { ChatOverlayService } from '@app/features/chat/chat-overlay.service';
import { I18nService } from '@app/core/i18n.service';
import { ThemeService } from '@app/core/theme.service';
import { TokenStorageService } from '@app/core/token-storage.service';
import {
  WorkspaceService,
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
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

test('TitleBar drops A telemetry atomically and reloads only B after a workspace switch', async () => {
  const workspace = new WorkspaceStub();
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
  const injector = Injector.create({
    providers: [
      TitleBarComponent,
      { provide: WorkspaceService, useValue: workspace },
      { provide: ApiService, useValue: api },
      { provide: ThemeService, useValue: { mode: signal('dark'), setMode: () => undefined } },
      { provide: AuthStore, useValue: { email: () => null, clear: () => undefined } },
      {
        provide: ChatOverlayService,
        useValue: { isOpen: () => false, open: () => undefined, close: () => undefined },
      },
      {
        provide: I18nService,
        useValue: { locale: signal('en'), t: (key: string) => key, setLocale: () => undefined },
      },
      { provide: AuthBootstrapService, useValue: { markInvalid: () => undefined } },
      {
        provide: TokenStorageService,
        useValue: { getRefreshToken: () => null, clear: () => undefined },
      },
      { provide: AuthApiService, useValue: { logout: () => of(null) } },
      {
        provide: Router,
        useValue: { navigate: () => Promise.resolve(true), navigateByUrl: () => Promise.resolve(true) },
      },
      {
        provide: ToastrService,
        useValue: { success: () => undefined, error: () => undefined },
      },
    ],
  });

  try {
    const titleBar = injector.get(TitleBarComponent);
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
