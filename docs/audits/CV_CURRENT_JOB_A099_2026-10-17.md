# 当前杨瀚森任务a099ca917d06：错判定位与修复候选（2026-10-17）

## 结论

用户这次指的是**约91秒杨瀚森视频，任务a099ca917d06**，不是此前利拉德30秒实验。已经定位真实运行配置/资源问题与首个事件的关键缺帧，并准备隔离修复副本。**线上结果尚未覆盖，当前网页仍使用20261016-152930固定版本。**

- 原任务2726帧，仅920帧保留模型篮球（33.75%），174帧筐jump_rejected，805帧没有筐候选；3段筐不可用超过2秒，不能把83.38%的旧fresh持有率当筐Recall。
- 原视觉输出8条：2自动命中、2自动未中、4未知；只有3条具有接近/离手归属代理。模型输出不等于8次已审核真实出手。
- 记分牌OCR实际加载失败；球衣OCR同样使用按代码父目录推导的默认路径，固定发布目录导致其默认目录漂移。路径已在工作区修复，并在模拟固定快照根目录下离线加载成功。
- 请求ball_rim_recovery=false，却因manual_hoops被强制改为true。已修复显式选项优先，同时保持未传该字段的旧调用行为，既有手工筐回归未删除。
- 首条记录约5.64秒原判未中；高分辨率离线回溯补到了6.54秒过筐附近模型观测，判为命中。严格单因素控制见第3节；尚无精确人工框/动作审核，不能报准确率提升。

原始输入与视频SHA见本目录input_identity.json，raw SHA `548789dd4b371220fe6831129617701f80ff09dd1de5d7e423ddb608e93d6147`，兼容视频SHA `af8c5ab309e6fcb61ed5e7294daeb1c0520179c04c7d8294f5c1016908ba9bf2`。该素材继续标Development。

## 1. 当前任务实际阻断

实际原始产物：out/a099ca917d06/raw_track.json。完整逐帧诊断及视频在本轮diagnostic/，不是新造的算法真值。

| 问题 | 实际证据 |
| --- | --- |
| 缺少真实模型球 | 1806/2726帧；person_head77框、size_rejected75框、motion_rejected283框；次数有重叠，不相加当误检数 |
| 筐几何不可用 | 453帧fresh=false；28.128～30.130、35.736～42.910、58.191～60.994秒有长缺口 |
| 手工筐未保证全片 | 两个外观锁仅333/200次匹配，各538/365次未匹配，并在切镜后停用；标过两边并不等于每个后续镜头都识别可靠 |
| OCR故障 | 报错目录deploy/runtime/aihoop_assets/models/easyocr，实际模型在/data/projects/aihoop_assets/models/easyocr；模板 fallback frames_hit=0 |
| 分值/队别未知 | 约64.06秒自动命中没有队别/出手人，未计入队伍得分；原显示2:0不是把两次自动命中都确认归队的结果。不能强行分配球队解决 |
| 实验未上线 | 当前PID262365使用固定源码；之前默认关闭的实验没有作用于本任务 |

球场地面标定本次valid=true，rmse约0.14m。缺球、筐跟踪、归属与命中判定是另外的证据链，不能凭地面标定通过断言投篮必然可识别。

## 2. 已修复的代码

### OCR资源与发布目录解耦

新增src/aihoop/ocr_assets.py，统一服务于球衣、记分牌、资源检查与模型准备脚本：

1. 显式AIHOOP_SCOREBOARD_OCR_MODELS/AIHOOP_JERSEY_MODEL优先；显式错误路径不悄悄退回其它模型。
2. 固定副本通过已存在的data软链接识别共享项目根；优先已预置models/easyocr，兼容兄弟aihoop_assets/models/easyocr目录。
3. 分析始终download_enabled=false，没有下载、训练或替换权重。球衣off/none/空字符串禁用语义不变。

修改文件：src/aihoop/jersey_numbers.py、scripts/read_marked_scoreboard.py、scripts/check_server.py、scripts/prepare_jersey_ocr.py。

### 显式ROI选项优先

