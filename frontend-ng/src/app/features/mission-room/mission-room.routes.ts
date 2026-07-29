import { inject } from '@angular/core';
import { Router, Routes, type CanMatchFn } from '@angular/router';
import { WorkspaceService } from '@app/core/workspace.service';
import { missionRoomExtensionState } from './mission-room.extension';

export const specializedMissionRoomRouteGuard: CanMatchFn = () => {
  const state = missionRoomExtensionState(inject(WorkspaceService).current());
  return state.enabled && !state.genericProvider
    ? true
    : inject(Router).parseUrl('/hypervisor/mission-room/cockpit');
};

/**
 * Feature-local routes for the Mission Room workspace extension.
 *
 * The parent route remains `/hypervisor/mission-room`, so every public URL is
 * identical to the pre-extraction route table.
 */
export const missionRoomRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./mission-room-extension-host.component').then(
        (m) => m.MissionRoomExtensionHostComponent,
      ),
    children: [
      { path: '', redirectTo: 'cockpit', pathMatch: 'full' },
      {
        path: 'securite/monitor',
        canMatch: [specializedMissionRoomRouteGuard],
        loadComponent: () =>
          import('./security-monitor.component').then((m) => m.SecurityMonitorComponent),
      },
      {
        path: 'veille-sociale',
        canMatch: [specializedMissionRoomRouteGuard],
        loadComponent: () =>
          import('./social-pulse-page.component').then((m) => m.SocialPulsePageComponent),
      },
      {
        path: 'agenda/meeting/:event_id',
        canMatch: [specializedMissionRoomRouteGuard],
        loadComponent: () =>
          import('./vp-meeting.component').then((m) => m.VpMeetingComponent),
      },
      {
        path: ':view',
        loadComponent: () =>
          import('./mission-room-provider-host.component').then(
            (m) => m.MissionRoomProviderHostComponent,
          ),
      },
    ],
  },
];
