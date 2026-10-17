import { afterRenderEffect, ChangeDetectionStrategy, Component, computed, ElementRef, inject, input, output, signal, viewChild } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { IconComponent } from '@app/shared/ui/icon.component';

/** Presentation adapter for a Work inbox, independent of its source and record type. */
export interface WorkRecordItem {
  id: string;
  title: string;
  subtitle?: string;
  description?: string;
  value?: string;
  meta?: string;
  status?: { value: string; label: string };
  badge?: { label: string; tone?: 'warning' };
}

let nextQueueId = 0;

@Component({
  selector: 'app-work-record-queue',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '(window:resize)': 'revealSelected()' },
  styleUrl: './work-record-queue.scss',
  template: `
    <div class="work-record-heading"><h2 [id]="id + '-title'">{{ title() }}</h2><span>{{ items().length }}</span></div>
    <button #toggle type="button" class="work-record-toggle" [attr.aria-expanded]="expanded()"
      [attr.aria-controls]="id" (click)="expanded.set(!expanded())">
      <span><strong>{{ current()?.title || i18n.t('experience.records.choose') }}</strong>
        @if (current()?.subtitle; as subtitle) { <small>{{ subtitle }}</small> }
      </span>
      <span>{{ i18n.t(expanded() ? 'experience.records.close' : 'experience.records.change') }}
        <app-icon [name]="expanded() ? 'chevron-up' : 'chevron-down'" [size]="14" />
      </span>
    </button>
    <div class="work-record-browser" [id]="id" [class.is-expanded]="expanded()">
      <div class="work-record-filters">
        <label><span>{{ i18n.t('common.search') }}</span>
          <input type="search" [value]="query()" (input)="query.set($any($event.target).value)"
            [placeholder]="i18n.t('experience.records.search_hint')" />
        </label>
        @if (statuses().length > 1) {
          <label><span>{{ i18n.t('experience.records.status') }}</span>
            <select [value]="status()" (change)="status.set($any($event.target).value)">
              <option value="">{{ i18n.t('experience.records.all_statuses') }}</option>
              @for (option of statuses(); track option.value) { <option [value]="option.value">{{ option.label }}</option> }
            </select>
          </label>
        }
      </div>
      <p class="work-record-count" role="status">{{ i18n.t('experience.records.count', { shown: visible().length, total: items().length }) }}</p>
      @if (currentHidden()) { <p class="work-record-filter-note">{{ i18n.t('experience.records.selected_hidden', { title: current()!.title }) }}</p> }
      <ul #list class="work-record-list" [attr.aria-labelledby]="id + '-title'">
        @for (item of visible(); track item.id) {
          <li><button type="button" class="work-record-item" [class.is-selected]="selected() === item.id"
            [attr.aria-current]="selected() === item.id ? 'true' : null" [disabled]="disabled()" (click)="choose(item.id)">
            <span class="work-record-item-top"><strong>{{ item.title }}</strong>@if (item.value) { <span>{{ item.value }}</span> }</span>
            @if (item.subtitle) { <span>{{ item.subtitle }}</span> }
            @if (item.description) { <span class="work-record-secondary">{{ item.description }}</span> }
            @if (item.badge; as badge) { <span class="work-record-badge" [class.is-warning]="badge.tone === 'warning'">{{ badge.label }}</span> }
            @if (item.status; as itemStatus) { <span class="work-record-status">{{ itemStatus.label }}</span> }
            @if (item.meta) { <span class="work-record-secondary work-record-meta">{{ item.meta }}</span> }
          </button></li>
        } @empty { <li class="work-record-empty">{{ items().length ? i18n.t('experience.records.no_match') : emptyText() }}</li> }
      </ul>
    </div>
  `,
})
export class WorkRecordQueueComponent {
  readonly i18n = inject(I18nService);
  readonly id = `work-records-${++nextQueueId}`;
  readonly title = input.required<string>();
  readonly items = input.required<readonly WorkRecordItem[]>();
  readonly selected = input<string | null>(null);
  readonly disabled = input(false);
  readonly emptyText = input('');
  readonly selectedChange = output<string>();
  readonly query = signal('');
  readonly status = signal('');
  readonly expanded = signal(false);
  readonly toggle = viewChild<ElementRef<HTMLButtonElement>>('toggle');
  readonly list = viewChild<ElementRef<HTMLUListElement>>('list');
  readonly current = computed(() => this.items().find(item => item.id === this.selected()));
  readonly statuses = computed(() => [...new Map(this.items().flatMap(item => item.status ? [[item.status.value, item.status] as const] : [])).values()]);
  readonly visible = computed(() => {
    const words = this.fold(this.query()).split(/\s+/).filter(Boolean);
    return this.items().filter(item => {
      const haystack = this.fold([item.id, item.title, item.subtitle, item.description, item.meta, item.status?.label].join(' '));
      return (!this.status() || item.status?.value === this.status()) && words.every(word => haystack.includes(word));
    });
  });
  readonly currentHidden = computed(() => !!this.current() && !this.visible().some(item => item.id === this.selected()));

  constructor() {
    afterRenderEffect(() => {
      this.selected(); this.visible(); this.expanded();
      this.revealSelected();
    });
  }

  revealSelected(): void {
    const list = this.list()?.nativeElement;
    const selected = list?.querySelector<HTMLButtonElement>('[aria-current="true"]');
    if (!list || !selected || !list.clientHeight) return;
    const bounds = list.getBoundingClientRect(), item = selected.getBoundingClientRect();
    // Only move the queue's own scroll position. Opening a deep link must
    // reveal its record without scrolling the whole page away from the work.
    if (item.bottom > bounds.bottom) list.scrollTop += item.bottom - bounds.bottom;
    else if (item.top < bounds.top) list.scrollTop -= bounds.top - item.top;
  }

  choose(id: string): void {
    if (this.disabled()) return;
    this.selectedChange.emit(id);
    this.expanded.set(false);
    // On narrow screens the chosen button disappears with the queue. Keep
    // keyboard focus on the visible disclosure rather than losing it to body.
    if (typeof matchMedia !== 'undefined' && matchMedia('(max-width: 760px)').matches) this.toggle()?.nativeElement.focus();
  }

  private fold(value: string): string {
    return value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase(this.i18n.locale());
  }
}
