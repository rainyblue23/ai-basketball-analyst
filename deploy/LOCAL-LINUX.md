# 本机服务（这台 Linux 电脑）

项目：`/data/projects/ai-basketball-analyst`  
Conda：`/data/conda-envs/ai-basketball-analyst`  
本机入口：`http://127.0.0.1:8018/web/login.html`

服务使用 `deploy/ai-basketball-analyst.service`，只监听回环地址。`data/` 保存上传、账号与任务数据库，`out/` 保存分析结果，`models/` 存放模型，临时文件与框架缓存使用 `/data/aihoop-cache/`；这些目录均在 `/data` 磁盘。运行配置保存在不入库的 `.env`，请勿公开。

```bash
systemctl --user status ai-basketball-analyst.service
journalctl --user -u ai-basketball-analyst.service -n 100 --no-pager
```

首次使用可在 `/web/register.html` 直接创建账号，无需注册码；公开注册每个来源地址每小时最多尝试 10 次。公网域名由 Cloudflare Tunnel 指向 `http://127.0.0.1:8018`，同时在 `.env` 设置 `AIHOOP_ALLOWED_ORIGINS=https://basketparts.top` 与 `AIHOOP_COOKIE_SECURE=1`。本机 HTTP 登录保留可用，公网 Cookie 使用 Secure 属性。

## 公网速度

2026-10-10 从本机测得注册页本地响应约 2 毫秒，经 `basketparts.top` 约 1.15 秒；这只代表本机到 Cloudflare 再回本机的路径，不等同于其他地区用户的速度。当前 Tunnel 使用 HTTP/2，并连接到 `lax01/lax05`；静态图片在 Cloudflare 为 `HIT`，HTML 为 `DYNAMIC`。注册页已去掉额外的配置请求，登录与注册页允许浏览器私有缓存 60 秒。若要进一步缩短首次打开 HTML 的跨境等待，需要在 Cloudflare 侧仅针对公开的登录、注册页配置缓存；不要缓存 `/api/`、用户页面、视频或分析结果。

合成数据演示可直接运行。真实视频分析使用 `.env` 的 `AIHOOP_PLAYER_WEIGHTS` 选择球员模型；如有自备球与篮筐模型，可放在 `models/ball.pt`、`models/rim.pt`，或用双类 `models/rim_ball_v6.pt`。还需要合适的视频及针对该视频的篮筐和球场标定。通用 YOLO 人员模型不足以保证自动判分准确。

当前还备有第三方篮球检测模型 `models/BODD_yolov8n_0001.pt`（E-BARD，球/篮筐/球员/裁判四类；来源和校验值见 `deploy/ASSETS.md`）。程序在没有自训练球/篮筐权重时自动选它。它在 NBA 转播画面的检测表现不等于本项目的进球判定准确率；仍需对每段视频检查球与篮筐覆盖、机位和标定。

可选的球衣号码 OCR 已安装 EasyOCR 1.7.2，并在 `/data/projects/aihoop_assets/models/easyocr/` 放好两个模型文件。运行时只读取本地模型，不自动下载。重新搭建 Conda 环境时执行 `python -m pip install easyocr==1.7.2`，再运行 `python scripts/prepare_jersey_ocr.py --model-dir /data/projects/aihoop_assets/models/easyocr`。

Ubuntu 上的比分牌 OCR 也使用这两个本地 EasyOCR 模型；Windows 继续使用系统 OCR。自动定位需要画面里能稳定读到双方队名与比分。对于只有队徽和数字的台标，需在页面框选**只包含两个比分数字**的区域，或用 `scripts/read_marked_scoreboard.py --box-home x0,y0,x1,y1 --box-away x0,y0,x1,y1` 分别框选。OCR 读数仍会经过比分递增和单次最多 3 分的检查；剪辑视频跳过多次得分时，不能把被拒绝的跳变当作 OCR 故障。运行 `scripts/check_server.py` 可验证 Linux OCR 模型是否离线加载。自定义模型目录可设 `AIHOOP_SCOREBOARD_OCR_MODELS`。对于本机 OpenCV 无法解码的 AV1 上传，比分牌 OCR 会用 ffmpeg 临时转成 H.264 取帧；完整视频分析在启动时也会将可解码的 H.264 副本缓存到 `data/compatible/`。原上传文件保留，缓存文件不进入 Git。

2026-10-10 本机验证：`data/uploads/` 的杨瀚森、利拉德、哈登 3 段 AV1 均已生成 H.264 缓存，OpenCV 分别能读取首帧，帧数为 2726、5314、10209。用杨瀚森上传视频裁出的 8 秒 AV1 片段跑完整后端，任务完成并生成 9 个文件；该片段结果为 0:0、0 条出手，仅证明解码和分析链路可运行，不证明自动判分正确。收到的 3 份现成解析快照已在隔离测试中通过样例目录、报告和原视频读取接口，尚未加入线上样例库。
