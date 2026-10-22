# 球场配准缺失恢复与补充机位审核

日期：2026-10-20。当前工作为离线 Development 实验，未发布网站或修改正式运行副本。

## 输入与诊断

延续任务 `0c19396bf72c`：上一轮离线战术位置可显示145/182个半秒采样点，空间指标为60/91个秒级采样点。原保存任务仍为51/182与25/91，未被覆盖。

- 视频：`yang-retry2_8828aea2e1_dc67d140c8aa1d9f.mp4`，1920×1080，29.97002997 FPS，约90.96秒。
- 视频SHA-256：`af8c5ab309e6fcb61ed5e7294daeb1c0520179c04c7d8294f5c1016908ba9bf2`。
- 原始轨迹SHA-256：`1f9039e5647298d6235c1264c026973bdabf9b39bec55ac90a83534c3a75bf67`。
- 本轮证据：`out/calibration_recovery_20261020_183838/`。最终以`final_verified/`为准，其余实验目录为保留的中间结果。

37个缺失时刻均有person检测上下文，主要阻断点是当前镜头无法与两张侧视手标参照可靠配准，并非这些时刻无人被检测。特别是34.5～40秒采用正面罚球机位，需要补充对应机位参照。

根据少量代表帧的工程目视检查，最终剩余33个半秒采样点中：12个来自正面罚球机位，2个为仍未可靠匹配的普通广角画面，19个为特写、替补席或转场叠影。该分类尚不是完整人工真值，不应作为训练标签或准确率分母。

## 低风险修改

复用`MarkedProjector`既有ORB、白线几何和手标参照，不增加模型、不修改原标定、不沿用无验证的旧坐标。

新增默认关闭的`RegistrationOptions.local_recovery`。只有直接配准失败时，才尝试附近有独立手标匹配支持的实测帧：

- 锚点间隔0.25秒，最远0.75秒，最多6个候选，至少3个相互一致的独立锚点。
- 不跨已知切镜；局部恢复结果不能再作为锚点递归传播。
- 至少24个匹配、24个内点、0.4内点比例，RANSAC阈值2像素，白线拟合比至少1.25。
- 原生球场网格投影的中位差不超过图像对角线0.005，最大差不超过0.015；没有足够共同可见地面支持时拒绝。
- 对地面区域做曝光偏移补偿后的像素一致性检查：中位差≤20，差值超过24的像素比例≤0.45。
- 缓存有界；失败保持未知，不延长轨迹有效期。

最后一道检查来自实际负例：51秒双重曝光转场在不加检查时会被局部几何错误接受；该帧地面差异中位值50、变化比例0.782，最终版本拒绝。正常恢复代表帧的对应值为4～7与0.168～0.235。这只是开发负例验证，尚无跨比赛阈值泛化结论。

补投影只读取原始缓存中的真实person测量帧。显式指定检测步长2，排除奇数帧沿用的旧框、预测框及时间戳不匹配记录，使用bbox脚点重新投影。原有位置、球队分组和投篮事件保持不变；新增未确认身份仍为UNKNOWN。

## 真实对照结果

| 方案 | 位置显示 / 182 | 人数异常拒绝 | 空间采样 / 91 |
| --- | ---: | ---: | ---: |
| 上一轮离线结果 | 145 | 0 | 60 |
| 本轮位置恢复 | 149 | 0 | 61 |
| 本轮位置恢复＋新增位置角色检查 | 149 | 0 | 61 |

恢复的0.25秒配准时刻：9.5、33.25、43.5、56.75、67.5、89.5秒。其中新增半秒显示时刻为9.5、43.5、67.5、89.5秒。共增加97条实测人员位置记录，不是97名球员。既有人员位置与原任务投篮事件未修改。

几何尝试墙钟14.094秒；角色证据采集的YOLO调用墙钟11.073秒，解码与证据采集合计16.657秒，覆盖1108帧。不是全视频端到端加速指标。

上述计数只能说明开发素材上输出覆盖变化。位置误差、球员身份、球队归属以及总体准确率尚无独立审核真值，不可计算。

## 补充人工标注状态

入口：`http://127.0.0.1:8137/recovery/registration-review.html`。

只需补一张正面图，提供原图、5个地面点示意、两张旧参照、撤销及JSON导出。对应端允许“不确定”；草稿保存在当前浏览器，不自动上传或改正式标定。

