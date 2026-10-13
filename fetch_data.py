#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""腾讯证券公开行情接口批量抓取（前复权日K）。

纪律（对齐工作区 AGENTS.md）：
  - 原始响应落盘 data/raw/，带 sha256 与抓取时间，永不覆盖（文件名含抓取批次）
  - 解析后合并为 data/kline/{code}.csv
  - 数据质量红线：>11 个自然日的空洞必须报告（对齐策略文档的血泪教训）
"""

import hashlib
import json
import os
import sys
import time
import urllib.request
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "data", "raw")
KLINE = os.path.join(HERE, "data", "kline")
os.makedirs(RAW, exist_ok=True)
os.makedirs(KLINE, exist_ok=True)

UA = {"User-Agent": "Mozilla/5.0 (compatible; research-backtest)"}

POOL = {
    # 进攻池 42 只（按策略文档主题清单映射最大/最老牌 ETF，非原始清单，待用户提供后校准）
    "半导体设备": "sz159516", "芯片": "sz159995", "半导体": "sh512480",
    "科创芯片": "sh588200", "通信": "sh515880", "5G": "sh515050",
    "电子": "sz159997", "软件": "sh515230", "云计算": "sh516510",
    "人工智能": "sz159819", "科技": "sh515000", "机器人": "sh562500",
    "创新药": "sz159992", "生物医药": "sh512290", "医疗": "sh512170",
    "新能源": "sh516160", "电池": "sz159755", "光伏": "sh515790",
    "稀土": "sh516780", "有色": "sh512400", "煤炭": "sh515220",
    "银行": "sh512800", "证券": "sh512880", "军工": "sh512660",
    "电力": "sz159611", "基建": "sh516950", "建材": "sz159745",
    "环保": "sh512580", "农业": "sz159825", "养殖": "sz159865",
    "食品饮料": "sh515170", "消费": "sz159928", "酒": "sh512690",
    "家电": "sz159996", "传媒": "sh512980", "游戏": "sz159869",
    "旅游": "sz159766", "房地产": "sh512200", "汽车": "sh516110",
    "化工": "sz159870", "钢铁": "sh515210", "红利": "sh510880",
    # 防守腿
    "红利低波": "sh512890",
    # 防守腿危机替代（测试用）
    "十年国债": "sh511260", "货币ETF": "sh511880",
    # 基准
    "上证指数": "sh000001", "沪深300": "sh000300", "中证全指": "sh000985",
}

CHUNKS = [("2018-01-01", "2020-12-31"), ("2021-01-01", "2023-12-31"),
          ("2024-01-01", "2026-10-10")]


def fetch_one(code, start, end, batch):
    url = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
           f"param={code},day,{start},{end},800,qfq")
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            data = urllib.request.urlopen(req, timeout=20).read()
            sha = hashlib.sha256(data).hexdigest()[:16]
            fn = os.path.join(RAW, f"{code}_{start[:4]}_{end[:4]}_{batch}_{sha}.json")
            with open(fn, "wb") as f:
                f.write(data)
            return json.loads(data), sha
        except Exception as e:
            if attempt == 2:
                return None, str(e)
            time.sleep(1.5 * (attempt + 1))


def parse_rows(js, code):
    node = js.get("data", {}).get(code, {})
    rows = node.get("qfqday") or node.get("day") or []
    out = []
    for r in rows:
        out.append((r[0], float(r[1]), float(r[2]), float(r[3]),
                    float(r[4]), float(r[5]) if len(r) > 5 else 0.0))
    return out


def main():
    batch = datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest = []
    all_data = {c: {} for c in POOL.values()}
    fails = []
    for name, code in POOL.items():
        for start, end in CHUNKS:
            js, info = fetch_one(code, start, end, batch)
            if js is None:
                fails.append((code, start, info))
                continue
            rows = parse_rows(js, code)
            for d, o, c, h, l, v in rows:
                all_data[code][d] = (o, c, h, l, v)
            manifest.append({"code": code, "name": name, "start": start,
                             "end": end, "rows": len(rows), "sha": info,
                             "fetch_time": batch})
            time.sleep(0.12)
        print(f"[done] {name} {code} 累计 {len(all_data[code])} 行")

    with open(os.path.join(RAW, f"manifest_{batch}.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    print("\n===== 合并与空洞检查 =====")
    for name, code in POOL.items():
        d = all_data[code]
        if not d:
            print(f"{name} {code}: 无数据!")
            continue
        dates = sorted(d)
        with open(os.path.join(KLINE, f"{code}.csv"), "w", encoding="utf-8") as f:
            f.write("date,open,close,high,low,volume\n")
            for dt in dates:
                o, c, h, l, v = d[dt]
                f.write(f"{dt},{o},{c},{h},{l},{v}\n")
        holes = []
        prev = datetime.strptime(dates[0], "%Y-%m-%d")
        for dt in dates[1:]:
            cur = datetime.strptime(dt, "%Y-%m-%d")
            if (cur - prev).days > 11:
                holes.append(f"{prev.date()}~{cur.date()}")
            prev = cur
        flag = " 空洞:" + ";".join(holes) if holes else ""
        print(f"{name} {code}: {dates[0]} ~ {dates[-1]}, {len(dates)} 行{flag}")

    if fails:
        print("\n失败:", fails)
        sys.exit(1)


if __name__ == "__main__":
    main()
