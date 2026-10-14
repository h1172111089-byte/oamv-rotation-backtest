"""Fixed automatic-selection experiments with input snapshots and audit outputs."""

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import bt
from accounting import equity_stats
from run_experiments import BASE
from run_window_exit import gen_signals, timing_bt

ROOT = Path(__file__).resolve().parent
PERIODS = {
    "full": ("2019-01-01", "2026-10-09"),
    "development": ("2019-01-01", "2023-12-31"),
    "historical_validation": ("2024-01-01", "2026-10-09"),
}
VARIANTS = {
    "baseline": ("none", "rs", "close"),
    "open_control": ("none", "rs", "open"),
    "amv_MA20_slope_positive": ("amv", "rs", "close"),
    "correlation_cluster_breadth_gt_50pct": ("breadth", "rs", "close"),
    "RS20_percentile_persistence_5days": ("none", "persistence", "close"),
    "correlation_cluster_median_RS20": ("none", "cluster", "close"),
    "correlation_cluster_median_persistence": ("none", "cluster_persistence", "close"),
}


def to_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def snapshot_inputs(context, run_id):
    destination = ROOT.parent / "10-数据" / "data" / "raw" / "automatic_research" / run_id
    destination.mkdir(parents=True, exist_ok=False)
    paths = [ROOT / "0amv_day.csv", ROOT / "0AMV活跃市值切换信号登记表.csv",
             ROOT / "data/etf_universe.csv", ROOT / "data/universe_meta.json",
             ROOT / "data/automatic_research_protocol.json"]
    paths += [ROOT / name for name in ("bt.py", "accounting.py", "study_automatic.py", "run_window_exit.py", "run_experiments.py")]
    codes = set(context.assets) | set(context.bench_map) | {bt.DEFENSE, bt.DEFENSE_PROXY, bt.CASH_ASSET}
    paths += [ROOT / "data/kline" / f"{code}.csv" for code in sorted(codes)]
    paths += [ROOT / "data/kline/sh000001_sina_long.csv"]
    manifest = []
    for source in paths:
        payload = source.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        target = destination / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(payload)
        manifest.append({"path": source.relative_to(ROOT).as_posix(), "sha256": digest, "bytes": len(payload)})
    to_json(destination / "manifest.json", {
        "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "source": "existing local Tencent qfq snapshots; original download metadata may be incomplete",
        "calendar_cutoff": str(context.cal[-1].date()), "inputs": manifest,
    })
    return str(destination), manifest


