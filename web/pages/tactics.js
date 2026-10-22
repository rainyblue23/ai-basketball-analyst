// Display interpolation only; never changes saved positions or statistics.
function tacticsPopulationIssue(f){
  if(!f)return false;
  if(f.population_quality && f.population_quality.valid===false)return true;
  var counts={};(f.players||[]).forEach(function(p){counts[p[1]]=(counts[p[1]]||0)+1;});
  return (f.players||[]).length>10 || Object.keys(counts).some(function(k){return ['unknown','UNKNOWN','','?'].indexOf(k)<0 && counts[k]>5;});
}
function interpolateTacticsFrame(a,b,t){
  if(!a)return null;
  if(t<a.t || t-a.t>.6)return Object.assign({},a,{players:[],ball:null,position_quality:{valid:false,reason:'display_frame_expired'}});
  if(!b || a.segment===undefined || a.segment!==b.segment || b.t-a.t<=0 || b.t-a.t>.6 ||
     (a.population_quality&&a.population_quality.valid===false) || (b.population_quality&&b.population_quality.valid===false) ||
     !(a.players||[]).length || !(b.players||[]).length)return a;
  var f=Math.max(0,Math.min(1,(t-a.t)/(b.t-a.t))),by={};b.players.forEach(function(p){by[p[0]]=p;});
  var players=a.players.map(function(p){var q=by[p[0]];if(!q||q[1]!==p[1]||Math.hypot(q[2]-p[2],q[3]-p[3])>12*(b.t-a.t))return p;return [p[0],p[1],p[2]+(q[2]-p[2])*f,p[3]+(q[3]-p[3])*f];});
  return Object.assign({},a,{players:players,display_interpolated:true});
}
/* ==========================================================================
   pages/tactics.js —— 页面 5：战术分析（核心展示页）
   --------------------------------------------------------------------------
   数据来源（懒加载：只有真的打开这一页才去拉，不拖慢总览/统计页）：
     GET /api/games/{id}/tactics          tactics.json
        possession  回合统计（total / by_team / avg_passes / list / spells）
        passes      传球事件 + 排行榜（events / leaderboard）
        pass_network{home,away}  有向传球网络（nodes 带平均站位 x/d、edges 带次数）
        formation   {offense:{team:[段]}, defense:{team:[段]}, summary:{team:{...}}}
        spacing     {teams:{team:{area,...}}, timeline:[{t,team,area,...}]}
        insights    可直接展示的战术结论
     GET /api/games/{id}/tactics/frames   俯视战术图逐帧数据
        {available, count, frames:[{t, side, ball:[x,y], players:[[id,team,x,y],...]}]}

   四块内容（对应方案里的"战术分析页"清单）：
     ① 俯视战术图播放器（带球员轨迹尾迹、球、可拖进度条）
     ② 传球网络图（画在半场上，节点=球员平均站位、边宽=传球次数）
     ③ 阵型识别结果（进攻落位 / 防守阵型的时间轴 + 占比）
     ④ 间距曲线（凸包面积 / 平均间距 / 宽度 / 纵深，两队对比）

   为什么战术图只画"一张半场"：后端 tactics.py 把两侧进攻折叠成
   「局部进攻坐标」(x, d=|y|)，被进攻的篮筐永远在 (0,1.575)。
   所以一张半场就能同时表达左右两侧的进攻，且两队可以直接叠着比。
   ========================================================================== */
window.PAGES = window.PAGES || {};

