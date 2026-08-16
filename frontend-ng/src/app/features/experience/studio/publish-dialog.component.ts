import { DOCUMENT } from '@angular/common';
import { A11yModule } from '@angular/cdk/a11y';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { forkJoin } from 'rxjs';
import { HelpTooltipComponent } from '@app/shared/cockpit';
import { I18nService } from '@app/core/i18n.service';
import {
  apiCode,
  studioError,
  StudioApiService,
  type StudioDeployment,
  type StudioDetail,
  type StudioDraft,
  type StudioRelease,
} from './studio-api.service';
import {
  canCreateRelease,
  canDeploy,
  releaseSemanticDiff,
  type ReleaseDiffCategory,
  type ReleaseDiffItem,
  type ReadyBindingEvidence,
  type ReadyCheck,
  type ReadyIssue,
} from './studio-publish';

/** What the release freezes, as the author reads it before confirming. */
export interface PublishSummary {
  pages: number;
  components: number;
  bindingKeys: readonly string[];
  languages: readonly string[];
}

@Component({
  selector: 'app-experience-publish-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [A11yModule, HelpTooltipComponent],
  styleUrl: './studio.scss',
  template: `
    @if (open()) {
      <div class="xp-pub" role="presentation">
        <button
          type="button"
          class="xp-pub-back"
          [attr.aria-label]="i18n.t('experience.publish.close')"
          [disabled]="busy()"
          (click)="close()"
        ></button>
        <section
          class="xp-pub-dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="xp-pub-title"
          cdkTrapFocus
          [cdkTrapFocusAutoCapture]="true"
          (keydown.escape)="close()"
        >
          <button
            type="button"
            class="xp-pub-close"
            [attr.aria-label]="i18n.t('experience.publish.close')"
            [disabled]="busy()"
            (click)="close()"
          >✕</button>
          <p class="xp-hint">{{ i18n.t(release() ? 'experience.publish.deploy.eyebrow' : 'experience.publish.eyebrow') }}</p>
          <h2 id="xp-pub-title">{{ release()
            ? i18n.t('experience.publish.deploy.title', { n: release()!.release_number })
            : i18n.t('experience.publish.title') }}</h2>
          <p>{{ i18n.t(release() ? 'experience.publish.deploy.subtitle' : 'experience.publish.subtitle') }}</p>

          <dl class="xp-recap">
            <dt>{{ i18n.t('experience.publish.recap.pages') }}</dt>
            <dd>{{ i18n.t('experience.publish.recap.pages.n', { n: recapSummary().pages, c: recapSummary().components }) }}</dd>
            <dt>
              {{ i18n.t('experience.publish.recap.bindings') }}
              <ck-help id="concept.binding" />
            </dt>
            <dd>
              @if (recapBindings().length === 0) {
                {{ i18n.t('experience.publish.recap.none') }}
              } @else {
                <ul class="xp-issues">
                  @for (binding of recapBindings(); track binding.binding_key) {
                    <li>
                      <code>{{ binding.binding_key }}</code>
                      <small>
                        {{ i18n.t('experience.publish.recap.binding.version', {
                          version: binding.published_flow_version_id
                        }) }}
                        ·
                        {{ i18n.t('experience.publish.recap.binding.hash', {
                          hash: binding.flow_sha256 || '—'
                        }) }}
                      </small>
                    </li>
                  }
                </ul>
              }
            </dd>
            <dt>{{ i18n.t('experience.publish.recap.audience') }}</dt>
            <dd>{{ audienceText() }}</dd>
            <dt>{{ i18n.t('experience.publish.recap.languages') }}</dt>
            <dd>{{ languagesText() }}</dd>
            <dt>{{ i18n.t('experience.publish.recap.theme') }}</dt>
            <dd>{{ themeText() }}</dd>
            <dt>{{ i18n.t(release() ? 'experience.publish.recap.release' : 'experience.publish.recap.revision') }}</dt>
            <dd><code>{{ recapRevision() }}</code></dd>
            <dt>{{ i18n.t('experience.publish.recap.hash') }}</dt>
            <dd><code>{{ recapHash() }}</code></dd>
          </dl>

          @if (!release()) {
            <section class="xp-release-diff" aria-labelledby="xp-release-diff-title">
              <div class="xp-release-diff-head">
                <h3 id="xp-release-diff-title">{{ i18n.t('experience.publish.diff.title') }}</h3>
                @if (previousRelease(); as previous) {
                  <span>{{ i18n.t('experience.publish.diff.baseline', { n: previous.release_number }) }}</span>
                }
              </div>
              @if (checkState() === 'loading' || checkState() === 'idle') {
                <p class="xp-hint">{{ i18n.t('experience.publish.diff.loading') }}</p>
              } @else if (checkState() === 'error') {
                <p class="xp-error">{{ i18n.t('experience.publish.diff.error') }}</p>
              } @else if (!previousRelease()) {
                <p class="xp-hint">{{ i18n.t('experience.publish.diff.first') }}</p>
              } @else if (semanticDiff().length === 0) {
                <p class="xp-hint">{{ i18n.t('experience.publish.diff.none') }}</p>
              } @else {
                @for (category of diffCategories; track category) {
                  @if (diffItems(category); as items) {
                    @if (items.length > 0) {
                      <section class="xp-release-diff-group">
                        <h4>{{ i18n.t('experience.publish.diff.category.' + category) }}</h4>
                        <ul>
                          @for (item of items; track $index) {
                            <li [class.is-breaking]="item.breaking">
                              <span>{{ diffItemText(item) }}</span>
                              @if (item.breaking) {
                                <strong>{{ i18n.t('experience.publish.diff.breaking') }}</strong>
                              }
                            </li>
                          }
                        </ul>
                      </section>
                    }
                  }
                }
              }
            </section>

            @if (breakingItems().length > 0) {
              <label class="xp-breaking-ack" for="xp-pub-breaking-ack">
                <input
                  id="xp-pub-breaking-ack"
                  type="checkbox"
                  [checked]="breakingAcknowledged()"
                  [disabled]="busy()"
                  aria-describedby="xp-pub-breaking-hint"
                  (change)="onBreakingAcknowledgement($event)"
                />
                <span>{{ i18n.t('experience.publish.diff.ack') }}</span>
              </label>
              <p id="xp-pub-breaking-hint" class="xp-hint">
                {{ i18n.t('experience.publish.diff.ack.hint', { n: breakingItems().length }) }}
              </p>
            }
          }

          @if (checkState() === 'loading') {
            <p class="xp-hint">{{ i18n.t('experience.publish.loading') }}</p>
          } @else if (checkState() === 'error') {
            <button type="button" class="xp-btn" [disabled]="busy()" (click)="loadCheck()">
              {{ i18n.t('experience.wizard.retry') }}
            </button>
          } @else {
            @if (check()!.blockers.length > 0) {
              <p>{{ i18n.t('experience.publish.blockers') }}</p>
              <ul class="xp-issues is-block">
                @for (item of check()!.blockers; track item.code ?? item.message) {
                  <li>{{ issueText(item) }}</li>
                }
              </ul>
            } @else if (!release()) {
              <p>{{ i18n.t('experience.publish.ready') }}</p>
            }
            @if (check()!.warnings.length > 0) {
              <p>{{ i18n.t('experience.publish.warnings') }}</p>
              <ul class="xp-issues">
                @for (item of check()!.warnings; track item.code ?? item.message) {
                  <li>{{ issueText(item) }}</li>
                }
              </ul>
            }
          }

          @if (!release()) {
            <label class="xp-field" for="xp-pub-notes">
              <span>{{ i18n.t('experience.publish.notes') }}</span>
              <textarea
                id="xp-pub-notes"
                rows="3"
                cdkFocusInitial
                [value]="notes()"
                [placeholder]="i18n.t('experience.publish.notes.placeholder')"
                [disabled]="busy()"
                (input)="onNotes($event)"
              ></textarea>
            </label>
          } @else {
            <p #releasedStatus tabindex="-1">
              {{ i18n.t('experience.publish.released', { n: release()!.release_number }) }}
            </p>
            <p class="xp-hint">{{ i18n.t('experience.publish.deploy.separate') }}</p>
            <fieldset class="xp-channel-choices">
              <legend>
                {{ i18n.t('experience.publish.channel') }}
                <ck-help id="concept.pilot" />
              </legend>
              @for (choice of channels; track choice; let index = $index) {
                <label [class.is-on]="channel() === choice">
                  <input
                    type="radio"
                    name="xp-publish-channel"
                    [value]="choice"
                    [checked]="channel() === choice"
                    [disabled]="busy()"
                    [tabIndex]="channel() === choice ? 0 : -1"
                    (change)="channel.set(choice)"
                    (keydown)="onChannelKey($event, index)"
                  />
                  <span>
                    <strong>{{ i18n.t('experience.publish.channel.' + choice) }}</strong>
                    <small>{{ i18n.t('experience.publish.channel.' + choice + '.hint') }}</small>
                  </span>
                </label>
              }
            </fieldset>
            @if (channel() === 'pilot') {
              <label class="xp-field" for="xp-pub-pilot-groups">
                <span>{{ i18n.t('experience.publish.pilot.groups') }}</span>
                <input
                  id="xp-pub-pilot-groups"
                  type="text"
                  [value]="deployGroups().join(', ')"
                  [placeholder]="i18n.t('experience.publish.pilot.groups.placeholder')"
                  [disabled]="busy()"
                  (input)="onDeployGroups($event)"
                />
                <small>{{ i18n.t('experience.publish.pilot.groups.hint') }}</small>
                <small>{{ i18n.t('experience.publish.pilot.groups.boundary', { audience: audienceText() }) }}</small>
                @if (!pilotAudience()) {
                  <small class="xp-error" role="alert">{{ i18n.t('experience.publish.pilot.audience_required') }}</small>
                }
              </label>
            }
            @if (channel() === 'none') {
              <p class="xp-hint">{{ i18n.t('experience.publish.channel.none.done') }}</p>
            } @else {
              <p class="xp-hint" role="status">
                {{ i18n.t(
                  busy() ? 'experience.publish.deploy.progress' : 'experience.publish.deploy.retry_hint',
                  { channel: i18n.t('experience.publish.channel.' + channel()) }
                ) }}
              </p>
            }
          }

          @if (error(); as err) {
            <p class="xp-error" role="alert">{{ err }}</p>
          }

          <div class="xp-foot">
            <button type="button" class="xp-btn" [disabled]="busy()" (click)="close()">
              {{ i18n.t('common.cancel') }}
            </button>
            @if (!release()) {
              <button
                type="button"
                class="xp-btn xp-btn-primary"
                [disabled]="busy() || !canRelease()"
                (click)="releaseNow()"
              >
                {{ releaseActionLabel() }}
              </button>
            } @else if (channel() !== 'none') {
              <button
                #deployRetry
                type="button"
                class="xp-btn xp-btn-primary"
                [disabled]="busy() || !canDeployNow()"
                (click)="deployNow()"
              >
                {{ busy()
                  ? i18n.t('experience.publish.deploying')
                  : i18n.t(error() ? 'experience.publish.deploy.retry' : 'experience.publish.deploy') }}
              </button>
            } @else {
              <button type="button" class="xp-btn xp-btn-primary" (click)="close()">
                {{ i18n.t('experience.publish.done') }}
              </button>
            }
          </div>
        </section>
      </div>
    }
  `,
})
export class ExperiencePublishDialogComponent {
  readonly i18n = inject(I18nService);
  private readonly api = inject(StudioApiService);
  private readonly document = inject(DOCUMENT);
  readonly experienceId = input.required<string>();
  readonly draft = input.required<StudioDraft>();
  readonly experienceUpdatedAt = input.required<string>();
  readonly deployments = input<readonly StudioDeployment[]>([]);
  readonly audience = input<Record<string, unknown>>({});
  readonly summary = input<PublishSummary>({
    pages: 0,
    components: 0,
    bindingKeys: [],
    languages: [],
  });
  readonly open = input(false);
  readonly initialRelease = input<StudioRelease | null>(null);
  readonly closed = output();
  readonly released = output();
  readonly deployed = output();
  readonly refreshRequested = output();

