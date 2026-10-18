import {expect, type Page} from '@playwright/test';
import {expectOk} from './api';

export interface NativeInvocationEvidence {
  run_id: string;
  invocation_id: string;
  workspace_slug: string;
  projection_enabled: boolean;
  source: 'run_audit' | 'invocation_projection';
}

/** Resolve the same authorized source as SkillInvocationView, without retaining I/O. */
export async function resolveNativeInvocation(page: Page, selection: {
  runId: string; invocationId: string; workspaceSlug: string;
}): Promise<NativeInvocationEvidence> {
  const {runId, invocationId, workspaceSlug} = selection;
  expect(await page.evaluate(() => localStorage.getItem('agentium_workspace_slug'))).toBe(workspaceSlug);
  const workspace = await expectOk<{slug: string; effective_features?: Record<string, boolean>}>(page,
    `/api/v1/auth/workspaces/${encodeURIComponent(workspaceSlug)}`);
  expect(workspace.slug).toBe(workspaceSlug);
  const enabled = workspace.effective_features?.['skill_invocation_360_projection_v1'];
  expect(typeof enabled, 'The current workspace must declare the effective invocation projection flag').toBe('boolean');
  const path = `/api/v1/runs/${encodeURIComponent(runId)}`
    + (enabled ? `/invocations/${encodeURIComponent(invocationId)}` : '');
  // Do not pass the invocation payload to Playwright assertions or reporters.
  // A 404 on an enabled dedicated endpoint must fail; it never triggers fallback.
  const result = await page.evaluate(async ({path, runId, invocationId, enabled}) => {
    const response = await fetch(path, {headers: {
      Authorization: localStorage.getItem('agentium_token') || '',
      'X-Workspace-Slug': localStorage.getItem('agentium_workspace_slug') || '',
    }});
    const body = await response.json().catch(() => null);
    const identityMatches = enabled
      ? body?.id === invocationId && body?.run_id === runId
      : body?.id === runId && Array.isArray(body.invocations)
        && body.invocations.filter((item: {id?: string}) => item.id === invocationId).length === 1;
    return {status: response.status, identityMatches};
  }, {path, runId, invocationId, enabled});
  expect(result.status, `GET ${path}`).toBe(200);
  expect(result.identityMatches, 'The selected source contains this exact invocation under its native Run').toBe(true);
  return {run_id: runId, invocation_id: invocationId, workspace_slug: workspaceSlug,
    projection_enabled: enabled === true, source: enabled ? 'invocation_projection' : 'run_audit'};
}

/** Assert the loaded native destination; sensitive comparisons stay in the browser. */
export async function visibleNativeInvocation(page: Page, evidence: NativeInvocationEvidence): Promise<void> {
  const path = `/runs/${encodeURIComponent(evidence.run_id)}/invocations/${encodeURIComponent(evidence.invocation_id)}`;
  await expect.poll(() => new URL(page.url()).pathname).toBe(path);
  await expect(page.locator('app-skill-invocation-view')).toBeVisible();
  await expect.poll(() => page.evaluate(async (expected) => {
    if (localStorage.getItem('agentium_workspace_slug') !== expected.workspace_slug) return false;
    const view = document.querySelector('app-skill-invocation-view');
    if (!view) return false;
    if (expected.projection_enabled) {
      const sections = [...view.querySelectorAll('[data-object-type="skill_invocation"]')];
      return sections.length > 0
        && sections.every(section => section.getAttribute('data-object-id') === expected.invocation_id)
        && !!view.querySelector('[data-testid^="object360-skill_invocation-"]')
        && !view.querySelector('[data-testid="skill-invocation-audit"], [data-testid="object-perspective-loading"], [data-testid="object-perspective-error"], [data-testid="object-perspective-empty"]');
    }
    const audit = view.querySelector('[data-testid="skill-invocation-audit"] pre');
    if (!audit || view.querySelector('[data-testid^="object360-skill_invocation-"]')) return false;
    const response = await fetch(`/api/v1/runs/${encodeURIComponent(expected.run_id)}`, {headers: {
      Authorization: localStorage.getItem('agentium_token') || '',
      'X-Workspace-Slug': localStorage.getItem('agentium_workspace_slug') || '',
    }});
    if (!response.ok) return false;
    const run = await response.json().catch(() => null);
    if (run?.id !== expected.run_id || !Array.isArray(run.invocations)) return false;
    const matches = run.invocations.filter((item: {id?: string}) => item.id === expected.invocation_id);
    if (matches.length !== 1) return false;
    const invocation = matches[0];
    const canonical = (value: unknown): string => {
      if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
      if (value !== null && typeof value === 'object') {
        const row = value as Record<string, unknown>;
        return `{${Object.keys(row).sort().map(key => `${JSON.stringify(key)}:${canonical(row[key])}`).join(',')}}`;
      }
      return JSON.stringify(value);
    };
    try {
      return canonical(JSON.parse(audit.textContent || '')) === canonical({
        input_ref: invocation.input_ref ?? {}, output_ref: invocation.output_ref ?? {},
        metrics: invocation.metrics ?? {}, trace: invocation.trace ?? {},
      });
    } catch { return false; }
  }, evidence), {message: 'The exact invocation renders its authorized Run audit or loaded projection'}).toBe(true);
}
