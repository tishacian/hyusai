import { Injectable, computed, inject, signal } from '@angular/core';
import { ApiService } from './api.service';

/**
 * Canonical shape of the settings payload exposed by `GET /api/v1/settings`.
 * Keys are the ones the backend actively persists today; anything unknown is
 * preserved on update so we don't drop fields we don't yet surface.
 */
export interface AppSettings {
  // LLM
  defaultModel?: string;
  defaultProvider?: string;
  temperature?: number;
  maxTokens?: number;
  // Retrieval / RAG
  ragPipelineMode?: 'auto' | 'naive' | 'hybrid' | 'hah' | 'chah';
  ragTopK?: number;
  ragCandidatePoolK?: number;
  ragSynthesisK?: number;
  ragSourceDisplayK?: number;
  ragSimilarityThreshold?: number;
  ragUseHybridSearch?: boolean;
  ragVectorWeight?: number;
  ragBM25Weight?: number;
  ragChunkSize?: number;
  ragChunkOverlap?: number;
  // UX
  enableStreaming?: boolean;
  showReasoningTraces?: boolean;
  showSources?: boolean;
  autoExpandReasoning?: boolean;
  [key: string]: unknown;
}

const LS_KEY = 'agentium:settings:v1';

const DEFAULT_SETTINGS: AppSettings = {
  defaultModel: 'gpt-5',
  defaultProvider: 'openai',
  temperature: 0.3,
  maxTokens: 2000,
  ragPipelineMode: 'auto',
  ragTopK: 5,
  ragCandidatePoolK: 48,
  ragSynthesisK: 12,
  ragSourceDisplayK: 8,
  ragSimilarityThreshold: 0.35,
  ragUseHybridSearch: true,
  ragVectorWeight: 0.7,
  ragBM25Weight: 0.3,
  ragChunkSize: 1000,
  ragChunkOverlap: 200,
  enableStreaming: true,
  showReasoningTraces: true,
  showSources: true,
  autoExpandReasoning: false,
};

@Injectable({ providedIn: 'root' })
export class SettingsService {
  private readonly api = inject(ApiService);

  private readonly _settings = signal<AppSettings>(this.readLocal());
  readonly settings = this._settings.asReadonly();

  readonly ragPipelineMode = computed(() => this._settings().ragPipelineMode ?? 'auto');
  readonly ragTopK = computed(() => this._settings().ragTopK ?? 5);
  readonly ragSimilarityThreshold = computed(
    () => this._settings().ragSimilarityThreshold ?? 0.35,
  );
  readonly temperature = computed(() => this._settings().temperature ?? 0.3);
  readonly maxTokens = computed(() => this._settings().maxTokens ?? 2000);
  readonly showReasoningTraces = computed(() => this._settings().showReasoningTraces ?? true);

  /** Fire-and-forget fetch; backend is authoritative when reachable. */
  refresh(): void {
    this.api.get<{ settings: AppSettings }>('/settings').subscribe({
      next: (res) => {
        if (res?.settings) {
          const merged = { ...DEFAULT_SETTINGS, ...res.settings };
          this._settings.set(merged);
          this.writeLocal(merged);
        }
      },
      error: () => {
        // Keep whatever we cached locally; no toast, this is best-effort.
      },
    });
  }

  /** Optimistic partial update: local cache first, then backend persist. */
  update(patch: Partial<AppSettings>): void {
    const next = { ...this._settings(), ...patch };
    this._settings.set(next);
    this.writeLocal(next);
    this.api.post('/settings', { settings: patch }).subscribe({ error: () => {} });
  }

  private readLocal(): AppSettings {
    try {
      const raw = localStorage.getItem(LS_KEY);
      if (!raw) return { ...DEFAULT_SETTINGS };
      return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) };
    } catch {
      return { ...DEFAULT_SETTINGS };
    }
  }

  private writeLocal(s: AppSettings): void {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify(s));
    } catch {
      /* quota exceeded — ignore */
    }
  }
}
