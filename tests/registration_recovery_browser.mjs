// Read-only original task preview plus one local draft annotation. Synthetic
// clicks are cleared; the test neither uploads labels nor writes production.
import fs from 'node:fs';import path from 'node:path';
const [out,url='http://127.0.0.1:8137/',cdp='http://127.0.0.1:9230']=process.argv.slice(2);
if(!out)throw Error('Usage: node tests/registration_recovery_browser.mjs OUT [URL] [CDP]');
fs.mkdirSync(out,{recursive:false});
const pages=await(await fetch(cdp+'/json')).json();const ws=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);
await new Promise(r=>ws.onopen=r);let id=0;const pending=new Map(),errors=[],requests=[];
ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){pending.get(m.id)?.(m);pending.delete(m.id)}if(m.method==='Runtime.exceptionThrown')errors.push(m.params);if(m.method==='Network.requestWillBeSent')requests.push({method:m.params.request.method,url:m.params.request.url})};
const call=(method,params={})=>new Promise((resolve,reject)=>{const n=++id;const timer=setTimeout(()=>{pending.delete(n);reject(Error(method+' timeout'))},10000);pending.set(n,m=>{clearTimeout(timer);m.error?reject(Error(JSON.stringify(m.error))):resolve(m.result)});ws.send(JSON.stringify({id:n,method,params}))});
const run=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value};
const check=(v,n)=>{if(!v)throw Error(n)};
const shot=async name=>{const r=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});fs.writeFileSync(path.join(out,name+'.png'),Buffer.from(r.data,'base64'))};
try{
 await call('Runtime.enable');await call('Network.enable');await call('Network.setCacheDisabled',{cacheDisabled:true});
 await call('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});
 await call('Page.navigate',{url});
 for(let i=0;i<100;i++){if(await run('!!window.previewApp?.ready && !!window.previewApp.$refs.content'))break;await new Promise(r=>setTimeout(r,50))}
 check(await run('previewApp.ready && !previewApp.error'),'Preview not ready');
 await run("previewApp.variant='saved';previewApp.loadVariant()");await run('previewApp.$refs.content.seek(9.5)');
 const before=await run('({...previewApp.quality,spacing:previewApp.spacing,players:previewApp.$refs.content.frame.players.length})');
 check(before.valid===145&&before.players===0,'Original fixed frame was not missing');await shot('before');
 await run("previewApp.variant='subset';previewApp.loadVariant()");await run('previewApp.$refs.content.seek(9.5)');
 const after=await run('({...previewApp.quality,spacing:previewApp.spacing,players:previewApp.$refs.content.frame.players.length})');
 check(after.valid===149&&after.players>0&&after.spacing===61,'Recovered frame count differs');await shot('after');
 await run('previewApp.$refs.content.seek(35.5)');
 check(await run("previewApp.$refs.content.frame.players.length===0 && document.body.innerText.includes('此镜头暂未定位球场')"),'Unmatched new view was silently filled');await shot('reference_missing');
 await run('previewApp.$refs.content.seek(51)');
 check(await run('previewApp.$refs.content.frame.players.length===0'),'Dissolve wrongly filled');
 await call('Page.navigate',{url:url+'recovery/registration-review.html'});
 for(let i=0;i<100;i++){if(await run("document.getElementById('canvas')?.width===1920 && document.getElementById('landmark').options.length===5"))break;await new Promise(r=>setTimeout(r,50))}
 check(await run("$('canvas').width===1920 && $('canvas').height===1080"),'Review image not loaded');
 await shot('one_view_review');
 // Test only in the isolated Chrome profile; no human label is asserted.
 await run("$('clear').click();[['paint_base_left',.2,.2],['paint_base_right',.8,.2],['lane_left',.2,.8],['lane_right',.8,.8]].forEach(([n,x,y])=>{$('landmark').value=n;const r=canvas.getBoundingClientRect();canvas.onclick({clientX:r.left+x*r.width,clientY:r.top+y*r.height})})");
 check(await run('Object.keys(points).length===4'),'Local point input failed');
 await run("$('undo').click()");check(await run('Object.keys(points).length===3'),'Undo failed');
 await run("$('clear').click()");check(await run('Object.keys(points).length===0'),'Synthetic points not cleared');
 check(errors.length===0,'Browser exception '+JSON.stringify(errors));
 check(requests.every(r=>r.method==='GET'&&r.url.startsWith(url)),'External or mutation request');
 fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify({before,after,new_view_unknown:true,dissolve_unknown:true,
   review_single_frame_loaded:true,point_input_undo_clear:true,synthetic_points_cleared:true,
   human_labels_not_submitted:true,errors,requests,production_updated:false},null,2));
 console.log('Registration recovery, missing-view message and one-frame draft input PASS');
}finally{ws.close()}
