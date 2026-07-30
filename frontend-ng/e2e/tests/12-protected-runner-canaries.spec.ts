import { createHash } from 'node:crypto';
import {
  chmodSync,
  lstatSync,
  mkdirSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { isAbsolute, join } from 'node:path';
import { expect, test, type BrowserContext, type Page } from '@playwright/test';
import {
  findOctocityForbiddenPresentationTerms,
  OCTOCITY_MISSION_ROOM_PROFILE,
  SENTINEL_MISSION_ROOM_PROFILE,
} from '../../src/app/features/mission-room/mission-room.presentation';

/**
 * Release A — content-free evidence produced by the protected browser runner.
 *
 * The suite is deliberately opt-in. It discovers the three workspace roles
 * from their persisted settings contracts; no workspace slug, UUID or display
 * name is configured or embedded here.
 *
 * Live inventory contract (post-Nawa landing): exactly one workspace carries
 * the `business_end_user` navigation profile with the four business surfaces
 * (Andritz). The Nawa workspace deliberately carries a `standard` profile —
 * `065_nawa_itsd` documents why the business shell cannot serve its routes —
 * so it never matches the business predicate, and showcase/default workspaces
 * carry no business navigation profile at all.
 *
 * Required environment:
 *   E2E_PROTECTED_RUNNER_CANARIES=1
 *   E2E_USERNAME=...
 *   E2E_PASSWORD=...
 *   E2E_EXPECTED_SHA=<deployed 40-hex SHA>
 *   E2E_DEPLOYMENT_ID=<Release A deployment id>
 *   E2E_EVIDENCE_CLASS=acceptance|release
 *   E2E_PRINCIPAL_CLASS=operator_personal_admin|automation_non_personal
 *   E2E_FORMAL_RELEASE_ELIGIBLE=true|false
 *   E2E_PROTECTED_EVIDENCE_DIR=<absolute, fresh private directory>
 *
 * Traces, screenshots and video are always disabled. The five emitted
 * `${token}.artifact` files contain only booleans, counts, hashes and release
 * identity. They are compact canonical JSON, owner-private and never replaced.
 */

const enabled = process.env['E2E_PROTECTED_RUNNER_CANARIES'] === '1';
const username = process.env['E2E_USERNAME'];
const password = process.env['E2E_PASSWORD'];

// The business-app workspace ships three apps through four entitled surfaces
// (FSE reports rides the capture router as its own surface since Lot 4).
const BUSINESS_SURFACES = Object.freeze([
  'chat',
  'client360-pdr',
  'knowledge-capture',
  'fse-reports',
] as const);
const BUSINESS_ROUTES = Object.freeze([
  { path: '/chat', selector: 'app-chat-workspace' },
  { path: '/client360', selector: 'app-client360-page' },
  { path: '/knowledge/capture', selector: 'app-capture-router' },
  { path: '/knowledge/interventions', selector: 'app-capture-router' },
] as const);
const SENTINEL_ACTION_PACKS = Object.freeze([
  'global_voice_v1',
  'sentinel_ci_aya_v1',
  'sentinel_ci_aya_security_v1',
] as const);
const OCTOCITY_ACTION_PACKS = Object.freeze([
  'global_voice_v1',
  'octave_mission_room_v1',
  'octave_security_v1',
] as const);

type ArtifactToken =
  | 'canary-andritz'
  | 'canary-sentinel'
  | 'canary-octocity'
  | 'canary-livekit'
  | 'browser-permission-probe';

type ContentFreeCheck = boolean | number;
type ContentFreeChecks = Record<string, ContentFreeCheck>;

interface WorkspaceMembership {
  id?: unknown;
  slug?: unknown;
  name?: unknown;
  settings?: unknown;
}

interface WorkspaceTarget {
  id: string;
  slug: string;
  name: string | null;
  settings: Record<string, unknown>;
}

interface WorkspaceTargets {
  andritz: WorkspaceTarget;
  sentinel: WorkspaceTarget;
  octocity: WorkspaceTarget;
}

interface EvidenceRuntime {
  expectedSha: string;
  deploymentId: string;
  evidenceDir: string;
  evidenceClass: 'acceptance' | 'release';
  principalClass: 'operator_personal_admin' | 'automation_non_personal';
  formalReleaseEligible: boolean;
}

interface BuildChecks {
  backend_build_info_exact: true;
  frontend_build_info_exact: true;
}

interface MissionRoomContract {
  role_marker_current: boolean;
  navigation_read: boolean;
  navigation_profile_bound: boolean;
  navigation_item_count: number;
  navigation_system_bindings_complete: boolean;
  branding_settings_complete: boolean;
  branding_api_bound: boolean;
  branding_ui_bound: boolean;
  action_pack_count: number;
  action_packs_exact: boolean;
  action_pack_namespace_isolated: boolean;
  cross_terms_absent: boolean;
}

test.use({
  trace: 'off',
  video: 'off',
  screenshot: 'off',
  permissions: [],
});

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string')
    ? [...value]
    : [];
}

