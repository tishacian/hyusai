import { ChangeDetectionStrategy, Component, computed, ElementRef, inject, signal, viewChild } from '@angular/core';
import { Router } from '@angular/router';
import { HelpTooltipComponent, NavLinkDirective } from '@app/shared/cockpit';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { I18nService } from '@app/core/i18n.service';
import { ExperienceRuntimeHostComponent } from '../runtime/runtime-host.component';
import { SystemHomeService } from '../system-home.service';
import {
  apiCode,
  studioError,
  StudioApiService,
  type StudioBinding,
  type StudioIngress,
} from './studio-api.service';
import { pagesPayload } from './studio-document';
import {
  ACCESS_ROLES,
  bindSeedDocument,
  CONFIRMATION_POLICIES,
  EXPERIENCE_PATTERNS,
  experienceSlug,
  isDataLedPattern,
  seedDocument,
  templateOutputCompatible,
  uniqueBindingKey,
  uniqueExperienceSlug,
  type ExperiencePattern,
} from './studio-model';
import type { System } from '@app/core/canonical-api.service';
import { formSchemaSupported, type ExperienceDocument } from '../runtime/model';

@Component({
  selector: 'app-experience-wizard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NavLinkDirective, HelpTooltipComponent, ExperienceRuntimeHostComponent],
  styleUrl: './studio.scss',
  template: `
    <section class="xp-wizard" aria-labelledby="xp-wiz-heading">
      <h1 #wizardHeading id="xp-wiz-heading" class="sr-only" tabindex="-1">{{ stepTitle() }}</h1>
      <header class="xp-wizard-topbar">
        <button type="button" class="xp-wizard-close" (click)="closeWizard()">
          × {{ i18n.t('experience.wizard.close') }}
        </button>
        <div class="xp-wizard-title">
          <strong>{{ i18n.t('experience.wizard.title') }}</strong>
          <span>{{ i18n.t(experienceId() ? 'experience.wizard.created' : 'experience.wizard.not_created') }}</span>
        </div>
        <button
          type="button"
          class="xp-btn"
          [disabled]="busy() || stagedBindings().length > 0 || (step() === 3 && !canFinish())"
          (click)="saveAndClose()"
        >
          {{ i18n.t(experienceId() ? 'experience.wizard.save_close' : 'experience.wizard.close') }}
        </button>
      </header>

      <ol class="xp-steps" [attr.aria-label]="i18n.t('experience.wizard.step.of', { current: step(), total: 3 })">
        @for (label of stepLabels; track label; let i = $index) {
          <li
            [class.is-on]="step() === i + 1"
            [class.is-done]="step() > i + 1"
            [attr.aria-current]="step() === i + 1 ? 'step' : null"
          >
            <span class="xp-step-n">{{ i + 1 }}</span>
            {{ i18n.t(label) }}
          </li>
        }
      </ol>
      <p class="sr-only" role="status" aria-live="polite" aria-atomic="true">{{ stepAnnouncement() }}</p>

      <div class="xp-wizard-body">
        @if (error(); as err) {
          <p class="xp-error" role="alert">{{ err }}</p>
        }
        @if (notice(); as message) {
          <p class="xp-note" role="status">{{ message }}</p>
        }

      @switch (step()) {
        @case (1) {
          <label class="xp-field" for="xp-wiz-name">
            <span>{{ i18n.t('experience.wizard.name') }}</span>
            <input
              id="xp-wiz-name"
              type="text"
              [value]="name()"
              [placeholder]="i18n.t('experience.wizard.name.placeholder')"
              (input)="onName($event)"
            />
          </label>
          <label class="xp-field" for="xp-wiz-description">
            <span>{{ i18n.t('experience.identity.description') }}</span>
            <textarea
              id="xp-wiz-description"
              rows="2"
              maxlength="500"
              [value]="description()"
              [placeholder]="i18n.t('experience.identity.description.placeholder')"
              (input)="description.set(inputValue($event))"
            ></textarea>
            <small class="xp-hint">{{ i18n.t('experience.identity.description.hint') }}</small>
          </label>
          <label class="xp-field" for="xp-wiz-emblem">
            <span>{{ i18n.t('experience.identity.emblem') }}</span>
            <select id="xp-wiz-emblem" [value]="emblem()" (change)="emblem.set(selectValue($event))">
              @for (option of emblemOptions; track option.value) {
                <option [value]="option.value">{{ option.value }} · {{ i18n.t(option.label) }}</option>
              }
            </select>
          </label>
          @if (slug()) {
            <p class="xp-hint">{{ i18n.t('experience.wizard.slug') }} · /work/{{ slug() }}</p>
          } @else {
            <p class="xp-hint">{{ i18n.t('experience.wizard.slug.pending') }}</p>
          }

          <div class="xp-cards" role="radiogroup" [attr.aria-label]="i18n.t('experience.wizard.pattern.aria')">
            @for (pattern of patterns; track pattern; let i = $index) {
              <button
                type="button"
                class="xp-choice"
                role="radio"
                [attr.aria-checked]="!fromHome() && selectedPattern() === pattern"
                [tabIndex]="!fromHome() && selectedPattern() === pattern ? 0 : -1"
                (click)="pickPattern(pattern)"
                (keydown)="onPatternKey($event, i)"
              >
                <span class="xp-thumb" aria-hidden="true">
                  <i class="is-wide"></i>
                  <i [class]="thumbLead(pattern)"></i>
                  <i class="is-half"></i>
                </span>
                <span class="xp-choice-head">
                  <strong>{{ i18n.t('experience.work.pattern.' + pattern) }}</strong>
                  @if (!fromHome() && selectedPattern() === pattern) {
                    <span class="xp-choice-on">{{ i18n.t('experience.wizard.pattern.selected') }}</span>
                  }
                </span>
                <p>{{ i18n.t('experience.wizard.pattern.' + pattern + '.body') }}</p>
                <p class="xp-choice-eg">{{ i18n.t('experience.wizard.pattern.' + pattern + '.example') }}</p>
              </button>
            }
            @if (homeDoc()) {
              <button
                type="button"
                class="xp-choice"
                role="radio"
                [attr.aria-checked]="fromHome()"
                [tabIndex]="fromHome() ? 0 : -1"
                (click)="pickHome()"
                (keydown)="onPatternKey($event, patterns.length)"
              >
                <span class="xp-thumb" aria-hidden="true">
                  <i class="is-wide is-accent"></i>
                  <i class="is-wide is-tall"></i>
                  <i class="is-half"></i>
                </span>
                <span class="xp-choice-head">
                  <strong>{{ i18n.t('experience.wizard.home.option') }}</strong>
                  @if (fromHome()) {
                    <span class="xp-choice-on">{{ i18n.t('experience.wizard.pattern.selected') }}</span>
                  }
                </span>
                <p>{{ i18n.t('experience.wizard.home.body') }}</p>
              </button>
            }
          </div>
        }
        @case (2) {
          <p class="xp-note">{{ i18n.t('experience.wizard.bind.intro') }}</p>
          <div class="xp-bind-grid">
            <section class="xp-bind" [attr.aria-label]="i18n.t('experience.wizard.bind.catalog')">
              <div class="xp-bind-head">
                <h3>{{ i18n.t('experience.wizard.bind.catalog') }}</h3>
                <ck-help id="concept.entry-point" />
              </div>
              <label class="xp-search">
                <span class="sr-only">{{ i18n.t('experience.wizard.bind.search') }}</span>
                <input
                  type="search"
                  [value]="systemQuery()"
                  [placeholder]="i18n.t('experience.wizard.bind.search')"
                  (input)="systemQuery.set(inputValue($event))"
                />
              </label>
              @if (systemsState() === 'loading') {
                <p class="xp-hint" role="status">{{ i18n.t('experience.wizard.bind.systems.loading') }}</p>
              } @else if (systemsState() === 'error') {
                <div class="xp-error" role="alert">
                  <p>{{ i18n.t('experience.wizard.bind.systems.error') }}</p>
                  <button type="button" class="xp-btn" (click)="loadSystems()">
                    {{ i18n.t('experience.wizard.retry') }}
                  </button>
                </div>
              } @else if (systems().length === 0) {
                <p class="xp-hint">{{ i18n.t('experience.wizard.bind.none_published') }}</p>
              } @else if (visibleSystems().length === 0) {
                <p class="xp-hint">{{ i18n.t('experience.wizard.bind.no_match') }}</p>
              }
              @for (sys of visibleSystems(); track sys.id) {
                <article class="xp-sys">
                  <div class="xp-sys-head">
                    <strong>{{ sys.name }}</strong>
                    @if (entryState(sys.id) === 'ready') {
                      <span class="xp-bind-count">{{ entriesOf(sys.id).length }}</span>
                    }
                  </div>
                  @if (entryState(sys.id) === 'loading') {
                    <p class="xp-hint" role="status">{{ i18n.t('experience.wizard.bind.entries.loading') }}</p>
                  } @else if (entryState(sys.id) === 'error') {
                    <div class="xp-error" role="alert">
                      <p>{{ i18n.t('experience.wizard.bind.entries.error') }}</p>
                      <button type="button" class="xp-btn" (click)="loadEntriesFor(sys.id)">
                        {{ i18n.t('experience.wizard.retry') }}
                      </button>
                    </div>
                  } @else {
                    @for (entry of entriesOf(sys.id); track entry.ingress_id) {
                    <div class="xp-entry">
                      <span>{{ entryLabel(entry) }}</span>
                      @if (linkedKey(sys.id, entry.ingress_id)) {
                        <span class="xp-entry-on">{{ i18n.t('experience.wizard.bind.linked') }}</span>
                      } @else {
                        <button
                          type="button"
                          class="xp-btn"
                          [disabled]="busy() || bindingsState() !== 'ready'"
                          (click)="link(sys.id, entry.ingress_id)"
                        >
                          {{ i18n.t('experience.wizard.bind.link') }}
                        </button>
                      }
                    </div>
                    } @empty {
                      <p class="xp-hint">{{ i18n.t('experience.wizard.bind.no_entry') }}</p>
                    }
                  }
                </article>
              }
            </section>

            <section class="xp-bind" [attr.aria-label]="i18n.t('experience.wizard.bind.selected')">
              <div class="xp-bind-head">
                <h3>{{ i18n.t('experience.wizard.bind.selected') }}</h3>
                <span class="xp-bind-count">{{ selectedKeys().length }}</span>
              </div>
              @if (bindingsState() === 'loading') {
                <p class="xp-hint" role="status">{{ i18n.t('experience.wizard.bind.bindings.loading') }}</p>
              } @else if (bindingsState() === 'error') {
                <div class="xp-error" role="alert">
                  <p>{{ i18n.t('experience.wizard.bind.bindings.error') }}</p>
                  <button type="button" class="xp-btn" (click)="loadBindings()">
                    {{ i18n.t('experience.wizard.retry') }}
                  </button>
                </div>
              }
              @for (row of selectedBindings(); track row.binding_key) {
                <article class="xp-bcard">
                  <div class="xp-bcard-head">
                    <strong>{{ systemName(row.system_id) }}</strong>
                    @if (isHomeSource(row.binding_key)) {
                      <span class="xp-entry-on">{{ i18n.t('experience.wizard.home.source') }}</span>
                    } @else {
                      <button type="button" class="xp-btn" (click)="toggleKey(row.binding_key)">
                        {{ i18n.t('experience.wizard.bind.unlink') }}
                      </button>
                    }
                  </div>
                  <dl class="xp-kv">
                    <dt>{{ i18n.t('experience.wizard.bind.inputs') }}</dt>
                    <dd>{{ row.ingress_id }}</dd>
                    <dt>{{ i18n.t('experience.wizard.bind.confirmation') }}</dt>
                    <dd>{{ confirmLabel(row.confirmation_policy) }}</dd>
                  </dl>
                  <details>
                    <summary class="xp-hint">{{ i18n.t('experience.editor.action.advanced') }}</summary>
                    <p class="xp-hint">{{ i18n.t('experience.editor.action.key') }} · {{ row.binding_key }}</p>
                  </details>
                </article>
              } @empty {
                <p class="xp-hint">{{ i18n.t('experience.wizard.bind.selected.empty') }}</p>
              }
              @if (reusable().length > 0) {
                <p class="xp-hint">{{ i18n.t('experience.wizard.bind.existing') }}</p>
                @for (row of reusable(); track row.binding_key) {
                  <div class="xp-entry">
                    <span>{{ systemName(row.system_id) }} · {{ row.ingress_id }}</span>
                    <button type="button" class="xp-btn" (click)="toggleKey(row.binding_key)">
                      {{ i18n.t('experience.wizard.bind.link') }}
                    </button>
                  </div>
                }
              }
              <p class="xp-hint">{{ i18n.t('experience.wizard.bind.editable') }}</p>
              @if (stagedBindings().length > 0) {
                <p class="xp-note" role="status">{{ i18n.t('experience.wizard.bind.staged') }}</p>
              }
              @if (!selectedContractsReady()) {
                <p class="xp-error" role="alert">{{ contractErrorText() }}</p>
              }
            </section>
          </div>
        }
        @default {
          <fieldset class="xp-wizard-fieldset xp-row">
            <legend>{{ i18n.t('experience.wizard.access.languages') }}</legend>
            <label class="xp-check">
              <input type="checkbox" [checked]="langs().includes('fr')" (change)="toggleLang('fr')" />
              {{ i18n.t('experience.work.lang.fr') }}
            </label>
            <label class="xp-check">
              <input type="checkbox" [checked]="langs().includes('en')" (change)="toggleLang('en')" />
              {{ i18n.t('experience.work.lang.en') }}
            </label>
          </fieldset>
          @if (langs().length === 0) {
            <p class="xp-error" role="alert">{{ i18n.t('experience.wizard.access.language_required') }}</p>
          }
          <label class="xp-field">
            <span>{{ i18n.t('experience.wizard.access.theme') }}</span>
            <select [value]="themeMode()" (change)="themeMode.set(selectValue($event))">
              <option value="default">{{ i18n.t('experience.wizard.access.theme.default') }}</option>
              <option value="dark">{{ i18n.t('experience.wizard.access.theme.dark') }}</option>
              <option value="light">{{ i18n.t('experience.wizard.access.theme.light') }}</option>
            </select>
          </label>
          <fieldset class="xp-wizard-fieldset">
            <legend>{{ i18n.t('experience.wizard.access.who') }}</legend>
            <p class="xp-hint">{{ i18n.t('experience.wizard.access.who.hint') }}</p>
            <label class="xp-check">
              <input type="checkbox" [checked]="wholeWorkspace()" (change)="toggleWholeWorkspace()" />
              {{ i18n.t('experience.wizard.access.whole_workspace') }}
            </label>
            @for (role of roles; track role) {
              <label class="xp-check">
                <input
                  type="checkbox"
                  [checked]="audience().includes(role)"
                  [disabled]="wholeWorkspace()"
                  (change)="toggleRole(role)"
                />
                {{ i18n.t('governance.access.role.' + role) }}
              </label>
            }
            <label class="xp-field" for="xp-wiz-groups">
              <span>{{ i18n.t('experience.wizard.access.groups') }}</span>
              <input
                id="xp-wiz-groups"
                type="text"
                [value]="groups().join(', ')"
                [disabled]="wholeWorkspace()"
                [placeholder]="i18n.t('experience.wizard.access.groups.placeholder')"
                (input)="onGroups($event)"
              />
              <small class="xp-hint">{{ i18n.t('experience.wizard.access.groups.hint') }}</small>
            </label>
          </fieldset>
          <h3>{{ i18n.t('experience.wizard.preview') }}</h3>
          <p class="xp-hint" role="status">{{ i18n.t('experience.wizard.preview.safe') }}</p>
          <div class="xp-wizard-preview" inert>
            <app-experience-runtime-host [document]="previewDoc()" />
          </div>
        }
      }

      <footer class="xp-foot">
        @if (step() > 1) {
          <button type="button" class="xp-btn" [disabled]="busy()" (click)="back()">
            {{ i18n.t('experience.wizard.back') }}
          </button>
        } @else {
          <a [navLink]="{ surface: 'create-apps' }" class="xp-btn">{{ i18n.t('common.cancel') }}</a>
        }
        <div class="xp-foot-end">
          @if (step() === 1 && !canNext()) {
            <span class="xp-hint">{{ i18n.t('experience.wizard.name.required') }}</span>
          }
          @if (step() < 3) {
            <button type="button" class="xp-btn xp-btn-primary" [disabled]="busy() || !canAdvance()" (click)="next()">
              {{ busy()
                ? i18n.t(experienceId() ? 'experience.wizard.saving' : 'experience.wizard.creating')
                : i18n.t(experienceId() ? 'experience.wizard.next' : 'experience.wizard.create_continue') }}
            </button>
          } @else {
            @if (langs().length === 0) {
              <span class="xp-hint">{{ i18n.t('experience.wizard.access.language_required') }}</span>
            } @else if (!hasAudienceChoice()) {
              <span class="xp-hint">{{ i18n.t('experience.wizard.access.required') }}</span>
            } @else if (!selectedContractsReady()) {
              <span class="xp-hint">{{ contractErrorText() }}</span>
            }
            <button type="button" class="xp-btn xp-btn-primary" [disabled]="busy() || !canFinish()" (click)="finish()">
              {{ busy() ? i18n.t('experience.wizard.saving') : i18n.t('experience.wizard.finish') }}
            </button>
          }
        </div>
      </footer>
      </div>
    </section>
  `,
})
export class ExperienceWizardComponent {
  readonly i18n = inject(I18nService);
  private readonly api = inject(StudioApiService);
  private readonly home = inject(SystemHomeService);
  private readonly router = inject(Router);
  private readonly navigation = inject(ZoomContextService);
  private readonly wizardHeading = viewChild<ElementRef<HTMLHeadingElement>>('wizardHeading');

