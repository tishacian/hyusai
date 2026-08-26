import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  type Type,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import type { ChartConfiguration, ChartData } from 'chart.js';
import { BaseChartDirective } from 'ng2-charts';
import { take } from 'rxjs/operators';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { TagComponent, type CkTagTone } from '@app/shared/cockpit';
import { I18nService } from '@app/core/i18n.service';
import { ThemeService } from '@app/core/theme.service';
import { ExperienceRuntimeService } from './experience-runtime.service';
import {
  type CertifiedType,
  type ExperienceNode,
  type LocalizedText,
  type RuntimeField,
  type RuntimeNodeContext,
  type RuntimeResultRow,
  chartKind,
  chartPalette,
  chartRamp,
  chartSeries,
  extractCitations,
  extractResult,
  fieldsFromSchema,
  humanizeIdentifier,
  isReadyFileReference,
  mapRunStatus,
  runtimeAfterSuccess,
  runtimeDataBinding,
  runtimeItems,
  runtimeResultRows,
  runtimeSummary,
  seedFromSchema,
  selectRuntimeData,
  textFallback,
  unavailablePolicy,
  validateValues,
  valuesToPayload,
} from './model';
import { a11yOf, appearanceOf } from './style';

function str(node: ExperienceNode, key: string, fallback = ''): string {
  const value = node.props?.[key];
  return typeof value === 'string' ? value : fallback;
}

/**
 * A copy prop as written, whether or not the document reached the renderer
 * localized: `localizeDocument` resolves `{$i18n, fallback}` into a plain
 * string, but a preview or a raw `parseDocument` hands the pair straight over.
 */
function copyText(node: ExperienceNode, key: string): string {
  const value = node.props?.[key];
  if (typeof value === 'string') return value;
  if (isRecord(value) && typeof value['$i18n'] === 'string' && typeof value['fallback'] === 'string') {
    return textFallback(value as unknown as LocalizedText);
  }
  return '';
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function itemLabel(value: unknown): string {
  if (!isRecord(value)) return String(value ?? '');
  for (const key of ['title', 'label', 'name', 'id']) {
    if (typeof value[key] === 'string' && value[key]) return value[key];
  }
  return JSON.stringify(value) ?? '';
}

function firstString(value: Record<string, unknown>, keys: readonly string[]): string {
  for (const key of keys) {
    if (typeof value[key] === 'string' && value[key]) return value[key];
  }
  return '';
}

type Slot = 'ready' | 'loading' | 'empty' | 'error';

function slotOf(node: ExperienceNode, empty: boolean, loading = false, error = false): Slot {
  if (node.props?.['loading'] === true || loading) return 'loading';
  if (typeof node.props?.['error'] === 'string' || error) return 'error';
  if (empty) return 'empty';
  return 'ready';
}

function dynamicValue(
  runtime: ExperienceRuntimeService,
  node: ExperienceNode,
  context: RuntimeNodeContext,
): unknown {
  const binding = runtimeDataBinding(node);
  if (!binding) return undefined;
  return selectRuntimeData(runtime.run(context.sourceStateKey)?.output_ref, binding.selector);
}

function dynamicSlot(
  runtime: ExperienceRuntimeService,
  node: ExperienceNode,
  context: RuntimeNodeContext,
  empty: boolean,
): Slot {
  if (!runtimeDataBinding(node)) return slotOf(node, empty);
  const phase = runtime.phase(context.sourceStateKey);
  return slotOf(node, empty, phase === 'loading' || phase === 'running', phase === 'error');
}

@Component({
  selector: 'xp-rt-slot',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [EmptyStateComponent],
  template: `
    @switch (state()) {
      @case ('loading') {
        <app-empty-state icon="sparkles" size="sm" [title]="i18n.t('common.loading')" />
      }
      @case ('error') {
        <app-empty-state
          icon="alert-triangle"
          size="sm"
          [title]="i18n.t('state.error.title')"
          [description]="errorDescription()"
        />
      }
      @case ('empty') {
        <app-empty-state
          [icon]="emptyIcon()"
          size="sm"
          [title]="emptyTitle() || i18n.t('state.empty.title')"
          [description]="empty() || i18n.t('state.empty.description')"
        />
      }
      @default {
        <ng-content />
      }
    }
  `,
})
export class RuntimeSlotComponent {
  readonly i18n = inject(I18nService);
  readonly state = input<Slot>('ready');
  readonly detail = input('');
  readonly errorDescription = computed(() =>
    this.detail() ? this.i18n.t('experience.runtime.error.body') : undefined,
  );
  readonly empty = input('');
  readonly emptyTitle = input('');
  readonly emptyIcon = input('inbox');
}

@Component({
  selector: 'xp-rt-fallback',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './runtime.scss',
  template: `
    <aside class="xp-rt-block xp-rt-fallback" role="note">
      <h3>{{ i18n.t('experience.runtime.unknown.title') }}</h3>
      <p class="xp-rt-sub">{{ i18n.t('experience.runtime.unknown.body') }}</p>
    </aside>
  `,
})
export class FallbackBlock {
  readonly i18n = inject(I18nService);
  readonly node = input.required<ExperienceNode>();
}

@Component({
  selector: 'xp-rt-section',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './runtime.scss',
  template: `
    <section class="xp-rt-block" [attr.aria-label]="ariaName() || null">
      @switch (level()) {
        @case (2) { <h2>{{ title() }}</h2> }
        @case (4) { <h4>{{ title() }}</h4> }
        @default { <h3>{{ title() }}</h3> }
      }
      @if (description()) {
        <p class="xp-rt-sub">{{ description() }}</p>
      }
    </section>
  `,
})
export class SectionBlock {
  readonly node = input.required<ExperienceNode>();
  readonly title = computed(() => appearanceOf(this.node()).title || this.node().id || '');
  readonly description = computed(() => appearanceOf(this.node()).description);
  readonly ariaName = computed(() => a11yOf(this.node()).ariaLabel);
  readonly level = computed(() => a11yOf(this.node()).headingLevel ?? 3);
}

@Component({
  selector: 'xp-rt-header',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './runtime.scss',
  template: `
    <header class="xp-rt-block" [attr.aria-label]="ariaName() || null">
      @switch (level()) {
        @case (2) { <h2 class="xp-rt-head">{{ title() }}</h2> }
        @case (4) { <h4 class="xp-rt-head">{{ title() }}</h4> }
        @default { <h3 class="xp-rt-head">{{ title() }}</h3> }
      }
      @if (subtitle()) {
        <p class="xp-rt-sub">{{ subtitle() }}</p>
      }
      @if (description()) {
        <p class="xp-rt-sub">{{ description() }}</p>
      }
    </header>
  `,
})
export class HeaderBlock {
  readonly node = input.required<ExperienceNode>();
  readonly title = computed(() => appearanceOf(this.node()).title || this.node().id || '');
  readonly subtitle = computed(() => str(this.node(), 'subtitle'));
  readonly description = computed(() => appearanceOf(this.node()).description);
  readonly ariaName = computed(() => a11yOf(this.node()).ariaLabel);
  readonly level = computed(() => a11yOf(this.node()).headingLevel ?? 3);
}

@Component({
  selector: 'xp-rt-callout',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  styleUrl: './runtime.scss',
  template: `
    <aside class="xp-rt-block" role="note">
      <p class="xp-rt-sub">{{ body() }}</p>
      @if (href()) {
        <a class="xp-rt-link" [routerLink]="href()">{{ href() }}</a>
      }
    </aside>
  `,
})
export class CalloutBlock {
  readonly node = input.required<ExperienceNode>();
  readonly body = computed(() => str(this.node(), 'body'));
  readonly href = computed(() => {
    const value = this.node().props?.['href'];
    if (typeof value !== 'string') return null;
    const trimmed = value.trim();
    if (!trimmed.startsWith('/') || trimmed.startsWith('//') || trimmed.includes('\\')) return null;
    return trimmed;
  });
}

@Component({
  selector: 'xp-rt-query-control',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './runtime.scss',
  template: `
    @if (query(); as binding) {
      <div class="xp-rt-query">
        @if (context().mode === 'preview') {
          <p class="xp-rt-hint">{{ i18n.t('experience.runtime.preview.read_only') }}</p>
        } @else if (confirming()) {
          <div
            class="xp-rt-confirm"
            role="group"
            [attr.aria-labelledby]="confirmTitleId()"
            (keydown.escape)="cancelConfirmation()"
          >
            <p class="xp-rt-sub" [id]="confirmTitleId()">{{ i18n.t('experience.runtime.query.confirm') }}</p>
            <div class="xp-rt-actions">
              <button type="button" class="xp-rt-btn xp-rt-btn-ghost" (click)="cancelConfirmation()">
                {{ i18n.t('common.cancel') }}
              </button>
              <button type="button" class="xp-rt-btn" data-confirm-accept (click)="invoke(true)">
                {{ i18n.t('common.confirm') }}
              </button>
            </div>
          </div>
        } @else {
          <button
            type="button"
            class="xp-rt-btn xp-rt-btn-ghost"
            data-action-trigger
            [disabled]="busy() || resolving() || blocked()"
            (click)="load()"
          >
            {{ i18n.t(hasRun() ? 'experience.runtime.query.refresh' : 'experience.runtime.query.load') }}
          </button>
          @if (blocked()) {
            <p class="xp-rt-err" role="alert">{{ i18n.t('experience.runtime.unavailable.body') }}</p>
          }
        }
      </div>
    }
  `,
})
export class RuntimeQueryControlComponent {
  private readonly runtime = inject(ExperienceRuntimeService);
  private readonly element: ElementRef<HTMLElement> = inject(ElementRef);
  readonly i18n = inject(I18nService);
  readonly node = input.required<ExperienceNode>();
  readonly context = input.required<RuntimeNodeContext>();
  readonly confirming = signal(false);
  readonly resolveStatus = signal<string | null>(null);
  private confirmation = false;

  readonly query = computed(() => {
    const binding = runtimeDataBinding(this.node());
    return binding?.source === 'system-binding' ? binding : null;
  });
  readonly busy = computed(() => {
    const phase = this.runtime.phase(this.context().stateKey);
    return phase === 'loading' || phase === 'running';
  });
  readonly blocked = computed(() => {
    const status = this.resolveStatus();
    return !!status && status !== 'ok' && status !== 'loading';
  });
  readonly resolving = computed(() => this.resolveStatus() === 'loading');
  readonly hasRun = computed(() => !!this.runtime.run(this.context().stateKey));
  readonly confirmTitleId = computed(() =>
    `xp-rt-${this.context().stateKey.replace(/[^a-zA-Z0-9_-]/g, '-')}-query-confirm`,
  );

  constructor() {
    effect(() => {
      const query = this.query();
      const context = this.context();
      if (!query?.bindingKey || context.mode !== 'live') {
        this.resolveStatus.set(null);
        return;
      }
      this.resolveStatus.set('loading');
      this.runtime.resolve(context, query.bindingKey).pipe(take(1)).subscribe((resolved) => {
        this.resolveStatus.set(resolved?.status ?? 'unavailable');
        this.confirmation = resolved?.binding.confirmation_policy === 'confirm';
      });
    });
  }

  load(): void {
    if (this.busy() || this.resolving() || this.blocked()) return;
    if (this.confirmation) {
      this.confirming.set(true);
      queueMicrotask(() => this.element.nativeElement.querySelector<HTMLElement>('[data-confirm-accept]')?.focus());
      return;
    }
    this.invoke(false);
  }

  invoke(confirmed: boolean): void {
    const query = this.query();
    if (!query?.bindingKey) return;
    this.confirming.set(false);
    if (confirmed) queueMicrotask(() => this.element.nativeElement.querySelector<HTMLElement>('[data-action-trigger]')?.focus());
    const context = this.context();
    this.runtime.invoke(context, query.bindingKey, query.input, confirmed || undefined).subscribe((started) => {
      if (started?.id) this.runtime.poll(context, started.id).subscribe();
    });
  }

  cancelConfirmation(): void {
    this.confirming.set(false);
    queueMicrotask(() => this.element.nativeElement.querySelector<HTMLElement>('[data-action-trigger]')?.focus());
  }
}

@Component({
  selector: 'xp-rt-kpi',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RuntimeQueryControlComponent, RuntimeSlotComponent],
  styleUrl: './runtime.scss',
  template: `
    <article class="xp-rt-block" [attr.aria-label]="ariaName() || null">
      <p class="xp-rt-sub">{{ label() }}</p>
      <xp-rt-slot [state]="slot()" [detail]="errorText()">
        <p class="xp-rt-kpi">{{ value() }}</p>
      </xp-rt-slot>
      @if (description()) {
        <p class="xp-rt-sub">{{ description() }}</p>
      }
      <xp-rt-query-control [node]="node()" [context]="context()" />
    </article>
  `,
})
export class KpiBlock {
  private readonly runtime = inject(ExperienceRuntimeService);
  readonly node = input.required<ExperienceNode>();
  readonly context = input.required<RuntimeNodeContext>();
  readonly label = computed(() => str(this.node(), 'label'));
  readonly description = computed(() => appearanceOf(this.node()).description);
  readonly ariaName = computed(() => a11yOf(this.node()).ariaLabel);
  readonly value = computed(() => {
    const dynamic = dynamicValue(this.runtime, this.node(), this.context());
    if (runtimeDataBinding(this.node())) {
      const summary = runtimeSummary(dynamic);
      return summary === undefined || summary === null ? '—' : String(summary);
    }
    const raw = this.node().props?.['value'];
    return raw === undefined || raw === null ? '—' : String(raw);
  });
  readonly slot = computed(() =>
    dynamicSlot(this.runtime, this.node(), this.context(), false),
  );
  readonly errorText = computed(() => this.runtime.lastError(this.context().sourceStateKey) ?? '');
}

