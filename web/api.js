/* ==========================================================================
   api.js —— 后端接口封装 + WebSocket 进度推送 + 演示数据降级
   --------------------------------------------------------------------------
   后端契约（Base: http://127.0.0.1:8000）：
     POST /api/jobs                             建任务  {job_id}
     GET  /api/jobs/{job_id}                    任务状态（轮询兜底）
     WS   /api/jobs/{job_id}/ws                 任务状态（每帧同一份 job JSON）
     GET  /api/jobs                             最近 20 条任务
     GET  /api/games/{job_id}                   game.json
     GET  /api/games/{job_id}/players           players.json
     GET  /api/games/{job_id}/shotchart         shotchart.json
     GET  /api/games/{job_id}/report            {markdown, json}
     GET  /api/games/{job_id}/highlights        {clips, index_url}
     GET  /api/games/{job_id}/export?fmt=...    csv_stats | csv_shots | json | report_md
     GET  /api/games/{job_id}/video             原始视频（支持 Range）
     GET  /api/media/{job_id}/{path}            高光片段等静态文件
     POST /api/games/{job_id}/shots/{i}/correct 人工复核改判 {made, value}
   --------------------------------------------------------------------------
   后端或历史读取失败时显示空状态。web/demo/ 静态合成产物仅在
   用户明确选择演示时加载，不能作为视频分析的自动替代。
   ========================================================================== */
