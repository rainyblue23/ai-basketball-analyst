# 结果标签改为“中／没中”

日期：2026-10-21。本轮替代上一轮`101-binary-shot-display`的显示规则。

## 改动

- 已判定结果只显示“中”或“没中”，列表、筛选、复核选项、高光和回看按钮统一。
- 删除上一轮的推测、暂定标记，也撤销把缺证据记录暂列未中的默认分组。
- 没有结论的记录不生成结果徽章，保留在“其他回看时间”，每条仍能定位原事件；不增加第三个结果状态。
- 没中的球不显示分值。原始事件、比分、统计、算法建议字段保持原样；没有把缺证据转成MISS。
- 人工补录只能选择“中／没中”，没有选择时不提交。去掉UI中采纳算法建议的快捷入口，保留回看和逐条确认。

这次修复的是显示口径，不能据此宣称所有投篮都已准确判断。证据不足的回看时间没有被删除，也没有被计入命中或未中结果数。

## 实际验证

使用原任务`0c19396bf72c`保存的8条事件，实际挂载现有Vue总览组件：3个原MADE、1个原MISSED显示为“中3／没中1”；另外4个时间点全部保留为回看按钮。上一轮按算法建议额外显示的1个命中及3个默认未中已经撤回。

浏览器验证标签只可能为“中／没中”，无第三类筛选；没中筛选只显示原有1条MISSED；其他4个时间点可选中原始事件。原事件JSON和原比分逐字比较不变，没有外部请求或提交结果。

- 本机预览：`http://127.0.0.1:8139/`。
- 截图：`out/shot_two_states_20261021_01/browser_verified/binary_results.png`。
- 证据与源码：`out/shot_two_states_20261021_01/`，保留改前及改后快照；浏览器.mjs源码单独收录。

## 修改范围

`web/data.js`、`pages/overview.js`、`pages/review.js`、`pages/highlights.js`、`detection-overlay.js`、`components.js`、`pages/home.js`及`index.html`。相关脚本版本为`102-two-result-states`。

更新了`test_binary_shot_display.js`、`test_shot_outcome_display.js`、`test_review_suggestions.js`、`test_unknown_style.js`和`binary_shot_browser.mjs`，明确验证建议不能替代结论、未判定时间不得丢失、原始字段和人工写入保护。

## 测试结果

- JS定向：二态标签、分值、复核、播放器及结果刷新通过，实际日志见`js_checks.json`与对应`.log`。
- Chromium实际组件渲染、两类筛选、其他时间点原事件定位通过；未修改正式结果。
- Python统计/复核/运行契约/来源保护：18 passed，7条依赖弃用提示，0.38秒。
- `test_unknown_style.js`的本轮二态及数据保留检查通过，仍在此前即失败的旧`v-else-if="e.decision_t != null"`模板断言处失败；未声称全部JS或全量Python通过。

## 发布状态

只修改开发源码和隔离预览。正式固定副本没有部署、没有重启；没有换模型、运行新推理、启用记分牌融合或覆盖用户原分析。
