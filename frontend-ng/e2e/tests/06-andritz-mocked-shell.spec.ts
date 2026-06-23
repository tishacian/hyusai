import { expect, test, type Page, type Route } from '@playwright/test';

const workspace = {
  id: 'ws-andritz-qa',
  name: 'Andritz QA',
  slug: 'andritz',
  role: 'admin',
  role_template: 'workspace_admin',
  member_count: 3,
  created_at: '2026-06-23T00:00:00Z',
  is_active: true,
  mode: 'executive',
  settings: {
    connectors: {
      secure_deposit: { enabled: true },
      sftp: { enabled: true },
    },
  },
};

const user = {
  id: 'user-andritz-qa',
  username: 'andritz.qa',
  email: 'andritz.qa@example.test',
  role: 'admin',
  is_active: true,
  mfa_enabled: false,
  first_name: 'Andritz',
  last_name: 'QA',
  phone: null,
  company: 'Andritz',
  job_title: 'QA',
  workspaces: [{ id: workspace.id, name: workspace.name, slug: workspace.slug, role: workspace.role }],
};

type MockRoleTemplate = 'workspace_admin' | 'workspace_reviewer';

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

function emptyOperations() {
  return {
    stale_after_hours: 24,
    poll_interval_seconds: 5,
    active_uploads: [],
    stale_partials: [],
    storage_summary: {
      active_count: 0,
      idle_count: 0,
      stale_count: 0,
      temporary_count: 0,
      temporary_size_bytes: 0,
      unattributed_partial_count: 0,
      unattributed_partial_size_bytes: 0,
      last_received_at: null,
      last_received_filename: null,
      link_count: 1,
      deposit_counts: {},
    },
    reconciliation_summary: {
      mode: 'dry_run',
      status: 'clean',
      stale_after_hours: 24,
      stale_partials: 0,
      orphan_files: 0,
      missing_db_files: 0,
      pending_rows: 0,
      unattributed_partials: 0,
      stale_partial_bytes: 0,
      orphan_file_bytes: 0,
      generated_at: '2026-06-23T00:00:00Z',
      confirm_from_job_id: null,
    },
    last_jobs: [],
  };
}

async function installAndritzMocks(
  page: Page,
  options: { roleTemplate?: MockRoleTemplate } = {},
) {
  const roleTemplate = options.roleTemplate ?? 'workspace_admin';
  const legacyRole = roleTemplate === 'workspace_reviewer' ? 'member' : 'admin';
  const activeWorkspace = {
    ...workspace,
    role: legacyRole,
    role_template: roleTemplate,
  };
  const activeUser = {
    ...user,
    role: legacyRole,
    email: roleTemplate === 'workspace_reviewer' ? 'reviewer.andritz.qa@example.test' : user.email,
    workspaces: [
      {
        id: workspace.id,
        name: workspace.name,
        slug: workspace.slug,
        role: legacyRole,
        role_template: roleTemplate,
      },
    ],
  };

  await page.addInitScript(() => {
    localStorage.setItem('agentium_token', 'Bearer mocked-andritz-token');
    localStorage.setItem('agentium_workspace_slug', 'andritz');
  });

  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api\/v1/, '');
    const method = request.method();

    if (path === '/auth/validate' && method === 'POST') {
      return json(route, { valid: true, user_id: activeUser.id, email: activeUser.email, role: activeUser.role });
    }
    if (path === '/auth/workspaces') {
      return json(route, [activeWorkspace]);
    }
    if (path === '/auth/me') {
      return json(route, activeUser);
    }
    if (path === '/iam/matrix') {
      return json(route, {
        workspace: { id: activeWorkspace.id, slug: activeWorkspace.slug, name: activeWorkspace.name },
        subject_user_id: activeUser.id,
        role_template: roleTemplate,
        custom_labels: [],
        role_flags: { require_second_eye_for_ingestion: false },
        enforcement: true,
        permissions: [
          { resource_kind: 'capture_session', action: 'create', roles: [roleTemplate], conditions: [], policy_id: 'qa', allowed_for_subject: true },
          { resource_kind: 'capture_session', action: 'read', roles: [roleTemplate], conditions: [], policy_id: 'qa', allowed_for_subject: true },
          { resource_kind: 'capture_session', action: 'update', roles: [roleTemplate], conditions: ['owner_match'], policy_id: 'qa', allowed_for_subject: true },
          { resource_kind: 'capture_session', action: 'execute', roles: [roleTemplate], conditions: ['owner_match'], policy_id: 'qa', allowed_for_subject: true },
          { resource_kind: 'knowledge_proposal', action: 'review_decide', roles: [roleTemplate], conditions: [], policy_id: 'qa', allowed_for_subject: true },
        ],
      });
    }

    if (path === '/contexts') {
      return json(route, { contexts: [] });
    }
    if (path === '/systems') {
      return json(route, { systems: [] });
    }

    if (path === '/documents/collections') {
      return json(route, {
        collections: ['andritz-qa'],
        default: 'andritz-qa',
        items: [
          {
            slug: 'andritz-qa',
            name: 'Andritz QA',
            document_count: 2,
            chunk_count: 12,
            updated_at: '2026-06-23T00:00:00Z',
            status: 'ready',
          },
        ],
      });
    }

    if (path === '/knowledge-capture/sessions') {
      return json(route, { sessions: [] });
    }
    if (path === '/knowledge-capture/proposals') {
      return json(route, { proposals: [] });
    }
    if (path === '/knowledge-capture/fiches') {
      return json(route, { fiches: [], total: 0, limit: 100, offset: 0, has_more: false });
    }

    if (path === '/sftp/health') {
      return json(route, {
        status: 'ok',
        workspace: 'andritz',
        enabled: true,
        default_allowed_extensions: ['.pdf', '.docx', '.pptx', '.xlsx', '.png', '.jpg'],
      });
    }
    if (path === '/sftp/links') {
      return json(route, {
        links: [
          {
            id: 'link-andritz-qa',
            label: 'Andritz QA external upload',
            access_id: 'andritz-qa',
            public_url: 'https://example.test/deposit/andritz-qa',
            status: 'active',
            expires_at: null,
            max_file_size_mb: 250,
            allowed_extensions: ['.pdf', '.docx', '.pptx', '.xlsx'],
            created_at: '2026-06-23T00:00:00Z',
            created_by_user_id: activeUser.id,
            created_by: activeUser.email,
          },
        ],
      });
    }
    if (path === '/sftp/deposits') {
      return json(route, { files: [] });
    }
    if (path === '/sftp/operations') {
      return json(route, emptyOperations());
    }
    if (path === '/sftp/deposits/indexing-assist') {
      return json(route, {
        collection: { slug: 'andritz-qa', name: 'Andritz QA', jobs: [] },
        files: [],
        summary: { recommended: 0, needs_review: 0, blocked: 0 },
      });
    }

    if (path.startsWith('/chat/')) {
      return json(route, path.endsWith('/sessions') ? { sessions: [] } : {});
    }
    if (path === '/actions/effective') {
      return json(route, { actions: [] });
    }
    if (path === '/voice/runtimes') {
      return json(route, {
        default_provider: 'mock',
        allowed_providers: ['mock'],
        fallback_providers: [],
        events: [],
        providers: [],
      });
    }

    return json(route, {});
  });
}

