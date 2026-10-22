# 连续相机变换与ROI轨迹污染修复（2026-10-17）

承接 [第一阶段交付](CV_GENERAL_STAGE1_2026-10-16.md)。本轮仅继续定位与局部修复，没有改动正式投篮判据、权重、BoT-SORT、记分牌融合或线上固定副本。

## 1. 本轮结论

1. 修复动态筐预测的相机变换断链错误：相邻变换必须连续有效，不能将第N-1→N帧的变换用于第N-2或更早的坐标。本轮真实视频11个错误PREDICTED帧全部改为STALE；球观测与正式事件逐字段对比未变。
2. 通过真实ROI对照定位另一条链：第402帧(13.413秒)裁剪边界的局部人员框被模型误报为球，ROI观测成为新锚点；之后第415/416帧的远处候选遭运动门控拒绝。新增默认关闭的裁剪内部边缘未证实检查，保留原框/拒绝原因，完整帧协同证据仍可放行。
3. 已完成8次GPU实验（利拉德四ROI配置+Dairy两配置，再各跑一次双ROI边缘检查），没有把框数变化计作TP。真球/筐/投篮的精确审核真值仍缺，不能宣称总体精度改善。首次投篮/被盖的可靠离手和结果问题尚未完成。

证据根目录：`out/cv_followup_20261017_145341/`。所有新行为保持默认关闭，不启动线上分析或重启服务。

## 2. 修改文件与原因

| 文件 | 本轮改动 |
| --- | --- |
| src/aihoop/legacy_shots/scorer.py | RimTracker增加geometry_frame/geometry_t；连续变换检查、当前时刻预测状态约束；真实检测恢复链条，预测不刷新last_seen |
| src/aihoop/ball_recovery.py | unconfirmed_crop_boundary仅检查ROI内部裁剪边缘与完整帧支持，不把运动预测当检测 |
| src/aihoop/legacy_shots/stream.py | 在现有选球流程中可选标记roi_boundary_unconfirmed；raw框/来源/region保留审计，不改ScoreEngine门限 |
| src/aihoop/legacy_shots/settings.py | 新参数与resolve_detect完整传递；默认保持关闭 |
| scripts/audit_recovery_pair.py | 相同视频SHA、几何、FPS、逐帧时间/数量核对；输出逐帧差异/阻断点/接近代理/待审核任务，不读标签注入事件 |
| tests/test_general_vision_detection.py | 连续变换失败后不能偷偷恢复预测；跳帧/过时时刻不可声称当前预测；真实观测可恢复 |
| tests/test_recovery_pair_audit.py | 预测不计真实观测、身份不匹配拒绝比较、接近不等于归属、边缘开关/完整帧证据/图像边界/内部球回归 |

完整补丁、改前/改后SHA与源码tar位于`final_source/`，相对于本轮开始的脏工作区快照比较，不包含此前已做工作的归属宣称。没有reset或覆盖既有运行副本。

## 3. 相机断链证据

上一轮F trace在帧145/299/350/463/501/505/529/621/700/730/732出现：前一帧背景运动验证失败且没有当前实测筐，本帧背景变换成功，旧代码仍将旧坐标做一次相邻变换并标为PREDICTED。它遗漏了中间失败的变换，不能证明坐标当前有效。

`camera_chain_before.json`保存候选证据、内点质量、旧last_seen；`camera_fix_comparison.json`证明上述11帧全变为STALE/camera_verified=false。新配置ROI关闭时，仍是453帧模型球和3条正式UNKNOWN；正式事件逐字段一致。该项是状态/坐标正确性修复，不是篮筐Recall提升。

真实检测重新接受后更新geometry_frame/geometry_t，相邻预测才能恢复；绝不延长0.25秒预测上限。代价是运动估计不连续时更保守；不以错误的预测坐标增加“可用率”。

## 4. ROI对照与裁剪边缘修复

同视频/同权重/同基础参数：E-BARD四分类YOLOv8n+COCO person/BoT-SORT、球逐帧、人员stride2、球候选conf=.25、原640/960级联、5Hz补检节拍、每帧最多2个ROI；general五个实验开关均开启以承接上一轮F。无球场标定/人工筐、无OCR、无高光。主搜索仍是完整帧，ROI仅补充。

