import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import {
  GlyphComponent,
  HelpTooltipComponent,
  PageFrameComponent,
  TagComponent,
  type CkGlyphName,
} from '@app/shared/cockpit';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { canEditExperienceStudio } from './experience-access';
import { StudioApiService } from './studio/studio-api.service';
import { inventoryState, type StudioExperience } from './studio/studio-model';

@Component({
  selector: 'app-create-hub',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    EmptyStateComponent,
    GlyphComponent,
    HelpTooltipComponent,
    PageFrameComponent,
    TagComponent,
  ],
  templateUrl: './create-hub.component.html',
  styleUrl: './create-hub.component.scss',
})
export class CreateHubComponent {
  readonly i18n = inject(I18nService);
  private readonly studioApi = inject(StudioApiService);
  private readonly workspace = inject(WorkspaceService);
  readonly recentApps = signal<StudioExperience[]>([]);
  readonly recentState = signal<'loading' | 'ready' | 'error'>('loading');
  readonly canEdit = computed(() => canEditExperienceStudio(
    this.workspace.current()?.role_template,
    this.workspace.current()?.role,
    this.workspace.isAdmin(),
  ));

  constructor() {
    this.loadRecent();
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

  readonly intents: readonly {
    glyph: CkGlyphName;
    titleKey: 'nav.business_apps' | 'nav.systems' | 'nav.knowledge';
    helpId: string;
    bodyKey: 'experience.hub.intent.app.body' | 'experience.hub.intent.system.body' | 'experience.hub.intent.knowledge.body';
    badges: readonly string[];
    ctaKey: 'experience.hub.intent.app.cta' | 'experience.hub.intent.system.cta' | 'experience.hub.intent.knowledge.cta';
    route: string;
  }[] = [
    {
      glyph: 'orbit',
      titleKey: 'nav.business_apps',
      helpId: '',
      bodyKey: 'experience.hub.intent.app.body',
      badges: [
        'experience.hub.intent.app.badge.templates',
        'experience.hub.intent.app.badge.nocode',
      ],
      ctaKey: 'experience.hub.intent.app.cta',
      route: '/create/apps/new',
    },
    {
      glyph: 'cube',
      titleKey: 'nav.systems',
      helpId: 'concept.system',
      bodyKey: 'experience.hub.intent.system.body',
      badges: ['experience.hub.intent.system.badge'],
      ctaKey: 'experience.hub.intent.system.cta',
      route: '/systems/new',
    },
    {
      glyph: 'layers',
      titleKey: 'nav.knowledge',
      helpId: '',
      bodyKey: 'experience.hub.intent.knowledge.body',
      badges: ['experience.hub.intent.knowledge.badge'],
      ctaKey: 'experience.hub.intent.knowledge.cta',
      route: '/knowledge',
    },
  ];
}
