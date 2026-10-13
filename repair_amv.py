#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修复 0amv_day.csv 的日期轴。

原理：
  - 数值序列是按时间顺序记录的（仅日期标签错），相邻行的涨跌幅计算仍然有效
  - 台账 96 个信号日是硬锚点：卖出日该行跌幅必 < -2.3%，买入日 1/2/3 日涨幅和最大值 > +4%
  - 先做"事件-候选"序列比对（DP，代价=标签日与台账日的偏差天数），
    再在相邻锚点间按交易日历单调插值
  - 台账之前（2001-2018）无锚点：从首个锚点按交易日历倒推 1:1 排布，
    置信度标 low（约 7% 的缺失行会使越早的日期越偏早）

输出：0amv_day_fixed.csv（date, open..close, change_pct, confidence, method）
校验：修复后的序列重算信号，应精确复现台账日期（锚点），并统计锚点间伪信号。
"""

import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))

BUY_TH, SELL_TH = 0.04, -0.023
SKIP_CAND_COST = 1.5     # 跳过一个候选行（视为漂移产生的噪音信号）的代价
MISS_EVENT_COST = 45.0   # 台账事件无候选可配（严重）的代价


def load_calendar():
    d = pd.read_csv(os.path.join(HERE, "data", "kline", "sh000001_sina_long.csv"))
    d["date"] = pd.to_datetime(d["date"])
    return d["date"].tolist()


def main():
    cal = load_calendar()
    cal_idx = {d: i for i, d in enumerate(cal)}

    amv = pd.read_csv(os.path.join(HERE, "0amv_day.csv"))
    amv["label"] = (pd.to_datetime(amv["date"], utc=True)
                    .dt.tz_convert("Asia/Shanghai").dt.tz_localize(None))
    amv = amv.sort_values("label").reset_index(drop=True)
    r = amv["change_pct"] / 100.0
    s2 = r + r.shift(1)
    s3 = s2 + r.shift(2)
    mx = pd.concat([r, s2, s3], axis=1).max(axis=1)
    # 候选行：严格满足 + 容差带（手抄舍入可能让真值跨阈值），容差越大匹配代价越高
    amv["cand"] = ""
    amv["cand_pen"] = np.nan
    for th_s, pen in [(SELL_TH, 0.0), (-0.021, 3.0), (-0.019, 8.0)]:
        msk = (r < th_s) & (amv["cand"] == "") & (mx <= BUY_TH)
        amv.loc[msk, "cand"] = "sell"
        amv.loc[msk, "cand_pen"] = pen
    msk = (r < SELL_TH) & (mx > BUY_TH) & (amv["cand"] == "")
    amv.loc[msk, "cand"] = "sell"          # 同日双触发卖出优先
    amv.loc[msk, "cand_pen"] = 0.0
    for th_b, pen in [(BUY_TH, 0.0), (0.036, 3.0), (0.032, 8.0)]:
        msk = (mx > th_b) & (amv["cand"] == "") & (r >= SELL_TH)
        amv.loc[msk, "cand"] = "buy"
        amv.loc[msk, "cand_pen"] = pen

    led = pd.read_csv(os.path.join(HERE, "0AMV活跃市值切换信号登记表.csv")
                      ).dropna(subset=["信号日期"])
    led["T"] = pd.to_datetime(led["信号日期"])
    events = [("buy" if x == "买入" else "sell", t)
              for x, t in zip(led["方向"], led["T"])]

    cand_idx = amv.index[amv["cand"] != ""].tolist()
    cand = [(amv.loc[i, "cand"], amv.loc[i, "label"], i,
             amv.loc[i, "cand_pen"]) for i in cand_idx]
    print(f"CSV 候选行 {len(cand)}（买 {sum(c[0]=='buy' for c in cand)} / "
          f"卖 {sum(c[0]=='sell' for c in cand)}），台账事件 {len(events)}")

    # ---- 序列比对 DP：候选行 i × 台账事件 j ----
    n, m = len(cand), len(events)
    NEG = np.inf
    dp = np.full((n + 1, m + 1), NEG)
    back = np.full((n + 1, m + 1), "", dtype=object)
    dp[0, :] = np.arange(m + 1) * MISS_EVENT_COST
    dp[:, 0] = np.arange(n + 1) * SKIP_CAND_COST
    for j in range(1, m + 1):
        back[0, j] = "miss"
    for i in range(1, n + 1):
        back[i, 0] = "skip"
    for i in range(1, n + 1):
        ci_type, ci_label, _, ci_pen = cand[i - 1]
        for j in range(1, m + 1):
            ev_type, ev_T = events[j - 1]
            best, how = dp[i - 1, j] + SKIP_CAND_COST, "skip"
            if dp[i, j - 1] + MISS_EVENT_COST < best:
                best, how = dp[i, j - 1] + MISS_EVENT_COST, "miss"
            if ci_type == ev_type:
                mc = (dp[i - 1, j - 1] + abs((ci_label - ev_T).days)
                      + ci_pen)
                if mc < best:
                    best, how = mc, "match"
            dp[i, j] = best
            back[i, j] = how
    # 回溯
    i, j = n, m
    anchors = []   # (csv_row, ledger_date, type)
    skipped_events = []
    while i > 0 or j > 0:
        how = back[i, j]
        if how == "match":
            anchors.append((cand[i - 1][2], events[j - 1][1], events[j - 1][0]))
            i -= 1
            j -= 1
        elif how == "miss":
            skipped_events.append(events[j - 1])
            j -= 1
        else:
            i -= 1
    anchors.reverse()
    print(f"对齐完成: 匹配 {len(anchors)}/{len(events)} 个台账事件，"
          f"未匹配 {len(skipped_events)}，DP总代价 {dp[n, m]:.0f}")
    if skipped_events:
        print("未匹配事件:", [(t, str(d.date())) for t, d in skipped_events])
    devs = [abs((amv.loc[row, 'label'] - T).days) for row, T, _ in anchors]
    print(f"锚点标签日偏差: 中位 {np.median(devs):.0f} 天, 最大 {max(devs)} 天")
    strict_anchors = [(row, T, t) for row, T, t in anchors
                      if amv.loc[row, "cand_pen"] == 0.0]
    band_anchors = [(row, T, t) for row, T, t in anchors
                    if amv.loc[row, "cand_pen"] > 0.0]
    print(f"其中严格满足阈值 {len(strict_anchors)} 个，容差带匹配 {len(band_anchors)} 个")

    # 未匹配事件的诊断：找最近的同型候选行
    print("\n未匹配事件诊断（台账日 vs 最近同型候选）:")
    for ev_t, ev_T in skipped_events:
        same = [(c[1], c[2]) for c in cand if c[0] == ev_t]
        if not same:
            continue
        lab, row = min(same, key=lambda x: abs((x[0] - ev_T).days))
        v = amv.loc[row, "change_pct"]
        print(f"  {ev_T.date()} {ev_t}: 最近候选标签 {lab.date()} "
              f"(差{abs((lab-ev_T).days)}天) 当日涨跌 {v:+.2f}%")

    # ---- 逐行日期分配（锚点间保邻接：左正推+右倒推，缝取标签偏差最小处）----
    assigned = pd.Series(pd.NaT, index=amv.index)
    method = pd.Series("interp", index=amv.index, dtype=object)
    for row, T, _ in anchors:
        assigned[row] = T
        method[row] = "anchor"
    a_rows = [a[0] for a in anchors]
    a_days = [a[1] for a in anchors]

    def seg_cost(rows, days):
        return sum(abs((amv.loc[rw, "label"] - dy).days)
                   for rw, dy in zip(rows, days))

    for k in range(len(anchors) - 1):
        r0, r1 = a_rows[k], a_rows[k + 1]
        d0, d1 = cal_idx[a_days[k]], cal_idx[a_days[k + 1]]
        n_rows = r1 - r0 - 1
        n_days = d1 - d0 - 1
        if n_rows <= 0:
            continue
        best_s, best_c = None, np.inf
        for s in range(r0, r1 + 1):            # 缝在 s：左段到 s，s+1 起右段
            nL = s - r0
            nR = r1 - s - 1
            if nL > n_days or nR > n_days or (nL + nR) > n_days:
                continue
            # 左段 1:1 从 d0 顺推；右段 1:1 从 d1 倒推；中间留空则跳过
            dL = list(range(d0, d0 + nL + 1))            # 含锚点 r0→d0
            dR = list(range(d1 - nR, d1 + 1))            # 含锚点 r1→d1
            if dL and dR and dL[-1] >= dR[0]:
                continue
            rows = list(range(r0, s + 1)) + list(range(s + 1, r1 + 1))
            days = [cal[x] for x in dL + dR]
            c = seg_cost(rows, days)
            if c < best_c:
                best_c, best_s = c, (rows, days)
        if best_s is None:                     # 行数多于天数：按天比例压缩
            for row in range(r0 + 1, r1):
                frac = (row - r0) / (r1 - r0)
                assigned[row] = cal[int(round(d0 + frac * (d1 - d0)))]
                method[row] = "interp_squeeze"
            continue
        rows, days = best_s
        for rw, dy in zip(rows, days):
            if rw not in a_rows:
                assigned[rw] = dy
    # 首锚之前：按交易日 1:1 倒推
    r0 = a_rows[0]
    d0 = cal_idx[a_days[0]]
    for row in range(r0 - 1, -1, -1):
        d0 -= 1
        if d0 < 0:
            assigned = assigned.iloc[:r0]
            break
        assigned[row] = cal[d0]
        method[row] = "backward_lowconf"
    # 末锚之后：1:1 顺推
    r1 = a_rows[-1]
    d1 = cal_idx[a_days[-1]]
    for row in range(r1 + 1, len(amv)):
        d1 += 1
        if d1 >= len(cal):
            break
        assigned[row] = cal[d1]
        method[row] = "forward_lowconf"

    out = amv[["open", "high", "low", "close", "change_pct"]].copy()
    out.insert(0, "date", assigned)
    out["confidence"] = np.where(method == "anchor", "anchor",
                         np.where(method == "interp", "interp", "low"))
    out["method"] = method
    out = out.dropna(subset=["date"]).sort_values("date")
    out.to_csv(os.path.join(HERE, "0amv_day_fixed.csv"), index=False,
               encoding="utf-8-sig")
    print(f"\n已输出 0amv_day_fixed.csv  {len(out)} 行  "
          f"{out['date'].min().date()} ~ {out['date'].max().date()}")
    print(out["confidence"].value_counts().to_dict())

    # ---- 校验：修复序列上重算信号，对照台账 ----
    rr = out.set_index("date")["change_pct"] / 100.0
    rr = rr[~rr.index.duplicated(keep="last")].sort_index()
    s2f = rr + rr.shift(1)
    s3f = s2f + rr.shift(2)
    mxf = pd.concat([rr, s2f, s3f], axis=1).max(axis=1)
    buy_f = mxf > BUY_TH
    sell_f = rr < SELL_TH
    state = "D"
    trans = []
    for d in rr.index:
        b, s = bool(buy_f.get(d, False)), bool(sell_f.get(d, False))
        if b and s:
            b = False
        if d < pd.Timestamp("2019-01-01"):
            if s:
                state = "D"
            elif b:
                state = "A"
            continue
        if state == "D" and b:
            trans.append((d, "buy"))
            state = "A"
        elif state == "A" and s:
            trans.append((d, "sell"))
            state = "D"
    trans = pd.DataFrame(trans, columns=["date", "dir"])
    hit = extra = 0
    for _, r_ in led.iterrows():
        want = "buy" if r_["方向"] == "买入" else "sell"
        if ((trans["dir"] == want) & (trans["date"] == r_["T"])).any():
            hit += 1
    led_set = {(str(r_["T"].date()), "buy" if r_["方向"] == "买入" else "sell")
               for _, r_ in led.iterrows()}
    for _, r_ in trans.iterrows():
        if (str(r_["date"].date()), r_["dir"]) not in led_set:
            extra += 1
    print(f"\n校验: 台账命中 {hit}/96, 修复序列多出的信号 {extra} 条")
    if extra:
        ex = [r_ for _, r_ in trans.iterrows()
              if (str(r_["date"].date()), r_["dir"]) not in led_set]
        print("多出信号明细:", [(str(d.date()), t) for d, t in ex][:12])


if __name__ == "__main__":
    main()
