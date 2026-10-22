import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal } from '@angular/core';
import { catchError, forkJoin, map, of } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';

type Lookup =
  | { s: 'searching' }
  | { s: 'found'; workspaces: Array<{ slug: string; name: string }> }
  | { s: 'nowhere' };

/** Reader's other workspaces checked for a missing app, at most. */
const MAX_LOOKUPS = 12;

/**
 * Diagnosis for a Work app that is not published in the current workspace.
 *
 * Reads the same app in the reader's other workspaces (read only, their own
 * rights) and offers to switch when it exists there, instead of a message
 * that points at a broken publication or data connection.
 */
@Component({
  selector: 'app-work-app-elsewhere',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="elsewhere" data-testid="work-app-elsewhere" role="status">
      <h2>{{ i18n.t('experience.work.elsewhere.title', { workspace: currentName() }) }}</h2>
      @switch (lookup().s) {
        @case ('searching') { <p>{{ i18n.t('experience.work.elsewhere.searching') }}</p> }
        @case ('nowhere') { <p>{{ i18n.t('experience.work.elsewhere.nowhere') }}</p> }
        @case ('found') {
          <p>{{ i18n.t('experience.work.elsewhere.found') }}</p>
          <div class="actions">
            @for (target of found(); track target.slug) {
              <button type="button" (click)="open(target.slug)" [attr.data-testid]="'work-app-elsewhere-' + target.slug">
                {{ i18n.t('experience.work.elsewhere.open', { workspace: target.name }) }}
              </button>
            }
          </div>
        }
      }
    </section>
  `,
  styles: [`
    :host { display: block; }
    .elsewhere { padding: var(--ck-space-4); border: 1px solid var(--ck-status-info-line); border-radius: var(--ck-radius-md); background: var(--ck-status-info-bg); color: var(--ck-fg-1); }
    h2 { margin: 0 0 var(--ck-space-2); font-family: var(--ck-font-display); font-weight: 600; font-size: 16px; }
    p { margin: 0 0 var(--ck-space-2); font-size: 13px; color: var(--ck-fg-2); }
    .actions { display: flex; flex-wrap: wrap; gap: var(--ck-space-2); }
    button { padding: var(--ck-space-2) var(--ck-space-3); border: 1px solid var(--ck-stroke-3); border-radius: var(--ck-radius-sm); background: var(--ck-bg-panel); color: inherit; }
    button:focus-visible { outline: 2px solid var(--ck-primary); outline-offset: 2px; }
  `],
})
export class WorkAppElsewhereComponent {
  readonly appSlug = input.required<string>();
  readonly i18n = inject(I18nService);
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);
  readonly lookup = signal<Lookup>({ s: 'searching' });
  readonly currentName = computed(() => this.workspace.current()?.name ?? '');
  readonly found = computed(() => {
    const state = this.lookup();
    return state.s === 'found' ? state.workspaces : [];
  });

  constructor() {
    effect((onCleanup) => {
      const slug = this.appSlug();
      const current = this.workspace.currentSlug();
      const scope = this.workspace.captureRequestScope();
      const others = this.workspace.workspaces().filter((row) => row.slug !== current).slice(0, MAX_LOOKUPS);
      this.lookup.set({ s: 'searching' });
      if (!slug || !others.length) { this.lookup.set({ s: 'nowhere' }); return; }
      const sub = forkJoin(others.map((row) =>
        this.api.get(`/work/${encodeURIComponent(slug)}`, undefined, { workspaceSlug: row.slug }).pipe(
          map(() => ({ slug: row.slug, name: row.name })),
          catchError(() => of(null)),
        ),
      )).subscribe((rows) => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        const hits = rows.filter((row): row is { slug: string; name: string } => !!row);
        this.lookup.set(hits.length ? { s: 'found', workspaces: hits } : { s: 'nowhere' });
      });
      onCleanup(() => sub.unsubscribe());
    });
  }

  open(slug: string): void {
    this.workspace.switchWorkspace(slug);
  }
}
