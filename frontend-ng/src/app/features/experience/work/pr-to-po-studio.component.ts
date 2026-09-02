import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { Subscription, of, timer } from 'rxjs';
import { catchError, switchMap, takeWhile } from 'rxjs/operators';
import { ApiService } from '@app/core/api.service';
import { CanonicalApiService, type Run, type System } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { ThinkingOrbComponent } from '@app/shared/cockpit';
import { ChatPanelComponent } from '@app/features/chat/chat-panel.component';
import { ExperienceRuntimeService } from '../runtime/experience-runtime.service';
import {
  FACTORY_BINDING_KEY,
  FACTORY_EXPERIENCE_SLUG,
  factoryRunHref,
  factoryRuntimeContext,
} from './pr-to-po-runtime';
import { WorkApiService } from './work-api.service';
import {
  BAPI_SERVER_ID,
  LIVE_BAPI_COMMIT,
  LIVE_BAPI_CREATE,
  LIVE_BAPI_ROLLBACK,
  LIVE_BUDGET,
  LIVE_DISCARD,
  LIVE_PO_HEADER,
  LIVE_PR_ITEM,
  LIVE_PR_ITEM_BY_KEY,
  STUDIO_CHAT_CHIPS,
  STUDIO_GUARDRAIL_TOOLS,
  STUDIO_NODE_KIND,
  chatWriteDialogueFromRun,
  formatStudioAmount,
  gateDecided,
  nextCandidates,
  openChatWriteDialogue,
  postOutcome,
  proposalFromRun,
  runDecision,
  runIsBusy,
  runIsSettled,
  studioFactSheet,
  studioJson,
  studioNodesFromRun,
  studioRunPayload,
  type ChatWriteDialogue,
  type StudioMode,
  type StudioNodeId,
  type StudioProposal,
} from './pr-to-po-studio';

interface RailServer {
  id: string;
  label: string;
  configured: boolean;
  enabled: boolean;
}

interface RailTool {
  server: string;
  name: string;
  write: boolean;
  toggle: boolean;
}

interface PostedRow {
  runId: string;
  po: string;
  pr: string;
  amount: string;
}

const STUDIO_POLL_MS = 1500;
/** ~4 minutes: SAP reads, an LLM summary and a BAPI commit fit comfortably. */
const STUDIO_MAX_POLLS = 160;

const RAIL_TOOLS: readonly RailTool[] = [
  { server: 'sap', name: LIVE_PR_ITEM, write: false, toggle: false },
  { server: 'sap', name: LIVE_BUDGET, write: false, toggle: false },
  { server: 'sap', name: LIVE_PR_ITEM_BY_KEY, write: false, toggle: false },
  { server: 'sap', name: LIVE_DISCARD, write: true, toggle: true },
  { server: 'hikma', name: LIVE_PO_HEADER, write: false, toggle: false },
  { server: BAPI_SERVER_ID, name: LIVE_BAPI_CREATE, write: true, toggle: true },
  { server: BAPI_SERVER_ID, name: LIVE_BAPI_COMMIT, write: true, toggle: true },
  { server: BAPI_SERVER_ID, name: LIVE_BAPI_ROLLBACK, write: true, toggle: false },
];

