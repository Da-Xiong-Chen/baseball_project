const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_PACKAGE||'playwright');

const base=process.env.BASEBALL_QA_URL||'http://127.0.0.1:8052/';
const catalog=JSON.parse(fs.readFileSync(path.join(__dirname,'../docs/data/replay/dates.json'),'utf8'));

async function checkCatalogRetry(browser) {
  const page=await browser.newPage({viewport:{width:390,height:880}});
  const april=catalog.days.find(row=>row.date==='2026-04-01');
  const {game,pa,decision}=april.case;
  const url=new URL(base);
  url.search=new URLSearchParams({replay:april.date,game,pa,decision});
  let requests=0;
  try {
    await page.route('**/data/replay/dates.json',route=>
      ++requests===1?route.fulfill({status:503}):route.continue());
    await page.goto(url.href);
    await page.getByText('暫時無法確認分享日期，請重新載入日期。').waitFor({timeout:8000});
    assert.equal(page.url(),url.href);
    assert.equal(requests,1);
    await page.locator('#replayCatalogRetry').click();
    await page.locator('#resultBody .scoreboard').waitFor();
    assert.equal(await page.locator('#replayDate').inputValue(),april.date);
    assert.equal(await page.locator('[data-reveal-outcome]').evaluate(el=>el.open),false);
    assert.equal(page.url(),url.href);
    assert.equal(requests,2);
    console.log('Passed recovery of a valid replay link after a temporary date catalogue failure');
  } finally {await page.close();}
}

