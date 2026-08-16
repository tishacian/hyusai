import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  HostListener,
  computed,
  inject,
  input,
  signal,
  viewChild,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import {
  CdkConnectedOverlay,
  CdkOverlayOrigin,
  type ConnectedPosition,
} from '@angular/cdk/overlay';

import {
  HelpService,
  type HelpContentIndex,
  type Language,
  type LocalizedText,
  type Persona,
} from '@app/core/help.service';
import { I18nService } from '@app/core/i18n.service';

/**
 * `<ck-help [id]="..." />` — persona-aware help affordance.
 *
 * Renders a 12px "?" badge aligned next to any UI surface. On click it
 * opens a compact panel showing the persona-specific copy, with a
 * persona toggle so the same tooltip adapts to `builder`, `operator`
 * and `executive` without duplicating markup.
 *
 * Usage:
 * ```html
 * <span>Balance sheet</span>
 * <ck-help id="hypervisor.balance-sheet.overview" />
 * ```
 */
@Component({
  selector: 'ck-help',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CdkOverlayOrigin, CdkConnectedOverlay],
  template: `
    <span class="ck-help-root" (click)="$event.stopPropagation()">
      <button
        #trigger
        #origin="cdkOverlayOrigin"
        cdkOverlayOrigin
        type="button"
        class="ck-help-button"
        (click)="toggleOpen()"
        [attr.aria-expanded]="open()"
        aria-haspopup="dialog"
        [attr.aria-controls]="panelId()"
        [attr.aria-label]="i18n.t('common.help.about', { name: titleText() || id() })"
      >
        ?
      </button>

      <ng-template
        cdkConnectedOverlay
        [cdkConnectedOverlayOrigin]="origin"
        [cdkConnectedOverlayOpen]="open()"
        [cdkConnectedOverlayPositions]="overlayPositions"
        [cdkConnectedOverlayHasBackdrop]="false"
        [cdkConnectedOverlayViewportMargin]="8"
        [cdkConnectedOverlayPush]="true"
        [cdkConnectedOverlayFlexibleDimensions]="true"
        cdkConnectedOverlayPanelClass="ck-help-overlay-panel"
        (overlayOutsideClick)="onOutsideClick($event)"
        (detach)="close(false)"
      >
        <div
          #panel
          class="ck-help-panel"
          [id]="panelId()"
          [style.width.px]="width()"
          role="dialog"
          [attr.aria-labelledby]="resolved() ? panelTitleId() : null"
          [attr.aria-label]="resolved() ? null : i18n.t('common.help.missing', { name: id() })"
          tabindex="-1"
        >
          @if (!resolved()) {
            <div class="ck-help-empty">
              {{ i18n.t('common.help.missing', { name: id() }) }}
            </div>
          } @else {
            <header class="ck-help-header">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="ck-help-title" [id]="panelTitleId()">{{ titleText() }}</span>
                <span class="ck-help-category">{{ resolved()!.entry.category }}</span>
              </div>
              <div class="flex items-center gap-2 flex-wrap">
                <div class="ck-help-personas">
                  @for (p of personas; track p) {
                    <button
                      type="button"
                      class="ck-help-persona"
                      [class.ck-help-persona-active]="help.persona() === p"
                      [attr.aria-pressed]="help.persona() === p"
                      (click)="switchPersona(p)"
                    >
                      {{ help.personaLabelOf(p) }}
                    </button>
                  }
                </div>
                <div class="ck-help-personas" [attr.aria-label]="i18n.t('common.help.language')">
                  @for (lang of languages; track lang) {
                    <button
                      type="button"
                      class="ck-help-persona"
                      [class.ck-help-persona-active]="help.language() === lang"
                      [attr.aria-pressed]="help.language() === lang"
                      (click)="switchLanguage(lang)"
                      [attr.aria-label]="i18n.t('common.help.switch_language', { name: help.languageLabelOf(lang) })"
                    >
                      {{ help.languageLabelOf(lang) }}
                    </button>
                  }
                </div>
              </div>
            </header>

            <p class="ck-help-summary">{{ pick(resolved()!.copy.summary) }}</p>

            @if (pick(resolved()!.copy.user_story)) {
              <section class="ck-help-section">
                <span class="ck-help-section-label">{{ labels().userStory }}</span>
                <p class="ck-help-section-body">{{ pick(resolved()!.copy.user_story) }}</p>
              </section>
            }

            @if (resolved()!.copy.prerequisites.length) {
              <section class="ck-help-section">
                <span class="ck-help-section-label">{{ labels().prerequisites }}</span>
                <ul class="ck-help-list">
                  @for (p of resolved()!.copy.prerequisites; track $index) {
                    <li>{{ pick(p) }}</li>
                  }
                </ul>
              </section>
            }

            @if (resolved()!.copy.related_actions.length) {
              <section class="ck-help-section">
                <span class="ck-help-section-label">{{ relatedLabel() }}</span>
                <ul class="ck-help-list">
                  @for (a of resolved()!.copy.related_actions; track a) {
                    <li><code class="ck-help-code">{{ a }}</code></li>
                  }
                </ul>
              </section>
            }

            @if (resolved()!.entry.learn_more) {
              <footer class="ck-help-footer">
                <a
                  class="ck-help-learn"
                  [href]="resolved()!.entry.learn_more"
                  target="_blank"
                  rel="noreferrer noopener"
                >
                  {{ labels().learnMore }} →
                </a>
              </footer>
            }
          }
        </div>
      </ng-template>
    </span>
  `,
  styles: [
    `
      :host { display: inline-flex; }
      .ck-help-root {
        position: relative;
        display: inline-flex;
        align-items: center;
      }
      .ck-help-button {
        width: 24px;
        height: 24px;
        border-radius: 50%;
        border: 1px solid var(--ck-stroke-soft);
        background: var(--ck-bg-inset);
        color: var(--ck-fg-4);
        font-family: var(--font-mono, ui-monospace, SFMono-Regular);
        font-size: 10px;
        line-height: 1;
        padding: 0;
        cursor: help;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        transition: color 120ms ease, border-color 120ms ease, background 120ms ease;
      }
      .ck-help-button:hover {
        color: var(--ck-fg-1);
        border-color: var(--ck-stroke);
        background: var(--ck-bg-raised);
      }
      .ck-help-panel {
        padding: 14px 16px;
        border-radius: 6px;
        background: var(--ck-bg-raised, #0f1117);
        border: 1px solid var(--ck-stroke, rgba(255,255,255,0.12));
        box-shadow: var(--ck-shadow-popover);
        color: var(--ck-fg-1);
        font-size: 12px;
        line-height: 1.55;
        max-height: min(70vh, 640px);
        max-width: calc(100vw - 16px);
        overflow-y: auto;
        overscroll-behavior: contain;
      }
      .ck-help-header {
        display: flex;
        flex-direction: column;
        gap: 8px;
        margin-bottom: 10px;
      }
      .ck-help-title {
        font-family: var(--font-mono);
        font-size: 11px;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        color: var(--ck-fg-1);
      }
      .ck-help-category {
        font-family: var(--font-mono);
        font-size: 9px;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        color: var(--ck-fg-4);
        padding: 2px 6px;
        border-radius: 3px;
        border: 1px solid var(--ck-stroke-soft);
      }
      .ck-help-personas {
        display: flex;
        gap: 4px;
        padding: 3px;
        border-radius: 4px;
        background: var(--ck-bg-inset);
        width: fit-content;
      }
      .ck-help-persona {
        font-family: var(--font-mono);
        font-size: 9px;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        padding: 3px 8px;
        border-radius: 3px;
        color: var(--ck-fg-4);
        background: transparent;
        border: none;
        cursor: pointer;
      }
      .ck-help-persona-active {
        background: var(--ck-bg-raised);
        color: var(--ck-fg-1);
      }
      .ck-help-summary {
        color: var(--ck-fg-2);
        margin-bottom: 10px;
      }
      .ck-help-section {
        display: flex;
        flex-direction: column;
        gap: 4px;
        margin-bottom: 8px;
      }
      .ck-help-section-label {
        font-family: var(--font-mono);
        font-size: 9px;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        color: var(--ck-fg-4);
      }
      .ck-help-section-body {
        color: var(--ck-fg-2);
      }
      .ck-help-list {
        list-style: disc;
        padding-left: 16px;
        color: var(--ck-fg-2);
        margin: 0;
      }
      .ck-help-code {
        font-family: var(--font-mono);
        font-size: 10px;
        color: var(--ck-fg-1);
        background: var(--ck-bg-inset);
        padding: 1px 4px;
        border-radius: 3px;
      }
      .ck-help-footer { margin-top: 6px; }
      .ck-help-learn {
        font-family: var(--font-mono);
        font-size: 10px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: var(--ck-signal-cool, #38bdf8);
      }
      .ck-help-empty {
        color: var(--ck-fg-4);
        font-size: 11px;
      }
    `,
  ],
})
export class HelpTooltipComponent {
  readonly help = inject(HelpService);
  /** UI-locale chrome only (aria labels); panel copy follows `help.language()`. */
  readonly i18n = inject(I18nService);
  private readonly host: ElementRef<HTMLElement> = inject(ElementRef);
  private readonly trigger = viewChild<ElementRef<HTMLButtonElement>>('trigger');
  private readonly panel = viewChild<ElementRef<HTMLElement>>('panel');

