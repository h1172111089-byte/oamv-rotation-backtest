#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""选股质量审计：每个进攻段，我的漏斗选了什么 vs 事后最优板块排第几。

回答三个问题：
  1. 选中率：我的选择落在事后前 5 名的比例？
  2. 距离：事后冠军在我信号日的 RS 排名是多少？（若常在前 3，说明排序对但规则没选它）
  3. 差距来源：选错的段里，冠军是因为没在漏斗里（趋势/资格被刷）还是排名靠后？
"""
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt


def main():
    ctx = bt.Context("2019-01-01", "2026-10-09")
    assets, bench = ctx.assets, ctx.bench_map["sh000001"]
    led = pd.read_csv(os.path.join(HERE, "0AMV活跃市值切换信号登记表.csv")).dropna(
        subset=["信号日期"])
    led["d"] = pd.to_datetime(led["信号日期"])
    led["exec"] = pd.to_datetime(led["执行日(T+1收盘)"])
    buys = led[led["方向"] == "买入"].reset_index(drop=True)
    sells = led[led["方向"] == "卖出"].reset_index(drop=True)

    rows = []
    for i in range(len(buys)):
        sig_d, exec_d = buys.loc[i, "d"], buys.loc[i, "exec"]
        exit_d = sells.loc[i, "exec"] if i < len(sells) else ctx.cal[-1]
        # 信号日截面：全部通过资格/趋势的候选及RS
        cands = []
        for code, a in assets.items():
            p = a.pos(sig_d)
            if p is None or p < 63:
                continue
            c = a.df["close"].iloc[p]
            if not (c > a.ma20.iloc[p] > a.ma60.iloc[p]):
                continue
            rs = a.ret20.iloc[p] - bench.ret20.iloc[bench.pos(sig_d)]
            if rs <= 0:
                continue
            # 段内收益（执行日收盘→退出执行日收盘）
            pe, px_ = a.pos(exec_d), a.pos(exit_d)
            if pe is None or px_ is None or px_ <= pe:
                continue
            seg_ret = a.df["close"].iloc[px_] / a.df["close"].iloc[pe] - 1
            cands.append((code, rs, seg_ret))
        if not cands:
            continue
        df = pd.DataFrame(cands, columns=["code", "rs", "seg_ret"])
        df["rank"] = df["rs"].rank(ascending=False)
        best = df.loc[df["seg_ret"].idxmax()]
        top1 = df.loc[df["rs"].idxmax()]
        seg = pd.read_csv(os.path.join(HERE, "outputs", "segments.csv"))
        my = None
        m = seg[pd.to_datetime(seg["entry"]) == exec_d]
        if len(m):
            import re
            my_codes = re.findall(r"'(s[hz]\d{6})'", m.iloc[0]["picks"])
            if my_codes:
                my = df[df.code.isin(my_codes)]["seg_ret"].mean()
        rows.append({
            "year": exec_d.year, "entry": exec_d.date(), "exit": exit_d.date(),
            "n_cand": len(df), "my_ret": my,
            "best_code": best["code"], "best_ret": best["seg_ret"],
            "best_rank": int(best["rank"]),
            "top1_code": top1["code"], "top1_ret": top1["seg_ret"],
            "med_ret": df["seg_ret"].median(),
        })
    r = pd.DataFrame(rows)
    r.to_csv(os.path.join(HERE, "outputs", "segment_audit.csv"), index=False)
    r["my_gt_med"] = r["my_ret"] > r["med_ret"]
    print("=== 选股质量总览（按段，事后视角）===")
    print(f"段数 {len(r)}  我的选择跑赢候选中位数比例: {r.my_gt_med.mean():.0%}")
    print(f"事后冠军的 RS 排名分布: 第1名 {(r.best_rank==1).sum()} 次, "
          f"前3 {(r.best_rank<=3).sum()} 次, 前10 {(r.best_rank<=10).sum()} 次, "
          f"10名外 {(r.best_rank>10).sum()} 次")
    print(f"信号日RS第1名的事后段收益均值 {r.top1_ret.mean():+.1%}  "
          f"中位数 {r.top1_ret.median():+.1%}")
    print(f"候选中位数段收益均值 {r.med_ret.mean():+.1%}  "
          f"事后冠军均值 {r.best_ret.mean():+.1%}")
    if r["my_ret"].notna().any():
        print(f"我的实际选择段收益均值 {r.my_ret.mean():+.1%}")
    print("\n=== 逐年差距（vs 档案）===")
    doc = {2019: 0.173, 2020: 1.428, 2021: 0.285, 2022: 0.125,
           2023: 0.184, 2024: 0.356, 2025: 0.764, 2026: 1.285}
    mine = {2019: 0.196, 2020: 1.952, 2021: 0.340, 2022: 0.075,
            2023: -0.003, 2024: 0.301, 2025: 0.064, 2026: 1.078}
    for y in doc:
        print(f"  {y}: 我 {mine[y]:+.1%}  档案 {doc[y]:+.1%}  差 {mine[y]-doc[y]:+.1%}")
    print("\n=== 冠军漏选最严重的段（冠军排名>5 且段收益>20%）===")
    bad = r[(r.best_rank > 5) & (r.best_ret > 0.2)].sort_values("entry")
    for _, x in bad.iterrows():
        print(f"  {x['entry']}~{x['exit']} 冠军 {x['best_code']} "
              f"段收益{x['best_ret']:+.0%} 但RS只排第{x['best_rank']}  "
              f"(我选 {x['top1_code']} {x['top1_ret']:+.0%})")


if __name__ == "__main__":
    main()
