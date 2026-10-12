# 标注模板（复制到上一级目录再改名）

口径与优先级见 `docs/需要人工标注的真值清单_2026-10-11.md`。这里只讲**怎么用**。

## 三步

1. 复制模板到上一层的 `eval/ground_truth/`，**去掉 `.template`**：
   - `jersey_split1.template.json` → `eval/ground_truth/jersey_split1.json`
   - `tactics_split1.template.json` → `eval/ground_truth/tactics_split1.json`
   - `scoreboard_split1.template.json` → `eval/ground_truth/scoreboard_split1.json`
2. 填：`annotator`（谁标的）、`created_at`，然后把每个 sample 里空着的列表填满。
   模板里那个 `_example` 只是**格式参考**，正式标注里删掉即可。
3. 自检（**这一步别省**，标错两个小时最后导入失败最亏）：

```powershell
python scripts\check_truth_files.py
```

通过后再告诉我，我把它接进 `scripts/bench_report.py` 的指标表。

## 三条要紧的规矩

- **时间一律用原片秒**（`original_video_seconds`），不是片段内相对秒。脚本会拿测试集里的
  `[start_s, end_s]` 卡你，超出范围直接报错。
- **「看不清」是合法值**：球衣号码写 `"jersey": null` + `"readable": false`，
  **不许猜**。猜出来的号码会让 top-1 变成假数字。
- `track_id` 必须用**引擎的轨迹号**（`raw_track.json` 里的 `player_track`）；
  没有轨迹号的号码标注算不出 top-1，只能算"出现过的号码集合"。
