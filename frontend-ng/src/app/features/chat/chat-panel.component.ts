import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router, RouterLink } from '@angular/router';
import { ToastrService, ActiveToast } from 'ngx-toastr';
import { ApiService, VoiceRuntimeCatalog, VoiceRuntimeProviderOption } from '@app/core/api.service';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { SettingsService } from '@app/core/settings.service';
import { SseChunk, SseService } from '@app/core/sse.service';
import { VoiceSessionConnection, VoiceSessionEvent, VoiceSessionService } from '@app/core/voice-session.service';
import {
  VoiceLoopControllerFactory,
  VoiceLoopEndpointReason,
  VoiceLoopState,
} from '@app/core/voice-loop-controller.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { RuntimeHealthService } from '@app/core/runtime-health.service';
import { WorkspaceService } from '@app/core/workspace.service';
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
  mapCommand?: Record<string, unknown>;
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

type VoiceOracleStage = 'idle' | 'listening' | 'thinking' | 'committed' | 'superseded' | 'fallback' | 'error';

interface SuggestionCard {
  icon: string;
  label: string;
  prompt: string;
  scope_key?: string;
  knowledge_scope?: string;
  source_key?: string;
  context_mode?: SessionDocsMode | 'any';
}

interface AssistantProfile {
  key: string;
  label?: string;
  subtitle?: string;
  default_knowledge_scope?: string;
  executive_mode?: boolean;
  showcase_mode?: string;
  design_mode?: string;
  tone?: string;
  prompt_pack?: SuggestionCard[];
  hidden_controls?: string[];
  chat?: WorkspaceChatConfig;
  voice_loop?: WorkspaceVoiceLoopConfig;
}

interface KnowledgeScopeOption {
  key: string;
  label?: string;
  description?: string;
  is_default?: boolean;
  collection_slugs?: string[];
}

type SourceSelection = 'auto' | 'workspace_default' | string;
type SessionDocsMode = 'replace' | 'combine';

interface WorkspaceChatConfig {
  title?: string;
  subtitle?: string;
  placeholder?: string;
  prompt_pack?: SuggestionCard[];
  prompt_pack_by_scope?: Record<string, SuggestionCard[]>;
  session_doc_prompt_pack?: SuggestionCard[];
  use_assistant_profile_prompt_pack?: boolean;
}

type VoiceLoopDefaultMode = 'batch' | 'session_loop' | 'realtime';

interface WorkspaceVoiceLoopConfig {
  default_mode?: VoiceLoopDefaultMode;
  enabled_default?: boolean;
  auto_send_final_transcript?: boolean;
  auto_endpoint?: boolean;
  auto_rearm_after_tts?: boolean;
  barge_in?: boolean;
  commands_enabled?: boolean;
  trigger_word?: string | null;
  command_packs?: string[];
  stop_phrases?: string[];
  silence_ms?: number;
  min_speech_ms?: number;
  max_turn_ms?: number;
  cooldown_ms?: number;
  rms_threshold?: number;
}

function isSentinelShowcaseProfile(profile: AssistantProfile | null): boolean {
  if (!profile) return false;
  return profile.key === 'vigie_executive'
    || profile.showcase_mode === 'sentinel_ci'
    || profile.design_mode === 'sentinel_ci'
    || profile.tone === 'ministerial';
}

interface ReasoningTemplate {
  slug: string;
  label: string;
  description: string;
}

