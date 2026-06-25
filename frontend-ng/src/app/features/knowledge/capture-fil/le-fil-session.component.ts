import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  EventEmitter,
  Output,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { GlyphComponent, LiveDotComponent } from '@app/shared/cockpit';
import { CaptureEngine } from './capture-engine';
import { LaSceneComponent } from './la-scene.component';
import { AnchorChipComponent } from './anchor-chip.component';
import { clockLabel } from './capture-presentation';

/**
 * Le Fil (Phase 2 / D3) — the live capture session. A single horodated event
 * timeline (`speak | note | anchor`) with auto-scroll, two append-only channels
 * (voice transcript is never overwritten by typed notes), a single-modality
 * composer (Enter inserts, Shift+Enter newlines, mic VU captured continuously),
 * La Scène, and the calm Oracle list. Composes {@link LaSceneComponent} and
 * {@link AnchorChipComponent}; binds the {@link CaptureEngine} contract.
 */
@Component({
  selector: 'app-le-fil-session',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [GlyphComponent, LiveDotComponent, LaSceneComponent, AnchorChipComponent],
  template: `
    <div style="display:flex; flex-direction:column; gap:0; border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-lg); overflow:hidden; background:var(--ck-bg-base);">
      <!-- status bar -->
      <div
        style="flex:none; display:flex; align-items:center; gap:14px; padding:10px 16px; border-bottom:1px solid var(--ck-stroke-2); background:var(--ck-bg-panel); flex-wrap:wrap;"
      >
        <ck-live-dot [tone]="connected() ? 'neg' : 'neutral'" label="" />
        <span
          class="ck-mono"
          style="font-size:11px; font-weight:700; letter-spacing:0.08em;"
          [style.color]="connected() ? 'var(--ck-signal-neg)' : 'var(--ck-fg-4)'"
        >
          {{ connected() ? 'CAPTURE' : connectionLabel() }}
        </span>
        <span style="width:1px; height:18px; background:var(--ck-stroke-2);"></span>
        <span style="font-size:13px; color:var(--ck-fg-1); font-weight:600;">{{ title() }}</span>
        <span class="ck-mono ck-tnum" style="font-size:12px; color:var(--ck-fg-3);">{{ clock() }}</span>

        <div style="margin-left:auto; display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
          <span
            class="ck-mono"
            style="font-size:10px; color:var(--ck-fg-4); padding:3px 8px; border:1px solid var(--ck-stroke-2); border-radius:999px;"
          >
            pointage · hybride
          </span>
          <span class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">{{ refsCount() }} réf.</span>
          <button
            type="button"
            class="ck-mono"
            (click)="toggleMuteWhileTyping()"
            [title]="muteWhileTyping() ? 'Le micro est coupé pendant la frappe' : 'Le micro reste ouvert pendant la frappe'"
            style="display:inline-flex; align-items:center; gap:5px; font-size:10px; padding:3px 8px; border-radius:999px; cursor:pointer; background:transparent;"
            [style.border]="'1px solid ' + (muteWhileTyping() ? 'var(--ck-signal-warn)' : 'var(--ck-stroke-2)')"
            [style.color]="muteWhileTyping() ? 'var(--ck-signal-warn)' : 'var(--ck-fg-4)'"
          >
            <ck-glyph name="pulse" [size]="11" color="currentColor" />
            {{ muteWhileTyping() ? 'micro coupé à la frappe' : 'micro continu' }}
          </button>
          <button
            type="button"
            (click)="finish.emit()"
            style="display:inline-flex; align-items:center; gap:6px; padding:7px 13px; border-radius:var(--ck-radius-md); border:none; cursor:pointer; font-weight:550; font-size:12.5px; background:color-mix(in oklab, var(--ck-signal-cool) 88%, transparent); color:var(--ck-on-signal);"
          >
            <ck-glyph name="arrow-right" [size]="13" color="currentColor" /> Terminer la capture
          </button>
        </div>
      </div>

      @if (lastError()) {
        <div
          style="flex:none; padding:7px 16px; background:color-mix(in oklab, var(--ck-signal-warn) 12%, var(--ck-bg-panel)); border-bottom:1px solid color-mix(in oklab, var(--ck-signal-warn) 30%, transparent); display:flex; align-items:center; gap:8px;"
        >
          <ck-glyph name="warn" [size]="13" color="var(--ck-signal-warn)" />
          <span style="font-size:12px; color:var(--ck-fg-2);">{{ lastError() }}</span>
        </div>
      }

      <!-- body -->
      <div style="display:grid; grid-template-columns:48px minmax(0,1fr) 360px; min-height:60vh;">
        <!-- spine -->
        <div
          style="border-right:1px solid var(--ck-stroke-2); background:var(--ck-bg-panel); display:flex; flex-direction:column; align-items:center; padding-top:16px; gap:8px;"
        >
          <ck-glyph name="pulse" [size]="16" color="var(--ck-signal-cool)" />
          <div class="lf-vu" [class.lf-vu-on]="micActive()">
            @for (b of bars; track b) {
              <span [style.animationDelay.s]="b * 0.12"></span>
            }
          </div>
          <div style="flex:1; width:1px; background:var(--ck-stroke-2); margin-top:8px;"></div>
          <span
            class="ck-mono"
            style="writing-mode:vertical-rl; font-size:8.5px; letter-spacing:0.18em; color:var(--ck-fg-5); text-transform:uppercase; padding:8px 0;"
          >
            le fil
          </span>
        </div>

        <!-- Le Fil + composer -->
        <div style="display:flex; flex-direction:column; min-height:0; min-width:0;">
          <div
            #feed
            class="ck-scroll"
            style="flex:1; overflow-y:auto; padding:24px 28px; display:flex; flex-direction:column; gap:16px; min-height:0;"
          >
            @if (engine.feed().length === 0) {
              <div style="color:var(--ck-fg-4); font-size:13px; font-style:italic; margin-top:12px;">
                En écoute… la parole et l'écrit s'inscrivent ici, sur un seul fil horodaté.
              </div>
            }
            @for (item of engine.feed(); track item.id) {
              <div style="display:flex; gap:14px;">
                <span
                  class="ck-mono ck-tnum"
                  style="flex:none; width:56px; padding-top:4px; font-size:10px; color:var(--ck-fg-5);"
                >
                  {{ stamp(item.ts_ms) }}
                </span>
                @switch (item.kind) {
                  @case ('speak') {
                    <p
                      style="margin:0; font-size:17px; line-height:1.62; text-wrap:pretty;"
                      [style.color]="item.partial ? 'var(--ck-fg-3)' : 'var(--ck-fg-1)'"
                      [style.fontStyle]="item.partial ? 'italic' : 'normal'"
                    >
                      {{ item.text }}@if (item.partial) {<span class="lf-cursor"></span>}
                    </p>
                  }
                  @case ('note') {
                    <div
                      style="display:flex; gap:9px; align-items:flex-start; padding:8px 12px; background:var(--ck-tint-faint); border-radius:0 var(--ck-radius-sm) var(--ck-radius-sm) 0; max-width:560px;"
                      [style.borderLeft]="'2px solid ' + (item.speaker === 'system' ? 'var(--ck-signal-violet)' : 'var(--ck-signal-cool)')"
                    >
                      <ck-glyph
                        name="ledger"
                        [size]="14"
                        [color]="item.speaker === 'system' ? 'var(--ck-signal-violet)' : 'var(--ck-signal-cool)'"
                      />
                      <span style="font-size:15px; line-height:1.5; color:var(--ck-fg-2);">{{ item.text }}</span>
                    </div>
                  }
                  @case ('anchor') {
                    <app-anchor-chip [view]="item.view" />
                  }
                }
              </div>
            }
          </div>

          <!-- composer -->
          <div style="flex:none; padding:14px 28px 16px; border-top:1px solid var(--ck-stroke-2); background:var(--ck-bg-panel);">
            <div
              style="display:flex; align-items:flex-end; gap:12px; border:1px solid var(--ck-stroke-3); border-radius:var(--ck-radius-lg); background:var(--ck-bg-inset); padding:10px 12px;"
            >
              <div style="display:flex; align-items:center; gap:7px; padding-bottom:2px;">
                <ck-glyph name="pulse" [size]="16" [color]="micActive() ? 'var(--ck-signal-cool)' : 'var(--ck-fg-4)'" />
                <div class="lf-vu" [class.lf-vu-on]="micActive()">
                  @for (b of bars; track b) {
                    <span [style.animationDelay.s]="b * 0.12"></span>
                  }
                </div>
              </div>
              <span style="width:1px; height:22px; background:var(--ck-stroke-2);"></span>
              <textarea
                #composer
                rows="1"
                [value]="draft()"
                (input)="onDraft($event)"
                (keydown)="onKeydown($event)"
                (focus)="typing.set(true)"
                (blur)="typing.set(false)"
                placeholder="Écrire une note — s'insère dans le Fil  ·  la voix est captée en continu"
                style="flex:1; resize:none; border:none; outline:none; background:transparent; color:var(--ck-fg-1); font-family:var(--ck-font-sans); font-size:14px; line-height:1.5; max-height:120px;"
              ></textarea>
              <button
                type="button"
                (click)="submit()"
                [disabled]="!draft().trim()"
                style="display:inline-flex; align-items:center; gap:6px; padding:6px 12px; border-radius:var(--ck-radius-md); border:1px solid var(--ck-stroke-2); cursor:pointer; font-size:12px; font-weight:550; white-space:nowrap;"
                [style.background]="draft().trim() ? 'color-mix(in oklab, var(--ck-signal-cool) 88%, transparent)' : 'transparent'"
                [style.color]="draft().trim() ? 'var(--ck-on-signal)' : 'var(--ck-fg-4)'"
                [style.cursor]="draft().trim() ? 'pointer' : 'not-allowed'"
              >
                <ck-glyph name="ledger" [size]="12" color="currentColor" /> Insérer
              </button>
            </div>
            <div style="display:flex; gap:16px; margin-top:7px; padding-left:4px; flex-wrap:wrap;">
              <span class="ck-mono" style="font-size:9.5px; color:var(--ck-fg-5);">↵ insérer</span>
              <span class="ck-mono" style="font-size:9.5px; color:var(--ck-fg-5);">⇧↵ nouvelle ligne</span>
              <span class="ck-mono" style="font-size:9.5px; color:var(--ck-fg-5);">voix ⇄ écrit : même flux</span>
            </div>
          </div>
        </div>

        <!-- La Scène + Oracle -->
        <div
          style="border-left:1px solid var(--ck-stroke-2); background:var(--ck-bg-panel); display:flex; flex-direction:column; min-height:0; padding:14px; gap:14px;"
        >
          <app-la-scene />

          <div style="display:flex; flex-direction:column; min-height:0; gap:10px;">
            <div style="display:flex; align-items:center; gap:8px;">
              <ck-glyph name="bolt" [size]="13" color="var(--ck-signal-violet)" />
              <span class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">
                Pistes de l'oracle
              </span>
              <span class="ck-mono" style="margin-left:auto; font-size:9px; color:var(--ck-fg-5);">non bloquant</span>
            </div>
            <div class="ck-scroll" style="display:flex; flex-direction:column; gap:8px; overflow-y:auto; max-height:280px;">
              @if (openOracle().length === 0) {
                <span style="color:var(--ck-fg-5); font-size:12px; font-style:italic;">
                  L'oracle écoute… il déposera ici des questions d'approfondissement.
                </span>
              }
              @for (q of openOracle(); track q.id) {
                <div
                  style="padding:10px 11px; border-radius:var(--ck-radius-md); display:flex; flex-direction:column; gap:7px;"
                  [style.border]="'1px solid ' + (q.status === 'answered' ? 'color-mix(in oklab, var(--ck-signal-violet) 50%, transparent)' : 'var(--ck-stroke-2)')"
                  [style.background]="q.status === 'answered' ? 'color-mix(in oklab, var(--ck-signal-violet) 9%, transparent)' : 'var(--ck-bg-inset)'"
                >
                  <div style="display:flex; align-items:center; gap:6px;">
                    <ck-glyph name="bolt" [size]="12" color="var(--ck-signal-violet)" />
                    <span class="ck-mono" style="font-size:8.5px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-signal-violet);">
                      Oracle
                    </span>
                    <span class="ck-mono" style="margin-left:auto; font-size:9px; color:var(--ck-fg-5);">{{ stamp(q.ts_ms) }}</span>
                  </div>
                  <p style="margin:0; font-size:12.5px; line-height:1.45; color:var(--ck-fg-2);">{{ q.text }}</p>
                  <div style="display:flex; gap:6px;">
                    <button
                      type="button"
                      class="lf-chip"
                      (click)="engine.setOracleStatus(q.id, q.status === 'answered' ? 'open' : 'answered')"
                      [style.--lf-accent]="q.status === 'answered' ? 'var(--ck-signal-violet)' : null"
                    >
                      <ck-glyph name="layers" [size]="11" color="currentColor" /> {{ q.status === 'answered' ? 'À traiter' : 'Garder' }}
                    </button>
                    <button type="button" class="lf-chip" (click)="engine.setOracleStatus(q.id, 'dismissed')">
                      <ck-glyph name="x" [size]="11" color="currentColor" /> Ignorer
                    </button>
                  </div>
                </div>
              }
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
  styles: [
    `
      @keyframes lf-mic-bar {
        0%, 100% { height: 4px; }
        50% { height: 18px; }
      }
      @keyframes lf-cur-blink {
        0%, 100% { opacity: 1; }
        50% { opacity: 0; }
      }
      .lf-vu {
        display: flex;
        align-items: center;
        gap: 2px;
        height: 20px;
      }
      .lf-vu span {
        width: 2.5px;
        height: 4px;
        border-radius: 2px;
        background: var(--ck-fg-5);
      }
      .lf-vu-on span {
        background: var(--ck-signal-cool);
        animation: lf-mic-bar 0.9s var(--ck-ease-in-out) infinite;
      }
      .lf-cursor {
        display: inline-block;
        width: 2px;
        height: 16px;
        margin-left: 3px;
        vertical-align: text-bottom;
        background: var(--ck-signal-cool);
        animation: lf-cur-blink 1s steps(2) infinite;
      }
      .lf-chip {
        appearance: none;
        display: inline-flex;
        align-items: center;
        gap: 4px;
        font-family: var(--ck-font-sans);
        font-size: 11px;
        font-weight: 550;
        padding: 3px 8px;
        border-radius: var(--ck-radius-sm);
        cursor: pointer;
        border: 1px solid var(--lf-accent, var(--ck-stroke-2));
        background: transparent;
        color: var(--lf-accent, var(--ck-fg-2));
      }
      .lf-chip:hover {
        background: var(--ck-tint-soft);
      }
      @media (prefers-reduced-motion: reduce) {
        .lf-vu-on span,
        .lf-cursor {
          animation: none;
        }
      }
    `,
  ],
})
export class LeFilSessionComponent {
  protected readonly engine = inject(CaptureEngine);

  /** Emitted by "Terminer la capture" — the shell routes to the publish surface. */
  @Output() finish = new EventEmitter<void>();

  protected readonly bars = [0, 1, 2, 3, 4];
  protected readonly draft = signal('');
  protected readonly typing = signal(false);
  /** Mute-mic-while-typing — CONFIGURABLE, DEFAULT OFF (D3). */
  protected readonly muteWhileTyping = signal(false);

  protected readonly connected = this.engine.connected;
  protected readonly lastError = this.engine.lastError;

  private readonly feedHost = viewChild<ElementRef<HTMLElement>>('feed');
  private readonly composerRef = viewChild<ElementRef<HTMLTextAreaElement>>('composer');

  protected readonly title = computed(() => this.engine.session()?.title ?? 'Capture en cours');
  protected readonly refsCount = computed(
    () => this.engine.viewReferences().filter((r) => r.status === 'confirmed').length,
  );
  protected readonly openOracle = computed(() =>
    this.engine.oracle().filter((q) => q.status !== 'dismissed'),
  );
  /** Composer VU reflects the engine's real mic state (D3). */
  protected readonly micActive = this.engine.micActive;

  /** Live wall-clock for the status bar, ticked by a timer (never reads the
   * wall clock directly in the template — that trips ExpressionChanged in dev). */
  protected readonly clock = signal(clockLabel(Date.now()));

  private readonly destroyRef = inject(DestroyRef);

  constructor() {
    if (this.engine.sessionId() && this.engine.documents().length === 0) {
      void this.engine.loadDocuments();
    }
    const timer = setInterval(() => this.clock.set(clockLabel(Date.now())), 1000);
    this.destroyRef.onDestroy(() => clearInterval(timer));
    // Auto-scroll the Fil to the bottom on every new event (scrollTop, never scrollIntoView).
    effect(() => {
      this.engine.feed();
      const el = this.feedHost()?.nativeElement;
      if (el) queueMicrotask(() => (el.scrollTop = el.scrollHeight));
    });
    // Mute-mic-while-typing gate (D3, default OFF): only mute while actively typing.
    effect(() => this.engine.setMicMuted(this.muteWhileTyping() && this.typing()));
  }

  protected connectionLabel(): string {
    switch (this.engine.connectionState()) {
      case 'connecting':
        return 'CONNEXION…';
      case 'reconnecting':
        return 'RECONNEXION…';
      case 'error':
        return 'ERREUR';
      case 'closed':
        return 'TERMINÉ';
      default:
        return 'EN ATTENTE';
    }
  }

  protected stamp(tsMs: number): string {
    return clockLabel(tsMs);
  }

  protected toggleMuteWhileTyping(): void {
    this.muteWhileTyping.update((v) => !v);
  }

  protected onDraft(event: Event): void {
    const ta = event.target as HTMLTextAreaElement;
    this.draft.set(ta.value);
    this.autoGrow(ta);
  }

  protected onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.submit();
    }
  }

  protected submit(): void {
    const text = this.draft().trim();
    if (!text) return;
    void this.engine.sendTextTurn(text, { compute_evaluation: false });
    this.draft.set('');
    const ta = this.composerRef()?.nativeElement;
    if (ta) {
      ta.value = '';
      ta.style.height = 'auto';
    }
  }

  private autoGrow(ta: HTMLTextAreaElement): void {
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 120)}px`;
  }
}