class Features:
    def __init__(self, context):
        self.context = context
        calendar = context.full_calendar
        close = pd.DataFrame({code: asset.df.close.reindex(calendar) for code, asset in context.assets.items()})
        runs = pd.DataFrame({
            code: pd.Series(asset.contiguous, index=asset.df.index).reindex(calendar)
            for code, asset in context.assets.items()
        })
        self.eligible = runs.ge(63)
        self.close = close
        self.ma20 = close.rolling(20).mean()
        self.ma60 = close.rolling(60).mean()
        self.returns = close.pct_change(fill_method=None)
        benchmark = context.bench_map["sh000001"].df.close.reindex(calendar)
        self.rs = close.pct_change(20, fill_method=None).sub(benchmark.pct_change(20, fill_method=None), axis=0)
        self.percentiles = self.rs.where(self.eligible).rank(axis=1, pct=True)
        self.persistence = self.percentiles.rolling(5).mean()
        amv = pd.read_csv(Path(context.input_root) / "0amv_day.csv")
        dates = pd.to_datetime(amv.date, utc=True).dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
        amv_close = pd.Series(amv.close.to_numpy(), index=dates).reindex(calendar)
        self.amv_slope = amv_close.rolling(20).mean().diff(5)
        self.cluster_cache = {}
        self.audit = {}

    def clusters(self, date):
        if date in self.cluster_cache:
            return self.cluster_cache[date]
        codes = self.eligible.columns[self.eligible.loc[date]].tolist()
        if not codes:
            self.cluster_cache[date] = []
            return []
        correlation = self.returns.loc[:date, codes].tail(60).corr(min_periods=60).to_numpy()
        parents = list(range(len(codes)))

        def find(index):
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index

        for left, right in zip(*np.where(np.triu(correlation > .9, k=1))):
            parents[find(int(right))] = find(int(left))
        grouped = {}
        for index, code in enumerate(codes):
            grouped.setdefault(find(index), []).append(code)
        result = list(grouped.values())
        self.cluster_cache[date] = result
        return result

    def candidates(self, date):
        trend = (self.close.loc[date] > self.ma20.loc[date]) & (self.ma20.loc[date] > self.ma60.loc[date])
        mask = self.eligible.loc[date] & trend & self.rs.loc[date].gt(0)
        return self.rs.columns[mask].tolist()

    def signal_allowed(self, date, method):
        if method == "none":
            return True
        if method == "amv":
            value = self.amv_slope.loc[date]
            allowed = bool(pd.notna(value) and value > 0)
            self.audit.setdefault(str(date.date()), {})["amv_slope_positive"] = allowed
            return allowed
        groups = self.clusters(date)
        above = [float((self.close.loc[date, group] > self.ma20.loc[date, group]).mean()) > .5 for group in groups]
        breadth = float(np.mean(above)) if above else 0.0
        self.audit.setdefault(str(date.date()), {})["correlation_cluster_breadth"] = breadth
        return breadth > .5

    def select(self, date, previous, previous_rs, method):
        assets = self.context.assets
        benchmark = self.context.bench_map["sh000001"]
        if method == "rs":
            return bt.funnel(date, assets, benchmark, previous, previous_rs, 20, .02)
        eligible = self.candidates(date)
        metric = self.persistence.loc[date] if "persistence" in method else self.rs.loc[date]
        if method.startswith("cluster"):
            scored = []
            for group in self.clusters(date):
                available = [code for code in group if code in eligible and pd.notna(metric.get(code))]
                if available:
                    score = float(metric[group].dropna().median())
                    if method == "cluster" and score <= 0:
                        continue
                    representative = sorted(available, key=lambda code: (-float(metric[code]), code))[0]
                    scored.append((representative, score))
        else:
            scored = [(code, float(metric[code])) for code in eligible if pd.notna(metric[code])]
        scored.sort(key=lambda item: (-item[1], item[0]))
        picked = []
        for code, score in scored:
            if any(abs(bt.corr60(assets[code], assets[other], date)) > .9 for other, value in picked):
                continue
            picked.append((code, score))
            if len(picked) == 5:
                break
        if previous and len(picked) > 1 and picked[0][0] == previous and float(self.rs.loc[date, previous]) <= (previous_rs or 0):
            picked = picked[1:]
        if not picked:
            return []
        self.audit.setdefault(str(date.date()), {})[method + "_ranking"] = [
            {"code": code, "score": score, "rs20": float(self.rs.loc[date, code])} for code, score in picked
        ]
        if len(picked) > 1 and abs(float(self.rs.loc[date, picked[0][0]]) - float(self.rs.loc[date, picked[1][0]])) < .02:
            return [(picked[0][0], .5), (picked[1][0], .5)]
        return [(picked[0][0], 1.0)]


def closed_segments(segments):
    if segments.empty:
        return segments
    mask = ~segments.get("open_end", pd.Series(False, index=segments.index)).fillna(False).astype(bool)
    mask &= ~segments.get("empty_mainline", pd.Series(False, index=segments.index)).fillna(False).astype(bool)
    return segments.loc[mask].copy()


def period_stats(nav, segments, lower, upper):
    sliced = nav.loc[lower:upper, "nav"]
    previous = nav.loc[nav.index < pd.Timestamp(lower), "nav"]
    initial = float(previous.iloc[-1]) if len(previous) else 1.0
    stats = equity_stats(sliced, initial)
    closed = closed_segments(segments)
    if len(closed):
        closed = closed[
            pd.to_datetime(closed.entry).ge(lower) & pd.to_datetime(closed.exit).le(upper)
        ]
    winners = closed.loc[closed.ret > 0, "ret"] if len(closed) else pd.Series(dtype=float)
    losers = closed.loc[closed.ret <= 0, "ret"] if len(closed) else pd.Series(dtype=float)
    stats.update({
        "closed_segments": len(closed), "win_rate": float((closed.ret > 0).mean()) if len(closed) else None,
        "mean_winner": float(winners.mean()) if len(winners) else None,
        "mean_loser": float(losers.mean()) if len(losers) else None,
        "profit_factor": float(winners.sum() / abs(losers.sum())) if len(losers) and losers.sum() < 0 else None,
        "attack_share": float(nav.loc[lower:upper, "state"].eq("A").mean()),
    })
    events = [event for event in nav.attrs.get("return_events", [])
              if lower <= event["date"] <= upper]
    factors = {
        leg: float(np.prod([event["factor"] for event in events if event["leg"] == leg]))
        for leg in ["attack", "defense", "cost"]
    }
    if events:
        if not np.isclose(np.prod(list(factors.values())), stats["total"] + 1, rtol=1e-9):
            raise ValueError("Attack/defense/cost factors do not reconcile")
        stats["leg_factors"] = factors
    return stats


