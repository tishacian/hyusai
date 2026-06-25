/**
 * `FlowCatalogService` — the dynamic palette source (P3).
 *
 * Projects the live `/skills` catalog (each Skill carrying its typed
 * `input_schema`) into `PaletteItem`s the palette can render and drop. The
 * structural graph primitives (source / sink / decision / fork / join / loop)
 * stay client-defined in `DEFAULT_PALETTE` — they are graph semantics, not
 * catalog entries.
 *
 * Read-only: it only consumes `CanonicalApiService.listSkills()` and shapes
 * the result. The single in-flight request is shared + replayed so every
 * palette instance reuses one fetch.
 */
import { Injectable, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { map, shareReplay } from 'rxjs';
import { CanonicalApiService } from '@app/core/canonical-api.service';
import { skillToPaletteItem, type PaletteItem } from './flow.types';

@Injectable({ providedIn: 'root' })
export class FlowCatalogService {
  private readonly canonical = inject(CanonicalApiService);

  private readonly skills$ = this.canonical.listSkills().pipe(
    map((skills) =>
      skills
        .map((skill) => skillToPaletteItem(skill))
        .sort((a, b) => a.label.localeCompare(b.label)),
    ),
    shareReplay({ bufferSize: 1, refCount: false }),
  );

  /** Skill palette entries, async-loaded ([] until the first response). */
  readonly skillItems = toSignal(this.skills$, {
    initialValue: [] as PaletteItem[],
  });
}
