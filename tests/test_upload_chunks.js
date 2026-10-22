const assert = require('node:assert/strict');
global.location={search:'',protocol:'https:',origin:'https://test'};
global.window={};
require('../web/api.js');
const API=window.API;
let sends=[], fail=true, received=new Set(), bytes=0, active=0, maximum=0;
global.XMLHttpRequest=class {
  constructor(){this.headers={};this.upload={};}
  open(method,url){this.url=url;}
  setRequestHeader(k,v){this.headers[k]=v;}
  send(blob){
    const offset=Number(this.headers['x-upload-offset']);
    sends.push([offset,blob.size]);
    active++; maximum=Math.max(maximum,active);
    if(offset===1048576 && fail){fail=false;setTimeout(()=>{active--;this.onerror();},10);return;}
    this.status=200;
    const end=offset+blob.size, total=Number(this.headers['x-upload-size']);
    if(!received.has(offset)){received.add(offset);bytes+=blob.size;}
    this.responseText=JSON.stringify(bytes===total ? {complete:true,path:'video.mp4',bytes:total} : {complete:false,received:bytes});
    setTimeout(()=>{active--;this.onload();},10);
  }
};
(async()=>{
  const blob=new Blob([new Uint8Array(3200000)]);blob.name='比赛.mp4';
  const progress=[];
  const r=await API.uploadVideo(blob,p=>progress.push(p));
  assert.equal(r.bytes,blob.size);
  assert.equal(sends.filter(x=>x[0]===1048576).length,2);
  assert.equal(maximum,3,'Only three chunks should be in flight');
  assert.ok(sends.every(x=>x[1]<=1048576));
  assert.equal(progress.at(-1),1);
  console.log('Chunk upload retry and completion passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
