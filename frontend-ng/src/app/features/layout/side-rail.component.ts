import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink } from '@angular/router';
import { filter, map, startWith } from 'rxjs';
import { GlyphComponent, type CkGlyphName } from '@app/shared/cockpit';
import { WorkspaceService, type WorkspaceMode } from '@app/core/workspace.service';

interface RailItem {
  key: string;
  label: string;
  hint: string;
  glyph: CkGlyphName;
  route: string;
  matches: string[];
  hiddenInModes?: WorkspaceMode[];
}

interface ExtraGroup {
  title: string;
  items: { label: string; glyph: CkGlyphName; route: string }[];
}

/**
 * 56px-wide icon-only navigation rail. Hosts the 5 cockpit views
 * (Hypervisor / Zoom / Steering / Builder / Run). Active view is marked
 * by a glowing vertical bar on the left edge. The "More" affordance at
 * the bottom opens a slide-over with the full secondary nav (Knowledge,
 * Intelligence, Apps, Settings, …) so legacy areas stay one click away.
 */
@Component({
  selector: 'app-side-rail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, GlyphComponent],
  template: `
    <aside
      [style.position]="'relative'"
      [style.width.px]="56"
      [style.flex]="'0 0 56px'"
      [style.height]="'100%'"
      [style.display]="'flex'"
      [style.flexDirection]="'column'"
      [style.alignItems]="'center'"
      [style.padding]="'10px 0'"
      [style.background]="'var(--ck-bg-base)'"
      [style.borderRight]="'1px solid var(--ck-stroke-2)'"
      [style.zIndex]="30"
    >
      <nav [style.display]="'flex'" [style.flexDirection]="'column'" [style.alignItems]="'center'" [style.gap.px]="6" [style.flex]="'1 1 auto'">
        @for (it of visibleItems(); track it.key) {
          <a
            [routerLink]="it.route"
            [title]="it.label + ' — ' + it.hint"
            class="ck-rail-item"
            [class.active]="isActive(it)"
            [style.position]="'relative'"
            [style.display]="'inline-flex'"
            [style.alignItems]="'center'"
            [style.justifyContent]="'center'"
            [style.width.px]="38"
            [style.height.px]="38"
            [style.borderRadius.px]="6"
            [style.color]="isActive(it) ? 'var(--ck-signal-cool)' : 'var(--ck-fg-3)'"
            [style.background]="isActive(it) ? 'rgba(125,211,252,0.06)' : 'transparent'"
            [style.transition]="'color 120ms var(--ck-ease-out), background 120ms'"
          >
            @if (isActive(it)) {
              <span
                [style.position]="'absolute'"
                [style.left.px]="-10"
                [style.top.px]="6"
                [style.bottom.px]="6"
                [style.width.px]="2"
                [style.background]="'var(--ck-signal-cool)'"
                [style.boxShadow]="'var(--ck-glow-cool)'"
                [style.borderRadius.px]="2"
              ></span>
            }
            <ck-glyph [name]="it.glyph" [size]="18" />

            <!-- Hover fly-out label (shown on hover via sibling CSS) -->
            <span
              class="ck-rail-flyout ck-mono"
            >
              <span [style.fontSize.px]="11" [style.fontWeight]="600" [style.color]="'var(--ck-fg-1)'" [style.letterSpacing]="'0.06em'" [style.textTransform]="'uppercase'">{{ it.label }}</span>
              <span [style.fontSize.px]="10" [style.color]="'var(--ck-fg-3)'" [style.marginTop.px]="2">{{ it.hint }}</span>
            </span>
          </a>
        }
      </nav>

      <div [style.display]="'flex'" [style.flexDirection]="'column'" [style.alignItems]="'center'" [style.gap.px]="6" [style.padding]="'8px 0'">
        <button
          type="button"
          (click)="toggleMore($event)"
          title="More views (⌘K)"
          [style.width.px]="38"
          [style.height.px]="38"
          [style.borderRadius.px]="6"
          [style.background]="moreOpen() ? 'var(--ck-bg-panel-hi)' : 'transparent'"
          [style.border]="'1px solid ' + (moreOpen() ? 'var(--ck-stroke-3)' : 'transparent')"
          [style.color]="'var(--ck-fg-3)'"
          [style.cursor]="'pointer'"
          [style.display]="'inline-flex'"
          [style.alignItems]="'center'"
          [style.justifyContent]="'center'"
        >
          <ck-glyph name="orbit" [size]="18" />
        </button>
      </div>
    </aside>

    @if (moreOpen()) {
      <div
        (click)="moreOpen.set(false)"
        [style.position]="'fixed'"
        [style.inset]="'0'"
        [style.background]="'rgba(0,0,0,0.45)'"
        [style.zIndex]="50"
      ></div>
      <div
        (click)="$event.stopPropagation()"
        [style.position]="'fixed'"
        [style.left.px]="56"
        [style.top.px]="48"
        [style.bottom.px]="28"
        [style.width.px]="320"
        [style.background]="'var(--ck-bg-panel-hi)'"
        [style.borderRight]="'1px solid var(--ck-stroke-3)'"
        [style.padding]="'18px 16px'"
        [style.zIndex]="51"
        [style.overflowY]="'auto'"
        class="ck-scroll"
      >
        <div class="ck-label" [style.marginBottom.px]="10">Secondary views</div>
        @for (g of extras; track g.title) {
          <div [style.marginBottom.px]="12">
            <div class="ck-label-sm" [style.color]="'var(--ck-fg-4)'" [style.marginBottom.px]="6">{{ g.title }}</div>
            <div [style.display]="'flex'" [style.flexDirection]="'column'" [style.gap.px]="2">
              @for (it of g.items; track it.route) {
                <a
                  [routerLink]="it.route"
                  (click)="moreOpen.set(false)"
                  [style.display]="'flex'"
                  [style.alignItems]="'center'"
                  [style.gap.px]="10"
                  [style.padding]="'6px 8px'"
                  [style.borderRadius.px]="4"
                  [style.color]="'var(--ck-fg-2)'"
                  [style.fontSize.px]="12"
                  [style.transition]="'background 120ms'"
                >
                  <ck-glyph [name]="it.glyph" [size]="14" color="var(--ck-fg-3)" />
                  <span>{{ it.label }}</span>
                </a>
              }
            </div>
          </div>
        }
      </div>
    }
  `,
})
export class SideRailComponent {
  private readonly router = inject(Router);
  private readonly workspace = inject(WorkspaceService);
  moreOpen = signal(false);

