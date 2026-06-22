import { AfterViewInit, ChangeDetectionStrategy, Component, DestroyRef, ElementRef, OnInit, ViewChild, computed, effect, inject, signal, untracked } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { firstValueFrom, Subscription } from 'rxjs';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { ApiService, PublishedCaptureFiche } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { LiveKitConversationConnection, LiveKitConversationService } from '@app/core/livekit-conversation.service';
import { NavigationProfileService } from '@app/core/navigation-profile.service';
import { PermissionsService } from '@app/core/permissions.service';
import {
  ResolvedVoiceCaptureConfig,
  VoiceCaptureMode,
  normalizeVoiceCaptureMode,
  resolveVoiceCaptureConfig,
  voiceCaptureStorageKey,
} from '@app/core/voice-capture-config';
import { VoiceTtsPlaybackService, VoiceTtsState } from '@app/core/voice-tts-playback.service';
import { VoiceSessionConnection, VoiceSessionEvent, VoiceSessionService } from '@app/core/voice-session.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { DocumentPreviewComponent } from '@app/shared/document-preview/document-preview.component';
import { IconComponent } from '@app/shared/ui/icon.component';

type CaptureVoiceConnection = VoiceSessionConnection | LiveKitConversationConnection;

interface CaptureQuestion {
  id: string;
  question: string;
  prompt?: string;
  title?: string;
  topic_id?: string;
  subtopic_id?: string;
  path_label?: string;
  target_gap_id?: string;
  follow_ups?: string[];
  completion_criteria?: string[];
  estimated_minutes?: number;
}

interface CaptureSubtopic {
  id: string;
  title: string;
  prompt?: string;
  objective?: string;
  status?: string;
  target_gap_ids?: string[];
  knowledge_refs?: Array<Record<string, unknown>>;
  questions?: CaptureQuestion[];
}

interface CaptureHint {
  id: string;
  subtopic_id?: string;
  hint?: string;
  full_question?: string;
  priority?: number;
  source?: string;
  visibility?: string;
  kb_excerpt?: string;
}

interface CaptureTopic {
  id: string;
  title: string;
  prompt?: string;
  objective?: string;
  rationale?: string;
  status?: string;
  oracle_confidence?: number;
  estimated_minutes?: number;
  knowledge_refs?: Array<Record<string, unknown>>;
  subtopics?: CaptureSubtopic[];
}

// New capture-session contract: the oracle exposes its own working questions
// (NOT questions posed to the expert) and live retrieval chunks. The plan is a
// passive reminder; suggestions are non-blocking, dismissible hints.
interface OracleOpenQuestion {
  id?: string;
  text?: string;
  topic_id?: string;
  priority?: number;
  status?: string;
}

type OracleQuestionStatus = 'active' | 'open' | 'answered' | 'dismissed' | 'deferred';

interface CaptureLiveSuggestion {
  id: string;
  kind: string;
  text: string;
}

interface PlanOracleSnapshot {
  coverage_gaps?: Array<{ title?: string; description?: string; priority?: number; slug?: string }>;
  contradiction_candidates?: Array<{
    claim_expert?: string;
    claim_kb?: string;
    severity?: string;
    suggested_hint?: string;
    kb_excerpt?: string;
  }>;
  last_refreshed_at?: string;
}

interface CapturePlan {
  schema_version?: string;
  topics?: CaptureTopic[];
  questions?: CaptureQuestion[];
  question_bank_status?: 'idle' | 'generating' | 'ready' | string;
  oracle?: PlanOracleSnapshot;
  dialogue?: { turns?: Array<{ id: string; text: string }>; ready_to_finalize?: boolean; status?: string };
  review?: {
    status?: string;
    revision?: number;
    approved_at?: string | null;
    approved_by_user_id?: string | null;
    edited_at?: string | null;
    edited_by_user_id?: string | null;
  };
  [key: string]: unknown;
}

interface CaptureSession {
  id: string;
  capability_id?: string | null;
  context_id?: string | null;
  system_id?: string | null;
  created_by_user_id?: string | null;
  created_by_label?: string | null;
  voice_runtime?: string | null;
  title: string;
  objective: string;
  duration_minutes?: number | null;
  status: string;
  plan: CapturePlan;
  transcript?: Array<{ id: string; speaker: string; text: string }>;
  evaluations?: Array<{ verdict: string; score: number; follow_up?: string }>;
  metrics?: Record<string, number | string | boolean | null | undefined>;
  summary_short?: string | null;
  open_questions_count?: number | null;
  last_activity?: string | null;
  archived?: boolean;
  started_at?: string | null;
  completed_at?: string | null;
}

interface ContextOption {
  id: string;
  name: string;
  data_refs?: string[];
  environment_state?: { collection?: string; document_count?: number };
}

interface ContextCreationNotice {
  tone: 'success' | 'error' | 'info';
  text: string;
}

interface SystemOption {
  id: string;
  name: string;
  objective?: string | null;
  capability_id?: string | null;
  context_id?: string | null;
  flow_definition?: Record<string, unknown>;
}

interface TurnResponse {
  session: CaptureSession;
  next_prompt?: string | null;
  next_question_id?: string | null;
  system_prompt_event_id?: string | null;
  evaluation?: { verdict: string; score: number; follow_up?: string } | null;
}

interface CaptureEvent {
  id: string;
  event_type: string;
  parent_event_id?: string | null;
  speaker?: string | null;
  sequence: number;
  question_id?: string | null;
  text?: string | null;
  text_raw?: string | null;
  text_amended?: string | null;
  status: string;
  source: string;
  metadata?: Record<string, any>;
  created_at?: string | null;
}

type Voice2VoiceState =
  | 'idle'
  | 'listening'
  | 'partial_transcribing'
  | 'retrieving'
  | 'oracle_updating'
  | 'thinking'
  | 'speaking'
  | 'interrupted';

interface RetrievalPrefetch {
  event_id?: string;
  status: 'idle' | 'searching' | 'ready' | 'late' | 'timeout' | 'error' | 'completed' | 'completed_from_warm_cache' | 'ignored';
  latency_ms?: number;
  collection_name?: string;
  chunks: string[];
  scores: number[];
  metadatas: Record<string, any>[];
  hints?: CaptureHint[];
  active_subtopic_id?: string;
  active_topic_id?: string;
  active_section_confidence?: number;
  oracle_exact_match_count?: number;
  passive?: boolean;
  passive_reason?: string;
}

type ConversationMode = 'manual' | 'conversation_only';
type CapturePlanMode = 'ai_plan' | 'provided_plan' | 'free_conversation' | 'plan_build';
type CapturePlanSourceKind = 'manual' | 'pasted_text' | 'uploaded_file' | 'conversation';
type CaptureSurfaceView = 'dashboard' | 'prep' | 'plan' | 'plan_build' | 'session' | 'review' | 'publish';
type QualityTab = 'imprecisions' | 'contradictions' | 'open_questions';
type PlanOutlineFormatAction = 'indent' | 'outdent' | 'renumber' | 'move_up' | 'move_down';
type CaptureEndpointReason = 'manual' | 'silence' | 'max_turn' | 'no_speech' | 'stop' | 'voice_command' | 'error';

const HTTP_BATCH_PARTIAL_MAX_AUDIO_BYTES = 512 * 1024;
const HTTP_BATCH_PARTIAL_MIN_INTERVAL_MS = 1200;

interface WorkspaceVoiceLoopConfig {
  capture_mode?: VoiceCaptureMode | string | null;
  auto_capture_mode_enabled?: boolean;
  auto_endpoint?: boolean;
  auto_rearm_after_tts?: boolean;
  barge_in?: boolean;
  commands_enabled?: boolean;
  trigger_word?: string | null;
  command_packs?: string[];
  stop_phrases?: string[];
  silence_ms?: number;
  min_speech_ms?: number;
  dictation_silence_ms?: number;
  dictation_min_speech_ms?: number;
  max_turn_ms?: number;
  partial_stt_min_interval_ms?: number;
  partial_stt_max_audio_bytes?: number;
  live_partial_stt_enabled?: boolean;
  live_questions_enabled?: boolean;
  cooldown_ms?: number;
  rms_threshold?: number;
  endpoint_grace_ms?: number;
  vad_hangover_ms?: number;
  vad_calibration_ms?: number;
  vad_min_silence_frames_ms?: number;
}

interface QualityBacklogItem {
  id?: string;
  question_id?: string | null;
  label?: string;
  follow_up?: string;
  status?: string;
  deferred_reason?: string | null;
  severity?: string;
}
type ProposalFactDecision = 'pending' | 'accept' | 'reject';
type VoiceNoticeTone = 'info' | 'warning' | 'error';

interface PendingPlanSourceReplacement {
  file: File;
  filename: string;
  size: number;
}

interface CapturePlanSourceOutlineItem {
  title: string;
  subtopics: string[];
}

interface CapturePlanSourceSummary {
  kindLabel: string;
  title: string;
  stats: string;
  extractedOutline: CapturePlanSourceOutlineItem[];
  replacedExistingPlan: boolean;
}

interface ConversationStageRow {
  id: string;
  label: string;
  detail: string;
  icon: string;
  state: 'done' | 'active' | 'pending';
}

type RelanceKind = 'topic_close' | 'gap_question' | 'contradiction' | null;
type CaptureTranscriptStatus = 'live' | 'refined' | 'amended';

interface CaptureRelance {
  kind: RelanceKind;
  text: string | null;
}

interface TranscriptSegment {
  id: string;
  speaker: 'expert' | 'ia';
  text: string;
  status: CaptureTranscriptStatus;
  topicTitle?: string;
  relanceKind?: RelanceKind;
}

interface ConversationStepResponse {
  intent: string;
  confidence: number;
  action_taken: string;
  session: CaptureSession;
  proposal?: any | null;
  turn?: any | null;
  evaluation?: TurnResponse['evaluation'] | null;
  next_prompt?: string | null;
  next_question_id?: string | null;
  system_prompt_event_id?: string | null;
  relance?: CaptureRelance | null;
  requires_confirmation: boolean;
  confirmation_target?: string | null;
  closure_sheet?: {
    markdown?: string;
    topics?: string[];
    captured_facts?: unknown[];
    unresolved?: Array<{ bucket?: string; label?: string; status?: string }>;
  } | null;
}

/** Section-level KB source attached by the FINAL pass (chat-style display). */
interface CaptureReportSource {
  rank?: number;
  document_id?: string | null;
  source_id?: string | null;
  source?: string | null;
  title?: string | null;
  filename?: string | null;
  collection?: string | null;
  preview?: string | null;
}

interface CaptureReportStructureNode {
  topic_id?: string | null;
  subtopic_id?: string | null;
  title?: string | null;
  synthesis?: string | null;
  facts?: ProposalFact[];
  sources?: CaptureReportSource[];
  open_questions?: ProposalOpenQuestion[];
  subtopics?: CaptureReportStructureNode[];
}

/** Nested bullet in a section synthesis list. */
interface CaptureReportListItem {
  text: string;
  children: CaptureReportListItem[];
}

/** Parsed block of a section synthesis (markdown stored, structured render). */
interface CaptureReportBlock {
  kind: 'paragraph' | 'list' | 'heading';
  text?: string;
  items?: CaptureReportListItem[];
}

interface CaptureReportSubsectionCard {
  key: string;
  title: string;
  blocks: CaptureReportBlock[];
  facts: string[];
  sources: CaptureReportSource[];
  openQuestionLinks: CaptureReportOpenQuestionLink[];
}

/** Compact index entry in the fiche pointing to a sidebar management card. */
interface CaptureReportOpenQuestionLink {
  key: string;
  label: string;
  index: number;
}

interface CaptureReportSectionCard extends CaptureReportSubsectionCard {
  index: number;
  subsections: CaptureReportSubsectionCard[];
}

/** Honest FINAL-phase progress stage streamed by the gateway. */
interface CaptureFinalizeStage {
  stage: string;
  label: string;
  section_label?: string | null;
  current?: number | null;
  total?: number | null;
}

interface CapturePublicationResult {
  proposal_id?: string;
  collection?: string;
  document_id?: string;
  chunks_processed?: number;
  status?: string;
  category?: string;
  destination?: string;
  final_title?: string;
  export_urls?: { download_url?: string; raw_url?: string };
}

interface CaptureProposal {
  id: string;
  status: string;
  session_id?: string;
  created_by_user_id?: string | null;
  reviewer_user_id?: string | null;
  proposal?: {
    title?: string;
    objective?: string;
    captured_facts?: ProposalFact[];
    open_questions?: ProposalOpenQuestion[];
    recommended_ingestion?: { title?: string; content?: string; metadata?: Record<string, any> };
    report_markdown?: string;
    plan_structure?: { topics?: CaptureReportStructureNode[]; unassigned?: ProposalFact[] };
    publication?: {
      category?: string | null;
      destination?: string | null;
      destination_scope?: string | null;
      final_title?: string | null;
      include_unresolved_questions?: boolean;
      suggested?: boolean;
      document_id?: string | null;
      collection_slug?: string | null;
      chunks_processed?: number | null;
      published_at?: string | null;
      export_urls?: { download_url?: string; raw_url?: string };
    };
    audit?: { event_count?: number; amendment_count?: number };
  };
}

// Unified open-question lifecycle (shared with the backend contract):
//  open | answered | invalid (supprimer, exclu de la publication) | deferred (laisser ouverte).
type ProposalQuestionStatus = 'open' | 'answered' | 'invalid' | 'deferred';

interface ProposalOpenQuestion {
  id?: string;
  question_id?: string;
  gap_id?: string;
  reason?: string;
  follow_up?: string;
  answer?: string | null;
  answered_text?: string | null;
  priority?: number | string | null;
  severity?: number | string | null;
  status?: string | null;
}

interface ProposalReviewQuestion {
  key: string;
  question: ProposalOpenQuestion;
  priority: number;
  status: ProposalQuestionStatus;
}

interface ProposalFact {
  id?: string;
  text?: string;
  statement?: string;
  type?: string;
  status?: string;
  source?: string;
  source_event_id?: string | null;
  retrieval_event_id?: string | null;
  retrieval_refs?: Array<{ title?: string; source?: string; preview?: string; score?: number | null }>;
  turn_kind?: string;
  confidence?: number;
  amended?: boolean;
  raw_text?: string;
  amended_text?: string;
  needs_review?: boolean;
}

@Component({
  selector: 'app-knowledge-capture',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, RouterLink, NgTemplateOutlet, IconComponent, DocumentPreviewComponent],
  styles: [
    `
      @keyframes kc-timer-blink {
        0%,
        100% {
          opacity: 1;
        }
        50% {
          opacity: 0.35;
        }
      }
      .kc-timer-blink {
        animation: kc-timer-blink 1s ease-in-out infinite;
      }
      .kc-sticky-action {
        position: sticky;
        bottom: 0.75rem;
        z-index: 5;
      }
      .ck-fiche-list,
      .ck-fiche-nested-list {
        list-style: none;
        margin: 0;
        padding: 0;
      }
      .ck-fiche-list {
        display: flex;
        flex-direction: column;
        gap: 0.375rem;
      }
      .ck-fiche-nested-list {
        margin-top: 0.375rem;
        margin-left: 0.5rem;
        padding-left: 0.625rem;
        border-left: 1px solid rgba(255, 255, 255, 0.06);
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
      }
      .ck-fiche-heading + .ck-fiche-list-wrap {
        margin-left: 0.75rem;
        padding-left: 0.625rem;
        border-left: 1px solid rgba(255, 255, 255, 0.08);
      }
      .ck-fiche-row {
        display: flex;
        gap: 0.5rem;
        align-items: flex-start;
      }
      .ck-fiche-bullet {
        margin-top: 0.4375rem;
        height: 0.375rem;
        width: 0.375rem;
        flex-shrink: 0;
        border-radius: 9999px;
        background: rgba(96, 165, 250, 0.7);
      }
      .ck-fiche-nested-list .ck-fiche-bullet {
        margin-top: 0.5rem;
        height: 0.25rem;
        width: 0.25rem;
        background: rgba(96, 165, 250, 0.55);
      }
      @keyframes kc-review-q-highlight {
        0%,
        100% {
          box-shadow: 0 0 0 0 rgba(96, 165, 250, 0);
        }
        25%,
        75% {
          box-shadow: 0 0 0 2px rgba(96, 165, 250, 0.45);
        }
      }
      .kc-review-q-highlight {
        animation: kc-review-q-highlight 2s ease-in-out;
      }
    `,
  ],
  template: `
    <section class="space-y-5">
      <header class="t-card t-elevated rounded-lg p-5 flex items-start justify-between gap-4">
        <div>
          <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">
            {{ i18n.t('capture.eyebrow') }}
          </p>
          <h1 class="text-2xl font-semibold text-white mt-1">
            {{ i18n.t('capture.title') }}
          </h1>
          @if (!isDemoMode()) {
            <p class="text-sm text-gray-400 mt-2 max-w-3xl">
              {{ i18n.t('capture.description') }}
            </p>
          }
        </div>
        <div class="flex flex-col items-end gap-2">
          @if (!isDemoMode()) {
            <button
              type="button"
              class="inline-flex items-center gap-1.5 text-xs px-3 py-2 rounded bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
              (click)="showAdvancedSetup.set(!showAdvancedSetup())"
            >
              <app-icon [name]="showAdvancedSetup() ? 'chevron-up' : 'settings-2'" [size]="12" />
              {{ i18n.t('capture.advanced') }}
            </button>
            <a
              [routerLink]="workspaceAccessRoute()"
              class="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
            >
              <app-icon name="settings-2" [size]="12" />
              {{ i18n.t('capture.manage_access') }}
            </a>
          }
        </div>
      </header>

      <nav class="border-y border-white/10 py-3 flex flex-wrap items-center gap-2">
        @for (item of visibleSurfaceNav(); track item.id) {
          <button
            type="button"
            [disabled]="!canNavigateTo(item.id)"
            [class]="activeSurface() === item.id
              ? 'inline-flex items-center gap-2 px-3 py-2 rounded text-brand-100 border-b-2 border-brand-300'
              : canNavigateTo(item.id)
                ? stepIsComplete(item.id)
                  ? 'inline-flex items-center gap-2 px-3 py-2 rounded text-gray-300 hover:text-white'
                  : 'inline-flex items-center gap-2 px-3 py-2 rounded text-gray-500 hover:text-gray-300'
                : 'inline-flex items-center gap-2 px-3 py-2 rounded text-gray-600 opacity-50 cursor-not-allowed'"
            (click)="goSurface(item.id)"
          >
            <span
              [class]="activeSurface() === item.id
                ? 'inline-flex h-5 w-5 items-center justify-center rounded-full bg-brand-300 text-black text-xs font-semibold'
                : stepIsComplete(item.id)
                  ? 'inline-flex h-5 w-5 items-center justify-center rounded-full bg-emerald-500/20 text-emerald-200 text-xs'
                  : 'inline-flex h-5 w-5 items-center justify-center rounded-full bg-white/5 text-gray-500 text-xs ring-1 ring-white/10'"
            >
              {{ stepIsComplete(item.id) ? '✓' : item.step }}
            </span>
            <span class="text-sm">{{ surfaceNavLabel(item) }}</span>
          </button>
          @if (!$last) {
            <span class="text-gray-700">·</span>
          }
        }
      </nav>

      @if (activeSurface() === 'prep') {
        <section class="max-w-5xl mx-auto py-6 lg:py-8 space-y-6 min-h-[calc(100vh-15rem)] flex flex-col">
          <div>
            <p class="ck-mono text-[10px] uppercase tracking-[0.18em] text-gray-500">{{ i18n.t('capture.prep.eyebrow') }}</p>
            <h2 class="mt-2 text-3xl text-white font-semibold">{{ i18n.t('capture.prep.title') }}</h2>
            <p class="mt-2 text-sm text-gray-400 max-w-3xl">
              {{ isDemoMode()
                ? i18n.t('capture.prep.description_demo')
                : i18n.t('capture.prep.description_full') }}
            </p>
          </div>

          <div class="space-y-5 flex-1">
            <div>
              <label class="block text-[11px] uppercase tracking-wider text-gray-500 mb-2">{{ i18n.t('capture.prep.session_title') }}</label>
              <input
                class="w-full rounded bg-black/30 border border-white/10 px-4 py-3 text-sm text-white"
                [(ngModel)]="sessionTitle"
                [placeholder]="i18n.t('capture.prep.session_title_placeholder')"
              />
            </div>

            @if (!isDemoMode() && showAdvancedSetup()) {
            <div>
              <label class="block text-[11px] uppercase tracking-wider text-gray-500 mb-2">{{ i18n.t('capture.prep.domain') }}</label>
              <div class="grid md:grid-cols-3 gap-3">
                @for (domain of captureDomains; track domain.id) {
                  <button
                    type="button"
                    [class]="selectedDomain === domain.id
                      ? 'text-left rounded border border-brand-300 bg-brand-500/10 p-4 ring-1 ring-brand-300/40'
                      : 'text-left rounded border border-white/10 bg-white/[0.03] hover:bg-white/[0.06] p-4'"
                    (click)="selectedDomain = domain.id"
                  >
                    <div class="flex items-center justify-between gap-3">
                      <div class="text-sm font-semibold text-white">{{ domain.label }}</div>
                      @if (selectedDomain === domain.id) {
                        <span class="text-brand-200">✓</span>
                      }
                    </div>
                    <p class="mt-1 text-xs text-gray-500">{{ domain.description }}</p>
                  </button>
                }
              </div>
            </div>
            }

            @if (!isPilotMode()) {
            <div>
              <button
                type="button"
                class="inline-flex items-center gap-2 rounded border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-gray-300 hover:bg-white/[0.06]"
                (click)="showAdvancedSetup.set(!showAdvancedSetup())"
              >
                <app-icon [name]="showAdvancedSetup() ? 'chevron-up' : 'chevron-down'" [size]="14" />
                {{ i18n.t('capture.prep.advanced_sources') }}
              </button>
              @if (showAdvancedSetup()) {
              <div class="mt-3">
              <label class="block text-[11px] uppercase tracking-wider text-gray-500 mb-2">{{ i18n.t('capture.prep.document_context') }}</label>
              <select
                class="w-full rounded bg-black/30 border border-white/10 px-4 py-3 text-sm text-white"
                [(ngModel)]="contextId"
                (ngModelChange)="onContextChange($event)"
              >
                <option value="">{{ i18n.t('capture.prep.workspace_default_sources') }}</option>
                @for (ctx of contexts(); track ctx.id) {
                  <option [value]="ctx.id">
                    {{ ctx.name }}{{ ctx.environment_state?.collection ? ' · ' + ctx.environment_state?.collection : '' }}
                  </option>
                }
              </select>

              @if (selectedContext(); as ctx) {
                <div class="mt-3 rounded border border-white/10 bg-white/[0.03] px-4 py-3">
                  <div class="flex flex-wrap items-center justify-between gap-3">
                    <div class="min-w-0">
                      <div class="text-xs font-semibold text-gray-200 truncate">{{ ctx.name }}</div>
                      <div class="mt-1 text-[11px] text-gray-500 font-mono truncate">
                        {{ ctx.environment_state?.collection || ctx.data_refs?.[0] || 'Sources par défaut du workspace' }}
                      </div>
                    </div>
                    @if (newContextId() === ctx.id) {
                      <span class="shrink-0 text-[10px] uppercase tracking-wider px-2 py-1 rounded bg-emerald-500/15 text-emerald-200 ring-1 ring-emerald-400/20">
                        {{ i18n.t('capture.prep.new_context') }}
                      </span>
                    }
                  </div>
                </div>
              }

              <div class="mt-4 rounded border border-brand-400/20 bg-brand-500/5 p-4 space-y-3">
                <div class="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Créer depuis une collection</p>
                    <p class="mt-1 text-xs text-gray-400">
                      Rattachez une collection documentaire à la capture sans quitter la préparation.
                    </p>
                  </div>
                  @if (loadingKnowledgeCollections()) {
                    <span class="text-[11px] text-gray-500">Chargement des collections...</span>
                  }
                </div>

                <div class="grid md:grid-cols-[minmax(0,1fr)_minmax(220px,0.8fr)] gap-3">
                  <div>
                    <label class="block text-[10px] uppercase tracking-wider text-gray-500 mb-1.5">Collection</label>
                    <select
                      class="w-full rounded bg-black/30 border border-white/10 px-3 py-2.5 text-sm text-white disabled:opacity-50"
                      [disabled]="loadingKnowledgeCollections() || knowledgeCollections().length === 0"
                      [(ngModel)]="selectedKnowledgeCollection"
                      (ngModelChange)="onKnowledgeCollectionChange($event)"
                    >
                      <option value="">Choisir une collection</option>
                      @for (collection of knowledgeCollections(); track collection) {
                        <option [value]="collection">{{ collection }}</option>
                      }
                    </select>
                  </div>
                  <div>
                    <label class="block text-[10px] uppercase tracking-wider text-gray-500 mb-1.5">Nom du contexte</label>
                    <input
                      class="w-full rounded bg-black/30 border border-white/10 px-3 py-2.5 text-sm text-white"
                      [(ngModel)]="newContextName"
                      placeholder="Contexte notices BBA120"
                    />
                  </div>
                </div>

                <div class="flex flex-wrap items-center justify-between gap-3">
                  <p class="text-[11px] text-gray-500">
                    Ce contexte servira à retrouver les documents utiles pendant la capture.
                  </p>
                  <button
                    type="button"
                    class="inline-flex items-center gap-2 px-3 py-2 rounded bg-brand-300 hover:bg-brand-200 text-sm font-semibold text-black disabled:opacity-50"
                    [disabled]="!selectedKnowledgeCollection || creatingContext()"
                    (click)="createContextFromCollection()"
                  >
                    <app-icon name="plus" [size]="14" />
                    {{ creatingContext() ? 'Création...' : 'Créer le contexte' }}
                  </button>
                </div>

                @if (contextCreationNotice(); as notice) {
                  <p [class]="contextCreationNoticeClass(notice.tone)">{{ notice.text }}</p>
                }
                @if (!loadingKnowledgeCollections() && knowledgeCollections().length === 0) {
                  <p class="text-xs rounded border border-white/10 bg-white/5 px-3 py-2 text-gray-400">
                    Aucune collection documentaire n’est disponible dans ce workspace pour l’instant.
                  </p>
                }
              </div>
              </div>
              }
            </div>
            }

            <div class="grid md:grid-cols-[220px_minmax(0,1fr)] gap-5 items-start">
              <div>
                <label class="block text-[11px] uppercase tracking-wider text-gray-500 mb-2">{{ i18n.t('capture.prep.duration') }}</label>
                @if (!isDemoMode() && durationUnlimited()) {
                  <div class="rounded bg-black/30 border border-white/10 px-4 py-3 text-sm text-brand-100">{{ i18n.t('capture.prep.no_limit') }}</div>
                } @else {
                  <input
                    type="number"
                    min="5"
                    max="90"
                    placeholder="20"
                    class="w-full rounded bg-black/30 border border-white/10 px-4 py-3 text-sm text-white"
                    [(ngModel)]="durationMinutes"
                  />
                }
                @if (!isDemoMode()) {
                  <button
                    type="button"
                    class="mt-2 text-xs text-brand-200 hover:text-brand-100"
                    (click)="toggleDurationUnlimited()"
                  >
                    {{ durationUnlimited() ? i18n.t('capture.prep.set_duration') : i18n.t('capture.prep.no_limit') }}
                  </button>
                }
              </div>
              <div class="space-y-3">
                <p class="block text-[11px] uppercase tracking-wider text-gray-500">{{ i18n.t('capture.prep.mode') }}</p>
                <div class="grid md:grid-cols-2 gap-3">
                  @for (mode of visiblePlanModes(); track mode.id) {
                    <button
                      type="button"
                      [disabled]="mode.disabled"
                      [class]="isCaptureModeSelected(mode.id)
                        ? 'text-left rounded-lg border border-brand-300 bg-brand-500/10 p-4 ring-1 ring-brand-300/40'
                        : mode.disabled
                          ? 'text-left rounded-lg border border-white/10 bg-white/[0.02] p-4 opacity-60 cursor-not-allowed'
                          : 'text-left rounded-lg border border-white/10 bg-white/[0.03] hover:bg-white/[0.06] p-4'"
                      (click)="selectPlanMode(mode.id)"
                    >
                      <span class="flex items-start gap-3">
                        <span
                          [class]="isCaptureModeSelected(mode.id)
                            ? 'inline-flex h-9 w-9 shrink-0 items-center justify-center rounded border border-brand-300 text-brand-200'
                            : 'inline-flex h-9 w-9 shrink-0 items-center justify-center rounded border border-white/10 text-gray-500'"
                        >
                          <app-icon [name]="mode.icon" [size]="16" />
                        </span>
                        <span class="min-w-0">
                          <span class="block text-sm font-semibold text-white">{{ mode.label }}</span>
                          <span class="mt-1 block text-xs leading-relaxed text-gray-500">{{ mode.description }}</span>
                        </span>
                      </span>
                    </button>
                  }
                </div>
              </div>
            </div>

            <div class="kc-sticky-action flex items-center justify-end gap-3 pt-4 rounded-t-lg border-t border-white/10 bg-black/75 px-1 py-3 backdrop-blur">
              <button
                type="button"
                class="px-4 py-2 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-300 ring-1 ring-white/10"
                (click)="goSurface('dashboard')"
              >
                {{ i18n.t('common.cancel') }}
              </button>
              <button
                type="button"
                class="inline-flex items-center gap-2 px-5 py-2.5 rounded bg-brand-300 hover:bg-brand-200 text-sm font-semibold text-black disabled:opacity-50"
                [disabled]="loading() || !sessionTitle.trim() || !canCaptureCreate()"
                [title]="preparationBlockingHint() || ''"
                (click)="continueFromPreparation()"
              >
                {{ loading() ? i18n.t('capture.action.preparing') : i18n.t('capture.action.continue') }}
                <app-icon name="arrow-right" [size]="14" />
              </button>
            </div>
            @if (preparationBlockingHint(); as hint) {
              <p class="-mt-3 text-right text-[11px] text-amber-200/85">{{ hint }}</p>
            }
          </div>
        </section>
      }

      @if (activeSurface() === 'dashboard') {
        <section class="space-y-4">
          @if (!isDemoMode()) {
            <nav class="flex flex-wrap gap-2 border-b border-white/10 pb-3">
              <button
                type="button"
                [class]="dashboardTab() === 'sessions'
                  ? 'inline-flex items-center gap-2 px-3 py-2 rounded text-brand-100 border-b-2 border-brand-300'
                  : 'inline-flex items-center gap-2 px-3 py-2 rounded text-gray-400 hover:text-white'"
                (click)="setDashboardTab('sessions')"
              >
                <app-icon name="layout-dashboard" [size]="14" />
                {{ i18n.t('capture.dashboard.tab_sessions') }}
              </button>
              <button
                type="button"
                [class]="dashboardTab() === 'fiches'
                  ? 'inline-flex items-center gap-2 px-3 py-2 rounded text-brand-100 border-b-2 border-brand-300'
                  : 'inline-flex items-center gap-2 px-3 py-2 rounded text-gray-400 hover:text-white'"
                (click)="setDashboardTab('fiches')"
              >
                <app-icon name="book-open" [size]="14" />
                {{ i18n.t('capture.dashboard.tab_fiches') }}
              </button>
            </nav>
          }

          @if (dashboardTab() === 'fiches') {
            <section class="t-card rounded-lg p-5 space-y-4">
              <div class="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">{{ i18n.t('capture.fiches.eyebrow') }}</p>
                  <h2 class="text-lg font-semibold text-white">{{ i18n.t('capture.fiches.title') }}</h2>
                  <p class="mt-1 text-sm text-gray-400 max-w-3xl">{{ i18n.t('capture.fiches.description') }}</p>
                </div>
                <button
                  type="button"
                  class="inline-flex items-center gap-1.5 text-xs px-3 py-2 rounded bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200"
                  [disabled]="publishedFichesLoading()"
                  (click)="refreshPublishedFiches()"
                >
                  <app-icon name="refresh-cw" [size]="12" />
                  {{ i18n.t('common.retry') }}
                </button>
              </div>

              <div class="grid md:grid-cols-4 gap-3">
                <div class="md:col-span-2">
                  <label class="block text-[10px] uppercase tracking-wider text-gray-500 mb-1">{{ i18n.t('common.search') }}</label>
                  <input
                    class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white"
                    [(ngModel)]="ficheSearchQuery"
                    [placeholder]="i18n.t('capture.fiches.search_placeholder')"
                    (keyup.enter)="refreshPublishedFiches()"
                  />
                </div>
                <div>
                  <label class="block text-[10px] uppercase tracking-wider text-gray-500 mb-1">{{ i18n.t('capture.fiches.filter_category') }}</label>
                  <select
                    class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white"
                    [(ngModel)]="ficheCategoryFilter"
                    (ngModelChange)="refreshPublishedFiches()"
                  >
                    <option value="">{{ i18n.t('capture.fiches.all_categories') }}</option>
                    @for (value of publishedFicheCategories(); track value) {
                      <option [value]="value">{{ value }}</option>
                    }
                  </select>
                </div>
                <div>
                  <label class="block text-[10px] uppercase tracking-wider text-gray-500 mb-1">{{ i18n.t('capture.fiches.filter_destination') }}</label>
                  <select
                    class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white"
                    [(ngModel)]="ficheDestinationFilter"
                    (ngModelChange)="refreshPublishedFiches()"
                  >
                    <option value="">{{ i18n.t('capture.fiches.all_destinations') }}</option>
                    @for (value of publishedFicheDestinations(); track value) {
                      <option [value]="value">{{ value }}</option>
                    }
                  </select>
                </div>
              </div>
              <div class="max-w-sm">
                <label class="block text-[10px] uppercase tracking-wider text-gray-500 mb-1">{{ i18n.t('capture.fiches.filter_author') }}</label>
                <select
                  class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white"
                  [(ngModel)]="ficheAuthorFilter"
                  (ngModelChange)="refreshPublishedFiches()"
                >
                  <option value="">{{ i18n.t('capture.fiches.all_authors') }}</option>
                  @for (author of publishedFicheAuthors(); track author.id) {
                    <option [value]="author.id">{{ author.label }}</option>
                  }
                </select>
              </div>

              @if (publishedFichesLoading()) {
                <div class="rounded border border-white/10 bg-black/20 p-8 text-center text-gray-400">
                  {{ i18n.t('common.loading') }}
                </div>
              } @else if (publishedFichesError()) {
                <div class="rounded border border-red-400/30 bg-red-500/10 p-6 text-center text-red-200 space-y-3">
                  <p>{{ i18n.t('capture.fiches.error') }}</p>
                  <button
                    type="button"
                    class="inline-flex items-center gap-1.5 text-xs px-3 py-2 rounded bg-white/10 hover:bg-white/15 text-gray-100"
                    (click)="refreshPublishedFiches()"
                  >
                    {{ i18n.t('common.retry') }}
                  </button>
                </div>
              } @else {
                <div class="overflow-x-auto rounded border border-white/10">
                  <table class="min-w-full text-sm">
                    <thead class="bg-white/[0.03] text-[10px] uppercase tracking-wider text-gray-500">
                      <tr>
                        <th class="px-3 py-2 text-left">{{ i18n.t('capture.fiches.column_title') }}</th>
                        <th class="px-3 py-2 text-left">{{ i18n.t('capture.fiches.column_category') }}</th>
                        <th class="px-3 py-2 text-left">{{ i18n.t('capture.fiches.column_collection') }}</th>
                        <th class="px-3 py-2 text-left">{{ i18n.t('capture.fiches.column_author') }}</th>
                        <th class="px-3 py-2 text-left">{{ i18n.t('capture.fiches.column_published') }}</th>
                        <th class="px-3 py-2 text-left">{{ i18n.t('capture.fiches.column_metrics') }}</th>
                        <th class="px-3 py-2 text-right">{{ i18n.t('common.open') }}</th>
                      </tr>
                    </thead>
                    <tbody class="divide-y divide-white/5">
                      @for (row of publishedFiches(); track row.id) {
                        <tr class="hover:bg-white/[0.03]">
                          <td class="px-3 py-3 align-top">
                            <div class="font-semibold text-white">{{ row.title }}</div>
                            @if (row.session_title) {
                              <div class="mt-1 text-xs text-gray-500">{{ row.session_title }}</div>
                            }
                          </td>
                          <td class="px-3 py-3 align-top text-gray-300">{{ row.category || '—' }}</td>
                          <td class="px-3 py-3 align-top text-gray-300">{{ row.destination || row.collection_slug || '—' }}</td>
                          <td class="px-3 py-3 align-top text-gray-300">{{ row.author?.label || '—' }}</td>
                          <td class="px-3 py-3 align-top text-gray-400 text-xs">
                            <div>{{ publishedFicheDateLabel(row) }}</div>
                            @if (row.published_by?.label) {
                              <div class="mt-1 text-gray-500">{{ row.published_by?.label }}</div>
                            }
                          </td>
                          <td class="px-3 py-3 align-top text-xs text-gray-400 space-y-1">
                            <div>{{ publishedFicheWordLabel(row) }} · {{ publishedFicheChunkLabel(row) }}</div>
                            @if ((row.open_questions_count || 0) > 0) {
                              <div class="text-amber-200">{{ publishedFicheOpenQuestionsLabel(row) }}</div>
                            }
                          </td>
                          <td class="px-3 py-3 align-top">
                            <div class="flex flex-wrap justify-end gap-1.5">
                              @if (row.preview_url || row.document_id) {
                                <button
                                  type="button"
                                  class="px-2 py-1 rounded bg-white/5 hover:bg-white/10 text-xs text-brand-100 ring-1 ring-white/10"
                                  (click)="openPublishedFichePreview(row)"
                                >
                                  {{ i18n.t('capture.fiches.open_preview') }}
                                </button>
                              }
                              @if (row.collection_slug) {
                                <button
                                  type="button"
                                  class="px-2 py-1 rounded bg-white/5 hover:bg-white/10 text-xs text-gray-200 ring-1 ring-white/10"
                                  (click)="openPublishedFicheCollection(row)"
                                >
                                  {{ i18n.t('capture.fiches.open_kb') }}
                                </button>
                              }
                              @if (row.session_owned_by_current_user) {
                                <button
                                  type="button"
                                  class="px-2 py-1 rounded bg-white/5 hover:bg-white/10 text-xs text-gray-200 ring-1 ring-white/10"
                                  (click)="openPublishedFicheSession(row)"
                                >
                                  {{ i18n.t('capture.fiches.open_session') }}
                                </button>
                              }
                            </div>
                          </td>
                        </tr>
                      } @empty {
                        <tr>
                          <td colspan="7" class="px-3 py-8 text-center text-gray-500">
                            {{ i18n.t('capture.fiches.empty') }}
                          </td>
                        </tr>
                      }
                    </tbody>
                  </table>
                </div>
              }
            </section>
          } @else {
        <section [class]="isDemoMode() ? 'grid gap-5 max-w-5xl mx-auto' : 'grid xl:grid-cols-[1.5fr_1fr] gap-5'">
          <div class="t-card rounded-lg p-5 space-y-4">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">{{ i18n.t('capture.dashboard.eyebrow') }}</p>
                <h2 class="text-lg font-semibold text-white">
                  {{ isDemoMode() ? i18n.t('capture.dashboard.title') : i18n.t('capture.dashboard.title_full') }}
                </h2>
              </div>
              @if (!isDemoMode()) {
              <select
                class="rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white"
                [(ngModel)]="dashboardDomainFilter"
                (ngModelChange)="refreshDashboard()"
              >
                <option value="">{{ i18n.t('capture.dashboard.all_domains') }}</option>
                @for (domain of captureDomains; track domain.id) {
                  <option [value]="domain.id">{{ domain.label }}</option>
                }
              </select>
              }
              <button
                type="button"
                class="inline-flex items-center gap-2 px-3 py-2 rounded bg-brand-500 hover:bg-brand-400 text-sm font-semibold text-white disabled:opacity-50"
                [disabled]="!canCaptureCreate()"
                (click)="startNewSessionDraft()"
              >
                <app-icon name="plus" [size]="14" /> {{ isDemoMode() ? i18n.t('capture.dashboard.new_capture') : i18n.t('capture.dashboard.new_session') }}
              </button>
            </div>
            @if (!isDemoMode() && showAdvancedSetup()) {
            <div class="grid md:grid-cols-4 gap-3">
              <div class="rounded bg-black/20 border border-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500">{{ i18n.t('capture.dashboard.sessions') }}</div>
                <div class="text-2xl text-white font-semibold">{{ dashboardSessions().length }}</div>
              </div>
              <div class="rounded bg-black/20 border border-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500">{{ i18n.t('capture.dashboard.active') }}</div>
                <div class="text-2xl text-white font-semibold">{{ activeSessionCount() }}</div>
              </div>
              <div class="rounded bg-black/20 border border-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500">{{ i18n.t('capture.dashboard.reports') }}</div>
                <div class="text-2xl text-white font-semibold">{{ dashboardProposals().length }}</div>
              </div>
              <div class="rounded bg-black/20 border border-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500">{{ i18n.t('capture.dashboard.to_review') }}</div>
                <div class="text-2xl text-white font-semibold">{{ pendingProposalCount() }}</div>
              </div>
            </div>
            }
            <div class="flex items-center justify-end">
              <button
                type="button"
                class="inline-flex items-center gap-1.5 text-[11px] px-2 py-1 rounded ring-1 transition-colors"
                [class]="showArchivedSessions()
                  ? 'bg-brand-500/15 text-brand-100 ring-brand-300/20'
                  : 'bg-white/5 text-gray-400 ring-white/10 hover:text-gray-200'"
                (click)="toggleArchivedSessions()"
              >
                <app-icon name="archive" [size]="12" />
                {{ showArchivedSessions() ? 'Masquer les sessions archivées' : 'Afficher les sessions archivées' }}
              </button>
            </div>
            <div class="space-y-2">
              @for (row of visibleDashboardSessions(); track row.id) {
                <div
                  role="button"
                  tabindex="0"
                  class="w-full cursor-pointer text-left rounded border p-3 transition-colors"
                  [class]="row.archived
                    ? 'border-white/5 bg-white/[0.015] opacity-70 hover:opacity-100 hover:bg-white/[0.04]'
                    : 'border-white/10 bg-white/[0.03] hover:bg-white/[0.06]'"
                  (click)="openDashboardSession(row)"
                  (keydown.enter)="openDashboardSession(row)"
                >
                  <div class="flex items-start justify-between gap-3">
                    <div>
                      <div class="text-sm font-semibold text-white">{{ row.title }}</div>
                      <p class="text-xs text-gray-500 mt-1 line-clamp-2">{{ sessionCardSummary(row) }}</p>
                      @if (!isDemoMode() && showAdvancedSetup() && isAuthor(row)) {
                        <span class="mt-2 inline-flex px-2 py-0.5 rounded bg-brand-500/15 text-[10px] uppercase tracking-wider text-brand-200">
                          {{ i18n.t('capture.dashboard.author') }}
                        </span>
                      }
                    </div>
                    <div class="flex shrink-0 items-center gap-1.5">
                      @if (row.archived) {
                        <span class="text-xs px-2 py-1 rounded bg-white/5 text-gray-500 ring-1 ring-white/10">Archivée</span>
                      } @else {
                        <span class="text-xs px-2 py-1 rounded bg-white/5 text-gray-300">{{ captureSessionStatusLabel(row) }}</span>
                      }
                      @if (canCaptureUpdate(row)) {
                        @if (row.archived) {
                          <button
                            type="button"
                            class="p-1.5 rounded text-gray-500 hover:text-brand-200 hover:bg-white/5"
                            title="Désarchiver la session"
                            [disabled]="sessionActionLoading() === row.id"
                            (click)="unarchiveSession(row, $event)"
                          >
                            <app-icon name="archive-restore" [size]="14" />
                          </button>
                        } @else {
                          <button
                            type="button"
                            class="p-1.5 rounded text-gray-500 hover:text-gray-200 hover:bg-white/5"
                            title="Archiver la session"
                            [disabled]="sessionActionLoading() === row.id"
                            (click)="archiveSession(row, $event)"
                          >
                            <app-icon name="archive" [size]="14" />
                          </button>
                        }
                        <button
                          type="button"
                          class="p-1.5 rounded text-gray-500 hover:text-red-300 hover:bg-red-500/10"
                          title="Supprimer la session"
                          [disabled]="sessionActionLoading() === row.id"
                          (click)="requestDeleteSession(row, $event)"
                        >
                          <app-icon name="trash-2" [size]="14" />
                        </button>
                      }
                    </div>
                  </div>
                  @if (confirmDeleteSessionId() === row.id) {
                    <div class="mt-3 flex flex-wrap items-center justify-between gap-2 rounded border border-red-400/30 bg-red-500/10 px-3 py-2 text-xs">
                      <span class="text-red-200">Supprimer définitivement cette session (transcript et rapports inclus) ?</span>
                      <span class="flex gap-2">
                        <button
                          type="button"
                          class="px-2 py-1 rounded bg-red-500/80 hover:bg-red-500 text-white font-semibold"
                          [disabled]="sessionActionLoading() === row.id"
                          (click)="confirmDeleteSession(row, $event)"
                        >
                          Supprimer
                        </button>
                        <button
                          type="button"
                          class="px-2 py-1 rounded bg-white/10 hover:bg-white/15 text-gray-200"
                          (click)="cancelDeleteSession($event)"
                        >
                          Annuler
                        </button>
                      </span>
                    </div>
                  }
                  <div class="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-gray-400">
                    <div class="flex flex-wrap gap-2">
                      <span>{{ sessionLastActivityLabel(row) }}</span>
                      @if (sessionOpenQuestionCount(row) > 0) {
                        <span class="text-amber-200">{{ sessionOpenQuestionsLabel(row) }}</span>
                      }
                    </div>
                    <span class="inline-flex shrink-0 items-center gap-1 rounded bg-brand-500/15 px-2 py-1 text-brand-100 ring-1 ring-brand-300/20">
                      {{ sessionCardActionLabel(row) }}
                      <app-icon name="arrow-right" [size]="12" />
                    </span>
                  </div>
                </div>
              } @empty {
                <div class="rounded border border-dashed border-white/10 bg-black/20 p-8 text-center text-gray-500">
                  {{ i18n.t('capture.dashboard.empty') }}
                </div>
              }
            </div>
            @if (!isDemoMode() && dashboardQualityBacklog().length) {
              <section class="rounded border border-amber-500/25 bg-amber-500/5 p-4 space-y-2">
                <p class="ck-mono text-[10px] uppercase tracking-wider text-amber-200">Points à clarifier</p>
                @for (row of dashboardQualityBacklog(); track row.sessionId + (row.item.id || row.item.label)) {
                  <article class="text-sm text-gray-200 flex flex-wrap items-center justify-between gap-2">
                    <span class="min-w-0 truncate">{{ row.sessionTitle }} · {{ row.item.label || row.item.follow_up }}</span>
                    <button
                      type="button"
                      class="shrink-0 text-[10px] text-brand-200 hover:text-brand-100"
                      (click)="openDashboardSessionForQuality(row.sessionId); $event.stopPropagation()"
                    >
                      Clarifier
                    </button>
                  </article>
                }
              </section>
            }
          </div>

          @if (!isDemoMode()) {
          <div class="t-card rounded-lg p-5 space-y-4">
            <div>
              <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Rapports à relire</p>
              <h2 class="text-lg font-semibold text-white">File de revue</h2>
            </div>
            <div class="space-y-2">
              @for (row of dashboardProposals(); track row.id) {
                <button
                  type="button"
                  class="w-full text-left rounded border border-white/10 bg-white/[0.03] hover:bg-white/[0.06] p-3"
                  (click)="openDashboardProposal(row)"
                >
                  <div class="flex items-center justify-between gap-3">
                    <div class="text-sm font-semibold text-white">
                      {{ row.proposal?.title || 'Rapport de capture' }}
                    </div>
                    <span class="text-xs px-2 py-1 rounded bg-white/5 text-gray-300">{{ workflowStatusLabel(row.status) }}</span>
                  </div>
                  @if (showAdvancedSetup()) {
                  <div class="mt-2 text-xs text-gray-500">
                    {{ row.proposal?.captured_facts?.length || 0 }} faits · {{ row.proposal?.audit?.event_count || 0 }} événements d’audit
                  </div>
                  }
                </button>
              } @empty {
                <div class="rounded border border-dashed border-white/10 bg-black/20 p-6 text-center text-gray-500">
                  Aucun rapport en attente de relecture.
                </div>
              }
            </div>
          </div>
          }
        </section>
          }
        </section>
      }

      @if (activeSurface() === 'session') {
        @if (session(); as s) {
          <section class="space-y-4">
            <section class="t-card rounded-lg p-4">
              <div class="flex flex-wrap items-center justify-between gap-4">
                <div class="min-w-0">
                  <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">{{ i18n.t('capture.session.status.in_progress') }}</p>
                  <h2 class="text-lg font-semibold text-white mt-1 truncate">{{ s.title }}</h2>
                </div>
                <div class="flex flex-wrap items-center gap-2 text-xs">
                  @if (!isDemoMode() && showAdvancedSetup()) {
                    <span class="px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">{{ workflowStatusLabel(s.status) }}</span>
                  }
                  @if (sessionTimerView(s); as timer) {
                    <span
                      [class]="timer.overtime
                        ? 'px-2 py-1 rounded bg-red-500/15 text-red-200 ring-1 ring-red-400/30'
                        : timer.blink
                          ? 'px-2 py-1 rounded bg-amber-500/20 text-amber-100 ring-1 ring-amber-400/30 kc-timer-blink'
                          : 'px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10'"
                    >
                      {{ timer.label }}
                    </span>
                  }
                  <span class="px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">
                    {{ captureProgressLabel(s) }}
                  </span>
                  @if (!isDemoMode() && showAdvancedSetup()) {
                    <span class="px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">
                      {{ s.metrics?.['captured_facts'] || 0 }} faits
                    </span>
                    <span class="px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">
                      {{ knowledgeScopeLabel() }}
                    </span>
                    @if (isAuthor(s)) {
                      <span class="px-2 py-1 rounded bg-brand-500/15 text-brand-100 ring-1 ring-brand-300/20">{{ i18n.t('capture.dashboard.author') }}</span>
                    }
                  }
                  @if (s.status === 'active') {
                    <button type="button" class="px-2 py-1 rounded bg-white/5 text-gray-300 hover:text-white text-xs" (click)="pauseSession(s)">{{ i18n.t('capture.action.pause') }}</button>
                  }
                  @if (s.status === 'paused') {
                    <button type="button" class="px-2 py-1 rounded bg-brand-500/20 text-brand-100 text-xs" (click)="resumeSession(s)">{{ i18n.t('capture.action.resume') }}</button>
                  }
                </div>
              </div>
            </section>

            @if (showClosurePanel(s)) {
              <section class="t-card rounded-lg border border-amber-400/30 bg-amber-500/10 p-5 space-y-4">
                <div>
                  <p class="ck-mono text-[10px] uppercase tracking-wider text-amber-200">Fin de session</p>
                  <h3 class="text-lg font-semibold text-white mt-1">Durée planifiée atteinte</h3>
                  <p class="text-sm text-gray-300 mt-1">
                    Continuez vers le rapport, prolongez de 15 minutes ou replanifiez une session — sans interruption vocale.
                  </p>
                </div>
                @if (closureSheetMarkdown(); as sheet) {
                  <details class="rounded border border-white/10 bg-black/20 p-3" open>
                    <summary class="cursor-pointer text-sm text-gray-200">Fiche fin de session</summary>
                    <pre class="mt-3 whitespace-pre-wrap text-xs text-gray-400 max-h-56 overflow-auto">{{ sheet }}</pre>
                  </details>
                }
                <div class="flex flex-wrap gap-2">
                  <button
                    type="button"
                    class="inline-flex items-center gap-2 px-4 py-2 rounded bg-brand-500 hover:bg-brand-400 text-sm font-semibold text-white"
                    [disabled]="closureActionLoading()"
                    (click)="applySessionClosure(s, 'finish')"
                  >
                  <app-icon name="arrow-right" [size]="14" /> {{ i18n.t('capture.action.continue') }}
                  </button>
                  <button
                    type="button"
                    class="inline-flex items-center gap-2 px-4 py-2 rounded bg-white/10 hover:bg-white/15 text-sm text-gray-100 ring-1 ring-white/10"
                    [disabled]="closureActionLoading()"
                    (click)="applySessionClosure(s, 'extend')"
                  >
                    Prolonger (+15 min)
                  </button>
                  <button
                    type="button"
                    class="inline-flex items-center gap-2 px-4 py-2 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-200 ring-1 ring-white/10"
                    [disabled]="closureActionLoading()"
                    (click)="applySessionClosure(s, 'schedule')"
                  >
                    Replanifier
                  </button>
                </div>
              </section>
            }

            <section
              [class]="isDemoMode()
                ? 'grid xl:grid-cols-[380px_minmax(0,1fr)] gap-4 items-start'
                : (showAdvancedSetup() || proposal())
                  ? 'grid xl:grid-cols-[300px_minmax(0,1fr)_360px] gap-4 items-start'
                  : 'grid xl:grid-cols-[300px_minmax(0,1fr)] gap-4 items-start'"
            >
              <aside class="t-card rounded-lg p-4 max-h-[calc(100vh-270px)] flex flex-col gap-4 overflow-hidden">
                <div class="shrink-0">
                  <div class="flex items-center justify-between gap-3">
                    <div>
                      <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Rappel</p>
                      <h3 class="text-sm font-semibold text-white">
                        {{ isFreeConversationSession(s) ? 'Conversation libre' : 'Sujets de capture' }}
                      </h3>
                    </div>
                    <span class="text-xs text-brand-200">{{ captureProgressLabel(s) }}</span>
                  </div>
                  @if (!isFreeConversationSession(s)) {
                    <p class="mt-1 text-[11px] leading-relaxed text-gray-500">
                      Simple repère : parlez librement, dans l’ordre que vous voulez. Rien ne vous oblige à suivre ce plan.
                    </p>
                  }
                </div>

                @if (!isDemoMode()) {
                <div class="grid grid-cols-2 gap-2 text-xs shrink-0">
                  <div class="rounded bg-black/20 border border-white/10 p-3">
                    <span class="block text-[9px] uppercase tracking-wider text-gray-500">État</span>
                    <span class="text-gray-200">{{ sessionStartStateLabel(s) }}</span>
                  </div>
                  <div class="rounded bg-black/20 border border-white/10 p-3">
                    <span class="block text-[9px] uppercase tracking-wider text-gray-500">{{ isFreeConversationSession(s) ? 'Faits' : 'Couverture' }}</span>
                    <span class="text-gray-200">
                      {{ isFreeConversationSession(s) ? (s.metrics?.['captured_facts'] || 0) : coveragePercent(s) + '%' }}
                    </span>
                  </div>
                </div>
                }

                <!-- QUESTIONS IA pinned above the plan list so it stays visible
                     without scrolling; the plan list below is the scroll area. -->
                <section class="rounded border border-white/10 bg-black/20 p-3 shrink-0">
                  <div class="flex items-center justify-between gap-2">
                    <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Questions IA</p>
                    <span class="text-[10px] text-gray-600">
                      {{ oracleQuestionsMuted() ? 'masquées' : activeOracleQuestions().length }}
                    </span>
                  </div>
                  @if (oracleQuestionsMuted()) {
                    <p class="mt-1 text-[10px] leading-relaxed text-gray-600">
                      Les questions IA sont masquées pour cette session.
                    </p>
                    <button
                      type="button"
                      class="mt-2 text-[10px] text-gray-400 hover:text-gray-200"
                      (click)="unmuteOracleQuestions()"
                    >
                      Réactiver
                    </button>
                  } @else {
                    <p class="mt-1 text-[10px] leading-relaxed text-gray-600">
                      Questions utiles à clarifier pendant ou après l’échange.
                    </p>
                    @if (activeOracleQuestions().length) {
                      <button
                        type="button"
                        class="mt-2 text-[10px] text-gray-400 hover:text-gray-200"
                        (click)="muteOracleQuestions()"
                      >
                        Ne plus poser de questions
                      </button>
                    }
                  }
                  <div class="mt-2 space-y-2 max-h-[26vh] overflow-y-auto pr-1">
                    @if (!oracleQuestionsMuted()) {
                      @for (q of activeOracleQuestions(); track q.id || q.text) {
                        <div class="rounded border border-white/10 bg-white/[0.03] p-2.5">
                          <div class="flex items-start gap-2">
                            <span [class]="oracleQuestionPriorityClass(q)" class="mt-1.5"></span>
                            <p class="text-xs text-gray-200 leading-snug">{{ q.text }}</p>
                          </div>
                          <div class="mt-1.5 flex flex-wrap items-center gap-2 pl-3.5">
                            @if (oracleQuestionTopicLabel(q); as topicLabel) {
                              <span class="text-[10px] text-brand-200/80 truncate">{{ topicLabel }}</span>
                            }
                            @if (oracleQuestionPriorityLabel(q); as priorityLabel) {
                              <span class="text-[10px] text-gray-600">{{ priorityLabel }}</span>
                            }
                          </div>
                          <div class="mt-2 flex flex-wrap gap-2 pl-3.5">
                            <button type="button" class="text-[10px] text-brand-200 hover:text-brand-100" (click)="answerOracleQuestion(q)">Répondre</button>
                            <button type="button" class="text-[10px] text-gray-400 hover:text-gray-200" (click)="dismissOracleQuestion(q)">Fermer</button>
                            <button type="button" class="text-[10px] text-gray-400 hover:text-gray-200" (click)="deferOracleQuestion(q)">Plus tard</button>
                          </div>
                        </div>
                      } @empty {
                        <p class="text-[11px] text-gray-600">
                          Les questions IA apparaîtront ici au fil de l’échange.
                        </p>
                      }
                    }
                  </div>
                </section>

                <div class="flex-1 min-h-32 overflow-y-auto pr-1">
                @if (isFreeConversationSession(s)) {
                  <div class="rounded border border-dashed border-white/10 bg-black/20 p-4 text-sm text-gray-400">
                    {{ i18n.t('capture.session.free_guidance') }}
                  </div>
                } @else {
                  <div class="space-y-3">
                    @for (topic of planTopics(s); track topic.id) {
                      <!-- Plain outline titles only: the generated "Présentez..."
                           interpretations were cropped mid-sentence and over-interpreted
                           the expert's intent — they stay available on hover. -->
                      <div class="rounded border border-white/10 bg-white/[0.03] p-3">
                        <div class="flex items-start justify-between gap-3">
                          @if ((topic.subtopics || []).length) {
                            <div class="min-w-0" [title]="outlineItemPrompt(topic) || topic.objective || ''">
                              <div class="text-xs font-semibold leading-snug text-gray-200">{{ topic.title }}</div>
                            </div>
                          } @else {
                            <button
                              type="button"
                              class="min-w-0 flex-1 text-left"
                              [class]="topicOnlyRailClass(s, topic)"
                              [title]="outlineItemPrompt(topic) || topic.objective || ''"
                              (click)="selectCaptureTopic(topic.id)"
                            >
                              <div class="text-xs font-semibold leading-snug">{{ topic.title }}</div>
                            </button>
                          }
                          <span class="shrink-0 rounded bg-white/5 px-2 py-1 text-[10px] text-gray-400">
                            {{ subtopicsLabel((topic.subtopics || []).length) }}
                          </span>
                        </div>
                        @for (subtopic of topic.subtopics || []; track subtopic.id) {
                          <button
                            type="button"
                            [class]="subtopicRailClass(s, subtopic)"
                            [title]="outlineItemPrompt(subtopic) || subtopic.objective || ''"
                            (click)="selectCaptureSubtopic(subtopic.id)"
                          >
                            <span class="min-w-0">
                              <span class="block leading-snug">{{ subtopic.title }}</span>
                            </span>
                            <span class="shrink-0 text-[10px] opacity-70">{{ subtopicProgressLabel(s, subtopic) }}</span>
                          </button>
                        }
                      </div>
                    } @empty {
                      <div class="rounded border border-dashed border-white/10 bg-black/20 p-4 text-sm text-gray-400">
                        Aucun sujet structuré. La pile de relances reste disponible dans la colonne centrale.
                      </div>
                    }
                  </div>
                }
                </div>

                @if (!isDemoMode() && showAdvancedSetup()) {
                  <section class="rounded border border-white/10 bg-black/20 p-3 shrink-0">
                    <div class="flex items-center justify-between gap-2">
                      <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Contexte retrouvé</p>
                      @if (retrieval().latency_ms !== undefined) {
                        <span class="text-[10px] text-gray-600">{{ retrieval().latency_ms }} ms</span>
                      }
                    </div>
                    @if (retrieval().chunks.length) {
                      <div class="mt-2 space-y-2 max-h-[24vh] overflow-y-auto pr-1">
                        @for (chunk of retrieval().chunks.slice(0, 3); track retrievalChunkTrack($index, chunk); let ci = $index) {
                          <div class="rounded bg-white/[0.03] border border-white/10 p-2.5">
                            <div class="flex items-start justify-between gap-2">
                              <p class="text-[11px] text-gray-400 line-clamp-3">{{ chunk }}</p>
                              @if (canPreviewRetrievalChunk(ci)) {
                                <button
                                  type="button"
                                  class="shrink-0 inline-flex items-center justify-center rounded p-1 text-gray-500 hover:text-brand-300 hover:bg-white/5 transition"
                                  title="Prévisualiser la source"
                                  (click)="previewRetrievalChunk(ci)"
                                >
                                  <app-icon name="eye" [size]="12" />
                                </button>
                              }
                            </div>
                            @if (retrievalChunkTitle(ci); as srcTitle) {
                              <p class="mt-1 text-[10px] uppercase tracking-wider text-gray-600 truncate">{{ srcTitle }}</p>
                            }
                          </div>
                        }
                      </div>
                    } @else {
                      <p class="mt-2 text-[11px] text-gray-600 leading-relaxed">
                        Les passages utiles s’affichent ici dès que l’échange devient assez précis. L’IA ne vous attend pas.
                      </p>
                    }
                  </section>
                }
              </aside>

              <main class="t-card rounded-lg p-4 min-h-[calc(100vh-270px)] max-h-[calc(100vh-270px)] flex flex-col overflow-hidden">
                @if (!isFreeConversationSession(s)) {
                <!-- Compact current-position breadcrumb: the left rail already shows
                     the full plan, so the transcript reclaims the vertical space the
                     old full-plan block was taking. -->
                <div
                  [class]="isDemoMode()
                    ? 'sticky top-2 z-10 rounded bg-brand-500/10 border border-brand-400/20 px-3 py-2 backdrop-blur'
                    : 'rounded bg-brand-500/10 border border-brand-400/20 px-3 py-2'"
                >
                  <div class="flex items-center justify-between gap-3">
                    <div class="min-w-0 flex items-center gap-2.5">
                      <span class="ck-mono shrink-0 text-[9px] uppercase tracking-wider text-brand-200/80">
                        Position
                      </span>
                      <p class="truncate text-sm text-gray-100" [title]="captureBreadcrumb(s) || ''">
                        {{ captureBreadcrumb(s) || 'Parlez librement : le plan reste visible à gauche.' }}
                      </p>
                    </div>
                    <div class="flex shrink-0 items-center gap-2">
                      @if (sessionHasStarted(s) && s.status === 'active') {
                        <button
                          type="button"
                          class="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded bg-amber-500/15 hover:bg-amber-500/25 text-xs font-medium text-amber-100 ring-1 ring-amber-400/25"
                          [title]="i18n.t('capture.action.finish_section_hint')"
                          (click)="finishCurrentSection(s)"
                        >
                          <app-icon name="check" [size]="13" /> {{ i18n.t('capture.action.finish_section') }}
                        </button>
                      }
                      <button
                        type="button"
                        class="inline-flex items-center gap-2 px-3 py-1.5 rounded bg-white/5 hover:bg-white/10 text-xs text-gray-200 ring-1 ring-white/10"
                        [disabled]="!currentPromptText()"
                        (click)="readCurrentQuestion()"
                      >
                        <app-icon name="volume-2" [size]="14" /> Lire
                      </button>
                    </div>
                  </div>
                </div>
                }

                @if (visibleSuggestions().length) {
                  <div class="mt-3 space-y-2">
                    @for (sug of visibleSuggestions(); track sug.id) {
                      <div class="flex items-start gap-2 rounded border border-white/10 bg-white/[0.03] px-3 py-2">
                        <app-icon name="lightbulb" [size]="13" class="mt-0.5 shrink-0 text-amber-300/80" />
                        <div class="min-w-0 flex-1">
                          <p class="text-[10px] uppercase tracking-wider text-gray-500">{{ suggestionKindLabel(sug.kind) }}</p>
                          <p class="text-xs text-gray-200 leading-snug">{{ sug.text }}</p>
                        </div>
                        <button
                          type="button"
                          class="shrink-0 inline-flex items-center justify-center rounded p-1 text-gray-500 hover:text-gray-200 hover:bg-white/5"
                          title="Ignorer cette suggestion (elle n’interrompt jamais)."
                          (click)="dismissSuggestion(sug.id)"
                        >
                          <app-icon name="x" [size]="12" />
                        </button>
                      </div>
                    }
                  </div>
                }

                @if (!isDemoMode() && (!isFreeConversationSession(s) || hintStack().length)) {
                  <section class="mt-4 rounded border border-white/10 bg-black/20 p-4">
                    <div class="flex items-center justify-between gap-3">
                      <div>
                        <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">
                          {{ isDemoMode() ? 'Prochaines questions' : 'Pile de relances' }}
                        </p>
                        <h3 class="text-sm font-semibold text-white">
                          {{ isDemoMode() ? 'À aborder pendant l’échange' : 'Questions disponibles hors navigation' }}
                        </h3>
                      </div>
                      @if (!isDemoMode()) {
                        <span class="text-xs text-gray-500">{{ planQuestions(s).length }} item(s)</span>
                      }
                    </div>
                    <div class="mt-3 grid gap-2 md:grid-cols-2">
                      @for (q of visibleQuestionStack(s); track q.id) {
                        <button
                          type="button"
                          class="text-left rounded border border-white/10 bg-white/[0.03] hover:bg-white/[0.06] p-3"
                          [class.ring-1]="selectedQuestionId() === q.id"
                          [class.ring-brand-400]="selectedQuestionId() === q.id"
                          (click)="selectCaptureQuestion(q)"
                        >
                          <div class="flex items-center justify-between gap-2">
                            <span class="text-xs text-brand-300 font-mono">{{ questionDisplayId(q) }}</span>
                            <span
                              [class]="selectedQuestionId() === q.id
                                ? 'text-[10px] uppercase tracking-wider px-2 py-0.5 rounded bg-brand-500/20 text-brand-100'
                                : 'text-[10px] uppercase tracking-wider px-2 py-0.5 rounded bg-white/5 text-gray-500'"
                            >
                              {{ questionStateLabel(s, q) }}
                            </span>
                          </div>
                          <p class="mt-2 text-sm text-gray-100 leading-snug line-clamp-2">{{ questionText(q) }}</p>
                          <p class="mt-2 text-[10px] text-gray-500">{{ q.path_label || 'Relance guidée' }}</p>
                        </button>
                      } @empty {
                        <div class="rounded border border-dashed border-white/10 bg-black/20 p-4 text-sm text-gray-400 md:col-span-2">
                          Les questions générées apparaîtront ici dès que la banque de relances est prête.
                        </div>
                      }
                    </div>
                    @if (topHint(); as hint) {
                      <div class="mt-3 rounded border border-brand-400/20 bg-brand-500/10 p-3">
                        <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-200">À préciser si pertinent</p>
                        <p class="mt-2 text-sm text-gray-100 leading-snug">{{ hint.hint || hint.full_question }}</p>
                      </div>
                    }
                  </section>
                }

                <div class="mt-4 flex-1 flex flex-col gap-3 min-h-0">
                  <div class="flex items-center justify-between gap-3">
                    <div>
                      <p class="ck-mono text-[9px] uppercase tracking-wider text-gray-500">
                        {{ isDemoMode() ? 'Échange avec l’expert' : 'Échange capturé' }}
                      </p>
                      <h3 class="text-xs font-medium text-gray-200">{{ voiceStateLabel() }}</h3>
                    </div>
                    @if (!isDemoMode()) {
                      @if (lastConversationStep(); as step) {
                        <span class="text-xs px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">
                          {{ step.intent }} · {{ (step.confidence * 100).toFixed(0) }}%
                        </span>
                      }
                    }
                  </div>
                  @if (isDemoMode() || !showAdvancedSetup()) {
                    <div class="relative flex-1 min-h-0 flex flex-col">
                      <div
                        #captureTranscriptScroll
                        class="flex-1 min-h-0 rounded bg-black/20 border border-white/10 p-5 overflow-y-auto leading-relaxed"
                        (scroll)="onTranscriptScroll()"
                      >
                        @for (row of captureTranscriptRows(); track row.key) {
                          @if (row.kind === 'topic') {
                            <p class="mt-6 first:mt-0 mb-2 ck-mono text-[10px] uppercase tracking-wider text-brand-300">{{ row.text }}</p>
                          } @else if (row.kind === 'ia') {
                            <p class="my-3 border-l-2 border-brand-400/40 pl-3 text-sm italic text-brand-200/90">{{ row.text }}</p>
                          } @else {
                            <p class="my-3 first:mt-0 text-sm text-gray-100 leading-relaxed whitespace-pre-wrap">{{ row.text }}@if (row.liveText) {<span [class]="row.liveCommitted ? 'text-gray-100' : 'text-gray-400 italic'">{{ row.text ? ' ' : '' }}{{ row.liveText }}</span>}</p>
                          }
                        } @empty {
                          <div class="flex h-full flex-col items-center justify-center text-center">
                            <p class="text-sm text-gray-400">La transcription de l’échange apparaîtra ici.</p>
                            <p class="mt-1 text-xs text-gray-600">{{ emptyConversationHint() }}</p>
                          </div>
                        }
                      </div>
                      @if (!transcriptAtBottom()) {
                        <button
                          type="button"
                          class="absolute bottom-3 right-3 inline-flex items-center gap-1.5 rounded-full bg-brand-500/90 hover:bg-brand-400 px-3 py-1.5 text-xs font-medium text-white shadow-lg"
                          (click)="jumpToLatestTranscript()"
                        >
                          <app-icon name="arrow-down" [size]="12" /> Dernier échange
                        </button>
                      }
                    </div>
                  }
                  @if (!isDemoMode() && showAdvancedSetup()) {
                  <div class="flex-1 min-h-80 rounded bg-black/20 border border-white/10 p-4 overflow-auto space-y-3">
                    <article class="rounded border border-brand-400/20 bg-brand-500/10 p-4">
                      <div class="flex items-center justify-between gap-3">
                        <span class="ck-mono text-[10px] uppercase tracking-wider text-brand-200">IA</span>
                        <span class="text-[10px] text-gray-500">{{ currentQuestion()?.estimated_minutes || 3 }} min</span>
                      </div>
                      <p class="mt-2 text-sm text-gray-100 leading-relaxed">
                        {{ currentPromptText() || 'La prochaine relance apparaîtra ici.' }}
                      </p>
                    </article>
                    @for (event of textEvents().slice(-5); track event.id) {
                      <article class="rounded border border-white/10 bg-white/[0.03] p-4">
                        <div class="flex items-center justify-between gap-3">
                          <span class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">
                            {{ conversationEventLabel(event) }}
                          </span>
                          <button type="button" class="text-xs text-brand-200 hover:text-brand-100" (click)="beginAmend(event)">
                            Amender
                          </button>
                        </div>
                        @if (editingEventId() === event.id) {
                          <textarea
                            class="mt-3 w-full min-h-20 rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white"
                            [ngModel]="editingText"
                            (ngModelChange)="editingText = $event"
                          ></textarea>
                          <div class="mt-2 flex gap-2">
                            <button type="button" class="px-3 py-1.5 rounded bg-brand-500 hover:bg-brand-400 text-xs text-white" (click)="applyAmend(s.id, event.id)">
                              Appliquer la correction
                            </button>
                            <button type="button" class="px-3 py-1.5 rounded bg-white/5 hover:bg-white/10 text-xs text-gray-300" (click)="editingEventId.set(null)">
                              Annuler
                            </button>
                          </div>
                        } @else if (eventDisplayText(event); as text) {
                          <p class="mt-2 text-sm text-gray-200 leading-relaxed whitespace-pre-wrap">{{ text }}</p>
                        }
                      </article>
                    } @empty {
                      <div class="rounded border border-dashed border-white/10 bg-black/20 p-6 text-center">
                        <p class="text-sm text-gray-400">Aucune réponse expert capturée pour l’instant.</p>
                        <p class="mt-1 text-xs text-gray-600">{{ emptyConversationHint() }}</p>
                      </div>
                    }
                    @if (answer.trim()) {
                      <article class="rounded border border-emerald-400/20 bg-emerald-500/10 p-4">
                        <span class="ck-mono text-[10px] uppercase tracking-wider text-emerald-200">Réponse en brouillon</span>
                        <p class="mt-2 text-sm text-gray-100 leading-relaxed whitespace-pre-wrap">{{ answer }}</p>
                      </article>
                    }
                  </div>
                  }
                  @if (showAnswerComposer(s)) {
                    <textarea
                      class="w-full min-h-28 rounded bg-black/30 border border-white/10 px-4 py-3 text-sm text-white leading-relaxed"
                      [(ngModel)]="answer"
                      (ngModelChange)="onAnswerDraftChange()"
                      placeholder="Saisir ou corriger la réponse expert avant évaluation..."
                    ></textarea>
                  }
                </div>

                <div class="mt-4 sticky bottom-3 z-30 rounded bg-black/70 border border-white/10 p-3 backdrop-blur">
                  <div class="flex flex-wrap items-center gap-3">
                    @if (sessionHasStarted(s)) {
                      <button
                        type="button"
                        class="inline-flex w-full items-center justify-center gap-2 px-4 py-2.5 rounded bg-brand-500 hover:bg-brand-400 text-sm font-semibold text-white disabled:opacity-50 sm:w-auto"
                        [disabled]="transcribing() || !canCaptureExecute(s)"
                        [title]="recording() ? 'Met le micro en pause sans déclencher de relance.' : 'Ouvre le micro pour parler librement.'"
                        (click)="onPrimaryCaptureAction(s)"
                      >
                        <app-icon [name]="conversationPrimaryIcon()" [size]="15" />
                        {{ conversationPrimaryLabel() }}
                      </button>
                      <label class="inline-flex w-full items-center gap-2 rounded border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-gray-300 sm:w-auto" [title]="voiceCaptureModeHint()">
                        <app-icon name="shield-check" [size]="13" class="text-emerald-300" />
                        <select
                          class="bg-transparent text-xs font-semibold text-gray-100 outline-none"
                          [ngModel]="voiceCaptureMode()"
                          (ngModelChange)="setVoiceCaptureMode($event)"
                        >
                          <option value="normal">Normal</option>
                          <option value="robust">Robuste</option>
                          <option value="manual_safe">Manuel</option>
                        </select>
                      </label>
                      @if (sessionHasStarted(s) && s.status === 'active') {
                        <button
                          type="button"
                          class="inline-flex w-full items-center justify-center gap-2 px-3 py-2.5 rounded bg-emerald-500/20 hover:bg-emerald-500/30 text-sm font-semibold text-emerald-100 ring-1 ring-emerald-400/20 disabled:opacity-50 sm:w-auto"
                          [disabled]="closureActionLoading() || transcribing()"
                          title="Clôt toutes les sections restantes et lance la phase finale (proposition)."
                          (click)="finishCapture(s)"
                        >
                          <app-icon name="flag" [size]="14" /> Terminer la capture
                        </button>
                      }
                      @if (speaking()) {
                        <button
                          type="button"
                          class="inline-flex w-full items-center justify-center gap-2 px-3 py-2.5 rounded bg-amber-500/20 hover:bg-amber-500/30 text-sm text-amber-100 ring-1 ring-amber-400/20 sm:w-auto"
                          title="Couper la lecture et répondre tout de suite (la conversation continue)."
                          (click)="interruptSpeech()"
                        >
                          <app-icon name="pause" [size]="14" /> Interrompre
                        </button>
                      }
                    } @else {
                      <button
                        type="button"
                        class="inline-flex w-full items-center justify-center gap-2 px-4 py-2.5 rounded bg-brand-500 hover:bg-brand-400 text-sm font-semibold text-white disabled:opacity-50 sm:w-auto"
                        [disabled]="loading() || !canCaptureExecute(s)"
                        (click)="startGuidedSession(s)"
                      >
                        <app-icon [name]="planStartIcon(s)" [size]="15" />
                        {{ loading() ? 'Préparation...' : planStartLabel(s) }}
                      </button>
                    }
                    @if (showAnswerComposer(s)) {
                      <button
                        type="button"
                        class="inline-flex w-full items-center justify-center gap-2 px-3 py-2.5 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-200 ring-1 ring-white/10 disabled:opacity-50 sm:w-auto"
                        [disabled]="!answer.trim() || !canCaptureUpdate(s)"
                        (click)="sendAnswer(s)"
                      >
                        <app-icon name="send" [size]="14" /> {{ captureAnswerActionLabel(s) }}
                      </button>
                      <button
                        type="button"
                        class="inline-flex w-full items-center justify-center gap-2 px-3 py-2.5 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-200 ring-1 ring-white/10 disabled:opacity-50 sm:w-auto"
                        [disabled]="!canProposalSubmit(s)"
                        (click)="createProposal(s)"
                      >
                        <app-icon name="arrow-right" [size]="14" /> {{ i18n.t('capture.action.continue') }}
                      </button>
                    }
                    <div class="min-w-0 w-full flex items-center gap-3 rounded bg-white/[0.03] px-3 py-2 sm:min-w-40 sm:flex-1">
                      <div class="flex h-7 items-center gap-1">
                        @for (bar of voiceWaveBars; track $index) {
                          <span
                            class="w-1 rounded-full bg-brand-300/80 transition-all"
                            [style.height.px]="voiceWaveHeight(bar)"
                          ></span>
                        }
                      </div>
                      <div class="min-w-0">
                        <div class="text-xs text-gray-200 truncate">{{ voiceInputStatusLabel() }}</div>
                        @if (voiceNotice(); as notice) {
                          <div [class]="voiceNoticeClass()">{{ notice }}</div>
                        } @else {
                          <div class="text-[10px] text-gray-500 truncate">
                            {{ showAdvancedSetup() ? voiceRuntimeArchitecture(s.voice_runtime) : 'Prêt à écouter l’expert' }}
                          </div>
                        }
                      </div>
                    </div>
                    @if (!isDemoMode()) {
                    <div class="flex items-center gap-2 text-xs text-gray-400">
                      <span class="px-2 py-1 rounded bg-white/5">{{ sessionStartStateLabel(s) }}</span>
                      <span class="px-2 py-1 rounded bg-white/5">{{ recording() ? 'enregistrement' : 'prêt' }}</span>
                      <span class="px-2 py-1 rounded bg-white/5">{{ speaking() ? 'restitution' : 'voix prête' }}</span>
                    </div>
                    }
                  </div>
                </div>

              </main>

              @if (!isDemoMode() && (showAdvancedSetup() || proposal())) {
              <aside class="space-y-4 max-h-[calc(100vh-270px)] overflow-auto">
                @if (!isDemoMode() && showAdvancedSetup()) {
                <section class="t-card rounded-lg p-4">
                  <div class="flex items-center justify-between gap-3">
                    <div>
                      <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Qualité</p>
                      <h3 class="text-sm font-semibold text-white mt-1">Points à clarifier</h3>
                    </div>
                    <span class="text-xs px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">
                      {{ qualityBacklogCount() }}
                    </span>
                  </div>
                  <div class="mt-3 flex gap-1">
                    @for (tab of qualityTabs; track tab.id) {
                      <button
                        type="button"
                        [class]="qualityTab() === tab.id
                          ? 'flex-1 px-2 py-1.5 rounded text-xs bg-brand-500/20 text-brand-100 ring-1 ring-brand-300/30'
                          : 'flex-1 px-2 py-1.5 rounded text-xs bg-white/5 text-gray-400 hover:text-gray-200'"
                        (click)="qualityTab.set(tab.id)"
                      >
                        {{ tab.label }}
                      </button>
                    }
                  </div>
                  <div class="mt-3 space-y-2 max-h-48 overflow-auto">
                    @for (item of activeQualityItems(); track item.id) {
                      <article class="rounded border border-white/10 bg-black/20 p-3">
                        <p class="text-xs text-gray-200">{{ item.label || item.follow_up }}</p>
                        <div class="mt-2 flex gap-2">
                          <button type="button" class="text-[10px] text-brand-200" (click)="respondToQualityItem(s, item)">Répondre maintenant</button>
                          <button type="button" class="text-[10px] text-gray-400" (click)="deferQualityItem(s, item)">Reporter</button>
                        </div>
                      </article>
                    } @empty {
                      <p class="text-xs text-gray-500">Aucun point dans cette catégorie pour l’instant.</p>
                    }
                  </div>
                </section>

                <section
                  [class]="conversationMode() === 'conversation_only'
                    ? 't-card rounded-lg p-4 bg-brand-500/5 border-brand-400/20'
                    : 't-card rounded-lg p-4'"
                >
                  <div class="flex items-start justify-between gap-3">
                    <div>
                      <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Mode de session</p>
                      <h3 class="text-sm font-semibold text-white mt-1">
                        {{ conversationMode() === 'conversation_only' ? 'Conversation autonome' : 'Capture guidée' }}
                      </h3>
                    </div>
                    @if (conversationSessionActive()) {
                      <span class="text-xs text-brand-100">Active</span>
                    }
                  </div>
                  @if (!isFreeConversationSession(s)) {
                    <div class="mt-3 grid grid-cols-2 gap-2">
                      <button
                        type="button"
                        [class]="conversationMode() === 'manual'
                          ? 'rounded border border-brand-300 bg-brand-500/15 px-3 py-2 text-left text-brand-100'
                          : 'rounded border border-white/10 bg-white/[0.03] px-3 py-2 text-left text-gray-300 hover:bg-white/[0.06]'"
                        (click)="setConversationMode('manual')"
                      >
                        <span class="flex items-center gap-2 text-xs font-semibold">
                          <app-icon name="list-checks" [size]="13" /> Guidé
                        </span>
                      </button>
                      <button
                        type="button"
                        [class]="conversationMode() === 'conversation_only'
                          ? 'rounded border border-brand-300 bg-brand-500/15 px-3 py-2 text-left text-brand-100'
                          : 'rounded border border-white/10 bg-white/[0.03] px-3 py-2 text-left text-gray-300 hover:bg-white/[0.06]'"
                        (click)="setConversationMode('conversation_only')"
                      >
                        <span class="flex items-center gap-2 text-xs font-semibold">
                          <app-icon name="message-circle" [size]="13" /> Conversation
                        </span>
                      </button>
                    </div>
                  }
                    @if (conversationMode() === 'conversation_only') {
                      <p class="mt-3 text-sm text-white">{{ lastConversationLabel() }}</p>
                      @if (nextPrompt()) {
                        <p class="mt-3 text-xs text-gray-300 leading-relaxed">{{ promptText(nextPrompt()) }}</p>
                      }
                    }
                    @if (isDemoMode()) {
                      @if (voiceNotice(); as notice) {
                        <p [class]="voiceNoticePanelClass()">{{ notice }}</p>
                      }
                    }
                  </section>

                @if (!isDemoMode()) {
                <section class="t-card rounded-lg p-4">
                  <div class="flex items-center justify-between gap-3">
                    <div>
                      <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">État de la conversation</p>
                      <h3 class="text-sm font-semibold text-white mt-1">{{ conversationStateHeadline(s) }}</h3>
                    </div>
                    @if (lastConversationStep(); as step) {
                      <span class="ck-mono text-[10px] text-brand-200">{{ (step.confidence * 100).toFixed(0) }}%</span>
                    }
                  </div>
                  <div class="mt-3 space-y-2">
                    @for (row of conversationStageRows(s); track row.id) {
                      <div [class]="conversationStageClass(row)">
                        <span
                          [class]="row.state === 'done'
                            ? 'inline-flex h-7 w-7 shrink-0 items-center justify-center rounded bg-emerald-500/20 text-emerald-100'
                            : row.state === 'active'
                              ? 'inline-flex h-7 w-7 shrink-0 items-center justify-center rounded bg-brand-500/20 text-brand-100'
                              : 'inline-flex h-7 w-7 shrink-0 items-center justify-center rounded bg-white/5 text-gray-500'"
                        >
                          <app-icon [name]="row.icon" [size]="13" />
                        </span>
                        <span class="min-w-0">
                          <span class="block text-xs font-semibold text-gray-100">{{ row.label }}</span>
                          <span class="mt-0.5 block text-[10px] text-gray-500 truncate">{{ row.detail }}</span>
                        </span>
                      </div>
                    }
                  </div>
                  @if (voiceNotice(); as notice) {
                    <p [class]="voiceNoticePanelClass()">{{ notice }}</p>
                  }
                </section>
                }

                @if (!isDemoMode() && showAdvancedSetup()) {
                  <section class="t-card rounded-lg p-4">
                    <div class="flex items-center justify-between gap-3">
                      <div>
                        <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Contexte retrouvé</p>
                        <h3 class="text-sm font-semibold text-white">{{ retrievalLabel() }}</h3>
                      </div>
                      @if (retrieval().latency_ms !== undefined) {
                        <span class="text-xs text-gray-500">{{ retrieval().latency_ms }} ms</span>
                      }
                    </div>
                    @if (retrieval().chunks.length) {
                      <div class="mt-3 space-y-2">
                        @for (chunk of retrieval().chunks.slice(0, 3); track retrievalChunkTrack($index, chunk); let ci = $index) {
                          <div class="rounded bg-black/20 border border-white/10 p-3">
                            <div class="flex items-start justify-between gap-2">
                              <p class="text-xs text-gray-400 line-clamp-3">{{ chunk }}</p>
                              @if (canPreviewRetrievalChunk(ci)) {
                                <button
                                  type="button"
                                  class="shrink-0 inline-flex items-center justify-center rounded p-1 text-gray-500 hover:text-brand-300 hover:bg-white/5 transition"
                                  title="Prévisualiser la source"
                                  (click)="previewRetrievalChunk(ci)"
                                >
                                  <app-icon name="eye" [size]="12" />
                                </button>
                              }
                            </div>
                            @if (retrievalChunkTitle(ci); as srcTitle) {
                              <p class="mt-1.5 text-[10px] uppercase tracking-wider text-gray-600 truncate">{{ srcTitle }}</p>
                            }
                          </div>
                        }
                      </div>
                    } @else {
                      <p class="mt-3 text-xs text-gray-500 leading-relaxed">
                        Les passages utiles apparaissent ici dès que la réponse devient assez précise. La conversation ne les attend pas.
                      </p>
                    }
                  </section>
                }
                }

                @if (proposal(); as p) {
                  <section class="t-card rounded-lg p-4">
                    <div class="flex items-center justify-between gap-3">
                      <div>
                        <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Rapport en brouillon</p>
                        <h3 class="text-sm font-semibold text-white">{{ proposalFacts().length }} fait(s)</h3>
                      </div>
                      <span class="text-xs text-gray-400">{{ workflowStatusLabel(p.status) }}</span>
                    </div>
                    <button type="button" class="mt-3 w-full px-3 py-2 rounded bg-brand-500/20 text-brand-100 ring-1 ring-brand-300/30" (click)="goSurface('review')">
                      Relire le rapport
                    </button>
                  </section>
                }
              </aside>
              }
            </section>
          </section>
        } @else {
          <section class="t-card rounded-lg p-8 text-center text-gray-400">
            Préparez une session de capture avant d’ouvrir l’échange.
          </section>
        }
      }

      @if (activeSurface() === 'plan') {
        @if (session(); as s) {
          <section class="grid xl:grid-cols-[minmax(0,1fr)_420px] gap-5">
            <div class="t-card rounded-lg p-5 space-y-4">
              <div class="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">
                    {{ isDemoMode() ? 'Plan d’échange' : 'Plan d’entretien' }}
                  </p>
                  <h2 class="text-lg font-semibold text-white mt-1">{{ s.title }}</h2>
                  <p class="text-sm text-gray-500 mt-1 max-w-3xl">{{ s.objective }}</p>
                </div>
                @if (!isDemoMode()) {
                <button
                  type="button"
                  class="inline-flex items-center gap-2 px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-200 ring-1 ring-white/10"
                  (click)="goSurface('session')"
                >
                  <app-icon name="eye" [size]="14" /> Prévisualiser l’échange
                </button>
                }
              </div>

              <div class="grid md:grid-cols-3 gap-3 text-sm">
                @if (isTopicOnlyPlan(s)) {
                  <div class="rounded bg-black/20 border border-white/10 p-3">
                    <div class="text-[10px] uppercase tracking-wider text-gray-500">Sous-sujets</div>
                    <div class="text-2xl text-white font-semibold">{{ planSubtopicCount(s) }}</div>
                  </div>
                  <div class="rounded bg-black/20 border border-white/10 p-3">
                    <div class="text-[10px] uppercase tracking-wider text-gray-500">Durée estimée</div>
                    <div class="text-2xl text-white font-semibold">{{ planDurationMinutes(s) }} min</div>
                  </div>
                  <div class="rounded bg-black/20 border border-white/10 p-3">
                    <div class="text-[10px] uppercase tracking-wider text-gray-500">
                      {{ isDemoMode() ? 'Préparation' : 'Préparation du plan' }}
                    </div>
                    <div class="text-sm text-gray-200 mt-2">{{ questionBankStatusLabel(s) }}</div>
                  </div>
                } @else {
                  <div class="rounded bg-black/20 border border-white/10 p-3">
                    <div class="text-[10px] uppercase tracking-wider text-gray-500">Sous-sujets</div>
                    <div class="text-2xl text-white font-semibold">{{ planSubtopicCount(s) }}</div>
                  </div>
                  <div class="rounded bg-black/20 border border-white/10 p-3">
                    <div class="text-[10px] uppercase tracking-wider text-gray-500">Durée estimée</div>
                    <div class="text-2xl text-white font-semibold">{{ planDurationMinutes(s) }} min</div>
                  </div>
                }
                @if (!isDemoMode()) {
                <div class="rounded bg-black/20 border border-white/10 p-3">
                  <div class="text-[10px] uppercase tracking-wider text-gray-500">Destination</div>
                  <div class="text-sm text-gray-200 mt-2 truncate">{{ selectedContext()?.environment_state?.collection || 'Sources par défaut du workspace' }}</div>
                </div>
                }
              </div>

              @if (planNotice(); as notice) {
                <div [class]="planNoticeClass(notice.tone)">
                  {{ notice.text }}
                </div>
              }

              @if (isTopicOnlyPlan(s)) {
                <div class="space-y-2">
                  <div class="flex flex-wrap items-center justify-between gap-2">
                    <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Plan</p>
                    @if (canEditPlan(s)) {
                      <div class="flex flex-wrap items-center gap-1.5">
                        <button type="button" class="inline-flex h-9 w-9 items-center justify-center rounded bg-white/5 text-gray-300 ring-1 ring-white/10 hover:bg-white/10" title="Désindenter (Shift+Tab)" aria-label="Désindenter" (click)="applyPlanOutlineFormatFrom('plan', s, 'outdent')">
                          <app-icon name="list-indent-decrease" [size]="15" />
                        </button>
                        <button type="button" class="inline-flex h-9 w-9 items-center justify-center rounded bg-white/5 text-gray-300 ring-1 ring-white/10 hover:bg-white/10" title="Indenter (Tab)" aria-label="Indenter" (click)="applyPlanOutlineFormatFrom('plan', s, 'indent')">
                          <app-icon name="list-indent-increase" [size]="15" />
                        </button>
                        <button type="button" class="inline-flex h-9 w-9 items-center justify-center rounded bg-white/5 text-gray-300 ring-1 ring-white/10 hover:bg-white/10" title="Remettre en forme la numérotation" aria-label="Remettre en forme la numérotation" (click)="applyPlanOutlineFormatFrom('plan', s, 'renumber')">
                          <app-icon name="list-ordered" [size]="15" />
                        </button>
                        <button type="button" class="inline-flex h-9 w-9 items-center justify-center rounded bg-white/5 text-gray-300 ring-1 ring-white/10 hover:bg-white/10" title="Monter la sélection" aria-label="Monter la sélection" (click)="applyPlanOutlineFormatFrom('plan', s, 'move_up')">
                          <app-icon name="arrow-up" [size]="15" />
                        </button>
                        <button type="button" class="inline-flex h-9 w-9 items-center justify-center rounded bg-white/5 text-gray-300 ring-1 ring-white/10 hover:bg-white/10" title="Descendre la sélection" aria-label="Descendre la sélection" (click)="applyPlanOutlineFormatFrom('plan', s, 'move_down')">
                          <app-icon name="arrow-down" [size]="15" />
                        </button>
                        <label
                          class="inline-flex h-9 cursor-pointer items-center gap-2 rounded bg-white/5 px-3 text-xs font-semibold text-gray-300 ring-1 ring-white/10 hover:bg-white/10 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-50"
                          title="Importer un fichier de plan"
                        >
                          <app-icon [name]="extractingPlanSource() ? 'loader-2' : 'upload'" [size]="14" [class]="extractingPlanSource() ? 'animate-spin' : ''" />
                          Importer
                          <input
                            type="file"
                            class="hidden"
                            accept=".txt,.text,.md,.markdown,.csv,.tsv,.json,.yaml,.yml,.rtf,.html,.htm,.xml,.log,.pdf,.docx,text/*,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                            [disabled]="extractingPlanSource()"
                            (change)="onPlanOutlineImportFile($event, s)"
                          />
                        </label>
                      </div>
                    }
                  </div>
                  <textarea
                    #planOutlineEditor
                    class="min-h-[22rem] w-full rounded border border-white/10 bg-black/30 px-4 py-3 font-mono text-sm leading-6 text-gray-100 outline-none focus:border-brand-300 disabled:opacity-60"
                    [ngModel]="planOutlineText(s)"
                    (ngModelChange)="updatePlanOutlineText(s, $event)"
                    (keydown)="onPlanOutlineKeydown($event, s)"
                    [disabled]="!canEditPlan(s)"
                    spellcheck="false"
                  ></textarea>
                </div>
              } @else {
              <div class="space-y-4">
                @for (topic of planTopics(s); track topic.id) {
                  <section class="rounded border border-white/10 bg-white/[0.025] p-4 space-y-4">
                    <div class="flex flex-wrap items-start justify-between gap-3">
                      <div class="min-w-0 flex-1">
                        <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Sujet</p>
                        <input
                          class="mt-1 w-full rounded bg-black/20 border border-white/10 px-3 py-2 text-base font-semibold text-white disabled:opacity-70"
                          [(ngModel)]="topic.title"
                          [disabled]="!canEditPlan(s)"
                          (ngModelChange)="touchPlanDraft()"
                        />
                        <p class="mt-2 text-xs text-gray-500">{{ outlineItemPrompt(topic) || topic.objective || 'Sujet à présenter' }}</p>
                      </div>
                      <span class="rounded bg-brand-500/10 text-brand-100 border border-brand-300/20 px-2 py-1 text-xs">
                        {{ (topic.subtopics || []).length }} sous-sujets
                      </span>
                    </div>

                    @for (subtopic of topic.subtopics || []; track subtopic.id) {
                      <div class="rounded border border-white/10 bg-black/15 p-3 space-y-3">
                        <div>
                          <p class="ck-mono text-[9px] uppercase tracking-wider text-gray-500">Sous-sujet</p>
                          <input
                            class="mt-1 w-full rounded bg-black/20 border border-white/10 px-3 py-2 text-sm font-semibold text-gray-100 disabled:opacity-70"
                            [(ngModel)]="subtopic.title"
                            [disabled]="!canEditPlan(s)"
                            (ngModelChange)="touchPlanDraft()"
                          />
                          @if (isTopicOnlyPlan(s)) {
                            <textarea
                              class="mt-2 w-full min-h-16 rounded bg-black/20 border border-white/10 px-3 py-2 text-xs text-gray-300 disabled:opacity-70"
                              [(ngModel)]="subtopic.objective"
                              [disabled]="!canEditPlan(s)"
                              (ngModelChange)="touchPlanDraft()"
                            ></textarea>
                          }
                        </div>

                        @if (isTopicOnlyPlan(s) && (subtopic.questions || []).length) {
                          <div class="space-y-1.5">
                            <p class="ck-mono text-[9px] uppercase tracking-wider text-gray-500">Points à présenter</p>
                            @for (point of subtopic.questions || []; track point.id) {
                              <div class="rounded border border-white/10 bg-white/[0.03] px-3 py-2">
                                <p class="text-xs text-gray-200 leading-relaxed">{{ outlineItemLabel(point) || 'Point à présenter' }}</p>
                              </div>
                            }
                          </div>
                        }

                        @if (!isTopicOnlyPlan(s) && isDemoMode()) {
                          @for (q of subtopic.questions || []; track q.id) {
                            <div class="rounded border border-white/10 bg-white/[0.03] p-3">
                              <p class="text-sm text-gray-100 leading-relaxed">{{ outlineItemLabel(q) || 'Point à présenter' }}</p>
                            </div>
                          }
                        }
                        @if (!isTopicOnlyPlan(s) && !isDemoMode()) {
                          @for (q of subtopic.questions || []; track q.id; let i = $index) {
                          <div
                            class="rounded border border-white/10 bg-white/[0.03] p-4"
                            [class.ring-1]="selectedQuestionId() === q.id"
                            [class.ring-brand-400]="selectedQuestionId() === q.id"
                          >
                            <div class="flex flex-wrap items-center justify-between gap-3">
                              <button
                                type="button"
                                class="inline-flex items-center gap-2 text-xs text-brand-200 hover:text-brand-100"
                                (click)="selectedQuestionId.set(q.id)"
                              >
                                <span class="ck-mono">{{ questionDisplayId(q) }}</span>
                                <span
                                  [class]="selectedQuestionId() === q.id
                                    ? 'text-[10px] uppercase tracking-wider px-2 py-1 rounded bg-brand-500/20 text-brand-100'
                                    : 'text-[10px] uppercase tracking-wider px-2 py-1 rounded bg-white/5 text-gray-400'"
                                >
                                  {{ questionStateLabel(s, q) }}
                                </span>
                              </button>
                              <div class="flex items-center gap-2">
                                <input
                                  type="number"
                                  min="1"
                                  max="30"
                                  class="w-16 rounded bg-black/20 border border-white/10 px-2 py-1 text-xs text-gray-200 disabled:opacity-70"
                                  [(ngModel)]="q.estimated_minutes"
                                  [disabled]="!canEditPlan(s)"
                                  (ngModelChange)="touchPlanDraft()"
                                />
                                <span class="text-xs text-gray-500">min</span>
                                <button
                                  type="button"
                                  class="rounded bg-white/5 hover:bg-white/10 p-1.5 text-gray-300 disabled:opacity-30"
                                  [disabled]="!canEditPlan(s) || i === 0"
                                  (click)="moveQuestion(s, subtopic, i, -1)"
                                  title="Monter la question"
                                >
                                  <app-icon name="arrow-up" [size]="13" />
                                </button>
                                <button
                                  type="button"
                                  class="rounded bg-white/5 hover:bg-white/10 p-1.5 text-gray-300 disabled:opacity-30"
                                  [disabled]="!canEditPlan(s) || i >= ((subtopic.questions || []).length - 1)"
                                  (click)="moveQuestion(s, subtopic, i, 1)"
                                  title="Descendre la question"
                                >
                                  <app-icon name="arrow-down" [size]="13" />
                                </button>
                                <button
                                  type="button"
                                  class="rounded bg-red-500/10 hover:bg-red-500/20 p-1.5 text-red-200 disabled:opacity-30"
                                  [disabled]="!canEditPlan(s) || planQuestions(s).length <= 1"
                                  (click)="removeQuestion(s, subtopic, i)"
                                  title="Supprimer la question"
                                >
                                  <app-icon name="trash-2" [size]="13" />
                                </button>
                              </div>
                            </div>
                            <textarea
                              class="mt-3 w-full min-h-24 rounded bg-black/20 border border-white/10 px-3 py-2 text-sm text-gray-100 leading-relaxed disabled:opacity-70"
                              [(ngModel)]="q.question"
                              [disabled]="!canEditPlan(s)"
                              (ngModelChange)="touchPlanDraft()"
                            ></textarea>
                          </div>
                          }

                          <button
                            type="button"
                            class="inline-flex items-center gap-2 rounded bg-white/5 hover:bg-white/10 px-3 py-2 text-xs text-gray-200 disabled:opacity-40"
                            [disabled]="!canEditPlan(s)"
                            (click)="addQuestion(s, topic, subtopic)"
                          >
                            <app-icon name="plus" [size]="13" /> Ajouter une question
                          </button>
                        }
                      </div>
                    }
                  </section>
                }
              </div>
              }

            </div>

            <aside class="t-card rounded-lg p-5 space-y-4 xl:sticky xl:top-4">
              <div>
                <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">
                  {{ i18n.t('capture.action.continue') }}
                </p>
                <h3 class="text-sm font-semibold text-white mt-1">
                  {{ isDemoMode() ? i18n.t('capture.plan.ready_exchange') : i18n.t('capture.plan.ready_capture') }}
                </h3>
              </div>
              @if (isTopicOnlyPlan(s)) {
                <div class="rounded bg-black/20 border border-white/10 px-3 py-2.5" role="status" aria-live="polite">
                  <div class="flex items-center gap-2">
                    @if ((s.plan.question_bank_status || questionBankStatus()) === 'generating') {
                      <app-icon name="check-circle-2" [size]="13" class="shrink-0 text-emerald-300" />
                      <span class="text-xs text-gray-300">{{ questionBankStatusLabel(s) }}</span>
                      <span class="ml-auto shrink-0 rounded-full bg-white/5 px-2 py-0.5 text-[9px] uppercase tracking-wider text-gray-500">
                        prêt
                      </span>
                    } @else if ((s.plan.question_bank_status || questionBankStatus()) === 'ready') {
                      <app-icon name="check-circle-2" [size]="13" class="shrink-0 text-emerald-300" />
                      <span class="text-xs text-gray-300">{{ questionBankStatusLabel(s) }}</span>
                    } @else {
                      <app-icon name="info" [size]="13" class="shrink-0 text-gray-500" />
                      <span class="text-xs text-gray-400">{{ questionBankStatusLabel(s) }}</span>
                    }
                  </div>
                </div>
              }
              @if (!isDemoMode()) {
              @if (showAdvancedSetup()) {
              <div class="space-y-2 text-xs">
                <div class="rounded bg-black/20 border border-white/10 p-3">
                  <span class="block text-[9px] uppercase tracking-wider text-gray-500">Contexte</span>
                  <span class="text-gray-200">{{ contextLabel(s.context_id) }}</span>
                </div>
                <div class="rounded bg-black/20 border border-white/10 p-3">
                  <span class="block text-[9px] uppercase tracking-wider text-gray-500">Intervenant</span>
                  <span class="text-gray-200">{{ expertProfile }}</span>
                </div>
                <div class="rounded bg-black/20 border border-white/10 p-3">
                  <span class="block text-[9px] uppercase tracking-wider text-gray-500">Voix</span>
                  <span class="text-gray-200">{{ voiceRuntimeArchitecture(s.voice_runtime) }}</span>
                </div>
                <div class="rounded bg-black/20 border border-white/10 p-3">
                  <span class="block text-[9px] uppercase tracking-wider text-gray-500">État</span>
                  <span class="text-gray-200">{{ sessionStartStateLabel(s) }} · {{ planReviewLabel(s) }}</span>
                </div>
              </div>
              }
              <div>
                <button
                  type="button"
                  class="w-full inline-flex items-center justify-center gap-2 px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-xs font-semibold text-gray-200 disabled:opacity-40"
                  [disabled]="savingPlan() || !canEditPlan(s)"
                  (click)="savePlan(s)"
                >
                  <app-icon name="save" [size]="13" /> Enregistrer le plan
                </button>
              </div>
              <div class="rounded bg-black/20 border border-white/10 p-3">
                <span class="block text-[9px] uppercase tracking-wider text-gray-500 mb-2">Mode de session</span>
                <div class="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    [class]="conversationMode() === 'manual'
                      ? 'rounded border border-brand-300 bg-brand-500/15 px-3 py-2 text-left text-brand-100'
                      : 'rounded border border-white/10 bg-white/[0.03] px-3 py-2 text-left text-gray-300 hover:bg-white/[0.06]'"
                    (click)="setConversationMode('manual')"
                  >
                    <span class="flex items-center gap-2 text-xs font-semibold">
                      <app-icon name="list-checks" [size]="13" /> Guidé
                    </span>
                    <span class="mt-1 block text-[10px] text-gray-500">Tour par tour</span>
                  </button>
                  <button
                    type="button"
                    [class]="conversationMode() === 'conversation_only'
                      ? 'rounded border border-brand-300 bg-brand-500/15 px-3 py-2 text-left text-brand-100'
                      : 'rounded border border-white/10 bg-white/[0.03] px-3 py-2 text-left text-gray-300 hover:bg-white/[0.06]'"
                    (click)="setConversationMode('conversation_only')"
                  >
                    <span class="flex items-center gap-2 text-xs font-semibold">
                      <app-icon name="message-circle" [size]="13" /> Conversation
                    </span>
                    <span class="mt-1 block text-[10px] text-gray-500">Piloté à la voix</span>
                  </button>
                </div>
              </div>
              }
              @if (isDemoMode()) {
                <p class="text-[10px] uppercase tracking-wider text-brand-300/80">{{ i18n.t('capture.action.primary') }}</p>
              }
              <button
                type="button"
                class="w-full inline-flex items-center justify-center gap-2 px-3 py-3 rounded bg-brand-500 hover:bg-brand-400 text-sm font-semibold text-white disabled:opacity-50"
                [disabled]="loading() || !canCaptureExecute(s) || !canStartSessionPlan(s)"
                [title]="planBlockingReason(s)
                  || i18n.t('capture.plan.start_hint')"
                (click)="startGuidedSession(s)"
              >
                <app-icon [name]="planStartIcon(s)" [size]="14" /> {{ planStartLabel(s) }}
              </button>
              @if (planBlockingReason(s); as reason) {
                <p class="text-[11px] leading-relaxed text-amber-200/85">{{ reason }}</p>
              }
            </aside>
          </section>
        } @else {
          @if (planSourceStep()) {
            <section class="max-w-5xl mx-auto py-8 space-y-7">
              <div>
                <p class="ck-mono text-[10px] uppercase tracking-[0.18em] text-gray-500">Source du plan</p>
                <h2 class="mt-2 text-3xl text-white font-semibold">Donner le texte source</h2>
                <p class="mt-2 text-sm text-gray-400 max-w-3xl">
                  Fichier, copier-coller ou saisie libre : le texte est transformé en plan éditable.
                </p>
              </div>

              <section class="rounded-lg border border-white/10 bg-white/[0.03] p-5 space-y-4">
                <div class="flex flex-wrap items-center gap-3">
                  <label class="inline-flex cursor-pointer items-center gap-2 rounded bg-brand-500/20 px-4 py-2.5 text-sm font-semibold text-brand-100 ring-1 ring-brand-300/20 hover:bg-brand-500/30">
                    <app-icon name="upload" [size]="14" /> Fichier
                    <input
                      type="file"
                      class="hidden"
                      accept=".txt,.text,.md,.markdown,.csv,.tsv,.json,.yaml,.yml,.rtf,.html,.htm,.xml,.log,.pdf,.docx,text/*,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                      (change)="onProvidedPlanFile($event)"
                    />
                  </label>
                  @if (extractingPlanSource()) {
                    <span class="inline-flex items-center gap-2 text-sm text-brand-100">
                      <app-icon name="loader-2" [size]="14" class="animate-spin" /> Extraction...
                    </span>
                  }
                </div>
                @if (pendingPlanSourceReplacement(); as pending) {
                  <div class="rounded border border-amber-300/30 bg-amber-500/10 p-4">
                    <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div class="min-w-0">
                        <p class="text-sm font-semibold text-amber-100">{{ i18n.t('capture.plan.replace_prompt') }}</p>
                        <p class="mt-1 truncate text-xs text-amber-100/80">
                          {{ pending.filename }} · {{ pendingPlanSourceStats(pending) }}
                        </p>
                      </div>
                      <div class="flex shrink-0 flex-wrap gap-2">
                        <button
                          type="button"
                          class="inline-flex items-center gap-2 rounded bg-amber-300 px-3 py-2 text-xs font-semibold text-black hover:bg-amber-200"
                          (click)="confirmProvidedPlanReplacement()"
                        >
                          Remplacer
                        </button>
                        <button
                          type="button"
                          class="inline-flex items-center gap-2 rounded bg-white/5 px-3 py-2 text-xs font-semibold text-gray-200 ring-1 ring-white/10 hover:bg-white/10"
                          (click)="cancelProvidedPlanReplacement()"
                        >
                          Garder le plan
                        </button>
                      </div>
                    </div>
                  </div>
                }
                @if (hasProvidedPlanSource()) {
                  <div class="rounded border border-brand-300/25 bg-brand-500/10 p-4">
                    <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div class="min-w-0">
                        <p class="ck-mono text-[10px] uppercase tracking-[0.18em] text-brand-200">
                          {{ providedPlanSourceKindLabel() }}
                        </p>
                        <h3 class="mt-1 truncate text-sm font-semibold text-white">{{ providedPlanSourceLabel() }}</h3>
                        <p class="mt-1 text-xs text-gray-400">{{ providedPlanSourceStats() }}</p>
                      </div>
                      <button
                        type="button"
                        class="inline-flex shrink-0 items-center gap-2 rounded bg-white/5 px-3 py-2 text-xs font-semibold text-gray-200 ring-1 ring-white/10 hover:bg-white/10"
                        [disabled]="extractingPlanSource()"
                        (click)="clearProvidedPlanSource()"
                      >
                        Retirer
                      </button>
                    </div>
                    <p class="mt-3 line-clamp-3 text-xs leading-relaxed text-gray-300">{{ providedPlanSourcePreview() }}</p>
                  </div>
                }
                <div>
                  <div class="mb-2 flex items-center justify-between gap-3">
                    <label class="ck-mono text-[10px] uppercase tracking-[0.18em] text-gray-500">
                      Plan extrait et éditable
                    </label>
                    @if (providedPlanText.trim()) {
                      <span class="text-[11px] text-gray-500">{{ providedPlanSourceStats() }}</span>
                    }
                  </div>
                <textarea
                  class="min-h-[24rem] w-full rounded border border-white/10 bg-black/30 px-4 py-3 font-mono text-sm leading-6 text-gray-100 outline-none focus:border-brand-300 disabled:opacity-60"
                  [ngModel]="providedPlanText"
                  (ngModelChange)="onProvidedPlanTextChange($event)"
                  [disabled]="extractingPlanSource()"
                  spellcheck="false"
                ></textarea>
                </div>
                @if (!providedPlanText.trim()) {
                  <p class="text-xs text-amber-200/90">Ajoutez un texte source pour construire le plan.</p>
                }
              </section>

              <div class="flex items-center justify-between gap-3 pt-4">
                <button
                  type="button"
                  class="inline-flex items-center gap-2 px-4 py-2 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-300 ring-1 ring-white/10"
                  (click)="backToPlanModeSelection()"
                >
                  <app-icon name="arrow-left" [size]="14" /> Retour
                </button>
                <button
                  type="button"
                  class="inline-flex items-center gap-2 px-5 py-2.5 rounded bg-brand-300 hover:bg-brand-200 text-sm font-semibold text-black disabled:opacity-50"
                  [disabled]="loading() || extractingPlanSource() || !canSubmitProvidedPlanSource()"
                  (click)="createPlan()"
                >
                  {{ loading() ? i18n.t('capture.action.preparing') : i18n.t('capture.action.continue') }}
                  <app-icon name="arrow-right" [size]="14" />
                </button>
              </div>
            </section>
          } @else {
            <section class="max-w-3xl mx-auto py-10 space-y-4 text-center">
              <p class="ck-mono text-[10px] uppercase tracking-[0.18em] text-gray-500">Préparation</p>
              <h2 class="text-2xl text-white font-semibold">Revenir à la préparation</h2>
              <p class="text-sm text-gray-400">
                Choisissez un déroulé, puis continuez directement vers la capture.
              </p>
              <button
                type="button"
                class="inline-flex items-center gap-2 px-4 py-2 rounded bg-brand-500 hover:bg-brand-400 text-sm font-semibold text-white"
                (click)="goSurface('prep')"
              >
                <app-icon name="arrow-left" [size]="14" /> Retour à la préparation
              </button>
            </section>
          }
        }
      }

      @if (activeSurface() === 'plan_build') {
        @if (session(); as s) {
          <section class="grid xl:grid-cols-[minmax(0,1fr)_420px] gap-5">
            <div class="t-card rounded-lg p-5 space-y-4">
              <div>
                <p class="ck-mono text-[10px] uppercase tracking-[0.18em] text-gray-500">
                  {{ isProvidedPlanSession(s) ? 'Plan fourni' : 'Modifier le plan' }}
                </p>
                <h2 class="mt-2 text-2xl text-white font-semibold">{{ s.title }}</h2>
                <p class="mt-2 text-sm text-gray-400">
                  @if (isProvidedPlanSession(s)) {
                    Ajustez l’arborescence importée, puis validez les sujets.
                  } @else {
                    Modifiez l’arborescence, puis continuez vers la capture.
                  }
                </p>
              </div>
              @if (planSourceSummary(s); as source) {
                <section class="rounded border border-brand-300/25 bg-brand-500/10 p-4 space-y-3">
                  <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div class="min-w-0">
                      <p class="ck-mono text-[10px] uppercase tracking-[0.18em] text-brand-200">Source du plan · {{ source.kindLabel }}</p>
                      <h3 class="mt-1 truncate text-sm font-semibold text-white">{{ source.title }}</h3>
                      <p class="mt-1 text-xs text-gray-400">{{ source.stats }}</p>
                    </div>
                    @if (source.replacedExistingPlan) {
                      <span class="shrink-0 rounded bg-amber-500/15 px-2 py-1 text-[10px] uppercase tracking-wider text-amber-100 ring-1 ring-amber-300/20">
                        Remplacement confirmé
                      </span>
                    }
                  </div>
                  @if (source.extractedOutline.length) {
                    <div class="rounded border border-white/10 bg-black/20 p-3">
                      <p class="ck-mono text-[10px] uppercase tracking-[0.18em] text-gray-500">Interprétation extraite</p>
                      <div class="mt-3 grid gap-2 md:grid-cols-2">
                        @for (item of source.extractedOutline; track $index) {
                          <article class="rounded border border-white/10 bg-white/[0.03] p-3">
                            <p class="text-xs font-semibold text-gray-100 line-clamp-2">{{ item.title }}</p>
                            @if (item.subtopics.length) {
                              <p class="mt-1 text-[11px] leading-relaxed text-gray-500 line-clamp-2">
                                {{ item.subtopics.join(' · ') }}
                              </p>
                            }
                          </article>
                        }
                      </div>
                    </div>
                  }
                </section>
              }
              <div class="space-y-2">
                <div class="flex flex-wrap items-center justify-between gap-2">
                  <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Plan</p>
                  @if (canEditPlan(s)) {
                    <div class="flex flex-wrap items-center gap-1.5">
                      <button type="button" class="inline-flex h-9 w-9 items-center justify-center rounded bg-white/5 text-gray-300 ring-1 ring-white/10 hover:bg-white/10" title="Désindenter (Shift+Tab)" aria-label="Désindenter" (click)="applyPlanOutlineFormatFrom('plan_build', s, 'outdent')">
                        <app-icon name="list-indent-decrease" [size]="15" />
                      </button>
                      <button type="button" class="inline-flex h-9 w-9 items-center justify-center rounded bg-white/5 text-gray-300 ring-1 ring-white/10 hover:bg-white/10" title="Indenter (Tab)" aria-label="Indenter" (click)="applyPlanOutlineFormatFrom('plan_build', s, 'indent')">
                        <app-icon name="list-indent-increase" [size]="15" />
                      </button>
                      <button type="button" class="inline-flex h-9 w-9 items-center justify-center rounded bg-white/5 text-gray-300 ring-1 ring-white/10 hover:bg-white/10" title="Remettre en forme la numérotation" aria-label="Remettre en forme la numérotation" (click)="applyPlanOutlineFormatFrom('plan_build', s, 'renumber')">
                        <app-icon name="list-ordered" [size]="15" />
                      </button>
                      <button type="button" class="inline-flex h-9 w-9 items-center justify-center rounded bg-white/5 text-gray-300 ring-1 ring-white/10 hover:bg-white/10" title="Monter la sélection" aria-label="Monter la sélection" (click)="applyPlanOutlineFormatFrom('plan_build', s, 'move_up')">
                        <app-icon name="arrow-up" [size]="15" />
                      </button>
                      <button type="button" class="inline-flex h-9 w-9 items-center justify-center rounded bg-white/5 text-gray-300 ring-1 ring-white/10 hover:bg-white/10" title="Descendre la sélection" aria-label="Descendre la sélection" (click)="applyPlanOutlineFormatFrom('plan_build', s, 'move_down')">
                        <app-icon name="arrow-down" [size]="15" />
                      </button>
                    </div>
                  }
                </div>
                <textarea
                  #planBuildOutlineEditor
                  class="min-h-[22rem] w-full rounded border border-white/10 bg-black/30 px-4 py-3 font-mono text-sm leading-6 text-gray-100 outline-none focus:border-brand-300 disabled:opacity-60"
                  [ngModel]="planOutlineText(s)"
                  (ngModelChange)="updatePlanOutlineText(s, $event)"
                  (keydown)="onPlanOutlineKeydown($event, s)"
                  [disabled]="!canEditPlan(s)"
                  spellcheck="false"
                ></textarea>
              </div>
            </div>
            <aside class="t-card rounded-lg p-5 space-y-4">
              <div>
                <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Modifier le plan</p>
                <p class="mt-2 text-sm text-gray-300 leading-relaxed">Indiquez quoi ajouter, déplacer ou reformuler dans le plan à gauche.</p>
              </div>
              <div class="space-y-2">
                <div class="flex items-start gap-2">
                  <textarea
                    #planDialogueAnswerEditor
                    class="w-full min-h-24 rounded bg-black/30 border border-white/10 px-4 py-3 text-sm text-white disabled:opacity-60 transition-colors"
                    [class.border-brand-300/35]="planDictationActive()"
                    [class.ring-1]="planDictationActive()"
                    [class.ring-brand-300/15]="planDictationActive()"
                    [ngModel]="planDialogueAnswer()"
                    (ngModelChange)="planDialogueAnswer.set($event)"
                    [disabled]="planDialogueLoading()"
                    placeholder="Ajoutez un point, fusionnez deux sections, simplifiez les titres..."
                  ></textarea>
                  <button
                    type="button"
                    class="shrink-0 inline-flex h-11 w-11 items-center justify-center rounded-full ring-1 transition-colors"
                    [class.bg-brand-500/20]="!planDictationActive()"
                    [class.text-brand-100]="!planDictationActive()"
                    [class.ring-brand-300/30]="!planDictationActive()"
                    [class.hover:bg-brand-500/30]="!planDictationActive()"
                    [class.bg-brand-500/35]="planDictationListening()"
                    [class.text-brand-50]="planDictationListening()"
                    [class.ring-brand-300/55]="planDictationListening()"
                    [class.animate-pulse]="planDictationListening() && !dictationVoiceDetected()"
                    [class.bg-brand-500/25]="planDictationTranscribing()"
                    [class.text-brand-200]="planDictationTranscribing()"
                    [class.ring-brand-300/40]="planDictationTranscribing()"
                    [attr.aria-label]="recording() ? 'Arrêter et transcrire la dictée' : 'Dicter la réponse'"
                    [title]="recording() ? 'Arrêter et transcrire la dictée' : 'Dicter la réponse'"
                    (click)="dictatePlanDialogue()"
                  >
                    @if (planDictationTranscribing()) {
                      <span class="inline-block h-4 w-4 rounded-full border-2 border-brand-200/40 border-t-brand-200 animate-spin"></span>
                    } @else {
                      <app-icon [name]="recording() ? 'square' : 'mic'" [size]="16" />
                    }
                  </button>
                </div>
                @if (planDictationActive()) {
                  <div class="flex items-center gap-2 rounded bg-brand-500/10 border border-brand-300/15 px-3 py-2">
                    <div class="flex h-5 items-center gap-0.5 shrink-0" aria-hidden="true">
                      @for (bar of planDictationWaveBars; track $index) {
                        <span
                          class="w-0.5 rounded-full bg-brand-300/80 transition-all duration-75"
                          [style.height.px]="planDictationWaveHeight(bar)"
                        ></span>
                      }
                    </div>
                    <p class="text-[11px] leading-relaxed text-brand-200/90">{{ planDictationStatusLabel() }}</p>
                  </div>
                }
              </div>
              <div class="flex flex-wrap gap-2">
                <button
                  type="button"
                  class="inline-flex items-center gap-2 px-4 py-2 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-200 ring-1 ring-white/10 disabled:opacity-50"
                  title="Applique votre instruction au plan courant."
                  [disabled]="planDialogueLoading()"
                  (click)="submitPlanDialogueTurn(s)"
                >
                  @if (planDialogueLoading()) {
                    <span class="inline-block h-3.5 w-3.5 rounded-full border-2 border-white/40 border-t-white animate-spin"></span>
                    Analyse…
                  } @else {
                    Appliquer
                  }
                </button>
                <label
                  class="inline-flex cursor-pointer items-center gap-2 px-4 py-2 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-200 ring-1 ring-white/10 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-50"
                  [title]="i18n.t('capture.plan.import_instruction_hint')"
                >
                  <app-icon [name]="extractingPlanSource() ? 'loader-2' : 'upload'" [size]="14" [class]="extractingPlanSource() ? 'animate-spin' : ''" />
                  {{ i18n.t('capture.plan.import_instruction') }}
                  <input
                    type="file"
                    class="hidden"
                    accept=".txt,.text,.md,.markdown,.csv,.tsv,.json,.yaml,.yml,.rtf,.html,.htm,.xml,.log,.pdf,.docx,text/*,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    [disabled]="extractingPlanSource() || planDialogueLoading() || !canEditPlan(s)"
                    (change)="onPlanInstructionImportFile($event, s)"
                  />
                </label>
                <button
                  type="button"
                  class="inline-flex items-center gap-2 px-5 py-2 rounded bg-emerald-500 hover:bg-emerald-400 text-sm font-semibold text-white shadow-lg shadow-emerald-500/20 disabled:opacity-50 disabled:shadow-none"
                  [title]="i18n.t('capture.notice.plan_ready')"
                  [disabled]="(!planDialogueReady(s) && !planTopics(s).length) || planDialogueLoading()"
                  (click)="finalizePlanBuild(s)"
                >
                  <app-icon name="check" [size]="14" />
                  {{ i18n.t('capture.action.validate_plan') }}
                  <app-icon name="arrow-right" [size]="14" />
                </button>
              </div>
              @if (planDialogueLoading()) {
                <p class="flex items-center gap-2 text-[11px] leading-relaxed text-brand-200/90">
                  <span class="inline-block h-3.5 w-3.5 shrink-0 rounded-full border-2 border-brand-200/40 border-t-brand-200 animate-spin"></span>
                  L’assistant analyse votre description et met à jour le plan de sujets…
                </p>
              } @else if (planDialogueReadyHint(s); as hint) {
                <p class="text-[11px] leading-relaxed text-amber-200/85">{{ hint }}</p>
              }
              @if (planDialogueNotice(); as notice) {
                <p [class]="planNoticeClass(notice.tone)">{{ notice.text }}</p>
              }
            </aside>
          </section>
        }
      }

      @if (activeSurface() === 'review') {
        <section class="grid xl:grid-cols-[1fr_320px] gap-5">
          <div class="t-card rounded-lg p-5 space-y-4">
            <div class="flex items-start justify-between gap-4">
              <div>
                <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">{{ i18n.t('capture.review.eyebrow') }}</p>
                <h2 class="text-lg font-semibold text-white">
                  {{ proposal()?.proposal?.title || session()?.title || i18n.t('capture.review.title') }}
                </h2>
                <p class="text-sm text-gray-500 mt-1 max-w-3xl">
                  {{ i18n.t('capture.review.description') }}
                </p>
              </div>
              @if (!isDemoMode()) {
                @if (proposal(); as p) {
                  <span class="text-xs px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">{{ workflowStatusLabel(p.status) }}</span>
                }
              }
            </div>

            <div class="space-y-3">
              <div class="flex items-center justify-between gap-3">
                <label class="block text-[10px] uppercase tracking-wider text-brand-300">{{ i18n.t('capture.review.final_report') }}</label>
                @if (proposalReportDirty()) {
                  <span class="text-[11px] text-amber-200">{{ i18n.t('capture.review.unsaved') }}</span>
                }
              </div>
              @if (reportFiche().length && !reportEditMode()) {
                <ng-template #reportListTpl let-items let-nested="nested" let-compact="compact">
                  <ul [class]="nested ? 'ck-fiche-nested-list' : 'ck-fiche-list'">
                    @for (item of items; track $index) {
                      <li class="ck-fiche-li">
                        <div
                          class="ck-fiche-row"
                          [class]="compact ? 'text-[13px] leading-relaxed text-gray-300' : 'text-sm leading-relaxed text-gray-200'"
                        >
                          <span class="ck-fiche-bullet"></span>
                          <span>{{ item.text }}</span>
                        </div>
                        @if (item.children?.length) {
                          <ng-container
                            *ngTemplateOutlet="reportListTpl; context: { $implicit: item.children, nested: true, compact: compact }"
                          ></ng-container>
                        }
                      </li>
                    }
                  </ul>
                </ng-template>
                <!-- Structured fiche rendering: section cards following the plan /
                     thematic blocks, with key facts, open questions and KB sources. -->
                <div class="space-y-4">
                  @for (card of reportFiche(); track card.key) {
                    <article class="rounded-lg border border-white/10 bg-black/25 overflow-hidden">
                      <header class="flex items-center gap-3 px-4 py-3 border-b border-white/5 bg-white/[0.03]">
                        <span class="ck-mono inline-flex h-6 w-6 shrink-0 items-center justify-center rounded bg-brand-500/15 text-[11px] font-semibold text-brand-200 ring-1 ring-brand-300/25">
                          {{ card.index }}
                        </span>
                        <h3 class="text-sm font-semibold text-white">{{ card.title }}</h3>
                      </header>
                      <div class="px-4 py-3.5 space-y-3">
                        @for (block of card.blocks; track $index) {
                          @if (block.kind === 'heading') {
                            <h4 class="ck-fiche-heading text-[11px] uppercase tracking-wider text-brand-200 font-semibold">{{ block.text }}</h4>
                          } @else if (block.kind === 'list' && block.items?.length) {
                            <div class="ck-fiche-list-wrap">
                              <ng-container
                                *ngTemplateOutlet="reportListTpl; context: { $implicit: block.items, nested: false, compact: false }"
                              ></ng-container>
                            </div>
                          } @else if (block.text) {
                            <p class="ck-fiche-paragraph text-sm leading-relaxed text-gray-200">{{ block.text }}</p>
                          }
                        }
                        @if (card.facts.length) {
                          <ul class="space-y-1.5">
                            @for (fact of card.facts; track $index) {
                              <li class="flex gap-2 text-sm leading-relaxed text-gray-300">
                                <span class="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-gray-500"></span>
                                <span>{{ fact }}</span>
                              </li>
                            }
                          </ul>
                        }
                        @for (sub of card.subsections; track sub.key) {
                          <section class="rounded border border-white/5 bg-white/[0.02] p-3 space-y-2">
                            <h4 class="text-xs font-semibold text-gray-200">{{ sub.title }}</h4>
                            @for (block of sub.blocks; track $index) {
                              @if (block.kind === 'heading') {
                                <h5 class="ck-fiche-heading text-[10px] uppercase tracking-wider text-brand-200/90 font-semibold">{{ block.text }}</h5>
                              } @else if (block.kind === 'list' && block.items?.length) {
                                <div class="ck-fiche-list-wrap">
                                  <ng-container
                                    *ngTemplateOutlet="reportListTpl; context: { $implicit: block.items, nested: false, compact: true }"
                                  ></ng-container>
                                </div>
                              } @else if (block.text) {
                                <p class="ck-fiche-paragraph text-[13px] leading-relaxed text-gray-300">{{ block.text }}</p>
                              }
                            }
                            @for (fact of sub.facts; track $index) {
                              <p class="text-[13px] leading-relaxed text-gray-400">• {{ fact }}</p>
                            }
                            @if (sub.openQuestionLinks.length) {
                              <div class="rounded bg-amber-500/5 ring-1 ring-amber-300/15 px-2.5 py-2 space-y-1">
                                <p class="text-[10px] uppercase tracking-wider text-amber-200/80 font-semibold">Questions ouvertes</p>
                                @for (link of sub.openQuestionLinks; track link.key) {
                                  <button
                                    type="button"
                                    class="block w-full text-left text-[12px] leading-relaxed text-brand-200 hover:text-brand-100 underline decoration-brand-300/40 underline-offset-2"
                                    (click)="scrollToReviewQuestion(link.key)"
                                  >
                                    {{ link.index }}. {{ link.label }}
                                  </button>
                                }
                              </div>
                            }
                            @if (sub.sources.length) {
                              <div class="flex flex-wrap gap-1.5 pt-1">
                                @for (src of sub.sources; track $index) {
                                  <button
                                    type="button"
                                    class="inline-flex items-center gap-1.5 max-w-full px-2 py-1 rounded bg-white/5 ring-1 ring-white/10 text-[11px] text-gray-300 hover:text-white hover:bg-white/10 disabled:cursor-default disabled:hover:bg-white/5"
                                    [disabled]="!canPreviewReportSource(src)"
                                    (click)="previewReportSource(src)"
                                  >
                                    <app-icon name="file-text" [size]="11" class="shrink-0 text-brand-300" />
                                    <span class="truncate">{{ reportSourceLabel(src) }}</span>
                                  </button>
                                }
                              </div>
                            }
                          </section>
                        }
                        @if (card.openQuestionLinks.length) {
                          <div class="rounded bg-amber-500/5 ring-1 ring-amber-300/15 px-3 py-2.5 space-y-1.5">
                            <p class="text-[10px] uppercase tracking-wider text-amber-200/80 font-semibold">Questions ouvertes</p>
                            @for (link of card.openQuestionLinks; track link.key) {
                              <button
                                type="button"
                                class="block w-full text-left text-xs leading-relaxed text-brand-200 hover:text-brand-100 underline decoration-brand-300/40 underline-offset-2"
                                (click)="scrollToReviewQuestion(link.key)"
                              >
                                {{ link.index }}. {{ link.label }}
                              </button>
                            }
                          </div>
                        }
                      </div>
                      @if (card.sources.length) {
                        <footer class="px-4 py-2.5 border-t border-white/5 bg-black/20">
                          <div class="flex flex-wrap items-center gap-1.5">
                            <span class="text-[10px] uppercase tracking-wider text-gray-500 mr-1">Sources</span>
                            @for (src of card.sources; track $index) {
                              <button
                                type="button"
                                class="inline-flex items-center gap-1.5 max-w-full px-2 py-1 rounded bg-white/5 ring-1 ring-white/10 text-[11px] text-gray-300 hover:text-white hover:bg-white/10 disabled:cursor-default disabled:hover:bg-white/5"
                                [disabled]="!canPreviewReportSource(src)"
                                (click)="previewReportSource(src)"
                              >
                                <app-icon name="file-text" [size]="11" class="shrink-0 text-brand-300" />
                                <span class="truncate">{{ reportSourceLabel(src) }}</span>
                              </button>
                            }
                          </div>
                        </footer>
                      }
                    </article>
                  }
                  @if (reportUnassignedFacts().length) {
                    <article class="rounded-lg border border-dashed border-white/10 bg-black/20 px-4 py-3.5 space-y-2">
                      <h3 class="text-xs font-semibold text-gray-400 uppercase tracking-wider">Éléments hors plan</h3>
                      @for (fact of reportUnassignedFacts(); track $index) {
                        <p class="text-[13px] leading-relaxed text-gray-400">• {{ fact }}</p>
                      }
                    </article>
                  }
                </div>
              } @else {
                <textarea
                  class="w-full min-h-[520px] rounded bg-black/30 border border-white/10 px-4 py-3 font-mono text-sm leading-relaxed text-gray-100 resize-y"
                  [ngModel]="proposalReportDraft"
                  (ngModelChange)="onProposalReportChange($event)"
                  [placeholder]="i18n.t('capture.review.placeholder')"
                ></textarea>
              }
              @if (!proposalReportText() && !reportFiche().length) {
                <div class="rounded border border-dashed border-white/10 bg-black/20 p-5 text-sm text-gray-500">
                  {{ i18n.t('capture.review.empty_report') }}
                </div>
              }
            </div>
            @if (proposal(); as p) {
              <footer class="flex flex-wrap items-center justify-between gap-3 pt-4 border-t border-white/10">
                <div class="flex flex-wrap items-center gap-2">
                  @if (reportFiche().length) {
                    <button
                      type="button"
                      class="inline-flex items-center gap-1.5 px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-200 ring-1 ring-white/10"
                      (click)="toggleReportEditMode()"
                    >
                      <app-icon [name]="reportEditMode() ? 'layout-grid' : 'pencil'" [size]="14" />
                      {{ reportEditMode() ? i18n.t('capture.review.view_fiche') : i18n.t('capture.review.edit') }}
                    </button>
                  }
                  <details class="relative">
                    <summary class="inline-flex cursor-pointer list-none items-center gap-1.5 px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-300 ring-1 ring-white/10">
                      <app-icon name="more-horizontal" [size]="14" />
                      {{ i18n.t('capture.action.more_actions') }}
                    </summary>
                    <div class="absolute left-0 z-10 mt-1 min-w-[12rem] rounded-lg border border-white/10 bg-gray-950 p-1 shadow-xl">
                      <button
                        type="button"
                        class="block w-full rounded px-3 py-2 text-left text-sm text-gray-200 hover:bg-white/5 disabled:opacity-50"
                        [disabled]="!proposalReportDirty() || proposalReportSaving() || !proposalReportText()"
                        (click)="saveProposalReport(p.id)"
                      >
                        {{ proposalReportSaving() ? i18n.t('capture.review.saving_report') : i18n.t('capture.review.save_report') }}
                      </button>
                      <button type="button" class="block w-full rounded px-3 py-2 text-left text-sm text-gray-200 hover:bg-white/5" (click)="exportProposalMd()">
                        {{ i18n.t('capture.review.export_markdown') }}
                      </button>
                      <button type="button" class="block w-full rounded px-3 py-2 text-left text-sm text-gray-200 hover:bg-white/5" (click)="goSurface('session')">
                        {{ i18n.t('capture.review.resume_capture') }}
                      </button>
                      @if (!isDemoMode() && showAdvancedSetup()) {
                        <button type="button" class="block w-full rounded px-3 py-2 text-left text-sm text-gray-200 hover:bg-white/5" [disabled]="!session()" (click)="regenerateProposal()">
                          {{ i18n.t('capture.review.regenerate_report') }}
                        </button>
                      }
                    </div>
                  </details>
                </div>
                <div class="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    class="inline-flex items-center gap-2 px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-200 ring-1 ring-white/10"
                    [title]="i18n.t('capture.action.pass_later_hint')"
                    (click)="passReviewLater()"
                  >
                    {{ i18n.t('capture.action.pass_later') }}
                    <app-icon name="arrow-right" [size]="14" />
                  </button>
                  <button
                    type="button"
                    class="inline-flex items-center gap-2 px-4 py-2 rounded bg-brand-500 hover:bg-brand-400 text-sm font-semibold text-white disabled:opacity-50"
                    [disabled]="!proposalReportText() || proposalReportSaving() || !canContinueFromReview(p)"
                    [title]="proposalReviewHint(p) || i18n.t('capture.review.footer_publish_hint')"
                    (click)="continueFromReview(p)"
                  >
                    {{ i18n.t('capture.action.continue_to_publish') }}
                    <app-icon name="arrow-right" [size]="14" />
                  </button>
                </div>
              </footer>
            } @else if (session(); as s) {
              <footer class="flex flex-wrap items-center justify-end gap-2 pt-4 border-t border-white/10">
                <button
                  type="button"
                  class="inline-flex items-center gap-2 px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-200 ring-1 ring-white/10"
                  (click)="passReviewLater()"
                >
                  {{ i18n.t('capture.action.pass_later') }}
                  <app-icon name="arrow-right" [size]="14" />
                </button>
                <button
                  type="button"
                  class="inline-flex items-center gap-2 px-4 py-2 rounded bg-brand-500 hover:bg-brand-400 text-sm font-semibold text-white disabled:opacity-50"
                  [disabled]="!canProposalSubmit(s)"
                  (click)="createProposal(s)"
                >
                  {{ i18n.t('capture.action.continue') }}
                  <app-icon name="arrow-right" [size]="14" />
                </button>
              </footer>
            }
            @if (closureSheetMarkdown()) {
              <details class="rounded border border-white/10 bg-black/20 p-3">
                <summary class="cursor-pointer text-sm text-gray-300">{{ i18n.t('capture.review.end_sheet') }}</summary>
                <pre class="mt-3 whitespace-pre-wrap text-xs text-gray-400 max-h-72 overflow-auto">{{ closureSheetMarkdown() }}</pre>
              </details>
            }
          </div>

          <aside class="t-card rounded-lg p-5 space-y-4">
            <div>
              <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">{{ i18n.t('capture.review.review') }}</p>
              <h3 class="text-sm font-semibold text-white mt-1">{{ i18n.t('capture.review.open_questions') }}</h3>
              @if (iamRoleBanner(); as banner) {
                <p class="mt-2 text-xs text-brand-100/80">{{ banner }}</p>
              }
            </div>
            @if (!isDemoMode() && showAdvancedSetup()) {
            <div class="grid grid-cols-2 gap-2 text-xs">
              <div class="rounded bg-black/20 border border-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500">{{ i18n.t('capture.review.report') }}</div>
                <div class="text-xl text-white font-semibold">{{ proposalReportWordCount() }}</div>
              </div>
              <div class="rounded bg-black/20 border border-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500">{{ i18n.t('capture.review.evidence') }}</div>
                <div class="text-xl text-white font-semibold">{{ proposalEvidenceCount() }}</div>
              </div>
              <div class="rounded bg-black/20 border border-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500">{{ i18n.t('capture.review.prompts') }}</div>
                <div class="text-xl text-white font-semibold">{{ proposalUnresolvedOpenQuestionCount() }}</div>
              </div>
              <div class="rounded bg-black/20 border border-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500">{{ i18n.t('capture.review.state') }}</div>
                <div class="text-sm text-white font-semibold">{{ proposalReviewStateLabel() }}</div>
              </div>
            </div>
            }
            @if (proposal(); as p) {
              <section class="rounded border border-brand-300/20 bg-brand-500/5 p-3 space-y-3">
                <div>
                  <label class="block text-[10px] uppercase tracking-wider text-brand-200">{{ i18n.t('capture.review.edit_report') }}</label>
                  <p class="mt-1 text-xs leading-relaxed text-gray-400">
                    {{ i18n.t('capture.review.edit_report_hint') }}
                  </p>
                </div>
                <textarea
                  class="w-full min-h-24 rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white placeholder:text-gray-600 resize-y disabled:opacity-60"
                  [(ngModel)]="proposalInstructionText"
                  [disabled]="proposalInstructionLoading()"
                  [placeholder]="i18n.t('capture.review.instruction_placeholder')"
                ></textarea>
                <button
                  type="button"
                  class="w-full inline-flex items-center justify-center gap-2 px-3 py-2 rounded bg-brand-500/20 hover:bg-brand-500/30 text-sm text-brand-100 ring-1 ring-brand-300/30 disabled:opacity-50"
                  [disabled]="!proposalInstructionText.trim() || proposalInstructionLoading() || !proposalReportText()"
                  (click)="applyProposalInstruction(p)"
                >
                  @if (proposalInstructionLoading()) {
                    <span class="inline-block h-3.5 w-3.5 shrink-0 rounded-full border-2 border-brand-200/40 border-t-brand-200 animate-spin"></span>
                    {{ i18n.t('capture.review.updating') }}
                  } @else {
                    <app-icon name="sparkles" [size]="14" /> {{ i18n.t('capture.review.apply_instruction') }}
                  }
                </button>
              </section>
            }
            @if (proposalReviewQuestions().length) {
              <div class="rounded bg-amber-500/10 border border-amber-400/20 p-3">
                <div class="flex items-center justify-between gap-3">
                  <div class="text-[10px] uppercase tracking-wider text-amber-200">{{ i18n.t('capture.review.open_questions') }}</div>
                  @if (proposalUnresolvedOpenQuestionCount() > 0) {
                    <span class="text-[10px] text-amber-100/70">{{ proposalOpenQuestionsLabel() }}</span>
                  }
                </div>
                <div class="mt-3 space-y-2">
                @for (row of proposalReviewQuestions(); track row.key; let i = $index) {
                  <article
                    [attr.id]="reviewQuestionDomId(row.key)"
                    class="rounded border border-amber-300/15 bg-black/20 p-3"
                    [class.opacity-70]="row.status === 'deferred'"
                    [class.kc-review-q-highlight]="highlightedReviewQuestionKey() === row.key"
                  >
                    <div class="flex flex-wrap items-center gap-2">
                      <span [class]="proposalQuestionPriorityClass(row.priority)">
                        {{ proposalQuestionPriorityLabel(row.priority) }}
                      </span>
                      @if (row.status === 'answered') {
                        <span class="rounded bg-emerald-500/15 px-2 py-0.5 text-[9px] uppercase tracking-wider text-emerald-200 ring-1 ring-emerald-300/20">
                          répondue
                        </span>
                      } @else if (row.status === 'deferred') {
                        <span class="rounded bg-white/5 px-2 py-0.5 text-[9px] uppercase tracking-wider text-gray-400">
                          {{ i18n.t('capture.review.deferred') }}
                        </span>
                      }
                    </div>
                    <p class="mt-2 text-xs leading-relaxed text-amber-100/90">{{ proposalQuestionText(row.question) }}</p>
                    @if (proposalQuestionDetail(row.question); as detail) {
                      <p class="mt-1 text-[11px] leading-relaxed text-gray-500">{{ detail }}</p>
                    }
                    @if (proposalQuestionAnswer(row.question); as answered) {
                      <p class="mt-2 rounded bg-emerald-500/10 border border-emerald-400/20 px-2 py-1.5 text-[11px] leading-relaxed text-emerald-100/90">
                        <span class="text-emerald-300/80">Réponse :</span> {{ answered }}
                      </p>
                    }
                    @if (answeringQuestionKey() === row.key) {
                      <div class="mt-3 space-y-2">
                        <textarea
                          class="w-full min-h-16 rounded bg-black/30 border border-white/10 px-2 py-1.5 text-xs text-white leading-relaxed"
                          [(ngModel)]="questionAnswerDraft"
                          placeholder="Saisissez la réponse, ou dictez-la avec le micro…"
                        ></textarea>
                        <div class="flex flex-wrap items-center gap-2">
                          <button
                            type="button"
                            class="inline-flex items-center gap-1 rounded bg-white/5 px-2 py-1 text-[10px] text-gray-200 ring-1 ring-white/10 hover:bg-white/10"
                            title="Répondre à la voix (transcrite en texte)."
                            (click)="dictateProposalQuestionAnswer()"
                          >
                            <app-icon [name]="recording() ? 'square' : 'mic'" [size]="12" />
                            {{ recording() ? 'Arrêter la dictée' : 'Dicter' }}
                          </button>
                          <button
                            type="button"
                            class="inline-flex items-center gap-1 rounded bg-emerald-500/20 px-2 py-1 text-[10px] font-medium text-emerald-100 ring-1 ring-emerald-300/20 hover:bg-emerald-500/30 disabled:opacity-50"
                            [disabled]="!questionAnswerDraft.trim() || questionAnswerLoading()"
                            (click)="submitProposalQuestionAnswer(row, i)"
                          >
                            @if (questionAnswerLoading()) {
                              <span class="inline-block h-3 w-3 shrink-0 rounded-full border-2 border-emerald-200/40 border-t-emerald-200 animate-spin"></span>
                              Enregistrement…
                            } @else {
                              <app-icon name="send" [size]="12" /> Valider la réponse
                            }
                          </button>
                          <button
                            type="button"
                            class="rounded bg-white/5 px-2 py-1 text-[10px] text-gray-400 ring-1 ring-white/10 hover:bg-white/10"
                            (click)="cancelProposalQuestionAnswer()"
                          >
                            Annuler
                          </button>
                        </div>
                      </div>
                    }
                    <div class="mt-3 flex flex-wrap gap-2">
                      @if (answeringQuestionKey() !== row.key) {
                        <button
                          type="button"
                          class="rounded bg-brand-500/15 px-2 py-1 text-[10px] font-medium text-brand-100 ring-1 ring-brand-300/20 hover:bg-brand-500/25"
                          (click)="beginProposalQuestionAnswer(row.key)"
                        >
                          {{ row.status === 'answered' ? 'Modifier la réponse' : 'Répondre' }}
                        </button>
                      }
                      <button
                        type="button"
                        class="rounded bg-white/5 px-2 py-1 text-[10px] text-gray-300 ring-1 ring-white/10 hover:bg-white/10"
                        (click)="row.status === 'deferred' ? restoreProposalOpenQuestion(row.key) : deferProposalOpenQuestion(row.key)"
                      >
                        {{ row.status === 'deferred' ? i18n.t('capture.review.restore') : i18n.t('capture.review.defer') }}
                      </button>
                      <button
                        type="button"
                        class="rounded bg-red-500/10 px-2 py-1 text-[10px] text-red-200 ring-1 ring-red-400/20 hover:bg-red-500/20"
                        title="Supprime la question : masquée et exclue de la publication."
                        (click)="invalidateProposalOpenQuestion(row.key)"
                      >
                        {{ i18n.t('capture.review.hide') }}
                      </button>
                    </div>
                  </article>
                }
                </div>
              </div>
            }
            @if (!proposalReviewQuestions().length) {
              <div class="rounded border border-white/10 bg-black/20 p-3 text-xs text-gray-400">
                {{ i18n.t('capture.review.no_open_questions') }}
              </div>
            }
            @if (!isDemoMode() && showAdvancedSetup()) {
              <label class="block text-[10px] uppercase tracking-wider text-gray-500">{{ i18n.t('capture.review.executive_summary') }}</label>
              <textarea
                class="w-full min-h-20 rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white"
                [(ngModel)]="executiveSummary"
                [placeholder]="i18n.t('capture.review.summary_placeholder')"
              ></textarea>
            }
            @if (!isDemoMode() && showAdvancedSetup() && residualQualityCount() > 0) {
              <p class="text-xs text-amber-200/90">{{ i18n.t('capture.review.quality_open', { count: residualQualityCount() }) }}</p>
            }
            @if (!isDemoMode() && showAdvancedSetup() && postSessionQualityItems().length) {
              <section class="rounded border border-amber-500/25 bg-amber-500/5 p-3 space-y-2">
                <p class="ck-mono text-[10px] uppercase tracking-wider text-amber-200">{{ i18n.t('capture.review.quality_points') }}</p>
                @for (item of postSessionQualityItems(); track item.id || item.label) {
                  <div class="text-xs text-gray-200 flex flex-wrap items-center justify-between gap-2">
                    <span>{{ item.label || item.follow_up }}</span>
                    @if (item.status === 'deferred') {
                      <span class="text-amber-200/80">{{ i18n.t('capture.review.deferred') }}</span>
                    }
                  </div>
                }
                <button
                  type="button"
                  class="w-full mt-1 px-3 py-2 rounded bg-brand-500/20 text-xs text-brand-100 ring-1 ring-brand-300/30"
                  (click)="startClarificationSession()"
                >
                  {{ i18n.t('capture.review.clarify_new_session') }}
                </button>
              </section>
            }
          </aside>
        </section>
      }

      @if (activeSurface() === 'publish') {
        @if (proposal(); as p) {
          <section class="grid xl:grid-cols-[minmax(0,1fr)_360px] gap-5">
            <div class="t-card rounded-lg p-5 space-y-5">
              @if (p.status === 'published' || publicationResult()) {
                <div class="rounded-lg border border-emerald-400/25 bg-emerald-500/10 p-5 space-y-4">
                  <div class="flex items-start gap-3">
                    <span class="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-emerald-500/20 ring-1 ring-emerald-300/30">
                      <app-icon name="check" [size]="18" class="text-emerald-200" />
                    </span>
                    <div class="min-w-0">
                      <p class="ck-mono text-[10px] uppercase tracking-wider text-emerald-300">{{ i18n.t('capture.publish.eyebrow') }}</p>
                      <h2 class="text-lg font-semibold text-white mt-1">{{ i18n.t('capture.publish.success_title') }}</h2>
                      <p class="text-sm text-emerald-100/90 mt-2 leading-relaxed">
                        {{ i18n.t('capture.publish.success_body', {
                          title: publicationResult()?.final_title || effectivePublicationFinalTitle(),
                          collection: publicationDestinationDisplay(
                            publicationResult()?.collection || p.proposal?.publication?.collection_slug || effectivePublicationDestination()
                          )
                        }) }}
                      </p>
                    </div>
                  </div>
                  <div class="flex flex-wrap items-center gap-2">
                    @if (publicationDocumentUrl(publicationResult()); as docUrl) {
                      <a
                        class="inline-flex items-center gap-2 px-4 py-2.5 rounded bg-emerald-500 hover:bg-emerald-400 text-sm font-semibold text-white"
                        [href]="docUrl"
                        target="_blank"
                        rel="noopener"
                      >
                        <app-icon name="external-link" [size]="14" /> {{ i18n.t('capture.publish.view_document') }}
                      </a>
                    }
                    <button
                      type="button"
                      class="inline-flex items-center gap-2 px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-200 ring-1 ring-white/10"
                      (click)="goSurface('dashboard')"
                    >
                      {{ i18n.t('capture.publish.back_dashboard') }}
                    </button>
                  </div>
                </div>
              } @else {
                <div>
                  <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">{{ i18n.t('capture.publish.eyebrow') }}</p>
                  <h2 class="text-lg font-semibold text-white mt-1">
                    {{ effectivePublicationFinalTitle() }}
                  </h2>
                  <p class="text-sm text-gray-500 mt-1 max-w-3xl">
                    {{ i18n.t('capture.publish.description') }}
                  </p>
                </div>

                <div class="grid md:grid-cols-2 gap-4">
                  <div class="md:col-span-2">
                    <label class="block text-[11px] uppercase tracking-wider text-gray-400 mb-1">{{ i18n.t('capture.publish.final_title') }}</label>
                    <p class="text-[11px] text-gray-500 mb-2">{{ i18n.t('capture.publish.final_title_hint') }}</p>
                    <input
                      class="w-full rounded bg-black/30 border border-white/10 px-4 py-3 text-sm text-white"
                      [(ngModel)]="publicationFinalTitle"
                      [placeholder]="publicationFinalTitleLabel()"
                    />
                  </div>
                  <div>
                    <label class="block text-[11px] uppercase tracking-wider text-gray-400 mb-1">{{ i18n.t('capture.publish.category') }}</label>
                    <p class="text-[11px] text-gray-500 mb-2">{{ i18n.t('capture.publish.category_hint') }}</p>
                    <select
                      class="w-full rounded bg-black/30 border border-white/10 px-4 py-3 text-sm text-white"
                      [(ngModel)]="publicationCategory"
                    >
                      @for (option of publicationCategoryOptions; track option.id) {
                        <option [value]="option.id">{{ option.label }}</option>
                      }
                    </select>
                  </div>
                  <div>
                    <label class="block text-[11px] uppercase tracking-wider text-gray-400 mb-1">{{ i18n.t('capture.publish.destination') }}</label>
                    <p class="text-[11px] text-gray-500 mb-2">{{ i18n.t('capture.publish.destination_hint') }}</p>
                    <select
                      class="w-full rounded bg-black/30 border border-white/10 px-4 py-3 text-sm text-white font-mono"
                      [ngModel]="publicationDestinationChoice()"
                      (ngModelChange)="onPublicationDestinationChoice($event)"
                    >
                      @if (!publicationDestinationChoice()) {
                        <option value="" disabled>{{ i18n.t('capture.publish.destination_required') }}</option>
                      }
                      @for (slug of publicationDestinationOptions(); track slug) {
                        <option [value]="slug">{{ slug }}</option>
                      }
                      <option value="__custom__">{{ i18n.t('capture.publish.destination_custom') }}</option>
                    </select>
                    @if (publicationDestinationCustom()) {
                      <input
                        class="mt-2 w-full rounded bg-black/30 border border-white/10 px-4 py-3 text-sm text-white font-mono"
                        [(ngModel)]="publicationDestination"
                        [placeholder]="i18n.t('capture.publish.destination_custom_placeholder')"
                      />
                    }
                    @if (!effectivePublicationDestination()) {
                      <p class="mt-2 text-[11px] leading-relaxed text-amber-200/85">
                        {{ i18n.t('capture.publish.destination_required') }}
                      </p>
                    }
                  </div>
                </div>

                <div>
                  <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500 mb-3">{{ i18n.t('capture.publish.preview') }}</p>
                  @if (publicationSectionTitles().length) {
                    <!-- Digest: every section of the report at a glance. -->
                    <div class="mb-3 rounded border border-white/10 bg-white/[0.02] px-3 py-2.5">
                      <p class="text-[10px] uppercase tracking-wider text-gray-500 mb-2">
                        {{ i18n.t('capture.publish.preview_sections', { count: publicationSectionTitles().length }) }}
                      </p>
                      <div class="flex flex-wrap gap-1.5">
                        @for (title of publicationSectionTitles(); track $index) {
                          <span class="inline-flex items-center gap-1.5 max-w-full px-2 py-1 rounded bg-white/5 ring-1 ring-white/10 text-[11px] text-gray-300">
                            <span class="ck-mono inline-flex h-4 w-4 shrink-0 items-center justify-center rounded bg-brand-500/15 text-[9px] font-semibold text-brand-200 ring-1 ring-brand-300/25">
                              {{ $index + 1 }}
                            </span>
                            <span class="truncate">{{ title }}</span>
                          </span>
                        }
                      </div>
                    </div>
                  }
                  @if (reportFiche().length) {
                    <div class="space-y-3 max-h-[28rem] overflow-auto pr-1">
                      @for (card of reportFiche(); track card.key) {
                        <article class="rounded-lg border border-white/10 bg-black/25 overflow-hidden">
                          <header class="flex items-center gap-3 px-4 py-2.5 border-b border-white/5 bg-white/[0.03]">
                            <span class="ck-mono inline-flex h-5 w-5 shrink-0 items-center justify-center rounded bg-brand-500/15 text-[10px] font-semibold text-brand-200 ring-1 ring-brand-300/25">
                              {{ card.index }}
                            </span>
                            <h3 class="text-sm font-semibold text-white">{{ card.title }}</h3>
                          </header>
                          <div class="px-4 py-3 space-y-2">
                            @for (block of card.blocks; track $index) {
                              @if (block.kind === 'heading') {
                                <h4 class="text-[10px] uppercase tracking-wider text-brand-200/90 font-semibold">{{ block.text }}</h4>
                              } @else if (block.text) {
                                <p class="text-[13px] leading-relaxed text-gray-300">{{ block.text }}</p>
                              }
                            }
                            @if (card.facts.length) {
                              <ul class="space-y-1">
                                @for (fact of card.facts; track $index) {
                                  <li class="text-[13px] leading-relaxed text-gray-300 pl-3 border-l border-brand-300/20">{{ fact }}</li>
                                }
                              </ul>
                            }
                            @for (sub of card.subsections; track sub.key) {
                              <section class="rounded border border-white/5 bg-white/[0.02] p-3 space-y-1.5">
                                <h4 class="text-xs font-semibold text-gray-200">{{ sub.title }}</h4>
                                @for (block of sub.blocks; track $index) {
                                  @if (block.kind === 'heading') {
                                    <h5 class="text-[10px] uppercase tracking-wider text-brand-200/90 font-semibold">{{ block.text }}</h5>
                                  } @else if (block.text) {
                                    <p class="text-[13px] leading-relaxed text-gray-300">{{ block.text }}</p>
                                  }
                                }
                                @for (fact of sub.facts; track $index) {
                                  <p class="text-[13px] leading-relaxed text-gray-400">• {{ fact }}</p>
                                }
                              </section>
                            }
                          </div>
                        </article>
                      }
                    </div>
                  } @else {
                    <div class="rounded border border-white/10 bg-black/20 p-4 max-h-96 overflow-auto">
                      <pre class="whitespace-pre-wrap text-sm leading-relaxed text-gray-200">{{ proposalReportText() }}</pre>
                    </div>
                  }
                </div>

                <footer class="flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-white/10">
                  <button
                    type="button"
                    class="inline-flex items-center gap-2 px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-200 ring-1 ring-white/10"
                    (click)="goSurface('review')"
                  >
                    <app-icon name="arrow-left" [size]="14" /> {{ i18n.t('capture.review.edit') }}
                  </button>
                  <div class="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      class="inline-flex items-center gap-2 px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-200 ring-1 ring-white/10"
                      [title]="i18n.t('capture.action.pass_later_hint')"
                      (click)="passReviewLater()"
                    >
                      {{ i18n.t('capture.action.pass_later') }}
                      <app-icon name="arrow-right" [size]="14" />
                    </button>
                    <button
                      type="button"
                      class="inline-flex items-center gap-2 px-4 py-2.5 rounded bg-brand-500 hover:bg-brand-400 text-sm font-semibold text-white disabled:opacity-50"
                      [disabled]="!canPublishProposal(p) || publicationPublishing()"
                      [title]="proposalPublishHint(p) || ''"
                      (click)="publishToKnowledge(p.id)"
                    >
                      @if (publicationPublishing()) {
                        <app-icon name="loader-2" [size]="14" class="animate-spin" />
                        {{ i18n.t('capture.publish.publishing') }}
                      } @else {
                        <app-icon name="upload" [size]="14" /> {{ i18n.t('capture.publish.cta') }}
                      }
                    </button>
                  </div>
                </footer>
              }
            </div>

            <aside class="t-card rounded-lg p-5 space-y-4 xl:sticky xl:top-4">
              <div>
                <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">{{ i18n.t('capture.publish.sidebar_title') }}</p>
                <h3 class="text-sm font-semibold text-white mt-1">
                  @if (p.status === 'published' || publicationResult()) {
                    {{ i18n.t('capture.publish.success_title') }}
                  } @else {
                    {{ i18n.t('capture.publish.sidebar_ready') }}
                  }
                </h3>
              </div>
              <div class="rounded border border-white/10 bg-black/20 p-3 text-xs text-gray-300 space-y-2">
                <p><span class="text-gray-500">{{ i18n.t('capture.publish.metadata_title') }} :</span> {{ effectivePublicationFinalTitle() }}</p>
                <p><span class="text-gray-500">{{ i18n.t('capture.publish.metadata_expert') }} :</span> {{ captureExpertLabel() }}</p>
                <p><span class="text-gray-500">{{ i18n.t('capture.publish.metadata_category') }} :</span> {{ publicationCategoryLabel() }}</p>
                <p><span class="text-gray-500">{{ i18n.t('capture.publish.metadata_destination') }} :</span> {{ publicationDestinationDisplay(effectivePublicationDestination()) }}</p>
                <p><span class="text-gray-500">{{ i18n.t('capture.publish.metadata_state') }} :</span> {{ proposalReviewStateLabel() }}</p>
              </div>
              @if (p.status !== 'published' && !publicationResult()) {
                <div class="rounded border border-brand-300/20 bg-brand-500/5 p-3 space-y-2 text-xs text-gray-300">
                  <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-200">{{ i18n.t('capture.publish.sidebar_what_happens') }}</p>
                  <p>{{ i18n.t('capture.publish.word_count', { count: proposalReportWordCount() }) }}</p>
                  @if (proposalPublishableUnresolvedCount() > 0) {
                    <p>{{ i18n.t('capture.publish.unresolved_questions', { count: proposalPublishableUnresolvedCount() }) }}</p>
                    <p class="leading-relaxed text-gray-400">{{ i18n.t('capture.publish.handoff_note') }}</p>
                  } @else {
                    <p>{{ i18n.t('capture.publish.no_open_questions') }}</p>
                  }
                  @if (effectivePublicationDestination(); as destination) {
                    <p class="leading-relaxed text-gray-400">
                      {{ i18n.t('capture.publish.indexing_note', { collection: publicationDestinationDisplay(destination) }) }}
                    </p>
                  }
                </div>
                @if (proposalPublishHint(p); as hint) {
                  <p class="text-[11px] leading-relaxed text-amber-200/85">{{ hint }}</p>
                }
              } @else {
                <p class="text-[11px] leading-relaxed text-emerald-200/90">{{ i18n.t('capture.publish.already_published') }}</p>
              }
            </aside>
          </section>
        }
      }
    </section>

    <!-- FINAL-phase loader: the report screen only opens once the heavy
         restructuring pass has persisted the report. -->
    @if (captureFinalizing()) {
      <div class="fixed inset-0 z-[70] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
        <section class="w-full max-w-md rounded-lg bg-gray-950 ring-1 ring-white/10 shadow-2xl p-6 space-y-5">
          <div class="flex items-center gap-3">
            <span class="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-500/15 ring-1 ring-brand-300/30">
              <app-icon name="loader-2" [size]="18" class="animate-spin text-brand-200" />
            </span>
            <div class="min-w-0">
              <p class="ck-mono text-[10px] uppercase tracking-[0.18em] text-brand-300">Synthèse finale</p>
              <h2 class="mt-0.5 text-sm font-semibold text-white">Restructuration de la capture en cours</h2>
            </div>
          </div>
          <div>
            <p class="text-sm text-gray-200 leading-relaxed">{{ captureFinalizeStageLabel() }}</p>
            @if (captureFinalizeSectionProgress(); as sectionProgress) {
              <p class="mt-1 text-[11px] font-mono text-gray-500">{{ sectionProgress }}</p>
            }
            @if (captureFinalizeProgressPct(); as pct) {
              <div class="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-white/5 ring-1 ring-white/10">
                <div class="h-full rounded-full bg-brand-400 transition-all duration-700" [style.width.%]="pct"></div>
              </div>
            }
          </div>
          <ul class="space-y-2">
            @for (step of captureFinalizeSteps(); track step.label) {
              <li class="flex items-center gap-2.5 text-xs">
                @if (step.state === 'done') {
                  <span class="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-emerald-500/20 text-emerald-200">
                    <app-icon name="check" [size]="10" />
                  </span>
                  <span class="text-gray-400">{{ step.label }}</span>
                } @else if (step.state === 'active') {
                  <span class="inline-flex h-4 w-4 shrink-0 items-center justify-center">
                    <app-icon name="loader-2" [size]="12" class="animate-spin text-brand-300" />
                  </span>
                  <span class="text-white">{{ step.label }}</span>
                } @else {
                  <span class="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-white/5 ring-1 ring-white/10"></span>
                  <span class="text-gray-600">{{ step.label }}</span>
                }
              </li>
            }
          </ul>
          <p class="text-[11px] leading-relaxed text-gray-500">
            L'expression captée est restructurée selon le plan, nettoyée de ses doublons et alignée sur le
            vocabulaire métier. Le rapport s'ouvrira automatiquement.
          </p>
        </section>
      </div>
    }

    <app-document-preview
      [open]="sourcePreviewOpen()"
      [previewUrl]="sourcePreviewUrl()"
      [title]="sourcePreviewTitle()"
      [page]="sourcePreviewPage()"
      [highlight]="sourcePreviewHighlight()"
      subtitle="Source documentaire"
      (closed)="closeSourcePreview()"
    />
  `,
})
export class KnowledgeCaptureComponent implements OnInit, AfterViewInit {
  @ViewChild('planOutlineEditor') private planOutlineEditor?: ElementRef<HTMLTextAreaElement>;
  @ViewChild('planBuildOutlineEditor') private planBuildOutlineEditor?: ElementRef<HTMLTextAreaElement>;
  @ViewChild('planDialogueAnswerEditor') private planDialogueAnswerEditor?: ElementRef<HTMLTextAreaElement>;
  @ViewChild('captureTranscriptScroll') private captureTranscriptScroll?: ElementRef<HTMLElement>;

  // Stick-to-bottom state for the transcript panel. Driven by REAL scroll
  // events (not pre-render measurements, which drifted and silently disabled
  // autoscroll): the user stays pinned while at/near the bottom, and a manual
  // scroll-up is never yanked back — a "jump to latest" affordance shows instead.
  readonly transcriptAtBottom = signal(true);

  private transcriptAutoscrollFrame: number | null = null;

  private readonly transcriptAutoscrollSignature = computed(() => {
    const rows = this.captureTranscriptRows();
    const live = this.liveTranscript();
    const pending = this.pendingLiveCommits();
    const lastRow = rows[rows.length - 1];
    return [
      rows.length,
      lastRow?.key ?? '',
      lastRow?.liveText?.length ?? 0,
      lastRow?.text?.length ?? 0,
      live?.id ?? '',
      live?.text?.length ?? 0,
      live?.status ?? '',
      pending.length,
      pending[pending.length - 1]?.text?.length ?? 0,
    ].join('|');
  });

  // Keep the transcript pinned to the latest text as partial/committed rows
  // stream in. Scrolling happens AFTER render so the new content height is
  // taken into account.
  private readonly autoScrollTranscript = effect(() => {
    void this.transcriptAutoscrollSignature();
    const followLive =
      this.recording() ||
      this.transcribing() ||
      this.conversationSessionActive();
    const stick = followLive || untracked(() => this.transcriptAtBottom());
    if (!stick) return;
    this.scheduleTranscriptAutoscroll();
  });

  private planDialogueAutoscrollFrame: number | null = null;

  // Single-purpose dictation field: always pin to the latest dictated text.
  private readonly autoScrollPlanDialogue = effect(() => {
    void this.planDialogueAnswer();
    this.schedulePlanDialogueAutoscroll();
  });

  ngAfterViewInit(): void {
    this.scheduleTranscriptAutoscroll();
    this.schedulePlanDialogueAutoscroll();
  }

  private schedulePlanDialogueAutoscroll(): void {
    if (this.planDialogueAutoscrollFrame !== null) return;
    this.planDialogueAutoscrollFrame = window.requestAnimationFrame(() => {
      this.planDialogueAutoscrollFrame = null;
      this.scrollPlanDialogueToBottom();
      window.setTimeout(() => this.scrollPlanDialogueToBottom(), 0);
    });
  }

  private scrollPlanDialogueToBottom(): void {
    const node = this.planDialogueAnswerEditor?.nativeElement;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
  }

  private scheduleTranscriptAutoscroll(): void {
    if (this.transcriptAutoscrollFrame !== null) return;
    this.transcriptAutoscrollFrame = window.requestAnimationFrame(() => {
      this.transcriptAutoscrollFrame = null;
      this.scrollTranscriptToBottom();
      window.setTimeout(() => this.scrollTranscriptToBottom(), 0);
    });
  }

  private scrollTranscriptToBottom(): void {
    const node = this.captureTranscriptScroll?.nativeElement;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
  }

  onTranscriptScroll(): void {
    const el = this.captureTranscriptScroll?.nativeElement;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    this.transcriptAtBottom.set(distanceFromBottom < 80);
  }

  jumpToLatestTranscript(): void {
    this.transcriptAtBottom.set(true);
    this.scheduleTranscriptAutoscroll();
  }

  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly zoom = inject(ZoomContextService);
  private readonly voiceSession = inject(VoiceSessionService);
  private readonly livekitConversation = inject(LiveKitConversationService);
  private readonly ttsPlaybackFactory = inject(VoiceTtsPlaybackService);
  private readonly workspace = inject(WorkspaceService);
  private readonly navigationProfile = inject(NavigationProfileService);
  readonly i18n = inject(I18nService);
  readonly permissions = inject(PermissionsService);
  readonly isBusinessSurface = computed(() => this.navigationProfile.businessShellActive());
  // Keep the existing template predicate, but let the business profile reuse
  // the same simplified capture UI without changing workspace.mode to "demo".
  readonly isDemoMode = computed(() => this.workspace.isDemoSafeMode() || this.isBusinessSurface());
  readonly isPilotMode = this.isDemoMode;
  readonly workspaceVoiceLoopConfig = computed<WorkspaceVoiceLoopConfig>(() => {
    const settings = this.asRecord(this.workspace.current()?.settings);
    const voiceLoop = this.asRecord(settings['voice_loop']);
    const workspaceSlug = String(this.workspace.current()?.slug || this.workspace.currentSlug() || '').toLowerCase();
    const andritzDefaults: WorkspaceVoiceLoopConfig =
      workspaceSlug === 'andritz'
        ? { silence_ms: 900, min_speech_ms: 350, max_turn_ms: 25000 }
        : {};
    return {
      auto_endpoint: true,
      auto_rearm_after_tts: true,
      barge_in: true,
      commands_enabled: true,
      ...andritzDefaults,
      ...voiceLoop,
    } as WorkspaceVoiceLoopConfig;
  });
  readonly voiceCaptureMode = signal<VoiceCaptureMode>('normal');
  readonly resolvedVoiceCaptureConfig = computed<ResolvedVoiceCaptureConfig>(() =>
    resolveVoiceCaptureConfig(this.workspaceVoiceLoopConfig(), this.voiceCaptureMode(), {
      silence_ms: 8000,
      dictation_silence_ms: 2000,
      min_speech_ms: 350,
      dictation_min_speech_ms: 300,
      max_turn_ms: 120000,
      rms_threshold: 0.018,
    }),
  );
  private loadedVoiceCaptureStorageKey = '';
  private readonly voiceCaptureModeLoader = effect(() => {
    const workspaceSlug = this.workspace.current()?.slug || this.workspace.currentSlug() || 'workspace';
    const config = this.workspaceVoiceLoopConfig();
    const storageKey = voiceCaptureStorageKey({ surface: 'knowledge_capture', workspaceSlug, profileKey: 'capture' });
    if (storageKey === this.loadedVoiceCaptureStorageKey) return;
    this.loadedVoiceCaptureStorageKey = storageKey;
    const stored = this.readStoredVoiceCaptureMode(storageKey, normalizeVoiceCaptureMode(config.capture_mode));
    queueMicrotask(() => this.voiceCaptureMode.set(stored));
  });
  readonly workspaceVoiceOutputConfig = computed(() => {
    const settings = this.asRecord(this.workspace.current()?.settings);
    const voiceOutput = this.asRecord(settings['voice_output']);
    return {
      // 'quality' maps to gpt-4o-mini-tts in voice_runtime (vs the muffled
      // tts-1 used by 'fast'). Workspace settings can still override this.
      latency_profile: 'quality',
      voice: 'nova',
      format: 'mp3',
      flush_first_chars: 24,
      flush_next_chars: 80,
      flush_timeout_ms: 900,
      interrupt_on_user_speech: true,
      ...voiceOutput,
    };
  });

  objective = '';
  sessionTitle = '';
  expertProfile = 'Expert métier';
  durationMinutes = 20;
  contextId = '';
  systemId = '';
  answer = '';
  selectedKnowledgeCollection = '';
  newContextName = '';
  selectedDomain = 'technical';
  selectedPlanMode: CapturePlanMode = 'free_conversation';
  providedPlanText = '';
  providedPlanFileName = '';
  providedPlanSourceKind: CapturePlanSourceKind = 'pasted_text';
  providedPlanReplacesExisting = false;
  readonly planDialogueAnswer = signal('');
  executiveSummary = '';
  publicationCategory = 'technical';
  publicationDestination = '';
  readonly publicationDestinationCustom = signal(false);
  publicationFinalTitle = '';
  dashboardDomainFilter = '';
  readonly durationUnlimited = signal(false);
  readonly qualityTab = signal<QualityTab>('imprecisions');
  readonly qualityBacklog = signal<{
    imprecisions: QualityBacklogItem[];
    contradictions: QualityBacklogItem[];
    open_questions: QualityBacklogItem[];
  }>({ imprecisions: [], contradictions: [], open_questions: [] });
  readonly deferWeakContradictions = signal(false);
  readonly planDialogueLoading = signal(false);
  readonly planDialogueReadyFlag = signal(false);
  readonly planDialogueNextPrompt = signal<string | null>(null);
  readonly planSourceStep = signal(false);
  readonly extractingPlanSource = signal(false);
  readonly pendingPlanSourceReplacement = signal<PendingPlanSourceReplacement | null>(null);
  private readonly planOutlineDrafts = new Map<string, string>();
  readonly planDialogueNotice = signal<{ tone: 'success' | 'error' | 'info'; text: string } | null>(null);
  readonly hintStack = signal<CaptureHint[]>([]);
  readonly activeSubtopicId = signal<string | null>(null);
  /** Manual left-rail / breadcrumb section picks block auto-detection for 60s. */
  private manualSectionSelectedAt = 0;
  private readonly liveSectionDetectMinConfidence = 0.42;
  private readonly manualSectionOverrideCooldownMs = 60_000;
  readonly questionBankStatus = signal<string>('idle');
  readonly qualityTabs = [
    { id: 'imprecisions' as QualityTab, label: 'Imprécisions' },
    { id: 'open_questions' as QualityTab, label: 'Questions' },
  ];
  readonly captureDomains = [
    { id: 'technical', label: 'Technique', description: 'Ingénierie, procédés, machines' },
    { id: 'commercial', label: 'Commercial', description: 'Marchés, comptes, affaires' },
    { id: 'innovation', label: 'Innovation', description: 'R&D, prototypes, exploration' },
  ];
  readonly publicationCategoryOptions = [
    { id: 'technical', label: 'Technique' },
    { id: 'commercial', label: 'Commercial' },
    { id: 'innovation', label: 'Innovation' },
    { id: 'maintenance', label: 'Maintenance' },
    { id: 'operation', label: 'Opération' },
    { id: 'other', label: 'Autre' },
  ];
  readonly visiblePlanModes = computed(() => {
    const modes: Array<{
      id: CapturePlanMode;
      label: string;
      description: string;
      icon: string;
      recommended: boolean;
      disabled?: boolean;
    }> = [
      {
        id: 'plan_build',
        label: this.i18n.t('capture.prep.with_plan'),
        description: this.i18n.t('capture.prep.with_plan_description'),
        icon: 'layout-grid',
        recommended: false,
      },
      {
        id: 'free_conversation',
        label: this.i18n.t('capture.prep.without_plan'),
        description: this.i18n.t('capture.prep.without_plan_description'),
        icon: 'activity',
        recommended: false,
      },
    ];
    return modes;
  });
  readonly visibleSurfaceNav = computed(() => {
    const session = this.session();
    const hidePlan = session ? this.isFreeConversationSession(session) : false;
    return this.surfaceNav.filter((item) => item.id !== 'plan' || !hidePlan);
  });
  readonly modelSteps = [
    {
      eyebrow: 'Capacité',
      label: 'Capture de connaissances',
      description: 'La fonction métier : préserver le raisonnement expert et la connaissance tacite.',
    },
    {
      eyebrow: 'Échange',
      label: 'Session guidée',
      description: 'Exécute un plan avec voix, évaluation et structuration.',
    },
    {
      eyebrow: 'Contexte',
      label: 'Périmètre documentaire',
      description: 'Sélectionne collections, accès et contraintes pour l’entretien.',
    },
    {
      eyebrow: 'Publication',
      label: 'Rapport relu',
      description: 'Reçoit les rapports validés après relecture.',
    },
  ];

  readonly loading = signal(false);
  readonly savingPlan = signal(false);
  readonly planNotice = signal<{ tone: 'success' | 'error' | 'info'; text: string } | null>(null);
  readonly contexts = signal<ContextOption[]>([]);
  readonly knowledgeCollections = signal<string[]>([]);
  readonly loadingKnowledgeCollections = signal(false);
  readonly creatingContext = signal(false);
  readonly newContextId = signal<string | null>(null);
  readonly contextCreationNotice = signal<ContextCreationNotice | null>(null);
  readonly showAdvancedSetup = signal(false);
  readonly systems = signal<SystemOption[]>([]);
  readonly systemScoped = signal(false);
  readonly activeSurface = signal<CaptureSurfaceView>('dashboard');
  readonly dashboardSessions = signal<CaptureSession[]>([]);
  readonly dashboardProposals = signal<CaptureProposal[]>([]);
  readonly showArchivedSessions = signal(false);
  readonly confirmDeleteSessionId = signal<string | null>(null);
  readonly sessionActionLoading = signal<string | null>(null);
  readonly visibleDashboardSessions = computed(() =>
    this.showArchivedSessions()
      ? this.dashboardSessions()
      : this.dashboardSessions().filter((row) => !row.archived),
  );
  readonly dashboardQualityRows = signal<
    Array<{ sessionId: string; sessionTitle: string; item: QualityBacklogItem }>
  >([]);
  readonly dashboardQualityBacklog = computed(() => this.dashboardQualityRows());
  readonly dashboardTab = signal<'sessions' | 'fiches'>('sessions');
  readonly publishedFiches = signal<PublishedCaptureFiche[]>([]);
  readonly publishedFichesLoading = signal(false);
  readonly publishedFichesError = signal(false);
  readonly publishedFicheCategories = computed(() =>
    [...new Set(this.publishedFiches().map((row) => row.category).filter((value): value is string => Boolean(value)))].sort(),
  );
  readonly publishedFicheDestinations = computed(() =>
    [...new Set(
      this.publishedFiches()
        .map((row) => row.destination || row.collection_slug)
        .filter((value): value is string => Boolean(value)),
    )].sort(),
  );
  readonly publishedFicheAuthors = computed(() => {
    const seen = new Set<string>();
    const rows: Array<{ id: string; label: string }> = [];
    for (const fiche of this.publishedFiches()) {
      const author = fiche.author;
      if (!author?.id || seen.has(author.id)) continue;
      seen.add(author.id);
      rows.push(author);
    }
    return rows.sort((a, b) => a.label.localeCompare(b.label));
  });
  ficheSearchQuery = '';
  ficheCategoryFilter = '';
  ficheDestinationFilter = '';
  ficheAuthorFilter = '';
  readonly postSessionQualityItems = computed(() => {
    const backlog = this.qualityBacklog();
    const items = [
      ...backlog.imprecisions,
      ...backlog.open_questions,
    ];
    return items.filter((item) => {
      const status = item.status || 'open';
      return status === 'open' || status === 'deferred';
    });
  });
  readonly conversationMode = signal<ConversationMode>('manual');
  readonly lastConversationStep = signal<ConversationStepResponse | null>(null);
  readonly recording = signal(false);
  readonly transcribing = signal(false);
  readonly dictationSurface = signal<'plan' | 'proposal_question' | 'prep' | null>(null);
  readonly dictationVoiceDetected = signal(false);
  readonly dictationSilenceEnding = signal(false);
  readonly dictationAudioLevel = signal(0);
  readonly planDictationWaveBars = [8, 14, 20, 12, 18, 16, 10];
  readonly planDictationActive = computed(
    () => this.dictationSurface() === 'plan' && (this.recording() || this.transcribing()),
  );
  readonly planDictationListening = computed(() => this.dictationSurface() === 'plan' && this.recording());
  readonly planDictationTranscribing = computed(() => this.dictationSurface() === 'plan' && this.transcribing());
  readonly speaking = signal(false);
  readonly conversationSessionActive = signal(false);
  readonly textFallbackActive = signal(false);
  readonly voiceState = signal<Voice2VoiceState>('idle');
  readonly voiceNotice = signal<string | null>(null);
  readonly voiceNoticeTone = signal<VoiceNoticeTone>('info');
  readonly session = signal<CaptureSession | null>(null);
  readonly selectedQuestionId = signal<string | null>(null);
  readonly lastEvaluation = signal<TurnResponse['evaluation'] | null>(null);
  readonly nextPrompt = signal<string | null>(null);
  readonly lastSystemPromptEventId = signal<string | null>(null);
  readonly interruptionOfEventId = signal<string | null>(null);
  readonly proposal = signal<CaptureProposal | null>(null);
  readonly proposalFactDecisions = signal<Record<string, ProposalFactDecision>>({});
  readonly proposalFactEdits = signal<Record<string, string>>({});
  readonly proposalQuestionStatuses = signal<Record<string, ProposalQuestionStatus>>({});
  readonly answeringQuestionKey = signal<string | null>(null);
  readonly questionAnswerLoading = signal(false);
  readonly highlightedReviewQuestionKey = signal<string | null>(null);
  private reviewQuestionHighlightTimer: ReturnType<typeof setTimeout> | null = null;
  questionAnswerDraft = '';
  readonly editingProposalFactKey = signal<string | null>(null);
  readonly proposalReportDirty = signal(false);
  readonly proposalReportSaving = signal(false);
  readonly proposalInstructionLoading = signal(false);
  readonly closureSheetMarkdown = signal<string | null>(null);
  readonly closurePanelDismissed = signal(false);
  readonly closureActionLoading = signal(false);
  readonly sessionClockTick = signal(0);
  private sessionClockTimer: ReturnType<typeof setInterval> | null = null;
  // Countdown anchor: latest server-provided remaining_seconds + reception
  // time. The per-second tick interpolates from it (see sessionTimerView).
  private timerAnchor: { sessionId: string; remainingSeconds: number; atMs: number } | null = null;
  private lastFiveMinutesNoticeSessionId: string | null = null;
  private readonly captureTimerAnchor = effect(() => {
    const session = this.session();
    const remaining = Number(session?.metrics?.['remaining_seconds'] ?? NaN);
    if (session && Number.isFinite(remaining)) {
      this.timerAnchor = { sessionId: session.id, remainingSeconds: remaining, atMs: Date.now() };
    } else if (!session || this.timerAnchor?.sessionId !== session.id) {
      this.timerAnchor = null;
    }
  });
  readonly events = signal<CaptureEvent[]>([]);
  readonly retrieval = signal<RetrievalPrefetch>({
    status: 'idle',
    chunks: [],
    scores: [],
    metadatas: [],
  });
  readonly editingEventId = signal<string | null>(null);
  editingText = '';
  proposalFactEditText = '';
  proposalReportDraft = '';
  proposalInstructionText = '';
  readonly sourcePreviewOpen = signal(false);
  readonly sourcePreviewUrl = signal<string | null>(null);
  readonly sourcePreviewTitle = signal('');
  readonly sourcePreviewPage = signal<number | null>(null);
  readonly sourcePreviewHighlight = signal<string | null>(null);
  // FINAL-phase gating: true between capture.finish and the proposal-ready
  // conversation.step. While true the report screen stays locked behind the
  // finalization loader, whose stage label follows the gateway's honest
  // capture.finalize.progress events.
  readonly captureFinalizing = signal(false);
  readonly captureFinalizeStage = signal<CaptureFinalizeStage | null>(null);
  private captureFinalizeTimeout: ReturnType<typeof setTimeout> | null = null;
  // Fallback armed when the heavy pass reports its terminal `done` stage: the
  // proposal-bearing conversation.step normally lands within a couple of seconds
  // and clears this, but a dropped/late terminal event would otherwise trap the
  // user on a finished-looking loader until the 4-min safety valve. This shorter
  // net fetches the persisted proposal and opens the report.
  private captureFinalizeDoneTimeout: ReturnType<typeof setTimeout> | null = null;
  // Report screen: structured fiche by default, raw markdown on demand.
  readonly reportEditMode = signal(false);
  readonly reportFiche = computed(() => this.buildReportFiche(this.proposal()));
  readonly publicationPublishing = signal(false);
  readonly publicationResult = signal<CapturePublicationResult | null>(null);
  readonly liveTranscript = signal<{ id: string; text: string; status: CaptureTranscriptStatus; reframed?: boolean } | null>(
    null,
  );
  // Finished live turns whose persisted expert event has not landed yet. When a
  // NEW turn starts, the previous live paragraph is promoted here instead of
  // being dropped, so committed text never disappears/reappears (flicker) while
  // waiting for the event refresh.
  private readonly pendingLiveCommits = signal<Array<{ id: string; text: string }>>([]);
  readonly relanceAnnotations = signal<Array<{ id: string; order: number; text: string; kind: RelanceKind }>>([]);
  // New non-blocking model: oracle's own working questions, passive suggestions.
  readonly oracleOpenQuestions = signal<OracleOpenQuestion[]>([]);
  readonly oracleQuestionsMuted = computed(() => Boolean(this.session()?.metrics?.['suppress_oracle_questions']));
  readonly activeOracleQuestions = computed(() =>
    this.oracleQuestionsMuted() ? [] : this.openOracleQuestionsForAction(this.oracleOpenQuestions()),
  );
  readonly captureSuggestions = signal<CaptureLiveSuggestion[]>([]);
  private dismissedSuggestionKeys = new Set<string>();

  readonly surfaceNav: Array<{ id: CaptureSurfaceView; label: string; icon: string; step: number }> = [
    { id: 'dashboard', label: 'capture.step.dashboard', icon: 'layout-dashboard', step: 1 },
    { id: 'prep', label: 'capture.step.prep', icon: 'sliders-horizontal', step: 2 },
    { id: 'plan', label: 'capture.step.plan', icon: 'list-checks', step: 3 },
    { id: 'session', label: 'capture.step.capture', icon: 'mic', step: 4 },
    { id: 'review', label: 'capture.step.review', icon: 'file-text', step: 5 },
    { id: 'publish', label: 'capture.step.publish', icon: 'upload', step: 6 },
  ];

  surfaceNavLabel(item: { id: CaptureSurfaceView; label: string }): string {
    return this.i18n.t(item.label);
  }

  readonly voiceWaveBars = [10, 18, 26, 14, 22, 30, 16, 24, 12, 20];
  readonly workspaceAccessRoute = computed(() => {
    const slug = this.workspace.current()?.slug || this.workspace.currentSlug();
    return slug ? ['/workspace', slug, 'access'] : '/governance/access';
  });

  private recorder: MediaRecorder | null = null;
  // Realtime lane: when the LiveKit sidecar streams the published mic track to
  // gpt-realtime-whisper, the browser must NOT also push WebM frames over the
  // data channel (the sidecar ignores them and they would waste bandwidth). The
  // mic track + client VAD endpoint stay; only the WebM frame send is skipped.
  // Set from the sidecar session.ready (stt_mode === 'realtime').
  private realtimeSttActive = false;
  private chunks: BlobPart[] = [];
  private recordedAudioBytes = 0;
  private stream: MediaStream | null = null;
  private partialTranscriptionInFlight = false;
  private partialTranscriptionSubscription: Subscription | null = null;
  private partialTranscriptionRequestId = 0;
  private activePartialTranscriptionRequestId = 0;
  private lastPartialTranscriptionStartedAt = 0;
  private partialTranscriptionDisabledForTurn = false;
  private partialTranscriptionLimitNoticeShown = false;
  private prefetchInFlight = false;
  private lastPrefetchText = '';
  private lastPrefetchAt = 0;
  private eventsSessionId: string | null = null;
  private lastEventSequence: number | null = null;
  private currentClientTurnId: string | null = null;
  private commandHandledForTurn: string | null = null;
  private activeAudio: HTMLAudioElement | null = null;
  private voiceConnection: CaptureVoiceConnection | null = null;
  private readonly ttsPlayback = this.ttsPlaybackFactory.createController('knowledge_capture');
  private pendingVoiceFrameSends: Promise<void>[] = [];
  private deferredLoopStopAfterStreamingTurn: Record<string, unknown> | null = null;
  private deferredCaptureFinishAfterStreamingTurn = false;
  private closeVoiceAfterStreamingTurn = false;
  private revokedAudioUrls: string[] = [];
  private autoResumeTimer: ReturnType<typeof setTimeout> | null = null;
  private transcriptionWatchdog: number | null = null;
  private conversationProcessingWatchdog: number | null = null;
  private captureEndpointRaf: number | null = null;
  private captureEndpointAudioContext: AudioContext | null = null;
  private captureEndpointSource: MediaStreamAudioSourceNode | null = null;
  private dictationAudioRaf: number | null = null;
  private dictationAudioContext: AudioContext | null = null;
  private dictationAudioSource: MediaStreamAudioSourceNode | null = null;
  private dictationSpeechDetected = false;
  private dictationLastVoiceAt = 0;
  private dictationTurnStartedAt = 0;
  private captureSpeechDetected = false;
  private captureLastVoiceAt = 0;
  private captureTurnStartedAt = 0;
  private captureEndpointReason: CaptureEndpointReason = 'manual';
  private captureNoiseFloor = 0;
  private captureSpeechAboveSince = 0;
  private captureSilenceBelowSince = 0;
  private captureLastVadMetricAt = 0;
  private captureEndpointCandidateTimer: ReturnType<typeof setTimeout> | null = null;
  private captureEndpointCandidateStartedAt = 0;
  private dictationNoiseFloor = 0;
  private dictationSpeechAboveSince = 0;
  private dictationSilenceBelowSince = 0;
  private dictationLastVadMetricAt = 0;
  private dictationEndpointCandidateTimer: ReturnType<typeof setTimeout> | null = null;
  private dictationEndpointCandidateStartedAt = 0;
  private lastVoiceChunkAt = 0;
  private lastSuggestedContextName = '';

  ngOnInit(): void {
    this.destroyRef.onDestroy(() => {
      if (this.transcriptAutoscrollFrame !== null) {
        window.cancelAnimationFrame(this.transcriptAutoscrollFrame);
        this.transcriptAutoscrollFrame = null;
      }
      this.stopCaptureEndpointMonitor();
      this.closeVoiceConnection();
      this.ttsPlayback.destroy();
      if (this.sessionClockTimer != null) {
        clearInterval(this.sessionClockTimer);
      }
    });
    this.sessionClockTimer = setInterval(() => {
      const session = this.session();
      if (session?.status === 'active' && !this.isSessionTimerUnlimited(session)) {
        this.sessionClockTick.update((value) => value + 1);
        this.maybeNotifyLastFiveMinutes(session);
        this.maybeOpenClosurePanel(session);
      }
    }, 1000);
    this.permissions.refresh().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
    this.contextId = this.route.snapshot.queryParamMap.get('contextId') || '';
    this.systemId =
      this.route.snapshot.paramMap.get('systemId') ||
      this.route.snapshot.queryParamMap.get('systemId') ||
      '';
    this.systemScoped.set(Boolean(this.systemId));
    this.api
      .get<{ contexts: ContextOption[] }>('/contexts')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((payload) => {
        const contexts = payload.contexts || [];
        this.contexts.set(contexts);
        if (!this.contextId) {
          const best = this.pickDefaultContext(contexts);
          if (best) {
            this.contextId = best.id;
          }
        }
        const selected = contexts.find((ctx) => ctx.id === this.contextId);
        if (selected) {
          this.zoom.setCurrentContext(selected.id, selected.name);
          this.syncKnowledgeComposerFromContext(selected);
        }
      });
    this.loadKnowledgeCollections();
    this.api
      .get<{ systems: SystemOption[] }>('/systems')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((payload) => {
        const systems = payload.systems || [];
        this.systems.set(systems);
        const scoped = systems.find((system) => system.id === this.systemId);
        if (scoped) {
          this.applySystemScope(scoped);
        }
      });
    if (this.systemId) {
      this.api
        .get<SystemOption>(`/systems/${this.systemId}`)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe((system) => this.applySystemScope(system));
    }
    this.refreshDashboard();
  }

  private asRecord(value: unknown): Record<string, unknown> {
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
  }

  startNewSessionDraft(): void {
    if (!this.canCaptureCreate()) {
      this.setVoiceNotice('Votre rôle ne permet pas de créer une session de capture dans ce workspace.', 'error');
      return;
    }
    this.resetCurrentCaptureSessionState();
    this.sessionTitle = '';
    this.objective = '';
    this.answer = '';
    this.expertProfile = 'Expert métier';
    this.durationMinutes = 20;
    this.durationUnlimited.set(false);
    this.selectedDomain = 'technical';
    this.selectedPlanMode = this.isDemoMode() ? 'plan_build' : 'free_conversation';
    this.providedPlanText = '';
    this.providedPlanFileName = '';
    this.providedPlanSourceKind = 'pasted_text';
    this.providedPlanReplacesExisting = false;
    this.pendingPlanSourceReplacement.set(null);
    this.planDialogueAnswer.set('');
    this.executiveSummary = '';
    this.publicationCategory = 'technical';
    this.publicationDestination = '';
    this.publicationDestinationCustom.set(false);
    this.publicationFinalTitle = '';
    this.planSourceStep.set(false);
    this.extractingPlanSource.set(false);
    this.conversationMode.set('conversation_only');
    this.activeSurface.set('prep');
  }

  continueFromPreparation(): void {
    if (this.loading()) return;
    if (!this.canCaptureCreate()) {
      this.setVoiceNotice('Votre rôle ne permet pas de créer une session de capture dans ce workspace.', 'error');
      return;
    }
    if (!this.sessionTitle.trim()) {
      this.setVoiceNotice('Renseignez un titre de session avant de continuer.', 'warning');
      return;
    }
    this.resetCurrentCaptureSessionState();
    this.planSourceStep.set(false);
    if (this.selectedPlanMode === 'provided_plan') {
      this.planSourceStep.set(true);
      this.activeSurface.set('plan');
      return;
    }
    this.createPlan();
  }

  preparationBlockingHint(): string | null {
    if (!this.sessionTitle.trim()) return 'Renseignez un titre de session pour continuer.';
    if (!this.canCaptureCreate()) return 'Votre rôle ne permet pas de créer une session de capture dans ce workspace.';
    return null;
  }

  private resetCurrentCaptureSessionState(): void {
    if (this.conversationSessionActive() || this.recording() || this.speaking() || this.transcribing()) {
      this.stopConversationSession();
    }
    this.session.set(null);
    this.selectedQuestionId.set(null);
    this.lastEvaluation.set(null);
    this.nextPrompt.set(null);
    this.lastSystemPromptEventId.set(null);
    this.interruptionOfEventId.set(null);
    this.setProposal(null);
    this.closureSheetMarkdown.set(null);
    this.closurePanelDismissed.set(false);
    this.events.set([]);
    this.eventsSessionId = null;
    this.lastEventSequence = null;
    this.hintStack.set([]);
    this.activeSubtopicId.set(null);
    this.questionBankStatus.set('idle');
    this.planNotice.set(null);
    this.planDialogueReadyFlag.set(false);
    this.planDialogueNextPrompt.set(null);
    this.pendingPlanSourceReplacement.set(null);
    this.lastConversationStep.set(null);
    this.textFallbackActive.set(false);
    this.retrieval.set({ status: 'idle', chunks: [], scores: [], metadatas: [] });
    this.liveTranscript.set(null);
    this.pendingLiveCommits.set([]);
    this.relanceAnnotations.set([]);
    this.oracleOpenQuestions.set([]);
    this.captureSuggestions.set([]);
    this.dismissedSuggestionKeys.clear();
    this.currentClientTurnId = null;
    this.lastPrefetchText = '';
    this.lastPrefetchAt = 0;
  }

  /** Drop in-memory capture transcript rows when leaving plan co-construction. */
  private clearCaptureTranscriptState(): void {
    this.liveTranscript.set(null);
    this.pendingLiveCommits.set([]);
    this.relanceAnnotations.set([]);
    this.answer = '';
    this.currentClientTurnId = null;
    this.transcriptAtBottom.set(true);
  }

  createPlan(): void {
    if (!this.canCaptureCreate()) {
      this.voiceNotice.set('Votre rôle ne permet pas de créer une session de capture dans ce workspace.');
      return;
    }
    const title = this.sessionTitle.trim();
    if (!title) {
      this.setVoiceNotice('Renseignez un titre de session avant de continuer.', 'warning');
      return;
    }
    if (this.selectedPlanMode === 'provided_plan' && !this.canSubmitProvidedPlanSource()) {
      this.setVoiceNotice('Ajoutez un texte source pour construire le plan.', 'warning');
      this.planSourceStep.set(true);
      return;
    }
    this.loading.set(true);
    this.api
      .createCapturePlan({
        title,
        objective: this.captureObjectiveForPlan(),
        expert_profile: this.expertProfile,
        duration_minutes: this.durationUnlimited() ? 0 : Number(this.durationMinutes) || 20,
        context_id: this.isPilotMode() ? null : this.contextId || null,
        system_id: this.systemId || null,
        voice_runtime: 'cascade_openai',
        plan_mode: this.selectedPlanMode === 'plan_build' ? 'plan_build' : this.selectedPlanMode,
        capture_domain: this.selectedDomain,
        provided_plan_text: this.providedPlanText || null,
        plan_source_kind: this.hasProvidedPlanSource() ? this.providedPlanSourceKind : null,
        plan_source_filename: this.providedPlanFileName || null,
        plan_source_replaces_existing_plan: this.providedPlanReplacesExisting,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (session) => {
          const typed = session as CaptureSession;
          this.session.set(typed);
          this.zoom.setCurrentCapability(typed.capability_id || null, this.i18n.t('capture.title'));
          this.zoom.setCurrentSystem(typed.system_id || null, this.systemLabel(typed.system_id));
          this.zoom.setCurrentContext(typed.context_id || null, this.contextLabel(typed.context_id));
          this.selectedQuestionId.set(this.planQuestions(typed)[0]?.id || null);
          this.planNotice.set({
            tone: 'info',
            text: this.isFreeConversationSession(typed)
              ? this.i18n.t('capture.notice.free_ready')
              : this.i18n.t('capture.notice.plan_ready'),
          });
          this.refreshEvents(typed.id);
          this.refreshDashboard();
          if (this.isPlanBuildSession(typed)) {
            this.planSourceStep.set(false);
            this.activeSurface.set('plan_build');
            this.planDialogueNextPrompt.set(this.planDialoguePromptFor(typed));
          } else {
            this.activeSurface.set(this.isFreeConversationSession(typed) ? 'session' : 'plan');
          }
          this.loading.set(false);
          if (this.isFreeConversationSession(typed)) {
            this.conversationMode.set('conversation_only');
          }
        },
        error: () => this.loading.set(false),
      });
  }

  selectPlanMode(mode: string): void {
    const entry = this.visiblePlanModes().find((row) => row.id === mode);
    if (!entry || entry.disabled) return;
    if (mode === 'ai_plan' || mode === 'provided_plan' || mode === 'free_conversation' || mode === 'plan_build') {
      this.selectedPlanMode = mode;
      if (mode !== 'provided_plan') {
        this.planSourceStep.set(false);
      }
      if (mode === 'free_conversation') {
        this.conversationMode.set('conversation_only');
      } else if (!this.session()) {
        this.conversationMode.set(this.isDemoMode() ? 'conversation_only' : 'manual');
      }
      if (mode === 'plan_build') {
        this.selectedPlanMode = 'plan_build';
      }
    }
  }

  isPlannedCaptureMode(): boolean {
    return this.selectedPlanMode === 'plan_build' || this.selectedPlanMode === 'provided_plan' || this.selectedPlanMode === 'ai_plan';
  }

  isCaptureModeSelected(mode: CapturePlanMode): boolean {
    if (mode === 'plan_build') return this.isPlannedCaptureMode();
    return this.selectedPlanMode === mode;
  }

  canCreateSelectedPlan(): boolean {
    return this.canCaptureCreate() && Boolean(this.sessionTitle.trim());
  }

  canSubmitProvidedPlanSource(): boolean {
    return this.canCreateSelectedPlan() && this.providedPlanText.trim().length >= 3;
  }

  onProvidedPlanTextChange(value: string): void {
    this.providedPlanText = value;
    if (!value.trim()) {
      if (this.providedPlanFileName) {
        this.providedPlanSourceKind = 'uploaded_file';
      }
      return;
    }
    if (!this.providedPlanFileName) {
      this.providedPlanSourceKind = 'pasted_text';
    }
  }

  hasProvidedPlanSource(): boolean {
    return Boolean(this.providedPlanText.trim() || this.providedPlanFileName);
  }

  providedPlanSourceLabel(): string {
    if (this.providedPlanFileName) return this.providedPlanFileName;
    if (this.providedPlanText.trim()) {
      return 'Texte source';
    }
    return 'Aucune source active';
  }

  providedPlanSourceKindLabel(kind: CapturePlanSourceKind = this.providedPlanSourceKind): string {
    switch (kind) {
      case 'uploaded_file':
        return 'Fichier source';
      case 'conversation':
        return 'Texte source';
      case 'pasted_text':
        return 'Texte source';
      default:
        return 'Texte source';
    }
  }

  providedPlanSourceStats(): string {
    const text = this.providedPlanText.trim();
    if (!text) return this.providedPlanFileName ? 'Extraction en attente' : 'Aucun contenu';
    const lines = text.split(/\r?\n/).filter((line) => line.trim()).length;
    return `${text.length.toLocaleString('fr-FR')} caractères · ${lines.toLocaleString('fr-FR')} ligne(s)`;
  }

  providedPlanSourcePreview(): string {
    const text = this.providedPlanText.replace(/\s+/g, ' ').trim();
    if (!text) return 'L’interprétation extraite apparaîtra ici avant création du plan.';
    return text.length > 260 ? `${text.slice(0, 260)}…` : text;
  }

  planSourceSummary(session: CaptureSession): CapturePlanSourceSummary | null {
    const source = this.asRecord(session.plan?.['plan_source']);
    if (!Object.keys(source).length) return null;
    const kind = String(source['kind'] || 'manual') as CapturePlanSourceKind;
    const filename = String(source['filename'] || '').trim();
    const chars = Number(source['chars'] || 0);
    const lineCount = Number(source['line_count'] || 0);
    const outline = this.planSourceExtractedOutline(source['extracted_outline']);
    const stats = [
      chars > 0 ? `${chars.toLocaleString('fr-FR')} caractères` : null,
      lineCount > 0 ? `${lineCount.toLocaleString('fr-FR')} ligne(s)` : null,
      outline.length ? `${outline.length.toLocaleString('fr-FR')} rubrique(s)` : null,
    ].filter(Boolean).join(' · ');
    return {
      kindLabel: this.providedPlanSourceKindLabel(kind),
      title: filename || this.providedPlanSourceKindLabel(kind),
      stats: stats || 'Source enregistrée',
      extractedOutline: outline.slice(0, 8),
      replacedExistingPlan: source['replaces_existing_plan'] === true,
    };
  }

  private planSourceExtractedOutline(value: unknown): CapturePlanSourceOutlineItem[] {
    if (!Array.isArray(value)) return [];
    return value
      .map((item) => {
        const row = this.asRecord(item);
        const title = String(row['title'] || '').trim();
        const subtopics = Array.isArray(row['subtopics'])
          ? row['subtopics'].map((subtopic) => String(subtopic || '').trim()).filter(Boolean)
          : [];
        return title ? { title, subtopics } : null;
      })
      .filter((item): item is CapturePlanSourceOutlineItem => Boolean(item));
  }

  pendingPlanSourceStats(source: PendingPlanSourceReplacement): string {
    if (!source.size) return 'Taille inconnue';
    if (source.size < 1024) return `${source.size} o`;
    if (source.size < 1024 * 1024) return `${(source.size / 1024).toFixed(1)} Ko`;
    return `${(source.size / 1024 / 1024).toFixed(1)} Mo`;
  }

  clearProvidedPlanSource(): void {
    this.providedPlanText = '';
    this.providedPlanFileName = '';
    this.providedPlanSourceKind = 'pasted_text';
    this.providedPlanReplacesExisting = false;
    this.pendingPlanSourceReplacement.set(null);
  }

  confirmProvidedPlanReplacement(): void {
    const pending = this.pendingPlanSourceReplacement();
    if (!pending) return;
    this.pendingPlanSourceReplacement.set(null);
    this.providedPlanReplacesExisting = true;
    this.extractProvidedPlanFile(pending.file);
  }

  cancelProvidedPlanReplacement(): void {
    this.pendingPlanSourceReplacement.set(null);
  }

  backToPlanModeSelection(): void {
    this.planSourceStep.set(false);
    this.activeSurface.set('prep');
  }

  canNavigateTo(view: CaptureSurfaceView): boolean {
    if (view === 'dashboard' || view === 'prep') return true;
    const current = this.session();
    if (view === 'plan') {
      if (!current) {
        return this.planSourceStep() && this.canCaptureCreate() && Boolean(this.sessionTitle.trim());
      }
      if (this.isFreeConversationSession(current)) return false;
      if (this.isPlanBuildSession(current)) {
        // Trame tab unlocks once the co-construction produced an outline
        // (finalizePlanBuild moves the surface to 'plan' even on plan_build_v2).
        return this.planTopics(current).length > 0;
      }
      return true;
    }
    if (view === 'plan_build') {
      return Boolean(current) && this.isPlanBuildSession(current!);
    }
    if (view === 'session') {
      if (!current) return false;
      if (this.isPlanBuildSession(current)) return this.planTopics(current).length > 0;
      return current.status === 'active' || current.status === 'paused' || this.stepIsComplete('plan');
    }
    if (view === 'review') {
      // The report screen stays locked while the heavy FINAL pass runs.
      if (this.captureFinalizing()) return false;
      return Boolean(this.proposal()) || current?.status === 'completed';
    }
    if (view === 'publish') {
      return Boolean(this.proposal()) && Boolean(this.proposalReportText()) && this.proposal()?.status !== 'published';
    }
    return false;
  }

  goSurface(view: CaptureSurfaceView): void {
    if (view === 'publish') {
      const proposal = this.proposal();
      if (proposal && proposal.status !== 'accepted' && proposal.status !== 'published') {
        if (this.canContinueFromReview(proposal)) {
          this.continueFromReview(proposal);
          return;
        }
      }
    }
    if (!this.canNavigateTo(view)) return;
    if (view === 'prep' || view === 'dashboard') {
      this.planSourceStep.set(false);
    }
    this.activeSurface.set(view);
    if (view === 'dashboard') {
      this.refreshDashboard();
      if (this.dashboardTab() === 'fiches') {
        this.refreshPublishedFiches();
      }
    }
    if (view === 'session' && this.session()) {
      this.refreshQualityBacklog(this.session()!.id);
      const resume = (this.session()?.metrics?.['resume_summary'] as string) || null;
      if (this.session()?.status === 'paused' && resume) {
        this.setVoiceNotice(resume, 'info');
      }
    }
    if (view === 'review') {
      if (this.session()) {
        this.refreshQualityBacklog(this.session()!.id);
      }
      if (!this.proposal() && this.session()) {
        this.refreshDashboard();
        this.executiveSummary = this.proposal()?.proposal?.title || this.session()?.title || '';
      }
    }
  }

  toggleDurationUnlimited(): void {
    this.durationUnlimited.update((value) => !value);
  }

  knowledgeScopeLabel(): string {
    if (this.isPilotMode()) {
      return this.selectedContext()?.environment_state?.collection || this.selectedContext()?.name || 'Base workspace';
    }
    return this.selectedContext()?.name || 'Sources workspace';
  }

  async startGuidedSession(session: CaptureSession): Promise<void> {
    if (this.loading()) return;
    this.clearCaptureTranscriptState();
    if (!this.canCaptureExecute(session)) {
      this.setVoiceNotice('Votre rôle ne permet pas de démarrer cette session de capture.', 'error');
      return;
    }
    if (!this.canStartSessionPlan(session)) {
      this.planNotice.set({ tone: 'error', text: 'Ajoutez au moins une question ou passez en capture libre avant de démarrer.' });
      this.activeSurface.set('plan');
      return;
    }
    this.loading.set(true);
    // The explicit "Valider les sujets" gate is gone, so persist any inline
    // edits to the topics before starting. The backend auto-triggers
    // question-bank generation on start when idle, so no confirm step is needed.
    const topics = this.planTopics(session);
    if (this.isTopicOnlyPlan(session) && topics.length) {
      try {
        await firstValueFrom(
          this.api
            .updateCapturePlanTopics(session.id, topics as unknown as Record<string, unknown>[])
            .pipe(takeUntilDestroyed(this.destroyRef)),
        );
      } catch {
        // Non-blocking: start the session even if the topics PATCH fails.
      }
    }
    let conversationOnly = this.conversationMode() === 'conversation_only';
    let armed = true;
    if (conversationOnly) {
      this.conversationSessionActive.set(true);
      this.setVoiceNotice('Préparation du micro pour la conversation.', 'info');
      armed = await this.ensureAudioStream();
      if (!armed) {
        this.conversationSessionActive.set(false);
        this.voiceState.set('idle');
        this.conversationMode.set('manual');
        this.textFallbackActive.set(true);
        conversationOnly = false;
        this.setVoiceNotice('Micro indisponible : la session démarre en saisie guidée, sans bloquer le parcours.', 'warning');
      } else {
        this.textFallbackActive.set(false);
      }
    }
    this.api
      .startCaptureSession(session.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (payload) => {
          const typed = payload as CaptureSession;
          this.session.set(typed);
          this.ensureDefaultPlanSection(typed);
          const questions = this.planQuestions(typed);
          const selected = this.selectedQuestionId();
          this.selectedQuestionId.set(
            selected && questions.some((question) => question.id === selected)
              ? selected
              : questions[0]?.id || null,
          );
          this.refreshEvents(typed.id);
          this.refreshQualityBacklog(typed.id);
          this.refreshDashboard();
          this.activeSurface.set('session');
          this.loading.set(false);
          if (conversationOnly && armed) {
            void this.ensureVoiceConnection(typed).then(() => {
              const firstPrompt = this.spokenSectionPrompt();
              if (firstPrompt && !this.isFreeConversationSession(typed) && !this.isTopicOnlyPlan(typed)) {
                this.speak(firstPrompt);
              } else {
                void this.startRecordingTurn();
              }
            });
          }
        },
        error: () => {
          if (conversationOnly) {
            this.stopConversationSession();
          }
          this.setVoiceNotice('Démarrage de session impossible. Vérifiez le backend, puis réessayez.', 'error');
          this.loading.set(false);
        },
      });
  }

  private refreshDashboardQualityRows(sessions: CaptureSession[]): void {
    const targets = sessions.filter((row) => row.status === 'completed' || row.status === 'paused').slice(0, 6);
    if (!targets.length) {
      this.dashboardQualityRows.set([]);
      return;
    }
    let pending = targets.length;
    const aggregated: Array<{ sessionId: string; sessionTitle: string; item: QualityBacklogItem }> = [];
    for (const row of targets) {
      this.api
        .getCaptureQualityBacklog(row.id)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe((payload) => {
          for (const bucket of ['imprecisions', 'open_questions'] as const) {
            for (const item of (payload[bucket] || []) as QualityBacklogItem[]) {
              const status = item.status || 'open';
              if (status === 'open' || status === 'deferred') {
                aggregated.push({ sessionId: row.id, sessionTitle: row.title, item });
              }
            }
          }
          pending -= 1;
          if (pending <= 0) {
            this.dashboardQualityRows.set(aggregated.slice(0, 12));
          }
        });
    }
  }

  startClarificationSession(): void {
    const current = this.session();
    const seed = this.postSessionQualityItems()
      .map((item) => item.label || item.follow_up || '')
      .filter(Boolean)
      .join('\n');
    this.session.set(null);
    this.proposal.set(null);
    this.providedPlanText = seed ? `# Points à clarifier\n${seed}` : '';
    this.sessionTitle = current?.title ? `${current.title} — clarification` : 'Clarification expert';
    this.objective = current?.objective || this.objective;
    this.selectedPlanMode = seed ? 'provided_plan' : 'free_conversation';
    this.activeSurface.set('prep');
  }

  openDashboardSessionForQuality(sessionId: string): void {
    const row = this.dashboardSessions().find((item) => item.id === sessionId);
    if (!row) return;
    this.session.set(row);
    this.refreshQualityBacklog(row.id);
    if (row.status === 'completed') {
      if (!this.proposal() || this.proposal()?.session_id !== row.id) {
        this.setProposal(null);
        this.loadLatestSessionProposal(row.id);
      }
      this.activeSurface.set('review');
      return;
    }
    this.openDashboardSession(row);
  }

  setDashboardTab(tab: 'sessions' | 'fiches'): void {
    this.dashboardTab.set(tab);
    if (tab === 'fiches') {
      this.refreshPublishedFiches();
    }
  }

  refreshPublishedFiches(): void {
    this.publishedFichesLoading.set(true);
    this.publishedFichesError.set(false);
    this.api
      .listPublishedCaptureFiches({
        q: this.ficheSearchQuery.trim() || undefined,
        category: this.ficheCategoryFilter || undefined,
        destination: this.ficheDestinationFilter || undefined,
        author_user_id: this.ficheAuthorFilter || undefined,
        limit: 100,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (payload) => {
          this.publishedFiches.set(payload.fiches || []);
          this.publishedFichesLoading.set(false);
        },
        error: () => {
          this.publishedFiches.set([]);
          this.publishedFichesLoading.set(false);
          this.publishedFichesError.set(true);
        },
      });
  }

  publishedFicheDateLabel(row: PublishedCaptureFiche): string {
    const raw = row.published_at;
    if (!raw) return '—';
    const date = new Date(raw);
    if (Number.isNaN(date.getTime())) return raw;
    return date.toLocaleString();
  }

  publishedFicheWordLabel(row: PublishedCaptureFiche): string {
    const count = row.word_count || 0;
    return count === 1
      ? this.i18n.t('capture.fiches.words_one')
      : this.i18n.t('capture.fiches.words_many', { count });
  }

  publishedFicheChunkLabel(row: PublishedCaptureFiche): string {
    const count = row.chunks_processed || 0;
    return count === 1
      ? this.i18n.t('capture.fiches.chunks_one')
      : this.i18n.t('capture.fiches.chunks_many', { count });
  }

  publishedFicheOpenQuestionsLabel(row: PublishedCaptureFiche): string {
    const count = row.open_questions_count || 0;
    return count === 1
      ? this.i18n.t('capture.fiches.open_questions_one')
      : this.i18n.t('capture.fiches.open_questions_many', { count });
  }

  openPublishedFichePreview(row: PublishedCaptureFiche): void {
    // Whole-file browsing — no retrieved passage to highlight.
    this.sourcePreviewPage.set(null);
    this.sourcePreviewHighlight.set(null);
    const previewPath = row.preview_url;
    if (previewPath) {
      this.sourcePreviewTitle.set(row.title);
      this.sourcePreviewUrl.set(`${this.api.base}/${previewPath}`);
      this.sourcePreviewOpen.set(true);
      return;
    }
    const documentId = row.document_id;
    const collection = row.collection_slug;
    if (!documentId || !collection) return;
    this.sourcePreviewTitle.set(row.title);
    this.sourcePreviewUrl.set(
      `${this.api.base}/documents/${encodeURIComponent(documentId)}/rich-preview` +
        `?collection_name=${encodeURIComponent(collection)}`,
    );
    this.sourcePreviewOpen.set(true);
  }

  openPublishedFicheCollection(row: PublishedCaptureFiche): void {
    const slug = row.collection_slug || row.destination;
    if (!slug) return;
    const workspaceSlug = this.workspace.current()?.slug || this.workspace.currentSlug();
    if (!workspaceSlug) return;
    void this.router.navigate(['/workspace', workspaceSlug, 'knowledge', slug]);
  }

  openPublishedFicheSession(row: PublishedCaptureFiche): void {
    const existing = this.dashboardSessions().find((session) => session.id === row.capture_session_id);
    if (existing) {
      this.dashboardTab.set('sessions');
      this.openDashboardSession(existing);
      return;
    }
    this.loading.set(true);
    this.api
      .listCaptureSessions(undefined, undefined, this.systemId || undefined, true)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (payload) => {
          const sessions = (payload as { sessions?: CaptureSession[] }).sessions || [];
          const match = sessions.find((session) => session.id === row.capture_session_id);
          this.loading.set(false);
          if (!match) {
            this.setVoiceNotice('Session source introuvable ou non accessible.', 'warning');
            return;
          }
          this.dashboardTab.set('sessions');
          this.openDashboardSession(match);
        },
        error: () => {
          this.loading.set(false);
          this.setVoiceNotice('Impossible d’ouvrir la session source.', 'error');
        },
      });
  }

  refreshDashboard(): void {
    this.api
      .listCaptureSessions(
        undefined,
        this.dashboardDomainFilter || undefined,
        this.systemId || undefined,
        this.showArchivedSessions(),
      )
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((payload) => {
        const sessions = (payload as { sessions?: CaptureSession[] }).sessions || [];
        const scoped = this.systemId
          ? sessions.filter((row) => !row.system_id || row.system_id === this.systemId)
          : sessions;
        const rows = scoped.slice(0, this.showArchivedSessions() ? 16 : 8);
        this.dashboardSessions.set(rows);
        this.refreshDashboardQualityRows(rows.filter((row) => !row.archived));
      });
    this.api
      .listCaptureProposals(undefined, this.systemId || undefined)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((payload) => {
        const proposals = (payload as { proposals?: CaptureProposal[] }).proposals || [];
        const sessionIds = new Set(this.dashboardSessions().map((row) => row.id));
        const scoped = this.systemId && sessionIds.size
          ? proposals.filter((row) => !row.session_id || sessionIds.has(row.session_id))
          : proposals;
        this.dashboardProposals.set(scoped.slice(0, 8));
      });
  }

  private setProposal(proposal: CaptureProposal | null): void {
    const previousId = this.proposal()?.id || null;
    this.proposal.set(proposal);
    if ((proposal?.id || null) !== previousId) {
      this.proposalFactDecisions.set({});
      this.proposalFactEdits.set({});
      this.proposalQuestionStatuses.set({});
      this.editingProposalFactKey.set(null);
      this.proposalFactEditText = '';
      this.proposalReportDraft = this.proposalReportContent(proposal);
      this.proposalReportDirty.set(false);
      this.syncPublicationDraftFromProposal(proposal);
      this.publicationResult.set(null);
    } else if (!this.proposalReportDirty()) {
      this.proposalReportDraft = this.proposalReportContent(proposal);
    }
    if (proposal) {
      this.syncLocalSessionOpenQuestionCount();
    }
  }

  private syncPublicationDraftFromProposal(proposal: CaptureProposal | null): void {
    const publication = proposal?.proposal?.publication || {};
    const metadata = proposal?.proposal?.recommended_ingestion?.metadata || {};
    const category = String(
      publication.category ||
      metadata['publication_category'] ||
      metadata['publication_category_suggested'] ||
      'technical',
    );
    this.publicationCategory = this.publicationCategoryOptions.some((option) => option.id === category)
      ? category
      : 'other';
    this.publicationDestination = String(
      publication.destination_scope ||
      publication.destination ||
      metadata['publication_destination_scope'] ||
      metadata['publication_destination_scope_suggested'] ||
      metadata['publication_destination'] ||
      metadata['publication_destination_suggested'] ||
      '',
    );
    this.publicationDestinationCustom.set(false);
    this.publicationFinalTitle = String(
      publication.final_title ||
      metadata['publication_final_title'] ||
      proposal?.proposal?.recommended_ingestion?.title ||
      proposal?.proposal?.title ||
      '',
    );
  }

  openDashboardSession(row: CaptureSession): void {
    this.session.set(row);
    this.ensureDefaultPlanSection(row);
    this.closurePanelDismissed.set(false);
    this.syncClosureSheetFromSession(row);
    this.setProposal(null);
    this.loadLatestSessionProposal(row.id);
    const selected = this.selectedQuestionId();
    const questions = this.planQuestions(row);
    this.selectedQuestionId.set(
      selected && questions.some((question) => question.id === selected)
        ? selected
        : questions[0]?.id || null,
    );
    this.refreshEvents(row.id);
    this.activeSurface.set(row.status === 'completed' ? 'review' : 'session');
  }

  /**
   * Re-entering an existing session must restore the last generated report:
   * the proposal is persisted server-side but was previously only populated
   * via live WS events, so reopening a session showed an empty report tab.
   */
  private loadLatestSessionProposal(sessionId: string): void {
    this.api
      .listCaptureProposals(undefined, undefined, sessionId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((payload) => {
        const proposals = (payload as { proposals?: CaptureProposal[] }).proposals || [];
        const latest = proposals[0] || null;
        // Don't clobber a proposal that arrived in the meantime (e.g. WS event).
        if (latest && this.session()?.id === sessionId && !this.proposal()) {
          this.setProposal(latest);
        }
      });
  }

  toggleArchivedSessions(): void {
    this.showArchivedSessions.update((value) => !value);
    this.refreshDashboard();
  }

  archiveSession(row: CaptureSession, event?: Event): void {
    event?.stopPropagation();
    if (this.sessionActionLoading()) return;
    this.sessionActionLoading.set(row.id);
    this.api
      .archiveCaptureSession(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.sessionActionLoading.set(null);
          if (this.session()?.id === row.id) {
            this.session.set(null);
          }
          this.setVoiceNotice(`Session « ${row.title} » archivée.`, 'info');
          this.refreshDashboard();
        },
        error: () => {
          this.sessionActionLoading.set(null);
          this.setVoiceNotice('Archivage impossible pour le moment.', 'error');
        },
      });
  }

  unarchiveSession(row: CaptureSession, event?: Event): void {
    event?.stopPropagation();
    if (this.sessionActionLoading()) return;
    this.sessionActionLoading.set(row.id);
    this.api
      .unarchiveCaptureSession(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.sessionActionLoading.set(null);
          this.setVoiceNotice(`Session « ${row.title} » restaurée.`, 'info');
          this.refreshDashboard();
        },
        error: () => {
          this.sessionActionLoading.set(null);
          this.setVoiceNotice('Restauration impossible pour le moment.', 'error');
        },
      });
  }

  requestDeleteSession(row: CaptureSession, event?: Event): void {
    event?.stopPropagation();
    this.confirmDeleteSessionId.set(this.confirmDeleteSessionId() === row.id ? null : row.id);
  }

  cancelDeleteSession(event?: Event): void {
    event?.stopPropagation();
    this.confirmDeleteSessionId.set(null);
  }

  confirmDeleteSession(row: CaptureSession, event?: Event): void {
    event?.stopPropagation();
    if (this.sessionActionLoading()) return;
    this.sessionActionLoading.set(row.id);
    this.api
      .deleteCaptureSession(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.sessionActionLoading.set(null);
          this.confirmDeleteSessionId.set(null);
          if (this.session()?.id === row.id) {
            this.session.set(null);
            this.setProposal(null);
          }
          this.setVoiceNotice(`Session « ${row.title} » supprimée.`, 'info');
          this.refreshDashboard();
        },
        error: () => {
          this.sessionActionLoading.set(null);
          this.setVoiceNotice('Suppression impossible pour le moment.', 'error');
        },
      });
  }

  openDashboardProposal(row: CaptureProposal): void {
    this.setProposal(row);
    const related = this.dashboardSessions().find((session) => session.id === row.session_id);
    if (related) {
      this.session.set(related);
      this.refreshEvents(related.id);
    }
    this.activeSurface.set('review');
  }

  activeSessionCount(): number {
    return this.dashboardSessions().filter((row) => !['completed', 'cancelled'].includes(row.status)).length;
  }

  pendingProposalCount(): number {
    return this.dashboardProposals().filter((row) => row.status === 'pending_review').length;
  }

  sessionCardSummary(session: CaptureSession): string {
    if (session.summary_short?.trim()) return session.summary_short.trim();
    const summary = session.metrics?.['summary_short'];
    if (typeof summary === 'string' && summary.trim()) return summary.trim();
    if (session.objective?.trim()) return session.objective.trim();
    if (this.isFreeConversationSession(session)) return this.i18n.t('capture.session.free_summary');
    const topics = this.planTopics(session).map((topic) => topic.title).filter(Boolean).slice(0, 2);
    return topics.length
      ? this.i18n.t('capture.session.plan_prefix', { topics: topics.join(', ') })
      : this.i18n.t('capture.session.default_summary');
  }

  sessionOpenQuestionCount(session: CaptureSession): number {
    if (this.proposal()?.session_id === session.id) {
      return this.proposalUnresolvedOpenQuestionCount();
    }
    const topLevel = Number(session.open_questions_count);
    if (Number.isFinite(topLevel) && topLevel >= 0) return topLevel;
    const fromMetrics = Number(session.metrics?.['open_questions_count']);
    if (Number.isFinite(fromMetrics) && fromMetrics >= 0) return fromMetrics;
    return 0;
  }

  sessionCardActionLabel(session: CaptureSession): string {
    const status = String(session.status || '').toLowerCase();
    if (status === 'active' || status === 'paused') return this.i18n.t('capture.action.resume');
    return this.i18n.t('capture.action.open');
  }

  captureSessionStatusLabel(session: CaptureSession): string {
    if (session.status === 'completed' && this.sessionOpenQuestionCount(session) > 0) {
      return this.i18n.t('capture.session.status.completed_with_open_questions');
    }
    if (session.status === 'completed') return this.i18n.t('capture.session.status.completed');
    if (session.status === 'active' || session.status === 'paused' || session.status === 'planned') {
      return this.i18n.t('capture.session.status.in_progress');
    }
    return this.workflowStatusLabel(session.status);
  }

  sessionOpenQuestionsLabel(session: CaptureSession): string {
    const count = this.sessionOpenQuestionCount(session);
    return this.i18n.t(
      count === 1 ? 'capture.dashboard.open_questions_one' : 'capture.dashboard.open_questions_many',
      { count },
    );
  }

  sessionLastActivityLabel(session: CaptureSession): string {
    const metricActivity = session.metrics?.['last_activity'];
    const activity =
      session.last_activity ||
      (typeof metricActivity === 'string' ? metricActivity : null) ||
      session.completed_at ||
      session.started_at;
    if (!activity) {
      if (this.isFreeConversationSession(session)) return this.i18n.t('capture.dashboard.no_plan');
      const count = this.planSubtopicCount(session);
      return this.i18n.t(
        count === 1 ? 'capture.dashboard.subtopics_one' : 'capture.dashboard.subtopics_many',
        { count },
      );
    }
    return this.i18n.t('capture.dashboard.last_activity', {
      date: new Intl.DateTimeFormat(this.i18n.locale() === 'en' ? 'en-US' : 'fr-FR').format(new Date(activity)),
    });
  }

  workflowStatusLabel(status?: string | null): string {
    const normalized = String(status || '').toLowerCase();
    const labels: Record<string, string> = {
      planned: 'capture.workflow.status.planned',
      active: 'capture.workflow.status.active',
      paused: 'capture.workflow.status.paused',
      completed: 'capture.workflow.status.completed',
      pending_review: 'capture.workflow.status.pending_review',
      accepted: 'capture.workflow.status.accepted',
      rejected: 'capture.workflow.status.rejected',
      published: 'capture.workflow.status.published',
      failed: 'capture.workflow.status.failed',
    };
    return this.i18n.t(labels[normalized] || status || 'capture.workflow.status.unknown');
  }

  stepIsComplete(view: CaptureSurfaceView): boolean {
    const order: CaptureSurfaceView[] = ['dashboard', 'prep', 'plan', 'plan_build', 'session', 'review', 'publish'];
    const activeIndex = order.indexOf(this.activeSurface());
    const viewIndex = order.indexOf(view);
    const current = this.session();
    if (viewIndex >= 0 && activeIndex > viewIndex) return true;
    if (view === 'prep') return Boolean(current);
    if (view === 'plan_build') return current ? !this.isPlanBuildSession(current) : false;
    if (view === 'plan') return current ? this.planQuestions(current).length > 0 && !this.isPlanBuildSession(current) : false;
    if (view === 'session') {
      return Number(current?.metrics?.['captured_facts'] || 0) > 0 || current?.status === 'active';
    }
    if (view === 'review') return Boolean(this.proposal());
    if (view === 'publish') return this.proposal()?.status === 'published';
    return activeIndex > 0;
  }

  canCaptureCreate(): boolean {
    return this.permissions.can('capture_session', 'create');
  }

  canCaptureUpdate(session?: CaptureSession | null): boolean {
    return this.permissions.can('capture_session', 'update', {
      owner_user_id: session?.created_by_user_id || null,
    });
  }

  canCaptureExecute(session?: CaptureSession | null): boolean {
    return this.permissions.can('capture_session', 'execute', {
      owner_user_id: session?.created_by_user_id || null,
    });
  }

  canProposalSubmit(session?: CaptureSession | null): boolean {
    return this.permissions.can('knowledge_proposal', 'submit_review', {
      owner_user_id: session?.created_by_user_id || null,
    });
  }

  canProposalReview(proposal?: CaptureProposal | null): boolean {
    const relatedSession = this.session();
    const resource = {
      owner_user_id: proposal?.created_by_user_id || relatedSession?.created_by_user_id || null,
    };
    return this.permissions.can('knowledge_proposal', 'review_decide', resource);
  }

  canProposalPublish(proposal?: CaptureProposal | null): boolean {
    const relatedSession = this.session();
    return this.permissions.can('knowledge_proposal', 'trigger_ingestion', {
      owner_user_id: proposal?.created_by_user_id || relatedSession?.created_by_user_id || null,
    });
  }

  proposalReviewHint(proposal?: CaptureProposal | null): string | null {
    if (!this.proposalReportText()) return 'Ajoutez ou générez un rapport avant validation.';
    if (proposal?.status === 'accepted') return null;
    if (!this.canProposalReview(proposal)) return 'Votre rôle peut préparer le rapport, mais pas le valider.';
    if (this.proposalEvidenceCount() === 0) {
      return 'Aucune preuve documentaire attachée : validation possible, mais à traiter comme connaissance expert non sourcée.';
    }
    return null;
  }

  canContinueFromReview(proposal?: CaptureProposal | null): boolean {
    if (!proposal || !this.proposalReportText()) return false;
    if (proposal.status === 'accepted') return true;
    return this.canProposalReview(proposal);
  }

  proposalReportText(): string {
    return (this.proposalReportDraft || '').trim();
  }

  proposalReportWordCount(): number {
    const text = this.proposalReportText();
    return text ? text.split(/\s+/).length : 0;
  }

  proposalReviewStateLabel(): string {
    const status = this.proposal()?.status || 'draft';
    return this.workflowStatusLabel(status);
  }

  onProposalReportChange(value: string): void {
    this.proposalReportDraft = value;
    this.proposalReportDirty.set(value.trim() !== this.proposalReportContent(this.proposal()).trim());
  }

  proposalPublishHint(proposal?: CaptureProposal | null): string | null {
    if (proposal?.status === 'published') return null;
    if (proposal?.status !== 'accepted') {
      return this.i18n.t('capture.publish.validate_first');
    }
    if (!this.canProposalPublish(proposal)) return this.i18n.t('capture.publish.no_ingest_permission');
    if (!this.effectivePublicationDestination()) return this.i18n.t('capture.publish.destination_required');
    return null;
  }

  canPublishProposal(proposal?: CaptureProposal | null): boolean {
    return Boolean(proposal) && !this.proposalPublishHint(proposal);
  }

  publicationCategoryLabel(): string {
    return this.publicationCategoryOptions.find((option) => option.id === this.publicationCategory)?.label || 'Autre';
  }

  publicationDestinationLabel(): string {
    return this.publicationDestinationSuggestion() || 'Destination à renseigner';
  }

  effectivePublicationDestination(): string {
    if (this.publicationDestinationCustom()) return this.publicationDestination.trim();
    return this.publicationDestination.trim() || this.publicationDestinationSuggestion() || '';
  }

  /** Options for the destination dropdown: workspace KB collections plus the
   *  currently suggested/selected value when it is not part of the list. */
  publicationDestinationOptions(): string[] {
    const options = new Set<string>(this.knowledgeCollections());
    const suggestion = this.publicationDestinationSuggestion();
    if (suggestion) options.add(suggestion);
    const current = this.publicationDestination.trim();
    if (current && !this.publicationDestinationCustom()) options.add(current);
    return [...options].sort((a, b) => a.localeCompare(b));
  }

  publicationDestinationChoice(): string {
    if (this.publicationDestinationCustom()) return '__custom__';
    return this.effectivePublicationDestination();
  }

  onPublicationDestinationChoice(value: string): void {
    if (value === '__custom__') {
      this.publicationDestinationCustom.set(true);
      this.publicationDestination = '';
      return;
    }
    this.publicationDestinationCustom.set(false);
    this.publicationDestination = String(value || '').trim();
  }

  /** Digest of the fiche: every top-level section title of the report. */
  publicationSectionTitles(): string[] {
    const cards = this.reportFiche();
    if (cards.length) return cards.map((card) => card.title);
    const titles: string[] = [];
    for (const line of this.proposalReportText().split('\n')) {
      const match = /^##\s+(.+)$/.exec(line.trim());
      if (match) titles.push(match[1].trim());
    }
    return titles;
  }

  captureExpertLabel(): string {
    const session = this.session();
    return session?.created_by_label || session?.created_by_user_id?.slice(0, 8) || '—';
  }

  private publicationDestinationSuggestion(): string | null {
    const context = this.selectedContext();
    const environment = (context?.environment_state || {}) as Record<string, unknown>;
    const candidate =
      environment['collection'] ||
      environment['collection_name'] ||
      environment['collection_slug'] ||
      context?.name ||
      null;
    const value = typeof candidate === 'string' ? candidate.trim() : '';
    return value || null;
  }

  publicationFinalTitleLabel(): string {
    return this.proposal()?.proposal?.title || this.session()?.title || 'Rapport de capture';
  }

  effectivePublicationFinalTitle(): string {
    return this.publicationFinalTitle.trim() || this.publicationFinalTitleLabel();
  }

  publicationDestinationDisplay(slug?: string | null): string {
    const value = String(slug || this.effectivePublicationDestination() || '').trim();
    if (!value) return this.i18n.t('capture.publish.destination_required');
    const context = this.selectedContext();
    const environment = (context?.environment_state || {}) as Record<string, unknown>;
    const candidates = [
      context?.name,
      environment['collection_label'],
      environment['collection_name'],
    ];
    for (const candidate of candidates) {
      const label = typeof candidate === 'string' ? candidate.trim() : '';
      if (!label) continue;
      const normalized = label.toLowerCase().replace(/[\s_]+/g, '-');
      if (normalized === value.toLowerCase() || label.toLowerCase() === value.toLowerCase()) {
        return label;
      }
    }
    return value.replace(/-/g, ' ');
  }

  publicationDocumentUrl(result?: CapturePublicationResult | null): string | null {
    const urls = result?.export_urls || this.proposal()?.proposal?.publication?.export_urls;
    const raw = urls?.raw_url || urls?.download_url;
    return raw ? raw : null;
  }

  isAuthor(session?: CaptureSession | null): boolean {
    return this.permissions.isAuthor({ owner_user_id: session?.created_by_user_id || null });
  }

  iamRoleBanner(): string | null {
    if (!this.permissions.matrix()) return null;
    if (this.permissions.isReviewerOrAdmin()) return `IAM : ${this.permissions.roleLabel()} peut relire les rapports du workspace.`;
    if (this.canCaptureCreate()) return `IAM : ${this.permissions.roleLabel()} peut capturer ses propres sessions.`;
    return `IAM : ${this.permissions.roleLabel()} dispose d’un accès limité à la capture.`;
  }

  selectedContext(): ContextOption | null {
    return this.contexts().find((ctx) => ctx.id === this.contextId) || null;
  }

  onContextChange(contextId: string): void {
    const ctx = this.contexts().find((item) => item.id === contextId);
    this.zoom.setCurrentContext(ctx?.id || null, ctx?.name || null);
    const collection = ctx?.environment_state?.collection || ctx?.data_refs?.[0] || '';
    if (collection) {
      this.selectedKnowledgeCollection = collection;
      this.newContextName = this.contextNameForCollection(collection);
    }
  }

  onKnowledgeCollectionChange(collection: string): void {
    this.contextCreationNotice.set(null);
    if (!collection) {
      this.newContextName = '';
      this.lastSuggestedContextName = '';
      return;
    }
    const suggestion = this.contextNameForCollection(collection);
    if (!this.newContextName.trim() || this.newContextName === this.lastSuggestedContextName) {
      this.newContextName = suggestion;
    }
    this.lastSuggestedContextName = suggestion;
  }

  createContextFromCollection(): void {
    const collection = this.selectedKnowledgeCollection.trim();
    if (!collection || this.creatingContext()) return;
    const name = this.newContextName.trim() || this.contextNameForCollection(collection);
    this.creatingContext.set(true);
    this.contextCreationNotice.set(null);
    this.api
      .post<ContextOption>('/contexts', {
        name,
        data_refs: [collection],
        environment_state: { collection },
        business_constraints: { source: 'knowledge_capture_prep' },
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (ctx) => {
          this.contexts.set([ctx, ...this.contexts().filter((item) => item.id !== ctx.id)]);
          this.contextId = ctx.id;
          this.newContextId.set(ctx.id);
          this.zoom.setCurrentContext(ctx.id, ctx.name);
          this.contextCreationNotice.set({
            tone: 'success',
            text: `Le contexte "${ctx.name}" est maintenant rattaché à ${collection}.`,
          });
          this.lastSuggestedContextName = ctx.name;
          this.creatingContext.set(false);
        },
        error: () => {
          this.contextCreationNotice.set({
            tone: 'error',
            text: 'Création du contexte impossible. Vérifiez l’accès workspace, puis réessayez.',
          });
          this.creatingContext.set(false);
        },
      });
  }

  contextCreationNoticeClass(tone: ContextCreationNotice['tone']): string {
    const base = 'text-xs rounded border px-3 py-2';
    if (tone === 'success') return `${base} bg-emerald-500/10 border-emerald-400/20 text-emerald-200`;
    if (tone === 'error') return `${base} bg-red-500/10 border-red-400/20 text-red-200`;
    return `${base} bg-white/5 border-white/10 text-gray-300`;
  }

  private loadKnowledgeCollections(): void {
    this.loadingKnowledgeCollections.set(true);
    this.api
      .get<{ collections: string[] }>('/documents/collections')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (payload) => {
          const collections = [...(payload?.collections || [])].sort((a, b) => a.localeCompare(b));
          this.knowledgeCollections.set(collections);
          const currentCollection = this.selectedContext()?.environment_state?.collection || this.selectedContext()?.data_refs?.[0] || '';
          if (currentCollection) {
            this.selectedKnowledgeCollection = currentCollection;
            this.newContextName = this.contextNameForCollection(currentCollection);
            this.lastSuggestedContextName = this.newContextName;
          }
          this.loadingKnowledgeCollections.set(false);
        },
        error: () => {
          this.knowledgeCollections.set([]);
          this.contextCreationNotice.set({
            tone: 'error',
            text: 'Les collections documentaires n’ont pas pu être chargées.',
          });
          this.loadingKnowledgeCollections.set(false);
        },
      });
  }

  private syncKnowledgeComposerFromContext(ctx: ContextOption): void {
    const collection = ctx.environment_state?.collection || ctx.data_refs?.[0] || '';
    if (!collection) return;
    this.selectedKnowledgeCollection = collection;
    this.newContextName = this.contextNameForCollection(collection);
    this.lastSuggestedContextName = this.newContextName;
  }

  private contextNameForCollection(collection: string): string {
    const clean = collection.trim();
    if (!clean) return '';
    return clean
      .replace(/[-_]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .replace(/\b\w/g, (char) => char.toUpperCase());
  }

  contextLabel(contextId?: string | null): string {
    if (!contextId) {
      return this.i18n.t('capture.prep.workspace_default_sources');
    }
    return this.contexts().find((ctx) => ctx.id === contextId)?.name || contextId.slice(0, 8);
  }

  questionText(question?: CaptureQuestion | null): string {
    return this.promptText(question?.prompt || question?.title || question?.question || '');
  }

  currentPromptText(): string | null {
    const session = this.session();
    if (session && this.isFreeConversationSession(session)) {
      return this.i18n.t('capture.session.free_prompt');
    }
    const question = this.currentQuestion();
    if (question) {
      return this.questionText(question);
    }
    const prompt = this.nextPrompt();
    if (prompt) return this.promptText(prompt);
    return this.activeOutlinePrompt();
  }

  private activeOutlinePrompt(): string | null {
    const session = this.session();
    if (!session) return null;
    const subtopicId = this.activeSubtopicId();
    const subtopics = this.planTopics(session).flatMap((topic) => topic.subtopics || []);
    const active = (subtopicId && subtopics.find((item) => item.id === subtopicId)) || subtopics[0];
    if (active) {
      const prompt = this.outlineItemPrompt(active);
      if (prompt) return prompt;
    }
    const firstTopic = this.planTopics(session)[0];
    return firstTopic ? this.outlineItemPrompt(firstTopic) : null;
  }

  promptText(text?: string | null): string {
    const clean = (text || '').trim();
    if (!clean) return '';
    return clean;
  }

  private captureObjectiveForPlan(): string {
    const clean = (this.objective || '').trim();
    if (clean && !this.isRuntimeCaptureObjective(clean)) {
      return clean;
    }
    const title = this.sessionTitle.trim();
    if (title) {
      return `Capturer les savoirs métier et retours d’expérience liés à : ${title}.`;
    }
    return this.defaultBusinessObjective();
  }

  private defaultBusinessObjective(): string {
    const expert = this.expertProfile.trim() || 'expert métier';
    return (
      `Capturer les décisions métier, exceptions terrain et critères de validation ` +
      `de l’expert (${expert}) au regard de ${this.knowledgeTargetPhrase()}.`
    );
  }

  private businessDecisionQuestion(): string {
    return (
      `Au regard de ${this.knowledgeTargetPhrase()}, quelle décision métier ou terrain ` +
      'reste difficile à retrouver dans la documentation, et comment l’expert la prend-il en pratique ?'
    );
  }

  private knowledgeTargetPhrase(): string {
    const sessionContextId = this.session()?.context_id || null;
    const ctx =
      this.selectedContext() ||
      this.contexts().find((item) => item.id === sessionContextId) ||
      null;
    const target = ctx?.environment_state?.collection || ctx?.name || '';
    return target ? `la base de connaissances « ${target} »` : 'la base de connaissances connectée';
  }

  private isRuntimeCapturePrompt(text: string): boolean {
    const lower = text.toLowerCase();
    return (
      this.isRuntimeCaptureObjective(text) ||
      (
        lower.includes('pour l’objectif') &&
        lower.includes('quelle décision experte') &&
        lower.includes('documentation')
      )
    );
  }

  private isRuntimeCaptureObjective(text?: string | null): boolean {
    const lower = (text || '').toLowerCase();
    if (!lower) return false;
    return [
      'run guided voice-to-voice expert interviews',
      'voice-to-voice expert interviews',
      'retrieve live knowledge context',
      'hitl-reviewable knowledge update proposals',
      'knowledge update proposals',
      'guided session runtime',
    ].some((marker) => lower.includes(marker));
  }

  systemLabel(systemId?: string | null): string | null {
    if (!systemId) return null;
    return this.systems().find((system) => system.id === systemId)?.name || systemId.slice(0, 8);
  }

  private applySystemScope(system: SystemOption | null): void {
    if (!system || system.id !== this.systemId) return;
    this.systemScoped.set(true);
    const systemObjective = system.objective?.trim();
    if (systemObjective && !this.isRuntimeCaptureObjective(systemObjective)) {
      this.objective = systemObjective;
    } else if (this.isRuntimeCaptureObjective(this.objective)) {
      this.objective = this.defaultBusinessObjective();
    }
    if (system.context_id && (!this.contextId || this.systemScoped())) {
      this.contextId = system.context_id;
    }
    this.zoom.setCurrentSystem(system.id, system.name);
    if (system.context_id) {
      this.zoom.setCurrentContext(system.context_id, this.contextLabel(system.context_id));
    }
  }

  private pickDefaultContext(contexts: ContextOption[]): ContextOption | null {
    return (
      contexts.find((ctx) => Boolean(ctx.environment_state?.collection)) ||
      contexts.find((ctx) => (ctx.data_refs?.length || 0) > 0) ||
      contexts[0] ||
      null
    );
  }

  sendAnswer(session: CaptureSession): void {
    const text = this.answer.trim();
    if (!text) return;
    if (!this.canCaptureUpdate(session)) {
      this.setVoiceNotice('Votre rôle ne permet pas de modifier cette session de capture.', 'error');
      return;
    }
    this.voiceState.set('thinking');
    this.api
      .addCaptureTurn(session.id, {
        speaker: 'expert',
        text,
        question_id: this.selectedQuestionId(),
        client_turn_id: this.currentClientTurnId,
        retrieval_event_id: this.retrieval().event_id || null,
        interruption_of_event_id: this.interruptionOfEventId(),
        turn_kind: this.interruptionOfEventId() ? 'correction' : 'answer',
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((res) => {
        const typed = res as TurnResponse;
        this.session.set(typed.session);
        this.lastEvaluation.set(typed.evaluation || null);
        this.nextPrompt.set(typed.next_prompt || null);
        this.lastSystemPromptEventId.set(typed.system_prompt_event_id || null);
        if (typed.next_question_id) {
          this.selectedQuestionId.set(typed.next_question_id);
        }
        this.answer = '';
        this.currentClientTurnId = null;
        this.interruptionOfEventId.set(null);
        this.refreshEvents(typed.session.id);
        if (typed.next_prompt) {
          this.speak(this.promptText(typed.next_prompt));
        } else {
          this.voiceState.set('idle');
        }
      });
  }

  textEvents(): CaptureEvent[] {
    const priorities: Record<string, number> = {
      proposal_reviewed: 80,
      proposal_generated: 70,
      conversation_intent_detected: 60,
      transcript_amended: 50,
      expert_turn_finalized: 40,
      stt_final: 30,
      transcript_turn_recorded: 20,
    };
    const byKey = new Map<string, CaptureEvent>();
    this.events()
      .filter((event) => !this.isPlanPhaseTranscriptEvent(event))
      .filter((event) => priorities[event.event_type] && (
        Boolean(this.eventDisplayText(event)) ||
        event.event_type === 'proposal_generated' ||
        event.event_type === 'proposal_reviewed' ||
        this.isConversationBusinessDecision(event)
      ))
      .forEach((event) => {
        const key = this.eventLedgerKey(event);
        const current = byKey.get(key);
        if (!current || priorities[event.event_type] >= priorities[current.event_type]) {
          byKey.set(key, event);
        }
      });
    return Array.from(byKey.values()).sort((a, b) => a.sequence - b.sequence);
  }

  captureOutlineTitle(): string | null {
    const session = this.session();
    if (session && this.isFreeConversationSession(session)) return null;
    const question = this.currentQuestion();
    const title = (question?.title || '').trim();
    if (title) return title;
    const subtopicId = this.activeSubtopicId();
    if (session && subtopicId) {
      const subtopic = this.planTopics(session)
        .flatMap((topic) => topic.subtopics || [])
        .find((item) => item.id === subtopicId);
      if (subtopic?.title) return subtopic.title.trim();
    }
    return null;
  }

  capturePresentationPrompt(): string | null {
    return this.currentPromptText();
  }

  private eventOutlineTitle(event: CaptureEvent): string | undefined {
    const meta = event.metadata || {};
    const title = String(meta['subtopic_title'] || meta['topic_title'] || meta['path_label'] || '').trim();
    return title || undefined;
  }

  /**
   * Continuous capture transcript: committed expert speech is grouped into a
   * flowing paragraphs per active section (plan mode) or one global stream
   * (no-plan). VAD turns stay useful as capture units, but they only become a
   * visible paragraph break when the text itself looks like a real boundary.
   * The live partial can attach to the current paragraph tail.
   * No per-utterance bordered blocks, no successive re-correction display: we
   * rely on text.final as the single committed source. The only IA paroles
   * interleaved are timeline relances ("terminé ? continuer ?").
   */
  captureTranscriptRows(): Array<{
    key: string;
    kind: 'topic' | 'flow' | 'ia';
    text: string;
    liveText?: string;
    /** True once the in-progress tail has been finalised (text.final / refined). */
    liveCommitted?: boolean;
  }> {
    type ExpertTranscriptItem = {
      order: number;
      kind: 'expert';
      id: string;
      text: string;
      topic: string | undefined;
      round: string;
      endpointReason: string | null;
    };

    const expert: ExpertTranscriptItem[] = this.textEvents()
      .filter(
        (event) =>
          (event.speaker || '').toLowerCase() === 'expert' &&
          !this.isTrivialTranscriptSegment(this.eventDisplayText(event)),
      )
      .map((event) => ({
        order: event.sequence,
        kind: 'expert' as const,
        id: event.id,
        text: this.eventDisplayText(event).trim(),
        topic: this.eventOutlineTitle(event),
        // A "round" = one VAD speaking turn. It is a capture unit first; the
        // renderer decides below whether it is also a visible paragraph break.
        round:
          event.metadata?.['client_turn_id'] != null
            ? `turn:${event.metadata['client_turn_id']}`
            : `evt:${event.id}`,
        endpointReason: this.eventEndpointReason(event),
      }));
    const annotations = this.relanceAnnotations()
      .filter((item) => !this.isTrivialTranscriptSegment(item.text))
      .map((item) => ({
        order: item.order,
        kind: 'ia' as const,
        id: item.id,
        text: item.text.trim(),
        topic: undefined as string | undefined,
        round: undefined as string | undefined,
        endpointReason: null,
      }));
    const ordered = [...expert, ...annotations].sort((a, b) => a.order - b.order);

    const rows: Array<{
      key: string;
      kind: 'topic' | 'flow' | 'ia';
      text: string;
      liveText?: string;
      liveCommitted?: boolean;
    }> = [];
    let lastTopic: string | undefined;
    let lastExpertTextKey = '';
    // Accumulated flowing paragraph. Multiple VAD turns may remain in the same
    // paragraph when the cut is technical rather than linguistic.
    let buffer: string[] = [];
    let bufferKey = '';
    let lastRound: string | undefined;
    let lastExpertItem: ExpertTranscriptItem | null = null;
    const flushBuffer = () => {
      if (!buffer.length) return;
      rows.push({ key: `flow-${bufferKey}`, kind: 'flow', text: buffer.join(' ') });
      buffer = [];
      bufferKey = '';
    };

    for (const item of ordered) {
      if (item.kind === 'expert') {
        if (item.topic && item.topic !== lastTopic) {
          flushBuffer();
          rows.push({ key: `topic-${item.id}`, kind: 'topic', text: item.topic });
          lastTopic = item.topic;
          lastRound = undefined;
          lastExpertItem = null;
        }
        const key = this.transcriptTextKey(item.text);
        // Drop exact successive duplicates (re-emitted finals).
        if (key && key !== lastExpertTextKey) {
          const roundChanged = item.round !== lastRound;
          if (
            buffer.length &&
            roundChanged &&
            this.shouldStartNewTranscriptParagraph(lastExpertItem, item)
          ) {
            flushBuffer();
          }
          if (!buffer.length) bufferKey = item.id;
          buffer.push(item.text);
          lastExpertTextKey = key;
          lastRound = item.round;
          lastExpertItem = item;
        }
      } else {
        // Timeline relance: close the running paragraph then show the IA line.
        flushBuffer();
        lastExpertTextKey = '';
        lastRound = undefined;
        lastExpertItem = null;
        rows.push({ key: `ia-${item.id}`, kind: 'ia', text: item.text });
      }
    }

    flushBuffer();

    // Finished turns whose persisted event has not landed yet: keep them
    // rendered as committed paragraphs (stable `live-` keys reuse the DOM node
    // of the live row they come from) so a new turn NEVER makes the previous
    // paragraph vanish while waiting for the event refresh.
    const committedKeys = new Set(expert.map((item) => this.transcriptTextKey(item.text)));
    const appendLiveRow = (id: string, text: string, liveCommitted: boolean) => {
      const lastRow = rows[rows.length - 1];
      if (
        lastRow?.kind === 'flow' &&
        !lastRow.liveText &&
        this.isTranscriptContinuation(lastRow.text, text)
      ) {
        lastRow.liveText = text;
        lastRow.liveCommitted = liveCommitted;
        return;
      }
      rows.push({
        key: `live-${id}`,
        kind: 'flow',
        text: '',
        liveText: text,
        liveCommitted,
      });
    };
    for (const pending of this.pendingLiveCommits()) {
      const key = this.transcriptTextKey(pending.text);
      if (committedKeys.has(key) || key === lastExpertTextKey) continue;
      appendLiveRow(pending.id, pending.text, true);
      lastExpertTextKey = key;
    }

    const live = this.liveTranscript();
    const liveText = live ? live.text.trim() : '';
    if (liveText && !this.isTrivialTranscriptSegment(liveText)) {
      const liveKey = this.transcriptTextKey(liveText);
      const isDuplicate =
        live!.status !== 'live' && (liveKey === lastExpertTextKey || committedKeys.has(liveKey));
      if (!isDuplicate) {
        // When the live tail is clearly a continuation, keep the subtitle feel by
        // attaching it to the previous paragraph instead of forcing a new line.
        appendLiveRow(live!.id, liveText, live!.status !== 'live');
      }
    }
    return rows;
  }

  /** Filter out empty / trivial segments (single punctuation, lone filler tokens). */
  private isTrivialTranscriptSegment(text: string | null | undefined): boolean {
    const clean = (text || '').replace(/\s+/g, ' ').trim();
    if (!clean) return true;
    const alphanumeric = clean.replace(/[^\p{L}\p{N}]/gu, '');
    return alphanumeric.length < 2;
  }

  private transcriptTextKey(text: string): string {
    return text.replace(/\s+/g, ' ').trim().toLowerCase();
  }

  private eventEndpointReason(event: CaptureEvent): string | null {
    const meta = event.metadata || {};
    const latency = meta['latency_ms'];
    const latencyObject: Record<string, any> =
      latency && typeof latency === 'object' && !Array.isArray(latency) ? latency : {};
    const value =
      meta['endpoint_reason'] ||
      latencyObject['endpoint_reason'] ||
      meta['reason'] ||
      latencyObject['reason'];
    const reason = String(value || '').trim().toLowerCase();
    return reason || null;
  }

  private shouldStartNewTranscriptParagraph(
    previous: { text: string } | null,
    current: { text: string; endpointReason?: string | null },
  ): boolean {
    if (!previous) return false;
    const reason = (current.endpointReason || '').toLowerCase();
    if (['manual', 'stop', 'max_turn', 'no_speech', 'error'].includes(reason)) return true;
    return !this.isTranscriptContinuation(previous.text, current.text);
  }

  private isTranscriptContinuation(previousText: string, nextText: string): boolean {
    const previous = previousText.replace(/\s+/g, ' ').trim();
    const next = nextText.replace(/\s+/g, ' ').trim();
    if (!previous || !next) return false;
    if (/^(?:\.{2,}|…|[,;:)\]\}]|\p{Ll})/u.test(next)) return true;
    if (/[,:;]$/.test(previous)) return true;
    if (/(?:\.{2,}|…)["')\]\}]?$/.test(previous)) return true;
    if (!/[.!?]["')\]\}]?$/.test(previous)) return true;
    return false;
  }

  /**
   * When a NEW live turn starts (different id), the previous live paragraph is
   * promoted to the pending-commit list instead of vanishing: its persisted
   * expert event arrives asynchronously, and dropping the text in between
   * caused the "previous paragraph disappears then comes back" flicker.
   */
  private promoteLiveToPending(nextId: string): void {
    const live = this.liveTranscript();
    if (!live || live.id === nextId) return;
    const text = live.text.trim();
    if (!text || this.isTrivialTranscriptSegment(text)) return;
    this.pendingLiveCommits.update((rows) =>
      [...rows.filter((row) => row.id !== live.id), { id: live.id, text }].slice(-4),
    );
  }

  /** Drop pending commits whose persisted expert event has landed. */
  private prunePendingLiveCommits(events: CaptureEvent[]): void {
    if (!this.pendingLiveCommits().length) return;
    const committedKeys = new Set(
      events
        .filter((event) => (event.speaker || '').toLowerCase() === 'expert')
        .map((event) => this.transcriptTextKey(this.eventDisplayText(event))),
    );
    this.pendingLiveCommits.update((rows) =>
      rows.filter((row) => !committedKeys.has(this.transcriptTextKey(row.text))),
    );
  }

  /** A turn that becomes live again must leave the pending-commit list. */
  private reclaimPendingLiveCommit(id: string): void {
    if (!this.pendingLiveCommits().length) return;
    this.pendingLiveCommits.update((rows) => rows.filter((row) => row.id !== id));
  }

  private setLivePartial(id: string, text: string): void {
    const clean = text.trim();
    if (!clean) return;
    this.promoteLiveToPending(id);
    this.reclaimPendingLiveCommit(id);
    this.liveTranscript.set({ id, text: clean, status: 'live' });
  }

  private setLiveImproved(id: string, text: string, reframed = false): void {
    const clean = text.trim();
    if (!clean) return;
    this.promoteLiveToPending(id);
    this.reclaimPendingLiveCommit(id);
    this.liveTranscript.set({ id, text: clean, status: 'refined', reframed });
  }

  /**
   * Consume the passive assist payload that may ride on any streaming event:
   * the oracle's own working questions, its live retrieval, and non-blocking
   * suggestions. Nothing here ever interrupts the expert or gates input.
   */
  private ingestOraclePayload(payload: Record<string, any>): void {
    if (!payload || typeof payload !== 'object') return;
    // The gateway emits open_questions / retrieval / suggestions at the TOP LEVEL of
    // conversation.step and evaluation.delta. Older shapes nested them under an
    // `oracle` object, so we accept either and prefer the top-level keys.
    const oracle = payload['oracle'] && typeof payload['oracle'] === 'object' ? payload['oracle'] : {};
    const openQuestions = Array.isArray(payload['open_questions'])
      ? payload['open_questions']
      : Array.isArray(oracle['open_questions'])
        ? oracle['open_questions']
        : null;
    if (openQuestions) {
      const questions = (openQuestions as any[])
        .filter((q) => q && typeof q === 'object')
        .map((q) => ({
          id: q['id'] != null ? String(q['id']) : undefined,
          text: String(q['text'] || '').trim(),
          topic_id: q['topic_id'] != null ? String(q['topic_id']) : undefined,
          priority: typeof q['priority'] === 'number' ? q['priority'] : Number(q['priority']) || undefined,
          status: q['status'] != null ? String(q['status']) : undefined,
        }))
        .filter((q) => q.text);
      // Backend sends these already sorted desc by priority; keep as received.
      this.oracleOpenQuestions.set(questions);
    }
    const retrieval =
      payload['retrieval'] && typeof payload['retrieval'] === 'object'
        ? payload['retrieval']
        : oracle['retrieval'] && typeof oracle['retrieval'] === 'object'
          ? oracle['retrieval']
          : null;
    if (retrieval && Array.isArray(retrieval['chunks'])) {
      this.applyLiveRetrieval(retrieval);
    }
    const suggestions = Array.isArray(payload['suggestions'])
      ? payload['suggestions']
      : Array.isArray(oracle['suggestions'])
        ? oracle['suggestions']
        : null;
    if (suggestions) {
      this.applySuggestions(suggestions as any[]);
    }
  }

  /** Normalise oracle live-retrieval chunks into the existing retrieval shape so
   * the DocumentPreview affordance (previewRetrievalChunk) keeps working. */
  private applyLiveRetrieval(retrieval: Record<string, any>): void {
    const raw = Array.isArray(retrieval['chunks']) ? retrieval['chunks'] : [];
    if (!raw.length) return;
    const chunks: string[] = [];
    const scores: number[] = [];
    const metadatas: Record<string, any>[] = [];
    for (const item of raw) {
      if (typeof item === 'string') {
        chunks.push(item);
        scores.push(0);
        metadatas.push({});
        continue;
      }
      const obj = (item || {}) as Record<string, any>;
      const meta = (obj['metadata'] as Record<string, any>) || {};
      chunks.push(String(obj['text'] ?? obj['content'] ?? obj['chunk'] ?? obj['excerpt'] ?? '').trim());
      scores.push(typeof obj['score'] === 'number' ? obj['score'] : Number(obj['score']) || 0);
      metadatas.push({
        ...meta,
        document_id: obj['document_id'] ?? obj['source_id'] ?? meta['document_id'],
        source_id: obj['source_id'] ?? meta['source_id'],
        collection: obj['collection'] ?? obj['collection_name'] ?? meta['collection'],
        collection_name: obj['collection_name'] ?? obj['collection'] ?? meta['collection_name'],
        title: obj['title'] ?? obj['filename'] ?? obj['source'] ?? meta['title'],
        filename: obj['filename'] ?? meta['filename'],
      });
    }
    this.retrieval.set({
      ...this.retrieval(),
      status: 'ready',
      chunks,
      scores,
      metadatas,
      collection_name:
        String(retrieval['collection_name'] || retrieval['collection'] || '') || this.retrieval().collection_name,
    });
  }

  private applySuggestions(items: any[]): void {
    const next: CaptureLiveSuggestion[] = [];
    items.forEach((raw, index) => {
      if (!raw || typeof raw !== 'object') return;
      const text = String(raw['text'] || '').trim();
      if (!text) return;
      const kind = String(raw['kind'] || 'suggestion');
      const id = String(raw['id'] || `${kind}:${text}`);
      if (this.dismissedSuggestionKeys.has(id)) return;
      next.push({ id, kind, text });
    });
    this.captureSuggestions.set(next);
  }

  visibleSuggestions(): CaptureLiveSuggestion[] {
    return this.captureSuggestions().filter((s) => !this.dismissedSuggestionKeys.has(s.id));
  }

  dismissSuggestion(id: string): void {
    this.dismissedSuggestionKeys.add(id);
    this.captureSuggestions.update((current) => current.filter((s) => s.id !== id));
  }

  suggestionKindLabel(kind: string): string {
    switch (kind) {
      case 'topic_close':
        return 'Sujet bientôt couvert';
      case 'gap_question':
        return 'Angle peu abordé';
      case 'contradiction':
        return 'Possible contradiction';
      case 'relance':
        return 'Relance';
      default:
        return 'Suggestion';
    }
  }

  /** Read-only: oracle working questions, kept in received (priority-desc) order. */
  oracleQuestionTopicLabel(question: OracleOpenQuestion): string | null {
    const topicId = (question.topic_id || '').trim();
    if (!topicId) return null;
    const session = this.session();
    if (!session) return null;
    for (const topic of this.planTopics(session)) {
      if (topic.id === topicId) return topic.title || topicId;
      const sub = (topic.subtopics || []).find((item) => item.id === topicId);
      if (sub) return sub.title || topicId;
    }
    return topicId;
  }

  oracleQuestionPriorityLabel(question: OracleOpenQuestion): string | null {
    const priority = question.priority;
    if (priority == null || Number.isNaN(priority)) return null;
    if (priority >= 0.66 || priority >= 3) return 'Priorité haute';
    if (priority >= 0.33 || priority >= 2) return 'Priorité moyenne';
    return 'Priorité basse';
  }

  oracleQuestionPriorityClass(question: OracleOpenQuestion): string {
    const priority = question.priority ?? 0;
    if (priority >= 0.66 || priority >= 3) {
      return 'inline-block h-1.5 w-1.5 rounded-full bg-rose-400/80';
    }
    if (priority >= 0.33 || priority >= 2) {
      return 'inline-block h-1.5 w-1.5 rounded-full bg-amber-400/80';
    }
    return 'inline-block h-1.5 w-1.5 rounded-full bg-brand-300/70';
  }

  answerOracleQuestion(question: OracleOpenQuestion): void {
    this.markOracleQuestion(question, 'answered');
    this.persistOracleQuestionStatuses([{ question, status: 'answered' }]);
    const text = (question.text || '').trim();
    if (text) {
      this.answer = this.answer.trim() ? `${this.answer.trim()}\n\n${text}` : text;
    }
  }

  dismissOracleQuestion(question: OracleOpenQuestion): void {
    this.markOracleQuestion(question, 'dismissed');
    this.persistOracleQuestionStatuses([{ question, status: 'dismissed' }]);
  }

  deferOracleQuestion(question: OracleOpenQuestion): void {
    this.markOracleQuestion(question, 'deferred');
    this.persistOracleQuestionStatuses([{ question, status: 'deferred' }]);
  }

  deferAllOracleQuestions(): void {
    const active = this.activeOracleQuestions();
    if (!active.length) return;
    this.oracleOpenQuestions.update((questions) =>
      questions.map((question) => {
        const key = question.id || question.text || '';
        return active.some((item) => (item.id || item.text || '') === key)
          ? { ...question, status: 'deferred' }
          : question;
      }),
    );
    this.persistOracleQuestionStatuses(active.map((question) => ({ question, status: 'deferred' })));
  }

  muteOracleQuestions(): void {
    const session = this.session();
    if (!session) return;
    this.api
      .patchCaptureSessionFlags(session.id, { suppress_oracle_questions: true })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((payload) => this.session.set(payload as CaptureSession));
  }

  unmuteOracleQuestions(): void {
    const session = this.session();
    if (!session) return;
    this.api
      .patchCaptureSessionFlags(session.id, { suppress_oracle_questions: false })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((payload) => this.session.set(payload as CaptureSession));
  }

  private openOracleQuestionsForAction(questions: OracleOpenQuestion[] = this.oracleOpenQuestions()): OracleOpenQuestion[] {
    return questions.filter((question) => !['answered', 'dismissed', 'deferred'].includes(question.status || ''));
  }

  private markOracleQuestion(target: OracleOpenQuestion, status: OracleQuestionStatus): void {
    const targetKey = target.id || target.text || '';
    this.oracleOpenQuestions.update((questions) =>
      questions.map((question) => {
        const key = question.id || question.text || '';
        return key === targetKey ? { ...question, status } : question;
      }),
    );
  }

  private persistOracleQuestionStatuses(
    items: Array<{ question: OracleOpenQuestion; status: OracleQuestionStatus }>,
  ): void {
    const session = this.session();
    if (!session || !items.length) return;
    this.api
      .patchCaptureOracleQuestions(session.id, {
        items: items.map(({ question, status }) => ({
          question_id: question.id || null,
          question_text: question.text || null,
          status,
        })),
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (payload) => {
          const typed = payload as { session?: CaptureSession; open_questions?: OracleOpenQuestion[] };
          if (typed.session) {
            this.session.set(typed.session);
          }
          if (Array.isArray(typed.open_questions)) {
            this.oracleOpenQuestions.set(
              typed.open_questions
                .map((question) => ({
                  id: question.id != null ? String(question.id) : undefined,
                  text: String(question.text || '').trim(),
                  topic_id: question.topic_id != null ? String(question.topic_id) : undefined,
                  priority:
                    typeof question.priority === 'number'
                      ? question.priority
                      : Number(question.priority) || undefined,
                  status: question.status != null ? String(question.status) : undefined,
                }))
                .filter((question) => question.text),
            );
          }
          this.refreshQualityBacklog(session.id);
        },
      });
  }

  private pushRelanceAnnotation(relance?: CaptureRelance | null): void {
    if (!relance || !relance.kind || !relance.text || !relance.text.trim()) return;
    const order = (this.events().at(-1)?.sequence ?? 0) + 0.5;
    const id = `${relance.kind}-${Date.now()}`;
    this.relanceAnnotations.update((current) => [
      ...current,
      { id, order, text: relance.text!.trim(), kind: relance.kind },
    ]);
  }

  relanceAnnotationLabel(kind: RelanceKind): string {
    if (kind === 'topic_close') return 'IA · transition';
    if (kind === 'gap_question') return 'IA · précision';
    if (kind === 'contradiction') return 'IA · à vérifier';
    return 'IA';
  }

  refreshEvents(sessionId: string): void {
    // Incremental refresh: once a session is loaded, ask only for the delta
    // (events with sequence > last seen) and merge, instead of reloading the
    // full — and ever-growing — event list on every call.
    const incremental = this.eventsSessionId === sessionId && this.lastEventSequence !== null;
    const afterSequence = incremental ? this.lastEventSequence ?? undefined : undefined;
    this.api
      .listCaptureEvents(sessionId, afterSequence, true)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((payload) => {
        const incoming = (payload as { events?: CaptureEvent[] }).events || [];
        const merged = incremental ? this.mergeCaptureEvents(this.events(), incoming) : incoming;
        this.events.set(merged);
        this.eventsSessionId = merged.length ? sessionId : null;
        this.lastEventSequence = merged.length
          ? merged.reduce((max, event) => Math.max(max, event.sequence ?? 0), 0)
          : null;
        this.prunePendingLiveCommits(merged);
      });
  }

  private mergeCaptureEvents(existing: CaptureEvent[], incoming: CaptureEvent[]): CaptureEvent[] {
    if (!incoming.length) return existing;
    const byId = new Map<string, CaptureEvent>();
    for (const event of existing) byId.set(event.id, event);
    for (const event of incoming) byId.set(event.id, event);
    return Array.from(byId.values()).sort((a, b) => a.sequence - b.sequence);
  }

  voiceStateLabel(): string {
    const labels: Record<Voice2VoiceState, string> = {
      idle: 'capture.voice.ready',
      listening: 'capture.voice.listening',
      partial_transcribing: 'capture.voice.transcription',
      retrieving: 'capture.voice.retrieving',
      oracle_updating: 'capture.voice.oracle_updating',
      thinking: 'capture.voice.thinking',
      speaking: 'capture.voice.speaking',
      interrupted: 'capture.voice.interrupted',
    };
    return this.i18n.t(labels[this.voiceState()]);
  }

  retrievalLabel(): string {
    const rr = this.retrieval();
    if (rr.chunks.length) {
      return this.i18n.t(
        rr.chunks.length === 1 ? 'capture.retrieval.useful_one' : 'capture.retrieval.useful_many',
        { count: rr.chunks.length },
      );
    }
    if (rr.status === 'searching') {
      return this.i18n.t('capture.retrieval.searching');
    }
    if (rr.status === 'ready' || rr.status === 'completed') return this.i18n.t('capture.retrieval.none');
    if (rr.status === 'late') return this.i18n.t('capture.retrieval.late');
    if (rr.status === 'timeout') return this.i18n.t('capture.retrieval.timeout');
    if (rr.status === 'error') return this.i18n.t('capture.retrieval.error');
    return this.i18n.t('capture.retrieval.waiting');
  }

  onAnswerDraftChange(): void {
    const session = this.session();
    if (!session) return;
    this.maybePrefetchRetrieval(session, this.answer);
  }

  planQuestions(session?: CaptureSession | null): CaptureQuestion[] {
    const plan = session?.plan;
    if (!plan) return [];
    if (plan.topics?.length) {
      const questions: CaptureQuestion[] = [];
      for (const topic of plan.topics) {
        const subtopics = topic.subtopics || [];
        if (!subtopics.length) {
          const prompt = this.outlineItemPrompt(topic) || `Présentez ce que vous savez sur ${topic.title}.`;
          questions.push({
            id: `${topic.id}-present`,
            question: prompt,
            title: topic.title,
            topic_id: topic.id,
            subtopic_id: undefined,
            path_label: topic.title,
            estimated_minutes: topic.estimated_minutes || 3,
          });
          continue;
        }
        const topicIsOutline = !subtopics.some((subtopic) => (subtopic.questions || []).length);
        if (topicIsOutline) {
          const prompt = this.outlineItemPrompt(topic) || `Présentez ce que vous savez sur ${topic.title}.`;
          questions.push({
            id: `${topic.id}-overview`,
            question: prompt,
            title: topic.title,
            topic_id: topic.id,
            subtopic_id: undefined,
            path_label: topic.title,
            estimated_minutes: topic.estimated_minutes || 3,
          });
        }
        for (const subtopic of subtopics) {
          const pathLabel = `${topic.title} / ${subtopic.title}`;
          const subtopicQuestions = subtopic.questions || [];
          if (subtopicQuestions.length) {
            questions.push(
              ...subtopicQuestions.map((question) => ({
                ...question,
                topic_id: question.topic_id || topic.id,
                subtopic_id: question.subtopic_id || subtopic.id,
                path_label: question.path_label || pathLabel,
              })),
            );
          } else if (topicIsOutline) {
            const prompt = this.outlineItemPrompt(subtopic) || `Présentez ce que vous savez sur ${subtopic.title}.`;
            questions.push({
              id: `${subtopic.id}-present`,
              question: prompt,
              title: subtopic.title,
              topic_id: topic.id,
              subtopic_id: subtopic.id,
              path_label: pathLabel,
              estimated_minutes: 3,
            });
          }
        }
      }
      return questions;
    }
    return plan.questions || [];
  }

  planTopics(session: CaptureSession): CaptureTopic[] {
    if (session.plan.topics?.length) return session.plan.topics;
    const flat = session.plan.questions || [];
    if (!flat.length) return [];
    return flat.map((question, index) => ({
      id: question.topic_id || `outline-${index + 1}`,
      title: this.outlineItemLabel(question) || `Point ${index + 1}`,
      prompt: question.prompt || undefined,
      subtopics: [],
    }));
  }

  planOutlineText(session: CaptureSession): string {
    const draft = this.planOutlineDrafts.get(session.id);
    if (draft !== undefined) return draft;
    const text = this.serializePlanOutline(this.planTopics(session));
    this.planOutlineDrafts.set(session.id, text);
    return text;
  }

  updatePlanOutlineText(session: CaptureSession, text: string): void {
    this.planOutlineDrafts.set(session.id, text);
    const topics = this.parsePlanOutline(text, session.plan.topics || []);
    session.plan.topics = topics;
    session.plan.questions = [];
    this.session.set({ ...session, plan: { ...session.plan, topics, questions: [] } });
    this.touchPlanDraft();
  }

  onPlanOutlineKeydown(event: KeyboardEvent, session: CaptureSession): void {
    const textarea = event.target as HTMLTextAreaElement | null;
    if (!textarea) return;
    if (event.key === 'Tab') {
      event.preventDefault();
      this.applyPlanOutlineIndentShortcut(session, textarea, event.shiftKey ? 'outdent' : 'indent');
      return;
    }
    if (event.key === 'Enter' && !event.shiftKey && !event.metaKey && !event.ctrlKey && !event.altKey) {
      event.preventDefault();
      this.applyPlanOutlineEnterShortcut(session, textarea);
    }
  }

  applyPlanOutlineFormatFrom(editor: 'plan' | 'plan_build', session: CaptureSession, action: PlanOutlineFormatAction): void {
    const textarea =
      editor === 'plan'
        ? this.planOutlineEditor?.nativeElement
        : this.planBuildOutlineEditor?.nativeElement;
    if (!textarea) return;
    this.applyPlanOutlineFormat(session, textarea, action);
  }

  applyPlanOutlineFormat(session: CaptureSession, textarea: HTMLTextAreaElement, action: PlanOutlineFormatAction): void {
    if (!this.canEditPlan(session)) return;
    const original = textarea.value || this.planOutlineText(session);
    const lines = original.split('\n');
    const range = this.selectedPlanOutlineLines(original, textarea.selectionStart || 0, textarea.selectionEnd || 0);
    let nextLines = [...lines];
    let nextStartLine = range.startLine;
    let nextEndLine = range.endLine;
    const count = range.endLine - range.startLine + 1;

    if (action === 'renumber') {
      nextLines = this.renumberPlanOutlineLines(nextLines);
    } else if (action === 'move_up') {
      if (range.startLine === 0) return;
      const selected = nextLines.splice(range.startLine, count);
      nextLines.splice(range.startLine - 1, 0, ...selected);
      nextStartLine -= 1;
      nextEndLine -= 1;
    } else if (action === 'move_down') {
      if (range.endLine >= nextLines.length - 1) return;
      const selected = nextLines.splice(range.startLine, count);
      nextLines.splice(range.startLine + 1, 0, ...selected);
      nextStartLine += 1;
      nextEndLine += 1;
    } else {
      nextLines = nextLines.map((line, index) => {
        if (index < range.startLine || index > range.endLine) return line;
        return this.formatPlanOutlineLine(line, action, index - range.startLine + 1);
      });
      if (action === 'indent' || action === 'outdent') {
        nextLines = this.renumberPlanOutlineLines(nextLines);
      }
    }

    const nextText = nextLines.join('\n');
    textarea.value = nextText;
    this.updatePlanOutlineText(session, nextText);
    const selectionStart = this.planOutlineLineOffset(nextLines, nextStartLine);
    const selectionEnd = this.planOutlineLineOffset(nextLines, nextEndLine) + (nextLines[nextEndLine]?.length || 0);
    requestAnimationFrame(() => {
      textarea.focus();
      textarea.setSelectionRange(selectionStart, selectionEnd);
    });
  }

  private applyPlanOutlineIndentShortcut(session: CaptureSession, textarea: HTMLTextAreaElement, action: 'indent' | 'outdent'): void {
    if (!this.canEditPlan(session)) return;
    const original = textarea.value || this.planOutlineText(session);
    const start = textarea.selectionStart || 0;
    const end = textarea.selectionEnd || start;
    const range = this.selectedPlanOutlineLines(original, start, end);
    const lines = original.split('\n');
    const offsets = lines.map((_, index) => this.planOutlineLineOffset(lines, index));
    let nextStart = start;
    let nextEnd = end;

    for (let index = range.startLine; index <= range.endLine; index += 1) {
      const current = lines[index] || '';
      const next = this.formatPlanOutlineLine(current, action, 1);
      const delta = next.length - current.length;
      lines[index] = next;
      const lineStart = offsets[index] || 0;

      if (index === range.startLine && (start > lineStart || start === end)) {
        nextStart += delta;
      }
      if (index < range.endLine || end > lineStart || (start === end && end === lineStart)) {
        nextEnd += delta;
      }
    }

    const nextLines = this.renumberPlanOutlineLines(lines);
    const nextText = nextLines.join('\n');
    textarea.value = nextText;
    this.updatePlanOutlineText(session, nextText);
    requestAnimationFrame(() => {
      textarea.focus();
      textarea.setSelectionRange(Math.max(0, nextStart), Math.max(0, nextEnd));
    });
  }

  private applyPlanOutlineEnterShortcut(session: CaptureSession, textarea: HTMLTextAreaElement): void {
    if (!this.canEditPlan(session)) return;
    const original = textarea.value || this.planOutlineText(session);
    const start = textarea.selectionStart || 0;
    const end = textarea.selectionEnd || start;
    const collapsed = `${original.slice(0, start)}${original.slice(end)}`;
    const cursor = start;
    const lineStart = collapsed.lastIndexOf('\n', Math.max(0, cursor - 1)) + 1;
    const nextBreak = collapsed.indexOf('\n', cursor);
    const lineEnd = nextBreak >= 0 ? nextBreak : collapsed.length;
    const currentLine = collapsed.slice(lineStart, lineEnd);
    const lineIndex = collapsed.slice(0, lineStart).split('\n').length - 1;
    const marker = this.planOutlineMarker(currentLine);

    if (!marker) {
      const indent = currentLine.match(/^\s*/)?.[0] || '';
      const nextText = `${collapsed.slice(0, cursor)}\n${indent}${collapsed.slice(cursor)}`;
      const nextCursor = cursor + 1 + indent.length;
      textarea.value = nextText;
      this.updatePlanOutlineText(session, nextText);
      requestAnimationFrame(() => {
        textarea.focus();
        textarea.setSelectionRange(nextCursor, nextCursor);
      });
      return;
    }

    const cursorInLine = cursor - lineStart;
    const cursorAfterMarker = cursorInLine >= marker.prefixLength;
    if (cursorAfterMarker && !marker.body.trim()) {
      const lines = collapsed.split('\n');
      lines[lineIndex] = marker.indent;
      const nextLines = this.renumberPlanOutlineLines(lines);
      const nextCursor = this.planOutlineLineOffset(nextLines, lineIndex) + marker.indent.length;
      const nextText = nextLines.join('\n');
      textarea.value = nextText;
      this.updatePlanOutlineText(session, nextText);
      requestAnimationFrame(() => {
        textarea.focus();
        textarea.setSelectionRange(nextCursor, nextCursor);
      });
      return;
    }

    const provisionalMarker = marker.ordered ? '1. ' : marker.marker;
    const inserted = `\n${marker.indent}${provisionalMarker}`;
    const provisionalText = `${collapsed.slice(0, cursor)}${inserted}${collapsed.slice(cursor)}`;
    const provisionalLines = provisionalText.split('\n');
    const insertedLineIndex = lineIndex + 1;
    const nextLines = marker.ordered ? this.renumberPlanOutlineLines(provisionalLines) : provisionalLines;
    const prefixLength = this.planOutlineMarker(nextLines[insertedLineIndex] || '')?.prefixLength || marker.indent.length;
    const nextCursor = this.planOutlineLineOffset(nextLines, insertedLineIndex) + prefixLength;
    const nextText = nextLines.join('\n');
    textarea.value = nextText;
    this.updatePlanOutlineText(session, nextText);
    requestAnimationFrame(() => {
      textarea.focus();
      textarea.setSelectionRange(nextCursor, nextCursor);
    });
  }

  private selectedPlanOutlineLines(text: string, start: number, end: number): { startLine: number; endLine: number } {
    const safeStart = Math.max(0, Math.min(start, text.length));
    const rawEnd = Math.max(safeStart, Math.min(end, text.length));
    const safeEnd = rawEnd > safeStart && text[rawEnd - 1] === '\n' ? rawEnd - 1 : rawEnd;
    return {
      startLine: text.slice(0, safeStart).split('\n').length - 1,
      endLine: text.slice(0, safeEnd).split('\n').length - 1,
    };
  }

  private planOutlineLineOffset(lines: string[], lineIndex: number): number {
    let offset = 0;
    for (let index = 0; index < lineIndex; index += 1) {
      offset += (lines[index] || '').length + 1;
    }
    return offset;
  }

  private formatPlanOutlineLine(line: string, action: PlanOutlineFormatAction, number: number): string {
    if (action === 'indent') return `   ${line}`;
    if (action === 'outdent') return line.replace(/^( {1,3}|\t)/, '');
    return line;
  }

  private renumberPlanOutlineLines(lines: string[]): string[] {
    const counters: number[] = [];
    let previousLevel = 0;
    return lines.map((line) => {
      if (!line.trim()) return line;
      const requestedLevel = this.planOutlineIndentLevel(line);
      const level = counters.length ? Math.min(requestedLevel, previousLevel + 1) : 0;
      for (let index = 0; index < level; index += 1) {
        counters[index] = counters[index] || 1;
      }
      counters[level] = (counters[level] || 0) + 1;
      counters.length = level + 1;
      previousLevel = level;
      const marker = this.planOutlineMarker(line);
      const strippedBody = this.stripPlanOutlineMarker(line.trim());
      const body = strippedBody || (marker ? '' : 'Point à préciser');
      return `${'   '.repeat(level)}${counters.slice(0, level + 1).join('.')}. ${body}`;
    });
  }

  private planOutlineMarker(line: string): {
    indent: string;
    marker: string;
    body: string;
    prefixLength: number;
    ordered: boolean;
  } | null {
    const match = /^(\s*)((?:(?:\d+(?:\.\d+)*)|[a-zA-Z])[.)]\s+|[-*•·▪◦]\s+)(.*)$/.exec(line);
    if (!match) return null;
    const marker = match[2] || '';
    return {
      indent: match[1] || '',
      marker,
      body: match[3] || '',
      prefixLength: (match[1] || '').length + marker.length,
      ordered: /^(?:\d|[a-zA-Z])/.test(marker),
    };
  }

  private planOutlineIndentLevel(line: string): number {
    const prefix = line.match(/^\s*/)?.[0] || '';
    const width = Array.from(prefix).reduce((sum, character) => sum + (character === '\t' ? 3 : 1), 0);
    if (width <= 0) return 0;
    return Math.max(1, Math.round(width / 3));
  }

  private stripPlanOutlineMarker(value: string): string {
    return value
      .replace(/^(?:#{1,6}\s+|\d+(?:\.\d+)*[.)]?\s+|[a-zA-Z][.)]\s+|[-*•·▪◦]\s+)/, '')
      .trim();
  }

  private resetPlanOutlineDraft(session: CaptureSession): void {
    this.planOutlineDrafts.set(session.id, this.serializePlanOutline(this.planTopics(session)));
  }

  private serializePlanOutline(topics: CaptureTopic[]): string {
    return topics
      .map((topic, topicIndex) => {
        const lines = [`${topicIndex + 1}. ${topic.title}`];
        const subtopics = topic.subtopics || [];
        const visibleSubtopics = subtopics.filter((subtopic) => {
          const title = (subtopic.title || '').trim();
          return title && !(subtopics.length === 1 && title === topic.title && !subtopic.objective);
        });
        visibleSubtopics.forEach((subtopic, subtopicIndex) => {
          lines.push(`   ${topicIndex + 1}.${subtopicIndex + 1}. ${subtopic.title}`);
        });
        return lines.join('\n');
      })
      .join('\n');
  }

  private parsePlanOutline(text: string, fallbackTopics: CaptureTopic[]): CaptureTopic[] {
    const topics: CaptureTopic[] = [];
    let currentTopic: CaptureTopic | null = null;
    const addTopic = (title: string): CaptureTopic => {
      const index = topics.length;
      const fallback = fallbackTopics[index];
      const topic: CaptureTopic = {
        id: fallback?.id || `t-${String(index + 1).padStart(2, '0')}`,
        title: title.trim() || `Sujet ${index + 1}`,
        objective: '',
        status: fallback?.status,
        knowledge_refs: fallback?.knowledge_refs || [],
        subtopics: [],
      };
      topics.push(topic);
      currentTopic = topic;
      return topic;
    };
    const addSubtopic = (title: string): void => {
      const topic = currentTopic || addTopic('Plan');
      const subtopics = topic.subtopics || [];
      const fallback = fallbackTopics[topics.length - 1]?.subtopics?.[subtopics.length];
      subtopics.push({
        id: fallback?.id || `${topic.id}-sub-${String(subtopics.length + 1).padStart(2, '0')}`,
        title: title.trim() || `Sous-sujet ${subtopics.length + 1}`,
        objective: '',
        status: fallback?.status || 'pending',
      });
      topic.subtopics = subtopics;
    };

    for (const rawLine of text.split(/\r?\n/)) {
      if (!rawLine.trim()) continue;
      const indent = rawLine.length - rawLine.trimStart().length;
      const line = rawLine.trim();
      const heading = /^(#{1,6})\s+(.+)$/.exec(line);
      if (heading) {
        if (heading[1].length === 1) addTopic(heading[2]);
        else addSubtopic(heading[2]);
        continue;
      }
      const dotted = /^(\d+(?:\.\d+)+)[.)]?\s+(.+)$/.exec(line);
      if (dotted) {
        if (dotted[1].includes('.')) addSubtopic(dotted[2]);
        else addTopic(dotted[2]);
        continue;
      }
      const numbered = /^\d+[.)]\s+(.+)$/.exec(line);
      if (numbered) {
        addTopic(numbered[1]);
        continue;
      }
      const alpha = /^[a-zA-Z][.)]\s+(.+)$/.exec(line);
      if (alpha) {
        addSubtopic(alpha[1]);
        continue;
      }
      const bullet = /^[-*•·▪◦]\s+(.+)$/.exec(line);
      if (bullet) {
        if (!currentTopic) addTopic(bullet[1]);
        else addSubtopic(bullet[1]);
        continue;
      }
      if (!currentTopic || indent === 0) addTopic(line);
      else addSubtopic(line);
    }

    return topics;
  }

  outlineItemLabel(item?: { prompt?: string; title?: string; question?: string } | null): string {
    if (!item) return '';
    return (item.prompt || item.title || item.question || '').trim();
  }

  outlineItemPrompt(item?: { prompt?: string } | null): string | null {
    const value = (item?.prompt || '').trim();
    return value || null;
  }

  topicQuestionCount(topic: CaptureTopic): number {
    return (topic.subtopics || []).reduce((total, subtopic) => total + (subtopic.questions || []).length, 0);
  }

  canEditPlan(session: CaptureSession): boolean {
    return (this.isTopicPlan(session) || this.isTopicOnlyPlan(session)) && session.status === 'planned';
  }

  canApprovePlan(session: CaptureSession): boolean {
    return false;
  }

  canStartSessionPlan(session: CaptureSession): boolean {
    if (this.isFreeConversationSession(session)) return true;
    if (this.isTopicOnlyPlan(session)) {
      // Outline-driven capture does not need the question bank to be ready:
      // a validated outline (or any topics) is enough to start.
      return (
        this.sessionHasStarted(session) ||
        this.planQuestions(session).length > 0 ||
        this.planTopics(session).length > 0 ||
        session.plan.review?.status === 'topics_validated'
      );
    }
    return this.sessionHasStarted(session) || this.planQuestions(session).length > 0;
  }

  planBlockingReason(session: CaptureSession): string | null {
    if (this.canStartSessionPlan(session)) {
      // Not blocking, but surface question-bank progress instead of silence.
      if (
        this.isTopicOnlyPlan(session) &&
        !this.sessionHasStarted(session) &&
        (session.plan.question_bank_status || this.questionBankStatus()) === 'generating'
      ) {
        return 'Préparation des angles d’exploration en arrière-plan — vous pouvez démarrer dès maintenant.';
      }
      return null;
    }
    if (!this.canCaptureExecute(session)) return 'Votre rôle ne permet pas de démarrer cette session.';
    if (this.isTopicOnlyPlan(session)) {
      return 'Ajoutez au moins une rubrique au plan avant de démarrer.';
    }
    return 'Ajoutez au moins un point exploitable avant de démarrer.';
  }

  isTopicPlan(session: CaptureSession): boolean {
    return session.plan.schema_version === 'topic_plan_v1';
  }

  isFreeConversationSession(session: CaptureSession): boolean {
    return session.plan.schema_version === 'free_conversation_v1' || session.plan['mode'] === 'free_conversation';
  }

  isPlanBuildSession(session: CaptureSession): boolean {
    return (
      session.plan.schema_version === 'plan_build_v1' ||
      session.plan.schema_version === 'plan_build_v2' ||
      session.plan['mode'] === 'plan_build' ||
      session.plan['mode'] === 'provided_plan'
    );
  }

  isProvidedPlanSession(session: CaptureSession): boolean {
    return session.plan?.['mode'] === 'provided_plan';
  }

  isTopicOnlyPlan(session: CaptureSession): boolean {
    return session.plan.schema_version === 'plan_build_v2' || this.isPlanBuildSession(session);
  }

  planSubtopicCount(session: CaptureSession): number {
    return this.planTopics(session).reduce((total, topic) => total + (topic.subtopics?.length || 0), 0);
  }

  subtopicsLabel(count: number): string {
    return this.i18n.t(
      count === 1 ? 'capture.progress.subtopics_one' : 'capture.progress.subtopics_many',
      { count },
    );
  }

  subtopicQuestionCount(subtopic: CaptureSubtopic): number {
    return subtopic.questions?.length || 0;
  }

  subtopicHasCurrentQuestion(session: CaptureSession, subtopic: CaptureSubtopic): boolean {
    const selected = this.selectedQuestionId();
    if (!selected) return false;
    return this.planQuestions(session).some((question) => question.id === selected && question.subtopic_id === subtopic.id);
  }

  subtopicRailClass(session: CaptureSession, subtopic: CaptureSubtopic): string {
    const active = this.activeSubtopicId() === subtopic.id || this.subtopicHasCurrentQuestion(session, subtopic);
    return active
      ? 'mt-2 flex w-full items-center justify-between gap-2 rounded border border-brand-300/40 bg-brand-500/15 px-2 py-2 text-left text-sm text-brand-100'
      : 'mt-2 flex w-full items-center justify-between gap-2 rounded border border-transparent px-2 py-2 text-left text-sm text-gray-400 hover:border-white/10 hover:bg-white/[0.04] hover:text-gray-200';
  }

  topicHasActiveSubtopic(session: CaptureSession, topic: CaptureTopic): boolean {
    if (!(topic.subtopics || []).length) {
      return this.topicOnlySectionActive(session, topic);
    }
    return (topic.subtopics || []).some((subtopic) =>
      this.activeSubtopicId() === subtopic.id || this.subtopicHasCurrentQuestion(session, subtopic),
    );
  }

  topicOnlySectionActive(session: CaptureSession, topic: CaptureTopic): boolean {
    if ((topic.subtopics || []).length) return false;
    const selected = this.selectedQuestionId();
    if (selected) {
      return this.planQuestions(session).some(
        (question) => question.id === selected && question.topic_id === topic.id && !question.subtopic_id,
      );
    }
    const ref = this.activeSectionRef(session);
    return ref.topic_id === topic.id && !ref.subtopic_id;
  }

  topicOnlyRailClass(session: CaptureSession, topic: CaptureTopic): string {
    const active = this.topicOnlySectionActive(session, topic);
    return active
      ? 'rounded border border-brand-300/40 bg-brand-500/15 px-2 py-1 text-brand-100'
      : 'rounded border border-transparent px-2 py-1 text-gray-200 hover:border-white/10 hover:bg-white/[0.04] hover:text-white';
  }

  selectCaptureTopic(topicId: string): void {
    this.navigateCaptureSection(topicId, { manual: true, topicId });
  }

  captureTopicCardClass(session: CaptureSession, topic: CaptureTopic): string {
    const base = 'rounded border p-3';
    return this.topicHasActiveSubtopic(session, topic)
      ? `${base} border-brand-300/35 bg-brand-500/15`
      : `${base} border-white/10 bg-black/20`;
  }

  captureSubtopicCardClass(session: CaptureSession, subtopic: CaptureSubtopic): string {
    const active = this.activeSubtopicId() === subtopic.id || this.subtopicHasCurrentQuestion(session, subtopic);
    const base = 'flex w-full items-start gap-2 rounded px-3 py-2 text-left';
    return active
      ? `${base} bg-brand-300/15 text-brand-50 ring-1 ring-brand-300/30`
      : `${base} bg-white/[0.035] text-gray-300 hover:bg-white/[0.07] hover:text-white`;
  }

  subtopicProgressLabel(session: CaptureSession, subtopic: CaptureSubtopic): string {
    const count = this.subtopicQuestionCount(subtopic);
    if (!count) {
      return this.i18n.t(
        this.activeSubtopicId() === subtopic.id ? 'capture.subtopic.active' : 'capture.subtopic.subject',
      );
    }
    if (this.subtopicHasCurrentQuestion(session, subtopic)) return this.i18n.t('capture.question.status.current');
    return this.i18n.t(count === 1 ? 'capture.subtopic.prompts_one' : 'capture.subtopic.prompts_many', { count });
  }

  questionBankStatusLabel(session: CaptureSession): string {
    const status = String(session.plan.question_bank_status || this.questionBankStatus());
    if (status === 'generating') return 'Angles de relance en préparation';
    if (status === 'ready') return 'Banque prête';
    if ((session.plan.review?.status || '') === 'topics_validated') return 'Prêt pour l’échange';
    return 'En attente de validation du plan';
  }

  topHint(): CaptureHint | null {
    const stack = this.hintStack();
    return stack.length ? stack[0] : null;
  }

  selectCaptureSubtopic(subtopicId: string): void {
    this.navigateCaptureSection(subtopicId, { manual: true });
  }

  /** Jump to a plan subtopic; optional WS sync for manual left-rail navigation. */
  private navigateCaptureSection(
    sectionId: string,
    options: { manual?: boolean; topicId?: string | null; syncVoice?: boolean } = {},
  ): void {
    if (options.manual) {
      this.manualSectionSelectedAt = Date.now();
    }
    const session = this.session();
    if (!session) return;
    const topics = this.planTopics(session);
    const topicOnly = topics.find((item) => item.id === sectionId && !(item.subtopics || []).length);
    if (topicOnly) {
      this.activeSubtopicId.set(null);
      const question = this.planQuestions(session).find(
        (item) => item.topic_id === sectionId && !item.subtopic_id,
      );
      if (question) {
        this.selectedQuestionId.set(question.id);
      }
      this.refreshHintQueue(session.id, undefined);
      if (options.syncVoice !== false) {
        this.voiceConnection?.sectionSelect({
          topic_id: sectionId,
          subtopic_id: null,
          manual: options.manual === true,
        });
      }
      return;
    }
    this.activeSubtopicId.set(sectionId);
    const topic =
      topics.find((item) => (item.subtopics || []).some((st) => st.id === sectionId)) || null;
    const subtopic = topic?.subtopics?.find((item) => item.id === sectionId);
    const firstQuestion = subtopic?.questions?.[0];
    if (firstQuestion) {
      this.selectedQuestionId.set(firstQuestion.id);
    }
    this.refreshHintQueue(session.id, sectionId);
    if (options.syncVoice !== false) {
      this.voiceConnection?.sectionSelect({
        topic_id: options.topicId ?? topic?.id ?? null,
        subtopic_id: sectionId,
        manual: options.manual === true,
      });
    }
  }

  /** Apply a lightweight live section suggestion when confidence and cooldown allow. */
  private applyLiveSectionDetection(
    subtopicId: string | null | undefined,
    topicId: string | null | undefined,
    confidence: number,
    source: string,
  ): void {
    if (!subtopicId || confidence < this.liveSectionDetectMinConfidence) return;
    if (subtopicId === this.activeSubtopicId()) return;
    if (Date.now() - this.manualSectionSelectedAt < this.manualSectionOverrideCooldownMs) return;
    this.navigateCaptureSection(subtopicId, { manual: false, topicId, syncVoice: true });
  }

  planDialogueTurns(session: CaptureSession): Array<{ id: string; text: string }> {
    const dialogue = (session.plan['dialogue'] as { turns?: Array<{ id: string; text: string }> }) || {};
    return dialogue.turns || [];
  }

  planOracle(session: CaptureSession): PlanOracleSnapshot | null {
    const oracle = session.plan.oracle;
    if (!oracle) return null;
    const hasGaps = (oracle.coverage_gaps?.length || 0) > 0;
    return hasGaps ? oracle : null;
  }

  planTopicRationale(topic: CaptureTopic): string | null {
    const rationale = (topic.rationale || topic.objective || '').trim();
    return rationale || null;
  }

  planDialoguePrompt(): string | null {
    return this.planDialogueNextPrompt();
  }

  planDialoguePromptFor(session: CaptureSession): string | null {
    const dialogue = (session.plan['dialogue'] as { turns?: unknown[]; ready_to_finalize?: boolean }) || {};
    const turns = dialogue.turns?.length || 0;
    const prompts = [
      'Collez ou dictez le plan exact à respecter, avec vos numéros et indentations si vous en avez.',
      'Modifiez directement les rubriques à garder, ajouter ou retirer. Je conserve vos intitulés.',
      'Ajoutez seulement les sous-parties ou exceptions que vous voulez voir dans le plan.',
      'Dernière vérification : le bloc texte ci-contre est le plan qui sera utilisé.',
    ];
    if (dialogue.ready_to_finalize) return 'Vous pouvez valider le plan quand il vous convient.';
    return prompts[Math.min(turns, prompts.length - 1)] || null;
  }

  planDialogueReady(session: CaptureSession): boolean {
    // The plan is ready to validate as soon as the dialogue has produced at
    // least one topic ("Envoyer" builds plan.topics). This matches the backend
    // gate ("au moins un topic existe") and removes the old word-count mismatch.
    if (this.planTopics(session).length > 0) return true;
    if (this.planDialogueReadyFlag()) return true;
    return Boolean((session.plan['dialogue'] as { ready_to_finalize?: boolean })?.ready_to_finalize);
  }

  refreshQualityBacklog(sessionId: string): void {
    this.api
      .getCaptureQualityBacklog(sessionId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((payload) => {
        this.qualityBacklog.set({
          imprecisions: (payload.imprecisions || []) as unknown as QualityBacklogItem[],
          contradictions: (payload.contradictions || []) as unknown as QualityBacklogItem[],
          open_questions: (payload.open_questions || []) as unknown as QualityBacklogItem[],
        });
        this.deferWeakContradictions.set(Boolean(payload.defer_weak_contradictions));
      });
  }

  activeQualityItems(): QualityBacklogItem[] {
    const tab = this.qualityTab();
    if (tab === 'contradictions') return [];
    const backlog = this.qualityBacklog();
    return backlog[tab] || [];
  }

  qualityBacklogCount(): number {
    const backlog = this.qualityBacklog();
    return backlog.imprecisions.length + backlog.open_questions.length;
  }

  residualQualityCount(): number {
    return this.qualityBacklogCount();
  }

  toggleDeferWeakContradictions(session: CaptureSession, enabled: boolean): void {
    this.deferWeakContradictions.set(enabled);
    this.api
      .patchCaptureSessionFlags(session.id, { defer_weak_contradictions: enabled })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.refreshQualityBacklog(session.id));
  }

  deferQualityItem(session: CaptureSession, item: QualityBacklogItem): void {
    const bucket = this.qualityTab();
    this.api
      .deferCaptureQualityItem(session.id, {
        item_id: item.id || 'quality-item',
        bucket,
        deferred_reason: 'end_of_session',
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((payload) => {
        this.qualityBacklog.set({
          imprecisions: (payload.imprecisions || []) as unknown as QualityBacklogItem[],
          contradictions: (payload.contradictions || []) as unknown as QualityBacklogItem[],
          open_questions: (payload.open_questions || []) as unknown as QualityBacklogItem[],
        });
      });
  }

  respondToQualityItem(session: CaptureSession, item: QualityBacklogItem): void {
    const prompt = item.follow_up || item.label || '';
    if (!prompt) return;
    if (item.question_id) {
      this.selectedQuestionId.set(item.question_id);
    }
    this.api
      .patchCaptureSessionFlags(session.id, {
        focused_quality_question_id: item.question_id || null,
        focused_quality_evaluation_id: item.id || null,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe();
    this.answer = '';
    this.speak(this.promptText(prompt));
    void this.startRecordingTurn();
  }

  submitPlanDialogueTurn(session: CaptureSession): void {
    const text = this.planDialogueAnswer().trim();
    if (!text) {
      this.planDialogueNotice.set({
        tone: 'info',
        text: 'Saisissez ou dictez une description du sujet avant d’envoyer.',
      });
      return;
    }
    void this.persistPlanTopicsAndSubmitDialogue(session, text);
  }

  private async persistPlanTopicsAndSubmitDialogue(session: CaptureSession, text: string): Promise<void> {
    this.planDialogueNotice.set(null);
    this.planDialogueLoading.set(true);
    try {
      const topics = this.planTopics(session);
      if (topics.length) {
        await firstValueFrom(
          this.api
            .updateCapturePlanTopics(session.id, topics as unknown as Record<string, unknown>[])
            .pipe(takeUntilDestroyed(this.destroyRef)),
        );
      }
      const payload = await firstValueFrom(
        this.api.planDialogueTurn(session.id, { text }).pipe(takeUntilDestroyed(this.destroyRef)),
      );
      const body = payload as {
        session: CaptureSession;
        next_prompt?: string | null;
        ready_to_finalize?: boolean;
      };
      this.session.set(body.session);
      this.resetPlanOutlineDraft(body.session);
      this.planDialogueAnswer.set('');
      this.planDialogueNextPrompt.set(body.next_prompt || this.planDialoguePromptFor(body.session));
      this.planDialogueReadyFlag.set(Boolean(body.ready_to_finalize));
      this.planDialogueLoading.set(false);
      this.planDialogueNotice.set(null);
      this.touchPlanDraft();
    } catch (err) {
      this.planDialogueLoading.set(false);
      this.planDialogueNotice.set({
        tone: 'error',
        text: this.apiErrorMessage(err, 'Impossible d’envoyer ce tour de cadrage. Réessayez.'),
      });
    }
  }

  planDialogueReadyHint(session: CaptureSession): string | null {
    if (this.planDialogueReady(session)) return null;
    return 'Ajoutez une instruction ou complétez le plan : « Valider le plan » s’active dès qu’un sujet existe.';
  }

  private apiErrorMessage(err: unknown, fallback: string): string {
    const detail = (err as { error?: { detail?: unknown }; message?: string })?.error?.detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
    const message = (err as { message?: string })?.message;
    if (typeof message === 'string' && message.trim()) return message;
    return fallback;
  }

  validatePlanTopics(session: CaptureSession): void {
    const topics = this.planTopics(session);
    if (!topics.length) {
      this.planNotice.set({ tone: 'error', text: 'Aucun sujet à valider. Ajoutez au moins un sujet au plan.' });
      return;
    }
    this.planDialogueLoading.set(true);
    this.planNotice.set(null);
    this.planDialogueNotice.set(null);
    this.api
      .updateCapturePlanTopics(session.id, topics as unknown as Record<string, unknown>[])
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.api
            .validateCapturePlanTopics(session.id)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
              next: (updated) => {
                const typed = updated as CaptureSession;
                this.session.set(typed);
                this.ensureDefaultPlanSection(typed);
                this.resetPlanOutlineDraft(typed);
                this.questionBankStatus.set(String(typed.plan.question_bank_status || 'generating'));
                this.planDialogueLoading.set(false);
                this.planNotice.set(null);
                this.clearCaptureTranscriptState();
                this.activeSurface.set('session');
                this.pollQuestionBankStatus(session.id);
              },
              error: (err) => {
                this.planDialogueLoading.set(false);
                this.planNotice.set({ tone: 'error', text: this.apiErrorMessage(err, 'La validation des sujets a échoué. Réessayez.') });
              },
            });
        },
        error: (err) => {
          this.planDialogueLoading.set(false);
          this.planNotice.set({ tone: 'error', text: this.apiErrorMessage(err, 'Enregistrement des sujets impossible. Réessayez.') });
        },
      });
  }

  private pollQuestionBankStatus(sessionId: string, attempt = 0): void {
    if (attempt > 12) return;
    window.setTimeout(() => {
      this.api
        .getCapturePlanTopics(sessionId)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe((payload) => {
          const body = payload as { question_bank_status?: string };
          const status = body.question_bank_status || 'idle';
          this.questionBankStatus.set(status);
          if (status !== 'ready') {
            this.pollQuestionBankStatus(sessionId, attempt + 1);
          } else {
            this.api.listCaptureSessions(undefined, undefined, this.systemId || undefined).pipe(takeUntilDestroyed(this.destroyRef)).subscribe((rows) => {
              const sessions = ((rows as { sessions?: CaptureSession[] }).sessions || []);
              const current = sessions.find((row) => row.id === sessionId);
              if (current) this.session.set(current);
            });
            this.planNotice.set({ tone: 'success', text: 'Banque de questions prête — vous pouvez démarrer la capture.' });
          }
        });
    }, 1500);
  }

  refreshHintQueue(sessionId: string, subtopicId?: string | null): void {
    this.api
      .getCaptureHintQueue(sessionId, subtopicId || this.activeSubtopicId() || undefined)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((payload) => {
        const hints = ((payload as { hints?: CaptureHint[] }).hints || []) as CaptureHint[];
        this.hintStack.set(hints);
      });
  }

  finalizePlanBuild(session: CaptureSession): void {
    if (this.planTopics(session).length) {
      this.validatePlanTopics(session);
      return;
    }
    this.planDialogueLoading.set(true);
    this.planNotice.set(null);
    this.planDialogueNotice.set(null);
    this.api
      .finalizeCapturePlan(session.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          const typed = updated as CaptureSession;
          this.session.set(typed);
          this.resetPlanOutlineDraft(typed);
          this.questionBankStatus.set(String(typed.plan.question_bank_status || 'idle'));
          this.planDialogueLoading.set(false);
          this.validatePlanTopics(typed);
        },
        error: (err) => {
          this.planDialogueLoading.set(false);
          this.planNotice.set({ tone: 'error', text: this.apiErrorMessage(err, 'La préparation du plan a échoué. Réessayez.') });
        },
      });
  }

  onProvidedPlanFile(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    input.value = '';
    if (this.hasProvidedPlanSource() || this.session()) {
      this.pendingPlanSourceReplacement.set({
        file,
        filename: file.name,
        size: file.size,
      });
      return;
    }
    this.extractProvidedPlanFile(file);
  }

  /**
   * « Importer » in the plan-modification flow: the extracted file content is
   * treated as an INSTRUCTION applied to the current plan (same pipeline as the
   * dictated/typed instruction + « Appliquer »), never pasted as the plan itself.
   * The plan oracle merges it into the existing plan, whether the file contains
   * an actual plan, free-form notes or a transcript.
   */
  onPlanInstructionImportFile(event: Event, session: CaptureSession): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file || !this.canEditPlan(session)) return;
    input.value = '';
    this.extractingPlanSource.set(true);
    this.planDialogueNotice.set({ tone: 'info', text: this.i18n.t('capture.plan.import_extracting') });
    this.api
      .extractCapturePlanSource(file)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (payload) => {
          this.extractingPlanSource.set(false);
          this.applyImportedPlanInstruction(session, String(payload.text || ''), file.name);
        },
        error: () => this.readPlanInstructionImportFileLocally(file, session),
      });
  }

  private readPlanInstructionImportFileLocally(file: File, session: CaptureSession): void {
    const reader = new FileReader();
    reader.onload = () => {
      this.extractingPlanSource.set(false);
      this.applyImportedPlanInstruction(session, String(reader.result || ''), file.name);
    };
    reader.onerror = () => {
      this.extractingPlanSource.set(false);
      this.planDialogueNotice.set({ tone: 'error', text: this.i18n.t('capture.plan.import_failed') });
    };
    reader.readAsText(file);
  }

  /** Feed the imported content through the same plan-iteration path as the
   * instruction textarea (`latest_instruction` + current plan on the backend). */
  private applyImportedPlanInstruction(session: CaptureSession, rawText: string, filename: string): void {
    // Same hard limit as the backend plan-source extraction (20k chars).
    const text = rawText.replace(/\r\n?/g, '\n').trim().slice(0, 20000);
    if (!text) {
      this.planDialogueNotice.set({ tone: 'error', text: this.i18n.t('capture.plan.import_empty') });
      return;
    }
    const instruction =
      `Contenu importé depuis « ${filename} ». Intègre ces éléments dans le plan actuel : ` +
      `fusionne avec les sujets existants sans les perdre, ajoute les nouveaux sujets/sous-sujets pertinents, ` +
      `et restructure si nécessaire. Le contenu peut être un plan, des notes libres ou une transcription.\n\n${text}`;
    this.planDialogueNotice.set({ tone: 'info', text: this.i18n.t('capture.plan.import_applying', { filename }) });
    void this.persistPlanTopicsAndSubmitDialogue(session, instruction);
  }

  onPlanOutlineImportFile(event: Event, session: CaptureSession): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file || !this.canEditPlan(session)) return;
    input.value = '';
    this.extractingPlanSource.set(true);
    this.api
      .extractCapturePlanSource(file)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (payload) => {
          this.applyImportedPlanOutline(session, String(payload.text || ''), file.name);
          this.extractingPlanSource.set(false);
        },
        error: () => this.readPlanOutlineImportFileLocally(file, session),
      });
  }

  private extractProvidedPlanFile(file: File): void {
    this.providedPlanFileName = file.name;
    this.providedPlanSourceKind = 'uploaded_file';
    this.extractingPlanSource.set(true);
    this.api
      .extractCapturePlanSource(file)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (payload) => {
          this.providedPlanText = String(payload.text || '').slice(0, 20000);
          this.extractingPlanSource.set(false);
        },
        error: () => this.readProvidedPlanFileLocally(file),
      });
  }

  private readProvidedPlanFileLocally(file: File): void {
    const reader = new FileReader();
    reader.onload = () => {
      this.providedPlanText = String(reader.result || '').slice(0, 20000);
      this.extractingPlanSource.set(false);
    };
    reader.onerror = () => {
      this.extractingPlanSource.set(false);
      this.setVoiceNotice("Impossible d'extraire le texte du fichier sélectionné.", 'error');
    };
    reader.readAsText(file);
  }

  private readPlanOutlineImportFileLocally(file: File, session: CaptureSession): void {
    const reader = new FileReader();
    reader.onload = () => {
      this.applyImportedPlanOutline(session, String(reader.result || ''), file.name);
      this.extractingPlanSource.set(false);
    };
    reader.onerror = () => {
      this.extractingPlanSource.set(false);
      this.planNotice.set({ tone: 'error', text: "Impossible d'importer ce fichier de plan." });
    };
    reader.readAsText(file);
  }

  private applyImportedPlanOutline(session: CaptureSession, rawText: string, filename: string): void {
    const text = rawText.slice(0, 20000).replace(/\r\n?/g, '\n');
    const lines = this.renumberPlanOutlineLines(text.split('\n'));
    const outline = lines.join('\n').trim();
    if (!outline) {
      this.planNotice.set({ tone: 'error', text: 'Le fichier importé ne contient pas de plan exploitable.' });
      return;
    }
    this.updatePlanOutlineText(session, outline);
    this.planNotice.set({
      tone: 'info',
      text: `Plan importé depuis ${filename}. Vous pouvez le modifier avant de lancer la capture.`,
    });
    requestAnimationFrame(() => {
      const textarea = this.planBuildOutlineEditor?.nativeElement || this.planOutlineEditor?.nativeElement;
      textarea?.focus();
      textarea?.setSelectionRange(outline.length, outline.length);
    });
  }

  async dictatePrepSubject(): Promise<void> {
    if (this.recording()) {
      this.finishDictation();
      return;
    }
    await this.beginDictation((text) => {
      this.objective = text;
    });
  }

  async dictatePlanDialogue(): Promise<void> {
    if (this.recording()) {
      this.finishDictation();
      return;
    }
    await this.beginDictation((text) => {
      this.planDialogueAnswer.set(text);
    }, 'plan');
  }

  /**
   * Start an icon-only dictation. The captured audio is transcribed live
   * (throttled partials) into the target field while speaking, and finalised on
   * stop. Unlike the conversation hard-stop, dictation MUST transcribe — it
   * routes through the standard recorder `onstop` → `transcribeRecording` path,
   * never the discard-style hard stop.
   */
  private async beginDictation(
    write: (text: string) => void,
    surface: 'plan' | 'proposal_question' | 'prep' | null = null,
  ): Promise<void> {
    if (this.speaking()) this.interruptSpeech();
    const armed = await this.ensureAudioStream();
    if (!armed) return;
    this.dictationSurface.set(surface);
    this.dictationVoiceDetected.set(false);
    this.dictationSilenceEnding.set(false);
    this.dictationAudioLevel.set(0);
    this.resetHttpBatchRecordingBuffers();
    this.currentClientTurnId = this.newTurnId();
    this.commandHandledForTurn = null;
    this.lastPrefetchText = '';
    this.lastPrefetchAt = 0;
    this.recordingPartialCallback = (text: string) => {
      const clean = text.trim();
      if (clean) write(clean);
    };
    this.recordingStopCallback = (text: string) => {
      const clean = text.trim();
      if (clean) write(clean);
      this.recordingPartialCallback = null;
    };
    this.setVoiceNotice('Dictée en cours : le texte s’affiche en direct, puis se finalise à l’arrêt.', 'info');
    if (!this.startAudioRecorder('Dictée en cours. Appuyez sur le carré pour arrêter et finaliser.')) {
      this.recordingPartialCallback = null;
      this.recordingStopCallback = null;
      this.clearDictationSurface();
      return;
    }
    if (surface) {
      this.startDictationAudioMonitor();
    }
  }

  /** Stop an in-progress dictation and finalise it (transcribe + write). */
  private finishDictation(): void {
    if (this.recorder && this.recorder.state !== 'inactive') {
      this.endpointRecordingTurn('manual');
    }
  }

  private recordingStopCallback: ((text: string) => void) | null = null;
  private recordingPartialCallback: ((text: string) => void) | null = null;

  pauseSession(session: CaptureSession): void {
    this.api
      .pauseCaptureSession(session.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((payload) => {
        const typed = payload as CaptureSession;
        this.session.set(typed);
        const summary = (typed.metrics?.['resume_summary'] as string) || 'Session en pause.';
        this.setVoiceNotice(summary, 'info');
        this.speak(summary);
      });
  }

  resumeSession(session: CaptureSession): void {
    this.api
      .resumeCaptureSession(session.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((payload) => {
        const typed = payload as CaptureSession;
        this.session.set(typed);
        void this.startGuidedSession(typed);
      });
  }

  publishToKnowledge(proposalId: string): void {
    const proposal = this.proposal();
    const publishHint = this.proposalPublishHint(proposal);
    if (publishHint) {
      this.setVoiceNotice(publishHint, 'warning');
      return;
    }
    this.publicationPublishing.set(true);
    this.persistProposalReport(proposalId, () => {
      this.api
        .publishCaptureProposal(proposalId, {
          category: this.publicationCategory,
          destination: this.effectivePublicationDestination(),
          destination_scope: this.effectivePublicationDestination(),
          final_title: this.effectivePublicationFinalTitle(),
          include_unresolved_questions: true,
        })
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (payload) => {
            const result = payload as CapturePublicationResult;
            this.publicationResult.set(result);
            const current = this.proposal();
            if (current) {
              this.setProposal({
                ...current,
                status: 'published',
                proposal: {
                  ...(current.proposal || {}),
                  publication: {
                    ...(current.proposal?.publication || {}),
                    category: result.category || this.publicationCategory,
                    destination: result.destination || this.effectivePublicationDestination(),
                    destination_scope: result.destination || this.effectivePublicationDestination(),
                    final_title: result.final_title || this.effectivePublicationFinalTitle(),
                    document_id: result.document_id || null,
                    collection_slug: result.collection || null,
                    chunks_processed: result.chunks_processed ?? null,
                    published_at: new Date().toISOString(),
                    export_urls: result.export_urls,
                  },
                },
              });
            }
            this.refreshDashboard();
            if (this.dashboardTab() === 'fiches') {
              this.refreshPublishedFiches();
            }
            this.setVoiceNotice(this.i18n.t('capture.publish.success_title'), 'info');
          },
          error: () => {
            this.setVoiceNotice('Publication impossible pour le moment.', 'error');
          },
          complete: () => this.publicationPublishing.set(false),
        });
    });
  }

  exportProposalMd(): void {
    const session = this.session();
    if (!session) return;
    const runExport = () => {
      this.api
        .exportCaptureProposal(session.id, {
          executive_summary: this.executiveSummary,
          proposal_id: this.proposal()?.id,
        })
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe((payload) => {
          const blob = new Blob([payload.markdown], { type: 'text/markdown;charset=utf-8' });
          const url = URL.createObjectURL(blob);
          const anchor = document.createElement('a');
          anchor.href = url;
          anchor.download = `${session.title || 'capture'}.md`;
          anchor.click();
          URL.revokeObjectURL(url);
        });
    };
    const proposalId = this.proposal()?.id;
    if (proposalId) {
      this.persistProposalReport(proposalId, runExport);
    } else {
      runExport();
    }
  }

  regenerateProposal(): void {
    const session = this.session();
    if (!session || !this.canProposalSubmit(session)) return;
    this.createProposal(session);
  }

  planReviewStatus(session: CaptureSession): string {
    return session.plan.review?.status || (this.isTopicPlan(session) ? 'draft' : 'legacy');
  }

  planReviewLabel(session: CaptureSession): string {
    if (this.isFreeConversationSession(session)) return 'capture libre';
    const status = this.planReviewStatus(session);
    if (status === 'approved') return 'plan enregistré';
    if (status === 'edited') return 'changements enregistrés';
    if (status === 'draft') return 'plan prêt';
    if (status === 'topics_validated') return 'sujets validés';
    return 'session prête';
  }

  planNoticeClass(tone: 'success' | 'error' | 'info'): string {
    const base = 'rounded border px-3 py-2 text-sm';
    if (tone === 'success') return `${base} border-emerald-400/30 bg-emerald-500/10 text-emerald-100`;
    if (tone === 'error') return `${base} border-red-400/30 bg-red-500/10 text-red-100`;
    return `${base} border-brand-400/30 bg-brand-500/10 text-brand-100`;
  }

  touchPlanDraft(): void {
    const session = this.session();
    if (!session || !this.canEditPlan(session)) return;
    this.planNotice.set({ tone: 'info', text: 'Modifications non enregistrées. Enregistrez le plan avant de démarrer.' });
    this.session.set({ ...session, plan: { ...session.plan, topics: [...(session.plan.topics || [])] } });
  }

  addQuestion(session: CaptureSession, topic: CaptureTopic, subtopic: CaptureSubtopic): void {
    if (!this.canEditPlan(session)) return;
    const nextId = this.nextQuestionId(session);
    const question: CaptureQuestion = {
      id: nextId,
      topic_id: topic.id,
      subtopic_id: subtopic.id,
      path_label: `${topic.title} / ${subtopic.title}`,
      title: subtopic.title,
      question: 'Nouvelle question à valider avec l’expert.',
      estimated_minutes: 3,
      follow_ups: [],
      completion_criteria: [],
    };
    subtopic.questions = [...(subtopic.questions || []), question];
    this.selectedQuestionId.set(question.id);
    this.touchPlanDraft();
  }

  removeQuestion(session: CaptureSession, subtopic: CaptureSubtopic, index: number): void {
    if (!this.canEditPlan(session) || this.planQuestions(session).length <= 1) return;
    const questions = [...(subtopic.questions || [])];
    questions.splice(index, 1);
    subtopic.questions = questions;
    const selected = this.selectedQuestionId();
    if (selected && !this.planQuestions(session).some((question) => question.id === selected)) {
      this.selectedQuestionId.set(this.planQuestions(session)[0]?.id || null);
    }
    this.touchPlanDraft();
  }

  moveQuestion(session: CaptureSession, subtopic: CaptureSubtopic, index: number, direction: -1 | 1): void {
    if (!this.canEditPlan(session)) return;
    const questions = [...(subtopic.questions || [])];
    const target = index + direction;
    if (target < 0 || target >= questions.length) return;
    [questions[index], questions[target]] = [questions[target], questions[index]];
    subtopic.questions = questions;
    this.touchPlanDraft();
  }

  savePlan(session: CaptureSession): void {
    if (!this.canEditPlan(session) || this.savingPlan()) return;
    this.savingPlan.set(true);
    this.api
      .updateCapturePlan(session.id, session.plan as Record<string, unknown>)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (payload) => {
          const updated = payload as CaptureSession;
          this.session.set(updated);
          this.selectedQuestionId.set(this.planQuestions(updated)[0]?.id || this.selectedQuestionId());
          this.planNotice.set({ tone: 'success', text: 'Plan enregistré. Vous pouvez démarrer la capture.' });
          this.savingPlan.set(false);
        },
        error: () => {
          this.planNotice.set({ tone: 'error', text: 'Enregistrement du plan impossible. Vérifiez que chaque sujet contient au moins une question.' });
          this.savingPlan.set(false);
        },
      });
  }

  approvePlan(session: CaptureSession): void {
    if (!this.canApprovePlan(session) || this.savingPlan()) return;
    this.savingPlan.set(true);
    this.api
      .approveCapturePlan(session.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (payload) => {
          const updated = payload as CaptureSession;
          this.session.set(updated);
          this.selectedQuestionId.set(this.planQuestions(updated)[0]?.id || this.selectedQuestionId());
          this.planNotice.set({ tone: 'success', text: 'Plan validé. Continuez vers l’échange.' });
          this.savingPlan.set(false);
        },
        error: () => {
          this.planNotice.set({ tone: 'error', text: 'Validation du plan impossible. Enregistrez le plan puis réessayez.' });
          this.savingPlan.set(false);
        },
      });
  }

  private nextQuestionId(session: CaptureSession): string {
    const next = this.planQuestions(session).reduce((max, question) => {
      const match = question.id.match(/(\d+)$/);
      return match ? Math.max(max, Number(match[1])) : max;
    }, 0) + 1;
    return `q-${String(next).padStart(2, '0')}`;
  }

  selectCaptureQuestion(question: CaptureQuestion): void {
    this.selectedQuestionId.set(question.id);
  }

  questionDisplayId(question: CaptureQuestion): string {
    const match = question.id.match(/(\d+)$/);
    if (!match) return question.id;
    return `q-${match[1].padStart(2, '0')}`;
  }

  coveragePercent(session: CaptureSession): number {
    const raw = session.metrics?.['coverage'];
    if (typeof raw === 'number' && Number.isFinite(raw)) {
      return Math.max(0, Math.min(100, Math.round(raw * 100)));
    }
    const total = this.planQuestions(session).length;
    if (!total) return 0;
    return Math.round((Number(session.metrics?.['captured_facts'] || 0) / total) * 100);
  }

  isSessionTimerUnlimited(session: CaptureSession): boolean {
    return Boolean(session.metrics?.['unlimited_duration']) || Number(session.duration_minutes || 0) <= 0;
  }

  /**
   * Live countdown chip. The server `remaining_seconds` is used as an ANCHOR
   * (value + reception time) and the per-second clock tick interpolates from
   * it, so the chip really counts down between server payloads instead of
   * displaying a static snapshot. Past zero it keeps counting into overtime
   * ("+m:ss") without ever blocking the capture.
   */
  sessionTimerView(session: CaptureSession): { label: string; blink: boolean; ended: boolean; overtime: boolean } | null {
    this.sessionClockTick();
    if (this.isSessionTimerUnlimited(session)) {
      return null;
    }
    const limitMinutes =
      Number(session.duration_minutes || 0) + Number(session.metrics?.['duration_extension_minutes'] || 0);
    if (limitMinutes <= 0) {
      return null;
    }
    if (!session.started_at) {
      return { label: `${limitMinutes} min`, blink: false, ended: false, overtime: false };
    }
    const anchor = this.timerAnchor && this.timerAnchor.sessionId === session.id ? this.timerAnchor : null;
    let remainingSeconds: number;
    if (session.status === 'active') {
      if (anchor) {
        remainingSeconds = Math.round(anchor.remainingSeconds - (Date.now() - anchor.atMs) / 1000);
      } else {
        const startedAt = new Date(session.started_at).getTime();
        remainingSeconds = Number.isFinite(startedAt)
          ? Math.round(limitMinutes * 60 - (Date.now() - startedAt) / 1000)
          : limitMinutes * 60;
      }
    } else {
      const serverRemaining = Number(session.metrics?.['remaining_seconds'] ?? NaN);
      remainingSeconds = anchor
        ? anchor.remainingSeconds
        : Number.isFinite(serverRemaining)
          ? serverRemaining
          : limitMinutes * 60;
    }
    const ended = remainingSeconds <= 0;
    const overtime = ended && session.status === 'active';
    const display = Math.abs(remainingSeconds);
    const minutes = Math.floor(display / 60);
    const seconds = Math.floor(display % 60);
    const clock = `${minutes}:${String(seconds).padStart(2, '0')}`;
    return {
      label: overtime ? `+${clock} dépassées` : ended ? '0:00 · fin' : `${clock} restantes`,
      blink: !ended && remainingSeconds <= 5 * 60,
      ended,
      overtime,
    };
  }

  /** Discreet, one-shot reminder when entering the last 5 minutes. */
  private maybeNotifyLastFiveMinutes(session: CaptureSession): void {
    if (session.status !== 'active') return;
    const timer = this.sessionTimerView(session);
    if (!timer || timer.ended || !timer.blink) return;
    if (this.lastFiveMinutesNoticeSessionId === session.id) return;
    this.lastFiveMinutesNoticeSessionId = session.id;
    this.setVoiceNotice('Il reste moins de 5 minutes planifiées — la capture continue sans interruption.', 'info');
  }

  showClosurePanel(session: CaptureSession): boolean {
    if (this.closurePanelDismissed()) {
      return false;
    }
    if (Boolean(session.metrics?.['session_end_pending'])) {
      return true;
    }
    const timer = this.sessionTimerView(session);
    return Boolean(timer?.ended && session.status === 'active');
  }

  private maybeOpenClosurePanel(session: CaptureSession): void {
    const timer = this.sessionTimerView(session);
    if (timer?.ended && session.status === 'active' && !this.closureSheetMarkdown()) {
      this.ensureClosureSheet(session.id);
    }
  }

  private syncClosureSheetFromSession(session: CaptureSession): void {
    const stored = session.metrics?.['closure_sheet'];
    if (typeof stored === 'string' && stored.trim()) {
      this.closureSheetMarkdown.set(stored);
    }
  }

  ensureClosureSheet(sessionId: string): void {
    this.api
      .getCaptureClosureSheet(sessionId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((payload) => {
        const markdown = (payload as { markdown?: string }).markdown;
        if (markdown) {
          this.closureSheetMarkdown.set(markdown);
        }
      });
  }

  applySessionClosure(session: CaptureSession, action: 'finish' | 'extend' | 'schedule'): void {
    this.closureActionLoading.set(true);
    this.api
      .applyCaptureSessionClosure(session.id, { action })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (payload) => {
          const body = payload as {
            session?: CaptureSession;
            proposal?: CaptureProposal;
            closure_sheet?: { markdown?: string };
          };
          if (body.session) {
            this.session.set(body.session);
            this.syncClosureSheetFromSession(body.session);
          }
          if (body.closure_sheet?.markdown) {
            this.closureSheetMarkdown.set(body.closure_sheet.markdown);
          }
          if (action === 'extend') {
            this.closurePanelDismissed.set(false);
            this.setVoiceNotice('Session prolongée de 15 minutes.', 'info');
          } else if (action === 'schedule') {
            this.closurePanelDismissed.set(true);
            this.activeSurface.set('prep');
            this.setVoiceNotice('Session mise en pause pour replanification.', 'info');
          } else {
            this.closurePanelDismissed.set(true);
            if (body.proposal) {
              this.setProposal(body.proposal);
              // While the heavy FINAL pass is still running (capture.finish over
              // WS), stay on the loader: the report screen only opens when the
              // restructured report is persisted (proposal-ready step).
              if (!this.captureFinalizing()) {
                this.activeSurface.set('review');
              }
            } else if (!this.captureFinalizing()) {
              this.activeSurface.set('session');
              this.setVoiceNotice('Aucun rapport exploitable n’a encore été produit. Reprenez la capture ou régénérez après ajout de matière.', 'warning');
            }
          }
          this.closureActionLoading.set(false);
          this.refreshDashboard();
        },
        error: () => {
          this.closureActionLoading.set(false);
          this.setVoiceNotice('Action de fin de session impossible.', 'error');
        },
      });
  }

  answerQualityHeadline(): string {
    const evaluation = this.lastEvaluation();
    if (!evaluation) return 'En attente d’une première réponse';
    return `Réponse ${this.evaluationVerdictLabel(evaluation.verdict)}`;
  }

  private evaluationVerdictLabel(verdict?: string | null): string {
    const normalized = String(verdict || '').toLowerCase();
    if (normalized === 'accepted' || normalized === 'valid') return 'validée';
    if (normalized === 'running' || normalized === 'pending') return 'en analyse';
    if (normalized === 'needs_detail' || normalized === 'partial') return 'à préciser';
    if (normalized === 'rejected' || normalized === 'invalid') return 'à reprendre';
    return normalized || 'analysée';
  }

  conversationEventLabel(event: CaptureEvent): string {
    const speaker = (event.speaker || '').toLowerCase();
    if (speaker === 'expert') return `Expert · ${this.transcriptEventShortLabel(event)}`;
    if (speaker === 'system') return `IA · ${this.transcriptEventShortLabel(event)}`;
    if (event.event_type === 'proposal_generated') return 'Rapport · généré';
    if (event.event_type === 'proposal_reviewed') return 'Revue · terminée';
    return `Note · ${this.transcriptEventShortLabel(event)}`;
  }

  conversationStateHeadline(session: CaptureSession): string {
    if (!this.sessionHasStarted(session)) return this.i18n.t('capture.conversation.ready_start');
    if (this.speaking()) return this.i18n.t('capture.conversation.ai_asking');
    if (this.recording()) return this.i18n.t('capture.conversation.expert_answering');
    if (this.transcribing()) return this.i18n.t('capture.conversation.processing');
    if (this.voiceState() === 'oracle_updating') return this.i18n.t('capture.conversation.questions_updated');
    if (this.voiceState() === 'thinking') return this.i18n.t('capture.conversation.organizing');
    if (this.proposal()) return this.i18n.t('capture.conversation.report_ready');
    const step = this.lastConversationStep();
    if (step?.action_taken === 'proposal_deferred_insufficient_facts') {
      return this.i18n.t('capture.conversation.detail_needed');
    }
    return this.conversationMode() === 'conversation_only'
      ? this.i18n.t('capture.conversation.ready')
      : this.i18n.t('capture.conversation.guided_ready');
  }

  conversationStageRows(session: CaptureSession): ConversationStageRow[] {
    const started = this.sessionHasStarted(session);
    const hasAnswer = this.textEvents().some((event) =>
      ['expert_turn_finalized', 'transcript_amended', 'conversation_intent_detected'].includes(event.event_type),
    );
    const proposalActive = Boolean(
      this.lastConversationStep()?.intent?.includes('proposal') ||
      this.lastConversationStep()?.action_taken?.includes('proposal'),
    );
    return [
      {
        id: 'ready',
        label: 'Démarrage',
        detail: started ? this.sessionStartStateLabel(session) : 'en attente',
        icon: 'play',
        state: started ? 'done' : 'active',
      },
      {
        id: 'prompt',
        label: 'Relance',
        detail: this.speaking() ? 'restitution' : this.currentQuestion()?.id || 'sujet sélectionné',
        icon: 'volume-2',
        state: !started ? 'pending' : this.speaking() ? 'active' : 'done',
      },
      {
        id: 'answer',
        label: 'Réponse',
        detail: this.recording() ? 'écoute expert' : this.transcribing() ? 'finalisation transcript' : this.voiceStateLabel(),
        icon: 'mic',
        state: !started
          ? 'pending'
          : (this.recording() || this.transcribing() || this.voiceState() === 'thinking' || this.voiceState() === 'oracle_updating')
            ? 'active'
            : hasAnswer ? 'done' : 'pending',
      },
      {
        id: 'proposal',
        label: 'Rapport',
        detail: this.proposal() ? `${this.proposalFacts().length} fait(s)` : this.lastConversationLabel(),
        icon: 'check-circle-2',
        state: this.proposal() ? 'done' : proposalActive ? 'active' : 'pending',
      },
    ];
  }

  conversationStageClass(row: ConversationStageRow): string {
    const base = 'flex items-center gap-3 rounded border p-3';
    if (row.state === 'done') return `${base} border-emerald-400/20 bg-emerald-500/10`;
    if (row.state === 'active') return `${base} border-brand-400/25 bg-brand-500/10`;
    return `${base} border-white/10 bg-white/[0.03]`;
  }

  setConversationMode(mode: ConversationMode): void {
    const current = this.session();
    if (mode === 'manual' && current && this.isFreeConversationSession(current) && !this.textFallbackActive()) {
      this.conversationMode.set('conversation_only');
      return;
    }
    if (this.conversationMode() === mode) return;
    this.conversationMode.set(mode);
    this.textFallbackActive.set(false);
    this.lastConversationStep.set(null);
    this.stopConversationSession();
  }

  toggleConversationMode(): void {
    this.setConversationMode(this.conversationMode() === 'manual' ? 'conversation_only' : 'manual');
  }

  sessionHasStarted(session: CaptureSession): boolean {
    return session.status !== 'planned';
  }

  showAnswerComposer(session: CaptureSession): boolean {
    if (!this.sessionHasStarted(session)) return false;
    if (this.textFallbackActive()) return true;
    if (this.isFreeConversationSession(session)) return false;
    return this.conversationMode() === 'manual';
  }

  captureAnswerActionLabel(session: CaptureSession): string {
    return this.isFreeConversationSession(session)
      ? 'Enregistrer la réponse'
      : this.i18n.t('capture.action.evaluate_answer');
  }

  sessionStartStateLabel(session: CaptureSession): string {
    if (session.status === 'planned') return this.i18n.t('capture.session.state.not_started');
    if (session.status === 'active') return this.i18n.t('capture.workflow.status.active');
    if (session.status === 'paused') return this.i18n.t('capture.workflow.status.paused');
    if (session.status === 'completed') return this.i18n.t('capture.workflow.status.completed');
    return session.status;
  }

  planStartIcon(_session?: CaptureSession): string {
    return 'mic';
  }

  planStartLabel(_session?: CaptureSession): string {
    return 'Parler';
  }

  conversationPrimaryIcon(): string {
    if (this.conversationMode() !== 'conversation_only') {
      return this.recording() ? 'square' : 'mic';
    }
    // During capture the mic stays open continuously; the primary control
    // pauses it (no relance) rather than ending the turn.
    if (this.recording()) return 'pause';
    if (this.speaking()) return 'pause';
    return 'mic';
  }

  conversationPrimaryLabel(): string {
    if (this.conversationMode() !== 'conversation_only') {
      return this.recording()
        ? 'Pause'
        : this.speaking()
          ? 'Pause'
          : this.transcribing()
            ? 'Transcription'
            : 'Démarrer';
    }
    if (this.transcribing()) return 'Transcription';
    if (this.recording()) return 'Pause micro';
    if (this.speaking()) return 'Pause';
    return 'Parler';
  }

  emptyConversationHint(): string {
    if (this.conversationMode() === 'conversation_only') {
      return 'Démarrez la conversation. Si le micro est refusé, l’IA basculera en saisie guidée.';
    }
    return 'Démarrez la session, puis dictez ou saisissez la réponse expert.';
  }

  lastConversationLabel(): string {
    const step = this.lastConversationStep();
    if (!step) return 'Les actions seront déduites de la prochaine transcription finale.';
    const labels: Record<string, string> = {
      answer_ready: 'Réponse capturée et évaluée',
      correction: 'Correction capturée',
      more_detail: 'Complément capturé',
      proposal_requested: 'Rapport préparé, en attente de confirmation',
      proposal_deferred_insufficient_facts: 'Détail expert nécessaire avant rapport',
      proposal_confirmed: 'Rapport confirmé, validation finale attendue',
      proposal_rejected: 'Rapport rejeté, correction attendue',
      accept_confirmed: 'Rapport accepté',
      accept_rejected: 'Validation suspendue',
    };
    if (step.action_taken === 'proposal_deferred_insufficient_facts') {
      return labels['proposal_deferred_insufficient_facts'];
    }
    return labels[step.intent] || `${step.intent} · ${step.action_taken}`;
  }

  transcriptEventLabel(event: CaptureEvent): string {
    if (event.event_type === 'conversation_intent_detected') {
      return `intention : ${(event.metadata || {})['intent'] || 'détectée'}`;
    }
    if (event.event_type === 'proposal_generated') return 'rapport généré';
    if (event.event_type === 'proposal_reviewed') return 'rapport relu';
    if (event.event_type === 'transcript_amended' || event.text_amended) return 'transcription amendée';
    if (event.event_type === 'expert_turn_finalized') return 'réponse finale';
    if (event.event_type === 'stt_final') return 'transcription finale';
    return 'transcription';
  }

  private transcriptEventShortLabel(event: CaptureEvent): string {
    if (event.event_type === 'conversation_intent_detected') return 'intention';
    if (event.event_type === 'transcript_amended' || event.text_amended) return 'amendé';
    if (event.event_type === 'expert_turn_finalized') return 'réponse finale';
    if (event.event_type === 'stt_final') return 'transcription';
    return 'capturé';
  }

  eventDisplayText(event: CaptureEvent): string {
    if (event.event_type === 'conversation_intent_detected') {
      const factText = String((event.metadata || {})['fact_text'] || '').trim();
      return factText || this.conversationDecisionText(event);
    }
    return (event.text_amended || event.text || event.text_raw || '').trim();
  }

  private isPlanPhaseTranscriptEvent(event: CaptureEvent): boolean {
    if (event.event_type === 'plan_dialogue_turn') return true;
    const phase = String((event.metadata || {})['capture_phase'] || '').trim();
    return phase === 'plan_build';
  }

  private isConversationBusinessDecision(event: CaptureEvent): boolean {
    if (event.event_type !== 'conversation_intent_detected') return false;
    const intent = String((event.metadata || {})['intent'] || '');
    return [
      'proposal_requested',
      'proposal_confirmed',
      'proposal_rejected',
      'accept_confirmed',
      'accept_rejected',
      'session_complete',
    ].includes(intent);
  }

  private conversationDecisionText(event: CaptureEvent): string {
    const intent = String((event.metadata || {})['intent'] || '');
    const labels: Record<string, string> = {
      proposal_requested: 'Demande vocale de rapport',
      proposal_confirmed: 'Rapport confirmé à la voix',
      proposal_rejected: 'Rapport rejeté à la voix',
      accept_confirmed: 'Validation finale confirmée à la voix',
      accept_rejected: 'Validation finale suspendue à la voix',
      session_complete: 'Clôture de session demandée à la voix',
    };
    return labels[intent] || '';
  }

  beginAmend(event: CaptureEvent): void {
    this.editingEventId.set(event.id);
    this.editingText = event.text_amended || event.text || event.text_raw || '';
  }

  applyAmend(sessionId: string, eventId: string): void {
    const text = this.editingText.trim();
    if (!text) return;
    if (!this.canCaptureUpdate(this.session())) {
      this.setVoiceNotice('Votre rôle ne permet pas d’amender cette session de capture.', 'error');
      return;
    }
    this.api
      .amendCaptureEvent(sessionId, eventId, {
        text_amended: text,
        actor: 'demo-operator',
        reason: 'Correction HITL depuis le cockpit de capture.',
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((payload) => {
        const typed = payload as { session?: CaptureSession };
        if (typed.session) {
          this.session.set(typed.session);
        }
        this.editingEventId.set(null);
        this.refreshEvents(sessionId);
      });
  }

  /**
   * Where to land after a capture proposal is generated. Even when reviewer
   * arbitration is disabled, publication remains an explicit operator action.
   */
  private surfaceAfterProposalGeneration(proposal: CaptureProposal | null): CaptureSurfaceView {
    if (proposal?.status === 'published') {
      return 'publish';
    }
    return 'review';
  }

  createProposal(session: CaptureSession): void {
    if (!this.canProposalSubmit(session)) {
      this.setVoiceNotice('Votre rôle ne permet pas de préparer le rapport pour cette session.', 'error');
      return;
    }
    if (this.isFreeConversationSession(session) && session.status === 'active' && !this.textFallbackActive()) {
      this.finishCapture(session);
      return;
    }
    const draft = this.answer.trim();
    if (!draft) {
      this.api
        .createCaptureProposal(session.id)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe((proposal) => {
          this.setProposal(proposal as CaptureProposal);
          this.refreshDashboard();
          this.activeSurface.set(this.surfaceAfterProposalGeneration(proposal as CaptureProposal));
        });
      return;
    }
    this.voiceState.set('thinking');
    this.api
      .addCaptureTurn(session.id, {
        speaker: 'expert',
        text: draft,
        question_id: this.selectedQuestionId(),
        client_turn_id: this.currentClientTurnId,
        retrieval_event_id: this.retrieval().event_id || null,
        interruption_of_event_id: this.interruptionOfEventId(),
        turn_kind: this.interruptionOfEventId() ? 'correction' : 'answer',
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((res) => {
        const typed = res as TurnResponse;
        this.session.set(typed.session);
        this.lastEvaluation.set(typed.evaluation || null);
        this.nextPrompt.set(typed.next_prompt || null);
        this.lastSystemPromptEventId.set(typed.system_prompt_event_id || null);
        this.answer = '';
        this.currentClientTurnId = null;
        this.interruptionOfEventId.set(null);
        this.refreshEvents(typed.session.id);
        this.api
          .createCaptureProposal(typed.session.id)
          .pipe(takeUntilDestroyed(this.destroyRef))
          .subscribe((proposal) => {
            this.setProposal(proposal as CaptureProposal);
            this.refreshDashboard();
            this.activeSurface.set(this.surfaceAfterProposalGeneration(proposal as CaptureProposal));
            this.voiceState.set('idle');
          });
      });
  }

  runConversationStep(session: CaptureSession, text: string): void {
    const clean = text.trim();
    if (!clean) return;
    if (!this.canCaptureExecute(session)) {
      this.setVoiceNotice('Votre rôle ne permet pas d’exécuter la boucle conversationnelle de cette session.', 'error');
      return;
    }
    this.voiceState.set('thinking');
    this.setVoiceNotice('Traitement de la transcription finale et détection de la prochaine action.', 'info');
    this.armConversationProcessingWatchdog();
    this.api
      .runConversationStep(session.id, {
        client_turn_id: this.currentClientTurnId,
        text: clean,
        question_id: this.selectedQuestionId(),
        retrieval_event_id: this.retrieval().event_id || null,
        interruption_of_event_id: this.interruptionOfEventId(),
        last_proposal_id: this.proposal()?.id || null,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (payload) => {
          this.clearConversationProcessingWatchdog();
          const step = payload as ConversationStepResponse;
          this.ingestOraclePayload(payload as Record<string, any>);
          this.lastConversationStep.set(step);
          this.pushRelanceAnnotation(step.relance);
          this.session.set(step.session);
          this.lastEvaluation.set(step.evaluation || null);
          this.nextPrompt.set(step.next_prompt || null);
          this.lastSystemPromptEventId.set(step.system_prompt_event_id || null);
          if (step.next_question_id) {
            this.selectedQuestionId.set(step.next_question_id);
          }
          if (step.proposal) {
            this.setProposal(step.proposal as CaptureProposal);
            if (step.intent === 'proposal_requested') {
              this.activeSurface.set(this.surfaceAfterProposalGeneration(step.proposal as CaptureProposal));
            }
          }
          if (step.closure_sheet?.markdown) {
            this.closureSheetMarkdown.set(step.closure_sheet.markdown);
            this.closurePanelDismissed.set(false);
          } else if (step.confirmation_target === 'session_closure') {
            this.ensureClosureSheet(step.session.id);
            this.closurePanelDismissed.set(false);
          }
          this.currentClientTurnId = null;
          this.interruptionOfEventId.set(null);
          this.refreshEvents(step.session.id);
          if (step.next_prompt) {
            this.speak(this.promptText(step.next_prompt));
          } else {
            this.voiceState.set('idle');
            this.setVoiceNotice('Prêt pour la prochaine réponse expert.', 'info');
            this.scheduleConversationResume();
          }
        },
        error: () => {
          this.clearConversationProcessingWatchdog();
          this.voiceState.set('idle');
          this.setVoiceNotice('Traitement conversationnel impossible. La transcription n’a pas été exploitée.', 'error');
        },
      });
  }

  private applyConversationStepEvent(step: Partial<ConversationStepResponse>): void {
    const session = step.session || this.session();
    if (!session) return;
    const normalized: ConversationStepResponse = {
      intent: String(step.intent || 'answer_ready'),
      confidence: Number(step.confidence ?? 0),
      action_taken: String(step.action_taken || 'none'),
      session,
      proposal: step.proposal || null,
      turn: step.turn || null,
      evaluation: step.evaluation || null,
      next_prompt: step.next_prompt || null,
      next_question_id: step.next_question_id || null,
      system_prompt_event_id: step.system_prompt_event_id || null,
      relance: step.relance || null,
      requires_confirmation: Boolean(step.requires_confirmation),
      confirmation_target: step.confirmation_target || null,
      closure_sheet: step.closure_sheet || null,
    };
    this.ingestOraclePayload(step as Record<string, any>);
    this.lastConversationStep.set(normalized);
    this.pushRelanceAnnotation(normalized.relance);
    this.session.set(session);
    if (normalized.evaluation) {
      this.lastEvaluation.set(normalized.evaluation);
    }
    if (normalized.next_question_id) {
      this.selectedQuestionId.set(normalized.next_question_id);
    }
    if (normalized.proposal) {
      this.setProposal(normalized.proposal as CaptureProposal);
      if (normalized.intent === 'proposal_requested' && !this.captureFinalizing()) {
        this.activeSurface.set('review');
      }
    }
    if (normalized.closure_sheet?.markdown) {
      this.closureSheetMarkdown.set(normalized.closure_sheet.markdown);
      this.closurePanelDismissed.set(false);
    } else if (normalized.confirmation_target === 'session_closure') {
      this.ensureClosureSheet(session.id);
      this.closurePanelDismissed.set(false);
    }
    if (!normalized.next_prompt) {
      this.voiceState.set('idle');
      this.scheduleConversationResume();
    }
  }

  acceptProposal(proposalId: string): void {
    if (!this.canProposalReview(this.proposal())) {
      this.setVoiceNotice('Votre rôle ne permet pas de valider ce rapport.', 'error');
      return;
    }
    this.persistProposalReport(proposalId, () => {
      this.api
        .reviewCaptureProposal(proposalId, {
          status: 'accepted',
          reviewer: 'demo-operator',
          review_notes: 'Validé depuis la démo Capture de connaissances.',
        })
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe((proposal) => {
          this.setProposal(proposal as CaptureProposal);
          this.refreshDashboard();
        });
    });
  }

  continueFromReview(proposal: CaptureProposal): void {
    if (!this.canContinueFromReview(proposal)) {
      this.setVoiceNotice('Relisez le rapport avant de continuer.', 'warning');
      return;
    }
    if (proposal.status === 'accepted') {
      this.activeSurface.set('publish');
      return;
    }
    this.persistProposalReport(proposal.id, () => {
      this.api
        .reviewCaptureProposal(proposal.id, {
          status: 'accepted',
          reviewer: 'demo-operator',
          review_notes: 'Rapport validé avant publication.',
        })
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe((updated) => {
          this.setProposal(updated as CaptureProposal);
          this.syncLocalSessionOpenQuestionCount();
          this.refreshDashboard();
          this.activeSurface.set('publish');
        });
    });
  }

  passReviewLater(): void {
    const proposal = this.proposal();
    const returnToDashboard = () => {
      this.syncLocalSessionOpenQuestionCount();
      this.goSurface('dashboard');
    };
    if (proposal && this.proposalReportDirty()) {
      this.persistProposalReport(proposal.id, returnToDashboard);
      return;
    }
    returnToDashboard();
  }

  saveProposalReport(proposalId: string): void {
    this.persistProposalReport(proposalId, () => this.setVoiceNotice('Rapport enregistré.', 'info'));
  }

  applyProposalInstruction(proposal: CaptureProposal): void {
    const instruction = this.proposalInstructionText.trim();
    const content = this.proposalReportText();
    if (!instruction) {
      this.setVoiceNotice('Ajoutez une consigne de correction avant de l’appliquer.', 'warning');
      return;
    }
    if (!content) {
      this.setVoiceNotice('Le rapport est vide.', 'error');
      return;
    }
    this.proposalInstructionLoading.set(true);
    this.api
      .applyCaptureProposalInstruction(proposal.id, {
        instruction,
        current_content: content,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          const typed = updated as CaptureProposal;
          this.setProposal(typed);
          this.proposalReportDraft = this.proposalReportContent(typed);
          this.proposalReportDirty.set(false);
          this.proposalInstructionText = '';
          this.proposalInstructionLoading.set(false);
          this.refreshDashboard();
          this.setVoiceNotice('Rapport mis à jour.', 'info');
        },
        error: () => {
          this.proposalInstructionLoading.set(false);
          this.setVoiceNotice('Impossible d’appliquer cette consigne pour le moment.', 'error');
        },
      });
  }

  private persistProposalReport(proposalId: string, afterSave?: () => void): void {
    const content = this.proposalReportText();
    if (!content) {
      this.setVoiceNotice('Le rapport est vide.', 'error');
      return;
    }
    if (!this.proposalReportDirty()) {
      afterSave?.();
      return;
    }
    this.proposalReportSaving.set(true);
    this.api
      .updateCaptureProposalContent(proposalId, content)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (proposal) => {
          this.proposalReportDirty.set(false);
          this.setProposal(proposal as CaptureProposal);
          this.proposalReportDraft = this.proposalReportContent(proposal as CaptureProposal);
          this.proposalReportSaving.set(false);
          this.refreshDashboard();
          afterSave?.();
        },
        error: () => {
          this.proposalReportSaving.set(false);
          this.setVoiceNotice('Impossible d’enregistrer le rapport pour le moment.', 'error');
        },
      });
  }

  private proposalReportContent(proposal: CaptureProposal | null): string {
    return (
      proposal?.proposal?.report_markdown ||
      proposal?.proposal?.recommended_ingestion?.content ||
      ''
    ).trim();
  }

  proposalFacts(): ProposalFact[] {
    return (this.proposal()?.proposal?.captured_facts || [])
      .filter((fact) => Boolean(this.proposalFactText(fact)));
  }

  proposalOpenQuestions(): ProposalOpenQuestion[] {
    return (this.proposal()?.proposal?.open_questions || [])
      .filter((question) => Boolean(this.proposalQuestionText(question)));
  }

  proposalReviewQuestions(): ProposalReviewQuestion[] {
    const statuses = this.proposalQuestionStatuses();
    const rank: Record<ProposalQuestionStatus, number> = { open: 0, answered: 2, deferred: 3, invalid: 9 };
    return this.proposalOpenQuestions()
      .map((question, index) => {
        const key = this.proposalQuestionKey(question, index);
        const status = statuses[key] || this.normalizeProposalQuestionStatus(question.status);
        return {
          key,
          question,
          priority: this.proposalQuestionPriority(question),
          status,
        };
      })
      // `invalid` (supprimer) is hidden and excluded from publication.
      .filter((row) => row.status !== 'invalid')
      .sort((a, b) => {
        if (rank[a.status] !== rank[b.status]) return rank[a.status] - rank[b.status];
        return b.priority - a.priority;
      });
  }

  proposalUnresolvedOpenQuestionCount(): number {
    return this.proposalReviewQuestions().filter((row) => row.status === 'open').length;
  }

  proposalPublishableUnresolvedCount(): number {
    return this.proposalReviewQuestions().filter((row) => row.status === 'open' || row.status === 'deferred').length;
  }

  proposalOpenQuestionsLabel(): string {
    const count = this.proposalUnresolvedOpenQuestionCount();
    return this.i18n.t(
      count === 1 ? 'capture.review.open_count_one' : 'capture.review.open_count_many',
      { count },
    );
  }

  private syncLocalSessionOpenQuestionCount(): void {
    const sessionId = this.session()?.id;
    if (!sessionId) return;
    const count = this.proposalUnresolvedOpenQuestionCount();
    this.session.update((current) =>
      current && current.id === sessionId
        ? {
            ...current,
            open_questions_count: count,
            metrics: { ...(current.metrics || {}), open_questions_count: count },
          }
        : current,
    );
    this.dashboardSessions.update((rows) =>
      rows.map((row) =>
        row.id === sessionId
          ? {
              ...row,
              open_questions_count: count,
              metrics: { ...(row.metrics || {}), open_questions_count: count },
            }
          : row,
      ),
    );
  }

  proposalQuestionAnswer(question: ProposalOpenQuestion): string {
    return String(question.answer || question.answered_text || '').trim();
  }

  proposalQuestionText(question: ProposalOpenQuestion): string {
    return (question.follow_up || question.reason || question.gap_id || '').trim();
  }

  proposalQuestionDetail(question: ProposalOpenQuestion): string {
    const followUp = (question.follow_up || '').trim();
    const reason = (question.reason || '').trim();
    if (!followUp || !reason || followUp === reason) return '';
    return reason;
  }

  proposalQuestionPriorityLabel(priority: number): string {
    if (priority >= 3) return 'Priorité haute';
    if (priority >= 2) return 'Priorité moyenne';
    return 'Priorité basse';
  }

  proposalQuestionPriorityClass(priority: number): string {
    if (priority >= 3) {
      return 'rounded bg-red-500/15 px-2 py-0.5 text-[9px] uppercase tracking-wider text-red-100 ring-1 ring-red-300/20';
    }
    if (priority >= 2) {
      return 'rounded bg-amber-500/15 px-2 py-0.5 text-[9px] uppercase tracking-wider text-amber-100 ring-1 ring-amber-300/20';
    }
    return 'rounded bg-white/5 px-2 py-0.5 text-[9px] uppercase tracking-wider text-gray-300 ring-1 ring-white/10';
  }

  useProposalQuestionAsInstruction(question: ProposalOpenQuestion): void {
    const text = this.proposalQuestionText(question);
    if (!text) return;
    const instruction = `Traite cette question ouverte dans le rapport : ${text}`;
    this.proposalInstructionText = this.proposalInstructionText.trim()
      ? `${this.proposalInstructionText.trim()}\n${instruction}`
      : instruction;
    this.setVoiceNotice('Question ajoutée à la consigne de modification.', 'info');
  }

  /** "Laisser ouverte" — keep the question for later / another expert (publishable). */
  deferProposalOpenQuestion(key: string): void {
    this.setProposalOpenQuestionStatus(key, 'deferred');
  }

  restoreProposalOpenQuestion(key: string): void {
    this.setProposalOpenQuestionStatus(key, 'open');
  }

  /** "Invalider / Supprimer" — mark the question invalid: hidden and excluded from publication. */
  invalidateProposalOpenQuestion(key: string): void {
    if (this.answeringQuestionKey() === key) this.cancelProposalQuestionAnswer();
    this.setProposalOpenQuestionStatus(key, 'invalid');
  }

  /** Open the inline answer composer for a single question. */
  beginProposalQuestionAnswer(key: string): void {
    this.answeringQuestionKey.set(key);
    this.questionAnswerDraft = '';
  }

  cancelProposalQuestionAnswer(): void {
    if (this.recording()) this.finishDictation();
    this.answeringQuestionKey.set(null);
    this.questionAnswerDraft = '';
  }

  /** Voice answer: dictate into the answer draft (transcribed-to-text), then submit. */
  async dictateProposalQuestionAnswer(): Promise<void> {
    if (this.recording()) {
      this.finishDictation();
      return;
    }
    await this.beginDictation((text) => {
      this.questionAnswerDraft = text;
    });
  }

  /** Answer a single question (text OR voice) -> answer endpoint -> refresh proposal. */
  submitProposalQuestionAnswer(row: ProposalReviewQuestion, index: number): void {
    const proposal = this.proposal();
    const text = this.questionAnswerDraft.trim();
    if (!proposal || !text || this.questionAnswerLoading()) return;
    if (this.recording()) this.finishDictation();
    // The review list is sorted/filtered: the positional `question-{i}` fallback
    // must be computed against the RAW open_questions order the backend sees.
    const rawIndex = this.proposalOpenQuestions().findIndex((candidate) => candidate === row.question);
    const questionId = this.proposalQuestionId(row.question, rawIndex >= 0 ? rawIndex : index);
    this.questionAnswerLoading.set(true);
    this.api
      .answerCaptureProposalOpenQuestion(proposal.id, questionId, { text })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.questionAnswerLoading.set(false);
          this.answeringQuestionKey.set(null);
          this.questionAnswerDraft = '';
          this.proposalQuestionStatuses.update((current) => ({ ...current, [row.key]: 'answered' }));
          this.setProposal(updated as CaptureProposal);
          this.syncLocalSessionOpenQuestionCount();
          this.setVoiceNotice('Réponse enregistrée. La section concernée a été re-synthétisée.', 'info');
        },
        error: () => {
          this.questionAnswerLoading.set(false);
          this.setVoiceNotice('Réponse non enregistrée pour le moment. Réessayez.', 'error');
        },
      });
  }

  private setProposalOpenQuestionStatus(key: string, status: ProposalQuestionStatus): void {
    const row = this.proposalReviewQuestions().find((candidate) => candidate.key === key);
    const previousStatus = row?.status || this.proposalQuestionStatuses()[key] || 'open';
    this.proposalQuestionStatuses.update((current) => ({ ...current, [key]: status }));
    const proposal = this.proposal();
    if (!proposal || !row) return;
    const index = this.proposalOpenQuestions().findIndex((candidate) => candidate === row.question);
    this.api
      .patchCaptureProposalOpenQuestions(proposal.id, {
        items: [
          {
            question_key: key,
            question_id: this.proposalQuestionId(row.question, index >= 0 ? index : 0),
            question_text: this.proposalQuestionText(row.question),
            status,
          },
        ],
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.setProposal(updated as CaptureProposal);
          this.syncLocalSessionOpenQuestionCount();
        },
        error: () => {
          this.proposalQuestionStatuses.update((current) => ({ ...current, [key]: previousStatus }));
          this.setVoiceNotice('Statut de question non enregistré pour le moment.', 'error');
        },
      });
  }

  private proposalQuestionKey(question: ProposalOpenQuestion, index: number): string {
    return (
      question.question_id ||
      question.id ||
      question.gap_id ||
      question.follow_up ||
      question.reason ||
      `question-${index}`
    );
  }

  private proposalQuestionId(question: ProposalOpenQuestion, index: number): string {
    return question.question_id || question.id || question.gap_id || `question-${index}`;
  }

  private normalizeProposalQuestionStatus(status?: string | null): ProposalQuestionStatus {
    if (status === 'answered') return 'answered';
    if (status === 'invalid' || status === 'dismissed') return 'invalid';
    if (status === 'deferred') return 'deferred';
    return 'open';
  }

  private proposalQuestionPriority(question: ProposalOpenQuestion): number {
    const raw = question.priority ?? question.severity;
    if (typeof raw === 'number' && Number.isFinite(raw)) return Math.max(1, Math.min(3, Math.round(raw)));
    const value = String(raw || '').toLowerCase();
    if (['high', 'haute', 'critical', 'critique', 'urgent', '3'].includes(value)) return 3;
    if (['medium', 'moyenne', 'normal', '2'].includes(value)) return 2;
    if (['low', 'basse', '1'].includes(value)) return 1;
    const text = `${question.follow_up || ''} ${question.reason || ''}`.toLowerCase();
    if (/(sécurité|securite|risque|danger|contradiction|bloquant|validation|conformité|conformite)/.test(text)) return 3;
    if (/(condition|maintenance|procédure|procedure|source|preuve|hypothèse|hypothese)/.test(text)) return 2;
    return 1;
  }

  proposalEvidenceCount(): number {
    return this.proposalFacts().reduce((total, fact) => total + (fact.retrieval_refs?.length || 0), 0);
  }

  proposalFactTrack(index: number, fact: ProposalFact): string {
    return this.proposalFactKey(index, fact);
  }

  proposalFactKey(index: number, fact: ProposalFact): string {
    return fact.id || `${index}:${this.proposalFactText(fact).slice(0, 80)}`;
  }

  proposalFactText(fact: ProposalFact): string {
    return (fact.text || fact.statement || '').trim();
  }

  proposalFactReviewText(index: number, fact: ProposalFact): string {
    return this.proposalFactEdits()[this.proposalFactKey(index, fact)] || this.proposalFactText(fact);
  }

  proposalFactDecision(index: number, fact: ProposalFact): ProposalFactDecision {
    return this.proposalFactDecisions()[this.proposalFactKey(index, fact)] || 'pending';
  }

  proposalFactDecisionLabel(index: number, fact: ProposalFact): string {
    const decision = this.proposalFactDecision(index, fact);
    if (decision === 'accept') return 'accepté';
    if (decision === 'reject') return 'rejeté';
    return 'à relire';
  }

  proposalFactCardClass(index: number, fact: ProposalFact): string {
    const base = 'rounded border p-4';
    const decision = this.proposalFactDecision(index, fact);
    if (decision === 'accept') return `${base} border-emerald-400/30 bg-emerald-500/10`;
    if (decision === 'reject') return `${base} border-red-400/30 bg-red-500/10`;
    return `${base} border-white/10 bg-black/20`;
  }

  setProposalFactDecision(index: number, fact: ProposalFact, decision: ProposalFactDecision): void {
    const key = this.proposalFactKey(index, fact);
    this.proposalFactDecisions.update((current) => ({ ...current, [key]: decision }));
  }

  beginProposalFactEdit(index: number, fact: ProposalFact): void {
    const key = this.proposalFactKey(index, fact);
    this.editingProposalFactKey.set(key);
    this.proposalFactEditText = this.proposalFactReviewText(index, fact);
  }

  saveProposalFactEdit(index: number, fact: ProposalFact): void {
    const key = this.proposalFactKey(index, fact);
    const text = this.proposalFactEditText.trim();
    if (text) {
      this.proposalFactEdits.update((current) => ({ ...current, [key]: text }));
      this.proposalFactDecisions.update((current) => ({ ...current, [key]: 'accept' }));
    }
    this.editingProposalFactKey.set(null);
  }

  cancelProposalFactEdit(): void {
    this.editingProposalFactKey.set(null);
    this.proposalFactEditText = '';
  }

  acceptedProposalFactCount(): number {
    return this.countProposalFactDecision('accept');
  }

  rejectedProposalFactCount(): number {
    return this.countProposalFactDecision('reject');
  }

  private countProposalFactDecision(decision: ProposalFactDecision): number {
    return this.proposalFacts().filter((fact, index) => this.proposalFactDecision(index, fact) === decision).length;
  }

  proposalFactType(fact: ProposalFact): string {
    if (fact.type) return this.proposalFactTypeLabel(fact.type);
    if (fact.turn_kind === 'correction') return 'CORRECTION';
    if (fact.turn_kind === 'complement') return 'DÉTAIL';
    if (fact.amended) return 'AMENDÉ';
    return 'NOUVEAU';
  }

  proposalFactConfidence(fact: ProposalFact): string {
    const value = typeof fact.confidence === 'number' ? fact.confidence : 0.5;
    return `${Math.round(value * 100)}% confiance`;
  }

  private proposalFactTypeLabel(type: string): string {
    const normalized = type.toLowerCase();
    if (normalized === 'update') return 'MISE À JOUR';
    if (normalized === 'detail') return 'DÉTAIL';
    if (normalized === 'correction') return 'CORRECTION';
    if (normalized === 'exception') return 'EXCEPTION';
    if (normalized === 'open') return 'À CLARIFIER';
    if (normalized === 'new') return 'NOUVEAU';
    return type.toUpperCase();
  }

  private async ensureVoiceConnection(session: CaptureSession): Promise<CaptureVoiceConnection | null> {
    if (this.conversationMode() !== 'conversation_only') return null;
    if (this.voiceConnection) return this.voiceConnection;
    if (this.shouldPreferLiveKitTransport(session)) {
      try {
        const connection = await this.livekitConversation.open(session.id, {
          runtime: session.voice_runtime || 'cascade_openai',
          provider: session.voice_runtime || 'cascade_openai',
          transport: 'livekit',
          language: 'fr',
          output_language: 'fr',
          capability: 'voice2voice_interaction',
          context_id: session.context_id || this.contextId || null,
          system_id: session.system_id || this.systemId || null,
          mode: 'conversation_only',
          tandem_oracle: true,
          oracle: this.voiceOracleSessionOptions(),
          surface: 'knowledge_capture',
          publishMicrophone: true,
          dispatchAgent: true,
          requireVoiceGateway: true,
          metadata: {
            capture_domain: this.selectedDomain,
            mode: 'conversation_only',
          },
        });
        this.voiceConnection = connection;
        this.voiceConnection.events$
          .pipe(takeUntilDestroyed(this.destroyRef))
          .subscribe((event) => this.handleVoiceSessionEvent(event));
        this.setVoiceNotice('Session LiveKit prête. Connexion du pont vocal Agentium en cours.', 'info');
        return this.voiceConnection;
      } catch {
        this.voiceConnection = null;
        this.setVoiceNotice('LiveKit indisponible ; bascule sur la session vocale WebSocket.', 'warning');
      }
    }
    return this.ensureBackendVoiceConnection(session);
  }

  private ensureBackendVoiceConnection(session: CaptureSession): VoiceSessionConnection | null {
    try {
      this.voiceConnection = this.voiceSession.open(session.id);
      this.voiceConnection.events$
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe((event) => this.handleVoiceSessionEvent(event));
      this.voiceConnection.start({
        runtime: session.voice_runtime || 'cascade_openai',
        provider: session.voice_runtime || 'cascade_openai',
        transport: 'backend_ws',
        language: 'fr',
        output_language: 'fr',
        capability: 'voice2voice_interaction',
        context_id: session.context_id || this.contextId || null,
        system_id: session.system_id || this.systemId || null,
        mode: 'conversation_only',
        codec: { input: 'webm', channels: 1 },
        tandem_oracle: true,
        oracle: this.voiceOracleSessionOptions(),
      });
      return this.voiceConnection;
    } catch {
      this.voiceConnection = null;
      this.setVoiceNotice('WebSocket vocal indisponible ; bascule sur les tours vocaux HTTP.', 'warning');
      return null;
    }
  }

  private shouldPreferLiveKitTransport(session: CaptureSession): boolean {
    const runtime = String(session.voice_runtime || '').trim().toLowerCase();
    if (runtime === 'livekit' || runtime === 'livekit_agent') return true;
    const settings = this.asRecord(this.workspace.current()?.settings);
    const voiceRuntime = this.asRecord(settings['voice_runtime']);
    const livekit = this.asRecord(settings['livekit']);
    const livekitEnabled =
      voiceRuntime['livekit_enabled'] === true ||
      settings['livekit_enabled'] === true ||
      livekit['enabled'] === true;
    const transport = String(
      voiceRuntime['transport'] ||
        voiceRuntime['default_transport'] ||
        voiceRuntime['realtime_transport'] ||
        livekit['transport'] ||
        livekit['default_transport'] ||
        settings['voice_transport'] ||
        '',
    )
      .trim()
      .toLowerCase();
    return transport === 'livekit' || (livekitEnabled && !transport);
  }

  private closeVoiceConnection(): void {
    this.voiceConnection?.close();
    this.voiceConnection = null;
    this.realtimeSttActive = false;
  }

  private finalizeDeferredStreamingStop(): void {
    const loopStopPayload = this.deferredLoopStopAfterStreamingTurn;
    const shouldFinishCapture = this.deferredCaptureFinishAfterStreamingTurn;
    const shouldClose = this.closeVoiceAfterStreamingTurn;
    this.deferredLoopStopAfterStreamingTurn = null;
    this.deferredCaptureFinishAfterStreamingTurn = false;
    this.closeVoiceAfterStreamingTurn = false;
    if (shouldFinishCapture && this.voiceConnection) {
      if (!this.captureFinalizing()) {
        this.beginCaptureFinalizing();
      }
      this.voiceConnection.captureFinish({ surface: 'knowledge_capture' });
      this.voiceState.set('thinking');
      this.armConversationProcessingWatchdog();
      this.setVoiceNotice('Dernier tour capturé. Préparation de la synthèse finale…', 'info');
      return;
    }
    if (loopStopPayload && this.voiceConnection) {
      this.voiceConnection.loopStop(loopStopPayload);
    }
    if (shouldClose) {
      this.releaseAudioStream();
      this.closeVoiceConnection();
      if (!this.recording() && !this.transcribing()) {
        this.voiceState.set('idle');
      }
    }
  }

  runtimeLabel(runtime?: string | null): string {
    const value = runtime || 'cascade_openai';
    if (this.isPilotMode()) {
      return 'Assistant vocal';
    }
    if (this.isDemoMode()) {
      if (value === 'cascade' || value === 'cascade_openai') return 'Cascade';
      if (value === 'openai_realtime' || value === 'local_realtime' || value === 'realtime_gpu') return 'Realtime';
      if (value === 'local_stt') return 'Transcription';
      if (value === 'local_tts') return 'Synthèse vocale';
      return 'Voix';
    }
    if (value === 'cascade' || value === 'cascade_openai') return 'cascade_openai · batch STT · segmented TTS';
    if (value === 'openai_realtime') return 'openai_realtime · speech-to-speech';
    if (value === 'local_stt') return 'local_stt · open-source STT';
    if (value === 'local_tts') return 'local_tts · open-source TTS';
    if (value === 'local_realtime') return 'local_realtime · local V2V';
    return value;
  }

  voiceRuntimeArchitecture(runtime?: string | null): string {
    if (this.isPilotMode()) return 'Assistant vocal actif';
    const label = this.runtimeLabel(runtime);
    return this.isDemoMode() ? `${label} · conversation assistée` : `${label} · priorité au dernier tour`;
  }

  private voiceSegmentId(payload: Record<string, any>): string {
    // Prefer the server-authoritative turn id. In realtime STT the sidecar mints
    // a fresh turn_id per OpenAI item (several turns per mic-open) and emits BOTH
    // text.partial (turn_id only) and transcript.partial (segment_id == turn_id)
    // for the same partial. Falling back to currentClientTurnId made those two
    // events land under different ids and flip-flop the live row via
    // promoteLiveToPending -> a stale partial paragraph stuck next to the live
    // one (the duplicate rows). turn_id is identical to currentClientTurnId in
    // the batch path, so this is safe there too.
    return String(payload['turn_id'] || payload['segment_id'] || this.currentClientTurnId || 'live-turn');
  }

  private voiceEventTurnId(payload: Record<string, any>): string {
    return String(payload['turn_id'] || payload['segment_id'] || '').trim();
  }

  private voiceEventMatchesCurrentTurn(payload: Record<string, any>): boolean {
    const eventTurnId = this.voiceEventTurnId(payload);
    return Boolean(eventTurnId && this.currentClientTurnId && eventTurnId === this.currentClientTurnId);
  }

  private handleVoiceSessionEvent(event: VoiceSessionEvent): void {
    const payload = event.payload || {};
    // Passive assist contract: any event may carry the oracle snapshot
    // (open questions + live retrieval) and non-blocking suggestions.
    this.ingestOraclePayload(payload);
    if (event.type === 'oracle.questions') {
      // Live grounded questions pushed by the gateway's background task; the
      // ingest above already updated the QUESTIONS IA panel. Nothing else to do.
      return;
    }
    if (event.type === 'session.ready') {
      this.realtimeSttActive = payload['stt_mode'] === 'realtime' || payload['realtime_stt'] === true;
      this.setVoiceNotice(
        this.realtimeSttActive
          ? 'Session vocale realtime prête (transcription gpt-realtime-whisper en direct).'
          : 'Session vocale streaming prête.',
        'info',
      );
      return;
    }
    if (event.type === 'text.partial' || event.type === 'transcript.partial') {
      // Realtime STT: the sidecar owns turn segmentation and streams partials
      // continuously, with its own server turn_id. The frontend's per-turn
      // `recording` flag flips on its own (client VAD / loop rearm) and never
      // matches that server turn_id, so the legacy "!recording -> drop" path
      // froze the live row on a fragment while the SAME server turn kept growing
      // to completion. In realtime, always render the partial; only an explicit
      // `stop` may pre-empt it, and a pending stop/finish still wins.
      if (this.realtimeSttActive) {
        const liveText = String(payload['text'] || '').trim();
        if (!liveText || this.closeVoiceAfterStreamingTurn) return;
        if (this.recording()) {
          const cmd = this.detectCaptureVoiceCommand(liveText);
          if (cmd === 'stop' && this.handleCaptureVoiceCommand(cmd, liveText)) return;
        }
        this.answer = liveText;
        this.setLivePartial(this.voiceSegmentId(payload), liveText);
        this.voiceState.set('partial_transcribing');
        return;
      }
      const recording = this.recording();
      const finalizingSameTurn = !recording && this.transcribing() && this.voiceEventMatchesCurrentTurn(payload);
      // Render partials during active speech, plus late same-turn partials while
      // endpoint STT is finalising. Older-turn partials stay filtered so a stale
      // result never flips committed text back to a live/italic row.
      if ((!recording && !finalizingSameTurn) || (this.closeVoiceAfterStreamingTurn && !finalizingSameTurn)) {
        return;
      }
      // Server-side incremental STT is the single source of truth for live
      // partials: render the subtitle row without coupling it to retrieval.
      const text = String(payload['text'] || '').trim();
      if (text) {
        if (recording) {
          // Only the immediate "stop" command may act on a PARTIAL. end_turn /
          // end_section must wait for the FINAL transcript: acting on a transient
          // partial (e.g. a common filler caught mid-utterance) force-commits the
          // turn early and swallows the live subtitle row.
          const command = this.detectCaptureVoiceCommand(text);
          if (command === 'stop' && this.handleCaptureVoiceCommand(command, text)) {
            return;
          }
        }
        this.answer = text;
        this.setLivePartial(this.voiceSegmentId(payload), text);
        // Keep the live indicator visible during speech; during endpoint
        // finalisation the text can update without changing the loop state.
        if (recording) {
          this.voiceState.set('partial_transcribing');
        }
      }
      return;
    }
    if (event.type === 'text.final') {
      const text = String(payload['text'] || '').trim();
      const emptyFinal = !text || payload['empty'] === true;
      if (emptyFinal) {
        this.clearTranscriptionWatchdog();
        this.transcribing.set(false);
        if (this.closeVoiceAfterStreamingTurn) {
          this.finalizeDeferredStreamingStop();
          return;
        }
        this.voiceState.set('idle');
        this.setVoiceNotice('Aucune parole exploitable détectée. Le micro va se rouvrir.', 'warning');
        this.scheduleConversationResume(this.voiceLoopCooldownMs());
        return;
      }
      const command = this.detectCaptureVoiceCommand(text);
      if (command) {
        // Commit the final transcript BEFORE handling the command: the spoken
        // tail is part of the capture and the live row must leave the
        // italic/in-flight state even when the turn ends on a voice command
        // (previously the tail stayed italic and a pending deferred stop never
        // ran, leaving the UI stuck on "Finalisation du dernier tour…").
        this.answer = text;
        this.setLiveImproved(this.voiceSegmentId(payload), text);
        if (this.handleCaptureVoiceCommand(command, text)) {
          this.clearTranscriptionWatchdog();
          this.transcribing.set(false);
          if (this.closeVoiceAfterStreamingTurn) {
            this.finalizeDeferredStreamingStop();
          }
          return;
        }
      }
      if (text) {
        this.answer = text;
        this.setLiveImproved(this.voiceSegmentId(payload), text);
      }
      this.clearTranscriptionWatchdog();
      this.transcribing.set(false);
      // Continuous capture path: the redesigned backend no longer emits a
      // per-turn `conversation.step`, so entering `thinking` + arming the 60s
      // `armConversationProcessingWatchdog()` here left every turn stuck in the
      // dim/"thinking" state and fired a false "L'analyse prend trop de temps"
      // after 60s. The `thinking` + analysis-watchdog pair is reserved for the
      // explicit finalization flows (section.finish / capture.finish) and the
      // HTTP `runConversationStep` path. Per turn we simply commit the
      // transcript and keep the mic loop running.
      if (this.closeVoiceAfterStreamingTurn) {
        // A stop/finish was requested while this turn was finalising: tear down.
        this.finalizeDeferredStreamingStop();
        return;
      }
      this.voiceState.set('listening');
      this.setVoiceNotice('Tour capturé. Le micro reste ouvert.', 'info');
      // Refresh the event ledger on turn commit (incremental delta) instead of
      // on every retrieval prefetch, which reloaded the full list per partial.
      const committedSession = this.session();
      if (committedSession) this.refreshEvents(committedSession.id);
      this.scheduleConversationResume(this.voiceLoopCooldownMs());
      return;
    }
    if (event.type === 'capture.finalize.progress') {
      // Honest stage events from the heavy FINAL pass: drive the loader.
      const stage = String(payload['stage'] || 'start');
      this.captureFinalizeStage.set({
        stage,
        label: String(payload['label'] || 'Synthèse finale en cours…'),
        section_label: payload['section_label'] ? String(payload['section_label']) : null,
        current: typeof payload['current'] === 'number' ? payload['current'] : null,
        total: typeof payload['total'] === 'number' ? payload['total'] : null,
      });
      if (stage === 'done') {
        // Report is persisted; the proposal-bearing conversation.step lands next.
        // Arm a short fallback so a dropped/late terminal event still opens the
        // report instead of leaving a completed-looking loader hanging.
        this.armCaptureFinalizeDoneFallback();
      }
      return;
    }
    if (event.type === 'conversation.step') {
      this.clearConversationProcessingWatchdog();
      const captureFinished = payload['capture_finished'] === true;
      this.applyConversationStepEvent(payload as Partial<ConversationStepResponse>);
      if (captureFinished) {
        // The restructured report is persisted: release the gate and land on
        // the report screen. Set the proposal straight from this payload too —
        // applyConversationStepEvent early-returns when the session payload is
        // null, which would otherwise leave the gate releasing onto the session
        // screen instead of the report.
        if (payload['proposal']) {
          this.setProposal(payload['proposal'] as CaptureProposal);
        }
        this.endCaptureFinalizing(true);
      }
      this.finalizeDeferredStreamingStop();
      return;
    }
    if (event.type === 'section.active') {
      const suggestion = payload as {
        subtopic_id?: string;
        topic_id?: string;
        confidence?: number;
        manual_locked?: boolean;
      };
      if (!suggestion.manual_locked) {
        this.applyLiveSectionDetection(
          suggestion.subtopic_id,
          suggestion.topic_id,
          Number(suggestion.confidence || 0),
          'section.active',
        );
      }
      return;
    }
    if (event.type === 'evaluation.delta') {
      // Live assist panels (oracle open questions + retrieved passages + suggestions)
      // ride at the top level of this event; ingest them regardless of plan mode.
      this.ingestOraclePayload(payload);
      const sectionSuggestion = payload['section_suggestion'] as
        | { subtopic_id?: string; topic_id?: string; confidence?: number }
        | null
        | undefined;
      if (sectionSuggestion?.subtopic_id) {
        this.applyLiveSectionDetection(
          sectionSuggestion.subtopic_id,
          sectionSuggestion.topic_id,
          Number(sectionSuggestion.confidence || 0),
          'evaluation.delta',
        );
      }
      const nextQuestionId = payload['next_question_id'];
      if (typeof nextQuestionId === 'string' && nextQuestionId) {
        this.selectedQuestionId.set(nextQuestionId);
      }
      if (payload['evaluation']) {
        this.lastEvaluation.set(payload['evaluation'] as TurnResponse['evaluation']);
      }
      if (payload['session']) {
        this.session.set(payload['session'] as CaptureSession);
        this.refreshEvents((payload['session'] as CaptureSession).id);
      }
      const stepPayload = payload['conversation_step'];
      if (stepPayload && typeof stepPayload === 'object') {
        this.applyConversationStepEvent({
          ...(stepPayload as Partial<ConversationStepResponse>),
          session: (payload['session'] as CaptureSession) || (stepPayload as Partial<ConversationStepResponse>).session,
          proposal: payload['proposal'] || (stepPayload as Partial<ConversationStepResponse>).proposal,
          evaluation:
            (payload['evaluation'] as TurnResponse['evaluation']) ||
            (stepPayload as Partial<ConversationStepResponse>).evaluation,
        });
      }
      return;
    }
    if (event.type === 'prompt.next') {
      const prompt = String(payload['text'] || '').trim();
      this.nextPrompt.set(prompt || null);
      const promptEventId = payload['system_prompt_event_id'];
      this.lastSystemPromptEventId.set(typeof promptEventId === 'string' ? promptEventId : null);
      this.setVoiceNotice('Prochaine relance préparée par l’orchestrateur de capture.', 'info');
      return;
    }
    if (event.type === 'oracle.delta' || event.type === 'oracle.superseded') {
      // Silent oracle during capture: these inner-monologue ticks fire on every
      // partial and never carry user-facing questions (open_questions stays 0
      // mid-capture). Flipping `voiceState` to `oracle_updating` + a notice on
      // each one produced a misleading "L'IA prépare une action…" status and
      // churned the UI on every partial. Grounded oracle questions are surfaced
      // through oracle.questions / open_questions panels, never as transcript
      // rows. The snapshot was already ingested at the top of this handler.
      return;
    }
    if (event.type === 'oracle.action') {
      const action = String(payload['action'] || 'action').replace(/_/g, ' ');
      if (payload['action'] === 'hint') {
        const hint: CaptureHint = {
          id: String(payload['oracle_id'] || payload['hint'] || Date.now()),
          hint: String(payload['hint'] || payload['content'] || ''),
          subtopic_id: typeof payload['subtopic_id'] === 'string' ? payload['subtopic_id'] : undefined,
          kb_excerpt: typeof payload['kb_excerpt'] === 'string' ? payload['kb_excerpt'] : undefined,
          source: 'oracle_live',
          priority: 100,
        };
        this.hintStack.update((current) => [hint, ...current.filter((item) => item.id !== hint.id)]);
        this.voiceState.set('listening');
        return;
      }
      this.voiceState.set('thinking');
      this.setVoiceNotice(`Action vocale prête : ${action}.`, 'info');
      return;
    }
    if (event.type === 'capture.hint_pushed') {
      const hint: CaptureHint = {
        id: String(payload['oracle_id'] || Date.now()),
        hint: String(payload['hint'] || payload['content'] || ''),
        subtopic_id: typeof payload['subtopic_id'] === 'string' ? payload['subtopic_id'] : undefined,
        kb_excerpt: typeof payload['kb_excerpt'] === 'string' ? payload['kb_excerpt'] : undefined,
        source: 'oracle_live',
        priority: 100,
      };
      this.hintStack.update((current) => [hint, ...current.filter((item) => item.id !== hint.id)]);
      return;
    }
    if (event.type === 'oracle.commit') {
      this.voiceState.set('thinking');
      this.setVoiceNotice('Dernier tour validé dans la trace de capture.', 'info');
      return;
    }
    if (event.type === 'audio.out') {
      this.playServerAudio(payload);
      return;
    }
    if (event.type === 'runtime.metric') {
      const metric = payload['metric'];
      const value = payload['value_ms'];
      if (metric === 'livekit_agent_dispatched') {
        if (payload['audio_bridge'] === 'voice_gateway_ready') {
          this.setVoiceNotice('Audio prêt pour la capture.', 'info');
        } else if (payload['audio_bridge'] === 'media_observer_ready') {
          this.setVoiceNotice('Audio reçu, bascule en mode secours si nécessaire.', 'warning');
        } else if (payload['audio_bridge'] === 'pending') {
          this.setVoiceNotice('Connexion audio en cours, mode secours disponible.', 'warning');
        }
      }
      if (metric === 'micro_turn' && !this.recording()) {
        this.voiceState.set('oracle_updating');
      }
      // Only attribute latency to the retrieval panel when the metric is actually a
      // retrieval timing. Transcript metrics like `time_to_first_text` must NOT show
      // up as "CONTEXTE RETROUVÉ" latency (that made the panel look active while empty).
      if (typeof metric === 'string' && metric.startsWith('retrieval') && typeof value === 'number') {
        this.retrieval.update((current) => ({ ...current, latency_ms: value }));
      }
      return;
    }
    if (event.type === 'barge_in') {
      this.setVoiceNotice('Interruption prise en compte par la passerelle vocale.', 'info');
      return;
    }
    if (event.type === 'session.error') {
      const code = String(payload['code'] || '');
      const deferredStop = Boolean(this.deferredLoopStopAfterStreamingTurn || this.closeVoiceAfterStreamingTurn);
      this.clearConversationProcessingWatchdog();
      this.transcribing.set(false);
      this.voiceState.set('idle');
      if (this.captureFinalizing()) {
        // The finalization transport failed: release the gate instead of
        // trapping the user on the loader (the REST closure proposal, if any,
        // is still shown).
        this.endCaptureFinalizing(true);
      }
      this.setVoiceNotice(String(payload['message'] || 'Session vocale streaming indisponible.'), 'error');
      this.finalizeDeferredStreamingStop();
      if (!deferredStop && code === 'synthesize_failed' && this.nextPrompt()) {
        this.speak(this.promptText(this.nextPrompt()));
      }
    }
  }

  private playServerAudio(payload: Record<string, any>): void {
    const b64 = String(payload['audio_base64'] || '');
    if (!b64) {
      this.scheduleConversationResume();
      return;
    }
    this.stopSpeech(false);
    this.speaking.set(true);
    this.voiceState.set('speaking');
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
      bytes[i] = binary.charCodeAt(i);
    }
    const blob = new Blob([bytes], { type: String(payload['content_type'] || 'audio/mpeg') });
    const url = URL.createObjectURL(blob);
    this.revokedAudioUrls.push(url);
    const audio = new Audio(url);
    this.activeAudio = audio;
    audio.onended = () => {
      this.speaking.set(false);
      this.voiceState.set('idle');
      this.cleanupAudioUrls();
      this.scheduleConversationResume();
    };
    audio.onerror = () => {
      this.setVoiceNotice('Lecture audio streaming impossible ; ouverture du micro à la place.', 'warning');
      this.speaking.set(false);
      this.voiceState.set('idle');
      this.scheduleConversationResume();
    };
    void audio.play().catch(() => {
      this.setVoiceNotice('Le navigateur bloque la lecture audio ; ouverture du micro à la place.', 'warning');
      this.speaking.set(false);
      this.voiceState.set('idle');
      this.scheduleConversationResume();
    });
  }

  private voiceFrameMeta(reason: CaptureEndpointReason | null = null): {
    turn_id: string | null;
    question_id: string | null;
    retrieval_event_id: string | null;
    interruption_of_event_id: string | null;
    content_type: string;
    auto?: boolean;
    reason?: string | null;
    capture_mode?: VoiceCaptureMode;
    silence_ms?: number;
    min_speech_ms?: number;
    rms_threshold?: number;
    endpoint_grace_ms?: number;
  } {
    const autoEndpoint = reason != null && reason !== 'manual';
    const captureConfig = this.resolvedVoiceCaptureConfig();
    return {
      turn_id: this.currentClientTurnId,
      question_id: this.selectedQuestionId(),
      retrieval_event_id: this.retrieval().event_id || null,
      interruption_of_event_id: this.interruptionOfEventId(),
      content_type: 'audio/webm',
      auto: autoEndpoint,
      reason,
      capture_mode: captureConfig.capture_mode,
      silence_ms: captureConfig.silence_ms,
      min_speech_ms: captureConfig.min_speech_ms,
      rms_threshold: captureConfig.rms_threshold,
      endpoint_grace_ms: captureConfig.endpoint_grace_ms,
    };
  }

  async toggleRecording(): Promise<void> {
    if (this.recording()) {
      this.endpointRecordingTurn('manual');
      return;
    }
    if (this.speaking()) {
      this.interruptSpeech();
    }
    const armed = await this.ensureAudioStream();
    if (!armed) {
      this.voiceState.set('idle');
      return;
    }
    this.resetHttpBatchRecordingBuffers();
    this.currentClientTurnId = this.newTurnId();
    this.commandHandledForTurn = null;
    this.lastPrefetchText = '';
    this.lastPrefetchAt = 0;
    this.startAudioRecorder('Micro ouvert. Arrêtez l’écoute quand la réponse expert est complète.');
  }

  async toggleConversationSession(): Promise<void> {
    if (this.recording()) {
      this.endpointRecordingTurn('manual');
      return;
    }
    if (this.speaking()) {
      this.interruptSpeech();
      this.conversationSessionActive.set(true);
      await this.startRecordingTurn();
      return;
    }
    if (this.conversationSessionActive()) {
      await this.startRecordingTurn();
      return;
    }
    const session = this.session();
    const connection = session ? await this.ensureVoiceConnection(session) : null;
    const captureConfig = this.resolvedVoiceCaptureConfig();
    this.conversationSessionActive.set(true);
    // Realtime: re-enable/publish the LiveKit mic before ensureAudioStream() grabs
    // its own getUserMedia, so a resume after pause restores real audio (not a
    // muted/silent track) — same device order as the initial connect.
    if (this.realtimeSttActive && connection && 'enableMicrophone' in connection) {
      await connection.enableMicrophone(true);
    }
    connection?.loopStart({
      surface: 'knowledge_capture',
      mode: 'conversation_loop',
      auto_endpoint: captureConfig.auto_endpoint,
      capture_mode: captureConfig.capture_mode,
      auto_rearm_after_tts: this.voiceLoopAutoRearmEnabled(),
      barge_in: this.voiceLoopBargeInEnabled(),
      silence_ms: captureConfig.silence_ms,
      min_speech_ms: captureConfig.min_speech_ms,
      rms_threshold: captureConfig.rms_threshold,
      endpoint_grace_ms: captureConfig.endpoint_grace_ms,
      max_turn_ms: captureConfig.max_turn_ms,
    });
    this.setVoiceNotice('Préparation du micro pour la conversation.', 'info');
    const armed = await this.ensureAudioStream();
    if (!armed) {
      this.conversationSessionActive.set(false);
      this.voiceState.set('idle');
      this.conversationMode.set('manual');
      this.textFallbackActive.set(true);
      this.setVoiceNotice('Micro indisponible : bascule en saisie guidée pour continuer la session.', 'warning');
      return;
    }
    this.textFallbackActive.set(false);
    const firstPrompt = this.spokenSectionPrompt();
    if (firstPrompt && !(session && (this.isFreeConversationSession(session) || this.isTopicOnlyPlan(session)))) {
      this.speak(firstPrompt);
      return;
    }
    await this.startRecordingTurn();
  }

  currentQuestion(): CaptureQuestion | null {
    const session = this.session();
    const questionId = this.selectedQuestionId();
    if (!session || !questionId) {
      return this.planQuestions(session)[0] || null;
    }
    return this.planQuestions(session).find((question) => question.id === questionId) || null;
  }

  readCurrentQuestion(): void {
    const prompt = this.spokenSectionPrompt();
    if (prompt) {
      this.speak(prompt);
    }
  }

  currentQuestionPosition(session: CaptureSession): number {
    const questionId = this.selectedQuestionId();
    const questions = this.planQuestions(session);
    const index = questions.findIndex((question) => question.id === questionId);
    return index >= 0 ? index + 1 : Math.min(questions.length, 1);
  }

  visibleQuestionStack(session: CaptureSession): CaptureQuestion[] {
    const questions = this.planQuestions(session);
    if (questions.length <= 5) return questions;
    const selected = this.selectedQuestionId();
    const selectedIndex = Math.max(
      0,
      questions.findIndex((question) => question.id === selected),
    );
    const start = Math.max(0, Math.min(selectedIndex - 1, questions.length - 5));
    return questions.slice(start, start + 5);
  }

  captureProgressLabel(session: CaptureSession): string {
    if (this.isFreeConversationSession(session)) return this.i18n.t('capture.progress.free');
    const total = this.planQuestions(session).length;
    if (!total) {
      const topics = this.planTopics(session).length;
      return topics
        ? this.i18n.t(topics === 1 ? 'capture.progress.topics_one' : 'capture.progress.topics_many', { count: topics })
        : this.i18n.t('capture.progress.no_plan');
    }
    return `${this.currentQuestionPosition(session)}/${total}`;
  }

  planDurationMinutes(session: CaptureSession): number {
    // The estimated duration set on the setup form is authoritative for the plan.
    const stored = Number(session.duration_minutes || 0);
    if (stored > 0) return stored;
    // Fallback for question-based plans: sum the per-question estimates.
    const questions = this.planQuestions(session);
    return questions.reduce((total, question) => total + (question.estimated_minutes || 3), 0);
  }

  questionStateLabel(session: CaptureSession, question: CaptureQuestion): string {
    const questions = this.planQuestions(session);
    const selected = this.selectedQuestionId();
    const selectedIndex = questions.findIndex((item) => item.id === selected);
    const questionIndex = questions.findIndex((item) => item.id === question.id);
    if (question.id === selected) return this.i18n.t('capture.question.status.current');
    if (selectedIndex >= 0 && questionIndex >= 0 && questionIndex < selectedIndex) {
      return this.i18n.t('capture.question.status.covered');
    }
    return this.i18n.t('capture.question.status.upcoming');
  }

  voiceWaveHeight(base: number): number {
    if (this.recording()) return base;
    if (this.speaking()) return Math.max(8, Math.round(base * 0.75));
    if (
      this.transcribing() ||
      this.voiceState() === 'thinking' ||
      this.voiceState() === 'retrieving' ||
      this.voiceState() === 'oracle_updating'
    ) {
      return Math.max(6, Math.round(base * 0.45));
    }
    return 6;
  }

  planDictationWaveHeight(base: number): number {
    if (!this.planDictationListening()) {
      return Math.max(6, Math.round(base * 0.45));
    }
    const level = this.dictationAudioLevel();
    const boost = 0.35 + level * 0.65;
    return Math.max(6, Math.round(base * boost));
  }

  planDictationStatusLabel(): string {
    if (this.planDictationTranscribing()) return this.i18n.t('capture.plan.dictation.transcribing');
    if (this.dictationSilenceEnding()) return this.i18n.t('capture.plan.dictation.silence_stop');
    if (this.voiceState() === 'partial_transcribing' && this.recording()) {
      return this.i18n.t('capture.plan.dictation.partial');
    }
    if (this.dictationVoiceDetected()) return this.i18n.t('capture.plan.dictation.voice_detected');
    return this.i18n.t('capture.plan.dictation.listening');
  }

  voiceInputStatusLabel(): string {
    if (this.recording()) return 'Écoute de la réponse expert';
    if (this.transcribing()) return 'Finalisation de la transcription';
    if (this.speaking()) return 'L’IA parle';
    if (this.voiceState() === 'retrieving') return 'Préparation de repères';
    if (this.voiceState() === 'oracle_updating') return 'Questions IA mises à jour';
    if (this.voiceState() === 'thinking') return 'Organisation des notes';
    if (this.conversationMode() === 'conversation_only' && this.conversationSessionActive()) {
      return 'Conversation prête';
    }
    return this.conversationMode() === 'conversation_only' ? 'Prêt à écouter' : 'Prêt pour la capture';
  }

  voiceNoticeClass(): string {
    const base = 'text-[10px] leading-snug';
    const tone = this.voiceNoticeTone();
    if (tone === 'error') return `${base} text-red-300`;
    if (tone === 'warning') return `${base} text-amber-200`;
    return `${base} text-brand-200`;
  }

  voiceNoticePanelClass(): string {
    const base = 'mt-3 rounded border px-3 py-2 text-xs leading-relaxed';
    const tone = this.voiceNoticeTone();
    if (tone === 'error') return `${base} border-red-400/20 bg-red-500/10 text-red-200`;
    if (tone === 'warning') return `${base} border-amber-400/20 bg-amber-500/10 text-amber-100`;
    return `${base} border-brand-400/20 bg-brand-500/10 text-brand-100`;
  }

  private setVoiceNotice(message: string | null, tone: VoiceNoticeTone = 'info'): void {
    this.voiceNotice.set(message);
    this.voiceNoticeTone.set(tone);
  }

  private voiceLoopSettingNumber(key: keyof WorkspaceVoiceLoopConfig, fallback: number, min: number, max: number): number {
    const value = Number(this.workspaceVoiceLoopConfig()[key]);
    if (!Number.isFinite(value)) return fallback;
    return Math.min(max, Math.max(min, Math.round(value)));
  }

  private voiceEndpointSilenceMs(): number {
    // Continuous capture: a turn should only auto-close on a very long silence,
    // never on the short conversational pauses an expert makes while thinking.
    return this.resolvedVoiceCaptureConfig().silence_ms;
  }

  private dictationEndpointSilenceMs(): number {
    // Plan/prep dictation: stop soon after the user finishes speaking (unlike capture turns).
    return this.resolvedVoiceCaptureConfig().dictation_silence_ms;
  }

  private dictationEndpointMinSpeechMs(): number {
    return this.resolvedVoiceCaptureConfig().dictation_min_speech_ms;
  }

  private voiceEndpointMinSpeechMs(): number {
    return this.resolvedVoiceCaptureConfig().min_speech_ms;
  }

  private voiceEndpointMaxTurnMs(): number {
    return this.resolvedVoiceCaptureConfig().max_turn_ms;
  }

  private voiceOracleSessionOptions(): {
    min_interval_ms: number;
    min_delta_chars: number;
    partial_stt_min_interval_ms: number;
    live_partial_stt_enabled: boolean;
    live_questions_enabled: boolean;
  } {
    const config = this.workspaceVoiceLoopConfig();
    return {
      min_interval_ms: 300,
      min_delta_chars: 20,
      partial_stt_min_interval_ms: this.voiceLoopSettingNumber('partial_stt_min_interval_ms', 1200, 0, 120000),
      live_partial_stt_enabled: config.live_partial_stt_enabled !== false,
      live_questions_enabled: config.live_questions_enabled !== false,
    };
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

  private voiceLoopAutoEndpointEnabled(): boolean {
    return this.resolvedVoiceCaptureConfig().auto_endpoint;
  }

  voiceCaptureModeHint(): string {
    const config = this.resolvedVoiceCaptureConfig();
    if (config.capture_mode === 'manual_safe') return 'Mode manuel: le micro ne coupe pas automatiquement sur silence.';
    if (config.capture_mode === 'robust') return `Mode robuste: silence ${config.silence_ms} ms, parole min ${config.min_speech_ms} ms.`;
    return 'Mode normal: utilise les réglages voix du workspace.';
  }

  setVoiceCaptureMode(mode: VoiceCaptureMode | string): void {
    const next = normalizeVoiceCaptureMode(mode);
    this.voiceCaptureMode.set(next);
    try {
      const workspaceSlug = this.workspace.current()?.slug || this.workspace.currentSlug() || 'workspace';
      localStorage.setItem(
        voiceCaptureStorageKey({ surface: 'knowledge_capture', workspaceSlug, profileKey: 'capture' }),
        next,
      );
    } catch {
      /* local preference only */
    }
    if (next === 'manual_safe') {
      this.stopCaptureEndpointMonitor();
      this.stopDictationAudioMonitor();
      this.setVoiceNotice('Mode capture manuel activé : terminez les tours au bouton micro.', 'info');
    } else if (next === 'robust') {
      this.setVoiceNotice('Mode capture robuste activé pour ce workspace.', 'info');
    }
  }

  private readStoredVoiceCaptureMode(key: string, fallback: VoiceCaptureMode): VoiceCaptureMode {
    try {
      return normalizeVoiceCaptureMode(localStorage.getItem(key), fallback);
    } catch {
      return fallback;
    }
  }

  speak(text: string): void {
    const clean = text.trim();
    if (!clean) {
      return;
    }
    this.setVoiceNotice('Préparation de la lecture. Vous pouvez interrompre et répondre à tout moment.', 'info');
    this.stopSpeech(false);
    this.ttsPlayback.playText(clean, {
      surface: 'knowledge_capture',
      provider: this.session()?.voice_runtime || 'cascade_openai',
      config: this.workspaceVoiceOutputConfig(),
      onState: (state) => this.syncCaptureTtsState(state),
      onStarted: (metric) => {
        this.voiceConnection?.ttsStarted({
          surface: 'knowledge_capture',
          latency_profile: metric.latency_profile,
          time_to_first_audio_ms: metric.time_to_first_audio_ms,
        });
        this.setVoiceNotice('L’IA lit la relance. Vous pouvez interrompre et répondre à tout moment.', 'info');
      },
      onEnded: (metric) => {
        this.voiceConnection?.ttsEnded({
          surface: 'knowledge_capture',
          duration_ms: metric.duration_ms,
          time_to_first_audio_ms: metric.time_to_first_audio_ms,
        });
        this.scheduleConversationResume();
      },
      onInterrupted: (reason) => {
        this.voiceConnection?.ttsInterrupted({ surface: 'knowledge_capture', reason });
      },
      onNotice: (message, tone) => {
        if (message) this.setVoiceNotice(message, tone || 'info');
      },
    });
    this.scheduleConversationResume(this.conversationResumeFallbackDelay(clean), true);
  }

  interruptSpeech(): void {
    const promptEventId = this.lastSystemPromptEventId();
    this.stopSpeech(true);
    this.voiceConnection?.bargeIn(promptEventId);
    this.interruptionOfEventId.set(promptEventId || 'client-interruption');
    this.voiceState.set('interrupted');
  }

  /**
   * The explicit STOP the user asked for on the capture surface: immediately cut
   * any TTS voice-out and hard-stop the conversation loop so it does not
   * auto-rearm. Any in-flight recording is torn down without being submitted;
   * the on-screen draft answer is kept.
   */
  stopConversation(): void {
    this.clearAutoResumeTimer();
    this.conversationSessionActive.set(false);
    // Re-entrancy guard: a stop is already finalising (e.g. voice-command stop
    // followed by a manual click, or a click while a VAD endpoint's text.final
    // is in flight). Tearing the connection down here would kill the pending
    // endpoint/final and leave `transcribing` stuck on "Finalisation de la
    // transcription" until the 45s watchdog. Defer to the in-flight completion.
    if (this.closeVoiceAfterStreamingTurn || (this.transcribing() && this.voiceConnection)) {
      this.closeVoiceAfterStreamingTurn = true;
      if (!this.deferredLoopStopAfterStreamingTurn) {
        this.deferredLoopStopAfterStreamingTurn = { surface: 'knowledge_capture', reason: 'user_stop' };
      }
      this.setVoiceNotice('Conversation arrêtée. Finalisation du dernier tour…', 'info');
      return;
    }
    this.captureEndpointReason = 'stop';
    this.stopCaptureEndpointMonitor();
    this.stopSpeech(false);
    // Capture the recording state BEFORE tearing the recorder down: it decides
    // whether a turn is still in flight and must be flushed to the backend.
    const wasRecording = this.recording();
    // Stop the local recorder WITHOUT its own onstop endpoint; we submit the
    // buffered turn explicitly below so the last round is committed (upright)
    // and persisted instead of being silently dropped while still "live".
    if (this.recorder) {
      try {
        this.recorder.onstop = null;
      } catch {
        /* browser cleanup only */
      }
      try {
        if (this.recorder.state !== 'inactive') this.recorder.stop();
      } catch {
        /* browser cleanup only */
      }
      this.recorder = null;
    }
    // If a turn was being recorded, its buffered audio may not yet have produced
    // a `text.final` (the partial-STT cadence can lag the stop click by seconds,
    // and the final partial often lands in the same tick as the click). Gating on
    // `wasRecording` — NOT on the live-slot status — flushes a final endpoint so
    // the backend transcribes + persists the last round and emits `text.final`
    // (which commits the tail upright). Teardown is deferred until it lands.
    if (wasRecording && this.voiceConnection) {
      const live = this.liveTranscript();
      if (live && live.status === 'live' && !this.isTrivialTranscriptSegment(live.text)) {
        this.setLiveImproved(live.id, live.text);
      }
      this.recording.set(false);
      this.closeVoiceAfterStreamingTurn = true;
      this.deferredLoopStopAfterStreamingTurn = { surface: 'knowledge_capture', reason: 'user_stop' };
      this.releaseAudioStream();
      void this.finishStreamingVoiceTurn('stop');
      this.setVoiceNotice('Conversation arrêtée. Finalisation du dernier tour…', 'info');
      return;
    }
    this.recording.set(false);
    this.deferredLoopStopAfterStreamingTurn = null;
    this.deferredCaptureFinishAfterStreamingTurn = false;
    this.closeVoiceAfterStreamingTurn = false;
    this.voiceConnection?.loopStop({ surface: 'knowledge_capture', reason: 'user_stop' });
    this.releaseAudioStream();
    this.closeVoiceConnection();
    this.voiceState.set('idle');
    this.setVoiceNotice('Conversation arrêtée. La lecture vocale a été coupée.', 'info');
  }

  /** Primary capture control: open the mic when idle, pause it (no relance) while
   * recording. Pausing must NOT end the turn or trigger a conversation step. */
  onPrimaryCaptureAction(session: CaptureSession): void {
    if (this.conversationMode() === 'conversation_only') {
      if (this.recording()) {
        this.pauseMicrophone();
        return;
      }
      void this.toggleConversationSession();
      return;
    }
    void this.toggleRecording();
  }

  /**
   * "Pause micro" — stop sending audio frames and close the mic locally without
   * ending the turn. Sends audio.pause so the backend keeps the section open and
   * does NOT emit any relance or conversation step. Resume via the primary button.
   */
  pauseMicrophone(): void {
    this.clearAutoResumeTimer();
    this.deferredLoopStopAfterStreamingTurn = null;
    this.deferredCaptureFinishAfterStreamingTurn = false;
    this.closeVoiceAfterStreamingTurn = false;
    this.captureEndpointReason = 'stop';
    this.stopCaptureEndpointMonitor();
    this.stopSpeech(false);
    // Deterministic pause ordering (fix 24a345): stop the recorder FIRST so its
    // final ondataavailable flush is sent as a normal audio.frame, and only THEN
    // send audio.pause. The stop event fires AFTER the last dataavailable, so by
    // the time onstop runs the tail frame's send promise is already in
    // pendingVoiceFrameSends; draining those sends before audioPause guarantees
    // the backend flushes a segment that includes the tail and that no frame
    // arrives after the flush (a late headerless frame used to poison the next
    // buffer and 400 every STT call for the rest of the session).
    const recorder = this.recorder;
    this.recorder = null;
    const sendPauseAfterTail = () => {
      void Promise.allSettled(this.pendingVoiceFrameSends).then(() => {
        this.voiceConnection?.audioPause({ surface: 'knowledge_capture' });
      });
    };
    if (recorder && recorder.state !== 'inactive') {
      try {
        recorder.onstop = () => {
          // The final flush frame was already handed to ondataavailable; make
          // sure nothing else from this recorder is ever sent.
          try {
            recorder.ondataavailable = null;
          } catch {
            /* browser cleanup only */
          }
          sendPauseAfterTail();
        };
        recorder.stop();
      } catch {
        /* browser cleanup only — still notify the backend of the pause */
        sendPauseAfterTail();
      }
    } else {
      sendPauseAfterTail();
    }
    this.recording.set(false);
    // Commit the in-flight tail (italic -> upright). The backend keeps the audio
    // buffer open across a pause, so resuming continues the same turn — no data
    // loss — but the visible transcript must not stay stuck in the "live" italic
    // state once the mic is paused.
    const live = this.liveTranscript();
    if (live && live.status === 'live' && !this.isTrivialTranscriptSegment(live.text)) {
      this.setLiveImproved(live.id, live.text);
    }
    // Keep the streaming connection open so the user can resume the same section.
    this.conversationSessionActive.set(false);
    this.releaseAudioStream();
    this.voiceState.set('idle');
    this.setVoiceNotice('Micro en pause. Aucune relance déclenchée — reprenez quand vous voulez.', 'info');
  }

  /** When no subtopic is selected yet, default to the first subtopic of the first topic. */
  private ensureDefaultPlanSection(session: CaptureSession): void {
    if (this.isFreeConversationSession(session)) return;
    if (this.activeSubtopicId()) return;
    const topics = this.planTopics(session);
    const firstTopic = topics[0];
    if (!firstTopic) return;
    if (!(firstTopic.subtopics || []).length) {
      this.navigateCaptureSection(firstTopic.id, {
        manual: false,
        topicId: firstTopic.id,
        syncVoice: false,
      });
      return;
    }
    const firstSubtopic = (firstTopic.subtopics || [])[0];
    if (!firstSubtopic) return;
    this.navigateCaptureSection(firstSubtopic.id, {
      manual: false,
      topicId: firstTopic.id,
      syncVoice: false,
    });
  }

  /** Resolve the active section (topic/subtopic) for section.select / section.finish. */
  private activeSectionRef(session: CaptureSession): { topic_id?: string; subtopic_id?: string } {
    const topics = this.planTopics(session);
    const subtopicId = this.activeSubtopicId();
    if (subtopicId) {
      const topic = topics.find((t) => (t.subtopics || []).some((st) => st.id === subtopicId));
      return { topic_id: topic?.id, subtopic_id: subtopicId };
    }
    const question = this.currentQuestion();
    if (question?.subtopic_id) {
      const topic =
        topics.find((t) => (t.subtopics || []).some((st) => st.id === question.subtopic_id)) ||
        topics.find((t) => t.id === question.topic_id);
      return { topic_id: topic?.id || question.topic_id, subtopic_id: question.subtopic_id };
    }
    if (question?.topic_id) {
      const topic = topics.find((t) => t.id === question.topic_id);
      const firstSubtopic = topic?.subtopics?.[0];
      if (firstSubtopic) {
        return { topic_id: question.topic_id, subtopic_id: firstSubtopic.id };
      }
      return { topic_id: question.topic_id };
    }
    const firstTopic = topics[0];
    if (firstTopic) {
      const firstSubtopic = (firstTopic.subtopics || [])[0];
      if (firstSubtopic) {
        return { topic_id: firstTopic.id, subtopic_id: firstSubtopic.id };
      }
      return { topic_id: firstTopic.id };
    }
    return {};
  }

  /** Flat list of plan sections (topics + subtopics) for the jump selector. */
  captureSectionOptions(session: CaptureSession): Array<{ value: string; label: string }> {
    if (this.isFreeConversationSession(session)) return [];
    const options: Array<{ value: string; label: string }> = [];
    for (const topic of this.planTopics(session)) {
      const topicTitle = (topic.title || 'Sujet').trim();
      options.push({ value: topic.id, label: topicTitle });
      for (const subtopic of topic.subtopics || []) {
        const subTitle = (subtopic.title || 'Sous-sujet').trim();
        options.push({ value: `${topic.id}|${subtopic.id}`, label: `   ↳ ${subTitle}` });
      }
    }
    return options;
  }

  currentSectionValue(): string {
    const session = this.session();
    if (!session) return '';
    const ref = this.activeSectionRef(session);
    if (ref.subtopic_id && ref.topic_id) return `${ref.topic_id}|${ref.subtopic_id}`;
    return ref.topic_id || '';
  }

  /** Resolve the current plan position (topic + subtopic with their indexes). */
  private currentPlanPosition(session: CaptureSession): {
    topic: CaptureTopic | null;
    topicIndex: number;
    subtopic: { id: string; title?: string } | null;
    subtopicIndex: number;
  } {
    const topics = this.planTopics(session);
    if (!topics.length) return { topic: null, topicIndex: -1, subtopic: null, subtopicIndex: -1 };
    const ref = this.activeSectionRef(session);
    let topicIndex = topics.findIndex((topic) => topic.id === ref.topic_id);
    if (topicIndex < 0) topicIndex = 0;
    const topic = topics[topicIndex];
    const subtopics = topic.subtopics || [];
    const subtopicIndex = ref.subtopic_id
      ? subtopics.findIndex((subtopic) => subtopic.id === ref.subtopic_id)
      : -1;
    return {
      topic,
      topicIndex,
      subtopic: subtopicIndex >= 0 ? subtopics[subtopicIndex] : null,
      subtopicIndex,
    };
  }

  /** One-line breadcrumb of the CURRENT plan position, e.g.
   *  "1. Maintenance des rouleaux › 1.1 Inspection et alignement". */
  captureBreadcrumb(session: CaptureSession): string | null {
    const { topic, topicIndex, subtopic, subtopicIndex } = this.currentPlanPosition(session);
    if (!topic) return null;
    let label = `${topicIndex + 1}. ${(topic.title || 'Sujet').trim()}`;
    if (subtopic) {
      label += ` › ${topicIndex + 1}.${subtopicIndex + 1} ${(subtopic.title || 'Sous-sujet').trim()}`;
    }
    return label;
  }

  /** Fixed spoken position label for Lire / loop-start (no question text appended). */
  private spokenSectionPrompt(): string | null {
    const session = this.session();
    if (!session || this.isFreeConversationSession(session)) {
      return this.currentPromptText();
    }
    const { topic, subtopic } = this.currentPlanPosition(session);
    const topicTitle = (topic?.title || '').trim();
    const subtopicTitle = (subtopic?.title || '').trim();
    if (subtopicTitle && !this.sectionTitlesAreRedundant(topicTitle, subtopicTitle)) {
      return this.i18n.t('capture.spoken.subsection', { title: subtopicTitle });
    }
    if (topicTitle) {
      return this.i18n.t('capture.spoken.section', { title: topicTitle });
    }
    return null;
  }

  private sectionTitlesAreRedundant(parentTitle: string, childTitle: string): boolean {
    const normalize = (value: string) =>
      value
        .toLowerCase()
        .trim()
        .replace(/^\d+(\.\d+)*\s*/, '');
    const parent = normalize(parentTitle);
    const child = normalize(childTitle);
    if (!child) return true;
    if (!parent) return false;
    if (parent === child) return true;
    if (child.includes(parent) || parent.includes(child)) return true;
    return false;
  }

  /** Jump directly to any topic/subtopic. Sends section.select; keeps the mic open. */
  onCaptureSectionSelect(value: string): void {
    if (!value) return;
    const [topicId, subtopicId] = value.split('|');
    if (subtopicId) {
      this.navigateCaptureSection(subtopicId, { manual: true, topicId: topicId || null });
    } else {
      const session = this.session();
      const topic = session ? this.planTopics(session).find((t) => t.id === topicId) : null;
      if (topic && !(topic.subtopics || []).length) {
        this.navigateCaptureSection(topic.id, { manual: true, topicId: topic.id });
        return;
      }
      const firstSubtopic = topic?.subtopics?.[0];
      if (firstSubtopic) {
        this.navigateCaptureSection(firstSubtopic.id, { manual: true, topicId: topicId || null });
      }
    }
    this.setVoiceNotice('Section sélectionnée. Le micro reste ouvert sur cette section.', 'info');
  }

  /**
   * "Terminer la section" — the ONLY action that triggers the timeline relance
   * ("avez-vous terminé ? / souhaitez-vous continuer ?") and the section
   * reformulation. Sends section.finish with the active section reference.
   */
  finishCurrentSection(session: CaptureSession): void {
    const ref = this.activeSectionRef(session);
    this.clearAutoResumeTimer();
    this.stopCaptureEndpointMonitor();
    this.voiceConnection?.sectionFinish({
      topic_id: ref.topic_id || null,
      subtopic_id: ref.subtopic_id || null,
      surface: 'knowledge_capture',
    });
    // section.finish genuinely runs analysis and emits a `conversation.step`,
    // so this is one of the few flows where the `thinking` state + 60s analysis
    // watchdog are expected (the watchdog is cleared when conversation.step lands).
    this.voiceState.set('thinking');
    this.armConversationProcessingWatchdog();
    this.setVoiceNotice('Section terminée. L’IA va vous demander si vous souhaitez continuer.', 'info');
  }

  /**
   * "Terminer la capture" — closes all remaining sections and starts the final
   * phase (reformulation + proposal). If a voice turn is still recording or
   * finalizing, flush it first so the final transcript is persisted before
   * capture.finish builds the report.
   */
  finishCapture(session: CaptureSession): void {
    this.clearAutoResumeTimer();
    this.captureEndpointReason = 'stop';
    this.stopCaptureEndpointMonitor();
    const hasStreamingConnection = Boolean(this.voiceConnection);
    if (hasStreamingConnection && (this.recording() || this.transcribing())) {
      this.deferredLoopStopAfterStreamingTurn = null;
      this.deferredCaptureFinishAfterStreamingTurn = true;
      this.closeVoiceAfterStreamingTurn = true;
      this.stopSpeech(false);
      if (this.recording()) {
        if (this.recorder) {
          try {
            this.recorder.onstop = null;
          } catch {
            /* browser cleanup only */
          }
          try {
            if (this.recorder.state !== 'inactive') this.recorder.stop();
          } catch {
            /* browser cleanup only */
          }
          this.recorder = null;
        }
        this.recording.set(false);
        this.conversationSessionActive.set(false);
        this.releaseAudioStream();
        void this.finishStreamingVoiceTurn('stop');
      } else {
        this.conversationSessionActive.set(false);
        this.setVoiceNotice('Finalisation du dernier tour avant synthèse…', 'info');
      }
      return;
    }
    this.deferredLoopStopAfterStreamingTurn = null;
    this.deferredCaptureFinishAfterStreamingTurn = false;
    this.closeVoiceAfterStreamingTurn = false;
    if (hasStreamingConnection) {
      // The heavy FINAL pass runs behind capture.finish: gate the report screen
      // behind the finalization loader until the proposal-ready step lands.
      this.beginCaptureFinalizing();
    }
    this.voiceConnection?.captureFinish({ surface: 'knowledge_capture' });
    this.stopSpeech(false);
    if (this.recorder) {
      try {
        this.recorder.onstop = null;
      } catch {
        /* browser cleanup only */
      }
      try {
        if (this.recorder.state !== 'inactive') this.recorder.stop();
      } catch {
        /* browser cleanup only */
      }
      this.recorder = null;
    }
    this.recording.set(false);
    this.conversationSessionActive.set(false);
    this.releaseAudioStream();
    // capture.finish runs the final reformulation + proposal, which is a genuine
    // analysis phase: keep the `thinking` state and arm the 60s analysis watchdog
    // (it is a no-op once voiceState moves off `thinking` as the closure lands).
    this.voiceState.set('thinking');
    this.armConversationProcessingWatchdog();
    this.setVoiceNotice('Capture terminée. Préparation de la synthèse finale…', 'info');
    if (session.status === 'active' && !hasStreamingConnection) {
      this.applySessionClosure(session, 'finish');
    }
  }

  private transcribeRecording(): void {
    if (!this.conversationSessionActive()) {
      this.releaseAudioStream();
    }
    this.recorder = null;
    this.cancelPartialTranscription('final');
    // Dictation always finalises over HTTP so the stop callback receives the
    // transcript; only conversation turns hand off to the streaming gateway.
    if (!this.recordingStopCallback && this.voiceConnection && this.conversationMode() === 'conversation_only') {
      void this.finishStreamingVoiceTurn(this.captureEndpointReason);
      return;
    }
    const blob = new Blob(this.chunks, { type: 'audio/webm' });
    this.transcribing.set(true);
    this.voiceState.set('partial_transcribing');
    this.setVoiceNotice('Finalisation de la transcription vocale.', 'info');
    this.armTranscriptionWatchdog();
    this.api
      .transcribeAudio(blob)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.clearTranscriptionWatchdog();
          const text = res.text || '';
          // Dictation finalises through this same path, but must NOT clobber the
          // capture answer field — the stop callback writes to its own target.
          if (this.recordingStopCallback) {
            this.transcribing.set(false);
            this.voiceState.set('idle');
            const finalize = this.recordingStopCallback;
            this.recordingStopCallback = null;
            this.recordingPartialCallback = null;
            finalize(text);
            this.clearDictationSurface();
            this.setVoiceNotice('Transcription enregistrée.', 'info');
            return;
          }
          this.answer = text;
          if (text.trim()) {
            this.setLiveImproved(this.currentClientTurnId || 'live-turn', text);
          }
          this.transcribing.set(false);
          this.voiceState.set('idle');
          const session = this.session();
          if (session) {
            this.maybePrefetchRetrieval(session, text, true);
            if (this.conversationMode() === 'conversation_only') {
              this.runConversationStep(session, text);
            } else {
              this.setVoiceNotice(
                session && this.isFreeConversationSession(session)
                  ? 'Transcription prête. Relisez puis enregistrez la réponse pour l’ajouter à la session.'
                  : 'Transcription prête pour évaluation.',
                'info',
              );
            }
          }
        },
        error: () => {
          this.clearTranscriptionWatchdog();
          this.transcribing.set(false);
          this.voiceState.set('idle');
          if (this.recordingStopCallback) {
            this.recordingStopCallback = null;
            this.recordingPartialCallback = null;
            this.clearDictationSurface();
          }
          this.setVoiceNotice('Transcription impossible. Réessayez un tour vocal ou utilisez la saisie guidée.', 'error');
        },
      });
  }

  private eventLedgerKey(event: CaptureEvent): string {
    const meta = event.metadata || {};
    if (meta['client_turn_id']) return `client:${meta['client_turn_id']}`;
    const text = this.eventDisplayText(event).trim().toLowerCase();
    if (text) return `text:${text.replace(/\s+/g, ' ').slice(0, 160)}`;
    if (event.parent_event_id) return `parent:${event.parent_event_id}`;
    if (event.question_id) return `question:${event.question_id}`;
    return `event:${event.id}`;
  }

  private resetHttpBatchRecordingBuffers(): void {
    this.cancelPartialTranscription('reset');
    this.chunks = [];
    this.recordedAudioBytes = 0;
    this.lastPartialTranscriptionStartedAt = 0;
    this.partialTranscriptionDisabledForTurn = false;
    this.partialTranscriptionLimitNoticeShown = false;
  }

  private cancelPartialTranscription(_reason: 'reset' | 'final' | 'stop'): void {
    this.partialTranscriptionRequestId += 1;
    this.activePartialTranscriptionRequestId = this.partialTranscriptionRequestId;
    if (this.partialTranscriptionSubscription && !this.partialTranscriptionSubscription.closed) {
      this.partialTranscriptionSubscription.unsubscribe();
    }
    this.partialTranscriptionSubscription = null;
    this.partialTranscriptionInFlight = false;
  }

  private httpBatchPartialSttMaxAudioBytes(): number {
    return this.voiceLoopSettingNumber(
      'partial_stt_max_audio_bytes',
      HTTP_BATCH_PARTIAL_MAX_AUDIO_BYTES,
      64 * 1024,
      4 * 1024 * 1024,
    );
  }

  private httpBatchPartialSttMinIntervalMs(): number {
    return this.voiceLoopSettingNumber(
      'partial_stt_min_interval_ms',
      HTTP_BATCH_PARTIAL_MIN_INTERVAL_MS,
      0,
      120000,
    );
  }

  private markHttpBatchPartialsCapped(blobBytes: number): void {
    this.partialTranscriptionDisabledForTurn = true;
    if (!this.partialTranscriptionLimitNoticeShown && this.recording() && !this.recordingPartialCallback) {
      this.partialTranscriptionLimitNoticeShown = true;
      this.setVoiceNotice(
        'Transcription live allégée sur ce tour ; la transcription complète sera finalisée à l’arrêt.',
        'info',
      );
    }
    this.emitCaptureClientMetric({
      metric: 'partial_stt_capped',
      value: blobBytes,
      partial_blob_bytes: blobBytes,
      partial_blob_cap_bytes: this.httpBatchPartialSttMaxAudioBytes(),
    });
  }

  private transcribePartialRecording(): void {
    if (this.voiceConnection && this.conversationMode() === 'conversation_only') {
      return;
    }
    if (
      this.partialTranscriptionInFlight ||
      this.partialTranscriptionDisabledForTurn ||
      this.workspaceVoiceLoopConfig().live_partial_stt_enabled === false ||
      this.chunks.length < 2
    ) {
      return;
    }
    const session = this.session();
    const dictation = !!this.recordingPartialCallback;
    // Live partials drive either the capture transcript (session) or an icon-only
    // dictation (which can run during prep/scoping where there is no session yet).
    if (!session && !dictation) {
      return;
    }
    const blobBytes = Math.max(this.recordedAudioBytes, 0);
    if (blobBytes > this.httpBatchPartialSttMaxAudioBytes()) {
      this.markHttpBatchPartialsCapped(blobBytes);
      return;
    }
    const now = performance.now();
    const minIntervalMs = this.httpBatchPartialSttMinIntervalMs();
    if (this.lastPartialTranscriptionStartedAt > 0 && now - this.lastPartialTranscriptionStartedAt < minIntervalMs) {
      return;
    }
    this.partialTranscriptionInFlight = true;
    this.lastPartialTranscriptionStartedAt = now;
    this.voiceState.set('partial_transcribing');
    const blob = new Blob(this.chunks, { type: 'audio/webm' });
    if (blob.size > this.httpBatchPartialSttMaxAudioBytes()) {
      this.partialTranscriptionInFlight = false;
      this.markHttpBatchPartialsCapped(blob.size);
      return;
    }
    const requestId = ++this.partialTranscriptionRequestId;
    this.activePartialTranscriptionRequestId = requestId;
    const turnId = this.currentClientTurnId;
    this.partialTranscriptionSubscription = this.api
      .transcribeAudio(blob, 'partial.webm')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          if (requestId !== this.activePartialTranscriptionRequestId || (!dictation && turnId !== this.currentClientTurnId)) {
            return;
          }
          this.partialTranscriptionSubscription = null;
          this.partialTranscriptionInFlight = false;
          const text = (res.text || '').trim();
          if (text) {
            // Plan/prep dictation must only update its target field — never the
            // capture transcript panel (which shares liveTranscript state).
            if (!dictation) {
              this.setLivePartial(this.currentClientTurnId || 'live-turn', text);
            }
            if (dictation) {
              this.recordingPartialCallback?.(text);
            } else if (session) {
              this.answer = text;
              // Realtime STT already retrieves on partials server-side and feeds
              // the panels via WS (evaluation.delta.retrieval / section.active /
              // oracle.questions); skip the duplicate HTTP prefetch here. Keep it
              // for non-realtime / dictation modes that have no server retrieval.
              if (!this.realtimeSttActive) {
                this.maybePrefetchRetrieval(session, text);
              }
            }
          }
          if (this.recording()) {
            this.voiceState.set(this.prefetchInFlight ? 'retrieving' : 'listening');
          }
        },
        error: () => {
          if (requestId !== this.activePartialTranscriptionRequestId || (!dictation && turnId !== this.currentClientTurnId)) {
            return;
          }
          this.partialTranscriptionSubscription = null;
          this.partialTranscriptionInFlight = false;
          if (this.recording()) {
            this.voiceState.set('listening');
          }
        },
      });
  }

  private async finishStreamingVoiceTurn(reason: CaptureEndpointReason = this.captureEndpointReason): Promise<void> {
    // Snapshot the connection BEFORE awaiting pending frame sends: a concurrent
    // stop/teardown can null `this.voiceConnection` during the await, which
    // silently dropped the endpoint and left the turn unfinalised.
    const connection = this.voiceConnection;
    this.transcribing.set(true);
    this.voiceState.set('partial_transcribing');
    this.setVoiceNotice(
      reason === 'no_speech'
        ? 'Aucune parole détectée. Le tour vocal est fermé sans analyse.'
        : 'Finalisation de la transcription via la session vocale streaming.',
      reason === 'no_speech' ? 'warning' : 'info',
    );
    const pending = [...this.pendingVoiceFrameSends];
    this.pendingVoiceFrameSends = [];
    if (pending.length) {
      await Promise.allSettled(pending);
    }
    connection?.endpoint(this.voiceFrameMeta(reason));
    if (reason === 'no_speech') {
      this.transcribing.set(false);
      this.voiceState.set('idle');
      this.scheduleConversationResume(this.voiceLoopCooldownMs());
      return;
    }
    this.armTranscriptionWatchdog();
  }

  private maybePrefetchRetrieval(session: CaptureSession, text: string, force = false): void {
    const clean = text.trim();
    if (this.prefetchInFlight || clean.split(/\s+/).filter(Boolean).length < 8) return;
    const now = Date.now();
    const newWords = Math.abs(clean.split(/\s+/).length - this.lastPrefetchText.split(/\s+/).filter(Boolean).length);
    if (!force && newWords < 8 && now - this.lastPrefetchAt < 2500) return;
    const passiveSurface = this.isFreeConversationSession(session);
    this.prefetchInFlight = true;
    this.lastPrefetchText = clean;
    this.lastPrefetchAt = now;
    if (!passiveSurface && !this.recording()) {
      this.voiceState.set('retrieving');
    }
    if (!passiveSurface) {
      this.retrieval.set({ ...this.retrieval(), status: 'searching' });
    }
    this.api
      .prefetchCaptureRetrieval(session.id, {
        client_turn_id: this.currentClientTurnId,
        question_id: this.selectedQuestionId(),
        partial_text: clean,
        mode: 'chah',
        top_k: 4,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (payload) => {
          const typed = payload as RetrievalPrefetch;
          const passive = this.shouldKeepRetrievalPassive(session, typed);
          if (passive) {
            this.prefetchInFlight = false;
            if (this.recording()) {
              this.voiceState.set('listening');
            } else if (this.voiceState() === 'retrieving') {
              this.voiceState.set('idle');
            }
            return;
          }
          const mappedStatus =
            typed.status === 'completed' || typed.status === 'completed_from_warm_cache'
              ? 'ready'
              : typed.status === 'timeout'
                ? 'timeout'
                : typed.status;
          this.retrieval.set({
            event_id: typed.event_id,
            status: mappedStatus as RetrievalPrefetch['status'],
            latency_ms: typed.latency_ms,
            collection_name: typed.collection_name,
            chunks: typed.chunks || [],
            scores: typed.scores || [],
            metadatas: typed.metadatas || [],
            hints: typed.hints || [],
            active_subtopic_id: typed.active_subtopic_id,
          });
          if (typed.hints?.length) {
            this.hintStack.update((current) => [...typed.hints!, ...current.filter((item) => !typed.hints!.some((h) => h.id === item.id))]);
          }
          this.applyLiveSectionDetection(
            typed.active_subtopic_id,
            typed.active_topic_id,
            Number(typed.active_section_confidence || 0),
            'prefetch',
          );
          this.prefetchInFlight = false;
          if (this.isTopicOnlyPlan(session)) this.refreshHintQueue(session.id, typed.active_subtopic_id || this.activeSubtopicId());
          if (this.recording()) {
            this.voiceState.set('listening');
          } else if (this.voiceState() === 'retrieving') {
            this.voiceState.set('idle');
          }
        },
        error: () => {
          if (!passiveSurface) {
            this.retrieval.set({ status: 'error', chunks: [], scores: [], metadatas: [] });
          }
          this.prefetchInFlight = false;
          if (this.recording()) {
            this.voiceState.set('listening');
          } else if (this.voiceState() === 'retrieving') {
            this.voiceState.set('idle');
          }
        },
      });
  }

  private shouldKeepRetrievalPassive(session: CaptureSession, payload: RetrievalPrefetch): boolean {
    if (!this.isFreeConversationSession(session)) {
      return payload.passive === true;
    }
    if (payload.status === 'timeout' || payload.status === 'error' || payload.passive === true) {
      return true;
    }
    if (Number(payload.oracle_exact_match_count || 0) > 0) {
      return false;
    }
    if (Number(payload.active_section_confidence || 0) >= 0.45) {
      return false;
    }
    return !this.hasStrongRetrievalEvidence(payload.metadatas || []);
  }

  private hasStrongRetrievalEvidence(metadatas: Record<string, any>[]): boolean {
    return metadatas.some((meta) => {
      const coverage = Number(meta['retrieval_evidence_coverage'] ?? 0);
      const policyScore = Number(meta['retrieval_policy_score'] ?? 0);
      const exactTerms = Array.isArray(meta['retrieval_exact_terms_matched'])
        ? meta['retrieval_exact_terms_matched'].length
        : 0;
      return coverage >= 0.35 || exactTerms >= 2 || (coverage >= 0.2 && policyScore >= 3);
    });
  }

  retrievalChunkTrack(index: number, chunk: string): string {
    return `${index}:${chunk.slice(0, 80)}`;
  }

  private retrievalChunkMeta(index: number): Record<string, any> {
    return this.retrieval().metadatas?.[index] || {};
  }

  private retrievalChunkDocumentId(index: number): string {
    const meta = this.retrievalChunkMeta(index);
    return String(meta['document_id'] || meta['source_id'] || '');
  }

  private retrievalChunkCollection(index: number): string {
    const meta = this.retrievalChunkMeta(index);
    return String(
      meta['collection_name'] ||
        meta['collection'] ||
        this.retrieval().collection_name ||
        '',
    );
  }

  retrievalChunkTitle(index: number): string | null {
    const meta = this.retrievalChunkMeta(index);
    const title = String(meta['title'] || meta['filename'] || meta['source'] || '').trim();
    return title || null;
  }

  canPreviewRetrievalChunk(index: number): boolean {
    return Boolean(this.retrievalChunkDocumentId(index)) && Boolean(this.retrievalChunkCollection(index));
  }

  previewRetrievalChunk(index: number): void {
    const documentId = this.retrievalChunkDocumentId(index);
    const collection = this.retrievalChunkCollection(index);
    if (!documentId || !collection) return;
    const meta = this.retrievalChunkMeta(index);
    const filename = String(meta['filename'] || '').trim();
    let url =
      `${this.api.base}/documents/${encodeURIComponent(documentId)}/rich-preview` +
      `?collection_name=${encodeURIComponent(collection)}`;
    if (filename) url += `&filename=${encodeURIComponent(filename)}`;
    this.sourcePreviewTitle.set(this.retrievalChunkTitle(index) || 'Source retrouvée');
    this.sourcePreviewUrl.set(url);
    this.sourcePreviewPage.set(this.coercePage(meta['page'] ?? meta['page_number']));
    const chunkText = String(this.retrieval().chunks?.[index] || '').trim();
    this.sourcePreviewHighlight.set(chunkText.length >= 8 ? chunkText : null);
    this.sourcePreviewOpen.set(true);
  }

  /** Parse a metadata page value into a positive 1-based page number, or null. */
  private coercePage(raw: unknown): number | null {
    if (raw === undefined || raw === null || `${raw}`.trim() === '') return null;
    const value = typeof raw === 'number' ? raw : Number.parseInt(String(raw), 10);
    return Number.isFinite(value) && value > 0 ? value : null;
  }

  closeSourcePreview(): void {
    this.sourcePreviewOpen.set(false);
    this.sourcePreviewUrl.set(null);
    this.sourcePreviewPage.set(null);
    this.sourcePreviewHighlight.set(null);
  }

  // --- FINAL-phase loader (capture.finish gating) ---------------------------

  /** Lock the report screen behind the finalization loader until the heavy
   * end-of-capture pass persists the restructured report. */
  private beginCaptureFinalizing(): void {
    this.captureFinalizing.set(true);
    this.captureFinalizeStage.set({ stage: 'start', label: 'Préparation de la synthèse finale…' });
    if (this.captureFinalizeDoneTimeout) {
      clearTimeout(this.captureFinalizeDoneTimeout);
      this.captureFinalizeDoneTimeout = null;
    }
    if (this.captureFinalizeTimeout) clearTimeout(this.captureFinalizeTimeout);
    // Safety valve: if the proposal-ready step never lands (connection lost),
    // release the gate after 4 minutes instead of trapping the user.
    this.captureFinalizeTimeout = setTimeout(() => {
      if (!this.captureFinalizing()) return;
      this.setVoiceNotice(
        'La synthèse finale prend plus de temps que prévu. Le rapport affiché peut être incomplet.',
        'warning',
      );
      this.endCaptureFinalizing(true);
    }, 240000);
  }

  /** Net for the terminal `done` stage: if the proposal-bearing
   * conversation.step does not land shortly after, fetch the persisted proposal
   * and open the report so the user is never stuck on a completed loader. */
  private armCaptureFinalizeDoneFallback(): void {
    if (this.captureFinalizeDoneTimeout) return;
    this.captureFinalizeDoneTimeout = setTimeout(() => {
      this.captureFinalizeDoneTimeout = null;
      if (!this.captureFinalizing()) return;
      const session = this.session();
      if (this.proposal() || !session) {
        this.endCaptureFinalizing(true);
        return;
      }
      this.api
        .listCaptureProposals(undefined, undefined, session.id)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (payload) => {
            const proposals = (payload as { proposals?: CaptureProposal[] }).proposals || [];
            const latest = proposals[0] || null;
            if (latest && this.session()?.id === session.id) {
              this.setProposal(latest);
            }
            this.endCaptureFinalizing(true);
          },
          error: () => this.endCaptureFinalizing(true),
        });
    }, 8000);
  }

  private endCaptureFinalizing(navigateToReview: boolean): void {
    if (this.captureFinalizeTimeout) {
      clearTimeout(this.captureFinalizeTimeout);
      this.captureFinalizeTimeout = null;
    }
    if (this.captureFinalizeDoneTimeout) {
      clearTimeout(this.captureFinalizeDoneTimeout);
      this.captureFinalizeDoneTimeout = null;
    }
    const wasFinalizing = this.captureFinalizing();
    this.captureFinalizing.set(false);
    this.captureFinalizeStage.set(null);
    if (!wasFinalizing || !navigateToReview) return;
    if (this.proposal()) {
      this.reportEditMode.set(false);
      this.activeSurface.set('review');
    } else {
      this.activeSurface.set(this.session() ? 'session' : 'dashboard');
    }
  }

  captureFinalizeStageLabel(): string {
    return this.captureFinalizeStage()?.label || 'Préparation de la synthèse finale…';
  }

  captureFinalizeSectionProgress(): string | null {
    const stage = this.captureFinalizeStage();
    if (!stage?.current || !stage?.total) return null;
    return `Section ${stage.current} / ${stage.total}`;
  }

  captureFinalizeProgressPct(): number | null {
    const stage = this.captureFinalizeStage();
    if (!stage?.current || !stage?.total) return null;
    return Math.min(100, Math.round(((stage.current - 0.5) / stage.total) * 100));
  }

  /** Pipeline checklist shown in the loader; states follow the real stages. */
  captureFinalizeSteps(): Array<{ label: string; state: 'done' | 'active' | 'pending' }> {
    const order = ['start', 'restructure', 'dedupe', 'vocabulary', 'reformulate', 'questions', 'section', 'report', 'done'];
    const grouping: Array<{ label: string; stages: string[] }> = [
      { label: 'Restructuration selon le plan', stages: ['start', 'restructure'] },
      { label: 'Nettoyage des doublons', stages: ['dedupe'] },
      { label: 'Alignement vocabulaire Andritz', stages: ['vocabulary'] },
      { label: 'Reformulation des sections', stages: ['reformulate', 'questions', 'section'] },
      { label: 'Assemblage du rapport', stages: ['report', 'done'] },
    ];
    const current = this.captureFinalizeStage()?.stage || 'start';
    // Terminal stage: every group is complete. Without this the last group
    // (stages ['report','done']) kept spinning at `done` because its rank
    // matched the current rank, so the loader never showed a finished state.
    if (current === 'done') {
      return grouping.map((group) => ({ label: group.label, state: 'done' as const }));
    }
    const currentRank = Math.max(0, order.indexOf(current));
    return grouping.map((group) => {
      const ranks = group.stages.map((stage) => order.indexOf(stage));
      if (ranks.some((rank) => rank === currentRank)) return { label: group.label, state: 'active' as const };
      return { label: group.label, state: Math.max(...ranks) < currentRank ? ('done' as const) : ('pending' as const) };
    });
  }

  // --- Report fiche (structured rendering of the FINAL report) --------------

  private buildReportFiche(proposal: CaptureProposal | null): CaptureReportSectionCard[] {
    const topics = proposal?.proposal?.plan_structure?.topics || [];
    const cards: CaptureReportSectionCard[] = [];
    for (const topic of topics) {
      const subsections: CaptureReportSubsectionCard[] = [];
      for (const subtopic of topic.subtopics || []) {
        const sub = this.buildReportNode(
          `${topic.topic_id || cards.length}:${subtopic.subtopic_id || subsections.length}`,
          subtopic,
        );
        if (sub.blocks.length || sub.facts.length || sub.sources.length || sub.openQuestionLinks.length) {
          subsections.push(sub);
        }
      }
      const node = this.buildReportNode(String(topic.topic_id || cards.length), topic);
      if (!node.blocks.length && !node.facts.length && !subsections.length) continue;
      cards.push({ ...node, index: cards.length + 1, subsections });
    }
    return cards;
  }

  private buildReportNode(key: string, node: CaptureReportStructureNode): CaptureReportSubsectionCard {
    const synthesis = String(node.synthesis || '').trim();
    const facts = synthesis
      ? []
      : (node.facts || [])
          .map((fact) => String(fact.text || fact.statement || '').trim())
          .filter((text) => Boolean(text));
    return {
      key,
      title: String(node.title || 'Section').trim(),
      blocks: this.parseReportBlocks(synthesis),
      facts,
      sources: (node.sources || []).filter((src) => Boolean(src)),
      openQuestionLinks: this.buildReportOpenQuestionLinks(node.open_questions || []),
    };
  }

  private buildReportOpenQuestionLinks(rawQuestions: Array<Record<string, unknown> | ProposalOpenQuestion>): CaptureReportOpenQuestionLink[] {
    const texts = rawQuestions
      .filter((q) => !['answered', 'invalid', 'dismissed'].includes(String((q as ProposalOpenQuestion).status || 'open').toLowerCase()))
      .map((q) =>
        String(
          (q as Record<string, unknown>)['text'] ||
            (q as ProposalOpenQuestion).follow_up ||
            (q as ProposalOpenQuestion).reason ||
            '',
        ).trim(),
      )
      .filter((text) => Boolean(text));
    const links: CaptureReportOpenQuestionLink[] = [];
    const seen = new Set<string>();
    for (const label of texts) {
      const key = this.resolveReviewQuestionKey(label);
      if (!key || seen.has(key)) continue;
      seen.add(key);
      const sidebarIndex = this.proposalReviewQuestions().findIndex((row) => row.key === key);
      links.push({
        key,
        label,
        index: sidebarIndex >= 0 ? sidebarIndex + 1 : links.length + 1,
      });
    }
    return links;
  }

  reviewQuestionDomId(key: string): string {
    return `kc-review-q-${this.encodeReviewQuestionDomKey(key)}`;
  }

  private encodeReviewQuestionDomKey(key: string): string {
    return encodeURIComponent(key).replace(/%/g, '_');
  }

  resolveReviewQuestionKey(text: string): string | null {
    const normalized = text.trim().toLowerCase();
    if (!normalized) return null;
    for (const [index, question] of this.proposalOpenQuestions().entries()) {
      const candidate = this.proposalQuestionText(question).trim().toLowerCase();
      if (!candidate) continue;
      if (candidate === normalized || candidate.includes(normalized) || normalized.includes(candidate)) {
        return this.proposalQuestionKey(question, index);
      }
    }
    return null;
  }

  scrollToReviewQuestion(key: string): void {
    const target = document.getElementById(this.reviewQuestionDomId(key));
    if (!target) {
      this.setVoiceNotice('Question introuvable dans le panneau de revue.', 'warning');
      return;
    }
    target.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    if (this.reviewQuestionHighlightTimer) clearTimeout(this.reviewQuestionHighlightTimer);
    this.highlightedReviewQuestionKey.set(key);
    this.reviewQuestionHighlightTimer = setTimeout(() => {
      this.highlightedReviewQuestionKey.set(null);
      this.reviewQuestionHighlightTimer = null;
    }, 2200);
  }

  /** Minimal, safe markdown-to-blocks parser for the section syntheses
   * (markdown stays the storage format; rendering is structured). */
  private parseReportBlocks(markdown: string): CaptureReportBlock[] {
    const blocks: CaptureReportBlock[] = [];
    if (!markdown) return blocks;
    let bulletBuffer: Array<{ level: number; text: string }> = [];
    let paragraph: string[] = [];
    const flushParagraph = () => {
      if (paragraph.length) {
        blocks.push({ kind: 'paragraph', text: this.stripInlineMarkdown(paragraph.join(' ')) });
        paragraph = [];
      }
    };
    const flushList = () => {
      if (bulletBuffer.length) {
        blocks.push({ kind: 'list', items: this.buildReportListTree(bulletBuffer) });
        bulletBuffer = [];
      }
    };
    for (const rawLine of markdown.split('\n')) {
      if (!rawLine.trim()) {
        flushList();
        flushParagraph();
        continue;
      }
      const bullet = this.parseReportBulletLine(rawLine);
      if (bullet) {
        flushParagraph();
        bulletBuffer.push(bullet);
        continue;
      }
      flushList();
      const trimmed = rawLine.trim();
      const heading = trimmed.match(/^#{1,6}\s+(.*)$/);
      if (heading) {
        flushParagraph();
        blocks.push({ kind: 'heading', text: this.stripInlineMarkdown(heading[1]) });
        continue;
      }
      if (this.isReportSubheading(trimmed)) {
        flushParagraph();
        blocks.push({ kind: 'heading', text: this.stripInlineMarkdown(this.normalizeReportSubheading(trimmed)) });
        continue;
      }
      paragraph.push(trimmed);
    }
    flushList();
    flushParagraph();
    return blocks;
  }

  private parseReportBulletLine(rawLine: string): { level: number; text: string } | null {
    const match = rawLine.match(/^([\t ]*)([-*•]|\d+[.)])\s+(.*)$/);
    if (!match) return null;
    const indent = match[1].replace(/\t/g, '  ').length;
    return { level: Math.floor(indent / 2), text: this.stripInlineMarkdown(match[3]) };
  }

  private buildReportListTree(flat: Array<{ level: number; text: string }>): CaptureReportListItem[] {
    const root: CaptureReportListItem[] = [];
    const stack: Array<{ level: number; item: CaptureReportListItem }> = [];
    for (const entry of flat) {
      const node: CaptureReportListItem = { text: entry.text, children: [] };
      while (stack.length && stack[stack.length - 1].level >= entry.level) {
        stack.pop();
      }
      if (!stack.length) {
        root.push(node);
      } else {
        stack[stack.length - 1].item.children.push(node);
      }
      stack.push({ level: entry.level, item: node });
    }
    return root;
  }

  private isReportSubheading(line: string): boolean {
    if (/^\*\*.+\*\*:?\s*$/.test(line)) return true;
    return line.length <= 100 && /:\s*$/.test(line) && !/^https?:\/\//i.test(line);
  }

  private normalizeReportSubheading(line: string): string {
    const bold = line.match(/^\*\*(.+)\*\*:?\s*$/);
    if (bold) return bold[1].trim();
    return line.replace(/:\s*$/, '').trim();
  }

  private stripInlineMarkdown(text: string): string {
    return text
      .replace(/\*\*([^*]+)\*\*/g, '$1')
      .replace(/\*([^*]+)\*/g, '$1')
      .replace(/`([^`]+)`/g, '$1')
      .trim();
  }

  reportUnassignedFacts(): string[] {
    return (this.proposal()?.proposal?.plan_structure?.unassigned || [])
      .map((fact) => String(fact.text || fact.statement || '').trim())
      .filter((text) => Boolean(text));
  }

  reportSourceLabel(src: CaptureReportSource): string {
    return String(src.title || src.filename || src.source || src.document_id || 'Source').trim();
  }

  canPreviewReportSource(src: CaptureReportSource): boolean {
    return Boolean(src.document_id) && Boolean(src.collection);
  }

  /** Chat-style source preview (same rich-preview endpoint as the chat chips). */
  previewReportSource(src: CaptureReportSource): void {
    const documentId = String(src.document_id || '');
    const collection = String(src.collection || '');
    if (!documentId || !collection) return;
    let url =
      `${this.api.base}/documents/${encodeURIComponent(documentId)}/rich-preview` +
      `?collection_name=${encodeURIComponent(collection)}`;
    const filename = String(src.filename || '').trim();
    if (filename) url += `&filename=${encodeURIComponent(filename)}`;
    this.sourcePreviewTitle.set(this.reportSourceLabel(src));
    this.sourcePreviewUrl.set(url);
    this.sourcePreviewPage.set(null);
    const passage = String(src.preview || '').trim();
    this.sourcePreviewHighlight.set(passage.length >= 8 ? passage : null);
    this.sourcePreviewOpen.set(true);
  }

  toggleReportEditMode(): void {
    this.reportEditMode.update((value) => !value);
  }

  private stopSpeech(markInterrupted: boolean): void {
    this.ttsPlayback.stop(markInterrupted ? 'barge_in' : 'reset', markInterrupted);
    if (this.activeAudio) {
      this.activeAudio.pause();
      this.activeAudio.currentTime = 0;
      this.activeAudio = null;
    }
    this.speaking.set(false);
    this.cleanupAudioUrls();
    if (markInterrupted) {
      this.voiceState.set('interrupted');
    }
  }

  private syncCaptureTtsState(state: VoiceTtsState): void {
    const active = ['preparing', 'queued', 'speaking', 'paused'].includes(state);
    this.speaking.set(active);
    if (state === 'speaking' || state === 'preparing' || state === 'queued' || state === 'paused') {
      this.voiceState.set('speaking');
      return;
    }
    if (state === 'idle' && !this.recording() && !this.transcribing()) {
      this.voiceState.set('idle');
    }
    if (state === 'error') {
      this.voiceState.set('idle');
      this.setVoiceNotice('Synthèse vocale indisponible ; ouverture du micro à la place.', 'warning');
    }
  }

  private endpointRecordingTurn(reason: CaptureEndpointReason): void {
    if (!this.recorder || this.recorder.state === 'inactive') return;
    this.captureEndpointReason = reason;
    this.stopCaptureEndpointMonitor();
    const isDictation = !!this.recordingPartialCallback;
    const notice = isDictation ? this.dictationEndpointNotice(reason) : this.captureEndpointNotice(reason);
    this.setVoiceNotice(notice, reason === 'no_speech' ? 'warning' : 'info');
    try {
      this.requestRecorderData();
      this.recorder.stop();
    } catch {
      this.captureEndpointReason = 'error';
      this.setVoiceNotice('Fermeture du tour vocal impossible. Relancez le micro.', 'error');
    }
    this.recording.set(false);
    this.stopDictationAudioMonitor();
  }

  private emitCaptureClientMetric(payload: Record<string, unknown>): void {
    const config = this.resolvedVoiceCaptureConfig();
    const network = (navigator as Navigator & { connection?: { effectiveType?: string } }).connection;
    this.voiceConnection?.clientMetric({
      surface: 'knowledge_capture',
      turn_id: this.currentClientTurnId,
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

  private requestRecorderData(): void {
    const recorder = this.recorder as (MediaRecorder & { requestData?: () => void }) | null;
    if (!recorder || recorder.state !== 'recording' || typeof recorder.requestData !== 'function') return;
    try {
      recorder.requestData();
    } catch {
      /* best-effort flush before endpoint */
    }
  }

  private updateAudioNoiseFloor(current: number, rms: number, preferFastAdapt: boolean): number {
    if (!Number.isFinite(rms)) return current;
    if (current <= 0) return rms;
    const alpha = preferFastAdapt ? 0.12 : 0.025;
    return current * (1 - alpha) + rms * alpha;
  }

  private clearCaptureEndpointCandidate(): void {
    if (this.captureEndpointCandidateTimer !== null) {
      clearTimeout(this.captureEndpointCandidateTimer);
      this.captureEndpointCandidateTimer = null;
    }
    this.captureEndpointCandidateStartedAt = 0;
  }

  private scheduleCaptureEndpointCandidate(details: Record<string, unknown>): void {
    if (this.captureEndpointCandidateTimer !== null) return;
    const graceMs = this.voiceEndpointGraceMs();
    this.captureEndpointCandidateStartedAt = performance.now();
    this.emitCaptureClientMetric({
      metric: 'endpoint_candidate',
      endpoint_reason: 'silence',
      ...details,
    });
    this.requestRecorderData();
    this.captureEndpointCandidateTimer = setTimeout(() => {
      this.clearCaptureEndpointCandidate();
      this.emitCaptureClientMetric({
        metric: 'endpoint_confirmed',
        endpoint_reason: 'silence',
      });
      this.endpointRecordingTurn('silence');
    }, graceMs);
  }

  private cancelCaptureEndpointCandidate(reason: string): void {
    if (this.captureEndpointCandidateTimer === null) return;
    const elapsed = Math.round(performance.now() - this.captureEndpointCandidateStartedAt);
    this.clearCaptureEndpointCandidate();
    this.emitCaptureClientMetric({
      metric: 'endpoint_cancelled',
      endpoint_reason: reason,
      endpoint_grace_ms: elapsed,
      cancelled: true,
    });
  }

  private clearDictationEndpointCandidate(): void {
    if (this.dictationEndpointCandidateTimer !== null) {
      clearTimeout(this.dictationEndpointCandidateTimer);
      this.dictationEndpointCandidateTimer = null;
    }
    this.dictationEndpointCandidateStartedAt = 0;
  }

  private scheduleDictationEndpointCandidate(details: Record<string, unknown>): void {
    if (this.dictationEndpointCandidateTimer !== null) return;
    const graceMs = this.voiceEndpointGraceMs();
    this.dictationEndpointCandidateStartedAt = performance.now();
    this.dictationSilenceEnding.set(true);
    this.emitCaptureClientMetric({
      metric: 'endpoint_candidate',
      endpoint_reason: 'silence',
      ...details,
    });
    this.requestRecorderData();
    this.dictationEndpointCandidateTimer = setTimeout(() => {
      this.clearDictationEndpointCandidate();
      this.emitCaptureClientMetric({
        metric: 'endpoint_confirmed',
        endpoint_reason: 'silence',
      });
      this.endpointRecordingTurn('silence');
    }, graceMs);
  }

  private cancelDictationEndpointCandidate(reason: string): void {
    if (this.dictationEndpointCandidateTimer === null) return;
    const elapsed = Math.round(performance.now() - this.dictationEndpointCandidateStartedAt);
    this.clearDictationEndpointCandidate();
    this.dictationSilenceEnding.set(false);
    this.emitCaptureClientMetric({
      metric: 'endpoint_cancelled',
      endpoint_reason: reason,
      endpoint_grace_ms: elapsed,
      cancelled: true,
    });
  }

  private captureEndpointNotice(reason: CaptureEndpointReason): string {
    if (reason === 'silence') return 'Silence détecté : finalisation du tour vocal.';
    if (reason === 'max_turn') return 'Durée maximale atteinte : finalisation du tour vocal.';
    if (reason === 'no_speech') return 'Aucune parole détectée : le tour vocal est ignoré.';
    if (reason === 'stop') return 'Conversation arrêtée.';
    if (reason === 'error') return 'Erreur pendant la capture vocale.';
    return 'Finalisation du tour vocal.';
  }

  private dictationEndpointNotice(reason: CaptureEndpointReason): string {
    if (reason === 'silence') return this.i18n.t('capture.plan.dictation.silence_stop');
    if (reason === 'no_speech') return 'Aucune parole détectée : dictée annulée.';
    if (reason === 'error') return 'Erreur pendant la dictée.';
    return 'Finalisation de la dictée…';
  }

  private clearDictationSurface(): void {
    this.dictationSurface.set(null);
    this.stopDictationAudioMonitor();
  }

  private startDictationAudioMonitor(): void {
    this.stopDictationAudioMonitor();
    if (!this.stream) return;
    const AudioContextCtor =
      window.AudioContext ||
      (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextCtor) return;
    try {
      const context = new AudioContextCtor();
      const analyser = context.createAnalyser();
      analyser.fftSize = 1024;
      analyser.smoothingTimeConstant = 0.18;
      const source = context.createMediaStreamSource(this.stream);
      source.connect(analyser);
      this.dictationAudioContext = context;
      this.dictationAudioSource = source;
      this.dictationSpeechDetected = false;
      this.dictationTurnStartedAt = performance.now();
      this.dictationLastVoiceAt = this.dictationTurnStartedAt;
      this.dictationSilenceEnding.set(false);
      this.dictationNoiseFloor = 0;
      this.dictationSpeechAboveSince = 0;
      this.dictationSilenceBelowSince = 0;
      this.dictationLastVadMetricAt = 0;
      const data = new Uint8Array(analyser.fftSize);
      const threshold = this.voiceEndpointRmsThreshold();
      const silenceMs = this.dictationEndpointSilenceMs();
      const minSpeechMs = this.dictationEndpointMinSpeechMs();
      const hangoverMs = this.voiceVadHangoverMs();
      const calibrationMs = this.voiceVadCalibrationMs();
      const minSilenceFramesMs = this.voiceVadMinSilenceFramesMs();
      const tick = () => {
        if (!this.recording() || !this.recordingPartialCallback) {
          this.stopDictationAudioMonitor();
          return;
        }
        analyser.getByteTimeDomainData(data);
        let sum = 0;
        for (const sample of data) {
          const normalized = (sample - 128) / 128;
          sum += normalized * normalized;
        }
        const rms = Math.sqrt(sum / data.length);
        const now = performance.now();
        const elapsed = now - this.dictationTurnStartedAt;
        this.dictationAudioLevel.set(Math.min(1, rms / 0.12));
        const calibrating = elapsed <= calibrationMs && !this.dictationSpeechDetected;
        this.dictationNoiseFloor = this.updateAudioNoiseFloor(
          this.dictationNoiseFloor,
          rms,
          calibrating || !this.dictationSpeechDetected,
        );
        const speechThreshold = Math.max(threshold, this.dictationNoiseFloor * 2.6 + 0.004);
        const silenceThreshold = Math.max(this.dictationNoiseFloor * 1.7 + 0.002, speechThreshold * 0.62);
        if (rms >= speechThreshold) {
          if (this.dictationSpeechAboveSince <= 0) this.dictationSpeechAboveSince = now;
          this.dictationSilenceBelowSince = 0;
        } else {
          this.dictationSpeechAboveSince = 0;
          if (rms <= silenceThreshold) {
            if (this.dictationSilenceBelowSince <= 0) this.dictationSilenceBelowSince = now;
          } else {
            this.dictationSilenceBelowSince = 0;
          }
        }
        const speechStable = this.dictationSpeechAboveSince > 0 && now - this.dictationSpeechAboveSince >= 80;
        if (speechStable) {
          this.cancelDictationEndpointCandidate('voice_resumed');
          this.dictationSpeechDetected = true;
          this.dictationLastVoiceAt = now;
          this.dictationVoiceDetected.set(true);
        }
        if (now - this.dictationLastVadMetricAt >= 1000) {
          this.dictationLastVadMetricAt = now;
          this.emitCaptureClientMetric({
            metric: 'rms',
            value: Number(rms.toFixed(5)),
            rms: Number(rms.toFixed(5)),
            noise_floor: Number(this.dictationNoiseFloor.toFixed(5)),
            threshold: Number(speechThreshold.toFixed(5)),
          });
        }
        const silenceStable =
          this.dictationSilenceBelowSince > 0 && now - this.dictationSilenceBelowSince >= minSilenceFramesMs;
        const reachedSilence =
          this.dictationSpeechDetected &&
          elapsed >= minSpeechMs &&
          silenceStable &&
          now - this.dictationLastVoiceAt >= silenceMs + hangoverMs;
        if (reachedSilence && this.dictationEndpointCandidateTimer === null) {
          this.setVoiceNotice(this.dictationEndpointNotice('silence'), 'info');
          this.scheduleDictationEndpointCandidate({
            since_voice_ms: Math.round(now - this.dictationLastVoiceAt),
            rms: Number(rms.toFixed(5)),
            threshold: Number(speechThreshold.toFixed(5)),
          });
        }
        this.dictationAudioRaf = requestAnimationFrame(tick);
      };
      this.dictationAudioRaf = requestAnimationFrame(tick);
    } catch {
      this.stopDictationAudioMonitor();
    }
  }

  private stopDictationAudioMonitor(): void {
    this.clearDictationEndpointCandidate();
    if (this.dictationAudioRaf !== null) {
      cancelAnimationFrame(this.dictationAudioRaf);
      this.dictationAudioRaf = null;
    }
    try {
      this.dictationAudioSource?.disconnect();
    } catch {
      /* ignore */
    }
    this.dictationAudioSource = null;
    void this.dictationAudioContext?.close();
    this.dictationAudioContext = null;
    this.dictationSpeechDetected = false;
    this.dictationLastVoiceAt = 0;
    this.dictationTurnStartedAt = 0;
    this.dictationNoiseFloor = 0;
    this.dictationSpeechAboveSince = 0;
    this.dictationSilenceBelowSince = 0;
    this.dictationLastVadMetricAt = 0;
    this.dictationVoiceDetected.set(false);
    this.dictationSilenceEnding.set(false);
    this.dictationAudioLevel.set(0);
  }

  private startCaptureEndpointMonitor(): void {
    this.stopCaptureEndpointMonitor();
    if (!this.stream || !this.voiceLoopAutoEndpointEnabled()) return;
    const AudioContextCtor =
      window.AudioContext ||
      (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextCtor) {
      this.setVoiceNotice('Détection automatique du silence indisponible dans ce navigateur.', 'warning');
      return;
    }
    try {
      const context = new AudioContextCtor();
      const analyser = context.createAnalyser();
      analyser.fftSize = 1024;
      analyser.smoothingTimeConstant = 0.18;
      const source = context.createMediaStreamSource(this.stream);
      source.connect(analyser);
      this.captureEndpointAudioContext = context;
      this.captureEndpointSource = source;
      this.captureSpeechDetected = false;
      this.captureTurnStartedAt = performance.now();
      this.captureLastVoiceAt = this.captureTurnStartedAt;
      this.captureNoiseFloor = 0;
      this.captureSpeechAboveSince = 0;
      this.captureSilenceBelowSince = 0;
      this.captureLastVadMetricAt = 0;

      const data = new Uint8Array(analyser.fftSize);
      const silenceMs = this.voiceEndpointSilenceMs();
      const minSpeechMs = this.voiceEndpointMinSpeechMs();
      const maxTurnMs = this.voiceEndpointMaxTurnMs();
      const threshold = this.voiceEndpointRmsThreshold();
      const hangoverMs = this.voiceVadHangoverMs();
      const calibrationMs = this.voiceVadCalibrationMs();
      const minSilenceFramesMs = this.voiceVadMinSilenceFramesMs();
      const tick = () => {
        if (!this.recorder || this.recorder.state !== 'recording') return;
        analyser.getByteTimeDomainData(data);
        let sum = 0;
        for (const sample of data) {
          const normalized = (sample - 128) / 128;
          sum += normalized * normalized;
        }
        const rms = Math.sqrt(sum / data.length);
        const now = performance.now();
        const elapsed = now - this.captureTurnStartedAt;
        const calibrating = elapsed <= calibrationMs && !this.captureSpeechDetected;
        this.captureNoiseFloor = this.updateAudioNoiseFloor(
          this.captureNoiseFloor,
          rms,
          calibrating || !this.captureSpeechDetected,
        );
        const speechThreshold = Math.max(threshold, this.captureNoiseFloor * 2.6 + 0.004);
        const silenceThreshold = Math.max(this.captureNoiseFloor * 1.7 + 0.002, speechThreshold * 0.62);
        if (rms >= speechThreshold) {
          if (this.captureSpeechAboveSince <= 0) this.captureSpeechAboveSince = now;
          this.captureSilenceBelowSince = 0;
        } else {
          this.captureSpeechAboveSince = 0;
          if (rms <= silenceThreshold) {
            if (this.captureSilenceBelowSince <= 0) this.captureSilenceBelowSince = now;
          } else {
            this.captureSilenceBelowSince = 0;
          }
        }
        const speechStable = this.captureSpeechAboveSince > 0 && now - this.captureSpeechAboveSince >= 80;
        if (speechStable) {
          this.cancelCaptureEndpointCandidate('voice_resumed');
          this.captureSpeechDetected = true;
          this.captureLastVoiceAt = now;
        }
        if (now - this.captureLastVadMetricAt >= 1000) {
          this.captureLastVadMetricAt = now;
          this.emitCaptureClientMetric({
            metric: 'rms',
            value: Number(rms.toFixed(5)),
            rms: Number(rms.toFixed(5)),
            noise_floor: Number(this.captureNoiseFloor.toFixed(5)),
            threshold: Number(speechThreshold.toFixed(5)),
          });
        }
        // Realtime STT: the sidecar's silence VAD owns turn segmentation. Firing
        // a client-side endpoint here chopped the turn at frontend boundaries
        // that do not match the sidecar's, set recording=false mid-turn and
        // dropped every later partial of the same server turn (live row froze on
        // a fragment). Keep the RMS meter/metrics above, but never auto-endpoint.
        if (this.realtimeSttActive) {
          this.captureEndpointRaf = requestAnimationFrame(tick);
          return;
        }
        const silenceStable =
          this.captureSilenceBelowSince > 0 && now - this.captureSilenceBelowSince >= minSilenceFramesMs;
        const reachedSilence =
          this.captureSpeechDetected &&
          elapsed >= minSpeechMs &&
          silenceStable &&
          now - this.captureLastVoiceAt >= silenceMs + hangoverMs;
        const reachedMax = elapsed >= maxTurnMs;
        if (reachedMax) {
          this.requestRecorderData();
          this.endpointRecordingTurn(
            !this.captureSpeechDetected ? 'no_speech' : 'max_turn',
          );
          return;
        }
        if (reachedSilence) {
          this.scheduleCaptureEndpointCandidate({
            since_voice_ms: Math.round(now - this.captureLastVoiceAt),
            rms: Number(rms.toFixed(5)),
            threshold: Number(speechThreshold.toFixed(5)),
          });
        }
        this.captureEndpointRaf = requestAnimationFrame(tick);
      };
      this.captureEndpointRaf = requestAnimationFrame(tick);
    } catch {
      this.stopCaptureEndpointMonitor();
      this.setVoiceNotice('Détection automatique du silence indisponible. Arrêtez le tour manuellement.', 'warning');
    }
  }

  private stopCaptureEndpointMonitor(): void {
    this.clearCaptureEndpointCandidate();
    if (this.captureEndpointRaf !== null) {
      cancelAnimationFrame(this.captureEndpointRaf);
      this.captureEndpointRaf = null;
    }
    try {
      this.captureEndpointSource?.disconnect();
    } catch {
      /* browser cleanup only */
    }
    const context = this.captureEndpointAudioContext;
    this.captureEndpointSource = null;
    this.captureEndpointAudioContext = null;
    this.captureSpeechDetected = false;
    this.captureNoiseFloor = 0;
    this.captureSpeechAboveSince = 0;
    this.captureSilenceBelowSince = 0;
    this.captureLastVadMetricAt = 0;
    if (context && context.state !== 'closed') {
      void context.close().catch(() => undefined);
    }
  }

  private detectCaptureVoiceCommand(rawText: string): string | null {
    const settings = this.workspaceVoiceLoopConfig();
    if (settings.commands_enabled === false) return null;
    let text = this.normalizeVoiceCommandText(rawText);
    const triggerWord =
      typeof settings.trigger_word === 'string' ? this.normalizeVoiceCommandText(settings.trigger_word) : '';
    const hasTrigger = !!triggerWord && (text === triggerWord || text.startsWith(`${triggerWord} `));
    if (hasTrigger) text = text.slice(triggerWord.length).trim();
    const genericCommandsEnabled = this.voiceCommandPackEnabled(settings, ['generic', 'fr_basic', 'workspace']);
    if (this.isNaturalStopCommand(text, settings.stop_phrases, genericCommandsEnabled)) return 'stop';
    if (!genericCommandsEnabled) return null;
    // Natural-phrase detection (regex, like isNaturalStopCommand) so multi-word
    // turn/section closures stay detectable past the short-command guard below.
    if (this.isEndSectionCommand(text)) return 'end_section';
    if (this.isEndTurnCommand(text)) return 'end_turn';
    const words = text.split(/\s+/).filter(Boolean);
    if (!hasTrigger && words.length > 4) return null;
    if (['stop', 'arrete', 'arret', 'fin', 'termine'].includes(text)) return 'stop';
    return null;
  }

  private handleCaptureVoiceCommand(command: string, transcript: string): boolean {
    // A command can surface on both the partial and the trailing final event of
    // the same turn; act on it once so end_turn/end_section never double-fire.
    if (this.currentClientTurnId !== null && this.commandHandledForTurn === this.currentClientTurnId) {
      return true;
    }
    this.commandHandledForTurn = this.currentClientTurnId;
    this.voiceConnection?.voiceCommand(command, transcript, { surface: 'knowledge_capture' });
    if (command === 'stop') {
      this.stopConversation();
      return true;
    }
    if (command === 'end_turn') {
      // Force-commit the current turn (endpoint -> sidecar commit); capture
      // keeps running, so do NOT stopConversation.
      void this.finishStreamingVoiceTurn('voice_command');
      return true;
    }
    if (command === 'end_section') {
      const session = this.session();
      if (session) this.finishCurrentSection(session);
      return true;
    }
    return false;
  }

  private isEndTurnCommand(commandText: string): boolean {
    if (!commandText) return false;
    // NOTE: never add common discourse fillers here (e.g. "voila"): the detector
    // also runs on the trailing FINAL transcript of every turn, so a frequent
    // word would force-commit and skip the normal turn resume on most turns.
    return [
      /\btour suivant\b/,
      /\bpoint suivant\b/,
      /\bj ai termine ce point\b/,
    ].some((pattern) => pattern.test(commandText));
  }

  private isEndSectionCommand(commandText: string): boolean {
    if (!commandText) return false;
    return [
      /\bsection suivante\b/,
      /\bon passe a la suite\b/,
      /\bfin de (?:la )?section\b/,
    ].some((pattern) => pattern.test(commandText));
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
      ? settings.command_packs.map((pack) => String(pack).trim().toLowerCase())
      : [];
    if (!packs.length) return true;
    return packs.some((pack) => accepted.includes(pack));
  }

  private startAudioRecorder(openMessage: string): boolean {
    if (typeof MediaRecorder === 'undefined') {
      this.recorder = null;
      this.releaseAudioStream();
      this.setVoiceNotice('L’enregistrement audio est indisponible dans ce navigateur. Essayez un autre navigateur ou utilisez la saisie guidée.', 'error');
      return false;
    }
    try {
      this.recorder = new MediaRecorder(this.stream!);
      this.captureEndpointReason = 'manual';
      this.lastVoiceChunkAt = 0;
      this.recorder.ondataavailable = (event) => {
        if (event.data.size <= 0) return;
        const chunkAt = performance.now();
        if (this.lastVoiceChunkAt > 0) {
          this.emitCaptureClientMetric({
            metric: 'chunk_gap_ms',
            value_ms: Math.round(chunkAt - this.lastVoiceChunkAt),
            chunk_gap_ms: Math.round(chunkAt - this.lastVoiceChunkAt),
            chunk_size: event.data.size,
          });
        }
        this.lastVoiceChunkAt = chunkAt;
        this.emitCaptureClientMetric({
          metric: 'chunk_size',
          value: event.data.size,
          chunk_size: event.data.size,
        });
        this.recordedAudioBytes += event.data.size;
        if (this.realtimeSttActive) {
          // Realtime lane: the LiveKit PCM mic track is transcribed by the
          // sidecar (gpt-realtime-whisper). Do not buffer or push WebM frames —
          // the client VAD endpoint drives the realtime commit instead.
          return;
        }
        this.chunks.push(event.data);
        if (this.voiceConnection && this.conversationMode() === 'conversation_only') {
          const sendStartedAt = performance.now();
          const send = this.voiceConnection
            .sendAudioFrame(event.data, this.voiceFrameMeta())
            .then(() => {
              const elapsed = Math.round(performance.now() - sendStartedAt);
              this.emitCaptureClientMetric({
                metric: 'send_audio_frame_ms',
                value_ms: elapsed,
                send_audio_frame_ms: elapsed,
                chunk_size: event.data.size,
              });
            })
            .catch(() => this.setVoiceNotice('Une trame vocale n’a pas pu être envoyée ; le fallback HTTP peut être nécessaire.', 'warning'));
          this.pendingVoiceFrameSends.push(send);
          void send.finally(() => {
            this.pendingVoiceFrameSends = this.pendingVoiceFrameSends.filter((item) => item !== send);
          });
        } else {
          this.transcribePartialRecording();
        }
      };
      this.recorder.onstop = () => {
        this.stopCaptureEndpointMonitor();
        this.transcribeRecording();
      };
      this.recorder.start(1200);
      if (this.voiceConnection && this.conversationMode() === 'conversation_only') {
        this.startCaptureEndpointMonitor();
      }
    } catch {
      this.recorder = null;
      this.stopCaptureEndpointMonitor();
      this.releaseAudioStream();
      this.setVoiceNotice('Démarrage de l’enregistrement impossible. Vérifiez le micro puis réessayez.', 'error');
      return false;
    }
    this.transcriptAtBottom.set(true);
    this.recording.set(true);
    this.voiceState.set('listening');
    this.setVoiceNotice(openMessage, 'info');
    return true;
  }

  private async startRecordingTurn(): Promise<void> {
    if (this.recording() || this.transcribing()) {
      return;
    }
    this.clearAutoResumeTimer();
    const session = this.session();
    // Realtime STT's audio source is the published LiveKit mic track, NOT the
    // local WebM MediaRecorder (whose output is dropped). A prior pause disabled
    // it (audioPause -> setMicrophoneEnabled(false)). Re-enable/publish it HERE,
    // BEFORE ensureAudioStream() grabs its own getUserMedia for the recorder:
    // acquiring the device for the recorder first contended with LiveKit and left
    // the republished track silent on resume ("redémarrer, mais plus rien").
    // Mirrors the initial-connect order (LiveKit mic first), which works.
    if (this.realtimeSttActive && session) {
      const liveConn = await this.ensureVoiceConnection(session);
      if (liveConn && 'enableMicrophone' in liveConn) {
        await liveConn.enableMicrophone(true);
      }
    }
    const armed = await this.ensureAudioStream();
    if (!armed) {
      this.conversationSessionActive.set(false);
      this.voiceState.set('idle');
      return;
    }
    this.resetHttpBatchRecordingBuffers();
    this.currentClientTurnId = this.newTurnId();
    this.commandHandledForTurn = null;
    this.lastPrefetchText = '';
    this.lastPrefetchAt = 0;
    if (session) {
      const connection = await this.ensureVoiceConnection(session);
      const captureConfig = this.resolvedVoiceCaptureConfig();
      connection?.loopArmed({
        surface: 'knowledge_capture',
        mode: 'conversation_loop',
        auto_endpoint: captureConfig.auto_endpoint,
        capture_mode: captureConfig.capture_mode,
        silence_ms: captureConfig.silence_ms,
        min_speech_ms: captureConfig.min_speech_ms,
        rms_threshold: captureConfig.rms_threshold,
        endpoint_grace_ms: captureConfig.endpoint_grace_ms,
        max_turn_ms: captureConfig.max_turn_ms,
      });
    }
    if (!this.startAudioRecorder('Micro ouvert. Terminez le tour quand la réponse expert est complète.')) {
      this.conversationSessionActive.set(false);
      this.voiceState.set('idle');
    }
  }

  private stopConversationSession(): void {
    this.conversationSessionActive.set(false);
    this.clearAutoResumeTimer();
    const loopStopPayload = { surface: 'knowledge_capture', reason: 'user_stop' };
    this.stopSpeech(false);
    this.setVoiceNotice(null);
    if (this.recording()) {
      this.deferredLoopStopAfterStreamingTurn = loopStopPayload;
      this.deferredCaptureFinishAfterStreamingTurn = false;
      this.closeVoiceAfterStreamingTurn = true;
      this.endpointRecordingTurn('manual');
    } else if (this.transcribing() && this.voiceConnection) {
      this.deferredLoopStopAfterStreamingTurn = loopStopPayload;
      this.deferredCaptureFinishAfterStreamingTurn = false;
      this.closeVoiceAfterStreamingTurn = true;
    } else if (!this.transcribing()) {
      this.deferredLoopStopAfterStreamingTurn = null;
      this.deferredCaptureFinishAfterStreamingTurn = false;
      this.closeVoiceAfterStreamingTurn = false;
      this.voiceConnection?.loopStop(loopStopPayload);
      this.releaseAudioStream();
      this.voiceState.set('idle');
      this.closeVoiceConnection();
    }
  }

  private async ensureAudioStream(): Promise<boolean> {
    if (this.hasLiveAudioStream()) {
      return true;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      this.stream = null;
      this.setVoiceNotice('La capture micro est indisponible dans ce contexte navigateur.', 'error');
      return false;
    }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      return true;
    } catch (error) {
      const name = error instanceof DOMException ? error.name : '';
      this.stream = null;
      this.setVoiceNotice(
        name === 'NotAllowedError'
          ? 'L’autorisation micro est bloquée. Autorisez le micro ou poursuivez en saisie guidée.'
          : 'La capture micro a échoué. Vérifiez le périphérique puis réessayez.',
        'error',
      );
      return false;
    }
  }

  private hasLiveAudioStream(): boolean {
    return Boolean(this.stream?.getAudioTracks().some((track) => track.readyState === 'live'));
  }

  private releaseAudioStream(): void {
    this.stopCaptureEndpointMonitor();
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
  }

  private scheduleConversationResume(delayMs = 450, forceAfterSpeech = false): void {
    if (
      this.conversationMode() !== 'conversation_only' ||
      !this.conversationSessionActive() ||
      this.recording() ||
      this.transcribing()
    ) {
      return;
    }
    this.clearAutoResumeTimer();
    this.autoResumeTimer = setTimeout(() => {
      this.autoResumeTimer = null;
      if (
        this.conversationMode() === 'conversation_only' &&
        this.conversationSessionActive() &&
        !this.recording() &&
        !this.transcribing()
      ) {
        if (this.speaking()) {
          if (!forceAfterSpeech) {
            this.scheduleConversationResume(700);
            return;
          }
          this.stopSpeech(false);
        }
        this.voiceConnection?.loopArmed({
          surface: 'knowledge_capture',
          mode: 'conversation_loop',
          auto_endpoint: this.resolvedVoiceCaptureConfig().auto_endpoint,
          capture_mode: this.resolvedVoiceCaptureConfig().capture_mode,
          silence_ms: this.resolvedVoiceCaptureConfig().silence_ms,
          min_speech_ms: this.resolvedVoiceCaptureConfig().min_speech_ms,
          rms_threshold: this.resolvedVoiceCaptureConfig().rms_threshold,
          endpoint_grace_ms: this.resolvedVoiceCaptureConfig().endpoint_grace_ms,
          max_turn_ms: this.resolvedVoiceCaptureConfig().max_turn_ms,
        });
        void this.startRecordingTurn();
      }
    }, delayMs);
  }

  private conversationResumeFallbackDelay(text: string): number {
    const estimatedSpeechMs = Math.ceil(Math.max(1, text.length) / 16) * 1000;
    return Math.max(4500, Math.min(12000, estimatedSpeechMs + 2500));
  }

  private clearAutoResumeTimer(): void {
    if (this.autoResumeTimer) {
      clearTimeout(this.autoResumeTimer);
      this.autoResumeTimer = null;
    }
  }

  private armTranscriptionWatchdog(): void {
    this.clearTranscriptionWatchdog();
    this.transcriptionWatchdog = window.setTimeout(() => {
      if (!this.transcribing()) return;
      this.transcribing.set(false);
      this.voiceState.set('idle');
      this.releaseAudioStream();
      this.finalizeDeferredStreamingStop();
      this.setVoiceNotice('La transcription prend trop de temps. Le micro est libéré, relancez un tour ou utilisez le texte.', 'error');
    }, 45000);
  }

  private clearTranscriptionWatchdog(): void {
    if (this.transcriptionWatchdog) {
      clearTimeout(this.transcriptionWatchdog);
      this.transcriptionWatchdog = null;
    }
  }

  private armConversationProcessingWatchdog(): void {
    this.clearConversationProcessingWatchdog();
    this.conversationProcessingWatchdog = window.setTimeout(() => {
      if (this.voiceState() !== 'thinking') return;
      this.voiceState.set('idle');
      this.setVoiceNotice('L’analyse prend trop de temps. Vous pouvez continuer la capture ou terminer la session.', 'error');
    }, 60000);
  }

  private clearConversationProcessingWatchdog(): void {
    if (this.conversationProcessingWatchdog) {
      clearTimeout(this.conversationProcessingWatchdog);
      this.conversationProcessingWatchdog = null;
    }
  }

  private cleanupAudioUrls(): void {
    this.revokedAudioUrls.forEach((url) => URL.revokeObjectURL(url));
    this.revokedAudioUrls = [];
  }

  private newTurnId(): string {
    return globalThis.crypto?.randomUUID?.() || `turn-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }
}
