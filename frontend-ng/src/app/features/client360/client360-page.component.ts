import { NgClass } from '@angular/common';
import { HttpClient, HttpParams } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { GlyphComponent, PageFrameComponent } from '@app/shared/cockpit';

type ViewKey = 'opportunities' | 'customer' | 'data' | 'mapping' | 'mail';

interface Client360DataSource {
  id: string;
  origin: string;
  source_type: string;
  label: string;
  filename?: string | null;
  collection_slug?: string | null;
  status: string;
  error?: string | null;
  metadata?: Record<string, unknown>;
}

interface Client360Opportunity {
  id: string;
  customer_key: string;
  customer_name: string;
  site_name?: string | null;
  country?: string | null;
  hub?: string | null;
  technology?: string | null;
  line_label?: string | null;
  machine_label?: string | null;
  part_family: string;
  part_reference?: string | null;
  part_description?: string | null;
  installed_quantity?: number | null;
  recommended_quantity?: number | null;
  periodicity_weeks?: number | null;
  delivery_time_weeks?: number | null;
  annual_theoretical_qty?: number | null;
  potential_theoretical?: number | null;
  potential_addressable?: number | null;
  potential_gap_qty?: number | null;
  potential_gap_value?: number | null;
  potential_unit: string;
  currency?: string | null;
  sales_known_qty?: number | null;
  sales_known_value?: number | null;
  next_due_at?: string | null;
  confidence_score?: number | null;
  confidence_label: string;
  score_reasons: Array<{ code: string; label: string; weight: number; met: boolean }>;
  recommended_action?: string | null;
  status: string;
  data_gaps: string[];
  evidence_refs: Array<Record<string, unknown>>;
}

interface Client360Summary {
  workspace: { id: string; slug: string; name: string };
  positioning: Record<string, unknown>;
  summary: {
    opportunities: number;
    customers: number;
    data_sources: number;
    mapping_rules: number;
    potential_theoretical: number;
    potential_gap_qty: number;
    potential_unit: string;
    mail_drafts: number;
    impact_events: number;
  };
  by_status: Record<string, number>;
  by_confidence: Record<string, number>;
  source_counts: Record<string, number>;
  data_gaps: string[];
  data_sources: Client360DataSource[];
}

interface Client360OpportunitiesResponse {
  items: Client360Opportunity[];
  facets: {
    countries: string[];
    hubs: string[];
    technologies: string[];
    part_families: string[];
    statuses: string[];
    confidence_labels: string[];
  };
}

interface Client360CustomerResponse {
  customer: {
    id: string;
    name: string;
    countries: string[];
    hubs: string[];
    technologies: string[];
  };
  opportunities: Client360Opportunity[];
  mail_drafts: Client360MailDraft[];
  impact_events: Client360ImpactEvent[];
  market_signals: Client360DataSource[];
  data_gaps: string[];
}

interface Client360MailDraft {
  id: string;
  opportunity_id: string;
  action_item_id?: string | null;
  subject: string;
  generated_body: string;
  sent_body?: string | null;
  language: string;
  status: string;
  created_at?: string | null;
  sent_at?: string | null;
}

interface Client360MappingRule {
  id: string;
  source_part_reference?: string | null;
  source_part_label?: string | null;
  source_part_family?: string | null;
  technology?: string | null;
  pdr_family: string;
  recommended_quantity?: number | null;
  periodicity_weeks?: number | null;
  delivery_time_weeks?: number | null;
  status: string;
  confidence: number;
  notes?: string | null;
}

interface Client360MappingsResponse {
  items: Client360MappingRule[];
}

interface Client360EngineResult {
  engine: string;
  dry_run: boolean;
  records_seen: number;
  candidate_mappings_created: number;
  opportunities_detected: number;
  created: number;
  updated: number;
  skipped: Record<string, number>;
  preview: Client360Opportunity[];
}

interface Client360ImpactEvent {
  id: string;
  opportunity_id?: string | null;
  action_item_id?: string | null;
  mail_draft_id?: string | null;
  impact_type: string;
  attribution: string;
  reason: string;
  summary: string;
  quote_value?: number | null;
  order_value?: number | null;
  currency?: string | null;
  occurred_at?: string | null;
}

interface ActionResponse {
  action: { id: string; status: string; metadata?: Record<string, unknown> };
}

interface MailDraftResponse {
  mail_draft: Client360MailDraft;
  action: { id: string; status: string };
}

interface ImpactResponse {
  impact_event: Client360ImpactEvent;
}

