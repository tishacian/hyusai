import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  type OnInit,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';
import { formatInstant } from '@app/core/format-instant';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService, type WorkspaceRequestScope } from '@app/core/workspace.service';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import type { ExperienceNode, RuntimeNodeContext } from '../model';
import {
  ReviewTimer,
  deadlineState,
  draftDecision,
  draftProblems,
  lostProtectedSpan,
  toggleAnnotation,
  type ReviewDraft,
  type ReviewItemPage,
  type ReviewItemView,
  type ReviewSetDetail,
  type ReviewSetView,
} from './review-model';
import { ReviewSetsApi, reviewErrorCode, type ReviewHistoryEntry } from './review-sets.api';

type Phase = 'loading' | 'loaded' | 'error';
const PAGE = 25;

/**
 * Certified `review_workbench`: the sets of a namespace, a set's packages and
 * records, and the per-record decision screen. The server enforces every rule
 * shown here; the screen only explains them before sending.
 */
@Component({
  selector: 'xp-rt-review',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [EmptyStateComponent],
  styleUrls: ['../runtime.scss', './review.scss'],
  template: `
    <section class="xp-rt-block xp-rv" [attr.aria-label]="title() || i18n.t('experience.review.sets.title')">
      <h3>{{ title() || i18n.t('experience.review.sets.title') }}</h3>
      @if (description()) {
        <p class="xp-rt-sub">{{ description() }}</p>
      }
      <p class="xp-rv-live" aria-live="polite">{{ notice() }}</p>

      @switch (view()) {
        @case ('sets') {
          @switch (setsPhase()) {
            @case ('loading') {
              <app-empty-state icon="sparkles" size="sm" [title]="i18n.t('experience.review.sets.loading')" />
            }
            @case ('error') {
              <app-empty-state icon="alert-triangle" size="sm" [title]="i18n.t('experience.review.sets.error')" />
              <button type="button" class="xp-rt-btn" (click)="loadSets()">{{ i18n.t('experience.review.retry') }}</button>
            }
            @default {
              @if (!sets().length) {
                <app-empty-state
                  icon="inbox"
                  size="sm"
                  [title]="i18n.t('experience.review.sets.empty_title')"
                  [description]="i18n.t('experience.review.sets.empty_body')"
                />
              } @else {
                <ul class="xp-rv-sets">
                  @for (s of sets(); track s.id) {
                    <li class="xp-rv-set">
                      <div>
                        <p class="xp-rv-set-title">{{ s.title }}</p>
                        <p class="xp-rt-sub">
                          {{ i18n.t('experience.review.set.progress', { decided: s.decided_count, total: s.item_count }) }}
                          @if (s.status === 'closed') { · {{ i18n.t('experience.review.set.closed') }} }
                          @if (deadlineLabel(s); as label) { · <span [class]="'xp-rv-due xp-rv-due-' + deadline(s)">{{ label }}</span> }
                        </p>
                        <progress class="xp-rv-progress" [value]="s.decided_count" [max]="s.item_count || 1"></progress>
                      </div>
                      <button type="button" class="xp-rt-btn" (click)="openSet(s.id)">{{ i18n.t('experience.review.set.open') }}</button>
                    </li>
                  }
                </ul>
              }
            }
          }
        }

        @case ('set') {
          <button type="button" class="xp-rt-btn xp-rt-btn-ghost" (click)="backToSets()">{{ i18n.t('experience.review.back_to_sets') }}</button>
          @switch (setPhase()) {
            @case ('loading') {
              <app-empty-state icon="sparkles" size="sm" [title]="i18n.t('experience.review.set.loading')" />
            }
            @case ('error') {
              <app-empty-state icon="alert-triangle" size="sm" [title]="i18n.t('experience.review.set.error')" />
              <button type="button" class="xp-rt-btn" (click)="reloadSet()">{{ i18n.t('experience.review.retry') }}</button>
            }
            @default {
              @if (detail(); as d) {
                <h4 class="xp-rv-h">{{ d.title }}</h4>
                <p class="xp-rt-sub">{{ i18n.t('experience.review.set.progress', { decided: d.decided_count, total: d.item_count }) }}</p>
                @if (d.completed_at) {
                  <p class="xp-rt-hint">{{ i18n.t('experience.review.all_done') }}</p>
                }
                <h5 class="xp-rv-h">{{ i18n.t('experience.review.packages.title') }}</h5>
                <ul class="xp-rv-packages">
                  @for (p of d.packages; track p.key) {
                    <li>
                      <button
                        type="button"
                        class="xp-rv-package"
                        [class.xp-rv-package-on]="filters().package === p.key"
                        [attr.aria-pressed]="filters().package === p.key"
                        (click)="togglePackage(p.key)"
                      >
                        {{ i18n.t('experience.review.package.label', { key: p.key, decided: p.decided, items: p.items }) }}
                      </button>
                      @if (p.locked) {
                        <span class="xp-rt-hint">{{ i18n.t('experience.review.package.locked') }}</span>
                      }
                    </li>
                  }
                </ul>

                <div class="xp-rv-filters">
                  <div class="xp-rt-field">
                    <label for="rv-status-{{ uid }}">{{ i18n.t('experience.review.filters.status') }}</label>
                    <select id="rv-status-{{ uid }}" [value]="filters().status ?? ''" (change)="setFilter('status', $any($event.target).value)">
                      <option value="">{{ i18n.t('experience.review.filters.all') }}</option>
                      @for (st of statuses; track st) {
                        <option [value]="st">{{ i18n.t('experience.review.status.' + st) }}</option>
                      }
                    </select>
                  </div>
                  <div class="xp-rt-field">
                    <label for="rv-tier-{{ uid }}">{{ i18n.t('experience.review.filters.tier') }}</label>
                    <select id="rv-tier-{{ uid }}" [value]="filters().tier ?? ''" (change)="setFilter('tier', $any($event.target).value)">
                      <option value="">{{ i18n.t('experience.review.filters.all') }}</option>
                      @for (t of d.policy.tiers; track t.key) {
                        <option [value]="t.key">{{ t.label }}</option>
                      }
                    </select>
                  </div>
                  <div class="xp-rt-field">
                    <label for="rv-cat-{{ uid }}">{{ i18n.t('experience.review.filters.category') }}</label>
                    <select id="rv-cat-{{ uid }}" [value]="filters().category ?? ''" (change)="setFilter('category', $any($event.target).value)">
                      <option value="">{{ i18n.t('experience.review.filters.all') }}</option>
                      @for (c of d.taxonomy.categories; track c.key) {
                        <option [value]="c.key">{{ c.label }}</option>
                      }
                    </select>
                  </div>
                  <div class="xp-rt-field">
                    <label for="rv-q-{{ uid }}">{{ i18n.t('experience.review.filters.search') }}</label>
                    <input id="rv-q-{{ uid }}" type="search" [value]="filters().q ?? ''" (change)="setFilter('q', $any($event.target).value)" />
                  </div>
                  @if (hasFilters()) {
                    <button type="button" class="xp-rt-btn xp-rt-btn-ghost" (click)="clearFilters()">{{ i18n.t('experience.review.filters.clear') }}</button>
                  }
                </div>

                @switch (itemsPhase()) {
                  @case ('loading') {
                    <app-empty-state icon="sparkles" size="sm" [title]="i18n.t('experience.review.items.loading')" />
                  }
                  @case ('error') {
                    <app-empty-state icon="alert-triangle" size="sm" [title]="i18n.t('experience.review.items.error')" />
                    <button type="button" class="xp-rt-btn" (click)="loadItems()">{{ i18n.t('experience.review.retry') }}</button>
                  }
                  @default {
                    @if (page(); as pg) {
                      @if (!pg.items.length) {
                        <app-empty-state icon="search" size="sm" [title]="i18n.t('experience.review.items.no_results')" />
                        @if (hasFilters()) {
                          <button type="button" class="xp-rt-btn xp-rt-btn-ghost" (click)="clearFilters()">{{ i18n.t('experience.review.filters.clear') }}</button>
                        }
                      } @else {
                        <div class="xp-rt-table-scroll" role="region" tabindex="0" [attr.aria-label]="d.title">
                          <table class="xp-rt-table xp-rv-table">
                            <thead>
                              <tr>
                                <th scope="col"><span class="xp-rv-sr">{{ i18n.t('experience.review.col.select') }}</span></th>
                                <th scope="col">{{ i18n.t('experience.review.col.ref') }}</th>
                                <th scope="col">{{ i18n.t('experience.review.col.source') }}</th>
                                <th scope="col">{{ i18n.t('experience.review.col.candidate') }}</th>
                                <th scope="col">{{ i18n.t('experience.review.col.status') }}</th>
                                <th scope="col">{{ i18n.t('experience.review.col.severity') }}</th>
                                <th scope="col"><span class="xp-rv-sr">{{ i18n.t('experience.review.review_item') }}</span></th>
                              </tr>
                            </thead>
                            <tbody>
                              @for (row of pg.items; track row.id) {
                                <tr>
                                  <td>
                                    <input
                                      type="checkbox"
                                      [checked]="selected().has(row.id)"
                                      [disabled]="row.status !== 'pending'"
                                      [attr.aria-label]="i18n.t('experience.review.select_row', { ref: row.item_ref })"
                                      (change)="toggleSelected(row.id)"
                                    />
                                  </td>
                                  <td class="xp-rv-mono">{{ row.item_ref }}</td>
                                  <td [attr.dir]="'auto'">{{ excerpt(row.subject?.source) }}</td>
                                  <td [attr.dir]="row.subject?.direction || 'auto'">{{ excerpt(row.subject?.candidate) }}</td>
                                  <td>{{ i18n.t('experience.review.status.' + row.status) }}</td>
                                  <td>{{ row.worst_severity || '' }}</td>
                                  <td><button type="button" class="xp-rt-btn xp-rt-btn-ghost" (click)="openItem(row.id)">{{ i18n.t('experience.review.review_item') }}</button></td>
                                </tr>
                              }
                            </tbody>
                          </table>
                        </div>
                        <div class="xp-rt-actions">
                          <span class="xp-rt-sub">{{ i18n.t('experience.review.page.range', { from: pg.offset + 1, to: pg.offset + pg.items.length, total: pg.total }) }}</span>
                          <button type="button" class="xp-rt-btn xp-rt-btn-ghost" [disabled]="pg.offset === 0" (click)="turnPage(-1)">{{ i18n.t('experience.review.page.prev') }}</button>
                          <button type="button" class="xp-rt-btn xp-rt-btn-ghost" [disabled]="pg.offset + pg.items.length >= pg.total" (click)="turnPage(1)">{{ i18n.t('experience.review.page.next') }}</button>
                          @if (selected().size) {
                            <button type="button" class="xp-rt-btn" [disabled]="busy()" (click)="bulkApprove()">{{ i18n.t('experience.review.bulk.approve', { count: selected().size }) }}</button>
                          }
                        </div>
                      }
                    }
                  }
                }
              }
            }
          }
        }

        @case ('item') {
          <button type="button" class="xp-rt-btn xp-rt-btn-ghost" (click)="backToList()">{{ i18n.t('experience.review.back_to_list') }}</button>
          @switch (itemPhase()) {
            @case ('loading') {
              <app-empty-state icon="sparkles" size="sm" [title]="i18n.t('experience.review.items.loading')" />
            }
            @case ('error') {
              <app-empty-state icon="alert-triangle" size="sm" [title]="itemError()" />
            }
            @default {
              @if (item(); as it) {
                <h4 class="xp-rv-h xp-rv-mono">{{ it.item_ref }}</h4>
                <div class="xp-rv-grid">
                  <div>
                    <h5 class="xp-rv-h">{{ i18n.t('experience.review.item.source') }}</h5>
                    @for (line of it.subject?.context?.before ?? []; track $index) {
                      <p class="xp-rv-context" dir="auto"><span class="xp-rv-sr">{{ i18n.t('experience.review.item.context_before') }}</span>{{ line }}</p>
                    }
                    <p class="xp-rv-source" dir="auto">{{ it.subject?.source }}</p>
                    @for (line of it.subject?.context?.after ?? []; track $index) {
                      <p class="xp-rv-context" dir="auto"><span class="xp-rv-sr">{{ i18n.t('experience.review.item.context_after') }}</span>{{ line }}</p>
                    }
                  </div>
                  <div class="xp-rt-field">
                    <label for="rv-value-{{ uid }}">{{ i18n.t('experience.review.item.proposal') }}</label>
                    <textarea
                      id="rv-value-{{ uid }}"
                      rows="5"
                      [attr.dir]="it.subject?.direction || 'auto'"
                      [value]="draft().value"
                      [disabled]="draft().reject"
                      [attr.aria-describedby]="'rv-problems-' + uid"
                      (input)="patchDraft({ value: $any($event.target).value })"
                    ></textarea>
                  </div>
                </div>

                @if (it.subject?.references?.length) {
                  <h5 class="xp-rv-h">{{ i18n.t('experience.review.item.references') }}</h5>
                  <ul class="xp-rv-list">
                    @for (ref of it.subject?.references ?? []; track $index) {
                      <li>
                        <p dir="auto">{{ ref.source }}</p>
                        <p dir="auto">{{ ref.target }}</p>
                        @if (ref.score !== undefined) {
                          <p class="xp-rt-sub">{{ i18n.t('experience.review.item.reference_score', { score: percent(ref.score) }) }}</p>
                        }
                      </li>
                    }
                  </ul>
                }

                @if (it.subject?.findings?.length) {
                  <h5 class="xp-rv-h">{{ i18n.t('experience.review.item.findings') }}</h5>
                  <ul class="xp-rv-list">
                    @for (f of it.subject?.findings ?? []; track $index) {
                      <li>
                        <span class="xp-rv-mono">{{ f.category }} {{ f.severity }}</span> {{ f.text }}
                        @if (f.fixed) { <span class="xp-rt-hint">{{ i18n.t('experience.review.item.finding_fixed') }}</span> }
                      </li>
                    }
                  </ul>
                }

                @if (detail()?.taxonomy?.categories?.length) {
                  <fieldset class="xp-rv-annotations" [disabled]="draftKind() === 'approve' && !draft().annotations.length">
                    <legend>{{ i18n.t('experience.review.item.annotations') }}</legend>
                    @for (c of detail()!.taxonomy.categories; track c.key) {
                      <div class="xp-rt-field">
                        <label for="rv-cat-{{ uid }}-{{ c.key }}" [title]="c.description || ''">{{ c.label }}</label>
                        <select id="rv-cat-{{ uid }}-{{ c.key }}" [value]="severityOf(c.key)" (change)="setSeverity(c.key, $any($event.target).value)">
                          <option value="">{{ i18n.t('experience.review.item.severity_none') }}</option>
                          @for (sev of c.severities; track sev) {
                            <option [value]="sev">{{ sev }}</option>
                          }
                        </select>
                      </div>
                    }
                  </fieldset>
                }

                <div class="xp-rt-field">
                  <label for="rv-comment-{{ uid }}">{{ i18n.t('experience.review.item.comment') }}</label>
                  <textarea id="rv-comment-{{ uid }}" rows="2" [value]="draft().comment" (input)="patchDraft({ comment: $any($event.target).value })"></textarea>
                </div>
                <label class="xp-rv-check">
                  <input type="checkbox" [checked]="draft().reject" (change)="patchDraft({ reject: $any($event.target).checked })" />
                  {{ i18n.t('experience.review.item.reject') }}
                </label>

                <ul class="xp-rv-problems" id="rv-problems-{{ uid }}">
                  @for (p of problems(); track p) {
                    <li class="xp-rt-err">{{ problemText(p) }}</li>
                  }
                </ul>
                @if (saveError()) {
                  <p class="xp-rt-err" role="alert">{{ saveError() }}</p>
                }
                <div class="xp-rt-actions">
                  <button type="button" class="xp-rt-btn" [disabled]="busy() || problems().length > 0" (click)="send()">
                    {{ i18n.t('experience.review.item.decision.' + draftKind()) }}
                  </button>
                  <button type="button" class="xp-rt-btn xp-rt-btn-ghost" [disabled]="busy()" (click)="skip()">{{ i18n.t('experience.review.item.skip') }}</button>
                </div>

                @if (history().length) {
                  <h5 class="xp-rv-h">{{ i18n.t('experience.review.history') }}</h5>
                  <ul class="xp-rv-list">
                    @for (h of history(); track h.revision) {
                      <li>
                        {{ i18n.t('experience.review.status.' + h.decision) }} · {{ when(h.decided_at) }}
                        @if (h.value) { <p dir="auto">{{ h.value }}</p> }
                        @if (h.comment) { <p class="xp-rt-sub">{{ h.comment }}</p> }
                      </li>
                    }
                  </ul>
                }
              }
            }
          }
        }
      }
    </section>
  `,
})
export class ReviewWorkbenchBlock implements OnInit {
  readonly i18n = inject(I18nService);
  private readonly api = inject(ReviewSetsApi);
  private readonly workspace = inject(WorkspaceService);
  private readonly destroyRef = inject(DestroyRef);

