import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  OnInit,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { forkJoin, Subscription } from 'rxjs';
import { map } from 'rxjs/operators';
import { ApiService } from '@app/core/api.service';
import { WorkspaceService, type WorkspaceRequestScope } from '@app/core/workspace.service';
import {
  GENERIC_MISSION_ROOM_PROVIDER_ENDPOINTS,
  missionRoomExtensionState,
} from './mission-room.extension';

type GenericMissionView =
  | 'cockpit'
  | 'strategie'
  | 'securite'
  | 'reputation'
  | 'agenda'
  | 'presse'
  | 'decisions';

interface GenericNavigationItem {
  key: string;
  label: string;
  route: string;
}

interface GenericNavigation {
  items?: GenericNavigationItem[];
}

interface GenericLoadContext {
  scope: WorkspaceRequestScope;
  generation: number;
}

const VIEW_ENDPOINTS: Readonly<Record<GenericMissionView, string>> = Object.freeze({
  cockpit: '/mission-room/cockpit',
  strategie: '/mission-room/map',
  securite: '/mission-room/monitor',
  reputation: '/mission-room/news',
  agenda: '/mission-room/timeline',
  presse: '/mission-room/news',
  decisions: '/mission-room/decisions',
});

const VIEW_ROUTES: Readonly<Record<GenericMissionView, string>> = Object.freeze({
  cockpit: '/hypervisor/mission-room/cockpit',
  strategie: '/hypervisor/mission-room/strategie',
  securite: '/hypervisor/mission-room/securite',
  reputation: '/hypervisor/mission-room/reputation',
  agenda: '/hypervisor/mission-room/agenda',
  presse: '/hypervisor/mission-room/presse',
  decisions: '/hypervisor/mission-room/decisions',
});

export const GENERIC_MISSION_ROOM_COPY = Object.freeze({
  eyebrow: 'Workspace objects',
  title: 'Mission Room',
  overview: 'Portfolio overview',
  unavailable: 'This view is not available for the installed provider.',
  empty: 'No workspace data is configured for this view.',
});