| 视频 | ROI模式 | 边缘检查 | 模型球观测帧 | 球/筐ROI调用 | 正式记录 | 单次墙钟秒 |
| --- | --- | --- | --- | --- | --- | --- |
| 利拉德完整片前900帧 | none | 关闭 | 453 | 0/0 | 3 UNKNOWN | 107.14 |
| 利拉德完整片前900帧 | ball | 关闭 | 453 | 43/0 | 3 UNKNOWN | 107.43 |
| 利拉德完整片前900帧 | rim | 关闭 | 452 | 0/22 | 3 UNKNOWN | 107.65 |
| 利拉德完整片前900帧 | both | 关闭 | 452 | 45/22 | 3 UNKNOWN | 108.41 |
| Dairy | none | 关闭 | 247 | 0/0 | 1 UNKNOWN | 79.99 |
| Dairy | both | 关闭 | 252 | 46/79 | 1 UNKNOWN | 78.11 |
| 利拉德完整片前900帧 | both | 开启 | 453 | 43/22 | 3 UNKNOWN | 108.29 |
| Dairy | both | 开启 | 252 | 46/79 | 1 UNKNOWN | 76.55 |

上表是完整流水线墙钟记录，GPU设备0/Quadro RTX5000；不等于GPU内核计时。部分实验同时进行了CPU测试、审计、图像编码，未控制冷暖与并发，亚秒差异不作提速证据。各次环境/权重SHA、源快照、解析配置保存在实验子目录。模型未更换/训练。

### 4.1 为什么补检没有自然提高召回

- 完整片前30秒球ROI运行43次，仅2帧有模型球输出（390、438），都因person_head拒绝；选球逐帧与关闭ROI一致。这说明当前预测位置裁剪未补足离手关键帧，不证明过滤规则全部正确。
- 筐ROI运行22次，新增第402帧模型观测，但之后415/416两帧失去原本的观测，净453→452。双ROI出现相同变化。`audit_rim/frames.jsonl`保留前后候选、拒绝原因和轨迹上下文；不能只看净框数判断优劣。
- 第402帧ROI区域[168,0,967,627]，框[945.728,340.459,966.839,371.214]、conf=.376；距内部右边界约.161px，图像里对应局部人员身体/肢体区域，属于工程目视疑似误检，正式标注仍pending。`rim_roi_difference_contact.jpg`显示该框及后续两帧门控。
- 可选新检查要求：仅来自ball_roi/rim_roi、在原图内部裁剪边界2px内、没有经IoU融合的full_frame/multiscale支持时，标roi_boundary_unconfirmed。真实球也可能被裁剪，因此不是“所有靠边框是假球”；不在默认配置启用，原图自身边界不因此拒绝。候选仍保留，不以删除痕迹掩盖误检。

边缘开关单因素对照的逐帧变化：

- 利拉德：{"unchanged": 897, "observation_removed": 1, "observation_added": 2}
- Dairy：{"unchanged": 836}

具体哪些帧改变、是否伤及真球必须看`audit_guard_*/review_tasks.json`和逐帧证据。所有TP/FP/FN、Precision/Recall、真实归属准确率均null。

## 5. 离手阻断与人工审核

本轮未把人工“约1秒/约21秒”硬编码到推理。已确认时间来自完整利拉德视频，而非旧终场回放剪辑；原片SHA、无损前900帧、H264转码与PTS关系沿用第一阶段清单。

`release_proximity_contact.jpg`与`release_proximity_evidence.json`提供22帧的工程核对：

- 首次出手附近47～49帧(1.568～1.635秒)有模型球；50帧(1.668秒)因人头区域拒绝，之后52/53/55/57帧的球分别落入不同背景人员的接近代理。接近不是手部接触，临时T16/T189等不能据此确认真实出手人。连续离手证据因再次接近/身份歧义中断。
- 被盖附近627～630帧(20.921～21.021秒)出现接近人头/身体区域的模型候选拒绝，随后球/筐存在观测缺口。不能为补回该出手全局取消头部抑制，也不能把21.955秒回抛附近的接近代理当成被盖出手真值。

这解释了篮球框、人员框、接近代理和真实动作之间的差距；仍不能从自动框准确推出离手帧、出手人或盖帽结果。现有角色影子未回写正式关联，保留UNKNOWN。

