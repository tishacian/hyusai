import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Output,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ApiService } from '@app/core/api.service';
import { GlyphComponent, TagComponent, type CkTagTone } from '@app/shared/cockpit';
import { CaptureEngine, type CaptureSessionInfo } from '../capture-engine';
import { CaptureFilSettingsComponent } from '../capture-fil-settings.component';

interface DashboardSession extends CaptureSessionInfo {
  last_activity?: string | null;
  summary_short?: string | null;
  open_questions_count?: number | null;
  archived?: boolean | null;
}

/**
 * Dashboard surface (Phase 5) — entry point of the autonomous flow: recent
 * sessions to resume and a "Nouvelle capture" CTA. Reuses the existing
 * {@link ApiService.listCaptureSessions}. Resuming a session binds it to the
 * shared {@link CaptureEngine}; the shell routes to the right surface.
 */
@Component({
  selector: 'app-capture-fil-dashboard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [GlyphComponent, TagComponent, CaptureFilSettingsComponent],
  template: `
    <div style="display:flex; flex-direction:column; gap:20px;">
      <div style="display:flex; align-items:center; gap:16px; flex-wrap:wrap;">
        <div>
          <span class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">
            Capture · Connaissances
          </span>
          <h2 style="margin:6px 0 0; font-size:22px; font-weight:680; color:var(--ck-fg-1);">Vos séances de capture</h2>
        </div>
        <div style="margin-left:auto; display:flex; align-items:center; gap:8px;">
          @if (hasSystem()) {
            <button
              type="button"
              (click)="settingsOpen.set(true)"
              title="Paramètres de capture du système"
              style="display:inline-flex; align-items:center; justify-content:center; padding:9px; border-radius:var(--ck-radius-md); border:1px solid var(--ck-stroke-2); background:transparent; color:var(--ck-fg-3); cursor:pointer;"
            >
              <ck-glyph name="sliders" [size]="14" color="currentColor" />
            </button>
          }
          <button
            type="button"
            (click)="newCapture.emit()"
            style="display:inline-flex; align-items:center; gap:7px; padding:9px 16px; border-radius:var(--ck-radius-md); border:none; cursor:pointer; font-size:13px; font-weight:600; background:color-mix(in oklab, var(--ck-signal-cool) 88%, transparent); color:var(--ck-on-signal);"
          >
            <ck-glyph name="bolt" [size]="14" color="currentColor" /> Nouvelle capture
          </button>
        </div>
      </div>

      @if (settingsOpen()) {
        <app-capture-fil-settings (closed)="settingsOpen.set(false)" />
      }

      @if (loading()) {
        <div class="ck-surface" style="border-radius:var(--ck-radius-md); padding:24px; text-align:center; color:var(--ck-fg-4); font-size:13px;">
          Chargement des séances…
        </div>
      } @else if (sessions().length === 0) {
        <div class="ck-surface" style="border-radius:var(--ck-radius-md); padding:28px; text-align:center; display:flex; flex-direction:column; gap:8px; align-items:center;">
          <ck-glyph name="ledger" [size]="22" color="var(--ck-fg-4)" />
          <div style="font-size:14px; color:var(--ck-fg-2); font-weight:550;">Aucune séance pour le moment</div>
          <div style="font-size:12.5px; color:var(--ck-fg-4); max-width:42ch;">
            Démarrez une nouvelle capture pour collecter la connaissance d'un expert sur un seul fil horodaté.
          </div>
        </div>
      } @else {
        <div style="display:flex; flex-direction:column; gap:10px;">
          @for (s of sessions(); track s.id) {
            <div
              class="ck-surface"
              style="border-radius:var(--ck-radius-lg); padding:16px 18px; display:flex; align-items:center; gap:16px;"
              [style.opacity]="s.archived ? '0.62' : '1'"
            >
              <ck-glyph name="ledger" [size]="18" color="var(--ck-fg-3)" />
              <button
                type="button"
                (click)="openSession.emit(s)"
                style="flex:1; min-width:0; text-align:left; cursor:pointer; background:none; border:none; padding:0; display:flex; align-items:center; gap:16px;"
              >
                <div style="flex:1; min-width:0;">
                  <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
                    <span style="font-size:14px; font-weight:600; color:var(--ck-fg-1);">{{ s.title || 'Séance sans titre' }}</span>
                    @if (s.archived) {
                      <ck-tag tone="neutral" variant="soft">Archivée</ck-tag>
                    } @else {
                      <ck-tag [tone]="statusTone(s.status)" variant="soft">{{ statusLabel(s.status) }}</ck-tag>
                    }
                  </div>
                  <div style="font-size:12.5px; color:var(--ck-fg-4); margin-top:4px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:72ch;">
                    {{ s.summary_short || s.objective || '—' }}
                  </div>
                </div>
                @if (s.open_questions_count) {
                  <span class="ck-mono" style="font-size:10px; color:var(--ck-signal-warn);">{{ s.open_questions_count }} ?</span>
                }
              </button>
              @if (s.archived) {
                <button
                  type="button"
                  (click)="unarchive(s)"
                  [disabled]="busyId() === s.id"
                  title="Restaurer cette séance dans la liste active"
                  style="appearance:none; display:inline-flex; align-items:center; gap:6px; padding:6px 11px; border-radius:var(--ck-radius-md); font-size:12px; cursor:pointer; border:1px solid var(--ck-stroke-2); background:var(--ck-bg-base); color:var(--ck-fg-2);"
                >
                  <ck-glyph name="orbit" [size]="13" color="currentColor" /> Désarchiver
                </button>
              } @else {
                <button
                  type="button"
                  (click)="archive(s)"
                  [disabled]="busyId() === s.id"
                  title="Archiver cette séance (masquée de la liste active, restaurable — aucune suppression)"
                  style="appearance:none; display:inline-flex; align-items:center; gap:6px; padding:6px 11px; border-radius:var(--ck-radius-md); font-size:12px; cursor:pointer; border:1px solid var(--ck-stroke-2); background:var(--ck-bg-base); color:var(--ck-fg-3);"
                >
                  <ck-glyph name="layers" [size]="13" color="currentColor" /> Archiver
                </button>
              }
              <ck-glyph name="arrow-right" [size]="14" color="var(--ck-fg-4)" />
            </div>
          }
        </div>
      }

      @if (actionError()) {
        <div style="font-size:12px; color:var(--ck-signal-neg);">{{ actionError() }}</div>
      }
    </div>
  `,
})
export class CaptureFilDashboardComponent {
  private readonly api = inject(ApiService);
  private readonly engine = inject(CaptureEngine);
  private readonly destroyRef = inject(DestroyRef);

