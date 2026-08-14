import { DOCUMENT } from '@angular/common';
import { A11yModule } from '@angular/cdk/a11y';
import { ChangeDetectionStrategy, Component, effect, inject, input, output, signal } from '@angular/core';
import { HelpTooltipComponent } from '@app/shared/cockpit';
import { I18nService } from '@app/core/i18n.service';
import { apiCode, studioError, StudioApiService, type StudioDraft, type StudioRelease } from './studio-api.service';
import { canCreateRelease, canDeploy, type ReadyCheck } from './studio-publish';

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
          <p class="xp-hint">{{ i18n.t('experience.publish.eyebrow') }}</p>
          <h2 id="xp-pub-title">{{ i18n.t('experience.publish.title') }}</h2>
          <p>{{ i18n.t('experience.publish.subtitle') }}</p>

          <dl class="xp-recap">
            <dt>{{ i18n.t('experience.publish.recap.pages') }}</dt>
            <dd>{{ i18n.t('experience.publish.recap.pages.n', { n: summary().pages, c: summary().components }) }}</dd>
            <dt>
              {{ i18n.t('experience.publish.recap.bindings') }}
              <ck-help id="concept.binding" />
            </dt>
            <dd>
              @if (summary().bindingKeys.length === 0) {
                {{ i18n.t('experience.publish.recap.none') }}
              } @else {
                <code>{{ summary().bindingKeys.join(', ') }}</code>
              }
            </dd>
            <dt>{{ i18n.t('experience.publish.recap.audience') }}</dt>
            <dd>{{ audienceText() }}</dd>
            <dt>{{ i18n.t('experience.publish.recap.languages') }}</dt>
            <dd>{{ languagesText() }}</dd>
            <dt>{{ i18n.t('experience.publish.recap.revision') }}</dt>
            <dd><code>r{{ draft().revision }}</code></dd>
            <dt>{{ i18n.t('experience.publish.recap.hash') }}</dt>
            <dd><code>{{ draft().content_sha256 }}</code></dd>
          </dl>

          @if (!check()) {
            <p class="xp-hint">{{ i18n.t('experience.publish.loading') }}</p>
          } @else {
            @if (check()!.blockers.length > 0) {
              <p>{{ i18n.t('experience.publish.blockers') }}</p>
              <ul class="xp-issues is-block">
                @for (item of check()!.blockers; track item.code ?? item.message) {
                  <li>{{ item.message || item.code }}</li>
                }
              </ul>
            } @else if (!release()) {
              <p>{{ i18n.t('experience.publish.ready') }}</p>
            }
            @if (check()!.warnings.length > 0) {
              <p>{{ i18n.t('experience.publish.warnings') }}</p>
              <ul class="xp-issues">
                @for (item of check()!.warnings; track item.code ?? item.message) {
                  <li>{{ item.message || item.code }}</li>
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
          } @else {
            <p>{{ i18n.t('experience.publish.released', { n: release()!.release_number }) }}</p>
            @if (channel() === 'none') {
              <p class="xp-hint">{{ i18n.t('experience.publish.channel.none.done') }}</p>
            } @else {
              <p class="xp-hint">{{ i18n.t('experience.publish.deploy.separate', { channel: i18n.t('experience.publish.channel.' + channel()) }) }}</p>
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
                {{ busy() ? i18n.t('experience.publish.releasing') : i18n.t('experience.publish.release') }}
              </button>
            } @else if (channel() !== 'none') {
              <button
                type="button"
                class="xp-btn xp-btn-primary"
                [disabled]="busy() || !canDeployNow()"
                (click)="deployNow()"
              >
                {{ busy() ? i18n.t('experience.publish.deploying') : i18n.t('experience.publish.deploy') }}
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
  readonly audience = input<Record<string, unknown>>({});
  readonly summary = input<PublishSummary>({
    pages: 0,
    components: 0,
    bindingKeys: [],
    languages: [],
  });
  readonly open = input(false);
  readonly closed = output();
  readonly released = output();
  readonly deployed = output();

  readonly check = signal<ReadyCheck | null>(null);
  readonly notes = signal('');
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly release = signal<StudioRelease | null>(null);
  readonly channels = ['none', 'pilot', 'live'] as const;
  readonly channel = signal<(typeof this.channels)[number]>('pilot');
  private previousFocus: HTMLElement | null = null;

  constructor() {
    effect(() => {
      if (!this.open()) return;
      this.previousFocus = this.document.activeElement instanceof HTMLElement
        ? this.document.activeElement
        : null;
      this.check.set(null);
      this.release.set(null);
      this.notes.set('');
      this.error.set(null);
      this.channel.set('pilot');
      this.api.readyCheck(this.experienceId()).subscribe({
        next: (body) => this.check.set(body),
        error: (err) => this.error.set(studioError(this.i18n, err, 'experience.publish.error')),
      });
    });
  }

  canRelease(): boolean {
    return canCreateRelease({ blockers: this.check()?.blockers ?? [{ code: 'pending' }], notes: this.notes() });
  }

  audienceText(): string {
    const raw = this.audience()['roles'];
    const roles = Array.isArray(raw) ? raw.filter((item): item is string => typeof item === 'string') : [];
    if (roles.length === 0) return this.i18n.t('experience.publish.recap.everyone');
    return roles
      .map((role) => {
        const key = `governance.access.role.${role}`;
        const label = this.i18n.t(key);
        return label === key ? role : label;
      })
      .join(', ');
  }

  languagesText(): string {
    const languages = this.summary().languages;
    return languages.length === 0
      ? this.i18n.t('experience.publish.recap.none')
      : languages.join(', ');
  }

  canDeployNow(): boolean {
    if (this.channel() === 'none') return false;
    return canDeploy({ releaseId: this.release()?.id, channel: this.channel() });
  }

  onNotes(event: Event): void {
    this.notes.set((event.target as HTMLTextAreaElement).value);
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
    }).subscribe({
      next: (row) => {
        this.release.set(row);
        this.busy.set(false);
        this.released.emit();
      },
      error: (err) => {
        const code = apiCode(err);
        this.error.set(
          code === 'EXPERIENCE_DRAFT_REVISION_CONFLICT' || code === 'EXPERIENCE_DRAFT_CONTENT_CONFLICT'
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
    this.api
      .deploy(this.experienceId(), {
        channel: this.channel() as 'pilot' | 'live',
        release_id: release.id,
      })
      .subscribe({
        next: () => {
          this.busy.set(false);
          this.deployed.emit();
          this.close();
        },
        error: (err) => {
          this.error.set(studioError(this.i18n, err, 'experience.publish.error'));
          this.busy.set(false);
        },
      });
  }

  close(): void {
    if (this.busy()) return;
    const target = this.previousFocus;
    this.closed.emit();
    queueMicrotask(() => target?.focus());
  }
}
