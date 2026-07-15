import { Routes } from '@angular/router';

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
        loadComponent: () =>
          import('./security-monitor.component').then((m) => m.SecurityMonitorComponent),
      },
      {
        path: 'veille-sociale',
        loadComponent: () =>
          import('./social-pulse-page.component').then((m) => m.SocialPulsePageComponent),
      },
      {
        path: 'agenda/meeting/:event_id',
        loadComponent: () =>
          import('./vp-meeting.component').then((m) => m.VpMeetingComponent),
      },
      {
        path: ':view',
        loadComponent: () =>
          import('./mission-room.component').then((m) => m.MissionRoomComponent),
      },
    ],
  },
];
