import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  OnInit,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { catchError, map, of } from 'rxjs';
import { ApiService } from '@app/core/api.service';

interface MeetingAgendaItem {
  id?: string;
  title: string;
  order?: number;
  priority?: string;
  owner_proposer?: string;
  decision_required?: boolean;
  source?: string;
  source_label?: string;
  options?: MeetingDecisionOption[];
  notes?: string;
}

interface MeetingDecisionOption {
  id: string;
  label: string;
  summary?: string;
  recommended?: boolean;
}

interface MeetingEvent {
  id: string;
  title: string;
  start_at?: string;
  end_at?: string;
  participants?: string[];
  location?: string;
  description?: string;
  metadata?: {
    agenda_items?: MeetingAgendaItem[];
    workspace?: string;
    [key: string]: unknown;
  };
}

interface MeetingDecision {
  id?: string;
  agenda_item_ref?: string;
  chosen_option?: string;
  options_offered?: MeetingDecisionOption[];
  rationale?: string;
  decided_at?: string;
  decided_by?: string;
  status?: string;
}

interface PendingAgendaPatch {
  event_id?: string;
  agenda_items?: MeetingAgendaItem[];
  proposed_at?: string;
  proposed_via?: string;
}

interface MeetingPayload {
  event?: MeetingEvent | null;
  agenda_items?: MeetingAgendaItem[];
  decisions?: MeetingDecision[];
  pending_agenda_patch?: PendingAgendaPatch | null;
}

