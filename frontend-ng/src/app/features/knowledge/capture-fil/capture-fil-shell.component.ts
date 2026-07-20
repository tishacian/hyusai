import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { PageFrameComponent } from '@app/shared/cockpit';
import type { CaptureViewReference } from '@app/core/api.service';
import { CanonicalApiService, type System } from '@app/core/canonical-api.service';
import { CaptureEngine, type CaptureSessionInfo } from './capture-engine';
import { FSE_INTERVENTION_V1 } from './capture-templates';
import { LeFilSessionComponent } from './le-fil-session.component';
import { ReportProvenanceComponent } from './report-provenance.component';
import { CaptureFilDashboardComponent } from './surfaces/capture-fil-dashboard.component';
import { CaptureFilPrepComponent } from './surfaces/capture-fil-prep.component';
import { CaptureFilPlanComponent } from './surfaces/capture-fil-plan.component';
import { CaptureFilFinalizeComponent } from './surfaces/capture-fil-finalize.component';
import { CaptureFilPublishComponent } from './surfaces/capture-fil-publish.component';

/** The autonomous "Le Fil" capture flow surfaces, owned by the shell. */
export type CaptureFilSurface =
  | 'dashboard'
  | 'prep'
  | 'plan'
  | 'session'
  | 'finalize'
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
    LeFilSessionComponent,
    ReportProvenanceComponent,
    CaptureFilDashboardComponent,
    CaptureFilPrepComponent,
    CaptureFilPlanComponent,
    CaptureFilFinalizeComponent,
    CaptureFilPublishComponent,
  ],
  template: `
    <ck-page-frame [eyebrow]="eyebrow()" [title]="headerTitle()" [hasActions]="false">
      <nav
        class="ck-surface"
        style="display:flex; gap:4px; padding:4px; border-radius:8px; margin-bottom:16px; flex-wrap:wrap;"
      >
        @for (tab of tabs; track tab.id) {
          <button
            type="button"
            class="ck-mono"
            [disabled]="!tabEnabled(tab.id)"
            (click)="surface.set(tab.id)"
            style="padding:6px 12px; border-radius:6px; font-size:10px; letter-spacing:0.14em; text-transform:uppercase; border:none;"
            [style.cursor]="tabEnabled(tab.id) ? 'pointer' : 'not-allowed'"
            [style.opacity]="tabEnabled(tab.id) ? 1 : 0.4"
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
          <app-le-fil-session (finish)="surface.set('finalize')" />
        }
        @case ('finalize') {
          <app-capture-fil-finalize (finalized)="surface.set('review')" />
        }
        @case ('review') {
          <app-report-provenance (revisit)="onRevisit($event)" (publish)="surface.set('publish')" />
        }
        @case ('publish') {
          <app-capture-fil-publish (done)="surface.set('dashboard')" />
        }
      }
    </ck-page-frame>
  `,
  styles: [
    /*
     * Capture-scoped legibility lift. The muted text tiers (--ck-fg-3 secondary,
     * --ck-fg-4 labels/captions, --ck-fg-5 faint: timestamps, hints, bullets)
     * were reported as too low-contrast. We raise all three a further notch here
     * on the shell host only — custom properties cascade to every descendant
     * surface, so the whole capture system reads clearer without touching the
     * global cockpit tokens used by other apps.
     */
    ':host { --ck-fg-3: #aeb7c4; --ck-fg-4: #a2acba; --ck-fg-5: #828b99; }',
    ':host-context(html:not(.dark)) { --ck-fg-3: #3e4451; --ck-fg-4: #434a57; --ck-fg-5: #59606e; }',
    ':host-context([data-theme="light"]) { --ck-fg-3: #3e4451; --ck-fg-4: #434a57; --ck-fg-5: #59606e; }',
  ],
})
export class CaptureFilShellComponent {
  private readonly engine = inject(CaptureEngine);
  private readonly route = inject(ActivatedRoute);
  private readonly systems = inject(CanonicalApiService);

  /** Active surface. Defaults to the dashboard entry point. */
  readonly surface = signal<CaptureFilSurface>('dashboard');

  /**
   * Real system name when the flow is scoped to one. "Le Fil" is the design
   * codename of this experience, not a product name, so the header is titled
   * after the actual system (or the generic capture label at capability level).
   */
  private readonly systemName = signal<string | null>(null);
  private readonly interventionsRoute = signal(false);
  protected readonly headerTitle = computed(() => {
    if (this.systemName()) return this.systemName()!;
    if (this.engine.template()) return this.engine.template()!.label;
    return this.interventionsRoute()
      ? FSE_INTERVENTION_V1.label
      : 'Capture de connaissances';
  });
  protected readonly eyebrow = computed(() =>
    this.engine.template() || this.interventionsRoute()
      ? 'Knowledge · Interventions FSE'
      : 'Knowledge · Capture',
  );

  constructor() {
    // System scope: `/systems/:systemId/capture` (route param) or the stable
    // `/knowledge/capture?systemId=` / `/knowledge/interventions?systemId=` deep
    // links. The interventions route also auto-resolves the FSE system by
    // `settings.capture.template_id` when no systemId is provided.
    const snapshot = this.route.snapshot;
    const path = snapshot.routeConfig?.path || '';
    const isInterventions = path === 'interventions'
      || snapshot.url.some((seg) => seg.path === 'interventions');
    this.interventionsRoute.set(isInterventions);

    const systemId =
      snapshot.paramMap.get('systemId') || snapshot.queryParamMap.get('systemId');
    if (systemId) {
      this.bindSystem(systemId);
    } else if (isInterventions) {
      this.engine.setTemplateId(FSE_INTERVENTION_V1.id);
      this.resolveFseSystem();
    } else {
      this.engine.setSystemId(null);
    }
  }

