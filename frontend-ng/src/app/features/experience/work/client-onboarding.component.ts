import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { catchError, exhaustMap, of, takeWhile, timer } from 'rxjs';
import { AdoptionService } from '@app/core/adoption.service';
import {
  CLIENT_STEPS,
  chosenSource,
  clientStepStates,
  fileState,
  ingestionSettled,
  ingestionSummary,
  sourceHasDocuments,
  type AdoptionSource,
  type ClientStep,
  type CollectionInventory,
  type InventorySource,
} from '@app/core/adoption-journey';
import { ApiService } from '@app/core/api.service';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { ChatPanelComponent } from '@app/features/chat/chat-panel.component';
import { IngestionStatusComponent } from '@app/features/knowledge/ingestion-status.component';
import { WorkApiService } from './work-api.service';
import { workPageHref } from './work-catalog';

const FILE_ORDER = { error: 0, pending: 1, indexed: 2 } as const;
const VISIBLE_FILES = 6;

/**
 * L34 — getting started on the workspace's own documents (artboard A2).
 *
 * Four steps, all on real data: choose one of this workspace's collections,
 * optionally add documents (per-file status from the collection inventory,
 * job status from the existing ingestion panel), ask a question scoped to
 * that collection, then decide on the answer with the usual feedback or
 * correction. The decision step is recorded only once that decision is saved.
 */