function arraysEqual(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== 'object') {
    const encoded = JSON.stringify(value);
    if (encoded === undefined) throw new Error('Evidence contains a non-JSON value');
    return encoded;
  }
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`)
    .join(',')}}`;
}

function sha256(value: string): string {
  return createHash('sha256').update(value, 'utf8').digest('hex');
}

function runtimeEvidence(): EvidenceRuntime {
  const expectedSha = process.env['E2E_EXPECTED_SHA'] ?? '';
  const deploymentId = process.env['E2E_DEPLOYMENT_ID'] ?? '';
  const evidenceClass = process.env['E2E_EVIDENCE_CLASS'] ?? '';
  const principalClass = process.env['E2E_PRINCIPAL_CLASS'] ?? '';
  const formalRaw = process.env['E2E_FORMAL_RELEASE_ELIGIBLE'] ?? '';
  const evidenceDir = process.env['E2E_PROTECTED_EVIDENCE_DIR'] ?? '';

  if (!/^[0-9a-f]{40}$/.test(expectedSha)) {
    throw new Error('E2E_EXPECTED_SHA must be a full lowercase Git SHA');
  }
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{5,95}$/.test(deploymentId)) {
    throw new Error('E2E_DEPLOYMENT_ID is not a canonical Release A deployment id');
  }
  if (evidenceClass !== 'acceptance' && evidenceClass !== 'release') {
    throw new Error('E2E_EVIDENCE_CLASS must be acceptance or release');
  }
  if (
    principalClass !== 'operator_personal_admin'
    && principalClass !== 'automation_non_personal'
  ) {
    throw new Error('E2E_PRINCIPAL_CLASS is not an approved principal class');
  }
  if (formalRaw !== 'true' && formalRaw !== 'false') {
    throw new Error('E2E_FORMAL_RELEASE_ELIGIBLE must be explicitly true or false');
  }
  if (!evidenceDir || !isAbsolute(evidenceDir)) {
    throw new Error('E2E_PROTECTED_EVIDENCE_DIR must be an absolute path');
  }

  const formalReleaseEligible = formalRaw === 'true';
  if (
    evidenceClass === 'release'
    && (!formalReleaseEligible || principalClass !== 'automation_non_personal')
  ) {
    throw new Error('Release evidence requires formal non-personal automation');
  }
  if (evidenceClass === 'acceptance' && formalReleaseEligible) {
    throw new Error('Acceptance evidence cannot claim formal release eligibility');
  }
  const ciSha = process.env['CI_COMMIT_SHA'];
  const protectedRef = process.env['CI_COMMIT_REF_PROTECTED'];
  if (ciSha && ciSha !== expectedSha) {
    throw new Error('CI_COMMIT_SHA and E2E_EXPECTED_SHA are inconsistent');
  }
  if (formalReleaseEligible && process.env['CI'] && protectedRef !== 'true') {
    throw new Error('A formal CI artifact requires a protected ref');
  }

  mkdirSync(evidenceDir, { recursive: true, mode: 0o700 });
  const directory = lstatSync(evidenceDir);
  if (!directory.isDirectory() || directory.isSymbolicLink()) {
    throw new Error('E2E_PROTECTED_EVIDENCE_DIR must be a real directory');
  }

  return {
    expectedSha,
    deploymentId,
    evidenceDir,
    evidenceClass,
    principalClass,
    formalReleaseEligible,
  };
}

