#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
s = pd.read_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "outputs", "segments.csv"))
print("总段数", len(s), " 空主线段:",
      int(s["empty_mainline"].sum()) if "empty_mainline" in s.columns else 0)
s["year"] = pd.to_datetime(s["entry"]).dt.year
print("\n2023/2025 分段明细:")
for _, r in s[s.year.isin([2023, 2025])].iterrows():
    print(f"{r['entry']}~{r['exit']} ret={r['ret']:+.1%} "
          f"empty={r.get('empty_mainline')} picks={str(r['picks'])[:80]}")
print("\n最差6段:")
for _, r in s.nsmallest(6, "ret").iterrows():
    print(f"{r['entry']}~{r['exit']} ret={r['ret']:+.1%} "
          f"picks={str(r['picks'])[:80]}")
