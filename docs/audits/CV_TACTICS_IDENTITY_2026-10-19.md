# 战术图下一步：同镜头ID接续与分队证据

日期：2026-10-19，Asia/Shanghai。输出：`out/tactics_identity_20261019_191723/`。

## 1. 本轮结论

在现有轨迹拼接函数上增加外观、相机连续性及双向运动检查，并接入默认关闭的战术证据层。没有替换人物模型、BoT-SORT 或投篮引擎，没有修改正式服务。

当前开发视频中，暂保留 **3 处同人接续假设**。临时轨迹数由 234 变为 231，含分队未知人员的显示时刻由 93 变为 87。它们尚未人工确认，**不能据此声称身份识别准确率提升**。完整位置覆盖仍为 144/182 个战术采样时刻，尚未解决其余位置缺失。

同时验证了只开启原生 ReID 的方案：临时ID数量增加、轨迹中位时长下降，没有提供直接启用的证据，因此保持现有默认配置。

## 2. 基线身份与诊断

- 原任务：`44ffbf4e186d`，约 90.96 秒的 Development 素材。
- 原始 raw SHA-256：`be422bf32aecc8465f9317e220d598f5624246bf029bb0d745cfa0a5a7582fd2`。
- 解码视频 SHA-256：`af8c5ab309e6fcb61ed5e7294daeb1c0520179c04c7d8294f5c1016908ba9bf2`。
- 复用上一轮角色与外观证据：`out/tactics_population_20261019_183045/verified_run/evidence.json`。
- 原始240条临时地面轨迹，中位持续时间约1.334秒；角色过滤后保留234条、4788条测量。
- 已记录切镜：F902 / 30.0967秒、F1203 / 40.1401秒。不能认为这就是全部真实剪辑点。
- 源码开始快照：`before/`；复现实验快照：`verified_run/`；交付最终源码身份在 `final_source/`。

### 找到的阻断点

1. 已有 `stitch_player_tracks` 只凭同队、间隔和距离接续，默认3秒/2.5米、最多8轮，且默认关闭；原实现不接受 team_a/team_b 的匿名分组。
2. 短轨迹缺少足够球衣投票，直接继承旧队伍会把不确定性隐藏掉。
3. 投影坐标的运动不连续，会拒绝像素上仍相符的球员；因此不能只在投影坐标上做接续判断。
4. 真实在线人物跟踪默认使用安装包 `botsort.yaml`，`with_reid=False`。仓库已有另外的 ReID 配置，但不能把“已有文件”等同于“正在启用”或“启用后一定更准”。

## 3. 通用实现

### 接续流程

复用现有角色/分队结果 → 现有 stitcher 提议短间隔端点 → 原视频端点躯干外观 → 复用 `frame_motion.validated_forward_motion` 的 ORB/RANSAC → 双向像素运动检查 → 唯一候选门槛 → 战术专用 alias。

- 不接时间重叠的轨迹，不接不同已知队伍，不跨已知切镜。
- 端点至少各有两次真实外观观测。只取躯干，合并低饱和像素的色相噪声。
- 同队相同球衣颜色不足以证明同一个人；必须同时满足空间、相机和运动条件。
- 外观不足的空间合理候选仍会阻止强行选择另一名球员。
- 记录原始 head/tail ID；链式拼接后继续用真实原始端点取证。
- UNKNOWN 只有通过完整接续门槛后，才可能借同一轨迹的已有分组证据补充队伍；不传播到附近未连接的球员。
- 相机补偿只用于判断两个观测是否可能属于同一人，不增加真实位置、不平滑原始坐标、不延长旧轨迹有效期。
- 原角色、队伍、投篮及球员统计数据保持原样，alias只作用于离线战术输入。

### 为什么加入像素运动检查

先保留原球场坐标判据做对照，再增加相机补偿后的像素运动。例：

| 接续假设 | 原片帧/时间 | 球场预测误差（前向/后向） | 补偿后像素误差/身高 | 当前判断 |
| --- | --- | ---: | ---: | --- |
| T68 → T196 | F72 2.402秒 → F84 2.803秒 | 2.265 / 1.377米 | 0.195 | 保留假设 |
| T3312 → T3897 | F1716 57.257秒 → F1718 57.324秒 | 0.259 / 0.148米 | 0.062 | 保留假设 |
| T4794 → T4829 | F2232 74.474秒 → F2236 74.608秒 | 1.038 / 1.078米 | 0.144 | 保留假设 |
| T2557 → T2522 | F1344 44.845秒 → F1350 45.045秒 | 0.314 / 0.516米 | 0.532 | 拒绝：像素运动不一致 |

