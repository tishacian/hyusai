import {
  AfterViewInit,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  DestroyRef,
  ElementRef,
  computed,
  effect,
  inject,
  input,
  signal,
  ViewChild,
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
  VoiceOutputConfig,
  VoiceTtsPlaybackService,
  VoiceTtsState,
} from '@app/core/voice-tts-playback.service';
import {
  VoiceLoopControllerFactory,
  VoiceLoopEndpointReason,
  VoiceLoopState,
} from '@app/core/voice-loop-controller.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { RuntimeHealthService } from '@app/core/runtime-health.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { AssistantEffectsService } from '@app/core/assistant-effects.service';
import { RuntimeStatusBadgeComponent } from '@app/shared/cockpit';
import {
  SharedVoiceOracleStep,
  SharedVoiceRuntimeOption,
  VoiceControlsComponent,
} from '@app/shared/voice/voice-controls.component';
import { DocumentPreviewComponent } from '@app/shared/document-preview/document-preview.component';

interface DecisionStep {
  id: string;
  type?: string;
  title?: string;
  description?: string;
  status?: 'pending' | 'active' | 'completed' | 'warning' | 'error';
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
  // Canonical Run id for this turn — lets the auto-QA polling loop attach its
  // verdict to the right bubble once the judge finishes.
  runId?: string | null;
  // Calm, end-user-facing auto-QA verdict. Present only when the reply
  // breached workspace thresholds. ``reasons`` holds the raw internal metric
  // names and is surfaced ONLY in operator mode.
  qaReview?: {
    compositeScore: number | null;
    reasons: string[];
    decisionId?: string | null;
    runId: string;
  } | null;
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
  grounding?: GroundingConfig;
  prompt_pack?: SuggestionCard[];
  hidden_controls?: string[];
  chat?: WorkspaceChatConfig;
  voice_loop?: WorkspaceVoiceLoopConfig;
  voice_output?: VoiceOutputConfig;
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
type GroundingMode = 'strict' | 'balanced';

interface GroundingConfig {
  default_mode?: GroundingMode;
  allowed_modes?: GroundingMode[];
  fallback_disclaimer?: string;
  strict_guard?: string;
}

interface WorkspaceChatConfig {
  title?: string;
  subtitle?: string;
  placeholder?: string;
  prompt_pack?: SuggestionCard[];
  prompt_pack_by_scope?: Record<string, SuggestionCard[]>;
  session_doc_prompt_pack?: SuggestionCard[];
  use_assistant_profile_prompt_pack?: boolean;
  grounding?: GroundingConfig;
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

interface WorkspaceVoiceOutputConfig extends VoiceOutputConfig {}

interface ActionManifest {
  action_id: string;
  label: string;
  description?: string;
  surfaces?: string[];
  phrases?: string[];
  requires_confirmation?: boolean;
  inherited_from?: string;
  handler?: { kind?: string; name?: string };
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
  imports: [
    FormsModule,
    RouterLink,
    IconComponent,
    RuntimeStatusBadgeComponent,
    VoiceControlsComponent,
    DocumentPreviewComponent,
  ],
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
            <div class="vigie-context-actions">
              <button
                type="button"
                class="vigie-voice-primary"
                [class.vigie-voice-primary-active]="voiceConversationActive() && !voiceConversationPaused()"
                [class.vigie-voice-primary-paused]="voiceConversationPaused()"
                [disabled]="!canUseVoiceSession() || streaming() || transcribing()"
                [title]="executiveVoiceCtaTitle()"
                (click)="startExecutiveVoiceLoop()"
              >
                <app-icon [name]="voiceConversationActive() && !voiceConversationPaused() ? 'mic' : 'play'" [size]="13" />
                {{ executiveVoiceCtaLabel() }}
              </button>
              @if (voiceStopAvailable()) {
                <button
                  type="button"
                  class="vigie-voice-stop"
                  title="Arrêter la voix : couper la lecture et la boucle d’écoute."
                  (click)="stopVoiceExperience()"
                >
                  <app-icon name="square" [size]="13" />
                  Arrêter
                </button>
              }
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
        </div>
      }

