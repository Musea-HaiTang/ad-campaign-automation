# -*- coding: utf-8 -*-
"""圈选阈值策略（纯决策，不碰浏览器）：越界时怎么找落点。

被 `run_audience.py` 用在两处：`--tune`（只搜不建）和正式跑越界时的**当场自动调**（搜到就继续建）。

**2026-09-21 改：曝光阈值锁死 1**（用户定：「日常就设置曝光1，博文数量越多越好，这样曝光就会大」）。

- 为什么不再动曝光：**曝光=0 是虚池**——池子大 2.2~24 倍，日均曝光反而低 2.8~11 倍
  （9/14 五桶对照 + 9/21 两条测试：12,370 篇→7,757 曝光，300,000 篇→5,130 曝光）。
  「实际圈选博客ID数」数的是博文ID的个数，不区分这篇博文有没有流量；曝光阈值是唯一能把
  「有过流量的活博文」和「零展示的僵尸博文」分开的旋钮。
- 所以搜索旋钮只剩「点击需≥X」：**超上限**时升点击收缩；**低于下限**时不再动阈值——
  那是关键词不够，去改词加词，不是调阈值。

规则（能脱浏览器测，见 `automation/tests/test_audience_policy.py`）：

  1. 基线：默认阈值（点击≥0、曝光≥1）读一个数 —— 落在 [min,max] 内就收工；
  2. 偏高：升点击 1..click_max（点击阈值越高圈得越少）；掉到下限以下就停；
  3. 偏低：直接 `needs_keywords`（**不再降曝光到 0**）；
  4. 都不行 → `needs_keywords`（不硬选，交给人改词）；
  5. **总调用上限 max_calls=5（含基线那次）**：到顶就收手（用户 2026-09-10 定：最多 5 次）。

`estimate(click, exposure) -> int | None`：读不到数字返回 None（这一步没读到，跳过继续试下一步）。

`base`：正式跑在进策略之前**已经读过一次基线**（就是日志里那行「预估圈选总数」），
把它传进来就不要再读一遍（同一组阈值读两次不但白花一次分析，还因为数字没变化要等满 25 秒兜底超时）。
不传（NOT_GIVEN）= 策略自己先读基线；传 None = 调用方已经试过、确实读不到 → 直接 analyze_fail。
"""
from dataclasses import dataclass

OK = "ok"
NEEDS_KEYWORDS = "needs_keywords"
ANALYZE_FAIL = "analyze_fail"

BASE_CLICK = 0
BASE_EXPOSURE = 1          # 锁死：曝光阈值永远是 1（见模块注释）
DEFAULT_CLICK_MAX = 4
DEFAULT_MAX_CALLS = 5

NOT_GIVEN = object()   # 区分「没传 base」和「传了 base=None（读不到）」


@dataclass
class Result:
    """一次搜索的结果。落点用 click/exposure/count，base 是最初那个基线数。"""

    click: int | None = None
    exposure: int | None = None
    count: int | None = None
    status: str = ANALYZE_FAIL
    base: int | None = None
    calls: int = 0

    def as_tuple(self):
        return self.click, self.exposure, self.count, self.status, self.base


def search(estimate, *, min_count, max_count,
           click_max=DEFAULT_CLICK_MAX, max_calls=DEFAULT_MAX_CALLS, base=NOT_GIVEN):
    """找第一个落在 [min_count, max_count] 的点击阈值，曝光固定 1。

    max_calls 只数「真的换了阈值去试」的次数；调用方自带 base 时不占额度。
    """
    calls = 0

    def rd(click, exposure):
        nonlocal calls
        calls += 1
        return estimate(click, exposure)

    def budget_left():
        return calls < max_calls

    if base is NOT_GIVEN:
        base = rd(BASE_CLICK, BASE_EXPOSURE)
        if base is None:
            return Result(status=ANALYZE_FAIL, calls=calls)
    elif base is None:
        return Result(status=ANALYZE_FAIL, calls=calls)   # 调用方已试过，读不到
    if min_count <= base <= max_count:
        return Result(BASE_CLICK, BASE_EXPOSURE, base, OK, base, calls)

    if base > max_count:
        for ck in range(1, click_max + 1):
            if not budget_left():
                break
            c = rd(ck, BASE_EXPOSURE)
            if c is None:
                continue
            if min_count <= c <= max_count:
                return Result(ck, BASE_EXPOSURE, c, OK, base, calls)
            if c < min_count:
                break
        return Result(status=NEEDS_KEYWORDS, base=base, calls=calls)

    # base < min_count：池子不够，是关键词不够——改词，不降曝光（曝光=0 是虚池）
    return Result(status=NEEDS_KEYWORDS, base=base, calls=calls)
