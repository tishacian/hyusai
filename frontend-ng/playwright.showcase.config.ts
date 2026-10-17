import { defineConfig, devices } from '@playwright/test';

// Dedicated live, read-only qualification. Authentication payloads must never
// appear in traces, videos, automatic screenshots or HTML failure attachments.
const proxyUrl = process.env['HTTPS_PROXY'] ?? process.env['HTTP_PROXY'];
const proxy = proxyUrl ? new URL(proxyUrl) : undefined;
const executablePath = process.env['E2E_CHROMIUM_EXECUTABLE'];

export default defineConfig({
  testDir: './e2e/tests',
  testMatch: '66-showcase-quality-release-canary.spec.ts',
  outputDir: './e2e/results/showcase-qualification',
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  timeout: 240_000,
  expect: { timeout: 15_000 },
  reporter: [['list']],
  use: {
    baseURL: process.env['E2E_BASE_URL'] ?? 'https://agentium.papai.ai',
    ignoreHTTPSErrors: false,
    trace: 'off',
    video: 'off',
    screenshot: 'off',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    launchOptions: executablePath ? { executablePath } : {},
    ...(proxy ? { proxy: {
      server: `${proxy.protocol}//${proxy.host}`,
      ...(proxy.username ? { username: decodeURIComponent(proxy.username) } : {}),
      ...(proxy.password ? { password: decodeURIComponent(proxy.password) } : {}),
    } } : {}),
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