  readonly patterns = EXPERIENCE_PATTERNS;
  readonly confirms = CONFIRMATION_POLICIES;
  readonly roles = ACCESS_ROLES;
  readonly stepLabels = [
    'experience.wizard.step.model',
    'experience.wizard.step.bind',
    'experience.wizard.step.access',
  ] as const;
  readonly emblemOptions = [
    { value: '◇', label: 'experience.identity.emblem.diamond' },
    { value: '✦', label: 'experience.identity.emblem.sparkle' },
    { value: '✓', label: 'experience.identity.emblem.check' },
    { value: '▦', label: 'experience.identity.emblem.grid' },
    { value: '◆', label: 'experience.identity.emblem.shield' },
    { value: '⚑', label: 'experience.identity.emblem.flag' },
  ] as const;

  readonly step = signal(1);
  readonly name = signal('');
  readonly description = signal('');
  readonly emblem = signal('◇');
  readonly slug = signal('');
  readonly slugDirty = signal(false);
  readonly selectedPattern = signal<ExperiencePattern>('form_result');
  readonly fromHome = signal(false);
  readonly experienceId = signal<string | null>(null);
  readonly draftRevision = signal(1);
  readonly experienceUpdatedAt = signal<string | null>(null);
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly notice = signal<string | null>(null);
  readonly taken = signal<string[]>([]);
  readonly bindings = signal<StudioBinding[]>([]);
  readonly stagedBindings = signal<StudioBinding[]>([]);
  readonly bindingsState = signal<'loading' | 'ready' | 'error'>('loading');
  readonly selectedKeys = signal<string[]>([]);
  readonly systems = signal<Array<System & { published_flow_version_id?: string | null }>>([]);
  readonly systemsState = signal<'loading' | 'ready' | 'error'>('loading');
  readonly entries = signal<Record<string, StudioIngress[]>>({});
  readonly outputSchemas = signal<Record<string, unknown>>({});
  readonly entryStates = signal<Record<string, 'loading' | 'ready' | 'error'>>({});
  readonly versions = signal<Record<string, string>>({});
  readonly systemQuery = signal('');
  readonly langs = signal<string[]>([this.i18n.locale()]);
  readonly themeMode = signal('default');
  readonly audience = signal<string[]>([]);
  readonly groups = signal<string[]>([]);
  readonly wholeWorkspace = signal(false);
  readonly homePreview = computed(() => this.home.preview());
  readonly homeDoc = computed(() => this.home.document());
  readonly visibleSystems = computed(() => {
    const query = this.systemQuery().trim().toLocaleLowerCase();
    return query
      ? this.systems().filter((row) => row.name.toLocaleLowerCase().includes(query))
      : this.systems();
  });

