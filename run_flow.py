#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""资金流排序实验：RS vs 当日资金流 vs 20日资金流（Chaikin 代理），
并叠加已采纳候选（T+1开盘、固定双仓）看交互。"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt
from run_experiments import BASE, evaluate

ctx = bt.Context("2019-01-01", "2026-10-09")
variants = [
    ("基线RS", {}),
    ("当日资金流", {"rank_by": "mf1"}),
    ("20日资金流", {"rank_by": "mf20"}),
    ("RS+开盘", {"exec_price": "open"}),
    ("当日资金流+开盘", {"rank_by": "mf1", "exec_price": "open"}),
    ("20日资金流+开盘", {"rank_by": "mf20", "exec_price": "open"}),
    ("当日资金流+开盘+双仓", {"rank_by": "mf1", "exec_price": "open", "topn": "2"}),
    ("20日资金流+开盘+双仓", {"rank_by": "mf20", "exec_price": "open", "topn": "2"}),
]
rows = []
for tag, patch in variants:
    rows.append(evaluate(ctx, {**BASE, **patch}, tag))
    print("done", tag, flush=True)
import pandas as pd
df = pd.DataFrame(rows)
for c in ["累计", "年化", "回撤", "样本内年化", "样本外年化", "样本外回撤", "胜率"]:
    df[c] = (df[c] * 100).round(1)
df["Calmar"] = df["Calmar"].round(2)
print(df.to_string(index=False))
df.to_csv(os.path.join(HERE, "outputs", "flow_experiments.csv"),
          index=False, encoding="utf-8-sig")
