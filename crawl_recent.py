# -*- coding: utf-8 -*-
"""
crawl_recent.py — 东财股吧抓取规则 v3（云环境直连版，适用于 GitHub Actions 定时任务）
v3 抗风控增强：
  1. UA 轮换（Chrome/Edge/Mac 三选一）
  2. 请求间隔随机化（0.6~1.8s），更像人工浏览
  3. 风控冷却升级：指数退避（60s 起步，每轮翻倍，最长 5 分钟），总重试窗口可至 ~1 小时
"""
import json
import os
import random
import re
import subprocess
import tempfile
import time
from datetime import datetime, timedelta

GUBA_LIST_URL = "https://guba.eastmoney.com/list,zssh000001,f_{page}.html"
UAS = [
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
]
VERIFY_MARKER_LEN = 5000  # 验证页 body 长度远小于正常页（正常 >100KB）


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


def parse_list_rows(html):
    """从直连 HTML 中解析帖子行（table tbody tr 五列）"""
    rows = []
    pattern = re.compile(r'<tr[^>]*>(.*?)</tr>', re.S)
    for tr_m in pattern.finditer(html):
        tr = tr_m.group(1)
        tds = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)
        if len(tds) < 5:
            continue
        clean = lambda x: re.sub(r'<[^>]+>', '', x).strip()
        read = clean(tds[0])
        reply = clean(tds[1])
        a_m = re.search(r'href="([^"]*(\d+)\.html)"[^>]*>(.*?)</a>', tds[2], re.S)
        if not a_m:
            title = clean(tds[2])
            href, post_id = "", ""
        else:
            href, post_id, title = a_m.group(1), a_m.group(2), clean(a_m.group(3))
        author = clean(tds[3])
        time_s = clean(tds[4])
        rows.append({
            "read": read, "reply": reply, "title": title, "author": author,
            "time": time_s, "href": href, "post_id": post_id,
        })
    return rows


def curl_get(url, timeout=20):
    """用 curl 拉取页面（TLS 指纹比 requests 更接近真实浏览器，云环境放行率高）"""
    tmp = tempfile.mktemp(suffix=".html")
    ua = random.choice(UAS)
    try:
        r = subprocess.run(
            ["curl", "-s", "-L", "--compressed", "--max-time", str(timeout),
             "-A", ua,
             "-H", "Referer: https://guba.eastmoney.com/",
             "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
             "-H", "Accept-Language: zh-CN,zh;q=0.9,en;q=0.8",
             "-o", tmp, "-w", "%{http_code}", url],
            capture_output=True, text=True, timeout=timeout + 10)
        code = r.stdout.strip()
        if code != "200":
            return None
        body = open(tmp, "r", encoding="utf-8", errors="replace").read()
        return body
    except Exception:
        return None
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def fetch_page(page, max_retry=3):
    """抓取单页；被反爬拦截返回 ('intercepted', None)"""
    url = GUBA_LIST_URL.format(page=page)
    for i in range(max_retry):
        body = curl_get(url)
        if body is None:
            if i == max_retry - 1:
                return "error", "network"
            time.sleep(2 + random.random() * 2)
            continue
        if len(body) < VERIFY_MARKER_LEN or "身份核实" in body[:2000]:
            return "intercepted", None
        return "ok", body
    return "error", None


def crawl_window_requests(cutoff, end_dt=None, max_pages=260):
    """翻页抓取 [cutoff, end_dt] 窗口；页内最早时间 < cutoff 即停
    v3：UA 轮换 + 随机间隔 + 指数退避冷却（60s/120s/240s/300s...），单次最多 ~1 小时重试
    """
    now = end_dt or datetime.now()
    results, seen = [], set()
    stopped = False
    intercepted = False
    cooldown_waits = 0
    for page in range(1, max_pages + 1):
        status, body = fetch_page(page)
        if status == "intercepted":
            # 指数退避冷却：60/120/240/300s，最多 20 轮
            if cooldown_waits < 20:
                cooldown_waits += 1
                wait = min(60 * (2 ** (cooldown_waits - 1)), 300)
                print(f"[抓取] page {page}: 触发风控，等待 {wait}s 冷却后重试（第 {cooldown_waits} 轮）...")
                time.sleep(wait)
                status, body = fetch_page(page)
            if status == "intercepted":
                intercepted = True
                print(f"[抓取] page {page}: 冷却重试仍被拦截，放弃")
                break
        if status != "ok":
            print(f"[抓取] page {page}: 请求失败，跳过")
            continue
        rows = parse_list_rows(body)
        if not rows:
            print(f"[抓取] page {page}: 无行，停止")
            break
        page_dts, page_new = [], 0
        for r in rows:
            dt = parse_list_time(r.get("time", ""), now)
            if dt is None:
                continue
            page_dts.append(dt)
            if dt < cutoff or dt > end_dt:
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
        print(f"[抓取] page {page}: 新增 {page_new}，累计 {len(results)}，最早 {min(page_dts).strftime('%m-%d %H:%M') if page_dts else '-'}")
        time.sleep(0.6 + random.random() * 1.2)
    print(f"[抓取] 完成: {len(results)} 条, stopped={stopped}, intercepted={intercepted}")
    return results, {"stopped": stopped, "intercepted": intercepted}


if __name__ == "__main__":
    # 自测：抓最近 12 小时
    rows, meta = crawl_window_requests(datetime.now() - timedelta(hours=12), max_pages=5)
    print(json.dumps({"rows": len(rows), "meta": meta}, ensure_ascii=False))
