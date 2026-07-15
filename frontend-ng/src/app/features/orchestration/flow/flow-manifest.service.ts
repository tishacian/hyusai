/**
 * `FlowManifestService` — the READ-only bridge between the backend runtime
 * manifest (`GET /systems/{id}/flow-manifest`) and the Flow Builder UI.
 *
 * Phase 2 (manifest inspector) needs two things the CanonicalFlow pivot does
 * NOT carry, because they are *derived* server-side from the live skill
 * registry rather than stored in `flow_definition`:
 *   - per-node `editable_fields` (typed parameter descriptors), and
 *   - per-node `runtime_status` / `operational` (the "configured?" verdict).
 *
 * Keeping this in a `providedIn: 'root'` singleton lets BOTH consumers share
 * one fetch without touching the store, the canvas, or the shell:
 *   - the inspector's manifest-fields child reads `unitFor(nodeId)`, and
 *   - the canvas node component reads `statusFor(nodeId)` for its badge.
 *
 * It deliberately holds NO graph state — the FlowStore stays the single
 * source of truth for the graph. The manifest is a transient, system-scoped
 * sidecar that never gets written back into the canonical model (so a freshly
 * loaded flow is never spuriously marked dirty).
 */
import { Injectable, computed, inject, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import {
  CanonicalApiService,
  type FlowManifestUnit,
  type FlowRuntimeManifest,
} from '@app/core/canonical-api.service';
import { WorkspaceService } from '@app/core/workspace.service';

export interface NodeRuntimeStatus {
  /** bound | stub | unbound | manifest_only | catalog_only (backend verbatim). */
  status: string;
  /** Backend's "this node actually drives a live surface" verdict. */
  operational: boolean;
}

@Injectable({ providedIn: 'root' })
export class FlowManifestService {
  private readonly canonical = inject(CanonicalApiService);
  private readonly workspace = inject(WorkspaceService);

  private readonly _manifest = signal<FlowRuntimeManifest | null>(null);
  private readonly _systemId = signal<string | null>(null);
  /** systemId already fetched / in-flight — dedups the N node callers. */
  private requestedSystemId: string | null = null;
  private request: Subscription | null = null;

  readonly manifest = this._manifest.asReadonly();
  readonly systemId = this._systemId.asReadonly();

  constructor() {
    this.workspace.registerContextReset(() => {
      this.request?.unsubscribe();
      this.request = null;
      this.requestedSystemId = null;
      this._systemId.set(null);
      this._manifest.set(null);
    });
  }

  private readonly unitsById = computed<Map<string, FlowManifestUnit>>(() => {
    const map = new Map<string, FlowManifestUnit>();
    for (const unit of this._manifest()?.unit_catalog ?? []) {
      if (unit?.id) map.set(unit.id, unit);
    }
    return map;
  });

  /**
   * Fetch the manifest for `systemId` exactly once. No-op for the scratchpad
   * (null id) or when the same system is already loaded / in-flight. Safe to
   * call from every node + the inspector — only the first call hits the wire.
   */
  ensureLoaded(systemId: string | null): void {
    if (!systemId || this.requestedSystemId === systemId) return;
    this.requestedSystemId = systemId;
    this._systemId.set(systemId);
    this.fetch(systemId);
  }

  /**
   * Force a re-fetch of the CURRENT system's manifest, bypassing the
   * `ensureLoaded` dedup. Call after a successful save: persisting the flow
   * can change `runtime_status` / `operational` / `editable_fields` (a node
   * just got a skill bound, a param now resolves), so node badges and the
   * inspector's "Configured?" verdict would otherwise stay stale until the
   * user navigates away and back. No-op for the scratchpad (no system loaded).
   */
  reload(): void {
    const systemId = this.requestedSystemId;
    if (!systemId) return;
    this.fetch(systemId);
  }

  private fetch(systemId: string): void {
    const scope = this.workspace.captureRequestScope();
    this.request?.unsubscribe();
    this.request = this.canonical.getSystemFlowManifest(systemId).subscribe((manifest) => {
      // Guard against a system switch landing before this response.
      if (
        this.requestedSystemId === systemId &&
        this.workspace.isRequestScopeCurrent(scope)
      ) {
        this._manifest.set(manifest);
      }
    });
  }

  unitFor(nodeId: string | null | undefined): FlowManifestUnit | null {
    if (!nodeId) return null;
    return this.unitsById().get(nodeId) ?? null;
  }

  statusFor(nodeId: string | null | undefined): NodeRuntimeStatus | null {
    const unit = this.unitFor(nodeId);
    if (!unit?.runtime_status) return null;
    return { status: unit.runtime_status, operational: Boolean(unit.operational) };
  }
}
