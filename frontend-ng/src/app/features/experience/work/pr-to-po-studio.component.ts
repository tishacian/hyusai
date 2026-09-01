import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { firstValueFrom, of } from 'rxjs';
import { catchError, switchMap } from 'rxjs/operators';
import { ApiService } from '@app/core/api.service';
import { CanonicalApiService, type System } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { ThinkingOrbComponent } from '@app/shared/cockpit';
import { ChatPanelComponent } from '@app/features/chat/chat-panel.component';
import {
  BAPI_SERVER_ID,
  LIVE_BAPI_COMMIT,
  LIVE_BAPI_CREATE,
  LIVE_BAPI_ROLLBACK,
  LIVE_BUDGET,
  LIVE_PO_HEADER,
  LIVE_PR_ITEM,
  LIVE_PR_ITEM_BY_KEY,
  approvedPrItemReadBody,
  budgetOkFromRead,
  budgetReadBody,
  extractJustificationText,
  justificationReadBody,
  recentPoTermsFromPreview,
  recentPosByPlantReadBody,
  uniquePurchaseOrders,
  type DeskKeyedRead,
  type DeskPreview,
  type DeskPrItemFields,
  type RecentPoTerms,
} from './pr-to-po-desk';
import { FACTORY_BINDING_KEY } from './pr-to-po-runtime';
import {
  STUDIO_CHAT_CHIPS,
  STUDIO_GUARDRAIL_TOOLS,
  STUDIO_NODE_KIND,
  STUDIO_WRITE_SERVERS,
  bapiCommitInvokeBody,
  bapiCreateInvokeBody,
  blockedCall,
  buildStudioProposal,
  discardInvokeBody,
  formatStudioAmount,
  guardrailBlocked,
  initialStudioNodes,
  openPrRowsFromPreview,
  outcomeFromInvoke,
  proposalsTotal,
  readCall,
  studioCallFromInvoke,
  studioJson,
  studioPlants,
  type StudioCall,
  type StudioMode,
  type StudioNodeId,
  type StudioNodeState,
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

const RAIL_TOOLS: readonly RailTool[] = [
  { server: 'sap', name: LIVE_PR_ITEM, write: false, toggle: false },
  { server: 'sap', name: LIVE_BUDGET, write: false, toggle: false },
  { server: 'sap', name: LIVE_PR_ITEM_BY_KEY, write: false, toggle: false },
  { server: 'sap', name: 'fi_DiscardFromPurchasing', write: true, toggle: true },
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
          <ck-thinking-orb [state]="running() ? 'working' : 'listening'" [size]="20" />
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
          <a routerLink="/work/pr-to-po/desk" class="xp-work-btn">
            {{ i18n.t('experience.pr_to_po.studio.open_desk') }}
          </a>
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
                [disabled]="running()"
              >
                @if (running()) {
                  <ck-thinking-orb state="working" [size]="20" />
                }
                {{
                  running()
                    ? i18n.t('experience.pr_to_po.studio.running')
                    : i18n.t('experience.pr_to_po.studio.run_now')
                }}
              </button>
            </section>

            @if (postedPoNumbers().length) {
              <section class="xp-studio-result" data-live="true">
                <h3>{{ i18n.t('experience.pr_to_po.studio.result.title') }}</h3>
                <ul>
                  @for (result of postedResults(); track result.po) {
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
                          </summary>
                          <p>{{ i18n.t('experience.pr_to_po.studio.call.request') }}</p>
                          <pre>{{ json(call.request) }}</pre>
                          <p>{{ i18n.t('experience.pr_to_po.studio.call.response') }}</p>
                          <pre>{{ json(call.response) }}</pre>
                        </details>
                      }

                      @if (node.id === 'gate' && proposals().length) {
                        <div class="xp-studio-gate">
                          @for (proposal of proposals(); track proposal.prId) {
                            <article class="xp-studio-card" [attr.data-decision]="proposal.decision">
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
                              @if (proposal.budgetWarning) {
                                <p class="xp-studio-warn">{{ proposal.budgetWarning }}</p>
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
                              </dl>
                              <ul class="xp-studio-provenance">
                                @for (row of proposal.provenance; track row.field) {
                                  <li>{{ i18n.t(row.sourceKey, row.sourceParams) }}</li>
                                }
                              </ul>
                              @if (proposal.post) {
                                <details>
                                  <summary>{{ i18n.t('experience.pr_to_po.studio.gate.payload') }}</summary>
                                  <pre>{{ json(proposal.post.requestBody) }}</pre>
                                </details>
                              }
                              @if (proposal.outcome; as outcome) {
                                <p class="xp-studio-outcome" [attr.data-ok]="outcome.sealed || outcome.sapOk">
                                  @if (outcome.sealed) {
                                    {{ i18n.t('experience.pr_to_po.studio.outcome.sealed') }}
                                  } @else if (outcome.sapOk && outcome.poNumber) {
                                    {{ i18n.t('experience.pr_to_po.studio.outcome.po', { po: outcome.poNumber }) }}
                                  } @else {
                                    {{ i18n.t('experience.pr_to_po.studio.outcome.failed') }}
                                    {{ outcome.messages[0] || '' }}
                                  }
                                </p>
                              }
                              @if (proposal.decision === 'pending') {
                                <div class="xp-work-hitl-actions">
                                  <button
                                    type="button"
                                    class="xp-work-btn xp-work-btn-primary"
                                    (click)="approve(proposal)"
                                    [disabled]="deciding()"
                                  >
                                    {{ i18n.t('experience.pr_to_po.studio.gate.approve') }}
                                  </button>
                                  <button
                                    type="button"
                                    class="xp-work-btn"
                                    (click)="rejectProposal(proposal)"
                                    [disabled]="deciding()"
                                  >
                                    {{ i18n.t('experience.pr_to_po.studio.gate.reject') }}
                                  </button>
                                </div>
                              } @else {
                                <p class="xp-desk-note">
                                  {{
                                    proposal.decision === 'approved'
                                      ? i18n.t('experience.pr_to_po.studio.gate.approved')
                                      : i18n.t('experience.pr_to_po.studio.gate.rejected')
                                  }}
                                </p>
                              }
                            </article>
                          }
                          @if (pendingCount() > 1) {
                            <button
                              type="button"
                              class="xp-work-btn xp-work-btn-primary xp-studio-approve-all"
                              (click)="approveAll()"
                              [disabled]="deciding()"
                            >
                              {{ i18n.t('experience.pr_to_po.studio.gate.approve_all', { count: pendingCount() }) }}
                            </button>
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
                  <button type="button" class="xp-desk-chip" (click)="askChip(chip)">
                    {{ i18n.t('experience.pr_to_po.studio.chip.' + chip) }}
                  </button>
                }
              </div>
              @if (systemId(); as chatSystemId) {
                <section class="xp-desk-portal xp-studio-chat">
                  @for (tick of [chatTick()]; track tick) {
                    <app-chat-panel
                      [systemId]="chatSystemId"
                      [initialPrompt]="chatPrompt()"
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
export class PrToPoStudioComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly canonical = inject(CanonicalApiService);
  readonly i18n = inject(I18nService);
  readonly workspace = inject(WorkspaceService);

  readonly mode = signal<StudioMode>('run');
  readonly running = signal(false);
  readonly deciding = signal(false);
  readonly error = signal<string | null>(null);
  readonly nodes = signal<StudioNodeState[]>(initialStudioNodes());
  readonly proposals = signal<StudioProposal[]>([]);
  readonly expanded = signal<Set<StudioNodeId>>(new Set(['gate']));
  readonly disabledTools = signal<Set<string>>(new Set());
  readonly railServers = signal<RailServer[]>([]);
  readonly system = signal<System | null>(null);
  readonly systemId = computed(() => this.system()?.id ?? null);
  readonly chatTick = signal(0);
  readonly chatPrompt = signal('');
  readonly railTools = RAIL_TOOLS;
  readonly chatChips = STUDIO_CHAT_CHIPS;
  readonly writeUnsealed = computed(() => this.workspace.sapWriteUnsealed());
  readonly pendingCount = computed(
    () => this.proposals().filter((row) => row.decision === 'pending').length,
  );
  readonly postedPoNumbers = computed(() =>
    this.proposals()
      .map((row) => row.outcome?.poNumber || '')
      .filter(Boolean),
  );
  readonly postedResults = computed(() =>
    this.proposals()
      .filter((row) => row.outcome?.poNumber)
      .map((row) => ({
        po: row.outcome!.poNumber,
        pr: row.prId,
        amount: formatStudioAmount(row.amount, row.currency),
      })),
  );

  private terms = new Map<string, { terms: RecentPoTerms; recentPo: string }>();
  private candidates: DeskPrItemFields[] = [];
  private budgetNotes = new Map<string, { ok: boolean; reason: string; warning: string }>();

  ngOnInit(): void {
    this.loadRail();
    this.loadSystem();
  }

  setMode(mode: StudioMode): void {
    this.mode.set(mode);
    if (mode === 'chat' && !this.chatPrompt()) {
      this.chatPrompt.set(this.composeChatPrompt(''));
      this.chatTick.update((tick) => tick + 1);
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

  askChip(chip: string): void {
    this.chatPrompt.set(
      this.composeChatPrompt(this.i18n.t(`experience.pr_to_po.studio.chip_prompt.${chip}`)),
    );
    this.chatTick.update((tick) => tick + 1);
  }

  private composeChatPrompt(question: string): string {
    return this.i18n.t('experience.pr_to_po.studio.chat.prompt', {
      question:
        question.trim() || this.i18n.t('experience.pr_to_po.studio.chip_prompt.open_prs'),
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

  private patchNode(id: StudioNodeId, patch: Partial<StudioNodeState>): void {
    this.nodes.update((rows) =>
      rows.map((row) => (row.id === id ? { ...row, ...patch } : row)),
    );
  }

  private appendCall(id: StudioNodeId, call: StudioCall): void {
    this.nodes.update((rows) =>
      rows.map((row) => (row.id === id ? { ...row, calls: [...row.calls, call] } : row)),
    );
  }

  private async read<T>(serverId: string, body: { tool: string }, node: StudioNodeId): Promise<T | null> {
    try {
      const result = await firstValueFrom(
        this.api.post<T>(`/mcp/servers/${encodeURIComponent(serverId)}/read`, body),
      );
      this.appendCall(node, readCall(serverId, body.tool, body, result));
      return result;
    } catch (err) {
      this.appendCall(node, readCall(serverId, body.tool, body, this.errorBody(err), false));
      return null;
    }
  }

  /** One allow-listed write. The guardrail blocks before the network. */
  private async invokeWrite(
    body: { tool: string; arguments: Record<string, unknown> },
    node: StudioNodeId,
  ): Promise<StudioCall> {
    const serverId = STUDIO_WRITE_SERVERS[body.tool] || BAPI_SERVER_ID;
    if (guardrailBlocked(body.tool, this.disabledTools())) {
      const call = blockedCall(serverId, body.tool, body);
      this.appendCall(node, call);
      return call;
    }
    try {
      const result = await firstValueFrom(
        this.api.post<unknown>(`/mcp/servers/${encodeURIComponent(serverId)}/invoke`, body),
      );
      const call = studioCallFromInvoke(serverId, body.tool, body, result);
      this.appendCall(node, call);
      return call;
    } catch (err) {
      const call: StudioCall = {
        server: serverId,
        tool: body.tool,
        request: body,
        response: this.errorBody(err),
        ok: false,
        write: true,
        blocked: false,
        sealed: false,
        durationMs: 0,
      };
      this.appendCall(node, call);
      return call;
    }
  }

  private errorBody(err: unknown): unknown {
    const detail = (err as { error?: { detail?: unknown } })?.error?.detail;
    return { ok: false, detail: typeof detail === 'string' ? detail : String(err) };
  }

  async runNow(): Promise<void> {
    if (!this.workspace.mcpConnectorEnabled()) {
      this.error.set(this.i18n.t('experience.pr_to_po.studio.error.offline'));
      return;
    }
    this.error.set(null);
    this.running.set(true);
    this.nodes.set(initialStudioNodes());
    this.proposals.set([]);
    this.candidates = [];
    this.terms.clear();
    this.budgetNotes.clear();
    try {
      await this.stepRequisitions();
      await this.stepBudget();
      await this.stepAutoDiscard();
      await this.stepSummarise();
      await this.stepHistory();
      this.stepDerive();
      this.stepProposals();
    } catch {
      this.error.set(this.i18n.t('experience.pr_to_po.studio.error.run_failed'));
    } finally {
      this.running.set(false);
    }
  }

  private async stepRequisitions(): Promise<void> {
    this.patchNode('requisitions', { status: 'running' });
    const body = approvedPrItemReadBody();
    const preview = await this.read<DeskPreview>('sap', body, 'requisitions');
    if (!preview || preview.ok === false) {
      this.patchNode('requisitions', { status: 'error' });
      throw new Error('requisitions read failed');
    }
    this.candidates = openPrRowsFromPreview(preview);
    this.patchNode('requisitions', {
      status: 'done',
      noteKey: 'experience.pr_to_po.studio.note.requisitions',
      noteParams: { shown: this.candidates.length, total: preview.row_count || 0 },
    });
  }

  private async stepBudget(): Promise<void> {
    this.patchNode('budget', { status: 'running' });
    let pass = 0;
    let fail = 0;
    for (const fields of this.candidates) {
      const body = budgetReadBody(fields.pr_id);
      const result = await this.read<DeskKeyedRead>('sap', body, 'budget');
      const verdict = budgetOkFromRead(result);
      const warning =
        verdict.ok && verdict.reason !== 'ok' ? verdict.reason : '';
      this.budgetNotes.set(fields.pr_id, { ok: verdict.ok, reason: verdict.reason, warning });
      if (verdict.ok) pass += 1;
      else fail += 1;
    }
    this.patchNode('budget', {
      status: fail ? 'warn' : 'done',
      noteKey: 'experience.pr_to_po.studio.note.budget',
      noteParams: { pass, fail },
    });
  }

  /** The only write the agent makes without asking — and only on a hard E. */
  private async stepAutoDiscard(): Promise<void> {
    const rejected = this.candidates.filter(
      (fields) => this.budgetNotes.get(fields.pr_id)?.ok === false,
    );
    if (!rejected.length) {
      this.patchNode('discard', {
        status: 'skipped',
        noteKey: 'experience.pr_to_po.studio.note.discard_skipped',
        noteParams: {},
      });
      return;
    }
    this.patchNode('discard', { status: 'running' });
    let sealed = false;
    for (const fields of rejected) {
      const call = await this.invokeWrite(discardInvokeBody(fields.pr_id, fields.item), 'discard');
      sealed = sealed || call.sealed;
    }
    this.candidates = this.candidates.filter(
      (fields) => this.budgetNotes.get(fields.pr_id)?.ok !== false,
    );
    this.patchNode('discard', {
      status: 'done',
      noteKey: sealed
        ? 'experience.pr_to_po.studio.note.discard_sealed'
        : 'experience.pr_to_po.studio.note.discard_done',
      noteParams: { count: rejected.length },
    });
  }

  private async stepSummarise(): Promise<void> {
    this.patchNode('summarise', { status: 'running' });
    const first = this.candidates[0];
    if (!first) {
      this.patchNode('summarise', { status: 'skipped', noteKey: '', noteParams: {} });
      return;
    }
    const body = justificationReadBody(first.pr_id, first.item);
    const result = await this.read<DeskKeyedRead>('sap', body, 'summarise');
    const text = (result?.text || extractJustificationText(result?.result) || '').trim();
    this.patchNode('summarise', {
      status: text ? 'done' : 'warn',
      noteKey: text
        ? 'experience.pr_to_po.studio.note.summarise'
        : 'experience.pr_to_po.studio.note.summarise_empty',
      noteParams: { pr: first.pr_id },
    });
  }

  private async stepHistory(): Promise<void> {
    this.patchNode('history', { status: 'running' });
    const plants = studioPlants(this.candidates);
    for (const plant of plants) {
      const body = recentPosByPlantReadBody(plant);
      const preview = await this.read<DeskPreview>('hikma', body, 'history');
      if (preview && preview.ok !== false) {
        this.terms.set(plant, {
          terms: recentPoTermsFromPreview(preview),
          recentPo: uniquePurchaseOrders(preview, 1)[0] || '',
        });
      }
    }
    this.patchNode('history', {
      status: this.terms.size ? 'done' : 'warn',
      noteKey: 'experience.pr_to_po.studio.note.history',
      noteParams: { plants: plants.join(', ') },
    });
  }

  private stepDerive(): void {
    const notes = [...this.terms.entries()]
      .map(([plant, row]) => `${plant} → ${row.terms.supplier || '—'}`)
      .join(' · ');
    this.patchNode('derive', {
      status: this.terms.size ? 'done' : 'warn',
      noteKey: 'experience.pr_to_po.studio.note.derive',
      noteParams: { map: notes || '—' },
    });
  }

  private stepProposals(): void {
    this.patchNode('proposal', { status: 'running' });
    const proposals = this.candidates
      .map((fields) => {
        const plant = fields.plant.trim() || '1000';
        const known = this.terms.get(plant);
        if (!known?.terms.supplier) return null;
        return buildStudioProposal(
          fields,
          known.terms,
          known.recentPo,
          this.budgetNotes.get(fields.pr_id)?.warning || '',
        );
      })
      .filter((row): row is StudioProposal => row !== null);
    this.proposals.set(proposals);
    this.patchNode('proposal', {
      status: proposals.length ? 'done' : 'warn',
      noteKey: 'experience.pr_to_po.studio.note.proposal',
      noteParams: {
        count: proposals.length,
        total: formatStudioAmount(proposalsTotal(proposals), proposals[0]?.currency || 'QAR'),
      },
    });
    this.patchNode('gate', {
      status: proposals.length ? 'waiting' : 'skipped',
      noteKey: proposals.length ? 'experience.pr_to_po.studio.note.gate' : '',
      noteParams: { count: proposals.length },
    });
    this.expanded.update((current) => new Set([...current, 'gate']));
  }

  private setDecision(prId: string, patch: Partial<StudioProposal>): void {
    this.proposals.update((rows) =>
      rows.map((row) => (row.prId === prId ? { ...row, ...patch } : row)),
    );
  }

  /** Two calls or nothing: the create returns a number, the commit makes it real. */
  async approve(proposal: StudioProposal): Promise<void> {
    if (!proposal.post || this.deciding()) return;
    this.deciding.set(true);
    this.patchNode('post', { status: 'running' });
    try {
      const create = await this.invokeWrite(bapiCreateInvokeBody(proposal.post), 'post');
      const created = outcomeFromInvoke(create.response);
      if (create.blocked) {
        this.setDecision(proposal.prId, {
          outcome: { ...created, sealed: false, messages: [this.i18n.t('experience.pr_to_po.studio.outcome.blocked')] },
        });
        this.patchNode('post', {
          status: 'warn',
          noteKey: 'experience.pr_to_po.studio.note.post_blocked',
          noteParams: {},
        });
        return;
      }
      if (created.sealed) {
        this.setDecision(proposal.prId, { decision: 'approved', outcome: created });
        this.patchNode('post', {
          status: 'done',
          noteKey: 'experience.pr_to_po.studio.note.post_sealed',
          noteParams: {},
        });
        return;
      }
      if (!created.sapOk) {
        this.setDecision(proposal.prId, { outcome: created });
        this.patchNode('post', {
          status: 'error',
          noteKey: 'experience.pr_to_po.studio.note.post_failed',
          noteParams: {},
        });
        return;
      }
      const commit = await this.invokeWrite(bapiCommitInvokeBody(), 'post');
      const committed = outcomeFromInvoke(commit.response);
      const done = !commit.blocked && (committed.sealed || committed.sapOk);
      this.setDecision(proposal.prId, {
        decision: 'approved',
        outcome: { ...created, sapOk: done && created.sapOk },
      });
      this.patchNode('post', {
        status: done ? 'done' : 'error',
        noteKey: done
          ? 'experience.pr_to_po.studio.note.post_done'
          : 'experience.pr_to_po.studio.note.post_failed',
        noteParams: { pos: this.postedPoNumbers().join(', ') || created.poNumber },
      });
    } finally {
      this.deciding.set(false);
      this.updateRejectNode();
    }
  }

  async approveAll(): Promise<void> {
    for (const proposal of this.proposals()) {
      if (proposal.decision === 'pending') {
        await this.approve(proposal);
      }
    }
  }

  async rejectProposal(proposal: StudioProposal): Promise<void> {
    if (this.deciding()) return;
    this.deciding.set(true);
    this.patchNode('reject', { status: 'running' });
    try {
      const call = await this.invokeWrite(discardInvokeBody(proposal.prId, proposal.item), 'reject');
      const outcome = outcomeFromInvoke(call.response);
      this.setDecision(proposal.prId, {
        decision: call.blocked ? 'pending' : 'rejected',
        outcome: call.blocked ? proposal.outcome : outcome,
      });
      this.patchNode('reject', {
        status: call.blocked ? 'warn' : 'done',
        noteKey: call.blocked
          ? 'experience.pr_to_po.studio.note.post_blocked'
          : outcome.sealed
            ? 'experience.pr_to_po.studio.note.reject_sealed'
            : 'experience.pr_to_po.studio.note.reject_done',
        noteParams: { pr: proposal.prId },
      });
    } finally {
      this.deciding.set(false);
    }
  }

  private updateRejectNode(): void {
    const anyRejected = this.proposals().some((row) => row.decision === 'rejected');
    if (!anyRejected && this.pendingCount() === 0) {
      this.patchNode('reject', {
        status: 'skipped',
        noteKey: 'experience.pr_to_po.studio.note.reject_skipped',
        noteParams: {},
      });
    }
    if (this.pendingCount() === 0) {
      this.patchNode('gate', {
        status: 'done',
        noteKey: 'experience.pr_to_po.studio.note.gate_done',
        noteParams: {},
      });
    }
  }
}
