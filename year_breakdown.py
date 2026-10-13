#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐年收益构成拆解：进攻/防守贡献分列，多方案 + 基准对比。"""
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


def yearly(nv):
    """每年：总收益、进攻态贡献、防守态贡献（按前一日收盘状态归属当日收益）。"""
    r = nv["nav"].pct_change()
    st_prev = nv["state"].shift(1)
    out = {}
    for y in range(nv.index[0].year, nv.index[-1].year + 1):
        m = nv.index.year == y
        if m.sum() < 5:
            continue
        rr, ss = r[m], st_prev[m]
        atk = (1 + rr[ss == "A"].fillna(0)).prod() - 1
        dfn = (1 + rr[ss == "D"].fillna(0)).prod() - 1
        tot = (1 + rr.fillna(0)).prod() - 1
        out[y] = (tot, atk, dfn)
    return out


def bench_yearly(code, name):
    df = bt.load_kline(code)
    df = df[df.index >= "2019-01-01"]
    out = {}
    for y in range(2019, 2027):
        w = df[df.index.year == y]
        if len(w) > 5:
            out[y] = w["close"].iloc[-1] / w["close"].iloc[0] - 1
    return name, out


def main():
    ctx = bt.Context("2019-01-01", "2026-10-09")
    plans = {
        "基线(收盘单仓)": BASE,
        "推荐(开盘双仓)": {**BASE, "exec_price": "open", "topn": "2"},
    }
    res = {}
    for name, cfg in plans.items():
        nv, seg = bt.run_bt(ctx, SimpleNamespace(**cfg), collect=True)
        res[name] = yearly(nv)

    doc = {2019: .173, 2020: 1.428, 2021: .285, 2022: .125,
           2023: .184, 2024: .356, 2025: .764, 2026: 1.285}
    hs300 = bench_yearly("sh000300", "沪深300")[1]
    div = bench_yearly("sh512890", "红利低波")[1]

    years = sorted(res["基线(收盘单仓)"].keys())
    lines = []
    head = ("| 年份 | 基线总收益 | 其中进攻 | 其中防守 | 推荐版总收益 | "
            "档案V2-P1 | 沪深300 | 红利低波 |")
    sep = "|---|---|---|---|---|---|---|---|"
    lines.append(head)
    lines.append(sep)
    tot = {k: 1.0 for k in ["基线", "推荐", "档案", "沪深300", "红利低波"]}
    for y in years:
        t, a, d = res["基线(收盘单仓)"][y]
        t2 = res["推荐(开盘双仓)"][y][0]
        dv = doc.get(y, np.nan)
        h = hs300.get(y, np.nan)
        g = div.get(y, np.nan)
        tot["基线"] *= 1 + t
        tot["推荐"] *= 1 + t2
        tot["档案"] *= 1 + dv
        tot["沪深300"] *= 1 + h
        tot["红利低波"] *= 1 + g
        lines.append(f"| {y} | {t:+.1%} | {a:+.1%} | {d:+.1%} | "
                     f"{t2:+.1%} | {dv:+.1%} | {h:+.1%} | {g:+.1%} |")
    lines.append(f"| **累计** | **{tot['基线']-1:+.0%}** | — | — | "
                 f"**{tot['推荐']-1:+.0%}** | **{tot['档案']-1:+.0%}** | "
                 f"**{tot['沪深300']-1:+.0%}** | **{tot['红利低波']-1:+.0%}** |")
    text = "\n".join(lines)
    print(text)
    with open(os.path.join(HERE, "outputs", "year_breakdown.md"), "w",
              encoding="utf-8") as f:
        f.write("<!-- ASOF 2026-10-12; 台账信号; 腾讯前复权 -->\n" + text + "\n")
    print("\n已写 outputs/year_breakdown.md")


if __name__ == "__main__":
    main()
