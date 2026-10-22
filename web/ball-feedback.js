(function(){
'use strict';
window.COMPONENTS=window.COMPONENTS||{};
window.COMPONENTS['ball-feedback']={
props:['jobId'],
data:function(){return {open:false,busy:false,loading:false,error:'',boxes:[],mode:'ball',conditions:[],image:null,start:null,t:0,requestSerial:0};},
watch:{jobId:function(){this.requestSerial++;this.open=false;this.image=null;}},
methods:{
begin:async function(){
var v=this.$parent.$refs.video;if(!v||!v.videoWidth)return;
v.pause();this.t=v.currentTime;this.boxes=[];this.conditions=[];this.error='';this.open=true;this.loading=true;this.image=null;
var serial=++this.requestSerial;
try{
var r=await fetch(window.API.base+'/api/games/'+encodeURIComponent(this.jobId)+'/ball-feedback/frame?t='+this.t);
if(!r.ok)throw Error('当前画面读取失败，请重试');
var blob=await r.blob(),url=URL.createObjectURL(blob),im=new Image();
try{await new Promise(function(resolve,reject){im.onload=resolve;im.onerror=reject;im.src=url;});}finally{URL.revokeObjectURL(url);}
if(serial!==this.requestSerial||!this.open)return;
this.image=im;
var overlay=this.$parent.$refs.boxOverlay;
var row=overlay&&window.REPLAY_BOXES.frameAt(overlay.frames,this.t);
if(row&&row.ball&&overlay.width&&overlay.height)this.boxes=[{kind:'detected',xyxy:[row.ball[0]/overlay.width,row.ball[1]/overlay.height,row.ball[2]/overlay.width,row.ball[3]/overlay.height]}];
this.$nextTick(this.paint);
}catch(e){if(serial===this.requestSerial)this.error=e.message||'画面加载失败';}
finally{if(serial===this.requestSerial)this.loading=false;}
},
paint:function(){var c=this.$refs.canvas;if(!c||!this.image)return;c.width=this.image.width;c.height=this.image.height;var ctx=c.getContext('2d');ctx.drawImage(this.image,0,0);var w=c.width,h=c.height;this.boxes.forEach(function(b){var p=b.xyxy;ctx.strokeStyle=b.kind==='decoy'?'#ff776c':b.kind==='ball'?'#59dd98':'#ffd45c';ctx.lineWidth=Math.max(2,w/450);ctx.strokeRect(p[0]*w,p[1]*h,(p[2]-p[0])*w,(p[3]-p[1])*h);});},
point:function(e){var r=this.$refs.canvas.getBoundingClientRect();return [Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))];},
down:function(e){if(!this.image||this.busy)return;this.start=this.point(e);this.$refs.canvas.setPointerCapture(e.pointerId);},
up:function(e){if(!this.start)return;var a=this.start,b=this.point(e);this.start=null;
if(Math.abs(a[0]-b[0])<0.006&&Math.abs(a[1]-b[1])<0.006){var hit=this.boxes.find(function(q){var p=q.xyxy;return a[0]>=p[0]&&a[0]<=p[2]&&a[1]>=p[1]&&a[1]<=p[3];});if(hit)hit.kind='decoy';}
else this.boxes.push({kind:this.mode,xyxy:[Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.max(a[0],b[0]),Math.max(a[1],b[1])]});this.paint();},
undo:function(){this.boxes.pop();this.paint();},
save:async function(){var boxes=this.boxes.filter(function(b){return b.kind!=='detected';});if(!boxes.length){this.error='请点掉误检黄框，或拖框补上篮球';return;}this.busy=true;this.error='';try{var r=await fetch(window.API.base+'/api/games/'+encodeURIComponent(this.jobId)+'/ball-feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({t:this.t,boxes:boxes,conditions:this.conditions})});var d=await r.json();if(!r.ok||!d.saved)throw Error(d.detail||'保存失败');this.open=false;this.$message.success('纠正已保存，待整帧审核；不改变本场统计');}catch(e){this.error=e.message||'保存失败，请重试';}finally{this.busy=false;}}
},
template:'<div style="margin-top:10px"><el-button size="small" :disabled="!jobId" @click="begin">纠正篮球识别</el-button><el-dialog v-model="open" title="纠正当前画面的篮球" width="min(940px, 96vw)" :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy"><p>点黄框标为误检；拖框补上篮球。仅保存纠正，不改比分。</p><p class="hint">这是局部纠错，不代表整帧完整标注；审核人确认整帧后才能用于训练。</p><el-radio-group v-model="mode" size="small"><el-radio-button value="ball">框出篮球</el-radio-button><el-radio-button value="decoy">框出误检物体</el-radio-button></el-radio-group><el-button size="small" :disabled="busy || !boxes.length" @click="undo">撤销最后一框</el-button><el-checkbox-group v-model="conditions" style="margin-top:10px"><el-checkbox value="far_small">远景小球</el-checkbox><el-checkbox value="motion_blur">运动模糊</el-checkbox><el-checkbox value="occluded">遮挡</el-checkbox><el-checkbox value="held_ball">持球</el-checkbox><el-checkbox value="logo_decoy">队徽/logo误检</el-checkbox><el-checkbox value="scoreboard_decoy">比分牌误检</el-checkbox><el-checkbox value="head_decoy">人头误检</el-checkbox></el-checkbox-group><p v-if="loading" role="status">正在读取画面…</p><canvas v-show="image" ref="canvas" style="display:block;width:100%;height:auto;touch-action:none;cursor:crosshair;margin-top:12px" aria-label="拖动框选篮球或误检物体" @pointerdown="down" @pointerup="up" @pointercancel="start=null"></canvas><p role="status">已标篮球 {{ boxes.filter(b=>b.kind===\'ball\').length }} 个，误检 {{ boxes.filter(b=>b.kind===\'decoy\').length }} 个</p><el-alert v-if="error" :title="error" type="error" :closable="false"/><template #footer><el-button :disabled="busy" @click="open=false">取消</el-button><el-button type="primary" :loading="busy" :disabled="loading || !image" @click="save">保存纠正</el-button></template></el-dialog></div>'
};
})();
