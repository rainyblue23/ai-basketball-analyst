/* ==========================================================================
   app.js —— SPA 外壳：全局状态 + hash 路由 + Element Plus 中文初始化
   --------------------------------------------------------------------------
   全局状态（window.STATE，各页面通过 app.js 提供的全局 getter 读取）：
     backendOk  后端是否可用（决定「演示数据模式」标签）
     jobId      当前展示的比赛 job_id
     game       game.json          ← GET /api/games/{id}
     players    players.json       ← GET /api/games/{id}/players
     shotchart  shotchart.json     ← GET /api/games/{id}/shotchart
     report     {markdown, json}   ← GET /api/games/{id}/report
     highlights {clips, index_url} ← GET /api/games/{id}/highlights
   降级：探测不到后端就整体切到 ./demo/ 下的静态产物（见 api.js loadDemo）。
   ========================================================================== */
(function () {
  'use strict';

  // 全局数据状态：**这一份本身就是响应式的**（移植自队友 d0247ee）。
  // 为什么必须这样：以前 STATE 是裸对象、STORE = Vue.reactive(STATE) 是它的代理，
  // 于是"直接写 STATE.xxx"（app.js 内部、api.js 回调里）**不会触发重绘** ——
  // 表现就是"第一次打开战术/热区页看到的是上一场的旧数据或空状态，
  // 离开再点一次才对"（实测踩到）。现在两个名字指向同一个代理，
  // 从哪边写都会通知已挂载的页面。
  var STATE = Vue.reactive({
    backendOk: false,
    demoMode: true,
    jobId: '',
    game: null,
    players: [],
    shotchart: null,
    report: null,
    highlights: [],
    // 战术层（懒加载 —— 只有打开"战术分析"页才去拉，
    // 否则每次进总览页都要多下几百 KB 的逐帧数据）
    tactics: null,
    tacticsFrames: null,
    tacticsLoaded: false,
    tacticsError: '',
    charts: {},          // 页面里创建过的 ECharts 实例（切换页面时统一 resize）
    loading: false,
    notice: '',
    // 顶栏「当前任务」切换用：最近 20 条任务（bootstrap 里填），
    // 以及「这次为什么没有内容」的一句话（applyGame 里算，见 buildEmptyWhy）
    jobs: [],
    emptyWhy: ''
  });
  window.STATE = STATE;

  // 老的 STORE 名字保留（各页面组件都在用它）。**必须指向同一个代理**：
  // 两个名字若指向两份对象，页面读到的就不是同一份数据（上面那条 bug 的成因）。
  var STORE = STATE;
  window.STORE = STORE;

  // 菜单即路由表：group 决定在左侧栏归到哪一段（首页 / 分析流程 / 结果与产出）。
  // 用户反馈（2026-09-27）：顶栏原来又平铺了一遍同样的菜单，跟左侧栏重复 ——
  // 现在顶栏只留品牌与状态，导航统一走左侧栏，菜单只在这一处定义。
  var MENUS = [
    { key: 'home', icon: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m3 10 9-7 9 7v11h-6v-7H9v7H3z"/></svg>', title: '首页', group: 'home' },
    { key: 'examples', icon: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><rect x="3" y="5" width="18" height="15" rx="2"/><path d="m10 9 5 4-5 4z"/></svg>', title: '样例比赛', group: 'home' },
    { key: 'upload', icon: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6"/></svg>', title: '上传与分析', group: 'flow' },
    { key: 'overview', icon: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 20V10m8 10V4m8 16v-7M2 21h20"/></svg>', title: '比赛总览', group: 'flow' },
    { key: 'review', icon: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="3" width="16" height="18" rx="2"/><path d="m8 12 3 3 5-6"/></svg>', title: '人工复核', group: 'flow' },
    { key: 'stats', icon: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="9" cy="7" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 4a3 3 0 0 1 0 6m2 4a5 5 0 0 1 3 5v2"/></svg>', title: '球员/球队统计', group: 'output' },
    { key: 'shotchart', icon: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/></svg>', title: '投篮热区', group: 'output' },
    { key: 'tactics', icon: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="1"/><path d="M3 12h18m-12-9v4h6V3m-6 18v-4h6v4"/><circle cx="12" cy="12" r="3"/></svg>', title: '战术分析', group: 'output' },
    { key: 'highlights', icon: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="m10 8 6 4-6 4zM3 8h4m10 0h4"/></svg>', title: '高光集锦', group: 'output' },
    { key: 'report', icon: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 3h10l4 4v14H5zM14 3v5h5M8 12h8m-8 4h8"/></svg>', title: '导出/报告', group: 'output' }
    // 「训练标注」页已按用户要求下线（2026-10-05）：入口、页面脚本、首页卡片说明、
    // 「怎么用」文案一并移除；后端 /api/label/* 接口保留（命令行/脚本仍可用），
    // 页面文件备份在 _tmp/merge/backup/train.js.removed，需要时可原样恢复。
  ];
  // 首页要用这份表渲染模块入口卡片，所以显式挂到 window（首页脚本在 app.js 之前加载，
  // 因此必须在 computed 里**惰性**读取，不能在模块顶层读）
  window.MENUS = MENUS;

  // ------------------------------------------------------------------
  // 数据装载
  // ------------------------------------------------------------------
  /**
   * 装载某个 job 的全部产物。
   * 接口：GET /api/games/{id}、/players、/shotchart、/report、/highlights
   */
  function loadFromBackend(id) {
    var A = window.API;
    // players / shotchart / report / highlights 允许缺失（后端早期版本或 video 源可能没有），
    // 缺失时由 applyGame 用 game.timeline 现算补齐，保证页面仍然可用。
    return Promise.all([
      A.game(id),
      A.players(id).catch(function () { return []; }),
      A.shotchart(id).catch(function () { return null; }),
      A.report(id).catch(function () { return null; }),
      A.highlights(id).catch(function () { return null; })
    ]).then(function (r) {
      // jobId 必须在 applyGame **之前**落定：applyGame 末尾会用 jobId 生成
      // 「这次为什么是空的」那句话，顺序反了就会引用上一个任务。
      STORE.jobId = id;
      try { if (id.indexOf("example_") === 0) sessionStorage.setItem("aihoop_active_example", id); else sessionStorage.removeItem("aihoop_active_example"); } catch (_) {}
      applyGame(r[0], r[1], r[2], r[3], r[4]);
      STORE.demoMode = false;
      STORE.notice = id.indexOf('example_') === 0 ? '样例比赛 · 只读分析结果' : '';
    });
  }

  /**
   * 静态产物兜底：读 web/demo/{game,players,shotchart,report}.json + report.md。
   * （仓库默认不带这些产物；跑一次 `aihoop.cli demo` + `scripts\sync_demo.ps1`
   *   或 `scripts\run_demo.ps1` 就有了。）
   */
  function loadFromDemo() {
    var A = window.API;
    return A.loadDemo().then(function (d) {
      if (!d.game) {
        STATE.notice = '未找到静态产物（web/demo/game.json）。先在根目录跑一次：' +
          "python -m aihoop.cli demo --seed 7 --duration 600 --out out/demo " +
          '（或直接启动后端 127.0.0.1:8000，前端会自动连）。缺失：' +
          (d.missing || []).join(', ');
        STATE.jobId = '';
        STORE.emptyWhy = buildEmptyWhy();
        return;
      }
      STATE.demoMode = true;
      STATE.jobId = (d.game.meta && d.game.meta.job_id) || 'demo';
      applyGame(d.game, d.players || [], d.shotchart, {
        markdown: d.reportMd || '',
        json: d.report_json || null
      }, d.highlights);
      STATE.notice = '';
    });
  }

  /** 规范化并落到全局状态 */
  function applyGame(game, players, shotchart, report, highlights) {
    var D = window.D;
    STORE.game = D.normalizeGame(game || {});

    // 出手点：优先 shotchart.json，其次 players.shots，最后 game.timeline
    var pts = (shotchart && shotchart.all && shotchart.all.points) || [];
    if (!pts.length) pts = D.shotsFromPlayers(players);
    if (!pts.length) pts = D.shotsFromTimeline(STORE.game);
    // 补上 team 字段（shotchart 默认不含 team，用 player_id 反查）
    var teamOf = {};
    (players || []).forEach(function (p) { teamOf[p.player_id] = p.team; });
    (STORE.game.timeline || []).forEach(function (e) { if (e.player_id) teamOf[e.player_id] = e.team; });
    pts.forEach(function (p) {
      if (!p.team) p.team = teamOf[p.player_id] || '';
      if (!p.zone) p.zone = D.zoneOf(p.x, p.y);
      if (p.distance === undefined) p.distance = D.distanceToHoop(p.x, p.y);
    });

    STORE.players = D.normalizePlayers(players || []);
    var playerLabels = {};
    STORE.players.forEach(function (p) { playerLabels[p.player_id] = p; });
    pts.forEach(function(p){p.player_name=D.playerLabel(playerLabels[p.player_id]||{});});
    (STORE.game.timeline || []).forEach(function (e) {
      e.player = D.playerLabel(playerLabels[e.player_id] || { name:e.player, player_id:e.player_id });
    });
    STORE.shotchart = D.normalizeShotchart(shotchart || {});
    STORE.shotchart.all.points = pts;                 // 保证点集统一
    STORE.shotchart.all.zones = STORE.shotchart.all.zones.length
      ? STORE.shotchart.all.zones : D.aggregateZones(pts);
    if (!STORE.shotchart.all.grid.length) STORE.shotchart.all.grid = D.buildGrid(pts, 1);
    // 分球队分区（后端 by_team 可能缺失）
    ['home', 'away'].forEach(function (s) {
      if (!STORE.shotchart.zonesByTeam[s].length) {
        STORE.shotchart.zonesByTeam[s] = D.aggregateZones(
          pts.filter(function (p) { return p.team === s; }));
      }
    });

    STORE.report = report || null;

    var clips = (highlights && highlights.clips) || STORE.game.highlights || [];
    STORE.highlights = clips;
    STORE.highlightsMeta = highlights || null;

    // 注意必须写 **STORE**（Vue 的响应式代理），不能写裸 STATE：
    // 裸对象的赋值不会触发重新渲染，界面上就"什么都没变"（本轮实测踩到：
    // 提示条赋值成功但一直不显示）。
    STORE.emptyWhy = buildEmptyWhy();
  }
  STATE.applyGame = applyGame;

  /**
   * 这次分析为什么没有内容？
   *
   * 为什么要做这件事（实测踩到）：页面默认展示"最近一个 done 任务"，而用户最近那次
   * 跑的是 **8.1 秒** 的片段（0 次出手、0 名球员、没有标定）—— 六个产出页全是空的，
   * 页面上却写着"请先在上传页创建分析任务"，等于让用户去重复一件已经做过的事。
   * 结果就是"上传视频分析完，什么都看不到"（用户原话）。
   * 这里把 game.meta 里已有的客观事实拼成一句人话，页面上直接显示，不猜、不美化。
   */
  function buildEmptyWhy() {
    var g = STATE.game || {};
    var meta = g.meta || {};
    var jobId = STATE.jobId || '';
    // 有内容就别喊（演示数据本身有内容时更不该弹这条，否则是假警报）
    var hasContent = ((g.timeline || []).length > 0) ||
                     Number((g.score || {}).home || 0) + Number((g.score || {}).away || 0) > 0 ||
                     (STATE.players || []).length > 0;
    if (hasContent) return '';
    if (!jobId || jobId === 'demo') {
      return STATE.demoMode
        ? '当前显示的是演示数据，而这份演示数据也是空的（没读到 web/demo 下的产物）。跑一次分析后，这里会显示它的真实结果。'
        : '还没有选中任何分析任务：到「上传与分析」页跑一次，或在顶栏「当前任务」里挑一个。';
    }
    var dur = Number(g.duration || meta.duration || 0);
    var durationLabel = dur > 0 ? '（' + dur.toFixed(1) + ' 秒）' : '';
    return '当前任务' + durationLabel + '尚未生成投篮记录。可回看原视频或重新分析；没有记录不代表没有投篮。';
  }

  /** 统一入口：优先后端，失败自动降级到 demo。
   *
   *  去重（移植自队友 d0247ee）：根组件 mounted、上传页、自动重连都可能调它，
   *  并发跑两遍会互相覆盖选中任务 —— 只允许一份在飞。 */
  var bootstrapPromise = null;
  function bootstrap() {
    if (bootstrapPromise) return bootstrapPromise;
    STORE.loading = true;
    var run = window.API.probe().then(function (ok) {
      STORE.backendOk = ok;
      if (ok) {
        var activeExample = "";
        var requestedExample = typeof URLSearchParams === "function" ? new URLSearchParams(location.search || "").get("example") : null;
        try { activeExample = sessionStorage.getItem("aihoop_active_example") || ""; } catch (_) {}
        if (requestedExample && /^[a-z0-9_-]+$/.test(requestedExample)) activeExample = "example_" + requestedExample;
        if (/^example_[a-z0-9_-]+$/.test(activeExample)) return loadFromBackend(activeExample).catch(function () { try { sessionStorage.removeItem("aihoop_active_example"); } catch (_) {} throw new Error("样例暂时无法加载"); });
        // 后端可用：取最近任务里最新的 done 任务作为默认展示对象
        return window.API.listJobs().then(function (jobs) {
          var list = Array.isArray(jobs) ? jobs : (jobs && jobs.jobs) || [];
          STORE.jobs = list;             // 顶栏「当前任务」下拉用这一份
          STORE.jobs = list;             // 必须走响应式代理才会触发顶栏重绘
          var done = list.filter(function (j) { return j.status === 'done'; });
          var pick = done[0] || list[0];
          if (pick && pick.job_id) return loadFromBackend(pick.job_id);
          return loadFromDemo().then(function () {
            STORE.demoMode = true;   // 后端在但没有任务，仍展示演示数据
          });
        }).catch(function () { return loadFromDemo(); });
      }
      return loadFromDemo();
    }).catch(function (e) {
      STORE.backendOk = false;
      return loadFromDemo();
    });
    bootstrapPromise = run.then(function (value) {
      STORE.loading = false;
      bootstrapPromise = null;
      return value;
    }, function (error) {
      STORE.loading = false;
      bootstrapPromise = null;
      throw error;
    });
    return bootstrapPromise;
  }

  /**
   * 新建任务完成后切到该 job 的数据。
   * 上传页调用：POST /api/jobs -> watchJob -> 成功后 app.loadJob(id)
   */
  function loadJob(id) {
    STATE.tacticsLoaded = false;      // 换比赛了，战术数据要重新拉
    STATE.tactics = null;
    STATE.tacticsFrames = null;
    return loadFromBackend(id);
  }

  /**
   * 懒加载战术层数据。
   *
   * 为什么不跟其它产物一起在 bootstrap 里拉：tactics_frames.jsonl 是逐帧数据，
   * 一场 12 分钟的比赛就有 ~900 帧 × 10 名球员，比 game.json 大一个数量级。
   * 把它绑在总览页上会让"打开就慢"，而战术页并不是每次答辩都会点。
   *
   * 降级：后端没有战术产物（老任务/关闭了战术层）时，演示模式读
   * web/demo/tactics.json；真实模式下直接把 available=false 交给页面去提示。
   */
  function loadTactics(force) {
    // 子组件的 mounted 可能比根组件的 bootstrap 更早跑（直接打开 #/tactics 时就是这样）。
    // 这时 jobId 还没定下来，照旧逻辑会去拉"上一次/演示"的战术数据并缓存住，
    // 于是第一次进战术页看到的是错的那份 —— 先等 bootstrap 选完任务再拉（队友 d0247ee）。
    if (bootstrapPromise) {
      return bootstrapPromise.then(function () { return loadTactics(true); });
    }
    if (STATE.tacticsLoaded && !force) return Promise.resolve(STATE.tactics);
    var A = window.API;
    var requestedJobId = STATE.jobId;
    function fromDemo() {
      return Promise.all([A.demoTactics(), A.demoTacticsFrames()])
        .then(function (r) {
          STATE.tactics = r[0] || {
            available: false,
            reason: '演示数据里没有 tactics.json —— 请先跑 scripts/sync_demo.ps1 同步一次'
          };
          STATE.tacticsFrames = r[1] || { available: false, frames: [] };
        });
    }
    var p;
    if (STATE.backendOk && STATE.jobId) {
      p = Promise.all([
        A.tactics(STATE.jobId).catch(function () { return null; }),
        A.tacticsFrames(STATE.jobId).catch(function () { return null; })
      ]).then(function (r) {
        // 用户可能在两个请求还在飞的时候换了任务 —— 绝不能把旧任务的结果
        // 当成"当前这场"的战术数据发布出去（队友 d0247ee）。
        if (requestedJobId !== STATE.jobId) return loadTactics(true);
        STATE.tactics = r[0] || { available: false, reason: '后端没有返回战术数据' };
        STATE.tacticsFrames = r[1] || { available: false, frames: [] };
      });
    } else {
      p = fromDemo();
    }
    return p.then(function () {
      // 这里**故意不做**"后端没有战术产物就退回演示数据"的兜底：
      // 那样会把另一场比赛的战术图当成当前这场显示出来，属于"看起来像真的"的
      // 假数据 —— 比空状态危险得多。没有就明确说没有，并告诉用户怎么拿到。
      STATE.tacticsLoaded = true;
    }).catch(function (e) {
      STATE.tacticsError = String((e && e.message) || e);
      STATE.tacticsLoaded = true;
    });
  }

  // ------------------------------------------------------------------
  // Vue 根组件
  // ------------------------------------------------------------------
  var app = Vue.createApp({
    data: function () {
      return {
        state: STATE,
        menus: MENUS,
        // 打开网页先落在「首页」：以前默认落在比赛总览，没有任务时是一大片空白，
        // 用户不知道该点哪里（反馈 2026-09-27）
        route: 'home',
        api: window.API,
        isFileProtocol: window.API.isFileProtocol,
        currentPage: null,
        job: window.makeJob(),
        ticking: null,
        reconnectTimer: null,
        // 深色/浅色：初值直接读 <html data-theme>（<head> 里的内联脚本已按
        // 「URL 参数 > localStorage > 默认深色」定好，避免首屏闪一下）
        lightTheme: document.documentElement.getAttribute('data-theme') === 'light'
      };
    },
    computed: {
      game: function () { return this.state.game; },
      teamName: function () {
        var self = this;
        return function (side) { return window.D.teamName(self.state.game, side); };
      }
    },
    methods: {
      /** 菜单点击时同步切页，不等浏览器异步派发 hashchange（队友 d0247ee）。
       *  为什么：hashchange 是异步的，点完菜单到页面真正换掉之间有一段空档，
       *  首次进入战术页时子组件的 mounted 会赶在这之前跑 —— 就是"第一次进去是空的，
       *  退出去再点一次才对"的成因之一。 */
      navigate: function (key) {
        if (!window.PAGES[key]) key = 'home';
        this.route = key;
        this.currentPage = window.PAGES[key];
        var hash = '#/' + key;
        if (location.hash !== hash) location.hash = hash;
      },
      /** 从 location.hash 解析当前页（#/shotchart -> window.PAGES['shotchart']） */
      syncRoute: function () {
        var key = (location.hash || '').replace(/^#\/?/, '').split('?')[0] || 'home';
        if (!window.PAGES[key]) key = 'home';
        this.route = key;
        this.currentPage = window.PAGES[key];
      },
      probe: function () {
        var self = this;
        window.API.probe().then(function (ok) {
          self.state.backendOk = ok;
          if (ok) {
            self.stopReconnect();
            self.$message.success('后端已连接：' + window.API.base);
            bootstrap();
          } else {
            self.$message.warning('仍未探测到后端，继续使用演示数据模式');
          }
        });
      },
      /** 顶栏任务快照：有活动任务时 1.5s 轮询一次（WS 由上传页负责） */
      trackJob: function () {
        var self = this;
        if (self.ticking) return;
        self.ticking = setInterval(function () {
          if (!self.job.job_id) return;
          window.API.getJob(self.job.job_id).then(function (j) {
            self.job = j;
            if (j.status === 'done' || j.status === 'error') {
              clearInterval(self.ticking); self.ticking = null;
            }
          }).catch(function () {});
        }, 3000);
      },
      /**
       * 后端起来之前打开的页面**自动重连** —— 不用再让用户自己点「重新探测」。
       *
       * 为什么必须有：`backendOk` 只在页面加载时探测一次（见 bootstrap），之后不会重试。
       * 于是"先开页面、后起后端"（或者后端正在自动重启的那两三秒）就会一直停在
       * "未检测到后端"：上传、标篮筐、标球场按钮全是灰的，用户以为界面坏了 ——
       * 实测反复踩到。这里每 5 秒探一次，连上就自动切回真实数据。
       */
      autoReconnect: function () {
        var self = this;
        if (self.reconnectTimer) return;
        var tries = 0;
        self.reconnectTimer = setInterval(function () {
          if (self.state.backendOk) { self.stopReconnect(); return; }
          if (++tries > 120) {                 // 约 10 分钟还没等到 → 停手，按钮仍在
            self.stopReconnect();
            self.$message.warning('仍未探测到后端：启动后端后点右上角「重新探测」');
            return;
          }
          window.API.probe().then(function (ok) {
            if (!ok) return;
            self.stopReconnect();
            self.state.backendOk = true;
            self.$message.success('后端已连接：' + window.API.base);
            bootstrap();
          }).catch(function () { /* 后端还没起来，下一轮继续 */ });
        }, 5000);
      },
      stopReconnect: function () {
        if (this.reconnectTimer) {
          clearInterval(this.reconnectTimer);
          this.reconnectTimer = null;
        }
      },
      /** 供上传页调用：登记正在跑的任务 */
      registerJob: function (job) { this.job = job; this.trackJob(); },

      /**
       * 深色 / 浅色切换。
       * 只改 <html data-theme>：配色全在 styles.css 里由变量定义，
       * 图表（ECharts 主题在 init 时定死）和球场 SVG 靠 'aihoop-theme' 事件跟着重建。
       */
      applyTheme: function (isLight) {
        var theme = isLight ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', theme);
        try { localStorage.setItem('aihoop-theme', theme); } catch (e) { /* 隐私模式下写不了，忽略 */ }
        window.dispatchEvent(new CustomEvent('aihoop-theme', { detail: theme }));
      },

      /**
       * 顶栏「当前任务」里点一条 → 切换看哪个任务的结果。
       * 为什么需要它：刷新后 SPA 只会自动挑"最新的 done 任务"，那次分析如果是空的
       * （实测：8 秒片段、0 次出手），六个产出页全是空的，用户以为功能坏了，
       * 而界面上**没有任何入口**能换到别的任务上。
       */
      switchJob: function (id) {
        var self = this;
        if (!id || id === self.state.jobId) return;
        window.APP_LOAD_JOB(id).then(function () {
          self.$message.success('已切换到任务 ' + String(id).slice(0, 8));
        }).catch(function (e) {
          self.$message.error('切换失败：' + (e && e.message ? e.message : e));
        });
      },
      /** 任务列表每行显示什么：job_id + 出手次数（从 summary 里取，取不到就写状态） */
      jobLabel: function (j) {
        var s = String((j && j.summary) || '');
        var m = s.match(/出手\s*(\d+)/);
        if (m) return '出手 ' + m[1] + ' 次';
        var st = String((j && j.status) || '');
        return st === 'done' ? '无出手记录' : (st || '—');
      }
    },
    mounted: function () {
      var self = this;
      window.addEventListener('hashchange', function () { self.syncRoute(); });
      this.syncRoute();
      bootstrap();
      this.autoReconnect();      // 后端晚起来也能自动连上（见该方法注释）
      // 暴露给页面组件用（避免每个页面重复挂 window）
      window.APP = this;
    }
  });

  app.use(ElementPlus, { locale: ElementPlusLocaleZhCn });
  app.component('calibration-gaps', window.COMPONENTS['calibration-gaps']);
  app.component('replay-tools', window.COMPONENTS['replay-tools']);
  app.component('detection-overlay', window.COMPONENTS['detection-overlay']);
  app.component('copy-note', window.COMPONENTS['copy-note']);
  app.component('page-help', window.COMPONENTS['page-help']);
  app.component('echarts-box', window.COMPONENTS['echarts-box']);
  app.component('court-view', window.COMPONENTS['court-view']);
  app.component('stat-compare', window.COMPONENTS['stat-compare']);
  app.component('big-scoreboard', window.COMPONENTS['big-scoreboard']);

  // ⚠️ 顺序不能反：页面子组件在 app.mount() 的**首次渲染**里就会跑 mounted，
  // 而它们要用 APP_WAIT_READY / APP_TACTICS 等入口。先挂 window 再 mount，
  // 否则直接打开 #/tactics 时子组件拿不到入口 —— 第一次进去无声失败，
  // 退出去再点一次才加载（队友 d0247ee 实测）。
  window.APP_BOOTSTRAP = bootstrap;
  window.APP_LOAD_JOB = loadJob;
  window.APP_TACTICS = loadTactics;
  window.APP_WAIT_READY = function () {
    return bootstrapPromise || Promise.resolve();
  };
  app.mount('#app');
})();
