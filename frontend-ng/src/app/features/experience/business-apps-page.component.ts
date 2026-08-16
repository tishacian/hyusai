import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { HelpTooltipComponent, PageFrameComponent, TagComponent } from '@app/shared/cockpit';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { canEditExperienceStudio, canReleaseExperienceStudio } from './experience-access';
import { StudioApiService } from './studio/studio-api.service';
import {
  filterInventory,
  inventoryAudience,
  inventoryOrigin,
  inventoryState,
  viewHref,
  type InventoryFilter,
  type InventoryState,
  type StudioExperience,
} from './studio/studio-model';

const LIFECYCLE = ['draft', 'checks', 'release', 'pilot', 'live'] as const;

@Component({
  selector: 'app-business-apps-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, EmptyStateComponent, HelpTooltipComponent, PageFrameComponent, TagComponent],
  template: `
    <ck-page-frame
      [eyebrow]="i18n.t('experience.apps.eyebrow')"
      [title]="i18n.t('experience.apps.title')"
      [description]="i18n.t('experience.apps.description')"
    >
      <ck-help titleHelp id="concept.business-application" />
      @if (canEdit()) {
        <a actions routerLink="/create/apps/new" class="xp-btn xp-btn-primary">
          {{ i18n.t('experience.apps.new') }}
        </a>
      }

      <ol class="xp-life" [attr.aria-label]="i18n.t('experience.apps.lifecycle.aria')">
        @for (step of lifecycle; track step) {
          <li>{{ i18n.t('experience.apps.lifecycle.' + step) }}</li>
        }
      </ol>

      <div class="xp-inventory-tools">
      <div class="xp-filters" role="tablist" [attr.aria-label]="i18n.t('experience.apps.filter.all')">
        @for (item of filters; track item; let index = $index) {
          <button
            type="button"
            role="tab"
            [attr.aria-selected]="filter() === item"
            [tabIndex]="filter() === item ? 0 : -1"
            [class.is-on]="filter() === item"
            (click)="filter.set(item)"
            (keydown)="onFilterKey($event, index)"
          >
            {{ i18n.t('experience.apps.filter.' + item) }}
          </button>
        }
      </div>
      <label class="xp-search">
        <span class="xp-sr-only">{{ i18n.t('experience.apps.search') }}</span>
        <input type="search" [value]="query()" [placeholder]="i18n.t('experience.apps.search')" (input)="query.set(inputValue($event))" />
      </label>
      </div>

      @if (state() === 'loading') {
        <app-empty-state icon="sparkles" size="lg" [title]="i18n.t('common.loading')" />
      } @else if (state() === 'error') {
        <app-empty-state
          icon="alert-triangle"
          size="lg"
          [title]="i18n.t('experience.work.unavailable.title')"
          [description]="i18n.t('experience.work.unavailable.body')"
        >
          <button type="button" class="xp-btn" (click)="load()">{{ i18n.t('common.retry') }}</button>
        </app-empty-state>
      } @else if (rows().length === 0) {
        <app-empty-state
          icon="layers"
          size="lg"
          [title]="i18n.t(hasActiveFilter() ? 'experience.work.search.empty.title' : 'experience.apps.empty.title')"
          [description]="i18n.t(hasActiveFilter() ? 'experience.work.search.empty.description' : 'experience.apps.empty.description')"
        >
          @if (canEdit() && !hasActiveFilter()) {
            <a routerLink="/create/apps/new" class="xp-btn xp-btn-primary">
              {{ i18n.t('experience.apps.new') }}
            </a>
          }
        </app-empty-state>
      } @else {
        <div class="xp-table-wrap">
          <table class="xp-table">
            <caption class="xp-sr-only">{{ i18n.t('experience.apps.description') }}</caption>
            <thead>
              <tr>
                <th>{{ i18n.t('experience.apps.col.name') }}</th>
                <th>{{ i18n.t('experience.apps.col.pattern') }}</th>
                <th>{{ i18n.t('experience.apps.col.systems') }}</th>
                <th>{{ i18n.t('experience.apps.col.state') }}</th>
                <th>{{ i18n.t('experience.apps.col.release') }}</th>
                <th>{{ i18n.t('experience.apps.col.audience') }}</th>
                <th>{{ i18n.t('experience.apps.col.actions') }}</th>
              </tr>
            </thead>
            <tbody>
              @for (app of rows(); track app.id) {
                <tr>
                  <td>
                    <div class="xp-app-name">
                      <strong>{{ app.name }}</strong>
                      <ck-tag [tone]="originOf(app) === 'existing' ? 'cool' : 'neutral'" variant="outline">
                        {{ i18n.t('experience.apps.origin.' + originOf(app)) }}
                      </ck-tag>
                    </div>
                    <code>{{ viewHref(app) || '/work/' + app.slug }}</code>
                  </td>
                  <td>{{ patternLabel(app.pattern) }}</td>
                  <td>{{ systemsLabel(app) }}</td>
                  <td>
                    <ck-tag [tone]="stateTone(stateOf(app))">{{
                      i18n.t('experience.apps.state.' + stateOf(app))
                    }}</ck-tag>
                  </td>
                  <td>{{ releaseLabel(app) }}</td>
                  <td>{{ audienceText(app) }}</td>
                  <td class="xp-actions">
                    @if (canEdit()) {
                      <a [routerLink]="['/create/apps', app.id]">
                        {{
                          stateOf(app) === 'draft'
                            ? i18n.t('experience.apps.action.continue')
                            : i18n.t('experience.apps.action.edit')
                        }}
                      </a>
                    } @else if (canReview()) {
                      <a [routerLink]="['/create/apps', app.id]">
                        {{ i18n.t('experience.apps.action.review') }}
                      </a>
                    }
                    @if (viewHref(app); as href) {
                      <a [routerLink]="href">
                        {{ i18n.t('experience.apps.action.view') }} ↗
                      </a>
                    }
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      }
    </ck-page-frame>
  `,
  styleUrl: './studio/studio.scss',
})
export class BusinessAppsPageComponent {
  readonly i18n = inject(I18nService);
  private readonly api = inject(StudioApiService);
  private readonly workspace = inject(WorkspaceService);
  readonly all = signal<StudioExperience[]>([]);
  readonly state = signal<'loading' | 'ready' | 'error'>('loading');
  readonly filter = signal<InventoryFilter>('all');
  readonly query = signal('');
  readonly hasActiveFilter = computed(() => this.filter() !== 'all' || this.query().trim().length > 0);
  readonly filters = ['all', 'live', 'pilot', 'drafts'] as const;
  readonly lifecycle = LIFECYCLE;
  readonly canEdit = computed(() => canEditExperienceStudio(
    this.workspace.current()?.role_template,
    this.workspace.current()?.role,
    this.workspace.isAdmin(),
  ));
  readonly canReview = computed(() => canReleaseExperienceStudio(
    this.workspace.current()?.role_template,
    this.workspace.current()?.role,
    this.workspace.isAdmin(),
  ) && !this.canEdit());
  readonly rows = computed(() => {
    const filtered = filterInventory(this.all(), this.filter());
    const query = this.query().trim().toLocaleLowerCase();
    if (!query) return filtered;
    return filtered.filter((row) => `${row.name} ${row.slug} ${(row.binding_keys ?? []).join(' ')}`.toLocaleLowerCase().includes(query));
  });
  readonly viewHref = viewHref;

