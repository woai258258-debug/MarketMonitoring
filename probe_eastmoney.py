# -*- coding: utf-8 -*-
"""云端探测：东财列表页 curl 直连的实际返回结构"""
import json, re, subprocess, sys, tempfile, os

def curl(url, cookie_jar=None, timeout=20):
    tmp = tempfile.mktemp(suffix=".html")
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    cmd = ["curl", "-s", "-L", "--compressed", "--max-time", str(timeout), "-A", ua,
           "-H", "Referer: https://guba.eastmoney.com/", "-o", tmp, "-w", "%{http_code}"]
    if cookie_jar:
        cmd += ["-b", cookie_jar, "-c", cookie_jar]
    cmd.append(url)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
        code = r.stdout.strip()
        body = open(tmp, "r", encoding="utf-8", errors="replace").read() if os.path.exists(tmp) else ""
        return code, body
    except Exception as e:
        return "ERR", str(e)
    finally:
        try: os.remove(tmp)
        except OSError: pass

def parse_rows(html):
    rows = []
    pattern = re.compile(r'<tr[^>]*>(.*?)</tr>', re.S)
    for tr_m in pattern.finditer(html):
        tr = tr_m.group(1)
        tds = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)
        if len(tds) < 5: continue
        clean = lambda x: re.sub(r'<[^>]+>', '', x).strip()
        rows.append(clean(tds[4]))
    return rows

def probe(label, url, jar=None):
    code, body = curl(url, jar)
    size = len(body)
    verify = "身份核实" in body[:3000] or "waf" in body[:2000].lower()
    rows = parse_rows(body)
    hot = "hotlist" in body or "hotList" in body or "hot_list" in body
    print(f"[{label}] http={code} size={size} verify={verify} rows={len(rows)} hotlist={hot}")
    if rows:
        print(f"   前5行时间: {rows[:5]}")
        print(f"   末3行时间: {rows[-3:]}")

jar = tempfile.mktemp(suffix=".jar")
print("=== A: curl 直连 f_1 ===")
probe("f1", "https://guba.eastmoney.com/list,zssh000001,f_1.html")
print("=== B: 先访问东财首页拿cookie再抓 f_1 ===")
c1, b1 = curl("https://www.eastmoney.com/", jar)
print(f"   首页 http={c1} size={len(b1)}")
probe("f1-cookie", "https://guba.eastmoney.com/list,zssh000001,f_1.html", jar)
print("=== C: curl 直连 f_2 ===")
probe("f2", "https://guba.eastmoney.com/list,zssh000001,f_2.html")
print("=== D: curl 直连 f_35（检查循环点）===")
probe("f35", "https://guba.eastmoney.com/list,zssh000001,f_35.html")
print("=== E: 手机版 H5 ===")
probe("mobile", "https://guba.eastmoney.com/m/list,zssh000001,f_1.html")