@Component({
  selector: 'xp-rt-table',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RuntimeSlotComponent, RuntimeQueryControlComponent],
  styleUrl: './runtime.scss',
  template: `
    <div class="xp-rt-block" [attr.aria-label]="ariaName() || null">
      @if (title()) {
        <h3>{{ title() }}</h3>
      }
      @if (description()) {
        <p class="xp-rt-sub">{{ description() }}</p>
      }
      <xp-rt-query-control [node]="node()" [context]="context()" />
      <xp-rt-slot [state]="slot()" [empty]="emptyText()" [detail]="errorText()">
        <div
          class="xp-rt-table-scroll"
          role="region"
          tabindex="0"
          [attr.aria-label]="caption() || title() || i18n.t('experience.runtime.table.region')"
        >
          <table class="xp-rt-table">
            @if (caption()) {
              <caption class="xp-rt-sub">{{ caption() }}</caption>
            }
            <thead>
              <tr>
                @for (col of columns(); track col.key) {
                  <th scope="col">{{ col.label }}</th>
                }
              </tr>
            </thead>
            <tbody>
              @for (row of rows(); track $index) {
                <tr>
                  @for (col of columns(); track col.key) {
                    <td>{{ cell(row, col.key) }}</td>
                  }
                </tr>
              }
            </tbody>
          </table>
        </div>
      </xp-rt-slot>
    </div>
  `,
})
export class TableBlock {
  private readonly runtime = inject(ExperienceRuntimeService);
  readonly i18n = inject(I18nService);
  readonly node = input.required<ExperienceNode>();
  readonly context = input.required<RuntimeNodeContext>();
  readonly columns = computed(() => {
    const raw = list(this.node().props?.['columns']);
    const configured = raw.map((item, index) => {
      if (typeof item === 'string') return { key: item, label: humanizeIdentifier(item) };
      if (isRecord(item) && typeof item['key'] === 'string') {
        return {
          key: item['key'],
          label: typeof item['label'] === 'string' ? item['label'] : humanizeIdentifier(item['key']),
        };
      }
      return { key: `c${index}`, label: String(item) };
    });
    if (configured.length > 0) return configured;
    const first = this.rows()[0];
    return first ? Object.keys(first).map((key) => ({ key, label: humanizeIdentifier(key) })) : [];
  });
  readonly rows = computed(() => {
    const dynamic = dynamicValue(this.runtime, this.node(), this.context());
    const value = runtimeDataBinding(this.node()) ? dynamic : this.node().props?.['rows'];
    return runtimeItems(value).filter(isRecord);
  });
  readonly caption = computed(() => str(this.node(), 'caption'));
  readonly title = computed(() => appearanceOf(this.node()).title);
  readonly description = computed(() => appearanceOf(this.node()).description);
  readonly ariaName = computed(() => a11yOf(this.node()).ariaLabel);
  readonly emptyText = computed(() => a11yOf(this.node()).emptyText);
  readonly slot = computed(() =>
    dynamicSlot(this.runtime, this.node(), this.context(), this.rows().length === 0),
  );
  readonly errorText = computed(() => this.runtime.lastError(this.context().sourceStateKey) ?? '');
  cell(row: Record<string, unknown>, key: string): string {
    const value = row[key];
    return value === undefined || value === null ? '' : String(value);
  }
}

