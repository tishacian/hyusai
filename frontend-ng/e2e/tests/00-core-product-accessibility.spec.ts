import { test } from '@playwright/test';

import { runAccessibilityMatrix } from '../fixtures/accessibility-matrix';
import { loginAsAlice } from '../fixtures/auth';

const enabled = process.env['E2E_CORE_ACCESSIBILITY'] === '1';

const surfaces = [
  { name: 'ask', path: '/chat?mode=quick', readySelector: 'app-chat-workspace' },
  { name: 'settings', path: '/settings', readySelector: 'app-resources-page' },
  { name: 'knowledge', path: '/knowledge', readySelector: 'app-knowledge-base' },
  { name: 'build', path: '/systems/new', readySelector: 'app-system-builder' },
  { name: 'runs', path: '/runs', readySelector: 'app-runs-list' },
] as const;

test.describe('P2 — core product accessibility and reflow', () => {
  test.skip(!enabled, 'Set E2E_CORE_ACCESSIBILITY=1 against an isolated test workspace.');

  for (const surface of surfaces) {
    test(`${surface.name}: WCAG AA, reduced motion, and 320 px reflow`, async ({ page }, testInfo) => {
      test.setTimeout(180_000);
      await loginAsAlice(page);
      await runAccessibilityMatrix({
        page,
        testInfo,
        path: surface.path,
        readySelector: surface.readySelector,
        surface: surface.name,
      });
    });
  }
});
