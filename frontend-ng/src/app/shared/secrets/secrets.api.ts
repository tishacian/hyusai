import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from '@app/core/api.service';

/** `/api/v1/secrets` — metadata only; a value goes up once and never comes back. */

export type SecretScope = 'platform' | 'workspace' | 'system';
export type SecretKind = 'api_key' | 'token' | 'password' | 'oauth_client' | 'generic';
export const SECRET_KINDS: readonly SecretKind[] = ['api_key', 'token', 'password', 'oauth_client', 'generic'];

export interface SecretVersionMeta {
  version: number;
  created_by: string | null;
  created_at: string;
  destroyed_at: string | null;
}

export interface SecretMeta {
  id: string;
  ref: string;
  scope: SecretScope;
  workspace_id: string | null;
  system_id: string | null;
  name: string;
  kind: SecretKind;
  backend: string;
  current_version: number;
  description: string | null;
  metadata: Record<string, unknown>;
  expires_at: string | null;
  rotated_at: string | null;
  created_by: string | null;
  created_at: string;
  disabled_at: string | null;
  value_set: boolean;
  versions: SecretVersionMeta[];
}

export interface SecretConsumerMeta {
  kind: string | null;
  id: string | null;
  system_id: string | null;
  node_id: string | null;
  last_resolved_at: string;
  last_version: number | null;
  count: number;
}

export interface SecretCreate {
  name: string;
  value: string;
  kind: SecretKind;
  scope?: SecretScope;
  system_id?: string;
  description?: string;
}

export interface SecretListQuery {
  scope?: SecretScope;
  system_id?: string;
  include_disabled?: boolean;
}

type Options = { workspaceSlug?: string | null };

/** Same rule as the backend: lowercase slug, 120 characters at most. */
export const SECRET_NAME_PATTERN = /^[a-z0-9][a-z0-9._-]{0,119}$/;

export function isValidSecretName(name: string): boolean {
  return SECRET_NAME_PATTERN.test(name);
}

/** Stable backend code (`SECRET_NAME_TAKEN`, `WORKSPACE_PERMISSION_DENIED`…) from an HTTP error. */
export function secretErrorCode(error: unknown): string | null {
  const detail = (error as { error?: { detail?: unknown } } | null)?.error?.detail;
  if (detail && typeof detail === 'object' && typeof (detail as { code?: unknown }).code === 'string') {
    return (detail as { code: string }).code;
  }
  return null;
}

@Injectable({ providedIn: 'root' })
export class SecretsApi {
  private readonly api = inject(ApiService);

  list(query: SecretListQuery = {}, options?: Options): Observable<{ secrets: SecretMeta[]; can_manage_platform: boolean }> {
    const params: Record<string, string> = {};
    if (query.scope) params['scope'] = query.scope;
    if (query.system_id) params['system_id'] = query.system_id;
    if (query.include_disabled) params['include_disabled'] = 'true';
    return this.api.get('/secrets', params, options);
  }

  get(id: string, options?: Options): Observable<SecretMeta> {
    return this.api.get(`/secrets/${encodeURIComponent(id)}`, undefined, options);
  }

  consumers(id: string, options?: Options): Observable<{ consumers: SecretConsumerMeta[] }> {
    return this.api.get(`/secrets/${encodeURIComponent(id)}/consumers`, undefined, options);
  }

  create(body: SecretCreate, options?: Options): Observable<SecretMeta> {
    return this.api.post('/secrets', body, options);
  }

  rotate(id: string, value: string, options?: Options): Observable<SecretMeta> {
    return this.api.post(`/secrets/${encodeURIComponent(id)}/rotate`, { value }, options);
  }

  disable(id: string, options?: Options): Observable<SecretMeta> {
    return this.api.post(`/secrets/${encodeURIComponent(id)}/disable`, {}, options);
  }

  destroy(id: string, version?: number, options?: Options): Observable<SecretMeta> {
    const query = version ? `?version=${version}` : '';
    return this.api.delete(`/secrets/${encodeURIComponent(id)}${query}`, options);
  }
}
