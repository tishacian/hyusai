import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  DestroyRef,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { ToastrService, ActiveToast } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { SettingsService } from '@app/core/settings.service';
import { SseChunk, SseService } from '@app/core/sse.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { RuntimeHealthService } from '@app/core/runtime-health.service';
import { RuntimeStatusBadgeComponent } from '@app/shared/cockpit';

interface DecisionStep {
  id: string;
  type?: string;
  title?: string;
  description?: string;
  status?: 'pending' | 'active' | 'completed' | 'error';
  duration?: number;
  metrics?: Record<string, unknown>;
}

interface Source {
  id?: string;
  document_id?: string;
  title?: string;
  filename?: string;
  snippet?: string;
  content?: string;
  text?: string;
  score?: number;
  collection?: string;
  collection_name?: string;
  page?: number;
  url?: string;
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
}

/**
 * Token emitted by ``renderAnswer`` — either a chunk of plain text or a
 * citation marker like ``[3]`` that we upgrade into a clickable chip.
 */
export type AnswerToken =
  | { kind: 'text'; value: string }
  | { kind: 'cite'; n: number };

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  decisionSteps?: DecisionStep[];
  sources?: Source[];
  feedback?: 'up' | 'down' | null;
  durationMs?: number;
  ragMode?: string | null;
  promptType?: string | null;
  evaluation?: {
    composite_score: number;
    scores: Record<string, number>;
    hallucination_rate: number;
    claim_audit?: { claims?: Array<{ text: string; verdict: string; score: number }> };
  } | null;
}

interface SuggestionCard {
  icon: string;
  label: string;
  prompt: string;
}

interface ReasoningTemplate {
  slug: string;
  label: string;
  description: string;
}

type RagModeChoice = 'auto' | 'naive' | 'hybrid' | 'hah' | 'chah';

const RAG_MODE_CHOICES: { slug: RagModeChoice; label: string; hint: string }[] = [
  { slug: 'auto', label: 'Auto', hint: 'Use workspace default' },
  { slug: 'naive', label: 'Naive', hint: 'Single-pass vector retrieval' },
  { slug: 'hybrid', label: 'Hybrid', hint: 'BM25 + dense, RRF fusion' },
  { slug: 'hah', label: 'HAH', hint: 'Hybrid Answer Harvesting (two-pass)' },
  { slug: 'chah', label: 'C-HAH', hint: 'Composite HAH (parallel variants)' },
];

const RAG_SLUG_TO_PRESET: Record<RagModeChoice, string> = {
  auto: 'None',
  naive: 'Semantic',
  hybrid: 'Hybrid',
  hah: 'HAH',
  chah: 'OmniRAG',
};

/**
 * Metric registry for the reasoning-trail evaluation step. Each entry
 * declares:
 *  - ``polarity``  — whether a HIGHER or LOWER raw value is considered
 *    good. All cosine-sim based scores (relevance, factuality, coherence,
 *    hhem, adv_hhem) are "higher is better"; future entries like
 *    ``hallucination_rate`` or ``*_error`` should flip to ``lower``.
 *  - ``max``       — theoretical upper bound of the raw value. Used to
 *    normalise the bar width so that e.g. HHEM (which is bounded at 0.5
 *    by the formula ``mf / (1 + mf)``) can visually reach 100% on a
 *    perfectly-grounded response.
 *  - ``good``      — normalised threshold [0..1] above which the metric
 *    is shown in emerald.
 *  - ``fair``      — normalised threshold above which it's shown in amber;
 *    anything below drops to red.
 *  - ``description`` — operator-facing tooltip text.
 *
 * Keep the keys in sync with ``backend/app/services/metrics/evaluator.py``
 * (and any future evaluator plugged in). Unknown keys fall back to the
 * ``default`` entry so we degrade gracefully on new metrics.
 */
interface MetricSpec {
  polarity: 'higher' | 'lower';
  max: number;
  good: number;
  fair: number;
  description: string;
}

const METRIC_REGISTRY: Record<string, MetricSpec> = {
  relevance: {
    polarity: 'higher',
    max: 1,
    good: 0.7,
    fair: 0.4,
    description: 'Cosine similarity between query and response embeddings.',
  },
  factuality: {
    polarity: 'higher',
    max: 1,
    good: 0.7,
    fair: 0.4,
    description: 'Max cosine similarity between response and retrieved chunks.',
  },
  coherence: {
    polarity: 'higher',
    max: 1,
    good: 0.7,
    fair: 0.4,
    description: 'Mean cosine similarity between consecutive response sentences.',
  },
  hhem: {
    polarity: 'higher',
    // hhem = mf / (1 + mf) with mf = mean_sim * factuality. Theoretical
    // ceiling is 0.5 (mf → 1) but realistic operating range for a
    // well-grounded RAG response is ~0.28–0.38 (mean_sim ≈ factuality ≈
    // 0.75 → mf ≈ 0.56 → hhem ≈ 0.36). Thresholds below are expressed as
    // "quality fraction" = raw / max, so good=0.55 ↔ raw ≥ 0.275 and
    // fair=0.25 ↔ raw ≥ 0.125 — matches what a solid response actually
    // produces instead of the unreachable "70 % of theoretical ceiling".
    max: 0.5,
    good: 0.55,
    fair: 0.25,
    description: 'Grounding = mean_sim × factuality, squashed by 1/(1+mf). Higher = less hallucinated. Realistic band ~0.28–0.38.',
  },
  adv_hhem: {
    polarity: 'higher',
    // adv_hhem = (mf * coherence * relevance) / (1 + mf). Four [0,1]
    // factors compounded: the ceiling is also 0.5, but realistic range
    // for a well-scored response is ~0.10–0.20 (mf≈0.5, coh≈0.7,
    // rel≈0.7 → adv_hhem ≈ 0.16). Thresholds calibrated on that band so
    // a good answer reads green, not catastrophic red, while genuinely
    // weak grounding/coherence/relevance still surfaces in amber.
    max: 0.5,
    good: 0.3,
    fair: 0.1,
    description: 'Compound grounding × coherence × relevance. Very penalising by design (product of 4 cosine scores). Realistic band ~0.10–0.20.',
  },
  hallucination_rate: {
    polarity: 'lower',
    max: 1,
    good: 0.7,
    fair: 0.4,
    description: 'Share of claims that could not be grounded. Lower is better.',
  },
};

const DEFAULT_METRIC_SPEC: MetricSpec = {
  polarity: 'higher',
  max: 1,
  good: 0.7,
  fair: 0.4,
  description: '',
};

const STEP_ICONS: Record<string, string> = {
  query_received: 'log-in',
  query_rewrite: 'wand-2',
  embedding: 'binary',
  retrieve: 'search',
  context_filtering: 'filter',
  validation: 'shield-check',
  synthesis: 'sparkles',
  evaluation: 'bar-chart-2',
  document_ingestion: 'file-text',
  routing: 'git-branch',
  default: 'cog',
};

