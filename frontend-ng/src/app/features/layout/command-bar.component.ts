import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router } from '@angular/router';
import { filter, map, startWith } from 'rxjs';
import { KbdComponent, LiveDotComponent } from '@app/shared/cockpit';

/**
 * Bottom command bar (28px). Mirrors the BottomCommand region of the
 * mockup: system status pulse, current path, command-palette hint,
 * semantic-zoom hint and build identifier.
 */
@Component({
  selector: 'app-command-bar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [KbdComponent, LiveDotComponent],
  template: `
    <footer
      [style.position]="'relative'"
      [style.zIndex]="35"
      [style.height.px]="28"
      [style.display]="'flex'"
      [style.alignItems]="'center'"
      [style.padding]="'0 14px'"
      [style.background]="'var(--ck-bg-base)'"
      [style.borderTop]="'1px solid var(--ck-stroke-2)'"
      [style.color]="'var(--ck-fg-3)'"
      [style.gap.px]="12"
    >
      <ck-live-dot tone="pos" label="System operational" />
      <span class="ck-hairline-v" [style.height.px]="14"></span>
      <span
        class="ck-mono"
        [style.fontSize.px]="10"
        [style.letterSpacing]="'0.10em'"
        [style.color]="'var(--ck-fg-2)'"
      >{{ path() }}</span>
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
      ><ck-kbd>⌘K</ck-kbd>Command</span>
      <span
        class="ck-mono"
        [style.fontSize.px]="9"
        [style.letterSpacing]="'0.14em'"
        [style.textTransform]="'uppercase'"
        [style.color]="'var(--ck-fg-4)'"
        [style.display]="'inline-flex'"
        [style.alignItems]="'center'"
        [style.gap.px]="6"
      ><ck-kbd>⌘Z</ck-kbd>Zoom</span>
      <span class="ck-hairline-v" [style.height.px]="14"></span>
      <span
        class="ck-mono"
        [style.fontSize.px]="9"
        [style.letterSpacing]="'0.14em'"
        [style.textTransform]="'uppercase'"
        [style.color]="'var(--ck-fg-5)'"
      >v0.4.0 · build 1</span>
    </footer>
  `,
})
export class CommandBarComponent {
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
}