@Component({
  selector: 'app-client360-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, NgClass, GlyphComponent, PageFrameComponent],
  template: `
    <ck-page-frame eyebrow="Andritz / Spare Parts" title="Client360 PDR" [hasActions]="true">
      <button actions type="button" class="icon-button" title="Rafraichir" (click)="refresh()">
        <ck-glyph name="orbit" [size]="14" color="currentColor" />
      </button>

      <nav sub class="ck-surface c360-tabs" aria-label="Client360 PDR">
        @for (tab of tabs; track tab.id) {
          <button type="button" (click)="view.set(tab.id)" [ngClass]="{ active: view() === tab.id }">
            {{ tab.label }}
          </button>
        }
      </nav>

      <section class="c360-workspace">
      @if (loading()) {
        <div class="state-line"><ck-glyph name="pulse" [size]="14" color="currentColor" /> Chargement Client360 PDR</div>
      } @else if (error()) {
        <div class="state-line error"><ck-glyph name="warn" [size]="14" color="currentColor" /> {{ error() }}</div>
      }

      <section class="kpi-grid">
        <div class="ck-surface kpi">
          <span>Opportunites</span>
          <strong>{{ summary()?.summary?.opportunities ?? 0 }}</strong>
        </div>
        <div class="ck-surface kpi">
          <span>Clients</span>
          <strong>{{ summary()?.summary?.customers ?? 0 }}</strong>
        </div>
        <div class="ck-surface kpi">
          <span>Sources</span>
          <strong>{{ summary()?.summary?.data_sources ?? 0 }}</strong>
        </div>
        <div class="ck-surface kpi">
          <span>Ecart adressable</span>
          <strong>{{ formatQty(summary()?.summary?.potential_gap_qty) }}</strong>
        </div>
      </section>

      @if (view() === 'opportunities') {
        <section class="ck-surface toolbar">
          <label>
            Client
            <input type="search" [(ngModel)]="filters.customer" (keyup.enter)="loadOpportunities()" placeholder="Nom client" />
          </label>
          <label>
            Pays
            <select [(ngModel)]="filters.country" (change)="loadOpportunities()">
              <option value="">Tous</option>
              @for (item of opportunitiesResponse()?.facets?.countries ?? []; track item) {
                <option [value]="item">{{ item }}</option>
              }
            </select>
          </label>
          <label>
            Famille
            <select [(ngModel)]="filters.part_family" (change)="loadOpportunities()">
              <option value="">Toutes</option>
              @for (item of opportunitiesResponse()?.facets?.part_families ?? []; track item) {
                <option [value]="item">{{ item }}</option>
              }
            </select>
          </label>
          <label>
            Confiance
            <select [(ngModel)]="filters.confidence" (change)="loadOpportunities()">
              <option value="">Toutes</option>
              <option value="high">Haute</option>
              <option value="medium">Moyenne</option>
              <option value="low">Faible</option>
            </select>
          </label>
          <button type="button" class="secondary" (click)="loadOpportunities()">
            <ck-glyph name="sliders" [size]="14" color="currentColor" /> Filtrer
          </button>
        </section>

        <section class="ck-surface table-wrap">
          @if (opportunities().length === 0) {
            <div class="empty">
              <ck-glyph name="ledger" [size]="18" color="currentColor" />
              <span>Aucune opportunite PDR calculee pour le moment.</span>
              <small>Les sources detectees et les gaps sont visibles dans l'onglet Donnees.</small>
            </div>
          } @else {
            <table>
              <thead>
                <tr>
                  <th>Client</th>
                  <th>Piece / famille</th>
                  <th>Pays</th>
                  <th>Echeance</th>
                  <th>Potentiel</th>
                  <th>Achats connus</th>
                  <th>Ecart achats</th>
                  <th>Confiance</th>
                  <th>Action</th>
                  <th>Statut</th>
                </tr>
              </thead>
              <tbody>
                @for (opp of opportunities(); track opp.id) {
                  <tr (click)="selectOpportunity(opp)">
                    <td>
                      <strong>{{ opp.customer_name }}</strong>
                      <small>{{ opp.technology || opp.line_label || opp.machine_label || 'Perimetre a completer' }}</small>
                    </td>
                    <td>
                      <strong>{{ opp.part_family }}</strong>
                      <small>{{ opp.part_reference || opp.part_description || 'Reference a completer' }}</small>
                    </td>
                    <td>{{ opp.country || opp.hub || 'A completer' }}</td>
                    <td>{{ formatDate(opp.next_due_at) }}</td>
                    <td>{{ formatQty(opp.potential_theoretical) }}</td>
                    <td>{{ formatQty(opp.sales_known_qty) }}</td>
                    <td>{{ formatQty(opp.potential_gap_qty) }}</td>
                    <td><span class="pill" [ngClass]="opp.confidence_label">{{ labelConfidence(opp.confidence_label) }}</span></td>
                    <td>{{ labelAction(opp.recommended_action) }}</td>
                    <td><span class="status">{{ labelStatus(opp.status) }}</span></td>
                  </tr>
                }
              </tbody>
            </table>
          }
        </section>
      }

      @if (view() === 'customer') {
        <section class="split">
          <aside class="ck-surface list-panel">
            @for (opp of opportunities(); track opp.id) {
              <button type="button" [ngClass]="{ active: selectedOpportunity()?.id === opp.id }" (click)="selectOpportunity(opp)">
                <strong>{{ opp.customer_name }}</strong>
                <span>{{ opp.part_family }}</span>
              </button>
            }
          </aside>
          <article class="ck-surface detail-panel">
            @if (selectedOpportunity()) {
              <div class="detail-head">
                <div>
                  <p class="ck-label c360-eyebrow">Fiche client PDR</p>
                  <h2>{{ selectedOpportunity()?.customer_name }}</h2>
                </div>
                <div class="button-row">
                  <button type="button" class="secondary" (click)="updateOpportunityStatus(selectedOpportunity()!, 'validated')">
                    <ck-glyph name="check" [size]="14" color="currentColor" /> Valider
                  </button>
                  <button type="button" class="secondary" (click)="updateOpportunityStatus(selectedOpportunity()!, 'dismissed')">
                    <ck-glyph name="x" [size]="14" color="currentColor" /> Rejeter
                  </button>
                  <button type="button" class="primary" (click)="generateDraft(selectedOpportunity()!)">
                    <ck-glyph name="ledger" [size]="14" color="currentColor" /> Brouillon mail
                  </button>
                </div>
              </div>
              <dl class="facts">
                <div><dt>Pays / hub</dt><dd>{{ selectedOpportunity()?.country || selectedOpportunity()?.hub || 'A completer' }}</dd></div>
                <div><dt>Technologie</dt><dd>{{ selectedOpportunity()?.technology || 'A completer' }}</dd></div>
                <div><dt>Piece</dt><dd>{{ selectedOpportunity()?.part_family }}</dd></div>
                <div><dt>Periodicite</dt><dd>{{ formatWeeks(selectedOpportunity()?.periodicity_weeks) }}</dd></div>
                <div><dt>Quantite annuelle</dt><dd>{{ formatQty(selectedOpportunity()?.annual_theoretical_qty) }}</dd></div>
                <div><dt>Achats SAP connus</dt><dd>{{ formatQty(selectedOpportunity()?.sales_known_qty) }}</dd></div>
                <div><dt>Ecart vs achats</dt><dd>{{ formatQty(selectedOpportunity()?.potential_gap_qty) }}</dd></div>
                <div><dt>Delai</dt><dd>{{ formatWeeks(selectedOpportunity()?.delivery_time_weeks) }}</dd></div>
                <div><dt>Echeance</dt><dd>{{ formatDate(selectedOpportunity()?.next_due_at) }}</dd></div>
                <div><dt>Action</dt><dd>{{ labelAction(selectedOpportunity()?.recommended_action) }}</dd></div>
              </dl>
              <h3>Donnees manquantes</h3>
              <div class="chips">
                @for (gap of selectedOpportunity()?.data_gaps ?? []; track gap) {
                  <span>{{ labelGap(gap) }}</span>
                }
              </div>
              <h3>Raisons du score</h3>
              <div class="reason-list">
                @for (reason of selectedOpportunity()?.score_reasons ?? []; track reason.code) {
                  <span [ngClass]="{ met: reason.met }">{{ reason.label }}</span>
                }
              </div>
              <h3>Signaux externes</h3>
              <div class="chips">
                @for (signal of selectedCustomer()?.market_signals ?? []; track signal.id) {
                  <span>{{ signal.label }}</span>
                }
                @if ((selectedCustomer()?.market_signals ?? []).length === 0) {
                  <span>Pas de signal externe rattache</span>
                }
              </div>
            } @else {
              <div class="empty"><span>Selectionner une opportunite.</span></div>
            }
          </article>
        </section>
      }

      @if (view() === 'data') {
        <section class="data-layout">
          <div class="ck-surface gap-panel">
            <div class="detail-head compact">
              <div>
                <p class="ck-label c360-eyebrow">Moteur donnees</p>
                <h2>Gaps metier</h2>
              </div>
              <button type="button" class="primary" (click)="runEngine(false)">
                <ck-glyph name="play" [size]="14" color="currentColor" /> Calculer
              </button>
            </div>
            <div class="chips">
              @for (gap of summary()?.data_gaps ?? []; track gap) {
                <span>{{ labelGap(gap) }}</span>
              }
              @if ((summary()?.data_gaps ?? []).length === 0) {
                <span class="ok">Sources minimales detectees</span>
              }
            </div>
            @if (engineResult()) {
              <dl class="engine-facts">
                <div><dt>Records lus</dt><dd>{{ engineResult()?.records_seen }}</dd></div>
                <div><dt>Opportunites</dt><dd>{{ engineResult()?.opportunities_detected }}</dd></div>
                <div><dt>Crees</dt><dd>{{ engineResult()?.created }}</dd></div>
                <div><dt>Maj</dt><dd>{{ engineResult()?.updated }}</dd></div>
                <div><dt>Mappings</dt><dd>{{ engineResult()?.candidate_mappings_created }}</dd></div>
              </dl>
            }
          </div>
          <div class="ck-surface table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Source</th>
                  <th>Collection</th>
                  <th>Statut</th>
                </tr>
              </thead>
              <tbody>
                @for (source of summary()?.data_sources ?? []; track source.id) {
                  <tr>
                    <td>{{ labelSourceType(source.source_type) }}</td>
                    <td>
                      <strong>{{ source.label }}</strong>
                      <small>{{ source.origin }}</small>
                    </td>
                    <td>{{ source.collection_slug || '-' }}</td>
                    <td><span class="status">{{ source.status }}</span></td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        </section>
      }

      @if (view() === 'mapping') {
        <section class="ck-surface table-wrap">
          @if (mappings().length === 0) {
            <div class="empty">
              <ck-glyph name="flow" [size]="18" color="currentColor" />
              <span>Aucun mapping SAP / famille PDR pour le moment.</span>
              <small>Lancer le moteur depuis Donnees cree les candidats detectables.</small>
            </div>
          } @else {
            <table>
              <thead>
                <tr>
                  <th>SAP / source</th>
                  <th>Famille PDR</th>
                  <th>Technologie</th>
                  <th>Periodicite</th>
                  <th>Statut</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                @for (mapping of mappings(); track mapping.id) {
                  <tr>
                    <td>
                      <strong>{{ mapping.source_part_reference || mapping.source_part_family || mapping.source_part_label || '-' }}</strong>
                      <small>{{ mapping.notes || 'Mapping semi-manuel' }}</small>
                    </td>
                    <td>{{ mapping.pdr_family }}</td>
                    <td>{{ mapping.technology || '-' }}</td>
                    <td>{{ formatWeeks(mapping.periodicity_weeks) }}</td>
                    <td><span class="status">{{ labelMappingStatus(mapping.status) }}</span></td>
                    <td>
                      @if (mapping.status !== 'validated') {
                        <button type="button" class="secondary" (click)="validateMapping(mapping)">
                          <ck-glyph name="check" [size]="14" color="currentColor" /> Valider
                        </button>
                      }
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          }
        </section>
      }

      @if (view() === 'mail') {
        <section class="mail-layout">
          <div class="ck-surface detail-panel">
            <div class="detail-head">
              <div>
                <p class="ck-label c360-eyebrow">Mail & suivi</p>
                <h2>{{ currentDraft()?.subject || 'Aucun brouillon selectionne' }}</h2>
              </div>
              @if (currentDraft()?.action_item_id) {
                <button type="button" class="primary" (click)="markSent()">
                  <ck-glyph name="arrow-up" [size]="14" color="currentColor" /> Marquer envoye
                </button>
              }
            </div>
            <textarea [ngModel]="currentDraft()?.sent_body || currentDraft()?.generated_body || ''" (ngModelChange)="draftBody.set($event)"></textarea>
          </div>
          <aside class="ck-surface impact-panel">
            <h3>Impact</h3>
            <label>
              Attribution
              <select [(ngModel)]="impactAttribution">
                <option value="direct">Direct</option>
                <option value="probable">Probable</option>
                <option value="unknown">Inconnu</option>
                <option value="none">Aucun</option>
              </select>
            </label>
            <label>
              Raison
              <select [(ngModel)]="impactReason">
                <option value="unknown">Inconnue</option>
                <option value="price">Prix</option>
                <option value="competitor">Concurrent</option>
                <option value="no_need">Pas besoin</option>
                <option value="wrong_contact">Mauvais contact</option>
                <option value="timing">Timing</option>
                <option value="hub">Hub</option>
                <option value="technical_mismatch">Ecart technique</option>
                <option value="bad_data">Donnee incorrecte</option>
                <option value="other">Autre</option>
              </select>
            </label>
            <label>
              Note
              <textarea class="small-textarea" [(ngModel)]="impactSummary"></textarea>
            </label>
            <div class="impact-buttons">
              <button type="button" (click)="recordImpact('response')">Reponse</button>
              <button type="button" (click)="recordImpact('quote')">Devis</button>
              <button type="button" (click)="recordImpact('order')">Commande</button>
              <button type="button" (click)="recordImpact('lost')">Perdu</button>
            </div>
          </aside>
        </section>
      }
      </section>
    </ck-page-frame>
  `,
  styles: [`
    :host { display: block; min-height: 100%; background: var(--ck-bg-base); color: var(--ck-fg-1); }
    .c360-workspace { display: flex; flex-direction: column; gap: 16px; }
    .c360-eyebrow { margin: 0 0 6px; color: var(--ck-signal-cool); letter-spacing: 0; }
    h1, h2, h3 { margin: 0; letter-spacing: 0; }
    h2 { font-size: 18px; font-weight: 650; }
    h3 { font-size: 13px; font-weight: 680; color: var(--ck-fg-2); }
    .icon-button, .primary, .secondary, .c360-tabs button, .impact-buttons button {
      display: inline-flex; align-items: center; justify-content: center; gap: 7px; border-radius: var(--ck-radius-md); border: 1px solid var(--ck-stroke-2);
      min-height: 34px; padding: 0 12px; background: var(--ck-bg-inset); color: var(--ck-fg-2); cursor: pointer; font-weight: 650;
    }
    .primary { background: color-mix(in oklab, var(--ck-signal-cool) 88%, transparent); color: var(--ck-on-signal); border-color: transparent; }
    .secondary:hover, .icon-button:hover, .c360-tabs button:hover { border-color: var(--ck-stroke-3); color: var(--ck-fg-1); }
    .c360-tabs { display: flex; flex-wrap: wrap; gap: 4px; padding: 4px; margin-top: 18px; width: 100%; border-radius: var(--ck-radius-lg); }
    .c360-tabs button {
      min-height: 36px;
      padding: 0 18px;
      background: transparent;
      border-color: transparent;
      color: var(--ck-fg-4);
      font-family: var(--ck-font-mono);
      font-size: 10px;
      font-weight: 650;
      letter-spacing: 0;
      text-transform: uppercase;
    }
    .c360-tabs button.active {
      background: var(--ck-bg-inset);
      color: var(--ck-fg-1);
      border-color: var(--ck-stroke-3);
      box-shadow: inset 0 0 0 1px var(--ck-stroke-2);
    }
    .state-line { display: inline-flex; align-items: center; gap: 8px; color: var(--ck-fg-3); font-size: 12px; }
    .state-line.error { color: var(--ck-signal-neg); }
    .kpi-grid { display: grid; grid-template-columns: repeat(4, minmax(160px, 1fr)); gap: 10px; }
    .kpi { padding: 14px 16px; border-radius: var(--ck-radius-md); }
    .kpi span { display: block; color: var(--ck-fg-4); font: 700 10px/1 var(--ck-font-mono); text-transform: uppercase; letter-spacing: 0; }
    .kpi strong { display: block; margin-top: 9px; font-size: 22px; font-weight: 680; }
    .toolbar { display: flex; align-items: end; flex-wrap: wrap; gap: 10px; padding: 12px 16px; border-radius: var(--ck-radius-md); }
    label { display: grid; gap: 5px; color: var(--ck-fg-4); font: 700 10px/1 var(--ck-font-mono); text-transform: uppercase; letter-spacing: 0; }
    input, select, textarea {
      min-height: 34px; border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-md); background: var(--ck-bg-inset);
      color: var(--ck-fg-1); padding: 0 10px; outline: 0; font: 500 13px/1.4 var(--ck-font-sans);
    }
    textarea { width: 100%; min-height: 360px; padding: 12px; resize: vertical; white-space: pre-wrap; }
    .small-textarea { min-height: 90px; }
    .table-wrap { overflow: auto; border-radius: var(--ck-radius-md); }
    table { width: 100%; border-collapse: collapse; min-width: 760px; }
    th, td { padding: 11px 12px; border-bottom: 1px solid var(--ck-stroke-2); text-align: left; vertical-align: top; font-size: 12px; }
    th { color: var(--ck-fg-4); font: 700 10px/1 var(--ck-font-mono); text-transform: uppercase; letter-spacing: 0; }
    td strong { display: block; color: var(--ck-fg-1); font-size: 12px; }
    td small { display: block; margin-top: 4px; color: var(--ck-fg-4); line-height: 1.35; }
    tbody tr { cursor: pointer; }
    tbody tr:hover { background: rgba(255, 255, 255, .035); }
    .pill, .status, .chips span { display: inline-flex; align-items: center; border-radius: var(--ck-radius-md); padding: 3px 8px; background: var(--ck-tint-faint); border: 1px solid var(--ck-stroke-2); color: var(--ck-fg-3); font-size: 11px; white-space: nowrap; }
    .pill.high { color: var(--ck-signal-pos); border-color: rgba(16,185,129,.35); }
    .pill.medium { color: var(--ck-signal-warn); border-color: rgba(245,158,11,.35); }
    .pill.low { color: var(--ck-fg-4); }
    .empty { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; min-height: 180px; color: var(--ck-fg-3); text-align: center; }
    .empty small { color: var(--ck-fg-4); }
    .split, .mail-layout, .data-layout { display: grid; grid-template-columns: minmax(240px, 320px) 1fr; gap: 12px; min-height: 420px; }
    .list-panel, .detail-panel, .gap-panel, .impact-panel { border-radius: var(--ck-radius-md); padding: 12px; }
    .list-panel { display: flex; flex-direction: column; gap: 6px; overflow: auto; }
    .list-panel button { text-align: left; border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-md); background: var(--ck-bg-inset); color: var(--ck-fg-2); padding: 10px; cursor: pointer; }
    .list-panel button.active { border-color: rgba(103, 213, 246, .42); color: var(--ck-signal-cool); }
    .list-panel span { display: block; margin-top: 4px; color: var(--ck-fg-4); font-size: 11px; }
    .detail-head { display: flex; justify-content: space-between; gap: 12px; align-items: start; margin-bottom: 14px; }
    .detail-head.compact { margin-bottom: 10px; }
    .button-row { display: inline-flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 7px; }
    .facts { display: grid; grid-template-columns: repeat(3, minmax(130px, 1fr)); gap: 10px; margin: 0 0 16px; }
    .facts div { padding: 10px; background: var(--ck-bg-inset); border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-md); }
    .engine-facts { display: grid; grid-template-columns: repeat(2, minmax(90px, 1fr)); gap: 8px; margin: 12px 0 0; }
    .engine-facts div { padding: 8px; background: var(--ck-bg-inset); border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-md); }
    dt { color: var(--ck-fg-4); font: 700 10px/1 var(--ck-font-mono); text-transform: uppercase; letter-spacing: 0; }
    dd { margin: 7px 0 0; color: var(--ck-fg-2); font-size: 13px; }
    .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
    .chips .ok { color: var(--ck-signal-pos); }
    .reason-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
    .reason-list span { border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-md); color: var(--ck-fg-4); padding: 4px 8px; font-size: 11px; }
    .reason-list span.met { color: var(--ck-signal-pos); border-color: rgba(16,185,129,.35); }
    .impact-panel { display: flex; flex-direction: column; gap: 12px; }
    .impact-buttons { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    @media (max-width: 900px) {
      .kpi-grid, .split, .mail-layout, .data-layout, .facts { grid-template-columns: 1fr; }
    }
  `],
})
export class Client360PageComponent implements OnInit {
  private readonly http = inject(HttpClient);
  readonly view = signal<ViewKey>('opportunities');
  readonly loading = signal(false);
  readonly error = signal<string | null>(null);
  readonly summary = signal<Client360Summary | null>(null);
  readonly opportunitiesResponse = signal<Client360OpportunitiesResponse | null>(null);
  readonly selectedOpportunity = signal<Client360Opportunity | null>(null);
  readonly selectedCustomer = signal<Client360CustomerResponse | null>(null);
  readonly currentDraft = signal<Client360MailDraft | null>(null);
  readonly draftBody = signal('');
  readonly mappingsResponse = signal<Client360MappingsResponse | null>(null);
  readonly engineResult = signal<Client360EngineResult | null>(null);

