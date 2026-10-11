/** Hard floor keeps form controls usable; ceiling avoids accidentally covering the desktop. */
export const CK_PANEL_MIN_WIDTH = 360;
export const CK_PANEL_MAX_WIDTH = 1280;

export function clampPanelWidth(
  value: number,
  min = CK_PANEL_MIN_WIDTH,
  max = CK_PANEL_MAX_WIDTH,
): number {
  return Math.min(max, Math.max(min, Math.round(value)));
}
