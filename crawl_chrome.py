# -*- coding: utf-8 -*-
"""
crawl_chrome.py — 东财股吧抓取规则 v4（Playwright + 系统 Chrome，GitHub Actions 用）

v1-v3 用 curl 直连 HTML，实测发现无 cookie 会话翻页超过 ~35 页后列表循环乱序
（f_35=09-29 01:10 → f_50 跳回 09-29 10:25），导致 9/29 下午晚上数据整段缺失。
v4 改用 Playwright 驱动真实 Chrome 渲染：与真实浏览器行为一致
（发帖时间倒序、每页 80 行、翻页连续），GitHub Actions ubuntu-latest 自带
/usr/bin/google-chrome，无需下载浏览器。

接口兼容 crawl_recent.crawl_window_requests(cutoff, end_dt=None, max_pages=N)
"""
import json
import os
import random
import re
import time
from datetime import datetime, timedelta

GUBA_LIST_URL = "https://guba.eastmoney.com/list,zssh000001,f_{page}.html"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
CHROME_CANDIDATES = [
    "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/chromium.chrome",
    "/usr/bin/google-chrome-beta",
]
LAUNCH_ARGS = [
    "--no-sandbox", "--disable-gpu",
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
]

EXTRACT_JS = """
() => {
  const out = [];
  const trs = document.querySelectorAll('table tbody tr');
  trs.forEach(tr => {
    const tds = tr.querySelectorAll(':scope > td');
    if (tds.length < 5) return;
    const cell = i => (tds[i] ? (tds[i].innerText || '').trim() : '');
    const a = tds[2] ? tds[2].querySelector('a') : null;
    let href = '', post_id = '';
    if (a) {
      href = a.href || '';
      const m = href.match(/(\\d+)\\.html/);
      if (m) post_id = m[1];
    }
    out.push({
      read: cell(0), reply: cell(1),
      title: a ? (a.innerText || '').trim() : cell(2),
      href: href, post_id: post_id,
      author: cell(3), time: cell(4),
    });
  });
  return out;
}
"""


def parse_list_time(time_str, now=None):
    """解析东财列表时间：'MM-DD HH:MM'（跨年回退）或 'HH:MM'（当日）"""
    if not time_str:
        return None
    time_str = time_str.strip()
    now = now or datetime.now()
    m = re.search(r"(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", time_str)
    if m:
        month, day, hr, mn = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        year = now.year
        dt = datetime(year, month, day, hr, mn)
        if dt > now + timedelta(days=1):  # 未来时间 → 上一年
            dt = dt.replace(year=year - 1)
        return dt
    m = re.search(r"(\d{1,2}):(\d{2})", time_str)
    if m:
        hr, mn = int(m.group(1)), int(m.group(2))
        dt = now.replace(hour=hr, minute=mn, second=0, microsecond=0)
        if dt > now + timedelta(minutes=5):  # 未来 → 前一天
            dt -= timedelta(days=1)
        return dt
    return None


def parse_number(s):
    """解析 '1.2万' / '3456' / '--' 为 int"""
    if s is None:
        return 0
    s = str(s).strip().replace(",", "")
    if s in ("--", "", "-", "None"):
        return 0
    m = re.match(r"([\d.]+)\s*(万|亿|k|K)?", s)
    if not m:
        return 0
    num = float(m.group(1))
    unit = m.group(2)
    if unit in ("万",):
        num *= 10000
    elif unit in ("亿",):
        num *= 100000000
    elif unit in ("k", "K"):
        num *= 1000
    return int(num)


def _find_chrome():
    for c in CHROME_CANDIDATES:
        if os.path.exists(c):
            return c
    return None


