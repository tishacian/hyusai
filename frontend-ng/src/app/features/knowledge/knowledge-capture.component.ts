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
  capability_id?: string | null;
  context_id?: string | null;
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

@Component({
  selector: 'app-knowledge-capture',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, IconComponent, RouterLink],
  template: `
    <section class="space-y-5">
      <header class="t-card t-elevated rounded-lg p-5 flex items-start justify-between gap-4">
        <div>
          <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Knowledge · Capture</p>
          <h1 class="text-2xl font-semibold text-white mt-1">Expert Knowledge Capture</h1>
          <p class="text-sm text-gray-400 mt-2 max-w-3xl">
            Capability-led capture: select a Context, identify knowledge gaps, run a guided voice
            session, then emit a reviewable Knowledge update proposal.
          </p>
        </div>
        <span class="text-xs px-3 py-2 rounded bg-white/5 ring-1 ring-white/10 text-gray-300">
          Phase 0 · cascade voice runtime
        </span>
      </header>

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
                    (click)="toggleRecording()"
                  >
                    <app-icon [name]="recording() ? 'square' : 'mic'" [size]="14" />
                    {{ recording() ? 'Stop listening' : speaking() ? 'Interrupt & answer' : transcribing() ? 'Transcribing...' : 'Listen' }}
                  </button>
                  <button
                    type="button"
                    class="inline-flex items-center gap-2 px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-200 ring-1 ring-white/10"
                    [disabled]="!answer.trim()"
                    (click)="sendAnswer(s)"
                  >
                    <app-icon name="send" [size]="14" /> Evaluate answer
                  </button>
                  @if (speaking()) {
                    <button
                      type="button"
                      class="inline-flex items-center gap-2 px-3 py-2 rounded bg-amber-500/20 hover:bg-amber-500/30 text-sm text-amber-100 ring-1 ring-amber-400/20"
                      (click)="interruptSpeech()"
                    >
                      <app-icon name="pause" [size]="14" /> Interrupt AI
                    </button>
                  }
                  <button
                    type="button"
                    class="inline-flex items-center gap-2 px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-200 ring-1 ring-white/10"
                    (click)="createProposal(s)"
                  >
                    <app-icon name="check-circle-2" [size]="14" /> Create proposal
                  </button>
                </div>

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
                          @for (chunk of rr.chunks.slice(0, 2); track chunk) {
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
                          #{{ event.sequence }} · {{ event.speaker || 'system' }} · {{ event.status }}
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
                        <p class="mt-2 text-sm text-gray-200 whitespace-pre-wrap">{{ event.text }}</p>
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
                    class="text-xs px-3 py-1.5 rounded bg-emerald-500/20 text-emerald-200 ring-1 ring-emerald-400/20"
                    (click)="acceptProposal(p.id)"
                  >
                    Accept proposal
                  </button>
                </div>
                <pre class="whitespace-pre-wrap text-xs text-gray-300 bg-black/30 rounded p-3 max-h-80 overflow-auto">{{ p.proposal?.recommended_ingestion?.content }}</pre>
              </section>
            }
          } @else {
            <section class="t-card rounded-lg p-8 text-center text-gray-400">
              Prepare a capture plan to start the guided session.
            </section>
          }
        </main>
      </div>
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
  readonly recording = signal(false);
  readonly transcribing = signal(false);
  readonly speaking = signal(false);
  readonly voiceState = signal<Voice2VoiceState>('idle');
  readonly session = signal<CaptureSession | null>(null);
  readonly selectedQuestionId = signal<string | null>(null);
  readonly lastEvaluation = signal<TurnResponse['evaluation'] | null>(null);
  readonly nextPrompt = signal<string | null>(null);
  readonly lastSystemPromptEventId = signal<string | null>(null);
  readonly interruptionOfEventId = signal<string | null>(null);
  readonly proposal = signal<any | null>(null);
  readonly events = signal<CaptureEvent[]>([]);
  readonly retrieval = signal<RetrievalPrefetch>({
    status: 'idle',
    chunks: [],
    scores: [],
    metadatas: [],
  });
  readonly editingEventId = signal<string | null>(null);
  editingText = '';

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

  ngOnInit(): void {
    this.contextId = this.route.snapshot.queryParamMap.get('contextId') || '';
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
      .subscribe((payload) => this.systems.set(payload.systems || []));
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
          this.loading.set(false);
        },
        error: () => this.loading.set(false),
      });
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
    return this.events().filter((event) => Boolean(event.text || event.text_raw || event.text_amended));
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
    if (rr.status === 'searching') return 'Searching in parallel';
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
    this.api
      .createCaptureProposal(session.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((proposal) => this.proposal.set(proposal));
  }

  acceptProposal(proposalId: string): void {
    this.api
      .reviewCaptureProposal(proposalId, {
        status: 'accepted',
        reviewer: 'demo-operator',
        review_notes: 'Accepted from Knowledge Capture demo.',
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((proposal) => this.proposal.set(proposal));
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

  speak(text: string): void {
    const clean = text.trim();
    if (!clean) {
      return;
    }
    this.stopSpeech(false);
    this.audioQueue = this.splitSpeech(clean);
    this.playNextSpeechSegment();
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
          if (session) this.maybePrefetchRetrieval(session, res.text, true);
        },
        error: () => {
          this.transcribing.set(false);
          this.voiceState.set('idle');
        },
      });
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
    this.voiceState.set('retrieving');
    this.retrieval.set({ status: 'searching', chunks: [], scores: [], metadatas: [] });
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

  private playNextSpeechSegment(): void {
    const segment = this.audioQueue.shift();
    if (!segment) {
      this.speaking.set(false);
      this.voiceState.set('idle');
      this.cleanupAudioUrls();
      return;
    }
    this.speaking.set(true);
    this.voiceState.set('speaking');
    this.api
      .synthesizeSpeech(segment.slice(0, 600))
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => {
          const url = URL.createObjectURL(blob);
          this.revokedAudioUrls.push(url);
          const audio = new Audio(url);
          this.activeAudio = audio;
          audio.onended = () => this.playNextSpeechSegment();
          audio.onerror = () => this.playNextSpeechSegment();
          void audio.play();
        },
        error: () => this.playNextSpeechSegment(),
      });
  }

  private stopSpeech(markInterrupted: boolean): void {
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

  private cleanupAudioUrls(): void {
    this.revokedAudioUrls.forEach((url) => URL.revokeObjectURL(url));
    this.revokedAudioUrls = [];
  }

  private newTurnId(): string {
    return globalThis.crypto?.randomUUID?.() || `turn-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }
}
