"""Self-financing portfolio accounting and reconcilable performance statistics."""

import numpy as np
import pandas as pd


def portfolio_value(positions, cash, prices):
    for code, shares in positions.items():
        price = prices.get(code)
        if shares < 0 or price is None or not np.isfinite(price) or price <= 0:
            raise ValueError(f"Missing or invalid executable price: {code}")
    return float(cash + sum(shares * prices[code] for code, shares in positions.items()))


def rebalance(positions, cash, targets, prices, cost):
    if not 0 <= cost < 1 or any(weight < 0 for weight in targets.values()):
        raise ValueError("Invalid cost or target weight")
    if not np.isclose(sum(targets.values()), 1):
        raise ValueError("Target weights must sum to one")
    for code in targets:
        if code not in prices or not np.isfinite(prices[code]) or prices[code] <= 0:
            raise ValueError(f"Missing executable target price: {code}")
    before = portfolio_value(positions, cash, prices)
    codes = set(positions) | set(targets)
    old_values = {code: positions.get(code, 0) * prices[code] for code in codes}

    def traded_value(net):
        return sum(abs(targets.get(code, 0) * net - old_values[code]) for code in codes)

    lower, upper = 0.0, before
    for iteration in range(64):
        middle = (lower + upper) / 2
        if middle + cost * traded_value(middle) > before:
            upper = middle
        else:
            lower = middle
    net = (lower + upper) / 2
    traded = traded_value(net)
    fees = cost * traded
    if not np.isclose(before, net + fees, atol=1e-10, rtol=1e-10):
        raise ValueError("Self-financing identity failed")
    new_positions = {code: net * weight / prices[code] for code, weight in targets.items()}
    return new_positions, net, fees, traded / before if before else 0.0


def equity_stats(nav, initial=1.0):
    nav = nav.astype(float)
    if nav.empty or initial <= 0 or (nav <= 0).any() or not np.isfinite(nav).all():
        raise ValueError("Invalid equity series")
    daily = nav.pct_change(fill_method=None)
    daily.iloc[0] = nav.iloc[0] / initial - 1
    yearly = (1 + daily).groupby(nav.index.year).prod() - 1
    peak = nav.cummax().clip(lower=initial)
    mdd = float((nav / peak - 1).min())
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    cagr = float((nav.iloc[-1] / initial) ** (1 / years) - 1) if years > 0 else None
    return {
        "total": float(nav.iloc[-1] / initial - 1), "cagr": cagr,
        "mdd": mdd, "calmar": cagr / abs(mdd) if mdd < 0 and cagr is not None else None,
        "yearly": {str(year): float(value) for year, value in yearly.items()},
    }
