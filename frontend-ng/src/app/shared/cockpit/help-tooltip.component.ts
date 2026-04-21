import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  HostListener,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';

import { HelpService, type Persona, type HelpContentIndex } from '@app/core/help.service';

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
  template: `
    <span class="ck-help-root" (click)="$event.stopPropagation()">
      <button
        type="button"
        class="ck-help-button"
        (click)="toggleOpen()"
        [attr.aria-expanded]="open()"
        [attr.aria-label]="'Help about ' + (resolved()?.entry?.title ?? id())"
      >
        ?
      </button>

      @if (open()) {
        <div
          class="ck-help-panel"
          [style.width.px]="width()"
          role="tooltip"
        >
          @if (!resolved()) {
            <div class="ck-help-empty">
              No documentation for
              <code class="ck-help-code">{{ id() }}</code>.
            </div>
          } @else {
            <header class="ck-help-header">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="ck-help-title">{{ resolved()!.entry.title }}</span>
                <span class="ck-help-category">{{ resolved()!.entry.category }}</span>
              </div>
              <div class="ck-help-personas">
                @for (p of personas; track p) {
                  <button
                    type="button"
                    class="ck-help-persona"
                    [class.ck-help-persona-active]="help.persona() === p"
                    (click)="switchPersona(p)"
                  >
                    {{ help.personaLabelOf(p) }}
                  </button>
                }
              </div>
            </header>

            <p class="ck-help-summary">{{ resolved()!.copy.summary }}</p>

            <section class="ck-help-section">
              <span class="ck-help-section-label">USER STORY</span>
              <p class="ck-help-section-body">{{ resolved()!.copy.user_story }}</p>
            </section>

            @if (resolved()!.copy.prerequisites.length) {
              <section class="ck-help-section">
                <span class="ck-help-section-label">PREREQUISITES</span>
                <ul class="ck-help-list">
                  @for (p of resolved()!.copy.prerequisites; track p) {
                    <li>{{ p }}</li>
                  }
                </ul>
              </section>
            }

            @if (resolved()!.copy.related_actions.length) {
              <section class="ck-help-section">
                <span class="ck-help-section-label">RELATED ACTIONS</span>
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
                  Learn more →
                </a>
              </footer>
            }
          }
        </div>
      }
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
        width: 16px;
        height: 16px;
        border-radius: 50%;
        border: 1px solid var(--ck-stroke-soft);
        background: var(--ck-bg-inset);
        color: var(--ck-fg-4);
        font-family: var(--font-mono, ui-monospace, SFMono-Regular);
        font-size: 10px;
        line-height: 14px;
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
        position: absolute;
        top: calc(100% + 8px);
        left: 50%;
        transform: translateX(-50%);
        z-index: 60;
        padding: 14px 16px;
        border-radius: 6px;
        background: var(--ck-bg-raised, #0f1117);
        border: 1px solid var(--ck-stroke, rgba(255,255,255,0.12));
        box-shadow: 0 18px 48px rgba(0,0,0,0.45);
        color: var(--ck-fg-1);
        font-size: 12px;
        line-height: 1.55;
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
  private readonly host = inject(ElementRef<HTMLElement>);

  readonly id = input.required<string>();
  readonly width = input<number>(320);
  readonly personaOverride = input<Persona | null>(null);

  readonly open = signal(false);
  protected readonly personas: Persona[] = ['builder', 'operator', 'executive'];

  private readonly index = toSignal(this.help.load(), { initialValue: null as HelpContentIndex | null });

  readonly resolved = computed(() => {
    const persona = this.personaOverride() ?? this.help.persona();
    return this.help.resolve(this.index(), this.id(), persona);
  });

  toggleOpen(): void {
    this.open.update((v) => !v);
  }

  switchPersona(p: Persona): void {
    this.help.setPersona(p);
  }

  @HostListener('document:click', ['$event'])
  protected onDocumentClick(event: MouseEvent): void {
    if (!this.open()) return;
    if (!this.host.nativeElement.contains(event.target as Node)) {
      this.open.set(false);
    }
  }

  @HostListener('document:keydown.escape')
  protected onEsc(): void {
    if (this.open()) this.open.set(false);
  }
}
