import { Injectable, inject } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { Observable, forkJoin, of } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import { ApiService } from '@app/core/api.service';
import { CanonicalApiService, type Run } from '@app/core/canonical-api.service';
import type { WorkExperience, WorkResolve } from './work-catalog';

export type WorkResolveResult =
  | { kind: 'ok'; body: WorkResolve }
  | { kind: 'missing' }
  | { kind: 'unavailable' };

@Injectable({ providedIn: 'root' })
export class WorkApiService {
  private readonly api = inject(ApiService);
  private readonly canonical = inject(CanonicalApiService);

  listExperiences(): Observable<WorkExperience[]> {
    return this.api.get<{ experiences: WorkExperience[] }>('/experiences').pipe(
      map((body) => body.experiences ?? []),
      catchError(() => of([])),
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

  listPendingValidations(origins: readonly string[]): Observable<Run[]> {
    if (origins.length === 0) return of([]);
    return forkJoin(
      origins.map((origin) =>
        this.api
          .get<{ runs: Run[] } | Run[]>('/runs', { origin, status: 'hitl_pending' })
          .pipe(
            map((body) => (Array.isArray(body) ? body : body.runs ?? [])),
            catchError(() => of([] as Run[])),
          ),
      ),
    ).pipe(map((groups) => dedupeRuns(groups.flat())));
  }

  decide(runId: string, action: 'accept' | 'reject', note: string): Observable<Run | null> {
    return this.canonical.resolveRunHitl(runId, { action, note });
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