function workspaceTarget(value: WorkspaceMembership): WorkspaceTarget | null {
  if (
    typeof value.id !== 'string'
    || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value.id)
    || typeof value.slug !== 'string'
    || !/^[a-z0-9][a-z0-9._-]{0,99}$/.test(value.slug)
  ) {
    return null;
  }
  const settings = asRecord(value.settings);
  if (!settings) return null;
  return {
    id: value.id,
    slug: value.slug,
    name: typeof value.name === 'string' ? value.name : null,
    settings,
  };
}

function isAndritzSettings(settings: Record<string, unknown>): boolean {
  const navigation = asRecord(settings['navigation_profile']);
  const features = asRecord(settings['features']);
  return (
    navigation?.['key'] === 'business_end_user'
    && navigation['default_route'] === '/chat'
    && navigation['advanced_access'] === 'admin_only'
    && arraysEqual(stringList(navigation['primary_surfaces']), BUSINESS_SURFACES)
    && features?.['app_entitlements_v1'] === true
    && features['workspace_experience_v2'] === true
  );
}

function missionRoomProfile(settings: Record<string, unknown>): string | null {
  const missionRoom = asRecord(settings['mission_room']);
  return missionRoom?.['enabled'] === true && typeof missionRoom['profile'] === 'string'
    ? missionRoom['profile']
    : null;
}

function discoverTargets(memberships: WorkspaceMembership[]): WorkspaceTargets {
  const targets = memberships
    .map(workspaceTarget)
    .filter((target): target is WorkspaceTarget => target !== null);
  const andritz = targets.filter((target) => isAndritzSettings(target.settings));
  const sentinel = targets.filter(
    (target) => missionRoomProfile(target.settings) === SENTINEL_MISSION_ROOM_PROFILE,
  );
  const octocity = targets.filter(
    (target) => missionRoomProfile(target.settings) === OCTOCITY_MISSION_ROOM_PROFILE,
  );

  expect(andritz.length, 'settings must identify exactly one business-app workspace').toBe(1);
  expect(sentinel.length, 'settings must identify exactly one government Mission Room').toBe(1);
  expect(octocity.length, 'settings must identify exactly one institutional Mission Room').toBe(1);
  expect(
    new Set([andritz[0].id, sentinel[0].id, octocity[0].id]).size,
    'the three settings roles must resolve to distinct workspaces',
  ).toBe(3);
  return { andritz: andritz[0], sentinel: sentinel[0], octocity: octocity[0] };
}

async function loginAndDiscover(page: Page): Promise<WorkspaceTargets> {
  if (!username || !password) {
    throw new Error('E2E_USERNAME and E2E_PASSWORD are required');
  }
  await page.goto('/auth/signin');
  const login = await page.evaluate(
    async ({ email, secret }) => {
      const response = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password: secret, remember_me: false }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok || typeof body.token !== 'string' || !body.token) {
        return { authenticated: false, status: response.status, workspaces: [] };
      }
      localStorage.setItem('agentium_token', `Bearer ${body.token}`);
      if (typeof body.refresh_token === 'string' && body.refresh_token) {
        localStorage.setItem('agentium_refresh_token', body.refresh_token);
      }
      const memberships = await fetch('/api/v1/auth/workspaces', {
        headers: { Authorization: `Bearer ${body.token}` },
      });
      return {
        authenticated: memberships.ok,
        status: memberships.status,
        workspaces: memberships.ok ? await memberships.json().catch(() => []) : [],
      };
    },
    { email: username, secret: password },
  );
  expect(login.authenticated, `authentication or settings discovery failed (${login.status})`).toBe(true);
  const memberships = Array.isArray(login.workspaces)
    ? login.workspaces as WorkspaceMembership[]
    : [];
  expect(memberships.length, 'the protected principal has no workspace settings to inspect')
    .toBeGreaterThan(0);
  return discoverTargets(memberships);
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
    localStorage.removeItem('agentium_workspace_slug');
  }).catch(() => undefined);
}

