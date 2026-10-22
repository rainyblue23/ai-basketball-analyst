# 通用算法第一阶段交付与开发基线（2026-10-16）

## 1. 结论与范围

本轮在已有 `VideoSource → LegacyShotStream → ScoreEngine` 上实现默认关闭的通用实验功能，完成3段Development素材、A–F共18组GPU对照，以及最终候选评分的9组固定观测复算。未训练、替换模型，未重启服务、更新线上固定副本或启用记分牌融合。

**真实出手召回问题尚未解决完毕。** 完整利拉德前30秒中，用户粗标的第一次命中与约21秒被盖帽，仍没有可验证的精确离手/结果匹配；现有引擎仅输出3条UNKNOWN。旧回放剪辑修复5帧篮筐跳变拒绝，正式引擎从0条变为1条UNKNOWN，不是新增已确认命中。没有新的完整人工真值，不能报告篮球或投篮准确率提升。

交付目录：`out/general_stage1_20261016_213026/`。`before/` 是本轮修改前的脏工作区快照，`ablation/source_snapshot.tar.gz` 是18组GPU实验时的源码，`final_source/` 是最终代码与报告快照。Git HEAD仍为 `56b9317d8cc561199786811069d54c40d2e47da5`，不能仅靠HEAD标识工作区代码。既有未提交工作全部保留。

## 2. 视频身份与人工信息核对（步骤1）

用户补充确认粗时间来自 **`lillard-buzzer-beater-BV165YQ68E3C_9e1bbd21c5.mp4`**，而不是旧的 `validation_lillard_30s.mp4`。

| 角色 | SHA-256 | 时间关系 |
| --- | --- | --- |
| 完整原片，AV1 | d8b5b37c3d5f88417e1a00bf44533dd06b659e56a30130f1839e69d1334906e6 | 用户时间从此片00:00起 |
| 已有H264兼容副本 | b56a57058df2062fe5e88f4c579d9bc77b02df888f110a253cdd7b08336c0924 | 原片转码；5314帧 |
| 本轮前900帧无损剪辑 | 9f5d803f52d78828b058efc60a798bab9123ee1e225a813404e5c2eceac55f67 | 与兼容副本前900帧逐像素相同，起点0 |
| 旧30秒回放剪辑 | cf6c1a647900e38f581e6cec2fe6ba8f6b3f7b0d0131db38296b684c29834352 | 另一剪辑；庆祝/回放，不能套用前两次粗标 |
| DairyCourts | 0e8d6f2b5537583ad041ab0c6d4533edf536ae409ac8e860b545a2f92caca303 | 独立Development来源，关联既有模型素材 |

实际OpenCV无法直接解码此AV1原片，复用已有兼容转码，没有用空帧冒充。原片与兼容副本前900帧PTS最大误差0.000058秒；兼容副本与本轮剪辑PTS误差0。兼容副本是此前有损转码，因此不声称与AV1原片像素相同。900帧约30.03秒，实际时间统一保留源PTS/29.970fps对应值，不以处理帧序号冒充原始秒。证据：`assets.json`、`pts_mapping.json`、`time_mapping_contact.jpg`。

人工意见已转为 `coarse_annotation_tasks.json`：来源为本次用户陈述，正例粗时刻暂给±1.5秒审核范围、审核pending、play_id未知、training_approved=false。12–15秒运球、15–18秒未确认出手、24–27秒争球、27–30秒传球均作为待核对负例窗口，不能当完整逐帧真值。被盖与随后的回抛是否同一play需单独审核。推理程序不读取此任务或任何测试标签。

## 3. 现有实现审查与本轮修改（步骤2～5）

原有模块诊断详见既有交付、STEP3/4/5和NBA调查报告。本轮复核实际权重为E-BARD四分类 **YOLOv8n**，不是假定的YOLOv8s：`models/BODD_yolov8n_0001.pt`，basketball/hoop/player/referee，训练imgsz704。COCO `yolov8n.pt` 仍用于person/BoT-SORT；两个ShotTracker备用模型仍保留。模型类别和全部SHA见 `ablation/inventory.json`。没有重复加载或替换主模型。

### 3.1 候选与自适应尺寸