def run_one(context, features, variant, cost, excluded=None):
    entry_filter, selection, execution = VARIANTS[variant]
    args = SimpleNamespace(**{
        **BASE, "signals": "csv", "entry_window": "12", "exit_rule": "drop",
        "cost": cost, "exec_price": execution, "valuation_policy": "previous-close",
    })
    excluded = excluded or set()
    return bt.run_bt(
        context, args, collect=True,
        signal_filter=lambda date: date not in excluded and features.signal_allowed(date, entry_filter),
        selector=lambda date, previous, strength: features.select(date, previous, strength, selection),
    )


def selection_diagnostics(context, features, results):
    if "baseline" not in results:
        return [], {"status": "blocked", "reason": "baseline failed"}
    baseline = closed_segments(results["baseline"][1])
    selected = {}
    for variant, (nav, segments) in results.items():
        selected[variant] = {
            str(row.entry_sig): row.picks for row in closed_segments(segments).itertuples()
        }
    rows = []
    for segment in baseline.itertuples():
        signal_date = pd.Timestamp(segment.entry_sig)
        entry, exit_date = pd.Timestamp(segment.entry), pd.Timestamp(segment.exit)
        future_returns = {}
        missing = []
        candidates = features.candidates(signal_date)
        for code in candidates:
            frame = context.assets[code].df
            expected_days = context.cal[(context.cal >= entry) & (context.cal <= exit_date)]
            if not expected_days.difference(frame.index).empty:
                missing.append(code)
                continue
            future_returns[code] = float(frame.loc[exit_date, "close"] / frame.loc[entry, "close"] - 1)
        population = pd.Series(future_returns, dtype=float)
        if population.empty:
            continue
        for variant in VARIANTS:
            if variant == "open_control" or variant not in selected:
                continue
            picks = selected[variant].get(str(segment.entry_sig), [])
            usable = bool(picks) and all(code in future_returns for code, weight, strength in picks)
            picked_return = sum(weight * future_returns[code] for code, weight, strength in picks) if usable else None
            rows.append({
                "variant": variant, "signal_date": str(signal_date.date()),
                "entry": str(entry.date()), "exit": str(exit_date.date()),
                "entered": bool(picks), "candidate_count_at_signal": len(candidates),
                "evaluation_coverage": len(future_returns), "missing_future_prices": len(missing),
                "picks": [{"code": code, "weight": weight} for code, weight, strength in picks],
                "selected_gross_return": picked_return,
                "candidate_median_return": float(population.median()),
                "beat_candidate_median": bool(picked_return >= population.median()) if usable else None,
                "top_quintile_hit": bool(picked_return >= population.quantile(.8)) if usable else None,
                "baseline_net_segment_return": float(segment.ret),
                "note": "事后评估标签，不参与选择；未覆盖未来价格者剔除并报告覆盖率",
            })
    grouped = {}
    for variant in VARIANTS:
        if variant not in results:
            grouped[variant] = {"status": "blocked"}
            continue
        observations = [row for row in rows if row["variant"] == variant]
        usable = [row for row in observations if row["selected_gross_return"] is not None]
        skipped = [row for row in observations if not row["entered"]]
        grouped[variant] = {
            "comparable_windows": len(observations), "evaluated_picks": len(usable),
            "beat_candidate_median_rate": float(np.mean([row["beat_candidate_median"] for row in usable])) if usable else None,
            "top_quintile_hit_rate": float(np.mean([row["top_quintile_hit"] for row in usable])) if usable else None,
            "skipped_windows": len(skipped),
            "skipped_baseline_profitable": sum(row["baseline_net_segment_return"] > 0 for row in skipped),
        }
    return rows, grouped


