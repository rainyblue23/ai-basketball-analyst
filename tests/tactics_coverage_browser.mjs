// Real Vue pages with local saved data only; never writes to the production API.
import fs from 'node:fs';
import path from 'node:path';
const [out, url='http://127.0.0.1:8136/', cdp='http://127.0.0.1:9230'] = process.argv.slice(2);
if (!out) throw Error('Usage: node tests/tactics_coverage_browser.mjs OUT [URL] [CDP]');
fs.mkdirSync(out, {recursive:false});
const pages=await(await fetch(cdp+'/json')).json();
const ws=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);
await new Promise(r=>ws.onopen=r);
let id=0; const pending=new Map(),errors=[],requests=[];
ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){pending.get(m.id)?.(m);pending.delete(m.id);}
  if(m.method==='Runtime.exceptionThrown')errors.push(m.params);
  if(m.method==='Network.requestWillBeSent')requests.push({url:m.params.request.url,method:m.params.request.method});};
const call=(method,params={})=>new Promise((resolve,reject)=>{const n=++id;const timer=setTimeout(()=>{pending.delete(n);reject(Error(method+' timeout'));},10000);
  pending.set(n,m=>{clearTimeout(timer);m.error?reject(Error(JSON.stringify(m.error))):resolve(m.result);});ws.send(JSON.stringify({id:n,method,params}));});
const run=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
const check=(v,message)=>{if(!v)throw Error(message);};
const shot=async name=>{const r=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});fs.writeFileSync(path.join(out,name+'.png'),Buffer.from(r.data,'base64'));};
try {
  await call('Runtime.enable');await call('Network.enable');await call('Network.setCacheDisabled',{cacheDisabled:true});
  await call('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});
  await call('Page.navigate',{url});
  for(let i=0;i<100;i++){if(await run("!!window.previewApp?.ready && !!window.previewApp?.$refs.content"))break;await new Promise(r=>setTimeout(r,50));}
  check(await run("window.previewApp.ready && !window.previewApp.error"),'Preview load failed');
  const select=variant=>run(`previewApp.variant=${JSON.stringify(variant)};previewApp.loadVariant()`);
  await select('saved');
  const before=await run('({...previewApp.quality,spacing:previewApp.spacing})');
  check(before.valid===51&&before.total===182&&before.spacing===25,'Saved task differs from screenshot');
  await shot('before');
  await select('subset');
  const after=await run('({...previewApp.quality,spacing:previewApp.spacing})');
  check(after.valid===145&&after.total===182&&after.spacing===60,'Repaired coverage mismatch');
  check(await run("document.body.innerText.includes('不代表完整五人阵容') && document.body.innerText.includes('每次可见人数')"),'Subset scope missing');
  const chart=await run('({series:previewApp.$refs.content.spacingOption.series.map(s=>({data:s.data,connectNulls:s.connectNulls}))})');
  check(chart.series.every(s=>s.connectNulls===false),'Curve connected unknown spans');
  check(chart.series.some(s=>s.data.some(p=>p[2]>=2)),'Observed player count missing');
  await run('previewApp.$refs.content.seek(13.5)');
  const time=await run('previewApp.$refs.content.playT');
  await run('previewApp.$refs.content.toggle()');await new Promise(r=>setTimeout(r,250));await run('previewApp.$refs.content.toggle()');
  check(await run('previewApp.$refs.content.playT')>time,'Playback failed');
  await shot('after');
  // Render the actual overview template with one temporary miss, make and
  // unknown input. Synthetic inputs remain exclusively inside this test tab.
  await run("window.originalTimeline=JSON.parse(JSON.stringify(STORE.game.timeline));STORE.game.timeline=[{t:1,result:'missed',made:false,value:3},{t:2,result:'made',made:true,value:2},{t:3,result:'unknown',made:null,value:3}];previewApp.page='overview';Vue.nextTick()");
  await run('Vue.nextTick()');
  const displayed=await run("Array.from(document.querySelectorAll('.tl-row')).map(r=>({text:r.innerText,value:r.querySelector('strong')?.innerText||''}))");
  check(displayed.length===3,'Overview matrix not rendered');
  check(displayed[0].text.includes('未中')&&!displayed[0].text.includes('分')&&!displayed[0].value,'Miss still displays a value');
  check(displayed[1].text.includes('命中')&&displayed[1].value==='2 分','Confirmed make value missing');
  check(displayed[2].text.includes('未知')&&!displayed[2].value,'Unknown coerced into a scored result');
  await shot('shot_display_test_matrix');
  await run("STORE.game.timeline=window.originalTimeline;delete window.originalTimeline;Vue.nextTick()");
  await shot('saved_shots_after');
  await run("previewApp.page='tactics';Vue.nextTick()");
  check(errors.length===0,'Browser runtime errors: '+JSON.stringify(errors));
  check(requests.every(r=>r.method==='GET'&&r.url.startsWith(url)),'Preview sent external or mutation requests');
  fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify({url,before,after,partial_scope_visible:true,playback:true,
    missed_point_value_hidden:true,confirmed_made_value_visible:true,unknown_preserved:true,
    screenshot_test_matrix_is_synthetic:true,saved_timeline_restored:true,errors,requests,production_updated:false},null,2));
  console.log('Actual tactical page, observed subsets, playback and outcome rendering PASS');
} finally {ws.close();}
