import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { HelpTooltipComponent } from '@app/shared/cockpit';
import { I18nService } from '@app/core/i18n.service';
import { ExperienceRuntimeHostComponent } from '../runtime/runtime-host.component';
import { SystemHomeService } from '../system-home.service';
import {
  apiCode,
  apiMessage,
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
  seedDocument,
  uniqueBindingKey,
  uniqueExperienceSlug,
  type ExperiencePattern,
} from './studio-model';
import type { System } from '@app/core/canonical-api.service';
import type { ExperienceDocument } from '../runtime/model';

@Component({
  selector: 'app-experience-wizard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, HelpTooltipComponent, ExperienceRuntimeHostComponent],
  styleUrl: './studio.scss',
  template: `
    <section class="xp-wizard" [attr.aria-label]="i18n.t('experience.wizard.title')">
      <header class="xp-wizard-topbar">
        <a routerLink="/create/apps" class="xp-wizard-close">× {{ i18n.t('experience.wizard.close') }}</a>
        <div class="xp-wizard-title">
          <strong>{{ i18n.t('experience.wizard.title') }}</strong>
          <span>{{ i18n.t('experience.wizard.autosave') }}</span>
        </div>
        <button type="button" class="xp-btn" [disabled]="busy()" (click)="saveAndClose()">
          {{ i18n.t('experience.wizard.save_close') }}
        </button>
      </header>

      <ol class="xp-steps" [attr.aria-label]="i18n.t('experience.wizard.step.of', { current: step(), total: 3 })">
        @for (label of stepLabels; track label; let i = $index) {
          <li [class.is-on]="step() === i + 1" [class.is-done]="step() > i + 1">
            <span class="xp-step-n">{{ i + 1 }}</span>
            {{ i18n.t(label) }}
          </li>
        }
      </ol>

      <div class="xp-wizard-body">
        @if (error(); as err) {
          <p class="xp-error" role="alert">{{ err }}</p>
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
              @if (systems().length === 0) {
                <p class="xp-hint">{{ i18n.t('experience.wizard.bind.none_published') }}</p>
              }
              @for (sys of visibleSystems(); track sys.id) {
                <article class="xp-sys">
                  <div class="xp-sys-head">
                    <strong>{{ sys.name }}</strong>
                    <span class="xp-bind-count">{{ entriesOf(sys.id).length }}</span>
                  </div>
                  @for (entry of entriesOf(sys.id); track entry.ingress_id) {
                    <div class="xp-entry">
                      <span>{{ entryLabel(entry) }}</span>
                      @if (linkedKey(sys.id, entry.ingress_id)) {
                        <span class="xp-entry-on">{{ i18n.t('experience.wizard.bind.linked') }}</span>
                      } @else {
                        <button
                          type="button"
                          class="xp-btn"
                          [disabled]="busy()"
                          (click)="link(sys.id, entry.ingress_id)"
                        >
                          {{ i18n.t('experience.wizard.bind.link') }}
                        </button>
                      }
                    </div>
                  } @empty {
                    <p class="xp-hint">{{ i18n.t('experience.wizard.bind.no_entry') }}</p>
                  }
                </article>
              }
            </section>

            <section class="xp-bind" [attr.aria-label]="i18n.t('experience.wizard.bind.selected')">
              <div class="xp-bind-head">
                <h3>{{ i18n.t('experience.wizard.bind.selected') }}</h3>
                <span class="xp-bind-count">{{ selectedKeys().length }}</span>
              </div>
              @for (row of selectedBindings(); track row.binding_key) {
                <article class="xp-bcard">
                  <div class="xp-bcard-head">
                    <strong>{{ systemName(row.system_id) }}</strong>
                    <button type="button" class="xp-btn" (click)="toggleKey(row.binding_key)">
                      {{ i18n.t('experience.wizard.bind.unlink') }}
                    </button>
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
            </section>
          </div>
        }
        @default {
          <div class="xp-row">
            <span>{{ i18n.t('experience.wizard.access.languages') }}</span>
            <label class="xp-check">
              <input type="checkbox" [checked]="langs().includes('fr')" (change)="toggleLang('fr')" />
              {{ i18n.t('experience.work.lang.fr') }}
            </label>
            <label class="xp-check">
              <input type="checkbox" [checked]="langs().includes('en')" (change)="toggleLang('en')" />
              {{ i18n.t('experience.work.lang.en') }}
            </label>
          </div>
          <label class="xp-field">
            <span>{{ i18n.t('experience.wizard.access.theme') }}</span>
            <select [value]="themeMode()" (change)="themeMode.set(selectValue($event))">
              <option value="default">{{ i18n.t('experience.wizard.access.theme.default') }}</option>
              <option value="dark">{{ i18n.t('experience.wizard.access.theme.dark') }}</option>
              <option value="light">{{ i18n.t('experience.wizard.access.theme.light') }}</option>
            </select>
          </label>
          <div>
            <p class="xp-hint">{{ i18n.t('experience.wizard.access.who') }} — {{ i18n.t('experience.wizard.access.who.hint') }}</p>
            @for (role of roles; track role) {
              <label class="xp-check">
                <input type="checkbox" [checked]="audience().includes(role)" (change)="toggleRole(role)" />
                {{ i18n.t('governance.access.role.' + role) }}
              </label>
            }
          </div>
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
          <a routerLink="/create/apps" class="xp-btn">{{ i18n.t('common.cancel') }}</a>
        }
        <div class="xp-foot-end">
          @if (step() === 1 && !canNext()) {
            <span class="xp-hint">{{ i18n.t('experience.wizard.name.required') }}</span>
          }
          @if (step() < 3) {
            <button type="button" class="xp-btn xp-btn-primary" [disabled]="busy() || !canNext()" (click)="next()">
              {{ busy() ? i18n.t('experience.wizard.saving') : i18n.t('experience.wizard.next') }}
            </button>
          } @else {
            <button type="button" class="xp-btn xp-btn-primary" [disabled]="busy()" (click)="finish()">
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

  readonly patterns = EXPERIENCE_PATTERNS;
  readonly confirms = CONFIRMATION_POLICIES;
  readonly roles = ACCESS_ROLES;
  readonly stepLabels = [
    'experience.wizard.step.model',
    'experience.wizard.step.bind',
    'experience.wizard.step.access',
  ] as const;

  readonly step = signal(1);
  readonly name = signal('');
  readonly slug = signal('');
  readonly slugDirty = signal(false);
  readonly selectedPattern = signal<ExperiencePattern>('form_result');
  readonly fromHome = signal(false);
  readonly experienceId = signal<string | null>(null);
  readonly draftRevision = signal(1);
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly taken = signal<string[]>([]);
  readonly bindings = signal<StudioBinding[]>([]);
  readonly selectedKeys = signal<string[]>([]);
  readonly systems = signal<Array<System & { published_flow_version_id?: string | null }>>([]);
  readonly entries = signal<Record<string, StudioIngress[]>>({});
  readonly versions = signal<Record<string, string>>({});
  readonly systemQuery = signal('');
  readonly langs = signal<string[]>(['fr']);
  readonly themeMode = signal('default');
  readonly audience = signal<string[]>([]);
  readonly homeDoc = computed(() => this.home.document());
  readonly visibleSystems = computed(() => {
    const query = this.systemQuery().trim().toLocaleLowerCase();
    return query
      ? this.systems().filter((row) => row.name.toLocaleLowerCase().includes(query))
      : this.systems();
  });

  readonly previewDoc = computed(() => this.document());

  /** Bindings attached to this app, in the order the author picked them. */
  readonly selectedBindings = computed(() => {
    const rows = this.bindings();
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
    this.api.listExperiences().subscribe((rows) => this.taken.set(rows.map((row) => row.slug)));
    this.api.listBindings().subscribe((rows) => this.bindings.set(rows));
    this.api.publishedSystems().subscribe((rows) => {
      this.systems.set(rows);
      const seeded: Record<string, string> = {};
      for (const row of rows) {
        const version = row.published_flow_version_id;
        if (typeof version === 'string' && version) seeded[row.id] = version;
      }
      this.versions.set(seeded);
    });
  }

  canNext(): boolean {
    return this.name().trim().length > 0;
  }

  entriesOf(systemId: string): StudioIngress[] {
    return this.entries()[systemId] ?? [];
  }

  entryLabel(entry: StudioIngress): string {
    return entry.kind ? `${entry.ingress_id} · ${entry.kind}` : entry.ingress_id;
  }

  /** The binding this app already uses for that System entry point, if any. */
  linkedKey(systemId: string, ingressId: string): string | null {
    const picked = new Set(this.selectedKeys());
    const row = this.bindings().find(
      (item) => picked.has(item.binding_key) && item.system_id === systemId && item.ingress_id === ingressId,
    );
    return row?.binding_key ?? null;
  }

  /**
   * One click from an entry point to a usable action: reuse the workspace
   * binding when one already points there, create it otherwise. Confirmation
   * defaults to asking the user; the editor's Action tab can relax it.
   */
  link(systemId: string, ingressId: string): void {
    const existing = this.bindings().find(
      (row) => row.system_id === systemId && row.ingress_id === ingressId,
    );
    if (existing) {
      this.selectedKeys.update((keys) =>
        keys.includes(existing.binding_key) ? keys : [...keys, existing.binding_key],
      );
      return;
    }
    const version = this.versions()[systemId];
    if (!version) {
      this.error.set(this.i18n.t('experience.wizard.bind.no_version'));
      return;
    }
    this.busy.set(true);
    this.error.set(null);
    this.api
      .createBinding({
        binding_key: uniqueBindingKey(
          this.name() || this.slug(),
          systemId,
          ingressId,
          this.bindings().map((row) => row.binding_key),
        ),
        system_id: systemId,
        published_flow_version_id: version,
        ingress_id: ingressId,
        confirmation_policy: 'confirm',
        on_unavailable: 'unavailable',
      })
      .subscribe({
        next: (row) => {
          this.bindings.update((list) => [...list, row]);
          this.selectedKeys.update((keys) => [...keys, row.binding_key]);
          this.busy.set(false);
        },
        error: (err) => {
          this.error.set(apiMessage(err, this.i18n.t('experience.wizard.error')));
          this.busy.set(false);
        },
      });
  }

  onName(event: Event): void {
    const value = this.inputValue(event);
    this.name.set(value);
    if (!this.slugDirty()) {
      this.slug.set(uniqueExperienceSlug(value, this.taken()));
    }
  }

  pickPattern(pattern: ExperiencePattern): void {
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
        this.step.set(2);
        this.loadEntries();
      });
      return;
    }
    if (this.step() === 2) {
      this.persistDraft(() => this.step.set(3));
    }
  }

  /** Entry points are only needed once the author reaches the linking step. */
  private loadEntries(): void {
    const pending = this.systems().filter((row) => !(row.id in this.entries()));
    for (const row of pending) {
      this.api.listIngresses(row.id).subscribe((body) => {
        this.entries.update((map) => ({ ...map, [row.id]: body?.ingresses ?? [] }));
        const version = body?.published_flow_version_id;
        if (version) this.versions.update((map) => ({ ...map, [row.id]: version }));
      });
    }
  }

  back(): void {
    this.step.update((n) => Math.max(1, n - 1));
  }

  saveAndClose(): void {
    if (!this.experienceId()) {
      void this.router.navigate(['/create/apps']);
      return;
    }
    this.busy.set(true);
    this.persistDraft(() => void this.router.navigate(['/create/apps']));
  }

  finish(): void {
    this.persistAccess(() => {
      const id = this.experienceId();
      if (id) void this.router.navigate(['/create/apps', id]);
    });
  }

  toggleKey(key: string): void {
    const current = this.selectedKeys();
    this.selectedKeys.set(
      current.includes(key) ? current.filter((item) => item !== key) : [...current, key],
    );
  }

  toggleLang(code: string): void {
    const current = this.langs();
    this.langs.set(current.includes(code) ? current.filter((item) => item !== code) : [...current, code]);
  }

  toggleRole(role: string): void {
    const current = this.audience();
    this.audience.set(current.includes(role) ? current.filter((item) => item !== role) : [...current, role]);
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
    if (this.fromHome() && this.homeDoc()) return this.homeDoc()!;
    const seeded = seedDocument(this.selectedPattern(), this.name(), {
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

  private persistStep1(done: () => void): void {
    this.busy.set(true);
    this.error.set(null);
    const body = {
      name: this.name().trim(),
      slug: this.slug()
        ? experienceSlug(this.slug())
        : uniqueExperienceSlug(this.name(), this.taken()),
      pattern: this.selectedPattern(),
      languages: this.langs(),
      theme: { mode: this.themeMode() },
      access_policy: { roles: this.audience() },
    };
    const existing = this.experienceId();
    const req = existing
      ? this.api.patchExperience(existing, body)
      : this.api.createExperience(body);
    req.subscribe({
      next: (row) => {
        this.experienceId.set(row.id);
        this.slug.set(row.slug);
        this.draftRevision.set(row.draft?.revision ?? this.draftRevision());
        this.persistDraft(done);
      },
      error: (err) => {
        this.error.set(apiMessage(err, this.i18n.t('experience.wizard.error')));
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
        this.error.set(
          apiCode(err) === 'EXPERIENCE_DRAFT_REVISION_CONFLICT'
            ? this.i18n.t('experience.editor.conflict')
            : apiMessage(err, this.i18n.t('experience.wizard.error')),
        );
        this.busy.set(false);
      },
    });
  }

  private persistAccess(done: () => void): void {
    const id = this.experienceId();
    if (!id) return;
    this.busy.set(true);
    this.api
      .patchExperience(id, {
        languages: this.langs(),
        theme: { mode: this.themeMode() },
        access_policy: { roles: this.audience() },
      })
      .subscribe({
        next: () => this.persistDraft(done),
        error: (err) => {
          this.error.set(apiMessage(err, this.i18n.t('experience.wizard.error')));
          this.busy.set(false);
        },
      });
  }
}