async function check(browser,width) {
  const page=await browser.newPage({viewport:{width,height:880},deviceScaleFactor:1});
  const errors=[], requests=[];
  page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>requests.push(new URL(request.url()).pathname));
  const fits=async()=>assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),width);
  try {
    await page.goto(base);
    await page.locator('#evalBtn:enabled').waitFor();
    assert.ok(!requests.some(p=>p.includes('/data/replay/')||p.includes('/data/player-notes-')),'initial load fetches no replay or player notes data');
    await page.locator('[data-entry=review]').click();
    await page.waitForFunction(n=>document.querySelector('#replayDate').options.length===n,catalog.days.length);
    await page.locator('#reviewBody .replay-match-heading').first().waitFor();
    await fits();
    await page.locator('#replayDate').selectOption('2026-04-01');
    await page.locator('#reviewBody .replay-match-heading').first().waitFor();
    assert.match(await page.locator('#reviewTitle').innerText(),/2026\/04\/01/);
    assert.match(page.url(),/replay=2026-04-01/);
    assert.ok(requests.some(p=>p.endsWith('/day-2026-04-01/index.json')));
    assert.ok(!requests.some(p=>p.includes('/day-2026-05-15/')),'unselected day stays unloaded');
    const link=page.locator('#replayFeatured');
    const april=catalog.days.find(row=>row.date==='2026-04-01');
    assert.match(await link.getAttribute('href'),new RegExp(april.case.pa));
    await link.click();
    await page.locator('#resultBody .scoreboard').waitFor();
    assert.equal(new URL(page.url()).searchParams.get('pa'),april.case.pa);
    assert.equal(await page.locator('[data-reveal-outcome]').evaluate(el=>el.open),false);
    await page.locator('.replay-extra-filters summary').click();
    await page.locator('#replayMargin').selectOption('0');
    const ids=await page.locator('#paList [data-p]').evaluateAll(nodes=>nodes.map(node=>node.dataset.p));
    const states=await page.evaluate(()=>S.pas);
    assert.ok(ids.every(id=>states.some(p=>p.pa_id===id&&p.bat_score===p.fld_score)));
    await page.locator('#replayReset').click();
    assert.equal(await page.locator('#replayMargin').inputValue(),'');
    await page.locator('.replay-extra-filters summary').click();
    await fits();
    if (process.env.BASEBALL_SCREENSHOT_DIR) await page.screenshot({
      path:path.join(process.env.BASEBALL_SCREENSHOT_DIR,`replay-${width}.png`)});
    await page.locator('#replayDate').selectOption('2026-09-20');
    await page.locator('#gameList [data-g]').first().waitFor();
    await page.goBack();
    await page.locator('#resultBody .scoreboard').waitFor();
    assert.equal(await page.locator('#replayDate').inputValue(),'2026-04-01');
    await page.goto(new URL('?replay=2026-12-31&game=missing&pa=missing&decision=pen',base).href);
    await page.getByText('此日期尚未收錄。請選擇其他日期。').waitFor();
    assert.equal(await page.locator('#resultBody .scoreboard').count(),0);
    await fits();
    await page.goto(base);
    await page.locator('#evalBtn:enabled').waitFor();
    await page.locator('[data-view=defense]').click();
    await page.locator('#evalBtn:enabled').click();
    const firstA=page.locator('[data-plan-slot=A]').first();
    await firstA.waitFor();
    const a=await firstA.getAttribute('data-plan-pitcher');
    const lastB=page.locator('[data-plan-slot=B]').last();
    const b=await lastB.getAttribute('data-plan-pitcher');
    assert.notEqual(a,b);
    const note=page.locator('[data-player-note] summary').first();
    await note.click();
    await page.locator('.player-notes').first().waitFor();
    const field=page.locator('#myPitcher');
    const incumbent=await field.inputValue();
    await firstA.click();
    const capacity=page.locator('#bullpenCapacity');
    await capacity.locator('[data-output]').getByText(/方案 A 第一順位/).waitFor();
    assert.equal(await capacity.locator('[data-order]').first().getAttribute('aria-invalid'),null);
    const rankA=await capacity.locator('[data-order]').evaluateAll(els=>els.map(e=>e.value));
    assert.equal(rankA.filter(v=>v==='1').length,1);
    await lastB.click();
    await capacity.locator('[data-output]').getByText(/方案 B 第一順位/).waitFor();
    assert.deepEqual(await capacity.locator('[data-order]').evaluateAll(els=>els.map(e=>e.value)),rankA);
    assert.equal(await field.inputValue(),incumbent);
    assert.equal(await capacity.locator('[data-order-b]').evaluateAll(els=>els.filter(e=>e.value==='1').length),1);
    await fits();
    // Two substitutions in the existing worksheet must unwind in order.
    const choose=async()=>{
      const button=page.locator('[data-apply-kind=pen]').first();
      await button.waitFor();
      const id=await button.getAttribute('data-apply-sub');
      await button.click();
      await page.locator('[data-sub-undo]').waitFor();
      assert.equal(await field.inputValue(),id);
      return id;
    };
    const prior=await choose();
    await choose();
    await page.locator('.substitution-history summary').getByText(/（2）/).waitFor();
    await page.locator('[data-sub-undo]').click();
    await page.waitForFunction(id=>document.querySelector('#myPitcher').value===id,prior);
    await page.locator('.substitution-history summary').getByText(/（1）/).waitFor();
    await page.locator('[data-sub-undo]').click();
    await page.waitForFunction(id=>document.querySelector('#myPitcher').value===id,incumbent);
    await page.getByText('已復原上一次換人。').waitFor();
    await page.locator('[data-entry=team]').click();
    await page.locator('#lineupApply:enabled').waitFor();
    await page.locator('#lineupBackup summary').click();
    const downloadPromise=page.waitForEvent('download');
    await page.locator('#lineupExport').click();
    const file=await (await downloadPromise).path();
    await page.locator('#lineupImport').setInputFiles(file);
    await page.locator('#lineupMessage').getByText(/草稿已保存/).waitFor();
    await fits();
    assert.deepEqual(errors,[]);
    console.log(`Passed multi-date lookup, deep links, mobile width and bullpen A/B at ${width}px`);
  } finally {await page.close();}
}

(async()=>{
  const browser=await chromium.launch(process.env.BASEBALL_QA_EXECUTABLE?{executablePath:process.env.BASEBALL_QA_EXECUTABLE}:{});
  try {
    await checkCatalogRetry(browser);
    for(const width of (process.env.BASEBALL_QA_WIDTHS||'390,1280').split(',').map(Number))await check(browser,width);
  }
  finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
