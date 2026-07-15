import { Injectable, computed, inject, signal } from '@angular/core';
import { EMPTY, Observable, catchError, filter, of, shareReplay, tap } from 'rxjs';

import { ApiService } from './api.service';
import { WorkspaceService } from './workspace.service';

export type Persona = 'builder' | 'operator' | 'executive';
export type HelpCategory = 'action' | 'metric' | 'control' | 'navigation' | 'status' | 'concept';
export type Language = 'en' | 'fr';

/**
 * Localized string map keyed by language code.
 *
 * The backend ships every textual field as `{ en: "…", fr: "…" }`.
 * Legacy plain strings (no locale wrapping) are silently coerced to
 * `{ en: value }` by the backend loader.
 */
export type LocalizedText = Partial<Record<Language, string>>;

export interface PersonaCopy {
  summary: LocalizedText;
  user_story: LocalizedText;
  prerequisites: LocalizedText[];
  related_actions: string[];
}

export interface HelpContent {
  id: string;
  title: LocalizedText;
  category: HelpCategory;
  by_persona: Partial<Record<Persona, PersonaCopy>>;
  learn_more?: string | null;
}

export interface HelpContentIndex {
  version: string;
  personas: Persona[];
  languages: Language[];
  items: HelpContent[];
}

const PERSONA_STORAGE_KEY = 'agentium.persona';
const LANGUAGE_STORAGE_KEY = 'agentium.help.lang';
const DEFAULT_PERSONA: Persona = 'operator';
const DEFAULT_LANGUAGE: Language = 'en';
const FALLBACK_ORDER: Language[] = ['en', 'fr'];

/**
 * HelpService — caches the persona-aware, bilingual help registry
 * served by `/api/v1/help-content` and resolves copy for a given
 * id × persona × language.
 *
 * The app is English-first; French is preserved so francophone
 * operators can stay in their language of choice. Both the persona
 * and the language are user preferences, persisted in localStorage
 * so they travel across sessions.
 */
@Injectable({ providedIn: 'root' })
export class HelpService {
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);

  private _index$: Observable<HelpContentIndex | null> | null = null;

  readonly persona = signal<Persona>(this.readStoredPersona());
  readonly personaLabel = computed(() => this.personaLabelOf(this.persona()));

  readonly language = signal<Language>(this.readStoredLanguage());
  readonly languageLabel = computed(() => this.languageLabelOf(this.language()));

  constructor() {
    // Persona and language are user preferences; only the API index is
    // workspace-bound and must not be replayed into the next tenant.
    this.workspace.registerContextReset(() => {
      this._index$ = null;
    });
  }

  load(): Observable<HelpContentIndex | null> {
    if (!this._index$) {
      const scope = this.workspace.captureRequestScope();
      this._index$ = this.api
        .get<HelpContentIndex>('/help-content', undefined, {
          workspaceSlug: scope.workspaceSlug,
        })
        .pipe(
          filter(() => this.workspace.isRequestScopeCurrent(scope)),
          catchError(() => (
            this.workspace.isRequestScopeCurrent(scope) ? of(null) : EMPTY
          )),
          shareReplay(1),
        );
    }
    return this._index$;
  }

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

  setLanguage(lang: Language): void {
    this.language.set(lang);
    try {
      localStorage.setItem(LANGUAGE_STORAGE_KEY, lang);
    } catch {
      // Ignore private-mode errors.
    }
  }

  /** Pick the best-matching text for the current (or requested) language. */
  pickText(text: LocalizedText | null | undefined, lang?: Language): string {
    if (!text) return '';
    const target = lang ?? this.language();
    if (text[target]) return text[target] ?? '';
    for (const fallback of FALLBACK_ORDER) {
      if (text[fallback]) return text[fallback] ?? '';
    }
    const firstValue = Object.values(text).find((v) => typeof v === 'string' && v.length > 0);
    return typeof firstValue === 'string' ? firstValue : '';
  }

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

  languageLabelOf(lang: Language): string {
    switch (lang) {
      case 'en':
        return 'EN';
      case 'fr':
        return 'FR';
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

  private readStoredLanguage(): Language {
    try {
      const stored = localStorage.getItem(LANGUAGE_STORAGE_KEY);
      if (stored === 'en' || stored === 'fr') {
        return stored;
      }
    } catch {
      // Ignore.
    }
    return DEFAULT_LANGUAGE;
  }
}
