import { Injectable, inject, signal, computed, effect } from '@angular/core';
import { HttpClient } from '@angular/common/http';

export interface WorkspaceInfo {
  id: string;
  name: string;
  slug: string;
  role: string;
}

const WS_KEY = 'agentium_workspace_slug';

@Injectable({ providedIn: 'root' })
export class WorkspaceService {
  private readonly http = inject(HttpClient);

  readonly workspaces = signal<WorkspaceInfo[]>([]);
  readonly currentSlug = signal<string | null>(localStorage.getItem(WS_KEY));
  readonly current = computed(() =>
    this.workspaces().find((w) => w.slug === this.currentSlug()) ?? null
  );

  constructor() {
    effect(() => {
      const slug = this.currentSlug();
      if (slug) {
        localStorage.setItem(WS_KEY, slug);
      } else {
        localStorage.removeItem(WS_KEY);
      }
    });
  }

  loadWorkspaces(): void {
    this.http
      .get<WorkspaceInfo[]>('/api/v1/auth/workspaces')
      .subscribe((list) => {
        this.workspaces.set(list);
        if (list.length === 1 && !this.currentSlug()) {
          this.currentSlug.set(list[0].slug);
        }
        if (this.currentSlug() && !list.find((w) => w.slug === this.currentSlug())) {
          this.currentSlug.set(list[0]?.slug ?? null);
        }
      });
  }

  switchWorkspace(slug: string): void {
    this.currentSlug.set(slug);
  }
}
