# NBA 30秒漏检调查、模型对照与离线比分回溯

日期：2026-10-16。承接 [原交付](CV_DELIVERY_2026-10-15_2157_TO_2026-10-16.md)、[步骤3](CV_STEP3_2026-10-16.md)、[步骤4](CV_STEP4_2026-10-16.md)、[步骤5](CV_STEP5_2026-10-16.md) 和 [标注规范](CV_ANNOTATION_PROTOCOL.md)。

项目：`/data/projects/ai-basketball-analyst`。
证据根目录：[nba_investigation_20261016_195859](../../out/nba_investigation_20261016_195859)。

## 1. 结论与未完成项

**已经定位0事件的直接阻断链，尚未解决本片的自动投篮漏检。** 默认配置、四组ROI和1280高密度实验仍是0事件。没有把自动候选当作真实出手，也没有降低出手/穿筐/未中条件凑数量。

1. 基线902帧始终是 `IDLE`。球和新鲜篮筐同时可用的47帧，全部未满足接近篮筐的水平距离要求；其中28帧还不满足高度要求。状态机根本没有建立attempt，阻断发生在命中判断之前。
2. 篮球问题包括模型未给出候选、固定57.6px上限拒绝近景真球、时序/固定干扰过滤；不是只保留最高置信度造成的单一问题。不能凭框数判断真球召回。
3. 篮筐主要是粗hoop/篮网框与篮圈几何不符、像素细化失败、连续确认不足，以及摇摄时跳变拒绝/EMA滞后；旧位置在1.5秒有效期内仍可能与当前画面不符。
4. 两ROI实际触发，但球ROI依赖近期球、筐ROI依赖新鲜筐，缺少两者时不能启动；ROI不是全局找筐的后备检测器。
5. 球员关联失败不是本次0事件的直接门槛；原引擎允许未知出手人。时间戳和抽帧也不是本片主因：球逐帧处理，PTS检查误差小于0.000084秒。
6. 本片先是终场庆祝，后为广角及近景回放；开始已经显示 `115:118 FINAL`。它不能用来证明比分上涨回溯能补回真实投篮。
7. 已完成离线回溯原型及实际运行。完整177秒利拉德视频的一次敏感性实验记录到稳定显示变化，并回查原始196帧；**仍未补回可确认的投篮**，未知球员/结果保持UNKNOWN。

缺少该30秒片段的完整、经人工审核的球框、篮圈开口和逐次出手真值。因此本片球TP/FP/FN、篮圈定位误差、出手/命中P/R、回溯补回率仍为**尚不可计算**。11张旧审核帧只用于开发子集的模型对照。

## 2. 输入与运行边界

| 项目 | 实际内容 |
| --- | --- |
| 视频 | data/samples/validation_lillard_30s.mp4，1280×720，902实际解码帧，30.096744秒 |
| SHA-256 | cf6c1a647900e38f581e6cec2fe6ba8f6b3f7b0d0131db38296b684c29834352 |
| 基线trace | out/cv_step5_gpu_defaults_20261016/01_validation_lillard_30s_none/raw_track.json |
| trace SHA-256 | 1b803b2b3d5d19f73d3b702b01d9ebd0ca00a73a0d6bb8e0fec59fa14cc36766 |
| 时间基准 | 原始解码帧号从0开始；t=frame/fps；本片另核对原始PTS |
| 基线人员 | COCO yolov8n + 原BoT-SORT，person stride2；球检测逐帧 |
| 基线检测 | E-BARD四类模型，standard640，原缺球960级联仍在；ball_conf=.25 |
| 基线标记 | 未标球场、未输入人工筐框；不能由这个隔离测试判断网页人工框是否传递失败 |
| 硬件 | Quadro RTX5000 16GiB，驱动595.84，torch2.11.0+cu128，CUDA12.8，Ultralytics8.4.175，OpenCV5.0.0 |

完整环境见 [environment.json](../../out/nba_investigation_20261016_195859/environment.json)。原始PTS见 [pts_check.json](../../out/nba_investigation_20261016_195859/pts_check.json)：902帧，first=0、last=30.063375，帧间隔0.033312～0.033376秒。此前文件头1044帧的问题已修复，本轮没有重复实现时长修复；其它VFR素材仍不能据此宣称已验收。

