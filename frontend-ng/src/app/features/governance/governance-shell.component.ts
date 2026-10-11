import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';

/**
 * Governance parent shell — pass-through for `/governance/*` routes.
 * Destinations live in the Administrer sommaire (L12); no second tab menu.
 */
@Component({
  selector: 'app-governance-shell',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterOutlet],
  template: `<router-outlet />`,
})
export class GovernanceShellComponent {}
