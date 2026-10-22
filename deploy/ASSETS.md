# 本机篮球素材与模型

GitHub 仓库没有提交比赛视频或专用检测权重，也没有 Release 附件。以下文件从文档或脚本指向的外部来源取得，放在 `/data/projects/ai-basketball-analyst` 内，均由 `.gitignore` 排除，不随源码发布。

| 本机文件 | 来源 | 大小 | SHA-256 |
| --- | --- | ---: | --- |
| `models/BODD_yolov8n_0001.pt` | [E-BARD 模型页](https://huggingface.co/GabrieleGiudici/E-BARD-detection-models)；模型页标注 CC-BY-4.0 | 6,151,282 B | `dfe3534d51bb21024d1a400c37f0c1fbf0c8b96ea9a56a5f3cb5454813bfd641` |
| `data/samples/bili/BV1e8HS6HEv4.mp4` | [杨瀚森比赛片段](https://www.bilibili.com/video/BV1e8HS6HEv4/)；仓库 `scripts/prepare_examples.py` 引用 | 21,976,122 B | `90aee93937fab0a780ce4567b9a7cbf317e35a192f9822d0fd2f304fe0a3a661` |
| `data/samples/bili/BV165YQ68E3C.mp4` | [利拉德比赛片段](https://www.bilibili.com/video/BV165YQ68E3C/)；同上 | 42,547,362 B | `9f1674331f185f7ad661f4f345b904a579a163eb1b10931e3484ab41d8b7844b` |
| `data/samples/bili/BV1sHYN6uEGd.mp4` | [哈登比赛片段](https://www.bilibili.com/video/BV1sHYN6uEGd/)；同上 | 83,113,229 B | `c853b9a3690691362710e3eabc47fd292cf7c4127b40fc490c4538a15cf7b7e2` |
| `data/samples/archive/unified_basketball_home_game.mp4` | [Archive.org 校园篮球短片](https://archive.org/details/marshtvmav-MCN_MHS_s_First_Unified_Basketball_Home_Game)；仓库 `tools_fetch_sample_video.py` 引用 | 9,291,026 B | `abed08af61c53b3c9b9a9d50c14bdf03e51bb1e29ba9da2914f0fd237f81d0d4` |
| `models/shottracker_best.pt` | [ShotTracker best.pt](https://github.com/AggieSportsAnalytics/ShotTracker/blob/main/best.pt) | 6,218,094 B | `b9d9c3d1c1db87b4788185cc422b67596e96a3058be843b494be02cfeebd4ba8` |
| `models/shottracker_before_best.pt` | [ShotTracker BeforeBest.pt](https://github.com/AggieSportsAnalytics/ShotTracker/blob/main/BeforeBest.pt) | 6,218,094 B | `77afe98849989d079e73034f191906b619c47e17c12e9b1f4bea9e70989a71e3` |
| `data/samples/shottracker/DairyCourts.MOV` | [ShotTracker 固定机位视频](https://github.com/AggieSportsAnalytics/ShotTracker/blob/main/DairyCourts.MOV) | 5,373,993 B | `0e8d6f2b5537583ad041ab0c6d4533edf536ae409ac8e860b545a2f92caca303` |
| `data/samples/shottracker/NathanBBall.mov` | [ShotTracker 投篮视频](https://github.com/AggieSportsAnalytics/ShotTracker/blob/main/NathanBBall.mov) | 8,890,181 B | `eee09238955cd0dbe34846b5428dda1bb418e788ca40ac6c3c44f1f0f0d720a2` |

三个 B 站视频时长依次约 91、177、341 秒。Archive.org 短片为 480p、约 97 秒。2026-10-11 按项目方要求，三段 B 站视频连同一段用户上传的室外定点投篮视频加入网站只读样例库；Archive.org 和 ShotTracker 素材仍只用于本机验证。

E-BARD 权重包含 `basketball`、`hoop`、`player`、`referee` 四类，程序在没有自训练球/筐权重时会选它。已对下载文件核对大小、SHA-256、PyTorch ZIP 内容及 Ultralytics 类别，并在四段视频上运行检测。24 帧抽样的检球覆盖分别为：杨瀚森 13/24、利拉德 11/24、哈登 6/24、Archive 校园短片 3/24；这只是检出帧比例，不是准确率。利拉德 8 秒与 30 秒片段的完整后端分析任务均完成并确认加载此权重，但在未标定、剪辑多机位的条件下输出 0 次出手、0:0，不能视为自动判分验证通过。球场标定、素材机位和进球真值还需分别复核。

ShotTracker 两份权重分别包含 `basketball`、`rim` 两类，校验后可由 Ultralytics 加载。其两个视频分别为 27.93 秒 1920×1080 和 26.90 秒 852×480。12 帧抽样检球覆盖：DairyCourts 上 E-BARD 4/12、ShotTracker best 11/12、BeforeBest 10/12；NathanBBall 上依次为 9/12、12/12、12/12。它们仅作本机候选，未切换线上默认模型；抽样检出并不能证明判分正确。ShotTracker 仓库未见明确再分发许可，因此视频与模型不加入公开样例库。`DairyCourts.MOV` 与 README 记载的 `sample_dairy.mov` 分辨率、时长接近，但尚未核实为同一剪辑，不创建同名替身。第三方训练数据集及 `output.mp4` 演示输出不是服务运行所需，未下载。

球衣号 OCR 所需的 EasyOCR 1.7.2 已装入本项目 Conda 环境；两个模型保存在 `/data/projects/aihoop_assets/models/easyocr/`，由仓库 `scripts/prepare_jersey_ocr.py` 下载。`craft_mlt_25k.pth` 为 80 MB、SHA-256 `4a5efbfb48b4081100544e75e1e2b57f8de3d84f213004b14b85fd4b3748db17`；`english_g2.pth` 为 15 MB、SHA-256 `e2272681d9d67a04e2dff396b6e95077bc19001f8f6d3593c307b9852e1c29e8`。已用 `download_enabled=False` 加载验证；球衣号识别准确率尚未验证。

## 2026-10-10 收到的视频与分析快照

本机收到的三段长视频和一段室外投篮视频保存在 `data/uploads/`。Git 提交 `a8e7fac` 已自带利拉德、哈登的便携视频、人工复核分析和49个逐球片段，应用直接从 `examples/catalog.json` 与 `examples/{lillard,harden}/` 读取，不再由本机旧清单覆盖。杨瀚森和室外视频仍由 `data/example_gallery.json` 指向 `out/examples/{yang,outdoor-shooting}/`。四条样例均通过 `/api/examples`、预览图和 `example_*` 视频接口提供给已登录用户。

| 视频 | 大小 | SHA-256 |
| --- | ---: | --- |
| `data/uploads/yang-retry2_8828aea2e1.mp4` | 21,072,317 B | `5d2ca919876500857b6619685879badbe5373c33579884341a8c0bb092365888` |
| `data/uploads/lillard-buzzer-beater-BV165YQ68E3C_9e1bbd21c5.mp4` | 52,310,977 B | `d8b5b37c3d5f88417e1a00bf44533dd06b659e56a30130f1839e69d1334906e6` |
| `data/uploads/harden-58pts-BV1sHYN6uEGd_1383973ee3.mp4` | 89,878,389 B | `4fb57d794b66f136ae1f061ab0b7e958432e39fae673be618c14b13e1cbb4b92` |
| `data/uploads/babc7ddb968531af7ed3f89df8e43678_4032d2ab0f.mp4` | 4,732,261 B | `8485feb7fdbabbe1b4066b8c6216d8b2425903fe9d0d77afd579f4235c9c7a32` |

利拉德新版人工复核为运动战14投9中、罚球1投0中，含2条重复回放；哈登为运动战34投31中。它们是人工复核演示结果，不代表自动检测准确率。室外视频改用专用球/筐权重后自动篮筐覆盖为703/704帧，识别7次出手，其中3次确认命中、4次证据不足保持未知；没有比分牌，球队与位置也未确认，因此不编比分或热区。
