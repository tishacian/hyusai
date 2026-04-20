import { Routes } from '@angular/router';

export const settingsRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./rag-settings.component').then((m) => m.RagSettingsComponent),
  },
];
