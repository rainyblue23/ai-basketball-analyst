# 服务器Git安全交接与开发恢复报告

审计时间：2026-10-21T21:35:24.023472+08:00（Asia/Shanghai）。项目：`/data/projects/ai-basketball-analyst`。证据目录：[out/server_git_handover_20261021_205145](out/server_git_handover_20261021_205145/)。本轮仅审计、隔离测试与报告输出；没有合并、变基、提交、推送、清理工作区或重启正式服务。

## 三项判断

|问题|判断|依据|
|---|---|---|
|A. Git代码同步完成？|**是，目标提交已包含**|远程main、origin/main、服务器HEAD均为`c1b65cf7bdabbdc825e94cd2330e3a91facf0c32`；ahead/behind为0/0|
|B. 服务器开发环境可以继续工作？|**可继续隔离开发与GPU诊断；冻结回归条件不齐**|CUDA可用，实际60帧推理/JSON/视频输出通过；缺少冻结原视频、Windows权重和产物，完整门禁未全绿|
|C. 当前实验算法具备启用条件？|**否**|人工穿筐审核未完成，历史实验新增假命中，无独立测试；保持开关false和记分牌融合禁用|

## 1. 源码及正式运行边界

本轮没有再次merge/rebase、覆盖工作区、清理stash、切换部署或重启服务。正式PID465726继续运行`deploy/runtime/20261021-result-ui`，不是刚同步的Git开发工作区。

Git同一提交不代表环境、权重、未提交源码及历史产物相同。本地原有修改已保留；提交新增的是穿筐分析/审核及导入证据工具，没有新增默认投篮引擎规则。

配套报告：

- [Git身份、未提交修改和差异](GIT_HANDOVER_AUDIT.md)
- [逐项资源SHA与迁移清单](SERVER_RESOURCE_AUDIT.md)
- [正式运行源码、模型和开关](SERVER_RUNTIME_IDENTITY.md)

## 2. 本轮实际测试

|项目|结果|说明|
|---|---|---|
|只读环境审计|通过|Python3.11.15、PyTorch2.11.0+cu128、Ultralytics8.4.175、CUDA12.8、Quadro RTX5000|
|运行模型契约|通过|Attempt/Shot及证据字段导入来自同一开发树|
|定向Python测试|43通过、5失败；另28个子测试通过|5失败均在crossing_evidence_audit；缺Windows输出或仍引用D盘视频|
|完整check_all.py|**4组失败**|战术层、前端自检、前端接线、样例导航；不能宣称全绿|
|API全流程|4通过/0失败|显式隔离data/out/auth，没有写正式任务库|
|实际GPU短片|通过|2.002秒60帧，GPU0，现有BODD+person，未读取人工标签|
|原标注/历史分析保护|通过|标注与Git内容一致，正式PID和快照未变，3条历史任务raw/game SHA未变|
|已有审核器HTTP只读验证|通过|6项manifest和页面返回200；临时回环进程退出，无POST或草稿写入|
|冻结汇总工具字节核验|**拒绝**|LF/CRLF导致truth hash mismatch；未改预期SHA或绕过校验|
|31条端到端重新推理|**未运行/不可复现**|3份视频与Windows活动权重缺失|
|59次出现/57个play开发集回归|**本轮未运行**|视频可匹配，但Windows同模型/产物未齐；不能把旧报告当当前服务器实跑|

完整门禁失败细分：

- `tests/test_plan_b.py::test_tactics_end_to_end_and_frames`：测试要求每一帧都有players，t=15无可靠坐标时为空（20项通过、1项失败）。本轮没有为过测试伪造位置。
- 前端聚合失败包括`test_unknown_style.js`、`test_ui_home.js`和文案预算`test_ui_copy_budget.js`；旧断言与本机既有UI差异需单独梳理，本轮不调预算掩盖问题。
- `test_frontend_wiring.js`及`test_examples.js`也失败，完整日志在证据目录。不能把所有失败直接归咎于Git同步或全部认定为无关旧测试。
- 5项新审核测试需要`out/crossing_evidence_20261020/{baseline/results.json,event_errors.json,review/tasks.json}`等；未生成伪产物，未将失败改成跳过来宣称通过。

测试命令/退出码/耗时见[tests.json](out/server_git_handover_20261021_205145/tests.json)；[完整门禁日志](out/server_git_handover_20261021_205145/full_gate.log)、[定向测试日志](out/server_git_handover_20261021_205145/targeted.log)。

## 3. GPU小样本结果和边界

输入从已有`data/samples/validation_lillard_8s.mp4`截取2秒，保存本轮输入SHA；重新编码是本轮独立smoke输入，不冒充31条冻结原片。推理使用现有CUDA环境与BODD权重，球员检测开启，两个ROI补检关闭，比分牌OCR关闭，不启用实验穿越窗口。

- 解码帧：60；输入fps：29.97003。
- 检测+流水线：5.558秒，约10.80处理fps（含冷启动）。
- 其中模型/视频准备约3.448秒，检测阶段约2.038秒；不能由2秒片段推断长视频整体性能或宣称加速。
- PyTorch峰值分配约52.08MiB，仅本测试进程的统计，不是整张卡显存。
- 自动事件0条；没有该窗口精确真值，**不据此评估投篮召回或命中准确率**。
- [raw_track JSON](out/server_git_handover_20261021_205145/gpu_smoke/raw_track.json)、[分析game.json](out/server_git_handover_20261021_205145/gpu_smoke/analysis/game.json)、[诊断视频](out/server_git_handover_20261021_205145/gpu_smoke/diagnostic.mp4)、[指标](out/server_git_handover_20261021_205145/gpu_smoke/smoke_metrics.json)。

