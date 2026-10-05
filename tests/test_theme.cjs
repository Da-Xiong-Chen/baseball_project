const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function page(saved,deny=false) {
  const buttons=['dark','light'].map(theme=>({dataset:{setTheme:theme},pressed:null,on:false,
    setAttribute(k,v){this.pressed=v;},classList:{toggle(k,v){buttons.find(b=>b.dataset.setTheme===theme).on=v;}},
    addEventListener(k,fn){this.click=fn;}}));
  let ready,stored=saved;
  const label={textContent:''},icon={setAttribute(k,v){this.href=v;}};
  const toggle={attributes:{},setAttribute(k,v){this.attributes[k]=v;},querySelector:s=>s==='span'?label:icon,addEventListener(k,fn){this.click=fn;}};
  const doc={documentElement:{dataset:{},style:{}},querySelectorAll:s=>s==='[data-theme-toggle]'?[toggle]:buttons,addEventListener:(k,fn)=>ready=fn};
  const localStorage={getItem(){if(deny)throw Error('blocked');return stored;},setItem(k,v){if(deny)throw Error('blocked');stored=v;}};
  vm.runInNewContext(fs.readFileSync('docs/theme.js','utf8'),{document:doc,localStorage});
  ready();return {doc,buttons,toggle,label,icon,saved:()=>stored};
}
test('dark default and selected state exist before application initialization',()=>{
  const p=page(null);assert.equal(p.doc.documentElement.dataset.theme,'dark');assert.equal(p.buttons[0].pressed,'true');
});
test('light preference survives reopening and controls update accessibly',()=>{
  const p=page('dark');p.buttons[1].click();assert.equal(p.saved(),'light');assert.equal(p.buttons[1].pressed,'true');
  assert.equal(p.buttons[0].pressed,'false');assert.equal(page(p.saved()).doc.documentElement.style.colorScheme,'light');
});
test('storage refusal and corrupted preference never prevent switching',()=>{
  for(const p of [page('garbage'),page('light',true)]){assert.equal(p.doc.documentElement.dataset.theme,'dark');p.buttons[1].click();assert.equal(p.doc.documentElement.dataset.theme,'light');}
});

test('one theme button toggles both ways and announces its next action',()=>{
  const p=page(null);assert.equal(p.label.textContent,'淺色');p.toggle.click();
  assert.equal(p.doc.documentElement.dataset.theme,'light');assert.equal(p.toggle.attributes['aria-label'],'切換為深色主題');
  assert.equal(p.icon.href,'#theme-moon');p.toggle.click();assert.equal(p.saved(),'dark');assert.equal(p.label.textContent,'淺色');
});