@Component({
  selector: 'app-pr-to-po-studio',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, RouterLink, ChatPanelComponent, ThinkingOrbComponent],
  styleUrl: './work.scss',
  template: `
    <div class="xp-work xp-studio" data-theme="dark" data-desk="nawa">
      <header class="xp-studio-bar">
        <div class="xp-studio-brand">
          <ck-thinking-orb [state]="busy() ? 'working' : 'listening'" [size]="20" />
          <div>
            <h1>{{ i18n.t('experience.pr_to_po.studio.title') }}</h1>
            <p>{{ i18n.t('experience.pr_to_po.studio.subtitle') }}</p>
          </div>
        </div>
        <nav class="xp-studio-modes" role="tablist">
          <button
            type="button"
            role="tab"
            [attr.aria-selected]="mode() === 'run'"
            [attr.data-active]="mode() === 'run'"
            (click)="setMode('run')"
          >
            {{ i18n.t('experience.pr_to_po.studio.mode.run') }}
          </button>
          <button
            type="button"
            role="tab"
            [attr.aria-selected]="mode() === 'chat'"
            [attr.data-active]="mode() === 'chat'"
            (click)="setMode('chat')"
          >
            {{ i18n.t('experience.pr_to_po.studio.mode.chat') }}
          </button>
        </nav>
        <div class="xp-studio-actions">
          <span class="xp-studio-badge" [attr.data-live]="writeUnsealed()">
            {{
              writeUnsealed()
                ? i18n.t('experience.pr_to_po.studio.badge.live')
                : i18n.t('experience.pr_to_po.studio.badge.sealed')
            }}
          </span>
          @if (run(); as current) {
            <a [routerLink]="runHref()" class="xp-work-btn xp-studio-run-link">
              {{ i18n.t('experience.pr_to_po.studio.open_run') }}
              <code>{{ current.id.slice(0, 8) }}</code>
            </a>
          }
        </div>
      </header>

      <div class="xp-studio-body">
        <main class="xp-studio-main">
          @if (error(); as err) {
            <p class="xp-work-error">{{ err }}</p>
          }

          @if (mode() === 'run') {
            <section class="xp-studio-hero">
              <div>
                <p class="xp-desk-kicker">{{ i18n.t('experience.pr_to_po.studio.hero.kicker') }}</p>
                <h2>{{ i18n.t('experience.pr_to_po.studio.hero.title') }}</h2>
                <p class="xp-desk-note">{{ i18n.t('experience.pr_to_po.studio.hero.hint') }}</p>
              </div>
              <button
                type="button"
                class="xp-work-btn xp-work-btn-primary xp-studio-run"
                (click)="runNow()"
                [disabled]="busy() || gateOpen()"
              >
                @if (busy()) {
                  <ck-thinking-orb state="working" [size]="20" />
                }
                {{
                  busy()
                    ? i18n.t('experience.pr_to_po.studio.running')
                    : i18n.t('experience.pr_to_po.studio.run_now')
                }}
              </button>
            </section>

            @if (posted().length) {
              <section class="xp-studio-result" data-live="true">
                <h3>{{ i18n.t('experience.pr_to_po.studio.result.title') }}</h3>
                <ul>
                  @for (result of posted(); track result.runId) {
                    <li>
                      <strong>{{ result.po }}</strong>
                      <span>{{ i18n.t('experience.pr_to_po.studio.result.row', { pr: result.pr, amount: result.amount }) }}</span>
                    </li>
                  }
                </ul>
              </section>
            }

            <ol class="xp-studio-nodes">
              @for (node of nodes(); track node.id; let i = $index) {
                <li [attr.data-status]="node.status" [attr.data-node]="node.id">
                  <button type="button" class="xp-studio-node-head" (click)="toggleNode(node.id)">
                    <span class="xp-studio-node-index">{{ i + 1 }}</span>
                    <span class="xp-studio-node-name">
                      <code>{{ i18n.t('experience.pr_to_po.studio.node.' + node.id) }}</code>
                      @if (node.noteKey) {
                        <em>{{ i18n.t(node.noteKey, node.noteParams) }}</em>
                      } @else if (node.error) {
                        <em>{{ node.error }}</em>
                      }
                    </span>
                    <span class="xp-studio-node-kind" [attr.data-kind]="nodeKind(node.id)">
                      {{ i18n.t('experience.pr_to_po.studio.kind.' + nodeKind(node.id)) }}
                    </span>
                    @if (node.status === 'running') {
                      <ck-thinking-orb state="searching" [size]="20" />
                    }
                    <span class="xp-studio-node-status">
                      {{ i18n.t('experience.pr_to_po.studio.status.' + node.status) }}
                    </span>
                  </button>
                  @if (expanded().has(node.id)) {
                    <div class="xp-studio-node-detail">
                      @if (node.calls.length === 0) {
                        <p class="xp-desk-note">{{ i18n.t('experience.pr_to_po.studio.no_calls') }}</p>
                      }
                      @for (call of node.calls; track $index) {
                        <details class="xp-studio-call" [attr.data-blocked]="call.blocked" [attr.data-sealed]="call.sealed">
                          <summary>
                            <code>{{ call.server }} · {{ call.tool }}</code>
                            <span [attr.data-kind]="call.write ? 'write' : 'read'">
                              {{ i18n.t(call.write ? 'experience.pr_to_po.studio.call.write' : 'experience.pr_to_po.studio.call.read') }}
                            </span>
                            @if (call.blocked) {
                              <b>{{ i18n.t('experience.pr_to_po.studio.call.blocked') }}</b>
                            } @else if (call.sealed && call.write) {
                              <b>{{ i18n.t('experience.pr_to_po.studio.call.sealed') }}</b>
                            } @else if (call.write) {
                              <b [attr.data-ok]="call.ok">
                                {{
                                  call.ok
                                    ? i18n.t('experience.pr_to_po.studio.call.live')
                                    : i18n.t('experience.pr_to_po.studio.call.failed')
                                }}
                              </b>
                            }
                            @if (call.durationMs) {
                              <small>{{ call.durationMs | number: '1.0-0' }} ms</small>
                            }
                          </summary>
                          <p>{{ i18n.t('experience.pr_to_po.studio.call.request') }}</p>
                          <pre>{{ json(call.request) }}</pre>
                          <p>{{ i18n.t('experience.pr_to_po.studio.call.response') }}</p>
                          <pre>{{ json(call.response) }}</pre>
                        </details>
                      }

                      @if (node.id === 'gate' && proposal(); as proposal) {
                        <div class="xp-studio-gate">
                          <article class="xp-studio-card" [attr.data-decision]="decision()">
                            <header>
                              <div>
                                <h4>{{ proposal.label }}</h4>
                                <p>
                                  {{ i18n.t('experience.pr_to_po.studio.gate.line', {
                                    pr: proposal.prId,
                                    item: proposal.item,
                                    plant: proposal.plant,
                                  }) }}
                                </p>
                              </div>
                              <strong>{{ amount(proposal) }}</strong>
                            </header>
                            @if (!proposal.budgetOk) {
                              <p class="xp-studio-warn">
                                {{ i18n.t('experience.pr_to_po.studio.gate.budget_ko', { reason: proposal.budgetReason }) }}
                              </p>
                            }
                            @if (proposal.priceMissing) {
                              <p class="xp-studio-warn">
                                {{ i18n.t('experience.pr_to_po.studio.gate.price_missing') }}
                              </p>
                            }
                            @if (proposal.justification) {
                              <p class="xp-studio-summary">{{ proposal.justification }}</p>
                            }
                            <dl>
                              <div>
                                <dt>{{ i18n.t('experience.pr_to_po.studio.gate.supplier') }}</dt>
                                <dd>{{ proposal.supplier || '—' }}</dd>
                              </div>
                              <div>
                                <dt>{{ i18n.t('experience.pr_to_po.studio.gate.payment') }}</dt>
                                <dd>{{ proposal.paymentTerms || '—' }}</dd>
                              </div>
                              <div>
                                <dt>{{ i18n.t('experience.pr_to_po.studio.gate.incoterms') }}</dt>
                                <dd>{{ proposal.incoterms || '—' }}</dd>
                              </div>
                              <div>
                                <dt>{{ i18n.t('experience.pr_to_po.studio.gate.type') }}</dt>
                                <dd>{{ proposal.format || 'ZLPO' }}</dd>
                              </div>
                            </dl>
                            <ul class="xp-studio-provenance">
                              @for (row of proposal.provenance; track row.field) {
                                <li>{{ i18n.t(row.sourceKey, row.sourceParams) }}</li>
                              }
                            </ul>
                            @if (proposal.dossier) {
                              <details>
                                <summary>{{ i18n.t('experience.pr_to_po.studio.gate.dossier') }}</summary>
                                <pre>{{ proposal.dossier }}</pre>
                              </details>
                            }
                            @if (outcome(); as outcome) {
                              <p class="xp-studio-outcome" [attr.data-ok]="outcome.sealed || outcome.sapOk">
                                @if (outcome.blocked) {
                                  {{ i18n.t('experience.pr_to_po.studio.outcome.blocked') }}
                                } @else if (outcome.sealed) {
                                  {{ i18n.t('experience.pr_to_po.studio.outcome.sealed') }}
                                } @else if (outcome.sapOk && outcome.poNumber) {
                                  {{ i18n.t('experience.pr_to_po.studio.outcome.po', { po: outcome.poNumber }) }}
                                } @else {
                                  {{ i18n.t('experience.pr_to_po.studio.outcome.failed') }}
                                  {{ outcome.messages[0] || '' }}
                                }
                              </p>
                            }
                            @if (gateOpen()) {
                              <div class="xp-work-hitl-actions">
                                <button
                                  type="button"
                                  class="xp-work-btn xp-work-btn-primary xp-studio-approve"
                                  (click)="approve()"
                                  [disabled]="deciding()"
                                >
                                  {{ i18n.t('experience.pr_to_po.studio.gate.approve') }}
                                </button>
                                <button
                                  type="button"
                                  class="xp-work-btn xp-studio-reject"
                                  (click)="reject()"
                                  [disabled]="deciding()"
                                >
                                  {{ i18n.t('experience.pr_to_po.studio.gate.reject') }}
                                </button>
                                @if (deciding()) {
                                  <ck-thinking-orb state="working" [size]="20" />
                                }
                              </div>
                            } @else if (decision() !== 'pending') {
                              <p class="xp-desk-note">
                                {{
                                  decision() === 'approved'
                                    ? i18n.t('experience.pr_to_po.studio.gate.approved')
                                    : i18n.t('experience.pr_to_po.studio.gate.rejected')
                                }}
                              </p>
                            }
                          </article>
                          @if (candidates().length && !busy()) {
                            <div class="xp-studio-next">
                              <p class="xp-desk-note">{{ i18n.t('experience.pr_to_po.studio.gate.next') }}</p>
                              @for (prId of candidates(); track prId) {
                                <button
                                  type="button"
                                  class="xp-work-btn xp-studio-next-btn"
                                  (click)="runNow(prId)"
                                  [disabled]="gateOpen()"
                                >
                                  {{ i18n.t('experience.pr_to_po.studio.gate.next_run', { pr: prId }) }}
                                </button>
                              }
                            </div>
                          }
                        </div>
                      }
                    </div>
                  }
                </li>
              }
            </ol>
          } @else {
            <section class="xp-studio-chat-wrap">
              <div class="xp-desk-chips xp-studio-chips">
                @for (chip of chatChips; track chip) {
                  <button
                    type="button"
                    class="xp-desk-chip"
                    [attr.data-write]="chip === 'create'"
                    (click)="askChip(chip)"
                  >
                    {{ i18n.t('experience.pr_to_po.studio.chip.' + chip) }}
                  </button>
                }
              </div>
              @if (chatDialogue(); as dialogue) {
                <section class="xp-studio-dialog" [attr.data-stage]="dialogue.stage">
                  <p class="xp-studio-dialog-user">
                    {{ i18n.t('experience.pr_to_po.studio.chat_write.ask', { pr: dialogue.proposal?.prId || '…' }) }}
                  </p>
                  <div class="xp-studio-dialog-row">
                  <span class="xp-studio-dialog-avatar" aria-hidden="true">
                    <ck-thinking-orb
                      [state]="dialogue.stage === 'posting' || dialogue.stage === 'preparing' ? 'working' : 'composing'"
                      [size]="20"
                    />
                  </span>
                  <div class="xp-studio-dialog-agent">
                    @if (dialogue.stage === 'preparing' || !dialogue.proposal) {
                      <p class="xp-studio-dialog-wait">
                        {{ i18n.t('experience.pr_to_po.studio.chat_write.preparing') }}
                      </p>
                    } @else {
                      <p>
                        {{
                          i18n.t('experience.pr_to_po.studio.chat_write.proposal', {
                            label: dialogue.proposal.label,
                            amount: amount(dialogue.proposal),
                            supplier: dialogue.proposal.supplier || '—',
                            plant: dialogue.proposal.plant,
                          })
                        }}
                      </p>
                      <ul class="xp-studio-provenance">
                        @for (row of dialogue.proposal.provenance; track row.field) {
                          <li>{{ i18n.t(row.sourceKey, row.sourceParams) }}</li>
                        }
                      </ul>
                      @if (dialogue.proposal.dossier) {
                        <details>
                          <summary>{{ i18n.t('experience.pr_to_po.studio.gate.dossier') }}</summary>
                          <pre>{{ dialogue.proposal.dossier }}</pre>
                        </details>
                      }
                    }
                    @if (dialogue.stage === 'proposing' || dialogue.stage === 'posting') {
                      <p class="xp-studio-dialog-confirm">
                        {{ i18n.t('experience.pr_to_po.studio.chat_write.confirm_q') }}
                      </p>
                      <div class="xp-studio-dialog-actions">
                        <button
                          type="button"
                          class="xp-work-btn xp-work-btn-primary xp-studio-dialog-yes"
                          (click)="confirmChatWrite()"
                          [disabled]="chatBusy() || dialogue.stage === 'posting'"
                        >
                          {{ i18n.t('experience.pr_to_po.studio.chat_write.confirm') }}
                        </button>
                        <button
                          type="button"
                          class="xp-work-btn xp-studio-dialog-no"
                          (click)="cancelChatWrite()"
                          [disabled]="chatBusy() || dialogue.stage === 'posting'"
                        >
                          {{ i18n.t('experience.pr_to_po.studio.chat_write.cancel') }}
                        </button>
                        @if (dialogue.stage === 'posting') {
                          <span class="xp-studio-dialog-wait">
                            <ck-thinking-orb state="working" [size]="20" />
                            {{ i18n.t('experience.pr_to_po.studio.chat_write.posting') }}
                          </span>
                        }
                      </div>
                    } @else if (dialogue.stage === 'posted') {
                      <p class="xp-studio-dialog-ok">
                        {{
                          i18n.t('experience.pr_to_po.studio.chat_write.posted', {
                            po: dialogue.outcome?.poNumber || '—',
                          })
                        }}
                      </p>
                    } @else if (dialogue.stage === 'blocked') {
                      <p class="xp-studio-dialog-blocked">
                        {{ i18n.t('experience.pr_to_po.studio.chat_write.blocked') }}
                      </p>
                    } @else if (dialogue.stage === 'sealed') {
                      <p class="xp-studio-dialog-sealed">
                        {{ i18n.t('experience.pr_to_po.studio.chat_write.sealed') }}
                      </p>
                    } @else if (dialogue.stage === 'cancelled') {
                      <p class="xp-studio-dialog-cancelled">
                        {{ i18n.t('experience.pr_to_po.studio.chat_write.cancelled') }}
                      </p>
                    } @else if (dialogue.stage === 'failed') {
                      <p class="xp-studio-dialog-err">
                        {{ i18n.t('experience.pr_to_po.studio.chat_write.failed') }}
                      </p>
                      @for (message of dialogue.outcome?.messages || []; track message) {
                        <p class="xp-studio-dialog-msg">{{ message }}</p>
                      }
                    }
                    @if (dialogue.calls.length) {
                      <details class="xp-studio-dialog-calls">
                        <summary>
                          {{
                            i18n.t('experience.pr_to_po.studio.chat_write.calls', {
                              count: dialogue.calls.length,
                            })
                          }}
                        </summary>
                        @for (call of dialogue.calls; track $index) {
                          <div class="xp-studio-call" [attr.data-blocked]="call.blocked">
                            <code>{{ call.server }} · {{ call.tool }}</code>
                            <pre>{{ json(call.response) }}</pre>
                          </div>
                        }
                      </details>
                    }
                  </div>
                  </div>
                </section>
              }
              @if (chatWriteError()) {
                <p class="xp-work-error xp-studio-dialog-error">{{ chatWriteError() }}</p>
              }
              @if (systemId(); as chatSystemId) {
                <section class="xp-desk-portal xp-studio-chat">
                  <header>
                    <div class="xp-desk-portal-head">
                      <ck-thinking-orb [state]="chatBusy() || busy() ? 'working' : 'composing'" [size]="20" />
                      <div>
                        <p class="xp-desk-kicker">{{ i18n.t('experience.pr_to_po.studio.chat.title') }}</p>
                        <p class="xp-desk-note">
                          {{
                            run()
                              ? i18n.t('experience.pr_to_po.studio.chat.hint')
                              : i18n.t('experience.pr_to_po.studio.chat.warming')
                          }}
                        </p>
                      </div>
                    </div>
                  </header>
                  @for (tick of [chatTick()]; track tick) {
                    <app-chat-panel
                      [systemId]="chatSystemId"
                      [initialPrompt]="chatPrompt()"
                      [systemPrompt]="chatSystemPrompt()"
                      [compact]="true"
                      [freshSession]="true"
                    />
                  }
                </section>
              } @else {
                <p class="xp-desk-note">{{ i18n.t('experience.pr_to_po.studio.chat.offline') }}</p>
              }
            </section>
          }
        </main>

        <aside class="xp-studio-rail">
          <h3>{{ i18n.t('experience.pr_to_po.studio.rail.title') }}</h3>
          <ul class="xp-studio-servers">
            @for (server of railServers(); track server.id) {
              <li [attr.data-configured]="server.configured && server.enabled">
                <i></i>
                <span>{{ server.label }}</span>
                <code>{{ server.id }}</code>
              </li>
            }
          </ul>
          <h3>{{ i18n.t('experience.pr_to_po.studio.rail.tools') }}</h3>
          <ul class="xp-studio-tools">
            @for (tool of railTools; track tool.name) {
              <li [attr.data-write]="tool.write" [attr.data-off]="isDisabled(tool.name)">
                <code>{{ tool.name }}</code>
                @if (tool.toggle) {
                  <button
                    type="button"
                    class="xp-studio-toggle"
                    role="switch"
                    [attr.aria-checked]="!isDisabled(tool.name)"
                    (click)="toggleTool(tool.name)"
                  >
                    <b></b>
                  </button>
                } @else {
                  <span>{{ i18n.t(tool.write ? 'experience.pr_to_po.studio.call.write' : 'experience.pr_to_po.studio.call.read') }}</span>
                }
              </li>
            }
          </ul>
          <p class="xp-desk-note">{{ i18n.t('experience.pr_to_po.studio.rail.hint') }}</p>
          <p class="xp-desk-note">
            {{
              writeUnsealed()
                ? i18n.t('experience.pr_to_po.studio.rail.live_note')
                : i18n.t('experience.pr_to_po.studio.rail.sealed_note')
            }}
          </p>
        </aside>
      </div>
    </div>
  `,
})
export class PrToPoStudioComponent implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly runtime = inject(ExperienceRuntimeService);
  private readonly workApi = inject(WorkApiService);
  readonly i18n = inject(I18nService);
  readonly workspace = inject(WorkspaceService);

  private readonly context = factoryRuntimeContext();
  private pollSub: Subscription | null = null;

  readonly mode = signal<StudioMode>('run');
  readonly launching = signal(false);
  readonly deciding = signal(false);
  readonly error = signal<string | null>(null);
  readonly run = signal<Run | null>(null);
  readonly posted = signal<PostedRow[]>([]);
  readonly expanded = signal<Set<StudioNodeId>>(new Set(['gate']));
  readonly disabledTools = signal<Set<string>>(new Set());
  readonly railServers = signal<RailServer[]>([]);
  readonly system = signal<System | null>(null);
  readonly systemId = computed(() => this.system()?.id ?? null);
  readonly chatTick = signal(0);
  readonly chatPrompt = signal('');
  readonly chatDialogue = signal<ChatWriteDialogue | null>(null);
  readonly chatBusy = signal(false);
  readonly chatWriteError = signal<string | null>(null);
  readonly railTools = RAIL_TOOLS;
  readonly chatChips = STUDIO_CHAT_CHIPS;
  readonly writeUnsealed = computed(() => this.workspace.sapWriteUnsealed());

  /** Everything below is a projection of the server Run — no local SAP state. */
  readonly nodes = computed(() => studioNodesFromRun(this.run()));
  readonly proposal = computed(() => proposalFromRun(this.run()));
  readonly decision = computed(() => runDecision(this.run()));
  readonly outcome = computed(() => postOutcome(this.run()));
  readonly gateOpen = computed(() => this.run()?.status === 'hitl_pending' && !gateDecided(this.run()));
  readonly busy = computed(() => this.launching() || runIsBusy(this.run()));
  readonly candidates = computed(() => nextCandidates(this.proposal()));
  readonly runHref = computed(() => (this.run() ? factoryRunHref(this.run()!.id) : '/work/pr-to-po'));
  readonly chatFacts = computed(() => studioFactSheet(this.run()));
  readonly chatSystemPrompt = computed(() =>
    this.i18n.t('experience.pr_to_po.studio.chat.system', { facts: this.chatFacts() || '—' }),
  );

  ngOnInit(): void {
    this.loadRail();
    this.loadSystem();
    this.loadPendingGate();
  }

  ngOnDestroy(): void {
    this.pollSub?.unsubscribe();
  }

  setMode(mode: StudioMode): void {
    this.mode.set(mode);
    if (mode === 'chat') {
      // The chat answers from a run's facts: warm one up (reads only, the
      // gate stays closed) so the first question lands on live SAP data.
      if (!this.run() && !this.busy()) this.runNow();
      if (!this.chatPrompt()) {
        this.chatPrompt.set(this.i18n.t('experience.pr_to_po.studio.chip_prompt.open_prs'));
      }
    }
  }

  json(value: unknown): string {
    return studioJson(value);
  }

  nodeKind(id: StudioNodeId): string {
    return STUDIO_NODE_KIND[id];
  }

  amount(proposal: StudioProposal): string {
    return formatStudioAmount(proposal.amount, proposal.currency);
  }

  toggleNode(id: StudioNodeId): void {
    this.expanded.update((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  isDisabled(tool: string): boolean {
    return this.disabledTools().has(tool);
  }

  toggleTool(tool: string): void {
    if (!STUDIO_GUARDRAIL_TOOLS.includes(tool)) return;
    this.disabledTools.update((current) => {
      const next = new Set(current);
      if (next.has(tool)) next.delete(tool);
      else next.add(tool);
      return next;
    });
  }

  /** Start one run of the published agent through the Experience binding. */
  runNow(prId = ''): void {
    if (this.busy()) return;
    if (!this.workspace.mcpConnectorEnabled()) {
      this.error.set(this.i18n.t('experience.pr_to_po.studio.error.offline'));
      return;
    }
    this.error.set(null);
    this.launching.set(true);
    this.run.set(null);
    this.runtime
      .invoke(this.context, FACTORY_BINDING_KEY, studioRunPayload(this.disabledTools(), prId))
      .subscribe((started) => {
        this.launching.set(false);
        if (!started?.id) {
          this.error.set(
            this.runtime.lastError(this.context.stateKey)
              || this.i18n.t('experience.pr_to_po.studio.error.run_failed'),
          );
          return;
        }
        this.follow(started.id);
      });
  }

  /** The gate answer is the canonical HITL decision — the server resumes the DAG. */
  approve(): void {
    this.decide('accept');
  }

  reject(): void {
    this.decide('reject');
  }

  askChip(chip: string): void {
    if (chip === 'create') {
      this.openChatWrite();
      return;
    }
    this.chatPrompt.set(this.i18n.t(`experience.pr_to_po.studio.chip_prompt.${chip}`));
    this.chatTick.update((tick) => tick + 1);
  }

  /** Fifth chip: the write dialogue opens inside the conversation. */
  openChatWrite(): void {
    if (this.chatBusy()) return;
    this.chatWriteError.set(null);
    const current = this.run();
    if (current && this.gateOpen()) {
      this.chatDialogue.set(openChatWriteDialogue(current.id, this.proposal()));
      return;
    }
    if (this.busy()) {
      this.chatDialogue.set(openChatWriteDialogue(current?.id ?? '', null));
      return;
    }
    // No package waiting: run the agent up to its gate, then propose.
    this.chatDialogue.set(openChatWriteDialogue('', null));
    this.runNow();
    const started = this.run();
    if (!started && !this.busy()) {
      this.chatDialogue.set(null);
      this.chatWriteError.set(this.i18n.t('experience.pr_to_po.studio.chat_write.unavailable'));
    }
  }

  /** The human said yes in the thread — same canonical decision as the run-flow gate. */
  confirmChatWrite(): void {
    const dialogue = this.chatDialogue();
    if (!dialogue || dialogue.stage !== 'proposing' || this.chatBusy()) return;
    this.chatDialogue.set({ ...dialogue, stage: 'posting' });
    this.decide('accept');
  }

  /** Cancel leaves the package at the gate — nothing is written, nothing discarded. */
  cancelChatWrite(): void {
    this.chatDialogue.update((dialogue) =>
      dialogue && dialogue.stage === 'proposing' ? { ...dialogue, stage: 'cancelled' } : dialogue,
    );
  }

  private decide(action: 'accept' | 'reject'): void {
    const current = this.run();
    if (!current || !this.gateOpen() || this.deciding()) return;
    this.deciding.set(true);
    this.chatBusy.set(true);
    this.workApi
      .decide(current.id, action, this.i18n.t(`experience.pr_to_po.studio.gate.note_${action}`))
      .subscribe((decided) => {
        this.deciding.set(false);
        this.chatBusy.set(false);
        if (!decided) {
          this.error.set(this.i18n.t('experience.pr_to_po.studio.error.decision_failed'));
          this.chatDialogue.update((dialogue) =>
            dialogue && dialogue.stage === 'posting' ? { ...dialogue, stage: 'proposing' } : dialogue,
          );
          return;
        }
        // The HITL endpoint answers with the pre-resume status; poll the walk.
        this.follow(current.id);
      });
  }

  /**
   * Poll the Run until it settles. A `hitl_pending` run whose Decision is
   * already accepted or rejected is resuming in the background, not settled —
   * the canonical HITL endpoint answers before the walker moves.
   */
  private follow(runId: string): void {
    this.pollSub?.unsubscribe();
    let polls = 0;
    this.pollSub = timer(0, STUDIO_POLL_MS)
      .pipe(
        switchMap(() => this.canonical.getRun(runId)),
        takeWhile((run) => {
          polls += 1;
          return polls < STUDIO_MAX_POLLS && !runIsSettled(run);
        }, true),
      )
      .subscribe((run) => {
        if (run) this.applyRun(run);
      });
  }

  private applyRun(run: Run): void {
    this.run.set(run);
    this.chatDialogue.update((dialogue) => (dialogue ? chatWriteDialogueFromRun(
      dialogue.runId ? dialogue : { ...dialogue, runId: run.id },
      run,
    ) : dialogue));
    if (run.status === 'failed') {
      this.error.set(run.error || this.i18n.t('experience.pr_to_po.studio.error.run_failed'));
    }
    const outcome = postOutcome(run);
    const proposal = proposalFromRun(run);
    if (run.status === 'completed' && outcome?.sapOk && outcome.poNumber && proposal) {
      this.posted.update((rows) =>
        rows.some((row) => row.runId === run.id)
          ? rows
          : [
              ...rows,
              {
                runId: run.id,
                po: outcome.poNumber,
                pr: proposal.prId,
                amount: formatStudioAmount(proposal.amount, proposal.currency),
              },
            ],
      );
    }
    if (run.status === 'hitl_pending') {
      this.expanded.update((current) => new Set([...current, 'gate']));
    }
  }

  /** A gate left open earlier (another tab, a scheduled tick) is the current run. */
  private loadPendingGate(): void {
    this.workApi.listPendingValidations(FACTORY_EXPERIENCE_SLUG).subscribe((result) => {
      if (result.kind !== 'ok' || !result.items.length || this.run()) return;
      const pending = result.items.find((row) => row.status === 'hitl_pending');
      if (pending) this.follow(pending.id);
    });
  }

  private loadRail(): void {
    if (!this.workspace.mcpConnectorEnabled()) return;
    this.api
      .get<{ servers?: Array<{ id?: string; label?: string; configured?: boolean; enabled?: boolean }> }>(
        '/mcp/servers',
      )
      .pipe(catchError(() => of({ servers: [] })))
      .subscribe((body) => {
        this.railServers.set(
          (body.servers || []).map((row) => ({
            id: String(row.id || ''),
            label: String(row.label || row.id || ''),
            configured: row.configured !== false,
            enabled: row.enabled !== false,
          })),
        );
      });
  }

  private loadSystem(): void {
    this.api
      .get<{ system_id?: string }>(`/system-bindings/${encodeURIComponent(FACTORY_BINDING_KEY)}`)
      .pipe(
        switchMap((row) => (row.system_id ? this.canonical.getSystem(row.system_id) : of(null))),
        catchError(() => of(null)),
      )
      .subscribe((system) => this.system.set(system));
  }
}
