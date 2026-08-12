import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Output,
  inject,
  signal,
} from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { CanonicalApiService, type System } from '@app/core/canonical-api.service';
import { GlyphComponent } from '@app/shared/cockpit';
import { CaptureEngine, type CaptureFilLayout } from './capture-engine';

/**
 * Paramètres de capture (niveau système) — small panel opened from the
 * dashboard gear. Single setting for now: "Disposition du Fil" (priorité
 * pièces jointes vs priorité transcript), persisted in
 * `System.settings.capture.fil_layout` via PATCH /systems/{id}. Settings are
 * MERGED (never overwrite other keys). Extensible entry point for future
 * capture-level system parameters.
 */
@Component({
  selector: 'app-capture-fil-settings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [GlyphComponent],
  template: `
    <div
      style="position:fixed; inset:0; z-index:60; display:grid; place-items:center; background:color-mix(in oklab, var(--ck-bg-base) 62%, transparent);"
      (click)="closed.emit()"
    >
      <div
        class="ck-surface"
        (click)="$event.stopPropagation()"
        style="width:min(560px, calc(100vw - 48px)); border-radius:var(--ck-radius-lg); border:1px solid var(--ck-stroke-3); box-shadow:var(--ck-shadow-card); padding:18px 20px; display:flex; flex-direction:column; gap:16px; background:var(--ck-bg-panel-hi);"
      >
        <div style="display:flex; align-items:center; gap:9px;">
          <ck-glyph name="sliders" [size]="14" color="var(--ck-signal-cool)" />
          <span class="ck-mono" style="font-size:10.5px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-3);">
            {{ i18n.t('capture.settings.title') }}
          </span>
          <button
            type="button"
            (click)="closed.emit()"
            [title]="i18n.t('common.close')"
            style="margin-left:auto; border:none; background:transparent; color:var(--ck-fg-4); cursor:pointer; display:inline-flex; padding:4px;"
          >
            <ck-glyph name="x" [size]="13" color="currentColor" />
          </button>
        </div>

        <div style="display:flex; flex-direction:column; gap:8px;">
          <span style="font-size:13px; font-weight:600; color:var(--ck-fg-1);">{{ i18n.t('capture.settings.layout') }}</span>
          <span style="font-size:12px; color:var(--ck-fg-4); line-height:1.45;">
            {{ i18n.t('capture.settings.layout_hint') }}
          </span>
        </div>

        @if (loading()) {
          <div style="font-size:12.5px; color:var(--ck-fg-4); padding:8px 0;">{{ i18n.t('capture.settings.loading') }}</div>
        } @else {
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">
            <!-- Priorité pièces jointes : scène large au centre, fil à droite -->
            <button type="button" class="cfs-card" [class.is-active]="selected() === 'documents'" (click)="selected.set('documents')">
              <span class="cfs-schema">
                <span style="width:14%;" class="cfs-box"></span>
                <span style="flex:1;" class="cfs-box cfs-box-hi"></span>
                <span style="width:26%;" class="cfs-box"></span>
              </span>
              <span style="font-size:12.5px; font-weight:600; color:var(--ck-fg-1);">{{ i18n.t('capture.settings.layout_documents') }}</span>
              <span style="font-size:11px; color:var(--ck-fg-4); line-height:1.4;">
                {{ i18n.t('capture.settings.layout_documents_hint') }}
              </span>
              <span class="ck-mono" style="font-size:9px; color:var(--ck-fg-5);">{{ i18n.t('capture.settings.default') }}</span>
            </button>
            <!-- Priorité transcript : fil au centre, scène à droite -->
            <button type="button" class="cfs-card" [class.is-active]="selected() === 'transcript'" (click)="selected.set('transcript')">
              <span class="cfs-schema">
                <span style="width:14%;" class="cfs-box"></span>
                <span style="flex:1;" class="cfs-box"></span>
                <span style="width:26%;" class="cfs-box cfs-box-hi"></span>
              </span>
              <span style="font-size:12.5px; font-weight:600; color:var(--ck-fg-1);">{{ i18n.t('capture.settings.layout_transcript') }}</span>
              <span style="font-size:11px; color:var(--ck-fg-4); line-height:1.4;">
                {{ i18n.t('capture.settings.layout_transcript_hint') }}
              </span>
            </button>
          </div>
        }

        @if (feedback(); as fb) {
          <div
            style="display:flex; align-items:center; gap:7px; font-size:12px;"
            [style.color]="fb.tone === 'pos' ? 'var(--ck-signal-pos)' : 'var(--ck-signal-neg)'"
          >
            <ck-glyph [name]="fb.tone === 'pos' ? 'check' : 'warn'" [size]="12" color="currentColor" />
            {{ fb.text }}
          </div>
        }

        <div style="display:flex; justify-content:flex-end; gap:8px;">
          <button
            type="button"
            (click)="closed.emit()"
            style="padding:7px 13px; border-radius:var(--ck-radius-md); border:1px solid var(--ck-stroke-2); background:transparent; color:var(--ck-fg-3); cursor:pointer; font-size:12.5px; font-weight:550;"
          >
            {{ i18n.t('common.close') }}
          </button>
          <button
            type="button"
            (click)="save()"
            [disabled]="loading() || saving()"
            style="display:inline-flex; align-items:center; gap:6px; padding:7px 14px; border-radius:var(--ck-radius-md); border:none; cursor:pointer; font-size:12.5px; font-weight:600; background:color-mix(in oklab, var(--ck-signal-cool) 88%, transparent); color:var(--ck-on-signal);"
            [style.opacity]="loading() || saving() ? 0.6 : 1"
          >
            <ck-glyph name="check" [size]="12" color="currentColor" />
            {{ saving() ? i18n.t('capture.settings.saving') : i18n.t('common.save') }}
          </button>
        </div>
      </div>
    </div>
  `,
  styles: [
    `
      .cfs-card {
        appearance: none;
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: 8px;
        text-align: left;
        padding: 12px;
        border-radius: var(--ck-radius-md);
        border: 1px solid var(--ck-stroke-2);
        background: var(--ck-bg-inset);
        cursor: pointer;
        font-family: var(--ck-font-sans);
      }
      .cfs-card:hover {
        background: var(--ck-tint-soft);
      }
      .cfs-card.is-active {
        border-color: var(--ck-signal-cool);
        box-shadow: inset 0 0 0 1px var(--ck-signal-cool);
      }
      .cfs-schema {
        display: flex;
        gap: 3px;
        width: 100%;
        height: 34px;
      }
      .cfs-box {
        border-radius: 3px;
        border: 1px solid var(--ck-stroke-3);
        background: var(--ck-bg-panel);
      }
      .cfs-box-hi {
        background: color-mix(in oklab, var(--ck-signal-cool) 22%, var(--ck-bg-panel));
        border-color: color-mix(in oklab, var(--ck-signal-cool) 50%, var(--ck-stroke-3));
      }
    `,
  ],
})
export class CaptureFilSettingsComponent {
  readonly i18n = inject(I18nService);