/**
 * `xp-rt-chart` — a labelled series as bars or as slices.
 *
 * A dashboard is legible at a glance or it is a table of numbers with a title,
 * and the certified catalog could express only the second. The two shapes cover
 * what a business page asks of a picture: bars rank categories against each
 * other, a donut shows how one total splits.
 *
 * Bars are DOM and the donut is a canvas: a handful of labelled rectangles is
 * laid out better by CSS than by a chart engine, and keeping them as elements
 * is what lets every label and number stay selectable text rather than pixels
 * a screen reader has to be told about separately. Arcs get chart.js, where
 * the geometry and its legend already exist.
 *
 * The bars are the block's own markup rather than the data plane's `ck-bar-list`
 * because the two are read at different distances. That list is an instrument:
 * 5px rules and 10.5px mono, dense enough to rank twenty feature importances in
 * a sidebar. This is a business page opened by someone deciding whether to fund
 * a retention campaign, read at a glance and often over a shoulder, and the
 * same picture at that size reads as a footnote.
 */
@Component({
  selector: 'xp-rt-chart',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RuntimeSlotComponent, RuntimeQueryControlComponent, BaseChartDirective],
  styleUrl: './runtime.scss',
  template: `
    <div class="xp-rt-block" [attr.aria-label]="ariaName() || null">
      @if (title()) {
        <h3>{{ title() }}</h3>
      }
      @if (caption()) {
        <p class="xp-rt-sub">{{ caption() }}</p>
      }
      <xp-rt-query-control [node]="node()" [context]="context()" />
      <xp-rt-slot [state]="slot()" [empty]="emptyText()" [detail]="errorText()">
        @if (kind() === 'donut') {
          <div class="xp-rt-chart-arc">
            <canvas
              baseChart
              type="doughnut"
              role="img"
              [attr.aria-label]="readout()"
              [data]="arcs()"
              [options]="arcOptions()"
            ></canvas>
            @if (totalDisplay(); as total) {
              <div class="xp-rt-chart-arc__hub" aria-hidden="true">
                <span class="xp-rt-chart-arc__total">{{ total }}</span>
                <span class="xp-rt-chart-arc__caption">
                  {{ i18n.t('experience.runtime.chart.total') }}
                </span>
              </div>
            }
          </div>
        } @else {
          <ul class="xp-rt-bars">
            @for (bar of bars(); track bar.label; let index = $index) {
              <li
                class="xp-rt-bars__row"
                [style.--xp-bar]="bar.color"
                [style.--xp-bar-order]="index"
              >
                <div class="xp-rt-bars__head">
                  <span class="xp-rt-bars__label" [title]="bar.label">{{ bar.label }}</span>
                  <span class="xp-rt-bars__figure">
                    <span class="xp-rt-bars__value">{{ bar.display }}</span>
                    @if (bar.share) {
                      <span class="xp-rt-bars__share">{{ bar.share }}</span>
                    }
                  </span>
                </div>
                <div class="xp-rt-bars__track">
                  <span
                    class="xp-rt-bars__fill"
                    [style.width.%]="bar.width"
                    [attr.data-negative]="bar.negative"
                  ></span>
                </div>
              </li>
            }
          </ul>
        }
        @if (hidden()) {
          <p class="xp-rt-hint">{{ i18n.t('experience.runtime.chart.capped', { n: hidden() }) }}</p>
        }
      </xp-rt-slot>
    </div>
  `,
})
export class ChartBlock {
  private readonly runtime = inject(ExperienceRuntimeService);
  private readonly element: ElementRef<HTMLElement> = inject(ElementRef);
  private readonly theme = inject(ThemeService);
  readonly i18n = inject(I18nService);
  readonly node = input.required<ExperienceNode>();
  readonly context = input.required<RuntimeNodeContext>();
  readonly title = computed(() => copyText(this.node(), 'title'));
  readonly caption = computed(() => copyText(this.node(), 'caption'));
  readonly ariaName = computed(() => a11yOf(this.node()).ariaLabel);
  readonly emptyText = computed(() => a11yOf(this.node()).emptyText);
  readonly kind = computed(() => chartKind(this.node().props?.['kind']));
  readonly series = computed(() => {
    const node = this.node();
    // A binding owns the block from the moment it exists, exactly as it does on
    // a table: the authored series is the source for an unbound chart, never a
    // placeholder drawn beside numbers a run is still producing.
    const value = runtimeDataBinding(node)
      ? dynamicValue(this.runtime, node, this.context())
      : node.props?.['series'];
    return chartSeries(
      value,
      str(node, 'labelKey') || 'label',
      str(node, 'valueKey') || 'value',
    );
  });
  readonly hidden = computed(() => this.series().hidden);
  readonly palette = computed(() => chartPalette(this.node().props?.['palette']));

  /**
   * The colour each bar and slice is drawn in.
   *
   * Computed once for the series rather than per bar because a ramp is a
   * property of the set: the ends of green → red have to mean the same thing
   * whether the run came back with three bands or eleven.
   */
  private readonly colors = computed(() => {
    const points = this.series().points;
    if (this.palette() === 'severity') {
      return chartRamp(
        SEVERITY_TOKENS.map(([name, fallback]) => this.token(name, fallback)),
        points.length,
      );
    }
    const accent = this.token('--ck-accent', '#7dd3fc');
    return points.map(() => accent);
  });

  readonly bars = computed<ChartBar[]>(() => {
    const locale = this.i18n.locale();
    const colors = this.colors();
    return this.series().points.map((point, index) => ({
      label: point.label,
      // The scaling is arithmetic the series did; the number needs a locale,
      // which is the one part of a bar a component drawing rectangles cannot
      // decide for itself.
      display: point.value.toLocaleString(locale, { maximumFractionDigits: 2 }),
      // Under a point of the total the rounded figure would read "0%", which
      // says measured-nothing about a band that does have subscribers in it.
      share:
        point.share === null
          ? ''
          : point.share < 1
            ? '<1%'
            : `${Math.round(point.share)}%`,
      width: point.width,
      negative: point.value < 0,
      color: colors[index] ?? '',
    }));
  });

  /**
   * The figure written through the middle of the donut.
   *
   * A ring shows how a total splits and then declines to say what the total
   * was, which is the first thing anyone asks it. Withheld on a series that is
   * not a whole, for the same reason the shares are.
   */
  readonly totalDisplay = computed(() => {
    const points = this.series().points;
    if (points.length === 0 || points.some((point) => point.share === null)) return '';
    return points
      .reduce((sum, point) => sum + point.value, 0)
      .toLocaleString(this.i18n.locale(), { maximumFractionDigits: 2 });
  });

  readonly slot = computed(() =>
    dynamicSlot(this.runtime, this.node(), this.context(), this.series().points.length === 0),
  );
  readonly errorText = computed(() => this.runtime.lastError(this.context().sourceStateKey) ?? '');

  /**
   * What a screen reader is told the donut says.
   *
   * A bare `role="img"` announces nothing, and unlike the bar list — whose
   * labels and numbers are text on the page — a canvas hides every figure it
   * draws. So the reading is the label: the series spelled out, in the order it
   * is drawn.
   */
  protected readonly readout = computed(() => {
    const name = this.title() || this.caption() || this.i18n.t('experience.runtime.chart.region');
    const spoken = this.series()
      .points.map((point) => `${point.label} ${point.value}`)
      .join(', ');
    return spoken ? `${name}: ${spoken}` : name;
  });

  /**
   * The token values the arcs are drawn with, re-read when the theme changes.
   *
   * A canvas takes a colour and nothing else: `var()` does not resolve there,
   * so the `--ck-*` tokens are looked up off the host rather than handed to the
   * renderer as text it cannot parse. Reading `theme.resolved()` is what makes
   * the flip work — without it a donut drawn dark keeps its dark greys.
   */
  private readonly arcPalette = computed(() => {
    this.theme.resolved();
    return {
      seam: this.token('--ck-bg-panel', '#0e1216'),
      text: this.token('--ck-fg-2', 'rgba(255, 255, 255, 0.82)'),
    };
  });

