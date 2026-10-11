import { Injectable, inject } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import {
  Observable,
  catchError,
  defer,
  finalize,
  forkJoin,
  map,
  of,
  shareReplay,
  throwError,
} from 'rxjs';
import { CanonicalApiService } from './canonical-api.service';
import type { ObjectLens } from './navigation.catalog';
import {
  AuthenticationRequestInvalidatedError,
  AuthStore,
  type AuthenticationRequestScope,
} from '../store/auth.store';
import {
  WorkspaceRequestInvalidatedError,
  WorkspaceService,
  type WorkspaceRequestScope,
} from './workspace.service';
import {
  LOT7_OBJECT_LENSES,
  type ObjectPerspectiveBlock,
  type ObjectPerspectiveFact,
  type ObjectPerspectiveFacetPayload,
  type ObjectPerspectiveIdentity,
  type ObjectPerspectiveResponse,
} from '@app/shared/cockpit/object-perspective.models';

export type Lot7PerspectiveObjectType = 'capability' | 'run' | 'skill_invocation';

export interface ObjectPerspectiveRequest {
  objectType: Lot7PerspectiveObjectType;
  objectId: string;
  runId?: string;
  window?: '7d' | '30d' | '90d';
}

export interface ObjectPerspectiveLoadOptions {
  /** Discard the current bundle before issuing all four authoritative reads. */
  forceRefresh?: boolean;
}

export class ObjectPerspectiveContractError extends Error {
  override readonly name = 'ObjectPerspectiveContractError';

  constructor(readonly violation: string) {
    super(`Invalid object perspective contract: ${violation}`);
  }
}

export class ObjectPerspectiveRequestSupersededError extends Error {
  override readonly name = 'ObjectPerspectiveRequestSupersededError';

  constructor() {
    super('Object perspective request was superseded by a newer refresh.');
  }
}

export class ObjectPerspectiveGateRevokedError extends Error {
  override readonly name = 'ObjectPerspectiveGateRevokedError';

  constructor(readonly objectType: Lot7PerspectiveObjectType) {
    super(`The ${objectType} projection gate was revoked.`);
  }
}

class ObjectPerspectiveSnapshotMismatchError extends ObjectPerspectiveContractError {
  constructor() {
    super('snapshot_id changes across lenses');
  }
}

interface CachedPerspective {
  readonly payload: ObjectPerspectiveResponse;
  readonly cachedAt: number;
}

interface InFlightPerspective {
  readonly generation: number;
  readonly request: Observable<Record<ObjectLens, ObjectPerspectiveResponse>>;
}

const CACHE_TTL_MS = 30_000;
const MAX_CACHE_ENTRIES = 128;
const OBJECT_TYPES = new Set<Lot7PerspectiveObjectType>([
  'capability',
  'run',
  'skill_invocation',
]);
const WINDOWS = new Set(['7d', '30d', '90d']);
const FACT_STATES = new Set([
  'available',
  'not_measured',
  'not_configured',
  'restricted',
  'unavailable',
]);
const REQUIRED_FACETS: Readonly<Record<Lot7PerspectiveObjectType, readonly string[]>> = {
  capability: ['overview', 'systems', 'outcomes', 'policies'],
  run: ['overview', 'invocations', 'payloads', 'checkpoints'],
  skill_invocation: ['overview', 'io', 'runtime', 'governance'],
};
const FEATURE_BY_OBJECT_TYPE: Readonly<Record<Lot7PerspectiveObjectType, string>> = {
  capability: 'capability_360_projection_v1',
  run: 'run_360_projection_v1',
  skill_invocation: 'skill_invocation_360_projection_v1',
};

