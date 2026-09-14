#!/usr/bin/env node

/**
 * Fail-closed runner for the two remaining core product browser release gates.
 *
 * It drives the existing Playwright specs — the first-use golden path and the
 * core product accessibility matrix — against one explicitly selected isolated
 * workspace, in that order, stopping at the first failure. Every precondition
 * is checked before a browser is spawned: the release command never falls back
 * to the fixture demo defaults, and it refuses a non-loopback target unless the
 * operator opts in.
 *
 * Usage: `npm run check:core-release [-- --golden-only | --accessibility-only]`
 */

import { spawn as spawnProcess } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { isAbsolute, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const PROJECT_ROOT = resolve(fileURLToPath(import.meta.url), '..', '..');
const PLAYWRIGHT_CLI = join(PROJECT_ROOT, 'node_modules', '@playwright', 'test', 'cli.js');

/** Exit code used for every precondition failure, to keep it distinct from Playwright's own 1. */
export const CONFIG_EXIT_CODE = 2;

export const DEFAULT_ARTIFACT_ROOT = 'e2e/results/core-release';

export const LOOPBACK_HOSTS = Object.freeze(['localhost', '127.0.0.1', '::1']);

export const COMMON_REQUIRED_ENV = Object.freeze([
  'E2E_BASE_URL',
  'E2E_USERNAME',
  'E2E_PASSWORD',
  'E2E_WORKSPACE_SLUG',
]);

export const CORE_RELEASE_GATES = Object.freeze([
  Object.freeze({
    name: 'golden-path',
    spec: 'e2e/tests/00-first-use-golden-path.spec.ts',
    activationEnv: 'E2E_GOLDEN_PATH',
    requiredEnv: Object.freeze(['E2E_GOLDEN_PROVIDER', 'E2E_GOLDEN_MODEL']),
  }),
  Object.freeze({
    name: 'core-accessibility',
    spec: 'e2e/tests/00-core-product-accessibility.spec.ts',
    activationEnv: 'E2E_CORE_ACCESSIBILITY',
    requiredEnv: Object.freeze([]),
  }),
]);

const ACTIVATION_ENV_NAMES = Object.freeze(CORE_RELEASE_GATES.map((gate) => gate.activationEnv));

const SECRET_ENV_PATTERN = /(PASSWORD|SECRET|TOKEN|API_KEY|APIKEY|CREDENTIAL|COOKIE|BEARER)/i;

export class ReleaseGateConfigError extends Error {
  constructor(problems) {
    super(problems.join('\n- '));
    this.name = 'ReleaseGateConfigError';
    this.problems = problems;
  }
}

/** Strips the brackets the WHATWG URL parser keeps around IPv6 hosts. */
function bareHostname(hostname) {
  const lowered = hostname.toLowerCase();
  return lowered.startsWith('[') && lowered.endsWith(']') ? lowered.slice(1, -1) : lowered;
}

export function isLoopbackHost(hostname) {
  return LOOPBACK_HOSTS.includes(bareHostname(hostname ?? ''));
}

/**
 * Accepts an http/https URL and refuses anything that is not loopback unless
 * `E2E_RELEASE_GATE_ALLOW_REMOTE=1` was set on purpose.
 */
export function validateBaseUrl(rawBaseUrl, { allowRemote = false } = {}) {
  let url;
  try {
    url = new URL(rawBaseUrl);
  } catch {
    return { problem: `E2E_BASE_URL is not a valid URL: ${rawBaseUrl}` };
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    return { problem: `E2E_BASE_URL must be http or https, got ${url.protocol.replace(':', '')}` };
  }
  if (!isLoopbackHost(url.hostname) && !allowRemote) {
    return {
      problem:
        `E2E_BASE_URL ${url.origin} is not a loopback target; these gates mutate the selected `
        + 'workspace. Set E2E_RELEASE_GATE_ALLOW_REMOTE=1 to run them against it on purpose.',
    };
  }
  return { url };
}

export function selectGates(argv) {
  const goldenOnly = argv.includes('--golden-only');
  const accessibilityOnly = argv.includes('--accessibility-only');
  const unknown = argv.filter((arg) => arg !== '--golden-only' && arg !== '--accessibility-only');

  const problems = [];
  if (unknown.length > 0) {
    problems.push(`unsupported argument(s): ${unknown.join(', ')}`);
  }
  if (goldenOnly && accessibilityOnly) {
    problems.push('--golden-only and --accessibility-only are mutually exclusive');
  }
  if (problems.length > 0) return { problems };

  if (goldenOnly) return { mode: 'golden-only', gates: [CORE_RELEASE_GATES[0]], problems };
  if (accessibilityOnly) {
    return { mode: 'accessibility-only', gates: [CORE_RELEASE_GATES[1]], problems };
  }
  return { mode: 'all', gates: [...CORE_RELEASE_GATES], problems };
}

function presentValue(env, name) {
  const value = env[name];
  return typeof value === 'string' && value.trim() !== '' ? value : undefined;
}

/**
 * Resolves the whole run up front so a missing precondition fails before any
 * browser is launched. Every problem found is reported together.
 *
 * @throws {ReleaseGateConfigError}
 */
export function resolveReleaseGateConfig(argv = [], env = {}) {
  const { mode, gates = [], problems: selectionProblems } = selectGates(argv);
  const problems = [...selectionProblems];

  const requiredEnv = [...COMMON_REQUIRED_ENV, ...gates.flatMap((gate) => [...gate.requiredEnv])];
  for (const name of requiredEnv) {
    if (presentValue(env, name) === undefined) {
      problems.push(`${name} is required and must not be empty (fixture demo defaults are not used here)`);
    }
  }

  const rawBaseUrl = presentValue(env, 'E2E_BASE_URL');
  let baseUrl;
  if (rawBaseUrl !== undefined) {
    const { url, problem } = validateBaseUrl(rawBaseUrl, {
      allowRemote: env['E2E_RELEASE_GATE_ALLOW_REMOTE'] === '1',
    });
    if (problem) problems.push(problem);
    else baseUrl = url;
  }

  if (problems.length > 0) throw new ReleaseGateConfigError(problems);

  const rawArtifactRoot = presentValue(env, 'E2E_CORE_RELEASE_ARTIFACT_DIR') ?? DEFAULT_ARTIFACT_ROOT;
  const artifactRoot = isAbsolute(rawArtifactRoot)
    ? rawArtifactRoot
    : join(PROJECT_ROOT, rawArtifactRoot);

  return {
    mode,
    gates,
    artifactRoot,
    baseUrl: baseUrl.origin + (baseUrl.pathname === '/' ? '' : baseUrl.pathname),
    workspaceSlug: env['E2E_WORKSPACE_SLUG'],
    provider: presentValue(env, 'E2E_GOLDEN_PROVIDER'),
    model: presentValue(env, 'E2E_GOLDEN_MODEL'),
  };
}

/** Every gate writes into its own subtree so a later run cannot mix the two. */
export function gateArtifactPaths(artifactRoot, gateName) {
  const base = join(artifactRoot, gateName);
  return {
    base,
    output: join(base, 'output'),
    blob: join(base, 'blob'),
    report: join(base, 'report'),
    junit: join(base, 'junit.xml'),
  };
}

export function buildPlaywrightArgs(gate, artifactPaths) {
  return [
    PLAYWRIGHT_CLI,
    'test',
    gate.spec,
    '--project=chromium',
    '--workers=1',
    `--output=${artifactPaths.output}`,
    '--reporter=list,html,junit,blob',
  ];
}

/**
 * Keeps the caller environment the specs need (credentials, provider, proxy,
 * PATH) and turns on exactly one gate, explicitly clearing the other one.
 */
export function buildGateEnv(callerEnv, gate, artifactPaths) {
  const gateEnv = { ...callerEnv };
  for (const name of ACTIVATION_ENV_NAMES) delete gateEnv[name];
  gateEnv[gate.activationEnv] = '1';
  gateEnv['PLAYWRIGHT_JUNIT_OUTPUT_NAME'] = artifactPaths.junit;
  gateEnv['PLAYWRIGHT_BLOB_OUTPUT_DIR'] = artifactPaths.blob;
  gateEnv['PLAYWRIGHT_HTML_OUTPUT_DIR'] = artifactPaths.report;
  gateEnv['PLAYWRIGHT_HTML_OPEN'] = 'never';
  return gateEnv;
}

export function secretValues(env) {
  return Object.entries(env)
    .filter(([name, value]) => SECRET_ENV_PATTERN.test(name) && typeof value === 'string' && value.trim() !== '')
    .map(([, value]) => value)
    // Longest first so an overlapping short secret cannot leave a tail behind.
    .sort((a, b) => b.length - a.length);
}

export function redactSecrets(message, env) {
  return secretValues(env).reduce(
    (redacted, secret) => redacted.split(secret).join('«redacted»'),
    String(message),
  );
}

async function defaultSpawn(command, args, options) {
  return await new Promise((resolvePromise, rejectPromise) => {
    const child = spawnProcess(command, args, options);
    child.on('error', rejectPromise);
    child.on('close', (code, signal) => resolvePromise({ exitCode: code, signal }));
  });
}

function defaultMkdir(directory) {
  mkdirSync(directory, { recursive: true });
}

/**
 * @param {object} [dependencies] Injection points so the unit tests never
 *   launch a real browser or touch the filesystem.
 */
export async function runCoreReleaseGates({
  argv = [],
  env = {},
  spawn = defaultSpawn,
  mkdir = defaultMkdir,
  now = () => Date.now(),
  log = (message) => console.log(message),
  logError = (message) => console.error(message),
  nodeExecutable = process.execPath,
} = {}) {
  const write = (message) => log(redactSecrets(message, env));
  const writeError = (message) => logError(redactSecrets(message, env));

  let config;
  try {
    config = resolveReleaseGateConfig(argv, env);
  } catch (error) {
    if (!(error instanceof ReleaseGateConfigError)) throw error;
    writeError(`core release gates refused to start:\n- ${error.problems.join('\n- ')}`);
    return { exitCode: CONFIG_EXIT_CODE, mode: undefined, results: [] };
  }

  write(
    `core release gates: mode=${config.mode} target=${config.baseUrl} `
    + `workspace=${config.workspaceSlug} artifacts=${config.artifactRoot}`,
  );

  const results = [];
  for (const gate of config.gates) {
    const artifactPaths = gateArtifactPaths(config.artifactRoot, gate.name);
    for (const directory of [artifactPaths.base, artifactPaths.output, artifactPaths.blob, artifactPaths.report]) {
      mkdir(directory);
    }

    const provenance = gate.name === 'golden-path'
      ? ` provider=${config.provider} model=${config.model}`
      : '';
    write(`core release gates: running ${gate.name} — ${gate.spec}${provenance}`);

    const startedAt = now();
    const { exitCode, signal } = await spawn(
      nodeExecutable,
      buildPlaywrightArgs(gate, artifactPaths),
      {
        cwd: PROJECT_ROOT,
        env: buildGateEnv(env, gate, artifactPaths),
        shell: false,
        stdio: 'inherit',
      },
    );
    const elapsedMs = now() - startedAt;
    const resolvedExitCode = exitCode ?? (signal ? 1 : 0);
    results.push({ gate: gate.name, exitCode: resolvedExitCode, elapsedMs });

    const elapsed = `${(elapsedMs / 1000).toFixed(1)}s`;
    if (resolvedExitCode !== 0) {
      writeError(
        `core release gates: ${gate.name} FAILED after ${elapsed} (exit ${resolvedExitCode}); `
        + `evidence in ${artifactPaths.base}`,
      );
      return { exitCode: resolvedExitCode, mode: config.mode, results };
    }
    write(`core release gates: ${gate.name} passed in ${elapsed}`);
  }

  write(`core release gates: all ${results.length} gate(s) passed`);
  return { exitCode: 0, mode: config.mode, results };
}

async function main() {
  const { exitCode } = await runCoreReleaseGates({
    argv: process.argv.slice(2),
    env: process.env,
  });
  process.exitCode = exitCode;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) await main();
