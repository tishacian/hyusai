import { Component } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';

interface AccountLink {
  label: string;
  icon: string;
  route: string;
  description: string;
}

@Component({
  selector: 'app-account-shell',
  standalone: true,
  imports: [RouterLink, RouterLinkActive, RouterOutlet, IconComponent, SectionHeaderComponent],
  template: `
    <div class="max-w-5xl mx-auto">
      <app-section-header
        breadcrumb="Account"
        title="My account"
        icon="user-round"
        subtitle="Manage your profile, security and preferences."
      />

      <div class="grid grid-cols-1 md:grid-cols-[240px_1fr] gap-6 md:gap-8">
        <aside class="space-y-1">
          @for (link of links; track link.route) {
            <a
              [routerLink]="link.route"
              routerLinkActive="bg-brand-500/10 text-white ring-1 ring-brand-500/30 shadow-glow-sm"
              [routerLinkActiveOptions]="{ exact: false }"
              class="block px-3 py-2.5 rounded-md border border-transparent text-sm text-gray-400 hover:text-white hover:bg-white/5 transition"
            >
              <div class="flex items-center gap-2.5">
                <app-icon [name]="link.icon" [size]="16" class="text-brand-400" />
                <span class="font-medium">{{ link.label }}</span>
              </div>
              <div class="text-xs text-gray-500 mt-0.5 pl-6">{{ link.description }}</div>
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
  links: AccountLink[] = [
    { label: 'Profile', icon: 'user-round', route: 'profile', description: 'Name, phone, company' },
    { label: 'Password', icon: 'key-round', route: 'password', description: 'Change your password' },
    { label: 'Security', icon: 'shield', route: 'security', description: 'Two-factor auth' },
    { label: 'Sessions', icon: 'laptop', route: 'sessions', description: 'Active sign-ins' },
    { label: 'Danger zone', icon: 'shield-alert', route: 'danger', description: 'Delete account' },
  ];
}
