// Test static delivery/date boundary independently of the Python comparator.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');

async function moduleFor(fetch, signal=AbortSignal) {
  const context = {window:{}, fetch, AbortSignal:signal};
  vm.runInNewContext(await fs.readFile(path.join(root,'docs/pitch-change.js'),'utf8'), context);
  return context.window.PitchChange;
}
const fileFetch = async url => ({ok:true, json:async()=>JSON.parse(await fs.readFile(path.join(root,'docs',url),'utf8'))});

test('pitch card reads snapshots without AbortSignal.timeout',async()=>{
  const api=await moduleFor(fileFetch,{});
  const result=await api.staticResult({pitcher:'鋼龍',season:2025,cutoff:'2026-01-01',hand:'ALL'});
  assert.equal(result.pitcher,'鋼龍');
});

test('static selection is strictly before the requested date for every hand', async()=>{
  const api = await moduleFor(fileFetch);
  const index = await fileFetch('data/pitch-change/2025/index.json').then(r=>r.json());
  const pitcher = Object.keys(index.pitchers)[0];
  const data = await fileFetch('data/pitch-change/2025/'+index.pitchers[pitcher]).then(r=>r.json());
  const snap = data.snapshots[Math.floor(data.snapshots.length/2)];
  for (const hand of ['ALL','L','R']) {
    const result = await api.staticResult({pitcher,season:2025,cutoff:snap.effective_from,hand});
    assert.equal(JSON.stringify(result),JSON.stringify(snap.hands[hand]));
    for (const window of Object.values(result.windows)) {
      assert.ok(window.games.every(g=>g.date < result.cutoff));
    }
  }
  // A day with no new appearance must retain the same state and current query cutoff.
  const result = await api.staticResult({pitcher,season:2025,cutoff:'2026-01-01',hand:'ALL'});
  assert.equal(result.cutoff,'2026-01-01');
  assert.equal(result.last_observed,data.snapshots.at(-1).hands.ALL.last_observed);
});

test('failed fetch is retryable instead of permanently cached', async()=>{
  let calls = 0;
  const api = await moduleFor(async url=>{
    if (calls++ === 0) return {ok:false};
    return fileFetch(url);
  });
  const opts = {pitcher:'鋼龍',season:2025,cutoff:'2026-01-01',hand:'ALL'};
  await assert.rejects(()=>api.staticResult(opts));
  assert.equal((await api.staticResult(opts)).pitcher,'鋼龍');
});

test('unknown pitcher produces a clear error without requesting a guessed filename', async()=>{
  const api = await moduleFor(fileFetch);
  await assert.rejects(()=>api.staticResult({pitcher:'不存在',season:2025,cutoff:'2026-01-01',hand:'ALL'}),/沒有配球資料/);
});

test('invalid handedness and impossible dates are rejected', async()=>{
  const api = await moduleFor(fileFetch);
  for (const extra of [{hand:'S'},{cutoff:'2025-02-30'},{cutoff:'oops'}]) {
    await assert.rejects(()=>api.staticResult({pitcher:'鋼龍',season:2025,cutoff:'2026-01-01',hand:'ALL',...extra}));
  }
});
