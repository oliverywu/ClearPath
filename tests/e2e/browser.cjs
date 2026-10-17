/* Browser acceptance test. Uses an isolated database and locally hosted services. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const net = require('node:net');
const { spawn, spawnSync } = require('node:child_process');
const root = path.resolve(__dirname, '../..');
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function freePort() {
  const server = net.createServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return port;
}
function python() {
  const bundled = path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe');
  for (const candidate of [process.env.CFT_PYTHON, process.platform === 'win32' && bundled, 'python3', 'python', 'py'].filter(Boolean)) {
    if (spawnSync(candidate, ['-c', 'import sys; sys.exit(sys.version_info < (3, 11))']).status === 0) return candidate;
  }
  throw new Error('Python 3.11+ is required. Set CFT_PYTHON to its executable.');
}
async function main() {
  fs.mkdirSync(path.join(root, '.local'), {recursive:true});
  const temp = fs.mkdtempSync(path.join(root, '.local/cleared-browser-'));
  const webPort = await freePort(), apiPort = await freePort();
  const base = `http://127.0.0.1:${webPort}`;
  const child = spawn(python(), ['start.py', '--web-port', String(webPort), '--api-port', String(apiPort), '--db', path.join(temp, 'browser.sqlite3')], {cwd: root, windowsHide: true});
  let logs = '';
  child.stdout.on('data', b => logs += b.toString()); child.stderr.on('data', b => logs += b.toString());
  let browser;
  async function api(endpoint, body) {
    const res = await fetch(base + endpoint, body === undefined ? undefined : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    assert.equal(res.ok, true, `${endpoint}: ${res.status} ${await res.clone().text()}`);
    return res.json();
  }
  try {
    let ready = false;
    for (let i=0; i<120; i++) { try { if ((await fetch(base+'/api/health')).ok) {ready=true;break;} } catch {} await sleep(100); }
    assert.equal(ready, true, logs);
    const boot = await api('/api/bootstrap');
    browser = await chromium.launch({headless:true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? {executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE} : {})});
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(base);
    await page.locator('.country-tile').first().waitFor();
    assert.match(await page.locator('#generate-plan').innerText(), /Check sources & recalculate/i);
    assert.match(await page.locator('#reset-demo').innerText(), /Restore demo starting point/i);
    assert.equal(await page.locator('body').evaluate(el => getComputedStyle(el).fontSize), '15px');
    assert.equal(await page.locator('.country-tile').count(), boot.jurisdictions.length);
    await page.locator('.calendar-card').waitFor();
    assert.ok(await page.locator('.calendar-event').count() > 0, 'Dashboard calendar should contain scenario milestones');
    fs.mkdirSync(path.join(root, 'test-results'), {recursive:true});
    await page.screenshot({path:path.join(root,'test-results/control-tower.png'),fullPage:true});
    let sourceCheckMode = 'clean';
    await page.route('**/api/sources/check-all', route => {
      const payload = sourceCheckMode === 'clean'
        ? {checked:1,changed:0,failed:0,results:[{source_id:'official-1',title:'Official rule'}]}
        : sourceCheckMode === 'changed'
          ? {checked:1,changed:1,failed:0,results:[{source_id:'official-1',title:'Official rule',changed:true}]}
          : {checked:1,changed:0,failed:1,results:[{source_id:'official-1',title:'Official rule',error:'timed out'}]};
      return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(payload)});
    });
    await page.locator('#generate-plan').click();
    await page.locator('.page-heading h1').filter({hasText:'Plans & decisions'}).waitFor();
    assert.match(await page.locator('#notice').innerText(), /All registered sources were checked and no changes were detected/i);
    await page.locator('[data-view="overview"]').click();
    sourceCheckMode = 'changed';
    const scenariosBeforeSourceChange = (await api('/api/bootstrap')).scenarios.length;
    await page.locator('#generate-plan').click();
    await page.locator('#ai-analyze-change').waitFor();
    assert.match(await page.locator('#notice').innerText(), /source change was detected[\s\S]*No proposal was created/i);
    assert.equal((await api('/api/bootstrap')).scenarios.length, scenariosBeforeSourceChange, 'A detected source change must pause proposal creation');
    await page.locator('[data-view="overview"]').click();
    sourceCheckMode = 'failed';
    await page.locator('#generate-plan').click();
    await page.locator('#continue-saved-evidence').waitFor();
    assert.match(await page.locator('#notice').innerText(), /could not be checked[\s\S]*no proposal was created/i);
    await page.locator('#continue-saved-evidence').click();
    await page.locator('.page-heading h1').filter({hasText:'Plans & decisions'}).waitFor();
    assert.match(await page.locator('#notice').innerText(), /without checking source links/i);
    await page.unroute('**/api/sources/check-all');
    await page.locator('[data-view="overview"]').click();
    await page.locator('[data-country="DE"]').click();
    await page.locator('.country-context-card').waitFor();
    assert.match(await page.locator('.country-context-card').innerText(), /Germany[\s\S]*Rules active as of[\s\S]*Projected delivery[\s\S]*Target delivery/i);
    await page.locator('.rule-select').first().waitFor();
    await page.locator('tr').filter({hasText:'Synthetic'}).locator('.rule-select').first().click();
    assert.match(await page.locator('#evidence-content').innerText(), /Synthetic/i);
    await page.locator('.delivery-progress').waitFor();
    assert.match(await page.locator('#timeline-panel').innerText(), /Delay exposure|business days slack/i);
    await page.locator('#req-country').selectOption('JP');
    await page.locator('#requirements-list .callout').waitFor();
    assert.match(await page.locator('#requirements-list .callout').innerText(), /6 official-source candidates need review/i);
    assert.equal(await page.locator('.requirements-table-wrap').evaluate(el => el.scrollWidth <= el.clientWidth + 1), true, 'Requirements table should fit without horizontal scrolling');
    await page.locator('[data-req-sort="type"]').click();
    assert.match(await page.locator('[data-req-sort="type"]').innerText(), /Rule type\s*[▲▼]/i);
    await page.locator('[data-req-sort="date"]').click();
    assert.match(await page.locator('[data-req-sort="date"]').innerText(), /Effective\s*[▲▼]/i);
    await page.locator('[data-req-sort="review"]').click();
    await page.locator('.rule-select').first().click();
    assert.match(await page.locator('#evidence-content').innerText(), /Needs Review Official[\s\S]*MHLW/i);
    await page.locator('[data-view="scenarios"]').click();
    assert.equal(await page.locator('.page-heading h1').innerText(), 'Plans & decisions');
    const jp = boot.events.find(e => e.jurisdiction === 'JP');
    assert.match(await page.locator(`[data-analyze="${jp.id}"]`).innerText(), /Calculate impact/i);
    await page.locator(`[data-analyze="${jp.id}"]`).click();
    await page.locator('[data-repair]').first().waitFor();
    await page.screenshot({path:path.join(root,'test-results/japanese-change.png'),fullPage:true});
    const jpRepair = jp.repair_options?.find(o=>o.recommended) || jp.repair_options?.[0];
    const repairResponse = page.waitForResponse(r => r.url().endsWith(`/api/change-events/${jp.id}/analyze`) && r.request().method() === 'POST');
    if (jpRepair) await page.locator(`[data-repair="${jpRepair.id}"]`).click();
    else await page.locator('[data-repair]').first().click();
    const repairedPlan = await (await repairResponse).json();
    await page.locator(`[data-approve="${repairedPlan.id}"]`).waitFor();
    await page.locator(`[data-approve="${repairedPlan.id}"]`).click();
    await page.locator('#decision-name').fill('Browser acceptance reviewer');
    await page.locator('#decision-note').fill('Reviewed synthetic Japanese separate-label repair.');
    await page.locator('#decision-submit').click();
    await page.locator('.modal').waitFor({state:'hidden'});
    const approvedBoot = await api('/api/bootstrap');
    assert.equal(approvedBoot.approved_scenario.id, repairedPlan.id);
    assert.equal(approvedBoot.approved_scenario.selected_repairs[jp.id], jpRepair.id);
    assert.equal(approvedBoot.approved_scenario.metrics.blocked_shipments, 0);
    const downloadPromise = page.waitForEvent('download');
    await page.locator('#calendar-btn').click();
    const download = await downloadPromise;
    const calendarPath = path.join(temp, 'approved.ics');
    await download.saveAs(calendarPath);
    const ics = fs.readFileSync(calendarPath, 'utf8');
    assert.match(ics, /BEGIN:VCALENDAR/);
    assert.ok(ics.split('BEGIN:VEVENT').length > boot.jurisdictions.length * 10);
    const de = boot.events.find(e => e.jurisdiction === 'DE');
    await page.locator(`[data-analyze="${de.id}"]`).click();
    await page.locator('[data-repair]').first().waitFor();
    await page.locator('#toggle-full-plan').waitFor();
    assert.ok(await page.locator('#scenario-shipments tbody tr').count() < boot.jurisdictions.length, 'Comparison should default to changed shipments');
    await page.locator('#toggle-full-plan').click();
    assert.equal(await page.locator('#scenario-shipments tbody tr').count(), boot.jurisdictions.length, 'Full plan should remain available');
    await page.screenshot({path:path.join(root,'test-results/german-disruption.png'),fullPage:true});
    await page.locator('[data-view="assistant"]').click();
    await page.locator('#chat-question').fill('Why is Germany at risk?');
    await page.locator('#chat-form button').click();
    await page.locator('.cite').first().waitFor();
    assert.match(await page.locator('#chat-messages').innerText(), /synthetic|simulat/i);
    await page.locator('[data-view="audit"]').click();
    await page.locator('#audit-list tbody tr').first().waitFor();
    assert.match(await page.locator('#audit-list').innerText(), /approv/i);
    await page.locator('[data-view="imports"]').click();
    await page.locator('#rules-json').fill('[{"jurisdiction":"XX"}]');
    await page.locator('#preview-rules').click();
    await page.getByText('Validation needs attention', {exact:true}).waitFor();
    const replacementText = fs.readFileSync(path.join(root,'data/demo/replacement.json'),'utf8');
    await page.locator('#dataset-json').evaluate((element, value) => {
      element.value = value;
      element.dispatchEvent(new Event('input', {bubbles:true}));
    }, replacementText);
    await page.locator('#preview-dataset').click();
    await page.locator('#reviewer-dataset').waitFor();
    await page.locator('#reviewer-dataset').fill('Browser acceptance reviewer');
    await page.locator('[data-commit="dataset"]').click();
    await page.getByText('Dataset import committed.', {exact:false}).waitFor();
    const replaced = await api('/api/bootstrap');
    const pending = replaced.scenarios.find(s=>s.status === 'proposed');
    assert.ok(pending, 'Dataset replacement must create a reviewable proposal');
    await page.locator('[data-view="scenarios"]').click();
    await page.locator(`[data-approve="${pending.id}"]`).waitFor();
    await page.locator(`[data-approve="${pending.id}"]`).click();
    await page.locator('#decision-name').fill('Browser acceptance reviewer');
    await page.locator('#decision-note').fill('Reviewed replacement dataset plan.');
    await page.locator('#decision-submit').click();
    await page.locator('.modal').waitFor({state:'hidden'});
    await page.locator('[data-view="overview"]').click();
    await page.locator('.country-tile').first().waitFor();
    assert.notEqual((await api('/api/bootstrap')).trial.id, boot.trial.id);
    assert.equal((await api('/api/bootstrap')).approved_scenario.shipments.length, 6);
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.join(root,'test-results/mobile.png'),fullPage:true});
    const overflow = await page.evaluate(()=>document.documentElement.scrollWidth > window.innerWidth + 2);
    assert.equal(overflow, false, 'Mobile layout overflows viewport');
    assert.deepEqual(errors, [], `Browser uncaught errors: ${errors.join(' | ')}`);
    console.log('PASS browser: control tower, evidence, Japan change/repair/approval, ICS, Germany disruption, assistant, audit, invalid import, replacement dataset, mobile, zero page errors.');
  } finally {
    if (browser) await browser.close();
    if (process.platform === 'win32') spawnSync('taskkill', ['/PID',String(child.pid),'/T','/F'], {windowsHide:true});
    else child.kill('SIGINT');
    await sleep(500);
    fs.rmSync(temp, {recursive:true,force:true});
  }
}
main().catch(error => {console.error(error);process.exitCode=1;});
