import { inject } from '@angular/core';
import { Router, type Routes } from '@angular/router';
import { observabilityFacetRedirectUrl } from './observability-facet-redirect';

function facetRedirect(facet: 'quality' | 'performance' | 'traces') {
  return ({ queryParams }: { queryParams: Record<string, string> }) => {
    const target = observabilityFacetRedirectUrl(facet, queryParams);
    return inject(Router).createUrlTree([target.path], {
      queryParams: target.queryParams,
    });
  };
}

/** Facets live in `?facet=` on the shell. Legacy child paths redirect and keep query params. */
export const observabilityRoutes: Routes = [
  { path: 'quality', redirectTo: facetRedirect('quality') },
  { path: 'performance', redirectTo: facetRedirect('performance') },
  { path: 'traces', redirectTo: facetRedirect('traces') },
  {
    path: '',
    loadComponent: () =>
      import('./observability-shell.component').then((m) => m.ObservabilityShellComponent),
  },
];
