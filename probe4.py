#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新浪分红拆分事件数据验证：能否自建复权因子。"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
import akshare as ak

for code in ["sh510150", "sh512880", "sh512890"]:
    for fn, name in [(ak.fund_etf_dividend_sina, "分红")]:
        try:
            d = fn(symbol=code)
            print(f"{code} {name}: {len(d)} 行 列:{list(d.columns)}")
            if len(d):
                print(d.to_string())
        except Exception as e:
            print(f"{code} {name} fail:", type(e).__name__, str(e)[:100])
    print("---")