  impactAttribution = 'unknown';
  impactReason = 'unknown';
  impactSummary = '';

  readonly filters = {
    customer: '',
    country: '',
    hub: '',
    technology: '',
    part_family: '',
    confidence: '',
    status: '',
  };

  readonly tabs: Array<{ id: ViewKey; label: string }> = [
    { id: 'opportunities', label: 'Opportunites' },
    { id: 'customer', label: 'Client' },
    { id: 'data', label: 'Donnees' },
    { id: 'mapping', label: 'Mapping' },
    { id: 'mail', label: 'Mail & suivi' },
  ];

  readonly opportunities = computed(() => this.opportunitiesResponse()?.items ?? []);
  readonly mappings = computed(() => this.mappingsResponse()?.items ?? []);

  ngOnInit(): void {
    this.refresh();
  }

  refresh(): void {
    this.loading.set(true);
    this.error.set(null);
    this.http.get<Client360Summary>('/api/v1/client360/summary').subscribe({
      next: (payload) => {
        this.summary.set(payload);
        this.loadMappings(false);
        this.loadOpportunities(false);
      },
      error: () => {
        this.loading.set(false);
        this.error.set('Client360 PDR indisponible');
      },
    });
  }

  loadMappings(showLoading = true): void {
    if (showLoading) this.loading.set(true);
    this.http.get<Client360MappingsResponse>('/api/v1/client360/mappings').subscribe({
      next: (payload) => {
        this.mappingsResponse.set(payload);
        if (showLoading) this.loading.set(false);
      },
      error: () => {
        if (showLoading) this.loading.set(false);
        this.error.set('Impossible de charger les mappings Client360 PDR');
      },
    });
  }

