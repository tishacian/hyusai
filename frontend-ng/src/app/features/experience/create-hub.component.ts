import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { switchMap } from 'rxjs';
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

@Component({
  selector: 'app-create-hub',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    NavLinkDirective,
    EmptyStateComponent,
    GlyphComponent,
    HelpTooltipComponent,
    PageFrameComponent,
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
  readonly automationError = signal<string | null>(null);

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

  createAutomation(): void {
    if (!this.canEdit() || this.automationCreating()) return;
    const prompt = this.automationPrompt.trim() || 'New automation';
    this.automationCreating.set(true);
    this.automationError.set(null);
    this.canonical
      .listSkills({ propagateErrors: true })
      .pipe(
        switchMap((skills) => {
          const skill = selectAutomationSkill(skills);
          if (!skill) throw new Error('automation_llm_unavailable');
          return this.canonical.createSystem(
            automationSystemBody(skill, prompt),
            { propagateErrors: true },
          );
        }),
      )
      .subscribe({
        next: (system) => {
          this.automationCreating.set(false);
          if (!system) throw new Error('automation_create_failed');
          void this.router.navigateByUrl(
            navigationLeafUrl('system-flow', { ref: system.id }),
          );
        },
        error: () => {
          this.automationCreating.set(false);
          this.automationError.set('experience.hub.automation.error');
        },
      });
  }

}
