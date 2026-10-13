#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台账 vs 机械重放 对账。"""
import os
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt

led = pd.read_csv(os.path.join(HERE, "0AMV活跃市值切换信号登记表.csv"))
led["信号日期"] = pd.to_datetime(led["信号日期"])
led["执行日(T+1收盘)"] = pd.to_datetime(led["执行日(T+1收盘)"])
print("台账:", len(led), "条  范围",
      led["信号日期"].min().date(), "~", led["信号日期"].max().date())
print(led["方向"].value_counts().to_dict())
print(led.groupby("年份")["方向"].count().to_dict())

# 机械重放（保守修复口径）
sig = bt.load_amv_signals("2019-01-01", "2026-10-09", 0.04, -0.023)
state = "D"
mech = []
for d, row in sig.iterrows():
    if state == "D" and row["buy"]:
        mech.append((d, "买入"))
        state = "A"
    elif state == "A" and row["sell"]:
        mech.append((d, "卖出"))
        state = "D"
mech = pd.DataFrame(mech, columns=["date", "dir"])
print("\n机械重放:", len(mech), "条", mech["dir"].value_counts().to_dict())

# 对账：台账每条信号，找机械重放里同方向最近的日期差
import numpy as np

diffs = []
for _, r in led.iterrows():
    cand = mech[mech["dir"] == r["方向"]]
    if len(cand) == 0:
        continue
    dd = (cand["date"] - r["信号日期"]).dt.days.abs().min()
    diffs.append(dd)
diffs = pd.Series(diffs)
print("\n台账→机械 最近同方向日期差分布:")
print("  0天:", (diffs == 0).sum(), " 1天:", (diffs == 1).sum(),
      " 2-3天:", ((diffs >= 2) & (diffs <= 3)).sum(),
      " 4-7天:", ((diffs >= 4) & (diffs <= 7)).sum(),
      " >7天:", (diffs > 7).sum())
print("  中位:", diffs.median(), " 最大:", diffs.max())

# 反向：机械有而台账无
diffs2 = []
for _, r in mech.iterrows():
    cand = led[led["方向"] == r["dir"]]
    dd = (cand["信号日期"] - r["date"]).dt.days.abs().min()
    diffs2.append(dd)
diffs2 = pd.Series(diffs2)
print("\n机械→台账 最近日期差: 0天:", (diffs2 == 0).sum(),
      " 1天:", (diffs2 == 1).sum(), " >7天:", (diffs2 > 7).sum())

# 不一致明细（>3天）
print("\n差异>3天的台账信号:")
for i, r in led.iterrows():
    cand = mech[mech["dir"] == r["方向"]]
    if len(cand):
        dd = (cand["date"] - r["信号日期"]).dt.days
        j = dd.abs().idxmin()
        if abs(dd[j]) > 3:
            print(f"  #{r['序号']} {r['信号日期'].date()} {r['方向']} "
                  f"→ 机械最近 {cand.loc[j, 'date'].date()} (差{dd[j]:+d}天)")
