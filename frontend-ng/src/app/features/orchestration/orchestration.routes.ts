import { Routes } from '@angular/router';

export const orchestrationRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./workflow-editor.component').then((m) => m.WorkflowEditorComponent),
  },
];
