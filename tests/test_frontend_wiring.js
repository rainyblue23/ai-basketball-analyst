/* 前端接线正确性（不需要浏览器、不需要后端）
   --------------------------------------------------------------------------
   为什么单独测这一条：有些 bug 是"接口名/入参拼错"，页面不报错、只是永远不工作。
   本轮实测撞到的两个：

   1) `API.videoUrl` 被定义了两次 —— 一个收 jobId（/api/games/{id}/video），
      另一个收视频路径（/api/video?video_path=...）。后一个覆盖前一个，于是总览页与
      高光页传 jobId 进去，得到 `/api/video?video_path=<jobId>` 这种永远打不开的地址。
   2) 「在画面上标篮筐 / 标球场」以前只判断后端连接状态，没判断"表单里有没有视频路径"。
      没有路径时点了只弹一个一闪而过的提示就 return，**取帧请求根本不会发出去** ——
      用户看到的就是"没法取帧"（后端日志里确实一个 /api/frame 都没有）。

   所以这里守两条不变量：
     * 按任务取原视频的地址只由 jobVideoUrl 生成；按路径取原视频的只由 videoUrl 生成；
       两个名字各自只被定义一次，且调用点用对名字。
     * 取帧类按钮在没有视频路径时必须被禁用，并且页面里有常驻说明（不是一闪而过的提示）。
*/
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..');
const read = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');

// ---- 1) API 地址拼接 ----
global.window = { STORE: {} };
global.location = { protocol: 'http:', search: '', href: 'http://x/web/' };
global.XMLHttpRequest = function () {};
require(path.join(ROOT, 'web/api.js'));
const API = global.window.API;
assert.ok(API, 'window.API 必须存在');

assert.equal(API.jobVideoUrl('abc123'), API.base + '/api/games/abc123/video',
  'jobVideoUrl(jobId) 应指向 /api/games/{id}/video');
assert.ok(API.videoUrl('/tmp/a b.mov').includes('/api/video?video_path='),
  'videoUrl(videoPath) 应指向 /api/video?video_path=...：' + API.videoUrl('/tmp/a b.mov'));
assert.ok(!API.videoUrl('/tmp/a.mov').includes('/api/games/'),
  'videoUrl(videoPath) 不该拼成按任务的地址');
assert.ok(API.videoUrl('/tmp/a b.mov').includes(encodeURIComponent('/tmp/a b.mov')),
  'videoUrl 必须对路径做 URL 编码（空格/中文/反斜杠）');

const apiSrc = read('web/api.js');
const defCount = (name) => (apiSrc.match(new RegExp('API\\.' + name + '\\s*=', 'g')) || []).length;
assert.equal(defCount('videoUrl'), 1, 'API.videoUrl 只能定义一次（重复定义会互相覆盖）');
assert.equal(defCount('jobVideoUrl'), 1, 'API.jobVideoUrl 只能定义一次');

// ---- 2) 调用点用对名字：传 jobId 的地方不能用 videoUrl ----
const callers = [];
for (const f of ['web/pages/overview.js', 'web/pages/highlights.js', 'web/pages/upload.js']) {
  read(f).split('\n').forEach((line, i) => {
    if (/API\.(videoUrl|jobVideoUrl)\(/.test(line)) {
      callers.push({ f, i: i + 1, line: line.trim() });
    }
  });
}
assert.ok(callers.length >= 3, '应当能找到三个调用点，实际：' + callers.length);
for (const c of callers) {
  const usesJobId = /this\.S\.jobId|S\.jobId/.test(c.line);
  if (usesJobId) {
    assert.ok(/API\.jobVideoUrl\(/.test(c.line),
      `${c.f}:${c.i} 传的是 jobId，必须用 jobVideoUrl：${c.line}`);
  }
}

// ---- 3) 取帧按钮必须依赖"有没有视频路径" ----
global.window = { STORE: {} };
require(path.join(ROOT, 'web/pages/upload.js'));
const up = global.window.PAGES.upload;
assert.ok(up.computed.hasVideoPath, 'upload 页要有 hasVideoPath computed');
const hp = up.computed.hasVideoPath;
assert.equal(hp.call({ form: { video_path: '' } }), false, '空路径 → false');
assert.equal(hp.call({ form: { video_path: '   ' } }), false, '空白路径 → false');
assert.equal(hp.call({ form: { video_path: 'D:\\v\\a.mp4' } }), true, '有路径 → true');
assert.equal(hp.call({}), false, 'form 缺失也不能崩');

const tpl = up.template;
assert.ok(tpl.includes(':disabled="!S.backendOk || !hasVideoPath"'),
  '标篮筐/标球场按钮在"没视频路径"时也要禁用');
assert.equal((tpl.match(/!hasVideoPath/g) || []).length >= 3, true,
  '两处按钮 + 常驻提示都应引用 hasVideoPath');
assert.ok(tpl.includes('先选一段视频，按钮才会亮'),
  '没有视频路径时要有**常驻**说明（一闪而过的 toast 不够）');

// 方法里的守卫仍在（按钮禁用只是第一道，方法里也要拦）
assert.ok(/先选一个视频/.test(up.methods.openMark.toString()), 'openMark 仍要守卫');
assert.ok(/先选一个视频/.test(up.methods.openCourt.toString()), 'openCourt 仍要守卫');

// ---- 4) 位置未知的出手不许变成热区（报告页要有常驻说明）----
// 后端已按同一口径挡掉（`export.py` 的 CSV、`report._hot_zones`），这里守前端：
// 既不能自己用占位坐标兜底出热区，也要告诉用户"为什么没有热区"。
global.window = { STORE: {} };
require(path.join(ROOT, 'web/pages/report.js'));
const rp = global.window.PAGES.report;
assert.ok(rp.computed.noLocation, 'report 页要有 noLocation computed');
const nl = rp.computed.noLocation;
assert.equal(nl.call({ game: { timeline: [{ tags: ['location_unknown'] }, { tags: [] }] } }), 1,
  'noLocation 应数出 location_unknown 的出手条数');
assert.equal(nl.call({ game: {} }), 0, '没有 timeline 时为 0');
assert.equal(nl.call({}), 0, 'game 缺失也不能崩');
assert.ok(rp.template.includes('noLocation'),
  '热区卡片要引用 noLocation，否则用户不知道"没有热区"是因为位置未知');
assert.ok(/占位估计/.test(rp.template), '要有常驻说明：为什么不给热区');

console.log('Frontend wiring: videoUrl/jobVideoUrl + 取帧前置条件 + 位置未知不出热区 (checks passed)');