优先审核材料继续使用第一阶段`review_full_first30/`原图；本轮`release_proximity_evidence.json`、各`audit_*/review_tasks.json`是新增索引。全部pending、Development、training_approved=false、frame_complete=false。网页无法编辑完整人员角色/轨迹/play_id，应按标注协议另附旁表；只有审核后才能评估，不作训练批准。

## 6. 测试、产物与线上边界

- 最终相关回归：71 passed，见targeted_tests_final.log。
- 最终全量：650 passed、2 failed、15 skipped、9 subtests passed（28.99秒），见full_tests_final.log。2个仍为既有`test_soft_failure_exit_carries_both_keys`、`test_tactics_end_to_end_and_frames`；没有删除断言或隐藏失败。
- Attempt/Shot往返契约和文档引用检查通过；运行副本171文件哈希与服务环境另存delivery_checks.json。没有启用线上比分融合。
- 两个900帧视频：full_both_before_guard.mp4、full_both_after_guard.mp4；红色显示拒绝框，绿色模型观测，黄色预测。上轮A/F与Dairy诊断视频仍保留，本轮没有替换已有产物。
- `comparison_all.json`保存8次实验；`camera_fix_audit/`、`audit_ball/`、`audit_rim/`、`audit_both/`、`audit_dairy_both/`、`audit_guard_full/`、`audit_guard_dairy/`保存所有前后变化。JSON与CSV同源，预测不计检出。

## 7. 配置、复现与回滚

新增`legacy_detect.ball_roi_edge_guard=false`、`ball_roi_edge_margin_px=2.0`（0～16原图像素）。检查仅在已有ROI开关开启且edge_guard=true时影响ROI候选。动态连续性修复仅在已有general.dynamic_rim=true生效。线上general全部关闭、ROI关闭的行为不因这两项改变。

```bash
cd /data/projects/ai-basketball-analyst
AIHOOP_PY=/data/conda-envs/ai-basketball-analyst/bin/python
export PYTHONPATH=src
export PATH=/data/projects/ai-basketball-analyst/out/cv_baseline_20261015/tools:$PATH
"$AIHOOP_PY" -m pytest -q tests/test_general_vision_detection.py tests/test_recovery_pair_audit.py tests/test_ball_recovery_stage4.py tests/test_shot_legacy_engine.py tests/test_shot_evidence_stage5.py tests/test_release_shadow.py tests/test_runtime_contract.py
"$AIHOOP_PY" -m pytest -q tests

# 必须选新输出目录，脚本拒绝覆盖；使用实际保存的配置，不需要测试标签
"$AIHOOP_PY" scripts/benchmark_ball_recovery.py   --videos out/general_stage1_20261016_213026/lillard_first30_lossless.mp4   --modes none ball rim both   --detect-options out/cv_followup_20261017_145341/detect_experiment.json --out out/roi_repeat_new
"$AIHOOP_PY" scripts/benchmark_ball_recovery.py   --videos out/general_stage1_20261016_213026/lillard_first30_lossless.mp4   --modes both --detect-options out/cv_followup_20261017_145341/detect_guard.json --out out/roi_guard_repeat_new
"$AIHOOP_PY" scripts/audit_recovery_pair.py   --before out/roi_repeat_new/00_lillard_first30_lossless_both/raw_track.json   --after out/roi_guard_repeat_new/00_lillard_first30_lossless_both/raw_track.json   --out out/roi_pair_repeat_new
```

复现实验必须保留原始输入SHA与对应源码快照；本轮最初四ROI实验源码早于可选edge_guard，后一对开启该新功能，其他推理参数保持一致。Dairy无保护配置显式false；不能将完整脏工作区Git HEAD视为全部源码身份。

回滚实验只需edge_guard=false；动态运动实验可独立关闭general.dynamic_rim，不修改默认权重或投篮条件。不得通过reset工作区回滚他人的改动。

## 8. 下一步

先审核上述少量关键帧与两次真实动作的离手/出手人/play_id，再评估完整球/筐真值。若ROI仍没有真实篮球原始输出，比较已有权重、裁剪尺度/采样率需在已审开发窗口上单因素进行；未证明前不重训、不启用线上。另需解决球员漏检/背景框接近造成的归属歧义，不能靠距离最近强派球员。跨比赛Validation/Independent Test仍按第一阶段清单待补，不用开发素材宣称泛化。
