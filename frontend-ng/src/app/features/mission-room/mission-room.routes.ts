import { inject } from '@angular/core';
import { Router, Routes, type RedirectFunction } from '@angular/router';
import { missionRoomImpactTarget } from './mission-room-redirects';

function impactTree(
  queryParams: Readonly<Record<string, string>> = {},
): ReturnType<Router['createUrlTree']> {
  return inject(Router).createUrlTree(['/hypervisor'], { queryParams: { ...queryParams } });
}

function redirectImpact(queryParams: Record<string, string> = {}): RedirectFunction {
  return () => impactTree(queryParams);
}

const redirectMeeting: RedirectFunction = (route) => {
  const eventId = route.params['event_id'];
  return impactTree({
    view: 'reunion',
    ...(typeof eventId === 'string' && eventId ? { eventId } : {}),
  });
};

const redirectLegacyView: RedirectFunction = (route) => {
  const view = route.params['view'];
  const target = missionRoomImpactTarget(
    typeof view === 'string' ? `/hypervisor/mission-room/${view}` : '/hypervisor/mission-room',
  );
  return impactTree(target?.queryParams ?? {});
};

/** `/recherche` → Impact + open the command palette (fiche proposition). */
const redirectRecherche: RedirectFunction = () => {
  if (typeof window !== 'undefined') {
    queueMicrotask(() => {
      window.dispatchEvent(new CustomEvent('ck:command-palette:open'));
    });
  }
  return impactTree();
};

/**
 * Feature-local routes for the Mission Room workspace extension.
 *
 * L13a: every public URL redirects into Impact (`/hypervisor`) with replaceUrl
 * semantics (Angular route redirects replace the history entry). Components
 * stay in the folder for L13b data reuse; they are no longer activated here.
 */
export const missionRoomRoutes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: redirectImpact({ theme: 'presentation' }) },
  { path: 'securite/monitor', redirectTo: redirectImpact({ view: 'securite' }) },
  { path: 'veille-sociale', redirectTo: redirectImpact({ view: 'veille' }) },
  { path: 'agenda/meeting/:event_id', redirectTo: redirectMeeting },
  { path: 'recherche', redirectTo: redirectRecherche },
  { path: ':view', redirectTo: redirectLegacyView },
];