@Component({
  selector: 'app-vp-meeting',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="vp-meeting-shell" aria-label="Mode meeting live">
      <header class="vp-meeting-header">
        <div class="meeting-title">
          <span class="eyebrow">Réunion live · arbitrages</span>
          <h1>{{ event()?.title || 'Réunion en préparation' }}</h1>
          <p>
            {{ participantsLabel() }} ·
            <time>{{ scheduleLabel() }}</time>
          </p>
        </div>
        <div class="meeting-chrono">
          <strong>{{ chronoLabel() }}</strong>
          <small>chrono live</small>
        </div>
        <a class="ghost-link" routerLink="/hypervisor/mission-room/agenda">
          Retour agenda
        </a>
      </header>

      @if (loading()) {
        <div class="meeting-loading">
          <span class="dots"></span>
          <strong>Chargement de la réunion…</strong>
        </div>
      } @else {
        <main class="meeting-main">
          @if (pendingPatch(); as pending) {
            <aside class="pending-patch-banner" aria-label="Modification ODJ proposee par AYA">
              <div class="pending-patch-copy">
                <span class="eyebrow">Modification ODJ proposee · AYA</span>
                <strong>{{ pendingPatchTitle(pending) }}</strong>
                <p>
                  {{ pending.agenda_items?.length || 0 }} point(s) en attente de validation. Validez ou
                  rejetez avant le demarrage de la reunion.
                </p>
              </div>
              <div class="pending-patch-actions">
                <button
                  type="button"
                  class="action-button primary"
                  [disabled]="patchSubmitting()"
                  (click)="confirmPendingPatch()"
                >
                  Valider modification
                </button>
                <button
                  type="button"
                  class="action-button ghost"
                  [disabled]="patchSubmitting()"
                  (click)="rejectPendingPatch()"
                >
                  Rejeter
                </button>
              </div>
            </aside>
          }

          <section class="agenda-propose" aria-label="Proposer un point ODJ">
            <header>
              <span class="eyebrow">Proposer un point ODJ</span>
              <small>Memes effets que la voix « AYA, ajoute le point ... »</small>
            </header>
            <div class="agenda-propose-row">
              <input
                type="text"
                [(ngModel)]="proposeAgendaTitle"
                placeholder="Ex. Point cacao - diversification anacarde"
                aria-label="Intitule du point a ajouter"
              />
              <button
                type="button"
                class="action-button"
                [disabled]="!proposeAgendaTitle.trim() || patchSubmitting()"
                (click)="proposeAgendaPatch()"
              >
                Proposer modification
              </button>
            </div>
          </section>

          <ol class="agenda-list" aria-label="Ordre du jour">
            @for (item of agendaItems(); track item.id || item.title; let idx = $index) {
              <li
                class="agenda-item"
                [class.active]="activeIndex() === idx"
                [class.decided]="isItemDecided(item)"
              >
                <button type="button" class="agenda-item-head" (click)="setActiveIndex(idx)">
                  <span class="agenda-rank">{{ idx + 1 }}</span>
                  <div class="agenda-copy">
                    <strong>{{ item.title }}</strong>
                    <small>
                      {{ item.owner_proposer || 'Cabinet' }}
                      @if (item.decision_required) {
                        · décision requise
                      }
                    </small>
                  </div>
                  @if (decisionForItem(item); as decision) {
                    <span class="decision-badge">
                      Option {{ optionShortLabel(decision.chosen_option) }}
                    </span>
                  } @else if (item.decision_required) {
                    <span class="pending-badge">à arbitrer</span>
                  }
                </button>

                @if (activeIndex() === idx && item.decision_required) {
                  <div class="agenda-item-body">
                    <p class="agenda-item-prompt">
                      Choisissez une option pour ce point. La décision sera loggée comme advisory dans l'historique d'arbitrage.
                    </p>
                    <div class="options-grid">
                      @for (option of itemOptions(item); track option.id) {
                        <button
                          type="button"
                          class="option-card"
                          [class.recommended]="option.recommended"
                          [class.selected]="pendingOptionId() === option.id"
                          (click)="selectPendingOption(option.id)"
                        >
                          <span class="option-id">{{ option.id }}</span>
                          <strong>{{ option.label }}</strong>
                          @if (option.summary) {
                            <p>{{ option.summary }}</p>
                          }
                          @if (option.recommended) {
                            <small class="reco-pill">recommandée</small>
                          }
                        </button>
                      }
                    </div>
                    <button
                      type="button"
                      class="decide-button"
                      [disabled]="!pendingOptionId() || submitting()"
                      (click)="openDecideModal(item)"
                    >
                      Décider
                    </button>
                  </div>
                }
              </li>
            }
            @if (!agendaItems().length) {
              <li class="agenda-empty">
                Aucun point d'ordre du jour structuré. Ajoutez des points depuis la vue Agenda.
              </li>
            }
          </ol>
        </main>

        <footer class="meeting-footer" aria-label="Récapitulatif arbitrages">
          <span class="counter">
            <strong>{{ decisions().length }}</strong>
            <small>arbitrage{{ decisions().length > 1 ? 's' : '' }} loggé{{ decisions().length > 1 ? 's' : '' }}</small>
            <span aria-hidden="true" class="counter-sep">·</span>
            <strong>{{ remainingCount() }}</strong>
            <small>restant{{ remainingCount() > 1 ? 's' : '' }}</small>
          </span>
          <button type="button" class="ghost-link" (click)="refresh()">Rafraîchir</button>
        </footer>
      }

      @if (decideModalOpen()) {
        <div class="modal-backdrop" (click)="closeDecideModal()" aria-hidden="true"></div>
        <aside class="decide-modal" role="dialog" aria-label="Confirmer décision">
          <header>
            <span class="eyebrow">Confirmer décision</span>
            <h3>{{ pendingItem()?.title }}</h3>
          </header>
          <p class="modal-line">
            Option choisie : <strong>{{ pendingOptionLabel() }}</strong>
          </p>
          <label class="modal-field">
            <span>Justification courte (rationale)</span>
            <textarea
              rows="3"
              [(ngModel)]="rationaleText"
              placeholder="Pourquoi cette option ? Sources, contraintes, alternatives écartées…"
            ></textarea>
          </label>
          <footer>
            <button type="button" class="action-button primary" [disabled]="submitting()" (click)="confirmDecision()">
              Logger la décision
            </button>
            <button type="button" class="action-button ghost" (click)="closeDecideModal()">
              Annuler
            </button>
          </footer>
        </aside>
      }
    </section>
  `,
  styles: [
    `
      :host {
        display: block;
        min-height: 100vh;
        background: var(--mission-bg, rgba(2, 6, 10, 0.96));
        color: var(--mission-text-primary);
        font-family: var(--mission-font-body);
      }
      .vp-meeting-shell {
        max-width: 980px;
        margin: 0 auto;
        padding: var(--mission-space-6) var(--mission-space-5) var(--mission-space-8);
        display: grid;
        gap: var(--mission-space-5);
      }
      .vp-meeting-header {
        position: sticky;
        top: 0;
        z-index: 4;
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto auto;
        gap: var(--mission-space-4);
        align-items: center;
        padding: var(--mission-space-4) var(--mission-space-5);
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-md);
        background: rgba(5, 8, 12, 0.92);
        backdrop-filter: blur(6px);
        -webkit-backdrop-filter: blur(6px);
        box-shadow: var(--mission-shadow-soft);
      }
      .meeting-title h1 {
        margin: var(--mission-space-1) 0;
        font-size: var(--mission-text-lg);
        font-weight: 600;
        letter-spacing: var(--mission-tracking-tight);
        line-height: var(--mission-lh-tight);
      }
      .meeting-title p {
        margin: 0;
        color: var(--mission-text-tertiary);
        font-size: var(--mission-text-xs);
      }
      .eyebrow {
        display: block;
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: var(--mission-tracking-micro);
        text-transform: uppercase;
      }
      .meeting-chrono { text-align: right; }
      .meeting-chrono strong {
        font-family: var(--mission-font-mono);
        font-variant-numeric: tabular-nums;
        font-size: var(--mission-text-lg);
        font-weight: 600;
        line-height: 1;
        color: var(--mission-warning);
      }
      .meeting-chrono small {
        display: block;
        margin-top: var(--mission-space-1);
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
      .ghost-link {
        display: inline-flex;
        padding: 6px var(--mission-space-3);
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: transparent;
        color: var(--mission-text-primary);
        font: inherit;
        font-size: var(--mission-text-xs);
        cursor: pointer;
        text-decoration: none;
        transition: border-color var(--mission-dur-fast) var(--mission-ease-out);
      }
      .ghost-link:hover { border-color: var(--sentinel-accent-muted); }
      .ghost-link:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }
      .meeting-loading {
        display: grid;
        place-items: center;
        gap: var(--mission-space-3);
        padding: var(--mission-space-12) var(--mission-space-5);
        color: var(--mission-text-tertiary);
      }
      .dots {
        width: 32px;
        height: 6px;
        border-radius: 999px;
        background: linear-gradient(90deg, transparent, var(--sentinel-accent), transparent);
        animation: dots 1.4s infinite;
      }
      @keyframes dots {
        0% { transform: translateX(-12px); opacity: 0.4; }
        50% { transform: translateX(0); opacity: 1; }
        100% { transform: translateX(12px); opacity: 0.4; }
      }
      .meeting-main {
        display: grid;
        gap: var(--mission-space-3);
      }
      .pending-patch-banner {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: var(--mission-space-3);
        align-items: center;
        padding: var(--mission-space-3) var(--mission-space-4);
        border: 1px solid rgba(242, 140, 56, 0.42);
        border-radius: var(--mission-radius-md);
        background: var(--agentium-aya-soft, rgba(242, 140, 56, 0.08));
      }
      .pending-patch-copy strong {
        display: block;
        margin-top: var(--mission-space-1);
        font-size: var(--mission-text-base);
        font-weight: 600;
        letter-spacing: var(--mission-tracking-tight);
        color: var(--mission-text-primary);
      }
      .pending-patch-copy p {
        margin: var(--mission-space-1) 0 0;
        color: var(--mission-text-secondary);
        font-size: var(--mission-text-xs);
        line-height: var(--mission-lh-body);
      }
      .pending-patch-actions {
        display: flex;
        flex-direction: column;
        gap: var(--mission-space-2);
        min-width: 180px;
      }
      .agenda-propose {
        display: grid;
        gap: var(--mission-space-2);
        padding: var(--mission-space-3) var(--mission-space-4);
        border: 1px dashed var(--mission-border);
        border-radius: var(--mission-radius-md);
        background: rgba(4, 8, 13, 0.32);
      }
      .agenda-propose header { display: grid; gap: 2px; }
      .agenda-propose header small {
        color: var(--mission-text-tertiary);
        font-size: var(--mission-text-xs);
      }
      .agenda-propose-row {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: var(--mission-space-2);
        align-items: center;
      }
      .agenda-propose input {
        padding: 8px var(--mission-space-3);
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: var(--mission-inset);
        color: inherit;
        font: inherit;
        font-size: var(--mission-text-sm);
      }
      .agenda-propose input:focus {
        outline: none;
        border-color: var(--sentinel-accent);
        box-shadow: 0 0 0 1px var(--sentinel-accent);
      }
      .agenda-list {
        margin: 0;
        padding: 0;
        list-style: none;
        display: grid;
        gap: var(--mission-space-2);
      }
      .agenda-item {
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-md);
        background: rgba(4, 8, 13, 0.42);
        overflow: hidden;
        transition: border-color var(--mission-dur-fast) var(--mission-ease-out);
      }
      .agenda-item.active {
        border-color: var(--sentinel-accent);
        background: var(--sentinel-accent-soft);
        box-shadow: inset 3px 0 0 0 var(--sentinel-accent);
      }
      .agenda-item.decided {
        opacity: 0.55;
      }
      .agenda-item.decided .agenda-copy strong { text-decoration: line-through; }
      .agenda-item-head {
        width: 100%;
        display: grid;
        grid-template-columns: 32px minmax(0, 1fr) auto;
        align-items: center;
        gap: var(--mission-space-3);
        padding: var(--mission-space-3) var(--mission-space-4);
        border: none;
        background: transparent;
        color: inherit;
        text-align: left;
        font: inherit;
        cursor: pointer;
      }
      .agenda-item-head:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: -2px;
      }
      .agenda-rank {
        display: inline-flex;
        width: 28px;
        height: 28px;
        align-items: center;
        justify-content: center;
        border-radius: 999px;
        border: 1px solid var(--mission-border);
        font-family: var(--mission-font-mono);
        font-variant-numeric: tabular-nums;
        font-size: var(--mission-text-xs);
        color: var(--mission-text-secondary);
      }
      .agenda-item.active .agenda-rank {
        border-color: var(--sentinel-accent);
        color: var(--sentinel-accent-strong);
        background: var(--sentinel-accent-soft);
      }
      .agenda-copy strong {
        display: block;
        font-size: var(--mission-text-base);
        font-weight: 600;
        letter-spacing: var(--mission-tracking-tight);
        line-height: 1.3;
        color: var(--mission-text-primary);
      }
      .agenda-copy small {
        color: var(--mission-text-tertiary);
        font-size: var(--mission-text-xs);
      }
      .decision-badge {
        padding: 4px 9px;
        border-radius: 999px;
        border: 1px solid rgba(101, 214, 110, 0.32);
        background: var(--mission-success-soft);
        color: var(--mission-success);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.06em;
        text-transform: uppercase;
      }
      .pending-badge {
        padding: 4px 9px;
        border-radius: 999px;
        border: 1px solid rgba(241, 180, 90, 0.32);
        background: var(--mission-warning-soft);
        color: var(--mission-warning);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.06em;
        text-transform: uppercase;
      }
      .agenda-item-body {
        padding: 0 var(--mission-space-4) var(--mission-space-4);
        display: grid;
        gap: var(--mission-space-3);
      }
      .agenda-item-prompt {
        margin: var(--mission-space-2) 0 0;
        color: var(--mission-text-secondary);
        font-size: var(--mission-text-xs);
        line-height: var(--mission-lh-body);
      }
      .options-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: var(--mission-space-3);
      }
      .option-card {
        position: relative;
        padding: var(--mission-space-3);
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-md);
        background: rgba(4, 8, 13, 0.58);
        color: inherit;
        text-align: left;
        cursor: pointer;
        appearance: none;
        font: inherit;
        transition:
          border-color var(--mission-dur-fast) var(--mission-ease-out),
          background var(--mission-dur-fast) var(--mission-ease-out),
          transform var(--mission-dur-fast) var(--mission-ease-out);
      }
      .option-card:hover {
        border-color: var(--sentinel-accent-muted);
      }
      .option-card:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }
      .option-card.recommended {
        border-color: rgba(101, 214, 110, 0.32);
      }
      .option-card.selected {
        border-color: var(--sentinel-accent);
        background: var(--sentinel-accent-soft);
        box-shadow: 0 0 0 1px rgba(101, 214, 110, 0.32);
      }
      .option-id {
        color: var(--sentinel-accent);
        font-family: var(--mission-font-mono);
        font-size: var(--mission-text-xs);
        font-weight: 700;
        letter-spacing: 0.08em;
      }
      .option-card strong {
        display: block;
        margin-top: var(--mission-space-1);
        font-size: var(--mission-text-sm);
        font-weight: 600;
        line-height: 1.3;
        color: var(--mission-text-primary);
      }
      .option-card p {
        margin: var(--mission-space-2) 0 0;
        color: var(--mission-text-secondary);
        font-size: var(--mission-text-xs);
        line-height: var(--mission-lh-body);
      }
      .reco-pill {
        position: absolute;
        top: var(--mission-space-2);
        right: var(--mission-space-2);
        padding: 2px 7px;
        border-radius: 999px;
        border: 1px solid rgba(101, 214, 110, 0.32);
        background: var(--mission-success-soft);
        color: var(--mission-success);
        font-family: var(--mission-font-mono);
        font-size: 9px;
        letter-spacing: 0.06em;
        text-transform: uppercase;
      }
      .decide-button {
        justify-self: end;
        padding: 9px var(--mission-space-4);
        border: 1px solid rgba(101, 214, 110, 0.42);
        border-radius: var(--mission-radius-sm);
        background: var(--sentinel-accent-soft);
        color: var(--sentinel-accent-strong);
        cursor: pointer;
        font: inherit;
        font-size: var(--mission-text-sm);
        font-weight: 600;
        letter-spacing: 0.04em;
        transition: background var(--mission-dur-fast) var(--mission-ease-out);
      }
      .decide-button:hover:not(:disabled) {
        background: rgba(101, 214, 110, 0.18);
      }
      .decide-button:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }
      .decide-button:disabled { opacity: 0.4; cursor: not-allowed; }
      .agenda-empty {
        padding: var(--mission-space-6);
        border: 1px dashed var(--mission-border);
        border-radius: var(--mission-radius-md);
        color: var(--mission-text-secondary);
        text-align: center;
        font-size: var(--mission-text-sm);
      }
      .meeting-footer {
        position: sticky;
        bottom: 0;
        z-index: 3;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--mission-space-3);
        padding: var(--mission-space-3) var(--mission-space-4);
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-md);
        background: rgba(5, 8, 12, 0.92);
        backdrop-filter: blur(6px);
        -webkit-backdrop-filter: blur(6px);
      }
      .counter strong {
        font-family: var(--mission-font-mono);
        font-size: var(--mission-text-lg);
        font-variant-numeric: tabular-nums;
        font-weight: 600;
        color: var(--mission-text-primary);
      }
      .counter small {
        margin-left: 6px;
        color: var(--mission-text-tertiary);
        font-size: var(--mission-text-xs);
      }
      .counter-sep {
        margin: 0 8px;
        color: var(--mission-text-disabled);
      }
      .modal-backdrop {
        position: fixed;
        inset: 0;
        background: rgba(2, 6, 10, 0.55);
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        z-index: 1200;
        animation: backdrop-in var(--mission-dur-base) var(--mission-ease-out);
      }
      @keyframes backdrop-in {
        from { opacity: 0; }
        to   { opacity: 1; }
      }
      .decide-modal {
        position: fixed;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        z-index: 1201;
        width: min(560px, 94vw);
        padding: var(--mission-space-6);
        border: 1px solid rgba(101, 214, 110, 0.28);
        border-radius: var(--mission-radius-lg);
        background: rgba(5, 8, 12, 0.98);
        display: grid;
        gap: var(--mission-space-3);
        box-shadow: var(--mission-shadow-floating);
        animation: modal-in var(--mission-dur-base) var(--mission-ease-out);
      }
      @keyframes modal-in {
        from { opacity: 0; transform: translate(-50%, -48%) scale(0.97); }
        to   { opacity: 1; transform: translate(-50%, -50%) scale(1); }
      }
      .decide-modal h3 {
        margin: var(--mission-space-1) 0 0;
        font-size: var(--mission-text-md);
        font-weight: 600;
        letter-spacing: var(--mission-tracking-tight);
      }
      .modal-line {
        margin: 0;
        color: var(--mission-text-secondary);
        font-size: var(--mission-text-sm);
      }
      .modal-line strong { color: var(--mission-text-primary); }
      .modal-field { display: grid; gap: 6px; }
      .modal-field span {
        color: var(--mission-text-tertiary);
        font-family: var(--mission-font-mono);
        font-size: 10px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
      }
      .modal-field textarea {
        border: 1px solid var(--mission-border);
        background: var(--mission-inset);
        color: inherit;
        border-radius: var(--mission-radius-sm);
        padding: var(--mission-space-3);
        font: inherit;
        font-size: var(--mission-text-sm);
        min-height: 100px;
        resize: vertical;
        transition: border-color var(--mission-dur-fast) var(--mission-ease-out);
      }
      .modal-field textarea:focus {
        outline: none;
        border-color: var(--sentinel-accent);
        box-shadow: 0 0 0 1px var(--sentinel-accent);
      }
      .decide-modal footer {
        display: flex;
        justify-content: flex-end;
        gap: var(--mission-space-2);
      }
      .action-button {
        min-height: 36px;
        padding: 8px var(--mission-space-4);
        border: 1px solid var(--mission-border);
        border-radius: var(--mission-radius-sm);
        background: var(--mission-inset);
        color: inherit;
        font: inherit;
        font-size: var(--mission-text-sm);
        cursor: pointer;
        transition: border-color var(--mission-dur-fast) var(--mission-ease-out);
      }
      .action-button:hover { border-color: var(--sentinel-accent-muted); }
      .action-button:focus-visible {
        outline: 2px solid var(--sentinel-accent);
        outline-offset: 2px;
      }
      .action-button.primary {
        border-color: rgba(101, 214, 110, 0.45);
        background: var(--sentinel-accent-soft);
        color: var(--sentinel-accent-strong);
        font-weight: 600;
      }
      .action-button.primary:hover { background: rgba(101, 214, 110, 0.18); }
      .action-button.ghost { background: transparent; }
      .action-button:disabled { opacity: 0.5; cursor: not-allowed; }
      @media (max-width: 760px) {
        .vp-meeting-header {
          grid-template-columns: 1fr;
          text-align: left;
        }
        .meeting-chrono { text-align: left; }
        .options-grid { grid-template-columns: 1fr; }
      }
      @media (prefers-reduced-motion: reduce) {
        .modal-backdrop,
        .decide-modal,
        .dots { animation: none !important; }
      }
    `,
  ],
})
export class VpMeetingComponent implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  private readonly route = inject(ActivatedRoute);

  private readonly eventIdParam = toSignal(
    this.route.paramMap.pipe(map((params) => params.get('event_id') || '')),
    { initialValue: '' },
  );

  readonly loading = signal(true);
  readonly event = signal<MeetingEvent | null>(null);
  readonly agendaItems = signal<MeetingAgendaItem[]>([]);
  readonly decisions = signal<MeetingDecision[]>([]);
  readonly activeIndex = signal<number>(0);
  readonly pendingOptionId = signal<string | null>(null);
  readonly pendingItem = signal<MeetingAgendaItem | null>(null);
  readonly decideModalOpen = signal(false);
  readonly submitting = signal(false);
  readonly pendingPatch = signal<PendingAgendaPatch | null>(null);
  readonly patchSubmitting = signal(false);

  rationaleText = '';
  proposeAgendaTitle = '';

  private chronoTick = signal(0);
  private chronoTimer: ReturnType<typeof setInterval> | null = null;

  ngOnInit(): void {
    this.chronoTimer = setInterval(() => this.chronoTick.update((v) => v + 1), 1000);
    this.refresh();
  }

  ngOnDestroy(): void {
    if (this.chronoTimer) clearInterval(this.chronoTimer);
  }

  refresh(): void {
    const eventId = this.eventIdParam();
    if (!eventId) {
      this.loading.set(false);
      return;
    }
    this.loading.set(true);
    this.api
      .get<MeetingPayload>(`/meetings/${eventId}`)
      .pipe(catchError(() => of<MeetingPayload | null>(null)))
      .subscribe((payload) => {
        this.applyPayload(payload, eventId);
        this.loading.set(false);
      });
  }

  participantsLabel(): string {
    const list = this.event()?.participants || [];
    if (!list.length) return 'Cabinet · participants à confirmer';
    return list.join(', ');
  }

  scheduleLabel(): string {
    const event = this.event();
    if (!event?.start_at) return 'horaire à confirmer';
    const start = new Date(event.start_at);
    const end = event.end_at ? new Date(event.end_at) : null;
    const formatter = new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium', timeStyle: 'short' });
    return end
      ? `${formatter.format(start)} → ${new Intl.DateTimeFormat('fr-FR', { timeStyle: 'short' }).format(end)}`
      : formatter.format(start);
  }

  chronoLabel(): string {
    this.chronoTick();
    const event = this.event();
    if (!event?.start_at) return '--:--';
    const start = new Date(event.start_at).getTime();
    if (!start) return '--:--';
    const elapsedMs = Math.max(0, Date.now() - start);
    const totalSeconds = Math.floor(elapsedMs / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    const pad = (n: number) => String(n).padStart(2, '0');
    return hours > 0 ? `${pad(hours)}:${pad(minutes)}:${pad(seconds)}` : `${pad(minutes)}:${pad(seconds)}`;
  }

  setActiveIndex(index: number): void {
    this.activeIndex.set(index);
    this.pendingOptionId.set(null);
  }

  selectPendingOption(optionId: string): void {
    this.pendingOptionId.set(optionId);
  }

  decisionForItem(item: MeetingAgendaItem): MeetingDecision | null {
    const ref = item.id || item.title;
    return this.decisions().find((decision) => (decision.agenda_item_ref || '') === ref) || null;
  }

  isItemDecided(item: MeetingAgendaItem): boolean {
    return !!this.decisionForItem(item);
  }

  remainingCount(): number {
    const items = this.agendaItems();
    return items.reduce((acc, item) => acc + (item.decision_required && !this.isItemDecided(item) ? 1 : 0), 0);
  }

  itemOptions(item: MeetingAgendaItem): MeetingDecisionOption[] {
    if (item.options?.length) return item.options;
    return [
      { id: 'A', label: 'Option A · statu quo', summary: 'Ne pas trancher maintenant, ré-arbitrer après collecte d\'éléments.' },
      { id: 'B', label: 'Option B · arbitrage cabinet', summary: 'Décision cabinet avec instructions advisory et calendrier de mise en œuvre.', recommended: true },
      { id: 'C', label: 'Option C · délégation', summary: 'Déléguer la décision opérationnelle au cabinet sectoriel.' },
    ];
  }

  optionShortLabel(value?: string): string {
    if (!value) return '—';
    return value.split(/[·\-:]/)[0].trim().slice(0, 2).toUpperCase();
  }

  openDecideModal(item: MeetingAgendaItem): void {
    if (!this.pendingOptionId()) return;
    this.pendingItem.set(item);
    this.rationaleText = '';
    this.decideModalOpen.set(true);
  }

  closeDecideModal(): void {
    this.decideModalOpen.set(false);
    this.pendingItem.set(null);
  }

  pendingOptionLabel(): string {
    const item = this.pendingItem();
    const id = this.pendingOptionId();
    if (!item || !id) return '';
    const option = this.itemOptions(item).find((entry) => entry.id === id);
    return option ? `${option.id} · ${option.label}` : id;
  }

  confirmDecision(): void {
    const event = this.event();
    const item = this.pendingItem();
    const optionId = this.pendingOptionId();
    if (!event?.id || !item || !optionId) return;
    this.submitting.set(true);
    const options = this.itemOptions(item);
    const payload = {
      agenda_item_ref: item.id || item.title,
      chosen_option: optionId,
      options_offered: options,
      rationale: this.rationaleText.trim() || `Décision advisory option ${optionId}.`,
    };
    this.api
      .post<MeetingDecision>(`/meetings/${event.id}/decisions`, payload)
      .pipe(catchError(() => of<MeetingDecision | null>(null)))
      .subscribe((decision) => {
        this.submitting.set(false);
        this.closeDecideModal();
        if (!decision) {
          this.recordLocalDecision(item, optionId, options, payload.rationale);
          return;
        }
        this.decisions.update((list) => [...list, decision]);
        this.pendingOptionId.set(null);
        const nextIndex = Math.min(this.activeIndex() + 1, this.agendaItems().length - 1);
        this.activeIndex.set(nextIndex);
      });
  }

  private recordLocalDecision(
    item: MeetingAgendaItem,
    optionId: string,
    options: MeetingDecisionOption[],
    rationale: string,
  ): void {
    const fallback: MeetingDecision = {
      id: `local-${Date.now()}`,
      agenda_item_ref: item.id || item.title,
      chosen_option: optionId,
      options_offered: options,
      rationale,
      decided_at: new Date().toISOString(),
      status: 'logged_local',
    };
    this.decisions.update((list) => [...list, fallback]);
    this.pendingOptionId.set(null);
    const nextIndex = Math.min(this.activeIndex() + 1, this.agendaItems().length - 1);
    this.activeIndex.set(nextIndex);
  }

  private applyPayload(payload: MeetingPayload | null, eventId: string): void {
    if (!payload || !payload.event) {
      this.event.set({
        id: eventId,
        title: 'Réunion (fallback)',
        start_at: new Date().toISOString(),
        participants: ['Cabinet'],
        metadata: { agenda_items: [] },
      });
      this.agendaItems.set([]);
      this.decisions.set([]);
      this.activeIndex.set(0);
      this.pendingPatch.set(null);
      return;
    }
    this.event.set(payload.event);
    const items = payload.agenda_items || payload.event.metadata?.agenda_items || [];
    const decisions = payload.decisions || [];
    this.agendaItems.set(items);
    this.decisions.set(decisions);
    this.pendingPatch.set(payload.pending_agenda_patch ?? null);
    if (items.length) {
      const firstUndecided = items.findIndex(
        (item) =>
          item.decision_required
          && !decisions.some((decision) => (decision.agenda_item_ref || '') === (item.id || item.title)),
      );
      this.activeIndex.set(firstUndecided >= 0 ? firstUndecided : 0);
    }
  }

  pendingPatchTitle(pending: PendingAgendaPatch): string {
    const items = pending.agenda_items || [];
    const first = items[0];
    if (!first) return 'Nouvelle modification ODJ';
    const more = items.length > 1 ? ` (+${items.length - 1})` : '';
    return `${first.title || 'Point sans titre'}${more}`;
  }

  proposeAgendaPatch(): void {
    const eventId = this.event()?.id;
    const title = this.proposeAgendaTitle.trim();
    if (!eventId || !title || this.patchSubmitting()) return;
    this.patchSubmitting.set(true);
    const slug = title
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/(^-|-$)/g, '')
      .slice(0, 40) || `point-${Date.now()}`;
    const item = {
      id: `agenda-${slug}`,
      title,
      order: this.agendaItems().length + 1,
      priority: 'high',
      owner_proposer: 'VP',
      decision_required: true,
      source: 'vp',
      source_label: 'Ajouté par VP (clic)',
    };
    this.api
      .post<{ pending_agenda_patch?: PendingAgendaPatch | null }>(
        `/meetings/${eventId}/agenda-patch`,
        { agenda_items: [item] },
      )
      .pipe(catchError(() => of<{ pending_agenda_patch?: PendingAgendaPatch | null } | null>(null)))
      .subscribe((response) => {
        this.patchSubmitting.set(false);
        this.proposeAgendaTitle = '';
        if (response?.pending_agenda_patch) {
          this.pendingPatch.set(response.pending_agenda_patch);
        }
      });
  }

  confirmPendingPatch(): void {
    const eventId = this.event()?.id;
    if (!eventId || this.patchSubmitting()) return;
    this.patchSubmitting.set(true);
    this.api
      .post<MeetingPayload>(`/meetings/${eventId}/agenda-patch/confirm`, {})
      .pipe(catchError(() => of<MeetingPayload | null>(null)))
      .subscribe((payload) => {
        this.patchSubmitting.set(false);
        if (payload?.event) {
          this.event.set(payload.event);
          this.agendaItems.set(
            payload.agenda_items || payload.event.metadata?.agenda_items || [],
          );
          this.pendingPatch.set(null);
        } else {
          this.refresh();
        }
      });
  }

  rejectPendingPatch(): void {
    // Local-only dismiss for the demo: the pending patch sits in workspace
    // settings; clearing the banner avoids confusion without re-PATCH plumbing.
    this.pendingPatch.set(null);
  }
}