  readonly check = signal<ReadyCheck | null>(null);
  readonly checkState = signal<'idle' | 'loading' | 'ready' | 'error'>('idle');
  readonly reviewDetail = signal<StudioDetail | null>(null);
  readonly previousRelease = signal<StudioRelease | null>(null);
  readonly breakingAcknowledged = signal(false);
  readonly notes = signal('');
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly release = signal<StudioRelease | null>(null);
  readonly channels = ['none', 'pilot', 'live'] as const;
  readonly channel = signal<(typeof this.channels)[number]>('none');
  readonly diffCategories: readonly ReleaseDiffCategory[] = ['presentation', 'behavior', 'access'];
  readonly deployGroups = signal<string[]>([]);
  readonly pilotAudience = computed<Record<string, unknown> | null>(() => {
    const selectedGroups = this.deployGroups();
    if (selectedGroups.length > 0) return { groups: selectedGroups };
    const policy = this.recapAudience();
    const roles = this.audienceValues(policy, 'roles');
    const groups = this.audienceValues(policy, 'groups');
    return roles.length > 0 || groups.length > 0 ? { roles, groups } : null;
  });
  private readonly expectedDeploymentReleaseIds = signal<Record<'pilot' | 'live', string | null>>({
    pilot: null,
    live: null,
  });
  private readonly expectedDeploymentUpdatedAts = signal<Record<'pilot' | 'live', string | null>>({
    pilot: null,
    live: null,
  });
  private readonly releasedStatus = viewChild<ElementRef<HTMLElement>>('releasedStatus');
  private readonly deployRetry = viewChild<ElementRef<HTMLButtonElement>>('deployRetry');
  private previousFocus: HTMLElement | null = null;
  private wasOpen = false;
  readonly recapBindings = computed<ReadyBindingEvidence[]>(() => {
    const release = this.release();
    return release ? release.bindings_snapshot ?? [] : this.check()?.bindings ?? [];
  });
  readonly recapSummary = computed<PublishSummary>(() => {
    const release = this.release();
    if (!release) {
      const summary = this.summary();
      return { ...summary, languages: this.reviewDetail()?.languages ?? summary.languages };
    }
    const raw = release.pages;
    const pages = raw && typeof raw === 'object' && Array.isArray((raw as Record<string, unknown>)['pages'])
      ? (raw as { pages: Array<Record<string, unknown>> }).pages
      : [];
    const bindingKeys = this.recapBindings().map((item) => item.binding_key);
    return {
      pages: pages.length,
      components: pages.reduce((total, page) => total + (Array.isArray(page['components']) ? page['components'].length : 0), 0),
      bindingKeys,
      languages: release.languages ?? [],
    };
  });
  readonly recapAudience = computed<Record<string, unknown>>(() => {
    const release = this.release();
    return release ? release.access_snapshot ?? {} : this.audience();
  });
  readonly semanticDiff = computed<ReleaseDiffItem[]>(() => {
    const detail = this.reviewDetail();
    const previous = this.previousRelease();
    const check = this.check();
    if (!detail || !previous || !check) return [];
    return releaseSemanticDiff(
      {
        pages: this.draft().pages,
        bindings: check.bindings,
        access: detail.access_policy ?? {},
        languages: detail.languages ?? [],
        theme: detail.theme ?? {},
      },
      {
        pages: previous.pages ?? { pages: [] },
        bindings: previous.bindings_snapshot ?? [],
        access: previous.access_snapshot ?? {},
        languages: previous.languages ?? [],
        theme: previous.theme ?? {},
      },
    );
  });
  readonly breakingItems = computed(() => this.semanticDiff().filter((item) => item.breaking));