  readonly previewDoc = computed(() => this.document());
  readonly allBindings = computed(() => [...this.bindings(), ...this.stagedBindings()]);

  /** Bindings attached to this app, in the order the author picked them. */
  readonly selectedBindings = computed(() => {
    const rows = this.allBindings();
    return this.selectedKeys()
      .map((key) => rows.find((row) => row.binding_key === key))
      .filter((row): row is StudioBinding => !!row);
  });

  /** Workspace bindings not attached yet — reusable without creating a twin. */
  readonly reusable = computed(() => {
    const picked = new Set(this.selectedKeys());
    return this.bindings().filter((row) => !picked.has(row.binding_key));
  });

  constructor() {
    this.api.listExperiences().subscribe({
      next: (rows) => this.taken.set(rows.map((row) => row.slug)),
      error: () => this.error.set(this.i18n.t('experience.wizard.slug.lookup_error')),
    });
    this.loadBindings();
    this.loadSystems();
  }

  canNext(): boolean {
    return this.name().trim().length > 0;
  }

  canAdvance(): boolean {
    return this.canNext() && (this.step() !== 2 || this.selectedContractsReady());
  }

  canFinish(): boolean {
    return this.langs().length > 0 && this.hasAudienceChoice() && this.selectedContractsReady();
  }

