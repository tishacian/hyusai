import { Injectable, inject } from '@angular/core';
import { WorkspaceFetchService } from '@app/core/workspace-fetch.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { AuthStore } from '@app/store/auth.store';
import { activityQuery, type ActivityCommand, type ActivityDetail, type ActivityEventPage, type ActivityFeatures, type ActivityFilters, type ActivityPage, type PlatformOverview } from './activity.models';
import { followActivityStream, type StreamOptions } from './activity-stream';

export class ActivityApiError extends Error {
  constructor(readonly status: number, readonly code: string) { super(code); }
}

@Injectable({ providedIn: 'root' })
export class ActivityApiService {
  private readonly transport = inject(WorkspaceFetchService);
  private readonly workspace = inject(WorkspaceService);
  private readonly auth = inject(AuthStore);
  private readonly base = '/api/v1/observability';

  private featureCache?: { workspace: ReturnType<WorkspaceService['captureRequestScope']>; principal: ReturnType<InstanceType<typeof AuthStore>['captureRequestScope']>; promise: Promise<ActivityFeatures> };
  async features(signal?: AbortSignal): Promise<ActivityFeatures> {
    const cached = this.featureCache;
    if (!cached || !this.workspace.isRequestScopeCurrent(cached.workspace) || !this.auth.isRequestScopeCurrent(cached.principal)) {
      const entry = { workspace: this.workspace.captureRequestScope(), principal: this.auth.captureRequestScope(), promise: this.json<ActivityFeatures>('/activities/features', {}) };
      this.featureCache = entry;
      entry.promise.catch(() => { if (this.featureCache === entry) this.featureCache = undefined; });
    }
    const features = await this.featureCache!.promise;
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    return features;
  }
  list(filters: ActivityFilters, signal?: AbortSignal): Promise<ActivityPage> { return this.json(`/activities?${activityQuery(filters)}`, { signal }); }
  detail(id: string, signal?: AbortSignal): Promise<ActivityDetail> { return this.json(`/activities/${encodeURIComponent(id)}`, { signal }); }
  events(id: string, cursor = '', signal?: AbortSignal): Promise<ActivityEventPage> {
    return this.json(`/activity-events?${new URLSearchParams({ activity_id: id, cursor, limit: '100' })}`, { signal });
  }
  platform(signal?: AbortSignal): Promise<PlatformOverview> { return this.json('/platform-overview', { signal }); }
  command(id: string, version: number, idempotencyKey: string, signal?: AbortSignal): Promise<ActivityCommand> {
    return this.json(`/activities/${encodeURIComponent(id)}/commands`, {
      method: 'POST', signal, headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'cancel', expected_version: version, idempotency_key: idempotencyKey }),
    });
  }
  follow(options: Omit<StreamOptions, 'url' | 'fetch'>): Promise<void> {
    const scope = this.workspace.captureRequestScope();
    const principal = this.auth.captureRequestScope();
    return followActivityStream({
      ...options, url: `${this.base}/activity-events/stream`,
      fetch: (url, init) => this.transport.fetch(url, { ...init, workspaceSlug: scope.workspaceSlug }),
      frame: frame => { if (this.workspace.isRequestScopeCurrent(scope) && this.auth.isRequestScopeCurrent(principal)) options.frame(frame); },
      state: state => { if (this.workspace.isRequestScopeCurrent(scope) && this.auth.isRequestScopeCurrent(principal)) options.state(state); },
    });
  }

  private async json<T>(path: string, init: RequestInit): Promise<T> {
    const scope = this.workspace.captureRequestScope();
    const principal = this.auth.captureRequestScope();
    const response = await this.transport.fetch(this.base + path, { ...init, workspaceSlug: scope.workspaceSlug, cache: 'no-store' });
    if (!this.workspace.isRequestScopeCurrent(scope) || !this.auth.isRequestScopeCurrent(principal) || init.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      const detail = body?.detail;
      throw new ActivityApiError(response.status, typeof detail === 'string' ? detail : detail?.code || 'ACTIVITY_REQUEST_FAILED');
    }
    const value = await response.json();
    if (!this.workspace.isRequestScopeCurrent(scope) || !this.auth.isRequestScopeCurrent(principal) || init.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    return value as T;
  }
}
