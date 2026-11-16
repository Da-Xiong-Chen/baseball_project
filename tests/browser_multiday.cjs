const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const playwright=require(process.env.PLAYWRIGHT_PACKAGE||'playwright');

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

async function checkReplayHistory(browser) {
  const page=await browser.newPage({viewport:{width:390,height:880}});
  try {
    const date=catalog.days.find(row=>row.date==='2026-04-01');
    const {game,pa,decision}=date.case;
    const url=new URL(base);
    url.search=new URLSearchParams({replay:date.date,game,pa,decision});
    await page.goto(url.href);
    const result=page.locator('#resultBody');
    await result.locator('.scoreboard').waitFor();
    await result.locator('.tabs [data-t=ph]').click();
    await page.locator('#resultBody[data-replay-decision=ph]').waitFor();
    await page.goBack();
    await page.locator('#resultBody[data-replay-decision=pen]').waitFor();
    const scoreboard=await result.locator('.scoreboard').elementHandle();
    await result.locator('.evaluation-nav [href="#candidateCompare"]').click();
    await page.waitForURL(url=>url.hash==='#candidateCompare');
    await page.goBack();
    assert.equal(await scoreboard.evaluate(el=>el.isConnected),true,'an in-page jump must not rerender the comparison');
    await page.locator('[data-entry=general]').click();
    await page.locator('[data-entry=general][aria-current=page]').waitFor();
    await page.goBack();
    await page.locator('#resultBody[data-replay-decision=pen]').waitFor();
    await page.goForward();
    await page.locator('[data-entry=general][aria-current=page]').waitFor({timeout:4000});
    await page.goBack();
    await page.locator('#resultBody[data-replay-decision=pen]').waitFor();
    await page.locator('[data-entry=team]').click();
    await page.locator('#lineupPage').waitFor();
    await page.goBack();
    await page.locator('#resultBody[data-replay-decision=pen]').waitFor();
    await page.goForward();
    await page.locator('[data-entry=team][aria-current=page]').waitFor();
    await page.locator('#lineupPage').waitFor();
    await page.goBack();
    await page.locator('#resultBody[data-replay-decision=pen]').waitFor();
    await page.locator('#replayDate').selectOption('2026-09-20');
    await page.locator('#gameList [data-g]').first().waitFor();
    await page.locator('#replayDate').selectOption('2026-05-15');
    await page.locator('#gameList [data-g]').first().waitFor();
    await page.goBack();
    await page.locator('[data-sub=replay].on').waitFor({timeout:4000});
    assert.equal(await page.locator('#replayDate').inputValue(),'2026-09-20');
    await page.locator('#gameList [data-g]').first().waitFor();
    await page.goto(base);
    await page.locator('#evalBtn:enabled').waitFor();
    await page.locator('[data-entry=review]').click();
    await page.locator('#reviewPage .replay-match-heading').first().waitFor();
    let reloaded=false;
    page.on('request',request=>{if(request.isNavigationRequest())reloaded=true;});
    await page.locator('#replayFeatured').click();
    await result.locator('.scoreboard').waitFor();
    await page.goBack();
    await page.locator('#reviewPage .replay-match-heading').first().waitFor();
    assert.equal(reloaded,false,'featured cases preserve the existing document and review state');
    console.log('Passed forward and back across replay tabs, dates, featured cases and general evaluation');
  } finally {await page.close();}
}

