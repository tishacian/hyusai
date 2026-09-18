import { output } from '@angular/core';
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
import { NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subscription } from 'rxjs';
import { Router } from '@angular/router';
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
import {
  ResolvedVoiceCaptureConfig,
  VoiceCaptureMode,
  normalizeVoiceCaptureMode,
  resolveVoiceCaptureConfig,
  voiceCaptureStorageKey,
} from '@app/core/voice-capture-config';
import { detectVoiceCommand as detectSharedVoiceCommand } from '@app/core/voice-command-detector';
import { IconComponent } from '@app/shared/ui/icon.component';
import { RuntimeHealthService } from '@app/core/runtime-health.service';
import {
  WorkspaceService,
  type WorkspaceContextTransition,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { persistWorkspaceEvalContext } from '@app/core/evaluation-context.storage';
import { PermissionsService } from '@app/core/permissions.service';
import { AssistantEffectsService } from '@app/core/assistant-effects.service';
import { I18nService, type Locale } from '@app/core/i18n.service';
import {
  NavLinkDirective,
  RuntimeStatusBadgeComponent,
  ThinkingOrbComponent,
  type CkOrbState,
} from '@app/shared/cockpit';
import { ZoomContextService } from '@app/core/zoom-context.service';
import {
  SharedVoiceOracleStep,
  SharedVoiceRuntimeOption,
  VoiceControlsComponent,
} from '@app/shared/voice/voice-controls.component';
import { DocumentPreviewComponent } from '@app/shared/document-preview/document-preview.component';
import { SystemMandateComponent } from '../mandate/system-mandate.component';
import { RunMandateComponent } from '../mandate/run-mandate.component';

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
  | { kind: 'strong'; value: string }
  | { kind: 'em'; value: string }
  | { kind: 'code'; value: string }
  | { kind: 'link'; value: string; href: string }
  | { kind: 'cite'; n: number; label?: string };

/**
 * A single list item: its inline tokens plus optional nested children. The
 * tree shape lets the renderer preserve the indentation hierarchy the model
 * emits (sub-bullets stay nested) instead of flattening every item to one
 * level.
 */
interface AnswerListItem {
  tokens: AnswerToken[];
  ordered: boolean;
  children: AnswerListItem[];
}

type AnswerBlock =
  | { kind: 'paragraph'; tokens: AnswerToken[] }
  | { kind: 'heading'; level: 2 | 3 | 4; tokens: AnswerToken[] }
  | { kind: 'list'; ordered: boolean; items: AnswerListItem[] }
  | { kind: 'codeblock'; value: string };

interface RetrievalDecisionTrace {
  summary?: string;
  query_type?: string;
  latency_profile?: string | null;
  retrieval_profile?: string | null;
  selected_route?: string;
  route_reason?: string;
  tradeoff?: string;
  collection_scope?: Record<string, unknown>;
  layers?: Array<Record<string, unknown>>;
  quality_controls?: Record<string, unknown>;
  fallbacks?: Array<Record<string, unknown>>;
  deep_search?: Record<string, unknown>;
  timings?: Record<string, unknown>;
  candidate_counts?: Record<string, unknown>;
  selected_sources?: Array<Record<string, unknown>>;
  trace_source?: string;
}

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  /**
   * Distinguishes special assistant bubbles from regular answers. A
   * ``correction_ack`` message is the sober conversational acknowledgement
   * appended after an expert correction — it renders muted with a check icon
   * and carries no action row, sources panel, or fact-check affordances.
   */
  kind?: 'correction_ack';
  decisionSteps?: DecisionStep[];
  sources?: Source[];
  mapCommand?: Record<string, unknown>;
  feedback?: 'up' | 'down' | null;
  durationMs?: number;
  ragMode?: string | null;
  promptType?: string | null;
  retrievalInfo?: {
    densePolicy?: string | null;
    fallbackReason?: string | null;
    sparseStatus?: string | null;
    retrievalScope?: Record<string, unknown> | null;
    retrievalPlan?: Record<string, unknown> | null;
    scopeReason?: string | null;
    scopeConfidence?: number | null;
    latencyProfile?: string | null;
    latencyBudget?: {
      profile?: string | null;
      deadlineSeconds?: number | null;
      candidatePoolK?: number | null;
      topK?: number | null;
    } | null;
    stageTimings?: Record<string, number | null> | null;
    candidateCounts?: Record<string, number | null> | null;
    decisionTrace?: RetrievalDecisionTrace | null;
    deepJobId?: string | null;
    deepStatus?: string | null;
    deepProgress?: number | null;
    deepStage?: string | null;
    deepPollUrl?: string | null;
    deepParentMessageId?: string | null;
    deepAnswer?: string | null;
    deepAnswerStatus?: string | null;
    deepAnswerModel?: string | null;
    deepSummary?: {
      chunksRetrieved?: number | null;
      sourcesReturned?: number | null;
      topSources?: Array<{ label?: string | null; chunks?: number | null }>;
      pipeline?: string | null;
      topScore?: number | null;
      partial?: boolean | null;
      fallbackReason?: string | null;
    } | null;
    deepDetailsOpen?: boolean;
    deepDetailsLoading?: boolean;
    deepDetailsError?: string | null;
    deepSources?: Source[];
  } | null;
  // Canonical Run id for this turn — lets the auto-QA polling loop attach its
  // verdict to the right bubble once the judge finishes.
  runId?: string | null;
  evaluationStatus?: string;
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
    composite_score: number | null;
    scores: Record<string, number>;
    hallucination_rate: number | null;
    claim_audit?: { claims?: Array<{ text: string; verdict: string; score: number }> };
  } | null;
}

interface ChatSessionSummary {
  id: string;
  title?: string | null;
  status?: 'active' | 'archived' | 'deleted' | string;
  created_at?: string | null;
  last_activity?: string | null;
  message_count?: number;
  meta_data?: Record<string, unknown>;
}

