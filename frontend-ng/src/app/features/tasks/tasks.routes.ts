import { Routes } from '@angular/router';

export const tasksRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./tasks-page.component').then((m) => m.TasksPageComponent),
  },
];
