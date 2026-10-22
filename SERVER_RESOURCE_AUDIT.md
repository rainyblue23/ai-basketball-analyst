# 服务器资源与迁移审计

审计时间：2026-10-21T21:35:24.023472+08:00（Asia/Shanghai）。项目：`/data/projects/ai-basketball-analyst`。证据目录：[out/server_git_handover_20261021_205145](out/server_git_handover_20261021_205145/)。本轮仅审计、隔离测试与报告输出；没有合并、变基、提交、推送、清理工作区或重启正式服务。

## 需要单独迁移的资源

1. **冻结31条基线原视频**：fixedcam、game01、game03，3个预期SHA在服务器现有`data/uploads`、`data/samples`和`/data/projects/aihoop_assets/samples`均未匹配。不得用名字相似的视频代替。
2. **Windows活动两分类权重**：预期SHA `800dab7c265b4cf9e488f75eb293f659f34a6efa86300c4823563887329072d9`，Windows报告将ball/rim两个best.pt记为同一文件。服务器当前没有该权重；已有ShotTracker备用`b9d9…`不是相同版本。建议迁入单独评估模型目录并显式引用，避免放入生产自动优先选择目录而意外切换默认模型。
3. **Windows评估和审核产物**：`out/stage2_audit_20261020/`、`out/crossing_window_20261020/`、`out/crossing_evidence_20261020/`。需要results、raw_track、A/B状态、逐事件FP/FN、review/tasks、原画/证据片段与人工导出JSON。Git未包含它们，当前不能核验Windows报告的全部逐事件证据。
4. **若人工穿筐审核仅存浏览器localStorage**，须从原电脑导出JSON。Git不会携带浏览器草稿；不得默认标记为审核完成。
5. 4段旧测试集原始字节与对应图像若需历史复核，也需按原SHA迁移；它们已用于训练/验证且来源存在问题，迁移后仍不能变为独立测试集。

## 已存在，不必重复迁移

- 杨瀚森、利拉德、哈登三段上传原片均存在且与新标注的`source_sha256`完全一致，见下表。
- COCO yolov8n、E-BARD/BODD四分类和两个ShotTracker备用权重存在，均已加载核对类别；不是Windows活动权重的替代品。
- EasyOCR两文件存在于`/data/projects/aihoop_assets/models/easyocr`，SHA与本机`source.json`一致。未跑OCR识别质量验收，不等于记分牌效果已验证。
- 人工TXT、规范化59条JSON、人工分值确认、31条标注和旧冻结结果均已在Git中。部分字节SHA受跨平台换行影响，见后文，禁止改写预期SHA掩盖差异。
- 正式数据库、历史分析产物仍在原存储；无需从Windows覆盖账号、数据库、模型配置或`.env`。

## 视频身份与时间基准

|清单/样本|条目|唯一play|预期视频SHA256|服务器匹配|审核/用途|
|---|---:|---:|---|---|---|
|s2_fixedcam_7shots|7|7|`db902e59bb8eb3792b8ad80357369e128be953db96a41970f137cbef7c73fe14`|未匹配|历史开发/隔离资料|
|s2_hs_game01|14|14|`8b5c360f690bad0cae2cde1c6fabd4f702b3a0388dfba8ff823052a7b4921c3b`|未匹配|历史开发/隔离资料|
|s2_hs_game03|10|10|`b5c037bc61e37b9e692a48f9333954ded229c52dcb0513f99468d276c60f1900`|未匹配|Validation_exposed|
|match_01|3|3|`9424a5d359139964a715085a367cbeaafdcaaa56e09ef1de55255f607a8767fe`|未匹配|历史开发/隔离资料|
|match_02|0|0|`73e033565c47418e1c0ab42f23f3b02be16d6c68a4e096d4aab1d9dfe89b91ca`|未匹配|历史开发/隔离资料|
|match_03|0|0|`d52ccc42357d41bd937479ac936211b91e1c63ccd12c43cfcfd0cf093d9b580a`|未匹配|历史开发/隔离资料|
|match_04|1|1|`be2881366e31bcd38e2205f6e8c09ddb8586f6f5967dd8f2cad4f234ec465e58`|未匹配|历史开发/隔离资料|
|yang|10|10|`5d2ca919876500857b6619685879badbe5373c33579884341a8c0bb092365888`|匹配|Development|
|lillard|15|13|`d8b5b37c3d5f88417e1a00bf44533dd06b659e56a30130f1839e69d1334906e6`|匹配|Development|
|harden|34|34|`4fb57d794b66f136ae1f061ab0b7e958432e39fae673be618c14b13e1cbb4b92`|匹配|Development|