这说明两种坐标证据会产生不同建议。没有为了增加拼接数量放宽原0.75米判据；两组试验都保留，尚需人审核同人关系。

## 4. 对照结果

所有组使用相同原始测量和上一轮分队/角色证据，均限定短时间空间候选：

| 组合 | 拼接假设数 | 临时轨迹数 | 含未知分队的显示时刻 | 未知分队位置点 | 显示时刻 | 测量数 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 上一轮 | 0 | 234 | 93 | 134 | 144 | 4788 |
| 仅空间接近（对照假设） | 25 | 209 | 76 | 109 | 144 | 4788 |
| 外观+相机+球场运动 | 2 | 232 | 93 | 134 | 144 | 4788 |
| 外观+相机+像素运动 | 3 | 231 | 87 | 125 | 144 | 4788 |

仅空间接近的较少ID与未知数不构成准确率证明，也没有启用该组正式输出。像素方案相邻战术帧共享ID计数411→412，同样只是连续性诊断。

显示位置点653→652：alias合并后，原先两个片段端部保持与单条轨迹内部大间隔的处理略有不同；原始4788条测量未删除。没有通过延长插值窗口把这个差异补回去。

证据层首次提议38对短间隔端点。逐对拒绝原因见 `verified_run/link_audit.json`，包含外观不一致、运动预测不一致、测量不足、端点时间不符等。`eligible` 是通过单对证据门槛，`linked` 才表示最终唯一接续；两者都不是人工真值。

## 5. 实时跟踪的单因素ReID试验

复用本地 COCO yolov8n 人物模型，在同一原片0～16秒、240个相同采样帧上比较。imgsz=960、conf=0.25、stride=2。由当前安装包配置复制两份，**只改变 with_reid**；`model=auto`使用检测器自身特征，确认无外部ReID权重回退。该窗口参数为显式离线试验设置，不冒充原任务全部隐藏参数。

两条路径都先预热并清除空白帧跟踪状态，逐帧交替运行顺序：

| 设置 | 人员跟踪输出条数 | 临时ID数 | 中位ID跨度 | 同步调用墙钟 |
| --- | ---: | ---: | ---: | ---: |
| with_reid=False | 3760 | 150 | 1.268秒 | 5.476秒 |
| with_reid=True，原生特征 | 4141 | 209 | 0.601秒 | 5.451秒 |

此处包含裁判、观众，未做场内过滤；输出条数不同不能当作检测召回提升。当前代理指标不支持直接启用该配置；IDF1、真实ID切换率、角色准确率均缺少真值，不可计算。微小耗时差不作为提速结论。

## 6. 文件与配置

| 文件 | 修改 |
| --- | --- |
| `src/aihoop/sources.py` | 扩展已有stitcher的可选证据回调、匿名分组/未知支持、原端点来源、唯一性和决策日志；旧调用默认行为保留 |
| `src/aihoop/tactics_roster.py` | 端点描述、外观距离、相机及运动评估、过滤后输入签名、默认关闭的接续入口 |
| `src/aihoop/pipeline.py` | 战术专用接续；合并原视频与配置提供的切镜边界；不改变正式事件身份 |
| `scripts/compare_tactics_identity.py` | 原片证据采集、三组比较、完整导出校验、紧凑审核页 |
| `scripts/benchmark_player_tracking.py` | 原生ReID单因素试验、预热、计时、模型与输入身份 |
| `scripts/compare_tactics_population.py` | 保持旧证据缓存兼容，只校验实际外观采集参数 |
| `scripts/render_tactics_population.py` | 复用原诊断视频导出器，增加接续前后ID对照 |
| `web/tactics-preview.html` | 支持不同实验的选项名称及默认组 |
| `tests/test_tactics_identity_evidence.py` | 13个针对真实风险的测试：切镜、异队、重叠、歧义、旧证据、链式来源、原坐标不变、投影抖动等 |
| `tests/tactics_population_browser.mjs` | 复用浏览器检查，增加接续身份和3处/6图审核页检查 |

