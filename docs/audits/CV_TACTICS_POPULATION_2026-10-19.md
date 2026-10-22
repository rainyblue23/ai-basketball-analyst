# 战术图人数异常：分队与裁判证据修复

日期：2026-10-19（Asia/Shanghai）。开发工作区 HEAD：`56b9317d8cc561199786811069d54c40d2e47da5`，含大量既有未提交修改；本报告不把 HEAD 当作完整源码身份。

## 1. 结论与边界

本轮继续处理任务 `44ffbf4e186d` 的战术图人数异常。保留上一轮的轨迹有效期、切镜边界和速度约束，增加可独立启用的角色/分队证据处理，复用现有 E-BARD、PlayerRoleClassifier、球衣取色及聚类。

在这条约 91 秒的开发视频上，182 个战术采样时刻中：异常时刻从 18 个减至 0 个，有位置可显示的时刻从 126 个增加至 144 个。没有裁掉“多出来”的前五人，也没有补造十名球员。

**这些数字是显示覆盖和规则触发计数，不是人数、角色、分队准确率。** 改后仍有 93/144 个显示时刻包含分队未知人员；653 个显示位置点中，519 个有外观分组、134 个分队未知。缺少逐帧人员角色与队伍真值，准确率暂不可计算。剩余 38 个采样时刻仍缺少可信位置，不用无限保持旧位置补齐。

未部署、未重启正式服务、未修改默认权重、未训练、未启用记分牌融合，未覆盖原任务分析结果。

## 2. 输入与证据身份

- 原始检测结果：`out/44ffbf4e186d/raw_track.json`。
- 原结果 SHA-256：`be422bf32aecc8465f9317e220d598f5624246bf029bb0d745cfa0a5a7582fd2`。
- 实际解码视频 SHA-256：`af8c5ab309e6fcb61ed5e7294daeb1c0520179c04c7d8294f5c1016908ba9bf2`。
- E-BARD：`models/BODD_yolov8n_0001.pt`，SHA-256 `dfe3534d51bb21024d1a400c37f0c1fbf0c8b96ea9a56a5f3cb5454813bfd641`。
- 人员像素观测：5216 条，1093 个观测帧。原始逐帧检测上下文 2726 帧；输入 FPS 约 29.97。
- 输出根目录：`out/tactics_population_20261019_183045/`。
- 开始源码快照：`before/`；最终复现快照：`verified_run/source_snapshot.tar.gz`、`verified_run/source_manifest.json`。新增 `.mjs` 浏览器测试另外纳入交付源码清单。

材料均为 Development，不是跨比赛独立测试。

## 3. 根因与取证

### 3.1 “同队超过五人”不等于“总人数超过十人”

剩余 18 个异常时刻都是原分类的 away 组有 6～7 人，总人数均不超过 10。时刻为 9、13、13.5、14.5、16、26.5、32、32.5、33、33.5、44、44.5、45、76、76.5、77.5、78、78.5 秒。

原分队是按整段轨迹聚类，类别数量不代表同一帧的阵容。没有三次球衣采样的 ID 还会保留初始队伍值，不能把这个初始值当作可信分队。原始类别置信度是全局聚类分离度，没有每条轨迹的投票一致性。

### 3.2 取色错误与肤色歧义

`VideoSource._jersey_color_of` 原肤色过滤的布尔括号不正确，已修正。随后发现两个需要区分的问题：

1. 只按色相取众数，白/灰球衣会因色相噪声被分散到多个箱；其红色条纹或背景可能赢得众数。现将低饱和像素按亮度合并。
2. 暖光中的白球衣也可能落入肤色 HSV 范围。13.5 秒的实际躯干裁剪中，T853 有约 89.2% 像素落入旧肤色区间；T1025 约 69.9%。把它们全部剔除，剩余像素不能代表球衣。离线试验允许保留这些躯干像素，靠多帧一致性及角色证据约束，不以肤色直接认定身份。

`jersey_contact.jpg`、`torso.jpg` 是工程检查图，不是已审核真值。默认采集主流程仍保持兼容；新的躯干试验取色只在显式运行离线工具时使用。

### 3.3 裁判与身份未知

复用 E-BARD 的 referee/player 输出与 `PlayerRoleClassifier`，使用多帧 IoU 投票。只在同一时间、同一临时 ID 有足够裁判证据时，从战术人员中排除。保留 428 条被排除观测的原因记录；它们是观测条数，不是 428 名裁判。投票在切镜及轨迹缺失后失效，不跨镜头套用。

角色 UNKNOWN 不直接删除。分队 UNKNOWN 不当作第三支最多五人的球队；它仍计入总人数十人的约束。已知分组仍限制最多五人。

