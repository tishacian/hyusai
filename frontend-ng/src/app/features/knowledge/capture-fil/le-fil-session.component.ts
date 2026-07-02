import {
  ChangeDetectionStrategy,
  Component,
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
import {
  CaptureEngine,
  type CapturePlanSubtopic,
  type CapturePlanTopic,
  type CaptureSectionSuggestion,
} from './capture-engine';
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
        <span
          class="ck-mono ck-tnum"
          style="font-size:12px; font-weight:700;"
          [style.color]="overtime() ? 'var(--ck-signal-neg)' : (lastFiveMinutes() ? 'var(--ck-signal-warn)' : 'var(--ck-fg-3)')"
          [title]="overtime() ? 'Temps imparti dépassé' : 'Temps restant'"
        >
          {{ remainingLabel() }}
        </span>
        <button
          type="button"
          class="ck-mono"
          (click)="togglePause()"
          [title]="paused() ? 'Reprendre la capture' : 'Mettre la capture en pause'"
          style="display:inline-flex; align-items:center; gap:5px; font-size:10px; padding:3px 8px; border-radius:999px; cursor:pointer; background:transparent;"
          [style.border]="'1px solid ' + (paused() ? 'var(--ck-signal-warn)' : 'var(--ck-stroke-2)')"
          [style.color]="paused() ? 'var(--ck-signal-warn)' : 'var(--ck-fg-4)'"
        >
          <ck-glyph [name]="paused() ? 'arrow-right' : 'pulse'" [size]="11" color="currentColor" />
          {{ paused() ? 'Reprendre' : 'Pause' }}
        </button>
        <button
          type="button"
          class="ck-mono"
          (click)="toggleFilLayout()"
          [title]="docsMode() ? 'Priorité pièces jointes — basculer vers Priorité transcript' : 'Priorité transcript — basculer vers Priorité pièces jointes'"
          style="display:inline-flex; align-items:center; gap:5px; font-size:10px; padding:3px 8px; border-radius:999px; cursor:pointer; background:transparent; border:1px solid var(--ck-stroke-2);"
          [style.color]="docsMode() ? 'var(--ck-signal-cool)' : 'var(--ck-fg-4)'"
        >
          <ck-glyph [name]="docsMode() ? 'layers' : 'ledger'" [size]="11" color="currentColor" />
          {{ docsMode() ? 'priorité pièces' : 'priorité transcript' }}
        </button>

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

      <!-- 5-minute notice (non-blocking) -->
      @if (lastFiveMinutes()) {
        <div
          style="flex:none; padding:7px 16px; background:color-mix(in oklab, var(--ck-signal-warn) 10%, var(--ck-bg-panel)); border-bottom:1px solid color-mix(in oklab, var(--ck-signal-warn) 28%, transparent); display:flex; align-items:center; gap:8px;"
        >
          <ck-glyph name="pulse" [size]="13" color="var(--ck-signal-warn)" />
          <span style="font-size:12px; color:var(--ck-fg-2);">5 dernières minutes — pensez à conclure les points clés.</span>
        </div>
      }

      <!-- closure bar (overtime, non-blocking) -->
      @if (overtime()) {
        <div
          style="flex:none; display:flex; flex-direction:column; gap:10px; padding:10px 16px; background:color-mix(in oklab, var(--ck-signal-neg) 8%, var(--ck-bg-panel)); border-bottom:1px solid color-mix(in oklab, var(--ck-signal-neg) 28%, transparent);"
        >
          <div style="display:flex; align-items:center; gap:12px; flex-wrap:wrap;">
            <ck-glyph name="warn" [size]="14" color="var(--ck-signal-neg)" />
            <span style="font-size:12.5px; color:var(--ck-fg-1); font-weight:600;">Temps imparti dépassé</span>
            <div style="margin-left:auto; display:flex; gap:8px; flex-wrap:wrap;">
              <button type="button" class="lf-close-btn" (click)="engine.extendSession(15)">
                <ck-glyph name="bolt" [size]="12" color="currentColor" /> Prolonger +15
              </button>
              <button type="button" class="lf-close-btn" (click)="scheduleFollowup()">
                <ck-glyph name="arrow-right" [size]="12" color="currentColor" /> Programmer un suivi
              </button>
              <button type="button" class="lf-close-btn" (click)="toggleClosure()">
                <ck-glyph name="layers" [size]="12" color="currentColor" /> {{ showClosure() ? 'Masquer la fiche' : 'Aperçu fiche' }}
              </button>
              <button
                type="button"
                (click)="finish.emit()"
                style="display:inline-flex; align-items:center; gap:6px; padding:6px 12px; border-radius:var(--ck-radius-md); border:none; cursor:pointer; font-weight:600; font-size:12px; background:color-mix(in oklab, var(--ck-signal-neg) 88%, transparent); color:var(--ck-on-signal);"
              >
                <ck-glyph name="check" [size]="12" color="currentColor" /> Terminer
              </button>
            </div>
          </div>
          @if (showClosure()) {
            <div
              class="ck-scroll"
              style="max-height:240px; overflow-y:auto; padding:11px 13px; border-radius:var(--ck-radius-md); border:1px solid var(--ck-stroke-2); background:var(--ck-bg-inset);"
            >
              @if (engine.closureSheet(); as sheet) {
                <pre
                  class="ck-mono"
                  style="margin:0; white-space:pre-wrap; word-break:break-word; font-size:11.5px; line-height:1.55; color:var(--ck-fg-2);"
                  >{{ sheet.markdown }}</pre>
              } @else {
                <span style="font-size:12px; color:var(--ck-fg-4); font-style:italic;">Chargement de la fiche de clôture…</span>
              }
            </div>
          }
        </div>
      }

      <!-- body — bounded to the viewport so the Fil scrolls INSIDE its panel
           (auto-scroll to bottom) and La Scène stays pinned in view instead of
           the whole page growing and pushing the scene off-screen. -->
      <div style="display:grid; grid-template-columns:220px minmax(0,1fr) 400px; height:calc(100vh - 172px); min-height:460px; overflow:hidden;">
        <!-- section rail -->
        <div
          style="border-right:1px solid var(--ck-stroke-2); background:var(--ck-bg-panel); display:flex; flex-direction:column; min-height:0;"
        >
          <div
            style="flex:none; display:flex; align-items:center; gap:7px; padding:12px 12px 10px; border-bottom:1px solid var(--ck-stroke-2);"
          >
            <ck-glyph name="layers" [size]="13" color="var(--ck-signal-violet)" />
            <span
              class="ck-mono"
              style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);"
            >
              Sections
            </span>
            @if (topicProgress().index >= 0) {
              <span class="ck-mono ck-tnum" style="margin-left:auto; font-size:10px; color:var(--ck-fg-4);">
                {{ topicProgress().index + 1 }}/{{ topicProgress().total }}
              </span>
            } @else if (topicProgress().total) {
              <span class="ck-mono ck-tnum" style="margin-left:auto; font-size:10px; color:var(--ck-fg-5);">
                {{ topicProgress().total }}
              </span>
            }
          </div>

          @if (autoSuggestion(); as sug) {
            <button
              type="button"
              (click)="applySuggestion(sug)"
              title="Section proposée automatiquement — cliquer pour suivre"
              style="flex:none; display:flex; align-items:center; gap:6px; margin:8px 10px 0; padding:6px 8px; border-radius:var(--ck-radius-sm); cursor:pointer; text-align:left; border:1px dashed color-mix(in oklab, var(--ck-signal-cool) 45%, transparent); background:color-mix(in oklab, var(--ck-signal-cool) 8%, transparent); color:var(--ck-fg-3);"
            >
              <ck-glyph name="bolt" [size]="11" color="var(--ck-signal-cool)" />
              <span style="font-size:11px; line-height:1.35; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                suggestion auto · {{ labelFor(sug.topic_id, sug.subtopic_id) }}
              </span>
            </button>
          }

          <div
            class="ck-scroll"
            style="flex:1; overflow-y:auto; padding:8px; display:flex; flex-direction:column; gap:2px; min-height:0;"
          >
            @if (planTopics().length === 0) {
              <span
                style="color:var(--ck-fg-5); font-size:11.5px; font-style:italic; padding:6px 9px; line-height:1.4;"
              >
                Conversation libre — aucun plan de sections.
              </span>
            }
            @for (topic of planTopics(); track topic.id; let i = $index) {
              <button
                type="button"
                class="lf-rail-item"
                [class.is-active]="activeTopicId() === topic.id && !activeSubtopicId()"
                (click)="selectTopic(topic)"
              >
                <span class="ck-mono ck-tnum" style="flex:none; font-size:9.5px; color:var(--ck-fg-5);">{{ i + 1 }}</span>
                <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{{ topic.title || topic.id }}</span>
              </button>
              @for (sub of topic.subtopics ?? []; track sub.id) {
                <button
                  type="button"
                  class="lf-rail-item lf-rail-sub"
                  [class.is-active]="activeTopicId() === topic.id && activeSubtopicId() === sub.id"
                  (click)="selectSubtopic(topic, sub)"
                >
                  <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{{ sub.title || sub.id }}</span>
                </button>
              }
            }
          </div>

          <div style="flex:none; padding:10px; border-top:1px solid var(--ck-stroke-2);">
            <button
              type="button"
              (click)="engine.finishSection()"
              style="display:inline-flex; align-items:center; justify-content:center; gap:6px; width:100%; padding:7px 10px; border-radius:var(--ck-radius-md); border:1px solid var(--ck-stroke-2); cursor:pointer; font-size:11.5px; font-weight:550; background:transparent; color:var(--ck-fg-3);"
            >
              <ck-glyph name="check" [size]="12" color="currentColor" /> Section terminée
            </button>
          </div>
        </div>

        <!-- Le Fil + composer — center column in mode transcript, minimized in
             the right 400px column in mode documents (order-only swap, same DOM). -->
        <div
          style="display:flex; flex-direction:column; min-height:0; min-width:0;"
          [style.order]="docsMode() ? 2 : 1"
          [style.borderLeft]="docsMode() ? '1px solid var(--ck-stroke-2)' : null"
          [style.background]="docsMode() ? 'var(--ck-bg-panel)' : null"
        >
          <div
            #feed
            class="ck-scroll"
            style="flex:1; overflow-y:auto; display:flex; flex-direction:column; gap:16px; min-height:0;"
            [style.padding]="docsMode() ? '14px 16px' : '24px 28px'"
          >
            @if (engine.feed().length === 0) {
              <div style="color:var(--ck-fg-4); font-size:13px; font-style:italic; margin-top:12px;">
                En écoute… la parole et l'écrit s'inscrivent ici, sur un seul fil horodaté.
              </div>
            }
            @for (item of engine.feed(); track item.id) {
              <div style="display:flex; gap:14px;" [attr.data-feed-id]="item.id">
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
                      [style.fontSize]="docsMode() ? '14px' : '17px'"
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

          <!-- relance stack (pile de relances) -->
          @if (hintQueue().length) {
            <div
              style="flex:none; display:flex; flex-direction:column; gap:8px;"
              [style.padding]="docsMode() ? '10px 16px 0' : '12px 28px 0'"
            >
              <div style="display:flex; align-items:center; gap:8px;">
                <ck-glyph name="bolt" [size]="12" color="var(--ck-signal-cool)" />
                <span
                  class="ck-mono"
                  style="font-size:9.5px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);"
                >
                  Relances
                </span>
                <span class="ck-mono" style="margin-left:auto; font-size:9px; color:var(--ck-fg-5);">
                  {{ hintQueue().length }} · non bloquant
                </span>
              </div>
              @if (topHint(); as h) {
                <div
                  [title]="h.full_question || h.hint"
                  style="padding:10px 12px; border-radius:var(--ck-radius-md); border:1px solid color-mix(in oklab, var(--ck-signal-cool) 35%, var(--ck-stroke-2)); background:color-mix(in oklab, var(--ck-signal-cool) 7%, var(--ck-bg-inset));"
                >
                  <p style="margin:0; font-size:13px; line-height:1.45; color:var(--ck-fg-1);">{{ h.hint }}</p>
                </div>
              }
              @if (restHints().length) {
                <div style="display:flex; flex-wrap:wrap; gap:6px;">
                  @for (h of restHints(); track h.id) {
                    <span
                      [title]="h.full_question || h.hint"
                      class="ck-mono"
                      style="font-size:10.5px; color:var(--ck-fg-4); padding:3px 8px; border:1px solid var(--ck-stroke-2); border-radius:999px; max-width:240px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;"
                    >
                      {{ h.hint }}
                    </span>
                  }
                </div>
              }
            </div>
          }

          <!-- composer -->
          <div
            style="flex:none; border-top:1px solid var(--ck-stroke-2); background:var(--ck-bg-panel);"
            [style.padding]="docsMode() ? '12px 16px 14px' : '14px 28px 16px'"
          >
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

        <!-- La Scène + Oracle — right 400px column in mode transcript, center
             (large, pièces jointes prioritized) in mode documents. -->
        <div
          class="ck-scroll"
          style="border-left:1px solid var(--ck-stroke-2); background:var(--ck-bg-panel); display:flex; flex-direction:column; min-height:0; overflow-y:auto; padding:14px; gap:14px;"
          [style.order]="docsMode() ? 1 : 2"
          [style.borderLeft]="docsMode() ? 'none' : '1px solid var(--ck-stroke-2)'"
          [style.padding]="docsMode() ? '18px 22px' : '14px'"
        >
          <app-la-scene [wide]="docsMode()" />

          <div style="display:flex; flex-direction:column; min-height:0; gap:10px;">
            <div style="display:flex; align-items:center; gap:8px;">
              <ck-glyph name="bolt" [size]="13" color="var(--ck-signal-violet)" />
              <span class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">
                Pistes de l'oracle
              </span>
              <button
                type="button"
                class="ck-mono"
                (click)="toggleOracleSuppressed()"
                [title]="oracleSuppressed() ? 'Réafficher les pistes de l\\'oracle' : 'Masquer l\\'oracle pour cette séance'"
                style="margin-left:auto; display:inline-flex; align-items:center; gap:5px; font-size:9px; padding:3px 8px; border-radius:999px; cursor:pointer; background:transparent;"
                [style.border]="'1px solid ' + (oracleSuppressed() ? 'var(--ck-signal-violet)' : 'var(--ck-stroke-2)')"
                [style.color]="oracleSuppressed() ? 'var(--ck-signal-violet)' : 'var(--ck-fg-5)'"
              >
                <ck-glyph [name]="oracleSuppressed() ? 'bolt' : 'x'" [size]="10" color="currentColor" />
                {{ oracleSuppressed() ? 'Afficher' : 'Masquer' }}
              </button>
            </div>
            @if (oracleSuppressed()) {
              <span style="color:var(--ck-fg-5); font-size:12px; font-style:italic;">
                Oracle masqué — il continue d'écouter en arrière-plan.
              </span>
            } @else {
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
                      <span
                        [title]="isHighPriority(q.priority) ? 'Priorité haute' : 'Priorité normale'"
                        style="flex:none; width:6px; height:6px; border-radius:999px;"
                        [style.background]="isHighPriority(q.priority) ? 'var(--ck-signal-warn)' : 'var(--ck-fg-5)'"
                      ></span>
                      <span class="ck-mono" style="font-size:8.5px; letter-spacing:0.12em; text-transform:uppercase; color:var(--ck-signal-violet);">
                        Oracle
                      </span>
                      @if (oracleTopic(q.topic_id); as topic) {
                        <span
                          class="ck-mono"
                          style="font-size:8.5px; padding:1px 6px; border-radius:999px; border:1px solid var(--ck-stroke-2); color:var(--ck-fg-4); max-width:120px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;"
                          [title]="topic"
                        >
                          {{ topic }}
                        </span>
                      }
                      @if (q.status === 'deferred') {
                        <span class="ck-mono" style="font-size:8.5px; color:var(--ck-signal-cool);">différée</span>
                      }
                      <span class="ck-mono" style="margin-left:auto; font-size:9px; color:var(--ck-fg-5);">{{ stamp(q.ts_ms) }}</span>
                    </div>
                    <p style="margin:0; font-size:12.5px; line-height:1.45; color:var(--ck-fg-2);">{{ q.text }}</p>
                    <div style="display:flex; gap:6px; flex-wrap:wrap;">
                      <button
                        type="button"
                        class="lf-chip"
                        (click)="engine.setOracleStatus(q.id, q.status === 'answered' ? 'open' : 'answered')"
                        [style.--lf-accent]="q.status === 'answered' ? 'var(--ck-signal-violet)' : null"
                      >
                        <ck-glyph name="layers" [size]="11" color="currentColor" /> {{ q.status === 'answered' ? 'À traiter' : 'Garder' }}
                      </button>
                      <button
                        type="button"
                        class="lf-chip"
                        (click)="engine.deferOracle(q.id)"
                        [style.--lf-accent]="q.status === 'deferred' ? 'var(--ck-signal-cool)' : null"
                      >
                        <ck-glyph name="arrow-right" [size]="11" color="currentColor" /> Différer
                      </button>
                      <button type="button" class="lf-chip" (click)="engine.setOracleStatus(q.id, 'dismissed')">
                        <ck-glyph name="x" [size]="11" color="currentColor" /> Ignorer
                      </button>
                    </div>
                  </div>
                }
              </div>
            }
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
      .lf-close-btn {
        appearance: none;
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-family: var(--ck-font-sans);
        font-size: 12px;
        font-weight: 550;
        padding: 6px 11px;
        border-radius: var(--ck-radius-md);
        cursor: pointer;
        border: 1px solid var(--ck-stroke-2);
        background: var(--ck-bg-inset);
        color: var(--ck-fg-2);
      }
      .lf-close-btn:hover {
        background: var(--ck-tint-soft);
      }
      .lf-rail-item {
        appearance: none;
        display: flex;
        align-items: center;
        gap: 7px;
        width: 100%;
        text-align: left;
        font-family: var(--ck-font-sans);
        font-size: 12.5px;
        cursor: pointer;
        border: none;
        background: transparent;
        border-radius: var(--ck-radius-sm);
        padding: 7px 9px;
        color: var(--ck-fg-2);
      }
      .lf-rail-item:hover {
        background: var(--ck-tint-soft);
      }
      .lf-rail-item.is-active {
        background: var(--ck-tint-soft);
        color: var(--ck-fg-1);
        box-shadow: inset 2px 0 0 var(--ck-signal-cool);
      }
      .lf-rail-sub {
        padding-left: 24px;
        font-size: 12px;
        color: var(--ck-fg-3);
      }
      .lf-rail-sub.is-active {
        color: var(--ck-fg-1);
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

  /** Mode 'documents' — La Scène au centre, fil minimisé à droite (visuel only). */
  protected readonly docsMode = computed(() => this.engine.filLayout() === 'documents');

  private readonly feedHost = viewChild<ElementRef<HTMLElement>>('feed');
  private readonly composerRef = viewChild<ElementRef<HTMLTextAreaElement>>('composer');

  protected readonly title = computed(() => this.engine.session()?.title ?? 'Capture en cours');
  protected readonly refsCount = computed(
    () => this.engine.viewReferences().filter((r) => r.status === 'confirmed').length,
  );
  protected readonly openOracle = computed(() =>
    this.engine.oracle().filter((q) => q.status !== 'dismissed'),
  );

  // ---- session minuterie / closure (P1, v0) ------------------------------
  protected readonly paused = this.engine.paused;
  protected readonly overtime = this.engine.overtime;
  protected readonly lastFiveMinutes = this.engine.lastFiveMinutes;
  /** mm:ss countdown (prefixed with `+` once in overtime). */
  protected readonly remainingLabel = computed(() => this.formatDuration(this.engine.remainingMs()));
  /** Collapsible closure-sheet preview under the closure bar. */
  protected readonly showClosure = signal(false);

  // ---- oracle enrichment (P1, Option A) ----------------------------------
  protected readonly oracleSuppressed = this.engine.oracleSuppressed;

  // ---- section rail (P0 #1) ----------------------------------------------
  protected readonly planTopics = this.engine.planTopics;
  protected readonly activeTopicId = this.engine.activeTopicId;
  protected readonly activeSubtopicId = this.engine.activeSubtopicId;

  /** Progression of the active topic within the plan (e.g. "2/5"). */
  protected readonly topicProgress = computed(() => {
    const topics = this.engine.planTopics();
    const index = topics.findIndex((t) => t.id === this.engine.activeTopicId());
    return { index, total: topics.length };
  });

  /** Auto-detected section suggestion, shown only when it differs from the active one. */
  protected readonly autoSuggestion = computed<CaptureSectionSuggestion | null>(() => {
    const sug = this.engine.sectionSuggestion();
    if (!sug || !sug.topic_id) return null;
    const sameTopic = sug.topic_id === this.engine.activeTopicId();
    const sameSub = (sug.subtopic_id ?? null) === (this.engine.activeSubtopicId() ?? null);
    return sameTopic && sameSub ? null : sug;
  });

  // ---- relance stack (P0 #1) ---------------------------------------------
  protected readonly hintQueue = this.engine.hintQueue;
  protected readonly topHint = computed(() => this.engine.hintQueue()[0] ?? null);
  protected readonly restHints = computed(() => this.engine.hintQueue().slice(1));
  /** Composer VU reflects the engine's real mic state (D3). */
  protected readonly micActive = this.engine.micActive;

  constructor() {
    if (this.engine.sessionId() && this.engine.documents().length === 0) {
      void this.engine.loadDocuments();
    }
    // Auto-scroll the Fil to the bottom on every new event (scrollTop, never
    // scrollIntoView) — unless a revisit target is pending (it wins the scroll).
    effect(() => {
      this.engine.feed();
      if (this.engine.revisitTarget()) return;
      const el = this.feedHost()?.nativeElement;
      if (el) queueMicrotask(() => (el.scrollTop = el.scrollHeight));
    });
    // "Revoir l'instant capté": once the targeted feed item is rendered, scroll
    // it into view (centered), flash it briefly, then consume the target.
    effect(() => {
      const target = this.engine.revisitTarget();
      if (!target) return;
      const rendered = this.engine.feed().some((i) => i.id === target);
      const host = this.feedHost()?.nativeElement;
      if (!rendered || !host) return;
      queueMicrotask(() => {
        const el = host.querySelector(`[data-feed-id="${CSS.escape(target)}"]`) as HTMLElement | null;
        if (el) {
          el.scrollIntoView({ block: 'center' });
          el.style.transition = 'background-color 1.6s ease-out';
          el.style.backgroundColor = 'color-mix(in oklab, var(--ck-signal-cool) 18%, transparent)';
          setTimeout(() => (el.style.backgroundColor = 'transparent'), 1200);
        }
        this.engine.revisitTarget.set(null);
      });
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

  /** Steer to a topic (no sous-sujet); used for plan topics and topic headers. */
  protected selectTopic(topic: CapturePlanTopic): void {
    void this.engine.selectSection(topic.id, null);
  }

  /** Steer to a specific sous-sujet within a topic. */
  protected selectSubtopic(topic: CapturePlanTopic, sub: CapturePlanSubtopic): void {
    void this.engine.selectSection(topic.id, sub.id);
  }

  /** Follow the auto-detected section suggestion. */
  protected applySuggestion(sug: CaptureSectionSuggestion): void {
    void this.engine.selectSection(sug.topic_id, sug.subtopic_id);
  }

  /** Human label for a topic/sous-sujet pair (falls back to ids). */
  protected labelFor(topicId: string | null, subtopicId: string | null): string {
    const topic = this.engine.planTopics().find((t) => t.id === topicId);
    if (!topic) return topicId ?? '—';
    const topicLabel = topic.title || topic.id;
    if (!subtopicId) return topicLabel;
    const sub = (topic.subtopics ?? []).find((s) => s.id === subtopicId);
    return sub ? `${topicLabel} › ${sub.title || sub.id}` : topicLabel;
  }

  /** Bascule éphémère de la disposition (ne modifie pas le défaut système). */
  protected toggleFilLayout(): void {
    this.engine.setFilLayout(this.docsMode() ? 'transcript' : 'documents');
  }

  protected toggleMuteWhileTyping(): void {
    this.muteWhileTyping.update((v) => !v);
  }

  // ---- session minuterie / closure (P1, v0) ------------------------------
  protected togglePause(): void {
    if (this.paused()) void this.engine.resume();
    else void this.engine.pause();
  }

  protected scheduleFollowup(): void {
    void this.engine.scheduleFollowup();
  }

  /** Toggle the closure-sheet preview; lazily load it on first open. */
  protected toggleClosure(): void {
    const next = !this.showClosure();
    this.showClosure.set(next);
    if (next && !this.engine.closureSheet()) void this.engine.loadClosureSheet();
  }

  /** Format a remaining-ms value as `mm:ss`, prefixing `+` when in overtime. */
  private formatDuration(ms: number): string {
    const overtime = ms < 0;
    const total = Math.floor(Math.abs(ms) / 1000);
    const minutes = Math.floor(total / 60);
    const seconds = total % 60;
    const body = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    return overtime ? `+${body}` : body;
  }

  // ---- oracle enrichment (P1, Option A) ----------------------------------
  protected toggleOracleSuppressed(): void {
    this.engine.setOracleSuppressed(!this.oracleSuppressed());
  }

  /** Human topic label for an oracle item (null when unmappable). */
  protected oracleTopic(topicId: string | null | undefined): string | null {
    return this.engine.topicLabelFor(topicId);
  }

  /** Treat a high backend priority as "haute" (warn dot), else "normale". */
  protected isHighPriority(priority: number | null | undefined): boolean {
    return (priority ?? 0) >= 2;
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
