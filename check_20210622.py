#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证台账更正：2021-06-22（错）vs 2021-07-09（对）。"""
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

for day in ["2021-06-22", "2021-07-09"]:
    d = pd.Timestamp(day)
    w = f.loc[d - pd.Timedelta(days=12): d + pd.Timedelta(days=3)]
    print(f"--- {day} 附近 ---")
    for dt in w.index:
        rr = r.get(dt)
        m3 = max(rr, s2.get(dt), s3.get(dt))
        tag = ""
        if m3 > 0.04:
            tag = "  <== 买入触发"
        elif rr < -0.023:
            tag = "  <== 卖出触发"
        print(f"{dt.date()} chg={rr:+.2%} 2日={s2.get(dt):+.2%} "
              f"3日={s3.get(dt):+.2%} conf={w.loc[dt,'confidence']}{tag}")
    print()