@Injectable({ providedIn: 'root' })
export class ObjectPerspectiveStore {
  private readonly api = inject(CanonicalApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly auth = inject(AuthStore);
  private readonly cache = new Map<string, CachedPerspective>();
  private readonly inFlight = new Map<string, InFlightPerspective>();
  private readonly generations = new Map<string, number>();

  constructor() {
    this.workspace.registerContextReset(() => this.resetContext());
    this.auth.registerContextReset(() => this.resetContext());
  }

  loadAll(
    request: ObjectPerspectiveRequest,
    options: ObjectPerspectiveLoadOptions = {},
  ): Observable<Record<ObjectLens, ObjectPerspectiveResponse>> {
    const requestError = this.validateRequest(request);
    if (requestError) {
      return throwError(() => new ObjectPerspectiveContractError(requestError));
    }

    const scope = this.workspace.captureRequestScope();
    const authScope = this.auth.captureRequestScope();
    const expectedWorkspaceId = scope.workspaceId;
    const window = request.window ?? '30d';
    const bundleKey = this.bundleKey(request, window, scope, authScope);
    if (options.forceRefresh) {
      this.invalidateCachedBundle(bundleKey);
    } else {
      const cached = this.cachedPayloads(bundleKey);
      if (cached) return of(cached);
      const pending = this.inFlight.get(bundleKey);
      if (pending) return pending.request;
    }

    const generation = this.nextGeneration(bundleKey);
    const readBundle = (
      retrySnapshotMismatch: boolean,
    ): Observable<Record<ObjectLens, ObjectPerspectiveResponse>> => defer(() => forkJoin(
      LOT7_OBJECT_LENSES.map((lens) => this.loadLens(request, lens, window)),
    )).pipe(
      map((responses) => {
        if (!this.auth.isRequestScopeCurrent(authScope)) {
          throw new AuthenticationRequestInvalidatedError();
        }
        if (!this.workspace.isRequestScopeCurrent(scope)) {
          throw new WorkspaceRequestInvalidatedError();
        }
        if (this.generations.get(bundleKey) !== generation) {
          throw new ObjectPerspectiveRequestSupersededError();
        }

        // Validate the complete bundle first. A malformed or cross-object
        // response must never leave even one lens in the cache.
        const payloads = this.validateBundle(
          responses,
          request,
          window,
          expectedWorkspaceId,
        );
        return payloads;
      }),
      catchError((error: unknown) => {
        if (this.isGateRevocation(error)) {
          // Errors bypass the successful-response guards above. A late 410
          // from workspace/principal A must never revoke the effective feature
          // of B, nor may an obsolete forced refresh revoke the winning one.
          if (!this.auth.isRequestScopeCurrent(authScope)) {
            return throwError(() => new AuthenticationRequestInvalidatedError());
          }
          if (!this.workspace.isRequestScopeCurrent(scope)) {
            return throwError(() => new WorkspaceRequestInvalidatedError());
          }
          if (this.generations.get(bundleKey) !== generation) {
            return throwError(() => new ObjectPerspectiveRequestSupersededError());
          }
          this.invalidateCachedBundle(bundleKey);
          this.workspace.revokeEffectiveFeature(FEATURE_BY_OBJECT_TYPE[request.objectType]);
          // Reconcile with the authoritative server snapshot. The local
          // pessimistic revocation above is synchronous and remains closed if
          // this best-effort refresh is interrupted by a workspace switch.
          this.workspace.refreshCurrentWorkspace().subscribe();
          return throwError(
            () => new ObjectPerspectiveGateRevokedError(request.objectType),
          );
        }
        if (
          retrySnapshotMismatch
          && error instanceof ObjectPerspectiveSnapshotMismatchError
        ) {
          return readBundle(false);
        }
        return throwError(() => error);
      }),
    );

    let request$: Observable<Record<ObjectLens, ObjectPerspectiveResponse>>;
    request$ = readBundle(true).pipe(
      map((payloads) => {
        const cachedAt = Date.now();
        LOT7_OBJECT_LENSES.forEach((lens) => {
          this.cache.set(this.lensKey(bundleKey, lens), {
            payload: payloads[lens],
            cachedAt,
          });
        });
        this.pruneCache(cachedAt);
        return payloads;
      }),
      finalize(() => {
        if (this.inFlight.get(bundleKey)?.generation === generation) {
          this.inFlight.delete(bundleKey);
        }
      }),
      shareReplay({ bufferSize: 1, refCount: true }),
    );
    this.inFlight.set(bundleKey, { generation, request: request$ });
    return request$;
  }

  /**
   * Invalidates one four-lens bundle. Passing no request clears every object
   * projection in the current workspace epoch.
   */
  invalidate(request?: ObjectPerspectiveRequest): void {
    if (!request) {
      this.resetContext();
      return;
    }
    const window = request.window ?? '30d';
    const bundleKey = this.bundleKey(
      request,
      window,
      this.workspace.captureRequestScope(),
      this.auth.captureRequestScope(),
    );
    this.invalidateCachedBundle(bundleKey);
    this.generations.set(bundleKey, (this.generations.get(bundleKey) ?? 0) + 1);
    this.inFlight.delete(bundleKey);
  }

  private cachedPayloads(
    bundleKey: string,
  ): Record<ObjectLens, ObjectPerspectiveResponse> | null {
    const now = Date.now();
    const payloads = {} as Record<ObjectLens, ObjectPerspectiveResponse>;
    for (const lens of LOT7_OBJECT_LENSES) {
      const key = this.lensKey(bundleKey, lens);
      const cached = this.cache.get(key);
      if (!cached || now - cached.cachedAt < 0 || now - cached.cachedAt > CACHE_TTL_MS) {
        if (cached) this.cache.delete(key);
        return null;
      }
      payloads[lens] = cached.payload;
    }
    return payloads;
  }

  private loadLens(
    request: ObjectPerspectiveRequest,
    lens: ObjectLens,
    window: string,
  ): Observable<ObjectPerspectiveResponse | null> {
    switch (request.objectType) {
      case 'capability':
        return this.api.getCapabilityPerspective(request.objectId, lens, window);
      case 'run':
        return this.api.getRunPerspective(request.objectId, lens, window);
      case 'skill_invocation':
        return this.api.getSkillInvocationPerspective(
          request.runId!,
          request.objectId,
          lens,
          window,
        );
    }
  }

  private isGateRevocation(error: unknown): boolean {
    return error instanceof HttpErrorResponse
      && error.status === 410
      && error.error?.detail?.code === 'OBJECT_PROJECTION_REVOKED';
  }

  private validateBundle(
    responses: readonly (ObjectPerspectiveResponse | null)[],
    request: ObjectPerspectiveRequest,
    window: string,
    expectedWorkspaceId: string | null,
  ): Record<ObjectLens, ObjectPerspectiveResponse> {
    if (responses.length !== LOT7_OBJECT_LENSES.length) {
      throw new ObjectPerspectiveContractError('the four lenses were not returned');
    }

    const payloads = {} as Record<ObjectLens, ObjectPerspectiveResponse>;
    let invariantSnapshot = '';
    let invariantIdentity = '';
    let invariantHeader = '';
    responses.forEach((candidate, index) => {
      const lens = LOT7_OBJECT_LENSES[index];
      const payload = this.validateResponse(
        candidate,
        request,
        lens,
        window,
        expectedWorkspaceId,
      );
      const identity = canonicalJson(payload.identity);
      const header = canonicalJson(payload.header);
      if (index === 0) {
        invariantSnapshot = payload.snapshot_id;
        invariantIdentity = identity;
        invariantHeader = header;
      } else {
        if (payload.snapshot_id !== invariantSnapshot) {
          throw new ObjectPerspectiveSnapshotMismatchError();
        }
        if (identity !== invariantIdentity) {
          throw new ObjectPerspectiveContractError('identity changes across lenses');
        }
        if (header !== invariantHeader) {
          throw new ObjectPerspectiveContractError('header changes across lenses');
        }
      }
      payloads[lens] = payload;
    });
    return payloads;
  }

  private validateResponse(
    candidate: unknown,
    request: ObjectPerspectiveRequest,
    expectedLens: ObjectLens,
    expectedWindow: string,
    expectedWorkspaceId: string | null,
  ): ObjectPerspectiveResponse {
    if (!isRecord(candidate)) {
      throw new ObjectPerspectiveContractError(`${expectedLens} payload is missing`);
    }
    if (candidate['schema_version'] !== 1) {
      throw new ObjectPerspectiveContractError(`${expectedLens} schema_version is not 1`);
    }
    if (!isNonEmptyString(candidate['snapshot_id'])) {
      throw new ObjectPerspectiveContractError(`${expectedLens} snapshot_id is missing`);
    }
    if (!isNonEmptyString(candidate['generated_at']) || Number.isNaN(Date.parse(candidate['generated_at']))) {
      throw new ObjectPerspectiveContractError(`${expectedLens} generated_at is invalid`);
    }
    if (candidate['lens'] !== expectedLens) {
      throw new ObjectPerspectiveContractError(`${expectedLens} response declares another lens`);
    }
    if (candidate['window'] !== expectedWindow) {
      throw new ObjectPerspectiveContractError(`${expectedLens} response declares another window`);
    }

    const identity = candidate['identity'];
    if (!this.validIdentity(identity, request, expectedWorkspaceId)) {
      throw new ObjectPerspectiveContractError(`${expectedLens} identity does not match the request`);
    }
    if (!isFactRecord(candidate['header'])) {
      throw new ObjectPerspectiveContractError(`${expectedLens} header is invalid`);
    }
    const facets = candidate['facets'];
    if (!isRecord(facets)) {
      throw new ObjectPerspectiveContractError(`${expectedLens} facets are invalid`);
    }
    for (const facet of REQUIRED_FACETS[request.objectType]) {
      if (!isFacetPayload(facets[facet])) {
        throw new ObjectPerspectiveContractError(`${expectedLens}.${facet} facet is invalid`);
      }
    }
    return candidate as unknown as ObjectPerspectiveResponse;
  }

  private validIdentity(
    candidate: unknown,
    request: ObjectPerspectiveRequest,
    expectedWorkspaceId: string | null,
  ): candidate is ObjectPerspectiveIdentity {
    if (!isRecord(candidate)) return false;
    if (
      !isNonEmptyString(candidate['workspace_id'])
      || candidate['object_type'] !== request.objectType
      || candidate['object_id'] !== request.objectId
      || !isNonEmptyString(candidate['name'])
    ) {
      return false;
    }
    if (expectedWorkspaceId && candidate['workspace_id'] !== expectedWorkspaceId) return false;
    switch (request.objectType) {
      case 'capability':
        return candidate['capability_id'] === request.objectId;
      case 'run':
        return candidate['run_id'] === request.objectId;
      case 'skill_invocation':
        return candidate['skill_invocation_id'] === request.objectId
          && candidate['run_id'] === request.runId;
    }
  }

  private validateRequest(request: ObjectPerspectiveRequest): string | null {
    if (!OBJECT_TYPES.has(request.objectType)) return 'objectType is invalid';
    if (!isNonEmptyString(request.objectId)) return 'objectId is required';
    if (request.window !== undefined && !WINDOWS.has(request.window)) return 'window is invalid';
    if (request.objectType === 'skill_invocation' && !isNonEmptyString(request.runId)) {
      return 'runId is required for a SkillInvocation';
    }
    return null;
  }

  private pruneCache(now: number): void {
    for (const [key, cached] of this.cache) {
      if (now - cached.cachedAt < 0 || now - cached.cachedAt > CACHE_TTL_MS) {
        this.cache.delete(key);
      }
    }
    while (this.cache.size > MAX_CACHE_ENTRIES) {
      const oldest = this.cache.keys().next().value as string | undefined;
      if (oldest === undefined) break;
      this.cache.delete(oldest);
    }
  }

  private resetContext(): void {
    this.cache.clear();
    this.inFlight.clear();
    this.generations.clear();
  }

  private invalidateCachedBundle(bundleKey: string): void {
    LOT7_OBJECT_LENSES.forEach((lens) => {
      this.cache.delete(this.lensKey(bundleKey, lens));
    });
  }

  private nextGeneration(bundleKey: string): number {
    const generation = (this.generations.get(bundleKey) ?? 0) + 1;
    this.generations.set(bundleKey, generation);
    return generation;
  }

  private bundleKey(
    request: ObjectPerspectiveRequest,
    window: string,
    workspaceScope: WorkspaceRequestScope,
    authScope: AuthenticationRequestScope,
  ): string {
    return JSON.stringify([
      authScope.epoch,
      workspaceScope.epoch,
      workspaceScope.workspaceSlug ?? '',
      workspaceScope.workspaceId ?? '',
      request.objectType,
      request.runId ?? '',
      request.objectId,
      window,
    ]);
  }

  private lensKey(bundleKey: string, lens: ObjectLens): string {
    return `${bundleKey}:${lens}`;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function isFact(value: unknown): value is ObjectPerspectiveFact {
  if (!isRecord(value)) return false;
  if (
    !isNonEmptyString(value['key'])
    || !isNonEmptyString(value['label'])
    || typeof value['state'] !== 'string'
    || !FACT_STATES.has(value['state'])
    || !Object.hasOwn(value, 'value')
  ) {
    return false;
  }
  const optionalStrings = ['unit', 'source', 'as_of', 'description'];
  if (optionalStrings.some((key) => value[key] != null && typeof value[key] !== 'string')) {
    return false;
  }
  return value['sample_count'] == null
    || (typeof value['sample_count'] === 'number' && Number.isFinite(value['sample_count']));
}

function isFactRecord(value: unknown): value is Record<string, ObjectPerspectiveFact> {
  return isRecord(value) && Object.values(value).every(isFact);
}

function isBlock(value: unknown): value is ObjectPerspectiveBlock {
  return isRecord(value)
    && isNonEmptyString(value['id'])
    && isNonEmptyString(value['title'])
    && (value['description'] == null || typeof value['description'] === 'string')
    && Array.isArray(value['facts'])
    && value['facts'].every(isFact);
}

function isFacetPayload(value: unknown): value is ObjectPerspectiveFacetPayload {
  return isRecord(value)
    && Array.isArray(value['blocks'])
    && value['blocks'].every(isBlock);
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  if (isRecord(value)) {
    return `{${Object.keys(value).sort().map((key) => (
      `${JSON.stringify(key)}:${canonicalJson(value[key])}`
    )).join(',')}}`;
  }
  return JSON.stringify(value) ?? 'undefined';
}
