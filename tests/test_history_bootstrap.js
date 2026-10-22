const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function context(overrides = {}) {
  let demoCalls = 0;
  const app = {use(){return this;},component(){return this;},mount(){return this;}};
  const api = {
    probe: async () => true, listJobs: async () => [],
    loadDemo: async () => {demoCalls++;throw Error('Automatic demo load');},
    demoTactics: async () => {demoCalls++;return {};},
    demoTacticsFrames: async () => {demoCalls++;return {frames:[]};},
    game: async () => ({timeline:[],score:{home:0,away:0}}),
    players:async()=>[],shotchart:async()=>({}),report:async()=>({}),highlights:async()=>({clips:[]}),
    ...overrides
  };
  const c = {window:{COMPONENTS:{},API:api},sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},
    Vue:{reactive:x=>x,createApp:()=>app},ElementPlus:{},ElementPlusLocaleZhCn:{},
    location:{hash:'#/home'},document:{documentElement:{getAttribute:()=>null}}};
  vm.runInNewContext(fs.readFileSync('web/data.js','utf8'),c);
  vm.runInNewContext(fs.readFileSync('web/app.js','utf8'),c);
  return {c,demoCalls:()=>demoCalls};
}

(async()=>{
  for (const overrides of [
    {}, {probe:async()=>false}, {probe:async()=>{throw Error('offline');}},
    {listJobs:async()=>{throw Error('history unavailable');}},
    {listJobs:async()=>[{job_id:'broken',status:'done',source:'video'}],game:async()=>{throw Error('missing result');}},
    {listJobs:async()=>[{job_id:'test-job',status:'done',source:'synthetic'}]},
    {listJobs:async()=>[{job_id:'pending',status:'running',source:'video'}]}
  ]) {
    const t = context(overrides);
    // Simulate leftover state from an earlier selected result.
    Object.assign(t.c.window.STORE,{game:{timeline:[{t:1}]},jobId:'stale',players:[{name:'old'}]});
    await t.c.window.APP_BOOTSTRAP();
    await t.c.window.APP_TACTICS();
    assert.equal(t.demoCalls(),0);
    assert.equal(t.c.window.STORE.game,null);
    assert.equal(t.c.window.STORE.demoMode,false);
    assert.equal(t.c.window.STORE.jobId,'');
    assert.equal(t.c.window.STORE.players.length,0);
    assert.ok(t.c.window.STORE.notice.length>0);
    assert.equal(t.c.window.STORE.tactics.available,false);
  }
  const valid = context({listJobs:async()=>[{job_id:'real',status:'done',source:'video'}]});
  await valid.c.window.APP_BOOTSTRAP();
  assert.equal(valid.c.window.STORE.jobId,'real');
  assert.equal(valid.c.window.STORE.demoMode,false);
  assert.equal(valid.demoCalls(),0);
  const explicit = context();
  explicit.c.window.STORE.demoMode=true;
  await explicit.c.window.APP_TACTICS();
  assert.equal(explicit.demoCalls(),2,'Explicit demo remains available');
  console.log('History empty/offline/failure stays empty; real and explicit demo paths PASS');
})().catch(e=>{console.error(e);process.exitCode=1;});
