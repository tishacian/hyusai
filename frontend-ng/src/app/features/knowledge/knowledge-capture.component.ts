import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ApiService } from '@app/core/api.service';
import { PermissionsService } from '@app/core/permissions.service';
import { VoiceTtsPlaybackService, VoiceTtsState } from '@app/core/voice-tts-playback.service';
import { VoiceSessionConnection, VoiceSessionEvent, VoiceSessionService } from '@app/core/voice-session.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { IconComponent } from '@app/shared/ui/icon.component';

interface CaptureQuestion {
  id: string;
  question: string;
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
  objective?: string;
  rationale?: string;
  oracle_confidence?: number;
  estimated_minutes?: number;
  knowledge_refs?: Array<Record<string, unknown>>;
  subtopics?: CaptureSubtopic[];
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
  voice_runtime?: string | null;
  title: string;
  objective: string;
  duration_minutes?: number | null;
  status: string;
  plan: CapturePlan;
  transcript?: Array<{ id: string; speaker: string; text: string }>;
  evaluations?: Array<{ verdict: string; score: number; follow_up?: string }>;
  metrics?: Record<string, number | string | null | undefined>;
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
  status: 'idle' | 'searching' | 'ready' | 'late' | 'timeout' | 'error' | 'completed';
  latency_ms?: number;
  collection_name?: string;
  chunks: string[];
  scores: number[];
  metadatas: Record<string, any>[];
  hints?: CaptureHint[];
  active_subtopic_id?: string;
}