该图对应原片F1064，名义时间35.502133秒。图像SHA-256：`c1d37f6a94fdd347656e13e8bb28010adfcec4e08ad8f96377b24d41369aac31`。时间来自解码帧号/名义FPS，未单独审核VFR原始PTS。

用户已提供完成5点的截图。**截至本报告，尚未收到导出的`additional_court_view_01.json`，不能声称已读取坐标或补算成功。** 截图不作为精确坐标输入。收到JSON后应先核对视频/图像SHA、点名、端向与地面几何，再添加独立机位参照；不能只凭四点可解就认为标定准确。

## 修改文件

- `src/aihoop/marked_projection.py`：可选局部配准、锚点隔离、多锚点几何及地面一致性检查、审计原因。
- `scripts/recover_marked_calibration.py`：离线恢复、真实缓存框回放、旧输出保护、同任务对照。
- `scripts/render_registration_recovery.py`：代表帧、6段诊断视频、补充机位任务与输入身份。
- `web/pages/tactics.js`：明确区分球场尚未定位与人数异常，未知时不画旧位置。
- `web/registration-review.html`：单图地面点补充标注入口，支持本机草稿和JSON导出。
- `tests/test_marked_registration_recovery.py`：默认关闭、锚点数量/隔离、切镜、几何/叠影拒绝、缓存与测量时间戳回归。
- `tests/registration_recovery_browser.mjs`：真实页面对照、缺失机位说明及隔离浏览器标注交互。

## 测试与隔离

- 新增与相关Python定向测试：42 passed，详见`targeted.log`。
- 全量Python，在补齐Node PATH后：720 passed、15 skipped、2 failed、9 subtests passed，28.90秒。失败为`test_multical_mini_and_snap.py::test_soft_failure_exit_carries_both_keys`与`test_plan_b.py::test_tactics_end_to_end_and_frames`，详见`regression_with_node.log`。本报告不宣称全量通过。
- 首次全量多出一项失败是环境找不到Node；补齐既有工具路径后该项通过，首次日志保留为`regression.log`。
- 默认关闭恢复时，14个正负代表时刻的新旧直接配准结果及矩阵逐项相同，见`default_path_equivalence.json`。
- 浏览器：145→149位置显示、61个空间采样、35.5秒未知提示、51秒转场不补位置、单图载入及撤销/清空通过。合成点击仅用于隔离测试，已清空，未当成人工标注。
- JS战术运动、结果刷新、未中显示与运行契约检查通过；`test_unknown_style.js`的既有模板断言问题未作为已解决事项。
- 正式进程PID262365、固定副本171个清单文件及禁用记分牌融合设置保持不变；原任务文件逐项SHA未变。没有重启、发布、重训或覆盖原分析。

## 查看与复现

离线对照入口：`http://127.0.0.1:8137/`。诊断视频位于`final_verified/preview/recovery/case_01.mp4`至`case_06.mp4`，包含4个恢复窗口、正面机位缺参照窗口与叠影负例。

```bash
cd /data/projects/ai-basketball-analyst
export PYTHONPATH=src:scripts
export PATH=/data/projects/ai-basketball-analyst/out/cv_baseline_20261015/tools:$PATH

# 输出目录必须尚不存在；原任务与原证据只读
/data/conda-envs/ai-basketball-analyst/bin/python scripts/recover_marked_calibration.py \
  --job-dir deploy/runtime/20261016-152930/out/0c19396bf72c \
  --calibration out/calibration_recovery_20261020_183838/inputs/calibration.json \
  --evidence out/tactics_coverage_20261020_181008/population/evidence.json \
  --person-stride 2 --device 0 \
  --out out/calibration_recovery_reproduce_01

/data/conda-envs/ai-basketball-analyst/bin/python -m pytest \
  tests/test_marked_registration_recovery.py tests/test_marked_projection.py \
  tests/test_tactics_partial_spacing.py tests/test_tactics_roster_evidence.py \
  tests/test_tactics_appearance_evidence.py tests/test_tactics_identity_evidence.py -q
```

风险与回退：误配准会产生错误地面位置，故局部恢复默认关闭，仅在离线副本启用。关闭该开关即可恢复原直接配准路径，无需恢复原任务文件。下一步先导入并验证用户本次补充机位的精确标注，再评估12个正面机位采样；未定位的特写和转场继续留空。