@Component({
  selector: 'app-chat-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, RouterLink, IconComponent, RuntimeStatusBadgeComponent],
  template: `
    <div class="flex flex-col h-full">
      <!-- Toolbar -->
      <div
        class="flex items-center justify-between gap-2 px-4 py-2.5 border-b border-white/5 bg-white/[0.02]"
      >
        <div class="flex items-center gap-2 text-[11px] text-gray-400 min-w-0 flex-wrap">
          <app-icon name="circle-dot" [size]="12" class="text-emerald-400" />
          <span class="uppercase tracking-wider font-semibold">Chat</span>
          <span class="text-gray-600">·</span>
          <span class="font-mono truncate">{{ settings.settings().defaultModel || '—' }}</span>
          <span class="text-gray-600">·</span>

          <!-- Per-query retrieval mode chip -->
          <label class="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider text-gray-500">
            Retrieval
          </label>
          <select
            class="bg-white/5 border border-white/10 rounded px-1.5 py-0.5 text-[11px] font-mono focus:outline-none focus:ring-1 focus:ring-brand-400"
            [ngModel]="ragModeOverride()"
            (ngModelChange)="ragModeOverride.set($event)"
            [title]="ragModeHint()"
          >
            @for (m of ragModeChoices; track m.slug) {
              <option [value]="m.slug">{{ m.label }}</option>
            }
          </select>
          @if (ragModeOverride() !== 'auto') {
            <ck-runtime-status [status]="ragModeRuntimeStatus()" />
          }

          <!-- Reasoning template chip -->
          <label class="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider text-gray-500">
            Reasoning
          </label>
          <select
            class="bg-white/5 border border-white/10 rounded px-1.5 py-0.5 text-[11px] focus:outline-none focus:ring-1 focus:ring-brand-400"
            [ngModel]="promptType()"
            (ngModelChange)="promptType.set($event)"
            [title]="promptTypeHint()"
          >
            <option value="auto">Auto</option>
            @for (t of reasoningTemplates(); track t.slug) {
              <option [value]="t.slug">{{ t.label }}</option>
            }
          </select>
        </div>
        <div class="flex items-center gap-1.5">
          @if (ttsEnabled() && ttsSpeaking()) {
            <button
              type="button"
              class="p-1.5 rounded hover:bg-white/5 text-brand-300 hover:text-brand-200 transition"
              [title]="ttsPaused() ? 'Resume voice playback' : 'Pause voice playback'"
              (click)="pauseResumeTts()"
            >
              <app-icon
                [name]="ttsPaused() ? 'play' : 'pause'"
                [size]="14"
              />
            </button>
          }
          <button
            type="button"
            class="p-1.5 rounded hover:bg-white/5 text-gray-400 hover:text-white transition"
            [class.text-brand-400]="ttsEnabled()"
            [title]="ttsEnabled() ? 'Voice output on' : 'Voice output off'"
            (click)="toggleTTS()"
          >
            <app-icon [name]="ttsEnabled() ? 'volume-2' : 'volume-x'" [size]="14" />
          </button>
          <button
            type="button"
            class="p-1.5 rounded hover:bg-white/5 text-gray-400 hover:text-white transition"
            title="Clear conversation"
            (click)="clearConversation()"
          >
            <app-icon name="trash-2" [size]="14" />
          </button>
        </div>
      </div>

      <!-- Messages -->
      <div
        class="flex-1 overflow-y-auto px-4 py-4 space-y-5"
        style="max-height: calc(100vh - 320px); min-height: 360px;"
      >
        @if (messages().length === 0 && !streaming()) {
          <div class="h-full flex flex-col items-center justify-center py-8">
            <div
              class="w-12 h-12 rounded-full bg-gradient-to-br from-brand-500/20 to-violet-500/20 flex items-center justify-center mb-3"
            >
              <app-icon name="sparkles" [size]="20" class="text-brand-300" />
            </div>
            <div class="text-sm font-semibold text-gray-900 dark:text-white">
              Start a conversation
            </div>
            <p class="text-xs text-gray-500 dark:text-gray-400 mt-1 max-w-xs text-center">
              Try one of these prompts or ask anything about your corpus.
            </p>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-5 w-full max-w-2xl">
              @for (s of suggestions; track s.prompt) {
                <button
                  type="button"
                  class="text-left px-3 py-2.5 rounded-md ring-1 ring-white/5 bg-white/[0.02] hover:bg-white/[0.06] hover:ring-brand-500/30 transition group"
                  (click)="useSuggestion(s)"
                >
                  <div class="flex items-center gap-2 mb-1">
                    <div
                      class="w-6 h-6 rounded-md flex items-center justify-center bg-brand-500/10 text-brand-400 group-hover:bg-brand-500/20 transition shrink-0"
                    >
                      <app-icon [name]="s.icon" [size]="12" />
                    </div>
                    <span class="text-xs font-semibold text-gray-700 dark:text-gray-200 truncate">
                      {{ s.label }}
                    </span>
                  </div>
                  <p class="text-[11px] text-gray-500 dark:text-gray-400 leading-relaxed line-clamp-2">
                    {{ s.prompt }}
                  </p>
                </button>
              }
            </div>
          </div>
        }

        @for (msg of messages(); track msg.id) {
          <!-- User bubble -->
          @if (msg.role === 'user') {
            <div class="flex justify-end">
              <div
                class="max-w-[80%] bg-brand-500 text-white rounded-2xl rounded-br-sm px-4 py-2.5 text-sm whitespace-pre-wrap shadow-sm"
              >
                {{ msg.content }}
              </div>
            </div>
          } @else {
            <!-- Assistant bubble with reasoning trail -->
            <div class="flex flex-col gap-2">
              @if (msg.decisionSteps && msg.decisionSteps.length > 0) {
                <div class="ml-0 space-y-1.5">
                  <button
                    type="button"
                    class="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-gray-500 hover:text-gray-300 font-semibold"
                    (click)="toggleTrail(msg.id)"
                  >
                    <app-icon
                      [name]="isTrailOpen(msg.id) ? 'chevron-down' : 'chevron-right'"
                      [size]="12"
                    />
                    <app-icon name="workflow" [size]="12" class="text-brand-400" />
                    Reasoning trail · {{ msg.decisionSteps.length }} step{{
                      msg.decisionSteps.length > 1 ? 's' : ''
                    }}
                  </button>
                  @if (isTrailOpen(msg.id)) {
                    <div class="space-y-1 pl-1">
                      @for (step of msg.decisionSteps; track step.id) {
                        <div
                          class="flex items-start gap-2 rounded-md px-2.5 py-2 text-[12px] border"
                          [class.border-emerald-500\\/20]="step.status === 'completed'"
                          [class.bg-emerald-500\\/5]="step.status === 'completed'"
                          [class.border-red-500\\/30]="step.status === 'error'"
                          [class.bg-red-500\\/5]="step.status === 'error'"
                          [class.border-brand-500\\/30]="step.status === 'active'"
                          [class.bg-brand-500\\/5]="step.status === 'active'"
                          [class.border-white\\/5]="!step.status || step.status === 'pending'"
                          [class.bg-white\\/[0\\.02]]="!step.status || step.status === 'pending'"
                        >
                          <app-icon
                            [name]="iconFor(step)"
                            [size]="13"
                            class="mt-0.5 shrink-0"
                            [class.text-emerald-400]="step.status === 'completed'"
                            [class.text-red-400]="step.status === 'error'"
                            [class.text-brand-400]="step.status === 'active'"
                            [class.text-gray-500]="!step.status || step.status === 'pending'"
                          />
                          <div class="flex-1 min-w-0">
                            <div class="flex items-center gap-2">
                              <span class="font-medium text-white truncate">{{
                                step.title || step.type || 'Step'
                              }}</span>
                              @if (step.status === 'active') {
                                <span
                                  class="text-[9px] uppercase tracking-wider text-brand-400 font-semibold"
                                  >running</span
                                >
                              }
                              @if (step.status === 'completed' && step.duration) {
                                <span class="text-[10px] font-mono text-gray-500 ml-auto"
                                  >{{ step.duration }}ms</span
                                >
                              }
                            </div>
                            <!-- Evaluation step: compact summary line +
                                 expand affordance. The description is
                                 suppressed in favor of a richer bar view
                                 so numeric scores stay scannable. -->
                            @if (isEvaluationStep(step)) {
                              <button
                                type="button"
                                class="group mt-1 flex items-center gap-1.5 text-[10px] text-gray-400 hover:text-gray-200"
                                (click)="toggleEval(msg.id, step.id)"
                                [title]="isEvalOpen(msg.id, step.id) ? 'Collapse metrics' : 'Expand metrics'"
                              >
                                <app-icon
                                  [name]="isEvalOpen(msg.id, step.id) ? 'chevron-down' : 'chevron-right'"
                                  [size]="10"
                                  class="text-gray-500 group-hover:text-gray-300"
                                />
                                <span class="font-mono">
                                  {{ scoreSummary(step) || 'metrics' }}
                                </span>
                                @for (m of latencyMetrics(step); track m.key) {
                                  <span class="text-gray-500">·</span>
                                  <span class="font-mono text-gray-500">
                                    {{ metricLabel(m.key).replace(' Latency', '') }}
                                    {{ formatLatency(m.value) }}
                                  </span>
                                }
                              </button>
                              @if (isEvalOpen(msg.id, step.id)) {
                                <div class="mt-2 space-y-1.5">
                                  @for (m of scoreMetrics(step); track m.key) {
                                    @let tone = scoreTone(m.key, m.value);
                                    @let spec = metricSpec(m.key);
                                    <div
                                      class="grid grid-cols-[96px_1fr_auto] items-center gap-2 text-[11px]"
                                      [title]="spec.description"
                                    >
                                      <!-- Label + polarity marker -->
                                      <div class="flex items-center gap-1.5 min-w-0">
                                        <span
                                          class="w-1.5 h-1.5 rounded-full shrink-0"
                                          [class]="tone.dot"
                                        ></span>
                                        <span class="font-mono text-[10px] uppercase tracking-wider text-gray-400 truncate">
                                          {{ metricLabel(m.key) }}
                                        </span>
                                        @if (spec.polarity === 'lower') {
                                          <span
                                            class="text-[9px] font-mono text-gray-500 shrink-0"
                                            title="Lower is better"
                                          >↓</span>
                                        } @else if (spec.max < 1) {
                                          <span
                                            class="text-[9px] font-mono text-gray-500 shrink-0"
                                            [title]="'Max ' + spec.max.toFixed(2)"
                                          >·{{ spec.max.toFixed(2) }}</span>
                                        }
                                      </div>
                                      <!-- Bar (width = normalised quality, not raw value,
                                           so metrics capped at 0.5 or flipped polarity
                                           still fill the track when optimal). -->
                                      <div
                                        class="relative h-1.5 rounded-full overflow-hidden"
                                        [class]="tone.barBg"
                                      >
                                        <div
                                          class="absolute inset-y-0 left-0 rounded-full transition-[width]"
                                          [class]="tone.bar"
                                          [style.width.%]="barFraction(m.key, m.value) * 100"
                                        ></div>
                                      </div>
                                      <!-- Raw value (always displayed in metric's own
                                           units so operators can correlate with logs). -->
                                      <span
                                        class="font-mono text-[10px] shrink-0 tabular-nums w-10 text-right"
                                        [class]="tone.text"
                                      >
                                        {{ m.value.toFixed(2) }}
                                      </span>
                                    </div>
                                  }
                                  @if (latencyMetrics(step).length > 0) {
                                    <div class="flex flex-wrap gap-1.5 pt-1 border-t border-white/5">
                                      @for (m of latencyMetrics(step); track m.key) {
                                        <span
                                          class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-white/[0.04] font-mono text-[10px] text-gray-400 ring-1 ring-white/5"
                                        >
                                          <span class="uppercase tracking-wider text-gray-500">
                                            {{ metricLabel(m.key).replace(' Latency', '') }}
                                          </span>
                                          <span class="tabular-nums text-gray-200">
                                            {{ formatLatency(m.value) }}
                                          </span>
                                        </span>
                                      }
                                    </div>
                                  }
                                </div>
                              }
                            } @else if (step.description) {
                              <div class="text-gray-400 text-[11px] mt-0.5 whitespace-pre-wrap">
                                {{ step.description }}
                              </div>
                            }
                          </div>
                        </div>
                      }
                    </div>
                  }
                </div>
              }

              <!-- Content -->
              <div class="flex justify-start">
                <div
                  class="max-w-[85%] bg-gray-100 dark:bg-white/[0.04] text-gray-900 dark:text-gray-100 rounded-2xl rounded-bl-sm px-4 py-2.5 text-sm whitespace-pre-wrap leading-relaxed ring-1 ring-black/5 dark:ring-white/5"
                >
                  @for (tok of renderAnswer(msg.content); track $index) {
                    @if (tok.kind === 'text') {
                      <span>{{ tok.value }}</span>
                    } @else if (isValidCitation(msg, tok.n)) {
                      <button
                        type="button"
                        class="inline-flex items-center justify-center min-w-[1.25rem] h-[1.125rem] px-1 mx-0.5 align-baseline rounded-md text-[10px] font-mono font-semibold bg-brand-500/15 text-brand-500 dark:text-brand-300 hover:bg-brand-500/30 hover:text-brand-200 transition ring-1 ring-brand-500/30 cursor-pointer"
                        [title]="citationTooltip(msg, tok.n)"
                        (click)="gotoSource(msg, tok.n)"
                      >
                        {{ tok.n }}
                      </button>
                    } @else {
                      <span
                        class="inline-flex items-center justify-center min-w-[1.25rem] h-[1.125rem] px-1 mx-0.5 align-baseline rounded-md text-[10px] font-mono bg-gray-400/15 text-gray-500 ring-1 ring-gray-400/20"
                        [title]="'Source [' + tok.n + '] referenced by the model but not available'"
                      >
                        {{ tok.n }}
                      </span>
                    }
                  }
                </div>
              </div>

              <!-- Missing-citations banner: model cited [N] but the retrieval
                   returned fewer (or zero) chunks. Surface it so operators
                   do not mistake disabled grey chips for a styling bug. -->
              @if (missingCitations(msg); as missing) {
                @if (missing.length > 0) {
                  <div
                    class="ml-0 mt-1 flex items-start gap-2 rounded-md px-3 py-2 text-[11px] bg-amber-500/10 text-amber-300 ring-1 ring-amber-500/25"
                  >
                    <app-icon name="alert-triangle" [size]="13" class="mt-0.5 shrink-0 text-amber-400" />
                    <div class="leading-relaxed">
                      The model referenced
                      @for (n of missing; track n; let last = $last) {
                        <span class="font-mono text-amber-200">[{{ n }}]</span>{{ last ? '' : ', ' }}
                      }
                      but
                      @if (!msg.sources || msg.sources.length === 0) {
                        no retrieval source was returned for this answer.
                      } @else {
                        only {{ msg.sources.length }} source{{ msg.sources.length > 1 ? 's were' : ' was' }} returned, so these citations are likely hallucinated.
                      }
                    </div>
                  </div>
                }
              }

              <!-- Sources / citations -->
              @if (msg.sources && msg.sources.length > 0) {
                <div class="ml-0 space-y-1.5">
                  <button
                    type="button"
                    class="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-gray-500 hover:text-gray-300 font-semibold"
                    (click)="toggleSources(msg.id)"
                  >
                    <app-icon
                      [name]="isSourcesOpen(msg.id) ? 'chevron-down' : 'chevron-right'"
                      [size]="12"
                    />
                    <app-icon name="book-open" [size]="12" class="text-brand-400" />
                    Sources · {{ msg.sources.length }}
                  </button>
                  @if (isSourcesOpen(msg.id)) {
                    <ol class="space-y-1.5 pl-1">
                      @for (src of msg.sources; track $index; let i = $index) {
                        <li
                          [id]="sourceDomId(msg.id, i + 1)"
                          [class]="isSourceCited(msg, i + 1)
                            ? 'rounded-md px-3 py-2 text-[12px] transition-all bg-brand-500/10 ring-1 ring-brand-500/25'
                            : 'rounded-md px-3 py-2 text-[12px] transition-all bg-white/[0.02] dark:bg-white/[0.03] ring-1 ring-black/5 dark:ring-white/5 opacity-70'"
                          [attr.aria-label]="isSourceCited(msg, i + 1) ? 'Cited source' : 'Retrieved but not cited in answer'"
                        >
                          <div class="flex items-center gap-2 mb-0.5">
                            <span
                              [class]="isSourceCited(msg, i + 1)
                                ? 'w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-mono shrink-0 bg-brand-500/25 text-brand-400'
                                : 'w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-mono shrink-0 bg-white/5 text-gray-400'"
                            >
                              {{ i + 1 }}
                            </span>
                            @if (!isSourceCited(msg, i + 1)) {
                              <span
                                class="text-[9px] uppercase tracking-wider text-gray-500 font-mono shrink-0"
                                title="This chunk was retrieved but the model did not cite it"
                              >
                                not cited
                              </span>
                            }
                            <span class="font-medium text-gray-900 dark:text-white truncate">
                              {{ sourceTitle(src) }}
                            </span>
                            @if (sourceLocator(src); as loc) {
                              <span
                                class="font-mono text-[10px] text-brand-400/80 shrink-0"
                                [title]="loc.tooltip"
                              >
                                · {{ loc.label }}
                              </span>
                            }
                            @if (sourceCollection(src); as col) {
                              <span
                                class="text-[9px] uppercase tracking-wider text-gray-500 font-mono shrink-0"
                              >
                                {{ col }}
                              </span>
                            }
                            @if (src.score != null) {
                              <span
                                class="ml-auto font-mono text-[10px] text-emerald-500 dark:text-emerald-400 shrink-0"
                              >
                                {{ scoreDisplay(src.score) }}
                              </span>
                            }
                          </div>
                          @if (sourceSnippet(src); as snippet) {
                            <p class="text-[11px] text-gray-600 dark:text-gray-400 leading-relaxed line-clamp-3">
                              {{ snippet }}
                            </p>
                          }
                        </li>
                      }
                    </ol>
                  }
                </div>
              }

              <!-- Task summary -->
              @if (msg.decisionSteps && msg.decisionSteps.length > 0) {
                <div
                  class="ml-0 mt-1 rounded-md px-3 py-2 bg-gradient-to-r from-brand-500/5 to-violet-500/5 ring-1 ring-brand-500/15 flex items-center gap-3 text-[11px] text-gray-700 dark:text-gray-300"
                >
                  <app-icon name="circle-dot" [size]="11" class="text-brand-400 shrink-0" />
                  <span class="font-medium">
                    {{ msg.decisionSteps.length }} step{{ msg.decisionSteps.length > 1 ? 's' : '' }}
                  </span>
                  @if (msg.durationMs) {
                    <span class="font-mono text-gray-500">· {{ msg.durationMs }}ms</span>
                  }
                  @if (msg.sources?.length) {
                    <span class="font-mono text-gray-500">· {{ msg.sources!.length }} sources</span>
                  }
                  @if (msg.ragMode) {
                    <span
                      class="font-mono text-[10px] px-1.5 py-0.5 rounded-full bg-brand-500/10 text-brand-400 border border-brand-500/20"
                      title="Retrieval mode override"
                    >
                      {{ msg.ragMode!.toUpperCase() }}
                    </span>
                  }
                  @if (msg.promptType) {
                    <span
                      class="font-mono text-[10px] px-1.5 py-0.5 rounded-full bg-violet-500/10 text-violet-300 border border-violet-500/20"
                      title="Reasoning template"
                    >
                      {{ msg.promptType }}
                    </span>
                  }
                  @if (msg.evaluation) {
                    <span class="font-mono text-emerald-500 dark:text-emerald-400">
                      · {{ msg.evaluation.composite_score.toFixed(1) }}/100
                    </span>
                  }
                  <a
                    routerLink="/runs"
                    class="ml-auto text-brand-500 hover:text-brand-400 inline-flex items-center gap-1"
                  >
                    <app-icon name="git-commit" [size]="11" />
                    Runs
                  </a>
                  <a
                    routerLink="/observability"
                    class="text-brand-500 hover:text-brand-400 inline-flex items-center gap-1"
                  >
                    <app-icon name="activity" [size]="11" />
                    Quality
                  </a>
                </div>
              }

              <!-- Post-chat audit toolbar -->
              <div class="flex items-center gap-1.5 ml-2 text-[11px] text-gray-500">
                <button
                  type="button"
                  class="p-1 rounded hover:bg-white/5 transition"
                  [class.text-emerald-400]="msg.feedback === 'up'"
                  title="Helpful"
                  (click)="rate(msg, 'up')"
                >
                  <app-icon name="thumbs-up" [size]="12" />
                </button>
                <button
                  type="button"
                  class="p-1 rounded hover:bg-white/5 transition"
                  [class.text-red-400]="msg.feedback === 'down'"
                  title="Not helpful"
                  (click)="rate(msg, 'down')"
                >
                  <app-icon name="thumbs-down" [size]="12" />
                </button>
                <button
                  type="button"
                  class="p-1 rounded hover:bg-white/5 transition"
                  title="Copy response"
                  (click)="copy(msg.content)"
                >
                  <app-icon name="copy" [size]="12" />
                </button>
                <button
                  type="button"
                  class="p-1 rounded hover:bg-white/5 transition flex items-center gap-1"
                  title="Fact-check with LLM-as-Judge"
                  [disabled]="evaluatingId() === msg.id"
                  (click)="factCheck(msg)"
                >
                  @if (evaluatingId() === msg.id) {
                    <app-icon name="loader-2" [size]="12" class="animate-spin" />
                    <span>Scoring…</span>
                  } @else {
                    <app-icon name="shield-check" [size]="12" />
                    <span>Fact-check</span>
                  }
                </button>
                @if (msg.evaluation) {
                  <span class="ml-auto font-mono text-[10px] text-emerald-400"
                    >Score {{ msg.evaluation.composite_score.toFixed(1) }}</span
                  >
                }
              </div>

              @if (msg.evaluation?.claim_audit?.claims?.length) {
                <div class="ml-2 mt-1 rounded-md bg-white/[0.02] border border-white/5 p-2.5 space-y-1">
                  <div
                    class="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1"
                  >
                    Claim audit
                  </div>
                  @for (c of msg.evaluation!.claim_audit!.claims!; track $index) {
                    <div class="flex items-start gap-2 text-[11px]">
                      <span
                        class="w-1.5 h-1.5 rounded-full mt-1.5 shrink-0"
                        [class.bg-emerald-400]="c.verdict === 'supported'"
                        [class.bg-amber-400]="c.verdict === 'partial'"
                        [class.bg-red-400]="c.verdict === 'unsupported'"
                      ></span>
                      <span class="flex-1 text-gray-300">{{ c.text }}</span>
                      <span class="font-mono text-gray-500">{{ c.score }}%</span>
                    </div>
                  }
                </div>
              }
            </div>
          }
        }

        <!-- Live streaming -->
        @if (streaming()) {
          <div class="flex flex-col gap-2">
            @if (liveSteps().length > 0) {
              <div class="space-y-1">
                @for (step of liveSteps(); track step.id) {
                  <div
                    class="flex items-center gap-2 rounded-md px-2.5 py-1.5 text-[11px] border"
                    [class.border-emerald-500\\/20]="step.status === 'completed'"
                    [class.bg-emerald-500\\/5]="step.status === 'completed'"
                    [class.border-brand-500\\/30]="step.status === 'active'"
                    [class.bg-brand-500\\/5]="step.status === 'active'"
                    [class.border-white\\/5]="!step.status || step.status === 'pending'"
                  >
                    <app-icon
                      [name]="iconFor(step)"
                      [size]="12"
                      [class.text-emerald-400]="step.status === 'completed'"
                      [class.text-brand-400]="step.status === 'active'"
                      [class.text-gray-500]="!step.status || step.status === 'pending'"
                      [class.animate-spin]="step.status === 'active'"
                    />
                    <span class="font-medium text-white">{{
                      step.title || step.type || 'Step'
                    }}</span>
                    @if (step.status === 'completed' && step.duration) {
                      <span class="text-[10px] font-mono text-gray-500 ml-auto"
                        >{{ step.duration }}ms</span
                      >
                    } @else if (step.status === 'active') {
                      <span class="text-[9px] uppercase tracking-wider text-brand-400 ml-auto"
                        >running</span
                      >
                    }
                  </div>
                }
              </div>
            }
            <div class="flex justify-start">
              <div
                class="max-w-[85%] bg-gray-100 dark:bg-white/[0.04] rounded-2xl rounded-bl-sm px-4 py-2.5 text-sm whitespace-pre-wrap leading-relaxed ring-1 ring-white/5"
              >
                {{ streamBuffer() }}<span class="inline-block w-1.5 h-4 bg-brand-400 ml-0.5 animate-pulse align-middle"></span>
              </div>
            </div>
          </div>
        }
      </div>

      <!-- Input -->
      <form
        (ngSubmit)="send()"
        class="flex items-end gap-2 p-3 border-t border-white/5 bg-white/[0.02]"
      >
        <button
          type="button"
          class="p-2.5 rounded-xl transition ring-1 relative"
          [class.bg-red-500\\/20]="recording()"
          [class.ring-red-500\\/40]="recording()"
          [class.text-red-300]="recording()"
          [class.bg-brand-500\\/20]="transcribing()"
          [class.ring-brand-500\\/40]="transcribing()"
          [class.text-brand-300]="transcribing()"
          [class.animate-pulse]="transcribing()"
          [class.bg-white\\/5]="!recording() && !transcribing()"
          [class.ring-white\\/10]="!recording() && !transcribing()"
          [class.text-gray-300]="!recording() && !transcribing()"
          [disabled]="transcribing()"
          [title]="transcribing() ? 'Transcribing…' : (recording() ? 'Stop recording' : 'Record voice')"
          (click)="toggleMic()"
        >
          <app-icon
            [name]="transcribing() ? 'loader-2' : (recording() ? 'square' : 'mic')"
            [size]="15"
            [class.animate-spin]="transcribing()"
          />
        </button>
        <textarea
          #inputEl
          [(ngModel)]="userInput"
          name="userInput"
          rows="1"
          class="flex-1 resize-none px-4 py-2.5 bg-white dark:bg-white/5 border border-gray-200 dark:border-white/10 rounded-xl focus:outline-none focus:ring-2 focus:ring-brand-400 text-sm max-h-32"
          placeholder="Ask anything… (Shift+Enter for newline)"
          [disabled]="streaming()"
          (keydown)="onKey($event)"
        ></textarea>
        <button
          type="submit"
          [disabled]="streaming() || !userInput.trim()"
          class="px-4 py-2.5 bg-brand-500 hover:bg-brand-600 disabled:opacity-50 text-white rounded-xl transition text-sm font-medium flex items-center gap-1.5"
        >
          <app-icon [name]="streaming() ? 'loader-2' : 'send'" [size]="14" [class.animate-spin]="streaming()" />
          {{ streaming() ? 'Streaming' : 'Send' }}
        </button>
      </form>
    </div>
  `,
})
export class ChatPanelComponent {
  /**
   * System id to scope the chat to. Optional since Vague D / D0 — the
   * `/chat` workspace surface mounts this component in *Quick ask* mode
   * with no system selected, in which case the backend falls back to
   * workspace defaults. Audit events still carry the id (or `null`) so
   * downstream analytics can bucket conversations by system.
   */
  readonly systemId = input<string | null>(null);
  /**
   * Optional ephemeral Context id (drop-and-ask). When set, the chat
   * automatically attaches the context ids to every outgoing query so
   * the orchestrator knows to ground answers on the dropped documents.
   */
  readonly contextId = input<string | null>(null);