  readonly node = input.required<ExperienceNode>();
  readonly context = input<RuntimeNodeContext | null>(null);

  readonly uid = Math.random().toString(36).slice(2, 8);
  readonly statuses = ['pending', 'decided', 'approve', 'correct', 'reject'];

  readonly view = signal<'sets' | 'set' | 'item'>('sets');
  readonly notice = signal('');
  readonly busy = signal(false);

  readonly setsPhase = signal<Phase>('loading');
  readonly sets = signal<ReviewSetView[]>([]);

  readonly setId = signal<string | null>(null);
  readonly setPhase = signal<Phase>('loading');
  readonly detail = signal<ReviewSetDetail | null>(null);
  readonly filters = signal<{ status?: string; tier?: string; category?: string; q?: string; package?: string; offset: number }>({ offset: 0 });
  readonly itemsPhase = signal<Phase>('loading');
  readonly page = signal<ReviewItemPage | null>(null);
  readonly selected = signal<Set<string>>(new Set());

  readonly itemPhase = signal<Phase>('loading');
  readonly item = signal<ReviewItemView | null>(null);
  readonly itemError = signal('');
  readonly history = signal<ReviewHistoryEntry[]>([]);
  readonly draft = signal<ReviewDraft>({ value: '', annotations: [], comment: '', reject: false });
  readonly saveError = signal('');
  private readonly timer = new ReviewTimer();