三段Bili合计59次画面出现、57个play_id，不是59个新独立样本。时间是所提供视频内近似离手秒；整场时间偏移仍UNKNOWN。完整性来自用户文件声明，未独立逐帧复核。harden_14仍有precise_release_pending。三段全部Development，Validation与Independent Test新增数量均为0。

按真实SHA生成了独立Linux路径索引`local_annotation_paths.json`；原始JSON中的D盘路径没有改写，不将其应用到正式环境。这个索引仅供后续离线评估使用，不作为推理标签输入。

## 跨平台字节身份问题

- `eval/ground_truth/shots_split2_20261011.json`：当前SHA `bd4c272c433e77c952d212f527b43f0d06b4001e5ace7b41dbf6da0194cc5da5`，Windows记录 `0e8e2e4be0c6a6c1f9d2e8ce1184cd447e210df950013d38f3ecea9821937e82`。只在内存将LF展开为CRLF，能重现Windows预期SHA；未改写文件。
- `eval/annotation_imports/three_bili_20261020/三个视频出手记录.txt`：当前SHA `0d2185a015bd96c94ab068d3c2c6b7b4a3aefbad793a68964f3808b793bd9d7d`，Windows记录 `1c84423a222c7cd9c33b5946d6aef232454ee339259eb53b8b72ab01f7dfd358`。只在内存将LF展开为CRLF，能重现Windows预期SHA；未改写文件。

`.gitattributes`明确文本文件使用LF。现有`summarize_frozen_baseline.py`仍按原始字节核验，当前调用会拒绝truth hash mismatch；这是必须记录的身份边界。应保留原SHA、Git blob身份与序列化映射，后续建立显式跨平台验证方案，不能简单改预期SHA后声称复现通过。

## 全部逐项清单

SHA适用于静态文件；活跃数据库不以单次文件SHA代表一致快照，另用只读SQLite查询。下表资源无LFS过滤配置。外部资源的原始获取来源不能从文件名推断，已知OCR来源见其source.json；模型角色已由实际加载的类别确认。

