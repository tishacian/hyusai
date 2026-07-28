import { Routes } from '@angular/router';

/** Feature-local routes for the Nawa ITSD workspace app. */
export const nawaRoutes: Routes = [
  { path: '', redirectTo: 'itsd', pathMatch: 'full' },
  {
    path: 'itsd',
    loadComponent: () =>
      import('./nawa-itsd-catalog.component').then((m) => m.NawaItsdCatalogComponent),
  },
  {
    path: 'itsd/password-reset',
    loadComponent: () =>
      import('./nawa-password-reset.component').then((m) => m.NawaPasswordResetComponent),
  },
  {
    path: 'itsd/assistant',
    loadComponent: () =>
      import('./nawa-assistant.component').then((m) => m.NawaAssistantComponent),
  },
];