- `legacy_shots/ball_selection.py`：保留原尺寸、形状、人头/UI/静态及运动过滤；只在独立多帧模型候选提供移动与人员/篮筐尺度上下文时，允许有限尺寸扩展。
- `legacy_shots/stream.py`：记录候选/拒绝原因/最终观测/预测状态。一次处理仅提交一次原始候选历史，镜头切换清除；不以预测为多帧支持票。
- 模型未输出的球不能由此补出。候选历史支持也不是真值，随相机移动的人头仍可能骗过时序，因此该开关保持关闭。

### 3.2 镜头运动与已有RimTracker

- `frame_motion.py`：复用现有ORB/RANSAC，验证匹配数、内点比例、网格分布、尺度与投影；正确将原current→previous单应矩阵反转为previous→current原图像素坐标。
- `legacy_shots/scorer.py`：扩展已有RimTracker；在可信全局运动下移动先前框，随后关联当前真实检测。当前真实测量alpha=1减少旧EMA滞后；默认旧行为不变。
- 状态分为DETECTED、REFINED、PREDICTED、STALE、LOST；预测最长0.25秒，不刷新真实检测时间。STALE仅诊断显示，不能确认穿筐；动态模式下fresh只认当前真实测量。
- 动态穿筐检验比较球相对各自真实篮筐的位置与尺度，不拿旧筐绝对像素线当移动镜头基准。正式事件阈值与状态机保留。
- `ball_recovery.py`：复用已有筐ROI，在动态模式允许短时经验证预测筐提供搜索窗口；ROI球依然要通过正常筛选，预测筐不能确认事件。两个ROI默认状态未修改；本轮A–F没有开启ROI，不能把收益归给ROI。

### 3.3 并行离手候选与通用负例评分

- `legacy_shots/release_candidates.py`：复用`release_binding.bind_release`的连续上半身接近/离开证据；无需先进入筐附近才建立候选。固定时长缓存，不读人工答案。
- 输出source_frame/timestamp/release_interval、临时track_id或UNKNOWN、rim_reference与状态、证据/原因/置信分/状态。结果恒允许UNKNOWN；所有新候选 `counts_for_statistics=false`。
- 使用球相对人员框的升降、真实筐接近程度、其他人员接球、回到持球人、近筐短轨迹、争抢与丢球上下文综合评分。方向不是唯一依据。篮下短轨迹允许进入审核，BLOCKED/反弹/偏转仅为未决子类型。
- 回到原持球人且向下更像运球/回抛；明确连续接收者更像传球。没有动作姿态真值，这些仍是启发式，不是已验证分类器。
- GPU实验后发现15.282秒只有2帧接近代理、21.955秒可能是争抢后回抛，追加弱远筐接触/争抢后重新持球保护：保留候选但降为UNKNOWN，不删除来伪造精度。最终9组固定观测复算与初始18组GPU版本分开保存。
- 新旧候选仅通过共享真实轨迹帧与相容人员关联证据，不仅凭时间合并；没有写入正式次数/得分。

### 3.4 人员角色与回放证据

- `player_roles.py`：复用E-BARD已有player/referee输出与COCO人员框，IoU、多帧投票、可用时的可信脚点场内约束；保留PLAYER/REFEREE/UNKNOWN与投票置信度。场外只提供spectator_hypothesis，不能区分观众与替补球员，因此本阶段未完成可靠SPECTATOR分类。
- `sources.py`：只向影子分类器提供原有脚点判断；不删除person，不改变BoT-SORT身份、球队颜色或号码OCR。
- `replay_candidates.py`：不同切镜段的连续移动感知哈希相似性，只给POSSIBLE_REPLAY_UNKNOWN、可能同play关联；不自动合并正式事件、不制造确定play_id。不同机位/慢放/漏切镜仍会失败，实际本轮未找到可信回放关联。
- 相邻帧球员ID不是跨镜头真实身份；现有颜色/OCR未被此次角色实验替代。

### 3.5 修改清单

本轮7个现有代码文件：`src/aihoop/ball_recovery.py`、`frame_motion.py`、`sources.py`、`legacy_shots/{ball_selection,scorer,settings,stream}.py`。

8个新代码/测试文件：`src/aihoop/legacy_shots/release_candidates.py`、`src/aihoop/player_roles.py`、`src/aihoop/replay_candidates.py`、`scripts/{run_general_ablation,rescore_release_shadow,render_general_vision}.py`、`tests/{test_general_vision_detection,test_release_shadow}.py`。

