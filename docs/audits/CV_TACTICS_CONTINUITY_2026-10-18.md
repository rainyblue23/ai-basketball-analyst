# 投篮复查与战术图连贯性修复（2026-10-18）

证据目录：out/tactics_continuity_20261018_212243/。实际对照输入是最新杨瀚森任务`44ffbf4e186d`，不是此前a099或利拉德。原任务、固定线上副本未修改；不启用记分牌融合、不训练或更换模型。

## 1. 已修复

- 战术图改为全场视图，按原折半分析坐标正确恢复两端位置。原图取abs(y)叠到同一半场，可能让两个半场的人看起来重合。
- 临时编号A/B超过99不再回落“号码待确认”；未在球员表中的轨迹用T编号区分。已识别球衣号继续显示“X号”，不把轨迹编号假装成球衣号。颜色区分主客队并明确临时编号含义。
- 同ID/同队、同镜头、相邻≤.6秒且位移合理的球员位置在前端平滑显示；显示插值不写回统计。空帧、超员、切镜、跳跃和过期采样不强接轨迹。球观测不会由此变成真实检测。
- 新增默认关闭的`TacticsConfig.roster_evidence_filter`用于独立评估：不提前显示未来才出生的ID；末端保留≤.12秒；有双端支撑且间隔≤.25秒/速度≤12m/s才插值；不跨切镜。仅当同队强观测附近存在弱末端重影时剔除弱影，真实近身双方保留；不截取前五人。
- 新模式停止用0.8m距离一律删除相邻球员。球位置不再使用最长3秒的近邻陈旧点。真实观测仍超员时照常暂停推断。

## 2. 真实输入对照

| 口径 | 原版 | 有证据边界模式 |
| --- | ---: | ---: |
| 0.5秒采样时刻 | 182 | 182 |
| 超员被拒 | 99 | 18 |
| 无球员位置时刻（含超员） | 125 | 56 |
| 可显示球员位置时刻 | 57 | 126 |
| 秒级空间统计采样 | 29 | 59 |

这是算法输出覆盖的变化，不是经过真值审核的球员Recall或正确阵容提升。240条碎片ID仍未变成跨镜头真实球员身份；角色混淆、分队错误与坐标缺口尚有残留，不能承诺全片无断点。没有删掉人数警告假装修复。

可操作预览：http://127.0.0.1:8131 。可切换原结果/有证据边界模式、播放/拖动；仅回环离线预览。浏览器已核对全场viewBox18×31、编号不再同名、无JS异常。生产网页没有发布这些改动。

## 3. 投篮不能靠取消未知来判对

当前任务原引擎输出2 MADE与8 UNKNOWN。对8个UNKNOWN逐一取有界前后窗口，沿用同视频缓存人员/切镜、相同E-BARD和事件引擎，1280高分辨率/原置信度、两ROI关闭，原帧复查；复用重叠帧检测缓存，总窗口流水线墙钟约19.42秒，未读取人工答案。

| 原候选离手秒（代理可能不准） | 高分辨率窗口的自动视觉输出 |
| --- | --- |
| 16.05 | 14.98s UNKNOWN，穿筐时刻None |
| 18.42 | 没有建立视觉投篮事件 |
| 23.02 | 23.76s MADE，穿筐时刻24.658 |
| 25.23 | 23.76s MADE，穿筐时刻24.658 |
| 31.00 | 31.00s MADE，穿筐时刻32.332 |
| 46.01 | 46.38s MADE，穿筐时刻46.847 |
| 74.84 | 74.84s MADE，穿筐时刻75.742 |
| 84.95 | 84.95s MADE，穿筐时刻85.819 |

24.658秒同一穿筐证据在23.02/25.23两个重叠窗口出现，不能算两球。共出现5组不同穿筐视觉候选，不代表5次人工确认命中；窗口输出与原候选没有自动合并。16.05窗口的新14.98候选不能按时间接近强当原出手；18.42没有新事件不等于未中。

仍无法把所有UNKNOWN强行变成进/不进：没有球、遮挡、传球/争球假候选或切镜时，缺乏证据不能硬判MISS。未用放宽命中判据、比分直接计数或强派球员来凑结果。新增脚本为离线复查工具，尚未接入生产自动回查；不把“工具实现”说成以后所有视频都能判定。

## 4. 测试与边界

- 全量：686 passed、2 failed、15 skipped、9 subtests passed，29.86秒。既有软失败文案与synthetic战术空人员用例仍失败，保留断言。
- 相关Python18项通过：未来ID、长保留、切镜插值、陈旧重影、真实近身双方、不截五人、瞬移与陈旧球等。
- JS：球衣显示、全场投影、受限平滑、过期采样失效、传球网络与结果刷新回归通过。
- Attempt/Shot往返契约与文档引用有效；生产171文件SHA一致，原raw SHA不变。新源快照/补丁保留在final_source。
- 战术边界参数之外没有修改YOLO/BoT-SORT、阈值或正式投篮状态机。角色过滤和完整跨比赛准确率仍待验证。

## 5. 配置和复现

`roster_evidence_filter=False`保持兼容路径；本次离线模式显式True，参数roster_gap_s=.25、roster_hold_s=.12、roster_max_speed_m_s=12。camera_cuts_s从实际trace切镜读取；所有JSON保留segment以阻止显示跨切镜平滑。

```bash
cd /data/projects/ai-basketball-analyst
export PYTHONPATH=src:scripts
export PATH=/data/projects/ai-basketball-analyst/out/cv_baseline_20261015/tools:$PATH
AIHOOP_PY=/data/conda-envs/ai-basketball-analyst/bin/python
"$AIHOOP_PY" scripts/compare_tactics_continuity.py --raw out/44ffbf4e186d/raw_track.json --out out/tactics_repeat_new
"$AIHOOP_PY" scripts/recheck_uncertain_shots.py --raw out/44ffbf4e186d/raw_track.json --out out/shot_recheck_repeat_new
"$AIHOOP_PY" -m pytest -q tests
node tests/test_tactics_motion.js
node tests/test_module_jersey.js
node tests/test_pass_network_focus.js
# 当前预览已运行；另一轮可以另选空闲端口
"$AIHOOP_PY" -m http.server 8131 --bind 127.0.0.1 --directory out/tactics_repeat_new/preview
```

本轮10个代码/测试/预览文件：

- `scripts/compare_tactics_continuity.py`
- `scripts/recheck_uncertain_shots.py`
- `src/aihoop/pipeline.py`
- `src/aihoop/tactics.py`
- `tests/test_tactics_motion.js`
- `tests/test_tactics_roster_evidence.py`
- `web/court.js`
- `web/data.js`
- `web/pages/tactics.js`
- `web/tactics-preview.html`

## 6. 未完成

没有“所有投篮都判明”和“整片战术图连续且正确”的验收结果。下一步需要审核高分辨率穿筐候选、剩余18个超员时刻中真实人数/角色/球队，以及剩余缺坐标段；之后才能决定边界模式默认启用与自动回查事件融合。当前不部署、不重写已有结果。
