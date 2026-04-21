import { Injectable, signal } from '@angular/core';

/**
 * `ZoomContextService` — the shared semantic-zoom context that threads
 * Capability × System × Run identifiers across the cockpit so every
 * breadcrumb, palette, and navigation shortcut can zoom without losing
 * the operator's focus.
 *
 * Pages call the respective `setCurrent*` setters when they load a
 * detail view; the breadcrumb consumes the signals to build contextual
 * hrefs (e.g. "System" level points to `/systems/{current}` instead of
 * `/systems` if a system is in scope).
 */
@Injectable({ providedIn: 'root' })
export class ZoomContextService {
  readonly capabilityId = signal<string | null>(null);
  readonly systemId = signal<string | null>(null);
  readonly runId = signal<string | null>(null);

  setCurrentCapability(id: string | null): void {
    this.capabilityId.set(id);
  }

  setCurrentSystem(id: string | null): void {
    this.systemId.set(id);
    // Switching systems invalidates the run scope.
    if (id === null) this.runId.set(null);
  }

  setCurrentRun(id: string | null): void {
    this.runId.set(id);
  }

  /** Called on hard navigation resets (e.g. workspace switch). */
  clear(): void {
    this.capabilityId.set(null);
    this.systemId.set(null);
    this.runId.set(null);
  }
}
