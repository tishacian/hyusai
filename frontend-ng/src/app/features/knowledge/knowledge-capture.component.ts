import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ApiService } from '@app/core/api.service';
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
  imports: [FormsModule, IconComponent, RouterLink],
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
          <button
            type="button"
            [class]="conversationMode() === 'conversation_only'
              ? 'text-xs px-3 py-1.5 rounded ring-1 bg-brand-500 text-white ring-brand-300'
              : 'text-xs px-3 py-1.5 rounded ring-1 bg-white/5 text-gray-300 ring-white/10'"
            (click)="toggleConversationMode()"
          >
            {{ conversationMode() === 'conversation_only' ? 'Exit conversation mode' : 'Conversation-only' }}
          </button>
        </div>
      </header>

      <nav class="t-card rounded-lg p-2 flex flex-wrap items-center gap-2">
        @for (item of surfaceNav; track item.id) {
          <button
            type="button"
            [class]="activeSurface() === item.id
              ? 'inline-flex items-center gap-2 px-3 py-2 rounded bg-brand-500/20 text-brand-100 ring-1 ring-brand-300/40'
              : 'inline-flex items-center gap-2 px-3 py-2 rounded text-gray-400 hover:text-white hover:bg-white/5'"
            (click)="goSurface(item.id)"
          >
            <app-icon [name]="item.icon" [size]="14" />
            <span class="text-sm">{{ item.label }}</span>
          </button>
        }
      </nav>

      @if (activeSurface() === 'prep') {
        <section class="grid md:grid-cols-4 gap-3">
          @for (step of modelSteps; track step.label) {
            <div class="t-card rounded-lg p-4 border border-white/10 bg-white/[0.02]">
              <div class="ck-mono text-[10px] uppercase tracking-[0.14em] text-brand-300">
                {{ step.eyebrow }}
              </div>
              <div class="text-sm font-semibold text-white mt-1">{{ step.label }}</div>
              <p class="text-xs text-gray-500 mt-1 leading-relaxed">{{ step.description }}</p>
            </div>
          }
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
                class="inline-flex items-center gap-2 px-3 py-2 rounded bg-brand-500 hover:bg-brand-400 text-sm font-semibold text-white"
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
                </div>
              </div>
            </section>

            <section class="grid xl:grid-cols-[320px_minmax(0,1fr)_360px] gap-4 items-start">
              <aside class="t-card rounded-lg p-4 max-h-[calc(100vh-270px)] overflow-auto">
                <div class="flex items-center justify-between gap-3">
                  <div>
                    <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Interview plan</p>
                    <h3 class="text-sm font-semibold text-white">Question track</h3>
                  </div>
                  <span class="text-xs text-brand-200">{{ captureProgressLabel(s) }}</span>
                </div>
                <div class="mt-4 space-y-2">
                  @for (q of s.plan.questions || []; track q.id) {
                    <button
                      type="button"
                      class="w-full text-left rounded border border-white/10 bg-white/[0.03] hover:bg-white/[0.06] p-3"
                      [class.ring-1]="selectedQuestionId() === q.id"
                      [class.ring-brand-400]="selectedQuestionId() === q.id"
                      (click)="selectedQuestionId.set(q.id); speak(q.question)"
                    >
                      <div class="flex items-center justify-between gap-2">
                        <span class="text-xs text-brand-300 font-mono">{{ q.id }}</span>
                        <span class="text-[10px] text-gray-500">{{ q.estimated_minutes || 3 }} min</span>
                      </div>
                      <div class="mt-2 text-sm text-gray-100 leading-snug">{{ q.question }}</div>
                    </button>
                  }
                </div>
              </aside>

              <main class="t-card rounded-lg p-4 min-h-[calc(100vh-270px)] flex flex-col">
                <div class="rounded bg-brand-500/10 border border-brand-400/20 p-4">
                  <div class="flex items-start justify-between gap-3">
                    <div>
                      <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-200">Current prompt</p>
                      <p class="mt-2 text-lg text-white leading-relaxed">{{ currentQuestion()?.question || nextPrompt() || 'Select a question to begin capture.' }}</p>
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

                <div class="mt-4 flex-1 flex flex-col gap-3">
                  <div class="flex items-center justify-between gap-3">
                    <div>
                      <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Expert answer</p>
                      <h3 class="text-sm font-semibold text-white">{{ voiceStateLabel() }}</h3>
                    </div>
                    @if (lastConversationStep(); as step) {
                      <span class="text-xs px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">
                        {{ step.intent }} · {{ (step.confidence * 100).toFixed(0) }}%
                      </span>
                    }
                  </div>
                  <textarea
                    class="w-full min-h-56 flex-1 rounded bg-black/30 border border-white/10 px-4 py-3 text-base text-white leading-relaxed"
                    [(ngModel)]="answer"
                    (ngModelChange)="onAnswerDraftChange()"
                    placeholder="La réponse captée apparaît ici. Vous pouvez aussi écrire ou corriger avant évaluation..."
                  ></textarea>
                </div>

                <div class="mt-4 sticky bottom-3 rounded bg-black/70 border border-white/10 p-3 backdrop-blur">
                  <div class="flex flex-wrap items-center gap-3">
                    <button
                      type="button"
                      class="inline-flex items-center gap-2 px-4 py-2.5 rounded bg-brand-500 hover:bg-brand-400 text-sm font-semibold text-white disabled:opacity-50"
                      [disabled]="transcribing()"
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
                    @if (conversationMode() === 'manual') {
                      <button
                        type="button"
                        class="inline-flex items-center gap-2 px-3 py-2.5 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-200 ring-1 ring-white/10 disabled:opacity-50"
                        [disabled]="!answer.trim()"
                        (click)="sendAnswer(s)"
                      >
                        <app-icon name="send" [size]="14" /> Evaluate
                      </button>
                      <button
                        type="button"
                        class="inline-flex items-center gap-2 px-3 py-2.5 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-200 ring-1 ring-white/10"
                        (click)="createProposal(s)"
                      >
                        <app-icon name="check-circle-2" [size]="14" /> Proposal
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
                        <div class="text-[10px] text-gray-500 truncate">cascade · en-fr · retrieval prefetch</div>
                      </div>
                    </div>
                    <div class="flex items-center gap-2 text-xs text-gray-400">
                      <span class="px-2 py-1 rounded bg-white/5">{{ recording() ? 'recording' : 'ready' }}</span>
                      <span class="px-2 py-1 rounded bg-white/5">{{ speaking() ? 'speaking' : 'tts idle' }}</span>
                    </div>
                  </div>
                </div>

                @if (textEvents().length) {
                  <div class="mt-4 border-t border-white/10 pt-4">
                    <div class="flex items-center justify-between gap-3">
                      <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Validated conversation trace</p>
                      <button type="button" class="text-xs text-brand-200 hover:text-brand-100" (click)="refreshEvents(s.id)">Refresh</button>
                    </div>
                    <div class="mt-3 space-y-2 max-h-48 overflow-auto">
                      @for (event of textEvents().slice(-4); track event.id) {
                        <div class="rounded bg-black/20 border border-white/10 p-3">
                          <div class="flex items-center justify-between gap-2">
                            <span class="text-[10px] uppercase tracking-wider text-gray-500">
                              #{{ event.sequence }} · {{ transcriptEventLabel(event) }}
                            </span>
                            <button type="button" class="text-xs text-brand-200 hover:text-brand-100" (click)="beginAmend(event)">
                              Amend
                            </button>
                          </div>
                          @if (editingEventId() === event.id) {
                            <textarea
                              class="mt-2 w-full min-h-20 rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white"
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
                            <p class="mt-2 text-sm text-gray-200 line-clamp-2">{{ text }}</p>
                          }
                        </div>
                      }
                    </div>
                  </div>
                }
              </main>

              <aside class="space-y-4 max-h-[calc(100vh-270px)] overflow-auto">
                <section class="t-card rounded-lg p-4">
                  <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Runtime state</p>
                  <div class="mt-3 grid grid-cols-2 gap-2 text-xs">
                    <div class="rounded bg-black/20 border border-white/10 p-3">
                      <span class="block text-[9px] uppercase tracking-wider text-gray-500">Voice</span>
                      <span class="text-gray-200">{{ voiceStateLabel() }}</span>
                    </div>
                    <div class="rounded bg-black/20 border border-white/10 p-3">
                      <span class="block text-[9px] uppercase tracking-wider text-gray-500">Mode</span>
                      <span class="text-gray-200">{{ conversationMode() === 'conversation_only' ? 'Conversation' : 'Manual' }}</span>
                    </div>
                    <div class="rounded bg-black/20 border border-white/10 p-3">
                      <span class="block text-[9px] uppercase tracking-wider text-gray-500">Retrieval</span>
                      <span class="text-gray-200">{{ retrievalLabel() }}</span>
                    </div>
                    <div class="rounded bg-black/20 border border-white/10 p-3">
                      <span class="block text-[9px] uppercase tracking-wider text-gray-500">TTS</span>
                      <span class="text-gray-200">{{ speaking() ? 'Speaking' : 'Idle' }}</span>
                    </div>
                  </div>
                </section>

                @if (conversationMode() === 'conversation_only') {
                  <section class="t-card rounded-lg p-4 bg-brand-500/5 border-brand-400/20">
                    <div class="flex items-start justify-between gap-3">
                      <div>
                        <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-200">Conversation-only</p>
                        <p class="mt-2 text-sm text-white">{{ lastConversationLabel() }}</p>
                      </div>
                      @if (conversationSessionActive()) {
                        <span class="text-xs text-brand-100">Active</span>
                      }
                    </div>
                    @if (nextPrompt()) {
                      <p class="mt-3 text-xs text-gray-300 leading-relaxed">{{ nextPrompt() }}</p>
                    }
                  </section>
                }

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

                @if (lastEvaluation(); as ev) {
                  <section class="t-card rounded-lg p-4">
                    <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Answer quality</p>
                    <div class="mt-2 text-sm text-white">{{ ev.verdict }} · score {{ ev.score }}</div>
                    @if (nextPrompt()) {
                      <button type="button" class="mt-3 text-left text-sm text-brand-200 hover:text-brand-100" (click)="speak(nextPrompt()!)">
                        {{ nextPrompt() }}
                      </button>
                    }
                  </section>
                }

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
          <section class="grid xl:grid-cols-[minmax(0,1fr)_360px] gap-5">
            <div class="t-card rounded-lg p-5 space-y-4">
              <div class="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Interview plan</p>
                  <h2 class="text-lg font-semibold text-white mt-1">{{ s.title }}</h2>
                  <p class="text-sm text-gray-500 mt-1 max-w-3xl">{{ s.objective }}</p>
                </div>
                <button
                  type="button"
                  class="inline-flex items-center gap-2 px-3 py-2 rounded bg-brand-500 hover:bg-brand-400 text-sm font-semibold text-white"
                  (click)="goSurface('session')"
                >
                  <app-icon name="mic" [size]="14" /> Open capture cockpit
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
                    class="w-full text-left rounded border border-white/10 bg-white/[0.03] hover:bg-white/[0.06] p-4"
                    [class.ring-1]="selectedQuestionId() === q.id"
                    [class.ring-brand-400]="selectedQuestionId() === q.id"
                    (click)="selectedQuestionId.set(q.id)"
                  >
                    <div class="flex flex-wrap items-center justify-between gap-3">
                      <div class="flex items-center gap-3">
                        <span class="ck-mono text-xs text-brand-300">{{ q.id }}</span>
                        <span class="text-[10px] uppercase tracking-wider px-2 py-1 rounded bg-white/5 text-gray-400">
                          {{ questionStateLabel(s, q) }}
                        </span>
                      </div>
                      <span class="text-xs text-gray-500">{{ q.estimated_minutes || 3 }} min</span>
                    </div>
                    <p class="mt-3 text-base text-gray-100 leading-relaxed">{{ q.question }}</p>
                  </button>
                }
              </div>
            </div>

            <aside class="t-card rounded-lg p-5 space-y-4">
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
              </div>
              <button
                type="button"
                class="w-full inline-flex items-center justify-center gap-2 px-3 py-2 rounded bg-brand-500 hover:bg-brand-400 text-sm font-semibold text-white"
                (click)="goSurface('session')"
              >
                <app-icon name="play" [size]="14" /> Start guided session
              </button>
            </aside>
          </section>
        } @else {
          <section class="t-card rounded-lg p-8 text-center text-gray-400">
            Prepare a capture plan before reviewing the interview plan.
          </section>
        }
      }

      @if (activeSurface() === 'prep') {
      <div class="grid lg:grid-cols-[360px_1fr] gap-5">
        <aside class="t-card rounded-lg p-4 space-y-4">
          <div>
            <label class="block text-[11px] uppercase tracking-wider text-gray-500 mb-1">Context</label>
            <select
              class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white"
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
            <p class="text-[11px] text-gray-500 mt-1">
              The selected Context binds this capture to a Knowledge collection, ACLs and business constraints.
            </p>
          </div>
          <div>
            <label class="block text-[11px] uppercase tracking-wider text-gray-500 mb-1">Objective</label>
            <textarea
              class="w-full min-h-28 rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white"
              [(ngModel)]="objective"
            ></textarea>
          </div>
          <div>
            <label class="block text-[11px] uppercase tracking-wider text-gray-500 mb-1">Expert profile</label>
            <input
              class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white"
              [(ngModel)]="expertProfile"
            />
          </div>
          <div>
            <label class="block text-[11px] uppercase tracking-wider text-gray-500 mb-1">Duration minutes</label>
            <input
              type="number"
              min="5"
              max="90"
              class="w-full rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white"
              [(ngModel)]="durationMinutes"
            />
          </div>
          <button
            type="button"
            class="w-full inline-flex items-center justify-center gap-2 px-3 py-2 rounded bg-brand-500 hover:bg-brand-400 text-sm font-semibold text-white disabled:opacity-50"
            [disabled]="loading()"
            (click)="createPlan()"
          >
            <app-icon name="wand-2" [size]="14" />
            {{ loading() ? 'Preparing...' : 'Prepare capture plan' }}
          </button>
        </aside>

        <main class="space-y-5">
          @if (session(); as s) {
            <section class="t-card rounded-lg p-4 space-y-3">
              <div class="flex items-center justify-between gap-3">
                <div>
                  <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Session</p>
                  <h2 class="text-lg font-semibold text-white">{{ s.title }}</h2>
                </div>
                <span class="text-xs px-2 py-1 rounded bg-white/5 text-gray-300">{{ s.status }}</span>
              </div>
              <div class="grid md:grid-cols-4 gap-2 text-xs">
                <a routerLink="/capabilities" class="rounded bg-black/20 p-2 text-gray-300 hover:text-white">
                  <span class="block text-[9px] uppercase tracking-wider text-gray-500">Capability</span>
                  Expert Knowledge Capture
                </a>
                <a routerLink="/systems" class="rounded bg-black/20 p-2 text-gray-300 hover:text-white">
                  <span class="block text-[9px] uppercase tracking-wider text-gray-500">System</span>
                  {{ systemLabel(s.system_id) || 'Workspace-scoped session' }}
                </a>
                <a routerLink="/steering/contexts" class="rounded bg-black/20 p-2 text-gray-300 hover:text-white">
                  <span class="block text-[9px] uppercase tracking-wider text-gray-500">Context</span>
                  {{ contextLabel(s.context_id) }}
                </a>
                <a routerLink="/knowledge" class="rounded bg-black/20 p-2 text-gray-300 hover:text-white">
                  <span class="block text-[9px] uppercase tracking-wider text-gray-500">Knowledge</span>
                  {{ selectedContext()?.environment_state?.collection || 'Review proposal target' }}
                </a>
              </div>
              <div class="grid md:grid-cols-3 gap-3 text-sm">
                <div class="rounded bg-black/20 p-3">
                  <div class="text-[10px] uppercase tracking-wider text-gray-500">Questions</div>
                  <div class="text-xl text-white font-semibold">{{ s.plan.questions?.length || 0 }}</div>
                </div>
                <div class="rounded bg-black/20 p-3">
                  <div class="text-[10px] uppercase tracking-wider text-gray-500">Coverage</div>
                  <div class="text-xl text-white font-semibold">{{ ((s.metrics?.['coverage'] || 0) * 100).toFixed(0) }}%</div>
                </div>
                <div class="rounded bg-black/20 p-3">
                  <div class="text-[10px] uppercase tracking-wider text-gray-500">Facts</div>
                  <div class="text-xl text-white font-semibold">{{ s.metrics?.['captured_facts'] || 0 }}</div>
                </div>
              </div>
            </section>

            <section class="grid lg:grid-cols-2 gap-5">
              <div class="t-card rounded-lg p-4 space-y-3">
                <h3 class="text-sm font-semibold text-white">Interview plan</h3>
                <div class="space-y-2">
                  @for (q of s.plan.questions || []; track q.id) {
                    <button
                      type="button"
                      class="w-full text-left rounded border border-white/10 bg-white/[0.03] hover:bg-white/[0.06] p-3"
                      [class.ring-1]="selectedQuestionId() === q.id"
                      [class.ring-brand-400]="selectedQuestionId() === q.id"
                      (click)="selectedQuestionId.set(q.id); speak(q.question)"
                    >
                      <div class="text-xs text-brand-300 font-mono">{{ q.id }} · {{ q.estimated_minutes || 3 }} min</div>
                      <div class="text-sm text-white mt-1">{{ q.question }}</div>
                    </button>
                  }
                </div>
              </div>

              <div class="t-card rounded-lg p-4 space-y-3">
                <div class="flex items-center justify-between gap-3">
                  <div>
                    <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Voice2Voice</p>
                    <h3 class="text-sm font-semibold text-white">Conversation controller</h3>
                  </div>
                  <span class="text-xs px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">
                    {{ voiceStateLabel() }}
                  </span>
                </div>
                <textarea
                  class="w-full min-h-32 rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white"
                  [(ngModel)]="answer"
                  (ngModelChange)="onAnswerDraftChange()"
                  placeholder="Record, interrupt or paste the expert answer..."
                ></textarea>
                <div class="grid sm:grid-cols-3 gap-2 text-xs">
                  <div class="rounded bg-black/20 border border-white/10 p-2">
                    <span class="block text-[9px] uppercase tracking-wider text-gray-500">Capture</span>
                    <span class="text-gray-200">{{ recording() ? 'Chunked every 1.2s' : 'Ready' }}</span>
                  </div>
                  <div class="rounded bg-black/20 border border-white/10 p-2">
                    <span class="block text-[9px] uppercase tracking-wider text-gray-500">Retrieval</span>
                    <span class="text-gray-200">{{ retrievalLabel() }}</span>
                  </div>
                  <div class="rounded bg-black/20 border border-white/10 p-2">
                    <span class="block text-[9px] uppercase tracking-wider text-gray-500">TTS</span>
                    <span class="text-gray-200">{{ speaking() ? 'Segmented playback' : 'Idle' }}</span>
                  </div>
                </div>
                <div class="flex flex-wrap gap-2">
                  <button
                    type="button"
                    class="inline-flex items-center gap-2 px-3 py-2 rounded bg-brand-500 hover:bg-brand-400 text-sm text-white disabled:opacity-50"
                    [disabled]="transcribing()"
                    (click)="conversationMode() === 'conversation_only' ? toggleConversationSession() : toggleRecording()"
                  >
                    <app-icon [name]="conversationPrimaryIcon()" [size]="14" />
                    {{ conversationPrimaryLabel() }}
                  </button>
                  @if (conversationMode() === 'manual') {
                    <button
                      type="button"
                      class="inline-flex items-center gap-2 px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-200 ring-1 ring-white/10"
                      [disabled]="!answer.trim()"
                      (click)="sendAnswer(s)"
                    >
                      <app-icon name="send" [size]="14" /> Evaluate answer
                    </button>
                  }
                  @if (speaking()) {
                    <button
                      type="button"
                      class="inline-flex items-center gap-2 px-3 py-2 rounded bg-amber-500/20 hover:bg-amber-500/30 text-sm text-amber-100 ring-1 ring-amber-400/20"
                      (click)="interruptSpeech()"
                    >
                      <app-icon name="pause" [size]="14" /> Interrupt AI
                    </button>
                  }
                  @if (conversationMode() === 'manual') {
                    <button
                      type="button"
                      class="inline-flex items-center gap-2 px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-200 ring-1 ring-white/10"
                      (click)="createProposal(s)"
                    >
                      <app-icon name="check-circle-2" [size]="14" /> Create proposal
                    </button>
                  }
                </div>

                @if (conversationMode() === 'conversation_only') {
                  <div class="rounded bg-brand-500/10 border border-brand-400/20 p-3 text-sm">
                    <div class="flex items-center justify-between gap-3">
                      <div>
                        <div class="text-[10px] uppercase tracking-wider text-brand-200">Conversation-only</div>
                        <div class="mt-1 text-white">{{ lastConversationLabel() }}</div>
                      </div>
                      @if (conversationSessionActive()) {
                        <span class="text-xs text-brand-100">Session active</span>
                      }
                      @if (lastConversationStep(); as step) {
                        <span class="text-xs text-gray-400">{{ (step.confidence * 100).toFixed(0) }}%</span>
                      }
                    </div>
                    @if (nextPrompt()) {
                      <p class="mt-2 text-xs text-gray-300">{{ nextPrompt() }}</p>
                    }
                  </div>
                }

                @if (retrieval(); as rr) {
                  @if (rr.status !== 'idle') {
                    <div class="rounded bg-black/20 border border-white/10 p-3 text-sm">
                      <div class="flex items-center justify-between gap-3">
                        <div>
                          <div class="text-[10px] uppercase tracking-wider text-gray-500">Contexte retrouvé</div>
                          <div class="mt-1 text-white">{{ retrievalLabel() }}</div>
                        </div>
                        @if (rr.latency_ms !== undefined) {
                          <span class="text-xs text-gray-500">{{ rr.latency_ms }} ms</span>
                        }
                      </div>
                      @if (rr.chunks.length) {
                        <div class="mt-2 space-y-2">
                          @for (chunk of rr.chunks.slice(0, 2); track retrievalChunkTrack($index, chunk)) {
                            <p class="text-xs text-gray-400 line-clamp-2">{{ chunk }}</p>
                          }
                        </div>
                      }
                    </div>
                  }
                }

                @if (lastEvaluation(); as ev) {
                  <div class="rounded bg-black/20 border border-white/10 p-3 text-sm">
                    <div class="text-[10px] uppercase tracking-wider text-gray-500">Evaluation</div>
                    <div class="mt-1 text-white">{{ ev.verdict }} · score {{ ev.score }}</div>
                    @if (nextPrompt()) {
                      <button
                        type="button"
                        class="mt-2 text-left text-brand-200 hover:text-brand-100"
                        (click)="speak(nextPrompt()!)"
                      >
                        Next prompt: {{ nextPrompt() }}
                      </button>
                    }
                  </div>
                }
              </div>
            </section>

            @if (textEvents().length) {
              <section class="t-card rounded-lg p-4 space-y-3">
                <div class="flex items-center justify-between gap-3">
                  <div>
                    <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Transcript ledger</p>
                    <h3 class="text-sm font-semibold text-white">HITL-amendable capture trace</h3>
                  </div>
                  <button
                    type="button"
                    class="text-xs px-3 py-1.5 rounded bg-white/5 text-gray-300 ring-1 ring-white/10"
                    (click)="refreshEvents(s.id)"
                  >
                    Refresh
                  </button>
                </div>
                <div class="space-y-2">
                  @for (event of textEvents(); track event.id) {
                    <div class="rounded border border-white/10 bg-black/20 p-3">
                      <div class="flex items-center justify-between gap-2">
                        <div class="text-[10px] uppercase tracking-wider text-gray-500">
                          #{{ event.sequence }} · {{ transcriptEventLabel(event) }} · {{ event.status }}
                        </div>
                        <button
                          type="button"
                          class="text-xs text-brand-200 hover:text-brand-100"
                          (click)="beginAmend(event)"
                        >
                          Amend
                        </button>
                      </div>
                      @if (editingEventId() === event.id) {
                        <textarea
                          class="mt-2 w-full min-h-24 rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white"
                          [ngModel]="editingText"
                          (ngModelChange)="editingText = $event"
                        ></textarea>
                        <div class="mt-2 flex gap-2">
                          <button
                            type="button"
                            class="px-3 py-1.5 rounded bg-brand-500 hover:bg-brand-400 text-xs text-white"
                            (click)="applyAmend(s.id, event.id)"
                          >
                            Apply correction
                          </button>
                          <button
                            type="button"
                            class="px-3 py-1.5 rounded bg-white/5 hover:bg-white/10 text-xs text-gray-300"
                            (click)="editingEventId.set(null)"
                          >
                            Cancel
                          </button>
                        </div>
                      } @else {
                        @if (eventDisplayText(event); as text) {
                          <p class="mt-2 text-sm text-gray-200 whitespace-pre-wrap">{{ text }}</p>
                        }
                        @if (event.text_amended) {
                          <p class="mt-2 text-xs text-gray-500">
                            Raw: {{ event.text_raw }}
                          </p>
                        }
                      }
                    </div>
                  }
                </div>
              </section>
            }

            @if (proposal(); as p) {
              <section class="t-card rounded-lg p-4 space-y-3">
                <div class="flex items-center justify-between">
                  <h3 class="text-sm font-semibold text-white">Knowledge update proposal</h3>
                  <button
                    type="button"
                    class="text-xs px-3 py-1.5 rounded bg-brand-500/20 text-brand-100 ring-1 ring-brand-300/30"
                    (click)="goSurface('review')"
                  >
                    Review facts
                  </button>
                </div>
                <div class="grid sm:grid-cols-3 gap-2 text-xs">
                  <div class="rounded bg-black/20 border border-white/10 p-3">
                    <div class="text-[10px] uppercase tracking-wider text-gray-500">Facts</div>
                    <div class="text-xl text-white font-semibold">{{ proposalFacts().length }}</div>
                  </div>
                  <div class="rounded bg-black/20 border border-white/10 p-3">
                    <div class="text-[10px] uppercase tracking-wider text-gray-500">Evidence</div>
                    <div class="text-xl text-white font-semibold">{{ proposalEvidenceCount() }}</div>
                  </div>
                  <div class="rounded bg-black/20 border border-white/10 p-3">
                    <div class="text-[10px] uppercase tracking-wider text-gray-500">Status</div>
                    <div class="text-sm text-gray-200 mt-1">{{ p.status }}</div>
                  </div>
                </div>
              </section>
            }
          } @else {
            <section class="t-card rounded-lg p-8 text-center text-gray-400">
              Prepare a capture plan to start the guided session.
            </section>
          }
        </main>
      </div>
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
                  <article class="rounded border border-white/10 bg-black/20 p-4">
                    <div class="flex items-start justify-between gap-3">
                      <div class="min-w-0">
                        <div class="flex flex-wrap items-center gap-2">
                          <span class="ck-mono text-[10px] uppercase tracking-wider px-2 py-1 rounded bg-brand-500/15 text-brand-200">
                            {{ proposalFactType(fact) }}
                          </span>
                          <span class="text-xs text-gray-500">{{ proposalFactConfidence(fact) }}</span>
                          @if (fact.amended) {
                            <span class="text-xs text-amber-200">HITL amended</span>
                          }
                        </div>
                        <p class="mt-3 text-sm text-gray-100 leading-relaxed whitespace-pre-wrap">{{ proposalFactText(fact) }}</p>
                        @if (fact.raw_text && fact.raw_text !== proposalFactText(fact)) {
                          <p class="mt-2 text-xs text-gray-500">Raw: {{ fact.raw_text }}</p>
                        }
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
                [disabled]="!proposalFacts().length"
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
                class="w-full inline-flex items-center justify-center gap-2 px-3 py-2 rounded bg-brand-500 hover:bg-brand-400 text-sm text-white"
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

  objective =
    'Capture tacit troubleshooting and offer reasoning from a senior industrial expert.';
  expertProfile = 'Senior field engineer';
  durationMinutes = 20;
  contextId = '';
  systemId = '';
  answer = '';
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
  readonly session = signal<CaptureSession | null>(null);
  readonly selectedQuestionId = signal<string | null>(null);
  readonly lastEvaluation = signal<TurnResponse['evaluation'] | null>(null);
  readonly nextPrompt = signal<string | null>(null);
  readonly lastSystemPromptEventId = signal<string | null>(null);
  readonly interruptionOfEventId = signal<string | null>(null);
  readonly proposal = signal<CaptureProposal | null>(null);
  readonly events = signal<CaptureEvent[]>([]);
  readonly retrieval = signal<RetrievalPrefetch>({
    status: 'idle',
    chunks: [],
    scores: [],
    metadatas: [],
  });
  readonly editingEventId = signal<string | null>(null);
  editingText = '';

  readonly surfaceNav: Array<{ id: CaptureSurfaceView; label: string; icon: string }> = [
    { id: 'dashboard', label: 'Sessions', icon: 'layout-dashboard' },
    { id: 'prep', label: 'Preparation', icon: 'sliders-horizontal' },
    { id: 'plan', label: 'Plan', icon: 'list-checks' },
    { id: 'session', label: 'Capture', icon: 'mic' },
    { id: 'review', label: 'Proposal', icon: 'check-circle-2' },
  ];
  readonly voiceWaveBars = [10, 18, 26, 14, 22, 30, 16, 24, 12, 20];

  private recorder: MediaRecorder | null = null;
  private chunks: BlobPart[] = [];
  private stream: MediaStream | null = null;
  private partialTranscriptionInFlight = false;
  private prefetchInFlight = false;
  private lastPrefetchText = '';
  private lastPrefetchAt = 0;
  private currentClientTurnId: string | null = null;
  private activeAudio: HTMLAudioElement | null = null;
  private audioQueue: string[] = [];
  private revokedAudioUrls: string[] = [];
  private speechGeneration = 0;
  private autoResumeTimer: ReturnType<typeof setTimeout> | null = null;

  ngOnInit(): void {
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
    this.loading.set(true);
    this.api
      .createCapturePlan({
        title: 'Expert Knowledge Capture',
        objective: this.objective,
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

  openDashboardSession(row: CaptureSession): void {
    this.session.set(row);
    this.proposal.set(null);
    this.selectedQuestionId.set(row.plan.questions?.[0]?.id || null);
    this.refreshEvents(row.id);
    this.activeSurface.set(row.status === 'completed' ? 'review' : 'session');
  }

  openDashboardProposal(row: CaptureProposal): void {
    this.proposal.set(row);
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

  systemLabel(systemId?: string | null): string | null {
    if (!systemId) return null;
    return this.systems().find((system) => system.id === systemId)?.name || systemId.slice(0, 8);
  }

  private applySystemScope(system: SystemOption | null): void {
    if (!system || system.id !== this.systemId) return;
    this.systemScoped.set(true);
    if (system.objective?.trim()) {
      this.objective = system.objective.trim();
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
          this.speak(typed.next_prompt);
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
      .listCaptureEvents(sessionId)
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

  toggleConversationMode(): void {
    this.conversationMode.set(this.conversationMode() === 'manual' ? 'conversation_only' : 'manual');
    this.lastConversationStep.set(null);
    this.stopConversationSession();
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
    return this.conversationSessionActive() ? 'Pause session' : 'Start session';
  }

  lastConversationLabel(): string {
    const step = this.lastConversationStep();
    if (!step) return 'Voice actions will be inferred from the next final transcript.';
    const labels: Record<string, string> = {
      answer_ready: 'Answer captured and evaluated',
      correction: 'Correction captured',
      more_detail: 'Additional detail captured',
      proposal_requested: 'Proposal prepared, waiting for confirmation',
      proposal_confirmed: 'Proposal confirmed, waiting for final acceptance',
      proposal_rejected: 'Proposal rejected, waiting for correction',
      accept_confirmed: 'Proposal accepted',
      accept_rejected: 'Acceptance paused',
    };
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
    const draft = this.answer.trim();
    if (!draft) {
      this.api
        .createCaptureProposal(session.id)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe((proposal) => {
          this.proposal.set(proposal as CaptureProposal);
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
            this.proposal.set(proposal as CaptureProposal);
            this.refreshDashboard();
            this.activeSurface.set('review');
            this.voiceState.set('idle');
          });
      });
  }

  runConversationStep(session: CaptureSession, text: string): void {
    const clean = text.trim();
    if (!clean) return;
    this.voiceState.set('thinking');
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
            this.proposal.set(step.proposal as CaptureProposal);
            if (step.intent === 'proposal_requested') {
              this.activeSurface.set('review');
            }
          }
          this.currentClientTurnId = null;
          this.interruptionOfEventId.set(null);
          this.refreshEvents(step.session.id);
          if (step.next_prompt) {
            this.speak(step.next_prompt);
          } else {
            this.voiceState.set('idle');
            this.scheduleConversationResume();
          }
        },
        error: () => this.voiceState.set('idle'),
      });
  }

  acceptProposal(proposalId: string): void {
    this.api
      .reviewCaptureProposal(proposalId, {
        status: 'accepted',
        reviewer: 'demo-operator',
        review_notes: 'Accepted from Knowledge Capture demo.',
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((proposal) => {
        this.proposal.set(proposal as CaptureProposal);
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
    return fact.id || `${index}:${this.proposalFactText(fact).slice(0, 80)}`;
  }

  proposalFactText(fact: ProposalFact): string {
    return (fact.text || fact.statement || '').trim();
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

  async toggleRecording(): Promise<void> {
    if (this.recording()) {
      this.recorder?.stop();
      this.recording.set(false);
      return;
    }
    if (this.speaking()) {
      this.interruptSpeech();
    }
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    this.chunks = [];
    this.currentClientTurnId = this.newTurnId();
    this.lastPrefetchText = '';
    this.lastPrefetchAt = 0;
    this.recorder = new MediaRecorder(this.stream);
    this.recorder.ondataavailable = (event) => {
      if (event.data.size <= 0) return;
      this.chunks.push(event.data);
      this.transcribePartialRecording();
    };
    this.recorder.onstop = () => this.transcribeRecording();
    this.recorder.start(1200);
    this.recording.set(true);
    this.voiceState.set('listening');
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
    this.conversationSessionActive.set(true);
    const firstPrompt = this.currentQuestion()?.question || this.nextPrompt();
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
    const question = this.currentQuestion();
    if (question?.question) {
      this.speak(question.question);
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
    return this.conversationMode() === 'conversation_only' ? 'Ready for conversation-only session' : 'Ready for manual capture';
  }

  speak(text: string): void {
    const clean = text.trim();
    if (!clean) {
      return;
    }
    this.stopSpeech(false);
    const generation = ++this.speechGeneration;
    this.audioQueue = this.splitSpeech(clean);
    this.playNextSpeechSegment(generation);
  }

  interruptSpeech(): void {
    const promptEventId = this.lastSystemPromptEventId();
    this.stopSpeech(true);
    this.interruptionOfEventId.set(promptEventId || 'client-interruption');
    this.voiceState.set('interrupted');
  }

  private transcribeRecording(): void {
    this.stream?.getTracks().forEach((track) => track.stop());
    const blob = new Blob(this.chunks, { type: 'audio/webm' });
    this.transcribing.set(true);
    this.voiceState.set('partial_transcribing');
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
            }
          }
        },
        error: () => {
          this.transcribing.set(false);
          this.voiceState.set('idle');
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
          audio.onerror = () => this.playNextSpeechSegment(generation);
          void audio.play();
        },
        error: () => this.playNextSpeechSegment(generation),
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

  private async startRecordingTurn(): Promise<void> {
    if (this.recording() || this.transcribing()) {
      return;
    }
    this.clearAutoResumeTimer();
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      this.conversationSessionActive.set(false);
      this.voiceState.set('idle');
      return;
    }
    this.chunks = [];
    this.currentClientTurnId = this.newTurnId();
    this.lastPrefetchText = '';
    this.lastPrefetchAt = 0;
    this.recorder = new MediaRecorder(this.stream);
    this.recorder.ondataavailable = (event) => {
      if (event.data.size <= 0) return;
      this.chunks.push(event.data);
      this.transcribePartialRecording();
    };
    this.recorder.onstop = () => this.transcribeRecording();
    this.recorder.start(1200);
    this.recording.set(true);
    this.voiceState.set('listening');
  }

  private stopConversationSession(): void {
    this.conversationSessionActive.set(false);
    this.clearAutoResumeTimer();
    this.stopSpeech(false);
    if (this.recording()) {
      this.recorder?.stop();
      this.recording.set(false);
    } else if (!this.transcribing()) {
      this.stream?.getTracks().forEach((track) => track.stop());
      this.voiceState.set('idle');
    }
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