type ConversationMode = 'manual' | 'conversation_only';
type CapturePlanMode = 'ai_plan' | 'provided_plan' | 'free_conversation' | 'plan_build';
type CaptureSurfaceView = 'dashboard' | 'prep' | 'plan' | 'plan_build' | 'session' | 'review';
type QualityTab = 'imprecisions' | 'contradictions' | 'open_questions';

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
  closure_sheet?: {
    markdown?: string;
    topics?: string[];
    captured_facts?: unknown[];
    unresolved?: Array<{ bucket?: string; label?: string; status?: string }>;
  } | null;
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
  imports: [DecimalPipe, FormsModule, RouterLink, IconComponent],
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
    `,
  ],
  template: `
    <section class="space-y-5">
      <header class="t-card t-elevated rounded-lg p-5 flex items-start justify-between gap-4">
        <div>
          <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">
            {{ isDemoMode() ? 'Capture expert' : (systemScoped() ? 'System · Workbench' : 'Knowledge · Capture') }}
          </p>
          <h1 class="text-2xl font-semibold text-white mt-1">
            {{ isDemoMode() ? 'Préserver le savoir terrain' : (systemScoped() ? systemLabel(systemId) || 'Expert Knowledge Capture' : 'Expert Knowledge Capture') }}
          </h1>
          <p class="text-sm text-gray-400 mt-2 max-w-3xl">
            {{ isDemoMode()
              ? 'Préparez une courte session, échangez avec l’expert, puis relisez les connaissances proposées avant intégration.'
              : systemScoped()
              ? 'Espace de capture dédié : préparer une session, échanger avec un expert, extraire les savoirs utiles et les relire avant intégration.'
              : 'Capture guidée ou libre : partez d’un sujet, échangez avec l’expert, puis transformez les enseignements en proposition relue.' }}
          </p>
        </div>
        <div class="flex flex-col items-end gap-2">
          @if (!isDemoMode()) {
            <span class="text-xs px-3 py-2 rounded bg-white/5 ring-1 ring-white/10 text-gray-300">
              Capture vocale
            </span>
          }
          <span class="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded bg-brand-500/10 ring-1 ring-brand-300/20 text-brand-100">
            <app-icon name="shield-check" [size]="12" />
            {{ isDemoMode() ? 'Validation humaine' : 'Trace & revue humaine' }}
          </span>
          @if (!isDemoMode()) {
            <span class="text-xs px-3 py-1.5 rounded bg-white/5 ring-1 ring-white/10 text-gray-300">
              {{ conversationMode() === 'conversation_only' ? 'Conversation libre' : 'Session guidée' }}
            </span>
            <a
              [routerLink]="workspaceAccessRoute()"
              class="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
            >
              <app-icon name="settings-2" [size]="12" />
              Gérer les accès
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
            <p class="ck-mono text-[10px] uppercase tracking-[0.18em] text-gray-500">Étape 1 · Préparation</p>
            <h2 class="mt-2 text-3xl text-white font-semibold">Définir le sujet de capture</h2>
            <p class="mt-2 text-sm text-gray-400 max-w-3xl">
              {{ isDemoMode()
                ? 'Indiquez simplement le sujet à explorer. Agentium se charge de guider l’échange et de préparer la connaissance à relire.'
                : 'Donnez un titre et décrivez ce que l’expert doit transmettre. Les sources et paramètres avancés restent disponibles sans encombrer le parcours pilote.' }}
            </p>
          </div>

          <div class="space-y-5 flex-1">
            <div>
              <label class="block text-[11px] uppercase tracking-wider text-gray-500 mb-2">Titre de session *</label>
              <input
                class="w-full rounded bg-black/30 border border-white/10 px-4 py-3 text-sm text-white"
                [(ngModel)]="sessionTitle"
                placeholder="Ex. Usure prématurée des paliers - retours terrain"
              />
            </div>

            <div>
              <label class="block text-[11px] uppercase tracking-wider text-gray-500 mb-2">Sujet (optionnel — précisez à la voix)</label>
              <div class="flex flex-wrap gap-2">
                <button
                  type="button"
                  class="inline-flex items-center gap-2 px-4 py-2.5 rounded bg-brand-500/20 text-brand-100 ring-1 ring-brand-300/30 hover:bg-brand-500/30"
                  (click)="dictatePrepSubject()"
                >
                  <app-icon name="mic" [size]="14" />
                  Décrire le sujet à la voix
                </button>
                @if (objective.trim()) {
                  <p class="text-sm text-gray-300 flex-1 min-w-[200px]">{{ objective }}</p>
                }
              </div>
            </div>

            @if (!isDemoMode()) {
            <div>
              <label class="block text-[11px] uppercase tracking-wider text-gray-500 mb-2">Domaine</label>
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
                Sources et contexte avancés
              </button>
              @if (showAdvancedSetup()) {
              <div class="mt-3">
              <label class="block text-[11px] uppercase tracking-wider text-gray-500 mb-2">Contexte documentaire</label>
              <select
                class="w-full rounded bg-black/30 border border-white/10 px-4 py-3 text-sm text-white"
                [(ngModel)]="contextId"
                (ngModelChange)="onContextChange($event)"
              >
                <option value="">Sources par défaut du workspace</option>
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
                        Nouveau contexte
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
                      Rattachez une collection Knowledge à la capture sans quitter la préparation.
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
                    Le contexte stocke <span class="font-mono text-gray-300">environment_state.collection</span> pour la recherche live.
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
                    Aucune collection Knowledge n’est disponible dans ce workspace pour l’instant.
                  </p>
                }
              </div>
              </div>
              }
            </div>
            }

            <div [class]="isDemoMode() ? 'grid gap-4' : 'grid md:grid-cols-[1fr_220px] gap-4'">
              <div>
                <label class="block text-[11px] uppercase tracking-wider text-gray-500 mb-2">
                  {{ isDemoMode() ? 'Personne interrogée' : 'Expert' }}
                </label>
                <input
                  class="w-full rounded bg-black/30 border border-white/10 px-4 py-3 text-sm text-white"
                  [(ngModel)]="expertProfile"
                />
              </div>
              @if (!isDemoMode()) {
              <div>
                <label class="block text-[11px] uppercase tracking-wider text-gray-500 mb-2">Durée maximale</label>
                @if (durationUnlimited()) {
                  <div class="rounded bg-black/30 border border-white/10 px-4 py-3 text-sm text-brand-100">Sans limite</div>
                } @else {
                  <input
                    type="number"
                    min="5"
                    max="90"
                    class="w-full rounded bg-black/30 border border-white/10 px-4 py-3 text-sm text-white"
                    [(ngModel)]="durationMinutes"
                  />
                }
                <button
                  type="button"
                  class="mt-2 text-xs text-brand-200 hover:text-brand-100"
                  (click)="toggleDurationUnlimited()"
                >
                  {{ durationUnlimited() ? 'Fixer une durée' : 'Sans limite' }}
                </button>
              </div>
              }
            </div>

            <div class="kc-sticky-action flex items-center justify-end gap-3 pt-4 rounded-t-lg border-t border-white/10 bg-black/75 px-1 py-3 backdrop-blur">
              <button
                type="button"
                class="px-4 py-2 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-300 ring-1 ring-white/10"
                (click)="goSurface('dashboard')"
              >
                Annuler
              </button>
              <button
                type="button"
                class="inline-flex items-center gap-2 px-5 py-2.5 rounded bg-brand-300 hover:bg-brand-200 text-sm font-semibold text-black disabled:opacity-50"
                [disabled]="loading() || !sessionTitle.trim() || !canCaptureCreate()"
                [title]="preparationBlockingHint() || ''"
                (click)="continueFromPreparation()"
              >
                Choisir le mode de capture
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
        <section [class]="isDemoMode() ? 'grid gap-5 max-w-5xl mx-auto' : 'grid xl:grid-cols-[1.5fr_1fr] gap-5'">
          <div class="t-card rounded-lg p-5 space-y-4">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Sessions de capture</p>
                <h2 class="text-lg font-semibold text-white">
                  {{ isDemoMode() ? 'Vos sessions' : 'Tableau de bord' }}
                </h2>
              </div>
              @if (!isDemoMode()) {
              <select
                class="rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white"
                [(ngModel)]="dashboardDomainFilter"
                (ngModelChange)="refreshDashboard()"
              >
                <option value="">Tous les domaines</option>
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
                <app-icon name="plus" [size]="14" /> {{ isDemoMode() ? 'Nouvelle capture' : 'Nouvelle session' }}
              </button>
            </div>
            @if (!isDemoMode()) {
            <div class="grid md:grid-cols-4 gap-3">
              <div class="rounded bg-black/20 border border-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500">Sessions</div>
                <div class="text-2xl text-white font-semibold">{{ dashboardSessions().length }}</div>
              </div>
              <div class="rounded bg-black/20 border border-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500">Actives</div>
                <div class="text-2xl text-white font-semibold">{{ activeSessionCount() }}</div>
              </div>
              <div class="rounded bg-black/20 border border-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500">Propositions</div>
                <div class="text-2xl text-white font-semibold">{{ dashboardProposals().length }}</div>
              </div>
              <div class="rounded bg-black/20 border border-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500">À relire</div>
                <div class="text-2xl text-white font-semibold">{{ pendingProposalCount() }}</div>
              </div>
            </div>
            }
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
                          Auteur
                        </span>
                      }
                    </div>
                    <span class="text-xs px-2 py-1 rounded bg-white/5 text-gray-300">{{ workflowStatusLabel(row.status) }}</span>
                  </div>
                  <div class="mt-3 grid grid-cols-3 gap-2 text-xs text-gray-400">
                    <span>{{ isFreeConversationSession(row) ? 'capture libre' : planQuestions(row).length + ' questions' }}</span>
                    <span>{{ row.metrics?.['captured_facts'] || 0 }} faits</span>
                    @if (!isDemoMode()) {
                      <span>{{ isFreeConversationSession(row) ? 'sans couverture' : coveragePercent(row) + '% couvert' }}</span>
                    }
                  </div>
                </button>
              } @empty {
                <div class="rounded border border-dashed border-white/10 bg-black/20 p-8 text-center text-gray-500">
                  Aucune session pour l’instant. Créez une capture depuis cette surface système.
                </div>
              }
            </div>
            @if (dashboardQualityBacklog().length) {
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
              <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Propositions Knowledge</p>
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
                      {{ row.proposal?.title || 'Proposition de connaissance' }}
                    </div>
                    <span class="text-xs px-2 py-1 rounded bg-white/5 text-gray-300">{{ workflowStatusLabel(row.status) }}</span>
                  </div>
                  <div class="mt-2 text-xs text-gray-500">
                    {{ row.proposal?.captured_facts?.length || 0 }} faits · {{ row.proposal?.audit?.event_count || 0 }} événements d’audit
                  </div>
                </button>
              } @empty {
                <div class="rounded border border-dashed border-white/10 bg-black/20 p-6 text-center text-gray-500">
                  Aucune proposition en attente de revue.
                </div>
              }
            </div>
          </div>
          }
        </section>
      }

      @if (activeSurface() === 'session') {
        @if (session(); as s) {
          <section class="space-y-4">
            <section class="t-card rounded-lg p-4">
              <div class="flex flex-wrap items-center justify-between gap-4">
                <div class="min-w-0">
                  <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Capture en cours</p>
                  <h2 class="text-lg font-semibold text-white mt-1 truncate">{{ s.title }}</h2>
                </div>
                <div class="flex flex-wrap items-center gap-2 text-xs">
                  <span class="px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">{{ workflowStatusLabel(s.status) }}</span>
                  @if (sessionTimerView(s); as timer) {
                    <span
                      [class]="timer.blink
                        ? 'px-2 py-1 rounded bg-amber-500/20 text-amber-100 ring-1 ring-amber-400/30 kc-timer-blink'
                        : 'px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10'"
                    >
                      {{ timer.label }}
                    </span>
                  }
                  <span class="px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">
                    {{ captureProgressLabel(s) }}
                  </span>
                  <span class="px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">
                    {{ s.metrics?.['captured_facts'] || 0 }} faits
                  </span>
                  <span class="px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">
                    {{ knowledgeScopeLabel() }}
                  </span>
                  @if (isAuthor(s)) {
                    <span class="px-2 py-1 rounded bg-brand-500/15 text-brand-100 ring-1 ring-brand-300/20">Auteur</span>
                  }
                  @if (s.status === 'active') {
                    <button type="button" class="px-2 py-1 rounded bg-white/5 text-gray-300 hover:text-white text-xs" (click)="pauseSession(s)">Pause</button>
                  }
                  @if (s.status === 'paused') {
                    <button type="button" class="px-2 py-1 rounded bg-brand-500/20 text-brand-100 text-xs" (click)="resumeSession(s)">Reprendre</button>
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
                    Choisissez de terminer, prolonger de 15 minutes ou replanifier une session — sans interruption vocale.
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
                    Terminer
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
                ? 'grid xl:grid-cols-[280px_minmax(0,1fr)] gap-4 items-start'
                : 'grid xl:grid-cols-[300px_minmax(0,1fr)_360px] gap-4 items-start'"
            >
              <aside class="t-card rounded-lg p-4 max-h-[calc(100vh-270px)] overflow-auto space-y-4">
                <div>
                  <div class="flex items-center justify-between gap-3">
                    <div>
                      <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Structure</p>
                      <h3 class="text-sm font-semibold text-white">
                        {{ isFreeConversationSession(s) ? 'Conversation libre' : 'Sujets de capture' }}
                      </h3>
                    </div>
                    <span class="text-xs text-brand-200">{{ captureProgressLabel(s) }}</span>
                  </div>
                </div>

                <div class="grid grid-cols-2 gap-2 text-xs">
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

                @if (isFreeConversationSession(s)) {
                  <div class="rounded border border-dashed border-white/10 bg-black/20 p-4 text-sm text-gray-400">
                    L’expert pilote le fil. Agentium extrait les faits, corrections et demandes de synthèse sans plan imposé.
                  </div>
                } @else {
                  <div class="space-y-3">
                    @for (topic of planTopics(s); track topic.id) {
                      <div class="rounded border border-white/10 bg-white/[0.03] p-3">
                        <div class="flex items-start justify-between gap-3">
                          <div class="min-w-0">
                            <div class="text-xs font-semibold text-gray-200 truncate">{{ topic.title }}</div>
                            @if (topic.objective) {
                              <p class="mt-1 text-[11px] text-gray-500 line-clamp-2">{{ topic.objective }}</p>
                            }
                          </div>
                          <span class="shrink-0 rounded bg-white/5 px-2 py-1 text-[10px] text-gray-400">
                            {{ (topic.subtopics || []).length }} sous-sujet(s)
                          </span>
                        </div>
                        @for (subtopic of topic.subtopics || []; track subtopic.id) {
                          <button
                            type="button"
                            [class]="subtopicRailClass(s, subtopic)"
                            (click)="selectCaptureSubtopic(subtopic.id)"
                          >
                            <span class="min-w-0">
                              <span class="block truncate">{{ subtopic.title }}</span>
                              @if (subtopic.objective) {
                                <span class="mt-0.5 block truncate text-[10px] opacity-70">{{ subtopic.objective }}</span>
                              }
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
              </aside>

              <main class="t-card rounded-lg p-4 min-h-[calc(100vh-270px)] flex flex-col">
                <div class="rounded bg-brand-500/10 border border-brand-400/20 p-4">
                  <div class="flex items-start justify-between gap-3">
                    <div>
                      <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-200">
                        {{ isDemoMode() ? 'Question posée' : 'Relance Agentium' }}
                      </p>
                      <p class="mt-2 text-lg text-white leading-relaxed">{{ currentPromptText() || 'Sélectionnez une question pour démarrer la capture.' }}</p>
                    </div>
                    <button
                      type="button"
                      class="shrink-0 inline-flex items-center gap-2 px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-xs text-gray-200 ring-1 ring-white/10"
                      [disabled]="!currentQuestion()"
                      (click)="readCurrentQuestion()"
                    >
                      <app-icon name="volume-2" [size]="14" /> Lire
                    </button>
                  </div>
                </div>

                @if (!isFreeConversationSession(s) || hintStack().length) {
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
                              [class]="questionStateLabel(s, q) === 'en cours'
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
                      <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">
                        {{ isDemoMode() ? 'Échange avec l’expert' : 'Trace utile' }}
                      </p>
                      <h3 class="text-sm font-semibold text-white">{{ voiceStateLabel() }}</h3>
                    </div>
                    @if (!isDemoMode()) {
                      @if (lastConversationStep(); as step) {
                        <span class="text-xs px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">
                          {{ step.intent }} · {{ (step.confidence * 100).toFixed(0) }}%
                        </span>
                      }
                    }
                  </div>
                  <div class="flex-1 min-h-80 rounded bg-black/20 border border-white/10 p-4 overflow-auto space-y-3">
                    <article class="rounded border border-brand-400/20 bg-brand-500/10 p-4">
                      <div class="flex items-center justify-between gap-3">
                        <span class="ck-mono text-[10px] uppercase tracking-wider text-brand-200">Agentium</span>
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
                  @if (conversationMode() === 'manual') {
                    <textarea
                      class="w-full min-h-28 rounded bg-black/30 border border-white/10 px-4 py-3 text-sm text-white leading-relaxed"
                      [(ngModel)]="answer"
                      (ngModelChange)="onAnswerDraftChange()"
                      placeholder="Saisir ou corriger la réponse expert avant évaluation..."
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
                          <app-icon name="pause" [size]="14" /> Interrompre
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
                        <app-icon name="send" [size]="14" /> Évaluer la réponse
                      </button>
                      <button
                        type="button"
                        class="inline-flex items-center gap-2 px-3 py-2.5 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-200 ring-1 ring-white/10 disabled:opacity-50"
                        [disabled]="!canProposalSubmit(s)"
                        (click)="createProposal(s)"
                      >
                        <app-icon name="check-circle-2" [size]="14" /> Créer la proposition
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
                          <div class="text-[10px] text-gray-500 truncate">
                            {{ isDemoMode() ? 'Prêt à écouter l’expert' : voiceRuntimeArchitecture(s.voice_runtime) }}
                          </div>
                        }
                      </div>
                    </div>
                    @if (!isDemoMode()) {
                    <div class="flex items-center gap-2 text-xs text-gray-400">
                      <span class="px-2 py-1 rounded bg-white/5">{{ sessionStartStateLabel(s) }}</span>
                      <span class="px-2 py-1 rounded bg-white/5">{{ recording() ? 'enregistrement' : 'prêt' }}</span>
                      <span class="px-2 py-1 rounded bg-white/5">{{ speaking() ? 'lecture IA' : 'TTS prêt' }}</span>
                    </div>
                    }
                  </div>
                </div>

              </main>

              @if (!isDemoMode()) {
              <aside class="space-y-4 max-h-[calc(100vh-270px)] overflow-auto">
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
                  <label class="mt-3 flex items-center gap-2 text-xs text-gray-400 cursor-pointer">
                    <input
                      type="checkbox"
                      class="rounded border-white/20"
                      [checked]="deferWeakContradictions()"
                      (change)="toggleDeferWeakContradictions(s, $any($event.target).checked)"
                    />
                    Ne pas interrompre pour contradictions faibles
                  </label>
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
                      @for (chunk of retrieval().chunks.slice(0, 3); track retrievalChunkTrack($index, chunk)) {
                        <p class="rounded bg-black/20 border border-white/10 p-3 text-xs text-gray-400 line-clamp-3">{{ chunk }}</p>
                      }
                    </div>
                  } @else {
                    <p class="mt-3 text-xs text-gray-500 leading-relaxed">
                      Les passages utiles apparaissent ici dès que la réponse devient assez précise. La conversation ne les attend pas.
                    </p>
                  }
                </section>

                @if (proposal(); as p) {
                  <section class="t-card rounded-lg p-4">
                    <div class="flex items-center justify-between gap-3">
                      <div>
                        <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Proposition en brouillon</p>
                        <h3 class="text-sm font-semibold text-white">{{ proposalFacts().length }} fait(s)</h3>
                      </div>
                      <span class="text-xs text-gray-400">{{ workflowStatusLabel(p.status) }}</span>
                    </div>
                    <button type="button" class="mt-3 w-full px-3 py-2 rounded bg-brand-500/20 text-brand-100 ring-1 ring-brand-300/30" (click)="goSurface('review')">
                      Relire la proposition
                    </button>
                  </section>
                }
              </aside>
              }
            </section>
          </section>
        } @else {
          <section class="t-card rounded-lg p-8 text-center text-gray-400">
            Préparez une session de capture avant d’ouvrir le cockpit live.
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
                    {{ isDemoMode() ? 'Trame d’échange' : 'Plan d’entretien' }}
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
                  <app-icon name="eye" [size]="14" /> Prévisualiser le cockpit
                </button>
                }
              </div>

              <div [class]="isDemoMode() ? 'grid md:grid-cols-2 gap-3 text-sm' : 'grid md:grid-cols-3 gap-3 text-sm'">
                @if (isTopicOnlyPlan(s)) {
                  <div class="rounded bg-black/20 border border-white/10 p-3">
                    <div class="text-[10px] uppercase tracking-wider text-gray-500">Sous-sujets</div>
                    <div class="text-2xl text-white font-semibold">{{ planSubtopicCount(s) }}</div>
                  </div>
                  <div class="rounded bg-black/20 border border-white/10 p-3">
                    <div class="text-[10px] uppercase tracking-wider text-gray-500">
                      {{ isDemoMode() ? 'Questions préparées' : 'Banque de questions' }}
                    </div>
                    <div class="text-sm text-gray-200 mt-2">{{ questionBankStatusLabel(s) }}</div>
                  </div>
                } @else {
                  <div class="rounded bg-black/20 border border-white/10 p-3">
                    <div class="text-[10px] uppercase tracking-wider text-gray-500">Questions</div>
                    <div class="text-2xl text-white font-semibold">{{ planQuestions(s).length }}</div>
                  </div>
                  <div class="rounded bg-black/20 border border-white/10 p-3">
                    <div class="text-[10px] uppercase tracking-wider text-gray-500">Durée estimée</div>
                    <div class="text-2xl text-white font-semibold">{{ planDurationMinutes(s) }} min</div>
                  </div>
                }
                @if (!isDemoMode()) {
                <div class="rounded bg-black/20 border border-white/10 p-3">
                  <div class="text-[10px] uppercase tracking-wider text-gray-500">Cible Knowledge</div>
                  <div class="text-sm text-gray-200 mt-2 truncate">{{ selectedContext()?.environment_state?.collection || 'Sources par défaut du workspace' }}</div>
                </div>
                }
              </div>

              @if (planNotice(); as notice) {
                <div [class]="planNoticeClass(notice.tone)">
                  {{ notice.text }}
                </div>
              }

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
                        <p class="mt-2 text-xs text-gray-500">{{ topic.objective || 'Objectif du sujet' }}</p>
                      </div>
                      <span class="rounded bg-brand-500/10 text-brand-100 border border-brand-300/20 px-2 py-1 text-xs">
                        @if (isTopicOnlyPlan(s)) {
                          {{ (topic.subtopics || []).length }} sous-sujets
                        } @else {
                          {{ topicQuestionCount(topic) }} questions
                        }
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

                        @if (!isTopicOnlyPlan(s)) {
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
                                  [class]="questionStateLabel(s, q) === 'en cours'
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
            </div>

            <aside class="t-card rounded-lg p-5 space-y-4 xl:sticky xl:top-4">
              <div>
                <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">
                  {{ isDemoMode() ? 'Démarrer' : 'Démarrage' }}
                </p>
                <h3 class="text-sm font-semibold text-white mt-1">
                  {{ isDemoMode() ? 'Prêt pour l’échange' : 'Prêt pour la capture' }}
                </h3>
              </div>
              @if (isTopicOnlyPlan(s)) {
                <div class="rounded bg-black/20 border border-white/10 p-3 text-xs text-gray-300">
                  {{ questionBankStatusLabel(s) }}
                </div>
                <button
                  type="button"
                  class="w-full inline-flex items-center justify-center gap-2 px-3 py-2 rounded bg-brand-500/80 hover:bg-brand-400 text-xs font-semibold text-white disabled:opacity-40"
                  [disabled]="planDialogueLoading() || !canEditPlan(s)"
                  (click)="validatePlanTopics(s)"
                >
                  {{ isDemoMode() ? 'Confirmer la trame' : 'Valider les sujets' }}
                </button>
              }
              @if (!isDemoMode()) {
              <div class="space-y-2 text-xs">
                <div class="rounded bg-black/20 border border-white/10 p-3">
                  <span class="block text-[9px] uppercase tracking-wider text-gray-500">Contexte</span>
                  <span class="text-gray-200">{{ contextLabel(s.context_id) }}</span>
                </div>
                <div class="rounded bg-black/20 border border-white/10 p-3">
                  <span class="block text-[9px] uppercase tracking-wider text-gray-500">Expert</span>
                  <span class="text-gray-200">{{ expertProfile }}</span>
                </div>
                <div class="rounded bg-black/20 border border-white/10 p-3">
                  <span class="block text-[9px] uppercase tracking-wider text-gray-500">Runtime vocal</span>
                  <span class="text-gray-200">{{ voiceRuntimeArchitecture(s.voice_runtime) }}</span>
                </div>
                <div class="rounded bg-black/20 border border-white/10 p-3">
                  <span class="block text-[9px] uppercase tracking-wider text-gray-500">État</span>
                  <span class="text-gray-200">{{ sessionStartStateLabel(s) }} · {{ planReviewLabel(s) }}</span>
                </div>
              </div>
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
              <button
                type="button"
                class="w-full inline-flex items-center justify-center gap-2 px-3 py-3 rounded bg-brand-500 hover:bg-brand-400 text-sm font-semibold text-white disabled:opacity-50"
                [disabled]="loading() || !canCaptureExecute(s) || !canStartSessionPlan(s)"
                [title]="planBlockingReason(s) || ''"
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
          <section class="max-w-5xl mx-auto py-8 space-y-7">
            <div>
              <p class="ck-mono text-[10px] uppercase tracking-[0.18em] text-gray-500">Étape 2 · Mode de capture</p>
              <h2 class="mt-2 text-3xl text-white font-semibold">
                {{ isDemoMode() ? 'Choisir le déroulé' : 'Choisir le niveau de guidage' }}
              </h2>
              <p class="mt-2 text-sm text-gray-400 max-w-3xl">
                {{ isDemoMode()
                  ? 'Démarrez une conversation libre ou laissez Agentium préparer une trame simple avant l’échange.'
                  : 'Pour un pilote, la capture libre va directement à l’échange. Le plan guidé reste disponible quand il faut sécuriser une trame d’entretien.' }}
              </p>
            </div>

            <div class="space-y-3">
              @for (mode of visiblePlanModes(); track mode.id) {
                <button
                  type="button"
                  [disabled]="mode.disabled"
                  [class]="selectedPlanMode === mode.id
                    ? 'w-full text-left rounded-lg border border-brand-300 bg-brand-500/10 p-5 ring-1 ring-brand-300/40'
                    : mode.disabled
                      ? 'w-full text-left rounded-lg border border-white/10 bg-white/[0.02] p-5 opacity-60 cursor-not-allowed'
                      : 'w-full text-left rounded-lg border border-white/10 bg-white/[0.03] hover:bg-white/[0.06] p-5'"
                  (click)="selectPlanMode(mode.id)"
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
                            Recommandé
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

            @if (selectedPlanMode === 'plan_build' || selectedPlanMode === 'provided_plan') {
              <section class="rounded-lg border border-white/10 bg-white/[0.03] p-5 space-y-3">
                <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Plan document (optionnel)</p>
                <p class="text-sm text-gray-400">
                  Importez un fichier .txt ou .md, ou collez un plan structuré (# sujets, ## sous-sujets, puces).
                </p>
                <input
                  type="file"
                  accept=".txt,.md,text/plain,text/markdown"
                  class="block w-full text-sm text-gray-400 file:mr-3 file:rounded file:border-0 file:bg-brand-500/20 file:px-3 file:py-2 file:text-brand-100"
                  (change)="onProvidedPlanFile($event)"
                />
                <textarea
                  class="w-full min-h-28 rounded bg-black/30 border border-white/10 px-4 py-3 text-sm text-white font-mono"
                  [(ngModel)]="providedPlanText"
                  placeholder="# Sujet principal&#10;## Sous-sujet A&#10;- Point à clarifier"
                ></textarea>
                @if (selectedPlanMode === 'provided_plan' && !providedPlanText.trim()) {
                  <p class="text-xs text-amber-200/90">Un plan fourni est requis pour ce mode.</p>
                }
              </section>
            }

            <div class="flex items-center justify-between gap-3 pt-4">
              <button
                type="button"
                class="inline-flex items-center gap-2 px-4 py-2 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-300 ring-1 ring-white/10"
                (click)="goSurface('prep')"
              >
                <app-icon name="arrow-left" [size]="14" /> Retour
              </button>
              <button
                type="button"
                class="inline-flex items-center gap-2 px-5 py-2.5 rounded bg-brand-300 hover:bg-brand-200 text-sm font-semibold text-black disabled:opacity-50"
                [disabled]="loading() || !canCreateSelectedPlan()"
                (click)="createPlan()"
              >
                {{ loading() ? 'Préparation...' : planModeActionLabel() }}
                <app-icon name="arrow-right" [size]="14" />
              </button>
            </div>
          </section>
        }
      }

      @if (activeSurface() === 'plan_build') {
        @if (session(); as s) {
          <section class="grid xl:grid-cols-[minmax(0,1fr)_420px] gap-5">
            <div class="t-card rounded-lg p-5 space-y-4">
              <div>
                <p class="ck-mono text-[10px] uppercase tracking-[0.18em] text-gray-500">
                  {{ isProvidedPlanSession(s) ? 'Plan fourni' : 'Co-construction du plan' }}
                </p>
                <h2 class="mt-2 text-2xl text-white font-semibold">{{ s.title }}</h2>
                <p class="mt-2 text-sm text-gray-400">
                  @if (isProvidedPlanSession(s)) {
                    Ajustez l’arborescence importée, validez les sujets puis la banque de questions internes.
                  } @else {
                    Validez l’arborescence de sujets — les questions d’entretien restent internes.
                  }
                </p>
              </div>
              @if (planOracle(s); as oracle) {
                @if (oracle.contradiction_candidates?.length) {
                  <section class="rounded border border-amber-500/30 bg-amber-500/5 p-4 space-y-2">
                    <p class="ck-mono text-[10px] uppercase tracking-wider text-amber-300">Contradictions détectées</p>
                    @for (item of oracle.contradiction_candidates; track $index) {
                      <article class="text-sm text-gray-200 space-y-1">
                        <p><span class="text-amber-200">Expert :</span> {{ item.claim_expert }}</p>
                        <p><span class="text-gray-400">KB :</span> {{ item.claim_kb }}</p>
                      </article>
                    }
                  </section>
                }
                @if (oracle.coverage_gaps?.length) {
                  <section class="rounded border border-white/10 bg-black/20 p-4 space-y-2">
                    <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Manques Knowledge</p>
                    @for (gap of oracle.coverage_gaps; track gap.slug || gap.title || $index) {
                      <article class="text-sm text-gray-300">
                        <p class="font-medium text-gray-100">{{ gap.title }}</p>
                        @if (gap.description) {
                          <p class="text-xs text-gray-500 mt-0.5">{{ gap.description }}</p>
                        }
                      </article>
                    }
                  </section>
                }
              }
              <div class="space-y-3">
                @for (topic of planTopics(s); track topic.id) {
                  <section class="rounded border border-white/10 bg-white/[0.025] p-4 space-y-3">
                    <input
                      class="w-full rounded bg-black/20 border border-white/10 px-3 py-2 text-base font-semibold text-white"
                      [(ngModel)]="topic.title"
                      (ngModelChange)="touchPlanDraft()"
                    />
                    @if (planTopicRationale(topic); as rationale) {
                      <p class="text-xs text-gray-400 leading-relaxed">{{ rationale }}</p>
                    }
                    @if (topic.oracle_confidence != null) {
                      <p class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">
                        Confiance oracle {{ (topic.oracle_confidence * 100) | number:'1.0-0' }}%
                      </p>
                    }
                    @for (subtopic of topic.subtopics || []; track subtopic.id) {
                      <div class="rounded border border-white/10 bg-black/15 p-3 space-y-2">
                        <input
                          class="w-full rounded bg-black/20 border border-white/10 px-3 py-2 text-sm font-semibold text-gray-100"
                          [(ngModel)]="subtopic.title"
                          (ngModelChange)="touchPlanDraft()"
                        />
                        <textarea
                          class="w-full min-h-16 rounded bg-black/20 border border-white/10 px-3 py-2 text-xs text-gray-300"
                          [(ngModel)]="subtopic.objective"
                          (ngModelChange)="touchPlanDraft()"
                          placeholder="Objectif du sous-sujet..."
                        ></textarea>
                      </div>
                    }
                  </section>
                } @empty {
                  <div class="rounded border border-dashed border-white/10 bg-black/20 p-6 text-sm text-gray-500">
                    L’oracle proposera des sujets après vos premiers échanges de cadrage.
                  </div>
                }
              </div>
              <button
                type="button"
                class="inline-flex items-center gap-2 px-4 py-2 rounded bg-brand-500 hover:bg-brand-400 text-sm text-white disabled:opacity-40"
                [disabled]="!planTopics(s).length || planDialogueLoading()"
                (click)="validatePlanTopics(s)"
              >
                Valider les sujets
              </button>
            </div>
            <aside class="t-card rounded-lg p-5 space-y-4">
              <div>
                <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Assistant de cadrage</p>
                <p class="mt-2 text-sm text-gray-300 leading-relaxed">{{ planDialoguePrompt() || 'Décrivez le sujet pour commencer.' }}</p>
              </div>
              <div class="rounded border border-white/10 bg-black/20 p-4 space-y-3 max-h-52 overflow-auto">
                @for (turn of planDialogueTurns(s); track turn.id) {
                  <p class="text-sm text-gray-200">{{ turn.text }}</p>
                } @empty {
                  <p class="text-sm text-gray-500">Aucun échange pour l’instant.</p>
                }
              </div>
              <textarea
                class="w-full min-h-24 rounded bg-black/30 border border-white/10 px-4 py-3 text-sm text-white"
                [(ngModel)]="planDialogueAnswer"
                placeholder="Votre réponse..."
              ></textarea>
              <div class="flex flex-wrap gap-2">
                <button type="button" class="px-4 py-2 rounded bg-brand-500 hover:bg-brand-400 text-sm text-white" [disabled]="planDialogueLoading()" (click)="submitPlanDialogueTurn(s)">
                  Envoyer
                </button>
                <button type="button" class="px-4 py-2 rounded bg-white/5 text-sm text-gray-200" [disabled]="!planDialogueReady(s) || planDialogueLoading()" (click)="finalizePlanBuild(s)">
                  Préparer le plan
                </button>
                <button type="button" class="inline-flex items-center gap-2 px-4 py-2 rounded bg-white/5 text-sm text-gray-300" (click)="dictatePlanDialogue()">
                  <app-icon name="mic" [size]="14" /> Dictée
                </button>
              </div>
            </aside>
          </section>
        }
      }

      @if (activeSurface() === 'review') {
        <section class="grid xl:grid-cols-[1fr_320px] gap-5">
          <div class="t-card rounded-lg p-5 space-y-4">
            <div class="flex items-start justify-between gap-4">
              <div>
                <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Proposition Knowledge</p>
                <h2 class="text-lg font-semibold text-white">
                  {{ proposal()?.proposal?.title || session()?.title || 'Relire les changements avant ingestion' }}
                </h2>
                <p class="text-sm text-gray-500 mt-1 max-w-3xl">
                  La revue se fait au niveau des faits, avec une trace conversationnelle auditable en arrière-plan.
                </p>
              </div>
              @if (proposal(); as p) {
                <span class="text-xs px-2 py-1 rounded bg-white/5 text-gray-300 ring-1 ring-white/10">{{ workflowStatusLabel(p.status) }}</span>
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
                            <span class="text-xs text-amber-200">Corrigé par humain</span>
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
                              Enregistrer
                            </button>
                            <button type="button" class="px-3 py-1.5 rounded bg-white/5 hover:bg-white/10 text-xs text-gray-300" (click)="cancelProposalFactEdit()">
                              Annuler
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
                          Accepter
                        </button>
                        <button
                          type="button"
                          [class]="proposalFactDecision($index, fact) === 'reject'
                            ? 'px-2 py-1.5 rounded bg-red-500/20 text-xs text-red-100 ring-1 ring-red-400/30'
                            : 'px-2 py-1.5 rounded bg-white/5 hover:bg-white/10 text-xs text-gray-300 ring-1 ring-white/10'"
                          (click)="setProposalFactDecision($index, fact, 'reject')"
                        >
                          Rejeter
                        </button>
                        <button
                          type="button"
                          class="px-2 py-1.5 rounded bg-white/5 hover:bg-white/10 text-xs text-gray-300 ring-1 ring-white/10"
                          (click)="beginProposalFactEdit($index, fact)"
                        >
                          Modifier
                        </button>
                      </div>
                    </div>
                    @if (fact.retrieval_refs?.length) {
                      <div class="mt-3 rounded bg-white/[0.03] border border-white/10 p-3">
                        <div class="text-[10px] uppercase tracking-wider text-gray-500">Preuves</div>
                        @for (ref of (fact.retrieval_refs || []).slice(0, 2); track ref.title || ref.source || ref.preview) {
                          <p class="mt-2 text-xs text-gray-400 line-clamp-2">
                            <span class="text-gray-300">{{ ref.title || ref.source || 'Contexte retrouvé' }}</span>
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
                Aucun fait structuré pour l’instant. Capturez ou amendez au moins une réponse expert substantielle, puis créez la proposition.
              </div>
            }

            @if (proposal()?.proposal?.recommended_ingestion?.content) {
              <details class="rounded border border-white/10 bg-black/20 p-3">
                <summary class="cursor-pointer text-sm text-gray-300">Aperçu d’ingestion Markdown</summary>
                <pre class="mt-3 whitespace-pre-wrap text-xs text-gray-400 max-h-72 overflow-auto">{{ proposal()?.proposal?.recommended_ingestion?.content }}</pre>
              </details>
            }
            @if (closureSheetMarkdown()) {
              <details class="rounded border border-white/10 bg-black/20 p-3">
                <summary class="cursor-pointer text-sm text-gray-300">Fiche fin de session</summary>
                <pre class="mt-3 whitespace-pre-wrap text-xs text-gray-400 max-h-72 overflow-auto">{{ closureSheetMarkdown() }}</pre>
              </details>
            }
          </div>

          <aside class="t-card rounded-lg p-5 space-y-4">
            <div>
              <p class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Contrôles de revue</p>
              <h3 class="text-sm font-semibold text-white mt-1">Validation humaine</h3>
              @if (iamRoleBanner(); as banner) {
                <p class="mt-2 text-xs text-brand-100/80">{{ banner }}</p>
              }
            </div>
            <div class="grid grid-cols-2 gap-2 text-xs">
              <div class="rounded bg-black/20 border border-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500">Faits</div>
                <div class="text-xl text-white font-semibold">{{ proposalFacts().length }}</div>
              </div>
              <div class="rounded bg-black/20 border border-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500">Preuves</div>
                <div class="text-xl text-white font-semibold">{{ proposalEvidenceCount() }}</div>
              </div>
              <div class="rounded bg-black/20 border border-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500">Acceptés</div>
                <div class="text-xl text-white font-semibold">{{ acceptedProposalFactCount() }}</div>
              </div>
              <div class="rounded bg-black/20 border border-white/10 p-3">
                <div class="text-[10px] uppercase tracking-wider text-gray-500">Rejetés</div>
                <div class="text-xl text-white font-semibold">{{ rejectedProposalFactCount() }}</div>
              </div>
            </div>
            @if (proposalOpenQuestions().length) {
              <div class="rounded bg-amber-500/10 border border-amber-400/20 p-3">
                <div class="text-[10px] uppercase tracking-wider text-amber-200">Relances ouvertes</div>
                @for (item of proposalOpenQuestions(); track item.gap_id || item.follow_up || item.reason) {
                  <p class="mt-2 text-xs text-amber-100/80">{{ item.follow_up || item.reason }}</p>
                }
              </div>
            }
            <label class="block text-[10px] uppercase tracking-wider text-gray-500">Résumé exécutif</label>
            <textarea
              class="w-full min-h-20 rounded bg-black/30 border border-white/10 px-3 py-2 text-sm text-white"
              [(ngModel)]="executiveSummary"
              placeholder="Synthèse éditable avant publication..."
            ></textarea>
            @if (residualQualityCount() > 0) {
              <p class="text-xs text-amber-200/90">{{ residualQualityCount() }} point(s) de qualité encore ouverts</p>
            }
            @if (postSessionQualityItems().length) {
              <section class="rounded border border-amber-500/25 bg-amber-500/5 p-3 space-y-2">
                <p class="ck-mono text-[10px] uppercase tracking-wider text-amber-200">Points qualité</p>
                @for (item of postSessionQualityItems(); track item.id || item.label) {
                  <div class="text-xs text-gray-200 flex flex-wrap items-center justify-between gap-2">
                    <span>{{ item.label || item.follow_up }}</span>
                    @if (item.status === 'deferred') {
                      <span class="text-amber-200/80">reporté</span>
                    }
                  </div>
                }
                <button
                  type="button"
                  class="w-full mt-1 px-3 py-2 rounded bg-brand-500/20 text-xs text-brand-100 ring-1 ring-brand-300/30"
                  (click)="startClarificationSession()"
                >
                  Clarifier en nouvelle session
                </button>
              </section>
            }
            @if (proposal(); as p) {
              <button
                type="button"
                class="w-full inline-flex items-center justify-center gap-2 px-3 py-2 rounded bg-emerald-500/20 hover:bg-emerald-500/30 text-sm text-emerald-100 ring-1 ring-emerald-400/20 disabled:opacity-50"
                [disabled]="!proposalFacts().length || !canProposalReview(p)"
                [title]="proposalReviewHint(p)"
                (click)="acceptProposal(p.id)"
              >
                <app-icon name="check-circle-2" [size]="14" /> Valider la proposition
              </button>
              @if (proposalReviewHint(p); as hint) {
                <p class="text-[11px] leading-relaxed text-gray-500">{{ hint }}</p>
              }
              <button
                type="button"
                class="w-full inline-flex items-center justify-center gap-2 px-3 py-2 rounded bg-brand-500/20 text-sm text-brand-100 ring-1 ring-brand-300/30 disabled:opacity-50"
                [disabled]="p.status !== 'accepted' || !canProposalPublish(p)"
                [title]="proposalPublishHint(p)"
                (click)="publishToKnowledge(p.id)"
              >
                <app-icon name="upload" [size]="14" /> Publier dans Knowledge
              </button>
              @if (proposalPublishHint(p); as hint) {
                <p class="text-[11px] leading-relaxed text-gray-500">{{ hint }}</p>
              }
              <button type="button" class="w-full px-3 py-2 rounded bg-white/5 text-sm text-gray-200" (click)="exportProposalMd()">
                Exporter en Markdown
              </button>
              <button type="button" class="w-full px-3 py-2 rounded bg-white/5 text-sm text-gray-200" [disabled]="!session()" (click)="regenerateProposal()">
                Régénérer la proposition
              </button>
              <button
                type="button"
                class="w-full inline-flex items-center justify-center gap-2 px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-sm text-gray-200 ring-1 ring-white/10"
                (click)="goSurface('session')"
              >
                <app-icon name="message-square" [size]="14" /> Reprendre la capture
              </button>
            } @else if (session(); as s) {
              <button
                type="button"
                class="w-full inline-flex items-center justify-center gap-2 px-3 py-2 rounded bg-brand-500 hover:bg-brand-400 text-sm text-white disabled:opacity-50"
                [disabled]="!canProposalSubmit(s)"
                (click)="createProposal(s)"
              >
                <app-icon name="check-circle-2" [size]="14" /> Créer la proposition
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
  private readonly ttsPlaybackFactory = inject(VoiceTtsPlaybackService);
  private readonly workspace = inject(WorkspaceService);
  readonly permissions = inject(PermissionsService);
  readonly isDemoMode = computed(() => this.workspace.isDemoSafeMode());
  readonly isPilotMode = this.isDemoMode;
  readonly workspaceVoiceOutputConfig = computed(() => {
    const settings = this.asRecord(this.workspace.current()?.settings);
    const voiceOutput = this.asRecord(settings['voice_output']);
    return {
      latency_profile: 'fast',
      voice: 'nova',
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
  planDialogueAnswer = '';
  executiveSummary = '';
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
  readonly hintStack = signal<CaptureHint[]>([]);
  readonly activeSubtopicId = signal<string | null>(null);
  readonly questionBankStatus = signal<string>('idle');
  readonly qualityTabs = [
    { id: 'imprecisions' as QualityTab, label: 'Imprécisions' },
    { id: 'contradictions' as QualityTab, label: 'Contradictions' },
    { id: 'open_questions' as QualityTab, label: 'Questions' },
  ];
  readonly captureDomains = [
    { id: 'technical', label: 'Technique', description: 'Ingénierie, procédés, machines' },
    { id: 'commercial', label: 'Commercial', description: 'Marchés, comptes, affaires' },
    { id: 'innovation', label: 'Innovation', description: 'R&D, prototypes, exploration' },
  ];
  readonly visiblePlanModes = computed(() => {
    if (this.isDemoMode()) {
      return [
        {
          id: 'ai_plan' as CapturePlanMode,
          label: 'Agentium prépare une trame',
          description: 'L’assistant propose quelques sujets pour structurer l’échange avec l’expert.',
          icon: 'zap',
          recommended: true,
        },
        {
          id: 'free_conversation' as CapturePlanMode,
          label: 'Démarrer directement',
          description: 'L’expert parle librement, Agentium extrait les points importants au fil de l’échange.',
          icon: 'activity',
          recommended: false,
        },
      ];
    }
    const modes: Array<{
      id: CapturePlanMode;
      label: string;
      description: string;
      icon: string;
      recommended: boolean;
      disabled?: boolean;
    }> = [
      {
        id: 'free_conversation',
        label: 'Capture libre',
        description: 'Conversation directe, sans plan ni questions imposées.',
        icon: 'activity',
        recommended: true,
      },
      {
        id: 'plan_build',
        label: 'Construire un plan',
        description: 'Échanges de cadrage vocaux ou texte, upload optionnel, puis plan hiérarchique.',
        icon: 'layout-grid',
        recommended: false,
      },
      {
        id: 'provided_plan',
        label: 'Plan fourni',
        description: 'Collez ou importez un plan (.txt/.md) — arborescence sujets puis validation.',
        icon: 'file-text',
        recommended: false,
      },
      {
        id: 'ai_plan',
        label: 'L’IA propose un plan',
        description: 'Génère une trame d’entretien depuis le sujet, le profil expert et le contexte Knowledge.',
        icon: 'zap',
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
      label: 'Expert Knowledge Capture',
      description: 'La fonction métier : préserver le raisonnement expert et la connaissance tacite.',
    },
    {
      eyebrow: 'Système',
      label: 'Runtime de session guidée',
      description: 'Exécute un plan avec voix, évaluation et structuration.',
    },
    {
      eyebrow: 'Contexte',
      label: 'Périmètre Knowledge',
      description: 'Sélectionne collections, ACL et contraintes pour l’entretien.',
    },
    {
      eyebrow: 'Knowledge',
      label: 'Mise à jour relue',
      description: 'Reçoit les propositions validées après revue humaine.',
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
  readonly dashboardQualityRows = signal<
    Array<{ sessionId: string; sessionTitle: string; item: QualityBacklogItem }>
  >([]);
  readonly dashboardQualityBacklog = computed(() => this.dashboardQualityRows());
  readonly postSessionQualityItems = computed(() => {
    const backlog = this.qualityBacklog();
    const items = [
      ...backlog.imprecisions,
      ...backlog.contradictions,
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
  readonly closureSheetMarkdown = signal<string | null>(null);
  readonly closurePanelDismissed = signal(false);
  readonly closureActionLoading = signal(false);
  readonly sessionClockTick = signal(0);
  private sessionClockTimer: ReturnType<typeof setInterval> | null = null;
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
    { id: 'prep', label: 'Préparation', icon: 'sliders-horizontal', step: 2 },
    { id: 'plan', label: 'Plan', icon: 'list-checks', step: 3 },
    { id: 'session', label: 'Capture', icon: 'mic', step: 4 },
    { id: 'review', label: 'Proposition', icon: 'check-circle-2', step: 5 },
  ];

  surfaceNavLabel(item: { id: CaptureSurfaceView; label: string }): string {
    if (!this.isDemoMode()) return item.label;
    const labels: Partial<Record<CaptureSurfaceView, string>> = {
      dashboard: 'Sessions',
      prep: 'Sujet',
      plan: 'Trame',
      plan_build: 'Trame',
      session: 'Échange',
      review: 'Validation',
    };
    return labels[item.id] || item.label;
  }

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
  private readonly ttsPlayback = this.ttsPlaybackFactory.createController('knowledge_capture');
  private pendingVoiceFrameSends: Promise<void>[] = [];
  private revokedAudioUrls: string[] = [];
  private autoResumeTimer: ReturnType<typeof setTimeout> | null = null;
  private lastSuggestedContextName = '';

  ngOnInit(): void {
    this.destroyRef.onDestroy(() => {
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
    this.selectedPlanMode = this.isDemoMode() ? 'ai_plan' : 'free_conversation';
    this.providedPlanText = '';
    this.planDialogueAnswer = '';
    this.executiveSummary = '';
    this.conversationMode.set(this.isDemoMode() ? 'conversation_only' : 'manual');
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
    this.activeSurface.set('plan');
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
    this.hintStack.set([]);
    this.activeSubtopicId.set(null);
    this.questionBankStatus.set('idle');
    this.planNotice.set(null);
    this.planDialogueReadyFlag.set(false);
    this.planDialogueNextPrompt.set(null);
    this.lastConversationStep.set(null);
    this.retrieval.set({ status: 'idle', chunks: [], scores: [], metadatas: [] });
    this.currentClientTurnId = null;
    this.lastPrefetchText = '';
    this.lastPrefetchAt = 0;
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
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (session) => {
          const typed = session as CaptureSession;
          this.session.set(typed);
          this.zoom.setCurrentCapability(typed.capability_id || null, 'Expert Knowledge Capture');
          this.zoom.setCurrentSystem(typed.system_id || null, this.systemLabel(typed.system_id));
          this.zoom.setCurrentContext(typed.context_id || null, this.contextLabel(typed.context_id));
          this.selectedQuestionId.set(this.planQuestions(typed)[0]?.id || null);
          this.planNotice.set({
            tone: 'info',
            text: this.isFreeConversationSession(typed)
              ? 'Capture libre prête. Lancez la session quand l’expert est prêt.'
              : 'Plan prêt. Ajustez-le si nécessaire, puis démarrez la capture.',
          });
          this.refreshEvents(typed.id);
          this.refreshDashboard();
          if (this.isPlanBuildSession(typed)) {
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
      if (mode === 'free_conversation') {
        this.conversationMode.set('conversation_only');
      }
      if (mode === 'plan_build') {
        this.selectedPlanMode = 'plan_build';
      }
    }
  }

  canCreateSelectedPlan(): boolean {
    if (!this.canCaptureCreate() || !this.sessionTitle.trim()) return false;
    if (this.selectedPlanMode === 'provided_plan') {
      return this.providedPlanText.trim().length >= 12;
    }
    return true;
  }

  planModeActionLabel(): string {
    if (this.selectedPlanMode === 'free_conversation') return 'Créer la session';
    if (this.selectedPlanMode === 'ai_plan') return 'Générer le plan';
    if (this.selectedPlanMode === 'plan_build') return 'Co-construire le plan';
    if (this.selectedPlanMode === 'provided_plan') return 'Importer le plan';
    return 'Préparer la session';
  }

  canNavigateTo(view: CaptureSurfaceView): boolean {
    if (view === 'dashboard' || view === 'prep') return true;
    const current = this.session();
    if (view === 'plan') {
      if (!current) {
        return this.canCaptureCreate() && Boolean(this.sessionTitle.trim());
      }
      return !this.isFreeConversationSession(current) && !this.isPlanBuildSession(current);
    }
    if (view === 'plan_build') {
      return Boolean(current) && this.isPlanBuildSession(current!);
    }
    if (view === 'session') {
      if (!current) return false;
      if (this.isPlanBuildSession(current)) return false;
      return current.status === 'active' || current.status === 'paused' || this.stepIsComplete('plan');
    }
    if (view === 'review') {
      return Boolean(this.proposal()) || current?.status === 'completed';
    }
    return false;
  }

  goSurface(view: CaptureSurfaceView): void {
    if (!this.canNavigateTo(view)) return;
    this.activeSurface.set(view);
    if (view === 'dashboard') {
      this.refreshDashboard();
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
        conversationOnly = false;
        this.setVoiceNotice('Micro indisponible : la session démarre en saisie guidée, sans bloquer le parcours.', 'warning');
      }
    }
    this.api
      .startCaptureSession(session.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (payload) => {
          const typed = payload as CaptureSession;
          this.session.set(typed);
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
            this.ensureVoiceConnection(typed);
            const firstPrompt = this.currentPromptText();
            if (firstPrompt && !this.isFreeConversationSession(typed)) {
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
          for (const bucket of ['imprecisions', 'contradictions', 'open_questions'] as const) {
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
      this.activeSurface.set('review');
      return;
    }
    this.openDashboardSession(row);
  }

  refreshDashboard(): void {
    this.api
      .listCaptureSessions(undefined, this.dashboardDomainFilter || undefined, this.systemId || undefined)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((payload) => {
        const sessions = (payload as { sessions?: CaptureSession[] }).sessions || [];
        const scoped = this.systemId
          ? sessions.filter((row) => !row.system_id || row.system_id === this.systemId)
          : sessions;
        const rows = scoped.slice(0, 8);
        this.dashboardSessions.set(rows);
        this.refreshDashboardQualityRows(rows);
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
      this.editingProposalFactKey.set(null);
      this.proposalFactEditText = '';
    }
  }

  openDashboardSession(row: CaptureSession): void {
    this.session.set(row);
    this.closurePanelDismissed.set(false);
    this.syncClosureSheetFromSession(row);
    this.setProposal(null);
    this.selectedQuestionId.set(this.planQuestions(row)[0]?.id || null);
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

  workflowStatusLabel(status?: string | null): string {
    const normalized = String(status || '').toLowerCase();
    const labels: Record<string, string> = {
      planned: 'planifiée',
      active: 'active',
      paused: 'en pause',
      completed: 'terminée',
      pending_review: 'à relire',
      accepted: 'validée',
      rejected: 'rejetée',
      published: 'publiée',
      failed: 'en erreur',
    };
    return labels[normalized] || status || 'inconnu';
  }

  stepIsComplete(view: CaptureSurfaceView): boolean {
    const order: CaptureSurfaceView[] = ['dashboard', 'prep', 'plan', 'plan_build', 'session', 'review'];
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
    if (!this.proposalFacts().length) return 'Ajoutez au moins un fait capturé avant validation.';
    if (!this.canProposalReview(proposal)) return 'Votre rôle peut préparer la proposition, mais pas la valider.';
    if (this.proposalEvidenceCount() === 0) {
      return 'Aucune preuve documentaire attachée : validation possible, mais à traiter comme connaissance expert non sourcée.';
    }
    return null;
  }

  proposalPublishHint(proposal?: CaptureProposal | null): string | null {
    if (proposal?.status !== 'accepted') return 'Validez d’abord la proposition avant publication.';
    if (!this.canProposalPublish(proposal)) return 'La publication Knowledge requiert le droit d’ingestion.';
    return null;
  }

  isAuthor(session?: CaptureSession | null): boolean {
    return this.permissions.isAuthor({ owner_user_id: session?.created_by_user_id || null });
  }

  iamRoleBanner(): string | null {
    if (!this.permissions.matrix()) return null;
    if (this.permissions.isReviewerOrAdmin()) return `IAM : ${this.permissions.roleLabel()} peut relire les propositions du workspace.`;
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
            text: 'Knowledge collections could not be loaded.',
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
      return 'Sources par défaut du workspace';
    }
    return this.contexts().find((ctx) => ctx.id === contextId)?.name || contextId.slice(0, 8);
  }

  questionText(question?: CaptureQuestion | null): string {
    return this.promptText(question?.question || '');
  }

  currentPromptText(): string | null {
    const session = this.session();
    if (session && this.isFreeConversationSession(session)) {
      return 'Capture libre active. Parlez du sujet, corrigez ou complétez naturellement ; Agentium structurera les éléments utiles.';
    }
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
      idle: 'Prêt',
      listening: 'Écoute en cours',
      partial_transcribing: 'Transcription live',
      retrieving: 'Contexte en parallèle',
      oracle_updating: 'Analyse qualité',
      thinking: 'Évaluation',
      speaking: 'Lecture IA',
      interrupted: 'Interrompu',
    };
    return labels[this.voiceState()];
  }

  retrievalLabel(): string {
    const rr = this.retrieval();
    if (rr.chunks.length) return `${rr.chunks.length} repère(s) utile(s)`;
    if (rr.status === 'searching') {
      return 'Recherche en parallèle';
    }
    if (rr.status === 'ready' || rr.status === 'completed') return 'Aucun repère utile';
    if (rr.status === 'late') return 'Contexte arrivé tard';
    if (rr.status === 'timeout') return 'Timeout, on continue';
    if (rr.status === 'error') return 'Contexte indisponible';
    return 'En attente';
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
      return plan.topics.flatMap((topic) =>
        (topic.subtopics || []).flatMap((subtopic) =>
          (subtopic.questions || []).map((question) => ({
            ...question,
            topic_id: question.topic_id || topic.id,
            subtopic_id: question.subtopic_id || subtopic.id,
            path_label: question.path_label || `${topic.title} / ${subtopic.title}`,
          })),
        ),
      );
    }
    return plan.questions || [];
  }

  planTopics(session: CaptureSession): CaptureTopic[] {
    if (session.plan.topics?.length) return session.plan.topics;
    return [
      {
        id: 'topic-legacy',
        title: 'Interview questions',
        objective: 'Legacy flat plan',
        subtopics: [
          {
            id: 'topic-legacy-sub-01',
            title: 'Questions',
            questions: session.plan.questions || [],
          },
        ],
      },
    ];
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
      return (
        this.sessionHasStarted(session) ||
        this.planQuestions(session).length > 0 ||
        (session.plan.review?.status === 'topics_validated' &&
          (session.plan.question_bank_status === 'ready' || this.questionBankStatus() === 'ready'))
      );
    }
    return this.sessionHasStarted(session) || this.planQuestions(session).length > 0;
  }

  planBlockingReason(session: CaptureSession): string | null {
    if (this.canStartSessionPlan(session)) return null;
    if (!this.canCaptureExecute(session)) return 'Votre rôle ne permet pas de démarrer cette session.';
    if (this.isTopicOnlyPlan(session)) {
      if ((session.plan.question_bank_status || this.questionBankStatus()) === 'generating') {
        return 'La banque de questions est en génération. Le démarrage sera disponible dès qu’elle est prête.';
      }
      return 'Validez les sujets pour générer les questions avant de démarrer, ou choisissez une capture libre.';
    }
    return 'Ajoutez au moins une question exploitable avant de démarrer.';
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

  subtopicProgressLabel(session: CaptureSession, subtopic: CaptureSubtopic): string {
    const count = this.subtopicQuestionCount(subtopic);
    if (!count) return this.activeSubtopicId() === subtopic.id ? 'actif' : 'sujet';
    if (this.subtopicHasCurrentQuestion(session, subtopic)) return 'en cours';
    return `${count} relance(s)`;
  }

  questionBankStatusLabel(session: CaptureSession): string {
    const status = String(session.plan.question_bank_status || this.questionBankStatus());
    if (status === 'generating') return 'Préparation des angles d’exploration…';
    if (status === 'ready') return 'Banque prête';
    if ((session.plan.review?.status || '') === 'topics_validated') return 'Validation reçue — génération en cours';
    return 'En attente de validation des sujets';
  }

  topHint(): CaptureHint | null {
    const stack = this.hintStack();
    return stack.length ? stack[0] : null;
  }

  selectCaptureSubtopic(subtopicId: string): void {
    this.activeSubtopicId.set(subtopicId);
    const session = this.session();
    if (!session) return;
    const subtopic = this.planTopics(session)
      .flatMap((topic) => topic.subtopics || [])
      .find((item) => item.id === subtopicId);
    const firstQuestion = subtopic?.questions?.[0];
    if (firstQuestion) {
      this.selectedQuestionId.set(firstQuestion.id);
    }
    this.refreshHintQueue(session.id, subtopicId);
  }

  planDialogueTurns(session: CaptureSession): Array<{ id: string; text: string }> {
    const dialogue = (session.plan['dialogue'] as { turns?: Array<{ id: string; text: string }> }) || {};
    return dialogue.turns || [];
  }

  planOracle(session: CaptureSession): PlanOracleSnapshot | null {
    const oracle = session.plan.oracle;
    if (!oracle) return null;
    const hasGaps = (oracle.coverage_gaps?.length || 0) > 0;
    const hasContradictions = (oracle.contradiction_candidates?.length || 0) > 0;
    return hasGaps || hasContradictions ? oracle : null;
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
      'Quels grands sujets ou thèmes souhaitez-vous couvrir pendant cette capture ?',
      'Sur quelle ligne, client ou périmètre porte principalement cette session ?',
      'Quels cas concrets, exceptions terrain ou décisions difficiles sont prioritaires ?',
      'Y a-t-il des zones à valider plus tard ou des interlocuteurs à impliquer en revue ?',
    ];
    if (dialogue.ready_to_finalize) return 'Vous pouvez valider le plan quand il vous convient.';
    return prompts[Math.min(turns, prompts.length - 1)] || null;
  }

  planDialogueReady(session: CaptureSession): boolean {
    return this.planDialogueReadyFlag() || Boolean((session.plan['dialogue'] as { ready_to_finalize?: boolean })?.ready_to_finalize);
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
    const backlog = this.qualityBacklog();
    return backlog[tab] || [];
  }

  qualityBacklogCount(): number {
    const backlog = this.qualityBacklog();
    return backlog.imprecisions.length + backlog.contradictions.length + backlog.open_questions.length;
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
    const text = this.planDialogueAnswer.trim();
    if (!text) return;
    this.planDialogueLoading.set(true);
    this.api
      .planDialogueTurn(session.id, { text })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (payload) => {
          const body = payload as {
            session: CaptureSession;
            next_prompt?: string | null;
            ready_to_finalize?: boolean;
          };
          this.session.set(body.session);
          this.planDialogueAnswer = '';
          this.planDialogueNextPrompt.set(body.next_prompt || this.planDialoguePromptFor(body.session));
          this.planDialogueReadyFlag.set(Boolean(body.ready_to_finalize));
          this.planDialogueLoading.set(false);
          this.touchPlanDraft();
        },
        error: () => this.planDialogueLoading.set(false),
      });
  }

  validatePlanTopics(session: CaptureSession): void {
    this.planDialogueLoading.set(true);
    const topics = this.planTopics(session);
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
                this.questionBankStatus.set(String(typed.plan.question_bank_status || 'generating'));
                this.planDialogueLoading.set(false);
                this.planNotice.set({ tone: 'info', text: this.questionBankStatusLabel(typed) });
                this.pollQuestionBankStatus(session.id);
              },
              error: () => this.planDialogueLoading.set(false),
            });
        },
        error: () => this.planDialogueLoading.set(false),
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
    this.planDialogueLoading.set(true);
    this.api
      .finalizeCapturePlan(session.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          const typed = updated as CaptureSession;
          this.session.set(typed);
          this.questionBankStatus.set(String(typed.plan.question_bank_status || 'idle'));
          this.planDialogueLoading.set(false);
          this.activeSurface.set('plan');
          this.planNotice.set({ tone: 'success', text: 'Plan de sujets prêt — validez les sujets puis la banque de questions.' });
        },
        error: () => this.planDialogueLoading.set(false),
      });
  }

  onProvidedPlanFile(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      this.providedPlanText = String(reader.result || '').slice(0, 12000);
    };
    reader.readAsText(file);
  }

  async dictatePrepSubject(): Promise<void> {
    const armed = await this.ensureAudioStream();
    if (!armed) return;
    this.setVoiceNotice('Décrivez le sujet à la voix, puis arrêtez l’enregistrement.', 'info');
    await this.startRecordingTurn();
    this.recordingStopCallback = (text: string) => {
      if (text.trim()) this.objective = text.trim();
    };
  }

  async dictatePlanDialogue(): Promise<void> {
    const armed = await this.ensureAudioStream();
    if (!armed) return;
    await this.startRecordingTurn();
    this.recordingStopCallback = (text: string) => {
      if (text.trim()) this.planDialogueAnswer = text.trim();
    };
  }

  private recordingStopCallback: ((text: string) => void) | null = null;

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
    if (!this.canProposalPublish(this.proposal())) {
      this.setVoiceNotice('Publication Knowledge non autorisée pour ce rôle.', 'error');
      return;
    }
    this.api
      .publishCaptureProposal(proposalId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => this.setVoiceNotice('Publication dans Knowledge lancée.', 'info'),
        error: () => this.setVoiceNotice('Publication impossible pour le moment.', 'error'),
      });
  }

  exportProposalMd(): void {
    const session = this.session();
    if (!session) return;
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
          this.planNotice.set({ tone: 'success', text: 'Plan validé. La session guidée peut démarrer.' });
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

  sessionTimerView(session: CaptureSession): { label: string; blink: boolean; ended: boolean } | null {
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
      return { label: `${limitMinutes} min`, blink: false, ended: false };
    }
    const serverRemaining = Number(session.metrics?.['remaining_seconds'] ?? NaN);
    let remainingSeconds = Number.isFinite(serverRemaining) && serverRemaining >= 0 ? serverRemaining : NaN;
    if (session.status === 'active') {
      const startedAt = new Date(session.started_at).getTime();
      if (Number.isFinite(startedAt)) {
        const elapsedSeconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
        const computedRemaining = Math.max(0, limitMinutes * 60 - elapsedSeconds);
        const clearlyStaleStart = elapsedSeconds > limitMinutes * 60 + 30 && !session.metrics?.['session_end_pending'];
        if (!Number.isFinite(remainingSeconds) || (remainingSeconds <= 0 && !session.metrics?.['session_end_pending'])) {
          remainingSeconds = clearlyStaleStart ? limitMinutes * 60 : computedRemaining;
        }
      } else if (!Number.isFinite(remainingSeconds)) {
        remainingSeconds = limitMinutes * 60;
      }
    } else if (!Number.isFinite(remainingSeconds)) {
      remainingSeconds = limitMinutes * 60;
    }
    const minutes = Math.floor(remainingSeconds / 60);
    const seconds = remainingSeconds % 60;
    const ended = remainingSeconds <= 0;
    const blink = !ended && remainingSeconds <= 5 * 60;
    return {
      label: ended ? '0:00 · fin' : `${minutes}:${String(seconds).padStart(2, '0')} restantes`,
      blink,
      ended,
    };
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
              this.activeSurface.set('review');
            } else {
              this.activeSurface.set('dashboard');
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
    if (speaker === 'system') return `Agentium · ${this.transcriptEventShortLabel(event)}`;
    if (event.event_type === 'proposal_generated') return 'Proposition · générée';
    if (event.event_type === 'proposal_reviewed') return 'Revue · terminée';
    return `Trace · ${this.transcriptEventShortLabel(event)}`;
  }

  conversationStateHeadline(session: CaptureSession): string {
    if (!this.sessionHasStarted(session)) return 'Prêt à démarrer';
    if (this.speaking()) return 'Agentium pose la question';
    if (this.recording()) return 'Réponse expert en cours';
    if (this.transcribing()) return 'Traitement du tour';
    if (this.voiceState() === 'oracle_updating') return 'Analyse qualité en cours';
    if (this.voiceState() === 'thinking') return 'Évaluation de la réponse';
    if (this.proposal()) return 'Proposition prête';
    const step = this.lastConversationStep();
    if (step?.action_taken === 'proposal_deferred_insufficient_facts') return 'Détail expert nécessaire';
    return this.conversationMode() === 'conversation_only' ? 'Boucle conversationnelle prête' : 'Capture guidée prête';
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
        detail: this.speaking() ? 'lecture Agentium' : this.currentQuestion()?.id || 'question sélectionnée',
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
        label: 'Proposition',
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
    if (session.status === 'planned') return 'non démarrée';
    if (session.status === 'active') return 'active';
    if (session.status === 'paused') return 'en pause';
    if (session.status === 'completed') return 'terminée';
    return session.status;
  }

  planStartIcon(session?: CaptureSession): string {
    if (session && this.sessionHasStarted(session)) {
      return this.conversationMode() === 'conversation_only' ? 'message-circle' : 'arrow-right';
    }
    return this.conversationMode() === 'conversation_only' ? 'message-circle' : 'play';
  }

  planStartLabel(session?: CaptureSession): string {
    const prefix = session && this.sessionHasStarted(session) ? 'Reprendre' : 'Démarrer';
    return this.conversationMode() === 'conversation_only'
      ? `${prefix} la conversation`
      : `${prefix} la session`;
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
        ? 'Arrêter l’écoute'
        : this.speaking()
          ? 'Interrompre et répondre'
          : this.transcribing()
            ? 'Transcription...'
            : 'Écouter';
    }
    if (this.transcribing()) return 'Traitement...';
    if (this.recording()) return 'Finir le tour';
    if (this.speaking()) return 'Interrompre et répondre';
    return this.conversationSessionActive() ? 'Mettre en pause' : 'Démarrer';
  }

  emptyConversationHint(): string {
    if (this.conversationMode() === 'conversation_only') {
      return 'Démarrez la conversation. Si le micro est refusé, Agentium basculera en saisie guidée.';
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
      proposal_requested: 'Proposition préparée, en attente de confirmation',
      proposal_deferred_insufficient_facts: 'Détail expert nécessaire avant proposition',
      proposal_confirmed: 'Proposition confirmée, validation finale attendue',
      proposal_rejected: 'Proposition rejetée, correction attendue',
      accept_confirmed: 'Proposition acceptée',
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
    if (event.event_type === 'proposal_generated') return 'proposition générée';
    if (event.event_type === 'proposal_reviewed') return 'proposition relue';
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
    return (event.text || event.text_amended || event.text_raw || '').trim();
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
      proposal_requested: 'Demande vocale de proposition',
      proposal_confirmed: 'Proposition confirmée à la voix',
      proposal_rejected: 'Proposition rejetée à la voix',
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

  createProposal(session: CaptureSession): void {
    if (!this.canProposalSubmit(session)) {
      this.setVoiceNotice('Votre rôle ne permet pas de soumettre une proposition pour cette session.', 'error');
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
      this.setVoiceNotice('Votre rôle ne permet pas d’exécuter la boucle conversationnelle de cette session.', 'error');
      return;
    }
    this.voiceState.set('thinking');
    this.setVoiceNotice('Traitement de la transcription finale et détection de la prochaine action.', 'info');
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
      requires_confirmation: Boolean(step.requires_confirmation),
      confirmation_target: step.confirmation_target || null,
      closure_sheet: step.closure_sheet || null,
    };
    this.lastConversationStep.set(normalized);
    this.session.set(session);
    if (normalized.evaluation) {
      this.lastEvaluation.set(normalized.evaluation);
    }
    if (normalized.next_question_id) {
      this.selectedQuestionId.set(normalized.next_question_id);
    }
    if (normalized.proposal) {
      this.setProposal(normalized.proposal as CaptureProposal);
      if (normalized.intent === 'proposal_requested') {
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
      this.setVoiceNotice('Votre rôle ne permet pas de valider cette proposition.', 'error');
      return;
    }
    this.api
      .reviewCaptureProposal(proposalId, {
        status: 'accepted',
        reviewer: 'demo-operator',
        review_notes: 'Validé depuis la démo Knowledge Capture.',
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

  private ensureVoiceConnection(session: CaptureSession): VoiceSessionConnection | null {
    if (this.conversationMode() !== 'conversation_only') return null;
    if (this.voiceConnection) return this.voiceConnection;
    try {
      this.voiceConnection = this.voiceSession.open(session.id);
      this.voiceConnection.events$
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe((event) => this.handleVoiceSessionEvent(event));
      this.voiceConnection.start({
        runtime: session.voice_runtime || 'cascade_openai',
        provider: session.voice_runtime || 'cascade_openai',
        transport: 'backend_ws',
        capability: 'voice2voice_interaction',
        context_id: session.context_id || this.contextId || null,
        system_id: session.system_id || this.systemId || null,
        mode: 'conversation_only',
        codec: { input: 'webm', channels: 1 },
        tandem_oracle: true,
        oracle: { min_interval_ms: 300, min_delta_chars: 20 },
      });
      return this.voiceConnection;
    } catch {
      this.voiceConnection = null;
      this.setVoiceNotice('WebSocket vocal indisponible ; bascule sur les tours vocaux HTTP.', 'warning');
      return null;
    }
  }

  private closeVoiceConnection(): void {
    this.voiceConnection?.close();
    this.voiceConnection = null;
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
      return 'Runtime vocal';
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

  private handleVoiceSessionEvent(event: VoiceSessionEvent): void {
    const payload = event.payload || {};
    if (event.type === 'session.ready') {
      this.setVoiceNotice('Session vocale streaming prête.', 'info');
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
      this.setVoiceNotice('Transcription finalisée par la session vocale streaming.', 'info');
      return;
    }
    if (event.type === 'conversation.step') {
      this.applyConversationStepEvent(payload as Partial<ConversationStepResponse>);
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
    if (event.type === 'oracle.delta') {
      this.voiceState.set('oracle_updating');
      this.setVoiceNotice('Agentium prépare une action depuis la dernière transcription.', 'info');
      return;
    }
    if (event.type === 'oracle.superseded') {
      this.voiceState.set('oracle_updating');
      this.setVoiceNotice('Ancien signal remplacé par la dernière transcription.', 'info');
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
        if (hint.subtopic_id) this.activeSubtopicId.set(hint.subtopic_id);
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
      if (hint.subtopic_id) this.activeSubtopicId.set(hint.subtopic_id);
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
      if (metric === 'micro_turn') {
        this.voiceState.set('oracle_updating');
      }
      if (typeof metric === 'string' && typeof value === 'number') {
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
      this.transcribing.set(false);
      this.voiceState.set('idle');
      this.setVoiceNotice(String(payload['message'] || 'Session vocale streaming indisponible.'), 'error');
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
    this.startAudioRecorder('Micro ouvert. Arrêtez l’écoute quand la réponse expert est complète.');
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
    const connection = session ? this.ensureVoiceConnection(session) : null;
    this.conversationSessionActive.set(true);
    connection?.loopStart({
      surface: 'knowledge_capture',
      mode: 'conversation_loop',
      auto_rearm_after_tts: true,
      barge_in: true,
    });
    this.setVoiceNotice('Préparation du micro pour la conversation.', 'info');
    const armed = await this.ensureAudioStream();
    if (!armed) {
      this.conversationSessionActive.set(false);
      this.voiceState.set('idle');
      this.conversationMode.set('manual');
      this.setVoiceNotice('Micro indisponible : bascule en saisie guidée pour continuer la session.', 'warning');
      return;
    }
    const firstPrompt = this.currentPromptText();
    if (firstPrompt && !(session && this.isFreeConversationSession(session))) {
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
    const prompt = this.currentPromptText();
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
    if (this.isFreeConversationSession(session)) return 'Capture libre';
    const total = this.planQuestions(session).length;
    if (!total) return 'Sans plan';
    return `${this.currentQuestionPosition(session)}/${total}`;
  }

  planDurationMinutes(session: CaptureSession): number {
    const questions = this.planQuestions(session);
    return questions.reduce((total, question) => total + (question.estimated_minutes || 3), 0);
  }

  questionStateLabel(session: CaptureSession, question: CaptureQuestion): string {
    const questions = this.planQuestions(session);
    const selected = this.selectedQuestionId();
    const selectedIndex = questions.findIndex((item) => item.id === selected);
    const questionIndex = questions.findIndex((item) => item.id === question.id);
    if (question.id === selected) return 'en cours';
    if (selectedIndex >= 0 && questionIndex >= 0 && questionIndex < selectedIndex) return 'couverte';
    return 'à venir';
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

  voiceInputStatusLabel(): string {
    if (this.recording()) return 'Écoute de la réponse expert';
    if (this.transcribing()) return 'Finalisation de la transcription';
    if (this.speaking()) return 'Agentium parle';
    if (this.voiceState() === 'retrieving') return 'Recherche du contexte';
    if (this.voiceState() === 'oracle_updating') return 'Analyse qualité en cours';
    if (this.voiceState() === 'thinking') return 'Évaluation de la réponse';
    if (this.conversationMode() === 'conversation_only' && this.conversationSessionActive()) {
      return 'Conversation armée';
    }
    return this.conversationMode() === 'conversation_only' ? 'Prêt pour la conversation autonome' : 'Prêt pour la capture manuelle';
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
        this.setVoiceNotice('Agentium lit la relance. Vous pouvez interrompre et répondre à tout moment.', 'info');
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
    this.setVoiceNotice('Finalisation de la transcription vocale.', 'info');
    this.api
      .transcribeAudio(blob)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.answer = res.text;
          this.transcribing.set(false);
          this.voiceState.set('idle');
          if (this.recordingStopCallback) {
            this.recordingStopCallback(res.text);
            this.recordingStopCallback = null;
            this.setVoiceNotice('Transcription enregistrée.', 'info');
            return;
          }
          const session = this.session();
          if (session) {
            this.maybePrefetchRetrieval(session, res.text, true);
            if (this.conversationMode() === 'conversation_only') {
              this.runConversationStep(session, res.text);
            } else {
              this.setVoiceNotice('Transcription prête pour évaluation.', 'info');
            }
          }
        },
        error: () => {
          this.transcribing.set(false);
          this.voiceState.set('idle');
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
    this.setVoiceNotice('Finalisation de la transcription via la session vocale streaming.', 'info');
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
            hints: typed.hints || [],
            active_subtopic_id: typed.active_subtopic_id,
          });
          if (typed.hints?.length) {
            this.hintStack.update((current) => [...typed.hints!, ...current.filter((item) => !typed.hints!.some((h) => h.id === item.id))]);
          }
          if (typed.active_subtopic_id) this.activeSubtopicId.set(typed.active_subtopic_id);
          this.prefetchInFlight = false;
          this.refreshEvents(session.id);
          if (this.isTopicOnlyPlan(session)) this.refreshHintQueue(session.id, typed.active_subtopic_id || this.activeSubtopicId());
          if (this.recording()) {
            this.voiceState.set('listening');
          } else if (this.voiceState() === 'retrieving') {
            this.voiceState.set('idle');
          }
        },
        error: () => {
          this.retrieval.set({ status: 'error', chunks: [], scores: [], metadatas: [] });
          this.prefetchInFlight = false;
          if (this.recording()) {
            this.voiceState.set('listening');
          } else if (this.voiceState() === 'retrieving') {
            this.voiceState.set('idle');
          }
        },
      });
  }

  retrievalChunkTrack(index: number, chunk: string): string {
    return `${index}:${chunk.slice(0, 80)}`;
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

  private startAudioRecorder(openMessage: string): boolean {
    if (typeof MediaRecorder === 'undefined') {
      this.recorder = null;
      this.releaseAudioStream();
      this.setVoiceNotice('L’enregistrement audio est indisponible dans ce navigateur. Essayez un autre navigateur ou utilisez la saisie guidée.', 'error');
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
            .catch(() => this.setVoiceNotice('Une trame vocale n’a pas pu être envoyée ; le fallback HTTP peut être nécessaire.', 'warning'));
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
      this.setVoiceNotice('Démarrage de l’enregistrement impossible. Vérifiez le micro puis réessayez.', 'error');
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
      this.ensureVoiceConnection(session)?.loopArmed({ surface: 'knowledge_capture', mode: 'conversation_loop' });
    }
    if (!this.startAudioRecorder('Micro ouvert. Terminez le tour quand la réponse expert est complète.')) {
      this.conversationSessionActive.set(false);
      this.voiceState.set('idle');
    }
  }

  private stopConversationSession(): void {
    this.conversationSessionActive.set(false);
    this.clearAutoResumeTimer();
    this.voiceConnection?.loopStop({ surface: 'knowledge_capture', reason: 'user_stop' });
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
        this.voiceConnection?.loopArmed({ surface: 'knowledge_capture', mode: 'conversation_loop' });
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
