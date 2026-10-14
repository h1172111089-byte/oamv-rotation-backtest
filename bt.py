#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""0AMV 信号择时 + 全市场行业动量轮动 · 回测引擎

与原始策略文档（B腿 V2-P1）的关系：
  - 漏斗七层规则忠实复刻（资格/趋势/RS/去重/空主线/接力/分散）
  - 进攻池从"手工44只"改为"全市场行业主题ETF宇宙"（build_universe.py 产物）
  - 信号源可插拔：当前为 0amv_day.csv 保守修复版（见 signals_from_amv），
    待用户手抄台账到位后以 ledger 替换，一行切换

口径：T日收盘出信号，T+1 成交（默认收盘，可切开盘），单边成本默认 0.1%。

已知局限（输出中会再次声明）：
  1. 宇宙为当前在册 ETF，已清盘者缺失（轻度幸存者偏差）
  2. AMV 日期轴损坏，修复版信号为**暂定口径**，台账对账前绝对收益不可尽信
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
KLINE = os.path.join(HERE, "data", "kline")
OUT = os.path.join(HERE, "outputs")
os.makedirs(OUT, exist_ok=True)

DEFENSE = "sh512890"          # 红利低波ETF
DEFENSE_PROXY = "sh510880"    # 512890 上市前代理（红利ETF）
CASH_ASSET = "sh511880"       # 货币ETF（防守熔断用）
LEDGER = os.path.join(HERE, "0AMV活跃市值切换信号登记表.csv")


def load_ledger_signals(start, end):
    """手抄台账信号（权威源）。结构已校验：交易日/严格交替/执行日=次一交易日。"""
    led = pd.read_csv(LEDGER).dropna(subset=["信号日期"])
    led["date"] = pd.to_datetime(led["信号日期"])
    led = led[(led["date"] >= pd.Timestamp(start)) & (led["date"] <= pd.Timestamp(end))]
    sig = pd.DataFrame({"buy": led["方向"] == "买入",
                        "sell": led["方向"] == "卖出"}).set_index(led["date"])
    return sig


# ---------------------------------------------------------------- 数据层

def load_kline(code):
    df = pd.read_csv(os.path.join(KLINE, f"{code}.csv"))
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def trading_calendar():
    return load_kline("sh000001").index


def load_amv_signals(start, end, buy_th, sell_th, entry_window="123",
                     exit_rule="drop"):
    """机械信号（干净 CSV 口径）。只用标签恰为真实交易日的行；
    累加和分量要求交易日历相邻，否则该分量作废。
    entry_window: "12"=max(当日,2日和)；"123"=max(当日,2日和,3日和)
    exit_rule: "drop"=当日<sell_th；"ma10"=0AMV收盘跌破MA10；"both"=任一触发。"""
    cal = trading_calendar()
    cal_pos = {d: i for i, d in enumerate(cal)}
    amv = pd.read_csv(os.path.join(HERE, "0amv_day.csv"))
    amv["d"] = (pd.to_datetime(amv["date"], utc=True)
                .dt.tz_convert("Asia/Shanghai").dt.tz_localize(None))
    amv = amv.set_index("d").sort_index()
    amv = amv[~amv.index.duplicated(keep="last")]
    amv_close = amv["close"]
    ma10 = amv_close.rolling(10).mean()

    rows = []
    for d, row in amv.iterrows():
        if d not in cal_pos:
            continue
        r = row["change_pct"] / 100.0 if pd.notna(row["change_pct"]) else np.nan
        rows.append((d, r))
    sig = []
    for i, (d, r) in enumerate(rows):
        if pd.isna(r) or d < pd.Timestamp(start) or d > pd.Timestamp(end):
            continue
        comps = [r]
        ks = (1,) if entry_window == "12" else (1, 2)
        for k in ks:
            if (i - k >= 0
                    and cal_pos[d] - cal_pos[rows[i - k][0]] == k
                    and not pd.isna(rows[i - k][1])):
                comps.append(sum(rows[i - j][1] for j in range(0, k + 1)))
        b = max(comps) > buy_th
        if exit_rule == "ma10":
            s = bool(pd.notna(ma10.get(d)) and amv_close.get(d) < ma10.get(d))
        elif exit_rule == "both":
            s = bool((r < sell_th) or (pd.notna(ma10.get(d))
                                       and amv_close.get(d) < ma10.get(d)))
        else:
            s = r < sell_th
        if b and s:
            b = False
        sig.append((d, b, s))
    return pd.DataFrame(sig, columns=["date", "buy", "sell"]).set_index("date")


# ---------------------------------------------------------------- 指标层