  readonly title = computed(() => this.text('title'));
  readonly description = computed(() => this.text('description'));
  readonly draftKind = computed(() => draftDecision(this.item()?.subject, this.draft()));
  readonly problems = computed(() =>
    draftProblems(this.detail()?.taxonomy ?? { categories: [], comment_required_for: [] }, this.item()?.subject, this.draft()),
  );
  readonly hasFilters = computed(() => {
    const f = this.filters();
    return !!(f.status || f.tier || f.category || f.q || f.package);
  });

  ngOnInit(): void {
    const onVisibility = () => (document.hidden ? this.timer.pause() : this.timer.start());
    document.addEventListener('visibilitychange', onVisibility);
    this.destroyRef.onDestroy(() => {
      document.removeEventListener('visibilitychange', onVisibility);
      const current = this.item();
      if (current && this.view() === 'item') this.api.release(this.workspace.captureRequestScope(), current.id).subscribe({ error: () => undefined });
    });
    this.loadSets();
  }

  private text(key: string): string {
    const value = this.node().props?.[key];
    return typeof value === 'string' ? value : '';
  }

  private guard<T>(scope: WorkspaceRequestScope, next: (value: T) => void, error: (err: unknown) => void) {
    return {
      next: (value: T) => this.workspace.isRequestScopeCurrent(scope) && next(value),
      error: (err: unknown) => this.workspace.isRequestScopeCurrent(scope) && error(err),
    };
  }