  protected readonly arcs = computed<ChartData<'doughnut'>>(() => {
    const points = this.series().points;
    // An unordered series keeps the categorical set — six distinguishable hues
    // that claim no ranking — while `severity` walks the same ramp the bars do,
    // so the two shapes of the same block never disagree about what red means.
    const slices =
      this.palette() === 'severity'
        ? this.colors()
        : points.map(
            (_, index) =>
              this.token(...SLICE_TOKENS[index % SLICE_TOKENS.length]!),
          );
    return {
      labels: points.map((point) => point.label),
      datasets: [
        {
          data: points.map((point) => point.value),
          backgroundColor: slices,
          // The ring lifts off the page on hover rather than only recolouring,
          // which is the one affordance telling a reader the arcs are live.
          hoverOffset: 10,
          hoverBorderColor: this.arcPalette().seam,
          borderColor: this.arcPalette().seam,
          borderWidth: 3,
          borderRadius: 6,
          spacing: 2,
        },
      ],
    };
  });

  protected readonly arcOptions = computed<ChartConfiguration<'doughnut'>['options']>(() => ({
    responsive: true,
    maintainAspectRatio: false,
    // Thinner than the default ring so the hub has room for the total, and so
    // the arcs read as a gauge rather than as a pie with a hole punched in it.
    cutout: '70%',
    animation: { animateRotate: true, animateScale: false, duration: 900, easing: 'easeOutQuart' },
    plugins: {
      legend: {
        position: 'bottom',
        labels: {
          color: this.arcPalette().text,
          boxWidth: 8,
          boxHeight: 8,
          usePointStyle: true,
          pointStyle: 'circle',
          padding: 14,
          font: { size: 12 },
        },
      },
    },
  }));

  /**
   * A `--ck-*` token's value, or the fallback.
   *
   * A canvas takes a colour and nothing else: `var()` does not resolve there,
   * so the tokens are looked up off the host rather than handed to the renderer
   * as text it cannot parse. Reading `theme.resolved()` in {@link arcPalette}
   * is what makes the flip work — without it a donut drawn dark keeps its dark
   * greys.
   *
   * Falls back whole when there is no live document to compute against, which
   * is the unit runner: the colours are then the ones written here, which is
   * what those tests assert on and what an SSR pass would emit.
   */
  private token(name: string, fallback: string): string {
    const host = this.element.nativeElement;
    if (typeof getComputedStyle !== 'function' || host?.nodeType !== 1) return fallback;
    return getComputedStyle(host).getPropertyValue(name).trim() || fallback;
  }
}

@Component({
  selector: 'xp-rt-queue',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RuntimeSlotComponent, RuntimeQueryControlComponent],
  styleUrl: './runtime.scss',
  template: `
    <section class="xp-rt-block" [attr.aria-label]="ariaName() || i18n.t('experience.runtime.queue.title')">
      <h3>{{ title() || i18n.t('experience.runtime.queue.title') }}</h3>
      @if (description()) {
        <p class="xp-rt-sub">{{ description() }}</p>
      }
      <xp-rt-query-control [node]="node()" [context]="context()" />
      <xp-rt-slot [state]="slot()" [empty]="emptyText()" [detail]="errorText()">
        <ul class="xp-rt-list">
          @for (item of items(); track $index) {
            <li>{{ item }}</li>
          }
        </ul>
      </xp-rt-slot>
    </section>
  `,
})
export class QueueBlock {
  private readonly runtime = inject(ExperienceRuntimeService);
  readonly i18n = inject(I18nService);
  readonly node = input.required<ExperienceNode>();
  readonly context = input.required<RuntimeNodeContext>();
  readonly items = computed(() =>
    runtimeItems(
      runtimeDataBinding(this.node())
        ? dynamicValue(this.runtime, this.node(), this.context())
        : this.node().props?.['items'],
    ).map(itemLabel),
  );
  readonly title = computed(() => appearanceOf(this.node()).title);
  readonly description = computed(() => appearanceOf(this.node()).description);
  readonly ariaName = computed(() => a11yOf(this.node()).ariaLabel);
  readonly emptyText = computed(() => a11yOf(this.node()).emptyText);
  readonly slot = computed(() =>
    dynamicSlot(this.runtime, this.node(), this.context(), this.items().length === 0),
  );
  readonly errorText = computed(() => this.runtime.lastError(this.context().sourceStateKey) ?? '');
}

@Component({
  selector: 'xp-rt-approval',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RuntimeSlotComponent, RuntimeQueryControlComponent, TagComponent],
  styleUrl: './runtime.scss',
  template: `
    <article class="xp-rt-block" [attr.aria-label]="ariaName() || null">
      <xp-rt-query-control [node]="node()" [context]="context()" />
      <xp-rt-slot [state]="slot()" [empty]="emptyText()">
        <div class="xp-rt-row">
          <h3>{{ title() }}</h3>
          @if (status()) {
            <ck-tag tone="warn">{{ status() }}</ck-tag>
          }
        </div>
        <p class="xp-rt-sub">{{ body() }}</p>
        @if (description()) {
          <p class="xp-rt-sub">{{ description() }}</p>
        }
      </xp-rt-slot>
    </article>
  `,
})
export class ApprovalCardBlock {
  private readonly runtime = inject(ExperienceRuntimeService);
  readonly node = input.required<ExperienceNode>();
  readonly context = input.required<RuntimeNodeContext>();
  readonly data = computed(() => {
    const value = dynamicValue(this.runtime, this.node(), this.context());
    return runtimeDataBinding(this.node()) && isRecord(value) ? value : {};
  });
  readonly title = computed(() =>
    firstString(this.data(), ['title', 'label', 'name'])
      || appearanceOf(this.node()).title || this.node().id || '',
  );
  readonly body = computed(() =>
    firstString(this.data(), ['body', 'description', 'message', 'summary']) || str(this.node(), 'body'),
  );
  readonly description = computed(() => appearanceOf(this.node()).description);
  readonly ariaName = computed(() => a11yOf(this.node()).ariaLabel);
  readonly emptyText = computed(() => a11yOf(this.node()).emptyText);
  readonly status = computed(() =>
    firstString(this.data(), ['status', 'state']) || str(this.node(), 'status'),
  );
  readonly slot = computed(() =>
    runtimeDataBinding(this.node())
      ? dynamicSlot(this.runtime, this.node(), this.context(), !this.title() && !this.body())
      : slotOf(this.node(), !this.title() && !this.body()),
  );
}

@Component({
  selector: 'xp-rt-history',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RuntimeQueryControlComponent, RuntimeSlotComponent],
  styleUrl: './runtime.scss',
  template: `
    <section class="xp-rt-block" [attr.aria-label]="i18n.t('experience.runtime.history.title')">
      <h3>{{ i18n.t('experience.runtime.history.title') }}</h3>
      <xp-rt-query-control [node]="node()" [context]="context()" />
      <xp-rt-slot
        [state]="slot()"
        [detail]="errorText()"
        [empty]="i18n.t('experience.runtime.history.pending')"
      >
        <ul class="xp-rt-list">
          @for (item of items(); track $index) {
            <li>
              <span>{{ item.title }}</span>
              @if (item.at) {
                <span>{{ item.at }}</span>
              }
            </li>
          }
        </ul>
      </xp-rt-slot>
    </section>
  `,
})
export class HistoryBlock {
  private readonly runtime = inject(ExperienceRuntimeService);
  readonly i18n = inject(I18nService);
  readonly node = input.required<ExperienceNode>();
  readonly context = input.required<RuntimeNodeContext>();
  readonly implicit = computed(() => !runtimeDataBinding(this.node()) && this.node().props?.['items'] === undefined);
  readonly items = computed(() =>
    runtimeItems(
      runtimeDataBinding(this.node())
        ? dynamicValue(this.runtime, this.node(), this.context())
        : this.node().props?.['items'] ?? this.runtime.state(this.context().sourceStateKey).history,
    ).map((item) => {
      if (typeof item === 'string') return { title: item, at: '' };
      if (isRecord(item)) {
        return {
          title: itemLabel(item),
          at: typeof item['at'] === 'string' ? item['at'] : typeof item['when'] === 'string' ? item['when'] : '',
        };
      }
      return { title: String(item), at: '' };
    }),
  );
  readonly slot = computed(() => {
    if (runtimeDataBinding(this.node())) {
      return dynamicSlot(this.runtime, this.node(), this.context(), this.items().length === 0);
    }
    const phase = this.runtime.phase(this.context().sourceStateKey);
    return slotOf(
      this.node(),
      this.items().length === 0,
      this.implicit() && (phase === 'loading' || phase === 'running'),
      this.implicit() && phase === 'error',
    );
  });
  readonly errorText = computed(() => this.runtime.lastError(this.context().sourceStateKey) ?? '');
}

