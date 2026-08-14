import { ChangeDetectionStrategy, Component, effect, inject, input, output, signal } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { apiMessage, StudioApiService, type StudioRelease } from './studio-api.service';
import { canCreateRelease, canDeploy, type ReadyCheck } from './studio-publish';

@Component({
  selector: 'app-experience-publish-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './studio.scss',
  template: `
    @if (open()) {
      <div class="xp-pub" role="presentation">
        <button
          type="button"
          class="xp-pub-back"
          [attr.aria-label]="i18n.t('experience.publish.close')"
          [disabled]="busy()"
          (click)="closed.emit()"
        ></button>
        <section class="xp-pub-dialog" role="dialog" aria-modal="true" aria-labelledby="xp-pub-title">
          <p class="xp-hint">{{ i18n.t('experience.publish.eyebrow') }}</p>
          <h2 id="xp-pub-title">{{ i18n.t('experience.publish.title') }}</h2>
          <p>{{ i18n.t('experience.publish.subtitle') }}</p>

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
                [value]="notes()"
                [placeholder]="i18n.t('experience.publish.notes.placeholder')"
                [disabled]="busy()"
                (input)="onNotes($event)"
              ></textarea>
            </label>
          } @else {
            <p>{{ i18n.t('experience.publish.released', { n: release()!.release_number }) }}</p>
            <label class="xp-field">
              <span>{{ i18n.t('experience.publish.channel') }}</span>
              <select [value]="channel()" (change)="onChannel($event)">
                <option value="pilot">{{ i18n.t('experience.publish.channel.pilot') }}</option>
                <option value="live">{{ i18n.t('experience.publish.channel.live') }}</option>
              </select>
            </label>
          }

          @if (error(); as err) {
            <p class="xp-error" role="alert">{{ err }}</p>
          }

          <div class="xp-row">
            <button type="button" class="xp-btn" [disabled]="busy()" (click)="closed.emit()">
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
            } @else {
              <button
                type="button"
                class="xp-btn xp-btn-primary"
                [disabled]="busy() || !canDeployNow()"
                (click)="deployNow()"
              >
                {{ busy() ? i18n.t('experience.publish.deploying') : i18n.t('experience.publish.deploy') }}
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
  readonly experienceId = input.required<string>();
  readonly audience = input<Record<string, unknown>>({});
  readonly open = input(false);
  readonly closed = output();
  readonly deployed = output();

  readonly check = signal<ReadyCheck | null>(null);
  readonly notes = signal('');
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly release = signal<StudioRelease | null>(null);
  readonly channel = signal<'pilot' | 'live'>('pilot');

  constructor() {
    effect(() => {
      if (!this.open()) return;
      this.check.set(null);
      this.release.set(null);
      this.notes.set('');
      this.error.set(null);
      this.api.readyCheck(this.experienceId()).subscribe({
        next: (body) => this.check.set(body),
        error: (err) => this.error.set(apiMessage(err, this.i18n.t('experience.publish.error'))),
      });
    });
  }

  canRelease(): boolean {
    return canCreateRelease({ blockers: this.check()?.blockers ?? [{ code: 'pending' }], notes: this.notes() });
  }

  canDeployNow(): boolean {
    return canDeploy({ releaseId: this.release()?.id, channel: this.channel() });
  }

  onNotes(event: Event): void {
    this.notes.set((event.target as HTMLTextAreaElement).value);
  }

  onChannel(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    if (value === 'live' || value === 'pilot') this.channel.set(value);
  }

  releaseNow(): void {
    if (!this.canRelease()) return;
    this.busy.set(true);
    this.error.set(null);
    this.api.createRelease(this.experienceId(), this.notes().trim()).subscribe({
      next: (row) => {
        this.release.set(row);
        this.busy.set(false);
      },
      error: (err) => {
        this.error.set(apiMessage(err, this.i18n.t('experience.publish.error')));
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
        channel: this.channel(),
        release_id: release.id,
        audience: this.audience(),
      })
      .subscribe({
        next: () => {
          this.busy.set(false);
          this.deployed.emit();
          this.closed.emit();
        },
        error: (err) => {
          this.error.set(apiMessage(err, this.i18n.t('experience.publish.error')));
          this.busy.set(false);
        },
      });
  }
}
