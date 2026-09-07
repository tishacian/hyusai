import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  OnInit,
  inject,
  signal,
} from '@angular/core';
import { Router } from '@angular/router';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { CanonicalApiService, type System } from '@app/core/canonical-api.service';

/**
 * `/intelligence` is not a bespoke page anymore — it is a *pre-selected*
 * System. This thin resolver looks up the workspace's Intelligence System
 * (seeded at backend boot, see `app/services/systems/bootstrap.py`) and
 * redirects the user to `/systems/:id?facet=intelligence`.
 *
 * Fallback: if the seed hasn't run yet, we display a tiny placeholder and
 * retry once a few seconds later. This keeps the cockpit deterministic
 * even when the backend is still initializing.
 */
@Component({
  selector: 'app-intelligence-entry',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (error()) {
      <div class="ck-surface rounded-md p-8 text-center">
        <h2 class="text-base font-semibold text-white mb-2">
          Initializing your News Lab…
        </h2>
        <p class="text-xs text-gray-400 max-w-lg mx-auto leading-relaxed">
          The intelligence System is being provisioned for this workspace.
          This usually takes a few seconds at first boot — we'll redirect
          you automatically.
        </p>
        <p class="text-[11px] text-gray-500 mt-3 ck-mono">
          Retry in {{ retryIn() }}s
        </p>
      </div>
    } @else {
      <div class="ck-surface rounded-md p-5 text-center text-xs text-gray-400">
        Resolving Intelligence System…
      </div>
    }
  `,
})
export class IntelligenceEntryComponent implements OnInit, OnDestroy {
  private readonly canonical = inject(CanonicalApiService);
  private readonly router = inject(Router);
  private readonly navigation = inject(ZoomContextService);

  readonly error = signal(false);
  readonly retryIn = signal(3);

  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private countdown: ReturnType<typeof setInterval> | null = null;

  ngOnInit(): void {
    // Intelligence is a canonical System — surface the redirect to the
    // breadcrumb by clearing any stale focus first; `SystemViewComponent`
    // The destination route is the sole owner of the selected System.
    this.resolve();
  }

  ngOnDestroy(): void {
    if (this.retryTimer) clearTimeout(this.retryTimer);
    if (this.countdown) clearInterval(this.countdown);
  }

  private resolve(): void {
    this.canonical.listSystems().subscribe({
      next: (systems) => {
        const intel = this.pickIntelligenceSystem(systems);
        if (intel) {
          void this.router.navigateByUrl(
            this.navigation.objectUrl('system', intel.id, { facet: 'intelligence' }),
            { replaceUrl: true },
          );
        } else {
          this.scheduleRetry();
        }
      },
      error: () => this.scheduleRetry(),
    });
  }

  private pickIntelligenceSystem(systems: System[]): System | null {
    if (!systems || systems.length === 0) return null;
    const byTemplate = systems.find((s) => {
      const flow = (s.flow_definition ?? {}) as Record<string, unknown>;
      return flow['template_id'] === 'sentinel-ci-intelligence';
    });
    if (byTemplate) return byTemplate;
    const byVariant = systems.find((s) => {
      const flow = (s.flow_definition ?? {}) as Record<string, unknown>;
      return flow['variant'] === 'intelligence';
    });
    if (byVariant) return byVariant;
    // Fallback: match by conventional name so older seeds still resolve.
    return (
      systems.find((s) => s.name === 'News Lab') ??
      systems.find((s) => /news\s*lab/i.test(s.name ?? '')) ??
      null
    );
  }

  private scheduleRetry(): void {
    this.error.set(true);
    this.retryIn.set(3);
    if (this.countdown) clearInterval(this.countdown);
    this.countdown = setInterval(() => {
      this.retryIn.update((n) => Math.max(0, n - 1));
    }, 1000);
    this.retryTimer = setTimeout(() => {
      if (this.countdown) clearInterval(this.countdown);
      this.error.set(false);
      this.resolve();
    }, 3000);
  }
}