## 3. 逐帧证据与拒绝原因

直接打开 [完整诊断视频](../../out/nba_investigation_20261016_195859/final_diagnostic_with_players/diagnostic.mp4)。902帧，1280×880，约30.097秒。

- 绿色：最终模型篮球；黄色：预测；红色：被拒候选；蓝色：筐候选；紫色：跟踪筐，标明TRACKED/STALE；灰色：人员临时框。
- 面板显示原始帧号、时间、球/筐状态和阻断原因。
- [逐帧JSONL](../../out/nba_investigation_20261016_195859/final_diagnostic_with_players/frames.jsonl) 还保留候选置信度、坐标、来源、人员/头部上下文、原状态机证据与重新计算的像素轮廓拒绝原因。
- [逐帧CSV](../../out/nba_investigation_20261016_195859/final_diagnostic_with_players/frames.csv) 用于筛选；[汇总](../../out/nba_investigation_20261016_195859/final_diagnostic_with_players/summary.json) 用于复核计数。
- [候选联系图](../../out/nba_investigation_20261016_195859/candidate_evidence.jpg)、[篮筐局部图](../../out/nba_investigation_20261016_195859/rim_crops.jpg)、[模型对照图](../../out/nba_investigation_20261016_195859/model_comparison_contact.jpg) 供快速查看。

“原始候选”指YOLO阈值/NMS之后、业务过滤之前的输出，不是未经NMS的神经网络张量。低于候选下限的目标不可从这些框中反推出来。程序逐帧分析覆盖全片，工程画面抽查不冒充完整人工标注。

### 3.1 关键帧

| 原始帧 / 秒 | 实际证据 | 原流程阻断 |
| --- | --- | --- |
| 360 / 12.012 | hoop .791，约[604.6,181.9,645.8,231.4]；球未进入本帧基线候选 | 粗框高于宽，被invalid_shape拒绝；细化的30×26px连通区域aspect约1.15，不是合格横向篮圈 |
| 400 / 13.347 | 场上持球画面，基线无ball候选；hoop .745，[606.5,180.6,648.2,229.9] | 像素区域24×22被pixel_aspect_rejected，其余小碎片被尺寸拒绝；不能凭粗框裁出假筐口 |
| 442 / 14.748 | 仅有预测球；粗hoop及细化仍不合格 | 预测不是测量；筐已过期；未建立attempt |
| 500 / 16.683 | 真像素细化得到[480,185,525,205] | 远处重捕处于pending_confirmation；连续确认不足，不能直接恢复旧筐身份 |
| 780 / 26.026 | ball .562，[902.8,182.8,950.1,233.5]；跟踪筐中心约(394.3,299.6)、宽45.0 | 水平距离约532px，门限约225px；在远处离手阶段原近筐attempt门槛不满足 |
| 800 / 26.693 | ball .343；新细化筐约[344,632,404,654] | 镜头跟球移动，真实新候选被jump_rejected；旧筐仍保留在约(363.0,395.8) |
| 813 / 27.127 | ball .584，约58.3×56.8px | 宽超过57.6px，被size_rejected |
| 820 / 27.361 | ball .581，约73.3×77.0px，图中可见飞行球 | 宽高超过57.6px，业务过滤拒绝了已进入YOLO的目标 |
| 850 / 28.362 | ball .697的大框约116.7×112.3px | 仍被尺寸拒绝；图中框覆盖篮网/球重叠区域，不能未经审核把放行它算成正确检球 |
| 860 / 28.695 | hoop .375，[678.3,168.5,840.7,355.5]；无ball候选 | 粗区域不是筐口，颜色碎片小于所需宽度，细化失败；旧筐已过期 |

关键模型框见 [keyframe_model_candidates.json](../../out/nba_investigation_20261016_195859/keyframe_model_candidates.json)。细化全部轮廓的局部坐标相对各行 `search_box`，不能直接当原视频坐标；选出的pixel_candidates才是原图坐标。

### 3.2 全片阻断统计

