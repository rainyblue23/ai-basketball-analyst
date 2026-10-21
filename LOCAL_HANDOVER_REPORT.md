# 本地接手报告（2026-10-20）

## 1. 结论

项目已能在本机 Windows 环境运行核心测试和 GPU 视频推理。当前代码对 24 秒固定机位真视频的输出与 2026-10-11 冻结基线逐条一致，没有发现迁移造成的算法漂移。

本轮没有调整投篮算法阈值。原因是：可用的 31 次出手真值可用于开发和验证现状，但现有“独立测试集”4 段视频的文件哈希全部与冻结清单不一致；同时交接说明引用的 8 份服务器阶段报告在本机缺失。缺少这两类证据时继续调参，会增加对开发素材过拟合的风险。

## 2. 检查点 A：环境与源码

### 环境

- 系统：Windows 11 `10.0.26200`
- Python：`E:\python\python.exe`，3.13.0
- GPU：NVIDIA GeForce RTX 4060 Laptop GPU
- PyTorch：2.14.0+cu126；CUDA 可用，运行时 12.6
- OpenCV：5.0.0
- Ultralytics：8.4.146
- NumPy：2.5.2
- FastAPI：0.141.1
- Node：v24.14.0
- FFmpeg：`E:\ffmpeg-7.1-essentials_build\bin\ffmpeg.exe`
- Windows OCR：可用，语言 `zh-Hans-CN`
- 磁盘余量：约 6.5 GB，低于项目检查器建议的 10 GB
- 缺失依赖：`pytest`。本轮没有静默安装依赖；现有 `scripts/check_all.py` 可运行大部分测试。

项目本地依赖需要以下搜索路径：

```powershell
$env:PYTHONPATH='D:\dsh_folder\aihoop\src;D:\dsh_folder\aihoop_assets\_patch;D:\dsh_folder\aihoop_assets\libs'
$env:PYTHONIOENCODING='utf-8'
```

### Git 与路径

- 分支：`main`
- 接手时 HEAD：`56b9317d8cc561199786811069d54c40d2e47da5`
- `mine/main` 与 HEAD 一致。
- `origin/main` 属于更旧且分叉的历史线，本轮没有强行合并或重置。
- `src/` 与 `scripts/` 中未发现服务器绝对路径 `/data/projects` 的残留引用。
- 真值文件仍包含本机绝对视频路径。这些路径目前可用，但属于可移植性债务；本轮未批量改写真值。

### 模型核验

当前本地活动球/筐权重是两类模型：`basketball`、`rim`。本地源码和权重不能证明交接文字中提到的“默认 E-BARD 四类模型”已经接入，因此本报告不采用该说法。

关键权重：

- `runs/detect/ball/weights/best.pt`：21.45 MB，SHA256 `800dab7c265b4cf9e488f75eb293f659f34a6efa86300c4823563887329072d9`
- `runs/detect/rim/weights/best.pt`：同一 SHA256
- 外置 `aihoop_assets/models/rim_ball_v6.pt`：同一 SHA256
- 外置 `aihoop_assets/models/rim_ball.pt`：SHA256 `b9d9c3d1c1db87b4788185cc422b67596a3058be843b494be02cfeebd4ba8`
- `jersey_numbers_rejected_20261009.pt` 明确是 rejected 文件，不应作为活动模型。

### 缺失交接资料

以下 8 份被交接说明点名的文件在项目与外置资源目录中均未找到：

1. `CV_SUMMARY_2026-10-16_2126_TO_2026-10-18.md`
2. `CV_DELIVERY_2026-10-18_1946_TO_2135.md`
3. `CV_GENERAL_STAGE1_2026-10-16.md`
4. `CV_STAGE2_PART1_2026-10-18.md`
5. `CV_REVIEW_SPARSE_2026-10-18.md`
6. `CV_TACTICS_CONTINUITY_2026-10-18.md`
7. `CV_CURRENT_JOB_A099_2026-10-17.md`
8. `CV_ANNOTATION_PROTOCOL.md`

因此，服务器阶段中“自适应候选”“shadow release”等模块是否存在、默认是否开启、历史指标是多少，均不能仅凭交接文字认定。

## 3. 检查点 B：人工真值与本地基线

### 可用真值

`eval/ground_truth/shots_split2_20261011.json` 完整标注 31 次出手，当前 SHA256 为：

`0e8e2e4be0c6a6c1f9d2e8ce1184cd447e210df950013d38f3ecea9821937e82`

与冻结基线 `eval/baselines/events_players_off_split2_20261011.json` 记录的真值哈希完全一致。

建议按以下口径继续使用：

- 开发/调参：fixedcam 7 次 + game01 14 次，共 21 次；已有 `tuning_split2.json`。
- 单次保留验证：game03 10 次。不要在看过验证结果后继续反复调参。
- Bili 三场样例已用于产品示例和人工修正，只适合作为开发/演示数据，不作为独立测试集。
- `match_testset_20261011.json` 中 4 段现存视频的 SHA256 全部与冻结值不一致，当前不能作为锁定独立测试集。必须先找回原始文件或重新确认、重新标注并生成新版本清单。
- `nathan_freethrow.csv` 与 `dairy_courts.csv` 只有表头，不能当逐球定时真值。

