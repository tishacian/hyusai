/**
 * NAWA WE — data access for the two ITSD surfaces.
 *
 * The catalogue is a static asset. Password Reset still drives systems/runs;
 * when `experience_v1` is on, System lookup prefers the seeded
 * `nawa.password_reset` binding and falls back to name-match.
 */
import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, of, shareReplay } from 'rxjs';
import { catchError, map, switchMap } from 'rxjs/operators';
import { CanonicalApiService, type Run, type System } from '@app/core/canonical-api.service';
import { ApiService } from '@app/core/api.service';
import { WorkspaceService } from '@app/core/workspace.service';
import {
  NAWA_APP_FULL_NAME,
  NAWA_PASSWORD_RESET_BINDING_KEY,
  NAWA_SYSTEM_NAME_MATCH,
  systemIdFromBindingResolve,
  type NawaCatalog,
  type NawaScenario,
} from './nawa-itsd.model';

const CATALOG_URL = '/assets/nawa/itsd-use-cases.json';

const EMPTY_CATALOG: NawaCatalog = {
  meta: {
    assistant: NAWA_APP_FULL_NAME,
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
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);

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
    const byName = () => this.canonical.listSystems().pipe(
      map((systems) =>
        systems.find((system) =>
          (system.name || '').toLowerCase().includes(NAWA_SYSTEM_NAME_MATCH),
        ) ?? null,
      ),
    );
    if (!this.experienceV1Enabled()) return byName();
    return this.api.get<{
      status?: string;
      binding?: { system_id?: string };
    }>(`/system-bindings/${encodeURIComponent(NAWA_PASSWORD_RESET_BINDING_KEY)}/resolve`).pipe(
      switchMap((resolved) => {
        const systemId = systemIdFromBindingResolve(resolved);
        if (systemId) return this.canonical.getSystem(systemId);
        console.warn(
          `NAWA: binding ${NAWA_PASSWORD_RESET_BINDING_KEY} missed; falling back to name-match`,
        );
        return byName();
      }),
      catchError(() => {
        console.warn(
          `NAWA: binding ${NAWA_PASSWORD_RESET_BINDING_KEY} resolve failed; falling back to name-match`,
        );
        return byName();
      }),
    );
  }

  private experienceV1Enabled(): boolean {
    const raw = this.workspace.current()?.settings?.['features'];
    return Boolean(
      raw
      && typeof raw === 'object'
      && !Array.isArray(raw)
      && (raw as Record<string, unknown>)['experience_v1'] === true,
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
  launch(system: System, scenario: NawaScenario): Observable<Run | null> {
    return this.launchWith(system, { scenario: scenario.scenario, ...scenario.input });
  }

  /**
   * Launch the typed-request lane with a case composed outside the run.
   *
   * Separate from `launchWith` because the case is a nested object, not a flat
   * bench selector: on this lane the flow reads the caller's words from the run
   * input instead of loading a canned case from the System settings.
   */
  launchTyped(system: System, requestCase: Record<string, unknown>): Observable<Run | null> {
    if (!system.flow_sha256) return of(null);
    return this.canonical.triggerRun(system.id, {
      input_ref: { scenario: 'free_text', case: requestCase, source: 'nawa_itsd_app' },
      trigger: 'manual',
      expected_flow_sha256: system.flow_sha256,
    });
  }

  /** Launch from a raw input, as carried by `outcome.replay_input`. */
  launchWith(
    system: System,
    input: Record<string, string | number | boolean>,
  ): Observable<Run | null> {
    if (!system.flow_sha256) return of(null);
    return this.canonical.triggerRun(system.id, {
      input_ref: { ...input, source: 'nawa_itsd_app' },
      trigger: 'manual',
      expected_flow_sha256: system.flow_sha256,
    });
  }

  getRun(runId: string): Observable<Run | null> {
    return this.canonical.getRun(runId);
  }

  /**
   * Answer the identity gate from the business app. Same endpoint the cockpit
   * uses, so the decision lands in the ledger with its author either way — the
   * point of doing it here is that a service desk supervisor never has to enter
   * the platform's own screens to unblock a ticket.
   */
  resolveHitl(runId: string, action: 'accept' | 'reject', decisionId: string | undefined, note?: string): Observable<Run | null> {
    return this.canonical.resolveRunHitl(runId, { action, note, expected_decision_id: decisionId });
  }

  /** Recent runs of the System — feeds the replay/history strip. */
  history(systemId: string): Observable<Run[]> {
    return this.canonical.listRuns({ system_id: systemId });
  }
}