  private readonly sse = inject(SseService);
  private readonly api = inject(ApiService);
  private readonly canonicalApi = inject(CanonicalApiService);
  private readonly toast = inject(ToastrService);
  private readonly router = inject(Router);
  private readonly health = inject(RuntimeHealthService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly cdr = inject(ChangeDetectorRef);
  readonly settings = inject(SettingsService);

  messages = signal<ChatMessage[]>([]);
  streaming = signal(false);
  streamBuffer = signal('');
  liveSteps = signal<DecisionStep[]>([]);
  evaluatingId = signal<string | null>(null);
  userInput = '';

  readonly ragModeChoices = RAG_MODE_CHOICES;
  readonly ragModeOverride = signal<RagModeChoice>('auto');
  readonly promptType = signal<string>('auto');
  readonly reasoningTemplates = signal<ReasoningTemplate[]>([]);

  readonly ragModeHint = computed(() => {
    const slug = this.ragModeOverride();
    return this.ragModeChoices.find((m) => m.slug === slug)?.hint ?? '';
  });

  readonly ragModeRuntimeStatus = computed(() => {
    const slug = this.ragModeOverride();
    const presetId = RAG_SLUG_TO_PRESET[slug] ?? 'None';
    return this.health.presetStatus(presetId);
  });

  readonly promptTypeHint = computed(() => {
    const slug = this.promptType();
    if (slug === 'auto') return 'Heuristic selector picks the template per query';
    return this.reasoningTemplates().find((t) => t.slug === slug)?.description ?? '';
  });

  recording = signal(false);
  /**
   * True between the moment the user stops recording and the
   * transcription response lands. Drives a pulse state on the mic
   * button so the user knows we're waiting on Whisper rather than
   * assuming the app froze.
   */
  transcribing = signal(false);
  ttsEnabled = signal(false);

  private readonly openTrails = signal<Set<string>>(new Set());
  private readonly openSources = signal<Set<string>>(new Set());
  /**
   * Expanded evaluation steps, keyed by ``"${messageId}:${stepId}"``. Kept
   * separate from ``openTrails`` so operators can dive into a specific
   * metric card without expanding every other step below it.
   */
  private readonly openEvals = signal<Set<string>>(new Set());
  private mediaRecorder: MediaRecorder | null = null;
  private recordedChunks: Blob[] = [];
  private currentAudio: HTMLAudioElement | null = null;
  private streamStart = 0;

  // TTS pipeline state — we flush completed sentences from the LLM
  // stream to OpenAI TTS as they come in, then play the resulting MP3
  // chunks sequentially so the user hears the first sentence while the
  // model is still generating the last one.
  private ttsFlushedIdx = 0;
  private ttsQueue: HTMLAudioElement[] = [];
  private ttsPlaying = false;
  private ttsAborted = false;
  /**
   * Signals reflecting TTS transport state so the template can show a
   * pause/resume button only while audio is actually being played or
   * queued up. ``ttsSpeaking`` is OR of (currentAudio active || queue
   * non-empty); ``ttsPaused`` flips when the user hits pause/resume.
   */
  readonly ttsSpeaking = signal(false);
  readonly ttsPaused = signal(false);

  readonly suggestions: SuggestionCard[] = [
    {
      icon: 'file-search',
      label: 'Summarize corpus',
      prompt: 'Summarize the most important findings across my indexed documents.',
    },
    {
      icon: 'compass',
      label: 'Explore entities',
      prompt: 'What are the key people, organizations and topics mentioned recently?',
    },
    {
      icon: 'binary',
      label: 'Cite sources',
      prompt: 'Answer with exact quotes and cite the source documents you used.',
    },
    {
      icon: 'shield-check',
      label: 'Policy check',
      prompt: 'Is there any compliance risk in my recent knowledge base updates?',
    },
  ];

  constructor() {
    this.settings.refresh();
    this.health.load().subscribe();
    this.loadReasoningTemplates();
    this.destroyRef.onDestroy(() => {
      this.currentAudio?.pause();
      if (this.mediaRecorder?.state === 'recording') this.mediaRecorder.stop();
    });
  }

  private loadReasoningTemplates(): void {
    this.api
      .get<{ templates: ReasoningTemplate[] }>('/reasoning/templates')
      .subscribe({
        next: (res) => this.reasoningTemplates.set(res?.templates ?? []),
        error: () => this.reasoningTemplates.set([]),
      });
  }

  isTrailOpen(id: string): boolean {
    return this.openTrails().has(id);
  }

  toggleTrail(id: string): void {
    const next = new Set(this.openTrails());
    if (next.has(id)) next.delete(id);
    else next.add(id);
    this.openTrails.set(next);
  }

  isSourcesOpen(id: string): boolean {
    return this.openSources().has(id);
  }

  toggleSources(id: string): void {
    const next = new Set(this.openSources());
    if (next.has(id)) next.delete(id);
    else next.add(id);
    this.openSources.set(next);
  }

  // ─── Evaluation step expand/render helpers ──────────────────────────
  /** Any step with a structured ``metrics`` dict is treated as evaluable. */
  isEvaluationStep(step: DecisionStep): boolean {
    return !!step.metrics && Object.keys(step.metrics).length > 0;
  }

  private evalKey(messageId: string, stepId: string): string {
    return `${messageId}:${stepId}`;
  }

  isEvalOpen(messageId: string, stepId: string): boolean {
    return this.openEvals().has(this.evalKey(messageId, stepId));
  }

  toggleEval(messageId: string, stepId: string): void {
    const key = this.evalKey(messageId, stepId);
    const next = new Set(this.openEvals());
    if (next.has(key)) next.delete(key);
    else next.add(key);
    this.openEvals.set(next);
  }

  /**
   * Split ``step.metrics`` into quality scores (0-1) and latency measurements
   * (ms). The classification key is the suffix ``_latency``; everything else
   * is rendered as a bar. This keeps the heuristic robust even when a score
   * metric legitimately evaluates to 0.00 (e.g. factuality = 0).
   */
  scoreMetrics(step: DecisionStep): Array<{ key: string; value: number }> {
    const metrics = step.metrics ?? {};
    return Object.entries(metrics)
      .filter(
        ([k, v]) =>
          typeof v === 'number' && !k.endsWith('_latency') && k !== 'duration',
      )
      .map(([key, value]) => ({ key, value: value as number }));
  }

  latencyMetrics(step: DecisionStep): Array<{ key: string; value: number }> {
    const metrics = step.metrics ?? {};
    return Object.entries(metrics)
      .filter(([k, v]) => typeof v === 'number' && k.endsWith('_latency'))
      .map(([key, value]) => ({ key, value: value as number }));
  }

  /** Human-friendly label for a metric key (``adv_hhem`` → ``Adv HHEM``). */
  metricLabel(key: string): string {
    const cleaned = key.replace(/_/g, ' ').trim();
    return cleaned
      .split(' ')
      .map((w) =>
        w === 'hhem' || w === 'llm' ? w.toUpperCase() : w.charAt(0).toUpperCase() + w.slice(1),
      )
      .join(' ');
  }

  /** Resolve the declarative spec for a metric (falls back to defaults). */
  metricSpec(key: string): MetricSpec {
    return METRIC_REGISTRY[key] ?? DEFAULT_METRIC_SPEC;
  }

  /**
   * Normalise a raw metric value into a "quality in [0..1]" where 1 means
   * "as good as it gets". This is what drives both the bar width and the
   * color bucket, so metrics with different ranges/polarities remain
   * comparable on the same UI grid.
   */
  metricQuality(key: string, value: number): number {
    const spec = this.metricSpec(key);
    const max = spec.max || 1;
    const clamped = Math.max(0, Math.min(value, max));
    const fraction = clamped / max;
    return spec.polarity === 'lower' ? 1 - fraction : fraction;
  }

  /**
   * Tailwind class bundles for the score rows. Works off the normalised
   * quality so that:
   *  - HHEM = 0.50 (perfect grounding, formula ceiling) → emerald
   *  - hallucination_rate = 0.05 (tiny rate) → emerald
   *  - factuality = 0.00 (no claim to ground) → gray (null / no-signal)
   */
  scoreTone(
    key: string,
    value: number,
  ): {
    bar: string;
    barBg: string;
    text: string;
    dot: string;
    label: 'good' | 'fair' | 'poor' | 'null';
  } {
    const spec = this.metricSpec(key);
    // Raw 0 on a "higher is better" metric is the evaluator's "no signal"
    // default (e.g. factuality when nothing was retrieved). Painting it
    // red would over-signal a problem we never actually detected.
    if (spec.polarity === 'higher' && value <= 0) {
      return {
        bar: 'bg-gray-500/50',
        barBg: 'bg-gray-500/10',
        text: 'text-gray-400',
        dot: 'bg-gray-500',
        label: 'null',
      };
    }
    const quality = this.metricQuality(key, value);
    if (quality >= spec.good) {
      return {
        bar: 'bg-emerald-500/70',
        barBg: 'bg-emerald-500/10',
        text: 'text-emerald-400',
        dot: 'bg-emerald-500',
        label: 'good',
      };
    }
    if (quality >= spec.fair) {
      return {
        bar: 'bg-amber-500/70',
        barBg: 'bg-amber-500/10',
        text: 'text-amber-400',
        dot: 'bg-amber-500',
        label: 'fair',
      };
    }
    return {
      bar: 'bg-red-500/70',
      barBg: 'bg-red-500/10',
      text: 'text-red-400',
      dot: 'bg-red-500',
      label: 'poor',
    };
  }

  /** Fraction [0..1] driving the bar fill width (normalised by spec.max). */
  barFraction(key: string, value: number): number {
    return this.metricQuality(key, value);
  }

  /** Aggregate quality hint used in the collapsed row (e.g. 3 good / 2 null). */
  scoreSummary(step: DecisionStep): string {
    const buckets: Record<'good' | 'fair' | 'poor' | 'null', number> = {
      good: 0,
      fair: 0,
      poor: 0,
      null: 0,
    };
    for (const m of this.scoreMetrics(step)) {
      buckets[this.scoreTone(m.key, m.value).label] += 1;
    }
    const parts: string[] = [];
    if (buckets.good) parts.push(`${buckets.good} good`);
    if (buckets.fair) parts.push(`${buckets.fair} fair`);
    if (buckets.poor) parts.push(`${buckets.poor} poor`);
    if (buckets.null) parts.push(`${buckets.null} null`);
    return parts.join(' · ');
  }

  /** Inline "1170ms" formatter for latency pills. */
  formatLatency(ms: number): string {
    if (ms >= 10_000) return `${(ms / 1000).toFixed(1)}s`;
    if (ms >= 1_000) return `${(ms / 1000).toFixed(2)}s`;
    return `${Math.round(ms)}ms`;
  }

  // ─── Inline citation rendering ───────────────────────────────────────
  /**
   * Split an assistant answer into plain-text runs and citation markers
   * so the template can render ``[N]`` as clickable chips wired to the
   * ``sources`` panel. Supports stacked refs like ``[1][2][3]`` and also
   * the ``[1, 2]`` form sometimes produced by models.
   */
  renderAnswer(content: string | undefined | null): AnswerToken[] {
    if (!content) return [{ kind: 'text', value: '(no response)' }];
    const tokens: AnswerToken[] = [];
    const re = /\[(\d+(?:\s*,\s*\d+)*)\]/g;
    let last = 0;
    for (const m of content.matchAll(re)) {
      const idx = m.index ?? 0;
      if (idx > last) {
        tokens.push({ kind: 'text', value: content.slice(last, idx) });
      }
      for (const part of m[1].split(',')) {
        const n = parseInt(part.trim(), 10);
        if (Number.isFinite(n) && n > 0) tokens.push({ kind: 'cite', n });
      }
      last = idx + m[0].length;
    }
    if (last < content.length) {
      tokens.push({ kind: 'text', value: content.slice(last) });
    }
    return tokens.length ? tokens : [{ kind: 'text', value: content }];
  }

  /** DOM id we attach to each source ``<li>`` so chips can scroll to it. */
  sourceDomId(msgId: string, n: number): string {
    return `msg-${msgId}-src-${n}`;
  }

  /** Whether a citation ``[n]`` resolves to a real entry in ``msg.sources``. */
  isValidCitation(msg: ChatMessage, n: number): boolean {
    return !!msg.sources && n >= 1 && n <= msg.sources.length;
  }

  /**
   * Set of citation indices that the model cited but that are out of
   * range of ``msg.sources`` (empty list or fewer entries than expected).
   * Used to surface a "hallucinated references" banner so operators do
   * not have to eyeball disabled chips to realise no retrieval landed.
   */
  missingCitations(msg: ChatMessage): number[] {
    if (!msg.content) return [];
    const available = msg.sources?.length ?? 0;
    const seen = new Set<number>();
    for (const tok of this.renderAnswer(msg.content)) {
      if (tok.kind === 'cite' && tok.n > available) seen.add(tok.n);
    }
    return Array.from(seen).sort((a, b) => a - b);
  }

  /**
   * Set of source indices (1-based) that the assistant actually cited in
   * the answer body. Used to visually distinguish cited sources from
   * retrieved-but-unused context in the Sources panel — otherwise 5
   * entries for 2 chips reads like "duplicates".
   */
  private citedIndicesCache = new Map<string, Set<number>>();
  citedIndices(msg: ChatMessage): Set<number> {
    const key = `${msg.id}:${(msg.content ?? '').length}`;
    const cached = this.citedIndicesCache.get(key);
    if (cached) return cached;
    const set = new Set<number>();
    for (const tok of this.renderAnswer(msg.content)) {
      if (tok.kind === 'cite') set.add(tok.n);
    }
    this.citedIndicesCache.set(key, set);
    return set;
  }

  isSourceCited(msg: ChatMessage, index1Based: number): boolean {
    return this.citedIndices(msg).has(index1Based);
  }

  /** Short preview shown in a chip's native ``title`` tooltip on hover. */
  citationTooltip(msg: ChatMessage, n: number): string {
    const src = msg.sources?.[n - 1];
    if (!src) return `Source [${n}] — not available`;
    const title = this.sourceTitle(src);
    const loc = this.sourceLocator(src);
    return loc ? `${title} · ${loc.label}` : title;
  }

  /**
   * Open the sources panel for this message and scroll the clicked
   * citation target into view with a brief highlight ring. Defensive:
   * no-op if the citation index is out of bounds.
   */
  gotoSource(msg: ChatMessage, n: number): void {
    if (!this.isValidCitation(msg, n)) return;
    if (!this.isSourcesOpen(msg.id)) this.toggleSources(msg.id);
    setTimeout(() => {
      const el = document.getElementById(this.sourceDomId(msg.id, n));
      if (!el) return;
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el.classList.add('ring-brand-400', 'ring-2');
      setTimeout(() => el.classList.remove('ring-brand-400', 'ring-2'), 1600);
    }, 50);
  }

  sourceTitle(src: Source): string {
    return (
      (src.title as string | undefined) ||
      (src.filename as string | undefined) ||
      (src.document_id as string | undefined) ||
      ((src.metadata as any)?.title as string | undefined) ||
      ((src.metadata as any)?.filename as string | undefined) ||
      'Source'
    );
  }

  sourceCollection(src: Source): string {
    return (
      (src.collection as string | undefined) ||
      (src.collection_name as string | undefined) ||
      ((src.metadata as any)?.collection as string | undefined) ||
      ''
    );
  }

  /**
   * Produce a compact locator chip to disambiguate sources that share a
   * title. Prefers an actual page number (``p. 4``), then a chunk
   * identifier, then the short document id. Returns ``null`` when we
   * have no extra info to display — caller omits the chip entirely.
   */
  sourceLocator(src: Source): { label: string; tooltip: string } | null {
    const meta = (src.metadata ?? {}) as Record<string, unknown>;
    const page = (src.page as number | string | undefined) ?? (meta['page'] as number | string | undefined);
    if (page !== undefined && page !== null && `${page}`.trim() !== '') {
      return { label: `p. ${page}`, tooltip: `Page ${page}` };
    }
    const chunkIdx =
      (src['chunk_index'] as number | undefined) ??
      (meta['chunk_index'] as number | undefined) ??
      (meta['chunk_id'] as number | undefined);
    if (typeof chunkIdx === 'number' && Number.isFinite(chunkIdx)) {
      return { label: `chunk ${chunkIdx}`, tooltip: `Chunk index ${chunkIdx}` };
    }
    const docId = (src.document_id as string | undefined) ?? (meta['document_id'] as string | undefined);
    if (docId && typeof docId === 'string' && docId.length >= 6) {
      return { label: `#${docId.slice(0, 6)}`, tooltip: `Document id ${docId}` };
    }
    return null;
  }

  sourceSnippet(src: Source): string {
    const raw =
      (src.snippet as string | undefined) ||
      (src.content as string | undefined) ||
      (src.text as string | undefined) ||
      '';
    return raw.length > 240 ? raw.slice(0, 240).trim() + '…' : raw;
  }

  scoreDisplay(score: number | undefined): string {
    if (score == null || Number.isNaN(score)) return '';
    return score <= 1 ? (score * 100).toFixed(0) + '%' : score.toFixed(2);
  }

  useSuggestion(s: SuggestionCard): void {
    this.userInput = s.prompt;
    this.send();
  }

  iconFor(step: DecisionStep): string {
    return STEP_ICONS[step.type ?? 'default'] ?? STEP_ICONS['default'];
  }

  onKey(e: KeyboardEvent): void {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      this.send();
    }
  }

