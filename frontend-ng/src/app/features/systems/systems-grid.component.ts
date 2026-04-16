import { Component, inject, signal, OnInit } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ApiService } from '@app/core/api.service';

interface SystemAgent {
  id: string;
  name: string;
  description: string;
  status: string;
}

@Component({
  selector: 'app-systems-grid',
  standalone: true,
  imports: [RouterLink],
  template: `
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-2xl font-bold text-gray-900 dark:text-white">Systems</h1>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      @for (agent of agents(); track agent.id) {
        <a
          [routerLink]="[agent.id]"
          class="block p-5 bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 hover:border-brand-400 dark:hover:border-brand-500 transition shadow-sm hover:shadow-md"
        >
          <div class="flex items-start justify-between">
            <div>
              <h3 class="font-semibold text-gray-900 dark:text-white">{{ agent.name }}</h3>
              <p class="text-sm text-gray-500 dark:text-gray-400 mt-1 line-clamp-2">{{ agent.description }}</p>
            </div>
            <span
              class="shrink-0 w-2.5 h-2.5 rounded-full mt-1.5"
              [class.bg-green-400]="agent.status === 'active'"
              [class.bg-gray-400]="agent.status !== 'active'"
            ></span>
          </div>
        </a>
      } @empty {
        <div class="col-span-full text-center py-12 text-gray-500 dark:text-gray-400">
          <p class="text-lg">No systems configured yet</p>
          <p class="text-sm mt-1">Create your first AI agent system to get started.</p>
        </div>
      }
    </div>
  `,
})
export class SystemsGridComponent implements OnInit {
  private readonly api = inject(ApiService);
  agents = signal<SystemAgent[]>([]);

  ngOnInit(): void {
    this.api.get<{ agents: SystemAgent[] } | SystemAgent[]>('/agents').subscribe({
      next: (res) => {
        const list = Array.isArray(res) ? res : (res?.agents ?? []);
        this.agents.set(list.map((a) => ({ ...a, description: a.description ?? '' })));
      },
      error: () => this.agents.set([]),
    });
  }
}