  runEngine(dryRun: boolean): void {
    this.loading.set(true);
    this.error.set(null);
    this.http.post<Client360EngineResult>('/api/v1/client360/engines/opportunities/run', { dry_run: dryRun }).subscribe({
      next: (payload) => {
        this.engineResult.set(payload);
        this.loading.set(false);
        this.refresh();
      },
      error: () => {
        this.loading.set(false);
        this.error.set('Impossible de lancer le moteur Client360 PDR');
      },
    });
  }

  validateMapping(mapping: Client360MappingRule): void {
    this.http.patch<{ mapping: Client360MappingRule }>(`/api/v1/client360/mappings/${encodeURIComponent(mapping.id)}`, {
      status: 'validated',
      confidence: Math.max(mapping.confidence || 0, 0.75),
    }).subscribe({
      next: () => {
        this.loadMappings(false);
        this.runEngine(false);
      },
      error: () => this.error.set('Impossible de valider le mapping'),
    });
  }

  updateOpportunityStatus(opp: Client360Opportunity, status: 'validated' | 'dismissed'): void {
    this.http.patch<{ opportunity: Client360Opportunity }>(`/api/v1/client360/opportunities/${encodeURIComponent(opp.id)}`, {
      status,
      validation_reason: status === 'validated' ? 'sales_review' : undefined,
      rejection_reason: status === 'dismissed' ? 'sales_rejected' : undefined,
    }).subscribe({
      next: (payload) => {
        this.selectedOpportunity.set(payload.opportunity);
        this.loadOpportunities(false);
      },
      error: () => this.error.set('Impossible de qualifier opportunite'),
    });
  }