  private readonly canonicalApi = inject(CanonicalApiService);
  private readonly engine = inject(CaptureEngine);
  private readonly destroyRef = inject(DestroyRef);

  @Output() closed = new EventEmitter<void>();

  protected readonly loading = signal(true);
  protected readonly saving = signal(false);
  protected readonly selected = signal<CaptureFilLayout>('documents');
  protected readonly feedback = signal<{ tone: 'pos' | 'neg'; text: string } | null>(null);

  /** Loaded system snapshot — kept so the save merges its existing settings. */
  private system: System | null = null;

  constructor() {
    const systemId = this.engine.systemId();
    if (!systemId) {
      this.loading.set(false);
      return;
    }
    this.canonicalApi
      .getSystem(systemId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((sys) => {
        this.system = sys;
        const capture = (sys?.settings?.['capture'] ?? {}) as Record<string, unknown>;
        this.selected.set(capture['fil_layout'] === 'transcript' ? 'transcript' : 'documents');
        this.loading.set(false);
      });
  }

  protected save(): void {
    const systemId = this.engine.systemId();
    if (!systemId || this.saving()) return;
    this.saving.set(true);
    this.feedback.set(null);
    const existing = this.system?.settings ?? {};
    const capture =
      existing['capture'] && typeof existing['capture'] === 'object'
        ? (existing['capture'] as Record<string, unknown>)
        : {};
    // Merge, never overwrite: other settings keys (and other capture keys) survive.
    const settings = { ...existing, capture: { ...capture, fil_layout: this.selected() } };
    this.canonicalApi
      .updateSystem(systemId, { settings })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((sys) => {
        this.saving.set(false);
        if (sys) {
          this.system = sys;
          this.engine.setFilLayout(this.selected());
          this.feedback.set({ tone: 'pos', text: this.i18n.t('capture.settings.saved') });
        } else {
          this.feedback.set({ tone: 'neg', text: this.i18n.t('capture.settings.save_failed') });
        }
      });
  }
}