| 条件 | 帧数 |
| --- | ---: |
| 无最终模型篮球测量 | 773 |
| 无新鲜筐 | 741 |
| 球与筐同时可用 | 47 |
| 上述47帧中，球在接近半径之外 | 47 |
| 上述47帧中，球还低于允许的接近高度 | 28 |
| 状态机IDLE | 902 |

这些条件存在重叠，不能相加当失败帧总数。模型ball候选审计包括34次尺寸拒绝、2次person_head、14次screen_static、15次motion_rejected；每次拒绝是否错误需要逐框真值。

原调用链仍为：`VideoSource → 整帧/级联/可选ROI → preview_ball → LegacyShotStream.update → ScoreEngine`。
ScoreEngine先要求真实球和新鲜筐，并满足 `abs(ball_x-rim_x)<max(5*rim_w,30)` 以及高度条件，之后才建立attempt并回查归属。由此证明不是“没识别号码所以不记录出手”。

镜头直方图的13次报警中保留1处切镜、12处被已有背景几何复核保留。该复核不等于可靠的回放识别；固定画面坐标与变焦/摇摄处理仍不完善。延长筐有效期只会延长旧坐标污染，不作为本轮修复。

## 4. 模型与分辨率对照

所有模型使用同一个原视频902帧、相同conf候选下限.15、NMS IoU=.5，逐帧候选另存JSONL。并用**同11张已审核完整开发帧、8真球框、3无球帧、3个比赛来源**计算同一IoU≥.5指标。没有新增/修改人工标签。

| 模型 | imgsz | conf=.25 TP / FP / FN | conf=.15 TP / FP / FN |
| --- | ---: | --- | --- |
| E-BARD默认 | 640 | 3 / 4 / 5 | 3 / 10 / 5 |
| E-BARD默认 | 960 | 2 / 6 / 6 | 2 / 7 / 6 |
| E-BARD默认 | 1280 | 2 / 6 / 6 | 2 / 9 / 6 |
| ShotTracker best | 640 | 0 / 34 / 8 | 0 / 37 / 8 |
| ShotTracker best | 960 | 0 / 117 / 8 | 0 / 132 / 8 |
| ShotTracker best | 1280 | 0 / 187 / 8 | 0 / 211 / 8 |
| ShotTracker before_best | 640 | 0 / 58 / 8 | 0 / 81 / 8 |
| ShotTracker before_best | 960 | 0 / 213 / 8 | 0 / 259 / 8 |
| ShotTracker before_best | 1280 | 0 / 433 / 8 | 0 / 503 / 8 |

详细P/R/F1、逐图匹配、权重SHA见 [主要模型对照](../../out/nba_investigation_20261016_195859/model_comparison/comparison.json) 和 [before_best对照](../../out/nba_investigation_20261016_195859/model_backup_comparison/comparison.json)。E-BARD640/.25仍为P42.86%、R37.50%、F1 40%；扩大输入没有在这些审核帧上提高TP。

旧eval_ball_feedback没有显式指定NMS；本机Ultralytics默认IoU=.7。本轮固定为.5，所以.15下的10FP不能与旧11FP混称准确率提升。

NBA关键帧对照可见ShotTracker还有覆盖大块观众/场景的basketball候选。它在自己训练风格素材的表现不能代表电视转播NBA。**保留当前默认权重。**

本片没有完整审核球框/筐口真值，因此这里没有报告NBA的TP/FP/FN或篮筐中心误差。篮筐框质量目前仅有粗框/细化/真实图像的工程证据；“可用帧数”不是篮筐Recall。所有已用于开发的来源继续为development；独立测试集仍待提供并锁定，没有拿邻帧随机切分。

## 5. 原ROI与高密度实验

相同E-BARD模型、原VideoSource主流程、GPU0、person stride2，无OCR、无高光/叠框输出。球主检测仍逐帧，不存在把球从5Hz改成30Hz的收益；15Hz指的是缺球重试节拍。