  loadOpportunities(showLoading = true): void {
    if (showLoading) this.loading.set(true);
    let params = new HttpParams().set('limit', '200');
    for (const [key, value] of Object.entries(this.filters)) {
      if (value) params = params.set(key, value);
    }
    this.http.get<Client360OpportunitiesResponse>('/api/v1/client360/opportunities', { params }).subscribe({
      next: (payload) => {
        this.opportunitiesResponse.set(payload);
        if (!this.selectedOpportunity() && payload.items.length) {
          this.selectedOpportunity.set(payload.items[0]);
        }
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
        this.error.set('Impossible de charger les opportunites Client360 PDR');
      },
    });
  }

  selectOpportunity(opp: Client360Opportunity): void {
    this.selectedOpportunity.set(opp);
    this.view.set('customer');
    this.http.get<Client360CustomerResponse>(`/api/v1/client360/customers/${encodeURIComponent(opp.customer_key)}`).subscribe({
      next: (payload) => this.selectedCustomer.set(payload),
      error: () => this.selectedCustomer.set(null),
    });
  }

  generateDraft(opp: Client360Opportunity): void {
    this.loading.set(true);
    this.http.post<MailDraftResponse>('/api/v1/client360/mail-drafts', {
      opportunity_id: opp.id,
      language: 'fr',
      include_prices: false,
    }).subscribe({
      next: (payload) => {
        this.currentDraft.set(payload.mail_draft);
        this.draftBody.set(payload.mail_draft.generated_body);
        this.view.set('mail');
        this.loading.set(false);
        this.loadOpportunities(false);
      },
      error: () => {
        this.loading.set(false);
        this.error.set('Impossible de generer le brouillon');
      },
    });
  }

