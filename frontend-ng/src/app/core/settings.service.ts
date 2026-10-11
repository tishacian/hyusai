import { Injectable, computed, inject, signal } from '@angular/core';
import { ApiService } from './api.service';
import { WorkspaceService } from './workspace.service';
import {
  readWorkspaceLocalJson,
  writeWorkspaceLocalJson,
} from './workspace-local-storage';

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
  private readonly workspace = inject(WorkspaceService);

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

  constructor() {
    this.workspace.registerContextReset((transition) => {
      this._settings.set(this.readLocal(transition.nextSlug));
    });
  }

  /** Fire-and-forget fetch; backend is authoritative when reachable. */
  refresh(): void {
    const scope = this.workspace.captureRequestScope();
    this.api.get<{ settings: AppSettings }>('/settings').subscribe({
      next: (res) => {
        if (res?.settings && this.workspace.isRequestScopeCurrent(scope)) {
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

  private readLocal(slug = this.workspace.currentSlug()): AppSettings {
    const cached = readWorkspaceLocalJson<AppSettings>({
      storage: localStorage,
      baseKey: LS_KEY,
      workspaceSlug: slug,
      knownWorkspaceSlugs: this.workspace.workspaces().map((workspace) => workspace.slug),
      isValue: isSettingsValue,
      // UI preferences are non-sensitive and can be retained when a sole
      // known workspace makes their origin unambiguous enough for UX.
      allowUntaggedLegacyForSoleWorkspace: true,
    });
    return cached ? { ...DEFAULT_SETTINGS, ...cached } : { ...DEFAULT_SETTINGS };
  }

  private writeLocal(s: AppSettings): void {
    writeWorkspaceLocalJson(localStorage, LS_KEY, this.workspace.currentSlug(), s);
  }
}

function isSettingsValue(value: unknown): value is AppSettings {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}