@Component({
  selector: 'app-client-onboarding',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, ChatPanelComponent, IngestionStatusComponent],
  template: `
    <p class="sr-only" aria-live="polite" role="status">{{ announcement() }}</p>
    @if (!adoption.journeyAvailable()) {
      <section class="xp-onb-card xp-onb-unavailable" aria-labelledby="onb-unavailable-title" data-testid="onboarding-unavailable">
        <h2 id="onb-unavailable-title">{{ i18n.t('experience.work.onboarding.unavailable.title') }}</h2>
        <p>{{ i18n.t('experience.work.onboarding.unavailable.body') }}</p>
      </section>
    } @else {
      <div class="xp-onb-layout">
        <div class="xp-onb-main">
          <ol class="xp-onb-steps" [attr.aria-label]="i18n.t('experience.work.onboarding.steps_label')" data-testid="onboarding-steps">
            @for (step of steps; track step; let i = $index) {
              <li
                class="xp-onb-step"
                [class.is-current]="states()[step] === 'current'"
                [class.is-done]="states()[step] === 'done'"
                [attr.aria-current]="states()[step] === 'current' ? 'step' : null"
              >
                <span class="xp-onb-step-num">{{ i18n.t('experience.work.onboarding.step_number', { n: i + 1 }) }}</span>
                <span class="xp-onb-step-title">{{ i18n.t('experience.work.onboarding.step.' + step + '.title') }}</span>
                <span class="xp-onb-step-body">{{ i18n.t('experience.work.onboarding.step.' + step + '.body') }}</span>
                <span class="xp-onb-step-state" [attr.data-state]="states()[step]">
                  @if (states()[step] === 'done') { <span aria-hidden="true">✓ </span> }
                  {{ i18n.t('experience.work.onboarding.state.' + states()[step]) }}
                </span>
              </li>
            }
          </ol>

          <section class="xp-onb-card" aria-labelledby="onb-source-title" data-testid="onboarding-source">
            @if (confirmed(); as src) {
              <header class="xp-onb-card-head">
                <div>
                  <p class="xp-onb-label">{{ i18n.t('experience.work.onboarding.source.label') }}</p>
                  <h2 id="onb-source-title">{{ src.name }}</h2>
                </div>
                <div class="xp-onb-head-actions">
                  <span class="xp-onb-badge" [attr.data-tone]="statusTone(src)">{{ statusLabel(src) }}</span>
                  @if (sources().length > 1) {
                    <button type="button" class="xp-onb-btn" (click)="changeSource()">
                      {{ i18n.t('experience.work.onboarding.source.change') }}
                    </button>
                  }
                </div>
              </header>

              <div class="xp-onb-docs">
                <div class="xp-onb-docs-main">
                  <h3>{{ i18n.t('experience.work.onboarding.documents.title') }}</h3>
                  @if (optionalDocuments()) {
                    <p class="xp-onb-note">{{ i18n.t('experience.work.onboarding.documents.optional', { n: format(src.document_count) }) }}</p>
                  }
                  @if (src.can_add_documents ?? adoption.progress()?.can_add_documents) {
                    <label
                      class="xp-onb-drop"
                      [class.is-dragging]="dragging()"
                      (dragover)="onDragOver($event)"
                      (dragleave)="dragging.set(false)"
                      (drop)="onDrop($event)"
                    >
                      <span id="onb-drop-title" class="xp-onb-drop-title">{{ i18n.t('experience.work.onboarding.documents.pick') }}</span>
                      <span id="onb-drop-hint" class="xp-onb-note">{{ i18n.t('experience.work.onboarding.documents.hint') }} {{ i18n.t('experience.work.onboarding.documents.formats') }}</span>
                      <input
                        class="sr-only"
                        type="file"
                        multiple
                        data-testid="onboarding-file-input"
                        [disabled]="uploading()"
                        aria-labelledby="onb-drop-title"
                        [attr.aria-describedby]="uploadError() ? 'onb-drop-hint onb-upload-error' : 'onb-drop-hint'"
                        accept=".pdf,.txt,.md,.docx,.csv,.json,.png,.jpg,.jpeg,.tif,.tiff,.webp"
                        (change)="onFileSelect($event)"
                      />
                    </label>
                  } @else {
                    <p class="xp-onb-note">{{ i18n.t('experience.work.onboarding.documents.read_only') }}</p>
                  }
                  @if (uploadError()) {
                    <p id="onb-upload-error" class="xp-onb-error" role="alert">{{ i18n.t('experience.work.onboarding.documents.upload_error') }}</p>
                  }
                  @if (inventoryError()) {
                    <p class="xp-onb-note">{{ i18n.t('experience.work.onboarding.documents.load_error') }}</p>
                  } @else if (!inventory()) {
                    <p class="xp-onb-note">{{ i18n.t('experience.work.onboarding.documents.loading') }}</p>
                  } @else if (files().length) {
                    <ul class="xp-onb-files" [attr.aria-label]="i18n.t('experience.work.onboarding.documents.files_label')" data-testid="onboarding-files">
                      @for (file of files(); track file.id) {
                        <li class="xp-onb-file" [attr.data-state]="stateOf(file)">
                          <span class="xp-onb-file-name">{{ file.filename }}</span>
                          <span class="xp-onb-file-state">{{ fileLabel(file) }}</span>
                        </li>
                      }
                    </ul>
                    @if (moreFiles() > 0) {
                      <p class="xp-onb-note">{{ i18n.t('experience.work.onboarding.documents.more', { n: format(moreFiles()) }) }}</p>
                    }
                  }
                </div>
                <div class="xp-onb-counts" data-testid="onboarding-counts">
                  <dl class="xp-onb-count">
                    <dt>{{ i18n.t('experience.work.onboarding.documents.documents') }}</dt>
                    <dd>{{ inventory() ? format(summary().indexed) + ' / ' + format(summary().total) : '—' }}</dd>
                  </dl>
                  @if (inventory() && summary().total > 0) {
                    <progress
                      class="xp-onb-progress"
                      [max]="summary().total"
                      [value]="summary().indexed"
                      [attr.aria-label]="i18n.t('experience.work.onboarding.documents.count_label')"
                      [attr.aria-valuetext]="i18n.t('experience.work.onboarding.documents.progress', { indexed: format(summary().indexed), total: format(summary().total) })"
                    ></progress>
                  }
                  <dl class="xp-onb-count">
                    <dt>{{ i18n.t('experience.work.onboarding.documents.passages') }}</dt>
                    <dd>{{ inventory() ? format(summary().passages) : '—' }}</dd>
                  </dl>
                  <dl class="xp-onb-count">
                    <dt>{{ i18n.t('experience.work.onboarding.documents.errors') }}</dt>
                    <dd>{{ inventory() ? format(summary().errors) : '—' }}</dd>
                  </dl>
                </div>
              </div>
              @if (showJobStatus()) {
                <div class="xp-onb-job"><app-ingestion-status [collectionId]="src.id" /></div>
              }

              <div class="xp-onb-question">
                <h3>{{ i18n.t('experience.work.onboarding.question.title') }}</h3>
                <p class="xp-onb-note">{{ i18n.t('experience.work.onboarding.question.hint', { source: src.name }) }}</p>
                @if (contextError()) {
                  <p class="xp-onb-error" role="alert">{{ i18n.t('experience.work.onboarding.question.error') }}</p>
                  <button type="button" class="xp-onb-btn" (click)="openContext()">{{ i18n.t('common.retry') }}</button>
                } @else if (contextId(); as id) {
                  <div class="xp-onb-chat">
                    <app-chat-panel
                      [compact]="true"
                      [freshSession]="!adoption.progress()?.session_id"
                      [resumeSessionId]="adoption.progress()?.session_id || null"
                      [contextId]="id"
                      [contextCollection]="src.name"
                      (adoptionInteraction)="onChat($event)"
                    />
                  </div>
                } @else {
                  <p class="xp-onb-note" role="status">{{ i18n.t('experience.work.onboarding.question.opening') }}</p>
                }
              </div>

              <div class="xp-onb-decision" data-testid="onboarding-decision">
                <h3>{{ i18n.t('experience.work.onboarding.decision.title') }}</h3>
                @if (decided()) {
                  <p class="xp-onb-done">{{ i18n.t('experience.work.onboarding.decision.done') }}</p>
                } @else if (answered()) {
                  <p class="xp-onb-note">{{ i18n.t('experience.work.onboarding.decision.prompt') }}</p>
                  <div class="xp-onb-actions">
                    <button type="button" class="xp-onb-btn" [disabled]="adoption.saving()" (click)="decide('up')">
                      {{ i18n.t('experience.work.onboarding.decision.confirm') }}
                    </button>
                    <button type="button" class="xp-onb-btn" [disabled]="adoption.saving()" (click)="decide('down')">
                      {{ i18n.t('experience.work.onboarding.decision.flag') }}
                    </button>
                    @if (chat()?.canCorrectInChat()) {
                      <button type="button" class="xp-onb-btn" (click)="correct()">
                        {{ i18n.t('experience.work.onboarding.decision.correct') }}
                      </button>
                    }
                  </div>
                  @if (noAnswer()) {
                    <p class="xp-onb-error" role="alert">{{ i18n.t('experience.work.onboarding.decision.no_answer') }}</p>
                  }
                } @else {
                  <p class="xp-onb-note">{{ i18n.t('experience.work.onboarding.decision.waiting') }}</p>
                }
                @if (!decided() && pendingDecision(); as pending) {
                  <p class="xp-onb-note">
                    {{ i18n.t('experience.work.onboarding.decision.pending', { app: pending.name }) }}
                    <a class="xp-onb-link" [routerLink]="pending.href">{{ i18n.t('experience.work.onboarding.decision.open_pending') }}</a>
                  </p>
                }
              </div>
            } @else {
              <fieldset class="xp-onb-choose">
                <legend><h2 id="onb-source-title">{{ i18n.t('experience.work.onboarding.source.choose') }}</h2></legend>
                <div class="xp-onb-options">
                  @for (src of sources(); track src.id) {
                    <label class="xp-onb-option" [class.is-selected]="selectedId() === src.id">
                      <input type="radio" name="onb-source" [value]="src.id" [checked]="selectedId() === src.id" (change)="selectedId.set(src.id)" />
                      <span class="xp-onb-option-text">
                        <span class="xp-onb-option-name">{{ src.name }}</span>
                        <span class="xp-onb-note">
                          {{ i18n.t('experience.work.onboarding.source.counts', { documents: format(src.document_count), passages: format(src.chunk_count) }) }}
                          · {{ statusLabel(src) }}
                        </span>
                      </span>
                    </label>
                  }
                </div>
                <button type="button" class="xp-onb-btn" data-testid="onboarding-use-source" [disabled]="!selectedId() || adoption.saving()" (click)="useSource()">
                  {{ i18n.t('experience.work.onboarding.source.use') }}
                </button>
              </fieldset>
            }
            @if (adoption.error()) {
              <p class="xp-onb-error" role="alert">{{ i18n.t('experience.adoption.error') }}</p>
            }
          </section>
        </div>

        <aside class="xp-onb-aside">
          <section class="xp-onb-card" aria-labelledby="onb-objective-title">
            <h2 id="onb-objective-title">{{ i18n.t('experience.work.onboarding.objective.title') }}</h2>
            <p>{{ i18n.t('experience.work.onboarding.objective.body') }}</p>
            <p class="xp-onb-note" data-testid="onboarding-objective-progress">{{ i18n.t('experience.work.onboarding.objective.progress', { done: doneCount() }) }}</p>
          </section>
          <section class="xp-onb-card" aria-labelledby="onb-proof-title">
            <h2 id="onb-proof-title">{{ i18n.t('experience.work.onboarding.proof.title') }}</h2>
            <ul class="xp-onb-proof">
              @for (item of proofs; track item) {
                <li>
                  <span class="xp-onb-proof-title">{{ i18n.t('experience.work.onboarding.proof.' + item + '.title') }}</span>
                  <span class="xp-onb-note">{{ i18n.t('experience.work.onboarding.proof.' + item + '.body') }}</span>
                </li>
              }
            </ul>
          </section>
        </aside>
      </div>
    }
  `,
  styles: [`
    :host { display: block; }
    .xp-onb-layout { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 24px; align-items: start; }
    .xp-onb-main, .xp-onb-aside { display: flex; flex-direction: column; gap: 20px; min-width: 0; }
    .xp-onb-card { padding: 20px; border: 1px solid var(--ck-stroke-2); border-radius: 8px; background: var(--ck-bg-panel); min-width: 0; }
    .xp-onb-card h2 { margin: 0 0 8px; font-size: 18px; font-weight: 600; }
    .xp-onb-card h3 { margin: 0 0 6px; font-size: 15px; font-weight: 600; }
    .xp-onb-card p { margin: 0 0 8px; line-height: 1.5; }
    .xp-onb-note { color: var(--ck-fg-3); font-size: 13px; line-height: 1.45; }
    .xp-onb-label { margin: 0 0 2px; color: var(--ck-fg-3); font-size: 12px; font-weight: 500; }
    .xp-onb-error { color: var(--ck-status-neg-fg); font-size: 13px; }
    .xp-onb-done { color: var(--ck-fg-1); font-weight: 600; }
    .xp-onb-steps { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 0; padding: 0; list-style: none; }
    .xp-onb-step { display: flex; flex-direction: column; gap: 4px; padding: 14px; border: 1px solid var(--ck-stroke-2); border-radius: 8px; background: var(--ck-bg-panel); }
    .xp-onb-step.is-current { border-color: var(--ck-signal-cool); box-shadow: inset 3px 0 0 var(--ck-signal-cool); }
    .xp-onb-step-num { color: var(--ck-fg-3); font-size: 12px; font-weight: 500; }
    .xp-onb-step-title { font-size: 15px; font-weight: 600; color: var(--ck-fg-1); }
    .xp-onb-step-body { color: var(--ck-fg-3); font-size: 13px; line-height: 1.4; flex: 1 1 auto; }
    .xp-onb-step-state { margin-top: 6px; color: var(--ck-fg-2); font-size: 12px; font-weight: 600; }
    .xp-onb-step-state[data-state='done'] { color: var(--ck-status-ok-fg); }
    .xp-onb-step-state[data-state='todo'], .xp-onb-step-state[data-state='optional'] { color: var(--ck-fg-3); font-weight: 500; }
    .xp-onb-card-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; padding-bottom: 14px; margin-bottom: 16px; border-bottom: 1px solid var(--ck-stroke-2); }
    .xp-onb-card-head h2 { margin: 0; }
    .xp-onb-head-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
    .xp-onb-badge { padding: 3px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; background: var(--ck-status-neutral-bg); color: var(--ck-status-neutral-fg); }
    .xp-onb-badge[data-tone='ok'] { background: var(--ck-status-ok-bg); color: var(--ck-status-ok-fg); }
    .xp-onb-badge[data-tone='info'] { background: var(--ck-status-info-bg); color: var(--ck-status-info-fg); }
    .xp-onb-badge[data-tone='warn'] { background: var(--ck-status-warn-bg); color: var(--ck-status-warn-fg); }
    .xp-onb-docs { display: grid; grid-template-columns: minmax(0, 1fr) 220px; gap: 20px; }
    .xp-onb-docs-main { min-width: 0; }
    .xp-onb-drop { display: flex; flex-direction: column; gap: 2px; margin: 8px 0 12px; padding: 16px; border: 1px dashed var(--ck-stroke-3); border-radius: 8px; background: var(--ck-bg-inset); cursor: pointer; }
    .xp-onb-drop.is-dragging { border-color: var(--ck-signal-cool); }
    .xp-onb-drop:focus-within { outline: 2px solid var(--ck-signal-cool); outline-offset: 2px; }
    .xp-onb-drop-title { font-weight: 600; color: var(--ck-fg-1); }
    .xp-onb-files { display: flex; flex-direction: column; gap: 6px; margin: 0 0 8px; padding: 0; list-style: none; }
    .xp-onb-file { display: flex; justify-content: space-between; gap: 12px; padding: 8px 12px; border: 1px solid var(--ck-stroke-2); border-radius: 6px; font-size: 13px; transition: opacity 150ms ease-out; }
    @starting-style { .xp-onb-file { opacity: 0; } }
    .xp-onb-file-name { font-weight: 600; min-width: 0; overflow-wrap: anywhere; }
    .xp-onb-file-state { color: var(--ck-fg-3); white-space: nowrap; }
    .xp-onb-file[data-state='error'] .xp-onb-file-state { color: var(--ck-status-neg-fg); white-space: normal; text-align: right; }
    .xp-onb-counts { display: flex; flex-direction: column; gap: 12px; margin: 0; }
    .xp-onb-count { display: flex; justify-content: space-between; gap: 8px; margin: 0; font-size: 13px; }
    .xp-onb-count dt { color: var(--ck-fg-3); }
    .xp-onb-count dd { margin: 0; font-weight: 600; font-variant-numeric: tabular-nums; }
    /* Native progress bars take the tokens, not the browser's green. */
    .xp-onb-progress, .xp-onb-job ::ng-deep progress { appearance: none; width: 100%; height: 6px; border: 0; border-radius: 3px; background: var(--ck-stroke-2); overflow: hidden; }
    .xp-onb-progress::-webkit-progress-bar, .xp-onb-job ::ng-deep progress::-webkit-progress-bar { background: var(--ck-stroke-2); border-radius: 3px; }
    .xp-onb-progress::-webkit-progress-value, .xp-onb-job ::ng-deep progress::-webkit-progress-value { background: var(--ck-signal-cool); border-radius: 3px; }
    .xp-onb-progress::-moz-progress-bar, .xp-onb-job ::ng-deep progress::-moz-progress-bar { background: var(--ck-signal-cool); }
    .xp-onb-job { margin-top: 16px; }
    .xp-onb-question, .xp-onb-decision { margin-top: 20px; padding-top: 16px; border-top: 1px solid var(--ck-stroke-2); }
    .xp-onb-chat { height: 30rem; min-height: 22rem; margin-top: 8px; border: 1px solid var(--ck-stroke-2); border-radius: 8px; overflow: hidden; }
    .xp-onb-actions { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0; }
    .xp-onb-btn { display: inline-flex; align-items: center; min-height: 36px; padding: 0 12px; border: 1px solid var(--ck-stroke-3); border-radius: 4px; background: transparent; color: var(--ck-fg-1); font: 600 13px/1.2 var(--ck-font-sans); cursor: pointer; }
    .xp-onb-btn:hover:not(:disabled) { border-color: var(--ck-signal-cool); }
    .xp-onb-btn:disabled { opacity: .55; cursor: default; }
    .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
    .xp-onb-link { color: var(--ck-signal-cool); font-weight: 600; text-decoration: underline; text-underline-offset: 2px; }
    .xp-onb-choose { margin: 0; padding: 0; border: 0; min-width: 0; }
    .xp-onb-choose legend { padding: 0; margin-bottom: 12px; }
    .xp-onb-options { display: flex; flex-direction: column; gap: 8px; margin-bottom: 14px; }
    .xp-onb-option { display: flex; align-items: flex-start; gap: 10px; padding: 12px; border: 1px solid var(--ck-stroke-2); border-radius: 6px; cursor: pointer; }
    .xp-onb-option.is-selected { border-color: var(--ck-signal-cool); }
    .xp-onb-option input { margin-top: 3px; accent-color: var(--ck-signal-cool); }
    .xp-onb-option-text { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
    .xp-onb-option-name { font-weight: 600; }
    .xp-onb-proof { display: flex; flex-direction: column; gap: 12px; margin: 8px 0 0; padding: 0; list-style: none; }
    .xp-onb-proof li { display: flex; flex-direction: column; gap: 2px; padding-left: 12px; border-left: 2px solid var(--ck-stroke-3); }
    .xp-onb-proof-title { font-weight: 600; font-size: 14px; }
    .xp-onb-unavailable { max-width: 44rem; }
    :focus-visible { outline: 2px solid var(--ck-signal-cool); outline-offset: 2px; }
    @media (max-width: 1080px) {
      .xp-onb-layout { grid-template-columns: minmax(0, 1fr); }
      .xp-onb-steps { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 720px) {
      .xp-onb-steps, .xp-onb-docs { grid-template-columns: minmax(0, 1fr); }
    }
    @media (prefers-reduced-motion: reduce) {
      .xp-onb-file { transition: none; }
    }
  `],
})
export class ClientOnboardingComponent {
  readonly adoption = inject(AdoptionService);
  readonly i18n = inject(I18nService);
  private readonly api = inject(ApiService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly work = inject(WorkApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly destroyRef = inject(DestroyRef);
  readonly chat = viewChild(ChatPanelComponent);

  readonly steps: readonly ClientStep[] = CLIENT_STEPS;
  readonly proofs = ['source', 'citation', 'decision'] as const;

  readonly sources = computed<AdoptionSource[]>(() => this.adoption.progress()?.sources ?? []);
  readonly completed = computed(() => this.adoption.progress()?.completed_steps ?? []);
  /** The member is choosing (again) instead of working on a confirmed source. */
  readonly choosing = signal(false);
  readonly selectedId = signal<string | null>(null);
  /** The source the member confirmed, once the `source` step is recorded. */
  readonly confirmed = computed<AdoptionSource | null>(() => {
    if (this.choosing() || !this.completed().includes('source')) return null;
    return chosenSource(this.adoption.progress());
  });
  /** Effects follow the confirmed collection, not every refresh of its counts. */
  private readonly confirmedId = computed(() => this.confirmed()?.id ?? null);
  readonly states = computed(() =>
    clientStepStates(this.completed(), sourceHasDocuments(chosenSource(this.adoption.progress()))),
  );
  readonly doneCount = computed(() => this.completed().filter((s) => (CLIENT_STEPS as readonly string[]).includes(s)).length);
  readonly optionalDocuments = computed(() => {
    const src = this.confirmed();
    return !!src && sourceHasDocuments(src) && !this.completed().includes('documents');
  });

  readonly inventory = signal<CollectionInventory | null>(null);
  readonly inventoryError = signal(false);
  private readonly inventoryReload = signal(0);
  readonly summary = computed(() => ingestionSummary(this.inventory()));
  private readonly sortedFiles = computed(() =>
    [...(this.inventory()?.sources ?? [])].sort(
      (a, b) => FILE_ORDER[fileState(a.status)] - FILE_ORDER[fileState(b.status)] || a.filename.localeCompare(b.filename),
    ),
  );
  readonly files = computed(() => this.sortedFiles().slice(0, VISIBLE_FILES));
  readonly moreFiles = computed(() => Math.max(0, this.summary().total - this.files().length));
  /** The existing job panel, once this member sent documents or a job is not settled. */
  readonly showJobStatus = computed(() => this.uploadedHere() || (!!this.inventory() && !ingestionSettled(this.inventory())));

  readonly dragging = signal(false);
  readonly uploading = signal(false);
  readonly uploadError = signal(false);
  private readonly uploadedHere = signal(false);

  readonly contextId = signal<string | null>(null);
  readonly contextError = signal(false);
  private contextFor: string | null = null;

  /** An answer exists in this conversation (this visit or a resumed one). */
  readonly answeredNow = signal(false);
  readonly answered = computed(() => this.answeredNow() || this.completed().includes('question'));
  readonly decided = computed(() => this.completed().includes('decision'));
  readonly noAnswer = signal(false);
  readonly pendingDecision = signal<{ name: string; href: string } | null>(null);
  readonly announcement = signal('');
  private readonly number = computed(() => new Intl.NumberFormat(this.i18n.locale()));

  constructor() {
    // Preselect the member's earlier choice, else the first ready source.
    effect(() => {
      const src = chosenSource(this.adoption.progress());
      if (src && !untracked(this.selectedId)) this.selectedId.set(src.id);
    });

    // Collection inventory: per-file status and counts, polled until settled.
    effect((cleanup) => {
      const id = this.confirmedId();
      this.inventoryReload();
      const scope = this.workspace.captureRequestScope();
      untracked(() => this.inventoryError.set(false));
      if (!id) { untracked(() => this.inventory.set(null)); return; }
      let wasSettled: boolean | null = null;
      const subscription = timer(0, 4000).pipe(
        exhaustMap(() => this.api
          .get<CollectionInventory>(`/documents/collections/${encodeURIComponent(id)}/inventory`, { source_limit: '200' })
          .pipe(catchError(() => of(null)))),
        takeWhile((value) => !value || !ingestionSettled(value), true),
      ).subscribe((value) => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        if (!value) { this.inventoryError.set(!this.inventory()); return; }
        const before = this.inventory() ? ingestionSummary(this.inventory()) : null;
        this.inventory.set(value);
        this.inventoryError.set(false);
        const after = ingestionSummary(value);
        if (before && before.indexed !== after.indexed) {
          this.announcement.set(this.i18n.t('experience.work.onboarding.documents.progress', {
            indexed: this.format(after.indexed), total: this.format(after.total),
          }));
        }
        const settled = ingestionSettled(value);
        // Fresh counts for the step machine once indexing finishes.
        if (wasSettled === false && settled) this.adoption.load();
        wasSettled = settled;
      });
      cleanup(() => subscription.unsubscribe());
    });

    // A conversation grounded on the confirmed collection only.
    effect(() => {
      const id = this.confirmedId();
      if (!id) return;
      untracked(() => {
        if (this.contextFor === id) return;
        this.inventory.set(null);
        this.openContext();
      });
    });

    this.work.listExperiences().pipe(takeUntilDestroyed(this.destroyRef)).subscribe((result) => {
      if (result.kind !== 'ok') return;
      const item = result.items.find((entry) => (entry.pending_decisions?.count ?? 0) > 0);
      if (item) this.pendingDecision.set({ name: item.experience.name, href: workPageHref(item.experience.slug) });
    });
  }

  format(value: number): string {
    return this.number().format(value);
  }

  statusTone(src: AdoptionSource): 'ok' | 'info' | 'warn' | 'neutral' {
    if (src.status === 'ready') return src.document_count > 0 ? 'ok' : 'neutral';
    if (['queued', 'ingesting', 'embedding'].includes(src.status)) return 'info';
    if (src.status === 'error') return 'warn';
    return 'neutral';
  }

  statusLabel(src: AdoptionSource): string {
    const tone = this.statusTone(src);
    const key = tone === 'ok' ? 'ready' : tone === 'info' ? 'indexing' : tone === 'warn' ? 'error' : 'empty';
    return this.i18n.t(`experience.work.onboarding.source.status.${key}`);
  }

  stateOf(file: InventorySource): string {
    return fileState(file.status);
  }

  fileLabel(file: InventorySource): string {
    const state = fileState(file.status);
    if (state === 'indexed') {
      return this.i18n.t('experience.work.onboarding.documents.file.indexed', { n: this.format(file.chunk_count ?? 0) });
    }
    return this.i18n.t(`experience.work.onboarding.documents.file.${state}`);
  }

  useSource(): void {
    const id = this.selectedId();
    const src = this.sources().find((item) => item.id === id);
    if (!src) return;
    this.choosing.set(false);
    this.adoption.update({ completed_step: 'source', collection_id: src.id });
    this.announcement.set(this.i18n.t('experience.work.onboarding.announce.source', { source: src.name }));
  }

  changeSource(): void {
    this.selectedId.set(this.confirmed()?.id ?? null);
    this.choosing.set(true);
  }

  openContext(): void {
    const src = this.confirmed();
    const scope = this.workspace.captureRequestScope();
    if (!src || !scope.workspaceSlug) return;
    this.contextFor = src.id;
    this.contextId.set(null);
    this.contextError.set(false);
    this.canonical.createContext({
      name: this.i18n.t('experience.work.onboarding.question.context', { source: src.name }),
      data_refs: [],
      environment_state: { collection: src.slug },
      business_constraints: { source: 'client_onboarding', collection_id: src.id },
      ephemeral: true,
      ttl_hours: 24,
    }, { workspaceSlug: scope.workspaceSlug }).pipe(takeUntilDestroyed(this.destroyRef)).subscribe((context) => {
      if (!this.workspace.isRequestScopeCurrent(scope) || this.contextFor !== src.id) return;
      if (!context?.id || context.environment_state?.['collection'] !== src.slug) {
        this.contextError.set(true);
        return;
      }
      this.contextId.set(context.id);
    });
  }

  onDragOver(event: DragEvent): void {
    event.preventDefault();
    this.dragging.set(true);
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    this.dragging.set(false);
    const files = event.dataTransfer?.files;
    if (files?.length) this.upload(files);
  }

  onFileSelect(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files?.length) this.upload(input.files);
    input.value = '';
  }

