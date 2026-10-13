#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日增量更新：宇宙全部 ETF + 核心标的最近行情，并提示录入当日 0AMV。

用法：
  python update_daily.py                          # 只更新行情
  python update_daily.py --amv 155000 1.23        # 同时录入今日0AMV收盘与涨跌幅(%)

说明：
  - 每个标的取最近 15 根日K，与本地 CSV 按日期合并去重
  - 全量约 770 个请求、限速 1.2s/个，预计 15-25 分钟；被限流会自动冷却，
    中断后重跑即可断点续传（已是最新的会跳过）
  - 0AMV 是指南针人工读数，脚本只做追加写入并校验交易日
"""

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "data", "raw", "daily")
KLINE = os.path.join(HERE, "data", "kline")
os.makedirs(RAW, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
HOSTS = ["https://web.ifzq.gtimg.cn", "https://proxy.finance.qq.com"]
CORE = ["sh512890", "sh510880", "sh511260", "sh511880",
        "sh000001", "sh000300", "sh000985"]


def fetch_tail(code, count=15):
    for att in range(3):
        host = HOSTS[att % len(HOSTS)]
        url = (f"{host}/appstock/app/fqkline/get?"
               f"param={code},day,,,{count},qfq")
        try:
            req = urllib.request.Request(url, headers=UA)
            return urllib.request.urlopen(req, timeout=12).read()
        except Exception:
            time.sleep(2.0 * (att + 1))
    return None


def merge(code, rows):
    path = os.path.join(KLINE, f"{code}.csv")
    import pandas as pd
    new = pd.DataFrame(rows, columns=["date", "open", "close", "high", "low",
                                      "volume"])
    if os.path.exists(path):
        old = pd.read_csv(path, dtype=str)
        df = pd.concat([old, new.astype(str)]).drop_duplicates("date",
                                                               keep="last")
    else:
        df = new.astype(str)
    df = df.sort_values("date")
    df.to_csv(path, index=False)
    return df["date"].iloc[-1]


def append_amv(close, chg):
    path = os.path.join(HERE, "0amv_day.csv")
    import pandas as pd
    cal = pd.read_csv(os.path.join(KLINE, "sh000001.csv"))["date"].tolist()
    today = datetime.now().strftime("%Y-%m-%d")
    if today not in cal:
        print(f"警告: 今天 {today} 不是交易日，未写入"); return
    df = pd.read_csv(path)
    stamp = f"{today}T16:00:00Z"
    if stamp in df["date"].tolist():
        print("今日 0AMV 已存在，跳过"); return
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{stamp},{close},{close},{close},{close},{chg}\n")
    print(f"已录入 0AMV: {today} close={close} chg={chg}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--amv", nargs=2, metavar=("CLOSE", "CHG_PCT"),
                    help="录入今日0AMV收盘值与涨跌幅(%)")
    args = ap.parse_args()

    import pandas as pd
    uni = pd.read_csv(os.path.join(HERE, "data", "etf_universe.csv"))
    codes = sorted(set(uni.loc[uni.cat == "行业主题", "code"]) | set(CORE))
    print(f"共 {len(codes)} 个标的待更新")
    fails, done, consec = [], 0, 0
    t0 = time.time()
    for code in codes:
        path = os.path.join(KLINE, f"{code}.csv")
        if os.path.exists(path):
            last = pd.read_csv(path)["date"].iloc[-1]
            if last >= datetime.now().strftime("%Y-%m-%d"):
                done += 1
                continue
        if consec >= 8:
            print("连续失败，冷却120s", flush=True)
            time.sleep(120)
            consec = 0
        data = fetch_tail(code)
        rows = []
        if data:
            try:
                node = json.loads(data).get("data", {}).get(code, {})
                rows = node.get("qfqday") or node.get("day") or []
            except Exception:
                rows = []
        if not rows:
            fails.append(code)
            consec += 1
            time.sleep(1.2)
            continue
        consec = 0
        sha = hashlib.sha256(data).hexdigest()[:16]
        with open(os.path.join(RAW, f"{code}_{datetime.now():%Y%m%d}_{sha}.json"),
                  "wb") as f:
            f.write(data)
        last = merge(code, rows)
        done += 1
        if done % 50 == 0:
            print(f"[{done}/{len(codes)}] 用时{time.time()-t0:.0f}s "
                    f"失败{len(fails)}", flush=True)
        time.sleep(1.2)
    print(f"完成 更新{done} 失败{len(fails)} 用时{(time.time()-t0)/60:.1f}min")
    if fails:
        print("失败:", fails[:20])
    if args.amv:
        append_amv(args.amv[0], args.amv[1])
    else:
        print("提醒: 今日 0AMV 未录入。运行 python update_daily.py --amv 收盘值 涨跌幅")


if __name__ == "__main__":
    main()