def _load_page(page, url):
    """加载单页并提取行；3 轮 × 3 次尝试，轮间长退避 60s（抗翻页限流）。
    注意：不使用 page.wait_for_selector —— Playwright 1.63 在超时转写错误时
    存在 'str' object is not callable 的内部 TypeError bug，改为 evaluate 轮询。"""
    for round_i in range(3):
        for attempt in range(3):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
            except Exception as e:
                print(f"    [诊断] goto失败 {type(e).__name__}: {str(e)[:80]} url={page.url()[:90]!r}")
                time.sleep(5 + random.random() * 5)
                continue
            rows = None
            for _ in range(30):  # 轮询最多 ~30s 等表格渲染
                try:
                    rows = page.evaluate(EXTRACT_JS)
                except Exception:
                    rows = None
                if rows:
                    return rows
                time.sleep(1)
            print(f"    [诊断] 页面无表格行，url={page.url()[:90]!r} title={page.title()[:40]!r}")
        print(f"    第 {round_i + 1} 轮失败，长退避 60s 后重试")
        time.sleep(60)
    return None


def crawl_window_requests(cutoff, end_dt=None, max_pages=300):
    """Playwright 翻页抓取 [cutoff, end_dt] 窗口；页内最早时间 < cutoff 即停"""
    from playwright.sync_api import sync_playwright
    now = end_dt or datetime.now()
    chrome = _find_chrome()
    if not chrome:
        print("[抓取] 未找到系统 Chrome，无法使用 Playwright 通道")
        return [], {"stopped": False, "intercepted": True}
    results, seen = [], set()
    stopped = False
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome, headless=True, args=LAUNCH_ARGS)
        ctx = browser.new_context(user_agent=UA, locale="zh-CN")
        page = ctx.new_page()
        no_new_streak = 0
        for page_no in range(1, max_pages + 1):
            url = GUBA_LIST_URL.format(page=page_no)
            rows = _load_page(page, url)
            if not rows:
                print(f"[抓取] page {page_no}: 多轮重试仍失败，停止")
                break
            page_dts, page_new = [], 0
            for r in rows:
                dt = parse_list_time(r.get("time", ""), now)
                if dt is None:
                    continue
                page_dts.append(dt)
                if dt < cutoff or dt >= end_dt:  # v5: 次日 00:00 归属次日，不入当日窗口
                    continue
                key = r.get("post_id") or (r.get("title", "") + r.get("author", ""))
                if key in seen:
                    continue
                seen.add(key)
                results.append({
                    "post_id": r.get("post_id", ""), "title": r.get("title", ""),
                    "read_count": r.get("read", ""), "reply_count": r.get("reply", ""),
                    "author": r.get("author", ""), "time": r.get("time", ""),
                    "href": r.get("href", ""), "source": "eastmoney",
                })
                page_new += 1
            if page_dts and min(page_dts) < cutoff:
                stopped = True
                break
            if page_new == 0:
                # 只有已翻到窗口边界内（最早时间 < end_dt）才认为可能循环；
                # 整页仍在窗口未来区（如早晨抓取时 9/30 早盘帖）则继续翻页
                if page_dts and min(page_dts) < end_dt:
                    no_new_streak += 1
                    if no_new_streak >= 5:
                        print(f"[抓取] 连续 {no_new_streak} 页无新增，提前停止（防循环）")
                        break
            else:
                no_new_streak = 0
            print(f"[抓取] page {page_no}: 新增 {page_new}，累计 {len(results)}，"
                  f"最早 {min(page_dts).strftime('%m-%d %H:%M') if page_dts else '-'}")
            # 限流防护：翻页间隔随机化；每 20 页长退避 30s
            time.sleep(1.5 + random.random() * 1.5)
            if page_no % 20 == 0:
                print(f"[抓取] 连续翻页 {page_no} 页，长退避 30s 防风控")
                time.sleep(30)
        browser.close()
    print(f"[抓取] 完成: {len(results)} 条, stopped={stopped}")
    return results, {"stopped": stopped, "intercepted": False}


if __name__ == "__main__":
    rows, meta = crawl_window_requests(datetime.now() - timedelta(hours=12), max_pages=5)
    print(json.dumps({"rows": len(rows), "meta": meta}, ensure_ascii=False))