| 配置 | 模型测量球帧 | 内部筐可用帧 | 球/筐ROI实际调用 | 事件 | 单次耗时 |
| --- | ---: | ---: | --- | ---: | ---: |
| ROI关闭 | 129 | 161 | 0 / 0 | 0 | 30.33s |
| 球ROI | 130 | 161 | 44 / 0 | 0 | 29.55s |
| 筐ROI | 129 | 161 | 0 / 17 | 0 | 29.75s |
| 双ROI | 130 | 161 | 44 / 17 | 0 | 29.72s |
| 1280 + .15候选多帧确认 + 15Hz双ROI | 93 | 150 | 99 / 60 | 0 | 31.09s |
| 仅尺寸上限从.06改.16，ROI关闭 | 155 | 161 | 0 / 0 | 0 | 30.66s |

[ROI完整对照](../../out/nba_investigation_20261016_195859/roi_comparison/comparison.json)、[高密度对照](../../out/nba_investigation_20261016_195859/dense1280/comparison.json)、[尺寸对照](../../out/nba_investigation_20261016_195859/size_only/comparison.json)。高密度一行改变了多项参数，只是组合压力实验，不用于归因某一个模块。

球ROI半径96～384px，依赖0.5秒内实测锚；筐ROI半径至少96px、通常5个筐宽，要求fresh。两者只补检篮球，最多两次裁剪，原坐标只加一次offset。未初始化/过期筐、无近期球、未到重试节拍、已有合格球都会抑制相应补检。

尺寸实验放行了26帧原先受上限阻挡的候选，包括27秒飞行球，也包括28秒篮网重叠的大框，见 [逐帧差分](../../out/nba_investigation_20261016_195859/size_gate_ablation_evidence.json)。**不把26帧算成26个TP，不默认提高上限。** 它证明尺寸阻断存在，也证明单改尺寸不解决筐几何和attempt建立。

旧素材Dairy重新跑836帧：223模型球帧、835筐可用帧、1次UNKNOWN，35.61s，与原默认事件结果一致。见 [旧素材回归](../../out/nba_investigation_20261016_195859/dairy_regression/comparison.json)。

耗时是单次记录，不能从亚秒波动推断加速；模型对照的批量检测FPS不等于包含人员追踪/OCR/视频输出的系统FPS。

## 6. 离线记分牌回溯原型

新增 `score_guided_recovery.py` 与 `experiment_score_recovery.py`，不接入API或玩家统计。

```text
既有EasyOCR / logo_scoreboard.scan
 → 保存原读数、置信度及失败样本
 → 既有scoreboard_fusion.score_changes多帧确认
 → 低置信度/切镜/显式回放或FINAL区间/比分回退隔离/重复变化否决
 → 独立的比分显示事实 + 3～12秒回查任务
 → 原YOLO、两ROI、LegacyShotStream、原ScoreEngine高分辨率逐帧再分析
 → 独立视觉证据，UNKNOWN及待审核关联；不写Attempt、不更新计分
```

- +1单独标FREE_THROW_OR_SPECIAL_UNKNOWN，默认不启动运动战回查。
- +2/+3也不直接创建MADE；保留 `physical_score_verified=false`、未知得分类型。
- 显示左右不自动对应主客队。只有同视频SHA、review_status=approved的显式team-map才用于关联。
- 关联需要已知同队、类型一致、无切镜、唯一候选且一对一；没有足够身份/上下文时保留SCORE_CONFIRMED_SHOOTER_UNKNOWN。
- 回溯保持原视频帧号/时间；修复了原型中“取整后漏掉四舍五入时间对应尾帧”的问题，以ceil包含边界，EOF按最后实际解码帧结束。
- 复用同源人员/切镜缓存和同一模型实例；重叠回查窗口缓存同参数整帧检测。ROI受窗口状态影响继续独立运行，最多两次/重试帧。
- 回放/FINAL区间目前可由外部场景审核清单提供；**没有实现可靠的自动回放分类**。未知回放仍可能造成显示变化歧义，不能因此启用自动统计。

### 实际运行