## 4. 改动清单与调用关系

| 文件 | 作用 |
| --- | --- |
| `src/aihoop/sources.py` | 修正诊断取色括号；低饱和像素合并；可选保留躯干肤色区间；保守分队增加单轨迹投票/间隔置信度，未知不继承默认队伍；色相特征要求饱和度可靠 |
| `src/aihoop/tactics_roster.py` | 默认关闭的证据应用层、配置校验、输入签名；按时间处理裁判证据；外观分组输出 team_a/team_b/unknown |
| `src/aihoop/pipeline.py` | `PipelineConfig.tactics_roster` 显式启用；证据只作用于战术输入，投篮、热区及球员统计使用原数据；动画与人数审计复用同一配置及帧结果 |
| `src/aihoop/tactics.py` | 未知组人口语义；未知身份不产生队伍传球/控球结论；含未知分队的时刻不生成球队阵型和空间统计；位置可展示与战术统计可用性分开 |
| `web/pages/tactics.js` | 人数质量计算统一；支持匿名分组标签；避免把灰色组当成超员球队 |
| `web/court.js` | 分组 A/B 颜色和传球箭头；未知队伍提示；轨迹编号移至点旁，用深色字和浅色描边保证完整可读 |
| `web/tactics-preview.html` | 离线原结果/角色/分队/组合四组对照与未知计数 |
| `scripts/compare_tactics_population.py` | 真实视频采集、缓存签名验证、四组消融、原始数据保护、完整导出一致性检查 |
| `scripts/render_tactics_population.py` | 从异常时刻自动选窗口，输出原始标签和实验标签对照视频，维持原视频时间戳 |
| `tests/test_tactics_appearance_evidence.py` | 白球衣/条纹/肤色歧义、低饱和色相、未知统计、证据时效与配置绑定、管线不改投篮等回归 |
| `tests/test_tactics_motion.js` | 未知人数语义、颜色、完整标签和已有播放插值检查 |
| `tests/tactics_population_browser.mjs` | Chromium 真实页面加载、切换、播放、未知提示、截图；关闭缓存，避免把旧脚本当成新结果 |

调用顺序：现有观测 → 已有角色/取色/聚类 → 带输入签名的 evidence.json → 可选战术证据层 → PlayerIndex → 原战术分析/导出。没有替换 YOLO、BoT-SORT 或投篮状态机。

## 5. 配置与回退

`PipelineConfig.tactics_roster=None` 为默认值。`RosterEvidenceConfig.use_roles=False`、`use_teams=False`，均不自动启用。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| referee_confidence | 0.8 | 战术排除需要的多帧裁判置信度 |
| team_min_votes | 3 | 最少外观采样数 |
| team_min_margin | 0.25 | 聚类最近与次近中心的归一化距离差 |
| team_min_vote_share | 0.7 | 单轨迹采样投票一致性 |
| hue_min_sat / hue_min_share | 60 / 0.8 | 使用色相分队所需的饱和度及组内比例 |
| jersey_skin_filter | False | 离线躯干取色试验保留肤色范围像素；不是球/人头过滤开关 |

采集工具当前每轨迹最多 12 次球衣采样、间隔至少 0.15 秒，角色检测 imgsz=1280、conf=0.25，复用角色匹配门槛 IoU=0.5、专用类别 conf=0.6、最少三票。所有运行设置写入证据。没有从人数倒推队伍配额。

证据与视频路径、FPS、像素框、地面轨迹、镜头切换绑定；输入或取色配置不符即拒绝应用。停用 `tactics_roster` 即回退到原战术输入；原任务文件没有改动，无需恢复已有结果。

## 6. 对照结果

同一原片、原始轨迹、模型、角色证据，四组只切换证据层开关：

| 组合 | 异常时刻 / 182 | 可显示时刻 | 含分队未知的显示时刻 | 显示位置点 |
| --- | ---: | ---: | ---: | ---: |
| 原轨迹有效期修复 | 18 | 126 | 0（旧分类没有表达未知） | 578 |
| 仅角色证据 | 15 | 129 | 0 | 549 |
| 仅多帧外观分队 | 1 | 143 | 111 | 701 |
| 角色 + 多帧分队 | 0 | 144 | 93 | 653 |

单独角色过滤不能解决分队问题；单独分队也不能可靠排除裁判。未知增加是保留不确定性的结果，不应作为分队提升的证明。

四组共享同一份采集证据；外观原型采样已避开有裁判证据的观测。因此这里是证据应用层的开关对照，不是完全移除角色模型后的端到端消融。

