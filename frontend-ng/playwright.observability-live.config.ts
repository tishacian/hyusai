import { defineConfig } from '@playwright/test';
import showcase from './playwright.showcase.config';

// Real service only; each recipe declares its required corpus and release state.
// Reuse strict TLS and suppression of authentication traces/videos/screenshots.
export default defineConfig({
  ...showcase,
  testMatch: [
    '66-showcase-quality-release-canary.spec.ts',
    '67-*.spec.ts',
    '68-*.spec.ts',
  ],
  outputDir: './e2e/results/observability-live',
});