  @Output() newCapture = new EventEmitter<void>();
  @Output() openSession = new EventEmitter<CaptureSessionInfo>();

  protected readonly loading = signal(true);
  protected readonly sessions = signal<DashboardSession[]>([]);
  /** Id of the session whose archive/unarchive round-trip is in flight. */
  protected readonly busyId = signal<string | null>(null);
  protected readonly actionError = signal<string | null>(null);
  /** Paramètres de capture (gear) — system-scoped entry only. */
  protected readonly settingsOpen = signal(false);
  protected readonly hasSystem = this.engine.systemId;

  constructor() {
    this.reload();
  }

  private reload(): void {
    const systemId = this.engine.systemId();
    this.loading.set(true);
    this.api
      .listCaptureSessions(undefined, undefined, systemId ?? undefined, true)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (payload) => {
          const rows = (payload as { sessions?: DashboardSession[] } | null)?.sessions ?? [];
          // Scoped entry: drop sessions bound to a different system (the API
          // filter also does this, but unscoped legacy rows can leak through).
          const scoped = systemId
            ? rows.filter((r) => !r.system_id || r.system_id === systemId)
            : rows;
          this.sessions.set(scoped);
          this.loading.set(false);
        },
        error: () => this.loading.set(false),
      });
  }

  protected archive(s: DashboardSession): void {
    this.setArchived(s, true);
  }

  protected unarchive(s: DashboardSession): void {
    this.setArchived(s, false);
  }

  private setArchived(s: DashboardSession, archived: boolean): void {
    if (this.busyId()) return;
    this.busyId.set(s.id);
    this.actionError.set(null);
    const call$ = archived
      ? this.api.archiveCaptureSession(s.id)
      : this.api.unarchiveCaptureSession(s.id);
    call$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: () => {
        // Optimistic flip so the row updates instantly, then refresh to stay in
        // sync with the server (ordering, archived_at, …).
        this.sessions.update((rows) =>
          rows.map((r) => (r.id === s.id ? { ...r, archived } : r)),
        );
        this.busyId.set(null);
        this.reload();
      },
      error: () => {
        this.actionError.set(
          archived
            ? "Impossible d'archiver la séance — réessayez."
            : 'Impossible de désarchiver la séance — réessayez.',
        );
        this.busyId.set(null);
      },
    });
  }

  protected statusLabel(status: string | null | undefined): string {
    const s = (status || '').toLowerCase();
    if (s === 'completed' || s === 'published') return 'Terminée';
    if (s === 'in_progress' || s === 'active' || s === 'running') return 'En cours';
    if (s === 'archived') return 'Archivée';
    if (s === 'draft' || s === 'planning') return 'Brouillon';
    return status || 'Inconnu';
  }

  protected statusTone(status: string | null | undefined): CkTagTone {
    const s = (status || '').toLowerCase();
    if (s === 'completed' || s === 'published') return 'pos';
    if (s === 'in_progress' || s === 'active' || s === 'running') return 'cool';
    if (s === 'archived') return 'neutral';
    return 'warn';
  }
}
