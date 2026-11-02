# 录制器（开发用）· `record_audience.py`

> **管什么**：起一个带登录 profile 的真实浏览器，把你手动操作「圈选用户」的每次 click / input / change 录成 JSONL，用来反推真实选择器。
> **不管什么**：真正跑圈选 → [`run_audience.md`](run_audience.md)。
> **谁什么时候读**：写 / 改 `run_audience.py` 的选择器时（一次性开发工具）。

## 用法

```powershell
.venv\Scripts\python.exe -u automation/scripts/record_audience.py --out activities/{活动名}/日志/audience_<ts>.jsonl
```

浏览器打开后手动走一遍 `圈选用户 → 创建圈选任务`；结束时在 `activities/{活动名}/日志/` 下生成同名 `.stop` 文件（脚本自动收尾），或直接关浏览器。

## 输出

`activities/{活动名}/日志/audience_<ts>.jsonl`：每行一个 JSON，含 `kind`(click/input/change) / `tag` / `text` / `placeholder` / `label`（所属表单项）/ `val` 等，用于还原操作链。