async function selectWorkspace(page: Page, target: WorkspaceTarget): Promise<void> {
  await page.evaluate((slug) => {
    localStorage.setItem('agentium_workspace_slug', slug);
  }, target.slug);
}

async function buildChecks(page: Page, expectedSha: string): Promise<BuildChecks> {
  const inspect = async (path: string, service: 'backend' | 'frontend'): Promise<boolean> => {
    const response = await page.request.get(`${path}?protected-canary=${Date.now()}`, {
      headers: { Accept: 'application/json', 'Cache-Control': 'no-cache' },
    });
    if (!response.ok()) return false;
    const body = asRecord(await response.json().catch(() => null));
    return (
      body?.['revision'] === expectedSha
      && body['service'] === service
      && body['revision_verified'] === true
    );
  };
  const [backend, frontend] = await Promise.all([
    inspect('/api/v1/build-info', 'backend'),
    inspect('/build-info.json', 'frontend'),
  ]);
  expect(backend, 'backend build-info must match E2E_EXPECTED_SHA exactly').toBe(true);
  expect(frontend, 'frontend build-info must match E2E_EXPECTED_SHA exactly').toBe(true);
  return {
    backend_build_info_exact: true,
    frontend_build_info_exact: true,
  };
}

function assertChecksAreContentFree(checks: ContentFreeChecks): void {
  for (const [key, value] of Object.entries(checks)) {
    if (!/^[a-z][a-z0-9_]{2,95}$/.test(key)) {
      throw new Error('Evidence contains a non-canonical check key');
    }
    if (
      typeof value !== 'boolean'
      && !(typeof value === 'number' && Number.isInteger(value) && value >= 0)
    ) {
      throw new Error('Evidence checks may contain only booleans and non-negative integers');
    }
  }
}

function writeEvidence(
  runtime: EvidenceRuntime,
  token: ArtifactToken,
  target: WorkspaceTarget,
  checks: ContentFreeChecks,
): void {
  assertChecksAreContentFree(checks);
  const artifact = {
    schema_version: 1,
    kind: 'agentium-protected-runner-canary',
    profile: 'agentium-protected-runner-canary-v1',
    token,
    result: 'passed',
    evidence_class: runtime.evidenceClass,
    formal_release_eligible: runtime.formalReleaseEligible,
    deployment_id: runtime.deploymentId,
    tested_sha: runtime.expectedSha,
    principal_class: runtime.principalClass,
    workspace_sha256: sha256(target.id),
    checks,
    captured_at: new Date().toISOString(),
  };
  const expectedKeys = [
    'captured_at',
    'checks',
    'deployment_id',
    'evidence_class',
    'formal_release_eligible',
    'kind',
    'principal_class',
    'profile',
    'result',
    'schema_version',
    'tested_sha',
    'token',
    'workspace_sha256',
  ];
  if (!arraysEqual(Object.keys(artifact).sort(), expectedKeys)) {
    throw new Error('Evidence artifact schema differs');
  }
  const body = `${canonicalJson(artifact)}\n`;
  const forbiddenExactValues = [
    username,
    password,
    target.id,
    target.slug,
    target.name,
  ].filter((value): value is string => typeof value === 'string' && value.length > 0);
  const leaves = [
    artifact.kind,
    artifact.profile,
    artifact.result,
    artifact.evidence_class,
    artifact.token,
    artifact.tested_sha,
    artifact.deployment_id,
    artifact.principal_class,
    artifact.workspace_sha256,
    artifact.captured_at,
  ];
  if (leaves.some((value) => forbiddenExactValues.includes(value))) {
    throw new Error('Evidence attempted to serialize a private identity');
  }

  const output = join(runtime.evidenceDir, `${token}.artifact`);
  writeFileSync(output, body, { encoding: 'utf8', flag: 'wx', mode: 0o600 });
  chmodSync(output, 0o600);
  if ((statSync(output).mode & 0o777) !== 0o600) {
    throw new Error('Evidence artifact mode differs from 0600');
  }
}

