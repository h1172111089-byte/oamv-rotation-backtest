#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量抓取宇宙全部 ETF 前复权日线（腾讯源，支持断点续传）。

  - 已完成（kline csv 存在且行数>0）的代码自动跳过
  - 原始响应落 data/raw/universe/（带 sha256），解析合并入 data/kline/{code}.csv
  - 失败列表写 data/fetch_failures.txt，重跑即补
"""

import hashlib
import json
import os
import sys
import time
import urllib.request
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "data", "raw", "universe")
KLINE = os.path.join(HERE, "data", "kline")
os.makedirs(RAW, exist_ok=True)
os.makedirs(KLINE, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (compatible; research-backtest)"}
CHUNKS = [("2018-01-01", "2020-12-31"), ("2021-01-01", "2023-12-31"),
          ("2024-01-01", "2026-10-10")]
HOSTS = ["https://web.ifzq.gtimg.cn", "https://proxy.finance.qq.com"]


def fetch(code, start, end):
    for att in range(3):
        host = HOSTS[att % len(HOSTS)]
        url = (f"{host}/appstock/app/fqkline/get?"
               f"param={code},day,{start},{end},800,qfq")
        try:
            req = urllib.request.Request(url, headers=UA)
            return urllib.request.urlopen(req, timeout=10).read()
        except Exception:
            time.sleep(2.0 * (att + 1))
    return None


def main():
    import pandas as pd
    uni = pd.read_csv(os.path.join(HERE, "data", "etf_universe.csv"))
    codes = uni.loc[uni.cat == "行业主题", "code"].tolist()
    batch = datetime.now().strftime("%Y%m%d_%H%M%S")
    fails, done = [], 0
    consec_fail = 0
    t0 = time.time()
    for i, code in enumerate(codes):
        if consec_fail >= 15:
            print("连续失败，冷却 60s 防限流...", flush=True)
            time.sleep(60)
            consec_fail = 0
        out_csv = os.path.join(KLINE, f"{code}.csv")
        if os.path.exists(out_csv) and os.path.getsize(out_csv) > 100:
            done += 1
            continue
        all_rows = {}
        ok = True
        for start, end in CHUNKS:
            data = fetch(code, start, end)
            if data is None:
                ok = False
                break
            sha = hashlib.sha256(data).hexdigest()[:16]
            with open(os.path.join(RAW, f"{code}_{start[:4]}_{end[:4]}_{sha}.json"), "wb") as f:
                f.write(data)
            try:
                node = json.loads(data).get("data", {}).get(code, {})
                rows = node.get("qfqday") or node.get("day") or []
                for r in rows:
                    all_rows[r[0]] = r[1:6]
            except Exception:
                pass
            time.sleep(0.35)
        if not ok or not all_rows:
            fails.append(code)
            consec_fail += 1
            continue
        consec_fail = 0
        with open(out_csv, "w", encoding="utf-8") as f:
            f.write("date,open,close,high,low,volume\n")
            for dt in sorted(all_rows):
                f.write(dt + "," + ",".join(all_rows[dt]) + "\n")
        done += 1
        if done % 10 == 0:
            el = time.time() - t0
            print(f"[{done}/{len(codes)}] {el:.0f}s  失败{len(fails)}  "
                  f"{datetime.now().strftime('%H:%M:%S')}", flush=True)
    with open(os.path.join(HERE, "data", "fetch_failures.txt"), "w") as f:
        f.write("\n".join(fails))
    print(f"完成 {done}/{len(codes)}，失败 {len(fails)}，用时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
