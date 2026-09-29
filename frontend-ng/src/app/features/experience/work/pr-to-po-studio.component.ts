import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  Injector,
  afterNextRender,
  OnDestroy,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Subscription, of, timer } from 'rxjs';
import { catchError, switchMap, takeWhile } from 'rxjs/operators';
import { ApiService } from '@app/core/api.service';
import { appearanceStyles } from '@app/core/brand-appearance';
import { CanonicalApiService, type Run, type System } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { navigationObjectUrl } from '@app/core/navigation.catalog';
import { focusAfterRoute, navigationFocusFromState } from '@app/core/route-focus';
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
import {
  chronology,
  formatReceiptAmount,
  formatReceiptDuration,
  gateChecks,
  gateConsequences,
  readSystemLabel,
  rejectReasonError,
  runDisabledTools,
  workReceipt,
  type ChronologyStep,
} from './pr-to-po-receipt';
import { WorkApiService } from './work-api.service';
import { WorkBarComponent } from './work-bar.component';
import { WorkAppHeaderComponent } from './work-app-header.component';
import { returnToFromParams } from './work-return';
import { canEditExperience } from './work-catalog';
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
  type StudioNodeState,
  type StudioProposal,
} from './pr-to-po-studio';

interface ReceiptPart {
  text: string;
  /** Screen-reader prefix for a bare figure (the working time). */
  sr?: string;
}

