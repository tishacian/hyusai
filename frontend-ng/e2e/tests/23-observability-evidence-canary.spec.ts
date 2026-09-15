import {expect,test} from '@playwright/test';
import {expectOk} from '../fixtures/api';
import {loginAsAlice} from '../fixtures/auth';

/** Read-only live canary. Uses existing auth and canonical Runs; never alters answers. */
test('evaluation and chart inspection retain the exact Run',async({page})=>{
 await loginAsAlice(page);
 const history=await expectOk<{evaluations:Array<{run_id:string;status:string;composite_score:number|null}>}>(page,'/api/v1/evaluation/history?limit=20&since=30d');
 const item=history.evaluations.find(row=>row.run_id);
 test.skip(!item,'The selected workspace needs a real evaluated Run for observability acceptance.');
 const runId=item!.run_id;
 const result=await expectOk<{status:string;composite_score?:number|null;metadata?:{excerpts?:Array<{id:string;availability?:string;text?:string|null}>}}>(page,`/api/v1/evaluation/by-run/${encodeURIComponent(runId)}`);
 expect(['completed','partial','failed','skipped','queued','running','unavailable','historical']).toContain(result.status);
 if(['failed','unavailable','skipped'].includes(result.status))expect(result.composite_score == null).toBe(true);
 for(const excerpt of result.metadata?.excerpts || [])if(excerpt.availability==='source_unavailable')expect(excerpt.text).toBeNull();
 await page.goto(`/runs/${encodeURIComponent(runId)}`);
 await expect(page.locator('app-run-investigation')).toBeVisible();
 await page.reload();
 await expect(page.locator('app-run-investigation')).toBeVisible();
 expect(new URL(page.url()).pathname).toBe(`/runs/${runId}`);
});