  constructor() {
    effect(() => {
      if (!this.open()) {
        this.wasOpen = false;
        return;
      }
      const deployments = this.deployments();
      if (this.wasOpen) {
        this.syncDeploymentCas(deployments);
        return;
      }
      this.wasOpen = true;
      this.previousFocus = this.document.activeElement instanceof HTMLElement
        ? this.document.activeElement
        : null;
      this.syncDeploymentCas(deployments);
      this.check.set(null);
      this.checkState.set('idle');
      this.reviewDetail.set(null);
      this.previousRelease.set(null);
      this.breakingAcknowledged.set(false);
      const initialRelease = this.initialRelease();
      this.release.set(initialRelease);
      this.notes.set('');
      this.error.set(null);
      this.channel.set('none');
      this.deployGroups.set([]);
      if (initialRelease) {
        this.check.set({ ready: true, blockers: [], warnings: [], bindings_sha256: '', bindings: [] });
        this.checkState.set('ready');
      } else {
        this.loadCheck();
      }
    });
  }

  loadCheck(): void {
    this.check.set(null);
    this.checkState.set('loading');
    this.reviewDetail.set(null);
    this.previousRelease.set(null);
    this.breakingAcknowledged.set(false);
    this.error.set(null);
    forkJoin({
      check: this.api.readyCheck(this.experienceId()),
      detail: this.api.getExperience(this.experienceId()),
      releases: this.api.listReleases(this.experienceId()),
    }).subscribe({
      next: ({ check, detail, releases }) => {
        const draft = this.draft();
        if (
          detail.updated_at !== this.experienceUpdatedAt()
          || detail.draft?.revision !== draft.revision
          || detail.draft?.content_sha256 !== draft.content_sha256
        ) {
          this.checkState.set('error');
          this.error.set(this.i18n.t('experience.publish.conflict'));
          return;
        }
        this.reviewDetail.set(detail);
        this.previousRelease.set(releases[0] ?? null);
        this.check.set(check);
        this.checkState.set('ready');
      },
      error: (err) => {
        this.checkState.set('error');
        this.error.set(studioError(this.i18n, err, 'experience.publish.error'));
      },
    });
  }

