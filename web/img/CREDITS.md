# web/img 图片来源与许可

这些图片**只用于界面装饰**（首页 hero 右半、整页淡背景纹理），不参与任何分析结果表达。
三张都是 **CC0 1.0（公有领域奉献）** —— 作者已放弃著作权，可自由使用、**无署名义务**；
下面仍如实记录来源，方便答辩时说明出处。

| 文件 | 原图标题 | 许可 | 作者 | 来源页 |
|---|---|---|---|---|
| `hero_court.jpg` | NBA basketball court parallel perspective top view | CC0 1.0 | Wikideas1 | https://commons.wikimedia.org/w/index.php?curid=155945076 |
| `bg_court.jpg` | Closeup red blue basketball court | CC0 1.0 | 未标注（rawpixel） | https://www.rawpixel.com/image/6040940/photo-image-public-domain-blue-lines |
| `hoop_dark.jpg` | Closeup outdoor basketball hoop | CC0 1.0 | 未标注（rawpixel） | https://www.rawpixel.com/image/6040868/photo-image-public-domain-free-sport |

## 处理方式

原图很大（3759×1886 ~ 5623×3739），用 `_tmp/build_web_images.py` 做了
**中心裁剪 + LANCZOS 缩放 + JPEG(progressive, quality 68~80)**：

| 文件 | 页面尺寸 | 用途 | 体积 |
|---|---|---|---|
| `hero_court.jpg` | 1920×880 | 首页 hero 右半（`url('./img/hero_court.jpg')`） | ~174 KB |
| `bg_court.jpg` | 1600×900 | 整页淡背景纹理（CSS 里 opacity .06 + blur） | ~115 KB |
| `hoop_dark.jpg` | 1200×800 | 备用（`.hoop-art` 类，暂时没挂到页面上） | ~120 KB |

## 想换图怎么办

候选池里有 **20 张 CC0** 图 + 一个可点的预览页：

- 预览页：`_tmp/img_candidates/预览.html`（直接双击用浏览器打开，每张图下面写着文件名）
- 清单：`_tmp/img_candidates/cc0.json`（含许可、作者、来源页、亮度/饱和度）

把喜欢的文件名告诉我，我替换掉 `web/img/` 下对应文件即可，**样式不用改**（CSS 只按文件名引用）。

## 抓取环境（复现用）

这台机器**没有外网直连**（DNS 是 fake-IP，出站被拦），但本机有代理：
`http://127.0.0.1:7890`。抓图脚本走这个代理访问
[Openverse API](https://api.openverse.org/v1/images/)（`license=cc0,pdm`）与 Wikimedia Commons API：

- `_tmp/fetch_cc0_images.py` —— 抓 CC0/公有领域候选 + 自动粗筛（标题避人物词、算亮度/饱和度）+ 生成预览页
- `_tmp/fetch_basketball_images.py` —— 抓 Wikimedia Commons（CC BY / CC BY-SA / CC0，带许可元数据）
- `_tmp/build_web_images.py` —— 裁剪/缩放成页面尺寸，并写出 `_tmp/img_candidates/used.json`

> 注意：Openverse 有速率限制，脚本里出现过 `429 Too many requests`；重跑前等一会儿或减少查询词。

## 2026-10-09 原創視覺
replay-editorial-v1.webp / tactics-editorial-v1.webp / replay-frames-v1.webp：內置 image_gen 生成，僅作裝飾；提示與用途見 docs/網頁視覺與字體優化_2026-10-09.md。

