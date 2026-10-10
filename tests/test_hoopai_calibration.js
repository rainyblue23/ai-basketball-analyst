const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const elements={},requests=[],messages=[];
const ctx={clearRect(){},drawImage(){},beginPath(){},lineTo(){},moveTo(){},stroke(){},arc(){},fill(){},fillText(){}};
function el(id){return elements[id]||(elements[id]={value:'0',checked:false,disabled:false,style:{},options:[],append(o){this.options.push(o);if(id==='landmark' && this.value==='0')this.value=o.value;},getContext(){return ctx;},getBoundingClientRect(){return {left:0,top:0,width:640,height:480};},scrollIntoView(){}});}
const names=['a','b','c','d'];
const sandbox={URLSearchParams,console,Set,Image:class{set src(v){this.naturalWidth=640;this.naturalHeight=480;this.onload();}},
 location:{search:'?video=fixture.mp4&api=http://localhost:8000',origin:'http://localhost:8000'},
 document:{getElementById:el,createElement(){return el('new'+Math.random());}},
 window:{parent:{postMessage(m){messages.push(m);}}},confirm:()=>true,
 fetch:async(url,options)=>{requests.push({url,options});let data={};
  if(url.includes('/hoopai/court'))data={landmarks:names.map(name=>({name,label:name})),default_names:names};
  else if(url.includes('/camera_profiles'))data={profiles:[]};
  else if(url.includes('/frames'))data={frames:[{t:2,image:'data:image/jpeg;base64,fixture'}]};
  else if(options?.method==='POST')data={ok:true,saved:JSON.parse(options.body).confirm,lines:[[[0,0],[1,1]]],reproj_err_px:0};
  else data={exists:false,revision:0};
  return {ok:true,json:async()=>data};
 }};
vm.runInNewContext(fs.readFileSync(path.resolve(__dirname,'../web/hoopai-calibration.js'),'utf8'),sandbox);
(async()=>{
 await new Promise(resolve=>setImmediate(resolve));
 const canvas=el('court');
 for(let i=0;i<4;i++){el('landmark').value=names[i];canvas.onclick({clientX:100+i*30,clientY:100+i*20});}
 assert.equal(el('preview').disabled,false);
 el('landmark').value='a';canvas.onclick({clientX:50,clientY:60});
 await el('preview').onclick();
 const preview=JSON.parse(requests.find(r=>r.options?.method==='POST').options.body);
 assert.equal(Object.keys(preview.landmarks).length,4,'repeat landmark replaces point');
 assert.equal(preview.landmarks.a[0],50/640);
 assert.equal(preview.at,2,'preview image time is retained');
 assert.equal(preview.confirm,false);assert.equal(preview.court_model,'hoopai');
 assert.equal(el('save').disabled,true);
 el('fixed').checked=true;el('aligned').checked=true;el('aligned').onchange();
 assert.equal(el('save').disabled,false);
 await el('save').onclick();
 assert.equal(messages.length,1);assert.equal(messages[0].type,'hoopai-calibration-saved');
 console.log('HoopAI calibration: selection, replacement, preview, confirmation and return passed');
})().catch(e=>{console.error(e);process.exitCode=1});
