import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { WorkspaceService } from '@app/core/workspace.service';
import { GenericMissionRoomComponent } from './generic-mission-room.component';
import { MissionRoomComponent } from './mission-room.component';
import { missionRoomExtensionState } from './mission-room.extension';

/** Selects exactly one installed provider without falling back across apps. */
@Component({
  selector: 'app-mission-room-provider-host',
  standalone: true,
  imports: [GenericMissionRoomComponent, MissionRoomComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (state().genericProvider) {
      <app-generic-mission-room />
    } @else if (state().enabled) {
      <app-mission-room />
    } @else {
      <section class="provider-unavailable" role="alert">
        <h1>Mission Room unavailable</h1>
        <p>The installed application has no authorized runtime provider.</p>
      </section>
    }
  `,
  styles: [`
    .provider-unavailable { min-height: 100vh; padding: 48px; background: #071018; color: #e9f0f4; }
    .provider-unavailable h1 { margin: 0 0 10px; }
    .provider-unavailable p { color: #9fb0bb; }
  `],
})
export class MissionRoomProviderHostComponent {
  private readonly workspace = inject(WorkspaceService);
  readonly state = computed(() => missionRoomExtensionState(this.workspace.current()));
}