interface ChatSessionDetail extends ChatSessionSummary {
  messages?: Array<{
    id: string;
    role: 'user' | 'assistant';
    content: string;
    timestamp?: string | null;
    meta_data?: Record<string, unknown>;
  }>;
  jobs?: unknown[];
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
  capture_mode?: VoiceCaptureMode | string | null;
  auto_capture_mode_enabled?: boolean;
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
  endpoint_grace_ms?: number;
  vad_hangover_ms?: number;
  vad_calibration_ms?: number;
  vad_min_silence_frames_ms?: number;
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

const RAG_MODE_CHOICES: { slug: RagModeChoice; labelKey: string; hintKey: string }[] = [
  { slug: 'auto', labelKey: 'chat.controls.auto', hintKey: 'chat.rag.auto_hint' },
  { slug: 'naive', labelKey: 'chat.rag.naive', hintKey: 'chat.rag.naive_hint' },
  { slug: 'hybrid', labelKey: 'chat.rag.hybrid', hintKey: 'chat.rag.hybrid_hint' },
  { slug: 'hah', labelKey: 'chat.rag.hah', hintKey: 'chat.rag.hah_hint' },
  { slug: 'chah', labelKey: 'chat.rag.chah', hintKey: 'chat.rag.chah_hint' },
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
 *
 * The operator-facing tooltip lives in the i18n dictionary under
 * ``chat.metrics.desc.<key>`` (see ``metricDescription()``), so the guard
 * can keep FR/EN copy in parity.
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
}

const METRIC_REGISTRY: Record<string, MetricSpec> = {
  relevance: {
    polarity: 'higher',
    max: 1,
    good: 0.7,
    fair: 0.4,
  },
  factuality: {
    polarity: 'higher',
    max: 1,
    good: 0.7,
    fair: 0.4,
  },
  coherence: {
    polarity: 'higher',
    max: 1,
    good: 0.7,
    fair: 0.4,
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
  },
  hallucination_rate: {
    polarity: 'lower',
    max: 1,
    good: 0.7,
    fair: 0.4,
  },
};

const DEFAULT_METRIC_SPEC: MetricSpec = {
  polarity: 'higher',
  max: 1,
  good: 0.7,
  fair: 0.4,
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
    NgTemplateOutlet,
    NavLinkDirective,
    IconComponent,
    RuntimeStatusBadgeComponent,
    ThinkingOrbComponent,
    VoiceControlsComponent,
    DocumentPreviewComponent,
    SystemMandateComponent,
    RunMandateComponent,
  ],
  template: `
    <div
      class="chat-history-shell"
      [class.chat-history-embed]="compact()"
      [class.chat-history-collapsed]="!compact() && !chatHistoryOpen()"
    >
      @if (!compact() && !chatHistoryOpen()) {
        <button
          type="button"
          class="chat-history-expand"
          [title]="i18n.t('chat.history.show')"
          [attr.aria-label]="i18n.t('chat.history.show')"
          [attr.aria-expanded]="false"
          (click)="toggleChatHistory()"
        >
          <app-icon name="message-square" [size]="15" />
          <span>{{ chatSessions().length }}</span>
        </button>
      }
      <aside class="chat-history-panel" [hidden]="compact() || !chatHistoryOpen()">
        <div class="chat-history-head">
          <div>
            <div class="chat-history-kicker">{{ i18n.t('chat.history.title') }}</div>
            <div class="chat-history-count">
              {{ i18n.t('chat.history.count', { count: chatSessions().length }) }}
            </div>
          </div>
          <div class="chat-history-tools">
            <button
              type="button"
              class="chat-history-toggle"
              [title]="i18n.t('chat.history.hide')"
              [attr.aria-label]="i18n.t('chat.history.hide')"
              [attr.aria-expanded]="true"
              (click)="toggleChatHistory()"
            >
              <app-icon name="chevron-left" [size]="14" />
            </button>
            <button
              type="button"
              class="chat-history-new"
              [title]="i18n.t('chat.history.new')"
              [disabled]="creatingChatSession"
              (click)="createNewChat()"
            >
              <app-icon name="plus" [size]="14" />
            </button>
          </div>
        </div>
        <div class="chat-history-search">
          <app-icon name="search" [size]="12" />
          <input
            type="search"
            [ngModel]="chatSessionSearch()"
            (ngModelChange)="chatSessionSearch.set($event)"
            [placeholder]="i18n.t('chat.history.search')"
          />
        </div>
        <div class="chat-history-list">
          @if (chatSessionsLoading()) {
            <div class="chat-history-empty">
              <app-icon name="loader-2" [size]="13" class="animate-spin" />
              {{ i18n.t('chat.history.loading') }}
            </div>
          } @else if (filteredChatSessions().length === 0) {
            <div class="chat-history-empty">{{ i18n.t('chat.history.empty') }}</div>
          } @else {
            @for (session of filteredChatSessions(); track session.id) {
              <div
                class="chat-history-item"
                [class.chat-history-item-active]="isActiveSession(session)"
                (click)="openChatSession(session.id)"
              >
                <span class="chat-history-title">{{ sessionTitle(session) }}</span>
                <span class="chat-history-subtitle">{{ sessionSubtitle(session) }}</span>
                <span class="chat-history-actions">
                  <button
                    type="button"
                    [title]="i18n.t('chat.history.archive')"
                    (click)="archiveChatSession(session, $event)"
                  >
                    <app-icon name="archive" [size]="11" />
                  </button>
                  <button
                    type="button"
                    [title]="i18n.t('common.delete')"
                    (click)="deleteChatSession(session, $event)"
                  >
                    <app-icon name="trash-2" [size]="11" />
                  </button>
                </span>
              </div>
            }
          }
        </div>
      </aside>
      <div class="flex flex-col h-full min-w-0 flex-1">
      @if (executiveMode()) {
        <div class="vigie-context-bar">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <div class="vigie-kicker">
                {{ i18n.t('chat.exec.kicker') }}
              </div>
              <div class="vigie-scope-line">
                {{ i18n.t('chat.exec.scope') }}
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
                  [title]="i18n.t('chat.voice.stop.hint')"
                  (click)="stopVoiceExperience()"
                >
                  <app-icon name="square" [size]="13" />
                  {{ i18n.t('chat.voice.stop') }}
                </button>
              }
              <button
                type="button"
                class="vigie-trace-button"
                (click)="traceOpen.set(!traceOpen())"
                [title]="traceOpen() ? i18n.t('chat.trace.hide') : i18n.t('chat.trace.show')"
              >
                <app-icon name="sliders-horizontal" [size]="13" />
                {{ i18n.t('chat.trace.toggle') }}
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
            [title]="i18n.t('chat.controls.runtime_hint')"
          >
            <app-icon name="circle-dot" [size]="12" class="text-emerald-400" />
            <span>{{ i18n.t('chat.title') }}</span>
            <span class="chat-mode-model">{{ chatRuntimeLabel() }}</span>
          </div>

          @if (knowledgeScopeOptions().length > 0 && (!contextId() || sessionDocsMode() === 'combine')) {
            <div class="source-picker" [title]="assistantScopeLabel()">
              <span class="source-picker-label">
                <app-icon name="database" [size]="12" />
                {{ i18n.t('chat.controls.sources') }}
                <span
                  class="control-info-dot"
                  [title]="i18n.t('chat.controls.sources_info')"
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
                  <option value="auto">{{ i18n.t('chat.controls.source_auto', { label: autoSourceLabel() }) }}</option>
                  <option value="workspace_default">{{ i18n.t('chat.controls.source_default') }}</option>
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
            <div class="session-doc-mode" [title]="contextCollection() ? i18n.t('chat.controls.collection_hint') : i18n.t('chat.controls.session_docs_hint')">
              <span class="session-doc-label">
                <app-icon name="files" [size]="12" />
                {{ contextCollection() || i18n.t('chat.controls.session_docs') }}
                <span
                  class="control-info-dot"
                  [title]="contextCollection() ? i18n.t('chat.controls.collection_hint') : i18n.t('chat.controls.session_docs_info')"
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
                {{ i18n.t('chat.controls.session_docs_only') }}
              </button>
              <button
                type="button"
                class="session-doc-mode-button"
                [class.session-doc-mode-active]="sessionDocsMode() === 'combine'"
                (click)="setSessionDocsMode('combine')"
              >
                {{ i18n.t('chat.controls.session_docs_combine') }}
              </button>
            </div>
            <span class="text-gray-600">·</span>
          }

          <div class="mini-control" [title]="ragModeHint()">
            <span class="mini-control-label">
              {{ i18n.t('chat.controls.retrieval') }}
              <span
                class="control-info-dot"
                [title]="i18n.t('chat.controls.retrieval_info')"
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
                  <option [value]="m.slug">{{ i18n.t(m.labelKey) }}</option>
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
              {{ i18n.t('chat.controls.reasoning') }}
              <span
                class="control-info-dot"
                [title]="i18n.t('chat.controls.reasoning_info')"
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
                <option value="auto">{{ i18n.t('chat.controls.auto') }}</option>
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
              class="p-1.5 rounded hover:bg-white/5 text-cyan-300 hover:text-cyan-200 transition"
              [title]="ttsPaused() ? i18n.t('chat.voice.resume_playback') : i18n.t('chat.voice.pause_playback')"
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
            [class.text-cyan-400]="ttsEnabled()"
            [title]="ttsEnabled() ? i18n.t('chat.voice.output_on') : i18n.t('chat.voice.output_off')"
            (click)="toggleTTS()"
          >
            <app-icon [name]="ttsEnabled() ? 'volume-2' : 'volume-x'" [size]="14" />
          </button>
          <button
            type="button"
            class="p-1.5 rounded hover:bg-white/5 text-gray-400 hover:text-white transition"
            [title]="i18n.t('chat.controls.clear')"
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
        [captureMode]="voiceCaptureMode()"
        [captureModeHint]="voiceCaptureModeHint()"
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
        (captureModeChange)="setVoiceCaptureMode($event)"
      />

      @if (isDemoMode() && !demoVoiceChipsDismissed() && demoVoiceChips().length) {
        <div class="demo-voice-chips">
          <div class="demo-voice-chips-head">
            <span>{{ i18n.t('chat.demo.voice_chips') }}</span>
            <button type="button" class="demo-voice-dismiss" (click)="demoVoiceChipsDismissed.set(true)">{{ i18n.t('chat.demo.voice_chips_hide') }}</button>
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
            {{ i18n.t('chat.actions.title') }}
            <span class="control-info-dot" [title]="i18n.t('chat.actions.info')">
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
                <span>{{ i18n.t('chat.actions.confirm_badge') }}</span>
              }
            </button>
          }
        </div>
      }

      <!-- Messages -->
      <div
        #messagesScroller
        class="flex-1 min-h-0 overflow-y-auto px-4 py-4 space-y-5"
        [class.vigie-messages]="executiveMode()"
      >
        @if (systemId(); as mandateSystemId) {
          <app-system-mandate [systemId]="mandateSystemId" [compact]="true" />
        }
        @if (messages().length === 0 && !streaming()) {
          <div class="h-full flex flex-col items-center justify-center py-8" [class.vigie-empty-state]="executiveMode()">
            <div class="ck-chat-empty-mark w-12 h-12 rounded-full flex items-center justify-center mb-3">
              <ck-thinking-orb state="listening" [size]="20" />
            </div>
            <div class="ck-chat-empty-title text-sm font-semibold text-gray-900 dark:text-white">
              {{ emptyTitle() }}
            </div>
            <p class="ck-chat-empty-hint text-xs text-gray-500 dark:text-gray-400 mt-1 max-w-xs text-center">
              {{ emptySubtitle() }}
            </p>
            @if (!isDemoMode() && activeSuggestions().length) {
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-5 w-full max-w-2xl">
                @for (s of activeSuggestions(); track s.prompt) {
                  <button
                    type="button"
                    class="text-left px-3 py-2.5 rounded-md ring-1 ring-white/5 bg-white/[0.02] hover:bg-white/[0.06] hover:ring-cyan-500/30 transition group"
                    (click)="useSuggestion(s)"
                  >
                    <div class="flex items-center gap-2 mb-1">
                      <div
                        class="w-6 h-6 rounded-md flex items-center justify-center bg-cyan-500/10 text-cyan-400 group-hover:bg-cyan-500/20 transition shrink-0"
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
                class="ck-chat-user-bubble max-w-[80%] bg-cyan-500 text-white rounded-2xl rounded-br-sm px-4 py-2.5 text-sm whitespace-pre-wrap shadow-sm"
                [class.vigie-user-bubble]="executiveMode()"
              >
                {{ msg.content }}
              </div>
            </div>
          } @else if (msg.kind === 'correction_ack') {
            <!-- Sober conversational acknowledgement of an expert correction.
                 Intentionally carries no action row, sources, or fact-check —
                 it is a simple acquittal in the thread, not an answer. -->
            <div class="flex justify-start">
              <div class="inline-flex items-start gap-2 max-w-[80%] rounded-2xl rounded-bl-sm bg-emerald-500/[0.06] px-3.5 py-2 text-[13px] leading-relaxed text-gray-600 dark:text-gray-300 ring-1 ring-emerald-500/20">
                <app-icon name="check" [size]="14" class="mt-0.5 shrink-0 text-emerald-600 dark:text-emerald-300" />
                <span class="whitespace-pre-wrap">{{ msg.content }}</span>
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
                    <app-icon name="workflow" [size]="12" class="text-cyan-400" />
                    {{
                      msg.decisionSteps.length > 1
                        ? i18n.t('chat.trail.toggle', { count: msg.decisionSteps.length })
                        : i18n.t('chat.trail.toggle_one', { count: msg.decisionSteps.length })
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
                          [class.border-cyan-500\\/30]="step.status === 'active'"
                          [class.bg-cyan-500\\/5]="step.status === 'active'"
                          [class.border-white\\/5]="!step.status || step.status === 'pending'"
                          [class.bg-white\\/[0\\.02]]="!step.status || step.status === 'pending'"
                        >
                          <app-icon
                            [name]="iconFor(step)"
                            [size]="13"
                            class="mt-0.5 shrink-0"
                            [class.text-emerald-400]="step.status === 'completed'"
                            [class.text-red-400]="step.status === 'error'"
                            [class.text-cyan-400]="step.status === 'active'"
                            [class.text-gray-500]="!step.status || step.status === 'pending'"
                          />
                          <div class="flex-1 min-w-0">
                            <div class="flex items-center gap-2">
                              <span class="font-medium text-white truncate">{{
                                step.title || step.type || i18n.t('chat.trail.step')
                              }}</span>
                              @if (step.status === 'active') {
                                <span
                                  class="text-[9px] uppercase tracking-wider text-cyan-400 font-semibold"
                                  >{{ i18n.t('chat.trail.running') }}</span
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
                                [title]="isEvalOpen(msg.id, step.id) ? i18n.t('chat.metrics.collapse') : i18n.t('chat.metrics.expand')"
                              >
                                <app-icon
                                  [name]="isEvalOpen(msg.id, step.id) ? 'chevron-down' : 'chevron-right'"
                                  [size]="10"
                                  class="text-gray-500 group-hover:text-gray-300"
                                />
                                <span class="font-mono">
                                  {{ scoreSummary(step) || i18n.t('chat.metrics.label') }}
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
                                      [title]="metricDescription(m.key)"
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
                                            [title]="i18n.t('chat.metrics.lower_better')"
                                          >↓</span>
                                        } @else if (spec.max < 1) {
                                          <span
                                            class="text-[9px] font-mono text-gray-500 shrink-0"
                                            [title]="i18n.t('chat.metrics.max', { value: spec.max.toFixed(2) })"
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

              <ng-template
                #answerInline
                let-tokens="tokens"
                let-sources="sources"
                let-sourceHostId="sourceHostId"
                let-openDirectSources="openDirectSources"
              >
                @for (tok of tokens; track $index) {
                  @if (tok.kind === 'text') {
                    <span>{{ tok.value }}</span>
                  } @else if (tok.kind === 'strong') {
                    <strong class="font-semibold text-gray-950 dark:text-white">{{ tok.value }}</strong>
                  } @else if (tok.kind === 'em') {
                    <em class="italic">{{ tok.value }}</em>
                  } @else if (tok.kind === 'code') {
                    <code class="rounded bg-black/5 dark:bg-white/10 px-1 py-0.5 font-mono text-[0.92em]">{{ tok.value }}</code>
                  } @else if (tok.kind === 'link') {
                    <a class="text-cyan-500 dark:text-cyan-300 underline underline-offset-2" [href]="safeMarkdownHref(tok.href)" target="_blank" rel="noreferrer">{{ tok.value }}</a>
                  } @else if (isValidCitationForSources(sources, tok.n)) {
                    <button
                      type="button"
                      class="inline-flex items-center justify-center min-w-[1.25rem] h-[1.125rem] px-1 mx-0.5 align-baseline rounded-md text-[10px] font-mono font-semibold bg-cyan-500/15 text-cyan-500 dark:text-cyan-300 hover:bg-cyan-500/30 hover:text-cyan-200 transition ring-1 ring-cyan-500/30 cursor-pointer"
                      [title]="citationTooltipForSources(sources, tok.n)"
                      (click)="gotoSourceTarget(msg, tok.n, sourceHostId || msg.id, openDirectSources !== false)"
                    >
                      {{ tok.label || tok.n }}
                    </button>
                  } @else {
                    <span
                      class="inline-flex items-center justify-center min-w-[1.25rem] h-[1.125rem] px-1 mx-0.5 align-baseline rounded-md text-[10px] font-mono bg-gray-400/15 text-gray-500 ring-1 ring-gray-400/20"
                      [title]="i18n.t('chat.citation.unavailable', { n: tok.n })"
                    >
                      {{ tok.label || tok.n }}
                    </span>
                  }
                }
              </ng-template>

              <!-- Recursive list renderer: preserves nested-bullet indentation
                   the model emits. Each level picks <ol>/<ul> from its first
                   item and recurses into children. Shared by the main answer
                   and the Deep Search answer. -->
              <ng-template
                #answerList
                let-items
                let-sources="sources"
                let-sourceHostId="sourceHostId"
                let-openDirectSources="openDirectSources"
              >
                @if (items[0]?.ordered) {
                  <ol class="my-1.5 list-decimal pl-5 space-y-0.5">
                    @for (item of items; track $index) {
                      <li>
                        <ng-container [ngTemplateOutlet]="answerInline" [ngTemplateOutletContext]="{ tokens: item.tokens, sources: sources, sourceHostId: sourceHostId, openDirectSources: openDirectSources }"></ng-container>
                        @if (item.children?.length) {
                          <ng-container [ngTemplateOutlet]="answerList" [ngTemplateOutletContext]="{ $implicit: item.children, sources: sources, sourceHostId: sourceHostId, openDirectSources: openDirectSources }"></ng-container>
                        }
                      </li>
                    }
                  </ol>
                } @else {
                  <ul class="my-1.5 list-disc pl-5 space-y-0.5">
                    @for (item of items; track $index) {
                      <li>
                        <ng-container [ngTemplateOutlet]="answerInline" [ngTemplateOutletContext]="{ tokens: item.tokens, sources: sources, sourceHostId: sourceHostId, openDirectSources: openDirectSources }"></ng-container>
                        @if (item.children?.length) {
                          <ng-container [ngTemplateOutlet]="answerList" [ngTemplateOutletContext]="{ $implicit: item.children, sources: sources, sourceHostId: sourceHostId, openDirectSources: openDirectSources }"></ng-container>
                        }
                      </li>
                    }
                  </ul>
                }
              </ng-template>

              <!-- Content -->
              <div class="flex justify-start">
                <div
                  class="ck-chat-assistant-bubble max-w-[85%] bg-gray-100 dark:bg-white/[0.04] text-gray-900 dark:text-gray-100 rounded-2xl rounded-bl-sm px-4 py-2.5 text-sm whitespace-pre-wrap leading-relaxed ring-1 ring-black/5 dark:ring-white/5"
                  [class.vigie-assistant-bubble]="executiveMode()"
                >
                  @for (block of renderMarkdownAnswer(msg.content, msg.sources); track $index) {
                    @if (block.kind === 'heading') {
                      <h3 class="mt-2 first:mt-0 mb-1 text-[0.95rem] font-semibold text-gray-950 dark:text-white">
                        <ng-container [ngTemplateOutlet]="answerInline" [ngTemplateOutletContext]="{ tokens: block.tokens, sources: msg.sources, sourceHostId: msg.id, openDirectSources: true }"></ng-container>
                      </h3>
                    } @else if (block.kind === 'list') {
                      <ng-container [ngTemplateOutlet]="answerList" [ngTemplateOutletContext]="{ $implicit: block.items, sources: msg.sources, sourceHostId: msg.id, openDirectSources: true }"></ng-container>
                    } @else if (block.kind === 'codeblock') {
                      <pre class="my-2 max-w-full overflow-auto rounded-md bg-black/5 dark:bg-white/[0.06] p-2 text-xs leading-relaxed"><code>{{ block.value }}</code></pre>
                    } @else {
                      <p class="my-1 first:mt-0 last:mb-0">
                        <ng-container [ngTemplateOutlet]="answerInline" [ngTemplateOutletContext]="{ tokens: block.tokens, sources: msg.sources, sourceHostId: msg.id, openDirectSources: true }"></ng-container>
                      </p>
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
                    {{ i18n.t('chat.map.ready') }} · {{ mapCommandLabel(msg.mapCommand) }}
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
                      {{ i18n.t('chat.citations.missing_intro') }}
                      @for (n of missing; track n; let last = $last) {
                        <span class="font-mono text-amber-200">[{{ n }}]</span>{{ last ? '' : ', ' }}
                      }
                      @if (!msg.sources || msg.sources.length === 0) {
                        {{ i18n.t('chat.citations.missing_none') }}
                      } @else if (msg.sources.length > 1) {
                        {{ i18n.t('chat.citations.missing_partial', { count: msg.sources.length }) }}
                      } @else {
                        {{ i18n.t('chat.citations.missing_partial_one', { count: msg.sources.length }) }}
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
                    <app-icon name="book-open" [size]="12" class="text-cyan-400" />
                    {{ i18n.t('chat.sources.toggle', { count: msg.sources.length }) }}
                  </button>
                  @if (isSourcesOpen(msg.id)) {
                    <ol class="space-y-1.5 pl-1">
                      @for (src of msg.sources; track $index; let i = $index) {
                        <li
                          [id]="sourceDomId(msg.id, i + 1)"
                          [class]="isSourceCited(msg, i + 1)
                            ? 'rounded-md px-3 py-2 text-[12px] transition-all bg-cyan-500/10 ring-1 ring-cyan-500/25'
                            : 'rounded-md px-3 py-2 text-[12px] transition-all bg-white/[0.02] dark:bg-white/[0.03] ring-1 ring-black/5 dark:ring-white/5 opacity-70'"
                          [attr.aria-label]="isSourceCited(msg, i + 1) ? i18n.t('chat.sources.cited_aria') : i18n.t('chat.sources.uncited_aria')"
                        >
                          <div class="flex items-center gap-2 mb-0.5">
                            <span
                              [class]="isSourceCited(msg, i + 1)
                                ? 'w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-mono shrink-0 bg-cyan-500/25 text-cyan-400'
                                : 'w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-mono shrink-0 bg-white/5 text-gray-400'"
                            >
                              {{ i + 1 }}
                            </span>
                            @if (!isSourceCited(msg, i + 1)) {
                              <span
                                class="text-[9px] uppercase tracking-wider text-gray-500 font-mono shrink-0"
                                [title]="i18n.t('chat.sources.uncited_hint')"
                              >
                                {{ i18n.t('chat.sources.uncited') }}
                              </span>
                            }
                            <span class="font-medium text-gray-900 dark:text-white truncate">
                              {{ sourceTitle(src) }}
                            </span>
                            @if (sourceLocator(src); as loc) {
                              <span
                                class="font-mono text-[10px] text-cyan-400/80 shrink min-w-0 max-w-[14rem] truncate"
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
                                class="shrink-0 inline-flex items-center justify-center rounded p-1 text-gray-500 hover:text-cyan-300 hover:bg-white/5 transition"
                                [class.ml-auto]="src.score == null"
                                [title]="i18n.t('chat.sources.preview')"
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
                  class="ck-chat-trace-summary ml-0 mt-1 rounded-md px-3 py-2 flex items-center gap-3 text-[11px] text-gray-700 dark:text-gray-300"
                  [class.hidden]="isDemoMode() || (executiveMode() && !traceOpen())"
                >
                  <app-icon name="circle-dot" [size]="11" class="text-cyan-400 shrink-0" />
                  <span class="font-medium">
                    {{
                      msg.decisionSteps.length > 1
                        ? i18n.t('chat.summary.steps', { count: msg.decisionSteps.length })
                        : i18n.t('chat.summary.steps_one', { count: msg.decisionSteps.length })
                    }}
                  </span>
                  @if (msg.durationMs) {
                    <span class="font-mono text-gray-500">· {{ msg.durationMs }}ms</span>
                  }
                  @if (msg.sources?.length) {
                    <span class="font-mono text-gray-500">· {{ i18n.t('chat.summary.sources', { count: msg.sources!.length }) }}</span>
                  }
                  @if (msg.ragMode) {
                    <span
                      class="font-mono text-[10px] px-1.5 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20"
                      [title]="i18n.t('chat.summary.rag_override_hint')"
                    >
                      {{ msg.ragMode!.toUpperCase() }}
                    </span>
                  }
                  @if (msg.retrievalInfo; as retrieval) {
                    @if (retrievalBadgeVisible(retrieval)) {
                      <span
                        class="inline-flex items-center gap-1 font-mono text-[10px] px-1.5 py-0.5 rounded-full bg-cyan-500/10 text-cyan-300 border border-cyan-500/20"
                        [title]="retrievalPolicyTitle(retrieval)"
                      >
                        <app-icon name="radar" [size]="10" />
                        {{ retrievalPolicyLabel(retrieval) }}
                      </span>
                    }
                    @if (retrieval.decisionTrace; as trace) {
                      <span
                        class="inline-flex items-center gap-1 font-mono text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-300 border border-emerald-500/20"
                        [title]="decisionTraceTitle(trace)"
                      >
                        <app-icon name="git-branch" [size]="10" />
                        {{ i18n.t('chat.summary.route', { label: decisionRouteLabel(trace) }) }}
                      </span>
                    }
                    @if (sparseDegraded(retrieval)) {
                      <span
                        class="inline-flex items-center gap-1 font-mono text-[10px] px-1.5 py-0.5 rounded-full bg-amber-500/10 text-amber-300 border border-amber-500/20"
                        [title]="i18n.t('chat.summary.sparse_degraded_hint', { status: retrieval.sparseStatus || '' })"
                      >
                        <app-icon name="alert-triangle" [size]="10" />
                        {{ i18n.t('chat.summary.dense_only') }}
                      </span>
                    }
                    @if (retrieval.deepJobId) {
                      <span
                        class="inline-flex items-center gap-1 font-mono text-[10px] px-1.5 py-0.5 rounded-full bg-sky-500/10 text-sky-300 border border-sky-500/20"
                        [title]="deepRetrievalTitle(retrieval)"
                      >
                        @if (retrieval.deepStatus === 'completed' && deepRetrievalPartial(retrieval)) {
                          <app-icon name="alert-triangle" [size]="10" />
                        } @else if (retrieval.deepStatus === 'completed') {
                          <app-icon name="check" [size]="10" />
                        } @else if (retrieval.deepStatus === 'failed' || retrieval.deepStatus === 'cancelled') {
                          <app-icon name="x-circle" [size]="10" />
                        } @else {
                          <app-icon name="loader" [size]="10" class="animate-spin" />
                        }
                        {{ deepRetrievalLabel(retrieval) }}
                      </span>
                    }
                  }
                  @if (msg.promptType) {
                    <span
                      class="font-mono text-[10px] px-1.5 py-0.5 rounded-full bg-sky-500/10 text-sky-300 border border-sky-500/20"
                      [title]="i18n.t('chat.summary.reasoning_template_hint')"
                    >
                      {{ msg.promptType }}
                    </span>
                  }
                  @if (msg.evaluationStatus) {
                    <span>{{i18n.t('runs.investigation.status.' + msg.evaluationStatus)}}</span>
                  }
                  @if (msg.evaluation) {
                    <span class="font-mono text-emerald-500 dark:text-emerald-400">
                      · {{ (msg.evaluation.composite_score?.toFixed(1) ?? '—') }}/100
                    </span>
                  }
                  <a
                    [navLink]="msg.runId ? { type: 'run', ref: msg.runId } : { surface: 'runs' }"
                    class="ml-auto text-cyan-500 hover:text-cyan-400 inline-flex items-center gap-1"
                  >
                    <app-icon name="git-commit" [size]="11" />
                    {{ i18n.t('chat.summary.runs_link') }}
                  </a>
                  <a
                    [navLink]="msg.runId ? { type: 'run', ref: msg.runId } : { surface: 'observability' }"
                    class="text-cyan-500 hover:text-cyan-400 inline-flex items-center gap-1"
                  >
                    <app-icon name="activity" [size]="11" />
                    {{ i18n.t('chat.summary.quality_link') }}
                  </a>
                </div>
              }

              @if (msg.runId; as mandateRunId) {
                <app-run-mandate [runId]="mandateRunId" [compact]="true" />
              }

              @if (msg.retrievalInfo?.decisionTrace; as trace) {
                <details
                  class="ml-0 mt-1 rounded-md bg-emerald-500/5 ring-1 ring-emerald-500/15 text-[11px] text-gray-700 dark:text-gray-300"
                >
                  <summary class="cursor-pointer select-none px-3 py-2 font-mono text-[10px] uppercase tracking-[0.12em] text-emerald-300">
                    {{ i18n.t('chat.decision.title') }} · {{ decisionRouteLabel(trace) }}
                  </summary>
                  <div class="grid gap-2 px-3 pb-3 md:grid-cols-2">
                    <div>
                      <div class="text-[10px] uppercase tracking-wider text-gray-500">{{ i18n.t('chat.decision.reason') }}</div>
                      <div class="mt-0.5 text-gray-300">{{ trace.route_reason || trace.summary || i18n.t('chat.decision.reason_fallback') }}</div>
                    </div>
                    <div>
                      <div class="text-[10px] uppercase tracking-wider text-gray-500">{{ i18n.t('chat.decision.tradeoff') }}</div>
                      <div class="mt-0.5 text-gray-300">{{ trace.tradeoff || i18n.t('chat.decision.tradeoff_fallback') }}</div>
                    </div>
                    <div class="font-mono text-[10px] text-gray-400">
                      {{ decisionTraceQualityLine(trace) }}
                    </div>
                    <div class="font-mono text-[10px] text-gray-400 truncate">
                      {{ decisionTraceSourcesLine(trace) }}
                    </div>
                  </div>
                </details>
              }

              @if (msg.retrievalInfo?.deepJobId && msg.retrievalInfo; as deepInfo) {
                <div
                  class="ml-0 mt-1 rounded-md px-3 py-2 bg-sky-500/5 ring-1 ring-sky-500/15 flex flex-wrap items-center gap-2 text-[11px] text-gray-700 dark:text-gray-300"
                  [title]="deepRetrievalTitle(deepInfo)"
                >
                  @if (deepInfo.deepStatus === 'completed' && deepRetrievalPartial(deepInfo)) {
                    <app-icon name="alert-triangle" [size]="11" class="text-sky-300 shrink-0" />
                  } @else if (deepInfo.deepStatus === 'completed') {
                    <app-icon name="check" [size]="11" class="text-sky-300 shrink-0" />
                  } @else if (deepInfo.deepStatus === 'failed' || deepInfo.deepStatus === 'cancelled') {
                    <app-icon name="x-circle" [size]="11" class="text-red-300 shrink-0" />
                  } @else {
                    <ck-thinking-orb state="searching" [size]="20" [label]="deepRetrievalLabel(deepInfo)" />
                  }
                  <span class="font-medium text-sky-300">{{ deepRetrievalLabel(deepInfo) }}</span>
                  @if (deepInfo.deepStage) {
                    <span class="font-mono text-gray-500">· {{ deepInfo.deepStage }}</span>
                  }
                  @if (deepInfo.deepSummary; as deep) {
                    @if (deep.chunksRetrieved != null) {
                      <span class="font-mono text-gray-500">· {{ i18n.t('chat.deep.passages', { count: deep.chunksRetrieved }) }}</span>
                    }
                    @if (deep.sourcesReturned != null) {
                      <span class="font-mono text-gray-500">· {{ i18n.t('chat.summary.sources', { count: deep.sourcesReturned }) }}</span>
                    }
                    @if (deepTopSourceLabels(deep).length) {
                      <span class="truncate text-gray-500">
                        · {{ deepTopSourceLabels(deep).join(' · ') }}
                      </span>
                    }
                  }
                  <span class="font-mono text-[10px] text-sky-300/70" [title]="deepInfo.deepPollUrl || deepInfo.deepJobId || ''">
                    · {{ i18n.t('chat.deep.tracking') }}
                  </span>
                  <button
                    type="button"
                    class="ml-auto inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-mono text-sky-300 hover:bg-sky-500/10 transition"
                    [disabled]="deepInfo.deepDetailsLoading"
                    (click)="toggleDeepRetrievalDetails(msg)"
                  >
                    <app-icon
                      [name]="deepInfo.deepDetailsOpen ? 'chevron-down' : 'chevron-right'"
                      [size]="11"
                    />
                    {{ i18n.t('chat.deep.details') }}
                  </button>
                  <div class="basis-full h-1 overflow-hidden rounded bg-sky-500/10">
                    <span
                      class="block h-full rounded bg-sky-300 transition-all duration-500"
                      [style.width.%]="deepRetrievalProgressValue(deepInfo)"
                    ></span>
                  </div>
                  @if (deepRetrievalRunning(deepInfo)) {
                    <span class="basis-full text-[10px] text-gray-500">
                      {{
                        i18n.t('chat.deep.server_note', {
                          url: deepTrackerPath(deepInfo),
                        })
                      }}
                    </span>
                  }
                </div>
                @if (deepInfo.deepDetailsOpen) {
                  <div class="ml-0 mt-1 rounded-md bg-white/[0.02] dark:bg-white/[0.03] ring-1 ring-sky-500/10 overflow-hidden">
                    @if (deepInfo.deepDetailsLoading) {
                      <div class="flex items-center gap-2 px-3 py-2 text-[11px] text-gray-500">
                        <app-icon name="loader" [size]="12" class="animate-spin text-sky-300" />
                        {{ i18n.t('chat.deep.details_loading') }}
                      </div>
                    } @else if (deepInfo.deepDetailsError) {
                      <div class="flex items-center gap-2 px-3 py-2 text-[11px] text-red-300">
                        <app-icon name="x-circle" [size]="12" />
                        {{ deepInfo.deepDetailsError }}
                      </div>
                    } @else {
                      @if (showDeepAnswerInDetails(msg, deepInfo)) {
                      @if (deepInfo.deepAnswer; as deepAnswer) {
                        <div class="border-b border-white/5 px-3 py-3 text-sm leading-relaxed text-gray-800 dark:text-gray-100">
                          <div class="mb-2 text-[10px] uppercase tracking-[0.16em] font-semibold text-sky-300">
                            {{ i18n.t('chat.deep.answer') }}
                          </div>
                          @for (block of renderMarkdownAnswer(deepAnswer, deepInfo.deepSources || msg.sources); track $index) {
                            @if (block.kind === 'heading') {
                              <h3 class="mt-2 first:mt-0 mb-1 text-[0.95rem] font-semibold text-gray-950 dark:text-white">
                                <ng-container [ngTemplateOutlet]="answerInline" [ngTemplateOutletContext]="{ tokens: block.tokens, sources: deepInfo.deepSources || msg.sources, sourceHostId: deepSourceHostId(msg), openDirectSources: false }"></ng-container>
                              </h3>
                            } @else if (block.kind === 'list') {
                              <ng-container [ngTemplateOutlet]="answerList" [ngTemplateOutletContext]="{ $implicit: block.items, sources: deepInfo.deepSources || msg.sources, sourceHostId: deepSourceHostId(msg), openDirectSources: false }"></ng-container>
                            } @else if (block.kind === 'codeblock') {
                              <pre class="my-2 max-w-full overflow-auto rounded-md bg-black/5 dark:bg-white/[0.06] p-2 text-xs leading-relaxed"><code>{{ block.value }}</code></pre>
                            } @else {
                              <p class="my-1 first:mt-0 last:mb-0">
                                <ng-container [ngTemplateOutlet]="answerInline" [ngTemplateOutletContext]="{ tokens: block.tokens, sources: deepInfo.deepSources || msg.sources, sourceHostId: deepSourceHostId(msg), openDirectSources: false }"></ng-container>
                              </p>
                            }
                          }
                        </div>
                      }
                      }
                      @if (deepInfo.deepSources?.length) {
                        <ol class="divide-y divide-white/5">
                          @for (src of deepInfo.deepSources!.slice(0, 8); track $index; let i = $index) {
                            <li
                              [id]="sourceDomId(deepSourceHostId(msg), i + 1)"
                              [class]="isSourceCitedForContent(deepInfo.deepAnswer || '', deepInfo.deepSources, i + 1)
                                ? 'px-3 py-2 text-[12px] transition-all bg-sky-500/10 ring-1 ring-sky-500/25'
                                : 'px-3 py-2 text-[12px] transition-all'"
                            >
                              <div class="flex items-center gap-2 mb-0.5">
                                <span class="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-mono shrink-0 bg-sky-500/15 text-sky-300">
                                  {{ i + 1 }}
                                </span>
                                <span class="font-medium text-gray-900 dark:text-white truncate">
                                  {{ sourceTitle(src) }}
                                </span>
                                @if (sourceLocator(src); as loc) {
                                  <span class="font-mono text-[10px] text-sky-300/80 shrink min-w-0 max-w-[14rem] truncate" [title]="loc.tooltip">
                                    · {{ loc.label }}
                                  </span>
                                }
                                @if (src.score != null) {
                                  <span class="ml-auto font-mono text-[10px] text-emerald-500 dark:text-emerald-400 shrink-0">
                                    {{ scoreDisplay(src.score) }}
                                  </span>
                                }
                                @if (canPreviewSource(src)) {
                                  <button
                                    type="button"
                                    class="shrink-0 inline-flex items-center justify-center rounded p-1 text-gray-500 hover:text-sky-300 hover:bg-white/5 transition"
                                    [class.ml-auto]="src.score == null"
                                    [title]="i18n.t('chat.sources.preview')"
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
                      } @else if (!deepInfo.deepAnswer) {
                        <div class="px-3 py-2 text-[11px] text-gray-500">
                          {{ i18n.t('chat.deep.details_empty') }}
                        </div>
                      }
                    }
                  </div>
                }
              }

              <!-- Post-chat audit toolbar -->
              <div class="flex items-center gap-1.5 ml-2 text-[11px] text-gray-500">
                <button
                  type="button"
                  class="p-1 rounded hover:bg-white/5 transition"
                  [class.text-emerald-400]="msg.feedback === 'up'"
                  [title]="i18n.t('chat.audit.helpful')"
                  (click)="rate(msg, 'up')"
                >
                  <app-icon name="thumbs-up" [size]="12" />
                </button>
                <button
                  type="button"
                  class="p-1 rounded hover:bg-white/5 transition"
                  [class.text-red-400]="msg.feedback === 'down'"
                  [title]="i18n.t('chat.audit.not_helpful')"
                  (click)="rate(msg, 'down')"
                >
                  <app-icon name="thumbs-down" [size]="12" />
                </button>
                <button
                  type="button"
                  class="p-1 rounded hover:bg-white/5 transition"
                  [title]="i18n.t('chat.audit.copy')"
                  (click)="copy(msg.content)"
                >
                  <app-icon name="copy" [size]="12" />
                </button>
                <button
                  type="button"
                  class="p-1 rounded hover:bg-sky-500/10 transition flex items-center gap-1 text-sky-300 disabled:opacity-50"
                  [title]="i18n.t('chat.audit.deep_search_hint')"
                  [disabled]="!!deepSearchTrackedJobId(msg) || deepSearchLaunchingId() === msg.id"
                  (click)="launchDeepSearch(msg)"
                >
                  @if (deepSearchLaunchingId() === msg.id) {
                    <app-icon name="loader-2" [size]="12" class="animate-spin" />
                    <span>{{ i18n.t('chat.audit.deep_launching') }}</span>
                  } @else if (deepSearchTrackedJobId(msg)) {
                    <app-icon name="check" [size]="12" />
                    <span>{{ i18n.t('chat.audit.deep_tracked') }}</span>
                  } @else {
                    <app-icon name="search" [size]="12" />
                    <span>{{ i18n.t('chat.audit.deep_search') }}</span>
                  }
                </button>
                @if (!isDemoMode()) {
                  <button
                    type="button"
                    class="p-1 rounded hover:bg-white/5 transition flex items-center gap-1"
                    [title]="i18n.t('chat.audit.fact_check_hint')"
                    [disabled]="evaluatingId() === msg.id"
                    (click)="factCheck(msg)"
                  >
                    @if (evaluatingId() === msg.id) {
                      <app-icon name="loader-2" [size]="12" class="animate-spin" />
                      <span>{{ i18n.t('chat.audit.scoring') }}</span>
                    } @else {
                      <app-icon name="shield-check" [size]="12" />
                      <span>{{ i18n.t('chat.audit.fact_check') }}</span>
                    }
                  </button>
                }
                @if (canCorrectInChat()) {
                  <button
                    type="button"
                    class="p-1 rounded hover:bg-emerald-500/10 transition flex items-center gap-1 text-emerald-600 dark:text-emerald-300"
                    [class.bg-emerald-500\\/10]="correctionOpenFor() === msg.id"
                    [title]="i18n.t('chat.correct.hint')"
                    (click)="toggleCorrection(msg)"
                  >
                    <app-icon name="pencil" [size]="12" />
                    <span>{{ i18n.t('chat.correct.action') }}</span>
                  </button>
                }
                @if (!isDemoMode() && msg.evaluation) {
                  <span class="ml-auto font-mono text-[10px] text-emerald-400"
                    >{{ i18n.t('chat.audit.score', { value: (msg.evaluation.composite_score?.toFixed(1) ?? '—') }) }}</span
                  >
                }
              </div>

              <!-- Inline expert correction composer -->
              @if (canCorrectInChat() && correctionOpenFor() === msg.id) {
                <div class="ml-2 mt-1.5 rounded-lg border border-emerald-500/25 bg-emerald-500/[0.04] p-3 space-y-2">
                  <div class="flex items-center justify-between gap-2">
                    <div class="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-emerald-600 dark:text-emerald-300 font-semibold">
                      <app-icon name="pencil" [size]="12" />
                      {{ i18n.t('chat.correct.title') }}
                    </div>
                    <button
                      type="button"
                      class="p-1 rounded text-gray-500 hover:text-gray-300 hover:bg-white/5 transition"
                      [title]="i18n.t('common.close')"
                      (click)="closeCorrection()"
                    >
                      <app-icon name="x" [size]="12" />
                    </button>
                  </div>

                  @if (correctionQuestionFor(msg); as question) {
                    <p class="text-[11px] text-gray-500 dark:text-gray-400 leading-relaxed">
                      <span class="font-semibold text-gray-600 dark:text-gray-300">{{
                        i18n.t('chat.correct.question')
                      }}</span>
                      <span class="line-clamp-2">{{ question }}</span>
                    </p>
                  }

                  <div class="flex items-start gap-2">
                    <textarea
                      rows="3"
                      class="flex-1 resize-y rounded-md border border-black/10 dark:border-white/10 bg-white dark:bg-white/[0.03] px-2.5 py-2 text-[12px] text-gray-900 dark:text-gray-100 placeholder:text-gray-400 focus:outline-none focus:ring-1 focus:ring-emerald-500/40"
                      [placeholder]="i18n.t('chat.correct.placeholder')"
                      [ngModel]="correctionText()"
                      (ngModelChange)="correctionText.set($event)"
                    ></textarea>
                    <button
                      type="button"
                      class="shrink-0 inline-flex items-center justify-center w-9 h-9 rounded-full transition ring-1"
                      [class.bg-red-500\\/15]="correctionMicState() === 'recording'"
                      [class.text-red-400]="correctionMicState() === 'recording'"
                      [class.ring-red-500\\/40]="correctionMicState() === 'recording'"
                      [class.animate-pulse]="correctionMicState() === 'recording'"
                      [class.bg-emerald-500\\/10]="correctionMicState() !== 'recording'"
                      [class.text-emerald-600]="correctionMicState() !== 'recording'"
                      [class.dark:text-emerald-300]="correctionMicState() !== 'recording'"
                      [class.ring-emerald-500\\/30]="correctionMicState() !== 'recording'"
                      [disabled]="correctionMicState() === 'transcribing' || correctionSubmitting()"
                      [title]="correctionMicState() === 'recording'
                        ? i18n.t('chat.correct.mic.stop')
                        : (correctionMicState() === 'transcribing'
                            ? i18n.t('chat.correct.mic.transcribing')
                            : i18n.t('chat.correct.mic.start'))"
                      (click)="toggleCorrectionMic()"
                    >
                      @if (correctionMicState() === 'transcribing') {
                        <app-icon name="loader-2" [size]="15" class="animate-spin" />
                      } @else if (correctionMicState() === 'recording') {
                        <app-icon name="square" [size]="14" />
                      } @else {
                        <app-icon name="mic" [size]="15" />
                      }
                    </button>
                  </div>

                  @if ((correctionMicState() === 'recording' || correctionMicState() === 'transcribing') && correctionLiveTranscript()) {
                    <div class="rounded-md bg-black/5 dark:bg-white/5 px-2.5 py-1.5 text-[11px] italic leading-relaxed text-gray-600 dark:text-gray-300">
                      <span class="not-italic text-[9px] uppercase tracking-wider text-emerald-600 dark:text-emerald-300 mr-1.5 align-middle">{{ i18n.t('chat.correct.live') }}</span>{{ correctionLiveTranscript() }}
                    </div>
                  }

                  <div class="flex items-center justify-between gap-2">
                    <span class="text-[10px] text-gray-500">
                      @switch (correctionMicState()) {
                        @case ('recording') {
                          <span class="text-red-400">{{ i18n.t('chat.correct.state.recording') }}</span>
                        }
                        @case ('transcribing') { {{ i18n.t('chat.correct.mic.transcribing') }} }
                        @case ('ready') { {{ i18n.t('chat.correct.state.ready') }} }
                        @default { {{ i18n.t('chat.correct.state.idle') }} }
                      }
                    </span>
                    <div class="flex items-center gap-1.5">
                      <button
                        type="button"
                        class="px-2 py-1 rounded text-[11px] text-gray-500 hover:text-gray-300 hover:bg-white/5 transition"
                        (click)="closeCorrection()"
                      >
                        {{ i18n.t('common.cancel') }}
                      </button>
                      <button
                        type="button"
                        class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] font-semibold bg-emerald-500/15 text-emerald-600 dark:text-emerald-300 ring-1 ring-emerald-500/30 hover:bg-emerald-500/25 transition disabled:opacity-50 disabled:cursor-not-allowed"
                        [disabled]="!correctionText().trim()
                          || correctionSubmitting()
                          || correctionMicState() === 'recording'
                          || correctionMicState() === 'transcribing'"
                        (click)="submitCorrection(msg)"
                      >
                        @if (correctionSubmitting()) {
                          <app-icon name="loader-2" [size]="12" class="animate-spin" />
                          <span>{{ i18n.t('chat.correct.sending') }}</span>
                        } @else {
                          <app-icon name="send" [size]="12" />
                          <span>{{ i18n.t('chat.correct.submit') }}</span>
                        }
                      </button>
                    </div>
                  </div>
                </div>
              }

              <!-- Persistent trace of a submitted correction: keeps the record
                   visible in the chat after the composer collapses. -->
              @if (canCorrectInChat() && correctionTraceFor(msg.id); as trace) {
                <div class="ml-2 mt-1.5 rounded-lg border border-emerald-500/25 bg-emerald-500/[0.06] p-2.5 space-y-1">
                  <div class="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-emerald-600 dark:text-emerald-300 font-semibold">
                    <app-icon name="check-circle" [size]="12" />
                    @if (trace.status === 'published') {
                      <span>{{ i18n.t('chat.correct.trace.published') }}</span>
                    } @else {
                      <span>{{ i18n.t('chat.correct.trace.sent') }}</span>
                    }
                    @if (trace.usedVoice) {
                      <app-icon
                        name="mic"
                        [size]="11"
                        class="opacity-70"
                        [title]="i18n.t('chat.correct.trace.voice')"
                      />
                    }
                  </div>
                  <p class="text-[11px] text-gray-600 dark:text-gray-300 leading-relaxed whitespace-pre-wrap">{{ trace.correction }}</p>
                  <div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] text-gray-500">
                    @if (trace.status === 'published') {
                      <span>{{ i18n.t('chat.correct.trace.published_note') }}</span>
                    } @else {
                      <span>{{ i18n.t('chat.correct.trace.pending_note') }}</span>
                      @if (trace.reviewQueueUrl) {
                        <button
                          type="button"
                          class="text-emerald-600 dark:text-emerald-300 hover:underline"
                          (click)="openReviewQueue(trace.reviewQueueUrl)"
                        >
                          {{ i18n.t('chat.correct.trace.queue') }}
                        </button>
                      }
                    }
                  </div>
                </div>
              }

              <!-- Calm, end-user-friendly auto-QA marker. Replaces the alarming
                   top toast for everyone; operators additionally get the raw
                   breach metrics inline (and still receive the verbose toast). -->
              @if (msg.qaReview; as qa) {
                <div class="ml-2 mt-1.5 flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    class="qa-review-badge inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium bg-amber-500/10 text-amber-700 dark:text-amber-300 ring-1 ring-amber-500/25 hover:bg-amber-500/15 transition"
                    [title]="qaReviewTooltip()"
                    (click)="openQaReview(qa.decisionId, qa.runId)"
                  >
                    <app-icon name="shield-alert" [size]="12" />
                    <span>{{ i18n.t('chat.qa.verify') }}</span>
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
                    {{ i18n.t('chat.audit.claims') }}
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
                  class="ck-chat-progress inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-[12px] text-gray-600 dark:text-gray-300 bg-gray-100 dark:bg-white/[0.04] ring-1 ring-white/5"
                  aria-live="polite"
                >
                  <ck-thinking-orb [state]="progress.orb" [size]="20" [label]="progress.label" />
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
                    [class.border-cyan-500\\/30]="step.status === 'active'"
                    [class.bg-cyan-500\\/5]="step.status === 'active'"
                    [class.border-white\\/5]="!step.status || step.status === 'pending'"
                  >
                    <app-icon
                      [name]="iconFor(step)"
                      [size]="12"
                      [class.text-emerald-400]="step.status === 'completed'"
                      [class.text-cyan-400]="step.status === 'active'"
                      [class.text-gray-500]="!step.status || step.status === 'pending'"
                      [class.animate-spin]="step.status === 'active'"
                    />
                    <span class="font-medium text-white">{{
                      step.title || step.type || i18n.t('chat.trail.step')
                    }}</span>
                    @if (step.status === 'completed' && step.duration) {
                      <span class="text-[10px] font-mono text-gray-500 ml-auto"
                        >{{ step.duration }}ms</span
                      >
                    } @else if (step.status === 'active') {
                      <span class="text-[9px] uppercase tracking-wider text-cyan-400 ml-auto"
                        >{{ i18n.t('chat.trail.running') }}</span
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
                  {{ streamBuffer() }}<span class="inline-block w-1.5 h-4 bg-cyan-400 ml-0.5 animate-pulse align-middle"></span>
                </div>
              </div>
            }
            @if (liveRetrievalInfo()?.deepJobId && liveRetrievalInfo(); as deepInfo) {
              <div
                class="ml-0 mt-1 rounded-md px-3 py-2 bg-sky-500/5 ring-1 ring-sky-500/15 flex flex-wrap items-center gap-2 text-[11px] text-gray-700 dark:text-gray-300"
                [title]="deepRetrievalTitle(deepInfo)"
                aria-live="polite"
              >
                @if (deepInfo.deepStatus === 'completed') {
                  <app-icon name="check" [size]="11" class="text-sky-300 shrink-0" />
                } @else if (deepInfo.deepStatus === 'failed' || deepInfo.deepStatus === 'cancelled') {
                  <app-icon name="x-circle" [size]="11" class="text-red-300 shrink-0" />
                } @else {
                  <ck-thinking-orb state="searching" [size]="20" [label]="deepRetrievalLabel(deepInfo)" />
                }
                <span class="font-medium text-sky-300">{{ deepRetrievalLabel(deepInfo) }}</span>
                @if (deepInfo.deepStage) {
                  <span class="font-mono text-gray-500">· {{ deepInfo.deepStage }}</span>
                }
                <span class="font-mono text-[10px] text-sky-300/70" [title]="deepInfo.deepPollUrl || deepInfo.deepJobId || ''">
                  · {{ i18n.t('chat.deep.tracking') }}
                </span>
                <div class="basis-full h-1 overflow-hidden rounded bg-sky-500/10">
                  <span
                    class="block h-full rounded bg-sky-300 transition-all duration-500"
                    [style.width.%]="deepRetrievalProgressValue(deepInfo)"
                  ></span>
                </div>
                @if (deepRetrievalRunning(deepInfo)) {
                  <span class="basis-full text-[10px] text-gray-500">
                    {{ i18n.t('chat.deep.resume_note') }}
                  </span>
                }
              </div>
            }
          </div>
        }
      </div>

      <!-- Live dictation preview: partial transcript while recording -->
      @if (recording() && voicePartial()) {
        <div class="px-3 pt-2 -mb-1 flex items-center gap-2 text-xs text-gray-400">
          <app-icon name="mic" [size]="12" class="text-cyan-300 animate-pulse" />
          <span class="italic truncate">{{ voicePartial() }}</span>
        </div>
      }

      <!-- Input -->
      <form
        (ngSubmit)="send()"
        class="ck-chat-input-bar flex items-end gap-2 p-3 border-t border-white/5 bg-white/[0.02]"
        [class.vigie-input-bar]="executiveMode()"
      >
        <button
          type="button"
          class="p-2.5 rounded-xl transition ring-1 relative"
          [class.vigie-mic-button]="executiveMode()"
          [class.bg-red-500\\/20]="recording()"
          [class.ring-red-500\\/40]="recording()"
          [class.text-red-300]="recording()"
          [class.bg-cyan-500\\/20]="transcribing()"
          [class.ring-cyan-500\\/40]="transcribing()"
          [class.text-cyan-300]="transcribing()"
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
          class="ck-chat-input flex-1 resize-none px-4 py-2.5 bg-white dark:bg-white/5 border border-gray-200 dark:border-white/10 rounded-xl focus:outline-none focus:ring-2 focus:ring-cyan-400 text-sm max-h-32"
          [placeholder]="inputPlaceholder()"
          [disabled]="streaming()"
          (keydown)="onKey($event)"
        ></textarea>
        <button
          type="submit"
          [disabled]="streaming() || !userInput.trim()"
          class="ck-chat-send px-4 py-2.5 bg-cyan-500 hover:bg-cyan-600 disabled:opacity-50 text-white rounded-xl transition text-sm font-medium flex items-center gap-1.5"
          [class.vigie-send-button]="executiveMode()"
        >
          <app-icon [name]="streaming() ? 'loader-2' : 'send'" [size]="14" [class.animate-spin]="streaming()" />
          {{ streaming() ? streamingLabel() : sendLabel() }}
        </button>
      </form>
    </div>
    </div>

    <app-document-preview
      [open]="sourcePreviewOpen()"
      [previewUrl]="sourcePreviewUrl()"
      [title]="sourcePreviewTitle()"
      [page]="sourcePreviewPage()"
      [highlight]="sourcePreviewHighlight()"
      [subtitle]="i18n.t('chat.preview.source_subtitle')"
      (closed)="closeSourcePreview()"
    />
  `,
	  styles: [`
    .ck-chat-empty-mark {
      border: 1px solid color-mix(in oklab, var(--ck-signal-cool, #22d3ee) 24%, transparent);
      background: color-mix(in oklab, var(--ck-signal-cool, #22d3ee) 10%, var(--ck-bg-inset, #0f172a));
      color: var(--ck-signal-cool, #22d3ee);
      box-shadow: inset 0 0 0 1px color-mix(in oklab, var(--ck-signal-cool, #22d3ee) 7%, transparent);
    }
    .ck-chat-trace-summary {
      border: 1px solid color-mix(in oklab, var(--ck-signal-cool, #22d3ee) 16%, transparent);
      background: color-mix(in oklab, var(--ck-signal-cool, #22d3ee) 5%, var(--ck-bg-inset, #0f172a));
    }
	    .chat-history-shell {
      display: flex;
      height: 100%;
      min-height: 0;
      width: 100%;
      background: rgba(3, 8, 16, 0.18);
    }
    .chat-history-shell.chat-history-embed {
      display: block;
    }
    .chat-history-shell.chat-history-embed .chat-history-panel {
      display: none;
    }
    .chat-history-expand {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 6px;
      width: 38px;
      flex: 0 0 38px;
      min-height: 0;
      border: 0;
      border-right: 1px solid rgba(255, 255, 255, 0.06);
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.028), rgba(255, 255, 255, 0.010)),
        rgba(2, 7, 14, 0.72);
      color: rgba(148, 163, 184, 0.9);
      font: 700 10px/1 var(--ck-font-mono, ui-monospace, monospace);
    }
    .chat-history-expand:hover {
      color: rgba(226, 232, 240, 1);
      background-color: rgba(255, 255, 255, 0.045);
    }
    .chat-history-panel {
      display: flex;
      flex-direction: column;
      width: 260px;
      min-width: 220px;
      max-width: 280px;
      min-height: 0;
      border-right: 1px solid rgba(255, 255, 255, 0.06);
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.028), rgba(255, 255, 255, 0.010)),
        rgba(2, 7, 14, 0.72);
    }
    .chat-history-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 12px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    }
    .chat-history-tools {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .chat-history-toggle {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 30px;
      height: 30px;
      border-radius: 8px;
      color: rgba(226, 232, 240, 0.86);
      background: rgba(255, 255, 255, 0.045);
      border: 1px solid rgba(255, 255, 255, 0.08);
      transition: 140ms ease;
    }
    .chat-history-toggle:hover {
      color: rgba(226, 232, 240, 1);
      background: rgba(255, 255, 255, 0.08);
    }
    .chat-history-kicker {
      color: rgba(125, 211, 252, 0.88);
      font: 750 10px/1.2 var(--ck-font-mono, ui-monospace, monospace);
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }
    .chat-history-count {
      margin-top: 3px;
      color: rgba(148, 163, 184, 0.82);
      font-size: 11px;
    }
    .chat-history-new {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 30px;
      height: 30px;
      border-radius: 8px;
      color: rgba(226, 232, 240, 0.92);
      background: rgba(56, 189, 248, 0.12);
      border: 1px solid rgba(56, 189, 248, 0.28);
      transition: 140ms ease;
    }
    .chat-history-new:hover:not(:disabled) {
      background: rgba(56, 189, 248, 0.18);
      border-color: rgba(56, 189, 248, 0.42);
    }
    .chat-history-new:disabled {
      cursor: wait;
      opacity: 0.55;
    }
    .chat-history-search {
      display: flex;
      align-items: center;
      gap: 7px;
      margin: 10px 10px 8px;
      padding: 7px 9px;
      border-radius: 8px;
      border: 1px solid rgba(148, 163, 184, 0.14);
      background: rgba(15, 23, 42, 0.58);
      color: rgba(148, 163, 184, 0.88);
    }
    .chat-history-search input {
      width: 100%;
      min-width: 0;
      border: 0;
      outline: 0;
      background: transparent;
      color: rgba(226, 232, 240, 0.94);
      font-size: 12px;
    }
    .chat-history-search input::placeholder {
      color: rgba(148, 163, 184, 0.62);
    }
    .chat-history-list {
      flex: 1;
      min-height: 0;
      overflow-y: auto;
      padding: 4px 8px 10px;
    }
    .chat-history-empty {
      display: flex;
      align-items: center;
      gap: 7px;
      padding: 12px 8px;
      color: rgba(148, 163, 184, 0.76);
      font-size: 12px;
    }
    .chat-history-item {
      position: relative;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      grid-template-rows: auto auto;
      gap: 2px 8px;
      width: 100%;
      margin: 2px 0;
      padding: 9px 8px;
      border-radius: 8px;
      border: 1px solid transparent;
      cursor: pointer;
      color: rgba(226, 232, 240, 0.88);
      background: transparent;
      transition: 120ms ease;
    }
    .chat-history-item:hover {
      background: rgba(255, 255, 255, 0.045);
      border-color: rgba(255, 255, 255, 0.06);
    }
    .chat-history-item-active {
      background: rgba(56, 189, 248, 0.105);
      border-color: rgba(56, 189, 248, 0.28);
    }
    .chat-history-title {
      grid-column: 1;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 12px;
      font-weight: 650;
    }
    .chat-history-subtitle {
      grid-column: 1;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: rgba(148, 163, 184, 0.70);
      font-size: 10px;
    }
    .chat-history-actions {
      grid-column: 2;
      grid-row: 1 / span 2;
      display: inline-flex;
      align-items: center;
      gap: 3px;
      opacity: 0;
      transition: 120ms ease;
    }
    .chat-history-item:hover .chat-history-actions,
    .chat-history-item-active .chat-history-actions {
      opacity: 1;
    }
    .chat-history-actions button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 22px;
      height: 22px;
      border-radius: 6px;
      color: rgba(148, 163, 184, 0.92);
    }
    .chat-history-actions button:hover {
      color: rgba(226, 232, 240, 0.96);
      background: rgba(255, 255, 255, 0.07);
    }
    @media (max-width: 900px) {
      .chat-history-panel {
        display: none;
      }
    }
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
      flex-wrap: wrap;
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
    .mini-select {
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
    .mini-select:focus {
      box-shadow: 0 0 0 1px rgba(103, 213, 246, 0.42);
      background: rgba(6, 13, 25, 0.76);
    }
    .source-picker-chevron,
    .mini-select-chevron {
      position: absolute;
      right: 7px;
      color: rgba(177, 190, 210, 0.72);
      pointer-events: none;
    }
    .session-doc-mode {
      padding: 3px;
      max-width: 100%;
      flex-wrap: wrap;
    }
    .session-doc-label {
      padding-left: 6px;
      min-width: 0;
      white-space: normal;
      overflow-wrap: anywhere;
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
    .mini-select-wrap {
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
    .vigie-empty-state button .bg-cyan-500\\/10,
    .vigie-empty-state button .group-hover\\:bg-cyan-500\\/20 {
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

    /* ============================================================
       LIGHT THEME — the hard-coded rgba() rules above are written for
       the dark cockpit and have no light counterpart, so this block
       re-states them in tokens under [data-theme="light"]. The dark
       cockpit above is left byte-identical.

       It deliberately does NOT touch dark:* utilities. Those fire only
       under a .dark ancestor, which the theme unlock now removes in
       light; and every dark:* class in this template is written beside
       a light-correct base class -- "text-gray-900 dark:text-white",
       "bg-gray-100 dark:bg-white/[0.04]". Overriding the dark: half was
       the only vector back when html was pinned .dark; today it would
       beat the base class on specificity and, for the bubbles, replace
       the intended bg-gray-100 with a 5 % wash.

       Bare greys and white washes are also handled by the global
       html:not(.dark) net in styles.scss; the rules kept here are the
       same intent expressed on the cockpit --ck-fg-* tiering, which is
       what the rest of this component's own classes use. The accent
       families (cyan, sky, emerald, amber, red) have no equivalent in
       the global net at all.
       ============================================================ */

    /* --- Answer body + inline markup: neutral Tailwind utilities. --- */
    :host-context([data-theme="light"]) .text-gray-200,
    :host-context([data-theme="light"]) .text-gray-300 { color: var(--ck-fg-2); }
    :host-context([data-theme="light"]) .text-gray-400 { color: var(--ck-fg-3); }
    :host-context([data-theme="light"]) .text-gray-500 { color: var(--ck-fg-4); }
    :host-context([data-theme="light"]) .hover\\:text-white:hover { color: var(--ck-fg-1); }
    :host-context([data-theme="light"]) .hover\\:text-gray-300:hover,
    :host-context([data-theme="light"]) .hover\\:text-gray-200:hover,
    :host-context([data-theme="light"]) .group:hover .group-hover\\:text-gray-300 { color: var(--ck-fg-2); }

    /* --- Accents: preserve semantics, pull to AA-on-paper signals.
           Covers citation chips ([n]), SOURCES icon, deep-search sky,
           positive/warn/negative states. --- */
    :host-context([data-theme="light"]) .text-cyan-300,
    :host-context([data-theme="light"]) .text-cyan-400,
    :host-context([data-theme="light"]) .text-cyan-400\\/80,
    :host-context([data-theme="light"]) .text-cyan-500,
    :host-context([data-theme="light"]) .text-sky-200,
    :host-context([data-theme="light"]) .text-sky-300,
    :host-context([data-theme="light"]) .text-sky-300\\/80,
    :host-context([data-theme="light"]) .text-sky-300\\/70,
    :host-context([data-theme="light"]) .hover\\:text-cyan-200:hover,
    :host-context([data-theme="light"]) .hover\\:text-cyan-300:hover,
    :host-context([data-theme="light"]) .hover\\:text-cyan-400:hover,
    :host-context([data-theme="light"]) .hover\\:text-sky-300:hover { color: var(--ck-signal-cool); }
    :host-context([data-theme="light"]) .text-emerald-300,
    :host-context([data-theme="light"]) .text-emerald-400,
    :host-context([data-theme="light"]) .text-emerald-500,
    :host-context([data-theme="light"]) .text-emerald-600 { color: var(--ck-signal-pos); }
    :host-context([data-theme="light"]) .text-amber-200,
    :host-context([data-theme="light"]) .text-amber-300,
    :host-context([data-theme="light"]) .text-amber-400,
    :host-context([data-theme="light"]) .text-amber-700 { color: var(--ck-signal-warn); }
    :host-context([data-theme="light"]) .text-red-300,
    :host-context([data-theme="light"]) .text-red-400 { color: var(--ck-signal-neg); }

    /* Faint white surface washes read as invisible mud on paper —
       give source cards / badges a subtle black tint instead. */
    :host-context([data-theme="light"]) .bg-white\\/5,
    :host-context([data-theme="light"]) .bg-white\\/\\[0\\.02\\] { background-color: var(--ck-tint-faint); }

    /* --- QA / warn pills (Réponse à vérifier, missing citations) --- */
    :host-context([data-theme="light"]) .qa-review-badge,
    :host-context([data-theme="light"]) .bg-amber-500\\/10.text-amber-300 {
      background: color-mix(in oklab, var(--ck-signal-warn) 14%, var(--ck-bg-panel-hi)) !important;
      color: var(--ck-signal-warn) !important;
      --tw-ring-color: color-mix(in oklab, var(--ck-signal-warn) 38%, transparent);
      box-shadow: inset 0 0 0 1px color-mix(in oklab, var(--ck-signal-warn) 38%, transparent);
    }
    :host-context([data-theme="light"]) .qa-review-badge:hover {
      background: color-mix(in oklab, var(--ck-signal-warn) 20%, var(--ck-bg-panel-hi)) !important;
    }

    /* --- Chat history sidebar --- */
    :host-context([data-theme="light"]) .chat-history-shell { background: transparent; }
    :host-context([data-theme="light"]) .chat-history-panel {
      border-right-color: var(--ck-stroke-1);
      background: var(--ck-bg-panel);
    }
    :host-context([data-theme="light"]) .chat-history-head { border-bottom-color: var(--ck-stroke-1); }
    :host-context([data-theme="light"]) .chat-history-kicker { color: var(--ck-signal-cool); }
    :host-context([data-theme="light"]) .chat-history-count,
    :host-context([data-theme="light"]) .chat-history-subtitle,
    :host-context([data-theme="light"]) .chat-history-empty,
    :host-context([data-theme="light"]) .chat-history-actions button { color: var(--ck-fg-3); }
    :host-context([data-theme="light"]) .chat-history-new {
      color: var(--ck-signal-cool);
      background: color-mix(in oklab, var(--ck-signal-cool) 12%, transparent);
      border-color: color-mix(in oklab, var(--ck-signal-cool) 30%, transparent);
    }
    :host-context([data-theme="light"]) .chat-history-new:hover:not(:disabled) {
      background: color-mix(in oklab, var(--ck-signal-cool) 18%, transparent);
      border-color: color-mix(in oklab, var(--ck-signal-cool) 42%, transparent);
    }
    :host-context([data-theme="light"]) .chat-history-search {
      border-color: var(--ck-stroke-2);
      background: var(--ck-bg-inset);
      color: var(--ck-fg-3);
    }
    :host-context([data-theme="light"]) .chat-history-search input { color: var(--ck-fg-1); }
    :host-context([data-theme="light"]) .chat-history-search input::placeholder { color: var(--ck-fg-5); }
    :host-context([data-theme="light"]) .chat-history-item { color: var(--ck-fg-2); }
    :host-context([data-theme="light"]) .chat-history-item:hover {
      background: var(--ck-tint-faint);
      border-color: var(--ck-stroke-1);
    }
    :host-context([data-theme="light"]) .chat-history-item-active {
      background: color-mix(in oklab, var(--ck-signal-cool) 12%, transparent);
      border-color: color-mix(in oklab, var(--ck-signal-cool) 30%, transparent);
    }
    :host-context([data-theme="light"]) .chat-history-actions button:hover {
      color: var(--ck-fg-1);
      background: var(--ck-tint-soft);
    }

    /* --- Vigie context bar + trace/voice actions --- */
    :host-context([data-theme="light"]) .vigie-context-bar {
      border-bottom-color: var(--ck-stroke-1);
      background: var(--ck-bg-panel);
    }
    :host-context([data-theme="light"]) .vigie-kicker { color: var(--ck-signal-warn); }
    :host-context([data-theme="light"]) .vigie-scope-line { color: var(--ck-fg-3); }
    :host-context([data-theme="light"]) .vigie-trace-button {
      border-color: var(--ck-stroke-2);
      background: var(--ck-bg-panel-hi);
      color: var(--ck-fg-2);
    }
    :host-context([data-theme="light"]) .vigie-trace-button:hover {
      border-color: var(--ck-stroke-3);
      color: var(--ck-fg-1);
      background: var(--ck-bg-inset);
    }
    :host-context([data-theme="light"]) .vigie-voice-primary {
      border-color: color-mix(in oklab, var(--ck-signal-pos) 45%, transparent);
      background: var(--ck-signal-pos);
      color: var(--ck-on-signal);
      box-shadow: none;
    }
    :host-context([data-theme="light"]) .vigie-voice-primary:hover:not(:disabled) {
      border-color: var(--ck-signal-pos);
      background: color-mix(in oklab, var(--ck-signal-pos) 88%, black);
      color: var(--ck-on-signal);
    }
    :host-context([data-theme="light"]) .vigie-voice-primary-active,
    :host-context([data-theme="light"]) .vigie-voice-primary-paused {
      border-color: color-mix(in oklab, var(--ck-signal-warn) 50%, transparent);
      background: var(--ck-signal-warn);
      color: var(--ck-on-signal);
    }
    :host-context([data-theme="light"]) .vigie-voice-stop {
      border-color: color-mix(in oklab, var(--ck-signal-neg) 45%, transparent);
      background: var(--ck-signal-neg);
      color: var(--ck-on-signal);
    }
    :host-context([data-theme="light"]) .vigie-voice-stop:hover { color: var(--ck-on-signal); }

    /* --- Control bar: mode chip, source picker, selects, info dot --- */
    :host-context([data-theme="light"]) .chat-control-bar {
      border-bottom-color: var(--ck-stroke-1);
      background: var(--ck-bg-panel);
    }
    :host-context([data-theme="light"]) .chat-mode-chip {
      border-color: var(--ck-stroke-2);
      background: var(--ck-bg-panel-hi);
      color: var(--ck-fg-2);
    }
    :host-context([data-theme="light"]) .chat-mode-model,
    :host-context([data-theme="light"]) .source-picker-label,
    :host-context([data-theme="light"]) .session-doc-label,
    :host-context([data-theme="light"]) .mini-control-label,
    :host-context([data-theme="light"]) .source-picker-chevron,
    :host-context([data-theme="light"]) .mini-select-chevron,
    :host-context([data-theme="light"]) .session-doc-mode-button,
    :host-context([data-theme="light"]) .control-info-dot { color: var(--ck-fg-3); }
    :host-context([data-theme="light"]) .source-picker-label app-icon,
    :host-context([data-theme="light"]) .session-doc-label app-icon,
    :host-context([data-theme="light"]) .mini-control-label app-icon { color: var(--ck-signal-cool); }
    :host-context([data-theme="light"]) .source-picker,
    :host-context([data-theme="light"]) .session-doc-mode,
    :host-context([data-theme="light"]) .mini-control {
      border-color: var(--ck-stroke-2);
      background: var(--ck-bg-panel-hi);
      box-shadow: inset 0 1px 0 var(--ck-tint-faint);
    }
    :host-context([data-theme="light"]) .source-picker-select,
    :host-context([data-theme="light"]) .mini-select {
      background: var(--ck-bg-inset);
      color: var(--ck-fg-1);
      color-scheme: light;
    }
    :host-context([data-theme="light"]) .session-doc-mode-button:hover {
      color: var(--ck-fg-1);
      background: var(--ck-tint-soft);
    }
    :host-context([data-theme="light"]) .control-info-dot {
      background: var(--ck-tint-soft);
      box-shadow: inset 0 0 0 1px var(--ck-stroke-2);
    }

    /* --- Action surface bar (Corriger / Compléter / Deep search) --- */
    :host-context([data-theme="light"]) .action-surface-bar {
      border-bottom-color: var(--ck-stroke-1);
      background: var(--ck-bg-panel);
    }
    :host-context([data-theme="light"]) .action-surface-label { color: var(--ck-fg-3); }
    :host-context([data-theme="light"]) .action-chip {
      border-color: color-mix(in oklab, var(--ck-signal-cool) 26%, transparent);
      background: color-mix(in oklab, var(--ck-signal-cool) 9%, transparent);
      color: var(--ck-signal-cool);
    }
    :host-context([data-theme="light"]) .action-chip:hover {
      border-color: color-mix(in oklab, var(--ck-signal-cool) 40%, transparent);
      background: color-mix(in oklab, var(--ck-signal-cool) 15%, transparent);
    }
    :host-context([data-theme="light"]) .action-empty-chip {
      border-color: var(--ck-stroke-2);
      background: var(--ck-tint-faint);
      color: var(--ck-fg-2);
    }
    :host-context([data-theme="light"]) .action-chip span {
      background: color-mix(in oklab, var(--ck-signal-warn) 18%, transparent);
      color: var(--ck-signal-warn);
    }

    /* --- Voice chips this component owns. The voice control bar, the
           transport toggle, the loop actions and the oracle panel belong to
           app-voice-controls; view encapsulation means a rule written here
           can never reach them, so both their base and light styles live in
           that component's own styles. --- */
    :host-context([data-theme="light"]) .demo-voice-chips-head,
    :host-context([data-theme="light"]) .demo-voice-dismiss { color: var(--ck-fg-3); }

    /* --- Message stream: kill the dark top-haze on the paper --- */
    :host-context([data-theme="light"]) .vigie-messages { background: transparent; }

    /* --- Empty state (accent hexes → warn/pos signals) --- */
    :host-context([data-theme="light"]) .vigie-empty-state > div:first-child {
      border-color: color-mix(in oklab, var(--ck-signal-warn) 40%, transparent) !important;
      background: color-mix(in oklab, var(--ck-signal-warn) 14%, var(--ck-bg-panel-hi)) !important;
      color: var(--ck-signal-warn) !important;
      box-shadow: var(--ck-shadow-card) !important;
    }
    :host-context([data-theme="light"]) .vigie-empty-state > div:first-child app-icon { color: var(--ck-signal-warn) !important; }
    :host-context([data-theme="light"]) .vigie-empty-state button {
      border-color: var(--ck-stroke-2) !important;
      background: var(--ck-bg-panel-hi) !important;
    }
    :host-context([data-theme="light"]) .vigie-empty-state button:hover {
      border-color: color-mix(in oklab, var(--ck-signal-warn) 30%, transparent) !important;
      background: var(--ck-bg-inset) !important;
    }
    :host-context([data-theme="light"]) .vigie-empty-state button .bg-cyan-500\\/10,
    :host-context([data-theme="light"]) .vigie-empty-state button .group-hover\\:bg-cyan-500\\/20 {
      background: color-mix(in oklab, var(--ck-signal-pos) 12%, transparent) !important;
      color: var(--ck-signal-pos) !important;
    }

    /* --- Bubbles: user = solid green pill, assistant = light paper card
           with dark-on-paper answer text (was pale near-white). --- */
    :host-context([data-theme="light"]) .vigie-user-bubble {
      border-color: color-mix(in oklab, var(--ck-signal-pos) 40%, transparent) !important;
      background: var(--ck-signal-pos) !important;
      color: var(--ck-on-signal) !important;
      box-shadow: var(--ck-shadow-card) !important;
    }
    :host-context([data-theme="light"]) .vigie-assistant-bubble {
      border-color: var(--ck-stroke-2) !important;
      background: var(--ck-bg-panel-hi) !important;
      color: var(--ck-fg-1) !important;
      box-shadow: var(--ck-shadow-card) !important;
    }
    :host-context([data-theme="light"]) .vigie-map-chip {
      border-color: color-mix(in oklab, var(--ck-signal-pos) 30%, transparent) !important;
      background: color-mix(in oklab, var(--ck-signal-pos) 12%, transparent) !important;
      color: var(--ck-signal-pos) !important;
      box-shadow: none !important;
    }

    /* --- Composer / input bar (accent hexes → signals) --- */
    :host-context([data-theme="light"]) .vigie-input-bar {
      background: var(--ck-bg-panel) !important;
      border-top-color: var(--ck-stroke-1) !important;
    }
    :host-context([data-theme="light"]) .vigie-input-bar textarea {
      border-color: var(--ck-stroke-2) !important;
      background: var(--ck-bg-panel-hi) !important;
      color: var(--ck-fg-1) !important;
    }
    :host-context([data-theme="light"]) .vigie-input-bar textarea:focus {
      border-color: color-mix(in oklab, var(--ck-signal-warn) 45%, transparent) !important;
      box-shadow: 0 0 0 2px color-mix(in oklab, var(--ck-signal-warn) 18%, transparent) !important;
    }
    :host-context([data-theme="light"]) .vigie-mic-button {
      border-color: color-mix(in oklab, var(--ck-signal-warn) 32%, transparent) !important;
      background: var(--ck-bg-panel-hi) !important;
      color: var(--ck-signal-warn) !important;
      box-shadow: none !important;
    }
    :host-context([data-theme="light"]) .vigie-mic-button:hover:not(:disabled) {
      border-color: color-mix(in oklab, var(--ck-signal-pos) 36%, transparent) !important;
      color: var(--ck-signal-pos) !important;
    }
    :host-context([data-theme="light"]) .vigie-send-button {
      border-color: color-mix(in oklab, var(--ck-signal-pos) 40%, transparent) !important;
      background: var(--ck-signal-pos) !important;
      color: var(--ck-on-signal) !important;
      box-shadow: none !important;
    }
    :host-context([data-theme="light"]) .vigie-send-button:hover:not(:disabled) {
      border-color: var(--ck-signal-pos) !important;
      background: color-mix(in oklab, var(--ck-signal-pos) 88%, black) !important;
    }

    /* --- NAWA Studio skin. The PR to PO Studio wraps this panel in
           .xp-studio-portal; inside it the chat drops the cockpit cyan and takes
           the Studio charter (coral accent, sage ok-green, warm charcoal
           surfaces) so the portal reads as one surface with the Studio. The
           .ck-chat-* hooks exist for skins like this one; they carry no style
           of their own. Last in the sheet on purpose: the skin must outrank
           the light-theme remaps at equal specificity. --- */
    :host-context(.xp-studio-portal) .chat-history-shell {
      background: transparent;
    }
    :host-context(.xp-studio-portal) .ck-chat-user-bubble {
      border: 1px solid color-mix(in srgb, #ffffff 16%, transparent);
      background: linear-gradient(
        135deg,
        color-mix(in srgb, var(--nawa-accent, #e8543a) 82%, #ffd9c9),
        var(--nawa-accent, #e8543a)
      );
      color: #1a0b07;
      font-weight: 500;
      padding: 12px 18px;
      font-size: 0.95rem;
      line-height: 1.55;
      box-shadow: 0 14px 34px color-mix(in srgb, var(--nawa-accent, #e8543a) 28%, transparent);
    }
    :host-context(.xp-studio-portal) .ck-chat-assistant-bubble {
      border: 1px solid var(--nawa-line, rgba(245, 242, 239, 0.1));
      background: var(--nawa-surface-2, #1d1d1d);
      color: var(--nawa-fg, #f5f2ef);
      padding: 14px 18px;
      font-size: 0.95rem;
      line-height: 1.65;
      box-shadow: 0 10px 28px rgba(0, 0, 0, 0.35);
    }
    :host-context(.xp-studio-portal) .ck-chat-progress {
      border: 1px solid color-mix(in srgb, var(--nawa-accent, #e8543a) 32%, transparent);
      background:
        radial-gradient(
          140px 60px at 0% 50%,
          color-mix(in srgb, var(--nawa-accent, #e8543a) 14%, transparent),
          transparent 70%
        ),
        var(--nawa-surface-2, #1d1d1d);
      color: var(--nawa-fg, #f5f2ef);
      box-shadow: none;
    }
    :host-context(.xp-studio-portal) .ck-chat-input-bar {
      border-top-color: var(--nawa-line, rgba(245, 242, 239, 0.1));
      background: color-mix(in srgb, var(--nawa-bg, #070707) 72%, transparent);
      padding: 14px 16px;
      gap: 10px;
    }
    :host-context(.xp-studio-portal) .ck-chat-input {
      border-color: var(--nawa-line, rgba(245, 242, 239, 0.12));
      background: var(--nawa-surface-2, #1d1d1d);
      color: var(--nawa-fg, #f5f2ef);
      caret-color: var(--nawa-accent, #e8543a);
      min-height: 52px;
      padding: 14px 16px;
      border-radius: 14px;
      font-size: 0.95rem;
      line-height: 1.5;
      transition: border-color 160ms ease, box-shadow 160ms ease, background 160ms ease;
      /* The 2px Tailwind ring reads harsh on the warm charcoal — swap it for
         a soft coral halo on focus below. */
      --tw-ring-color: transparent;
    }
    :host-context(.xp-studio-portal) .ck-chat-input-bar button:not(.ck-chat-send) {
      min-height: 52px;
      min-width: 48px;
      border-radius: 14px;
    }
    :host-context(.xp-studio-portal) .ck-chat-input::placeholder {
      color: var(--nawa-fg-dim, rgba(245, 242, 239, 0.55));
    }
    :host-context(.xp-studio-portal) .ck-chat-input:focus {
      border-color: color-mix(in srgb, var(--nawa-accent, #e8543a) 55%, transparent);
      background: color-mix(in srgb, var(--nawa-accent, #e8543a) 5%, var(--nawa-surface-2, #1d1d1d));
      box-shadow:
        0 0 0 3px color-mix(in srgb, var(--nawa-accent, #e8543a) 18%, transparent),
        0 12px 30px color-mix(in srgb, var(--nawa-accent, #e8543a) 12%, transparent);
    }
    :host-context(.xp-studio-portal) .ck-chat-send {
      border: 1px solid transparent;
      background: var(--nawa-accent, #e8543a);
      color: #140806;
      font-weight: 600;
      min-height: 52px;
      border-radius: 14px;
      padding-inline: 18px;
      box-shadow: 0 10px 24px color-mix(in srgb, var(--nawa-accent, #e8543a) 35%, transparent);
    }
    :host-context(.xp-studio-portal) .ck-chat-send:hover:not(:disabled) {
      background: color-mix(in srgb, var(--nawa-accent, #e8543a) 86%, #ffffff);
    }
    :host-context(.xp-studio-portal) .ck-chat-empty-mark {
      border-color: color-mix(in srgb, var(--nawa-accent, #e8543a) 30%, transparent);
      background: color-mix(in srgb, var(--nawa-accent, #e8543a) 10%, var(--nawa-surface, #141414));
      box-shadow: 0 0 32px color-mix(in srgb, var(--nawa-accent, #e8543a) 22%, transparent);
    }
    :host-context(.xp-studio-portal) .ck-chat-empty-title {
      color: var(--nawa-fg, #f5f2ef);
    }
    :host-context(.xp-studio-portal) .ck-chat-empty-hint {
      color: var(--nawa-fg-dim, rgba(245, 242, 239, 0.64));
    }
    :host-context(.xp-studio-portal) .ck-chat-trace-summary {
      border-color: color-mix(in srgb, var(--nawa-accent, #e8543a) 22%, transparent);
      background: color-mix(in srgb, var(--nawa-accent, #e8543a) 6%, var(--nawa-surface, #141414));
    }
    :host-context(.xp-studio-portal) ck-thinking-orb {
      border-radius: 999px;
      filter: drop-shadow(0 0 9px color-mix(in srgb, var(--nawa-accent, #e8543a) 45%, transparent));
    }
    :host-context(.xp-studio-portal) .text-cyan-400,
    :host-context(.xp-studio-portal) .text-cyan-300,
    :host-context(.xp-studio-portal) .text-sky-300 {
      color: var(--nawa-accent, #e8543a);
    }
    :host-context(.xp-studio-portal) .text-emerald-400,
    :host-context(.xp-studio-portal) .text-emerald-300 {
      color: var(--nawa-ok, #8fd0a8);
    }
  `],
})
export class ChatPanelComponent implements AfterViewInit {
  /** Screen copy names the product by its brand in this workspace. */
  protected readonly brand = inject(WorkspaceService).brandName;
  @ViewChild('inputEl') private inputEl?: ElementRef<HTMLTextAreaElement>;
  @ViewChild('messagesScroller') private messagesScroller?: ElementRef<HTMLDivElement>;

