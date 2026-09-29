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
      var counts = { total: 0, made: 0, miss: 0, unknown: 0 };
      var self = this;
      ((this.game && this.game.timeline) || []).forEach(function (row) {
        counts.total++;
        counts[self.resultClass(row) === 'needs' ? 'unknown' : row.made ? 'made' : 'miss']++;
      });
      return counts;
    },
    game: function () { return this.S.game; },
    rimTracking: function () {
      return (((this.game || {}).meta || {}).shot_engine_details || {}).rim_tracking || null;
    },
    rimAvailability: function () {
      return this.rimTracking && this.rimTracking.availability || null;
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
      if (sb && sb.frames_read) {
        var pct = Math.round(sb.frames_hit / sb.frames_read * 100);
        out.push({ k: '广播比分牌', v: '读取成功 ' + sb.frames_hit + '/' + sb.frames_read +
          ' 帧（' + pct + '%）', d: '比分与得分时刻由它给出（导播系统直接渲染，零噪声）' });
      }
      if (m.hoopsight_error) {
        out.push({k: '篮下识别未完成', v: '本次结果可能漏球',
          d: m.hoopsight_error + '；请检查篮筐标注与尺寸，不能将本次统计视为完整比赛结果。'});
      }
      if (m.shot_engine === 'legacy') {
        out.push({ k: '投篮检测', v: '逐次出手引擎',
          d: '保留命中、未中与未知；推算建议不自动计分，检测次数仍需复核。' });
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
          d: '打铁候选置信度低，进人工复核队列，不进比分统计' });
      }
      if (m.teams) {
        out.push({ k: '分队依据', v: '球衣颜色聚类 ' + (m.teams.players || 0) + ' 名球员',
          d: '绿色系 ' + m.teams.green_hue + '° / 红色系 ' + m.teams.red_hue + '°' });
      }
      if (m.scoreboard_error) {
        out.push({ k: '比分牌', v: '未启用或读取失败', d: m.scoreboard_error });
      }
      return out;
    },
    courtMode: function () {
      var p = String((this.game && this.game.score_policy) || 'scoreboard').toLowerCase();
      return ['court', 'visual', 'auto'].indexOf(p) >= 0;
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
      lines.push('  ③ 人工复核：在「人工复核」页逐条确认/补录，'
        + '判完再看总览与热区。');
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
        // 「待确认」的判据与徽章/文案**共用同一个**（`resultClass` → `D.isUnknown`）：
        // 结果未知时 made 是 null，光看 `e.result` 会把"缺 result 但结果为空"的行
        // 漏到"未中"里、同时从"待确认"里漏掉（实测这处边界不一致）。
        var unknown = self.resultClass(e) === 'needs';
        if (self.filterMade === 'made' && (!e.made || unknown)) return false;
        if (self.filterMade === 'miss' && (unknown || e.made)) return false;
        if (self.filterMade === 'unknown' && !unknown) return false;
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
            lineStyle: { width: 2.4, color: '#2f6fed' }, itemStyle: { color: '#2f6fed' },
            areaStyle: { color: 'rgba(47,111,237,0.08)' },
            markLine: { silent: true, symbol: 'none', lineStyle: { type: 'dashed', color: '#c9ced6' }, data: q },
            data: data.map(function (p) {
              return [p.t, p.home, p.made && p.scorer ? '得分：' + p.scorer + ' +' + p.value : ''];
            })
          },
          {
            name: an, type: 'line', step: 'end', showSymbol: false,
            lineStyle: { width: 2.4, color: '#f2762e' }, itemStyle: { color: '#f2762e' },
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
    teamName: function (s) { return window.D.teamName(this.game, s); },
    mmss: function (t) { return window.D.mmss(t); },
    /**
     * 时间轴徽章配色：命中=绿、未中=灰、**待确认=橙**。
     * 为什么单独抽一个方法：结果未知时 `e.made` 是 null（后端已显式输出 null，
     * 不再用 false 占位），直接写 `e.made?'made':'miss'` 会把"待确认"配成"未中"的灰。
     * 待确认沿用既有但一直没被用到的 `.needs` 样式 —— 语义就是"需要人工复核"。
     */
    resultClass: function (e) {
      if (!e) return 'miss';
      if (window.D.isUnknown(e)) return 'needs';
      return e.made ? 'made' : 'miss';
    },
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
      return row.team === 'home' ? 'h' : 'a';
    },
    goUpload: function () { location.hash = '#/upload'; }
  },
  template: [
    '<div>',
    '  <div class="card" v-if="!game">',
    '    <el-empty description="暂无比赛数据"><el-button type="primary" @click="goUpload">去新建任务</el-button></el-empty>',
    '  </div>',

    '  <template v-else>',
    "    <div class=\"card\">",
    "      <h3 class=\"card-title\">原始视频 <span class=\"sub\">拖动进度条回看，也可点击下方投篮时间</span></h3>",
    "      <video v-if=\"videoUrl\" :key=\"videoUrl\" ref=\"video\" :src=\"videoUrl\" controls playsinline preload=\"metadata\" style=\"display:block;width:100%;max-height:520px;background:#000;border-radius:10px\" @loadedmetadata=\"onVideoMeta\" @error=\"onVideoError\"></video>",
    "      <p v-if=\"videoUrl && !videoReady && !videoErr\" class=\"hint\">正在加载原视频…</p>",
    "      <el-alert v-if=\"videoErr\" type=\"warning\" :closable=\"false\" :title=\"videoErr\" />",
    "      <el-empty v-if=\"!videoUrl\" description=\"此份演示数据没有关联原视频；上传视频后可在这里回看。\" :image-size=\"70\" />",
    "    </div>",
    "    <div class=\"card\">",
    "      <h3 class=\"card-title\">检测到 {{ shotCounts.total }} 条投篮候选</h3>",
    "      <div class=\"row\" style=\"flex-wrap:wrap;gap:20px;margin-bottom:12px\" aria-label=\"全部投篮候选统计\">",
    "        <span>命中 <strong>{{ shotCounts.made }}</strong></span>",
    "        <span>未中 <strong>{{ shotCounts.miss }}</strong></span>",
    "        <span>未知 <strong>{{ shotCounts.unknown }}</strong></span>",
    "      </div>",
    "      <p class=\"hint\">未知表示结果证据不足，不计入命中或未中。候选可能漏检或重复，完整投篮次数需复核确认。</p>",
    '        <h3 class="card-title" style="flex-wrap:wrap">投篮记录 <span class="sub">出手与结果分开看，未知不算未中</span>',
    '          <span class="grow"></span>',
    '          <el-radio-group v-model="filterMade" size="small">',
    '            <el-radio-button label="all">全部</el-radio-button>',
    '            <el-radio-button label="made">仅命中</el-radio-button>',
    '            <el-radio-button label="miss">仅未中</el-radio-button>',
      '            <el-radio-button label="unknown">未知 / 待确认</el-radio-button>',
    '          </el-radio-group>',
    '          <el-select v-model="filterTeam" size="small" style="width:130px">',
    '            <el-option label="双方" value="all" />',
    '            <el-option :label="teamName(\'home\')" value="home" />',
    '            <el-option :label="teamName(\'away\')" value="away" />',
    '          </el-select>',
    '        </h3>',
    '        <div class="timeline">',
    '          <div v-for="(e,i) in timeline" :key="(game.timeline||[]).indexOf(e)" class="tl-row" style="display:flex;flex-wrap:wrap" :class="{active: activeRow===(game.timeline||[]).indexOf(e)}">',
    '            <button class="el-button el-button--small" @click="gotoEvent(e,i)">看出手 {{ mmss(e.t) }}</button>',
    '            <span><span class="tl-badge" :class="e.team===\'home\'?\'h\':\'a\'">{{ e.team===\'home\' ? teamName(\'home\') : teamName(\'away\') }}</span>',
    "              <span class=\"tl-badge\" :class=\"resultClass(e)\" style=\"margin-left:4px\">{{ resultClass(e) === 'needs' ? '未知（待确认）' : e.made ? '命中' : '未中' }}</span></span>",
    "            <span class=\"pl\">{{ e.player || \"球员未识别\" }} · {{ e.zone || \"位置未知\" }}</span>",
    "            <button v-if=\"e.review_t != null\" class=\"el-button el-button--small\" @click=\"gotoEvent(e,i,true)\">看待确认位置 {{ mmss(e.review_t) }}</button>",
    "            <button v-else-if=\"e.crossing_t != null\" class=\"el-button el-button--small\" @click=\"gotoEvent(e,i,true)\">看篮下 {{ mmss(e.crossing_t) }}</button>",
    "            <button v-else-if=\"e.decision_t != null\" class=\"el-button el-button--small\" @click=\"gotoEvent(e,i,true)\">看判定收尾 {{ mmss(e.decision_t) }}</button>",
    "            <span v-if=\"e.release_source\" class=\"hint\">时间来源：{{ e.release_source === 'player_feet' ? '球员位置回溯' : '球轨迹' }}</span>",
    '          </div>',
    '          <el-empty v-if="!timeline.length" description="无符合条件的事件" :image-size="70" />',
    '        </div>',
    '    </div>',
    '    <section class="card" v-if="rimAvailability && rimAvailability.unavailable_ranges.length" aria-label="检测覆盖范围">',
    '      <h3 class="card-title">部分时段无法持续判定投篮</h3>',
    '      <p>以下时段连续至少 2 秒没有可用的篮筐跟踪，可能漏掉投篮；没有记录不代表没有出手。可回看原视频核对。</p>',
    '      <p class="hint">可用篮筐覆盖 {{ rimAvailability.usable_frames }} / {{ rimAvailability.sampled_frames }} 个采样帧（{{ Math.round(rimAvailability.usable_fraction * 100) }}%）。这是跟踪可用性，不是识别准确率；有筐也不保证球可见。</p>',
    '      <ul><li v-for="(gap,i) in rimAvailability.unavailable_ranges" :key="i">',
    '        <button class="el-button el-button--small" :disabled="!videoUrl" @click="gotoRimTransition({t:gap.start})">回看 {{ mmss(gap.start) }}–{{ mmss(gap.end) }}</button>',
    '      </li></ul>',
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
    '      <p class="hint">以下记录表示跟踪段重新建立或切镜，不代表已确认换成另一个物理篮筐。重新建立时会断开旧投篮证据链。</p>',
    '      <ul style="max-height:260px;overflow:auto">',
    '        <li v-for="(r,i) in rimTracking.transitions" :key="i" style="margin:8px 0">',
    '          <button class="el-button el-button--small" :disabled="!videoUrl" @click="gotoRimTransition(r)">回看 {{ mmss(r.t) }}</button>',
    '          {{ rimTransitionLabel(r.reason) }}：{{ rimPosition(r.previous) }} → {{ rimPosition(r.current) }}；收尾 {{ r.closed_attempts }} 条未决出手',
    '        </li>',
    '      </ul>',
    '    </details>',
    '    <h2>分模块分析</h2>',
    '    <p v-if="(game.timeline || []).some(e => e.value_assumed || (e.tags || []).includes(\'value_assumed\'))" class="hint">分值尚未确认：当前按每次命中 2 分暂计，不代表已识别两分或三分。位置未知的出手不生成热区或出手距离，请标定球场并复核出手位置。</p>',
    '    <p class="hint">以下统计基于当前已识别与已确认的记录；未知结果不计入命中率。</p>',
    // 这次分析什么都没出时，**先把原因说清楚**：用户看到 0:0 + 空列表会以为功能坏了，
    // 实际多半是上游判据放弃（镜头在动 / 球太小 / 没有记分牌），页面必须自己讲明白。
    '    <div class="card" v-if="emptyAnalysis">',
    '      <h3 class="card-title">比赛总览 <span class="sub">这次分析没有产出得分事件</span></h3>',
    '      <el-alert type="warning" :closable="false" show-icon',
    '        title="这份结果里没有任何进球/出手 —— 不是页面坏了，是上游没判出来"',
    '        :description="emptyWhy" />',
    '    </div>',
    '    <!-- ① 比分牌 + 分节比分 -->',
    '    <div class="card">',
    '      <h3 class="card-title">比分与球队统计 <span class="sub">当前记录的得分汇总</span>',
    '        <span class="grow"></span>',
    '        <el-tag v-if="S.demoMode" type="warning" size="small" effect="plain">演示数据</el-tag>',
    '        <el-tag v-else type="success" size="small" effect="plain">后端数据</el-tag>',
    '      </h3>',
    '      <big-scoreboard :game="game" />',
    '      <el-alert v-if="game.judgement && game.judgement.state===\'cannot_judge\'" type="warning" :closable="false" show-icon style="margin-top:12px"',
    '        :title="game.judgement.note"',
    '        :description="(game.judgement.reasons||[]).join(\' ｜ \') + \'。下面的 0 : 0 只表示「没有检测到得分」，不等于双方真的都没得分。\'" />',
    '    </div>',

    '    <!-- ①b 证据来源：这次结论是怎么来的 -->',
    '    <div class="card" v-if="evidence.length">',
    '      <h3 class="card-title">证据来源 <span class="sub">本次分析的依据与限制</span></h3>',
    '      <div class="grid grid-2">',
    '        <div v-for="(e,i) in evidence" :key="\'ev\'+i" class="kpi">',
    '          <div class="k">{{ e.k }}</div>',
    '          <div class="v" style="font-size:15px">{{ e.v }}</div>',
    '          <div class="d">{{ e.d }}</div>',
    '        </div>',
    '      </div>',
    '    </div>',

    '    <!-- ② 关键指标对比 -->',
    '    <div class="grid grid-4">',
    '      <div class="kpi home" v-for="(k,i) in kpis.slice(0,4)" :key="\'kh\'+i">',
    '        <div class="k">{{ k.k }}</div>',
    '        <div class="row" style="justify-content:space-between">',
    '          <span class="v">{{ k.hv }}</span>',
    '          <span class="v" style="color:var(--away);text-align:right">{{ k.av }}</span>',
    '        </div>',
    '        <div class="d">{{ teamName(\'home\') }} · {{ teamName(\'away\') }}</div>',
    '      </div>',
    '    </div>',
    '    <div class="grid grid-4">',
    '      <div class="kpi" v-for="(k,i) in kpis.slice(4)" :key="\'ka\'+i">',
    '        <div class="k">{{ k.k }}</div>',
    '        <div class="row" style="justify-content:space-between">',
    '          <span class="v" style="color:var(--home)">{{ k.hv }}</span>',
    '          <span class="v" style="color:var(--away);text-align:right">{{ k.av }}</span>',
    '        </div>',
    '        <div class="d">主队 / 客队</div>',
    '      </div>',
    '    </div>',

    '    <!-- ③ 走势图 -->',
    '    <div class="grid grid-2">',
    '      <div class="card">',
    '        <h3 class="card-title">{{ hasCarryIn ? \'本片段比分走势\' : \'比分走势\' }} <span class="sub">{{ hasCarryIn ? (\'不含比分牌带入的 \' + game.carry_in.home + \':\' + game.carry_in.away) : \'按已确认得分累加\' }}</span></h3>',
    '        <echarts-box :option="progressOption" height="330px" />',
    '      </div>',
    '      <div class="card">',
    '        <h3 class="card-title">分差走势 <span class="sub">主队 - 客队，正数表示主队领先</span></h3>',
    '        <echarts-box :option="scoreDiffOption" height="330px" />',
    '      </div>',
    '    </div>',

    '  </template>',
    '</div>'
  ].join('\n')
};
