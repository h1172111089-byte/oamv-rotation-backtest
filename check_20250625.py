#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证：2025-06-25 信号日 RS 前 10，多少在原方案 44 池内。"""
import os
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt

DOC44 = {  # 档案 44 池主题 → 代表代码（按档案名单映射）
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
}


def main():
    ctx = bt.Context("2019-01-01", "2026-10-09")
    assets, bench = ctx.assets, ctx.bench_map["sh000001"]
    uni = pd.read_csv(os.path.join(HERE, "data", "etf_universe.csv"))
    name_of = dict(zip(uni.code, uni.name))
    d = pd.Timestamp("2025-06-25")
    rows = []
    for code, a in assets.items():
        p = a.pos(d)
        if p is None or p < 63:
            continue
        c = a.df["close"].iloc[p]
        if not (c > a.ma20.iloc[p] > a.ma60.iloc[p]):
            continue
        rs = a.ret20.iloc[p] - bench.ret20.iloc[bench.pos(d)]
        rows.append((code, rs))
    df = pd.DataFrame(rows, columns=["code", "rs"]).sort_values(
        "rs", ascending=False).reset_index(drop=True)
    print(f"合格候选 {len(df)} 只（RS>0 的 {int((df.rs > 0).sum())} 只）\n")
    print("RS 前 12 名：")
    for i, r in df.head(12).iterrows():
        inpool = ""
        for theme, c in DOC44.items():
            if c == r["code"]:
                inpool = f"  ← 44池[{theme}]"
        print(f"  #{i+1:>2} {r['code']} {name_of.get(r['code'], ''):<14} "
              f"RS {r['rs']*100:+.1f}pp{inpool}")
    pos44 = df[df.code.isin(DOC44.values())].reset_index(drop=True)
    print("\n44 池内部排名（前5）：")
    for i, r in pos44.head(5).iterrows():
        theme = [t for t, c in DOC44.items() if c == r["code"]][0]
        print(f"  池内#{i+1} {theme}({r['code']}) RS {r['rs']*100:+.1f}pp  "
              f"全市场排第 {int((df.rs > r.rs).sum()) + 1}")


if __name__ == "__main__":
    main()
