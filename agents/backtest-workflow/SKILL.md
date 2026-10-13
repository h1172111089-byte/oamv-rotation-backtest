---
name: backtest-workflow
description: 0AMV 信号择时 + 全市场行业动量轮动回测项目的标准工作流程。当用户提到回测、0AMV、活跃市值、轮动策略、进攻/防守腿、信号台账、每日日更时使用。项目根目录 F:\宏观经济分析\回测方案。
---

# Backtest Workflow（0AMV 轮动项目）

## 项目事实（必须遵守）

- 项目根目录：`F:\宏观经济分析\回测方案`（git 仓库，远程 GitHub 私有库 `oamv-rotation-backtest`）
- **信号真值只有一份**：`0AMV活跃市值切换信号登记表.csv`（人工台账，96 条）。`0amv_day.csv` 的日期轴已证实损坏（工作日网格、节假日不跳空、约 7% 缺失），只能当数值档案，不能当信号源
- 行情数据：腾讯前复权日线为主力源（`data/kline/`，有小时级限流，超限发 501）；东财 API 在本网络不通；新浪/baostock 为备胎（ETF 不复权，仅校验用）
- 原始快照（`data/raw/`）只增不改；行情数据不进 git
- 宇宙：`data/etf_universe.csv`（当前在册 767 只行业主题 ETF，有幸存者偏差，分类变更需人工复核）

## 工具与触发时机

| 命令 | 何时用 |
|---|---|
| `python update_daily.py [--amv 收盘值 涨跌幅]` | 每日收盘后增量更新行情 + 录入 0AMV |
| `python bt.py` | 基线回测（台账信号+全市场宇宙+T+1收盘）。变体用 `--exec-price open`、`--topn 2` 等 |
| `python run_experiments.py` | 优化变体矩阵（OFAT+阈值网格），样本内外分列 |
| `python repair_amv.py` | 台账变更后重新对齐 `0amv_day.csv`，输出 `0amv_day_fixed.csv` 并对账 |
| `python fetch_universe_v2.py` | 新机重建/断点补抓全宇宙日线 |

## 已定稿的策略结论（勿推翻，除非新数据证伪）

- 采纳口径：台账信号 + RS20 排名 + T+1 开盘执行 + 固定双仓；基线约 +1520% / 年化 43.1%（台账更正后）
- 已否决：日频 MA200 防守熔断、流动性过滤、RS 混合窗口、脉冲过滤、5 日重排、资金流排序（Chaikin 代理口径）
- RS 基准选择数学上不影响排名，固定用上证指数
- 前瞻折现口径：年化 15-25%、MDD 20-30%，禁止按回测账面外推

## 报告纪律（每篇分析必须包含）

ASOF（分析时点）、CUTOFF（数据截止）、SOURCE（来源）、FACT（事实）、INFER（推断+方法）、FALSIFY（失效条件）、WRONG（我可能错在哪）。
优化实验必须分列样本内（2019-2023）/样本外（2024-2026.10），并注明多重检验次数。

## 每日节奏

收盘后：`update_daily.py --amv ...` → 查看信号状态变化 → GitHub Desktop Commit + Push。
