import { Injectable, computed, effect, inject, signal } from '@angular/core';
import { Observable, map, of, tap } from 'rxjs';
import { ApiService } from '@app/core/api.service';

export interface SystemAgent {
  id: string;
  name: string;
  description: string;
  status: string;
  rag_mode?: string;
  model?: string;
  template?: string;
  prompt?: string;
  skills?: string[];
  collections?: string[];
  draft?: boolean;
  created_at?: string;
}

const LS_KEY = 'agentium_system_drafts';

@Injectable({ providedIn: 'root' })
export class SystemsStore {
  private readonly api = inject(ApiService);

  private readonly remote = signal<SystemAgent[]>([]);
  private readonly drafts = signal<SystemAgent[]>(this.readDrafts());
  readonly loading = signal<boolean>(true);

  readonly systems = computed<SystemAgent[]>(() => {
    const ids = new Set(this.remote().map((a) => a.id));
    const onlyLocal = this.drafts().filter((d) => !ids.has(d.id));
    return [...this.remote(), ...onlyLocal];
  });

  constructor() {
    effect(() => {
      localStorage.setItem(LS_KEY, JSON.stringify(this.drafts()));
    });
  }

  private readDrafts(): SystemAgent[] {
    try {
      const raw = localStorage.getItem(LS_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }

  load(): Observable<SystemAgent[]> {
    this.loading.set(true);
    return this.api
      .get<{ agents: SystemAgent[] } | SystemAgent[]>('/agents')
      .pipe(
        map((res) => (Array.isArray(res) ? res : res?.agents ?? [])),
        map((list) =>
          list.map((a) => ({
            ...a,
            description: a.description ?? '',
          })),
        ),
        tap((list) => {
          this.remote.set(list);
          this.loading.set(false);
        }),
      );
  }

  findById(id: string): SystemAgent | null {
    return this.systems().find((s) => s.id === id) ?? null;
  }

  getById(id: string): Observable<SystemAgent | null> {
    const local = this.findById(id);
    if (local) return of(local);
    return this.api
      .get<SystemAgent>(`/agents/${id}`)
      .pipe(
        map((a) => ({ ...a, description: a.description ?? '' })),
        tap(() => {}),
      );
  }

  createDraft(input: Partial<SystemAgent> & { name: string }): SystemAgent {
    const slug = input.name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 32);
    const id = `draft-${slug || 'system'}-${Date.now().toString(36)}`;
    const draft: SystemAgent = {
      id,
      name: input.name,
      description: input.description ?? '',
      status: 'draft',
      rag_mode: input.rag_mode ?? 'OmniRAG',
      model: input.model ?? 'gpt-4o-mini',
      template: input.template,
      prompt: input.prompt,
      skills: input.skills ?? [],
      collections: input.collections ?? [],
      draft: true,
      created_at: new Date().toISOString(),
    };
    this.drafts.update((list) => [...list, draft]);
    return draft;
  }

  removeDraft(id: string): void {
    this.drafts.update((list) => list.filter((d) => d.id !== id));
  }
}
