import { Routes } from '@angular/router';

export const intelligenceRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./intelligence-entry.component').then(
        (m) => m.IntelligenceEntryComponent,
      ),
  },
];
