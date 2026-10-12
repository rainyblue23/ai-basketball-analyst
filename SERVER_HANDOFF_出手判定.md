# 出手判定专项交接（哨响之后）

> 这份是 `SERVER_HANDOFF.md` 的**专项补充**，只讲"出手判定的准确率"这一件事：
> 五轮实验各自做了什么、量到什么、哪些杠杆已实测否掉（**别再试**）。
> 通用部署/产品面交接看 `SERVER_HANDOFF.md`，两边不要互相覆盖。
日期：2026-10-12
写给：有 GPU、能跑训练的那台机器（本机磁盘只剩 ~1.7 GB，跑不了重活）

> ⚠️ **两条不能破的规矩**
> 1. 第 1 节最后那条：**留出段 `s2_hs_game03`（10 次出手）不许进训练集、不许用于任何选择**，
>    只在最后报数字时跑一次。（`SERVER_HANDOFF.md` 里"match_01/02 已用于训练"指的是**另一批**素材，
>    与这里的留出段不是同一批，两边不要混。）
> 2. 真值文件（`eval/ground_truth/*.json`）只由人改，程序只读；`scripts/bench_report.py` 不写真值。

---

## 0. 现在到哪一步了（先看这张表，别重复劳动）

| 指标（调参段 21 次人工出手） | 基线 | 现在 |
|---|---|---|
| 出手召回 / 精确 | 100% / 100%（固定机位段 7/7） | 同 |
| 转播段（`game01`，14 次）匹配 | 10 | **10**（五轮改动后仍是 10） |
| 漏检 | 4 | 4 |
| 多报 | 6 | 6 |
| 离手时刻偏差中位数 | +0.78 s（全偏晚） | **+0.03 s**（已修，但成绩没变） |
| 敢判时的结果正确率 | 9/12 | 9/12 |

**四轮下来所有证据指向同一个瓶颈：球检测器在关键帧上看不见球。**
两次真漏检那两段里，**篮球的原始候选只有 0~1 个/帧** —— 不是跟踪策略、不是时间戳、不是标定。

### 已经实测否掉的杠杆（**别再试**，试过并记录在案）

| 杠杆 | 结果 |
|---|---|
| 全图推理提到 `imgsz=960` | 转播段匹配 10 → **9**（更差） |
| `ball_roi_recovery=True` | 转播段 10 → **8**（更差，还多漏两次上篮） |
| 静止锁换锚（单独用） | 触发 303 帧可疑 / 14 次换锚，指标**完全不变** |
| 筐周围高分辨率复检（`ball_rim_recovery`） | 真跑了 371 帧，指标**完全不变** |
| **筐复检 + 换锚一起开**（理论上互补的组合） | 复检 412 帧、换锚 14 次，指标**仍然完全不变** |

---

## 1. 要做的第 1 件（唯一能真正提分）：重训 / 替换篮球检测模型

**为什么**：现在用的是 `runs/detect/ball/weights/best.pt`，在真实转播素材上对**小目标 + 运动模糊**的球命中率低。
球定位评测（`eval/annotated_balls` 口径）在 7 个真值框上只有 **IoU≥0.5 命中 2 个**。

**要什么数据**：
- 用现成工具标球框：`scripts/label_ball.py`（离线批量）或 `scripts/serve_match_labeling.py`（网页标注台，仅本机回环）
- 建议规模：**≥ 2 万帧**，覆盖：固定机位 + 转播（镜头平移）、远距离小目标（球宽 12~30 px）、运动模糊帧、遮挡帧
- **负样本同样重要**：把"被误当成球的静止物"（记分牌灯、场边标牌、人脸）单独收进去 ——
  实测跟踪器会锁在一个**随镜头平移的静止物**上（转播段 23% 的帧），根子就是这类误检

**怎么训**：`scripts/train_ball_detector.py`（主）、`scripts/train_nybo_model.py`、`scripts/train_ball_correction_pilot.py`（小样本修正）都有现成入口；建议输入分辨率 ≥ 960（球小，640 太糊）。

**怎么验收**（两步都要跑，缺一不可）：
```powershell
# ① 帧级定位：IoU≥0.5 / IoU≥0.3 / 中心落框 三种指标并列，不许合并叫"准确率"
python scripts\eval_annotated_balls.py --batch out\match_testset_20261011 `
       --weights <新权重> --out out\new_ball_eval.json
# ② 事件级：出手召回/精确/F1、敢判正确率、abstain 率
python scripts\eval_match_annotations.py --truth eval\ground_truth\tuning_split2.json `
       --out out\events_new --players
```
两条命令的参数与口径都写在 `eval/README.md` 里。

**硬规矩**：`eval/ground_truth/shots_split2_20261011.json` 里的 **留出段 `s2_hs_game03`（10 次出手）不许拿来做任何选择**
（调参、挑权重、挑阈值都不行），只在最后报数字时跑一次。

---

## 2. 要做的第 2 件：把真值扩到 ≥100 次出手（否则"准确率"没有统计意义）

- 现在 31 次出手，召回 83.9% 的 **95% 置信区间是 [67%, 93%]** —— 这个宽度下说"非常高"是不成立的
- 素材与观看清单见 `docs/需要人工标注的真值清单_2026-10-11.md` 与 `eval/ground_truth/templates/README.md`
- 标完用 `python scripts\check_truth_files.py` 自检（会挑出号码/时间/结果写错的地方，也会报"还差几条"）

## 3. 要做的第 3 件：给评测素材标一次地标（补标定类指标）

4 段素材都没有标定，所以「标定 RMSE / 弱段」到现在还是"未测"。
标法：用应用里的「标球场」面板、或 `scripts/mark_landmarks.py`；随后 `scripts/check_video_fit.py` 出 RMSE。

## 4. 要做的第 4 件：球衣号码真值（100+ 条轨迹）

`src/aihoop/jersey_numbers.py` 已经接进管线，但**没有独立人工标注的真值**，所以 top-1 说不出来。
格式与口径见 `docs/需要人工标注的真值清单_2026-10-11.md` 第 1 节。

---

## 5. 跑评测的固定环境（照抄，别漏）

```powershell
$repo='D:\dsh_folder\aihoop'; $assets='D:\dsh_folder\aihoop_assets'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONPATH="$repo\src;$assets\_patch;$assets\libs"
$env:YOLO_CONFIG_DIR="$repo\_tmp\yolo_cfg"; $env:TMP="$repo\_tmp"; $env:TEMP="$repo\_tmp"
```
- 说明：这台机器**没装 pytest**，跑单测用 `python -B _tmp\run_tests_tmp.py`（带 pytest 垫片）
- 评测每跑一轮会写 **0.6 GB 级**中间片段（`out/bench/.../*.mp4`），跑完记得删；本机磁盘已经很紧
- 结果对比：`eval/baselines/` 里冻结了每一轮的 `results.json`，新结果要跟**同一份**比

## 6. 结构性事实（写方案时要写进去，别当成 bug）

- 转播素材有镜头平移，`camera_motion.verdict = slightly_moving`；固定机位素材上这条链路 **7/7 全中、零多报**
- 出手结果判定的证据要求是"进筐 → 下降 → 出筐"三段；只看到"进筐"时引擎**选择不下结论**（abstain），
  调参段 15 次 abstain 里有 9 次是这种情况 —— 这是刻意保留的诚实口径，**不是缺陷**；改进方向是提高筐口附近的观测连续性
