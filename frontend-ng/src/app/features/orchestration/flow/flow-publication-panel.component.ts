import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { DOCUMENT } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subscription, take } from 'rxjs';
import { A11yModule } from '@angular/cdk/a11y';
import { Router } from '@angular/router';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { ToastrService } from 'ngx-toastr';
import { IconComponent } from '@app/shared/ui/icon.component';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { apiCode, studioError } from '@app/features/experience/studio/studio-api.service';
import {
  ExperienceApiMissingError,
  SystemHomeService,
  type SystemHomeCreateInput,
} from '@app/features/experience/system-home.service';
import {
  compileSystemHome,
  firstManualIngress,
  hasHitlHint,
  systemHomeBlocker,
  uniqueBindingKey,
  uniqueSlug,
} from '@app/features/experience/runtime/system-home';
import { FlowStore } from './flow.store';
import { FlowPersistenceService } from './flow-persistence.service';

/** Explicit, secret-free semantic review between a saved server draft and the
 * immutable published pointer. Publishing never changes System activation. */
@Component({
  selector: 'app-flow-publication-panel',
  standalone: true,
  imports: [A11yModule, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './flow-publication-panel.component.scss',
  template: `
    @if (persistence.publishReviewOpen()) {
      <div class="ck-publish" role="presentation">
        <button
          type="button"
          class="ck-publish__backdrop"
          [attr.aria-label]="i18n.t('flow.publish.close')"
          [disabled]="persistence.publishing() || activating()"
          (click)="close()"
        ></button>
        <section
          class="ck-publish__dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="ck-publish-title"
          cdkTrapFocus
          [cdkTrapFocusAutoCapture]="true"
          (keydown.escape)="close()"
        >
          <header class="ck-publish__header">
            <div>
              <p class="ck-publish__eyebrow">{{ i18n.t('flow.publish.eyebrow') }}</p>
              <h2 id="ck-publish-title">{{ i18n.t(persistence.publishSucceeded()
                ? 'experience.home.section.title' : 'flow.publish.title') }}</h2>
              <p>{{ i18n.t(persistence.publishSucceeded()
                ? 'experience.home.section.body' : 'flow.publish.subtitle') }}</p>
            </div>
            <button
              type="button"
              class="ck-publish__close"
              [attr.aria-label]="i18n.t('flow.publish.close')"
              [disabled]="persistence.publishing() || activating()"
              (click)="close()"
            >
              <app-icon name="x" [size]="16" />
            </button>
          </header>

          <div class="ck-publish__identities">
            <span>
              {{ i18n.t('flow.toolbar.version.draft', { revision: persistence.draftRevision() ?? '' }) }}
              <code>{{ shortHash(persistence.savedFlowSha256()) }}</code>
            </span>
            <app-icon name="arrow-right" [size]="13" />
            <span>
              {{ i18n.t('flow.toolbar.version.published', { version: persistence.publishedVersionNumber() ?? '' }) }}
              <code>{{ shortHash(persistence.publishedFlowSha256()) }}</code>
            </span>
          </div>

          @switch (persistence.publishDiffState()) {
            @case ('loading') {
              <div class="ck-publish__state" role="status">
                <app-icon name="loader-2" [size]="15" class="is-spinning" />
                {{ i18n.t('flow.publish.diff.loading') }}
              </div>
            }
            @case ('error') {
              <div class="ck-publish__state is-error" role="alert">
                <app-icon name="alert-triangle" [size]="15" />
                {{ persistence.publishError() || i18n.t('flow.publish.diff.error') }}
              </div>
            }
            @case ('ready') {
              @if (persistence.publishDiff(); as diff) {
                <div
                  class="ck-publish__summary"
                  [attr.aria-label]="i18n.t('flow.publish.diff.aria')"
                >
                  <span data-impact="breaking">{{
                    i18n.t('flow.publish.diff.breaking', { count: diff.summary.breaking })
                  }}</span>
                  <span data-impact="behavioral">{{
                    i18n.t('flow.publish.diff.behavioral', { count: diff.summary.behavioral })
                  }}</span>
                  <span data-impact="presentation">{{
                    i18n.t('flow.publish.diff.presentation', { count: diff.summary.presentation })
                  }}</span>
                </div>

                <ol
                  class="ck-publish__changes"
                  [attr.aria-label]="i18n.t('flow.publish.diff.changes.aria')"
                >
                  @for (change of diff.changes; track change.path + change.subject) {
                    <li [attr.data-impact]="change.impact">
                      <div class="ck-publish__change-head">
                        <strong>{{ change.category === 'mandate' ? i18n.t('mandate_system.publication.impact') : change.impact }}</strong>
                        <span>{{ change.category === 'mandate' ? i18n.t('mandate_system.publication.category') : change.category }}</span>
                        <code>{{ change.subject }}</code>
                      </div>
                      <p>{{ change.category === 'mandate' ? i18n.t('mandate_system.publication.description') : change.description }}</p>
                    </li>
                  } @empty {
                    <li class="is-empty">{{ i18n.t('flow.publish.diff.empty') }}</li>
                  }
                </ol>

                @if (diff.summary.breaking > 0) {
                  <label class="ck-publish__ack">
                    <input
                      type="checkbox"
                      [checked]="persistence.breakingChangeAcknowledged()"
                      (change)="onBreakingAcknowledgement($event)"
                    />
                    <span>{{ i18n.t('flow.publish.ack') }}</span>
                  </label>
                }
              }
            }
          }

          @if (!persistence.publishSucceeded()) {
            <label class="ck-publish__message" for="ck-publish-message">
              <span>{{ i18n.t('flow.publish.message') }}</span>
              <textarea
                id="ck-publish-message"
                rows="3"
                maxlength="2000"
                [placeholder]="i18n.t('flow.publish.message.placeholder')"
                [value]="message()"
                [disabled]="persistence.publishing()"
                cdkFocusInitial
                (input)="onMessage($event)"
              ></textarea>
            </label>
          }

          @if (persistence.publishError(); as error) {
            <p class="ck-publish__error" role="alert">{{ error }}</p>
          }

          @if (showHome()) {
            <aside class="ck-publish__home">
              @if (persistence.publishSucceeded()) {
                <p class="ck-publish__home-ready">{{ i18n.t('experience.home.ready') }}</p>
              }
              @if (!persistence.publishSucceeded()) {
                <h3>{{ i18n.t('experience.home.section.title') }}</h3>
                <p>{{ i18n.t('experience.home.section.body') }}</p>
              }
              @if (persistence.systemStatus() !== 'active') {
                <p class="ck-publish__home-note">{{ i18n.t('experience.home.activate.description') }}</p>
              }
              <div class="ck-publish__home-actions">
                <button type="button" [disabled]="activating()" (click)="previewHome()">
                  {{ i18n.t('experience.home.preview') }}
                </button>
                @if (persistence.systemStatus() !== 'active') {
                  <button type="button" class="is-primary" [disabled]="!canActivate()" (click)="activateSystem()">
                    {{ i18n.t(activating() ? 'experience.home.activate.busy' : 'experience.home.activate') }}
                  </button>
                } @else {
                  <button
                    type="button"
                    class="is-primary"
                    [disabled]="creating() || persistence.actionsDisabled() || apiMissing() || homeBlocker() !== null"
                    (click)="createHome()"
                  >
                    @if (creating()) {
                      {{ i18n.t('experience.home.create.busy') }}
                    } @else {
                      {{ i18n.t('experience.home.create') }}
                    }
                  </button>
                }
              </div>
              @if (activationError(); as err) {
                <p class="ck-publish__error" role="alert">{{ err }}</p>
              }
              @if (apiMissing()) {
                <p class="ck-publish__home-note">{{ i18n.t('experience.home.create.unavailable') }}</p>
              }
              @if (homeBlocker(); as blocker) {
                <p class="ck-publish__home-note" role="status">
                  {{ i18n.t(blocker === 'missing-manual-ingress'
                    ? 'experience.home.create.no_manual_ingress'
                    : 'experience.home.create.unsupported_schema') }}
                </p>
              }
              @if (createError(); as err) {
                <p class="ck-publish__error" role="alert">{{ err }}</p>
              }
            </aside>
          }

          <footer class="ck-publish__actions">
            <button type="button" (click)="close()" [disabled]="persistence.publishing() || activating()">
              {{ i18n.t('flow.publish.cancel') }}
            </button>
            @if (!persistence.publishSucceeded()) {
              <button
                type="button"
                class="is-primary"
                [disabled]="!canSubmit()"
                (click)="publish()"
              >
                @if (persistence.publishing()) {
                  <app-icon name="loader-2" [size]="14" class="is-spinning" />
                  {{ i18n.t('flow.publish.submitting') }}
                } @else {
                  <app-icon name="upload-cloud" [size]="14" />
                  {{ i18n.t('flow.publish.submit') }}
                }
              </button>
            }
          </footer>
        </section>
      </div>
    }
  `,
})
export class FlowPublicationPanelComponent {
  protected readonly persistence = inject(FlowPersistenceService);
  readonly i18n = inject(I18nService);
  private readonly workspace = inject(WorkspaceService);
  private readonly store = inject(FlowStore);
  private readonly home = inject(SystemHomeService);
  private readonly router = inject(Router);
  private readonly navigation = inject(ZoomContextService);
  private readonly toastr = inject(ToastrService);
  private readonly document = inject(DOCUMENT);
  private readonly canonical = inject(CanonicalApiService);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly message = signal('');
  protected readonly activating = signal(false);
  protected readonly activationError = signal<string | null>(null);
  protected readonly creating = signal(false);
  protected readonly apiMissing = signal(false);
  protected readonly createError = signal<string | null>(null);
  private pendingHomeCreate: SystemHomeCreateInput | null = null;
  private activationRequest: Subscription | null = null;
  private activationSystemId: string | null = null;
  private activationVersionId: string | null = null;
  private previousFocus: HTMLElement | null = null;
  protected readonly canSubmit = computed(
    () =>
      this.message().trim().length > 0 &&
      !this.activating() &&
      this.persistence.canConfirmPublication(),
  );
  protected readonly showHome = computed(
    () =>
      this.workspace.experienceStudioV1Enabled() &&
      this.persistence.publishedExecutionContract() !== null,
  );
  protected readonly homeBlocker = computed(() =>
    systemHomeBlocker(this.persistence.publishedExecutionContract()),
  );
  protected readonly canActivate = computed(() =>
    this.showHome() && this.homeBlocker() === null
    && !!this.persistence.systemId()
    && !!this.persistence.publishedVersionId()
    && this.persistence.publishedContractReady()
    && this.persistence.systemStatus() !== null
    && this.persistence.systemStatus() !== 'active'
    && !this.persistence.actionsDisabled() && !this.activating() && !this.creating(),
  );

  constructor() {
    const unregister = this.workspace.registerContextReset(() => this.cancelActivation());
    this.destroyRef.onDestroy(() => { unregister(); this.cancelActivation(); });
    effect(() => {
      const systemId = this.persistence.systemId();
      const publishedVersionId = this.persistence.publishedVersionId();
      if (this.activationSystemId && (this.activationSystemId !== systemId
        || this.activationVersionId !== publishedVersionId)) this.cancelActivation();
      if (this.persistence.publishReviewOpen()) {
        this.previousFocus = this.document.activeElement instanceof HTMLElement
          ? this.document.activeElement
          : null;
      } else {
        this.message.set('');
        this.createError.set(null);
        this.activationError.set(null);
        this.pendingHomeCreate = null;
      }
    });
  }

  protected shortHash(value: string | null): string {
    return value ? value.slice(0, 10) : '—';
  }

  protected onMessage(event: Event): void {
    this.message.set((event.target as HTMLTextAreaElement).value);
  }

  protected onBreakingAcknowledgement(event: Event): void {
    this.persistence.setBreakingChangeAcknowledged(
      (event.target as HTMLInputElement).checked,
    );
  }

  protected publish(): void {
    if (this.activating()) return;
    this.persistence.publishDraft(this.message());
  }

  protected close(): void {
    if (this.activating() || this.persistence.publishing()) return;
    const target = this.previousFocus;
    this.persistence.closePublicationReview();
    queueMicrotask(() => target?.focus());
  }

  protected activateSystem(): void {
    const systemId = this.persistence.systemId();
    const publishedVersionId = this.persistence.publishedVersionId();
    if (!systemId || !publishedVersionId || !this.canActivate()) return;
    const scope = this.workspace.captureRequestScope();
    const current = () => this.workspace.isRequestScopeCurrent(scope)
      && this.persistence.systemId() === systemId
      && this.persistence.publishedVersionId() === publishedVersionId;
    this.activating.set(true);
    this.activationError.set(null);
    this.activationSystemId = systemId;
    this.activationVersionId = publishedVersionId;
    this.activationRequest = this.canonical.updateSystem(systemId, { status: 'active' }, {
      expected_published_version_id: publishedVersionId, propagateErrors: true,
    })
      .pipe(take(1), takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: system => {
          if (!current()) return;
          this.activating.set(false);
          if (system?.id !== systemId || system.status !== 'active') {
            this.activationError.set(this.i18n.t('experience.home.activate.error'));
            return;
          }
          this.persistence.systemStatus.set(system.status);
        },
        error: error => {
          if (!current()) return;
          this.activating.set(false);
          this.activationError.set(error instanceof HttpErrorResponse && error.status === 403
            ? this.i18n.t('experience.home.activate.denied')
            : apiCode(error) === 'SYSTEM_PUBLISHED_VERSION_MISMATCH'
            ? this.i18n.t('experience.home.activate.stale')
            : studioError(this.i18n, error, 'experience.home.activate.error'));
        },
      });
  }

  private cancelActivation(): void {
    this.activationRequest?.unsubscribe();
    this.activationRequest = null;
    this.activationSystemId = null;
    this.activationVersionId = null;
    this.activating.set(false);
    this.activationError.set(null);
  }

  protected previewHome(): void {
    const compiled = this.compileHome();
    if (!compiled) return;
    const systemId = this.persistence.systemId();
    const publishedVersionId = this.persistence.publishedVersionId();
    const binding = compiled.ingressId && systemId && publishedVersionId
      ? {
          binding_key: compiled.bindingKey,
          system_id: systemId,
          published_flow_version_id: publishedVersionId,
          ingress_id: compiled.ingressId,
          confirmation_policy: 'confirm',
          on_unavailable: 'unavailable',
        }
      : null;
    this.home.provide(compiled.document, binding);
    const tree = this.router.parseUrl(this.navigation.leafUrl('create-preview'));
    tree.queryParams = { ...tree.queryParams, source: 'home' };
    void this.router.navigateByUrl(tree);
  }

  protected createHome(): void {
    const compiled = this.compileHome();
    const systemId = this.persistence.systemId();
    const publishedVersionId = this.persistence.publishedVersionId();
    if (
      !compiled
      || !systemId
      || !publishedVersionId
      || this.persistence.systemStatus() !== 'active'
      || this.persistence.actionsDisabled()
      || this.creating()
      || this.apiMissing()
      || this.homeBlocker() !== null
    ) {
      return;
    }
    this.creating.set(true);
    this.createError.set(null);
    const nonce = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
    const name = compiled.systemName;
    const input = this.pendingHomeCreate ?? {
      name,
      slug: uniqueSlug(name, nonce),
      languages: [this.i18n.locale()],
      document: compiled.document,
      bindingKey: compiled.bindingKey,
      systemId,
      publishedVersionId,
      ingressId: compiled.ingressId,
    };
    this.pendingHomeCreate = input;
    this.home
      .createDraft(input)
      .subscribe({
        next: (created) => {
          this.creating.set(false);
          this.pendingHomeCreate = null;
          this.toastr.success(this.i18n.t('experience.home.created'));
          void this.router.navigateByUrl(this.navigation.leafUrl('create-app-edit', { ref: created.id }));
        },
        error: (err: unknown) => {
          this.creating.set(false);
          if (err instanceof ExperienceApiMissingError) {
            this.apiMissing.set(true);
            return;
          }
          this.createError.set(this.i18n.t('experience.home.create.error'));
        },
      });
  }

  private compileHome(): {
    document: ReturnType<typeof compileSystemHome>;
    bindingKey: string;
    ingressId: string | null;
    systemName: string;
  } | null {
    const contract = this.persistence.publishedExecutionContract();
    if (!contract) return null;
    const systemName =
      (this.persistence.systemDisplayName() || '').trim() ||
      this.i18n.t('experience.home.preview.title');
    const ingress = firstManualIngress(contract);
    const nonce = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
    const bindingKey = uniqueBindingKey(systemName, ingress?.ingress_id ?? 'submit', nonce);
    const kinds = this.store.snapshot().nodes.map((node) => node.kind ?? '');
    return {
      systemName,
      bindingKey,
      ingressId: ingress?.ingress_id ?? null,
      document: compileSystemHome({
        systemName,
        bindingKey,
        ingress,
        hasHitl: hasHitlHint(contract, kinds),
        labels: {
          subtitle: this.i18n.t('experience.home.subtitle'),
          submit: this.i18n.t('experience.runtime.form.submit'),
          missingEntry: this.i18n.t('experience.home.missing_entry'),
          approvalTitle: this.i18n.t('experience.runtime.approval.title'),
          approvalBody: this.i18n.t('experience.home.approval.body'),
        },
      }),
    };
  }
}