另新增本报告、追加标注规范。`final_source/round_changes.json`、`round_changes.patch`以before快照比较，不能把仓库所有既有脏改动算作本轮工作。

## 4. 开发基线与A–F消融（步骤6）

A原始；B仅自适应球；C仅动态筐；D仅离手影子；E动态筐+离手影子；F自适应球+动态筐+离手/角色/回放影子。F是组合实验，不能将F变化归因给某个单独模块。

全部相同视频、权重与基础参数：device0，person_stride2，球conf/candidate_conf=.25，原有640/960整帧级联，ROI关闭，无球场标定/手动筐、OCR关闭。第一遍球/筐仍逐原视频帧处理，没有使用人工注入事件。`baseline_before/`另保留改动前实际3次运行。

下表“球观测帧”指最终保留的模型球，不是TP；“筐实测帧”只数本帧接受的真实观测；UNKNOWN记录可能包含误报，不能当真实出手数。GPU列为Ultralytics逐结果inference计时之和，不等于全流水线GPU忙碌时间。

| 素材 | 组 | 球观测帧 | 筐实测帧 | jump拒绝帧 | 正式未决记录 | 总耗时秒 | YOLO报告推理秒 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 完整利拉德前30秒 | A | 388 | 407 | 6 | 3 UNKNOWN | 62.86 | 7.29 |
| 完整利拉德前30秒 | B | 453 | 407 | 6 | 3 UNKNOWN | 63.73 | 7.24 |
| 完整利拉德前30秒 | C | 388 | 407 | 6 | 3 UNKNOWN | 118.74 | 7.17 |
| 完整利拉德前30秒 | D | 388 | 407 | 6 | 3 UNKNOWN | 61.56 | 7.20 |
| 完整利拉德前30秒 | E | 388 | 407 | 6 | 3 UNKNOWN | 112.70 | 7.12 |
| 完整利拉德前30秒 | F | 453 | 407 | 6 | 3 UNKNOWN | 111.82 | 7.02 |
| Dairy | A | 223 | 778 | 0 | 1 UNKNOWN | 35.80 | 6.72 |
| Dairy | B | 247 | 778 | 0 | 1 UNKNOWN | 35.44 | 6.64 |
| Dairy | C | 223 | 778 | 0 | 1 UNKNOWN | 77.41 | 6.66 |
| Dairy | D | 223 | 778 | 0 | 1 UNKNOWN | 35.57 | 6.66 |
| Dairy | E | 223 | 778 | 0 | 1 UNKNOWN | 77.67 | 6.67 |
| Dairy | F | 247 | 778 | 0 | 1 UNKNOWN | 77.86 | 6.67 |
| 旧回放30秒 | A | 129 | 33 | 5 | 0 UNKNOWN | 29.72 | 7.28 |
| 旧回放30秒 | B | 143 | 33 | 5 | 0 UNKNOWN | 29.65 | 7.27 |
| 旧回放30秒 | C | 129 | 38 | 0 | 1 UNKNOWN | 75.20 | 7.30 |
| 旧回放30秒 | D | 129 | 33 | 5 | 0 UNKNOWN | 29.64 | 7.30 |
| 旧回放30秒 | E | 129 | 38 | 0 | 1 UNKNOWN | 75.80 | 7.38 |
| 旧回放30秒 | F | 143 | 38 | 0 | 1 UNKNOWN | 76.20 | 7.33 |

旧fresh口径允许持有旧筐1.5秒，动态fresh只认当前实测，不能直接比较“rim_usable_frames”宣称召回升降。完整前30秒实测均407帧、Dairy均778帧；旧回放33→38帧，5个jump拒绝均得到当前真实观测关联。证据帧796、797、798、800、802，匹配内点比例约.997/1/.947/.990/.867，网格6/6/5/5/5，见`camera_recovery_evidence.json`；背景补偿是否精确到真实篮圈开口仍需要人工框。

自适应增加球观测65/24/14帧，含近景尺度扩展；没有完整球框真值，TP/FP/FN/Precision/Recall/F1均尚不可计算。篮筐IoU、轨迹中断、人员Recall/误纳率、出手/命中TPFPFN、传球争抢误报、真实出手归属率也不可计算。所有输出保留null；不以增加框数作为召回证明。

