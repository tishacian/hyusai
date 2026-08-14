import { Routes } from '@angular/router';
import { experienceV1Guard } from './experience.guard';

export const experienceRoutes: Routes = [
  {
    path: '',
    canActivate: [experienceV1Guard],
    loadComponent: () =>
      import('./create-hub.component').then((m) => m.CreateHubComponent),
  },
  {
    path: 'apps',
    canActivate: [experienceV1Guard],
    loadComponent: () =>
      import('./business-apps-page.component').then((m) => m.BusinessAppsPageComponent),
  },
  {
    path: 'apps/new',
    canActivate: [experienceV1Guard],
    loadComponent: () =>
      import('./studio/wizard.component').then((m) => m.ExperienceWizardComponent),
  },
  {
    path: 'apps/:id',
    canActivate: [experienceV1Guard],
    loadComponent: () =>
      import('./studio/editor.component').then((m) => m.ExperienceEditorComponent),
  },
  {
    path: 'preview',
    canActivate: [experienceV1Guard],
    loadComponent: () =>
      import('./runtime/preview-page.component').then((m) => m.ExperiencePreviewPageComponent),
  },
];