@Component({
  selector: 'xp-rt-status',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TagComponent],
  styleUrl: './runtime.scss',
  template: `
    <div class="xp-rt-block xp-rt-row" role="status" aria-live="polite">
      <ck-tag [tone]="tone()">{{ label() }}</ck-tag>
    </div>
  `,
})
export class RuntimeStatusBlock {
  private readonly runtime = inject(ExperienceRuntimeService);
  readonly i18n = inject(I18nService);
  readonly node = input.required<ExperienceNode>();
  readonly context = input.required<RuntimeNodeContext>();
  readonly vocab = computed(() => {
    const projected = runtimeDataBinding(this.node())
      ? runtimeSummary(dynamicValue(this.runtime, this.node(), this.context()))
      : undefined;
    const value = typeof projected === 'string'
      ? projected
      : str(this.node(), 'status') || this.runtime.run(this.context().sourceStateKey)?.status;
    return mapRunStatus(value);
  });
  readonly label = computed(() => {
    const vocab = this.vocab();
    if (!vocab) return this.i18n.t('experience.runtime.status.idle');
    return this.i18n.t(`experience.runtime.status.${vocab}`);
  });
  readonly tone = computed<CkTagTone>(() => {
    switch (this.vocab()) {
      case 'completed':
        return 'pos';
      case 'pending_validation':
      case 'running':
        return 'cool';
      case 'retry':
        return 'warn';
      case 'error':
        return 'neg';
      default:
        return 'neutral';
    }
  });
}

@Component({
  selector: 'xp-rt-result',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RuntimeSlotComponent],
  styleUrl: './runtime.scss',
  template: `
    <section class="xp-rt-block" [attr.aria-label]="i18n.t('experience.runtime.result.title')">
      <h3>{{ i18n.t('experience.runtime.result.title') }}</h3>
      <xp-rt-slot
        [state]="slot()"
        [detail]="errorText()"
        emptyIcon="clock"
        [emptyTitle]="i18n.t('experience.runtime.result.pending.title')"
        [empty]="i18n.t('experience.runtime.result.pending.body')"
      >
        @if (rows().length === 1 && rows()[0]!.path.length === 0) {
          <p class="xp-rt-result-value">{{ resultValue(rows()[0]!.value) }}</p>
        } @else if (rows().length > 0) {
          <dl class="xp-rt-kv">
            @for (row of rows(); track $index) {
              <dt>{{ resultLabel(row) }}</dt>
              <dd>{{ resultValue(row.value) }}</dd>
            }
          </dl>
        }
      </xp-rt-slot>
    </section>
  `,
})
export class ResultBlock {
  private readonly runtime = inject(ExperienceRuntimeService);
  readonly i18n = inject(I18nService);
  readonly node = input.required<ExperienceNode>();
  readonly context = input.required<RuntimeNodeContext>();
  readonly data = computed(() => {
    if (runtimeDataBinding(this.node())) {
      return dynamicValue(this.runtime, this.node(), this.context());
    }
    const fromProps = this.node().props?.['value'];
    if (fromProps !== undefined) return fromProps;
    return extractResult(this.runtime.run(this.context().sourceStateKey));
  });
  readonly rows = computed(() => runtimeResultRows(this.data()));
  readonly slot = computed(() => runtimeDataBinding(this.node())
    ? dynamicSlot(this.runtime, this.node(), this.context(), this.data() === null || this.data() === undefined)
    : slotOf(
      this.node(),
      this.data() === null || this.data() === undefined,
      this.runtime.phase(this.context().sourceStateKey) === 'loading'
        || this.runtime.phase(this.context().sourceStateKey) === 'running',
      this.runtime.phase(this.context().sourceStateKey) === 'error',
    ));
  readonly errorText = computed(() => this.runtime.lastError(this.context().sourceStateKey) ?? '');

  resultLabel(row: RuntimeResultRow): string {
    return row.path.map((part) => typeof part === 'number'
      ? this.i18n.t('experience.runtime.result.item', { n: part })
      : part).join(' · ');
  }

  resultValue(value: RuntimeResultRow['value']): string {
    if (value === null) return '—';
    if (typeof value === 'boolean') {
      return this.i18n.t(value ? 'common.yes' : 'common.no');
    }
    return String(value);
  }
}

@Component({
  selector: 'xp-rt-evidence',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RuntimeSlotComponent],
  styleUrl: './runtime.scss',
  template: `
    <section class="xp-rt-block" [attr.aria-label]="i18n.t('experience.runtime.evidence.title')">
      <h3>{{ i18n.t('experience.runtime.evidence.title') }}</h3>
      <xp-rt-slot
        [state]="slot()"
        [detail]="errorText()"
        [empty]="i18n.t('experience.runtime.evidence.pending')"
      >
        <ul class="xp-rt-list">
          @for (item of citations(); track $index) {
            <li>
              <span>{{ item.title }}</span>
              @if (item.source) {
                <span>{{ item.source }}</span>
              }
            </li>
          }
        </ul>
      </xp-rt-slot>
    </section>
  `,
})
export class EvidenceBlock {
  private readonly runtime = inject(ExperienceRuntimeService);
  readonly i18n = inject(I18nService);
  readonly node = input.required<ExperienceNode>();
  readonly context = input.required<RuntimeNodeContext>();
  readonly citations = computed(() => {
    if (runtimeDataBinding(this.node())) {
      const value = dynamicValue(this.runtime, this.node(), this.context());
      if (Array.isArray(value)) return extractCitations({ output_ref: { citations: value } });
      if (isRecord(value)) return extractCitations({ output_ref: value });
      return [];
    }
    const fromProps = this.node().props?.['citations'];
    if (Array.isArray(fromProps)) {
      return extractCitations({ output_ref: { citations: fromProps } });
    }
    return extractCitations(this.runtime.run(this.context().sourceStateKey));
  });
  readonly slot = computed(() => runtimeDataBinding(this.node())
    ? dynamicSlot(this.runtime, this.node(), this.context(), this.citations().length === 0)
    : slotOf(this.node(), this.citations().length === 0));
  readonly errorText = computed(() => this.runtime.lastError(this.context().sourceStateKey) ?? '');
}

