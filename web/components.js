/* ==========================================================================
   components.js —— 跨页面复用的 Vue 组件
   --------------------------------------------------------------------------
   1) echarts-box   ECharts 统一封装（自适应 + option 热更新 + 统一浅色主题）
   2) court-view    标准半场视图容器（court.js 生成 SVG + 叠加层，半场/全场切换）
   3) stat-compare  双方指标对比条（命中率 / 三分率 / 罚球…）
   4) big-scoreboard 大比分牌 + 分节比分表
   ========================================================================== */
(function () {
  'use strict';

  /**
   * 读 CSS 变量。浅色/深色模式只换 CSS 变量值，所以图表、球场 SVG 也一律读变量，
   * 不再写死颜色 —— 否则切到浅色会出现"灰字看不见 / 深色球场"的问题。
   */
  window.AIHOOP_CSSVAR = window.AIHOOP_CSSVAR || function (name, fallback) {
    try {
      var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      return v || fallback;
    } catch (e) { return fallback; }
  };
  /** ECharts 内置主题：深色用 'dark'，浅色用默认（null = 不指定） */
  window.AIHOOP_ECHARTS_THEME = window.AIHOOP_ECHARTS_THEME || function () {
    return document.documentElement.getAttribute('data-theme') === 'light' ? null : 'dark';
  };

  // ECharts 统一主题：与 styles.css 的深顶栏 / 浅内容区一致
  // 调色板**每次现读**：切到浅色后 --chart-c4/5/6 会变，写死一次就会用到旧颜色。
  function palette() {
    return ['#3D8BFF', '#FF7A33', '#22C55E',
      window.AIHOOP_CSSVAR('--chart-c4', '#B6C5D8'),
      window.AIHOOP_CSSVAR('--chart-c5', '#7F9FBF'),
      window.AIHOOP_CSSVAR('--chart-c6', '#5BC8DF')];
  }

  window.COMPONENTS = {};
  window.COMPONENTS['calibration-gaps'] = {
    props: ['game'],
    computed: { coverage: function(){ return (((this.game||{}).meta||{}).sliding_calibration||{}).coverage; } },
    template: '<div v-if="coverage && coverage.paused_frames" class="hint">坐标暂停 {{ coverage.paused_frames }} 帧 <copy-note label="查看时段"><p>标定分析范围内暂停 {{ coverage.paused_frames }}/{{ coverage.analyzed_frames }} 帧（{{ (100*coverage.paused_fraction).toFixed(1) }}%），不代表没检测到球员。</p><p v-for="(r,i) in coverage.ranges_s" :key="i">{{ r[0].toFixed(2) }}–{{ r[1].toFixed(2) }} 秒：定位依据不连续，暂停输出坐标（不含结束时刻）。</p></copy-note></div>'
  };
  window.COMPONENTS['copy-note'] = {
    props: {label: {type:String, default:'说明'}},
    template: '<el-popover trigger="click" placement="bottom-start" :width="360" popper-class="copy-note-panel"><template #reference><button type="button" class="copy-note-trigger" :aria-label="label + \'，查看说明\'">{{ label }}</button></template><div class="copy-note-body"><slot></slot></div></el-popover>'
  };
  window.COMPONENTS['page-help'] = {
    props: ['page'],
    computed: {steps: function(){return {
      home:'上传比赛视频，分析后先看总览，再逐条复核待确认出手。',
      upload:'选择视频 → 设置分析参数 → 开始分析。球场标定可选，需要位置分析时再标。',
      overview:'拖动原视频回看；选择事件定位画面，再到人工复核确认结果。',
      review:'先核对画面，再确认结果与分值；系统建议确认前不计分。',
      report:'先检查待复核记录，再下载战报或数据文件。',
      highlights:'选择事件并回看；导出片段前核对起止时间。',
      shotchart:'选择球队或球员，切换散点与热区；位置不可用的出手不绘图。',
      tactics:'查看球员位置、传球与阵型；自动坐标未校验时只作参考。',
      stats:'切换球队，按列排序查看球员统计。'
      // train: 已下线（用户要求删除「训练标注」模块），对应文案一并移除
    }[this.page] || '先查看结果，再核对原视频。';}},
    template: '<div class="page-help"><el-popover trigger="click" placement="bottom-end" :width="360" popper-class="copy-note-panel"><template #reference><button type="button" class="copy-note-trigger">怎么用</button></template><p class="copy-note-body">{{ steps }}</p></el-popover><el-popover trigger="click" placement="bottom-end" :width="400" popper-class="copy-note-panel"><template #reference><button type="button" class="copy-note-trigger">方法与口径</button></template><div class="copy-note-body"><p><b>仅提示、不计分：</b>轨迹候选与未确认建议不自动加入出手和命中统计；matched只代表时间接近，不证明同一次出手。</p><p><b>投篮结果：</b>只显示中与没中；证据不足的时间点单独供回看，不当作投篮结论。</p><p><b>球检测观测率：</b>这是模型检测到球的比例，不是录像里有没有球的判定。</p><p><b>估计值、未校验：</b>分值和自动位置需复核。未标定或位置未知时不据占位坐标生成热区；未确认结果不进投篮图。</p><p><b>证据跨段、切镜截断、球框可疑：</b>这些提示说明证据限制，不是投篮与否的结论；不跨切镜自动合链。</p></div></el-popover></div>'
  };


  /** ---------------- ECharts 容器 ---------------- */
  window.COMPONENTS['echarts-box'] = {
    name: 'echarts-box',
    props: {
      option: { type: Object, required: true },
      height: { type: String, default: '320px' }
    },
    template: '<div ref="el" :style="{width:\'100%\',height:height}"></div>',
    data: function () { return { chart: null, ro: null }; },
    mounted: function () {
      this.setupChart();
      // 切换深/浅色时要**重建**图表：ECharts 的主题在 init 时就定死了，
      // 只 setOption 换不掉内置主题的配色。
      window.addEventListener('aihoop-theme', this.onThemeChange);
    },
    watch: {
      option: {
        deep: true,
        handler: function () {
          var self = this;
          if (!self.chart) return;
          // 切换任务时坐标轴与 series 会同时变化。ECharts 6 即使用 notMerge，
          // 仍可能在同一渲染帧里让旧 series 访问已替换的坐标轴（getAxis/type 异常）。
          // 下一次 Vue 更新完成后先 clear，再提交一份完整 option。
          this.$nextTick(function () {
            if (!self.chart || !self.$refs.el || !self.$refs.el.isConnected) return;
            self.chart.clear();
            self.chart.setOption(self.buildOption(), { notMerge: true, lazyUpdate: false });
          });
        }
      }
    },
    beforeUnmount: function () {
      window.removeEventListener('aihoop-theme', this.onThemeChange);
      if (this.ro) this.ro.disconnect();
      if (this.chart) { this.chart.dispose(); this.chart = null; }
    },
    methods: {
      setupChart: function () {
        if (!window.echarts) {
          console.warn('[echarts-box] ECharts 未加载，请检查 CDN');
          return;
        }
        // ECharts 实例含大量内部对象，交给 Vue 深层响应式代理后会把内部数组变成
        // Proxy；ECharts 6 渲染坐标轴时会因此出现 getAxis/type 异常。
        this.chart = Vue.markRaw(window.echarts.init(
          this.$refs.el, window.AIHOOP_ECHARTS_THEME(), { renderer: 'canvas' }));
        var created = this.chart;
        var self = this;
        // mounted 时父页面的 game 计算属性仍可能处在同一轮刷新中。延后一帧，
        // 避免 ECharts 在坐标轴 option 尚未稳定时开始 series 渲染。
        this.$nextTick(function () {
          requestAnimationFrame(function () {
            if (self.chart !== created || !self.$refs.el || !self.$refs.el.isConnected) return;
            created.setOption(self.buildOption(), { notMerge: true, lazyUpdate: false });
          });
        });
        if (window.ResizeObserver && !this.ro) {
          this.ro = new ResizeObserver(function () { if (self.chart) self.chart.resize(); });
          this.ro.observe(this.$refs.el);
        }
      },
      onThemeChange: function () {
        if (this.chart) { this.chart.dispose(); this.chart = null; }
        this.setupChart();
      },
      buildOption: function () {
        var o = JSON.parse(JSON.stringify(this.option || {}));
        o.color = o.color || palette();
        o.backgroundColor = 'transparent';
        o.textStyle = Object.assign({ color: window.AIHOOP_CSSVAR('--chart-text', '#9DAEC2'), fontFamily: 'PingFang SC, Microsoft YaHei, sans-serif', fontSize: 12 }, o.textStyle || {});
        if (!o.grid && o.series) {
          o.grid = { left: 46, right: 20, top: 34, bottom: 34, containLabel: true };
        }
        if (o.tooltip === undefined && o.series) {
          o.tooltip = { trigger: 'axis', axisPointer: { type: 'cross', label: { backgroundColor: window.AIHOOP_CSSVAR('--chart-tip-bg', '#1f2d3d') } } };
        }
        if (!o.legend && (o.series || []).length > 1) {
          o.legend = { top: 0, right: 8, icon: 'roundRect', itemWidth: 10, itemHeight: 10 };
        }
        (o.series || []).forEach(function(series) {
          if (series.label) series.label = Object.assign({},series.label,{color:window.AIHOOP_CSSVAR('--chart-label','#EAF0F7')});
        });
        ['xAxis','yAxis'].forEach(function(key) {
          if (!o[key]) return;
          var axes = Array.isArray(o[key]) ? o[key] : [o[key]];
          axes.forEach(function(axis) {
            axis.axisLabel = Object.assign({}, axis.axisLabel || {}, {color:'#9DAEC2'});
            axis.nameTextStyle = Object.assign({}, axis.nameTextStyle || {}, {color:'#9DAEC2'});
            axis.splitLine = Object.assign({}, axis.splitLine || {}, {lineStyle:{color:window.AIHOOP_CSSVAR('--chart-split','#2B3748')}});
          });
        });
        if (o.tooltip && typeof o.tooltip === 'object') {
          o.tooltip.backgroundColor = window.AIHOOP_CSSVAR('--chart-tip-bg', '#1A2330');
          o.tooltip.borderColor = window.AIHOOP_CSSVAR('--chart-tip-border', '#43536A');
          o.tooltip.textStyle = Object.assign({}, o.tooltip.textStyle || {}, {color: window.AIHOOP_CSSVAR('--chart-label', '#EAF0F7')});
        }
        return o;
      },
      resize: function () { if (this.chart) this.chart.resize(); }
    }
  };

  /** ---------------- 标准半场容器 ----------------
   * props.points  —— 出手点数组（shotchart.all.points 的口径）
   * props.zones   —— 分区聚合数组
   * props.grid    —— 网格热力 grid[iy][ix]
   * props.layer   —— 'shots' | 'zones' | 'grid' | 'none'
   */
  window.COMPONENTS['court-view'] = {
    name: 'court-view',
    props: {
      view: { type: String, default: 'half' },
      layer: { type: String, default: 'shots' },
      points: { type: Array, default: function () { return []; } },
      zones: { type: Array, default: function () { return []; } },
      grid: { type: Array, default: function () { return []; } },
      bin: { type: Number, default: 1 },
      metric: { type: String, default: 'pct' },
      dotR: { type: Number, default: 0.2 },
      useHeat: { type: Boolean, default: false }
    },
    template:
      '<div class="court-wrap">' +
      '  <div v-html="courtHTML"></div>' +
      '  <div v-if="layerHTML" v-html="layerHTML" style="position:absolute;inset:0"></div>' +
      '</div>',
    computed: {
      courtHTML: function () { return window.Court.courtSVG({ view: this.view }); },
      layerHTML: function () {
        var C = window.Court;
        if (this.layer === 'zones') return C.zoneLayer(this.zones, {});
        if (this.layer === 'grid') return C.gridLayer(this.grid, { bin: this.bin, metric: this.metric });
        if (this.layer === 'shots') {
          return C.shotLayer(this.points, { view: this.view, dotR: this.dotR, useHeat: this.useHeat });
        }
        return '';
      }
    }
  };

  /** ---------------- 双方指标对比 ---------------- */
  window.COMPONENTS['stat-compare'] = {
    name: 'stat-compare',
    props: {
      label: String,
      home: { type: Number, default: 0 },
      away: { type: Number, default: 0 },
      isPct: { type: Boolean, default: false },
      homeName: String,
      awayName: String
    },
    template:
      '<div style="margin-bottom:14px">' +
      '  <div class="row" style="justify-content:space-between;font-size:12.5px">' +
      '    <span><b style="color:var(--home)">{{ fmt(home) }}</b> <span class="muted">{{ homeName }}</span></span>' +
      '    <span class="muted">{{ label }}</span>' +
      '    <span><span class="muted">{{ awayName }}</span> <b style="color:var(--away)">{{ fmt(away) }}</b></span>' +
      '  </div>' +
      '  <div class="pctbar" style="margin-top:6px">' +
      '    <i class="h" :style="{width: hw + \'%\'}"></i>' +
      '    <i class="a" :style="{width: aw + \'%\'}"></i>' +
      '  </div>' +
      '</div>',
    computed: {
      total: function () { return Math.max(1e-6, this.home + this.away); },
      hw: function () { return (this.home / this.total * 100).toFixed(1); },
      aw: function () { return (this.away / this.total * 100).toFixed(1); }
    },
    methods: {
      fmt: function (v) { return this.isPct ? window.D.pctSmart(v) : window.D.num(v); }
    }
  };

  /** ---------------- 大比分牌 + 分节比分表 ---------------- */
  window.COMPONENTS['big-scoreboard'] = {
    name: 'big-scoreboard',
    props: { game: { type: Object, required: true } },
    template:
      '<div>' +
      '  <div class="scoreboard">' +
      '    <div class="scoreboard-share" :class="{empty: scoreSum === 0}" aria-hidden="true"><i class="h" :style="{width: homeShare + \'%\'}"></i><i class="a" :style="{width: awayShare + \'%\'}"></i></div>' +
      '    <div class="team home">' +
      '      <div class="nm">{{ name("home") }}</div>' +
      '      <div class="pts">{{ displayScore.home }}</div>' +
      '      <div class="meta">已判定投篮 {{ st("home").fgm }}/{{ st("home").fga }} · 待确认 {{ st("home").unknown || 0 }}<br>已判定记录命中率 {{ pct(st("home").fg_pct) }}（非全部出手）<br>' +
      '        三分 {{ st("home").tpm }}/{{ st("home").tpa }} · 罚球 {{ st("home").ftm }}/{{ st("home").fta }}</div>' +
      '    </div>' +
      '    <div class="mid">' +
      '      <div class="vs">{{ scoreLabel }}</div>' +
      '      <div class="win">{{ winnerText }}</div>' +
      '      <div class="vs" style="letter-spacing:0">{{ periods }} 节 · {{ mmss(game.duration) }}</div>' +
      '      <div v-if="courtMode && hasCarry" class="vs" style="letter-spacing:0;margin-top:8px;font-size:12px;color:#8a93a4">' +
      '        比分牌读数 {{ game.carry_in.home }} : {{ game.carry_in.away }}（仅供参考，不计入本片段得分）' +
      '      </div>' +
      '      <div v-if="!courtMode && hasCarry" class="vs" style="letter-spacing:0;margin-top:8px;font-size:12px;color:#8a93a4">' +
      '        比分牌带入 {{ game.carry_in.home }} : {{ game.carry_in.away }}<br>' +
      '        当前大比分 {{ totalScore.home }} : {{ totalScore.away }}<br>' +
      '        {{ currentLeadText }}' +
      '      </div>' +
      '    </div>' +
      '    <div class="team away">' +
      '      <div class="nm">{{ name("away") }}</div>' +
      '      <div class="pts">{{ displayScore.away }}</div>' +
      '      <div class="meta">已判定投篮 {{ st("away").fgm }}/{{ st("away").fga }} · 待确认 {{ st("away").unknown || 0 }}<br>已判定记录命中率 {{ pct(st("away").fg_pct) }}（非全部出手）<br>' +
      '        三分 {{ st("away").tpm }}/{{ st("away").tpa }} · 罚球 {{ st("away").ftm }}/{{ st("away").fta }}</div>' +
      '    </div>' +
      '  </div>' +
      '  <el-alert v-if="hasCarry" type="info" :closable="false" show-icon style="margin-top:10px"' +
      '    :title="carryExplain" />' +
      '  <el-table :data="quarterRows" size="small" style="margin-top:12px" border>' +
      '    <el-table-column prop="label" label="节次" width="110" />' +
      '    <el-table-column :label="name(\'home\')" align="center">' +
      '      <template #default="s"><span :style="{fontWeight: s.row.home>=s.row.away?700:400, color:\'var(--home)\'}">{{ s.row.home }}</span></template>' +
      '    </el-table-column>' +
      '    <el-table-column :label="name(\'away\')" align="center">' +
      '      <template #default="s"><span :style="{fontWeight: s.row.away>=s.row.home?700:400, color:\'var(--away)\'}">{{ s.row.away }}</span></template>' +
      '    </el-table-column>' +
      '    <el-table-column label="本节分差" align="center" width="110">' +
      '      <template #default="s">{{ s.row.home - s.row.away > 0 ? "+" : "" }}{{ s.row.home - s.row.away }}</template>' +
      '    </el-table-column>' +
      '  </el-table>' +
      '</div>',
    computed: {
      scoreSum: function () { return Math.max(0,Number(this.displayScore.home)||0) + Math.max(0,Number(this.displayScore.away)||0); },
      homeShare: function () { return this.scoreSum ? Math.max(0,Number(this.displayScore.home)||0) / this.scoreSum * 100 : 0; },
      awayShare: function () { return this.scoreSum ? 100 - this.homeShare : 0; },
      scorePolicy: function () {
        return String(this.game.score_policy || 'scoreboard').toLowerCase();
      },
      courtMode: function () {
        return ['court', 'visual', 'auto'].indexOf(this.scorePolicy) >= 0;
      },
      hasCarry: function () {
        var ci = this.game.carry_in || {};
        return !!(ci.home || ci.away);
      },
      totalScore: function () {
        return this.game.score || { home: 0, away: 0 };
      },
      clipScore: function () {
        if (this.game.clip_score) return this.game.clip_score;
        var ci = this.game.carry_in || { home: 0, away: 0 };
        return {
          home: (this.game.score.home || 0) - (ci.home || 0),
          away: (this.game.score.away || 0) - (ci.away || 0)
        };
      },
      displayScore: function () {
        return (this.courtMode || this.hasCarry) ? this.clipScore : this.totalScore;
      },
      scoreLabel: function () {
        return (this.courtMode || this.hasCarry) ? '本片段得分' : 'FINAL';
      },
      periods: function () { return this.game.periods || 4; },
      winnerText: function () {
        var h = this.displayScore.home, a = this.displayScore.away;
        if (h === a) return this.hasCarry ? '本片段暂无得分' : '战平';
        var leader = h > a ? this.name('home') : this.name('away');
        return leader + (this.hasCarry ? ' 本片段领先 ' : ' 胜 ') + Math.abs(h - a) + ' 分';
      },
      currentLeadText: function () {
        var h = this.totalScore.home, a = this.totalScore.away;
        if (h === a) return '比赛当前战平';
        var leader = h > a ? this.name('home') : this.name('away');
        return '比赛当前：' + leader + ' 领先 ' + Math.abs(h - a) + ' 分';
      },
      carryExplain: function () {
        var ci = this.game.carry_in || { home: 0, away: 0 };
        if (this.courtMode) {
          return '上方大字是「本片段得分」，按场上检测到的进球计分；比分牌读数 '
            + ci.home + ' : ' + ci.away + ' 仅供参考，不计入本片段得分。';
        }
        return '上方大字是「本片段得分」；' + ci.home + ' : ' + ci.away +
          ' 是比分牌带入的比赛当前大比分，不是这 ' + this.mmss(this.game.duration) +
          ' 得的。下方表格里「本片段」行才是这段视频真正产生的得分。';
      },
      quarterRows: function () {
        var rows = (this.game.quarter_scores || []).map(function (q) {
          return { label: '第' + q.period + '节', home: q.home, away: q.away };
        });
        if (this.hasCarry && !this.courtMode) {
          rows.push({ label: '本片段', home: this.clipScore.home, away: this.clipScore.away });
        }
        rows.push({
          label: this.courtMode ? '本片段总计' : (this.hasCarry ? '当前大比分' : '总计'),
          home: this.totalScore.home, away: this.totalScore.away
        });
        return rows;
      }
    },
    methods: {
      name: function (s) { return window.D.teamName(this.game, s); },
      st: function (s) { return (this.game.teams[s] || {}).stats || {}; },
      pct: function (v) { return window.D.pctSmart(v); },
      mmss: function (t) { return window.D.mmss(t); }
    }
  };

  /** ---------------- 小工具：把状态轮询/WS 逻辑封装起来 ---------------- */
  window.makeJob = function () {
    return {
      job_id: '', status: '', progress: 0, message: '', error: null,
      out_dir: '', summary: ''
    };
  };
})();