  /**
   * System id to scope the chat to. Optional since Vague D / D0 — the
   * `/chat` workspace surface mounts this component in *Quick ask* mode
   * with no system selected, in which case the backend falls back to
   * workspace defaults. Audit events still carry the id (or `null`) so
   * downstream analytics can bucket conversations by system.
   */
  readonly systemId = input<string | null>(null);
  readonly resumeSessionId = input<string | null>(null);
  readonly knowledgeScopeOverride = input<string | null>(null);
  readonly adoptionInteraction = output<{step:'question'|'source'|'answer';runId?:string;sessionId?:string}>();
  /**
   * Optional ephemeral Context id (drop-and-ask). When set, the chat
   * automatically attaches the context ids to every outgoing query so
   * the orchestrator knows to ground answers on the dropped documents.
   */
  readonly contextId = input<string | null>(null);
  /** Presentation of the server-created Context; does not grant retrieval access. */
  readonly contextCollection = input<string | null>(null);
  readonly assistantProfileKey = input<string | null>(null);
  readonly initialPrompt = input<string | null>(null);
  readonly autoStartVoiceLoop = input(false);
  /** Hide the conversation rail. Used when the panel sits inside a Studio. */
  readonly compact = input(false);
  /** Open on a blank conversation instead of resuming the last session. A
      Studio portal opens clean every time; send() creates the session lazily. */
  readonly freshSession = input(false);
  /**
   * Per-embed system prompt. A Studio that grounds the model on live facts
   * passes them here so the visible thread carries only the human question —
   * the instructions ride the system role, never a bubble.
   */
  readonly systemPrompt = input<string | null>(null);