async function currentSettingsStillMatch(
  page: Page,
  target: WorkspaceTarget,
  predicate: (settings: Record<string, unknown>) => boolean,
): Promise<boolean> {
  return page.evaluate(
    async ({ slug }) => {
      const response = await fetch(`/api/v1/auth/workspaces/${encodeURIComponent(slug)}`, {
        headers: {
          Authorization: localStorage.getItem('agentium_token') ?? '',
          'X-Workspace-Slug': slug,
        },
      });
      if (!response.ok) return { ok: false, settings: null };
      const body = await response.json().catch(() => null);
      return {
        ok: true,
        settings: body && typeof body === 'object' && !Array.isArray(body)
          ? body.settings
          : null,
      };
    },
    { slug: target.slug },
  ).then((result) => {
    const settings = asRecord(result.settings);
    return result.ok && settings !== null && predicate(settings);
  });
}

async function andritzDryRun(page: Page, target: WorkspaceTarget): Promise<{
  status_ok: boolean;
  dry_run_confirmed: boolean;
  no_rows_created: boolean;
  no_rows_updated: boolean;
  counters_content_free: boolean;
}> {
  return page.evaluate(async (slug) => {
    const response = await fetch('/api/v1/client360/engines/opportunities/run', {
      method: 'POST',
      headers: {
        Authorization: localStorage.getItem('agentium_token') ?? '',
        'Content-Type': 'application/json',
        'X-Workspace-Slug': slug,
      },
      body: JSON.stringify({ dry_run: true }),
    });
    const raw = await response.json().catch(() => null);
    const body = raw && typeof raw === 'object' && !Array.isArray(raw)
      ? raw as Record<string, unknown>
      : {};
    const counter = (key: string): number | null =>
      Number.isInteger(body[key]) && Number(body[key]) >= 0 ? Number(body[key]) : null;
    return {
      status_ok: response.status === 200,
      dry_run_confirmed: body['dry_run'] === true,
      no_rows_created: counter('created') === 0,
      no_rows_updated: counter('updated') === 0,
      counters_content_free: [
        counter('records_seen'),
        counter('candidate_mappings_created'),
        counter('opportunities_detected'),
        Array.isArray(body['preview']) ? body['preview'].length : null,
      ].every((value) => value !== null && value >= 0),
    };
  }, target.slug);
}

function missionRoomBrand(settings: Record<string, unknown>): Record<string, unknown> | null {
  const missionRoom = asRecord(settings['mission_room']);
  return asRecord(missionRoom?.['brand']) ?? asRecord(settings['workspace_app_brand']);
}

