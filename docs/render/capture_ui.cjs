// Renders the Agentium UI mockup screens to PNGs for the product document.
const { chromium } = require('playwright');
const path = require('path');
const ROOT = path.resolve(__dirname, '../..');
const MOCK = 'file://' + path.join(ROOT, 'docs/mockups/Agentium.html');
const OUT = path.join(__dirname, 'assets/screens');
const views = [
  ['Hypervisor', 'ui-hypervisor.png'],
  ['Builder',    'ui-builder.png'],
  ['Steering',   'ui-steering.png'],
  ['Run',        'ui-run.png'],
];
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport:{width:1480,height:920}, deviceScaleFactor:2 });
  await p.goto(MOCK, { waitUntil:'load', timeout:45000 });
  await p.waitForTimeout(4000);
  for (const [name, file] of views) {
    await p.click(`button[title^="${name}"]`);
    await p.waitForTimeout(2000);
    await p.screenshot({ path: path.join(OUT, file), fullPage:false });
    console.log('captured', file);
  }
  await b.close();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
