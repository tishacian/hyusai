import assert from 'node:assert/strict';
import test from 'node:test';

import {
  CONFIG_EXIT_CODE,
  CORE_RELEASE_GATES,
  buildGateEnv,
  gateArtifactPaths,
  isLoopbackHost,
  redactSecrets,
  resolveReleaseGateConfig,
  runCoreReleaseGates,
  validateBaseUrl,
} from './run-core-release-gates.mjs';

const ARTIFACT_ROOT = '/tmp/agentium-core-release-spec';

function completeEnv(overrides = {}) {
  return {
    PATH: '/usr/bin',
    E2E_BASE_URL: 'http://localhost:4200',
    E2E_USERNAME: 'release-runner@example.test',
    E2E_PASSWORD: 'super-secret-password',
    E2E_WORKSPACE_SLUG: 'isolated-release-workspace',
    E2E_GOLDEN_PROVIDER: 'ollama',
    E2E_GOLDEN_MODEL: 'llama3.1',
    E2E_CORE_RELEASE_ARTIFACT_DIR: ARTIFACT_ROOT,
    ...overrides,
  };
}

/** Drives the runner with every side effect captured, so no browser is launched. */
function harness(exitCodes = [0, 0]) {
  const spawnCalls = [];
  const madeDirectories = [];
  const out = [];
  const err = [];
  let clock = 0;

  const run = async (argv = [], env = completeEnv()) =>
    await runCoreReleaseGates({
      argv,
      env,
      spawn: async (command, args, options) => {
        spawnCalls.push({ command, args, options });
        return { exitCode: exitCodes[spawnCalls.length - 1] ?? 0, signal: null };
      },
      mkdir: (directory) => {
        madeDirectories.push(directory);
      },
      now: () => {
        clock += 1500;
        return clock;
      },
      log: (message) => out.push(message),
      logError: (message) => err.push(message),
      nodeExecutable: '/usr/local/bin/node',
    });

  return { spawnCalls, madeDirectories, out, err, run };
}

test('refuses to start when required configuration is missing, before spawning Playwright', async () => {
  const bench = harness();
  const env = completeEnv();
  delete env['E2E_USERNAME'];
  delete env['E2E_WORKSPACE_SLUG'];
  env['E2E_GOLDEN_MODEL'] = '   ';

  const { exitCode } = await bench.run([], env);

  assert.equal(exitCode, CONFIG_EXIT_CODE);
  assert.deepEqual(bench.spawnCalls, []);
  assert.deepEqual(bench.madeDirectories, []);
  const report = bench.err.join('\n');
  assert.match(report, /E2E_USERNAME is required/);
  assert.match(report, /E2E_WORKSPACE_SLUG is required/);
  assert.match(report, /E2E_GOLDEN_MODEL is required/);
});

test('does not fall back to the fixture demo defaults for provider and model', async () => {
  const bench = harness();
  const env = completeEnv();
  delete env['E2E_GOLDEN_PROVIDER'];

  assert.equal((await bench.run([], env)).exitCode, CONFIG_EXIT_CODE);
  assert.deepEqual(bench.spawnCalls, []);

  // The accessibility gate does not need them, so the same env runs fine alone.
  const accessibilityBench = harness([0]);
  assert.equal((await accessibilityBench.run(['--accessibility-only'], env)).exitCode, 0);
  assert.equal(accessibilityBench.spawnCalls.length, 1);
});

test('refuses a non-loopback target unless the operator opts in explicitly', async () => {
  const remote = completeEnv({ E2E_BASE_URL: 'https://agentium.papai.ai' });

  const refused = harness();
  assert.equal((await refused.run([], remote)).exitCode, CONFIG_EXIT_CODE);
  assert.deepEqual(refused.spawnCalls, []);
  assert.match(refused.err.join('\n'), /E2E_RELEASE_GATE_ALLOW_REMOTE=1/);

  const allowed = harness();
  const optedIn = { ...remote, E2E_RELEASE_GATE_ALLOW_REMOTE: '1' };
  assert.equal((await allowed.run([], optedIn)).exitCode, 0);
  assert.equal(allowed.spawnCalls.length, 2);
});

