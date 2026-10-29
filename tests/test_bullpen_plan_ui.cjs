const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
test('closing and reopening a capacity draft preserves rows, while a changed roster reloads',()=>{
 const events={},nodes=new Map();let rowWrites=0,key='team-A';
 const q=s=>{if(!nodes.has(s)){let content='';nodes.set(s,{value:'',textContent:'',get innerHTML(){return content;},set innerHTML(x){content=x;if(s==='[data-rows]')rowWrites++;}});}return nodes.get(s);};
 const el={open:false,innerHTML:'',querySelector:q,querySelectorAll:()=>[],addEventListener:(name,fn)=>events[name]=fn};
 const context={window:{}};vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../docs/bullpen-plan-ui.js'),'utf8'),context);
 context.window.BullpenPlanUI.mount({element:el,label:s=>s,snapshot:()=>({key,pitchers:[{id:'A'}]})});
 el.open=true;events.toggle();assert.equal(rowWrites,1);
 q('[data-target]').value='7';el.open=false;events.toggle();el.open=true;events.toggle();
 assert.equal(rowWrites,1);assert.equal(q('[data-target]').value,'7');
 key='team-B';el.open=false;events.toggle();el.open=true;events.toggle();assert.equal(rowWrites,2);
 q('[data-refresh]').onclick();assert.equal(rowWrites,3);
});

function worksheet(pitchers=[{id:'A'},{id:'B'}]){
 const events={},nodes=new Map();let focused=null,key='A';
 const field=(value='')=>({value,attrs:{},textContent:'',innerHTML:'',checkValidity:()=>true,setAttribute(k,v){this.attrs[k]=v},removeAttribute(k){delete this.attrs[k]},focus(){focused=this}});
 const q=s=>{if(!nodes.has(s))nodes.set(s,field());return nodes.get(s)};
 const rows=['A','B'].map(id=>{const fields={'[data-status]':field('available'),'[data-capacity]':field(''),'[data-order]':field('')};return {id,fields,querySelector:s=>fields[s]}});
 const el={open:true,innerHTML:'',querySelector:s=>s==='[data-order]'?rows[0].fields[s]:q(s),querySelectorAll:s=>s==='[data-arm]'?rows:s==='[aria-invalid]'?[...nodes.values(),...rows.flatMap(r=>Object.values(r.fields))].filter(f=>f.attrs['aria-invalid']):[],addEventListener:(n,f)=>events[n]=f};
 const context={window:{},BullpenPlan:require('../docs/bullpen-plan.js')};vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../docs/bullpen-plan-ui.js'),'utf8'),context);
 context.window.BullpenPlanUI.mount({element:el,label:s=>'投手'+s,snapshot:()=>({key,pitchers})});
 events.toggle();q('[data-target]').value='7';
 return {q,rows,events,el,focus:()=>focused,setKey:v=>key=v,run:()=>q('[data-calculate]').onclick()};
}
test('capacity errors identify and focus the exact target, capacity, status and order field',()=>{
 const w=worksheet(),a=w.rows[0].fields,b=w.rows[1].fields;
 w.q('[data-target]').value='1.5';w.run();assert.equal(w.focus(),w.q('[data-target]'));assert.equal(w.focus().attrs['aria-invalid'],'true');
 w.q('[data-target]').value='7';w.run();assert.equal(w.focus(),a['[data-order]']);
 a['[data-order]'].value='1';w.run();assert.equal(w.focus(),a['[data-capacity]']);assert.match(w.q('[data-output]').textContent,/投手A/);
 a['[data-capacity]'].value='3';a['[data-status]'].value='retired';w.run();assert.equal(w.focus(),a['[data-status]']);
 a['[data-status]'].value='available';b['[data-capacity]'].value='5';b['[data-order]'].value='1';w.run();assert.equal(w.focus(),b['[data-order]']);assert.match(w.q('[data-output]').textContent,/順位不可重複/);
 b['[data-order]'].value='2';w.run();assert.match(w.q('[data-output]').innerHTML,/容量足夠/);assert.equal(a['[data-capacity]'].attrs['aria-invalid'],undefined);
});
test('editing a successful or shortage result invalidates it with a concise recalculation prompt',()=>{
 for(const target of ['7','9']){const w=worksheet();w.q('[data-target]').value=target;w.rows.forEach((r,i)=>{r.fields['[data-order]'].value=String(i+1);r.fields['[data-capacity]'].value=i?'5':'3'});w.run();assert.match(w.q('[data-output]').innerHTML,target==='7'?/容量足夠/:/尚缺 1/);w.events.input({target:w.q('[data-target]')});assert.match(w.q('[data-output]').textContent,/重新檢查/);w.events.change({target:w.q('[data-target]')});assert.match(w.q('[data-output]').textContent,/重新檢查/);}
});
test('a changed roster cannot reuse the previous capacity result',()=>{
 const w=worksheet();w.setKey('B');w.run();assert.match(w.q('[data-output]').textContent,/重新帶入/);
});

test('an empty bullpen disables calculation and explains how to continue',()=>{
 const w=worksheet([]);assert.equal(w.q('[data-calculate]').disabled,true);assert.match(w.q('[data-rows]').innerHTML,/先選取牛棚/);
});
