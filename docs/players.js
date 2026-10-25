/* Player IDs are values; dated names are presentation. No model calculations. */
(function(root){
  'use strict';
  const prefix='rebas:CPBL:';
  let current=Object.create(null),context=null;
  const rosters=new Map();
  const isId=value=>typeof value==='string'&&value.startsWith(prefix);
  function setRegistry(map){current=Object.assign(Object.create(null),map||{});}
  function setContext(map){context=map?Object.assign(Object.create(null),map):null;}
  function currentName(id){return isId(id)?current[id]||'未有姓名紀錄的球員':String(id??'');}
  function name(id){return isId(id)?(context?context[id]:current[id])||'未有姓名紀錄的球員':String(id??'');}
  function text(value){return String(value??'').replace(/rebas:CPBL:[A-Za-z0-9]+/g,id=>name(id));}
  function registerRoster(team,roster){
    rosters.set(team,roster);
    for(const p of [...roster.hitters,...roster.pitchers])if(p.display_name)current[p.name]=p.display_name;
  }
  function resolve(value,pool){
    if(value==='')return '';
    if(typeof value!=='string')return null;
    if(pool.some(p=>p.name===value))return value;
    if(isId(value))return null;
    const matches=[...new Set(pool.filter(p=>p.display_name===value||p.aliases?.includes(value)||current[p.name]===value).map(p=>p.name))];
    return matches.length===1?matches[0]:null;
  }
  function migrateLineup(config,roster){
    if(!config)return {value:null,unresolved:[],changed:false};
    const value=JSON.parse(JSON.stringify(config)),unresolved=[];let changed=false;
    function convert(old,pool){const id=resolve(old,pool);if(id===null){unresolved.push(old);return old;}if(id!==old)changed=true;return id;}
    value.pitcher=convert(value.pitcher,roster.pitchers);
    value.slots.forEach(slot=>slot.name=convert(slot.name,roster.hitters));
    if(value.unavailable)value.unavailable=[...new Set(value.unavailable.map(n=>convert(n,[...roster.hitters,...roster.pitchers])))];
    return {value,unresolved:[...new Set(unresolved)],changed};
  }
  function migrateEvaluation(config,bat,fld){
    const value=JSON.parse(JSON.stringify(config)),unresolved=[];
    const convert=(old,pool)=>{const id=resolve(old,pool);if(id===null){unresolved.push(old);return old;}return id;};
    value.due=convert(value.due,bat.hitters);value.pitcher=convert(value.pitcher,fld.pitchers);
    for(const field of ['bench','next_batters'])if(value[field])value[field]=value[field].map(n=>convert(n,bat.hitters));
    if(value.pen)value.pen=value.pen.map(n=>convert(n,fld.pitchers));
    if(value.streaks)value.streaks=Object.fromEntries(Object.entries(value.streaks).map(([n,v])=>[convert(n,fld.pitchers),v]));
    if(value.lineup_positions)value.lineup_positions=Object.fromEntries(Object.entries(value.lineup_positions).map(([n,v])=>[convert(n,bat.hitters),v]));
    return {value,unresolved:[...new Set(unresolved)]};
  }
  const api={isId,setRegistry,setContext,currentName,name,text,registerRoster,roster:team=>rosters.get(team),resolve,migrateLineup,migrateEvaluation};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.PlayerIdentity=api;
})(typeof window!=='undefined'?window:globalThis);
