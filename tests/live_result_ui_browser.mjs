// Deployment verification with a temporary account; no analysis/result writes.
import fs from 'node:fs';
import path from 'node:path';
const [out,base='https://basketparts.top',cdp='http://127.0.0.1:9230']=process.argv.slice(2);
const user=process.env.UI_VERIFY_USERNAME,password=process.env.UI_VERIFY_PASSWORD;
if(!out||!user||!password)throw Error('Temporary verification credentials required');
fs.mkdirSync(out,{recursive:false});
const target=await(await fetch(cdp+'/json/new?about:blank',{method:'PUT'})).json();
const ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise(r=>ws.onopen=r);
let seq=0;const pending=new Map(),errors=[],requests=[];
ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){pending.get(m.id)?.(m);pending.delete(m.id)}
 if(m.method==='Runtime.exceptionThrown')errors.push(m.params);
 if(m.method==='Network.requestWillBeSent')requests.push({method:m.params.request.method,url:m.params.request.url});};
const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;
 const timer=setTimeout(()=>{pending.delete(id);reject(Error(method+' timeout'));},20000);
 pending.set(id,m=>{clearTimeout(timer);m.error?reject(Error(JSON.stringify(m.error))):resolve(m.result)});
 ws.send(JSON.stringify({id,method,params}));});
const run=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});
 if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text||'Browser expression failed');return r.result.value;};
const check=(value,message)=>{if(!value)throw Error(message);};
try{
 await call('Runtime.enable');await call('Network.enable');await call('Network.setCacheDisabled',{cacheDisabled:true});
 await call('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});
 await call('Page.navigate',{url:base+'/web/login.html'});
 for(let i=0;i<300;i++){if(await run("location.pathname==='/web/login.html'&&document.readyState==='complete'"))break;await new Promise(r=>setTimeout(r,100));}
 const status=await run(`fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(${JSON.stringify({username:user,password})})}).then(r=>r.status)`);
 check(status===200,'Temporary login failed: '+status);
 await call('Page.navigate',{url:base+'/web/index.html#/overview'});
 for(let i=0;i<300;i++){if(await run("!!window.STORE?.backendOk&&!!window.STORE?.game"))break;await new Promise(r=>setTimeout(r,100));}
 check(await run("document.documentElement.dataset.resultUi==='104'"),'Public site did not serve the new HTML');
 await run("(async()=>{window.liveOriginal=await(await fetch('/api/games/097c0611d8c3',{cache:'no-store'})).json();await APP_LOAD_JOB('097c0611d8c3');location.hash='#/overview';await Vue.nextTick()})()");
 for(let i=0;i<100;i++){if(await run("document.querySelectorAll('.timeline .tl-badge').length===2"))break;await new Promise(r=>setTimeout(r,100));}
 const result=await run(`(()=>{const signature=rows=>JSON.stringify(rows.map(e=>({t:e.t,made:e.made,result:e.result,value:e.value,counts_for_score:e.counts_for_score})));return {
  release:document.documentElement.dataset.resultUi,labels:[...document.querySelectorAll('.timeline .tl-badge')].map(e=>e.innerText),
  other:document.querySelectorAll('.shot-review-times').length,resultText:document.querySelector('.timeline')?.parentElement.innerText,
  scoreUnchanged:JSON.stringify(STORE.game.score)===JSON.stringify(liveOriginal.score),eventsUnchanged:signature(STORE.game.timeline)===signature(liveOriginal.timeline),
  scripts:[...document.scripts].map(e=>e.src).filter(s=>s.includes('104-result-ui-release'))};})()`);
 check(result.labels.length===2&&result.labels.every(s=>s==='中'),'Displayed outcomes differ from saved task');
 check(result.other===0,'Other-times section still displayed');
 check(!/未知|推测|暂定|证据不足|其他回看时间/.test(result.resultText),'Removed result text still displayed');
 check(result.scoreUnchanged&&result.eventsUnchanged,'UI changed saved outcomes or score');
 check(result.scripts.length===6,'Expected versioned scripts were not loaded');
 const clip=await run("(()=>{const r=document.querySelector('.timeline').parentElement.getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1};})()");
 const screenshot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip});
 fs.writeFileSync(path.join(out,'production_results.png'),Buffer.from(screenshot.data,'base64'));
 const logout=await run("fetch('/api/logout',{method:'POST'}).then(r=>r.status)");check(logout===200,'Verification logout failed');
 check(errors.length===0,JSON.stringify(errors));
 fs.writeFileSync(path.join(out,'requests.json'),JSON.stringify(requests,null,2));
 const writes=requests.filter(r=>r.method!=='GET'&&r.method!=='HEAD');
 const applicationWrites=writes.filter(r=>new URL(r.url).origin===new URL(base).origin&&new URL(r.url).pathname.startsWith('/api/'));
 check(applicationWrites.every(r=>r.url===base+'/api/login'||r.url===base+'/api/logout'),'Unexpected application mutation: '+JSON.stringify(applicationWrites));
 fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify({origin:base,result,errors,requests,login:true,logout:true,analysis_or_result_writes:false},null,2));
 console.log('Public authenticated page: release104, only binary results, no other-times section, unchanged raw results PASS');
}finally{fs.writeFileSync(path.join(out,'requests.json'),JSON.stringify(requests,null,2));ws.close();await fetch(cdp+'/json/close/'+target.id);}
