import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { CaptureExperienceService } from '@app/core/capture-experience.service';
import { KnowledgeCaptureComponent } from '../knowledge-capture.component';
import { CaptureFilShellComponent } from './capture-fil-shell.component';

/**
 * URL-stable wrapper for `/knowledge/capture`. Renders the frozen v0 monolith
 * (`<app-knowledge-capture>`, default) or the new cockpit experience
 * (`<app-capture-fil-shell>`) depending on the `capture_experience` flag.
 *
 * Both heavy components are loaded via `@defer` so only the active experience's
 * chunk is fetched — the v0 path is byte-for-byte the same monolith chunk as
 * before, just reached through this wrapper. Existing users (flag `v0`) are
 * unaffected.
 */
@Component({
  selector: 'app-capture-router',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [KnowledgeCaptureComponent, CaptureFilShellComponent],
  template: `
    @if (experience() === 'fil') {
      @defer (on immediate) {
        <app-capture-fil-shell />
      }
    } @else {
      @defer (on immediate) {
        <app-knowledge-capture />
      }
    }
  `,
})
export class CaptureRouterComponent {
  private readonly captureExperience = inject(CaptureExperienceService);

  protected readonly experience = computed(() => this.captureExperience.experience());

  constructor() {
    // The root flag service is created at app start (before this route
    // activates), so re-read the `?exp=` deep-link override now.
    this.captureExperience.syncFromUrl();
  }
}
