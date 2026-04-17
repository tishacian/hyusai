import { Component } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

interface AccountLink {
  label: string;
  icon: string;
  route: string;
  description: string;
}

@Component({
  selector: 'app-account-shell',
  standalone: true,
  imports: [RouterLink, RouterLinkActive, RouterOutlet],
  template: `
    <div class="max-w-5xl mx-auto">
      <header class="mb-6">
        <h1 class="text-2xl font-bold text-gray-900 dark:text-white">My account</h1>
        <p class="text-sm text-gray-500 dark:text-gray-400 mt-1">
          Manage your profile, security and preferences.
        </p>
      </header>

      <div class="grid grid-cols-1 md:grid-cols-[220px_1fr] gap-6">
        <aside class="space-y-1">
          @for (link of links; track link.route) {
            <a
              [routerLink]="link.route"
              routerLinkActive="bg-brand-500/10 text-brand-600 dark:text-brand-300 border-brand-500"
              [routerLinkActiveOptions]="{ exact: false }"
              class="flex items-start gap-2 px-3 py-2 rounded-lg border border-transparent hover:bg-gray-50 dark:hover:bg-gray-800 transition text-sm text-gray-700 dark:text-gray-200"
            >
              <span class="text-base mt-0.5">{{ link.icon }}</span>
              <div>
                <div class="font-medium">{{ link.label }}</div>
                <div class="text-xs text-gray-500 dark:text-gray-400">{{ link.description }}</div>
              </div>
            </a>
          }
        </aside>

        <section class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-6 min-h-[360px]">
          <router-outlet />
        </section>
      </div>
    </div>
  `,
})
export class AccountShellComponent {
  links: AccountLink[] = [
    { label: 'Profile', icon: '👤', route: 'profile', description: 'Name, phone, company' },
    { label: 'Password', icon: '🔑', route: 'password', description: 'Change your password' },
    { label: 'Security', icon: '🔐', route: 'security', description: 'Two-factor auth' },
    { label: 'Sessions', icon: '💻', route: 'sessions', description: 'Active sign-ins' },
    { label: 'Danger zone', icon: '⚠️', route: 'danger', description: 'Delete account' },
  ];
}