  selectedContractsReady(): boolean {
    const contractsReady = this.selectedBindings().every((row) => {
      const entry = this.entriesOf(row.system_id).find((item) => item.ingress_id === row.ingress_id);
      return this.entryState(row.system_id) === 'ready'
        && this.versions()[row.system_id] === row.published_flow_version_id
        && !!entry
        && formSchemaSupported(entry.input_schema ?? { type: 'object', properties: {} });
    });
    if (!contractsReady || !isDataLedPattern(this.selectedPattern())) return contractsReady;
    const source = this.selectedBindings()[0];
    return !!source && templateOutputCompatible(
      this.selectedPattern(),
      this.outputSchemas()[source.system_id],
    );
  }

  contractErrorText(): string {
    const source = this.selectedBindings()[0];
    if (isDataLedPattern(this.selectedPattern()) && !source) {
      return this.i18n.t('experience.wizard.bind.data_source_required');
    }
    const unsupported = this.selectedBindings().some((row) => {
      const entry = this.entriesOf(row.system_id).find((item) => item.ingress_id === row.ingress_id);
      return !!entry && !formSchemaSupported(entry.input_schema ?? { type: 'object', properties: {} });
    });
    if (unsupported) return this.i18n.t('experience.wizard.bind.contract_unsupported');
    if (
      isDataLedPattern(this.selectedPattern())
      && source
      && this.entryState(source.system_id) === 'ready'
      && this.versions()[source.system_id] === source.published_flow_version_id
      && !templateOutputCompatible(this.selectedPattern(), this.outputSchemas()[source.system_id])
    ) {
      return this.i18n.t(
        this.selectedPattern() === 'approval'
          ? 'experience.wizard.bind.output_approval_required'
          : 'experience.wizard.bind.output_collection_required',
      );
    }
    return this.i18n.t('experience.wizard.bind.contracts_pending');
  }

