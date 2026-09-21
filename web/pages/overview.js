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
      showVideo: false,
      activeRow: -1,
      videoReady: false,
      videoErr: '',
      filterTeam: 'all',
      filterMade: 'all'      // all | made | miss
    };
  },
  computed: {
    game: function () { return this.S.game; },
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
      var vis = m.visual;
      if (vis) {
        out.push({ k: '视觉路径（球+篮筐）', v: '识别出手 ' + vis.shots + ' 次 / 判进 ' +
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
    hasCarryIn: function () {
      var ci = this.game && this.game.carry_in;
      return !!(ci && (ci.home || ci.away));
    },
    videoUrl: function () {
      if (!this.S.jobId || this.S.demoMode) return '';
      return window.API.videoUrl(this.S.jobId);
    },
    /** 时间轴：来自 game.timeline，可按球队/命中与否过滤 */
    timeline: function () {
      var rows = (this.game && this.game.timeline) || [];
      var self = this;
      return rows.filter(function (e) {
        if (self.filterTeam !== 'all' && e.team !== self.filterTeam) return false;
        if (self.filterMade === 'made' && !e.made) return false;
        if (self.filterMade === 'miss' && e.made) return false;
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
    /** 点击事件行：有视频就 seek，没有视频只高亮 */
    gotoEvent: function (row, idx) {
      this.activeRow = idx;
      var v = this.$refs.video;
      if (v && this.showVideo) {
        try { v.currentTime = Math.max(0, Number(row.t) - 0.6); v.play(); } catch (e) {}
      }
    },
    onVideoMeta: function () { this.videoReady = true; this.videoErr = ''; },
    onVideoError: function () { this.videoErr = '无法加载视频流（/api/games/{id}/video），可能未关联原始视频或浏览器不支持该编码'; },
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
    '    <!-- ① 比分牌 + 分节比分 -->',
    '    <div class="card">',
    '      <h3 class="card-title">比赛总览 <span class="sub">数据来源：GET /api/games/{{ S.jobId }}（game.json）</span>',
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
    '      <h3 class="card-title">证据来源 <span class="sub">game.meta · 自动计分用了哪几路证据</span></h3>',
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
    '        <h3 class="card-title">{{ hasCarryIn ? \'本片段比分走势\' : \'比分走势\' }} <span class="sub">{{ hasCarryIn ? (\'不含比分牌带入的 \' + game.carry_in.home + \':\' + game.carry_in.away) : \'game.progression · 阶梯累计得分\' }}</span></h3>',
    '        <echarts-box :option="progressOption" height="330px" />',
    '      </div>',
    '      <div class="card">',
    '        <h3 class="card-title">分差走势 <span class="sub">主队 - 客队，正数表示主队领先</span></h3>',
    '        <echarts-box :option="scoreDiffOption" height="330px" />',
    '      </div>',
    '    </div>',

    '    <!-- ④ 视频 + 事件时间轴 -->',
    '    <div class="grid grid-court">',
    '      <div class="card">',
    '        <h3 class="card-title">事件时间轴 <span class="sub">game.timeline · 共 {{ (game.timeline||[]).length }} 次出手</span>',
    '          <span class="grow"></span>',
    '          <el-radio-group v-model="filterMade" size="small">',
    '            <el-radio-button label="all">全部</el-radio-button>',
    '            <el-radio-button label="made">仅命中</el-radio-button>',
    '            <el-radio-button label="miss">仅未中</el-radio-button>',
    '          </el-radio-group>',
    '          <el-select v-model="filterTeam" size="small" style="width:130px">',
    '            <el-option label="双方" value="all" />',
    '            <el-option :label="teamName(\'home\')" value="home" />',
    '            <el-option :label="teamName(\'away\')" value="away" />',
    '          </el-select>',
    '        </h3>',
    '        <div class="timeline">',
    '          <div v-for="(e,i) in timeline" :key="i" class="tl-row" :class="{active: activeRow===i}" @click="gotoEvent(e,i)">',
    '            <span class="t">{{ mmss(e.t) }}</span>',
    '            <span><span class="tl-badge" :class="e.team===\'home\'?\'h\':\'a\'">{{ e.team===\'home\' ? teamName(\'home\') : teamName(\'away\') }}</span>',
    '              <span class="tl-badge" :class="e.made?\'made\':\'miss\'" style="margin-left:4px">{{ e.made ? (e.counts_for_score===false ? \'+\' + e.value + \' 未确认\' : (e.value_estimated ? \'+\' + e.value + \' 待确认\' : \'+\'+(e.points||e.value))) : \'未中\' }}</span></span>',
    '            <span class="pl">第{{ e.period }}节 {{ e.player }} · {{ e.zone }} · {{ e.value }}分出手 · {{ e.source }}</span>',
    '            <span class="mono muted" style="font-size:12px">{{ (e.confidence*100).toFixed(0) }}%</span>',
    '          </div>',
    '          <el-empty v-if="!timeline.length" description="无符合条件的事件" :image-size="70" />',
    '        </div>',
    '      </div>',

    '      <div class="card">',
    '        <h3 class="card-title">原始视频 <span class="sub">GET /api/games/{{ S.jobId }}/video（Range 支持）</span></h3>',
    '        <div class="row" style="margin-bottom:8px">',
    '          <el-switch v-model="showVideo" active-text="显示视频" />',
    '          <span class="hint" v-if="showVideo && !videoReady && !videoErr">正在加载视频流…</span>',
    '        </div>',
    '        <video v-if="showVideo && videoUrl" ref="video" :src="videoUrl" controls preload="metadata"',
    '               style="width:100%;border-radius:10px;background:#000;max-height:320px"',
    '               @loadedmetadata="onVideoMeta" @error="onVideoError"></video>',
    '        <el-alert v-if="videoErr" type="warning" :closable="false" :title="videoErr" />',
    '        <el-empty v-if="showVideo && !videoUrl" :image-size="70"',
    '                  description="演示数据模式下没有视频源；连接后端并新建 video 任务后可在此播放" />',
    '        <div class="hint" style="margin-top:10px">',
    '          点击左侧任意一条事件：有视频时会把进度条跳到 <code>t - 0.6s</code> 并自动播放；没有视频时只高亮该行。',
    '        </div>',
    '        <el-divider />',
    '        <div class="row">',
    '          <el-statistic title="总回合数" :value="game.possessions || 0" />',
    '          <el-statistic title="出手总数" :value="(game.timeline||[]).length" />',
    '          <el-statistic title="待复核" :value="(game.needs_review||[]).length" />',
    '          <el-statistic title="视频时长(秒)" :value="Math.round(game.duration||0)" />',
    '        </div>',
    '      </div>',
    '    </div>',
    '  </template>',
    '</div>'
  ].join('\n')
};
