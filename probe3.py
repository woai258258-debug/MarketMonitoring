# -*- coding: utf-8 -*-
"""云端探测 v3：Playwright+系统Chrome 抓股吧 + akshare 行情"""
import re, sys

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

def parse_times(html):
    times = []
    for m in re.finditer(r'<tr[^>]*>(.*?)</tr>', html, re.S):
        tds = re.findall(r'<td[^>]*>(.*?)</td>', m.group(1), re.S)
        if len(tds) < 5: continue
        t = re.sub(r'<[^>]+>', '', tds[4]).strip()
        if re.match(r'^\d{1,2}-\d{1,2} \d{2}:\d{2}$', t): times.append(t)
    return times

print("=== 1. Playwright + 系统 Chrome 抓股吧 ===")
try:
    from playwright.sync_api import sync_playwright
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True,
                                    args=["--no-sandbox", "--disable-gpu", "--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=UA, locale="zh-CN")
        page = ctx.new_page()
        for pg in [1, 5, 10, 35, 60]:
            try:
                page.goto(f"https://guba.eastmoney.com/list,zssh000001,f_{pg}.html",
                          wait_until="domcontentloaded", timeout=30000)
                page.wait_for_selector("table tbody tr", timeout=20000)
                html = page.content()
                times = parse_times(html)
                if times:
                    results[pg] = (times[0], times[-1], len(times))
                    print(f"  f_{pg}: {len(times)} 行 | 首 {times[0]} | 末 {times[-1]}")
                else:
                    print(f"  f_{pg}: 表格存在但无有效时间 rows? {html.count('<tr')}")
            except Exception as e:
                print(f"  f_{pg}: 失败 {type(e).__name__}: {str(e)[:150]}")
        browser.close()
    # 时间连续性判断
    if results:
        seq = [results[k][0] for k in sorted(results)]
        print("  各页首时间:", seq)
except Exception as e:
    print("  Playwright 整体失败:", type(e).__name__, str(e)[:300])

print("\n=== 2. 云端 akshare 行情 ===")
try:
    import akshare as ak
    for name, fn in [("涨停", lambda: ak.stock_zt_pool_em(date="20260929")),
                     ("跌停", lambda: ak.stock_zt_pool_dtgc_em(date="20260929")),
                     ("炸板", lambda: ak.stock_zt_pool_zbgc_em(date="20260929"))]:
        try:
            df = fn()
            print(f"  [{name}] rows={len(df)}")
        except Exception as e:
            print(f"  [{name}] 失败: {type(e).__name__}: {str(e)[:150]}")
except Exception as e:
    print("  akshare 导入失败:", str(e)[:200])

print("\n=== 3. requests + gbapi JSON 接口（带cookie）===")
try:
    import requests
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Referer": "https://guba.eastmoney.com/"})
    try:
        s.get("https://www.eastmoney.com/", timeout=15)
    except Exception as e:
        print("  首页 cookie:", str(e)[:100])
    for url in [
        "https://gbapi.eastmoney.com/List/List?pno=1&ps=80&sort=1&code=000001&market=1",
        "https://gbapi.eastmoney.com/List/List?pno=1&ps=80&sort=1&code=000001&market=1&type=1&token=44c9d0e6e1c3f0d8c9b5a6c0d1e2f3a4",
    ]:
        try:
            r = s.get(url, timeout=15)
            body = r.text
            print(f"  {url[:70]}... -> http={r.status_code} len={len(body)} head={body[:120]!r}")
        except Exception as e:
            print(f"  {url[:70]}... 失败: {str(e)[:120]}")
except Exception as e:
    print("  requests 失败:", str(e)[:200])