interface ChronologyRow extends ChronologyStep {
  node: StudioNodeState;
  href: string | null;
}

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
  imports: [CommonModule, RouterLink, ChatPanelComponent, ThinkingOrbComponent, WorkBarComponent, WorkAppHeaderComponent],
  styleUrl: './work.scss',
  template: `
    <div class="xp-work xp-studio" data-brand-scope data-theme="dark" [ngStyle]="brandStyles()">
      <app-work-bar
        [appContext]="i18n.t('experience.pr_to_po.studio.title')"
        creatorLabelKey="experience.work.open_cockpit"
        [creatorHref]="creatorHref()"
      />
      <app-work-app-header
        [title]="i18n.t('experience.pr_to_po.studio.title')"
        [eyebrow]="i18n.t('experience.work.eyebrow.app', { type: i18n.t('experience.work.pattern.approval') })"
        [description]="i18n.t('experience.pr_to_po.studio.subtitle')"
        [returnTo]="cockpitReturnTo()"
        defaultBackKey="experience.work.back_apps"
      >
        @if (mode() === 'chat') {
          <ck-thinking-orb [state]="busy() ? 'working' : 'listening'" [size]="20" />
        }
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
      </app-work-app-header>

      <div class="xp-studio-body">
        <main class="xp-studio-main">
          @if (error(); as err) {
            <p class="xp-work-error">{{ err }}</p>
          }

          @if (mode() === 'run') {
            @if (!gateOpen()) {
              <section class="xp-studio-hero">
                <div>
                  <p class="xp-studio-kicker">{{ i18n.t('experience.pr_to_po.studio.hero.kicker') }}</p>
                  <h2>{{ i18n.t('experience.pr_to_po.studio.hero.title') }}</h2>
                  <p class="xp-studio-note">{{ i18n.t('experience.pr_to_po.studio.hero.hint') }}</p>
                </div>
                <button
                  type="button"
                  class="xp-work-btn xp-work-btn-primary xp-studio-run"
                  (click)="runNow()"
                  [disabled]="busy() || gateOpen()"
                >
                  {{
                    busy()
                      ? i18n.t('experience.pr_to_po.studio.running')
                      : i18n.t('experience.pr_to_po.studio.run_now')
                  }}
                </button>
              </section>
            }

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

            @if (run()) {
              <section class="xp-receipt" aria-labelledby="xp-receipt-title" data-testid="work-receipt">
                <div class="xp-receipt-main">
                  <h2 id="xp-receipt-title" class="xp-receipt-title">{{ i18n.t('experience.pr_to_po.studio.receipt.title') }}</h2>
                  @if (receiptParts().length) {
                    <p class="xp-receipt-line">
                      @for (part of receiptParts(); track $index) {
                        @if ($index > 0) {
                          <span class="xp-receipt-sep" aria-hidden="true">·</span>
                        }
                        <span>
                          @if (part.sr) {
                            <span class="sr-only">{{ part.sr }}</span>
                          }
                          {{ part.text }}
                        </span>
                      }
                    </p>
                  }
                  <p class="xp-receipt-now" role="status" aria-live="polite">
                    @if (busy() && !gateOpen()) {
                      <ck-thinking-orb [state]="orbState()" [size]="20" [label]="receiptNow()" />
                    }
                    <span>{{ receiptNow() }}</span>
                  </p>
                </div>
                @if (steps().length) {
                  <button
                    type="button"
                    class="xp-work-btn xp-receipt-toggle"
                    [attr.aria-expanded]="chronologyOpen()"
                    aria-controls="xp-receipt-chronology"
                    (click)="toggleChronology($event)"
                    (keydown)="guardRepeat($event)"
                  >
                    {{
                      chronologyOpen()
                        ? i18n.t('experience.pr_to_po.studio.receipt.hide')
                        : i18n.t('experience.pr_to_po.studio.receipt.show')
                    }}
                    <span class="xp-receipt-chevron" aria-hidden="true"></span>
                  </button>
                }
              </section>

              <div
                id="xp-receipt-chronology"
                class="xp-receipt-chronology"
                [attr.data-open]="chronologyOpen()"
                [attr.data-instant]="chronologyInstant()"
                [attr.inert]="chronologyOpen() ? null : ''"
              >
                <div class="xp-receipt-chronology-inner">
                  <ol class="xp-studio-nodes" [attr.aria-label]="i18n.t('experience.pr_to_po.studio.receipt.chronology')">
                    @for (step of steps(); track step.id; let i = $index) {
                      <li [attr.data-status]="step.status" [attr.data-node]="step.id">
                        <div class="xp-studio-node-row">
                          <button
                            type="button"
                            class="xp-studio-node-head"
                            [attr.aria-expanded]="expanded().has(step.id)"
                            [attr.aria-controls]="'xp-node-' + step.id"
                            (click)="toggleNode(step.id)"
                            (keydown)="guardRepeat($event)"
                          >
                            <span class="xp-studio-node-index" aria-hidden="true">{{ i + 1 }}</span>
                            <span class="xp-studio-node-name">
                              <strong>{{ i18n.t(step.labelKey) }}</strong>
                              <span class="xp-studio-node-sub">
                                @if (step.node.noteKey) {
                                  <em>{{ i18n.t(step.node.noteKey, step.node.noteParams) }}</em>
                                } @else if (step.node.error) {
                                  <em>{{ step.node.error }}</em>
                                }
                                <span class="xp-studio-node-kind">{{ i18n.t('experience.pr_to_po.studio.kind.' + step.kind) }}</span>
                                <code>{{ step.technical }}</code>
                              </span>
                            </span>
                            <span class="xp-studio-node-time">
                              @if (step.durationMs != null) {
                                {{ duration(step.durationMs) }}
                              }
                            </span>
                            <span class="xp-studio-node-status">
                              {{ i18n.t('experience.pr_to_po.studio.status.' + step.status) }}
                            </span>
                          </button>
                          @if (step.href) {
                            <a
                              class="xp-studio-node-link"
                              [routerLink]="step.href"
                              [attr.aria-label]="i18n.t('experience.pr_to_po.studio.receipt.invocation_aria', { step: i18n.t(step.labelKey) })"
                            >
                              {{ i18n.t('experience.pr_to_po.studio.receipt.invocation') }}
                            </a>
                          } @else {
                            <span class="xp-studio-node-link" aria-hidden="true"></span>
                          }
                        </div>
                        @if (expanded().has(step.id)) {
                          <div class="xp-studio-node-detail" [id]="'xp-node-' + step.id">
                            @if (step.node.calls.length === 0) {
                              <p class="xp-studio-note">{{ i18n.t('experience.pr_to_po.studio.no_calls') }}</p>
                            }
                            @for (call of step.node.calls; track $index) {
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
                                    <small>{{ duration(call.durationMs) }}</small>
                                  }
                                </summary>
                                <p>{{ i18n.t('experience.pr_to_po.studio.call.request') }}</p>
                                <pre>{{ json(call.request) }}</pre>
                                <p>{{ i18n.t('experience.pr_to_po.studio.call.response') }}</p>
                                <pre>{{ json(call.response) }}</pre>
                              </details>
                            }
                          </div>
                        }
                      </li>
                    }
                  </ol>
                </div>
              </div>
            }

            @if (proposal(); as proposal) {
              <article class="xp-studio-card xp-gate" [attr.data-decision]="decision()" aria-labelledby="xp-gate-title">
                <header class="xp-gate-head">
                  <div class="xp-gate-id">
                    <p class="xp-gate-eyebrow">
                      @if (gateOpen() && !busy()) {
                        <ck-thinking-orb state="listening" [size]="20" [label]="i18n.t('experience.pr_to_po.studio.gate.waiting')" />
                      }
                      <span>{{ i18n.t('experience.pr_to_po.studio.gate.eyebrow') }}</span>
                      @if (gateOpen()) {
                        <span class="xp-gate-waiting">· {{ i18n.t('experience.pr_to_po.studio.gate.waiting') }}</span>
                      }
                    </p>
                    <h2 id="xp-gate-title">{{ proposal.label }}</h2>
                    <p>
                      {{ i18n.t('experience.pr_to_po.studio.gate.line', {
                        pr: proposal.prId,
                        item: proposal.item,
                        plant: proposal.plant,
                      }) }}
                    </p>
                  </div>
                  <div class="xp-gate-amount">
                    <strong>{{ amount(proposal) }}</strong>
                    <span>{{ i18n.t('experience.pr_to_po.studio.gate.amount') }}</span>
                  </div>
                </header>
                @if (gateOpen()) {
                  <p class="xp-gate-lede">{{ i18n.t('experience.pr_to_po.studio.gate.lede') }}</p>
                }
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

                <dl class="xp-gate-terms">
                  <div>
                    <dt>{{ i18n.t('experience.pr_to_po.studio.gate.supplier') }}</dt>
                    <dd><span class="xp-gate-id-value">{{ proposal.supplier || '—' }}</span></dd>
                  </div>
                  <div>
                    <dt>{{ i18n.t('experience.pr_to_po.studio.gate.payment') }}</dt>
                    <dd><span class="xp-gate-id-value">{{ proposal.paymentTerms || '—' }}</span></dd>
                  </div>
                  <div>
                    <dt>{{ i18n.t('experience.pr_to_po.studio.gate.incoterms') }}</dt>
                    <dd><span class="xp-gate-id-value">{{ proposal.incoterms || '—' }}</span></dd>
                  </div>
                  <div>
                    <dt>{{ i18n.t('experience.pr_to_po.studio.gate.type') }}</dt>
                    <dd><span class="xp-gate-id-value">{{ proposal.format || 'ZLPO' }}</span></dd>
                  </div>
                </dl>

                <section class="xp-gate-lines" aria-labelledby="xp-gate-lines-title">
                  <h3 id="xp-gate-lines-title">{{ i18n.t('experience.pr_to_po.studio.gate.lines') }}</h3>
                  <div class="xp-gate-table">
                    <table>
                      <thead>
                        <tr>
                          <th scope="col">{{ i18n.t('experience.pr_to_po.studio.gate.col.item') }}</th>
                          <th scope="col">{{ i18n.t('experience.pr_to_po.studio.gate.col.article') }}</th>
                          <th scope="col" class="xp-num">{{ i18n.t('experience.pr_to_po.studio.gate.col.quantity') }}</th>
                          <th scope="col" class="xp-num">{{ i18n.t('experience.pr_to_po.studio.gate.col.price') }}</th>
                          <th scope="col" class="xp-num">{{ i18n.t('experience.pr_to_po.studio.gate.col.total') }}</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr>
                          <td class="xp-gate-id-value">{{ proposal.item }}</td>
                          <td>{{ proposal.label }}</td>
                          <td class="xp-num">{{ quantity(proposal) }}</td>
                          <td class="xp-num">{{ unitPrice(proposal) }}</td>
                          <td class="xp-num">{{ amount(proposal) }}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                  <p class="xp-gate-caption">{{ i18n.t('experience.pr_to_po.studio.gate.lines_caption', { pr: proposal.prId }) }}</p>
                </section>

                <div class="xp-gate-columns">
                  <section aria-labelledby="xp-gate-checked-title">
                    <h3 id="xp-gate-checked-title">{{ i18n.t('experience.pr_to_po.studio.gate.checked') }}</h3>
                    <ul class="xp-gate-list">
                      @for (check of checks(); track check.id) {
                        <li [attr.data-ok]="check.ok">
                          <span class="xp-gate-mark" aria-hidden="true">{{ check.ok ? '✓' : '!' }}</span>
                          <span>
                            <span class="sr-only">
                              {{ i18n.t(check.ok ? 'experience.pr_to_po.studio.gate.check_ok' : 'experience.pr_to_po.studio.gate.check_warn') }}
                            </span>
                            {{ i18n.t(check.key, check.params) }}
                            @if (check.tool) {
                              <code>{{ check.tool }}</code>
                            }
                          </span>
                        </li>
                      }
                    </ul>
                    @if (proposal.justification) {
                      <blockquote class="xp-gate-quote">{{ proposal.justification }}</blockquote>
                    }
                  </section>
                  @if (gateOpen()) {
                    <section aria-labelledby="xp-gate-triggers-title">
                      <h3 id="xp-gate-triggers-title">{{ i18n.t('experience.pr_to_po.studio.gate.triggers') }}</h3>
                      <ol class="xp-gate-list">
                        @for (item of approveNext(); track item.step) {
                          <li [attr.data-tone]="item.tone">
                            <span class="xp-gate-mark" aria-hidden="true">{{ $index + 1 }}</span>
                            <span>
                              {{ i18n.t(item.key, item.params) }}
                              @if (item.tools.length) {
                                <code>{{ item.tools.join(' · ') }}</code>
                              }
                            </span>
                          </li>
                        }
                      </ol>
                      @if (rejectNext().length) {
                        <h4 class="xp-gate-subhead">{{ i18n.t('experience.pr_to_po.studio.gate.if_reject') }}</h4>
                        <ol class="xp-gate-list">
                          @for (item of rejectNext(); track item.step) {
                            <li [attr.data-tone]="item.tone">
                              <span class="xp-gate-mark" aria-hidden="true">{{ $index + 1 }}</span>
                              <span>{{ i18n.t(item.key, item.params) }}</span>
                            </li>
                          }
                        </ol>
                      }
                    </section>
                  }
                </div>

                @if (proposal.dossier) {
                  <details class="xp-gate-dossier">
                    <summary>{{ i18n.t('experience.pr_to_po.studio.gate.dossier') }}</summary>
                    <pre>{{ proposal.dossier }}</pre>
                  </details>
                }

                @if (gateOpen()) {
                  <div class="xp-gate-actions">
                    <button
                      type="button"
                      class="xp-work-btn xp-gate-btn xp-studio-approve"
                      (click)="approve()"
                      [disabled]="deciding()"
                      [attr.aria-label]="i18n.t('experience.pr_to_po.studio.gate.approve_aria', { pr: proposal.prId })"
                    >
                      {{ i18n.t('experience.pr_to_po.studio.gate.approve') }}
                    </button>
                    <button
                      type="button"
                      class="xp-work-btn xp-gate-btn xp-studio-reject"
                      (click)="reject()"
                      [disabled]="deciding()"
                      [attr.aria-expanded]="rejecting()"
                      aria-controls="xp-gate-reject"
                      [attr.aria-label]="i18n.t('experience.pr_to_po.studio.gate.reject_aria', { pr: proposal.prId })"
                    >
                      {{ i18n.t('experience.pr_to_po.studio.gate.reject') }}
                    </button>
                  </div>
                  @if (rejecting()) {
                    <form id="xp-gate-reject" class="xp-gate-reject" (submit)="confirmReject($event)" novalidate>
                      <label for="xp-gate-reason">{{ i18n.t('experience.pr_to_po.studio.gate.reason_label') }}</label>
                      <p id="xp-gate-reason-hint" class="xp-gate-hint">{{ i18n.t('experience.pr_to_po.studio.gate.reason_hint') }}</p>
                      <textarea
                        id="xp-gate-reason"
                        rows="3"
                        required
                        [value]="rejectReason()"
                        (input)="onReason($event)"
                        [attr.aria-invalid]="reasonError() ? 'true' : null"
                        [attr.aria-describedby]="reasonError() ? 'xp-gate-reason-hint xp-gate-reason-error' : 'xp-gate-reason-hint'"
                      ></textarea>
                      @if (reasonError(); as err) {
                        <p id="xp-gate-reason-error" class="xp-gate-error" role="alert">{{ i18n.t(err) }}</p>
                      }
                      <div class="xp-gate-reject-actions">
                        <button type="submit" class="xp-work-btn xp-gate-btn xp-studio-reject-confirm" [disabled]="deciding()">
                          {{ i18n.t('experience.pr_to_po.studio.gate.reject_confirm') }}
                        </button>
                        <button type="button" class="xp-work-btn xp-gate-cancel" (click)="cancelReject()">
                          {{ i18n.t('experience.pr_to_po.studio.gate.reject_cancel') }}
                        </button>
                      </div>
                    </form>
                  }
                } @else if (decision() !== 'pending' || gateDecidedNow()) {
                  <section class="xp-gate-after" aria-labelledby="xp-gate-after-title">
                    <p class="xp-studio-outcome" role="status" [attr.data-ok]="outcomeOk()">
                      <strong id="xp-gate-after-title">
                        {{
                          decision() === 'rejected'
                            ? i18n.t('experience.pr_to_po.studio.gate.decided_reject')
                            : i18n.t('experience.pr_to_po.studio.gate.decided_approve')
                        }}
                      </strong>
                      @if (decision() !== 'rejected' && outcome(); as outcome) {
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
                      } @else if (busy()) {
                        {{ i18n.t('experience.pr_to_po.studio.gate.resuming') }}
                      }
                    </p>
                    @if (decision() === 'rejected' && lastReason()) {
                      <p class="xp-gate-hint">{{ i18n.t('experience.pr_to_po.studio.gate.reason_given', { reason: lastReason() }) }}</p>
                    }
                    @if (afterSteps().length) {
                      <h3 class="xp-gate-subhead">{{ i18n.t('experience.pr_to_po.studio.gate.then') }}</h3>
                      <ol class="xp-gate-list">
                        @for (step of afterSteps(); track step.id) {
                          <li [attr.data-status]="step.status">
                            <span class="xp-gate-mark" aria-hidden="true">{{ step.status === 'done' ? '✓' : '·' }}</span>
                            <span>
                              <strong>{{ i18n.t(step.labelKey) }}</strong>
                              ·
                              @if (step.node.noteKey) {
                                {{ i18n.t(step.node.noteKey, step.node.noteParams) }}
                              } @else {
                                {{ i18n.t('experience.pr_to_po.studio.status.' + step.status) }}
                              }
                            </span>
                          </li>
                        }
                      </ol>
                    }
                  </section>
                }
              </article>
              @if (candidates().length && !busy() && !gateOpen()) {
                <div class="xp-studio-next">
                  <p class="xp-studio-note">{{ i18n.t('experience.pr_to_po.studio.gate.next') }}</p>
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
            }
          } @else {
            <section class="xp-studio-chat-wrap">
              <div class="xp-studio-chips">
                @for (chip of chatChips; track chip) {
                  <button
                    type="button"
                    class="xp-studio-chip"
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
                <section class="xp-studio-portal xp-studio-chat">
                  <header>
                    <div class="xp-studio-portal-head">
                      <div>
                        <p class="xp-studio-kicker">{{ i18n.t('experience.pr_to_po.studio.chat.title') }}</p>
                        <p class="xp-studio-note">
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
                <p class="xp-studio-note">{{ i18n.t('experience.pr_to_po.studio.chat.offline') }}</p>
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
                <code [id]="'xp-tool-' + tool.name">{{ tool.name }}</code>
                @if (tool.toggle) {
                  <button
                    type="button"
                    class="xp-studio-toggle"
                    role="switch"
                    [attr.aria-labelledby]="'xp-tool-' + tool.name"
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
          <p class="xp-studio-note">{{ i18n.t('experience.pr_to_po.studio.rail.hint') }}</p>
          <p class="xp-studio-note">
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
  private readonly host = inject(ElementRef<HTMLElement>);
  private readonly injector = inject(Injector);
  private readonly router = inject(Router);
  readonly i18n = inject(I18nService);
  readonly workspace = inject(WorkspaceService);
  private readonly route = inject(ActivatedRoute);
  readonly cockpitReturnTo = signal<string | null>(null);
  readonly creatorHref = computed(() =>
    this.workspace.experienceStudioV1Enabled()
    && canEditExperience(this.workspace.current()?.role_template, this.workspace.isAdmin())
      ? '/create'
      : null,
  );
  /**
   * The Studio wears the workspace appearance, always in the dark: the palette
   * and accent a workspace declares in platform_brand.appearance, else the
   * product's dark tokens. work.scss derives every --studio-* token from them.
   */
  readonly brandStyles = computed(() => {
    const brand = this.workspace.current()?.settings?.['platform_brand'] as Record<string, unknown> | undefined;
    return appearanceStyles(brand?.['appearance'], 'dark');
  });

  private readonly context = factoryRuntimeContext();
  private pollSub: Subscription | null = null;

  readonly mode = signal<StudioMode>('run');
  readonly launching = signal(false);
  readonly deciding = signal(false);
  readonly error = signal<string | null>(null);
  readonly run = signal<Run | null>(null);
  readonly posted = signal<PostedRow[]>([]);
  readonly expanded = signal<Set<StudioNodeId>>(new Set());
  readonly chronologyOpen = signal(false);
  /** Keyboard-initiated toggles skip the reveal (Emil: never animate a key press). */
  readonly chronologyInstant = signal(false);
  readonly rejecting = signal(false);
  readonly rejectReason = signal('');
  readonly reasonError = signal<string | null>(null);
  /** The reason given in this session, echoed after the decision. */
  readonly lastReason = signal('');
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

  /** L32 — the work receipt: only what the Run recorded, nothing estimated. */
  readonly receipt = computed(() => workReceipt(this.run(), this.nodes()));
  readonly steps = computed<ChronologyRow[]>(() => {
    const run = this.run();
    const byId = new Map(this.nodes().map((node) => [node.id, node]));
    return chronology(run, this.nodes()).map((step) => ({
      ...step,
      node: byId.get(step.id)!,
      href: run && step.invocationId
        ? navigationObjectUrl('skill_invocation', step.invocationId, { runId: run.id })
        : null,
    }));
  });
  readonly receiptParts = computed<ReceiptPart[]>(() => {
    const receipt = this.receipt();
    const t = (key: string, params?: Record<string, string | number>) =>
      this.i18n.t(`experience.pr_to_po.studio.receipt.${key}`, params);
    const count = (key: string, value: number, params: Record<string, string | number> = {}) =>
      t(`${key}_${value === 1 ? 'one' : 'other'}`, { count: value, ...params });
    const parts: ReceiptPart[] = [];
    if (receipt.stepsDone) parts.push({ text: count('steps', receipt.stepsDone) });
    if (receipt.stepsFailed) parts.push({ text: count('failed', receipt.stepsFailed) });
    for (const read of receipt.reads) {
      parts.push({ text: count('reads', read.count, { system: readSystemLabel(read.server) }) });
    }
    if (receipt.budget) parts.push({ text: t(receipt.budget.ok ? 'budget_ok' : 'budget_ko') });
    if (receipt.agentMs != null && !this.busy()) {
      parts.push({ text: this.duration(receipt.agentMs), sr: t('time_label') });
    }
    return parts;
  });
  readonly receiptNow = computed(() => {
    const t = (key: string, params?: Record<string, string | number>) =>
      this.i18n.t(`experience.pr_to_po.studio.receipt.${key}`, params);
    const current = this.receipt().current;
    if (current) return t('now', { step: this.i18n.t(`experience.pr_to_po.studio.node.${current}`) });
    if (this.gateOpen()) return t('waiting');
    if (this.busy()) return t('starting');
    if (this.run()?.status === 'failed') return t('failed_run');
    if (this.run()?.status === 'completed') return t('done');
    return '';
  });
  /** One orb per screen: it sits on the step the agent is on. */
  readonly orbState = computed(() => {
    const current = this.receipt().current;
    if (current === 'summarise') return 'composing' as const;
    const kind = current ? STUDIO_NODE_KIND[current] : null;
    if (kind === 'read') return 'searching' as const;
    if (kind === 'derive') return 'solving' as const;
    return 'working' as const;
  });
  readonly checks = computed(() => gateChecks(this.run(), this.nodes(), this.proposal(), this.i18n.locale()));
  private readonly consequenceOptions = computed(() => ({
    unsealed: this.writeUnsealed(),
    disabledTools: runDisabledTools(this.run()),
    prId: this.proposal()?.prId ?? '',
  }));
  readonly approveNext = computed(() => gateConsequences('approve', this.nodes(), this.consequenceOptions()));
  readonly rejectNext = computed(() => gateConsequences('reject', this.nodes(), this.consequenceOptions()));
  readonly gateDecidedNow = computed(() => gateDecided(this.run()));
  readonly afterSteps = computed(() =>
    this.steps().filter((step) => (step.id === 'post' || step.id === 'reject' || step.id === 'audit') && step.status !== 'skipped'),
  );
  readonly outcomeOk = computed(() => {
    if (this.decision() === 'rejected') return true;
    const outcome = this.outcome();
    return outcome ? outcome.sealed || outcome.sapOk : true;
  });
  readonly chatSystemPrompt = computed(() =>
    this.i18n.t('experience.pr_to_po.studio.chat.system', { facts: this.chatFacts() || '—' }),
  );

  ngOnInit(): void {
    this.cockpitReturnTo.set(returnToFromParams(this.route.snapshot.queryParamMap.get('returnTo')));
    this.loadRail();
    this.loadSystem();
    this.loadPendingGate();
    queueMicrotask(() => this.focusRouteTarget());
  }

  private focusRouteTarget(): void {
    focusAfterRoute(this.host.nativeElement, {
      focus: navigationFocusFromState(
        this.router.lastSuccessfulNavigation?.extras?.state
          ?? (globalThis.history?.state as Record<string, unknown> | null),
      ),
    });
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

  amount(proposal: StudioProposal): string {
    return formatReceiptAmount(proposal.amount, proposal.currency, this.i18n.locale());
  }

  unitPrice(proposal: StudioProposal): string {
    return formatReceiptAmount(Number(proposal.netPrice) || 0, proposal.currency, this.i18n.locale());
  }

  quantity(proposal: StudioProposal): string {
    const value = Number(proposal.quantity);
    const figure = Number.isFinite(value)
      ? value.toLocaleString(this.i18n.locale() === 'fr' ? 'fr-FR' : 'en-US', { maximumFractionDigits: 3 })
      : proposal.quantity;
    return `${figure} ${proposal.unit}`.trim();
  }

  duration(ms: number): string {
    return formatReceiptDuration(ms, this.i18n.locale());
  }

  toggleChronology(event: MouseEvent): void {
    // `detail === 0`: the click came from Enter or Space, not a pointer.
    this.chronologyInstant.set(event.detail === 0);
    this.chronologyOpen.update((open) => !open);
  }

  /** A held key must not flicker a disclosure open and shut. */
  guardRepeat(event: KeyboardEvent): void {
    if (event.repeat && (event.key === 'Enter' || event.key === ' ')) event.preventDefault();
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

  /** A refusal needs a reason: the button opens the labelled field first. */
  reject(): void {
    if (!this.gateOpen() || this.deciding()) return;
    this.rejecting.set(true);
    this.reasonError.set(null);
    this.focusAfterRender('#xp-gate-reason');
  }

  onReason(event: Event): void {
    this.rejectReason.set((event.target as HTMLTextAreaElement).value);
    if (this.reasonError() && !rejectReasonError(this.rejectReason())) this.reasonError.set(null);
  }

  confirmReject(event?: Event): void {
    event?.preventDefault();
    const error = rejectReasonError(this.rejectReason());
    if (error) {
      this.reasonError.set(error);
      (this.host.nativeElement as HTMLElement).querySelector<HTMLTextAreaElement>('#xp-gate-reason')?.focus();
      return;
    }
    const reason = this.rejectReason().trim();
    this.lastReason.set(reason);
    this.decide('reject', this.i18n.t('experience.pr_to_po.studio.gate.note_reject_reason', { reason }));
  }

  cancelReject(): void {
    this.rejecting.set(false);
    this.reasonError.set(null);
    this.focusAfterRender('.xp-studio-reject');
  }

  private focusAfterRender(selector: string): void {
    afterNextRender(
      () => (this.host.nativeElement as HTMLElement).querySelector<HTMLElement>(selector)?.focus(),
      { injector: this.injector },
    );
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

  private decide(action: 'accept' | 'reject', note?: string): void {
    const current = this.run();
    if (!current || !this.gateOpen() || this.deciding()) return;
    this.deciding.set(true);
    this.chatBusy.set(true);
    this.workApi
      .decide(current, action, note ?? this.i18n.t(`experience.pr_to_po.studio.gate.note_${action}`))
      .subscribe((decided) => {
        this.deciding.set(false);
        this.chatBusy.set(false);
        if (decided) this.rejecting.set(false);
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
