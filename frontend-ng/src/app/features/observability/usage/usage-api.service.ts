import { Injectable, inject } from '@angular/core';
import { WorkspaceFetchService } from '@app/core/workspace-fetch.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { AuthStore } from '@app/store/auth.store';
import type { UsageBudget, UsageBudgetPage, UsageBudgetWrite, UsageCallPage, UsageFilters, UsageReadiness, UsageSeries, UsageSummary, UsageTariff, UsageTariffPage, UsageTariffWrite } from './usage.models';
import { usageQuery } from './usage.vm';

export class UsageApiError extends Error {
  constructor(readonly status: number, readonly code: string) { super(code); }
}
@Injectable({ providedIn: 'root' })
export class UsageApiService {
  private readonly transport = inject(WorkspaceFetchService);
  private readonly workspace = inject(WorkspaceService);
  private readonly auth = inject(AuthStore);
  summary(filters: UsageFilters, signal?: AbortSignal): Promise<UsageSummary> { return this.json(`/summary?${usageQuery(filters)}`, { signal }); }
  series(filters: UsageFilters, signal?: AbortSignal): Promise<UsageSeries> { return this.json(`/series?${usageQuery(filters)}`, { signal }); }
  calls(filters: UsageFilters, signal?: AbortSignal): Promise<UsageCallPage> { return this.json(`/calls?${usageQuery(filters)}`, { signal }); }
  budgets(signal?: AbortSignal): Promise<UsageBudgetPage> { return this.json('/budgets', { signal }); }
  async tariffs(signal?: AbortSignal): Promise<UsageTariffPage> {
    const result = await this.json<Omit<UsageTariffPage, 'items'> & { items: Array<UsageTariff & { rates?: Partial<UsageTariff> }> }>('/tariffs', { signal });
    return { ...result, items: result.items.map(item => ({ ...item, ...item.rates })) };
  }
  readiness(signal?: AbortSignal): Promise<UsageReadiness> { return this.json('/readiness', { signal }); }
  saveBudget(body: UsageBudgetWrite): Promise<UsageBudget> { return this.json('/budgets', { method: 'POST', body: JSON.stringify(body) }); }
  saveTariff(body: UsageTariffWrite): Promise<UsageTariff> { return this.json('/tariffs', { method: 'POST', body: JSON.stringify(body) }); }
  private async json<T>(path: string, init: RequestInit): Promise<T> {
    const scope = this.workspace.captureRequestScope(), principal = this.auth.captureRequestScope();
    const current = () => this.workspace.isRequestScopeCurrent(scope) && this.auth.isRequestScopeCurrent(principal) && !init.signal?.aborted;
    const response = await this.transport.fetch('/api/v1/observability/usage' + path, {
      ...init, headers: { 'Content-Type': 'application/json', ...init.headers }, workspaceSlug: scope.workspaceSlug, cache: 'no-store',
    });
    if (!current()) throw new DOMException('Aborted', 'AbortError');
    const value = await response.json().catch(() => ({}));
    if (!current()) throw new DOMException('Aborted', 'AbortError');
    if (!response.ok) throw new UsageApiError(response.status, typeof value?.detail === 'string' ? value.detail : value?.detail?.code || 'USAGE_REQUEST_FAILED');
    return value as T;
  }
}