  private readonly url = toSignal(
    this.router.events.pipe(
      filter((e): e is NavigationEnd => e instanceof NavigationEnd),
      map((e) => e.urlAfterRedirects),
      startWith(this.router.url),
    ),
    { initialValue: this.router.url },
  );

  readonly items: RailItem[] = [
    { key: 'hypervisor', label: 'Hypervisor', hint: 'Balance sheet',  glyph: 'ledger',    route: '/hypervisor',    matches: ['/hypervisor'], hiddenInModes: ['builder'] },
    { key: 'zoom',       label: 'Zoom',       hint: 'Capabilities & skills', glyph: 'focus', route: '/capabilities', matches: ['/capabilities', '/skills'] },
    { key: 'steering',   label: 'Steering',   hint: 'Control plane',  glyph: 'sliders',   route: '/steering',       matches: ['/steering'], hiddenInModes: ['builder'] },
    { key: 'builder',    label: 'Builder',    hint: 'Compose systems', glyph: 'flow',     route: '/systems',        matches: ['/systems', '/orchestration', '/knowledge'] },
    { key: 'run',        label: 'Run',        hint: 'Observability & missions', glyph: 'telemetry', route: '/observability', matches: ['/observability', '/runs', '/intelligence', '/tasks'] },
  ];

  readonly visibleItems = computed(() => {
    const mode = this.workspace.mode();
    return this.items.filter((it) => !it.hiddenInModes || !it.hiddenInModes.includes(mode));
  });

  readonly extras: ExtraGroup[] = [
    {
      title: 'Knowledge & Build',
      items: [
        { label: 'Systems',       glyph: 'cube',  route: '/systems' },
        { label: 'Knowledge',     glyph: 'cube',  route: '/knowledge' },
        { label: 'Flow builder',  glyph: 'flow',  route: '/orchestration' },
        { label: 'Missions',      glyph: 'play',  route: '/tasks' },
      ],
    },
    {
      title: 'Measure',
      items: [
        { label: 'Intelligence',  glyph: 'pulse',     route: '/intelligence' },
        { label: 'Observability', glyph: 'telemetry', route: '/observability' },
        { label: 'Runs',          glyph: 'ledger',    route: '/runs' },
      ],
    },
    {
      title: 'Govern & Configure',
      items: [
        { label: 'Governance', glyph: 'warn',     route: '/governance' },
        { label: 'Resources',  glyph: 'orbit',    route: '/resources' },
        { label: 'Apps',       glyph: 'bolt',     route: '/apps' },
        { label: 'Settings',   glyph: 'sliders',  route: '/settings' },
      ],
    },
  ];

  readonly currentPath = computed(() => (this.url() || '/').split('?')[0]);

  isActive(it: RailItem): boolean {
    const path = this.currentPath();
    return it.matches.some((m) => path === m || path.startsWith(m + '/'));
  }

  toggleMore(ev: Event): void {
    ev.stopPropagation();
    this.moreOpen.update((v) => !v);
  }
}
