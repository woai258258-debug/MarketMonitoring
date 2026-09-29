# -*- coding: utf-8 -*-
"""
run_yesterday.py — 每天定时跑"前一天全天"数据（GitHub Actions 用）v2
v2 改进（抗风控降级）：
  - 抓取被东财风控拦截/0 帖时，若 data.json 已有该日历史数据：
    重建看板 + 更新 risk 日期 → 正常退出 0（保证 Pages 每天有内容），打印明显警告
  - 无任何该日数据才返回 2（此时看板保留旧数据，次日自动重试）

流程：
  1. 直连东财股吧，抓取 [昨天 00:00, 今天 00:00) 窗口帖子
  2. 情绪分析（sentiment_analyzer 增强版）
  3. 合并历史 → data.json / posts.json → 生成看板 index.html
  4. 打印报告（情绪指数/恐慌占比/TOP 词/高热度帖）

用法: python3 run_yesterday.py [--date YYYY-MM-DD]
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from crawl_recent import crawl_window_requests, parse_number
from sentiment_analyzer import SentimentAnalyzer
from data_store import save_bundle
from dashboard_generator import DashboardGenerator


def load_raw(path):
    posts = json.load(open(path, encoding="utf-8"))
    for p in posts:
        if isinstance(p.get("read_count"), str):
            p["read_count"] = parse_number(p["read_count"])
        if isinstance(p.get("reply_count"), str):
            p["reply_count"] = parse_number(p["reply_count"])
    return posts


def analyze_and_build(posts, day_start, day_end, data_path, posts_path, index_path, config_path):
    analyzer = SentimentAnalyzer(str(config_path))
    ref = day_end  # 以窗口末为参考时间，避免衰减偏差
    res = analyzer.analyze_posts(posts, reference_time=ref)
    s = res["summary"]
    s["scan_date"] = day_start.strftime("%Y-%m-%d")
    s["crawled_posts"] = len(posts)
    s["window_start"] = day_start.strftime("%Y-%m-%d %H:%M")
    s["window_end"] = day_end.strftime("%Y-%m-%d %H:%M")
    s["window_hours"] = "昨日全天"
    s["top_bullish_words"] = res["top_bullish_words"]
    s["top_bearish_words"] = res["top_bearish_words"]

    data = json.load(open(data_path, encoding="utf-8")) if data_path.exists() else {"daily_trends": [], "hourly_trends": [], "summary": {}, "top_bullish_words": [], "top_bearish_words": [], "posts": []}
    new_daily = {d["date"]: d for d in res["daily_trends"]}
    merged = []
    for d in data.get("daily_trends", []):
        if d["date"] in new_daily:
            merged.append(new_daily.pop(d["date"]))
        else:
            merged.append(d)
    for d in sorted(new_daily.keys()):
        merged.append(new_daily[d])
    merged.sort(key=lambda x: x["date"])
    data["daily_trends"] = merged

    new_hourly = {h["time"]: h for h in res["hourly_trends"]}
    merged_h = []
    for h in data.get("hourly_trends", []):
        if h["time"] in new_hourly:
            merged_h.append(new_hourly.pop(h["time"]))
        else:
            merged_h.append(h)
    for t in sorted(new_hourly.keys()):
        merged_h.append(new_hourly[t])
    merged_h.sort(key=lambda x: x["time"])
    data["hourly_trends"] = merged_h[-720:]

    data["summary"] = s
    data["top_bullish_words"] = res["top_bullish_words"]
    data["top_bearish_words"] = res["top_bearish_words"]
    data["posts"] = res["posts"]

    sc = s.get("overall_weighted_score", 0)
    if sc <= -0.3:
        lvl, adv = "⛔ 极端", "破位风险极高，建议大幅减仓/对冲"
    elif sc <= -0.1:
        lvl, adv = "⚠️ 预警", "情绪偏悲观，控制仓位、观察企稳"
    elif sc >= 0.5:
        lvl, adv = "🚀 亢奋", "市场情绪过热，注意保护利润、防守减仓"
    elif sc >= 0.1:
        lvl, adv = "😊 乐观", "情绪偏乐观，可维持仓位、顺势持有"
    else:
        lvl, adv = "➖ 中性", "情绪中性，维持当前策略不动"
    risk = data.setdefault("risk", {})
    risk["trade_date"] = day_end.strftime("%Y-%m-%d")
    risk["level"] = lvl
    risk["advice"] = adv
    risk["total_score"] = round(50 + sc * 50, 1)
    risk["dimensions"] = risk.get("dimensions") or {}
    risk["dimensions"]["sentiment"] = {
        "score": round(max(0, min(100, 50 + sc * 50)), 1),
        "value": round(sc, 4),
        "label": "论坛情绪(昨日窗口)",
        "detail": f"昨日情绪分 {sc:.4f}",
        "thresholds": {"warning": 0.3, "danger": 0.5},
    }

    save_bundle(data, str(data_path))
    gen = DashboardGenerator(data_path=str(data_path), config_path=str(config_path))
    ok = gen.generate_html(output_path=str(index_path))
    return s, ok


def degrade_with_existing(data_path, index_path, day_start, day_end):
    """降级：抓取失败但 data.json 已有该日数据 → 重建看板，正常退出"""
    if not data_path.exists():
        return False
    data = json.load(open(data_path, encoding="utf-8"))
    day_str = day_start.strftime("%Y-%m-%d")
    has_day = any(d.get("date") == day_str for d in data.get("daily_trends", []))
    if not has_day:
        return False
    # 更新 risk trade_date 为当日窗口末
    risk = data.setdefault("risk", {})
    risk["trade_date"] = day_end.strftime("%Y-%m-%d")
    risk["source_note"] = "抓取被风控拦截，本次使用已有历史数据重建看板（数据非最新抓取）"
    try:
        save_bundle(data, str(data_path))
        gen = DashboardGenerator(data_path=str(data_path), config_path=str(ROOT / "config.json"))
        ok = gen.generate_html(output_path=str(index_path))
        print(f"[降级] 已用 {day_str} 已有数据重建看板 (ok={ok})")
        return True
    except Exception as e:
        print(f"[降级] 重建看板失败: {e}")
        return False


def print_report(s, day_start, day_end, posts, top_n=8):
    print("=" * 60)
    print(f"  大A情绪分 · 昨日全天报告（{day_start.strftime('%Y-%m-%d')}）")
    print("=" * 60)
    print(f"  窗口: {day_start.strftime('%m-%d %H:%M')} ~ {day_end.strftime('%m-%d %H:%M')} (昨日全天)")
    print(f"  抓取: {s.get('crawled_posts')} 帖 | 有效: {s.get('valid_posts')} | 多 {s.get('bullish_posts')} / 空 {s.get('bearish_posts')} / 中性 {s.get('neutral_posts')}")
    print(f"  情绪指数: {s.get('overall_weighted_score')}  [±1.0]")
    print(f"  参与度: {s.get('sentiment_participation', '-')} | 恐慌占比: {s.get('panic_ratio', '-')}")
    sc = s.get("overall_weighted_score", 0)
    if sc <= -0.3:
        verdict = "极度悲观 / 黄金买点（恐慌）"
    elif sc <= -0.1:
        verdict = "偏悲观"
    elif sc >= 0.5:
        verdict = "极度亢奋"
    elif sc >= 0.1:
        verdict = "偏乐观"
    else:
        verdict = "中性震荡"
    print(f"  判定: {verdict}")
    print("-" * 60)
    print("  恐慌词 TOP:", ", ".join((x.get("word") if isinstance(x, dict) else x[0]) for x in s.get("top_bearish_words", [])[:6]))
    print("  亢奋词 TOP:", ", ".join((x.get("word") if isinstance(x, dict) else x[0]) for x in s.get("top_bullish_words", [])[:6]))
    print("-" * 60)
    hot = sorted(posts, key=lambda p: -(p.get("read_count") or 0))[:top_n]
    print("  高热度帖（阅读量 TOP%d）:" % top_n)
    for p in hot:
        t = (p.get("time") or "")[:16]
        print(f"    [{p.get('read_count', 0):>6}读] {t} {p.get('title', '')[:50]}")
    return verdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="指定抓取日 YYYY-MM-DD（默认昨天）")
    ap.add_argument("--posts", help="已有抓取 JSON，跳过抓取")
    args = ap.parse_args()

    now = datetime.now()
    if args.date:
        day = datetime.strptime(args.date, "%Y-%m-%d")
    else:
        day = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    if day_end > now:
        day_end = now

    data_path = ROOT / "data.json"
    posts_path = ROOT / "posts.json"
    index_path = ROOT / "index.html"
    config_path = ROOT / "config.json"

    if args.posts:
        posts = load_raw(args.posts)
    else:
        print(f"[抓取] 窗口 {day_start.strftime('%Y-%m-%d %H:%M')} ~ {day_end.strftime('%Y-%m-%d %H:%M')}")
        posts, meta = crawl_window_requests(day_start, end_dt=day_end)
        if meta.get("intercepted"):
            print("[失败] 直连被东财反爬拦截（验证页）")
            if degrade_with_existing(data_path, index_path, day_start, day_end):
                print("[降级完成] 看板已用历史数据重建，流程正常结束")
                return 0
            return 2
        if not posts:
            print("[失败] 窗口内没有帖子（0 条）")
            if degrade_with_existing(data_path, index_path, day_start, day_end):
                print("[降级完成] 看板已用历史数据重建，流程正常结束")
                return 0
            return 2
        raw_path = ROOT / f"posts_{day_start.strftime('%Y%m%d')}_raw.json"
        json.dump(posts, open(raw_path, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"[抓取] 已保存原始数据 {raw_path}")

    if not posts:
        print("[失败] 没有帖子数据")
        return 2

    print(f"[分析] 共 {len(posts)} 条帖子 → 情绪分析...")
    s, ok = analyze_and_build(posts, day_start, day_end, data_path, posts_path, index_path, config_path)
    verdict = print_report(s, day_start, day_end, posts)
    print("-" * 60)
    print("  产物: data.json / posts.json / index.html")
    print(f"  看板: {index_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
