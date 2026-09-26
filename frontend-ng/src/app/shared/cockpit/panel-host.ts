import {
  ChangeDetectionStrategy,
  Component,
  HostListener,
  Injectable,
  computed,
  inject,
  signal,
} from '@angular/core';
import { WorkspaceService } from '@app/core/workspace.service';

export type CkPanelPosition = 'side' | 'bottom' | 'floating';

export interface CkPanelRef {
  id: string;
  position: CkPanelPosition;
  close: () => void;
}

/**
 * Coordinates open `<ck-panel>` instances so only the topmost one consumes
 * Escape. Kept free of i18n so the app-root host stays out of the initial
 * dictionary chunk (L16).
 */
@Injectable({ providedIn: 'root' })
export class PanelHostService {
  private readonly workspace = inject(WorkspaceService);
  private readonly stack = signal<CkPanelRef[]>([]);
  readonly open = computed(() => this.stack().length > 0);
  readonly top = computed(() => {
    const s = this.stack();
    return s.length > 0 ? s[s.length - 1] : null;
  });

  constructor() {
    this.workspace.registerContextReset(() => this.closeAll());
  }

  push(ref: CkPanelRef): void {
    this.stack.update((s) => [...s, ref]);
  }

  pop(id: string): void {
    this.stack.update((s) => s.filter((r) => r.id !== id));
  }

  /** Close the topmost panel (used by global Escape in the shell outlet). */
  closeTop(): void {
    const ref = this.top();
    if (ref) ref.close();
  }

  closeAll(): void {
    for (const ref of [...this.stack()].reverse()) ref.close();
    this.stack.set([]);
  }
}

/**
 * `<app-panel-host>` — app-level Escape owner for the topmost panel.
 * Place once at the app root (Cockpit + Work).
 */
@Component({
  selector: 'app-panel-host',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: ``,
})
export class CkPanelHostComponent {
  private readonly panelHost = inject(PanelHostService);

  @HostListener('window:keydown.escape', ['$event'])
  onEscape(ev: Event): void {
    if (!this.panelHost.open()) return;
    ev.preventDefault();
    this.panelHost.closeTop();
  }
}
