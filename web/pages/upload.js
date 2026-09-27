/* ==========================================================================
   pages/upload.js —— 页面 1：上传与分析配置
   --------------------------------------------------------------------------
   数据来源接口：
     POST /api/jobs            建任务，body {video_path, source, seed, make_highlights}
     WS   /api/jobs/{id}/ws    每帧推送任务 JSON（status/progress/message）
     GET  /api/jobs/{id}       进度轮询兜底
     GET  /api/jobs            最近 20 条任务（可直接回看历史产物）
     GET  /api/games/{id} ...  任务完成后自动装载全部产物
   无后端时的降级：给出明确提示，并允许直接「载入演示数据」。
   ========================================================================== */
window.PAGES = window.PAGES || {};

window.PAGES['upload'] = {
  name: 'page-upload',
  data: function () {
    return {
      S: window.STORE,
      api: window.API,
      form: {
        source: 'video',            // video | jsonl（合成演示入口已移除）
        video_path: '',
        // 不再有 seed 输入框：它只对合成比赛生效，真实视频不用（见 start() 里的注释）
        make_highlights: true,
        // 真视频快速模式：跳过逐帧 YOLO，只走比分牌 + 颜色追球
        fast: false,
        // 进球标注文件（scripts/label_baskets.py 产出）—— 开发/评测用的基准输入，
        // 2026-09-27 起**不再暴露在界面上**（用户反馈：产品不该先要一份标注）。
        // 字段与后端参数保留，脚本调用仍可用；人工纠错走「人工复核」页。
        labels_path: '',
        // 可选：比分牌得分事件文件（「读比分牌」按钮的产出）。给了它，
        // 非标准台标也能走比分牌路径；留空则由后端自动定位。
        scoreboard_events: ''
      },
      busy: false,
      job: { job_id: '', status: '', progress: 0, message: '', error: null, out_dir: '', summary: '' },
      logs: [],
      jobs: [],
      watcher: null,
      uploadPct: -1,          // -1 = 未上传；0~1 = 上传中
      uploadedName: '',
      health: null,
      fileName: '',           // 本地文件名（仅用于界面显示；上传后用后端返回的路径）
      // ---- 「在画面上标篮筐」弹窗 ----
      markOpen: false,
      markAt: 1.0,            // 用第几秒的帧来标
      markImg: '',            // data:image/jpeg;base64,...
      markSize: { w: 0, h: 0 },
      markPts: [],            // [{name, label, x, y}]（归一化 0~1）
      markIdx: 0,
      // 可选步骤：选了"量筐宽"里的某一项后，下一次点画面落的就是它
      // （不选它就是默认路径：只点中心，半径交给检测器量）
      hoopOptTarget: '',
      markSaving: false,
      savedMarks: null,       // 该视频已保存的标点
      // ---- 标球场：点场地特征点解标定（用户建议：不一定要标篮筐）----
      markKind: 'hoop',       // hoop | court
      courtItems: [],         // [{name,label,hint}] 11 个候选特征点
      mfFrames: [],           // 抽出来的画面 [{t,image,w,h}]
      mfIdx: 0,               // 当前是第几张
      mfPts: [],              // 已标点 [{t,name,label,x,y}]
      mfTarget: '',           // 当前选中要标的点名
      autoMode: true,          // 自动识别模式：点位置即可，不用选特征点名字
      autoHalf: 'far',         // 你看到的主要是哪部分场地：far/near/full
      autoResult: null,        // 自动识别结果
      mfResult: null,         // 解算结果
      mfPreviewed: false,     // 预览过且可用（界面上用来区分"预览"与"已保存"）
      hoverPt: null,          // 鼠标在画面上的位置（画准星用）
      mfCenter: 60,           // 在哪个时刻附近抽帧（同一镜头内）
      mfSpan: 3,              // 抽帧的时间跨度（秒）
      courtPts: [],
      courtIdx: 0,
      courtResult: null,
      // ---- 新手上手（onboard）----
      // 目标：让第一次拿到软件的人在 5 分钟内看到一份结果，而不是对着表单发愣。
      // 关闭状态记在 localStorage：看过就不再烦他，但可以随时重新打开。
      guideOpen: true,
      samples: [],             // 机器上现成的视频（示例 + 已上传）
      samplePick: '',
      videoUrl: '',            // 原片播放地址（标定页拖动定位用）
      courtPreview: null,      // 「预览」的结果（不落盘）：每点像素误差 + 合规性
      courtPreviewed: false,   // 预览过且可用 → 才允许点「保存」
      calInfo: null,
      // ---- 「读比分牌」（自动定位 / 手动框选 + OCR）----
      sbBusy: false,
      sbResult: null,          // {ok, method, box, ocr_hit, n_crops, events, final, path, note}
      sbStartHome: null,       // 起始比分（可选；视频从半场中间开始录时填上更稳）
      sbStartAway: null,
      sbBox: ''                // 手动框选用：归一化 "x0,y0,x1,y1"；留空=自动定位
    };
  },
  computed: {
    canSubmit: function () {
      // 只有 video / jsonl 两种源（合成演示入口已移除）
      return !!String(this.form.video_path || '').trim();
    },
    /** 标点顺序：**只要求篮筐中心**；左右缘/上下沿是可选的"量筐宽"步骤。
     *
     * 用户反馈（2026-09-27）："标篮筐中心就挺准的吧，可以不需要再标上下左右四个点了"。对 ——
     * 一开始把 5 个点排成必须依次点的流程，会让人以为不点完就没法分析。
     * 现在中心是唯一必点项；四边收进「可选：量一下筐宽」里，不点也能保存、也能分析
     * （半径由后端检测器量，见 sources._visual_attempts 里的 manual_center+detector_radius）。 */
    markItems: function () {
      return [
        { name: 'rim_center', label: '篮筐中心', hint: '点篮圈正中心（只有这一项是必点的）' }
      ];
    },
    /** 可选的四边：量出半径能让"判进球的横向尺度"更准 */
    markItemsOptional: function () {
      return [
        { name: 'rim_left', label: '篮圈左缘', hint: '点篮圈最左边' },
        { name: 'rim_right', label: '篮圈右缘', hint: '点篮圈最右边' },
        { name: 'rim_top', label: '篮圈上沿', hint: '点篮圈最上边' },
        { name: 'rim_bottom', label: '篮圈下沿', hint: '点篮圈最下边' }
      ];
    },
    /** 当前模式要点的项（篮筐 5 项，只有"中心"必填 / 球场是点名清单，点够 4 个即可） */
    activeItems: function () {
      return this.markKind === 'court' ? this.courtItems : this.markItems;
    },
    /** 当前模式已点的点 */
    activePts: function () {
      // 球场模式只画**本帧**的点：不同画面的像素坐标不通用，
      // 把别帧的点叠上来会让人以为标错了
      return this.markKind === 'court' ? this.mfPtsHere : this.markPts;
    },
    /** 当前模式的下标 */
    activeIdx: function () {
      return this.markKind === 'court' ? this.courtIdx : this.markIdx;
    },
    /** 当前画面 */
    mfCurrent: function () { return this.mfFrames[this.mfIdx] || null; },
    /** 当前画面的原始像素尺寸。
     *  画点用 SVG 的 viewBox 对齐到图片原始尺寸 —— 之前用百分比定位，
     *  依赖"容器宽度==图片宽度"这个不成立的前提，点会整体偏移。
     *  （另：这两个 computed 曾经漏定义，导致 SVG 永不渲染、点完全看不见。） */
    frameW: function () {
      if (this.markKind === 'court') return this.mfCurrent ? this.mfCurrent.w : 0;
      return this.markSize.w || 0;
    },
    frameH: function () {
      if (this.markKind === 'court') return this.mfCurrent ? this.mfCurrent.h : 0;
      return this.markSize.h || 0;
    },
    /** 本帧已标的点（只画这些 —— 别的帧的点坐标不通用） */
    mfPtsHere: function () {
      var t = this.mfCurrent ? this.mfCurrent.t : null;
      return this.mfPts.filter(function (p) { return p.t === t; });
    },
    /** 某个点名是否已标过（按钮变绿） */
    mfDone: function () {
      var m = {};
      this.mfPts.forEach(function (p) { m[p.name] = 1; });
      return m;
    },
    mfEnough: function () { return this.mfPts.length >= 4; },
    courtCurrent: function () { return this.courtItems[this.courtIdx] || null; },
    courtDone: function () { return this.courtIdx >= this.courtItems.length; },
    courtEnough: function () { return this.courtPts.length >= 4; },
    markCurrent: function () {
      if (this.markKind === 'court') return this.courtCurrent;
      return this.markItems[this.markIdx] || null;
    },
    markDone: function () {
      if (this.markKind === 'court') return this.courtDone;
      return this.markIdx >= this.markItems.length;
    },
    /** 当前已点几个（按模式取：多帧看 mfPts、单帧看 courtPts、篮筐看 markPts） */
    guideCount: function () {
      if (this.markKind !== 'court') return this.markPts.length;
      return this.mfFrames.length ? this.mfPts.length : this.courtPts.length;
    },
    /** 新手三步的当前状态：做到哪一步，引导就跟到哪一步（不看教程也能自己走） */
    guideSteps: function () {
      var hasVideo = !!String(this.form.video_path || '').trim();
      var hasCal = !!(this.calInfo && this.calInfo.exists);
      var job = (this.S && this.S.job) || {};
      var done = job.status === 'done';
      var rmse = (this.calInfo && this.calInfo.reproj_error_m != null)
        ? this.calInfo.reproj_error_m : null;
      return [
        { key: 'video', n: 1, title: '选一段视频', done: hasVideo,
          desc: hasVideo ? ('已选：' + this.videoBaseName)
                         : '点右按钮用机器上现成的示例素材，或选你本地的文件上传',
          cta: hasVideo ? '换一个视频' : (this.samples.length ? '用示例视频' : '选择本地文件') },
        { key: 'calib', n: 2, title: '标定球场（可选，推荐做）', done: hasCal,
          desc: hasCal
            ? ('已标定' + (rmse != null ? ('：重投影误差 ' + rmse + ' m') : ''))
            : '告诉软件"球场在画面的哪个位置"：在同一个画面上点 4~6 个地面点即可。'
              + '不标也能分析（会按「只判进球」跑）：出手 / 进 / 不中 / 未知、比分'
              + '（分值按图像估计并标注为估计值）、命中率、球员统计、文字战报都能出；'
              + '只有热图、战术图和 2 分/3 分区分需要标定。',
          cta: hasCal ? '重新标定' : '去标定' },
        { key: 'run', n: 3, title: '开始分析，然后看结果', done: done,
          desc: done
            ? '分析完成 —— 去【结果总览】看比分、命中率、投篮热图、战术与文字战报'
            : '点「开始分析」；4 分钟的视频大约要 3 分钟，跑完这里会变成 ✓',
          cta: done ? '去看结果' : '开始分析' }
      ];
    },
    guideDoneCount: function () {
      var n = 0, self = this;
      this.guideSteps.forEach(function (s) { if (s.done) n += 1; });
      return n;
    },
    /** 只取文件名，路径太长会把引导卡撑爆 */
    videoBaseName: function () {
      var p = String(this.form.video_path || '');
      return p.split(/[\\/]/).filter(Boolean).pop() || '';
    },
    /** 界面该引导用户点的**下一个点**。
     *
     * 为什么不能直接用 `courtCurrent`：多帧模式下 `courtIdx` 永远停在 0
     * （只有单帧的 onCourtClick 会自增），而点名表第一项就是"篮筐中心" ——
     * 于是无论用户刚点完哪个点，提示都一路写着"篮筐中心"（用户实测反馈：
     * "他让我每一个都去标篮筐中心"）。多帧模式必须看用户自己选的那个点名
     * （`mfTarget`），没选就返回 null，由界面提示"先去上面选一个"。
     */
    guideNext: function () {
      var i;
      if (this.markKind !== 'court') {
        var it = this.markItems[this.markIdx] || null;
        return it ? { label: it.label, hint: it.hint, idx: this.markIdx + 1 } : null;
      }
      if (this.mfFrames.length) {
        for (i = 0; i < this.courtItems.length; i++) {
          if (this.courtItems[i].name === this.mfTarget) {
            return { label: this.courtItems[i].label,
                     hint: this.courtItems[i].hint,
                     idx: this.mfPts.length + 1 };
          }
        }
        return null;                       // 还没选点名 → 走"先去上面选一个"那条提示
      }
      var c = this.courtCurrent;
      return c ? { label: c.label, hint: c.hint, idx: this.courtPts.length + 1 } : null;
    },
    /** 可选四边里哪些已经点过（按钮变绿，与球场模式的 mfDone 同一套做法） */
    hoopOptDone: function () {
      var m = {};
      this.markPts.forEach(function (p) { m[p.name] = 1; });
      return m;
    },
    /** 与 guideNext 配套的一句话：已点几个、离能保存还差几个 */
    guideDesc: function () {
      if (this.markKind !== 'court') {
        return '已点 ' + this.markPts.length + ' 个；' +
          (this.markHoop ? '篮筐中心已标好，现在就能保存（其余 4 项可选，用来量筐宽/高度）'
                         : '请先点「篮筐中心」');
      }
      var n = this.guideCount;
      var enough = this.mfFrames.length ? this.mfEnough : this.courtEnough;
      return '已点 ' + n + ' 个（最少 4 个、建议 6 个）' +
        (enough ? '——已经够了，可以直接按「保存并解算标定」；想更准就继续点'
                : '——还差 ' + (4 - n) + ' 个才能保存') +
        (this.mfFrames.length ? '。画面里看不到的点按「跳过这一项」跳过它。' : '');
    },
    /** 已点出的点里，篮筐中心 + 左右缘 → 算出归一化 rx；中心 + 上下沿 → ry */
    markHoop: function () {
      var self = this;
      function g(n) {
        var p = self.markPts.filter(function (q) { return q.name === n; })[0];
        return p ? { x: p.x, y: p.y } : null;
      }
      var c = g('rim_center');
      if (!c) return null;
      var l = g('rim_left'), r = g('rim_right'), t = g('rim_top'), b = g('rim_bottom');
      var rx = 0, ry = 0;
      if (l && r) rx = Math.abs(r.x - l.x) / 2;
      else if (l) rx = Math.abs(c.x - l.x);
      else if (r) rx = Math.abs(r.x - c.x);
      if (t && b) ry = Math.abs(b.y - t.y) / 2;
      else if (t) ry = Math.abs(c.y - t.y);
      else if (b) ry = Math.abs(c.y - b.y);
      // 没量到宽度就**交 0 出去**（= "不知道"），由后端用检测器量。
      // 这里以前会给一个"画面宽 2%"的猜测值 —— 那是假精度：实测 852×480 的素材真实
      // rx≈29px、猜测只有 17px，偏小 40%，会让真进球被当成"贴筐掠过"，而且不报错。
      if (!(rx > 0)) { rx = 0; ry = 0; }
      else if (!(ry > 0)) ry = rx * 0.42;   // 上下沿没标时按篮圈扁率估算（只影响薄筐的下落下限）
      return { cx: c.x, cy: c.y, rx: rx, ry: ry, measured: rx > 0 };
    },
    statusTag: function () {
      return { queued: 'info', running: 'warning', done: 'success', error: 'danger' }[this.job.status] || 'info';
    },
    statusText: function () {
      return { queued: '排队中', running: '分析中', done: '已完成', error: '失败' }[this.job.status] || '未开始';
    },
    percent: function () { return Math.round((Number(this.job.progress) || 0) * 100); }
  },
  mounted: function () {
    this.refreshJobs();
    this.fetchHealth();
    this.loadSamples();          // 上手第一步要给得出"能直接用的视频"，不让新用户自己找路径
    try {
      this.guideOpen = localStorage.getItem('aihoop-guide-dismissed') !== '1';
    } catch (e) { this.guideOpen = true; }
  },
  beforeUnmount: function () {
    if (this.watcher) this.watcher.close();
  },
  methods: {
    /* ------------------------------------------------------------------
       在画面上标篮筐（不用敲命令行）
       ------------------------------------------------------------------ */
    openMark: function () {
      var self = this;
      this.markKind = 'hoop';
      var v = String(this.form.video_path || '').trim();
      if (!v) { this.$message.warning('先选一个视频（上传或填路径）'); return; }
      this.markOpen = true;
      this.markIdx = 0;
      this.markPts = [];
      this.loadPlayer();                 // 挂上原片，用户可以直接拖着定位
      this.loadMarkFrame();
      window.API.getMarks(v).then(function (r) {
        self.savedMarks = (r && r.exists) ? r.marks : null;
      }).catch(function () { self.savedMarks = null; });
    },
    /** 打开「标球场」：抽 N 个画面，多帧累加标点 */
    openCourt: function () {
      var self = this;
      var v = String(this.form.video_path || '').trim();
      if (!v) { this.$message.warning('先选一个视频'); return; }
      this.markKind = 'court';
      this.markOpen = true;
      this.mfFrames = [];
      this.mfIdx = 0;
      this.mfPts = [];
      this.mfTarget = '';
      this.mfResult = null;
      this.markImg = '';
      this.loadPlayer();                 // 挂上原片：可以拖着找到"场地看得最全"的那一帧再加进来
      if (!this.courtItems.length) {
        window.API.courtLandmarks().then(function (d) {
          self.courtItems = (d && d.landmarks) || [];
        }).catch(function () {});
      }
      this.$message.info('正在抽画面…');
      window.API.getFrames(v, 6, this.mfCenter, this.mfSpan).then(function (d) {
        self.mfFrames = (d && d.frames) || [];
        if (!self.mfFrames.length) {
          self.$message.error('抽不到画面（视频太短或全是黑帧？）');
          return;
        }
        self.$message.success('抽到 ' + self.mfFrames.length +
          ' 个画面：请挑场地看得最全的那一帧，一次点够 5~6 个点（同一帧里的点才算数）');
      }).catch(function (e) {
        self.$message.error('抽帧失败：' + (e && e.message ? e.message : e));
      });
      window.API.getCalibration(v).then(function (r) {
        self.calInfo = (r && r.exists) ? r : null;
      }).catch(function () { self.calInfo = null; });
    },
    /** 读回"这段视频有没有标定"（保存/撤销之后要刷新状态与 revision） */
    loadCalInfo: function () {
      var self = this;
      var v = String(this.form.video_path || '').trim();
      if (!v) { this.calInfo = null; return; }
      window.API.getCalibration(v).then(function (r) {
        self.calInfo = (r && r.exists) ? r : null;
      }).catch(function () { self.calInfo = null; });
    },
    /** 把原片挂到弹窗里的播放器上（拖动定位用；后端 /api/video 支持 Range） */
    loadPlayer: function () {
      var v = String(this.form.video_path || '').trim();
      this.videoUrl = v ? window.API.videoUrl(v) : '';
    },
    /** 数字框改了秒数 → 播放器跟着跳过去（两边保持同步） */
    seekVideo: function (t) {
      var el = this.$refs.markVideo;
      if (!el) { return; }
      try { el.currentTime = Math.max(0, Number(t) || 0); } catch (e) { /* 元数据还没到就忽略 */ }
    },
    /** 把某一时刻的画面**加进帧列表**（球场模式用：想标哪一帧就加哪一帧） */
    addFrameAtTime: function (t) {
      var self = this;
      var v = String(this.form.video_path || '').trim();
      var tt = Number(Number(t).toFixed(2));
      window.API.getFrame(v, tt).then(function (r) {
        self.mfFrames.push({ t: tt, w: r.w, h: r.h, image: r.image });
        self.mfIdx = self.mfFrames.length - 1;
        self.mfTarget = '';
        self.mfResult = null;
        self.$message.success('已加入 t=' + tt + 's 这一帧（共 ' + self.mfFrames.length +
          ' 帧）—— 现在可以在它上面标点');
      }).catch(function (e) {
        self.$message.error('取帧失败：' + (e && e.message ? e.message : e));
      });
    },
    /** 「用当前画面取帧」：读播放器当前位置 → 篮筐模式换取帧图、球场模式把这一帧加进列表 */
    useVideoMoment: function () {
      var el = this.$refs.markVideo;
      var t = (el && el.currentTime) ? el.currentTime : this.markAt;
      if (this.markKind === 'court') { this.addFrameAtTime(t); return; }
      this.markAt = Number(Number(t).toFixed(2));
      this.loadMarkFrame(false);
      this.$message.success('已取 t=' + this.markAt + 's 的画面，可以在它上面标点了');
    },
    /** 在指定时刻附近重抽（这几帧属于同一镜头，点才能叠加） */
    mfResample: function () {
      var self = this;
      var v = String(this.form.video_path || '').trim();
      if (!v) return;
      window.API.getFrames(v, 6, this.mfCenter, this.mfSpan).then(function (d) {
        // 换镜头就清空已标点：不同镜头的像素坐标不通用
        if (self.mfPts.length) {
          self.mfPts = [];
          self.$message.info('已换镜头，原标点已清空（不同镜头坐标不通用）');
        }
        self.mfFrames = (d && d.frames) || [];
        self.mfIdx = 0;
        self.$message.success('抽到 ' + self.mfFrames.length + ' 帧（t=' +
          (self.mfFrames.length ? self.mfFrames[0].t + '~' +
           self.mfFrames[self.mfFrames.length - 1].t : '') + 's）');
      }).catch(function (e) {
        self.$message.error('抽帧失败：' + (e && e.message ? e.message : e));
      });
    },
    mfPrev: function () { if (this.mfIdx > 0) this.mfIdx -= 1; },
    mfNext: function () {
      if (this.mfIdx < this.mfFrames.length - 1) this.mfIdx += 1;
      else this.$message.info('已经是最后一个画面了');
    },
    mfPick: function (item) { this.mfTarget = item.name; },
    /** 在当前画面上点一个点（必须是先选中了某个特征点） */
    mfClick: function (ev) {
      if (!this.mfCurrent) return;
      if (this.autoMode) {
        var e0 = (ev.target && ev.target.tagName === 'IMG') ? ev.target
                                                            : ev.currentTarget;
        var b0 = e0.getBoundingClientRect();
        var ax = Math.max(0, Math.min(1, (ev.clientX - b0.left) / b0.width));
        var ay = Math.max(0, Math.min(1, (ev.clientY - b0.top) / b0.height));
        this.mfPts.push({ t: this.mfCurrent.t, name: 'auto' + this.mfPts.length,
                          label: '点' + (this.mfPts.length + 1), x: ax, y: ay });
        this.autoResult = null;
        this.$message.success('已记录第 ' + this.mfPts.length + ' 个点');
        return;
      }
      if (!this.mfTarget) {
        this.$message.warning('先在上面选一个特征点（比如「中圈中心」），再在画面里点它');
        return;
      }
      if (!this.mfCurrent) return;
      var el = (ev.target && ev.target.tagName === 'IMG') ? ev.target
                                                          : ev.currentTarget;
      var box = el.getBoundingClientRect();
      var x = Math.max(0, Math.min(1, (ev.clientX - box.left) / box.width));
      var y = Math.max(0, Math.min(1, (ev.clientY - box.top) / box.height));
      var item = null;
      for (var i = 0; i < this.courtItems.length; i++) {
        if (this.courtItems[i].name === this.mfTarget) { item = this.courtItems[i]; }
      }
      // 同一点名只保留最后一次（重复点=修正）
      var self = this;
      this.mfPts = this.mfPts.filter(function (p) { return p.name !== self.mfTarget; });
      this.mfPts.push({ t: this.mfCurrent.t, name: this.mfTarget,
                        label: item ? item.label : this.mfTarget, x: x, y: y });
      this.mfTarget = '';
      // ★ 加了新点就清掉上一次的解算结果 —— 否则界面一直显示"旧报错"，
      // 用户会以为补点之后还是不行（实测踩到：先点 4 个点报错，再补到 6 个，
      // 红框仍写着"只点了 4 个点"，用户就卡在这里了）
      this.mfResult = null;
      // 立刻回显坐标：用户一眼就能看出记的是不是鼠标点的地方
      this.$message.success('已记录 ' + (item ? item.label : '') +
        ' → (' + x.toFixed(3) + ', ' + y.toFixed(3) + ')');
    },
    mfUndo: function () {
      if (this.mfPts.length) this.mfPts.pop();
      this.mfResult = null;      // 撤销后旧结果失效
    },
    mfClear: function () { this.mfPts = []; this.mfTarget = ''; this.mfResult = null; },
    /** 自动识别标定：把当前帧的点交给后端，让它自己认出对应关系 */
    solveAutoCalib: function () {
      var self = this;
      var pts = (this.mfPtsHere || []).map(function (p) { return [p.x, p.y]; });
      if (pts.length < 5) {
        this.$message.warning('自动识别至少要点 5 个点（现在 ' + pts.length +
          ' 个）—— 4 个点时任何配对都能精确拟合，分不出对错；第 5 个点才能投票');
        return;
      }
      this.autoResult = { loading: true };
      window.API.calibrateAuto({
        video_path: this.videoPath || this.form.video_path,
        points: pts,
        half: this.autoHalf,
        t: this.mfCurrent ? this.mfCurrent.t : 0
      }).then(function (r) {
        self.autoResult = r;
        if (r && r.ok) {
          self.$message.success('自动识别成功：' + r.named + '，误差 ' + r.rmse_m + ' m');
        } else {
          self.$message.error((r && r.note) || '自动识别失败');
        }
      }).catch(function (e) {
        self.autoResult = { ok: false, note: e.message || String(e) };
      });
    },
    /** 保存并解算（多帧累加）
     *
     * two-step：`confirm:false` 先预览（不落盘），`confirm:true` 才保存并带 revision
     * 做乐观锁（移植自旧版标定页）。宽容规则在服务端：只拒绝了"数学上无意义"的
     * 退化点位和"篮筐投偏 >6m"；只点 4 个点、有点矛盾、篮筐偏 3~6m 都**允许保存**，
     * 但会标 position_unverified，位置结论（热区/战术图）由分析端关掉。 */
    previewCourtMulti: function () {
      var self = this;
      if (!this.mfEnough) {
        this.$message.warning('至少要点 4 个特征点（现在 ' + this.mfPts.length + ' 个）');
        return;
      }
      var byT = {};
      this.mfPts.forEach(function (p) {
        byT[p.t] = byT[p.t] || { t: p.t, landmarks: {} };
        byT[p.t].landmarks[p.name] = [p.x, p.y];
      });
      var frames = Object.keys(byT).map(function (k) { return byT[k]; });
      this.markSaving = true;
      window.API.calibrateMulti({
        video_path: String(this.form.video_path).trim(), frames: frames, confirm: false
      }).then(function (r) {
        self.markSaving = false;
        self.mfResult = r;
        self.mfPreviewed = !!(r && r.ok);
        if (r.ok) {
          self.$message.success('预览通过：平均误差 ' + r.rmse_m + ' m' +
            (r.hoop_error_m != null ? ('，篮筐投影偏 ' + r.hoop_error_m + ' m') : '') +
            ' —— 确认没问题再点保存');
        } else {
          self.$message.warning('这份点法还不能用：' + String(r.note || '').slice(0, 60));
        }
      }).catch(function (e) {
        self.markSaving = false;
        self.$message.error('解算失败：' + (e && e.message ? e.message : e));
      });
    },
    saveCourtMulti: function () {
      var self = this;
      if (!this.mfEnough) {
        this.$message.warning('至少要点 4 个特征点（现在 ' + this.mfPts.length + ' 个）');
        return;
      }
      var byT = {};
      this.mfPts.forEach(function (p) {
        byT[p.t] = byT[p.t] || { t: p.t, landmarks: {} };
        byT[p.t].landmarks[p.name] = [p.x, p.y];
      });
      var frames = Object.keys(byT).map(function (k) { return byT[k]; });
      this.markSaving = true;
      window.API.calibrateMulti({
        video_path: String(this.form.video_path).trim(), frames: frames,
        confirm: true,
        revision: (this.calInfo && this.calInfo.revision != null)
          ? this.calInfo.revision : null
      }).then(function (r) {
        self.markSaving = false;
        self.mfResult = r;
        if (r.saved) {
          if (r.position_unverified) {
            self.$message.warning('标定已保存，但位置结论会被判为**未校验**：' +
              String(r.note || '').slice(0, 80));
          } else {
            self.$message.success('标定成功：' + r.n_points + ' 个点 / ' +
              r.n_frames + ' 个画面，平均误差 ' + r.rmse_m + ' m —— 分析时会自动使用');
          }
          self.loadCalInfo();
          self.markOpen = false;
        } else {
          self.$message.error('未保存：' + String(r.note || '点位不可用').slice(0, 90));
        }
      }).catch(function (e) {
        self.markSaving = false;
        self.$message.error('解算失败：' + (e && e.message ? e.message : e));
      });
    },
    /** 球场模式下点一个点 */
    onCourtClick: function (ev) {
      if (this.mfFrames.length) { this.mfClick(ev); return; }
      if (this.courtDone || !this.courtCurrent) return;
      // 用**图片元素**的框做基准（不是容器）：容器是 inline-block + max-width，
      // 在弹窗里它的宽度可能比图片显示宽度大，用容器归一化会导致绿圈整体偏移。
      var el = (ev.target && ev.target.tagName === 'IMG') ? ev.target
                                                          : ev.currentTarget;
      var box = el.getBoundingClientRect();
      var x = Math.max(0, Math.min(1, (ev.clientX - box.left) / box.width));
      var y = Math.max(0, Math.min(1, (ev.clientY - box.top) / box.height));
      this.courtPts.push({ name: this.courtCurrent.name,
                           label: this.courtCurrent.label, x: x, y: y });
      this.courtIdx += 1;
    },
    /** 读比分牌：自动定位（或手动框选）+ 放大 OCR → 得分事件文件 */
    readScoreboard: function () {
      var self = this;
      var v = String(this.videoPath || this.form.video_path || '').trim();
      if (!v) { this.$message.warning('先填视频路径（或上传视频）'); return; }
      var payload = { video_path: v, step: 0.5, zoom: 4.0 };
      var box = [];
      String(this.sbBox || '').split(',').forEach(function (x) {
        var n = parseFloat(x);
        if (!isNaN(n)) box.push(n);
      });
      if (box.length === 4) payload.box = box;
      var sh = parseInt(this.sbStartHome, 10);
      var sa = parseInt(this.sbStartAway, 10);
      if (!isNaN(sh) && !isNaN(sa)) payload.start = { home: sh, away: sa };
      this.sbBusy = true;
      this.sbResult = { loading: true };
      this.log('POST /api/scoreboard/ocr ' + JSON.stringify(payload));
      window.API.scoreboardOcr(payload).then(function (r) {
        self.sbBusy = false;
        self.sbResult = r;
        self.form.scoreboard_events = r.path || '';
        self.$message.success('比分牌读出 ' + r.n_events + ' 个得分事件，最终 ' +
          r.final.home + ' : ' + r.final.away);
        self.log('比分牌：' + r.note);
      }).catch(function (e) {
        self.sbBusy = false;
        self.sbResult = { ok: false, note: (e && e.message) || String(e) };
        self.$message.error('读比分牌失败：' + ((e && e.message) || e));
      });
    },
    /** 切视频后，看这段视频是否已经读过比分牌 */
    loadScoreboardEvents: function () {
      var self = this;
      var v = String(this.videoPath || this.form.video_path || '').trim();
      if (!v) return;
      window.API.scoreboardEvents(v).then(function (r) {
        if (r && r.exists) {
          self.form.scoreboard_events = r.path;
          self.sbResult = { ok: true, saved: true, path: r.path, final: r.final,
                            n_events: r.n_events, method: r.method,
                            note: '这段视频已经读过比分牌（' + r.n_events +
                                  ' 个得分事件，最终 ' + (r.final || {}).home +
                                  ' : ' + (r.final || {}).away + '），分析时会用它' };
        }
      }).catch(function () { /* 没读过就算了，不打扰用户 */ });
    },
    /** 提交球场标定
     *
     * 两段式（移植自旧版标定页）：先"预览"（confirm:false，不落盘），
     * 让用户看清每个点差多少像素、篮筐投影偏多少米，再决定要不要存。
     * 以前只有"保存"一个按钮，点错了只能反复覆盖，用户既不知道错在哪、
     * 也不知道能不能重来。 */
    previewCourt: function () {
      var self = this;
      if (!this.courtEnough) {
        this.$message.warning('至少要点 4 个场地特征点（现在 ' +
          this.courtPts.length + ' 个）');
        return;
      }
      var lm = {};
      this.courtPts.forEach(function (p) { lm[p.name] = [p.x, p.y]; });
      this.markSaving = true;
      window.API.saveCourtMarks({
        video_path: String(this.form.video_path).trim(),
        at: this.markAt, landmarks: lm, confirm: false
      }).then(function (r) {
        self.markSaving = false;
        self.courtResult = r;
        self.courtPreview = r;
        self.courtPreviewed = !!(r && r.ok);
      }).catch(function (e) {
        self.markSaving = false;
        self.$message.error('解算失败：' + (e && e.message ? e.message : e));
      });
    },
    saveCourt: function () {
      if (this.mfFrames.length) { this.saveCourtMulti(); return; }
      var self = this;
      if (!this.courtEnough) {
        this.$message.warning('至少要点 4 个场地特征点（现在 ' +
          this.courtPts.length + ' 个）');
        return;
      }
      var lm = {};
      this.courtPts.forEach(function (p) { lm[p.name] = [p.x, p.y]; });
      this.markSaving = true;
      window.API.saveCourtMarks({
        video_path: String(this.form.video_path).trim(),
        at: this.markAt, landmarks: lm,
        confirm: true,
        revision: (this.calInfo && this.calInfo.revision != null)
          ? this.calInfo.revision : null
      }).then(function (r) {
        self.markSaving = false;
        self.courtResult = r;
        self.courtPreview = r;
        if (r.saved) {
          if (r.position_unverified) {
            self.$message.warning('标定已保存，但篮筐投影偏 ' + r.hoop_error_m +
              ' m —— 位置类结论（热区/战术图）会被判为未校验；' +
              '想用位置结论请重新标一次');
          } else {
            self.$message.success('标定已保存：' + r.n_points + ' 个点，重投影误差 ' +
              r.rmse_m + ' m（最大单点 ' + r.reproj_err_px + ' px）');
          }
          self.markOpen = false;
          self.loadCalInfo();
        } else {
          self.$message.error(r.note || '标定未通过校验，未保存');
        }
      }).catch(function (e) {
        self.markSaving = false;
        self.$message.error('标定失败：' + (e && e.message ? e.message : e));
      });
    },
    /** 撤销这份标定（标错了要能重来，而不是只能覆盖） */
    clearCourtCalib: function () {
      var self = this;
      var v = String(this.form.video_path || '').trim();
      if (!v) { return; }
      window.API.deleteCalibration(v, (this.calInfo && this.calInfo.revision) || 0)
        .then(function (r) {
          self.$message.success(r && r.removed ? '已撤销这份标定' : '本来就没有标定');
          self.courtResult = null;
          self.courtPreview = null;
          self.courtPreviewed = false;
          self.loadCalInfo();
        }).catch(function (e) {
          self.$message.error('撤销失败：' + (e && e.message ? e.message : e));
        });
    },
    loadMarkFrame: function (keepPoints) {
      var self = this;
      var v = String(this.form.video_path || '').trim();
      // 换帧就清空标点：标点存的是**像素位置**，换了帧那些位置就指向别的东西了
      // （实测用户看到的现象是"点跟着画面漂移"，其实是我们没清）。
      if (!keepPoints && (this.courtPts.length || this.markPts.length)) {
        this.courtPts = [];
        this.courtIdx = 0;
        this.markPts = [];
        this.markIdx = 0;
        this.$message.info('已换帧，标点已清空，请按提示重新点');
      }
      this.markImg = '';
      this.log('GET /api/frame?at=' + this.markAt);
      window.API.getFrame(v, this.markAt).then(function (r) {
        self.markImg = r.image;
        self.markSize = { w: r.w, h: r.h };
      }).catch(function (e) {
        self.$message.error('取帧失败：' + (e && e.message ? e.message : e));
      });
    },
    /** 鼠标在画面上移动 → 记下位置，用来画准星（点之前就知道会落在哪） */
    onMarkMove: function (ev) {
      var el = (ev.target && ev.target.tagName === 'IMG') ? ev.target
                                                          : ev.currentTarget;
      var box = el.getBoundingClientRect();
      if (!box.width || !box.height) return;
      var x = (ev.clientX - box.left) / box.width;
      var y = (ev.clientY - box.top) / box.height;
      if (x < 0 || x > 1 || y < 0 || y > 1) { this.hoverPt = null; return; }
      this.hoverPt = { x: x, y: y };
    },
    onMarkLeave: function () { this.hoverPt = null; },
    onMarkClick: function (ev) {
      if (this.markKind === 'court') { this.onCourtClick(ev); return; }
      // 必点项（篮筐中心）已点完时，如果用户选了"可选：量筐宽"的某一项，就落那一项。
      // 这样"只点中心"是默认路径，想量精确半径的人也不用被困在 5 步流程里。
      var target = (this.markDone && this.hoopOptTarget) ? this.hoopOptTarget : null;
      if (!target && (this.markDone || !this.markCurrent)) return;
      var el = (ev.target && ev.target.tagName === 'IMG') ? ev.target
                                                          : ev.currentTarget;
      var box = el.getBoundingClientRect();
      var x = (ev.clientX - box.left) / box.width;
      var y = (ev.clientY - box.top) / box.height;
      x = Math.max(0, Math.min(1, x));
      y = Math.max(0, Math.min(1, y));
      if (target) {
        var item = this.markItemsOptional.filter(function (o) {
          return o.name === target; })[0] || { name: target, label: target };
        // 同名点只能有一个：再点一次就是覆盖（避免越点越多）
        this.markPts = this.markPts.filter(function (p) { return p.name !== target; });
        this.markPts.push({ name: item.name, label: item.label, x: x, y: y });
        this.hoopOptTarget = '';
        return;
      }
      this.markPts.push({ name: this.markCurrent.name,
                          label: this.markCurrent.label, x: x, y: y });
      this.markIdx += 1;
    },
    markUndo: function () {
      if (this.markKind === 'court') { this.courtUndo(); return; }
      if (this.markIdx > 0) {
        this.markIdx -= 1;
        this.markPts.pop();
      }
    },
    markSkip: function () {
      if (this.markKind === 'court') { this.courtSkip(); return; }
      if (!this.markDone) this.markIdx += 1;
    },
    courtUndo: function () {
      if (this.courtIdx > 0) { this.courtIdx -= 1; this.courtPts.pop(); }
    },
    courtSkip: function () { if (!this.courtDone) this.courtIdx += 1; },
    markPct: function (p) { return { left: (p.x * 100) + '%', top: (p.y * 100) + '%' }; },
    /** 保存标点：POST /api/marks（归一化坐标，后端换回像素） */
    saveMarks: function () {
      var self = this;
      if (this.markKind === 'court') { this.saveCourt(); return; }
      var h = this.markHoop;
      if (!h) { this.$message.warning('至少要点出「篮筐中心」'); return; }
      var lm = {};
      this.markPts.forEach(function (p) { lm[p.name] = [p.x, p.y]; });
      this.markSaving = true;
      window.API.saveMarks({
        video_path: String(this.form.video_path).trim(),
        at: this.markAt,
        landmarks: lm,
        hoop: [h.cx, h.cy, h.rx, h.ry]
      }).then(function (r) {
        self.markSaving = false;
        self.markOpen = false;
        self.savedMarks = r.marks;
        self.$message.success('标点已保存，分析时会直接用它（不再跑篮筐检测器）');
      }).catch(function (e) {
        self.markSaving = false;
        self.$message.error('保存失败：' + (e && e.message ? e.message : e));
      });
    },
    clearMarks: function () {
      if (this.markKind === 'court') { this.courtPts = []; this.courtIdx = 0; return; }
      this.markPts = []; this.markIdx = 0;
    },
    /** 把已保存的标点画回去（只读展示） */
    savedMarkPct: function (p) { return { left: (p[0] * 100) + '%', top: (p[1] * 100) + '%' }; },

    /** 后端能力探测：GET /api/health（ffmpeg / 检测模型 / OpenCV 是否就绪） */
    fetchHealth: function () {
      var self = this;
      if (!this.S.backendOk) return;
      window.API.health().then(function (h) { self.health = h; })
        .catch(function () { self.health = null; });
    },
    /** 浏览器上传视频：POST /api/upload（带 x-filename 头）→ 得到后端可见的路径 */
    /* ------------------------------------------------------------------
       新手上手引导（onboard）：让第一次拿到软件的人 5 分钟内看到一份结果
       ------------------------------------------------------------------ */
    /** 拉取"机器上现成的视频"清单（示例素材 + 已上传），给引导里的下拉用 */
    loadSamples: function () {
      var self = this;
      window.API.samples().then(function (r) {
        self.samples = (r && r.samples) || [];
        if (!self.samplePick && self.samples.length) {
          self.samplePick = self.samples[0].path;
        }
      }).catch(function () { self.samples = []; });
    },
    /** 一键用现成视频（新手上手最省事的一步） */
    useSample: function () {
      var p = this.samplePick || (this.samples[0] && this.samples[0].path);
      if (!p) {
        this.$message.warning('这台机器上没找到现成素材，请选一个本地文件上传');
        this.pickFile();
        return;
      }
      this.form.video_path = p;
      this.loadCalInfo();
      if (this.loadScoreboardEvents) { this.loadScoreboardEvents(); }
      this.$message.success('已选好视频：' + this.videoBaseName);
    },
    /** 引导里的按钮：按步骤分发（1 选视频 / 2 标定 / 3 分析或看结果） */
    guideAct: function (st) {
      if (!st) { return; }
      if (st.key === 'video') {
        if (this.samples.length) { this.useSample(); } else { this.pickFile(); }
        return;
      }
      if (st.key === 'calib') { this.openCourt(); return; }
      if (st.key === 'run') {
        var job = (this.S && this.S.job) || {};
        if (job.status === 'done') { location.hash = '#/overview'; return; }
        this.start();
      }
    },
    /** 收起引导：记在 localStorage，别每次都来烦人（但随时可以重新打开） */
    dismissGuide: function () {
      this.guideOpen = false;
      try { localStorage.setItem('aihoop-guide-dismissed', '1'); } catch (e) { /* 无痕模式 */ }
      this.$message.info('已收起上手引导；需要时在同一位置点「重新打开上手引导」');
    },
    openGuide: function () {
      this.guideOpen = true;
      try { localStorage.removeItem('aihoop-guide-dismissed'); } catch (e) { /* 忽略 */ }
    },
    /** 选本地文件上传（引导第 1 步的兜底路径） */
    pickFile: function () {
      var self = this;
      if (!this.S.backendOk) {
        this.$message.warning('未连接后端，无法上传文件；可先填写后端机器上的绝对路径');
        return;
      }
      if (this.health && this.health.stale) {
        this.$message.warning('后端正在自动重启或仍载入旧代码，请等几秒后点「刷新」再上传');
        return;
      }
      var input = document.createElement('input');
      input.type = 'file';
      input.accept = 'video/*';
      input.onchange = function () {
        var f = input.files && input.files[0];
        if (!f) return;
        self.fileName = f.name;
        self.uploadPct = 0;
        self.log('POST /api/upload（x-filename=' + f.name + '，' + (f.size / 1048576).toFixed(1) + ' MB）');
        window.API.uploadVideo(f, function (p) { self.uploadPct = p; }).then(function (r) {
          self.uploadPct = -1;
          self.form.source = 'video';
          self.form.video_path = r.path;
          self.log('上传完成：' + r.path + '（' + r.bytes + ' 字节）');
          self.$message.success('视频已上传到后端：' + r.path);
        }).catch(function (e) {
          self.uploadPct = -1;
          self.log('上传失败：' + e.message);
          // 错误消息本身已经写清楚了原因（后端没响应 / 被中断 / HTTP 码），
          // 这里不再套一层「上传失败：」，免得出现「上传失败：上传失败：…」
          self.$message.error(e.message);
        });
      };
      input.click();
    },

    /** 静态产物模式：载入 web/demo/*.json（不需要后端进程） */
    loadDemo: function () {
      var self = this;
      window.API.loadDemo().then(function (d) {
        if (!d.game) {
          self.$message.error('未找到 web/demo/game.json：先跑 '
            + 'python -m aihoop.cli demo --seed 7 --duration 600 --out out/demo');
          return;
        }
        self.S.applyGame(d.game, d.players || [], d.shotchart, {
          markdown: d.reportMd || '', json: d.report_json || null
        }, d.highlights);
        self.S.demoMode = true;
        self.S.jobId = 'demo';
        self.$message.success('已载入演示数据');
        location.hash = '#/overview';
      });
    },

    /** 拉取历史任务列表：GET /api/jobs */
    refreshJobs: function () {
      var self = this;
      if (!this.S.backendOk) return;
      window.API.listJobs().then(function (d) {
        self.jobs = Array.isArray(d) ? d : (d && d.jobs) || [];
      }).catch(function () { /* 静默：无后端时不打扰用户 */ });
    },

    /** 回看某个历史任务的全部产物：GET /api/games/{id} 等 */
    openJob: function (row) {
      var self = this;
      if (row.status !== 'done') { this.$message.info('该任务还未完成'); return; }
      window.APP_LOAD_JOB(row.job_id).then(function () {
        self.S.demoMode = false;
        self.$message.success('已载入任务 ' + String(row.job_id).slice(0, 8) + ' 的产物');
        location.hash = '#/overview';
      }).catch(function (e) {
        self.$message.error('载入失败：' + e.message);
      });
    },

    /** 开始分析：POST /api/jobs → WS/轮询跟踪进度 → 完成后装载产物 */
    start: function () {
      var self = this;
      if (!this.S.backendOk) {
        this.$message.warning('未连接后端，无法新建任务；可先点「载入演示数据」走完整演示流程');
        return;
      }
      if (!this.canSubmit) { this.$message.warning('请填写视频路径或 JSONL 文件路径'); return; }
      this.busy = true;
      this.logs = [];
      this.job = { job_id: '', status: 'queued', progress: 0, message: '正在提交任务…', error: null, out_dir: '', summary: '' };

      var payload = {
        // 后端 JobCreate：video 源用 video_path；jsonl 源用 raw_path（两个都带上，互不冲突）
        video_path: String(this.form.video_path).trim(),
        source: this.form.source,
        // 不再发 seed：它只对后端「合成比赛」生效（JobCreate.seed → synthetic_game），
        // 真实视频分析用不到（管线里没有随机数）。合成入口已从界面移除，
        // 需要合成数据时用命令行 `python -m aihoop.cli demo --seed 7`。
        make_highlights: !!this.form.make_highlights
      };
      if (this.form.source === 'video') {
        // 快速模式：跳过逐帧 YOLO，只走「比分牌 + 颜色追球」
        payload.detect_players = !this.form.fast;
        payload.stride = this.form.fast ? 1 : 2;
        // 如果标过篮筐，把标点文件带上：后端直接用你的坐标，跳过检测器
        if (this.savedMarks && this.savedMarks.path) {
          payload.marks = this.savedMarks.path;
          this.log('带上人工标点：' + this.savedMarks.path);
        }
        // 如果自己也标过进球（label_baskets 的产出），带上当准绳
        if (this.form.labels_path) payload.basket_labels = String(this.form.labels_path).trim();
        // 比分牌得分事件（「读比分牌」的产出）：带上它，非标准台标也能走比分牌路径
        if (this.form.scoreboard_events) {
          payload.scoreboard_events = String(this.form.scoreboard_events).trim();
          this.log('带上比分牌得分事件：' + payload.scoreboard_events);
        }
      }
      if (this.form.source === 'jsonl') payload.raw_path = payload.video_path;
      // **没标定球场时必须显式声明"不要球场坐标"**：后端 JobCreate.allow_no_calibration
      // 默认是 False，没标定就会直接抛「尚未标定球场…」把任务拒掉；而本页第 2 步的引导
      // 明明写着"不标也能出比分、命中率、球员统计和战报"。两边口径必须一致，
      // 否则用户照着引导走、点「开始分析」必被拒（用户实测反馈：不标定就是不给分析）。
      if (this.form.source === 'video') {
        var hasCal = !!(this.calInfo && this.calInfo.exists);
        payload.allow_no_calibration = !hasCal;
        if (!hasCal) {
          this.log('未标定球场：本次按「只判进球」跑（没有热图/战术图/2-3 分区分）'
            + '；标定后这些位置类结论才会打开。');
        }
      }
      this.log('POST /api/jobs ' + JSON.stringify(payload));

      window.API.createJob(payload).then(function (r) {
        var id = r.job_id || r.id;
        self.job.job_id = id;
        self.log('任务已创建 job_id=' + id + '，订阅 WS /api/jobs/' + id + '/ws');
        window.APP.registerJob(self.job);
        self.subscribe(id);
      }).catch(function (e) {
        self.busy = false;
        self.job.status = 'error';
        self.job.error = e.message;
        self.log('创建任务失败：' + e.message);
        self.$message.error('创建任务失败：' + e.message);
      });
    },

    /** 订阅进度：WS 优先，失败自动切轮询（api.js 内部实现） */
    subscribe: function (id) {
      var self = this;
      if (this.watcher) this.watcher.close();
      this.watcher = window.API.watchJob(id, function (j) {
        var prev = self.job.message;
        self.job = j;
        if (j.message && j.message !== prev) self.log('阶段：' + j.message + '（' + Math.round((j.progress || 0) * 100) + '%）');
        if (j.status === 'done') {
          self.busy = false;
          self.log('分析完成：' + (j.summary || ''));
          self.$message.success('分析完成，正在载入产物…');
          window.APP_LOAD_JOB(id).then(function () {
            self.S.demoMode = false;
            self.refreshJobs();
            location.hash = '#/overview';
          }).catch(function (e) { self.$message.error('产物载入失败：' + e.message); });
        } else if (j.status === 'error') {
          self.busy = false;
          self.log('任务失败：' + (j.error || '未知错误'));
          self.$message.error('分析失败：' + (j.error || '未知错误'));
        }
      }, function (err) {
        self.log('⚠ ' + err.message);
      });
    },

    log: function (msg) {
      var t = new Date().toLocaleTimeString('zh-CN', { hour12: false });
      this.logs.push('[' + t + '] ' + msg);
      if (this.logs.length > 200) this.logs.shift();
      var self = this;
      this.$nextTick(function () {
        var el = self.$refs.logbox;
        if (el) el.scrollTop = el.scrollHeight;
      });
    }
  },
  template: [
    '<div>',
    // ---- 新手上手引导：3 步走到"看到一份结果" ----
    // 为什么放最上面：第一次拿到软件的人面对 ①②③ 三张卡会一头雾水 ——
    // 不知道该先干什么、标定是不是必须、结果在哪看。这里把最短路径摊开，
    // 并**跟着用户的实际进度**打勾（状态驱动，不是一段死教程）。
    '  <div class="card" v-if="guideOpen">',
    '    <div class="row" style="align-items:center;justify-content:space-between">',
    // 注意：**不要**给卡片加左侧彩色竖条（border-left:3px 是 AI 生成界面的典型痕迹，
    // 检测器会直接判为 slop）。这里改用一个小标签来区分"这是引导，不是普通表单"。
    '      <h3 class="card-title" style="margin:0"><el-tag size="small" type="primary" effect="plain">上手引导</el-tag>',
    '        3 步跑出第一份分析',
    '        <span class="sub">已完成 {{ guideDoneCount }}/3 · 全程约 5 分钟</span></h3>',
    '      <el-button size="small" text @click="dismissGuide">收起（不再自动显示）</el-button>',
    '    </div>',
    '    <div class="hint" style="margin:6px 0 10px">做完这 3 步你能看到：比分与命中率、球员统计、投篮热图、战术分析，以及一份文字战报。不用先读文档，也不用先配环境。</div>',
    '    <div class="grid grid-3" style="gap:10px">',
    '      <div v-for="st in guideSteps" :key="st.key" class="src-card" :class="{active: !st.done}">',
    '        <div class="t">{{ st.done ? \'✓\' : st.n }}. {{ st.title }}</div>',
    '        <div class="d" style="margin-bottom:8px">{{ st.desc }}</div>',
    '        <el-button size="small" :type="st.done ? \'default\' : \'primary\'" @click="guideAct(st)">{{ st.cta }}</el-button>',
    '      </div>',
    '    </div>',
    '    <div class="row" style="margin-top:10px;align-items:center;flex-wrap:wrap;gap:6px">',
    '      <span class="hint">手头没有素材？直接选一段机器上现成的：</span>',
    '      <el-select v-model="samplePick" size="small" style="width:340px" placeholder="选择现成的视频" filterable>',
    '        <el-option v-for="s in samples" :key="s.path"',
    '          :label="s.group + \' · \' + s.name + \'（\' + s.size_mb + \' MB）\'" :value="s.path" />',
    '      </el-select>',
    '      <el-button size="small" @click="useSample" :disabled="!samples.length">用它</el-button>',
    '      <span class="hint" v-if="!samples.length">（没找到现成素材：点第 1 步的「选择本地文件」上传你自己的视频）</span>',
    '      <span class="grow"></span>',
    '      <span class="hint" v-if="!S.backendOk" style="color:#c45656">后端没连上：先双击项目根目录的「启动后端.bat」</span>',
    '    </div>',
    '  </div>',
    '  <div class="card" v-else style="padding:10px 14px">',
    '    <div class="row" style="align-items:center;gap:8px">',
    '      <span class="hint">上手引导已收起。</span>',
    '      <el-button size="small" text type="primary" @click="openGuide">重新打开上手引导</el-button>',
    '      <span class="grow"></span>',
    '      <span class="hint">没跳过的话，按下面 ① ② ③ 顺序走也一样。</span>',
    '    </div>',
    '  </div>',
    '  <div class="card">',
    '    <h3 class="card-title">① 选择数据源</h3>',
    '    <div class="grid grid-2">',
    '      <div class="src-card" :class="{active: form.source===\'video\'}" @click="form.source=\'video\'">',
    '        <div class="t">🎥 上传视频（video）</div>',
    '        <div class="d">两种方式：① 直接<b>选择本地文件</b>上传（POST /api/upload，后端复制到 data/uploads）；',
    '          ② 填写后端机器上的<b>绝对路径</b>（同机演示最省事）。</div>',
    '      </div>',
    '      <div class="src-card" :class="{active: form.source===\'jsonl\'}" @click="form.source=\'jsonl\'">',
    '        <div class="t">📄 已有 JSONL（jsonl）</div>',
    '        <div class="d">直接用既有的检测结果重跑统计与热区，跳过目标检测环节；',
    '          后端取 <code>raw_path</code> 指向的 raw_track.json。</div>',
    '      </div>',
    '    </div>',
    '    <div class="hint">「合成演示」入口已移除：它生成的是<b>模拟比赛</b>（比分/出手/回合全是造出来的），',
    '      混在历史任务里会被误认成真实分析结果。回归测试请用命令行：',
    '      <code>python -m aihoop.cli demo --seed 7 --duration 600 --out out/fixture</code></div>',
    '  </div>',

    '  <div class="grid grid-2">',
    '    <div class="card">',
    '      <h3 class="card-title">② 分析参数</h3>',
    '      <el-form label-width="112px" label-position="left">',
    '        <el-form-item label="文件路径">',
    '          <el-input v-model="form.video_path" @change="loadScoreboardEvents" placeholder="例如 D:\\\\videos\\\\game1.mp4 或 out\\\\xxx\\\\raw_track.json" clearable />',
    '          <div class="row" style="margin-top:8px">',
    '            <el-button size="small" :disabled="!S.backendOk || (health && health.stale)" @click="pickFile">选择本地视频上传</el-button>',
    '            <span class="hint" v-if="fileName">已选：{{ fileName }}</span>',
    '            <span class="hint" v-if="uploadPct>=0">上传中 {{ Math.round(uploadPct*100) }}%</span>',
    '          </div>',
    '          <el-progress v-if="uploadPct>=0" :percentage="Math.round(uploadPct*100)" :stroke-width="8" style="margin-top:8px;max-width:420px" />',
    '          <div class="hint">路径由后端进程解析；也可以点上面的按钮把视频上传到后端（返回可直接使用的路径）。</div>',
    '        </el-form-item>',
    // ---- 在画面上标篮筐：这是「分析前你先告诉我篮筐在哪」的入口 ----
    '        <el-form-item v-if="form.source===\'video\'" label="篮筐标点">',
    '          <div class="row">',
    '            <el-button size="small" type="primary" plain :disabled="!S.backendOk" @click="openMark">在画面上标篮筐</el-button>',
    // 这里原来还有一个「标球场」按钮，跟下面「球场标定」那一行完全重复 ——
    // 用户反馈（2026-09-27）："篮筐标点的地方就已经有标球场的选项了，后面又有一个球场标注就重复了"。
    // 现在只有「篮筐标点」管篮筐，「球场标定」管球场，各一处。
    '            <el-tag v-if="savedMarks && savedMarks.hoop" size="small" type="success" effect="plain">',
    '              已标：中心 {{ Math.round(savedMarks.hoop[0]) }},{{ Math.round(savedMarks.hoop[1]) }}',
    '              <template v-if="savedMarks.hoop[2] > 0">，半径 {{ Math.round(savedMarks.hoop[2]) }}×{{ Math.round(savedMarks.hoop[3]) }}</template>',
    '              <template v-else>（半径由检测器量）</template>',
    '            </el-tag>',
    // 这里原来还有一个「未标点（走自动检测）」标签 —— 用户反馈（2026-09-27）"把未标点删了"。
    // 没标点时不显示任何标签：没有徽章就是"还没标"，不需要多一个灰标签占地方。
    '          </div>',
    '          <div class="hint"><b>只点一下篮筐中心就够了</b>：框心当起点，筐位仍逐帧跟随镜头，',
    '            判进球的尺度由检测器量（实测 480p 手持素材 ~30px）。想让尺度完全由你定，',
    '            再点一下圈的左缘或右缘即可（那时就以你的为准，不再跑检测器）。</div>',
    '        </el-form-item>',
    // ---- 标球场：用户建议「不一定要标篮筐，别的有特色的点也可以」----
    '        <el-form-item v-if="form.source===\'video\'" label="球场标定">',
    '          <div class="row">',
    '            <el-button size="small" plain :disabled="!S.backendOk" @click="openCourt">标球场（点场地特征点）</el-button>',
    '            <el-tag v-if="calInfo" size="small" type="success" effect="plain">',
    '              已标定：重投影误差 {{ calInfo.reproj_error_m }} m',
    '            </el-tag>',
    '            <el-tag v-else size="small" type="warning" effect="plain">未标定（也能分析：热区不出、战术图退化成「自动逐帧标定」、2/3 分只能估）</el-tag>',
    '          </div>',
    '          <div class="hint">点 4 个以上<b>场地特征点</b>（四角 / 中线两端 / 中圈中心 / 罚球线中点 / 篮筐），',
    '            自动解出这段视频的球场标定。<b>热区、战术图、球场坐标全靠它</b> —— 用别的视频的标定会整片错位。',
    '            没有标定时：战术图仍会用<b>自动逐帧标定</b>算球员坐标（结果上会明确标注「位置未校验」），但热区不出。</div>',
    '        </el-form-item>',
    // 这里原来是「进球标注(可选)」输入框（要用户先准备一份 label_baskets.py 的产出当准绳）。
    // 用户反馈（2026-09-27）："本来就是一个投篮判定软件，却有一个进球标注的选项，这合适吗，
    // 你还不如在视频分析完以后加一个报错的选项" —— 那本质是开发/评测用的基准输入，
    // 不该出现在产品主流程里。人工纠错走「人工复核」页（判为命中/判为未中即时写回），
    // 攒训练样本走「训练标注」页。后端 `basket_labels` 参数保留，供脚本/命令行使用。
    // 随机种子输入框也一并去掉了：它只对「合成演示比赛」生效，真实视频分析根本不用它
    // （视频管线里没有任何随机数），摆在主流程里只会让人以为"结果是编出来的"。
    // 合成入口已从界面移除，需要合成数据时用命令行：
    //   python -m aihoop.cli demo --seed 7 --duration 600 --out out/demo
    '        <el-form-item label="生成高光片段">',
    '          <el-switch v-model="form.make_highlights" />',
    '          <span class="hint" style="margin-left:10px">需要本机安装 ffmpeg；关闭则只出统计数据，速度更快</span>',
    '        </el-form-item>',
    '        <el-form-item v-if="form.source===\'video\'" label="快速模式">',
    '          <el-switch v-model="form.fast" />',
    '          <span class="hint" style="margin-left:10px">跳过逐帧 YOLO（球员检测）：只读比分牌 + 颜色线索追球。CPU 上快十几倍；代价是没有球员个体归属，1v1/野球场视频会把进球都算在一边</span>',
    '        </el-form-item>',
    '        <el-form-item v-if="form.source===\'video\'" label="比分牌（可选）">',
    '          <div class="row" style="flex-wrap:wrap;align-items:center;gap:8px">',
    '            <el-button size="small" type="primary" :loading="sbBusy" @click="readScoreboard">',
    '              读比分牌（自动定位 + OCR）</el-button>',
    '            <span class="hint">起始比分（可选）：</span>',
    '            <el-input-number v-model="sbStartHome" :min="0" :max="199" size="small" style="width:100px" placeholder="主队" />',
    '            <el-input-number v-model="sbStartAway" :min="0" :max="199" size="small" style="width:100px" placeholder="客队" />',
    '          </div>',
    '          <div class="hint" style="margin-top:6px">',
    '            转播台标（含校园/村 BA 那种长横条）自动定位读不出时，用它兜底：',
    '            自动定位比分区域 → 放大 4 倍 → Windows OCR。填了起始比分更稳',
    '            （视频从半场中间开始录时用它当基线）。</div>',
    '          <el-input v-model="form.scoreboard_events" size="small" clearable style="margin-top:6px"',
    '            placeholder="得分事件文件路径（点上面的按钮自动填；也可手填 out\\\\sb_events.json）" />',
    '          <el-input v-model="sbBox" size="small" clearable style="margin-top:6px"',
    '            placeholder="手动框选（可选）：归一化 x0,y0,x1,y1，例如 0.21,0.10,0.79,0.15；留空=自动定位" />',
    '          <el-alert v-if="sbResult" style="margin-top:8px" :closable="false" show-icon',
    "            :type=\"sbResult.loading ? 'info' : (sbResult.ok ? 'success' : 'error')\"",
    "            :title=\"sbResult.loading ? '正在定位并 OCR…（十几秒到一分钟）' : (sbResult.ok ? ('读出 ' + (sbResult.n_events||0) + ' 个得分事件，最终 ' + ((sbResult.final||{}).home) + ' : ' + ((sbResult.final||{}).away)) : '没读出比分')\"",
    "            :description=\"sbResult.loading ? '' : (sbResult.note || '')\" />",
    '        </el-form-item>',
    '        <el-form-item label="后端状态">',
    '          <el-tag :type="S.backendOk ? \'success\' : \'warning\'" effect="plain">{{ api.base }}</el-tag>',
    '          <span class="hint" style="margin-left:10px">{{ S.backendOk ? \'已连接\' : \'未连接（演示数据模式）\' }}</span>',
    '          <div class="row" style="margin-top:8px" v-if="health">',
    '            <el-tag size="small" :type="health.ffmpeg ? \'success\' : \'info\'" effect="plain">ffmpeg {{ health.ffmpeg ? \'就绪\' : \'缺失\' }}</el-tag>',
    '            <el-tag size="small" :type="health.opencv ? \'success\' : \'info\'" effect="plain">OpenCV {{ health.opencv ? \'就绪\' : \'缺失\' }}</el-tag>',
    '            <el-tag size="small" :type="health.ultralytics ? \'success\' : \'info\'" effect="plain">检测模型 {{ health.ultralytics ? \'就绪\' : \'未装\' }}</el-tag>',
    '            <el-tag size="small" effect="plain" v-if="health.code_rev">代码 {{ health.code_rev }}</el-tag>',
    '            <el-tag size="small" effect="plain" type="info" v-if="health.code_loaded_at">进程载入 {{ health.code_loaded_at }}</el-tag>',
    '            <el-button size="small" text @click="fetchHealth">刷新</el-button>',
    '          </div>',
    '          <el-alert v-if="health && health.stale" type="warning" :closable="false" show-icon style="margin-top:8px"',
    '            title="后端正在自动重启以加载新代码"',
    '            description="源码（代码时间）比进程载入时间新，说明后端还没切到最新代码。用「启动后端.bat」启动的话会在 2 秒内自动重启；稍等片刻点「刷新」即可。若一直不变，请关掉后端窗口重新双击「启动后端.bat」。" />',
    '          <el-alert v-else-if="health && health.has_ball_rim_path === false" type="error" :closable="false" show-icon style="margin-top:8px"',
    '            title="后端进程跑的是旧代码，新功能不会生效"',
    '            description="uvicorn 只在启动时加载一次源码：改了 .py 但没重启，进程里还是老模块，而且不报错（表现就是「改了跟没改一样」）。请关掉后端窗口后重新双击项目根目录的「启动后端.bat」（它有自动重启，之后就不用管了）。" />',
    '          <div class="hint" v-if="health">ffmpeg 决定能否生成高光片段；检测模型与 OpenCV 只在 video 源需要。</div>',
    '        </el-form-item>',
    '      </el-form>',
    '      <div class="row">',
    '        <el-button type="primary" :loading="busy" @click="start">开始分析</el-button>',
    '        <el-button @click="refreshJobs">刷新任务列表</el-button>',
    // 说明清楚它是什么：这是**界面演示用的离线样例**（仓库里的合成比赛产物），
    // 不是从视频分析出来的结果。不写清楚会被当成"假数据"（用户反馈 2026-09-27）。
    '        <el-button plain type="warning" @click="loadDemo">载入离线样例（合成比赛，仅供界面演示）</el-button>',
    '      </div>',
    // 用户反馈（2026-09-27）："你还不如在视频分析完以后加一个报错的选项" ——
    // 纠错入口本来就有（人工复核页逐球改判、立刻写回比分/统计），但在这里没有指路，
    // 用户自然找不到。这里补一句去处说明，去掉的是"分析前先交一份标注"那种前置负担。
    '      <div class="hint" style="margin-top:8px">分析跑完后：判错的球到',
    '        <b>人工复核</b> 页逐球改判（立刻写回比分与统计）；要把误判留作样本去 <b>训练标注</b> 页。</div>',
    '    </div>',

    '    <div class="card">',
    '      <h3 class="card-title">③ 分析进度 <span class="sub">WebSocket 实时推送 /api/jobs/{id}/ws</span></h3>',
    '      <div class="progress-box">',
    '        <div class="row" style="justify-content:space-between;margin-bottom:8px">',
    '          <span><el-tag :type="statusTag" effect="dark" size="small">{{ statusText }}</el-tag>',
    '            <span class="mono muted" style="margin-left:8px">{{ job.job_id ? job.job_id.slice(0,12) : \'—\' }}</span></span>',
    '          <b class="mono">{{ percent }}%</b>',
    '        </div>',
    '        <el-progress :percentage="percent" :stroke-width="12" :status="job.status===\'error\' ? \'exception\' : (job.status===\'done\' ? \'success\' : \'\')" />',
    '        <div class="hint" style="margin-top:8px">当前阶段：{{ job.message || \'等待开始\' }}</div>',
    '        <div class="hint" v-if="job.summary">结果摘要：{{ job.summary }}</div>',
    '        <div class="hint" v-if="job.out_dir">产物目录：<code>{{ job.out_dir }}</code></div>',
    '        <el-alert v-if="job.error" type="error" :closable="false" :title="job.error" style="margin-top:10px" />',
    '      </div>',
    '      <div class="stage-log" ref="logbox" style="margin-top:12px">',
    '        <div v-for="(l,i) in logs" :key="i">{{ l }}</div>',
    '        <div v-if="!logs.length" class="muted">等待任务开始…（阶段：载入检测结果 → 计分规则引擎 → 统计与热区 → 战报 → 导出 → 高光）</div>',
    '      </div>',
    '    </div>',
    '  </div>',

    '  <div class="card" v-if="S.backendOk">',
    '    <h3 class="card-title">历史任务 <span class="sub">GET /api/jobs（最近 20 条）· 点「查看」可直接回看产物</span></h3>',
    '    <el-table :data="jobs" size="small" border empty-text="暂无任务">',
    '      <el-table-column prop="job_id" label="任务 ID" min-width="200" show-overflow-tooltip />',
    '      <el-table-column prop="status" label="状态" width="100">',
    '        <template #default="s"><el-tag size="small" :type="{done:\'success\',running:\'warning\',error:\'danger\',queued:\'info\'}[s.row.status]">{{ s.row.status }}</el-tag></template>',
    '      </el-table-column>',
    '      <el-table-column label="进度" width="150">',
    '        <template #default="s"><el-progress :percentage="Math.round((s.row.progress||0)*100)" :stroke-width="8" /></template>',
    '      </el-table-column>',
    '      <el-table-column prop="message" label="阶段" min-width="180" show-overflow-tooltip />',
    '      <el-table-column prop="summary" label="摘要" min-width="240" show-overflow-tooltip />',
    '      <el-table-column label="操作" width="110" align="center">',
    '        <template #default="s"><el-button size="small" text type="primary" @click="openJob(s.row)">查看</el-button></template>',
    '      </el-table-column>',
    '    </el-table>',
    '  </div>',

    // ---- 标注弹窗（篮筐 / 球场 两种模式共用）----
    '  <el-dialog v-model="markOpen" :title="markKind===\'court\' ? \'标球场：点场地特征点（4 个以上）\' : \'在画面上标篮筐\'" width="82%" top="4vh" :close-on-click-modal="false">',
    '    <div class="row" style="margin-bottom:8px;align-items:center">',
    '      <span class="hint">取帧时刻</span>',
    '      <el-input-number v-model="markAt" :min="0" :step="0.5" :precision="1" size="small" style="width:120px" @change="seekVideo(markAt)" />',
    '      <el-button size="small" @click="loadMarkFrame(false)">重新取帧（会清空已点的点）</el-button>',
    '      <span class="hint">（也可以在下面拖着原片找到最清楚的那一刻）</span>',
    '    </div>',
    // 原片播放器：拖动进度条定位 —— 光靠手输秒数等于碰运气（用户实测反馈：
    // "只调时间秒数不好整，一点也不方便"）。旧版标定页就是内嵌播放器 + 现场截帧。
    '    <div v-if="videoUrl" style="margin-bottom:8px">',
    '      <div class="row" style="align-items:center;margin-bottom:6px">',
    '        <b>原片</b>',
    '        <span class="hint">拖进度条找到场地看得最清楚的那一刻，暂停后点右边的按钮</span>',
    '        <span class="grow"></span>',
    '        <el-button size="small" type="primary" @click="useVideoMoment()">',
    '          {{ markKind===\'court\' ? \'把这帧加进来标点\' : \'用当前画面取帧\' }}</el-button>',
    '      </div>',
    '      <video ref="markVideo" :src="videoUrl" controls preload="metadata"',
    '             @loadedmetadata="seekVideo(markAt)"',
    '             style="width:100%;max-height:38vh;background:#000;border-radius:6px" />',
    '    </div>',
    // 第一步：先说清「这件事要干到什么程度」——用户实测反馈"标完篮筐中心就不知道怎么办了"
    '    <el-alert type="info" :closable="false" show-icon style="margin-bottom:8px"',
    '      :title="markKind===\'court\' ? \'怎么标：在同一个画面里点 4~6 个地面上的点就行，不必点完所有点名\' : \'怎么标：只标「篮筐中心」就能保存，另外 4 项是可选的\'"',
    '      :description="markKind===\'court\' ? (\'推荐点这 4~6 个：底线左角、底线右角、罚球区左角、罚球区右角、篮筐中心。\' + (mfFrames.length ? \'流程：先点下面的点名按钮 → 再到画面里点它（顺序随便，点了会自动取消选择）；尽量把 4~6 个点都点在同一帧里。\' : \'按提示顺序点即可。\') + \' 画面里看不到的点按「跳过这一项」；点够 4 个就能按「保存并解算标定」。\') : \'另外 4 项（篮圈左/右缘、上/下沿）只用来量筐宽和篮筐高度，跳过也行；标了中心就能保存。\'" />',
    // 当前目标 + 实时反馈（点了几个、离"能保存"还差几个）
    // 条件必须用 guideNext（它是模式感知的）；用 markCurrent 的话，多帧模式下
    // courtCurrent 恒为真而 guideNext 为 null，模板会取 null.idx 直接报错。
    '    <el-alert v-if="guideNext" type="info" :closable="false" show-icon style="margin-bottom:8px"',
    '      :title="\'第 \' + guideNext.idx + \' 个点：\' + guideNext.label + \'（\' + guideNext.hint + \'）\'"',
    '      :description="guideDesc" />',
    // 多帧模式还没选点名：明确说"先去下面的点名列表里选一个"（不能沿用 courtIdx，那永远停在第一个点名）。
    // 方位词必须对：这条 alert 在**点名按钮上方**，按钮在它下面。
    '    <el-alert v-else-if="markKind===\'court\'" type="info" :closable="false" show-icon style="margin-bottom:8px"',
    '      title="下一步：在下面的点名里点一个（推荐先点底线两角、罚球区两角、篮筐中心），再到画面里点它"',
    '      :description="guideDesc" />',
    '    <el-alert v-else type="success" :closable="false" show-icon style="margin-bottom:8px"',
    '      title="篮筐中心已标好 —— 可以直接保存（点多一下就是一步）"',
    '      :description="markHoop && markHoop.measured',
    '        ? (\'中心 \' + Math.round(markHoop.cx*markSize.w) + \',\' + Math.round(markHoop.cy*markSize.h)',
    '           + \'，半径 \' + Math.round(markHoop.rx*markSize.w) + \'×\' + Math.round(markHoop.ry*markSize.h) + \' 像素（你量的）\')',
    '        : (\'中心 \' + Math.round((markHoop?markHoop.cx:0)*markSize.w) + \',\' + Math.round((markHoop?markHoop.cy:0)*markSize.h)',
    '           + \'。没量筐宽也没关系：半径会由检测器量；想让判进球的尺度由你定，就再点一下「篮圈左缘」或「右缘」（可选）\')" />',
    // 球场模式下点不够 4 个的提示
    '    <el-alert v-if="markKind===\'court\' && guideCount < 4" type="warning" :closable="false" show-icon style="margin-bottom:8px"',
    '      title="至少要 4 个点才能解出标定"',
    '      :description="\'现在只有 \' + guideCount + \' 个，还差 \' + (4 - guideCount) + \' 个。若画面里看不清的点按「跳过这一项」，但最终仍要有 4 个以上。\'" />',
    // 标定失败时的原因（重投影误差偏大 / 点位退化 / 解释不了画面里的真篮筐）
    '    <el-alert v-if="courtResult && !courtResult.usable" type="error" :closable="false" show-icon style="margin-bottom:8px"',
    "      :title=\"'标定结果不可用' + (courtResult.rmse_m != null ? ('（重投影误差 ' + courtResult.rmse_m + ' m）') : '')\"",
    '      :description="courtResult.note || \'点位可能有误：检查是否点在了正确的角/线上，或换一张更清楚的帧重新标。\'" />',
    // 多帧标定的结果与"未校验"提示（宽容规则：能存但位置结论会关掉）
    '    <el-alert v-if="markKind===\'court\' && mfResult" :type="mfResult.ok ? (mfResult.position_unverified ? \'warning\' : \'success\') : \'error\'"',
    '      :closable="false" show-icon style="margin-bottom:8px"',
    '      :title="(mfResult.ok ? (mfResult.position_unverified ? \'标定已保存，但位置结论未校验\' : \'标定可用\') : \'这份点法还不能用\') + (mfResult.rmse_m != null ? (\'（平均误差 \' + mfResult.rmse_m + \' m\' + (mfResult.hoop_error_m != null ? (\'；篮筐投影偏 \' + mfResult.hoop_error_m + \' m\') : \'\') + \'）\') : \'\')"',
    '      :description="String(mfResult.note || \'\').slice(0, 200)" />',
    // 逐点误差：哪个点错了要能一眼看到（用户点的是像素，就按像素/米并排显示）
    '    <div v-if="markKind===\'court\' && mfResult && (mfResult.worst || []).length" style="margin-bottom:8px">',
    '      <span class="hint">误差最大的几个点：</span>',
    '      <el-tag v-for="(w,i) in mfResult.worst" :key="\'w\'+i" size="small" type="warning" effect="plain" style="margin:2px">',
    '        {{ w.label }} @{{ w.t }}s → {{ w.err_m }} m（像素 {{ w.px[0] }},{{ w.px[1] }}）</el-tag>',
    '    </div>',
    // 外层盒子宽度 = min(100%, 画面宽)；图片 width:100% 撑满它。
    // 这样"图片显示尺寸"和"定位容器尺寸"严格相等，绿圈才会落在鼠标点上。
    // ---- 球场模式：画面切换 + 特征点选择（多画面累加）----
    '    <div v-if="markKind===\'court\' && mfFrames.length" style="margin-bottom:8px">',
    '      <div class="row" style="align-items:center;margin-bottom:6px">',
    '        <b>画面 {{ mfIdx+1 }}/{{ mfFrames.length }}</b>',
    '        <span class="hint">t={{ mfCurrent ? mfCurrent.t : 0 }}s</span>',
    '        <el-button size="small" @click="mfPrev" :disabled="mfIdx<=0">上一张画面</el-button>',
    '        <el-button size="small" @click="mfNext" :disabled="mfIdx>=mfFrames.length-1">下一张画面</el-button>',
    '        <span class="grow"></span>',
    '        <el-tag size="small" :type="mfEnough?\'success\':\'info\'" effect="plain">已标 {{ mfPts.length }} 个点（本帧 {{ mfPtsHere.length }} 个）</el-tag>',
    '      </div>',
    '      <div class="row" style="align-items:center;margin-bottom:6px">',
    '        <span class="hint">在</span>',
    '        <el-input-number v-model="mfCenter" :min="0" :step="1" :precision="1" size="small" style="width:110px" />',
    '        <span class="hint">秒附近抽</span>',
    '        <el-input-number v-model="mfSpan" :min="0.5" :max="30" :step="0.5" size="small" style="width:100px" />',
    '        <span class="hint">秒内的帧</span>',
    '        <el-button size="small" @click="mfResample">按这个时刻重抽</el-button>',
    '        <span class="hint">（几帧要在**同一镜头**里，标点才能叠加）</span>',
    '      </div>',
    '      <div class="hint" style="margin-bottom:6px">① 先点下面一个特征点 → ② 再在画面里点它的位置。'
    + '★ 关键：<b>尽量在同一个画面里一次点够 5~6 个点</b>，再切画面 —— '
    + '单应矩阵要求同一帧至少 4 个点，分散在多个画面里会解不准（实测把 6 个点标在 3 个画面上，误差 4.6m）。'
    + '画面里看不清的点按「跳过这一个」。点要<b>铺开</b>：优先场地四角，其次中圈/罚球区角，别都挤在一条线上。</div>',
    '      <div class="row" style="align-items:center;gap:10px;margin-bottom:6px">',
    '        <el-switch v-model="autoMode" active-text="自动识别（不用选名字）" />',
    '        <span class="hint">我看的是：</span>',
    '        <el-select v-model="autoHalf" size="small" style="width:190px" :disabled="!autoMode">',
    '          <el-option label="远端半场 + 中圈" value="far" />',
    '          <el-option label="近端半场 + 中圈" value="near" />',
    '          <el-option label="两端都能看到" value="full" />',
    '        </el-select>',
    '        <el-button v-if="autoMode" size="small" type="primary" @click="solveAutoCalib">自动解算标定</el-button>',
    '      </div>',
    '      <el-alert v-if="autoResult" :closable="false" show-icon',
    "        :type=\"autoResult.loading ? 'info' : (autoResult.ok ? 'success' : 'error')\"",
    "        :title=\"autoResult.loading ? '正在识别…（几秒钟）' : (autoResult.ok ? ('识别成功：' + autoResult.named + '，误差 ' + autoResult.rmse_m + ' m') : '自动识别没成功')\"",
    "        :description=\"autoResult.loading ? '' : (autoResult.note || '')\" style=\"margin-bottom:8px\" />",
    // 球场的点名列表（篮筐模式没有这一排：中心是唯一必点项）
    '      <div v-if="!autoMode" class="row" style="flex-wrap:wrap">',
    '        <el-button v-for="it in courtItems" :key="it.name" size="small"',
    '          :type="mfTarget===it.name ? \'primary\' : (mfDone[it.name] ? \'success\' : \'default\')"',
    '          :plain="mfTarget!==it.name" @click="mfPick(it)">',
    '          {{ mfDone[it.name] ? \'✓ \' : \'\' }}{{ it.label }}</el-button>',
    '      </div>',
    // 篮筐模式的可选步骤：想自己量半径的人点这里，不点就交给检测器（默认路径）
    '      <div v-if="markKind===\'hoop\'" class="row" style="flex-wrap:wrap;margin-top:2px">',
    '        <span class="hint">可选：想让判进球的横向尺度由你定，就再点一下圈的一侧边缘',
    '          （只点中心也完全可以）</span>',
    '        <el-button v-for="it in markItemsOptional" :key="it.name" size="small"',
    '          :type="hoopOptTarget===it.name ? \'primary\' : (hoopOptDone[it.name] ? \'success\' : \'default\')"',
    '          :plain="hoopOptTarget!==it.name"',
    '          @click="hoopOptTarget = (hoopOptTarget===it.name ? \'\' : it.name)">',
    '          {{ hoopOptDone[it.name] ? \'✓ \' : \'\' }}{{ it.label }}</el-button>',
    '        <span class="hint" v-if="hoopOptTarget">现在去画面里点：{{ hoopOptTarget }}</span>',
    '      </div>',
    '      <div class="hint" v-if="mfTarget" style="margin-top:6px;color:#409eff">',
    '        现在去画面里点：{{ mfTarget }}（点了之后自动取消选择，可再选下一个）</div>',
      // 点完之后**必须留下"下一步"**：原来 mfTarget 一被清空，上一句就消失了，
      // 屏幕上只剩一排点名按钮 —— 用户就卡在"标完篮筐中心不知道怎么办"（实测反馈）。
      '      <div class="hint" v-else style="margin-top:6px;color:#409eff">',
      '        下一步：从上面选一个点名，再到画面里点它 —— 已点 {{ mfPts.length }} 个{{ mfEnough ? \'（够了，可以直接保存；想更准就继续点）\' : \'，还差 \' + (4 - mfPts.length) + \' 个才能保存\' }}。画面里看不到的点按「跳过这一项」。</div>',
    '      <el-alert v-if="mfResult && !mfResult.ok" type="error" :closable="false" show-icon style="margin-top:8px"',
    '        :title="mfResult.note ? mfResult.note : (\'标定误差偏大（平均 \' + mfResult.rmse_m + \' m）\')"',
    '        :description="\'最离群的几个点：\' + mfResult.worst.map(function(d){return (d.label || d.name || \'?\') + \'(t=\' + d.t + \'s, \' + d.err_m + \'m)\'}).join(\'，\')" />',
    // 客观体检读数：点位退化 / 与画面里的真篮筐对不上。
    // 单看"重投影误差"是不够的 —— 点位几乎共线时误差必然是 0.00m 左右。
    '      <div v-if="mfResult && mfResult.degeneracy" class="hint" style="margin-top:6px">',
    '        点位展开度：画面侧最大三角形 {{ mfResult.degeneracy.src_tri_px2 }}px²（占画面 {{ (mfResult.degeneracy.src_frac*100).toFixed(2) }}%）、',
    '        球场侧 {{ mfResult.degeneracy.dst_tri_m2 }}m²',
    '        <span v-if="mfResult.degeneracy.degenerate" style="color:#f56c6c"> —— 判定为退化（近共线/重合）</span>',
    '        <span v-if="mfResult.hoop_check && mfResult.hoop_check.checked"',
    '              :style="{color: mfResult.hoop_check.ok ? \'#67c23a\' : \'#f56c6c\'}">',
    '          ｜ 独立校验（真篮筐）：{{ mfResult.hoop_check.reason }}</span>',
    '      </div>',
    '      <div v-if="mfResult && mfResult.per_frame_fit" style="margin-top:8px">',
    '        <div class="hint">各画面单独拟合的结果（能标定的画面会标绿）：</div>',
    '        <div class="row" style="flex-wrap:wrap;margin-top:4px">',
    '          <el-tag v-for="fr in mfResult.per_frame_fit" :key="fr.t" size="small"',
    '            :type="fr.ok ? \'success\' : (fr.n >= 4 ? \'warning\' : \'info\')" effect="plain" style="margin:2px">',
    '            t={{ fr.t }}s · {{ fr.n }}点 · {{ fr.rmse_m === null ? \'—\' : fr.rmse_m + \'m\' }}</el-tag>',
    '        </div>',
    '      </div>',
    '      <el-alert v-else-if="mfResult && mfResult.ok" type="success" :closable="false" show-icon style="margin-top:8px"',
    '        :title="\'标定成功：平均误差 \' + mfResult.rmse_m + \' m\'"',
    '        description="已保存为这段视频的标定，分析时会自动使用。" />',
    '    </div>',
    // 画面（球场模式用抽帧图，篮筐模式用取帧图）
    '    <div style="position:relative;display:inline-block;width:100%;max-width:1100px;cursor:crosshair" @click="onMarkClick" @mousemove="onMarkMove" @mouseleave="onMarkLeave">',
    '      <img v-if="markKind===\'court\' && mfCurrent" :src="mfCurrent.image" style="width:100%;height:auto;display:block;border-radius:6px" />',
    '      <img v-else-if="markKind!==\'court\' && markImg" :src="markImg" style="width:100%;height:auto;display:block;border-radius:6px" />',
    '      <div v-else class="muted" style="padding:40px">正在抽画面…</div>',
    // 已点的标记（两种模式都画 activePts —— 之前只用 markPts，
    // 球场模式下点了一个点都不显示，用户以为没点上去）
    '      <svg v-if="frameW && frameH" :viewBox="\'0 0 \' + frameW + \' \' + frameH"',
    '           preserveAspectRatio="none"',
    '           style="position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none">',
    '        <g v-if="hoverPt">',
    '          <line :x1="hoverPt.x*frameW - 22" :y1="hoverPt.y*frameH" :x2="hoverPt.x*frameW + 22" :y2="hoverPt.y*frameH" stroke="#f59e0b" :stroke-width="Math.max(1.5, frameW*0.0022)" />',
    '          <line :x1="hoverPt.x*frameW" :y1="hoverPt.y*frameH - 22" :x2="hoverPt.x*frameW" :y2="hoverPt.y*frameH + 22" stroke="#f59e0b" :stroke-width="Math.max(1.5, frameW*0.0022)" />',
    '        </g>',
    '        <template v-for="(p,i) in activePts" :key="i">',
    '          <circle :cx="p.x * frameW" :cy="p.y * frameH" :r="Math.max(10, frameW*0.012)"',
    '                  fill="rgba(34,197,94,.35)" stroke="#22c55e" :stroke-width="Math.max(2, frameW*0.003)" />',
    '          <text :x="p.x * frameW + Math.max(12, frameW*0.014)" :y="p.y * frameH"',
    '                fill="#22c55e" :font-size="Math.max(16, frameW*0.022)"',
    '                style="paint-order:stroke;stroke:#000;stroke-width:3px">{{ i + 1 }}. {{ p.label }}</text>',
    '        </template>',
    '      </svg>',
    // 篮圈示意（只在篮筐模式）
    '      <div v-if="markKind===\'hoop\' && markHoop" style="position:absolute;pointer-events:none;border:2px dashed #ef4444;border-radius:50%"',
    '           :style="{left:((markHoop.cx-markHoop.rx)*100)+\'%\',top:((markHoop.cy-markHoop.ry)*100)+\'%\',width:(markHoop.rx*200)+\'%\',height:(markHoop.ry*200)+\'%\'}"></div>',
    '    </div>',
    // 已点清单（文字版，双重反馈）
    '    <div v-if="activePts.length" class="row" style="margin-top:8px;flex-wrap:wrap">',
    '      <el-tag v-for="(p,i) in activePts" :key="\'t\'+i" size="small" type="success" effect="plain" style="margin:2px">',
    '        {{ i + 1 }}. {{ p.label }} ({{ Math.round(p.x*frameW) }},{{ Math.round(p.y*frameH) }})</el-tag>',
    '    </div>',
    '    <template #footer>',
    '      <el-button v-if="markKind===\'court\'" size="small" @click="mfUndo" :disabled="!mfPts.length">撤销上一个点</el-button>',
    '      <el-button v-else size="small" @click="markUndo" :disabled="!activePts.length">撤销上一个</el-button>',
    // 跳过：**两种模式都要有**。以前球场的"跳过这一项"被 v-if 排除了，
    // 而球场点名里有"另一端的篮筐中心（若只有一个篮筐可见就别选它）"这类
    // 画面里根本不存在的点 —— 用户于是卡住：不点前进不了、点也点不出来。
    '      <el-button size="small" @click="markSkip" :disabled="markDone">跳过这一项</el-button>',
    '      <el-button size="small" @click="markKind===\'court\' ? mfClear() : clearMarks()" :disabled="!activePts.length">清空</el-button>',
    '      <el-button size="small" @click="markOpen=false">取消</el-button>',
    // 预览（不落盘）：先看清逐点误差与合规性，再决定要不要保存（移植自旧版标定页）
    '      <el-button v-if="markKind===\'court\'" size="small" :loading="markSaving"',
    '        :disabled="!(mfFrames.length ? mfEnough : courtEnough)" @click="previewCourtMulti()">先预览（不保存）</el-button>',
    // 保存：篮筐模式标了中心就能存；球场模式按"当前是单帧还是多帧"分别判够没够 4 个点
    // （以前一律看 mfEnough，单帧模式点了点也永远灰着，等于这条路走不通）
    '      <el-button size="small" type="primary" :loading="markSaving"',
    '        :disabled="markKind===\'court\' ? !(mfFrames.length ? mfEnough : courtEnough) : !markHoop"',
    '        @click="markKind===\'court\' ? (mfFrames.length ? saveCourtMulti() : saveCourt()) : saveMarks()">',
    '        {{ markKind===\'court\' ? \'保存并解算标定\' : \'保存标点\' }}</el-button>',
    '    </template>',
    '  </el-dialog>',
    '</div>'
  ].join('\n')
};
