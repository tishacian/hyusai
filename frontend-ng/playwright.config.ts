import { defineConfig, devices } from '@playwright/test';

const chromiumExecutable = process.env['E2E_CHROMIUM_EXECUTABLE'];
const hostResolverRules = process.env['E2E_HOST_RESOLVER_RULES'];
const junitOutput = process.env['PLAYWRIGHT_JUNIT_OUTPUT_NAME'] ?? 'e2e/results/junit.xml';
const launchOptions = chromiumExecutable || hostResolverRules
  ? {
      ...(chromiumExecutable ? { executablePath: chromiumExecutable } : {}),
      ...(hostResolverRules
        ? { args: [`--host-resolver-rules=${hostResolverRules}`] }
        : {}),
    }
  : undefined;

/**
 * Agentium E2E test config (Vague E / E2).
 *
 * Target is the staging VM at `https://agentium.papai.ai` by default
 * so the test harness hits a realistic Keycloak + Qdrant + Postgres
 * stack. Override with `E2E_BASE_URL=http://localhost:4200` when
 * developing a flow locally against `ng serve`.
 *
 * Scope (E2 critical flows + E1.5 guardrail):
 *   01-auth-keycloak.spec.ts         — login alice → workspace → logout
 *   02-chat-drop-and-ask.spec.ts     — drop 2 PDF → citation [1] → jump
 *   03-hitl-approve.spec.ts          — hitl_pending → accept → resume
 *   04-debug-step-continue.spec.ts   — debug → step skill → continue
 *   05-eval-canonical-answer.spec.ts — canonical answer deterministic hit
 *
 * Fixtures: alice@acme.test/alice-demo comes from the tenant-isolation
 * smoke. PDFs + HITL/debug systems are generated dynamically by specs.
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
  forbidOnly: !!process.env['CI'],
  retries: process.env['CI'] ? 2 : 0,
  workers: 1,
  reporter: process.env['CI']
    ? [
        ['list'],
        ['junit', { outputFile: junitOutput, embedAnnotationsAsProperties: true }],
        ['html', { outputFolder: 'e2e/report', open: 'never' }],
      ]
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
    ...(launchOptions ? { launchOptions } : {}),
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