|实际路径|存在|SHA256|Git追踪|忽略规则|用途/缺失影响|
|---|---|---|---|---|---|
|`/data/projects/ai-basketball-analyst/models/yolov8n.pt`|是|`f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36`|否|.gitignore:113:models/	models/yolov8n.pt|model；role-specific inference / exact historical reproduction|
|`/data/projects/ai-basketball-analyst/models/BODD_yolov8n_0001.pt`|是|`dfe3534d51bb21024d1a400c37f0c1fbf0c8b96ea9a56a5f3cb5454813bfd641`|否|.gitignore:113:models/	models/BODD_yolov8n_0001.pt|model；role-specific inference / exact historical reproduction|
|`/data/projects/ai-basketball-analyst/models/shottracker_best.pt`|是|`b9d9c3d1c1db87b4788185cc422b67596e96a3058be843b494be02cfeebd4ba8`|否|.gitignore:113:models/	models/shottracker_best.pt|model；role-specific inference / exact historical reproduction|
|`/data/projects/ai-basketball-analyst/models/shottracker_before_best.pt`|是|`77afe98849989d079e73034f191906b619c47e17c12e9b1f4bea9e70989a71e3`|否|.gitignore:113:models/	models/shottracker_before_best.pt|model；role-specific inference / exact historical reproduction|
|`/data/projects/ai-basketball-analyst/runs/detect/ball/weights/best.pt`|否|`—`|否|.gitignore:111:runs/	runs/detect/ball/weights/best.pt|model；role-specific inference / exact historical reproduction|
|`/data/projects/ai-basketball-analyst/runs/detect/rim/weights/best.pt`|否|`—`|否|.gitignore:111:runs/	runs/detect/rim/weights/best.pt|model；role-specific inference / exact historical reproduction|
|`/data/projects/ai-basketball-analyst/models/rim_ball_v6.pt`|否|`—`|否|.gitignore:113:models/	models/rim_ball_v6.pt|model；role-specific inference / exact historical reproduction|
|`/data/projects/ai-basketball-analyst/models/rim_ball.pt`|否|`—`|否|.gitignore:113:models/	models/rim_ball.pt|model；role-specific inference / exact historical reproduction|
|`/data/projects/aihoop_assets/models/easyocr/craft_mlt_25k.pth`|是|`4a5efbfb48b4081100544e75e1e2b57f8de3d84f213004b14b85fd4b3748db17`|否|outside repository|OCR；offline EasyOCR|
|`/data/projects/aihoop_assets/models/easyocr/english_g2.pth`|是|`e2272681d9d67a04e2dff396b6e95077bc19001f8f6d3593c307b9852e1c29e8`|否|outside repository|OCR；offline EasyOCR|
|`/data/projects/aihoop_assets/models/easyocr/source.json`|是|`4f5384daf83d351d0ec45ff25eaf7fe26aa2c12fc189f978b8d58fbfdd294ced`|否|outside repository|OCR；offline EasyOCR|
|`/data/projects/ai-basketball-analyst/data/samples/archive/unified_basketball_home_game.mp4`|是|`abed08af61c53b3c9b9a9d50c14bdf03e51bb1e29ba9da2914f0fd237f81d0d4`|否|.gitignore:29:data/samples/	data/samples/archive/unified_basketball_home_game.mp4|video；matching evaluation or analysis|
|`/data/projects/ai-basketball-analyst/data/samples/bili/BV165YQ68E3C.mp4`|是|`9f1674331f185f7ad661f4f345b904a579a163eb1b10931e3484ab41d8b7844b`|否|.gitignore:29:data/samples/	data/samples/bili/BV165YQ68E3C.mp4|video；matching evaluation or analysis|
|`/data/projects/ai-basketball-analyst/data/samples/bili/BV1e8HS6HEv4.mp4`|是|`90aee93937fab0a780ce4567b9a7cbf317e35a192f9822d0fd2f304fe0a3a661`|否|.gitignore:29:data/samples/	data/samples/bili/BV1e8HS6HEv4.mp4|video；matching evaluation or analysis|
|`/data/projects/ai-basketball-analyst/data/samples/bili/BV1sHYN6uEGd.mp4`|是|`c853b9a3690691362710e3eabc47fd292cf7c4127b40fc490c4538a15cf7b7e2`|否|.gitignore:29:data/samples/	data/samples/bili/BV1sHYN6uEGd.mp4|video；matching evaluation or analysis|
|`/data/projects/ai-basketball-analyst/data/samples/shottracker/DairyCourts.MOV`|是|`0e8d6f2b5537583ad041ab0c6d4533edf536ae409ac8e860b545a2f92caca303`|否|.gitignore:29:data/samples/	data/samples/shottracker/DairyCourts.MOV|video；matching evaluation or analysis|
|`/data/projects/ai-basketball-analyst/data/samples/shottracker/NathanBBall.mov`|是|`eee09238955cd0dbe34846b5428dda1bb418e788ca40ac6c3c44f1f0f0d720a2`|否|.gitignore:29:data/samples/	data/samples/shottracker/NathanBBall.mov|video；matching evaluation or analysis|
|`/data/projects/ai-basketball-analyst/data/samples/validation_lillard_30s.mp4`|是|`cf6c1a647900e38f581e6cec2fe6ba8f6b3f7b0d0131db38296b684c29834352`|否|.gitignore:29:data/samples/	data/samples/validation_lillard_30s.mp4|video；matching evaluation or analysis|
|`/data/projects/ai-basketball-analyst/data/samples/validation_lillard_8s.mp4`|是|`03872085a0577a6c3a695d6828275039f13d485c63f6bb4146360344f2d2e4b8`|否|.gitignore:29:data/samples/	data/samples/validation_lillard_8s.mp4|video；matching evaluation or analysis|
|`/data/projects/ai-basketball-analyst/data/uploads/8558f0fcb272159c3af1fea72eedd2bb_f0fc352798.mp4`|是|`2b8cc6a3f230383b08ba81b081329b134c3ef5696f1da31c7780ed5479367f58`|否|.gitignore:27:data/uploads/	data/uploads/8558f0fcb272159c3af1fea72eedd2bb_f0fc352798.mp4|video；matching evaluation or analysis|
|`/data/projects/ai-basketball-analyst/data/uploads/babc7ddb968531af7ed3f89df8e43678_4032d2ab0f.mp4`|是|`8485feb7fdbabbe1b4066b8c6216d8b2425903fe9d0d77afd579f4235c9c7a32`|否|.gitignore:27:data/uploads/	data/uploads/babc7ddb968531af7ed3f89df8e43678_4032d2ab0f.mp4|video；matching evaluation or analysis|
|`/data/projects/ai-basketball-analyst/data/uploads/babc7ddb968531af7ed3f89df8e43678_c65f1415b3.mp4`|是|`8485feb7fdbabbe1b4066b8c6216d8b2425903fe9d0d77afd579f4235c9c7a32`|否|.gitignore:27:data/uploads/	data/uploads/babc7ddb968531af7ed3f89df8e43678_c65f1415b3.mp4|video；matching evaluation or analysis|
|`/data/projects/ai-basketball-analyst/data/uploads/harden-58pts-BV1sHYN6uEGd_1383973ee3.mp4`|是|`4fb57d794b66f136ae1f061ab0b7e958432e39fae673be618c14b13e1cbb4b92`|否|.gitignore:27:data/uploads/	data/uploads/harden-58pts-BV1sHYN6uEGd_1383973ee3.mp4|video；matching evaluation or analysis|
|`/data/projects/ai-basketball-analyst/data/uploads/lillard-buzzer-beater-BV165YQ68E3C_9e1bbd21c5.mp4`|是|`d8b5b37c3d5f88417e1a00bf44533dd06b659e56a30130f1839e69d1334906e6`|否|.gitignore:27:data/uploads/	data/uploads/lillard-buzzer-beater-BV165YQ68E3C_9e1bbd21c5.mp4|video；matching evaluation or analysis|
|`/data/projects/ai-basketball-analyst/data/uploads/parallel-validation_e085e68288c54595.mp4`|是|`5d2ca919876500857b6619685879badbe5373c33579884341a8c0bb092365888`|否|.gitignore:27:data/uploads/	data/uploads/parallel-validation_e085e68288c54595.mp4|video；matching evaluation or analysis|
|`/data/projects/ai-basketball-analyst/data/uploads/upload-analysis-smoke_91f58b67cf7bce3c.mp4`|是|`0340e89e84c0f58563b726fdbbcf9bb68cbfbef4da6a60a685e9c91dce782637`|否|.gitignore:27:data/uploads/	data/uploads/upload-analysis-smoke_91f58b67cf7bce3c.mp4|video；matching evaluation or analysis|
|`/data/projects/ai-basketball-analyst/data/uploads/upload-validation-yang_e146a4061cfbe068.mp4`|是|`5d2ca919876500857b6619685879badbe5373c33579884341a8c0bb092365888`|否|.gitignore:27:data/uploads/	data/uploads/upload-validation-yang_e146a4061cfbe068.mp4|video；matching evaluation or analysis|
|`/data/projects/ai-basketball-analyst/data/uploads/yang-retry2_8828aea2e1.mp4`|是|`5d2ca919876500857b6619685879badbe5373c33579884341a8c0bb092365888`|否|.gitignore:27:data/uploads/	data/uploads/yang-retry2_8828aea2e1.mp4|video；matching evaluation or analysis|
|`/data/projects/ai-basketball-analyst/data/uploads/yang-retry2_8828aea2e1_13eb89ba04d1e080.mp4`|是|`5d2ca919876500857b6619685879badbe5373c33579884341a8c0bb092365888`|否|.gitignore:27:data/uploads/	data/uploads/yang-retry2_8828aea2e1_13eb89ba04d1e080.mp4|video；matching evaluation or analysis|
|`/data/projects/ai-basketball-analyst/data/uploads/yang-retry2_8828aea2e1_47dd7e03b468f9d3.mp4`|是|`5d2ca919876500857b6619685879badbe5373c33579884341a8c0bb092365888`|否|.gitignore:27:data/uploads/	data/uploads/yang-retry2_8828aea2e1_47dd7e03b468f9d3.mp4|video；matching evaluation or analysis|
|`/data/projects/ai-basketball-analyst/data/uploads/yang-retry2_8828aea2e1_53adf906269f1182.mp4`|是|`5d2ca919876500857b6619685879badbe5373c33579884341a8c0bb092365888`|否|.gitignore:27:data/uploads/	data/uploads/yang-retry2_8828aea2e1_53adf906269f1182.mp4|video；matching evaluation or analysis|
|`/data/projects/ai-basketball-analyst/data/uploads/yang-retry2_8828aea2e1_841dfc7d9b0aa425.mp4`|是|`5d2ca919876500857b6619685879badbe5373c33579884341a8c0bb092365888`|否|.gitignore:27:data/uploads/	data/uploads/yang-retry2_8828aea2e1_841dfc7d9b0aa425.mp4|video；matching evaluation or analysis|
|`/data/projects/ai-basketball-analyst/data/uploads/yang-retry2_8828aea2e1_aa3328ae50cf0c96.mp4`|是|`5d2ca919876500857b6619685879badbe5373c33579884341a8c0bb092365888`|否|.gitignore:27:data/uploads/	data/uploads/yang-retry2_8828aea2e1_aa3328ae50cf0c96.mp4|video；matching evaluation or analysis|
|`/data/projects/ai-basketball-analyst/data/uploads/yang-retry2_8828aea2e1_d021328bef748d21.mp4`|是|`5d2ca919876500857b6619685879badbe5373c33579884341a8c0bb092365888`|否|.gitignore:27:data/uploads/	data/uploads/yang-retry2_8828aea2e1_d021328bef748d21.mp4|video；matching evaluation or analysis|
|`/data/projects/ai-basketball-analyst/data/uploads/yang-retry2_8828aea2e1_d0e66f06890fce25.mp4`|是|`5d2ca919876500857b6619685879badbe5373c33579884341a8c0bb092365888`|否|.gitignore:27:data/uploads/	data/uploads/yang-retry2_8828aea2e1_d0e66f06890fce25.mp4|video；matching evaluation or analysis|
|`/data/projects/ai-basketball-analyst/data/uploads/yang-retry2_8828aea2e1_dc67d140c8aa1d9f.mp4`|是|`5d2ca919876500857b6619685879badbe5373c33579884341a8c0bb092365888`|否|.gitignore:27:data/uploads/	data/uploads/yang-retry2_8828aea2e1_dc67d140c8aa1d9f.mp4|video；matching evaluation or analysis|
|`/data/projects/ai-basketball-analyst/data/uploads/yang-retry2_8828aea2e1_fc010933d64fa8e0.mp4`|是|`5d2ca919876500857b6619685879badbe5373c33579884341a8c0bb092365888`|否|.gitignore:27:data/uploads/	data/uploads/yang-retry2_8828aea2e1_fc010933d64fa8e0.mp4|video；matching evaluation or analysis|
|`/data/projects/ai-basketball-analyst/data/uploads/yuanshenwang_ee7c7ee534b0c5af.mp4`|是|`5d2ca919876500857b6619685879badbe5373c33579884341a8c0bb092365888`|否|.gitignore:27:data/uploads/	data/uploads/yuanshenwang_ee7c7ee534b0c5af.mp4|video；matching evaluation or analysis|
|`/data/projects/ai-basketball-analyst/data/uploads/yuanshenwang_f2f463d1c8c6a7e8.mp4`|是|`5d2ca919876500857b6619685879badbe5373c33579884341a8c0bb092365888`|否|.gitignore:27:data/uploads/	data/uploads/yuanshenwang_f2f463d1c8c6a7e8.mp4|video；matching evaluation or analysis|
|`/data/projects/ai-basketball-analyst/eval/ground_truth/shots_split2_20261011.json`|是|`bd4c272c433e77c952d212f527b43f0d06b4001e5ace7b41dbf6da0194cc5da5`|是|无|human annotations；evaluation|
|`/data/projects/ai-basketball-analyst/eval/ground_truth/match_testset_20261011.json`|是|`e213cc2efbe8c91ab1b4dbe8eedb13c1f7b18728947eb7bb037538578469c732`|是|无|human annotations；evaluation|
|`/data/projects/ai-basketball-analyst/eval/annotation_imports/three_bili_20261020/annotations.normalized.json`|是|`f890f60fd60983629af74ab05e2182aa666b035672f95ce90e32071925042c93`|是|无|human annotations；evaluation|
|`/data/projects/ai-basketball-analyst/eval/annotation_imports/three_bili_20261020/human_confirmation.json`|是|`dc85209b7447f31180cd4002f90ebb649c17bf79a4e81c80a6024527176cc652`|是|无|annotations or evidence；historical audit / review recovery|
|`/data/projects/ai-basketball-analyst/eval/baselines/events_players_off_split2_20261011.json`|是|`18cfb5908a89ad2835f4a96b1055282fbcbe9e6c8a9c486782df728c7f76a69e`|是|无|annotations or evidence；historical audit / review recovery|
|`/data/projects/ai-basketball-analyst/out/crossing_evidence_20261020/review/tasks.json`|否|`—`|否|.gitignore:63:out/	out/crossing_evidence_20261020/review/tasks.json|annotations or evidence；historical audit / review recovery|
|`/data/projects/ai-basketball-analyst/out/crossing_evidence_20261020/baseline/results.json`|否|`—`|否|.gitignore:63:out/	out/crossing_evidence_20261020/baseline/results.json|annotations or evidence；historical audit / review recovery|
|`/data/projects/ai-basketball-analyst/out/crossing_evidence_20261020/event_errors.json`|否|`—`|否|.gitignore:63:out/	out/crossing_evidence_20261020/event_errors.json|annotations or evidence；historical audit / review recovery|
|`/data/projects/ai-basketball-analyst/out/stage2_audit_20261020/current_baseline/results.json`|否|`—`|否|.gitignore:63:out/	out/stage2_audit_20261020/current_baseline/results.json|annotations or evidence；historical audit / review recovery|
|`/data/projects/ai-basketball-analyst/out/crossing_window_20261020/predeclared_plan.json`|否|`—`|否|.gitignore:63:out/	out/crossing_window_20261020/predeclared_plan.json|annotations or evidence；historical audit / review recovery|
|`/data/projects/ai-basketball-analyst/out/stage2_review_20261018_194735/manifest.json`|否|`—`|否|.gitignore:63:out/	out/stage2_review_20261018_194735/manifest.json|annotations or evidence；historical audit / review recovery|
|`/data/projects/ai-basketball-analyst/yolov8n.pt`|是|`f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36`|否|.gitignore:108:*.pt	yolov8n.pt|source/config/resource；specified workflow|
|`/data/projects/ai-basketball-analyst/data/botsort_reid.yaml`|是|`1e56f2c0863278280fd816b9086f0a136ce82ff351bf4885cc862ae463952e5c`|是|无|source/config/resource；specified workflow|
|`/data/projects/ai-basketball-analyst/pyproject.toml`|否|`—`|否|无|source/config/resource；specified workflow|
|`/data/projects/ai-basketball-analyst/requirements.txt`|是|`3387bcc209270e5622e8fd3f34ff08b81eeb977cb01d5b1647bfdc45265161ff`|是|无|source/config/resource；specified workflow|
|`/data/projects/ai-basketball-analyst/requirements-dev.txt`|否|`—`|否|无|source/config/resource；specified workflow|
|`/data/projects/ai-basketball-analyst/requirements-full.txt`|是|`6b94313dad1ded159be5383f650954eb951f2453dccb975f6a0b930ec3f2ed0d`|是|无|source/config/resource；specified workflow|
|`/data/projects/ai-basketball-analyst/out/stage2_review_20261018_194735/review/manifest.json`|是|`7e39a25cbb47786e844cd8e7100b73965b500e2163c31cabfc769f6edb309e2b`|否|.gitignore:63:out/	out/stage2_review_20261018_194735/review/manifest.json|source/config/resource；specified workflow|
|`/usr/bin/ffmpeg`|是|`36d94a605d612e4090d1b8aec889d0c0801c6eafb1593c90f5c0dfd2e2966a45`|否|outside repository|ffmpeg；media decode/encode/probe|
|`/usr/bin/ffprobe`|是|`d4f3ef9c12be756793cad83dd2004d89f49c1c4094053bfbbe7e28925c8fa4fd`|否|outside repository|ffprobe；media decode/encode/probe|
|`/data/projects/ai-basketball-analyst/eval/annotation_imports/three_bili_20261020/三个视频出手记录.txt`|是|`0d2185a015bd96c94ab068d3c2c6b7b4a3aefbad793a68964f3808b793bd9d7d`|是|无|original annotation text；annotation provenance|
|`/data/projects/ai-basketball-analyst/三个视频出手记录.txt`|是|`0d2185a015bd96c94ab068d3c2c6b7b4a3aefbad793a68964f3808b793bd9d7d`|是|无|original annotation text；annotation provenance|

资源逐项来源、字节数、角色及LFS标记见`resources.json`；模型类别见`model_inventory.json`。资源搜索范围不包括任意挂载盘或所有用户目录，未匹配表示在本轮明确检查范围内未找到，不表示Windows原文件已丢失。

## 配置与依赖

`src/scripts/tests/web/docs`及requirements文件存在。项目没有`pyproject.toml`，不因此认定项目无法运行；现有requirements与Conda入口可用。`.env`存在但不会复制或打印其中敏感内容。ffmpeg、ffprobe为现有系统可执行文件，本次已真实完成解码和H264编码。Windows专用ffmpeg绝对路径仍出现在`build_crossing_review.py`，因此迁齐数据后还需做显式的Linux命令路径适配；没有套用Windows环境文件。