## 4. 31条冻结基线及跨平台身份

历史保存结果：出手TP/FP/FN=26/7/5，P/R/F1=78.79%/83.87%/81.25%；命中7/3/3，P/R/F1=70%/70%/70%。保存的33条引擎事件中UNKNOWN=20，其中14条已匹配、6条未匹配。此处是旧产物重计/报告，不是新GPU结果，也不是独立测试。

Windows记录的真值SHA`0e8e…`，当前Git LF版本SHA`bd4c…`；仅内存LF→CRLF能够精确重现原SHA，TXT原件也存在同样换行差异。原始JSON、TXT、冻结记录和预期SHA均未改。`summarize_frozen_baseline.py`原样执行拒绝哈希不符，日志完整保留；下一步应明确保存字节身份与跨平台序列化映射，不能静默改SHA。

Windows为Python3.13、PyTorch2.14+cu126、Ultralytics8.4.146、RTX4060 Laptop；服务器为Python3.11、PyTorch2.11+cu128、Ultralytics8.4.175、Quadro RTX5000。更重要的是活动模型SHA不同，不能把两环境输出当同模型严格A/B。未升级依赖、未替换权重。

## 5. 三视频人工记录及审核状态

三原视频均按SHA匹配，本轮无需重复迁移；具体路径见[local_annotation_paths.json](out/server_git_handover_20261021_205145/local_annotation_paths.json)。规范化JSON保留原Windows路径，Linux索引独立生成。按原文件59次画面记录、57个play_id：杨10、利15（去回放13）、哈34；全部Development。

人工分值确认文件存在，但不等于逐帧球/篮圈开口已审核。harden_14精确离手仍待补；整场来源身份、完整原片偏移和负例细类标注不完整，不能将31+57称为88个独立样本。

新增5条穿筐任务涉及game01的1/15/170秒、game03的56/158秒；生成脚本和网页已同步，但依赖的Windows原片、状态trace与审核产物未在服务器，当前不能提供真实可操作的这5项入口。`build_crossing_review.py`还硬编码Windows ffmpeg路径，需要迁齐证据后做Linux参数化修复，不能伪造trace恢复页面。

服务器旧集中6项任务仍齐备，含552张图和视频。利拉德first/block两项有部分人工记录但status仍pending，其余4项未保存完整审核，training_approved没有启用。已验证既有审核器HTTP接口，保留用户草稿，未重复生成任务。

需要继续旧6项审核时，可在Ubuntu自行启动原工具（本轮未留下常驻服务）：

```bash
cd /data/projects/ai-basketball-analyst
PYTHONPATH=src /data/conda-envs/ai-basketball-analyst/bin/python \
  scripts/serve_match_labeling.py \
  --batch out/stage2_review_20261018_194735/review --port 8128
```

然后在该Ubuntu打开`http://127.0.0.1:8128/`。这不是新5项穿筐审核页，也不是正式网站。新页面的localStorage草稿需从Windows导出，不能由当前服务器推断。

## 6. 下一步最高优先级

1. 先迁移3个冻结原片、SHA800dab7c…权重及3份Windowsout证据目录；权重放独立评估路径，不改变生产优先级。
2. 显式处理标注字节/换行身份和Linux路径映射，再按相同模型、视频、容差与配置恢复31条复现；本轮不“修正”旧标签/预期SHA。
3. 恢复真实5项穿筐审核入口，导入用户导出的JSON；人工完成后才讨论开口证据单因素实验。
4. 修复现有完整门禁失败并保留各失败基线，不进行大型算法改造。已有原生断言不能为了页面连续而填假球员。
5. 59次出现/57play按Development评估；game03已暴露，不能充当独立测试。独立跨比赛材料仍需按真实比赛来源另行锁定。
6. 算法启用或任何生产部署须另行验收；本次没有发布新算法的条件和动作。

## 7. 复查命令

```bash
cd /data/projects/ai-basketball-analyst
# 只读比较提交关系
 git rev-parse HEAD
 git rev-parse origin/main
 git rev-list --left-right --count HEAD...origin/main
# 新目录保存审计材料，不变更Git/服务
/data/conda-envs/ai-basketball-analyst/bin/python \
  scripts/audit_server_handover.py --out out/server_handover_recheck_new
# 定向测试会通过conftest隔离API存储
PYTHONPATH=src /data/conda-envs/ai-basketball-analyst/bin/python -m pytest -q \
  tests/test_shot_legacy_geometry.py tests/test_crossing_evidence_audit.py \
  tests/test_crossing_window_experiment.py tests/test_stage2_audit.py \
  tests/test_runtime_contract.py tests/test_score_guided_recovery.py \
  tests/test_collect_cv_baseline.py
```

完整门禁本轮设置`AIHOOP_DATA_DIR`和`AIHOOP_OUT_DIR`到本次证据目录下的隔离目录，并把已有node工具目录加入PATH。不要通过未隔离的旧脚本将合成任务写入正式库；实际测试命令、环境路径和全部日志都随本报告交付。

## 8. 本轮文件改动

仅新增只读采集脚本`scripts/audit_server_handover.py`、本报告和3份配套Markdown；证据、GPU视频、路径映射、序列化对照写在新out目录。不修改产品源码、模型、人工真值、默认配置和用户历史分析。采集脚本本轮内部修正了两个资源索引拼写/层级，安全清单记录该变化；未重复跑全量推理。
