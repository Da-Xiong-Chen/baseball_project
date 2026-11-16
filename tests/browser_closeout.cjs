// Browser smoke test. Run with Playwright installed and the site already served.
const assert = require('node:assert/strict');
const { chromium, webkit } = require(process.env.PLAYWRIGHT_PACKAGE || 'playwright');

const base = process.env.BASEBALL_QA_URL || 'http://127.0.0.1:8042/';
const name = process.env.BASEBALL_QA_BROWSER || 'chromium';
const width = Number(process.env.BASEBALL_QA_WIDTH || 720);
const replay = new URL('?replay=2026-10-04&game=2026-251&pa=2026-251-a000&decision=pen', base).href;

async function assertFits(page) {
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),width);
}

async function openLineup(page) {
  await page.goto(base);
  await page.locator('#evalBtn:enabled').waitFor();
  await page.locator('[data-entry=team]').press('Enter');
  await page.locator('#lineupRows [data-pick="8"]').waitFor();
  await page.locator('#lineupApply:enabled').waitFor();
}

async function evaluation(page) {
  await page.goto(base);
  const evaluate = page.locator('#evalBtn');
  await evaluate.waitFor();
  await page.locator('#evalBtn:enabled').waitFor();
  await page.locator('#outs [data-o="2"]').press('Enter');
  for (const base of [1,2,4]) await page.locator(`#baseControls [data-b="${base}"]`).press('Enter');
  await page.locator('#myScore').fill('2');
  await evaluate.press('Enter');
  const result = page.locator('#resultBody');
  await result.locator('.result-scope').waitFor();
  assert.match(await result.innerText(), /2 出局・滿壘/);
  await page.locator('#benchNone').press('Enter');
  assert.equal(await result.isVisible(), false);
  await evaluate.press('Enter');
  await result.locator('.result-scope').waitFor();
  assert.match(await result.innerText(), /沒有|尚無/);
  await page.locator('[data-view=defense]').press('Enter');
  await page.locator('#halfSeg [data-half=home]').press('Enter');
  await evaluate.press('Enter');
  await result.locator('.result-scope').waitFor();
  assert.match(await result.innerText(), /後續 3 棒/);
  assert.equal(await result.locator('.sb-inning small').innerText(), '局下');
  const select = page.locator('#myPitcher');
  const current = await select.inputValue();
  const values = await select.locator('option:enabled').evaluateAll(options => options.map(o => o.value));
  const alternate = values.find(value => value && value!==current);
  assert.ok(alternate);
  await select.selectOption(alternate);
  assert.equal(await result.isVisible(), false);
  await evaluate.press('Enter');
  await result.locator('.result-scope').waitFor();
  assert.match(await result.innerText(), /後續 3 棒/);
  await page.locator('#penNone').press('Enter');
  assert.equal(await result.isVisible(), false);
  const team = page.locator('#myTeam');
  const selectedTeam = await team.inputValue();
  const teams = await team.locator('option:enabled').evaluateAll(options => options.map(o => o.value));
  await team.selectOption(teams.find(value=>value!==selectedTeam));
  await page.locator('#evalBtn:enabled').waitFor();
  await evaluate.press('Enter');
  await result.locator('.result-scope').waitFor();
  assert.match(await result.locator('.sb-score').innerText(),new RegExp(await team.inputValue()));
  await assertFits(page);
}

async function lineup(context) {
  const first = await context.newPage(), second = await context.newPage();
  await openLineup(first);
  await first.locator('#lineupApply').press('Enter');
  await first.getByText('配置已套用並保存。').waitFor();
  await openLineup(second);
  const starting = await first.locator('#lineupRows [data-pick="0"]').innerText();
  await first.locator('[data-move="0"][data-step="1"]').press('Enter');
  await first.locator('#lineupApply').press('Enter');
  await first.getByText('配置已套用並保存。').waitFor();
  const changed = await first.locator('#lineupRows [data-pick="0"]').innerText();
  assert.notEqual(changed,starting);
  await second.locator('[data-move="2"][data-step="1"]').press('Enter');
  await second.getByText('另一個分頁已更新名單。', { exact:false }).waitFor();
  await second.locator('#lineupApply').press('Enter');
  await second.getByText('另一個分頁已更新名單。', { exact:false }).waitFor();
  await openLineup(second);
  assert.equal(await second.locator('#lineupRows [data-pick="0"]').innerText(),changed);
  await second.locator('[data-pick="0"]').press('Enter');
  await second.locator('#lineupSearch').waitFor();
  await second.keyboard.press('Escape');
  assert.equal(await second.evaluate(()=>document.activeElement.dataset.pick),'0');
  await assertFits(second);
  await first.close();
  await second.close();
}

