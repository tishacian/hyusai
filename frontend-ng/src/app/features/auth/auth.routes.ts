import { Routes } from '@angular/router';

export const authRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./auth-shell.component').then((m) => m.AuthShellComponent),
    children: [
      { path: '', redirectTo: 'signin', pathMatch: 'full' },
      {
        path: 'signin',
        loadComponent: () =>
          import('./signin.component').then((m) => m.SigninComponent),
      },
      {
        path: 'signup',
        loadComponent: () =>
          import('./signup.component').then((m) => m.SignupComponent),
      },
      {
        path: 'password-reset',
        loadComponent: () =>
          import('./password-reset.component').then((m) => m.PasswordResetComponent),
      },
    ],
  },
];
