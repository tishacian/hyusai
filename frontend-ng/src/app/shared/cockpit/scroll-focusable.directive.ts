import {
  DestroyRef,
  Directive,
  ElementRef,
  NgZone,
  OnInit,
  inject,
} from '@angular/core';

/**
 * Keeps a scrolling container reachable from the keyboard (WCAG 2.1.1).
 *
 * A pane with `overflow: auto` can hide content that a mouse reaches by
 * dragging and a keyboard cannot reach at all — unless the pane itself takes
 * focus. A focusable descendant does not make all off-screen prose reachable:
 * tabbing can jump directly to that control while the rest of the region still
 * has no keyboard scroll target. The command bar hits this below ~460 px
 * (the status, position and shortcut hints stop fitting on one 28 px line) and
 * the chat transcript hits it at 320 px before the first reply exists.
 *
 * Hard-coding `tabindex="0"` would fix both and charge every other layout a
 * dead tab stop on a pane that has nothing to scroll. So the attribute tracks
 * the measurement instead: it appears only while the element genuinely
 * overflows and is removed again as soon as it stops. The tab order therefore
 * gains a stop exactly where a keyboard user would otherwise be stranded.
 */
@Directive({
  selector: '[ckScrollFocusable]',
  standalone: true,
})
export class ScrollFocusableDirective implements OnInit {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly zone = inject(NgZone);
  private readonly destroyRef = inject(DestroyRef);
  private frame = 0;

  ngOnInit(): void {
    const element = this.host.nativeElement;
    // Measuring is layout-only work driven by resize/mutation, never by
    // Angular state — running it inside the zone would schedule a change
    // detection pass per scroll-height change of a streaming transcript.
    this.zone.runOutsideAngular(() => {
      const schedule = () => {
        cancelAnimationFrame(this.frame);
        this.frame = requestAnimationFrame(() => this.sync());
      };

      const resize = new ResizeObserver(schedule);
      resize.observe(element);
      for (const child of Array.from(element.children)) resize.observe(child);

      const mutations = new MutationObserver((records) => {
        for (const record of records) {
          for (const added of Array.from(record.addedNodes)) {
            if (added instanceof Element && added.parentElement === element) {
              resize.observe(added);
            }
          }
        }
        schedule();
      });
      mutations.observe(element, { childList: true, subtree: true, characterData: true });

      this.destroyRef.onDestroy(() => {
        cancelAnimationFrame(this.frame);
        resize.disconnect();
        mutations.disconnect();
      });

      this.sync();
    });
  }

  private sync(): void {
    const element = this.host.nativeElement;
    const scrolls =
      element.scrollWidth > element.clientWidth + 1 ||
      element.scrollHeight > element.clientHeight + 1;
    if (scrolls) {
      element.setAttribute('tabindex', '0');
    } else {
      element.removeAttribute('tabindex');
    }
  }
}
