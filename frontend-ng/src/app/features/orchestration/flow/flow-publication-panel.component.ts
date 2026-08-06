import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { IconComponent } from '@app/shared/ui/icon.component';
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
              <p class="ck-publish__eyebrow">Draft → Published</p>
              <h2 id="ck-publish-title">Review publication</h2>
              <p>Creates an immutable version. It never activates or resumes the System.</p>
            </div>
            <button
              type="button"
              class="ck-publish__close"
              aria-label="Close publication review"
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
                Loading the semantic diff…
              </div>
            }
            @case ('error') {
              <div class="ck-publish__state is-error" role="alert">
                <app-icon name="alert-triangle" [size]="15" />
                {{ persistence.publishError() || 'Publication diff unavailable.' }}
              </div>
            }
            @case ('ready') {
              @if (persistence.publishDiff(); as diff) {
                <div class="ck-publish__summary" aria-label="Semantic diff summary">
                  <span data-impact="breaking">{{ diff.summary.breaking }} breaking</span>
                  <span data-impact="behavioral">{{ diff.summary.behavioral }} behavioral</span>
                  <span data-impact="presentation">{{ diff.summary.presentation }} presentation</span>
                </div>

                <ol class="ck-publish__changes" aria-label="Semantic changes">
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
                    <li class="is-empty">No semantic change detected.</li>
                  }
                </ol>

                @if (diff.summary.breaking > 0) {
                  <label class="ck-publish__ack">
                    <input
                      type="checkbox"
                      [checked]="persistence.breakingChangeAcknowledged()"
                      (change)="onBreakingAcknowledgement($event)"
                    />
                    <span>
                      I reviewed the breaking changes and explicitly accept their release impact.
                    </span>
                  </label>
                }
              }
            }
          }

          <label class="ck-publish__message" for="ck-publish-message">
            <span>Release message</span>
            <textarea
              id="ck-publish-message"
              rows="3"
              maxlength="2000"
              placeholder="What changed, why, and what operators should know"
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
              Cancel
            </button>
            <button
              type="button"
              class="is-primary"
              [disabled]="!canSubmit()"
              (click)="publish()"
            >
              @if (persistence.publishing()) {
                <app-icon name="loader-2" [size]="14" class="is-spinning" /> Publishing…
              } @else {
                <app-icon name="upload-cloud" [size]="14" /> Publish immutable version
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
