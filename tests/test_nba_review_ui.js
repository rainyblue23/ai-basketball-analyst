const assert=require('node:assert/strict');
const fs=require('node:fs');const vm=require('node:vm');
const html=fs.readFileSync('web/match-labeling.html','utf8');
const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
new vm.Script(script);
const line=script.split('\n').find(x=>x.startsWith('const frameTime='));
const frameTime=vm.runInNewContext(line+'\nframeTime');
assert.equal(frameTime({frame_times:{'frame_000780.jpg':26.026}},'frame_000780.jpg'),26.026);
assert.equal(frameTime({},'frame_0012.50.jpg'),12.5);
assert(!script.includes("$('range').textContent='原片 00:30–01:30 · 60秒'"));
assert(script.includes('frameTime(item,item.images[frameIndex])'));
assert(html.includes('value="rim"'));
assert(!script.includes('NBA总决赛'));
console.log('NBA review timestamp and legacy compatibility passed');

const activeTimeLine=script.split('\n').find(x=>x.startsWith('const activeReviewTime='));
const activeReviewTime=vm.runInNewContext(activeTimeLine+'\nactiveReviewTime');
assert.equal(activeReviewTime(true,21.054,19.5),21.054);
assert.equal(activeReviewTime(false,21.054,19.5),19.5);
assert(html.includes('id="markReleaseStart"') && html.includes('id="markReleaseEnd"'));

const selectSource=script.slice(script.indexOf('function selectReviewIndices('),script.indexOf('function shownFrames('));
const selectReviewIndices=vm.runInNewContext(selectSource+'\nselectReviewIndices',{frameTime});
const task={images:Array.from({length:120},(_,i)=>`frame_${String(i).padStart(6,'0')}.jpg`),frame_times:{}};
task.images.forEach((n,i)=>task.frame_times[n]=i/30);
const labels={shots:[{release_s:1}],frames:[{image:task.images[77],visibility:'visible',boxes:[{kind:'ball',xyxy:[.1,.1,.2,.2]}]}]};
const frozen=JSON.stringify(labels);const indices=selectReviewIndices(task,labels,{});
assert(indices.length<=12);assert(indices.includes(29)&&indices.includes(30)&&indices.includes(31)&&indices.includes(77));
assert.equal(JSON.stringify(labels),frozen);assert.equal(selectReviewIndices({...task,images:[]},labels,{}).length,0);
