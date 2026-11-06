const {test}=require('node:test'),assert=require('node:assert/strict');
const L=require('../docs/lineup.js'),G=require('../docs/pitcher-groups.js');
test('lineups are isolated by season and existing 2025 shape remains supported',()=>{
 const state={version:2,season:2025,draft:L.empty(),confirmed:null};
 assert.equal(L.validState(state),true);L.setRuntime({season:2026});assert.equal(L.validState(state),false);
 assert.equal(L.validState({...state,season:2026}),true);L.setRuntime({season:2025});assert.equal(L.validState(state),true);
});
test('new-season pitcher groups cannot overwrite old-season groups',()=>{
 const data=new Map(),storage={getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v)};
 const groups=G.names.map(name=>({name,members:[]}));G.setRuntime({season:2025});assert.equal(G.write(storage,'A',groups),true);
 const before=data.get('cpbl-pitcher-groups-v3:A');G.setRuntime({season:2026});assert.deepEqual(G.read(storage,'A'),[]);
 assert.equal(G.write(storage,'A',groups),true);assert.equal(data.get('cpbl-pitcher-groups-v3:A'),before);
 assert.equal(JSON.parse(data.get('cpbl-pitcher-groups-2026-v3:A')).season,2026);G.setRuntime({season:2025});
});
