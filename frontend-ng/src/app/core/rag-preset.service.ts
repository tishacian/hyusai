import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from './api.service';
import type { AppSettings } from './settings.service';

/**
 * Canonical scope enum — mirrors the backend `rag_presets.scope`
 * check constraint.
 */
export type RagPresetScope = 'workspace' | 'capability' | 'system';

export interface RagPreset {
  id: string;
  name: string;
  scope: RagPresetScope;
  scope_id: string | null;
  workspace_id: string | null;
  config: AppSettings;
  is_default: boolean;
  created_at: string | null;
  updated_at: string | null;
}

interface PresetEnvelope {
  preset: RagPreset;
}

interface PresetListEnvelope {
  presets: RagPreset[];
}

interface ResolvedEnvelope {
  preset: {
    scope_hint: RagPresetScope;
    config: AppSettings;
  };
}

/**
 * Thin typed client over `/api/v1/presets`.
 *
 * The service keeps a read-only signal cache of the current workspace's
 * presets so list/detail pages can share state without refetching. Writes
 * always go through the backend and refresh the cache optimistically.
 */
@Injectable({ providedIn: 'root' })
export class RagPresetService {
  private readonly api = inject(ApiService);
  private readonly _presets = signal<RagPreset[]>([]);
  readonly presets = this._presets.asReadonly();

  list(scope?: RagPresetScope): Promise<RagPreset[]> {
    const params = scope ? { scope } : undefined;
    return firstValueFrom(
      this.api.get<PresetListEnvelope>('/presets', params),
    ).then((res) => {
      const list = res?.presets ?? [];
      this._presets.set(list);
      return list;
    });
  }

  get(id: string): Promise<RagPreset> {
    return firstValueFrom(
      this.api.get<PresetEnvelope>(`/presets/${id}`),
    ).then((res) => res.preset);
  }

  create(body: {
    name: string;
    scope: RagPresetScope;
    scope_id?: string | null;
    config: AppSettings;
    is_default?: boolean;
  }): Promise<RagPreset> {
    return firstValueFrom(
      this.api.post<PresetEnvelope>('/presets', body),
    ).then((res) => res.preset);
  }

  update(
    id: string,
    patch: {
      name?: string;
      config?: AppSettings;
      config_patch?: Partial<AppSettings>;
      scope_id?: string | null;
    },
  ): Promise<RagPreset> {
    return firstValueFrom(
      this.api.patch<PresetEnvelope>(`/presets/${id}`, patch),
    ).then((res) => res.preset);
  }

  remove(id: string): Promise<void> {
    return firstValueFrom(this.api.delete<void>(`/presets/${id}`)).then(
      () => {},
    );
  }

  setDefault(id: string): Promise<RagPreset> {
    return firstValueFrom(
      this.api.post<PresetEnvelope>(`/presets/${id}/set-default`, {}),
    ).then((res) => res.preset);
  }

  resolve(args: {
    capability_id?: string | null;
    system_id?: string | null;
  } = {}): Promise<ResolvedEnvelope['preset']> {
    const params: Record<string, string> = {};
    if (args.capability_id) params['capability_id'] = args.capability_id;
    if (args.system_id) params['system_id'] = args.system_id;
    return firstValueFrom(
      this.api.get<ResolvedEnvelope>('/presets/resolve', params),
    ).then((res) => res.preset);
  }
}
