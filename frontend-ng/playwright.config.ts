import { defineConfig, devices } from '@playwright/test';

/**
 * Agentium E2E test config (Vague E / E2).
 *
 * Target is the staging VM at `https://agentium.papai.ai` by default
 * so the test harness hits a realistic Keycloak + Qdrant + Postgres
 * stack. Override with `E2E_BASE_URL=http://localhost:4200` when
 * developing a flow locally against `ng serve`.
 *
 * Scope (4 flows per `docs/vague-e-plan.md` § E2):
 *   01-auth-keycloak.spec.ts         — login alice → workspace → logout
 *   02-chat-drop-and-ask.spec.ts     — drop 2 PDF → citation [1] → jump
 *   03-hitl-approve.spec.ts          — hitl_pending → accept → resume
 *   04-debug-step-continue.spec.ts   — debug → step skill → continue
 *
 * Fixtures are seeded via `scripts/test-vm.sh` (alice@papai.ai /
 * Agentium2026 dev password + a workspace `playwright-staging` with
 * 2 capabilities + 1 system wired for the HITL flow).
 *
 * Run:
 *   npx playwright install chromium     # one-time
 *   npm run test:e2e                    # against E2E_BASE_URL
 *   npm run test:e2e -- --headed        # watch it click
 *   npm run test:e2e -- --debug         # step through
 */
export default defineConfig({
  testDir: './e2e/tests',
  outputDir: './e2e/results',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI
    ? [['github'], ['html', { outputFolder: 'e2e/report', open: 'never' }]]
    : [['list'], ['html', { outputFolder: 'e2e/report', open: 'never' }]],

  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },

  use: {
    baseURL: process.env['E2E_BASE_URL'] ?? 'https://agentium.papai.ai',
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
    screenshot: 'only-on-failure',
    ignoreHTTPSErrors: true,
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  webServer: process.env['E2E_BASE_URL']?.includes('localhost')
    ? {
        command: 'npm run start',
        url: 'http://localhost:4200',
        reuseExistingServer: true,
        timeout: 60_000,
      }
    : undefined,
});
