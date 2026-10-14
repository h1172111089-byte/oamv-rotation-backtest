"""Offline regression checks; no market downloads or brokerage connections."""

import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd

import bt
from accounting import equity_stats, rebalance
from check_research_health import inspect_summary
from package_research_results import package_summary
from run_window_exit import timing_bt
from study_automatic import research_gates, selection_diagnostics

ROOT = Path(__file__).resolve().parent


class PriceAsset:
    def __init__(self, code, dates, prices):
        self.code = code
        self.df = pd.DataFrame({"open": prices, "close": prices}, index=dates)
        self.positions = {date: index for index, date in enumerate(dates)}

    def has(self, date):
        return date in self.positions

    def pos(self, date):
        return self.positions.get(date)


def execution_checks():
    dates = pd.bdate_range("2020-01-01", periods=25)
    attack = PriceAsset("attack", dates, [100.0] * 25)
    defense = PriceAsset(bt.DEFENSE, dates, [100.0] * 25)
    defense.df.loc[dates[-2], "close"] = 110.0
    benchmark = PriceAsset("sh000001", dates, [100.0] * 25)
    context = SimpleNamespace(
        cal=dates[-3:], bench_map={"sh000001": benchmark}, defense=defense,
        defense_px=defense, cash=defense, assets={"attack": attack},
        start=str(dates[-3].date()), end=str(dates[-1].date()),
    )
    args = SimpleNamespace(
        benchmark="sh000001", signals="ledger", buy_th=.04, sell_th=-.023,
        defense_overlay="none", cost=0.0, exec_price="open", rs_window=20, top2_gap=.02,
    )
    signals = pd.DataFrame({"buy": [True, False, False], "sell": [False]*3}, index=dates[-3:])
    with patch.object(bt, "load_ledger_signals", return_value=signals), patch.object(
        bt, "funnel", return_value=[("attack", 1.0)]
    ):
        nav, segments = bt.run_bt(context, args, collect=True)
        assert np.isclose(nav.loc[dates[-2], "nav"], 1.0)
        veto_nav, veto_segments = bt.run_bt(context, args, collect=True, signal_filter=lambda date: False)
        assert veto_segments.empty and len(veto_nav.attrs["transactions"]) == 1
    prices = pd.DataFrame({"close": [100.0, 110.0, 110.0]}, index=dates[-3:])
    actual = timing_bt(signals, prices, context.start, context.end)["累计"]
    cash = 1.02 ** (1 / 244) - 1
    assert np.isclose(actual, (1 + cash) / (1 + .001) - 1)
    defense.df.loc[dates[-1], "close"] = np.nan
    no_signals = signals.copy()
    no_signals["buy"] = False
    with patch.object(bt, "load_ledger_signals", return_value=no_signals):
        try:
            bt.run_bt(context, args, collect=True)
        except ValueError:
            pass
        else:
            raise AssertionError("Missing valuation must fail in strict mode")
        permissive = SimpleNamespace(**{**vars(args), "valuation_policy": "previous-close"})
        nav, segments = bt.run_bt(context, permissive, collect=True)
        assert len(nav.attrs["valuation_warnings"]) == 1


def accounting_checks():
    shares, net, fees, turnover = rebalance({}, 1.0, {"a": 1.0}, {"a": 100.0}, .001)
    assert np.isclose(net, 1 / 1.001)
    same, same_net, same_fees, same_turnover = rebalance(shares, 0, {"a": 1}, {"a": 100}, .001)
    assert np.isclose(same_fees, 0)
    shares, net, fees, turnover = rebalance({"a": .005, "b": .005}, 0, {"a": 1}, {"a": 100, "b": 100}, .001)
    assert np.isclose(fees, .001 * (.5 + abs(net - .5))) and np.isclose(net + fees, 1)
    nav = pd.Series([1.1, 1.21, 1.331], index=pd.to_datetime(["2019-12-31", "2020-01-02", "2020-12-31"]))
    stats = equity_stats(nav)
    assert np.isclose(stats["yearly"]["2020"], .21)
    assert np.isclose(np.prod([1 + value for value in stats["yearly"].values()]), nav.iloc[-1])


