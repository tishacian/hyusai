import { Injectable } from '@angular/core';

/**
 * Callback contract for a tab group that wants to receive `Cmd/Ctrl + digit`
 * keyboard shortcuts. The number corresponds to the 1-based position of the
 * *visible* tab (overflow tabs are unreachable by shortcut — that is the
 * intentional trade-off of progressive disclosure).
 */
export type TabShortcutHandler = (visibleIndex: number) => void;

/**
 * `TabShortcutService` — a singleton registry that routes `Cmd/Ctrl + 1…9`
 * to the most recently mounted `<ck-tabs>` instance.
 *
 * Why a registry: Angular components each installing their own global
 * `@HostListener('window:keydown')` would race whenever multiple tab
 * groups are mounted concurrently (e.g. a side panel + a main canvas both
 * rendering tabs). Instead every `<ck-tabs>` registers a handler on
 * `ngOnInit` and unregisters on destroy, and this service ensures the
 * *topmost* (last-registered) tab group owns the shortcuts.
 *
 * Shortcuts are intentionally skipped when the user is typing in an input,
 * textarea, select, or contenteditable element so native OS bindings keep
 * working for form input.
 *
 * See docs/mental-model.md §5bis.5 for the tabs-as-facets contract.
 */
@Injectable({ providedIn: 'root' })
export class TabShortcutService {
  private readonly stack: TabShortcutHandler[] = [];
  private installed = false;

  /** Register a handler; returns a disposer to call from `ngOnDestroy`. */
  register(handler: TabShortcutHandler): () => void {
    this.stack.push(handler);
    this.ensureInstalled();
    return () => this.unregister(handler);
  }

  private unregister(handler: TabShortcutHandler): void {
    const idx = this.stack.lastIndexOf(handler);
    if (idx !== -1) this.stack.splice(idx, 1);
  }

  private ensureInstalled(): void {
    if (this.installed) return;
    if (typeof window === 'undefined') return;
    window.addEventListener('keydown', this.onKeydown, { capture: false });
    this.installed = true;
  }

  private readonly onKeydown = (ev: KeyboardEvent): void => {
    if (!(ev.metaKey || ev.ctrlKey)) return;
    if (ev.altKey || ev.shiftKey) return;
    if (ev.key.length !== 1) return;
    const code = ev.key.charCodeAt(0);
    // '1'..'9'
    if (code < 49 || code > 57) return;

    const target = ev.target as HTMLElement | null;
    if (target && this.isEditable(target)) return;

    const top = this.stack[this.stack.length - 1];
    if (!top) return;

    ev.preventDefault();
    ev.stopPropagation();
    top(code - 49);
  };

  private isEditable(el: HTMLElement): boolean {
    const tag = el.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
    if (el.isContentEditable) return true;
    return false;
  }
}
