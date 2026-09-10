import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Locator, type Page } from '@playwright/test';

import { runAccessibilityMatrix } from '../fixtures/accessibility-matrix';
import {
  api,
  assertDeployedRevision,
  bindWorkspace,
  discoverExperienceWorkspace,
  evidencePathFor,
  expectedSha,
  experienceCanaryEnabled,
  login,
  logout,
  sha256,
  writeEvidence,
  type WorkCatalogItem,
} from '../fixtures/experience-canary';

/**
 * US-8 — authenticated /work launcher canary.
 *
 * Discovers `settings.features.experience_v1` from the live principal's
 * workspaces. No tenant, app or row id is embedded. Once the canary flag is
 * enabled, missing configuration or test data is a failure rather than a
 * silent skip. Traces stay off because login uses a live principal.
 */

const ENGINE_JARGON = /\b(Flows?|Skills?|Runs?)\b/;

test.use({ trace: 'off', video: 'off', screenshot: 'off' });

async function visibleChromeText(root: Locator): Promise<string> {
  return (await root.allTextContents()).join(' ').replace(/\s+/g, ' ').trim();
}

async function workSurface(page: Page): Promise<'launcher' | 'redirect' | null> {
  const path = new URL(page.url()).pathname.replace(/\/$/, '') || '/';
  if (path.startsWith('/work/') && await page.locator('app-work-shell').count() > 0) {
    return 'redirect';
  }
  if (path !== '/work') return null;
  const listed = await page.locator('app-work-launcher .xp-work-grid').count();
  const empty = await page.locator('app-work-launcher app-empty-state p').count();
  return listed > 0 || empty > 0 ? 'launcher' : null;
}

test.describe('US-8 — Experience /work canary', () => {
  test.skip(!experienceCanaryEnabled, 'Set E2E_EXPERIENCE_CANARY=1 to exercise /work');
  test.afterEach(async ({ page }) => logout(page));

  test('opens the launcher or a deployed app without cockpit chrome', async ({ page }, testInfo) => {
    test.setTimeout(180_000);
    await assertDeployedRevision(page);
    const memberships = await login(page);
    const workspace = await discoverExperienceWorkspace(page, memberships);
    expect(workspace, 'experience_v1 must be enabled on an authorized workspace').toBeTruthy();

    const listed = await api<{ experiences: WorkCatalogItem[] }>(
      page,
      workspace!.slug,
      '/work',
    );
    expect(listed.ok, `GET /work failed (${listed.status})`).toBe(true);
    const apps = listed.body.experiences ?? [];
    expect(apps.length, 'at least one Pilot/In-service Experience must be visible').toBeGreaterThan(0);

    await bindWorkspace(page, workspace!.slug);
    await page.goto('/work');
    await expect.poll(async () => workSurface(page)).not.toBeNull();
    const surface = await workSurface(page);
    expect(surface, 'work must settle on the launcher or a deployed app').toBeTruthy();

    await expect(page.locator('app-side-rail')).toHaveCount(0);
    await expect(page.getByRole('main')).toBeVisible();
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    if (surface === 'launcher') {
      await expect(page.locator('app-work-launcher')).toBeVisible();
      await expect(
        page.getByRole('heading', { name: /Mes applications|My applications/ }),
      ).toBeVisible();
      await expect(page.locator('.xp-work-grid a.xp-work-card')).toHaveCount(apps.length);
      const chrome = page.locator('app-work-launcher header, app-work-launcher .xp-work-status, app-work-launcher .xp-work-grid p');
      expect(await visibleChromeText(chrome), 'launcher chrome must not name Flow/Skill/Run')
        .not.toMatch(ENGINE_JARGON);
    } else {
      await expect(page.locator('app-work-shell')).toBeVisible();
      expect(new URL(page.url()).pathname).toMatch(/^\/work\/[^/]+/);
      const chrome = page.locator(
        'app-work-shell .xp-work-brand a, app-work-shell .xp-work-actions a, app-work-shell .xp-work-actions button',
      );
      expect(await visibleChromeText(chrome), 'work chrome must not name Flow/Skill/Run')
        .not.toMatch(ENGINE_JARGON);
    }

    const matrix = await runAccessibilityMatrix({
      page,
      testInfo,
      path: new URL(page.url()).pathname,
      readySelector: surface === 'launcher' ? 'app-work-launcher' : 'app-work-shell',
      surface: 'work',
    });

    const evidence = {
      schema_version: 2,
      kind: 'experience_work_canary',
      claim: 'US-8-WORK-LAUNCHER',
      outcome: 'passed',
      tested_revision: expectedSha || null,
      generated_at: new Date().toISOString(),
      target: { workspace_sha256: sha256(workspace!.id) },
      checks: {
        experience_v1: true,
        work_surface: surface,
        no_side_rail: true,
        no_engine_jargon: true,
        main_landmark: true,
        accessibility_matrix: matrix.combinations,
        wcag_aa_axe: true,
        reduced_motion: true,
        reflow_320_css_px: true,
      },
    };
    writeEvidence(evidencePathFor('work'), evidence);
    await testInfo.attach('experience-work-canary', {
      body: JSON.stringify(evidence, null, 2),
      contentType: 'application/json',
    });
  });
});