  send(): void {
    const text = this.userInput.trim();
    if (!text || this.streaming()) return;

    const userMsg: ChatMessage = {
      id: cryptoId(),
      role: 'user',
      content: text,
    };
    this.messages.update((msgs) => [...msgs, userMsg]);
    this.userInput = '';
    this.streaming.set(true);
    this.streamBuffer.set('');
    this.liveSteps.set([]);
    this.streamStart = Date.now();
    this.resetTtsPipeline();

    const s = this.settings.settings();
    let buffer = '';
    let reasoning: DecisionStep[] = [];
    let sources: Source[] | undefined;

    const ragOverride = this.ragModeOverride();
    const promptTypeSel = this.promptType();
    this.sse
      .stream('/api/v1/chat/stream', {
        query: text,
        agent_id: this.systemId(),
        session_id: null,
        stream: true,
        include_reasoning: true,
        include_sources: true,
        temperature: s.temperature,
        max_tokens: s.maxTokens,
        top_k: s.ragTopK,
        similarity_threshold: s.ragSimilarityThreshold,
        // Per-query retrieval override wins over workspace default.
        rag_pipeline_mode: ragOverride !== 'auto' ? ragOverride : s.ragPipelineMode,
        rag_mode_override: ragOverride !== 'auto' ? ragOverride : null,
        // Per-query reasoning template; "auto" lets the mode_selector decide.
        prompt_type: promptTypeSel !== 'auto' ? promptTypeSel : null,
        system_prompt: (s['systemPrompt'] as string | undefined) ?? null,
        agent_preferences: {
          model_preferences: {
            model: s.defaultModel,
            provider: s.defaultProvider,
          },
        },
      })
      .subscribe({
        next: (chunk: SseChunk) => {
          // Sources can ride along any chunk type (backend attaches them on
          // the first text chunk of the stream). Extract them eagerly so
          // the final assistant message always ends up with the source list
          // even though an `if/else if` cascade is used below.
          if (chunk.sources && Array.isArray(chunk.sources) && chunk.sources.length > 0) {
            sources = chunk.sources as Source[];
          }
          if (chunk.chunk_type === 'text' && typeof chunk.content === 'string') {
            buffer += chunk.content;
            this.streamBuffer.set(buffer);
            if (this.ttsEnabled()) this.maybeFlushSentences(buffer);
          } else if (chunk.chunk_type === 'decision_step' && chunk.decision_step) {
            const step = chunk.decision_step as DecisionStep;
            reasoning = upsertStep(reasoning, step);
            this.liveSteps.set([...reasoning]);
          } else if (chunk.chunk_type === 'error' && chunk.content) {
            buffer += `\n\n⚠ ${chunk.content}`;
            this.streamBuffer.set(buffer);
          } else if (chunk.chunk_type === 'eval_pending' && chunk.run_id) {
            // Backend persisted a Run for this turn and kicked the
            // auto-eval loop; start polling so we can surface a
            // breach-toast within a few seconds of the judge finishing.
            this.startEvalPolling(chunk.run_id);
          } else if (chunk.sources && Array.isArray(chunk.sources)) {
            sources = chunk.sources as Source[];
          } else if (chunk.type === 'done') {
            const durationMs = Date.now() - this.streamStart;
            const assistantId = cryptoId();
            const assistantMsg: ChatMessage = {
              id: assistantId,
              role: 'assistant',
              content: buffer,
              decisionSteps: reasoning.length ? reasoning : undefined,
              sources,
              feedback: null,
              evaluation: null,
              durationMs,
              ragMode: ragOverride !== 'auto' ? ragOverride : null,
              promptType: promptTypeSel !== 'auto' ? promptTypeSel : null,
            };
            this.messages.update((m) => [...m, assistantMsg]);
            this.streaming.set(false);
            this.streamBuffer.set('');
            this.liveSteps.set([]);
            this.persistLastEvalContext(text, buffer);
            this.logAudit('chat_query', {
              message_id: assistantId,
              agent_id: this.systemId(),
              query_length: text.length,
              response_length: buffer.length,
              sources: sources?.length ?? 0,
              steps: reasoning.length,
              duration_ms: durationMs,
            });
            if (this.ttsEnabled() && buffer.trim()) this.flushTrailingTts(buffer);
          }
        },
        error: () => {
          this.toast.error('Connection lost while streaming', 'Chat');
          this.streaming.set(false);
          this.streamBuffer.set('');
          this.liveSteps.set([]);
        },
      });
  }