  markSent(): void {
    const draft = this.currentDraft();
    if (!draft?.action_item_id) return;
    this.http.patch<ActionResponse>(`/api/v1/client360/actions/${encodeURIComponent(draft.action_item_id)}`, {
      mail_draft_id: draft.id,
      mail_status: 'sent',
      status: 'in_progress',
      sent_body: this.draftBody(),
      sent_at: new Date().toISOString(),
    }).subscribe({
      next: () => {
        this.currentDraft.set({ ...draft, status: 'sent', sent_body: this.draftBody(), sent_at: new Date().toISOString() });
        this.loadOpportunities(false);
      },
      error: () => this.error.set('Impossible de mettre a jour le suivi mail'),
    });
  }

  recordImpact(type: string): void {
    const draft = this.currentDraft();
    if (!draft?.action_item_id) return;
    this.http.post<ImpactResponse>(`/api/v1/client360/actions/${encodeURIComponent(draft.action_item_id)}/impact`, {
      impact_type: type,
      attribution: this.impactAttribution,
      reason: this.impactReason,
      summary: this.impactSummary,
      opportunity_id: draft.opportunity_id,
      mail_draft_id: draft.id,
    }).subscribe({
      next: () => {
        this.refresh();
      },
      error: () => this.error.set('Impossible de qualifier impact'),
    });
  }

