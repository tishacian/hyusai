import { expect, test, type Page, type Route } from '@playwright/test';

const workspace = { id: 'ops-ws', slug: 'ops-ws', name: 'Operations', role: 'owner', role_template: 'workspace_owner', settings: {} };
const mission = { id: 'mission-1', title: 'Delivery report', description: 'Summarise the delivery evidence', agent_id: 'system-1', status: 'pending', steps: [], artifacts: {}, executions: [] };
const secret = { id: 'secret-1', name: 'erp-key', ref: 'secret://workspace/erp-key', scope: 'workspace', workspace_id: workspace.id, kind: 'api_key', current_version: 2, value_set: true, disabled_at: null, versions: [{version:1, created_at:'2026-10-01T00:00:00Z'}, {version:2, created_at:'2026-10-10T00:00:00Z'}] };
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType:'application/json', body:JSON.stringify(body) });

async function install(page: Page, options: { existing?: Record<string, unknown>; listFailure?: number } = {}) {
  const base = test.info().project.use.baseURL;
  if (!base || !['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new Error('Loopback only');
  const writes: string[] = [];
  let current: Record<string, unknown> | null = options.existing ?? null;
  await page.route('**/*', route => ['127.0.0.1','localhost'].includes(new URL(route.request().url()).hostname) ? route.fallback() : route.abort('blockedbyclient'));
  await page.addInitScript(() => {
    localStorage.setItem('agentium_token','Bearer mocked-operations');
    localStorage.setItem('agentium_workspace_slug','ops-ws');
    localStorage.setItem('agentium_locale','fr');
  });
  await page.route('**/api/v1/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api\/v1/,'');
    if (path === '/auth/validate') return json(route,{valid:true,user_id:'ops-user',role:'admin',email:'ops@example.test'});
    if (path === '/auth/me') return json(route,{id:'ops-user',role:'admin',is_active:true,email:'ops@example.test',workspaces:[workspace]});
    if (path === '/auth/workspaces') return json(route,[workspace]);
    if (path === '/auth/workspaces/ops-ws') return json(route,workspace);
    if (path === '/systems') return json(route,{systems:[{id:'system-1',name:'Delivery assistant'}]});
    if (path === '/tasks' && request.method() === 'GET') return json(route,{tasks:current ? [current] : []},options.listFailure ?? 200);
    if (path === '/tasks' && request.method() === 'POST') { writes.push(path); current={...mission,...request.postDataJSON()}; return json(route,current); }
    if (path === '/tasks/mission-1') return json(route,current ?? mission);
    if (path.endsWith('/run') || path.endsWith('/resume')) {
      writes.push(path);
      current={...(current ?? mission),status:'completed',execution_id:'attempt-new',artifacts:{report:'Verified report'}};
      return route.fulfill({contentType:'text/event-stream',body:'data: {"type":"task_complete","status":"completed","artifacts":{"report":"Verified report"},"progress":100}\n\ndata: [DONE]\n\n'});
    }
    if (path === '/secrets') return json(route,{secrets:[secret],can_manage_platform:false});
    if (path === '/secrets/secret-1/consumers') return json(route,{consumers:[{kind:'system',id:'s1',system_id:'s1',name:'Finance checks',count:2},{kind:'system',id:'s2',system_id:'s2',name:'Delivery assistant',count:1}]});
    if (path === '/secrets/secret-1/disable') { writes.push(path); return json(route,{...secret,disabled_at:'2026-10-21T00:00:00Z'}); }
    if (path === '/secrets/secret-1' && request.method() === 'DELETE') { writes.push(`${path}?${new URL(request.url()).searchParams}`); return json(route,secret); }
    return json(route,request.method() === 'GET' && path.endsWith('s') ? [] : {});
  });
  return writes;
}

test.describe('Lot 7: deliberate operations and retained evidence', () => {
  test.skip(process.env['E2E_CHROME_V2_MOCKED'] !== '1','Local mocked contract only');
  test.use({serviceWorkers:'block',video:'off'});

  test('composition saves a draft, launch reviews goal, agent and deliverable',async ({page}) => {
    const writes=await install(page);
    await page.goto('/tasks');
    await page.getByRole('button',{name:'Nouvelle mission'}).click();
    const compose=page.getByRole('dialog',{name:'Nouvelle mission'});
    await compose.locator('input').fill('Delivery report');
    await compose.locator('textarea').fill(mission.description);
    await expect(compose).toContainText('assistant LLM');
    await compose.getByRole('button',{name:'Enregistrer la mission'}).click();
    await expect(page.locator('app-drawer')).toContainText('Delivery report');
    expect(writes).toEqual(['/tasks']);
    await page.getByRole('button',{name:'Exécuter',exact:true}).click();
    const confirm=page.locator('app-confirm-dialog');
    await expect(confirm).toContainText(mission.description);
    await expect(confirm).toContainText('Assistant de rédaction (LLM)');
    await expect(confirm).toContainText('Livrable attendu');
    expect(writes).toEqual(['/tasks']);
    await confirm.getByRole('button',{name:'Confirmer',exact:true}).click();
    await expect(page.locator('app-drawer')).toContainText('Verified report');
    expect(writes).toEqual(['/tasks','/tasks/mission-1/run']);
  });

  test('relaunch retains historical output and asks explicitly',async ({page}) => {
    const writes=await install(page,{existing:{...mission,status:'completed',executions:[{id:'attempt-old',status:'completed',started_at:'2026-10-20T10:00:00Z',artifacts:{report:'Previous retained report'}}]}});
    await page.goto('/tasks');
    await page.getByRole('button',{name:/Delivery report/}).click();
    await page.getByText('Exécutions et livrables conservés').click();
    await expect(page.locator('app-drawer')).toContainText('Previous retained report');
    await page.getByRole('button',{name:'Relancer',exact:true}).click();
    await expect(page.locator('app-confirm-dialog')).toContainText('conserv');
    expect(writes).toEqual([]);
  });

  for (const status of [403,500,504]) test(`a failed mission read (${status}) is never empty`,async ({page}) => {
    await install(page,{listFailure:status}); await page.goto('/tasks');
    await expect(page.locator('app-tasks-page [role="alert"]')).toBeVisible();
    await expect(page.locator('app-tasks-page app-empty-state')).toHaveCount(0);
  });

  test('secret disable names every observed consumer before mutation',async ({page}) => {
    const writes=await install(page); await page.goto('/workspace/ops-ws/secrets');
    await page.locator('app-workspace-secrets').getByRole('button',{name:/Désactiver/}).click();
    const confirm=page.locator('app-confirm-dialog');
    await expect(confirm).toContainText('Finance checks'); await expect(confirm).toContainText('Delivery assistant');
    expect(writes).toEqual([]);
    await confirm.getByRole('button',{name:'Confirmer',exact:true}).click();
    expect(writes).toEqual(['/secrets/secret-1/disable']);
  });
});