  hasAudienceChoice(): boolean {
    return this.wholeWorkspace() || this.audience().length > 0 || this.groups().length > 0;
  }

  stepTitle(): string {
    return `${this.i18n.t('experience.wizard.title')} · ${this.i18n.t(this.stepLabels[this.step() - 1]!)}`;
  }

  stepAnnouncement(): string {
    const position = this.i18n.t('experience.wizard.step.of', { current: this.step(), total: 3 });
    return this.busy()
      ? `${position} · ${this.i18n.t(this.experienceId() ? 'experience.wizard.saving' : 'experience.wizard.creating')}`
      : `${position} · ${this.i18n.t(this.stepLabels[this.step() - 1]!)}`;
  }

  loadBindings(): void {
    this.bindingsState.set('loading');
    this.bindings.set([]);
    this.api.listBindings().subscribe({
      next: (rows) => {
        this.bindings.set(rows);
        this.bindingsState.set('ready');
        if (this.fromHome()) this.selectHomeSource();
      },
      error: () => this.bindingsState.set('error'),
    });
  }

  loadSystems(): void {
    this.systemsState.set('loading');
    this.systems.set([]);
    this.api.publishedSystems().subscribe({
      next: (rows) => {
        this.systems.set(rows);
        const seeded: Record<string, string> = {};
        for (const row of rows) {
          const version = row.published_flow_version_id;
          if (typeof version === 'string' && version) seeded[row.id] = version;
        }
        this.versions.set(seeded);
        this.systemsState.set('ready');
        if (this.step() === 2) this.loadEntries();
      },
      error: () => this.systemsState.set('error'),
    });
  }

  entriesOf(systemId: string): StudioIngress[] {
    return this.entries()[systemId] ?? [];
  }

  entryState(systemId: string): 'loading' | 'ready' | 'error' {
    return this.entryStates()[systemId] ?? 'loading';
  }

  entryLabel(entry: StudioIngress): string {
    return entry.kind ? `${entry.ingress_id} · ${entry.kind}` : entry.ingress_id;
  }

