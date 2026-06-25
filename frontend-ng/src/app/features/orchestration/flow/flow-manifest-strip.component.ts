/**
 * `<app-flow-manifest-strip>` — a thin, read-only summary of the backend
 * runtime manifest (units / source / effective-config / latest-retrieval-
 * decision), shown as a compact status strip above the canvas.
 *
 * It is a pure view over `FlowManifestService`: it adds NO backend calls (the
 * shell already triggers the single deduped `ensureLoaded`, and the persistence
 * save path calls `reload()` — both land on the `manifest` signal this strip
 * reads, so it refreshes reactively after a save). All mapping lives in the
 * Angular-free `manifestToStripVm` so the component stays trivial.
 *
 * Gating mirrors Execute / Versions: the manifest is per-System, so the strip
 * shows only for a bound System (`manifest.systemId()` non-null); on the
 * `/orchestration` scratchpad it renders nothing.
 */
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
} from '@angular/core';
import { IconComponent } from '@app/shared/ui/icon.component';
import { FlowManifestService } from './flow-manifest.service';
import { manifestToStripVm } from './flow-manifest-strip.vm';

@Component({
  selector: 'app-flow-manifest-strip',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent],
  styleUrl: './flow-manifest-strip.component.scss',
  template: `
    @if (bound()) {
      @if (vm(); as v) {
        <div class="ck-manifest" role="status" aria-label="Runtime manifest summary">
          <span class="ck-manifest__eyebrow">
            <app-icon name="cpu" [size]="12" /> Runtime manifest
          </span>
          <span class="ck-manifest__name" [title]="v.systemName">{{ v.systemName }}</span>
          <span class="ck-manifest__sep" aria-hidden="true"></span>
          @for (chip of v.chips; track chip.key) {
            <span class="ck-manifest__chip" [attr.data-tone]="chip.tone" [title]="chip.title">
              <span class="ck-manifest__chip-label">{{ chip.label }}</span>
              <span class="ck-manifest__chip-value">{{ chip.value }}</span>
            </span>
          }
        </div>
      } @else {
        <div class="ck-manifest ck-manifest--muted" role="status">
          <span class="ck-manifest__eyebrow">
            <app-icon name="cpu" [size]="12" /> Runtime manifest
          </span>
          <span class="ck-manifest__hint">Loading…</span>
        </div>
      }
    }
  `,
})
export class FlowManifestStripComponent {
  private readonly manifest = inject(FlowManifestService);

  /** Per-System surface — hidden on the scratchpad (no systemId loaded). */
  protected readonly bound = computed(() => this.manifest.systemId() !== null);

  /** Reactively re-derives whenever the manifest signal changes (e.g. reload). */
  protected readonly vm = computed(() => manifestToStripVm(this.manifest.manifest()));
}
