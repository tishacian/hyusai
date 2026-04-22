import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ToastrService } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
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
                            @if (step.description) {
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
                  {{ msg.content || '(no response)' }}
                </div>
              </div>

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
                          class="rounded-md px-3 py-2 text-[12px] bg-white/[0.02] dark:bg-white/[0.03] ring-1 ring-black/5 dark:ring-white/5"
                        >
                          <div class="flex items-center gap-2 mb-0.5">
                            <span
                              class="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-mono shrink-0 bg-brand-500/15 text-brand-400"
                            >
                              {{ i + 1 }}
                            </span>
                            <span class="font-medium text-gray-900 dark:text-white truncate">
                              {{ sourceTitle(src) }}
                            </span>
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
          class="p-2.5 rounded-xl transition ring-1"
          [class.bg-red-500\\/20]="recording()"
          [class.ring-red-500\\/40]="recording()"
          [class.text-red-300]="recording()"
          [class.bg-white\\/5]="!recording()"
          [class.ring-white\\/10]="!recording()"
          [class.text-gray-300]="!recording()"
          [title]="recording() ? 'Stop recording' : 'Record voice'"
          (click)="toggleMic()"
        >
          <app-icon [name]="recording() ? 'square' : 'mic'" [size]="15" />
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
  private readonly toast = inject(ToastrService);
  private readonly health = inject(RuntimeHealthService);
  private readonly destroyRef = inject(DestroyRef);
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
  ttsEnabled = signal(false);

  private readonly openTrails = signal<Set<string>>(new Set());
  private readonly openSources = signal<Set<string>>(new Set());
  private mediaRecorder: MediaRecorder | null = null;
  private recordedChunks: Blob[] = [];
  private currentAudio: HTMLAudioElement | null = null;
  private streamStart = 0;

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
          if (chunk.chunk_type === 'text' && typeof chunk.content === 'string') {
            buffer += chunk.content;
            this.streamBuffer.set(buffer);
          } else if (chunk.chunk_type === 'decision_step' && chunk.decision_step) {
            const step = chunk.decision_step as DecisionStep;
            reasoning = upsertStep(reasoning, step);
            this.liveSteps.set([...reasoning]);
          } else if (chunk.chunk_type === 'error' && chunk.content) {
            buffer += `\n\n⚠ ${chunk.content}`;
            this.streamBuffer.set(buffer);
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
            if (this.ttsEnabled() && buffer.trim()) this.playTTS(buffer);
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
    if (!next) this.currentAudio?.pause();
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
    this.api.transcribeAudio(blob).subscribe({
      next: (res) => {
        if (res?.text) {
          this.userInput = (this.userInput ? this.userInput + ' ' : '') + res.text;
        }
      },
      error: () => this.toast.error('Transcription failed', 'Voice'),
    });
  }

  private playTTS(text: string): void {
    const clean = text.replace(/[#*_`\[\]|]/g, '').slice(0, 2000);
    this.api.synthesizeSpeech(clean).subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(blob);
        this.currentAudio?.pause();
        const audio = new Audio(url);
        this.currentAudio = audio;
        audio.onended = () => URL.revokeObjectURL(url);
        audio.play().catch(() => URL.revokeObjectURL(url));
      },
      error: () => {
        /* non-blocking */
      },
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