  /** The binding this app already uses for that System entry point, if any. */
  linkedKey(systemId: string, ingressId: string): string | null {
    const picked = new Set(this.selectedKeys());
    const row = this.allBindings().find(
      (item) => picked.has(item.binding_key) && item.system_id === systemId && item.ingress_id === ingressId,
    );
    return row?.binding_key ?? null;
  }

  /**
   * Reuse an existing binding immediately, but stage a new one until the
   * author validates the final step. This keeps abandoned wizards from
   * leaving workspace-level bindings behind.
   */
  link(systemId: string, ingressId: string): void {
    if (this.bindingsState() !== 'ready') return;
    const version = this.versions()[systemId];
    if (!version) {
      this.error.set(this.i18n.t('experience.wizard.bind.no_version'));
      return;
    }
    const existing = this.bindings().find(
      (row) =>
        row.system_id === systemId
        && row.ingress_id === ingressId
        && row.published_flow_version_id === version,
    );
    if (existing) {
      this.selectedKeys.update((keys) =>
        keys.includes(existing.binding_key) ? keys : [...keys, existing.binding_key],
      );
      return;
    }
    const row: StudioBinding = {
      binding_key: uniqueBindingKey(
        this.name() || this.slug(),
        systemId,
        ingressId,
        this.allBindings().map((item) => item.binding_key),
      ),
      system_id: systemId,
      published_flow_version_id: version,
      ingress_id: ingressId,
      confirmation_policy: 'confirm',
      on_unavailable: 'unavailable',
    };
    this.stagedBindings.update((list) => [...list, row]);
    this.selectedKeys.update((keys) => [...keys, row.binding_key]);
  }

  onName(event: Event): void {
    const value = this.inputValue(event);
    this.name.set(value);
    if (!this.slugDirty()) {
      this.slug.set(uniqueExperienceSlug(value, this.taken()));
    }
  }

  pickPattern(pattern: ExperiencePattern): void {
    const homeKey = this.homePreview()?.binding?.binding_key;
    if (homeKey) {
      this.selectedKeys.update((keys) => keys.filter((key) => key !== homeKey));
      this.stagedBindings.update((rows) => rows.filter((row) => row.binding_key !== homeKey));
    }
    this.fromHome.set(false);
    this.selectedPattern.set(pattern);
  }

  /** Sketches the shape of the template: a dense block, a queue, a single input. */
  thumbLead(pattern: ExperiencePattern): string {
    if (pattern === 'dashboard' || pattern === 'mission_cockpit') return 'is-wide is-tall';
    if (pattern === 'queue' || pattern === 'approval') return 'is-half is-tall';
    return 'is-wide is-accent';
  }

  pickHome(): void {
    this.fromHome.set(true);
    this.selectedPattern.set('form_result');
    this.selectHomeSource();
  }

  isHomeSource(key: string): boolean {
    return this.fromHome() && this.homePreview()?.binding?.binding_key === key;
  }

  onPatternKey(event: KeyboardEvent, index: number): void {
    const count = this.patterns.length + (this.homeDoc() ? 1 : 0);
    let next = index;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (index + 1) % count;
    else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (index - 1 + count) % count;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = count - 1;
    else return;
    event.preventDefault();
    if (next < this.patterns.length) this.pickPattern(this.patterns[next]!);
    else this.pickHome();
    const radios = (event.currentTarget as HTMLElement).parentElement?.querySelectorAll<HTMLElement>('[role="radio"]');
    queueMicrotask(() => radios?.[next]?.focus());
  }

  next(): void {
    if (this.step() === 1) {
      this.persistStep1(() => {
        this.goToStep(2);
        this.loadEntries();
      });
      return;
    }
    if (this.step() === 2) {
      if (!this.selectedContractsReady()) {
        this.error.set(this.contractErrorText());
        return;
      }
      this.goToStep(3);
    }
  }

  /** Entry points are only needed once the author reaches the linking step. */
  private loadEntries(): void {
    const pending = this.systems().filter((row) => !(row.id in this.entryStates()));
    for (const row of pending) {
      this.loadEntriesFor(row.id);
    }
  }

  loadEntriesFor(systemId: string): void {
    this.entryStates.update((states) => ({ ...states, [systemId]: 'loading' }));
    this.api.listIngresses(systemId).subscribe({
      next: (body) => {
        this.entries.update((map) => ({ ...map, [systemId]: body.ingresses ?? [] }));
        this.outputSchemas.update((map) => ({ ...map, [systemId]: body.output_schema ?? null }));
        if (body.published_flow_version_id) {
          this.versions.update((map) => ({ ...map, [systemId]: body.published_flow_version_id }));
          if (this.reconcileSelectedBindings(
            systemId,
            body.published_flow_version_id,
            body.ingresses ?? [],
          )) {
            this.notice.set(this.i18n.t('experience.wizard.bind.publish_refreshed'));
          }
        }
        this.entryStates.update((states) => ({ ...states, [systemId]: 'ready' }));
      },
      error: () => {
        this.entryStates.update((states) => ({ ...states, [systemId]: 'error' }));
      },
    });
  }

  back(): void {
    this.goToStep(Math.max(1, this.step() - 1));
  }

