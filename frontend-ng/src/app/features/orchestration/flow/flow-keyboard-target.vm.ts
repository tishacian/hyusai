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
