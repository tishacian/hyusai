import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { CkPanelComponent } from '@app/shared/cockpit/panel.component';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import { HelpService } from '@app/core/help.service';
import {
  HELP_GUIDE_IDS,
  HelpOverlayService,
} from './help-overlay.service';

interface GuideBody {
  id: string;
  title: string;
  paragraphs: string[];
}

/**
 * Global help side-panel (L16). Mounted once at the app root so Cockpit
 * and Work share the same Escape / focus behaviour via `app-panel-host`.
 */
@Component({
  selector: 'app-help-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CkPanelComponent],
  template: `
    <ck-panel
      [open]="overlay.isOpen()"
      (openChange)="onOpenChange($event)"
      position="side"
      [title]="i18n.t('experience.help.panel.title')"
      width="420px"
      data-testid="help-panel"
    >
      <div class="help-panel">
        <div class="help-panel-toolbar">
          <button
            type="button"
            class="help-panel-full"
            data-testid="help-panel-full-page"
            (click)="overlay.openFullPage()"
          >
            {{ i18n.t('experience.help.panel.open_full') }}
          </button>
        </div>

        <label class="help-panel-search">
          <span class="sr-only">{{ i18n.t('experience.help.panel.search') }}</span>
          <input
            type="search"
            data-testid="help-panel-search"
            [placeholder]="i18n.t('experience.help.panel.search')"
            [value]="overlay.query()"
            (input)="onSearch($event)"
          />
        </label>

        @if (filteredGuides().length > 1 || overlay.query().trim()) {
          <ul class="help-panel-hits" role="listbox" [attr.aria-label]="i18n.t('experience.help.panel.search')">
            @for (id of filteredGuides(); track id) {
              <li>
                <button
                  type="button"
                  [attr.aria-selected]="overlay.guideId() === id"
                  [class.help-panel-hit-active]="overlay.guideId() === id"
                  (click)="overlay.selectGuide(id)"
                >
                  {{ guideLabel(id) }}
                </button>
              </li>
            }
          </ul>
        }

        @if (guide(); as g) {
          <p class="help-panel-tag ck-mono">{{ i18n.t('experience.help.panel.guide_tag', { name: guideLabel(g.id) }) }}</p>
          <!-- The guide may be in another language than the interface (WCAG 3.1.2). -->
          <h3 [attr.lang]="help.language()">{{ g.title }}</h3>
          @for (p of g.paragraphs; track $index) {
            <p [attr.lang]="help.language()">{{ p }}</p>
          }
        } @else if (error()) {
          <p role="alert">{{ i18n.t('experience.adoption.guide_error') }}</p>
          <button type="button" class="help-panel-retry" (click)="load()">
            {{ i18n.t('common.retry') }}
          </button>
        } @else {
          <p role="status">{{ i18n.t('common.loading') }}</p>
        }

        @if (seeAlso().length) {
          <section class="help-panel-also" [attr.aria-label]="i18n.t('experience.help.panel.see_also')">
            <h4>{{ i18n.t('experience.help.panel.see_also') }}</h4>
            <ul>
              @for (id of seeAlso(); track id) {
                <li>
                  <button type="button" (click)="overlay.selectGuide(id)">
                    {{ guideLabel(id) }}
                  </button>
                </li>
              }
            </ul>
          </section>
        }

        @if (overlay.origin(); as origin) {
          <p class="help-panel-escape ck-mono">
            {{ i18n.t('experience.help.panel.escape', { page: origin.label }) }}
          </p>
        }
      </div>
    </ck-panel>
  `,
  styles: [`
    :host { display: contents; }
    .help-panel {
      display: flex;
      flex-direction: column;
      gap: 14px;
      min-height: 100%;
    }
    .help-panel-toolbar {
      display: flex;
      justify-content: flex-end;
    }
    .help-panel-full {
      border: 0;
      background: transparent;
      color: var(--ck-signal-cool, #67d5f6);
      font: 700 11px/1.3 var(--ck-font-mono, ui-monospace, monospace);
      letter-spacing: 0.04em;
      text-decoration: underline;
      cursor: pointer;
      padding: 0;
    }
    .help-panel-search input {
      width: 100%;
      box-sizing: border-box;
      min-height: 36px;
      padding: 8px 10px;
      border-radius: 4px;
      border: 1px solid var(--ck-stroke-2);
      background: var(--ck-bg-inset);
      color: var(--ck-fg-1);
      font-size: 13px;
    }
    .help-panel-hits {
      list-style: none;
      margin: 0;
      padding: 0;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .help-panel-hits button,
    .help-panel-also button,
    .help-panel-retry {
      border: 0;
      background: transparent;
      color: var(--ck-signal-cool, #67d5f6);
      text-align: left;
      cursor: pointer;
      padding: 4px 0;
      font-size: 13px;
      text-decoration: underline;
    }
    .help-panel-hit-active {
      color: var(--ck-fg-1) !important;
      font-weight: 700;
      text-decoration: none !important;
    }
    .help-panel-tag {
      margin: 0;
      font-size: 10px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--ck-fg-4);
    }
    h3 {
      margin: 0;
      font-size: 22px;
      font-weight: 650;
      letter-spacing: -0.02em;
      color: var(--ck-fg-1);
    }
    .help-panel > p {
      margin: 0;
      line-height: 1.65;
      color: var(--ck-fg-2);
      font-size: 14px;
    }
    .help-panel-also h4 {
      margin: 8px 0 6px;
      font-size: 12px;
      font-weight: 700;
      color: var(--ck-fg-3);
    }
    .help-panel-also ul {
      list-style: none;
      margin: 0;
      padding: 0;
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    .help-panel-escape {
      margin-top: auto;
      padding-top: 16px;
      font-size: 10px;
      letter-spacing: 0.06em;
      color: var(--ck-fg-4);
    }
    .sr-only {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }
  `],
})
export class HelpPanelComponent {
  readonly overlay = inject(HelpOverlayService);
  readonly i18n = inject(I18nService);
  protected readonly help = inject(HelpService);
  private readonly api = inject(ApiService);

