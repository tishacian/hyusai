import assert from 'node:assert/strict';
import { test } from 'node:test';
import { CK_PANEL_MAX_WIDTH, CK_PANEL_MIN_WIDTH, clampPanelWidth } from './panel-resize';

test('panel resizing keeps the chat usable without covering the workspace by accident', () => {
  assert.equal(clampPanelWidth(240), CK_PANEL_MIN_WIDTH);
  assert.equal(clampPanelWidth(562.4), 562);
  assert.equal(clampPanelWidth(2000), CK_PANEL_MAX_WIDTH);
  assert.equal(clampPanelWidth(900, 480, 820), 820);
});
