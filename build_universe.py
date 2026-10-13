#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建全市场行业/主题 ETF 宇宙（点样本在当前在册名单，局限性见输出说明）。

流程：东财 fundcode_search.js → 场内 ETF（51/15/56/58 前缀且非联接）
     → 按名称剔除宽基/债券/货币/商品/跨境 → 行业/主题宇宙
输出：data/etf_universe.csv（含分类与剔除原因，供人工复核）

已知局限（诚实声明）：
  - 名单为"当前在册"，2019 年以来已清盘的 ETF 不在其中 → 宇宙有轻度幸存者偏差
  - 名称关键词分类存在误判边界，输出全量分类供人工核对
"""

import json
import re
import sys
import urllib.request
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")
UA = {"User-Agent": "Mozilla/5.0"}
HERE = __file__.rsplit("\\", 1)[0]

BROAD = ["300ETF", "500ETF", "1000", "2000", "A500", "50ETF", "综指", "创业板",
         "科创50", "科创板50", "MSCI", "央企", "国企", "增强", "深证", "上证50",
         "中证A50", "A100", "A50", "科创100", "科创200", "科创综指", "双创",
         "北证", "中小", "等权", "基本面", "价值ETF", "成长ETF",
         "ESG", "500质量", "深100", "中证100", "800", "TMT50",
         "180", "380", "中盘", "超大盘", "上证指数", "责任", "治理", "大盘"]
STYLE = ["红利", "低波", "现金流", "质量"]
BOND = ["债", "国开", "国债", "信用", "政金", "利率"]
MONEY = ["货币", "日利", "添益", "保证金", "快线", "快钱", "现金管理", "理财",
         "收益宝", "天天金", "添利"]
COMMODITY = ["黄金", "豆粕", "原油", "白银", "期货", "金ETF", "上海金"]
COMMODITY_CODES = {"sz159980", "sz159981", "sz159985"}  # 有色期货/能源化工/豆粕
OVERSEA = ["纳指", "纳斯达克", "标普", "道琼", "日经", "德国", "法国", "沙特",
           "东南亚", "恒生", "港股", "H股", "中概", "亚太", "全球", "美国",
           "越南", "印度", "韩国", "日本", "QDII", "港股通", "香港", "中韩",
           "沪港深", "AH优选"]


def classify(name, code=""):
    if code in COMMODITY_CODES:
        return "剔除-商品"
    for kw in BOND:
        if kw in name:
            return "剔除-债券"
    for kw in MONEY:
        if kw in name:
            return "剔除-货币"
    for kw in COMMODITY:
        if kw in name:
            return "剔除-商品"
    for kw in OVERSEA:
        if kw in name:
            return "剔除-跨境"
    for kw in STYLE:
        if kw in name:
            return "剔除-策略风格"
    for kw in BROAD:
        if kw in name:
            return "剔除-宽基/风格"
    return "行业主题"


def main():
    raw = urllib.request.urlopen(
        urllib.request.Request("http://fund.eastmoney.com/js/fundcode_search.js",
                               headers=UA), timeout=20).read()
    text = raw.decode("utf-8", errors="ignore")
    items = re.findall(r'\["(\d{6})","([^"]*)","([^"]+)","([^"]*)"', text)
    traded = [x for x in items
              if x[0][:2] in ("51", "15", "56", "58") and "ETF" in x[2]
              and "联接" not in x[2] and x[0][:3] != "513"]  # 513=上交所跨境ETF
    rows = []
    for code, py, name, ftype in traded:
        exch = ("sh" if code[0] == "5" else "sz") + code
        cat = classify(name, exch)
        rows.append({"code": exch, "name": name, "type": ftype, "cat": cat})
    rows.sort(key=lambda r: r["code"])
    out = HERE + "\\data\\etf_universe.csv"
    with open(out, "w", encoding="utf-8-sig") as f:
        f.write("code,name,type,cat\n")
        for r in rows:
            f.write(f"{r['code']},{r['name']},{r['type']},{r['cat']}\n")
    keep = [r for r in rows if r["cat"] == "行业主题"]
    print(f"场内ETF {len(rows)} 只 → 行业主题宇宙 {len(keep)} 只")
    from collections import Counter
    print(Counter(r["cat"] for r in rows).most_common())
    with open(HERE + "\\data\\universe_meta.json", "w", encoding="utf-8") as f:
        json.dump({"asof": datetime.now().isoformat(timespec="seconds"),
                   "n_traded": len(rows), "n_keep": len(keep)},
                  f, ensure_ascii=False, indent=1)
    print("样例:", [(r["code"], r["name"]) for r in keep[:10]])


if __name__ == "__main__":
    main()
