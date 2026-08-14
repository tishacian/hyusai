import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { HelpTooltipComponent, PageFrameComponent, TagComponent } from '@app/shared/cockpit';
import { I18nService } from '@app/core/i18n.service';
import { StudioApiService } from './studio/studio-api.service';
import {
  audienceLabel,
  filterInventory,
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
      <a actions routerLink="/create/apps/new" class="xp-btn xp-btn-primary">
        {{ i18n.t('experience.apps.new') }}
      </a>

      <ol class="xp-life" [attr.aria-label]="i18n.t('experience.apps.lifecycle.aria')">
        @for (step of lifecycle; track step) {
          <li>{{ i18n.t('experience.apps.lifecycle.' + step) }}</li>
        }
      </ol>

      <div class="xp-filters" role="tablist" [attr.aria-label]="i18n.t('experience.apps.filter.all')">
        @for (item of filters; track item) {
          <button
            type="button"
            role="tab"
            [attr.aria-selected]="filter() === item"
            [class.is-on]="filter() === item"
            (click)="filter.set(item)"
          >
            {{ i18n.t('experience.apps.filter.' + item) }}
          </button>
        }
      </div>

      @if (rows().length === 0) {
        <app-empty-state
          icon="layers"
          size="lg"
          [title]="i18n.t('experience.apps.empty.title')"
          [description]="i18n.t('experience.apps.empty.description')"
        >
          <a routerLink="/create/apps/new" class="xp-btn xp-btn-primary">
            {{ i18n.t('experience.apps.new') }}
          </a>
        </app-empty-state>
      } @else {
        <div class="xp-table-wrap">
          <table class="xp-table">
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
                    <a [routerLink]="['/create/apps', app.id]">
                      {{
                        stateOf(app) === 'draft'
                          ? i18n.t('experience.apps.action.continue')
                          : i18n.t('experience.apps.action.edit')
                      }}
                    </a>
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
  readonly all = signal<StudioExperience[]>([]);
  readonly filter = signal<InventoryFilter>('all');
  readonly filters = ['all', 'live', 'pilot', 'drafts'] as const;
  readonly lifecycle = LIFECYCLE;
  readonly rows = computed(() => filterInventory(this.all(), this.filter()));
  readonly viewHref = viewHref;

  constructor() {
    this.api.listExperiences().subscribe((rows) => this.all.set(rows));
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
    const roles = audienceLabel(app.deployments);
    if (roles.length === 0) return this.i18n.t('experience.apps.audience.open');
    return roles
      .map((role) => {
        const key = `governance.access.role.${role}`;
        const label = this.i18n.t(key);
        return label === key ? role : label;
      })
      .join(', ');
  }

  stateTone(state: InventoryState): 'neutral' | 'cool' | 'pos' {
    if (state === 'live') return 'pos';
    if (state === 'pilot') return 'cool';
    return 'neutral';
  }
}