  canRelease(): boolean {
    const check = this.check();
    return !!this.experienceUpdatedAt()
      && this.checkState() === 'ready'
      && !!check?.bindings_sha256
      && canCreateRelease({
        blockers: check.blockers,
        notes: this.notes(),
        breakingChanges: this.breakingItems(),
        breakingAcknowledged: this.breakingAcknowledged(),
      });
  }

  releaseActionLabel(): string {
    return this.busy()
      ? this.i18n.t('experience.publish.releasing')
      : this.i18n.t('experience.publish.release');
  }

  audienceText(): string {
    const policy = this.recapAudience();
    const raw = policy['roles'];
    const roles = Array.isArray(raw) ? raw.filter((item): item is string => typeof item === 'string') : [];
    const rawGroups = policy['groups'];
    const groups = Array.isArray(rawGroups)
      ? rawGroups.filter((item): item is string => typeof item === 'string')
      : [];
    if (roles.length === 0 && groups.length === 0) {
      return Object.keys(policy).length === 0
        ? this.i18n.t('experience.publish.recap.unset')
        : this.i18n.t('experience.publish.recap.everyone');
    }
    return [
      ...roles.map((role) => {
        const key = `governance.access.role.${role}`;
        const label = this.i18n.t(key);
        return label === key ? role : label;
      }),
      ...groups.map((group) => this.i18n.t('experience.publish.recap.group', { name: group })),
    ].join(', ');
  }

