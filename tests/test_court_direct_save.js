const assert=require('node:assert/strict');
global.window={STORE:{}};require('../web/pages/upload.js');
const p=window.PAGES.upload;
assert.ok(!p.template.includes('生成并显示球场矩阵'));
assert.ok(!p.template.includes('showCourtOverlay'));
assert.ok(!p.template.includes('4 点试算'));
let payload;
window.API={calibrateMulti:async body=>{payload=body;return {saved:true,n_points:14,n_frames:2,rmse_m:.2};}};
const vm={courtMini:false,mfEnough:true,mfFullCourtReady:true,mfVersion:1,mfPreviewed:false,mfResult:null,
 form:{video_path:'/tmp/game.mp4'},calInfo:{revision:2},courtStandard:'nba',markOpen:true,
 courtMultiPayload:()=>({frames:[{t:1,landmarks:{}},{t:12,landmarks:{}}],note:''}),
 loadCalInfo(){},$message:{warning(){},error(){},success(){}}};
(async()=>{
 await p.methods.saveCourtMulti.call(vm);
 await new Promise(r=>setTimeout(r,0));
 assert.equal(payload.confirm,true,'direct save must run backend verification');
 assert.equal(payload.compensate,false);
 assert.equal(payload.revision,2);
 assert.equal(vm.markOpen,false);
 console.log('Court direct save works without preview; cyan overlay and preview controls removed');
})().catch(e=>{console.error(e);process.exitCode=1;});
