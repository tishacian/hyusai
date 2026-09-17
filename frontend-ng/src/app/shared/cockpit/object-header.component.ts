import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

export type CkObjectKpiTone =
  | 'neutral'
  | 'pos'
  | 'neg'
  | 'cool'
  | 'violet'
  | 'warn';

export interface CkObjectKpi {
  label: string;
  value: string;
  hint?: string;
  tone?: CkObjectKpiTone;
}

/**
 * `<ck-object-header>` — the persistent identity card for a zoomed object.
 *
 * Sits above the tab strip and **never re-renders when the user switches
 * tabs**. That invariance is the whole point: it proves the user is still
 * on the same object, no matter which facet they are viewing. See
 * docs/mental-model.md §5bis.5 (object invariance) for the contract.
 *
 * Composition:
 *   - `eyebrow`      small ALL-CAPS mono label (breadcrumb tail / type).
 *   - `title`        object name.
 *   - `subtitle`     one-line description.
 *   - `kpis`         up to 4–5 KPI pills (ROI, Cost, Yield…).
 *   - `[status]`     slot for a status badge.
 *   - `[actions]`    slot for primary action buttons.
 */
@Component({
  selector: 'ck-object-header',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header
      [style.display]="'flex'"
      [style.flexDirection]="'column'"
      [style.gap.px]="10"
      [style.padding]="'16px 20px'"
      [style.background]="'linear-gradient(180deg, rgba(125,211,252,0.04) 0%, transparent 100%), color-mix(in srgb, var(--ck-bg-base, #0b0f14) 94%, transparent)'"
      [style.border]="'1px solid var(--ck-stroke-2, rgba(255,255,255,0.06))'"
      [style.borderRadius.px]="8"
      [style.marginBottom.px]="12"
      [style.top.px]="0"
      [style.zIndex]="5"
      [style.backdropFilter]="'blur(6px)'"
    >
      <div
        [style.display]="'flex'"
        [style.alignItems]="'flex-start'"
        [style.justifyContent]="'space-between'"
        [style.gap.px]="16"
        [style.flexWrap]="'wrap'"
      >
        <div [style.minWidth]="'280px'" [style.flex]="'1 1 360px'">
          @if (eyebrow) {
            <div
              class="ck-mono"
              [style.fontSize.px]="10"
              [style.letterSpacing]="'0.14em'"
              [style.textTransform]="'uppercase'"
              [style.color]="'var(--ck-fg-4)'"
              [style.marginBottom.px]="4"
            >
              {{ eyebrow }}
            </div>
          }
          <div
            [style.display]="'flex'"
            [style.alignItems]="'center'"
            [style.gap.px]="10"
            [style.flexWrap]="'wrap'"
          >
            <h1
              [style.fontSize.px]="20"
              [style.fontWeight]="600"
              [style.margin]="'0'"
              [style.color]="'var(--ck-fg-1, #e7eef7)'"
              [style.letterSpacing]="'-0.01em'"
            >
              {{ title }}
            </h1>
            <ng-content select="[status]" />
          </div>
          @if (subtitle) {
            <div
              [style.fontSize.px]="13"
              [style.color]="'var(--ck-fg-3, #8793a4)'"
              [style.marginTop.px]="4"
              [style.maxWidth]="'720px'"
            >
              {{ subtitle }}
            </div>
          }
        </div>
        <div
          [style.display]="'inline-flex'"
          [style.alignItems]="'center'"
          [style.gap.px]="8"
          [style.flex]="'1 1 360px'"
          [style.flexWrap]="'wrap'"
          [style.justifyContent]="'flex-end'"
        >
          <ng-content select="[actions]" />
        </div>
      </div>
      @if (kpis && kpis.length > 0) {
        <div
          [style.display]="'flex'"
          [style.alignItems]="'stretch'"
          [style.gap.px]="16"
          [style.flexWrap]="'wrap'"
          [style.paddingTop.px]="6"
          [style.borderTop]="'1px dashed var(--ck-stroke-2, rgba(255,255,255,0.05))'"
        >
          @for (k of kpis; track k.label) {
            <div
              [style.display]="'flex'"
              [style.flexDirection]="'column'"
              [style.gap.px]="2"
              [style.minWidth]="'80px'"
              [title]="k.hint || k.label"
            >
              <div
                class="ck-mono"
                [style.fontSize.px]="9"
                [style.letterSpacing]="'0.14em'"
                [style.textTransform]="'uppercase'"
                [style.color]="'var(--ck-fg-4)'"
              >
                {{ k.label }}
              </div>
              <div
                [style.fontSize.px]="18"
                [style.fontWeight]="600"
                [style.fontVariantNumeric]="'tabular-nums'"
                [style.color]="toneColor(k.tone)"
              >
                {{ k.value }}
              </div>
            </div>
          }
        </div>
      }
    </header>
  `,
  styles: [`
    header { position: sticky; }
    /* Wrapped identity/actions must not cover the object being inspected. */
    @media (max-width: 767px), (max-height: 600px) {
      header { position: static; }
    }
  `],
})
export class CkObjectHeaderComponent {
  @Input() eyebrow = '';
  @Input({ required: true }) title!: string;
  @Input() subtitle = '';
  @Input() kpis: CkObjectKpi[] = [];

  toneColor(tone: CkObjectKpiTone | undefined): string {
    switch (tone) {
      case 'pos':    return 'var(--ck-signal-pos, #34d399)';
      case 'neg':    return 'var(--ck-signal-neg, #ef5a6f)';
      case 'cool':   return 'var(--ck-signal-cool, #7dd3fc)';
      case 'violet': return 'var(--ck-signal-violet, #a78bfa)';
      case 'warn':   return 'var(--ck-signal-warn, #f5b84a)';
      case 'neutral':
      default:       return 'var(--ck-fg-1, #e7eef7)';
    }
  }
}
