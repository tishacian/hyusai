import { Component, inject, signal, OnInit } from '@angular/core';
import { ApiService } from '@app/core/api.service';

@Component({
  selector: 'app-news-lab',
  standalone: true,
  template: `
    <h1 class="text-2xl font-bold text-gray-900 dark:text-white mb-6">Intelligence Lab</h1>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <!-- Feed sources -->
      <div class="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5">
        <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-3">Feed Sources</h2>
        <div class="space-y-2">
          @for (feed of feeds(); track feed.id) {
            <div class="flex items-center justify-between text-sm">
              <span class="text-gray-700 dark:text-gray-300">{{ feed.name }}</span>
              <span class="text-xs text-gray-500">{{ feed.article_count }} articles</span>
            </div>
          } @empty {
            <p class="text-gray-400 text-sm">No feeds configured</p>
          }
        </div>
      </div>

      <!-- Targets -->
      <div class="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5">
        <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-3">Semantic Targets</h2>
        <div class="space-y-2">
          @for (target of targets(); track target.id) {
            <div class="flex items-center justify-between text-sm">
              <span class="text-gray-700 dark:text-gray-300">{{ target.name }}</span>
              <span class="text-xs text-gray-500">threshold: {{ target.relevance_threshold }}</span>
            </div>
          } @empty {
            <p class="text-gray-400 text-sm">No targets configured</p>
          }
        </div>
      </div>
    </div>
  `,
})
export class NewsLabComponent implements OnInit {
  private readonly api = inject(ApiService);
  feeds = signal<any[]>([]);
  targets = signal<any[]>([]);

  ngOnInit(): void {
    this.api.get<any[]>('/intelligence/feeds').subscribe({
      next: (data) => this.feeds.set(data ?? []),
      error: () => {},
    });
    this.api.get<any[]>('/intelligence/targets').subscribe({
      next: (data) => this.targets.set(data ?? []),
      error: () => {},
    });
  }
}