(function () {
  'use strict';

  var qs = new URLSearchParams(location.search);
  var DEFAULT_BASE = location.protocol === 'file:' ? 'http://127.0.0.1:8000' : (location.origin || 'http://127.0.0.1:8000');

  var API = {
    // 后端地址：?api=http://host:port 可覆盖（方便换机演示）
    base: (qs.get('api') || DEFAULT_BASE).replace(/\/+$/, ''),
    // 演示数据目录（相对本页，兼容 file:// 与任意静态托管路径）
    demoDir: './demo/',
    lastError: '',
    probeDetail: ''
  };

  API.isFileProtocol = location.protocol === 'file:';

  // ------------------------------------------------------------------
  // 底层 fetch
  // ------------------------------------------------------------------
  function withTimeout(ms) {
    // 老浏览器没有 AbortController 时退化为「不超时」
    if (typeof AbortController === 'undefined') return { signal: undefined, done: function () {} };
    var ctl = new AbortController();
    var timer = setTimeout(function () { ctl.abort(); }, ms);
    return { signal: ctl.signal, done: function () { clearTimeout(timer); } };
  }

  API.getJSON = function (url, ms) {
    var t = withTimeout(ms || 20000);
    return fetch(url, { cache: 'no-store', signal: t.signal, headers: { 'Accept': 'application/json' } })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status + ' @ ' + url);
        return r.json();
      })
      .finally(t.done);
  };

  API.getText = function (url, ms) {
    var t = withTimeout(ms || 20000);
    return fetch(url, { signal: t.signal })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status + ' @ ' + url);
        return r.text();
      })
      .finally(t.done);
  };

  API.deleteJSON = function (url, ms) {
    var t = withTimeout(ms || 20000);
    return fetch(url, { method: 'DELETE', signal: t.signal })
      .then(function (r) {
        if (r.ok) return r.json();
        return r.json().catch(function () { return null; }).then(function (j) {
          var msg = (j && (j.detail || j.message)) || '';
          if (typeof msg !== 'string') { msg = JSON.stringify(msg); }
          throw new Error(msg || ('HTTP ' + r.status + ' @ ' + url));
        });
      })
      .finally(t.done);
  };

  API.postJSON = function (url, body, ms) {
    var t = withTimeout(ms || 30000);
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
      signal: t.signal
    }).then(function (r) {
      if (r.ok) return r.json();
      // 把服务端的 detail 带出来 —— 只显示 "HTTP 400" 等于没说，
      // 用户看到的是"保存不了"却不知道原因（实测踩过：
      // 后端明明回了"点共线或退化，请重新选点"，前端只显示 HTTP 400）。
      return r.json().catch(function () { return null; }).then(function (j) {
        var msg = (j && (j.detail || j.message)) || '';
        if (typeof msg !== 'string') { msg = JSON.stringify(msg); }
        throw new Error(msg || ('HTTP ' + r.status + ' @ ' + url));
      });
    }).finally(t.done);
  };

  // 演示数据里的静态文件（相对路径）
  function demo(path) { return API.demoDir + path; }

  // ------------------------------------------------------------------
  // 后端可用性探测：命中 /api/jobs（契约里的任务列表接口，最轻量）
  // ------------------------------------------------------------------
  API.probe = function () {
    return API.getJSON(API.base + '/api/jobs', 12000)
      .then(function (d) {
        API.lastError = '';
        API.probeDetail = 'GET /api/jobs 正常，返回 ' +
          (Array.isArray(d) ? d.length : Object.keys(d || {}).length) + ' 条任务';
        return true;
      })
      .catch(function (e) {
        API.lastError = (e && e.name === 'AbortError') ? '探测超时（后端没起来）' : String(e && e.message || e);
        API.probeDetail = API.isFileProtocol
          ? '当前为 file:// 打开，浏览器会拦截本地文件/接口读取'
          : API.lastError;
        return false;
      });
  };

  // ------------------------------------------------------------------
  // 任务：创建 / 查询 / 列表 / WS 订阅
  // ------------------------------------------------------------------
  API.createJob = function (payload) {
    return API.postJSON(API.base + '/api/jobs', payload);
  };

  /** 分块上传，每块 1 MB、最多 3 块并行；网络中断仅重试当前块。
   * 服务端确认完整视频落盘后才返回分析可用的 path。
   */
  API.uploadVideo = function (file, onProgress) {
    if (!file.size) return Promise.reject(new Error('视频文件为空'));
    var random = new Uint8Array(16);
    crypto.getRandomValues(random);
    var id = Array.from(random).map(function (v) { return v.toString(16).padStart(2,'0'); }).join('');
    var size = 1024 * 1024, cursor = 0, complete = null;
    var progress = {};
    function report() {
      var sum = Object.keys(progress).reduce(function (n,k) { return n+progress[k]; },0);
      if (onProgress) onProgress(Math.min(.99,sum/file.size));
    }
    function sendChunk(offset, end) {
      return new Promise(function (resolve, reject) {
        var xhr = new XMLHttpRequest();
        xhr.open('POST', API.base + '/api/upload/chunk');
        xhr.withCredentials = true;
        xhr.timeout = 90000;
        xhr.setRequestHeader('Content-Type', 'application/octet-stream');
        xhr.setRequestHeader('x-filename', encodeURIComponent(file.name));
        xhr.setRequestHeader('x-upload-id', id);
        xhr.setRequestHeader('x-upload-offset', String(offset));
        xhr.setRequestHeader('x-upload-size', String(file.size));
        xhr.setRequestHeader('x-upload-part-size', String(size));
        xhr.upload.onprogress = function (e) {
          if (e.lengthComputable) { progress[offset]=e.loaded; report(); }
        };
        xhr.onload = function () {
          if (xhr.status >= 200 && xhr.status < 300) {
            try { resolve(JSON.parse(xhr.responseText)); }
            catch (e) { reject(new Error('上传响应无效')); }
          } else {
            var error = new Error(xhr.status===401 ? '登录已过期，请重新登录后上传' :
              '上传失败（HTTP '+xhr.status+'）：'+String(xhr.responseText).slice(0,160));
            error.retryable = xhr.status>=500 || xhr.status===408 || xhr.status===429;
            reject(error);
          }
        };
        xhr.onerror = xhr.ontimeout = function () {
          var error = new Error('当前视频块传输中断，请检查网络后重试');
          error.retryable = true; reject(error);
        };
        xhr.onabort = function () { reject(new Error('上传已取消')); };
        xhr.send(file.slice(offset, end));
      });
    }
    function uploadPart(offset) {
      var end = Math.min(file.size,offset+size), retries = 0;
      function attempt() {
        return sendChunk(offset,end).catch(function (error) {
          if (!error.retryable || retries>=3) throw error;
          retries++;
          progress[offset]=0; report();
          return new Promise(function (resolve) { setTimeout(resolve,500*retries); }).then(attempt);
        });
      }
      return attempt().then(function (r) {
        progress[offset]=end-offset; report();
        if (r.complete) complete=r;
      });
    }
    function worker() {
      if (cursor >= file.size) return Promise.resolve();
      var offset=cursor; cursor+=size;
      return uploadPart(offset).then(worker);
    }
    return Promise.all([worker(),worker(),worker()]).then(function () {
      if (!complete || !complete.path || complete.bytes!==file.size) throw new Error('视频尚未完整保存，请重试');
      if (onProgress) onProgress(1);
      return complete;
    });
  };

  /** 后端能力探测：GET /api/health → {ok, ffmpeg, ultralytics, opencv, jobs} */
  API.health = function () {
    return API.getJSON(API.base + '/api/health', 3000);
  };

  /** 复核队列（后端可选接口）：GET /api/games/{id}/review */
  API.review = function (jobId) {
    return API.getJSON(API.base + '/api/games/' + jobId + '/review');
  };

  /** LLM 润色战报（可选）：POST /api/games/{id}/report/llm */
  API.reportLlm = function (jobId) {
    return API.postJSON(API.base + '/api/games/' + jobId + '/report/llm');
  };

  API.getJob = function (id) {
    return API.getJSON(API.base + '/api/jobs/' + encodeURIComponent(id));
  };
  /* 任务列表。includeSynthetic=true 时把**合成/演示任务**也算进来 ——
     战术页在"当前任务没有战术产物"时要靠它去找一个真有战术数据的任务
     （合成数据源自带战术层，用户第一次打开战术页就能看到结果，不用先跑真视频）。 */
  API.listJobs = function (includeSynthetic) {
    return API.getJSON(API.base + '/api/jobs' +
      (includeSynthetic ? '?include_synthetic=true' : ''), 5000);
  };

  /**
   * 订阅任务进度：优先 WebSocket（每帧推送完整 job JSON）。
   * 返回 { close() }，后端不可用/WSS 连接失败时自动切到 1.2s 轮询。
   */
  API.watchJob = function (id, onFrame, onError) {
    var stopped = false, ws = null, timer = null;

    function poll() {
      if (stopped) return;
      API.getJob(id).then(function (j) {
        if (stopped) return;
        onFrame(j);
        if (j.status === 'done' || j.status === 'error') return;
        timer = setTimeout(poll, 1200);
      }).catch(function (e) {
        if (stopped) return;
        if (onError) onError(e);
        timer = setTimeout(poll, 2000);
      });
    }

    try {
      var wsUrl = API.base.replace(/^http/, 'ws') + '/api/jobs/' + encodeURIComponent(id) + '/ws';
      ws = new WebSocket(wsUrl);
      ws.onmessage = function (ev) {
        if (stopped) return;
        try { onFrame(JSON.parse(ev.data)); } catch (e) { /* 非 JSON 帧忽略 */ }
      };
      ws.onerror = function () {
        if (stopped) return;
        if (onError) onError(new Error('WebSocket 不可用，已切换轮询'));
        try { ws.close(); } catch (e) {}
        ws = null;
        poll();
      };
      ws.onclose = function () { /* 任务结束时后端会主动关闭，无需处理 */ };
    } catch (e) {
      poll();
    }

    return {
      close: function () {
        stopped = true;
        if (timer) clearTimeout(timer);
        if (ws) { try { ws.close(); } catch (e) {} }
      }
    };
  };

  // ------------------------------------------------------------------
  // 比赛产物：这些接口在演示模式下走 web/demo/*.json
  // ------------------------------------------------------------------
  /**
   * 判断后端给的片段路径能否直接作为浏览器 URL。
   * 后端返回的可能是绝对文件系统路径（Windows 的 D:\... 或 /home/...），
   * 这类路径浏览器无法访问，必须走 /api/media/{job_id}/{path} 或原始视频。
   */
  API.isWebPath = function (p) {
    p = String(p || '');
    if (!p) return false;
    if (/^[a-zA-Z]:[\\/]/.test(p)) return false;   // D:\out\highlights\a.mp4
    if (p.charAt(0) === '/') return false;         // /home/user/out/highlights/a.mp4
    if (/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(p)) return true;  // http(s)://
    return true;                                    // 相对路径
  };

  API.game = function (jobId) {
    return API.getJSON(API.base + '/api/games/' + jobId);
  };
  API.players = function (jobId) {
    return API.getJSON(API.base + '/api/games/' + jobId + '/players');
  };
  API.shotchart = function (jobId) {
    return API.getJSON(API.base + '/api/games/' + jobId + '/shotchart');
  };
  API.report = function (jobId) {
    return API.getJSON(API.base + '/api/games/' + jobId + '/report');
  };
  API.highlights = function (jobId) {
    return API.getJSON(API.base + '/api/games/' + jobId + '/highlights');
  };
  /** 战术层结论（控球/传球网络/阵型/空间） */
  API.tactics = function (jobId) {
    // 带时间戳：战术数据会被"重算战术层"原地覆盖，URL 不变的话浏览器会拿旧缓存
    return API.getJSON(API.base + '/api/games/' + jobId + '/tactics?_=' +
      Date.now(), 30000);
  };
  /** 俯视战术图逐帧数据（比较大，只在打开战术页时才拉） */
  API.tacticsFrames = function (jobId) {
    return API.getJSON(API.base + '/api/games/' + jobId +
      '/tactics/frames?_=' + Date.now(), 60000);
  };
  API.correctShot = function (jobId, index, payload) {
    return API.postJSON(API.base + '/api/games/' + jobId + '/shots/' + index + '/correct', payload);
  };
  API.addManualShot = function (jobId, payload) {
    return API.postJSON(API.base + '/api/games/' + jobId + '/shots/add', payload);
  };
  // 注意：这里原来叫 API.videoUrl(jobId)，而文件后面**又**定义了一个
  // API.videoUrl(videoPath)（标定页用），后一个把前一个覆盖掉 —— 于是总览页/高光页
  // 传 jobId 进去得到 `/api/video?video_path=<jobId>` 这种永远打不开的地址（实测发现）。
  // 现在拆成两个名字，各管一种入参：
  //   jobVideoUrl(jobId)  → /api/games/{jobId}/video  （按任务取原视频）
  //   videoUrl(videoPath) → /api/video?video_path=... （按文件路径取，标定页用）
  API.jobVideoUrl = function (jobId) { return API.base + '/api/games/' + jobId + '/video'; };
  API.mediaUrl = function (jobId, path) {
    return API.base + '/api/media/' + jobId + '/' + String(path).replace(/^\/+/, '');
  };
  API.exportUrl = function (jobId, fmt) {
    return API.base + '/api/games/' + jobId + '/export?fmt=' + fmt;
  };
  /** 重切高光片段（按已保存的时间码 + 源视频，不重新推理） */
  API.regenerateHighlights = function (jobId) {
    return API.postJSON(API.base + '/api/games/' + jobId + '/export/highlights', {});
  };
  /** 取视频某一秒的一帧（给「在画面上标点」用） */
  API.getFrame = function (videoPath, at) {
    return API.getJSON(API.base + '/api/frame?video_path=' +
      encodeURIComponent(videoPath) + '&at=' + encodeURIComponent(at == null ? 1 : at), 30000);
  };
  /** 保存画面标点（归一化坐标） */
  API.saveMarks = function (payload) {
    return API.postJSON(API.base + '/api/marks', payload);
  };
  /** 读回某视频已保存的标点 */
  API.getMarks = function (videoPath) {
    return API.getJSON(API.base + '/api/marks?video_path=' +
      encodeURIComponent(videoPath), 10000);
  };
  /** 某次分析里被判成进球的时刻（给「进球确认」用） */
  API.candidates = function (jobId) {
    return API.getJSON(API.base + '/api/games/' + jobId + '/candidates', 15000);
  };
  /** 提交「进没进」的人工判断（过滤误报 + 攒训练数据） */
  API.postFeedback = function (videoPath, items) {
    return API.postJSON(API.base + '/api/feedback',
      { video_path: videoPath, items: items });
  };
  /** 读回某视频的历史判断 */
  API.getFeedback = function (videoPath) {
    return API.getJSON(API.base + '/api/feedback' +
      (videoPath ? '?video_path=' + encodeURIComponent(videoPath) : ''), 10000);
  };
  /* 「训练标注」页已于 2026-10-05 按用户要求下线：下面这 4 个 label* 方法暂时没有
     页面在调用。**后端 /api/label/* 接口仍然保留**（命令行、脚本、以后恢复页面都能用），
     所以这里也一并留着，不做删除。页面文件备份在 _tmp/merge/backup/train.js.removed。 */
  /** 训练标注：读候选列表（candidates.json） */
  API.labelCandidates = function (path) {
    return API.getJSON(API.base + '/api/label/candidates?path=' +
      encodeURIComponent(path), 30000);
  };
  /** 训练标注：第 idx 个候选的证据图 URL（可直接给 <img src>） */
  API.labelSheetUrl = function (path, idx) {
    return API.base + '/api/label/sheet?path=' + encodeURIComponent(path) +
      '&idx=' + idx + '&_=' + Date.now();
  };
  /**
   * 训练标注：第 idx 个候选的**放大慢放视频** URL（给 <video src>）。
   * 用户明确说逐帧拼图看不懂，要视频 —— 所以默认走这个。
   */
  API.labelClipUrl = function (path, idx, zoom, slow) {
    return API.base + '/api/label/clip?path=' + encodeURIComponent(path) +
      '&idx=' + idx + '&zoom=' + (zoom || 4) + '&slow=' + (slow || 3) +
      '&_=' + Date.now();
  };
  /** 训练标注：记录一条「进没进」 */
  API.labelOne = function (payload) {
    return API.postJSON(API.base + '/api/label/labeled', payload);
  };
  /** 球场特征点清单（点几个就能标定这段视频的球场） */
  API.courtLandmarks = function () {
    return API.getJSON(API.base + '/api/court_landmarks', 10000);
  };
  /** 用球场特征点标定（>=4 个点） */
  API.saveCourtMarks = function (payload) {
    return API.postJSON(API.base + '/api/calibrate', payload);
  };
  /** 这段视频是否已有标定 */
  API.getCalibration = function (videoPath) {
    return API.getJSON(API.base + '/api/calibrate?video_path=' +
      encodeURIComponent(videoPath), 10000);
  };
  /** 撤销这段视频的标定（标错了要能重来；revision 做乐观锁） */
  API.deleteCalibration = function (videoPath, revision) {
    return API.deleteJSON(API.base + '/api/calibrate?video_path=' +
      encodeURIComponent(videoPath) + '&revision=' + (revision || 0));
  };
  /** 原片的播放地址（给标定页的 <video> 用；后端支持 Range 才能拖动定位） */
  API.videoUrl = function (videoPath) {
    return API.base + '/api/video?video_path=' + encodeURIComponent(videoPath);
  };
  API.markVideoUrl = function (videoPath) {
    return API.base + '/api/mark-video?video_path=' + encodeURIComponent(videoPath);
  };
  /** 机器上现成的视频清单（示例素材 + 已上传）—— 新手上手第一步用 */
  API.samples = function () {
    return API.getJSON(API.base + '/api/samples', 20000);
  };
  /** 随机抽 N 个画面（多画面标定用）。给了 center 就抽那一时刻附近的帧
   *  —— 这几帧属于同一镜头，标点才能叠加到同一坐标系。 */
  API.getFrames = function (videoPath, n, center, span) {
    var u = API.base + '/api/frames?video_path=' +
      encodeURIComponent(videoPath) + '&n=' + (n || 6);
    if (center !== undefined && center !== null && center >= 0) {
      u += '&center=' + encodeURIComponent(center) +
           '&span=' + encodeURIComponent(span || 3);
    }
    return API.getJSON(u, 60000);
  };
  /** 自动挑两帧"同一镜头"的画面（标定页用）。
   *  为什么需要后端做：判定镜头有没有切要算 ORB 内点率，浏览器里做不了。
   *  两帧必须在同一镜头，合并解才成立（实测用户取到两个镜头 -> 必然矛盾）。 */
  API.framesStable = function (videoPath, n) {
    return API.getJSON(API.base + '/api/frames_stable?video_path=' +
      encodeURIComponent(videoPath) + '&n=' + (n || 8), 120000);
  };
  /** 多画面累加解标定（并返回逐个点误差） */
  API.calibrateAuto = function (payload) {
  return postJSON('/api/calibrate_auto', payload);
};
API.calibrateMulti = function (payload) {
    // ⚠️ 单独给 120 秒（默认是 30 秒）。为什么：这条路要做"按镜头分组 + 逐段解算"，
    // 最坏情况还要抓几帧、算几次 ORB —— 实测一次正常的跨镜头标定可以到 40 秒以上。
    // 30 秒的上限会让浏览器先放弃，用户看到的是"解算失败：后端算太久被浏览器中断了"，
    // 而后端其实还在算（甚至已经存好了）—— 用户却以为标定失败了（实测踩到）。
    return API.postJSON(API.base + '/api/calibrate_multi', payload, 120000);
  };

  /* ---- 比分牌：自动定位 / 手动框选 + OCR 读得分事件 ----
     为什么需要：模板匹配只认它标过的样式，非标准台标（校园/村 BA 的横条）
     读不出来；而"框出比分区域 + 放大 OCR"实测能稳定读出
     （这段素材读出 27:33 → 27:35 → 27:37 → 29:38，与画面逐帧一致）。
     返回里的 path 直接作为任务的 scoreboard_events 传给后端。 */
  API.scoreboardOcr = function (payload) {
    return API.postJSON(API.base + '/api/scoreboard/ocr', payload);
  };
  /** 这段视频是否已有 OCR 读出的得分事件（界面据此显示"已读比分牌"） */
  API.scoreboardEvents = function (videoPath) {
    return API.getJSON(API.base + '/api/scoreboard/events?video_path=' +
                       encodeURIComponent(videoPath), 8000);
  };

  // 演示模式下的高光片段：静态文件直接给链接
  API.demoMediaUrl = function (path) { return demo(String(path).replace(/^\/+/, '')); };

  // 演示模式下的战术产物（没有后端时战术页也能完整演示）
  API.demoTactics = function () {
    return API.getJSON(demo('tactics.json'), 15000)
      .catch(function () { return null; });
  };
  API.demoTacticsFrames = function () {
    return API.getJSON(demo('tactics_frames.json'), 30000)
      .catch(function () { return null; });
  };

  // ------------------------------------------------------------------
  // 演示数据加载（后端不可用时的完整降级路径）
  // ------------------------------------------------------------------
  API.loadDemo = function () {
    var missing = [];
    function soft(p) {
      return API.getJSON(demo(p), 6000).catch(function (e) { missing.push(p); API.lastError = String(e.message || e); return null; });
    }
    function softText(p) {
      return API.getText(demo(p), 6000).catch(function () { missing.push(p); return ''; });
    }
    return Promise.all([
      soft('game.json'),
      soft('players.json'),
      soft('shotchart.json'),
      soft('report.json'),
      softText('report.md'),
      soft('highlights.json')
    ]).then(function (r) {
      return {
        game: r[0],
        players: r[1],
        shotchart: r[2],
        report_json: r[3],
        reportMd: r[4],
        highlights: r[5],
        missing: missing
      };
    });
  };

  window.API = API;
})();