  private bindSystem(systemId: string): void {
    this.engine.setSystemId(systemId);
    this.systems.getSystem(systemId).subscribe((sys) => {
      if (sys?.name) this.systemName.set(sys.name);
    });
  }

  /** Find the workspace system seeded with the FSE capture template. */
  private resolveFseSystem(): void {
    this.systems.listSystems().subscribe((rows) => {
      const match = (rows || []).find((sys) => this.systemTemplateId(sys) === FSE_INTERVENTION_V1.id)
        || (rows || []).find((sys) => /intervention|fse/i.test(sys.name || ''));
      if (match?.id) {
        this.bindSystem(match.id);
      }
    });
  }

  private systemTemplateId(sys: System): string | null {
    const settings = sys.settings && typeof sys.settings === 'object'
      ? sys.settings as Record<string, unknown>
      : null;
    const capture = settings?.['capture'] && typeof settings['capture'] === 'object'
      ? settings['capture'] as Record<string, unknown>
      : null;
    const raw = capture?.['template_id'];
    return typeof raw === 'string' && raw.trim() ? raw.trim() : null;
  }

  protected readonly tabs: SurfaceTab[] = [
    { id: 'dashboard', label: 'Séances' },
    { id: 'prep', label: 'Préparation' },
    { id: 'plan', label: 'Plan' },
    { id: 'session', label: 'Capture' },
    { id: 'finalize', label: 'Finalisation' },
    { id: 'review', label: 'Revue' },
    { id: 'publish', label: 'Publication' },
  ];

  /**
   * Gate the nav to a linear flow: a tab is reachable only once its prerequisite
   * state exists. Programmatic `surface.set(...)` (resume, planReady, started)
   * still routes freely — this only blocks manual misnavigation (e.g. landing on
   * the live Capture before it was started, which had no Start affordance).
   */
  protected tabEnabled(id: CaptureFilSurface): boolean {
    const hasSession = !!this.engine.sessionId();
    switch (id) {
      case 'dashboard':
      case 'prep':
        return true;
      case 'plan':
        return hasSession;
      case 'session':
        return this.engine.connected() || this.engine.feed().length > 0;
      case 'finalize':
        // Reachable once a session has been started (live or hydrated feed).
        return hasSession || this.engine.connected() || this.engine.feed().length > 0;
      case 'review':
        // Reachable once a report (proposal) has been generated/loaded.
        return !!this.engine.proposal() || !!this.engine.proposalId();
      case 'publish': {
        // Reachable once the report is accepted; if the status isn't reliably
        // present on the loaded proposal, fall back to "a proposal exists".
        if (!this.engine.proposal() && !this.engine.proposalId()) return false;
        const status = (this.engine.proposal()?.status ?? '').toLowerCase();
        if (!status) return true;
        return status === 'accepted' || status === 'published';
      }
      default:
        return true;
    }
  }

  /** Resume a session picked from the dashboard; route by status. */
  protected async onOpenSession(info: CaptureSessionInfo): Promise<void> {
    this.engine.setSession(info);
    void this.engine.loadDocuments();
    const status = (info.status ?? '').toLowerCase();
    if (['completed', 'published', 'archived'].includes(status)) {
      // Terminal sessions never open a live WS, so hydrate the Fil + anchors
      // from the backend feed projection (provenance) and load the persisted
      // proposal so the review fiche renders instead of an empty report.
      void this.engine.hydrateFeed();
      await this.engine.loadProposal();
      this.surface.set('review');
      return;
    }
    // A genuinely in-progress session with NO plan (free conversation) has
    // nothing to configure: routing it to the plan surface traps the operator in
    // a plan editor with no path to the live capture ("bloqué dans le mode
    // configuration plan"). Resume straight into the live session surface,
    // connecting with the right (LiveKit) transport. Fresh/plan-less sessions
    // (not yet started) and every session WITH a plan still land on the launch
    // surface, which owns the single explicit Start/"Reprendre" affordance.
    if (this.engine.isResumable() && this.engine.isFreeConversation()) {
      void this.engine.connect(info.id);
      this.surface.set('session');
      return;
    }
    // Every other non-terminal session lands on the launch surface. We never
    // auto-connect a not-yet-started session — that was the "la capture démarre
    // directe sans bouton" regression. The launch button connects live.
    this.surface.set('plan');
  }

  /** Bidirectional provenance: "Revoir l'instant capté" jumps back to Le Fil. */
  protected onRevisit(ref: CaptureViewReference): void {
    // Revisiting a terminal session (no live WS): make sure the Fil is hydrated.
    if (!this.engine.feed().length) void this.engine.hydrateFeed();
    // Point the session surface at the journaled instant: it scrolls the Fil to
    // the matching feed item (anchor id = event id, else the turn) on render.
    this.engine.revisitTarget.set(ref.event_id ?? ref.turn_id ?? null);
    this.surface.set('session');
  }
}