  clearConversation(): void {
    this.messages.set([]);
    this.streamBuffer.set('');
    this.liveSteps.set([]);
    this.openTrails.set(new Set());
  }

  /**
   * Poll ``/evaluation/by-run/:runId`` until the auto-eval judge has
   * persisted a score or explicitly skipped, then surface a toast
   * when the reply breached the workspace thresholds.
   *
   * Budget: ~30s total (20 attempts × 1.5s). The judge typically
   * lands in 3-6s on GPT-4o-mini; we give it room for a slow cold
   * start without spamming the review queue with retries. A silent
   * ``status: "skipped"`` response ends the loop immediately — those
   * workspaces just haven't turned auto-eval on yet.
   */
  private startEvalPolling(runId: string): void {
    let attempts = 0;
    const maxAttempts = 20;
    const tick = (): void => {
      if (attempts >= maxAttempts) return;
      attempts += 1;
      this.canonicalApi.getEvaluationByRun(runId).subscribe({
        next: (res) => {
          if (!res) return; // network hiccup — stop quietly
          if (res.status === 'pending') {
            window.setTimeout(tick, 1500);
            return;
          }
          if (res.status === 'skipped') return;
          if (res.status === 'completed' && res.breach) {
            this.showBreachToast(res);
          }
        },
        error: () => {
          // Stop polling on hard error — transient 5xx will be
          // retried by the next chat turn's polling loop.
        },
      });
    };
    window.setTimeout(tick, 1500);
  }