途中保留了两次未采纳试验：`experiment/` 的原色相取色与 `achromatic/` 的仍硬剔肤色版本。后者使全局聚类失效、人员全部成为未知，虽然人数门槛不再报警，也不能视为修复成功。最终使用 `torso_evidence/` 的实测采集，`verified_run/` 在同一证据缓存上重放并验证完整管线。

最终外观特征为 val，sat 分离度接近；主客身份尚未核实，所以仅标分组 A/B。缺少帧级完整真值，球员角色、球队分类、人数准确率均为不可计算。

## 7. 性能

Quadro RTX 5000，16 GiB。1093 个角色补充推理帧：同步 YOLO 调用墙钟耗时约 11.18 秒，解码与证据采集合计约 16.31 秒。该时间不是纯 GPU kernel 时间，也不是网站完整分析时间。

最终重放使用缓存，不重复推理；报告保留原采集耗时，不能把重放耗时误报为模型提速。每组战术动画构建约 0.02 秒。没有增加生产请求耗时。

## 8. 测试

- 定向 Python：39 passed。
- 全量 `pytest tests -q`：694 passed、2 failed、15 skipped、9 subtests passed。两处失败与上一轮报告一致：
  - `test_multical_mini_and_snap.py::test_soft_failure_exit_carries_both_keys`：标定软失败提示不含断言要求的“4 个点”。
  - `test_plan_b.py::test_tactics_end_to_end_and_frames`：合成数据 t=15 秒没有可信位置，旧测试要求前 200 帧全不为空。未为了通过测试而延长旧位置有效期。
- `test_tactics_motion.js`、`test_module_jersey.js`、`test_pass_network_focus.js`、`test_results_refresh.js` 通过。
- Chromium 页面加载、13.5 秒原结果异常/实验显示六人、14.5 秒未知提示、播放推进通过；最终截图使用关闭缓存的复核。
- `check_runtime_contract.py` 通过；`git diff --check` 通过。
- 完整导出对照：投篮 timeline、shotchart、players 统计一致，改后导出 182 个战术帧。
- 正式运行快照 171 个清单文件逐个 SHA 校验未变化；原 raw SHA 未变化。
- 曾误从项目根目录执行不限定路径的 pytest，因历史产物递归收集过慢而中断；它不是测试失败结果。有效全量命令明确限定 `tests`，见 `regression_final.log`。

## 9. 查看入口与复现

本机离线入口：`http://127.0.0.1:8132/`。只能在这台 Ubuntu 打开；不是正式网站部署。

四个诊断视频位于 `out/tactics_population_20261019_183045/diagnostic_videos/`，原片窗口分别为 12～17、31～34.5、43～46、75～79.5 秒。这些窗口由原异常记录自动选取，不参与推理规则。视频显示原始像素框/角色证据，网页显示球场投影；两者都不是人工真值。

```bash
cd /data/projects/ai-basketball-analyst
export PYTHONPATH=src:scripts
export PATH=/data/projects/ai-basketball-analyst/out/cv_baseline_20261015/tools:$PATH

# 选择一个尚不存在的新输出目录，保留已有结果
/data/conda-envs/ai-basketball-analyst/bin/python scripts/compare_tactics_population.py \
  --raw out/44ffbf4e186d/raw_track.json \
  --out out/tactics_population_reproduce_01

# 复用本轮实测证据，不重复 GPU 推理
/data/conda-envs/ai-basketball-analyst/bin/python scripts/compare_tactics_population.py \
  --raw out/44ffbf4e186d/raw_track.json \
  --evidence out/tactics_population_20261019_183045/torso_evidence/evidence.json \
  --out out/tactics_population_cached_reproduce_01

/data/conda-envs/ai-basketball-analyst/bin/python -m pytest tests -q
node tests/test_tactics_motion.js
node tests/test_module_jersey.js
node tests/test_pass_network_focus.js
node tests/test_results_refresh.js
/data/conda-envs/ai-basketball-analyst/bin/python scripts/check_runtime_contract.py
```

## 10. 下一步

1. 优先审核四个差异窗口里的角色、两组球衣归属和场外人员，允许只圈出错误，不要求重复标全部相似帧。
2. 在不同比赛上检查白/深色球衣、颜色相近、阴影、遮挡；目前没有独立测试准确率证据。
3. 进一步处理轨迹碎片化与人员漏检。234 个仍保留地面轨迹的临时 ID 不等于 234 名真实球员，不把跨镜头 ID 当真实身份。
4. 区分不完整阵容的展示与阵型结论，完善真实球队映射后再评估正式启用。此轮没有承诺全程十人或战术完全连贯。