  private readonly sse = inject(SseService);
  private readonly api = inject(ApiService);
  private readonly canonicalApi = inject(CanonicalApiService);
  private readonly toast = inject(ToastrService);
  private readonly router = inject(Router);
  private readonly navigation = inject(ZoomContextService);
  private readonly health = inject(RuntimeHealthService);
  private readonly voiceSession = inject(VoiceSessionService);
  private readonly voiceLoopFactory = inject(VoiceLoopControllerFactory);
  private readonly ttsPlaybackFactory = inject(VoiceTtsPlaybackService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly cdr = inject(ChangeDetectorRef);
  private readonly workspace = inject(WorkspaceService);
  private readonly permissions = inject(PermissionsService);
  private readonly assistantEffects = inject(AssistantEffectsService);
  readonly i18n = inject(I18nService);
  readonly settings = inject(SettingsService);

  messages = signal<ChatMessage[]>([]);
  streaming = signal(false);
  streamBuffer = signal('');
  liveSteps = signal<DecisionStep[]>([]);
  liveRetrievalInfo = signal<ChatMessage['retrievalInfo']>(null);
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
  readonly streamProgress = computed<{ label: string; orb: CkOrbState } | null>(() => {
    if (!this.streaming()) return null;
    // Once tokens arrive the bubble renders them — drop the placeholder.
    if (this.streamBuffer().length > 0) return null;

    const steps = this.liveSteps();
    const byType = (t: string): DecisionStep | undefined =>
      [...steps].reverse().find((s) => s.type === t);

    // Synthesis is active but no text has landed yet → the model is writing.
    if (byType('synthesis')) {
      return { label: this.i18n.t('chat.progress.composing'), orb: 'composing' };
    }

    const retrieve = byType('retrieve');
    if (retrieve && (retrieve.status === 'completed' || retrieve.status === 'warning')) {
      const n = this.passagesFound(retrieve);
      let label = this.i18n.t('chat.progress.passages_analysed');
      if (n === 1) label = this.i18n.t('chat.progress.passages_found_one');
      else if (n != null) label = this.i18n.t('chat.progress.passages_found', { count: n });
      return { label, orb: 'solving' };
    }
    if (byType('thought')) {
      return { label: this.i18n.t('chat.progress.analysing'), orb: 'solving' };
    }
    if (retrieve || byType('embedding') || byType('query_analysis')) {
      return { label: this.i18n.t('chat.progress.searching'), orb: 'searching' };
    }
    return { label: this.i18n.t('chat.progress.preparing'), orb: 'working' };
  });
  readonly autoscrollSignature = computed(() => {
    const messages = this.messages();
    const last = messages[messages.length - 1];
    const deep = last?.retrievalInfo;
    return [
      messages.length,
      last?.id ?? '',
      last?.role ?? '',
      last?.content?.length ?? 0,
      this.streaming() ? 'streaming' : 'idle',
      this.streamBuffer().length,
      this.liveSteps().length,
      this.liveRetrievalInfo()?.deepStatus ?? '',
      deep?.deepStatus ?? '',
      deep?.deepProgress ?? '',
      deep?.deepAnswer?.length ?? 0,
      deep?.deepSources?.length ?? 0,
    ].join('|');
  });
  userInput = '';
  private chatSessionId: string | null = null;
  private chatSessionSignature: string | null = null;
  private readonly selectedSessionStorageBaseKey = 'agentium:selected-chat-session-id';
  private readonly chatHistoryStorageKey = 'agentium:chat-history-open';
  private readonly activeDeepRetrievalPolls = new Set<string>();
  private readonly activeHitlMessagePolls = new Set<string>();
  private chatWorkspaceGeneration = 0;
  private chatWorkspaceSubscriptions = new Subscription();
  private readonly chatPollingTimers = new Set<ReturnType<typeof setTimeout>>();
  private chatDestroyed = false;
  creatingChatSession = false;
  readonly chatHistoryOpen = signal(this.readStoredChatHistoryOpen());
  readonly chatSessions = signal<ChatSessionSummary[]>([]);
  readonly chatSessionsLoading = signal(false);
  readonly activeChatSessionId = signal<string | null>(null);
  readonly chatSessionSearch = signal('');
  readonly filteredChatSessions = computed(() => {
    const q = this.chatSessionSearch().trim().toLowerCase();
    const sessions = this.chatSessions();
    if (!q) return sessions;
    return sessions.filter((session) => this.sessionTitle(session).toLowerCase().includes(q));
  });

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
  readonly voiceCaptureMode = signal<VoiceCaptureMode>('normal');
  readonly resolvedVoiceCaptureConfig = computed<ResolvedVoiceCaptureConfig>(() =>
    resolveVoiceCaptureConfig(this.workspaceVoiceLoopConfig(), this.voiceCaptureMode(), {
      silence_ms: 1200,
      dictation_silence_ms: 2000,
      min_speech_ms: 350,
      dictation_min_speech_ms: 300,
      max_turn_ms: 45000,
      rms_threshold: 0.018,
    }),
  );
	  readonly voiceConversationActive = signal(false);
	  readonly voiceConversationPaused = signal(false);
	  readonly voicePartial = signal('');
	  readonly voiceNotice = signal<string | null>(null);
	  readonly voiceOracleStage = signal<VoiceOracleStage>('idle');
	  readonly voiceOracleMessage = signal(this.i18n.t('chat.voice.oracle_batch'));

  // --- Inline expert correction ("Corriger / Compléter") composer state ---
  // Only one composer is open at a time, keyed by the assistant message id.
  readonly correctionOpenFor = signal<string | null>(null);
  readonly correctionText = signal('');
  /** Raw STT output kept verbatim for audit when the correction was dictated. */
  private correctionTranscriptRaw: string | null = null;
  readonly correctionUsedVoice = signal(false);
  readonly correctionMicState = signal<'idle' | 'recording' | 'transcribing' | 'ready'>('idle');
  readonly correctionSubmitting = signal(false);
  private correctionStream: MediaStream | null = null;
  private correctionRecorder: MediaRecorder | null = null;
  private correctionChunks: Blob[] = [];
  /** Last dictation recording, sent (base64) for audit/replay when voice used. */
  private correctionAudioBlob: Blob | null = null;
  /**
   * Best-effort *live* preview shown while the expert dictates. The browser
   * SpeechRecognition engine streams interim words so the user sees text appear
   * in real time; the authoritative transcript still comes from the server
   * `/voice/transcribe` call on stop (French-tuned + persisted for audit).
   */
  readonly correctionLiveTranscript = signal('');
  private correctionSpeech: { stop?: () => void; abort?: () => void; onresult?: unknown; onerror?: unknown; onend?: unknown } | null = null;
  /** Accumulated *final* segments from the live engine, kept as a fallback. */
  private correctionSpeechFinal = '';
  /**
   * Per-message persistent trace of submitted corrections so the expert keeps a
   * visible record in the chat after the composer collapses (keyed by the
   * assistant message id).
   */
  readonly correctionTraces = signal<Record<string, {
    correction: string;
    usedVoice: boolean;
    proposalId: string | null;
    reviewQueueUrl: string | null;
    status: 'published' | 'pending_review';
    at: number;
  }>>({});

  readonly isDemoMode = computed(() => this.workspace.isDemoSafeMode());
  readonly showAdvancedChatControls = computed(() =>
    !this.isDemoMode() && (!this.executiveMode() || this.traceOpen()),
  );
  readonly chatRuntimeLabel = computed(() =>
    this.isDemoMode()
      ? this.i18n.t('chat.controls.runtime_managed')
      : this.settings.settings().defaultModel || '—',
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
  readonly assistantLabel = computed(() => this.activeAssistantProfile()?.label || this.brand());
  readonly workspaceContextLabel = computed(() => {
    const fallback = this.i18n.t('chat.scope.workspace_fallback');
    const name = String(this.workspace.current()?.name || this.workspace.current()?.slug || fallback).trim();
    return name || fallback;
  });
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
  /**
   * Per-workspace toggle for the inline expert-correction CTA. Read from the
   * client-side workspace settings under ``source_policy`` (primary) or
   * ``chat.source_policy`` (fallback). Returns ``null`` when the key is absent
   * client-side — in that case we do not block on it and rely on backend
   * enforcement (the endpoint returns 403 when the feature is disabled).
   */
  readonly expertCorrectionFlag = computed<boolean | null>(() => {
    const settings = this.workspace.current()?.settings;
    const rootPolicy = this.isRecord(settings?.['source_policy'])
      ? (settings!['source_policy'] as Record<string, unknown>)
      : null;
    const chat = this.isRecord(settings?.['chat']) ? (settings!['chat'] as Record<string, unknown>) : null;
    const chatPolicy = chat && this.isRecord(chat['source_policy'])
      ? (chat['source_policy'] as Record<string, unknown>)
      : null;
    for (const policy of [rootPolicy, chatPolicy]) {
      if (policy && 'expert_fiche_correction_enabled' in policy) {
        return policy['expert_fiche_correction_enabled'] === true;
      }
    }
    return null;
  });

  /**
   * Whether the inline "Corriger / Compléter" CTA is available. Gated by:
   *  - the matrix permission ``knowledge_proposal:chat_correct`` which the
   *    backend grants to REVIEW_ROLES (reviewer/admin/owner) — reusing the same
   *    PermissionsService the Knowledge Capture workbench relies on for its own
   *    role gating, and
   *  - the per-workspace ``expert_fiche_correction_enabled`` flag (only when it
   *    is explicitly present client-side; absent -> we do not block on it).
   * The ``expert_knowledge_capture`` capability-active check and the workspace
   * flag are ultimately enforced server-side (the endpoint returns 403 when the
   * feature is disabled), which the submit handler degrades gracefully.
   */
  readonly canCorrectInChat = computed(() => {
    if (this.expertCorrectionFlag() === false) return false;
    return this.permissions.can('knowledge_proposal', 'chat_correct');
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
    if (!this.contextId()) return this.i18n.t('chat.scope.sources', { label });
    if (this.contextCollection()) {
      return this.i18n.t(this.sessionDocsMode() === 'combine' ? 'chat.scope.collection_plus' : 'chat.scope.collection_only', { collection: this.contextCollection()!, source: label });
    }
    if (this.sessionDocsMode() === 'combine') {
      return this.i18n.t('chat.scope.session_plus', { label });
    }
    return this.i18n.t('chat.scope.session_only');
  });
  readonly autoSourceLabel = computed(() => {
    const key = this.profileKnowledgeScope() || this.workspaceDefaultKnowledgeScope();
    return this.scopeLabel(key);
  });
  readonly sourceSelectionLabel = computed(() => {
    const selected = this.selectedSource();
    if (selected === 'auto') {
      return this.profileKnowledgeScope()
        ? this.i18n.t('chat.scope.profile_default')
        : this.i18n.t('chat.controls.source_default');
    }
    if (selected === 'workspace_default') return this.i18n.t('chat.controls.source_default');
    return this.scopeLabel(selected);
  });

  readonly activeSuggestions = computed<SuggestionCard[]>(() => {
    if (this.contextId() && this.contextCollection()) return this.knowledgeSourceSuggestions(this.assistantScopeLabel());
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
    if (this.isDemoMode()) return this.i18n.t('chat.ask.title');
    if (this.executiveMode() || this.activeAssistantProfile()) {
      return this.i18n.t('chat.ask.title_scoped', { name: this.assistantLabel() });
    }
    return this.i18n.t('chat.ask.title_default');
  });
  readonly emptySubtitle = computed(() => {
    if (this.contextId() && this.contextCollection()) return this.i18n.t('chat.ask.subtitle_scope', { source: this.assistantScopeLabel() });
    const configured = this.workspaceChatConfig().subtitle;
    if (configured) return configured;
    if (this.isDemoMode()) {
      return this.i18n.t('chat.ask.subtitle_context', { scope: this.workspaceContextLabel() });
    }
    if (this.executiveMode()) return this.i18n.t('chat.ask.subtitle_executive');
    if (this.contextId() && this.sessionDocsMode() === 'replace') {
      return this.i18n.t('chat.ask.subtitle_session');
    }
    const source = this.scopeLabel(this.activeKnowledgeScope());
    if (this.contextId() && this.sessionDocsMode() === 'combine') {
      return this.i18n.t('chat.ask.subtitle_session_combine', { source });
    }
    if (this.activeKnowledgeScope()) {
      return this.i18n.t('chat.ask.subtitle_scope', { source });
    }
    return this.i18n.t('chat.ask.subtitle_default');
  });
  readonly inputPlaceholder = computed(() => {
    if (this.contextId() && this.contextCollection()) return this.i18n.t('chat.ask.placeholder_scope', { source: this.assistantScopeLabel() });
    const configured = this.workspaceChatConfig().placeholder;
    if (configured) return configured;
    if (this.isDemoMode()) return this.i18n.t('chat.ask.placeholder');
    if (this.executiveMode()) {
      return this.i18n.t('chat.ask.placeholder_scoped', { name: this.assistantLabel() });
    }
    if (this.contextId() && this.sessionDocsMode() === 'replace') {
      return this.i18n.t('chat.ask.placeholder_session');
    }
    const source = this.scopeLabel(this.activeKnowledgeScope());
    if (this.contextId() && this.sessionDocsMode() === 'combine') {
      return this.i18n.t('chat.ask.placeholder_session_combine', { source });
    }
    if (this.activeKnowledgeScope()) {
      return this.i18n.t('chat.ask.placeholder_scope', { source });
    }
    return this.i18n.t('chat.ask.placeholder_default');
  });
  readonly sendLabel = computed(() =>
    this.isDemoMode() || this.executiveMode()
      ? this.i18n.t('chat.input.ask')
      : this.i18n.t('chat.input.send'),
  );
  readonly streamingLabel = computed(() =>
    this.isDemoMode() || this.executiveMode()
      ? this.i18n.t('chat.input.working')
      : this.i18n.t('chat.input.streaming'),
  );

  readonly ragModeHint = computed(() => {
    const slug = this.ragModeOverride();
    const hintKey = this.ragModeChoices.find((m) => m.slug === slug)?.hintKey;
    return hintKey ? this.i18n.t(hintKey) : '';
  });

  readonly ragModeRuntimeStatus = computed(() => {
    const slug = this.ragModeOverride();
    const presetId = RAG_SLUG_TO_PRESET[slug] ?? 'None';
    return this.health.presetStatus(presetId);
  });

  readonly promptTypeHint = computed(() => {
    const slug = this.promptType();
    if (slug === 'auto') return this.i18n.t('chat.controls.reasoning_auto_hint');
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
    if (!runtime) return this.i18n.t('chat.voice.status.unknown');
    const notice = this.voiceNotice();
    if (notice) return notice;
    const status = runtime.status || 'unknown';
    if (status === 'bound') return this.i18n.t('chat.voice.status.ready');
    if (status === 'disabled') return this.i18n.t('chat.voice.status.disabled');
    if (status === 'unconfigured') return this.i18n.t('chat.voice.status.fallback_required');
    if (status === 'experimental') return this.i18n.t('chat.voice.status.experimental');
    return status.replace(/_/g, ' ');
  });

	  readonly voiceStatusClass = computed(() => {
    const status = this.selectedVoiceRuntime()?.status || 'unknown';
    // This badge is rendered by <app-voice-controls>, so a light override
    // written in this component's styles could never reach it. The global
    // .ck-tone-* utilities are theme-aware on their own.
    const base = 'px-2 py-1 rounded ';
    if (this.voiceNotice()) return base + 'ck-tone-info';
    if (status === 'bound') return base + 'ck-tone-ok';
    if (status === 'disabled' || status === 'unconfigured') return base + 'ck-tone-warn';
    if (status === 'experimental') return base + 'ck-tone-info';
	    return base + 'ck-tone-neutral';
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
	        label: this.i18n.t('chat.voice.timeline.listening'),
	        icon: 'mic',
	        detail: this.i18n.t('chat.voice.timeline.listening_detail'),
	        state: mkState(1, 'listening'),
	      },
	      {
	        stage: 'thinking' as VoiceOracleStage,
	        label: this.i18n.t('chat.voice.timeline.thinking'),
	        icon: 'activity',
	        detail: this.i18n.t('chat.voice.timeline.thinking_detail'),
	        state: mkState(2, 'thinking'),
	      },
	      {
	        stage: 'superseded' as VoiceOracleStage,
	        label: this.i18n.t('chat.voice.timeline.refreshed'),
	        icon: 'refresh-cw',
	        detail: this.i18n.t('chat.voice.timeline.refreshed_detail'),
	        state: stage === 'superseded' ? 'active' : currentRank > 2 ? 'done' : 'pending',
	      },
	      {
	        stage: 'fallback' as VoiceOracleStage,
	        label: this.i18n.t('chat.voice.timeline.fallback'),
	        icon: 'route',
	        detail: this.i18n.t('chat.voice.timeline.fallback_detail'),
	        state: stage === 'fallback' ? 'active' : 'pending',
	      },
	      {
	        stage: 'committed' as VoiceOracleStage,
	        label: this.i18n.t('chat.voice.timeline.committed'),
	        icon: 'check-circle-2',
	        detail: this.i18n.t('chat.voice.timeline.committed_detail'),
	        state: mkState(3, 'committed'),
	      },
	    ];
	  });

	  readonly voiceRuntimeDetail = computed(() => {
	    const runtime = this.selectedVoiceRuntime();
	    const caps = runtime?.capabilities ?? {};
    const input = caps['streaming_transcription']
      ? this.i18n.t('chat.voice.detail.stt_streaming')
      : caps['batch_transcription']
        ? this.i18n.t('chat.voice.detail.stt_batch')
        : this.hasCascadeFallback()
          ? this.i18n.t('chat.voice.detail.stt_cascade')
          : this.i18n.t('chat.voice.detail.stt_none');
    const output = caps['tts'] || caps['speech_to_speech']
      ? this.i18n.t('chat.voice.detail.out_native')
      : this.hasCascadeFallback()
        ? this.i18n.t('chat.voice.detail.out_cascade')
        : this.i18n.t('chat.voice.detail.out_none');
	    const transport = this.voiceTransport() === 'backend_ws'
	      ? this.i18n.t('chat.voice.detail.transport_channel')
	      : this.i18n.t('chat.voice.detail.transport_http');
	    const oracle = caps['oracle_injection'] || caps['background_tool_calls']
	      ? this.i18n.t('chat.voice.detail.oracle_tandem')
	      : this.i18n.t('chat.voice.detail.oracle_fallback');
	    if (runtime && this.voiceRuntimeNeedsWebRtc(runtime)) {
	      return this.isDemoMode()
	        ? this.i18n.t('chat.voice.detail.webrtc_demo')
	        : this.i18n.t('chat.voice.detail.webrtc', { runtime: runtime.slug.replace(/_/g, ' ') });
	    }
	    if (this.isDemoMode()) {
	      const mode = this.voiceRuntimeKind(runtime?.slug || this.voiceProvider()).toLowerCase();
	      return `${mode} · ${input} · ${output} · ${transport} · ${oracle}`;
    }
    return `${input} · ${output} · ${transport} · ${oracle}`;
  });

	  readonly voiceTandemOracleHint = computed(() =>
	    this.isDemoMode()
	      ? this.i18n.t('chat.voice.oracle_panel_demo')
	      : this.i18n.t('chat.voice.oracle_panel'),
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
  readonly sourcePreviewPage = signal<number | null>(null);
  readonly sourcePreviewHighlight = signal<string | null>(null);
  readonly deepSearchLaunchingId = signal<string | null>(null);
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
  private chatAutoscrollFrame: number | null = null;
  private voiceLoopRearmTimer: ReturnType<typeof setTimeout> | null = null;
  private voiceLastEndpointReason: VoiceLoopEndpointReason | null = null;
  private appliedVoiceDefaultsSignature = '';
  private loadedVoiceCaptureStorageKey = '';
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
  /** Invalidates every async voice continuation captured before a workspace reset. */
  private voiceWorkspaceGeneration = 0;
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
    const unregisterVoiceWorkspaceReset = this.workspace.registerContextReset(() => {
      this.resetVoiceForWorkspaceChange();
    });
    const unregisterChatWorkspaceReset = this.workspace.registerContextReset((transition) => {
      this.resetChatForWorkspaceChange(transition);
    });
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
      const storageKey = voiceCaptureStorageKey({ surface: 'chat', workspaceSlug, profileKey });
      if (storageKey !== this.loadedVoiceCaptureStorageKey) {
        this.loadedVoiceCaptureStorageKey = storageKey;
        const stored = this.readStoredVoiceCaptureMode(storageKey, normalizeVoiceCaptureMode(config.capture_mode));
        queueMicrotask(() => this.voiceCaptureMode.set(stored));
      }
      const mode = this.voiceCaptureMode();
      const signature = `${workspaceSlug}|${profileKey}|${selectable}|${mode}|${JSON.stringify(config)}`;
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
      void this.autoscrollSignature();
      this.scheduleChatAutoscroll();
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
    // Refresh the IAM matrix so the inline expert-correction CTA can gate on
    // the `chat_correct` permission (capability-active + REVIEW_ROLES).
    this.permissions.refresh().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
    this.health.load().subscribe();
    this.loadReasoningTemplates();
    this.loadVoiceRuntimes();
    queueMicrotask(() => {
      this.loadChatSessions();
    });
    this.destroyRef.onDestroy(() => {
      this.chatDestroyed = true;
      unregisterVoiceWorkspaceReset();
      unregisterChatWorkspaceReset();
      this.cancelChatWorkspaceRequests();
      if (this.chatAutoscrollFrame !== null) {
        window.cancelAnimationFrame(this.chatAutoscrollFrame);
        this.chatAutoscrollFrame = null;
      }
      this.resetVoiceForWorkspaceChange();
      this.voiceLoop.dispose();
      this.ttsPlayback.destroy();
      this.releaseCorrectionRecorder();
    });
  }

  ngAfterViewInit(): void {
    this.focusComposer(120);
    this.scheduleChatAutoscroll();
  }

  private scheduleChatAutoscroll(): void {
    if (this.chatAutoscrollFrame !== null) return;
    this.chatAutoscrollFrame = window.requestAnimationFrame(() => {
      this.chatAutoscrollFrame = null;
      const behavior: ScrollBehavior = this.streaming() ? 'auto' : 'smooth';
      this.scrollMessagesToBottom(behavior);
      window.setTimeout(() => this.scrollMessagesToBottom('auto'), 0);
    });
  }

