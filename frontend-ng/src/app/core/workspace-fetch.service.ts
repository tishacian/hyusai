import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { AuthRefreshCoordinator } from './auth-refresh-coordinator.service';
import { TokenStorageService } from './token-storage.service';
import { WorkspaceService } from './workspace.service';

export interface WorkspaceFetchInit extends RequestInit {
  /**
   * Immutable workspace scope for this request and its optional 401 retry.
   * An explicit X-Workspace-Slug header takes precedence over this value.
   */
  workspaceSlug?: string | null;
}

/**
 * Authenticated direct-fetch transport for streaming and non-HttpClient users.
 *
 * Each call snapshots one workspace slug, attaches auth + tenant headers, and
 * performs at most one retry on an actual 401. The retry reuses the same input,
 * body and workspace scope; no other status or transport error is replayed.
 */
@Injectable({ providedIn: 'root' })
export class WorkspaceFetchService {
  private readonly tokenStorage = inject(TokenStorageService);
  private readonly workspace = inject(WorkspaceService);
  private readonly refreshCoordinator = inject(AuthRefreshCoordinator);

  async fetch(input: RequestInfo | URL, init: WorkspaceFetchInit = {}): Promise<Response> {
    const { workspaceSlug: requestedWorkspaceSlug, ...requestInit } = init;
    const baseHeaders = this.requestHeaders(input, requestInit.headers);
    const capturedWorkspaceSlug =
      baseHeaders.get('X-Workspace-Slug') ||
      requestedWorkspaceSlug ||
      this.workspace.captureRequestScope().workspaceSlug;

    if (!baseHeaders.has('Authorization')) {
      const authorization = this.tokenStorage.getToken();
      if (authorization) baseHeaders.set('Authorization', authorization);
    }
    if (!baseHeaders.has('X-Workspace-Slug') && capturedWorkspaceSlug) {
      baseHeaders.set('X-Workspace-Slug', capturedWorkspaceSlug);
    }

    // Clone Request inputs before dispatch so their bodies remain available for
    // the single permitted retry. RequestInit bodies used by Agentium's direct
    // transports are replayable strings, Blob/FormData values, or null.
    const [firstInput, retryInput] = this.attemptInputs(input);
    const firstHeaders = new Headers(baseHeaders);
    const response = await globalThis.fetch(firstInput, {
      ...requestInit,
      headers: firstHeaders,
    });
    if (response.status !== 401) return response;

    const authorization = await firstValueFrom(
      this.refreshCoordinator.authorizationAfter401(firstHeaders.get('Authorization')),
    );
    if (requestInit.signal?.aborted) {
      throw requestInit.signal.reason ?? new DOMException('Aborted', 'AbortError');
    }
    const retryHeaders = new Headers(baseHeaders);
    retryHeaders.set('Authorization', authorization);
    return globalThis.fetch(retryInput, {
      ...requestInit,
      headers: retryHeaders,
    });
  }

  private requestHeaders(input: RequestInfo | URL, initHeaders: HeadersInit | undefined): Headers {
    if (initHeaders !== undefined) return new Headers(initHeaders);
    if (typeof Request !== 'undefined' && input instanceof Request) {
      return new Headers(input.headers);
    }
    return new Headers();
  }

  private attemptInputs(input: RequestInfo | URL): [RequestInfo | URL, RequestInfo | URL] {
    if (typeof Request !== 'undefined' && input instanceof Request) {
      return [input.clone(), input.clone()];
    }
    return [input, input];
  }
}