  private upload(files: FileList): void {
    const src = this.confirmed();
    if (!src || this.uploading()) return;
    const count = files.length;
    const form = new FormData();
    Array.from(files).forEach((file) => form.append('files', file));
    const scope = this.workspace.captureRequestScope();
    this.uploading.set(true);
    this.uploadError.set(false);
    this.announcement.set(this.i18n.t('experience.work.onboarding.documents.uploading', { n: this.format(count) }));
    this.api.post(`/documents/collections/${encodeURIComponent(src.id)}/documents`, form, { workspaceSlug: scope.workspaceSlug })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          if (!this.workspace.isRequestScopeCurrent(scope)) return;
          this.uploading.set(false);
          this.uploadedHere.set(true);
          this.announcement.set(this.i18n.t('experience.work.onboarding.documents.uploaded', { n: this.format(count) }));
          if (!this.completed().includes('documents')) this.adoption.update({ completed_step: 'documents' });
          this.inventoryReload.update((value) => value + 1);
        },
        error: () => {
          if (!this.workspace.isRequestScopeCurrent(scope)) return;
          this.uploading.set(false);
          this.uploadError.set(true);
        },
      });
  }

  onChat(event: { step: 'question' | 'source' | 'answer' | 'decision'; sessionId?: string }): void {
    if (event.step === 'answer') {
      this.answeredNow.set(true);
      this.noAnswer.set(false);
      if (!this.completed().includes('question') || (event.sessionId && event.sessionId !== this.adoption.progress()?.session_id)) {
        this.adoption.update({ completed_step: 'question', ...(event.sessionId ? { session_id: event.sessionId } : {}) });
      }
    } else if (event.step === 'decision') {
      // Emitted only once the feedback or the correction was saved.
      this.adoption.recordDecision();
      this.announcement.set(this.i18n.t('experience.work.onboarding.decision.done'));
    }
  }

  decide(verdict: 'up' | 'down'): void {
    const ok = this.chat()?.rateLatestAnswer(verdict) ?? false;
    this.noAnswer.set(!ok);
  }

  correct(): void {
    const ok = this.chat()?.correctLatestAnswer() ?? false;
    this.noAnswer.set(!ok);
  }
}
