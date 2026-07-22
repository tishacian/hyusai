import { createHash } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { expect, test, type Page, type TestInfo } from '@playwright/test';

/**
 * Lot 8 — authenticated, marker-discovered authoritative value-loop canary.
 *
 * Nothing identifies the target by workspace slug, System name or database
 * id. The test discovers the unique `experience.value_loop_canary = "v1"`
 * marker in the principal's authorized workspaces. Actuation applies one
 * bounded, deterministic change to the canary policy's HITL threshold.
 *
 * The suite is intentionally opt-in and mutating. It persists an audited
 * scenario, simulation, approval, effective actuation and measurement attempt.
 * Idempotency keys are content-addressed so retries reuse the same
 * operation records. Traces, video and automatic screenshots remain off
 * because authentication uses a live principal.
 */

const enabled = process.env['E2E_LOT8_CANARY'] === '1';
const username = process.env['E2E_USERNAME'];
const password = process.env['E2E_PASSWORD'];
const expectedSha = (process.env['E2E_EXPECTED_SHA'] ?? '').trim().toLowerCase();
const evidencePath = process.env['E2E_LOT8_EVIDENCE'];
const ACTUATOR = 'control_policy.guardrails.patch.v1';
const protectedCi = process.env['CI'] === 'true'
  && process.env['CI_COMMIT_REF_PROTECTED'] === 'true';

test.use({ trace: 'off', video: 'off', screenshot: 'off' });

interface WorkspaceSummary {
  id: string;
  slug: string;
  name: string;
  settings?: Record<string, unknown>;
}

interface SystemRow {
  id: string;
  name: string;
  capability_id?: string | null;
  settings?: Record<string, unknown>;
}

interface RunRow {
  id: string;
  system_id?: string | null;
  status: string;
  started_at?: string | null;
  completed_at?: string | null;
  outcome?: {
    value_estimated?: number | null;
    value_source?: 'auto' | 'operator' | 'unset';
    measurement_provenance?: {
      schema_version?: number;
      source?: 'runtime_auto' | 'operator_override';
      actor?: string;
      recorded_at?: string;
      artifact_ref?: string;
    } | null;
    baseline_eligible?: boolean;
    baseline_ineligible_reason?: string | null;
  };
}

interface ControlPolicyRow {
  id: string;
  target_id?: string | null;
  mandatory_hitl_if_confidence_below?: number | null;
}

interface ValueSimulation {
  id: string;
  scenario_id: string;
  system_id: string;
  evidence_type: 'simulation';
  model: string;
  projected_outcome: Record<string, unknown>;
  recommended_action: { actuator?: string; patch?: Record<string, unknown> };
  provenance: Record<string, unknown>;
  confidence: number;
}

interface ValueMeasurement {
  id: string;
  scenario_id: string;
  system_id: string;
  simulation_id: string;
  source_run_id: string | null;
  status: 'measured' | 'not_measured';
  reason: string | null;
  evidence_type: 'run' | null;
  forecast_delta: Record<string, number> | null;
  assumption_verdict: 'confirmed' | 'partially_confirmed' | 'not_confirmed' | 'not_evaluable';
  assumption_evaluation: {
    verdict?: string;
    causality?: string;
    criteria?: unknown[];
  };
  observed_outcome?: {
    measurement_provenance?: {
      schema_version?: number;
      source?: 'runtime_auto' | 'operator_override';
      actor?: string;
      recorded_at?: string;
      artifact_ref?: string;
    };
  } | null;
}

interface ValueScenario {
  id: string;
  system_id: string;
  source_run_id: string;
  status: 'decision_proposed' | 'simulated' | 'approved' | 'acted' | 'measured';
  objective: string;
  decision: { id: string; status: string; title: string } | null;
  simulations: ValueSimulation[];
  action: { id: string; actuator: string; status: 'succeeded'; changed_fields: string[] } | null;
  measurements: ValueMeasurement[];
}

interface SystemValueLoop {
  schema_version: 1;
  system_id: string;
  actuator: typeof ACTUATOR;
  items: ValueScenario[];
}