@Component({
  selector: 'app-generic-mission-room',
  standalone: true,
  imports: [CommonModule, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section
      class="generic-mission-room"
      data-mission-room-provider="workspace_objects_v1"
      [attr.data-workspace-epoch]="requestEpoch()"
    >
      <aside class="generic-rail" aria-label="Mission Room navigation">
        <div class="generic-brand">
          <span>{{ copy.eyebrow }}</span>
          <strong>{{ providerLabel() }}</strong>
        </div>
        <nav>
          @for (item of safeNavigation(); track item.key) {
            <a
              [routerLink]="item.route"
              [class.active]="item.key === currentView()"
              [attr.data-provider-view]="item.key"
            >{{ item.label }}</a>
          }
        </nav>
        @if (workspace.workspaces().length > 1) {
          <label class="generic-workspace">
            <span>Workspace</span>
            <select
              data-testid="mission-workspace-switch"
              [value]="workspace.currentSlug() || ''"
              (change)="selectWorkspace(($any($event.target)).value)"
              aria-label="Changer de workspace"
            >
              @for (candidate of workspace.workspaces(); track candidate.id) {
                <option [value]="candidate.slug">{{ candidate.name }}</option>
              }
            </select>
          </label>
        }
      </aside>

      <main class="generic-content">
        <header>
          <span>{{ copy.eyebrow }}</span>
          <h1>{{ currentViewLabel() }}</h1>
          <p>{{ workspaceName() }}</p>
        </header>

        @if (loading()) {
          <p class="generic-state" role="status">Loading workspace data…</p>
        } @else if (error()) {
          <p class="generic-state error" role="alert">{{ error() }}</p>
        } @else {
          <section class="generic-card" data-provider-block="overview">
            <h2>{{ copy.overview }}</h2>
            <pre>{{ overviewText() }}</pre>
          </section>
          <section class="generic-card" data-provider-block="current-view">
            <h2>{{ currentViewLabel() }}</h2>
            <pre>{{ payloadText() }}</pre>
          </section>
        }
      </main>
    </section>
  `,
  styles: [`
    :host { display: block; min-height: 100%; background: #071018; color: #e9f0f4; }
    .generic-mission-room { display: grid; grid-template-columns: 230px minmax(0, 1fr); min-height: 100vh; }
    .generic-rail { display: flex; flex-direction: column; padding: 28px 18px; border-right: 1px solid rgba(255,255,255,.1); background: #0a151f; }
    .generic-brand { display: grid; gap: 6px; margin-bottom: 28px; }
    .generic-brand span, header span { color: #80c9c5; font-size: 11px; letter-spacing: .12em; text-transform: uppercase; }
    .generic-brand strong { font-size: 18px; }
    nav { display: grid; gap: 6px; }
    nav a { padding: 10px 12px; border-radius: 8px; color: #a9bac5; text-decoration: none; }
    nav a:hover, nav a.active { color: #fff; background: rgba(128,201,197,.12); }
    .generic-workspace { display: grid; gap: 5px; margin-top: auto; padding-top: 24px; }
    .generic-workspace span { color: #80c9c5; font-size: 10px; letter-spacing: .1em; text-transform: uppercase; }
    .generic-workspace select { width: 100%; min-width: 0; padding: 8px; border: 1px solid rgba(255,255,255,.14); border-radius: 8px; color: #e9f0f4; background: #071018; }
    .generic-content { padding: 36px; }
    header h1 { margin: 7px 0; font-size: 32px; }
    header p { margin: 0 0 28px; color: #8fa2ae; }
    .generic-card { margin-bottom: 16px; padding: 20px; border: 1px solid rgba(255,255,255,.1); border-radius: 12px; background: rgba(255,255,255,.025); }
    .generic-card h2 { margin: 0 0 12px; font-size: 15px; }
    pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; color: #c5d1d8; font: 12px/1.55 ui-monospace, monospace; }
    .generic-state { padding: 20px; border-radius: 10px; background: rgba(255,255,255,.04); }
    .generic-state.error { color: #ffb8b8; }
    @media (max-width: 800px) { .generic-mission-room { grid-template-columns: 1fr; } .generic-rail { border-right: 0; } }
  `],
})
export class GenericMissionRoomComponent implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  protected readonly workspace = inject(WorkspaceService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private requests = new Subscription();
  private unregisterReset: () => void = () => undefined;
  private generation = 0;
  private initialized = false;
  private lastWorkspaceEpoch: number | null = null;
  private lastRequestedView: string | null = null;

  readonly copy = GENERIC_MISSION_ROOM_COPY;
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly navigation = signal<GenericNavigation | null>(null);
  readonly overview = signal<Record<string, unknown> | null>(null);
  readonly payload = signal<Record<string, unknown> | null>(null);
  readonly requestEpoch = signal<number | null>(null);
  private readonly requestedView = toSignal(
    this.route.paramMap.pipe(map((params) => params.get('view') || 'cockpit')),
    { initialValue: 'cockpit' },
  );
  readonly providerState = computed(() => missionRoomExtensionState(this.workspace.current()));
  readonly providerLabel = computed(() => this.providerState().label || GENERIC_MISSION_ROOM_COPY.title);
  readonly workspaceName = computed(() => this.workspace.current()?.name || GENERIC_MISSION_ROOM_COPY.title);
  readonly currentView = computed<GenericMissionView>(() => {
    const value = this.requestedView();
    return isGenericMissionView(value) ? value : 'cockpit';
  });
  readonly currentViewLabel = computed(() => (
    this.safeNavigation().find((item) => item.key === this.currentView())?.label
      || this.currentView().replace(/^./, (letter) => letter.toUpperCase())
  ));
  readonly safeNavigation = computed(() => {
    const items = this.navigation()?.items;
    if (!Array.isArray(items)) return [];
    return items.filter((item) => (
      isGenericMissionView(item?.key)
      && item.route === VIEW_ROUTES[item.key]
      && this.endpointAllowed('GET', VIEW_ENDPOINTS[item.key])
    ));
  });
  readonly overviewText = computed(() => this.serialized(this.overview()));
  readonly payloadText = computed(() => this.serialized(this.payload()));

  constructor() {
    this.unregisterReset = this.workspace.registerContextReset(() => this.purge());
    effect(() => {
      const epoch = this.workspace.captureRequestScope().epoch;
      const view = this.requestedView();
      if (
        !this.initialized
        || (epoch === this.lastWorkspaceEpoch && view === this.lastRequestedView)
      ) return;
      if (!isGenericMissionView(view)) {
        this.purge();
        void this.router.navigate(['/hypervisor/mission-room/cockpit'], { replaceUrl: true });
        return;
      }
      this.load();
    });
  }

  ngOnInit(): void {
    this.initialized = true;
    if (!this.providerState().genericProvider) {
      this.loading.set(false);
      this.error.set(GENERIC_MISSION_ROOM_COPY.unavailable);
      return;
    }
    if (!isGenericMissionView(this.requestedView())) {
      void this.router.navigate(['/hypervisor/mission-room/cockpit'], { replaceUrl: true });
      return;
    }
    this.load();
  }

  ngOnDestroy(): void {
    this.initialized = false;
    this.unregisterReset();
    this.requests.unsubscribe();
  }

  selectWorkspace(slug: string): void {
    if (!slug || slug === this.workspace.currentSlug()) return;
    if (!this.workspace.switchWorkspace(slug)) return;
    // The root resolver owns the destination after WorkspaceService has
    // synchronously purged tenant state and published the next epoch.
    void this.router.navigateByUrl('/');
  }

  private load(): void {
    this.purge(false);
    const context: GenericLoadContext = {
      scope: this.workspace.captureRequestScope(),
      generation: this.generation,
    };
    this.lastWorkspaceEpoch = context.scope.epoch;
    this.lastRequestedView = this.requestedView();
    this.requestEpoch.set(context.scope.epoch);
    if (!this.providerState().genericProvider) {
      this.loading.set(false);
      this.error.set(GENERIC_MISSION_ROOM_COPY.unavailable);
      return;
    }
    const viewEndpoint = VIEW_ENDPOINTS[this.currentView()];
    const required = [
      ['GET', '/mission-room/overview'],
      ['GET', '/mission-room/navigation'],
      ['GET', viewEndpoint],
    ] as const;
    if (required.some(([method, path]) => !this.endpointAllowed(method, path))) {
      this.loading.set(false);
      this.error.set(GENERIC_MISSION_ROOM_COPY.unavailable);
      return;
    }
    const options = { workspaceSlug: context.scope.workspaceSlug };
    this.loading.set(true);
    const request = forkJoin({
      navigation: this.api.get<GenericNavigation>('/mission-room/navigation', undefined, options),
      overview: this.api.get<Record<string, unknown>>('/mission-room/overview', undefined, options),
      payload: this.api.get<Record<string, unknown>>(viewEndpoint, undefined, options),
    }).subscribe({
      next: ({ navigation, overview, payload }) => {
        if (!this.contextCurrent(context)) return;
        this.navigation.set(navigation);
        this.overview.set(overview);
        this.payload.set(payload);
        this.loading.set(false);
      },
      error: () => {
        if (!this.contextCurrent(context)) return;
        this.loading.set(false);
        this.error.set('Workspace data is temporarily unavailable.');
      },
    });
    this.requests.add(request);
  }

  private endpointAllowed(method: string, path: string): boolean {
    const relative = path.startsWith('/mission-room')
      ? path.slice('/mission-room'.length) || '/'
      : '';
    const contract = `${method.toUpperCase()} ${relative}`;
    return this.providerState().genericProvider
      && GENERIC_MISSION_ROOM_PROVIDER_ENDPOINTS.includes(
        contract as (typeof GENERIC_MISSION_ROOM_PROVIDER_ENDPOINTS)[number],
      );
  }

  private contextCurrent(context: GenericLoadContext): boolean {
    return context.generation === this.generation
      && this.workspace.isRequestScopeCurrent(context.scope);
  }

  private purge(increment = true): void {
    if (increment) this.generation += 1;
    this.requests.unsubscribe();
    this.requests = new Subscription();
    this.navigation.set(null);
    this.overview.set(null);
    this.payload.set(null);
    this.error.set(null);
    this.loading.set(false);
    this.requestEpoch.set(null);
  }

  private serialized(value: Record<string, unknown> | null): string {
    return value ? JSON.stringify(value, null, 2) : GENERIC_MISSION_ROOM_COPY.empty;
  }
}

function isGenericMissionView(value: unknown): value is GenericMissionView {
  return typeof value === 'string' && Object.prototype.hasOwnProperty.call(VIEW_ENDPOINTS, value);
}