  readonly id = input.required<string>();
  readonly width = input<number>(320);
  readonly personaOverride = input<Persona | null>(null);

  readonly open = signal(false);
  readonly panelId = computed(() => `ck-help-${this.id().replace(/[^A-Za-z0-9_-]/g, '-')}`);
  readonly panelTitleId = computed(() => `${this.panelId()}-title`);
  protected readonly personas: Persona[] = ['builder', 'operator', 'executive'];
  protected readonly languages: Language[] = ['en', 'fr'];

  /**
   * Flexible connected positions for the overlay. The first that fits the
   * viewport wins; CDK auto-flips to the fallbacks so the tooltip is always
   * entirely visible (bottom → top → right → left).
   */
  protected readonly overlayPositions: ConnectedPosition[] = [
    { originX: 'center', originY: 'bottom', overlayX: 'center', overlayY: 'top', offsetY: 8 },
    { originX: 'center', originY: 'top', overlayX: 'center', overlayY: 'bottom', offsetY: -8 },
    { originX: 'end', originY: 'center', overlayX: 'start', overlayY: 'center', offsetX: 8 },
    { originX: 'start', originY: 'center', overlayX: 'end', overlayY: 'center', offsetX: -8 },
    { originX: 'start', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetY: 8 },
    { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 8 },
  ];

