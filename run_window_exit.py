#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""入口窗口(1-2日 vs 1-3日) × 出口规则(-2.3% vs 跌破MA10) 2×2 对照。

A 部分：2019 至今，全市场宇宙 + 七层漏斗完整策略（csv 机械信号）
B 部分：2012 至今，信号层单测——进攻载体用上证指数（2018 前无行业 ETF 宇宙），
        防守=2%/年现金，T+1 收盘，单边 0.1%
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
from accounting import equity_stats
from run_experiments import BASE, evaluate

COMBOS = [("1-2日", "12"), ("1-3日", "123")]
EXITS = [("-2.3%", "drop"), ("跌破MA10", "ma10")]


def gen_signals(start, end, buy_th, sell_th, ew, er, input_root=None):
    """自包含信号生成（用新浪长日历，支持 2012 起）。"""
    root = HERE if input_root is None else input_root
    cal = pd.read_csv(os.path.join(root, "data", "kline",
                                   "sh000001_sina_long.csv"))["date"]
    return bt.load_amv_signals(start, end, buy_th, sell_th, ew, er,
                               pd.DatetimeIndex(pd.to_datetime(cal)), root)


def timing_bt(sig, px, start, end):
    """载体=上证指数，防守=2%/年现金，T+1收盘，单边0.1%。"""
    days = px.index[(px.index >= pd.Timestamp(start)) & (px.index <= pd.Timestamp(end))]
    nav, state, pending = 1.0, "D", None
    segs, cur = [], None
    cash_daily = (1.02) ** (1 / 244) - 1
    nav_series = []
    returns = px["close"].pct_change(fill_method=None)
    for index, d in enumerate(days):
        if index:
            ret = returns.loc[d]
            if not np.isfinite(ret):
                raise ValueError(f"Missing index return: {d}")
            nav *= (1 + ret) if state == "A" else (1 + cash_daily)
        if pending == "enter":
            cur = nav
            nav /= 1 + 0.001
            state = "A"
            pending = None
        elif pending == "exit":
            nav *= 1 - 0.001
            segs.append(nav / cur - 1)
            cur = None
            state = "D"
            pending = None
        nav_series.append((d, nav))
        if d in sig.index:
            row = sig.loc[d]
            if state == "D" and row["buy"]:
                pending = "enter"
            elif state == "A" and row["sell"]:
                pending = "exit"
    nv = pd.Series(dict(nav_series)).sort_index()
    stats = equity_stats(nv)
    wins = sum(1 for x in segs if x > 0)
    return {"累计": stats["total"], "年化": stats["cagr"],
            "MDD": stats["mdd"], "段数": len(segs), "胜率": wins / len(segs) if segs else np.nan}


def main():
    ctx = bt.Context("2019-01-01", "2026-10-09")
    print("== A: 2019至今 全市场完整策略（csv机械信号）==")
    rows = []
    for ename, ew in COMBOS:
        for xname, xr in EXITS:
            cfg = {**BASE, "signals": "csv", "entry_window": ew, "exit_rule": xr}
            row = evaluate(ctx, cfg, f"{ename}入场/{xname}离场")
            rows.append(row)
            print("done", ename, xname, flush=True)
    df = pd.DataFrame(rows)
    for c in ["累计", "年化", "回撤", "历史开发段年化", "历史验证段年化", "历史验证段回撤", "胜率"]:
        df[c] = (df[c] * 100).round(1)
    df["Calmar"] = df["Calmar"].round(2)
    print(df[["变体", "累计", "年化", "回撤", "Calmar", "历史开发段年化",
              "历史验证段年化", "进攻段", "胜率"]].to_string(index=False))
    print("所有既有时期已经查看；不是未见样本外证据。")

    print("\n== B: 信号层单测（载体=上证指数，防守=2%现金）==")
    px = pd.read_csv(os.path.join(HERE, "data", "kline", "sh000001_sina_long.csv"))
    px["date"] = pd.to_datetime(px["date"])
    px = px.set_index("date").sort_index()
    for span, (s, e) in [("2012至今", ("2012-01-01", "2026-10-13")),
                         ("2012-2018", ("2012-01-01", "2018-12-31")),
                         ("2019至今", ("2019-01-01", "2026-10-13"))]:
        print(f"-- {span} --")
        hs300_bh = timing_bt(pd.DataFrame(columns=["buy", "sell"],
                                          index=pd.DatetimeIndex([])), px, s, e)
        # 基准：全程持有
        w = px[(px.index >= s) & (px.index <= e)]["close"]
        bh = w.iloc[-1] / w.iloc[0] - 1
        yrs = (w.index[-1] - w.index[0]).days / 365.25
        print(f"   买入持有基准: 累计{bh:+.0%} 年化{(1+bh)**(1/yrs)-1:+.1%}")
        for ename, ew in COMBOS:
            for xname, xr in EXITS:
                sig = gen_signals(s, e, 0.04, -0.023, ew, xr)
                m = timing_bt(sig, px, s, e)
                print(f"   {ename}入场/{xname}离场: 累计{m['累计']:+.0%} "
                      f"年化{m['年化']:+.1%} MDD{m['MDD']:.1%} "
                      f"段{m['段数']} 胜率{m['胜率']:.0%}")


if __name__ == "__main__":
    main()
