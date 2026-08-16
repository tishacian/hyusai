import type { Type } from '@angular/core';
import {
  CERTIFIED_RENDERER_VERSION as CURRENT_RENDERER_VERSION,
  type ExperienceDocument,
  localizeDocument as localizeCurrentDocument,
} from './model';
import { ExperienceRuntimeHostComponent as CurrentRuntimeHostComponent } from './runtime-host.component';
import {
  CERTIFIED_RENDERER_VERSION as LEGACY_RENDERER_VERSION,
  localizeDocument as localizeLegacyDocument,
} from './v0_1/model';
import { ExperienceRuntimeHostComponent as LegacyRuntimeHostComponent } from './v0_1/runtime-host.component';

export { CURRENT_RENDERER_VERSION, LEGACY_RENDERER_VERSION };

// v0_1 snapshots the visual catalog shipped by 56a9c57. Its components carry
// only a version host attribute to prevent Angular style-scope collisions;
// transport/auth/idempotency deliberately remain in the shared runtime service.
export interface CertifiedExperienceRenderer {
  readonly version: string;
  readonly host: Type<unknown>;
  readonly localizeDocument: (raw: unknown, locale: string) => ExperienceDocument;
}

const RENDERERS = new Map<string, CertifiedExperienceRenderer>([
  [
    LEGACY_RENDERER_VERSION,
    {
      version: LEGACY_RENDERER_VERSION,
      host: LegacyRuntimeHostComponent,
      localizeDocument: localizeLegacyDocument,
    },
  ],
  [
    CURRENT_RENDERER_VERSION,
    {
      version: CURRENT_RENDERER_VERSION,
      host: CurrentRuntimeHostComponent,
      localizeDocument: localizeCurrentDocument,
    },
  ],
]);

/** Immutable Releases render only through a catalog explicitly known by this SPA. */
export function experienceRenderer(
  version: string | null | undefined,
): CertifiedExperienceRenderer | null {
  return version ? RENDERERS.get(version) ?? null : null;
}