  formatQty(value: number | null | undefined): string {
    if (value == null || Number.isNaN(value)) return '-';
    return new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 1 }).format(value);
  }

  formatWeeks(value: number | null | undefined): string {
    if (value == null) return 'A completer';
    return `${this.formatQty(value)} semaines`;
  }

  formatDate(value: string | null | undefined): string {
    if (!value) return 'A completer';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'A completer';
    return new Intl.DateTimeFormat('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' }).format(date);
  }

  labelConfidence(value: string): string {
    return value === 'high' ? 'Haute' : value === 'medium' ? 'Moyenne' : 'Faible';
  }

  labelStatus(value: string): string {
    const labels: Record<string, string> = {
      detected: 'Detectee',
      validated: 'Validee',
      draft_generated: 'Brouillon',
      sent: 'Envoye',
      responded: 'Reponse',
      quote_requested: 'Devis',
      won: 'Gagne',
      lost: 'Perdu',
      dismissed: 'Ecartee',
    };
    return labels[value] || value;
  }

  labelAction(value: string | null | undefined): string {
    const labels: Record<string, string> = {
      validate_pdr_mapping: 'Valider mapping',
      request_installed_base: 'Demander base installee',
      prepare_inspection_or_spa: 'Inspection / SPA',
      draft_expertise_email: 'Brouillon expertise',
      complete_sap_history: 'Completer SAP',
      review_with_sales: 'Revue commerciale',
    };
    return value ? labels[value] || value : '-';
  }

  labelMappingStatus(value: string): string {
    const labels: Record<string, string> = {
      candidate: 'Candidat',
      validated: 'Valide',
      rejected: 'Rejete',
      needs_review: 'A revoir',
    };
    return labels[value] || value;
  }

  labelGap(value: string): string {
    const labels: Record<string, string> = {
      installed_base_missing: 'Base installee manquante',
      periodicity_missing: 'Periodicite manquante',
      sap_sales_history_missing: 'Historique SAP manquant',
      recommended_quantity_missing: 'Quantite recommandee manquante',
      installed_quantity_missing: 'Quantite installee manquante',
      customer_location_missing: 'Pays / hub manquant',
      delivery_time_missing: 'Delai manquant',
    };
    return labels[value] || value;
  }

  labelSourceType(value: string): string {
    const labels: Record<string, string> = {
      installed_base: 'Base installee',
      periodicity: 'Periodicite',
      sap_sales_history: 'Historique SAP',
      contact_hub: 'Contacts / hubs',
      market_signal: 'Signal marche',
      other: 'Autre',
    };
    return labels[value] || value;
  }
}
