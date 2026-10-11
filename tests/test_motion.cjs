const {test}=require('node:test');const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');const vm=require('node:vm');

function load({reduce=false,narrow=true}={}){
  const listeners={};
  const context={console,setTimeout,
    matchMedia:q=>({matches:q.includes('reduced-motion')?reduce:q.includes('max-width')?narrow:false,addEventListener(){}}),
    getComputedStyle:()=>({overflowX:'visible'}),
    history:{state:null,pushState(s){this.state=s;},back(){this.state=null;listeners.popstate?.();}},
    addEventListener:(t,fn)=>{listeners[t]=fn;},
    document:{documentElement:{dataset:{}},body:{classList:classes()},querySelectorAll:()=>[],addEventListener:(t,fn)=>{listeners['doc:'+t]=fn;}}};
  context.window=context;
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../docs/motion.js'),'utf8'),context);
  return {M:context.Motion,context,listeners};
}
function classes(){const s=new Set();return {add:c=>s.add(c),remove:(...c)=>c.forEach(x=>s.delete(x)),contains:c=>s.has(c),get list(){return [...s];}};}

test('swipe needs a clear, quick horizontal movement',()=>{
  const {M}=load();
  assert.equal(M.swipeDirection(-120,0,200),'left');
  assert.equal(M.swipeDirection(120,10,300),'right');
  assert.equal(M.swipeDirection(-40,0,200),null);        // 太短
  assert.equal(M.swipeDirection(-100,60,200),null);      // 太斜
  assert.equal(M.swipeDirection(-120,0,900),null);       // 太慢
});
test('no slide-in or drawer animation is exposed',()=>{
  const {M}=load();assert.equal(M.slideIn,undefined);assert.equal(M.openDrawer,undefined);
});
