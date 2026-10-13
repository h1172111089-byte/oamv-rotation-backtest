#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""防守腿危机熔断独立检验（不依赖信号）。

问题：策略 55-59% 时间持有红利低波，文档已指出系统性危机中红利不避险。
检验：MA200 纪律（收盘价 < MA200 → 撤到类现金资产，收回上方 → 回来）
      在 512890(2019起) / 510880(2018起) / 上证红利指数000015(2005起,新浪源) 上，
      能否压住 2008/2015/2018/2022 式回撤，代价是多少。

类现金资产：511880 货币ETF（本地数据）；000015 长历史段用 2%/年恒定现金曲线近似
（文档口径假设，非数据）。单边成本 0.1%。
"""

import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
KLINE = os.path.join(HERE, "data", "kline")


def load(code):
    df = pd.read_csv(os.path.join(KLINE, f"{code}.csv"))
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def overlay_test(risky_close, cash_close, cost=0.001, ma_win=200):
    """同一日历上：risky < MA200 → cash。返回净值序列与统计。"""
    df = pd.DataFrame({"r": risky_close}).dropna()
    df["ma"] = df["r"].rolling(ma_win).mean()
    if cash_close is not None:
        df["c"] = cash_close.reindex(df.index).ffill()
        cash_ret = df["c"].pct_change().fillna(0.0)
    else:  # 恒定 2%/年
        cash_ret = pd.Series((1.02) ** (1 / 244) - 1, index=df.index)
    risky_ret = df["r"].pct_change().fillna(0.0)
    hold_risky = (df["r"] >= df["ma"]).shift(1).fillna(False)
    strat = np.where(hold_risky, risky_ret, cash_ret)
    switch = hold_risky.diff().fillna(False).abs()
    strat = pd.Series(strat, index=df.index) - switch * cost * 2
    nav_s = (1 + pd.Series(strat, index=df.index)).cumprod()
    nav_b = (1 + risky_ret).cumprod()
    return nav_b, nav_s, int(switch.sum() // 2)


def stats(nav, name, crises):
    total = nav.iloc[-1] - 1
    yrs = (nav.index[-1] - nav.index[0]).days / 365.25
    cagr = (1 + total) ** (1 / yrs) - 1
    mdd = (nav / nav.cummax() - 1).min()
    print(f"  {name}: 累计{total:+.0%} 年化{cagr:.1%} 最大回撤{mdd:.1%}")
    for cname, (s, e) in crises.items():
        w = nav[(nav.index >= s) & (nav.index <= e)]
        if len(w) > 20:
            dd = (w / w.cummax() - 1).min()
            print(f"      {cname}: DD {dd:.1%}")
    return mdd


def main():
    crises = {"2008金融危机": ("2008-01-01", "2008-12-31"),
              "2015股灾": ("2015-06-01", "2016-02-29"),
              "2018去杠杆": ("2018-01-01", "2018-12-31"),
              "2022熊市": ("2022-01-01", "2022-12-31")}

    print("=== 512890 红利低波 (2019-02~, 腾讯qfq, 避难所=511880货币) ===")
    r = load("sh512890")["close"]
    c = load("sh511880")["close"]
    nb, ns, nsw = overlay_test(r, c)
    stats(nb, "买入持有", {k: v for k, v in crises.items() if k >= "2022"})
    stats(ns, "MA200熔断", {k: v for k, v in crises.items() if k >= "2022"})
    print(f"  切换次数(往返): {nsw}")

    print("\n=== 510880 红利ETF (2018-07~, 腾讯qfq, 避难所=511880) ===")
    r = load("sh510880")["close"]
    r = r[r.index >= "2018-07-01"]  # MA200需要前置数据
    nb, ns, nsw = overlay_test(r, c)
    stats(nb, "买入持有", {k: v for k, v in crises.items() if k >= "2018"})
    stats(ns, "MA200熔断", {k: v for k, v in crises.items() if k >= "2018"})
    print(f"  切换次数(往返): {nsw}")

    idx_path = os.path.join(KLINE, "sh000015_sina.csv")
    if os.path.exists(idx_path):
        print("\n=== 000015 上证红利指数 (2005~, 新浪源不复权≈价格指数, "
              "低估真实分红收益; 避难所=2%现金) ===")
        d = pd.read_csv(idx_path)
        d["date"] = pd.to_datetime(d["date"])
        r = d.set_index("date")["close"].sort_index()
        nb, ns, nsw = overlay_test(r, None)
        stats(nb, "买入持有", crises)
        stats(ns, "MA200熔断", crises)
        print(f"  切换次数(往返): {nsw}")
    else:
        print("\n000015 长历史未就绪，跳过")


if __name__ == "__main__":
    main()
