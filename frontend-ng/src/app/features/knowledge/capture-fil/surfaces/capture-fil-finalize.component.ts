import { ChangeDetectionStrategy, Component, EventEmitter, Output, inject, signal } from '@angular/core';
import type { CaptureShareLevelItem } from '@app/core/api.service';
import { GlyphComponent } from '@app/shared/cockpit';
import { CaptureEngine } from '../capture-engine';
import { CaptureTriageDialogComponent } from '../triage-dialog.component';

/**
 * Finalisation surface (Option A) — hosts the end-of-capture triage then
 * triggers {@link CaptureEngine.finalize} (generate the report) and routes the
 * shell onward to the review fiche once the proposal is ready. Indexing stays a
 * background concern surfaced on the report; the real KB publication is a
 * separate downstream surface (`app-capture-fil-publish`).
 */
@Component({
  selector: 'app-capture-fil-finalize',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [GlyphComponent, CaptureTriageDialogComponent],
  template: `
    <div style="max-width:780px;">
      @if (finalizing()) {
        <div
          class="ck-surface"
          style="border-radius:var(--ck-radius-lg); padding:40px 28px; display:flex; flex-direction:column; align-items:center; gap:14px; text-align:center;"
        >
          <span class="ck-live-dot violet"></span>
          <div style="font-size:16px; font-weight:600; color:var(--ck-fg-1);">
            Fin de séance · génération du rapport…
          </div>
          <div style="font-size:13px; color:var(--ck-fg-4); max-width:48ch; line-height:1.5;">
            {{ engine.finalizeStage().message || 'Restructuration de la séance en fiche de connaissance.' }}
            L'indexation lourde démarrera en arrière-plan à l'ouverture du rapport.
          </div>
          @if (error()) {
            <div style="display:flex; align-items:center; gap:8px; color:var(--ck-signal-neg); font-size:12.5px; margin-top:6px;">
              <ck-glyph name="warn" [size]="14" color="currentColor" /> {{ error() }}
              <button
                type="button"
                (click)="retry()"
                style="border:1px solid var(--ck-stroke-2); background:transparent; color:var(--ck-fg-2); border-radius:var(--ck-radius-sm); padding:4px 10px; cursor:pointer; font-size:12px;"
              >
                Réessayer
              </button>
            </div>
          }
        </div>
      } @else {
        <app-capture-triage-dialog [open]="true" (confirm)="onConfirm($event)" />
      }
    </div>
  `,
})
export class CaptureFilFinalizeComponent {
  protected readonly engine = inject(CaptureEngine);

  /** Emitted once the proposal (report) is ready — the shell opens the review fiche. */
  @Output() finalized = new EventEmitter<void>();

  protected readonly finalizing = signal(false);
  protected readonly error = signal<string | null>(null);
  private lastItems: CaptureShareLevelItem[] = [];

  constructor() {
    if (this.engine.documents().length === 0) void this.engine.loadDocuments();
  }

  protected async onConfirm(items: CaptureShareLevelItem[]): Promise<void> {
    this.lastItems = items;
    await this.run();
  }

  protected retry(): void {
    void this.run();
  }

  private async run(): Promise<void> {
    this.finalizing.set(true);
    this.error.set(null);
    // Persist the triage first, then finalize over the LIVE WS so the backend
    // streams capture.finalize.progress stages to the banner; close the realtime
    // leg only once the proposal is ready (indexing continues server-side).
    await this.engine.setShareLevels(this.lastItems);
    const proposalId = await this.engine.finalize();
    this.engine.disconnect();
    if (proposalId || this.engine.finalizeStage().stage === 'done') {
      this.finalized.emit();
      return;
    }
    this.error.set(this.engine.lastError() || 'La génération du rapport a échoué.');
  }
}
