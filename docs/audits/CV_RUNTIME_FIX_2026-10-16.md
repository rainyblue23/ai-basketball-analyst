# 在线任务release_known参数失败与运行版本隔离

## 原因

任务c299e023441c在约50%处失败：`Attempt.__init__() got an unexpected keyword argument 'release_known'`。

服务PID220604自2026-10-15 21:48启动，仍保留旧sources.Attempt类。开发直接修改其PYTHONPATH所指工作区；视频任务到适配阶段才延迟导入新的legacy_shots.adapter，新适配器传入release_known，而进程中的旧类没有该字段。这是运行代码与开发代码未隔离造成的混合版本故障。

进度约50%对应检测结果转换为投篮记录，字段类型错误发生在算法阶段，不能用登录页返回200证明分析功能正常。此前fresh-process测试能通过，无法覆盖老服务延迟导入新模块的情形。

## 修复

- 服务固定使用`deploy/runtime/20261016-152930/`里的src、scripts、web副本；data、out、models、eval链接原项目资源，没有复制视频、账号库或权重。
- 工作目录与EnvironmentFile保持原位置，PYTHONPATH经用户级systemd drop-in改到固定副本的src。后续工作区修改不再进入已运行服务的延迟导入。
- 新增scripts/check_runtime_contract.py作为ExecStartPre：核对Attempt/Shot四个证据字段、模块来源及适配器到Shot的证据贯通；不匹配则在接收分析任务之前失败。
- scoreboard_fusion新增显式禁用开关。生产服务设置AIHOOP_DISABLE_SCOREBOARD_FUSION=1，保持用户暂停的记分牌融合改动禁用，离线测试默认行为不变。
- 2026-10-16 15:29:54完成服务切换，PID262365；重启前无running/queued任务。修复涉及步骤3～5代码一致加载，已经改变线上算法版本，不再沿用先前“尚未部署”的状态说明。
- 失败任务保留原job ID、视频、球场标定、篮筐框及分析参数，在固定副本下复跑；状态写回同一任务。失败前数据库行另行备份，未删除人工标定/纠错。

配置位置：`/home/john/.config/systemd/user/ai-basketball-analyst.service.d/70-pinned-runtime.conf`。原主unit未改。不要直接把PYTHONPATH退回正在修改的开发目录；需要回退时，应先选择一份通过契约检查的完整版本。

## 验证

- 契约/适配/投篮证据/记分牌禁用回归：42 passed，1.47s。
- 模拟旧Attempt类的测试，确认启动检查会拒绝缺字段的旧类。
- 固定副本171个文件的SHA清单复核一致。
- 重启后本机与公网登录页HTTP200；这只作为服务可达性检查。
- 完整分析复跑的最终状态与产物校验另存`out/runtime_fix_20261016/`，未在任务完成之前将其写成成功。
- 15:38:07，原任务c299e023441c复跑完成：status=done、progress=1、error=null；game、players、shotchart、events、report、tactics等产物已校验存在并可解析，10条时间线记录均保留release_known字段。广播比分融合输出为null。没有把此次10条程序事件当作人工验收准确率。

```bash
cd /data/projects/ai-basketball-analyst
PYTHONPATH=src /data/conda-envs/ai-basketball-analyst/bin/python -m pytest -q \
  tests/test_runtime_contract.py tests/test_shot_evidence_stage5.py \
  tests/test_shot_legacy_engine.py tests/test_scoreboard_fusion.py

PYTHONPATH=deploy/runtime/20261016-152930/src \
  /data/conda-envs/ai-basketball-analyst/bin/python \
  deploy/runtime/20261016-152930/scripts/check_runtime_contract.py
```

这些部署检查不代表篮球检测准确率提升；NBA漏检仍受前述检测证据不足限制。
