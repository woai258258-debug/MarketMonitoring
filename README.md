# MarketMonitoring · 大A情绪分参考

[![Daily Analysis](https://github.com/woai258258-debug/MarketMonitoring/actions/workflows/daily.yml/badge.svg)](https://github.com/woai258258-debug/MarketMonitoring/actions/workflows/daily.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

> 每天自动抓取东方财富股吧（上证指数）帖子，基于增强情绪词库做量化打分，结合 AKShare 当日涨停/跌停/炸板行情，自动生成可视化看板并部署到 GitHub Pages。

**在线看板：** https://woai258258-debug.github.io/MarketMonitoring/

---

## 自动运行机制

| 项目 | 说明 |
|------|------|
| **定时任务** | GitHub Actions 每天 **北京时间 01:00**（cron `0 17 * * *` UTC）自动运行 |
| **抓取目标** | 前一自然日全天（00:00 ~ 24:00）东财上证指数股吧帖子 |
| **抓取通道** | Playwright + 系统 Chrome（headless），时间倒序连续翻页，翻页间隔随机化 + 长翻页退避抗风控 |
| **情绪分析** | 增强词库（多头 155 / 空头 269 / 短语 197 / 否定/反讽正则 40），`log2(阅读量)` 权重压缩，热帖不再一票定音 |
| **涨停/跌停** | AKShare 免费接口（`stock_zt_pool_em` / `stock_zt_pool_dtgc_em` / `stock_zt_pool_zbgc_em`），按分析日实时拉取 |
| **交付** | 自动 commit `data.json` / `posts.json` / `index.html` → 部署 GitHub Pages |

## 手动触发 / 补跑历史

GitHub Actions 页面 → **Daily Sentiment Analysis → Run workflow**：

- **留空 date**：抓取昨天（与定时任务一致）
- **填写 `YYYY-MM-DD`**：补跑指定日期（例如 `2026-09-28`）

## 情绪指数解读（5 档）

| 区间 | 含义 | 参考操作 |
|------|------|----------|
| `≤ -0.3` | 极度恐慌 / 黄金买点 | 逆向建仓 +10%~+20% |
| `-0.3 ~ -0.1` | 偏悲观 / 预警 | 控制仓位、观察企稳 |
| `-0.1 ~ 0.1` | 中性 | 维持底仓，持股不动 |
| `0.1 ~ 0.5` | 偏乐观 | 顺势持有 |
| `≥ 0.5` | 极度亢奋 / 防御警报 | 防守减仓 -10%~-20% |

## 看板布局

| 区域 | 内容 |
|------|------|
| 左上 | 大盘情绪指数（5 档判定仪表盘 + 帖子分类占比） |
| 右上 | 情绪日线趋势 + 模型说明（5 档横排） |
| 中部 | 活跃多头/空头词频（左右并排） |
| 横版风险卡 | 风险值（当日情绪折算）+ 当日涨停/炸板/跌停 + 炸板率 |
| 底部 | 情绪模拟器（实时打分）+ 帖子明细表（可筛选/排序） |

## 项目结构

```
├── run_yesterday.py         # 主入口：抓取 → 分析 → 行情 → 看板（GitHub Actions 用）
├── crawl_chrome.py          # 东财股吧抓取（Playwright + 系统 Chrome）
├── sentiment_analyzer.py    # 情绪分析引擎（词库 + 否定/反讽 + log 权重）
├── dashboard_generator.py   # HTML 看板生成（5 档判定）
├── data_store.py            # data.json / posts.json 读写
├── beijing_time.py          # 全项目统一北京时间 (Asia/Shanghai)
├── risk_scorer.py           # 历史风险评分工具（TuShare 时代遗留，当前看板不依赖）
├── config.json              # 情绪词库与配置
├── data.json                # 分析摘要 + 风险 + 日线/小时线（轻量）
├── posts.json               # 帖子明细（紧凑 JSON，看板异步加载）
├── index.html               # 在线看板（每次运行自动重新生成）
└── .github/workflows/
    └── daily.yml            # 每日 01:00 定时 + 手动触发/补跑
```

## 本地运行（可选）

```bash
git clone https://github.com/woai258258-debug/MarketMonitoring.git
cd MarketMonitoring
pip install -r requirements.txt
playwright install chromium   # 需要时
python run_yesterday.py              # 分析昨天
python run_yesterday.py --date 2026-09-28   # 补跑指定日期
```

## 免责声明

本工具仅供情绪因子研究与数据展示，**不构成任何投资建议**。股市有风险，投资需谨慎。

## License

[MIT](LICENSE)