  closeWizard(): void {
    const hasLocalChoices = !!this.experienceId() && (this.step() > 1 || this.stagedBindings().length > 0);
    if (hasLocalChoices && !globalThis.confirm(this.i18n.t('experience.wizard.discard_confirm'))) return;
    void this.router.navigateByUrl(this.navigation.surfaceUrl('create-apps'));
  }

  private goToStep(step: number): void {
    this.step.set(step);
    queueMicrotask(() => this.wizardHeading()?.nativeElement.focus());
  }

  saveAndClose(): void {
    if (this.stagedBindings().length > 0) {
      this.error.set(this.i18n.t('experience.wizard.bind.finish_to_save'));
      return;
    }
    if (!this.experienceId()) {
      void this.router.navigateByUrl(this.navigation.surfaceUrl('create-apps'));
      return;
    }
    const close = () => void this.router.navigateByUrl(this.navigation.surfaceUrl('create-apps'));
    if (this.step() === 1) {
      this.persistStep1(close);
      return;
    }
    if (this.step() === 3) {
      this.finalizeDraft(false);
      return;
    }
    this.busy.set(true);
    this.persistDraft(close);
  }

  finish(): void {
    this.finalizeDraft(true);
  }

  private finalizeDraft(openEditor: boolean): void {
    if (!this.canFinish()) return;
    const id = this.experienceId();
    const expectedExperienceUpdatedAt = this.experienceUpdatedAt();
    if (!id || !expectedExperienceUpdatedAt) {
      this.error.set(this.i18n.t('experience.wizard.error_after_create'));
      return;
    }
    this.busy.set(true);
    this.error.set(null);
    this.api.finalizeDraft(id, {
      pages: pagesPayload(this.document()),
      bindingKeys: this.selectedKeys(),
      expectedRevision: this.draftRevision(),
      bindings: this.stagedBindings(),
      languages: this.langs(),
      theme: { mode: this.themeMode() },
      accessPolicy: {
        roles: this.wholeWorkspace() ? [] : this.audience(),
        groups: this.wholeWorkspace() ? [] : this.groups(),
      },
      description: this.description().trim() || null,
      emblem: this.emblem().trim() || null,
      expectedExperienceUpdatedAt,
    }).subscribe({
      next: (draft) => {
        this.draftRevision.set(draft.revision);
        this.stagedBindings.set([]);
        this.busy.set(false);
        void this.router.navigateByUrl(
          openEditor
            ? this.navigation.leafUrl('create-app-edit', { ref: id })
            : this.navigation.surfaceUrl('create-apps'),
        );
      },
      error: (err) => {
        if (apiCode(err) === 'BINDING_NOT_CURRENT_PUBLISH') {
          this.error.set(this.i18n.t('experience.wizard.bind.publish_changed'));
          for (const systemId of new Set(this.selectedBindings().map((row) => row.system_id))) {
            this.loadEntriesFor(systemId);
          }
        } else {
          this.error.set(this.draftError(err));
        }
        this.busy.set(false);
      },
    });
  }

  /**
   * A republished System never retargets a shared workspace binding silently.
   * Staged bindings can move to the new immutable version; persisted stale
   * bindings are replaced by a fresh staged key for this application only.
   */
  private reconcileSelectedBindings(
    systemId: string,
    publishedVersionId: string,
    ingresses: readonly StudioIngress[],
  ): boolean {
    const ingressIds = new Set(ingresses.map((entry) => entry.ingress_id));
    const allRows = this.allBindings();
    const stagedKeys = new Set(this.stagedBindings().map((row) => row.binding_key));
    const taken = allRows.map((row) => row.binding_key);
    const replacements: StudioBinding[] = [];
    let refreshed = false;
    const staged = this.stagedBindings().map((row) => {
      if (
        row.system_id !== systemId
        || row.published_flow_version_id === publishedVersionId
        || !ingressIds.has(row.ingress_id)
      ) return row;
      refreshed = true;
      const updated = { ...row, published_flow_version_id: publishedVersionId };
      if (this.isHomeSource(row.binding_key)) this.home.refreshBinding(updated);
      return updated;
    });
    const keys = this.selectedKeys().map((key) => {
      const row = allRows.find((item) => item.binding_key === key);
      if (
        !row
        || row.system_id !== systemId
        || row.published_flow_version_id === publishedVersionId
        || !ingressIds.has(row.ingress_id)
      ) return key;
      refreshed = true;
      if (stagedKeys.has(key)) return key;
      const replacement: StudioBinding = {
        binding_key: uniqueBindingKey(
          this.name() || this.slug(),
          row.system_id,
          row.ingress_id,
          taken,
        ),
        system_id: row.system_id,
        published_flow_version_id: publishedVersionId,
        ingress_id: row.ingress_id,
        confirmation_policy: row.confirmation_policy,
        on_unavailable: row.on_unavailable,
      };
      taken.push(replacement.binding_key);
      replacements.push(replacement);
      if (this.isHomeSource(key)) this.home.refreshBinding(replacement);
      return replacement.binding_key;
    });
    if (refreshed) {
      this.stagedBindings.set([...staged, ...replacements]);
      this.selectedKeys.set([...new Set(keys)]);
    }
    return refreshed;
  }

