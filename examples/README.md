# 已解析演示样例

利拉德、哈登两段正式样例，含压缩回看视频、49个逐球片段、统计、战报、战术产物及精简检测框。

逐球结果由用户人工核对，game.meta.sample_review 保留来源，不代表自动检测准确率。队别、位置未确认时不编造比分或热区；战术与检测框保留原分析的不确定性。

catalog.json 使用相对路径，应用自动发现，无需复制本机 data/example_gallery.json。Docker 构建包含此目录；挂载 data/out 不会遮住它。

视频出处见 catalog.json 的 source_url；版权归原权利人。压缩版本仅供对应比赛复盘样例回看。本目录不是开放许可素材集，也不授权其他用途。

raw_track、推理检查点和训练文件未随包发布。manifest.json 可核对文件完整性。