interface PortfolioValueLoop {
  schema_version: 1;
  scope: 'portfolio';
  state: 'available' | 'not_configured';
  systems: Array<{
    system_id: string;
    actuator_state: 'available' | 'not_configured';
  }>;
  outcomes: { state: 'available' | 'not_measured' };
  risks: { state: 'available' | 'not_measured'; items: Array<{ scenario_id: string }> };
  arbitrations: {
    state: 'available' | 'not_measured';
    items: Array<{ id: string; scenario_id: string; system_id: string }>;
  };
  scenarios: {
    state: 'available' | 'not_measured';
    items: Array<{
      id: string;
      system_id: string;
      objective: string;
      outcome: { state: 'available' | 'not_measured'; measurement_id: string | null };
    }>;
  };
  simulation_is_measurement: false;
}

interface ApiResult<T> {
  ok: boolean;
  status: number;
  body: T;
}

interface BuildInfo {
  revision: string;
  service: 'backend' | 'frontend';
  revision_verified: boolean;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function features(settings: Record<string, unknown> | undefined): Record<string, unknown> {
  return asRecord(settings?.['features']) ?? {};
}

function marker(system: SystemRow): unknown {
  return asRecord(asRecord(system.settings)?.['experience'])?.['value_loop_canary'];
}

function unwrap<T>(body: T[] | Record<string, T[]>, key: string): T[] {
  if (Array.isArray(body)) return body;
  return Array.isArray(body?.[key]) ? body[key] : [];
}

function sha256(value: string): string {
  return createHash('sha256').update(value).digest('hex');
}

function writeEvidence(path: string | undefined, value: unknown): void {
  if (!path) return;
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`, { encoding: 'utf8', mode: 0o600 });
}

async function login(page: Page): Promise<WorkspaceSummary[]> {
  expect(username, 'E2E_USERNAME is required for the Lot 8 canary').toBeTruthy();
  expect(password, 'E2E_PASSWORD is required for the Lot 8 canary').toBeTruthy();
  await page.goto('/auth/signin');
  const result = await page.evaluate(
    async ({ email, secret }) => {
      const response = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password: secret, remember_me: false }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok || !body.token) {
        return { ok: false, status: response.status, workspaces: [] };
      }
      localStorage.setItem('agentium_token', `Bearer ${body.token}`);
      if (body.refresh_token) localStorage.setItem('agentium_refresh_token', body.refresh_token);
      const memberships = await fetch('/api/v1/auth/workspaces', {
        headers: { Authorization: `Bearer ${body.token}` },
      });
      return {
        ok: memberships.ok,
        status: memberships.status,
        workspaces: memberships.ok ? await memberships.json().catch(() => []) : [],
      };
    },
    { email: username as string, secret: password as string },
  );
  expect(result.ok, `login or workspace discovery failed (${result.status})`).toBe(true);
  const memberships = (Array.isArray(result.workspaces) ? result.workspaces : []) as WorkspaceSummary[];
  expect(memberships.length).toBeGreaterThan(0);
  return memberships;
}

async function logout(page: Page): Promise<void> {
  await page.evaluate(async () => {
    const refreshToken = localStorage.getItem('agentium_refresh_token');
    if (refreshToken) {
      await fetch('/api/v1/auth/logout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      }).catch(() => undefined);
    }
    localStorage.removeItem('agentium_token');
    localStorage.removeItem('agentium_refresh_token');
  }).catch(() => undefined);
}

async function api<T>(
  page: Page,
  workspaceSlug: string,
  path: string,
  options: { method?: 'GET' | 'POST'; body?: unknown; idempotencyKey?: string } = {},
): Promise<ApiResult<T>> {
  return page.evaluate(
    async ({ slug, apiPath, method, body, idempotencyKey }) => {
      const headers: Record<string, string> = {
        Authorization: localStorage.getItem('agentium_token') || '',
        'X-Workspace-Slug': slug,
      };
      if (body !== undefined) headers['Content-Type'] = 'application/json';
      if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey;
      const response = await fetch(`/api/v1${apiPath}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      const text = await response.text();
      let parsed: unknown = null;
      if (text) {
        try { parsed = JSON.parse(text); } catch { parsed = text; }
      }
      return { ok: response.ok, status: response.status, body: parsed };
    },
    {
      slug: workspaceSlug,
      apiPath: path,
      method: options.method ?? 'GET',
      body: options.body,
      idempotencyKey: options.idempotencyKey,
    },
  ) as Promise<ApiResult<T>>;
}

