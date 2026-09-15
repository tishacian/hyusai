import {expect,test} from '@playwright/test';
import {expectOk} from '../fixtures/api';
import {loginAsAlice} from '../fixtures/auth';

/** Read-only live canary. Uses existing auth and canonical Runs; never alters answers. */
test('evaluation and chart inspection retain the exact Run',async({page},testInfo)=>{
 await loginAsAlice(page);
 const workspace = process.env['E2E_SHOWCASE_WORKSPACE_SLUG'];
 if(workspace){await page.evaluate(slug=>localStorage.setItem('agentium_workspace_slug',slug),workspace);await page.reload();}
 const history=await expectOk<{evaluations:Array<{run_id:string;status:string;composite_score:number|null}>}>(page,'/api/v1/evaluation/history?limit=20&since=30d');
 const item=history.evaluations.find(row=>row.run_id);
 test.skip(!item,'The selected workspace needs a real evaluated Run for observability acceptance.');
 const runId=item!.run_id;
 const result=await expectOk<{status:string;composite_score?:number|null;metadata?:{excerpts?:Array<{id:string;availability?:string;text?:string|null}>}}>(page,`/api/v1/evaluation/by-run/${encodeURIComponent(runId)}`);
 expect(['completed','partial','failed','skipped','queued','running','unavailable','historical']).toContain(result.status);
 if(['failed','unavailable','skipped'].includes(result.status))expect(result.composite_score == null).toBe(true);
 for(const excerpt of result.metadata?.excerpts || [])if(excerpt.availability==='source_unavailable')expect(excerpt.text).toBeNull();
 await page.goto('/observability/quality?since=30d');
 await expect(page.locator('app-quality-evidence-charts')).toBeVisible();
 const point=page.locator(`app-quality-evidence-charts [role=button][aria-label^="${runId}:"]`);
 await point.click();
 const evidenceLink=page.locator('app-quality-evidence-charts .selection a');
 await expect(evidenceLink).toHaveAttribute('href',new RegExp(`/runs/${runId}(?:[?]|$)`));
 await page.screenshot({path:testInfo.outputPath('quality-chart.png'),fullPage:true});
 await evidenceLink.click();
 await expect(page.locator('app-run-investigation')).toBeVisible();
 await page.reload();
 await expect(page.locator('app-run-investigation')).toBeVisible();
 expect(new URL(page.url()).pathname).toBe(`/runs/${runId}`);
 await page.screenshot({path:testInfo.outputPath('run-investigation.png'),fullPage:true});
});