  readonly guide = signal<GuideBody | null>(null);
  readonly error = signal(false);

  readonly filteredGuides = computed(() => {
    const q = this.overlay.query().trim().toLowerCase();
    if (!q) return [...HELP_GUIDE_IDS];
    return HELP_GUIDE_IDS.filter((id) => {
      const label = this.guideLabel(id).toLowerCase();
      const body = this.guide();
      const hay = body?.id === id
        ? `${label} ${body.title} ${body.paragraphs.join(' ')}`.toLowerCase()
        : label;
      return hay.includes(q);
    });
  });

  readonly seeAlso = computed(() => {
    const current = this.overlay.guideId();
    return HELP_GUIDE_IDS.filter((id) => id !== current).slice(0, 4);
  });

  constructor() {
    effect(() => {
      this.overlay.isOpen();
      this.overlay.guideId();
      this.help.language();
      if (this.overlay.isOpen()) this.load();
    });
  }

  guideLabel(id: string): string {
    const key = `experience.help.guide.${id}`;
    const label = this.i18n.t(key);
    return label === key ? id : label;
  }

  onSearch(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    this.overlay.setQuery(value);
    const hits = this.filteredGuides();
    if (hits.length === 1 && hits[0] !== this.overlay.guideId()) {
      this.overlay.selectGuide(hits[0]!);
    }
  }

  onOpenChange(open: boolean): void {
    if (!open) this.overlay.close();
  }

  load(): void {
    const id = this.overlay.guideId();
    const language = this.help.language();
    this.error.set(false);
    this.guide.set(null);
    this.api
      .get<{ title: string; paragraphs: string[] }>(
        `/help-content/guides/${encodeURIComponent(id)}`,
        { language },
      )
      .subscribe({
        next: (v) => {
          if (id === this.overlay.guideId() && language === this.help.language()) {
            this.guide.set({ id, title: v.title, paragraphs: v.paragraphs });
          }
        },
        error: () => {
          if (id === this.overlay.guideId() && language === this.help.language()) {
            this.error.set(true);
          }
        },
      });
  }
}
