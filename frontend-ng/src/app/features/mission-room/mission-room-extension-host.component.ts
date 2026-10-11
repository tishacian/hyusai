import {
  AfterViewInit,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnDestroy,
  ViewChild,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { WorkspaceService } from '@app/core/workspace.service';
import { missionRoomExtensionState } from './mission-room.extension';
import {
  MISSION_ROOM_PRESENTATION_ATTRIBUTES,
  presentMissionRoomText,
} from './mission-room.presentation';

interface PresentedValue {
  source: string;
  rendered: string;
}

/**
 * Route-bound host for Mission Room extension infrastructure.
 *
 * It owns the presentation boundary and nested outlet while the existing
 * business components remain untouched.  Source values are retained so a
 * workspace/profile switch can restore Sentinel labels atomically.
 */
@Component({
  selector: 'app-mission-room-extension-host',
  standalone: true,
  imports: [RouterOutlet],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      #extensionRoot
      class="mission-room-extension-host"
      data-mission-room-extension="mission-room"
      [attr.data-mission-room-profile]="profile()"
      [style.visibility]="ready() ? null : 'hidden'"
    >
      <router-outlet />
    </div>
  `,
  styles: [`
    :host,
    .mission-room-extension-host {
      display: contents;
    }
  `],
})
export class MissionRoomExtensionHostComponent implements AfterViewInit, OnDestroy {
  private readonly workspace = inject(WorkspaceService);
  private readonly textValues = new WeakMap<Text, PresentedValue>();
  private readonly attributeValues = new WeakMap<Element, Map<string, PresentedValue>>();
  private observer: MutationObserver | null = null;
  private viewReady = false;
  private scrubQueued = false;

  @ViewChild('extensionRoot', { static: true })
  private extensionRoot!: ElementRef<HTMLElement>;

  readonly ready = signal(false);
  readonly profile = computed(() => missionRoomExtensionState(this.workspace.current()).profile);

  constructor() {
    effect(() => {
      this.profile();
      if (this.viewReady) this.queueScrub();
    });
  }

  ngAfterViewInit(): void {
    this.viewReady = true;
    const root = this.extensionRoot.nativeElement;
    this.observer = new MutationObserver(() => this.queueScrub());
    this.observer.observe(root, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
      attributeFilter: [...MISSION_ROOM_PRESENTATION_ATTRIBUTES],
    });
    this.queueScrub();
  }

  ngOnDestroy(): void {
    this.observer?.disconnect();
    this.observer = null;
  }

  private queueScrub(): void {
    // Keep the extension subtree non-paintable across profile switches and
    // async child mutations until the presentation pass has completed.
    this.ready.set(false);
    if (this.scrubQueued) return;
    this.scrubQueued = true;
    queueMicrotask(() => {
      this.scrubQueued = false;
      this.scrub();
      this.ready.set(true);
    });
  }

  private scrub(): void {
    if (!this.viewReady) return;
    const root = this.extensionRoot.nativeElement;
    const profile = this.profile();
    const walker = root.ownerDocument.createTreeWalker(root, 4); // NodeFilter.SHOW_TEXT
    let current = walker.nextNode();
    while (current) {
      this.presentTextNode(current as Text, profile);
      current = walker.nextNode();
    }

    this.presentAttributes(root, profile);
    for (const element of Array.from(root.querySelectorAll('*'))) {
      this.presentAttributes(element, profile);
    }
  }

  private presentTextNode(node: Text, profile: string | null): void {
    const current = node.nodeValue || '';
    const previous = this.textValues.get(node);
    const source = previous && current === previous.rendered ? previous.source : current;
    const rendered = presentMissionRoomText(profile, source);
    this.textValues.set(node, { source, rendered });
    if (current !== rendered) node.nodeValue = rendered;
  }

  private presentAttributes(element: Element, profile: string | null): void {
    let state = this.attributeValues.get(element);
    if (!state) {
      state = new Map<string, PresentedValue>();
      this.attributeValues.set(element, state);
    }
    for (const attribute of MISSION_ROOM_PRESENTATION_ATTRIBUTES) {
      const current = element.getAttribute(attribute);
      if (current === null) {
        state.delete(attribute);
        continue;
      }
      const previous = state.get(attribute);
      const source = previous && current === previous.rendered ? previous.source : current;
      const rendered = presentMissionRoomText(profile, source);
      state.set(attribute, { source, rendered });
      if (current !== rendered) element.setAttribute(attribute, rendered);
    }
  }
}