  private scrollMessagesToBottom(behavior: ScrollBehavior): void {
    const el = this.messagesScroller?.nativeElement;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior });
  }

  loadChatSessions(selectId?: string | null): void {
    const scope = this.workspace.captureRequestScope();
    const generation = this.chatWorkspaceGeneration;
    this.chatSessionsLoading.set(true);
    const subscription = this.api.get<{ sessions?: ChatSessionSummary[] }>(
      '/sessions?status=active&limit=80',
      undefined,
      { workspaceSlug: scope.workspaceSlug },
    ).subscribe({
      next: (payload) => {
        if (!this.isChatContinuationCurrent(scope, generation)) return;
        const sessions = Array.isArray(payload?.sessions) ? payload.sessions : [];
        this.chatSessions.set(sessions);
        this.chatSessionsLoading.set(false);
        const stored = this.loadSelectedSessionId(scope.workspaceSlug);
        // A fresh-session panel never resumes an old conversation on its own;
        // it only follows the session it just created (selectId after send()).
        const target = selectId || this.resumeSessionId() || (this.freshSession() ? null : stored);
        const exists = target && sessions.some((session) => session.id === target);
        if (exists && target) {
          this.openChatSession(target);
        } else if (!this.freshSession() && !this.activeChatSessionId() && sessions.length > 0) {
          this.openChatSession(sessions[0].id);
        }
      },
      error: () => {
        if (!this.isChatContinuationCurrent(scope, generation)) return;
        this.chatSessionsLoading.set(false);
      },
    });
    this.chatWorkspaceSubscriptions.add(subscription);
  }

  createNewChat(): void {
    if (this.creatingChatSession) return;
    const scope = this.workspace.captureRequestScope();
    const generation = this.chatWorkspaceGeneration;
    this.creatingChatSession = true;
    const subscription = this.api.post<ChatSessionSummary>(
      '/sessions',
      { context: this.currentChatSessionContext() },
      { workspaceSlug: scope.workspaceSlug },
    ).subscribe({
      next: (session) => {
        if (!this.isChatContinuationCurrent(scope, generation)) return;
        this.creatingChatSession = false;
        this.chatSessionId = session.id;
        this.chatSessionSignature = this.currentChatSessionSignature();
        this.activeChatSessionId.set(session.id);
        this.storeSelectedSessionId(session.id, scope.workspaceSlug);
        this.messages.set([]);
        this.streamBuffer.set('');
        this.liveSteps.set([]);
        this.liveRetrievalInfo.set(null);
        this.chatSessions.update((sessions) => [session, ...sessions.filter((item) => item.id !== session.id)]);
        this.focusComposer();
      },
      error: () => {
        if (!this.isChatContinuationCurrent(scope, generation)) return;
        this.creatingChatSession = false;
        this.toast.error(this.i18n.t('chat.toast.create_failed'), this.i18n.t('chat.title'));
      },
    });
    this.chatWorkspaceSubscriptions.add(subscription);
  }

  openChatSession(sessionId: string): void {
    if (!sessionId || this.activeChatSessionId() === sessionId) return;
    const scope = this.workspace.captureRequestScope();
    const generation = this.chatWorkspaceGeneration;
    const subscription = this.api.get<ChatSessionDetail>(
      `/sessions/${encodeURIComponent(sessionId)}?include_messages=true&include_jobs=true`,
      undefined,
      { workspaceSlug: scope.workspaceSlug },
    ).subscribe({
      next: (detail) => {
        if (!this.isChatContinuationCurrent(scope, generation)) return;
        this.chatSessionId = detail.id;
        this.chatSessionSignature = this.currentChatSessionSignature();
        this.activeChatSessionId.set(detail.id);
        this.storeSelectedSessionId(detail.id, scope.workspaceSlug);
        const messages = (detail.messages || []).map((message) => this.chatMessageFromStored(message));
        const messageIds = new Set(messages.map((message) => message.id));
        const jobMessages = (detail.jobs || [])
          .map((job) => this.chatMessageFromWorkspaceJob(job))
          .filter((message): message is ChatMessage => !!message && !messageIds.has(message.id));
        this.messages.set([...messages, ...jobMessages]);
        for (const stored of detail.messages || []) {
          const meta = stored.meta_data || {};
          const pendingRunId = typeof meta['run_id'] === 'string' ? meta['run_id'] : '';
          if (
            stored.role === 'assistant'
            && pendingRunId
            && meta['route'] === 'agentic_review'
            && meta['resumed_after_hitl'] !== true
          ) {
            this.startHitlMessagePolling(pendingRunId);
          }
        }
        for (const msg of this.messages()) {
          const jobId = msg.retrievalInfo?.deepJobId;
          const pollUrl = msg.retrievalInfo?.deepPollUrl;
          const info = msg.retrievalInfo;
          if (jobId && info && this.deepRetrievalRunning(info)) {
            this.startDeepRetrievalPolling(msg.id, jobId, pollUrl || null);
          }
        }
        this.focusComposer();
      },
      error: () => {
        if (!this.isChatContinuationCurrent(scope, generation)) return;
        this.toast.error(this.i18n.t('chat.toast.load_failed'), this.i18n.t('chat.title'));
      },
    });
    this.chatWorkspaceSubscriptions.add(subscription);
  }

  archiveChatSession(session: ChatSessionSummary, event?: Event): void {
    event?.stopPropagation();
    const scope = this.workspace.captureRequestScope();
    const generation = this.chatWorkspaceGeneration;
    const subscription = this.api.patch<ChatSessionSummary>(
      `/sessions/${encodeURIComponent(session.id)}`,
      { status: 'archived' },
      { workspaceSlug: scope.workspaceSlug },
    ).subscribe({
      next: () => {
        if (!this.isChatContinuationCurrent(scope, generation)) return;
        this.chatSessions.update((sessions) => sessions.filter((item) => item.id !== session.id));
        if (this.activeChatSessionId() === session.id) this.createNewChat();
      },
      error: () => {
        if (!this.isChatContinuationCurrent(scope, generation)) return;
        this.toast.error(this.i18n.t('chat.toast.archive_failed'), this.i18n.t('chat.title'));
      },
    });
    this.chatWorkspaceSubscriptions.add(subscription);
  }

  deleteChatSession(session: ChatSessionSummary, event?: Event): void {
    event?.stopPropagation();
    const scope = this.workspace.captureRequestScope();
    const generation = this.chatWorkspaceGeneration;
    const subscription = this.api.delete(
      `/sessions/${encodeURIComponent(session.id)}`,
      { workspaceSlug: scope.workspaceSlug },
    ).subscribe({
      next: () => {
        if (!this.isChatContinuationCurrent(scope, generation)) return;
        this.chatSessions.update((sessions) => sessions.filter((item) => item.id !== session.id));
        if (this.activeChatSessionId() === session.id) {
          this.activeChatSessionId.set(null);
          this.chatSessionId = null;
          this.messages.set([]);
        }
      },
      error: () => {
        if (!this.isChatContinuationCurrent(scope, generation)) return;
        this.toast.error(this.i18n.t('chat.toast.delete_failed'), this.i18n.t('chat.title'));
      },
    });
    this.chatWorkspaceSubscriptions.add(subscription);
  }

  sessionTitle(session: ChatSessionSummary): string {
    return (session.title || '').trim() || this.i18n.t('chat.session.untitled');
  }

  sessionSubtitle(session: ChatSessionSummary): string {
    const count = session.message_count ?? 0;
    const when = session.last_activity ? new Date(session.last_activity) : null;
    const date = when && Number.isFinite(when.getTime()) ? when.toLocaleDateString() : '';
    const messages =
      count > 1
        ? this.i18n.t('chat.session.messages', { count })
        : this.i18n.t('chat.session.messages_one', { count });
    return `${messages}${date ? ' · ' + date : ''}`;
  }

  isActiveSession(session: ChatSessionSummary): boolean {
    return this.activeChatSessionId() === session.id;
  }

  toggleChatHistory(): void {
    const next = !this.chatHistoryOpen();
    this.chatHistoryOpen.set(next);
    try {
      globalThis.localStorage?.setItem(this.chatHistoryStorageKey, String(next));
    } catch {
      // The collapse still works for this tab when storage is unavailable.
    }
  }

  private readStoredChatHistoryOpen(): boolean {
    try {
      return globalThis.localStorage?.getItem(this.chatHistoryStorageKey) !== 'false';
    } catch {
      return true;
    }
  }

  private storeSelectedSessionId(
    sessionId: string,
    workspaceSlug = this.workspace.currentSlug(),
  ): void {
    try {
      const key = this.selectedSessionStorageKey(workspaceSlug);
      if (key) window.localStorage.setItem(key, sessionId);
    } catch {
      // Selection restore is nice-to-have only.
    }
  }

  private loadSelectedSessionId(workspaceSlug = this.workspace.currentSlug()): string | null {
    try {
      const key = this.selectedSessionStorageKey(workspaceSlug);
      if (!key) return null;
      const scoped = window.localStorage.getItem(key);
      if (scoped !== null) return scoped;

      // The legacy selection has no workspace provenance. Never attribute it
      // to the merely-current tenant; the scoped session can be selected again.
      const legacy = window.localStorage.getItem(this.selectedSessionStorageBaseKey);
      if (legacy === null) return null;
      window.localStorage.removeItem(this.selectedSessionStorageBaseKey);
      return null;
    } catch {
      return null;
    }
  }

  private selectedSessionStorageKey(slug = this.workspace.currentSlug()): string | null {
    return slug
      ? `${this.selectedSessionStorageBaseKey}:${encodeURIComponent(slug)}`
      : null;
  }

  /**
   * WorkspaceService invokes resetters synchronously under the old scope.
   * Cancel A before B is published, then clear every session-owned signal so
   * neither an old callback nor a transient render can expose A in B.
   */
  private resetChatForWorkspaceChange(transition: WorkspaceContextTransition): void {
    this.chatWorkspaceGeneration += 1;
    this.cancelChatWorkspaceRequests();
    this.activeDeepRetrievalPolls.clear();
    this.activeHitlMessagePolls.clear();
    this.chatSessionId = null;
    this.chatSessionSignature = null;
    this.creatingChatSession = false;
    this.chatSessions.set([]);
    this.chatSessionsLoading.set(false);
    this.activeChatSessionId.set(null);
    this.chatSessionSearch.set('');
    this.messages.set([]);
    this.streaming.set(false);
    this.streamBuffer.set('');
    this.liveSteps.set([]);
    this.liveRetrievalInfo.set(null);
    this.evaluatingId.set(null);
    this.deepSearchLaunchingId.set(null);
    this.userInput = '';

    // The atomic transition has not published B yet while the resetter runs.
    // Rehydrate only once B is visible and only if this panel survived it.
    queueMicrotask(() => {
      if (this.chatDestroyed) return;
      if (this.workspace.currentSlug() !== transition.nextSlug) return;
      if (this.workspace.contextEpoch() !== transition.nextEpoch) return;
      this.loadChatSessions();
    });
  }

  private cancelChatWorkspaceRequests(): void {
    this.chatWorkspaceSubscriptions.unsubscribe();
    this.chatWorkspaceSubscriptions = new Subscription();
    for (const timer of this.chatPollingTimers) clearTimeout(timer);
    this.chatPollingTimers.clear();
  }

  private isChatContinuationCurrent(
    scope: WorkspaceRequestScope,
    generation: number,
  ): boolean {
    return !this.chatDestroyed
      && generation === this.chatWorkspaceGeneration
      && this.workspace.isRequestScopeCurrent(scope);
  }

  private scheduleChatPoll(
    callback: () => void,
    delayMs: number,
    scope: WorkspaceRequestScope,
    generation: number,
  ): void {
    if (!this.isChatContinuationCurrent(scope, generation)) return;
    const timer = setTimeout(() => {
      this.chatPollingTimers.delete(timer);
      if (!this.isChatContinuationCurrent(scope, generation)) return;
      callback();
    }, delayMs);
    this.chatPollingTimers.add(timer);
  }

  private chatMessageFromStored(message: NonNullable<ChatSessionDetail['messages']>[number]): ChatMessage {
    const meta = message.meta_data || {};
    const sources = Array.isArray(meta['sources']) ? (meta['sources'] as Source[]) : undefined;
    const decisionSteps = Array.isArray(meta['decision_steps']) ? (meta['decision_steps'] as DecisionStep[]) : undefined;
    const deepJobId = (meta['deep_job_id'] as string | undefined) || (meta['workspace_job_id'] as string | undefined) || null;
    const deepSummary = this.parseDeepSummaryMeta(meta['deep_summary']);
    const deepSources = Array.isArray(meta['deep_sources']) ? (meta['deep_sources'] as Source[]) : undefined;
    const metaMetrics = this.isRecord(meta['retrieval_metrics'])
      ? (meta['retrieval_metrics'] as Record<string, unknown>)
      : {};
    const decisionTrace =
      this.parseRetrievalDecisionTrace(meta['retrieval_decision_trace'])
      ?? this.parseRetrievalDecisionTrace(metaMetrics['retrieval_decision_trace'])
      ?? this.parseRetrievalDecisionTrace(deepSummary && this.isRecord(meta['deep_summary'])
        ? (meta['deep_summary'] as Record<string, unknown>)['retrieval_decision_trace']
        : null);
    const hasRetrievalInfo = !!(
      deepJobId
      || decisionTrace
      || meta['dense_policy']
      || meta['retrieval_scope']
      || meta['latency_profile']
      || metaMetrics['dense_policy']
    );
    // The backend persists the expert-correction acknowledgement as a regular
    // assistant message tagged ``kind: "expert_correction_ack"`` so the sober
    // bubble (and its missing action row) survives a reload.
    const kind = meta['kind'] === 'expert_correction_ack' ? 'correction_ack' as const : undefined;
    return {
      id: message.id,
      role: message.role,
      content: message.content,
      kind,
      decisionSteps,
      sources,
      feedback: null,
      evaluation: null,
      runId: (meta['run_id'] as string | undefined) || null,
      retrievalInfo: hasRetrievalInfo
        ? {
            densePolicy: (meta['dense_policy'] as string | undefined) || (metaMetrics['dense_policy'] as string | undefined) || null,
            fallbackReason:
              (meta['fallback_reason'] as string | undefined)
              || (metaMetrics['fallback_reason'] as string | undefined)
              || null,
            sparseStatus: (meta['sparse_status'] as string | undefined) || (metaMetrics['sparse_status'] as string | undefined) || null,
            retrievalScope: this.isRecord(meta['retrieval_scope'])
              ? (meta['retrieval_scope'] as Record<string, unknown>)
              : this.isRecord(metaMetrics['retrieval_scope'])
                ? (metaMetrics['retrieval_scope'] as Record<string, unknown>)
                : null,
            retrievalPlan: this.isRecord(meta['retrieval_plan'])
              ? (meta['retrieval_plan'] as Record<string, unknown>)
              : this.isRecord(metaMetrics['retrieval_plan'])
                ? (metaMetrics['retrieval_plan'] as Record<string, unknown>)
                : null,
            scopeReason: (meta['scope_reason'] as string | undefined) || (metaMetrics['scope_reason'] as string | undefined) || null,
            scopeConfidence: typeof meta['scope_confidence'] === 'number'
              ? (meta['scope_confidence'] as number)
              : typeof metaMetrics['scope_confidence'] === 'number'
                ? (metaMetrics['scope_confidence'] as number)
                : null,
            latencyProfile:
              (meta['latency_profile'] as string | undefined)
              || (metaMetrics['latency_profile'] as string | undefined)
              || null,
            latencyBudget: this.parseLatencyBudget(meta['latency_budget'] ?? metaMetrics['latency_budget']),
            stageTimings: this.parseNumberRecord(metaMetrics['stage_timings']),
            candidateCounts: this.parseNumberRecord(metaMetrics['candidate_counts']),
            decisionTrace,
            deepJobId,
            deepPollUrl: deepJobId ? ((meta['deep_poll_url'] as string | undefined) || `/workspace-jobs/${deepJobId}`) : null,
            deepStatus: (meta['deep_status'] as string | undefined) || 'queued',
            deepProgress: typeof meta['deep_progress'] === 'number' ? (meta['deep_progress'] as number) : null,
            deepStage: (meta['deep_stage'] as string | undefined) || null,
            deepParentMessageId: (meta['parent_message_id'] as string | undefined) || null,
            deepAnswer: (meta['deep_answer'] as string | undefined) || null,
            deepAnswerStatus: (meta['deep_answer_status'] as string | undefined) || null,
            deepAnswerModel: (meta['deep_answer_model'] as string | undefined) || null,
            deepSummary,
            deepSources,
          }
        : null,
    };
  }

  private chatMessageFromWorkspaceJob(raw: unknown): ChatMessage | null {
    if (!this.isRecord(raw)) return null;
    const jobId = typeof raw['id'] === 'string' ? (raw['id'] as string) : '';
    if (!jobId) return null;
    const result = this.isRecord(raw['result']) ? (raw['result'] as Record<string, unknown>) : {};
    const inputRef = this.isRecord(raw['input_ref']) ? (raw['input_ref'] as Record<string, unknown>) : {};
    const request = this.isRecord(inputRef['request']) ? (inputRef['request'] as Record<string, unknown>) : {};
    const query = typeof request['query'] === 'string' ? (request['query'] as string) : 'Deep Search';
    const answer = typeof result['answer'] === 'string' && result['answer'].trim()
      ? (result['answer'] as string).trim()
      : this.i18n.t(
          raw['status'] === 'completed' ? 'chat.deep_search.done_for' : 'chat.deep_search.running_for',
          { query },
        );
    const pollUrl = typeof raw['poll_url'] === 'string' ? (raw['poll_url'] as string) : `/workspace-jobs/${jobId}`;
    return {
      id: typeof raw['message_id'] === 'string' && raw['message_id'] ? (raw['message_id'] as string) : `job:${jobId}`,
      role: 'assistant',
      content: answer,
      sources: this.deepSourcesFromJob(raw),
      feedback: null,
      evaluation: null,
      retrievalInfo: {
        deepJobId: jobId,
        deepPollUrl: pollUrl,
        deepStatus: typeof raw['status'] === 'string' ? (raw['status'] as string) : 'queued',
        deepProgress: typeof raw['progress'] === 'number' ? (raw['progress'] as number) : 0,
        deepStage: typeof raw['stage'] === 'string' ? (raw['stage'] as string) : null,
        deepParentMessageId: typeof raw['parent_message_id'] === 'string' ? (raw['parent_message_id'] as string) : null,
        deepSummary: this.parseDeepSummaryFromJob(raw),
        decisionTrace:
          this.parseRetrievalDecisionTrace(result['retrieval_decision_trace'])
          ?? this.parseRetrievalDecisionTrace(this.isRecord(result['summary'])
            ? (result['summary'] as Record<string, unknown>)['retrieval_decision_trace']
            : null),
        deepSources: this.deepSourcesFromJob(raw),
        deepAnswer: answer,
        deepAnswerStatus: typeof result['answer_status'] === 'string' ? (result['answer_status'] as string) : null,
        deepAnswerModel: typeof result['answer_model'] === 'string' ? (result['answer_model'] as string) : null,
      },
    };
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
    const capture = this.resolvedVoiceCaptureConfig();
    const mode = config.default_mode || (config.enabled_default ? 'session_loop' : 'batch');
    if (mode === 'session_loop' && canUseSession) {
      this.voiceTransport.set('backend_ws');
    } else {
      this.voiceTransport.set('batch_http');
    }
    if (typeof config.auto_send_final_transcript === 'boolean') {
      this.voiceAutoSend.set(config.auto_send_final_transcript);
    }
    this.voiceAutoEndpoint.set(capture.auto_endpoint);
    this.cdr.markForCheck();
  }

  executiveVoiceCtaLabel(): string {
    if (!this.canUseVoiceSession()) return this.i18n.t('chat.voice.unavailable');
    if (this.voiceConversationPaused()) return this.i18n.t('chat.voice.resume_aya');
    if (this.voiceConversationActive()) return this.i18n.t('chat.voice.aya_listening');
    return this.i18n.t('chat.voice.talk_to_aya');
  }

  executiveVoiceCtaTitle(): string {
    if (!this.canUseVoiceSession()) return this.voiceSessionButtonTitle();
    if (this.voiceConversationPaused()) return this.i18n.t('chat.voice.resume_aya_title');
    if (this.voiceConversationActive()) return this.i18n.t('chat.voice.aya_active_title');
    return this.i18n.t('chat.voice.talk_to_aya_title');
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
	      if (webRtcRequired) return this.i18n.t('chat.voice.title_webrtc_required', { label });
	      if (runtime.status === 'bound') return label;
	      if (runtime.status === 'disabled') return this.i18n.t('chat.voice.title_unavailable', { label });
	      if (runtime.status === 'unconfigured') return this.i18n.t('chat.voice.title_not_configured', { label });
      if (runtime.status === 'experimental') return this.i18n.t('chat.voice.title_experimental', { label });
      return label;
	    }
	    const label = runtime.slug.replace(/_/g, ' ');
	    if (webRtcRequired) return this.i18n.t('chat.voice.title_webrtc_not_wired', { label });
	    if (runtime.status === 'bound') return label;
	    return `${label} · ${runtime.status}`;
	  }

	  selectedVoiceDescription(): string {
	    const runtime = this.selectedVoiceRuntime();
	    if (runtime && this.voiceRuntimeNeedsWebRtc(runtime)) {
	      return this.isDemoMode()
	        ? this.i18n.t('chat.voice.realtime_requires_webrtc')
	        : this.i18n.t('chat.voice.runtime_requires_webrtc', {
	            runtime: runtime.slug.replace(/_/g, ' '),
	          });
	    }
	    if (this.isDemoMode()) {
	      return this.i18n.t('chat.voice.runtime_demo_hint', {
	        kind: this.voiceRuntimeKind(this.voiceProvider()),
	      });
	    }
	    return runtime?.description || this.voiceRuntimeDetail();
	  }

	  onVoiceProviderChange(slug: string): void {
	    const runtime = this.voiceRuntimeOptions().find((item) => item.slug === slug);
	    if (runtime && !this.isVoiceRuntimeSelectableInChat(runtime)) {
	      this.toast.info(this.i18n.t('chat.voice.realtime_toast'), this.i18n.t('chat.voice.title'));
	      return;
	    }
	    this.voiceProvider.set(slug || 'cascade_openai');
	    this.voicePartial.set('');
	    this.voiceNotice.set(null);
	    this.voiceOracleStage.set('idle');
	    this.voiceOracleMessage.set(this.i18n.t('chat.voice.oracle_batch'));
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
	      this.voiceOracleMessage.set(this.i18n.t('chat.voice.oracle_batch'));
	    } else {
	      this.voiceOracleStage.set('idle');
	      this.voiceOracleMessage.set(this.i18n.t('chat.voice.oracle_session'));
	    }
	  }

	  isVoiceRuntimeSelectableInChat(runtime: VoiceRuntimeProviderOption): boolean {
	    return !this.voiceRuntimeNeedsWebRtc(runtime);
	  }

	  private voiceRuntimeNeedsWebRtc(runtime: VoiceRuntimeProviderOption): boolean {
	    return String(runtime.transport || '').toLowerCase() === 'webrtc';
	  }

	  voiceTransportHint(): string {
	    return this.i18n.t('chat.voice.transport_hint');
	  }

	  voiceSessionButtonTitle(): string {
	    const runtime = this.selectedVoiceRuntime();
	    if (runtime && this.voiceRuntimeNeedsWebRtc(runtime)) {
	      return this.i18n.t('chat.voice.realtime_webrtc_not_wired');
	    }
	    if (!this.canUseVoiceSession()) return this.i18n.t('chat.voice.session_path_unavailable');
	    return this.i18n.t('chat.voice.session_button_hint');
	  }

	  voiceRealtimeBlockedHint(): string | null {
	    const runtime = this.selectedVoiceRuntime();
	    if (!runtime || !this.voiceRuntimeNeedsWebRtc(runtime)) return null;
	    return this.isDemoMode()
	      ? this.i18n.t('chat.voice.realtime_webrtc_uses_brand')
	      : this.i18n.t('chat.voice.runtime_requires_webrtc', {
	          runtime: runtime.slug.replace(/_/g, ' '),
	        });
	  }

	  voiceOraclePanelHint(): string {
	    return this.i18n.t('chat.voice.tandem_hint');
	  }

  voiceMicTitle(): string {
    if (this.voiceConversationActive()) {
      if (this.voiceConversationPaused()) return this.i18n.t('chat.voice.loop_paused_title');
      return this.i18n.t('chat.voice.stop_no_rearm_title');
    }
    if (!this.canTranscribeVoice() && !this.voiceStopAvailable())
      return this.isDemoMode()
        ? this.i18n.t('chat.voice.mic_cannot_demo')
        : this.i18n.t('chat.voice.mic_cannot');
    if (this.ttsSpeaking()) return this.i18n.t('chat.voice.cut_playback_title');
    if (this.transcribing())
      return this.isDemoMode()
        ? this.i18n.t('chat.voice.transcribing')
        : this.i18n.t('chat.voice.transcribing_with', { provider: this.voiceInputProvider() });
    if (this.recording()) {
      return this.voiceAutoEndpoint() && this.voiceTransport() === 'backend_ws'
        ? this.i18n.t('chat.voice.mic_listening')
        : this.i18n.t('chat.voice.mic_stop');
    }
    const mode = this.voiceTransport() === 'backend_ws'
      ? this.i18n.t('chat.voice.mode_session')
      : this.i18n.t('chat.voice.mode_batch');
    if (this.isDemoMode()) return this.i18n.t('chat.voice.mic_record', { mode });
    return this.i18n.t('chat.voice.mic_record_provider', {
      provider: this.voiceInputProvider(),
      mode,
    });
  }

  private voiceRuntimeNotice(label: string, provider?: string | null): string {
    if (this.isDemoMode()) return label;
    return provider ? `${label} · ${provider}` : label;
  }

  private voiceRuntimeKind(slug: string): string {
    const normalized = (slug || '').toLowerCase();
    if (normalized === 'cascade' || normalized === 'cascade_openai') return this.i18n.t('chat.voice.kind.cascade');
    if (normalized.includes('realtime') || normalized === 'realtime_gpu') return this.i18n.t('chat.voice.kind.realtime');
    if (normalized.includes('stt')) return this.i18n.t('chat.voice.kind.stt');
    if (normalized.includes('tts')) return this.i18n.t('chat.voice.kind.tts');
    return this.i18n.t('chat.voice.kind.generic');
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
   * Operator-facing tooltip for a metric, resolved from the i18n dictionary
   * (``chat.metrics.desc.<key>``). Unknown metrics get an empty tooltip,
   * mirroring the old ``DEFAULT_METRIC_SPEC.description`` behaviour.
   */
  metricDescription(key: string): string {
    const dictKey = `chat.metrics.desc.${key}`;
    const label = this.i18n.t(dictKey);
    return label === dictKey ? '' : label;
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
    if (buckets.good) parts.push(this.i18n.t('chat.metrics.good', { count: buckets.good }));
    if (buckets.fair) parts.push(this.i18n.t('chat.metrics.fair', { count: buckets.fair }));
    if (buckets.poor) parts.push(this.i18n.t('chat.metrics.poor', { count: buckets.poor }));
    if (buckets.null) parts.push(this.i18n.t('chat.metrics.none', { count: buckets.null }));
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
   * ``sources`` panel. Supports stacked refs like ``[1][2][3]``, the
   * ``[1, 2]`` form, and source-label refs like ``[menu.html]`` when the
   * label can be matched to a returned source.
   */
  renderAnswer(content: string | undefined | null, sources?: Source[] | null): AnswerToken[] {
    if (!content) return [{ kind: 'text', value: this.i18n.t('chat.answer.empty') }];
    const tokens: AnswerToken[] = [];
    const re = /\[([^\]\n]{1,180})\]/g;
    let last = 0;
    for (const m of content.matchAll(re)) {
      const idx = m.index ?? 0;
      if (idx > last) {
        tokens.push({ kind: 'text', value: content.slice(last, idx) });
      }
      const label = m[1].trim();
      const expanded = this.expandBracketCitation(label, sources);
      if (expanded.length === 1 && expanded[0].kind === 'text' && expanded[0].value === `[${label}]`) {
        tokens.push({ kind: 'text', value: m[0] });
      } else {
        tokens.push(...expanded);
      }
      last = idx + m[0].length;
    }
    if (last < content.length) {
      tokens.push({ kind: 'text', value: content.slice(last) });
    }
    return tokens.length ? tokens : [{ kind: 'text', value: content }];
  }

  renderMarkdownAnswer(content: string | undefined | null, sources?: Source[] | null): AnswerBlock[] {
    const text = this.normalizeAnswerMarkdown(content || this.i18n.t('chat.answer.empty')).replace(/\r\n?/g, '\n');
    const lines = text.split('\n');
    const blocks: AnswerBlock[] = [];
    let paragraph: string[] = [];
    let bulletBuffer: Array<{ level: number; ordered: boolean; tokens: AnswerToken[] }> = [];
    let codeLines: string[] = [];
    let inCode = false;

    const flushParagraph = () => {
      const value = paragraph.join('\n').trim();
      if (value) blocks.push({ kind: 'paragraph', tokens: this.inlineMarkdownTokens(value, sources) });
      paragraph = [];
    };
    const flushList = () => {
      if (bulletBuffer.length) {
        blocks.push({
          kind: 'list',
          ordered: bulletBuffer[0].ordered,
          items: this.buildAnswerListTree(bulletBuffer),
        });
      }
      bulletBuffer = [];
    };

    for (const rawLine of lines) {
      const line = rawLine.replace(/\s+$/g, '');
      if (/^\s*```/.test(line)) {
        if (inCode) {
          blocks.push({ kind: 'codeblock', value: codeLines.join('\n') });
          codeLines = [];
          inCode = false;
        } else {
          flushParagraph();
          flushList();
          inCode = true;
        }
        continue;
      }
      if (inCode) {
        codeLines.push(rawLine);
        continue;
      }
      if (!line.trim()) {
        flushParagraph();
        flushList();
        continue;
      }
      const heading = /^(#{1,4})\s+(.+)$/.exec(line);
      if (heading) {
        flushParagraph();
        flushList();
        const level = Math.min(4, Math.max(2, heading[1].length + 1)) as 2 | 3 | 4;
        blocks.push({ kind: 'heading', level, tokens: this.inlineMarkdownTokens(heading[2], sources) });
        continue;
      }
      const bullet = this.parseAnswerBulletLine(line);
      if (bullet) {
        flushParagraph();
        bulletBuffer.push({
          level: bullet.level,
          ordered: bullet.ordered,
          tokens: this.inlineMarkdownTokens(bullet.content, sources),
        });
        continue;
      }
      flushList();
      paragraph.push(line);
    }
    if (inCode) {
      blocks.push({ kind: 'codeblock', value: codeLines.join('\n') });
    }
    flushParagraph();
    flushList();
    return blocks.length ? blocks : [{ kind: 'paragraph', tokens: [{ kind: 'text', value: this.i18n.t('chat.answer.empty') }] }];
  }

  /**
   * Parse a markdown list line into its indent level, ordered flag and inline
   * content. Leading whitespace (two spaces / one tab per level) drives the
   * nesting depth so sub-bullets are not collapsed into siblings.
   */
  private parseAnswerBulletLine(
    line: string,
  ): { level: number; ordered: boolean; content: string } | null {
    const match = /^([\t ]*)([-*•]|\d+[.)])\s+(.+)$/.exec(line);
    if (!match) return null;
    const indent = match[1].replace(/\t/g, '  ').length;
    return { level: Math.floor(indent / 2), ordered: /\d/.test(match[2]), content: match[3] };
  }

  /**
   * Turn a flat, indent-tagged bullet list into a nested tree using a level
   * stack. Orderedness is kept per node so nested groups can mix bullets and
   * numbers. Mirrors the parser used by the knowledge-capture fiche.
   */
  private buildAnswerListTree(
    flat: Array<{ level: number; ordered: boolean; tokens: AnswerToken[] }>,
  ): AnswerListItem[] {
    const root: AnswerListItem[] = [];
    const stack: Array<{ level: number; item: AnswerListItem }> = [];
    for (const entry of flat) {
      const node: AnswerListItem = { tokens: entry.tokens, ordered: entry.ordered, children: [] };
      while (stack.length && stack[stack.length - 1].level >= entry.level) stack.pop();
      if (!stack.length) root.push(node);
      else stack[stack.length - 1].item.children.push(node);
      stack.push({ level: entry.level, item: node });
    }
    return root;
  }

  private normalizeAnswerMarkdown(content: string): string {
    const text = String(content || '').trim();
    if (!text) return text;
    if (/\n\s*([-*•]|\d+[\.)])\s+/.test(text)) return text;
    const inlineBulletPattern = /\s-\s+(?=[A-ZÀ-ÖØ-Þ0-9"“])/g;
    const matches = text.match(inlineBulletPattern) || [];
    if (matches.length < 2 && !/:\s-\s+(?=[A-ZÀ-ÖØ-Þ0-9"“])/.test(text)) return text;
    return text
      .replace(inlineBulletPattern, '\n- ')
      .replace(/\s+(Source\s*:)/i, '\n\n$1')
      .replace(/\n{3,}/g, '\n\n');
  }

  showDeepAnswerInDetails(
    msg: ChatMessage,
    info: NonNullable<ChatMessage['retrievalInfo']>,
  ): boolean {
    const answer = info.deepAnswer?.trim();
    if (!answer) return false;
    const normalizedMessage = this.normalizeAnswerMarkdown(msg.content || '').replace(/\s+/g, ' ').trim();
    const normalizedAnswer = this.normalizeAnswerMarkdown(answer).replace(/\s+/g, ' ').trim();
    return !!normalizedAnswer && normalizedMessage !== normalizedAnswer;
  }

  private inlineMarkdownTokens(value: string, sources?: Source[] | null): AnswerToken[] {
    const tokens: AnswerToken[] = [];
    const re =
      /(\[([^\]\n]+)\]\(((?:https?:\/\/|\/)[^) \t]+)\))|(\[(\d+(?:\s*,\s*\d+)*)\])|(\[([^\]\n]{1,180})\])|(\*\*([^*]+)\*\*)|(__([^_]+)__)|(`([^`]+)`)|(\*([^*]+)\*)|(_([^_]+)_)/g;
    let last = 0;
    for (const match of value.matchAll(re)) {
      const index = match.index ?? 0;
      if (index > last) {
        tokens.push({ kind: 'text', value: value.slice(last, index) });
      }
      if (match[2] && match[3]) {
        tokens.push({ kind: 'link', value: match[2], href: match[3] });
      } else if (match[5] || match[7]) {
        const label = (match[5] || match[7] || '').trim();
        const expanded = this.expandBracketCitation(label, sources);
        if (expanded.length === 1 && expanded[0].kind === 'text' && expanded[0].value === `[${label}]`) {
          tokens.push({ kind: 'text', value: match[0] });
        } else {
          tokens.push(...expanded);
        }
      } else if (match[9] || match[11]) {
        tokens.push({ kind: 'strong', value: match[9] ?? match[11] ?? '' });
      } else if (match[13]) {
        tokens.push({ kind: 'code', value: match[13] });
      } else if (match[15] || match[17]) {
        tokens.push({ kind: 'em', value: match[15] ?? match[17] ?? '' });
      }
      last = index + match[0].length;
    }
    if (last < value.length) {
      tokens.push({ kind: 'text', value: value.slice(last) });
    }
    return tokens.length ? tokens : [{ kind: 'text', value }];
  }

  safeMarkdownHref(href: string): string {
    const value = String(href || '').trim();
    return /^(https?:\/\/|\/)/i.test(value) ? value : '#';
  }

  /** DOM id we attach to each source ``<li>`` so chips can scroll to it. */
  sourceDomId(msgId: string, n: number): string {
    return `msg-${msgId}-src-${n}`;
  }

  deepSourceHostId(msg: ChatMessage): string {
    return `${msg.id}-deep`;
  }

  /** Whether a citation ``[n]`` resolves to a real entry in ``msg.sources``. */
  isValidCitation(msg: ChatMessage, n: number): boolean {
    return this.isValidCitationForSources(msg.sources, n);
  }

  isValidCitationForSources(sources: Source[] | undefined | null, n: number): boolean {
    return !!sources && n >= 1 && n <= sources.length;
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
    for (const tok of this.renderAnswer(msg.content, msg.sources)) {
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
    const key = `${msg.id}:${(msg.content ?? '').length}:${this.sourceSignature(msg.sources)}`;
    const cached = this.citedIndicesCache.get(key);
    if (cached) return cached;
    const set = this.citedIndicesForContent(msg.content, msg.sources);
    this.citedIndicesCache.set(key, set);
    return set;
  }

  isSourceCited(msg: ChatMessage, index1Based: number): boolean {
    return this.citedIndices(msg).has(index1Based);
  }

  isSourceCitedForContent(content: string | undefined | null, sources: Source[] | undefined | null, index1Based: number): boolean {
    return this.citedIndicesForContent(content, sources).has(index1Based);
  }

  private citedIndicesForContent(content: string | undefined | null, sources?: Source[] | null): Set<number> {
    const set = new Set<number>();
    for (const tok of this.renderAnswer(content, sources)) {
      if (tok.kind === 'cite') set.add(tok.n);
    }
    return set;
  }

  /** Short preview shown in a chip's native ``title`` tooltip on hover. */
  citationTooltip(msg: ChatMessage, n: number): string {
    return this.citationTooltipForSources(msg.sources, n);
  }

  citationTooltipForSources(sources: Source[] | undefined | null, n: number): string {
    const src = sources?.[n - 1];
    if (!src) return this.i18n.t('chat.citation.missing', { n });
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
    this.gotoSourceTarget(msg, n, msg.id, true);
  }

  gotoSourceTarget(msg: ChatMessage, n: number, sourceHostId: string, openDirectSources: boolean): void {
    const sources = sourceHostId === this.deepSourceHostId(msg)
      ? (msg.retrievalInfo?.deepSources?.length ? msg.retrievalInfo.deepSources : msg.sources)
      : msg.sources;
    if (!this.isValidCitationForSources(sources, n)) return;
    this.adoptionInteraction.emit({step:'source'});
    if (openDirectSources && !this.isSourcesOpen(msg.id)) this.toggleSources(msg.id);
    setTimeout(() => {
      const el = document.getElementById(this.sourceDomId(sourceHostId, n));
      if (!el) return;
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el.classList.add('ring-cyan-400', 'ring-2');
      setTimeout(() => el.classList.remove('ring-cyan-400', 'ring-2'), 1600);
    }, 50);
  }

  /**
   * Turn bracket content into cite chips. Supports ``[1, 2]``, stacked numeric
   * refs, and comma-separated document labels such as
   * ``[TTN21546J, TTN20951J]``.
   */
  private expandBracketCitation(label: string, sources?: Source[] | null): AnswerToken[] {
    const trimmed = label.trim();
    if (!trimmed) return [{ kind: 'text', value: '[]' }];

    if (/^\d+(?:\s*,\s*\d+)*$/.test(trimmed)) {
      const tokens: AnswerToken[] = [];
      for (const part of trimmed.split(',')) {
        const n = parseInt(part.trim(), 10);
        if (Number.isFinite(n) && n > 0) tokens.push({ kind: 'cite', n });
      }
      return tokens.length ? tokens : [{ kind: 'text', value: `[${trimmed}]` }];
    }

    const parts = trimmed.split(',').map((part) => part.trim()).filter(Boolean);
    if (parts.length > 1) {
      const tokens = parts.flatMap((part) => this.expandSingleBracketCitation(part, sources, false));
      if (!tokens.length) return [{ kind: 'text', value: `[${trimmed}]` }];
      if (tokens.every((token) => token.kind === 'text')) {
        return [{ kind: 'text', value: `[${trimmed}]` }];
      }
      return tokens;
    }

    return this.expandSingleBracketCitation(trimmed, sources, true);
  }

  private expandSingleBracketCitation(
    part: string,
    sources?: Source[] | null,
    bracketFallback = true,
  ): AnswerToken[] {
    const trimmed = part.trim();
    if (!trimmed) return [];
    if (this.isWildcardSourceReference(trimmed)) {
      return [{ kind: 'text', value: trimmed }];
    }
    const n = this.resolveSourceReferenceIndex(trimmed, sources);
    if (n) return [{ kind: 'cite', n, label: trimmed }];
    return bracketFallback ? [{ kind: 'text', value: `[${trimmed}]` }] : [{ kind: 'text', value: trimmed }];
  }

  private isWildcardSourceReference(value: string): boolean {
    return /[*?]/.test(value) || /x{2,}/i.test(value);
  }

  private isAndritzProjectCode(value: string): boolean {
    return /^[A-Z]{3}\d{2,4}[A-Z]{0,2}$/i.test(value.trim());
  }

  private andritzProjectCodePrefixMatch(target: string, candidateNorm: string): boolean {
    if (!target || !candidateNorm) return false;
    return (
      candidateNorm === target ||
      candidateNorm.startsWith(`${target} `) ||
      candidateNorm.startsWith(`${target}.`) ||
      candidateNorm.startsWith(`${target}_`) ||
      candidateNorm.startsWith(`${target}-`)
    );
  }

  private resolveSourceReferenceIndex(label: string, sources?: Source[] | null): number | null {
    if (!sources?.length) return null;
    const target = this.normalizeSourceReference(label);
    if (!target || /^[\d,\s]+$/.test(target)) return null;
    const targetBase = this.normalizeSourceReference(this.basenameSourceReference(label));
    const targetStem = this.stripSourceExtension(targetBase);
    const allowLooseMatch = target.length >= 10 && /[\s._/-]/.test(label);
    const andritzCode = this.isAndritzProjectCode(label);
    let looseMatch: number | null = null;

    for (let i = 0; i < sources.length; i += 1) {
      for (const candidate of this.sourceReferenceCandidates(sources[i])) {
        const candidateNorm = this.normalizeSourceReference(candidate);
        if (!candidateNorm) continue;
        const candidateBase = this.normalizeSourceReference(this.basenameSourceReference(candidate));
        const candidateStem = this.stripSourceExtension(candidateBase);
        const exact =
          target === candidateNorm ||
          target === candidateBase ||
          targetBase === candidateNorm ||
          targetBase === candidateBase ||
          (!!targetStem && targetStem.length >= 4 && targetStem === candidateStem);
        if (exact) return i + 1;
        if (andritzCode && this.andritzProjectCodePrefixMatch(target, candidateNorm)) return i + 1;
        if (
          looseMatch == null &&
          allowLooseMatch &&
          ((target.length >= 6 && candidateNorm.includes(target)) ||
            (candidateNorm.length >= 6 && target.includes(candidateNorm)))
        ) {
          looseMatch = i + 1;
        }
      }
    }
    return looseMatch;
  }

  private sourceReferenceCandidates(src: Source): string[] {
    const meta = (src.metadata ?? {}) as Record<string, unknown>;
    const values: string[] = [];
    const add = (value: unknown) => {
      if (typeof value !== 'string') return;
      const trimmed = value.trim();
      if (!trimmed) return;
      values.push(trimmed);
      const basename = this.basenameSourceReference(trimmed);
      if (basename && basename !== trimmed) values.push(basename);
    };
    add(src.title);
    add(src.filename);
    add(src.document_id);
    add(src.id);
    add(src.url);
    add(src['project_code']);
    for (const key of [
      'title',
      'filename',
      'document_filename',
      'document_title',
      'source_filename',
      'source_path',
      'file_path',
      'path',
      'name',
      'citation_label',
      'project_code',
      'url',
    ]) {
      add(meta[key]);
    }
    return Array.from(new Set(values));
  }

  private normalizeSourceReference(value: string): string {
    return String(value || '')
      .normalize('NFKD')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/[’‘]/g, "'")
      .replace(/[“”]/g, '"')
      .replace(/^source\s*:\s*/i, '')
      .replace(/^["'`]+|["'`]+$/g, '')
      .replace(/\s+/g, ' ')
      .trim()
      .toLowerCase();
  }

  private basenameSourceReference(value: string): string {
    const clean = String(value || '').split(/[?#]/, 1)[0].replace(/\\/g, '/');
    return clean.split('/').pop() || clean;
  }

  private stripSourceExtension(value: string): string {
    return value.replace(/\.[a-z0-9]{1,8}$/i, '');
  }

  private sourceSignature(sources?: Source[] | null): string {
    return (sources || [])
      .map((source) => `${this.sourceTitle(source)}:${source.filename || ''}:${source.document_id || ''}`)
      .join('|');
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
    const label = command['target_label'] || command['target'] || this.i18n.t('chat.map.command_fallback');
    return String(label);
  }

  sourceCollection(src: Source): string {
    return (
      (src.collection as string | undefined) ||
      (src.collection_name as string | undefined) ||
      ((src.metadata as any)?.collection as string | undefined) ||
      ((src.metadata as any)?.collection_name as string | undefined) ||
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
        parts.push(this.i18n.t('chat.source.locator_row', { range: `${rowStart}${end}` }));
      }
      return {
        label: parts.join(' · '),
        tooltip: this.i18n.t('chat.source.locator_sheet', { label: parts.join(' · ') }),
      };
    }
    const page = this.sourcePageNumber(src);
    if (page !== undefined && page !== null && `${page}`.trim() !== '') {
      return {
        label: this.i18n.t('chat.source.locator_page', { page }),
        tooltip: this.i18n.t('chat.source.locator_page_hint', { page }),
      };
    }
    const chunkIdx =
      (src['chunk_index'] as number | undefined) ??
      (meta['chunk_index'] as number | undefined) ??
      (meta['chunk_id'] as number | undefined);
    if (typeof chunkIdx === 'number' && Number.isFinite(chunkIdx)) {
      return {
        label: this.i18n.t('chat.source.locator_chunk', { index: chunkIdx }),
        tooltip: this.i18n.t('chat.source.locator_chunk_hint', { index: chunkIdx }),
      };
    }
    const docId = (src.document_id as string | undefined) ?? (meta['document_id'] as string | undefined);
    if (docId && typeof docId === 'string' && docId.length >= 6) {
      return {
        label: `#${docId.slice(0, 6)}`,
        tooltip: this.i18n.t('chat.source.locator_doc_hint', { id: docId }),
      };
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

  private sourcePageNumber(src: Source): number | null {
    const meta = (src.metadata ?? {}) as Record<string, unknown>;
    const raw =
      (src.page as number | string | undefined) ??
      (src['page_number'] as number | string | undefined) ??
      (meta['page'] as number | string | undefined) ??
      (meta['page_number'] as number | string | undefined);
    if (raw === undefined || raw === null || `${raw}`.trim() === '') return null;
    const value = typeof raw === 'number' ? raw : Number(raw);
    return Number.isInteger(value) && value > 0 ? value : null;
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
    const meta = (src.metadata ?? {}) as Record<string, unknown>;
    const sheet = src['sheet_name'] ?? meta['sheet_name'];
    const cells = src['cell_range'] ?? meta['cell_range'] ?? src['cell_ref'] ?? meta['cell_ref'];
    if (typeof sheet === 'string' && sheet) {
      url += `&sheet_name=${encodeURIComponent(sheet)}`;
    }
    if (typeof cells === 'string' && cells) url += `&cell_range=${encodeURIComponent(cells)}`;
    this.sourcePreviewTitle.set(this.sourceTitle(src));
    this.sourcePreviewUrl.set(url);
    this.sourcePreviewPage.set(this.sourcePageNumber(src));
    this.sourcePreviewHighlight.set(this.sourceHighlightText(src));
    this.sourcePreviewOpen.set(true);
    this.cdr.markForCheck();
  }

  /**
   * Full chunk text used to locate + highlight the passage inside the preview.
   * Unlike {@link sourceSnippet} (a 240-char display teaser), this returns the
   * complete snippet/content so the in-document matcher has the most to work
   * with.
   */
  private sourceHighlightText(src: Source): string | null {
    const raw =
      (src.snippet as string | undefined) ||
      (src.content as string | undefined) ||
      (src.text as string | undefined) ||
      '';
    const trimmed = raw.trim();
    return trimmed.length >= 8 ? trimmed : null;
  }

  closeSourcePreview(): void {
    this.sourcePreviewOpen.set(false);
    this.sourcePreviewUrl.set(null);
    this.sourcePreviewPage.set(null);
    this.sourcePreviewHighlight.set(null);
    this.cdr.markForCheck();
  }

  useSuggestion(s: SuggestionCard): void {
    this.userInput = s.prompt;
    this.voiceOracleMessage.set(this.i18n.t('chat.suggestion.question_ready'));
    this.cdr.markForCheck();
    this.focusComposer();
  }

  stageActionPrompt(action: ActionManifest): void {
    const phrase = action.phrases?.[0] || action.label;
    this.userInput = phrase;
    this.voiceOracleMessage.set(
      action.requires_confirmation
        ? this.i18n.t('chat.actions.proposed', { label: action.label })
        : this.i18n.t('chat.actions.ready', { label: action.label }),
    );
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
        label: this.i18n.t('chat.prompt.ask.label'),
        prompt: this.i18n.t('chat.prompt.ask.prompt_plain'),
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
        label: this.i18n.t('chat.prompt.verify.label'),
        prompt: this.i18n.t('chat.prompt.verify.prompt'),
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
        label: this.i18n.t('chat.prompt.find.label'),
        prompt: this.i18n.t('chat.prompt.find.prompt_with_doc'),
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
        label: this.i18n.t('chat.prompt.sourced.label'),
        prompt: this.i18n.t('chat.prompt.sourced.prompt'),
      };
    }
    if (label === 'find mismatch' || label === 'compare sources') {
      return {
        ...keepScope,
        icon: 'split',
        label: this.i18n.t('chat.prompt.compare.label'),
        prompt: this.i18n.t('chat.prompt.compare.prompt_plain'),
      };
    }
    return card;
  }

  private workspaceSuggestions(): SuggestionCard[] {
    return [
      {
        icon: 'search',
        label: this.i18n.t('chat.prompt.ask.label'),
        prompt: this.i18n.t('chat.prompt.ask.prompt_workspace'),
      },
      {
        icon: 'file-search',
        label: this.i18n.t('chat.prompt.find.label'),
        prompt: this.i18n.t('chat.prompt.find.prompt_plain'),
      },
      {
        icon: 'split',
        label: this.i18n.t('chat.prompt.compare.label'),
        prompt: this.i18n.t('chat.prompt.compare.prompt_docs'),
      },
      {
        icon: 'list-checks',
        label: this.i18n.t('chat.prompt.summarize.label'),
        prompt: this.i18n.t('chat.prompt.summarize.prompt_plain'),
      },
    ];
  }

  private knowledgeSourceSuggestions(source = this.scopeLabel(this.activeKnowledgeScope())): SuggestionCard[] {
    return [
      {
        icon: 'search',
        label: this.i18n.t('chat.prompt.ask.label'),
        prompt: this.i18n.t('chat.prompt.ask.prompt', { source }),
      },
      {
        icon: 'file-search',
        label: this.i18n.t('chat.prompt.find.label'),
        prompt: this.i18n.t('chat.prompt.find.prompt', { source }),
      },
      {
        icon: 'split',
        label: this.i18n.t('chat.prompt.compare.label'),
        prompt: this.i18n.t('chat.prompt.compare.prompt', { source }),
      },
      {
        icon: 'list-checks',
        label: this.i18n.t('chat.prompt.summarize.label'),
        prompt: this.i18n.t('chat.prompt.summarize.prompt', { source }),
      },
    ];
  }

  private sessionDocSuggestions(): SuggestionCard[] {
    const combine = this.sessionDocsMode() === 'combine';
    const source = this.scopeLabel(this.activeKnowledgeScope());
    return [
      {
        icon: 'list-checks',
        label: this.i18n.t('chat.prompt.files_summarize.label'),
        prompt: combine
          ? this.i18n.t('chat.prompt.files_summarize.prompt_combine', { source })
          : this.i18n.t('chat.prompt.files_summarize.prompt'),
      },
      {
        icon: 'search',
        label: this.i18n.t('chat.prompt.files_ask.label'),
        prompt: this.i18n.t('chat.prompt.files_ask.prompt'),
      },
      {
        icon: 'split',
        label: this.i18n.t('chat.prompt.compare.label'),
        prompt: combine
          ? this.i18n.t('chat.prompt.files_compare.prompt_combine', { source })
          : this.i18n.t('chat.prompt.files_compare.prompt'),
      },
      {
        icon: 'file-text',
        label: this.i18n.t('chat.prompt.files_note.label'),
        prompt: this.i18n.t('chat.prompt.files_note.prompt'),
      },
    ];
  }

  private isRecord(value: unknown): value is Record<string, unknown> {
    return !!value && typeof value === 'object' && !Array.isArray(value);
  }

  private finiteNumber(value: unknown): number | null {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'string' && value.trim()) {
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : null;
    }
    return null;
  }

  private parseLatencyBudget(value: unknown): NonNullable<NonNullable<ChatMessage['retrievalInfo']>['latencyBudget']> | null {
    if (!this.isRecord(value)) return null;
    const profile = typeof value['profile'] === 'string' ? (value['profile'] as string) : null;
    return {
      profile,
      deadlineSeconds: this.finiteNumber(value['deadline_seconds'] ?? value['deadlineSeconds']),
      candidatePoolK: this.finiteNumber(value['candidate_pool_k'] ?? value['candidatePoolK']),
      topK: this.finiteNumber(value['top_k'] ?? value['topK']),
    };
  }

  private parseNumberRecord(value: unknown): Record<string, number | null> | null {
    if (!this.isRecord(value)) return null;
    const out: Record<string, number | null> = {};
    Object.entries(value).forEach(([key, raw]) => {
      out[key] = this.finiteNumber(raw);
    });
    return Object.keys(out).length ? out : null;
  }

  private parseRetrievalDecisionTrace(value: unknown): RetrievalDecisionTrace | null {
    if (!this.isRecord(value)) return null;
    return value as RetrievalDecisionTrace;
  }

  decisionRouteLabel(trace: RetrievalDecisionTrace | null | undefined): string {
    const route = String(trace?.selected_route || 'retrieval');
    return route.replace(/_/g, ' ');
  }

  decisionTraceTitle(trace: RetrievalDecisionTrace | null | undefined): string {
    if (!trace) return this.i18n.t('chat.decision.trace_fallback');
    return [trace.summary, trace.route_reason, trace.tradeoff]
      .filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
      .join(' · ') || this.i18n.t('chat.decision.trace_fallback');
  }

  decisionTraceQualityLine(trace: RetrievalDecisionTrace | null | undefined): string {
    const quality = this.isRecord(trace?.quality_controls) ? trace!.quality_controls! : {};
    const sparse = quality['sparse_status']
      ? this.i18n.t('chat.decision.sparse', { status: String(quality['sparse_status']) })
      : null;
    const cross = quality['cross_encoder_status']
      ? this.i18n.t('chat.decision.cross_encoder', { status: String(quality['cross_encoder_status']) })
      : null;
    const latency = trace?.latency_profile
      ? this.i18n.t('chat.decision.latency', { profile: trace.latency_profile })
      : null;
    const queryType = trace?.query_type
      ? this.i18n.t('chat.decision.query_type', { type: trace.query_type })
      : null;
    return (
      [queryType, latency, sparse, cross].filter(Boolean).join(' · ') ||
      this.i18n.t('chat.decision.quality_fallback')
    );
  }

  decisionTraceSourcesLine(trace: RetrievalDecisionTrace | null | undefined): string {
    const sources = Array.isArray(trace?.selected_sources) ? trace!.selected_sources! : [];
    if (!sources.length) return this.i18n.t('chat.decision.sources_none');
    const labels = sources
      .map((source) => {
        if (!this.isRecord(source)) return null;
        return String(source['label'] || source['document_id'] || source['collection'] || '').trim();
      })
      .filter((label): label is string => !!label)
      .slice(0, 3);
    return labels.length
      ? this.i18n.t('chat.decision.sources_line', { labels: labels.join(' · ') })
      : this.i18n.t('chat.decision.sources_count', { count: sources.length });
  }

  private groundingDefaultMode(value: unknown): GroundingMode | null {
    if (!this.isRecord(value)) return null;
    const mode = value['default_mode'];
    return mode === 'strict' || mode === 'balanced' ? mode : null;
  }

  scopeLabel(scopeKey: string | null | undefined): string {
    if (!scopeKey) return this.i18n.t('chat.scope.workspace_fallback');
    const scope = this.knowledgeScopeOptions().find((item) => item.key === scopeKey);
    return this.cleanSourceLabel(scope?.label || scopeKey);
  }

  private cleanSourceLabel(label: string): string {
    const cleaned = label
      .replace(/\bknowledge\s+experiment\b/gi, '')
      .replace(/\bworkspace\s+Knowledge\b/g, this.i18n.t('chat.context.workspace'))
      .replace(/\s{2,}/g, ' ')
      .replace(/[\s·,:-]+$/g, '')
      .trim();
    return cleaned || label;
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

  retrievalPolicyLabel(info: NonNullable<ChatMessage['retrievalInfo']>): string {
    const budget = this.retrievalBudgetShortLabel(info);
    const scope = this.retrievalScopeChipLabel(info.retrievalScope);
    if (info.deepJobId) return this.i18n.t('chat.retrieval_policy.refine');
    let label = this.i18n.t('chat.retrieval_policy.retrieval');
    const policy = info.densePolicy || '';
    if (policy === 'catalogue_inventory') label = this.i18n.t('chat.retrieval_policy.catalogue');
    else if (policy === 'deep_hierarchical_dense') label = this.i18n.t('chat.retrieval_policy.deep');
    else if (policy === 'fast_scoped_dense_auto') label = this.i18n.t('chat.retrieval_policy.guardrail');
    else if (policy.startsWith('fast_scoped_dense')) label = this.i18n.t('chat.retrieval_policy.auto_scoped');
    else if (info.latencyProfile === 'fast') label = this.i18n.t('chat.retrieval_policy.fast');
    else if (info.latencyProfile === 'balanced') label = this.i18n.t('chat.retrieval_policy.balanced');
    return [label, scope, budget].filter(Boolean).join(' · ');
  }

  retrievalBadgeVisible(info: NonNullable<ChatMessage['retrievalInfo']>): boolean {
    return !!(info.deepJobId || info.densePolicy || info.retrievalScope || info.latencyProfile === 'deep');
  }

  sparseDegraded(info: NonNullable<ChatMessage['retrievalInfo']>): boolean {
    const status = (info.sparseStatus || '').toLowerCase();
    return status === 'timeout' || status === 'error';
  }

  deepRetrievalLabel(info: NonNullable<ChatMessage['retrievalInfo']>): string {
    if (info.deepStatus === 'completed') {
      const count = info.deepSummary?.chunksRetrieved;
      if (this.deepRetrievalPartial(info)) {
        return typeof count === 'number'
          ? this.i18n.t('chat.deep.state.partial_count', { count })
          : this.i18n.t('chat.deep.state.partial');
      }
      return typeof count === 'number'
        ? this.i18n.t('chat.deep.state.done_count', { count })
        : this.i18n.t('chat.deep.state.done');
    }
    if (info.deepStatus === 'failed') return this.i18n.t('chat.deep.state.failed');
    if (info.deepStatus === 'cancelled') return this.i18n.t('chat.deep.state.stopped');
    if (typeof info.deepProgress === 'number' && info.deepProgress > 0) {
      return this.i18n.t('chat.deep.state.progress', { percent: Math.round(info.deepProgress) });
    }
    if (info.deepStatus === 'queued') return this.i18n.t('chat.deep.state.queued');
    return info.deepStage ? this.i18n.t('chat.deep.state.running') : this.i18n.t('chat.deep.state.plain');
  }

  deepRetrievalTitle(info: NonNullable<ChatMessage['retrievalInfo']>): string {
    const parts = [`Deep retrieval job ${info.deepJobId || ''}`.trim()];
    if (info.deepStatus) parts.push(`status ${info.deepStatus}`);
    if (info.deepStage) parts.push(`stage ${info.deepStage}`);
    if (typeof info.deepProgress === 'number') parts.push(`progress ${Math.round(info.deepProgress)}%`);
    const summary = info.deepSummary;
    if (summary) {
      if (typeof summary.chunksRetrieved === 'number') parts.push(`${summary.chunksRetrieved} chunks`);
      if (typeof summary.sourcesReturned === 'number') parts.push(`${summary.sourcesReturned} sources`);
      if (summary.pipeline) parts.push(`pipeline ${summary.pipeline}`);
      if (summary.fallbackReason) parts.push(`fallback ${summary.fallbackReason}`);
      const topSources = (summary.topSources || [])
        .slice(0, 3)
        .map((source) => source.label || '')
        .filter(Boolean);
      if (topSources.length) parts.push(`top ${topSources.join(', ')}`);
    }
    return parts.join(' · ');
  }

  deepRetrievalPartial(info: NonNullable<ChatMessage['retrievalInfo']>): boolean {
    return info.deepStage === 'deep_timeout' || info.deepSummary?.partial === true;
  }

  deepRetrievalRunning(info: NonNullable<ChatMessage['retrievalInfo']>): boolean {
    return info.deepStatus === 'queued' || info.deepStatus === 'running' || !info.deepStatus;
  }

  deepRetrievalProgressValue(info: NonNullable<ChatMessage['retrievalInfo']>): number {
    if (info.deepStatus === 'completed') return 100;
    if (info.deepStatus === 'failed' || info.deepStatus === 'cancelled') return 100;
    const progress = typeof info.deepProgress === 'number' && Number.isFinite(info.deepProgress)
      ? info.deepProgress
      : info.deepStatus === 'running'
        ? 25
        : 8;
    return Math.max(4, Math.min(100, Math.round(progress)));
  }

  deepTopSourceLabels(summary: NonNullable<NonNullable<ChatMessage['retrievalInfo']>['deepSummary']>): string[] {
    return (summary.topSources || [])
      .slice(0, 3)
      .map((source) => {
        const label = source.label || '';
        const short = label.length > 42 ? `${label.slice(0, 39)}...` : label;
        return source.chunks != null ? `${short} (${source.chunks})` : short;
      })
      .filter(Boolean);
  }

  toggleDeepRetrievalDetails(msg: ChatMessage): void {
    const info = msg.retrievalInfo;
    const jobId = info?.deepJobId;
    if (!info || !jobId) return;
    if (info.deepDetailsOpen) {
      this.patchMessageRetrievalInfo(msg.id, { deepDetailsOpen: false });
      return;
    }
    if (info.deepSources || info.deepDetailsError) {
      this.patchMessageRetrievalInfo(msg.id, { deepDetailsOpen: true });
      return;
    }
    this.patchMessageRetrievalInfo(msg.id, {
      deepDetailsOpen: true,
      deepDetailsLoading: true,
      deepDetailsError: null,
    });
    const jobPath = this.deepRetrievalJobPath(info, jobId);
    this.api
      .get<{ result?: unknown; status?: string }>(jobPath)
      .subscribe({
        next: (job) => {
          const sources = this.deepSourcesFromJob(job);
          if (sources.length || job.status !== 'completed') {
            this.patchMessageRetrievalInfo(msg.id, {
              deepDetailsLoading: false,
              deepDetailsError: null,
              deepSources: sources,
            });
            return;
          }
          this.api
            .get<{ result?: unknown; status?: string }>(jobPath, { include_context: 'true' })
            .subscribe({
              next: (detailedJob) => {
                this.patchMessageRetrievalInfo(msg.id, {
                  deepDetailsLoading: false,
                  deepDetailsError: null,
                  deepSources: this.deepSourcesFromJob(detailedJob),
                });
              },
              error: () => {
                this.patchMessageRetrievalInfo(msg.id, {
                  deepDetailsLoading: false,
                  deepDetailsError: this.i18n.t('chat.deep.details_error'),
                });
              },
            });
        },
        error: () => {
          this.patchMessageRetrievalInfo(msg.id, {
            deepDetailsLoading: false,
            deepDetailsError: this.i18n.t('chat.deep.details_error'),
          });
        },
      });
  }

  /** Where the tracker polls from — shown as raw detail under the progress bar. */
  deepTrackerPath(info: NonNullable<ChatMessage['retrievalInfo']>): string {
    return this.deepRetrievalJobPath(info, String(info.deepJobId || ''));
  }

  private deepRetrievalJobPath(
    info: NonNullable<ChatMessage['retrievalInfo']>,
    fallbackJobId: string,
  ): string {
    const path = String(info.deepPollUrl || '').trim();
    if (path.startsWith('/workspace-jobs/')) return path;
    if (path.startsWith('/documents/jobs/')) return path;
    return `/workspace-jobs/${encodeURIComponent(fallbackJobId)}`;
  }

  private patchMessageRetrievalInfo(
    messageId: string,
    patch: Partial<NonNullable<ChatMessage['retrievalInfo']>>,
  ): void {
    this.messages.update((messages) =>
      messages.map((msg) => {
        if (msg.id !== messageId) return msg;
        return {
          ...msg,
          retrievalInfo: {
            ...(msg.retrievalInfo || {}),
            ...patch,
          },
        };
      }),
    );
  }

  private deepSourcesFromJob(job: { result?: unknown }): Source[] {
    const result = job.result;
    if (!this.isRecord(result)) return [];
    const partialResult = this.isRecord(result['partial_result'])
      ? (result['partial_result'] as Record<string, unknown>)
      : null;
    const sourcePreview = Array.isArray(result['sources_preview'])
      ? (result['sources_preview'] as unknown[])
      : partialResult && Array.isArray(partialResult['sources_preview'])
        ? (partialResult['sources_preview'] as unknown[])
        : null;
    if (sourcePreview) {
      const preview = sourcePreview
        .filter((source): source is Record<string, unknown> => this.isRecord(source))
        .map((source, index) => {
          const meta = this.isRecord(source['metadata']) ? (source['metadata'] as Record<string, unknown>) : {};
          return {
            id: (source['id'] as string | undefined) || (meta['chunk_id'] as string | undefined) || `deep-preview:${index}`,
            document_id: (source['document_id'] as string | undefined) || (meta['document_id'] as string | undefined),
            title: (source['title'] as string | undefined) || (meta['document_title'] as string | undefined),
            filename: (source['filename'] as string | undefined) || (meta['document_filename'] as string | undefined),
            snippet: (source['snippet'] as string | undefined) || (source['content'] as string | undefined),
            content: (source['content'] as string | undefined) || (source['snippet'] as string | undefined),
            score: typeof source['score'] === 'number' ? (source['score'] as number) : undefined,
            collection: (source['collection'] as string | undefined) || (meta['collection'] as string | undefined),
            collection_name:
              (source['collection_name'] as string | undefined) || (meta['collection_name'] as string | undefined),
            page: typeof source['page'] === 'number' ? (source['page'] as number) : undefined,
            metadata: meta,
          } satisfies Source;
        });
      if (preview.length) return preview;
    }
    if (!this.isRecord(result['retrieval_context'])) return [];
    const context = result['retrieval_context'];
    const chunks = Array.isArray(context['chunks']) ? context['chunks'] : [];
    const scores = Array.isArray(context['scores']) ? context['scores'] : [];
    const metadatas = Array.isArray(context['metadatas']) ? context['metadatas'] : [];
    const collection = typeof context['collection'] === 'string' ? (context['collection'] as string) : undefined;
    return chunks.map((chunk, index) => {
      const meta = this.isRecord(metadatas[index]) ? (metadatas[index] as Record<string, unknown>) : {};
      const score = typeof scores[index] === 'number' ? (scores[index] as number) : undefined;
      const filename =
        (meta['filename'] as string | undefined) ||
        (meta['document_filename'] as string | undefined) ||
        (meta['source'] as string | undefined);
      const title =
        (meta['document_title'] as string | undefined) ||
        (meta['title'] as string | undefined) ||
        filename;
      const documentId = (meta['document_id'] as string | undefined) || (meta['id'] as string | undefined);
      return {
        id: (meta['chunk_id'] as string | undefined) || `${documentId || 'deep'}:${index}`,
        document_id: documentId,
        title,
        filename,
        snippet: typeof chunk === 'string' ? chunk : String(chunk ?? ''),
        content: typeof chunk === 'string' ? chunk : String(chunk ?? ''),
        score,
        collection: (meta['collection'] as string | undefined) || (meta['collection_name'] as string | undefined) || collection,
        collection_name: (meta['collection_name'] as string | undefined) || (meta['collection'] as string | undefined) || collection,
        page: typeof meta['page'] === 'number' ? (meta['page'] as number) : undefined,
        metadata: meta,
      } satisfies Source;
    });
  }

  private parseDeepSummaryMeta(raw: unknown): NonNullable<NonNullable<ChatMessage['retrievalInfo']>['deepSummary']> | null {
    if (!this.isRecord(raw)) return null;
    const topSourcesRaw = Array.isArray(raw['top_sources']) ? raw['top_sources'] : [];
    return {
      chunksRetrieved: typeof raw['chunks_retrieved'] === 'number' ? (raw['chunks_retrieved'] as number) : null,
      sourcesReturned: typeof raw['sources_returned'] === 'number' ? (raw['sources_returned'] as number) : null,
      topScore: typeof raw['top_score'] === 'number' ? (raw['top_score'] as number) : null,
      pipeline: typeof raw['pipeline'] === 'string' ? (raw['pipeline'] as string) : null,
      partial: raw['partial'] === true,
      fallbackReason: typeof raw['fallback_reason'] === 'string' ? (raw['fallback_reason'] as string) : null,
      topSources: topSourcesRaw
        .filter((source): source is Record<string, unknown> => this.isRecord(source))
        .map((source) => ({
          label: typeof source['label'] === 'string' ? (source['label'] as string) : null,
          chunks: typeof source['chunks'] === 'number' ? (source['chunks'] as number) : null,
        })),
    };
  }

  private parseDeepSummaryFromJob(job: unknown): NonNullable<NonNullable<ChatMessage['retrievalInfo']>['deepSummary']> | null {
    if (!this.isRecord(job)) return null;
    const result = this.isRecord(job['result']) ? (job['result'] as Record<string, unknown>) : {};
    return this.parseDeepSummaryMeta(result['summary']);
  }

  retrievalPolicyTitle(info: NonNullable<ChatMessage['retrievalInfo']>): string {
    const parts: string[] = [];
    if (info.scopeReason) parts.push(info.scopeReason);
    const scopeSummary = this.retrievalScopeSummary(info.retrievalScope);
    if (scopeSummary) parts.push(`scope ${scopeSummary}`);
    if (typeof info.scopeConfidence === 'number') {
      parts.push(`confidence ${Math.round(info.scopeConfidence * 100)}%`);
    }
    if (info.densePolicy) parts.push(`policy ${info.densePolicy}`);
    if (info.fallbackReason) parts.push(`fallback ${info.fallbackReason}`);
    const budget = this.retrievalBudgetTitle(info);
    if (budget) parts.push(budget);
    else if (info.latencyProfile) parts.push(`profile ${info.latencyProfile}`);
    const layerSummary = this.retrievalPlanLayerSummary(info.retrievalPlan);
    if (layerSummary) parts.push(layerSummary);
    const timingSummary = this.retrievalTimingSummary(info.stageTimings);
    if (timingSummary) parts.push(timingSummary);
    const countSummary = this.retrievalCountSummary(info.candidateCounts);
    if (countSummary) parts.push(countSummary);
    return parts.join(' · ') || this.i18n.t('chat.retrieval_policy.title_fallback');
  }

  private retrievalScopeSummary(scope: Record<string, unknown> | null | undefined): string | null {
    if (!this.isRecord(scope)) return null;
    const filters = this.isRecord(scope['filters']) ? (scope['filters'] as Record<string, unknown>) : {};
    const fields: Array<[string, string]> = [
      ['project_code', 'project'],
      ['archive_name', 'archive'],
      ['source_kind', 'kind'],
      ['extension', 'ext'],
      ['status', 'status'],
      ['language', 'lang'],
      ['document_filename', 'file'],
      ['document_id', 'doc'],
    ];
    const parts = fields
      .map(([key, label]) => {
        const rendered = this.renderScopeValue(filters[key]);
        return rendered ? `${label} ${rendered}` : null;
      })
      .filter((part): part is string => !!part);
    if (parts.length) return parts.slice(0, 4).join(', ');
    const fallbackParts: string[] = [];
    if (typeof scope['intent'] === 'string') fallbackParts.push(`intent ${scope['intent']}`);
    const sourceCount = this.finiteNumber(scope['source_count'] ?? scope['sourceCount']);
    const chunkCount = this.finiteNumber(scope['chunk_count'] ?? scope['chunkCount']);
    if (typeof sourceCount === 'number') fallbackParts.push(`${Math.round(sourceCount)} sources`);
    if (typeof chunkCount === 'number') fallbackParts.push(`${Math.round(chunkCount)} chunks`);
    return fallbackParts.slice(0, 3).join(', ') || null;
  }

  private retrievalScopeChipLabel(scope: Record<string, unknown> | null | undefined): string | null {
    if (!this.isRecord(scope)) return null;
    const filters = this.isRecord(scope['filters']) ? (scope['filters'] as Record<string, unknown>) : {};
    for (const key of ['project_code', 'archive_name', 'source_kind', 'extension', 'document_filename']) {
      const rendered = this.renderScopeValue(filters[key]);
      if (rendered) return this.truncateScopeChip(rendered);
    }
    return null;
  }

  private renderScopeValue(value: unknown): string | null {
    if (Array.isArray(value)) {
      const cleaned = value.map((item) => String(item ?? '').trim()).filter(Boolean);
      if (!cleaned.length) return null;
      if (cleaned.length > 3) return `${cleaned.length} selected`;
      return cleaned.map((item) => this.truncateScopeValue(item)).join(', ');
    }
    if (this.isRecord(value)) {
      const nested = Object.values(value).find((item) => item !== null && item !== undefined && item !== '');
      return this.renderScopeValue(nested);
    }
    const text = String(value ?? '').trim();
    return text ? this.truncateScopeValue(text) : null;
  }

  private truncateScopeValue(value: string): string {
    return value.length > 34 ? `${value.slice(0, 31)}...` : value;
  }

  private truncateScopeChip(value: string): string {
    return value.length > 18 ? `${value.slice(0, 15)}...` : value;
  }

  private retrievalBudgetShortLabel(info: NonNullable<ChatMessage['retrievalInfo']>): string | null {
    const budget = info.latencyBudget;
    const seconds = budget?.deadlineSeconds;
    if (typeof seconds === 'number' && Number.isFinite(seconds) && seconds > 0) {
      return `${Math.round(seconds)}s`;
    }
    return null;
  }

  private retrievalBudgetTitle(info: NonNullable<ChatMessage['retrievalInfo']>): string | null {
    const budget = info.latencyBudget;
    if (!budget) return null;
    const parts: string[] = [];
    if (budget.profile) parts.push(`profile ${budget.profile}`);
    if (typeof budget.deadlineSeconds === 'number') parts.push(`deadline ${budget.deadlineSeconds}s`);
    if (typeof budget.candidatePoolK === 'number') parts.push(`candidate pool ${budget.candidatePoolK}`);
    if (typeof budget.topK === 'number') parts.push(`top k ${budget.topK}`);
    return parts.join(', ') || null;
  }

  private retrievalPlanLayerSummary(plan: Record<string, unknown> | null | undefined): string | null {
    if (!plan || typeof plan !== 'object') return null;
    const layers = plan['layers'];
    if (!layers || typeof layers !== 'object') return null;
    const active: string[] = [];
    Object.entries(layers as Record<string, unknown>).forEach(([key, raw]) => {
      if (!raw || typeof raw !== 'object') return;
      const layer = raw as Record<string, unknown>;
      if (layer['enabled'] === true) active.push(key);
    });
    if (!active.length) return null;
    const deadline = typeof plan['deadline_ms'] === 'number' ? ` / ${Math.round((plan['deadline_ms'] as number) / 1000)}s` : '';
    return `layers ${active.slice(0, 6).join(', ')}${active.length > 6 ? ', ...' : ''}${deadline}`;
  }

  private retrievalTimingSummary(timings: Record<string, number | null> | null | undefined): string | null {
    if (!timings) return null;
    const labels: Array<[string, string]> = [
      ['planner_ms', 'plan'],
      ['inventory_ms', 'inventory'],
      ['qdrant_ms', 'qdrant'],
      ['sparse_ms', 'sparse'],
      ['rerank_ms', 'rerank'],
      ['context_build_ms', 'context'],
      ['table_facts_ms', 'tables'],
      ['llm_ms', 'llm'],
      ['total_ms', 'total'],
    ];
    const parts = labels
      .map(([key, label]) => {
        const value = timings[key];
        return typeof value === 'number' ? `${label} ${Math.round(value)}ms` : null;
      })
      .filter((part): part is string => !!part);
    return parts.length ? `timings ${parts.join(', ')}` : null;
  }

  private retrievalCountSummary(counts: Record<string, number | null> | null | undefined): string | null {
    if (!counts) return null;
    const chunks = counts['chunks_retrieved'];
    const raw = counts['raw_chunks_retrieved'];
    const pool = counts['candidate_pool_k'];
    const corpusChunks = counts['chunk_count'];
    const exactTables = counts['exact_table_hits'];
    const bits: string[] = [];
    if (typeof chunks === 'number') bits.push(`loaded ${chunks}`);
    if (typeof raw === 'number' && raw !== chunks) bits.push(`raw ${raw}`);
    if (typeof exactTables === 'number' && exactTables > 0) bits.push(`exact tables ${exactTables}`);
    if (typeof pool === 'number') bits.push(`pool ${pool}`);
    if (typeof corpusChunks === 'number') bits.push(`corpus ${corpusChunks}`);
    return bits.length ? `counts ${bits.join(', ')}` : null;
  }

  private responseLanguageFor(query: string): Locale {
    const text = (query || '').trim();
    if (!text) return this.i18n.locale();
    const french = /[àâçéèêëîïôùûüÿœæ]|\b(bonjour|bonsoir|salut|merci|quel|quelle|quels|quelles|comment|pourquoi|où|peux[\s-]?tu|pouvez[\s-]?vous|donne|retrouve|résume|resume|explique|source|fichier|documents?|données)\b/i;
    const english = /\b(hello|hi|thanks|thank\s+you|what|which|how|why|where|when|who|can\s+you|could\s+you|please|show\s+me|tell\s+me|find|retrieve|summari[sz]e|explain|give\s+me|documents?|sources?|files?|data|knowledge)\b/i;
    const hasFrench = french.test(text);
    const hasEnglish = english.test(text);
    if (hasEnglish && !hasFrench) return 'en';
    if (hasFrench && !hasEnglish) return 'fr';
    return this.i18n.locale();
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
      const scope = this.workspace.captureRequestScope();
      const generation = this.chatWorkspaceGeneration;
      this.creatingChatSession = true;
      const subscription = this.api
        .post<ChatSessionSummary>(
          '/sessions',
          { context: this.currentChatSessionContext() },
          { workspaceSlug: scope.workspaceSlug },
        )
        .subscribe({
          next: (session) => {
            if (!this.isChatContinuationCurrent(scope, generation)) return;
            this.chatSessionId = session.id;
            this.activeChatSessionId.set(session.id);
            this.storeSelectedSessionId(session.id, scope.workspaceSlug);
            this.chatSessions.update((sessions) => [session, ...sessions.filter((item) => item.id !== session.id)]);
            this.creatingChatSession = false;
            this.send();
          },
          error: () => {
            if (!this.isChatContinuationCurrent(scope, generation)) return;
            this.creatingChatSession = false;
            this.toast.error(this.i18n.t('chat.toast.create_failed'), this.i18n.t('chat.title'));
          },
        });
      this.chatWorkspaceSubscriptions.add(subscription);
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
    this.liveRetrievalInfo.set(null);
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
    let retrievalInfo: ChatMessage['retrievalInfo'] = null;
    // Set when the backend consumed this turn as an expert correction (a
    // teaching message detected on /chat): the reply is the same sober
    // acknowledgement the "Corriger" composer produces, not an answer.
    let expertCorrection: Record<string, unknown> | null = null;
    let pendingDeepSearch:
      | {
          jobId: string;
          messageId: string;
          pollUrl: string;
          status: string;
          progress: number;
          stage: string | null;
          parentMessageId: string | null;
        }
      | null = null;

    const ragOverride = this.ragModeOverride();
    const promptTypeSel = this.promptType();
    const responseLanguage = this.responseLanguageFor(text);
    // Demo-safe surfaces keep the chat chrome light and defer the whole
    // retrieval budget to the workspace chat flow defaults (scope top_k,
    // mode, latency profile). Null fields let the backend folds apply, so
    // the values shown in workspace settings are the ones actually used.
    const deferToWorkspace = this.isDemoMode();
    const streamScope = this.workspace.captureRequestScope();
    const streamGeneration = this.chatWorkspaceGeneration;
    this.adoptionInteraction.emit({step:'question'});
    const streamSubscription = this.sse
      .stream('/api/v1/chat/stream', {
        query: text,
        ui_locale: this.i18n.locale(),
        response_language: responseLanguage,
        agent_id: this.systemId(),
        session_id: this.chatSessionId,
        context_id: this.contextId(),
        context_mode: this.contextId() ? this.sessionDocsMode() : null,
        stream: true,
        include_reasoning: true,
        include_sources: true,
        temperature: s.temperature,
        max_tokens: s.maxTokens,
        top_k: deferToWorkspace ? null : s.ragTopK,
        candidate_pool_k: deferToWorkspace
          ? null
          : Math.min(s.ragCandidatePoolK ?? Math.max((s.ragSynthesisK ?? 12) * 4, 40), 20),
        synthesis_k: deferToWorkspace ? null : (s.ragSynthesisK ?? Math.max(s.ragTopK ?? 5, 12)),
        source_display_k: deferToWorkspace
          ? null
          : (s.ragSourceDisplayK ?? Math.min(Math.max(s.ragTopK ?? 5, 5), 8)),
        latency_profile: deferToWorkspace ? null : 'fast',
        similarity_threshold: deferToWorkspace ? null : s.ragSimilarityThreshold,
        // Per-query retrieval override wins over workspace default.
        rag_pipeline_mode:
          ragOverride !== 'auto' ? ragOverride : deferToWorkspace ? null : s.ragPipelineMode,
        rag_mode_override: ragOverride !== 'auto' ? ragOverride : null,
        // Per-query reasoning template; "auto" lets the mode_selector decide.
        prompt_type: promptTypeSel !== 'auto' ? promptTypeSel : null,
        knowledge_scope: this.knowledgeScopeOverride() || this.activeKnowledgeScope(),
        assistant_profile: this.activeAssistantProfile()?.key ?? this.assistantProfileKey(),
        grounding_mode: this.groundingMode(),
        system_prompt: this.systemPrompt() ?? ((s['systemPrompt'] as string | undefined) ?? null),
        agent_preferences: {
          model_preferences: {
            model: s.defaultModel,
            provider: s.defaultProvider,
          },
        },
      })
      .subscribe({
        next: (chunk: SseChunk) => {
          if (!this.isChatContinuationCurrent(streamScope, streamGeneration)) return;
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
          if (this.isRecord((chunk as Record<string, unknown>)['expert_correction'])) {
            expertCorrection = (chunk as Record<string, unknown>)['expert_correction'] as Record<string, unknown>;
          }
          if (chunk.chunk_type === 'session' && typeof (chunk as Record<string, unknown>)['session_id'] === 'string') {
            const sessionId = (chunk as Record<string, unknown>)['session_id'] as string;
            this.chatSessionId = sessionId;
            this.activeChatSessionId.set(sessionId);
            this.storeSelectedSessionId(sessionId, streamScope.workspaceSlug);
          } else if (chunk.chunk_type === 'text' && typeof chunk.content === 'string') {
            buffer += chunk.content;
            this.streamBuffer.set(buffer);
            if (this.ttsEnabled()) this.maybeFlushSentences(buffer);
          } else if (chunk.chunk_type === 'decision_step' && chunk.decision_step) {
            const step = chunk.decision_step as DecisionStep;
            reasoning = upsertStep(reasoning, step);
            this.liveSteps.set([...reasoning]);
          } else if (chunk.chunk_type === 'retrieval') {
            const details = (((chunk as Record<string, unknown>)['details'] as Record<string, unknown> | undefined) || {});
            const phase = String((chunk as Record<string, unknown>)['phase'] || '');
            if (phase === 'deep_queued') {
              const jobId = typeof details['deep_job_id'] === 'string' ? (details['deep_job_id'] as string) : '';
              if (jobId) {
                pendingDeepSearch = {
                  jobId,
                  messageId:
                    typeof details['message_id'] === 'string' && details['message_id']
                      ? (details['message_id'] as string)
                      : `job:${jobId}`,
                  pollUrl:
                    typeof details['deep_poll_url'] === 'string' && details['deep_poll_url']
                      ? (details['deep_poll_url'] as string)
                      : `/workspace-jobs/${jobId}`,
                  status: typeof details['deep_status'] === 'string' ? (details['deep_status'] as string) : 'queued',
                  progress: typeof details['deep_progress'] === 'number' ? (details['deep_progress'] as number) : 0,
                  stage: typeof details['deep_stage'] === 'string' ? (details['deep_stage'] as string) : 'auto_deep_search',
                  parentMessageId: typeof details['parent_message_id'] === 'string' ? (details['parent_message_id'] as string) : null,
                };
              }
              return;
            }
            const latencyBudget = this.parseLatencyBudget(details['latency_budget']);
            const stageTimings = this.parseNumberRecord(details['stage_timings']);
            const candidateCounts = this.parseNumberRecord(details['candidate_counts']);
            const decisionTrace = this.parseRetrievalDecisionTrace(details['retrieval_decision_trace']);
            retrievalInfo = {
              ...(retrievalInfo || {}),
              densePolicy: (details['dense_policy'] as string | undefined) ?? retrievalInfo?.densePolicy ?? null,
              fallbackReason:
                (details['fallback_reason'] as string | undefined)
                ?? (details['retrieval_fallback'] as string | undefined)
                ?? retrievalInfo?.fallbackReason
                ?? null,
              retrievalPlan:
                this.isRecord(details['retrieval_plan'])
                  ? (details['retrieval_plan'] as Record<string, unknown>)
                  : retrievalInfo?.retrievalPlan ?? null,
              retrievalScope:
                this.isRecord(details['retrieval_scope'])
                  ? (details['retrieval_scope'] as Record<string, unknown>)
                  : retrievalInfo?.retrievalScope ?? null,
              sparseStatus: (details['sparse_status'] as string | undefined) ?? retrievalInfo?.sparseStatus ?? null,
              scopeReason: (details['scope_reason'] as string | undefined) ?? retrievalInfo?.scopeReason ?? null,
              scopeConfidence:
                typeof details['scope_confidence'] === 'number'
                  ? (details['scope_confidence'] as number)
                  : retrievalInfo?.scopeConfidence ?? null,
              latencyProfile:
                (details['latency_profile'] as string | undefined)
                ?? latencyBudget?.profile
                ?? retrievalInfo?.latencyProfile
                ?? null,
              latencyBudget: latencyBudget ?? retrievalInfo?.latencyBudget ?? null,
              stageTimings: stageTimings ?? retrievalInfo?.stageTimings ?? null,
              candidateCounts: candidateCounts ?? retrievalInfo?.candidateCounts ?? null,
              decisionTrace: decisionTrace ?? retrievalInfo?.decisionTrace ?? null,
              deepJobId: (details['deep_job_id'] as string | undefined) ?? retrievalInfo?.deepJobId ?? null,
              deepStatus: (details['deep_status'] as string | undefined) ?? retrievalInfo?.deepStatus ?? null,
              deepProgress:
                typeof details['deep_progress'] === 'number'
                  ? (details['deep_progress'] as number)
                  : retrievalInfo?.deepProgress ?? null,
              deepStage: (details['deep_stage'] as string | undefined) ?? retrievalInfo?.deepStage ?? null,
              deepPollUrl: (details['deep_poll_url'] as string | undefined) ?? retrievalInfo?.deepPollUrl ?? null,
            };
            this.liveRetrievalInfo.set(retrievalInfo);
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
          } else if (chunk.chunk_type === 'hitl_pending' && chunk.run_id) {
            // The SSE request ends at the governance gate. Poll the user's
            // own chat session (never the private Run draft) so an accepted
            // or rejected decision refreshes this bubble without a reload.
            this.startHitlMessagePolling(chunk.run_id);
          } else if (chunk.sources && Array.isArray(chunk.sources)) {
            sources = chunk.sources as Source[];
          } else if (chunk.type === 'done') {
            this.adoptionInteraction.emit({step:'answer',runId:turnRunId,sessionId:this.chatSessionId || undefined});
            const durationMs = Date.now() - this.streamStart;
            // Reuse the backend's acknowledgement message id so the bubble
            // matches the persisted one after a reload.
            const ackId = expertCorrection?.['message_id'];
            const assistantId = typeof ackId === 'string' && ackId ? ackId : cryptoId();
            const assistantMsg: ChatMessage = {
              id: assistantId,
              role: 'assistant',
              content: buffer,
              kind: expertCorrection ? 'correction_ack' : undefined,
              decisionSteps: reasoning.length ? reasoning : undefined,
              sources,
              mapCommand,
              feedback: null,
              evaluation: null,
              durationMs,
              ragMode: ragOverride !== 'auto' ? ragOverride : null,
              promptType: promptTypeSel !== 'auto' ? promptTypeSel : null,
              retrievalInfo,
              runId: turnRunId ?? null,
              qaReview: null,
            };
            this.messages.update((m) => [...m, assistantMsg]);
            if (pendingDeepSearch) {
              const parentMessageId = pendingDeepSearch.parentMessageId || assistantId;
              this.appendDeepSearchPlaceholder({
                messageId: pendingDeepSearch.messageId,
                jobId: pendingDeepSearch.jobId,
                pollUrl: pendingDeepSearch.pollUrl,
                status: pendingDeepSearch.status,
                progress: pendingDeepSearch.progress,
                stage: pendingDeepSearch.stage,
                parentMessageId,
              });
              this.startDeepRetrievalPolling(
                pendingDeepSearch.messageId,
                pendingDeepSearch.jobId,
                pendingDeepSearch.pollUrl,
              );
            }
            this.streaming.set(false);
            this.streamBuffer.set('');
            this.liveSteps.set([]);
            this.liveRetrievalInfo.set(null);
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
            this.loadChatSessions(this.chatSessionId);
            this.focusComposer();
          }
        },
        error: () => {
          if (!this.isChatContinuationCurrent(streamScope, streamGeneration)) return;
          this.toast.error(this.i18n.t('chat.toast.stream_lost'), this.i18n.t('chat.title'));
          this.streaming.set(false);
          this.streamBuffer.set('');
          this.liveSteps.set([]);
          this.liveRetrievalInfo.set(null);
          if (this.ttsEnabled()) this.resetTtsPipeline();
          this.scheduleVoiceLoopRearm();
          this.focusComposer();
        },
      });
    this.chatWorkspaceSubscriptions.add(streamSubscription);
  }

  clearConversation(): void {
    this.createNewChat();
  }

  deepSearchTrackedJobId(msg: ChatMessage): string | null {
    const direct = msg.retrievalInfo?.deepJobId;
    if (direct) return direct;
    const linked = this.messages().find(
      (candidate) =>
        candidate.id !== msg.id
        && candidate.retrievalInfo?.deepParentMessageId === msg.id
        && !!candidate.retrievalInfo.deepJobId,
    );
    return linked?.retrievalInfo?.deepJobId || null;
  }

  private appendDeepSearchPlaceholder(params: {
    messageId: string;
    jobId: string;
    pollUrl: string;
    status: string;
    progress: number;
    stage: string | null;
    parentMessageId: string | null;
  }): void {
    const content = this.i18n.t('chat.deep_search.started_notice');
    this.messages.update((messages) => {
      const existing = messages.some((msg) => msg.id === params.messageId);
      if (existing) {
        return messages.map((msg) => {
          if (msg.id !== params.messageId) return msg;
          return {
            ...msg,
            retrievalInfo: {
              ...(msg.retrievalInfo || {}),
              deepJobId: params.jobId,
              deepPollUrl: params.pollUrl,
              deepStatus: params.status,
              deepProgress: params.progress,
              deepStage: params.stage,
              deepParentMessageId: params.parentMessageId,
              deepDetailsOpen: false,
              deepDetailsLoading: false,
              deepDetailsError: null,
            },
          };
        });
      }
      const placeholder: ChatMessage = {
        id: params.messageId,
        role: 'assistant',
        content,
        sources: [],
        feedback: null,
        evaluation: null,
        retrievalInfo: {
          deepJobId: params.jobId,
          deepPollUrl: params.pollUrl,
          deepStatus: params.status,
          deepProgress: params.progress,
          deepStage: params.stage,
          deepParentMessageId: params.parentMessageId,
          deepDetailsOpen: false,
          deepDetailsLoading: false,
          deepDetailsError: null,
        },
      };
      return [...messages, placeholder];
    });
  }

  launchDeepSearch(msg: ChatMessage): void {
    if (msg.role !== 'assistant' || this.deepSearchTrackedJobId(msg) || this.deepSearchLaunchingId() === msg.id) return;
    const query = this.previousUserQueryFor(msg.id);
    if (!query) {
      this.toast.error(this.i18n.t('chat.deep.no_source_question'), this.i18n.t('chat.deep.title'));
      return;
    }
    const s = this.settings.settings();
    const ragOverride = this.ragModeOverride();
    const promptTypeSel = this.promptType();
    const responseLanguage = this.responseLanguageFor(query);
    const scope = this.workspace.captureRequestScope();
    const generation = this.chatWorkspaceGeneration;
    this.deepSearchLaunchingId.set(msg.id);
    const subscription = this.api
      .post<{
        id?: string;
        poll_url?: string;
        status?: string;
        progress?: number;
        stage?: string | null;
        message_id?: string | null;
        parent_message_id?: string | null;
      }>('/chat/deep-retrieval-jobs', {
        query,
        ui_locale: this.i18n.locale(),
        response_language: responseLanguage,
        parent_message_id: msg.id,
        previous_answer: msg.content,
        agent_id: this.systemId(),
        session_id: this.chatSessionId,
        context_id: this.contextId(),
        context_mode: this.contextId() ? this.sessionDocsMode() : null,
        stream: false,
        include_reasoning: true,
        include_sources: true,
        temperature: s.temperature,
        max_tokens: s.maxTokens,
        latency_profile: 'deep',
        deep_retrieval: true,
        rag_pipeline_mode: ragOverride !== 'auto' ? ragOverride : s.ragPipelineMode,
        rag_mode_override: ragOverride !== 'auto' ? ragOverride : null,
        prompt_type: promptTypeSel !== 'auto' ? promptTypeSel : null,
        knowledge_scope: this.knowledgeScopeOverride() || this.activeKnowledgeScope(),
        assistant_profile: this.activeAssistantProfile()?.key ?? this.assistantProfileKey(),
        grounding_mode: this.groundingMode(),
        system_prompt: this.systemPrompt() ?? ((s['systemPrompt'] as string | undefined) ?? null),
        agent_preferences: {
          model_preferences: {
            model: s.defaultModel,
            provider: s.defaultProvider,
          },
        },
      }, { workspaceSlug: scope.workspaceSlug })
      .subscribe({
        next: (job) => {
          if (!this.isChatContinuationCurrent(scope, generation)) return;
          const jobId = typeof job?.id === 'string' ? job.id : '';
          if (!jobId) {
            this.toast.error('Deep Search job was not created.', 'Deep Search');
            this.deepSearchLaunchingId.set(null);
            return;
          }
          const pollUrl = typeof job.poll_url === 'string' ? job.poll_url : `/workspace-jobs/${jobId}`;
          const messageId =
            typeof job.message_id === 'string' && job.message_id
              ? job.message_id
              : `job:${jobId}`;
          this.appendDeepSearchPlaceholder({
            messageId,
            jobId,
            pollUrl,
            status: typeof job.status === 'string' ? job.status : 'queued',
            progress: typeof job.progress === 'number' ? job.progress : 0,
            stage: typeof job.stage === 'string' ? job.stage : 'manual_deep_search',
            parentMessageId: msg.id,
          });
          this.startDeepRetrievalPolling(messageId, jobId, pollUrl);
          this.deepSearchLaunchingId.set(null);
        },
        error: () => {
          if (!this.isChatContinuationCurrent(scope, generation)) return;
          this.deepSearchLaunchingId.set(null);
          this.toast.error(this.i18n.t('chat.deep.launch_failed'), this.i18n.t('chat.deep.title'));
        },
      });
    this.chatWorkspaceSubscriptions.add(subscription);
  }

  private previousUserQueryFor(messageId: string): string | null {
    const messages = this.messages();
    const index = messages.findIndex((message) => message.id === messageId);
    if (index < 0) return null;
    for (let i = index - 1; i >= 0; i -= 1) {
      const candidate = messages[i];
      if (candidate.role === 'user' && candidate.content.trim()) return candidate.content.trim();
    }
    return null;
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
      knowledge_scope: this.knowledgeScopeOverride() || this.activeKnowledgeScope(),
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
    const scope = this.workspace.captureRequestScope();
    const generation = this.chatWorkspaceGeneration;
    let attempts = 0;
    const maxAttempts = 20;
    const tick = (): void => {
      if (!this.isChatContinuationCurrent(scope, generation)) return;
      if (attempts >= maxAttempts) return;
      attempts += 1;
      const subscription = this.canonicalApi.getEvaluationByRun(
        runId,
        { workspaceSlug: scope.workspaceSlug },
      ).subscribe({
        next: (res) => {
          if (!this.isChatContinuationCurrent(scope, generation)) return;
          if (!res) return; // network hiccup — stop quietly
          if (['pending', 'queued', 'running'].includes(res.status)) {
            this.scheduleChatPoll(tick, 1500, scope, generation);
            return;
          }
          this.messages.update(messages => messages.map(message => message.runId === runId ? {...message, evaluationStatus: res.status} : message));
          if (res.status === 'skipped') return;
          if (res.status === 'completed' && res.breach) {
            this.showBreachToast(res);
          }
        },
        error: () => {
          if (!this.isChatContinuationCurrent(scope, generation)) return;
          // Stop polling on hard error — transient 5xx will be
          // retried by the next chat turn's polling loop.
        },
      });
      this.chatWorkspaceSubscriptions.add(subscription);
    };
    this.scheduleChatPoll(tick, 1500, scope, generation);
  }

  private startHitlMessagePolling(runId: string): void {
    const sessionId = this.chatSessionId;
    if (!sessionId || !runId) return;
    const scope = this.workspace.captureRequestScope();
    const generation = this.chatWorkspaceGeneration;
    const pollKey = `${sessionId}:${runId}`;
    const isCurrent = (): boolean =>
      this.isChatContinuationCurrent(scope, generation)
      && this.chatSessionId === sessionId;
    if (!isCurrent() || this.activeHitlMessagePolls.has(pollKey)) return;
    this.activeHitlMessagePolls.add(pollKey);
    const finish = (): void => {
      this.activeHitlMessagePolls.delete(pollKey);
    };
    let attempts = 0;
    const maxAttempts = 200; // 10 minutes at 3s: leave time for a human review.
    const tick = (): void => {
      if (!isCurrent() || attempts >= maxAttempts) {
        finish();
        return;
      }
      attempts += 1;
      const subscription = this.api.get<ChatSessionDetail>(
        `/sessions/${encodeURIComponent(sessionId)}?include_messages=true`,
        undefined,
        { workspaceSlug: scope.workspaceSlug },
      ).subscribe({
        next: (detail) => {
          if (!isCurrent()) {
            finish();
            return;
          }
          const stored = (detail.messages || []).find((message) => {
            const meta = message.meta_data || {};
            return message.role === 'assistant'
              && meta['run_id'] === runId
              && meta['resumed_after_hitl'] === true;
          });
          if (!stored) {
            this.scheduleChatPoll(tick, 3000, scope, generation);
            return;
          }
          const refreshed = this.chatMessageFromStored(stored);
          this.messages.update((messages) => messages.map((message) =>
            message.runId === runId
              ? {
                  ...message,
                  content: refreshed.content,
                  sources: refreshed.sources,
                  retrievalInfo: refreshed.retrievalInfo,
                }
              : message
          ));
          finish();
          const hitlDecision = (stored.meta_data || {})['hitl_decision'];
          if (hitlDecision !== 'rejected') this.startEvalPolling(runId);
        },
        error: () => {
          if (!isCurrent()) {
            finish();
            return;
          }
          this.scheduleChatPoll(tick, 3000, scope, generation);
        },
      });
      this.chatWorkspaceSubscriptions.add(subscription);
    };
    this.scheduleChatPoll(tick, 1500, scope, generation);
  }

  private startDeepRetrievalPolling(messageId: string, jobId: string, pollUrl?: string | null): void {
    const scope = this.workspace.captureRequestScope();
    const generation = this.chatWorkspaceGeneration;
    if (this.activeDeepRetrievalPolls.has(jobId)) return;
    this.activeDeepRetrievalPolls.add(jobId);
    let attempts = 0;
    const maxAttempts = 60;
    const updateStatus = (
      status: string,
      summary?: NonNullable<ChatMessage['retrievalInfo']>['deepSummary'],
      progress?: number | null,
      stage?: string | null,
      sources?: Source[],
      answer?: { text?: string | null; status?: string | null; model?: string | null },
      decisionTrace?: RetrievalDecisionTrace | null,
    ): void => {
      if (!this.isChatContinuationCurrent(scope, generation)) return;
      const promotedAnswer = answer?.text?.trim();
      const shouldPromoteAnswer =
        !!promotedAnswer && (status === 'completed' || status === 'failed' || status === 'cancelled');
      this.messages.update((messages) =>
        messages.map((msg) => {
          if (msg.id !== messageId || !msg.retrievalInfo) return msg;
          return {
            ...msg,
            content: shouldPromoteAnswer ? promotedAnswer : msg.content,
            sources: shouldPromoteAnswer && sources?.length ? sources : msg.sources,
            retrievalInfo: {
              ...msg.retrievalInfo,
              deepStatus: status,
              deepProgress: progress ?? msg.retrievalInfo.deepProgress ?? null,
              deepStage: stage ?? msg.retrievalInfo.deepStage ?? null,
              deepSummary: summary ?? msg.retrievalInfo.deepSummary ?? null,
              deepSources: sources?.length ? sources : msg.retrievalInfo.deepSources,
              deepAnswer: answer?.text ?? msg.retrievalInfo.deepAnswer ?? null,
              deepAnswerStatus: answer?.status ?? msg.retrievalInfo.deepAnswerStatus ?? null,
              deepAnswerModel: answer?.model ?? msg.retrievalInfo.deepAnswerModel ?? null,
              decisionTrace: decisionTrace ?? msg.retrievalInfo.decisionTrace ?? null,
            },
          };
        }),
      );
    };
    const parseAnswer = (job: { result?: unknown }): { text?: string | null; status?: string | null; model?: string | null } => {
      const result = job.result;
      if (!this.isRecord(result)) return {};
      const text = typeof result['answer'] === 'string' ? (result['answer'] as string).trim() : '';
      const status = typeof result['answer_status'] === 'string' ? (result['answer_status'] as string) : null;
      const provider = typeof result['answer_provider'] === 'string' ? (result['answer_provider'] as string) : null;
      const model = typeof result['answer_model'] === 'string' ? (result['answer_model'] as string) : null;
      const modelLabel = provider && model ? `${provider}/${model}` : model;
      return { text: text || null, status, model: modelLabel };
    };
    const parseSummary = (job: { result?: unknown }): NonNullable<ChatMessage['retrievalInfo']>['deepSummary'] => {
      const result = job.result;
      if (!this.isRecord(result)) return null;
      const partialResult = this.isRecord(result['partial_result'])
        ? (result['partial_result'] as Record<string, unknown>)
        : null;
      if (!this.isRecord(result['summary'])) {
        const retrievalSummary = partialResult && this.isRecord(partialResult['retrieval_summary'])
          ? (partialResult['retrieval_summary'] as Record<string, unknown>)
          : null;
        if (!retrievalSummary) return null;
        return {
          chunksRetrieved:
            typeof retrievalSummary['chunks_retrieved'] === 'number'
              ? (retrievalSummary['chunks_retrieved'] as number)
              : null,
          sourcesReturned: null,
          topScore: null,
          pipeline: typeof retrievalSummary['dense_policy'] === 'string'
            ? (retrievalSummary['dense_policy'] as string)
            : null,
          partial: false,
          fallbackReason:
            typeof retrievalSummary['fallback_reason'] === 'string'
              ? (retrievalSummary['fallback_reason'] as string)
              : null,
          topSources: [],
        };
      }
      const summary = result['summary'];
      const topSourcesRaw = Array.isArray(summary['top_sources']) ? summary['top_sources'] : [];
      return {
        chunksRetrieved:
          typeof summary['chunks_retrieved'] === 'number' ? (summary['chunks_retrieved'] as number) : null,
        sourcesReturned:
          typeof summary['sources_returned'] === 'number' ? (summary['sources_returned'] as number) : null,
        topScore: typeof summary['top_score'] === 'number' ? (summary['top_score'] as number) : null,
        pipeline: typeof summary['pipeline'] === 'string' ? (summary['pipeline'] as string) : null,
        partial: summary['partial'] === true || result['status'] === 'completed_partial' || result['stage'] === 'deep_timeout',
        fallbackReason:
          typeof summary['fallback_reason'] === 'string'
            ? (summary['fallback_reason'] as string)
            : null,
        topSources: topSourcesRaw
          .filter((source): source is Record<string, unknown> => this.isRecord(source))
          .map((source) => ({
            label: typeof source['label'] === 'string' ? (source['label'] as string) : null,
            chunks: typeof source['chunks'] === 'number' ? (source['chunks'] as number) : null,
          })),
      };
    };
    const parseDecisionTrace = (job: { result?: unknown }): RetrievalDecisionTrace | null => {
      const result = job.result;
      if (!this.isRecord(result)) return null;
      return (
        this.parseRetrievalDecisionTrace(result['retrieval_decision_trace'])
        ?? this.parseRetrievalDecisionTrace(this.isRecord(result['summary'])
          ? (result['summary'] as Record<string, unknown>)['retrieval_decision_trace']
          : null)
      );
    };
    const jobPath = pollUrl && (pollUrl.startsWith('/workspace-jobs/') || pollUrl.startsWith('/documents/jobs/'))
      ? pollUrl
      : `/workspace-jobs/${encodeURIComponent(jobId)}`;
    const tick = (): void => {
      if (!this.isChatContinuationCurrent(scope, generation)) {
        this.activeDeepRetrievalPolls.delete(jobId);
        return;
      }
      if (attempts >= maxAttempts) {
        this.activeDeepRetrievalPolls.delete(jobId);
        updateStatus('running', undefined, null, 'poll_window_elapsed');
        return;
      }
      attempts += 1;
      const subscription = this.api.get<{
        status?: string;
        progress?: number;
        stage?: string | null;
        result?: unknown;
      }>(jobPath, undefined, { workspaceSlug: scope.workspaceSlug }).subscribe({
        next: (job) => {
          if (!this.isChatContinuationCurrent(scope, generation)) return;
          const status = String(job?.status || 'queued');
          const progress = typeof job?.progress === 'number' ? job.progress : null;
          const stage = typeof job?.stage === 'string' ? job.stage : null;
          updateStatus(status, parseSummary(job), progress, stage, this.deepSourcesFromJob(job), parseAnswer(job), parseDecisionTrace(job));
          if (status === 'queued' || status === 'running') {
            this.scheduleChatPoll(tick, 2000, scope, generation);
          } else {
            this.activeDeepRetrievalPolls.delete(jobId);
          }
        },
        error: () => {
          if (!this.isChatContinuationCurrent(scope, generation)) return;
          updateStatus('failed', undefined, null, 'poll_failed');
          this.activeDeepRetrievalPolls.delete(jobId);
        },
      });
      this.chatWorkspaceSubscriptions.add(subscription);
    };
    this.scheduleChatPoll(tick, 2000, scope, generation);
  }

  private showBreachToast(res: {
    composite_score?: number | null;
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
      const title = this.i18n.t('chat.qa.flagged_title');
      const scoreLabel = score != null ? `${score}` : '—';
      const msg = metricList
        ? this.i18n.t('chat.qa.flagged_breaches', { score: scoreLabel, metrics: metricList })
        : this.i18n.t('chat.qa.flagged_review', { score: scoreLabel });
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
    return this.i18n.t('chat.qa.review_tooltip');
  }

  /** Navigate to the detailed QA review for a flagged reply (opt-in). */
  openQaReview(decisionId: string | null | undefined, runId: string): void {
    // Deeplink priority: if the breach already produced a Decision row we jump
    // to the review queue (so the reviewer can accept/reject inline);
    // otherwise we fall back to the Run inspector for raw context.
    if (decisionId) {
      const tree = this.router.parseUrl(this.navigation.surfaceUrl('review-queue'));
      tree.queryParams = { ...tree.queryParams, decision: decisionId };
      void this.router.navigateByUrl(tree);
    } else {
      void this.router.navigateByUrl(this.navigation.objectUrl('run', runId));
    }
  }

  rate(msg: ChatMessage, verdict: 'up' | 'down'): void {
    this.messages.update((msgs) =>
      msgs.map((m) => (m.id === msg.id ? { ...m, feedback: verdict } : m)),
    );
    this.toast.success(
      verdict === 'up'
        ? this.i18n.t('chat.feedback.helpful')
        : this.i18n.t('chat.feedback.recorded'),
      this.i18n.t('chat.correction.thanks'),
    );
    this.logAudit('chat_feedback', {
      message_id: msg.id,
      agent_id: this.systemId(),
      verdict,
    });
  }

  copy(text: string): void {
    navigator.clipboard
      .writeText(text)
      .then(() => this.toast.info(this.i18n.t('chat.toast.copied')))
      .catch(() => this.toast.error(this.i18n.t('chat.toast.copy_failed')));
  }

  // --- Inline expert correction ("Corriger / Compléter") -------------------

  /** Short reminder of the question the assistant answered, shown above the
   * composer so the expert keeps the context in view. */
  correctionQuestionFor(msg: ChatMessage): string {
    return this.previousUserQueryFor(msg.id) || '';
  }

  /** Persistent trace of a submitted correction for an assistant message, or
   * null when none has been sent in this session view. */
  correctionTraceFor(id: string): {
    correction: string;
    usedVoice: boolean;
    proposalId: string | null;
    reviewQueueUrl: string | null;
    status: 'published' | 'pending_review';
    at: number;
  } | null {
    return this.correctionTraces()[id] ?? null;
  }

  /** Toggle the inline correction composer for a given assistant message. Only
   * one composer is open at a time. */
  toggleCorrection(msg: ChatMessage): void {
    if (this.correctionOpenFor() === msg.id) {
      this.closeCorrection();
      return;
    }
    this.releaseCorrectionRecorder();
    this.correctionText.set('');
    this.correctionTranscriptRaw = null;
    this.correctionAudioBlob = null;
    this.correctionUsedVoice.set(false);
    this.correctionMicState.set('idle');
    this.correctionSubmitting.set(false);
    this.correctionOpenFor.set(msg.id);
  }

  closeCorrection(): void {
    this.releaseCorrectionRecorder();
    this.correctionOpenFor.set(null);
    this.correctionText.set('');
    this.correctionTranscriptRaw = null;
    this.correctionAudioBlob = null;
    this.correctionUsedVoice.set(false);
    this.correctionMicState.set('idle');
    this.correctionSubmitting.set(false);
  }

  /** Push-to-talk toggle: start recording when idle/ready, stop (and transcribe)
   * while recording. A no-op while a transcription is already in flight. */
  async toggleCorrectionMic(): Promise<void> {
    const state = this.correctionMicState();
    if (state === 'recording') {
      this.stopCorrectionRecording();
      return;
    }
    if (state === 'transcribing') return;
    await this.startCorrectionRecording();
  }

  private async startCorrectionRecording(): Promise<void> {
    if (typeof MediaRecorder === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      this.toast.error(this.i18n.t('chat.correction.mic_unsupported'), this.i18n.t('chat.correction.dictation'));
      return;
    }
    try {
      this.correctionStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      this.correctionMicState.set('idle');
      this.toast.error(this.i18n.t('chat.correction.mic_denied'), this.i18n.t('chat.correction.dictation'));
      this.cdr.markForCheck();
      return;
    }
    this.correctionChunks = [];
    let recorder: MediaRecorder;
    try {
      recorder = MediaRecorder.isTypeSupported('audio/webm')
        ? new MediaRecorder(this.correctionStream, { mimeType: 'audio/webm' })
        : new MediaRecorder(this.correctionStream);
    } catch {
      recorder = new MediaRecorder(this.correctionStream);
    }
    this.correctionRecorder = recorder;
    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) this.correctionChunks.push(event.data);
    };
    recorder.onstop = () => this.transcribeCorrectionRecording();
    recorder.start();
    this.correctionMicState.set('recording');
    // Best-effort live preview while recording (server transcript is authoritative).
    this.startCorrectionSpeech();
    this.cdr.markForCheck();
  }

  /**
   * Start the browser SpeechRecognition engine (when available) purely for a
   * live, in-place transcript preview. It runs alongside MediaRecorder and is a
   * no-op on unsupported browsers — the server transcription remains the source
   * of truth on stop.
   */
  private startCorrectionSpeech(): void {
    this.correctionSpeechFinal = '';
    this.correctionLiveTranscript.set('');
    const SR =
      (window as unknown as { SpeechRecognition?: new () => any; webkitSpeechRecognition?: new () => any })
        .SpeechRecognition ||
      (window as unknown as { webkitSpeechRecognition?: new () => any }).webkitSpeechRecognition;
    if (!SR) return;
    let recognition: any;
    try {
      recognition = new SR();
    } catch {
      return;
    }
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = 'fr-FR';
    recognition.onresult = (event: any) => {
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        const transcript = result[0]?.transcript ?? '';
        if (result.isFinal) {
          this.correctionSpeechFinal = `${this.correctionSpeechFinal} ${transcript}`.trim();
        } else {
          interim += transcript;
        }
      }
      const live = `${this.correctionSpeechFinal} ${interim}`.trim();
      this.correctionLiveTranscript.set(live);
      this.cdr.markForCheck();
    };
    recognition.onerror = () => {
      /* best-effort preview: ignore (mic/server transcript still handle it) */
    };
    recognition.onend = () => {
      /* engine may auto-stop; we don't restart — recording continues regardless */
    };
    try {
      recognition.start();
      this.correctionSpeech = recognition;
    } catch {
      this.correctionSpeech = null;
    }
  }

  private stopCorrectionSpeech(): void {
    const recognition = this.correctionSpeech;
    this.correctionSpeech = null;
    if (!recognition) return;
    recognition.onresult = null;
    recognition.onerror = null;
    recognition.onend = null;
    try {
      recognition.stop?.();
    } catch {
      try {
        recognition.abort?.();
      } catch {
        /* already stopped */
      }
    }
  }

  private stopCorrectionRecording(): void {
    const recorder = this.correctionRecorder;
    if (!recorder) return;
    this.stopCorrectionSpeech();
    this.correctionMicState.set('transcribing');
    this.cdr.markForCheck();
    try {
      if (recorder.state !== 'inactive') {
        recorder.stop();
      } else {
        this.transcribeCorrectionRecording();
      }
    } catch {
      this.transcribeCorrectionRecording();
    }
  }

  private transcribeCorrectionRecording(): void {
    this.releaseCorrectionStream();
    this.stopCorrectionSpeech();
    this.correctionRecorder = null;
    const chunks = this.correctionChunks;
    this.correctionChunks = [];
    // Live preview captured while speaking — used as a fallback if the server
    // transcript is empty or fails so dictated words are never silently lost.
    const livePreview = (this.correctionSpeechFinal || this.correctionLiveTranscript()).trim();
    if (!chunks.length) {
      if (livePreview) {
        this.applyCorrectionTranscript(livePreview);
        this.correctionLiveTranscript.set('');
        this.cdr.markForCheck();
        return;
      }
      this.correctionMicState.set('idle');
      this.correctionLiveTranscript.set('');
      this.toast.warning(this.i18n.t('chat.correction.no_sound'), this.i18n.t('chat.correction.dictation'));
      this.cdr.markForCheck();
      return;
    }
    const blob = new Blob(chunks, { type: 'audio/webm' });
    // Keep the recording so the dictation audio can be persisted for audit when
    // the expert submits (the backend stores it and derives an audio_ref).
    this.correctionAudioBlob = blob;
    this.correctionMicState.set('transcribing');
    this.api
      .transcribeAudio(blob, 'chat-correction.webm')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          const text = (res?.text || '').trim();
          if (text) {
            // Keep the raw transcript verbatim for audit; the expert edits the
            // textarea copy before submitting.
            this.applyCorrectionTranscript(text);
          } else if (livePreview) {
            // Server returned nothing usable — keep the live preview rather than
            // discarding what the expert dictated.
            this.applyCorrectionTranscript(livePreview);
          } else {
            this.correctionMicState.set('idle');
            this.toast.warning(this.i18n.t('chat.correction.empty_transcript'), this.i18n.t('chat.correction.dictation'));
          }
          this.correctionLiveTranscript.set('');
          this.cdr.markForCheck();
        },
        error: () => {
          // Clean degradation: fall back to the in-browser live transcript when
          // present, otherwise keep the textarea usable for manual typing.
          if (livePreview) {
            this.applyCorrectionTranscript(livePreview);
            this.toast.info(this.i18n.t('chat.correction.local_transcript'), this.i18n.t('chat.correction.dictation'));
          } else {
            this.correctionMicState.set('idle');
            this.toast.error(this.i18n.t('chat.correction.transcript_failed'), this.i18n.t('chat.correction.dictation'));
          }
          this.correctionLiveTranscript.set('');
          this.cdr.markForCheck();
        },
      });
  }

  /** Append a transcript to the composer textarea, marking the voice path used. */
  private applyCorrectionTranscript(text: string): void {
    this.correctionTranscriptRaw = text;
    this.correctionUsedVoice.set(true);
    const existing = this.correctionText().trim();
    this.correctionText.set(existing ? `${existing} ${text}` : text);
    this.correctionMicState.set('ready');
  }

  private releaseCorrectionStream(): void {
    this.correctionStream?.getTracks().forEach((track) => track.stop());
    this.correctionStream = null;
  }

  private releaseCorrectionRecorder(): void {
    const recorder = this.correctionRecorder;
    if (recorder) {
      recorder.ondataavailable = null;
      recorder.onstop = null;
      try {
        if (recorder.state !== 'inactive') recorder.stop();
      } catch {
        /* recorder already stopped */
      }
    }
    this.correctionRecorder = null;
    this.correctionChunks = [];
    this.stopCorrectionSpeech();
    this.correctionSpeechFinal = '';
    this.correctionLiveTranscript.set('');
    this.releaseCorrectionStream();
  }

  async submitCorrection(msg: ChatMessage): Promise<void> {
    if (this.correctionSubmitting()) return;
    const micState = this.correctionMicState();
    if (micState === 'recording' || micState === 'transcribing') return;
    const correction = this.correctionText().trim();
    if (!correction) {
      this.toast.warning(this.i18n.t('chat.correction.text_required'), this.i18n.t('chat.correction.title'));
      return;
    }
    const usedVoice = this.correctionUsedVoice() && !!this.correctionTranscriptRaw;
    const query = this.previousUserQueryFor(msg.id) || '';
    const sessionId = this.activeChatSessionId();
    this.correctionSubmitting.set(true);
    // When dictated, ship the raw audio (base64) so the backend persists it for
    // audit/replay (it derives the audio_ref). Failure to encode is non-fatal —
    // the correction still goes through with the transcript only.
    let audioBase64: string | null = null;
    let audioContentType: string | null = null;
    if (usedVoice && this.correctionAudioBlob) {
      try {
        audioBase64 = await this.blobToBase64(this.correctionAudioBlob);
        audioContentType = this.correctionAudioBlob.type || 'audio/webm';
      } catch {
        audioBase64 = null;
        audioContentType = null;
      }
    }
    this.api
      .submitChatCorrection({
        query,
        answer: msg.content,
        correction,
        message_id: msg.id,
        session_id: sessionId,
        sources: msg.sources ?? [],
        transcript_raw: usedVoice ? this.correctionTranscriptRaw : null,
        audio_base64: audioBase64,
        audio_content_type: audioContentType,
        input_modality: usedVoice ? 'voice' : 'text',
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.correctionSubmitting.set(false);
          this.logAudit('chat_correction_submitted', {
            message_id: msg.id,
            agent_id: this.systemId(),
            session_id: sessionId,
            input_modality: usedVoice ? 'voice' : 'text',
            proposal_id: res?.proposal_id ?? null,
          });
          const url = res?.review_queue_url || null;
          // When the workspace has expert review disabled, the backend
          // auto-accepts and publishes the fiche immediately and reports
          // ``status: "published"``. Otherwise we keep the legacy review-queue
          // wording. Anything unexpected degrades to the safe review wording.
          const published = res?.status === 'published';
          const status: 'published' | 'pending_review' = published ? 'published' : 'pending_review';
          // Persist a visible trace under the message so the expert keeps a
          // record of what was corrected even after the composer collapses.
          this.correctionTraces.update((traces) => ({
            ...traces,
            [msg.id]: {
              correction,
              usedVoice,
              proposalId: res?.proposal_id ?? null,
              reviewQueueUrl: url,
              status,
              at: Date.now(),
            },
          }));
          const toastRef: ActiveToast<unknown> = published
            ? this.toast.success(
                this.i18n.t('chat.correction.published'),
                this.i18n.t('chat.correction.thanks'),
                { closeButton: true, tapToDismiss: true },
              )
            : this.toast.success(
                url
                  ? this.i18n.t('chat.correction.sent_tap')
                  : this.i18n.t('chat.correction.sent'),
                this.i18n.t('chat.correction.thanks'),
                { closeButton: true, tapToDismiss: !url },
              );
          if (!published && url) {
            toastRef.onTap.subscribe(() => this.openReviewQueue(url));
          }
          // Conversational acknowledgement: drop a sober assistant bubble into
          // the thread (and never touch the original corrected answer). Only
          // when the backend handed us a ready-to-show sentence.
          const ack = (res?.acknowledgement ?? '').trim();
          if (ack) {
            const ackMsg: ChatMessage = {
              id: res?.ack_message_id || cryptoId(),
              role: 'assistant',
              content: ack,
              kind: 'correction_ack',
            };
            this.messages.update((list) => [...list, ackMsg]);
          }
          this.closeCorrection();
          this.cdr.markForCheck();
        },
        error: (err) => {
          this.correctionSubmitting.set(false);
          if (err?.status === 403) {
            // Feature disabled for the workspace / caller not permitted: degrade
            // gracefully by collapsing the composer and informing the expert.
            this.toast.info(
              this.i18n.t('chat.correction.disabled'),
              this.i18n.t('chat.correction.title'),
            );
            this.closeCorrection();
            this.cdr.markForCheck();
            return;
          }
          this.toast.error(
            err?.error?.detail ?? this.i18n.t('chat.correction.send_failed'),
            this.i18n.t('chat.correction.title'),
          );
          this.cdr.markForCheck();
        },
      });
  }

  openReviewQueue(url: string | null): void {
    // Absolute external URL: open in a new tab. Otherwise route to the in-app
    // Knowledge Capture workbench (the backend's `review_queue_url` is an API
    // path, not an Angular route, so we never navigate the SPA to it).
    if (url && /^https?:\/\//i.test(url)) {
      window.open(url, '_blank', 'noopener');
      return;
    }
    if (url && url.startsWith('/') && !url.startsWith('/api/')) {
      void this.router.navigateByUrl(url);
      return;
    }
    void this.router.navigateByUrl(this.navigation.surfaceUrl('knowledge-capture'));
  }

  /** Encode a Blob as a base64 string (without the ``data:`` URL prefix). */
  private blobToBase64(blob: Blob): Promise<string> {
    return new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(reader.error ?? new Error('blob read failed'));
      reader.onload = () => {
        const result = typeof reader.result === 'string' ? reader.result : '';
        const comma = result.indexOf(',');
        resolve(comma >= 0 ? result.slice(comma + 1) : result);
      };
      reader.readAsDataURL(blob);
    });
  }

  factCheck(msg: ChatMessage): void {
    if (this.evaluatingId()) return;
    const user = this.lastUserMessageBefore(msg.id);
    if (!user) {
      this.toast.warning(this.i18n.t('chat.audit.no_query'));
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
            this.i18n.t('chat.audit.fact_check_score', {
              score: Number(res?.composite_score ?? 0).toFixed(1),
            }),
            this.i18n.t('chat.audit.fact_check'),
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
          this.toast.error(
            err?.error?.detail ?? this.i18n.t('chat.audit.evaluation_failed'),
            this.i18n.t('chat.audit.fact_check'),
          );
          this.evaluatingId.set(null);
        },
      });
  }

  toggleTTS(): void {
    const next = !this.ttsEnabled();
    if (next && !this.voiceOutputProvider()) {
      this.toast.error(
        this.isDemoMode()
          ? this.i18n.t('chat.voice.tts_cannot_demo')
          : this.i18n.t('chat.voice.tts_cannot'),
        this.i18n.t('chat.voice.title'),
      );
      return;
    }
    this.ttsEnabled.set(next);
    this.toast.info(
      next
        ? this.voiceRuntimeNotice(this.i18n.t('chat.voice.output_enabled'), this.voiceOutputProvider())
        : this.i18n.t('chat.voice.output_disabled'),
    );
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
    this.voiceNotice.set(this.i18n.t('chat.voice.playback_cut'));
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
    return this.resolvedVoiceCaptureConfig().silence_ms;
  }

  private voiceEndpointMinSpeechMs(): number {
    return this.resolvedVoiceCaptureConfig().min_speech_ms;
  }

  private voiceEndpointMaxTurnMs(): number {
    return this.resolvedVoiceCaptureConfig().max_turn_ms;
  }

  private voiceEndpointRmsThreshold(): number {
    return this.resolvedVoiceCaptureConfig().rms_threshold;
  }

  private voiceEndpointGraceMs(): number {
    return this.resolvedVoiceCaptureConfig().endpoint_grace_ms;
  }

  private voiceVadHangoverMs(): number {
    return this.resolvedVoiceCaptureConfig().vad_hangover_ms;
  }

  private voiceVadCalibrationMs(): number {
    return this.resolvedVoiceCaptureConfig().vad_calibration_ms;
  }

  private voiceVadMinSilenceFramesMs(): number {
    return this.resolvedVoiceCaptureConfig().vad_min_silence_frames_ms;
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

  voiceCaptureModeHint(): string {
    const config = this.resolvedVoiceCaptureConfig();
    if (config.capture_mode === 'manual_safe') return this.i18n.t('chat.voice.capture_manual');
    if (config.capture_mode === 'robust') {
      return this.i18n.t('chat.voice.capture_robust', {
        silence: config.silence_ms,
        speech: config.min_speech_ms,
      });
    }
    return this.i18n.t('chat.voice.capture_normal');
  }

  setVoiceCaptureMode(mode: VoiceCaptureMode | string): void {
    const next = normalizeVoiceCaptureMode(mode);
    this.voiceCaptureMode.set(next);
    try {
      const workspaceSlug = this.workspace.current()?.slug || 'workspace';
      const profileKey = this.activeAssistantProfile()?.key || this.assistantProfileKey() || 'default';
      localStorage.setItem(voiceCaptureStorageKey({ surface: 'chat', workspaceSlug, profileKey }), next);
    } catch {
      /* local preference only */
    }
    if (!this.voiceConversationActive() && !this.recording() && !this.transcribing()) {
      this.applyWorkspaceVoiceDefaults(this.workspaceVoiceLoopConfig(), this.canUseVoiceSession());
    }
    if (next === 'manual_safe' && this.recording()) {
      this.voiceLoop.disableAutoEndpoint();
      this.voiceNotice.set(this.i18n.t('chat.voice.capture_manual_enabled'));
    }
  }

  private readStoredVoiceCaptureMode(key: string, fallback: VoiceCaptureMode): VoiceCaptureMode {
    try {
      return normalizeVoiceCaptureMode(localStorage.getItem(key), fallback);
    } catch {
      return fallback;
    }
  }

  private emitVoiceClientMetric(payload: Record<string, unknown>): void {
    const config = this.resolvedVoiceCaptureConfig();
    const network = (navigator as Navigator & { connection?: { effectiveType?: string } }).connection;
    this.voiceConnection?.clientMetric({
      surface: 'chat',
      turn_id: this.voiceTurnId,
      capture_mode: config.capture_mode,
      auto_endpoint: config.auto_endpoint,
      silence_ms: config.silence_ms,
      min_speech_ms: config.min_speech_ms,
      endpoint_grace_ms: config.endpoint_grace_ms,
      visibility_state: document.visibilityState,
      network_effective_type: network?.effectiveType || '',
      ...payload,
    });
  }

  private async startVoiceTurn(fromConversationLoop: boolean): Promise<boolean> {
    if (!this.canTranscribeVoice()) {
      this.toast.error(
        this.isDemoMode()
          ? this.i18n.t('chat.voice.stt_cannot_demo')
          : this.i18n.t('chat.voice.stt_cannot'),
        this.i18n.t('chat.voice.title'),
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
        this.voiceNotice.set(this.i18n.t('chat.voice.output_stopped_listening'));
      }

      const captureConfig = this.resolvedVoiceCaptureConfig();
      const autoEndpoint = (fromConversationLoop || this.voiceAutoEndpoint()) && captureConfig.auto_endpoint;
      this.voiceConnection?.loopArmed({
        surface: 'chat',
        mode: fromConversationLoop ? 'conversation_loop' : 'manual_turn',
        auto_endpoint: autoEndpoint,
        capture_mode: captureConfig.capture_mode,
        silence_ms: captureConfig.silence_ms,
        min_speech_ms: captureConfig.min_speech_ms,
        rms_threshold: captureConfig.rms_threshold,
        endpoint_grace_ms: captureConfig.endpoint_grace_ms,
      });
      this.voiceOracleStage.set('listening');
      this.voiceOracleMessage.set(
        autoEndpoint
          ? captureConfig.capture_mode === 'robust'
            ? this.i18n.t('chat.voice.listening_robust')
            : this.i18n.t('chat.voice.listening_auto')
          : this.i18n.t('chat.voice.listening_manual'),
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
        captureMode: captureConfig.capture_mode,
        endpointGraceMs: this.voiceEndpointGraceMs(),
        vadHangoverMs: this.voiceVadHangoverMs(),
        vadCalibrationMs: this.voiceVadCalibrationMs(),
        vadMinSilenceFramesMs: this.voiceVadMinSilenceFramesMs(),
        onChunk: streamTurn
          ? (chunk) => this.onConversationVoiceChunk(chunk)
          : livePartialTurn
            ? (chunk) => this.onManualVoiceChunk(chunk)
            : undefined,
        onMetric: (payload) => this.emitVoiceClientMetric(payload),
        onState: (state) => this.syncVoiceLoopState(state),
        onSpeechStart: () => {
          this.voiceOracleStage.set('listening');
          this.voiceOracleMessage.set(this.i18n.t('chat.voice.speech_detected'));
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
            this.voiceNotice.set(this.i18n.t('chat.voice.no_speech_short'));
            this.voiceOracleStage.set('idle');
            this.voiceOracleMessage.set(this.i18n.t('chat.voice.no_turn_submitted'));
            this.scheduleVoiceLoopRearm();
            this.cdr.markForCheck();
            return;
          }
          this.voiceLastEndpointReason = reason;
          this.voiceNotice.set(this.voiceEndpointNotice(reason));
          this.voiceOracleStage.set('thinking');
          this.voiceOracleMessage.set(this.i18n.t('chat.voice.turn_ended_transcribing'));
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
          this.toast.error(message, this.i18n.t('chat.voice.title'));
        },
      });
      this.recording.set(started);
      if (!started && fromConversationLoop) this.stopConversationLoop('microphone_unavailable');
      return started;
    } catch {
      this.recording.set(false);
      this.toast.error(this.i18n.t('chat.voice.mic_denied'), this.i18n.t('chat.voice.title'));
      if (fromConversationLoop) this.stopConversationLoop('microphone_denied');
      return false;
    }
  }

  async startConversationLoop(): Promise<void> {
    if (!this.canUseVoiceSession()) {
      this.toast.error(
        this.isDemoMode()
          ? this.i18n.t('chat.voice.loop_unavailable')
          : this.i18n.t('chat.voice.session_unsupported'),
        this.i18n.t('chat.voice.title'),
      );
      return;
    }
    if (this.voiceConversationActive()) return;
    const config = this.workspaceVoiceLoopConfig();
    const captureConfig = this.resolvedVoiceCaptureConfig();
    this.setVoiceTransport('backend_ws');
    this.voiceAutoEndpoint.set(captureConfig.auto_endpoint);
    this.voiceAutoSend.set(config.auto_send_final_transcript !== false);
    if (this.voiceOutputProvider()) this.ttsEnabled.set(true);
    this.voiceConversationActive.set(true);
    this.voiceConversationPaused.set(false);
    const connection = this.ensureVoiceSession();
    connection?.loopStart({
      surface: 'chat',
      mode: 'conversation_loop',
      auto_endpoint: captureConfig.auto_endpoint,
      auto_rearm_after_tts: this.voiceLoopAutoRearmEnabled(),
      capture_mode: captureConfig.capture_mode,
      silence_ms: this.voiceEndpointSilenceMs(),
      min_speech_ms: this.voiceEndpointMinSpeechMs(),
      rms_threshold: this.voiceEndpointRmsThreshold(),
      endpoint_grace_ms: this.voiceEndpointGraceMs(),
      max_turn_ms: this.voiceEndpointMaxTurnMs(),
      barge_in: this.voiceLoopBargeInEnabled(),
    });
    this.voiceNotice.set(this.i18n.t('chat.voice.loop_starting'));
    this.voiceOracleStage.set('listening');
    this.voiceOracleMessage.set(this.i18n.t('chat.voice.loop_armed'));
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
    this.voiceNotice.set(this.i18n.t('chat.voice.conversation_paused'));
    this.voiceOracleStage.set('idle');
    this.voiceOracleMessage.set(this.i18n.t('chat.voice.loop_paused_msg'));
    this.cdr.markForCheck();
  }

  resumeConversationLoop(): void {
    if (!this.voiceConversationActive()) return;
    this.voiceConversationPaused.set(false);
    this.voiceConnection?.loopResume({ surface: 'chat' });
    this.voiceNotice.set(this.i18n.t('chat.voice.conversation_resuming'));
    this.voiceOracleMessage.set(this.i18n.t('chat.voice.loop_rearming'));
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
    this.voiceNotice.set(
      reason === 'user_stop'
        ? this.i18n.t('chat.voice.conversation_stopped')
        : this.i18n.t('chat.voice.conversation_stopped_reason', {
            reason: reason.replace(/_/g, ' '),
          }),
    );
    this.voiceOracleStage.set('idle');
    this.voiceOracleMessage.set(this.i18n.t('chat.voice.loop_stopped_msg'));
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
    this.voiceNotice.set(this.i18n.t('chat.voice.conversation_rearming'));
    this.voiceOracleMessage.set(this.i18n.t('chat.voice.answer_complete'));
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

  /**
   * WorkspaceService invokes this synchronously while A is still current.
   * Disarm callbacks and invalidate async continuations before B is published,
   * so recorder A can neither endpoint nor fall back to HTTP transcription in B.
   */
  private resetVoiceForWorkspaceChange(): void {
    this.voiceWorkspaceGeneration += 1;
    this.voiceConversationActive.set(false);
    this.voiceConversationPaused.set(false);
    this.clearVoiceLoopRearmTimer();
    this.voiceLoop.hardStop({
      disableRearm: () => this.clearVoiceLoopRearmTimer(),
      cancelTts: () => this.resetTtsPipeline(),
    });
    this.recording.set(false);
    this.transcribing.set(false);
    this.voicePartial.set('');
    this.voiceNotice.set(null);
    this.voiceOracleStage.set('idle');
    this.voiceOracleMessage.set(this.i18n.t('chat.voice.session_reset'));
    this.voiceLastEndpointReason = null;
    this.voiceTurnId = null;
    this.voiceTurnChunks = [];
    this.voiceTurnStreaming = false;
    this.voiceFramesStreamed = false;
    this.voicePartialInFlight = false;
    this.lastVoicePartialAt = 0;
    this.pendingVoiceFrameSends = [];
    this.closeVoiceSession();
  }

  private syncVoiceLoopState(state: VoiceLoopState): void {
    if (state === 'arming') {
      this.voiceNotice.set(this.i18n.t('chat.voice.arming_mic'));
      return;
    }
    if (state === 'listening') {
      this.voiceOracleStage.set('listening');
      return;
    }
    if (state === 'endpointing') {
      this.voiceOracleStage.set('thinking');
      this.voiceOracleMessage.set(this.i18n.t('chat.voice.endpoint_detected'));
      return;
    }
    if (state === 'transcribing' || state === 'thinking') {
      this.voiceOracleStage.set('thinking');
      return;
    }
    if (state === 'paused') {
      this.recording.set(false);
      this.voiceOracleStage.set('idle');
      this.voiceOracleMessage.set(this.i18n.t('chat.voice.loop_paused_short'));
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
    if (reason === 'silence') return this.i18n.t('chat.voice.endpoint.silence');
    if (reason === 'max_turn') return this.i18n.t('chat.voice.endpoint.max_turn');
    if (reason === 'no_speech') return this.i18n.t('chat.voice.no_speech_short');
    if (reason === 'pause') return this.i18n.t('chat.voice.endpoint.pause');
    if (reason === 'stop') return this.i18n.t('chat.voice.endpoint.stop');
    return this.i18n.t('chat.voice.endpoint.ended');
  }

  private handleFinalVoiceTranscript(
    rawText: string,
    options: { fallbackUsed?: boolean; provider?: string | null } = {},
  ): boolean {
    const text = rawText.trim();
    // The final transcript supersedes the live preview.
    this.voicePartial.set('');
    if (!text) {
      this.toast.info(this.i18n.t('chat.voice.no_speech_recording'), this.i18n.t('chat.voice.title'));
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
        this.toast.info(this.i18n.t('chat.voice.draft_replaced'), this.i18n.t('chat.voice.title'));
      }
      this.userInput = text;
    } else {
      this.userInput = this.userInput ? `${this.userInput} ${text}` : text;
    }
    this.voiceNotice.set(
      options.fallbackUsed
        ? this.voiceRuntimeNotice(this.i18n.t('chat.voice.transcript_ready_fallback'), options.provider || this.voiceInputProvider())
        : this.voiceRuntimeNotice(this.i18n.t('chat.voice.transcript_ready'), options.provider || this.voiceInputProvider()),
    );
    this.cdr.markForCheck();
    if (autoSendNow && this.userInput.trim()) {
      queueMicrotask(() => this.send());
    }
    return false;
  }

  private detectVoiceCommand(rawText: string): string | null {
    return detectSharedVoiceCommand(rawText, this.workspaceVoiceLoopConfig(), 'chat');
  }

  private handleVoiceCommand(command: string, transcript: string): boolean {
    this.voiceConnection?.voiceCommand(command, transcript, { surface: 'chat' });
    this.voicePartial.set('');
    this.transcribing.set(false);
    this.voiceOracleStage.set('committed');
    this.voiceOracleMessage.set(
      this.i18n.t('chat.voice.command_committed', { command: command.replace(/_/g, ' ') }),
    );

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
      this.voiceNotice.set(this.i18n.t('chat.voice.draft_cancelled'));
      this.scheduleVoiceLoopRearm();
      return true;
    }
    if (command === 'repeat') {
      const last = this.lastAssistantMessage();
      if (!last?.content?.trim()) {
        this.toast.info(this.i18n.t('chat.voice.no_answer_repeat'), this.i18n.t('chat.voice.title'));
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
        this.toast.info(this.i18n.t('chat.voice.no_answer_rephrase'), this.i18n.t('chat.voice.title'));
        this.scheduleVoiceLoopRearm();
        return true;
      }
      this.userInput = this.i18n.t('chat.voice.rephrase_prompt');
      if (!this.streaming()) queueMicrotask(() => this.send());
      return true;
    }
    if (command === 'next_question' || command === 'validate') {
      this.toast.info(this.i18n.t('chat.voice.command_capture_only'), this.i18n.t('chat.voice.title'));
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
    const generation = this.voiceWorkspaceGeneration;
    const provider = this.voiceInputProvider();
    this.voiceNotice.set(this.voiceRuntimeNotice(this.i18n.t('chat.voice.transcribing'), provider));
    this.api.transcribeAudio(blob, 'recording.webm', provider).subscribe({
      next: (res) => {
        if (generation !== this.voiceWorkspaceGeneration) return;
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
            ? this.voiceRuntimeNotice(this.i18n.t('chat.voice.fallback_used'), res.provider || provider)
            : this.voiceRuntimeNotice(this.i18n.t('chat.voice.transcript_ready'), res.provider || provider),
        );
        this.cdr.markForCheck();
      },
      error: (err) => {
        if (generation !== this.voiceWorkspaceGeneration) return;
        this.transcribing.set(false);
        this.voiceNotice.set(null);
        this.cdr.markForCheck();
        const detail = this.voiceErrorMessage(err, this.i18n.t('chat.voice.transcription_failed'));
        this.toast.error(detail, this.i18n.t('chat.voice.title'));
      },
    });
  }

	  private async transcribeViaVoiceSession(blob: Blob): Promise<void> {
	    const generation = this.voiceWorkspaceGeneration;
	    this.transcribing.set(true);
	    this.voicePartial.set('');
	    this.voiceNotice.set(this.voiceRuntimeNotice(this.i18n.t('chat.voice.session_notice'), this.voiceInputProvider()));
	    this.voiceOracleStage.set('thinking');
	    this.voiceOracleMessage.set(this.i18n.t('chat.voice.segment_sent'));
	    const connection = this.ensureVoiceSession();
    if (!connection) {
      this.voiceTransport.set('batch_http');
      this.transcribe(blob);
      return;
    }
    try {
      const turnId = crypto.randomUUID?.() || String(Date.now());
      await connection.sendAudioFrame(blob, { turn_id: turnId, content_type: blob.type || 'audio/webm' });
      if (generation !== this.voiceWorkspaceGeneration) return;
      connection.endpoint({
        turn_id: turnId,
        auto: this.voiceLastEndpointReason === 'silence' || this.voiceLastEndpointReason === 'max_turn',
        reason: this.voiceLastEndpointReason,
      });
      this.voiceLastEndpointReason = null;
    } catch (err) {
      if (generation !== this.voiceWorkspaceGeneration) return;
      this.transcribing.set(false);
      this.voiceNotice.set(null);
      this.toast.error(
        this.voiceErrorMessage(err, this.i18n.t('chat.voice.session_failed')),
        this.i18n.t('chat.voice.title'),
      );
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
    const generation = this.voiceWorkspaceGeneration;
    this.voiceTurnChunks.push(chunk);
    const connection = this.voiceConnection;
    if (connection) {
      const sendStartedAt = performance.now();
      const send = connection
        .sendAudioFrame(chunk, { turn_id: this.voiceTurnId, content_type: chunk.type || 'audio/webm' })
        .then(() => {
          if (generation !== this.voiceWorkspaceGeneration) return;
          this.voiceFramesStreamed = true;
          this.emitVoiceClientMetric({
            metric: 'send_audio_frame_ms',
            value_ms: Math.round(performance.now() - sendStartedAt),
            send_audio_frame_ms: Math.round(performance.now() - sendStartedAt),
            chunk_size: chunk.size,
          });
        })
        .catch(() => {
          if (generation !== this.voiceWorkspaceGeneration) return;
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
    const generation = this.voiceWorkspaceGeneration;
    this.transcribing.set(true);
    this.voiceOracleStage.set('thinking');
    this.voiceNotice.set(this.voiceRuntimeNotice(this.i18n.t('chat.voice.session_notice'), this.voiceInputProvider()));
    this.voiceOracleMessage.set(this.i18n.t('chat.voice.finalising_turn'));
    const connection = this.voiceConnection;
    if (!connection) {
      this.voiceTurnStreaming = false;
      this.transcribe(new Blob(this.voiceTurnChunks, { type: 'audio/webm' }));
      return;
    }
    const pending = [...this.pendingVoiceFrameSends];
    this.pendingVoiceFrameSends = [];
    if (pending.length) await Promise.allSettled(pending);
    if (generation !== this.voiceWorkspaceGeneration) return;
    const captureConfig = this.resolvedVoiceCaptureConfig();
    connection.endpoint({
      turn_id: this.voiceTurnId,
      auto: reason === 'silence' || reason === 'max_turn',
      reason,
      capture_mode: captureConfig.capture_mode,
      silence_ms: captureConfig.silence_ms,
      min_speech_ms: captureConfig.min_speech_ms,
      rms_threshold: captureConfig.rms_threshold,
      endpoint_grace_ms: captureConfig.endpoint_grace_ms,
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
	      this.voiceNotice.set(this.i18n.t('chat.voice.session_ready'));
	      this.voiceOracleMessage.set(this.i18n.t('chat.voice.channel_ready'));
	      return;
	    }
	    if (event.type === 'text.partial' || event.type === 'transcript.partial') {
	      // Server is the single source of truth for live partials: the gateway
	      // emits these mid-utterance from its server-side incremental STT.
	      const text = String(payload['text'] || '').trim();
	      if (text) this.voicePartial.set(text);
	      this.voiceOracleStage.set('thinking');
	      this.voiceOracleMessage.set(
	        text
	          ? this.i18n.t('chat.voice.transcript_received', {
	              text: `${text.slice(0, 90)}${text.length > 90 ? '…' : ''}`,
	            })
	          : this.i18n.t('chat.voice.transcript_received_updating'),
	      );
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
	      this.voiceNotice.set(
	        payload['fallback_used']
	          ? this.i18n.t('chat.voice.transcript_ready_fallback')
	          : this.i18n.t('chat.voice.transcript_ready'),
	      );
	      this.voiceOracleStage.set(payload['fallback_used'] ? 'fallback' : 'committed');
	      this.voiceOracleMessage.set(
	        payload['fallback_used']
	          ? this.i18n.t('chat.voice.transcript_fallback_done')
	          : this.i18n.t('chat.voice.transcript_committed'),
	      );
	      this.cdr.markForCheck();
	      return;
	    }
	    if (event.type === 'loop.start' || event.type === 'loop.resume' || event.type === 'loop.armed') {
	      this.voiceNotice.set(
	        event.type === 'loop.armed'
	          ? this.i18n.t('chat.voice.conversation_armed')
	          : this.i18n.t('chat.voice.loop_ready'),
	      );
	      return;
	    }
	    if (event.type === 'loop.pause' || event.type === 'loop.stop') {
	      this.voiceNotice.set(
	        event.type === 'loop.pause'
	          ? this.i18n.t('chat.voice.conversation_paused')
	          : this.i18n.t('chat.voice.conversation_stopped'),
	      );
	      return;
	    }
	    if (event.type === 'tts.started') {
	      this.voiceNotice.set(this.i18n.t('chat.voice.speaking'));
	      return;
	    }
	    if (event.type === 'tts.ended') {
	      this.voiceNotice.set(this.i18n.t('chat.voice.output_complete'));
	      this.scheduleVoiceLoopRearm();
	      return;
	    }
	    if (event.type === 'tts.interrupted') {
	      this.voiceNotice.set(this.i18n.t('chat.voice.output_interrupted'));
	      return;
	    }
	    if (event.type === 'voice.command') {
	      const command = String(payload['command'] || '').trim();
	      if (command) {
	        this.voiceNotice.set(
	          this.i18n.t('chat.voice.command', { command: command.replace(/_/g, ' ') }),
	        );
	      }
	      return;
	    }
	    if (event.type === 'runtime.metric') {
	      const provider = payload['provider'];
	      if (payload['metric'] === 'micro_turn') {
	        this.voiceNotice.set(this.i18n.t('chat.voice.oracle_micro_turns'));
	        this.voiceOracleStage.set('thinking');
	        this.voiceOracleMessage.set(this.i18n.t('chat.voice.micro_turn_tracked'));
	      } else if (provider) {
	        this.voiceNotice.set(this.voiceRuntimeNotice(this.i18n.t('chat.voice.session_notice'), String(provider)));
	      }
	      return;
	    }
	    if (event.type === 'oracle.delta') {
	      this.voiceNotice.set(this.i18n.t('chat.voice.oracle_updating'));
	      this.voiceOracleStage.set('thinking');
	      this.voiceOracleMessage.set(this.i18n.t('chat.voice.oracle_delta'));
	      return;
	    }
	    if (event.type === 'oracle.superseded') {
	      this.voiceNotice.set(this.i18n.t('chat.voice.oracle_refreshed'));
	      this.voiceOracleStage.set('superseded');
	      this.voiceOracleMessage.set(this.i18n.t('chat.voice.oracle_superseded_msg'));
	      return;
	    }
	    if (event.type === 'oracle.action') {
	      const action = String(payload['action'] || 'action').replace(/_/g, ' ');
	      this.voiceNotice.set(this.i18n.t('chat.voice.oracle_action', { action }));
	      this.voiceOracleStage.set('committed');
	      this.voiceOracleMessage.set(this.i18n.t('chat.voice.oracle_action_ready', { action }));
	      return;
	    }
	    if (event.type === 'oracle.commit') {
	      this.voiceNotice.set(this.i18n.t('chat.voice.oracle_committed'));
	      this.voiceOracleStage.set('committed');
	      this.voiceOracleMessage.set(this.i18n.t('chat.voice.oracle_committed_msg'));
	      return;
	    }
	    if (event.type === 'session.error') {
	      this.transcribing.set(false);
	      this.voicePartial.set('');
	      this.voiceNotice.set(null);
	      this.voiceOracleStage.set('error');
	      this.voiceOracleMessage.set(String(payload['message'] || this.i18n.t('chat.voice.session_failed_msg')));
	      this.toast.error(
	        String(payload['message'] || this.i18n.t('chat.voice.session_failed')),
	        this.i18n.t('chat.voice.title'),
	      );
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
        this.voiceNotice.set(this.i18n.t('chat.voice.speaking'));
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
    persistWorkspaceEvalContext(localStorage, this.workspace.currentSlug(), {
      agent_id: this.systemId(),
      query,
      response,
    });
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
