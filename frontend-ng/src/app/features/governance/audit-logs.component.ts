import { Component, inject, signal, OnInit } from '@angular/core';
import { ApiService } from '@app/core/api.service';

@Component({
  selector: 'app-audit-logs',
  standalone: true,
  template: `
    <h1 class="text-2xl font-bold text-gray-900 dark:text-white mb-6">Audit Logs</h1>
    <div class="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden">
      <table class="w-full text-sm">
        <thead class="bg-gray-50 dark:bg-gray-800">
          <tr>
            <th class="px-4 py-3 text-left text-gray-600 dark:text-gray-400 font-medium">Time</th>
            <th class="px-4 py-3 text-left text-gray-600 dark:text-gray-400 font-medium">Event</th>
            <th class="px-4 py-3 text-left text-gray-600 dark:text-gray-400 font-medium">Actor</th>
            <th class="px-4 py-3 text-left text-gray-600 dark:text-gray-400 font-medium">Severity</th>
          </tr>
        </thead>
        <tbody>
          @for (log of logs(); track log.id) {
            <tr class="border-t border-gray-100 dark:border-gray-800">
              <td class="px-4 py-3 text-gray-500 dark:text-gray-400">{{ log.timestamp }}</td>
              <td class="px-4 py-3 text-gray-900 dark:text-white">{{ log.event_type }}</td>
              <td class="px-4 py-3 text-gray-500">{{ log.actor }}</td>
              <td class="px-4 py-3">
                <span class="px-2 py-0.5 text-xs rounded-full"
                  [class]="log.severity === 'error' ? 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400' : 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'">
                  {{ log.severity }}
                </span>
              </td>
            </tr>
          } @empty {
            <tr><td colspan="4" class="px-4 py-8 text-center text-gray-400">No audit logs</td></tr>
          }
        </tbody>
      </table>
    </div>
  `,
})
export class AuditLogsComponent implements OnInit {
  private readonly api = inject(ApiService);
  logs = signal<any[]>([]);

  ngOnInit(): void {
    this.api.get<any[]>('/audit').subscribe({
      next: (data) => this.logs.set(Array.isArray(data) ? data : []),
      error: () => {},
    });
  }
}
