#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""稳定性体检：滚动收益分布、水下时间、年收益统计——回答"年化能否稳定"。"""
import os
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt
from run_experiments import BASE


def stability(nv, name):
    nav = nv["nav"]
    r12 = nav / nav.shift(244) - 1                      # 滚动12月收益
    r36 = (nav / nav.shift(732)) ** (1 / 3) - 1          # 滚动36月年化
    dd = nav / nav.cummax() - 1
    uw = dd < -0.001
    # 最长水下天数
    longest = cur = 0
    for x in uw:
        cur = cur + 1 if x else 0
        longest = max(longest, cur)
    yearly = nav.groupby(nav.index.year).last().pct_change().dropna()
    print(f"\n=== {name} ===")
    print(f"滚动12月收益: 中位 {r12.median():+.1%}  P10 {r12.quantile(.1):+.1%}  "
          f"P90 {r12.quantile(.9):+.1%}  最差 {r12.min():+.1%}  最好 {r12.max():+.1%}")
    print(f"滚动12月为负的比例: {(r12 < 0).mean():.0%}")
    print(f"滚动36月年化: 中位 {r36.median():+.1%}  最差 {r36.min():+.1%}  "
          f"最好 {r36.max():+.1%}")
    print(f"最长水下时间: {longest} 个交易日 (~{longest/244:.1f} 年)")
    print(f"单年收益: 均值 {yearly.mean():+.1%}  标准差 {yearly.std():.0%}  "
            f"min {yearly.min():+.1%}  max {yearly.max():+.1%}")
    se = yearly.std() / np.sqrt(len(yearly))
    print(f"8年均值的统计误差: ±{se*1.96:.0%} (95%CI) → 真实年化区间 "
          f"[{yearly.mean()-1.96*se:+.0%}, {yearly.mean()+1.96*se:+.0%}]")


def main():
    ctx = bt.Context("2019-01-01", "2026-10-09")
    for name, cfg in [("基线(收盘单仓)", BASE),
                      ("推荐(开盘+双仓)", {**BASE, "exec_price": "open", "topn": "2"})]:
        nv, _ = bt.run_bt(ctx, SimpleNamespace(**cfg), collect=True)
        stability(nv, name)
    for code, nm in [("sh000300", "沪深300"), ("sh512890", "红利低波")]:
        df = bt.load_kline(code)
        df = df[df.index >= "2019-01-01"]
        nv = pd.DataFrame({"nav": df["close"] / df["close"].iloc[0],
                           "state": "X"}, index=df.index)
        stability(nv, nm)


if __name__ == "__main__":
    main()