  languagesText(): string {
    const languages = this.recapSummary().languages;
    return languages.length === 0
      ? this.i18n.t('experience.publish.recap.none')
      : languages.join(', ');
  }

  themeText(): string {
    const theme = this.release()?.theme ?? this.reviewDetail()?.theme ?? {};
    const mode = typeof theme['mode'] === 'string' && theme['mode'] ? theme['mode'] : 'default';
    const key = `experience.publish.recap.theme.${mode}`;
    const translated = this.i18n.t(key);
    const label = translated === key ? mode : translated;
    const accent = typeof theme['accent'] === 'string' && theme['accent'].trim()
      ? this.i18n.t('experience.publish.recap.theme.accent', { value: theme['accent'] })
      : '';
    return accent ? `${label} · ${accent}` : label;
  }

  recapRevision(): string {
    const release = this.release();
    return release ? `R${release.release_number}` : `r${this.draft().revision}`;
  }

  recapHash(): string {
    const release = this.release();
    return release ? release.content_sha256 ?? '—' : this.draft().content_sha256;
  }

  issueText(issue: ReadyIssue): string {
    const code = issue.code?.toLowerCase();
    const key = code ? `experience.publish.issue.${code}` : '';
    const translated = key ? this.i18n.t(key) : '';
    const label = translated && translated !== key
      ? translated
      : issue.message || issue.code || this.i18n.t('experience.publish.error');
    const context = issue.component_id || issue.binding_key || issue.path;
    return context ? `${label} · ${context}` : label;
  }