test.describe('Andritz mocked browser smoke', () => {
  test('renders Chat, Knowledge Capture, Collections and SFTP entry without real data', async ({ page }) => {
    await installAndritzMocks(page);

    await page.goto('/connectors');
    await expect(page.getByRole('heading', { name: 'Connectors' })).toBeVisible();
    await expect(page.getByRole('link', { name: /Open secure deposit/i })).toBeVisible();

    await page.goto('/connectors/sftp');
    await expect(page.getByRole('heading', { name: /SFTP \/ Secure Deposit/i })).toBeVisible();
    await expect(page.locator('body')).toContainText(/No active SFTP transfer|Live upload monitor/i);

    await page.goto('/knowledge');
    await expect(page.getByRole('heading', { name: /Knowledge/i })).toBeVisible();
    await expect(page.locator('body')).toContainText(/Andritz QA|andritz-qa/i);

    await page.goto('/knowledge/capture');
    await expect(page.locator('body')).toContainText(/Vos sessions|Sessions de capture|Nouvelle capture|Capture sessions|New session/i);

    await page.goto('/chat');
    await expect(page.locator('body')).toContainText(/Chat|Question rapide|Posez votre question|Quick ask|Ask/i);
  });

  test('keeps primary Andritz surfaces reachable on mobile viewport', async ({ page }) => {
    await installAndritzMocks(page);
    await page.setViewportSize({ width: 390, height: 844 });

    await page.goto('/connectors');
    await expect(page.getByRole('heading', { name: 'Connectors' })).toBeVisible();
    await expect(page.getByRole('link', { name: /Open secure deposit/i })).toBeVisible();

    await page.goto('/connectors/sftp');
    await expect(page.getByRole('heading', { name: /SFTP \/ Secure Deposit/i })).toBeVisible();
    await expect(page.locator('body')).toContainText(/Live upload monitor|No active SFTP transfer/i);

    await page.goto('/knowledge');
    await expect(page.getByRole('heading', { name: /Knowledge/i })).toBeVisible();
    await expect(page.locator('body')).toContainText(/Andritz QA|andritz-qa/i);

    await page.goto('/knowledge/capture');
    await expect(page.locator('body')).toContainText(/Capture sessions|Sessions de capture|New session|Nouvelle capture/i);

    await page.goto('/chat');
    await expect(page.locator('body')).toContainText(/Chat|Quick ask|Question rapide|Ask|Posez votre question/i);
  });

  test('enables new capture for reviewer IAM matrix', async ({ page }) => {
    await installAndritzMocks(page, { roleTemplate: 'workspace_reviewer' });

    await page.goto('/knowledge/capture');
    const newCapture = page
      .getByRole('button', { name: /New session|New capture|Nouvelle session|Nouvelle capture/i })
      .first();
    await expect(newCapture).toBeVisible();
    await expect(newCapture).toBeEnabled();
  });
});
