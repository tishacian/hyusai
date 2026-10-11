import { Injectable, inject } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { Observable, of } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import { ApiService } from '@app/core/api.service';
import { CanonicalApiService, type Run, type LabelReviewSubmission } from '@app/core/canonical-api.service';
import type { WorkCatalogItem, WorkResolve, SystemLinkedWorkApp, PendingDecisions } from './work-catalog';
import type { WorkHome } from './work-home.vm';

export type WorkResolveResult =
  | { kind: 'ok'; body: WorkResolve }
  | { kind: 'missing' }
  | { kind: 'unavailable' };

export interface WorkAutomationJob {
  job: { system_id: string; name?: string | null; flow_sha256?: string };
  objective: { status?: string; text?: string | null };
  convention: { status?: string; value_per_unit?: number | null; currency?: string | null; unit?: string | null };
  gap: { status?: string };
  proof: { run_id?: string; status?: string; sap?: { sealed?: boolean; called?: boolean } | null } | null;
  /** Additive L17: decisions this reader may treat for this automation. */
  pending_decisions?: PendingDecisions | null;
}

export type WorkListResult =
  | { kind: 'ok'; items: WorkCatalogItem[]; jobs: WorkAutomationJob[] }
  | { kind: 'unavailable' };

export type SystemWorkAppsResult =
  | { kind: 'ok'; apps: SystemLinkedWorkApp[] }
  | { kind: 'unavailable' };

export type WorkHomeResult =
  | { kind: 'ok'; body: WorkHome }
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

  /** L33 — what waits for this reader and what agents did this week. */
  home(): Observable<WorkHomeResult> {
    return this.api.get<WorkHome>('/work/_home').pipe(
      map((body) => ({ kind: 'ok' as const, body: body ?? {} })),
      catchError(() => of({ kind: 'unavailable' as const })),
    );
  }

  /** One Run, for a receipt line; unreadable → null and the line is omitted. */
  run(id: string): Observable<Run | null> {
    return this.canonical.getRun(id).pipe(catchError(() => of(null)));
  }

  listSystemWorkApps(systemId: string): Observable<SystemWorkAppsResult> {
    return this.api
      .get<{ apps: SystemLinkedWorkApp[] }>(
        `/work/systems/${encodeURIComponent(systemId)}/apps`,
      )
      .pipe(
        map((body) => ({ kind: 'ok' as const, apps: body.apps ?? [] })),
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

  decide(run: Run, action: 'accept' | 'reject', note: string, labelReview?: LabelReviewSubmission): Observable<Run | null> {
    return this.canonical.resolveRunHitl(run.id, { action, note, expected_decision_id: run.hitl?.decision_id,
      ...(action === 'accept' && labelReview ? { label_review: labelReview } : {}),
    });
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
