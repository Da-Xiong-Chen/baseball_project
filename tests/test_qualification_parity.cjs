const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');const vm=require('node:vm');const {spawnSync}=require('node:child_process');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
function fixture(){return {model_cutoff:'2025-04-01',situation:{pitcher:'P'},
  candidates:[{角色:'現任',球員:'A'},{角色:'代打',球員:'B'}],
  bullpen:{next:['A','B'],rows:[{角色:'場上',投手:'P'},{角色:'牛棚',投手:'Q'}]}};}
const dataset={policy:{mode:'observed-only',min_pa:1,min_outs:0,min_np:1,decision_validated:false},
  cutoffs:{'2025-04-01':{hitters:{A:[1,'2025-03-31'],B:[14,'2025-03-31']},
  pitchers:{P:[0,'2025-03-31',3],Q:[1,'2025-03-31',9]},ambiguous:['Same']}}};
for(const [label,change] of [['nonzero pitches and zero outs',()=>{}],
  ['unknown cutoff fails closed',r=>r.model_cutoff='2025-04-02'],
  ['zero hitter PA blocks comparison',r=>r.candidates[0].球員='New'],
  ['missing pitcher NP blocks comparison',r=>r.situation.pitcher='Missing']]){
  test(`Python and browser eligibility agree: ${label}`,()=>{
    const r=fixture();change(r);
    const c={dataset,result:JSON.parse(JSON.stringify(r))};vm.createContext(c);
    vm.runInContext(fs.readFileSync(path.join(root,'docs/qualification.js'),'utf8')+'\nQualification.configure(dataset);Qualification.annotate(result);',c);
    const py=spawnSync('python',['-c',"import json,sys;sys.path.insert(0,'src');from qualification import annotate;v=json.load(sys.stdin);print(json.dumps(annotate(v['result'],v['dataset']),ensure_ascii=False))"],
      {cwd:root,input:JSON.stringify({result:r,dataset}),encoding:'utf8',env:{...process.env,PYTHONIOENCODING:'utf-8'}});
    assert.equal(py.status,0,py.stderr);
    assert.deepEqual(JSON.parse(JSON.stringify(c.result)),JSON.parse(py.stdout));
    if(label==='nonzero pitches and zero outs'){
      assert.ok(c.result.bullpen.rows[0]['可列入排名']);
      assert.equal(c.result.bullpen.rows[0]['個人投球數'],3);
      assert.equal(c.result.candidates[0]['推薦已驗證'],false);
    }
  });
}
