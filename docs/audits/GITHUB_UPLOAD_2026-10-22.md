# 服务器开发工作区 GitHub 上传交接

日期：2026-10-22（Asia/Shanghai）。用户要求暂停功能开发，将当前内容上传 GitHub。

## 范围与身份

- 仓库：`https://github.com/rainyblue23/ai-basketball-analyst.git`，分支：`main`。
- 上传前 HEAD 和 fetch 后的 `origin/main` 均为 `c1b65cf7bdabbdc825e94cd2330e3a91facf0c32`，左右差异为 0/0。无需合并或变基。
- 提交包含此前积累的后端、前端、离线实验、测试、部署模板、诊断文档，以及小体积人工身份审核 JSON。此文档所在提交即本次源码快照。
- 现有开发成果合计 201 个文件、2,626,223 字节；加上本交接文档后共 202 个文件。字节数按暂存文件全文统计，不是网络压缩上传量。
- 本次新增忽略规则：兼容预览视频缓存、标定备份、服务器固定运行快照。没有清理这些本地文件。
- 未设置全局 Git 用户；提交使用命令级 `Codex <codex@openai.com>` 身份，区分服务器代提交与用户本人提交。

## 验证

- 对变更及新增源码进行语法检查：110 个 Python 文件、40 个 JavaScript/MJS 文件，通过。
- 定向回归：95 passed，7 warnings，耗时 1.06 秒。警告来自 Pydantic、FastAPI、Starlette 已弃用接口。
- 首轮只设置 `PYTHONPATH=src` 时有 1 项测试因无法导入脚本模块失败；按项目工具路径使用 `PYTHONPATH=src:scripts` 后，全部 95 项通过，未修改断言或算法来通过测试。
- 对暂存内容检查了文件类型、大小及常见私钥/访问令牌格式，没有发现需要排除的内容。此检查不等于全面安全审计。
- 暂存空白检查提示 3 处既有文档行末空格，其中 2 处用于 Markdown 换行；未据此修改既有文档。
- 没有重新执行全量验收或 GPU 准确率评估；已有报告记录的失败、待审核项和限制继续有效。

测试命令：

```bash
cd /data/projects/ai-basketball-analyst
PYTHONPATH=src:scripts /data/conda-envs/ai-basketball-analyst/bin/python -m pytest -q \
  tests/test_runtime_contract.py tests/test_made_shooter_recovery.py \
  tests/test_marked_projection.py tests/test_marked_registration_recovery.py \
  tests/test_score_guided_recovery.py tests/test_release_shadow.py \
  tests/test_tactics_roster_evidence.py tests/test_tactics_partial_spacing.py \
  tests/test_examples.py tests/test_upload_chunks.py tests/test_cv_low_risk_fixes.py
```

## 上传与运行的边界

- 本次只提交、推送，不部署、不重启、不修改正式任务结果，不启用实验记分牌融合或命中算法。
- 当前开发工作区与正式固定运行副本不同；拉取本提交不等于已经发布这些功能。
- 样例热区和战术修复按用户要求暂停，尚未完成，不应在其他机器上据此宣称已修复。
- `docs/audits/` 随本次上传，但文档引用的 `out/` 视频、截图、ZIP、逐帧证据大多仍只在服务器，需要单独迁移。
- 模型权重、原始/转码视频、OCR 模型、账号/任务数据库、`.env`、服务器运行副本仍不入库。已有 Git 跟踪的样例媒体保持原样，本次没有新增媒体。
- 本地标定、审核图片和未入库标注也需要按 SHA 与来源另行迁移。小体积身份审核 JSON 入库不代表相关图片已经入库，更不代表获准训练。

上传前本地差异与文件身份备份：`out/github_publish_20261022_170920/`。它不随 Git 提交；GitHub 是否上传成功应以推送后远程分支 SHA 核对为准。
