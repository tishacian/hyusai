import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { CaptureExperienceService } from '@app/core/capture-experience.service';
import { NavigationProfileService } from '@app/core/navigation-profile.service';
import { KnowledgeCaptureComponent } from '../knowledge-capture.component';
import { CaptureFilShellComponent } from './capture-fil-shell.component';
import {
  collectionCaptureFacetUrl,
  systemCaptureFacetUrl,
} from '../knowledge-capture-redirect';

/**
 * URL-stable wrapper for `/knowledge/capture`. L19 redirects hosted Capture to
 * the owning object's Capture facet in the full chrome; the business shell keeps
 * `/knowledge/capture?systemId=` (allowed primary surface).
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
  private readonly navigationProfile = inject(NavigationProfileService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  protected readonly experience = computed(() => this.captureExperience.experience());

  constructor() {
    this.captureExperience.syncFromUrl();
    const params = this.route.snapshot.queryParamMap;
    const systemId = (params.get('systemId') || params.get('system_id') || '').trim();
    const collection = (
      params.get('collection') || params.get('collectionId') || params.get('kbId') || ''
    ).trim();

    if (systemId && !this.navigationProfile.businessShellActive()) {
      void this.router.navigateByUrl(systemCaptureFacetUrl(systemId), { replaceUrl: true });
      return;
    }
    if (collection) {
      const query: Record<string, string | null> = {};
      params.keys.forEach((key) => {
        query[key] = params.get(key);
      });
      void this.router.navigateByUrl(collectionCaptureFacetUrl(collection, query), {
        replaceUrl: true,
      });
    }
  }
}