      @if (showAdvancedChatControls()) {
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

      @if (showAdvancedChatControls()) {
      <app-voice-controls
        [runtimeOptions]="voiceControlRuntimeOptions()"
        [provider]="voiceProvider()"
        [selectedRuntimeDescription]="selectedVoiceDescription()"
        [transport]="voiceTransport()"
        [transportHint]="voiceTransportHint()"
        [sessionButtonTitle]="voiceSessionButtonTitle()"
        [realtimeBlockedHint]="voiceRealtimeBlockedHint()"
        [canUseSession]="canUseVoiceSession()"
        [canTranscribe]="canTranscribeVoice()"
        [streaming]="streaming()"
        [transcribing]="transcribing()"
        [conversationActive]="voiceConversationActive()"
        [conversationPaused]="voiceConversationPaused()"
        [tandemOracleHint]="voiceTandemOracleHint()"
        [autoSend]="voiceAutoSend()"
        [autoEndpoint]="voiceAutoEndpoint()"
        [statusClass]="voiceStatusClass()"
        [statusLabel]="voiceStatusLabel()"
        [runtimeDetail]="voiceRuntimeDetail()"
        [partial]="voicePartial()"
        [oraclePanelHint]="voiceOraclePanelHint()"
        [oracleMessage]="voiceOracleMessage()"
        [oracleTimeline]="voiceOracleTimeline()"
        (providerChange)="onVoiceProviderChange($event)"
        (transportChange)="setVoiceTransport($event)"
        (startConversation)="startConversationLoop()"
        (pauseConversation)="pauseConversationLoop()"
        (resumeConversation)="resumeConversationLoop()"
        (stopConversation)="stopConversationLoop()"
        (autoSendChange)="voiceAutoSend.set($event)"
        (autoEndpointChange)="voiceAutoEndpoint.set($event)"
      />

      @if (isDemoMode() && !demoVoiceChipsDismissed() && demoVoiceChips().length) {
        <div class="demo-voice-chips">
          <div class="demo-voice-chips-head">
            <span>Phrases demo (fallback voix)</span>
            <button type="button" class="demo-voice-dismiss" (click)="demoVoiceChipsDismissed.set(true)">Masquer</button>
          </div>
          <div class="demo-voice-chip-row">
            @for (chip of demoVoiceChips(); track chip.action_id) {
              <button
                type="button"
                class="action-chip demo-voice-chip"
                [title]="chip.description || chip.label"
                (click)="stageActionPrompt(chip)"
              >
                {{ chip.phrases?.[0] || chip.label }}
              </button>
            }
          </div>
        </div>
      }
      }

      @if (showAdvancedChatControls() && effectiveChatActions().length) {
        <div class="action-surface-bar">
          <span class="action-surface-label">
            <app-icon name="zap" [size]="12" />
            Actions
            <span class="control-info-dot" title="Workspace/system action manifests available to this chat. Voice can resolve the same safe commands from final transcripts.">
              <app-icon name="info" [size]="10" />
            </span>
          </span>
          @for (action of effectiveChatActions(); track action.action_id) {
            <button
              type="button"
              class="action-chip"
              [title]="action.description || action.label"
              (click)="stageActionPrompt(action)"
            >
              {{ action.label }}
              @if (action.requires_confirmation) {
                <span>confirm</span>
              }
            </button>
          }
        </div>
      }

      <!-- Messages -->
      <div
        class="flex-1 min-h-0 overflow-y-auto px-4 py-4 space-y-5"
        [class.vigie-messages]="executiveMode()"
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
            @if (!isDemoMode() && activeSuggestions().length) {
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
            }
            @if (!isDemoMode() && effectiveChatActions().length) {
              <div class="mt-4 flex max-w-2xl flex-wrap items-center justify-center gap-2">
                @for (action of effectiveChatActions().slice(0, 4); track action.action_id) {
                  <button
                    type="button"
                    class="action-empty-chip"
                    [title]="action.description || action.label"
                    (click)="stageActionPrompt(action)"
                  >
                    <app-icon name="zap" [size]="12" />
                    {{ action.label }}
                  </button>
                }
              </div>
            }
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
              @if (!isDemoMode() && msg.decisionSteps && msg.decisionSteps.length > 0) {
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
                  <app-icon
                    name="map-pin"
                    [size]="14"
                    [class.text-sky-300]="!executiveMode()"
                    [class.text-amber-300]="executiveMode()"
                  />
                  <span>
                    Carte stratégique prête · {{ mapCommandLabel(msg.mapCommand) }}
                  </span>
                </div>
              }

              <!-- Missing-citations banner: model cited [N] but the retrieval
                   returned fewer (or zero) chunks. Surface it so operators
                   do not mistake disabled grey chips for a styling bug. -->
              @if (!isDemoMode() && missingCitations(msg); as missing) {
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
                            @if (canPreviewSource(src)) {
                              <button
                                type="button"
                                class="shrink-0 inline-flex items-center justify-center rounded p-1 text-gray-500 hover:text-brand-300 hover:bg-white/5 transition"
                                [class.ml-auto]="src.score == null"
                                title="Preview source document"
                                (click)="previewSource(src); $event.stopPropagation()"
                              >
                                <app-icon name="eye" [size]="12" />
                              </button>
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
              @if (!isDemoMode() && msg.decisionSteps && msg.decisionSteps.length > 0) {
                <div
                  class="ml-0 mt-1 rounded-md px-3 py-2 bg-gradient-to-r from-brand-500/5 to-violet-500/5 ring-1 ring-brand-500/15 flex items-center gap-3 text-[11px] text-gray-700 dark:text-gray-300"
                  [class.hidden]="isDemoMode() || (executiveMode() && !traceOpen())"
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
                @if (!isDemoMode()) {
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
                }
                @if (!isDemoMode() && msg.evaluation) {
                  <span class="ml-auto font-mono text-[10px] text-emerald-400"
                    >Score {{ msg.evaluation.composite_score.toFixed(1) }}</span
                  >
                }
              </div>

              <!-- Calm, end-user-friendly auto-QA marker. Replaces the alarming
                   top toast for everyone; operators additionally get the raw
                   breach metrics inline (and still receive the verbose toast). -->
              @if (msg.qaReview; as qa) {
                <div class="ml-2 mt-1.5 flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    class="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium bg-amber-500/10 text-amber-700 dark:text-amber-300 ring-1 ring-amber-500/25 hover:bg-amber-500/15 transition"
                    [title]="qaReviewTooltip()"
                    (click)="openQaReview(qa.decisionId, qa.runId)"
                  >
                    <app-icon name="shield-alert" [size]="12" />
                    <span>Réponse à vérifier</span>
                  </button>
                  @if (!isDemoMode() && qa.reasons.length) {
                    <span class="text-[10px] font-mono text-gray-500">
                      {{ qa.compositeScore != null ? qa.compositeScore + '/100 · ' : '' }}{{ qa.reasons.slice(0, 3).join(', ') }}
                    </span>
                  }
                </div>
              }

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
            <!-- Staged, plain-language progress (driven by real decision_step
                 lifecycle events). Shown until the answer text starts arriving,
                 in every mode — demo-safe workspaces hide the verbose step list
                 below, so this is their only progress feedback. -->
            @if (streamProgress(); as progress) {
              <div class="flex justify-start">
                <div
                  class="inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-[12px] text-gray-600 dark:text-gray-300 bg-gray-100 dark:bg-white/[0.04] ring-1 ring-white/5"
                  aria-live="polite"
                >
                  <app-icon
                    name="loader-2"
                    [size]="13"
                    class="text-brand-400"
                    [class.animate-spin]="progress.spinning"
                  />
                  <span>{{ progress.label }}</span>
                </div>
              </div>
            }
            @if (!isDemoMode() && liveSteps().length > 0) {
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
            @if (streamBuffer().length > 0) {
              <div class="flex justify-start">
                <div
                  class="max-w-[85%] bg-gray-100 dark:bg-white/[0.04] rounded-2xl rounded-bl-sm px-4 py-2.5 text-sm whitespace-pre-wrap leading-relaxed ring-1 ring-white/5"
                >
                  {{ streamBuffer() }}<span class="inline-block w-1.5 h-4 bg-brand-400 ml-0.5 animate-pulse align-middle"></span>
                </div>
              </div>
            }
          </div>
        }
      </div>

      <!-- Live dictation preview: partial transcript while recording -->
      @if (recording() && voicePartial()) {
        <div class="px-3 pt-2 -mb-1 flex items-center gap-2 text-xs text-gray-400">
          <app-icon name="mic" [size]="12" class="text-brand-300 animate-pulse" />
          <span class="italic truncate">{{ voicePartial() }}</span>
        </div>
      }

      <!-- Input -->
      <form
        (ngSubmit)="send()"
        class="flex items-end gap-2 p-3 border-t border-white/5 bg-white/[0.02]"
        [class.vigie-input-bar]="executiveMode()"
      >
        <button
          type="button"
          class="p-2.5 rounded-xl transition ring-1 relative"
          [class.vigie-mic-button]="executiveMode()"
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
          [disabled]="transcribing() || (!canTranscribeVoice() && !voiceStopAvailable())"
          [title]="voiceMicTitle()"
          (click)="toggleMic()"
        >
          <app-icon
            [name]="transcribing() ? 'loader-2' : (voiceStopAvailable() ? 'square' : 'mic')"
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
          [class.vigie-send-button]="executiveMode()"
        >
          <app-icon [name]="streaming() ? 'loader-2' : 'send'" [size]="14" [class.animate-spin]="streaming()" />
          {{ streaming() ? streamingLabel() : sendLabel() }}
        </button>
      </form>
    </div>

    <app-document-preview
      [open]="sourcePreviewOpen()"
      [previewUrl]="sourcePreviewUrl()"
      [title]="sourcePreviewTitle()"
      subtitle="Retrieval source"
      (closed)="closeSourcePreview()"
    />
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
    .vigie-context-actions {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;
    }
    .vigie-voice-primary {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 36px;
      padding: 8px 13px;
      border-radius: 12px;
      border: 1px solid rgba(101, 214, 110, 0.36);
      background:
        linear-gradient(135deg, rgba(32, 120, 68, 0.90), rgba(20, 70, 47, 0.86)),
        rgba(11, 18, 28, 0.82);
      color: #d9ffdf;
      font-size: 12px;
      font-weight: 750;
      letter-spacing: 0.01em;
      box-shadow:
        0 0 0 1px rgba(101, 214, 110, 0.10) inset,
        0 14px 38px rgba(10, 70, 34, 0.22);
      transition: 140ms ease;
    }
    .vigie-voice-primary:hover:not(:disabled) {
      transform: translateY(-1px);
      border-color: rgba(137, 236, 133, 0.55);
      background:
        linear-gradient(135deg, rgba(40, 145, 80, 0.96), rgba(25, 90, 57, 0.92)),
        rgba(11, 18, 28, 0.82);
      color: #f6fff3;
    }
    .vigie-voice-primary-active {
      border-color: rgba(245, 168, 90, 0.50);
      background:
        linear-gradient(135deg, rgba(242, 140, 56, 0.88), rgba(33, 104, 60, 0.78)),
        rgba(11, 18, 28, 0.82);
      color: #fff6e8;
    }
    .vigie-voice-primary-paused {
      border-color: rgba(245, 168, 90, 0.44);
      color: #ffe1b8;
    }
    .vigie-voice-primary:disabled {
      cursor: not-allowed;
      opacity: 0.48;
      box-shadow: none;
    }
    .vigie-voice-stop {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-height: 36px;
      padding: 8px 12px;
      border-radius: 12px;
      border: 1px solid rgba(248, 113, 113, 0.42);
      background:
        linear-gradient(135deg, rgba(159, 33, 33, 0.88), rgba(94, 18, 18, 0.84)),
        rgba(11, 18, 28, 0.82);
      color: #ffe2e2;
      font-size: 12px;
      font-weight: 750;
      transition: 140ms ease;
    }
    .vigie-voice-stop:hover {
      transform: translateY(-1px);
      border-color: rgba(248, 113, 113, 0.66);
      color: #fff;
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
    @media (max-width: 760px) {
      .vigie-context-actions {
        align-items: stretch;
        flex-direction: column;
      }
      .vigie-voice-primary,
      .vigie-voice-stop,
      .vigie-trace-button {
        justify-content: center;
      }
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
    .action-surface-bar {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      padding: 8px 14px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.055);
      background: rgba(2, 8, 18, 0.28);
    }
    .action-surface-label {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: rgba(177, 190, 210, 0.82);
      font-size: 10px;
      font-weight: 800;
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }
    .action-chip,
    .action-empty-chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 28px;
      border-radius: 10px;
      padding: 5px 9px;
      border: 1px solid rgba(103, 213, 246, 0.16);
      background: rgba(34, 211, 238, 0.07);
      color: rgb(207, 250, 254);
      font-size: 11px;
      font-weight: 700;
      transition: 140ms ease;
    }
    .action-chip:hover,
    .action-empty-chip:hover {
      border-color: rgba(103, 213, 246, 0.35);
      background: rgba(34, 211, 238, 0.13);
    }
    .action-chip span {
      border-radius: 999px;
      padding: 1px 5px;
      background: rgba(245, 158, 11, 0.12);
      color: rgb(253, 230, 138);
      font-size: 9px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .action-empty-chip {
      min-height: 32px;
      background: rgba(255, 255, 255, 0.03);
      color: rgba(232, 239, 250, 0.88);
    }
    .demo-voice-chips {
      margin: 0 12px 10px;
      padding: 10px 12px;
      border: 1px dashed rgba(125, 211, 252, 0.18);
      border-radius: 10px;
      background: rgba(125, 211, 252, 0.04);
    }
    .demo-voice-chips-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 8px;
      color: rgba(148, 197, 229, 0.78);
      font: 750 10px/1 var(--ck-font-mono, ui-monospace, monospace);
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }
    .demo-voice-dismiss {
      border: 0;
      background: transparent;
      color: rgba(148, 197, 229, 0.72);
      font: inherit;
      font-size: 10px;
      cursor: pointer;
    }
    .demo-voice-chip-row {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .demo-voice-chip {
      opacity: 0.88;
      font-size: 11px;
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
      background:
        radial-gradient(circle at 36% 28%, rgba(242, 140, 56, 0.25), transparent 46%),
        linear-gradient(145deg, rgba(11, 30, 18, 0.92), rgba(20, 17, 13, 0.92)) !important;
      color: #f5a85a !important;
      box-shadow: 0 18px 55px rgba(0, 0, 0, 0.26);
    }
    .vigie-empty-state > div:first-child app-icon {
      color: #f5a85a !important;
    }
    .vigie-empty-state button {
      border-radius: 14px !important;
      border: 1px solid rgba(101, 214, 110, 0.13) !important;
      background:
        linear-gradient(135deg, rgba(101, 214, 110, 0.055), rgba(255, 255, 255, 0.018)) !important;
      padding: 14px !important;
    }
    .vigie-empty-state button:hover {
      border-color: rgba(242, 140, 56, 0.26) !important;
      background:
        linear-gradient(135deg, rgba(101, 214, 110, 0.085), rgba(242, 140, 56, 0.050)) !important;
    }
    .vigie-empty-state button .bg-brand-500\\/10,
    .vigie-empty-state button .group-hover\\:bg-brand-500\\/20 {
      background: rgba(101, 214, 110, 0.10) !important;
      color: #d9ffdf !important;
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
      border: 1px solid rgba(101, 214, 110, 0.14) !important;
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
      box-shadow: inset 0 0 0 1px rgba(242, 140, 56, 0.08) !important;
    }
    .vigie-input-bar {
      padding: 14px !important;
      background: rgba(6, 10, 15, 0.82) !important;
      border-top-color: rgba(101, 214, 110, 0.12) !important;
    }
    .vigie-input-bar textarea {
      border-radius: 16px !important;
      border-color: rgba(101, 214, 110, 0.18) !important;
      background: rgba(255, 255, 255, 0.045) !important;
      min-height: 48px;
    }
    .vigie-input-bar textarea:focus {
      border-color: rgba(242, 140, 56, 0.38) !important;
      box-shadow: 0 0 0 2px rgba(242, 140, 56, 0.10) !important;
    }
    .vigie-mic-button {
      border-color: rgba(242, 140, 56, 0.28) !important;
      background: rgba(11, 24, 16, 0.78) !important;
      color: #ffe1b8 !important;
      box-shadow: inset 0 0 0 1px rgba(101, 214, 110, 0.08) !important;
    }
    .vigie-mic-button:hover:not(:disabled) {
      border-color: rgba(101, 214, 110, 0.36) !important;
      color: #d9ffdf !important;
    }
    .vigie-input-bar button[type='submit'] {
      border-radius: 16px !important;
      min-height: 48px;
    }
    .vigie-send-button {
      border: 1px solid rgba(101, 214, 110, 0.32) !important;
      background:
        linear-gradient(135deg, rgba(32, 120, 68, 0.96), rgba(242, 140, 56, 0.72)) !important;
      color: #fff8ec !important;
      box-shadow: 0 18px 38px rgba(5, 45, 20, 0.20) !important;
    }
    .vigie-send-button:hover:not(:disabled) {
      border-color: rgba(242, 140, 56, 0.45) !important;
      background:
        linear-gradient(135deg, rgba(42, 145, 78, 0.98), rgba(242, 140, 56, 0.82)) !important;
    }
  `],
})
export class ChatPanelComponent implements AfterViewInit {
  @ViewChild('inputEl') private inputEl?: ElementRef<HTMLTextAreaElement>;

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
  readonly autoStartVoiceLoop = input(false);

  private readonly sse = inject(SseService);
  private readonly api = inject(ApiService);
  private readonly canonicalApi = inject(CanonicalApiService);
  private readonly toast = inject(ToastrService);
  private readonly router = inject(Router);
  private readonly health = inject(RuntimeHealthService);
  private readonly voiceSession = inject(VoiceSessionService);
  private readonly voiceLoopFactory = inject(VoiceLoopControllerFactory);
  private readonly ttsPlaybackFactory = inject(VoiceTtsPlaybackService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly cdr = inject(ChangeDetectorRef);
  private readonly workspace = inject(WorkspaceService);
  private readonly assistantEffects = inject(AssistantEffectsService);
  readonly settings = inject(SettingsService);

  messages = signal<ChatMessage[]>([]);
  streaming = signal(false);
  streamBuffer = signal('');
  liveSteps = signal<DecisionStep[]>([]);
  evaluatingId = signal<string | null>(null);

  /**
   * Plain-language, staged progress label for the in-flight turn. Driven by
   * the *real* ``decision_step`` lifecycle events emitted by the orchestrator
   * (query_analysis → embedding → retrieve → thought → synthesis), NOT by any
   * artificial timer. Returns ``null`` once the answer text starts streaming —
   * at that point the assistant bubble itself is the progress feedback.
   *
   * This is intentionally NOT gated behind ``isDemoMode()`` so demo-safe
   * workspaces (which hide the verbose decision-step list) still get
   * meaningful progress instead of a blank bubble during the 25-55s retrieval
   * + synthesis window.
   */
  readonly streamProgress = computed<{ label: string; spinning: boolean } | null>(() => {
    if (!this.streaming()) return null;
    // Once tokens arrive the bubble renders them — drop the placeholder.
    if (this.streamBuffer().length > 0) return null;

    const steps = this.liveSteps();
    const byType = (t: string): DecisionStep | undefined =>
      [...steps].reverse().find((s) => s.type === t);

    // Synthesis is active but no text has landed yet → the model is writing.
    if (byType('synthesis')) return { label: 'Rédaction de la réponse…', spinning: true };

    const retrieve = byType('retrieve');
    if (retrieve && (retrieve.status === 'completed' || retrieve.status === 'warning')) {
      const n = this.passagesFound(retrieve);
      const label =
        n != null
          ? `${n} passage${n > 1 ? 's' : ''} trouvé${n > 1 ? 's' : ''} · analyse en cours…`
          : 'Passages analysés…';
      return { label, spinning: true };
    }
    if (byType('thought')) return { label: 'Analyse des passages…', spinning: true };
    if (retrieve || byType('embedding') || byType('query_analysis')) {
      return { label: 'Recherche dans les documents…', spinning: true };
    }
    return { label: 'Préparation de la requête…', spinning: true };
  });
  userInput = '';
  private chatSessionId: string | null = null;
  private chatSessionSignature: string | null = null;
  private creatingChatSession = false;

  readonly ragModeChoices = RAG_MODE_CHOICES;
  readonly ragModeOverride = signal<RagModeChoice>('auto');
  readonly promptType = signal<string>('auto');
  readonly reasoningTemplates = signal<ReasoningTemplate[]>([]);
  readonly voiceRuntimes = signal<VoiceRuntimeCatalog | null>(null);
  readonly effectiveChatActions = signal<ActionManifest[]>([]);
  readonly demoVoiceChips = signal<ActionManifest[]>([]);
  readonly demoVoiceChipsDismissed = signal(false);
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
  readonly showAdvancedChatControls = computed(() =>
    !this.isDemoMode() && (!this.executiveMode() || this.traceOpen()),
  );
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
  readonly groundingMode = computed<GroundingMode | null>(() => {
    const settings = this.workspace.current()?.settings;
    const workspaceChat = this.isRecord(settings?.['chat']) ? settings?.['chat'] : null;
    const workspaceGrounding = this.groundingDefaultMode(
      this.isRecord(workspaceChat) ? workspaceChat['grounding'] : null,
    );
    const profileGrounding = this.groundingDefaultMode(this.activeAssistantProfile()?.grounding);
    return profileGrounding ?? workspaceGrounding ?? (this.executiveMode() ? 'balanced' : null);
  });
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
  readonly workspaceVoiceOutputConfig = computed<WorkspaceVoiceOutputConfig>(() => {
    const settings = this.workspace.current()?.settings;
    const workspaceConfig = this.isRecord(settings?.['voice_output']) ? settings?.['voice_output'] : {};
    const profileConfig = this.activeAssistantProfile()?.voice_output;
    return {
      latency_profile: 'fast',
      voice: 'nova',
      flush_first_chars: 18,
      flush_next_chars: 56,
      flush_timeout_ms: 450,
      interrupt_on_user_speech: true,
      ...(this.isRecord(workspaceConfig) ? workspaceConfig : {}),
      ...(this.isRecord(profileConfig) ? profileConfig : {}),
    } as WorkspaceVoiceOutputConfig;
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
    if (this.isDemoMode()) return 'Rechercher dans les connaissances';
    if (this.executiveMode()) return `Interroger ${this.assistantLabel()}`;
    if (this.activeAssistantProfile()) return `Ask ${this.assistantLabel()}`;
    return 'Start a conversation';
  });
  readonly emptySubtitle = computed(() => {
    const configured = this.workspaceChatConfig().subtitle;
    if (configured) return configured;
    if (this.isDemoMode()) {
      const label = this.scopeLabel(this.activeKnowledgeScope());
      return label && label !== 'workspace'
        ? `Posez une question sur ${label}. La réponse cite les sources utilisées.`
        : 'Posez une question sur les documents du workspace. La réponse cite les sources utilisées.';
    }
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
    if (this.isDemoMode()) {
      const label = this.scopeLabel(this.activeKnowledgeScope());
      return label && label !== 'workspace'
        ? `Posez votre question sur ${label}...`
        : 'Posez votre question sur les documents...';
    }
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
  readonly sendLabel = computed(() => this.isDemoMode() || this.executiveMode() ? 'Interroger' : 'Send');
  readonly streamingLabel = computed(() => this.isDemoMode() || this.executiveMode() ? 'En cours…' : 'Streaming');

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

  readonly voiceControlRuntimeOptions = computed<SharedVoiceRuntimeOption[]>(() =>
    this.voiceRuntimeOptions().map((runtime) => ({
      slug: runtime.slug,
      label: this.voiceRuntimeLabel(runtime),
      disabled: !this.isVoiceRuntimeSelectableInChat(runtime),
    })),
  );

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

  readonly voiceStatusLabel = computed<string>(() => {
    const runtime = this.selectedVoiceRuntime();
    if (!runtime) return 'runtime unknown';
    const notice = this.voiceNotice();
    if (notice) return notice;
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

		  readonly voiceOracleTimeline = computed<SharedVoiceOracleStep[]>(() => {
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
		    const mkState = (stepRank: number, stepStage: VoiceOracleStage): SharedVoiceOracleStep['state'] => {
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

  // Source document preview (reuses the shared Knowledge/SFTP viewer drawer).
  readonly sourcePreviewOpen = signal(false);
  readonly sourcePreviewUrl = signal<string | null>(null);
  readonly sourcePreviewTitle = signal('');
  /**
   * Expanded evaluation steps, keyed by ``"${messageId}:${stepId}"``. Kept
   * separate from ``openTrails`` so operators can dive into a specific
   * metric card without expanding every other step below it.
   */
  private readonly openEvals = signal<Set<string>>(new Set());
  private voiceConnection: VoiceSessionConnection | null = null;
  private readonly voiceLoop = this.voiceLoopFactory.create('chat');
  private readonly ttsPlayback = this.ttsPlaybackFactory.createController('chat');
  private chatVoiceSessionId = `chat-${crypto.randomUUID?.() || Date.now()}`;
  private streamStart = 0;
  private voiceLoopRearmTimer: ReturnType<typeof setTimeout> | null = null;
  private voiceLastEndpointReason: VoiceLoopEndpointReason | null = null;
  private appliedVoiceDefaultsSignature = '';
  /**
   * Streaming-turn state. When the conversation loop runs over a backend_ws
   * session we stream MediaRecorder chunks to the gateway as they arrive
   * (rather than sending one blob on endpoint), and run throttled partial
   * transcription so the tandem oracle can react live to in-progress speech.
   */
  private voiceTurnId: string | null = null;
  private voiceTurnChunks: Blob[] = [];
  private voiceTurnStreaming = false;
  private voiceFramesStreamed = false;
  private voicePartialInFlight = false;
  private lastVoicePartialAt = 0;
  private pendingVoiceFrameSends: Promise<void>[] = [];
  /**
   * Signals reflecting TTS transport state so the template can show a
   * pause/resume button only while audio is actually being prepared,
   * queued or played.
   */
  readonly ttsSpeaking = signal(false);
  readonly ttsPaused = signal(false);

  private initialPromptApplied = false;
  private autoVoiceLoopStarted = false;

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
    effect(() => {
      if (!this.autoStartVoiceLoop() || this.autoVoiceLoopStarted) return;
      if (!this.canUseVoiceSession()) return;
      this.autoVoiceLoopStarted = true;
      queueMicrotask(() => {
        void this.startConversationLoop();
      });
    });
    effect(() => {
      const workspaceSlug = this.workspace.current()?.slug || '';
      const profileKey = this.activeAssistantProfile()?.key || this.assistantProfileKey() || '';
      const systemId = this.systemId() || '';
      if (!workspaceSlug) return;
      this.loadEffectiveChatActions(profileKey, systemId);
      this.loadDemoVoiceActions(profileKey, systemId);
    });
    this.settings.refresh();
    this.health.load().subscribe();
    this.loadReasoningTemplates();
    this.loadVoiceRuntimes();
    this.destroyRef.onDestroy(() => {
      this.clearVoiceLoopRearmTimer();
      this.voiceLoop.dispose();
      this.ttsPlayback.destroy();
      this.voiceConnection?.close();
    });
  }

  ngAfterViewInit(): void {
    this.focusComposer(120);
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

  private loadEffectiveChatActions(assistantProfile: string, systemId: string): void {
    const params: Record<string, string> = { surface: 'chat' };
    if (assistantProfile) params['assistant_profile'] = assistantProfile;
    if (systemId) params['system_id'] = systemId;
    this.api.get<{ actions: ActionManifest[] }>('/actions/effective', params).subscribe({
      next: (res) => this.effectiveChatActions.set((res?.actions || []).filter((action) => !action.action_id.startsWith('voice.')).slice(0, 8)),
      error: () => this.effectiveChatActions.set([]),
    });
  }

  private loadDemoVoiceActions(assistantProfile: string, systemId: string): void {
    if (!this.isDemoMode()) {
      this.demoVoiceChips.set([]);
      return;
    }
    const params: Record<string, string> = { surface: 'voice' };
    if (assistantProfile) params['assistant_profile'] = assistantProfile;
    if (systemId) params['system_id'] = systemId;
    this.api.get<{ actions: ActionManifest[] }>('/actions/effective', params).subscribe({
      next: (res) => {
        const chips = (res?.actions || [])
          .filter((action) => Array.isArray(action.phrases) && action.phrases.length > 0)
          .slice(0, 3)
          .map((action) => ({
            ...action,
            label: action.phrases?.[0] || action.label,
          }));
        this.demoVoiceChips.set(chips);
      },
      error: () => this.demoVoiceChips.set([]),
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

  executiveVoiceCtaLabel(): string {
    if (!this.canUseVoiceSession()) return 'Voix indisponible';
    if (this.voiceConversationPaused()) return 'Reprendre AYA';
    if (this.voiceConversationActive()) return 'AYA écoute';
    return 'Parler à AYA';
  }

  executiveVoiceCtaTitle(): string {
    if (!this.canUseVoiceSession()) return this.voiceSessionButtonTitle();
    if (this.voiceConversationPaused()) return 'Relancer la boucle vocale AYA.';
    if (this.voiceConversationActive()) return 'La session vocale AYA est active. Les commandes stop, pause et annule restent disponibles.';
    return 'Démarrer une conversation vocale persistante avec AYA.';
  }

  startExecutiveVoiceLoop(): void {
    if (!this.canUseVoiceSession() || this.streaming() || this.transcribing()) return;
    if (this.voiceConversationPaused()) {
      this.resumeConversationLoop();
      return;
    }
    if (this.voiceConversationActive()) return;
    void this.startConversationLoop();
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
    if (this.voiceConversationActive()) {
      if (this.voiceConversationPaused()) return 'Conversation loop paused. Press Resume to reopen the microphone.';
      return 'Arrêter la voix : couper la lecture et la boucle d’écoute (sans relance).';
    }
    if (!this.canTranscribeVoice() && !this.voiceStopAvailable())
      return this.isDemoMode() ? 'Voice runtime cannot transcribe audio' : 'Selected provider cannot transcribe voice';
    if (this.ttsSpeaking()) return 'Couper la lecture vocale en cours.';
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

  private sourceDocumentId(src: Source): string {
    const meta = (src.metadata ?? {}) as Record<string, unknown>;
    return (
      (src.document_id as string | undefined) ||
      (meta['document_id'] as string | undefined) ||
      ''
    );
  }

  /** A source is previewable when we can resolve a document id + collection. */
  canPreviewSource(src: Source): boolean {
    return !!this.sourceDocumentId(src) && !!this.sourceCollection(src);
  }

  previewSource(src: Source): void {
    const documentId = this.sourceDocumentId(src);
    const collection = this.sourceCollection(src);
    if (!documentId || !collection) return;
    const filename =
      (src.filename as string | undefined) ||
      ((src.metadata as any)?.filename as string | undefined) ||
      '';
    let url =
      `${this.api.base}/documents/${encodeURIComponent(documentId)}/rich-preview` +
      `?collection_name=${encodeURIComponent(collection)}`;
    if (filename) url += `&filename=${encodeURIComponent(filename)}`;
    this.sourcePreviewTitle.set(this.sourceTitle(src));
    this.sourcePreviewUrl.set(url);
    this.sourcePreviewOpen.set(true);
    this.cdr.markForCheck();
  }

  closeSourcePreview(): void {
    this.sourcePreviewOpen.set(false);
    this.sourcePreviewUrl.set(null);
    this.cdr.markForCheck();
  }

  useSuggestion(s: SuggestionCard): void {
    this.userInput = s.prompt;
    this.voiceOracleMessage.set('Question prête. Complétez si besoin, puis envoyez.');
    this.cdr.markForCheck();
    this.focusComposer();
  }

  stageActionPrompt(action: ActionManifest): void {
    const phrase = action.phrases?.[0] || action.label;
    this.userInput = phrase;
    this.voiceOracleMessage.set(action.requires_confirmation ? `Action proposed: ${action.label}. Confirmation will be requested if it changes data.` : `Action ready: ${action.label}.`);
    this.cdr.markForCheck();
    this.focusComposer();
  }

  private focusComposer(delayMs = 0): void {
    window.setTimeout(() => {
      if (!this.streaming()) this.inputEl?.nativeElement.focus();
    }, delayMs);
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
        return [this.normalizeSuggestionCard(card)];
      });
  }

  private normalizeSuggestionCard(card: SuggestionCard): SuggestionCard {
    const label = card.label.trim().toLowerCase();
    const prompt = card.prompt.trim().toLowerCase();
    const keepScope = {
      scope_key: card.scope_key,
      knowledge_scope: card.knowledge_scope,
      source_key: card.source_key,
      context_mode: card.context_mode,
    };
    if (
      label === 'find a value' ||
      prompt.includes('find the value of a business parameter') ||
      label === 'find evidence'
    ) {
      return {
        ...keepScope,
        icon: 'search',
        label: 'Poser une question',
        prompt: 'Que disent les documents sur [votre sujet] ? Cite les sources utilisées.',
      };
    }
    if (
      label === 'evidence gap' ||
      prompt.includes('what is missing') ||
      prompt.includes('missing evidence') ||
      label === 'check confidence'
    ) {
      return {
        ...keepScope,
        icon: 'shield-check',
        label: 'Vérifier les sources',
        prompt: 'Réponds à la question avec les documents disponibles. Si aucun passage ne répond clairement, indique-le simplement.',
      };
    }
    if (
      label === 'locate the table' ||
      prompt.includes('find the table or section') ||
      label === 'ready for knowledge'
    ) {
      return {
        ...keepScope,
        icon: 'file-search',
        label: 'Retrouver un passage',
        prompt: 'Retrouve le passage, la procédure ou la section qui explique [votre sujet], avec le document source.',
      };
    }
    if (
      label === 'cited answer' ||
      label === 'sourced answer' ||
      label === 'answer with sources' ||
      prompt.includes('citations for every factual claim')
    ) {
      return {
        ...keepScope,
        icon: 'book-open',
        label: 'Réponse sourcée',
        prompt: 'Réponds à ma question uniquement avec les documents sélectionnés et cite les sources utiles.',
      };
    }
    if (label === 'find mismatch' || label === 'compare sources') {
      return {
        ...keepScope,
        icon: 'split',
        label: 'Comparer',
        prompt: 'Compare les informations disponibles sur [votre sujet] et indique les sources utilisées.',
      };
    }
    return card;
  }

  private workspaceSuggestions(): SuggestionCard[] {
    return [
      {
        icon: 'search',
        label: 'Poser une question',
        prompt: 'Que disent les documents du workspace sur [votre sujet] ? Cite les sources utilisées.',
      },
      {
        icon: 'file-search',
        label: 'Retrouver un passage',
        prompt: 'Retrouve le passage, la procédure ou la section qui explique [votre sujet].',
      },
      {
        icon: 'split',
        label: 'Comparer',
        prompt: 'Compare les informations disponibles sur [votre sujet] dans les documents.',
      },
      {
        icon: 'list-checks',
        label: 'Résumer',
        prompt: 'Résume les points clés sur [votre sujet] avec les sources utiles.',
      },
    ];
  }

  private knowledgeSourceSuggestions(): SuggestionCard[] {
    const sourceLabel = this.scopeLabel(this.activeKnowledgeScope());
    return [
      {
        icon: 'search',
        label: 'Poser une question',
        prompt: `Que disent les documents ${sourceLabel} sur [votre sujet] ? Cite les sources utilisées.`,
      },
      {
        icon: 'file-search',
        label: 'Retrouver un passage',
        prompt: `Retrouve dans ${sourceLabel} le passage, la procédure ou la section qui explique [votre sujet].`,
      },
      {
        icon: 'split',
        label: 'Comparer',
        prompt: `Compare les informations disponibles dans ${sourceLabel} sur [votre sujet].`,
      },
      {
        icon: 'list-checks',
        label: 'Résumer',
        prompt: `Résume les points clés trouvés dans ${sourceLabel} sur [votre sujet], avec les sources utiles.`,
      },
    ];
  }

  private sessionDocSuggestions(): SuggestionCard[] {
    const mode = this.sessionDocsMode();
    const sourceLabel = this.scopeLabel(this.activeKnowledgeScope());
    return [
      {
        icon: 'list-checks',
        label: 'Résumer les fichiers',
        prompt: mode === 'combine'
          ? `Résume les fichiers ajoutés et complète avec ${sourceLabel} si utile, en citant les sources.`
          : 'Résume les fichiers ajoutés et cite les noms de fichiers utilisés.',
      },
      {
        icon: 'search',
        label: 'Question aux fichiers',
        prompt: 'Réponds à ma question à partir des fichiers ajoutés, avec les sources utiles.',
      },
      {
        icon: 'split',
        label: 'Comparer',
        prompt: mode === 'combine'
          ? `Compare les fichiers ajoutés avec ${sourceLabel} sur [votre sujet].`
          : 'Compare les informations disponibles dans les fichiers ajoutés sur [votre sujet].',
      },
      {
        icon: 'file-text',
        label: 'Préparer une note',
        prompt: 'Prépare une note courte à partir des fichiers ajoutés, avec les sources à vérifier.',
      },
    ];
  }

  private isRecord(value: unknown): value is Record<string, unknown> {
    return !!value && typeof value === 'object' && !Array.isArray(value);
  }

  private groundingDefaultMode(value: unknown): GroundingMode | null {
    if (!this.isRecord(value)) return null;
    const mode = value['default_mode'];
    return mode === 'strict' || mode === 'balanced' ? mode : null;
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

  /**
   * Best-effort passage count for the retrieval step. The orchestrator encodes
   * it in the step description (``"Retrieved N chunks…"``) and in a structured
   * ``details`` array (``"Retrieved: N/top_k documents"``); we read whichever is
   * present so the staged progress label can say "N passages trouvés".
   */
  private passagesFound(step: DecisionStep): number | null {
    const raw = step as unknown as { details?: unknown; scores?: unknown };
    if (Array.isArray(raw.details)) {
      for (const d of raw.details as unknown[]) {
        const m = String(d).match(/Retrieved:\s*(\d+)\s*\//i);
        if (m) return Number(m[1]);
      }
    }
    const desc = step.description ?? '';
    const m = desc.match(/Retrieved\s+(\d+)\s+chunks/i);
    if (m) return Number(m[1]);
    if (Array.isArray(raw.scores)) return (raw.scores as unknown[]).length;
    return null;
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
    if (this.ttsEnabled()) {
      this.beginTtsStream();
    }

    const s = this.settings.settings();
    let buffer = '';
    let reasoning: DecisionStep[] = [];
    let sources: Source[] | undefined;
    let mapCommand: Record<string, unknown> | undefined;
    let turnRunId: string | undefined;

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
        grounding_mode: this.groundingMode(),
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
          // The canonical Run id can ride along any chunk (special-path text
          // chunks and the trailing ``eval_pending`` chunk both carry it).
          // Remember it so the auto-QA verdict can be pinned to this bubble.
          if (chunk.run_id) turnRunId = chunk.run_id;
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
            // Backend builds these chunks via ``{"chunk_type": "map_command", **command}``
            // (see executor.execute_flow_action), so the command payload — including
            // ``map_state.camera`` used by workspace-map to flyTo Zone Nord — is
            // spread directly onto the chunk. Strip the ``chunk_type`` sentinel
            // before forwarding so listeners receive the raw command object with
            // ``target``, ``map_state``, ``explanation``, ``sources``, etc.
            const { chunk_type: _ct, ...command } = chunk as Record<string, unknown>;
            mapCommand = command;
            window.dispatchEvent(new CustomEvent('agentium:map-command', { detail: mapCommand }));
          } else if (chunk.chunk_type === 'action_effect') {
            // ``chunk`` is the spread of an executor ``_action_effect`` dict
            // and carries ``effect: "<kind>"`` plus the payload. The previous
            // implementation peeled the ``effect`` string off and forwarded
            // it as the payload, which broke ``handleActionEffect``'s
            // kind detection. Forward the whole chunk so the kind string is
            // visible to ``handleActionEffect``.
            this.assistantEffects.handleActionEffect(chunk as Record<string, unknown>);
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
              runId: turnRunId ?? null,
              qaReview: null,
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
              if (this.ttsEnabled()) this.resetTtsPipeline();
              this.scheduleVoiceLoopRearm();
            }
            this.focusComposer();
          }
        },
        error: () => {
          this.toast.error('Connection lost while streaming', 'Chat');
          this.streaming.set(false);
          this.streamBuffer.set('');
          this.liveSteps.set([]);
          if (this.ttsEnabled()) this.resetTtsPipeline();
          this.scheduleVoiceLoopRearm();
          this.focusComposer();
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
      grounding_mode: this.groundingMode(),
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
    const reasons = (res.reasons ?? [])
      .map((r) => r.metric)
      .filter((m): m is string => Boolean(m));
    const score = res.composite_score != null ? Math.round(res.composite_score) : null;

    // Primary, end-user-friendly affordance: pin a calm "à vérifier" marker on
    // the bubble itself. No jargon, no alarming top toast. The detailed review
    // stays reachable via the badge's discreet "Voir le détail" action.
    this.attachQaReview(res.run_id, {
      compositeScore: score,
      reasons,
      decisionId: res.decision_id ?? null,
      runId: res.run_id,
    });

    // Operator/debug context only: keep the verbose breach toast so reviewer
    // tooling (raw metric names, one-tap deeplink) is not regressed. End users
    // in demo-safe workspaces never see this.
    if (!this.isDemoMode()) {
      const metricList = reasons.slice(0, 3).join(', ');
      const title = 'Reply flagged by auto-QA';
      const scoreLabel = score != null ? `${score}` : '—';
      const msg = metricList
        ? `Composite ${scoreLabel}/100 · breaches: ${metricList} · tap to review`
        : `Composite ${scoreLabel}/100 · tap to review`;
      const t: ActiveToast<unknown> = this.toast.warning(msg, title, {
        timeOut: 10000,
        closeButton: true,
        tapToDismiss: false,
        enableHtml: false,
      });
      t.onTap.subscribe(() => this.openQaReview(res.decision_id ?? null, res.run_id));
    }
  }

  /**
   * Pin the auto-QA verdict to the matching assistant bubble (by Run id). The
   * polling loop can resolve slightly before or after the ``done`` chunk
   * creates the bubble; either way ``messages`` is updated in place when the
   * bubble exists.
   */
  private attachQaReview(
    runId: string,
    review: NonNullable<ChatMessage['qaReview']>,
  ): void {
    this.messages.update((msgs) =>
      msgs.map((m) => (m.runId === runId ? { ...m, qaReview: review } : m)),
    );
  }

  /** Plain-language tooltip for the "Réponse à vérifier" badge. */
  qaReviewTooltip(): string {
    return 'Le contrôle qualité automatique recommande de vérifier cette réponse avant de l’utiliser. Cliquez pour consulter le détail.';
  }

  /** Navigate to the detailed QA review for a flagged reply (opt-in). */
  openQaReview(decisionId: string | null | undefined, runId: string): void {
    // Deeplink priority: if the breach already produced a Decision row we jump
    // to the review queue (so the reviewer can accept/reject inline);
    // otherwise we fall back to the Run inspector for raw context.
    if (decisionId) {
      this.router.navigate(['/steering', 'review-queue'], {
        queryParams: { decision: decisionId },
      });
    } else {
      this.router.navigate(['/runs', runId]);
    }
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
    } else if (!this.streaming() && !this.ttsSpeaking()) {
      this.speakLastAssistantAnswer();
    }
  }

  async toggleMic(): Promise<void> {
    // In a Conversation-default workspace the microphone toggles the whole
    // continuous loop (auto-rearm + tandem oracle + stop triggers) instead of
    // a single batch turn, so the Quick-ask surface gets the same behaviour as
    // the advanced voice controls without an extra button.
    if (this.voiceConversationActive()) {
      this.stopConversationLoop();
      return;
    }
    if (this.recording()) {
      this.voiceLoop.stopTurn('manual');
      return;
    }
    // No loop and not recording, but the assistant is still reading the answer
    // aloud: the on-screen text is already complete, so STOP just cuts the TTS.
    if (this.ttsSpeaking()) {
      this.stopVoiceExperience();
      return;
    }
    if (this.conversationModeIsDefault()) {
      await this.startConversationLoop();
      return;
    }
    await this.startVoiceTurn(false);
  }

  /** True while there is something to STOP: an active conversation loop, a live
   * recording, or the assistant reading the answer aloud. Drives the mic
   * button's stop (square) affordance and the executive STOP control. */
  voiceStopAvailable(): boolean {
    return this.voiceConversationActive() || this.recording() || this.ttsSpeaking();
  }

  /**
   * The explicit STOP the user asked for: immediately cut any TTS voice-out and
   * hard-stop the loop so it does not auto-rearm. The on-screen answer is kept.
   */
  stopVoiceExperience(): void {
    if (this.voiceConversationActive()) {
      this.stopConversationLoop();
      return;
    }
    this.clearVoiceLoopRearmTimer();
    if (this.recording()) {
      this.voiceLoop.hardStop({ cancelTts: () => this.resetTtsPipeline() });
      this.recording.set(false);
    } else if (this.ttsSpeaking()) {
      this.resetTtsPipeline();
    }
    this.voiceConnection?.ttsInterrupted({ reason: 'user_stop', surface: 'chat' });
    this.voiceNotice.set('Lecture coupée');
    this.cdr.markForCheck();
  }

  /** True when the workspace voice default is Conversation and the runtime can
   * open a streaming voice session. */
  private conversationModeIsDefault(): boolean {
    return this.workspaceVoiceLoopConfig().default_mode === 'session_loop' && this.canUseVoiceSession();
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

      const autoEndpoint = fromConversationLoop || this.voiceAutoEndpoint();
      this.voiceConnection?.loopArmed({
        surface: 'chat',
        mode: fromConversationLoop ? 'conversation_loop' : 'manual_turn',
        auto_endpoint: autoEndpoint,
      });
      this.voiceOracleStage.set('listening');
      this.voiceOracleMessage.set(
        autoEndpoint
          ? 'Listening: the assistant will end this voice turn after a short silence.'
          : 'Listening: press the microphone again to end this voice turn.',
      );

      // Stream audio chunks to the gateway (live) when the conversation loop is
      // running over a backend_ws session. This drives per-chunk transcription
      // and the tandem oracle while the user is still speaking, instead of one
      // big blob on endpoint.
      const streamTurn =
        fromConversationLoop && this.voiceTransport() === 'backend_ws' && this.canUseVoiceSession();
      // A standard (non-streaming) dictation turn still shows live partial text
      // as the user speaks: the recorder emits timeslice chunks and we run
      // throttled HTTP partial transcription into `voicePartial`.
      const livePartialTurn = !streamTurn && this.canTranscribeVoice();
      this.voiceTurnStreaming = streamTurn;
      this.voiceFramesStreamed = false;
      this.voiceTurnChunks = [];
      this.voicePartialInFlight = false;
      this.lastVoicePartialAt = 0;
      this.voicePartial.set('');
      if (streamTurn) {
        this.voiceTurnId = crypto.randomUUID?.() || String(Date.now());
        this.ensureVoiceSession();
      } else if (livePartialTurn) {
        this.voiceTurnId = crypto.randomUUID?.() || String(Date.now());
      } else {
        this.voiceTurnId = null;
      }

      const started = await this.voiceLoop.startTurn({
        autoEndpoint,
        mimeType: 'audio/webm',
        timesliceMs: streamTurn || livePartialTurn ? 1200 : undefined,
        silenceMs: this.voiceEndpointSilenceMs(),
        minSpeechMs: this.voiceEndpointMinSpeechMs(),
        maxTurnMs: this.voiceEndpointMaxTurnMs(),
        rmsThreshold: this.voiceEndpointRmsThreshold(),
        onChunk: streamTurn
          ? (chunk) => this.onConversationVoiceChunk(chunk)
          : livePartialTurn
            ? (chunk) => this.onManualVoiceChunk(chunk)
            : undefined,
        onState: (state) => this.syncVoiceLoopState(state),
        onSpeechStart: () => {
          this.voiceOracleStage.set('listening');
          this.voiceOracleMessage.set('Speech detected. The assistant will submit after silence.');
          if (this.ttsSpeaking() && this.voiceLoopBargeInEnabled()) {
            this.voiceConnection?.bargeIn();
            this.voiceConnection?.ttsInterrupted({ reason: 'user_speech', surface: 'chat' });
            this.resetTtsPipeline();
          }
        },
        onNotice: (message) => this.voiceNotice.set(message),
        onEndpoint: (blob, reason) => {
          this.recording.set(false);
          if (reason === 'no_speech') {
            this.voiceLastEndpointReason = null;
            this.voiceNotice.set('No speech detected');
            this.voiceOracleStage.set('idle');
            this.voiceOracleMessage.set('No voice turn was submitted. The microphone will reopen automatically.');
            this.scheduleVoiceLoopRearm();
            this.cdr.markForCheck();
            return;
          }
          this.voiceLastEndpointReason = reason;
          this.voiceNotice.set(this.voiceEndpointNotice(reason));
          this.voiceOracleStage.set('thinking');
          this.voiceOracleMessage.set('Voice turn ended; transcribing final audio.');
          if (this.voiceTurnStreaming && this.voiceFramesStreamed) {
            void this.finishStreamingVoiceTurn(reason);
          } else {
            this.transcribe(blob);
          }
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
    this.voiceLoop.hardStop({
      disableRearm: () => this.clearVoiceLoopRearmTimer(),
      cancelTts: () => {
        if (this.ttsSpeaking()) this.resetTtsPipeline();
      },
    });
    this.recording.set(false);
    this.transcribing.set(false);
    this.voicePartial.set('');
    this.voiceLastEndpointReason = null;
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
    if (reason === 'no_speech') return 'No speech detected';
    if (reason === 'pause') return 'Voice turn paused';
    if (reason === 'stop') return 'Voice turn stopped';
    return 'Voice turn ended';
  }

  private handleFinalVoiceTranscript(
    rawText: string,
    options: { fallbackUsed?: boolean; provider?: string | null } = {},
  ): boolean {
    const text = rawText.trim();
    // The final transcript supersedes the live preview.
    this.voicePartial.set('');
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
        this.beginTtsStream();
        this.flushTrailingTts(last.content);
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

  private speakLastAssistantAnswer(): void {
    const last = this.lastAssistantMessage();
    const text = last?.content?.trim();
    if (!text) return;
    this.resetTtsPipeline();
    this.beginTtsStream();
    this.flushTrailingTts(text);
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
	    this.voiceOracleMessage.set('Audio segment sent to the voice session; waiting for transcript.');
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

  /** Handle one MediaRecorder timeslice while a streaming conversation turn is
   * in progress: forward it to the gateway only. The gateway is now the single
   * source of truth for live partials — it transcribes the growing buffer
   * server-side and emits `transcript.partial` events that drive `voicePartial`
   * (see handleVoiceSessionEvent). We no longer re-transcribe client-side here,
   * which removes the previous double transcription. */
  private onConversationVoiceChunk(chunk: Blob): void {
    if (!this.voiceTurnStreaming || chunk.size <= 0) return;
    this.voiceTurnChunks.push(chunk);
    const connection = this.voiceConnection;
    if (connection) {
      const send = connection
        .sendAudioFrame(chunk, { turn_id: this.voiceTurnId, content_type: chunk.type || 'audio/webm' })
        .then(() => {
          this.voiceFramesStreamed = true;
        })
        .catch(() => {
          // Frame transport failed; finalise this turn with a single blob.
          this.voiceTurnStreaming = false;
        });
      this.pendingVoiceFrameSends.push(send);
      void send.finally(() => {
        this.pendingVoiceFrameSends = this.pendingVoiceFrameSends.filter((item) => item !== send);
      });
    }
  }

  /** Handle one MediaRecorder timeslice during a standard (non-conversation)
   * dictation turn: buffer it and run throttled partial STT for live display. */
  private onManualVoiceChunk(chunk: Blob): void {
    if (chunk.size <= 0) return;
    this.voiceTurnChunks.push(chunk);
    this.maybeTranscribeManualPartial();
  }

  /** Throttled (~1.5s) partial transcription of the dictation captured so far,
   * shown live in `voicePartial`. The final transcript still arrives through the
   * normal endpoint path; this only drives the live preview. */
  private maybeTranscribeManualPartial(): void {
    if (this.voicePartialInFlight || this.voiceTurnChunks.length < 2) return;
    const now = Date.now();
    if (now - this.lastVoicePartialAt < 1500) return;
    this.voicePartialInFlight = true;
    this.lastVoicePartialAt = now;
    const turnId = this.voiceTurnId;
    const blob = new Blob(this.voiceTurnChunks, { type: 'audio/webm' });
    this.api
      .transcribeAudio(blob, 'partial.webm', this.voiceInputProvider())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.voicePartialInFlight = false;
          const text = String(res?.text || '').trim();
          if (!text || turnId !== this.voiceTurnId || !this.recording()) return;
          this.voicePartial.set(text);
          this.cdr.markForCheck();
        },
        error: () => {
          this.voicePartialInFlight = false;
        },
      });
  }

  /** Finalise a streamed conversation turn: flush any in-flight frames then
   * signal the endpoint. The gateway transcribes from the buffered frames, so
   * we never resend the whole blob (which would duplicate the audio). */
  private async finishStreamingVoiceTurn(reason: VoiceLoopEndpointReason): Promise<void> {
    this.transcribing.set(true);
    this.voiceOracleStage.set('thinking');
    this.voiceNotice.set(this.voiceRuntimeNotice('Voice session', this.voiceInputProvider()));
    this.voiceOracleMessage.set('Finalising the streamed voice turn; waiting for the transcript.');
    const connection = this.voiceConnection;
    if (!connection) {
      this.voiceTurnStreaming = false;
      this.transcribe(new Blob(this.voiceTurnChunks, { type: 'audio/webm' }));
      return;
    }
    const pending = [...this.pendingVoiceFrameSends];
    this.pendingVoiceFrameSends = [];
    if (pending.length) await Promise.allSettled(pending);
    connection.endpoint({
      turn_id: this.voiceTurnId,
      auto: reason === 'silence' || reason === 'max_turn',
      reason,
    });
    this.voiceLastEndpointReason = null;
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
	    if (event.type === 'text.partial' || event.type === 'transcript.partial') {
	      // Server is the single source of truth for live partials: the gateway
	      // emits these mid-utterance from its server-side incremental STT.
	      const text = String(payload['text'] || '').trim();
	      if (text) this.voicePartial.set(text);
	      this.voiceOracleStage.set('thinking');
	      this.voiceOracleMessage.set(text ? `Transcript received: “${text.slice(0, 90)}${text.length > 90 ? '…' : ''}”` : 'Transcript received; oracle is updating.');
	      this.cdr.markForCheck();
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

  private resetTtsPipeline(): void {
    this.ttsPlayback.reset(true);
    this.ttsSpeaking.set(false);
    this.ttsPaused.set(false);
  }

  pauseResumeTts(): void {
    if (!this.ttsSpeaking()) return;
    this.ttsPlayback.togglePause();
  }

  private beginTtsStream(): void {
    this.ttsPlayback.begin({
      surface: 'chat',
      provider: this.voiceOutputProvider(),
      config: this.workspaceVoiceOutputConfig(),
      onState: (state) => this.syncTtsState(state),
      onStarted: (metric) => {
        this.voiceConnection?.ttsStarted({
          surface: 'chat',
          latency_profile: metric.latency_profile,
          time_to_first_audio_ms: metric.time_to_first_audio_ms,
        });
        this.voiceNotice.set('Speaking.');
      },
      onEnded: (metric) => {
        this.voiceConnection?.ttsEnded({
          surface: 'chat',
          duration_ms: metric.duration_ms,
          time_to_first_audio_ms: metric.time_to_first_audio_ms,
        });
        this.scheduleVoiceLoopRearm();
      },
      onInterrupted: (reason) => {
        this.voiceConnection?.ttsInterrupted({ surface: 'chat', reason });
      },
      onNotice: (message) => {
        if (message) this.voiceNotice.set(message);
      },
    });
  }

  private syncTtsState(state: VoiceTtsState): void {
    this.ttsSpeaking.set(['preparing', 'queued', 'speaking', 'paused'].includes(state));
    this.ttsPaused.set(state === 'paused');
  }

  private maybeFlushSentences(buffer: string): void {
    if (this.ttsPlayback.state() === 'idle') this.beginTtsStream();
    this.ttsPlayback.appendBuffer(buffer);
  }

  private flushTrailingTts(buffer: string): void {
    if (this.ttsPlayback.state() === 'idle') this.beginTtsStream();
    this.ttsPlayback.finish(buffer);
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