async function substitutionPersistence(browser) {
  const context=await browser.newContext({viewport:{width,height:900},hasTouch:width<500});
  try {
    const first=await context.newPage();
    await openLineup(first);
    await first.locator('#lineupApply').press('Enter');
    await first.getByText('配置已套用並保存。').waitFor();
    const key='cpbl-lineup-2026-v1:'+await first.locator('#lineupTeam').inputValue();
    const saved=await first.evaluate(key=>localStorage.getItem(key),key);
    for(const mode of ['team','general']){
      let tab=await context.newPage();
      await tab.addInitScript(()=>{
        const set=Storage.prototype.setItem;
        Storage.prototype.setItem=function(key,value){
          if(String(key).startsWith('cpbl-lineup-'))throw new DOMException('Test denied write','QuotaExceededError');
          return set.call(this,key,value);
        };
      });
      await openLineup(tab);
      if(mode==='general'){
        await tab.locator('[data-entry=general]').click();
        await tab.locator('[data-view=defense]').click();
        const select=tab.locator('#myPitcher'),original=await select.inputValue();
        const alternative=await select.locator('option').evaluateAll((options,id)=>options.find(option=>option.value!==id).value,original);
        await select.selectOption(alternative);
        assert.equal(await select.locator(`option[value="${original}"]`).isDisabled(),false);
        await select.selectOption(original);
      }
      await tab.locator('.feature-nav [data-page=lineup]').click();
      await tab.getByRole('button',{name:'設定換人',exact:true}).press('Enter');
      assert.equal(await tab.locator('#lineupChangeTab').getAttribute('aria-pressed'),'true');
      await assertFits(tab);
      await tab.locator('#lineupChangeKind').selectOption('pen');
      const out=await tab.locator('#lineupChangeOut').inputValue();
      const incoming=await tab.locator('#lineupChangeIn option').nth(1).getAttribute('value');
      const record=async()=>{
        await tab.locator('#lineupChangeIn').selectOption(incoming);
        assert.equal(await tab.locator('#lineupRecord').isDisabled(),true);
        await tab.getByRole('checkbox',{name:/最低投球義務/}).press('Space');
        await tab.getByRole('button',{name:'記錄換人',exact:true}).press('Enter');
        await tab.locator('#lineupChangeStatus').getByText(/已退場/).waitFor();
      };
      await record();
      await assertFits(tab);
      assert.equal(await tab.locator('#lineupChangeIn option').evaluateAll((opts,id)=>opts.some(option=>option.value===id),out),false);
      await tab.locator('#lineupUndoChange').click();
      await tab.locator('#lineupChangeStatus').getByText(/已復原/).waitFor();
      assert.equal(await tab.locator('#lineupChangeOut').inputValue(),out);
      await record();
      await tab.locator('#lineupChanges [data-page=evaluation]').click();
      await tab.locator('[data-view=defense]').click();
      assert.equal(await tab.locator('#myPitcher').inputValue(),incoming);
      assert.equal(await tab.locator('#pitchCount').inputValue(),'0');
      await tab.locator('#evalBtn:enabled').click();
      await tab.locator('#resultBody .evaluation-table').waitFor();
      assert.equal(await tab.locator('#resultBody [data-apply-sub], #confirmChangeEligibility').count(),0);
      await tab.close();

      tab=await context.newPage();
      await openLineup(tab);
      await tab.locator('#lineupChangeTab').click();
      await tab.locator('#lineupChangeKind').selectOption('pen');
      assert.equal(await tab.locator('#lineupChangeOut').inputValue(),out);
      assert.equal(await tab.locator('#lineupChangeHistory li').count(),0);
      await tab.close();
    }
    await first.locator('#lineupChangeTab').click();
    await first.locator('#lineupChangeKind').selectOption('pen');
    const available=await first.locator('#lineupChangeIn option').nth(1).getAttribute('value');
    await first.locator('#lineupSetupTab').click();
    await first.locator('.lineup-unavailable summary').click();
    await first.locator(`[data-lineup-unavailable="${available}"]`).check();
    await first.locator('#lineupChangeTab').click();
    await first.locator('#lineupChangeSource').getByText(/先發草稿尚未套用/).waitFor();
    assert.equal(await first.locator(`#lineupChangeIn option[value="${available}"]`).count(),1);
    await first.locator('#lineupSetupTab').click();
    await first.locator('#lineupApply').click();
    await first.locator('#lineupChangeTab').click();
    assert.equal(await first.locator(`#lineupChangeIn option[value="${available}"]`).count(),0);
    assert.equal(await first.evaluate(key=>localStorage.getItem(key),key),saved);
    console.log('Passed tab-local substitutions, undo, denied writes, and reopening both modes');
  } finally {await context.close();}
}