def research_gates(summaries, diagnostics):
    grouped = {(row["variant"], row["cost"]): row for row in summaries if "periods" in row}
    winner_rows = {row["variant"]: row for row in diagnostics if "stats" in row}
    gates = {}
    for variant in VARIANTS:
        if variant in {"baseline", "open_control"}:
            continue
        row = grouped.get((variant, .001))
        baseline = grouped.get(("baseline", .001))
        if row is None or baseline is None:
            gates[variant] = {"status": "blocked", "reason": "missing comparison"}
            continue
        checks = {
            "full_return_better": all(
                (variant, cost) in grouped and ("baseline", cost) in grouped
                and grouped[(variant, cost)]["periods"]["full"]["total"]
                    > grouped[("baseline", cost)]["periods"]["full"]["total"]
                for cost in [.001, .0015, .002]
            ),
            "historical_validation_better": all(
                (variant, cost) in grouped and ("baseline", cost) in grouped
                and grouped[(variant, cost)]["periods"]["historical_validation"]["total"]
                    > grouped[("baseline", cost)]["periods"]["historical_validation"]["total"]
                for cost in [.001, .0015, .002]
            ),
            "all_costs_mdd_within_30pct": all(
                (variant, cost) in grouped and grouped[(variant, cost)]["periods"]["full"]["mdd"] >= -.30
                for cost in [.001, .0015, .002]
            ),
            "winner_diagnostic_better": variant in winner_rows and "baseline" in winner_rows
                and winner_rows[variant]["stats"]["total"] > winner_rows["baseline"]["stats"]["total"],
        }
        complete = all((variant, cost) in grouped and ("baseline", cost) in grouped for cost in [.001, .0015, .002])
        complete = complete and variant in winner_rows and "baseline" in winner_rows
        gates[variant] = {"checks": checks, "research_status": "blocked" if not complete else "pass" if all(checks.values()) else "fail",
                          "production_status": "blocked", "reason": "valuation/PIT-data/forward evidence unresolved"}
    return gates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-stress", action="store_true")
    args = parser.parse_args()
    context = bt.Context("2019-01-01", "2026-10-09")
    run_id = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%dT%H%M%S")
    output = ROOT / "outputs" / "automatic_research" / run_id
    output.mkdir(parents=True, exist_ok=False)
    snapshot, manifest = snapshot_inputs(context, run_id)
    context = bt.Context("2019-01-01", "2026-10-09", input_root=snapshot)
    features = Features(context)
    summaries = []
    first_cost_results = {}
    baseline_segments = None
    costs = [.001] if args.skip_stress else [.001, .0015, .002]
    for cost in costs:
        for variant in VARIANTS:
            try:
                nav, segments = run_one(context, features, variant, cost)
            except ValueError as error:
                summaries.append({"variant": variant, "cost": cost, "error": str(error)})
                print("BLOCKED", variant, cost, str(error), flush=True)
                continue
            folder = output / f"{variant}_{cost}"
            folder.mkdir()
            nav.to_csv(folder / "equity.csv")
            segments.to_csv(folder / "segments.csv", index=False)
            to_json(folder / "transactions.json", nav.attrs["transactions"])
            to_json(folder / "valuation_assumptions.json", nav.attrs["valuation_warnings"])
            to_json(folder / "return_events.json", nav.attrs["return_events"])
            periods = {name: period_stats(nav, segments, *span) for name, span in PERIODS.items()}
            row = {"variant": variant, "cost": cost, "periods": periods,
                   "valuation_assumptions": len(nav.attrs["valuation_warnings"])}
            summaries.append(row)
            if variant == "baseline" and cost == .001:
                baseline_segments = closed_segments(segments)
            if cost == .001:
                first_cost_results[variant] = (nav, segments)
            print(variant, cost, json.dumps(periods["full"], ensure_ascii=False), flush=True)
    diagnostics = []
    if baseline_segments is not None and len(baseline_segments):
        excluded = set(pd.to_datetime(baseline_segments.nlargest(3, "ret").entry_sig))
        for variant in VARIANTS:
            if variant == "open_control":
                continue
            try:
                nav, segments = run_one(context, features, variant, .001, excluded)
                diagnostics.append({"variant": variant, "excluded_baseline_top3_entry_dates": [
                    str(date.date()) for date in sorted(excluded)],
                    "stats": period_stats(nav, segments, *PERIODS["full"])})
            except ValueError as error:
                diagnostics.append({"variant": variant, "error": str(error)})
    long_prices = pd.read_csv(Path(snapshot) / "data/kline/sh000001_sina_long.csv")
    long_prices["date"] = pd.to_datetime(long_prices.date)
    long_prices = long_prices.set_index("date").sort_index()
    timing = []
    for span, lower in [("2012_to_cutoff", "2012-01-04"), ("2019_to_cutoff", "2019-01-01")]:
        for window in ["12", "123"]:
            for exit_rule in ["drop", "ma10"]:
                signals = gen_signals(lower, "2026-10-09", .04, -.023, window, exit_rule, snapshot)
                timing.append({"period": span, "window": window, "exit": exit_rule,
                               "stats": timing_bt(signals, long_prices, lower, "2026-10-09")})
    diagnostic_rows, diagnostic_summary = selection_diagnostics(context, features, first_cost_results)
    to_json(output / "selection_diagnostics.json", diagnostic_rows)
    to_json(output / "summary.json", {
        "asof": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(), "snapshot": snapshot,
        "protocol_sha256": next(item["sha256"] for item in manifest if item["path"].endswith("protocol.json")),
        "loaded_price_files": len(context.assets), "catalog_count": context.n_universe,
        "results": summaries, "winner_diagnostics": diagnostics, "timing_only": timing,
        "selection_diagnostics": diagnostic_summary,
        "research_gates": research_gates(summaries, diagnostics),
        "feature_audit": features.audit, "production_ready": False,
    })
    print("OUTPUT", output, flush=True)


if __name__ == "__main__":
    main()