type RagModeChoice = 'auto' | 'naive' | 'hybrid' | 'hah' | 'chah';
type VoiceTransportChoice = 'batch_http' | 'backend_ws';

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
      @if (executiveMode()) {
        <div class="vigie-context-bar">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <div class="vigie-kicker">
                Briefing souverain
              </div>
              <div class="vigie-scope-line">
                Sources qualifiées · Presse, projets, agenda, carte et observations
              </div>
            </div>
            <button
              type="button"
              class="vigie-trace-button"
              (click)="traceOpen.set(!traceOpen())"
              [title]="traceOpen() ? 'Masquer les paramètres avancés' : 'Afficher traçabilité et paramètres avancés'"
            >
              <app-icon name="sliders-horizontal" [size]="13" />
              Traçabilité
            </button>
          </div>
        </div>
      }

      @if (!executiveMode() || traceOpen()) {
      <!-- Toolbar -->
      <div class="chat-control-bar">
        <div class="chat-control-main">
          <div
            class="chat-mode-chip"
            title="Chat runtime used for answer generation. Provider details are hidden in demo-safe presentation."
          >
            <app-icon name="circle-dot" [size]="12" class="text-emerald-400" />
            <span>Chat</span>
            <span class="chat-mode-model">{{ chatRuntimeLabel() }}</span>
          </div>

          @if (knowledgeScopeOptions().length > 0) {
            <div class="source-picker" [title]="assistantScopeLabel()">
              <span class="source-picker-label">
                <app-icon name="database" [size]="12" />
                Knowledge
                <span
                  class="control-info-dot"
                  title="Select the workspace Knowledge source searched by retrieval. Auto uses the assistant profile default when available, otherwise the workspace default."
                >
                  <app-icon name="info" [size]="10" />
                </span>
              </span>
              <div class="source-picker-select-wrap">
                <select
                  class="source-picker-select"
                  [ngModel]="selectedSource()"
                  (ngModelChange)="onSourceSelectionChange($event)"
                >
                  <option value="auto">Auto · {{ autoSourceLabel() }}</option>
                  <option value="workspace_default">Workspace default</option>
                  @for (scope of knowledgeScopeOptions(); track scope.key) {
                    <option [value]="scope.key">{{ scope.label || scope.key }}</option>
                  }
                </select>
                <app-icon name="chevron-down" [size]="12" class="source-picker-chevron" />
              </div>
            </div>
            <span class="text-gray-600">·</span>
          }

          @if (contextId()) {
            <div class="session-doc-mode" title="Choose whether uploaded session documents replace or complement the selected Knowledge source.">
              <span class="session-doc-label">
                <app-icon name="files" [size]="12" />
                Session docs
                <span
                  class="control-info-dot"
                  title="Only searches uploaded session docs. + Knowledge searches session docs plus the selected Knowledge source."
                >
                  <app-icon name="info" [size]="10" />
                </span>
              </span>
              <button
                type="button"
                class="session-doc-mode-button"
                [class.session-doc-mode-active]="sessionDocsMode() === 'replace'"
                (click)="setSessionDocsMode('replace')"
              >
                Only
              </button>
              <button
                type="button"
                class="session-doc-mode-button"
                [class.session-doc-mode-active]="sessionDocsMode() === 'combine'"
                (click)="setSessionDocsMode('combine')"
              >
                + Knowledge
              </button>
            </div>
            <span class="text-gray-600">·</span>
          }

          <div class="mini-control" [title]="ragModeHint()">
            <span class="mini-control-label">
              Retrieval
              <span
                class="control-info-dot"
                title="Choose how Agentium searches indexed Knowledge for this question. Auto follows workspace/source defaults."
              >
                <app-icon name="info" [size]="10" />
              </span>
            </span>
            <div class="mini-select-wrap">
              <select
                class="mini-select"
                [ngModel]="ragModeOverride()"
                (ngModelChange)="ragModeOverride.set($event)"
              >
                @for (m of ragModeChoices; track m.slug) {
                  <option [value]="m.slug">{{ m.label }}</option>
                }
              </select>
              <app-icon name="chevron-down" [size]="12" class="mini-select-chevron" />
            </div>
            @if (ragModeOverride() !== 'auto') {
              <ck-runtime-status [status]="ragModeRuntimeStatus()" />
            }
          </div>

          <div class="mini-control" [title]="promptTypeHint()">
            <span class="mini-control-label">
              Reasoning
              <span
                class="control-info-dot"
                title="Choose the answer framing. Auto lets Agentium infer the best reasoning template from the question."
              >
                <app-icon name="info" [size]="10" />
              </span>
            </span>
            <div class="mini-select-wrap">
              <select
                class="mini-select"
                [ngModel]="promptType()"
                (ngModelChange)="promptType.set($event)"
              >
                <option value="auto">Auto</option>
                @for (t of reasoningTemplates(); track t.slug) {
                  <option [value]="t.slug">{{ t.label }}</option>
                }
              </select>
              <app-icon name="chevron-down" [size]="12" class="mini-select-chevron" />
            </div>
          </div>
        </div>
        <div class="chat-control-actions">
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
      }

      @if (!executiveMode() || traceOpen()) {
      <div class="voice-control-bar">
        <div class="voice-control-group">
          <span class="voice-control-label">
            <app-icon name="waves" [size]="13" class="text-brand-300" />
            Voice runtime
            <span
              class="control-info-dot"
              title="Select the voice provider/runtime used for speech-to-text and voice session events."
            >
              <app-icon name="info" [size]="10" />
            </span>
          </span>
          <div class="voice-select-wrap" [title]="selectedVoiceDescription()">
            <select
              class="voice-select"
              [ngModel]="voiceProvider()"
              (ngModelChange)="onVoiceProviderChange($event)"
            >
              @for (runtime of voiceRuntimeOptions(); track runtime.slug) {
                <option
                  [value]="runtime.slug"
                  [disabled]="!isVoiceRuntimeSelectableInChat(runtime)"
                >
                  {{ voiceRuntimeLabel(runtime) }}
                </option>
              }
            </select>
            <app-icon name="chevron-down" [size]="12" class="voice-select-chevron" />
          </div>
        </div>
        <div class="voice-transport-toggle" [title]="voiceTransportHint()">
          <button
            type="button"
            class="voice-transport-button"
            [class.voice-transport-active]="voiceTransport() === 'batch_http'"
            (click)="setVoiceTransport('batch_http')"
            title="Record one audio segment, then transcribe through /voice/transcribe."
          >
            Batch
          </button>
          <button
            type="button"
            class="voice-transport-button"
            [class.voice-transport-active]="voiceTransport() === 'backend_ws'"
            [disabled]="!canUseVoiceSession()"
            (click)="setVoiceTransport('backend_ws')"
            [title]="voiceSessionButtonTitle()"
          >
            Session loop
          </button>
          <button
            type="button"
            class="voice-transport-button"
            disabled
            [title]="voiceRealtimeBlockedHint() || 'Realtime voice uses WebRTC and is enabled only when the workspace/provider lane is ready.'"
          >
            Realtime
          </button>
        </div>
        @if (voiceTransport() === 'backend_ws') {
          <div class="voice-loop-actions" title="Start or pause a hands-free Agentium voice session. The microphone rearms after the spoken answer.">
            @if (!voiceConversationActive()) {
              <button
                type="button"
                class="voice-loop-button voice-loop-start"
                [disabled]="!canUseVoiceSession() || streaming() || transcribing()"
                (click)="startConversationLoop()"
              >
                <app-icon name="play" [size]="12" />
                Start conversation
              </button>
            } @else {
              <button
                type="button"
                class="voice-loop-button"
                [disabled]="transcribing()"
                (click)="voiceConversationPaused() ? resumeConversationLoop() : pauseConversationLoop()"
              >
                <app-icon [name]="voiceConversationPaused() ? 'play' : 'pause'" [size]="12" />
                {{ voiceConversationPaused() ? 'Resume' : 'Pause' }}
              </button>
              <button
                type="button"
                class="voice-loop-button voice-loop-stop"
                (click)="stopConversationLoop()"
              >
                <app-icon name="square" [size]="12" />
                Stop
              </button>
            }
          </div>
        }
        @if (voiceRealtimeBlockedHint()) {
          <span class="voice-warning-pill" [title]="voiceRealtimeBlockedHint()">
            <app-icon name="radio" [size]="12" />
            WebRTC required
          </span>
        }
        <span
          class="tandem-oracle-pill"
          [title]="voiceTandemOracleHint()"
        >
          <app-icon name="activity" [size]="12" />
          Tandem oracle
          <span
            class="control-info-dot"
            title="Fast voice loop plus background Knowledge oracle. It can update context while the conversation continues."
          >
            <app-icon name="info" [size]="10" />
          </span>
        </span>
        <label
          class="voice-checkbox"
          title="When enabled, the final voice transcript replaces the current draft and is sent as one chat turn."
        >
          <input
            type="checkbox"
            class="accent-brand-500"
            [ngModel]="voiceAutoSend()"
            (ngModelChange)="voiceAutoSend.set($event)"
            [disabled]="!canTranscribeVoice()"
          />
          Auto-send final transcript
        </label>
        @if (voiceTransport() === 'backend_ws') {
          <label
            class="voice-checkbox"
            title="When enabled, Agentium ends the current voice turn after speech followed by a short silence. This does not keep the microphone open between assistant turns yet."
          >
            <input
              type="checkbox"
              class="accent-brand-500"
              [ngModel]="voiceAutoEndpoint()"
              (ngModelChange)="voiceAutoEndpoint.set($event)"
              [disabled]="!canUseVoiceSession()"
            />
            Auto endpoint
          </label>
        }
        <span [class]="voiceStatusClass()">{{ voiceStatusLabel() }}</span>
        <span class="text-gray-600">·</span>
        <span class="truncate max-w-[36rem]" [title]="voiceRuntimeDetail()">{{ voiceRuntimeDetail() }}</span>
        @if (voicePartial()) {
          <span class="text-brand-200 truncate max-w-xs">“{{ voicePartial() }}”</span>
        }
      </div>
      @if (voiceTransport() === 'backend_ws') {
        <div class="voice-oracle-panel" [title]="voiceOraclePanelHint()">
          <div class="voice-oracle-copy">
            <span class="voice-oracle-kicker">Agentium voice session</span>
            <span class="voice-oracle-message">{{ voiceOracleMessage() }}</span>
          </div>
          <div class="voice-oracle-steps">
            @for (step of voiceOracleTimeline(); track step.stage) {
              <span
                class="voice-oracle-step"
                [class.voice-oracle-step-active]="step.state === 'active'"
                [class.voice-oracle-step-done]="step.state === 'done'"
                [class.voice-oracle-step-error]="step.state === 'error'"
                [title]="step.detail"
              >
                <app-icon [name]="step.icon" [size]="11" />
                {{ step.label }}
              </span>
            }
          </div>
        </div>
      }
      }

      <!-- Messages -->
      <div
        class="flex-1 overflow-y-auto px-4 py-4 space-y-5"
        [class.vigie-messages]="executiveMode()"
        style="max-height: calc(100vh - 320px); min-height: 360px;"
      >
        @if (messages().length === 0 && !streaming()) {
          <div class="h-full flex flex-col items-center justify-center py-8" [class.vigie-empty-state]="executiveMode()">
            <div class="w-12 h-12 rounded-full bg-gradient-to-br from-brand-500/20 to-violet-500/20 flex items-center justify-center mb-3">
              <app-icon name="sparkles" [size]="20" class="text-brand-300" />
            </div>
            <div class="text-sm font-semibold text-gray-900 dark:text-white">
              {{ emptyTitle() }}
            </div>
            <p class="text-xs text-gray-500 dark:text-gray-400 mt-1 max-w-xs text-center">
              {{ emptySubtitle() }}
            </p>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-5 w-full max-w-2xl">
              @for (s of activeSuggestions(); track s.prompt) {
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
                [class.vigie-user-bubble]="executiveMode()"
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
                  [class.vigie-assistant-bubble]="executiveMode()"
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

              @if (msg.mapCommand) {
                <div
                  class="ml-0 inline-flex max-w-[85%] items-center gap-2 rounded-xl px-3 py-2 text-xs bg-sky-500/10 text-sky-200 ring-1 ring-sky-400/25"
                  [class.vigie-map-chip]="executiveMode()"
                >
                  <app-icon name="map-pin" [size]="14" class="text-sky-300" />
                  <span>
                    Carte stratégique prête · {{ mapCommandLabel(msg.mapCommand) }}
                  </span>
                </div>
              }

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
                                class="font-mono text-[10px] text-brand-400/80 shrink min-w-0 max-w-[14rem] truncate"
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
                  [class.hidden]="executiveMode() && !traceOpen()"
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
        [class.vigie-input-bar]="executiveMode()"
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
          [disabled]="transcribing() || !canTranscribeVoice()"
          [title]="voiceMicTitle()"
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
          [placeholder]="inputPlaceholder()"
          [disabled]="streaming()"
          (keydown)="onKey($event)"
        ></textarea>
        <button
          type="submit"
          [disabled]="streaming() || !userInput.trim()"
          class="px-4 py-2.5 bg-brand-500 hover:bg-brand-600 disabled:opacity-50 text-white rounded-xl transition text-sm font-medium flex items-center gap-1.5"
        >
          <app-icon [name]="streaming() ? 'loader-2' : 'send'" [size]="14" [class.animate-spin]="streaming()" />
          {{ streaming() ? 'Streaming' : sendLabel() }}
        </button>
      </form>
    </div>
  `,
  styles: [`
    .vigie-context-bar {
      padding: 12px 18px;
      border-bottom: 1px solid rgba(101, 214, 110, 0.12);
      background:
        linear-gradient(90deg, rgba(101, 214, 110, 0.070), rgba(242, 140, 56, 0.035) 42%, transparent 68%),
        rgba(255, 255, 255, 0.018);
    }
    .vigie-kicker {
      color: #f5a85a;
      font: 750 11px/1.2 var(--ck-font-mono, ui-monospace, monospace);
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }
    .vigie-scope-line {
      margin-top: 4px;
      color: rgba(226, 236, 248, 0.74);
      font-size: 12px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .vigie-trace-button {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      padding: 8px 10px;
      border-radius: 10px;
      border: 1px solid rgba(101, 214, 110, 0.18);
      background: rgba(11, 18, 28, 0.74);
      color: rgba(226, 236, 248, 0.78);
      font-size: 12px;
      transition: 140ms ease;
    }
    .vigie-trace-button:hover {
      border-color: rgba(101, 214, 110, 0.38);
      color: #f4f8ff;
      background: rgba(18, 31, 45, 0.82);
    }
    .chat-control-bar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 10px 14px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.06);
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.032), rgba(255, 255, 255, 0.010)),
        rgba(3, 8, 16, 0.40);
    }
    .chat-control-main {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
      flex-wrap: wrap;
    }
    .chat-control-actions {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-shrink: 0;
    }
    .chat-mode-chip {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-height: 30px;
      padding: 4px 9px;
      border: 1px solid rgba(148, 197, 229, 0.12);
      border-radius: 12px;
      background: rgba(255, 255, 255, 0.035);
      color: rgba(232, 239, 250, 0.88);
      font-size: 11px;
      font-weight: 750;
      letter-spacing: 0.05em;
      text-transform: uppercase;
    }
    .chat-mode-model {
      color: rgba(177, 190, 210, 0.82);
      font: 650 11px/1.2 var(--ck-font-mono, ui-monospace, monospace);
      text-transform: none;
      letter-spacing: 0;
    }
    .source-picker,
    .session-doc-mode,
    .mini-control {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-height: 30px;
      border: 1px solid rgba(148, 197, 229, 0.14);
      border-radius: 12px;
      background: rgba(255, 255, 255, 0.045);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
    }
    .source-picker {
      padding: 3px 7px 3px 9px;
    }
    .source-picker-label,
    .session-doc-label,
    .mini-control-label {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      color: rgba(177, 190, 210, 0.82);
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      white-space: nowrap;
    }
    .source-picker-label app-icon,
    .session-doc-label app-icon,
    .mini-control-label app-icon {
      color: rgb(103, 213, 246);
    }
    .source-picker-select-wrap {
      position: relative;
      display: inline-flex;
      align-items: center;
      min-width: 184px;
      max-width: 270px;
    }
    .source-picker-select,
    .mini-select,
    .voice-select {
      width: 100%;
      -webkit-appearance: none;
      appearance: none;
      border: 0;
      outline: 0;
      border-radius: 8px;
      background: rgba(2, 8, 18, 0.38);
      color: rgba(245, 248, 252, 0.92);
      padding: 4px 24px 4px 9px;
      font: 600 11px/1.2 var(--ck-font-sans, ui-sans-serif, system-ui);
      color-scheme: dark;
    }
    .source-picker-select:focus,
    .mini-select:focus,
    .voice-select:focus {
      box-shadow: 0 0 0 1px rgba(103, 213, 246, 0.42);
      background: rgba(6, 13, 25, 0.76);
    }
    .source-picker-chevron,
    .mini-select-chevron,
    .voice-select-chevron {
      position: absolute;
      right: 7px;
      color: rgba(177, 190, 210, 0.72);
      pointer-events: none;
    }
    .session-doc-mode {
      padding: 3px;
    }
    .session-doc-label {
      padding-left: 6px;
    }
    .session-doc-mode-button {
      border: 0;
      border-radius: 8px;
      color: rgba(177, 190, 210, 0.78);
      padding: 4px 8px;
      font-size: 11px;
      font-weight: 700;
      transition: 140ms ease;
    }
    .session-doc-mode-button:hover {
      color: rgba(245, 248, 252, 0.92);
      background: rgba(255, 255, 255, 0.06);
    }
    .session-doc-mode-active {
      color: rgb(219, 249, 255);
      background: rgba(34, 211, 238, 0.15);
      box-shadow: inset 0 0 0 1px rgba(103, 213, 246, 0.22);
    }
    .mini-control {
      padding: 3px 7px 3px 9px;
    }
    .mini-select-wrap,
    .voice-select-wrap {
      position: relative;
      display: inline-flex;
      align-items: center;
      min-width: 104px;
    }
    .mini-select {
      min-width: 96px;
      font-family: var(--ck-font-mono, ui-monospace, monospace);
    }
    .control-info-dot {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 14px;
      height: 14px;
      border-radius: 999px;
      color: rgba(177, 190, 210, 0.78);
      background: rgba(255, 255, 255, 0.055);
      box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.08);
      cursor: help;
    }
    .control-info-dot:hover {
      color: rgb(219, 249, 255);
      background: rgba(34, 211, 238, 0.13);
      box-shadow: inset 0 0 0 1px rgba(103, 213, 246, 0.25);
    }
    .voice-control-bar {
      display: flex;
      align-items: center;
      gap: 9px;
      flex-wrap: wrap;
      padding: 10px 14px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.06);
      background: rgba(0, 0, 0, 0.15);
      color: rgba(177, 190, 210, 0.82);
      font-size: 11px;
    }
	    .voice-control-group,
	    .voice-control-label,
	    .managed-runtime-pill,
	    .tandem-oracle-pill,
	    .voice-warning-pill,
	    .voice-checkbox {
	      display: inline-flex;
	      align-items: center;
	      gap: 7px;
	    }
    .voice-control-label {
      color: rgba(232, 239, 250, 0.86);
      font-weight: 700;
    }
    .managed-runtime-pill,
    .tandem-oracle-pill {
      min-height: 30px;
      padding: 5px 9px;
      border-radius: 12px;
      background: rgba(255, 255, 255, 0.045);
      box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.08);
      color: rgba(232, 239, 250, 0.88);
    }
	    .tandem-oracle-pill {
	      background: rgba(34, 211, 238, 0.10);
	      color: rgb(207, 250, 254);
	      box-shadow: inset 0 0 0 1px rgba(103, 213, 246, 0.20);
	    }
	    .voice-warning-pill {
	      min-height: 30px;
	      padding: 5px 9px;
	      border-radius: 12px;
	      background: rgba(245, 158, 11, 0.10);
	      color: rgb(253, 230, 138);
	      box-shadow: inset 0 0 0 1px rgba(245, 158, 11, 0.22);
	      font-weight: 750;
	    }
	    .voice-select-wrap {
	      min-width: 176px;
	      max-width: 260px;
	    }
    .voice-transport-toggle {
      display: inline-flex;
      overflow: hidden;
      border-radius: 12px;
      border: 1px solid rgba(148, 197, 229, 0.14);
      background: rgba(255, 255, 255, 0.035);
    }
    .voice-transport-button {
      padding: 6px 11px;
      color: rgba(177, 190, 210, 0.78);
      font-weight: 700;
      transition: 140ms ease;
    }
    .voice-transport-button:hover:not(:disabled) {
      color: rgba(245, 248, 252, 0.94);
      background: rgba(255, 255, 255, 0.06);
    }
    .voice-transport-button:disabled {
      opacity: 0.42;
      cursor: not-allowed;
    }
    .voice-transport-active {
      color: rgb(207, 250, 254);
      background: rgba(34, 211, 238, 0.14);
    }
	    .voice-loop-actions {
	      display: inline-flex;
	      align-items: center;
	      gap: 6px;
	      padding: 3px;
	      border-radius: 12px;
	      border: 1px solid rgba(148, 197, 229, 0.14);
	      background: rgba(255, 255, 255, 0.035);
	    }
	    .voice-loop-button {
	      display: inline-flex;
	      align-items: center;
	      gap: 6px;
	      min-height: 28px;
	      border-radius: 9px;
	      padding: 5px 9px;
	      color: rgba(232, 239, 250, 0.86);
	      font-weight: 750;
	      transition: 140ms ease;
	    }
	    .voice-loop-button:hover:not(:disabled) {
	      background: rgba(255, 255, 255, 0.07);
	      color: rgb(245, 248, 252);
	    }
	    .voice-loop-button:disabled {
	      opacity: 0.48;
	      cursor: not-allowed;
	    }
	    .voice-loop-start {
	      background: rgba(16, 185, 129, 0.12);
	      color: rgb(187, 247, 208);
	      box-shadow: inset 0 0 0 1px rgba(52, 211, 153, 0.20);
	    }
	    .voice-loop-stop {
	      background: rgba(239, 68, 68, 0.10);
	      color: rgb(254, 202, 202);
	      box-shadow: inset 0 0 0 1px rgba(248, 113, 113, 0.18);
	    }
	    .voice-checkbox {
	      color: rgba(177, 190, 210, 0.84);
	    }
	    .voice-oracle-panel {
	      display: flex;
	      align-items: center;
	      justify-content: space-between;
	      gap: 12px;
	      padding: 10px 14px;
	      border-bottom: 1px solid rgba(255, 255, 255, 0.06);
	      background:
	        linear-gradient(90deg, rgba(34, 211, 238, 0.055), transparent 42%),
	        rgba(3, 8, 16, 0.30);
	      color: rgba(177, 190, 210, 0.84);
	      font-size: 11px;
	    }
	    .voice-oracle-copy {
	      display: flex;
	      align-items: baseline;
	      gap: 9px;
	      min-width: 0;
	    }
	    .voice-oracle-kicker {
	      color: rgb(103, 213, 246);
	      font: 700 10px/1.2 var(--ck-font-mono, ui-monospace, monospace);
	      letter-spacing: 0.12em;
	      text-transform: uppercase;
	      white-space: nowrap;
	    }
	    .voice-oracle-message {
	      overflow: hidden;
	      text-overflow: ellipsis;
	      white-space: nowrap;
	      color: rgba(232, 239, 250, 0.82);
	    }
	    .voice-oracle-steps {
	      display: flex;
	      align-items: center;
	      gap: 6px;
	      flex-wrap: wrap;
	      justify-content: flex-end;
	    }
	    .voice-oracle-step {
	      display: inline-flex;
	      align-items: center;
	      gap: 5px;
	      min-height: 24px;
	      padding: 3px 7px;
	      border-radius: 999px;
	      background: rgba(255, 255, 255, 0.035);
	      color: rgba(177, 190, 210, 0.70);
	      box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.06);
	      white-space: nowrap;
	    }
	    .voice-oracle-step-active {
	      background: rgba(34, 211, 238, 0.12);
	      color: rgb(207, 250, 254);
	      box-shadow: inset 0 0 0 1px rgba(103, 213, 246, 0.24);
	    }
	    .voice-oracle-step-done {
	      background: rgba(16, 185, 129, 0.10);
	      color: rgb(187, 247, 208);
	      box-shadow: inset 0 0 0 1px rgba(52, 211, 153, 0.18);
	    }
	    .voice-oracle-step-error {
	      background: rgba(239, 68, 68, 0.10);
	      color: rgb(254, 202, 202);
	      box-shadow: inset 0 0 0 1px rgba(248, 113, 113, 0.20);
	    }
	    @media (max-width: 900px) {
	      .voice-oracle-panel {
	        align-items: flex-start;
	        flex-direction: column;
	      }
	      .voice-oracle-steps {
	        justify-content: flex-start;
	      }
	    }
	    .vigie-messages {
      background:
        radial-gradient(circle at 82% 4%, rgba(101, 214, 110, 0.055), transparent 32%),
        linear-gradient(180deg, rgba(5, 10, 16, 0.18), transparent 38%);
    }
    .vigie-empty-state {
      align-items: stretch !important;
      justify-content: flex-start !important;
      padding-top: 28px !important;
      max-width: 590px;
      margin: 0 auto;
    }
    .vigie-empty-state > div:first-child {
      align-self: center;
      width: 56px !important;
      height: 56px !important;
      border: 1px solid rgba(242, 140, 56, 0.26);
      box-shadow: 0 18px 55px rgba(0, 0, 0, 0.26);
    }
    .vigie-empty-state button {
      border-radius: 14px !important;
      border: 1px solid rgba(101, 214, 110, 0.13) !important;
      background:
        linear-gradient(135deg, rgba(101, 214, 110, 0.055), rgba(255, 255, 255, 0.018)) !important;
      padding: 14px !important;
    }
    .vigie-user-bubble {
      max-width: 78% !important;
      border: 1px solid rgba(101, 214, 110, 0.34) !important;
      background:
        linear-gradient(135deg, rgba(21, 122, 61, 0.78), rgba(27, 87, 55, 0.72)) !important;
      color: #f4fbff !important;
      box-shadow: 0 18px 42px rgba(0, 0, 0, 0.22) !important;
    }
    .vigie-assistant-bubble {
      max-width: 88% !important;
      border: 1px solid rgba(148, 197, 229, 0.13) !important;
      background:
        linear-gradient(145deg, rgba(17, 25, 38, 0.94), rgba(10, 15, 23, 0.90)) !important;
      color: rgba(245, 248, 252, 0.94) !important;
      border-radius: 18px !important;
      box-shadow: 0 18px 45px rgba(0, 0, 0, 0.18) !important;
    }
    .vigie-map-chip {
      border-radius: 14px !important;
      border: 1px solid rgba(101, 214, 110, 0.22) !important;
      background: rgba(21, 47, 36, 0.68) !important;
      color: #d8ffd5 !important;
    }
    .vigie-input-bar {
      padding: 14px !important;
      background: rgba(6, 10, 15, 0.82) !important;
      border-top-color: rgba(101, 214, 110, 0.12) !important;
    }
    .vigie-input-bar textarea {
      border-radius: 16px !important;
      border-color: rgba(148, 197, 229, 0.18) !important;
      background: rgba(255, 255, 255, 0.045) !important;
      min-height: 48px;
    }
    .vigie-input-bar button[type='submit'] {
      border-radius: 16px !important;
      min-height: 48px;
    }
  `],
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
  readonly assistantProfileKey = input<string | null>(null);
  readonly initialPrompt = input<string | null>(null);

  private readonly sse = inject(SseService);
  private readonly api = inject(ApiService);
  private readonly canonicalApi = inject(CanonicalApiService);
  private readonly toast = inject(ToastrService);
  private readonly router = inject(Router);
  private readonly health = inject(RuntimeHealthService);
  private readonly voiceSession = inject(VoiceSessionService);
  private readonly voiceLoopFactory = inject(VoiceLoopControllerFactory);
  private readonly destroyRef = inject(DestroyRef);
  private readonly cdr = inject(ChangeDetectorRef);
  private readonly workspace = inject(WorkspaceService);
  readonly settings = inject(SettingsService);

  messages = signal<ChatMessage[]>([]);
  streaming = signal(false);
  streamBuffer = signal('');
  liveSteps = signal<DecisionStep[]>([]);
  evaluatingId = signal<string | null>(null);
  userInput = '';
  private chatSessionId: string | null = null;
  private chatSessionSignature: string | null = null;
  private creatingChatSession = false;

  readonly ragModeChoices = RAG_MODE_CHOICES;
  readonly ragModeOverride = signal<RagModeChoice>('auto');
  readonly promptType = signal<string>('auto');
  readonly reasoningTemplates = signal<ReasoningTemplate[]>([]);
  readonly voiceRuntimes = signal<VoiceRuntimeCatalog | null>(null);
  readonly voiceProvider = signal('cascade_openai');
	  readonly voiceTransport = signal<VoiceTransportChoice>('batch_http');
	  readonly voiceAutoSend = signal(false);
	  readonly voiceAutoEndpoint = signal(true);
	  readonly voiceConversationActive = signal(false);
	  readonly voiceConversationPaused = signal(false);
	  readonly voicePartial = signal('');
	  readonly voiceNotice = signal<string | null>(null);
	  readonly voiceOracleStage = signal<VoiceOracleStage>('idle');
	  readonly voiceOracleMessage = signal('Batch mode: no persistent voice session is open.');
	  readonly isDemoMode = computed(() => this.workspace.isDemoSafeMode());
  readonly chatRuntimeLabel = computed(() =>
    this.isDemoMode() ? 'managed runtime' : this.settings.settings().defaultModel || '—',
  );
  readonly traceOpen = signal(false);

  readonly activeAssistantProfile = computed<AssistantProfile | null>(() => {
    const settings = this.workspace.current()?.settings;
    const explicitKey = this.assistantProfileKey();
    const defaultKey = typeof settings?.['assistant_profile_default'] === 'string'
      ? settings['assistant_profile_default']
      : null;
    const key = explicitKey || defaultKey;
    if (!key) return null;
    const profiles = settings?.['assistant_profiles'];
    if (!Array.isArray(profiles)) return null;
    const match = (profiles as AssistantProfile[]).find((profile) => profile.key === key);
    return match ?? null;
  });

  readonly executiveMode = computed(() => isSentinelShowcaseProfile(this.activeAssistantProfile()));
  readonly assistantLabel = computed(() => this.activeAssistantProfile()?.label || 'Agentium');
  readonly workspaceChatConfig = computed<WorkspaceChatConfig>(() => {
    const settings = this.workspace.current()?.settings;
    const workspaceConfig = settings?.['chat'];
    const profileConfig = this.activeAssistantProfile()?.chat;
    return {
      ...(this.isRecord(workspaceConfig) ? workspaceConfig : {}),
      ...(this.isRecord(profileConfig) ? profileConfig : {}),
    } as WorkspaceChatConfig;
  });
  readonly workspaceVoiceLoopConfig = computed<WorkspaceVoiceLoopConfig>(() => {
    const settings = this.workspace.current()?.settings;
    const workspaceConfig = this.isRecord(settings?.['voice_loop']) ? settings?.['voice_loop'] : {};
    const profileConfig = this.activeAssistantProfile()?.voice_loop;
    return {
      ...(this.isRecord(workspaceConfig) ? workspaceConfig : {}),
      ...(this.isRecord(profileConfig) ? profileConfig : {}),
    } as WorkspaceVoiceLoopConfig;
  });
  readonly selectedSource = signal<SourceSelection>('auto');
  readonly sessionDocsMode = signal<SessionDocsMode>('replace');
  readonly knowledgeScopeOptions = computed<KnowledgeScopeOption[]>(() => {
    const settings = this.workspace.current()?.settings;
    const scopes = settings?.['knowledge_scopes'];
    if (!Array.isArray(scopes)) return [];
    return (scopes as Array<Record<string, unknown>>)
      .map((scope) => ({
        key: String(scope['key'] || ''),
        label: typeof scope['label'] === 'string' ? scope['label'] : undefined,
        description: typeof scope['description'] === 'string' ? scope['description'] : undefined,
        is_default: !!scope['is_default'],
        collection_slugs: Array.isArray(scope['collection_slugs'])
          ? scope['collection_slugs'].map((slug) => String(slug))
          : undefined,
      }))
      .filter((scope) => !!scope.key);
  });
  readonly profileKnowledgeScope = computed(() => this.activeAssistantProfile()?.default_knowledge_scope || null);
  readonly workspaceDefaultKnowledgeScope = computed(() => {
    const scopes = this.knowledgeScopeOptions();
    return scopes.find((scope) => scope.is_default)?.key || scopes[0]?.key || null;
  });
  readonly activeKnowledgeScope = computed(() => {
    if (this.contextId() && this.sessionDocsMode() === 'replace') return null;
    const selected = this.selectedSource();
    if (selected === 'workspace_default') return this.workspaceDefaultKnowledgeScope();
    if (selected !== 'auto') return selected;
    return this.profileKnowledgeScope() || this.workspaceDefaultKnowledgeScope();
  });
  readonly assistantScopeLabel = computed(() => {
    const label = this.scopeLabel(this.activeKnowledgeScope());
    if (!this.contextId()) return `Knowledge source: ${label}`;
    if (this.sessionDocsMode() === 'combine') return `Session docs + ${label}`;
    return 'Session docs only';
  });
  readonly autoSourceLabel = computed(() => {
    const key = this.profileKnowledgeScope() || this.workspaceDefaultKnowledgeScope();
    return this.scopeLabel(key);
  });
  readonly sourceSelectionLabel = computed(() => {
    const selected = this.selectedSource();
    if (selected === 'auto') {
      return this.profileKnowledgeScope() ? 'Profile default' : 'Workspace default';
    }
    if (selected === 'workspace_default') return 'Workspace default';
    return this.scopeLabel(selected);
  });

  readonly activeSuggestions = computed<SuggestionCard[]>(() => {
    if (this.executiveMode()) {
      const pack = this.sanitizePromptPack(this.activeAssistantProfile()?.prompt_pack);
      if (pack.length) return pack;
    }
    const configured = this.configuredPromptPack();
    if (configured.length) return configured;
    if (this.contextId()) return this.sessionDocSuggestions();
    if (this.activeKnowledgeScope()) return this.knowledgeSourceSuggestions();
    return this.workspaceSuggestions();
  });

  readonly emptyTitle = computed(() => {
    const configured = this.workspaceChatConfig().title;
    if (configured) return configured;
    if (this.executiveMode()) return `Interroger ${this.assistantLabel()}`;
    if (this.activeAssistantProfile()) return `Ask ${this.assistantLabel()}`;
    return 'Start a conversation';
  });
  readonly emptySubtitle = computed(() => {
    const configured = this.workspaceChatConfig().subtitle;
    if (configured) return configured;
    if (this.executiveMode()) return 'Posez une question sur les signaux, projets, sources et décisions attendues.';
    if (this.contextId() && this.sessionDocsMode() === 'replace') {
      return 'Ask a sourced question grounded only in the documents uploaded for this session.';
    }
    if (this.contextId() && this.sessionDocsMode() === 'combine') {
      return `Ask a sourced question across session documents and ${this.scopeLabel(this.activeKnowledgeScope())}.`;
    }
    if (this.activeKnowledgeScope()) {
      return `Ask a sourced question using ${this.scopeLabel(this.activeKnowledgeScope())}.`;
    }
    return 'Ask a workspace question, or choose a Knowledge source before sending.';
  });
  readonly inputPlaceholder = computed(() => {
    const configured = this.workspaceChatConfig().placeholder;
    if (configured) return configured;
    if (this.executiveMode()) return `Interroger ${this.assistantLabel()} sur les sources du workspace...`;
    if (this.contextId() && this.sessionDocsMode() === 'replace') {
      return 'Ask about the uploaded session documents...';
    }
    if (this.contextId() && this.sessionDocsMode() === 'combine') {
      return `Ask across session documents and ${this.scopeLabel(this.activeKnowledgeScope())}...`;
    }
    if (this.activeKnowledgeScope()) {
      return `Ask a sourced question using ${this.scopeLabel(this.activeKnowledgeScope())}...`;
    }
    return 'Ask a workspace question…';
  });
  readonly sendLabel = computed(() => this.executiveMode() ? 'Interroger' : 'Send');

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

  readonly voiceRuntimeOptions = computed<VoiceRuntimeProviderOption[]>(() => {
    const catalog = this.voiceRuntimes();
    return catalog?.providers?.length
      ? catalog.providers
      : [
          {
            slug: 'cascade_openai',
            status: 'unconfigured',
            transport: 'backend_ws',
            capabilities: { batch_transcription: true, tts: true, barge_in: true },
          },
        ];
  });

	  readonly selectedVoiceRuntime = computed<VoiceRuntimeProviderOption | null>(() => {
	    const provider = this.voiceProvider();
	    return this.voiceRuntimeOptions().find((runtime) => runtime.slug === provider) ?? null;
	  });

	  readonly canUseVoiceSession = computed(() => {
	    const runtime = this.selectedVoiceRuntime();
	    if (!runtime || !this.isVoiceRuntimeSelectableInChat(runtime)) return false;
	    const caps = runtime.capabilities ?? {};
	    return Boolean(caps['streaming_transcription'] || caps['batch_transcription']);
	  });

  readonly canTranscribeVoice = computed(() => {
    const caps = this.selectedVoiceRuntime()?.capabilities ?? {};
    return Boolean(caps['streaming_transcription'] || caps['batch_transcription'] || this.hasCascadeFallback());
  });

  readonly voiceStatusLabel = computed(() => {
    const runtime = this.selectedVoiceRuntime();
    if (!runtime) return 'runtime unknown';
    if (this.voiceNotice()) return this.voiceNotice();
    const status = runtime.status || 'unknown';
    if (status === 'bound') return 'ready';
    if (status === 'disabled') return 'disabled';
    if (status === 'unconfigured') return 'fallback required';
    if (status === 'experimental') return 'experimental';
    return status.replace(/_/g, ' ');
  });

	  readonly voiceStatusClass = computed(() => {
    const status = this.selectedVoiceRuntime()?.status || 'unknown';
    if (this.voiceNotice()) return 'px-2 py-1 rounded bg-brand-500/10 text-brand-100 ring-1 ring-brand-300/20';
    if (status === 'bound') return 'px-2 py-1 rounded bg-emerald-500/10 text-emerald-200 ring-1 ring-emerald-400/20';
    if (status === 'disabled' || status === 'unconfigured') return 'px-2 py-1 rounded bg-amber-500/10 text-amber-200 ring-1 ring-amber-400/20';
    if (status === 'experimental') return 'px-2 py-1 rounded bg-violet-500/10 text-violet-200 ring-1 ring-violet-400/20';
	    return 'px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10';
	  });

	  readonly voiceOracleTimeline = computed(() => {
	    const stage = this.voiceOracleStage();
	    const rank: Record<VoiceOracleStage, number> = {
	      idle: 0,
	      listening: 1,
	      thinking: 2,
	      superseded: 2,
	      fallback: 2,
	      committed: 3,
	      error: 0,
	    };
	    const currentRank = rank[stage] ?? 0;
	    const mkState = (stepRank: number, stepStage: VoiceOracleStage) => {
	      if (stage === 'error') return stepStage === 'fallback' ? 'error' : 'pending';
	      if (stage === stepStage) return 'active';
	      return currentRank > stepRank ? 'done' : 'pending';
	    };
	    return [
	      {
	        stage: 'listening' as VoiceOracleStage,
	        label: 'listening',
	        icon: 'mic',
	        detail: 'Microphone input is being recorded. Agent speech is paused to avoid overlap.',
	        state: mkState(1, 'listening'),
	      },
	      {
	        stage: 'thinking' as VoiceOracleStage,
	        label: 'thinking',
	        icon: 'activity',
	        detail: 'Agentium received a transcript and is updating the background oracle.',
	        state: mkState(2, 'thinking'),
	      },
	      {
	        stage: 'superseded' as VoiceOracleStage,
	        label: 'refreshed',
	        icon: 'refresh-cw',
	        detail: 'A newer oracle signal replaced an older one using latest-wins semantics.',
	        state: stage === 'superseded' ? 'active' : currentRank > 2 ? 'done' : 'pending',
	      },
	      {
	        stage: 'fallback' as VoiceOracleStage,
	        label: 'fallback',
	        icon: 'route',
	        detail: 'The selected runtime used its fallback lane for this voice turn.',
	        state: stage === 'fallback' ? 'active' : 'pending',
	      },
	      {
	        stage: 'committed' as VoiceOracleStage,
	        label: 'committed',
	        icon: 'check-circle-2',
	        detail: 'The latest transcript/oracle decision is committed for the current turn.',
	        state: mkState(3, 'committed'),
	      },
	    ];
	  });

	  readonly voiceRuntimeDetail = computed(() => {
	    const runtime = this.selectedVoiceRuntime();
	    const caps = runtime?.capabilities ?? {};
    const input = caps['streaming_transcription']
      ? 'streaming STT'
      : caps['batch_transcription']
        ? 'batch STT'
        : this.hasCascadeFallback()
          ? 'input fallback cascade'
          : 'no STT';
    const output = caps['tts'] || caps['speech_to_speech'] ? 'native output' : this.hasCascadeFallback() ? 'output fallback cascade' : 'no TTS';
	    const transport = this.voiceTransport() === 'backend_ws' ? 'Agentium voice channel' : 'HTTP batch';
	    const oracle = caps['oracle_injection'] || caps['background_tool_calls'] ? 'tandem oracle' : 'oracle via fallback';
	    if (runtime && this.voiceRuntimeNeedsWebRtc(runtime)) {
	      return this.isDemoMode()
	        ? 'realtime · WebRTC required · not available in chat session yet'
	        : `${runtime.slug.replace(/_/g, ' ')} · WebRTC required · chat session not wired yet`;
	    }
	    if (this.isDemoMode()) {
	      const mode = this.voiceRuntimeKind(runtime?.slug || this.voiceProvider()).toLowerCase();
	      return `${mode} · ${input} · ${output} · ${transport} · ${oracle}`;
    }
    return `${input} · ${output} · ${transport} · ${oracle}`;
  });

	  readonly voiceTandemOracleHint = computed(() =>
	    this.isDemoMode()
	      ? 'Realtime voice loop plus background Knowledge oracle. Provider details are hidden.'
	      : 'Realtime loop + background oracle with latest-wins events: oracle.delta, oracle.superseded, oracle.action and oracle.commit.',
	  );

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
  private currentAudio: HTMLAudioElement | null = null;
  private voiceConnection: VoiceSessionConnection | null = null;
  private readonly voiceLoop = this.voiceLoopFactory.create('chat');
  private chatVoiceSessionId = `chat-${crypto.randomUUID?.() || Date.now()}`;
  private streamStart = 0;
  private voiceLoopRearmTimer: ReturnType<typeof setTimeout> | null = null;
  private voiceLastEndpointReason: VoiceLoopEndpointReason | null = null;
  private appliedVoiceDefaultsSignature = '';

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

  private initialPromptApplied = false;

  constructor() {
    effect(() => {
      const prompt = this.initialPrompt();
      if (prompt && !this.initialPromptApplied) {
        this.userInput = prompt;
        this.initialPromptApplied = true;
        this.cdr.markForCheck();
      }
    });
    effect(() => {
      const workspaceSlug = this.workspace.current()?.slug || 'workspace';
      const profileKey = this.activeAssistantProfile()?.key || this.assistantProfileKey() || 'default';
      const config = this.workspaceVoiceLoopConfig();
      const selectable = this.canUseVoiceSession();
      const signature = `${workspaceSlug}|${profileKey}|${selectable}|${JSON.stringify(config)}`;
      if (signature === this.appliedVoiceDefaultsSignature) return;
      this.appliedVoiceDefaultsSignature = signature;
      this.applyWorkspaceVoiceDefaults(config, selectable);
    });
    this.settings.refresh();
    this.health.load().subscribe();
    this.loadReasoningTemplates();
    this.loadVoiceRuntimes();
    this.destroyRef.onDestroy(() => {
      this.currentAudio?.pause();
      this.clearVoiceLoopRearmTimer();
      this.voiceLoop.dispose();
      this.voiceConnection?.close();
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

  private loadVoiceRuntimes(): void {
    this.api.listVoiceRuntimes().subscribe({
      next: (catalog) => {
        this.voiceRuntimes.set(catalog);
	        const current = this.voiceProvider();
	        const allowed = catalog.allowed_providers || [];
	        const providers = catalog.providers || [];
	        const currentRuntime = providers.find((runtime) => runtime.slug === current);
	        const preferred = providers.find((runtime) => runtime.slug === catalog.default_provider && this.isVoiceRuntimeSelectableInChat(runtime));
	        const fallback = providers.find((runtime) => (catalog.fallback_providers || []).includes(runtime.slug) && this.isVoiceRuntimeSelectableInChat(runtime));
	        const firstSelectable = providers.find((runtime) => this.isVoiceRuntimeSelectableInChat(runtime));
	        if (!allowed.includes(current) || (currentRuntime && !this.isVoiceRuntimeSelectableInChat(currentRuntime))) {
	          this.voiceProvider.set(preferred?.slug || fallback?.slug || firstSelectable?.slug || 'cascade_openai');
	        }
	      },
      error: () => {
        this.voiceRuntimes.set(null);
        this.voiceProvider.set('cascade_openai');
      },
    });
  }

  private applyWorkspaceVoiceDefaults(config: WorkspaceVoiceLoopConfig, canUseSession: boolean): void {
    if (this.voiceConversationActive() || this.recording() || this.transcribing()) return;
    const mode = config.default_mode || (config.enabled_default ? 'session_loop' : 'batch');
    if (mode === 'session_loop' && canUseSession) {
      this.voiceTransport.set('backend_ws');
    } else {
      this.voiceTransport.set('batch_http');
    }
    if (typeof config.auto_send_final_transcript === 'boolean') {
      this.voiceAutoSend.set(config.auto_send_final_transcript);
    }
    if (typeof config.auto_endpoint === 'boolean') {
      this.voiceAutoEndpoint.set(config.auto_endpoint);
    }
    this.cdr.markForCheck();
  }

	  voiceRuntimeLabel(runtime: VoiceRuntimeProviderOption): string {
	    const webRtcRequired = this.voiceRuntimeNeedsWebRtc(runtime);
	    if (this.isDemoMode()) {
	      const label = this.voiceRuntimeKind(runtime.slug);
	      if (webRtcRequired) return `${label} · WebRTC required`;
	      if (runtime.status === 'bound') return label;
	      if (runtime.status === 'disabled') return `${label} · unavailable`;
	      if (runtime.status === 'unconfigured') return `${label} · not configured`;
      if (runtime.status === 'experimental') return `${label} · experimental`;
      return label;
	    }
	    const label = runtime.slug.replace(/_/g, ' ');
	    if (webRtcRequired) return `${label} · WebRTC not wired in chat`;
	    if (runtime.status === 'bound') return label;
	    return `${label} · ${runtime.status}`;
	  }

	  selectedVoiceDescription(): string {
	    const runtime = this.selectedVoiceRuntime();
	    if (runtime && this.voiceRuntimeNeedsWebRtc(runtime)) {
	      return this.isDemoMode()
	        ? 'Realtime voice requires the WebRTC lane, which is not wired into this chat control yet.'
	        : `${runtime.slug.replace(/_/g, ' ')} requires WebRTC. This chat control currently uses Agentium backend WebSocket sessions.`;
	    }
	    if (this.isDemoMode()) return `${this.voiceRuntimeKind(this.voiceProvider())} runtime. Provider and model details are hidden in demo-safe presentation.`;
	    return runtime?.description || this.voiceRuntimeDetail();
	  }

	  onVoiceProviderChange(slug: string): void {
	    const runtime = this.voiceRuntimeOptions().find((item) => item.slug === slug);
	    if (runtime && !this.isVoiceRuntimeSelectableInChat(runtime)) {
	      this.toast.info('Realtime voice requires the WebRTC lane; this chat surface uses Agentium voice sessions for now.', 'Voice');
	      return;
	    }
	    this.voiceProvider.set(slug || 'cascade_openai');
	    this.voicePartial.set('');
	    this.voiceNotice.set(null);
	    this.voiceOracleStage.set('idle');
	    this.voiceOracleMessage.set('Batch mode: no persistent voice session is open.');
	    this.stopConversationLoop();
	    this.closeVoiceSession();
	    if (!this.canUseVoiceSession()) {
	      this.voiceTransport.set('batch_http');
    }
  }

	  setVoiceTransport(transport: VoiceTransportChoice): void {
	    if (transport === 'backend_ws' && !this.canUseVoiceSession()) {
	      this.toast.info(this.voiceSessionButtonTitle(), 'Voice');
	      return;
	    }
	    this.voiceTransport.set(transport);
	    this.voiceNotice.set(null);
	    if (transport === 'batch_http') {
	      this.stopConversationLoop();
	      this.closeVoiceSession();
	      this.voiceOracleStage.set('idle');
	      this.voiceOracleMessage.set('Batch mode: no persistent voice session is open.');
	    } else {
	      this.voiceOracleStage.set('idle');
	      this.voiceOracleMessage.set('Session mode: Agentium will emit transcript, oracle and runtime events for each voice turn.');
	    }
	  }

	  isVoiceRuntimeSelectableInChat(runtime: VoiceRuntimeProviderOption): boolean {
	    return !this.voiceRuntimeNeedsWebRtc(runtime);
	  }

	  private voiceRuntimeNeedsWebRtc(runtime: VoiceRuntimeProviderOption): boolean {
	    return String(runtime.transport || '').toLowerCase() === 'webrtc';
	  }

	  voiceTransportHint(): string {
	    return 'Batch records one audio segment over HTTP. Session opens a persistent Agentium voice channel; Cascade still finalizes by segment. Full realtime speech requires WebRTC.';
	  }

	  voiceSessionButtonTitle(): string {
	    const runtime = this.selectedVoiceRuntime();
	    if (runtime && this.voiceRuntimeNeedsWebRtc(runtime)) {
	      return 'Realtime voice requires WebRTC; this chat session control is not wired to WebRTC yet.';
	    }
	    if (!this.canUseVoiceSession()) return 'This voice runtime does not expose an Agentium voice session path.';
	    return 'Use an Agentium voice session: text.partial, text.final, oracle events and runtime metrics.';
	  }

	  voiceRealtimeBlockedHint(): string | null {
	    const runtime = this.selectedVoiceRuntime();
	    if (!runtime || !this.voiceRuntimeNeedsWebRtc(runtime)) return null;
	    return this.isDemoMode()
	      ? 'Realtime voice requires the WebRTC lane. This chat control currently uses Agentium voice sessions.'
	      : `${runtime.slug.replace(/_/g, ' ')} requires WebRTC. This chat control currently uses Agentium backend WebSocket sessions.`;
	  }

	  voiceOraclePanelHint(): string {
	    return 'The session panel shows the voice turn lifecycle: listening, background oracle update, latest-wins refreshes, fallback and commit.';
	  }

  voiceMicTitle(): string {
    if (!this.canTranscribeVoice()) return this.isDemoMode() ? 'Voice runtime cannot transcribe audio' : 'Selected provider cannot transcribe voice';
    if (this.voiceConversationActive()) {
      if (this.voiceConversationPaused()) return 'Conversation loop paused. Press Resume to reopen the microphone.';
      if (this.recording()) return 'Listening. Silence will submit this voice turn automatically.';
      return 'Conversation loop is armed. The microphone reopens after each answer.';
    }
    if (this.transcribing()) return this.isDemoMode() ? 'Transcribing…' : `Transcribing with ${this.voiceInputProvider()}…`;
    if (this.recording()) {
      return this.voiceAutoEndpoint() && this.voiceTransport() === 'backend_ws'
        ? 'Listening. Silence submits this turn.'
        : 'Stop recording';
    }
    if (this.isDemoMode()) return `Record voice · ${this.voiceTransport() === 'backend_ws' ? 'session' : 'batch'}`;
    return `Record voice · ${this.voiceInputProvider()} · ${this.voiceTransport() === 'backend_ws' ? 'session' : 'batch'}`;
  }

  private voiceRuntimeNotice(label: string, provider?: string | null): string {
    if (this.isDemoMode()) return label;
    return provider ? `${label} · ${provider}` : label;
  }

  private voiceRuntimeKind(slug: string): string {
    const normalized = (slug || '').toLowerCase();
    if (normalized === 'cascade' || normalized === 'cascade_openai') return 'Cascade';
    if (normalized.includes('realtime') || normalized === 'realtime_gpu') return 'Realtime';
    if (normalized.includes('stt')) return 'Transcription';
    if (normalized.includes('tts')) return 'Speech output';
    return 'Voice runtime';
  }

  private hasCascadeFallback(): boolean {
    const catalog = this.voiceRuntimes();
    return !catalog || (catalog.fallback_providers || []).includes('cascade_openai') || (catalog.allowed_providers || []).includes('cascade_openai');
  }

  private voiceInputProvider(): string {
    const runtime = this.selectedVoiceRuntime();
    const caps = runtime?.capabilities ?? {};
    if (caps['batch_transcription'] || caps['streaming_transcription']) return runtime?.slug || 'cascade_openai';
    return this.hasCascadeFallback() ? 'cascade_openai' : runtime?.slug || 'cascade_openai';
  }

  private voiceOutputProvider(): string {
    const runtime = this.selectedVoiceRuntime();
    const caps = runtime?.capabilities ?? {};
    if (caps['tts'] || caps['speech_to_speech']) return runtime?.slug || 'cascade_openai';
    return this.hasCascadeFallback() ? 'cascade_openai' : runtime?.slug || 'cascade_openai';
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

  mapCommandLabel(command: Record<string, unknown>): string {
    const label = command['target_label'] || command['target'] || 'vue territoriale mise a jour';
    return String(label);
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
    const sheet = (src['sheet_name'] as string | undefined) ?? (meta['sheet_name'] as string | undefined);
    const cellRange = (src['cell_range'] as string | undefined) ?? (meta['cell_range'] as string | undefined);
    const rowStart = (src['row_start'] as number | string | undefined) ?? (meta['row_start'] as number | string | undefined);
    const rowEnd = (src['row_end'] as number | string | undefined) ?? (meta['row_end'] as number | string | undefined);
    if (sheet || cellRange || rowStart !== undefined || rowEnd !== undefined) {
      const parts: string[] = [];
      if (sheet) parts.push(sheet);
      if (cellRange) {
        parts.push(cellRange);
      } else if (rowStart !== undefined && rowStart !== null) {
        const end = rowEnd !== undefined && rowEnd !== null && `${rowEnd}` !== `${rowStart}` ? `-${rowEnd}` : '';
        parts.push(`row ${rowStart}${end}`);
      }
      return {
        label: parts.join(' · '),
        tooltip: `Spreadsheet locator: ${parts.join(' · ')}`,
      };
    }
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

  private configuredPromptPack(): SuggestionCard[] {
    const config = this.workspaceChatConfig();
    const activeScope = this.activeKnowledgeScope();
    const byScope = this.isRecord(config.prompt_pack_by_scope) && activeScope
      ? this.sanitizePromptPack(config.prompt_pack_by_scope[activeScope])
      : [];
    if (byScope.length) return byScope;

    if (this.contextId()) {
      const sessionPack = this.sanitizePromptPack(config.session_doc_prompt_pack);
      if (sessionPack.length) return sessionPack;
    }

    const workspacePack = this.sanitizePromptPack(config.prompt_pack);
    if (workspacePack.length) return this.filterPromptPack(workspacePack);

    if (config.use_assistant_profile_prompt_pack === true) {
      return this.filterPromptPack(this.sanitizePromptPack(this.activeAssistantProfile()?.prompt_pack));
    }

    return [];
  }

  private filterPromptPack(pack: SuggestionCard[]): SuggestionCard[] {
    const activeScope = this.activeKnowledgeScope();
    const docsMode = this.contextId() ? this.sessionDocsMode() : null;
    return pack.filter((card) => {
      const cardScope = card.scope_key || card.knowledge_scope || card.source_key;
      if (cardScope && cardScope !== activeScope) return false;
      if (card.context_mode && card.context_mode !== 'any' && card.context_mode !== docsMode) return false;
      return true;
    });
  }

  private sanitizePromptPack(value: unknown): SuggestionCard[] {
    if (!Array.isArray(value)) return [];
    return value
      .flatMap((item): SuggestionCard[] => {
        if (!this.isRecord(item)) return [];
        const label = typeof item['label'] === 'string' ? item['label'].trim() : '';
        const prompt = typeof item['prompt'] === 'string' ? item['prompt'].trim() : '';
        if (!label || !prompt) return [];
        const contextMode = item['context_mode'];
        const card: SuggestionCard = {
          icon: typeof item['icon'] === 'string' && item['icon'].trim() ? item['icon'].trim() : 'sparkles',
          label,
          prompt,
        };
        if (typeof item['scope_key'] === 'string') card.scope_key = item['scope_key'];
        if (typeof item['knowledge_scope'] === 'string') card.knowledge_scope = item['knowledge_scope'];
        if (typeof item['source_key'] === 'string') card.source_key = item['source_key'];
        if (contextMode === 'replace' || contextMode === 'combine' || contextMode === 'any') {
          card.context_mode = contextMode;
        }
        return [card];
      });
  }

  private workspaceSuggestions(): SuggestionCard[] {
    return [
      {
        icon: 'file-search',
        label: 'Find evidence',
        prompt: 'Find the most relevant workspace sources for this question and cite the documents used.',
      },
      {
        icon: 'binary',
        label: 'Answer with sources',
        prompt: 'Answer using only indexed workspace knowledge, then list the exact sources that support the answer.',
      },
      {
        icon: 'compass',
        label: 'Compare sources',
        prompt: 'Compare the available sources on this topic and highlight any mismatch or missing evidence.',
      },
      {
        icon: 'shield-check',
        label: 'Check confidence',
        prompt: 'State what is confirmed by the sources, what is uncertain, and what should be verified next.',
      },
    ];
  }

  private knowledgeSourceSuggestions(): SuggestionCard[] {
    const sourceLabel = this.scopeLabel(this.activeKnowledgeScope());
    return [
      {
        icon: 'file-search',
        label: 'Find a value',
        prompt: `In ${sourceLabel}, find the value of a business parameter and cite the file, page/sheet, and row or section used.`,
      },
      {
        icon: 'binary',
        label: 'Cited answer',
        prompt: `Answer using ${sourceLabel} only, with citations for every factual claim.`,
      },
      {
        icon: 'layers',
        label: 'Locate the table',
        prompt: `Find the table or section in ${sourceLabel} that defines a parameter, then explain how to read it.`,
      },
      {
        icon: 'shield-check',
        label: 'Evidence gap',
        prompt: `Check whether ${sourceLabel} contains enough evidence to answer the question, and say what is missing if it does not.`,
      },
    ];
  }

  private sessionDocSuggestions(): SuggestionCard[] {
    const mode = this.sessionDocsMode();
    const sourceLabel = this.scopeLabel(this.activeKnowledgeScope());
    return [
      {
        icon: 'file-search',
        label: 'Summarize upload',
        prompt: mode === 'combine'
          ? `Summarize the uploaded documents and compare them with ${sourceLabel}, citing both when used.`
          : 'Summarize the uploaded documents and cite the exact file names used.',
      },
      {
        icon: 'binary',
        label: 'Extract facts',
        prompt: 'Extract the key facts from the uploaded documents and include source references for each fact.',
      },
      {
        icon: 'compass',
        label: 'Find mismatch',
        prompt: mode === 'combine'
          ? `Identify any mismatch between the uploaded documents and ${sourceLabel}.`
          : 'Identify contradictions, missing values, or uncertainty inside the uploaded documents.',
      },
      {
        icon: 'shield-check',
        label: 'Ready for Knowledge',
        prompt: 'Assess whether the uploaded documents contain reviewable knowledge that should be promoted or captured.',
      },
    ];
  }

  private isRecord(value: unknown): value is Record<string, unknown> {
    return !!value && typeof value === 'object' && !Array.isArray(value);
  }

  scopeLabel(scopeKey: string | null | undefined): string {
    if (!scopeKey) return 'workspace';
    const scope = this.knowledgeScopeOptions().find((item) => item.key === scopeKey);
    return scope?.label || scopeKey;
  }

  onSourceSelectionChange(value: SourceSelection): void {
    this.selectedSource.set(value || 'auto');
    this.chatSessionId = null;
    this.chatSessionSignature = null;
  }

  setSessionDocsMode(mode: SessionDocsMode): void {
    this.sessionDocsMode.set(mode);
    this.chatSessionId = null;
    this.chatSessionSignature = null;
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
    if (!text || this.streaming() || this.creatingChatSession) return;

    const nextSignature = this.currentChatSessionSignature();
    if (this.chatSessionSignature !== nextSignature) {
      this.chatSessionId = null;
      this.chatSessionSignature = nextSignature;
    }
    if (!this.chatSessionId) {
      this.creatingChatSession = true;
      this.api
        .post<{ id: string }>('/sessions', { context: this.currentChatSessionContext() })
        .subscribe({
          next: (session) => {
            this.chatSessionId = session.id;
            this.creatingChatSession = false;
            this.send();
          },
          error: () => {
            this.creatingChatSession = false;
            this.toast.error('Could not create a chat session', 'Chat');
          },
        });
      return;
    }

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
    let mapCommand: Record<string, unknown> | undefined;

    const ragOverride = this.ragModeOverride();
    const promptTypeSel = this.promptType();
    this.sse
      .stream('/api/v1/chat/stream', {
        query: text,
        agent_id: this.systemId(),
        session_id: this.chatSessionId,
        context_id: this.contextId(),
        context_mode: this.contextId() ? this.sessionDocsMode() : null,
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
        knowledge_scope: this.activeKnowledgeScope(),
        assistant_profile: this.activeAssistantProfile()?.key ?? this.assistantProfileKey(),
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
          } else if (chunk.chunk_type === 'action_result') {
            const action = String((chunk as Record<string, unknown>)['action'] || '');
            if (action.startsWith('calendar_')) {
              window.dispatchEvent(new CustomEvent('agentium:calendar-updated', { detail: chunk }));
            } else if (action.startsWith('action_plan_')) {
              window.dispatchEvent(new CustomEvent('agentium:action-plan-updated', { detail: chunk }));
            } else if (action.startsWith('visual_')) {
              window.dispatchEvent(new CustomEvent('agentium:visual-intelligence-updated', { detail: chunk }));
            }
          } else if (chunk.chunk_type === 'map_command') {
            mapCommand = (chunk as Record<string, unknown>)['map_command'] as Record<string, unknown>;
            window.dispatchEvent(new CustomEvent('agentium:map-command', { detail: mapCommand }));
          } else if (chunk.chunk_type === 'map_state_updated') {
            window.dispatchEvent(new CustomEvent('agentium:map-state-updated', { detail: chunk }));
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
              mapCommand,
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
            if (this.ttsEnabled() && buffer.trim()) {
              this.flushTrailingTts(buffer);
            } else {
              this.scheduleVoiceLoopRearm();
            }
          }
        },
        error: () => {
          this.toast.error('Connection lost while streaming', 'Chat');
          this.streaming.set(false);
          this.streamBuffer.set('');
          this.liveSteps.set([]);
          this.scheduleVoiceLoopRearm();
        },
      });
  }

  clearConversation(): void {
    this.messages.set([]);
    this.streamBuffer.set('');
    this.liveSteps.set([]);
    this.openTrails.set(new Set());
    this.chatSessionId = null;
    this.chatSessionSignature = null;
    this.creatingChatSession = false;
  }

  private currentChatSessionSignature(): string {
    return [
      this.systemId() || 'workspace',
      this.contextId() || 'no-context',
      this.activeAssistantProfile()?.key || this.assistantProfileKey() || 'default-profile',
      this.selectedSource(),
      this.contextId() ? this.sessionDocsMode() : 'no-session-docs',
      this.activeKnowledgeScope() || 'workspace-scope',
    ].join('|');
  }

  private currentChatSessionContext(): Record<string, unknown> {
    return {
      system_id: this.systemId(),
      context_id: this.contextId(),
      context_mode: this.contextId() ? this.sessionDocsMode() : null,
      assistant_profile: this.activeAssistantProfile()?.key ?? this.assistantProfileKey(),
      knowledge_scope: this.activeKnowledgeScope(),
      source_selection: this.selectedSource(),
      created_from: 'chat_panel',
    };
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
    if (next && !this.voiceOutputProvider()) {
      this.toast.error(this.isDemoMode() ? 'Voice runtime cannot synthesize speech.' : 'Selected voice provider cannot synthesize speech.', 'Voice');
      return;
    }
    this.ttsEnabled.set(next);
    this.toast.info(next ? this.voiceRuntimeNotice('Voice output enabled', this.voiceOutputProvider()) : 'Voice output disabled');
    if (!next) {
      // Stop any playing audio and drop queued chunks so the user isn't
      // surprised by lagging TTS coming through after they muted.
      this.resetTtsPipeline();
    }
  }

  async toggleMic(): Promise<void> {
    if (this.recording()) {
      this.voiceLoop.stopTurn('manual');
      return;
    }
    await this.startVoiceTurn(false);
  }

  private voiceLoopSettingNumber(key: keyof WorkspaceVoiceLoopConfig, fallback: number, min: number, max: number): number {
    const value = Number(this.workspaceVoiceLoopConfig()[key]);
    if (!Number.isFinite(value)) return fallback;
    return Math.min(max, Math.max(min, Math.round(value)));
  }

  private voiceEndpointSilenceMs(): number {
    return this.voiceLoopSettingNumber('silence_ms', 1200, 300, 5000);
  }

  private voiceEndpointMinSpeechMs(): number {
    return this.voiceLoopSettingNumber('min_speech_ms', 350, 100, 3000);
  }

  private voiceEndpointMaxTurnMs(): number {
    return this.voiceLoopSettingNumber('max_turn_ms', 45000, 5000, 180000);
  }

  private voiceEndpointRmsThreshold(): number {
    const value = Number(this.workspaceVoiceLoopConfig().rms_threshold);
    return Number.isFinite(value) ? Math.min(0.15, Math.max(0.001, value)) : 0.018;
  }

  private voiceLoopCooldownMs(): number {
    return this.voiceLoopSettingNumber('cooldown_ms', 500, 0, 5000);
  }

  private voiceLoopBargeInEnabled(): boolean {
    return this.workspaceVoiceLoopConfig().barge_in !== false;
  }

  private voiceLoopAutoRearmEnabled(): boolean {
    return this.workspaceVoiceLoopConfig().auto_rearm_after_tts !== false;
  }

  private async startVoiceTurn(fromConversationLoop: boolean): Promise<boolean> {
    if (!this.canTranscribeVoice()) {
      this.toast.error(
        this.isDemoMode() ? 'Voice runtime cannot transcribe audio.' : 'Selected voice provider cannot transcribe audio.',
        'Voice',
      );
      return false;
    }
    if (this.recording() || this.transcribing() || this.streaming()) return false;
    if (fromConversationLoop && (!this.voiceConversationActive() || this.voiceConversationPaused())) return false;

    this.clearVoiceLoopRearmTimer();
    try {
      if (this.ttsSpeaking() && this.voiceLoopBargeInEnabled()) {
        this.voiceConnection?.bargeIn();
        this.voiceConnection?.ttsInterrupted({ reason: 'user_speech', surface: 'chat' });
        this.resetTtsPipeline();
        this.voiceNotice.set('Voice output stopped for listening');
      }

      const autoEndpoint = this.voiceTransport() === 'backend_ws' && (fromConversationLoop || this.voiceAutoEndpoint());
      this.voiceConnection?.loopArmed({
        surface: 'chat',
        mode: fromConversationLoop ? 'conversation_loop' : 'manual_turn',
        auto_endpoint: autoEndpoint,
      });
      this.voiceOracleStage.set('listening');
      this.voiceOracleMessage.set(
        autoEndpoint
          ? 'Listening: Agentium will end this voice turn after a short silence.'
          : 'Listening: press the microphone again to end this voice turn.',
      );

      const started = await this.voiceLoop.startTurn({
        autoEndpoint,
        mimeType: 'audio/webm',
        silenceMs: this.voiceEndpointSilenceMs(),
        minSpeechMs: this.voiceEndpointMinSpeechMs(),
        maxTurnMs: this.voiceEndpointMaxTurnMs(),
        rmsThreshold: this.voiceEndpointRmsThreshold(),
        onState: (state) => this.syncVoiceLoopState(state),
        onSpeechStart: () => {
          this.voiceOracleStage.set('listening');
          this.voiceOracleMessage.set('Speech detected. Agentium will submit after silence.');
          if (this.ttsSpeaking() && this.voiceLoopBargeInEnabled()) {
            this.voiceConnection?.bargeIn();
            this.voiceConnection?.ttsInterrupted({ reason: 'user_speech', surface: 'chat' });
            this.resetTtsPipeline();
          }
        },
        onNotice: (message) => this.voiceNotice.set(message),
        onEndpoint: (blob, reason) => {
          this.recording.set(false);
          this.voiceLastEndpointReason = reason;
          this.voiceNotice.set(this.voiceEndpointNotice(reason));
          this.voiceOracleStage.set('thinking');
          this.voiceOracleMessage.set('Voice turn ended; transcribing final audio.');
          this.transcribe(blob);
        },
        onError: (message) => {
          this.recording.set(false);
          this.voiceOracleStage.set('error');
          this.voiceOracleMessage.set(message);
          this.toast.error(message, 'Voice');
        },
      });
      this.recording.set(started);
      if (!started && fromConversationLoop) this.stopConversationLoop('microphone_unavailable');
      return started;
    } catch {
      this.recording.set(false);
      this.toast.error('Microphone access denied', 'Voice');
      if (fromConversationLoop) this.stopConversationLoop('microphone_denied');
      return false;
    }
  }

  async startConversationLoop(): Promise<void> {
    if (!this.canUseVoiceSession()) {
      this.toast.error(
        this.isDemoMode() ? 'Voice session loop is not available for this runtime.' : 'Selected runtime cannot open an Agentium voice session.',
        'Voice',
      );
      return;
    }
    if (this.voiceConversationActive()) return;
    const config = this.workspaceVoiceLoopConfig();
    this.setVoiceTransport('backend_ws');
    this.voiceAutoEndpoint.set(config.auto_endpoint !== false);
    this.voiceAutoSend.set(config.auto_send_final_transcript !== false);
    if (this.voiceOutputProvider()) this.ttsEnabled.set(true);
    this.voiceConversationActive.set(true);
    this.voiceConversationPaused.set(false);
    const connection = this.ensureVoiceSession();
    connection?.loopStart({
      surface: 'chat',
      mode: 'conversation_loop',
      auto_endpoint: true,
      auto_rearm_after_tts: this.voiceLoopAutoRearmEnabled(),
      silence_ms: this.voiceEndpointSilenceMs(),
      max_turn_ms: this.voiceEndpointMaxTurnMs(),
      barge_in: this.voiceLoopBargeInEnabled(),
    });
    this.voiceNotice.set('Conversation loop starting');
    this.voiceOracleStage.set('listening');
    this.voiceOracleMessage.set('Conversation loop armed. Speak after the microphone opens.');
    const started = await this.startVoiceTurn(true);
    if (!started && this.voiceConversationActive() && !this.voiceConversationPaused()) {
      this.scheduleVoiceLoopRearm();
    }
  }

  pauseConversationLoop(): void {
    if (!this.voiceConversationActive()) return;
    this.voiceConversationPaused.set(true);
    this.clearVoiceLoopRearmTimer();
    if (this.recording()) this.voiceLoop.pause();
    this.voiceConnection?.loopPause({ surface: 'chat' });
    this.voiceNotice.set('Conversation paused');
    this.voiceOracleStage.set('idle');
    this.voiceOracleMessage.set('Conversation loop is paused. Resume to reopen the microphone.');
    this.cdr.markForCheck();
  }

  resumeConversationLoop(): void {
    if (!this.voiceConversationActive()) return;
    this.voiceConversationPaused.set(false);
    this.voiceConnection?.loopResume({ surface: 'chat' });
    this.voiceNotice.set('Conversation resuming');
    this.voiceOracleMessage.set('Conversation loop is rearming the microphone.');
    void this.armConversationLoopTurn();
  }

  stopConversationLoop(reason = 'user_stop'): void {
    if (!this.voiceConversationActive() && !this.recording() && !this.transcribing() && !this.ttsSpeaking()) return;
    this.voiceConversationActive.set(false);
    this.voiceConversationPaused.set(false);
    this.clearVoiceLoopRearmTimer();
    this.voiceLoop.stopLoop();
    this.recording.set(false);
    this.transcribing.set(false);
    this.voicePartial.set('');
    this.voiceLastEndpointReason = null;
    if (this.ttsSpeaking()) this.resetTtsPipeline();
    this.voiceConnection?.loopStop({ surface: 'chat', reason });
    this.closeVoiceSession();
    this.voiceNotice.set(reason === 'user_stop' ? 'Conversation stopped' : `Conversation stopped · ${reason.replace(/_/g, ' ')}`);
    this.voiceOracleStage.set('idle');
    this.voiceOracleMessage.set('Conversation loop stopped. Batch voice turns remain available.');
    this.cdr.markForCheck();
  }

  private async armConversationLoopTurn(): Promise<void> {
    if (!this.voiceConversationActive() || this.voiceConversationPaused()) return;
    if (this.recording() || this.transcribing() || this.streaming() || this.ttsSpeaking()) return;
    await this.startVoiceTurn(true);
  }

  private scheduleVoiceLoopRearm(): void {
    if (!this.voiceConversationActive() || this.voiceConversationPaused()) return;
    if (!this.voiceLoopAutoRearmEnabled()) return;
    if (this.recording() || this.transcribing() || this.streaming()) return;
    this.clearVoiceLoopRearmTimer();
    this.voiceNotice.set('Conversation rearming');
    this.voiceOracleMessage.set('Answer complete. The microphone will reopen automatically.');
    this.voiceLoopRearmTimer = setTimeout(() => {
      this.voiceLoopRearmTimer = null;
      void this.armConversationLoopTurn();
    }, this.voiceLoopCooldownMs());
  }

  private clearVoiceLoopRearmTimer(): void {
    if (this.voiceLoopRearmTimer !== null) {
      clearTimeout(this.voiceLoopRearmTimer);
      this.voiceLoopRearmTimer = null;
    }
  }

  private syncVoiceLoopState(state: VoiceLoopState): void {
    if (state === 'arming') {
      this.voiceNotice.set('Arming microphone');
      return;
    }
    if (state === 'listening') {
      this.voiceOracleStage.set('listening');
      return;
    }
    if (state === 'endpointing') {
      this.voiceOracleStage.set('thinking');
      this.voiceOracleMessage.set('Endpoint detected; closing the voice turn.');
      return;
    }
    if (state === 'transcribing' || state === 'thinking') {
      this.voiceOracleStage.set('thinking');
      return;
    }
    if (state === 'paused') {
      this.recording.set(false);
      this.voiceOracleStage.set('idle');
      this.voiceOracleMessage.set('Conversation loop paused.');
      return;
    }
    if (state === 'idle') {
      this.recording.set(false);
      return;
    }
    if (state === 'error') {
      this.voiceOracleStage.set('error');
    }
  }

  private voiceEndpointNotice(reason: VoiceLoopEndpointReason): string {
    if (reason === 'silence') return 'Silence detected';
    if (reason === 'max_turn') return 'Max voice turn reached';
    if (reason === 'pause') return 'Voice turn paused';
    if (reason === 'stop') return 'Voice turn stopped';
    return 'Voice turn ended';
  }

  private handleFinalVoiceTranscript(
    rawText: string,
    options: { fallbackUsed?: boolean; provider?: string | null } = {},
  ): boolean {
    const text = rawText.trim();
    if (!text) {
      this.toast.info('No speech detected in the recording', 'Voice');
      this.scheduleVoiceLoopRearm();
      return true;
    }

    const command = this.detectVoiceCommand(text);
    if (command && this.handleVoiceCommand(command, text)) {
      this.cdr.markForCheck();
      return true;
    }

    const autoSendNow = (this.voiceConversationActive() || this.voiceAutoSend()) && !this.streaming();
    if (autoSendNow) {
      if (this.userInput.trim()) {
        this.toast.info('Existing draft replaced by the final voice transcript before auto-send.', 'Voice');
      }
      this.userInput = text;
    } else {
      this.userInput = this.userInput ? `${this.userInput} ${text}` : text;
    }
    this.voiceNotice.set(
      options.fallbackUsed
        ? this.voiceRuntimeNotice('Transcript ready · fallback used', options.provider || this.voiceInputProvider())
        : this.voiceRuntimeNotice('Transcript ready', options.provider || this.voiceInputProvider()),
    );
    this.cdr.markForCheck();
    if (autoSendNow && this.userInput.trim()) {
      queueMicrotask(() => this.send());
    }
    return false;
  }

  private detectVoiceCommand(rawText: string): string | null {
    const settings = this.workspaceVoiceLoopConfig();
    if (settings.commands_enabled === false) return null;
    let text = rawText
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/[^\p{L}\p{N}\s'-]/gu, ' ')
      .replace(/\s+/g, ' ')
      .trim();
    const triggerWord = typeof settings.trigger_word === 'string'
      ? settings['trigger_word'].toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').trim()
      : '';
    const hasTrigger = !!triggerWord && (text === triggerWord || text.startsWith(`${triggerWord} `));
    if (hasTrigger) text = text.slice(triggerWord.length).trim();
    const compact = text.replace(/\s+/g, ' ');
    const commandText = compact.replace(/['-]/g, ' ').replace(/\s+/g, ' ').trim();
    const genericCommandsEnabled = this.voiceCommandPackEnabled(settings, ['generic', 'fr_basic', 'workspace']);
    if (this.isNaturalStopCommand(commandText, settings.stop_phrases, genericCommandsEnabled)) return 'stop';
    if (!genericCommandsEnabled) return null;
    const words = commandText.split(/\s+/).filter(Boolean);
    if (!hasTrigger && words.length > 4) return null;
    if (['stop', 'arrete', 'arret', 'fin', 'termine'].includes(compact)) return 'stop';
    if (['stop', 'arrete', 'arret', 'fin', 'termine'].includes(commandText)) return 'stop';
    if (['pause', 'mets en pause'].includes(commandText)) return 'pause';
    if (['reprends', 'reprendre', 'continue', 'relance'].includes(commandText)) return 'resume';
    if (['annule', 'annuler', 'cancel', 'efface'].includes(commandText)) return 'cancel';
    if (['repete', 'repeter', 'repeat'].includes(commandText)) return 'repeat';
    if (['reformule', 'reformuler', 'rephrase'].includes(commandText)) return 'rephrase';
    if (commandText === 'question suivante' || commandText === 'suivant') return 'next_question';
    if (['valider', 'valide', 'confirmer', 'confirme'].includes(commandText)) return 'validate';
    return null;
  }

  private isNaturalStopCommand(commandText: string, configuredPhrases: unknown = null, includeDefaultPhrases = true): boolean {
    if (!commandText) return false;
    const customPhrases = Array.isArray(configuredPhrases)
      ? configuredPhrases
          .map((phrase) => this.normalizeVoiceCommandText(String(phrase)))
          .filter(Boolean)
      : [];
    if (customPhrases.some((phrase) => commandText === phrase || commandText.includes(phrase))) return true;
    if (!includeDefaultPhrases) return false;
    return [
      /\bon peut s arreter(?: la)?\b/,
      /\bon peut arreter(?: la)?\b/,
      /\bnous pouvons nous arreter(?: la)?\b/,
      /\bon s arrete(?: la)?\b/,
      /\bon arrete(?: la)?\b/,
      /\bon va s arreter(?: la)?\b/,
      /\bje vais m arreter(?: la)?\b/,
      /\bc est bon\b.*\b(?:arreter|stop|termine|terminer|fini|fin)\b/,
      /\bca suffit\b/,
      /\bcela suffit\b/,
      /\bon a fini\b/,
      /\bc est fini\b/,
      /\bc est termine\b/,
      /\bfin de session\b/,
      /\btu peux t arreter\b/,
      /\btu peux couper\b/,
      /\bon coupe\b/,
    ].some((pattern) => pattern.test(commandText));
  }

  private normalizeVoiceCommandText(value: string): string {
    return value
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/[^\p{L}\p{N}\s'-]/gu, ' ')
      .replace(/['-]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  private voiceCommandPackEnabled(settings: WorkspaceVoiceLoopConfig, accepted: string[]): boolean {
    const packs = Array.isArray(settings.command_packs)
      ? settings.command_packs.map((pack) => String(pack).trim().toLowerCase()).filter(Boolean)
      : [];
    if (packs.length === 0) return true;
    return accepted.some((name) => packs.includes(name));
  }

  private handleVoiceCommand(command: string, transcript: string): boolean {
    this.voiceConnection?.voiceCommand(command, transcript, { surface: 'chat' });
    this.voicePartial.set('');
    this.transcribing.set(false);
    this.voiceOracleStage.set('committed');
    this.voiceOracleMessage.set(`Voice command committed: ${command.replace(/_/g, ' ')}.`);

    if (command === 'stop') {
      this.stopConversationLoop('voice_command');
      return true;
    }
    if (command === 'pause') {
      this.pauseConversationLoop();
      return true;
    }
    if (command === 'resume') {
      this.resumeConversationLoop();
      return true;
    }
    if (command === 'cancel') {
      this.userInput = '';
      this.voiceNotice.set('Voice draft cancelled');
      this.scheduleVoiceLoopRearm();
      return true;
    }
    if (command === 'repeat') {
      const last = this.lastAssistantMessage();
      if (!last?.content?.trim()) {
        this.toast.info('No assistant answer to repeat yet', 'Voice');
        this.scheduleVoiceLoopRearm();
        return true;
      }
      if (!this.ttsEnabled() && this.voiceOutputProvider()) this.ttsEnabled.set(true);
      if (this.ttsEnabled()) {
        this.resetTtsPipeline();
        this.queueTtsChunk(last.content);
      }
      return true;
    }
    if (command === 'rephrase') {
      const last = this.lastAssistantMessage();
      if (!last?.content?.trim()) {
        this.toast.info('No assistant answer to rephrase yet', 'Voice');
        this.scheduleVoiceLoopRearm();
        return true;
      }
      this.userInput = 'Reformule ta dernière réponse de façon plus courte et opérationnelle.';
      if (!this.streaming()) queueMicrotask(() => this.send());
      return true;
    }
    if (command === 'next_question' || command === 'validate') {
      this.toast.info('This voice command is available in Knowledge Capture sessions.', 'Voice');
      this.scheduleVoiceLoopRearm();
      return true;
    }
    return false;
  }

  private lastAssistantMessage(): ChatMessage | undefined {
    return [...this.messages()].reverse().find((msg) => msg.role === 'assistant');
  }

  private transcribe(blob: Blob): void {
    if (this.voiceTransport() === 'backend_ws' && this.canUseVoiceSession()) {
      void this.transcribeViaVoiceSession(blob);
      return;
    }
    this.transcribing.set(true);
    const provider = this.voiceInputProvider();
    this.voiceNotice.set(this.voiceRuntimeNotice('Transcribing', provider));
    this.api.transcribeAudio(blob, 'recording.webm', provider).subscribe({
      next: (res) => {
        // The response-side mutation of a plain property (``userInput``)
        // doesn't propagate through OnPush change detection on its own
        // — NgModel only re-reads on an input/event tick. We force a
        // re-check so the textarea picks up the transcribed text and
        // emit a small toast when Whisper returned nothing (silence).
        this.handleFinalVoiceTranscript(String(res?.text || ''), {
          fallbackUsed: !!res?.fallback,
          provider: res?.provider || provider,
        });
        this.transcribing.set(false);
        this.voiceNotice.set(
          res?.fallback
            ? this.voiceRuntimeNotice('Fallback used', res.provider || provider)
            : this.voiceRuntimeNotice('Transcript ready', res.provider || provider),
        );
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.transcribing.set(false);
        this.voiceNotice.set(null);
        this.cdr.markForCheck();
        const detail = this.voiceErrorMessage(err, 'Transcription failed');
        this.toast.error(detail, 'Voice');
      },
    });
  }

	  private async transcribeViaVoiceSession(blob: Blob): Promise<void> {
	    this.transcribing.set(true);
	    this.voicePartial.set('');
	    this.voiceNotice.set(this.voiceRuntimeNotice('Voice session', this.voiceInputProvider()));
	    this.voiceOracleStage.set('thinking');
	    this.voiceOracleMessage.set('Audio segment sent to Agentium voice session; waiting for transcript.');
	    const connection = this.ensureVoiceSession();
    if (!connection) {
      this.voiceTransport.set('batch_http');
      this.transcribe(blob);
      return;
    }
    try {
      const turnId = crypto.randomUUID?.() || String(Date.now());
      await connection.sendAudioFrame(blob, { turn_id: turnId, content_type: blob.type || 'audio/webm' });
      connection.endpoint({
        turn_id: turnId,
        auto: this.voiceLastEndpointReason === 'silence' || this.voiceLastEndpointReason === 'max_turn',
        reason: this.voiceLastEndpointReason,
      });
      this.voiceLastEndpointReason = null;
    } catch (err) {
      this.transcribing.set(false);
      this.voiceNotice.set(null);
      this.toast.error(this.voiceErrorMessage(err, 'Voice session failed'), 'Voice');
      this.closeVoiceSession();
      this.cdr.markForCheck();
    }
  }

  private ensureVoiceSession(): VoiceSessionConnection | null {
    if (this.voiceConnection) return this.voiceConnection;
    try {
      const connection = this.voiceSession.open(this.chatVoiceSessionId);
      this.voiceConnection = connection;
      connection.events$
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe((event) => this.handleVoiceSessionEvent(event));
      connection.start({
        runtime: this.voiceInputProvider(),
        provider: this.voiceInputProvider(),
        transport: 'backend_ws',
        capability: 'voice2voice_interaction',
        mode: 'manual',
        codec: { input: 'webm', channels: 1 },
        fallback_policy: 'cascade_openai',
        tandem_oracle: true,
        oracle: { min_interval_ms: 350, min_delta_chars: 24 },
      });
      return connection;
    } catch {
      this.voiceConnection = null;
      return null;
    }
  }

  private closeVoiceSession(): void {
    this.voiceConnection?.close();
    this.voiceConnection = null;
    this.chatVoiceSessionId = `chat-${crypto.randomUUID?.() || Date.now()}`;
  }

  private handleVoiceSessionEvent(event: VoiceSessionEvent): void {
    if (event.session_id && event.session_id !== this.chatVoiceSessionId) return;
    const payload = event.payload || {};
	    if (event.type === 'session.ready') {
	      this.voiceNotice.set('Voice session ready');
	      this.voiceOracleMessage.set('Session channel ready. Record a voice turn to start oracle tracking.');
	      return;
	    }
	    if (event.type === 'text.partial') {
	      const text = String(payload['text'] || '').trim();
	      if (text) this.voicePartial.set(text);
	      this.voiceOracleStage.set('thinking');
	      this.voiceOracleMessage.set(text ? `Transcript received: “${text.slice(0, 90)}${text.length > 90 ? '…' : ''}”` : 'Transcript received; oracle is updating.');
	      return;
	    }
	    if (event.type === 'text.final') {
	      const text = String(payload['text'] || '').trim();
	      const consumed = this.handleFinalVoiceTranscript(text, {
	        fallbackUsed: !!payload['fallback_used'],
	        provider: this.voiceInputProvider(),
	      });
	      this.voicePartial.set('');
	      this.transcribing.set(false);
	      if (consumed) {
	        this.cdr.markForCheck();
	        return;
	      }
	      this.voiceNotice.set(payload['fallback_used'] ? 'Transcript ready · fallback used' : 'Transcript ready');
	      this.voiceOracleStage.set(payload['fallback_used'] ? 'fallback' : 'committed');
	      this.voiceOracleMessage.set(
	        payload['fallback_used']
	          ? 'Transcript produced through fallback; final voice text is ready.'
	          : 'Final transcript committed for this voice turn.',
	      );
	      this.cdr.markForCheck();
	      return;
	    }
	    if (event.type === 'loop.start' || event.type === 'loop.resume' || event.type === 'loop.armed') {
	      this.voiceNotice.set(event.type === 'loop.armed' ? 'Conversation armed' : 'Conversation loop ready');
	      return;
	    }
	    if (event.type === 'loop.pause' || event.type === 'loop.stop') {
	      this.voiceNotice.set(event.type === 'loop.pause' ? 'Conversation paused' : 'Conversation stopped');
	      return;
	    }
	    if (event.type === 'tts.started') {
	      this.voiceNotice.set('Speaking');
	      return;
	    }
	    if (event.type === 'tts.ended') {
	      this.voiceNotice.set('Voice output complete');
	      this.scheduleVoiceLoopRearm();
	      return;
	    }
	    if (event.type === 'tts.interrupted') {
	      this.voiceNotice.set('Voice output interrupted');
	      return;
	    }
	    if (event.type === 'voice.command') {
	      const command = String(payload['command'] || '').trim();
	      if (command) this.voiceNotice.set(`Voice command · ${command.replace(/_/g, ' ')}`);
	      return;
	    }
	    if (event.type === 'runtime.metric') {
	      const provider = payload['provider'];
	      if (payload['metric'] === 'micro_turn') {
	        this.voiceNotice.set('Tandem oracle tracking micro-turns');
	        this.voiceOracleStage.set('thinking');
	        this.voiceOracleMessage.set('Micro-turn tracked; background oracle is following the conversation.');
	      } else if (provider) {
	        this.voiceNotice.set(this.voiceRuntimeNotice('Voice session', String(provider)));
	      }
	      return;
	    }
	    if (event.type === 'oracle.delta') {
	      this.voiceNotice.set('Tandem oracle updating');
	      this.voiceOracleStage.set('thinking');
	      this.voiceOracleMessage.set('Oracle delta received; the background context is updating.');
	      return;
	    }
	    if (event.type === 'oracle.superseded') {
	      this.voiceNotice.set('Tandem oracle refreshed');
	      this.voiceOracleStage.set('superseded');
	      this.voiceOracleMessage.set('Older oracle signal superseded by a newer transcript state.');
	      return;
	    }
	    if (event.type === 'oracle.action') {
	      const action = String(payload['action'] || 'action').replace(/_/g, ' ');
	      this.voiceNotice.set(`Oracle action · ${action}`);
	      this.voiceOracleStage.set('committed');
	      this.voiceOracleMessage.set(`Oracle action ready: ${action}.`);
	      return;
	    }
	    if (event.type === 'oracle.commit') {
	      this.voiceNotice.set('Oracle committed latest turn');
	      this.voiceOracleStage.set('committed');
	      this.voiceOracleMessage.set('Latest oracle state committed for this turn.');
	      return;
	    }
	    if (event.type === 'session.error') {
	      this.transcribing.set(false);
	      this.voicePartial.set('');
	      this.voiceNotice.set(null);
	      this.voiceOracleStage.set('error');
	      this.voiceOracleMessage.set(String(payload['message'] || 'Voice session failed.'));
	      this.toast.error(String(payload['message'] || 'Voice session failed'), 'Voice');
      this.closeVoiceSession();
      this.cdr.markForCheck();
    }
  }

  private voiceErrorMessage(err: unknown, fallback: string): string {
    const anyErr = err as any;
    const detail = anyErr?.error?.detail;
    if (typeof detail === 'string') return detail;
    if (detail?.message) return String(detail.message);
    if (anyErr?.message) return String(anyErr.message);
    return fallback;
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
    this.api.synthesizeSpeech(clean, 'nova', this.voiceOutputProvider()).subscribe({
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
        if (!this.ttsPlaying && this.ttsQueue.length === 0) this.scheduleVoiceLoopRearm();
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
      this.voiceConnection?.ttsEnded({ surface: 'chat' });
      this.scheduleVoiceLoopRearm();
      return;
    }
    this.ttsPlaying = true;
    this.currentAudio = next;
    this.ttsSpeaking.set(true);
    this.voiceConnection?.ttsStarted({ surface: 'chat' });
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