async function historical(page) {
  await page.goto(base);
  await page.locator("#evalBtn:enabled").waitFor();
  await page.getByRole("button", {name:"單日分析",exact:true}).press("Enter");
  await page.waitForFunction(()=>document.querySelector('#historyPlayer').value!=='');
  await page.locator('.history-background > summary').click();
  await page.locator('#prefsPanel summary').click();
  await page.locator('#historyPitchCount').fill('63');
  await page.locator('#presetSave').click();
  await page.locator('#presetStatus').getByText('歷史情境已保存。').waitFor();
  await page.locator('#presetClear').click();
  assert.equal(await page.locator('#historyPitchCount').inputValue(),'0');
  await page.locator('#presetLoad').click();
  await page.locator('#presetStatus').getByText('已載入歷史情境。').waitFor();
  assert.equal(await page.locator('#historyPitchCount').inputValue(),'63');
  await page.getByRole("button", {name:"逐打席回放",exact:true}).press("Enter");
  await page.getByRole("heading", {name:"先選一個打席"}).waitFor();
  assert.equal(await page.locator("#customEmptyGuide").isVisible(),false);
  await page.goto(replay);
  const result = page.locator('#resultBody[data-replay-decision=pen]');
  await result.waitFor();
  assert.equal(await result.getAttribute('data-replay-pa'),'2026-251-a000');
  assert.equal(await result.locator('[data-reveal-action]').getAttribute('open'),null);
  await page.locator('#replayNext').press('Enter');
  await page.locator('#resultBody[data-replay-pa="2026-251-a001"]').waitFor();
  assert.equal(await page.evaluate(()=>document.activeElement.id),'replayNext');
  await page.locator('#replayShare').press('Enter');
  await page.waitForFunction(()=>document.querySelector('#replayShareStatus').textContent.length>0);
  await page.goBack();
  await page.locator('#resultBody[data-replay-pa="2026-251-a000"]').waitFor();
  const archived=new URL(base);
  archived.search=new URLSearchParams({replay:'2026-03-29',game:'2026-003',pa:'2026-003-h007',decision:'ph'});
  await page.goto(archived.href);
  await page.locator('#resultBody[data-replay-pa="2026-003-h007"]').waitFor();
  assert.equal(await page.evaluate(()=>S.last.candidates.filter(row=>
    row['守備說明'].startsWith('需由 ')&&row['守備說明'].includes('板凳已無備用捕手')).length),3);
}

async function lineupAcrossRosterReload(browser) {
  const context=await browser.newContext({viewport:{width,height:900}});
  try {
    const page=await context.newPage();
    await openLineup(page);
    const teamSelect=page.locator('#lineupTeam');
    const next=await teamSelect.locator('option').evaluateAll(options=>options.find(option=>!option.selected).value);
    await teamSelect.selectOption(next);
    await page.locator('#lineupApply:enabled').waitFor();
    await page.evaluate(club=>{
      const original=team;
      globalThis.failLineupRoster=true;
      team=(name)=>name===club&&globalThis.failLineupRoster
        ?Promise.reject(Error('Test lineup roster load failed')):original(name);
    },next);
    await page.locator('#lineupApply').click();
    await page.getByText('配置已套用並保存。').waitFor();
    const expected=await page.evaluate(club=>LineupBoard.current(club).pitcher,next);
    await page.locator('.feature-nav [data-page=evaluation]').click();
    await page.locator('#formError').getByText('名單載入失敗，請重試。').waitFor();
    assert.equal(await page.locator('#evalBtn').isDisabled(),true);
    await page.evaluate(()=>{globalThis.failLineupRoster=false;});
    await page.locator('#formError .retry').click();
    await page.locator('#evalBtn:enabled').waitFor();
    await page.locator('[data-view=defense]').click();
    assert.equal(await page.locator('#myTeam').inputValue(),next);
    assert.equal(await page.locator('#myPitcher').inputValue(),expected);
    assert.equal(await page.locator('#pitchCount').inputValue(),'0');
    assert.equal(await page.locator('#pitchCount').isEditable(),true);
    await page.locator('#evalBtn').click();
    await page.locator('#resultBody .scoreboard').waitFor();
    console.log('Passed cross-club lineup application and roster retry without losing the pitcher reset');
  } finally {await context.close();}
}