test('accepts IPv4 and IPv6 loopback targets and rejects non-http schemes', () => {
  assert.ok(isLoopbackHost('localhost'));
  assert.ok(isLoopbackHost('127.0.0.1'));
  assert.ok(isLoopbackHost('[::1]'));
  assert.ok(!isLoopbackHost('agentium.papai.ai'));
  assert.ok(!isLoopbackHost('127.0.0.1.example.test'));

  for (const base of ['http://localhost:4200', 'http://127.0.0.1:4200', 'http://[::1]:4200']) {
    const config = resolveReleaseGateConfig([], completeEnv({ E2E_BASE_URL: base }));
    assert.equal(config.baseUrl, new URL(base).origin);
  }

  assert.match(
    String(validateBaseUrl('ftp://127.0.0.1/').problem),
    /must be http or https/,
  );
  assert.match(String(validateBaseUrl('not-a-url').problem), /not a valid URL/);
});

test('spawns the local Playwright CLI through the current Node binary without a shell', async () => {
  const bench = harness();
  await bench.run(['--golden-only']);

  assert.equal(bench.spawnCalls.length, 1);
  const [call] = bench.spawnCalls;
  assert.equal(call.command, '/usr/local/bin/node');
  assert.equal(call.options.shell, false);
  assert.match(call.args[0], /node_modules\/@playwright\/test\/cli\.js$/);
  assert.deepEqual(call.args.slice(1), [
    'test',
    'e2e/tests/00-first-use-golden-path.spec.ts',
    '--project=chromium',
    '--workers=1',
    `--output=${ARTIFACT_ROOT}/golden-path/output`,
    '--reporter=list,html,junit,blob',
  ]);
});

test('activates exactly one gate flag per run and preserves the caller environment', async () => {
  const bench = harness();
  await bench.run([], completeEnv({ E2E_CORE_ACCESSIBILITY: '1', E2E_GOLDEN_PATH: '1' }));

  const [golden, accessibility] = bench.spawnCalls.map((call) => call.options.env);

  assert.equal(golden['E2E_GOLDEN_PATH'], '1');
  assert.ok(!('E2E_CORE_ACCESSIBILITY' in golden));
  assert.equal(accessibility['E2E_CORE_ACCESSIBILITY'], '1');
  assert.ok(!('E2E_GOLDEN_PATH' in accessibility));

  for (const gateEnv of [golden, accessibility]) {
    assert.equal(gateEnv['PATH'], '/usr/bin');
    assert.equal(gateEnv['E2E_BASE_URL'], 'http://localhost:4200');
    assert.equal(gateEnv['E2E_USERNAME'], 'release-runner@example.test');
    assert.equal(gateEnv['E2E_PASSWORD'], 'super-secret-password');
    assert.equal(gateEnv['E2E_WORKSPACE_SLUG'], 'isolated-release-workspace');
    assert.equal(gateEnv['PLAYWRIGHT_HTML_OPEN'], 'never');
  }
});

test('keeps each gate blob, report, and JUnit output in its own subdirectory', async () => {
  const bench = harness();
  await bench.run();

  const [golden, accessibility] = bench.spawnCalls.map((call) => call.options.env);
  assert.equal(golden['PLAYWRIGHT_BLOB_OUTPUT_DIR'], `${ARTIFACT_ROOT}/golden-path/blob`);
  assert.equal(golden['PLAYWRIGHT_HTML_OUTPUT_DIR'], `${ARTIFACT_ROOT}/golden-path/report`);
  assert.equal(golden['PLAYWRIGHT_JUNIT_OUTPUT_NAME'], `${ARTIFACT_ROOT}/golden-path/junit.xml`);
  assert.equal(accessibility['PLAYWRIGHT_BLOB_OUTPUT_DIR'], `${ARTIFACT_ROOT}/core-accessibility/blob`);
  assert.equal(accessibility['PLAYWRIGHT_HTML_OUTPUT_DIR'], `${ARTIFACT_ROOT}/core-accessibility/report`);
  assert.equal(accessibility['PLAYWRIGHT_JUNIT_OUTPUT_NAME'], `${ARTIFACT_ROOT}/core-accessibility/junit.xml`);

  assert.ok(bench.madeDirectories.length > 0);
  assert.ok(bench.madeDirectories.every((directory) => directory.startsWith(`${ARTIFACT_ROOT}/`)));
  assert.deepEqual(
    [...new Set(bench.madeDirectories)].filter((directory) => directory.endsWith('/blob')).sort(),
    [`${ARTIFACT_ROOT}/core-accessibility/blob`, `${ARTIFACT_ROOT}/golden-path/blob`],
  );
});

