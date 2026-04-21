import { Injectable, signal } from '@angular/core';

/**
 * `ZoomContextService` — the shared semantic-zoom context that threads
 * Capability × System × Run × Skill identifiers across the cockpit so every
 * breadcrumb, palette, and navigation shortcut can zoom without losing
 * the operator's focus.
 *
 * Canonical hierarchy order (see docs/mental-model.md §5bis.2):
 *   Portfolio › Capability › System › Run › Skill
 *
 * Rationale: a Run is an *instance* of a System, and a Skill is a *component
 * invocation within a Run*. Skill therefore sits beneath Run in the zoom
 * chain, not above it.
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
  readonly skillId = signal<string | null>(null);

  setCurrentCapability(id: string | null): void {
    this.capabilityId.set(id);
    if (id === null) {
      this.systemId.set(null);
      this.runId.set(null);
      this.skillId.set(null);
    }
  }

  setCurrentSystem(id: string | null): void {
    this.systemId.set(id);
    if (id === null) {
      this.runId.set(null);
      this.skillId.set(null);
    }
  }

  setCurrentRun(id: string | null): void {
    this.runId.set(id);
    if (id === null) this.skillId.set(null);
  }

  setCurrentSkill(id: string | null): void {
    this.skillId.set(id);
  }

  /** Called on hard navigation resets (e.g. workspace switch). */
  clear(): void {
    this.capabilityId.set(null);
    this.systemId.set(null);
    this.runId.set(null);
    this.skillId.set(null);
  }
}