  constructor() {
    this.load();
  }

  load(): void {
    this.state.set('loading');
    this.api.listExperiences().subscribe({
      next: (rows) => {
        this.all.set(rows);
        this.state.set('ready');
      },
      error: () => this.state.set('error'),
    });
  }

  inputValue(event: Event): string {
    return (event.target as HTMLInputElement).value;
  }

  onFilterKey(event: KeyboardEvent, index: number): void {
    let next: number | null = null;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (index + 1) % this.filters.length;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (index - 1 + this.filters.length) % this.filters.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = this.filters.length - 1;
    if (next === null) return;
    event.preventDefault();
    this.filter.set(this.filters[next]!);
    const tabs = (event.currentTarget as HTMLElement).parentElement?.querySelectorAll<HTMLElement>('[role="tab"]');
    queueMicrotask(() => tabs?.[next!]?.focus());
  }

  stateOf(app: StudioExperience): InventoryState {
    return inventoryState(app.deployments);
  }

  originOf(app: StudioExperience): 'existing' | 'studio' {
    return inventoryOrigin(app);
  }

  patternLabel(pattern: string): string {
    const key = `experience.work.pattern.${pattern}`;
    const label = this.i18n.t(key);
    return label === key ? pattern : label;
  }

  systemsLabel(app: StudioExperience): string {
    const keys = app.binding_keys ?? [];
    return keys.length === 0 ? this.i18n.t('experience.apps.systems.none') : keys.join(', ');
  }

  releaseLabel(app: StudioExperience): string {
    const n = app.latest_release_number;
    return n ? this.i18n.t('experience.apps.release.n', { n }) : this.i18n.t('experience.apps.release.none');
  }

  audienceText(app: StudioExperience): string {
    const audience = inventoryAudience(app);
    if (audience.kind === 'unknown') return this.i18n.t('experience.apps.audience.unknown');
    if (audience.kind === 'open') return this.i18n.t('experience.apps.audience.open');
    return [
      ...audience.roles
      .map((role) => {
        const key = `governance.access.role.${role}`;
        const label = this.i18n.t(key);
        return label === key ? role : label;
      }),
      ...audience.groups.map((group) => this.i18n.t('experience.publish.recap.group', { name: group })),
    ].join(', ');
  }

  stateTone(state: InventoryState): 'neutral' | 'cool' | 'pos' {
    if (state === 'live') return 'pos';
    if (state === 'pilot') return 'cool';
    return 'neutral';
  }
}
