# record_audience.py — 录制器（开发用）

> 一次性开发工具：起一个带登录 profile 的真实浏览器，把用户手动操作"圈选用户"的
> 每一次 click / input / change 记成 JSONL，用于反推真实选择器（写 run_audience.py 的素材）。

## 作用

人工走一遍 `圈选用户 → 创建圈选任务`，录制真实 DOM 交互，产出结构化日志，
据此确定选择器，避免靠截图猜。

## 用法

```powershell
.venv\Scripts\python.exe -u automation/scripts/record_audience.py --out activities/{活动名}/日志/audience_<ts>.jsonl
```

浏览器打开后手动走一遍流程即可；结束时在 `activities/{活动名}/日志/` 下生成同名 `.stop` 文件
（脚本自动收尾），或直接关浏览器。

## 输出

`activities/{活动名}/日志/audience_<ts>.jsonl`：每行一个 JSON，含 `kind`(click/input/change)、
`tag`、`text`、`placeholder`、`label`(所属表单项)、`val` 等，用于还原操作链。
