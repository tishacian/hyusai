import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, catchError, of, shareReplay, tap } from 'rxjs';

import { ApiService } from './api.service';

export type Persona = 'builder' | 'operator' | 'executive';
export type HelpCategory = 'action' | 'metric' | 'control' | 'navigation' | 'status' | 'concept';

export interface PersonaCopy {
  summary: string;
  user_story: string;
  prerequisites: string[];
  related_actions: string[];
}

export interface HelpContent {
  id: string;
  title: string;
  category: HelpCategory;
  by_persona: Partial<Record<Persona, PersonaCopy>>;
  learn_more?: string | null;
}

export interface HelpContentIndex {
  version: string;
  personas: Persona[];
  items: HelpContent[];
}

const PERSONA_STORAGE_KEY = 'agentium.persona';
const DEFAULT_PERSONA: Persona = 'operator';

/**
 * HelpService — caches the persona-aware help registry served by
 * `/api/v1/help-content` and resolves copy for a given id × persona.
 *
 * Any UI element that accepts a help handle (Outcome card, Balance
 * sheet KPI, Steering lever, Builder step, etc.) can consume this
 * service via the `<ck-help>` component without having to manage
 * its own state.
 */
@Injectable({ providedIn: 'root' })
export class HelpService {
  private readonly api = inject(ApiService);

  private _index$: Observable<HelpContentIndex | null> | null = null;

  readonly persona = signal<Persona>(this.readStoredPersona());
  readonly personaLabel = computed(() => this.personaLabelOf(this.persona()));

  /** Lazily loads (and caches) the help index from the backend. */
  load(): Observable<HelpContentIndex | null> {
    if (!this._index$) {
      this._index$ = this.api
        .get<HelpContentIndex>('/help-content')
        .pipe(
          catchError(() => of(null)),
          shareReplay(1),
        );
    }
    return this._index$;
  }

  /** Force-refresh from the backend (used by the content reload endpoint). */
  reload(): Observable<HelpContentIndex | null> {
    this._index$ = null;
    return this.load().pipe(tap(() => undefined));
  }

  setPersona(p: Persona): void {
    this.persona.set(p);
    try {
      localStorage.setItem(PERSONA_STORAGE_KEY, p);
    } catch {
      // Ignore private-mode errors.
    }
  }

  /** Find an entry in the already-loaded index (returns null if not loaded yet). */
  find(index: HelpContentIndex | null, id: string): HelpContent | null {
    if (!index) return null;
    return index.items.find((item) => item.id === id) ?? null;
  }

  /** Resolve the copy for a given id × persona. Falls back gracefully. */
  resolve(
    index: HelpContentIndex | null,
    id: string,
    persona?: Persona,
  ): { entry: HelpContent; copy: PersonaCopy; persona: Persona } | null {
    const entry = this.find(index, id);
    if (!entry) return null;
    const p = persona ?? this.persona();
    const copy =
      entry.by_persona[p] ??
      entry.by_persona[DEFAULT_PERSONA] ??
      Object.values(entry.by_persona)[0];
    if (!copy) return null;
    const resolvedPersona = (entry.by_persona[p] ? p : DEFAULT_PERSONA) as Persona;
    return { entry, copy, persona: resolvedPersona };
  }

  personaLabelOf(p: Persona): string {
    switch (p) {
      case 'builder':
        return 'Builder';
      case 'operator':
        return 'Operator';
      case 'executive':
        return 'Executive';
    }
  }

  private readStoredPersona(): Persona {
    try {
      const stored = localStorage.getItem(PERSONA_STORAGE_KEY);
      if (stored === 'builder' || stored === 'operator' || stored === 'executive') {
        return stored;
      }
    } catch {
      // Ignore.
    }
    return DEFAULT_PERSONA;
  }
}
