import { DOCUMENT } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { NEW_VERSION_CHECK_MS, newVersionAvailable, type BuildInfo } from '@app/core/new-version';
import { catchError, of } from 'rxjs';

/**
 * Invites the reader to refresh when a new Agentium version is served.
 * Checks when the tab becomes visible again and every ten minutes; never
 * reloads by itself.
 */
@Component({
  selector: 'app-new-version-notice',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (available() && !dismissed()) {
      <div class="notice" role="status" aria-live="polite" data-testid="new-version-notice">
        <p>{{ i18n.t('common.new_version.body') }}</p>
        <div class="actions">
          <button type="button" class="primary" (click)="refresh()">{{ i18n.t('common.new_version.refresh') }}</button>
          <button type="button" (click)="dismissed.set(true)">{{ i18n.t('common.new_version.later') }}</button>
        </div>
      </div>
    }
  `,
  styles: [`
    .notice {
      position: fixed; inset-inline-end: var(--ck-space-4); inset-block-end: var(--ck-space-4); z-index: 1300;
      max-width: min(420px, calc(100vw - 2 * var(--ck-space-4)));
      padding: var(--ck-space-3) var(--ck-space-4);
      border: 1px solid var(--ck-status-info-line); border-radius: var(--ck-radius-md);
      background: var(--ck-bg-panel-hi); color: var(--ck-fg-1);
    }
    p { margin: 0 0 var(--ck-space-2); font-size: 13px; }
    .actions { display: flex; gap: var(--ck-space-2); flex-wrap: wrap; }
    button { padding: var(--ck-space-1) var(--ck-space-3); border: 1px solid var(--ck-stroke-3); border-radius: var(--ck-radius-sm); background: transparent; color: inherit; }
    button.primary { background: var(--ck-cta-bg, var(--ck-primary)); border-color: var(--ck-cta-bg, var(--ck-primary)); color: var(--ck-cta-fg); }
    button:focus-visible { outline: 2px solid var(--ck-primary); outline-offset: 2px; }
  `],
})
export class NewVersionNoticeComponent {
  readonly i18n = inject(I18nService);
  private readonly http = inject(HttpClient);
  private readonly document = inject(DOCUMENT);
  readonly available = signal(false);
  readonly dismissed = signal(false);
  private loaded: BuildInfo | null = null;

  constructor() {
    const view = this.document.defaultView;
    if (!view) return;
    this.read((info) => { this.loaded = info; });
    const check = () => { if (!this.document.hidden && this.loaded) this.read((info) => this.available.set(newVersionAvailable(this.loaded, info))); };
    const timer = view.setInterval(check, NEW_VERSION_CHECK_MS);
    this.document.addEventListener('visibilitychange', check);
    inject(DestroyRef).onDestroy(() => {
      view.clearInterval(timer);
      this.document.removeEventListener('visibilitychange', check);
    });
  }

  private read(next: (info: BuildInfo | null) => void): void {
    this.http
      .get<BuildInfo>('/build-info.json', { params: { t: String(Date.now()) }, headers: { 'Cache-Control': 'no-store' } })
      .pipe(catchError(() => of(null)))
      .subscribe(next);
  }

  refresh(): void {
    this.document.defaultView?.location.reload();
  }
}
