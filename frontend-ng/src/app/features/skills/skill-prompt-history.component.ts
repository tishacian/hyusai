import { ChangeDetectionStrategy, Component, OnDestroy, computed, effect, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Subscription } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { WorkspaceViewContext } from '@app/core/workspace-view-context';
import { NavLinkDirective } from '@app/shared/cockpit';

interface PublishedPrompt {
  version_id: string; version_number: number; system_id: string; system_name: string; node_id: string;
  created_at: string; created_by: string; template: string; template_sha256: string; matches_current: boolean;
}
interface PromptHistory { current_template: string; current_sha256: string; entries: PublishedPrompt[] }

@Component({
  selector: 'app-skill-prompt-history', standalone: true,
  imports: [FormsModule, NavLinkDirective], changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="ck-surface history">
      <header><div><h3>{{ i18n.t('skills.prompt_history.title') }}</h3>
        <p>{{ i18n.t('skills.prompt_history.description') }}</p></div>
        <button type="button" class="ck-btn-quiet" (click)="load()" [disabled]="busy()">{{ i18n.t(history() ? 'skills.prompt_history.refresh' : 'skills.prompt_history.open') }}</button>
      </header>
      @if (history(); as data) {
        @if (data.entries.length) {
          <label>{{ i18n.t('skills.prompt_history.source') }}
            <select [ngModel]="selectedKey()" (ngModelChange)="selectedKey.set($event)" [disabled]="busy()">
              @for (entry of data.entries; track key(entry)) {
                <option [value]="key(entry)">{{ entry.system_name }} · v{{ entry.version_number }} · {{ date(entry.created_at) }} · {{ entry.node_id }}</option>
              }
            </select>
          </label>
          @if (selected(); as entry) {
            <div class="templates"><div><h4>{{ i18n.t('skills.prompt_history.current') }}</h4><pre>{{ data.current_template }}</pre></div>
              <div><h4>{{ i18n.t('skills.prompt_history.previous') }}</h4><pre>{{ entry.template }}</pre></div></div>
            <p>{{ entry.created_by }} · <a [navLink]="{leaf: 'system-flow', ref: entry.system_id}">{{ entry.system_name }} · v{{ entry.version_number }}</a></p>
            @if (entry.matches_current) { <p>{{ i18n.t('skills.prompt_history.matches') }}</p> }
            @else if (canRestore()) {
              <p>{{ i18n.t('skills.prompt_history.reach') }}</p>
              <button type="button" class="ck-btn-quiet" (click)="restore()" [disabled]="busy()">{{ i18n.t('skills.prompt_history.restore') }}</button>
            }
          }
        } @else { <p>{{ i18n.t('skills.prompt_history.empty') }}</p> }
      }
      @if (notice()) { <p role="status">{{ notice() }}</p> }
      @if (error()) { <p role="alert" style="color:var(--ck-neg)">{{ error() }}</p> }
    </section>
  `,
  styles: [`
    .history{padding:1.25rem;margin-top:.75rem;border:1px solid var(--ck-stroke-soft);border-radius:.5rem}header{display:flex;justify-content:space-between;gap:1rem;flex-wrap:wrap}h3{font-size:.875rem;font-weight:600;margin:0}h4,label{font-size:.8125rem}p{font-size:.8125rem;line-height:1.5;color:var(--ck-fg-3);margin:.65rem 0}button{padding:.45rem .75rem;font-size:.8125rem;align-self:start}button:disabled{opacity:.5}label{display:block;margin:1rem 0}select{display:block;width:100%;padding:.6rem;margin-top:.4rem;color:var(--ck-fg-1);background:var(--ck-bg-inset);border:1px solid var(--ck-stroke-soft);border-radius:.375rem}.templates{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;font-size:.8125rem;line-height:1.55;margin:.5rem 0;padding:.875rem;background:var(--ck-bg-inset);border-radius:.375rem;max-height:24rem;overflow:auto;color:var(--ck-fg-2)}a{color:var(--ck-signal-cool)}@media(max-width:700px){.templates{grid-template-columns:1fr}}
  `],
})
export class SkillPromptHistoryComponent implements OnDestroy {
  readonly slug = input.required<string>();
  readonly canRestore = input(false);
  readonly restored = output<void>();
  readonly i18n = inject(I18nService);
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);
  readonly history = signal<PromptHistory | null>(null);
  readonly selectedKey = signal('');
  readonly selected = computed(() => this.history()?.entries.find((entry) => this.key(entry) === this.selectedKey()) ?? null);
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly notice = signal<string | null>(null);
  private subscription = new Subscription();
  private readonly view = new WorkspaceViewContext(this.workspace, () => this.reset(), () => {});
  constructor() { effect(() => { this.slug(); this.view.invalidate(); this.reset(); }); }
  date(value: string): string {
    const date = new Date(value);
    return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat(this.i18n.locale(), {dateStyle: 'short', timeStyle: 'short'}).format(date) : '—';
  }
  key(entry: PublishedPrompt): string { return `${entry.version_id}:${entry.node_id}:${entry.template_sha256}`; }
  load(): void {
    const request = this.view.beginRequest();
    this.busy.set(true); this.error.set(null);
    this.subscription.add(this.api.get<PromptHistory>(`/skills/${encodeURIComponent(this.slug())}/prompt-history`).subscribe({
      next: (data) => {
        if (!this.view.isCurrent(request)) return;
        this.history.set(data); this.selectedKey.set(data.entries.length ? this.key(data.entries[0]) : ''); this.busy.set(false);
      }, error: () => { if (this.view.isCurrent(request)) { this.busy.set(false); this.error.set(this.i18n.t('skills.prompt_history.error')); } },
    }));
  }
  restore(): void {
    const entry = this.selected(); const history = this.history();
    if (!entry || !history || entry.matches_current || !this.canRestore() || this.busy()) return;
    const request = this.view.beginRequest();
    this.busy.set(true); this.error.set(null); this.notice.set(null);
    this.subscription.add(this.api.post(`/skills/${encodeURIComponent(this.slug())}/prompt-history/restore`, {
      version_id: entry.version_id, node_id: entry.node_id, template_sha256: entry.template_sha256, expected_current_sha256: history.current_sha256,
    }).subscribe({
      next: () => {
        if (!this.view.isCurrent(request)) return;
        this.busy.set(false); this.notice.set(this.i18n.t('skills.prompt_history.restored')); this.restored.emit(); this.load();
      }, error: () => { if (this.view.isCurrent(request)) { this.busy.set(false); this.error.set(this.i18n.t('skills.prompt_history.error')); } },
    }));
  }
  private reset(): void {
    this.subscription.unsubscribe(); this.subscription = new Subscription(); this.history.set(null); this.selectedKey.set('');
    this.busy.set(false); this.error.set(null); this.notice.set(null);
  }
  ngOnDestroy(): void { this.view.destroy(); }
}
