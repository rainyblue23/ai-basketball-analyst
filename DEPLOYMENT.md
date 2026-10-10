# 服务器部署

仓库只包含应用源码、网页、测试和必要配置。视频、分析产物、账号、会话以及模型权重不会进入 Git。

## Docker 启动

```bash
cp .env.example .env
# 编辑 .env：设置长随机注册码、正式域名；HTTPS 部署保留 AIHOOP_COOKIE_SECURE=1
mkdir -p data out models
docker compose up -d --build
```

打开 `http://服务器地址:8000/web/register.html` 注册首个账号。正式公网部署应使用 HTTPS 反向代理，并只暴露代理端口。

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