// Local visual and interaction contract. The API is intentionally mocked;
// canonical publication, arithmetic and authorization are tested by the backend suite.
test.describe('Adoption local contract', () => {
  test.skip(process.env['E2E_ADOPTION_MOCKED'] !== '1', 'Set E2E_ADOPTION_MOCKED=1 for the local adoption fixture');
  test('keeps a non-modal companion through navigation and serves bilingual guides', async ({page},testInfo) => {
    test.setTimeout(90_000);
    const workspace={id:'adoption-fixture',slug:'agentium-showcase',name:'Agentium Showcase · local fixture',mode:'portfolio',role:'owner',role_template:'workspace_owner',settings:{features:{experience_v1:true,adoption_experience_v1:true,hypervisor_v2:true}}};
    const user={id:'adoption-user',username:'adoption',email:'adoption@example.test',role:'admin',is_active:true,workspaces:[workspace]};
    const progress={version:1,persona:'operator',journey:'northforge_sources',completed_steps:[] as string[],dismissed:false,example_available:true};
    await page.addInitScript(() => {
      localStorage.setItem('agentium_token','Bearer local-adoption-fixture');
      localStorage.setItem('agentium_workspace_slug','agentium-showcase');
      localStorage.setItem('agentium_locale','en');localStorage.setItem('agentium.help.lang','en');
      localStorage.setItem('agentium_theme','light');
    });
    await page.route('**/api/v1/**',async route=>{
      const request=route.request();const url=new URL(request.url());const path=url.pathname.replace(/^\/api\/v1/,'');
      const json=(body:unknown,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
      if(path==='/auth/validate')return json({valid:true,user_id:user.id,role:'admin'});
      if(path==='/auth/me')return json(user);
      if(path==='/auth/workspaces')return json([workspace]);
      if(path===`/auth/workspaces/${workspace.slug}`)return json(workspace);
      if(path.endsWith('/me/experience')){
        if(request.method()==='PATCH'){const patch=request.postDataJSON();Object.assign(progress,{...patch,completed_steps:patch.completed_step?[...new Set([...progress.completed_steps,patch.completed_step])]:progress.completed_steps});}
        return json(progress);
      }
      if(path==='/work')return json({experiences:[]});
      if(path==='/assistant/systems')return json({systems:[{system_id:'ops',name:'Operational Analysis',runnable:true,objective:'Explain a synthetic delay'}]});
      if(path==='/assistant/turns')return json({session_id:'fixture-conversation',answer:'The fixed example has 35 minutes of net overrun. This fixture verifies the UI only.',tool_calls:[{name:'get_run_status',ok:true,result:{system_id:'ops',run_id:'fixture-run',status:'completed',demonstration:true}}],finish_reason:'stop'});
      if(path.startsWith('/help-content/guides/')){
        const language=url.searchParams.get('language')||'en';return json({language,title:language==='fr'?'Bien démarrer':'Getting started',paragraphs:[language==='fr'?'Vérifiez la réponse dans sa source.':'Check the answer against its source.']});
      }
      if(path==='/help-content')return json({version:'fixture',items:[],personas:['operator','builder','executive'],languages:['en','fr']});
      return json(path.endsWith('s')?[]:{});
    });
    const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
    await page.goto('/');
    await expect(page).toHaveURL(/\/work$/);
    await expect(page.locator('app-adoption-journey')).toBeVisible();
    await page.screenshot({path:testInfo.outputPath('adoption-work-local-fixture.png'),fullPage:true});
    await page.getByRole('button',{name:'Control through conversation'}).click();
    const pilot=page.locator('app-assistant-pilot');await expect(pilot).toBeVisible();
    await pilot.getByRole('checkbox',{name:'Operational Analysis'}).check();
    await pilot.getByRole('textbox',{name:'Your request'}).fill('Explain this example');
    await pilot.getByRole('button',{name:'Send',exact:true}).click();
    await expect(pilot).toContainText('35 minutes');
    await expect(pilot.getByRole('link',{name:'Open System',exact:true}).first()).toHaveAttribute('href', /\/systems\/ops(?:\?|$)/);
    await expect(pilot.getByRole('link',{name:/Open Run/})).toHaveAttribute('href', /\/runs\/fixture-run(?:\?|$)/);
    await expect(pilot.getByRole('link',{name:/Open Run/})).not.toHaveAttribute('href', /lens=hypervisor/);
    // A desktop companion must leave the page usable.
    await expect(page.locator('app-chat-overlay [aria-modal="true"]')).toHaveCount(0);
    await page.locator('app-work-launcher nav').getByRole('link',{name:'Getting started help',exact:true}).click();
    await expect(page.locator('app-help-guide h1')).toHaveText('Getting started');
    await expect(pilot).toContainText('35 minutes');
    await page.screenshot({path:testInfo.outputPath('adoption-companion-local-fixture.png'),fullPage:true});
    await page.locator('app-help-guide').getByRole('button',{name:'FR',exact:true}).click();
    await expect(page.locator('app-help-guide h1')).toHaveText('Bien démarrer');
    await page.setViewportSize({width:390,height:844});
    await expect(page.locator('app-chat-overlay [aria-modal="true"]')).toHaveCount(1);
    const panel=page.locator('app-chat-overlay [aria-modal="true"]');
    expect((await panel.boundingBox())!.width).toBeLessThanOrEqual(390);
    await page.screenshot({path:testInfo.outputPath('adoption-mobile-local-fixture.png'),fullPage:true});
    await page.setViewportSize({width:1280,height:900});
    await page.route('**/api/v1/systems*', route => route.fulfill({status:403,contentType:'application/json',body:JSON.stringify({detail:'fixture access refusal'})}));
    await page.goto('/systems?lens=build');
    await expect(page.locator('app-systems-grid [role="alert"]')).toContainText('Your permissions do not allow');
    await expect(page.locator('app-systems-grid [role="alert"]').getByRole('button',{name:'Retry',exact:true})).toBeVisible();
    const diagnostics=page.getByTestId('titlebar-diagnostics');
    await expect(diagnostics.locator('.tb-readouts')).not.toBeVisible();
    await diagnostics.locator('summary').focus();
    await page.keyboard.press('Enter');
    await expect(diagnostics.locator('.tb-readouts')).toBeVisible();
    await expect(diagnostics).toContainText('Completed Runs');
    await expect(diagnostics).toContainText('neither answer quality nor economic benefit');
    await page.screenshot({path:testInfo.outputPath('adoption-diagnostics-local-fixture.png'),fullPage:true});
    await diagnostics.locator('summary').click();
    await expect(diagnostics.locator('.tb-readouts')).not.toBeVisible();
    await page.screenshot({path:testInfo.outputPath('adoption-access-local-fixture.png'),fullPage:true});
    expect(errors).toEqual([]);
  });
});

test.describe('White labelling local contract', () => {
  test.skip(process.env['E2E_ADOPTION_MOCKED'] !== '1', 'Uses the existing local adoption fixture switch');
  test('edits workspace identity, persists it and renders an application from its release', async ({ page }, testInfo) => {
    const workspace: any = {id:'brand-fixture',slug:'brand-fixture',name:'Brand fixture',role:'owner',role_template:'workspace_owner',is_active:true,member_count:1,mode:'builder',settings:{features:{experience_v1:true,experience_studio_v1:true,adoption_experience_v1:true},unrelated:{keep:true}}};
    const user = {id:'brand-user',username:'brand',role:'admin',is_active:true,workspaces:[workspace]};
    const draftApp:any = {id:'app-fixture',name:'NorthForge draft',slug:'branded-app',pattern:'form_result',languages:['en'],access_policy:{roles:[],groups:[]},updated_at:'2026-09-10T20:00:00Z',theme:{mode:'light',appearance:{palette:'sand'}},draft:{revision:1,binding_keys:[],pages:{pages:[{id:'home',title:'Home',components:[{id:'header',type:'header',props:{title:'Draft example'}}]}]}},deployments:[]};
    const errors:string[]=[];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {
      localStorage.setItem('agentium_token','Bearer local-brand-fixture');
      localStorage.setItem('agentium_workspace_slug','brand-fixture');
      localStorage.setItem('agentium_locale','en');
      localStorage.setItem('agentium_theme','light');
    });
    await page.route('**/api/v1/**', async route => {
      const request = route.request();
      const path = new URL(request.url()).pathname.replace(/^\/api\/v1/,'');
      const json = (body:unknown,status=200) => route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
      if(path==='/auth/validate') return json({valid:true,user_id:user.id,role:'admin'});
      if(path==='/auth/me') return json(user);
      if(path==='/auth/workspaces') return json([workspace]);
      if(path===`/auth/workspaces/${workspace.slug}`) {
        if(request.method()==='PATCH') {
          const body = request.postDataJSON();
          expect(body.settings).toBeUndefined();
          expect(body.expected_platform_brand).toEqual(workspace.settings.platform_brand ?? null);
          workspace.settings.platform_brand = body.platform_brand;
        }
        return json(workspace);
      }
      if(path==='/experiences/app-fixture') {
        if(request.method()==='PATCH') {
          const body=request.postDataJSON(); expect(body.expected_updated_at).toBe(draftApp.updated_at);
          Object.assign(draftApp,body,{updated_at:'2026-09-10T20:00:02Z'});
        }
        return json(draftApp);
      }
      if(path==='/experiences/app-fixture/ready-check') return json({ready:true,blockers:[],warnings:[],bindings_sha256:'fixture'});
      if(path==='/work/branded-app') return json({
        experience:{id:'app-fixture',name:'Unsaved draft name',slug:'branded-app',pattern:'form_result',theme:{mode:'light',appearance:{palette:'sand'}}},
        channel:'live',release:{id:'release-fixture',release_number:1,renderer_version:'certified-components-0.2.0',languages:['en'],bindings_snapshot:[],
          identity_snapshot:{name:'NorthForge Operations',emblem:'◇'},theme:{mode:'dark',appearance:{palette:'graphite',accent:'#e8543a',corners:'round'}},
          pages:{pages:[{id:'home',title:'Home',components:[{type:'header',id:'welcome',props:{title:'Published example'}}]}]},
        },
      });
      if(path==='/work') return json({experiences:[]});
      if(path==='/help-content') return json({version:'fixture',items:[],personas:[],languages:['en','fr']});
      if(path.endsWith('/me/experience')) return json({version:1,persona:'builder',completed_steps:[],dismissed:true});
      return json(path.endsWith('s')?[]:{});
    });
    await page.setViewportSize({width:1680,height:1100});
    await page.goto('/workspace/brand-fixture/settings');
    const form = page.locator('app-workspace-brand');
    await expect(form.getByRole('heading',{name:'White labelling'})).toBeVisible();
    await form.getByRole('checkbox',{name:'Use a custom identity for this workspace'}).check();
    await form.getByRole('textbox',{name:'Display name'}).fill('NorthForge');
    await form.getByRole('combobox',{name:'Palette',exact:true}).selectOption('graphite');
    await form.getByRole('combobox',{name:'Corners',exact:true}).selectOption('round');
    await form.getByLabel('Action colour').fill('#e8543a');
    // Synthetic initials drawn in the browser; no customer asset is uploaded.
    const logo = await page.evaluate(() => {
      const canvas = document.createElement('canvas'); canvas.width=96; canvas.height=72;
      const ctx = canvas.getContext('2d')!;
      ctx.fillStyle='#e8543a'; ctx.fillRect(0,0,96,72);
      ctx.fillStyle='#ffffff'; ctx.font='bold 40px sans-serif'; ctx.fillText('NF',19,51);
      return canvas.toDataURL('image/png').split(',')[1]!;
    });
    await form.getByLabel('Main logo / dark background').setInputFiles({name:'fixture.png',mimeType:'image/png',buffer:Buffer.from(logo,'base64')});
    await expect(form.locator('.brand-preview img')).toBeVisible();
    await expect.poll(() => form.locator('.brand-preview img').evaluate(el => (el as HTMLImageElement).naturalWidth)).toBe(96);
    await form.getByRole('combobox',{name:'Preview background',exact:true}).selectOption('dark');
    await expect(form.locator('.brand-preview')).toHaveCSS('background-color','rgb(9, 9, 9)');
    await expect(form.locator('.brand-preview article button')).toHaveCSS('background-color','rgb(232, 84, 58)');
    await form.scrollIntoViewIfNeeded();
    const accessibility = await new AxeBuilder({page}).include('app-workspace-brand').withTags(['wcag2a','wcag2aa']).analyze();
    expect(accessibility.violations).toEqual([]);
    await form.screenshot({path:testInfo.outputPath('white-labelling-desktop-local-fixture.png')});
    await form.getByRole('button',{name:'Save',exact:true}).click();
    await expect(form).toContainText('Identity saved for this workspace.');
    expect(workspace.settings.unrelated).toEqual({keep:true});
    await page.reload();
    await expect(form.getByRole('textbox',{name:'Display name'})).toHaveValue('NorthForge');
    await expect(form.getByRole('combobox',{name:'Palette',exact:true})).toHaveValue('graphite');
    await form.getByRole('button',{name:'Reset to standard style'}).click();
    await expect(form.getByRole('combobox',{name:'Corners',exact:true})).toHaveValue('soft');
    await expect(form.locator('.brand-preview')).toHaveCSS('border-radius','14px');
    await expect(form.locator('.brand-preview img')).toBeVisible();
    await form.getByRole('button',{name:'Cancel',exact:true}).click();
    await expect(form.getByRole('combobox',{name:'Palette',exact:true})).toHaveValue('graphite');
    await page.setViewportSize({width:390,height:844});
    await form.scrollIntoViewIfNeeded();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await form.locator('.brand-preview').scrollIntoViewIfNeeded();
    await page.screenshot({path:testInfo.outputPath('white-labelling-mobile-local-fixture.png')});
    await page.setViewportSize({width:1680,height:1100});
    await page.goto('/create/apps/app-fixture');
    const editor=page.locator('app-experience-editor');
    await editor.getByRole('button',{name:'Visual identity',exact:true}).click();
    const identity=editor.locator('app-brand-appearance-editor');
    await expect(identity.getByRole('combobox',{name:'Palette',exact:true})).toHaveValue('sand');
    await identity.getByRole('combobox',{name:'Palette',exact:true}).selectOption('graphite');
    await identity.getByLabel('Action colour').fill('#0e7490');
    await editor.locator('#xp-bottom-panel').getByRole('button',{name:'Save',exact:true}).click();
    await expect.poll(()=>draftApp.theme.appearance.accent).toBe('#0e7490');
    await page.reload();
    await editor.getByRole('button',{name:'Visual identity',exact:true}).click();
    await expect(identity.getByRole('combobox',{name:'Palette',exact:true})).toHaveValue('graphite');
    await identity.locator('.brand-preview').scrollIntoViewIfNeeded();
    await page.screenshot({path:testInfo.outputPath('white-labelling-studio-local-fixture.png')});
    await page.goto('/work/branded-app');
    await expect(page.getByRole('heading',{name:'NorthForge Operations',exact:true})).toBeVisible();
    const app = page.locator('app-work-shell > .xp-work');
    await expect(app).toHaveAttribute('data-theme','dark');
    await expect(app).toHaveCSS('background-color','rgb(9, 9, 9)');
    await expect(app).toHaveCSS('color','rgb(245, 245, 245)');
    await page.screenshot({path:testInfo.outputPath('white-labelling-published-local-fixture.png'),fullPage:true});
    expect(errors).toEqual([]);
  });
});
