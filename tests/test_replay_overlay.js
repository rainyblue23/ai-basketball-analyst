const fs=require('fs'),vm=require('vm'),assert=require('assert');
const c={window:{}};vm.createContext(c);vm.runInContext(fs.readFileSync('web/detection-overlay.js','utf8'),c);
const R=c.window.REPLAY_BOXES;
const frames=[{t:0,segment:1,ball:[0,0,2,2]},{t:.1,segment:1,ball:[2,2,4,4]},{t:.2,cut:true,segment:2,ball:[4,4,6,6]},{t:.3,segment:2,ball:[6,6,8,8]}];
assert.equal(R.frameAt(frames,-.1),null);assert.equal(R.frameAt(frames,.05).t,0);
assert.equal(R.frameAt(frames,.6),null);assert.equal(R.trailAt(frames,.1),'1,1 3,3');
assert.equal(R.trailAt(frames,.2),'');assert.equal(R.trailAt(frames,.3),'5,5 7,7');
assert.equal(R.trailAt([{t:0,ball:[0,0,2,2]},{t:.3,ball:[1,1,3,3]}],.3),'');
const vue={};vm.createContext(vue);vm.runInContext(fs.readFileSync('web/vendor/vue.global.prod.js','utf8'),vue);
vue.Vue.compile(c.window.COMPONENTS['detection-overlay'].template,{decodeEntities:s=>s.replace(/&amp;/g,"&").replace(/&lt;/g,"<").replace(/&gt;/g,">"),onError:e=>{throw e;}});
// 判据是「挂上了 detection-overlay 并且带 job-id」，不是属性的书写顺序 ——
// 有人给标签加了 ref="boxOverlay" 之后，原来的 includes('<detection-overlay :job-id=') 就误报了（实测踩到）。
assert(/<detection-overlay\b[^>]*:job-id="S\.jobId"/.test(fs.readFileSync('web/pages/overview.js','utf8')));
console.log('Replay overlay: timing, gaps, cuts, template and player wiring passed');

assert.equal(R.eventTime({t:4,review_t:0,crossing_t:3}),0);
assert.equal(R.eventTime({t:4,review_t:null,crossing_t:3}),3);
assert.equal(R.stepTime(0,-1,30,10),0);
assert(Math.abs(R.stepTime(1,1,30,10)-31/30)<1e-8);
assert(R.stepTime(10,1,30,10)<10);
assert.equal(R.stepTime(1,1,0,10),1);
const tools=c.window.COMPONENTS['replay-tools'];
const first={t:3,made:null},second={t:1,made:true},other={t:0,type:'pass'};
const rows=tools.computed.markers.call({events:[first,second,other],duration:10});
assert.equal(rows.length,2);assert.equal(rows[0].row,second);assert.equal(rows[0].index,1);
let paused=false;const video={currentTime:1,duration:10,pause(){paused=true;}};
tools.methods.step.call({$parent:{$refs:{video}},ready:true,effectiveFps:30},1);
assert(paused);assert(Math.abs(video.currentTime-31/30)<1e-8);
let change={$parent:{$refs:{video}},rate:1};tools.methods.changeRate.call(change,.25);assert.equal(video.playbackRate,.25);
let selection={selectedPlayer:''};const select=c.window.COMPONENTS['detection-overlay'].methods.selectPlayer;
select.call(selection,{id:'T2'});assert.equal(selection.selectedPlayer,'T2');select.call(selection,{id:'T2'});assert.equal(selection.selectedPlayer,'');
vue.Vue.compile(tools.template,{decodeEntities:s=>s.replace(/&amp;/g,"&").replace(/&lt;/g,"<").replace(/&gt;/g,">"),onError:e=>{throw e;}});
console.log('Replay tools: event identity, zero timestamp, stepping, playback speed and selection passed');
