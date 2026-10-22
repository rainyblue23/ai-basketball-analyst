# 正式服务与开发源码身份

审计时间：2026-10-21T21:35:24.023472+08:00（Asia/Shanghai）。项目：`/data/projects/ai-basketball-analyst`。证据目录：[out/server_git_handover_20261021_205145](out/server_git_handover_20261021_205145/)。本轮仅审计、隔离测试与报告输出；没有合并、变基、提交、推送、清理工作区或重启正式服务。

## 实际运行边界

|层次|实际身份|
|---|---|
|Git HEAD/main|`c1b65cf7bdabbdc825e94cd2330e3a91facf0c32`|
|开发工作区|同HEAD基础上含既有78个已追踪本地修改和多个未追踪模块；不是Windows干净副本|
|本轮开发Python|`/data/conda-envs/ai-basketball-analyst/bin/python`；3.11.15|
|正式固定运行副本|`/data/projects/ai-basketball-analyst/deploy/runtime/20261021-result-ui`|
|正式服务PID|`465726`；本轮前后不变|
|实际PYTHONPATH|`/data/projects/ai-basketball-analyst/deploy/runtime/20261021-result-ui/src`|
|运行标识|`20261021-result-ui`|
|记分牌自动融合|`AIHOOP_DISABLE_SCOREBOARD_FUSION=1`，禁用|
|服务接口|127.0.0.1:8018，健康检查200、ok=true|
|数据库|`data/jobs.sqlite`，只读检查191 done / 1 error；无queued/running|

启动命令：

```text
/data/conda-envs/ai-basketball-analyst/bin/python /data/conda-envs/ai-basketball-analyst/bin/uvicorn aihoop.api:app --host 127.0.0.1 --port 8018 --proxy-headers --forwarded-allow-ips 127.0.0.1 
```

快照manifest SHA：`9287791b7c52baf99523ad29d37d6bb3e429149f3de8beb8f912e48177252a5f`，逐文件核对无差异。本轮没有修改快照、systemd配置或进程环境；没有让运行副本自动跟随Git工作区。上述PYTHONPATH及启动契约确定预期导入路径，没有用ptrace注入运行进程。

## 模型身份

环境中的模型目录为`/data/projects/ai-basketball-analyst/models`，人员权重为`/data/projects/ai-basketball-analyst/models/yolov8n.pt`。按运行副本的文件选择逻辑，缺少runs/best.pt时当前球/筐选E-BARD/BODD；这只是当前可选择文件身份，不证明所有历史任务都用同一权重，也不等于从进程内存导出模型。

|文件|SHA256|实际类别|
|---|---|---|
|`/data/projects/ai-basketball-analyst/models/BODD_yolov8n_0001.pt`|`dfe3534d51bb21024d1a400c37f0c1fbf0c8b96ea9a56a5f3cb5454813bfd641`|basketball, hoop, player, referee|
|`/data/projects/ai-basketball-analyst/models/shottracker_before_best.pt`|`77afe98849989d079e73034f191906b619c47e17c12e9b1f4bea9e70989a71e3`|basketball, rim|
|`/data/projects/ai-basketball-analyst/models/shottracker_best.pt`|`b9d9c3d1c1db87b4788185cc422b67596e96a3058be843b494be02cfeebd4ba8`|basketball, rim|
|`/data/projects/ai-basketball-analyst/models/yolov8n.pt`|`f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36`|COCO 80类（含person）|

## 历史任务身份

最近3条真实视频任务的产物保留。其out_dir仍引用`deploy/runtime/20261016-152930/out/...`，该out是共享存储链接，不应将路径文字等同于精确的逐任务源码SHA。样本raw中没有单独的runtime_id或完整源码快照身份，不能凭当前HEAD追认所有旧任务。

已保存这3条任务raw/game文件SHA，审计末尾核对未变；没有更新任务、写回纠错或覆盖分析结果。数据库文件仅用只读连接查询，未复制账号或会话。

## 开关与审核

工作区`DEFAULT_CONFIG.score.make_window_from_crossing=false`，`ScoreEngine({},30)`也为false；正式固定副本也保留false。实验脚本会在离线B臂中显式设置true，但不影响生产配置。新增开口证据机制目前是设计/审核工具，不是已完成且默认启用的新命中算法。

穿越窗口历史实验出现新增假命中，人工穿筐审核尚未齐备；因此当前不具备启用条件。JSON保留UNKNOWN是证据状态，与网页只显示“中/没中”的展示约定不同；不能为界面文字修改历史结果。

## 与工作区不同的src文件

- `src/aihoop/rules.py`
- `src/aihoop/frame_motion.py`
- `src/aihoop/api.py`
- `src/aihoop/sources.py`
- `src/aihoop/auth.py`
- `src/aihoop/ball_recovery.py`
- `src/aihoop/pipeline.py`
- `src/aihoop/model.py`
- `src/aihoop/jersey_numbers.py`
- `src/aihoop/tactics.py`
- `src/aihoop/hoop.py`
- `src/aihoop/logo_scoreboard.py`
- `src/aihoop/marked_projection.py`
- `src/aihoop/legacy_shots/scorer.py`
- `src/aihoop/legacy_shots/ball_selection.py`
- `src/aihoop/legacy_shots/settings.py`
- `src/aihoop/legacy_shots/stream.py`

完整可公开的环境白名单与健康状态见`runtime_identity.json`；未保存内部令牌、密码或完整进程环境。