### 4.1 最终离手候选评分（固定观测复算）

初始GPU实验与最终代码有版本区别：后续保护只改变影子评分。`candidate_rescore_final/`在相同已选球/人员/筐/切镜观测上复算，没有重新跑YOLO，也没有修改正式事件。每份保存raw SHA、候选源码SHA、选项与正式事件副本。F调试视频显示最终评分；GPU耗时仍属于初始18组。

| 固定观测输入 | 候选 | 负例倾向 | UNKNOWN | 待审核投篮倾向 |
| --- | --- | --- | --- | --- |
| 00_lillard_first30_lossless_D | 9 | 5 | 4 | 0 |
| 00_lillard_first30_lossless_E | 9 | 5 | 4 | 0 |
| 00_lillard_first30_lossless_F | 11 | 6 | 5 | 0 |
| 01_DairyCourts_D | 2 | 1 | 1 | 0 |
| 01_DairyCourts_E | 2 | 1 | 1 | 0 |
| 01_DairyCourts_F | 3 | 2 | 1 | 0 |
| 02_validation_lillard_30s_D | 3 | 1 | 2 | 0 |
| 02_validation_lillard_30s_E | 3 | 1 | 1 | 1 |
| 02_validation_lillard_30s_F | 3 | 1 | 1 | 1 |

状态占比和有临时人员ID比例在JSON中可查；它们不是分类准确率或真实球员归属率。所有候选命中结果UNKNOWN，置信分是启发式证据分，不是校准概率。6组A==D、C==E正式事件逐字段一致检查通过，说明影子记录没有回写统计。

## 5. 正例阻断点与误报风险

`coarse_positive_window_diagnostics.json`使用F的post-YOLO置信度/NMS/类别输出，**没有捕获YOLO阈值前logits**。“没有候选”仅意味着当前配置没有输出球框，不证明真实画面没有球。

- 0～4秒120帧：76帧保留模型球；40帧无模型球候选。框级拒绝另有person_head4、motion_rejected1。无球候选帧21(0.701s)、26～34(0.868～1.134s)等，覆盖用户粗时刻。尚不能判断真正球被YOLO漏检还是不可见，需逐帧真值。
- 19.5～23.5秒120帧：67帧保留模型球；49帧无球候选。框级拒绝person_head4、motion_rejected1、size_rejected2。帧598～619(19.953～20.654s)连续缺候选，帧631～632(21.054～21.088s)再次缺候选。正式引擎在21.955秒才建立接近/离开代理，可能已是被盖后的抛回；不能按“接近21秒”匹配真出手。
- 正式未知记录：release约2.44→decision3.30，15.28→17.52，21.96→23.79。第一条未找到足够持球/离手证据；其余即便有接近代理也缺穿筐/结果证据。出手成立与结果成立分开，未调用比分事实强行造命中。
- 原旧30秒回放的“0条”主要有篮筐运动关联拒绝及缺乏连续观测，不是可以把人工1秒/21秒标签套进去修复的同一个问题。
- 镜头切换机制仍会漏检编辑切镜，完整前30秒自动cut记录为0，实际是否有剪接需人审；因此回放去重不能宣称已完成。静态人头/Logo/篮网拒绝仍在，但跨视频误检下降尚无真值证明。

## 6. GPU与性能

使用Quadro RTX5000，GPU/torch/CUDA/模型SHA完整登记于`ablation/inventory.json`。相同权重推理计时基本维持约6.6～7.4秒/视频；动态镜头算法增加的主要成本是CPU逐帧ORB与几何验证。

F/A总耗时约1.78倍（完整前30秒）、2.17倍（Dairy）、2.56倍（旧回放）。默认关闭，不能宣称提速或目前可接受上线。一次/组测量，含初始化/解码/检测/追踪/JSON准备；不含本轮后续叠框视频编码。部分早期CPU解码与测试有并发，未作冷暖/热稳态多次随机对照，亚秒差异不代表模块收益。torch峰值已分组记录，只涵盖torch分配，不能视为NVML全显存。

下一步应先保证识别证据，再将背景运动按需触发或复用已有缓存；需要单独固定输入、精度回归与计时，而不是为了速度跳过关键帧。

## 7. 测试与工程稳定性

