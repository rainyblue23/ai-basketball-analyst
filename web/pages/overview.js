/* ==========================================================================
   pages/overview.js —— 页面 2：比赛总览
   --------------------------------------------------------------------------
   数据来源接口：
     GET /api/games/{job_id}            game.json（score / teams.stats /
                                        quarter_scores / progression / timeline）
     GET /api/games/{job_id}/video      原始视频（支持 Range，可拖动跳转）
   展示内容：
     * 大比分牌 + 分节比分表（big-scoreboard 组件）
     * 双方命中率 / 三分率 / 罚球 / 篮板助攻等 KPI 对比卡片
     * 比分走势折线图（ECharts，按 game.progression 画）
     * 事件时间轴（可滚动；点击某条 → 若有视频跳 currentTime，否则只高亮）
   ========================================================================== */
window.PAGES = window.PAGES || {};

window.PAGES['overview'] = {
  name: 'page-overview',
  data: function () {
    return {
      S: window.STORE,
      api: window.API,
      pendingSeek: null,
      activeRow: -1,
      videoReady: false,
      videoErr: '',
      filterTeam: 'all',
      filterMade: 'all'      // all | made | miss
    };
  },
  watch: {
    videoUrl: function () {
      this.videoReady = false; this.videoErr = ''; this.pendingSeek = null;
      this.activeRow = -1;
    }
  },
  computed: {
    shotCounts: function () {
      var counts = { total: 0, made: 0, miss: 0, pending: 0 };
      ((this.game && this.game.timeline) || []).forEach(function (row) {
        var display = window.D.shotDisplay(row);
        counts.total++;
        if (display.resolved) counts[display.made ? 'made' : 'miss']++;
        else counts.pending++;
      });
      return counts;
    },
    unresolvedShots: function () {
      return ((this.game && this.game.timeline) || []).filter(function (row) {
        return !window.D.shotDisplay(row).resolved;
      });
    },
    game: function () { return this.S.game; },
    sampleReview: function () { return ((this.game || {}).meta || {}).sample_review || null; },
    rimTracking: function () {
      return (((this.game || {}).meta || {}).shot_engine_details || {}).rim_tracking || null;
    },
    rimAvailability: function () {
      return this.rimTracking && this.rimTracking.availability || null;
    },
    ballVisibility: function () {
      return this.rimTracking && this.rimTracking.ball_visibility || null;
    },
    /**
     * 待核对的轨迹候选：由投篮引擎的**独立候选层**给出，只提示与回看，
     * 不进 timeline、不计入出手次数与命中统计（判定仍只由 events 决定）。
     */
    shotCandidates: function () {
      var sc = (((this.game || {}).meta || {}).shot_engine_details || {}).shot_candidates;
      return sc && sc.candidates ? sc : null;
    },
    // 未对应任何事件的候选排在前面 —— 那才是真正需要回看的
    reviewCandidates: function () {
      var sc = this.shotCandidates;
      if (!sc) return [];
      return sc.candidates.slice().sort(function (a, b) {
        return (a.matched === b.matched) ? a.release_t - b.release_t : (a.matched ? 1 : -1);
      });
    },
    /**
     * 证据跨段的候选：切镜（或跟踪段边界）把"上升段"和"顶点"分在了两段里，
     * 主列表为保证不跨段拼接而排除了它们 —— 但"被排除"不等于"不存在"，
     * 所以单独列出来核对，单独计数，同样不进任何统计。
     */
    crossSegmentCandidates: function () {
      var sc = this.shotCandidates;
      if (!sc || !sc.cross_segment) return [];
      return sc.cross_segment.slice().sort(function (a, b) {
        return (a.matched === b.matched) ? a.release_t - b.release_t : (a.matched ? 1 : -1);
      });
    },
    duration: function () { return (this.game && this.game.duration) || 0; },
    /**
     * 证据来源：直接读 game.meta，把「这次判定用了哪几路证据、质量如何」
     * 摆到台面上。比分是哪来的、球追到了多少、分队怎么分的，一眼能看见 ——
     * 这是「可解释」最直接的体现，也是答辩时最好讲的一页。
     */
    evidence: function () {
      var m = (this.game && this.game.meta) || {};
      var out = [];
      var sb = m.scoreboard;
      if (sb && sb.frames_hit > 0) {
        var pct = Math.round(sb.frames_hit / sb.frames_read * 100);
        out.push({ k: '广播比分牌', v: '读取成功 ' + sb.frames_hit + '/' + sb.frames_read +
          ' 帧（' + pct + '%）', d: '仅采信通过检查的读数；比分变化不能确定投篮球员和出手位置。' });
      }
      if (m.hoopsight_error) {
        out.push({k: '篮下识别未完成', v: '本次结果可能漏球',
          d: m.hoopsight_error + '；请检查篮筐标注与尺寸，不能将本次统计视为完整比赛结果。'});
      }
      if (m.shot_engine === 'legacy') {
        out.push({ k: '投篮检测', v: '逐次出手引擎',
          d: '投篮记录显示时间、中或没中。' });
      }
      var vis = m.visual;
      if (vis) {
        out.push({ k: '视觉路径（球+篮筐）', v: '出手候选 ' + vis.shots + ' 条 / 判进 ' +
          vis.made + ' 次',
          d: (vis.method || '') + '。判定口径：球在图像里从篮筐平面上方落到下方且穿越点在篮圈内，不需要知道球离地多高' });
        if (vis.hoop_drift_px && Math.max(vis.hoop_drift_px[0], vis.hoop_drift_px[1]) > 6) {
          out.push({ k: '机位在移动', v: '篮筐漂移 ' + vis.hoop_drift_px[0] + '×' +
            vis.hoop_drift_px[1] + ' 像素',
            d: '因此用的是每一帧各自的篮筐位置，而不是一个全局中位数' });
        }
      }
      var hoop = m.hoop && m.hoop.median;
      if (hoop) {
        out.push({ k: '篮筐识别', v: '中心 (' + Math.round(hoop.cx) + ',' +
          Math.round(hoop.cy) + ')  半径 ' + Math.round(hoop.rx) + 'px',
          d: '检测到 ' + (m.hoop.votes || 0) + '/' + (m.hoop.frames || 0) + ' 帧，依据：' + (hoop.method || '') });
      }
      if (m.calibration_valid === false) {
        out.push({ k: '球场标定', v: '不适用本视频',
          d: '标定是按机位存的；本视频尺寸/场地不同，所以出手位置不换算成球场坐标，每次得分按默认分值计' });
      }
      if (m.scoreboard_final) {
        out.push({ k: this.courtMode ? '比分牌读数（仅供参考）' : '比分牌读数',
          v: m.scoreboard_final.home + ' : ' + m.scoreboard_final.away,
          d: this.courtMode ? '比分牌上的比赛当前大比分；不计入本片段得分'
            : '画面里比分牌上的比赛当前大比分' });
      }
      var clip = this.game && this.game.clip_score;
      if (!clip && this.game && this.game.carry_in) {
        // 旧产物兜底：总分 - 带入分 = 本片段得分
        clip = {
          home: (this.game.score.home || 0) - (this.game.carry_in.home || 0),
          away: (this.game.score.away || 0) - (this.game.carry_in.away || 0)
        };
      }
      if (clip) {
        out.push({ k: '本片段得分', v: clip.home + ' : ' + clip.away,
          d: '这段视频真正产生的得分；不含比分牌带入分' });
      }
      var ci = this.game && this.game.carry_in;
      if (ci && (ci.home || ci.away)) {
        out.push({ k: this.courtMode ? '比分牌读数（参考）' : '比分牌带入（当前大比分）',
          v: ci.home + ' : ' + ci.away,
          d: this.courtMode ? '比赛进行到该时刻的已有比分；仅供参照，不计入本片段得分'
            : '本片段从比赛中途开始，比分牌上已有的分数；计入当前大比分，但没有对应的出手事件' });
      }
      if (m.ball) {
        out.push({ k: '球轨迹', v: '候选 ' + (m.ball.candidates || 0) + ' 个 / 轨迹 ' +
          (m.ball.tracks || 0) + ' 条 / 保留 ' + (m.ball.kept_points || 0) + ' 点',
          d: '单目估计位置，只用于定位出手点，不参与计分' });
      }
      if (m.attempts) {
        out.push({ k: '出手来源', v: '比分牌 ' + (m.attempts.from_scoreboard || 0) +
          ' 次 / 打铁候选 ' + (m.attempts.from_ball_track || 0) + ' 次',
          d: this.sampleReview ? '轨迹候选不自动计入样例统计'
            : '打铁候选置信度低，进入待确认队列，不进比分统计' });
      }
      if (m.teams) {
        out.push({ k: '分队依据', v: '球衣颜色聚类 ' + (m.teams.players || 0) + ' 名球员',
          d: '绿色系 ' + m.teams.green_hue + '° / 红色系 ' + m.teams.red_hue + '°' });
      }
      return out;
    },
    courtMode: function () {
      var p = String((this.game && this.game.score_policy) || 'scoreboard').toLowerCase();
      return ['court', 'visual', 'auto'].indexOf(p) >= 0;
    },
    /** 有没有"分值是我们暂计的"事件（value_assumed）—— 决定要不要提示「分值尚未确认」 */
    assumedValue: function () {
      var tl = (this.game && this.game.timeline) || [];
      return tl.some(function (e) {
        return e.value_assumed || ((e.tags || []).indexOf('value_assumed') >= 0);
      });
    },
    analysisModules: function () {
      var review = this.sampleReview;
      var players = this.S.players || [];
      var points = (((this.S.shotchart || {}).all || {}).points || []);
      var tactics = (this.game && this.game.tactics) || {};
      var report = this.S.report;
      return [
        { title: '球员 / 球队统计', href: '#/stats', available: players.length > 0,
          summary: players.length ? ('已生成 ' + players.length + ' 条球员统计') : '没有可用的球员统计',
          note: review && !review.players_verified ? '本样例尚未确认球员身份，统计按未分配球员汇总。' : '' },
        { title: '投篮热图', href: '#/shotchart', available: points.length > 0,
          summary: points.length ? ('已定位 ' + points.length + ' 次出手') : '没有可靠的出手位置，不绘制热图',
          note: points.length ? '只绘制有可靠球场坐标的出手。' : '位置未知时不会生成假热区。' },
        { title: '战术分析', href: '#/tactics', available: !!tactics.available,
          summary: tactics.available ? '已生成阵型、空间与回合分析' : '没有可用的战术分析',
          note: tactics.position_unverified ? '球员位置尚未独立校验，战术结论仅供回看参考。' : '' },
        { title: '战报与导出', href: '#/report', available: !!report,
          summary: report ? '已生成本场战报和导出文件' : '尚未生成战报', note: '' }
      ];
    },
    /** 这次分析是不是"什么都没判出来"（没有任何得分事件/出手/时间轴） */
    emptyAnalysis: function () {
      var g = this.game || {};
      var sc = g.score || {};
      var tl = g.timeline || [];
      var att = (g.meta && g.meta.attempts) || {};
      var n = (att.from_scoreboard || 0) + (att.from_ball_track || 0);
      return tl.length === 0 && n === 0 && !sc.home && !sc.away;
    },
    /** 空结果时把真正的原因说清楚（别只给一个 0:0 让人以为页面坏了） */
    emptyWhy: function () {
      var m = (this.game && this.game.meta) || {};
      var lines = ['得分事件：0    出手记录：0'];
      var ve = m.visual_error || (m.hoopsight && m.hoopsight.reason);
      if (ve) { lines.push('为什么没判出来：' + String(ve).slice(0, 180)); }
      if (m.scoreboard_error) {
        lines.push('比分牌路径：' + String(m.scoreboard_error).slice(0, 140));
      }
      if (m.court_outputs_unverified) {
        lines.push('另外：热区/战术图用的是你手动标的标定，'
          + '自动校验没通过，位置可能有偏差。');
      }
      lines.push('');
      lines.push('想让它有内容，三条路：');
      lines.push('  ① 记分牌路径：视频里有可读记分牌时，得分事件直接进结果'
        + '（这段视频底部就有记分牌）；');
      lines.push('  ② 换更清楚的素材：球在画面里 ≥30 像素时进球检测才能工作'
        + '（README「素材体检」）；');
      lines.push(this.sampleReview
        ? '  ③ 样例逐球时间：在总览时间轴逐条回看。'
        : '  ③ 人工复核：在「人工复核」页逐条确认/补录，判完再看总览与热区。');
      return lines.join('\n');
    },
    hasCarryIn: function () {
      var ci = this.game && this.game.carry_in;
      return !!(ci && (ci.home || ci.away));
    },
    videoUrl: function () {
      if (!this.S.jobId || this.S.demoMode) return '';
      return window.API.jobVideoUrl(this.S.jobId);
    },
    /** 时间轴：来自 game.timeline，可按球队/命中与否过滤 */
    timeline: function () {
      var rows = (this.game && this.game.timeline) || [];
      var self = this;
      return rows.filter(function (e) {
        if (self.filterTeam !== 'all' && e.team !== self.filterTeam) return false;
        // 筛选与徽章使用同一显示建议，不覆写用于统计的原始结果。
        var display = window.D.shotDisplay(e);
        if (!display.resolved) return false;
        if (self.filterMade === 'made' && !display.made) return false;
        if (self.filterMade === 'miss' && display.made) return false;
        return true;
      });
    },
    /** KPI 对比数据（全部取自 game.teams[side].stats，与后端统计口径一致） */
    kpis: function () {
      if (!this.game) return [];
      var h = this.game.teams.home.stats, a = this.game.teams.away.stats;
      var D = window.D;
      function ts(s) {
        var den = 2 * (s.fga + 0.44 * s.fta);
        return den ? s.points / den : 0;
      }
      return [
        { k: '得分', hv: h.points + '', av: a.points + '' },
        { k: '投篮命中率', hv: D.pctSmart(h.fg_pct), av: D.pctSmart(a.fg_pct) },
        { k: '运动战进球', hv: h.fgm + '/' + h.fga, av: a.fgm + '/' + a.fga },
        { k: '三分命中率', hv: D.pctSmart(h.tp_pct), av: D.pctSmart(a.tp_pct) },
        { k: '三分球', hv: h.tpm + '/' + h.tpa, av: a.tpm + '/' + a.tpa },
        { k: '罚球', hv: h.ftm + '/' + h.fta, av: a.ftm + '/' + a.fta },
        { k: '真实命中率 TS%', hv: D.pctSmart(ts(h)), av: D.pctSmart(ts(a)) },
        { k: '回合数（估计）', hv: (this.game.possessions || 0) + '', av: (this.game.possessions || 0) + '' }
      ];
    },
    /** 比分走势折线图 option：x 轴是比赛时间（秒），两条线是双方累计得分 */
    progressOption: function () {
      var g = this.game;
      var D = window.D;
      if (!g || !g.progression) return {};
      var data = g.progression;
      var hn = D.teamName(g, 'home'), an = D.teamName(g, 'away');
      // 用 markLine 标出每节结束时刻（按四等分估算，后端未给节次时间戳时也够用）
      var q = [], per = (g.duration || 0) / (g.periods || 4);
      for (var i = 1; i < (g.periods || 4); i++) {
        q.push({ xAxis: Math.round(per * i * 10) / 10, label: { formatter: '第' + (i + 1) + '节' } });
      }
      return {
        tooltip: {
          trigger: 'axis',
          formatter: function (ps) {
            var p = ps[0].data;
            var extra = (p && p[2]) ? '<br/>' + p[2] : '';
            return D.mmss(ps[0].axisValue) + '<br/>' +
              ps.map(function (x) { return x.marker + x.seriesName + '：' + x.data[1]; }).join('<br/>') + extra;
          }
        },
        legend: { top: 0 },
        grid: { left: 44, right: 22, top: 34, bottom: 46, containLabel: true },
        xAxis: {
          type: 'value', name: '比赛时间', min: 0, max: Math.max(60, Math.round(g.duration || 0)),
          axisLabel: { formatter: function (v) { return D.mmss(v); } }
        },
        yAxis: { type: 'value', name: '累计得分', minInterval: 1 },
        dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 10 }],
        series: [
          {
            name: hn, type: 'line', step: 'end', showSymbol: false, smooth: false,
            lineStyle: { width: 2.4, color: '#3D8BFF' }, itemStyle: { color: '#3D8BFF' },
            areaStyle: { color: 'rgba(47,111,237,0.08)' },
            markLine: { silent: true, symbol: 'none', lineStyle: { type: 'dashed', color: '#c9ced6' }, data: q },
            data: data.map(function (p) {
              return [p.t, p.home, p.made && p.scorer ? '得分：' + p.scorer + ' +' + p.value : ''];
            })
          },
          {
            name: an, type: 'line', step: 'end', showSymbol: false,
            lineStyle: { width: 2.4, color: '#FF7A33' }, itemStyle: { color: '#FF7A33' },
            data: data.map(function (p) { return [p.t, p.away]; })
          }
        ]
      };
    },
    scoreDiffOption: function () {
      var g = this.game;
      if (!g || !g.progression) return {};
      return {
        tooltip: { trigger: 'axis' },
        grid: { left: 44, right: 22, top: 16, bottom: 30, containLabel: true },
        xAxis: { type: 'value', name: '时间', axisLabel: { formatter: function (v) { return window.D.mmss(v); } } },
        yAxis: { type: 'value', name: '分差' },
        series: [{
          type: 'line', name: '分差（主-客）', showSymbol: false, smooth: true,
          lineStyle: { color: '#8b5cf6', width: 2 },
          areaStyle: {
            color: 'rgba(139,92,246,0.12)',
            origin: 'start'
          },
          data: g.progression.map(function (p) { return [p.t, p.home - p.away]; })
        }]
      };
    }
  },
  methods: {
    locationToReview: function () { window.location.hash = '#/review'; },
    teamName: function (s) { return window.D.teamName(this.game, s); },
    mmss: function (t) { return window.D.mmss(t); },
    /**
     * 候选层的中文标签：这两个**必须是 methods**（模板里当函数调用）。
     * 之前误放进 computed，模板渲染时 `candidateKindLabel(c.kind)` 会报错 —— 候选卡片整块渲染失败。
     */
    candidateClassLabel: function (k) {
      return ({ far: '远投类', near: '近筐类（补篮/二次进攻/反弹）', unknown: '筐位未知' })[k] || k;
    },
    candidateKindLabel: function (k) {
      return ({ arc: '完整弧线', rise_only: '上升后未下落', vanish: '上升后球消失' })[k] || k;
    },
    /**
     * 证据提示（后端 evidence_flags）：说的是"看这条候选时要注意什么"，
     * **不是**"这条是不是投篮"。实测真实投篮的窗口里也会出现竖长球框（人/头误检），
     * 所以文案里不能写成结论，只能写成证据状态。
     */
    evidenceFlagLabel: function (f) {
      return ({
        ball_box_shape: '球框形态可疑（竖长框，可能框到人）',
        ball_box_size: '球框尺寸异常（远大于本片正常球框）',
        ball_with_person: '球全程贴着人体框（像持球/走动）',
        few_ball_observations: '球观测过少（轨迹本就不稳）',
        cut_truncated: '证据被切镜截断（结果要去下一个镜头找）',
      })[f] || f;
    },
    /** Only resolved rows are assigned a result color. */
    resultClass: function (e) {
      var display = window.D.shotDisplay(e);
      return display.resolved ? (display.made ? 'made' : 'miss') : '';
    },
    resultLabel: function (e) { return window.D.shotDisplay(e).label; },
    resultReason: function (e) { return window.D.shotDisplay(e).reason; },
    shotValueLabel: function (e) { return window.D.shotValueLabel(e); },
    rimPosition: function (r) {
      return r ? '(' + Math.round(r.cx) + ', ' + Math.round(r.cy) + ')' : '未确认';
    },
    rimTransitionLabel: function (reason) {
      return ({initialized:'开始跟踪',reacquired_near:'失效后重新确认',
        reacquired_far:'失效后在远处重新确认',cut:'切镜，结束旧跟踪'})[reason] || '跟踪状态变化';
    },
    gotoRimTransition: function (row) {
      if (!this.videoUrl || !Number.isFinite(Number(row.t))) return;
      this.activeRow=-1; this.pendingSeek=Math.max(0,Number(row.t)-1); this.seekVideo();
      var v=this.$refs.video;
      if (v && v.scrollIntoView) v.scrollIntoView({block:'nearest'});
    },
    /** 保留原始事件身份，筛选后仍高亮同一条；元数据未就绪时延后跳转。 */
    gotoEvent: function (row, idx, crossing) {
      this.activeRow = ((this.game && this.game.timeline) || []).indexOf(row);
      var target = crossing ? [row.review_t, row.crossing_t, row.decision_t, row.t].find(function (v) { return typeof v === "number" && Number.isFinite(v) && v >= 0; }) : row.t;
      var t = Number(target);
      if (!Number.isFinite(t) || !this.videoUrl) return;
      this.pendingSeek = Math.max(0, t - (crossing ? 1 : 0.6));
      this.seekVideo();
      var v = this.$refs.video;
      if (v && v.scrollIntoView) v.scrollIntoView({ block: 'nearest' });
    },
    seekVideo: function () {
      var v = this.$refs.video;
      if (!v || !this.videoReady || this.pendingSeek === null) return;
      try {
        v.currentTime = Number.isFinite(v.duration) ? Math.min(this.pendingSeek, Math.max(0, v.duration - 0.05)) : this.pendingSeek;
        this.pendingSeek = null;
        var playing = v.play();
        if (playing && playing.catch) playing.catch(function () {});
      } catch (e) { this.videoErr = '暂时无法跳转，请使用视频进度条重试。'; }
    },
    onVideoMeta: function () { this.videoReady = true; this.videoErr = ''; this.seekVideo(); },
    onVideoError: function () { this.videoReady = false; this.videoErr = '原视频暂时无法播放，请检查文件是否仍在原位置，或重新上传兼容的视频。'; },
    rowClass: function (row) {
      return row.team === 'home' ? 'h' : row.team === 'away' ? 'a' : '';
    },
    goUpload: function () { location.hash = '#/upload'; }
  },
  template: [
    '<div>',
    '  <section class="card" v-if="sampleReview">',
    '    <h3 class="card-title">本场产出</h3>',
    '    <div class="row"><a href="#/stats">球员 / 球队统计</a><a href="#/shotchart">投篮热图</a><a href="#/tactics">战术分析</a><a href="#/highlights">{{ sampleReview.attempts }} 次出手回放</a><a href="#/report">战报与导出</a></div>',
    '    <p class="hint">完整分析入口均可查看；球员、球队或出手位置尚未确认的模块会直接说明缺少的数据，不生成假统计或假热区。</p>',
    '  </section>',

    '  <div class="card" v-if="!game">',
    '    <el-empty description="暂无比赛数据"><el-button type="primary" @click="goUpload">去新建任务</el-button></el-empty>',
    '  </div>',
    '  <template v-else>',
    '    <div class="card">',
    '      <h3 class="card-title">原始视频 <el-tag v-if="sampleReview" size="small" effect="plain">样例分析</el-tag></h3>',
    '      <div class="replay-stage" v-if="videoUrl">',
    '      <video v-if="videoUrl" :key="videoUrl" ref="video" :src="videoUrl" controls playsinline preload="metadata" style="display:block;width:100%;max-height:520px;background:var(--bg);border-radius:var(--r-sm)" @loadedmetadata="onVideoMeta" @error="onVideoError"></video>',
    '        <detection-overlay ref="boxOverlay" :job-id="S.jobId" />',
    '      </div>',
    '      <ball-feedback v-if="videoUrl" :job-id="S.jobId" />',
    '      <replay-tools v-if="videoUrl" :job-id="S.jobId" :events="game.timeline" :fps="game.fps || (game.meta && game.meta.fps)" @event="gotoEvent" />',
    '      <p v-if="videoUrl && !videoReady && !videoErr" class="hint">正在加载原视频…</p>',
    '      <el-alert v-if="videoErr" type="warning" :closable="false" :title="videoErr" />',
    '      <el-empty v-if="!videoUrl" description="演示数据没有关联原视频" :image-size="70" />',
    '    </div>',
    '    <div class="card">',
    '      <h3 v-if="sampleReview" class="card-title">全片统计：运动战 {{ sampleReview.field_attempts }} 投 {{ sampleReview.field_made }} 中 · 罚球 {{ sampleReview.free_throw_attempts }} 投 {{ sampleReview.free_throw_made }} 中</h3>',
    '      <h3 v-else class="card-title">投篮结果 {{ shotCounts.made + shotCounts.miss }} 条</h3>',
    '      <p v-if="sampleReview">按逐球记录整理；下方时间可逐条回看。</p>',
    '      <p v-if="sampleReview && sampleReview.replay_count">含 {{ sampleReview.replay_count }} 条重复回放；去重后运动战 {{ sampleReview.unique_field_attempts }} 投 {{ sampleReview.unique_field_made }} 中。</p>',
    '      <div class="row" style="flex-wrap:wrap;gap:20px;margin-bottom:12px" aria-label="全部投篮候选统计">',
    '        <span>中 <strong>{{ shotCounts.made }}</strong></span>',
    '        <span>没中 <strong>{{ shotCounts.miss }}</strong></span>',
    '      </div>',
    '        <h3 class="card-title" style="flex-wrap:wrap">投篮记录 ',
    '          <span class="grow"></span>',
    '          <el-radio-group v-model="filterMade" size="small">',
    '            <el-radio-button label="all">全部</el-radio-button>',
    '            <el-radio-button label="made">只看中</el-radio-button>',
    '            <el-radio-button label="miss">只看没中</el-radio-button>',
    '          </el-radio-group>',
    '          <el-select v-if="!sampleReview || sampleReview.teams_verified" v-model="filterTeam" size="small" style="width:130px">',
    '            <el-option label="双方" value="all" />',
    '            <el-option :label="teamName(\'home\')" value="home" />',
    '            <el-option :label="teamName(\'away\')" value="away" />',
    '          </el-select>',
    '        </h3>',
    '        <div class="timeline">',
    '          <div v-for="(e,i) in timeline" :key="(game.timeline||[]).indexOf(e)" class="tl-row" style="display:flex;flex-wrap:wrap" :class="{active: activeRow===(game.timeline||[]).indexOf(e)}">',
    '            <button class="el-button el-button--small" @click="gotoEvent(e,i)">{{ mmss(e.t) }}</button>',
    '            <span class="tl-badge" :class="resultClass(e)" :title="resultReason(e)">{{ resultLabel(e) }}</span>',
    '            <strong v-if="shotValueLabel(e)">{{ shotValueLabel(e) }}</strong>',
    '          </div>',
    '          <el-empty v-if="!timeline.length" description="无符合条件的事件" :image-size="70" />',
    '        </div>',
    '    </div>',
    '    <h2>完整分析结果</h2>',
    '    <div class="grid grid-4">',
    '      <a v-for="m in analysisModules" :key="m.title" :href="m.href" class="card" style="display:block;text-decoration:none;color:inherit">',
    '        <h3 class="card-title">{{ m.title }} <el-tag size="small" :type="m.available ? \'success\' : \'info\'">{{ m.available ? \'可查看\' : \'暂无数据\' }}</el-tag></h3>',
    '        <p>{{ m.summary }}</p><p v-if="m.note" class="hint">{{ m.note }}</p>',
    '      </a>',
    '    </div>',
    '    <section class="card" v-if="rimAvailability || ballVisibility" aria-label="分析覆盖摘要"><h3 class="card-title">分析覆盖</h3><p><span v-if="rimAvailability">篮筐可用 {{ Math.round(rimAvailability.usable_fraction*100) }}%</span><span v-if="ballVisibility"> · 球检测观测 {{ Math.round(ballVisibility.observed_fraction*100) }}%</span></p><p class="hint">这是检测覆盖，不是准确率；没有记录不代表没有投篮。</p><el-button size="small" @click="locationToReview">补录漏掉的出手</el-button></section>',
    '    <section class="card" v-if="(rimAvailability && rimAvailability.unavailable_ranges.length) || (ballVisibility && ballVisibility.blind_ranges.length)" aria-label="检测覆盖范围">',
    '      <h3 class="card-title">部分时段无法持续判定投篮</h3>',
    '      <p v-if="rimAvailability && rimAvailability.unavailable_ranges.length"><copy-note label="说明">以下时段连续至少 2 秒没有可用的篮筐跟踪，可能漏掉投篮；没有记录不代表没有出手。可回看原视频核对。</copy-note></p>',
    '      <p v-if="rimAvailability" class="hint">可用篮筐覆盖 {{ rimAvailability.usable_frames }} / {{ rimAvailability.sampled_frames }} 帧（{{ Math.round(rimAvailability.usable_fraction * 100) }}%）<copy-note label="说明">这是跟踪可用性，不是识别准确率；有筐也不保证球可见。</copy-note></p>',
    '      <ul><li v-for="(gap,i) in (rimAvailability ? rimAvailability.unavailable_ranges : [])" :key="i">',
    '        <button class="el-button el-button--small" :disabled="!videoUrl" @click="gotoRimTransition({t:gap.start})">回看 {{ mmss(gap.start) }}–{{ mmss(gap.end) }}</button>',
    '      </li></ul>',
    '      <p v-if="ballVisibility" class="hint">球检测观测率 {{ Math.round(ballVisibility.observed_fraction * 100) }}% · <copy-note label="说明">球检测观测率：{{ ballVisibility.observed_frames }} / {{ ballVisibility.sampled_frames }} 个采样帧（{{ Math.round(ballVisibility.observed_fraction * 100) }}%）有真实球观测，最长连续缺失 {{ ballVisibility.longest_blind_s.toFixed(1) }} 秒。这只是<b>检测观测率</b>（不是录像里有没有球的判定）：没检测到可能是检测器漏检，也可能是球太小/被挡住；这些时段不能断言"没有投篮"。</copy-note></p>',
    '      <ul v-if="ballVisibility && ballVisibility.blind_ranges.length"><li v-for="(gap,i) in ballVisibility.blind_ranges" :key="\'b\'+i">',
    '        <button class="el-button el-button--small" :disabled="!videoUrl" @click="gotoRimTransition({t:gap.start})">回看（该段无球观测）{{ mmss(gap.start) }}–{{ mmss(gap.end) }}</button>',
    '      </li></ul>',
    '    </section>',
    '    <section class="card" v-if="shotCandidates && (shotCandidates.candidates.length || shotCandidates.cross_segment_count)" aria-label="待核对的轨迹候选">',
    '      <h3 class="card-title">待核对的轨迹候选 <span class="sub"><copy-note label="说明">这份清单来自<b>独立的轨迹候选层</b>：球的上升→下落弧线接近过篮筐。其中<b>离手时刻与某条已有事件接近</b>的，只说明时间上靠近（<b>不证明是同一次出手</b>，需人工确认）；<b>未对应任何事件</b>的才是更需要回看的候选。请回看原视频确认；确认后请用「复核页」补录或改判，本清单不会自动改变任何统计。<br>另外「证据提示」只说明<b>这条候选的证据状况</b>（球框框到人了、球一直贴着人、观测太少），用来决定<b>值不值得看、看的时候注意什么</b>；它<b>不是</b>投篮与否的判定 —— 实测真实投篮的窗口里也会出现这些提示。</copy-note></span></h3>',
    '      <p class="hint">共 {{ shotCandidates.count }} 条 · 未对应 {{ shotCandidates.unmatched_count }} 条</p>',
    '      <ul style="max-height:300px;overflow:auto">',
    '        <li v-for="(c,i) in reviewCandidates" :key="i" style="margin:8px 0">',
    '          <button class="el-button el-button--small" :disabled="!videoUrl" @click="gotoRimTransition({t: Math.max(0, c.release_t - (shotCandidates.review_offset_s || 1))})">回看 {{ mmss(c.release_t) }}</button>',
    '          <el-tag size="small" :type="c.matched ? \'info\' : \'warning\'" effect="plain">{{ c.matched ? "与已有出手对应" : "未对应任何事件" }}</el-tag>',
    '          出手≈{{ mmss(c.release_t) }}（顶点 {{ mmss(c.apex_t) }}）· {{ candidateKindLabel(c.kind) }} · {{ candidateClassLabel(c.klass) }} · 上升 {{ c.rise_px }}px / 下落 {{ c.fall_px }}px',
    '          <span v-if="c.evidence_flags && c.evidence_flags.length" class="hint"> · 证据提示：{{ c.evidence_flags.map(evidenceFlagLabel).join("、") }}</span>',
    '          <span v-if="c.start_dist_rims != null" class="hint"> · 起点距筐 {{ c.start_dist_rims }} 个筐宽</span>',
    '          <span v-if="c.matched" class="hint"> · 对应事件 {{ mmss(c.matched_event_t) }}（{{ c.matched_event_type }}，离手差 {{ c.matched_delta_s }}s）</span>',
    '        </li>',
    '      </ul>',
    '      <div v-if="crossSegmentCandidates.length" style="margin-top:12px;border-top:1px solid #ebeef5;padding-top:8px">',
    '        <p class="hint"><copy-note label="说明"><b>另 {{ shotCandidates.cross_segment_count }} 条「证据跨段」</b>：切镜或跟踪段边界把"上升段"和"顶点"分在了两个镜头/两段里。主列表为保证不跨段拼接已排除它们，但<b>排除不等于不存在</b> —— 这几条同样必须目视核对。它们单独计数，<b>不计入上面的 {{ shotCandidates.count }} 条</b>，也不计入出手次数与命中统计。</copy-note></p>',
    '        <ul style="max-height:200px;overflow:auto">',
    '          <li v-for="(c,i) in crossSegmentCandidates" :key="\'x\'+i" style="margin:8px 0">',
    '            <button class="el-button el-button--small" :disabled="!videoUrl" @click="gotoRimTransition({t: Math.max(0, c.release_t - (shotCandidates.review_offset_s || 1))})">回看 {{ mmss(c.release_t) }}</button>',
    '            <el-tag size="small" :type="c.matched ? \'info\' : \'warning\'" effect="plain">{{ c.matched ? "与已有事件时间接近" : "未对应任何事件" }}</el-tag>',
    '            出手≈{{ mmss(c.release_t) }}（顶点 {{ mmss(c.apex_t) }} · 证据横跨 {{ c.blocks_in_window }} 段）· {{ candidateKindLabel(c.kind) }} · 上升 {{ c.rise_px }}px / 下落 {{ c.fall_px }}px',
    '            <span v-if="c.evidence_flags && c.evidence_flags.length" class="hint"> · 证据提示：{{ c.evidence_flags.map(evidenceFlagLabel).join("、") }}</span>',
    '            <span v-if="c.matched" class="hint"> · 相近事件 {{ mmss(c.matched_event_t) }}（{{ c.matched_event_type }}，离手差 {{ c.matched_delta_s }}s）</span>',
    '          </li>',
    '        </ul>',
    '      </div>',
    '      <p class="hint"><copy-note label="说明">{{ shotCandidates.note }} 阈值见任务参数（detect.cand_*），调整需重新分析。</copy-note></p>',
    '    </section>',
    '    <details class="card" v-if="rimTracking">',
    '      <summary>篮筐跟踪与标注反馈</summary>',
    '      <p>中心约束：{{ rimTracking.lock_enabled ? "已启用（实验）" : "未启用" }}；拒绝 {{ rimTracking.rejected_candidates }} 个候选，涉及 {{ rimTracking.rejected_frames }} / {{ rimTracking.frames }} 帧。</p>',
    '      <p v-if="rimTracking.lock_requested && !rimTracking.center_hint">没有中心提示点，中心约束未生效。</p>',
    '      <p v-if="rimTracking.center_hint">提示点：({{ rimTracking.center_hint.join(", ") }})</p>',
    '      <p v-if="rimTracking.first_confirmed">首次确认的筐：{{ rimPosition(rimTracking.first_confirmed.tracked_rim) }}，{{ mmss(rimTracking.first_confirmed.t) }}</p>',
    '      <p v-else>尚未确认篮筐，请检查标注和原视频，不能将无结果理解为没有投篮。</p>',
    '      <p v-if="rimTracking.first_confirmed && rimTracking.first_confirmed.hint_relation">提示点{{ rimTracking.first_confirmed.hint_relation.inside_box ? "在首次确认框内" : "在首次确认框外" }}，距框中心 {{ Math.round(rimTracking.first_confirmed.hint_relation.distance_px) }} 像素。这只表示与检测框的位置关系；框外不代表标注错误，可回看画面确认。</p>',
    '      <p>片尾跟踪位置：{{ rimPosition(rimTracking.last_tracked) }}{{ rimTracking.last_tracked && !rimTracking.last_tracked.fresh ? "（已失效，不用于新判定）" : "" }}</p>',
    '      <ul style="max-height:260px;overflow:auto">',
    '        <li v-for="(r,i) in rimTracking.transitions" :key="i" style="margin:8px 0">',
    '          <button class="el-button el-button--small" :disabled="!videoUrl" @click="gotoRimTransition(r)">回看 {{ mmss(r.t) }}</button>',
    '          {{ rimTransitionLabel(r.reason) }}：{{ rimPosition(r.previous) }} → {{ rimPosition(r.current) }}；收尾 {{ r.closed_attempts }} 条未决出手',
    '        </li>',
    '      </ul>',
    '    </details>',
    '    <div class="card" v-if="!sampleReview && (!game.judgement || game.judgement.state!==\'cannot_judge\')">',
    '      <h3 class="card-title">比分与球队统计</h3>',
    '      <big-scoreboard :game="game" />',
    '      <el-tag v-if="assumedValue" type="warning" size="small" effect="plain" style="margin-top:8px">分值尚未确认</el-tag>',
    '    </div>',
    '    <details class="card" v-if="evidence.length"><summary>识别依据与限制</summary>',
    '      <div class="grid grid-2" style="margin-top:12px"><div v-for="(e,i) in evidence" :key="\'ev\'+i" class="kpi">',
    '        <div class="k">{{ e.k }}</div><div class="v" style="font-size:15px">{{ e.v }}</div><div class="d">{{ e.d }}</div>',
    '      </div></div>',
    '    </details>',
    '  </template>',
    '</div>'
  ].join('\n')
};
