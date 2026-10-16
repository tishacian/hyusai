import { Injectable, inject } from '@angular/core';
import { WorkspaceFetchService } from '@app/core/workspace-fetch.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { AuthStore } from '@app/store/auth.store';
import { ActivityApiError } from '../observability/activities/activity-api.service';
import { followActivityStream, type StreamOptions } from '../observability/activities/activity-stream';
import type { RunExecutionView } from './run-execution.models';
@Injectable({ providedIn: 'root' })
export class RunExecutionApiService {
  private readonly transport = inject(WorkspaceFetchService);
  private readonly workspace = inject(WorkspaceService);
  private readonly auth = inject(AuthStore);
  async read(runId: string, filters: { node_id?: string; activity_id?: string; offset?: number }, signal: AbortSignal): Promise<RunExecutionView> {
    const scope = this.workspace.captureRequestScope(); const principal = this.auth.captureRequestScope();
    const query = new URLSearchParams({ limit: '50' });
    Object.entries(filters).forEach(([key, value]) => { if (value != null && value !== '') query.set(key, String(value)); });
    const response = await this.transport.fetch(`/api/v1/runs/${encodeURIComponent(runId)}/execution-view?${query}`, { signal, workspaceSlug: scope.workspaceSlug, cache: 'no-store' });
    if (signal.aborted || !this.workspace.isRequestScopeCurrent(scope) || !this.auth.isRequestScopeCurrent(principal)) throw new DOMException('Aborted', 'AbortError');
    if (!response.ok) throw new ActivityApiError(response.status, 'EXECUTION_VIEW_UNAVAILABLE');
    const value: RunExecutionView = await response.json();
    if (signal.aborted || !this.workspace.isRequestScopeCurrent(scope) || !this.auth.isRequestScopeCurrent(principal)) throw new DOMException('Aborted', 'AbortError');
    if (value.schema_version !== 1 || value.run.id !== runId) throw new Error('EXECUTION_VIEW_VERSION');
    return value;
  }
  follow(runId: string, options: Omit<StreamOptions, 'url' | 'fetch'>): Promise<void> {
    const scope = this.workspace.captureRequestScope(); const principal = this.auth.captureRequestScope();
    return followActivityStream({ ...options, url: `/api/v1/observability/activity-events/stream?${new URLSearchParams({ run_id: runId, subtree: 'true' })}`,
      fetch: (url, init) => this.transport.fetch(url, { ...init, workspaceSlug: scope.workspaceSlug }),
      frame: frame => { if (this.workspace.isRequestScopeCurrent(scope) && this.auth.isRequestScopeCurrent(principal)) options.frame(frame); },
      state: state => { if (this.workspace.isRequestScopeCurrent(scope) && this.auth.isRequestScopeCurrent(principal)) options.state(state); },
    });
  }
}
