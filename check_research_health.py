"""Check recorded research risks; not a live signal or trading readiness check."""

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def inspect_summary(summary):
    if not isinstance(summary.get("asof"), str):
        raise ValueError("Missing research timestamp")
    baseline = next((row for row in summary.get("results", [])
                     if row.get("variant") == "baseline" and row.get("cost") == .001
                     and "periods" in row), None)
    if baseline is None:
        raise ValueError("Baseline result is unavailable")
    mdd = baseline["periods"]["full"].get("mdd")
    assumptions = baseline.get("valuation_assumptions")
    if not isinstance(mdd, (int, float)) or not math.isfinite(mdd) or mdd > 0:
        raise ValueError("Invalid historical drawdown")
    if not isinstance(assumptions, (int, float)) or not math.isfinite(assumptions) or assumptions < 0:
        raise ValueError("Missing or invalid valuation-assumption count")
    alerts = []
    if abs(mdd) > .30:
        alerts.append("AR01: historical drawdown exceeds 30%")
    if assumptions > 0:
        alerts.append("AR02: unresolved valuation assumptions exist")
    return {
        "asof": summary["asof"], "status": "alert" if alerts else "no_threshold_alert",
        "historical_mdd": mdd, "valuation_assumptions": assumptions, "alerts": alerts,
        "production_ready": False,
        "note": "No alerts does not prove trading readiness or future risk limits.",
    }


def select_source():
    runs = sorted((ROOT / "outputs/automatic_research").glob("*/summary.json"))
    if runs:
        return runs[-1]
    archives = sorted((ROOT / "results").glob("*-automatic-summary.json"))
    if archives:
        return archives[-1]
    raise ValueError("No research results; download-free checks require a sealed summary")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    try:
        source = args.summary or select_source()
        result = inspect_summary(json.loads(source.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"UNAVAILABLE: {error}")
        return 1
    print(f"RECORDED RESEARCH ONLY: {source}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result["alerts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
