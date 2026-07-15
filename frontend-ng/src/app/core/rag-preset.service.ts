import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from './api.service';
import type { AppSettings } from './settings.service';
import {
  WorkspaceRequestInvalidatedError,
  WorkspaceService,
  type WorkspaceRequestScope,
} from './workspace.service';

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
  private readonly workspace = inject(WorkspaceService);
  private readonly _presets = signal<RagPreset[]>([]);
  readonly presets = this._presets.asReadonly();

  constructor() {
    this.workspace.registerContextReset(() => this._presets.set([]));
  }

  list(scope?: RagPresetScope): Promise<RagPreset[]> {
    const requestScope = this.workspace.captureRequestScope();
    const params = scope ? { scope } : undefined;
    return firstValueFrom(
      this.api.get<PresetListEnvelope>('/presets', params, {
        workspaceSlug: requestScope.workspaceSlug,
      }),
    ).then((res) => {
      const list = res?.presets ?? [];
      this.assertCurrent(requestScope);
      this._presets.set(list);
      return list;
    });
  }

  get(id: string): Promise<RagPreset> {
    const scope = this.workspace.captureRequestScope();
    return firstValueFrom(
      this.api.get<PresetEnvelope>(`/presets/${id}`, undefined, { workspaceSlug: scope.workspaceSlug }),
    ).then((res) => {
      this.assertCurrent(scope);
      return res.preset;
    });
  }

  create(body: {
    name: string;
    scope: RagPresetScope;
    scope_id?: string | null;
    config: AppSettings;
    is_default?: boolean;
  }): Promise<RagPreset> {
    const scope = this.workspace.captureRequestScope();
    return firstValueFrom(
      this.api.post<PresetEnvelope>('/presets', body, { workspaceSlug: scope.workspaceSlug }),
    ).then((res) => {
      this.assertCurrent(scope);
      return res.preset;
    });
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
    const scope = this.workspace.captureRequestScope();
    return firstValueFrom(
      this.api.patch<PresetEnvelope>(`/presets/${id}`, patch, { workspaceSlug: scope.workspaceSlug }),
    ).then((res) => {
      this.assertCurrent(scope);
      return res.preset;
    });
  }

  remove(id: string): Promise<void> {
    const scope = this.workspace.captureRequestScope();
    return firstValueFrom(this.api.delete<void>(`/presets/${id}`, {
      workspaceSlug: scope.workspaceSlug,
    })).then(() => {
      this.assertCurrent(scope);
    });
  }

  setDefault(id: string): Promise<RagPreset> {
    const scope = this.workspace.captureRequestScope();
    return firstValueFrom(
      this.api.post<PresetEnvelope>(`/presets/${id}/set-default`, {}, { workspaceSlug: scope.workspaceSlug }),
    ).then((res) => {
      this.assertCurrent(scope);
      return res.preset;
    });
  }

  resolve(args: {
    capability_id?: string | null;
    system_id?: string | null;
  } = {}): Promise<ResolvedEnvelope['preset']> {
    const scope = this.workspace.captureRequestScope();
    const params: Record<string, string> = {};
    if (args.capability_id) params['capability_id'] = args.capability_id;
    if (args.system_id) params['system_id'] = args.system_id;
    return firstValueFrom(
      this.api.get<ResolvedEnvelope>('/presets/resolve', params, { workspaceSlug: scope.workspaceSlug }),
    ).then((res) => {
      this.assertCurrent(scope);
      return res.preset;
    });
  }

  private assertCurrent(scope: WorkspaceRequestScope): void {
    if (!this.workspace.isRequestScopeCurrent(scope)) {
      throw new WorkspaceRequestInvalidatedError();
    }
  }
}