### 冻结基线指标

条件：关闭球员检测、比分牌和自动滑动标定；事件匹配容差 ±1.5 秒；全自动、无人工回填。

| 指标 | TP | FP | FN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| 出手事件检出 | 26 | 7 | 5 | 78.79% | 83.87% | 81.25% |
| 确认命中（端到端） | 7 | 3 | 3 | 70.00% | 70.00% | 70.00% |

匹配事件结果矩阵：

- 真命中→确认命中：7
- 真命中→未中：1
- 真命中→未知：1
- 真未中→确认命中：2
- 真未中→未中：2
- 真未中→未知：13

“未知”共占匹配事件 14/26。它不是误判为未中，应单列为证据覆盖不足。后续优化要同时报告：事件检出、确认结果、未知覆盖率，不能只报一个总准确率。

### 当前代码真视频复核

对 `fixedcam_shooting_960x540_7shots.mp4` 的 23.5 秒片段重新进行 GPU 推理：

- 真值出手：7
- 引擎事件：7
- 匹配：7
- 漏检：0
- 多报：0
- 确认命中：3
- 7 条事件的离手时间、结果、判定时间、穿筐时间与 evidence 字段均与冻结基线一致。

产物：

- `out/local_handover_fixedcam/results.json`
- `out/local_handover_fixedcam/s2_fixedcam_7shots/raw_track.json`
- `out/local_handover_fixedcam/s2_fixedcam_7shots/evaluation_segment.mp4`

## 4. 检查点 C：本轮决定

本轮不进入算法阈值优化。检查点 A/B 已证明本地可运行和基线可复现，但尚未具备可信的独立测试集，也缺失服务器阶段报告。此时选择某个开发集表现最好的恢复开关并改默认值，无法证明泛化，风险高于收益。

下一轮最小闭环应是：

1. 修复或重建 `match_testset_20261011.json` 的素材身份，锁定文件哈希。
2. 保持 game03 只做一次保留验证。
3. 从调优集只选择一个假设，例如“球 ROI 恢复”或“筐周高分辨率恢复”，先写明预期改善的失败类型。
4. 一次性跑调优集、保留验证和锁定测试集。
5. 同时报告事件 Precision/Recall/F1、命中 Precision/Recall/F1、未知率、每类失败数量、耗时和显存。
6. 验证失败立即回退，不叠加第二个变量。

## 5. 本轮工程修复

为恢复门禁，做了以下小范围修复，不改变投篮判定：

- 修正半场镜像测试：比较相反进攻端的对应坐标；同一端的左右位置本来不应重合。
- 缩短战术页一条常驻说明。
- 更新文案预算到当前战术页基线并保留余量。
- 将浏览器/框架 API 名称加入文档引用检查器白名单，消除误报。
- `启动后端.bat` 增加 UTF-8 code page 声明。
- 新增只读环境审计脚本 `scripts/check_local_handover.py`。
- 新增冻结基线汇总脚本 `scripts/summarize_frozen_baseline.py`。

## 6. 验证状态

- 核心 Python、API、投篮、比分牌、战术层测试通过。
- 两个历史重点之一 `test_tactics_end_to_end_and_frames` 已由完整门禁实际运行并通过。
- `test_soft_failure_exit_carries_both_keys` 所在文件依赖 pytest；本机缺少 pytest，因此未声称已运行该用例。
- 通用真值检查器会把 `scoreboard_vid3.rim_times.json` 当成不支持格式并报错；31 次出手主真值和 21 次调优真值检查通过。这是检查器覆盖范围问题，不是主真值损坏。
- 修复后重新运行 `scripts/check_all.py`：全部通过。

## 7. 复现命令

```powershell
cd D:\dsh_folder\aihoop
$env:PYTHONPATH='D:\dsh_folder\aihoop\src;D:\dsh_folder\aihoop_assets\_patch;D:\dsh_folder\aihoop_assets\libs'
$env:PYTHONIOENCODING='utf-8'

E:\python\python.exe -B scripts\check_local_handover.py
E:\python\python.exe -B scripts\summarize_frozen_baseline.py `
  --truth eval\ground_truth\shots_split2_20261011.json `
  --baseline eval\baselines\events_players_off_split2_20261011.json `
  --out eval\baselines\local_baseline_summary_20261020.json
E:\python\python.exe -B scripts\check_all.py
```

短视频 GPU 复核使用临时清单 `_tmp/handover_fixedcam_truth.json`：

```powershell
E:\python\python.exe -B scripts\eval_match_annotations.py `
  --truth _tmp\handover_fixedcam_truth.json `
  --out out\local_handover_fixedcam `
  --device 0
```

## 8. 风险与下一步

1. 磁盘余量不足 10 GB，跑完整比赛评测前应继续控制中间视频和 raw trace。
2. 补装与 requirements 对齐的 pytest 后，再跑历史多帧标定用例；安装前应固定版本并记录来源。
3. 找回 8 份服务器阶段报告，或明确声明它们已丢失并重新建立本地事实基线。
4. 将真值中的绝对视频路径逐步迁移为相对素材标识，但必须保留原始 SHA256，避免“路径修好、素材换了”的静默污染。
5. 建立真正锁定的独立测试集后，才开始第一轮小算法优化。
