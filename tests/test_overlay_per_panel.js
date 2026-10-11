/* 回归测试：**每个画面各画各的球场线**（用户实测反馈："红框明显不对"）。
 *
 * 现场：标定页左右两个画面是**两个机位**（各拍半场、取的时刻也不同）。
 * 后端一份 H 只属于其中一幅，而模板里两个 <svg> 以前渲染的是**同一个** overlayLines
 * —— 于是把一个机位的球场线画到了另一个机位上：左画面整体偏约 20m、
 * 右画面也压不到画面里的白线（形状还和左画面一模一样，这就是 bug 的指纹）。
 *
 * 断言：
 *   ① 两帧各自有 H 时（per_frame_fit），左画面用左帧的 H、右画面用右帧的 H，互不相同；
 *   ② 右画面**不得**再拿到左帧的那份 H；
 *   ③ 顶层 H 只属于某一帧（旧后端 / single-frame 路径）时，不许把它画到另一帧上；
 *   ④ 单画面（没有右帧）时行为不变：照旧用顶层 H 画；
 *   ⑤ 关掉自检开关 / 关窗：左右两份都要清空（不能留下旧线）；
 *   ⑥ `segments_H`（多机位那条路：顶层没有 H）也要能认领；
 *   ⑦ 自动试算**不许**在"还有一幅没点够 4 个点"的中间状态去解算
 *      （实测：点下第二幅第 1 个点时后端报"跨画面的点混在一起解不了"，还要 40+ 秒）；
 *   ⑧ 吻合度读数必须**逐段**摆出来（分时段标定只报"最差 0.17"会让用户以为整份都差）。
 */
'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');

global.window = { STORE: { backendOk: true } };
require(path.resolve(__dirname, '../web/pages/upload.js'));
const p = window.PAGES.upload;

function makeVm() {
  const v = { ...p.data(), $message: { warning() {}, info() {}, error() {}, success() {} } };
  for (const [k, fn] of Object.entries(p.methods)) v[k] = fn.bind(v);
  for (const [k, fn] of Object.entries(p.computed || {})) {
    Object.defineProperty(v, k, { get: fn.bind(v), configurable: true });
  }
  return v;
}

// ---- 两个"机位"的单应矩阵（像素→球场米），形态模仿真实标定：帧上方是远端(y>0) ----
const H_LEFT = [[0.002, -0.03, 10.0], [-0.025, -0.001, 16.0], [-0.0008, 0.0025, 1.0]];
const H_RIGHT = [[0.021, -0.02, -8.0], [-0.012, 0.004, 12.0], [0.0015, 0.0022, 1.0]];

function applyH(H, x, y, W = 960, Hh = 544) {
  const px = x * W, py = y * Hh;
  const w = H[2][0] * px + H[2][1] * py + H[2][2];
  return [(H[0][0] * px + H[0][1] * py + H[0][2]) / w,
          (H[1][0] * px + H[1][1] * py + H[1][2]) / w];
}
// 用 H 的**逆**生成"用户点准了"的画面点（和 repo 里其它夹具同一套做法）
function inv3(m) {
  const [a, b, c] = m[0], [d, e, f] = m[1], [g, h, i] = m[2];
  const A = e * i - f * h, B = c * h - b * i, C = b * f - c * e;
  const D = f * g - d * i, E = a * i - c * g, F = c * d - a * f;
  const G = d * h - e * g, Hh = b * g - a * h, I = a * e - b * d;
  const det = a * A + b * D + c * G;
  return [[A / det, B / det, C / det],
          [D / det, E / det, F / det],
          [G / det, Hh / det, I / det]];
}
function pointOn(H, dst, W = 960, Hh = 544) {
  const inv = inv3(H);
  const v = [inv[0][0] * dst[0] + inv[0][1] * dst[1] + inv[0][2],
             inv[1][0] * dst[0] + inv[1][1] * dst[1] + inv[1][2],
             inv[2][0] * dst[0] + inv[2][1] * dst[1] + inv[2][2]];
  return { x: (v[0] / v[2]) / W, y: (v[1] / v[2]) / Hh };
}

