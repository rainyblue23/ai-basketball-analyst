# 服务器部署

仓库只包含应用源码、网页、测试和必要配置。视频、分析产物、账号、会话以及模型权重不会进入 Git。

这台 Linux 电脑使用 Conda 和用户级 systemd 服务；启动方式及本机地址见 [deploy/LOCAL-LINUX.md](deploy/LOCAL-LINUX.md)。

## Docker 启动

```bash
cp .env.example .env
# 编辑 .env：设置正式域名；HTTPS 部署保留 AIHOOP_COOKIE_SECURE=1
mkdir -p data out models
docker compose up -d --build
```

打开 `http://服务器地址:8000/web/register.html` 注册账号，无需注册码。公开注册每个来源地址每小时最多尝试 10 次。正式公网部署应使用 HTTPS 反向代理，并只暴露代理端口。

## 模型

真视频分析需要自行取得或训练合法可用的模型文件，放到服务器的 `models/`。程序通过 `AIHOOP_MODELS=/app/models` 读取该目录。仓库不再分发来源或许可不明确的权重。

仅启动网页、登录、合成演示不要求模型权重。真视频推理还需要足够的 CPU/GPU 与磁盘空间。

## 持久化与备份

- `data/`：上传视频、用户账号、会话、任务库、标定。
- `out/`：分析结果、报告和回放片段。
- `models/`：本机提供的模型，只读挂载进容器。

升级代码前备份 `data/`；`out/` 可重建，但若包含人工复核结果也应备份。

## 上线检查

```bash
docker compose ps
curl http://127.0.0.1:8000/api/health
docker compose logs --tail=200 api
```

健康接口应返回 `ok: true`。上传真视频前，确认健康信息里的 ffmpeg、OpenCV、Ultralytics 均可用，并在网页中完成篮筐或球场标定。

## 更新

```bash
git pull --ff-only
docker compose up -d --build
```

不要把 `.env`、`data/`、`out/`、`models/` 提交到 GitHub。

### 本机Ubuntu用户服务（2026-10-16补记）

本机systemd用户服务已固定到`deploy/runtime/20261016-152930`的代码快照，使用`70-pinned-runtime.conf`覆盖PYTHONPATH并在ExecStartPre检查事件数据类型契约。开发工作区与在线导入路径已经隔离；git更新工作区不等于更新该服务。快照只复制src/scripts/web，数据和模型仍位于原项目。

构建下一版本时先运行新快照内的`check_runtime_contract.py`，确认没有在跑的分析，再切换快照并重启。保留`AIHOOP_DISABLE_SCOREBOARD_FUSION=1`，直到暂停中的记分牌任务单独验收。参见`docs/audits/CV_RUNTIME_FIX_2026-10-16.md`。
