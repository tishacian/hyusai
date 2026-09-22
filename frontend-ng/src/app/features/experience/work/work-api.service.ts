import { Injectable, inject } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { Observable, of } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import { ApiService } from '@app/core/api.service';
import { CanonicalApiService, type Run } from '@app/core/canonical-api.service';
import type { WorkCatalogItem, WorkResolve } from './work-catalog';

export type WorkResolveResult =
  | { kind: 'ok'; body: WorkResolve }
  | { kind: 'missing' }
  | { kind: 'unavailable' };

export interface WorkAutomationJob {
  job: { system_id: string; name?: string | null };
  objective: { status?: string; text?: string | null };
  convention: { status?: string; value_per_unit?: number | null; currency?: string | null; unit?: string | null };
  gap: { status?: string };
  proof: { run_id?: string; status?: string; sap?: { sealed?: boolean; called?: boolean } | null } | null;
}

export type WorkListResult =
  | { kind: 'ok'; items: WorkCatalogItem[]; jobs: WorkAutomationJob[] }
  | { kind: 'unavailable' };

export type WorkValidationsResult =
  | { kind: 'ok'; items: Run[] }
  | { kind: 'unavailable' };

@Injectable({ providedIn: 'root' })
export class WorkApiService {
  private readonly api = inject(ApiService);
  private readonly canonical = inject(CanonicalApiService);

  listExperiences(): Observable<WorkListResult> {
    return this.api.get<{ experiences: WorkCatalogItem[]; automation_jobs?: WorkAutomationJob[] }>('/work').pipe(
      map((body) => ({
        kind: 'ok' as const,
        items: body.experiences ?? [],
        jobs: body.automation_jobs ?? [],
      })),
      catchError(() => of({ kind: 'unavailable' as const })),
    );
  }

  automation(systemId: string): Observable<WorkAutomationJob> {
    return this.api.get<WorkAutomationJob>(`/work/automation-jobs/${encodeURIComponent(systemId)}`);
  }

  automationPackage(systemId: string, runId: string): Observable<Record<string, unknown>> {
    return this.api.get<Record<string, unknown>>(
      `/work/automation-jobs/${encodeURIComponent(systemId)}/package`,
      { run_id: runId },
    );
  }

  resolve(slug: string): Observable<WorkResolveResult> {
    return this.api.get<WorkResolve>(`/work/${encodeURIComponent(slug)}`).pipe(
      map((body) => ({ kind: 'ok' as const, body })),
      catchError((err: unknown) => {
        if (err instanceof HttpErrorResponse && err.status === 404) {
          return of({ kind: 'missing' as const });
        }
        return of({ kind: 'unavailable' as const });
      }),
    );
  }

  listPendingValidations(slug: string): Observable<WorkValidationsResult> {
    return this.api
      .get<{ runs: Run[] }>(`/work/${encodeURIComponent(slug)}/validations`)
      .pipe(
        map((body) => ({ kind: 'ok' as const, items: dedupeRuns(body.runs ?? []) })),
        catchError(() => of({ kind: 'unavailable' as const })),
      );
  }

  decide(run: Run, action: 'accept' | 'reject', note: string): Observable<Run | null> {
    return this.canonical.resolveRunHitl(run.id, { action, note, expected_decision_id: run.hitl?.decision_id });
  }
}

function dedupeRuns(runs: Run[]): Run[] {
  const seen = new Set<string>();
  const out: Run[] = [];
  for (const run of runs) {
    if (!run.id || seen.has(run.id)) continue;
    seen.add(run.id);
    out.push(run);
  }
  return out;
}