  loadSets(): void {
    const scope = this.workspace.captureRequestScope();
    this.setsPhase.set('loading');
    const namespace = this.text('namespace') || undefined;
    this.api.sets(scope, namespace).subscribe(this.guard<ReviewSetView[]>(scope,
      (rows) => { this.sets.set(rows); this.setsPhase.set('loaded'); },
      () => this.setsPhase.set('error'),
    ));
  }

  openSet(id: string): void {
    this.setId.set(id);
    this.filters.set({ offset: 0 });
    this.selected.set(new Set());
    this.view.set('set');
    this.reloadSet();
  }

  reloadSet(): void {
    const id = this.setId();
    if (!id) return;
    const scope = this.workspace.captureRequestScope();
    this.setPhase.set('loading');
    this.api.set(scope, id).subscribe(this.guard<ReviewSetDetail>(scope,
      (d) => { this.detail.set(d); this.setPhase.set('loaded'); this.loadItems(); },
      () => this.setPhase.set('error'),
    ));
  }

  loadItems(): void {
    const id = this.setId();
    if (!id) return;
    const scope = this.workspace.captureRequestScope();
    this.itemsPhase.set('loading');
    const { offset, ...rest } = this.filters();
    this.api.items(scope, id, { ...rest, offset, limit: PAGE }).subscribe(this.guard<ReviewItemPage>(scope,
      (pg) => { this.page.set(pg); this.itemsPhase.set('loaded'); },
      () => this.itemsPhase.set('error'),
    ));
  }

