import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { PageFrameComponent, CkObjectHeaderComponent } from '@app/shared/cockpit';
import type { CaptureViewReference } from '@app/core/api.service';
import { CaptureEngine, type CaptureSessionInfo } from './capture-engine';
import { LeFilSessionComponent } from './le-fil-session.component';
import { ReportProvenanceComponent } from './report-provenance.component';
import { CaptureFilDashboardComponent } from './surfaces/capture-fil-dashboard.component';
import { CaptureFilPrepComponent } from './surfaces/capture-fil-prep.component';
import { CaptureFilPlanComponent } from './surfaces/capture-fil-plan.component';
import { CaptureFilPublishComponent } from './surfaces/capture-fil-publish.component';

/** The autonomous "Le Fil" capture flow surfaces, owned by the shell. */
export type CaptureFilSurface =
  | 'dashboard'
  | 'prep'
  | 'plan'
  | 'session'
  | 'review'
  | 'publish';

interface SurfaceTab {
  id: CaptureFilSurface;
  label: string;
}

/**
 * CaptureFilShellComponent — the cockpit shell of the new autonomous capture
 * experience (Phase 1 / D0). Owns the surface switch (`dashboard | prep | plan
 * | session | review | publish`) and routes each surface to its (placeholder)
 * component. Provides {@link CaptureEngine} so all surfaces and their children
 * share one engine instance scoped to this capture experience.
 *
 * Downstream agents flesh out the disjoint surface/widget files; they do **not**
 * edit this shell.
 */
@Component({
  selector: 'app-capture-fil-shell',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [CaptureEngine],
  imports: [
    PageFrameComponent,
    CkObjectHeaderComponent,
    LeFilSessionComponent,
    ReportProvenanceComponent,
    CaptureFilDashboardComponent,
    CaptureFilPrepComponent,
    CaptureFilPlanComponent,
    CaptureFilPublishComponent,
  ],
  template: `
    <ck-page-frame eyebrow="Knowledge · Capture" title="Le Fil" [hasActions]="false">
      <ck-object-header
        eyebrow="CAPTURE EXPERIENCE"
        title="Le Fil"
        subtitle="Expérience de capture autonome en cockpit (derrière le flag capture_experience)."
      />

      <nav
        class="ck-surface"
        style="display:flex; gap:4px; padding:4px; border-radius:8px; margin-bottom:16px; flex-wrap:wrap;"
      >
        @for (tab of tabs; track tab.id) {
          <button
            type="button"
            class="ck-mono"
            (click)="surface.set(tab.id)"
            style="padding:6px 12px; border-radius:6px; font-size:10px; letter-spacing:0.14em; text-transform:uppercase; border:none; cursor:pointer;"
            [style.background]="surface() === tab.id ? 'var(--ck-bg-inset)' : 'transparent'"
            [style.color]="surface() === tab.id ? 'var(--ck-fg-1)' : 'var(--ck-fg-4)'"
            [style.boxShadow]="surface() === tab.id ? 'inset 0 0 0 1px var(--ck-stroke-3)' : 'none'"
          >
            {{ tab.label }}
          </button>
        }
      </nav>

      @switch (surface()) {
        @case ('dashboard') {
          <app-capture-fil-dashboard (newCapture)="surface.set('prep')" (openSession)="onOpenSession($event)" />
        }
        @case ('prep') {
          <app-capture-fil-prep (planReady)="surface.set($event)" />
        }
        @case ('plan') {
          <app-capture-fil-plan (started)="surface.set('session')" />
        }
        @case ('session') {
          <app-le-fil-session (finish)="surface.set('publish')" />
        }
        @case ('review') {
          <app-report-provenance (revisit)="onRevisit($event)" />
        }
        @case ('publish') {
          <app-capture-fil-publish (published)="surface.set('review')" />
        }
      }
    </ck-page-frame>
  `,
})
export class CaptureFilShellComponent {
  private readonly engine = inject(CaptureEngine);

  /** Active surface. Defaults to the dashboard entry point. */
  readonly surface = signal<CaptureFilSurface>('dashboard');

  protected readonly tabs: SurfaceTab[] = [
    { id: 'dashboard', label: 'Dashboard' },
    { id: 'prep', label: 'Prep' },
    { id: 'plan', label: 'Plan' },
    { id: 'session', label: 'Session' },
    { id: 'review', label: 'Review' },
    { id: 'publish', label: 'Publish' },
  ];

  /** Resume a session picked from the dashboard; route by status. */
  protected onOpenSession(info: CaptureSessionInfo): void {
    this.engine.setSession(info);
    void this.engine.loadDocuments();
    const status = (info.status ?? '').toLowerCase();
    if (['completed', 'published', 'archived'].includes(status)) {
      // Terminal sessions never open a live WS, so hydrate the Fil + anchors
      // from the backend feed projection or the report renders empty.
      void this.engine.hydrateFeed();
      this.surface.set('review');
    } else if (['draft', 'planning', 'plan_ready'].includes(status)) {
      this.surface.set('plan');
    } else {
      // connect() hydrates the feed before subscribing to live WS events.
      void this.engine.connect(info.id);
      this.surface.set('session');
    }
  }

  /** Bidirectional provenance: "Revoir l'instant capté" jumps back to Le Fil. */
  protected onRevisit(_ref: CaptureViewReference): void {
    // Revisiting a terminal session (no live WS): make sure the Fil is hydrated.
    if (!this.engine.feed().length) void this.engine.hydrateFeed();
    this.surface.set('session');
  }
}