async function triggerAndAwaitMeasuredRun(
  page: Page,
  workspace: WorkspaceSummary,
  system: SystemRow,
  contractFingerprint: string,
): Promise<{ run: RunRow | null; reason: string | null }> {
  const triggered = await api<{ id?: string }>(
    page,
    workspace.slug,
    `/systems/${encodeURIComponent(system.id)}/runs`,
    {
      method: 'POST',
      body: {
        trigger: 'lot8_value_loop_canary',
        input_ref: {
          query: 'Run the configured System after the governed value-loop actuation.',
          lot8_value_loop_canary: true,
          contract_sha256: contractFingerprint,
        },
      },
    },
  );
  if (!triggered.ok || !triggered.body.id) {
    return { run: null, reason: `post_action_run_trigger_failed_${triggered.status}` };
  }

  const runId = triggered.body.id;
  const deadline = Date.now() + 5 * 60 * 1_000;
  while (Date.now() < deadline) {
    const current = await api<RunRow>(
      page,
      workspace.slug,
      `/runs/${encodeURIComponent(runId)}`,
    );
    if (!current.ok) {
      return { run: null, reason: `post_action_run_unreadable_${current.status}` };
    }
    if (current.body.status === 'completed') {
      const source = current.body.outcome?.value_source;
      const value = current.body.outcome?.value_estimated;
      if (
        (source === 'auto' || source === 'operator')
        && typeof value === 'number'
        && Number.isFinite(value)
      ) {
        return { run: current.body, reason: null };
      }
      return { run: null, reason: 'post_action_outcome_not_measured_by_runtime' };
    }
    if (['failed', 'cancelled', 'hitl_pending'].includes(current.body.status)) {
      return { run: null, reason: `post_action_run_${current.body.status}` };
    }
    await page.waitForTimeout(1_000);
  }
  return { run: null, reason: 'post_action_run_timeout' };
}

async function triggerAndAwaitBaselineRun(
  page: Page,
  workspace: WorkspaceSummary,
  system: SystemRow,
): Promise<{ run: RunRow | null; reason: string | null }> {
  const triggered = await api<{ id?: string }>(
    page,
    workspace.slug,
    `/systems/${encodeURIComponent(system.id)}/runs`,
    {
      method: 'POST',
      body: {
        trigger: 'manual',
        input_ref: {
          query: 'Run the configured System to establish a fresh measured baseline.',
        },
      },
    },
  );
  if (!triggered.ok || !triggered.body.id) {
    return { run: null, reason: `baseline_run_trigger_failed_${triggered.status}` };
  }

  const deadline = Date.now() + 5 * 60 * 1_000;
  while (Date.now() < deadline) {
    const current = await api<RunRow>(
      page,
      workspace.slug,
      `/runs/${encodeURIComponent(triggered.body.id)}`,
    );
    if (!current.ok) {
      return { run: null, reason: `baseline_run_unreadable_${current.status}` };
    }
    if (current.body.status === 'completed') {
      const outcome = current.body.outcome;
      if (
        outcome?.baseline_eligible === true
        && outcome.measurement_provenance?.source === 'runtime_auto'
        && typeof outcome.value_estimated === 'number'
        && Number.isFinite(outcome.value_estimated)
      ) {
        return { run: current.body, reason: null };
      }
      return {
        run: null,
        reason: outcome?.baseline_ineligible_reason ?? 'baseline_runtime_provenance_unavailable',
      };
    }
    if (['failed', 'cancelled', 'hitl_pending'].includes(current.body.status)) {
      return { run: null, reason: `baseline_run_${current.body.status}` };
    }
    await page.waitForTimeout(2_000);
  }
  return { run: null, reason: 'baseline_run_timeout' };
}

async function buildInfo(page: Page, path: string): Promise<BuildInfo> {
  const response = await page.request.get(`${path}?canary=${Date.now()}`, {
    headers: { Accept: 'application/json', 'Cache-Control': 'no-cache' },
  });
  expect(response.ok(), `${path} must be readable`).toBe(true);
  return response.json() as Promise<BuildInfo>;
}