| 输入/设置 | 结果 |
| --- | --- |
| 30秒片段、紧ROI、既有严格scan | 有效读数不足，运行失败；日志保留，不伪造结果 |
| 30秒片段、留边ROI、诊断模式 | 16样本仅3个解析pair，usable=false；可见115/118被错读为115/78；0稳定变化，0回查任务 |
| 完整177秒视频，截取前140秒OCR、默认confidence_floor=.90 | 280样本206个解析pair；过滤后167条高置信度读数；0确认变化，更新附近读数间隔不足 |
| 同一份原始OCR缓存，显式离线confidence_floor=.85敏感性实验 | t=6.506显示113:105→113:107，+2，支持置信度下界.8631；回查0～6.506秒，实际196帧，0视觉事件，出手人/结果UNKNOWN |

结果见 [30秒OCR原始诊断](../../out/nba_investigation_20261016_195859/ocr_lillard30_audited/ocr_reference.json)、[完整视频OCR缓存](../../out/nba_investigation_20261016_195859/ocr_full_lillard/ocr_reference.json)、[默认回溯](../../out/nba_investigation_20261016_195859/ocr_full_lillard/recovery.json)、[.85敏感性实验](../../out/nba_investigation_20261016_195859/ocr_full_sensitivity085_final/recovery.json)、[原始196帧回查证据](../../out/nba_investigation_20261016_195859/ocr_full_sensitivity085_final/window_00.json)。

.85是独立OCR敏感性配置，未改投篮判据或默认.90，也没有变成线上配置。一次稳定显示变化不能证明物理进球、得分类型或球员身份。+1/+3、抖动、回放回退、双投篮歧义、一对一关联目前有自动化构造测试；实际素材上的完整正确率尚未验证。

## 7. 实际代码改动与开关

本轮没有重新实现YOLO、BoT-SORT、球追踪器、ROI或投篮状态机。

| 文件 | 本轮修改 |
| --- | --- |
| src/aihoop/legacy_shots/settings.py | 将已有ball_max_reference_ratio暴露为受校验配置，默认仍.06；增加可选过滤/轮廓诊断开关 |
| src/aihoop/legacy_shots/stream.py | 开启诊断时保存实际尺寸上下限与候选宽高；没有改变选择或出手逻辑 |
| src/aihoop/hoop.py | 复用原轮廓提取，选开时记录尺寸/高宽比/颜色/上下文拒绝原因；不改变篮圈接纳规则 |
| src/aihoop/logo_scoreboard.py | diagnostic模式保留失败OCR词、置信度、帧号和usable状态；默认仍按原规则拒绝有效读数不足 |
| src/aihoop/score_guided_recovery.py | 新增默认关闭的离线调查策略；显示事实与投篮分开，不写线上统计 |
| scripts/diagnose_nba_clip.py | 全帧诊断视频/CSV/JSONL、原始帧审核任务、可选像素拒绝复算 |
| scripts/compare_nba_detectors.py | 同输入/审核帧、模型/分辨率对照，保存逐图TP/FP/FN及权重/源码SHA |
| scripts/experiment_score_recovery.py | 离线OCR、原始时间窗口回查、同源缓存复用及保守关联 |
| scripts/serve_match_labeling.py | 现有本机标注器允许rim开口框；没有开放person角色或自动批准训练 |
| web/match-labeling.html | 修复写死的30～90秒/8帧文案与帧号当秒；按manifest换算时间，支持查看前后上下文及框篮圈 |
| tests/test_nba_diagnostics.py | 尺寸默认与选开、预测隔离、轮廓拒绝、标注校验、密集回查时间与缓存保护 |
| tests/test_score_guided_recovery.py | +1/+2/+3、低置信度、抖动、回退/回放、切镜、未知映射和歧义、失败OCR留证 |
| tests/test_nba_review_ui.js | 帧号/原秒映射及旧文件兼容 |
| docs/audits/CV_ANNOTATION_PROTOCOL.md | 补充NBA审核任务与rim完整性边界 |

配置：

