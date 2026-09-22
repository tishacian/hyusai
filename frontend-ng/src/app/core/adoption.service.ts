import { Injectable, computed, effect, inject, signal } from "@angular/core";
import { Subject, EMPTY, concatMap, catchError, tap } from "rxjs";
import { ApiService } from "./api.service";
import { WorkspaceService, workspaceSettingFeature } from "./workspace.service";
import { HelpService, type Persona } from "./help.service";

export type AdoptionStep = "example" | "question" | "source" | "result";
export interface AdoptionProgress {
  version: 1;
  persona: Persona;
  journey: "northforge_sources";
  completed_steps: AdoptionStep[];
  dismissed: boolean;
  session_id?: string;
  run_id?: string;
  example_available?: boolean;
}
@Injectable({ providedIn: "root" })
export class AdoptionService {
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly help = inject(HelpService);
  readonly enabled = computed(() =>
    workspaceSettingFeature(this.workspace.current(), "adoption_experience_v1", true),
  );
  readonly progress = signal<AdoptionProgress | null>(null);
  readonly error = signal(false);
  readonly saving = signal(false);
  private revision = 0;
  readonly exampleAvailable = computed(
    () => this.enabled() && this.progress()?.example_available === true,
  );
  private readonly patches = new Subject<{
    patch: {
      persona?: Persona;
      completed_step?: AdoptionStep;
      dismissed?: boolean;
      session_id?: string;
      run_id?: string;
    };
    scope: ReturnType<WorkspaceService["captureRequestScope"]>;
  }>();
  constructor() {
    this.patches
      .pipe(
        concatMap(({ patch, scope }) => {
          if (!this.workspace.isRequestScopeCurrent(scope)) return EMPTY;
          this.saving.set(true);
          return this.api
            .patch<AdoptionProgress>(
              `/auth/workspaces/${encodeURIComponent(scope.workspaceSlug!)}/me/experience`,
              patch,
              { workspaceSlug: scope.workspaceSlug },
            )
            .pipe(
              tap((value) => {
                if (!this.workspace.isRequestScopeCurrent(scope)) return;
                this.progress.set({
                  ...value,
                  example_available: this.progress()?.example_available,
                });
                this.help.setPersona(value.persona);
                this.saving.set(false);
                this.error.set(false);
              }),
              catchError(() => {
                if (this.workspace.isRequestScopeCurrent(scope)) {
                  this.error.set(true);
                  this.saving.set(false);
                }
                return EMPTY;
              }),
            );
        }),
      )
      .subscribe();
    this.workspace.registerContextReset(() => {
      this.revision++;
      this.progress.set(null);
      this.help.setPersona("operator");
      this.error.set(false);
      this.saving.set(false);
    });
    effect(() => {
      if (this.enabled()) this.load();
    });
  }
  load(): void {
    const scope = this.workspace.captureRequestScope();
    const revision = this.revision;
    this.api
      .get<AdoptionProgress>(
        `/auth/workspaces/${encodeURIComponent(scope.workspaceSlug!)}/me/experience`,
        undefined,
        { workspaceSlug: scope.workspaceSlug },
      )
      .subscribe({
        next: (value) => {
          if (!this.workspace.isRequestScopeCurrent(scope)) return;
          if (revision !== this.revision) {
            this.progress.update((current) =>
              current
                ? { ...current, example_available: value.example_available }
                : current,
            );
            return;
          }
          this.progress.set(value);
          this.help.setPersona(value.persona);
          this.error.set(false);
        },
        error: () => {
          if (this.workspace.isRequestScopeCurrent(scope)) this.error.set(true);
        },
      });
  }
  update(patch: {
    persona?: Persona;
    completed_step?: AdoptionStep;
    dismissed?: boolean;
    session_id?: string;
    run_id?: string;
  }): void {
    if (!this.enabled()) return;
    this.revision++;
    this.patches.next({ patch, scope: this.workspace.captureRequestScope() });
  }
}
