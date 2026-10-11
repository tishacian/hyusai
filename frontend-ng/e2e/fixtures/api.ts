import { Page, expect } from '@playwright/test';

export async function appFetch<T = unknown>(
  page: Page,
  path: string,
  options: {
    method?: string;
    data?: unknown;
    headers?: Record<string, string>;
  } = {},
): Promise<{ status: number; body: T }> {
  const result = await page.evaluate(
    async ({ path, options }) => {
      const res = await fetch(path, {
        method: options.method ?? 'GET',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          ...(localStorage.getItem('agentium_token')
            ? { Authorization: localStorage.getItem('agentium_token') as string }
            : {}),
          ...(localStorage.getItem('agentium_workspace_slug')
            ? { 'X-Workspace-Slug': localStorage.getItem('agentium_workspace_slug') as string }
            : {}),
          ...(options.headers ?? {}),
        },
        body: options.data == null ? undefined : JSON.stringify(options.data),
      });
      const text = await res.text();
      let body: unknown = null;
      try {
        body = text ? JSON.parse(text) : null;
      } catch {
        body = text;
      }
      return { status: res.status, body };
    },
    { path, options },
  );
  return result as { status: number; body: T };
}

export async function expectOk<T = unknown>(
  page: Page,
  path: string,
  options: Parameters<typeof appFetch>[2] = {},
): Promise<T> {
  const res = await appFetch<T>(page, path, options);
  expect(res.status, `${options.method ?? 'GET'} ${path}`).toBeGreaterThanOrEqual(200);
  expect(res.status, `${options.method ?? 'GET'} ${path}`).toBeLessThan(300);
  return res.body;
}