| 检查 | 实际结果 | 证据 |
| --- | --- | --- |
| 球尺寸/相机/筐与既有回归 | 54 passed | step_ab_tests.log |
| 初始离手回归 | 54 passed | step_c_initial_tests.log |
| 候选/角色/回放相关 | 46 passed | step_cde_tests.log |
| 最终交付源码全量tests | 640 passed, 2 failed, 15 skipped, 9 subtests passed，27.98秒 | full_tests_delivery.log |
| 最后依赖校验及新增保护用例、既有相关回归 | 75 passed | final_targeted_tests.log |
| 文档引用检查 | 全部引用有效 | delivery_checks.json |
| Attempt/Shot接口及证据往返契约 | ok=true | delivery_checks.json |
| 正式事件影子隔离 | 6/6逐字段一致 | final_comparison.json |
| 关闭新开关与修改前基线 | 3视频正式事件及球观测帧数一致 | artifact_checks.json |
| 审核/视频产物 | 6视频帧数正确，900审核图，视频Range206/图片200 | artifact_checks.json |
| 线上固定副本 | 171文件无变化，PID262365，融合禁用=1 | runtime_check.json |

75是相关测试，不应与640相加。较早的full_tests_final.log为639通过；最后新增用例/依赖断言后已重新运行全量，结果以full_tests_delivery.log为准。2个既有失败：`test_multical_mini_and_snap.py::test_soft_failure_exit_carries_both_keys`（软失败文案）及`test_plan_b.py::test_tactics_end_to_end_and_frames`（synthetic人员为空）；未删断言/跳过来制造全绿。15skip也未计入通过。

风险与回滚：新球过滤可能引入移动干扰误检；背景运动可能受球员/视差影响；真实筐严格有效期可能使事件更保守；近筐短轨迹评分仍可能混淆盖帽后回抛。新行为以`legacy_detect.general`逐项开关控制，全部false回到兼容路径；无需覆盖源码或重启线上服务回滚实验。生产PYTHONPATH仍固定在`deploy/runtime/20261016-152930/src`。

## 8. 配置与复现命令

全部最终配置（含原有ROI/阈值）见`final_configuration.json`；五个新开关adaptive_ball/dynamic_rim/release_shadow/role_shadow/replay_shadow均false。回放影子必须同时开release_shadow；非法组合有验证测试。所有新增选项与取值范围以`GeneralVisionOptions`为准。

关键默认：自适应下限2px、短边最大比例.22、独立支持3帧/.3秒/2px移动；相机最长边640、至少20匹配、.6内点比、4网格、尺度变化≤.25；筐预测≤.25秒、实测alpha1；离手窗口1.2秒、补充上下文.7秒、有效间隔.25秒、重新持球4帧、强接触3帧、先前飞行3帧、相对身体升幅.12、近筐4筐宽；角色3票/IoU.5/conf.6；回放哈希距离5/最小运动4bits。接近/离手的最小双帧证据等复用原有绑定规则，不宣称经跨比赛调优。

```bash
cd /data/projects/ai-basketball-analyst
AIHOOP_PY=/data/conda-envs/ai-basketball-analyst/bin/python
export PYTHONPATH=src
export PATH=/data/projects/ai-basketball-analyst/out/cv_baseline_20261015/tools:$PATH

# 最终代码相关回归；全量限定tests，避免误收集运行副本
"$AIHOOP_PY" -m pytest -q tests/test_general_vision_detection.py tests/test_release_shadow.py
"$AIHOOP_PY" -m pytest -q tests
"$AIHOOP_PY" scripts/check_runtime_contract.py
"$AIHOOP_PY" scripts/verify_doc_refs.py

# 新目录运行最终版本A–F；历史18组需使用ablation/source_snapshot.tar.gz对应源码
"$AIHOOP_PY" scripts/run_general_ablation.py --videos   out/general_stage1_20261016_213026/lillard_first30_lossless.mp4   data/samples/shottracker/DairyCourts.MOV   data/samples/validation_lillard_30s.mp4   --out out/general_stage1_repeat_new

# 固定观测上只复算影子候选，不改变正式输出
"$AIHOOP_PY" scripts/rescore_release_shadow.py --raws   out/general_stage1_20261016_213026/ablation/00_lillard_first30_lossless_F/raw_track.json   --out out/release_shadow_repeat_new

# 绘制模型/预测/拒绝/筐状态和最终离手候选；必须选择新的输出文件
"$AIHOOP_PY" scripts/render_general_vision.py   --raw out/general_stage1_20261016_213026/ablation/00_lillard_first30_lossless_F/raw_track.json   --shadow out/general_stage1_20261016_213026/candidate_rescore_final/02_00_lillard_first30_lossless_F.json   --out out/lillard_general_repeat_new.mp4

# 复用已有本地人工审核工具，只绑定回环，不启动分析API或改生产
"$AIHOOP_PY" scripts/serve_match_labeling.py   --batch out/general_stage1_20261016_213026/review_full_first30 --port 8127
# 在同一台机器打开 http://127.0.0.1:8127
```

