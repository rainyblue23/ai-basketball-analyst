# 战术覆盖不足与未中分值展示修复

日期：2026-10-20，Asia/Shanghai。

## 1. 对应任务及结论

本轮找到了与截图完全一致的保存任务 `0c19396bf72c`：俯视位置51/182、空间采样25/91。它仍由固定线上副本生成，前两轮默认关闭的战术证据处理没有部署到该副本。

在同一任务的原始观测上，复用既有轨迹有效期、角色及球衣多帧分组实现，离线位置覆盖变为145/182，人数异常触发从105降为0。新增可选“可见球员空间指标”后，可展示60/91个秒级采样时刻。

这些是显示覆盖和规则触发计数，**不是人数、角色、球队或球员身份准确率**。97/145个显示时刻仍含分队未知人员。没有读入上一轮的人工同人标签，也没有把旧任务的临时ID映射直接套到新任务。

未中事件的列表、复核结果标签、高光标题/副标签及球场提示改为“未中”，不再附分值；命中才附分值。未知不会变成未中。原始出手类型与统计接口不因文案修改而删除。

## 2. 输入、输出及隔离

- 原目录：`deploy/runtime/20261016-152930/out/0c19396bf72c/`。
- raw SHA-256：`1f9039e5647298d6235c1264c026973bdabf9b39bec55ac90a83534c3a75bf67`。
- Development来源组：`yang-retry2`；约90.96秒，29.97002997 FPS。
- 产物：`out/tactics_coverage_20261020_181008/`。
- `before/`：改前源码身份；`population/`：同任务角色/分队证据及四组对照；`final_verified/`：最终复现结果及源码快照。
- `verified_run/`及`final_run/`保留中间实验，不应当作最终交付；最终以`final_verified/`为准。

模型沿用E-BARD `models/BODD_yolov8n_0001.pt`，imgsz=1280、conf=0.25；未训练、未换模型。精确视频/模型/缓存SHA在`population/evidence.json`与`final_verified/comparison.json`。

正式运行副本171个清单文件SHA保持一致、原进程PID262365未变化、`AIHOOP_DISABLE_SCOREBOARD_FUSION=1`保持原样。原任务文件逐个SHA校验未变。没有部署、重启、覆盖已有分析结果或旧证据ZIP。

## 3. 定位到的问题与处理

### 3.1 原结果的人员采样/分队导致大量时刻被整帧拒绝

旧插值会提前带入未来ID、过久保持已经结束的碎片；单轨迹分队证据不足也会形成同队超过五人的假象。此次复用已完成的保守边界、角色和多帧球衣分组，不重新实现、不截取前五人、不凭配额补十人。

### 3.2 一个未知分队的人会清空两组空间指标

原代码对当前采样采取整帧未知门槛：只要有一个分队未知人员，所有组的空间指标一起跳过。

新增 `TacticsConfig.spacing_observed_subset=False`，默认不启用。显式启用时，只计算已有可靠分组且至少两人的可见子集，输出实际`n`、`scope=observed_team_subset`、`unassigned_present`与镜头段。未知位置不分配球队、不参与该组空间指标；存在未知人员时依旧禁止新增阵型推断。

页面标明“仅可见球员”“不代表完整五人阵容”，悬停显示人数，表格显示采样人数范围。人数变化、切镜、时间断档时断线。这个口径可以帮助查看局部站位，不能与完整五人阵容面积直接等同。

### 3.3 稀疏阵型被误连成很长的持续片段

本次实际检查发现，同名阵型在15～55秒仅5个离散采样，却被合成40秒持续片段。现有`_segments`增加可选间隔与切镜检查；`roster_evidence_filter=True`时采用不超过1.5倍采样间隔的连续性条件。

最终该假40秒片段不再输出；32～34秒三条连续采样保留为2秒片段。修复作用于已有分段函数，不通过延长位置有效期制造连贯性。匿名分组的战术亮点也不再从“号码待确认”截取出错误队名。

### 3.4 剩余37个时刻不是只靠人物跟踪就能补齐

37个空白采样时刻全部有person检测上下文，但没有0.12秒内可用的投影人员观测，对应的手标画面配准均失败。具体时刻及配准记录见`missing_position_registration_audit.json`。

主要范围包括9.5～10、28～30、34.5～43.5、49.5～51、67.5～69、89.5～90.5秒（这里列的是0.5秒网格点，并非精确失败区间边界）。不能据此判定没有球员，也不能沿用旧镜头坐标填满画面。

## 4. 同任务对照

| 方案 | 可显示位置 / 182 | 人数异常触发 | 空间采样 / 91 | 含未知分队的显示时刻 |
| --- | ---: | ---: | ---: | ---: |
| 原任务保存结果 | 51 | 105 | 25 | 0，旧分类未表达未知 |
| 复用角色＋多帧分组＋轨迹边界 | 145 | 0 | 22 | 97 |
| 上项＋可见球员空间指标 | 145 | 0 | 60 | 97 |

后两行是相同输入、相同证据和相同位置的单开关对照。图的位置帧逐条一致，阵型和正式事件导出一致。22→60是空间展示口径的改变，不是检测召回改善。原保存结果→新证据方案包含此前多项修复，不将差异归因于本轮单个参数。