  private readonly index = toSignal(this.help.load(), { initialValue: null as HelpContentIndex | null });

  readonly resolved = computed(() => {
    const persona = this.personaOverride() ?? this.help.persona();
    return this.help.resolve(this.index(), this.id(), persona);
  });

  readonly titleText = computed(() => {
    const r = this.resolved();
    return r ? this.help.pickText(r.entry.title) : '';
  });

  readonly labels = computed(() => {
    switch (this.help.language()) {
      case 'fr':
        return {
          userStory: 'USER STORY',
          prerequisites: 'PRÉREQUIS',
          relatedActions: 'ACTIONS LIÉES',
          technicalDetail: 'TERME TECHNIQUE',
          learnMore: 'En savoir plus',
        };
      case 'en':
      default:
        return {
          userStory: 'USER STORY',
          prerequisites: 'PREREQUISITES',
          relatedActions: 'RELATED ACTIONS',
          technicalDetail: 'TECHNICAL TERM',
          learnMore: 'Learn more',
        };
    }
  });

  /**
   * Lexicon-backed concepts list the internal terms the label replaces, not
   * actions — the technical register of the two-register rule.
   */
  readonly relatedLabel = computed(() =>
    this.resolved()?.entry.category === 'concept'
      ? this.labels().technicalDetail
      : this.labels().relatedActions,
  );

  pick(text: LocalizedText | null | undefined): string {
    return this.help.pickText(text);
  }

  toggleOpen(): void {
    if (this.open()) {
      this.close(true);
      return;
    }
    this.open.set(true);
    queueMicrotask(() => {
      const panel = this.panel()?.nativeElement;
      (panel?.querySelector<HTMLElement>('button, a[href]') ?? panel)?.focus();
    });
  }

  close(restoreFocus: boolean): void {
    if (!this.open()) return;
    this.open.set(false);
    if (restoreFocus) queueMicrotask(() => this.trigger()?.nativeElement.focus());
  }

  switchPersona(p: Persona): void {
    this.help.setPersona(p);
  }

  switchLanguage(lang: Language): void {
    this.help.setLanguage(lang);
  }

  protected onOutsideClick(event: MouseEvent): void {
    if (!this.open()) return;
    if (!this.host.nativeElement.contains(event.target as Node)) {
      this.close(false);
    }
  }

  @HostListener('document:keydown.escape')
  protected onEsc(): void {
    this.close(true);
  }
}
