#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""备胎验证2: baostock ETF / sina-qfq。"""
import sys

sys.stdout.reconfigure(encoding="utf-8")

try:
    import baostock as bs
    bs.login()
    rs = bs.query_history_k_data_plus(
        "sh.510150", "date,open,close,amount,adjustflag",
        start_date="2019-01-01", end_date="2026-10-09",
        frequency="d", adjustflag="2")
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    print(f"baostock ETF: err={rs.error_code} {rs.error_msg} rows={len(rows)}")
    if rows:
        print("  首行", rows[0], " 末行", rows[-1])
    bs.logout()
except Exception as e:
    print("baostock fail:", type(e).__name__, str(e)[:120])

try:
    import akshare as ak
    h = ak.stock_zh_a_daily(symbol="sh510150", adjust="qfq",
                            start_date="20180101", end_date="20261010")
    print(f"sina qfq OK {len(h)} 行 列:{list(h.columns)}")
    print(h.tail(2).to_string())
except Exception as e:
    print("sina qfq fail:", type(e).__name__, str(e)[:120])