`RosterEvidenceConfig.stitch_tracks=False` 为默认；角色、球队开关仍默认False。

| 配置 | 默认 |
| --- | ---: |
| stitch_max_gap_s | 0.5秒 |
| stitch_max_dist_m | 1.5米 |
| stitch_max_prediction_error_m | 0.75米，court对照使用 |
| stitch_max_appearance_distance | 0.35 |
| stitch_min_endpoint_samples | 每端2个测量 |
| stitch_max_iterations | 100，实际到无唯一候选即停止 |
| stitch_motion_space | camera_pixels；可选court |
| stitch_max_pixel_error_ratio | 0.2，按端点人物框高度归一化 |

停用 `stitch_tracks` 即回退上一轮战术输入；没有修改已保存任务，不需恢复原任务文件。

## 7. 验证结果与性能

- 相关最终定向测试：43 passed。
- 全量：707 passed、2 failed、15 skipped、9 subtests passed。失败仍为既有的 `test_soft_failure_exit_carries_both_keys` 和 `test_tactics_end_to_end_and_frames`；见 `regression.log`。
- 浏览器：接续前T196、接续后T68、播放推进、灰色未知、匿名分组提示通过；审核页仅3处/6张图，全部可加载。
- events.jsonl、shots.csv、stats.csv、players.json、shotchart.json逐文件SHA一致；投篮timeline与总分一致。
- 原始raw SHA及内存数据未变；正式快照171个清单文件未变，正式进程未重启，记分牌融合仍禁用。
- `check_runtime_contract.py`、`git diff --check`通过。
- 端点解码与描述约3.96秒，背景几何约3.03秒；复用上一轮模型观测，无新增检测GPU推理。ReID单因素试验另有GPU调用，如上表，不能混为网站端到端耗时。

## 8. 审核入口和视频

- 本机战术对照：`http://127.0.0.1:8133/`。
- 本轮优先审核：`http://127.0.0.1:8133/review.html`。只需确认每行是不是同一个人，回复“同一个人 / 不同人 / 看不清”，无需重标篮球或精确时间。
- 队列：`verified_run/identity_review_queue.json`，全部pending，不用于运行时推理。
- 三段诊断视频：`diagnostic_videos/population_01.mp4`（1.702～3.503秒）、`population_02.mp4`（56.557～58.024秒）、`population_03.mp4`（73.774～75.308秒）。

## 9. 复现

```bash
cd /data/projects/ai-basketball-analyst
export PYTHONPATH=src:scripts
export PATH=/data/projects/ai-basketball-analyst/out/cv_baseline_20261015/tools:$PATH

# 每次选择尚不存在的新输出目录
/data/conda-envs/ai-basketball-analyst/bin/python scripts/compare_tactics_identity.py \
  --raw out/44ffbf4e186d/raw_track.json \
  --evidence out/tactics_population_20261019_183045/verified_run/evidence.json \
  --out out/tactics_identity_reproduce_01

# 地面运动对照：其他配置相同
/data/conda-envs/ai-basketball-analyst/bin/python scripts/compare_tactics_identity.py \
  --raw out/44ffbf4e186d/raw_track.json \
  --evidence out/tactics_population_20261019_183045/verified_run/evidence.json \
  --motion-space court --out out/tactics_identity_court_reproduce_01

/data/conda-envs/ai-basketball-analyst/bin/python scripts/benchmark_player_tracking.py \
  --raw out/44ffbf4e186d/raw_track.json --out out/tracker_reid_reproduce_01

/data/conda-envs/ai-basketball-analyst/bin/python -m pytest tests/test_tactics_identity_evidence.py -q
/data/conda-envs/ai-basketball-analyst/bin/python -m pytest tests -q
node tests/test_tactics_motion.js
node tests/test_pass_network_focus.js
```

## 10. 剩余问题

尚有大量ID碎片、人员漏检与投影缺失；本轮不是全场身份识别完成。相同球衣的近距离球员、转身/遮挡、同机位剪辑与回放仍会造成歧义。ORB连续背景也不能单独证明比赛时间连续。

下一步先核实3处接续是否真实，再针对有测量却投影跳变的窗口修正球场坐标稳定性，并整理少量同队交叉跑位的身份负例。保持独立比赛用于后续验证，不能在这条开发素材上反复调参后宣称泛化。
