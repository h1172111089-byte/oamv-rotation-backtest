#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修复后单独补测 固定双仓/三仓（+与T+1开盘组合）。"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt
from run_experiments import BASE, evaluate

ctx = bt.Context("2019-01-01", "2026-10-09")
rows = []
for tag, patch in [("固定双仓", {"topn": "2"}),
                   ("固定三仓", {"topn": "3"}),
                   ("T+1开盘+固定双仓", {"topn": "2", "exec_price": "open"}),
                   ("T+1开盘+固定三仓", {"topn": "3", "exec_price": "open"})]:
    rows.append(evaluate(ctx, {**BASE, **patch}, tag))
    print("done", tag, flush=True)
import pandas as pd
df = pd.DataFrame(rows)
for c in ["累计", "年化", "回撤", "历史开发段年化", "历史验证段年化", "历史验证段回撤", "胜率"]:
    df[c] = (df[c] * 100).round(1)
df["Calmar"] = df["Calmar"].round(2)
print(df.to_string(index=False))