function missionRoomAssistant(settings: Record<string, unknown>): string | null {
  const missionRoom = asRecord(settings['mission_room']);
  const value = missionRoom?.['assistant_label'] ?? missionRoom?.['label'];
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function missionRoomCorpus(page: Page): Promise<string> {
  return page.locator('[data-mission-room-extension="mission-room"]').evaluate((root) => {
    const attributes = ['aria-label', 'aria-description', 'title', 'placeholder', 'alt'];
    const values = [root.textContent ?? ''];
    for (const element of [root, ...Array.from(root.querySelectorAll('*'))]) {
      for (const attribute of attributes) {
        const value = element.getAttribute(attribute);
        if (value) values.push(value);
      }
    }
    return values.join('\n');
  });
}

async function missionRoomContract(
  page: Page,
  target: WorkspaceTarget,
  profile: typeof SENTINEL_MISSION_ROOM_PROFILE | typeof OCTOCITY_MISSION_ROOM_PROFILE,
): Promise<MissionRoomContract> {
  await selectWorkspace(page, target);
  const expectedPacks = profile === SENTINEL_MISSION_ROOM_PROFILE
    ? SENTINEL_ACTION_PACKS
    : OCTOCITY_ACTION_PACKS;
  const expectedBrand = missionRoomBrand(target.settings);
  const expectedAssistant = missionRoomAssistant(target.settings);
  const expectedSettingsPacks = stringList(asRecord(target.settings['actions'])?.['enabled_packs']);
  const roleMarkerCurrent = await currentSettingsStillMatch(
    page,
    target,
    (settings) => (
      missionRoomProfile(settings) === profile
      && arraysEqual(
        stringList(asRecord(settings['actions'])?.['enabled_packs']),
        expectedPacks,
      )
      && canonicalJson(missionRoomBrand(settings)) === canonicalJson(expectedBrand)
      && missionRoomAssistant(settings) === expectedAssistant
    ),
  );
  await page.goto('/hypervisor');
  await expect(page.locator('app-mission-room')).toBeVisible();
  await expect(page.locator('[data-mission-room-extension="mission-room"]')).toBeVisible();

  const brandingSettingsComplete = Boolean(
    expectedBrand
    && typeof expectedBrand['label'] === 'string'
    && stringList(expectedBrand['lines']).length > 0
    && typeof expectedBrand['emblem'] === 'string'
    && typeof expectedBrand['style'] === 'string'
    && expectedAssistant,
  );

  const apiProjection = await page.evaluate(
    async ({ slug, expectedProfile, brandCanonical, assistant }) => {
      const headers = {
        Authorization: localStorage.getItem('agentium_token') ?? '',
        'X-Workspace-Slug': slug,
      };
      const response = await fetch('/api/v1/mission-room/navigation', { headers });
      const raw = await response.json().catch(() => null);
      const body = raw && typeof raw === 'object' && !Array.isArray(raw)
        ? raw as Record<string, unknown>
        : {};
      const app = body['app'] && typeof body['app'] === 'object' && !Array.isArray(body['app'])
        ? body['app'] as Record<string, unknown>
        : {};
      const items = Array.isArray(body['items']) ? body['items'] : [];
      const stable = (value: unknown): string => {
        if (value === null || typeof value !== 'object') {
          return JSON.stringify(value) ?? 'undefined';
        }
        if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`;
        const record = value as Record<string, unknown>;
        return `{${Object.keys(record).sort().map(
          (key) => `${JSON.stringify(key)}:${stable(record[key])}`,
        ).join(',')}}`;
      };
      return {
        navigation_read: response.status === 200,
        navigation_profile_bound: app['profile'] === expectedProfile,
        navigation_item_count: items.length,
        navigation_system_bindings_complete: items.length > 0 && items.every((item) => (
          item
          && typeof item === 'object'
          && !Array.isArray(item)
          && typeof (item as Record<string, unknown>)['system_id'] === 'string'
          && Boolean((item as Record<string, unknown>)['system_id'])
        )),
        branding_api_bound: stable(app['brand']) === brandCanonical
          && app['assistant_label'] === assistant,
      };
    },
    {
      slug: target.slug,
      expectedProfile: profile,
      brandCanonical: canonicalJson(expectedBrand),
      assistant: expectedAssistant,
    },
  );

  const brandingUiBound = await page.evaluate(
    ({ brand, assistant }) => {
      if (!brand || typeof assistant !== 'string') return false;
      const rail = document.querySelector('app-mission-rail .mission-rail');
      if (!rail) return false;
      const avatar = rail.querySelector('.assistant-avatar')?.textContent?.trim();
      const emblem = rail.querySelector('.brand-emblem')?.getAttribute('src');
      const wordmark = rail.querySelector('.brand-wordmark')?.textContent ?? '';
      const lines = Array.isArray(brand['lines']) ? brand['lines'] : [];
      const style = brand['style'];
      return (
        avatar === assistant
        && emblem === brand['emblem']
        && lines.every((line) => typeof line === 'string' && wordmark.includes(line))
        && (style === 'agentium'
          ? rail.classList.contains('agentium-brand')
          : !rail.classList.contains('agentium-brand'))
      );
    },
    { brand: expectedBrand, assistant: expectedAssistant },
  );

  const corpus = await missionRoomCorpus(page);
  const crossTermsAbsent = profile === OCTOCITY_MISSION_ROOM_PROFILE
    ? findOctocityForbiddenPresentationTerms(corpus).length === 0
    : !/Octocity|\bOCTAVE\b|\bAsteria\b|\bMeridian\b/i.test(corpus);
  const actionPacksExact = arraysEqual(expectedSettingsPacks, expectedPacks);
  const actionPackNamespaceIsolated = profile === SENTINEL_MISSION_ROOM_PROFILE
    ? expectedSettingsPacks.every(
      (pack) => pack === 'global_voice_v1' || pack.startsWith('sentinel_ci_'),
    ) && !expectedSettingsPacks.some((pack) => pack.startsWith('octave_'))
    : expectedSettingsPacks.every(
      (pack) => pack === 'global_voice_v1' || pack.startsWith('octave_'),
    ) && !expectedSettingsPacks.some((pack) => pack.startsWith('sentinel_ci_'));

  return {
    role_marker_current: roleMarkerCurrent,
    navigation_read: apiProjection.navigation_read,
    navigation_profile_bound: apiProjection.navigation_profile_bound,
    navigation_item_count: apiProjection.navigation_item_count,
    navigation_system_bindings_complete: apiProjection.navigation_system_bindings_complete,
    branding_settings_complete: brandingSettingsComplete,
    branding_api_bound: apiProjection.branding_api_bound,
    branding_ui_bound: brandingUiBound,
    action_pack_count: expectedSettingsPacks.length,
    action_packs_exact: actionPacksExact,
    action_pack_namespace_isolated: actionPackNamespaceIsolated,
    cross_terms_absent: crossTermsAbsent,
  };
}

async function livekitProjection(page: Page, target: WorkspaceTarget): Promise<{
  authenticated_config_read: boolean;
  public_state_shape_valid: boolean;
  secret_fields_absent: boolean;
  token_values_absent: boolean;
}> {
  return page.evaluate(async (slug) => {
    const response = await fetch('/api/v1/livekit/config', {
      headers: {
        Authorization: localStorage.getItem('agentium_token') ?? '',
        'X-Workspace-Slug': slug,
      },
    });
    const raw = await response.json().catch(() => null);
    const body = raw && typeof raw === 'object' && !Array.isArray(raw)
      ? raw as Record<string, unknown>
      : {};
    const forbiddenKeys = /(?:^|_)(?:token|password|secret|authorization|api_key|api_secret)(?:$|_)/i;
    const sensitiveValue = /(?:^|\s)Bearer\s+|eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/;
    let secretFieldsAbsent = true;
    let tokenValuesAbsent = true;
    const visit = (value: unknown): void => {
      if (Array.isArray(value)) {
        value.forEach(visit);
        return;
      }
      if (value && typeof value === 'object') {
        for (const [key, nested] of Object.entries(value as Record<string, unknown>)) {
          if (forbiddenKeys.test(key)) secretFieldsAbsent = false;
          visit(nested);
        }
        return;
      }
      if (typeof value === 'string' && sensitiveValue.test(value)) tokenValuesAbsent = false;
    };
    visit(body);
    return {
      authenticated_config_read: response.status === 200,
      public_state_shape_valid:
        typeof body['enabled'] === 'boolean'
        && typeof body['configured'] === 'boolean'
        && body['transport'] === 'livekit'
        && body['fallback_transport'] === 'backend_ws',
      secret_fields_absent: secretFieldsAbsent,
      token_values_absent: tokenValuesAbsent,
    };
  }, target.slug);
}

async function microphoneNotGranted(
  page: Page,
  context: BrowserContext,
): Promise<boolean> {
  await context.clearPermissions();
  const state = await page.evaluate(async () => {
    try {
      const permission = await navigator.permissions.query({
        name: 'microphone' as PermissionName,
      });
      return permission.state;
    } catch {
      return 'unavailable';
    }
  });
  return state === 'prompt' || state === 'denied';
}

function expectAllChecksPassed(checks: ContentFreeChecks): void {
  for (const [key, value] of Object.entries(checks)) {
    if (typeof value === 'boolean') {
      expect(value, `${key} must pass`).toBe(true);
    }
  }
}

test.describe.serial('Release A — protected runner content-free canaries', () => {
  test.skip(
    !enabled,
    'Set E2E_PROTECTED_RUNNER_CANARIES=1 to produce protected evidence',
  );

  test.afterEach(async ({ page }) => logout(page));

  test('business application routes and Client360 dry-run', async ({ page }) => {
    const runtime = runtimeEvidence();
    const builds = await buildChecks(page, runtime.expectedSha);
    const targets = await loginAndDiscover(page);
    await selectWorkspace(page, targets.andritz);
    const roleMarkerCurrent = await currentSettingsStillMatch(
      page,
      targets.andritz,
      isAndritzSettings,
    );

    let accessibleRoutes = 0;
    for (const route of BUSINESS_ROUTES) {
      await page.goto(route.path);
      await expect(page.locator(route.selector)).toBeVisible();
      accessibleRoutes += 1;
    }
    await page.goto('/client360');
    await expect(page.locator('app-client360-page')).toBeVisible();
    const dryRun = await andritzDryRun(page, targets.andritz);
    const checks: ContentFreeChecks = {
      ...builds,
      settings_role_unique: true,
      role_marker_current: roleMarkerCurrent,
      configured_app_count: BUSINESS_SURFACES.length,
      accessible_route_count: accessibleRoutes,
      authenticated_dry_run: dryRun.status_ok,
      dry_run_confirmed: dryRun.dry_run_confirmed,
      dry_run_created_zero: dryRun.no_rows_created,
      dry_run_updated_zero: dryRun.no_rows_updated,
      dry_run_counters_content_free: dryRun.counters_content_free,
    };
    expect(accessibleRoutes).toBe(4);
    expectAllChecksPassed(checks);
    writeEvidence(runtime, 'canary-andritz', targets.andritz, checks);
  });

  for (const canary of [
    {
      token: 'canary-sentinel' as const,
      target: 'sentinel' as const,
      profile: SENTINEL_MISSION_ROOM_PROFILE,
    },
    {
      token: 'canary-octocity' as const,
      target: 'octocity' as const,
      profile: OCTOCITY_MISSION_ROOM_PROFILE,
    },
  ] as const) {
    test(`${canary.target} branding and action packs stay isolated`, async ({ page }) => {
      const runtime = runtimeEvidence();
      const builds = await buildChecks(page, runtime.expectedSha);
      const targets = await loginAndDiscover(page);
      const target = targets[canary.target];
      const contract = await missionRoomContract(page, target, canary.profile);
      const checks: ContentFreeChecks = {
        ...builds,
        settings_role_unique: true,
        ...contract,
      };
      expect(contract.navigation_item_count).toBe(7);
      expect(contract.action_pack_count).toBe(3);
      expectAllChecksPassed(checks);
      writeEvidence(runtime, canary.token, target, checks);
    });
  }

  test('authenticated LiveKit config exposes state without a token', async ({ page }) => {
    const runtime = runtimeEvidence();
    const builds = await buildChecks(page, runtime.expectedSha);
    const targets = await loginAndDiscover(page);
    await selectWorkspace(page, targets.andritz);
    const livekit = await livekitProjection(page, targets.andritz);
    const checks: ContentFreeChecks = {
      ...builds,
      settings_role_unique: true,
      ...livekit,
    };
    expectAllChecksPassed(checks);
    writeEvidence(runtime, 'canary-livekit', targets.andritz, checks);
  });

  test('microphone is not granted while Capture remains accessible', async ({
    page,
    context,
  }) => {
    const runtime = runtimeEvidence();
    const builds = await buildChecks(page, runtime.expectedSha);
    const targets = await loginAndDiscover(page);
    await selectWorkspace(page, targets.andritz);
    const permissionNotGranted = await microphoneNotGranted(page, context);
    await page.goto('/knowledge/capture');
    await expect(page.locator('app-capture-router')).toBeVisible();
    const checks: ContentFreeChecks = {
      ...builds,
      settings_role_unique: true,
      microphone_not_granted: permissionNotGranted,
      capture_ui_accessible: true,
    };
    expectAllChecksPassed(checks);
    writeEvidence(runtime, 'browser-permission-probe', targets.andritz, checks);
  });
});
