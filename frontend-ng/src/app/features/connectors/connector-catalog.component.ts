import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output, computed, inject, signal } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { BrandIconComponent } from '@app/shared/ui/brand-icon.component';
import { IconComponent } from '@app/shared/ui/icon.component';
import {
  CATALOG_FAMILIES,
  familyCounts,
  filterCatalog,
  primaryAction,
  secondaryAction,
  type CatalogAction,
  type CatalogCapability,
  type CatalogEntry,
  type CatalogFamily,
} from './connector-catalog.vm';

export interface CatalogActionEvent {
  entry: CatalogEntry;
  action: CatalogAction;
}

/**
 * The connector catalogue grid: search, family filter and one card per entry.
 *
 * Presentational only. The page decides where an action leads, labels the
 * buttons of historical cards and says which ones are configured here.
 */
@Component({
  selector: 'app-connector-catalog',
  standalone: true,
  imports: [BrandIconComponent, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (!frameworkEnabled) {
      <p class="mb-4 rounded-md border border-white/10 bg-white/[0.03] px-4 py-3 text-sm text-gray-300" role="status" data-testid="catalog-disabled-banner">
        {{ i18n.t('connectors.catalog.disabled_banner') }}
      </p>
    }

    <div class="mb-5 flex flex-col gap-3 lg:flex-row lg:items-center">
      <label class="block lg:w-80">
        <span class="sr-only">{{ i18n.t('connectors.catalog.search_label') }}</span>
        <input
          type="text"
          role="searchbox"
          inputmode="search"
          enterkeyhint="search"
          autocomplete="off"
          spellcheck="false"
          class="ck-input w-full"
          data-testid="catalog-search"
          [attr.aria-label]="i18n.t('connectors.catalog.search_label')"
          [placeholder]="i18n.t('connectors.catalog.search_placeholder')"
          [value]="query()"
          (input)="query.set($any($event.target).value)"
        />
      </label>
      <div class="flex flex-wrap gap-1.5" role="group" [attr.aria-label]="i18n.t('connectors.catalog.filter_label')">
        <button
          type="button"
          class="rounded px-2.5 py-1 text-xs ring-1 transition"
          [class]="chipClass(family() === 'all')"
          [attr.aria-pressed]="family() === 'all'"
          data-testid="catalog-family-all"
          (click)="family.set('all')"
        >
          {{ i18n.t('connectors.catalog.all') }} <span class="ml-1 font-mono text-[10px] text-gray-400">{{ entries.length }}</span>
        </button>
        @for (item of families(); track item.family) {
          <button
            type="button"
            class="rounded px-2.5 py-1 text-xs ring-1 transition"
            [class]="chipClass(family() === item.family)"
            [attr.aria-pressed]="family() === item.family"
            [attr.data-testid]="'catalog-family-' + item.family"
            (click)="family.set(item.family)"
          >
            {{ familyLabel(item.family) }} <span class="ml-1 font-mono text-[10px] text-gray-400">{{ item.count }}</span>
          </button>
        }
      </div>
    </div>

    @for (section of sections(); track section.family) {
      <section class="mb-7" [attr.data-testid]="'catalog-section-' + section.family" [attr.aria-labelledby]="'catalog-heading-' + section.family">
        <header class="mb-3 flex items-center gap-2">
          <h2 [id]="'catalog-heading-' + section.family" class="text-[10px] font-semibold uppercase tracking-[0.16em] text-gray-400">
            {{ familyLabel(section.family) }}
          </h2>
          <span class="text-[11px] text-gray-400">{{ i18n.t('connectors.category.count', { count: section.entries.length }) }}</span>
          <div class="ml-2 h-px flex-1 bg-white/5"></div>
        </header>
        <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          @for (entry of section.entries; track entry.id) {
            <article class="ck-surface flex flex-col rounded-md p-5" [attr.data-testid]="'catalog-card-' + entry.key">
              <div class="flex items-start justify-between gap-3">
                <span class="inline-flex h-12 w-12 items-center justify-center rounded bg-white/[0.04] text-gray-100 ring-1 ring-white/10">
                  <app-brand-icon [name]="entry.brand" [fallback]="entry.fallbackIcon" [size]="24" />
                </span>
                <span class="ck-pill" [class]="'ck-pill ' + pillClass(entry)" data-testid="catalog-level">{{ pillLabel(entry) }}</span>
              </div>
              <h3 class="mt-4 flex items-center gap-2 text-base font-semibold text-white">
                {{ entryName(entry) }}
                @if (entry.official) {
                  <span class="rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-gray-300 ring-1 ring-white/15">
                    {{ i18n.t('connectors.catalog.official') }}
                  </span>
                }
              </h3>
              <p class="mt-2 min-h-[48px] text-sm leading-6 text-gray-400">{{ entryDescription(entry) }}</p>
              @if (entry.capabilities.length) {
                <ul class="mt-3 flex flex-wrap gap-1.5" [attr.aria-label]="i18n.t('connectors.catalog.capabilities_label')">
                  @for (capability of entry.capabilities; track capability) {
                    <li class="rounded px-1.5 py-0.5 text-[11px] text-gray-300 ring-1 ring-white/10">{{ capabilityLabel(capability) }}</li>
                  }
                </ul>
              }
              <div class="mt-auto flex flex-wrap items-center gap-2 pt-5">
                @switch (primary(entry)) {
                  @case ('unavailable') {
                    <button type="button" class="ck-btn w-full justify-center" disabled [attr.title]="i18n.t('connectors.catalog.unavailable_hint')">
                      {{ i18n.t('connectors.catalog.unavailable') }}
                    </button>
                  }
                  @case ('connect') {
                    <a class="ck-btn ck-btn-accent flex-1 justify-center" [attr.href]="href(entry, 'connect')" [attr.data-testid]="'catalog-connect-' + entry.key" (click)="follow($event, entry, 'connect')">
                      <app-icon name="plug" [size]="14" /> {{ i18n.t('connectors.catalog.connect') }}
                    </a>
                  }
                  @default {
                    @if (href(entry, primary(entry)); as url) {
                      <a class="ck-btn ck-btn-accent flex-1 justify-center" [attr.href]="url" [attr.data-testid]="'catalog-open-' + entry.key" (click)="follow($event, entry, primary(entry))">
                        <app-icon name="arrow-right" [size]="14" /> {{ label(entry, primary(entry)) }}
                      </a>
                    } @else {
                      <button type="button" class="ck-btn ck-btn-accent flex-1 justify-center" [attr.data-testid]="'catalog-open-' + entry.key" (click)="emit(entry, primary(entry))">
                        <app-icon name="plug" [size]="14" /> {{ label(entry, primary(entry)) }}
                      </button>
                    }
                  }
                }
                @if (secondary(entry); as action) {
                  <a class="ck-btn flex-1 justify-center" [attr.href]="href(entry, action)" [attr.data-testid]="'catalog-dedicated-' + entry.key" (click)="follow($event, entry, action)">
                    {{ label(entry, action) }}
                  </a>
                }
                @if (entry.documentation) {
                  <a class="inline-flex items-center gap-1 text-[11px] text-gray-400 hover:text-gray-200" [href]="entry.documentation" target="_blank" rel="noopener noreferrer">
                    <app-icon name="external-link" [size]="12" /> {{ i18n.t('connectors.catalog.documentation') }}
                  </a>
                }
              </div>
            </article>
          }
        </div>
      </section>
    } @empty {
      <p class="rounded-md border border-white/10 bg-white/[0.03] p-5 text-sm text-gray-400" role="status">{{ i18n.t('connectors.catalog.empty') }}</p>
    }

    <p class="mt-2 text-[11px] text-gray-400">{{ i18n.t('connectors.catalog.logo_notice') }}</p>
  `,
})
export class ConnectorCatalogComponent {
  readonly i18n = inject(I18nService);

  @Input({ required: true }) set catalog(value: readonly CatalogEntry[]) {
    this.entries = [...value];
    this.entriesSignal.set(this.entries);
  }
  @Input() frameworkEnabled = false;
  /** Historical card ids configured in this workspace. */
  @Input() configured: ReadonlySet<string> = new Set();
  /** Label of a historical page or drawer button, decided by the page. */
  @Input() actionLabel: (entry: CatalogEntry, action: CatalogAction) => string = () => '';
  /** Address of a navigation action; null keeps a button (setup drawer). */
  @Input() actionHref: (entry: CatalogEntry, action: CatalogAction) => string | null = () => null;
  @Output() readonly act = new EventEmitter<CatalogActionEvent>();

  entries: CatalogEntry[] = [];
  private readonly entriesSignal = signal<CatalogEntry[]>([]);
  readonly query = signal('');
  readonly family = signal<CatalogFamily | 'all'>('all');

  readonly families = computed(() => {
    const counts = familyCounts(this.entriesSignal());
    return CATALOG_FAMILIES.filter((family) => (counts.get(family) ?? 0) > 0).map((family) => ({
      family,
      count: counts.get(family) ?? 0,
    }));
  });

  readonly sections = computed(() => {
    const visible = filterCatalog(this.entriesSignal(), this.family(), this.query(), (entry) =>
      `${this.entryName(entry)} ${this.entryDescription(entry)} ${this.familyLabel(entry.family)}`,
    );
    return CATALOG_FAMILIES.map((family) => ({
      family,
      entries: visible.filter((entry) => entry.family === family),
    })).filter((section) => section.entries.length > 0);
  });

  primary(entry: CatalogEntry): CatalogAction {
    return primaryAction(entry, this.frameworkEnabled);
  }

  secondary(entry: CatalogEntry): CatalogAction | null {
    return secondaryAction(entry, this.frameworkEnabled);
  }

  emit(entry: CatalogEntry, action: CatalogAction): void {
    this.act.emit({ entry, action });
  }

  href(entry: CatalogEntry, action: CatalogAction): string | null {
    return this.actionHref(entry, action);
  }

  /** Real links for new tabs and assistive tech; a plain click stays in the SPA. */
  follow(event: MouseEvent, entry: CatalogEntry, action: CatalogAction): void {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    this.emit(entry, action);
  }

  label(entry: CatalogEntry, action: CatalogAction): string {
    return this.actionLabel(entry, action) || this.i18n.t('connectors.catalog.dedicated');
  }

  entryName(entry: CatalogEntry): string {
    return this.translate(entry.nameKey, entry.name);
  }

  entryDescription(entry: CatalogEntry): string {
    return this.translate(entry.descriptionKey, entry.descriptionFallback);
  }

  familyLabel(family: CatalogFamily): string {
    return this.i18n.t(`connectors.catalog.family.${family}`);
  }

  capabilityLabel(capability: CatalogCapability): string {
    return this.i18n.t(`connectors.catalog.capability.${capability}`);
  }

  pillLabel(entry: CatalogEntry): string {
    if (entry.legacyId && this.configured.has(entry.legacyId)) return this.i18n.t('connectors.status.configured');
    if (entry.level === 'verified' || entry.level === 'certified') return this.i18n.t(`connections.${entry.level}`);
    return this.i18n.t(`connectors.status.${entry.level}`);
  }

  pillClass(entry: CatalogEntry): string {
    if (entry.legacyId && this.configured.has(entry.legacyId)) return 'ck-tone-ok';
    if (entry.level === 'on_request') return 'ck-tone-warn';
    if (entry.level === 'third_party') return 'ck-tone-preview';
    return 'ck-tone-info';
  }

  chipClass(active: boolean): string {
    return active
      ? 'rounded px-2.5 py-1 text-xs ring-1 transition bg-white/[0.06] text-white ring-cyan-400/35'
      : 'rounded px-2.5 py-1 text-xs ring-1 transition text-gray-400 ring-white/10 hover:text-gray-200 hover:bg-white/5';
  }

  private translate(key: string | null, fallback: string): string {
    if (!key) return fallback;
    const value = this.i18n.t(key);
    return value === key ? fallback || value : value;
  }
}