  private showBreachToast(res: {
    composite_score?: number;
    reasons?: Array<{ metric: string }>;
    decision_id?: string | null;
    run_id: string;
  }): void {
    const metricList = (res.reasons ?? [])
      .map((r) => r.metric)
      .filter(Boolean)
      .slice(0, 3)
      .join(', ');
    const score = res.composite_score != null ? Math.round(res.composite_score) : '—';
    const title = 'Reply flagged by auto-QA';
    const msg = metricList
      ? `Composite ${score}/100 · breaches: ${metricList} · tap to review`
      : `Composite ${score}/100 · tap to review`;
    const t: ActiveToast<unknown> = this.toast.warning(msg, title, {
      timeOut: 10000,
      closeButton: true,
      tapToDismiss: false,
      enableHtml: false,
    });
    t.onTap.subscribe(() => {
      // Deeplink priority: if the breach already produced a
      // Decision row we jump to the review queue (so the reviewer
      // can accept/reject inline); otherwise we fall back to the
      // Run inspector for raw context.
      if (res.decision_id) {
        this.router.navigate(['/steering', 'review-queue'], {
          queryParams: { decision: res.decision_id },
        });
      } else {
        this.router.navigate(['/runs', res.run_id]);
      }
    });
  }

  rate(msg: ChatMessage, verdict: 'up' | 'down'): void {
    this.messages.update((msgs) =>
      msgs.map((m) => (m.id === msg.id ? { ...m, feedback: verdict } : m)),
    );
    this.toast.success(verdict === 'up' ? 'Marked as helpful' : 'Feedback recorded', 'Thanks');
    this.logAudit('chat_feedback', {
      message_id: msg.id,
      agent_id: this.systemId(),
      verdict,
    });
  }

