import { ChangeDetectionStrategy, Component, DestroyRef, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { AuthStore } from '@app/store/auth.store';
import { normalizedResolutionPolicy, sameResolutionPolicy, type ResolutionPolicy, type ResolutionPolicyEvidence, type ResolutionPolicyState } from './claims-resolution-policy.model';

type PolicyMessage = 'load_failed' | 'saved' | 'conflict' | 'unknown' | 'verified' | 'not_recorded' | 'invalid' | 'forbidden' | 'document_unavailable';

@Component({
  selector: 'app-claims-resolution-policy', standalone: true, imports: [FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styles: [`
    :host{display:block;min-width:0}details.policy{border-top:1px solid var(--ck-stroke-2);padding:14px 0}
    summary{cursor:pointer;font-size:13px;font-weight:600;line-height:24px}p{font-size:12px;line-height:1.6;margin:10px 0;color:var(--ck-fg-2)}
    dl{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:14px 0}dt,label{font-size:12px;color:var(--ck-fg-2)}dd{margin:4px 0 0;font-size:14px;overflow-wrap:anywhere}
    .policy-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:14px 0}label{display:flex;flex-direction:column;gap:6px}.wide{grid-column:1/-1}
    input{width:100%;min-width:0;box-sizing:border-box;min-height:36px;padding:7px 9px;border:1px solid var(--ck-stroke-2);border-radius:4px;color:var(--ck-fg-1);background:var(--ck-bg-inset);font:inherit}
    button{min-height:32px;padding:5px 10px;border:1px solid var(--ck-stroke-2);border-radius:4px;color:var(--ck-fg-1);background:var(--ck-bg-panel);font:inherit;font-size:12px;cursor:pointer}
    button.primary{background:var(--ck-signal-cool);color:var(--ck-on-signal)}button:disabled{opacity:.5;cursor:default}.actions{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}
    button:focus-visible,input:focus-visible,summary:focus-visible{outline:2px solid var(--ck-signal-cool);outline-offset:3px}
    .notice{border-inline-start:2px solid var(--ck-signal-cool);padding-inline-start:10px}.notice[data-problem=true]{border-color:var(--ck-signal-warn)}
    code{font-size:12px;overflow-wrap:anywhere;color:var(--ck-fg-2)}.applied-differs{padding:10px;border:1px solid var(--ck-stroke-2);border-radius:4px}
    @media(max-width:480px){dl,.policy-fields{grid-template-columns:1fr}}
  `],
  template: `
    <details class="policy" [open]="opened()" (toggle)="toggle($event)" data-testid="claims-resolution-policy">
      <summary>{{ i18n.t('experience.claims.policy.title') }}</summary>
      @if (loading()) { <p role="status">{{ i18n.t('common.loading') }}</p> }
      @if (state(); as current) {
        @if (applied(); as used) {
          <p [class.applied-differs]="used.sha256 !== current.sha256">{{ i18n.t(used.sha256 === current.sha256 ? 'experience.claims.policy.applied_current' : 'experience.claims.policy.applied_previous') }}</p>
          @if (used.sha256 !== current.sha256) {
            <dl><div><dt>{{ i18n.t('experience.claims.policy.document') }}</dt><dd>{{ used.document_key }} · {{ used.document_version }}</dd></div><div><dt>{{ i18n.t('experience.claims.policy.manager') }}</dt><dd>{{ money(used.manager_approval_above, used.currency) }}</dd></div></dl>
          }
        }
        <p>{{ i18n.t('experience.claims.policy.current') }} · {{ i18n.t(current.source === 'legacy_defaults' ? 'experience.claims.policy.legacy' : 'experience.claims.policy.configured') }}</p>
        @if (!editing()) {
          <dl>
            <div><dt>{{ i18n.t('experience.claims.policy.document') }}</dt><dd>{{ current.policy.document_key }} · {{ current.policy.document_version }}</dd></div>
            <div><dt>{{ i18n.t('experience.claims.policy.manager') }}</dt><dd>{{ money(current.policy.manager_approval_above, current.policy.currency) }}</dd></div>
          </dl>
          <p>{{ i18n.t('experience.claims.policy.guards') }}</p>
          <details><summary>{{ i18n.t('experience.claims.policy.revision') }}</summary><code>{{ current.sha256 }}</code></details>
          <div class="actions">
            <button type="button" [disabled]="loading() || busy() || unresolved()" (click)="load()">{{ i18n.t('experience.claims.policy.reload') }}</button>
            @if (current.can_configure) { <button type="button" [disabled]="loading() || busy() || unresolved()" (click)="edit()">{{ i18n.t('experience.claims.policy.edit') }}</button> }
          </div>
        } @else {
          <p class="notice">{{ i18n.t('experience.claims.policy.change_notice') }}</p>
          <div class="policy-fields">
            <label>{{ i18n.t('experience.claims.policy.currency') }}<input [(ngModel)]="draft.currency" maxlength="3" [disabled]="busy() || unresolved()" /></label>
            <label>{{ i18n.t('experience.claims.policy.manager') }}<input [(ngModel)]="draft.manager_approval_above" inputmode="decimal" [disabled]="busy() || unresolved()" /></label>
          </div>
          <details><summary>{{ i18n.t('experience.claims.policy.document_revision') }}</summary>
            <p>{{ i18n.t('experience.claims.policy.document_notice') }}</p>
            <div class="policy-fields">
              <label>{{ i18n.t('experience.claims.policy.reference') }}<input [(ngModel)]="draft.document_key" maxlength="160" [disabled]="busy() || unresolved()" /></label>
              <label>{{ i18n.t('experience.claims.policy.version') }}<input [(ngModel)]="draft.document_version" maxlength="64" [disabled]="busy() || unresolved()" /></label>
              <label class="wide">{{ i18n.t('experience.claims.policy.hash') }}<input [(ngModel)]="draft.document_sha256" maxlength="64" [disabled]="busy() || unresolved()" /></label>
            </div>
          </details>
          <div class="actions">
            <button type="button" class="primary" [disabled]="busy() || unresolved() || !valid()" (click)="save()">{{ i18n.t('experience.claims.policy.save') }}</button>
            <button type="button" [disabled]="busy() || unresolved()" (click)="editing.set(false)">{{ i18n.t('experience.claims.policy.cancel') }}</button>
          </div>
        }
      }
      @if (message(); as notice) {
        <p class="notice" [attr.data-problem]="!['saved', 'verified', 'not_recorded'].includes(notice)" [attr.role]="['saved', 'verified', 'not_recorded'].includes(notice) ? 'status' : 'alert'">{{ i18n.t('experience.claims.policy.' + notice) }}</p>
        @if (unresolved() || notice === 'load_failed' || notice === 'conflict') { <button type="button" [disabled]="busy() || loading()" (click)="verify()">{{ i18n.t('experience.claims.policy.reload') }}</button> }
      }
    </details>
  `,
})
export class ClaimsResolutionPolicyComponent {
  readonly i18n = inject(I18nService);
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly auth = inject(AuthStore);
  private readonly destroy = inject(DestroyRef);
  readonly applied = input<ResolutionPolicyEvidence | null>(null);
  readonly state = signal<ResolutionPolicyState | null>(null);
  readonly opened = signal(false); readonly loading = signal(false); readonly busy = signal(false);
  readonly editing = signal(false); readonly unresolved = signal(false);
  readonly message = signal<PolicyMessage | null>(null);
  draft: ResolutionPolicy = { schema_version: 1, document_key: '', document_version: '', document_sha256: '', currency: 'EUR', manager_approval_above: '' };
  private attempted: ResolutionPolicy | null = null;
  private generation = 0;

  constructor() {
    effect(() => {
      this.workspace.current()?.id; this.auth.authEpoch();
      this.reset();
    });
    this.destroy.onDestroy(() => this.generation++);
  }
  private reset(): void {
    this.generation++; this.state.set(null); this.opened.set(false); this.loading.set(false);
    this.busy.set(false); this.editing.set(false); this.unresolved.set(false); this.message.set(null); this.attempted = null;
  }
  toggle(event: Event): void {
    const open = (event.target as HTMLDetailsElement).open;
    this.opened.set(open);
    if (open && !this.state() && !this.loading()) void this.load();
  }
  valid(): boolean { return !!normalizedResolutionPolicy(this.draft); }
  edit(): void {
    if (!this.state()?.can_configure || this.loading() || this.busy() || this.unresolved()) return;
    this.draft = { ...this.state()!.policy }; this.message.set(null); this.editing.set(true);
  }
  async load(verify = false): Promise<void> {
    if (this.loading()) return;
    const generation = this.generation, scope = this.workspace.captureRequestScope();
    const current = () => generation === this.generation && this.workspace.isRequestScopeCurrent(scope);
    this.loading.set(true);
    try {
      const result = await firstValueFrom(this.api.get<ResolutionPolicyState>('/ecommerce-claims/policy'));
      if (!current()) return;
      this.state.set(result);
      if (verify && this.attempted && sameResolutionPolicy(this.attempted, result.policy)) {
        this.message.set('verified'); this.editing.set(false);
      } else if (verify) { this.message.set('not_recorded'); this.editing.set(false); }
      else this.message.set(null);
      this.unresolved.set(false); this.attempted = null;
    } catch { if (current()) this.message.set(this.unresolved() ? 'unknown' : 'load_failed'); }
    finally { if (current()) this.loading.set(false); }
  }
  async verify(): Promise<void> { await this.load(true); }
  async save(): Promise<void> {
    const currentState = this.state(), policy = normalizedResolutionPolicy(this.draft);
    if (!currentState?.can_configure || !policy || this.busy() || this.unresolved()) return;
    const generation = this.generation, scope = this.workspace.captureRequestScope();
    const current = () => generation === this.generation && this.workspace.isRequestScopeCurrent(scope);
    this.busy.set(true); this.message.set(null); this.attempted = policy;
    try {
      const result = await firstValueFrom(this.api.put<ResolutionPolicyState>('/ecommerce-claims/policy', { expected_sha256: currentState.sha256, policy }));
      if (!current()) return;
      this.state.set(result); this.editing.set(false); this.message.set('saved'); this.attempted = null;
    } catch (error) {
      if (!current()) return;
      const status = Number((error as { status?: number })?.status ?? 0);
      const code = (error as { error?: { detail?: { code?: string } } })?.error?.detail?.code;
      if (status === 409 && code === 'CLAIM_POLICY_CONFLICT') { this.message.set('conflict'); this.unresolved.set(true); }
      else if (status === 409 && code === 'CLAIM_POLICY_DOCUMENT_UNAVAILABLE') this.message.set('document_unavailable');
      else if (status === 403) {
        this.state.update(value => value ? { ...value, can_configure: false } : value);
        this.editing.set(false); this.message.set('forbidden'); this.attempted = null;
      }
      else if (status === 422) this.message.set('invalid');
      else { this.message.set('unknown'); this.unresolved.set(true); }
    } finally { if (current()) this.busy.set(false); }
  }
  money(value: string, currency: string): string {
    try { return new Intl.NumberFormat(this.i18n.locale(), { style: 'currency', currency }).format(Number(value)); }
    catch { return `${value} ${currency}`; }
  }
}