class Asset:
    def __init__(self, code):
        self.code = code
        self.df = load_kline(code)
        c = self.df["close"]
        self.ma20 = c.rolling(20).mean()
        self.ma60 = c.rolling(60).mean()
        self.ret20 = c.pct_change(20)
        self.ret1 = c.pct_change()
        self.ma200 = c.rolling(200).mean()
        self.listed_pos = {d: i for i, d in enumerate(self.df.index)}
        # 成交额估算（腾讯量为手）：手×100×收盘价，单位元
        self.amt20 = (self.df["volume"] * 100 * c).rolling(20).mean()
        # Chaikin 资金流代理：CLV = 收盘在当日振幅中的位置 (-1~+1)
        h, l, v = self.df["high"], self.df["low"], self.df["volume"]
        rng = (h - l).replace(0, np.nan)
        clv = (((c - l) - (h - c)) / rng).fillna(0.0)
        amt = v * 100 * c
        mfv = clv * amt
        # 当日净流入强度（相对自身20日正常量），20日累计净流入率
        self.mf1 = mfv / amt.rolling(20).mean()
        self.mf20 = mfv.rolling(20).sum() / amt.rolling(20).sum()

    def has(self, d):
        return d in self.listed_pos

    def pos(self, d):
        return self.listed_pos.get(d)


def corr60(a: Asset, b: Asset, d):
    """两资产截至 d 的 60 日日收益相关（按共同交易日）。"""
    ra = a.ret1.loc[:d].tail(61)
    rb = b.ret1.loc[:d].tail(61)
    j = pd.concat([ra, rb], axis=1, join="inner").dropna()
    if len(j) < 40:
        return np.nan
    return j.iloc[:, 0].corr(j.iloc[:, 1])


# ---------------------------------------------------------------- 漏斗

def funnel(d, assets, bench, prev_pick, prev_pick_rs, rs_window, top2_gap,
           min_listed=63, min_amt=0.0, rs_blend=False, spike_filter=False,
           topn="auto", rank_by="rs"):
    """返回 [(code, weight)]；空主线返回 []（调用方持有防守资产）。"""
    cands = []
    for code, a in assets.items():
        p = a.pos(d)
        if p is None or p < min_listed:
            continue
        if min_amt > 0 and (pd.isna(a.amt20.iloc[p]) or a.amt20.iloc[p] < min_amt):
            continue
        c = a.df["close"].iloc[p]
        if not (c > a.ma20.iloc[p] > a.ma60.iloc[p]):
            continue
        if spike_filter and p >= 22:
            r20 = c / a.df["close"].iloc[p - rs_window] - 1
            r2 = c / a.df["close"].iloc[p - 2] - 1
            if r20 > 0.05 and r2 / r20 > 0.6:
                continue
        if rs_window != 20:
            r = a.df["close"].iloc[p] / a.df["close"].iloc[p - rs_window] - 1
        else:
            r = a.ret20.iloc[p]
        br = bench.ret20.iloc[bench.pos(d)] if rs_window == 20 else (
            bench.df["close"].iloc[bench.pos(d)]
            / bench.df["close"].iloc[bench.pos(d) - rs_window] - 1)
        rs = r - br
        if rs_blend:
            bp = bench.pos(d)
            rs10 = (c / a.df["close"].iloc[p - 10] - 1) - \
                   (bench.df["close"].iloc[bp] / bench.df["close"].iloc[bp - 10] - 1)
            rs40 = (c / a.df["close"].iloc[p - 40] - 1) - \
                   (bench.df["close"].iloc[bp] / bench.df["close"].iloc[bp - 40] - 1)
            rs = (rs10 + rs + rs40) / 3
        if rank_by == "mf1":
            key = a.mf1.iloc[p]
        elif rank_by == "mf20":
            key = a.mf20.iloc[p]
        else:
            key = rs
        if pd.isna(key):
            continue
        cands.append((code, key, rs))
    cands = [x for x in cands if x[1] > 0]           # 层5 空主线保护
    if not cands:
        return []
    cands.sort(key=lambda x: -x[1])
    picked = []                                       # 层4 相关性去重
    for code, key, rs in cands:
        if any(abs(corr60(assets[code], assets[q], d)) > 0.9
               for q, _, _ in picked):
            continue
        picked.append((code, key, rs))
        if len(picked) >= 5:
            break
    if not picked:
        return []
    if prev_pick and picked[0][0] == prev_pick and picked[0][2] <= (prev_pick_rs or 0):
        if len(picked) > 1:                           # 层6 接力约束
            picked = picked[1:]
    top = picked[0]
    if str(topn) == "2" and len(picked) > 1:
        return [(picked[0][0], 0.5), (picked[1][0], 0.5)]
    if str(topn) == "3" and len(picked) > 2:
        return [(picked[0][0], 1/3), (picked[1][0], 1/3), (picked[2][0], 1/3)]
    if len(picked) > 1 and top[2] - picked[1][2] < top2_gap:
        return [(top[0], 0.5), (picked[1][0], 0.5)]   # 层7 分散
    return [(top[0], 1.0)]


