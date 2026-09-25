/**
 * Route focus (chrome L3). After navigation, move focus to a target from
 * `NavigationExtras.state.focus` (CSS selector), else the first `h1`, else
 * `root` when it is an element. L14 uses `state.focus` to restore focus to
 * "Open in Work" on the return trip.
 */

export type RouteFocusState = {
  focus?: unknown;
  [key: string]: unknown;
} | null | undefined;

export function navigationFocusFromState(state: RouteFocusState): string | null {
  const value = state && typeof state === 'object' ? state['focus'] : null;
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

export function focusAfterRoute(
  root: ParentNode,
  options: { focus?: string | null } = {},
): HTMLElement | null {
  const requested = resolveFocusSelector(root, options.focus);
  const heading = root.querySelector<HTMLElement>('h1');
  const fallback = root instanceof HTMLElement ? root : null;
  const target = requested ?? heading ?? fallback;
  if (!target) return null;

  // Only force tabindex on the default title / main fallback. A caller-supplied
  // focus target (L14 button) must keep its natural tab order.
  if (!requested && !target.hasAttribute('tabindex')) {
    target.setAttribute('tabindex', '-1');
  }
  target.focus({ preventScroll: true });
  return target;
}

function resolveFocusSelector(root: ParentNode, focus: string | null | undefined): HTMLElement | null {
  if (!focus) return null;
  try {
    return root.querySelector<HTMLElement>(focus);
  } catch {
    return null;
  }
}
