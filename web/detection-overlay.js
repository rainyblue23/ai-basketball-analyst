/* 原视频检测框回放：仅显示保存的像素观测。 */
(function () {
  'use strict';
  function indexAt(frames, t) {
    var lo=0, hi=frames.length-1, found=-1;
    while(lo<=hi){var mid=(lo+hi)>>1;if(frames[mid].t<=t){found=mid;lo=mid+1;}else hi=mid-1;}
    return found;
  }
  function frameAt(frames,t){var i=indexAt(frames,t);return i>=0 && t-frames[i].t<=0.18 ? frames[i] : null;}
  function trailAt(frames,t){
    var i=indexAt(frames,t), points=[], next=null;
    if(!frameAt(frames,t)) return '';
    for(;i>=0 && t-frames[i].t<=0.5;i--){
      var f=frames[i];
      if(!f.ball || (next && (next.cut || next.segment!==f.segment || next.t-f.t>0.18)))break;
      points.unshift(((f.ball[0]+f.ball[2])/2)+','+((f.ball[1]+f.ball[3])/2));next=f;
      if(f.cut)break;
    }
    return points.length>1?points.join(' '):'';
  }
  window.REPLAY_BOXES={frameAt:frameAt,trailAt:trailAt};
  window.COMPONENTS=window.COMPONENTS||{};
  window.COMPONENTS['detection-overlay']={
    props:['jobId'],
    data:function(){return {identities:{},frames:[],width:0,height:0,row:null,trail:'',selectedPlayer:'',fps:0,enabled:true,playersOn:true,ballOn:true,rimOn:true,trailOn:false,status:'正在加载检测框…',available:false};},
    computed:{playerIds:function(){var ids=new Set();this.frames.forEach(function(f){(f.players||[]).forEach(function(p){if(p.id)ids.add(p.id);});});return Array.from(ids);}},
    watch:{jobId:function(){this.load();}},
    mounted:function(){this.load();this.tick();},
    beforeUnmount:function(){this.dead=true;this.serial=(this.serial||0)+1;if(this.abort)this.abort.abort();cancelAnimationFrame(this.raf);},
    methods:{
      load:async function(){
        var serial=this.serial=(this.serial||0)+1;this.frames=[];this.identities={};this.row=null;this.trail='';this.selectedPlayer='';this.available=false;
        if(this.abort)this.abort.abort();
        if(!this.jobId){this.status='';return;}
        this.status='正在加载检测框…';this.abort=new AbortController();
        try{
          var response=await fetch(window.API.base+'/api/games/'+encodeURIComponent(this.jobId)+'/detections',{signal:this.abort.signal});
          if(!response.ok)throw new Error('request');var data=await response.json();
          if(this.dead||serial!==this.serial)return;
          this.fps=Number(data.fps)||0;this.width=Number(data.width)||0;this.height=Number(data.height)||0;
          this.identities=data.identities||{};this.frames=Object.freeze(data.frames||[]);this.available=!!data.available;
          this.status=this.available?'':(data.reason||'这份任务没有检测框。');
        }catch(e){if(!this.dead&&serial===this.serial&&e.name!=='AbortError')this.status='检测框加载失败，请刷新重试。';}
      },
      tick:function(){
        if(this.dead)return;
        var video=this.$parent.$refs.video;
        if(video && this.available && this.enabled){
          this.row=frameAt(this.frames,video.currentTime);
          this.trail=this.trailOn&&this.ballOn?trailAt(this.frames,video.currentTime):'';
        }else{this.row=null;this.trail='';}
        this.raf=requestAnimationFrame(this.tick);
      },
      fullscreen:function(){var stage=this.$el.parentElement;if(stage.requestFullscreen)stage.requestFullscreen().catch(function(){});},
      selectPlayer:function(p){if(p.id)this.selectedPlayer=this.selectedPlayer===p.id?'':p.id;},
      ballLabel:function(row){return row.ball_suspect?'疑似球':'篮球';},
      playerLabel:function(p){return window.D.playerLabel(p);},
      boxLabel:function(p){
        var identity=this.identities[p.id]||{};
        var number=[p.jersey,identity.jersey].find(function(v){return v!=null && /^[0-9]{1,2}$/.test(String(v));});
        return number===undefined?'':String(number)+'号';
      },
      identityLabel:function(id){return window.D.playerLabel(this.identities[id]||{player_id:id});}
    },
    template:[
      '<div class="detection-overlay">',
      ' <svg v-if="available && enabled && row" class="detection-boxes" :viewBox="\'0 0 \'+width+\' \'+height" preserveAspectRatio="xMidYMid meet" aria-label="检测框">',
      '  <polyline v-if="trail" :points="trail" class="ball-tail" />',
      '  <g v-if="playersOn" v-for="(p,i) in row.players" :key="\'p\'+i" class="player-box" :class="{selected:selectedPlayer===p.id,dimmed:selectedPlayer && selectedPlayer!==p.id}" role="button" :tabindex="p.id ? 0 : -1" :aria-label="playerLabel(p)" :aria-pressed="selectedPlayer===p.id" @click="selectPlayer(p)" @keydown.enter.prevent="selectPlayer(p)" @keydown.space.prevent="selectPlayer(p)"><rect :x="p.box[0]" :y="p.box[1]" :width="p.box[2]-p.box[0]" :height="p.box[3]-p.box[1]" /><text v-if="boxLabel(p)" :x="p.box[0]+3" :y="Math.max(16,p.box[1]-5)">{{ boxLabel(p) }}</text></g>',
      '  <g v-if="ballOn && row.ball" class="ball-box" :class="{suspect:row.ball_suspect}"><rect :x="row.ball[0]" :y="row.ball[1]" :width="row.ball[2]-row.ball[0]" :height="row.ball[3]-row.ball[1]" /><text :x="row.ball[0]" :y="Math.max(16,row.ball[1]-5)">{{ ballLabel(row) }}</text></g>',
      '  <g v-if="rimOn && row.rim" class="rim-box"><rect :x="row.rim[0]" :y="row.rim[1]" :width="row.rim[2]-row.rim[0]" :height="row.rim[3]-row.rim[1]" /><text :x="row.rim[0]" :y="Math.max(16,row.rim[1]-5)">篮筐</text></g>',
      ' </svg>',
      ' <div v-if="available" class="detection-controls"><el-button size="small" plain @click="fullscreen">全屏标记</el-button><el-popover trigger="click" placement="bottom-end" :width="220"><template #reference><el-button size="small" plain>画面标记</el-button></template><div class="detection-options"><el-switch v-model="enabled" active-text="显示标记" /><el-checkbox v-model="playersOn">球员绿框</el-checkbox><el-checkbox v-model="ballOn">篮球黄框</el-checkbox><el-checkbox v-model="rimOn">篮筐青框</el-checkbox><el-checkbox v-model="trailOn">篮球短轨迹</el-checkbox><el-select v-model="selectedPlayer" clearable placeholder="全部球员" aria-label="高亮球员"><el-option v-for="id in playerIds" :key="id" :label="identityLabel(id)" :value="id" /></el-select><small>无检测的时刻不显示框。</small></div></el-popover></div>',
      ' <span v-else-if="status" class="detection-status">{{ status }}</span>',
      '</div>'
    ].join('')
  };

  function eventTime(e){return [e.review_t,e.crossing_t,e.decision_t,e.t].find(function(t){return typeof t==='number'&&Number.isFinite(t)&&t>=0;});}
  function stepTime(t,dir,fps,duration){if(!Number.isFinite(fps)||fps<=0)return t;return Math.max(0,Math.min(Math.max(0,duration-0.001),Math.round((t+dir/fps)*fps)/fps));}
  window.REPLAY_BOXES.eventTime=eventTime;window.REPLAY_BOXES.stepTime=stepTime;
  window.COMPONENTS['replay-tools']={
    props:['events','fps','jobId'],emits:['event'],
    data:function(){return {ready:false,rate:1,time:0,duration:0,sourceFps:0};},
    watch:{jobId:function(){this.rate=1;this.sourceFps=0;this.loadFps();}},
    mounted:function(){this.loadFps();this.tick();},
    beforeUnmount:function(){this.dead=true;cancelAnimationFrame(this.raf);if(this.abort)this.abort.abort();},
    computed:{
      effectiveFps:function(){var f=Number(this.fps)||this.sourceFps;return Number.isFinite(f)&&f>0?f:0;},
      markers:function(){var self=this;return (this.events||[]).map(function(e,i){return {row:e,index:i,t:eventTime(e)};}).filter(function(m){return (!m.row.type || m.row.type==='shot')&&m.t!==undefined&&(!self.duration||m.t<=self.duration);}).sort(function(a,b){return a.t-b.t;});}
    },
    methods:{
      loadFps:async function(){if(Number(this.fps)>0||!this.jobId)return;if(this.abort)this.abort.abort();this.abort=new AbortController();var id=this.jobId;try{var r=await fetch(window.API.base+'/api/games/'+encodeURIComponent(id)+'/detections',{signal:this.abort.signal});if(!r.ok)return;var d=await r.json();if(!this.dead&&id===this.jobId)this.sourceFps=Number(d.fps)||0;}catch(e){}},
      tick:function(){if(this.dead)return;var v=this.$parent.$refs.video;this.ready=!!(v&&v.readyState>=1);if(v){this.time=v.currentTime;this.rate=v.playbackRate;this.duration=Number.isFinite(v.duration)?v.duration:0;}this.raf=requestAnimationFrame(this.tick);},
      changeRate:function(value){var v=this.$parent.$refs.video;if(v){v.playbackRate=Number(value);this.rate=Number(value);}},
      step:function(dir){var v=this.$parent.$refs.video;if(!v||!this.ready||!this.effectiveFps)return;v.pause();v.currentTime=stepTime(v.currentTime,dir,this.effectiveFps,v.duration);},
      stamp:function(t){return Math.floor(t/60).toString().padStart(2,'0')+':'+Math.floor(t%60).toString().padStart(2,'0');},
      label:function(e){return window.D.shotDisplay(e).label;},
      resultClass:function(e){var d=window.D.shotDisplay(e);return d.resolved?(d.made?'made':'miss'):'';},
      select:function(m){this.$emit('event',m.row,m.index,true);}
    },
    template:[
      '<div class="replay-tools">',
      ' <div class="replay-actions"><el-button size="small" :disabled="!ready || !effectiveFps" @click="step(-1)">上一帧</el-button><el-button size="small" :disabled="!ready || !effectiveFps" @click="step(1)">下一帧</el-button><el-select :model-value="rate" @change="changeRate" :disabled="!ready" aria-label="播放速度" class="replay-rate"><el-option :value="0.25" label="0.25 倍" /><el-option :value="0.5" label="0.5 倍" /><el-option :value="1" label="正常速度" /></el-select><span class="replay-clock">{{ stamp(time) }}</span></div>',
      ' <div v-if="markers.length" class="replay-events" aria-label="投篮事件时间标记"><el-button v-for="m in markers" :key="m.index" size="small" :disabled="!ready" :class="{active:Math.abs(time-m.t)<1}" :aria-label="stamp(m.t)+\' \'+label(m.row)" @click="select(m)"><span>{{ stamp(m.t) }}</span><span v-if="label(m.row)" :class="[\'event-result\',resultClass(m.row)]">{{ label(m.row) }}</span></el-button></div>',
      '</div>'
    ].join('')
  };
})();