  setFilter(key: 'status' | 'tier' | 'category' | 'q', value: string): void {
    this.filters.update((f) => ({ ...f, [key]: value || undefined, offset: 0 }));
    this.selected.set(new Set());
    this.loadItems();
  }

  togglePackage(key: string): void {
    this.filters.update((f) => ({ ...f, package: f.package === key ? undefined : key, offset: 0 }));
    this.loadItems();
  }

  clearFilters(): void {
    this.filters.set({ offset: 0 });
    this.loadItems();
  }

  turnPage(direction: number): void {
    this.filters.update((f) => ({ ...f, offset: Math.max(0, f.offset + direction * PAGE) }));
    this.loadItems();
  }

  toggleSelected(id: string): void {
    this.selected.update((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  bulkApprove(): void {
    const id = this.setId();
    if (!id) return;
    const scope = this.workspace.captureRequestScope();
    this.busy.set(true);
    this.api.bulkApprove(scope, id, [...this.selected()]).subscribe(this.guard<{ approved: string[]; skipped: unknown[] }>(scope,
      (out) => {
        this.busy.set(false);
        this.selected.set(new Set());
        this.notice.set(this.i18n.t('experience.review.bulk.done', { approved: out.approved.length, skipped: out.skipped.length }));
        this.reloadSet();
      },
      () => { this.busy.set(false); this.notice.set(this.i18n.t('experience.review.bulk.error')); },
    ));
  }

  backToSets(): void {
    this.view.set('sets');
    this.loadSets();
  }

  backToList(): void {
    const current = this.item();
    if (current) this.api.release(this.workspace.captureRequestScope(), current.id).subscribe({ error: () => undefined });
    this.item.set(null);
    this.view.set('set');
    this.reloadSet();
  }

  openItem(id: string): void {
    const scope = this.workspace.captureRequestScope();
    this.view.set('item');
    this.itemPhase.set('loading');
    this.saveError.set('');
    this.api.claim(scope, id).subscribe(this.guard(scope,
      () => this.fetchItem(scope, id),
      (err) => {
        const code = reviewErrorCode(err);
        this.itemError.set(this.i18n.t(
          code === 'REVIEW_ITEM_CLAIMED' ? 'experience.review.item.claim_error_claimed'
            : code === 'REVIEW_TIER_LOCKED' ? 'experience.review.item.claim_error_locked'
              : 'experience.review.item.claim_error',
        ));
        this.itemPhase.set('error');
      },
    ));
  }

  private fetchItem(scope: WorkspaceRequestScope, id: string): void {
    this.api.item(scope, id).subscribe(this.guard<ReviewItemView & { history: ReviewHistoryEntry[] }>(scope,
      (it) => {
        this.item.set(it);
        this.history.set(it.history ?? []);
        this.draft.set({ value: it.subject?.candidate ?? '', annotations: [], comment: '', reject: false });
        this.itemPhase.set('loaded');
        this.timer.take();
        this.timer.start();
      },
      () => { this.itemError.set(this.i18n.t('experience.review.item.claim_error')); this.itemPhase.set('error'); },
    ));
  }

  patchDraft(patch: Partial<ReviewDraft>): void {
    this.draft.update((d) => ({ ...d, ...patch }));
  }

  severityOf(category: string): string {
    return this.draft().annotations.find((a) => a.category === category)?.severity ?? '';
  }

  setSeverity(category: string, severity: string): void {
    this.draft.update((d) => ({ ...d, annotations: toggleAnnotation(d.annotations, category, severity || null) }));
  }

  problemText(problem: string): string {
    if (problem === 'protected_span_lost') {
      return this.i18n.t('experience.review.problem.protected_span_lost', {
        span: lostProtectedSpan(this.item()?.subject, this.draft().value) ?? '',
      });
    }
    return this.i18n.t(`experience.review.problem.${problem}`);
  }

  send(): void {
    const it = this.item();
    if (!it || this.problems().length) return;
    const draft = this.draft();
    const decision = this.draftKind();
    const scope = this.workspace.captureRequestScope();
    this.busy.set(true);
    this.saveError.set('');
    this.api.decide(scope, it.id, {
      revision: it.revision,
      decision,
      value: decision === 'correct' ? draft.value : undefined,
      annotations: decision === 'approve' ? [] : draft.annotations,
      comment: draft.comment.trim() || undefined,
      duration_ms: this.timer.take(),
    }).subscribe(this.guard<ReviewItemView>(scope,
      () => {
        this.busy.set(false);
        this.notice.set(this.i18n.t('experience.review.item.saved'));
        this.openNext(it.id);
      },
      (err) => {
        this.busy.set(false);
        const code = reviewErrorCode(err);
        this.saveError.set(code === 'REVIEW_REVISION_STALE'
          ? this.i18n.t('experience.review.item.stale')
          : this.i18n.t('experience.review.item.save_error', { reason: code ?? '' }));
      },
    ));
  }

  skip(): void {
    const it = this.item();
    if (!it) return;
    this.api.release(this.workspace.captureRequestScope(), it.id).subscribe({ error: () => undefined });
    this.openNext(it.id);
  }

  /** The next pending record of the current page, or back to the list. */
  private openNext(currentId: string): void {
    const rows = this.page()?.items ?? [];
    const index = rows.findIndex((r) => r.id === currentId);
    const next = rows.slice(index + 1).find((r) => r.status === 'pending');
    if (next) this.openItem(next.id);
    else {
      this.item.set(null);
      this.view.set('set');
      this.reloadSet();
    }
  }

  deadline(s: ReviewSetView): 'overdue' | 'soon' | 'none' {
    return deadlineState(s.deadline_at);
  }

  deadlineLabel(s: ReviewSetView): string {
    const state = this.deadline(s);
    if (state === 'overdue') return this.i18n.t('experience.review.deadline.overdue');
    if (state === 'soon') return this.i18n.t('experience.review.deadline.soon');
    return s.deadline_at ? this.i18n.t('experience.review.deadline.date', { date: this.when(s.deadline_at) }) : '';
  }

  when(value: string): string {
    return formatInstant(value, this.i18n.locale()) ?? value;
  }

  percent(score: number): number {
    return Math.round((score <= 1 ? score * 100 : score) * 10) / 10;
  }

  excerpt(value: string | undefined): string {
    if (!value) return '';
    return value.length > 140 ? `${value.slice(0, 139)}…` : value;
  }
}
