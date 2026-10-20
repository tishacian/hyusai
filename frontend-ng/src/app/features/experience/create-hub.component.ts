import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { CanonicalApiService, type RunSystemSummary } from '@app/core/canonical-api.service';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import {
  GlyphComponent,
  HelpTooltipComponent,
  NavLinkDirective,
  PageFrameComponent,
} from '@app/shared/cockpit';
import { navigationLeafUrl } from '@app/core/navigation.catalog';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { canEditExperienceStudio } from './experience-access';
import { StudioApiService } from './studio/studio-api.service';
import { inventoryState, type StudioExperience } from './studio/studio-model';
import { automationSystemBody, selectAutomationSkill } from './hub/automation-draft.model';
import { StartExampleImportComponent } from './hub/example-import.component';
import { StartPrerequisitesComponent } from './hub/prerequisites.component';
import { automationFailure, type AutomationFailure } from './hub/start.model';
import { wizardQueryParams, wizardReturnTo } from './studio/wizard-route';

@Component({
  selector: 'app-create-hub',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    RouterLink,
    NavLinkDirective,
    EmptyStateComponent,
    GlyphComponent,
    HelpTooltipComponent,
    PageFrameComponent,
    StartExampleImportComponent,
    StartPrerequisitesComponent,
  ],
  templateUrl: './create-hub.component.html',
  styleUrl: './create-hub.component.scss',
})
export class CreateHubComponent {
  readonly i18n = inject(I18nService);
  private readonly studioApi = inject(StudioApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly router = inject(Router);
  private readonly queryParams = toSignal(inject(ActivatedRoute).queryParamMap, { requireSync: true });
  readonly recentApps = signal<StudioExperience[]>([]);
  readonly recentState = signal<'loading' | 'ready' | 'error'>('loading');
  readonly recentSystems = signal<RunSystemSummary[]>([]);
  readonly recentSystemsState = signal<'loading' | 'ready' | 'error'>('loading');
  readonly canEdit = computed(() => canEditExperienceStudio(
    this.workspace.current()?.role_template,
    this.workspace.current()?.role,
    this.workspace.isAdmin(),
  ));
  automationPrompt = '';
  readonly automationCreating = signal(false);
  readonly automationError = signal<AutomationFailure | null>(null);
  readonly modelPortalOpen = this.workspace.modelPortalEnabled;

  constructor() {
    this.loadRecent();
    this.loadRecentSystems();
  }

  loadRecent(): void {
    this.recentState.set('loading');
    this.studioApi.listExperiences().subscribe({
      next: (rows) => {
        this.recentApps.set(rows.slice(0, 4));
        this.recentState.set('ready');
      },
      error: () => this.recentState.set('error'),
    });
  }

  state(app: StudioExperience): string {
    return this.i18n.t(`experience.apps.state.${inventoryState(app.deployments)}`);
  }

  loadRecentSystems(): void {
    this.recentSystemsState.set('loading');
    this.canonical.listRunSummaries().subscribe({
      next: (rows) => {
        this.recentSystems.set(rows.slice(0, 3));
        this.recentSystemsState.set('ready');
      },
      error: () => this.recentSystemsState.set('error'),
    });
  }

  systemStatus(status: string | null): string {
    if (!status) return '—';
    const key = `runs.status.${status}`;
    const label = this.i18n.t(key);
    return label === key ? status : label;
  }

  /** An unfinished creation wizard resumes at its step, not in the editor. */
  readonly wizardPath = navigationLeafUrl('create-app-new');
  wizardParams(app: StudioExperience): Record<string, string> {
    return wizardQueryParams(app.id, app.wizard_step ?? 1);
  }

  /** Set when the wizard sent the author here to create the missing System. */
  readonly returnTo = computed(() => {
    const target = wizardReturnTo(this.queryParams().get('returnTo'));
    if (!target) return null;
    const url = new URL(target, 'http://local');
    const params: Record<string, string> = {};
    url.searchParams.forEach((value, key) => { params[key] = value; });
    return { path: url.pathname, params };
  });

  /** "Start from scratch" or "Start from an example": nothing is imported by default. */
  readonly start = signal<'zero' | 'example' | null>(null);

  createAutomation(): void {
    if (!this.canEdit() || this.automationCreating()) return;
    const prompt = this.automationPrompt.trim() || 'New automation';
    const scope = this.workspace.captureRequestScope();
    this.automationCreating.set(true);
    this.automationError.set(null);
    this.canonical.listSkills({ propagateErrors: true }).subscribe({
      next: (skills) => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        const skill = selectAutomationSkill(skills);
        if (!skill) {
          this.automationCreating.set(false);
          this.automationError.set('no_model');
          return;
        }
        this.canonical
          .createSystem(automationSystemBody(skill, prompt), { propagateErrors: true })
          .subscribe({
            next: (system) => {
              if (!this.workspace.isRequestScopeCurrent(scope)) return;
              this.automationCreating.set(false);
              if (!system) {
                // The server answered without a System: whether one exists is unknown.
                this.automationError.set('unverifiable');
                return;
              }
              void this.router.navigateByUrl(navigationLeafUrl('system-flow', { ref: system.id }));
            },
            error: (error: unknown) => {
              if (!this.workspace.isRequestScopeCurrent(scope)) return;
              this.automationCreating.set(false);
              this.automationError.set(automationFailure('create', error));
            },
          });
      },
      error: (error: unknown) => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        this.automationCreating.set(false);
        this.automationError.set(automationFailure('skills', error));
      },
    });
  }

}
