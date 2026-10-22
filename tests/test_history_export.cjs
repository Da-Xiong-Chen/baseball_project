const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const root=path.join(process.env.BASEBALL_STATIC_OUT||path.join(__dirname,'../docs/data'),'replay'),day='2025-09-20',dir=path.join(root,'day-'+day);
const index=JSON.parse(fs.readFileSync(path.join(dir,'index.json'),'utf8'));
test('fixed day exports every PA once and hashes every lazy-loaded file',()=>{
 let count=0,changed=0;
 for(const [game,ids] of Object.entries(index.games)){
  const pas=JSON.parse(fs.readFileSync(path.join(root,game+'.json'),'utf8')).pas;
  assert.deepEqual(new Set(ids),new Set(pas.map(p=>p.pa_id)));
  const prev={};
  for(const pa of pas){
   const raw=fs.readFileSync(path.join(dir,index.files[pa.pa_id]));assert.equal(crypto.createHash('sha256').update(raw).digest('hex'),index.sha256[pa.pa_id]);
   const bundle=JSON.parse(raw),old=prev[pa.fld_team]||pa.pitcher;prev[pa.fld_team]=pa.pitcher;
   assert.equal(bundle.pa_id,pa.pa_id);assert.equal(bundle.date,day);
   assert.equal(bundle.ph.situation.pitcher,pa.pitcher);
   assert.equal(bundle.ph.replay_context.incumbent_pitcher,old);
   assert.equal(!!bundle.pen,old!==pa.pitcher);
   if(bundle.pen){changed++;assert.equal(bundle.pen.situation.pitcher,old);assert.equal(bundle.pen.actual.pitcher,pa.pitcher);}
   for(const r of [bundle.ph,bundle.pen].filter(Boolean)){
    assert.ok(r.ml_cutoff<=r.model_cutoff&&r.model_cutoff<=day);
    assert.equal(r.schema_version,2);assert.ok(r.details);
    for(const p of r.bullpen.rows){const total=p.對決明細.reduce((s,d)=>s+d.runs+d.fatigue,0);assert.ok(Math.abs(total-p.預估失分)<.00002);}
   }
   count++;
  }
 }
 assert.equal(count,226);assert.equal(changed,19);assert.equal(index.pa_count,count);assert.equal(index.pitcher_changes,changed);
});
test('a fixed day file is fetched on demand rather than preloading all decisions',()=>{
 const app=fs.readFileSync(path.join(__dirname,'../docs/app.js'),'utf8');
 assert.match(app,/day-\$\{HISTORY_DATE\}\/\$\{index.files\[pa\]\}/);
 assert.doesNotMatch(app,/Promise\.all\(Object\.values\(index.files\)/);
});
