#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""优化实验矩阵：基线 + 单因子轮换（OFAT）+ 信号阈值网格。

纪律（对齐 AGENTS.md）：
  - 所有变体共用同一份上下文（同一宇宙、同一信号），只动一个因子 → 效应可归因
  - 样本内 2019-2023 / 样本外 2024-2026 分列，防"全样本调优"自欺
  - 变体数量即多重检验次数，读表时最好的变体要打 DeflatedSharpe 折扣
"""

import os
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt

BASE = dict(exec_price="close", cost=0.001, rs_window=20, buy_th=0.04,
            sell_th=-0.023, top2_gap=0.02, benchmark="sh000001",
            defense_overlay="none", signals="ledger")

OFAT = [
    ("执行=T+1开盘", {"exec_price": "open"}),
    ("成本=0.15%", {"cost": 0.0015}),
    ("成本=0.20%", {"cost": 0.002}),
    ("RS窗口=10", {"rs_window": 10}),
    ("RS窗口=40", {"rs_window": 40}),
    ("RS基准=中证全指", {"benchmark": "sh000985"}),
    ("防守熔断MA200", {"defense_overlay": "ma200"}),
    ("流动性≥2000万", {"min_amt": 2e7}),
    ("流动性≥5000万", {"min_amt": 5e7}),
    ("固定双仓", {"topn": "2"}),
    ("固定三仓", {"topn": "3"}),
    ("RS混合10/20/40", {"rs_blend": True}),
    ("脉冲过滤", {"spike_filter": True}),
    ("5日重排", {"rerank5": 1}),
    ("5日重排+RS混合", {"rerank5": 1, "rs_blend": True}),
]

THRESH_GRID = [(b, s) for b in (0.035, 0.04, 0.045) for s in (-0.020, -0.023, -0.026)]


def metrics(nv, seg, lo, hi):
    w = nv[(nv.index >= lo) & (nv.index <= hi)]
    if len(w) < 30:
        return np.nan, np.nan
    yrs = (w.index[-1] - w.index[0]).days / 365.25
    cagr = (w.nav.iloc[-1] / w.nav.iloc[0]) ** (1 / yrs) - 1
    mdd = (w.nav / w.nav.cummax() - 1).min()
    return cagr, mdd


def evaluate(ctx, cfg, tag):
    args = SimpleNamespace(**cfg)
    nv, seg = bt.run_bt(ctx, args, collect=True)
    yrs = (nv.index[-1] - nv.index[0]).days / 365.25
    total = nv.nav.iloc[-1] - 1
    cagr = nv.nav.iloc[-1] ** (1 / yrs) - 1
    mdd = (nv.nav / nv.nav.cummax() - 1).min()
    calmar = cagr / abs(mdd) if mdd < 0 else np.nan
    is_c, is_m = metrics(nv, seg, "2019-01-01", "2023-12-31")
    os_c, os_m = metrics(nv, seg, "2024-01-01", "2026-10-09")
    wins = int((seg.ret > 0).sum()) if len(seg) else 0
    return {"变体": tag, "累计": total, "年化": cagr, "回撤": mdd,
            "Calmar": calmar, "样本内年化": is_c, "样本外年化": os_c,
            "样本外回撤": os_m, "进攻段": len(seg),
            "胜率": wins / len(seg) if len(seg) else np.nan}


def main():
    ctx = bt.Context("2019-01-01", "2026-10-09")
    print(f"宇宙 {len(ctx.assets)} 只\n")
    rows = [evaluate(ctx, BASE, "基线(V2-P1参数/全市场宇宙)")]
    print(f"[1/{1+len(OFAT)+len(THRESH_GRID)}] 基线完成", flush=True)
    for i, (tag, patch) in enumerate(OFAT):
        cfg = {**BASE, **patch}
        rows.append(evaluate(ctx, cfg, tag))
        print(f"[{i+2}/{1+len(OFAT)+len(THRESH_GRID)}] {tag}", flush=True)
    for j, (b, s) in enumerate(THRESH_GRID):
        cfg = {**BASE, "buy_th": b, "sell_th": s, "signals": "csv"}
        rows.append(evaluate(ctx, cfg, f"买{b:.1%}/卖{s:.1%}"))
        print(f"[{len(OFAT)+2+j}/{1+len(OFAT)+len(THRESH_GRID)}] 阈值{b}/{s}",
              flush=True)
    df = pd.DataFrame(rows)
    out = os.path.join(HERE, "outputs", "experiments.csv")
    df.to_csv(out, index=False, encoding="utf-8-sig")
    show = df.copy()
    for c in ["累计", "年化", "回撤", "样本内年化", "样本外年化", "样本外回撤", "胜率"]:
        show[c] = (show[c] * 100).round(1)
    show["Calmar"] = show["Calmar"].round(2)
    print("\n", show.to_string(index=False))
    print(f"\n已写 {out}")
    print("提示: 共检验", len(df), "个变体，最优者需按多重检验折现解读")


if __name__ == "__main__":
    main()
