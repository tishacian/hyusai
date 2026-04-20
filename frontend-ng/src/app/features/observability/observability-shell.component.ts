import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { IconComponent } from '@app/shared/ui/icon.component';

interface Tab {
  label: string;
  icon: string;
  route: string;
  exact?: boolean;
}

@Component({
  selector: 'app-observability-shell',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, RouterLinkActive, RouterOutlet, IconComponent],
  template: `
    <div class="flex items-center gap-1 mb-6 border-b border-white/5">
      @for (t of tabs; track t.route) {
        <a
          [routerLink]="t.route"
          [routerLinkActiveOptions]="{ exact: t.exact ?? false }"
          routerLinkActive="text-white border-brand-500 bg-brand-500/10"
          class="inline-flex items-center gap-1.5 px-3.5 py-2 text-sm font-medium text-gray-400 border-b-2 border-transparent hover:text-white hover:bg-white/5 transition"
        >
          <app-icon [name]="t.icon" [size]="14" />
          {{ t.label }}
        </a>
      }
    </div>
    <router-outlet />
  `,
})
export class ObservabilityShellComponent {
  readonly tabs: Tab[] = [
    { label: 'Quality', icon: 'activity', route: '/observability', exact: true },
    { label: 'Performance', icon: 'gauge', route: '/observability/performance' },
    { label: 'Traces', icon: 'git-commit', route: '/observability/traces' },
  ];
}
