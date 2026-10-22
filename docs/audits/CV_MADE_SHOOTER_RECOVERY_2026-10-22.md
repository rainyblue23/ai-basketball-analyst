# 进筐锚定的出手人反向回溯（2026-10-22）

## 当前结论

已实现离线原型：原有模型MADE事件 → 对应镜头内反向观测链 → 连续持球/离手 → 对应时刻球员脚点 → 手标球场映射 → 两分/三分建议。默认关闭，不接入正式计分，不修改ScoreEngine、命中判据、旧事件或主客队统计。

**当前任务097c0611d8c3的两次模型命中仍未可靠补回出手人。** 88项回归通过不能替代真实视频准确率验证；没有宣称修复0:0或部署该实验。用户提出回溯方向后完成了实际GPU/ROI对照，而不是将最后一个靠近球的人直接记成射手。

## 原因和实际证据

- 第一条原候选起点6.406秒：原球轨迹在出手附近存在长缺测；1280密集重检补出5.305秒起的连续飞行观测，但更早的持球/离手段仍不足，且球员框重叠。只靠篮筐位置无法确定分值。
- 第二条原候选64.064秒：回溯会把T4117短暂的头部附近接近解释成持球。对应时刻的手标镜头匹配成功，T4117脚点被投到场外；因此此候选被否决。T4118的脚点实际在场内，但原on_court字段有时为false，说明不能将旧静态位置筛选当作永远正确的角色真值。
- 已修复离线重检的人员元数据丢失：原reanalyze通过Det.pack/unpack丢弃on_court/role字段，可能把场外人员重新当作无标记人员。现在诊断输出保留原people上下文；若提供对应时刻的标定，则重新验证脚点，不能沿用错误旧场内/场外标签。
- 接触判据现在额外排除纯头顶接近，以及短接触之前已自由飞行的情况；仍是离线候选规则，不是已验证的身份分类器。
- 第一轮1280重检仍产生一次make；第二轮相同窗口得到unknown。后者不自动推翻旧结果，也不能把旧模型MADE当人工确认；本模块只调查原事件，不创建新命中。

## 代码

- `src/aihoop/made_shooter_recovery.py`：默认关闭的选项；同镜头、有限时间、真实观测、尺度/速度门控的反向beam关联；复用bind_release；保留多球员歧义，提供独立的分值建议，counts_for_statistics恒false。
- `scripts/recover_made_shooters.py`：离线入口、预算上限、原视频/模型/标定/raw SHA、短片导出与结果保存。未开启时不加载模型。
- `scripts/experiment_score_recovery.py`：保留人员元数据；新增反向重检函数，复用原YOLO缓存及两类ROI；反向步数只用于搜索，输出恢复为原视频帧号/时间，反向状态机结果全部丢弃。
- `tests/test_made_shooter_recovery.py`：默认禁用、两分/三分脚点映射、未知球队不乱归属、切镜/段/缺测不跨接、裁判/场外/头顶负例、原记录不变、反向时间恢复等检查。

没有训练/下载/切换权重，没有修改正式服务或固定运行副本。源码与身份快照见source_snapshot.tar.gz、source_manifest.json。

## 测试

88 passed，6条已有依赖弃用警告；完整日志tests.log。另单独验证CLI默认禁用，日志disabled_check.log。未重跑所有项目门禁，不宣称整体全绿。

本轮真实开发视频两条MADE锚点，每条回查约4秒，模型同为BODD，1280全帧、现有ball ROI/rim ROI。反向阶段分别复用121/100次全帧缓存，额外推理11/12次；两窗口处理及归属约23.7/27.2秒（墙钟，含反向解码、CPU关联和标定，不是纯GPU推理耗时，未计导出编码）。这只是诊断成本，不是生产性能提升。

当前真实球框与精确出手人真值不足，TP/FP/FN和归属准确率不可计算。算法输出没有写成人工标签。

## 最少人工核对

只保留两段短片，不要求逐帧画框：

- [约6秒的动作](out/shot_attribution_20261022_131522/reverse_verified/event_00_original.mp4)
- [约64秒的动作](out/shot_attribution_20261022_131522/reverse_verified/event_06_original.mp4)

请确认实际出手球衣颜色/号码；任务来源SHA与时间映射在minimal_review_tasks.json，状态保持pending，training_approved=false。回答用于审核/评估，不会把指定视频、时刻或答案写进推理逻辑。

## 复现

```bash
cd /data/projects/ai-basketball-analyst
# 默认禁用，仅建立诊断记录；必须选择不存在的新输出目录
PYTHONPATH=src /data/conda-envs/ai-basketball-analyst/bin/python \
 scripts/recover_made_shooters.py --raw out/097c0611d8c3/raw_track.json --out out/made_recovery_disabled_new

# 明确开启离线反向补检与对应镜头标定
PYTHONPATH=src:scripts /data/conda-envs/ai-basketball-analyst/bin/python \
 scripts/recover_made_shooters.py --raw out/097c0611d8c3/raw_track.json \
 --out out/made_recovery_new --enable --redetect --reverse-redetect --clips \
 --calibration data/calibration_yang-retry2_8828aea2e1_13eb89ba04d1e080.json

PYTHONPATH=src /data/conda-envs/ai-basketball-analyst/bin/python -m pytest -q \
 tests/test_made_shooter_recovery.py tests/test_shot_evidence_stage5.py \
 tests/test_shot_legacy_engine.py tests/test_shot_legacy_geometry.py \
 tests/test_score_guided_recovery.py tests/test_release_shadow.py
```

## 回退

该原型没有API调用入口，保持不传--enable即可不运行。正式服务没有加载新模块，无需重启回退。若移除离线功能，只撤销本轮4个文件的增量，不重置整个工作区。恢复人员元数据属于诊断兼容修复，未改变原reanalyze的检测输入或事件判定。
