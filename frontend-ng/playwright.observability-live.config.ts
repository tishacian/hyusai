import { defineConfig } from '@playwright/test';
import showcase from './playwright.showcase.config';

// Playwright also captures an accessibility snapshot on failure, independently
// of trace/video/screenshot settings. Native audits may contain private I/O.
// Keep failure metadata, but exclude that automatic page-content attachment.
process.env['PLAYWRIGHT_NO_COPY_PROMPT'] = '1';

// Real service only; each recipe declares its required corpus and release state.
// Reuse strict TLS and suppression of authentication traces/videos/screenshots.
export default defineConfig({
  ...showcase,
  testMatch: [
    '66-showcase-quality-release-canary.spec.ts',
    '67-*.spec.ts',
    '68-*.spec.ts',
    '69-*.spec.ts',
  ],
  outputDir: './e2e/results/observability-live',
});