  canDeployNow(): boolean {
    if (this.channel() === 'none') return false;
    if (this.channel() === 'pilot' && !this.pilotAudience()) return false;
    return canDeploy({ releaseId: this.release()?.id, channel: this.channel() });
  }

  onNotes(event: Event): void {
    this.notes.set((event.target as HTMLTextAreaElement).value);
  }

  onBreakingAcknowledgement(event: Event): void {
    this.breakingAcknowledged.set((event.target as HTMLInputElement).checked);
  }

  diffItems(category: ReleaseDiffCategory): ReleaseDiffItem[] {
    return this.semanticDiff().filter((item) => item.category === category);
  }

  diffItemText(item: ReleaseDiffItem): string {
    return this.i18n.t(`experience.publish.diff.item.${item.code}`, {
      label: item.label,
      before: this.diffValues(item, item.before),
      after: this.diffValues(item, item.after),
    });
  }

  private diffValues(item: ReleaseDiffItem, values: readonly string[] | undefined): string {
    if (!values?.length) return this.i18n.t('experience.publish.recap.none');
    if (item.valueKind === 'audience') {
      return values.map((value) => {
        if (value === 'everyone') return this.i18n.t('experience.publish.recap.everyone');
        if (value === 'unset') return this.i18n.t('experience.publish.recap.unset');
        if (value.startsWith('group:')) {
          return this.i18n.t('experience.publish.recap.group', { name: value.slice(6) });
        }
        const role = value.startsWith('role:') ? value.slice(5) : value;
        const key = `governance.access.role.${role}`;
        const translated = this.i18n.t(key);
        return translated === key ? role : translated;
      }).join(', ');
    }
    if (item.valueKind === 'binding') {
      return values.map((value) => {
        const separator = value.indexOf(':');
        const kind = separator > 0 ? value.slice(0, separator) : 'value';
        const detail = separator > 0 ? value.slice(separator + 1) : value;
        return this.i18n.t(`experience.publish.diff.value.${kind}`, { value: detail });
      }).join(' · ');
    }
    return values.join(' · ');
  }

  onDeployGroups(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    this.deployGroups.set(value.split(',').map((item) => item.trim()).filter(
      (item, index, all) => !!item && all.indexOf(item) === index,
    ));
  }

