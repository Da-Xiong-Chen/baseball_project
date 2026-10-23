const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.join(__dirname,'..');
function pitchModule(){
 const c={window:{}};
 const source=fs.readFileSync(path.join(root,'docs/pitch-change.js'),'utf8').replace('return {mount, staticResult};','return {mount, staticResult, render};');
 vm.runInNewContext(source,c);return c.window.PitchChange;
}
function pitchPayload(){
 const index=JSON.parse(fs.readFileSync(path.join(root,'docs/data/pitch-change/2025/index.json'),'utf8'));
 const file=JSON.parse(fs.readFileSync(path.join(root,'docs/data/pitch-change/2025',Object.values(index.pitchers)[0]),'utf8'));
 return structuredClone(file.snapshots.at(-1).hands.ALL);
}
test('pitch percentages retain small changes without signed zero or nonfinite text',()=>{
 const api=pitchModule(),data=pitchPayload();
 data.rows[0].delta_pp=-.006;data.rows[0].adjusted=[.000001,.1];data.rows[0].interval=[-.0001,.0001];
 const html=api.render(data);
 assert.match(html,/減少不到 0\.1 百分點/);assert.match(html,/增加不到 0\.1 百分點/);assert.match(html,/&lt;0\.1%/);
 assert.doesNotMatch(html,/[−-]0\.0(?:\D|$)|\+0\.0(?:\D|$)/);
 for(const value of [null,undefined,NaN,Infinity,-Infinity]){
  data.rows[0].delta_pp=value;data.rows[0].adjusted=[value,value];data.coverage=[value,value];
  assert.doesNotMatch(api.render(data),/NaN|Infinity|undefined/);
 }
});

test('every released pitch snapshot renders without nonfinite numbers or signed zero',()=>{
 const api=pitchModule(),folder=path.join(root,'docs/data/pitch-change/2025');
 const index=JSON.parse(fs.readFileSync(path.join(folder,'index.json'),'utf8'));let snapshots=0,rows=0;
 for(const name of Object.values(index.pitchers)){
  const file=JSON.parse(fs.readFileSync(path.join(folder,name),'utf8'));
  for(const snapshot of file.snapshots)for(const data of Object.values(snapshot.hands)){
   const html=api.render(data);
   assert.doesNotMatch(html,/NaN|Infinity|undefined|[−-]0\.0(?:\D|$)|\+0\.0(?:\D|$)/,name+' '+snapshot.effective_from);
   snapshots++;rows+=data.rows.length;
   const raw=api.render(data,'raw');assert.doesNotMatch(raw,/NaN|Infinity|undefined/);
   assert.match(raw,/未調整球數，不作變化判定|沒有可用配球紀錄/);
  }
 }
 assert.ok(snapshots>9000);assert.equal(rows,39420);
});

test('raw pitch view uses observed proportions and never reuses adjusted intervals or claims',()=>{
 const api=pitchModule(),d=pitchPayload();d.status='insufficient';
 d.rows[0].raw=[.2,.35];d.rows[0].adjusted=[.5,.8];d.rows[0].delta_pp=30;d.rows[0].interval=[20,40];
 const html=api.render(d,'raw');assert.match(html,/\+15\.0 百分點/);assert.match(html,/20\.0%/);assert.match(html,/35\.0%/);
 assert.doesNotMatch(html,/\+30\.0 百分點|\+20\.0 百分點 至 \+40\.0/);
 assert.match(html,/未產生調整後區間或趨勢結論/);
 assert.match(html,/同條件樣本不足，先看觀察配球/);
 d.status='ready';
 assert.doesNotMatch(api.render(d,'raw'),/同條件樣本不足/);
});

test('validation distinguishes absolute MSE difference from relative improvement',async()=>{
 const B=require('../docs/backtest.js'),report=require('../docs/data/model-evaluation.json');
 const el={innerHTML:'',querySelector:()=>({insertAdjacentHTML(){}}),querySelectorAll:()=>[],insertAdjacentHTML(pos,html){this.innerHTML+=html;}};
 await B.validation(el,async()=>report,report.batch_id);
 assert.match(el.innerHTML,/MSE 差值（基準－模型）/);assert.match(el.innerHTML,/誤差減少 <b>0\.18%/);
 assert.match(el.innerHTML,/\+0\.000406/);assert.doesNotMatch(el.innerHTML,/相對基準誤差減少 \+0\.000406/);
});

test('timeline WPA missing and tiny values are not displayed as a measured zero',()=>{
 const B=require('../docs/backtest.js');
 for(const [wpa,expected] of [[null,/攻方 WPA —/],[undefined,/攻方 WPA —/],[-.00000001,/減少不到 0\.001/],[0,/攻方 WPA 0\.000/]]){
  const action={},outcome={},open={},button={dataset:{btPa:'p'},setAttribute(){}};
  const detail={innerHTML:'',querySelector:s=>s==='[data-bt-action]'?action:s==='[data-bt-outcome]'?outcome:open};
  const el={innerHTML:'',querySelector:()=>detail,querySelectorAll:s=>s==='[data-bt-pa]'?[button]:[]};
  B.timeline({element:el,pas:[{pa_id:'p',inning:6,fld_team:'A',bat_team:'B',pitcher:'P',WPA:wpa}],marks:{p:[2,'Q','P']},team:'A',open(){}});
  button.onclick();assert.match(detail.innerHTML,expected);assert.doesNotMatch(detail.innerHTML,/-0\.000/);
 }
});
