# 第二阶段第一部分：集中人工审核、来源隔离与补检评估（2026-10-18）

交付时间：2026-10-18T20:07:44.992985+08:00。根目录`/data/projects/ai-basketball-analyst`；证据`out/stage2_review_20261018_194735/`。先阅读指定5份材料，沿用既有标注器、VideoSource、LegacyShotStream、RimTracker、OCR回溯与审核帧评估器。本轮不部署、不重启正式服务、不训练/更换权重、不改线上比分融合、不覆盖原任务。所有正式视觉结果仍由原状态机产生；实验结果只在新目录。

## 1. 现在可操作的审核入口

**[集中审核页面](http://127.0.0.1:8128)**，在本Ubuntu打开。已实际启动的是独立回环审核器，不是生产API。另一台电脑可先执行`ssh -N -L 8128:127.0.0.1:8128 john@<Ubuntu服务器地址>`，再打开相同URL；没改公网网站或发布素材。

| 任务 | 原片范围 | 逐帧图 | 要确认的内容 |
| --- | --- | ---: | --- |
| 利拉德首次动作 | 0～4秒 | 120 | 是否出手、离手范围、命中/分值 |
| 利拉德篮下动作 | 19.5～23.5秒 | 120 | 上篮、盖帽、未中与随后回抛；动作与回放关系 |
| 杨瀚森当前任务 | 5.6～7秒 | 42 | 真实球是否穿筐、是否命中、真实球队 |
| 利拉德运球 | 12～15秒 | 90 | 完整负例审核，不按原描述直接认定无出手 |
| 利拉德争球 | 24～27秒 | 90 | 争球/篮板/短出手是否存在 |
| 利拉德传球 | 27～30秒 | 90 | 传球与真实投篮区分 |

合计552张原尺寸JPEG。每项提供原视频上下文预览、原片/转码SHA、原片秒、逐帧/慢速/滑块、人工ball/rim/person/decoy框、人员角色、三个算法证据视图（旧分析、640、1280）、审核状态与保存。算法原始候选是**YOLO阈值/NMS后的候选，不是logits**；最终球/预测与拒绝原因独立展示，切换证据不会复制成人工框。

预览使用已有H264兼容视频；利拉德原片SHA d8b5b37c…、预览b56a5705…，已有PTS验证最大差0.000058秒；杨瀚森原片5d2ca919…、预览af8c5ab3…。杨瀚森精确原片PTS映射仍需补审核；标注声明compatible frame/fps时间依据，未冒称原AV1像素一致。各JPEG SHA随任务保存。原片时间与旧cf6c1a64回放剪辑仍分开。

### 怎样填写，不要求记精确时间

1. 先看视频，是否出手、结果、分值与球队能确认的填写；看不清选未知。
2. **动作编号（原play_id）可留空。** 如同一球在比赛画面和两次回放中出现，三个记录用同一个“投篮1”；不同出手换编号。不能仅按时间相近合并。
3. **离手范围**：起点在球还在手上/刚要离手，终点在已经确定离手；不是飞行到篮筐的起止。暂停后点“记起点/记终点”，逐帧页也可直接记。允许宽一点，不记得精确秒也可留空；不要猜一个精确帧。
4. 真正出手仍在“出手记录”添加，已有“取当前视频时间”。如果仅有粗时间范围，在备注说明近似，不能据此计算精确离手误差；后续可逐帧补精度。多次出手分别记录。
5. 球可见才框球；篮圈只框开口；人头/Logo/篮网诱饵另框。看不清不能当无球。球、篮圈和人员完整性分别勾选，不强迫一次标完552帧。
6. 填审核人，整段看完勾选出手完整性，显式选择人工核对完成并保存。保存草稿不等于完整真值；完成人工核对也不自动批准训练，training_approved恒false。未知结果独立保留。

保存位置：[任务manifest](../../out/stage2_review_20261018_194735/review/manifest.json)与各任务目录的annotations.json。真实任务没有被自动测试写标签；浏览器保存/刷新测试写的是显式SYNTHETIC_UI_TEST_NOT_TRUTH临时任务。用户已说明新素材稍后提供，无需现在记精确时间。

## 2. 跨比赛数据与泄漏核查

[来源登记](../../out/stage2_review_20261018_194735/review/source_registry.json)、[缺失材料](../../out/stage2_review_20261018_194735/review/missing_materials.json)、[历史标注清单](../../out/stage2_review_20261018_194735/review/legacy_annotation_inventory.json)。

- 已登记5个历史Development来源：利拉德、杨瀚森、哈登、Dairy、Nathan。原片/兼容转码/旧回放保持同source_match_id；实际文件逐个核SHA、ffprobe时长/FPS/尺寸。转播样式、对阵日期等未核实字段保持pending，未凭文件名编造。
- 另发现8份SHA不同且比赛/转码关系未确认的uploads/B站/Archive文件；它们都隔离为Development待来源审核，不可凭“哈希不同”认定新比赛。
- 历史4段Windows比赛标注仍缺可核验原片/32张图片映射；导入的source_sha256是预期视频SHA，尚未在此匹配文件，不能凭名称找替身。旧标注已参与开发，迁移后仍不能成为新独立测试。
- ShotTracker仓库关联素材存在模型训练/示例重叠风险；E-BARD训练集完整来源未查清。split检查会拒绝同比赛或同SHA跨组、未经来源审核的非Development条目；近似重复、不同机位回放与训练来源人工审查仍未完成。
- 当前新增Validation=0、Independent Test=0。8条占位任务都没有视频/SHA，不计算为已收集数据。

### 需要稍后提供的材料

**4场新NBA + 4场新CBA，不同比赛**；每联赛2场Validation、2场Independent Test。每场提供：原视频或本机路径、比赛日期、双方球队、来源链接/转播台、是否用于过训练/调参；同场剪辑/回放/转码一并列出。工具负责算SHA/时长，不要求你手算。

优先连续比赛上下文，包含投篮/未中/盖帽/运球/传球/争球/观众/Logo、切镜和回放，不要只提供进球集锦。独立测试锁定后不用于反复调参。可沿用54项/18场景采集计划，但它只是起点，不代表足够泛化样本量。

## 3. 640/1280严格单因素窗口实验

同E-BARD原权重、原帧、conf=.25、两个ROI关闭、相同已缓存人员/切镜上下文与现有事件引擎；只改imgsz，交替640/1280运行次序。模型实例复用并分别暖机，GPU0 Quadro RTX5000。推理不读取人工标注。

| 窗口 | 处理帧数 | 球模型观测640/1280 | 自动事件640/1280 | 窗口流水线秒640/1280 | YOLO报告GPU推理秒640/1280 |
| --- | ---: | --- | --- | --- | --- |
| 利拉德：首次投篮 | 121 | 54 / 46 | UNKNOWN / 无事件 | 1.262 / 1.472 | 0.565 / 0.583 |
| 利拉德：上篮、盖帽与回抛 | 122 | 51 / 47 | UNKNOWN / UNKNOWN | 1.651 / 1.720 | 0.606 / 0.594 |
| 杨瀚森：穿筐与真实球队 | 44 | 27 / 34 | UNKNOWN / MADE | 0.669 / 0.771 | 0.212 / 0.226 |
| 负例待核对：运球 | 92 | 29 / 30 | 无事件 / 无事件 | 1.224 / 1.417 | 0.435 / 0.452 |
| 负例待核对：争球 | 92 | 47 / 50 | 无事件 / 无事件 | 1.411 / 1.608 | 0.436 / 0.450 |
| 负例待核对：传球 | 91 | 30 / 38 | 无事件 / 无事件 | 1.058 / 1.251 | 0.426 / 0.447 |

帧数比审核图略多，因已有reanalyze使用floor起点/ceil终点并包含末帧提供上下文；两种尺寸的源帧号和时间逐一一致。窗口耗时含解码、YOLO、候选/跟踪/事件处理，**不含首次人员/OCR、模型载入暖机、JSON写出及视频编码**；不是全系统多遍端到端加速。GPU列为Ultralytics推理计时；同步predict墙钟另存在JSON，不能冒称CUDA内核总忙碌时间。

杨瀚森1280补到6.54秒模型观测、输出MADE，但精确穿筐/队别仍待人审；由于本次窗口从5.6开始，候选release与上轮0秒起回查不同，不能把5.77/5.81差异当改善。利拉德首次动作1280反而少球/无正式事件，不能默认全视频1280。负例窗口两种尺寸无正式事件，只能报告自动输出，不能据此称误报率为0。

6个并排诊断视频及逐帧JSON在[分辨率结果目录](../../out/stage2_review_20261018_194735/resolution/)，审核页可原图切换证据。原算法正式统计与线上结果均未被这些实验改写。

### 旧审核开发帧复核与误检限制

11张完整审核Development帧、8个真球框、3张无球帧，现有评估器复用IoU≥.5、NMS=.5、conf=.25：640 TP/FP/FN=3/4/5；1280=2/6/6，与既有结论一致。该小集含head_decoy；不能外推整视频、角色、事件召回。Logo专门完整真值仍缺。

新的窗口已记录person_head/upper_graphic/size/motion等拒绝框；640/1280每框拒绝记录和原图可逐帧审核。upper_graphic、人头邻近不是已确认误检：真实球也可能进入这些区域。观众/Logo相关画面包含在全帧实验，但**缺少已审核Logo/看台完整框，无法验收这两类误检率**，已列入需补标材料。没有隐藏低置信度框来代替评估。

### 有预算触发策略

离线budget_windows从既有正向候选、近期真实球接近筐后的观测缺口、稳定显示变化生成建议，不读取标签；默认enabled=false，6秒/视频、最多3窗口，按唯一帧数硬限制，重复帧可复用已有缓存。+1不作为运动战补检触发。

这是**预算规划与约束测试**，本轮没有把建议调度自动接入线上，也没有完成整个“第一遍+预算回查”的耗时/准确率验收；高不确定性短轨迹目前仍通过原候选通道，未完成独立策略。优先顺序和窗口长度需待审核后的真实离手/负例验证；初始检测漏掉候选时，候选触发也可能漏。

## 4. 动态篮筐CPU性能

保留ORB/RANSAC、全部几何校验、RimTracker和切镜失效。新开关`legacy_detect.general.camera_feature_cache=false`复用**相邻原帧的ORB描述子，不复用未经验证的H**；缺帧/尺度变化/切镜不偷接。`camera_demand_only=false`只在compensate本来就不能消费变换时跳过（未初始化、几何帧不连续、实际观测超过.25秒），不延长真实检测时间或旧轨迹。

同视频完整VideoSource，人员检测/追踪逐次真实执行；三配置顺序original→cached→cached_demand。

| 素材 | 配置 | 全流程墙钟秒 | 进程CPU秒 | ORB提取秒 | estimate总秒 | camera总秒 | ORB调用 | 按需跳过 | 球/筐几何/事件逐字段同原始 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| lillard_first30_lossless.mp4 | original | 109.29 | 251.10 | 12.90 | 47.97 | 48.75 | 1818 | 0 | 基准 |
| lillard_first30_lossless.mp4 | cached | 101.29 | 248.74 | 6.56 | 35.10 | 42.28 | 920 | 0 | True |
| lillard_first30_lossless.mp4 | cached_demand | 87.78 | 239.06 | 3.88 | 18.92 | 22.82 | 514 | 429 | True |
| DairyCourts.MOV | original | 77.26 | 109.30 | 8.23 | 39.99 | 41.24 | 1670 | 0 | 基准 |
| DairyCourts.MOV | cached | 72.54 | 103.03 | 4.22 | 31.76 | 37.26 | 836 | 0 | True |
| DairyCourts.MOV | cached_demand | 71.79 | 102.39 | 4.25 | 31.79 | 37.31 | 835 | 2 | True |

estimate包含ORB，不可相加；camera包含几何、缩放等；进程CPU秒含线程，可超过墙钟。scene_motion_guard也会调用几何，ORB统计覆盖它；相机特定计时另列。完整流水线阶段计时在pipeline_stage_timings.json，包含模型准备。该脚本没有独立累计YOLO GPU内核时间，不能从CPU差额反推GPU加速。

利拉德109.29→87.78秒（本次约19.7%），Dairy77.26→71.79秒（约7.1%）；4组优化对照的**每帧实测球/筐/跟踪几何/切镜/正式事件均逐字段一致**，实测筐407/778帧未变。切镜机制由回归测试覆盖，两个输入的切镜实际计数按JSON记录，不能据它们证明所有切镜/缩放都安全。

每配置仅1次、次序未随机，部分测试/图像编码并发；未控制热稳态或全面观测正确性。仅为Development上的耗时观测；不开启默认、不宣称普遍提速或真实筐定位Recall提高。

## 5. 测试与工程隔离

- 最终全量：**680 passed、2 failed、15 skipped、9 subtests passed，27.89秒**（full_tests_delivery.log）。原有失败仍为软失败文案test_soft_failure_exit_carries_both_keys、synthetic战术人员为空test_tactics_end_to_end_and_frames，保留原断言。
- 本轮新Python测试17项：标注校验/完整性与HTTP真实保存/Origin隔离、按比赛与SHA分组、ORB描述子一致与失效、需求条件不复活旧筐、有界预算/+1与空输入。已通过。
- Chromium实测6任务视频readyState4、1920px逐帧图、算法框不写人框、Range206；在独立合成工作区实际填写/保存/刷新成功，无JS异常，不修改6个真实任务。最终记起止按钮另有JS时间选择回归。
- 12组窗口实验、6组完整动态筐实验，6个诊断视频帧数/hash核对。文档引用与Attempt/Shot证据往返契约通过。
- 中间失败保留：测试首次未带既有Node工具PATH导致额外FileNotFoundError；两次新增测试导入路径错误已修复，未删断言。全量最后已用正确PATH。
- 所有事件/球框准确率、归属率、传球/争球FP、篮圈IoU仍null；11张旧开发帧原始模型指标单列，不混为新算法提升。
- 最新只读核验：生产PID262365，20261016-152930的171文件哈希一致，融合禁用=1；原a099 raw SHA548789dd…未变。审核服务独立端口8128，不是发布。

## 6. 修改与复现

本轮相对before脏工作区快照去重修改14个代码/工具/测试文件：

- `scripts/benchmark_camera_budget.py`
- `scripts/benchmark_stage2_windows.py`
- `scripts/compare_stage2_reviewed_frames.py`
- `scripts/prepare_stage2_review.py`
- `scripts/render_stage2_comparison.py`
- `scripts/serve_match_labeling.py`
- `src/aihoop/frame_motion.py`
- `src/aihoop/legacy_shots/settings.py`
- `src/aihoop/legacy_shots/stream.py`
- `tests/test_camera_feature_budget.py`
- `tests/test_high_resolution_budget.py`
- `tests/test_nba_review_ui.js`
- `tests/test_stage2_review.py`
- `web/match-labeling.html`

另更新标注规范并新增本报告。before与final_source含源码快照、manifest、revision、差分；并非纯Git提交，也未reset其它工作。两个相机优化开关默认false；离线预算默认关闭；原YOLO/BoT-SORT、权重/投篮条件/记分牌融合不变。

```bash
cd /data/projects/ai-basketball-analyst
AIHOOP_PY=/data/conda-envs/ai-basketball-analyst/bin/python
export PYTHONPATH=src:scripts
export PATH=/data/projects/ai-basketball-analyst/out/cv_baseline_20261015/tools:$PATH
# 审核入口，当前已经运行；重启时确认8128未被占用
"$AIHOOP_PY" scripts/serve_match_labeling.py --batch out/stage2_review_20261018_194735/review --port 8128
# 生成新的审核工作区（所有实验/生成命令选不存在的新目录）
"$AIHOOP_PY" scripts/prepare_stage2_review.py --out out/stage2_review_repeat_new
"$AIHOOP_PY" scripts/benchmark_stage2_windows.py --plan out/stage2_review_20261018_194735/window_plan.json --out out/stage2_resolution_repeat_new
"$AIHOOP_PY" scripts/compare_stage2_reviewed_frames.py --out out/stage2_reviewed_repeat_new.json
"$AIHOOP_PY" scripts/benchmark_camera_budget.py --videos out/general_stage1_20261016_213026/lillard_first30_lossless.mp4 data/samples/shottracker/DairyCourts.MOV --out out/stage2_camera_repeat_new
"$AIHOOP_PY" -m pytest -q tests
node tests/test_nba_review_ui.js
"$AIHOOP_PY" scripts/check_runtime_contract.py
"$AIHOOP_PY" scripts/verify_doc_refs.py
```

窗口复现读取window_plan里的固定原视频/原trace SHA；真标签不进入推理。精确重现需选本轮对应源码快照；输出拒绝覆盖。回滚仅关闭两个相机实验开关；不覆盖整个工作区或线上固定副本。

## 7. 是否可以进入正式跨比赛评估

**目前不能。** 审核工具、来源模板、单因素实验和工程回归已就绪，但6项人工真值仍待用户完成；8个新比赛尚待提供，完整Logo/看台负例及角色/回放真值不足。可以继续Development工程诊断，不可以用当前素材宣称泛化或正式准确率提升。

下一步：先收3关键动作与负例的人工结论，补精确帧/穿筐/队别与回放关联；再锁定8场不同来源并完成来源泄漏审核，按Validation开发与Independent Test封存执行。预算回查在审核过的正负窗口验收后，才讨论是否接入正式流程。用户已回复新素材稍后提供。