实验输出目录已存在时脚本拒绝覆盖。不是通过reset工作区复现。所有模型与视频保留在/data，不纳入源码tar或公开样例库。

## 9. 诊断视频与人工审核

`debug/`已输出三素材A/F共6个带逐帧拒绝原因的MP4，以及`contact.jpg`：

- `00_lillard_first30_lossless_A.mp4` / `00_lillard_first30_lossless_F.mp4`：真正对应用户时间的完整片前900帧。
- `01_DairyCourts_A.mp4` / `01_DairyCourts_F.mp4`。
- `02_validation_lillard_30s_A.mp4` / `02_validation_lillard_30s_F.mp4`：旧回放剪辑。

绿色=保留模型观测，红色=拒绝模型候选，黄色=预测；预测不是检出，候选不是人工真值。F视频候选标签是最终离线评分，历史release phase为当时记录，图上明确写last observed。

`review_full_first30/manifest.json`有10组×90张原分辨率图，共900帧，回看视频引用较小的已有H264完整副本；仍保留原片SHA、逐帧时间映射与剪辑SHA。优先review_00/01核对第一次出手；review_06/07核对被盖、回抛；之后review_08/09核对争球、传球与漏报。每组要求真实球框/诱饵框/篮圈开口、可见性、逐次离手时间/结果/分值、原比赛或回放、play_id与未知身份。现有网页不能完整编辑人员框、轨迹ID和所有play_id字段，扩展信息应按标注协议另附JSON旁表，不能假称网页已支持。

只审核局部帧时不得勾整帧/整段完整性。人工粗标不自动批准训练；对确认无球负例仍需完整检查；不清楚留UNKNOWN。详见更新后的标注协议。

## 10. 第二阶段数据计划与开发顺序（步骤7）

`stage2_source_registry.json`锁定已使用的利拉德、Dairy、哈登、杨瀚森等为Development，同场剪辑/回放/转码不得跨组；规划8个新的互斥比赛来源：Validation各2场NBA/CBA，Independent Test各2场NBA/CBA。目前均未提供原片/SHA，pending，不能宣称已具备独立测试集。需排查模型训练集与历史开发重合，Dairy不能作为独立测试。

`stage2_annotation_tasks.json`列18场景、每类3个起始窗口。54项是采集起点，不代表充分统计样本；精确球/筐/人员/出手/回放标注尚未完成。不要拿Independent Test反复调参数。

下一轮顺序：

1. 完成本轮完整原片0～4秒与19.5～23.5秒密集审核：离手/盖帽接触/回抛、球/筐、play_id；先解决正例到底发生在哪帧。
2. 在已审核Development窗口单因素比较E-BARD/ShotTracker、分辨率与现有ROI/丢球密集分析；计算TPFPFN与筐定位，不先换线上模型。
3. 根据误拒真球与真实缺候选分别修过滤/ROI/模型能力；保留头部和Logo负例。并改进真实动作与回抛、补篮的时序证据。
4. 校验镜头切换及回放关联，再评估候选→正式事件的严格融合；未证明前保持影子。
5. 优化动态筐CPU开销，重复暖态GPU/墙钟性能测量，固定Validation后评估；最后只运行一次锁定Independent Test。

未进行完整177秒、全场比赛及多比赛长时内存/性能验证；本轮只覆盖三段开发素材。当前没有证据要求立即重训。若审核显示正确ROI/高分辨率下仍持续漏小球或误检头部/Logo，再按比赛来源整理完整标注与困难负例，审核并批准后训练，保留旧素材回归。记分牌离线回溯原型保持已有状态，本轮不扩展或启用线上融合。
