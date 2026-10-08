# -*- coding: utf-8 -*-
"""圈选阈值策略的单测：假 estimate，毫秒级，不开浏览器。

跑法（在仓库根）：
    .venv\\Scripts\\python.exe -m unittest discover -s automation/tests -v

口径（2026-09-21）：**曝光阈值锁死 1**——搜索只动点击阈值；低于下限直接 needs_keywords
（改词加词），不再降曝光到 0。下限默认 25000（≈ 保底 1 万日均曝光）。
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]   # automation/
sys.path.insert(0, str(ROOT / "scripts"))

import audience_policy as ap  # noqa: E402

MIN_C, MAX_C = 25000, 200000


def fake_estimate(table, default=None):
    """table: {(click, exposure): 预估总数}；不在表里就用 default。返回 (函数, 调用记录)。"""
    calls = []

    def estimate(click, exposure):
        calls.append((click, exposure))
        return table.get((click, exposure), default)

    return estimate, calls


class AudiencePolicyTest(unittest.TestCase):
    def search(self, table, default=None, **kw):
        est, calls = fake_estimate(table, default)
        r = ap.search(est, min_count=MIN_C, max_count=MAX_C, **kw)
        return r, calls

    def test_基线就在范围内_一次收工(self):
        r, calls = self.search({(0, 1): 64269})
        self.assertEqual((r.status, r.click, r.exposure, r.count, r.calls),
                         (ap.OK, 0, 1, 64269, 1))
        self.assertEqual(calls, [(0, 1)])

    def test_偏高_升点击命中(self):
        r, calls = self.search({(0, 1): 500000, (1, 1): 120000})
        self.assertEqual((r.status, r.click, r.exposure, r.count, r.base),
                         (ap.OK, 1, 1, 120000, 500000))
        self.assertEqual(calls, [(0, 1), (1, 1)])

    def test_偏高_升点击掉下界就停手(self):
        # 点击 1 直接缩到下限以下 → 不再往后试，交给人改词
        r, calls = self.search({(0, 1): 500000, (1, 1): 5000}, default=5000)
        self.assertEqual(r.status, ap.NEEDS_KEYWORDS)
        self.assertEqual(calls, [(0, 1), (1, 1)])

    def test_曝光恒为1_任何一步都不动曝光(self):
        r, calls = self.search({(0, 1): 500000, (1, 1): 30000, (2, 1): 100000})
        self.assertEqual((r.status, r.click, r.exposure, r.count), (ap.OK, 1, 1, 30000))
        self.assertEqual([e for _, e in calls], [1, 1])

    def test_偏高_一直不命中_标需要改词(self):
        r, calls = self.search({}, default=500000)
        self.assertEqual(r.status, ap.NEEDS_KEYWORDS)
        self.assertEqual(r.base, 500000)
        self.assertEqual(r.calls, ap.DEFAULT_MAX_CALLS)      # 1 次基线 + 4 次点击，到顶收手
        self.assertEqual(len(calls), ap.DEFAULT_MAX_CALLS)

    def test_偏低_不降曝光_直接标需要改词(self):
        # 曝光=0 能把池子撑到 6 万也不试——虚池不进流程（2026-09-21 定）
        r, calls = self.search({(0, 1): 3000, (0, 0): 60000})
        self.assertEqual(r.status, ap.NEEDS_KEYWORDS)
        self.assertEqual(r.base, 3000)
        self.assertEqual(calls, [(0, 1)])

    def test_偏低一点点_同样标需要改词(self):
        r, calls = self.search({(0, 1): 499})
        self.assertEqual(r.status, ap.NEEDS_KEYWORDS)
        self.assertEqual(r.calls, 1)

    def test_基线读不到数字_直接判分析失败(self):
        r, calls = self.search({})
        self.assertEqual(r.status, ap.ANALYZE_FAIL)
        self.assertEqual((r.calls, len(calls)), (1, 1))

    def test_途中读不到数字_跳过这一步继续试(self):
        r, calls = self.search({(0, 1): 500000, (3, 1): 150000}, default=None)
        self.assertEqual((r.status, r.click, r.exposure, r.count), (ap.OK, 3, 1, 150000))
        self.assertEqual(calls, [(0, 1), (1, 1), (2, 1), (3, 1)])

    def test_总次数上限可调(self):
        r, calls = self.search({}, default=500000, max_calls=2)
        self.assertEqual(r.status, ap.NEEDS_KEYWORDS)
        self.assertEqual((r.calls, len(calls)), (2, 2))

    def test_搜索边界由_click_max_决定(self):
        r, calls = self.search({}, default=500000, click_max=2, max_calls=10)
        self.assertEqual(calls, [(0, 1), (1, 1), (2, 1)])
        self.assertEqual(r.status, ap.NEEDS_KEYWORDS)

    def test_命中后不再往后试(self):
        r, calls = self.search({(0, 1): 500000, (1, 1): 199999, (2, 1): 30000})
        self.assertEqual((r.click, r.exposure, r.count), (1, 1, 199999))
        self.assertEqual(len(calls), 2)

    def test_给了基线就不再重复读一次(self):
        # 正式跑已经读过基线 → 直接从「点击 1」开始试，省掉那次白读
        est, calls = fake_estimate({(1, 1): 25393})
        r = ap.search(est, min_count=MIN_C, max_count=50000, base=64269)
        self.assertEqual((r.status, r.click, r.exposure, r.count, r.base), (ap.OK, 1, 1, 25393, 64269))
        self.assertEqual(calls, [(1, 1)])          # 没有 (0,1) 那次
        self.assertEqual(r.calls, 1)

    def test_给了基线时_额度都花在真实尝试上(self):
        # 自带基线不占额度：试满 click_max 次才收手
        est, calls = fake_estimate({}, default=500000)
        r = ap.search(est, min_count=MIN_C, max_count=MAX_C, base=500000)
        self.assertEqual(r.status, ap.NEEDS_KEYWORDS)
        self.assertEqual(r.calls, ap.DEFAULT_CLICK_MAX)
        self.assertEqual(len(calls), ap.DEFAULT_CLICK_MAX)
        self.assertEqual(calls[0], (1, 1))         # 第一发就是点击 1，不是重读基线

    def test_调用方说基线读不到_直接判失败且不再调estimate(self):
        est, calls = fake_estimate({}, default=123)
        r = ap.search(est, min_count=MIN_C, max_count=MAX_C, base=None)
        self.assertEqual((r.status, r.calls), (ap.ANALYZE_FAIL, 0))
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
