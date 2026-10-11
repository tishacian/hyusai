import { Routes } from '@angular/router';

export const presetsRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./presets-list.component').then((m) => m.PresetsListComponent),
  },
  {
    path: 'evaluation',
    loadComponent: () =>
      import('./evaluation-preset.component').then(
        (m) => m.EvaluationPresetComponent,
      ),
  },
  {
    path: ':presetId',
    loadComponent: () =>
      import('./preset-view.component').then((m) => m.PresetViewComponent),
  },
];
