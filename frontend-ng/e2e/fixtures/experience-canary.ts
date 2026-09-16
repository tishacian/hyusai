import { createHash } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { expect, type Page } from '@playwright/test';

export const experienceCanaryEnabled = process.env['E2E_EXPERIENCE_CANARY'] === '1';
export const expectedSha = (process.env['E2E_EXPECTED_SHA'] ?? '').trim().toLowerCase();
export const experienceEvidencePath = process.env['E2E_EXPERIENCE_EVIDENCE'];

const username = process.env['E2E_USERNAME'];
const password = process.env['E2E_PASSWORD'];

export interface CanaryCredentials {
  username: string;
  password: string;
}

const reviewerUsername = process.env['E2E_EXPERIENCE_REVIEWER_USERNAME'];
const reviewerPassword = process.env['E2E_EXPERIENCE_REVIEWER_PASSWORD'];

export const reviewerCredentialsMisconfigured = !!reviewerUsername !== !!reviewerPassword;
export const reviewerCredentials: CanaryCredentials | null =
  reviewerUsername
  && reviewerPassword
    ? {
        username: reviewerUsername,
        password: reviewerPassword,
      }
    : null;

export const reviewerRequired = process.env['E2E_EXPERIENCE_REQUIRE_REVIEWER'] === '1';
export const deployExperience = process.env['E2E_EXPERIENCE_DEPLOY'] === '1';
export const allowRetainedExperience = process.env['E2E_EXPERIENCE_ALLOW_RETAINED'] === '1';

export interface WorkspaceSummary {
  id: string;
  slug: string;
  name: string;
  role?: string;
  role_template?: string | null;
  settings?: Record<string, unknown>;
}

export interface WorkCatalogItem {
  experience: {
    id: string;
    name: string;
    slug: string;
    pattern: string;
    languages?: string[];
    theme?: Record<string, unknown> | null;
  };
  channel: 'pilot' | 'live' | string;
  release: {
    id: string;
    release_number?: number;
    renderer_version?: string | null;
  };
}

export interface ApiResult<T> {
  ok: boolean;
  status: number;
  body: T;
}

export function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

export function features(settings: Record<string, unknown> | undefined): Record<string, unknown> {
  return asRecord(settings?.['features']) ?? {};
}

export function sha256(value: string): string {
  return createHash('sha256').update(value).digest('hex');
}

export function evidencePathFor(suite: 'work' | 'studio'): string | undefined {
  if (!experienceEvidencePath) return undefined;
  if (experienceEvidencePath.endsWith('.json')) {
    return experienceEvidencePath.replace(/\.json$/, `-${suite}.json`);
  }
  return `${experienceEvidencePath.replace(/\/$/, '')}/${suite}.json`;
}

export function writeEvidence(path: string | undefined, value: unknown): void {
  if (!path) return;
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`, { encoding: 'utf8', mode: 0o600 });
}

export async function login(
  page: Page,
  credentials: CanaryCredentials | null = null,
): Promise<WorkspaceSummary[]> {
  const email = credentials?.username ?? username;
  const secret = credentials?.password ?? password;
  expect(email, 'E2E_USERNAME is required for the Experience canary').toBeTruthy();
  expect(secret, 'E2E_PASSWORD is required for the Experience canary').toBeTruthy();
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
    { email: email as string, secret: secret as string },
  );
  expect(result.ok, `login or workspace discovery failed (${result.status})`).toBe(true);
  const memberships = (Array.isArray(result.workspaces) ? result.workspaces : []) as WorkspaceSummary[];
  expect(memberships.length, 'the canary principal needs at least one authorized workspace').toBeGreaterThan(0);
  return memberships;
}

export async function logout(page: Page): Promise<void> {
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

export async function api<T>(
  page: Page,
  workspaceSlug: string,
  path: string,
  options: { method?: 'GET' | 'POST' | 'DELETE'; body?: unknown } = {},
): Promise<ApiResult<T>> {
  return page.evaluate(
    async ({ slug, apiPath, request }) => {
      const response = await fetch(`/api/v1${apiPath}`, {
        method: request.method ?? 'GET',
        headers: {
          Authorization: localStorage.getItem('agentium_token') || '',
          'X-Workspace-Slug': slug,
          ...(request.body === undefined ? {} : { 'Content-Type': 'application/json' }),
        },
        body: request.body === undefined ? undefined : JSON.stringify(request.body),
      });
      const text = await response.text();
      let body: unknown = null;
      if (text) {
        try { body = JSON.parse(text); } catch { body = text; }
      }
      return { ok: response.ok, status: response.status, body };
    },
    { slug: workspaceSlug, apiPath: path, request: options },
  ) as Promise<ApiResult<T>>;
}

export async function bindWorkspace(page: Page, slug: string): Promise<void> {
  await page.evaluate((value) => localStorage.setItem('agentium_workspace_slug', value), slug);
}

export async function discoverExperienceWorkspace(
  page: Page,
  memberships: WorkspaceSummary[],
  options: { studio?: boolean } = {},
): Promise<WorkspaceSummary | null> {
  const showcase = process.env['E2E_SHOWCASE_WORKSPACE_SLUG'];
  const candidates = showcase ? memberships.filter(item => item.slug === showcase) : memberships;
  for (const membership of candidates) {
    const detail = await api<WorkspaceSummary>(
      page,
      membership.slug,
      `/auth/workspaces/${encodeURIComponent(membership.slug)}`,
    );
    const flags = detail.ok ? features(detail.body.settings) : {};
    if (
      detail.ok
      && flags['experience_v1'] === true
      && (!options.studio || flags['experience_studio_v1'] !== false)
    ) {
      return detail.body;
    }
  }
  return null;
}

export async function assertDeployedRevision(page: Page): Promise<void> {
  if (!expectedSha) return;
  expect(expectedSha, 'E2E_EXPECTED_SHA must be the deployed full SHA').toMatch(/^[0-9a-f]{40}$/);
  for (const path of ['/api/v1/build-info', '/build-info.json']) {
    const response = await page.request.get(`${path}?canary=${Date.now()}`, {
      headers: { Accept: 'application/json', 'Cache-Control': 'no-cache' },
    });
    expect(response.ok(), `${path} must be readable`).toBe(true);
    expect(await response.json()).toMatchObject({ revision: expectedSha, revision_verified: true });
  }
}