src/aihoop/sources.py现在尊重传入的ball_rim_recovery=false；true仍开启。完全未传此选项的旧调用继续保留原手工筐自动补检行为，保持原test_complete_ellipse_stays_manual回归。API使用完整参数dump，因此显式false将生效。该修复只解决配置一致性，未证明关闭ROI能提高本视频准确率。

离线scripts/experiment_score_recovery.py也修复了ROI开关未检查的问题，并将ROI审计写入帧；新增--visual-options用于严格控制实验参数。原先双ROI开启的默认原型行为不变。

scripts/benchmark_shot_evidence.py新增可选--rim-current，使用现有引擎隔离筐实测几何；不运行相机补偿，不当成完整动态算法性能或精度实验。全部基于缓存，原检测/状态机不替换。

## 3. 首条事件：过筐关键帧漏检

已有ScoreGuidedShotRecovery在当前视频识别的显示变化前生成窗口0～9.51秒与0～10.511秒。复用同视频缓存人员/切镜上下文和已有YOLO，二次分析原始视频帧。

| 配置 | 6.54秒帧196 | 本窗口视觉结果 | 解释 |
| --- | --- | --- | --- |
| 当前线上原结果：640+原960级联、手标筐及自动ROI | 只有预测球，不是观测 | 原5.64秒记录MISSED | 原轨迹预测仍在筐上方，缺穿筐实测链 |
| 离线控制：640、conf=.25、ROI全关、无手工筐 | 只有预测球 | release5.81秒UNKNOWN | 与下行只有imgsz不同，原人员/切镜缓存相同 |
| 离线控制：1280、conf=.25、ROI全关、无手工筐 | 模型实测，conf=.733764 | release5.81秒MADE，crossing6.54秒 | 287帧完整检测，没有降低候选门槛或注入人工事件 |
| 初始回溯组合：1280/.15候选/15Hz双ROI | 模型实测 | MADE | 多参数压力实验，不用于单模块归因 |

单因素对照仅指中间两行：不能把线上原配置与离线1280的全部差异归因于分辨率，因为手工筐、级联和ROI上下文也不同。1280在这一个Development窗口补到了关键模型观测，不代表全视频或其它比赛Recall提升。既有11张审核开发帧上1280未优于640，不能全局默认1280。

原检测与二次检测均来自同一实际视频。第一遍的预测不算测量。first_shot_before_after_slow.mp4左边是原任务、右边1280/.25控制；first_outcome_old_vs_dense.jpg是初始组合实验的工程放大图。原完整视频见diagnostic/diagnostic.mp4，8条事件联系图events_contact.jpg。

两个重叠回溯窗口都得到约5.81秒的同一条候选，必须视为同一视觉证据，不能报告“恢复两次命中”。出手人和球队仍UNKNOWN；本轮没有改写原任务或生成队伍分数。

## 4. OCR现在读到了什么

同一兼容视频，自动定位数值ROI [176,882,220,70]；原fallback模板ROI [36,993,373,54]没有读数。离线使用既有EasyOCR/定位/多帧确认，182个采样得到177条读数，读数从88:86到109:120。

严格回溯规则确认7次**显示变化**，置信度下界约.971～.9996：

- 9.510s：[88, 86] → [88, 88]，right +2，类型UNKNOWN。
- 10.511s：[88, 88] → [90, 88]，left +2，类型UNKNOWN。
- 34.535s：[91, 92] → [91, 93]，right +1，类型FREE_THROW_OR_SPECIAL_UNKNOWN。
- 51.552s：[91, 94] → [91, 97]，right +3，类型UNKNOWN。
- 67.067s：[99, 107] → [99, 109]，right +2，类型UNKNOWN。
- 69.570s：[99, 109] → [102, 109]，left +3，类型UNKNOWN。
- 88.088s：[109, 118] → [109, 120]，right +2，类型UNKNOWN。

