import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ApiService } from '@app/core/api.service';
import { PermissionsService } from '@app/core/permissions.service';
import { VoiceSessionConnection, VoiceSessionEvent, VoiceSessionService } from '@app/core/voice-session.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { IconComponent } from '@app/shared/ui/icon.component';

interface CaptureQuestion {
  id: string;
  question: string;
  title?: string;
  estimated_minutes?: number;
}

interface CaptureSession {
  id: string;
  capability_id?: string | null;
  context_id?: string | null;
  system_id?: string | null;
  created_by_user_id?: string | null;
  title: string;
  objective: string;
  status: string;
  plan: { questions?: CaptureQuestion[] };
  transcript?: Array<{ id: string; speaker: string; text: string }>;
  evaluations?: Array<{ verdict: string; score: number; follow_up?: string }>;
  metrics?: Record<string, number>;
}

interface ContextOption {
  id: string;
  name: string;
  data_refs?: string[];
  environment_state?: { collection?: string; document_count?: number };
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
  | 'thinking'
  | 'speaking'
  | 'interrupted';

interface RetrievalPrefetch {
  event_id?: string;
  status: 'idle' | 'searching' | 'ready' | 'late' | 'timeout' | 'error' | 'completed';
  latency_ms?: number;
  collection_name?: string;
  chunks: string[];
  scores: number[];
  metadatas: Record<string, any>[];
}

type ConversationMode = 'manual' | 'conversation_only';
type CaptureSurfaceView = 'dashboard' | 'prep' | 'plan' | 'session' | 'review';
type ProposalFactDecision = 'pending' | 'accept' | 'reject';
type VoiceNoticeTone = 'info' | 'warning' | 'error';

interface ConversationStageRow {
  id: string;
  label: string;
  detail: string;
  icon: string;
  state: 'done' | 'active' | 'pending';
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
  requires_confirmation: boolean;
  confirmation_target?: string | null;
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
    open_questions?: Array<{ gap_id?: string; reason?: string; follow_up?: string }>;
    recommended_ingestion?: { content?: string; metadata?: Record<string, any> };
    audit?: { event_count?: number; amendment_count?: number };
  };
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
  imports: [FormsModule, RouterLink, IconComponent],
  template: `
    <section class="space-y-5">
      <header class="t-card t-elevated rounded-lg p-5 flex items-start justify-between gap-4">
        <div>
          <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">
            {{ systemScoped() ? 'System · Workbench' : 'Knowledge · Capture' }}
          </p>
          <h1 class="text-2xl font-semibold text-white mt-1">
            {{ systemScoped() ? systemLabel(systemId) || 'Expert Knowledge Capture' : 'Expert Knowledge Capture' }}
          </h1>
          <p class="text-sm text-gray-400 mt-2 max-w-3xl">
            {{ systemScoped()
              ? 'Dedicated System UI: run guided voice capture, retrieve live context, evaluate answers, and produce reviewable Knowledge proposals.'
              : 'Capability-led capture: select a Context, identify knowledge gaps, run a guided voice session, then emit a reviewable Knowledge update proposal.' }}
          </p>
        </div>
        <div class="flex flex-col items-end gap-2">
          <span class="text-xs px-3 py-2 rounded bg-white/5 ring-1 ring-white/10 text-gray-300">
            Phase 0 · cascade voice runtime
          </span>
          <span class="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded bg-brand-500/10 ring-1 ring-brand-300/20 text-brand-100">
            <app-icon name="shield-check" [size]="12" />
            IAM · expert_knowledge_capture
          </span>
          <span class="text-xs px-3 py-1.5 rounded bg-white/5 ring-1 ring-white/10 text-gray-300">
            {{ conversationMode() === 'conversation_only' ? 'Conversation mode' : 'Guided mode' }}
          </span>
          <a
            [routerLink]="workspaceAccessRoute()"
            class="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
          >
            <app-icon name="settings-2" [size]="12" />
            Manage Capture IAM
          </a>
        </div>
      </header>

      <nav class="border-y border-white/10 py-3 flex flex-wrap items-center gap-2">
        @for (item of surfaceNav; track item.id) {
          <button
            type="button"
            [class]="activeSurface() === item.id
              ? 'inline-flex items-center gap-2 px-3 py-2 rounded text-brand-100 border-b-2 border-brand-300'
              : stepIsComplete(item.id)
                ? 'inline-flex items-center gap-2 px-3 py-2 rounded text-gray-300 hover:text-white'
                : 'inline-flex items-center gap-2 px-3 py-2 rounded text-gray-500 hover:text-gray-300'"
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
            <span class="text-sm">{{ item.label }}</span>
          </button>
          @if (!$last) {
            <span class="text-gray-700">·</span>
          }
        }
      </nav>

      @if (activeSurface() === 'prep') {
        <section class="max-w-5xl mx-auto py-8 space-y-7">
          <div>
            <p class="ck-mono text-[10px] uppercase tracking-[0.18em] text-gray-500">Step 1 · Preparation</p>
            <h2 class="mt-2 text-3xl text-white font-semibold">Define the capture session</h2>
            <p class="mt-2 text-sm text-gray-400 max-w-3xl">
              Set the objective and scope. Agentium uses this to generate a focused interview plan and keep the live conversation grounded.
            </p>
          </div>

          <div class="space-y-5">
            <div>
              <label class="block text-[11px] uppercase tracking-wider text-gray-500 mb-2">Session title</label>
              <input
                class="w-full rounded bg-black/30 border border-white/10 px-4 py-3 text-sm text-white"
                [(ngModel)]="sessionTitle"
              />
            </div>

            <div>
              <label class="block text-[11px] uppercase tracking-wider text-gray-500 mb-2">Objective</label>
              <textarea
                class="w-full min-h-24 rounded bg-black/30 border border-white/10 px-4 py-3 text-sm text-white leading-relaxed"
                [(ngModel)]="objective"
              ></textarea>
            </div>

            <div>
              <label class="block text-[11px] uppercase tracking-wider text-gray-500 mb-2">Domain</label>
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

            <div>
              <label class="block text-[11px] uppercase tracking-wider text-gray-500 mb-2">Knowledge context</label>
              <select
                class="w-full rounded bg-black/30 border border-white/10 px-4 py-3 text-sm text-white"
                [(ngModel)]="contextId"
                (ngModelChange)="onContextChange($event)"
              >
                <option value="">Workspace defaults</option>
                @for (ctx of contexts(); track ctx.id) {
                  <option [value]="ctx.id">
                    {{ ctx.name }}{{ ctx.environment_state?.collection ? ' · ' + ctx.environment_state?.collection : '' }}
                  </option>
                }
              </select>
            </div>

            <div class="grid md:grid-cols-[1fr_220px] gap-4">
              <div>
                <label class="block text-[11px] uppercase tracking-wider text-gray-500 mb-2">Expert</label>
                <input
                  class="w-full rounded bg-black/30 border border-white/10 px-4 py-3 text-sm text-white"
                  [(ngModel)]="expertProfile"
                />
              </div>
              <div>
                <label class="block text-[11px] uppercase tracking-wider text-gray-500 mb-2">Maximum duration</label>
                <input
                  type="number"
                  min="5"
                  max="90"
                  class="w-full rounded bg-black/30 border border-white/10 px-4 py-3 text-sm text-white"
                  [(ngModel)]="durationMinutes"
                />
              </div>
            </div>

            <div class="flex items-center justify-end gap-3 pt-4">
              <button
                type="button"
                class="px-4 py-2 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-300 ring-1 ring-white/10"
                (click)="goSurface('dashboard')"
              >
                Cancel
              </button>
              <button
                type="button"
                class="inline-flex items-center gap-2 px-5 py-2.5 rounded bg-brand-300 hover:bg-brand-200 text-sm font-semibold text-black disabled:opacity-50"
                [disabled]="loading()"
                (click)="goSurface('plan')"
              >
                Continue to plan
                <app-icon name="arrow-right" [size]="14" />
              </button>
            </div>
          </div>
        </section>
      }

      @if (activeSurface() === 'dashboard') {
        <section class="grid xl:grid-cols-[1.5fr_1fr] gap-5">
          <div class="t-card rounded-lg p-5 space-y-4">
            <div class="flex items-center justify-between gap-3">
              <div>
                <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Capture sessions</p>
                <h2 class="text-lg font-semibold text-white">Session cockpit queue</h2>
              </div>
              <button
                type="button"
                class="inline-flex items-center gap-2 px-3 py-2 rounded bg-brand-500 hover:bg-brand-400 text-sm font-semibold text-white disabled:opacity-50"
                [disabled]="!canCaptureCreate()"
                (click)="goSurface('prep')"
              >
                <app-icon name="plus" [size]="14" /> New session
              </button>
            </div>
            <div class="grid md:grid-cols-4 gap-3">
              <div class="rounded bg-black/20 border border-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500">Sessions</div>
                <div class="text-2xl text-white font-semibold">{{ dashboardSessions().length }}</div>
              </div>
              <div class="rounded bg-black/20 border border-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500">Active</div>
                <div class="text-2xl text-white font-semibold">{{ activeSessionCount() }}</div>
              </div>
              <div class="rounded bg-black/20 border border-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500">Proposals</div>
                <div class="text-2xl text-white font-semibold">{{ dashboardProposals().length }}</div>
              </div>
              <div class="rounded bg-black/20 border border-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500">Pending review</div>
                <div class="text-2xl text-white font-semibold">{{ pendingProposalCount() }}</div>
              </div>
            </div>
            <div class="space-y-2">
              @for (row of dashboardSessions(); track row.id) {
                <button
                  type="button"
                  class="w-full text-left rounded border border-white/10 bg-white/[0.03] hover:bg-white/[0.06] p-3"
                  (click)="openDashboardSession(row)"
                >
                  <div class="flex items-center justify-between gap-3">
                    <div>
                      <div class="text-sm font-semibold text-white">{{ row.title }}</div>
                      <p class="text-xs text-gray-500 mt-1 line-clamp-1">{{ row.objective }}</p>
                      @if (isAuthor(row)) {
                        <span class="mt-2 inline-flex px-2 py-0.5 rounded bg-brand-500/15 text-[10px] uppercase tracking-wider text-brand-200">
                          Author
                        </span>
                      }
                    </div>
                    <span class="text-xs px-2 py-1 rounded bg-white/5 text-gray-300">{{ row.status }}</span>
                  </div>
                  <div class="mt-3 grid grid-cols-3 gap-2 text-xs text-gray-400">
                    <span>{{ row.plan.questions?.length || 0 }} questions</span>
                    <span>{{ row.metrics?.['captured_facts'] || 0 }} facts</span>
                    <span>{{ ((row.metrics?.['coverage'] || 0) * 100).toFixed(0) }}% coverage</span>
                  </div>
                </button>
              } @empty {
                <div class="rounded border border-dashed border-white/10 bg-black/20 p-8 text-center text-gray-500">
                  No capture session yet. Prepare one from this System surface.
                </div>
              }
            </div>
          </div>

          <div class="t-card rounded-lg p-5 space-y-4">
            <div>
              <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Knowledge proposals</p>
              <h2 class="text-lg font-semibold text-white">Review queue</h2>
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
                      {{ row.proposal?.title || 'Knowledge update proposal' }}
                    </div>
                    <span class="text-xs px-2 py-1 rounded bg-white/5 text-gray-300">{{ row.status }}</span>
                  </div>
                  <div class="mt-2 text-xs text-gray-500">
                    {{ row.proposal?.captured_facts?.length || 0 }} facts · {{ row.proposal?.audit?.event_count || 0 }} audit events
                  </div>
                </button>
              } @empty {
                <div class="rounded border border-dashed border-white/10 bg-black/20 p-6 text-center text-gray-500">
                  No proposal waiting for review.
                </div>
              }
            </div>
          </div>
        </section>
      }

      @if (activeSurface() === 'session') {
        @if (session(); as s) {
          <section class="space-y-4">
            <section class="t-card rounded-lg p-4">
              <div class="flex flex-wrap items-center justify-between gap-4">
                <div class="min-w-0">
                  <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Live capture cockpit</p>
                  <h2 class="text-lg font-semibold text-white mt-1 truncate">{{ s.title }}</h2>
                </div>
                <div class="flex flex-wrap items-center gap-2 text-xs">
                  <span class="px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">{{ s.status }}</span>
                  <span class="px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">
                    {{ currentQuestionPosition(s) }} / {{ s.plan.questions?.length || 0 }} questions
                  </span>
                  <span class="px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">
                    {{ s.metrics?.['captured_facts'] || 0 }} facts
                  </span>
                  <span class="px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">
                    {{ selectedContext()?.environment_state?.collection || 'Knowledge target' }}
                  </span>
                  @if (isAuthor(s)) {
                    <span class="px-2 py-1 rounded bg-brand-500/15 text-brand-100 ring-1 ring-brand-300/20">Author</span>
                  }
                </div>
              </div>
            </section>

            <section class="grid xl:grid-cols-[300px_minmax(0,1fr)_360px] gap-4 items-start">
              <aside class="t-card rounded-lg p-4 max-h-[calc(100vh-270px)] overflow-auto">
                <div class="flex items-center justify-between gap-3">
                  <div>
                    <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Interview plan</p>
                    <h3 class="text-sm font-semibold text-white">Question track</h3>
                  </div>
                  <span class="text-xs text-brand-200">{{ captureProgressLabel(s) }}</span>
                </div>
                <div class="mt-4 grid grid-cols-2 gap-2 text-xs">
                  <div class="rounded bg-black/20 border border-white/10 p-3">
                    <span class="block text-[9px] uppercase tracking-wider text-gray-500">Status</span>
                    <span class="text-gray-200">{{ sessionStartStateLabel(s) }}</span>
                  </div>
                  <div class="rounded bg-black/20 border border-white/10 p-3">
                    <span class="block text-[9px] uppercase tracking-wider text-gray-500">Coverage</span>
                    <span class="text-gray-200">{{ coveragePercent(s) }}%</span>
                  </div>
                </div>
                <div class="mt-4 space-y-2">
                  @for (q of s.plan.questions || []; track q.id) {
                    <button
                      type="button"
                      class="w-full text-left rounded border border-white/10 bg-white/[0.03] hover:bg-white/[0.06] p-3"
                      [class.ring-1]="selectedQuestionId() === q.id"
                      [class.ring-brand-400]="selectedQuestionId() === q.id"
                      (click)="selectCaptureQuestion(q)"
                    >
                      <div class="flex items-center justify-between gap-2">
                        <span class="text-xs text-brand-300 font-mono">{{ questionDisplayId(q) }}</span>
                        <span
                          [class]="questionStateLabel(s, q) === 'current'
                            ? 'text-[10px] uppercase tracking-wider px-2 py-0.5 rounded bg-brand-500/20 text-brand-100'
                            : 'text-[10px] uppercase tracking-wider px-2 py-0.5 rounded bg-white/5 text-gray-500'"
                        >
                          {{ questionStateLabel(s, q) }}
                        </span>
                      </div>
                      <div class="mt-2 text-sm text-gray-100 leading-snug line-clamp-3">{{ questionText(q) }}</div>
                      <div class="mt-3 text-[10px] text-gray-500">{{ q.estimated_minutes || 3 }} min expected</div>
                    </button>
                  }
                </div>
              </aside>

              <main class="t-card rounded-lg p-4 min-h-[calc(100vh-270px)] flex flex-col">
                <div class="rounded bg-brand-500/10 border border-brand-400/20 p-4">
                  <div class="flex items-start justify-between gap-3">
                    <div>
                      <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-200">Current prompt</p>
                      <p class="mt-2 text-lg text-white leading-relaxed">{{ currentPromptText() || 'Select a question to begin capture.' }}</p>
                    </div>
                    <button
                      type="button"
                      class="shrink-0 inline-flex items-center gap-2 px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-xs text-gray-200 ring-1 ring-white/10"
                      [disabled]="!currentQuestion()"
                      (click)="readCurrentQuestion()"
                    >
                      <app-icon name="volume-2" [size]="14" /> Read
                    </button>
                  </div>
                </div>

                <div class="mt-4 flex-1 flex flex-col gap-3 min-h-0">
                  <div class="flex items-center justify-between gap-3">
                    <div>
                      <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Conversation</p>
                      <h3 class="text-sm font-semibold text-white">{{ voiceStateLabel() }}</h3>
                    </div>
                    @if (lastConversationStep(); as step) {
                      <span class="text-xs px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">
                        {{ step.intent }} · {{ (step.confidence * 100).toFixed(0) }}%
                      </span>
                    }
                  </div>
                  <div class="flex-1 min-h-80 rounded bg-black/20 border border-white/10 p-4 overflow-auto space-y-3">
                    <article class="rounded border border-brand-400/20 bg-brand-500/10 p-4">
                      <div class="flex items-center justify-between gap-3">
                        <span class="ck-mono text-[10px] uppercase tracking-wider text-brand-200">Agentium</span>
                        <span class="text-[10px] text-gray-500">{{ currentQuestion()?.estimated_minutes || 3 }} min</span>
                      </div>
                      <p class="mt-2 text-sm text-gray-100 leading-relaxed">
                        {{ currentPromptText() || 'The next interviewer prompt will appear here.' }}
                      </p>
                    </article>
                    @for (event of textEvents().slice(-5); track event.id) {
                      <article class="rounded border border-white/10 bg-white/[0.03] p-4">
                        <div class="flex items-center justify-between gap-3">
                          <span class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">
                            {{ conversationEventLabel(event) }}
                          </span>
                          <button type="button" class="text-xs text-brand-200 hover:text-brand-100" (click)="beginAmend(event)">
                            Amend
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
                              Apply correction
                            </button>
                            <button type="button" class="px-3 py-1.5 rounded bg-white/5 hover:bg-white/10 text-xs text-gray-300" (click)="editingEventId.set(null)">
                              Cancel
                            </button>
                          </div>
                        } @else if (eventDisplayText(event); as text) {
                          <p class="mt-2 text-sm text-gray-200 leading-relaxed whitespace-pre-wrap">{{ text }}</p>
                        }
                      </article>
                    } @empty {
                      <div class="rounded border border-dashed border-white/10 bg-black/20 p-6 text-center">
                        <p class="text-sm text-gray-400">No expert answer captured yet.</p>
                        <p class="mt-1 text-xs text-gray-600">Start the session, then answer by voice or type below.</p>
                      </div>
                    }
                    @if (answer.trim()) {
                      <article class="rounded border border-emerald-400/20 bg-emerald-500/10 p-4">
                        <span class="ck-mono text-[10px] uppercase tracking-wider text-emerald-200">Draft answer</span>
                        <p class="mt-2 text-sm text-gray-100 leading-relaxed whitespace-pre-wrap">{{ answer }}</p>
                      </article>
                    }
                  </div>
                  @if (conversationMode() === 'manual') {
                    <textarea
                      class="w-full min-h-28 rounded bg-black/30 border border-white/10 px-4 py-3 text-sm text-white leading-relaxed"
                      [(ngModel)]="answer"
                      (ngModelChange)="onAnswerDraftChange()"
                      placeholder="Type or correct the expert answer before evaluation..."
                    ></textarea>
                  }
                </div>

                <div class="mt-4 sticky bottom-3 rounded bg-black/70 border border-white/10 p-3 backdrop-blur">
                  <div class="flex flex-wrap items-center gap-3">
                    @if (sessionHasStarted(s)) {
                      <button
                        type="button"
                        class="inline-flex items-center gap-2 px-4 py-2.5 rounded bg-brand-500 hover:bg-brand-400 text-sm font-semibold text-white disabled:opacity-50"
                        [disabled]="transcribing() || !canCaptureExecute(s)"
                        (click)="conversationMode() === 'conversation_only' ? toggleConversationSession() : toggleRecording()"
                      >
                        <app-icon [name]="conversationPrimaryIcon()" [size]="15" />
                        {{ conversationPrimaryLabel() }}
                      </button>
                      @if (speaking()) {
                        <button
                          type="button"
                          class="inline-flex items-center gap-2 px-3 py-2.5 rounded bg-amber-500/20 hover:bg-amber-500/30 text-sm text-amber-100 ring-1 ring-amber-400/20"
                          (click)="interruptSpeech()"
                        >
                          <app-icon name="pause" [size]="14" /> Interrupt AI
                        </button>
                      }
                    } @else {
                      <button
                        type="button"
                        class="inline-flex items-center gap-2 px-4 py-2.5 rounded bg-brand-500 hover:bg-brand-400 text-sm font-semibold text-white disabled:opacity-50"
                        [disabled]="loading() || !canCaptureExecute(s)"
                        (click)="startGuidedSession(s)"
                      >
                        <app-icon [name]="planStartIcon(s)" [size]="15" />
                        {{ planStartLabel(s) }}
                      </button>
                    }
                    @if (conversationMode() === 'manual' && sessionHasStarted(s)) {
                      <button
                        type="button"
                        class="inline-flex items-center gap-2 px-3 py-2.5 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-200 ring-1 ring-white/10 disabled:opacity-50"
                        [disabled]="!answer.trim() || !canCaptureUpdate(s)"
                        (click)="sendAnswer(s)"
                      >
                        <app-icon name="send" [size]="14" /> Evaluate answer
                      </button>
                      <button
                        type="button"
                        class="inline-flex items-center gap-2 px-3 py-2.5 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-200 ring-1 ring-white/10 disabled:opacity-50"
                        [disabled]="!canProposalSubmit(s)"
                        (click)="createProposal(s)"
                      >
                        <app-icon name="check-circle-2" [size]="14" /> Create proposal
                      </button>
                    }
                    <div class="min-w-40 flex-1 flex items-center gap-3 rounded bg-white/[0.03] px-3 py-2">
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
                          <div class="text-[10px] text-gray-500 truncate">cascade · en-fr · retrieval prefetch</div>
                        }
                      </div>
                    </div>
                    <div class="flex items-center gap-2 text-xs text-gray-400">
                      <span class="px-2 py-1 rounded bg-white/5">{{ sessionStartStateLabel(s) }}</span>
                      <span class="px-2 py-1 rounded bg-white/5">{{ recording() ? 'recording' : 'ready' }}</span>
                      <span class="px-2 py-1 rounded bg-white/5">{{ speaking() ? 'speaking' : 'tts idle' }}</span>
                    </div>
                  </div>
                </div>

              </main>

              <aside class="space-y-4 max-h-[calc(100vh-270px)] overflow-auto">
                <section class="t-card rounded-lg p-4">
                  <div class="flex items-center justify-between gap-3">
                    <div>
                      <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Quality panel</p>
                      <h3 class="text-sm font-semibold text-white mt-1">{{ answerQualityHeadline() }}</h3>
                    </div>
                    <span class="text-xs px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">
                      {{ coveragePercent(s) }}%
                    </span>
                  </div>
                  <div class="mt-3 grid grid-cols-2 gap-2 text-xs">
                    <div class="rounded bg-black/20 border border-white/10 p-3">
                      <span class="block text-[9px] uppercase tracking-wider text-gray-500">Facts</span>
                      <span class="text-gray-200">{{ s.metrics?.['captured_facts'] || proposalFacts().length || 0 }}</span>
                    </div>
                    <div class="rounded bg-black/20 border border-white/10 p-3">
                      <span class="block text-[9px] uppercase tracking-wider text-gray-500">Evidence</span>
                      <span class="text-gray-200">{{ proposalEvidenceCount() }}</span>
                    </div>
                    <div class="rounded bg-black/20 border border-white/10 p-3">
                      <span class="block text-[9px] uppercase tracking-wider text-gray-500">Retrieval</span>
                      <span class="text-gray-200">{{ retrievalLabel() }}</span>
                    </div>
                    <div class="rounded bg-black/20 border border-white/10 p-3">
                      <span class="block text-[9px] uppercase tracking-wider text-gray-500">Voice</span>
                      <span class="text-gray-200">{{ voiceStateLabel() }}</span>
                    </div>
                  </div>
                  @if (lastEvaluation(); as ev) {
                    <div class="mt-3 rounded bg-black/20 border border-white/10 p-3">
                      <div class="flex items-center justify-between gap-3">
                        <span class="text-xs text-gray-200">{{ ev.verdict }}</span>
                        <span class="ck-mono text-[10px] text-brand-200">score {{ ev.score }}</span>
                      </div>
                      @if (nextPrompt()) {
                        <button type="button" class="mt-3 text-left text-sm text-brand-200 hover:text-brand-100" (click)="speak(promptText(nextPrompt()))">
                          {{ promptText(nextPrompt()) }}
                        </button>
                      }
                    </div>
                  } @else {
                    <p class="mt-3 text-xs text-gray-500 leading-relaxed">
                      Quality signals appear after the first evaluated expert answer.
                    </p>
                  }
                </section>

                <section
                  [class]="conversationMode() === 'conversation_only'
                    ? 't-card rounded-lg p-4 bg-brand-500/5 border-brand-400/20'
                    : 't-card rounded-lg p-4'"
                >
                  <div class="flex items-start justify-between gap-3">
                    <div>
                      <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Session mode</p>
                      <h3 class="text-sm font-semibold text-white mt-1">
                        {{ conversationMode() === 'conversation_only' ? 'Conversation' : 'Guided capture' }}
                      </h3>
                    </div>
                    @if (conversationSessionActive()) {
                      <span class="text-xs text-brand-100">Active</span>
                    }
                  </div>
                  <div class="mt-3 grid grid-cols-2 gap-2">
                    <button
                      type="button"
                      [class]="conversationMode() === 'manual'
                        ? 'rounded border border-brand-300 bg-brand-500/15 px-3 py-2 text-left text-brand-100'
                        : 'rounded border border-white/10 bg-white/[0.03] px-3 py-2 text-left text-gray-300 hover:bg-white/[0.06]'"
                      (click)="setConversationMode('manual')"
                    >
                      <span class="flex items-center gap-2 text-xs font-semibold">
                        <app-icon name="list-checks" [size]="13" /> Guided
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
                  @if (conversationMode() === 'conversation_only') {
                    <p class="mt-3 text-sm text-white">{{ lastConversationLabel() }}</p>
                    @if (voiceNotice(); as notice) {
                      <p [class]="voiceNoticePanelClass()">{{ notice }}</p>
                    }
                    @if (nextPrompt()) {
                      <p class="mt-3 text-xs text-gray-300 leading-relaxed">{{ promptText(nextPrompt()) }}</p>
                    }
                  }
                </section>

                <section class="t-card rounded-lg p-4">
                  <div class="flex items-center justify-between gap-3">
                    <div>
                      <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Conversation state</p>
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

                <section class="t-card rounded-lg p-4">
                  <div class="flex items-center justify-between gap-3">
                    <div>
                      <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Live context</p>
                      <h3 class="text-sm font-semibold text-white">{{ retrievalLabel() }}</h3>
                    </div>
                    @if (retrieval().latency_ms !== undefined) {
                      <span class="text-xs text-gray-500">{{ retrieval().latency_ms }} ms</span>
                    }
                  </div>
                  @if (retrieval().chunks.length) {
                    <div class="mt-3 space-y-2">
                      @for (chunk of retrieval().chunks.slice(0, 3); track retrievalChunkTrack($index, chunk)) {
                        <p class="rounded bg-black/20 border border-white/10 p-3 text-xs text-gray-400 line-clamp-3">{{ chunk }}</p>
                      }
                    </div>
                  } @else {
                    <p class="mt-3 text-xs text-gray-500 leading-relaxed">
                      Context appears here as the expert answer becomes specific enough. The conversation does not wait for it.
                    </p>
                  }
                </section>

                @if (proposal(); as p) {
                  <section class="t-card rounded-lg p-4">
                    <div class="flex items-center justify-between gap-3">
                      <div>
                        <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Proposal draft</p>
                        <h3 class="text-sm font-semibold text-white">{{ proposalFacts().length }} facts</h3>
                      </div>
                      <span class="text-xs text-gray-400">{{ p.status }}</span>
                    </div>
                    <button type="button" class="mt-3 w-full px-3 py-2 rounded bg-brand-500/20 text-brand-100 ring-1 ring-brand-300/30" (click)="goSurface('review')">
                      Review proposal
                    </button>
                  </section>
                }
              </aside>
            </section>
          </section>
        } @else {
          <section class="t-card rounded-lg p-8 text-center text-gray-400">
            Prepare a capture plan before opening the live cockpit.
          </section>
        }
      }

      @if (activeSurface() === 'plan') {
        @if (session(); as s) {
          <section class="grid xl:grid-cols-[minmax(0,1fr)_420px] gap-5">
            <div class="t-card rounded-lg p-5 space-y-4">
              <div class="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Interview plan</p>
                  <h2 class="text-lg font-semibold text-white mt-1">{{ s.title }}</h2>
                  <p class="text-sm text-gray-500 mt-1 max-w-3xl">{{ s.objective }}</p>
                </div>
                <button
                  type="button"
                  class="inline-flex items-center gap-2 px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-200 ring-1 ring-white/10"
                  (click)="goSurface('session')"
                >
                  <app-icon name="eye" [size]="14" /> Preview cockpit
                </button>
              </div>

              <div class="grid md:grid-cols-3 gap-3 text-sm">
                <div class="rounded bg-black/20 border border-white/10 p-3">
                  <div class="text-[10px] uppercase tracking-wider text-gray-500">Questions</div>
                  <div class="text-2xl text-white font-semibold">{{ s.plan.questions?.length || 0 }}</div>
                </div>
                <div class="rounded bg-black/20 border border-white/10 p-3">
                  <div class="text-[10px] uppercase tracking-wider text-gray-500">Estimated duration</div>
                  <div class="text-2xl text-white font-semibold">{{ planDurationMinutes(s) }} min</div>
                </div>
                <div class="rounded bg-black/20 border border-white/10 p-3">
                  <div class="text-[10px] uppercase tracking-wider text-gray-500">Knowledge target</div>
                  <div class="text-sm text-gray-200 mt-2 truncate">{{ selectedContext()?.environment_state?.collection || 'Workspace defaults' }}</div>
                </div>
              </div>

              <div class="space-y-3">
                @for (q of s.plan.questions || []; track q.id) {
                  <button
                    type="button"
                    class="w-full text-left rounded border border-white/10 bg-white/[0.03] hover:bg-white/[0.06] p-5"
                    [class.ring-1]="selectedQuestionId() === q.id"
                    [class.ring-brand-400]="selectedQuestionId() === q.id"
                    (click)="selectedQuestionId.set(q.id)"
                  >
                    <div class="flex flex-wrap items-center justify-between gap-3">
                      <div class="flex items-center gap-3">
                        <span class="ck-mono text-xs text-brand-300">{{ questionDisplayId(q) }}</span>
                        <span
                          [class]="questionStateLabel(s, q) === 'current'
                            ? 'text-[10px] uppercase tracking-wider px-2 py-1 rounded bg-brand-500/20 text-brand-100'
                            : 'text-[10px] uppercase tracking-wider px-2 py-1 rounded bg-white/5 text-gray-400'"
                        >
                          {{ questionStateLabel(s, q) }}
                        </span>
                      </div>
                      <span class="text-xs text-gray-500">{{ q.estimated_minutes || 3 }} min</span>
                    </div>
                    <p class="mt-4 text-base text-gray-100 leading-relaxed">{{ questionText(q) }}</p>
                  </button>
                }
              </div>
            </div>

            <aside class="t-card rounded-lg p-5 space-y-4 xl:sticky xl:top-4">
              <div>
                <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Session setup</p>
                <h3 class="text-sm font-semibold text-white mt-1">Ready for capture</h3>
              </div>
              <div class="space-y-2 text-xs">
                <div class="rounded bg-black/20 border border-white/10 p-3">
                  <span class="block text-[9px] uppercase tracking-wider text-gray-500">Context</span>
                  <span class="text-gray-200">{{ contextLabel(s.context_id) }}</span>
                </div>
                <div class="rounded bg-black/20 border border-white/10 p-3">
                  <span class="block text-[9px] uppercase tracking-wider text-gray-500">Expert</span>
                  <span class="text-gray-200">{{ expertProfile }}</span>
                </div>
                <div class="rounded bg-black/20 border border-white/10 p-3">
                  <span class="block text-[9px] uppercase tracking-wider text-gray-500">Runtime</span>
                  <span class="text-gray-200">cascade · chunked capture · segmented TTS</span>
                </div>
                <div class="rounded bg-black/20 border border-white/10 p-3">
                  <span class="block text-[9px] uppercase tracking-wider text-gray-500">Status</span>
                  <span class="text-gray-200">{{ sessionStartStateLabel(s) }}</span>
                </div>
              </div>
              <div class="rounded bg-black/20 border border-white/10 p-3">
                <span class="block text-[9px] uppercase tracking-wider text-gray-500 mb-2">Session mode</span>
                <div class="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    [class]="conversationMode() === 'manual'
                      ? 'rounded border border-brand-300 bg-brand-500/15 px-3 py-2 text-left text-brand-100'
                      : 'rounded border border-white/10 bg-white/[0.03] px-3 py-2 text-left text-gray-300 hover:bg-white/[0.06]'"
                    (click)="setConversationMode('manual')"
                  >
                    <span class="flex items-center gap-2 text-xs font-semibold">
                      <app-icon name="list-checks" [size]="13" /> Guided
                    </span>
                    <span class="mt-1 block text-[10px] text-gray-500">Turn by turn</span>
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
                    <span class="mt-1 block text-[10px] text-gray-500">Voice led</span>
                  </button>
                </div>
              </div>
              <button
                type="button"
                class="w-full inline-flex items-center justify-center gap-2 px-3 py-3 rounded bg-brand-500 hover:bg-brand-400 text-sm font-semibold text-white disabled:opacity-50"
                [disabled]="loading() || !canCaptureExecute(s)"
                (click)="startGuidedSession(s)"
              >
                <app-icon [name]="planStartIcon(s)" [size]="14" /> {{ planStartLabel(s) }}
              </button>
            </aside>
          </section>
        } @else {
          <section class="max-w-5xl mx-auto py-8 space-y-7">
            <div>
              <p class="ck-mono text-[10px] uppercase tracking-[0.18em] text-gray-500">Step 2 · Plan mode</p>
              <h2 class="mt-2 text-3xl text-white font-semibold">How should the conversation be structured?</h2>
              <p class="mt-2 text-sm text-gray-400 max-w-3xl">
                The choice changes how the AI interviewer behaves and how rigorous the resulting proposal will be.
              </p>
            </div>

            <div class="space-y-3">
              @for (mode of planModes; track mode.id) {
                <button
                  type="button"
                  [class]="selectedPlanMode === mode.id
                    ? 'w-full text-left rounded-lg border border-brand-300 bg-brand-500/10 p-5 ring-1 ring-brand-300/40'
                    : 'w-full text-left rounded-lg border border-white/10 bg-white/[0.03] hover:bg-white/[0.06] p-5'"
                  (click)="selectedPlanMode = mode.id"
                >
                  <div class="flex items-center gap-4">
                    <span
                      [class]="selectedPlanMode === mode.id
                        ? 'inline-flex h-11 w-11 items-center justify-center rounded border border-brand-300 text-brand-200'
                        : 'inline-flex h-11 w-11 items-center justify-center rounded border border-white/10 text-gray-500'"
                    >
                      <app-icon [name]="mode.icon" [size]="18" />
                    </span>
                    <span class="min-w-0 flex-1">
                      <span class="flex flex-wrap items-center gap-2">
                        <span class="text-base font-semibold text-white">{{ mode.label }}</span>
                        @if (mode.recommended) {
                          <span class="ck-mono text-[10px] uppercase tracking-wider px-2 py-0.5 rounded border border-brand-300/40 text-brand-200">
                            Recommended
                          </span>
                        }
                      </span>
                      <span class="mt-1 block text-sm text-gray-500">{{ mode.description }}</span>
                    </span>
                    <span
                      [class]="selectedPlanMode === mode.id
                        ? 'inline-flex h-5 w-5 items-center justify-center rounded-full bg-brand-300 text-black'
                        : 'inline-flex h-5 w-5 rounded-full border border-white/15'"
                    >
                      @if (selectedPlanMode === mode.id) {
                        <app-icon name="check" [size]="12" />
                      }
                    </span>
                  </div>
                </button>
              }
            </div>

            <div class="flex items-center justify-between gap-3 pt-4">
              <button
                type="button"
                class="inline-flex items-center gap-2 px-4 py-2 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-300 ring-1 ring-white/10"
                (click)="goSurface('prep')"
              >
                <app-icon name="arrow-left" [size]="14" /> Back
              </button>
              <button
                type="button"
                class="inline-flex items-center gap-2 px-5 py-2.5 rounded bg-brand-300 hover:bg-brand-200 text-sm font-semibold text-black disabled:opacity-50"
                [disabled]="loading() || !canCaptureCreate()"
                (click)="createPlan()"
              >
                {{ loading() ? 'Generating plan...' : 'Generate plan' }}
                <app-icon name="arrow-right" [size]="14" />
              </button>
            </div>
          </section>
        }
      }

      @if (activeSurface() === 'review') {
        <section class="grid xl:grid-cols-[1fr_320px] gap-5">
          <div class="t-card rounded-lg p-5 space-y-4">
            <div class="flex items-start justify-between gap-4">
              <div>
                <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Knowledge update proposal</p>
                <h2 class="text-lg font-semibold text-white">
                  {{ proposal()?.proposal?.title || session()?.title || 'Review changes before ingestion' }}
                </h2>
                <p class="text-sm text-gray-500 mt-1 max-w-3xl">
                  Fact-level review keeps the conversation trace auditable without making raw transcription the primary user experience.
                </p>
              </div>
              @if (proposal(); as p) {
                <span class="text-xs px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">{{ p.status }}</span>
              }
            </div>

            @if (proposalFacts().length) {
              <div class="space-y-3">
                @for (fact of proposalFacts(); track proposalFactTrack($index, fact)) {
                  <article [class]="proposalFactCardClass($index, fact)">
                    <div class="flex items-start justify-between gap-3">
                      <div class="min-w-0">
                        <div class="flex flex-wrap items-center gap-2">
                          <span class="ck-mono text-[10px] uppercase tracking-wider px-2 py-1 rounded bg-brand-500/15 text-brand-200">
                            {{ proposalFactType(fact) }}
                          </span>
                          <span class="text-xs text-gray-500">{{ proposalFactConfidence(fact) }}</span>
                          <span
                            [class]="proposalFactDecision($index, fact) === 'accept'
                              ? 'text-xs text-emerald-200'
                              : proposalFactDecision($index, fact) === 'reject'
                                ? 'text-xs text-red-200'
                                : 'text-xs text-gray-500'"
                          >
                            {{ proposalFactDecisionLabel($index, fact) }}
                          </span>
                          @if (fact.amended) {
                            <span class="text-xs text-amber-200">HITL amended</span>
                          }
                        </div>
                        @if (editingProposalFactKey() === proposalFactKey($index, fact)) {
                          <textarea
                            class="mt-3 w-full min-h-24 rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white"
                            [ngModel]="proposalFactEditText"
                            (ngModelChange)="proposalFactEditText = $event"
                          ></textarea>
                          <div class="mt-2 flex gap-2">
                            <button type="button" class="px-3 py-1.5 rounded bg-brand-500 hover:bg-brand-400 text-xs text-white" (click)="saveProposalFactEdit($index, fact)">
                              Save edit
                            </button>
                            <button type="button" class="px-3 py-1.5 rounded bg-white/5 hover:bg-white/10 text-xs text-gray-300" (click)="cancelProposalFactEdit()">
                              Cancel
                            </button>
                          </div>
                        } @else {
                          <p class="mt-3 text-sm text-gray-100 leading-relaxed whitespace-pre-wrap">{{ proposalFactReviewText($index, fact) }}</p>
                        }
                        @if (fact.raw_text && fact.raw_text !== proposalFactText(fact)) {
                          <p class="mt-2 text-xs text-gray-500">Raw: {{ fact.raw_text }}</p>
                        }
                      </div>
                      <div class="shrink-0 grid gap-1.5 w-28">
                        <button
                          type="button"
                          [class]="proposalFactDecision($index, fact) === 'accept'
                            ? 'px-2 py-1.5 rounded bg-emerald-500/20 text-xs text-emerald-100 ring-1 ring-emerald-400/30'
                            : 'px-2 py-1.5 rounded bg-white/5 hover:bg-white/10 text-xs text-gray-300 ring-1 ring-white/10'"
                          (click)="setProposalFactDecision($index, fact, 'accept')"
                        >
                          Accept
                        </button>
                        <button
                          type="button"
                          [class]="proposalFactDecision($index, fact) === 'reject'
                            ? 'px-2 py-1.5 rounded bg-red-500/20 text-xs text-red-100 ring-1 ring-red-400/30'
                            : 'px-2 py-1.5 rounded bg-white/5 hover:bg-white/10 text-xs text-gray-300 ring-1 ring-white/10'"
                          (click)="setProposalFactDecision($index, fact, 'reject')"
                        >
                          Reject
                        </button>
                        <button
                          type="button"
                          class="px-2 py-1.5 rounded bg-white/5 hover:bg-white/10 text-xs text-gray-300 ring-1 ring-white/10"
                          (click)="beginProposalFactEdit($index, fact)"
                        >
                          Edit
                        </button>
                      </div>
                    </div>
                    @if (fact.retrieval_refs?.length) {
                      <div class="mt-3 rounded bg-white/[0.03] border border-white/10 p-3">
                        <div class="text-[10px] uppercase tracking-wider text-gray-500">Evidence</div>
                        @for (ref of (fact.retrieval_refs || []).slice(0, 2); track ref.title || ref.source || ref.preview) {
                          <p class="mt-2 text-xs text-gray-400 line-clamp-2">
                            <span class="text-gray-300">{{ ref.title || ref.source || 'Retrieved context' }}</span>
                            @if (ref.preview) { · {{ ref.preview }} }
                          </p>
                        }
                      </div>
                    }
                  </article>
                }
              </div>
            } @else {
              <div class="rounded border border-dashed border-white/10 bg-black/20 p-8 text-center text-gray-500">
                No structured fact yet. Capture or amend at least one substantive expert answer, then create a proposal.
              </div>
            }

            @if (proposal()?.proposal?.recommended_ingestion?.content) {
              <details class="rounded border border-white/10 bg-black/20 p-3">
                <summary class="cursor-pointer text-sm text-gray-300">Markdown ingestion preview</summary>
                <pre class="mt-3 whitespace-pre-wrap text-xs text-gray-400 max-h-72 overflow-auto">{{ proposal()?.proposal?.recommended_ingestion?.content }}</pre>
              </details>
            }
          </div>

          <aside class="t-card rounded-lg p-5 space-y-4">
            <div>
              <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Review controls</p>
              <h3 class="text-sm font-semibold text-white mt-1">Human validation</h3>
              @if (iamRoleBanner(); as banner) {
                <p class="mt-2 text-xs text-brand-100/80">{{ banner }}</p>
              }
            </div>
            <div class="grid grid-cols-2 gap-2 text-xs">
              <div class="rounded bg-black/20 border border-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500">Facts</div>
                <div class="text-xl text-white font-semibold">{{ proposalFacts().length }}</div>
              </div>
              <div class="rounded bg-black/20 border border-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500">Evidence</div>
                <div class="text-xl text-white font-semibold">{{ proposalEvidenceCount() }}</div>
              </div>
              <div class="rounded bg-black/20 border border-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500">Accepted</div>
                <div class="text-xl text-white font-semibold">{{ acceptedProposalFactCount() }}</div>
              </div>
              <div class="rounded bg-black/20 border border-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500">Rejected</div>
                <div class="text-xl text-white font-semibold">{{ rejectedProposalFactCount() }}</div>
              </div>
            </div>
            @if (proposalOpenQuestions().length) {
              <div class="rounded bg-amber-500/10 border border-amber-400/20 p-3">
                <div class="text-[10px] uppercase tracking-wider text-amber-200">Open follow-ups</div>
                @for (item of proposalOpenQuestions(); track item.gap_id || item.follow_up || item.reason) {
                  <p class="mt-2 text-xs text-amber-100/80">{{ item.follow_up || item.reason }}</p>
                }
              </div>
            }
            @if (proposal(); as p) {
              <button
                type="button"
                class="w-full inline-flex items-center justify-center gap-2 px-3 py-2 rounded bg-emerald-500/20 hover:bg-emerald-500/30 text-sm text-emerald-100 ring-1 ring-emerald-400/20 disabled:opacity-50"
                [disabled]="!proposalFacts().length || !canProposalReview(p)"
                (click)="acceptProposal(p.id)"
              >
                <app-icon name="check-circle-2" [size]="14" /> Accept & ingest selected
              </button>
              <button
                type="button"
                class="w-full inline-flex items-center justify-center gap-2 px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-200 ring-1 ring-white/10"
                (click)="goSurface('session')"
              >
                <app-icon name="message-square" [size]="14" /> Continue capture
              </button>
            } @else if (session(); as s) {
              <button
                type="button"
                class="w-full inline-flex items-center justify-center gap-2 px-3 py-2 rounded bg-brand-500 hover:bg-brand-400 text-sm text-white disabled:opacity-50"
                [disabled]="!canProposalSubmit(s)"
                (click)="createProposal(s)"
              >
                <app-icon name="check-circle-2" [size]="14" /> Create proposal
              </button>
            }
          </aside>
        </section>
      }
    </section>
  `,
})
export class KnowledgeCaptureComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly route = inject(ActivatedRoute);
  private readonly zoom = inject(ZoomContextService);
  private readonly voiceSession = inject(VoiceSessionService);
  private readonly workspace = inject(WorkspaceService);
  readonly permissions = inject(PermissionsService);

  objective =
    'Capture tacit troubleshooting and offer reasoning from a senior industrial expert.';
  sessionTitle = 'Expert Knowledge Capture';
  expertProfile = 'Senior field engineer';
  durationMinutes = 20;
  contextId = '';
  systemId = '';
  answer = '';
  selectedDomain = 'technical';
  selectedPlanMode = 'ai_plan';
  readonly captureDomains = [
    { id: 'technical', label: 'Technical', description: 'Engineering, processes, machines' },
    { id: 'commercial', label: 'Commercial', description: 'Markets, accounts, deals' },
    { id: 'innovation', label: 'Innovation', description: 'R&D, prototypes, exploration' },
  ];
  readonly planModes = [
    {
      id: 'ai_plan',
      label: 'AI proposes a plan',
      description: 'Generates an interview agenda from your objective and the linked knowledge gaps. Editable before start.',
      icon: 'zap',
      recommended: true,
    },
    {
      id: 'provided_plan',
      label: 'I provide the plan',
      description: 'You write or paste the agenda. AI reviews and suggests refinements.',
      icon: 'layout-grid',
      recommended: false,
    },
    {
      id: 'free_conversation',
      label: 'No plan — free conversation',
      description: 'AI follows the expert. Objective is required; coverage and rigor are lower.',
      icon: 'activity',
      recommended: false,
    },
  ];
  readonly modelSteps = [
    {
      eyebrow: 'Capability',
      label: 'Expert Knowledge Capture',
      description: 'The business function: preserve expert reasoning and tacit knowledge.',
    },
    {
      eyebrow: 'System',
      label: 'Guided session runtime',
      description: 'Runs a plan with voice, evaluator and structuring skills.',
    },
    {
      eyebrow: 'Context',
      label: 'Knowledge scope',
      description: 'Selects collections, ACLs and constraints for the interview.',
    },
    {
      eyebrow: 'Knowledge',
      label: 'Reviewed update',
      description: 'Receives validated proposals after human review.',
    },
  ];

  readonly loading = signal(false);
  readonly contexts = signal<ContextOption[]>([]);
  readonly systems = signal<SystemOption[]>([]);
  readonly systemScoped = signal(false);
  readonly activeSurface = signal<CaptureSurfaceView>('dashboard');
  readonly dashboardSessions = signal<CaptureSession[]>([]);
  readonly dashboardProposals = signal<CaptureProposal[]>([]);
  readonly conversationMode = signal<ConversationMode>('manual');
  readonly lastConversationStep = signal<ConversationStepResponse | null>(null);
  readonly recording = signal(false);
  readonly transcribing = signal(false);
  readonly speaking = signal(false);
  readonly conversationSessionActive = signal(false);
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
  readonly editingProposalFactKey = signal<string | null>(null);
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

  readonly surfaceNav: Array<{ id: CaptureSurfaceView; label: string; icon: string; step: number }> = [
    { id: 'dashboard', label: 'Sessions', icon: 'layout-dashboard', step: 1 },
    { id: 'prep', label: 'Preparation', icon: 'sliders-horizontal', step: 2 },
    { id: 'plan', label: 'Plan', icon: 'list-checks', step: 3 },
    { id: 'session', label: 'Capture', icon: 'mic', step: 4 },
    { id: 'review', label: 'Proposal', icon: 'check-circle-2', step: 5 },
  ];
  readonly voiceWaveBars = [10, 18, 26, 14, 22, 30, 16, 24, 12, 20];
  readonly workspaceAccessRoute = computed(() => {
    const slug = this.workspace.current()?.slug || this.workspace.currentSlug();
    return slug ? ['/workspace', slug, 'access'] : '/governance/access';
  });

  private recorder: MediaRecorder | null = null;
  private chunks: BlobPart[] = [];
  private stream: MediaStream | null = null;
  private partialTranscriptionInFlight = false;
  private prefetchInFlight = false;
  private lastPrefetchText = '';
  private lastPrefetchAt = 0;
  private currentClientTurnId: string | null = null;
  private activeAudio: HTMLAudioElement | null = null;
  private voiceConnection: VoiceSessionConnection | null = null;
  private pendingVoiceFrameSends: Promise<void>[] = [];
  private audioQueue: string[] = [];
  private revokedAudioUrls: string[] = [];
  private speechGeneration = 0;
  private autoResumeTimer: ReturnType<typeof setTimeout> | null = null;

  ngOnInit(): void {
    this.destroyRef.onDestroy(() => this.closeVoiceConnection());
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
        }
      });
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

  createPlan(): void {
    if (!this.canCaptureCreate()) {
      this.voiceNotice.set('You do not have permission to create Capture sessions in this workspace.');
      return;
    }
    this.loading.set(true);
    this.api
      .createCapturePlan({
        title: this.sessionTitle.trim() || 'Expert Knowledge Capture',
        objective: this.captureObjectiveForPlan(),
        expert_profile: this.expertProfile,
        duration_minutes: Number(this.durationMinutes) || 20,
        context_id: this.contextId || null,
        system_id: this.systemId || null,
        voice_runtime: 'cascade',
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (session) => {
          const typed = session as CaptureSession;
          this.session.set(typed);
          this.zoom.setCurrentCapability(typed.capability_id || null, 'Expert Knowledge Capture');
          this.zoom.setCurrentSystem(typed.system_id || null, this.systemLabel(typed.system_id));
          this.zoom.setCurrentContext(typed.context_id || null, this.contextLabel(typed.context_id));
          this.selectedQuestionId.set(typed.plan.questions?.[0]?.id || null);
          this.refreshEvents(typed.id);
          this.refreshDashboard();
          this.activeSurface.set('plan');
          this.loading.set(false);
        },
        error: () => this.loading.set(false),
      });
  }

  goSurface(view: CaptureSurfaceView): void {
    this.activeSurface.set(view);
    if (view === 'dashboard') {
      this.refreshDashboard();
    }
    if (view === 'review' && !this.proposal() && this.session()) {
      this.refreshDashboard();
    }
  }

  async startGuidedSession(session: CaptureSession): Promise<void> {
    if (this.loading()) return;
    if (!this.canCaptureExecute(session)) {
      this.setVoiceNotice('You do not have permission to start this Capture session.', 'error');
      return;
    }
    this.loading.set(true);
    const conversationOnly = this.conversationMode() === 'conversation_only';
    let armed = true;
    if (conversationOnly) {
      this.conversationSessionActive.set(true);
      this.setVoiceNotice('Preparing microphone access for the conversation session.', 'info');
      armed = await this.ensureAudioStream();
      if (!armed) {
        this.conversationSessionActive.set(false);
        this.voiceState.set('idle');
        this.loading.set(false);
        return;
      }
    }
    this.api
      .startCaptureSession(session.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (payload) => {
          const typed = payload as CaptureSession;
          this.session.set(typed);
          const questions = typed.plan.questions || [];
          const selected = this.selectedQuestionId();
          this.selectedQuestionId.set(
            selected && questions.some((question) => question.id === selected)
              ? selected
              : questions[0]?.id || null,
          );
          this.refreshEvents(typed.id);
          this.refreshDashboard();
          this.activeSurface.set('session');
          this.loading.set(false);
          if (conversationOnly && armed) {
            this.ensureVoiceConnection(typed);
            const firstPrompt = this.currentPromptText();
            if (firstPrompt) {
              this.speak(firstPrompt);
            } else {
              void this.startRecordingTurn();
            }
          }
        },
        error: () => {
          if (conversationOnly) {
            this.stopConversationSession();
          }
          this.setVoiceNotice('Session start failed. Check backend availability, then retry.', 'error');
          this.loading.set(false);
        },
      });
  }

  refreshDashboard(): void {
    this.api
      .listCaptureSessions()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((payload) => {
        const sessions = (payload as { sessions?: CaptureSession[] }).sessions || [];
        const scoped = this.systemId
          ? sessions.filter((row) => !row.system_id || row.system_id === this.systemId)
          : sessions;
        this.dashboardSessions.set(scoped.slice(0, 8));
      });
    this.api
      .listCaptureProposals()
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
      this.editingProposalFactKey.set(null);
      this.proposalFactEditText = '';
    }
  }

  openDashboardSession(row: CaptureSession): void {
    this.session.set(row);
    this.setProposal(null);
    this.selectedQuestionId.set(row.plan.questions?.[0]?.id || null);
    this.refreshEvents(row.id);
    this.activeSurface.set(row.status === 'completed' ? 'review' : 'session');
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

  stepIsComplete(view: CaptureSurfaceView): boolean {
    const order: CaptureSurfaceView[] = ['dashboard', 'prep', 'plan', 'session', 'review'];
    const activeIndex = order.indexOf(this.activeSurface());
    const viewIndex = order.indexOf(view);
    if (viewIndex >= 0 && activeIndex > viewIndex) return true;
    if (view === 'prep') return Boolean(this.session());
    if (view === 'plan') return Boolean(this.session());
    if (view === 'session') return (this.session()?.metrics?.['captured_facts'] || 0) > 0;
    if (view === 'review') return Boolean(this.proposal());
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
    return (
      this.permissions.can('knowledge_proposal', 'review_decide', resource) &&
      this.permissions.can('knowledge_proposal', 'trigger_ingestion', resource)
    );
  }

  isAuthor(session?: CaptureSession | null): boolean {
    return this.permissions.isAuthor({ owner_user_id: session?.created_by_user_id || null });
  }

  iamRoleBanner(): string | null {
    if (!this.permissions.matrix()) return null;
    if (this.permissions.isReviewerOrAdmin()) return `IAM: ${this.permissions.roleLabel()} can review workspace proposals.`;
    if (this.canCaptureCreate()) return `IAM: ${this.permissions.roleLabel()} can capture own sessions.`;
    return `IAM: ${this.permissions.roleLabel()} has limited Capture access.`;
  }

  selectedContext(): ContextOption | null {
    return this.contexts().find((ctx) => ctx.id === this.contextId) || null;
  }

  onContextChange(contextId: string): void {
    const ctx = this.contexts().find((item) => item.id === contextId);
    this.zoom.setCurrentContext(ctx?.id || null, ctx?.name || null);
  }

  contextLabel(contextId?: string | null): string {
    if (!contextId) {
      return 'Workspace defaults';
    }
    return this.contexts().find((ctx) => ctx.id === contextId)?.name || contextId.slice(0, 8);
  }

  questionText(question?: CaptureQuestion | null): string {
    return this.promptText(question?.question || '');
  }

  currentPromptText(): string | null {
    const question = this.currentQuestion();
    if (question) {
      return this.questionText(question);
    }
    const prompt = this.nextPrompt();
    return prompt ? this.promptText(prompt) : null;
  }

  promptText(text?: string | null): string {
    const clean = (text || '').trim();
    if (!clean) return '';
    return this.isRuntimeCapturePrompt(clean) ? this.businessDecisionQuestion() : clean;
  }

  private captureObjectiveForPlan(): string {
    const clean = (this.objective || '').trim();
    if (!clean || this.isRuntimeCaptureObjective(clean)) {
      return this.defaultBusinessObjective();
    }
    return clean;
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
      this.setVoiceNotice('You do not have permission to update this Capture session.', 'error');
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
      .filter((event) => priorities[event.event_type] && (
        Boolean(this.eventDisplayText(event)) ||
        event.event_type === 'proposal_generated' ||
        event.event_type === 'proposal_reviewed'
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

  refreshEvents(sessionId: string): void {
    this.api
      .listCaptureEvents(sessionId, undefined, true)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((payload) => {
        const events = (payload as { events?: CaptureEvent[] }).events || [];
        this.events.set(events);
      });
  }

  voiceStateLabel(): string {
    const labels: Record<Voice2VoiceState, string> = {
      idle: 'Idle',
      listening: 'Listening',
      partial_transcribing: 'Live transcription',
      retrieving: 'Retrieving context',
      thinking: 'Evaluating',
      speaking: 'AI speaking',
      interrupted: 'Interrupted',
    };
    return labels[this.voiceState()];
  }

  retrievalLabel(): string {
    const rr = this.retrieval();
    if (rr.status === 'searching') {
      return rr.chunks.length ? `Refreshing · ${rr.chunks.length} chunk(s)` : 'Searching in parallel';
    }
    if (rr.status === 'ready') return `${rr.chunks.length} chunk(s) ready`;
    if (rr.status === 'late') return 'Late context';
    if (rr.status === 'timeout') return 'Timeout, continuing';
    if (rr.status === 'error') return 'Unavailable';
    return 'Standby';
  }

  onAnswerDraftChange(): void {
    const session = this.session();
    if (!session) return;
    this.maybePrefetchRetrieval(session, this.answer);
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
    const total = session.plan.questions?.length || 0;
    if (!total) return 0;
    return Math.round(((session.metrics?.['captured_facts'] || 0) / total) * 100);
  }

  answerQualityHeadline(): string {
    const evaluation = this.lastEvaluation();
    if (!evaluation) return 'Waiting for first answer';
    return `${evaluation.verdict} answer`;
  }

  conversationEventLabel(event: CaptureEvent): string {
    const speaker = (event.speaker || '').toLowerCase();
    if (speaker === 'expert') return `Expert · ${this.transcriptEventShortLabel(event)}`;
    if (speaker === 'system') return `Agentium · ${this.transcriptEventShortLabel(event)}`;
    if (event.event_type === 'proposal_generated') return 'Proposal · generated';
    if (event.event_type === 'proposal_reviewed') return 'Review · completed';
    return `Trace · ${this.transcriptEventShortLabel(event)}`;
  }

  conversationStateHeadline(session: CaptureSession): string {
    if (!this.sessionHasStarted(session)) return 'Ready to start';
    if (this.speaking()) return 'AI asking';
    if (this.recording()) return 'Expert answering';
    if (this.transcribing()) return 'Processing turn';
    if (this.voiceState() === 'thinking') return 'Evaluating answer';
    if (this.proposal()) return 'Proposal ready';
    const step = this.lastConversationStep();
    if (step?.action_taken === 'proposal_deferred_insufficient_facts') return 'More detail needed';
    return this.conversationMode() === 'conversation_only' ? 'Conversation loop ready' : 'Guided capture ready';
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
        label: 'Ready',
        detail: started ? session.status : 'waiting for launch',
        icon: 'play',
        state: started ? 'done' : 'active',
      },
      {
        id: 'prompt',
        label: 'Prompt',
        detail: this.speaking() ? 'AI speaking' : this.currentQuestion()?.id || 'selected question',
        icon: 'volume-2',
        state: !started ? 'pending' : this.speaking() ? 'active' : 'done',
      },
      {
        id: 'answer',
        label: 'Answer',
        detail: this.recording() ? 'recording expert' : this.transcribing() ? 'finalizing transcript' : this.voiceStateLabel(),
        icon: 'mic',
        state: !started ? 'pending' : (this.recording() || this.transcribing() || this.voiceState() === 'thinking') ? 'active' : hasAnswer ? 'done' : 'pending',
      },
      {
        id: 'proposal',
        label: 'Proposal',
        detail: this.proposal() ? `${this.proposalFacts().length} facts` : this.lastConversationLabel(),
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
    if (this.conversationMode() === mode) return;
    this.conversationMode.set(mode);
    this.lastConversationStep.set(null);
    this.stopConversationSession();
  }

  toggleConversationMode(): void {
    this.setConversationMode(this.conversationMode() === 'manual' ? 'conversation_only' : 'manual');
  }

  sessionHasStarted(session: CaptureSession): boolean {
    return session.status !== 'planned';
  }

  sessionStartStateLabel(session: CaptureSession): string {
    if (session.status === 'planned') return 'not started';
    if (session.status === 'active') return 'active';
    return session.status;
  }

  planStartIcon(session?: CaptureSession): string {
    if (session && this.sessionHasStarted(session)) {
      return this.conversationMode() === 'conversation_only' ? 'message-circle' : 'arrow-right';
    }
    return this.conversationMode() === 'conversation_only' ? 'message-circle' : 'play';
  }

  planStartLabel(session?: CaptureSession): string {
    const prefix = session && this.sessionHasStarted(session) ? 'Resume' : 'Start';
    return this.conversationMode() === 'conversation_only'
      ? `${prefix} conversation session`
      : `${prefix} guided session`;
  }

  conversationPrimaryIcon(): string {
    if (this.conversationMode() !== 'conversation_only') {
      return this.recording() ? 'square' : 'mic';
    }
    if (this.recording()) return 'square';
    if (this.speaking()) return 'mic';
    return this.conversationSessionActive() ? 'pause' : 'play';
  }

  conversationPrimaryLabel(): string {
    if (this.conversationMode() !== 'conversation_only') {
      return this.recording()
        ? 'Stop listening'
        : this.speaking()
          ? 'Interrupt & answer'
          : this.transcribing()
            ? 'Transcribing...'
            : 'Listen';
    }
    if (this.transcribing()) return 'Processing turn...';
    if (this.recording()) return 'End turn';
    if (this.speaking()) return 'Interrupt & answer';
    return this.conversationSessionActive() ? 'Pause conversation' : 'Start conversation';
  }

  lastConversationLabel(): string {
    const step = this.lastConversationStep();
    if (!step) return 'Voice actions will be inferred from the next final transcript.';
    const labels: Record<string, string> = {
      answer_ready: 'Answer captured and evaluated',
      correction: 'Correction captured',
      more_detail: 'Additional detail captured',
      proposal_requested: 'Proposal prepared, waiting for confirmation',
      proposal_deferred_insufficient_facts: 'More expert detail needed before proposal',
      proposal_confirmed: 'Proposal confirmed, waiting for final acceptance',
      proposal_rejected: 'Proposal rejected, waiting for correction',
      accept_confirmed: 'Proposal accepted',
      accept_rejected: 'Acceptance paused',
    };
    if (step.action_taken === 'proposal_deferred_insufficient_facts') {
      return labels['proposal_deferred_insufficient_facts'];
    }
    return labels[step.intent] || `${step.intent} · ${step.action_taken}`;
  }

  transcriptEventLabel(event: CaptureEvent): string {
    if (event.event_type === 'conversation_intent_detected') {
      return `intent: ${(event.metadata || {})['intent'] || 'detected'}`;
    }
    if (event.event_type === 'proposal_generated') return 'proposal generated';
    if (event.event_type === 'proposal_reviewed') return 'proposal reviewed';
    if (event.event_type === 'transcript_amended' || event.text_amended) return 'amended transcript';
    if (event.event_type === 'expert_turn_finalized') return 'final answer';
    if (event.event_type === 'stt_final') return 'final transcript';
    return 'transcript';
  }

  private transcriptEventShortLabel(event: CaptureEvent): string {
    if (event.event_type === 'conversation_intent_detected') return 'intent';
    if (event.event_type === 'transcript_amended' || event.text_amended) return 'amended';
    if (event.event_type === 'expert_turn_finalized') return 'final answer';
    if (event.event_type === 'stt_final') return 'transcript';
    return 'captured';
  }

  eventDisplayText(event: CaptureEvent): string {
    if (event.event_type === 'conversation_intent_detected') {
      return String((event.metadata || {})['fact_text'] || '').trim();
    }
    return (event.text || event.text_amended || event.text_raw || '').trim();
  }

  beginAmend(event: CaptureEvent): void {
    this.editingEventId.set(event.id);
    this.editingText = event.text_amended || event.text || event.text_raw || '';
  }

  applyAmend(sessionId: string, eventId: string): void {
    const text = this.editingText.trim();
    if (!text) return;
    if (!this.canCaptureUpdate(this.session())) {
      this.setVoiceNotice('You do not have permission to amend this Capture session.', 'error');
      return;
    }
    this.api
      .amendCaptureEvent(sessionId, eventId, {
        text_amended: text,
        actor: 'demo-operator',
        reason: 'HITL transcript correction from capture console.',
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

  createProposal(session: CaptureSession): void {
    if (!this.canProposalSubmit(session)) {
      this.setVoiceNotice('You do not have permission to submit a proposal for this session.', 'error');
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
          this.activeSurface.set('review');
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
            this.activeSurface.set('review');
            this.voiceState.set('idle');
          });
      });
  }

  runConversationStep(session: CaptureSession, text: string): void {
    const clean = text.trim();
    if (!clean) return;
    if (!this.canCaptureExecute(session)) {
      this.setVoiceNotice('You do not have permission to run the conversation loop for this session.', 'error');
      return;
    }
    this.voiceState.set('thinking');
    this.setVoiceNotice('Processing the final transcript and inferring the next action.', 'info');
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
          const step = payload as ConversationStepResponse;
          this.lastConversationStep.set(step);
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
              this.activeSurface.set('review');
            }
          }
          this.currentClientTurnId = null;
          this.interruptionOfEventId.set(null);
          this.refreshEvents(step.session.id);
          if (step.next_prompt) {
            this.speak(this.promptText(step.next_prompt));
          } else {
            this.voiceState.set('idle');
            this.setVoiceNotice('Ready for the next expert answer.', 'info');
            this.scheduleConversationResume();
          }
        },
        error: () => {
          this.voiceState.set('idle');
          this.setVoiceNotice('Conversation step failed. The transcript was not processed.', 'error');
        },
      });
  }

  acceptProposal(proposalId: string): void {
    if (!this.canProposalReview(this.proposal())) {
      this.setVoiceNotice('You do not have permission to review this proposal.', 'error');
      return;
    }
    this.api
      .reviewCaptureProposal(proposalId, {
        status: 'accepted',
        reviewer: 'demo-operator',
        review_notes: 'Accepted from Knowledge Capture demo.',
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((proposal) => {
        this.setProposal(proposal as CaptureProposal);
        this.refreshDashboard();
      });
  }

  proposalFacts(): ProposalFact[] {
    return (this.proposal()?.proposal?.captured_facts || [])
      .filter((fact) => Boolean(this.proposalFactText(fact)));
  }

  proposalOpenQuestions(): Array<{ gap_id?: string; reason?: string; follow_up?: string }> {
    return this.proposal()?.proposal?.open_questions || [];
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
    if (decision === 'accept') return 'accepted';
    if (decision === 'reject') return 'rejected';
    return 'pending';
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
    if (fact.type) return fact.type.toUpperCase();
    if (fact.turn_kind === 'correction') return 'UPDATE';
    if (fact.turn_kind === 'complement') return 'DETAIL';
    if (fact.amended) return 'AMENDED';
    return 'NEW';
  }

  proposalFactConfidence(fact: ProposalFact): string {
    const value = typeof fact.confidence === 'number' ? fact.confidence : 0.5;
    return `${Math.round(value * 100)}% confidence`;
  }

  private ensureVoiceConnection(session: CaptureSession): VoiceSessionConnection | null {
    if (this.conversationMode() !== 'conversation_only') return null;
    if (this.voiceConnection) return this.voiceConnection;
    try {
      this.voiceConnection = this.voiceSession.open(session.id);
      this.voiceConnection.events$
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe((event) => this.handleVoiceSessionEvent(event));
      this.voiceConnection.start({
        runtime: 'cascade',
        capability: 'expert_knowledge_capture',
        context_id: session.context_id || this.contextId || null,
        system_id: session.system_id || this.systemId || null,
        mode: 'conversation_only',
        codec: { input: 'webm', channels: 1 },
      });
      return this.voiceConnection;
    } catch {
      this.voiceConnection = null;
      this.setVoiceNotice('Voice WebSocket could not open; falling back to HTTP voice turns.', 'warning');
      return null;
    }
  }

  private closeVoiceConnection(): void {
    this.voiceConnection?.close();
    this.voiceConnection = null;
  }

  private handleVoiceSessionEvent(event: VoiceSessionEvent): void {
    const payload = event.payload || {};
    if (event.type === 'session.ready') {
      this.setVoiceNotice('Streaming voice session ready.', 'info');
      return;
    }
    if (event.type === 'text.partial') {
      const text = String(payload['text'] || '').trim();
      if (text) {
        this.answer = text;
        const session = this.session();
        if (session) this.maybePrefetchRetrieval(session, text);
      }
      return;
    }
    if (event.type === 'text.final') {
      const text = String(payload['text'] || '').trim();
      if (text) this.answer = text;
      this.transcribing.set(false);
      this.voiceState.set('thinking');
      this.setVoiceNotice('Transcript finalized through the streaming voice session.', 'info');
      return;
    }
    if (event.type === 'evaluation.delta') {
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
      return;
    }
    if (event.type === 'prompt.next') {
      const prompt = String(payload['text'] || '').trim();
      this.nextPrompt.set(prompt || null);
      const promptEventId = payload['system_prompt_event_id'];
      this.lastSystemPromptEventId.set(typeof promptEventId === 'string' ? promptEventId : null);
      this.setVoiceNotice('Next prompt prepared by the streaming capture oracle.', 'info');
      return;
    }
    if (event.type === 'audio.out') {
      this.playServerAudio(payload);
      return;
    }
    if (event.type === 'runtime.metric') {
      const metric = payload['metric'];
      const value = payload['value_ms'];
      if (typeof metric === 'string' && typeof value === 'number') {
        this.retrieval.update((current) => ({ ...current, latency_ms: value }));
      }
      return;
    }
    if (event.type === 'barge_in') {
      this.setVoiceNotice('Barge-in accepted by the voice gateway.', 'info');
      return;
    }
    if (event.type === 'session.error') {
      const code = String(payload['code'] || '');
      this.transcribing.set(false);
      this.voiceState.set('idle');
      this.setVoiceNotice(String(payload['message'] || 'Voice streaming failed.'), 'error');
      if (code === 'synthesize_failed' && this.nextPrompt()) {
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
      this.setVoiceNotice('Streaming audio playback failed; opening the microphone instead.', 'warning');
      this.speaking.set(false);
      this.voiceState.set('idle');
      this.scheduleConversationResume();
    };
    void audio.play().catch(() => {
      this.setVoiceNotice('Browser blocked streaming audio playback; opening the microphone instead.', 'warning');
      this.speaking.set(false);
      this.voiceState.set('idle');
      this.scheduleConversationResume();
    });
  }

  private voiceFrameMeta(): {
    turn_id: string | null;
    question_id: string | null;
    retrieval_event_id: string | null;
    interruption_of_event_id: string | null;
    content_type: string;
  } {
    return {
      turn_id: this.currentClientTurnId,
      question_id: this.selectedQuestionId(),
      retrieval_event_id: this.retrieval().event_id || null,
      interruption_of_event_id: this.interruptionOfEventId(),
      content_type: 'audio/webm',
    };
  }

  async toggleRecording(): Promise<void> {
    if (this.recording()) {
      this.recorder?.stop();
      this.recording.set(false);
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
    this.chunks = [];
    this.currentClientTurnId = this.newTurnId();
    this.lastPrefetchText = '';
    this.lastPrefetchAt = 0;
    this.startAudioRecorder('Microphone is open. Stop listening when the expert answer is complete.');
  }

  async toggleConversationSession(): Promise<void> {
    if (this.recording()) {
      this.recorder?.stop();
      this.recording.set(false);
      return;
    }
    if (this.speaking()) {
      this.interruptSpeech();
      this.conversationSessionActive.set(true);
      await this.startRecordingTurn();
      return;
    }
    if (this.conversationSessionActive()) {
      this.stopConversationSession();
      return;
    }
    const session = this.session();
    if (session) {
      this.ensureVoiceConnection(session);
    }
    this.conversationSessionActive.set(true);
    this.setVoiceNotice('Preparing microphone access for the conversation session.', 'info');
    const armed = await this.ensureAudioStream();
    if (!armed) {
      this.conversationSessionActive.set(false);
      this.voiceState.set('idle');
      return;
    }
    const firstPrompt = this.currentPromptText();
    if (firstPrompt) {
      this.speak(firstPrompt);
      return;
    }
    await this.startRecordingTurn();
  }

  currentQuestion(): CaptureQuestion | null {
    const session = this.session();
    const questionId = this.selectedQuestionId();
    if (!session || !questionId) {
      return session?.plan.questions?.[0] || null;
    }
    return session.plan.questions?.find((question) => question.id === questionId) || null;
  }

  readCurrentQuestion(): void {
    const prompt = this.currentPromptText();
    if (prompt) {
      this.speak(prompt);
    }
  }

  currentQuestionPosition(session: CaptureSession): number {
    const questionId = this.selectedQuestionId();
    const questions = session.plan.questions || [];
    const index = questions.findIndex((question) => question.id === questionId);
    return index >= 0 ? index + 1 : Math.min(questions.length, 1);
  }

  captureProgressLabel(session: CaptureSession): string {
    const total = session.plan.questions?.length || 0;
    if (!total) return 'No plan';
    return `${this.currentQuestionPosition(session)} of ${total}`;
  }

  planDurationMinutes(session: CaptureSession): number {
    const questions = session.plan.questions || [];
    return questions.reduce((total, question) => total + (question.estimated_minutes || 3), 0);
  }

  questionStateLabel(session: CaptureSession, question: CaptureQuestion): string {
    const questions = session.plan.questions || [];
    const selected = this.selectedQuestionId();
    const selectedIndex = questions.findIndex((item) => item.id === selected);
    const questionIndex = questions.findIndex((item) => item.id === question.id);
    if (question.id === selected) return 'current';
    if (selectedIndex >= 0 && questionIndex >= 0 && questionIndex < selectedIndex) return 'covered';
    return 'upcoming';
  }

  voiceWaveHeight(base: number): number {
    if (this.recording()) return base;
    if (this.speaking()) return Math.max(8, Math.round(base * 0.75));
    if (this.transcribing() || this.voiceState() === 'thinking' || this.voiceState() === 'retrieving') {
      return Math.max(6, Math.round(base * 0.45));
    }
    return 6;
  }

  voiceInputStatusLabel(): string {
    if (this.recording()) return 'Recording expert turn';
    if (this.transcribing()) return 'Finalizing transcript';
    if (this.speaking()) return 'AI is speaking';
    if (this.voiceState() === 'retrieving') return 'Retrieving context';
    if (this.voiceState() === 'thinking') return 'Evaluating answer';
    if (this.conversationMode() === 'conversation_only' && this.conversationSessionActive()) {
      return 'Conversation armed';
    }
    return this.conversationMode() === 'conversation_only' ? 'Ready for conversation-only session' : 'Ready for manual capture';
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

  speak(text: string): void {
    const clean = text.trim();
    if (!clean) {
      return;
    }
    this.setVoiceNotice('Agentium is reading the prompt. You can interrupt and answer at any time.', 'info');
    this.stopSpeech(false);
    const generation = ++this.speechGeneration;
    this.audioQueue = this.splitSpeech(clean);
    this.playNextSpeechSegment(generation);
  }

  interruptSpeech(): void {
    const promptEventId = this.lastSystemPromptEventId();
    this.stopSpeech(true);
    this.voiceConnection?.bargeIn(promptEventId);
    this.interruptionOfEventId.set(promptEventId || 'client-interruption');
    this.voiceState.set('interrupted');
  }

  private transcribeRecording(): void {
    if (!this.conversationSessionActive()) {
      this.releaseAudioStream();
    }
    this.recorder = null;
    if (this.voiceConnection && this.conversationMode() === 'conversation_only') {
      void this.finishStreamingVoiceTurn();
      return;
    }
    const blob = new Blob(this.chunks, { type: 'audio/webm' });
    this.transcribing.set(true);
    this.voiceState.set('partial_transcribing');
    this.setVoiceNotice('Finalizing the voice transcript.', 'info');
    this.api
      .transcribeAudio(blob)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.answer = res.text;
          this.transcribing.set(false);
          this.voiceState.set('idle');
          const session = this.session();
          if (session) {
            this.maybePrefetchRetrieval(session, res.text, true);
            if (this.conversationMode() === 'conversation_only') {
              this.runConversationStep(session, res.text);
            } else {
              this.setVoiceNotice('Transcript ready for evaluation.', 'info');
            }
          }
        },
        error: () => {
          this.transcribing.set(false);
          this.voiceState.set('idle');
          this.setVoiceNotice('Transcription failed. Try another voice turn or use guided text entry.', 'error');
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

  private transcribePartialRecording(): void {
    if (this.voiceConnection && this.conversationMode() === 'conversation_only') {
      return;
    }
    const session = this.session();
    if (!session || this.partialTranscriptionInFlight || this.chunks.length < 2) {
      return;
    }
    this.partialTranscriptionInFlight = true;
    this.voiceState.set('partial_transcribing');
    const blob = new Blob(this.chunks, { type: 'audio/webm' });
    this.api
      .transcribeAudio(blob, 'partial.webm')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.partialTranscriptionInFlight = false;
          const text = (res.text || '').trim();
          if (text) {
            this.answer = text;
            this.maybePrefetchRetrieval(session, text);
          }
          if (this.recording()) {
            this.voiceState.set(this.prefetchInFlight ? 'retrieving' : 'listening');
          }
        },
        error: () => {
          this.partialTranscriptionInFlight = false;
          if (this.recording()) {
            this.voiceState.set('listening');
          }
        },
      });
  }

  private async finishStreamingVoiceTurn(): Promise<void> {
    this.transcribing.set(true);
    this.voiceState.set('partial_transcribing');
    this.setVoiceNotice('Finalizing transcript through the streaming voice session.', 'info');
    const pending = [...this.pendingVoiceFrameSends];
    this.pendingVoiceFrameSends = [];
    if (pending.length) {
      await Promise.allSettled(pending);
    }
    this.voiceConnection?.endpoint(this.voiceFrameMeta());
  }

  private maybePrefetchRetrieval(session: CaptureSession, text: string, force = false): void {
    const clean = text.trim();
    if (this.prefetchInFlight || clean.split(/\s+/).filter(Boolean).length < 8) return;
    const now = Date.now();
    const newWords = Math.abs(clean.split(/\s+/).length - this.lastPrefetchText.split(/\s+/).filter(Boolean).length);
    if (!force && newWords < 8 && now - this.lastPrefetchAt < 2500) return;
    this.prefetchInFlight = true;
    this.lastPrefetchText = clean;
    this.lastPrefetchAt = now;
    if (!this.recording()) {
      this.voiceState.set('retrieving');
    }
    this.retrieval.set({ ...this.retrieval(), status: 'searching' });
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
          const mappedStatus =
            typed.status === 'completed' ? 'ready' : typed.status === 'timeout' ? 'timeout' : typed.status;
          this.retrieval.set({
            event_id: typed.event_id,
            status: mappedStatus as RetrievalPrefetch['status'],
            latency_ms: typed.latency_ms,
            collection_name: typed.collection_name,
            chunks: typed.chunks || [],
            scores: typed.scores || [],
            metadatas: typed.metadatas || [],
          });
          this.prefetchInFlight = false;
          this.refreshEvents(session.id);
          if (this.recording()) {
            this.voiceState.set('listening');
          }
        },
        error: () => {
          this.retrieval.set({ status: 'error', chunks: [], scores: [], metadatas: [] });
          this.prefetchInFlight = false;
          if (this.recording()) {
            this.voiceState.set('listening');
          }
        },
      });
  }

  private splitSpeech(text: string): string[] {
    return text
      .replace(/\s+/g, ' ')
      .split(/(?<=[.!?])\s+/)
      .map((part) => part.trim())
      .filter(Boolean)
      .reduce<string[]>((segments, part) => {
        if (part.length <= 220) return [...segments, part];
        const chunks = part.match(/.{1,220}(\s|$)/g) || [part.slice(0, 220)];
        return [...segments, ...chunks.map((chunk) => chunk.trim()).filter(Boolean)];
      }, []);
  }

  retrievalChunkTrack(index: number, chunk: string): string {
    return `${index}:${chunk.slice(0, 80)}`;
  }

  private playNextSpeechSegment(generation: number): void {
    if (generation !== this.speechGeneration) {
      return;
    }
    const segment = this.audioQueue.shift();
    if (!segment) {
      this.speaking.set(false);
      this.voiceState.set('idle');
      this.cleanupAudioUrls();
      this.scheduleConversationResume();
      return;
    }
    this.speaking.set(true);
    this.voiceState.set('speaking');
    this.api
      .synthesizeSpeech(segment.slice(0, 600))
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => {
          if (generation !== this.speechGeneration) {
            return;
          }
          const url = URL.createObjectURL(blob);
          this.revokedAudioUrls.push(url);
          const audio = new Audio(url);
          this.activeAudio = audio;
          audio.onended = () => this.playNextSpeechSegment(generation);
          audio.onerror = () => {
            this.setVoiceNotice('Audio playback failed; opening the microphone instead.', 'warning');
            this.playNextSpeechSegment(generation);
          };
          void audio.play().catch(() => {
            this.setVoiceNotice('Browser blocked audio playback; opening the microphone instead.', 'warning');
            this.playNextSpeechSegment(generation);
          });
        },
        error: () => {
          this.setVoiceNotice('Voice synthesis is unavailable; opening the microphone instead.', 'warning');
          this.playNextSpeechSegment(generation);
        },
      });
  }

  private stopSpeech(markInterrupted: boolean): void {
    this.speechGeneration += 1;
    if (this.activeAudio) {
      this.activeAudio.pause();
      this.activeAudio.currentTime = 0;
      this.activeAudio = null;
    }
    this.audioQueue = [];
    this.speaking.set(false);
    this.cleanupAudioUrls();
    if (markInterrupted) {
      this.voiceState.set('interrupted');
    }
  }

  private startAudioRecorder(openMessage: string): boolean {
    if (typeof MediaRecorder === 'undefined') {
      this.recorder = null;
      this.releaseAudioStream();
      this.setVoiceNotice('Audio recording is unavailable in this browser. Try another browser or use guided text entry.', 'error');
      return false;
    }
    try {
      this.recorder = new MediaRecorder(this.stream!);
      this.recorder.ondataavailable = (event) => {
        if (event.data.size <= 0) return;
        this.chunks.push(event.data);
        if (this.voiceConnection && this.conversationMode() === 'conversation_only') {
          const send = this.voiceConnection
            .sendAudioFrame(event.data, this.voiceFrameMeta())
            .catch(() => this.setVoiceNotice('A voice frame could not be sent; fallback HTTP may be needed.', 'warning'));
          this.pendingVoiceFrameSends.push(send);
          void send.finally(() => {
            this.pendingVoiceFrameSends = this.pendingVoiceFrameSends.filter((item) => item !== send);
          });
        } else {
          this.transcribePartialRecording();
        }
      };
      this.recorder.onstop = () => this.transcribeRecording();
      this.recorder.start(1200);
    } catch {
      this.recorder = null;
      this.releaseAudioStream();
      this.setVoiceNotice('Audio recording could not start. Check the microphone device, then retry.', 'error');
      return false;
    }
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
    const armed = await this.ensureAudioStream();
    if (!armed) {
      this.conversationSessionActive.set(false);
      this.voiceState.set('idle');
      return;
    }
    this.chunks = [];
    this.currentClientTurnId = this.newTurnId();
    this.lastPrefetchText = '';
    this.lastPrefetchAt = 0;
    const session = this.session();
    if (session) {
      this.ensureVoiceConnection(session);
    }
    if (!this.startAudioRecorder('Microphone is open. End the turn when the expert answer is complete.')) {
      this.conversationSessionActive.set(false);
      this.voiceState.set('idle');
    }
  }

  private stopConversationSession(): void {
    this.conversationSessionActive.set(false);
    this.clearAutoResumeTimer();
    this.stopSpeech(false);
    this.setVoiceNotice(null);
    if (this.recording()) {
      this.recorder?.stop();
      this.recording.set(false);
    } else if (!this.transcribing()) {
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
      this.setVoiceNotice('Microphone capture is unavailable in this browser context.', 'error');
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
          ? 'Microphone permission is blocked. Allow microphone access, then start the session again.'
          : 'Microphone capture failed. Check the input device, then retry.',
        'error',
      );
      return false;
    }
  }

  private hasLiveAudioStream(): boolean {
    return Boolean(this.stream?.getAudioTracks().some((track) => track.readyState === 'live'));
  }

  private releaseAudioStream(): void {
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
  }

  private scheduleConversationResume(): void {
    if (
      this.conversationMode() !== 'conversation_only' ||
      !this.conversationSessionActive() ||
      this.recording() ||
      this.transcribing() ||
      this.speaking()
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
        !this.transcribing() &&
        !this.speaking()
      ) {
        void this.startRecordingTurn();
      }
    }, 450);
  }

  private clearAutoResumeTimer(): void {
    if (this.autoResumeTimer) {
      clearTimeout(this.autoResumeTimer);
      this.autoResumeTimer = null;
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