function main() {
  const vm = makeVm();
  vm.markKind = 'court';
  vm.form = { video_path: 'x.mp4' };
  vm.mfFrames = [{ t: 117.97, w: 960, h: 544, image: '' },
                 { t: 13.5, w: 960, h: 544, image: '' }];
  vm.mfIdx = 0; vm.mfIdx2 = 1; vm.mfActive = 0; vm.dualView = true;
  assert.equal(vm.mfDualSplit, true, '两帧不同时刻 → 必须是左右两个画面');

  // 用户点的点：左画面 A端 5 个、右画面 B端 5 个（用各自的 H 反投影生成）
  const A = { corner_far_right: [7.5, 14.0], lane_far_left: [-2.45, 8.2], ft_far: [0.0, 8.2],
              lane_far_right: [2.45, 8.2], arc_far: [0.0, 5.675] };
  const B = { lane_near_left: [-2.45, -8.2], ft_near: [0.0, -8.2], lane_near_right: [2.45, -8.2],
              arc_near: [0.0, -5.675], corner_near_left: [-7.5, -14.0] };
  vm.mfPts = [];
  for (const [n, d] of Object.entries(A)) {
    const q = pointOn(H_LEFT, d);
    vm.mfPts.push({ t: 117.97, name: n, label: n, x: q.x, y: q.y });
  }
  for (const [n, d] of Object.entries(B)) {
    const q = pointOn(H_RIGHT, d);
    vm.mfPts.push({ t: 13.5, name: n, label: n, x: q.x, y: q.y });
  }

  // ---- ①/② 后端带每帧自己的 H（多机位那条路：顶层没有 H）----
  vm.mfResult = {
    ok: true, via: 'per-shot', multi_shot: true, H: null,
    per_frame_fit: [
      { t: 117.97, n: 5, ok: true, rmse_m: 0.04, H: H_LEFT },
      { t: 13.5, n: 5, ok: true, rmse_m: 0.03, H: H_RIGHT }
    ]
  };
  vm.refreshOverlay();
  assert.ok(vm.overlayLinesLeft.length > 0, '左画面必须有自己的球场线');
  assert.ok(vm.overlayLinesRight.length > 0, '右画面必须有自己的球场线（顶层没有 H 时也要画）');
  assert.notDeepEqual(vm.overlayLinesLeft, vm.overlayLinesRight,
    '两个机位的线不可能一模一样 —— 一样就说明又画成同一份了');

  // 左画面的线 = 用 H_LEFT 投出来的；右画面 = 用 H_RIGHT 投出来的
  const leftOwn = vm._overlayLinesFor(H_LEFT, 960, 544);
  const rightOwn = vm._overlayLinesFor(H_RIGHT, 960, 544);
  assert.deepEqual(vm.overlayLinesLeft, leftOwn, '左画面必须用左帧自己的 H');
  assert.deepEqual(vm.overlayLinesRight, rightOwn, '右画面必须用右帧自己的 H');
  assert.notDeepEqual(vm.overlayLinesRight, leftOwn, '右画面不能再拿到左帧的线');

  // 每个画面的线都要落在**它自己**那帧的对角地标上（自证：用点反投影量误差）
  function worstErr(pts, H) {
    let worst = 0;
    for (const q of pts) {
      const g = applyH(H, q.x, q.y);
      const d = (q.t === 117.97 ? A : B)[q.name];
      worst = Math.max(worst, Math.hypot(g[0] - d[0], g[1] - d[1]));
    }
    return worst;
  }
  assert.ok(worstErr(vm.mfPts.filter(x => x.t === 117.97), H_LEFT) < 0.01, 'H_LEFT 属于左帧');
  assert.ok(worstErr(vm.mfPts.filter(x => x.t === 13.5), H_RIGHT) < 0.01, 'H_RIGHT 属于右帧');
  assert.ok(worstErr(vm.mfPts.filter(x => x.t === 13.5), H_LEFT) > 1.0, 'H_LEFT 用在右帧上必然偏 >1m');

  // ---- ③ 只有顶层 H（旧后端 / single-frame）：只许画在它自己那一帧上 ----
  vm.mfResult = { ok: true, via: 'single-frame', best_frame_t: 117.97, H: H_LEFT,
                  per_frame_fit: [{ t: 117.97, n: 5, ok: true, rmse_m: 0.04 }] };
  vm.refreshOverlay();
  assert.ok(vm.overlayLinesLeft.length > 0, '顶层 H 属于左帧 → 左画面要画');
  assert.equal(vm.overlayLinesRight.length, 0,
    '顶层 H 不属于右帧时，右画面**宁可空着**也不许画别的机位的线（这就是原来那个 bug）');

  // ---- ④ 单画面：行为不变，照旧用顶层 H ----
  vm.dualView = false;
  vm.mfIdx2 = 0;
  vm.mfResult = { ok: true, via: 'merged', H: H_RIGHT, per_frame_fit: [] };
  vm.refreshOverlay();
  assert.ok(vm.overlayLinesLeft.length > 0, '单画面时顶层 H 照旧生效');
  assert.deepEqual(vm.overlayLinesLeft, vm._overlayLinesFor(H_RIGHT, 960, 544));

  // ---- ⑤ 关掉开关 / 关窗：三份都必须清空 ----
  vm.dualView = true; vm.mfIdx2 = 1;
  vm.mfResult = { ok: true, H: null,
                  per_frame_fit: [{ t: 117.97, n: 5, ok: true, H: H_LEFT },
                                  { t: 13.5, n: 5, ok: true, H: H_RIGHT }] };
  vm.refreshOverlay();
  assert.ok(vm.overlayLinesRight.length > 0, '前置条件：右画面有线');
  vm.toggleCourtOverlay();
  assert.equal(vm.overlayLinesLeft.length + vm.overlayLinesRight.length + vm.overlayLines.length,
    0, '关掉自检开关必须清空所有叠线');
  vm.toggleCourtOverlay();
  vm.refreshOverlay();
  vm.onMarkClosed();
  assert.equal(vm.overlayLinesLeft.length + vm.overlayLinesRight.length + vm.overlayLines.length,
    0, '关窗必须清空所有叠线');

  // ---- ⑥ 多机位那条路：顶层 H = null，每段一份 H（segments_H）也要能认领 ----
  vm.mfResult = { ok: true, via: 'per-shot', multi_shot: true, H: null,
                  segments_H: [{ t_start: 0.0, t_end: 55.21, names: [], n_points: 5, H: H_RIGHT },
                               { t_start: 55.21, t_end: 240.08, names: [], n_points: 5, H: H_LEFT }] };
  vm.refreshOverlay();
  assert.deepEqual(vm.overlayLinesLeft, vm._overlayLinesFor(H_LEFT, 960, 544),
    'per-shot：左画面要按 t 认领它所在那一段的 H');
  assert.deepEqual(vm.overlayLinesRight, vm._overlayLinesFor(H_RIGHT, 960, 544),
    'per-shot：右画面要按 t 认领它所在那一段的 H');

  // ---- ⑦ 自动试算的中间状态门禁 ----
  const calls = [];
  window.API = { calibrateMulti: (payload) => { calls.push(payload); return Promise.resolve(vm.mfResult); } };
  const v2 = makeVm();
  v2.markKind = 'court';
  v2.form = { video_path: 'x.mp4' };
  v2.mfFrames = vm.mfFrames;
  v2.mfIdx = 0; v2.mfIdx2 = 1; v2.mfActive = 0; v2.dualView = true;
  v2.mfPts = vm.mfPts.filter(q => q.t === 117.97);        // 只有左画面点够 4 个
  v2.scheduleAutoPreview();
  const step = () => new Promise(r => setTimeout(r, 800));
  return step().then(() => {
    assert.equal(calls.length, 0,
      '右画面还没点够 4 个点时不许自动解算（实测那一步会报"跨画面的点混在一起解不了"）');
    v2.mfPts = vm.mfPts;                                  // 两边都够 4 个了
    v2.scheduleAutoPreview();
    return step();
  }).then(() => {
    assert.equal(calls.length, 1, '两边都点够之后应该自动解算一次');

    // ---- ⑧ 吻合度逐段 ----
    const v3 = makeVm();
    v3.markKind = 'court';
    v3.mfResult = { ok: true, calibration_fit: {
      ratio: 0.17, rmse_m: 0.0,
      by_segment: [{ t_start: 0.0, t_end: 55.21, n_points: 5, rmse_m: 0.0, ratio: 0.17 },
                   { t_start: 55.21, t_end: 240.08, n_points: 5, rmse_m: 0.0, ratio: 0.94 }] } };
    const rows = v3.fitSegRows;
    assert.equal(rows.length, 2, '两段必须各摆一行，不能只报一个总数');
    assert.equal(rows[0].ratio, 0.17);
    assert.equal(rows[1].ratio, 0.94);
    assert.equal(rows[1].ok, false, '0.94 < 1.25 → 这一段也不过门槛');
    assert.equal(v3.fitIsWorstOfSegments, true, '标题必须说清这是"最差那一段"的读数');

    // ---- 输出 ----
    console.log('① 两帧各自的 H → 左画面用左帧、右画面用右帧  ✅');
    console.log('② 右画面不再拿到左帧的线  ✅');
    console.log('③ 顶层 H 只画在它自己那一帧上，另一帧宁可空着  ✅');
    console.log('④ 单画面行为不变  ✅');
    console.log('⑤ 开关/关窗清空左右两份  ✅');
    console.log('⑥ segments_H（多机位）也能按 t 认领  ✅');
    console.log('⑦ 中间状态不自动解算，两边够 4 个才算  ✅');
    console.log('⑧ 吻合度逐段摆出来  ✅');
    console.log('\n每个画面各画各的球场线 + 逐段读数（checks passed）');
  });
}

main().catch((e) => { console.error('失败：', e && e.message ? e.message : e); process.exit(1); });