  onChannelKey(event: KeyboardEvent, index: number): void {
    let next: number | null = null;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (index + 1) % this.channels.length;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (index - 1 + this.channels.length) % this.channels.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = this.channels.length - 1;
    if (next === null) return;
    event.preventDefault();
    this.channel.set(this.channels[next]!);
    const radios = (event.currentTarget as HTMLElement).closest('fieldset')?.querySelectorAll<HTMLElement>('input[type="radio"]');
    queueMicrotask(() => radios?.[next!]?.focus());
  }

  releaseNow(): void {
    if (!this.canRelease()) return;
    this.busy.set(true);
    this.error.set(null);
    this.api.createRelease(this.experienceId(), {
      notes: this.notes().trim(),
      expectedDraftRevision: this.draft().revision,
      expectedContentSha256: this.draft().content_sha256,
      expectedExperienceUpdatedAt: this.experienceUpdatedAt(),
      expectedBindingsSha256: this.check()!.bindings_sha256,
    }).subscribe({
      next: (row) => {
        this.release.set(row);
        this.released.emit();
        this.busy.set(false);
        queueMicrotask(() => this.releasedStatus()?.nativeElement.focus());
      },
      error: (err) => {
        const code = apiCode(err);
        this.error.set(
          code === 'EXPERIENCE_DRAFT_REVISION_CONFLICT'
            || code === 'EXPERIENCE_DRAFT_CONTENT_CONFLICT'
            || code === 'EXPERIENCE_METADATA_CONFLICT'
            || code === 'EXPERIENCE_BINDINGS_CONFLICT'
            ? this.i18n.t('experience.publish.conflict')
            : studioError(this.i18n, err, 'experience.publish.error'),
        );
        this.busy.set(false);
      },
    });
  }

  deployNow(): void {
    const release = this.release();
    if (!release || !this.canDeployNow()) return;
    this.busy.set(true);
    this.error.set(null);
    this.deployRelease(release, this.channel() as 'pilot' | 'live');
  }

  private deployRelease(release: StudioRelease, channel: 'pilot' | 'live'): void {
    const pilotAudience = channel === 'pilot' ? this.pilotAudience() : null;
    if (channel === 'pilot' && !pilotAudience) return;
    this.api
      .deploy(this.experienceId(), {
        channel,
        release_id: release.id,
        expected_current_release_id: this.expectedDeploymentReleaseIds()[channel],
        expected_deployment_updated_at: this.expectedDeploymentUpdatedAts()[channel],
        ...(pilotAudience ? { audience: pilotAudience } : {}),
      })
      .subscribe({
        next: () => {
          this.busy.set(false);
          this.deployed.emit();
          this.close();
        },
        error: (err) => {
          const conflict = apiCode(err) === 'EXPERIENCE_DEPLOYMENT_CONFLICT';
          this.error.set(conflict
            ? this.i18n.t('experience.deployment.conflict')
            : studioError(this.i18n, err, 'experience.publish.error'));
          if (conflict) this.refreshRequested.emit();
          this.busy.set(false);
          queueMicrotask(() => this.deployRetry()?.nativeElement.focus());
        },
      });
  }

  private syncDeploymentCas(deployments: readonly StudioDeployment[]): void {
    const pilot = deployments.find((item) => item.channel === 'pilot');
    const live = deployments.find((item) => item.channel === 'live');
    this.expectedDeploymentReleaseIds.set({
      pilot: pilot?.release_id ?? null,
      live: live?.release_id ?? null,
    });
    this.expectedDeploymentUpdatedAts.set({
      pilot: pilot?.updated_at ?? null,
      live: live?.updated_at ?? null,
    });
  }

  private audienceValues(policy: Record<string, unknown>, key: 'roles' | 'groups'): string[] {
    const raw = policy[key];
    return Array.isArray(raw)
      ? raw.filter((item, index, all): item is string =>
          typeof item === 'string' && !!item.trim() && all.indexOf(item) === index)
      : [];
  }

  close(): void {
    if (this.busy()) return;
    const target = this.previousFocus;
    this.closed.emit();
    queueMicrotask(() => target?.focus());
  }
}
