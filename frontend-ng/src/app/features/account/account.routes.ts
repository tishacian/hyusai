import { Routes } from '@angular/router';

export const accountRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./account-shell.component').then((m) => m.AccountShellComponent),
    children: [
      { path: '', redirectTo: 'profile', pathMatch: 'full' },
      {
        path: 'profile',
        loadComponent: () =>
          import('./profile.component').then((m) => m.ProfileComponent),
      },
      {
        path: 'password',
        loadComponent: () =>
          import('./password.component').then((m) => m.PasswordComponent),
      },
      {
        path: 'security',
        loadComponent: () =>
          import('./security.component').then((m) => m.SecurityComponent),
      },
      {
        path: 'sessions',
        loadComponent: () =>
          import('./sessions.component').then((m) => m.SessionsComponent),
      },
      {
        path: 'danger',
        loadComponent: () =>
          import('./danger.component').then((m) => m.DangerComponent),
      },
    ],
  },
];