# ---------------------------------------------------------------- 上下文（可复用）

class Context:
    def __init__(self, start, end, benchmark="sh000001"):
        cal = trading_calendar()
        self.cal = cal[(cal >= pd.Timestamp(start)) & (cal <= pd.Timestamp(end))]
        self.bench_map = {b: Asset(b) for b in ("sh000001", "sh000985")}
        self.defense = Asset(DEFENSE)
        self.defense_px = Asset(DEFENSE_PROXY)
        self.cash = Asset(CASH_ASSET)
        uni = pd.read_csv(os.path.join(HERE, "data", "etf_universe.csv"))
        codes = uni.loc[uni.cat == "行业主题", "code"].tolist()
        self.assets = {}
        for c in codes:
            fp = os.path.join(KLINE, f"{c}.csv")
            if os.path.exists(fp) and os.path.getsize(fp) > 100:
                self.assets[c] = Asset(c)
        self.n_universe = len(codes)
        self.start, self.end = start, end


# ---------------------------------------------------------------- 回测主循环

def run_bt(ctx: Context, args, collect=False):
    cal, bench = ctx.cal, ctx.bench_map[args.benchmark]
    defense, defense_px, cash = ctx.defense, ctx.defense_px, ctx.cash
    assets = ctx.assets
    if getattr(args, "signals", "ledger") == "ledger":
        sig = load_ledger_signals(ctx.start, ctx.end)
    else:
        sig = load_amv_signals(ctx.start, ctx.end, args.buy_th, args.sell_th,
                               getattr(args, "entry_window", "12"),
                               getattr(args, "exit_rule", "drop"))

    def px(a: Asset, d, kind):
        if a.has(d):
            return a.df[kind].loc[d]
        return np.nan

    def defense_asset_at(d):
        """防守腿实际持有资产（含可选熔断）。返回 Asset。"""
        if args.defense_overlay == "ma200":
            p = defense.pos(d)
            if p is not None and p >= 200:
                if defense.df["close"].iloc[p] < defense.ma200.iloc[p]:
                    return cash
        return defense if defense.has(d) else defense_px

    nav = 1.0
    state = "D"
    pos = {}            # code -> shares
    prev_pick, prev_pick_rs = None, None
    pending = None      # (action, targets, rs_map)
    nav_rows, seg_rows = [], []
    cur_seg = None
    last_prices = {}
    seg_day = 0

    def mark(d):
        v = 0.0
        for code, sh in pos.items():
            p = px(assets.get(code) or (defense if code == DEFENSE else
                 cash if code == CASH_ASSET else defense_px), d, "close")
            if np.isnan(p):
                p = last_prices.get(code, np.nan)
            if np.isnan(p):
                raise ValueError(f"{code} 在 {d.date()} 无价")
            v += sh * p
        return v

    def do_trade(d, targets, kind):
        """按 targets {code: weight} 全量换仓，扣双边成本。"""
        nonlocal nav, pos
        first = len(pos) == 0
        v = nav if first else mark(d)
        turnover_in = sum(targets.values())
        sell_leg = 0.0 if first else 1.0
        cost_rate = args.cost * (sell_leg + min(turnover_in, 1.0))
        v *= (1 - cost_rate)
        new_pos = {}
        for code, w in targets.items():
            a = assets.get(code) or (defense if code == DEFENSE else
                                     cash if code == CASH_ASSET else defense_px)
            p = px(a, d, kind)
            if np.isnan(p):  # 标的数据缺口 → 该腿退守防守资产
                a2 = defense if defense.has(d) else defense_px
                p = px(a2, d, kind)
                code = a2.code
            new_pos[code] = new_pos.get(code, 0.0) + v * w / p
            last_prices[code] = p
        pos = new_pos
        nav = v

    for d in cal:
        if d == cal[0] and not pos:
            da0 = defense_asset_at(d)
            do_trade(d, {da0.code: 1.0}, args.exec_price)
        # 先执行昨日收盘信号产生的交易
        if pending is not None:
            act, targets, rs_map = pending
            pending = None
            if act == "enter":
                if targets:
                    do_trade(d, dict(targets), args.exec_price)
                    cur_seg = {"entry_sig": sig_d.date(), "entry": d.date(),
                               "picks": [(c, w, rs_map.get(c)) for c, w in targets],
                               "entry_nav": nav}
                    prev_pick = targets[0][0]
                    prev_pick_rs = rs_map.get(prev_pick)
                    state = "A"
                    seg_day = 0
                else:  # 空主线：持有防守资产
                    da = defense_asset_at(d)
                    if set(pos) != {da.code}:
                        do_trade(d, {da.code: 1.0}, args.exec_price)
                    cur_seg = {"entry_sig": sig_d.date(), "entry": d.date(),
                               "picks": [], "entry_nav": nav, "empty_mainline": True}
                    state = "A"
            elif act == "exit":
                da = defense_asset_at(d)
                if set(pos) != {da.code}:
                    do_trade(d, {da.code: 1.0}, args.exec_price)
                if cur_seg is not None:
                    cur_seg["exit_sig"] = sig_d.date()
                    cur_seg["exit"] = d.date()
                    cur_seg["exit_nav"] = nav
                    cur_seg["ret"] = nav / cur_seg["entry_nav"] - 1
                    seg_rows.append(cur_seg)
                    cur_seg = None
                state = "D"

        # 进攻态第5n个交易日：重排漏斗，换仓（滞后阈值防反复）
        if state == "A" and getattr(args, "rerank5", 0) and pending is None:
            seg_day += 1
            if seg_day % 5 == 0:
                targets = funnel(d, assets, bench, None, None,
                                 args.rs_window, args.top2_gap,
                                 min_amt=getattr(args, "min_amt", 0.0),
                                 rs_blend=getattr(args, "rs_blend", False),
                                 spike_filter=getattr(args, "spike_filter", False),
                                 topn=getattr(args, "topn", "auto"))
                if targets:
                    cur_codes = set(pos.keys())
                    new_codes = {c for c, _ in targets}
                    if new_codes != cur_codes:
                        # 滞后：新冠军RS须超出现持第一名 3pp 才换
                        cur_rs = []
                        for cc in cur_codes:
                            a = assets.get(cc)
                            if a is None or a.pos(d) is None:
                                continue
                            p_ = a.pos(d)
                            r_ = a.df["close"].iloc[p_] / a.df["close"].iloc[p_ - args.rs_window] - 1
                            bp = bench.pos(d)
                            br_ = bench.df["close"].iloc[bp] / bench.df["close"].iloc[bp - args.rs_window] - 1
                            cur_rs.append(r_ - br_)
                        # funnel 不返回 rs，重算新冠军 RS
                        a = assets[targets[0][0]]
                        p_ = a.pos(d)
                        bp = bench.pos(d)
                        new_rs = (a.df["close"].iloc[p_] / a.df["close"].iloc[p_ - args.rs_window] - 1) - \
                                 (bench.df["close"].iloc[bp] / bench.df["close"].iloc[bp - args.rs_window] - 1)
                        if not cur_rs or new_rs > max(cur_rs) + 0.03:
                            do_trade(d, dict(targets), "close")

        # 防守态熔断（每日检查，仅 defense_overlay 开启时）
        if state == "D" and args.defense_overlay == "ma200":
            da = defense_asset_at(d)
            if set(pos) != {da.code} and d > cal[0]:
                do_trade(d, {da.code: 1.0}, "close")

        # 收盘后判定信号
        if d in sig.index:
            row = sig.loc[d]
            if state == "D" and row["buy"]:
                targets = funnel(d, assets, bench, prev_pick, prev_pick_rs,
                                 args.rs_window, args.top2_gap,
                                 min_amt=getattr(args, "min_amt", 0.0),
                                 rs_blend=getattr(args, "rs_blend", False),
                                 spike_filter=getattr(args, "spike_filter", False),
                                 topn=getattr(args, "topn", "auto"),
                                 rank_by=getattr(args, "rank_by", "rs"))
                rs_map = {}
                for code, w in targets:
                    a = assets[code]
                    p = a.pos(d)
                    r20 = a.df["close"].iloc[p] / a.df["close"].iloc[p - args.rs_window] - 1
                    br = bench.df["close"].iloc[bench.pos(d)] / \
                        bench.df["close"].iloc[bench.pos(d) - args.rs_window] - 1
                    rs_map[code] = r20 - br
                pending = ("enter", targets, rs_map)
                sig_d = d
            elif state == "A" and row["sell"]:
                pending = ("exit", None, None)
                sig_d = d

        nav = mark(d)
        nav_rows.append((d, nav, state))

    if cur_seg is not None:
        cur_seg["exit"] = cal[-1].date()
        cur_seg["exit_nav"] = nav
        cur_seg["ret"] = nav / cur_seg["entry_nav"] - 1
        cur_seg["open_end"] = True
        seg_rows.append(cur_seg)

    if collect:
        nv = pd.DataFrame(nav_rows, columns=["date", "nav", "state"]).set_index("date")
        return nv, pd.DataFrame(seg_rows)
    report(nav_rows, seg_rows, cal, defense, defense_px, args)