async function switchWorkspace(
  page: Page,
  from: WorkspaceSummary,
  to: WorkspaceSummary,
): Promise<void> {
  const nextRequest = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return url.pathname.startsWith('/api/v1/')
      && request.headers()['x-workspace-slug'] === to.slug;
  });
  await page.getByTitle(from.name, { exact: true }).click();
  await page.locator('app-title-bar button').filter({ hasText: to.name }).first().click();
  await nextRequest;
  await expect.poll(() => page.evaluate(() => localStorage.getItem('agentium_workspace_slug')))
    .toBe(to.slug);
}

test.describe.serial('Lot 8 — authenticated authoritative value-loop canary', () => {
  test.skip(!enabled, 'Set E2E_LOT8_CANARY=1 to execute the mutating Lot 8 canary');
  test.setTimeout(8 * 60 * 1_000);

  test.afterEach(async ({ page }) => logout(page));

  test('discovers one marked System and proves persisted simulate-to-measure semantics', async ({ page }, testInfo: TestInfo) => {
    expect(expectedSha, 'E2E_EXPECTED_SHA must be the deployed full SHA').toMatch(/^[0-9a-f]{40}$/);
    if (process.env['CI'] === 'true') {
      expect(process.env['CI_COMMIT_SHA']?.toLowerCase(), 'CI must test its own exact deployed SHA')
        .toBe(expectedSha);
      expect(process.env['CI_COMMIT_REF_PROTECTED'], 'formal evidence requires a protected ref')
        .toBe('true');
      expect(process.env['CI_PIPELINE_ID']).toBeTruthy();
      expect(process.env['CI_JOB_ID']).toBeTruthy();
    }
    expect(await buildInfo(page, '/api/v1/build-info')).toMatchObject({
      revision: expectedSha,
      service: 'backend',
      revision_verified: true,
    });
    expect(await buildInfo(page, '/build-info.json')).toMatchObject({
      revision: expectedSha,
      service: 'frontend',
      revision_verified: true,
    });

    const memberships = await login(page);
    const discoveries: Array<{ workspace: WorkspaceSummary; system: SystemRow }> = [];
    for (const summary of memberships) {
      const workspaceResult = await api<WorkspaceSummary>(
        page,
        summary.slug,
        `/auth/workspaces/${encodeURIComponent(summary.slug)}`,
      );
      expect(workspaceResult.ok).toBe(true);
      const systemsResult = await api<SystemRow[] | { systems: SystemRow[] }>(
        page,
        summary.slug,
        '/systems?include_retired=true&limit=2147483647',
      );
      expect(systemsResult.ok).toBe(true);
      for (const system of unwrap(systemsResult.body, 'systems')) {
        if (
          marker(system) === 'v1'
          && features(workspaceResult.body.settings)['value_loop_v1'] === true
        ) {
          discoveries.push({ workspace: workspaceResult.body, system });
        }
      }
    }
    expect(discoveries, 'exactly one authorized System must own the active v1 value-loop marker')
      .toHaveLength(1);
    const { workspace, system } = discoveries[0];
    const alternate = memberships.find((candidate) => candidate.id !== workspace.id);
    expect(alternate, 'a second workspace is required to prove atomic context purge').toBeTruthy();
    expect(system.capability_id, 'the marked System must keep its Capability identity').toBeTruthy();
    expect(features(workspace.settings)['cockpit_router_axes_v4']).toBe(true);
    expect(features(workspace.settings)['system_360_projection_v1']).toBe(true);

    const baselineResult = await triggerAndAwaitBaselineRun(page, workspace, system);
    expect(
      baselineResult.reason,
      'the canary needs a fresh, non-seed Run with server runtime provenance',
    ).toBeNull();
    expect(baselineResult.run).toBeTruthy();
    const baseline = baselineResult.run as RunRow;
    expect(baseline.system_id).toBe(system.id);
    expect(baseline.outcome?.baseline_eligible).toBe(true);
    expect(baseline.outcome?.measurement_provenance?.source).toBe('runtime_auto');

    const policiesResult = await api<{ policies: ControlPolicyRow[] }>(
      page,
      workspace.slug,
      `/control-plane/policies?scope=system&target_id=${encodeURIComponent(system.id)}`,
    );
    expect(policiesResult.ok).toBe(true);
    const policies = unwrap(policiesResult.body, 'policies');
    expect(policies, 'the canary System needs exactly one explicitly scoped ControlPolicy').toHaveLength(1);
    const threshold = policies[0].mandatory_hitl_if_confidence_below;
    expect(typeof threshold).toBe('number');
    expect(Number.isFinite(threshold)).toBe(true);
    expect(threshold as number).toBeGreaterThanOrEqual(0);
    expect(threshold as number).toBeLessThanOrEqual(1);
    const changedThreshold = (threshold as number) <= 0.9
      ? Number(((threshold as number) + 0.1).toFixed(6))
      : Number(((threshold as number) - 0.1).toFixed(6));
    expect(changedThreshold).not.toBe(threshold);

    const contractFingerprint = sha256([
      expectedSha,
      workspace.id,
      system.id,
      baseline.id,
      String(threshold),
      String(changedThreshold),
    ].join('|'));
    const key = (operation: string) => `agentium-lot8:${contractFingerprint}:${operation}`;
    const title = `Lot 8 canary ${contractFingerprint.slice(0, 12)}`;
    const createBody = {
      source_run_id: baseline.id,
      objective: 'Prove the governed value loop through an effective bounded guardrail change.',
      title,
      rationale: { source: 'authenticated-lot8-canary', contract_sha256: contractFingerprint },
    };

    const created = await api<ValueScenario>(
      page,
      workspace.slug,
      `/systems/${encodeURIComponent(system.id)}/value-loop/scenarios`,
      { method: 'POST', body: createBody, idempotencyKey: key('create') },
    );
    expect(created.ok, `scenario creation failed (${created.status})`).toBe(true);
    const createdAgain = await api<ValueScenario>(
      page,
      workspace.slug,
      `/systems/${encodeURIComponent(system.id)}/value-loop/scenarios`,
      { method: 'POST', body: createBody, idempotencyKey: key('create') },
    );
    expect(createdAgain.ok).toBe(true);
    expect(createdAgain.body.id).toBe(created.body.id);
    const scenarioId = created.body.id;
    expect(created.body.decision?.id, 'scenario creation must persist its Decision').toBeTruthy();
    const decisionId = created.body.decision!.id;

    const patch = { mandatory_hitl_if_confidence_below: changedThreshold };
    const simulated = await api<ValueSimulation>(
      page,
      workspace.slug,
      `/systems/${encodeURIComponent(system.id)}/value-loop/scenarios/${encodeURIComponent(scenarioId)}/simulate`,
      { method: 'POST', body: { recommended_patch: patch }, idempotencyKey: key('simulate') },
    );
    expect(simulated.ok, `simulation failed (${simulated.status})`).toBe(true);
    expect(simulated.body).toMatchObject({
      scenario_id: scenarioId,
      system_id: system.id,
      evidence_type: 'simulation',
    });
    expect(simulated.body.model).toMatch(/^system-steering:/);
    expect(simulated.body.provenance['system_id']).toBe(system.id);
    expect(simulated.body.recommended_action).toEqual({ actuator: ACTUATOR, patch });
    const simulatedAgain = await api<ValueSimulation>(
      page,
      workspace.slug,
      `/systems/${encodeURIComponent(system.id)}/value-loop/scenarios/${encodeURIComponent(scenarioId)}/simulate`,
      { method: 'POST', body: { recommended_patch: patch }, idempotencyKey: key('simulate') },
    );
    expect(simulatedAgain.ok).toBe(true);
    expect(simulatedAgain.body.id).toBe(simulated.body.id);

    await page.evaluate((slug) => localStorage.setItem('agentium_workspace_slug', slug), workspace.slug);
    await page.goto(
      `/systems/${encodeURIComponent(system.id)}?lens=steer&capabilityId=${encodeURIComponent(system.capability_id as string)}&facet=overview`,
    );
    const simulatedCard = page.locator(`[data-scenario-id="${scenarioId}"]`);
    await expect(simulatedCard).toHaveAttribute(
      'data-scenario-status',
      /^(simulated|approved|acted|measured)$/,
    );
    let uiApprovalTransition = false;
    if (await simulatedCard.getAttribute('data-scenario-status') === 'simulated') {
      await simulatedCard.locator('[data-testid="value-loop-approve"]').click();
      await expect(simulatedCard).toHaveAttribute('data-scenario-status', 'approved');
      uiApprovalTransition = true;
    }
    const approvedRead = await api<SystemValueLoop>(
      page,
      workspace.slug,
      `/systems/${encodeURIComponent(system.id)}/value-loop`,
    );
    expect(approvedRead.ok).toBe(true);
    expect(['approved', 'acted', 'measured']).toContain(
      approvedRead.body.items.find((item) => item.id === scenarioId)?.status,
    );

    const acted = await api<{ id: string; actuator: string; status: string; changed_fields: string[] }>(
      page,
      workspace.slug,
      `/systems/${encodeURIComponent(system.id)}/value-loop/scenarios/${encodeURIComponent(scenarioId)}/act`,
      { method: 'POST', body: { actuator: ACTUATOR, patch }, idempotencyKey: key('act') },
    );
    expect(acted.ok, `actuation failed (${acted.status})`).toBe(true);
    expect(acted.body).toMatchObject({ actuator: ACTUATOR, status: 'succeeded' });
    expect(acted.body.changed_fields).toContain('mandatory_hitl_if_confidence_below');
    const actedAgain = await api<{ id: string }>(
      page,
      workspace.slug,
      `/systems/${encodeURIComponent(system.id)}/value-loop/scenarios/${encodeURIComponent(scenarioId)}/act`,
      { method: 'POST', body: { actuator: ACTUATOR, patch }, idempotencyKey: key('act') },
    );
    expect(actedAgain.ok).toBe(true);
    expect(actedAgain.body.id).toBe(acted.body.id);
    const policiesAfterAct = await api<{ policies: ControlPolicyRow[] }>(
      page,
      workspace.slug,
      `/control-plane/policies?scope=system&target_id=${encodeURIComponent(system.id)}`,
    );
    expect(policiesAfterAct.ok).toBe(true);
    const persistedPolicies = unwrap(policiesAfterAct.body, 'policies');
    expect(persistedPolicies).toHaveLength(1);
    expect(persistedPolicies[0].id).toBe(policies[0].id);
    expect(persistedPolicies[0].mandatory_hitl_if_confidence_below).toBe(changedThreshold);

    const postAction = await triggerAndAwaitMeasuredRun(
      page,
      workspace,
      system,
      contractFingerprint,
    );
    const measured = await api<ValueMeasurement>(
      page,
      workspace.slug,
      `/systems/${encodeURIComponent(system.id)}/value-loop/scenarios/${encodeURIComponent(scenarioId)}/measure`,
      {
        method: 'POST',
        body: { source_run_id: postAction.run?.id ?? null },
        idempotencyKey: key('measure'),
      },
    );
    expect(measured.ok, `measurement failed (${measured.status})`).toBe(true);
    expect(measured.body.evidence_type).not.toBe('simulation');
    expect(measured.body.simulation_id).toBe(simulated.body.id);
    expect(measured.body.assumption_evaluation.verdict).toBe(measured.body.assumption_verdict);
    expect(measured.body.assumption_evaluation.causality).toBe('not_established');
    if (measured.body.status === 'measured') {
      expect(measured.body.evidence_type).toBe('run');
      expect(measured.body.source_run_id).toBeTruthy();
      expect(measured.body.forecast_delta).not.toBeNull();
      expect(measured.body.assumption_verdict).not.toBe('not_evaluable');
    } else {
      expect(measured.body.evidence_type).toBeNull();
      expect(measured.body.reason).toBeTruthy();
      expect(measured.body.forecast_delta).toBeNull();
      expect(measured.body.assumption_verdict).toBe('not_evaluable');
    }
    const measuredAgain = await api<ValueMeasurement>(
      page,
      workspace.slug,
      `/systems/${encodeURIComponent(system.id)}/value-loop/scenarios/${encodeURIComponent(scenarioId)}/measure`,
      {
        method: 'POST',
        body: { source_run_id: postAction.run?.id ?? null },
        idempotencyKey: key('measure'),
      },
    );
    expect(measuredAgain.ok).toBe(true);
    expect(measuredAgain.body.id).toBe(measured.body.id);

    const loopResult = await api<SystemValueLoop>(
      page,
      workspace.slug,
      `/systems/${encodeURIComponent(system.id)}/value-loop`,
    );
    expect(loopResult.ok).toBe(true);
    expect(loopResult.body).toMatchObject({ schema_version: 1, system_id: system.id, actuator: ACTUATOR });
    const persisted = loopResult.body.items.find((item) => item.id === scenarioId);
    expect(persisted, 'the command chain must be persisted in the authoritative read model').toBeTruthy();
    expect(persisted?.simulations.at(-1)?.id).toBe(simulated.body.id);
    expect(persisted?.action?.id).toBe(acted.body.id);
    expect(persisted?.measurements.at(-1)?.id).toBe(measured.body.id);
    expect(persisted?.status).toBe(measured.body.status === 'measured' ? 'measured' : 'acted');

    await page.goto(
      `/systems/${encodeURIComponent(system.id)}?lens=steer&capabilityId=${encodeURIComponent(system.capability_id as string)}&facet=overview`,
    );
    await expect(
      page.locator(
        `#ck-tabpanel-overview app-system-perspective section[data-system-id="${system.id}"][data-perspective-lens="steer"]`,
      ),
    ).toBeVisible();
    await expect(page.locator('app-system-view ck-object-header')).toContainText(system.name);
    await expect(page.locator('app-semantic-zoom-breadcrumb')).toContainText(system.name);
    const valueLoop = page.locator('app-system-value-loop [data-testid="system-value-loop"]');
    await expect(valueLoop).toBeVisible();
    const scenarioCard = valueLoop.locator(`[data-scenario-id="${scenarioId}"]`);
    await expect(scenarioCard).toBeVisible();
    await expect(scenarioCard).toContainText(title);
    await expect(scenarioCard).toContainText(
      measured.body.status === 'measured' ? 'Observed evidence' : 'Not measured',
    );
    expect(new URL(page.url()).searchParams.get('lens')).toBe('steer');
    expect(new URL(page.url()).searchParams.get('facet')).toBe('overview');

    const buildLink = page.locator('app-side-rail a.ck-rail-item').filter({ hasText: /Build/i });
    await expect(buildLink).toHaveCount(1);
    await buildLink.click();
    await expect.poll(() => new URL(page.url()).searchParams.get('lens')).toBe('build');
    await expect(page.locator('app-system-value-loop')).toHaveCount(0);
    await page.goBack();
    await expect.poll(() => new URL(page.url()).searchParams.get('lens')).toBe('steer');
    await expect(scenarioCard).toBeVisible();
    await page.reload();
    await expect(page.locator(`[data-scenario-id="${scenarioId}"]`)).toBeVisible();
    expect(new URL(page.url()).searchParams.get('facet')).toBe('overview');

    const portfolioResult = await api<PortfolioValueLoop>(
      page,
      workspace.slug,
      '/hypervisor/value-loop',
    );
    expect(portfolioResult.ok).toBe(true);
    expect(portfolioResult.body).toMatchObject({
      schema_version: 1,
      scope: 'portfolio',
      state: 'available',
      simulation_is_measurement: false,
    });
    expect(portfolioResult.body.systems).toContainEqual(expect.objectContaining({
      system_id: system.id,
      actuator_state: 'available',
    }));
    expect(portfolioResult.body.scenarios.items).toContainEqual(expect.objectContaining({
      id: scenarioId,
      system_id: system.id,
      objective: createBody.objective,
      outcome: expect.objectContaining({
        state: measured.body.status === 'measured' ? 'available' : 'not_measured',
        measurement_id: measured.body.id,
      }),
    }));
    expect(portfolioResult.body.arbitrations.items).toContainEqual(expect.objectContaining({
      id: decisionId,
      scenario_id: scenarioId,
      system_id: system.id,
    }));

    await page.goto('/hypervisor');
    const portfolioSection = page.locator('[data-testid="portfolio-value-loop"]');
    await expect(portfolioSection).toBeVisible();
    await expect(portfolioSection).toContainText('VALUE LOOP · PORTFOLIO');
    await expect(portfolioSection).toContainText(createBody.objective);
    await expect(portfolioSection).toContainText('Simulation ≠ measurement');

    await switchWorkspace(page, workspace, alternate as WorkspaceSummary);
    await expect.poll(() => new URL(page.url()).pathname).not.toContain(`/systems/${system.id}`);
    await expect(page.locator(`[data-scenario-id="${scenarioId}"]`)).toHaveCount(0);
    expect(page.url()).not.toContain(system.id);

    const screenshot = testInfo.outputPath('lot8-value-loop-canary.png');
    await page.screenshot({ path: screenshot, animations: 'disabled' });
    await testInfo.attach('lot8-value-loop-canary', { path: screenshot, contentType: 'image/png' });
    const measurementProvenance = measured.body.observed_outcome?.measurement_provenance;
    const measurementPromotable = measured.body.status === 'measured'
      && measured.body.evidence_type === 'run'
      && Boolean(measured.body.source_run_id)
      && Boolean(postAction.run)
      && (measurementProvenance?.source === 'runtime_auto'
        || measurementProvenance?.source === 'operator_override')
      && Boolean(measurementProvenance?.actor)
      && measured.body.simulation_id === simulated.body.id
      && measured.body.assumption_verdict !== 'not_evaluable'
      && measured.body.assumption_evaluation.causality === 'not_established'
      && measured.body.forecast_delta !== null
      && /^sha256:[0-9a-f]{64}$/.test(measurementProvenance?.artifact_ref ?? '');
    const promotionEligible = protectedCi && measurementPromotable;
    writeEvidence(evidencePath, {
      schema_version: 2,
      kind: 'lot8_value_loop_observation',
      claim: 'LOT8-AUTHORITATIVE-VALUE-LOOP',
      status: promotionEligible
        ? 'behavior_observed'
        : measurementPromotable ? 'runner_verified' : 'not_promotable',
      promotion_eligible: promotionEligible,
      non_promotable_reason: promotionEligible
        ? null
        : postAction.reason ?? (protectedCi ? 'measurement_not_measured' : 'runner_not_protected'),
      tested_revision: expectedSha,
      runner: {
        protected_ci: protectedCi,
        pipeline_id: process.env['CI_PIPELINE_ID'] ?? null,
        job_id: process.env['CI_JOB_ID'] ?? null,
      },
      contract_sha256: contractFingerprint,
      target: {
        workspace_sha256: sha256(workspace.id),
        system_sha256: sha256(system.id),
        baseline_run_sha256: sha256(baseline.id),
      },
      operations: {
        scenario_sha256: sha256(scenarioId),
        decision_sha256: sha256(decisionId),
        simulation_sha256: sha256(simulated.body.id),
        action_sha256: sha256(acted.body.id),
        measurement_sha256: sha256(measured.body.id),
        observed_run_sha256: measured.body.source_run_id
          ? sha256(measured.body.source_run_id)
          : null,
        measurement_status: measured.body.status,
      },
      checks: {
        create: true,
        simulate: true,
        approve: true,
        act: true,
        measure: measurementPromotable,
        idempotency: true,
        tenant_isolation: true,
        simulation_not_measurement: true,
      },
      diagnostics: {
        marker_discovery: true,
        real_actuator_effective_value_change: true,
        independent_measurement_provenance: measurementPromotable,
        persisted_read_model: true,
        ui_steer_projection: true,
        reload_and_history: true,
        atomic_workspace_purge: true,
        ui_approval_transition: uiApprovalTransition,
        control_policy_reread_after_act: true,
        measurement_bound_to_approved_simulation: measured.body.simulation_id === simulated.body.id,
        forecast_assumption_evaluation: measured.body.assumption_evaluation.causality === 'not_established',
        portfolio_tenant_scope: portfolioResult.body.scenarios.items.every(
          (item) => item.system_id === system.id,
        ),
        ui_portfolio_projection: true,
      },
      generated_at: new Date().toISOString(),
    });
  });
});
