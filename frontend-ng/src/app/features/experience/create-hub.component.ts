import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
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
import { WorkApiService } from './work/work-api.service';
import { hasDeployment, type WorkExperience } from './work/work-catalog';

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
  private readonly workApi = inject(WorkApiService);
  readonly deployedApps = signal<WorkExperience[]>([]);

  constructor() {
    this.workApi.listExperiences().subscribe((rows) => {
      this.deployedApps.set(rows.filter(hasDeployment));
    });
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
