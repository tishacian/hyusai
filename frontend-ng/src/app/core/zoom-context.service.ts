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
  readonly capabilityLabel = signal<string | null>(null);
  readonly systemId = signal<string | null>(null);
  readonly systemLabel = signal<string | null>(null);
  readonly runId = signal<string | null>(null);
  readonly runLabel = signal<string | null>(null);
  readonly skillId = signal<string | null>(null);
  readonly skillLabel = signal<string | null>(null);
  readonly contextId = signal<string | null>(null);
  readonly contextLabel = signal<string | null>(null);

  setCurrentCapability(id: string | null, label?: string | null): void {
    this.capabilityId.set(id);
    this.capabilityLabel.set(label ?? null);
    if (id === null) {
      this.systemId.set(null);
      this.systemLabel.set(null);
      this.runId.set(null);
      this.runLabel.set(null);
      this.skillId.set(null);
      this.skillLabel.set(null);
    }
  }

  setCurrentSystem(id: string | null, label?: string | null): void {
    this.systemId.set(id);
    this.systemLabel.set(label ?? null);
    if (id === null) {
      this.runId.set(null);
      this.runLabel.set(null);
      this.skillId.set(null);
      this.skillLabel.set(null);
    }
  }

  setCurrentRun(id: string | null, label?: string | null): void {
    this.runId.set(id);
    this.runLabel.set(label ?? null);
    if (id === null) {
      this.skillId.set(null);
      this.skillLabel.set(null);
    }
  }

  setCurrentSkill(id: string | null, label?: string | null): void {
    this.skillId.set(id);
    this.skillLabel.set(label ?? null);
  }

  setCurrentContext(id: string | null, label?: string | null): void {
    this.contextId.set(id);
    this.contextLabel.set(label ?? null);
  }

  /** Called on hard navigation resets (e.g. workspace switch). */
  clear(): void {
    this.capabilityId.set(null);
    this.capabilityLabel.set(null);
    this.systemId.set(null);
    this.systemLabel.set(null);
    this.runId.set(null);
    this.runLabel.set(null);
    this.skillId.set(null);
    this.skillLabel.set(null);
    this.contextId.set(null);
    this.contextLabel.set(null);
  }
}
