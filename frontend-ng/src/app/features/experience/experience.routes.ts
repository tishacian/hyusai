import { Routes } from '@angular/router';
import { experienceStudioEditGuard, experienceStudioGuard, experienceV1Guard } from './experience.guard';

export const experienceRoutes: Routes = [
  {
    path: '',
    canActivate: [experienceV1Guard, experienceStudioGuard],
    loadComponent: () =>
      import('./create-hub.component').then((m) => m.CreateHubComponent),
  },
  {
    path: 'apps',
    canActivate: [experienceV1Guard, experienceStudioGuard],
    loadComponent: () =>
      import('./business-apps-page.component').then((m) => m.BusinessAppsPageComponent),
  },
  {
    path: 'apps/new',
    canActivate: [experienceV1Guard, experienceStudioEditGuard],
    loadComponent: () =>
      import('./studio/wizard.component').then((m) => m.ExperienceWizardComponent),
  },
  {
    path: 'apps/:id',
    canActivate: [experienceV1Guard, experienceStudioGuard],
    loadComponent: () =>
      import('./studio/editor.component').then((m) => m.ExperienceEditorComponent),
  },
  {
    path: 'preview',
    canActivate: [experienceV1Guard, experienceStudioGuard],
    loadComponent: () =>
      import('./runtime/preview-page.component').then((m) => m.ExperiencePreviewPageComponent),
  },
];
