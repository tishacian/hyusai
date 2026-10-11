import { Component, inject } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { I18nService } from '@app/core/i18n.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';

interface AccountLink {
  labelKey: string;
  icon: string;
  route: string;
  descriptionKey: string;
}

@Component({
  selector: 'app-account-shell',
  standalone: true,
  imports: [RouterLink, RouterLinkActive, RouterOutlet, IconComponent, SectionHeaderComponent],
  template: `
    <div class="max-w-5xl mx-auto">
      <app-section-header
        [breadcrumb]="i18n.t('account.shell.breadcrumb')"
        [title]="i18n.t('account.shell.title')"
        icon="user-round"
        [subtitle]="i18n.t('account.shell.subtitle')"
      />

      <div class="grid grid-cols-1 md:grid-cols-[240px_1fr] gap-6 md:gap-8">
        <aside class="space-y-1">
          @for (link of links; track link.route) {
            <a
              [routerLink]="link.route"
              routerLinkActive="bg-cyan-500/10 text-white ring-1 ring-cyan-500/30 shadow-glow-sm"
              [routerLinkActiveOptions]="{ exact: false }"
              class="block px-3 py-2.5 rounded-md border border-transparent text-sm text-gray-400 hover:text-white hover:bg-white/5 transition"
            >
              <div class="flex items-center gap-2.5">
                <app-icon [name]="link.icon" [size]="16" class="text-cyan-400" />
                <span class="font-medium">{{ i18n.t(link.labelKey) }}</span>
              </div>
              <div class="text-xs text-gray-500 mt-0.5 pl-6">{{ i18n.t(link.descriptionKey) }}</div>
            </a>
          }
        </aside>

        <section class="min-w-0">
          <router-outlet />
        </section>
      </div>
    </div>
  `,
})
export class AccountShellComponent {
  readonly i18n = inject(I18nService);

  links: AccountLink[] = [
    {
      labelKey: 'account.profile',
      icon: 'user-round',
      route: 'profile',
      descriptionKey: 'account.shell.profile.description',
    },
    {
      labelKey: 'account.password',
      icon: 'key-round',
      route: 'password',
      descriptionKey: 'account.shell.password.description',
    },
    {
      labelKey: 'account.security',
      icon: 'shield',
      route: 'security',
      descriptionKey: 'account.shell.security.description',
    },
    {
      labelKey: 'account.sessions',
      icon: 'laptop',
      route: 'sessions',
      descriptionKey: 'account.shell.sessions.description',
    },
    {
      labelKey: 'account.danger',
      icon: 'shield-alert',
      route: 'danger',
      descriptionKey: 'account.shell.danger.description',
    },
  ];
}
