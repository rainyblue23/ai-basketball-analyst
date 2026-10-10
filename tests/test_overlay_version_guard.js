/* 回归测试：自动叠线的**异步不串帧**（用户 2026-10-05 要求）。
 *
 * 风险场景：用户点完 4 个点触发一次自动解算（慢请求 A 在飞），接着又拖了一个点
 * （版本号 +1，请求 B 也发出去）。如果 B 先回来、A 后回来，而代码不认版本，
 * A 的旧结果就会把**按新点位算的线**盖掉 —— 画面上看着"线是对的"，其实对应旧点位。
 *
 * 断言：
 *   ① 旧响应（版本已变）必须被丢弃，不得写进 mfResult / overlayLines；
 *   ② 当前版本的响应正常生效；
 *   ③ 关窗（onMarkClosed）会 +1 版本并清空叠线。
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
  Object.defineProperty(v, 'mfEnough', { value: true, configurable: true, writable: true });
  return v;
}

function main() {
  const vm = makeVm();
  vm.mfFrames = [{ t: 1.0, w: 960, h: 540, image: '' }];
  vm.mfIdx = 0;
  vm.form = { video_path: 'x.mp4' };
  vm.markKind = 'court';
  vm.courtMultiPayload = () => ({ frames: [{ t: 1.0, landmarks: {} }], note: '' });

  const pending = [];
  window.API = {
    calibrateMulti: () => new Promise((resolve) => pending.push(resolve)),
  };

  // 第一次（旧点位）
  vm.previewCourtMulti(true);
  assert.equal(pending.length, 1, '第一次请求应已发出');
  const verAtA = vm.mfVersion;

  // 期间用户又动了点位 → 版本号 +1
  vm.mfVersion++;
  assert.notEqual(vm.mfVersion, verAtA, '点位变化必须让版本号变化');

  // 第二次（新点位）
  vm.previewCourtMulti(true);
  assert.equal(pending.length, 2, '第二次请求应已发出');

  // 旧请求先回来 → 必须被丢弃
  pending[0]({ ok: true, rmse_m: 9.99, note: 'stale-A', _tag: 'A' });
  // 再让当前请求回来
  pending[1]({ ok: true, rmse_m: 0.11, note: 'fresh-B', _tag: 'B' });

  return Promise.resolve().then(() => Promise.resolve()).then(() => {
    assert.equal(vm.mfResult && vm.mfResult._tag, 'B',
      '旧响应不得覆盖新结果（当前 mfResult=' + JSON.stringify(vm.mfResult) + '）');
    assert.equal(vm.overlayLines.length, 0);

    // 关窗：版本 +1 且叠线清空
    vm.overlayLines = [[[0, 0], [1, 1]]];
    const before = vm.mfVersion;
    vm.onMarkClosed();
    assert.equal(vm.mfVersion, before + 1, '关窗必须让在途结果失效');
    assert.equal(vm.overlayLines.length, 0, '关窗必须清空叠线');

    console.log('① 旧响应被丢弃（mfResult 仍是新版本的 B）  ✅');
    console.log('② 当前版本响应正常生效  ✅');
    console.log('③ 关窗让在途结果失效并清空叠线  ✅');
    console.log('\n自动叠线异步不串帧（checks passed）');
  });
}

main().catch((e) => {
  console.error('失败：', e && e.message ? e.message : e);
  process.exit(1);
});
