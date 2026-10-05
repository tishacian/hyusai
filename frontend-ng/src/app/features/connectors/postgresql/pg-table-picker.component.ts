import { ChangeDetectionStrategy, Component, computed, inject, input, output, signal } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { groupTables, pgTableKey, type PgTable } from './postgresql.types';

/**
 * The accessible tables of a PostgreSQL catalog, filterable and grouped by
 * schema. Shared by the explorer page and the Flow source inspector, so a
 * catalog of hundreds of tables stays one search away in both.
 */
@Component({
  selector: 'app-pg-table-picker', standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent],
  template: `
    <div class="picker" [class.picker--compact]="compact()">
      <label class="picker-search">
        <app-icon name="search" [size]="13" />
        <input type="search" [value]="query()" (input)="query.set($any($event.target).value)"
          [attr.aria-label]="i18n.t('connectors.pg.search_tables')" [placeholder]="i18n.t('connectors.pg.search_tables')"
          [disabled]="disabled()" autocomplete="off" spellcheck="false" />
      </label>
      <p class="picker-count" aria-live="polite">{{ i18n.t('connectors.pg.tables_shown', { shown: shown(), total: tables().length }) }}</p>
      <div class="picker-list" role="group" [attr.aria-label]="i18n.t('connectors.pg.table')">
        @for (group of groups(); track group.schema) {
          <p class="picker-schema ck-mono">{{ group.schema }}</p>
          <ul>
            @for (table of group.tables; track table.name) {
              <li>
                <button type="button" class="picker-item" [class.is-selected]="key(table) === selected()"
                  [attr.aria-pressed]="key(table) === selected()" [disabled]="disabled()" (click)="picked.emit(table)">
                  <app-icon name="table" [size]="12" />
                  <span class="picker-name ck-mono">{{ table.name }}</span>
                  @if (table.kind === 'partitioned') { <span class="picker-tag">{{ i18n.t('connectors.pg.partitioned') }}</span> }
                  @if (marked().includes(key(table))) {
                    <span class="picker-tag picker-tag--in"><app-icon name="check" [size]="11" />{{ markedLabel() }}</span>
                  }
                </button>
              </li>
            }
          </ul>
        } @empty { <p class="picker-empty">{{ i18n.t('connectors.pg.no_match', { query: query() }) }}</p> }
      </div>
    </div>
  `,
  styles: [`
    :host { display: block; min-width: 0; }
    .picker { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
    .picker-search { display: flex; align-items: center; gap: 8px; padding: 0 10px; min-height: 36px; border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-sm); background: var(--ck-bg-inset); color: var(--ck-fg-3); }
    .picker-search:focus-within { outline: 2px solid var(--ck-primary); outline-offset: 2px; }
    .picker-search input { flex: 1; min-width: 0; border: 0; background: transparent; color: var(--ck-fg-1); font: inherit; font-size: 13px; outline: none; min-height: 34px; }
    .picker-count { margin: 0; color: var(--ck-fg-3); font-size: 11px; }
    .picker-list { max-height: 360px; overflow-y: auto; min-width: 0; border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-sm); background: var(--ck-bg-inset); padding: 4px 0; }
    .picker--compact .picker-list { max-height: 220px; }
    .picker-schema { margin: 8px 12px 4px; color: var(--ck-fg-3); font-size: 10px; letter-spacing: .08em; text-transform: uppercase; overflow-wrap: anywhere; }
    ul { list-style: none; margin: 0; padding: 0; }
    .picker-item { display: flex; align-items: center; gap: 8px; width: 100%; min-height: 32px; padding: 4px 12px; border: 0; border-left: 2px solid transparent; background: transparent; color: var(--ck-fg-2); font-size: 13px; text-align: left; cursor: pointer; }
    .picker-item:hover:not(:disabled) { background: var(--ck-bg-raised); color: var(--ck-fg-1); }
    .picker-item:focus-visible { outline: 2px solid var(--ck-primary); outline-offset: -2px; }
    .picker-item.is-selected { border-left-color: var(--ck-primary); background: var(--ck-bg-raised); color: var(--ck-fg-1); font-weight: 600; }
    .picker-item:disabled { cursor: default; opacity: .6; }
    .picker-name { flex: 1; min-width: 0; overflow-wrap: anywhere; }
    .picker-tag { display: inline-flex; align-items: center; gap: 3px; flex-shrink: 0; color: var(--ck-fg-3); font-size: 10px; font-weight: 500; }
    .picker-tag--in { color: var(--ck-status-ok-fg); }
    .picker-empty { margin: 12px; color: var(--ck-fg-3); font-size: 12px; overflow-wrap: anywhere; }
  `],
})
export class PgTablePickerComponent {
  protected readonly i18n = inject(I18nService);
  readonly tables = input.required<readonly PgTable[]>();
  /** `schema.table` of the open table. */
  readonly selected = input('');
  /** `schema.table` keys to tag, such as the tables already in a source's scope. */
  readonly marked = input<readonly string[]>([]);
  readonly markedLabel = input('');
  readonly disabled = input(false);
  readonly compact = input(false);
  readonly picked = output<PgTable>();
  protected readonly query = signal('');
  protected readonly groups = computed(() => groupTables(this.tables(), this.query()));
  protected readonly shown = computed(() => this.groups().reduce((count, group) => count + group.tables.length, 0));
  protected key(table: PgTable): string { return pgTableKey(table); }
}
