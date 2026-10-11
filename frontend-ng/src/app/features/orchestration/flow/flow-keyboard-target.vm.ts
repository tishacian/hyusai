/** Interactive surfaces that own Delete/Backspace while they have focus.
 * `closest()` intentionally covers icons/spans nested inside a control. */
export const FLOW_DELETE_BLOCK_SELECTOR = [
  'input',
  'textarea',
  'select',
  'button',
  'a',
  'dialog',
  'menu',
  '[contenteditable]:not([contenteditable="false"])',
  '[role="button"]',
  '[role="link"]',
  '[role="dialog"]',
  '[role="menu"]',
  '[role="menuitem"]',
  '[role="listbox"]',
  '[role="option"]',
  '[role="combobox"]',
].join(',');

interface ClosestCapableTarget {
  closest(selector: string): unknown;
}

/** True when a global Flow delete shortcut must yield to the focused UI. */
export function blocksFlowDeleteShortcut(target: EventTarget | null): boolean {
  const candidate = target as Partial<ClosestCapableTarget> | null;
  return typeof candidate?.closest === 'function'
    && !!candidate.closest(FLOW_DELETE_BLOCK_SELECTOR);
}

interface ContainsCapableTarget {
  contains(other: unknown): boolean;
}

/** True when undo/redo belongs to the chrome around the builder, where ⌘Z
 * zooms out. A click on the bare canvas moves the focus to one of the
 * builder's ancestors (the shell `main`, or `body`), so an ancestor still
 * counts as the canvas. */
export function yieldsFlowHistoryShortcut(
  target: EventTarget | null,
  builder: EventTarget | null,
): boolean {
  const focused = target as Partial<ContainsCapableTarget> | null;
  const host = builder as Partial<ContainsCapableTarget> | null;
  if (typeof focused?.contains !== 'function' || typeof host?.contains !== 'function') {
    return false;
  }
  return !host.contains(focused) && !focused.contains(host);
}
