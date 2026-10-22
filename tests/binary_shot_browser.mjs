// A fresh isolated CDP tab, real overview component, saved job fixture.
// No analysis rerun, labels or production writes.
import fs from 'node:fs';
import path from 'node:path';
const [out,url='http://127.0.0.1:8139/',cdp='http://127.0.0.1:9230']=process.argv.slice(2);
fs.mkdirSync(out,{recursive:false});
const target=await(await fetch(cdp+'/json/new?about:blank',{method:'PUT'})).json();
const ws=new WebSocket(target.webSocketDebuggerUrl);
await new Promise(resolve=>ws.onopen=resolve);
let seq=0;const pending=new Map(),errors=[],requests=[];
ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){pending.get(m.id)?.(m);pending.delete(m.id)}
 if(m.method==='Runtime.exceptionThrown')errors.push(m.params);
 if(m.method==='Network.requestWillBeSent')requests.push({method:m.params.request.method,url:m.params.request.url});};
const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;
 const timer=setTimeout(()=>{pending.delete(id);reject(Error(method+' timed out'));},10000);
 pending.set(id,m=>{clearTimeout(timer);m.error?reject(Error(JSON.stringify(m.error))):resolve(m.result)});
 ws.send(JSON.stringify({id,method,params}));});
const run=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});
 if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
const check=(condition,message)=>{if(!condition)throw Error(message);};
try{
 await call('Runtime.enable');await call('Network.enable');
 await call('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
 await call('Page.navigate',{url});
 for(let i=0;i<120;i++){if(await run('!!window.previewApp?.$refs.page'))break;await new Promise(r=>setTimeout(r,50));}
 check(await run('!!window.previewApp?.$refs.page'),'Overview did not mount: '+JSON.stringify(errors));
 const before=await run(`({labels:[...document.querySelectorAll('.timeline .tl-badge')].map(x=>x.innerText),
  count:previewApp.$refs.page.shotCounts,other:document.querySelectorAll('.shot-review-times .el-button').length,
  raw:JSON.stringify(STORE.game.timeline)===savedEvents,
  score:JSON.stringify(STORE.game.score)===savedScore,
  filters:[...document.querySelectorAll('.el-radio-button')].map(x=>x.innerText),
  resultText:document.querySelector('.timeline').innerText,
  expected:window.previewExpected||{resolved:4,other:4,made:3,miss:1}})`);
 check(before.labels.length===before.expected.resolved && before.other===before.expected.other,'Visible records do not match fixture expectations');
 check(before.labels.every(label=>label==='中'||label==='没中'),'Unexpected result label');
 check(!before.filters.some(label=>label.includes('未知')),'Third filter still rendered');
 check(before.count.made===before.expected.made&&before.count.miss===before.expected.miss&&before.count.pending===(before.expected.pending??before.expected.other)&&before.raw&&before.score,'Suggestions must not inflate results; raw score must remain unchanged');
 check(!/未知|推测|暂定/.test(before.resultText),'Unexpected result/value text remains visible');
 const clip=await run(`(()=>{const r=document.querySelector('.timeline').parentElement.getBoundingClientRect();return {x:Math.max(0,r.x+scrollX),y:r.y+scrollY,width:r.width,height:r.height,scale:1};})()`);
 const screenshot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip});
 fs.writeFileSync(path.join(out,'binary_results.png'),Buffer.from(screenshot.data,'base64'));
 await run(`[...document.querySelectorAll('.el-radio-button')].find(x=>x.innerText==='只看没中').click();Vue.nextTick()`);
 check(await run("previewApp.$refs.page.filterMade==='miss' && document.querySelectorAll('.timeline .tl-badge').length===previewApp.$refs.page.shotCounts.miss"),'Miss filter does not match rendered groups');
 if(before.expected.other){
  await run("document.querySelector('.shot-review-times .el-button').click();Vue.nextTick()");
  check(await run('previewApp.$refs.page.activeRow===STORE.game.timeline.indexOf(previewApp.$refs.page.unresolvedShots[0])'),'Other time lost its original event identity');
 }else{
  check(await run("!document.querySelector('.shot-review-times') && !/证据不足|其他回看时间/.test(document.querySelector('.timeline').parentElement.innerText)"),'Removed result section is still visible');
 }
 check(errors.length===0,JSON.stringify(errors));
 check(requests.every(r=>r.method==='GET'&&(r.url.startsWith(url)||r.url.startsWith('data:'))),'Unexpected external/write request');
 fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify({before,miss_filter:true,errors,requests,
  production_updated:false,fixture:'saved job data; UI only; no accuracy conclusion'},null,2));
 console.log('Two literal labels; every source time retained; no unknown values; original score PASS');
}finally{ws.close();await fetch(cdp+'/json/close/'+target.id);}