同条件导出中`events.jsonl`、`shots.csv`、`stats.csv`、`players.json`、`shotchart.json`逐文件SHA相等。预览的投篮记录直接加载原任务保存的`game.json`，不使用本轮重新导出的事件替换用户结果。

## 5. 修改文件

| 文件 | 改动 |
| --- | --- |
| `src/aihoop/tactics.py` | 默认关闭的可见子集空间指标、人数/镜头元数据；已有阵型分段增加断档和切镜门槛；匿名队名保护 |
| `web/data.js` | 未中提示无分值；共享结果分值显示判据 |
| `web/pages/overview.js` | 投篮列表仅命中显示分值 |
| `web/pages/review.js` | 复核结果标签复用判据，未中无分值 |
| `web/pages/highlights.js` | 未中标题/标签不沿用带分值旧文案 |
| `web/pages/tactics.js` | 可见人数、展示口径提示、人数/切镜断线、未知主客分组标签 |
| `web/tactics-coverage-preview.html` | 使用真实页面组件的隔离对照入口 |
| `scripts/compare_tactics_coverage.py` | 同任务复现、输入保护、导出一致性验证、预览产物 |
| `tests/test_tactics_partial_spacing.py` | 子集不冒充完整球队、UNKNOWN/超员保留限制、断档/切镜及队名回归 |
| `tests/test_shot_outcome_display.js` | 列表/提示/高光中的未中分值、矛盾UNKNOWN元数据、原值不被修改 |
| `tests/test_tactics_motion.js` | 新增人数变化/切镜断线、悬停人数及转义检查 |
| `tests/test_unknown_style.js` | 未中tooltip期望更新为“未中”；既有失效模板断言保持记录 |
| `tests/tactics_coverage_browser.mjs` | 真实Vue页面、三组覆盖、播放及未中实际渲染检查 |

## 6. 测试结果

- 定向Python：**53 passed**，0.54秒；有6条既有依赖弃用提示。
- JS：`test_shot_outcome_display.js`、`test_tactics_motion.js`、`test_pass_network_focus.js`、`test_results_refresh.js`通过。
- Chromium：原任务51/182与25采样、新结果145/182与60采样、播放器推进、可见子集范围、未中无分值/命中有分值/UNKNOWN保留通过；无运行异常，无外部或写入请求。
- 浏览器未中渲染矩阵使用三个合成事件，仅在测试标签页临时显示并随即恢复原任务事件；它不是算法诊断真值。`browser_verified/shot_display_test_matrix.png`明确属于合成UI输入；`saved_shots_after.png`才是保存事件恢复后的页面。
- `test_unknown_style.js`仍在既有`v-else-if="e.decision_t != null"`旧模板断言失败。已从改前源码快照实际复现同一失败，见`unknown_style_before.log`、`unknown_style_after.log`和`known_ui_regression.json`；不宣称全部JS通过。
- Attempt/Shot运行契约、`git diff --check`通过。
- 本轮未重跑全量Python测试，不将上一轮全量结果冒充本轮结果。

角色补充推理共1085帧，已同步的YOLO调用墙钟约11.13秒，解码和证据采集合计16.26秒。最终对照复用缓存，无新增GPU调用；没有端到端加速或准确率改善结论。

## 7. 查看与复现

本机可操作入口：**http://127.0.0.1:8136/**。可切原任务/角色分队修复/可见球员空间曲线，并查看原任务投篮列表。仅回环离线预览，正式网站尚未发布。

```bash
cd /data/projects/ai-basketball-analyst
export PYTHONPATH=src:scripts
export PATH=/data/projects/ai-basketball-analyst/out/cv_baseline_20261015/tools:$PATH

# 缓存已存在；每次使用尚不存在的新输出目录
/data/conda-envs/ai-basketball-analyst/bin/python scripts/compare_tactics_coverage.py \
  --job-dir deploy/runtime/20261016-152930/out/0c19396bf72c \
  --evidence out/tactics_coverage_20261020_181008/population/evidence.json \
  --out out/tactics_coverage_reproduce_01

/data/conda-envs/ai-basketball-analyst/bin/python -m pytest \
  tests/test_tactics_partial_spacing.py tests/test_tactics_roster_evidence.py \
  tests/test_tactics_appearance_evidence.py tests/test_tactics_identity_evidence.py \
  tests/test_external_report.py tests/test_runtime_contract.py -q
node tests/test_shot_outcome_display.js
node tests/test_tactics_motion.js
node tests/test_pass_network_focus.js
node tests/test_results_refresh.js

# 浏览器检查需要独立Chrome CDP及上面的离线预览服务
node tests/tactics_coverage_browser.mjs out/coverage_browser_reproduce_01 \
  http://127.0.0.1:8136/ http://127.0.0.1:9230
```

回退：关闭`spacing_observed_subset`恢复保守空间口径；停用离线角色/分队证据恢复旧战术输入。不需要恢复原任务文件，原目录未改。

## 8. 后续顺序

优先处理缺失37个采样时刻的镜头—标定配准：输出少量代表画面，核对已有标定是否覆盖该机位，再评估相邻有效镜头的有限几何传播。传播必须独立校验，失败仍保留未知，不延长错误旧坐标。之后再补完整人员角色/分队真值和跨比赛评估；当前不能宣称战术已全程连续或整体识别准确率提升。
