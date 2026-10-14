#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""窗口口径冲突核查：1-2日 vs 1-3日 在各台账买入日的触发情况。"""
import os
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))

f = pd.read_csv(os.path.join(HERE, "0amv_day_fixed.csv"))
f["date"] = pd.to_datetime(f["date"])
f = f.set_index("date").sort_index()
f = f[~f.index.duplicated(keep="last")]
r = f["change_pct"] / 100
s2 = r + r.shift(1)
s3 = s2 + r.shift(2)

led = pd.read_csv(os.path.join(HERE, "0AMV活跃市值切换信号登记表.csv")
                  ).dropna(subset=["信号日期"])
buys = pd.to_datetime(led.loc[led["方向"] == "买入", "信号日期"])

n12 = n123 = 0
only3 = []
for d in buys:
    if d not in r.index:
        print(f"{d.date()} 无数据行")
        continue
    t12 = max(r[d], s2[d]) > 0.04
    t123 = max(r[d], s2[d], s3[d]) > 0.04
    n12 += t12
    n123 += t123
    if t123 and not t12:
        only3.append((str(d.date()), r[d], s2[d], s3[d]))
print(f"台账买入 {len(buys)} 条：1-2窗口触发 {n12}，1-3窗口触发 {n123}")
print("仅靠3日和才触发的买入（1-2窗口会漏掉）:")
for d, r1, r2, r3 in only3:
    print(f"  {d}: 1日{r1:+.2%} 2日{r2:+.2%} 3日{r3:+.2%}")
