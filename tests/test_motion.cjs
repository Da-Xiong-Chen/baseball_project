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
function element(){return {classList:classes(),offsetWidth:1,scrollTop:5,focus(){this.focused=true;},addEventListener(){}};}

test('swipe needs a clear, quick horizontal movement',()=>{
  const {M}=load();
  assert.equal(M.swipeDirection(-120,0,200),'left');
  assert.equal(M.swipeDirection(120,10,300),'right');
  assert.equal(M.swipeDirection(-40,0,200),null);        // 太短
  assert.equal(M.swipeDirection(-100,60,200),null);      // 太斜
  assert.equal(M.swipeDirection(-120,0,900),null);       // 太慢
});
test('slide-in direction follows navigation order and is skipped with reduced motion',()=>{
  let {M}=load();const a=element();
  M.slideIn(a,1);assert.equal(a.classList.contains('slide-from-right'),true);
  M.slideIn(a,-1);assert.equal(a.classList.contains('slide-from-left'),true);assert.equal(a.classList.contains('slide-from-right'),false);
  ({M}=load({reduce:true}));const b=element();M.slideIn(b,1);assert.deepEqual(b.classList.list,[]);
});
test('result drawer opens only on narrow screens and closes through history back',()=>{
  const wide=load({narrow:false});wide.M.setupDrawer({element:element()});assert.equal(wide.M.openDrawer(),false);
  const {M,context}=load({reduce:true});const el=element();let closed=0;
  M.setupDrawer({element:el,onClose:()=>closed++});
  assert.equal(M.openDrawer(),true);assert.equal(M.drawerOpen(),true);assert.equal(el.scrollTop,0);assert.equal(el.focused,true);
  assert.equal(context.document.body.classList.contains('result-drawer'),true);assert.equal(context.history.state.resultDrawer,true);
  M.closeDrawer();
  assert.equal(M.drawerOpen(),false);assert.equal(closed,1);assert.equal(context.document.body.classList.contains('result-drawer'),false);assert.equal(context.history.state,null);
});