  copy(text: string): void {
    navigator.clipboard
      .writeText(text)
      .then(() => this.toast.info('Copied to clipboard'))
      .catch(() => this.toast.error('Copy failed'));
  }

  factCheck(msg: ChatMessage): void {
    if (this.evaluatingId()) return;
    const user = this.lastUserMessageBefore(msg.id);
    if (!user) {
      this.toast.warning('No matching query found for this response');
      return;
    }
    this.evaluatingId.set(msg.id);
    this.api
      .post<any>('/evaluation/score', {
        query: user.content,
        response: msg.content,
        agent_id: this.systemId(),
      })
      .subscribe({
        next: (res) => {
          this.messages.update((msgs) =>
            msgs.map((m) => (m.id === msg.id ? { ...m, evaluation: res } : m)),
          );
          this.toast.success(
            `Composite score ${Number(res?.composite_score ?? 0).toFixed(1)}/100`,
            'Fact-check',
          );
          this.logAudit('evaluation_run', {
            message_id: msg.id,
            agent_id: this.systemId(),
            composite_score: Number(res?.composite_score ?? 0),
            hallucination_rate: Number(res?.hallucination_rate ?? 0),
          });
          this.evaluatingId.set(null);
        },
        error: (err) => {
          this.toast.error(err?.error?.detail ?? 'Evaluation failed', 'Fact-check');
          this.evaluatingId.set(null);
        },
      });
  }

