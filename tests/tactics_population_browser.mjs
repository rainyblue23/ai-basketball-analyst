// Read-only Chromium preview check; no API writes and no production navigation.
import fs from 'node:fs';
import path from 'node:path';
const [out,url='http://127.0.0.1:8132',cdp='http://127.0.0.1:9229',mode='population']=process.argv.slice(2);
if(!out)throw Error('node tests/tactics_population_browser.mjs ARTIFACT_DIR [PREVIEW_URL] [CDP_URL]');
fs.mkdirSync(out,{recursive:false});
const pages=await(await fetch(cdp+'/json')).json();
const ws=new WebSocket(pages[0].webSocketDebuggerUrl);
await new Promise(r=>ws.onopen=r);
let id=0;const pending=new Map(),errors=[];
ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){pending.get(m.id)?.(m);pending.delete(m.id);}if(m.method==='Runtime.exceptionThrown')errors.push(m.params);};
const call=(method,params={})=>new Promise((resolve,reject)=>{const n=++id;const timer=setTimeout(()=>{pending.delete(n);reject(Error('CDP timeout '+method));},10000);pending.set(n,m=>{clearTimeout(timer);if(m.error)reject(Error(JSON.stringify(m.error)));else resolve(m.result);});ws.send(JSON.stringify({id:n,method,params}));});
const run=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
try{
 await call('Runtime.enable');
 await call('Network.enable');
 await call('Network.setCacheDisabled',{cacheDisabled:true});
 await call('Emulation.setDeviceMetricsOverride',{width:1280,height:1000,deviceScaleFactor:1,mobile:false});
 await call('Page.navigate',{url});
 for(let i=0;i<100;i++){if(await run("document.getElementById('variant')?.dataset.configured==='1' && document.getElementById('status').textContent.length>0"))break;await new Promise(r=>setTimeout(r,50));}
 const selected=mode==='identity'?'linked':'combined',oldVariant=mode==='identity'?'before':'observed';
 if(await run("get('variant').value")!==selected)throw Error('Experimental default missing');
 if(!(await run("document.querySelector('p').textContent")).includes('尚未核实'))throw Error('Anonymous team mapping presented as verified');
 await run(`t=${mode==='identity'?3:13.5};draw()`);
 const statusAfter=await run("get('status').textContent");
 const circles=await run("get('overlay').querySelectorAll('circle').length");
 if(!statusAfter.includes('显示')||circles<1)throw Error('Missing measured positions');
 if(mode==='identity' && !(await run("get('overlay').innerHTML")).includes('T68'))throw Error('Expected temporal alias missing');
 if(!(await run("get('overlay').innerHTML")).includes('fill="#172033"'))throw Error('Unreadable old tactical labels still cached');
 const shot=await call('Page.captureScreenshot',{format:'png'});
 fs.writeFileSync(path.join(out,'after.png'),Buffer.from(shot.data,'base64'));
 await run(`get('variant').value='${oldVariant}';load()`);
 await run(`t=${mode==='identity'?3:13.5};draw()`);
 const statusBefore=await run("get('status').textContent");
 if(mode==='population' && !statusBefore.includes('异常'))throw Error('Original invalid roster was silently shown');
 if(mode==='identity' && !(await run("get('overlay').innerHTML")).includes('T196'))throw Error('Original temporary ID lost');
 const before=await call('Page.captureScreenshot',{format:'png'});
 fs.writeFileSync(path.join(out,'before.png'),Buffer.from(before.data,'base64'));
 await run(`get('variant').value='${selected}';load()`);
 await run("t=14.5;draw()");
 const unknown=await run("get('status').textContent");
 if(!unknown.includes('分队未知'))throw Error('Unknown membership hidden');
 const start=await run('t');
 await run("get('play').click()");await new Promise(r=>setTimeout(r,250));await run("get('play').click()");
 if(await run('t')<=start)throw Error('Playback failed');
 if(mode==='identity'){
  await call('Page.navigate',{url:url+'/review.html'});
  for(let i=0;i<100;i++){if(await run("document.querySelectorAll('section').length===3 && Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)"))break;await new Promise(r=>setTimeout(r,40));}
  if(!(await run("document.querySelectorAll('section').length===3 && document.images.length===6 && Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)")))throw Error('Compact identity review failed');
  const review=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});
  fs.writeFileSync(path.join(out,'review.png'),Buffer.from(review.data,'base64'));
 }
 if(errors.length)throw Error(JSON.stringify(errors));
 fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify({url,statusBefore,statusAfter,circles,unknown,
  playback:true,anonymous_mapping_honest:true,errors,production_written:false},null,2));
 console.log('Read-only tactical preview and playback PASS');
}finally{ws.close();}
