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
      hoopDragStart: null,    // 按下时的归一化坐标；拖动直接画篮筐框
      hoopDragCurrent: null,
      hoopSuppressClick: false,
      markSaving: false,
      savedMarks: null,       // 该视频已保存的标点
      hoopPanels: { left: {at:1, image:'', box:null, loading:false, version:0}, right: {at:1, image:'', box:null, loading:false, version:0} },
      hoopPanelDrag: null,
      hoopSession: 0,
      hoopSide: 'left',       // 当前框的是左半场还是右半场篮筐
      // ---- 标球场：点场地特征点解标定（用户建议：不一定要标篮筐）----
      markKind: 'hoop',       // hoop | court
      courtItems: [],         // [{name,label,hint,dst}] 当前这一份清单里的特征点
      courtStandard: 'fiba',
      courtDraftAvailable: false,
      // 每幅画面都明确归属 A 端或 B 端；left/right 仅作为旧坐标键兼容。
      // 为什么不让工具自己认：试过用自动标定 + 罚球区可见面积投票，投影会退化、
      // 面积算成 0，不可靠；而选一次只影响**点名表显示哪一份**，代价极小、结果确定。
      // 默认全场（队友 d821ab4 的主流程）：同一个物理地标在两幅画面里叫**同一个名字**
      // （A端底线左角就是一个点），各自解算完再合并 —— 半场清单保留作临时筛选。
      courtSide: 'full',      // full = 全场 A端/B端 | right = A端 | left = B端
      // ⚠️ 哪一套点对应哪一侧，必须按**工具内部的坐标约定**来，不能凭直觉：
      //   A端 = y ∈ [0, 14]（底线在 y=+14），即 **_far 那一套**；
      //   B端 = y ∈ [-14, 0]（底线在 y=-14），也就是 **_near 那一套**。
      //   写反了不会报错，只会把球场整体平移 28m（两分变三分、热区整片错位）。
      courtSideNames: {
        // ⚠️ 这三份清单里**都没有「篮筐中心」**（曾经有，已移除）。
        // 篮圈离地 3.05m，而单应矩阵只能映射地面 —— 把篮筐当球场地点标进去
        // 会把整份标定拉偏（实测去掉它：两段误差 1.00m→0.03m、2.61m→0.18m）。
        // 篮筐请用「在画面上标篮筐」，那条路直接存画面坐标，不走单应矩阵。
        left: [
          { name: 'corner_near_left', label: 'B端底线左角' },
          { name: 'corner_near_right', label: 'B端底线右角' },
          { name: 'paint_base_near_left', label: 'B端禁区底线左角' },
          { name: 'paint_base_near_right', label: 'B端禁区底线右角' },
          { name: 'lane_near_left', label: 'B端罚球区左角' },
          { name: 'lane_near_right', label: 'B端罚球区右角' },
          { name: 'ft_near', label: 'B端罚球线中点' },
          { name: 'arc_near', label: 'B端三分弧顶' }
        ],
        right: [
          // “左/右”按站在该端底线后、朝场内看的视角定义。A/B朝向相反，
          // A端本地左/右对应全场 x 的正负与 B端相反；这里映射回标准地标名。
          { name: 'corner_far_right', label: 'A端底线左角' },
          { name: 'corner_far_left', label: 'A端底线右角' },
          { name: 'paint_base_far_right', label: 'A端禁区底线左角' },
          { name: 'paint_base_far_left', label: 'A端禁区底线右角' },
          { name: 'lane_far_right', label: 'A端罚球区左角' },
          { name: 'lane_far_left', label: 'A端罚球区右角' },
          { name: 'ft_far', label: 'A端罚球线中点' },
          { name: 'arc_far', label: 'A端三分弧顶' }
        ],
        // 全场 15 个地面地标（A端 = y>0 那一端，B端 = y<0）。带 dst 球场坐标（米）：
        // 解算后用它反投影，就能算出"这个点在你这两幅画面里根本看不见"（见 offFrameNames）。
        full: [
          { name: 'paint_base_far_right', label: 'A端禁区底线左角', dst: [2.45,14], hint: '禁区左侧长边与底线交点，不是球场四角' },
          { name: 'paint_base_far_left', label: 'A端禁区底线右角', dst: [-2.45,14], hint: '禁区右侧长边与底线交点，不是球场四角' },
          { name: 'paint_base_near_left', label: 'B端禁区底线左角', dst: [-2.45,-14], hint: '禁区左侧长边与底线交点，不是球场四角' },
          { name: 'paint_base_near_right', label: 'B端禁区底线右角', dst: [2.45,-14], hint: '禁区右侧长边与底线交点，不是球场四角' },
          { name: 'corner_far_left', label: 'A端底线右角', dst: [-7.5, 14.0], hint: '站在A端底线后朝场内看，底线与右边线交点' },
          { name: 'corner_far_right', label: 'A端底线左角', dst: [7.5, 14.0], hint: '站在A端底线后朝场内看，底线与左边线交点' },
          // ⚠️ 「A端篮筐中心」**已从这里移除**：篮圈离地 3.05m，不在球场地面上，
          // 而单应矩阵只能映射地面 —— 把它当球场地点标进去会把整份标定拉偏
          // （实测：去掉它，两段平均重投影误差 1.00m→0.03m、2.61m→0.18m）。
          // 篮筐请用上面的「在画面上标篮筐」，那条路直接存画面坐标，不走单应矩阵。
          { name: 'lane_far_left', label: 'A端罚球区右角', dst: [-2.45, 8.2], hint: '站在A端底线后朝场内看，罚球线右端与罚球区边线交点' },
          { name: 'ft_far', label: 'A端罚球线中点', dst: [0.0, 8.2], hint: 'A端罚球线正中，罚球时站的那条线' },
          { name: 'lane_far_right', label: 'A端罚球区左角', dst: [2.45, 8.2], hint: '站在A端底线后朝场内看，罚球线左端与罚球区边线交点' },
          { name: 'arc_far', label: 'A端三分弧顶', dst: [0.0, 5.675], hint: 'A端三分弧正对篮筐的最高点' },
          { name: 'half_left', label: '中线左边线交点', dst: [-7.5, 0.0], hint: '中线与画面左侧边线交点' },
          { name: 'center', label: '中圈中心', dst: [0.0, 0.0], hint: '中圈或中场标志的圆心' },
          { name: 'half_right', label: '中线右边线交点', dst: [7.5, 0.0], hint: '中线与画面右侧边线交点' },
          { name: 'lane_near_left', label: 'B端罚球区左角', dst: [-2.45, -8.2], hint: 'B端罚球线左端与罚球区边线交点' },
          { name: 'ft_near', label: 'B端罚球线中点', dst: [0.0, -8.2], hint: 'B端罚球线正中，罚球时站的那条线' },
          { name: 'lane_near_right', label: 'B端罚球区右角', dst: [2.45, -8.2], hint: 'B端罚球线右端与罚球区边线交点' },
          { name: 'arc_near', label: 'B端三分弧顶', dst: [0.0, -5.675], hint: 'B端三分弧正对篮筐的最高点' },
          { name: 'corner_near_left', label: 'B端底线左角', dst: [-7.5, -14.0], hint: 'B端篮筐后，底线与左边线交点' },
          { name: 'corner_near_right', label: 'B端底线右角', dst: [7.5, -14.0], hint: 'B端篮筐后，底线与右边线交点' }
          // 「B端篮筐中心」同样已移除（理由见上面 A端 那段注释）
        ]
      },
      mfFrames: [],           // 抽出来的画面 [{t,image,w,h}]
      mfIdx: 0,               // 当前是第几张
      mfPts: [],              // 已标点 [{t,name,label,x,y}]
      mfSideByT: {},          // 每个取帧时间各自归属 A端(right) 或 B端(left)
      mfTarget: '',           // 当前选中要标的点名
      mfResult: null,         // 解算结果
      mfPreviewed: false,     // 预览过且可用（界面上用来区分"预览"与"已保存"）
      hoverPt: null,          // 鼠标在画面上的位置（画准星用）
      mfCenter: 60,           // 在哪个时刻附近抽帧（同一镜头内）
      mfSpan: 3,              // 抽帧的时间跨度（秒）
      // 用户实测反馈：「只能在一个画面里点，想点完所有点根本不显示」——
      // 一个镜头里只看得见半场，剩下的半场在这个画面里压根不存在，
      // 于是怎么点都点不全。做法改成**左右两个画面各自点各自的点**：
      // A端、B端各自使用独立的地面地标名，两端的点一起送去解算。
      // 单应矩阵的硬要求没变：**每个画面自己要有 4 个以上、铺得开的点**
      // （backend /api/calibrate_multi 的 per_frame_fit 就是按这个判的）。
      dualView: true,         // true = 左右两个画面；false = 老的「一张一张切」
      mfActive: 0,            // 正在点哪个画面：0=左（上面那张）1=右
      mfIdx2: 0,              // 右边画面对应的帧下标
      courtPts: [],
      courtIdx: 0,
      courtResult: null,
      // 标定自检叠加层：把"这份 H 算出来的球场线"画回画面上，
      // 对不对得上一眼就能看见 —— 而不是只给一个"误差 4.2m"的数字。
      // 为什么必须加：5 个点里**任取 4 个都能精确解出 H（误差恒为 0）**，
      // 所以单看误差数字，用户根本无法判断自己点得对不对（实测争议点）。
      // 用户反馈：自动/失败标定的红色球场投影容易被误当作有效结果；默认不显示。
      showCourtOverlay: false,
      overlayW: 0,
      overlayH: 0,
      overlayLines: [],        // [[[x,y],...], ...] 画面像素坐标（左画面 / 单画面）
      // ⚠️ 叠线必须**每个画面各一份**。为什么（实测踩到）：左右两个画面是**两个机位**
      // （各拍半场、取的时刻也不同），后端一份 H 只属于其中一幅。以前两边都渲染同一个
      // overlayLines，于是把一个机位的球场线画到了另一个机位上 —— 左边整体偏 20m、
      // 右边也压不到白线，用户看到的"红框明显不对"就是这个。
      // 现在：左画面用自己那一帧的 H、右画面用自己那一帧的 H，分别算各自的线。
      overlayLinesLeft: [],
      overlayLinesRight: [],
      overlayWLeft: 0,
      overlayHLeft: 0,
      overlayWRight: 0,
      overlayHRight: 0,
      // 「点吸附精修」被采纳时的点（画成空心黄圈，供对照）——
      // 后端 refine_keypoints 采纳后，**存下来的标定用的是吸附后的点**，
      // 所以画面上必须也把它画出来，否则用户看到的点和他实际存下来的不一致
      //（会以为工具偷偷改了位置）。
      snapPts: [],
      // 四个未命名点只用于预览；正式标定使用多个人工命名地标。
      // 为什么不给点命名：corner_near_* 的坐标其实是 y=-14（另一端底线），
      // 命名与直觉相反，判错一次整张图平移 28m（实测踩过）。
      courtMini: false,
      mfMiniPts: [],           // [{t, seq(1..4), x, y}] 按点选顺序
      // ---- 拖动修正 + 点完自动叠线（用户 2026-10-05 的改进要求）----
      // mfDrag：正在拖的那个点（{t,name}）；mfDragMoved：这次按住有没有真的移动过
      // （没移动就是普通单击，仍然走"新增一个点"）
      mfDrag: null,
      mfDragMoved: false,
      // 点位/画面的版本号：自动叠线是异步的，回来时若版本变了（用户又点/拖/切了画面），结果必须丢弃，
      // 否则慢请求会把**旧点位算出来的线**画在新点位上（用户 2026-10-05 指出的风险）
      mfVersion: 0,
      autoPreviewTimer: null,  // 点/拖之后延迟自动解算一次（静默），让球场线立刻出现在画面上
      samples: [],             // 机器上现成的视频（示例 + 已上传）
      samplePick: '',
      localVideoUrl: '',
      localVideoPath: '',
      courtCaptureBusy: [false,false],
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
      return this.uploadPct < 0 && !!String(this.form.video_path || '').trim();
    },
    /** 用两个角把篮圈框出来。中心点无法提供尺寸，检测器漏筐时仍然救不回来；
     * 矩形框同时给出中心与宽高，后端可以直接锁定并在附近补检篮球。 */
    markItems: function () {
      return [
        { name: 'rim_box_tl', label: '篮筐框左上角', hint: '点在篮圈外接框的左上角' },
        { name: 'rim_box_br', label: '篮筐框右下角', hint: '点在篮圈外接框的右下角' }
      ];
    },
    /** 旧版可选四边保留为空，避免已有模板分支报错。 */
    markItemsOptional: function () {
      return [];
    },
    /** 当前模式要点的项（篮筐框两个角都必填 / 球场是点名清单，点够 4 个即可） */
    activeItems: function () {
      return this.markKind === 'court' ? this.courtItems : this.markItems;
    },
    /** 当前模式已点的点（**只用于篮筐模式**；球场模式的左右画面各自渲染
     *  mfPtsHere / mfPtsRight —— 用 activePts 会让另一边"看起来消失"） */
    activePts: function () {
      return this.markKind === 'court' ? this.mfPtsHere : this.markPts;
    },
    /** 当前模式的下标 */
    activeIdx: function () {
      return this.markKind === 'court' ? this.courtIdx : this.markIdx;
    },
    /** 当前画面 */
    mfCurrent: function () { return this.mfFrames[this.mfIdx] || null; },
    /** 右画面的帧（两个画面模式下才有意义；没有第二帧就退回跟左画面同一张） */
    mfCurrentRight: function () {
      if (!this.dualView) return null;
      return this.mfFrames[this.mfIdx2] || this.mfFrames[this.mfIdx] || null;
    },
    /** 每帧独立选择 A/B 端；left 对应 B端，right 对应 A端。 */
    frameCourtSide: function () {
      var self = this;
      return function (t, panel) {
        var side = self.mfSideByT && self.mfSideByT[String(Number(t))];
        return side === 'left' || side === 'right' ? side : (panel === 1 ? 'left' : 'right');
      };
    },
    /** 两个画面模式：左右各自一张，t 相同就只有一张（还没加第二帧） */
    mfDualSplit: function () {
      return !!(this.dualView && this.mfCurrentRight &&
                this.mfCurrent && this.mfCurrentRight.t !== this.mfCurrent.t);
    },
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
    /** **右画面**那一帧的原始像素尺寸。
     *  两个画面的 viewBox/坐标必须各用各的：以前右画面的 svg 用的是左帧的 frameW/frameH，
     *  两帧尺寸不同时（不同码率/不同机位的素材）右画面的点和叠线会被整体拉偏。 */
    frameWRight: function () {
      var f = this.mfCurrentRight || this.mfCurrent;
      if (this.markKind === 'court') return f ? f.w : 0;
      return this.markSize.w || 0;
    },
    frameHRight: function () {
      var f = this.mfCurrentRight || this.mfCurrent;
      if (this.markKind === 'court') return f ? f.h : 0;
      return this.markSize.h || 0;
    },
    /** 本帧已标的点（只画这些 —— 别的帧的点坐标不通用） */
    mfPtsHere: function () {
      var t = this.mfCurrent ? this.mfCurrent.t : null;
      return this.mfPts.filter(function (p) { return p.t === t; });
    },
    /** **右画面**那一帧上的点。
     *
     *  为什么必须单独有一个 computed（实测 bug）：右画面以前渲染的是
     *  `activePts`，而 `activePts === mfPtsHere` 只认 `mfCurrent`（左帧）。
     *  于是"在左画面标完、切到右画面标"的时候，左画面会把右帧的点排除掉，
     *  用户看到的现象就是"我标完左画面再标右画面，左画面标的点没了"
     *  （数据其实都在，是渲染时用错了时刻）。
     */
    mfPtsRight: function () {
      var t = this.mfCurrentRight ? this.mfCurrentRight.t : null;
      return this.mfPts.filter(function (p) { return p.t === t; });
    },
    /** **当前正在点的那一面**上有几个点（撤销/清空按钮的禁用状态要用它）。
     *  以前用 mfPtsHere（只认左帧），在右画面标完点后按钮还是灰的（实测 bug）。 */
    mfActivePtsCount: function () {
      if (!this.mfDualSplit) return this.mfPts.length;
      return (this.mfActive === 1 ? this.mfPtsRight : this.mfPtsHere).length;
    },
    // ---- 「只点 4 个点」模式的点（**必须是 computed，不能放 methods**）----
    //
    // 为什么单独写这段注释：一开始把这两个函数放进了 `methods`。模板里写
    // `miniPtsHere`（不带括号）时，Vue 拿到的是**函数对象本身**，于是：
    //   * `miniPtsHere.length` 读的是"函数的形参个数" = 0 → 槽位永远显示「未点」；
    //   * `v-for="p in miniPtsHere"` 遍历一个函数 → 0 次迭代 → **画面上不画任何圈**。
    // 而点其实全都记进了 mfMiniPts（所以点满 4 个之后守卫会拦住下一次点击）。
    // 用户看到的就是"点完 4 个啥也点不了了，而且没有圈"（实测三症状同一根因）。
    /** 左画面（mfCurrent）上的 4 点 */
    miniPtsHere: function () {
      var t = this.mfCurrent ? this.mfCurrent.t : null;
      return this.mfMiniPts.filter(function (p) { return p.t === t; });
    },
    /** 右画面上的 4 点 */
    miniPtsRight: function () {
      var t = this.mfCurrentRight ? this.mfCurrentRight.t : null;
      return this.mfMiniPts.filter(function (p) { return p.t === t; });
    },
    /** **当前正在点的那一面**上的 4 点 —— 槽位显示要用它。
     *  以前槽位固定用 miniPtsHere（左帧），在右画面点时槽位全显示「未点」，
     *  用户会以为没点上（实测 bug）。 */
    miniPtsActive: function () {
      if (!this.mfDualSplit) return this.mfMiniPts;
      return this.mfActive === 1 ? this.miniPtsRight : this.miniPtsHere;
    },
    /** 有没有哪一幅画面已经正好点满 4 个点（决定「先试算」能不能按）。
     *  ⚠️ 不能用 mfEnough —— 它数的是**命名点** mfPts，4 点模式下永远是 0，
     *  于是按钮一直是灰的、整个 4 点通道点不动（队友那边就是这个状态）。 */
    miniReady: function () {
      return this.miniPayload().length > 0;
    },
    /** 「点吸附精修」被采纳时的点（模板要画成空心黄圈，供对照）。
     *  ⚠️ 必须放 computed：放 methods 的话模板里 `snapPtsHere` 拿到的是函数对象，
     *  `v-for` 迭代 0 次 → 画面上什么都不显示（同类错误还有 miniPtsHere/miniPtsRight）。 */
    snapPtsHere: function () {
      var t = this.mfCurrent ? this.mfCurrent.t : null;
      return (this.snapPts || []).filter(function (p) { return p.t === t; });
    },
    snapPtsRight: function () {
      var t = this.mfCurrentRight ? this.mfCurrentRight.t : null;
      return (this.snapPts || []).filter(function (p) { return p.t === t; });
    },
    /** 另一个画面上的点（已不再用于渲染：右画面现在画 mfPtsRight。
     *  保留这段注释是为了记住踩过的坑：曾经右画面画的是"除左帧以外的所有点"，
     *  理由是"另一帧的坐标不通用、只当参照"，但那会让右画面的点出现在左画面上
     *  或反之，看起来就像"点丢了"。现在两边各画各的那一帧，界限清楚。） */
    /** 每个画面各自有几个点、够不够 4 个、点铺得开不开。
     *
     *  为什么必须单独显示：一个画面里只看得见半场，另一个半场的点要么在画面外、
     *  要么挤在边角上（点接近共线时单应矩阵的误差照样是 0.00m，但整份标定是错的）。
     *  所以"这个画面够不够"要当场告诉用户，而不是等解算失败才说一句"误差偏大"。 */
    mfFrameCov: function () {
      var F = this.mfFrames || [];
      return F.map(function (f) {
        var pts = this.mfPts.filter(function (p) { return p.t === f.t; });
        var tri = 0;
        for (var i = 0; i < pts.length; i++) {
          for (var j = i + 1; j < pts.length; j++) {
            for (var k = j + 1; k < pts.length; k++) {
              var a = Math.abs((pts[j].x - pts[i].x) * (pts[k].y - pts[i].y) -
                               (pts[k].x - pts[i].x) * (pts[j].y - pts[i].y)) / 2;
              if (a > tri) tri = a;
            }
          }
        }
        return { idx: F.indexOf(f), t: f.t, n: pts.length, tri: tri,
                 enough: pts.length >= 4, spread: tri >= 0.02 };
      }, this);
    },
    /** 两个画面模式下，左右画面各自标了几个点（界面顶部那两行读数用的） */
    mfLeftCov: function () {
      var t = this.mfCurrent ? this.mfCurrent.t : null;
      var c = null;
      this.mfFrameCov.forEach(function (x) { if (x.t === t) c = x; });
      return c || { t: t, n: 0, tri: 0, enough: false, spread: false };
    },
    mfRightCov: function () {
      var t = this.mfCurrentRight ? this.mfCurrentRight.t : null;
      var c = null;
      this.mfFrameCov.forEach(function (x) { if (x.t === t) c = x; });
      return c || { t: t, n: 0, tri: 0, enough: false, spread: false };
    },
    /** 完整球场必须分别有 A、B 两端各一幅可解画面。 */
    mfSideCoverage: function () {
      var counts = { A: 0, B: 0 };
      this.mfFrameCov.forEach(function (f) {
        if (!f.enough) return;
        var side = this.frameCourtSide(f.t, 0);
        if (side === 'right') counts.A += 1;
        else if (side === 'left') counts.B += 1;
      }, this);
      return counts;
    },
    mfFullCourtReady: function () {
      return this.mfSideCoverage.A > 0 && this.mfSideCoverage.B > 0;
    },
    /** 哪些画面自己就够 4 个点（后端 per_frame_fit 也是按这个判的） */
    solvableFrames: function () {
      return this.mfFrameCov.filter(function (f) { return f.enough; });
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
    /** 顶部四步流程的当前状态。 */
    guideSteps: function () {
      var hasVideo = !!String(this.form.video_path || '').trim();
      var hasCal = !!(this.calInfo && this.calInfo.exists);
      var calReady = !!(this.calInfo && this.calInfo.calibration_ok);
      var hoopRows = (this.savedMarks && this.savedMarks.hoops) || {};
      var hasHoop = !!(this.savedMarks && this.savedMarks.hoop) || Object.keys(hoopRows).length > 0;
      var leftHoop = Number((((hoopRows.left || {}).hoop || [0,0,0])[2]) || 0) > 0;
      var rightHoop = Number((((hoopRows.right || {}).hoop || [0,0,0])[2]) || 0) > 0;
      var measuredHoop = leftHoop && rightHoop;
      var legacyHoop = hasHoop && !leftHoop && !rightHoop;
      var job = (this.S && this.S.job) || {};
      var done = job.status === 'done';
      var rmse = (this.calInfo && this.calInfo.reproj_error_m != null)
        ? this.calInfo.reproj_error_m : null;
      return [
        { key: 'video', n: 1, title: '选一段视频', done: hasVideo,
          desc: hasVideo ? ('已选：' + this.videoBaseName) : '用现成示例，或上传本地文件',
          cta: hasVideo ? '换一个视频' : (this.samples.length ? '用示例视频' : '选择本地文件') },
        { key: 'calib', n: 2, title: '标定球场（可选）', done: calReady,
          desc: calReady
            ? ('球场位置校验通过' + (rmse != null ? ('，重投影误差 ' + rmse + ' m') : ''))
            : hasCal ? '检测到旧标定，但位置校验未通过；重新标点后再生成热区/战术图'
            // 一句话说清"怎么做 + 不做的后果"。**必须保留"不标也能分析"这几个字**：
            // 不写用户就以为标定是硬门槛（`tests/test_upload_payload.js` 也在钉这条）。
            : '在画面里点 4~6 个地面点；不标也能分析（热图/战术图要标）',
          cta: hasCal ? '重新标定' : '标定球场' },
        { key: 'hoop', n: 3, title: '标定篮筐（推荐）', done: measuredHoop,
          desc: measuredHoop ? '左右半场篮筐均已框选'
            : (leftHoop || rightHoop
                ? ('已框' + (leftHoop ? '左' : '右') + '半场，还需框' + (leftHoop ? '右' : '左') + '半场')
                : (legacyHoop ? '已有旧版单篮筐标点，请补齐左右半场'
                              : '左右半场分别框选，避免检测器漏筐')),
          cta: measuredHoop ? '重新框选篮筐' : '框选篮筐' },
        { key: 'run', n: 4, title: '开始分析', done: done,
          desc: done
            // 完成后要指出"判错了去哪儿改"——去掉「训练标注」模块后，
            // 「人工复核」是唯一的纠错入口，界面上必须还找得到（test_ui_home.js 钉这条）。
            ? '分析完成；判错去「人工复核」改判' : '点「开始分析」，跑完变 ✓',
          cta: done ? '去看结果' : '开始分析' }
      ];
    },
    calInfoSegmentRows: function () {
      return ((this.calInfo && this.calInfo.segments) || []).map(function (s) {
        var a = s.t_start == null ? '?' : Number(s.t_start).toFixed(1);
        var b = s.t_end == null ? '?' : Number(s.t_end).toFixed(1);
        return {
          when: a + '–' + b + 's',
          ratio: s.ratio == null ? '—' : s.ratio,
          ok: s.ratio != null && Number(s.ratio) >= 1.25,
          points: (s.points || []).map(function (p) {
            return p.name + ' (' + p.px.join(', ') + ')';
          }).join('、')
        };
      });
    },
    calInfoPointSummary: function () {
      return this.calInfoSegmentRows.map(function (s) {
        return s.when + '：吻合度 ' + s.ratio + '；点位 ' + (s.points || '无记录');
      }).join('；');
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
    hoopSavedState: function () {
      var rows = (this.savedMarks && this.savedMarks.hoops) || {};
      function valid(side) {
        return Number((((rows[side] || {}).hoop || [0,0,0])[2]) || 0) > 0;
      }
      return { left: valid('left'), right: valid('right') };
    },
    /** 与 guideNext 配套的一句话：已点几个、离能保存还差几个 */
    guideDesc: function () {
      if (this.markKind !== 'court') {
        return '已点 ' + this.markPts.length + ' 个；' +
          (this.markHoop ? '篮筐框已完成；分析会直接锁定这个篮筐并在附近补检篮球'
                         : '请依次点篮筐框的左上角、右下角');
      }
      var n = this.guideCount;
      var enough = this.mfFrames.length ? this.mfEnough : this.courtEnough;
      var tail = this.mfFrames.length
        ? (this.mfDualSplit
            ? '。左画面 ' + this.mfLeftCov.n + ' 个、右画面 ' + this.mfRightCov.n +
              ' 个 —— 每边各自够 4 个才算解得出（两边的点不能互相补）'
            : '。画面里看不到的点按「跳过这一项」跳过它。')
        : '';
      return '已点 ' + n + ' 个（两边合计）' +
        (enough ? '——点数已够试算，请先生成投影，核对两端场线后再保存'
                : '——每边至少 4 个、建议 5~6 个') + tail;
    },
    /** 两个角直接得到篮圈外接框。 */
    markHoop: function () {
      var self = this;
      function g(n) {
        var p = self.markPts.filter(function (q) { return q.name === n; })[0];
        return p ? { x: p.x, y: p.y } : null;
      }
      var tl = this.hoopDragStart || g('rim_box_tl');
      var br = this.hoopDragCurrent || g('rim_box_br');
      if (tl && br) {
        var left = Math.min(tl.x, br.x), right = Math.max(tl.x, br.x);
        var top = Math.min(tl.y, br.y), bottom = Math.max(tl.y, br.y);
        if (right-left < 0.002 || bottom-top < 0.002) return null;
        return { cx:(left+right)/2, cy:(top+bottom)/2,
                 rx:(right-left)/2, ry:(bottom-top)/2, measured:true };
      }
      // 兼容已保存/旧会话里“中心 + 边缘”的点。
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
    /** 表单里有没有可用视频（取帧、标点、开工都必须先有它） */
    hasVideoPath: function () {
      return !!String((this.form && this.form.video_path) || '').trim();
    },
    statusTag: function () {
      return { queued: 'info', running: 'warning', done: 'success', error: 'danger' }[this.job.status] || 'info';
    },
    statusText: function () {
      return { queued: '排队中', running: '分析中', done: '已完成', error: '失败' }[this.job.status] || '未开始';
    },
    percent: function () { return Math.round((Number(this.job.progress) || 0) * 100); },
    /** 标定"吻合度"读数：分析端收不收这份标定的硬门槛是 ≥1.25。
     *  放在 computed 里是因为模板要拿它判颜色/文案。 */
    fitRatio: function () {
      var r = this.mfResult || this.courtResult;
      var f = r && r.calibration_fit;
      var v = f && f.ratio;
      return (typeof v === 'number') ? v : 0;
    },
    /** 这份标定的吻合度是**哪一段**的读数（分时段标定才有）。
     *
     *  实测争议点：界面只显示一个"吻合度 0.17"，用户看不出"是整份都差，
     *  还是只有那一段差"。分时段标定里每一段各解一份 H，后端给的是**最差那一段**
     *  的读数（取最好那段会把坏段盖住），所以必须把"这是最差一段"和"每段各是多少"
     *  一起摆出来，否则用户只能理解成"工具坏了"或者把整份重标一遍。 */
    fitSegRows: function () {
      var r = this.mfResult || this.courtResult;
      var f = r && r.calibration_fit;
      var list = (f && f.by_segment) || [];
      if (!Array.isArray(list) || list.length < 2) return [];
      return list.map(function (s) {
        var a = (s && s.t_start != null) ? Number(s.t_start) : NaN;
        var b = (s && s.t_end != null) ? Number(s.t_end) : NaN;
        var ratio = (s && s.ratio != null) ? Number(s.ratio) : NaN;
        return {
          when: (isFinite(a) ? a.toFixed(1) : '?') + '~' + (isFinite(b) ? b.toFixed(1) : '?') + 's',
          ratio: isFinite(ratio) ? ratio : null,
          rmse: (s && s.rmse_m != null) ? s.rmse_m : null,
          n: (s && s.n_points != null) ? s.n_points : null,
          // 吻合度和重投影误差都要过关；仅靠小误差无法证明点名正确。
          ok: isFinite(ratio) && ratio >= 1.25 && s && s.rmse_m != null &&
            Number(s.rmse_m) <= 1.5
        };
      });
    },
    /** 吻合度读数是不是"分时段里最差那一段"的（决定标题怎么写，别让用户误会成整份） */
    fitIsWorstOfSegments: function () { return this.fitSegRows.length > 0; },
    /** 多机位标定里"不可信的那几段"（后端 calibration_fit.weak_segments）。
     *
     *  为什么必须逐段摆出来（用户实测踩到）：多机位是**每一段各解一份 H**，
     *  而以前返回的吻合度取的是 max —— 好段把坏段盖住了（实测两段 0.34 / 3.12，
     *  界面报 3.12、说"标定可用"），于是**半个视频的球员坐标是错的**，
     *  用户看到的现象就是"战术图到了一分钟之后怎么就乱码了"。
     *  现在后端给的是**最差那一段**的读数 + 不可信段清单，这里把它们逐段显示出来：
     *  哪一段时间不可信、吻合度多少、误差多少。
     *  老后端没有这个字段 → 返回空数组，界面不多说一句话。 */
    weakSegs: function () {
      var r = this.mfResult || this.courtResult;
      var f = r && r.calibration_fit;
      var list = (f && f.weak_segments) || [];
      if (!Array.isArray(list)) return [];
      return list.map(function (s) {
        // ⚠️ 缺字段要显示成 "?"，不能靠 Number(undefined)=NaN 之外的小聪明：
        // Number(null) 是 0，naive 写法会把"没给开始时刻"显示成 0.0s（假读数）。
        var a = (s && s.t_start != null) ? Number(s.t_start) : NaN;
        var b = (s && s.t_end != null) ? Number(s.t_end) : NaN;
        return {
          from: isFinite(a) ? a.toFixed(1) : '?',
          to: isFinite(b) ? b.toFixed(1) : '?',
          ratio: (s && s.ratio != null) ? s.ratio : '—',
          rmse_m: (s && s.rmse_m != null) ? s.rmse_m : '—',
          why: (s && s.why) || '这一段不可信',
          diagnostic: (s && s.diagnostic) || null
        };
      });
    },
    /** 哪些点名在某一幅画面里根本看不见（用解出来的 H 反投影判断）。
     *
     *  为什么要这个：这台机位只拍得到半场时，「另一侧的底线角」在画面里
     *  压根不存在，用户硬点只能靠猜 —— 误差就是这么来的（实测：用户把
     *  "底线右角"点成了罚球区右角，偏 9m）。解算后用同一份 H 就能算出
     *  每个特征点该落在画面的哪个位置，落在画面外的就是"看不见"。
     *
     *  ⚠️ 必须放在 computed：模板里当值用（offFrameNames.length）。
     */
    offFrameNames: function () {
      var r = this.mfResult || this.courtResult;
      var H = r && r.H;
      if (!H || this.markKind !== 'court') return [];
      // 和叠加层同一个方向问题：H 是「像素 → 球场米」，反投影必须用它的逆。
      var inv = this._invertH(H);
      if (!inv) return [];
      var items = this.courtItems || [];
      var frames = (this.mfFrames || []).slice();
      if (!frames.length && this.frameW) {
        frames = [{ t: null, w: this.frameW, h: this.frameH }];
      }
      if (!frames.length) return [];
      var out = [];
      items.forEach(function (it) {
        var m = it.dst;                 // 球场全场坐标（米）；半场那两份清单没带 dst
        if (!m || m.length < 2) return;
        var w = inv[2][0] * m[0] + inv[2][1] * m[1] + inv[2][2];
        if (Math.abs(w) < 1e-9) { out.push(it.label); return; }
        var u = (inv[0][0] * m[0] + inv[0][1] * m[1] + inv[0][2]) / w;
        var v = (inv[1][0] * m[0] + inv[1][1] * m[1] + inv[1][2]) / w;
        if (!isFinite(u) || !isFinite(v)) { out.push(it.label); return; }
        // 至少得在**一幅**画面里能看见，否则这个点名就是"点了也白点"。
        // 用 6% 的宽容边框：标定本身有误差，紧贴边缘的点不算"看不见"。
        var seen = frames.some(function (f) {
          var pad = 0.06;
          return u > -pad * f.w && u < f.w * (1 + pad) &&
                 v > -pad * f.h && v < f.h * (1 + pad);
        });
        if (!seen) out.push(it.label);
      });
      return out;
    }
  },
  watch: {
    mfPts: { deep: true, handler: function () { this.storeCourtDraft(); } },
    mfSideByT: { deep: true, handler: function () { this.storeCourtDraft(); } },
    courtStandard: function () {
      this.mfResult = null; this.mfPreviewed = false; this.showCourtOverlay = false;
      this.mfVersion++; this.syncCourtSideForActive(); this.storeCourtDraft();
    }
  },
  mounted: function () {
    this.refreshJobs();
    this.fetchHealth();
    this.loadSamples();
    try { this.courtDraftAvailable = !!localStorage.getItem('aihoop-court-draft'); }
    catch (e) { this.courtDraftAvailable = false; }
  },
  beforeUnmount: function () {
    if (this.watcher) this.watcher.close();
    if (this.localVideoUrl) URL.revokeObjectURL(this.localVideoUrl);
  },
  methods: {
    storeCourtDraft: function () {
      if (this.markKind !== 'court' || !this.mfPts.length || !this.mfFrames.length) return;
      var draft = {video_path: this.form.video_path, court_standard: this.courtStandard,
        frames: this.mfFrames.map(function (f) { return {t:f.t,w:f.w,h:f.h}; }),
        points: this.mfPts, sideByT: this.mfSideByT,
        left: this.mfIdx, right: this.mfIdx2};
      try { localStorage.setItem('aihoop-court-draft', JSON.stringify(draft));
        this.courtDraftAvailable = true; } catch (e) { /* Do not interrupt marking. */ }
    },
    restoreCourtDraft: function (draft) {
      var self = this;
      try {
        if (!draft || !draft.frames) draft = JSON.parse(localStorage.getItem('aihoop-court-draft') || '{}');
        if (!draft.video_path || !Array.isArray(draft.frames) || !Array.isArray(draft.points)) throw new Error('草稿格式不正确');
        var known = {}; this.courtSideNames.full.forEach(function (p) { known[p.name] = p.label; });
        if (!draft.points.every(function (p) { return known[p.name] && isFinite(p.t) &&
          isFinite(p.x) && isFinite(p.y) && p.x >= 0 && p.x <= 1 && p.y >= 0 && p.y <= 1; })) throw new Error('草稿包含无效点位');
      } catch (e) { this.$message.error(String(e.message || e)); return; }
      this.form.video_path = draft.video_path;
      this.markSaving = true;
      Promise.all(draft.frames.map(function (f) {
        return window.API.getFrame(draft.video_path, Number(f.t)).then(function (r) {
          return {t:Number(f.t),w:r.w,h:r.h,image:r.image};
        });
      })).then(function (frames) {
        self.markKind = 'court'; self.courtMini = false; self.dualView = true;
        self.courtStandard = draft.court_standard === 'nba' ? 'nba' : 'fiba';
        self.mfFrames = frames; self.mfIdx = Math.min(draft.left || 0,frames.length-1);
        self.mfIdx2 = Math.min(draft.right == null ? 1 : draft.right,frames.length-1);
        self.mfPts = draft.points.map(function (p) {
          return Object.assign({}, p, {label:p.label || known[p.name]});
        }); self.mfSideByT = draft.sideByT || {};
        self.mfActive = 1; self.mfTarget = ''; self.mfResult = null;
        self.mfPreviewed = false; self.showCourtOverlay = false; self.mfVersion++;
        self.markOpen = true; self.markSaving = false;
        self.syncCourtSideForActive(); self.loadPlayer(); self.loadCalInfo();
        self.$message.success('已恢复 A/B 标点草稿，请生成矩阵核对');
      }).catch(function (e) { self.markSaving = false; self.$message.error('草稿取帧失败：'+String(e.message || e)); });
    },
    importCourtDraft: function (event) {
      var self = this, file = event.target.files && event.target.files[0];
      if (!file) return;
      file.text().then(function (s) { self.restoreCourtDraft(JSON.parse(s.replace(/^\uFEFF/, ''))); })
        .catch(function (e) { self.$message.error('草稿读取失败：'+String(e.message || e)); });
      event.target.value = '';
    },
    /** 分析完成后跳「人工复核」：判错的球在那儿改判（会写回比分与统计） */
    goReview: function () { location.hash = '#/review'; },
    /** 跳「结果总览」 */
    goOverview: function () { location.hash = '#/overview'; },

    /* ------------------------------------------------------------------
       在画面上标篮筐（不用敲命令行）
       ------------------------------------------------------------------ */
    openMark: function () {
      var self = this, v = String(this.form.video_path || '').trim();
      if (!v) { this.$message.warning('先选一个视频'); return; }
      this.markKind = 'hoop';
      this.markOpen = true;
      this.markPts = [];
      this.hoopPanelDrag = null;
      var session = ++this.hoopSession;
      this.hoopPanels = {
        left: {at:1,image:'',box:null,loading:false,version:0},
        right: {at:1,image:'',box:null,loading:false,version:0}
      };
      this.loadPlayer();
      window.API.getMarks(v).then(function (r) {
        if (session !== self.hoopSession) return;
        self.savedMarks = r && r.exists ? Object.assign({}, r.marks, {path:r.path}) : null;
        var hs = (self.savedMarks && self.savedMarks.hoops) || {};
        ['left','right'].forEach(function (side) {
          var row = hs[side];
          if (!row || self.hoopPanels[side].version) return;
          self.hoopPanels[side].at = row.at;
          var size = row.frame_size || self.savedMarks.frame_size;
          var box = row.hoop;
          var normalized = box && size && size[0] && size[1]
            ? [box[0]/size[0],box[1]/size[1],box[2]/size[0],box[3]/size[1]] : null;
          self.loadHoopPanel(side, normalized);
        });
      }).catch(function (e) {
        if (session !== self.hoopSession) return;
        self.$message.error('读取篮筐标定失败：' + e.message);
      });
    },
    loadHoopPanel: function (side, savedBox) {
      if (this.markSaving) return;
      var self = this, panel = this.hoopPanels[side];
      var session = this.hoopSession, version = ++panel.version;
      var at = Number(panel.at) || 0;
      panel.loading = true;
      panel.image = '';
      panel.box = null;
      window.API.getFrame(String(this.form.video_path).trim(), at).then(function (r) {
        if (session !== self.hoopSession || version !== panel.version) return;
        panel.image = r.image;
        panel.frameAt = at;
        panel.box = savedBox || null;
        panel.restored = !!savedBox;
        panel.loading = false;
      }).catch(function (e) {
        if (session !== self.hoopSession || version !== panel.version) return;
        panel.loading = false;
        self.$message.error('取帧失败：' + e.message);
      });
    },
    captureHoopPanel: function (side) {
      if (this.markSaving) return;
      var video = this.$refs['hoopVideo_' + side];
      if (Array.isArray(video)) video = video[0];
      if (!video || video.readyState < 2 || video.seeking || !video.videoWidth) { this.$message.warning('请等这一侧画面加载完成'); return; }
      video.pause();
      var panel = this.hoopPanels[side];
      var canvas = document.createElement('canvas');
      canvas.width=video.videoWidth;canvas.height=video.videoHeight;
      try {
        canvas.getContext('2d').drawImage(video,0,0);
        var image=canvas.toDataURL('image/jpeg',.9);
        ++panel.version;
        panel.image=image;panel.at=video.currentTime;panel.frameAt=video.currentTime;
        panel.box=null;panel.restored=false;panel.loading=false;
      } catch(e) { this.$message.error('当前画面无法截取，请重新加载视频'); }
    },
    hoopVideoTime: function (side, event) {
      this.hoopPanels[side].at = event.target.currentTime;
    },
    seekHoopPanel: function (side, at) {
      var video=this.$refs['hoopVideo_'+side];
      if(Array.isArray(video))video=video[0];
      if(video) {video.pause();video.currentTime=Math.max(0,Number(at)||0);}
    },
    swapHoopPanels: function () {
      if (this.markSaving || this.hoopPanels.left.loading || this.hoopPanels.right.loading) return;
      var left = this.hoopPanels.left;
      this.hoopPanels.left = this.hoopPanels.right;
      this.hoopPanels.right = left;
      this.hoopPanelDrag = null;
      this.$nextTick(function () {
        ['left','right'].forEach(function (side) {
          var video = this.$refs['hoopVideo_' + side];
          if (Array.isArray(video)) video = video[0];
          if (video) video.currentTime = this.hoopPanels[side].at;
        }, this);
      });
    },
    hoopPanelDown: function (side, ev) {
      if (this.markSaving || !this.hoopPanels[side].image) return;
      var point = this.markEventPoint(ev);
      if (!point) return;
      ev.preventDefault();
      this.hoopPanelDrag = {side:side, start:point};
      this.hoopPanels[side].box = null;
      this.hoopPanels[side].restored = false;
    },
    hoopPanelMove: function (side, ev) {
      var drag = this.hoopPanelDrag;
      if (!drag || drag.side !== side) return;
      var b = this.markEventPoint(ev), a = drag.start;
      if (!b) return;
      this.hoopPanels[side].box = Math.abs(a.x-b.x) >= 0.002 && Math.abs(a.y-b.y) >= 0.002
        ? [(a.x+b.x)/2,(a.y+b.y)/2,Math.abs(a.x-b.x)/2,Math.abs(a.y-b.y)/2] : null;
    },
    hoopPanelUp: function (side, ev) {
      this.hoopPanelMove(side, ev);
      this.hoopPanelDrag = null;
    },
    hoopPanelStyle: function (box) {
      return {left:(box[0]-box[2])*100+'%', top:(box[1]-box[3])*100+'%',
        width:box[2]*200+'%', height:box[3]*200+'%'};
    },
    /** 打开「标球场」：抽帧 → 在画面里点地标 → 解算（走 /api/calibrate_multi） */
    openCourt: function () {
      var v = String(this.form.video_path || '').trim();
      if (!v) { this.$message.warning('先选一个视频'); return; }
      this.markKind = 'court';
      this.markOpen = true;
      this.mfFrames = [];
      this.mfIdx = 0;
      this.mfIdx2 = 0;
      this.mfActive = 0;
      // 球场标定必须保留左右两幅独立画面：每幅都要明确标到哪个半场。
      this.dualView = true;
      this.mfPts = [];
      this.mfSideByT = {};
      this.mfTarget = '';
      this.mfResult = null;
      this.courtMini = false;
      this.mfMiniPts = [];
      this.markImg = '';
      this.loadPlayer();                 // 挂上原片：可以拖着找到"场地看得最全"的那一帧再加进来
      // 点名表**只用本地这张表**（按"摄像机拍的是哪一侧"取 7 个），不再拉后端那 17 个。
      // 后端那 17 个里有一半是"另一侧/中圈那一头"的点，在这种机位下画面里根本不存在，
      // 列出来只会让用户去点不存在的东西（实测：把"底线右角"点成了罚球区右角，偏 9.17m）。
      this.setCourtSide('left');
      // 先显示可标定画面，不让分镜识别或不支持的编码挡住入口。
      this.mfFrames = [{t:-1,w:0,h:0,image:''},{t:-2,w:0,h:0,image:''}];
      this.mfIdx=0;this.mfIdx2=1;
      this.mfVersion++;
      this.syncCourtSideForActive();
      this.loadCalInfo();                // 顺便读回"这段视频已有标定没有"
    },
    captureCourtPanel: function (panel) {
      if (this.markSaving || this.courtCaptureBusy[panel]) return;
      var video = this.$refs['courtVideo_'+panel];
      if (Array.isArray(video)) video=video[0];
      if (!video || video.readyState<2 || !video.videoWidth) {
        this.$message.warning('先在这一侧播放器选好画面'); return;
      }
      video.pause();
      var t=Number(video.currentTime.toFixed(2));
      var other=panel===0 ? this.mfCurrentRight : this.mfCurrent;
      if (other && other.image && Math.abs(other.t-t)<.01) {
        this.$message.warning('两侧请分别选取不同时间的半场画面'); return;
      }
      var canvas=document.createElement('canvas');
      canvas.width=video.videoWidth;canvas.height=video.videoHeight;
      var image;
      try {
        canvas.getContext('2d').drawImage(video,0,0);
        image=canvas.toDataURL('image/jpeg',.9);
      } catch (e) { this.$message.error('当前播放器无法截取画面，请重新加载视频'); return; }
      var index=panel===0 ? this.mfIdx : this.mfIdx2;
      var previous=this.mfFrames[index];
      var side=this.frameCourtSide(previous ? previous.t : -1,panel);
      this.mfPts=this.mfPts.filter(function(p){return !previous || p.t!==previous.t;});
      this.mfFrames.splice(index,1,{t:t,w:canvas.width,h:canvas.height,image:image});
      this.mfSideByT=Object.assign({},this.mfSideByT,{[String(t)]:side});
      this.mfActive=panel;this.mfTarget='';this.mfResult=null;this.mfPreviewed=false;
      this.showCourtOverlay=false;this.overlayLines=[];this.overlayLinesLeft=[];this.overlayLinesRight=[];
      this.mfVersion++;this.syncCourtSideForActive();this.storeCourtDraft();
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
      this.videoUrl = v ? (this.localVideoPath===v && this.localVideoUrl ? this.localVideoUrl :
        (window.API.markVideoUrl ? window.API.markVideoUrl(v) : window.API.videoUrl(v))) : '';
    },
    /** 数字框改了秒数 → 播放器跟着跳过去（两边保持同步） */
    seekVideo: function (t) {
      var el = this.$refs.markVideo;
      if (!el) { return; }
      try { el.currentTime = Math.max(0, Number(t) || 0); } catch (e) { /* 元数据还没到就忽略 */ }
    },
    /** 把某一时刻的画面**加进帧列表**（球场模式用：想标哪一帧就加哪一帧）     *
     *  `onReady(t)` 可选：加完帧后回调，两个画面模式用它把新帧直接放到对应半边
     *  （不然用户"加了一帧却不知道它在哪个画面里"）。 */
    addFrameAtTime: function (t, onReady) {
      var self = this;
      var v = String(this.form.video_path || '').trim();
      var tt = Number(Number(t).toFixed(2));
      window.API.getFrame(v, tt).then(function (r) {
        self.mfFrames.push({ t: tt, w: r.w, h: r.h, image: r.image });
        self.mfIdx = self.mfFrames.length - 1;
        self.mfTarget = '';
        self.mfResult = null;
        self.mfVersion++;
        if (typeof onReady === 'function') {
          onReady(tt);
          return;                     // 由回调给出更贴切的提示
        }
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
      if (this.markKind === 'court') {
        var self = this;
        var side = this.dualView ? this.mfActive : 0;
        var keepLeftIdx = this.mfIdx;
        var keepRightIdx = this.mfIdx2;
        this.addFrameAtTime(t, function (tt) {
          var i = self.mfFrames.length - 1;
          if (self.dualView) {          // 两个画面模式：放到当前那一半，并切过去
            if (side === 1) {
              self.mfIdx = keepLeftIdx;
              self.mfIdx2 = i;
            } else {
              self.mfIdx = i;
              self.mfIdx2 = keepRightIdx;
            }
            self.mfActive = side;
            var sideMap = Object.assign({}, self.mfSideByT || {});
            // 默认：左画面放 A端（y>0），右画面放 B端（y<0）。面板位置
            // 不能直接当成 courtSide；courtSide 的 'right' 才代表 A端。
            sideMap[String(Number(tt))] = side === 1 ? 'left' : 'right';
            self.mfSideByT = sideMap;
            self.syncCourtSideForActive();
          }
          self.$message.success('已把 t=' + tt + 's 的这幅画面放到' +
            (self.dualView ? (side === 0 ? '左' : '右') : '') +
            '画面 —— 现在可以在它上面点这个半场的点');
        });
        return;
      }
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
        // 换批画面：只保留"新画面里还有同一时刻"的点。
        // 不能一律清空 —— 用户可能已经辛辛苦苦标了一个半场，重抽一次就全没了；
        // 也不能一律留着 —— 画面换了以后那些点会飘到别的地方去（实测反馈的"点跟着漂"）。
        var frames = (d && d.frames) || [];
        var kept = 0, lost = 0;
        if (self.mfPts.length) {
          var ts = {};
          frames.forEach(function (f) { ts[f.t] = 1; });
          var before = self.mfPts.length;
          self.mfPts = self.mfPts.filter(function (p) { return !!ts[p.t]; });
          kept = self.mfPts.length;
          lost = before - kept;
        }
        self.mfFrames = frames;
        self.mfIdx = 0;
        self.mfIdx2 = Math.min(1, Math.max(0, self.mfFrames.length - 1));
        self.mfActive = 0;
        self.$message.success('抽到 ' + self.mfFrames.length + ' 帧（t=' +
          (self.mfFrames.length ? self.mfFrames[0].t + '~' +
           self.mfFrames[self.mfFrames.length - 1].t : '') + 's）' +
          (lost ? ('；' + lost + ' 个点所在的画面已经不在这批里，已丢弃（保留 ' +
                   kept + ' 个）') : ''));
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
    /** 当前要往哪个画面的帧上落点（左右各自一张画面时以点击的那张为准） */
    mfClickT: function (ev) {
      var el = ev && ev.currentTarget;
      var side = (el && el.getAttribute) ? el.getAttribute('data-side') : null;
      if (side === '1' && this.mfCurrentRight) { this.mfActive = 1; this.syncCourtSideForActive(); return this.mfCurrentRight.t; }
      if (side === '0' && this.mfCurrent) { this.mfActive = 0; this.syncCourtSideForActive(); return this.mfCurrent.t; }
      return this.mfCurrent ? this.mfCurrent.t : null;
    },
    /** 切换「只点 4 个点」模式：两边点集不通用，切换时清干净并说明。 */
    setCourtMini: function (v) {
      this.courtMini = !!v;
      this.mfMiniPts = [];
      this.mfPts = [];
      this.mfTarget = '';
      this.mfResult = null;
      this.snapPts = [];
      this.mfVersion++;          // 点集换了 → 在途的自动叠线结果作废
      this.$message.info(this.courtMini
        ? '已切到「4 点试算」：仅预览投影线，不能保存为正式（热区/战术图）标定'
        : '已切回「命名地标」：标 4 个以上看得见的地标，并核对球场线投影');
    },
    /** 在画面上点一个点（必须是先选中了某个特征点）
     *
     *  左右两个画面各有各的坐标系：点落在**哪一张画面**上，就记那一张的 t。
     *  以前这里只认 mfCurrent，于是"在右边画面点的点"会被记到左边画面上，
     *  坐标整体跑到另一边去。 */
    mfClick: function (ev) {
      if (!this.mfCurrent) return;
      var t = this.mfClickT(ev);
      if (t === null || !this.mfFrames.some(function(f){return f.t===t && f.image;})) return;
      var el = (ev.target && ev.target.tagName === 'IMG') ? ev.target
                                                          : ev.currentTarget;
      var box = el.getBoundingClientRect();
      var x = Math.max(0, Math.min(1, (ev.clientX - box.left) / box.width));
      var y = Math.max(0, Math.min(1, (ev.clientY - box.top) / box.height));

      // ---- 「只点 4 个点」模式：**不给点命名**，按点选顺序记录 ----
      // 顺序本身就是数据：它决定这 4 个点对应球场上的哪一套地物，后端拿它
      // 穷举试 10 种组合、用"投影线压在白线上"挑最好的那套。所以**不能**按名字存。
      if (this.courtMini) {
        var sameHere = this.mfMiniPts.filter(function (p) { return p.t === t; });
        if (sameHere.length >= 4) {
          this.$message.warning('这一幅画面已经点了 4 个点。要重来请按「重点这一幅」。');
          return;
        }
        this.mfMiniPts.push({ t: t, seq: sameHere.length + 1, x: x, y: y });
        this.showCourtOverlay = false;
        this.mfResult = null;
        this.$message.success('第 ' + (sameHere.length + 1) + ' 个点 → (' +
          x.toFixed(3) + ', ' + y.toFixed(3) + ')' +
          (sameHere.length + 1 < 4 ? '，继续点第 ' + (sameHere.length + 2) + ' 个'
                                   : '，4 个点齐了，按「先试算」'));
        return;
      }

      if (!this.mfTarget) {
        this.$message.warning('先在下面选一个球场地面特征点，再在画面里点它的实际位置'
          + (this.mfDualSplit ? '—— 选一次就能在两边各点一下' : ''));
        return;
      }
      var item = null;
      for (var i = 0; i < this.courtItems.length; i++) {
        if (this.courtItems[i].name === this.mfTarget) { item = this.courtItems[i]; }
      }
      // 同名点只保留最后一次，但**只在同一个画面里替换**：
      // 「底线左角」在左半场和右半场各出现一次，那是两个不同的点；
      // 以前按名字全局去重，点第二半场时会把第一半场的点删掉
      // （用户看到的现象就是"点完所有点一个都不显示"）。
      var self = this;
      var sameT = this.mfPts.filter(function (p) {
        return p.t === t && p.name === self.mfTarget; });
      var extra = sameT.length ? '（改到了新位置）' : '（这也是一幅画面里的第 ' +
        (this.mfPtsHere.length + 1) + ' 个点）';
      this.mfPts = this.mfPts.filter(function (p) {
        return !(p.t === t && p.name === self.mfTarget); });
      this.mfPts.push({ t: t, name: this.mfTarget,
                        label: item ? item.label : this.mfTarget, x: x, y: y });
      this.mfTarget = '';
      this.mfVersion++;
      this.showCourtOverlay = false;
      // ★ 加了新点就清掉上一次的解算结果 —— 否则界面一直显示"旧报错"，
      // 用户会以为补点之后还是不行（实测踩到：先点 4 个点报错，再补到 6 个，
      // 红框仍写着"只点了 4 个点"，用户就卡在这里了）
      this.mfResult = null;
      // 立刻回显坐标：用户一眼就能看出记的是不是鼠标点的地方
      this.$message.success('已记录 ' + (item ? item.label : '') + extra +
        ' → (' + x.toFixed(3) + ', ' + y.toFixed(3) + ')' +
        (this.mfDualSplit ? ('（' + (this.mfActive === 1 ? '右' : '左') + '画面）') : ''));
      // ★ 点完就自动算一次并叠线（静默）：用户不用先按「预览」才知道压得准不准
      this.scheduleAutoPreview();
    },
    /* ---------------- 拖动修正 + 自动叠线（用户 2026-10-05 要求） ----------------
     *
     *  为什么要有拖动：一个点偏 3~5 像素，整份标定就会整体歪一点，而"撤销重标"还得
     *  重新去点名表里找同一个名字，实测用户更想**直接把那个点拖到新位置**。
     *  为什么要有自动叠线：叠线是唯一能肉眼判断对错的证据（4 个点就能精确解出 H、
     *  误差恒为 0，数字看不出来），点完立刻看见红线压没压在画面白线上，才知道下一个点往哪点。
     */
    /** 按住已标的点开始拖动（28px 内算抓住那个点；没抓到就是普通单击 → 新增一个点） */
    mfDragStart: function (ev) {
      if (this.markKind !== 'court' || !this.mfFrames.length) return;
      var t = this.mfClickT(ev);
      if (t === null) return;
      var el = ev.currentTarget;
      var box = el.getBoundingClientRect();
      if (!box.width) return;
      var mx = (ev.clientX - box.left) / box.width;
      var my = (ev.clientY - box.top) / box.height;
      var tol = Math.max(0.012, 28 / Math.max(1, box.width));
      var hit = null, best = 1e9;
      this.mfPts.forEach(function (p) {
        if (p.t !== t) return;
        var d = Math.sqrt((p.x - mx) * (p.x - mx) + (p.y - my) * (p.y - my));
        if (d <= tol && d < best) { best = d; hit = p; }
      });
      if (!hit) return;
      this.mfDrag = { t: t, name: hit.name };
      this.mfDragMoved = false;
      if (ev.preventDefault) ev.preventDefault();
    },
    /** 拖动中：实时改那个点的归一化坐标（返回 true 表示这一下是拖动，别再走悬停准星） */
    mfDragMove: function (ev) {
      if (!this.mfDrag) return false;
      var el = ev.currentTarget;
      var box = el.getBoundingClientRect();
      if (!box.width) return true;
      var x = Math.max(0, Math.min(1, (ev.clientX - box.left) / box.width));
      var y = Math.max(0, Math.min(1, (ev.clientY - box.top) / box.height));
      var d = this.mfDrag;
      this.mfPts = this.mfPts.map(function (p) {
        return (p.t === d.t && p.name === d.name)
          ? { t: p.t, name: p.name, label: p.label, x: x, y: y } : p;
      });
      this.mfDragMoved = true;
      return true;
    },
    /** 松手：真的移动过就作废旧结果、报一次坐标，并自动重算叠线 */
    mfDragEnd: function () {
      if (!this.mfDrag) return;
      var d = this.mfDrag, moved = this.mfDragMoved;
      this.mfDrag = null;
      this.mfDragMoved = false;
      if (!moved) return;
      var p = null;
      this.mfPts.forEach(function (q) { if (q.t === d.t && q.name === d.name) p = q; });
      this.showCourtOverlay = false;
      this.mfResult = null;
      this.mfVersion++;
      this.$message.success('已修正「' + (p ? p.label : d.name) + '」的位置' +
        (p ? (' → (' + p.x.toFixed(3) + ', ' + p.y.toFixed(3) + ')') : ''));
      this.scheduleAutoPreview();
    },
    /** 点/拖之后延迟自动解算一次（静默、不弹提示），只为把球场线立刻叠上去 */
    scheduleAutoPreview: function () {
      // 用户点「生成投影」才请求试算，点选期间不反复解码、计算。
      if (this.autoPreviewTimer) clearTimeout(this.autoPreviewTimer);
      this.autoPreviewTimer = null;
    },
    mfUndo: function () {
      // 「4 点试算」模式下点不在 mfPts 里（走 mfMiniPts），不单独处理的话
      // 页脚那个「撤销上一个点」在 4 点模式下就是个死按钮。
      if (this.courtMini) {
        var tm = this.mfClickTForActive();
        for (var k = this.mfMiniPts.length - 1; k >= 0; k--) {
          if (this.mfMiniPts[k].t === tm) {
            this.mfMiniPts.splice(k, 1);
            this.showCourtOverlay = false;
            this.mfResult = null;
            this.$message.success('已撤销这一幅的最后一个 4 点');
            return;
          }
        }
        this.$message.info('这一幅还没有点');
        return;
      }
      // 两个画面分开撤销：撤销要退的是**当前这个画面**上刚点的那一个
      if (this.mfDualSplit) {
        var t = this.mfActive === 1
          ? (this.mfCurrentRight ? this.mfCurrentRight.t : null)
          : (this.mfCurrent ? this.mfCurrent.t : null);
        var found = false;
        for (var i = this.mfPts.length - 1; i >= 0; i--) {
          if (this.mfPts[i].t === t) { this.mfPts.splice(i, 1); found = true; break; }
        }
        if (!found) this.$message.info(this.mfActive === 1 ? '右画面还没有点' : '左画面还没有点');
      } else if (this.mfPts.length) {
        this.mfPts.pop();
      }
      this.showCourtOverlay = false;
      this.mfResult = null;      // 撤销后旧结果失效
      this.mfVersion++;
      this.scheduleAutoPreview();
    },
    /** 清空 = 清掉**当前画面**上的点（想全清再点右边那个「全部清空」） */
    mfClear: function () {
      var self = this;
      if (this.mfDualSplit) {
        var t = this.mfActive === 1
          ? (this.mfCurrentRight ? this.mfCurrentRight.t : null)
          : (this.mfCurrent ? this.mfCurrent.t : null);
        var n = this.mfPts.length;
        this.mfPts = this.mfPts.filter(function (p) { return p.t !== t; });
        this.showCourtOverlay = false;
        this.mfTarget = '';
        this.mfResult = null;
        this.$message.success('已清空' + (this.mfActive === 1 ? '右' : '左') + '画面上的 ' +
          (n - this.mfPts.length) + ' 个点（另一边的点还在）');
        this.mfVersion++;
        this.scheduleAutoPreview();
        return;
      }
      this.mfPts = []; this.mfTarget = ''; this.mfResult = null; this.showCourtOverlay = false;
    },
    /** 全部清空（左右两边一起清） */
    mfClearAll: function () {
      this.mfPts = []; this.mfTarget = ''; this.mfResult = null; this.showCourtOverlay = false;
      this.$message.success('已清空所有画面上的点');
      this.mfVersion++;
      this.scheduleAutoPreview();
    },
    /* ---------------- 左右两个画面（各标一个半场） ---------------- */
    /** 某个画面（0=左 1=右）上已标的点（下面那份文字清单用） */
    mfFramePts: function (panel) {
      var f = panel === 1 ? this.mfCurrentRight : this.mfCurrent;
      var t = f ? f.t : null;
      return this.mfPts.filter(function (p) { return p.t === t; });
    },
    /** 切换"正在点哪个画面" —— 也可以直接在画面里点一下自动切 */
    setMfActive: function (i) {
      if (i === 1 && !this.mfCurrentRight) return;
      this.mfActive = i;
      this.syncCourtSideForActive();
      this.mfVersion++;   // 换画面 = 点位上下文变了，在途结果作废
    },
    /** 切换「左右两个画面 / 一张一张切」 */
    setDualView: function (v) {
      this.dualView = !!v;
      if (this.dualView) {
        this.mfActive = 0;
        if (this.mfFrames.length > 1 && this.mfIdx2 === this.mfIdx) {
          this.mfIdx2 = (this.mfIdx + 1) % this.mfFrames.length;
        }
        if (this.mfFrames.length < 2) {
          this.$message.info('现在左右两边是同一幅画面：拖动下面的原片到「看另一侧半场」' +
            '的那一刻，再按「把这帧放到右画面」，左右就各自一张了');
        }
        this.syncCourtSideForActive();
      }
    },
    /** 把某一幅已抽好的画面放到左/右画面（用户不用记"第几帧"） */
    assignToPanel: function (panel, idx) {
      idx = Number(idx);
      if (panel === 1) { this.mfIdx2 = idx; this.mfActive = 1; }
      else { this.mfIdx = idx; this.mfActive = 0; }
      var f = panel === 1 ? this.mfCurrentRight : this.mfCurrent;
      if (f && !(this.mfSideByT || {})[String(Number(f.t))]) {
        var initial = Object.assign({}, this.mfSideByT || {});
        initial[String(Number(f.t))] = panel === 1 ? 'right' : 'left';
        this.mfSideByT = initial;
      }
      this.syncCourtSideForActive();
      this.showCourtOverlay = false;
      this.mfResult = null;
    },
    /** 下拉框直接用的两个入口（面板号写死，模板里不必写内联函数） */
    setLeftFrame: function (idx) { this.assignToPanel(0, idx); },
    setRightFrame: function (idx) { this.assignToPanel(1, idx); },
    courtListFor: function (side) {
      var full = this.courtSideNames.full;
      var standard = this.courtStandard;
      return (this.courtSideNames[side] || full).map(function (it) {
        var detail = full.find(function (p) { return p.name === it.name; }) || {};
        var result = Object.assign({}, detail, it);
        if (standard === 'nba' && result.dst) {
          var g = {sx:15/15.24,sy:28/28.6512};
          var sign = /_near/.test(it.name) ? -1 : 1;
          var xsign = /_left$/.test(it.name) ? -1 : 1;
          if (/^lane_/.test(it.name)) result.dst = [xsign*2.4384*g.sx,sign*(14-5.7912*g.sy)];
          if (/^paint_base_/.test(it.name)) result.dst = [xsign*2.4384*g.sx,sign*14];
          if (/^ft_/.test(it.name)) result.dst = [0,sign*(14-5.7912*g.sy)];
          if (/^arc_/.test(it.name)) result.dst = [0,sign*(14-(1.6002+7.239)*g.sy)];
        }
        return result;
      });
    },
    /** 激活画面时恢复这张帧自己的半场清单。 */
    syncCourtSideForActive: function () {
      if (!this.mfFrames.length || !this.dualView) return;
      var f = this.mfActive === 1 ? this.mfCurrentRight : this.mfCurrent;
      if (!f) return;
      var side = this.frameCourtSide(f.t, this.mfActive);
      this.courtSide = side;
      this.courtItems = this.courtListFor(side);
      if (this.mfTarget && !this.courtItems.some(function (it) {
        return it.name === this.mfTarget;
      }, this)) this.mfTarget = '';
    },
    setPanelCourtSide: function (panel, side) {
      this.mfActive = panel === 1 ? 1 : 0;
      this.setCourtSide(side);
    },
    /** 右画面直接对着原片取一帧（"我看的是另一侧半场"那一刻） */
    addRightFrame: function () {
      var self = this;
      var keepLeftIdx = this.mfIdx;
      var el = this.$refs.markVideo;
      var t = (el && el.currentTime) ? el.currentTime : this.mfCenter;
      this.addFrameAtTime(t, function (tt) {
        // addFrameAtTime 默认把左面板指向新帧；恢复原左帧，避免两面板重合。
        self.mfIdx = keepLeftIdx;
        self.mfIdx2 = self.mfFrames.length - 1;
        self.mfActive = 1;
        var sides = Object.assign({}, self.mfSideByT || {});
        sides[String(Number(tt))] = 'left';
        self.mfSideByT = sides;
        self.syncCourtSideForActive();
        self.$message.success('右画面已换成 t=' + tt + 's 这一帧 —— 请核对端点并设为 A端或B端');
      });
    },
    /** 把已标的点整理成 /api/calibrate_multi 的入参：每幅画面各自一组。
     *
     *  左右两个画面的坐标各归各的，**不能混在一个 frames 项里** ——
     *  后端就是按 t 分组、逐帧拟合来判断"这幅画面自己够不够 4 个点"的。
     *  返回 null 表示拦下了（并已经把原因说给用户了），调用方直接 return。 */
    courtMultiPayload: function (silent) {
      var byT = {};
      this.mfPts.forEach(function (p) {
        byT[p.t] = byT[p.t] || { t: p.t, landmarks: {} };
        // 用 {value,label} 形式带上**界面上显示的名字**：后端点名诊断会原样回传，
        // 这样它说"最可疑的是「篮筐中心」"时，你能对上自己刚才按的那个按钮
        // （后端自己的措辞可能不一样，比如把这一侧的筐叫"另一端的篮筐中心"）。
        byT[p.t].landmarks[p.name] = { value: [p.x, p.y], label: p.label };
      });
      var frames = Object.keys(byT).map(function (k) { return byT[k]; });
      var solvable = 0, best = 0, bestT = null, okT = [];
      frames.forEach(function (f) {
        var n = Object.keys(f.landmarks || {}).length;
        if (n > best) { best = n; bestT = f.t; }
        if (n >= 4) { solvable += 1; okT.push(f.t); }
      });
      if (solvable === 0) {
        // 这是最常见的翻车点：点全撒在几幅画面上，**没有一幅凑够 4 个**。
        // 直接把话说透，别让用户对着"误差偏大"猜。
        var detail = frames.map(function (f) {
          return 't=' + f.t + 's 有 ' + Object.keys(f.landmarks || {}).length + ' 个';
        }).join('、');
        if (!silent) this.$message.warning('每一幅画面都不够 4 个点（' + (detail || '还没有点') +
          '）。单应矩阵要求**同一幅画面里至少 4 个点**：左边画面点够 4 个、右边画面再点够 4 个。');
        return null;
      }
      // 要得到完整球场坐标，A、B 两端必须各有独立的有效画面。
      if (!this.mfFullCourtReady) {
        if (!silent) this.$message.warning('还不能保存完整球场：A端、B端必须各有一幅至少 4 个地面点的画面。请在每幅画面上选对端点；同一端的相邻帧不能代替另一端。');
        return null;
      }
      var note = solvable > 1
        ? ('有 ' + solvable + ' 幅画面各自都够 4 个点，用其中点最多的那一幅（t=' +
           bestT + 's，' + best + ' 个点）解算')
        : ('只有 t=' + bestT + 's 那一幅画面够 4 个点，用它解算');
      return { frames: frames, note: note, solvable: solvable, best: best };
    },
    /** 保存并解算（多帧累加）
     *
     * two-step：`confirm:false` 先预览（不落盘），`confirm:true` 才保存并带 revision
     * 做乐观锁（移植自旧版标定页）。宽容规则在服务端：只拒绝了"数学上无意义"的
     * 退化点位和"篮筐投偏 >6m"；只点 4 个点、有点矛盾、篮筐偏 3~6m 都**允许保存**，
     * 但会标 position_unverified，位置结论（热区/战术图）由分析端关掉。 */
    /** 「只点 4 个点」模式：组装有序的 4 点并交给后端自动定向。
     *
     *  为什么单独走一条通道：点选**顺序**本身就是数据的一部分（它决定这 4 个点
     *  对应球场上的哪套地物），所以不能用 landmarks 字典那种按名字的写法 ——
     *  靠 JS 对象键的插入顺序传顺序太脆。
     */
    miniPayload: function () {
      var byT = {};
      this.mfMiniPts.forEach(function (p) {
        byT[p.t] = byT[p.t] || [];
        byT[p.t][p.seq - 1] = [p.x, p.y];
      });
      var frames = [];
      Object.keys(byT).forEach(function (k) {
        var pts = byT[k];
        // 必须正好 4 个、且不缺位
        var ok = pts.length === 4;
        for (var i = 0; i < 4; i++) { if (!pts[i]) { ok = false; } }
        if (ok) { frames.push({ t: Number(k), points: pts }); }
      });
      return frames;
    },
    /** 把标定解算的报错翻译成人话。
     *
     *  为什么需要：标定解算是重操作（抓帧 + 算投影线吻合度 + 跨镜头时定位切镜），
     *  请求被浏览器超时中断时，Promise 的报错原文是
     *  **"signal is aborted without reason"** —— 用户看到这行英文完全不知道
     *  发生了什么，只会以为"功能坏了"。
     */
    calibErrMsg: function (e) {
      var msg = (e && e.message) ? String(e.message) : String(e || '');
      if ((e && e.name === 'AbortError') ||
          /aborted|abort|signal is aborted/i.test(msg)) {
        return '后端算太久被浏览器中断了（不是标定点的问题）。'
          + '跨镜头标定要逐段解算，请稍后重试保存。'
          + '若反复超时，请确认后端窗口还在跑（没被关掉）。';
      }
      return msg || '未知错误';
    },
    /** 4 点模式的解算（confirm=false）/ 保存（confirm=true） */
    miniSolve: function (confirm) {
      var self = this;
      var frames = this.miniPayload();
      if (!frames.length) {
        this.$message.warning('需要**同一幅画面**上正好 4 个点（现在：' +
          this.mfMiniPts.length + ' 个）—— 少一个都解不出来');
        return;
      }
      this.markSaving = true;
      window.API.calibrateMulti({
        video_path: String(this.form.video_path).trim(),
        mini: true, mini_frames: frames,
        confirm: !!confirm,
        revision: (this.calInfo && this.calInfo.revision != null)
          ? this.calInfo.revision : null
      }).then(function (r) {
        self.markSaving = false;
        self.mfResult = r;
        self.mfPreviewed = !!(r && r.ok);
        self.refreshOverlay();
        var m = r && r.mini;
        if (r && r.ok && m && m.ok) {
          self.$message.warning('4 点试算仅供预览：' + m.which +
            '；吻合度不能证明点位对应正确，请切回命名地标标定后再保存');
        } else if (r && r.ok) {
          // 队友原文是"看下面的候选排名"，但两边模板都没渲染 mfResult.mini.ranked ——
          // 指向一个不存在的清单只会让人找。改成指向真的会出现的那个提示条。
          self.$message.warning('解出来了，但后端没给出自动定向的结果；看下面的提示条');
        } else {
          self.$message.warning('这份点法还不能用：' +
            String((r && r.note) || '').slice(0, 70));
        }
      }).catch(function (e) {
        self.markSaving = false;
        self.$message.error('解算失败：' + self.calibErrMsg(e));
      });
    },
    /** 当前正在点的那一幅画面的时刻（mini 模式用） */
    mfClickTForActive: function () {
      var f = (this.mfActive === 1) ? this.mfCurrentRight : this.mfCurrent;
      return f ? f.t : null;
    },
    /** 重点当前这一幅（清掉它的 4 个点） */
    miniClearHere: function () {
      var t = this.mfClickTForActive();
      this.mfMiniPts = this.mfMiniPts.filter(function (p) { return p.t !== t; });
      this.mfResult = null;
    },
    miniClearAll: function () {
      this.mfMiniPts = [];
      this.mfResult = null;
      this.$message.success('已清空 4 点');
    },
    previewCourtMulti: function (silent) {
      var self = this;
      // 「只点 4 点」模式：走 mini 通道（不给名字，后端自动定向）
      if (this.courtMini) { this.miniSolve(false); return; }
      if (!this.mfEnough) {
        if (silent) return;
        this.$message.warning('至少要点 4 个特征点（现在 ' + this.mfPts.length +
          ' 个）；左右画面各自至少 4 个才能解算，建议 5~6 个并分散到场地线上；最后仍要通过吻合度校验');
        return;
      }
      if (!window.API || !window.API.calibrateMulti) {
        if (!silent) this.$message.warning('接口还没就绪，稍后再试');
        return;
      }
      var got = this.courtMultiPayload(silent);
      if (!got) return;
      var ver = this.mfVersion;
      // A端和B端是球场两端各自的一幅画面，点名已经把它们映射到同一
      // 全场坐标系。不要再把相隔十几秒的两端画面逐帧链式配准：该过程
      // 会重复打开视频数十次并拖到浏览器超时；后端仍会分别校验每帧/镜头。
      var compensateFrames = !this.mfFullCourtReady;
      this.markSaving = true;
      window.API.calibrateMulti({
        video_path: String(this.form.video_path).trim(), frames: got.frames,
        court_model: this.courtStandard === 'nba' ? 'nba' : 'full',
        confirm: false, compensate: compensateFrames
      }).then(function (r) {
        self.markSaving = false;
        if (ver !== self.mfVersion) return;   // 期间点位/画面变了 → 这次结果作废
        self.mfResult = r;
        var fitRatio = r && r.calibration_fit && Number(r.calibration_fit.ratio);
        var rmse = r && r.rmse_m != null ? Number(r.rmse_m) : Infinity;
        self.mfPreviewed = !!(r && r.ok && rmse <= 1.5 &&
          isFinite(fitRatio) && fitRatio >= 1.25 &&
          !(r.calibration_fit.weak_segments || []).length);
        self.refreshOverlay();
        if (silent) return;
        if (self.mfPreviewed) {
          self.$message.success('预览通过：平均误差 ' + r.rmse_m + ' m' +
            (r.hoop_error_m != null ? ('，篮筐投影偏 ' + r.hoop_error_m + ' m') : '') +
            '（' + got.note + '）—— 确认投影贴合后再保存');
        } else {
          self.$message.warning('试算矩阵已生成，但尚未通过质量校验；误差 ' +
            (r && r.rmse_m != null ? r.rmse_m + 'm' : '未知') +
            '，吻合度 ' + (isFinite(fitRatio) ? fitRatio : '未知') + '。请看投影线并修正点位。');
        }
      }).catch(function (e) {
        self.markSaving = false;
        self.$message.error('解算失败：' + self.calibErrMsg(e));
      });
    },
    saveCourtMulti: function () {
      var self = this;
      // 「只点 4 点」模式：走 mini 通道保存（后端对 mini+confirm 直接 400，
      // 所以界面上 mini 模式把「保存」按钮藏起来了，这里是防御性入口）
      if (this.courtMini) { this.miniSolve(true); return; }
      if (!this.mfEnough) {
        this.$message.warning('至少要点 4 个特征点（现在 ' + this.mfPts.length +
          ' 个）；左右画面各自至少 4 个才能解算，建议 5~6 个并分散到场地线上；最后仍要通过吻合度校验');
        return;
      }
      var got = this.courtMultiPayload();
      if (!got) return;
      var ver2 = this.mfVersion;
      // 保存时由后端直接解算并检查地面标定。
      var compensateFrames = !this.mfFullCourtReady;
      this.markSaving = true;
      window.API.calibrateMulti({
        video_path: String(this.form.video_path).trim(), frames: got.frames,
        court_model: this.courtStandard === 'nba' ? 'nba' : 'full',
        confirm: true,
        compensate: compensateFrames,
        revision: (this.calInfo && this.calInfo.revision != null)
          ? this.calInfo.revision : null
      }).then(function (r) {
        self.markSaving = false;
        if (ver2 !== self.mfVersion) return;   // 同上：旧响应不覆盖新点位
        self.mfResult = r;
        if (r.saved) {
          if (r.position_unverified) {
            self.$message.warning('标定已保存，但位置结论会被判为**未校验**：' +
              String(r.note || '').slice(0, 80));
          } else {
            self.$message.success('标定成功：' + r.n_points + ' 个点 / ' +
              r.n_frames + ' 个画面，平均误差 ' + r.rmse_m + ' m（' + got.note +
              '）—— 分析时会自动使用');
          }
          self.loadCalInfo();
          self.markOpen = false;
        } else {
          self.$message.error('未保存：' + String(r.note || '点位不可用').slice(0, 90));
        }
      }).catch(function (e) {
        self.markSaving = false;
        self.$message.error('解算失败：' + self.calibErrMsg(e));
      });
    },
    /* ---------------- 标定自检：把算出来的球场线画回画面 ----------------
     *
     * 背景（实测争议）：用户标了 5 个点，界面说"误差 4.2m、有点互相矛盾"，
     * 用户觉得"我标得明显是对的"。而数学上 **5 个点里任取 4 个都能精确解出 H**
     * （误差恒为 0），所以那个数字本身不能证明谁对谁错。
     * 唯一能被肉眼验证的办法：把这份 H 算出来的球场线**投影回画面** ——
     * 对得上就是对，对不上错在哪一条线上一眼就看到。
     */
    /** 球场线折线（米）。双画面标定只投当前端的半场，避免把未观测的远端
     * 外推到画面里产生绕圈、交叉的假线；full 保留给单画面全场标定。 */
    _courtPolylines: function (side) {
      var lines = [];
      var i, x, y, pts, arc;
      var nba = this.courtStandard === 'nba';
      var sx = nba ? 15/15.24 : 1, sy = nba ? 28/28.6512 : 1;
      var lw = nba ? 2.4384*sx : 2.45, ft = nba ? 5.7912*sy : 5.8;
      var hoop = nba ? 1.6002*sy : 1.575;
      var rx = nba ? 7.239*sx : 6.75, ry = nba ? 7.239*sy : 6.75;
      var corner = nba ? 6.7056*sx : 6.6;
      var cx = nba ? 1.8288*sx : 1.8, cy = nba ? 1.8288*sy : 1.8;
      var halves = side === 'right' ? [1] : (side === 'left' ? [-1] : [-1, 1]);
      halves.forEach(function (sgn) {
        var baseY = sgn * 14, ftY = sgn * (14-ft);
        // 两条边线、底线和中线构成该端半场边界。
        [-7.5, 7.5].forEach(function (xx) {
          pts = [];
          for (var yy = 0; yy <= 14.01; yy += 0.5) pts.push([xx, sgn * yy]);
          lines.push(pts);
        });
        var baseline = [];
        for (var bx = -7.5; bx <= 7.51; bx += 0.25) baseline.push([bx, baseY]);
        lines.push(baseline);
        if (!side || side === 'full') {
          var midline = [];
          for (var mx = -7.5; mx <= 7.51; mx += 0.25) midline.push([mx, 0]);
          lines.push(midline);
        }
        // 罚球区侧线、罚球线和罚球圈。
        [-lw, lw].forEach(function (xx) {
          lines.push([[xx, baseY], [xx, ftY]]);
        });
        lines.push([[-lw, ftY], [lw, ftY]]);
        var circle = [];
        for (var j = 0; j <= 48; j++) {
          var a = j * Math.PI * 2 / 48;
          circle.push([cx * Math.cos(a), ftY + cy * Math.sin(a)]);
        }
        lines.push(circle);
        var yHoop = sgn * (14-hoop);
        [-corner, corner].forEach(function (xx) {
          var yEnd = yHoop - sgn * ry * Math.sqrt(1-xx*xx/(rx*rx));
          lines.push([[xx, baseY], [xx, yEnd]]);
        });
        arc = [];
        for (i = 0; i <= 64; i++) {
          x = -corner + 2*corner * i / 64;
          y = yHoop - sgn * ry * Math.sqrt(Math.max(0, 1-x*x/(rx*rx)));
          arc.push([x, y]);
        }
        lines.push(arc);
      });
      // 半场预览只画中圈落在本端的半圆；全场模式画完整中圈。
      var centerCircle = [];
      if (side === 'right' || side === 'left') {
        var start = side === 'right' ? 0 : Math.PI;
        for (i = 0; i <= 24; i++) {
          var halfAngle = start + Math.PI * i / 24;
          centerCircle.push([1.8 * Math.cos(halfAngle), 1.8 * Math.sin(halfAngle)]);
        }
      } else {
        for (i = 0; i <= 48; i++) {
          var ca = i * Math.PI * 2 / 48;
          centerCircle.push([1.8 * Math.cos(ca), 1.8 * Math.sin(ca)]);
        }
      }
      lines.push(centerCircle);
      return lines;
    },
    /** 求 3×3 单应矩阵的逆；不可逆时返回 null。
     *
     *  ⚠️ 标定 H 的方向是「**像素 → 球场米**」（后端 `apply_homography(H, src_px) ≈ dst_m`
     *  就是按这个方向拟合的）。凡是"把球场坐标画回画面"的地方（叠加线、画面外点名判断）
     *  都必须先用它的**逆**，不能直接拿 H 去乘球场点 —— 那是这个方向的反向使用，
     *  画出来的红线跟画面白线完全对不上（队友 d0247ee 实测：叠加自检一直不对就是这个原因）。 */
    _invertH: function (H) {
      if (!H || !H[0] || !H[1] || !H[2]) return null;
      var a = H[0][0], b = H[0][1], c = H[0][2];
      var d = H[1][0], e = H[1][1], f = H[1][2];
      var g = H[2][0], h = H[2][1], i = H[2][2];
      var det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g);
      if (!isFinite(det) || Math.abs(det) < 1e-12) return null;
      return [
        [(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det],
        [(f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det],
        [(d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det]
      ];
    },
    /** 用一份 H 把球场线投影到画面像素坐标（**纯函数**：不写任何状态） */
    _overlayLinesFor: function (H, W, Hh, side) {
      if (!H || !W || !Hh) return [];
      var inv = this._invertH(H);
      if (!inv) return [];
      var out = [];
      var clip = function (a, b) {
        var dx = b[0] - a[0], dy = b[1] - a[1], t0 = 0, t1 = 1;
        var p = [-dx, dx, -dy, dy], q = [a[0], W - a[0], a[1], Hh - a[1]];
        for (var k = 0; k < 4; k++) {
          if (Math.abs(p[k]) < 1e-12) { if (q[k] < 0) return null; continue; }
          var t = q[k] / p[k];
          if (p[k] < 0) t0 = Math.max(t0, t); else t1 = Math.min(t1, t);
          if (t0 > t1) return null;
        }
        return [[a[0] + t0 * dx, a[1] + t0 * dy],
                [a[0] + t1 * dx, a[1] + t1 * dy], t0, t1];
      };
      this._courtPolylines(side).forEach(function (line) {
        var run = [], prev = null;
        var flush = function () {
          if (run.length > 1) out.push(run);
          run = [];
        };
        line.forEach(function (p) {
          var x = p[0], y = p[1];
          var w = inv[2][0] * x + inv[2][1] * y + inv[2][2];
          if (!isFinite(w) || Math.abs(w) < 1e-9) { flush(); prev = null; return; }
          var u = (inv[0][0] * x + inv[0][1] * y + inv[0][2]) / w;
          var v = (inv[1][0] * x + inv[1][1] * y + inv[1][2]) / w;
          if (!isFinite(u) || !isFinite(v)) { flush(); prev = null; return; }
          var cur = { xy: [u, v], w: w,
            inside: u >= 0 && u <= W && v >= 0 && v <= Hh };
          if (prev) {
            // 单应分母过零代表投影穿过无穷远；绝不把无穷远两侧连成一条假对角线。
            if (prev.w * cur.w <= 0) flush();
            else {
              var seg = clip(prev.xy, cur.xy);
              if (!seg) flush();
              else {
                var start = seg[0], end = seg[1];
                var joins = run.length && prev.inside &&
                  Math.hypot(run[run.length - 1][0] - start[0],
                             run[run.length - 1][1] - start[1]) < 1.0;
                if (!joins) flush();
                if (!run.length) run.push(start);
                run.push(end);
                // 视野外的折线段单独截断，避免过滤点后跨空档错误连线。
                if (!prev.inside || !cur.inside) flush();
              }
            }
          }
          prev = cur;
        });
        flush();
      });
      return out;
    },
    /** 用一份 H 把球场线投影到画面像素坐标（写进默认的那一份叠线） */
    _buildOverlay: function (H, W, Hh) {
      this.overlayW = W;
      this.overlayH = Hh;
      this.overlayLines = this._overlayLinesFor(H, W, Hh, this.courtSide);
    },
    /** 前端自己判断"这份 H 是不是属于这一帧"，**不依赖后端多回任何字段**。
     *
     *  做法：用 H 把这一帧的点反投影到球场坐标，再看它离**这一帧自己的地标名**
     *  该在的球场坐标有多远（米）。属于它的那份 H 误差是厘米级，别的机位那份是米级
     *  —— 两者差两个数量级，用 0.75 m 判就够了，不会两边都命中或都不命中。
     *
     *  为什么不让后端直接告诉前端（它其实知道）：那是"响应里多一个字段"的耦合，
     *  而这里用**前端的原始数据**算，任何后端版本、任何返回格式都能自证，
     *  也不再出现"后端换了返回结构 → 叠线悄悄不画了"这种没法测的坏法。 */
    _HMatchesFrame: function (H, t) {
      if (!H || !this.courtSideNames) return false;
      var dstOf = {};
      this.courtListFor('full').forEach(function (it) { dstOf[it.name] = it.dst; });
      var pts = (this.mfPts || []).filter(function (p) { return p.t === t && dstOf[p.name]; });
      if (!pts.length) return false;
      var f = null;
      (this.mfFrames || []).forEach(function (x) { if (Number(x.t) === Number(t)) f = x; });
      var sz = this._frameSizeFor(f);
      var best = Infinity;
      for (var i = 0; i < pts.length; i++) {
        var g = this._applyH(H, pts[i].x, pts[i].y, sz[0], sz[1]);
        if (!g) continue;
        var d = dstOf[pts[i].name];
        var e = Math.sqrt(Math.pow(g[0] - d[0], 2) + Math.pow(g[1] - d[1], 2));
        if (e < best) best = e;
      }
      return best <= 0.75;
    },
    /** 像素（归一化 0~1）→ 球场米；H 的方向是「像素 → 球场」（与后端一致）。
     *  画面尺寸必须由调用方给：两帧的 w/h 可能不同（不同机位/不同码率），
     *  用错尺寸等于把点挪了位置，判定就会失效。 */
    _applyH: function (H, x, y, W, Hh) {
      if (!H || !H[0] || !H[1] || !H[2]) return null;
      W = W || this.frameW || 960;
      Hh = Hh || this.frameH || 540;
      var px = x * W, py = y * Hh;
      var w = H[2][0] * px + H[2][1] * py + H[2][2];
      if (!isFinite(w) || Math.abs(w) < 1e-12) return null;
      return [(H[0][0] * px + H[0][1] * py + H[0][2]) / w,
              (H[1][0] * px + H[1][1] * py + H[1][2]) / w];
    },
    /** 逐帧的 H 表（t → H）。两个来源：
     *   * `per_frame_fit`：单镜头那条路带回来的"每帧各自拟合"的 H；
     *   * `segments_H`：**多机位那条路**（顶层没有 H、per_frame_fit 也是空的）
     *     带回来的"每段一份 H"，按时间段认领。
     *  旧后端没有这两个字段也不影响 —— `_HForFrame` 会退回"按前端点判"。 */
    _perFrameHByT: function (r) {
      var byT = {};
      ((r && r.per_frame_fit) || []).forEach(function (f) {
        if (f && f.H && f.t != null) byT[Number(f.t)] = f.H;
      });
      return byT;
    },
    /** 某一帧落在哪一段里 → 那一段的 H（多机位路径用） */
    _segmentHForT: function (r, t) {
      if (t == null) return null;
      var segs = (r && r.segments_H) || [];
      var tt = Number(t);
      for (var i = 0; i < segs.length; i++) {
        var a = Number(segs[i].t_start), b = Number(segs[i].t_end);
        if (isFinite(a) && isFinite(b) && tt >= a - 1e-6 && tt <= b + 1e-6 && segs[i].H) {
          return segs[i].H;
        }
      }
      return null;
    },
    /** 某一帧该用哪份 H。
     *
     *  ① 顶层 H 就是这一帧解出来的（`best_frame_t`）→ 直接用它（最准，且与后端一致）；
     *  ② 后端给了"每段/每帧自己的 H"（`segments_H` / `per_frame_fit.H`）→ 按 t 认领。
     *     **多机位那条路顶层没有 H**，就是靠它才能"各画各的"；
     *  ③ 都没有（旧后端）→ 用前端的点反投影把这一帧认出来，认不出就**不画**。
     *     宁可这个画面不画线，也绝不把别的机位的线画上来 —— 那正是用户看到的
     *     "红框明显不对"（左边偏 20m、右边也压不到白线）。 */
    _HForFrame: function (r, t) {
      if (t == null) return null;
      var best = r && r.best_frame_t;
      if (best != null && Math.abs(Number(best) - Number(t)) < 1e-6 && r && r.H) {
        return r.H;
      }
      var Hseg = this._segmentHForT(r, t);
      if (Hseg) return Hseg;
      var byT = this._perFrameHByT(r);
      if (byT[Number(t)]) return byT[Number(t)];
      var H = r && r.H;
      if (H) {
        if (best == null || !(this.mfPts || []).length) return H;   // 单画面：就这一份
        if (this._HMatchesFrame(H, Number(t))) return H;
      }
      return null;
    },
    /** 某一帧的画面原始尺寸（像素），用于把叠线的 viewBox 对齐到那一张图 */
    _frameSizeFor: function (frame) {
      if (frame && frame.w && frame.h) return [frame.w, frame.h];
      return [this.markSize.w || 960, this.markSize.h || 540];
    },
    /** 预览/解算回来之后刷新自检叠加层。
     *
     *  ⚠️ 每个画面各算各的：左画面用左帧自己的 H、右画面用右帧自己的 H。
     *  以前这里只算一份、两个 `<svg>` 都渲染它 —— 于是"一个机位的线画到另一个机位上"，
     *  两边的红线都对不上画面里的白线（用户实测反馈："红框明显不对"）。 */
    refreshOverlay: function () {
      var r = this.mfResult || this.courtResult;
      // 「点吸附精修」被采纳时，存下来的标定用的是**吸附后的点**。
      // 所以画面上必须也把吸附后的位置画出来（空心黄圈），
      // 否则用户看到的点和他实际存下来的标定不一致 —— 会以为工具偷偷改了位置。
      var snapPts = null;
      var sn = r && r.snap;
      if (sn && sn.accepted && sn.landmarks) {
        var byT = {};
        (this.mfPts || []).forEach(function (p) {
          byT[p.t] = byT[p.t] || {};
          byT[p.t][p.name] = p;
        });
        snapPts = [];
        Object.keys(byT).forEach(function (tt) {
          Object.keys(byT[tt]).forEach(function (nm) {
            var v = sn.landmarks[nm];
            if (v) { snapPts.push({ t: Number(tt), name: nm, x: v[0], y: v[1] }); }
          });
        });
      }
      this.snapPts = snapPts || [];

      // 清空（含"关掉自检开关"、"点了新点还没算出来"）：绝不能留着上一轮的线
      this.overlayLines = [];
      this.overlayLinesLeft = [];
      this.overlayLinesRight = [];
      this.overlayW = 0; this.overlayH = 0;
      this.overlayWLeft = 0; this.overlayHLeft = 0;
      this.overlayWRight = 0; this.overlayHRight = 0;
      if (!this.showCourtOverlay || !r) return;

      // 1) 左画面 / 单画面（以前的路径原样保留：球场的点、拖拽、自动叠线都靠它）
      var tL = this.mfCurrent ? this.mfCurrent.t : null;
      var HL = this._HForFrame(r, tL);
      if (HL) {
        var sL = this._frameSizeFor(this.mfCurrent);
        var sideL = this.dualView ? this.frameCourtSide(tL, 0) : this.courtSide;
        this.overlayLinesLeft = this._overlayLinesFor(HL, sL[0], sL[1], sideL);
        this.overlayWLeft = sL[0];
        this.overlayHLeft = sL[1];
      }

      // 2) 右画面：只有它**确实是另一帧**时才单独算
      //    （同一帧时不重复算 —— 两个画面本来就画同一份线，那也是对的）
      if (this.mfDualSplit && this.mfCurrentRight) {
        var tR = this.mfCurrentRight.t;
        if (Number(tR) !== Number(tL)) {
          var HR = this._HForFrame(r, tR);
          if (HR) {
            var sR = this._frameSizeFor(this.mfCurrentRight);
            var sideR = this.frameCourtSide(tR, 1);
            this.overlayLinesRight = this._overlayLinesFor(HR, sR[0], sR[1], sideR);
            this.overlayWRight = sR[0];
            this.overlayHRight = sR[1];
          }
        }
      }

      // 3) 画面上真正渲染的那一份 = **这一帧的**（模板共用一套渲染代码）
      var t = this.mfActive === 1 ? this.mfCurrentRight : this.mfCurrent;
      var H = this._HForFrame(r, t ? t.t : null);
      if (H) {
        var s = this._frameSizeFor(t);
        var side = this.dualView ? this.frameCourtSide(t.t, this.mfActive) : this.courtSide;
        this.overlayLines = this._overlayLinesFor(H, s[0], s[1], side);
        this.overlayW = s[0];
        this.overlayH = s[1];
      } else if (!this.mfDualSplit) {
        // 单画面 + 后端只回了一份 H（老路径）：照旧用它，行为不变
        var H0 = r.H;
        if (H0) {
          var s0 = this._frameSizeFor(this.mfCurrent);
          this.overlayLines = this._overlayLinesFor(H0, s0[0], s0[1], this.courtSide);
          this.overlayW = s0[0];
          this.overlayH = s0[1];
        }
      }
    },
    toggleCourtOverlay: function () {
      if (!this.hasCourtProjection()) {
        this.$message.info('先标点并完成试算，才有球场投影可看');
        return;
      }
      this.showCourtOverlay = !this.showCourtOverlay;
      this.refreshOverlay();
    },
    generateCourtOverlay: function () {
      this.showCourtOverlay = true;
      this.mfResult = null;
      this.refreshOverlay();
      this.previewCourtMulti(false);
    },
    hasCourtProjection: function () {
      var r = this.mfResult || this.courtResult;
      return !!(r && (r.H || (r.mini && r.mini.H) ||
        (Array.isArray(r.per_frame_fit) && r.per_frame_fit.some(function (f) { return f && f.H; })) ||
        (Array.isArray(r.segments_H) && r.segments_H.some(function (s) { return s && s.H; }))));
    },
    /** 切换当前画面的半场地标表。
     *  B端映射 y<0/_near，A端映射 y>0/_far；双画面模式只清当前帧，
     *  保留另一幅图已经标好的半场。 */
    setCourtSide: function (side) {
      var next = (side === 'left' || side === 'right') ? side : 'full';
      var f = this.dualView && this.mfFrames.length
        ? (this.mfActive === 1 ? this.mfCurrentRight : this.mfCurrent) : null;
      var frameT = f ? f.t : null;
      var previous = f ? this.frameCourtSide(frameT, this.mfActive) : this.courtSide;
      if (f && previous !== next) {
        this.mfPts = this.mfPts.filter(function (p) { return p.t !== frameT; });
        var sideMap = Object.assign({}, this.mfSideByT || {});
        sideMap[String(Number(frameT))] = next;
        this.mfSideByT = sideMap;
        this.mfTarget = '';
        this.mfResult = null;
        this.showCourtOverlay = false;
        this.mfVersion++;
        this.$message.info('已切换当前画面的 A/B 端；这幅图的旧点已清除，另一幅画面的标点保留');
      } else if (!f && this.courtSide !== next && this.mfPts && this.mfPts.length) {
        this.mfPts = [];
        this.mfTarget = '';
        this.mfResult = null;
        this.showCourtOverlay = false;
        this.$message.info('已切换当前画面的 A/B 端；旧点已清空，因为两端对应不同球场坐标');
      }
      this.courtSide = next;
      this.courtItems = this.courtListFor(next);
      if (f) {
        var updated = Object.assign({}, this.mfSideByT || {});
        updated[String(Number(frameT))] = next;
        this.mfSideByT = updated;
      }
    },
    /** 用**指定时刻**的两帧装进左右画面（同一镜头才行）。
     *
     *  为什么要有这一条：标定页原来是"用户拖播放器 → 每边各加一帧"，
     *  很容易把两帧取在**不同镜头**上（实测 t=4.75s / t=58.5s，中间镜头切过），
     *  两帧不同机位 -> 合并解必然互相矛盾 -> 界面只会报"不在同一镜头/点互相矛盾"，
     *  用户根本不知道问题出在抽帧。现在由后端自动挑同一段镜头的首尾两帧。 */
    loadFramesAt: function (t1, t2) {
      var self = this;
      var v = String(this.form.video_path || '').trim();
      if (!v) { return; }
      this.markSaving = false;
      this.mfFrames = [];
      this.mfIdx = 0;
      this.mfIdx2 = 0;
      this.mfActive = 0;
      this.mfPts = [];
      this.mfSideByT = {};
      this.mfTarget = '';
      this.mfResult = null;
      // 换了两帧 → 上一轮的叠线（左右各一份）一律作废，否则新画面上会留着旧线
      this.overlayLines = [];
      this.overlayLinesLeft = [];
      this.overlayLinesRight = [];
      var version = ++this.mfVersion;
      var jobs = [[t1, 0], [t2, 1]];
      jobs.forEach(function (it) {
        var t = it[0], slot = it[1];
        window.API.getFrame(v, t).then(function (r) {
          if (version !== self.mfVersion || !self.markOpen) return;
          var fr = { t: Number(Number(t).toFixed(2)), w: r.w, h: r.h,
                     image: r.image, slot: slot };
          self.mfFrames.push(fr);
          if (self.mfFrames.length === 1) { self.mfIdx = 0; }
          if (self.mfFrames.length === 2) {
            // 按 slot 摆好：左画面 = 第一帧、右画面 = 第二帧
            self.mfFrames.sort(function (a, b) { return a.slot - b.slot; });
            self.mfIdx = 0;
            self.mfIdx2 = 1;
            var sides = {};
            // 两个面板按 A/B 端分别初始化，用户可按实际篮筐端点修改。
            sides[String(Number(self.mfFrames[0].t))] = 'right'; // A端（y>0）
            sides[String(Number(self.mfFrames[1].t))] = 'left';  // B端（y<0）
            self.mfSideByT = sides;
            self.mfActive = 0;
            self.syncCourtSideForActive();
            self.$message.info('已装好两帧（t=' + self.mfFrames[0].t +
              's / t=' + self.mfFrames[1].t + 's）。请核对每帧实际拍到的篮筐端点，分别设为 A端、B端后标点。');
          }
        }).catch(function (e) {
          if (version !== self.mfVersion || !self.markOpen) return;
          self.$message.error('取帧失败：' + (e && e.message ? e.message : e));
        });
      });
    },
    /** 自动挑"同一段镜头"的两帧（后端用 ORB 内点率判镜头有没有切） */
    pickStableFrames: function () {
      var self = this;
      var v = String(this.form.video_path || '').trim();
      if (!v) { return; }
      this.$message.info('正在判断镜头有没有切…');
      window.API.framesStable(v, 8).then(function (r) {
        if (!r || !r.ok) {
          self.$message.warning((r && r.note) || '没能自动认出连续镜头');
          return;
        }
        self.loadFramesAt(r.t1, r.t2);
        self.$message.success(r.note);
      }).catch(function (e) {
        self.$message.error('自动挑帧失败：' + (e && e.message ? e.message : e));
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
      if (this.markKind !== 'court' && this.hoopDragStart) {
        this.hoopDragCurrent = this.markEventPoint(ev);
        this.hoverPt = null;
        return;
      }
      // 拖动修正优先：按住了某个已标的点就实时改它的坐标，不再画准星
      if (this.mfDrag && this.mfDragMove(ev)) { this.hoverPt = null; return; }
      this.hoverPt = this.markEventPoint(ev, false);
    },
    markEventPoint: function (ev, clamp) {
      var el = ev.currentTarget;
      var box = el && el.getBoundingClientRect ? el.getBoundingClientRect() : null;
      if (!box || !box.width || !box.height) return null;
      var x = (ev.clientX - box.left) / box.width;
      var y = (ev.clientY - box.top) / box.height;
      if (clamp !== false) {
        x = Math.max(0, Math.min(1, x));
        y = Math.max(0, Math.min(1, y));
      } else if (x < 0 || x > 1 || y < 0 || y > 1) {
        return null;
      }
      return { x: x, y: y };
    },
    finishHoopDrag: function (ev) {
      if (!this.hoopDragStart) return;
      if (ev) this.hoopDragCurrent = this.markEventPoint(ev);
      var a = this.hoopDragStart, b = this.hoopDragCurrent;
      if (a && b && Math.abs(a.x-b.x) >= 0.002 && Math.abs(a.y-b.y) >= 0.002) {
        this.markPts = [
          { name:'rim_box_tl', label:'篮筐框', x:Math.min(a.x,b.x), y:Math.min(a.y,b.y) },
          { name:'rim_box_br', label:'', x:Math.max(a.x,b.x), y:Math.max(a.y,b.y) }
        ];
        this.markIdx = 2;
      }
      this.hoopDragStart = null;
      this.hoopDragCurrent = null;
      this.hoopSuppressClick = true;
    },
    onMarkLeave: function (ev) {
      this.hoverPt = null;
      if (this.markKind !== 'court' && this.hoopDragStart) this.finishHoopDrag(ev);
      this.mfDragEnd();
    },
    /** 关闭标定窗口：叠线与在途结果一律作废（否则关掉再打开会看到上一轮的线） */
    onMarkClosed: function () {
      this.hoopSession++;
      this.hoopPanelDrag = null;
      this.mfVersion++;
      this.overlayLines = [];
      this.overlayLinesLeft = [];    // 左右各一份，关窗时都要清（不然重开会看到上一轮的线）
      this.overlayLinesRight = [];
      this.hoverPt = null;
      this.mfDrag = null;
      this.hoopDragStart = null;
      this.hoopDragCurrent = null;
    },
    /** 画面上的按下/松开：按住已标的点 = 拖动修正；普通单击 = 新增（原有行为不变） */
    onMarkDown: function (ev) {
      if (this.markKind !== 'court') {
        var p = this.markEventPoint(ev);
        if (!p) return;
        this.markPts = [];
        this.markIdx = 0;
        this.hoopDragStart = p;
        this.hoopDragCurrent = p;
        this.hoopSuppressClick = false;
        if (ev.preventDefault) ev.preventDefault();
        return;
      }
      if (this.mfFrames.length) this.mfDragStart(ev);
    },
    onMarkUp: function (ev) {
      if (this.markKind !== 'court') { this.finishHoopDrag(ev); return; }
      this.mfDragEnd();
    },
    onMarkClick: function (ev) {
      if (this.markKind === 'court') { this.onCourtClick(ev); return; }
      // mouseup 后浏览器会再派发 click；框选已经在拖动结束时完成，这里只吞掉它。
      if (this.hoopSuppressClick) this.hoopSuppressClick = false;
    },
    markUndo: function () {
      if (this.markKind === 'court') { this.courtUndo(); return; }
      this.markPts = [];
      this.markIdx = 0;
      this.hoopDragStart = null;
      this.hoopDragCurrent = null;
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
      if (this.markKind === 'court') { this.saveCourt(); return; }
      if (this.markSaving) return;
      var self = this, sides = ['left','right'];
      if (!this.hoopPanels.left.box || !this.hoopPanels.right.box ||
          this.hoopPanels.left.loading || this.hoopPanels.right.loading) {
        this.$message.warning('请分别框选左右半场篮筐'); return;
      }
      // 串行合并两侧，避免两个写文件请求互相覆盖。
      var payloads = sides.map(function (side) {
        var panel = self.hoopPanels[side];
        return {video_path:String(self.form.video_path).trim(), at:panel.frameAt,
          landmarks:{}, hoop:panel.box.slice(), hoop_side:side};
      });
      this.markSaving = true;
      window.API.saveMarks(payloads[0]).then(function (r) {
        self.savedMarks = Object.assign({}, r.marks, {path:r.path});
        return window.API.saveMarks(payloads[1]);
      }).then(function (r) {
        self.savedMarks = Object.assign({}, r.marks, {path:r.path});
        self.markSaving = false;
        self.markOpen = false;
        self.$message.success('左右半场篮筐已保存');
      }).catch(function (e) {
        self.markSaving = false;
        self.$message.error('保存未完成，请重试：' + (e.message || e));
      });
    },
    clearMarks: function () {
      if (this.markKind === 'court') { this.courtPts = []; this.courtIdx = 0; return; }
      this.hoopPanels.left.box = null; this.hoopPanels.right.box = null;
      this.markPts = []; this.markIdx = 0;
      this.hoopDragStart = null; this.hoopDragCurrent = null;
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
    /** 拉取机器上现成的视频清单（示例素材 + 已上传）。 */
    loadSamples: function () {
      var self = this;
      window.API.samples().then(function (r) {
        self.samples = (r && r.samples) || [];
        if (!self.samplePick && self.samples.length) {
          self.samplePick = self.samples[0].path;
        }
      }).catch(function () { self.samples = []; });
    },
    loadSavedMarks: function () {
      var self = this;
      var v = String(this.form.video_path || '').trim();
      if (!v || !this.S.backendOk) { this.savedMarks = null; return; }
      window.API.getMarks(v).then(function (r) {
        self.savedMarks = (r && r.exists) ? Object.assign({}, r.marks, { path: r.path }) : null;
      }).catch(function () { self.savedMarks = null; });
    },
    /** 一键使用现成视频。 */
    useSample: function () {
      var p = this.samplePick || (this.samples[0] && this.samples[0].path);
      if (!p) {
        this.$message.warning('这台机器上没找到现成素材，请选一个本地文件上传');
        this.pickFile();
        return;
      }
      // 一定要填**绝对路径**：/api/samples 返回的就是绝对路径；
      // 手抄成相对路径（data\uploads\xxx.mp4）在浏览器/资源管理器里会解析到别的地方，
      // 表现是"路径不存在"（用户实测踩过）。
      this.form.source = 'video';
      this.form.video_path = p;
      this.loadCalInfo();
      this.loadSavedMarks();
      if (this.loadScoreboardEvents) { this.loadScoreboardEvents(); }
      this.$message.success('已选好视频：' + this.videoBaseName);
    },
    /** 把当前视频的绝对路径复制到剪贴板（给"想用别的播放器打开"的人用） */
    copyVideoPath: function () {
      var p = String(this.form.video_path || '');
      if (!p) { return; }
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(p);
          this.$message.success('已复制绝对路径：' + p);
          return;
        }
      } catch (e) { /* 下面兜底 */ }
      this.$message.info('绝对路径：' + p);
    },
    /** 四步主流程按钮分发。 */
    guideAct: function (st) {
      if (!st) { return; }
      if (st.key === 'video') {
        if (this.samples.length) { this.useSample(); } else { this.pickFile(); }
        return;
      }
      if (st.key === 'calib') { this.openCourt(); return; }
      if (st.key === 'hoop') { this.openMark(); return; }
      if (st.key === 'run') {
        var job = (this.S && this.S.job) || {};
        if (job.status === 'done') { location.hash = '#/overview'; return; }
        this.start();
      }
    },
    /** 选本地文件上传。 */
    pickFile: function () {
      var self = this;
      if (!this.S.backendOk) {
        this.$message.warning('服务暂不可用，恢复连接后再选择本地文件');
        return;
      }
      if (this.health && this.health.stale) {
        this.$message.warning('后端正在自动重启或仍载入旧代码，请等几秒后点「刷新」再上传');
        return;
      }
      if (this.uploadPct >= 0) { this.$message.info('视频正在上传，请等待完成'); return; }
      var input = document.createElement('input');
      input.type = 'file';
      input.accept = 'video/*';
      input.onchange = function () {
        var f = input.files && input.files[0];
        if (!f) return;
        if (self.localVideoUrl) URL.revokeObjectURL(self.localVideoUrl);
        self.localVideoUrl=URL.createObjectURL(f);
        self.localVideoPath='';
        self.fileName = f.name;
        self.form.video_path = '';
        self.savedMarks = null;
        self.calInfo = null;
        self.videoUrl = '';
        self.uploadPct = 0;
        self.log('POST /api/upload（x-filename=' + f.name + '，' + (f.size / 1048576).toFixed(1) + ' MB）');
        window.API.uploadVideo(f, function (p) { self.uploadPct = p; }).then(function (r) {
          self.uploadPct = -1;
          self.form.source = 'video';
          self.form.video_path = r.path;
          self.localVideoPath = r.path;
          self.loadCalInfo();
          self.loadSavedMarks();
          self.log('上传完成：' + r.path + '（' + r.bytes + ' 字节）');
          self.$message.success('视频上传完成，可以标定或开始分析');
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
        self.S.notice = '合成样例，仅供界面演示，不代表视频分析结果';
        self.$message.success('已载入合成演示数据');
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
      if (this.uploadPct >= 0) { this.$message.warning('请等待视频上传完成再开始分析'); return; }
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
        // 自动模式：能可靠读到比分牌得分事件时用于逐球匹配；没有比分牌时
        // 自然回退到球+篮筐视觉路径，不要求用户先配置 OCR。
        payload.score_policy = 'auto';
        // 快速模式只跳过球员检测；球、篮筐和可用比分牌仍会检查。
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
    // 旧版独立标定页（HoopAI 那套 /api/hoopai/court + /api/calibrate）已不在界面上出现：
    // 标定统一走下面那个多帧地标面板（与队友的 multical 一致）。
    // 文件 web/hoopai-calibration.html / .js 仍在磁盘上，需要时可以临时挂回来。
    // 顶端四步是本页唯一主流程；视频、球场和篮筐入口不在下方重复出现。
    '  <div class="card">',
    '    <div class="row" style="align-items:center;justify-content:space-between">',
    '      <h3 class="card-title" style="margin:0">4 步完成视频分析',
    '        <span class="sub">已完成 {{ guideDoneCount }}/4</span></h3>',
    '    </div>',
    '    <div class="grid grid-4" style="gap:10px">',
    '      <div v-for="st in guideSteps" :key="st.key" class="src-card" :class="{active: !st.done}">',
    '        <div class="t">{{ st.done ? \'✓\' : st.n }}. {{ st.title }}</div>',
    '        <div class="d" style="margin-bottom:8px">{{ st.desc }}</div>',
    '        <template v-if="st.key===\'video\'">',
    '          <el-select v-model="samplePick" size="small" style="width:100%;margin-bottom:8px" placeholder="选择示例视频" filterable>',
    '            <el-option v-for="s in samples" :key="s.path" :label="s.name" :value="s.path" />',
    '          </el-select>',
    '          <div class="row" style="gap:6px;flex-wrap:wrap">',
    '            <el-button size="small" @click="useSample" :disabled="uploadPct>=0 || !samples.length">用示例视频</el-button>',
    '            <el-button size="small" type="primary" plain :disabled="uploadPct>=0 || !S.backendOk || !!(health && health.stale)" @click="pickFile">选取本地文件</el-button>',
    '          </div>',
    '          <el-progress v-if="uploadPct>=0" :percentage="Math.round(uploadPct*100)" :stroke-width="7" style="margin-top:8px" />',
    '        </template>',
    '        <el-button v-else size="small" :type="st.done ? \'default\' : \'primary\'" :disabled="uploadPct>=0 || (st.key!==\'run\' && !hasVideoPath)" @click="guideAct(st)">{{ st.cta }}</el-button>',
    '      </div>',
    '    </div>',
    '    <p v-if="!S.backendOk" class="hint" style="color:#c45656;margin:10px 0 0">服务暂不可用，本页会自动重连</p>',
    '  </div>',
    '  <details class="card">',
    '    <summary>高级：用已有 JSONL 检测结果重跑统计</summary>',
    '    <div class="row" style="margin-top:12px;gap:8px">',
    '      <el-input v-model="form.video_path" @focus="form.source=\'jsonl\'" placeholder="已有 raw_track.json 的后端绝对路径" clearable />',
    '      <el-button size="small" @click="form.source=\'jsonl\'">使用 JSONL</el-button>',
    '    </div>',
    '  </details>',
    '  <div class="grid grid-2">',
    '    <div class="card">',
    '      <h3 class="card-title">分析设置</h3>',
    '      <el-form label-width="112px" label-position="left">',
    // 这里原来是「进球标注(可选)」输入框（要用户先准备一份 label_baskets.py 的产出当准绳）。
    // 用户反馈（2026-09-27）："本来就是一个投篮判定软件，却有一个进球标注的选项，这合适吗，
    // 你还不如在视频分析完以后加一个报错的选项" —— 那本质是开发/评测用的基准输入，
    // 不该出现在产品主流程里。人工纠错走「人工复核」页（判为命中/判为未中即时写回）。
    // （「训练标注」页已于 2026-10-05 下线；攒训练样本改用命令行 /api/label/* 接口。）
    // 后端 `basket_labels` 参数保留，供脚本/命令行使用。
    // 随机种子输入框也一并去掉了：它只对「合成演示比赛」生效，真实视频分析根本不用它
    // （视频管线里没有任何随机数），摆在主流程里只会让人以为"结果是编出来的"。
    // 合成入口已从界面移除，需要合成数据时用命令行：
    //   python -m aihoop.cli demo --seed 7 --duration 600 --out out/demo
    '        <el-form-item label="生成高光片段">',
    '          <el-switch v-model="form.make_highlights" />',
    '        </el-form-item>',
    '        <el-form-item v-if="form.source===\'video\'" label="快速模式">',
    '          <el-switch v-model="form.fast" />',
    '          <span class="hint" style="margin-left:10px"><copy-note label="说明">跳过球员检测，仍会检查篮球、篮筐和可用的比分牌线索；速度更快，但没有球员个体归属。</copy-note></span>',
    '        </el-form-item>',
    '      </el-form>',
    '      <div class="row">',
    '        <el-button @click="refreshJobs">刷新任务列表</el-button>',
    '      </div>',
    // 用户反馈（2026-09-27）："你还不如在视频分析完以后加一个报错的选项" ——
    // 纠错入口本来就有（人工复核页逐球改判、立刻写回比分/统计），但在这里没有指路，
    // 用户自然找不到。这里补一句去处说明，去掉的是"分析前先交一份标注"那种前置负担。
    '    </div>',
    '    <div class="card">',
    '      <h3 class="card-title">③ 分析进度</h3>',
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
    // 分析完成后给一个"判错了去哪儿改"的入口。「训练标注」模块已下线，
    // 「人工复核」是唯一的纠错入口 —— 界面上必须还找得到（test_ui_home.js 钉这条）。
    '        <div class="row" v-if="job.status===\'done\'" style="gap:8px;margin-top:10px">',
    '          <el-button size="small" type="primary" plain @click="goReview">去人工复核</el-button>',
    '          <el-button size="small" @click="goOverview">看结果总览</el-button>',
    '        </div>',
    '      </div>',
    '      <div class="stage-log" ref="logbox" style="margin-top:12px">',
    '        <div v-for="(l,i) in logs" :key="i">{{ l }}</div>',
    '      </div>',
    '    </div>',
    '  </div>',
    '  <div class="card" v-if="S.backendOk">',
    '    <h3 class="card-title">服务器历史任务 <span class="sub">所有登录用户共享 · 最近 20 条</span></h3>',
    '    <el-table :data="jobs" size="small" border empty-text="暂无任务">',
    '      <el-table-column prop="video_name" label="视频文件" min-width="220" show-overflow-tooltip />',
    '      <el-table-column label="数据来源" width="110">',
    '        <template #default="s">{{ {video:\'视频分析\',jsonl:\'导入记录\',synthetic:\'合成演示\'}[s.row.source] || \'来源未知\' }}</template>',
    '      </el-table-column>',
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
    '  <el-dialog v-model="markOpen" @closed="onMarkClosed" :title="markKind===\'court\' ? \'标球场：点场地特征点（4 个以上）\' : \'在画面上标篮筐\'" width="82%" top="4vh" :close-on-click-modal="false" :close-on-press-escape="!markSaving" :show-close="!markSaving">',
    '    <div v-if="markKind===\'court\'" class="row" style="margin-bottom:8px;gap:8px">',
    '      <el-button v-if="courtDraftAvailable" size="small" :disabled="markSaving" @click="restoreCourtDraft()">恢复标点草稿</el-button>',
    '      <el-button size="small" :disabled="markSaving" @click="$refs.courtDraftFile.click()">导入标点草稿</el-button>',
    '      <input ref="courtDraftFile" type="file" accept=".json" style="display:none" @change="importCourtDraft" />',
    '    </div>',
    '    <div v-if="markKind===\'court\'" class="mf-panels" style="margin-bottom:12px">',
    '      <div v-for="panel in [0,1]" :key="panel" class="mf-panel-wrap">',
    '        <b>{{ panel===0 ? \'左画面\' : \'右画面\' }}</b>',
    '        <video v-if="videoUrl" :ref="\'courtVideo_\'+panel" :src="videoUrl" controls preload="metadata" style="width:100%;max-height:26vh;background:var(--bg)" />',
    '        <el-button size="small" type="primary" :disabled="markSaving" @click="captureCourtPanel(panel)">{{ panel===0 ? \'选作左画面\' : \'选作右画面\' }}</el-button>',
    '      </div>',
    '    </div>',
    // 第一步：先说清「这件事要干到什么程度」——用户实测反馈"标完篮筐中心就不知道怎么办了"
    // ⚠️ 「4 点试算」模式下点名那套流程不适用，换一句"怎么标"（否则会教用户去选点名）
    '    <el-alert v-if="markKind===\'court\' && courtMini" type="info" :closable="false" show-icon style="margin-bottom:8px"',
    '      title="依次点罚球线两角、篮下两角，再试算（仅预览）" />',
    '    <el-alert v-else-if="markKind===\'court\'" type="info" :closable="false" title="A端、B端各标 5~6 个地面点" description="先确认 A/B 端，再选点名、点地面线角。" />',
    '    <p v-if="markKind===\'hoop\'" class="hint">左右半场由你指定：各自拖动视频选截图，再框篮筐。</p>',
    // 当前目标 + 实时反馈（点了几个、离"能保存"还差几个）
    // 条件必须用 guideNext（它是模式感知的）；用 markCurrent 的话，多帧模式下
    // courtCurrent 恒为真而 guideNext 为 null，模板会取 null.idx 直接报错。
    '    <el-alert v-if="markKind===\'court\' && guideNext" type="info" :closable="false" show-icon style="margin-bottom:8px"',
    '      :title="markKind===\'court\' ? (\'当前：\' + guideNext.label) : \'拖动框住篮筐\'" />',
    // 多帧模式还没选点名：明确说"先去下面的点名列表里选一个"（不能沿用 courtIdx，那永远停在第一个点名）。
    // 方位词必须对：这条 alert 在**点名按钮上方**，按钮在它下面。
    // 「4 点试算」模式下不需要选点名 → 不显示（否则会教用户去点没用的名字）
    '    <el-alert v-else-if="markKind===\'court\' && !courtMini" type="info" :closable="false" show-icon style="margin-bottom:8px"',
    '      title="先选点名，再点画面中的对应位置" />',
    // 球场模式下点不够 4 个的提示（4 点试算的点不在 mfPts 里，这条在这儿是假警报）
    '    <el-alert v-if="markKind===\'court\' && !courtMini && guideCount < 4" type="warning" :closable="false" show-icon style="margin-bottom:8px"',
    '      title="至少要 4 个点才能解出标定"',
    '      :description="\'左画面 \' + mfLeftCov.n + \' 个，右画面 \' + mfRightCov.n + \' 个\'" />',
    // 标定失败时的原因（重投影误差偏大 / 点位退化 / 解释不了画面里的真篮筐）
    '    <el-alert v-if="courtResult && !courtResult.usable" type="error" :closable="false" show-icon style="margin-bottom:8px"',
    "      :title=\"'标定结果不可用' + (courtResult.rmse_m != null ? ('（重投影误差 ' + courtResult.rmse_m + ' m）') : '')\"",
    '      :description="courtResult.note || \'点位可能有误：检查是否点在了正确的角/线上，或换一张更清楚的帧重新标。\'" />',
    // 多帧标定的结果与"未校验"提示（宽容规则：能存但位置结论会关掉）
    '    <el-alert v-if="markKind===\'court\' && mfResult" :type="(courtMini || mfResult.position_unverified) ? \'warning\' : (mfResult.ok ? \'success\' : \'error\')"',
    '      :closable="false" show-icon style="margin-bottom:8px"',
    '      :title="!mfResult.ok ? \'这份点法还不能用\' : (mfResult.saved ? \'标定已保存\' : \'尚未保存\')"',
    // 后端的多机位告警（`_multical_note`）在"哪一段不可信 + 去看叠加自检"后面还有一大段
    // 解释 —— 直接整段摆出来就是一条长句。做法：框里只留前面那段读数，全文折进「说明」。
    '      >{{ String(mfResult.note || \'\').slice(0, 200) }}',
    '      <copy-note v-if="!courtMini && String(mfResult.note || \'\').length > 200" label="说明">{{ mfResult.note }}</copy-note></el-alert>',
    // 逐点责任诊断：直接点名"哪个点跟其余对不上"。
    // 为什么必须有：以前只说"有 N 个点互相矛盾"，不说是哪个 —— 用户只能反复重标，
    // 最后怀疑软件本身（实测原话："我标点就说表的不对，你这个标定的代码真的准确吗"）。
    '    <el-alert v-if="markKind===\'court\' && !courtMini && mfResult && mfResult.point_diagnosis" type="warning" :closable="false" show-icon style="margin-bottom:6px"',
    '      title="逐点体检：这些点里哪个跟其余对不上"',
    '      :description="mfResult.point_diagnosis.note" />',
    '    <div v-if="markKind===\'court\' && !courtMini && mfResult && mfResult.point_diagnosis" class="row" style="flex-wrap:wrap;margin-bottom:6px">',
    '      <el-tag v-for="(r,i) in mfResult.point_diagnosis.rows" :key="\'pd\'+i" size="small" effect="plain" style="margin:2px"',
    '        :type="r.excused_err_m != null && r.excused_err_m > 3 ? \'danger\' : \'info\'">',
    '        {{ r.label }}：排除它后偏 {{ r.excused_err_m != null ? r.excused_err_m : \'?\' }} m（其余点平均 {{ r.others_mean_err_m != null ? r.others_mean_err_m : \'?\' }} m）</el-tag>',
    '    </div>',
    '    <div v-if="markKind===\'court\' && !courtMini && mfResult && (mfResult.worst || []).length" style="margin-bottom:8px">',
    '      <span class="hint">误差最大的几个点：</span>',
    '      <el-tag v-for="(w,i) in mfResult.worst" :key="\'w\'+i" size="small" type="warning" effect="plain" style="margin:2px">',
    '        {{ w.label }} @{{ w.t }}s → {{ w.err_m }} m（像素 {{ w.px[0] }},{{ w.px[1] }}）</el-tag>',
    '    </div>',
    // 不在标定画面绘制自动矩阵；本项目视频的低吻合度候选曾被误认为可信标定。
    // 把"通过校验"的客观读数摆出来。为什么必须显式给数字：
    // 分析端有一道硬门槛（投影线与画面白线的吻合度 ratio ≥1.25），
    // 达不到就**不生成战术图/热图**。以前界面只说"标定可用"，用户存下去才发现
    // 战术图是空的，完全对不上账（实测踩到：AI 自己标的点 ratio 只有 0.32）。
    '    <el-alert v-if="markKind===\'court\' && !courtMini && mfResult && mfResult.calibration_fit" :closable="false" show-icon style="margin-bottom:6px"',
    '      :type="fitRatio >= 1.25 ? \'success\' : \'warning\'"',
    // 标题里必须写清"这是**最差那一段**的读数"：分时段标定（两个机位各一份 H）
    // 时只显示一个数字，用户会以为整份都差 —— 实测就卡在这（"那条 0.17 是怎么来的"）。
    '      :title="(fitIsWorstOfSegments ? \'吻合度读数（分时段，取最差的一段）：\' : \'吻合度读数：\') + (mfResult.calibration_fit.ratio != null ? mfResult.calibration_fit.ratio : \'—\') + \'（门槛 1.25）\' + (fitRatio >= 1.25 ? \' —— 这份标定会被分析端接受，战术图/热图能出\' : \' —— 太低，分析端会拒收：战术图、热图、2/3 分区分都不会生成（只判进球）\')"',
    '      description="白线对比分数不是准确率；请结合当前截图、投影线与点位误差核对。" />',
    // 分时段标定：**逐段**把吻合度摆出来。
    // 为什么必须有（用户实测反馈）：每一段各解一份 H，只报一个"最差 0.17"看不出
    // "是整份都差，还是只有那一段差" —— 于是要么以为工具坏了、要么白重标一遍。
    '    <div v-if="markKind===\'court\' && fitSegRows.length" class="row" style="flex-wrap:wrap;align-items:center;gap:6px;margin-bottom:6px">',
    '      <span class="hint">逐段读数：</span>',
    '      <el-tag v-for="(s,i) in fitSegRows" :key="\'fs\'+i" size="small" effect="plain"',
    '        :type="s.ok ? \'success\' : \'danger\'">',
    '        {{ s.when }}：吻合度 {{ s.ratio != null ? s.ratio : \'—\' }}{{ s.ok ? \' ✓\' : \' ✗\' }}（{{ s.n }} 点）',
    '      </el-tag>',
    '      <copy-note label="说明">这一段视频里镜头/机位切过，所以**每一段各解一份标定**（两个机位没有共同坐标系，硬合成一份必然互相矛盾）。上面的总读数取的是**最差那一段** —— 只要有一段不过门槛，那段时间的位置结论（热区/战术图）就不可信，但其它段是好的、不用重标整份。</copy-note>',
    '    </div>',
    // 「点吸附精修」的结果：采纳了没有（+ 后端给的原因）。
    // 为什么必须显式区分"采纳/没采纳"：护栏拒绝时点集**根本没动**，
    // 若只显示一个"已精修"的绿条，用户会以为点被改过（实测这机位就会被拒）。
    '    <el-alert v-if="markKind===\'court\' && mfResult && mfResult.snap && mfResult.snap.note" :closable="false" show-icon style="margin-bottom:6px"',
    '      :type="mfResult.snap.accepted ? \'success\' : \'info\'"',
    '      :title="(mfResult.snap.accepted ? \'点吸附精修：已采纳（画面上的空心黄圈就是存下来的位置）—— \' : \'点吸附精修：没采纳（保留你自己标的点）—— \') + mfResult.snap.note">',
    '      <copy-note label="说明">工具会试着把你标的点吸附到画面里的球场线上（位移上限 12 像素），只有在结果几何上仍像球场时才采纳；被拒不是出错 —— 机位太正对球场时单应矩阵本身就病态，点挪几个像素就能让吻合度虚高，那种解一律不用。</copy-note></el-alert>',
    // 多机位：**哪几段不可信**逐段摆出来。
    // 为什么必须有：多机位每一段各解一份 H，坏的那一段以前被"取最好的一段"盖住，
    // 界面照样说"标定可用" —— 用户看到的是"战术图过了一分钟就乱码"（实测）。
    // 上面的吻合度读数已经是**最差那一段**的值；这里说清坏在哪一段时间、坏成什么样。
    // 详细怎么看（开叠加层、红线压不压在白线上）折进「说明」，不占页面篇幅。
    '    <div v-if="markKind===\'court\' && mfResult && weakSegs.length" class="row" style="flex-wrap:wrap;align-items:center;margin-bottom:6px">',
    '      <span class="hint">这些时间段不可信：<copy-note label="说明">分段标定中每个镜头各解一份矩阵，只要有一段不可信，那段时间的位置结论（热区、战术图、球场坐标）就不可信。根据下方的时间段，重新抽取该镜头的清晰画面，把至少 4 个分散的地面点重新点准；红色矩阵不显示。</copy-note></span>',
    '      <el-tag v-for="(s,i) in weakSegs" :key="\'ws\'+i" size="small" type="danger" effect="plain" style="margin:2px">',
    '        {{ s.from }}–{{ s.to }}s：{{ s.why }}（吻合度 {{ s.ratio }} · 误差 {{ s.rmse_m }} m）{{ s.diagnostic && s.diagnostic.suspect_name ? \'；疑点「\' + s.diagnostic.suspect_name + \'」，移除后吻合度 \' + s.diagnostic.ratio_without_point : \'\' }}</el-tag>',
    '    </div>',
    // 外层盒子宽度 = min(100%, 画面宽)；图片 width:100% 撑满它。
    // 这样"图片显示尺寸"和"定位容器尺寸"严格相等，绿圈才会落在鼠标点上。
    // ---- 球场模式：画面切换 + 特征点选择（多画面累加）----
    '    <div v-if="markKind===\'court\' && mfFrames.length" style="margin-bottom:8px">',
    // 一句总纲：这件事现在是「左右两个画面各自标一个半场」
    '      <div class="row" style="align-items:center;gap:10px;margin-bottom:6px;flex-wrap:wrap">',
    '        <span class="hint">两幅画面分别标点</span>',
    '        <span style="margin-left:16px">球场规格：</span>',
    '        <el-radio-group v-model="courtStandard" size="small"><el-radio-button value="fiba">FIBA</el-radio-button><el-radio-button value="nba">NBA</el-radio-button></el-radio-group>',
    '      </div>',
    '      <div class="row" style="gap:12px;margin-bottom:8px;flex-wrap:wrap">',
    '        <div v-for="panel in [0,1]" :key="panel" class="row" style="gap:8px">',
    '          <b>{{ panel===0 ? \'左画面\' : \'右画面\' }}</b>',
    '          <el-radio-group :model-value="frameCourtSide(panel===0 ? mfCurrent.t : mfCurrentRight.t,panel)" size="small" @change="setPanelCourtSide(panel,$event)">',
    '            <el-radio-button label="right">A端</el-radio-button><el-radio-button label="left">B端</el-radio-button>',
    '          </el-radio-group>',
    '        </div>',
    '      </div>',
    // 「点名表列哪些点」选一次：默认全场 A端/B端 15 个地标（同一个物理地标在两幅
    // 画面里同名），也能临时只列某一侧半场的 6 个点（机位只拍得到半场时更清爽）。
    '      <div v-if="!dualView" class="row" style="align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap">',
    '        <span class="hint">当前画面对应端点：</span>',
    '        <el-radio-group :model-value="courtSide" size="small" @change="setCourtSide">',
    '          <el-radio-button label="full">全场（A端/B端）</el-radio-button>',
    '          <el-radio-button label="left">只看B端</el-radio-button>',
    '          <el-radio-button label="right">只看A端</el-radio-button>',
    '        </el-radio-group>',
    '      </div>',
    // 球场的点名列表（篮筐模式没有这一排：中心是唯一必点项）
    '      <div class="row" style="flex-wrap:wrap">',
    '        <el-button v-for="it in courtItems" :key="it.name" size="small"',
    '          :type="mfTarget===it.name ? \'primary\' : (mfDone[it.name] ? \'success\' : \'default\')"',
    '          :plain="mfTarget!==it.name" @click="mfPick(it)">',
    '          {{ mfDone[it.name] ? \'✓ \' : \'\' }}{{ it.label }}</el-button>',
    '      </div>',
    // 兼容旧版模板结构；新流程直接用两个角框出篮筐，不再有可选边缘按钮。
    '      <div v-if="markKind===\'hoop\' && markItemsOptional.length" class="row" style="flex-wrap:wrap;margin-top:2px">',
    '        <el-button v-for="it in markItemsOptional" :key="it.name" size="small"',
    '          :type="hoopOptTarget===it.name ? \'primary\' : (hoopOptDone[it.name] ? \'success\' : \'default\')"',
    '          :plain="hoopOptTarget!==it.name"',
    '          @click="hoopOptTarget = (hoopOptTarget===it.name ? \'\' : it.name)">',
    '          {{ hoopOptDone[it.name] ? \'✓ \' : \'\' }}{{ it.label }}</el-button>',
    '        <span class="hint" v-if="hoopOptTarget">现在去画面里点：{{ hoopOptTarget }}</span>',
    '      </div>',
    '      <div class="hint" v-if="mfTarget" style="margin-top:6px;color:#409eff">',
    '        现在去画面里点：<b>{{ guideNext ? guideNext.label : mfTarget }}</b> —— 选中的那一个高亮；',
    '        同一个名字可以在两幅画面里各点一次（各自独立记录）</div>',
      // 点完之后**必须留下"下一步"**：原来 mfTarget 一被清空，上一句就消失了，
      // 屏幕上只剩一排点名按钮 —— 用户就卡在"标完篮筐中心不知道怎么办"（实测反馈）。
      '      <div class="hint" v-else style="margin-top:6px;color:#409eff">',
      '        下一步：选一个点名 → 到画面里点它。现在：',
      '        左画面 {{ mfLeftCov.n }} 个{{ mfLeftCov.enough ? \'（够了）\' : \'（还差 \' + (4 - mfLeftCov.n) + \' 个）\' }}、',
      '        右画面 {{ mfRightCov.n }} 个{{ mfRightCov.enough ? \'（够了）\' : \'（还差 \' + (4 - mfRightCov.n) + \' 个）\' }}。',
      '        标完后点击「保存标定」。</div>',
    // 每幅画面各自的覆盖度：哪一边还差、点是不是挤在一条线上，一眼看到
    '      <div class="row" style="flex-wrap:wrap;align-items:center;margin-top:6px">',
    '        <span class="hint">每幅画面的覆盖度：</span>',
    '        <el-tag v-for="(f,i) in mfFrameCov" :key="\'cov\'+i" size="small" style="margin:2px"',
    '          :type="f.enough ? (f.spread ? \'success\' : \'warning\') : \'info\'" effect="plain"',
    '          :title="f.enough ? (f.spread ? \'这幅画面自己就能解算\' : \'点数够了，但点挤在一条线上 —— 再往别处点一下\') : \'这幅画面还差 \' + (4 - f.n) + \' 个点（别的画面的点补不上）\'">',
    '          第{{ f.idx+1 }}幅 t={{ f.t }}s · {{ f.n }}点{{ f.enough ? (f.spread ? \' ✓可解\' : \' ⚠太集中\') : \' ✗不够\' }}</el-tag>',
    '      </div>',
    // 画面外点名提示：解出一份 H 之后就能算出"每个特征点会落在画面哪里"。
    // 有些点名（比如另一侧的底线角）在这台机位的画面里**根本看不见**，
    // 用户硬点也只能是猜 —— 实测踩过（用户把"底线右角"点成了罚球区右角）。
    '      <el-alert v-if="!courtMini && offFrameNames.length" type="warning" :closable="false" show-icon style="margin-top:6px"',
    '        :title="\'有 \' + offFrameNames.length + \' 个点，在你这两幅画面里**根本看不见**：\' + offFrameNames.join(\'、\')"',
    '        description="重标时跳过画面外的点，改点画面里看得清的地面交点。不要猜被遮挡的角点；标完后直接保存。" />',
    '      <el-alert v-if="mfResult && !mfResult.ok" type="error" :closable="false" show-icon style="margin-top:8px"',
    '        :title="mfResult.note ? String(mfResult.note).slice(0, 120) : (\'标定误差偏大（平均 \' + mfResult.rmse_m + \' m）\')"',
    '        :description="\'最离群的几个点：\' + (mfResult.worst || []).map(function(d){return (d.label || d.name || \'?\') + \'(t=\' + d.t + \'s, \' + d.err_m + \'m)\'}).join(\'，\')" />',
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
    '      <div v-if="!courtMini && mfResult && mfResult.per_frame_fit" style="margin-top:8px">',
    '        <div class="hint">各画面单独拟合的结果（能标定的画面会标绿）：</div>',
    '        <div class="row" style="flex-wrap:wrap;margin-top:4px">',
    '          <el-tag v-for="fr in mfResult.per_frame_fit" :key="fr.t" size="small"',
    '            :type="fr.ok ? \'success\' : (fr.n >= 4 ? \'warning\' : \'info\')" effect="plain" style="margin:2px">',
    '            t={{ fr.t }}s · {{ fr.n }}点 · {{ fr.rmse_m === null ? \'—\' : fr.rmse_m + \'m\' }}</el-tag>',
    '        </div>',
    '        <div v-for="fr in mfResult.per_frame_fit" :key="\'why\'+fr.t" class="hint" style="margin-top:4px" :style="{color: fr.ok ? \'#67c23a\' : \'#fbbf24\'}">',
    '          t={{ fr.t }}s：{{ fr.note }}</div>',
    '      </div>',
    '      <el-alert v-else-if="!courtMini && mfResult && mfResult.ok" type="success" :closable="false" show-icon style="margin-top:8px"',
    '        :title="(mfResult.saved ? \'标定已保存：平均误差 \' : \'尚未保存：平均误差 \') + mfResult.rmse_m + \' m\'"',
    '        ><copy-note label="说明">保存后会用于这段视频的位置分析。</copy-note></el-alert>',
    '    </div>',
    // 画面（球场模式用抽帧图，篮筐模式用取帧图）
    // 两个画面模式下：左画面 + 右画面并排。**每张图各自记自己那一半场地的点** ——
    // 这就是用户要的"分两个画面点，一个画面点左半场、一个画面点右半场"。
    '    <div :class="markKind===\'court\' && mfDualSplit ? \'mf-panels\' : \'\'">',
    // 篮筐模式必须有自己的「取帧图」面板。这里以前只给球场模式画了图（下面那个
    // markKind==='court' 的 div），篮筐模式就只剩上面那个原片播放器 ——
    // 用户实际看到的就是"点进去有视频，但没有下面截帧，我没法点篮筐"（2026-10-05 实测）。
    // 取帧接口一直是好的（GET /api/frame 200），图早就存在 markImg 里，只是从来没人渲染它。
    '      <div v-if="markKind===\'hoop\'" class="row" style="margin-bottom:8px"><el-button size="small" :disabled="markSaving || hoopPanels.left.loading || hoopPanels.right.loading" @click="swapHoopPanels">交换左右截图</el-button></div>',
    '      <div v-if="markKind===\'hoop\'" class="mf-panels">',
    '        <div v-for="side in [\'left\',\'right\']" :key="side" class="mf-panel-wrap">',
    '          <div class="row" style="gap:8px;margin-bottom:8px;flex-wrap:wrap">',
    '            <b>{{ side===\'left\' ? \'左半场\' : \'右半场\' }}</b>',
    '            <el-tag size="small" :type="hoopPanels[side].box ? \'success\' : \'info\'">{{ hoopPanels[side].restored ? \'已保存框\' : (hoopPanels[side].box ? \'已框选\' : \'待框选\') }}</el-tag>',
    '            <el-input-number v-model="hoopPanels[side].at" @change="seekHoopPanel(side,$event)" :min="0" :step="0.5" :precision="2" size="small" :disabled="markSaving" style="width:125px" />',
    '            <el-button size="small" :disabled="markSaving" :loading="hoopPanels[side].loading" @click="captureHoopPanel(side)">取当前画面</el-button>',
    '          </div>',
    '          <video v-if="videoUrl" :ref="\'hoopVideo_\'+side" :src="videoUrl" controls preload="metadata"',
    '            @loadedmetadata="$event.target.currentTime=hoopPanels[side].at" @timeupdate="hoopVideoTime(side,$event)" style="width:100%;max-height:26vh;background:var(--bg);margin-bottom:8px" />',
    '          <div style="position:relative;cursor:crosshair;user-select:none"',
    '            @mousedown="hoopPanelDown(side,$event)" @mousemove="hoopPanelMove(side,$event)"',
    '            @mouseup="hoopPanelUp(side,$event)" @mouseleave="hoopPanelUp(side,$event)">',
    '            <img v-if="hoopPanels[side].image" :src="hoopPanels[side].image" draggable="false" style="width:100%;display:block;border-radius:6px" />',
    '            <div v-else class="muted" style="padding:60px 12px;text-align:center;background:var(--bg)">{{ hoopPanels[side].loading ? \'正在取帧…\' : \'拖动上方视频，选取这一侧截图\' }}</div>',
    '            <div v-if="hoopPanels[side].box" :style="hoopPanelStyle(hoopPanels[side].box)" style="position:absolute;pointer-events:none;border:2px solid #22c55e;box-sizing:border-box"></div>',
    '          </div>',
    '        </div>',
    '      </div>',
    '      <div v-if="markKind===\'court\'" class="mf-panel-wrap"',
    '           :class="{ on: !mfDualSplit || mfActive===0 }" data-side="0"',
    '           style="position:relative;width:100%;max-width:1100px;cursor:crosshair"',
    '           @click="onMarkClick" @mousemove="onMarkMove" @mouseleave="onMarkLeave"',
    '           @mousedown="onMarkDown" @mouseup="onMarkUp">',
    '        <img v-if="mfCurrent && mfCurrent.image" :src="mfCurrent.image" style="width:100%;height:auto;display:block;border-radius:var(--r-sm)" />',
    '        <div v-else class="muted" style="padding:40px">在上方播放器选好画面，再点击「选作左画面」</div>',
    '        <div v-if="mfDualSplit" class="mf-badge">左画面{{ mfActive===0 ? \'（正在点这里）\' : \'\' }}</div>',
    // 已点的标记（两种模式都画：篮筐模式画 markPts/activePts；
    // 球场模式**左画面画 mfPtsHere、右画面画 mfPtsRight** ——
    // 以前两边都用 activePts（=只认左帧），于是右画面的点会让左画面"看起来消失"）
    '        <svg v-if="frameW && frameH" :viewBox="\'0 0 \' + frameW + \' \' + frameH"',
    '             preserveAspectRatio="none"',
    '             style="position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none">',
    '          <g v-if="hoverPt && (markKind!==\'court\' || !mfDualSplit || mfActive===0)">',
    '            <line :x1="hoverPt.x*frameW - 22" :y1="hoverPt.y*frameH" :x2="hoverPt.x*frameW + 22" :y2="hoverPt.y*frameH" stroke="#f59e0b" :stroke-width="Math.max(1.5, frameW*0.0022)" />',
    '            <line :x1="hoverPt.x*frameW" :y1="hoverPt.y*frameH - 22" :x2="hoverPt.x*frameW" :y2="hoverPt.y*frameH + 22" stroke="#f59e0b" :stroke-width="Math.max(1.5, frameW*0.0022)" />',
    '          </g>',
    '          <template v-for="(p,i) in mfPtsHere" :key="i">',
    '            <circle :cx="p.x * frameW" :cy="p.y * frameH" :r="Math.max(10, frameW*0.012)"',
    '                    fill="rgba(34,197,94,.35)" stroke="#22c55e" :stroke-width="Math.max(2, frameW*0.003)" />',
    '            <text :x="p.x * frameW + Math.max(12, frameW*0.014)" :y="p.y * frameH"',
    '                  fill="#22c55e" :font-size="Math.max(16, frameW*0.022)"',
    '                  style="paint-order:stroke;stroke:#000;stroke-width:3px">{{ i + 1 }}. {{ p.label }}</text>',
    '          </template>',
    // 「只点 4 个点」模式：把点选顺序画出来（编号 1..4），用户才能确认顺序对不对。
    // 用**绿色**（和点名模式一致）—— 用户已经习惯"绿圈=我点上了"，换成别的颜色
    // 会被当成"没点上"（实测反馈："为什么点完点之后没有绿圈提示了"）。
    '          <template v-for="(p,i) in miniPtsHere" :key="\'M\'+i">',
    '            <circle :cx="p.x * frameW" :cy="p.y * frameH" :r="Math.max(11, frameW*0.013)"',
    '                    fill="rgba(34,197,94,.35)" stroke="#22c55e" :stroke-width="Math.max(2, frameW*0.0035)" />',
    '            <text :x="p.x * frameW + Math.max(13, frameW*0.015)" :y="p.y * frameH"',
    '                  fill="#22c55e" :font-size="Math.max(18, frameW*0.024)"',
    '                  style="paint-order:stroke;stroke:#000;stroke-width:3px">{{ p.seq }}</text>',
    '          </template>',
    // 精修被采纳时，把"吸附后"的点也画出来（空心黄圈）——存下来的标定用的是它
    '          <template v-for="(p,i) in snapPtsHere" :key="\'S\'+i">',
    '            <circle :cx="p.x * frameW" :cy="p.y * frameH" :r="Math.max(11, frameW*0.013)"',
    '                    fill="none" stroke="#f59e0b" :stroke-width="Math.max(2, frameW*0.0035)"',
    '                    stroke-dasharray="4 3" />',
    '          </template>',
    // 标定自检：把这份 H 算出来的球场线画回画面（对不上就是对不上，一眼可见）
    // ⚠️ 用的是**左画面自己那一帧的 H**（overlayLinesLeft）—— 右画面有它自己的一份，
    // 见下面右画面的模板。两个画面共用一个 overlayLines 会把一个机位的线画到另一个上。

    '        </svg>',
    // 这里原来还有一段「篮圈示意（只在篮筐模式）」的 div，但它在
    // `v-if="markKind==='court'"` 的面板里 —— 篮筐模式下这个面板根本不渲染，
    // 那段代码永远执行不到。已删掉，篮圈示意现在真的画在篮筐模式的面板上（见上）。
    '      </div>',
    // 右画面：自己的坐标系、自己的点（另一侧半场）
    '      <div v-if="markKind===\'court\' && mfDualSplit" class="mf-panel-wrap"',
    '           :class="{ on: mfActive===1 }" data-side="1"',
    '           style="position:relative;width:100%;max-width:1100px;cursor:crosshair"',
    '           @click="onMarkClick" @mousemove="onMarkMove" @mouseleave="onMarkLeave"',
    '           @mousedown="onMarkDown" @mouseup="onMarkUp">',
    '        <img v-if="mfCurrentRight && mfCurrentRight.image" :src="mfCurrentRight.image" style="width:100%;height:auto;display:block;border-radius:var(--r-sm)" />',
    '        <div v-if="!mfCurrentRight || !mfCurrentRight.image" class="muted" style="padding:40px">在上方播放器选好画面，再点击「选作右画面」</div>',
    '        <div v-if="mfDualSplit" class="mf-badge">右画面{{ mfActive===1 ? \'（正在点这里）\' : \'\' }}</div>',
    '        <svg v-if="frameWRight && frameHRight" :viewBox="\'0 0 \' + frameWRight + \' \' + frameHRight"',
    '             preserveAspectRatio="none"',
    '             style="position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none">',
    '          <template v-for="(p,i) in mfPtsRight" :key="\'R\'+i">',
    '            <circle :cx="p.x * frameWRight" :cy="p.y * frameHRight" :r="Math.max(10, frameWRight*0.012)"',
    '                    fill="rgba(34,197,94,.35)" stroke="#22c55e" :stroke-width="Math.max(2, frameWRight*0.003)" />',
    '            <text :x="p.x * frameWRight + Math.max(12, frameWRight*0.014)" :y="p.y * frameHRight"',
    '                  fill="#22c55e" :font-size="Math.max(16, frameWRight*0.022)"',
    '                  style="paint-order:stroke;stroke:#000;stroke-width:3px">{{ i + 1 }}. {{ p.label }}</text>',
    '          </template>',
    '          <template v-for="(p,i) in snapPtsRight" :key="\'SR\'+i">',
    '            <circle :cx="p.x * frameWRight" :cy="p.y * frameHRight" :r="Math.max(11, frameWRight*0.013)"',
    '                    fill="none" stroke="#f59e0b" :stroke-width="Math.max(2, frameWRight*0.0035)"',
    '                    stroke-dasharray="4 3" />',
    '          </template>',
    '          <template v-for="(p,i) in miniPtsRight" :key="\'MR\'+i">',
    '            <circle :cx="p.x * frameWRight" :cy="p.y * frameHRight" :r="Math.max(11, frameWRight*0.013)"',
    '                    fill="rgba(34,197,94,.35)" stroke="#22c55e" :stroke-width="Math.max(2, frameWRight*0.0035)" />',
    '            <text :x="p.x * frameWRight + Math.max(13, frameWRight*0.015)" :y="p.y * frameHRight"',
    '                  fill="#22c55e" :font-size="Math.max(18, frameWRight*0.024)"',
    '                  style="paint-order:stroke;stroke:#000;stroke-width:3px">{{ p.seq }}</text>',
    '          </template>',
    // ⚠️ 右画面用的是**它自己那一帧的 H**（overlayLinesRight）。以前这里渲染的是
    // 左画面的 overlayLines —— 两个机位的球场线互相串，两边都压不到白线上。

    '        </svg>',
    '      </div>',
    '    </div>',
    // 已点清单（文字版，双重反馈）：球场模式按"哪一幅画面"分开列 ——
    // 左右两个画面的坐标不通用，混成一列会让人以为它们在同一套坐标里。
    '    <div v-if="markKind===\'court\' && mfPts.length" style="margin-top:8px">',
    '      <div class="hint">左画面（t={{ mfLeftCov.t }}s）：</div>',
    '      <div class="row" style="flex-wrap:wrap">',
    '        <el-tag v-for="(p,i) in mfFramePts(0)" :key="\'lp\'+i" size="small" type="success" effect="plain" style="margin:2px">',
    '          {{ i + 1 }}. {{ p.label }}</el-tag>',
    '        <span v-if="!mfFramePts(0).length" class="hint">（还没点）</span>',
    '      </div>',
    '      <template v-if="mfDualSplit">',
    '        <div class="hint" style="margin-top:6px">右画面（t={{ mfRightCov.t }}s）：</div>',
    '        <div class="row" style="flex-wrap:wrap">',
    '          <el-tag v-for="(p,i) in mfFramePts(1)" :key="\'rp\'+i" size="small" type="success" effect="plain" style="margin:2px">',
    '            {{ i + 1 }}. {{ p.label }}</el-tag>',
    '          <span v-if="!mfFramePts(1).length" class="hint">（还没点）</span>',
    '        </div>',
    '      </template>',
    '    </div>',
    '    <div v-else-if="markKind!==\'court\' && activePts.length" class="row" style="margin-top:8px;flex-wrap:wrap">',
    '      <el-tag v-for="(p,i) in activePts" :key="\'t\'+i" size="small" type="success" effect="plain" style="margin:2px">',
    '        {{ i + 1 }}. {{ p.label }} ({{ Math.round(p.x*frameW) }},{{ Math.round(p.y*frameH) }})</el-tag>',
    '    </div>',
    '    <template #footer>',
    '      <el-button v-if="markKind===\'court\'" size="small" @click="mfUndo"',
    '        :disabled="courtMini ? !miniPtsActive.length : !mfPts.length">撤销上一个点</el-button>',
        // 跳过：**两种模式都要有**。以前球场的"跳过这一项"被 v-if 排除了，
    // 而球场点名里有"另一端的篮筐中心（若只有一个篮筐可见就别选它）"这类
    // 画面里根本不存在的点 —— 用户于是卡住：不点前进不了、点也点不出来。
    '      <el-button v-if="markKind===\'court\'" size="small" @click="markSkip" :disabled="markDone">跳过这一项</el-button>',
    // 清空：两个画面模式下「清空」只清当前这一个画面（另一边辛苦标的点不该被连坐），
    // 要全清就用后面那个「全部清空」。
    '      <el-button size="small" @click="markKind===\'court\' ? mfClear() : clearMarks()" :disabled="markKind===\'court\' ? !mfActivePtsCount : (markSaving || (!hoopPanels.left.box && !hoopPanels.right.box))">',
    '        {{ markKind===\'court\' && mfDualSplit ? \'清空这个画面\' : \'清空\' }}</el-button>',
    '      <el-button v-if="markKind===\'court\' && mfDualSplit" size="small" @click="mfClearAll" :disabled="!mfPts.length">全部清空</el-button>',
    '      <el-button size="small" :disabled="markSaving" @click="markOpen=false">关闭</el-button>',
    // 保存：篮筐模式标了中心就能存；球场模式要求**至少有一幅画面自己够 4 个点**
    // （以前只看总点数，于是"6 个点撒在 3 幅画面上"这种解不出来的点法也能点保存，
    //  点下去只会拿到一句"误差偏大"，用户根本不知道该改什么）
    '      <el-button v-if="markKind!==\'court\' || !courtMini" size="small" type="primary" :loading="markSaving"',
    '        :disabled="markKind===\'court\' ? !(mfFrames.length ? (mfEnough && solvableFrames.length && mfFullCourtReady) : courtEnough) : (!hoopPanels.left.box || !hoopPanels.right.box || hoopPanels.left.loading || hoopPanels.right.loading)"',
    '        @click="markKind===\'court\' ? (mfFrames.length ? saveCourtMulti() : saveCourt()) : saveMarks()">',
    '        {{ markKind===\'court\' ? \'保存标定\' : \'保存左右篮筐\' }}</el-button>',
    '    </template>',
    '  </el-dialog>',
    '</div>'
  ].join('\n')
};
