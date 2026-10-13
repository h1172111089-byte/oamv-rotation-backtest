#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据源探测：名单与历史行情各通路可用性。"""
import re
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
UA = {"User-Agent": "Mozilla/5.0"}

# 探测1: 东财基金名单静态JS（非push2主机）
try:
    d = urllib.request.urlopen(
        urllib.request.Request("http://fund.eastmoney.com/js/fundcode_search.js",
                               headers=UA), timeout=15).read()
    t = d.decode("utf-8", errors="ignore")
    items = re.findall(r'\["(\d{6})","[^"]*","([^"]+)","([^"]*)"', t)
    etfs = [x for x in items if x[2] and "ETF" in x[2]]
    print(f"probe1 fundcode_search.js OK  总基金 {len(items)}  场内ETF {len(etfs)}")
    print("  样例:", etfs[:3])
except Exception as e:
    print("probe1 fail:", type(e).__name__, str(e)[:150])

# 探测2: akshare东财ETF历史行情（push2his主机）
try:
    import akshare as ak
    h = ak.fund_etf_hist_em(symbol="512890", period="daily",
                            start_date="20190101", end_date="20261010", adjust="qfq")
    print(f"probe2 fund_etf_hist_em OK  {len(h)} 行  列: {list(h.columns)}")
    print(h.tail(2).to_string())
except Exception as e:
    print("probe2 fail:", type(e).__name__, str(e)[:150])

# 探测3: 腾讯历史行情补amount验证（ETF行是否带成交额字段）
try:
    u = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
         "param=sh512890,day,2026-10-01,2026-10-10,10,qfq")
    d = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=15).read()
    print("probe3 腾讯ETF行:", d[:300])
except Exception as e:
    print("probe3 fail:", type(e).__name__, str(e)[:150])

# 探测1b: 细看 fundcode_search.js 中名称含 ETF 的条目结构
try:
    d = urllib.request.urlopen(
        urllib.request.Request("http://fund.eastmoney.com/js/fundcode_search.js",
                               headers=UA), timeout=15).read()
    t = d.decode("utf-8", errors="ignore")
    items = re.findall(r'\["(\d{6})","([^"]*)","([^"]+)","([^"]*)"', t)
    etfs = [x for x in items if "ETF" in x[2]]
    print(f"probe1b 名称含ETF: {len(etfs)}")
    from collections import Counter
    print("  type分布:", Counter(x[3] for x in etfs).most_common(8))
    for x in etfs[:5]:
        print("  ", x)
except Exception as e:
    print("probe1b fail:", type(e).__name__, str(e)[:150])