async function checkFieldingEvidence(browser) {
  const page=await browser.newPage({viewport:{width:390,height:880}});
  const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  const date=catalog.days.find(row=>row.observed_case);
  const {pa}=date.observed_case;
  const evidence=JSON.parse(fs.readFileSync(path.join(__dirname,`../docs/data/replay/day-${date.date}/evidence.json`),'utf8'));
  const matching=(predicate)=>Object.entries(evidence.fielding).find(([,row])=>predicate(row));
  const open=async (pa,decision='ph',replay=date.date)=>{
    const url=new URL(base);
    url.search=new URLSearchParams({replay,game:pa.slice(0,8),pa,decision});
    await page.goto(url.href);
    await page.locator('#resultBody .scoreboard').waitFor();
  };
  try {
    let requests=0;
    await page.route('**/day-2026-07-29/evidence.json',route=>
      ++requests===1?route.fulfill({status:503}):route.continue());
    await page.goto(base);
    await page.locator('[data-entry=review]').click();
    await page.locator('#replayCase').waitFor();
    await page.locator('#replayCase').selectOption({label:'代打後實際接守 · 07/29'});
    await page.locator('#resultBody .scoreboard').waitFor();
    assert.equal(new URL(page.url()).searchParams.get('pa'),pa);
    assert.equal(await page.locator('[data-observed-fielding]').isVisible(),false);
    assert.equal(requests,0,'the published fielding example loads evidence on disclosure');
    const action=page.locator('[data-reveal-action] > summary');
    await action.focus();
    await action.press('Enter');
    const fielding=page.locator('[data-observed-fielding]');
    const retry=fielding.getByRole('button',{name:'重試'});
    await retry.click();
    await fielding.getByText(/下一個守備半局守捕手/).waitFor();
    assert.equal(requests,2);
    assert.equal(await page.locator('[data-reveal-outcome]').evaluate(el=>el.open),false);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),390);
    for(const [status,text] of [['other_player_fielded',/右外野由 王苡丞 防守/],['no_defensive_half',/沒有下一個守備半局/]]){
      const [other]=matching(row=>row.status===status);
      await open(other);
      await page.locator('[data-reveal-action] > summary').click();
      await page.locator('[data-observed-fielding]').getByText(text).waitFor();
    }
    const [blocked]=Object.entries(evidence.availability).find(([,states])=>states.ph==='fielding_unconfirmed');
    await open(blocked);
    await page.locator('[data-replay-availability]').getByText('有板凳人選，但守位紀錄無法確認接守。').waitFor();
    const opening='2026-03-29';
    const early=JSON.parse(fs.readFileSync(path.join(__dirname,`../docs/data/replay/day-${opening}/evidence.json`),'utf8'));
    const [empty]=Object.entries(early.availability).find(([,states])=>states.pen==='no_prior_pool');
    await open(empty,'pen',opening);
    await page.locator('[data-replay-availability]').getByText('賽前觀察期間沒有符合候選條件的出賽紀錄。').waitFor();
    assert.deepEqual(errors,[]);
    console.log('Passed scenario links, keyboard disclosure, blocked-candidate explanation and three fielding outcomes');
  } finally { await page.close(); }
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
    const calculate=capacity.locator('[data-calculate]');
    await capacity.locator('[data-target]').fill('3');
    for(const row of await capacity.locator('[data-arm]').all()) {
      if(await row.locator('[data-order]').inputValue()==='1'||await row.locator('[data-order-b]').inputValue()==='1') {
        await row.locator('[data-capacity]').fill('4');
      }
    }
    await calculate.click();
    assert.equal(await capacity.getByText('容量足夠',{exact:true}).count(),2);
    await fits();
    // Two substitutions in the existing worksheet must unwind in order.
    const choose=async()=>{
      const button=page.locator('[data-apply-kind=pen]').first();
      await button.waitFor();
      const id=await button.getAttribute('data-apply-sub');
      await page.locator('#confirmChangeEligibility').check();
      await button.click();
      await page.locator('[data-sub-undo]').waitFor();
      assert.equal(await field.inputValue(),id);
      return id;
    };
    const prior=await choose();
    assert.equal(await calculate.isDisabled(),true,'old bullpen capacity must clear on a confirmed pitching change');
    assert.equal(await capacity.getByText('容量足夠',{exact:true}).count(),0);
    await choose();
    await page.locator('.substitution-history summary').getByText(/（2）/).waitFor();
    await page.locator('[data-sub-undo]').click();
    await page.waitForFunction(id=>document.querySelector('#myPitcher').value===id,prior);
    await page.locator('.substitution-history summary').getByText(/（1）/).waitFor();
    await page.locator('[data-sub-undo]').click();
    await page.waitForFunction(id=>document.querySelector('#myPitcher').value===id,incumbent);
    await page.getByText('已復原上一次換人。').waitFor();
    assert.equal(await calculate.isEnabled(),true,'undo restores the matching saved worksheet');
    await calculate.click();
    assert.equal(await capacity.getByText('容量足夠',{exact:true}).count(),2);
    await choose();
    await page.locator('#penAll').click();
    const out=page.locator(`#penList input[value="${incumbent}"]`);
    assert.equal(await field.locator(`option[value="${incumbent}"]`).isDisabled(),true,'an exited pitcher cannot be selected as the incumbent');
    assert.equal(await out.isDisabled(),true);
    assert.equal(await out.isChecked(),false,'select all cannot reselect a retired pitcher');
    await capacity.locator('[data-refresh]').click();
    const retiredName=await page.evaluate(id=>playerText(id),incumbent);
    assert.equal(await capacity.locator('legend').getByText(retiredName,{exact:true}).count(),0);
    const teamSelect=page.locator('#myTeam');
    const anotherTeam=await teamSelect.locator('option:enabled').evaluateAll(options=>options.find(option=>!option.selected).value);
    await teamSelect.selectOption(anotherTeam);
    await page.locator('#evalBtn:enabled').waitFor();
    assert.equal(await capacity.locator('[data-rows]').isHidden(),true,'other team cannot see old pitcher rows');
    await capacity.locator('[data-refresh]').click();
    await capacity.locator('[data-rows]').waitFor();
    assert.equal(await calculate.isEnabled(),true);
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
  const engine=playwright[process.env.BASEBALL_QA_BROWSER||'chromium'];
  const browser=await engine.launch(process.env.BASEBALL_QA_EXECUTABLE?{executablePath:process.env.BASEBALL_QA_EXECUTABLE}:{});
  try {
    await checkCatalogRetry(browser);
    await checkReplayHistory(browser);
    await checkFieldingEvidence(browser);
    for(const width of (process.env.BASEBALL_QA_WIDTHS||'390,1280').split(',').map(Number))await check(browser,width);
  }
  finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
