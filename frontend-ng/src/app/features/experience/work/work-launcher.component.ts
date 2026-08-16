import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { WorkApiService } from './work-api.service';
import {
  canEditExperience,
  catalogLaunchHref,
  studioHref,
  workEmblem,
  workIdentity,
  type WorkCatalogItem,
  type WorkIdentity,
} from './work-catalog';

@Component({
  selector: 'app-work-launcher',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, EmptyStateComponent],
  styleUrl: './work.scss',
  template: `
    <div class="xp-work xp-work-launcher" data-theme="light">
      <header class="xp-work-bar xp-work-global-bar">
        <div class="xp-work-brand-line">
          <span class="xp-work-logo" aria-hidden="true">◇</span>
          <strong>Agentium</strong>
          <span class="xp-work-divider" aria-hidden="true"></span>
          <span>{{ workspace.current()?.name }}</span>
        </div>
        <label class="xp-work-search">
          <span class="sr-only">{{ i18n.t('experience.work.search') }}</span>
          <input
            type="search"
            [placeholder]="i18n.t('experience.work.search')"
            [value]="query()"
            (input)="query.set(inputValue($event))"
          />
        </label>
      </header>
      <section class="xp-work-main xp-work-home" aria-labelledby="work-launcher-title">
        <div class="xp-work-intro">
          <div>
            <p class="xp-work-eyebrow">{{ i18n.t('experience.work.title') }}</p>
            <h1 id="work-launcher-title">{{ i18n.t('experience.work.welcome') }}</h1>
            @if (state() === 'ready') {
              <p [attr.aria-live]="hasQuery() ? 'polite' : null">
                {{ i18n.t(
                  hasQuery() ? 'experience.work.search.count' : 'experience.work.home.count',
                  { n: items().length }
                ) }}
              </p>
            }
          </div>
          @if (canEdit()) {
            <a class="xp-work-studio-link" [routerLink]="studioLink">
              <span>{{ i18n.t('experience.work.author') }}</span>
              {{ i18n.t('experience.work.studio') }} →
            </a>
          }
        </div>

        @switch (state()) {
          @case ('loading') {
            <app-empty-state icon="sparkles" size="lg" [title]="i18n.t('common.loading')" />
          }
          @case ('error') {
            <app-empty-state
              icon="alert-triangle"
              size="lg"
              [title]="i18n.t('experience.work.unavailable.title')"
              [description]="i18n.t('experience.work.unavailable.body')"
            >
              <button type="button" class="xp-work-btn" (click)="load()">{{ i18n.t('common.retry') }}</button>
            </app-empty-state>
          }
          @default {
            @if (items().length === 0) {
              <app-empty-state
                icon="layers"
                size="lg"
                [title]="i18n.t(hasQuery() ? 'experience.work.search.empty.title' : 'experience.work.empty.title')"
                [description]="i18n.t(hasQuery() ? 'experience.work.search.empty.description' : 'experience.work.empty.description')"
              >
                @if (canEdit() && !hasQuery()) {
                  <a class="xp-work-btn xp-work-btn-primary" [routerLink]="studioLink">
                    {{ i18n.t('experience.work.empty.create') }}
                  </a>
                }
              </app-empty-state>
            } @else {
              <div class="xp-work-grid">
                @for (item of items(); track item.experience.id) {
                  <a class="xp-work-card" [routerLink]="launchHref(item)">
                    <div class="xp-work-card-head">
                      <span class="xp-work-app-icon" aria-hidden="true">{{ emblem(item) }}</span>
                      <span
                        class="xp-work-status"
                        [class.xp-work-status-live]="item.channel === 'live'"
                      >
                        {{ i18n.t(item.channel === 'live' ? 'experience.work.status.live' : 'experience.work.status.pilot') }}
                      </span>
                    </div>
                    <h2>{{ identity(item).name }}</h2>
                    <p>{{ identity(item).description || patternLabel(item.experience.pattern) }}</p>
                    <span class="xp-work-open">{{ i18n.t('experience.work.open') }} →</span>
                  </a>
                }
              </div>
            }
          }
        }
      </section>
    </div>
  `,
})
export class WorkLauncherComponent {
  private readonly api = inject(WorkApiService);
  private readonly router = inject(Router);
  readonly workspace = inject(WorkspaceService);
  readonly i18n = inject(I18nService);

  readonly state = signal<'loading' | 'ready' | 'error'>('loading');
  readonly allItems = signal<WorkCatalogItem[]>([]);
  readonly query = signal('');
  readonly hasQuery = computed(() => this.query().trim().length > 0);
  readonly studioLink = studioHref(null);
  readonly launchHref = catalogLaunchHref;
  readonly items = computed(() => {
    const query = this.query().trim().toLocaleLowerCase(this.i18n.locale());
    if (!query) return this.allItems();
    return this.allItems().filter((item) =>
      `${this.identity(item).name} ${this.identity(item).description} ${item.experience.pattern}`
        .toLocaleLowerCase(this.i18n.locale())
        .includes(query),
    );
  });

  readonly canEdit = computed(() =>
    this.workspace.experienceStudioV1Enabled()
    && canEditExperience(this.workspace.current()?.role_template, this.workspace.isAdmin()),
  );

  constructor() {
    this.load();
  }

  load(): void {
    this.state.set('loading');
    this.api.listExperiences().subscribe((result) => {
      if (result.kind !== 'ok') {
        this.state.set('error');
        return;
      }
      if (result.items.length === 1) {
        void this.router.navigateByUrl(catalogLaunchHref(result.items[0]!));
        return;
      }
      this.allItems.set(result.items);
      this.state.set('ready');
    });
  }

  inputValue(event: Event): string {
    return (event.target as HTMLInputElement).value;
  }

  identity(item: WorkCatalogItem): WorkIdentity {
    return workIdentity(item.experience, item.release);
  }

  emblem(item: WorkCatalogItem): string {
    return workEmblem(this.identity(item));
  }

  patternLabel(pattern: string): string {
    const key = `experience.work.pattern.${pattern}`;
    const label = this.i18n.t(key);
    return label === key ? this.i18n.t('experience.work.pattern.other') : label;
  }
}