@Component({
  selector: 'xp-rt-form',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RuntimeSlotComponent, EmptyStateComponent],
  styleUrl: './runtime.scss',
  template: `
    <form
      class="xp-rt-block"
      novalidate
      (submit)="$event.preventDefault(); submit()"
      [attr.aria-busy]="busy()"
      [attr.aria-label]="ariaName() || null"
    >
      @if (title()) {
        <h3>{{ title() }}</h3>
      }
      @if (description()) {
        <p class="xp-rt-sub">{{ description() }}</p>
      }
      @if (context().mode === 'preview') {
        <p class="xp-rt-preview-note" role="status">{{ i18n.t('experience.runtime.preview.read_only') }}</p>
      }
      @if (blocked()) {
        <app-empty-state
          icon="alert-triangle"
          size="sm"
          [title]="unavailableTitle()"
          [description]="unavailableBody()"
        />
      }
      @if (unlinked()) {
        <app-empty-state
          icon="link"
          size="sm"
          [title]="i18n.t('experience.runtime.form.no_link.title')"
          [description]="i18n.t('experience.runtime.form.no_link.body')"
        />
      } @else {
        <xp-rt-slot
          [state]="slot()"
          [emptyTitle]="i18n.t('experience.runtime.form.no_input.title')"
          [empty]="emptyText() || i18n.t('experience.runtime.form.no_input.body')"
        >
          @for (field of fields(); track field.name) {
            <div class="xp-rt-field">
              <label [for]="fid(field)">
                {{ field.label }}
                @if (field.required) { <span aria-hidden="true">*</span> }
              </label>
              @switch (field.kind) {
                @case ('boolean') {
                  <input
                    type="checkbox"
                    [id]="fid(field)"
                    [checked]="values()[field.name] === true"
                    [attr.aria-invalid]="!!errors()[field.name]"
                    [attr.aria-required]="field.required"
                    [attr.aria-describedby]="descIds(field)"
                    (change)="set(field.name, checkboxValue($event))"
                  />
                }
                @case ('enum') {
                  <select
                    [id]="fid(field)"
                    [value]="strVal(field.name)"
                    [required]="field.required"
                    [attr.aria-invalid]="!!errors()[field.name]"
                    [attr.aria-describedby]="descIds(field)"
                    (change)="set(field.name, inputValue($event))"
                  >
                    <option value=""></option>
                    @for (opt of field.options; track opt; let optionIndex = $index) {
                      <option [value]="opt">{{ field.optionLabels[optionIndex] || opt }}</option>
                    }
                  </select>
                }
                @case ('file') {
                  <input
                    type="file"
                    [id]="fid(field)"
                    [accept]="field.accept"
                    [required]="field.required"
                    [disabled]="context().mode === 'preview' || uploading()[field.name] === true"
                    [attr.aria-invalid]="!!errors()[field.name]"
                    [attr.aria-describedby]="descIds(field)"
                    (change)="selectFile(field, $event)"
                  />
                }
                @default {
                  <input
                    [type]="inputType(field)"
                    [id]="fid(field)"
                    [value]="strVal(field.name)"
                    [required]="field.required"
                    [attr.aria-invalid]="!!errors()[field.name]"
                    [attr.aria-describedby]="descIds(field)"
                    (input)="set(field.name, inputValue($event))"
                  />
                }
              }
              @if (field.description) {
                <p class="xp-rt-hint" [id]="fid(field) + '-desc'">{{ field.description }}</p>
              }
              @if (field.kind === 'file') {
                <p class="xp-rt-hint" [id]="fid(field) + '-hint'">{{ i18n.t('experience.runtime.form.file_hint') }}</p>
                @if (uploading()[field.name]) {
                  <p class="xp-rt-hint" [id]="fid(field) + '-upload'" role="status">
                    {{ i18n.t('experience.runtime.form.file_uploading') }}
                  </p>
                } @else if (fileNames()[field.name]; as filename) {
                  <p class="xp-rt-hint" [id]="fid(field) + '-upload'" role="status">
                    {{ i18n.t('experience.runtime.form.file_ready', { name: filename }) }}
                  </p>
                }
              }
              @if (errors()[field.name]; as err) {
                <p class="xp-rt-err" [id]="fid(field) + '-err'" role="alert">
                  {{ i18n.t(err === 'required' ? 'experience.runtime.form.required' : 'experience.runtime.form.invalid') }}
                </p>
              }
            </div>
          }
        </xp-rt-slot>
        @if (confirming()) {
          <div
            class="xp-rt-confirm"
            role="group"
            data-confirm
            [attr.aria-labelledby]="confirmTitleId()"
            (keydown.escape)="cancelConfirmation()"
          >
            <h3 [id]="confirmTitleId()">{{ i18n.t('experience.runtime.form.confirm_title') }}</h3>
            <p class="xp-rt-sub">{{ i18n.t('experience.runtime.form.confirm_body') }}</p>
            <div class="xp-rt-actions">
              <button type="button" class="xp-rt-btn xp-rt-btn-ghost" (click)="cancelConfirmation()">
                {{ i18n.t('common.cancel') }}
              </button>
              <button type="button" class="xp-rt-btn" data-confirm-accept (click)="invoke(true)">
                {{ i18n.t('common.confirm') }}
              </button>
            </div>
          </div>
        } @else {
          <div class="xp-rt-actions">
            <button
              type="submit"
              class="xp-rt-btn"
              data-action-trigger
              [disabled]="busy() || resolving() || blocked() || context().mode === 'preview' || hasUpload()"
            >
              {{ submitLabel() }}
            </button>
            @if (canRetry() && context().mode === 'live') {
              <button type="button" class="xp-rt-btn xp-rt-btn-ghost" (click)="retry()">
                {{ i18n.t('common.retry') }}
              </button>
            }
          </div>
        }
      }
    </form>
  `,
})
export class FormBlock {
  private readonly runtime = inject(ExperienceRuntimeService);
  private readonly element: ElementRef<HTMLElement> = inject(ElementRef);
  private readonly router = inject(Router);
  readonly i18n = inject(I18nService);
  readonly node = input.required<ExperienceNode>();
  readonly context = input.required<RuntimeNodeContext>();
  readonly values = signal<Record<string, unknown>>({});
  readonly errors = signal<Record<string, 'required' | 'invalid'>>({});
  readonly confirming = signal(false);
  readonly uploading = signal<Record<string, boolean>>({});
  readonly fileNames = signal<Record<string, string>>({});
  readonly resolveStatus = signal<string | null>(null);
  readonly policy = signal(unavailablePolicy(undefined));
  readonly confirmTitleId = computed(() => `${this.domPrefix()}-confirm-title`);

  readonly fields = computed(() => fieldsFromSchema(
    this.node().props?.['schema'],
    this.node().props?.['fieldPresentation'],
  ));
  readonly title = computed(() => appearanceOf(this.node()).title);
  readonly description = computed(() => appearanceOf(this.node()).description);
  readonly ariaName = computed(() => a11yOf(this.node()).ariaLabel);
  readonly emptyText = computed(() => a11yOf(this.node()).emptyText);
  readonly bindingKey = computed(() => str(this.node(), 'bindingKey'));
  readonly unlinked = computed(() => !this.bindingKey());
  readonly submitLabel = computed(
    () => str(this.node(), 'submitLabel') || this.i18n.t('experience.runtime.form.submit'),
  );
  readonly busy = computed(
    () => {
      const phase = this.runtime.phase(this.context().stateKey);
      return phase === 'loading' || phase === 'running';
    },
  );
  readonly hasUpload = computed(() => Object.values(this.uploading()).some(Boolean));
  readonly blocked = computed(() => {
    const status = this.resolveStatus();
    return !!status && status !== 'ok' && status !== 'loading';
  });
  readonly resolving = computed(() => this.resolveStatus() === 'loading');
  readonly slot = computed<Slot>(() => slotOf(this.node(), this.fields().length === 0));
  readonly unavailableTitle = computed(() => {
    if (this.policy() === 'admin-repair') return this.i18n.t('experience.runtime.unavailable.repair.title');
    if (this.policy() === 'empty') return this.i18n.t('experience.runtime.unavailable.empty.title');
    return this.i18n.t('experience.runtime.unavailable.title');
  });
  readonly unavailableBody = computed(() => {
    if (this.policy() === 'admin-repair') return this.i18n.t('experience.runtime.unavailable.repair.body');
    if (this.policy() === 'empty') return this.i18n.t('experience.runtime.unavailable.empty.body');
    return this.i18n.t('experience.runtime.unavailable.body');
  });
  readonly canRetry = computed(() => {
    const status = mapRunStatus(this.runtime.run(this.context().stateKey)?.status);
    return status === 'error' || status === 'retry' || this.runtime.phase(this.context().stateKey) === 'error';
  });

  constructor() {
    let seeded = false;
    effect(() => {
      if (seeded) return;
      this.values.set({ ...seedFromSchema(this.node().props?.['schema']) });
      this.errors.set({});
      seeded = true;
    });
    effect(() => {
      const key = this.bindingKey();
      const context = this.context();
      if (!key || context.mode !== 'live') {
        this.resolveStatus.set(null);
        return;
      }
      this.resolveStatus.set('loading');
      this.runtime.resolve(context, key).pipe(take(1)).subscribe((resolved) => {
        if (!resolved) {
          this.resolveStatus.set('unavailable');
          this.policy.set('unavailable');
          return;
        }
        this.resolveStatus.set(resolved.status);
        this.policy.set(unavailablePolicy(resolved.binding.on_unavailable));
        this.confirmation = resolved.binding.confirmation_policy === 'confirm';
      });
    });
  }

  private confirmation = false;