| 项 | 默认 | 含义 |
| --- | --- | --- |
| legacy_detect.ball_max_reference_ratio | .06 | 上限=min(.24×原图宽, ratio×min(原图宽,960))；.16只用于本轮消融 |
| legacy_detect.ball_filter_diagnostics | false | 保存尺寸门限/候选宽高 |
| legacy_detect.rim_refinement_options.contour_diagnostics | false | 保存原颜色轮廓被拒原因 |
| logo_scoreboard.scan(diagnostic=...) | false | 默认错误行为兼容；true保留低质量OCR证据 |
| RecoveryOptions.enabled / CLI --enable | false | 离线回溯明确启用 |
| confidence_floor | .90 | .85仅本轮敏感性比较；不能自动转成MADE |
| lookback_min_s / lookback_max_s | 3 / 12 | 回查范围；片头按0截断 |
| max_windows | 6 | 有界回查数量 |
| allow_one_point_reanalysis | false | 不把+1默认当运动战 |
| --reanalyze | false | 额外YOLO1280、.15候选多帧确认、15Hz双ROI，要求同视频forward trace |

最终源码快照与本轮专属差分见证据目录 `final_source/`、`this_round.patch`、`round_files.json`。原工作区已有大量其他修改，不把整个git diff冒称本轮改动。

## 8. 测试、失败与线上边界

- 相关回归：103 passed，2.11s，见 `targeted_tests_final.log`。
- 全量项目测试：621 passed、2 failed、15 skipped、9 subtests passed，27.14s，见 `python_tests_final.log`。
- 全量后仅离线缓存/CLI与审核页细节调整，20项新增测试及审核页JS再次通过，见 `final_new_tests.log`、`review_ui_tests_final.log`。
- Attempt/Shot运行契约检查通过，见 `runtime_contract.log`。
- 本机标注器HTTP检查通过：11组/902帧、图片200、视频Range206，未写标注；文档引用及报告32个本地链接通过。见 `review_http_check.json`、`doc_refs.log`、`report_links_check.json`。
- 首次裸 `pytest -q`误收集固定副本内的同名测试，产生83个collection error；没有删除快照/缓存来隐藏它。改用显式 `pytest -q tests`，原始失败日志 `python_collection_failure.log` 保留。
- 既有失败仍为 `test_multical_mini_and_snap::test_soft_failure_exit_carries_both_keys`（标定失败文案）及 `test_plan_b::test_tactics_end_to_end_and_frames`（合成战术空人员断言），未修改断言。
- 实测失败项：NBA默认仍0事件；30秒严格OCR读取不足；默认.90的完整视频回溯未确认变化；.85回查未恢复视觉出手；缺少标注的指标不验收。
- 浏览器中完整人工标注操作和新功能上线尚未验收。

线上复核见 [live_runtime_check.json](../../out/nba_investigation_20261016_195859/live_runtime_check.json)：服务PID262365仍active，固定副本171文件SHA全部匹配；PYTHONPATH仍为20261016-152930，`AIHOOP_DISABLE_SCOREBOARD_FUSION=1`。本轮未重启服务、未覆盖运行副本、未修改线上权重、未写用户分析结果、未训练或推送。

## 9. 可复现命令

以下从项目根执行；输出目录必须选新名字，工具拒绝覆盖已有实验。

