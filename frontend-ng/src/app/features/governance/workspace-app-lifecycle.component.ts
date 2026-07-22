import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { forkJoin } from 'rxjs';
import { WorkspaceService, type WorkspaceRequestScope } from '@app/core/workspace.service';
import { WorkspaceAppGovernanceApi } from './workspace-app-governance.api';
import {
  WorkspaceAppIdempotencyLedger,
  buildWorkspaceAppCatalog,
  workspaceAppActions,
  workspaceAppResponseIsCurrent,
  type PendingWorkspaceAppPlan,
  type WorkspaceAppAction,
  type WorkspaceAppCatalogItem,
  type WorkspaceAppLifecycleApplyResponse,
  type WorkspaceAppManifestEntry,
} from './workspace-app-lifecycle.models';

@Component({
  selector: 'app-workspace-app-lifecycle',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="apps-page" data-testid="workspace-app-lifecycle">
      <header class="page-head">
        <div>
          <p class="eyebrow">Governance · Workspace App Platform</p>
          <h1>Workspace Apps</h1>
          <p class="lead">
            Install, upgrade, roll back or uninstall a compiled app manifest through an exact,
            content-addressed plan. This lifecycle never edits workspace settings or member entitlements.
          </p>
        </div>
        <button type="button" class="ghost" (click)="load()" [disabled]="loading() || busy()">
          Refresh registry
        </button>
      </header>

      @if (!isAdmin()) {
        <div class="notice danger" role="alert">
          Workspace owner or admin access is required for this lifecycle.
        </div>
      } @else {
        @if (error()) {
          <div class="notice danger" role="alert">{{ error() }}</div>
        }
        @if (receipt(); as result) {
          <div class="notice success" data-testid="workspace-app-receipt">
            {{ result.operation }} completed for <strong>{{ result.app_id }}</strong>
            · revision {{ result.installation.revision }}
            · {{ result.step_receipts.length }} lifecycle steps verified
            · phase {{ result.lifecycle_phase }}
            @if (result.idempotent_replay) { · idempotent replay }
          </div>
        }

        <section class="safety-strip" aria-label="Workspace App lifecycle guarantees">
          <span>Admin-only</span>
          <span>Exact manifest digest</span>
          <span>Plan before apply</span>
          <span>Stable retry key</span>
          <span>No entitlement mutation</span>
        </section>

        @if (loading()) {
          <div class="empty">Loading the authoritative manifest registry…</div>
        } @else if (!catalog().length) {
          <div class="empty">No compiled Workspace App manifest is available.</div>
        } @else {
          <div class="catalog" data-testid="workspace-app-catalog">
            @for (app of catalog(); track app.appId) {
              <article class="app-card" [attr.data-app-id]="app.appId">
                <div class="card-head">
                  <div>
                    <p class="eyebrow">{{ app.category }}</p>
                    <h2>{{ app.displayName }}</h2>
                    <code>{{ app.appId }}</code>
                  </div>
                  <span class="state" [class.installed]="isInstalled(app)">
                    {{ isInstalled(app) ? 'installed' : 'not installed' }}
                  </span>
                </div>

                <div class="current">
                  <div>
                    <span>Current version</span>
                    <strong>{{ app.installation?.version || '—' }}</strong>
                  </div>
                  <div>
                    <span>Revision</span>
                    <strong>{{ app.installation?.revision || 0 }}</strong>
                  </div>
                  <div class="digest">
                    <span>Installed digest</span>
                    <code [title]="app.installation?.manifest_digest || ''">
                      {{ shortDigest(app.installation?.manifest_digest) }}
                    </code>
                  </div>
                </div>

                @if (displayManifest(app); as manifest) {
                  <dl class="contract">
                    <div>
                      <dt>Routes</dt>
                      <dd>{{ manifest.manifest.routes.join(', ') || 'none' }}</dd>
                    </div>
                    <div>
                      <dt>Brand namespace</dt>
                      <dd>{{ manifest.manifest.branding.namespace }}</dd>
                    </div>
                    <div>
                      <dt>Action packs</dt>
                      <dd>{{ manifest.manifest.action_packs.join(', ') || 'none' }}</dd>
                    </div>
                    <div>
                      <dt>Entitlement contract</dt>
                      <dd>{{ manifest.manifest.entitlement_keys.join(', ') || 'none' }}</dd>
                    </div>
                  </dl>
                }

                <div class="versions" aria-label="Available manifest versions">
                  @for (manifest of app.versions; track manifest.manifest_digest) {
                    <span [title]="manifest.manifest_digest">v{{ manifest.version }}</span>
                  }
                </div>

                <div class="actions">
                  @for (action of actions(app); track action.operation + ':' + action.manifest.manifest_digest) {
                    <button
                      type="button"
                      [class.danger]="action.operation === 'uninstall'"
                      [attr.data-operation]="action.operation"
                      [attr.data-manifest-digest]="action.manifest.manifest_digest"
                      (click)="plan(action)"
                      [disabled]="busy()"
                    >
                      Plan {{ action.label }}
                    </button>
                  } @empty {
                    <span class="no-action">No valid lifecycle transition in this registry.</span>
                  }
                </div>
              </article>
            }
          </div>
        }

        @if (pending(); as pendingPlan) {
          <section class="plan-panel" data-testid="workspace-app-plan">
            <div class="plan-head">
              <div>
                <p class="eyebrow">Authoritative dry-run</p>
                <h2>{{ pendingPlan.plan.operation }} · {{ pendingPlan.plan.app_id }}</h2>
              </div>
              <button type="button" class="ghost" (click)="discardPlan()" [disabled]="busy()">
                Discard
              </button>
            </div>
            <div class="transition">
              <div>
                <span>From</span>
                <strong>{{ pendingPlan.plan.from.state }} {{ pendingPlan.plan.from.version || '' }}</strong>
                <code>{{ shortDigest(pendingPlan.plan.from.manifest_digest) }}</code>
              </div>
              <span class="arrow">→</span>
              <div>
                <span>To</span>
                <strong>{{ pendingPlan.plan.to.state }} {{ pendingPlan.plan.to.version || '' }}</strong>
                <code>{{ shortDigest(pendingPlan.plan.to.manifest_digest) }}</code>
              </div>
            </div>
            <div class="hashes">
              <label>Manifest SHA-256</label>
              <code data-testid="workspace-app-manifest-digest">{{ pendingPlan.request.expected_manifest_digest }}</code>
              <label>Plan SHA-256</label>
              <code data-testid="workspace-app-plan-sha">{{ pendingPlan.plan.plan_sha256 }}</code>
              <label>Lifecycle phase</label>
              <code data-testid="workspace-app-lifecycle-phase">{{ pendingPlan.plan.lifecycle_phase }}</code>
              <label>Step chain SHA-256 ({{ pendingPlan.plan.steps.length }} steps)</label>
              <code data-testid="workspace-app-steps-sha">{{ pendingPlan.plan.steps_sha256 }}</code>
            </div>
            <p class="warning">
              Apply revalidates this exact plan after a tenant lock. A stale plan is rejected;
              retries reuse the same idempotency key.
            </p>
            <button
              type="button"
              class="primary"
              data-testid="workspace-app-apply"
              (click)="apply()"
              [disabled]="busy()"
            >
              {{ busy() ? 'Applying…' : 'Apply exact plan' }}
            </button>
          </section>
        }
      }
    </section>
  `,
  styles: [`
    :host { display: block; }
    .apps-page { max-width: 1480px; margin: 0 auto; padding: 24px 32px 64px; color: var(--ck-fg-1); }
    .page-head, .card-head, .plan-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; }
    h1 { margin: 4px 0 8px; font-size: 30px; font-weight: 650; }
    h2 { margin: 3px 0 5px; font-size: 18px; font-weight: 620; }
    .eyebrow, dt, label { margin: 0; color: var(--ck-fg-3); font-family: var(--ck-font-mono); font-size: 10px; letter-spacing: .09em; text-transform: uppercase; }
    .lead { max-width: 820px; margin: 0; color: var(--ck-fg-2); line-height: 1.55; }
    button { min-height: 32px; border: 1px solid var(--ck-stroke-3); border-radius: 4px; padding: 6px 11px; background: var(--ck-bg-panel-hi); color: var(--ck-fg-1); cursor: pointer; }
    button:hover:not(:disabled) { border-color: var(--ck-accent); }
    button:disabled { cursor: not-allowed; opacity: .5; }
    button.ghost { background: transparent; }
    button.primary { border-color: color-mix(in srgb, var(--ck-accent) 70%, transparent); background: color-mix(in srgb, var(--ck-accent) 22%, var(--ck-bg-panel)); }
    button.danger { border-color: color-mix(in srgb, #ef6f73 55%, transparent); color: #ff9fa2; }
    .safety-strip { display: flex; flex-wrap: wrap; gap: 8px; margin: 22px 0 16px; }
    .safety-strip span, .versions span, .state { border: 1px solid var(--ck-stroke-2); border-radius: 999px; padding: 4px 8px; color: var(--ck-fg-3); font: 10px var(--ck-font-mono); text-transform: uppercase; }
    .state.installed { border-color: color-mix(in srgb, #4bcf9b 48%, transparent); color: #72ddae; }
    .catalog { display: grid; grid-template-columns: repeat(auto-fit, minmax(390px, 1fr)); gap: 14px; }
    .app-card, .plan-panel { border: 1px solid var(--ck-stroke-2); border-radius: 6px; background: var(--ck-bg-panel); padding: 18px; }
    code { color: var(--ck-fg-2); font-family: var(--ck-font-mono); font-size: 11px; overflow-wrap: anywhere; }
    .current { display: grid; grid-template-columns: 1fr 1fr 2fr; gap: 10px; margin: 18px 0; }
    .current > div { min-width: 0; border: 1px solid var(--ck-stroke-1); border-radius: 4px; padding: 9px; background: var(--ck-bg-canvas); }
    .current span, .transition span { display: block; margin-bottom: 5px; color: var(--ck-fg-3); font-size: 11px; }
    .current strong, .transition strong { display: block; font-size: 13px; }
    .digest code { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .contract { display: grid; gap: 7px; margin: 0; }
    .contract div { display: grid; grid-template-columns: 130px 1fr; gap: 12px; }
    dd { margin: 0; color: var(--ck-fg-2); font-size: 12px; overflow-wrap: anywhere; }
    .versions, .actions { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 16px; }
    .no-action { color: var(--ck-fg-3); font-size: 12px; }
    .notice, .empty { margin: 18px 0; border: 1px solid var(--ck-stroke-2); border-radius: 5px; padding: 12px 14px; background: var(--ck-bg-panel); color: var(--ck-fg-2); }
    .notice.danger { border-color: color-mix(in srgb, #ef6f73 48%, transparent); color: #ffacad; }
    .notice.success { border-color: color-mix(in srgb, #4bcf9b 48%, transparent); color: #78dfb4; }
    .plan-panel { position: sticky; bottom: 18px; z-index: 5; max-width: 900px; margin: 18px auto 0; box-shadow: 0 18px 50px rgba(0, 0, 0, .42); }
    .transition { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 18px; margin: 16px 0; }
    .transition > div { border: 1px solid var(--ck-stroke-2); border-radius: 4px; padding: 11px; }
    .arrow { font-size: 20px; }
    .hashes { display: grid; grid-template-columns: 140px 1fr; gap: 7px 12px; align-items: baseline; }
    .warning { color: #e6c678; font-size: 12px; line-height: 1.45; }
    @media (max-width: 760px) {
      .apps-page { padding: 18px; }
      .page-head { display: block; }
      .page-head button { margin-top: 14px; }
      .catalog { grid-template-columns: 1fr; }
      .current { grid-template-columns: 1fr 1fr; }
      .digest { grid-column: 1 / -1; }
      .contract div, .hashes { grid-template-columns: 1fr; }
    }
  `],
})
export class WorkspaceAppLifecycleComponent implements OnInit, OnDestroy {
  private readonly api = inject(WorkspaceAppGovernanceApi);
  private readonly workspace = inject(WorkspaceService);
  private readonly ledger = new WorkspaceAppIdempotencyLedger();
  private requestSequence = 0;
  private destroyed = false;
  private readonly unregisterWorkspaceReset = this.workspace.registerContextReset(() => {
    this.requestSequence += 1;
    this.ledger.clear();
    this.catalog.set([]);
    this.pending.set(null);
    this.receipt.set(null);
    this.error.set(null);
    this.loading.set(false);
    this.busy.set(false);
    queueMicrotask(() => {
      if (!this.destroyed) this.load();
    });
  });

  readonly isAdmin = this.workspace.isAdmin;
  readonly catalog = signal<WorkspaceAppCatalogItem[]>([]);
  readonly pending = signal<PendingWorkspaceAppPlan | null>(null);
  readonly receipt = signal<WorkspaceAppLifecycleApplyResponse | null>(null);
  readonly loading = signal(false);
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly installedCount = computed(() => (
    this.catalog().filter((item) => this.isInstalled(item)).length
  ));

  ngOnInit(): void {
    this.load();
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    this.requestSequence += 1;
    this.unregisterWorkspaceReset();
  }

  load(): void {
    if (!this.isAdmin()) {
      this.catalog.set([]);
      this.loading.set(false);
      return;
    }
    const scope = this.workspace.captureRequestScope();
    if (!scope.workspaceSlug || !scope.workspaceId) {
      this.error.set('No active workspace is available.');
      return;
    }
    const sequence = ++this.requestSequence;
    this.loading.set(true);
    this.error.set(null);
    forkJoin({
      manifests: this.api.manifests(scope.workspaceSlug),
      installations: this.api.installations(scope.workspaceSlug),
    }).subscribe({
      next: ({ manifests, installations }) => {
        if (!this.isCurrent(sequence, scope)) return;
        if (
          manifests.workspace_id !== scope.workspaceId
          || installations.workspace_id !== scope.workspaceId
        ) {
          this.loading.set(false);
          this.error.set('The Workspace App registry returned another tenant identity.');
          return;
        }
        this.catalog.set(buildWorkspaceAppCatalog(
          manifests.manifests,
          installations.installations,
        ));
        this.loading.set(false);
      },
      error: (error) => {
        if (!this.isCurrent(sequence, scope)) return;
        this.loading.set(false);
        this.error.set(this.errorMessage(error, 'The Workspace App registry is unavailable.'));
      },
    });
  }

  plan(action: WorkspaceAppAction): void {
    if (this.busy() || !this.isAdmin()) return;
    const scope = this.workspace.captureRequestScope();
    if (!scope.workspaceSlug || !scope.workspaceId) return;
    const sequence = ++this.requestSequence;
    this.busy.set(true);
    this.pending.set(null);
    this.receipt.set(null);
    this.error.set(null);
    this.api.plan(action.request, scope.workspaceSlug).subscribe({
      next: (plan) => {
        if (!this.isCurrent(sequence, scope)) return;
        this.busy.set(false);
        if (
          plan.workspace_id !== scope.workspaceId
          || plan.app_id !== action.request.app_id
          || plan.operation !== action.request.operation
          || plan.to.manifest_digest !== (
            action.request.operation === 'uninstall'
              ? null
              : action.request.expected_manifest_digest
          )
        ) {
          this.error.set('The lifecycle plan does not match the selected manifest contract.');
          return;
        }
        this.pending.set({ request: action.request, plan, scope });
      },
      error: (error) => {
        if (!this.isCurrent(sequence, scope)) return;
        this.busy.set(false);
        this.error.set(this.errorMessage(error, 'The Workspace App plan was rejected.'));
      },
    });
  }

  apply(): void {
    const pending = this.pending();
    if (!pending || this.busy() || !this.isAdmin()) return;
    if (!this.workspace.isRequestScopeCurrent(pending.scope) || !pending.scope.workspaceSlug) {
      this.pending.set(null);
      this.ledger.clear();
      this.error.set('The workspace changed. Create a new lifecycle plan.');
      return;
    }
    const sequence = ++this.requestSequence;
    const idempotencyKey = this.ledger.key(pending.scope, pending.plan);
    this.busy.set(true);
    this.error.set(null);
    this.api.apply(
      pending.request,
      pending.plan.plan_sha256,
      idempotencyKey,
      pending.scope.workspaceSlug,
    ).subscribe({
      next: (result) => {
        if (!this.isCurrent(sequence, pending.scope)) return;
        this.busy.set(false);
        if (
          result.workspace_id !== pending.scope.workspaceId
          || result.app_id !== pending.plan.app_id
          || result.operation !== pending.plan.operation
          || result.plan_sha256 !== pending.plan.plan_sha256
          || result.manifest_digest !== pending.request.expected_manifest_digest
        ) {
          this.error.set('The lifecycle receipt does not match the applied plan.');
          return;
        }
        this.ledger.complete(pending.scope, pending.plan);
        this.pending.set(null);
        this.receipt.set(result);
        this.load();
      },
      error: (error) => {
        if (!this.isCurrent(sequence, pending.scope)) return;
        this.busy.set(false);
        this.error.set(this.errorMessage(error, 'The Workspace App apply was rejected.'));
      },
    });
  }

  discardPlan(): void {
    this.pending.set(null);
    this.error.set(null);
  }

  actions(item: WorkspaceAppCatalogItem): WorkspaceAppAction[] {
    return workspaceAppActions(item);
  }

  isInstalled(item: WorkspaceAppCatalogItem): boolean {
    return item.installation?.state === 'installed';
  }

  displayManifest(item: WorkspaceAppCatalogItem): WorkspaceAppManifestEntry | null {
    return item.versions.find((entry) => (
      entry.version === item.installation?.version
      && entry.manifest_digest === item.installation?.manifest_digest
    )) ?? item.versions.at(-1) ?? null;
  }

  shortDigest(value: string | null | undefined): string {
    return value ? `${value.slice(0, 12)}…${value.slice(-8)}` : '—';
  }

  private isCurrent(sequence: number, scope: WorkspaceRequestScope): boolean {
    return workspaceAppResponseIsCurrent(
      sequence,
      this.requestSequence,
      scope,
      this.workspace.captureRequestScope(),
    ) && this.workspace.isRequestScopeCurrent(scope);
  }

  private errorMessage(error: unknown, fallback: string): string {
    const candidate = error as {
      error?: { detail?: string | { code?: string; message?: string } };
    };
    const detail = candidate?.error?.detail;
    if (typeof detail === 'string' && detail) return detail;
    if (detail && typeof detail === 'object') {
      return detail.message || detail.code || fallback;
    }
    return fallback;
  }
}
