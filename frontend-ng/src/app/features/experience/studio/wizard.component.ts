import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { HelpTooltipComponent, PageFrameComponent } from '@app/shared/cockpit';
import { I18nService } from '@app/core/i18n.service';
import { ExperienceRuntimeHostComponent } from '../runtime/runtime-host.component';
import { SystemHomeService } from '../system-home.service';
import { apiMessage, StudioApiService, type StudioBinding, type StudioIngress } from './studio-api.service';
import { pagesPayload } from './studio-document';
import {
  ACCESS_ROLES,
  bindingKeyFrom,
  CONFIRMATION_POLICIES,
  EXPERIENCE_PATTERNS,
  experienceSlug,
  seedDocument,
  uniqueExperienceSlug,
  withAudience,
  type ExperiencePattern,
} from './studio-model';
import type { System } from '@app/core/canonical-api.service';
import type { ExperienceDocument } from '../runtime/model';

@Component({
  selector: 'app-experience-wizard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, HelpTooltipComponent, PageFrameComponent, ExperienceRuntimeHostComponent],
  styleUrl: './studio.scss',
  template: `
    <ck-page-frame
      [eyebrow]="i18n.t('experience.wizard.eyebrow')"
      [title]="i18n.t('experience.wizard.title')"
      [description]="i18n.t('experience.wizard.step.of', { current: step(), total: 3 })"
    >
      <ck-help titleHelp id="concept.business-application" />
      <a actions routerLink="/create/apps" class="xp-btn">{{ i18n.t('common.back') }}</a>

      <nav class="xp-steps" [attr.aria-label]="i18n.t('experience.wizard.step.of', { current: step(), total: 3 })">
        <span [class.is-on]="step() === 1">1. {{ i18n.t('experience.wizard.step.model') }}</span>
        <span [class.is-on]="step() === 2">2. {{ i18n.t('experience.wizard.step.bind') }}</span>
        <span [class.is-on]="step() === 3">3. {{ i18n.t('experience.wizard.step.access') }}</span>
      </nav>

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
          <p class="xp-hint">{{ i18n.t('experience.wizard.slug') }} · /work/{{ slug() }}</p>

          <div class="xp-cards" role="radiogroup" [attr.aria-label]="i18n.t('experience.wizard.pattern.aria')">
            @for (pattern of patterns; track pattern) {
              <button
                type="button"
                class="xp-choice"
                role="radio"
                [attr.aria-checked]="!fromHome() && selectedPattern() === pattern"
                (click)="pickPattern(pattern)"
              >
                <strong>{{ i18n.t('experience.work.pattern.' + pattern) }}</strong>
                <p>{{ i18n.t('experience.wizard.pattern.' + pattern + '.body') }}</p>
              </button>
            }
            @if (homeDoc()) {
              <button
                type="button"
                class="xp-choice"
                role="radio"
                [attr.aria-checked]="fromHome()"
                (click)="pickHome()"
              >
                <strong>{{ i18n.t('experience.wizard.home.option') }}</strong>
                <p>{{ i18n.t('experience.wizard.home.body') }}</p>
              </button>
            }
          </div>
        }
        @case (2) {
          <section class="xp-bind" [attr.aria-label]="i18n.t('experience.wizard.bind.existing')">
            <h3>{{ i18n.t('experience.wizard.bind.existing') }}</h3>
            @if (bindings().length === 0) {
              <p class="xp-hint">{{ i18n.t('experience.wizard.bind.empty') }}</p>
            }
            @for (row of bindings(); track row.binding_key) {
              <label class="xp-check">
                <input
                  type="checkbox"
                  [checked]="selectedKeys().includes(row.binding_key)"
                  (change)="toggleKey(row.binding_key)"
                />
                <span>
                  <strong>{{ i18n.t('experience.wizard.bind.calls') }}</strong>
                  {{ systemName(row.system_id) }}
                  · <strong>{{ i18n.t('experience.wizard.bind.inputs') }}</strong>
                  {{ row.ingress_id }}
                  · <strong>{{ i18n.t('experience.wizard.bind.confirmation') }}</strong>
                  {{ confirmLabel(row.confirmation_policy) }}
                </span>
              </label>
            }
          </section>
          <section class="xp-bind">
            <h3>{{ i18n.t('experience.wizard.bind.create') }}</h3>
            @if (systems().length === 0) {
              <p class="xp-hint">{{ i18n.t('experience.wizard.bind.none_published') }}</p>
            } @else {
              <label class="xp-field">
                <span>{{ i18n.t('experience.wizard.bind.system') }}</span>
                <select [value]="newSystemId()" (change)="onSystem($event)">
                  <option value="">—</option>
                  @for (sys of systems(); track sys.id) {
                    <option [value]="sys.id">{{ sys.name }}</option>
                  }
                </select>
              </label>
              <label class="xp-field">
                <span>{{ i18n.t('experience.wizard.bind.entry') }}</span>
                <select [value]="newIngressId()" (change)="newIngressId.set(selectValue($event))">
                  @for (entry of ingresses(); track entry.ingress_id) {
                    <option [value]="entry.ingress_id">{{ entry.ingress_id }}</option>
                  }
                </select>
              </label>
              <label class="xp-field">
                <span>{{ i18n.t('experience.wizard.bind.key') }}</span>
                <input [value]="newKey()" (input)="newKey.set(inputValue($event))" />
              </label>
              <label class="xp-field">
                <span>{{ i18n.t('experience.wizard.bind.confirm') }}</span>
                <select [value]="newConfirm()" (change)="newConfirm.set(selectValue($event))">
                  @for (policy of confirms; track policy) {
                    <option [value]="policy">{{ confirmLabel(policy) }}</option>
                  }
                </select>
              </label>
              <button type="button" class="xp-btn" [disabled]="!canCreateBinding()" (click)="createBinding()">
                {{ i18n.t('experience.wizard.bind.add') }}
              </button>
            }
          </section>
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
          <app-experience-runtime-host [document]="previewDoc()" />
        }
      }

      <div class="xp-row">
        @if (step() > 1) {
          <button type="button" class="xp-btn" [disabled]="busy()" (click)="back()">
            {{ i18n.t('experience.wizard.back') }}
          </button>
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
    </ck-page-frame>
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

  readonly step = signal(1);
  readonly name = signal('');
  readonly slug = signal('app');
  readonly slugDirty = signal(false);
  readonly selectedPattern = signal<ExperiencePattern>('form_result');
  readonly fromHome = signal(false);
  readonly experienceId = signal<string | null>(null);
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly taken = signal<string[]>([]);
  readonly bindings = signal<StudioBinding[]>([]);
  readonly selectedKeys = signal<string[]>([]);
  readonly systems = signal<Array<System & { published_flow_version_id?: string | null }>>([]);
  readonly ingresses = signal<StudioIngress[]>([]);
  readonly newSystemId = signal('');
  readonly newIngressId = signal('');
  readonly newKey = signal('');
  readonly newConfirm = signal<string>('confirm');
  readonly publishedVersionId = signal('');
  readonly langs = signal<string[]>(['fr']);
  readonly themeMode = signal('default');
  readonly audience = signal<string[]>([]);
  readonly homeDoc = computed(() => this.home.document());

  readonly previewDoc = computed(() => this.document());

  constructor() {
    this.api.listExperiences().subscribe((rows) => this.taken.set(rows.map((row) => row.slug)));
    this.api.listBindings().subscribe((rows) => this.bindings.set(rows));
    this.api.publishedSystems().subscribe((rows) => this.systems.set(rows));
  }

  canNext(): boolean {
    return this.name().trim().length > 0;
  }

  canCreateBinding(): boolean {
    return !!this.newSystemId() && !!this.newIngressId() && !!this.newKey() && !!this.publishedVersionId();
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

  pickHome(): void {
    this.fromHome.set(true);
    this.selectedPattern.set('form_result');
  }

  next(): void {
    if (this.step() === 1) {
      this.persistStep1(() => this.step.set(2));
      return;
    }
    if (this.step() === 2) {
      this.persistDraft(() => this.step.set(3));
    }
  }

  back(): void {
    this.step.update((n) => Math.max(1, n - 1));
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

  onSystem(event: Event): void {
    const id = this.selectValue(event);
    this.newSystemId.set(id);
    this.ingresses.set([]);
    this.newIngressId.set('');
    this.publishedVersionId.set('');
    const sys = this.systems().find((item) => item.id === id);
    const version = sys?.published_flow_version_id;
    if (typeof version === 'string') this.publishedVersionId.set(version);
    if (!id) return;
    this.api.listIngresses(id).subscribe((body) => {
      const list = body?.ingresses ?? [];
      this.ingresses.set(list);
      const first = list[0]?.ingress_id ?? '';
      this.newIngressId.set(first);
      if (body?.published_flow_version_id) this.publishedVersionId.set(body.published_flow_version_id);
      this.newKey.set(bindingKeyFrom(this.name() || this.slug(), first));
    });
  }

  createBinding(): void {
    this.busy.set(true);
    this.error.set(null);
    this.api
      .createBinding({
        binding_key: this.newKey(),
        system_id: this.newSystemId(),
        published_flow_version_id: this.publishedVersionId(),
        ingress_id: this.newIngressId(),
        confirmation_policy: this.newConfirm(),
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
    return seedDocument(this.selectedPattern(), this.name(), {
      subtitle: this.i18n.t('experience.home.subtitle'),
      submit: this.i18n.t('experience.runtime.form.submit'),
      empty: this.i18n.t('state.empty.description'),
      approvalBody: this.i18n.t('experience.home.approval.body'),
    });
  }

  private persistStep1(done: () => void): void {
    this.busy.set(true);
    this.error.set(null);
    const body = {
      name: this.name().trim(),
      slug: experienceSlug(this.slug()) || uniqueExperienceSlug(this.name(), this.taken()),
      pattern: this.selectedPattern(),
      languages: this.langs(),
      theme: { mode: this.themeMode() },
    };
    const existing = this.experienceId();
    const req = existing
      ? this.api.patchExperience(existing, body)
      : this.api.createExperience(body);
    req.subscribe({
      next: (row) => {
        this.experienceId.set(row.id);
        this.slug.set(row.slug);
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
    this.api.saveDraft(id, pagesPayload(this.document()), this.selectedKeys()).subscribe({
      next: () => {
        this.busy.set(false);
        done();
      },
      error: (err) => {
        this.error.set(apiMessage(err, this.i18n.t('experience.wizard.error')));
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
        theme: withAudience({ mode: this.themeMode() }, this.audience()),
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
