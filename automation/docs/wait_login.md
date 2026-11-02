# 等登录 · `wait_login.py`（只读）

> **管什么**：登录态失效时开个浏览器让你重新登录，确认 **MPToken / MPUser / 当前用户名** 都恢复后才继续。
> **不管什么**：登录态为什么失效、怎么恢复 cookie（浏览器 profile 归 [`../scripts/browser_broker.py`](../scripts/browser_broker.py)）。
> **谁什么时候读**：脚本报"无权访问 / 找不到输入框"，怀疑登录态掉了的时候。

## 为什么需要它

CSDN 后台可能保留部分旧会话：页面能打开、任务列表能查，但 `MPToken / MPUser` 已经丢失，前端当前用户名为空；继续建资源或工单会把 `createBy` 写成空值。光看“页面能打开”判断不出来——本脚本每 5 秒检查一次完整登录身份，**用户名非空且两个身份 Cookie 都在**才算恢复。

## 怎么跑

```powershell
.venv\Scripts\python.exe -u automation/scripts/wait_login.py                  # 默认 = 广告后台
.venv\Scripts\python.exe -u automation/scripts/wait_login.py --site databi     # 数据平台
... --minutes 20      # 最多等多少分钟（默认 15）
... --url <页面>       # 打开哪个页面等你登录（不给就按 --site 取默认）
```

## 两个站怎么判（`--site`）

| `--site` | 站 | 打开的页面 | 判定口径 |
|---|---|---|---|
| `admin`（默认） | CSDN **广告后台** `mp-admin.csdn.net` | 任务工单列表 | `MPToken + MPUser + userName` 都非空 |
| `databi` | **数据平台** `data.csdn.net`（`run_selection.py` 取数用） | 对话页 `…/chat` | **没被踢到 `/login`** 且**对话输入框在位** |

> ⚠ **两个站的登录态互相独立**：`data.csdn.net` 过期时 `run_selection.py` 会报「对话页找不到输入框」，而广告后台同时完全正常——**别拿 A 站的探针去看 B 站**。`databi` 的探测走**另一个标签页**，不打扰你正在填的那个窗口。

窗口用**最大化**打开——固定视口在比它小的屏幕上会把右侧挤出屏幕，用户就点不到登录入口了。

## 边界

- **只读**：只发只读探测（GET 接口 / 打开对话页），不点页面上任何按钮、不下载、不创建。
- 退出码：恢复 0 / 未恢复（超时或窗口被关）1。
- 导出模块的 `400600` 只代表该模块权限不可用，不能单独拿来判断登录是否有效。
