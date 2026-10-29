const test=require('node:test'),assert=require('node:assert/strict');
const P=require('../docs/players.js');
const roster={hitters:[{name:'rebas:CPBL:a',display_name:'新名',aliases:['舊名','同名']},{name:'rebas:CPBL:b',display_name:'另一人',aliases:['同名']}],pitchers:[{name:'rebas:CPBL:p',display_name:'投手',aliases:['投手']} ]};
test('values stay distinct; legacy ambiguous names are never guessed',()=>{
  P.setRegistry({'rebas:CPBL:a':'新名','rebas:CPBL:b':'另一人'});
  assert.equal(P.resolve('舊名',roster.hitters),'rebas:CPBL:a');
  assert.equal(P.resolve('同名',roster.hitters),null);
  assert.equal(P.resolve('rebas:CPBL:b',roster.hitters),'rebas:CPBL:b');
});
test('historical context never falls through to a later name',()=>{
  P.setContext({'rebas:CPBL:a':'舊名'});
  assert.equal(P.name('rebas:CPBL:a'),'舊名');
  assert.equal(P.name('rebas:CPBL:b'),'未有姓名紀錄的球員');
  assert.equal(P.currentName('rebas:CPBL:a'),'新名');P.setContext(null);
});
test('lineup migration preserves unresolved entries for review and does not mutate input',()=>{
  const config={pitcher:'投手',slots:[{name:'舊名',pos:'DH'},{name:'同名',pos:'C'}]};
  const before=JSON.stringify(config),result=P.migrateLineup(config,roster);
  assert.equal(JSON.stringify(config),before);
  assert.equal(result.value.pitcher,'rebas:CPBL:p');
  assert.equal(result.value.slots[0].name,'rebas:CPBL:a');
  assert.deepEqual(result.unresolved,['同名']);
});
test('evaluation migration resolves every name-bearing request field',()=>{
  const config={due:'舊名',pitcher:'投手',bench:['另一人'],next_batters:['舊名'],pen:['投手'],streaks:{投手:1},lineup_positions:{舊名:'DH'}};
  const result=P.migrateEvaluation(config,roster,roster);
  assert.deepEqual(result.unresolved,[]);assert.equal(result.value.due,'rebas:CPBL:a');
  assert.equal(result.value.streaks['rebas:CPBL:p'],1);assert.equal(result.value.lineup_positions['rebas:CPBL:a'],'DH');
});
