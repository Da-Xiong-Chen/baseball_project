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
  assert.match(await result.locator('.sb-team').last().innerText(),new RegExp(await team.inputValue()));
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

async function historical(page) {
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
    await historical(page);
    assert.deepEqual(errors,[]);
    await assertFits(page);
    console.log(JSON.stringify({base,browser:name,viewport:width,evaluation:true,lineup:true,history:true}));
  } finally {
    await browser.close();
  }
}

main().catch(error=>{console.error(error);process.exitCode=1;});