  fid(field: RuntimeField): string {
    return `${this.domPrefix()}-${field.name.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
  }

  descIds(field: RuntimeField): string | null {
    const ids: string[] = [];
    if (field.description) ids.push(`${this.fid(field)}-desc`);
    if (field.kind === 'file') ids.push(`${this.fid(field)}-hint`);
    if (field.kind === 'file' && (this.uploading()[field.name] || this.fileNames()[field.name])) {
      ids.push(`${this.fid(field)}-upload`);
    }
    if (this.errors()[field.name]) ids.push(`${this.fid(field)}-err`);
    return ids.length > 0 ? ids.join(' ') : null;
  }

  strVal(name: string): string {
    const value = this.values()[name];
    return value === undefined || value === null ? '' : String(value);
  }

  inputType(field: RuntimeField): string {
    if (field.kind === 'number' || field.kind === 'integer') return 'number';
    if (field.kind === 'date') return 'date';
    return 'text';
  }

  set(name: string, value: unknown): void {
    this.values.update((current) => ({ ...current, [name]: value }));
    if (this.errors()[name]) {
      this.errors.update((current) => {
        const next = { ...current };
        delete next[name];
        return next;
      });
    }
  }

  inputValue(event: Event): string {
    return (event.target as HTMLInputElement | HTMLSelectElement).value;
  }

  checkboxValue(event: Event): boolean {
    return (event.target as HTMLInputElement).checked;
  }

  selectFile(field: RuntimeField, event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file || this.context().mode !== 'live') return;
    this.uploading.update((current) => ({ ...current, [field.name]: true }));
    this.fileNames.update((current) => {
      const next = { ...current };
      delete next[field.name];
      return next;
    });
    const collection = str(this.node(), 'collectionName') || 'documents';
    this.runtime.uploadFile(this.context(), file, collection).subscribe((reference) => {
      this.uploading.update((current) => ({ ...current, [field.name]: false }));
      if (!isReadyFileReference(reference)) {
        this.errors.update((current) => ({ ...current, [field.name]: 'invalid' }));
        return;
      }
      this.set(field.name, reference);
      this.fileNames.update((current) => ({ ...current, [field.name]: reference.filename }));
    });
  }

  submit(): void {
    const next = validateValues(this.fields(), this.values());
    this.errors.set(next);
    if (
      Object.keys(next).length > 0
      || this.resolving()
      || this.blocked()
      || !this.bindingKey()
      || this.context().mode !== 'live'
      || this.hasUpload()
    ) return;
    if (this.confirmation) {
      this.confirming.set(true);
      queueMicrotask(() => this.element.nativeElement.querySelector<HTMLElement>('[data-confirm-accept]')?.focus());
      return;
    }
    this.invoke(false);
  }

  invoke(confirmed: boolean): void {
    this.confirming.set(false);
    if (confirmed) queueMicrotask(() => this.element.nativeElement.querySelector<HTMLElement>('[data-action-trigger]')?.focus());
    const payload = valuesToPayload(this.fields(), this.values());
    const context = this.context();
    this.runtime.invoke(context, this.bindingKey(), payload, confirmed || undefined).subscribe((started) => {
      if (!started?.id) return;
      this.runtime.poll(context, started.id).subscribe((run) => {
        if (run?.status === 'completed') this.applyAfterSuccess();
      });
    });
  }

  retry(): void {
    const context = this.context();
    this.runtime.retry(context).subscribe((started) => {
      if (!started?.id) return;
      this.runtime.poll(context, started.id).subscribe((run) => {
        if (run?.status === 'completed') this.applyAfterSuccess();
      });
    });
  }

  cancelConfirmation(): void {
    this.confirming.set(false);
    queueMicrotask(() => this.element.nativeElement.querySelector<HTMLElement>('[data-action-trigger]')?.focus());
  }

  private domPrefix(): string {
    return `xp-rt-${this.context().stateKey.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
  }

  private applyAfterSuccess(): void {
    const outcome = runtimeAfterSuccess(this.node().props?.['afterSuccess']);
    if (outcome.kind === 'reset') {
      this.values.set(seedFromSchema(this.node().props?.['schema']));
      this.errors.set({});
      this.fileNames.set({});
      return;
    }
    if (outcome.kind === 'page') {
      this.navigateToPage(outcome.pageId);
      return;
    }
    if (outcome.kind !== 'result') return;
    queueMicrotask(() => {
      const result = this.element.nativeElement
        .closest('.xp-rt-page')
        ?.querySelector<HTMLElement>('[data-component-type="result"]');
      result?.scrollIntoView({ block: 'nearest' });
      result?.focus();
    });
  }

  private navigateToPage(pageId: string): void {
    const context = this.context();
    if (context.mode !== 'live' || !context.experienceSlug) return;
    void this.router.navigateByUrl(
      `/work/${encodeURIComponent(context.experienceSlug)}/${encodeURIComponent(pageId)}`,
    );
  }
}

@Component({
  selector: 'xp-rt-action',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './runtime.scss',
  template: `
    <div class="xp-rt-block">
      @if (context().mode === 'preview') {
        <p class="xp-rt-preview-note" role="status">{{ i18n.t('experience.runtime.preview.read_only') }}</p>
      }
      @if (confirming()) {
        <div
          class="xp-rt-confirm"
          role="group"
          [attr.aria-labelledby]="confirmTitleId()"
          (keydown.escape)="cancelConfirmation()"
        >
          <h3 [id]="confirmTitleId()">{{ i18n.t('experience.runtime.form.confirm_title') }}</h3>
          <p class="xp-rt-sub">{{ i18n.t('experience.runtime.form.confirm_body') }}</p>
          <div class="xp-rt-actions">
            <button type="button" class="xp-rt-btn xp-rt-btn-ghost" (click)="cancelConfirmation()">
              {{ i18n.t('common.cancel') }}
            </button>
            <button type="button" class="xp-rt-btn" data-confirm-accept (click)="invoke(true)">
              {{ i18n.t('common.confirm') }}
            </button>
          </div>
        </div>
      } @else {
        <button
          type="button"
          class="xp-rt-btn"
          data-action-trigger
          [disabled]="busy() || resolving() || blocked() || unlinked() || context().mode === 'preview'"
          [attr.aria-label]="ariaName() || null"
          [attr.aria-describedby]="unlinked() ? noLinkHintId() : null"
          (click)="onClick()"
        >
          {{ label() }}
        </button>
        @if (unlinked()) {
          <p class="xp-rt-hint" [id]="noLinkHintId()">{{ i18n.t('experience.runtime.action.no_link') }}</p>
        }
      }
    </div>
  `,
})
export class ActionButtonBlock {
  private readonly runtime = inject(ExperienceRuntimeService);
  private readonly element: ElementRef<HTMLElement> = inject(ElementRef);
  private readonly router = inject(Router);
  readonly i18n = inject(I18nService);
  readonly node = input.required<ExperienceNode>();
  readonly context = input.required<RuntimeNodeContext>();
  readonly confirming = signal(false);
  readonly resolveStatus = signal<string | null>(null);
  private confirmation = false;

  readonly label = computed(
    () => str(this.node(), 'label') || this.i18n.t('experience.runtime.form.submit'),
  );
  readonly ariaName = computed(() => a11yOf(this.node()).ariaLabel);
  readonly bindingKey = computed(() => str(this.node(), 'bindingKey'));
  readonly unlinked = computed(() => !this.bindingKey());
  readonly noLinkHintId = computed(() => `${this.domPrefix()}-no-link`);
  readonly confirmTitleId = computed(() => `${this.domPrefix()}-confirm-title`);
  readonly busy = computed(
    () => {
      const phase = this.runtime.phase(this.context().stateKey);
      return phase === 'loading' || phase === 'running';
    },
  );
  readonly blocked = computed(() => {
    const status = this.resolveStatus();
    return !!status && status !== 'ok' && status !== 'loading';
  });
  readonly resolving = computed(() => this.resolveStatus() === 'loading');

  constructor() {
    effect(() => {
      const key = this.bindingKey();
      const context = this.context();
      if (!key || context.mode !== 'live') {
        this.resolveStatus.set(null);
        return;
      }
      this.resolveStatus.set('loading');
      this.runtime.resolve(context, key).pipe(take(1)).subscribe((resolved) => {
        if (!resolved) {
          this.resolveStatus.set('unavailable');
          return;
        }
        this.resolveStatus.set(resolved.status);
        this.confirmation = resolved.binding.confirmation_policy === 'confirm';
      });
    });
  }

