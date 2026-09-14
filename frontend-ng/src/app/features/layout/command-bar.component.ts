import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router } from '@angular/router';
import { filter, map, startWith } from 'rxjs';
import { KbdComponent, LiveDotComponent, ScrollFocusableDirective } from '@app/shared/cockpit';
import { I18nService } from '@app/core/i18n.service';
import { ZoomContextService } from '@app/core/zoom-context.service';

/**
 * Bottom command bar (28px). Mirrors the BottomCommand region of the
 * mockup: system status pulse, current path, command-palette hint,
 * semantic-zoom hint and build identifier.
 */
@Component({
  selector: 'app-command-bar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [KbdComponent, LiveDotComponent, ScrollFocusableDirective],
  template: `
    <footer
      ckScrollFocusable
      [style.position]="'relative'"
      [style.zIndex]="35"
      [style.height.px]="28"
      [style.display]="'flex'"
      [style.alignItems]="'center'"
      [style.padding]="'0 14px'"
      [style.minWidth]="'0'"
      [style.maxWidth]="'100%'"
      [style.overflowX]="'auto'"
      [style.background]="'var(--ck-bg-base)'"
      [style.borderTop]="'1px solid var(--ck-stroke-2)'"
      [style.color]="'var(--ck-fg-3)'"
      [style.gap.px]="12"
    >
      <ck-live-dot tone="pos" [label]="i18n.t('nav.footer.status_operational')" />
      <span class="ck-hairline-v" [style.height.px]="14"></span>
      <span
        class="ck-mono"
        [style.fontSize.px]="10"
        [style.letterSpacing]="'0.10em'"
        [style.color]="'var(--ck-fg-2)'"
      >{{ position() }}</span>
      <span [style.flex]="'1 1 auto'"></span>
      <span
        class="ck-mono"
        [style.fontSize.px]="9"
        [style.letterSpacing]="'0.14em'"
        [style.textTransform]="'uppercase'"
        [style.color]="'var(--ck-fg-4)'"
        [style.display]="'inline-flex'"
        [style.alignItems]="'center'"
        [style.gap.px]="6"
      ><ck-kbd>⌘K</ck-kbd>{{ i18n.t('nav.footer.command') }}</span>
      <span
        class="ck-mono"
        [title]="zoomHint()"
        [style.fontSize.px]="9"
        [style.letterSpacing]="'0.14em'"
        [style.textTransform]="'uppercase'"
        [style.color]="'var(--ck-fg-4)'"
        [style.display]="'inline-flex'"
        [style.alignItems]="'center'"
        [style.gap.px]="6"
        [style.cursor]="'help'"
      ><ck-kbd>⌘Z</ck-kbd>{{ i18n.t('nav.footer.zoom') }}</span>
      <span class="ck-hairline-v" [style.height.px]="14"></span>
      <!-- The build stamp is 9 px body text, not a large-text or UI-component
           case, so it owes the full 4.5:1 and cannot sit on the faint tier. -->
      <span
        class="ck-mono"
        [style.fontSize.px]="9"
        [style.letterSpacing]="'0.14em'"
        [style.textTransform]="'uppercase'"
        [style.color]="'var(--ck-fg-4)'"
      >v0.4.0 · build 1</span>
    </footer>
  `,
  styles: [`
    :host {
      display: block;
      min-width: 0;
      max-width: 100%;
    }
  `],
})
export class CommandBarComponent {
  readonly i18n = inject(I18nService);
  private readonly navigation = inject(ZoomContextService);
  private readonly router = inject(Router);
  private readonly url = toSignal(
    this.router.events.pipe(
      filter((e): e is NavigationEnd => e instanceof NavigationEnd),
      map((e) => e.urlAfterRedirects),
      startWith(this.router.url),
    ),
    { initialValue: this.router.url },
  );

  readonly path = computed(() => (this.url() || '/').split('?')[0]);

  readonly position = computed(() => {
    if (!this.navigation.navV5Enabled?.()) return this.path();
    const depth = this.depth();
    const zone = this.i18n.t(this.navigation.zoneI18nKey());
    const filtered = Boolean(
      !this.navigation.deepestResolvedType()
      && (this.navigation.systemId() || this.navigation.capabilityId()),
    );
    return this.i18n.t(filtered ? 'nav.command.position_filter' : 'nav.command.position', {
      zone,
      depth: String(depth),
    });
  });

  private depth(): number {
    switch (this.navigation.deepestResolvedType()) {
      case 'skill':
      case 'skill_invocation':
        return 5;
      case 'run':
        return 4;
      case 'system':
        return 3;
      case 'capability':
        return 2;
      default:
        return 1;
    }
  }

  /** Canonical zoom chain, in the order `SemanticZoomBreadcrumbComponent` walks it. */
  readonly zoomHint = computed(() => {
    const chain = (['portfolio', 'capability', 'system', 'run', 'skill'] as const)
      .map((key) => this.i18n.t(`nav.zoom.${key}`))
      .join(' › ');
    return this.i18n.t(
      this.navigation.navV5Enabled?.() ? 'nav.zoom.hint_v5' : 'nav.zoom.hint',
      { chain },
    );
  });
}
