import { ChangeDetectionStrategy, Component, DestroyRef, Input, OnChanges, computed, inject, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService, workspaceSettingFeature } from '@app/core/workspace.service';
import { ChatPanelComponent } from '../chat/chat-panel.component';

/** Start a new conversation from a confirmed Capture publication, not its interview. */
@Component({
  selector: 'app-capture-published-chat',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ChatPanelComponent],
  template: `
    @if (enabled() && collection && proposalId) {
      <section class="ck-surface" style="padding:16px; border-radius:var(--ck-radius-lg); min-width:0;">
        <p style="margin:0 0 12px; color:var(--ck-fg-2); overflow-wrap:anywhere;">
          {{ i18n.t('capture.publish.chat_scope', { collection }) }}
        </p>
        @if (contextId(); as id) {
          <button type="button" class="ck-btn-quiet" (click)="close()">{{ i18n.t('capture.publish.chat_close') }}</button>
          <div style="height:65vh; min-height:320px; margin-top:12px;">
            <app-chat-panel [contextId]="id" [contextCollection]="collection" [freshSession]="true" [compact]="true" />
          </div>
        } @else {
          <button type="button" class="ck-btn-accent" [disabled]="busy()" (click)="open()">
            {{ i18n.t(busy() ? 'capture.publish.chat_opening' : 'capture.publish.chat_open') }}
          </button>
        }
        @if (failed()) {
          <p role="alert" style="color:var(--ck-signal-neg); margin:12px 0 0;">{{ i18n.t('capture.publish.chat_failed') }}</p>
        }
      </section>
    }
  `,
  styles: [`
    button { padding: 8px 12px; border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-md); font: inherit; cursor: pointer; }
    button:disabled { cursor: wait; opacity: .6; }
    button:focus-visible { outline: 2px solid var(--ck-signal-cool); outline-offset: 3px; }
  `],
})
export class CapturePublishedChatComponent implements OnChanges {
  @Input() collection = '';
  @Input() proposalId = '';
  readonly i18n = inject(I18nService);
  private readonly api = inject(CanonicalApiService);
  private readonly workspace = inject(WorkspaceService);
  readonly enabled = computed(() => workspaceSettingFeature(this.workspace.current(), 'adoption_experience_v1'));
  readonly contextId = signal<string | null>(null);
  readonly busy = signal(false);
  readonly failed = signal(false);
  private request?: Subscription;
  private generation = 0;
  private publicationScope = this.workspace.captureRequestScope();

  constructor() {
    const unregister = this.workspace.registerContextReset(() => this.close());
    inject(DestroyRef).onDestroy(() => { unregister(); this.close(); });
  }

  ngOnChanges(): void {
    this.close();
    this.publicationScope = this.workspace.captureRequestScope();
  }

  close(): void {
    this.generation++;
    this.request?.unsubscribe();
    this.contextId.set(null);
    this.busy.set(false);
    this.failed.set(false);
  }

  open(): void {
    if (!this.enabled() || this.busy() || this.contextId()) return;
    const scope = this.publicationScope;
    const collection = this.collection.trim();
    if (!this.workspace.isRequestScopeCurrent(scope) || !scope.workspaceSlug || !scope.workspaceId || !this.proposalId || !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$/.test(collection)) {
      this.failed.set(true);
      return;
    }
    const generation = this.generation;
    this.busy.set(true);
    this.failed.set(false);
    this.request = this.api.createContext({
      name: this.i18n.t('capture.publish.chat_context', { collection }),
      data_refs: [], // Query the published collection; do not attach interview memory.
      environment_state: { collection },
      business_constraints: { source: 'capture_publication', proposal_id: this.proposalId },
      ephemeral: true,
      ttl_hours: 24,
    }, { workspaceSlug: scope.workspaceSlug }).subscribe({
      next: context => {
        if (generation !== this.generation || !this.workspace.isRequestScopeCurrent(scope)) return;
        this.busy.set(false);
        if (!context?.id || context.environment_state?.['collection'] !== collection) {
          this.failed.set(true);
          return;
        }
        this.contextId.set(context.id);
      },
      error: () => {
        if (generation !== this.generation || !this.workspace.isRequestScopeCurrent(scope)) return;
        this.busy.set(false);
        this.failed.set(true);
      },
    });
  }
}