async function pinchHitFielding(browser) {
  const context=await browser.newContext({viewport:{width,height:900}});
  try {
    const page=await context.newPage();
    await openLineup(page);
    const club=await page.locator('#lineupTeam').inputValue();
    const key='cpbl-lineup-2026-v1:'+club;
    await page.locator('#lineupApply').click();
    await page.getByText('配置已套用並保存。').waitFor();
    await page.locator('.feature-nav [data-page=evaluation]').click();
    const catcher=await page.evaluate(club=>LineupBoard.current(club).slots.find(slot=>slot.pos==='C').name,club);
    await page.locator('#dueBatter').selectOption(catcher);
    await page.locator('#benchAll').click();
    await page.locator('#evalBtn:enabled').click();
    await page.locator('#resultBody .evaluation-table').waitFor();
    const candidate=await page.evaluate(()=>S.last.candidates.find(row=>row.fielding_action==='replacement')?.['球員']);
    assert.ok(candidate,'confirmed catcher-replacement case');
    const toggle=page.locator('[data-rows-toggle=ph]');
    if(await toggle.isVisible())await toggle.click();
    const preview=page.locator(`[data-batter="${candidate}"] .pinch-hit-preview`);
    await preview.locator('summary').click();
    await preview.getByText(/承接原棒次/).waitFor();
    assert.equal(await preview.locator('button').count(),0);
    await page.locator('.feature-nav [data-page=lineup]').click();
    await page.locator('#lineupChangeTab').click();
    await page.locator('#lineupChangeKind').selectOption('ph');
    await page.locator('#lineupChangeOut').selectOption(catcher);
    await page.locator('#lineupChangeIn').selectOption(candidate);
    await page.locator('#lineupChangeConfirm').check();
    await page.locator('#lineupRecord').click();
    await page.locator('#lineupChangeStatus').getByText(/承接第/).waitFor();
    const saved=await page.evaluate(club=>LineupBoard.current(club),club);
    assert.equal(saved.slots.find(slot=>slot.pos==='C').name,candidate);
    assert.equal(saved.slots.find(slot=>slot.pos==='C').fieldingPending,true);
    assert.deepEqual(saved.unavailable,[catcher]);
    await page.locator('#lineupSetupTab').click();
    await page.locator('#lineupWarnings').getByText(/請確認接守：捕手/).waitFor();
    const catcherIndex=saved.slots.findIndex(slot=>slot.pos==='C');
    await page.locator('.lineup-unavailable summary').click();
    assert.equal(await page.locator(`[data-lineup-unavailable="${catcher}"]`).isDisabled(),true);
    await page.locator(`[data-position="${catcherIndex}"]`).selectOption('DH');
    await page.locator('#lineupWarnings').getByText(/請確認接守：捕手/).waitFor();
    assert.doesNotMatch(await page.locator('#lineupWarnings').textContent(),/請確認接守：指定打擊/);
    await page.locator('#lineupBackup summary').click();
    const downloading=page.waitForEvent('download');
    await page.locator('#lineupExport').click();
    const backup=await (await downloading).path();
    await page.locator(`[data-position="${catcherIndex}"]`).selectOption('C');
    await page.locator('#lineupImport').setInputFiles(backup);
    await page.locator('#lineupMessage').getByText(/已更新本場名單/).waitFor();
    assert.equal(await page.locator(`[data-position="${catcherIndex}"]`).inputValue(),'DH');
    assert.deepEqual(await page.evaluate(club=>LineupBoard.current(club),club),saved);
    await page.locator('#lineupApply').getByText('確認接守並套用').waitFor();
    await page.locator('#lineupApply').click();
    await page.getByText(/已更新本場名單/).waitFor();
    const confirmed=await page.evaluate(club=>LineupBoard.current(club),club);
    assert.equal(confirmed.slots[catcherIndex].pos,'DH');
    assert.deepEqual(confirmed.retired,[catcher]);
    assert.equal(confirmed.slots.find(slot=>slot.pos==='C').fieldingPending,undefined);
    const persisted=await page.evaluate(key=>JSON.parse(localStorage.getItem(key)).confirmed,key);
    assert.equal(persisted.slots.find(slot=>slot.pos==='C').name,catcher);
    console.log('Passed team pinch-hitter, positional confirmation, backup restore and manual apply');
  } finally {await context.close();}
}

async function main() {
  const engine = { chromium, webkit }[name];
  assert.ok(engine,`Unsupported browser: ${name}`);
  const browser = await engine.launch(process.env.BASEBALL_QA_EXECUTABLE
    ? {executablePath:process.env.BASEBALL_QA_EXECUTABLE} : {});
  try {
    const context = await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce',
      isMobile:width<500,hasTouch:width<500});
    const page = await context.newPage(),errors=[];
    context.on('page',opened=>opened.on('pageerror',e=>errors.push(e.message)));
    page.on('pageerror',e=>errors.push(e.message));
    await evaluation(page);
    await lineup(context);
    await substitutionPersistence(browser);
    await lineupAcrossRosterReload(browser);
    await pinchHitFielding(browser);
    await historical(page);
    assert.deepEqual(errors,[]);
    await assertFits(page);
    console.log(JSON.stringify({base,browser:name,viewport:width,evaluation:true,lineup:true,history:true}));
  } finally {
    await browser.close();
  }
}

main().catch(error=>{console.error(error);process.exitCode=1;});
