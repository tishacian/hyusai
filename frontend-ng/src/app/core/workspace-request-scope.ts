import { Observable, type MonoTypeOperatorFunction } from 'rxjs';
import {
  WorkspaceRequestInvalidatedError,
  type WorkspaceRequestScope,
  type WorkspaceService,
} from './workspace.service';

/** Pin a request to its workspace and reject replies from an earlier context. */
export function captureWorkspaceRequest(
  workspace: Pick<WorkspaceService, 'captureRequestScope' | 'isRequestScopeCurrent'>,
): {
  scope: WorkspaceRequestScope;
  headers: Record<string, string>;
  isCurrent: () => boolean;
  assertCurrent: () => void;
} {
  const scope = workspace.captureRequestScope();
  if (!scope.workspaceSlug) throw new WorkspaceRequestInvalidatedError();
  const isCurrent = () => workspace.isRequestScopeCurrent(scope);
  return {
    scope,
    headers: { 'X-Workspace-Slug': scope.workspaceSlug },
    isCurrent,
    assertCurrent: () => {
      if (!isCurrent()) throw new WorkspaceRequestInvalidatedError();
    },
  };
}

/**
 * Cancel delivery after its view/workspace was invalidated. This never supplies
 * a fallback value: a current workspace failure is forwarded unchanged, while
 * a stale request completes without mutating the newly selected workspace.
 */
export function guardWorkspaceRequest<T>(isCurrent: () => boolean): MonoTypeOperatorFunction<T> {
  return source => new Observable<T>(subscriber => source.subscribe({
    next: value => {
      if (isCurrent()) subscriber.next(value);
      else subscriber.complete();
    },
    error: error => {
      if (isCurrent()) subscriber.error(error);
      else subscriber.complete();
    },
    complete: () => subscriber.complete(),
  }));
}
