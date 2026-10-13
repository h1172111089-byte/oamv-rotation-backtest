#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全宇宙抓取 v2：限流友好版。

  - 每只 ETF 单请求取全历史：param=code,day,,,2000,qfq（空日期=最近2000条）
  - 固定节奏 1.2s/请求；失败重试 2 次（间隔 10s/30s）；连续失败 8 次冷却 120s
  - 断点续传：已有 kline csv 的跳过
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
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
HOSTS = ["https://web.ifzq.gtimg.cn", "https://proxy.finance.qq.com"]


def fetch_full(code):
    for att in range(3):
        host = HOSTS[att % len(HOSTS)]
        url = (f"{host}/appstock/app/fqkline/get?"
               f"param={code},day,,,2000,qfq")
        try:
            req = urllib.request.Request(url, headers=UA)
            return urllib.request.urlopen(req, timeout=12).read()
        except Exception as e:
            time.sleep([10, 30][att] if att < 2 else 0)
    return None


def main():
    import pandas as pd
    uni = pd.read_csv(os.path.join(HERE, "data", "etf_universe.csv"))
    codes = uni.loc[uni.cat == "行业主题", "code"].tolist()
    fails, done, consec = [], 0, 0
    t0 = time.time()
    todo = [c for c in codes
            if not (os.path.exists(os.path.join(KLINE, f"{c}.csv"))
                    and os.path.getsize(os.path.join(KLINE, f"{c}.csv")) > 100)]
    print(f"待抓 {len(todo)}/{len(codes)}", flush=True)
    for i, code in enumerate(todo):
        if consec >= 8:
            print("连续失败8次，冷却120s", flush=True)
            time.sleep(120)
            consec = 0
        data = fetch_full(code)
        rows = {}
        if data:
            try:
                node = json.loads(data).get("data", {}).get(code, {})
                for r in (node.get("qfqday") or node.get("day") or []):
                    rows[r[0]] = r[1:6]
            except Exception:
                rows = {}
        if not rows:
            fails.append(code)
            consec += 1
            time.sleep(1.2)
            continue
        consec = 0
        sha = hashlib.sha256(data).hexdigest()[:16]
        with open(os.path.join(RAW, f"{code}_full_{sha}.json"), "wb") as f:
            f.write(data)
        with open(os.path.join(KLINE, f"{code}.csv"), "w", encoding="utf-8") as f:
            f.write("date,open,close,high,low,volume\n")
            for dt in sorted(rows):
                f.write(dt + "," + ",".join(rows[dt]) + "\n")
        done += 1
        if done % 20 == 0:
            el = time.time() - t0
            eta = el / done * (len(todo) - done) / 60
            print(f"[{done}/{len(todo)}] 用时{el:.0f}s 失败{len(fails)} "
                  f"ETA {eta:.0f}min {datetime.now():%H:%M:%S}", flush=True)
        time.sleep(1.2)
    with open(os.path.join(HERE, "data", "fetch_failures.txt"), "w") as f:
        f.write("\n".join(fails))
    print(f"完成 新增{done} 失败{len(fails)} 用时{(time.time()-t0)/60:.1f}min")
    if fails:
        print("失败样例:", fails[:10])


if __name__ == "__main__":
    main()
