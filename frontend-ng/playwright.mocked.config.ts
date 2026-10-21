import { defineConfig, devices } from '@playwright/test';

const address = new URL(process.env['E2E_BASE_URL'] ?? 'http://127.0.0.1:4321');
if (address.protocol !== 'http:' || !['localhost', '127.0.0.1'].includes(address.hostname)
  || address.username || address.password || address.pathname !== '/' || address.search || address.hash) {
  throw new Error('Mocked browser tests require a plain loopback HTTP address; remote targets are forbidden.');
}
const port = Number(address.port || 80);
process.env['E2E_BASE_URL'] = address.origin;
process.env['E2E_CHROME_V2_MOCKED'] = '1';
process.env['E2E_ACTIVITY_OBSERVABILITY_FIXTURE'] = '1';
process.env['E2E_OPERATIONS_FIXTURE'] = '1';

export default defineConfig({
  testDir: './e2e/tests',
  testMatch: '**/*-mocked.spec.ts',
  outputDir: './e2e/results/mocked',
  forbidOnly: !!process.env['CI'],
  fullyParallel: false,
  workers: process.env['CI'] ? 2 : 1,
  retries: process.env['CI'] ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['junit', { outputFile: 'e2e/results/mocked/junit.xml' }], ['html', { outputFolder: 'e2e/report-mocked', open: 'never' }]],
  use: {
    baseURL: address.origin,
    serviceWorkers: 'block',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    ...(process.env['E2E_CHROMIUM_EXECUTABLE'] ? { launchOptions: { executablePath: process.env['E2E_CHROMIUM_EXECUTABLE'] } } : {}),
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'node e2e/serve-dist.mjs',
    env: { HOST: '127.0.0.1', PORT: String(port) },
    url: address.origin,
    reuseExistingServer: !process.env['CI'],
    timeout: 30_000,
  },
});
