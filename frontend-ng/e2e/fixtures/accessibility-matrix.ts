import AxeBuilder from '@axe-core/playwright';
import { expect, type Page, type TestInfo } from '@playwright/test';

const WCAG_AA_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];
const VIEWPORTS = [
  { label: 'desktop', width: 1440, height: 900 },
  { label: '456', width: 456, height: 720 },
  { label: '320-reflow', width: 320, height: 720 },
] as const;

interface MatrixOptions {
  page: Page;
  testInfo: TestInfo;
  path: string;
  readySelector: string;
  surface: 'studio' | 'work';
}

interface MatrixEntry {
  locale: 'fr' | 'en';
  theme: 'light' | 'dark';
  viewport: string;
  viewport_width: number;
  page_scroll_width: number;
  reduced_motion: boolean;
  active_motion: string[];
  axe_violations: Array<{
    id: string;
    impact: string | null;
    help: string;
    targets: unknown[];
  }>;
  axe_incomplete: string[];
}

export interface AccessibilityMatrixEvidence {
  combinations: number;
  wcag_tags: string[];
  reduced_motion: true;
  reflow_320_css_px: true;
  entries: MatrixEntry[];
}

/**
 * Real-browser WCAG/reflow matrix for the two end-user Experience surfaces.
 * 320 CSS px is the WCAG 1.4.10 equivalent of a 1280 px viewport at 400% zoom.
 */
export async function runAccessibilityMatrix({
  page,
  testInfo,
  path,
  readySelector,
  surface,
}: MatrixOptions): Promise<AccessibilityMatrixEvidence> {
  const entries: MatrixEntry[] = [];
  const failures: string[] = [];

  await page.emulateMedia({ reducedMotion: 'reduce' });
  for (const locale of ['fr', 'en'] as const) {
    for (const theme of ['light', 'dark'] as const) {
      for (const viewport of VIEWPORTS) {
        await page.setViewportSize({ width: viewport.width, height: viewport.height });
        await page.evaluate(
          ({ nextLocale, nextTheme }) => {
            localStorage.setItem('agentium_locale', nextLocale);
            localStorage.setItem('agentium_theme', nextTheme);
            localStorage.removeItem('agentium_business_theme');
          },
          { nextLocale: locale, nextTheme: theme },
        );
        await page.goto(path);
        await expect(page.locator(readySelector)).toBeVisible();
        await expect(page.getByRole('main').first()).toBeVisible();
        await expect.poll(() => page.evaluate(() => document.documentElement.lang)).toBe(locale);
        await expect.poll(() => page.evaluate(
          () => document.documentElement.getAttribute('data-theme'),
        )).toBe(theme);

        const layout = await page.evaluate((selector) => {
          const maxCssSeconds = (value: string): number => Math.max(
            0,
            ...value.split(',').map((part) => {
              const time = part.trim();
              if (time.endsWith('ms')) return Number.parseFloat(time) / 1000;
              if (time.endsWith('s')) return Number.parseFloat(time);
              return 0;
            }).filter(Number.isFinite),
          );
          const root = document.querySelector(selector);
          const rect = root?.getBoundingClientRect() ?? null;
          const clientWidth = document.documentElement.clientWidth;
          const scrollWidth = Math.max(
            document.documentElement.scrollWidth,
            document.body.scrollWidth,
          );
          const activeMotion = [...document.querySelectorAll<HTMLElement>('*')]
            .filter((element) => {
              const box = element.getBoundingClientRect();
              if (box.width === 0 || box.height === 0) return false;
              const style = getComputedStyle(element);
              const animationRuns = style.animationName !== 'none'
                && maxCssSeconds(style.animationDuration) > 0.01;
              const transitionRuns = maxCssSeconds(style.transitionDuration) > 0.01;
              return animationRuns || transitionRuns;
            })
            .slice(0, 20)
            .map((element) => {
              const classes = typeof element.className === 'string'
                ? element.className.trim().split(/\s+/).slice(0, 2).join('.')
                : '';
              return `${element.tagName.toLowerCase()}${classes ? `.${classes}` : ''}`;
            });
          return {
            clientWidth,
            scrollWidth,
            rootLeft: rect?.left ?? null,
            rootRight: rect?.right ?? null,
            reducedMotion: matchMedia('(prefers-reduced-motion: reduce)').matches,
            activeMotion,
          };
        }, readySelector);

        const axe = await new AxeBuilder({ page })
          .withTags(WCAG_AA_TAGS)
          .analyze();
        const violations = axe.violations.map((violation) => ({
          id: violation.id,
          impact: violation.impact ?? null,
          help: violation.help,
          targets: violation.nodes.map((node) => node.target),
        }));
        const tag = `${surface}-${locale}-${theme}-${viewport.label}`;
        const screenshot = await page.screenshot({
          animations: 'disabled',
          caret: 'hide',
          fullPage: true,
          type: 'png',
        });
        await testInfo.attach(`visual-${tag}`, { body: screenshot, contentType: 'image/png' });

        if (layout.scrollWidth > layout.clientWidth + 1) {
          failures.push(`${tag}: page width ${layout.scrollWidth}px exceeds ${layout.clientWidth}px`);
        }
        if (layout.rootLeft === null || layout.rootLeft < -1 || layout.rootRight! > layout.clientWidth + 1) {
          failures.push(`${tag}: ${readySelector} is clipped by the viewport`);
        }
        if (!layout.reducedMotion || layout.activeMotion.length > 0) {
          failures.push(`${tag}: reduced motion leaves ${layout.activeMotion.join(', ') || 'media mismatch'}`);
        }
        for (const violation of violations) {
          failures.push(`${tag}: axe ${violation.id} (${violation.impact ?? 'unknown'}) on ${violation.targets.join(', ')}`);
        }

        entries.push({
          locale,
          theme,
          viewport: viewport.label,
          viewport_width: viewport.width,
          page_scroll_width: layout.scrollWidth,
          reduced_motion: true,
          active_motion: layout.activeMotion,
          axe_violations: violations,
          axe_incomplete: axe.incomplete.map((result) => result.id),
        });
      }
    }
  }

  const evidence: AccessibilityMatrixEvidence = {
    combinations: entries.length,
    wcag_tags: [...WCAG_AA_TAGS],
    reduced_motion: true,
    reflow_320_css_px: true,
    entries,
  };
  await testInfo.attach(`${surface}-accessibility-matrix`, {
    body: JSON.stringify(evidence, null, 2),
    contentType: 'application/json',
  });
  expect(entries).toHaveLength(12);
  expect(failures, `${surface} accessibility/visual matrix`).toEqual([]);
  return evidence;
}