test('defaults the artifact root to e2e/results/core-release', () => {
  const env = completeEnv();
  delete env['E2E_CORE_RELEASE_ARTIFACT_DIR'];
  const config = resolveReleaseGateConfig([], env);

  assert.ok(config.artifactRoot.endsWith('/e2e/results/core-release'));
  assert.equal(
    gateArtifactPaths(config.artifactRoot, 'golden-path').junit,
    `${config.artifactRoot}/golden-path/junit.xml`,
  );
});

test('runs the golden path before accessibility and stops at the first failure', async () => {
  const passing = harness([0, 0]);
  assert.equal((await passing.run()).exitCode, 0);
  assert.deepEqual(passing.spawnCalls.map((call) => call.args[2]), [
    'e2e/tests/00-first-use-golden-path.spec.ts',
    'e2e/tests/00-core-product-accessibility.spec.ts',
  ]);

  const failing = harness([3, 0]);
  const result = await failing.run();
  assert.equal(result.exitCode, 3);
  assert.equal(failing.spawnCalls.length, 1);
  assert.match(failing.err.join('\n'), /golden-path FAILED after 1\.5s \(exit 3\)/);
});

test('supports the two explicit single-gate modes and rejects combining them', async () => {
  const goldenOnly = harness([0]);
  assert.equal((await goldenOnly.run(['--golden-only'])).exitCode, 0);
  assert.deepEqual(goldenOnly.spawnCalls.map((call) => call.args[2]), [
    'e2e/tests/00-first-use-golden-path.spec.ts',
  ]);

  const accessibilityOnly = harness([0]);
  assert.equal((await accessibilityOnly.run(['--accessibility-only'])).exitCode, 0);
  assert.deepEqual(accessibilityOnly.spawnCalls.map((call) => call.args[2]), [
    'e2e/tests/00-core-product-accessibility.spec.ts',
  ]);

  const both = harness();
  assert.equal((await both.run(['--golden-only', '--accessibility-only'])).exitCode, CONFIG_EXIT_CODE);
  assert.deepEqual(both.spawnCalls, []);
  assert.match(both.err.join('\n'), /mutually exclusive/);

  const unknown = harness();
  assert.equal((await unknown.run(['--headed'])).exitCode, CONFIG_EXIT_CODE);
  assert.deepEqual(unknown.spawnCalls, []);
  assert.match(unknown.err.join('\n'), /unsupported argument\(s\): --headed/);
});

test('logs the operator-facing facts without ever printing a credential', async () => {
  const bench = harness([1]);
  const env = completeEnv({ E2E_GOLDEN_API_KEY: 'sk-live-should-never-appear' });
  await bench.run([], env);

  const transcript = [...bench.out, ...bench.err].join('\n');
  assert.ok(!transcript.includes('super-secret-password'));
  assert.ok(!transcript.includes('sk-live-should-never-appear'));
  assert.match(transcript, /target=http:\/\/localhost:4200/);
  assert.match(transcript, /workspace=isolated-release-workspace/);
  assert.match(transcript, /provider=ollama model=llama3\.1/);
  assert.match(transcript, /running golden-path — e2e\/tests\/00-first-use-golden-path\.spec\.ts/);
});

test('redacts secret-shaped environment values out of any message', () => {
  const env = { E2E_PASSWORD: 'pw', E2E_GOLDEN_API_KEY: 'key-1234', E2E_USERNAME: 'alice' };
  assert.equal(redactSecrets('token key-1234 for pw', env), 'token «redacted» for «redacted»');
  // Non-secret variables stay readable so the log is still useful.
  assert.equal(redactSecrets('user alice', env), 'user alice');
});

test('only mentions provider and model for the gate that needs them', async () => {
  const bench = harness([0]);
  await bench.run(['--accessibility-only']);
  assert.ok(!bench.out.join('\n').includes('provider='));
});

test('names the two core release gates and their activation flags', () => {
  assert.deepEqual(
    CORE_RELEASE_GATES.map((gate) => [gate.name, gate.activationEnv]),
    [['golden-path', 'E2E_GOLDEN_PATH'], ['core-accessibility', 'E2E_CORE_ACCESSIBILITY']],
  );
  assert.deepEqual(
    buildGateEnv({ KEEP: 'yes' }, CORE_RELEASE_GATES[1], gateArtifactPaths('/r', 'core-accessibility'))['KEEP'],
    'yes',
  );
});
