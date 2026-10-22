# Git交接身份审计

审计时间：2026-10-21T21:35:24.023472+08:00（Asia/Shanghai）。项目：`/data/projects/ai-basketball-analyst`。证据目录：[out/server_git_handover_20261021_205145](out/server_git_handover_20261021_205145/)。本轮仅审计、隔离测试与报告输出；没有合并、变基、提交、推送、清理工作区或重启正式服务。

## 结论

- 目标远程：`https://github.com/rainyblue23/ai-basketball-analyst.git`，目标分支`main`。
- 当前分支`main`，服务器HEAD：`c1b65cf7bdabbdc825e94cd2330e3a91facf0c32`。
- 本轮`git fetch origin`及`git ls-remote --heads origin`确认远程`main`也是同一完整SHA。
- `HEAD...origin/main`为`0 / 0`，`merge-base --is-ancestor origin/main HEAD`退出0：预期Windows提交已经包含。
- 没有待处理的merge冲突，暂存区无差异。既有工作区不是干净的发布快照：78个已追踪文件仍有本地修改；本轮审计时另有129个未追踪文件条目。
- 因而“提交已同步”成立，“工作区逐字等于Windows工作区”不成立；后者不能仅靠HEAD相等宣称。
- 本轮没有再次merge/rebase/checkout/stash。上一轮已完成的快进同步及备份保留在`out/github_sync_20261021_200259/`，不重复操作。

## 最新提交及文件

`c1b65cf`新增穿筐证据审核/离线实验/标注导入、三视频记录和报告；没有修改`src/`正式投篮引擎。提交共32个文件，5322行新增、4行删除。`docs/CROSSING_EVIDENCE_DESIGN_20261020.md`明确PENDING_VALIDATION，没有新增可默认启用的命中规则。

```text
c1b65cf7bdabbdc825e94cd2330e3a91facf0c32 2026-10-21 14:29:45 +0800 上传本地工作区：穿筐证据分析/标注导入 + 三视频出手记录
56b9317d8cc561199786811069d54c40d2e47da5 2026-10-13 20:40:10 +0800 Fix A/B court calibration previews and shot heatmap geometry
0db9280a844b1963f47583d781837e3de6cc0bfd 2026-10-12 20:29:44 +0800 Merge remote-tracking branch 'origin/main' into fix-court-overlay
bab1b26f1aaaaf2db29895d365680683966edb5a 2026-10-12 19:46:22 +0800 ﻿球轨迹顺序 bug：没有静态标定时球轨迹恒为空
a8e7fac99407b3aa31e4f4f213910e1a0f99b64a 2026-10-11 21:23:43 +0800 Normalize published snapshot integrity across platforms
ca7c29c0ab5aa9c1c64f6f3ee72115e5cd7c73a5 2026-10-11 21:22:49 +0800 Publish reviewed Lillard and Harden demonstration samples
```

原始提交图、show摘要、reflog、暂存区检查、祖先关系见[out/server_git_handover_20261021_205145/git_identity.json](out/server_git_handover_20261021_205145/git_identity.json)。本轮没有观察到本地与远程分叉或fetch强制更新；没有完整远程历史审计记录，不能保证远程在所有历史时刻都未被重写。

## 本地修改边界

下列文件是审计开始时的既有修改，未清除、未覆盖：

```text
.env.example
.gitignore
DEPLOYMENT.md
README.md
SERVER_HANDOFF.md
docker-compose.yml
eval/ball_feedback_validation.md
requirements-full.txt
requirements-jersey.txt
scripts/check_server.py
scripts/prepare_jersey_ocr.py
scripts/read_marked_scoreboard.py
scripts/serve_match_labeling.py
scripts/train_ball_correction_pilot.py
src/aihoop/api.py
src/aihoop/auth.py
src/aihoop/ball_feedback.py
src/aihoop/ball_recovery.py
src/aihoop/calibcheck.py
src/aihoop/court.py
src/aihoop/footage.py
src/aihoop/frame_motion.py
src/aihoop/hoop.py
src/aihoop/jersey_numbers.py
src/aihoop/legacy_shots/adapter.py
src/aihoop/legacy_shots/ball_selection.py
src/aihoop/legacy_shots/detector.py
src/aihoop/legacy_shots/scorer.py
src/aihoop/legacy_shots/settings.py
src/aihoop/legacy_shots/stream.py
src/aihoop/model.py
src/aihoop/multical.py
src/aihoop/pipeline.py
src/aihoop/replay_overlay.py
src/aihoop/rules.py
src/aihoop/sources.py
src/aihoop/tactics.py
tests/test_api.py
tests/test_ball_feedback.py
tests/test_ball_static_lock.py
tests/test_calib_side_picker.js
tests/test_calibrate_multi_endpoint.py
tests/test_calibrate_write_acceptance.py
tests/test_court_marked_frame_preview.py
tests/test_external_report.py
tests/test_feedback_integration.py
tests/test_graphics_jersey.py
tests/test_overlay_per_panel.js
tests/test_replay_overlay.py
tests/test_review_suggestions.js
tests/test_shot_auth.py
tests/test_shot_center_hint.py
tests/test_shot_legacy_engine.py
tests/test_shot_night_settings.py
tests/test_ui_home.js
tests/test_unknown_style.js
tests/test_upload_payload.js
web/api.js
web/app.js
web/ball-feedback.js
web/components.js
web/court.js
web/data.js
web/detection-overlay.js
web/index.html
web/match-labeling.html
web/my.html
web/pages/examples.js
web/pages/highlights.js
web/pages/home.js
web/pages/overview.js
web/pages/report.js
web/pages/review.js
web/pages/shotchart.js
web/pages/stats.js
web/pages/tactics.js
web/pages/upload.js
web/register.html
```

未追踪文件的完整路径见`git_identity.json`的`untracked`。重点包括`docs/audits/`、`deploy/`、实验/回溯模块、评估脚本、浏览器测试、`eval/identity_reviews/`及标定备份。不能仅将HEAD打包作为这些本地工作的备份。

完整差异统计见[diff_summary.txt](out/server_git_handover_20261021_205145/diff_summary.txt)。本轮新增`scripts/audit_server_handover.py`是只读采集工具，不改变模型、状态机或生产配置；另生成本报告及3份配套报告。测试前源码身份见[source_manifest.before.json](out/server_git_handover_20261021_205145/source_manifest.before.json)，安全复核见[safety_verification.json](out/server_git_handover_20261021_205145/safety_verification.json)。

## LFS、子模块与忽略项

- Git LFS命令未安装；仓库属性未发现`filter=lfs`，两个关键资源的filter为unspecified，HEAD未找到LFS pointer。不能把未安装LFS误报为权重已经下载。
- `.gitmodules`不存在，`git submodule status`为空。
- `.gitignore`排除`*.pt/*.pth/*.onnx`、模型目录、上传视频、`out/`、运行数据库、OCR模型及多类本机资源；另外部分服务器报告/脚本本身未追踪。
- 本轮未安装LFS、未初始化子模块、未下载或迁移资源。各资源实际追踪与忽略规则见[SERVER_RESOURCE_AUDIT.md](SERVER_RESOURCE_AUDIT.md)。
