/**
 * Shared run/debug vocabulary for the restored execution surface.
 *
 * Kept in a tiny standalone module (no Angular, no DI) so the presentational
 * `flow-terminal` / `flow-run-controls` components can depend on the *shapes*
 * without importing the `FlowRunService` runtime — the service is the single
 * orchestrator, these are just the contracts that flow between it and the UI.
 */
import type { NodeTone } from './flow.types';

/**
 * Coarse run lifecycle the controls + terminal render against. Mirrors the
 * proven monolith state machine but as a small, explicit union:
 *   idle → running → (paused ⇄ running)* → done | error
 */
export type RunUiStatus = 'idle' | 'running' | 'paused' | 'done' | 'error';

/** Step-debugger mode cycled by the run controls (off → step → breakpoints). */
export type DebugMode = 'off' | 'step' | 'breakpoints';

/** One timestamped line in the execution terminal. */
export interface RunLogEntry {
  id: string;
  /** HH:MM:SS wall-clock stamp. */
  t: string;
  /** Short uppercase tag, e.g. `EXEC`, `NODE`, `HITL`, `ERR`. */
  tag: string;
  tone: NodeTone | 'pos' | 'neg' | 'warn' | 'info';
  text: string;
  /**
   * Stream id used by `token_delta` frames so a single LLM node owns one
   * growing line instead of flooding the log with one entry per chunk.
   */
  streamId?: string;
}
