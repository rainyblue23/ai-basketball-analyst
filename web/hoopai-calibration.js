(() => {
  const $=id=>document.getElementById(id), params=new URLSearchParams(location.search), videoPath=params.get('video'), base=(params.get('api')||location.origin).replace(/\/+$/,'');
  const endpoint=base+'/api/calibrate', canvas=$('court'),ctx=canvas.getContext('2d');
  const v=$('video');
  // 每个点都记录"它对应哪个地面标志点"，因此可以只点看得见的那些（≥4 个）
  let points=[],names=[],landmarks=[],lines=[],pictures=[],revision=0,img=null,busy=false,ticket=0;
  let profiles=[], profileId="", hoopError=null;
  let captureTime=null, usingLive=false, lastQuality=null;
  $('back').href='./index.html?api='+encodeURIComponent(base)+'#/upload';
  function leave(){if(window.parent!==window){window.parent.postMessage({type:'hoopai-calibration-saved'},location.origin);}else{location.href=$('back').href;}}
  $('back').onclick=e=>{if(window.parent!==window){e.preventDefault();leave();}};
  const label=n=>{const l=landmarks.find(x=>x.name===n);return l?l.label:n;};
  const invalidate=()=>{lines=[];lastQuality=null;$('aligned').checked=false;$('aligned').disabled=true;draw();};

  // 四步流程的显隐：让使用者随时知道"现在在第几步、下一步按哪个按钮"
  function syncSteps(){
    const hasPic=!!img, enough=points.length>=4, previewed=lines.length>0;
    const state=[hasPic, hasPic&&enough, previewed, previewed&&$('aligned').checked&&$('fixed').checked];
    ['step1','step2','step3','step4'].forEach((id,i)=>{
      const el=$(id); if(!el) return;
      el.className = state[i] ? 'done' : (state.slice(0,i).every(Boolean) ? 'on' : '');
    });
    const need=[];
    if(!previewed) need.push('先点「③ 预览球场线」');
    if(!$('fixed').checked) need.push('勾选「这段视频全程固定」');
    if(previewed&&!$('aligned').checked) need.push('勾选「黄线已核对」');
    $('why').textContent = need.length ? ('保存前还需要：' + need.join('；')) : '可以保存了。';
  }
  function draw(){
    ctx.clearRect(0,0,canvas.width,canvas.height);
    if(img)ctx.drawImage(img,0,0,canvas.width,canvas.height);
    ctx.lineWidth=Math.max(2,canvas.width/450);ctx.strokeStyle='#ffe079';
    lines.forEach(line=>{ctx.beginPath();line.forEach((p,i)=>ctx[i?'lineTo':'moveTo'](p[0]*canvas.width,p[1]*canvas.height));ctx.stroke();});
    points.forEach((p,i)=>{ctx.fillStyle='#f4bd5f';ctx.beginPath();ctx.arc(p[0]*canvas.width,p[1]*canvas.height,9,0,Math.PI*2);ctx.fill();
      ctx.fillStyle='white';ctx.font='20px sans-serif';ctx.fillText(String(i+1),p[0]*canvas.width+12,p[1]*canvas.height);});
    $('picked').innerHTML = points.length
      ? '已点：' + points.map((_,i)=>'<b>'+(i+1)+'</b> '+label(names[i])).join(' ｜ ')
      : '还没点任何点。';
    $('step').textContent = points.length<4
      ? ('还需要至少 '+(4-points.length)+' 个点（第 '+(points.length+1)+' 个将要标：'+label($('landmark').value)+'）')
      : (lines.length ? '黄线已画出：贴合就进第 ④ 步确认保存；不贴合就重新点选。'
                      : '已够 4 个点 —— 点下面蓝色的「③ 预览球场线」画线检查。');
    $('preview').disabled=busy||!img||points.length<4;
    $('save').disabled=busy||!lines.length||!$('aligned').checked||!$('fixed').checked;
    ['capture','picture','landmark','undo','reset','fixed','profile','profileName'].forEach(id=>{const e=$(id);if(e)e.disabled=busy;});
    $('quality').textContent = lastQuality===null ? '' : ('重投影误差 '+lastQuality+' 像素；篮筐独立校验：'+(hoopError==null?'暂无结果':hoopError+' 米')+'。误差小不代表点名正确，请核对黄线。');
    syncSteps();
  }
  const say=(text,bad)=>{$('status').textContent=text;$('status').style.color = bad ? '#FCD34D' : '#22C55E';};
  async function json(url,options){const r=await fetch(url,options);const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'请求失败，请刷新后重试');return d;}
  async function request(method,body){
    const query='?video_path='+encodeURIComponent(videoPath);
    if(method==='GET'){
      const [model,saved,frames]=await Promise.all([json(base+'/api/hoopai/court'),json(endpoint+query),json(base+'/api/frames'+query+'&n=6').catch(()=>({frames:[]}))]);
      pictures=frames.frames||[];
      if(saved.court_model!=='hoopai'){delete saved.normalized_points;delete saved.point_names;}
      return {...model,saved,pictures,video:base+'/api/video'+query};
    }
    if(new Set(body.point_names).size!==body.point_names.length)throw Error('同一个标志点不能重复；再次点击同名点可以调整位置');
    const landmarks=Object.fromEntries(body.point_names.map((n,i)=>[n,body.points[i]]));
    const d=await json(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({video_path:videoPath,court_model:'hoopai',fixed_camera:body.fixed_camera,at:body.capture_time_s??0,landmarks,profile_id:profileId||null,save_profile_name:$('profileName').value||null,overlay_confirmed:$('aligned').checked,confirm:body.confirm,revision})});
    if(!d.ok || (body.confirm&&!d.saved))throw Error(d.note||'标定未保存，请调整点位');
    return d;
  }
  function setImage(src,w,h){Array.from($('profile').options).forEach(o=>{const p=profiles.find(p=>p.id===o.value);if(p)o.hidden=p.frame_size[0]!==w||p.frame_size[1]!==h;});img=src;canvas.width=w;canvas.height=h;draw();}
  async function loadPicture(){const t=++ticket;img=null;usingLive=false;captureTime=pictures[Number($('picture').value)]?.t??null;invalidate();
    const next=new Image();next.onload=()=>{if(t!==ticket)return;setImage(next,next.naturalWidth,next.naturalHeight);};next.onerror=()=>{say('画面加载失败，请刷新', true);};const p=pictures[Number($('picture').value)];if(p)next.src=p.image;}
  // 现场截帧：把当前播放位置那一帧画到离屏 canvas，作为标定底图（服务端只收归一化点位 + 时刻）
  $('capture').onclick=()=>{if(v.readyState<2){say('原片还没加载好，请稍等或先播放一下', true);return;}
    ++ticket;v.pause();const c=document.createElement('canvas');c.width=v.videoWidth;c.height=v.videoHeight;
    c.getContext('2d').drawImage(v,0,0);points=[];names=[];usingLive=true;captureTime=v.currentTime;
    setImage(c,c.width,c.height);invalidate();
    say('已截取 '+captureTime.toFixed(2)+' 秒这一帧，可以开始点选了。');};
  canvas.onclick=e=>{if(busy||!img)return;profileId='';$('profile').value='';const r=canvas.getBoundingClientRect();
    const name=$('landmark').value, point=[(e.clientX-r.left)/r.width,(e.clientY-r.top)/r.height], index=names.indexOf(name);
    if(index>=0)points[index]=point;else{points.push(point);names.push(name);}
    const next=landmarks.find(l=>!names.includes(l.name));if(next)$('landmark').value=next.name;invalidate();};
  $('picture').onchange=()=>{points=[];names=[];loadPicture();};
  $('undo').onclick=()=>{points.pop();names.pop();invalidate();};
  $('reset').onclick=()=>{profileId='';$('profile').value='';points=[];names=[];invalidate();};
  $('fixed').onchange=()=>{draw();};$('aligned').onchange=draw;$('landmark').onchange=draw;
  async function submit(confirm){busy=true;draw();try{
    const body={points,point_names:names,fixed_camera:$('fixed').checked,confirm,revision,
                capture_time_s:captureTime,picture:Number($('picture').value)};
    const d=await request('POST',body);lines=d.lines;lastQuality=d.reproj_err_px;hoopError=d.hoop_error_m;
    if(confirm){leave();return;}
    $('aligned').disabled=false;$('aligned').checked=false;
    say('黄线已画出：请核对是否贴合真实球场线，然后到下面第 ④ 步勾选并保存。');
    $('confirmBox').scrollIntoView({block:'nearest'});}catch(e){say(e.message, true);}
    finally{busy=false;draw();}}
  $('preview').onclick=()=>submit(false);$('save').onclick=()=>submit(true);
  $('clear').onclick=async()=>{if(!confirm('移除这个视频已有的标定？'))return;busy=true;draw();try{const r=await fetch(endpoint+'?video_path='+encodeURIComponent(videoPath)+'&revision='+revision,{method:'DELETE'});if(!r.ok)throw Error('移除失败，标定可能已改变，请刷新');leave();}catch(e){say(e.message, true);busy=false;draw();}};
  $('profile').onchange=()=>{profileId=$('profile').value;const p=profiles.find(p=>p.id===profileId);points=p?p.normalized_points.map(x=>x.slice()):[];names=p?p.point_names.slice():[];invalidate();say('请在当前视频预览黄线，确认机位没有移动、缩放或裁剪后保存。');};
  (async()=>{try{const d=await request('GET');
      profiles=((await json(base+'/api/camera_profiles')).profiles||[]).filter(p=>p.court_model==='hoopai');
      profiles.forEach(p=>{const o=document.createElement('option');o.value=p.id;o.textContent=p.name;$('profile').append(o);});
      pictures=d.pictures||[];landmarks=d.landmarks||[];revision=d.saved?.revision||0;
      if(d.video){v.src=d.video;}else{$('capture').disabled=true;}
      landmarks.forEach(l=>{const o=document.createElement('option');o.value=l.name;o.textContent=l.label;$('landmark').append(o);});
      const def=d.default_names||[];if(def.length)$('landmark').value=def[0];
      pictures.forEach((_,i)=>{const o=document.createElement('option');o.value=i;o.textContent='系统预览 '+(i+1)+'（'+pictures[i].t.toFixed(2)+' 秒）';$('picture').append(o);});
      if(d.saved?.normalized_points){points=d.saved.normalized_points;names=d.saved.point_names||def;
        $('fixed').checked=true;say('已有标定，可重新预览检查；返回会保留已保存标定。');}
      if(d.saved?.normalized_points && d.saved.capture_time_s!=null){
        const frame=await json(base+'/api/frame?video_path='+encodeURIComponent(videoPath)+'&at='+d.saved.capture_time_s);
        pictures.push({...frame,t:d.saved.capture_time_s});const o=document.createElement('option');o.value=pictures.length-1;o.textContent='已保存标定画面';$('picture').append(o);$('picture').value=o.value;
      }
      loadPicture();}catch(e){say(e.message, true);}})();draw();
})();
