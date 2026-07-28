/**
 * NAWA WE — data access for the two ITSD surfaces.
 *
 * No new backend endpoint (SPEC §7.3): the catalogue is a static asset, and
 * the Password Reset page drives the existing systems/runs API only.
 */
import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, of, shareReplay } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import { CanonicalApiService, type Run, type System } from '@app/core/canonical-api.service';
import {
  NAWA_SYSTEM_NAME_MATCH,
  type NawaCatalog,
  type NawaScenario,
} from './nawa-itsd.model';

const CATALOG_URL = '/assets/nawa/itsd-use-cases.json';

const EMPTY_CATALOG: NawaCatalog = {
  meta: {
    assistant: 'NAWA WE',
    source_workbook: '',
    source_sheet: '',
    generated_by: '',
    use_case_count: 0,
    planned_agent_total: 0,
    source_headers: [],
    same_pattern_label: '',
  },
  use_cases: [],
};

@Injectable({ providedIn: 'root' })
export class NawaItsdService {
  private readonly http = inject(HttpClient);
  private readonly canonical = inject(CanonicalApiService);

  private catalog$: Observable<NawaCatalog> | null = null;

  /** Static catalogue — cached for the lifetime of the app. */
  catalog(): Observable<NawaCatalog> {
    this.catalog$ ??= this.http.get<NawaCatalog>(CATALOG_URL).pipe(
      catchError(() => of(EMPTY_CATALOG)),
      shareReplay({ bufferSize: 1, refCount: false }),
    );
    return this.catalog$;
  }

  /** Resolve the Password Reset System of the active workspace by name. */
  resolveSystem(): Observable<System | null> {
    return this.canonical.listSystems().pipe(
      map((systems) =>
        systems.find((system) =>
          (system.name || '').toLowerCase().includes(NAWA_SYSTEM_NAME_MATCH),
        ) ?? null,
      ),
    );
  }

  getSystem(systemId: string): Observable<System | null> {
    return this.canonical.getSystem(systemId);
  }

  /**
   * Launch one simulation from a selector entry: the scenario plus its own extra
   * fields is all the flow's bench decision reads, since it loads the caller
   * case itself from the System settings.
   */
  launch(systemId: string, scenario: NawaScenario): Observable<Run | null> {
    return this.launchWith(systemId, { scenario: scenario.scenario, ...scenario.input });
  }

  /** Launch from a raw input, as carried by `outcome.replay_input`. */
  launchWith(
    systemId: string,
    input: Record<string, string | number | boolean>,
  ): Observable<Run | null> {
    return this.canonical.triggerRun(systemId, {
      input_ref: { ...input, source: 'nawa_itsd_app' },
      trigger: 'manual',
    });
  }

  getRun(runId: string): Observable<Run | null> {
    return this.canonical.getRun(runId);
  }

  /** Recent runs of the System — feeds the replay/history strip. */
  history(systemId: string): Observable<Run[]> {
    return this.canonical.listRuns({ system_id: systemId });
  }
}
