/* ==========================================================================
   pages/review.js —— 页面 7：人工复核（自研加分点）
   --------------------------------------------------------------------------
   数据来源接口：
     GET  /api/games/{job_id}                          game.json → needs_review 数组
     POST /api/games/{job_id}/shots/{index}/correct    body {made, value} → {ok:true}
         index 是「出手在整场事件流中的序号」（后端按 shots 顺序编号）
   业务口径（答辩讲解要点）：
     * 后端计分规则引擎用「加权投票 + 置信度」融合球穿筐 / 记分牌 OCR / 网动多路证据，
       置信度低于阈值（RulesConfig.review_threshold = 0.6）的出手进入复核队列，
       而不是硬判 —— 这是「可解释、可干预」的产品差异点。
     * 改判会写回统计口径：该次出手的分值（1/2/3）与命中结果重新参与
       比分、球队统计、球员统计、热区聚合，报告与导出随之更新。
     * 复核页自身不重算规则，只提交人工结论（后端 outcome_source 会标记为 manual）。
   无后端时的降级：只做本地改判（前端重算统计口径），并在页面顶部明确标注。
   ========================================================================== */
window.PAGES = window.PAGES || {};

window.PAGES['review'] = {
  name: 'page-review',
  data: function () {
    return {
      S: window.STORE,
      rows: [],                 // 本地可改判队列（复制自 game.needs_review）
      onlyInferred: false,
      showAll: false,           // 是否把高置信度出手也列出来
      busyIdx: -1,
      localLog: [],             // 改判记录（用于答辩演示时说明写回口径）
      manual: { t: 0, team: '', value: 2, result: '', x: null, y: null },  // 必须主动选择结果；无坐标不进入热区
      adding: false
    };
  },
  computed: {
    isExample: function () { return (this.S.jobId || "").indexOf("example_") === 0; },
    game: function () { return this.S.game; },
    /** 全部出手（timeline 口径），用于「显示全部」模式 */
    allShots: function () {
      return ((this.game && this.game.timeline) || []).map(function (s, i) {
        return Object.assign({}, s, { _index: i });
      });
    },
    list: function () {
      var list = this.showAll ? this.allShots : this.rows;
      return this.onlyInferred ? list.filter(this.hasSuggestion) : list;
    },
    stats: function () {
      var total = this.allShots.length;
      var need = this.rows.length;
      var done = this.localLog.length;
      return {
        total: total, need: need, done: done, left: need,
        rate: total ? (1 - need / Math.max(1, total)) : 1
      };
    },
    /** 是否可提交到后端（演示/无后端时只做本地改判） */
    canSubmit: function () { return this.S.backendOk && !this.S.demoMode && this.S.jobId && this.S.jobId !== 'demo' && this.S.jobId.indexOf('example_') !== 0; }
  },
  watch: {
    // game 变化（新建任务/切换任务）时重建复核队列
    'S.game': {
      deep: false,
      handler: function () { this.build(); }
    }
  },
  created: function () { this.build(); },
  methods: {
    shotValueLabel: function (row) { return window.D.shotValueLabel(row); },
    /** 手动补录一次进球：填时间/球队/分值，后端按 manual 出手整条重算。 */
    addManual: function () {
      var self = this;
      if (!this.canSubmit) {
        this.$message.warning('无后端/演示模式下不能补录');
        return;
      }
      if (['made', 'missed'].indexOf(this.manual.result) < 0) {
        this.$message.warning('请选择中或没中');
        return;
      }
      var t = Number(this.manual.t);
      if (!Number.isFinite(t) || !(t >= 0)) {
        this.$message.warning('请输入出手时间（秒）');
        return;
      }
      var x = this.manual.x === null || this.manual.x === '' ? null : Number(this.manual.x);
      var y = this.manual.y === null || this.manual.y === '' ? null : Number(this.manual.y);
      if ((x === null) !== (y === null)) {
        this.$message.warning('要进入投篮热区，请同时填写球场 X、Y 坐标');
        return;
      }
      this.adding = true;
      window.API.addManualShot(this.S.jobId, {
        t: t, team: this.manual.team, value: Number(this.manual.value), result: this.manual.result, x: x, y: y
      }).then(function (r) {
        self.adding = false;
        self.$message.success('已补录：' + (r.summary || ''));
        return window.APP_LOAD_JOB(self.S.jobId);
      }).then(function () {
        self.build();
      }).catch(function (e) {
        self.adding = false;
        self.$message.error('补录失败：' + (e && e.message ? e.message : e));
      });
    },

    /** 用 game.needs_review 初始化复核队列，并记录它在全场出手里的序号 index */
    build: function () {
      var g = this.game;
      var timeline = (g && g.timeline) || [];
      var need = (g && g.needs_review) || [];
      this.rows = need.map(function (s) {
        // index：优先用后端给的 _index/shot_index，否则按 t 匹配 timeline 序号
        var explicit = s.index !== undefined ? s.index : s.shot_index;
        var idx = Number.isInteger(explicit) && explicit >= 0 && explicit < timeline.length
          ? explicit : findIndex(timeline, s);
        return Object.assign({}, s, { _index: idx, _corrected: false, _origin: { made: s.made, value: s.value, result: s.result } });
      }).sort(function (a, b) { return a._index - b._index; });

      function findIndex(list, s) {
        // Legacy timelines round seconds to two decimals. Never choose an ambiguous match.
        var candidates = [];
        list.forEach(function (e, i) {
          if (Math.abs(Number(e.t) - Number(s.t)) <= 0.005001 && e.player_id === s.player_id)
            candidates.push(i);
        });
        var exact = candidates.filter(function (i) { return Number(list[i].value) === Number(s.value); });
        if (exact.length === 1) return exact[0];
        return candidates.length === 1 ? candidates[0] : -1;
      }
    },
    isUnknown: function (row) { return row.result === 'unknown' || row.made == null; },
    suggestionReviewTime: function (row) {
      var t = row.review_t != null ? row.review_t : row.crossing_t;
      return typeof t === 'number' && Number.isFinite(t) && t >= 0 ? t : null;
    },
    unknownReason: function (row) {
      if (!this.isUnknown(row)) return '';
      var codes = [row.review_reason, row.evidence].concat(row.tags || []);
      if (codes.includes('no_rim_outcome_evidence')) return '已跟踪轨迹没有进入筐口区域，也没有穿越记录，结果无法判定。';
      if (codes.includes('below_rim_tracking_gap')) return '球在筐下方出现后，连续实测球轨迹中断，结果无法判定。';
      if (codes.includes('cross_hoop_uncertain')) return '这一刻篮筐位置不够稳定，无法可靠判定。';
      if (codes.includes('cross_rim_contact')) return '球的轨迹靠近筐沿，可能擦筐；是否进球需要人工确认。';
      return '';
    },
    hasSuggestion: function (row) {
      return this.isUnknown(row) && !this.unknownReason(row) && typeof row.suggested_made === 'boolean';
    },
    resultLabel: function (row) { return window.D.shotDisplay(row).label; },
    resultReason: function (row) { return window.D.shotDisplay(row).reason; },
    suggestionReason: function (row) {
      if (row.evidence === 'legacy_occlusion_descent') return '筐口短暂遮挡后，连续观测到球在筐下下降；尚未确认穿筐，请回看核实';
      return row.evidence === 'cross_extrapolated' ? '筐口轨迹缺失，依据趋势拟合推算' : '筐口轨迹缺失，依据前后位置插值推算';
    },
    teamName: function (s) { return window.D.teamName(this.game, s); },
    mmss: function (t) { return window.D.mmss(t); },
    /** 位置缩略图：court.js 的标准半场 + 该次出手标记 */
    thumb: function (row) { return this.isUnknown(row) ? '' : window.Court.shotThumb(row, {}); },
    conf: function (row) { return Math.round((Number(row.confidence) || 0) * 100); },
    confType: function (row) {
      var c = Number(row.confidence) || 0;
      return c < 0.4 ? 'danger' : c < 0.6 ? 'warning' : 'info';
    },
    nameOf: function (row) {
      var id = row.player_id;
      for (var i = 0; i < (this.S.players || []).length; i++) {
        if (this.S.players[i].player_id === id) return D.playerLabel(this.S.players[i]);
      }
      return D.playerLabel({player_id:id});
    },

    /** 改判入口：value 传 1|2|3，made 传 true/false */
    async correct(row, made, value) {
      if ((this.S.jobId || '').indexOf('example_') === 0) { this.$message.warning('样例只供查看'); return; }
      var self = this;
      if (this.busyIdx !== -1) return;
      if (!Number.isInteger(row._index) || row._index < 0) {
        this.$message.error('这条记录无法定位到比赛事件，请刷新后重试');
        return;
      }
      this.busyIdx = row._index;

      // 1) 有后端：POST /api/games/{id}/shots/{index}/correct
      //    后端会累积 corrections.json 并整条管线重算，返回 {ok, summary, score, corrections, needs_review_left}
      var persisted = false;
      var remote = null;
      if (this.canSubmit) {
        try {
          remote = await window.API.correctShot(this.S.jobId, row._index, { made: !!made, value: Number(value) });
          persisted = true;
          this.$message.success('已提交后端改判，统计口径已写回' +
            (remote && remote.score ? ('（后端比分 ' + remote.score.home + ':' + remote.score.away + '）') : ''));
        } catch (e) {
          this.$message.error('改判未保存：' + e.message + '。请重试。');
          this.busyIdx = -1;
          return;
        }
      } else {
        this.$message.info('演示/离线模式：本次改判只在本地重算统计口径，不会写回后端');
      }

      // 2) 本地写回：更新 needs_review 与 timeline，并重算比分/球队统计/热区
      if (persisted) {
        try { await window.APP_LOAD_JOB(this.S.jobId); this.build(); }
        catch (e) { this.$message.warning('改判已保存，但刷新失败，请重新载入比赛'); }
      } else {
        this.applyLocal(row, made, value);
      }
      row._corrected = true;
      row.made = !!made;
      row.value = Number(value);
      this.localLog.unshift({
        t: this.mmss(row.t), player: this.nameOf(row), made: made, value: value,
        before: row._origin, confidence: row.confidence, persisted: persisted,
        summary: remote && remote.summary ? remote.summary : ''
      });
      this.busyIdx = -1;
    },

    /** 本地重算：把改判结果回写到 timeline / needs_review，再交给全局的规范化+聚合 */
    applyLocal: function (row, made, value) {
      var g = this.S.game;
      if (!g) return;
      var tl = g.timeline || [];
      [g.timeline, g.needs_review].forEach(function (list) {
        (list || []).forEach(function (e) {
          if (e === row || (e.player_id === row.player_id &&
            Math.abs(Number(e.t) - Number(row.t)) < 0.001)) {
            e.made = !!made;
            e.result = made ? 'made' : 'missed';
            e.value = Number(value);
            e.points = made ? Number(value) : 0;
            e.source = 'manual';       // 与后端 OutcomeSource.MANUAL 对应
            e.confidence = 1;
          }
        });
      });
      // 重算比分与分节比分（保持与后端 pipeline 自检一致：分节之和 = 总分）
      var h = 0, a = 0;
      var qs = [];
      for (var p = 1; p <= (g.periods || 4); p++) qs.push({ period: p, home: 0, away: 0 });
      tl.forEach(function (e) {
        var pts = e.result !== 'unknown' && e.counts_for_score !== false && e.made ? Number(e.points === undefined ? e.value : e.points) : 0;
        if (e.team === 'home') { h += pts; if (qs[Number(e.period || 1) - 1]) qs[Number(e.period || 1) - 1].home += pts; }
        else if (e.team === 'away') { a += pts; if (qs[Number(e.period || 1) - 1]) qs[Number(e.period || 1) - 1].away += pts; }
      });
      g.score = { home: h, away: a };
      g.quarter_scores = qs;

      // 球员统计重算（口径与后端 rules.compute_player_stats 一致）
      var byId = {};
      (this.S.players || []).forEach(function (p) { byId[p.player_id] = p; });
      function blank(p, team) {
        return {
          player_id: p, name: (byId[p] && byId[p].name) || p, team: team || (byId[p] && byId[p].team) || 'home',
          jersey: byId[p] ? byId[p].jersey : null,
          points: 0, fgm: 0, fga: 0, tpm: 0, tpa: 0, ftm: 0, fta: 0,
          reb: (byId[p] && byId[p].reb) || 0, ast: (byId[p] && byId[p].ast) || 0,
          stl: (byId[p] && byId[p].stl) || 0, blk: (byId[p] && byId[p].blk) || 0,
          tov: (byId[p] && byId[p].tov) || 0, pf: (byId[p] && byId[p].pf) || 0,
          shots: []
        };
      }
      var agg = {};
      tl.forEach(function (e) {
        var r = agg[e.player_id] || (agg[e.player_id] = blank(e.player_id, e.team));
        var v = Number(e.value || 2);
        if (e.result === 'unknown') return;
        r.points += e.counts_for_score !== false && e.made ? v : 0;
        if (v === 1) { r.fta++; if (e.made) r.ftm++; }
        else { r.fga++; if (e.made) r.fgm++; if (v === 3) { r.tpa++; if (e.made) r.tpm++; } }
        r.shots.push({ t: e.t, x: e.x, y: e.y, made: !!e.made, value: v });
      });
      var D = window.D;
      var rows = Object.keys(agg).map(function (k) {
        var r = agg[k];
        r.fg_pct = r.fga ? r.fgm / r.fga : 0;
        r.tp_pct = r.tpa ? r.tpm / r.tpa : 0;
        r.ft_pct = r.fta ? r.ftm / r.fta : 0;
        r.efg = r.fga ? (r.fgm + 0.5 * r.tpm) / r.fga : 0;
        r.ts = (r.fga + 0.44 * r.fta) ? r.points / (2 * (r.fga + 0.44 * r.fta)) : 0;
        return r;
      }).sort(function (x, y) { return y.points - x.points; });

      // 球队汇总 + 热区重算，最后统一走全局规范化
      ['home', 'away'].forEach(function (side) {
        var st = { points: 0, fgm: 0, fga: 0, tpm: 0, tpa: 0, ftm: 0, fta: 0 };
        tl.forEach(function (e) {
          if (e.team !== side) return;
          var v = Number(e.value || 2);
          if (e.result === 'unknown') return;
          st.points += e.counts_for_score !== false && e.made ? v : 0;
          if (e.made) { if (v === 1) st.ftm++; else { st.fgm++; if (v === 3) st.tpm++; } }
          if (v === 1) st.fta++; else { st.fga++; if (v === 3) st.tpa++; }
        });
        st.fg_pct = st.fga ? st.fgm / st.fga : 0;
        st.tp_pct = st.tpa ? st.tpm / st.tpa : 0;
        if (g.teams && g.teams[side]) g.teams[side].stats = st;
      });
      g.needs_review = (g.needs_review || []).filter(function (e) { return Number(e.confidence) < 0.6; });

      // 重新走一遍全局规范化：出手点集 / 分区聚合 / 网格热力全部刷新
      var pts = D.shotsFromTimeline(g);
      var sc = { all: { points: pts, zones: [], grid: [], bin_size: 1 }, by_team: {} };
      this.S.applyGame(g, rows, sc, this.S.report, this.S.highlights);
      this.build();          // 复核队列跟着更新（已改判的不再是低置信度）
    },

    /** 一键批量：把所有剩余低置信度出手按「保持原判但标记为已确认」处理（演示用） */
    confirmAll: async function () {
      var self = this;
      var left = this.rows.filter(function (r) { return !r._corrected && !self.isUnknown(r); });
      if (!left.length) { this.$message.info('没有待处理的出手'); return; }
      for (var r of left) await self.correct(r, r.made, r.value);
    }
  },
  template: [
    '<div>',
    '  <div class="card" v-if="!game">',
    '    <el-empty description="暂无比赛数据" />',
    '  </div>',
    '  <template v-else>',
    '    <!-- ① 说明与统计 -->',
    '    <div class="card">',
    '      <h3 class="card-title">人工复核',
    '        <span class="grow"></span>',
    '        <el-tag :type="canSubmit ? \'success\' : \'warning\'" size="small" effect="dark">',
    '          {{ isExample ? \'样例只读\' : canSubmit ? \'改判将写回后端\' : \'演示模式：仅本地改判\' }}',
    '        </el-tag>',
    '      </h3>',
    '      <div class="grid grid-4">',
    '        <div class="kpi"><div class="k">识别出手</div><div class="v">{{ stats.total }}</div><div class="d">记录</div></div>',
    '        <div class="kpi"><div class="k">待复核</div><div class="v" style="color:#f5a623">{{ stats.need }}</div><div class="d">含建议</div></div>',
    '        <div class="kpi"><div class="k">已确认</div><div class="v" style="color:#22a06b">{{ stats.done }}</div><div class="d">本次</div></div>',
    '        <div class="kpi"><div class="k">无需复核</div><div class="v">{{ (stats.rate*100).toFixed(1) }}%</div><div class="d"><copy-note label="口径">= 1 - 待复核 / 总出手</copy-note></div></div>',
    '      </div>',
    '      <div class="row" style="margin-top:10px;flex-wrap:wrap">',
    '        <el-switch v-model="showAll" active-text="全部出手" />',
    '        <el-button size="small" @click="build">刷新</el-button>',
    '        <el-button size="small" type="primary" plain :disabled="!stats.left || isExample" @click="confirmAll">维持原判</el-button>',
    '      </div>',
    '    </div>',
    '    <!-- ①.5 手动补录 -->',
    '    <div class="card" v-if="!isExample">',
    '      <h3 class="card-title">补录漏掉的出手 </h3>',
    '      <div class="muted" style="margin-bottom:8px">填写半场坐标（米）后才会进入热区：X 为 -7.5 到 7.5，Y 为 -14 到 0；留空则只补事件。</div>',
    '      <div class="row" style="gap:12px;flex-wrap:wrap">',
    '        <el-input-number v-model="manual.t" :min="0" :max="36000" :step="0.1" controls-position="right" style="width:160px" />',
    '        <el-input-number v-model="manual.x" :min="-7.5" :max="7.5" :step="0.5" :precision="1" controls-position="right" placeholder="X (m)" style="width:140px" />',
    '        <el-input-number v-model="manual.y" :min="-14" :max="0" :step="0.5" :precision="1" controls-position="right" placeholder="Y (m)" style="width:140px" />',
    '        <el-select v-model="manual.team" style="width:120px">',
    '          <el-option label="球队未知" value="" /><el-option label="主队" value="home" /><el-option label="客队" value="away" />',
    '        </el-select>',
    '        <el-select v-model="manual.value" style="width:120px">',
    '          <el-option label="1 分" :value="1" /><el-option label="2 分" :value="2" /><el-option label="3 分" :value="3" />',
    '        </el-select>',
    '        <el-select v-model="manual.result" placeholder="选择结果" style="width:120px" aria-label="出手结果"><el-option label="中" value="made"/><el-option label="没中" value="missed"/></el-select>',
    '        <el-button type="primary" :loading="adding" :disabled="!canSubmit" @click="addManual">补录漏掉的出手</el-button>',
    '      </div>',
    '    </div>',
    '    <!-- ② 复核列表 -->',
    '    <div class="card">',
    '      <h3 class="card-title">出手列表 <span class="sub">筛选 {{ list.length }} 条</span></h3>',
    '      <div class="rev-row rev-head">',
    '        <div>时刻</div><div>球员</div><div>位置</div><div>结果</div><div>操作</div>',
    '      </div>',
    '      <div v-for="(row,i) in list" :key="i" class="rev-row">',
    '        <div>',
    '          <div class="mono">{{ mmss(row.t) }}</div>',
    '          <div class="muted" style="font-size:12px">第{{ row.period }}节 · 序号 {{ row._index===undefined ? \'—\' : row._index }}</div>',
    '        </div>',
    '        <div>',
    '          <div><span v-if="row.team===\'home\' || row.team===\'away\'" class="tl-badge" :class="row.team===\'home\'?\'h\':\'a\'">{{ row.team===\'home\' ? teamName(\'home\') : teamName(\'away\') }}</span>',
    '            <b style="margin-left:6px">{{ nameOf(row) }}</b></div>',
    '          <div class="muted" style="font-size:12px;margin-top:4px">',
    '            {{ row.zone || \'—\' }} · 距篮 {{ row.distance !== undefined ? row.distance : \'—\' }}m · 坐标 ({{ Number(row.x).toFixed(2) }}, {{ Number(row.y).toFixed(2) }})',
    '          </div>',
    '          <div class="muted" style="font-size:12px">来源：{{ row.outcome_source || row.source || \'—\' }}</div>',
    '        </div>',
    '        <div v-html="thumb(row)"></div>',
    '        <div>',
    '          <el-tag v-if="resultLabel(row)" size="small" :title="resultReason(row)" :type="row.made ? \'success\' : \'danger\'" effect="dark">',
    '            {{ resultLabel(row) }}<span v-if="shotValueLabel(row)"> · {{ shotValueLabel(row) }}</span>',
    '          </el-tag>',
    '          <div v-if="unknownReason(row)" style="margin-top:8px">',
    '            <div><copy-note label="判定依据">{{ unknownReason(row) }}</copy-note></div>',
    '            <div v-if="row.crossing_t != null">回看 {{ mmss(row.crossing_t) }} 附近</div>',
    '          </div>',
    '          <div v-if="hasSuggestion(row)" style="margin-top:8px">',
    '            <div v-if="suggestionReviewTime(row) != null">回看 {{ mmss(suggestionReviewTime(row)) }} 附近</div>',
    '          </div>',
    '          <div v-else class="muted" style="font-size:12px;margin-top:6px">置信度 {{ conf(row) }}%</div>',
    '          <div v-if="!hasSuggestion(row)" class="conf-bar"><i :style="{width: conf(row) + \'%\', background: conf(row)<40 ? \'#e5484d\' : \'#f5a623\'}"></i></div>',
    '          <el-tag v-if="row._corrected" size="small" type="success" effect="plain" style="margin-top:6px">已改判</el-tag>',
    '        </div>',
    '        <div>',
    '          <div class="row" style="gap:6px;flex-wrap:wrap;margin-top:6px">',
    '            <el-button size="small" type="success" :loading="busyIdx===row._index" :disabled="isExample" @click="correct(row, true, row.value)">中</el-button>',
    '            <el-button size="small" type="danger" plain :loading="busyIdx===row._index" :disabled="isExample" @click="correct(row, false, row.value)">没中</el-button>',
    '          </div>',
    '          <div class="row" style="gap:6px;margin-top:6px">',
    '            <span class="muted" style="font-size:12px">分值：</span>',
    '            <el-button size="small" text :disabled="isExample" @click="correct(row, true, 1)">1分</el-button>',
    '            <el-button size="small" text :disabled="isExample" @click="correct(row, true, 2)">2分</el-button>',
    '            <el-button size="small" text :disabled="isExample" @click="correct(row, true, 3)">3分</el-button>',
    '          </div>',
    '        </div>',
    '      </div>',
    '      <el-empty v-if="!list.length" :image-size="70" description="暂无待复核" />',
    '    </div>',
    '    <!-- ③ 改判记录：答辩时用来说明「写回口径」 -->',
    '    <div class="card" v-if="localLog.length">',
    '      <h3 class="card-title">改判记录 </h3>',
    '      <el-table :data="localLog" size="small" border>',
    '        <el-table-column prop="t" label="时刻" width="90" />',
    '        <el-table-column prop="player" label="球员" width="120" />',
    '        <el-table-column label="改判前" min-width="140">',
    '          <template #default="s">{{ resultLabel(s.row.before) }}<span v-if="shotValueLabel(s.row.before)"> {{ shotValueLabel(s.row.before) }}</span></template>',
    '        </el-table-column>',
    '        <el-table-column label="改判后" min-width="120">',
    '          <template #default="s">{{ resultLabel(s.row) }}<span v-if="shotValueLabel(s.row)"> {{ shotValueLabel(s.row) }}</span></template>',
    '        </el-table-column>',
    '        <el-table-column label="是否写回后端" width="130" align="center">',
    '          <template #default="s"><el-tag size="small" :type="s.row.persisted ? \'success\' : \'info\'">{{ s.row.persisted ? \'已写回\' : \'仅本地\' }}</el-tag></template>',
    '        </el-table-column>',
    '        <el-table-column label="后端返回摘要" min-width="220" show-overflow-tooltip>',
    '          <template #default="s"><span class="muted">{{ s.row.summary || \'（本地重算）\' }}</span></template>',
    '        </el-table-column>',
    '      </el-table>',
    '    </div>',
    '  </template>',
    '</div>'
  ].join('\n')
};
