const fs=require('node:fs'),vm=require('node:vm');
const model=JSON.parse(fs.readFileSync('docs/data/model.json','utf8'));
const c={fetch:async()=>({json:async()=>model})};vm.createContext(c);
vm.runInContext(fs.readFileSync('docs/engine.js','utf8')+'\nthis.engine=Engine;',c);
(async()=>{await c.engine.load();const bodies=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
fs.writeFileSync(process.argv[3],JSON.stringify(bodies.map(b=>c.engine.evaluate(b))));})().catch(e=>{console.error(e);process.exitCode=1;});
