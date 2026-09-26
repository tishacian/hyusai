import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  output,
} from '@angular/core';
import { Router, RouterLink, type UrlTree } from '@angular/router';
import { I18nService, type Locale } from '@app/core/i18n.service';
import { ThemeService } from '@app/core/theme.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { AuthStore } from '@app/store/auth.store';
import { ChatOverlayService } from '@app/features/chat/chat-overlay.service';
import { HelpOverlayService, helpPrefersPanel } from '@app/features/help/help-overlay.service';
import { platformBrand } from '@app/core/platform-brand';
import { canEditExperience } from './work-catalog';

/**
 * Shared 48 px Work chrome bar (L15): brand line, optional search,
 * help panel (L16), Chat ⌘J, locale, creator hand-off, avatar.
 */
@Component({
  selector: 'app-work-bar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  styleUrl: './work.scss',
  template: `
    <header class="xp-work-bar xp-work-global-bar" data-work-chrome="bar">
      <div class="xp-work-brand-line">
        @if (brand(); as identity) {
          <img
            class="xp-work-brand-image"
            [src]="themeMode() === 'light' ? identity.emblemLight || identity.emblem : identity.emblem"
            alt=""
          />
        } @else {
          <span class="xp-work-logo" aria-hidden="true">◇</span>
        }
        <strong>A Work</strong>
        <span class="xp-work-divider" aria-hidden="true"></span>
        <span>{{ workspace.current()?.name }}</span>
      </div>

      @if (showSearch()) {
        <label class="xp-work-search">
          <span class="sr-only">{{ i18n.t('experience.work.search') }}</span>
          <input
            type="search"
            [placeholder]="i18n.t('experience.work.search')"
            [value]="searchQuery()"
            (input)="searchChange.emit(inputValue($event))"
          />
        </label>
      }

      <div class="xp-work-actions">
        <button
          type="button"
          class="xp-work-btn xp-work-btn-icon"
          data-testid="work-bar-help"
          [title]="i18n.t('titlebar.help')"
          [attr.aria-label]="i18n.t('titlebar.help')"
          [attr.aria-pressed]="help.isOpen()"
          (click)="openHelp()"
        >?</button>

        <button
          type="button"
          class="xp-work-btn"
          [class.xp-work-btn-primary]="chat.isOpen()"
          [title]="i18n.t('titlebar.chat.tooltip')"
          [attr.aria-label]="i18n.t('titlebar.chat')"
          (click)="openChat()"
        >
          {{ i18n.t('titlebar.chat') }} ⌘J
        </button>

        <span class="xp-work-locales" role="group" [attr.aria-label]="i18n.t('experience.work.lang.label')">
          @for (locale of locales; track locale) {
            <button
              type="button"
              class="xp-work-btn"
              [attr.aria-pressed]="i18n.locale() === locale"
              [class.xp-work-btn-primary]="i18n.locale() === locale"
              (click)="i18n.setLocale(locale)"
            >
              {{ i18n.t(locale === 'fr' ? 'experience.work.lang.fr' : 'experience.work.lang.en') }}
            </button>
          }
        </span>

        @if (showCreator()) {
          <a class="xp-work-link xp-work-creator" [routerLink]="creatorHref()!">
            <span>{{ i18n.t('experience.work.author') }}</span>
            · {{ i18n.t(creatorLabelKey()) }} ↗
          </a>
        }

        <span class="xp-work-avatar" [attr.aria-label]="auth.email() || i18n.t('account.user_fallback')">
          {{ initials() }}
        </span>
      </div>
    </header>
  `,
})
export class WorkBarComponent {
  readonly i18n = inject(I18nService);
  readonly workspace = inject(WorkspaceService);
  readonly chat = inject(ChatOverlayService);
  readonly help = inject(HelpOverlayService);
  readonly auth = inject(AuthStore);
  private readonly theme = inject(ThemeService);
  private readonly router = inject(Router);

  readonly showSearch = input(false);
  readonly searchQuery = input('');
  readonly creatorHref = input<string | UrlTree | null>(null);
  readonly creatorLabelKey = input('experience.work.studio');
  /** App name for chat context « Dans {app} ». */
  readonly appContext = input<string | null>(null);

  readonly searchChange = output<string>();

  readonly locales: Locale[] = ['fr', 'en'];
  readonly brand = computed(() => platformBrand(this.workspace.current()?.settings));
  readonly themeMode = computed(() => this.theme.resolved());
  readonly showCreator = computed(
    () =>
      !!this.creatorHref()
      && this.workspace.experienceStudioV1Enabled()
      && canEditExperience(this.workspace.current()?.role_template, this.workspace.isAdmin()),
  );

  inputValue(event: Event): string {
    return (event.target as HTMLInputElement).value;
  }

  openHelp(): void {
    if (this.help.isOpen()) {
      this.help.close();
      return;
    }
    const app = this.appContext()?.trim();
    const originLabel = app || this.workspace.current()?.name || this.i18n.t('experience.work.title');
    if (!helpPrefersPanel()) {
      this.help.open({ originLabel, originUrl: this.router.url });
      this.help.openFullPage();
      return;
    }
    this.help.open({ originLabel, originUrl: this.router.url });
  }

  openChat(): void {
    if (this.chat.isOpen()) {
      this.chat.close();
      return;
    }
    const app = this.appContext()?.trim();
    this.chat.open({
      mode: 'quick',
      linkedLabel: app ? this.i18n.t('experience.work.chat.in_app', { app }) : null,
    });
  }

  initials(): string {
    const email = this.auth.email();
    if (!email) return '?';
    const local = email.split('@')[0] ?? '';
    const parts = local.split(/[._-]/).filter(Boolean);
    if (parts.length >= 2) return (parts[0]![0]! + parts[1]![0]!).toUpperCase();
    return local.slice(0, 2).toUpperCase() || '?';
  }
}
