import { Routes } from '@angular/router';

export const orchestrationRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./flow/flow-builder.component').then((m) => m.FlowBuilderComponent),
  },
];
