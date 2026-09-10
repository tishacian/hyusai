import { Injectable, inject, signal } from "@angular/core";
import { ApiService } from "@app/core/api.service";
import { WorkspaceService } from "@app/core/workspace.service";

export interface PilotSystem {
  system_id: string;
  name: string;
  objective: string;
  runnable: boolean;
}
export interface PilotEvidence {
  name: string;
  ok: boolean;
  error?: string;
  result: {
    run_id?: string;
    system_id?: string;
    status?: string;
    decision_id?: string;
    awaiting_gate?: { decision_id: string; prompt?: string };
    runs?: PilotEvidence["result"][];
    [key: string]: unknown;
  };
}
export interface PilotTurn {
  session_id: string;
  answer: string;
  tool_calls: PilotEvidence[];
  finish_reason?: string;
}
interface Request {
  text: string;
  system_ids: string[];
  session_id?: string;
  surface: "pilot";
  request_id: string;
}
@Injectable({ providedIn: "root" })
export class AssistantPilotService {
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);
  readonly systems = signal<PilotSystem[]>([]);
  readonly systemIds = signal<string[]>([]);
  readonly turns = signal<{ question: string; response: PilotTurn }[]>([]);
  readonly busy = signal(false);
  readonly error = signal<
    "failed" | "unavailable_pilot" | "decision_changed" | null
  >(null);
  readonly retryRequest = signal<Request | null>(null);
  private sessionId: string | undefined;
  constructor() {
    this.workspace.registerContextReset(() => {
      this.reset();
      this.systems.set([]);
      this.systemIds.set([]);
    });
  }
  load(): void {
    const scope = this.workspace.captureRequestScope();
    this.api
      .get<{
        systems: PilotSystem[];
      }>("/assistant/systems", undefined, { workspaceSlug: scope.workspaceSlug })
      .subscribe({
        next: (value) => {
          if (this.workspace.isRequestScopeCurrent(scope))
            this.systems.set(value.systems);
        },
        error: () => {
          if (this.workspace.isRequestScopeCurrent(scope))
            this.error.set("failed");
        },
      });
  }
  select(ids: string[]): void {
    if (this.busy()) return;
    const next = [...new Set(ids)].sort();
    if (next.join("|") === this.systemIds().join("|")) return;
    this.reset();
    this.systemIds.set(next);
  }
  reset(): void {
    this.sessionId = undefined;
    this.turns.set([]);
    this.error.set(null);
    this.retryRequest.set(null);
    this.busy.set(false);
  }
  send(text: string): void {
    if (!text.trim() || this.busy() || this.retryRequest()) return;
    this.execute({
      text: text.trim(),
      system_ids: this.systemIds(),
      session_id: this.sessionId,
      surface: "pilot",
      request_id: crypto.randomUUID(),
    });
  }
  retry(): void {
    const request = this.retryRequest();
    if (request && !this.busy()) this.execute(request);
  }
  private execute(request: Request): void {
    const scope = this.workspace.captureRequestScope();
    this.busy.set(true);
    this.error.set(null);
    this.retryRequest.set(request);
    this.api
      .post<PilotTurn>("/assistant/turns", request, {
        workspaceSlug: scope.workspaceSlug,
      })
      .subscribe({
        next: (response) => {
          if (!this.workspace.isRequestScopeCurrent(scope)) return;
          this.sessionId = response.session_id;
          this.turns.update((turns) => [
            ...turns,
            { question: request.text, response },
          ]);
          this.retryRequest.set(null);
          this.busy.set(false);
        },
        error: (error) => {
          if (!this.workspace.isRequestScopeCurrent(scope)) return;
          this.error.set(
            error?.status === 503 ? "unavailable_pilot" : "failed",
          );
          this.busy.set(false);
        },
      });
  }
  decide(proof: PilotEvidence["result"], decision: "accept" | "reject"): void {
    if (this.busy() || !proof.run_id || !proof.awaiting_gate?.decision_id)
      return;
    const scope = this.workspace.captureRequestScope();
    this.busy.set(true);
    this.api
      .post<Record<string, unknown>>(
        "/assistant/decisions",
        {
          system_ids: this.systemIds(),
          run_id: proof.run_id,
          decision_id: proof.awaiting_gate.decision_id,
          decision,
        },
        { workspaceSlug: scope.workspaceSlug },
      )
      .subscribe({
        next: (result) => {
          if (!this.workspace.isRequestScopeCurrent(scope)) return;
          this.turns.update((turns) =>
            turns.map((turn) => ({
              ...turn,
              response: {
                ...turn.response,
                tool_calls: turn.response.tool_calls.map((call) =>
                  call.result.run_id === proof.run_id
                    ? {
                        ...call,
                        result: {
                          ...call.result,
                          ...result,
                          awaiting_gate: undefined,
                        },
                      }
                    : call,
                ),
              },
            })),
          );
          this.busy.set(false);
          this.error.set(null);
        },
        error: () => {
          if (this.workspace.isRequestScopeCurrent(scope)) {
            this.busy.set(false);
            this.error.set("decision_changed");
          }
        },
      });
  }
}