# ---------------------------------------------------------------- 报告

def report(nav_rows, seg_rows, cal, defense, defense_px, args):
    nv = pd.DataFrame(nav_rows, columns=["date", "nav", "state"]).set_index("date")
    nv.to_csv(os.path.join(OUT, "equity_curve.csv"))
    seg = pd.DataFrame(seg_rows)
    seg.to_csv(os.path.join(OUT, "segments.csv"), index=False)

    total = nv.nav.iloc[-1] - 1
    yrs = (nv.index[-1] - nv.index[0]).days / 365.25
    cagr = nv.nav.iloc[-1] ** (1 / yrs) - 1
    mdd = (nv.nav / nv.nav.cummax() - 1).min()
    calmar = cagr / abs(mdd) if mdd < 0 else np.nan
    atk = nv[nv.state == "A"]
    share = len(atk) / len(nv)
    wins = seg[seg.ret > 0].shape[0] if len(seg) else 0

    print("\n===== 回测结果 =====")
    print(f"区间 {nv.index[0].date()} ~ {nv.index[-1].date()}")
    print(f"累计 {total:+.1%}  年化 {cagr:.1%}  最大回撤 {mdd:.1%}  Calmar {calmar:.2f}")
    print(f"进攻时间占比 {share:.0%}  进攻段 {len(seg)} 胜率 "
          f"{wins}/{len(seg)} = {(wins/len(seg) if len(seg) else 0):.0%}")
    print("\n分年收益:")
    for y in range(nv.index[0].year, nv.index[-1].year + 1):
        w = nv[nv.index.year == y]
        if len(w) > 5:
            print(f"  {y}: {w.nav.iloc[-1]/w.nav.iloc[0]-1:+.1%}")

    tag = f"exec={args.exec_price} cost={args.cost} rs={args.rs_window} " \
          f"buy={args.buy_th} sell={args.sell_th} overlay={args.defense_overlay}"
    with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({"config": tag, "total": total, "cagr": cagr, "mdd": mdd,
                   "calmar": calmar, "attack_share": share,
                   "n_segments": len(seg)}, f, ensure_ascii=False, indent=1)
    print(f"\n已输出 outputs/equity_curve.csv, segments.csv, summary.json")
    print(f"配置: {tag}")
    src = "台账" if getattr(args, "signals", "ledger") == "ledger" else "CSV修复版(暂定)"
    print(f"声明: 宇宙为当前在册ETF(有幸存者偏差)；信号源={src}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2019-01-01")
    p.add_argument("--end", default="2026-10-09")
    p.add_argument("--exec-price", choices=["close", "open"], default="close")
    p.add_argument("--cost", type=float, default=0.001)
    p.add_argument("--rs-window", type=int, default=20)
    p.add_argument("--buy-th", type=float, default=0.04)
    p.add_argument("--sell-th", type=float, default=-0.023)
    p.add_argument("--top2-gap", type=float, default=0.02)
    p.add_argument("--benchmark", default="sh000001")
    p.add_argument("--defense-overlay", choices=["none", "ma200"], default="none")
    p.add_argument("--signals", choices=["ledger", "csv"], default="ledger")
    p.add_argument("--entry-window", choices=["12", "123"], default="12")
    p.add_argument("--exit-rule", choices=["drop", "ma10", "both"], default="drop")
    p.add_argument("--min-amt", type=float, default=0.0,
                   help="20日均成交额下限（元），0=不过滤")
    p.add_argument("--rerank5", type=int, default=0, help="进攻态每5日重排换仓")
    p.add_argument("--rs-blend", action="store_true", help="RS=10/20/40日等权")
    p.add_argument("--spike-filter", action="store_true", help="剔除脉冲式上涨候选")
    p.add_argument("--topn", choices=["auto", "2", "3"], default="auto")
    p.add_argument("--rank-by", choices=["rs", "mf1", "mf20"], default="rs")
    args = p.parse_args()
    ctx = Context(args.start, args.end, args.benchmark)
    print(f"宇宙加载 {len(ctx.assets)} 只有效（清单 {ctx.n_universe} 只）")
    run_bt(ctx, args)


if __name__ == "__main__":
    main()