```bash
cd /data/projects/ai-basketball-analyst
AIHOOP_PY=/data/conda-envs/ai-basketball-analyst/bin/python
export PYTHONPATH=src

# 基线逐帧证据、诊断视频和902张待审核原帧
"$AIHOOP_PY" scripts/diagnose_nba_clip.py \
  --raw out/cv_step5_gpu_defaults_20261016/01_validation_lillard_30s_none/raw_track.json \
  --rim-pixels --review --out out/nba_repeat_diagnostic_01

# 三权重、三个输入尺寸；同一视频及旧审核帧
"$AIHOOP_PY" scripts/compare_nba_detectors.py \
  --video data/samples/validation_lillard_30s.mp4 \
  --weights models/BODD_yolov8n_0001.pt models/shottracker_best.pt models/shottracker_before_best.pt \
  --out out/nba_repeat_models_01

# 复用原工具四组ROI，完整主流程
"$AIHOOP_PY" scripts/benchmark_ball_recovery.py \
  --videos data/samples/validation_lillard_30s.mp4 --modes none ball rim both \
  --out out/nba_repeat_roi_01

# 本轮1280组合压力实验
"$AIHOOP_PY" scripts/benchmark_ball_recovery.py \
  --videos data/samples/validation_lillard_30s.mp4 --modes both \
  --detect-options out/nba_investigation_20261016_195859/dense1280.json \
  --out out/nba_repeat_dense_01

# 30秒OCR失败也保留原始词/置信度；不自动产生投篮
"$AIHOOP_PY" scripts/experiment_score_recovery.py \
  --video data/samples/validation_lillard_30s.mp4 --enable \
  --ocr-box 920,570,212,42 --ocr-end 8 \
  --forward-raw out/cv_step5_gpu_defaults_20261016/01_validation_lillard_30s_none/raw_track.json \
  --out out/nba_repeat_ocr30_01

# 同一完整视频OCR缓存的.85敏感性回查；视频SHA必须匹配
"$AIHOOP_PY" scripts/experiment_score_recovery.py \
  --video deploy/runtime/20261016-152930/data/compatible/d8b5b37c3d5f8841/lillard-buzzer-beater-BV165YQ68E3C_9e1bbd21c5.mp4 \
  --reference out/nba_investigation_20261016_195859/ocr_full_lillard/ocr_reference.json \
  --forward-raw out/c299e023441c/raw_track.json \
  --enable --confidence-floor .85 --reanalyze --max-windows 1 \
  --out out/nba_repeat_recovery_01

# 现成11组原帧的人工标注入口，仅监听本机
"$AIHOOP_PY" scripts/serve_match_labeling.py \
  --batch out/nba_investigation_20261016_195859/cached_diagnostic/review --port 8127
```

标注页打开 `http://127.0.0.1:8127`。本轮交付没有启动常驻标注服务或公开这些原帧。

```bash
PYTHONPATH=src /data/conda-envs/ai-basketball-analyst/bin/python -m pytest -q \
  tests/test_score_guided_recovery.py tests/test_nba_diagnostics.py

out/cv_baseline_20261015/tools/node tests/test_nba_review_ui.js

PATH=/data/projects/ai-basketball-analyst/out/cv_baseline_20261015/tools:$PATH \
PYTHONPATH=src /data/conda-envs/ai-basketball-analyst/bin/python -m pytest -q tests

PYTHONPATH=src /data/conda-envs/ai-basketball-analyst/bin/python scripts/check_runtime_contract.py
```

## 10. 下一轮顺序与回退

1. **先审核24～30秒与12～18秒**：[近景片段](../../out/nba_investigation_20261016_195859/review_clips/release_rim_closeup.mp4)、[广角片段](../../out/nba_investigation_20261016_195859/review_clips/wide_replay.mp4)、[annotation_queue.json](../../out/nba_investigation_20261016_195859/annotation_queue.json)。确认真实球、篮圈开口、离手/过筐区间及重复回放play_id；全部11任务目前pending，不能拿空shots列表当0出手真值。
2. 优先修正镜头移动/变焦下的篮圈观测及关联：复用已有hoop_lock/frame_motion，区分模型观测与运动预测。背景变换只能帮助关联，不能刷新真实筐观测时间；验证旧素材后再考虑默认开启。
3. 做有上下文和负例回归的篮球尺度适配，优先保留远景/模糊球，控制人头、Logo和篮网误检；不要直接全局提高尺寸上限或降低所有confidence。
4. 在已审核的真实离手/球飞行/穿筐片段上改进原attempt前的持球—离手证据，避免只等待近筐球。先与原门限并行记录候选，再决定状态转移；不把向上运动当投篮。
5. 补一段连续、比分更新清晰的完整比赛窗口，标OCR实际读数、罚球/纠错、延迟与回放；先验收回溯和一对一关联，继续保持线上融合关闭。
6. 然后推进人员角色、同队外观、多帧号码与跨镜头身份；另锁定未参与开发的NBA/CBA独立比赛。

当前没有充分证据建议立即重训。若审核后发现真球长期不进入多分辨率/ROI候选，再按比赛来源分组扩充远景、模糊、遮挡正例和头/Logo/广告负例。局部纠错审核后才可训练，且不能冒充整帧完整标注。

回退方式：诊断开关恢复false、尺寸比保持.06、不调用离线--enable；代码只按 `this_round.patch` 审核本轮文件或选完整快照，不能reset整个已有脏工作区。运行中的固定副本本轮没有变化。
