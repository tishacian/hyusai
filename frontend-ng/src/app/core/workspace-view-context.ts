import type {
  WorkspaceContextTransition,
  WorkspaceRequestScope,
  WorkspaceService,
} from './workspace.service';

/**
 * Identity captured by a workspace-bound view before it starts a request.
 *
 * The workspace scope rejects A responses after an A -> B transition. The
 * local generation also rejects an older route/id request that completes
 * after a newer request in the same workspace.
 */
export interface WorkspaceViewRequest {
  readonly scope: WorkspaceRequestScope;
  readonly generation: number;
}

type WorkspaceContextPort = Pick<
  WorkspaceService,
  | 'captureRequestScope'
  | 'isRequestScopeCurrent'
  | 'registerContextReset'
  | 'contextEpoch'
>;

/**
 * Coordinates atomic workspace resets for long-lived routed components.
 *
 * `WorkspaceService` invokes resetters while A is still the current scope,
 * then publishes B and its new epoch atomically. Consequently this helper:
 *
 * 1. invalidates all request tokens and clears view state synchronously;
 * 2. waits one microtask for B to be published;
 * 3. asks the surviving routed component to reload exactly for that epoch.
 */
export class WorkspaceViewContext {
  private generation = 0;
  private destroyed = false;
  private readonly unregisterReset: () => void;

  constructor(
    private readonly workspace: WorkspaceContextPort,
    private readonly resetView: () => void,
    private readonly reloadView: () => void,
  ) {
    this.unregisterReset = this.workspace.registerContextReset((transition) => {
      this.invalidate();
      this.resetView();
      this.reloadAfterCommit(transition);
    });
  }

  beginRequest(): WorkspaceViewRequest {
    return Object.freeze({
      scope: this.workspace.captureRequestScope(),
      generation: ++this.generation,
    });
  }

  captureRequest(): WorkspaceViewRequest {
    if (this.generation === 0) this.generation = 1;
    return Object.freeze({
      scope: this.workspace.captureRequestScope(),
      generation: this.generation,
    });
  }

  isCurrent(request: WorkspaceViewRequest): boolean {
    return (
      !this.destroyed
      && request.generation === this.generation
      && this.workspace.isRequestScopeCurrent(request.scope)
    );
  }

  invalidate(): void {
    this.generation += 1;
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    this.invalidate();
    this.unregisterReset();
    this.resetView();
  }

  private reloadAfterCommit(transition: WorkspaceContextTransition): void {
    queueMicrotask(() => {
      if (
        this.destroyed
        || this.workspace.contextEpoch() !== transition.nextEpoch
      ) {
        return;
      }
      this.reloadView();
    });
  }
}