+1保持FREE_THROW_OR_SPECIAL_UNKNOWN；多队同时变化/大跳变/低置信度单独记录，不能补成多个进球。标注physical_score_verified=false、scoring_team=UNKNOWN；显示事实不等于物理投篮真值。原始较宽松screen_events与严格facts口径不同，分别保存，不能混用次数。

7个显示事实中仅选择前2个回溯窗口作实验，6.54秒视觉结果与9.51秒显示+2在时间上相容，但尚未人工确认队别映射、回放/剪辑关系及物理同一事件。不自动把原MISS改MADE，也不将所有显示变化变投篮。线上融合禁用仍为1。

## 5. 测试与已知失败

- 资源路径/显式配置/已有OCR及ROI相关：56 passed；补充离线ROI控制及已有状态机相关：34 passed。
- 首次全量3 failed/658 passed：其中一个暴露旧的“完全未传配置时自动ROI”兼容行为；通过保留该旧行为、尊重显式false解决，未修改该既有断言。
- 之后全量659通过/2失败；最终加入离线ROI控制回归后：663 passed、2 failed、15 skipped、9 subtests passed，27.75秒，见full_tests_delivery.log。
- 两个既有失败仍是test_soft_failure_exit_carries_both_keys与test_tactics_end_to_end_and_frames；没有改断言或隐藏失败。
- 精确篮球/筐/出手/归属真值缺失，TP/FP/FN/Precision/Recall不可计算。没有宣称总体准确率提升。

## 6. 隔离发布候选与线上状态

staged_runtime/以原171文件固定快照为基础，只改6个资源/显式配置相关文件；不携带工作区其它大量改动，不更换模型、阈值或事件判据。staged_runtime_check.json记录：原快照哈希核对、独立启动契约、默认资源可达、显式ROI false生效，active=false。

该候选不包含1280实验参数、自动比分融合或新增候选上线。data/models/out/eval指向原共享目录，但没有通过候选启动服务/分析作业或写原结果。

按用户此前“不修改线上固定快照、不重启服务”的约束，候选尚未发布，原任务仍保持原样。若允许发布，只切到新的固定副本，不覆盖旧副本；之后是否重新分析当前视频应单独明确，不能把旧结果悄悄改成实验输出。

## 7. 复现

```bash
cd /data/projects/ai-basketball-analyst
AIHOOP_PY=/data/conda-envs/ai-basketball-analyst/bin/python
export PYTHONPATH=src
"$AIHOOP_PY" -m pytest -q tests/test_ocr_asset_paths.py tests/test_external_report.py tests/test_graphics_jersey.py tests/test_logo_scoreboard.py tests/test_ball_recovery_stage4.py tests/test_runtime_contract.py
"$AIHOOP_PY" scripts/check_runtime_contract.py
"$AIHOOP_PY" scripts/benchmark_shot_evidence.py --raws out/a099ca917d06/raw_track.json --rim-current --out out/yang_rim_repeat_new

# 下列视频路径从input_identity.json取；必须使用同SHA视频、同源原始缓存
"$AIHOOP_PY" scripts/experiment_score_recovery.py   --video data/compatible/5d2ca91987650085/yang-retry2_8828aea2e1_53adf906269f1182.mp4   --out out/yang_resolution_repeat_new --enable   --reference out/current_job_a099_20261017_161414/ocr_reference.json   --forward-raw out/a099ca917d06/raw_track.json --reanalyze --max-windows 1   --visual-options out/current_job_a099_20261017_161414/resolution_only.json
# 640控制改用resolution_640.json，并另选新输出目录。
```

所有输出拒绝覆盖。当前目录input_identity.json、源码改前/改后快照、配置、诊断视频、OCR原始读数/拒绝日志、局部回溯JSON、测试日志均保留，最终文件SHA汇总另存。

## 下一步

先人工审核5.6～7秒的过筐图像与队别，并核对原8条中的真/假出手及漏掉的动作。随后将近筐/得分提示触发的高分辨率二次检测做成有预算的通用离线流程，在Development负例和旧素材上回归；不要全局降低门槛，也不因单窗口成功启用全部实验。OCR路径修复只恢复证据通道，不保证投篮模块已经准确。