  toggleTTS(): void {
    const next = !this.ttsEnabled();
    this.ttsEnabled.set(next);
    this.toast.info(next ? 'Voice output enabled' : 'Voice output disabled');
    if (!next) {
      // Stop any playing audio and drop queued chunks so the user isn't
      // surprised by lagging TTS coming through after they muted.
      this.resetTtsPipeline();
    }
  }

  async toggleMic(): Promise<void> {
    if (this.recording()) {
      this.mediaRecorder?.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
      this.mediaRecorder = recorder;
      this.recordedChunks = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) this.recordedChunks.push(e.data);
      };
      recorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(this.recordedChunks, { type: 'audio/webm' });
        this.recording.set(false);
        this.transcribe(blob);
      };
      recorder.start();
      this.recording.set(true);
    } catch {
      this.toast.error('Microphone access denied', 'Voice');
    }
  }

  private transcribe(blob: Blob): void {
    this.transcribing.set(true);
    this.api.transcribeAudio(blob).subscribe({
      next: (res) => {
        // The response-side mutation of a plain property (``userInput``)
        // doesn't propagate through OnPush change detection on its own
        // — NgModel only re-reads on an input/event tick. We force a
        // re-check so the textarea picks up the transcribed text and
        // emit a small toast when Whisper returned nothing (silence).
        if (res?.text && res.text.trim()) {
          this.userInput = (this.userInput ? this.userInput + ' ' : '') + res.text.trim();
        } else {
          this.toast.info('No speech detected in the recording', 'Voice');
        }
        this.transcribing.set(false);
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.transcribing.set(false);
        this.cdr.markForCheck();
        const detail = err?.error?.detail || err?.message || 'Transcription failed';
        this.toast.error(detail, 'Voice');
      },
    });
  }

  /**
   * Reset the sentence-streaming TTS pipeline at the start of each new
   * answer (or when the user mutes). Stops any playing audio, clears the
   * queue, and arms the abort flag so in-flight HTTP responses drop
   * their blobs instead of auto-playing.
   */
  private resetTtsPipeline(): void {
    this.ttsAborted = true;
    try {
      this.currentAudio?.pause();
    } catch {
      /* ignore */
    }
    this.currentAudio = null;
    this.ttsQueue = [];
    this.ttsPlaying = false;
    this.ttsFlushedIdx = 0;
    this.ttsSpeaking.set(false);
    this.ttsPaused.set(false);
    // Re-open the gate on the next animation frame so freshly-issued
    // requests from the next call to ``send()`` aren't dropped.
    queueMicrotask(() => {
      this.ttsAborted = false;
    });
  }

  /**
   * Pause or resume the currently playing TTS audio. While paused, the
   * chunk queue keeps accepting new MP3s from in-flight requests but
   * they don't start playing until the user hits resume (the current
   * audio's ``onended`` is what drives queue advancement, and a paused
   * audio never fires that event).
   */
  pauseResumeTts(): void {
    if (!this.ttsSpeaking()) return;
    if (this.ttsPaused()) {
      this.currentAudio?.play().catch(() => {
        /* ignore — browser may block autoplay resume */
      });
      this.ttsPaused.set(false);
    } else {
      try {
        this.currentAudio?.pause();
      } catch {
        /* ignore */
      }
      this.ttsPaused.set(true);
    }
  }

  /**
   * Scan the in-flight assistant buffer for the last completed sentence
   * boundary past ``ttsFlushedIdx`` and queue a TTS chunk for it. We
   * only flush when the pending slice is at least 40 chars long to
   * avoid spamming OpenAI with 3-word sentences — a single TTS call
   * with 2 short sentences is both cheaper and less choppy than two.
   */
  private maybeFlushSentences(buffer: string): void {
    const pending = buffer.slice(this.ttsFlushedIdx);
    if (pending.length < 40) return;
    // Match sentence-ending punctuation (accepting trailing quotes/brackets)
    // followed by whitespace.
    const sentenceEnd = /[.!?…]["'\)\]]*(\s|$)/g;
    let lastEnd = -1;
    let m: RegExpExecArray | null;
    while ((m = sentenceEnd.exec(pending)) !== null) {
      lastEnd = m.index + m[0].length;
    }
    if (lastEnd < 40) return;
    const toSend = pending.slice(0, lastEnd).trim();
    this.ttsFlushedIdx += lastEnd;
    if (toSend) this.queueTtsChunk(toSend);
  }

  /**
   * After the LLM stream completes, flush whatever text hasn't yet been
   * sent to TTS — typically the last partial sentence that didn't end
   * with punctuation, or a very short answer that never hit the 40-char
   * threshold.
   */
  private flushTrailingTts(buffer: string): void {
    const remainder = buffer.slice(this.ttsFlushedIdx).trim();
    this.ttsFlushedIdx = buffer.length;
    if (remainder) this.queueTtsChunk(remainder);
  }

  private queueTtsChunk(text: string): void {
    // Strip markdown noise that would be pronounced literally ("star
    // star bold star star"), and cap at the backend limit.
    const clean = text.replace(/[#*_`\[\]|]/g, '').slice(0, 4000);
    if (!clean.trim()) return;
    this.api.synthesizeSpeech(clean).subscribe({
      next: (blob) => {
        if (this.ttsAborted) return;
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        audio.onended = () => {
          URL.revokeObjectURL(url);
          this.ttsPlaying = false;
          this.playNextInQueue();
        };
        audio.onerror = () => {
          URL.revokeObjectURL(url);
          this.ttsPlaying = false;
          this.playNextInQueue();
        };
        this.ttsQueue.push(audio);
        this.ttsSpeaking.set(true);
        if (!this.ttsPlaying && !this.ttsPaused()) this.playNextInQueue();
      },
      error: () => {
        // Skip this chunk and let the next one play. We don't toast —
        // this is non-blocking and toasting on every sentence would be
        // noisy if the quota is hit.
      },
    });
  }

  private playNextInQueue(): void {
    if (this.ttsAborted || this.ttsPaused()) return;
    const next = this.ttsQueue.shift();
    if (!next) {
      // Queue drained and current audio finished — flip the speaking
      // flag so the pause/resume button disappears.
      this.ttsPlaying = false;
      this.ttsSpeaking.set(false);
      return;
    }
    this.ttsPlaying = true;
    this.currentAudio = next;
    this.ttsSpeaking.set(true);
    next.play().catch(() => {
      this.ttsPlaying = false;
      this.playNextInQueue();
    });
  }

  private lastUserMessageBefore(id: string): ChatMessage | undefined {
    const msgs = this.messages();
    const idx = msgs.findIndex((m) => m.id === id);
    for (let i = idx - 1; i >= 0; i--) {
      if (msgs[i].role === 'user') return msgs[i];
    }
    return undefined;
  }

  private logAudit(event_type: string, details: Record<string, unknown>): void {
    this.api
      .post('/audit', {
        event_type,
        actor: 'user',
        details,
        agent_id: this.systemId(),
        severity: 'info',
      })
      .subscribe({
        next: () => {
          /* non-blocking */
        },
        error: () => {
          /* non-blocking */
        },
      });
  }

  private persistLastEvalContext(query: string, response: string): void {
    try {
      localStorage.setItem(
        'agentium:last_eval_context',
        JSON.stringify({ agent_id: this.systemId(), query, response }),
      );
    } catch {
      /* non-blocking */
    }
  }
}

function cryptoId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

function upsertStep(list: DecisionStep[], step: DecisionStep): DecisionStep[] {
  const idx = list.findIndex((s) => s.id === step.id);
  if (idx === -1) return [...list, step];
  const next = list.slice();
  next[idx] = { ...next[idx], ...step };
  return next;
}