def gate_checks():
    assert selection_diagnostics(None, None, {})[1]["status"] == "blocked"
    assert research_gates([], [])["amv_MA20_slope_positive"]["status"] == "blocked"
    rows = []
    for variant in ["baseline", "amv_MA20_slope_positive"]:
        for cost in [.001, .0015, .002]:
            total = 1 if variant == "baseline" else 2 if cost == .001 else .5
            rows.append({
                "variant": variant, "cost": cost,
                "periods": {"full": {"total": total, "mdd": -.1}, "historical_validation": {"total": total}},
            })
    diagnostic = [{"variant": variant, "stats": {"total": total}}
                  for variant, total in [("baseline", 1), ("amv_MA20_slope_positive", 2)]]
    assert research_gates(rows, diagnostic)["amv_MA20_slope_positive"]["research_status"] == "fail"
    assert research_gates(rows[:-1], diagnostic)["amv_MA20_slope_positive"]["research_status"] == "blocked"


def packaging_checks():
    directory = ROOT / "outputs" / f"regression-{uuid.uuid4().hex}"
    if not directory.resolve().is_relative_to((ROOT / "outputs").resolve()):
        raise ValueError("Regression artifacts must stay in this workspace")
    directory.mkdir(parents=True, exist_ok=False)
    if directory.exists():
        root = directory
        snapshot = root / "snap"
        snapshot.mkdir()
        manifest = {"created_at": "2026-10-14", "inputs": [{"path": "bt.py", "sha256": "0"*64, "bytes": 1}]}
        (snapshot / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        summary = {
            "asof": "2026-10-14", "snapshot": str(snapshot), "protocol_sha256": "0"*64,
            "production_ready": False, "loaded_price_files": 1, "catalog_count": 1,
            "feature_audit": {"large": "not exported"},
            "results": [{"variant": "baseline", "cost": .001, "valuation_assumptions": 1,
                         "periods": {"full": {"mdd": -.301, "total": 1.0}}}],
            "research_gates": {}, "winner_diagnostics": [], "timing_only": [],
            "selection_diagnostics": {},
        }
        source = root / "summary.json"
        source.write_text(json.dumps(summary), encoding="utf-8")
        package = package_summary(source)
        assert "snapshot" not in package and "feature_audit" not in package
        assert package["input_manifest"] == manifest
        assert len(package["provenance"]["source_summary_sha256"]) == 64
        health = inspect_summary(package)
        assert health["status"] == "alert" and len(health["alerts"]) == 2
        try:
            inspect_summary({"asof": "today", "results": []})
        except ValueError:
            pass
        else:
            raise AssertionError("Missing baseline must be reported as unavailable")


def delivery_checks():
    package_path = ROOT / "results/2026-10-14-automatic-summary.json"
    summary = json.loads(package_path.read_text(encoding="utf-8"))
    assert summary["production_ready"] is False
    assert len(summary["results"]) == 21
    for result in summary["results"]:
        for stats in result["periods"].values():
            assert np.isclose(np.prod(list(stats["leg_factors"].values())), 1 + stats["total"])
            assert np.isclose(np.prod([1 + value for value in stats["yearly"].values()]), 1 + stats["total"])
    skill = (ROOT / "agents/backtest-workflow/SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: backtest-workflow\n")
    assert "不可修订" in skill and "旧“开盘已采纳”" in skill
    for path in ROOT.glob("*.py"):
        compile(path.read_text(encoding="utf-8-sig"), str(path), "exec")


def main():
    checks = [execution_checks, accounting_checks, gate_checks, packaging_checks, delivery_checks]
    for check in checks:
        check()
        print(f"PASS: {check.__name__}")
    print("All five offline verification groups passed.")


if __name__ == "__main__":
    main()
