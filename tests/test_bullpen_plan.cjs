const {test}=require('node:test'),assert=require('node:assert/strict');
const {plan}=require('../docs/bullpen-plan.js');
const p=(id,remaining,available=true,retired=false)=>({id,remaining,available,retired});
test('capacity is conserved and used arms leave reserves',()=>{
 const r=plan({target:7,pitchers:[p('A',3),p('B',5),p('C',null)],order:['A','B']});
 assert.equal(r.covered,7);assert.equal(r.uncovered,0);assert.deepEqual(r.allocations.map(x=>[x.assigned,x.remaining]),[[3,0],[4,1]]);assert.deepEqual(r.reserve,[{id:'C',remaining:null}]);
});
test('reordering changes remaining arms; shortage remains visible',()=>{
 const r=plan({target:9,pitchers:[p('A',3),p('B',5)],order:['B','A']});assert.equal(r.uncovered,1);assert.equal(r.complete,false);assert.equal(r.allocations[0].id,'B');
});
test('unknown capacity is never treated as unlimited or zero',()=>{
 assert.throws(()=>plan({target:1,pitchers:[p('A',null)],order:['A']}),/容量/);
});
test('retired, unavailable, duplicate and foreign arms cannot enter',()=>{
 for(const x of [p('A',3,false),p('A',3,true,true)])assert.throws(()=>plan({target:2,pitchers:[x],order:['A']}));
 assert.throws(()=>plan({target:2,pitchers:[p('A',3)],order:['A','A']}));
 assert.throws(()=>plan({target:2,pitchers:[p('A',3)],order:['B']}));
 assert.throws(()=>plan({target:2,pitchers:[p('A',3),p('A',3)],order:[]}));
});
test('invalid numeric input rejected; zero capacity and empty plans remain defined',()=>{
 for(const n of [NaN,Infinity,-1,1.2,1001,'3'])assert.throws(()=>plan({target:n,pitchers:[],order:[]}));
 assert.equal(plan({target:0,pitchers:[],order:[]}).complete,true);
 assert.equal(plan({target:3,pitchers:[p('A',0)],order:['A']}).uncovered,3);
});
