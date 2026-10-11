import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router } from '@angular/router';
import { filter, map, startWith } from 'rxjs';
import { KbdComponent, LiveDotComponent } from '@app/shared/cockpit';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { ZoomContextService } from '@app/core/zoom-context.service';

/**
 * Bottom command bar (28px). Mirrors the BottomCommand region of the
 * mockup: platform status pulse (« Plateforme opérationnelle », never
 * « Système », which names a lexicon object), current path, command-palette hint,
 * semantic-zoom hint and build identifier.
 *
 * The zoom depth (« niveau 2 sur 3 ») and the ⌘Z hint are engineering
 * detail: only the builder mode sees them. Every other mode keeps the bar,
 * its landmark and the zone it is in.
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
        data-testid="command-bar-position"
        [style.fontSize.px]="11"
        [style.color]="'var(--ck-fg-2)'"
      >{{ position() }}</span>
      <span [style.flex]="'1 1 auto'"></span>
      <span
        [style.fontSize.px]="11"
        [style.color]="'var(--ck-fg-4)'"
        [style.display]="'inline-flex'"
        [style.alignItems]="'center'"
        [style.gap.px]="6"
      ><ck-kbd>⌘K</ck-kbd>{{ i18n.t('nav.footer.command') }}</span>
      @if (showZoomDepth()) {
      <span
        [title]="zoomHintTitle()"
        [style.fontSize.px]="11"
        [style.color]="'var(--ck-fg-4)'"
        [style.display]="'inline-flex'"
        [style.alignItems]="'center'"
        [style.gap.px]="6"
        [style.cursor]="'help'"
      ><ck-kbd>⌘Z</ck-kbd>{{ zoomHint() }}</span>
      }
      <span class="ck-hairline-v" [style.height.px]="14"></span>
      <!-- An identifier: the only mono text on the bar. -->
      <span
        class="ck-mono"
        data-testid="command-bar-version"
        [style.fontSize.px]="10"
        [style.color]="'var(--ck-fg-5)'"
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
  private readonly workspace = inject(WorkspaceService);
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

  /** Zoom depth and ⌘Z hint: builder mode only. */
  readonly showZoomDepth = computed(() => this.workspace.isBuilderMode());

  readonly position = computed(() => {
    if (!this.navigation.navV5Enabled?.()) return this.path();
    const { depth, total } = this.navigation.depthPair();
    const zone = this.i18n.t(this.navigation.zoneI18nKey());
    const filtered = Boolean(
      !this.navigation.deepestResolvedType()
      && (this.navigation.systemId() || this.navigation.capabilityId()),
    );
    if (!this.showZoomDepth()) {
      return this.i18n.t(filtered ? 'nav.command.zone_filter' : 'nav.command.zone', { zone });
    }
    return this.i18n.t(filtered ? 'nav.command.position_filter' : 'nav.command.position', {
      zone,
      depth: String(depth),
      total: String(total),
    });
  });

  /** Short ⌘Z target named by the parent crumb. */
  readonly zoomHint = computed(() => {
    if (!this.navigation.navV5Enabled?.()) {
      return this.i18n.t('nav.footer.zoom');
    }
    return this.navigation.zoomParentHint();
  });

  readonly zoomHintTitle = computed(() => {
    const chain = this.navigation.nodes()
      .map((node) => node.label)
      .join(' › ');
    return this.i18n.t(
      this.navigation.navV5Enabled?.() ? 'nav.zoom.hint_v5' : 'nav.zoom.hint',
      { chain },
    );
  });
}
