import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import {
  COCKPIT_VERBS,
  cockpitVerbSections,
  navigationSectionNaming,
  type CockpitSection,
  type CockpitSectionGroup,
} from '@app/core/navigation.catalog';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { GlyphComponent, PageFrameComponent } from '@app/shared/cockpit';
import { canGovernExperiences } from './experience-governance.models';

const GROUP_ORDER: CockpitSectionGroup[] = ['workspace', 'integrations', 'governance'];

/**
 * Administrer home at `/governance` — grouped destination list (L12).
 * Sommaire rows and this page share the same catalog; L22 deepens the list.
 */
@Component({
  selector: 'app-administrer-home',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, GlyphComponent, PageFrameComponent],
  template: `
    <ck-page-frame
      [eyebrow]="i18n.t('experience.adoption.nav.govern')"
      [title]="i18n.t('governance.home.title')"
      [description]="i18n.t('governance.home.lead')"
    >
      <div class="admin-home">
        @for (block of grouped(); track block.group) {
          <section class="admin-group">
            <h2 class="admin-group-title">{{ i18n.t('nav.sommaire.group.' + block.group) }}</h2>
            <ul class="admin-list">
              @for (section of block.sections; track section.key) {
                <li>
                  <a class="admin-row" [routerLink]="section.route.split('?')[0]" [queryParams]="queryParams(section)">
                    <ck-glyph [name]="section.glyph" [size]="14" />
                    <span>{{ sectionLabel(section) }}</span>
                  </a>
                </li>
              }
            </ul>
          </section>
        }
      </div>
    </ck-page-frame>
  `,
  styles: [
    `
      .admin-home {
        display: flex;
        flex-direction: column;
        gap: 28px;
        max-width: 560px;
      }
      .admin-group-title {
        margin: 0 0 8px;
        font-family: var(--ck-font-display);
        font-size: 14px;
        font-weight: 600;
        color: var(--ck-fg-2);
      }
      .admin-list {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: 2px;
      }
      .admin-row {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 10px 12px;
        border-radius: 4px;
        color: var(--ck-fg-1);
        text-decoration: none;
        transition: background 120ms var(--ck-ease-out);
      }
      .admin-row:hover {
        background: var(--ck-bg-panel-hi);
      }
    `,
  ],
})
export class AdministrerHomeComponent {
  readonly i18n = inject(I18nService);
  private readonly workspace = inject(WorkspaceService);

  readonly sections = computed(() => {
    const verb = COCKPIT_VERBS.find((item) => item.key === 'govern');
    if (!verb) return [];
    const current = this.workspace.current();
    return cockpitVerbSections(verb, {
      isAdmin: this.workspace.isAdmin(),
      experienceV1: this.workspace.experienceV1Enabled(),
      canGovernExperiences: canGovernExperiences(
        current?.role_template,
        current?.role,
        this.workspace.isAdmin(),
      ),
    });
  });

  readonly grouped = computed(() => {
    const byGroup = new Map<CockpitSectionGroup, CockpitSection[]>();
    for (const section of this.sections()) {
      if (!section.group) continue;
      const list = byGroup.get(section.group) ?? [];
      list.push(section);
      byGroup.set(section.group, list);
    }
    return GROUP_ORDER
      .filter((group) => byGroup.has(group))
      .map((group) => ({ group, sections: byGroup.get(group)! }));
  });

  sectionLabel(section: CockpitSection): string {
    const naming = navigationSectionNaming(section, section.route);
    const translated = this.i18n.t(naming.i18nKey);
    return translated === naming.i18nKey ? naming.label : translated;
  }

  queryParams(section: CockpitSection): Record<string, string> | null {
    if (!section.route.includes('?')) return null;
    const params = new URLSearchParams(section.route.slice(section.route.indexOf('?') + 1));
    const out: Record<string, string> = {};
    params.forEach((value, key) => {
      if (value) out[key] = value;
    });
    return Object.keys(out).length ? out : null;
  }
}
