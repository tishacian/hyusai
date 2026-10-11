import { Routes } from '@angular/router';

export const skillsRoutes: Routes = [
  {
    path: '',
    loadComponent: () => import('./skills.component').then((m) => m.SkillsComponent),
  },
  {
    path: ':skillId',
    loadComponent: () => import('./skill-view.component').then((m) => m.SkillViewComponent),
  },
];
