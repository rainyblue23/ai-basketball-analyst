// Real Chromium UI check; writes only an explicitly synthetic disposable task.
// Requires an existing loopback CDP endpoint and the generated review workspace.
import fs from 'node:fs';import path from 'node:path';import {spawn} from 'node:child_process';
const [batch,artifact,cdp='http://127.0.0.1:9228']=process.argv.slice(2);
if(!batch||!artifact)throw Error('node tests/review_browser.mjs REVIEW_DIR NEW_ARTIFACT_DIR [CDP_URL]');
fs.mkdirSync(artifact,{recursive:false});const original=JSON.parse(fs.readFileSync(path.join(batch,'manifest.json'),'utf8'))[0];
const task={...original,id:'synthetic_browser_fixture',source_match_id:'SYNTHETIC_UI_TEST_NOT_TRUTH'};
const folder=path.join(artifact,task.id);fs.mkdirSync(folder);const names=Object.keys(task.frame_times).slice(0,40);
for(const name of names)fs.symlinkSync(path.resolve(batch,original.id,name),path.join(folder,name));
fs.writeFileSync(path.join(artifact,'manifest.json'),JSON.stringify([task]));fs.writeFileSync(path.join(folder,'evidence.json'),'{}');
const port=8130;const server=spawn('/data/conda-envs/ai-basketball-analyst/bin/python',['scripts/serve_match_labeling.py','--batch',artifact,'--port',String(port)],{stdio:'ignore'});
let ws;
try{
 for(let i=0;i<100;i++){try{await fetch(`http://127.0.0.1:${port}/manifest`);break}catch{await new Promise(r=>setTimeout(r,40))}}
 const pages=await (await fetch(cdp+'/json')).json();ws=new WebSocket(pages[0].webSocketDebuggerUrl);await new Promise(r=>ws.onopen=r);
 let id=0;const waiting=new Map(),errors=[];ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){waiting.get(m.id)?.(m);waiting.delete(m.id)}if(m.method==='Runtime.exceptionThrown')errors.push(m.params)};
 const call=(method,params={})=>new Promise(r=>{const n=++id;waiting.set(n,r);ws.send(JSON.stringify({id:n,method,params}))});
 const run=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.result.exceptionDetails)throw Error(JSON.stringify(r.result.exceptionDetails));return r.result.result.value};
 await call('Runtime.enable');await call('Page.navigate',{url:`http://127.0.0.1:${port}`});await new Promise(r=>setTimeout(r,350));
 for(let i=0;i<100;i++){if(await run("document.getElementById('overview')?.children.length===1"))break;await new Promise(r=>setTimeout(r,40))}
 const sparseCount=await run("shownFrames().length");
 if(!(sparseCount<=11&&sparseCount<names.length))throw Error('Sparse default failed');
 await run("tab(true);$('frameMode').value='all';$('frameMode').onchange()");
 if(await run("shownFrames().length")!==names.length)throw Error('Full frame access lost');
 await run("$('frameMode').value='key';$('frameMode').onchange();frameIndex=0;showFrame();$('skipFrame').click()");
 const skip=await run("data.frames.find(f=>f.image===item.images[0])");
 if(skip.visibility!=='pending'||!skip.review_skip)throw Error('Skip promoted truth');
 await run("tab(true);frameIndex=0;showFrame();$('markReleaseStart').click();frameIndex=1;showFrame();$('markReleaseEnd').click()");
 const captured=await run("data.review.release_interval");
 if(!(Array.isArray(captured)&&captured[1]>captured[0]))throw Error('Frame interval capture failed');
 await run("$('reviewer').value='AUTOMATED_UI_TEST_NOT_HUMAN';$('isShot').value='unknown';$('isReplay').value='unknown';$('reviewResult').value='unknown';$('reviewStatus').value='in_progress';collectReview();save()");
 const saved=JSON.parse(fs.readFileSync(path.join(folder,'annotations.json'),'utf8'));
 if(saved.training_approved!==false||saved.review.status!=='in_progress'||saved.review_status!=='pending_human_review')throw Error('Unexpected truth/approval promotion');
 await call('Page.reload');await new Promise(r=>setTimeout(r,350));
 const persisted=await run("$('reviewer').value==='AUTOMATED_UI_TEST_NOT_HUMAN' && $('reviewStatus').value==='in_progress'");
 if(!persisted||errors.length)throw Error(JSON.stringify({persisted,errors}));
 fs.writeFileSync(path.join(artifact,'checks.json'),JSON.stringify({browser_save_reload:true,frame_interval_buttons:true,sparse_default_count:sparseCount,full_frame_access:true,skip_keeps_pending:true,training_approved:false,synthetic_fixture_only:true,real_annotation_tasks_modified:false,console_errors:errors},null,2));
 console.log('Chromium real save/reload passed in synthetic fixture only');
}finally{ws?.close();server.kill('SIGTERM')}
