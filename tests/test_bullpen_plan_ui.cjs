const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
test('closing and reopening a capacity draft preserves rows, while a changed roster reloads',()=>{
 const events={},nodes=new Map();let rowWrites=0,key='team-A';
 const q=s=>{if(!nodes.has(s)){let content='';nodes.set(s,{value:'',textContent:'',get innerHTML(){return content;},set innerHTML(x){content=x;if(s==='[data-rows]')rowWrites++;}});}return nodes.get(s);};
 const el={open:false,innerHTML:'',querySelector:q,addEventListener:(name,fn)=>events[name]=fn};
 const context={window:{}};vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../docs/bullpen-plan-ui.js'),'utf8'),context);
 context.window.BullpenPlanUI.mount({element:el,label:s=>s,snapshot:()=>({key,pitchers:[{id:'A'}]})});
 el.open=true;events.toggle();assert.equal(rowWrites,1);
 q('[data-target]').value='7';el.open=false;events.toggle();el.open=true;events.toggle();
 assert.equal(rowWrites,1);assert.equal(q('[data-target]').value,'7');
 key='team-B';el.open=false;events.toggle();el.open=true;events.toggle();assert.equal(rowWrites,2);
 q('[data-refresh]').onclick();assert.equal(rowWrites,3);
});
