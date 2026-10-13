#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""限流恢复探测 + 大count单请求可行性 + 新浪备胎验证。"""
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

t = time.time()
try:
    u = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
         "param=sh510150,day,2018-01-01,2026-10-10,2000,qfq")
    d = urllib.request.urlopen(urllib.request.Request(u, headers=UA),
                               timeout=15).read()
    import json
    js = json.loads(d)
    rows = js["data"]["sh510150"].get("qfqday") or js["data"]["sh510150"]["day"]
    print(f"腾讯恢复! count=2000 实际返回 {len(rows)} 行 "
          f"{rows[0][0]}~{rows[-1][0]}  耗时{time.time()-t:.1f}s")
except Exception as e:
    print("腾讯仍未恢复:", type(e).__name__, str(e)[:100])

try:
    import akshare as ak
    h = ak.fund_etf_hist_sina(symbol="sh510150")
    print(f"新浪ETF OK {len(h)} 行 列:{list(h.columns)}")
    print(h.tail(2).to_string())
except Exception as e:
    print("新浪 fail:", type(e).__name__, str(e)[:120])
