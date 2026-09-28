import { Injectable, computed, effect, inject, signal } from "@angular/core";
import { Subject, EMPTY, concatMap, catchError, tap } from "rxjs";
import { ApiService } from "./api.service";
import { WorkspaceService, workspaceSettingFeature } from "./workspace.service";
import { HelpService, type Persona } from "./help.service";
import { railLabelsVisible, type RailLabelsPreference } from "./rail-labels";

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
  /** L27 — how the Cockpit rail shows its zone names (default `auto`). */
  rail_labels?: RailLabelsPreference;
  /** Server-owned, set on the member's first read; drives `auto`. */
  first_seen_at?: string | null;
}
type ExperiencePatch = {
  persona?: Persona;
  completed_step?: AdoptionStep;
  dismissed?: boolean;
  session_id?: string;
  run_id?: string;
  rail_labels?: RailLabelsPreference;
};
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
  /**
   * Whether the Cockpit rail shows its labels; `null` while the experience
   * record is unknown, so the rail keeps its icon column and never shows
   * labels it might have to take back. Off with `adoption_experience_v1`.
   */
  readonly railLabelsVisible = computed<boolean | null>(() => {
    if (!this.enabled()) return false;
    const progress = this.progress();
    if (!progress) return null;
    return railLabelsVisible(progress.rail_labels ?? "auto", progress.first_seen_at, Date.now());
  });
  /** The last rail-label change could not be saved and was reverted. */
  readonly railLabelsError = signal(false);
  private readonly patches = new Subject<{
    patch: ExperiencePatch;
    scope: ReturnType<WorkspaceService["captureRequestScope"]>;
    /** Replaces the journey error (and its alert) for preference writes. */
    onError?: () => void;
  }>();
  constructor() {
    this.patches
      .pipe(
        concatMap(({ patch, scope, onError }) => {
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
                  if (onError) onError();
                  else this.error.set(true);
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
      this.railLabelsError.set(false);
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
  update(patch: Omit<ExperiencePatch, "rail_labels">): void {
    if (!this.enabled()) return;
    this.revision++;
    this.patches.next({ patch, scope: this.workspace.captureRequestScope() });
  }
  /**
   * Show or hide the rail labels. Optimistic: the rail follows at once; if
   * the write fails the previous preference comes back and
   * `railLabelsError` lets the rail say so politely.
   */
  setRailLabels(value: RailLabelsPreference): void {
    const current = this.progress();
    if (!this.enabled() || !current) return;
    const previous = current.rail_labels;
    this.revision++;
    this.railLabelsError.set(false);
    this.progress.set({ ...current, rail_labels: value });
    this.patches.next({
      patch: { rail_labels: value },
      scope: this.workspace.captureRequestScope(),
      onError: () => {
        const latest = this.progress();
        if (latest && latest.rail_labels === value) {
          this.progress.set({ ...latest, rail_labels: previous });
        }
        this.railLabelsError.set(true);
      },
    });
  }
}