  toggleKey(key: string): void {
    if (this.isHomeSource(key)) return;
    const current = this.selectedKeys();
    if (current.includes(key)) {
      this.selectedKeys.set(current.filter((item) => item !== key));
      this.stagedBindings.update((rows) => rows.filter((row) => row.binding_key !== key));
      return;
    }
    this.selectedKeys.set([...current, key]);
  }

  toggleLang(code: string): void {
    const current = this.langs();
    this.langs.set(current.includes(code) ? current.filter((item) => item !== code) : [...current, code]);
  }

  toggleRole(role: string): void {
    this.wholeWorkspace.set(false);
    const current = this.audience();
    this.audience.set(current.includes(role) ? current.filter((item) => item !== role) : [...current, role]);
  }

  onGroups(event: Event): void {
    const groups = this.inputValue(event)
      .split(',')
      .map((item) => item.trim())
      .filter((item, index, all) => !!item && all.indexOf(item) === index);
    this.groups.set(groups);
    if (groups.length > 0) this.wholeWorkspace.set(false);
  }

  toggleWholeWorkspace(): void {
    const next = !this.wholeWorkspace();
    this.wholeWorkspace.set(next);
    if (next) {
      this.audience.set([]);
      this.groups.set([]);
    }
  }

  systemName(id: string): string {
    return this.systems().find((item) => item.id === id)?.name || id;
  }

  confirmLabel(policy: string): string {
    const key = `experience.editor.confirm.${policy}`;
    const label = this.i18n.t(key);
    return label === key ? policy : label;
  }

  inputValue(event: Event): string {
    return (event.target as HTMLInputElement).value;
  }

  selectValue(event: Event): string {
    return (event.target as HTMLSelectElement).value;
  }

  private document(): ExperienceDocument {
    const seeded = this.fromHome() && this.homeDoc()
      ? this.homeDoc()!
      : seedDocument(this.selectedPattern(), this.name(), {
          subtitle: this.i18n.t('experience.home.subtitle'),
          empty: this.i18n.t('state.empty.description'),
          approvalBody: this.i18n.t('experience.home.approval.body'),
        });
    return bindSeedDocument(
      seeded,
      this.selectedBindings().map((row) => ({
        bindingKey: row.binding_key,
        ingressId: row.ingress_id,
        inputSchema: this.entriesOf(row.system_id).find((entry) => entry.ingress_id === row.ingress_id)?.input_schema,
      })),
    );
  }

  private selectHomeSource(): void {
    const source = this.homePreview()?.binding;
    if (!source) return;
    const persisted = this.bindings().find((row) => row.binding_key === source.binding_key);
    if (!persisted && !this.stagedBindings().some((row) => row.binding_key === source.binding_key)) {
      this.stagedBindings.update((rows) => [...rows, source]);
    }
    this.selectedKeys.update((keys) =>
      keys.includes(source.binding_key) ? keys : [source.binding_key, ...keys],
    );
  }

  private persistStep1(done: () => void): void {
    this.busy.set(true);
    this.error.set(null);
    const body = {
      name: this.name().trim(),
      description: this.description().trim() || null,
      emblem: this.emblem().trim() || null,
      slug: this.slug()
        ? experienceSlug(this.slug())
        : uniqueExperienceSlug(this.name(), this.taken()),
      pattern: this.selectedPattern(),
      languages: this.langs(),
      theme: { mode: this.themeMode() },
    };
    const existing = this.experienceId();
    const expectedUpdatedAt = this.experienceUpdatedAt();
    if (existing && !expectedUpdatedAt) {
      this.error.set(this.i18n.t('experience.wizard.error_after_create'));
      this.busy.set(false);
      return;
    }
    const req = existing
      ? this.api.patchExperience(existing, { ...body, expected_updated_at: expectedUpdatedAt! })
      : this.api.createExperience({ ...body, access_policy: { roles: ['workspace_admin'] } });
    req.subscribe({
      next: (row) => {
        this.experienceId.set(row.id);
        this.slug.set(row.slug);
        this.draftRevision.set(row.draft?.revision ?? this.draftRevision());
        this.experienceUpdatedAt.set(row.updated_at ?? null);
        if (this.stagedBindings().length > 0) {
          this.busy.set(false);
          done();
        } else {
          this.persistDraft(done);
        }
      },
      error: (err) => {
        this.error.set(studioError(this.i18n, err, 'experience.wizard.error'));
        this.busy.set(false);
      },
    });
  }

  private persistDraft(done: () => void): void {
    const id = this.experienceId();
    if (!id) {
      this.busy.set(false);
      done();
      return;
    }
    this.api
      .saveDraft(id, pagesPayload(this.document()), this.selectedKeys(), this.draftRevision())
      .subscribe({
      next: (draft) => {
        this.draftRevision.set(draft.revision);
        this.busy.set(false);
        done();
      },
      error: (err) => {
        this.error.set(this.draftError(err));
        this.busy.set(false);
      },
    });
  }

  /**
   * The application row already exists once a draft is saved, so a failure here
   * never means the creation failed — only that the layout did not land. Saying
   * otherwise sends the author back to create a duplicate.
   */
  private draftError(err: unknown): string {
    return apiCode(err) === 'EXPERIENCE_DRAFT_REVISION_CONFLICT'
      ? this.i18n.t('experience.editor.conflict')
      : studioError(this.i18n, err, 'experience.wizard.error_after_create');
  }

}
