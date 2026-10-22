// Browser or Node: independent frames, drag boxes, save both, retry and stale-frame protection.
(async function () {
  if (typeof window === 'undefined') {
    global.window = {STORE:{}};
    require('../web/pages/upload.js');
    global.document = {createElement:()=>({getContext:()=>({drawImage(video){this.video=video;}}),toDataURL:()=> 'native_frame'})};
  }
  const p = window.PAGES.upload;
  function check(value, message) { if (!value) throw Error(message); }
  const vm = Object.assign(p.data(), {$message:{warning(){},error(){},success(){},info(){}}});
  Object.keys(p.methods).forEach(k => vm[k] = p.methods[k].bind(vm));
  vm.form.video_path = '/tmp/match.mp4';
  const flush = () => new Promise(resolve=>setTimeout(resolve,0));
  let requestedFrames = 0;
  vm.loadPlayer = function () {};
  window.API = {getMarks:async()=>({exists:false}),getFrame:async()=>{requestedFrames++;}};
  vm.openMark(); await flush();
  check(requestedFrames===0, 'Do not assign an arbitrary frame to left or right');
  vm.$refs = {hoopVideo_left:[{currentTime:3,readyState:2,videoWidth:100,videoHeight:100,pause(){}}],hoopVideo_right:[{currentTime:19,readyState:2,videoWidth:100,videoHeight:100,pause(){}}]};
  window.API.getFrame = async (_v,t)=>({image:'frame_'+t,w:100,h:100});
  vm.captureHoopPanel('left');vm.captureHoopPanel('right');await flush();
  check(vm.hoopPanels.left.frameAt===3 && vm.hoopPanels.right.frameAt===19,
    'Each side captures its own player time');
  check(requestedFrames===0,'Native capture must not round-trip to the frame API');
  vm.hoopPanels.right.box=[.5,.5,.1,.1];vm.hoopPanels.right.restored=true;
  vm.hoopPanels.left.at=1;vm.$refs.hoopVideo_left[0].currentTime=12;
  vm.captureHoopPanel('left');
  check(vm.hoopPanels.left.frameAt===12,'Capture must use player time, not stale numeric time');
  check(vm.hoopPanels.right.box && vm.hoopPanels.right.restored,'Left capture must preserve the saved right box');
  vm.$refs.hoopVideo_left[0].currentTime=3;vm.captureHoopPanel('left');
  vm.$nextTick=fn=>fn.call(vm);
  vm.swapHoopPanels();
  check(vm.hoopPanels.left.frameAt===19 && vm.hoopPanels.right.frameAt===3,
    'Swap must exchange frames and timestamps together');
  vm.swapHoopPanels();

  vm.markKind = 'hoop'; vm.markOpen = true;
  const event = (x,y) => ({clientX:x,clientY:y,preventDefault(){},
    currentTarget:{getBoundingClientRect:()=>({left:0,top:0,width:100,height:100})}});
  for (const side of ['left','right']) {
    vm.hoopPanels[side].image = 'frame';
    vm.hoopPanels[side].frameAt = side==='left' ? 3 : 19;
    vm.hoopPanelDown(side,event(10,20));
    vm.hoopPanelUp(side,event(30,40));
  }
  check(vm.hoopPanels.left.box && vm.hoopPanels.right.box, 'Drawing right must retain left');
  const calls=[];
  let fail = true;
  window.API = {saveMarks: async payload => {
    calls.push(payload);
    if (payload.hoop_side==='right' && fail) throw Error('retry');
    return {path:'marks.json',marks:{hoops:{[payload.hoop_side]:{hoop:payload.hoop}}}};
  }};
  const tick = () => new Promise(resolve=>setTimeout(resolve,0));
  vm.saveMarks(); await tick();
  check(vm.markOpen && !vm.markSaving, 'Partial failure must retain dialog');
  check(vm.hoopPanels.left.box && vm.hoopPanels.right.box, 'Retry must retain both boxes');
  fail=false; vm.saveMarks(); await tick();
  check(!vm.markOpen && !vm.markSaving, 'Both saves must complete before close');
  check(calls[2].at===3 && calls[3].at===19, 'Each box must use its captured timestamp');
  let resolveOld;
  window.API.getFrame = () => new Promise(resolve=>resolveOld=resolve);
  vm.loadHoopPanel('right');
  check(!vm.hoopPanels.right.box && !!vm.hoopPanels.left.box, 'Replacing right clears only right');
  vm.hoopSession++;
  resolveOld({image:'stale',w:100,h:100}); await tick();
  check(vm.hoopPanels.right.image!=='stale', 'Old dialog requests must be ignored');
  if (typeof document !== 'undefined' && document.getElementById) document.getElementById('result').textContent='DUAL_HOOPS_PASS';
  else console.log('Dual hoops passed');
})().catch(e=>{
  if (typeof document !== 'undefined' && document.getElementById) document.getElementById('result').textContent='FAIL '+e.stack;
  else { console.error(e); process.exitCode=1; }
});
