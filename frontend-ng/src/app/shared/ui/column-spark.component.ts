/**
 * `<ck-column-spark>` — a column's distribution, small enough to sit in a list.
 *
 * `<ck-data-table>` draws this glyph in its headers, where there is room for a
 * scrollable table. The training surfaces need the same glyph somewhere much
 * tighter: choosing a target or a feature is a judgement about a column's
 * shape, and sending the author back to the dataset page to see that shape is
 * how a no-code studio stops feeling like one.
 *
 * It reads the profile the ingest worker already computed — a histogram for
 * numeric columns, top values for everything else — and hovers to the figures
 * behind it, so the glyph is never a picture without a legend.
 */
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
} from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import {
  isNumericKind,
  profileBars,
  profileFacts,
  type TabularColumnKind,
  type TabularColumnStats,
} from './data-table.vm';

@Component({
  selector: 'ck-column-spark',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (bars().length) {
      <span
        class="ck-spark"
        [class.ck-spark--cat]="!numeric()"
        [style.width.px]="width()"
        [style.height.px]="height()"
        [title]="summary()"
        aria-hidden="true"
      >
        @for (bar of bars(); track $index) {
          <span class="ck-spark__bar" [style.height.%]="bar.height"></span>
        }
      </span>
    }
  `,
  styles: [
    `
      :host {
        display: contents;
      }
      .ck-spark {
        display: inline-flex;
        align-items: flex-end;
        gap: 1px;
        flex-shrink: 0;
        opacity: 0.75;
        transition: opacity var(--ck-dur-fast, 120ms) var(--ck-ease-out, ease);
      }
      .ck-spark__bar {
        flex: 1 1 auto;
        min-width: 1px;
        border-radius: 1px 1px 0 0;
        background: var(--ck-signal-cool, #7dd3fc);
      }
      .ck-spark--cat .ck-spark__bar {
        background: var(--ck-signal-violet, #a78bfa);
      }
    `,
  ],
})
export class ColumnSparkComponent {
  protected readonly i18n = inject(I18nService);

  readonly stats = input<TabularColumnStats | null>(null);
  readonly kind = input<string>('other');
  readonly width = input<number>(46);
  readonly height = input<number>(14);

  protected readonly numeric = computed(() =>
    isNumericKind(this.kind() as TabularColumnKind),
  );

  protected readonly bars = computed(() =>
    profileBars(this.stats(), this.numeric(), this.i18n.t('data.table.null')),
  );

  /** The figures behind the glyph, for the reader who hovers it. */
  protected readonly summary = computed(() =>
    profileFacts(this.stats(), this.numeric())
      .map((fact) => {
        const label = this.i18n.t('data.table.profile.' + fact.key);
        const value =
          typeof fact.value === 'number'
            ? fact.value.toLocaleString(this.i18n.locale(), {
                maximumFractionDigits: 4,
              })
            : fact.value;
        return `${label} ${value}`;
      })
      .join(' · '),
  );
}
