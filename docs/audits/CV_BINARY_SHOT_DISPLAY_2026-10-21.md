# 投篮结果两类展示

日期：2026-10-21。按用户要求去掉投篮结果的“未知”第三类。只修改展示和人工补录选项，没有改变视觉引擎、模型、记分牌融合或原分析文件。

## 显示规则

统一复用`D.shotDisplay(row)`：

- 已有判定显示“命中”或“未中”。
- 原结果未确认、已有可用`suggested_made`时显示“命中（推测）”或“未中（推测）”。
- 完全缺少结论或有筐位不稳定、筐沿接触、实测轨迹中断等限制时，暂列“未中（暂定）”。这仅是显示分组，**不是算法已确认没进**。
- 所有推测/暂定记录保留可见标记；提示和汇总说明其不计入确认命中与比分。不能去掉这些标记后把显示分组冒充实测结果。
- 未中或未确认的记录不展示分值；确认命中的分值继续沿用既有规则。

时间轴只提供“全部、仅命中、仅未中”筛选。徽章、筛选、显示分组计数、高光标题及播放器时间标记统一使用上述规则。原始`result=unknown`、`made=null`和建议字段保持不变，不通过UI把它们写成MISS。

人工补录只给“命中、未中”两个选项，必须主动选择；空选择不发送请求。批量确认仍跳过未确认原记录，不会自动采纳显示用暂定分组。

位置未知、号码未知、分值未知属于其他数据缺口，未被伪造为已知数值。

## 实际页面验证

使用原保存任务`0c19396bf72c`的8条事件，实际挂载现有Vue总览组件。原输入中3条为MADE、1条为MISSED、4条未确认。显示分组为4命中、4未中，其中1条推测命中、3条暂列未中；**这不是4次确认命中或准确率提高**。

- “未知”结果筛选和结果徽章已移除。
- 推测/暂定文本实际渲染，未中筛选结果与显示分组一致。
- 原事件JSON及原比分逐字比较不变。
- 浏览器无运行异常，只发出本地GET请求，没有提交判断或写入正式接口。
- 截图：`out/shot_binary_display_20261021_01/browser_final/binary_results.png`。
- 本机离线预览：`http://127.0.0.1:8138/`，仅供显示核对，无新的视频识别结果。

## 修改文件

- `web/data.js`：统一显示分组，不修改`isUnknown`统计保护。
- `web/pages/overview.js`：两类筛选、标签和显示分组说明。
- `web/pages/review.js`：复用标签、人工补录两选项及空选择校验。
- `web/pages/highlights.js`、`web/detection-overlay.js`：高光和播放器标记使用相同标签。
- `web/pages/examples.js`、`web/pages/report.js`、`web/pages/home.js`、`web/components.js`：去掉结果第三类相关文案，保持数据缺口说明。
- `web/index.html`：修改脚本版本`101-binary-shot-display`。
- `tests/test_binary_shot_display.js`、`tests/binary_shot_browser.mjs`：展示、筛选、人工写入保护、原值保持与实际浏览器验证。
- `tests/test_review_suggestions.js`、`tests/test_unknown_style.js`：更新被新展示要求替代的三态文案期望，保留证据和未知位置保护。

## 测试

JS通过：`test_binary_shot_display.js`、`test_shot_outcome_display.js`、`test_review_suggestions.js`、`test_replay_overlay.js`、`test_results_refresh.js`。新测试覆盖矛盾的`result=unknown/made=true`、受阻建议、无结论暂定、原字段不变及无选择不提交。

实际Chromium总览渲染与交互通过，结果见`browser_final/checks.json`。Python统计/复核/运行契约/来源保护定向测试18 passed、7条依赖弃用提示，0.39秒。本轮没有重跑全量Python。

`test_unknown_style.js`的新二态展示、原未知投篮不入图、时间定位和对比度部分通过；随后仍在此前已失败的旧`v-else-if="e.decision_t != null"`模板断言处失败。不宣称全部JS通过，也没有为了通过旧断言恢复用户已要求精简的细节。

源码及日志保存在`out/shot_binary_display_20261021_01/`；浏览器.mjs源码另行保存，因为既有freeze清单不自动收录该扩展名。

## 发布及限制

开发源码已修改，固定正式副本未部署、未重启。现有网站尚不会自动变成新显示。没有重新训练或推理模型，没有覆盖用户分析。

本轮满足的是两类**展示**要求，没有证明所有投篮都能准确判断进或没进。没有足够视觉证据的记录仍需要有界复查或人工确认，不能通过改文字宣称召回率或命中判定准确率改善。
