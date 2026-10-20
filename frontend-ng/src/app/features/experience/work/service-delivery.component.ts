import { ChangeDetectionStrategy, Component, DestroyRef, effect, inject, OnInit, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { settleWrite, type WriteOutcome } from '@app/shared/ui/load-state';
import { WriteOutcomeComponent } from '@app/shared/ui/write-outcome.component';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService, type WorkspaceMemberDetail } from '@app/core/workspace.service';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import { DatasetPreviewComponent } from '@app/features/data/dataset-preview.component';
import { TypedJudgeResultComponent } from '@app/features/data/typed-judge-result.component';
import { WorkBarComponent } from './work-bar.component';
import { WorkAppHeaderComponent } from './work-app-header.component';
import { ServiceDeliveryApi } from './service-delivery.api';
import { candidateDatasetId, candidateObjects, downloadName, contractRequest, publicationRequest, reviewRequest, type CandidateObject, type BoundReview, type CandidateEvidence, type DeliveryReceipt, type Page, type ServiceContract, type ServiceContractForm, type ServiceAssetMetadata, type ServiceSourceForm, type ServiceIncident, type ServiceWindow } from './service-delivery.models';
type Tab = 'contracts' | 'windows' | 'receipts' | 'incidents';

@Component({
  selector: 'app-service-delivery', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, WorkBarComponent, WorkAppHeaderComponent, NavLinkDirective, DatasetPreviewComponent, TypedJudgeResultComponent, WriteOutcomeComponent],
  styleUrls: ['./work.scss', '../../data/dataops-editor.scss'],
  styles: [`
    .sd-status { display: inline-flex; align-items: center; gap: 6px; margin: 6px 0; padding: 2px 8px; border-radius: 4px; font-size: 12px; border: 1px solid var(--ck-stroke-2); }
    .sd-status[data-state='active'] { color: var(--ck-status-ok-fg); background: var(--ck-status-ok-bg); }
    .sd-status[data-state='draft'] { color: var(--ck-status-warn-fg); background: var(--ck-status-warn-bg); }
  `],
  template: `
    <div class="xp-work"><app-work-bar /><main class="dp-page">
      <app-work-app-header [title]="i18n.t('dataops.work.title')" [description]="i18n.t('dataops.work.subtitle')">
        <button type="button" class="dp-button" [disabled]="busy()" (click)="load()">{{ i18n.t('dataops.reload') }}</button>
      </app-work-app-header>
      <nav class="dp-row" [attr.aria-label]="i18n.t('dataops.work.title')">@for (item of tabs; track item) { <button type="button" class="dp-button" [attr.aria-pressed]="tab() === item" (click)="select(item)">{{ i18n.t('dataops.work.' + item) }}</button> }</nav>
      @if (error()) { <p class="dp-error" role="alert">{{ i18n.t(error()) }}</p> }
      @if (notice()) { <p class="dp-note" role="status">{{ i18n.t(notice()) }}</p> }
      @if (tab() === 'contracts') {
        @if (workspace.isAdmin()) {
          <details class="dp-section"><summary>{{ i18n.t('dataops.work.create') }}</summary><form (ngSubmit)="create()">
            <div class="dp-grid"><label class="dp-field"><span>{{ i18n.t('dataops.work.system') }}</span><select class="dp-input" [(ngModel)]="form.system_id" name="system" required><option value="">{{ i18n.t('dataops.choose') }}</option>@for (system of systems(); track system.id) { <option [value]="system.id">{{ system.name }}</option> }</select></label>
              <label class="dp-field"><span>{{ i18n.t('dataops.work.owner') }}</span><select class="dp-input" [(ngModel)]="form.owner_user_id" name="owner" required><option value="">{{ i18n.t('dataops.choose') }}</option>@for (member of members(); track member.user_id) { <option [value]="member.user_id">{{ member.username }}</option> }</select></label>
              <label class="dp-field"><span>{{ i18n.t('dataops.work.key') }}</span><input class="dp-input" [(ngModel)]="form.logical_key" name="logical_key" required /></label>
              <label class="dp-field"><span>{{ i18n.t('dataops.work.timezone') }}</span><input class="dp-input" [(ngModel)]="form.timezone" name="timezone" required /></label>
              <label class="dp-field"><span>{{ i18n.t('dataops.work.starts') }}</span><input class="dp-input" type="date" [(ngModel)]="form.starts_on" name="starts_on" required /></label>
              <label class="dp-field"><span>{{ i18n.t('dataops.work.deadline') }} · {{ i18n.t('dataops.work.daily') }}</span><input class="dp-input" type="time" [(ngModel)]="form.deadline" name="deadline" required /></label>
              @for (field of budgetFields; track field) { <label class="dp-field"><span>{{ i18n.t('dataops.work.' + field) }}</span><input class="dp-input" type="number" min="0" step="any" [(ngModel)]="form[field]" [name]="field" required /></label> }
            </div>
            <section class="dp-section"><h3>{{i18n.t('dataops.work.sources')}}</h3><p class="dp-note">{{i18n.t('dataops.work.sources_hint')}}</p>
              <div class="dp-row"><button type="button" class="dp-button" [disabled]="sourcesLoading()" (click)="loadSources(true)">{{i18n.t('dataops.reload')}}</button>@if (sourceOffset() < sourceTotal()) { <button type="button" class="dp-button" [disabled]="sourcesLoading()" (click)="loadSources()">{{i18n.t('dataops.work.more_sources')}}</button> }</div>
              @if (sourceError()) { <p class="dp-error" role="alert">{{i18n.t('dataops.error.load')}}</p> }
              @for (source of form.inputs ?? []; track $index; let n = $index) {
                <div class="dp-section"><div class="dp-grid">
                  <label class="dp-field"><span>{{i18n.t('dataops.work.source_asset')}}</span><select class="dp-input" [ngModel]="sourcePreview(source)?.asset_ref?.asset_id ?? ''" (ngModelChange)="chooseSource(n,$event)" [name]="'source_asset'+n" required><option value="">{{i18n.t('dataops.choose')}}</option>@for (asset of sourceChoices(); track asset.asset_ref.asset_id) { <option [value]="asset.asset_ref.asset_id">{{asset.logical_key}} · {{i18n.t('dataops.asset_kind.'+asset.kind)}}</option> }</select></label>
                  <label class="dp-field"><span>{{i18n.t('dataops.work.source_payload_key')}}</span><input class="dp-input" [(ngModel)]="source.payload_key" [name]="'source_key'+n" maxlength="64" pattern="[A-Za-z][A-Za-z0-9_]{0,63}" required /></label>
                  <label class="dp-field"><span>{{i18n.t('dataops.work.source_max_age')}}</span><input class="dp-input" type="number" min="1" max="31536000" step="1" [(ngModel)]="source.max_age_seconds" [name]="'source_age'+n" required /></label>
                  <label class="dp-field"><span>{{i18n.t('dataops.work.source_representation')}}</span><select class="dp-input" [(ngModel)]="source.representation" [name]="'source_representation'+n"><option value="asset_ref">{{i18n.t('dataops.work.source_asset_ref')}}</option><option value="native_id" [disabled]="source.asset?.kind !== 'dataset' && source.asset?.kind !== 'model'">{{i18n.t('dataops.work.source_native_id')}}</option></select></label>
                </div>
                <label class="dp-check"><input type="checkbox" [(ngModel)]="source.require_qualified" [name]="'source_qualified'+n" />{{i18n.t('dataops.work.source_require_qualified')}}</label>
                @if (sourcePreview(source); as asset) { <p class="dp-note">{{i18n.t('dataops.work.source_preview',{version:asset.version,created:date(asset.created_at)})}} · {{asset.qualification ? i18n.t('dataops.status.'+asset.qualification.status) : i18n.t('dataops.unknown')}}</p>
                  @if (asset.qualification?.policy_digest || source.qualification_policy_digest) { <label class="dp-check"><input type="checkbox" [checked]="source.qualification_policy_digest !== null" (change)="sourcePolicy(n,$event)" />{{i18n.t('dataops.work.source_pin_policy')}}</label> }
                }
                <button type="button" class="dp-button" (click)="removeSource(n)">{{i18n.t('dataops.remove')}}</button></div>
              }
              <button type="button" class="dp-button" [disabled]="(form.inputs?.length ?? 0) >= 16" (click)="addSource()">{{i18n.t('dataops.work.add_source')}}</button>
            </section>
            <h3>{{i18n.t('dataops.work.expected_output')}}</h3>
            @for (field of form.fields; track $index; let n = $index) { <div class="dp-row"><label class="dp-field"><span>{{ i18n.t('dataops.work.schema_name') }}</span><input class="dp-input" [(ngModel)]="field.name" [name]="'field' + n" required /></label><label class="dp-field"><span>{{ i18n.t('dataops.work.schema_type') }}</span><select class="dp-input" [(ngModel)]="field.type" [name]="'type' + n">@for (kind of fieldTypes; track kind) { <option [value]="kind">{{ kind }}</option> }</select></label><button type="button" class="dp-button" [disabled]="form.fields.length === 1" (click)="removeField(n)">{{ i18n.t('dataops.remove') }}</button></div> }
            <button type="button" class="dp-button" (click)="addField()">{{ i18n.t('dataops.work.add_field') }}</button>
            <label class="dp-field"><span>{{ i18n.t('dataops.work.qualification') }}</span><input class="dp-input" [(ngModel)]="form.qualification_policy_digest" name="qualification_policy_digest" pattern="[a-f0-9]{64}" /></label>
            <p class="dp-note">{{ i18n.t('dataops.judge.review_required') }}</p><button class="dp-button" type="submit" [disabled]="busy() || !canCreate()">{{ i18n.t('dataops.work.save') }}</button>
          </form></details>
        }
        @for (contract of contracts(); track contract.id) { <section class="dp-section"><h2>{{ contract.logical_key }} · v{{ contract.version }}</h2><p class="dp-note">{{ i18n.t('dataops.work.owner') }}: {{ memberName(contract.owner_user_id) }} · {{ contract.definition.deadline }} {{ contract.definition.timezone }}</p>
          <a [navLink]="{type: 'system', ref: contract.system_id}">{{ systemName(contract.system_id) }}</a>
          @if (contract.definition.inputs?.length) { <section class="dp-section"><h3>{{i18n.t('dataops.work.sources')}}</h3>@for (source of contract.definition.inputs; track source.payload_key) { <p>{{source.logical_key}} · {{i18n.t('dataops.asset_kind.'+source.kind)}} → {{source.payload_key}}</p><p class="dp-note">{{i18n.t('dataops.work.source_max_age')}}: {{source.max_age_seconds}} · {{i18n.t('dataops.work.source_require_qualified')}}: {{i18n.t(source.require_qualified ? 'dataops.yes':'dataops.no')}} · {{i18n.t(source.representation === 'native_id' ? 'dataops.work.source_native_id':'dataops.work.source_asset_ref')}}</p> }</section> }
          @if (contract.published_at) {
            <p class="sd-status" data-state="active" data-testid="service-contract-status">{{ i18n.t('dataops.work.status.active', { date: date(contract.published_at) }) }}</p>
          } @else {
            <p class="sd-status" data-state="draft" data-testid="service-contract-status">{{ i18n.t('dataops.work.status.draft') }}</p>
            @if (workspace.isAdmin()) {
              <p class="dp-note">{{ i18n.t('dataops.work.activate_hint') }}</p>
              <button type="button" class="dp-button" data-testid="service-contract-activate" [disabled]="busy() || activateWrites()[contract.id]?.s === 'sent'" (click)="activate(contract.id)">{{ i18n.t('dataops.work.activate') }}</button>
            }
          }
          <app-write-outcome
            data-testid="service-contract-activate-outcome"
            [outcome]="activateWrites()[contract.id] ?? null"
            [confirmedLabel]="i18n.t('dataops.work.activate_confirmed')"
            [failedLabel]="i18n.t('dataops.work.activate_failed')"
            [verifiable]="true"
            (verify)="load()"
          />
        </section> }
      }
      @if (tab() === 'windows') {
        @for (window of windows(); track window.id) { <section class="dp-section"><h2>{{ window.logical_key }} · {{ i18n.t('dataops.status.' + window.status) }}</h2><p>{{ i18n.t('dataops.work.deadline') }}: {{ date(window.deadline_at) }}</p>
          <p class="dp-note">{{ i18n.t('dataops.work.measured_cost') }}: {{ window.measured_cost == null ? i18n.t('dataops.unknown') : window.measured_cost }} · {{ i18n.t('dataops.work.reserved_cost') }}: {{ window.reserved_cost ?? window.cost_used ?? i18n.t('dataops.unknown') }}</p>
          @if (window.candidate_ref) { <button type="button" class="dp-button" [disabled]="busy()" (click)="inspect(window)">{{ i18n.t('dataops.work.candidate') }} · v{{ window.candidate_ref.version }}</button> }
          @if (candidateFor(window); as candidate) {
            <p class="dp-note">{{ candidate.asset_ref.digest }}</p>
            @if (candidateDataset(candidate); as dataset) { <ck-dataset-preview [datasetId]="dataset" /> }
            <app-typed-judge-result [value]="candidateEvaluation(candidate)" />
            @if (objects(candidate).length) {
              <section class="dp-section"><h3>{{ i18n.t('dataops.work.files') }}</h3>
              @for (object of objectPage(window.id,candidate); track object.index) { <div class="dp-row"><span>{{ object.name || i18n.t('dataops.work.file_number',{number:object.index+1}) }} · {{ size(object.size) }}</span><button type="button" class="dp-button" [disabled]="busy()" (click)="openObject(window,object)">{{ i18n.t('dataops.work.inspect_file') }}</button></div> }
              <div class="dp-row"><button type="button" class="dp-button" [disabled]="objectOffset(window.id) === 0" (click)="objectMove(window.id,-1)">{{ i18n.t('dataops.previous') }}</button><span>{{ objectOffset(window.id)+1 }}–{{ objectEnd(window.id,candidate) }} / {{ objects(candidate).length }}</span><button type="button" class="dp-button" [disabled]="objectEnd(window.id,candidate) >= objects(candidate).length" (click)="objectMove(window.id,1)">{{ i18n.t('dataops.next') }}</button></div>
              </section>
            }
            @if (filePreview(); as preview) { @if (preview.windowId === window.id && preview.digest === candidate.asset_ref.digest) {
              <section class="dp-section"><div class="dp-row"><strong>{{preview.name}}</strong><a class="dp-button" [href]="preview.url" [download]="preview.name">{{i18n.t('dataops.work.download')}}</a><button type="button" class="dp-button" (click)="closePreview()">{{i18n.t('dataops.work.close_preview')}}</button></div>
              @if (preview.image) { <img class="dp-object-image" [src]="preview.url" [alt]="preview.name" /> }
              @if (preview.text !== null) { <pre class="dp-code">{{preview.text}}</pre>@if (preview.truncated) { <p class="dp-note">{{i18n.t('dataops.work.text_truncated')}}</p> } }
              </section>
            } }

            <details><summary>{{ i18n.t('dataops.work.manifest') }}</summary><pre class="dp-code">{{ json(candidate.manifest) }}</pre></details>
            <details><summary>{{ i18n.t('dataops.work.qualification_detail') }}</summary><pre class="dp-code">{{ json(candidate.qualification) }}</pre></details>
            @if (workspace.isAdmin() && window.status === 'awaiting_review') {
              <label class="dp-check"><input type="checkbox" [checked]="confirmed()[window.id] === true" (change)="confirm(window.id, $event)" />{{ i18n.t('dataops.work.confirm') }}</label>
              @if (candidate.qualification?.['status'] !== 'qualified') { <label class="dp-check"><input type="checkbox" [checked]="qualifications()[window.id] === true" [disabled]="candidate.qualification?.['status'] === 'rejected'" (change)="qualify(window.id, $event)" />{{ i18n.t('dataops.work.qualify') }}</label> }
              <label class="dp-field"><span>{{ i18n.t('dataops.work.note') }}</span><textarea class="dp-input" rows="2" maxlength="2000" [value]="notes()[window.id] ?? ''" (input)="note(window.id, $event)"></textarea></label>
              <div class="dp-row"><button type="button" class="dp-button" [disabled]="busy() || !canReview(window)" (click)="review(window, true)">{{ i18n.t('dataops.work.review') }}</button><button type="button" class="dp-button" [disabled]="busy() || !canReview(window, false)" (click)="review(window, false)">{{ i18n.t('dataops.work.reject') }}</button>
                <button type="button" class="dp-button" [disabled]="busy() || !canPublish(window)" (click)="publish(window)">{{ i18n.t('dataops.work.publish') }}</button></div>
            }
          }
          <app-write-outcome
            data-testid="service-publish-outcome"
            [outcome]="publishWrites()[window.id] ?? null"
            [confirmedLabel]="i18n.t('dataops.work.publish_confirmed')"
            [failedLabel]="i18n.t('dataops.work.publish_failed')"
          />
          @if (unknownReceipts().includes(window.id)) {
            <p class="dp-error" role="alert" data-testid="service-publish-unconfirmed">{{ i18n.t('dataops.work.unknown_receipt') }}</p>
            <button type="button" class="dp-button" [disabled]="busy()" (click)="select('receipts')">{{ i18n.t('dataops.work.check_receipts') }}</button>
          }
        </section> }
      }
      @if (tab() === 'receipts') { @for (receipt of receipts(); track receipt.id) { <section class="dp-section"><h2>{{ i18n.t('dataops.work.receipt') }} · {{ date(receipt.published_at) }}</h2><p>{{ receipt.destination }}</p><p class="dp-note">{{ receipt.asset_digest }}</p><button type="button" class="dp-button" [disabled]="busy()" (click)="openReceipt(receipt.id)">{{ i18n.t('dataops.work.open') }}</button><button type="button" class="dp-button" [disabled]="busy()" (click)="downloadReceipt(receipt.id)">{{i18n.t('dataops.work.download_receipt')}}</button>@if (selectedReceipt()?.id === receipt.id) { <pre class="dp-code">{{ json(selectedReceipt()) }}</pre> }</section> } }
      @if (tab() === 'incidents') { @for (incident of incidents(); track incident.id) { <section class="dp-section"><h2>{{ incident.code }}</h2><p>{{ date(incident.created_at) }}</p><a [navLink]="{surface: 'review-queue'}">{{ i18n.t('dataops.work.review_queue') }}</a></section> } }
      @if (!total() && !busy()) { <p class="dp-note">{{ i18n.t('dataops.work.empty') }}</p> }
      <div class="dp-row dp-section"><button type="button" class="dp-button" [disabled]="busy() || offset() === 0" (click)="page(-1)">{{ i18n.t('dataops.previous') }}</button><span>{{ total() ? offset() + 1 : 0 }}–{{ end() }} / {{ total() }}</span><button type="button" class="dp-button" [disabled]="busy() || offset() + 25 >= total()" (click)="page(1)">{{ i18n.t('dataops.next') }}</button></div>
    </main></div>
  `,
})
export class ServiceDeliveryComponent implements OnInit {
  private readonly destroyRef = inject(DestroyRef);
  private readonly downloadUrls = new Set<string>();
  private readonly objectOffsets = signal<Record<string,number>>({});
  readonly filePreview = signal<{windowId:string; digest:string; name:string; url:string; image:boolean; text:string|null; truncated:boolean}|null>(null);
  constructor() {
    effect(() => { this.workspace.currentSlug(); this.workspace.contextEpoch(); untracked(() => { this.closePreview(); this.sourceAssets.set([]); this.sourceOffset.set(0); this.sourceTotal.set(0); this.form.inputs = []; }); });
    this.destroyRef.onDestroy(() => { this.closePreview(); for (const url of this.downloadUrls) URL.revokeObjectURL(url); this.downloadUrls.clear(); });
  }
  readonly i18n = inject(I18nService); readonly workspace = inject(WorkspaceService); private readonly api = inject(ServiceDeliveryApi); private readonly canonical = inject(CanonicalApiService);
  readonly tabs: Tab[] = ['contracts', 'windows', 'receipts', 'incidents']; readonly tab = signal<Tab>('windows'); readonly busy = signal(false); readonly error = signal(''); readonly notice = signal('');
  readonly contracts = signal<ServiceContract[]>([]); readonly windows = signal<ServiceWindow[]>([]); readonly receipts = signal<DeliveryReceipt[]>([]); readonly incidents = signal<ServiceIncident[]>([]);
  readonly systems = signal<Array<{id: string; name: string}>>([]); readonly members = signal<WorkspaceMemberDetail[]>([]); readonly offset = signal(0); readonly total = signal(0);
  readonly sourceAssets = signal<ServiceAssetMetadata[]>([]); readonly sourceOffset = signal(0); readonly sourceTotal = signal(0); readonly sourcesLoading = signal(false); readonly sourceError = signal(false);
  readonly candidates = signal<Record<string, CandidateEvidence>>({}); readonly notes = signal<Record<string, string | undefined>>({}); readonly confirmed = signal<Record<string, boolean>>({});
  readonly candidateFences = signal<Record<string, number>>({});
  /** Activation and delivery outcomes, said next to their button until the next attempt. */
  readonly activateWrites = signal<Record<string, WriteOutcome>>({});
  readonly publishWrites = signal<Record<string, WriteOutcome>>({});
  readonly qualifications = signal<Record<string, boolean>>({});
  readonly reviews = signal<Record<string, BoundReview | undefined>>({}); readonly unknownReceipts = signal<string[]>([]); readonly selectedReceipt = signal<DeliveryReceipt | null>(null);
  readonly budgetFields = ['max_attempts', 'max_cost', 'max_tokens', 'max_seconds'] as const; readonly fieldTypes = ['string', 'integer', 'number', 'boolean', 'object', 'array'];
  form: ServiceContractForm = { system_id: '', logical_key: '', owner_user_id: '', timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, starts_on: '', deadline: '17:00', max_attempts: 1, max_cost: 0, max_tokens: 0, max_seconds: 900, fields: [{name: '', type: 'string'}], qualification_policy_digest: '', inputs: [] };
  async ngOnInit(): Promise<void> { await this.load(); const slug = this.workspace.currentSlug(); if (this.workspace.isAdmin() && slug) { try { const [systems, members] = await Promise.all([firstValueFrom(this.canonical.listSystems({propagateErrors: true})), firstValueFrom(this.workspace.listMembers(slug))]); this.systems.set(systems); this.members.set(members); await this.loadSources(true); } catch { this.error.set('dataops.error.load'); } } }
  async load(): Promise<void> { if (this.busy()) return; this.busy.set(true); this.error.set(''); try { let page: Page<unknown>; switch (this.tab()) { case 'contracts': { const p = await this.api.contracts(this.offset()); this.contracts.set(p.items); page = p; break; } case 'windows': { const p = await this.api.windows(this.offset()); this.windows.set(p.items); page = p; break; } case 'receipts': { const p = await this.api.receipts(this.offset()); this.receipts.set(p.items); this.unknownReceipts.update(ids => ids.filter(id => !p.items.some(r => r.window_id === id))); page = p; break; } default: { const p = await this.api.incidents(this.offset()); this.incidents.set(p.items); page = p; } } this.total.set(page.total); } catch { this.error.set('dataops.error.load'); } finally { this.busy.set(false); } }
  select(tab: Tab): void { if (this.busy()) return; this.tab.set(tab); this.offset.set(0); void this.load(); }
  page(direction: -1 | 1): void { this.offset.update(offset => Math.max(0, offset + direction * 25)); void this.load(); }
  end(): number { return Math.min(this.offset() + 25, this.total()); }
  date(value: string): string { const date = new Date(/[Z+-]\d*:?\d*$/.test(value.slice(10)) ? value : value + 'Z'); return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(this.i18n.locale(), {dateStyle: 'medium', timeStyle: 'short'}).format(date); }
  json(value: unknown): string { return JSON.stringify(value, null, 2); }
  memberName(id: string): string { return this.members().find(m => m.user_id === id)?.username ?? id; }
  systemName(id: string): string { return this.systems().find(s => s.id === id)?.name ?? this.i18n.t('dataops.work.system'); }
  candidateFor(window: ServiceWindow): CandidateEvidence | null { const candidate = this.candidates()[window.id]; return candidate?.asset_ref.digest === window.candidate_ref?.digest && this.candidateFences()[window.id] === window.fence ? candidate : null; }
  candidateDataset(candidate: CandidateEvidence): string | null { return candidateDatasetId(candidate); }
  candidateEvaluation(candidate: CandidateEvidence): unknown { return candidate.qualification?.['typed_evaluation'] ?? candidate.manifest['typed_evaluation'] ?? candidate.manifest['output'] ?? null; }
  confirm(id: string, event: Event): void { this.confirmed.update(values => ({...values, [id]: (event.target as HTMLInputElement).checked})); }
  note(id: string, event: Event): void { this.notes.update(values => ({...values, [id]: (event.target as HTMLInputElement).value})); }
  qualify(id: string, event: Event): void { this.qualifications.update(values => ({...values, [id]: (event.target as HTMLInputElement).checked})); }
  canReview(window: ServiceWindow, accept = true): boolean { return !!reviewRequest(window, this.candidateFor(window), this.confirmed()[window.id], this.notes()[window.id] ?? '', accept, this.qualifications()[window.id] === true); }
  canPublish(window: ServiceWindow): boolean { return !!publicationRequest(window, this.reviews()[window.id], this.unknownReceipts().includes(window.id)); }
  private async action(work: () => Promise<void>): Promise<void> { if (this.busy()) return; this.busy.set(true); this.error.set(''); this.notice.set(''); try { await work(); } catch { this.error.set('dataops.error.request'); } finally { this.busy.set(false); } }
  inspect(window: ServiceWindow): Promise<void> { return this.action(async () => { const candidate = await this.api.candidate(window.id); this.closePreview(); this.objectOffsets.update(values => ({...values,[window.id]:0})); this.candidates.update(values => ({...values, [window.id]: candidate})); this.candidateFences.update(values => ({...values, [window.id]: window.fence})); this.confirmed.update(values => ({...values, [window.id]: false})); this.qualifications.update(values => ({...values, [window.id]: false})); }); }
  review(window: ServiceWindow, accept: boolean): Promise<void> { return this.action(async () => { const body = reviewRequest(window, this.candidateFor(window), this.confirmed()[window.id], this.notes()[window.id] ?? '', accept, this.qualifications()[window.id] === true); if (!body || !this.canReview(window, accept)) return; const decision = await this.api.review(window.id, body); this.reviews.update(values => ({...values, [window.id]: {decision, window_id: window.id, fence: window.fence, asset_digest: window.candidate_ref!.digest}})); this.notice.set('dataops.work.reviewed'); if (!accept) this.windows.update(rows => rows.map(row => row.id === window.id ? {...row, status: 'failed'} : row)); }); }
  /**
   * Delivery under the write contract. A delivery whose answer was lost, or
   * that broke on the server, is "not confirmed": it may have been published,
   * so it stays blocked until the receipts are read again.
   */
  publish(window: ServiceWindow): void {
    if (this.busy() || this.publishWrites()[window.id]?.s === 'sent') return;
    const body = publicationRequest(window, this.reviews()[window.id], this.unknownReceipts().includes(window.id));
    if (!body) return;
    this.error.set(''); this.notice.set('');
    settleWrite(this.api.publish$(window.id, body)).subscribe((raw) => {
      const outcome: WriteOutcome = raw.s === 'failed' && (raw.status ?? 500) >= 500 ? { s: 'unknown', status: raw.status, code: raw.code } : raw;
      this.publishWrites.update(values => ({...values, [window.id]: outcome}));
      if (outcome.s === 'confirmed' || outcome.s === 'accepted') {
        this.selectedReceipt.set(outcome.value as DeliveryReceipt);
        this.windows.update(rows => rows.map(row => row.id === window.id ? {...row, status: 'delivered'} : row));
      } else if (outcome.s === 'unknown') {
        this.unknownReceipts.update(ids => [...new Set([...ids, window.id])]);
      }
    });
  }
  openReceipt(id: string): Promise<void> { return this.action(async () => { this.selectedReceipt.set(await this.api.receipt(id)); }); }
  objects(candidate: CandidateEvidence): CandidateObject[] { return candidateObjects(candidate); }
  objectOffset(id: string): number { return this.objectOffsets()[id] ?? 0; }
  objectPage(id: string, candidate: CandidateEvidence): CandidateObject[] { return this.objects(candidate).slice(this.objectOffset(id),this.objectOffset(id)+25); }
  objectEnd(id: string, candidate: CandidateEvidence): number { return Math.min(this.objectOffset(id)+25,this.objects(candidate).length); }
  objectMove(id: string, direction: number): void { this.objectOffsets.update(values => ({...values,[id]:Math.max(0,(values[id] ?? 0)+direction*25)})); }
  size(bytes: number): string { return bytes < 1024 ? bytes + ' B' : bytes < 1048576 ? (bytes/1024).toFixed(1)+' KiB' : (bytes/1048576).toFixed(1)+' MiB'; }
  closePreview(): void { const current = this.filePreview(); if (current) URL.revokeObjectURL(current.url); this.filePreview.set(null); }
  openObject(window: ServiceWindow, object: CandidateObject): Promise<void> { return this.action(async () => {
    const candidate = this.candidateFor(window); if (!candidate) return;
    const scope = this.workspace.captureRequestScope();
    const response = await this.api.candidateObject(window.id,object.index,candidate.asset_ref.digest,window.fence);
    const blob = response.body; if (!blob) throw new Error('empty object');
    const name = downloadName(response.headers.get('Content-Disposition'),object.name || `file-${object.index+1}`);
    const mime = blob.type.split(';')[0].toLowerCase();
    const isText = ['text/plain','text/csv','text/markdown','application/json'].includes(mime);
    const text = isText ? await blob.slice(0,128000).text() : null;
    if (this.destroyRef.destroyed || !this.workspace.isRequestScopeCurrent(scope)) return;
    this.closePreview(); this.filePreview.set({windowId:window.id,digest:candidate.asset_ref.digest,name,url:URL.createObjectURL(blob),image:['image/png','image/jpeg','image/webp','image/gif'].includes(mime),text,truncated:isText && blob.size > 128000});
  }); }
  downloadReceipt(id: string): Promise<void> { return this.action(async () => {
    const response = await this.api.downloadReceipt(id); if (!response.body || this.destroyRef.destroyed) return;
    const url = URL.createObjectURL(response.body); this.downloadUrls.add(url);
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = downloadName(response.headers.get('Content-Disposition'),`receipt-${id}.zip`); anchor.click();
    setTimeout(() => { URL.revokeObjectURL(url); this.downloadUrls.delete(url); },30000);
  }); }
  async loadSources(reset = false): Promise<void> {
    if (this.sourcesLoading() || !this.workspace.isAdmin()) return;
    this.sourcesLoading.set(true); this.sourceError.set(false);
    try { const page = await this.api.assets(reset ? 0 : this.sourceOffset()); const byId = new Map((reset ? [] : this.sourceAssets()).map(asset => [asset.asset_ref.asset_id,asset])); for (const asset of page.items) byId.set(asset.asset_ref.asset_id,asset); this.sourceAssets.set([...byId.values()]); this.sourceOffset.set(page.offset+page.limit); this.sourceTotal.set(page.total); }
    catch { this.sourceError.set(true); } finally { this.sourcesLoading.set(false); }
  }
  sourceChoices(): ServiceAssetMetadata[] {
    const latest = new Map<string,ServiceAssetMetadata>(); for (const asset of this.sourceAssets()) { const key = asset.kind+':'+asset.logical_key; if (!latest.has(key) || latest.get(key)!.version < asset.version) latest.set(key,asset); } return [...latest.values()];
  }
  sourcePreview(source: ServiceSourceForm): ServiceAssetMetadata | null { const selected = source.asset; return selected ? this.sourceChoices().find(asset => asset.kind === selected.kind && asset.logical_key === selected.logical_key) ?? selected : null; }
  addSource(): void { const inputs = this.form.inputs ?? []; if (inputs.length >= 16) return; this.form.inputs = [...inputs,{asset:null,payload_key:inputs.length ? `input_${inputs.length+1}` : 'dataset_id',max_age_seconds:86400,require_qualified:true,qualification_policy_digest:null,representation:'asset_ref'}]; }
  removeSource(index: number): void { this.form.inputs = (this.form.inputs ?? []).filter((_,n) => n !== index); }
  chooseSource(index: number, id: string): void { const source = this.form.inputs?.[index]; if (!source) return; source.asset = this.sourceAssets().find(asset => asset.asset_ref.asset_id === id) ?? null; source.representation = source.asset?.kind === 'dataset' ? 'native_id' : 'asset_ref'; source.qualification_policy_digest = null; if (['dataset_id','source_ref'].includes(source.payload_key)) source.payload_key = source.asset?.kind === 'dataset' ? 'dataset_id' : 'source_ref'; }
  sourcePolicy(index: number, event: Event): void { const source = this.form.inputs?.[index]; if (!source) return; source.qualification_policy_digest = (event.target as HTMLInputElement).checked ? this.sourcePreview(source)?.qualification?.policy_digest ?? null : null; }
  canCreate(): boolean { return contractRequest(this.form) != null; }
  addField(): void { this.form.fields.push({name: '', type: 'string'}); }
  removeField(index: number): void { this.form.fields.splice(index, 1); }
  create(): Promise<void> { return this.action(async () => { const body = contractRequest(this.form); if (body) { const created = await this.api.create(body); this.contracts.update(rows => [created, ...rows]); this.total.update(total => total + 1); } }); }
  /** The contract was saved first; activating it is the second, explicit step. */
  activate(id: string): void {
    if (this.busy() || this.activateWrites()[id]?.s === 'sent') return;
    this.error.set(''); this.notice.set('');
    settleWrite(this.api.activate$(id)).subscribe((outcome) => {
      this.activateWrites.update(values => ({...values, [id]: outcome}));
      if ((outcome.s === 'confirmed' || outcome.s === 'accepted') && outcome.value) {
        this.contracts.update(rows => rows.map(row => row.id === id ? outcome.value : row));
      }
    });
  }
}