window.PAGES['tactics'] = {
  name: 'page-tactics',
  data: function () {
    return {
      S: window.STORE,
      // 球场底图与叠加层用同一个 viewBox，保证像素级对齐
      courtSVG: window.Court.courtSVG({ view: 'full' }),
      courtView: 'full',
      loading: false,
      err: '',
      // 在飞的加载 Promise（同一时刻只允许一份，见 load()）
      _loadPromise: null,
      // 播放器
      altJobs: [],          // 其它「有战术数据」的任务（空状态下一键切换）
      playing: false,
      playT: 0,
      speed: 1,
      showTrails: true,
      raf: null,
      _last: 0,
      // 传球网络
      netTeam: 'all',
      netFocus: '',
      // 间距曲线
      metric: 'area',
      METRICS: [
        { key: 'area', label: '站位面积', unit: 'm²', meaning:'把同队最外侧球员的位置连成一个圈，计算围住的面积（也叫凸包面积）。', reading:'面积越大，队员整体站得越散；面积越小，站位越集中。' },
        { key: 'mean_dist', label: '平均间距', unit: 'm', meaning:'计算同队球员两两之间的距离，再取平均值。', reading:'例如 5 米，表示队员之间的平均距离约为 5 米；数值越大，彼此越分散。' },
        { key: 'width', label: '左右展开宽度', unit: 'm', meaning:'同队最左侧与最右侧球员之间的横向距离。', reading:'数值越大，球队越向球场两边展开。' },
        { key: 'depth', label: '前后展开距离', unit: 'm', meaning:'沿篮筐到中场的方向，同队最靠前与最靠后球员之间的距离（也叫纵深）。', reading:'数值越大，队员前后站得越开。' },
        { key: 'radius', label: '整体离篮筐距离', unit: 'm', meaning:'先计算同队球员的平均位置（站位中心），再计算这个位置到该半场篮筐的距离。', reading:'数值越小，整体站位越靠近篮筐；它不是每名球员到篮筐距离的平均值。' }
      ]
    };
  },
  computed: {
    game: function () { return this.S.game; },
    tac: function () { return this.S.tactics; },
    summary: function () { return (this.game && this.game.tactics) || {}; },
    frames: function () {
      var d = this.S.tacticsFrames;
      if (!d) return [];
      return Array.isArray(d) ? d : (d.frames || []);
    },
    duration: function () {
      return (this.game && this.game.duration) || (this.frames.length ? this.frames[this.frames.length - 1].t : 0);
    },
    hasTactics: function () {
      return !!(this.tac && this.tac.available);
    },
    reason: function () {
      if (this.tac && !this.tac.available) return this.tac.reason || '';
      return this.summary.reason || '';
    },
    frameQuality: function () {
      var frames=this.frames||[], valid=0;
      frames.forEach(function(f){
        var n=(f.players||[]).length;
        if(n>0 && !tacticsPopulationIssue(f))valid++;
      });
      return {valid:valid,total:frames.length,pct:frames.length?valid/frames.length:0};
    },
    spacingQuality: function () {
      var rows=(this.tac && this.tac.spacing && this.tac.spacing.timeline)||[];
      var times={}; rows.forEach(function(r){times[String(r.t)]=true;});
      var observed=Object.keys(times).length;
      var step=Number((this.tac && this.tac.config && this.tac.config.frame_step)||1);
      var expected=this.duration>0?Math.floor(this.duration/step)+1:0;
      return {observed:observed,expected:expected,pct:expected?observed/expected:0};
    },
    spacingObservedSubset: function () {
      return !!(this.tac && this.tac.config && this.tac.config.spacing_observed_subset);
    },
    hasBallTrack: function () {
      return !!(this.tac && this.tac.coverage && Number(this.tac.coverage.ball_samples)>0);
    },
    canInferAttack: function () {
      return this.hasBallTrack && !!(this.tac && this.tac.possession && Number(this.tac.possession.total)>0);
    },

    // ---------------- 播放器 ----------------
    frameIdx: function () {
      var f = this.frames;
      if (!f.length) return 0;
      var t = this.playT, lo = 0, hi = f.length - 1;
      if (t <= f[0].t) return 0;
      if (t >= f[hi].t) return hi;
      while (lo < hi) {
        var mid = (lo + hi + 1) >> 1;
        if (f[mid].t <= t) lo = mid; else hi = mid - 1;
      }
      return lo;
    },
    frame: function () {
      var a=this.frames[this.frameIdx],b=this.frames[this.frameIdx+1];
      return interpolateTacticsFrame(a,b,this.playT);
    },
    positionMissing: function () {
      return !!(this.frame && this.frame.position_quality && this.frame.position_quality.valid === false);
    },
    registrationMissing: function () {
      return !!(this.frame && this.frame.position_quality && this.frame.position_quality.reason === 'court_registration_unavailable');
    },
    populationIssue: function () {
      return tacticsPopulationIssue(this.frame);
    },
    populationNeedsRebuild: function () {
      if(this.tac && this.tac.population_quality)return false;
      return this.frames.some(tacticsPopulationIssue);
    },
    teamOf: function () {
      var m = {};
      (this.frame ? this.frame.players : []).forEach(function (p) { m[p[0]] = p[1]; });
      return m;
    },
    /** 最近 10 帧的轨迹尾迹（按球员 id 聚合） */
    trails: function () {
      if (!this.showTrails || !this.frames.length || this.populationIssue) return {};
      var out = {}, i0 = Math.max(0, this.frameIdx - 10);
      for (var i = i0; i <= this.frameIdx; i++) {
        if(this.frames[i].segment!==this.frame.segment || !(this.frames[i].players||[]).length){out={};continue;}
        (this.frames[i].players || []).forEach(function (p) {
          if (Object.prototype.hasOwnProperty.call(this.teamOf,p[0])){var seq=out[p[0]]||[];if(seq.length && Math.hypot(p[2]-seq[seq.length-1][0],p[3]-seq[seq.length-1][1])>6)seq=[];seq.push([p[2],p[3]]);out[p[0]]=seq;}
        }, this);
      }
      return out;
    },
    overlayHTML: function () {
      if (!this.frame || this.populationIssue) return '';
      var f = this.frame;
      var teams = this.teamOf;
      var trails = {};
      Object.keys(this.trails).forEach(function (k) { trails[k] = this.trails[k]; }, this);
      return window.Court.tacticsPlayersLayer(f, trails, {
        showTrails: this.showTrails, teamOf: teams, players:this.S.players || [], view:this.courtView
      });
    },
    timeLabel: function () { return window.D.mmss(this.playT); },

    // ---------------- 传球网络 ----------------
    net: function () {
      var t = this.tac;
      if (!t || !t.pass_network) return { nodes: [], edges: [] };
      var sides=this.netTeam==='all' ? (this.teams || ['home','away']) : [this.netTeam];
      var players={};(this.S.players||[]).forEach(function(p){players[p.player_id]=p;});
      var nodes=[],edges=[];
      sides.forEach(function(side){var n=t.pass_network[side] || {};
        (n.nodes||[]).forEach(function(p){nodes.push(Object.assign({},p,players[p.id]||{},{id:p.id,team:p.team||side}));});
        edges=edges.concat(n.edges||[]);
      });
      return {nodes:nodes,edges:edges};
    },
    netHTML: function () {
      if (!this.hasTactics) return '';
      return window.Court.passNetLayer(this.net, { team: this.netTeam, focus:this.netFocus });
    },
    netEdges: function () {
      var self = this;
      var names = {};
      (this.net.nodes || []).forEach(function (n) { names[n.id] = D.tacticsPlayerLabel(n); });
      return (this.net.edges || []).filter(function(e){return !self.netFocus || e.source===self.netFocus || e.target===self.netFocus;}).map(function (e) {
        return {
          from: names[e.source] || D.tacticsPlayerLabel({player_id:e.source}), to: names[e.target] || D.tacticsPlayerLabel({player_id:e.target}),
          value: e.value
        };
      });
    },

    // ---------------- 阵型 ----------------
    formationGlossary: function () {
      var explanations={
        '均衡落位':'球员分布在不同区域，没有明显偏向篮下或三分线外；“均衡”不代表打得更好。',
        '五外拉开':'五人主要站在三分线外，把篮下空间让出来。',
        '四外一内':'通常指四人在外线、一人更靠近篮筐。',
        '三外两内':'通常指三人在外线、两人更靠近篮筐。',
        '双塔（内线为主）':'至少两名球员靠近篮筐，整体偏向篮下；这里按站位命名，不判断身高。',
        '转换进攻':'球员仍在从一侧向另一侧推进，还没有稳定站好进攻位置。',
        '人盯人':'防守球员主要跟随并贴近各自的对手。',
        '2-3 联防':'通常指两人在前、三人在后，分别守住球场区域。',
        '3-2 联防':'通常指三人在前、两人在后，分别守住球场区域。',
        '1-3-1 联防':'通常分成前方一人、中间三人、篮下附近一人的三层站位。',
        '1-2-2 联防':'通常分成前方一人、中间两人、后方两人的三层站位。',
        '收缩联防':'防守队员较集中地站在篮筐附近，优先保护篮下区域。',
        '前场施压（紧逼）':'防守位置向对方推进方向压上，尝试提早干扰持球和传球。',
        '混合防守':'当前站位不明显符合某一种防守形状，系统暂归为混合；不代表已确认具体战术。',
        '人数不足':'画面中可可靠定位的球员太少，无法判断站位形状。'
      };
      var labels=[];
      this.formationRows.forEach(function(row){row.offenseTop.concat(row.defenseTop).forEach(function(x){if(labels.indexOf(x.label)<0)labels.push(x.label);});});
      return labels.map(function(label){return {label:label,text:explanations[label] || '根据当前画面中的球员位置估计的站位形状。'};});
    },
    metricHelp: function () {
      return this.METRICS.find(function(m){return m.key===this.metric;},this) || this.METRICS[0];
    },
    teams: function () { return this.tac && this.tac.team_identity && this.tac.team_identity.verified===false ? ['team_a','team_b'] : ['home', 'away']; },
    rosterLegend: function () { return this.teams[0]==='team_a' ? '蓝色分组A · 橙色分组B · 灰色分队未知；分组尚未核实主客身份。' : '蓝色主队 · 橙色客队 · 灰色分队未知。'; },
    formationRows: function () {
      var t = this.tac;
      if (!t) return [];
      var self = this;
      var out = [];
      this.teams.forEach(function (side) {
        var off = ((t.formation || {}).summary || {})[side] || {};
        out.push({
          side: side,
          name: self.teamName(side),
          offense: (off.offense || [])[0] ? off.offense[0].label : '-',
          offenseTop: (off.offense || []).slice(0, 3),
          defense: (off.defense || [])[0] ? off.defense[0].label : '-',
          defenseTop: (off.defense || []).slice(0, 3)
        });
      });
      return out;
    },
    offBars: function () { return this._bars('offense'); },
    defBars: function () { return this._bars('defense'); },

    // ---------------- 间距曲线 ----------------
    spacingOption: function () {
      var t = this.tac;
      var tl = (t && t.spacing && t.spacing.timeline) || [];
      var m = this.metric;
      var self = this;
      // ⚠️ 必须先按球队过滤再抽稀：timeline 是"同一时刻主客各一条"交替排列的，
      // 直接整体按 i+=step 抽稀会让步长与球队交替同频，结果只剩一支球队
      // （后端也踩过同一个坑，见 tactics.py 里按球队分别抽稀的注释）。
      function pick(side) {
        var rows = tl.filter(function (r) { return r.team === side; }).slice().sort(function(a,b){return a.t-b.t;});
        var st = rows.length > 600 ? Math.ceil(rows.length / 600) : 1;
        var out = [], prev = null;
        for (var i = 0; i < rows.length; i += st) {
          var row=rows[i];
          if(prev && (row.t-prev.t > 1.5*((self.tac && self.tac.config && self.tac.config.frame_step)||1)
              || (row.segment !== undefined && prev.segment !== row.segment)
              || (self.spacingObservedSubset && prev.n !== row.n)))
            out.push([+((prev.t+row.t)/2).toFixed(1), null]);
          out.push(self.spacingObservedSubset ? [+row.t.toFixed(1), row[m], row.n] : [+row.t.toFixed(1), row[m]]);
          prev=row;
        }
        return out;
      }
      return {
        tooltip: { trigger: 'axis', formatter: this.spacingObservedSubset ? function (params) {
          function escape(s){return String(s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
          return params.filter(function(p){return p.value && p.value[1] != null;}).map(function(p){
            return escape(p.seriesName) + ' · ' + p.value[0] + '秒：' + p.value[1] + '（可见 ' + p.value[2] + ' 人）';
          }).join('<br>');
        } : undefined },
        legend: { top: 0, data: this.teams.map(function(side){return self.teamName(side);}) },
        grid: { left: 52, right: 20, top: 34, bottom: 40, containLabel: true },
        xAxis: { type: 'value', name: '时间(秒)', min: 0, max: Math.ceil(this.duration) },
        yAxis: { type: 'value', name: this.METRICS.filter(function (x) { return x.key === m; })[0].label },
        series: [
          { name: this.teamName(this.teams[0]), type: 'line', showSymbol: true, symbolSize: 4,
            smooth: false, connectNulls: false, lineStyle: { width: 2, color: '#3D8BFF' }, itemStyle: { color: '#3D8BFF' },
            data: pick(this.teams[0]) },
          { name: this.teamName(this.teams[1]), type: 'line', showSymbol: true, symbolSize: 4,
            smooth: false, connectNulls: false, lineStyle: { width: 2, color: '#FF7A33' }, itemStyle: { color: '#FF7A33' },
            data: pick(this.teams[1]) }
        ]
      };
    },
    attackSideText: function () {
      var v = (this.tac && this.tac.attack_side) || '';
      return ({ left: '左半场', right: '右半场', mixed: '左右两侧' })[v] || '-';
    },
    spacingTeams: function () {
      var sp = (this.tac && this.tac.spacing && this.tac.spacing.teams) || this.summary.spacing || {};
      var self = this;
      return this.teams.map(function (s) {
        return { side: s, name: self.teamName(s), d: sp[s] || {} };
      });
    }
  },
  methods: {
    selectNetPlayer: function (event) {
      if(event.type==='keydown' && event.key!=='Enter' && event.key!==' ')return;
      var node=event.target.closest('[data-player]');
      if(!node)return;
      event.preventDefault();
      this.netFocus=node.getAttribute('data-player');
    },
    teamName: function (side) { return ((this.tac && this.tac.team_identity && this.tac.team_identity.labels)||{})[side] || window.D.teamName(this.game, side); },
    mmss: function (t) { return window.D.mmss(t); },

    // ---- 数据加载 ----
    load: function () {
      var self = this;
      if (self._loadPromise) return self._loadPromise;
      self.loading = true;
      var requestedJobId = '';
      // 每次进页都针对**当前选中任务**刷新战术产物（force），避免首次进入时拿到
      // bootstrap 之前的演示数据或上一个任务的缓存。延后一微任务，让根组件先启动 bootstrap。
      var request = Promise.resolve().then(function () {
        return window.APP_WAIT_READY ? window.APP_WAIT_READY() : null;
      }).then(function () {
        requestedJobId = self.S.jobId;
        return window.APP_REFRESH_RESULTS ? window.APP_REFRESH_RESULTS() : null;
      }).then(function () {
        return window.APP_TACTICS(true);
      }).then(function () {
        // Keep the selected match; switching requires an explicit user action.
      }).then(function () {
        self.loading = false;
        // 任务可能在请求过程中被切换（顶栏「当前任务」/ 本页一键切换）。丢弃旧任务结果
        // 并跟进新 ID，不能把旧的空状态留在当前页面上。
        if (requestedJobId !== self.S.jobId) {
          self._loadPromise = null;
          return self.load();
        }
        if (!self.hasTactics && self.S.backendOk) self.loadAltJobs();
      }).catch(function (e) {
        self.loading = false;
        self.err = String((e && e.message) || e);
      }).finally(function () {
        self._loadPromise = null;
      });
      self._loadPromise = request;
      return request;
    },
    /** 后端连着但这一场没有战术数据时，列出"有战术数据"的任务供一键切换。 */
    loadAltJobs: function () {
      var self = this;
      return window.API.listJobs(true).then(function (list) {
        var arr = Array.isArray(list) ? list : (list && list.jobs) || [];
        self.altJobs = arr.filter(function (j) {
          return j.status === 'done' && j.has_tactics && j.source !== 'synthetic' && j.job_id !== self.S.jobId;
        }).slice(0, 5);
      }).catch(function () { self.altJobs = []; });
    },
    switchTo: function (id) {
      var self = this;
      self.loading = true;
      window.APP_LOAD_JOB(id).then(function () {
        return self.load();
      }).then(function () {
        self.loading = false;
        self.$message.success('已切换到任务 ' + String(id).slice(0, 8));
      }).catch(function (e) {
        self.loading = false;
        self.$message.error('切换失败：' + ((e && e.message) || e));
      });
    },

    _bars: function (kind) {
      var t = this.tac;
      if (!t) return [];
      var self = this;
      return this.teams.map(function (side) {
        var segs = ((t.formation || {})[kind] || {})[side] || [];
        return {
          side: side,
          name: self.teamName(side),
          html: window.Court.formationBar(segs, {
            total: self.duration || 1,
            colorOf: function (g) { return self.colorOf(g.shape || g.scheme); }
          }),
          count: segs.length
        };
      });
    },
    colorOf: function (label) {
      var map = {
        '五外拉开': '#3D8BFF', '四外一内': '#0ea5e9', '三外两内': '#22a06b',
        '双塔（内线为主）': '#FF7A33', '均衡落位': '#8b5cf6', '转换进攻': '#e5484d',
        '人盯人': '#3D8BFF', '2-3 联防': '#22a06b', '3-2 联防': '#f5a623',
        '1-3-1 联防': '#8b5cf6', '1-2-2 联防': '#0ea5e9', '收缩联防': '#64748b',
        '前场施压（紧逼）': '#e5484d', '混合防守': '#94a3b8'
      };
      return map[label] || '#94a3b8';
    },

    // ---- 播放控制 ----
    toggle: function () {
      if (!this.frames.length) return;
      this.playing = !this.playing;
      if (this.playing) {
        if (this.playT >= this.duration) this.playT = 0;
        this._last = 0;
        this.raf = requestAnimationFrame(this.tick);
      } else if (this.raf) {
        cancelAnimationFrame(this.raf); this.raf = null;
      }
    },
    tick: function (ts) {
      if (!this.playing) return;
      if (!this._last) this._last = ts;
      var dt = Math.min(0.5, (ts - this._last) / 1000);
      this._last = ts;
      this.playT = Math.min(this.duration, this.playT + dt * this.speed);
      if (this.playT >= this.duration) {
        this.playing = false; this.raf = null; return;
      }
      var self = this;
      this.raf = requestAnimationFrame(function (t) { self.tick(t); });
    },
    seek: function (v) { this.playT = Number(v) || 0; },
    jumpTo: function (t) {
      this.playT = Number(t) || 0;
      if (!this.playing) this.playing = true;
      this._last = 0;
      if (this.raf) cancelAnimationFrame(this.raf);
      var self = this;
      this.raf = requestAnimationFrame(function (x) { self.tick(x); });
    },
    step: function (d) { this.seek(Math.max(0, Math.min(this.duration, this.playT + d))); }
  },
  watch: {
    net: function (value) {
      if(this.netFocus && !(value.nodes||[]).some(function(p){return p.id===this.netFocus;},this))this.netFocus='';
    },
    netTeam: function () { this.netFocus=''; },
    // bootstrap 选完任务、或用户在本页/顶栏切换任务时，刷新对应任务的战术结果。
    'S.jobId': function (id, oldId) {
      this.netFocus='';
      if (id && id !== oldId) this.load();
    }
  },
  mounted: function () {
    this.load();
  },
  beforeUnmount: function () {
    this.playing = false;
    if (this.raf) { cancelAnimationFrame(this.raf); this.raf = null; }
  },
  template: [
    '<div class="page">',
    '  <calibration-gaps :game="game" />',
    '  <div class="page-head">',
    '    <h2>战术分析</h2>',
    '    <div class="page-sub">控球 · 传球 · 阵型 · 空间</div>',
    '  </div>',
    // 首次打开要有"已经在做事"的反馈：只给一个骨架屏，用户不知道是在加载
    // 还是又空了一次（队友 d0247ee）。
    '  <div v-if="loading" class="card">',
    '    <el-alert type="info" :closable="false" show-icon',
    '      title="战术分析已打开，正在载入当前任务的战术图与逐帧数据" />',
    '    <el-skeleton :rows="6" animated />',
    '  </div>',
    '  <el-alert v-else-if="!hasTactics" type="warning" :closable="false" show-icon',
    '            title="本场没有战术数据">',
    '    <div style="line-height:1.7">',
    '      <copy-note label="缺少战术数据">{{ reason || "战术层需要球员逐帧球场坐标：真视频要么有一份通过校验的球场标定，要么自动逐帧标定达标（工具会自动尝试）；合成数据源默认自带。" }}</copy-note>',
    '      <div v-if="altJobs.length" style="margin-top:10px">',
    '        <div class="muted">下面这些任务<b>已经有战术数据</b>，点一下直接切过去：</div>',
    '        <el-button v-for="j in altJobs" :key="j.job_id" size="small" type="primary"',
    '                   plain style="margin:6px 6px 0 0" @click="switchTo(j.job_id)">',
    '          {{ (j.video_path || "比赛分析").split(/[\\\\/]/).pop() }} · {{ String(j.job_id).slice(0,8) }}',
    '        </el-button>',
    '      </div>',
    '    </div>',
    '  </el-alert>',
    '  <template v-else>',
    // 位置来源提示：静态标定没通过校验、或**多机位里有一段不可信**时，
    // 结论照给，但必须说清"这些坐标没有经过独立校验"——不能让它冒充已校验。
    // 标题只陈述事实（不再断言"来自自动逐帧标定"：多机位弱段也会把它置真），
    // 具体原因由后端 position_note 给，没有就落在下面的说明里。
    '    <el-alert v-if="tac.position_unverified" type="warning" :closable="false" show-icon style="margin:6px 0 12px">',
    '      <template #title>球员位置<b>未通过独立校验</b></template>',
    '      <div style="line-height:1.7"><copy-note label="说明">',
    '        {{ tac.position_note || "这份坐标没有用画面里的真值点核对过，常见两种原因：① 用的是按球场线自动拟合出来的逐帧标定；② 多机位标定里有一段不可信 —— 那一段时间的球员坐标会整体偏掉（去「上传与分析」打开「叠加球场线自检」，看红色虚线压不压在白线上就能判断是哪一段）。回合/传球/阵型/间距等相对结论可参考，具体坐标可能有系统偏差。" }}',
    '      </copy-note></div>',
    '    </el-alert>',
    '    <el-alert v-if="populationNeedsRebuild" type="warning" :closable="false" title="旧结果含人数异常，战术统计暂停展示，请重新分析。" />',
    '    <el-alert v-if="!canInferAttack" type="warning" :closable="false" show-icon title="没有足够的球轨迹与控球片段：传球和攻防阵型无法判断。">',
    '      <span>下方球员位置与间距只反映检测到的片段；不能据此解释为完整战术或整场表现。</span>',
    '    </el-alert>',
    '    <el-alert v-if="frameQuality.total && frameQuality.pct < 0.5" type="warning" :closable="false" show-icon',
    '      :title="\'俯视图中可用坐标仅覆盖 \' + frameQuality.valid + \' / \' + frameQuality.total + \' 帧\'">',
    '      <span>已跳过人数或坐标异常时刻。球场位置未经独立校验，本结果不代表整场。</span>',
    '    </el-alert>',
    '    <el-alert v-if="spacingQuality.expected && spacingQuality.pct < 0.5" type="warning" :closable="false"',
    '      :title="\'空间指标仅来自 \' + spacingQuality.observed + \' / \' + spacingQuality.expected + \' 个秒级采样点\'">',
    '      <span>曲线会断开展示缺失时段，表格里的平均值也只基于这些有效采样点。</span>',
    '    </el-alert>',
    '    <!-- ① KPI -->',
    '    <div class="kpi-row" v-if="!populationNeedsRebuild">',
    '      <div class="kpi"><div class="v">{{ canInferAttack ? tac.possession.total : "—" }}</div><div class="k">回合数</div></div>',
    '      <div class="kpi"><div class="v">{{ canInferAttack ? tac.passes.total : "—" }}</div><div class="k">成功传球</div></div>',
    '      <div class="kpi"><div class="v">{{ canInferAttack ? tac.passes.turnovers : "—" }}</div><div class="k">球权转换</div></div>',
    '      <div class="kpi"><div class="v">{{ canInferAttack ? tac.possession.avg_passes : "—" }}</div><div class="k">每回合传球</div></div>',
    '      <div class="kpi"><div class="v">{{ canInferAttack ? tac.possession.avg_duration + "s" : "—" }}</div><div class="k">平均回合时长</div></div>',
    '      <div class="kpi"><div class="v">{{ canInferAttack ? attackSideText : "—" }}</div><div class="k">进攻方向</div></div>',
    '    </div>',
    '    <!-- ② 俯视战术图 + 战术亮点 -->',
    '    <el-card shadow="never" class="blk">',
    '      <template #header><b>① 俯视战术图</b>',
    '      </template>',
    '      <p>{{ rosterLegend }} A/B或T开头为临时轨迹编号，不是球衣号码。</p>',
    '      <div class="tac-grid">',
    '        <div>',
    '          <p v-if="populationIssue" role="status">本时刻人数异常，暂停显示阵型。请核对分队与球场边界。</p>',
    '          <p v-else-if="registrationMissing" role="status">此镜头暂未定位球场；特写、转场或缺少对应机位参照时，不显示场上位置。</p>',
    '          <p v-else-if="positionMissing" role="status">本时刻位置未知，暂停显示阵型。</p>',
    '          <div class="court-wrap">',
    '            <div v-html="courtSVG"></div>',
    '            <div class="tac-overlay" v-html="overlayHTML"></div>',
    '          </div>',
    '          <div class="playbar">',
    '            <el-button size="small" :icon="playing ? \'VideoPause\' : \'VideoPlay\'" @click="toggle">',
    '              {{ playing ? "暂停" : "播放" }}</el-button>',
    '            <el-button size="small" @click="step(-5)">-5s</el-button>',
    '            <el-button size="small" @click="step(5)">+5s</el-button>',
    '            <el-slider class="playbar-slider" :model-value="playT" :min="0" :max="duration"',
    '                       :step="0.1" :show-tooltip="false" @input="seek" />',
    '            <span class="mono">{{ timeLabel }} / {{ mmss(duration) }}</span>',
    '            <el-select v-model="speed" size="small" style="width:88px">',
    '              <el-option :value="0.5" label="0.5×" /><el-option :value="1" label="1×" />',
    '              <el-option :value="2" label="2×" /><el-option :value="4" label="4×" />',
    '            </el-select>',
    '            <el-checkbox v-model="showTrails" size="small">轨迹</el-checkbox>',
    '          </div>',
    '        </div>',
    '        <div>',
    '          <div class="blk-title">战术亮点</div>',
    '          <ul class="insight-list">',
    '            <li v-for="(i,k) in (canInferAttack && !populationNeedsRebuild ? tac.insights : [])" :key="k">',
    '              <a href="javascript:void(0)" @click="jumpTo(i.t)">▶ {{ mmss(i.t) }}</a>',
    '              <span>{{ i.text }}</span>',
    '            </li>',
    '            <li v-if="!canInferAttack" class="muted">球轨迹或控球数据不足，暂不生成战术亮点。</li>',
    '            <li v-else-if="!tac.insights.length" class="muted">没有可报告的战术亮点</li>',
    '          </ul>',
    '          <div class="blk-title" style="margin-top:14px">口径说明</div>',
    '          <div class="muted small">',
    '            <copy-note label="说明">控球 = 球位置上「最近的球员」在 {{ (tac.config && tac.config.possess_radius) || 2.5 }}m 内；',
    '            传球 = 控球人在队友之间切换；阵型 = 可解释的几何规则（不是训练模型）。</copy-note>',
    '          </div>',
    '        </div>',
    '      </div>',
    '    </el-card>',
    '    <!-- ③ 传球网络 -->',
    '    <el-card v-if="!populationNeedsRebuild && canInferAttack" shadow="never" class="blk">',
    '      <template #header><b>② 传球网络</b>',
    '      </template>',
    '      <el-radio-group v-model="netTeam" size="small" style="margin-bottom:10px">',
    '        <el-radio-button label="all">双方</el-radio-button>',
    '        <el-radio-button v-for="side in teams" :key="side" :label="side">{{ teamName(side) }}</el-radio-button>',
    '      </el-radio-group>',
    '      <el-button v-if="netFocus" size="small" @click="netFocus=\'\'" style="margin-left:12px">查看全部</el-button>',
    '      <div class="hint" style="margin-bottom:8px"><span style="color:#2f6fed">● {{ teamName(teams[0]) }}</span>　<span style="color:#f2762e">● {{ teamName(teams[1]) }}</span>　点击球员，查看相关传球</div>',
    '      <div class="tac-net">',
    '        <div class="court-wrap" @click="selectNetPlayer" @keydown="selectNetPlayer" v-html="netHTML"></div>',
    '        <el-table :data="netEdges" size="small" max-height="360" style="width:340px">',
    '          <el-table-column label="传球连线" >',
    '            <template #default="s">{{ s.row.from }} → {{ s.row.to }}</template>',
    '          </el-table-column>',
    '          <el-table-column prop="value" label="次数" width="70" align="center" />',
    '        </el-table>',
    '      </div>',
    '    </el-card>',
    '    <el-card v-else-if="!populationNeedsRebuild" shadow="never" class="blk">',
    '      <template #header><b>② 传球网络</b></template>',
    '      <div class="muted">没有足够的球轨迹与控球片段，暂时无法生成可信的传球网络。</div>',
    '    </el-card>',
    '    <!-- ④ 阵型识别 -->',
    '    <el-card v-if="!populationNeedsRebuild && canInferAttack" shadow="never" class="blk">',
    '      <template #header><b>③ 阵型识别</b>',
    '      </template>',
    '      <p>看两队球员怎么站位：进攻时是靠近篮筐还是向外拉开，防守时是跟着对手还是守住区域。</p>',
    '      <p class="hint">篮筐附近叫“内线”，三分线外叫“外线”。以下名称是根据检测到的站位估计，不代表已确认教练安排。</p>',
    '      <div style="margin:12px 0;line-height:1.8"><div v-for="item in formationGlossary" :key="item.label"><b>{{ item.label }}：</b>{{ item.text }}</div></div>',
    '      <p class="hint">标签后的数字是有效采样时刻数。例如“均衡落位 · 3”表示在 3 个采样时刻看到这种站位，不是 3 次进攻。</p>',
    '      <el-table :data="formationRows" size="small">',
    '        <el-table-column label="球队" width="110">',
    '          <template #default="s"><b>{{ s.row.name }}</b></template>',
    '        </el-table-column>',
    '        <el-table-column :label="hasBallTrack ? \'主要进攻落位\' : \'球员落位形状（攻守未判）\'">',
    '          <template #default="s">',
    '            <el-tag v-for="x in s.row.offenseTop" :key="x.label" size="small"',
    '                    :color="colorOf(x.label)" effect="dark" class="tag-gap">',
    '              {{ x.label }} · {{ x.n }}</el-tag>',
    '          </template>',
    '        </el-table-column>',
    '        <el-table-column :label="hasBallTrack ? \'主要防守阵型\' : \'防守阵型（无球轨迹）\'">',
    '          <template #default="s">',
    '            <el-tag v-for="x in s.row.defenseTop" :key="x.label" size="small"',
    '                    :color="colorOf(x.label)" effect="dark" class="tag-gap">',
    '              {{ x.label }} · {{ x.n }}</el-tag>',
    '          </template>',
    '        </el-table-column>',
    '      </el-table>',
    '      <p class="hint">下面的色条从左到右对应视频时间；每一段颜色表示当时识别出的阵型，长短表示持续时间。空白表示没有足够依据。</p>',
    '      <div v-for="b in offBars" :key="\'o\'+b.side" class="bar-row">',
    '        <span class="bar-label">{{ b.name }} · 进攻</span>',
    '        <span class="bar-track" v-html="b.html"></span>',
    '      </div>',
    '      <div v-for="b in defBars" :key="\'d\'+b.side" class="bar-row">',
    '        <span class="bar-label">{{ b.name }} · 防守</span>',
    '        <span class="bar-track" v-html="b.html"></span>',
    '      </div>',
    '    </el-card>',
    '    <el-card v-else-if="!populationNeedsRebuild" shadow="never" class="blk">',
    '      <template #header><b>③ 阵型识别</b></template>',
    '      <p>这个模块用来观察两队球员怎么站位：谁更靠近篮筐、谁在外线，以及防守如何分布。</p>',
    '      <div class="muted">当前球轨迹或控球片段不足，暂时无法区分进攻与防守阵型。</div>',
    '    </el-card>',
    '    <!-- ⑤ 间距曲线 -->',
    '    <el-card v-if="!populationNeedsRebuild" shadow="never" class="blk">',
    '      <template #header><b>④ 空间/间距曲线（{{ spacingObservedSubset ? "仅可见球员" : "仅有效采样" }}）</b>',
    '      </template>',
    '      <p>看同队球员站得有多开、整体离篮筐多远。横轴是视频时间，纵轴是所选指标；蓝色为{{ teamName(teams[0]) }}，橙色为{{ teamName(teams[1]) }}。</p>',
    '      <el-radio-group v-model="metric" size="small" style="margin-bottom:8px">',
    '        <el-radio-button v-for="m in METRICS" :key="m.key" :label="m.key">',
    '          {{ m.label }}</el-radio-button>',
    '      </el-radio-group>',
    '      <div style="line-height:1.8;margin:8px 0 16px"><b>{{ metricHelp.label }}（{{ metricHelp.unit }}）：</b>{{ metricHelp.meaning }}<br>{{ metricHelp.reading }}</div>',
    '      <p class="hint">曲线断开表示该时段缺少可靠位置；数值大或小不直接代表打得好坏。下表只对有效采样取平均，不代表整场比赛。</p>',
    '      <p v-if="spacingObservedSubset" class="hint">仅计算已分组的可见球员，不代表完整五人阵容。人数变化和切镜处断线；悬停可查看当时人数。</p>',
    '      <echarts-box :option="spacingOption" height="300px" />',
    '      <el-table :data="spacingTeams" size="small" style="margin-top:10px">',
    '        <el-table-column label="球队" width="110">',
    '          <template #default="s"><b>{{ s.row.name }}</b></template>',
    '        </el-table-column>',
    '        <el-table-column v-if="spacingObservedSubset" label="每次可见人数" width="120">',
    '          <template #default="s">{{ s.row.d.n_min == null ? "—" : s.row.d.n_min + "～" + s.row.d.n_max + " 人" }}</template>',
    '        </el-table-column>',
    '        <el-table-column label="站位面积(m²)" align="center">',
    '          <template #default="s">{{ s.row.d.area }}</template></el-table-column>',
    '        <el-table-column label="平均间距(m)" align="center">',
    '          <template #default="s">{{ s.row.d.mean_dist }}</template></el-table-column>',
    '        <el-table-column label="左右展开(m)" align="center">',
    '          <template #default="s">{{ s.row.d.width }}</template></el-table-column>',
    '        <el-table-column label="前后展开(m)" align="center">',
    '          <template #default="s">{{ s.row.d.depth }}</template></el-table-column>',
    '        <el-table-column label="整体离篮筐(m)" align="center">',
    '          <template #default="s">{{ s.row.d.radius }}</template></el-table-column>',
    '      </el-table>',
    '    </el-card>',
    '  </template>',
    '  <el-alert v-if="err" type="error" :closable="false" :title="err" />',
    '</div>'
  ].join('\n'),
  // 球场层直接用 court.js（与叠加层同一 viewBox，保证像素级对齐）
};
