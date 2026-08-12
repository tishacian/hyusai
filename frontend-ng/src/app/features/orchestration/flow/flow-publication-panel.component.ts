import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { IconComponent } from '@app/shared/ui/icon.component';
import { I18nService } from '@app/core/i18n.service';
import { FlowPersistenceService } from './flow-persistence.service';

/** Explicit, secret-free semantic review between a saved server draft and the
 * immutable published pointer. Publishing never changes System activation. */
@Component({
  selector: 'app-flow-publication-panel',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './flow-publication-panel.component.scss',
  template: `
    @if (persistence.publishReviewOpen()) {
      <div class="ck-publish" role="presentation">
        <button
          type="button"
          class="ck-publish__backdrop"
          aria-label="Close publication review"
          [disabled]="persistence.publishing()"
          (click)="close()"
        ></button>
        <section
          class="ck-publish__dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="ck-publish-title"
        >
          <header class="ck-publish__header">
            <div>
              <p class="ck-publish__eyebrow">{{ i18n.t('flow.publish.eyebrow') }}</p>
              <h2 id="ck-publish-title">{{ i18n.t('flow.publish.title') }}</h2>
              <p>{{ i18n.t('flow.publish.subtitle') }}</p>
            </div>
            <button
              type="button"
              class="ck-publish__close"
              [attr.aria-label]="i18n.t('flow.publish.close')"
              [disabled]="persistence.publishing()"
              (click)="close()"
            >
              <app-icon name="x" [size]="16" />
            </button>
          </header>

          <div class="ck-publish__identities">
            <span>
              Draft r{{ persistence.draftRevision() }}
              <code>{{ shortHash(persistence.savedFlowSha256()) }}</code>
            </span>
            <app-icon name="arrow-right" [size]="13" />
            <span>
              Published v{{ persistence.publishedVersionNumber() }}
              <code>{{ shortHash(persistence.publishedFlowSha256()) }}</code>
            </span>
          </div>

          @switch (persistence.publishDiffState()) {
            @case ('loading') {
              <div class="ck-publish__state" role="status">
                <app-icon name="loader-2" [size]="15" class="is-spinning" />
                {{ i18n.t('flow.publish.diff.loading') }}
              </div>
            }
            @case ('error') {
              <div class="ck-publish__state is-error" role="alert">
                <app-icon name="alert-triangle" [size]="15" />
                {{ persistence.publishError() || i18n.t('flow.publish.diff.error') }}
              </div>
            }
            @case ('ready') {
              @if (persistence.publishDiff(); as diff) {
                <div
                  class="ck-publish__summary"
                  [attr.aria-label]="i18n.t('flow.publish.diff.aria')"
                >
                  <span data-impact="breaking">{{
                    i18n.t('flow.publish.diff.breaking', { count: diff.summary.breaking })
                  }}</span>
                  <span data-impact="behavioral">{{
                    i18n.t('flow.publish.diff.behavioral', { count: diff.summary.behavioral })
                  }}</span>
                  <span data-impact="presentation">{{
                    i18n.t('flow.publish.diff.presentation', { count: diff.summary.presentation })
                  }}</span>
                </div>

                <ol
                  class="ck-publish__changes"
                  [attr.aria-label]="i18n.t('flow.publish.diff.changes.aria')"
                >
                  @for (change of diff.changes; track change.path + change.subject) {
                    <li [attr.data-impact]="change.impact">
                      <div class="ck-publish__change-head">
                        <strong>{{ change.impact }}</strong>
                        <span>{{ change.category }}</span>
                        <code>{{ change.subject }}</code>
                      </div>
                      <p>{{ change.description }}</p>
                    </li>
                  } @empty {
                    <li class="is-empty">{{ i18n.t('flow.publish.diff.empty') }}</li>
                  }
                </ol>

                @if (diff.summary.breaking > 0) {
                  <label class="ck-publish__ack">
                    <input
                      type="checkbox"
                      [checked]="persistence.breakingChangeAcknowledged()"
                      (change)="onBreakingAcknowledgement($event)"
                    />
                    <span>{{ i18n.t('flow.publish.ack') }}</span>
                  </label>
                }
              }
            }
          }

          <label class="ck-publish__message" for="ck-publish-message">
            <span>{{ i18n.t('flow.publish.message') }}</span>
            <textarea
              id="ck-publish-message"
              rows="3"
              maxlength="2000"
              [placeholder]="i18n.t('flow.publish.message.placeholder')"
              [value]="message()"
              [disabled]="persistence.publishing()"
              (input)="onMessage($event)"
            ></textarea>
          </label>

          @if (persistence.publishError(); as error) {
            <p class="ck-publish__error" role="alert">{{ error }}</p>
          }

          <footer class="ck-publish__actions">
            <button type="button" (click)="close()" [disabled]="persistence.publishing()">
              {{ i18n.t('flow.publish.cancel') }}
            </button>
            <button
              type="button"
              class="is-primary"
              [disabled]="!canSubmit()"
              (click)="publish()"
            >
              @if (persistence.publishing()) {
                <app-icon name="loader-2" [size]="14" class="is-spinning" />
                {{ i18n.t('flow.publish.submitting') }}
              } @else {
                <app-icon name="upload-cloud" [size]="14" />
                {{ i18n.t('flow.publish.submit') }}
              }
            </button>
          </footer>
        </section>
      </div>
    }
  `,
})
export class FlowPublicationPanelComponent {
  protected readonly persistence = inject(FlowPersistenceService);
  readonly i18n = inject(I18nService);
  protected readonly message = signal('');
  protected readonly canSubmit = computed(
    () =>
      this.message().trim().length > 0 &&
      this.persistence.canConfirmPublication(),
  );

  constructor() {
    effect(() => {
      if (!this.persistence.publishReviewOpen()) this.message.set('');
    });
  }

  protected shortHash(value: string | null): string {
    return value ? value.slice(0, 10) : '—';
  }

  protected onMessage(event: Event): void {
    this.message.set((event.target as HTMLTextAreaElement).value);
  }

  protected onBreakingAcknowledgement(event: Event): void {
    this.persistence.setBreakingChangeAcknowledged(
      (event.target as HTMLInputElement).checked,
    );
  }

  protected publish(): void {
    this.persistence.publishDraft(this.message());
  }

  protected close(): void {
    this.persistence.closePublicationReview();
  }
}
