import { Component, inject, signal, OnInit } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { MatTabsModule } from '@angular/material/tabs';
import { ApiService } from '@app/core/api.service';

@Component({
  selector: 'app-system-view',
  standalone: true,
  imports: [MatTabsModule],
  template: `
    <div class="mb-4">
      <h1 class="text-2xl font-bold text-gray-900 dark:text-white">{{ agentName() }}</h1>
    </div>

    <mat-tab-group animationDuration="200ms" class="agent-tabs">
      <mat-tab label="Chat">
        @defer (on viewport) {
          <div class="py-4">
            <app-chat-panel [systemId]="systemId" />
          </div>
        } @placeholder {
          <div class="py-8 text-center text-gray-400">Loading chat...</div>
        }
      </mat-tab>
      <mat-tab label="Overview">
        <div class="py-4 text-gray-500 dark:text-gray-400">
          System overview and configuration will appear here.
        </div>
      </mat-tab>
      <mat-tab label="Settings">
        <div class="py-4 text-gray-500 dark:text-gray-400">
          System settings will appear here.
        </div>
      </mat-tab>
    </mat-tab-group>
  `,
})
export class SystemViewComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly api = inject(ApiService);

  systemId = '';
  agentName = signal('System');

  ngOnInit(): void {
    this.systemId = this.route.snapshot.paramMap.get('systemId') ?? '';
    this.api.get<{ id: string; name: string }>(`/agents/${this.systemId}`).subscribe({
      next: (agent) => this.agentName.set(agent.name),
      error: () => {},
    });
  }
}