  onClick(): void {
    if (this.resolving() || this.blocked() || !this.bindingKey() || this.context().mode !== 'live') return;
    if (this.confirmation) {
      this.confirming.set(true);
      queueMicrotask(() => this.element.nativeElement.querySelector<HTMLElement>('[data-confirm-accept]')?.focus());
      return;
    }
    this.invoke(false);
  }

  invoke(confirmed: boolean): void {
    this.confirming.set(false);
    if (confirmed) queueMicrotask(() => this.element.nativeElement.querySelector<HTMLElement>('[data-action-trigger]')?.focus());
    const input = this.node().props?.['input'];
    const payload = isRecord(input) ? input : {};
    const context = this.context();
    this.runtime.invoke(context, this.bindingKey(), payload, confirmed || undefined).subscribe((started) => {
      if (!started?.id) return;
      this.runtime.poll(context, started.id).subscribe((run) => {
        if (run?.status === 'completed') this.applyAfterSuccess();
      });
    });
  }

  cancelConfirmation(): void {
    this.confirming.set(false);
    queueMicrotask(() => this.element.nativeElement.querySelector<HTMLElement>('[data-action-trigger]')?.focus());
  }

  private domPrefix(): string {
    return `xp-rt-${this.context().stateKey.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
  }

  private applyAfterSuccess(): void {
    const outcome = runtimeAfterSuccess(this.node().props?.['afterSuccess']);
    if (outcome.kind === 'page') {
      const context = this.context();
      if (context.mode === 'live' && context.experienceSlug) {
        void this.router.navigateByUrl(
          `/work/${encodeURIComponent(context.experienceSlug)}/${encodeURIComponent(outcome.pageId)}`,
        );
      }
      return;
    }
    if (outcome.kind !== 'result') return;
    queueMicrotask(() => {
      const result = this.element.nativeElement
        .closest('.xp-rt-page')
        ?.querySelector<HTMLElement>('[data-component-type="result"]');
      result?.scrollIntoView({ block: 'nearest' });
      result?.focus();
    });
  }
}

@Component({
  selector: 'xp-rt-feed',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RuntimeSlotComponent, RuntimeQueryControlComponent, TagComponent, RouterLink],
  styleUrl: './runtime.scss',
  template: `
    <section class="xp-rt-block" [attr.aria-label]="ariaName() || title()">
      <div class="xp-rt-row">
        <h3>{{ title() }}</h3>
      </div>
      @if (description()) {
        <p class="xp-rt-sub">{{ description() }}</p>
      }
      <xp-rt-query-control [node]="node()" [context]="context()" />
      <xp-rt-slot [state]="slot()" [empty]="emptyText()" [detail]="errorText()">
        <ul class="xp-rt-list">
          @for (item of items(); track $index) {
            <li>
              <span>{{ item.title }}</span>
              @if (item.when) {
                <span>{{ item.when }}</span>
              }
              @if (item.tone) {
                <ck-tag [tone]="item.tone">{{ item.tone }}</ck-tag>
              }
              @if (item.detail) {
                <span class="xp-rt-sub">{{ item.detail }}</span>
              }
            </li>
          }
        </ul>
      </xp-rt-slot>
      @if (href()) {
        <a class="xp-rt-link" [routerLink]="href()">{{ href() }}</a>
      }
    </section>
  `,
})
export class FeedBlock {
  private readonly runtime = inject(ExperienceRuntimeService);
  readonly i18n = inject(I18nService);
  readonly node = input.required<ExperienceNode>();
  readonly context = input.required<RuntimeNodeContext>();
  readonly title = computed(() => {
    const custom = appearanceOf(this.node()).title;
    if (custom) return custom;
    switch (this.node().type) {
      case 'map_panel':
        return this.i18n.t('experience.runtime.map_panel.title');
      case 'agenda_panel':
        return this.i18n.t('experience.runtime.agenda_panel.title');
      case 'intelligence_feed':
        return this.i18n.t('experience.runtime.intelligence_feed.title');
      case 'decision_queue':
        return this.i18n.t('experience.runtime.decision_queue.title');
      default:
        return this.node().id || '';
    }
  });
  readonly description = computed(() => appearanceOf(this.node()).description);
  readonly ariaName = computed(() => a11yOf(this.node()).ariaLabel);
  readonly emptyText = computed(() => a11yOf(this.node()).emptyText);
  readonly href = computed(() => {
    const value = this.node().props?.['href'];
    if (typeof value !== 'string') return null;
    const trimmed = value.trim();
    if (!trimmed.startsWith('/') || trimmed.startsWith('//') || trimmed.includes('\\')) return null;
    return trimmed;
  });
  readonly items = computed(() =>
    runtimeItems(
      runtimeDataBinding(this.node())
        ? dynamicValue(this.runtime, this.node(), this.context())
        : this.node().props?.['items'],
    ).map((item) => {
      if (typeof item === 'string') return { title: item, detail: '', when: '', tone: '' as CkTagTone | '' };
      if (!isRecord(item)) return { title: String(item), detail: '', when: '', tone: '' as CkTagTone | '' };
      const toneRaw = typeof item['tone'] === 'string' ? item['tone'].toLowerCase() : '';
      const tone: CkTagTone | '' =
        toneRaw === 'pos' || toneRaw === 'ok' || toneRaw === 'good'
          ? 'pos'
          : toneRaw === 'neg' || toneRaw === 'danger' || toneRaw === 'critical'
            ? 'neg'
            : toneRaw === 'warn' || toneRaw === 'watch'
              ? 'warn'
              : toneRaw === 'cool' || toneRaw === 'info'
                ? 'cool'
                : toneRaw === 'violet'
                  ? 'violet'
                  : toneRaw === 'neutral'
                    ? 'neutral'
                    : '';
      return {
        title:
          typeof item['title'] === 'string'
            ? item['title']
            : typeof item['label'] === 'string'
              ? item['label']
              : itemLabel(item),
        detail:
          typeof item['detail'] === 'string'
            ? item['detail']
            : typeof item['source'] === 'string'
              ? item['source']
              : typeof item['body'] === 'string'
                ? item['body']
                : '',
        when: typeof item['when'] === 'string' ? item['when'] : '',
        tone,
      };
    }),
  );
  readonly slot = computed(() =>
    dynamicSlot(this.runtime, this.node(), this.context(), this.items().length === 0),
  );
  readonly errorText = computed(() => this.runtime.lastError(this.context().sourceStateKey) ?? '');
}

/** Cycled: a donut with more slices than colours reuses them in order. */
const SLICE_TOKENS: readonly (readonly [string, string])[] = [
  ['--ck-accent', '#7dd3fc'],
  ['--ck-signal-violet', '#a78bfa'],
  ['--ck-signal-pos', '#34d399'],
  ['--ck-signal-warn', '#f5b84a'],
  ['--ck-signal-neg', '#ef5a6f'],
  ['--ck-signal-ice', '#e0f2fe'],
];

/**
 * Interpolated, not cycled: the anchors of the `severity` ramp.
 *
 * Three stops rather than a colour per band, because the number of bands is
 * the run's to decide. Green, amber and red are the only sequence a reader
 * does not have to be given a legend for.
 */
const SEVERITY_TOKENS: readonly (readonly [string, string])[] = [
  ['--ck-signal-pos', '#34d399'],
  ['--ck-signal-warn', '#f5b84a'],
  ['--ck-signal-neg', '#ef5a6f'],
];

/** One bar, with everything the template needs already decided. */
interface ChartBar {
  label: string;
  display: string;
  /** Rendered as-is; empty when the series is not a whole to take a share of. */
  share: string;
  /** 0–100, relative to the largest magnitude plotted. */
  width: number;
  negative: boolean;
  color: string;
}

export const CATALOG: Record<CertifiedType, Type<unknown>> = {
  section: SectionBlock,
  header: HeaderBlock,
  form: FormBlock,
  action_button: ActionButtonBlock,
  result: ResultBlock,
  table: TableBlock,
  queue: QueueBlock,
  approval_card: ApprovalCardBlock,
  runtime_status: RuntimeStatusBlock,
  evidence: EvidenceBlock,
  history: HistoryBlock,
  kpi: KpiBlock,
  chart: ChartBlock,
  callout: CalloutBlock,
  map_panel: FeedBlock,
  agenda_panel: FeedBlock,
  intelligence_feed: FeedBlock,
  decision_queue: FeedBlock,
};
